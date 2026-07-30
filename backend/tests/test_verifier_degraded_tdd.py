from __future__ import annotations

import json
import unittest

from backend.app import cplus_pipeline
from backend.app.agents import (
    QWEN_LOW_REASONING_TOKEN_RESERVE,
    VERIFIER_JSON_TIMEOUT_SECONDS,
    RoleRuntime,
    verify_parent_candidates,
)
from backend.app.mindmap_engine.schemas import (
    EvidenceRef,
    NormalizedGraph,
    NormalizedNode,
    NormalizedParentCandidate,
)
def _node(
    node_id: str,
    *,
    role: str = "concept",
    origin: str = "explicit",
) -> NormalizedNode:
    unit_id = f"unit:{node_id}"
    return NormalizedNode(
        id=node_id,
        temp_ids=[node_id],
        name=f"节点{node_id}",
        type=role,
        role=role,
        definition=f"节点{node_id}定义",
        aliases=[],
        origin=origin,
        branch_id="branch-1",
        confidence=0.9,
        optional=False,
        activation_score=0.9,
        activation_cost=0,
        is_root_candidate=False,
        evidence=[
            EvidenceRef(
                unit_id=unit_id,
                chunk_id=unit_id,
                excerpt=f"节点{node_id}原文",
            )
        ],
        support_unit_ids=[unit_id],
        media_asset_ids=[],
    )


def _graph(
    child_ids: list[str],
    *,
    parents_per_child: int = 1,
) -> NormalizedGraph:
    parents = [
        _node(
            f"parent-{index}",
            role="branch_topic",
            origin="structural",
        ).model_copy(update={"branch_id": "branch-parent"})
        for index in range(parents_per_child)
    ]
    children = [_node(child_id) for child_id in child_ids]
    candidates = [
        NormalizedParentCandidate(
            parent_id=parent.id,
            child_id=child.id,
            score=0.9 - parent_index * 0.1,
            classification="direct_parent",
            evidence=[
                EvidenceRef(
                    unit_id=f"unit:{child.id}",
                    chunk_id=f"unit:{child.id}",
                    excerpt=f"节点{child.id}原文",
                )
            ],
        )
        for child in children
        for parent_index, parent in enumerate(parents)
    ]
    return NormalizedGraph(
        document_id="doc",
        document_title="校验降级测试",
        nodes=[*parents, *children],
        parent_candidates=candidates,
        cross_links=[],
    )


class _VerifierClient:
    def __init__(
        self,
        *,
        classification: str = "direct_parent",
        fail_children: set[str] | None = None,
        malformed_children: set[str] | None = None,
        wrong_id_children: set[str] | None = None,
    ):
        self.classification = classification
        self.fail_children = fail_children or set()
        self.malformed_children = malformed_children or set()
        self.wrong_id_children = wrong_id_children or set()
        self.calls: list[list[str]] = []
        self.call_kwargs: list[dict] = []

    async def complete_json(self, **kwargs):
        payload = json.loads(kwargs["user_prompt"])
        child_ids = [
            item["child"]["id"] for item in payload["children"]
        ]
        self.calls.append(child_ids)
        self.call_kwargs.append(kwargs)
        children = []
        for item in payload["children"]:
            child_id = item["child"]["id"]
            if child_id in self.fail_children:
                continue
            if child_id in self.malformed_children:
                children.append(
                    {
                        "child_id": child_id,
                        "evaluations": "not-a-list",
                    }
                )
                continue
            children.append(
                {
                    "child_id": (
                        f"unknown:{child_id}"
                        if child_id in self.wrong_id_children
                        else child_id
                    ),
                    "evaluations": [
                        {
                            "parent_id": candidate["parent"]["id"],
                            "classification": self.classification,
                            "verifier_score": 0.91,
                            "reason": "测试校验结论",
                        }
                        for candidate in item["candidates"]
                    ],
                }
            )
        return {"children": children}


