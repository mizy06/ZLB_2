from __future__ import annotations

import inspect
import json
import unittest
from collections import Counter
from types import SimpleNamespace
from typing import Any

import httpx

from backend.app import cplus_pipeline
from backend.app.agents import (
    QWEN_LOW_REASONING_TOKEN_RESERVE,
    STRUCTURED_JSON_TIMEOUT_SECONDS,
    THEME_JSON_TIMEOUT_SECONDS,
    THEME_THINKING_TOKEN_BUDGET,
    RoleRuntime,
    ThemeNodeSpec,
    ThemePlanOutput,
    _balanced_leaf_unit_groups,
    _branch_scout,
    _theme_output_token_budget,
    build_branch_plans,
    run_branch_teams,
    synthesize_themes,
)
from backend.app.architecture_schemas import BranchPlan, ContentUnit
from backend.app.cplus_pipeline import _build_planning_projection
from backend.app.mindmap_engine.schemas import EvidenceRef, NodeCandidateIn
from backend.app.model_provider import (
    ModelProviderError,
    OpenAICompatibleClient,
)
from backend.app.schemas import ParsedDocument


# Run 1f5cf23f834a produced 136 planning units (92 text + 44 visual).
# These limits turn the observed long-document failure mode into a stable,
# provider-free regression contract.
LIVE_RUN_PLANNING_UNITS = 136
THEME_SAMPLE_LIMIT = 32
THEME_MIN_TEXT_SAMPLES = 24
THEME_MAX_VISUAL_SAMPLES = 8
THEME_TOKEN_HARD_CAP = 5000
BRANCH_TOKEN_HARD_CAP = 7000
GLOBAL_RETRY_WINDOW_SECONDS = 3 * 180


def _document() -> ParsedDocument:
    return ParsedDocument(
        document_id="long-document",
        filename="long-course.pdf",
        file_type="pdf",
        title="长课件知识体系",
        blocks=[],
    )


def _text_unit(
    index: int,
    *,
    importance: float = 0.7,
    page: int | None = None,
    chapter: int | None = None,
) -> ContentUnit:
    page_number = page if page is not None else index + 1
    chapter_number = (
        chapter if chapter is not None else (page_number - 1) // 12 + 1
    )
    source = f"第{page_number}页第{chapter_number}章知识点{index}"
    return ContentUnit(
        id=f"text-{index:03d}",
        document_id="long-document",
        kind="text",
        importance=importance,
        text=source,
        evidence_excerpt=source,
        heading_path=[f"第{chapter_number}章"],
        page=page_number,
    )


def _visual_unit(index: int, *, importance: float = 0.99) -> ContentUnit:
    source = f"第{index + 1}页视觉知识{index}"
    return ContentUnit(
        id=f"visual-{index:03d}",
        document_id="long-document",
        kind="visual",
        importance=importance,
        status="uncovered",
        evidence_excerpt=source,
        page=index + 1,
        asset_id=f"asset-{index:03d}",
        visual_kind="diagram",
        visual_action="standalone_node",
        summary=source,
        knowledge_score=0.9,
    )


def _seed_candidate(unit: ContentUnit, index: int) -> NodeCandidateIn:
    return NodeCandidateIn(
        temp_id=f"direct:{unit.id}",
        name=f"第{unit.page}页知识点{index}",
        type="concept",
        role="principle",
        definition=unit.text,
        origin="explicit",
        confidence=0.95,
        optional=True,
        evidence=[
            EvidenceRef(
                unit_id=unit.id,
                excerpt=unit.evidence_excerpt,
                page=unit.page,
            )
        ],
        support_unit_ids=[unit.id],
    )