class VerifierRuntimeDegradedTDDTests(unittest.IsolatedAsyncioTestCase):
    def _components(
        self,
        *,
        mode,
        verifier,
        second_verifier,
        arbiter,
        stats,
    ) -> list[str]:
        return cplus_pipeline.verifier_degraded_components(
            [],
            mode=mode,
            verifier=verifier,
            second_verifier=second_verifier,
            arbiter=arbiter,
            stats=stats,
        )

    async def test_standard_mixed_runtime_fallback_is_structured_partial_degradation(
        self,
    ):
        client = _VerifierClient(fail_children={"child-2"})
        runtime = RoleRuntime("qwen", "test", client, True)

        result = await verify_parent_candidates(
            _graph(["child-1", "child-2"]),
            verifier=runtime,
            second_verifier=None,
            arbiter=None,
            mode="standard",
        )

        self.assertEqual(result.stats.primary.requested_batches, 1)
        self.assertEqual(result.stats.primary.succeeded_batches, 1)
        self.assertEqual(result.stats.primary.fallback_batches, 1)
        self.assertEqual(result.stats.primary.requested_children, 2)
        self.assertEqual(result.stats.primary.succeeded_children, 1)
        self.assertEqual(result.stats.primary.fallback_children, 1)
        self.assertIn(
            "independent_parent_verifier_partial",
            self._components(
                mode="standard",
                verifier=runtime,
                second_verifier=None,
                arbiter=None,
                stats=result.stats,
            ),
        )
        # Preserve the established three-value unpacking contract.
        verified, votes, warnings = result
        self.assertEqual(len(verified.parent_candidates), 2)
        self.assertEqual(len(votes), 2)
        self.assertTrue(warnings)

    async def test_parent_verifier_uses_bounded_qwen_completion_policy(self):
        client = _VerifierClient()
        runtime = RoleRuntime(
            "qwen",
            "qwen3.8-max-preview",
            client,
            True,
        )

        await verify_parent_candidates(
            _graph(["child-1"], parents_per_child=2),
            verifier=runtime,
            second_verifier=None,
            arbiter=None,
            mode="standard",
        )

        self.assertEqual(len(client.call_kwargs), 1)
        call = client.call_kwargs[0]
        answer_budget = call["max_tokens"]
        self.assertEqual(call["max_attempts"], 1)
        self.assertEqual(
            call["thinking_budget"],
            QWEN_LOW_REASONING_TOKEN_RESERVE,
        )
        self.assertNotIn("reasoning_effort", call)
        self.assertEqual(
            call["max_completion_tokens"],
            answer_budget + QWEN_LOW_REASONING_TOKEN_RESERVE,
        )
        self.assertEqual(
            call["timeout_seconds"],
            VERIFIER_JSON_TIMEOUT_SECONDS,
        )

    async def test_standard_all_runtime_batches_fallback_is_failed_degradation(
        self,
    ):
        client = _VerifierClient(
            fail_children={"child-1"},
            malformed_children={"child-2"},
            wrong_id_children={"child-3"},
        )
        runtime = RoleRuntime("qwen", "test", client, True)

        result = await verify_parent_candidates(
            _graph(["child-1", "child-2", "child-3"]),
            verifier=runtime,
            second_verifier=None,
            arbiter=None,
            mode="standard",
        )

        components = self._components(
            mode="standard",
            verifier=runtime,
            second_verifier=None,
            arbiter=None,
            stats=result.stats,
        )
        self.assertEqual(result.stats.primary.succeeded_batches, 0)
        self.assertEqual(result.stats.primary.fallback_batches, 1)
        self.assertEqual(result.stats.primary.requested_children, 3)
        self.assertEqual(result.stats.primary.succeeded_children, 0)
        self.assertEqual(result.stats.primary.fallback_children, 3)
        self.assertIn("independent_parent_verifier_failed", components)
        self.assertNotIn("independent_parent_verifier_partial", components)

    async def test_precision_second_verifier_runtime_failure_is_degraded(
        self,
    ):
        primary_client = _VerifierClient()
        second_client = _VerifierClient(fail_children={"child-1"})
        arbiter_client = _VerifierClient()
        verifier = RoleRuntime("qwen", "test", primary_client, True)
        second = RoleRuntime("qwen", "test", second_client, True)
        arbiter = RoleRuntime("qwen", "test", arbiter_client, True)

        result = await verify_parent_candidates(
            _graph(["child-1"], parents_per_child=2),
            verifier=verifier,
            second_verifier=second,
            arbiter=arbiter,
            mode="precision",
        )

        components = self._components(
            mode="precision",
            verifier=verifier,
            second_verifier=second,
            arbiter=arbiter,
            stats=result.stats,
        )
        self.assertEqual(result.stats.secondary.requested_batches, 1)
        self.assertEqual(result.stats.secondary.succeeded_batches, 0)
        self.assertEqual(result.stats.secondary.fallback_batches, 1)
        self.assertEqual(result.stats.arbiter.requested_batches, 0)
        self.assertIn("second_parent_verifier_failed", components)

    async def test_unavailable_second_verifier_does_not_add_a_fallback_vote(
        self,
    ):
        primary_client = _VerifierClient(classification="direct_parent")
        verifier = RoleRuntime("qwen", "primary", primary_client, True)
        second = RoleRuntime(
            "qwen",
            "secondary",
            None,
            False,
            "未配置第二校验器",
        )

        result = await verify_parent_candidates(
            _graph(
                [f"child-{index}" for index in range(8)],
                parents_per_child=2,
            ),
            verifier=verifier,
            second_verifier=second,
            arbiter=None,
            mode="precision",
        )

        self.assertEqual(result.stats.secondary.requested_batches, 2)
        self.assertEqual(result.stats.secondary.attempted_batches, 0)
        self.assertEqual(result.stats.secondary.succeeded_batches, 0)
        self.assertEqual(result.stats.secondary.fallback_batches, 2)
        self.assertEqual(result.stats.secondary.requested_children, 8)
        self.assertEqual(result.stats.secondary.succeeded_children, 0)
        self.assertEqual(result.stats.secondary.fallback_children, 8)
        self.assertEqual(result.stats.arbiter.requested_batches, 0)
        self.assertTrue(
            all(
                [vote.actor for vote in votes] == ["qwen"]
                for votes in result.votes.values()
            )
        )

    async def test_precision_arbiter_runtime_failure_is_degraded(self):
        primary_client = _VerifierClient(classification="direct_parent")
        second_client = _VerifierClient(classification="sibling")
        arbiter_client = _VerifierClient(fail_children={"child-1"})
        verifier = RoleRuntime("qwen", "test", primary_client, True)
        second = RoleRuntime("qwen", "test", second_client, True)
        arbiter = RoleRuntime("qwen", "test", arbiter_client, True)

        result = await verify_parent_candidates(
            _graph(["child-1"], parents_per_child=2),
            verifier=verifier,
            second_verifier=second,
            arbiter=arbiter,
            mode="precision",
        )

        components = self._components(
            mode="precision",
            verifier=verifier,
            second_verifier=second,
            arbiter=arbiter,
            stats=result.stats,
        )
        self.assertEqual(result.stats.arbiter.requested_batches, 1)
        self.assertEqual(result.stats.arbiter.succeeded_batches, 0)
        self.assertEqual(result.stats.arbiter.fallback_batches, 1)
        self.assertIn("parent_verifier_arbiter_failed", components)

    async def test_unavailable_arbiter_does_not_add_a_fallback_vote(self):
        primary = RoleRuntime(
            "qwen",
            "primary",
            _VerifierClient(classification="direct_parent"),
            True,
        )
        second = RoleRuntime(
            "qwen",
            "secondary",
            _VerifierClient(classification="sibling"),
            True,
        )
        arbiter = RoleRuntime(
            "qwen",
            "arbiter",
            None,
            False,
            "未配置仲裁器",
        )

        result = await verify_parent_candidates(
            _graph(
                [f"child-{index}" for index in range(8)],
                parents_per_child=2,
            ),
            verifier=primary,
            second_verifier=second,
            arbiter=arbiter,
            mode="precision",
        )

        self.assertEqual(result.stats.arbiter.requested_batches, 2)
        self.assertEqual(result.stats.arbiter.attempted_batches, 0)
        self.assertEqual(result.stats.arbiter.succeeded_batches, 0)
        self.assertEqual(result.stats.arbiter.fallback_batches, 2)
        self.assertEqual(result.stats.arbiter.requested_children, 8)
        self.assertEqual(result.stats.arbiter.succeeded_children, 0)
        self.assertEqual(result.stats.arbiter.fallback_children, 8)
        self.assertTrue(
            all(
                [vote.actor for vote in votes]
                == ["qwen", "qwen", "deterministic-consensus"]
                for votes in result.votes.values()
            )
        )

    async def test_unused_unavailable_verifiers_do_not_degrade_direct_edges(
        self,
    ):
        parent = _node(
            "parent-direct",
            role="branch_topic",
            origin="structural",
        )
        child = _node("child-direct")
        graph = NormalizedGraph(
            document_id="doc",
            document_title="无需模型的直接父边",
            nodes=[parent, child],
            parent_candidates=[
                NormalizedParentCandidate(
                    parent_id=parent.id,
                    child_id=child.id,
                    score=0.94,
                    classification="direct_parent",
                    evidence=[
                        EvidenceRef(
                            unit_id="unit:child-direct",
                            excerpt="同分支直接父边证据",
                        )
                    ],
                )
            ],
            cross_links=[],
        )
        unavailable = RoleRuntime(
            "qwen",
            "unavailable",
            None,
            False,
            "模型不可用",
        )

        result = await verify_parent_candidates(
            graph,
            verifier=unavailable,
            second_verifier=unavailable,
            arbiter=unavailable,
            mode="precision",
        )
        components = self._components(
            mode="precision",
            verifier=unavailable,
            second_verifier=unavailable,
            arbiter=unavailable,
            stats=result.stats,
        )

        self.assertEqual(result.stats.primary.requested_batches, 0)
        self.assertEqual(result.stats.secondary.requested_batches, 0)
        self.assertEqual(result.stats.arbiter.requested_batches, 0)
        self.assertNotIn("independent_parent_verifier", components)
        self.assertNotIn("second_parent_verifier", components)


if __name__ == "__main__":
    unittest.main()