class _CapturingThemeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def complete_json(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        prompt = json.loads(kwargs["user_prompt"])
        unit_ids = [
            item["unit_id"] for item in prompt["content_units"]
        ]
        return {
            "root_candidates": [
                {
                    "temp_id": "root",
                    "name": "长课件知识体系",
                    "support_unit_ids": unit_ids,
                }
            ],
            "branch_topics": [
                {
                    "temp_id": "branch",
                    "name": "长课件主题脉络",
                    "support_unit_ids": unit_ids,
                }
            ],
        }


class _OmittingThemeClient:
    async def complete_json(self, **kwargs: Any) -> dict[str, Any]:
        prompt = json.loads(kwargs["user_prompt"])
        unit_ids = [
            item["unit_id"] for item in prompt["content_units"]
        ]
        retained_ids = unit_ids[: max(1, len(unit_ids) * 3 // 4)]
        return {
            "root_candidates": [
                {
                    "temp_id": "root",
                    "name": "长课件知识体系",
                    "support_unit_ids": unit_ids,
                }
            ],
            "branch_topics": [
                {
                    "temp_id": "branch",
                    "name": "前段课程主题",
                    "support_unit_ids": retained_ids,
                }
            ],
        }


class _MultipleRootThemeClient(_CapturingThemeClient):
    async def complete_json(self, **kwargs: Any) -> dict[str, Any]:
        payload = await super().complete_json(**kwargs)
        payload["root_candidates"] = [
            {
                "temp_id": "model-root-1",
                "name": "模型概括根一",
                "support_unit_ids": [],
                "confidence": 0.91,
            },
            {
                "temp_id": "model-root-2",
                "name": "模型概括根二",
                "support_unit_ids": [],
                "confidence": 0.9,
            },
        ]
        return payload


class _CapturingBranchClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def complete_json(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        prompt = json.loads(kwargs["user_prompt"])
        unit = prompt["content_units"][0]
        return {
            "nodes": [
                {
                    "temp_id": "node",
                    "name": "可审计知识点",
                    "definition": unit["text"],
                    "origin": "explicit",
                    "confidence": 0.9,
                    "evidence": [
                        {
                            "unit_id": unit["unit_id"],
                            "excerpt": unit["text"],
                        }
                    ],
                    "support_unit_ids": [unit["unit_id"]],
                }
            ],
            "cross_links": [],
        }


class _FailingBudgetClient:
    default_timeout_seconds = 180
    default_max_attempts = 3

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def complete_json(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        raise ModelProviderError("synthetic timeout without waiting")


class _AlwaysTimeoutHttpClient:
    def __init__(self) -> None:
        self.calls = 0

    async def post(self, url: str, **_kwargs: Any) -> httpx.Response:
        self.calls += 1
        raise httpx.ReadTimeout(
            "synthetic timeout",
            request=httpx.Request("POST", url),
        )


class _RejectingBranchClient:
    def __init__(self) -> None:
        self.calls = 0

    async def complete_json(self, **_kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        raise AssertionError(
            "seed-covered planning projections must bypass branch extraction"
        )


def _runtime(client: Any, *, model: str = "fake-model") -> RoleRuntime:
    return RoleRuntime(
        provider="fake",
        model=model,
        client=client,
        available=True,
    )


def _effective_retry_window_seconds(
    call: dict[str, Any],
    client: _FailingBudgetClient,
) -> float:
    policy = call.get("call_policy") or call.get("retry_policy") or {}
    attempts = call.get(
        "max_attempts",
        call.get(
            "attempts",
            policy.get("max_attempts", client.default_max_attempts),
        ),
    )
    timeout = call.get(
        "timeout_seconds",
        call.get(
            "request_timeout_seconds",
            policy.get(
                "timeout_seconds",
                client.default_timeout_seconds,
            ),
        ),
    )
    stage_budget = next(
        (
            value
            for value in (
                call.get("stage_budget_seconds"),
                call.get("total_timeout_seconds"),
                call.get("total_budget_seconds"),
                policy.get("stage_budget_seconds"),
                policy.get("total_timeout_seconds"),
            )
            if value is not None
        ),
        None,
    )
    retry_window = float(attempts) * float(timeout)
    if stage_budget is not None:
        retry_window = min(retry_window, float(stage_budget))
    return retry_window


class LongDocumentPerformanceTDDTests(unittest.IsolatedAsyncioTestCase):
    def test_136_planning_units_are_partitioned_once_into_at_most_24_small_leaves(
        self,
    ) -> None:
        units = [_text_unit(index) for index in range(LIVE_RUN_PLANNING_UNITS)]

        # This reproduces the live shape: seven retained themes cover 64
        # units, an eighth covers 8, and 64 unclaimed units are merged into
        # that eighth theme.  The current per-root allocation makes the
        # resulting 72-unit branch split into exactly 3 x 24-unit leaves.
        topic_sizes = [10, 9, 9, 9, 9, 9, 9, 8]
        topics: list[ThemeNodeSpec] = []
        cursor = 0
        for index, size in enumerate(topic_sizes):
            support = [
                unit.id for unit in units[cursor : cursor + size]
            ]
            cursor += size
            topics.append(
                ThemeNodeSpec(
                    temp_id=f"theme-{index}",
                    name=f"课程主题{index + 1}",
                    support_unit_ids=support,
                    confidence=0.95 - index * 0.01,
                )
            )

        plans = build_branch_plans(
            ThemePlanOutput(
                root_candidates=[
                    ThemeNodeSpec(
                        temp_id="root",
                        name="长课件知识体系",
                        support_unit_ids=[unit.id for unit in units],
                    )
                ],
                branch_topics=topics,
            ),
            units,
            max_units_per_leaf=8,
        )
        leaves = [plan for plan in plans if plan.leaf]
        occurrences = Counter(
            unit_id
            for leaf in leaves
            for unit_id in leaf.unit_ids
        )
        planning_ids = {unit.id for unit in units}

        with self.subTest("global leaf cap"):
            self.assertLessEqual(len(leaves), 24)
        with self.subTest("complete leaf coverage"):
            self.assertEqual(set(occurrences), planning_ids)
        with self.subTest("exactly once in leaf layer"):
            self.assertTrue(
                all(occurrences[unit_id] == 1 for unit_id in planning_ids)
            )
        with self.subTest("bounded leaf input"):
            self.assertLessEqual(
                max(len(leaf.unit_ids) for leaf in leaves),
                8,
                msg=(
                    "max_units_per_leaf=8 must remain a hard leaf invariant; "
                    f"observed sizes: {[len(leaf.unit_ids) for leaf in leaves]}"
                ),
            )

    def test_leaf_planner_rejects_a_mathematically_impossible_capacity(
        self,
    ) -> None:
        units = [_text_unit(index) for index in range(193)]
        theme = ThemeNodeSpec(
            temp_id="oversized",
            name="超长课程主题",
            support_unit_ids=[unit.id for unit in units],
        )

        with self.assertRaisesRegex(ValueError, "超过全局上限"):
            build_branch_plans(
                ThemePlanOutput(
                    root_candidates=[],
                    branch_topics=[theme],
                ),
                units,
                max_units_per_leaf=8,
            )

    def test_leaf_planner_consolidates_weak_roots_when_global_capacity_fits(
        self,
    ) -> None:
        units = [
            _text_unit(index, page=index + 1)
            for index in range(91)
        ]
        topic_sizes = [23, 1, 1, 1, 1, 1, 1, 62]
        topics: list[ThemeNodeSpec] = []
        cursor = 0
        for index, topic_size in enumerate(topic_sizes):
            topic_units = units[cursor : cursor + topic_size]
            topics.append(
                ThemeNodeSpec(
                    temp_id=f"topic-{index}",
                    name=f"通用主题{index + 1}",
                    support_unit_ids=[
                        unit.id for unit in topic_units
                    ],
                    confidence=0.95 - index * 0.05,
                )
            )
            cursor += topic_size

        node_weights = {unit.id: 1 for unit in units}
        leading_weights = [
            *([4, 5, 5, 5, 5] * 3),
            *([6, 6, 6, 6] * 2),
        ]
        trailing_weights = [
            *([4, 5, 5, 5, 5] * 6),
            *([6, 6, 6, 6] * 8),
        ]
        for unit, weight in zip(units[:23], leading_weights):
            node_weights[unit.id] = weight
        for unit, weight in zip(units[29:], trailing_weights):
            node_weights[unit.id] = weight

        naive_leaf_count = sum(
            len(
                _balanced_leaf_unit_groups(
                    topic.support_unit_ids,
                    {unit.id: unit for unit in units},
                    8,
                    unit_node_weights=node_weights,
                    max_node_weight_per_leaf=24,
                )
            )
            for topic in topics
        )
        self.assertEqual(naive_leaf_count, 25)

        plans = build_branch_plans(
            ThemePlanOutput(
                root_candidates=[],
                branch_topics=topics,
            ),
            units,
            max_units_per_leaf=8,
            unit_node_weights=node_weights,
            max_node_weight_per_leaf=24,
        )
        roots = [plan for plan in plans if plan.depth == 1]
        leaves = [plan for plan in plans if plan.leaf]
        occurrences = Counter(
            unit_id
            for leaf in leaves
            for unit_id in leaf.unit_ids
        )

        self.assertEqual(len(roots), 7)
        self.assertLessEqual(len(leaves), 24)
        self.assertEqual(set(occurrences), {unit.id for unit in units})
        self.assertTrue(
            all(count == 1 for count in occurrences.values())
        )
        self.assertTrue(
            all(len(leaf.unit_ids) <= 8 for leaf in leaves)
        )
        self.assertTrue(
            all(
                sum(node_weights[unit_id] for unit_id in leaf.unit_ids)
                <= 24
                for leaf in leaves
            )
        )
        self.assertEqual(
            [
                unit_id
                for leaf in leaves
                for unit_id in leaf.unit_ids
            ],
            [unit.id for unit in units],
        )

    def test_seed_covered_page_nodes_project_below_global_leaf_capacity(
        self,
    ) -> None:
        atomic_units = [
            _text_unit(
                index,
                page=index % 92 + 1,
                chapter=(index % 92) // 12 + 1,
            )
            for index in range(500)
        ]
        candidates = [
            _seed_candidate(unit, index)
            for index, unit in enumerate(atomic_units)
        ]
        visual_units = [_visual_unit(index) for index in range(44)]

        planning_units, seed_projection = _build_planning_projection(
            [*atomic_units, *visual_units],
            candidates,
        )
        plans = build_branch_plans(
            ThemePlanOutput(
                root_candidates=[],
                branch_topics=[
                    ThemeNodeSpec(
                        temp_id="projected-course",
                        name="多学科课程知识体系",
                        support_unit_ids=[
                            unit.id for unit in planning_units
                        ],
                    )
                ],
            ),
            planning_units,
            max_units_per_leaf=8,
        )
        leaves = [plan for plan in plans if plan.leaf]

        self.assertEqual(len(planning_units), 92 + 44)
        self.assertEqual(set(seed_projection), {unit.id for unit in atomic_units})
        self.assertLessEqual(len(leaves), 24)
        self.assertTrue(
            all(len(leaf.unit_ids) <= 8 for leaf in leaves)
        )
        self.assertEqual(
            {
                unit_id
                for leaf in leaves
                for unit_id in leaf.unit_ids
            },
            {unit.id for unit in planning_units},
        )

    def test_projected_page_leaves_respect_direct_node_weight(self) -> None:
        units = [
            _text_unit(index, page=index + 1)
            for index in range(92)
        ]
        node_weights = {
            unit.id: 5 if index < 37 else 4
            for index, unit in enumerate(units)
        }

        plans = build_branch_plans(
            ThemePlanOutput(
                root_candidates=[],
                branch_topics=[
                    ThemeNodeSpec(
                        temp_id="weighted-course",
                        name="长课件知识体系",
                        support_unit_ids=[unit.id for unit in units],
                    )
                ],
            ),
            units,
            max_units_per_leaf=8,
            unit_node_weights=node_weights,
            max_node_weight_per_leaf=24,
        )
        leaves = [plan for plan in plans if plan.leaf]
        occurrences = Counter(
            unit_id
            for leaf in leaves
            for unit_id in leaf.unit_ids
        )

        self.assertLessEqual(len(leaves), 24)
        self.assertEqual(set(occurrences), {unit.id for unit in units})
        self.assertTrue(
            all(count == 1 for count in occurrences.values())
        )
        self.assertTrue(
            all(len(leaf.unit_ids) <= 8 for leaf in leaves)
        )
        self.assertTrue(
            all(
                sum(node_weights[unit_id] for unit_id in leaf.unit_ids)
                <= 24
                for leaf in leaves
            ),
            msg=[
                sum(node_weights[unit_id] for unit_id in leaf.unit_ids)
                for leaf in leaves
            ],
        )

    def test_strict_page_projection_uses_seed_count_as_leaf_weight(
        self,
    ) -> None:
        atomic_units = [
            _text_unit(
                index,
                page=index % 92 + 1,
                chapter=(index % 92) // 12 + 1,
            )
            for index in range(405)
        ]
        candidates = [
            _seed_candidate(unit, index)
            for index, unit in enumerate(atomic_units)
        ]
        visual_units = [_visual_unit(index) for index in range(44)]
        planning_units, seed_projection = _build_planning_projection(
            [*atomic_units, *visual_units],
            candidates,
        )

        node_weights = cplus_pipeline._planning_unit_node_weights(
            planning_units,
            candidates,
            seed_projection,
        )
        plans = build_branch_plans(
            ThemePlanOutput(
                root_candidates=[],
                branch_topics=[
                    ThemeNodeSpec(
                        temp_id="strict-page-course",
                        name="长课件知识体系",
                        support_unit_ids=[
                            unit.id for unit in planning_units
                        ],
                    )
                ],
            ),
            planning_units,
            max_units_per_leaf=8,
            unit_node_weights=node_weights,
            max_node_weight_per_leaf=24,
        )
        leaves = [plan for plan in plans if plan.leaf]

        self.assertEqual(len(planning_units), 92 + 44)
        self.assertEqual(sum(node_weights.values()), 405 + 44 * 2)
        self.assertLessEqual(len(leaves), 24)
        self.assertTrue(
            all(
                sum(node_weights[unit_id] for unit_id in leaf.unit_ids)
                <= 24
                for leaf in leaves
            )
        )
        self.assertEqual(
            {
                unit_id
                for leaf in leaves
                for unit_id in leaf.unit_ids
            },
            {unit.id for unit in planning_units},
        )

    async def test_projected_seed_nodes_bypass_branch_llm_without_coverage_loss(
        self,
    ) -> None:
        atomic_units = [
            _text_unit(
                index,
                page=index % 92 + 1,
                chapter=(index % 92) // 12 + 1,
            )
            for index in range(500)
        ]
        candidates = [
            _seed_candidate(unit, index)
            for index, unit in enumerate(atomic_units)
        ]
        planning_units, seed_projection = _build_planning_projection(
            atomic_units,
            candidates,
        )
        plans = build_branch_plans(
            ThemePlanOutput(
                root_candidates=[],
                branch_topics=[
                    ThemeNodeSpec(
                        temp_id="projected-course",
                        name="多学科课程知识体系",
                        support_unit_ids=[
                            unit.id for unit in planning_units
                        ],
                    )
                ],
            ),
            planning_units,
            max_units_per_leaf=8,
        )
        client = _RejectingBranchClient()

        results = await run_branch_teams(
            plans,
            planning_units,
            [],
            _runtime(client),
            seed_nodes=candidates,
            seed_unit_projection=seed_projection,
        )
        explicit_nodes = [
            node
            for result in results
            for node in result.nodes
            if node.origin == "explicit"
        ]
        evidence_occurrences = Counter(
            evidence.unit_id
            for node in explicit_nodes
            for evidence in node.evidence
            if evidence.unit_id
        )
        parent_by_child = {
            candidate.child: candidate
            for result in results
            for candidate in result.parent_candidates
        }

        self.assertEqual(client.calls, 0)
        self.assertEqual(len(explicit_nodes), len(candidates))
        self.assertEqual(
            set(evidence_occurrences),
            {unit.id for unit in atomic_units},
        )
        self.assertTrue(
            all(count == 1 for count in evidence_occurrences.values())
        )
        self.assertTrue(
            all(
                (
                    parent := parent_by_child.get(node.temp_id)
                ) is not None
                and {
                    evidence.unit_id
                    for evidence in parent.evidence
                    if evidence.unit_id
                }
                & {
                    evidence.unit_id
                    for evidence in node.evidence
                    if evidence.unit_id
                }
                for node in explicit_nodes
            ),
            msg=(
                "projected branch topics must retain each routed seed's "
                "original support so direct parent edges keep evidence"
            ),
        )

    async def test_seed_node_spanning_multiple_leaves_is_routed_once(
        self,
    ) -> None:
        atomic_units = [
            _text_unit(index, page=index + 1)
            for index in range(16)
        ]
        candidates = [
            _seed_candidate(unit, index)
            for index, unit in enumerate(atomic_units)
        ]
        candidates.append(
            NodeCandidateIn(
                temp_id="cross-page",
                name="跨页共同结论",
                definition="两个来源单元共同支持同一原子结论。",
                origin="explicit",
                confidence=0.94,
                optional=True,
                evidence=[
                    EvidenceRef(
                        unit_id=atomic_units[index].id,
                        excerpt=atomic_units[index].evidence_excerpt,
                        page=atomic_units[index].page,
                    )
                    for index in (0, 8)
                ],
                support_unit_ids=[
                    atomic_units[0].id,
                    atomic_units[8].id,
                ],
            )
        )
        planning_units, seed_projection = _build_planning_projection(
            atomic_units,
            candidates,
        )
        plans = build_branch_plans(
            ThemePlanOutput(
                root_candidates=[],
                branch_topics=[
                    ThemeNodeSpec(
                        temp_id="course",
                        name="长课件知识体系",
                        support_unit_ids=[
                            unit.id for unit in planning_units
                        ],
                    )
                ],
            ),
            planning_units,
            max_units_per_leaf=8,
        )
        client = _RejectingBranchClient()

        results = await run_branch_teams(
            plans,
            planning_units,
            [],
            _runtime(client),
            seed_nodes=candidates,
            seed_unit_projection=seed_projection,
        )
        routed = [
            node
            for result in results
            for node in result.nodes
            if node.name == "跨页共同结论"
        ]

        self.assertEqual(client.calls, 0)
        self.assertEqual(len(routed), 1)

    async def test_theme_sample_is_stratified_across_text_visual_page_and_chapter(
        self,
    ) -> None:
        text_units = [
            _text_unit(
                index,
                importance=0.8 - index / 10_000,
                page=index + 1,
            )
            for index in range(92)
        ]
        visual_units = [_visual_unit(index) for index in range(44)]
        client = _CapturingThemeClient()

        await synthesize_themes(
            _document(),
            [*text_units, *visual_units],
            _runtime(client, model="fake-theme"),
        )

        prompt = json.loads(client.calls[0]["user_prompt"])
        sampled = prompt["content_units"]
        text_sample = [
            item for item in sampled if item["kind"] == "text"
        ]
        visual_sample = [
            item for item in sampled if item["kind"] == "visual"
        ]
        sampled_ids = {item["unit_id"] for item in text_sample}
        text_by_id = {unit.id: unit for unit in text_units}
        sampled_pages = {
            text_by_id[unit_id].page for unit_id in sampled_ids
        }
        sampled_chapters = {
            text_by_id[unit_id].heading_path[0]
            for unit_id in sampled_ids
        }
        expected_chapters = {
            unit.heading_path[0] for unit in text_units
        }

        with self.subTest("sample limit"):
            self.assertLessEqual(len(sampled), THEME_SAMPLE_LIMIT)
        with self.subTest("text quota"):
            self.assertGreaterEqual(
                len(text_sample),
                THEME_MIN_TEXT_SAMPLES,
                msg=(
                    "44 high-importance visuals must not reduce the "
                    f"92-page text spine to {len(text_sample)} samples"
                ),
            )
        with self.subTest("visual quota"):
            self.assertLessEqual(
                len(visual_sample),
                THEME_MAX_VISUAL_SAMPLES,
            )
        with self.subTest("chapter coverage"):
            self.assertEqual(sampled_chapters, expected_chapters)
        with self.subTest("document tail coverage"):
            self.assertGreaterEqual(max(sampled_pages), 89)
        with self.subTest("source location is visible to the model"):
            self.assertTrue(
                all(
                    "page" in item and "slide" in item
                    for item in sampled
                )
            )
        with self.subTest("bounded serialized input"):
            self.assertLessEqual(
                len(client.calls[0]["user_prompt"]),
                12_000,
            )
            self.assertTrue(
                all(len(item["summary"]) <= 280 for item in sampled)
            )

    async def test_theme_root_supports_all_planning_units_not_only_sample(
        self,
    ) -> None:
        units = [
            _text_unit(index)
            for index in range(LIVE_RUN_PLANNING_UNITS)
        ]
        client = _CapturingThemeClient()

        plan, used_model, warnings = await synthesize_themes(
            _document(),
            units,
            _runtime(client, model="fake-theme"),
        )

        self.assertTrue(used_model)
        self.assertEqual(warnings, [])
        self.assertEqual(
            plan.root_candidates[0].support_unit_ids,
            [unit.id for unit in units],
            msg=(
                "the document root must support the full planning ledger so "
                "every first-level topic has auditable structural evidence"
            ),
        )

    async def test_non_generic_document_title_is_the_only_root_candidate(
        self,
    ) -> None:
        units = [_text_unit(index) for index in range(12)]

        plan, used_model, warnings = await synthesize_themes(
            _document(),
            units,
            _runtime(_MultipleRootThemeClient(), model="fake-theme"),
        )

        self.assertTrue(used_model)
        self.assertEqual(warnings, [])
        self.assertEqual(len(plan.root_candidates), 1)
        self.assertEqual(
            plan.root_candidates[0].name,
            _document().title,
        )
        self.assertEqual(
            plan.root_candidates[0].support_unit_ids,
            [unit.id for unit in units],
        )

    async def test_chapter_document_title_is_the_only_root_candidate(
        self,
    ) -> None:
        units = [_text_unit(index) for index in range(12)]
        document = _document().model_copy(
            update={"title": "第28章 原子中的电子"}
        )

        plan, used_model, warnings = await synthesize_themes(
            document,
            units,
            _runtime(_MultipleRootThemeClient(), model="fake-theme"),
        )

        self.assertTrue(used_model)
        self.assertEqual(warnings, [])
        self.assertEqual(len(plan.root_candidates), 1)
        self.assertEqual(
            plan.root_candidates[0].name,
            document.title,
        )

    async def test_theme_plan_routes_omitted_units_without_discarding_taxonomy(
        self,
    ) -> None:
        units = [_text_unit(index) for index in range(80)]

        plan, used_model, warnings = await synthesize_themes(
            _document(),
            units,
            _runtime(_OmittingThemeClient(), model="fake-theme"),
        )

        planned_ids = {
            unit_id
            for branch in plan.branch_topics
            for unit_id in branch.support_unit_ids
        }
        self.assertTrue(used_model)
        self.assertNotEqual(planned_ids, {unit.id for unit in units})
        self.assertTrue(
            any("确定性分支规划" in warning for warning in warnings)
        )

        plans = build_branch_plans(plan, units)
        occurrences = Counter(
            unit_id
            for branch in plans
            if branch.leaf
            for unit_id in branch.unit_ids
        )
        self.assertEqual(set(occurrences), {unit.id for unit in units})
        self.assertTrue(all(count == 1 for count in occurrences.values()))

    async def test_theme_output_tokens_scale_with_expected_plan_size_and_are_capped(
        self,
    ) -> None:
        client = _CapturingThemeClient()
        runtime = _runtime(client, model="fake-theme")

        await synthesize_themes(
            _document(),
            [_text_unit(index) for index in range(8)],
            runtime,
        )
        await synthesize_themes(
            _document(),
            [_text_unit(index) for index in range(80)],
            runtime,
        )
        small_tokens = client.calls[0]["max_tokens"]
        large_tokens = client.calls[1]["max_tokens"]

        self.assertTrue(
            0 < small_tokens < large_tokens <= THEME_TOKEN_HARD_CAP,
            msg=(
                "theme max_tokens must scale with the expected number of "
                "root/branch records and remain capped; observed "
                f"small={small_tokens}, large={large_tokens}"
            ),
        )

    def test_full_theme_sample_reserves_eight_branch_records(self) -> None:
        minimum_visible_budget = (
            640
            + 8 * 320
            + THEME_SAMPLE_LIMIT * 24
        )

        self.assertGreaterEqual(
            _theme_output_token_budget(THEME_SAMPLE_LIMIT),
            minimum_visible_budget,
        )

    async def test_branch_output_tokens_scale_with_coverage_budget_and_are_capped(
        self,
    ) -> None:
        client = _CapturingBranchClient()
        runtime = _runtime(client, model="fake-branch")
        small_units = [_text_unit(index) for index in range(2)]
        large_units = [_text_unit(index) for index in range(8)]

        await _branch_scout(
            {
                "branch": BranchPlan(
                    id="small",
                    label="小分支",
                    unit_ids=[unit.id for unit in small_units],
                    coverage_budget=3,
                ),
                "units": small_units,
                "chunks": [],
                "runtime": runtime,
                "warnings": [],
            }
        )
        await _branch_scout(
            {
                "branch": BranchPlan(
                    id="large",
                    label="大分支",
                    unit_ids=[unit.id for unit in large_units],
                    coverage_budget=24,
                ),
                "units": large_units,
                "chunks": [],
                "runtime": runtime,
                "warnings": [],
            }
        )
        small_tokens = client.calls[0]["max_tokens"]
        large_tokens = client.calls[1]["max_tokens"]

        self.assertTrue(
            0 < small_tokens < large_tokens <= BRANCH_TOKEN_HARD_CAP,
            msg=(
                "branch max_tokens must scale with BranchPlan.coverage_budget "
                "and remain capped; observed "
                f"small={small_tokens}, large={large_tokens}"
            ),
        )

    async def test_structured_theme_and_branch_calls_bound_qwen_reasoning(self):
        theme_client = _CapturingThemeClient()
        branch_client = _CapturingBranchClient()
        units = [_text_unit(index) for index in range(4)]

        await synthesize_themes(
            _document(),
            units,
            _runtime(theme_client, model="qwen3.8-max-preview"),
        )
        await _branch_scout(
            {
                "branch": BranchPlan(
                    id="bounded-reasoning",
                    label="受控推理分支",
                    unit_ids=[unit.id for unit in units],
                    coverage_budget=8,
                ),
                "units": units,
                "chunks": [],
                "runtime": _runtime(
                    branch_client,
                    model="qwen3.8-max-preview",
                ),
                "warnings": [],
            }
        )

        self.assertEqual(
            theme_client.calls[0].get("thinking_budget"),
            THEME_THINKING_TOKEN_BUDGET,
        )
        self.assertNotIn("reasoning_effort", theme_client.calls[0])
        self.assertEqual(
            branch_client.calls[0].get("thinking_budget"),
            QWEN_LOW_REASONING_TOKEN_RESERVE,
            msg=(
                "branch extraction timed out at 180 seconds with the "
                "provider's implicit thinking budget; every deterministic "
                "JSON extraction call must explicitly bound reasoning"
            ),
        )
        self.assertNotIn("reasoning_effort", branch_client.calls[0])
        prompt_unit = json.loads(
            branch_client.calls[0]["user_prompt"]
        )["content_units"][0]
        self.assertFalse(
            any(value is None for value in prompt_unit.values()),
            msg=f"branch prompt retained null fields: {prompt_unit}",
        )
        self.assertNotIn("asset_id", prompt_unit)
        self.assertNotIn("visual_kind", prompt_unit)
        self.assertNotIn("visual_action", prompt_unit)
        self.assertNotIn("knowledge_claims", prompt_unit)
        self.assertNotIn("nearby_text_ids", prompt_unit)
        self.assertNotIn("bbox", prompt_unit)
        self.assertNotIn("parent_asset_id", prompt_unit)
        for stage, call in (
            ("themes", theme_client.calls[0]),
            ("branch", branch_client.calls[0]),
        ):
            with self.subTest(stage=stage):
                answer_budget = call["max_tokens"]
                reasoning_reserve = (
                    THEME_THINKING_TOKEN_BUDGET
                    if stage == "themes"
                    else QWEN_LOW_REASONING_TOKEN_RESERVE
                )
                self.assertEqual(
                    call.get("max_completion_tokens"),
                    answer_budget + reasoning_reserve,
                    msg=(
                        f"{stage} must bound thinking plus the existing "
                        "visible JSON budget without shrinking the answer"
                    ),
                )
                self.assertEqual(
                    call.get("timeout_seconds"),
                    (
                        THEME_JSON_TIMEOUT_SECONDS
                        if stage == "themes"
                        else STRUCTURED_JSON_TIMEOUT_SECONDS
                    ),
                )
                self.assertEqual(call.get("max_attempts"), 1)

    async def test_fallback_safe_theme_and_branch_calls_bound_total_retry_time(
        self,
    ) -> None:
        client = _FailingBudgetClient()
        runtime = _runtime(client)
        units = [_text_unit(index) for index in range(2)]

        theme_plan, used_model, _warnings = await synthesize_themes(
            _document(),
            units,
            runtime,
        )
        branch = BranchPlan(
            id="fallback-branch",
            label="确定性兜底分支",
            unit_ids=[unit.id for unit in units],
            coverage_budget=3,
        )
        branch_state = await _branch_scout(
            {
                "branch": branch,
                "units": units,
                "chunks": [],
                "runtime": runtime,
                "warnings": [],
            }
        )

        self.assertFalse(used_model)
        self.assertTrue(theme_plan.branch_topics)
        self.assertFalse(branch_state["used_model"])
        self.assertEqual(len(client.calls), 2)
        for stage, call in zip(("themes", "branch"), client.calls):
            with self.subTest(stage=stage):
                self.assertLessEqual(
                    _effective_retry_window_seconds(call, client),
                    GLOBAL_RETRY_WINDOW_SECONDS - 1,
                    msg=(
                        f"{stage} has a deterministic fallback and must not "
                        "inherit the global 3 x 180 second retry window; "
                        f"call controls were {sorted(call)}"
                    ),
                )

    def test_complete_json_exposes_a_per_call_attempt_or_stage_budget_control(
        self,
    ) -> None:
        signature = inspect.signature(
            OpenAICompatibleClient.complete_json
        )
        parameters = signature.parameters
        accepted_controls = {
            "max_attempts",
            "attempts",
            "stage_budget_seconds",
            "total_timeout_seconds",
            "total_budget_seconds",
            "call_policy",
            "retry_policy",
        }
        accepts_arbitrary_keywords = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )

        self.assertTrue(
            accepts_arbitrary_keywords
            or bool(accepted_controls & set(parameters)),
            msg=(
                "complete_json needs an explicit per-call attempt override "
                "or total stage budget so fallback-safe stages do not "
                "inherit the global retry window"
            ),
        )

    async def test_per_call_attempt_override_does_not_change_the_client_default(
        self,
    ) -> None:
        http_client = _AlwaysTimeoutHttpClient()
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        settings = SimpleNamespace(
            provider_max_attempts=3,
            provider_retry_delay_cap_seconds=30,
            provider_circuit_cooldown_seconds=120,
            provider_concurrency=1,
            provider_timeout_seconds=180,
            provider_retry_base_seconds=0,
        )
        client = OpenAICompatibleClient(
            settings=settings,
            api_key="fake-key",
            base_url="https://timeout.invalid/v1",
            provider_name="timeout-probe",
            api_key_env_name="FAKE_KEY",
            temperature=0,
            http_client=http_client,
            max_attempts=3,
            retry_sleep=fake_sleep,
        )

        with self.assertRaisesRegex(ModelProviderError, "已尝试 1 次"):
            await client.complete_json(
                model="fake-model",
                system_prompt="system",
                user_prompt="fallback-safe stage",
                max_attempts=1,
            )
        self.assertEqual(http_client.calls, 1)
        self.assertEqual(sleeps, [])

        with self.assertRaisesRegex(ModelProviderError, "已尝试 3 次"):
            await client.complete_json(
                model="fake-model",
                system_prompt="system",
                user_prompt="ordinary stage",
            )
        self.assertEqual(http_client.calls, 4)
        self.assertEqual(sleeps, [0, 0])


if __name__ == "__main__":
    unittest.main()
