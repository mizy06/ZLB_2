from __future__ import annotations

import json
import unittest

from backend.app.agents import (
    VerifierRoleRunStats,
    RoleRuntime,
    verify_parent_candidates,
)
from backend.app.mindmap_engine.schemas import (
    EvidenceRef,
    NormalizedGraph,
    NormalizedNode,
    NormalizedParentCandidate,
    SolveRequest,
)
from backend.app.mindmap_engine.topology import (
    TopologyLimits,
    solve_topology,
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
        branch_id=f"branch:{node_id}",
        confidence=0.9,
        optional=False,
        activation_score=0.9,
        activation_cost=0,
        is_root_candidate=False,
        evidence=[
            EvidenceRef(
                unit_id=unit_id,
                chunk_id=unit_id,
                excerpt=f"节点{node_id}证据",
            )
        ],
        support_unit_ids=[unit_id],
        media_asset_ids=[],
    )


def _graph(
    child_count: int,
    *,
    parents_per_child: int = 3,
) -> NormalizedGraph:
    parents = [
        _node(
            f"parent-{index}",
            role="branch_topic",
            origin="structural",
        )
        for index in range(parents_per_child)
    ]
    children = [_node(f"child-{index}") for index in range(child_count)]
    candidates = [
        NormalizedParentCandidate(
            parent_id=parent.id,
            child_id=child.id,
            score=0.95 - parent_index * 0.1,
            classification="direct_parent",
            evidence=[
                EvidenceRef(
                    unit_id=f"edge:{child.id}:{parent.id}",
                    chunk_id=f"edge:{child.id}:{parent.id}",
                    excerpt=f"{child.id} 到 {parent.id} 的候选证据",
                )
            ],
        )
        for child in children
        for parent_index, parent in enumerate(parents)
    ]
    return NormalizedGraph(
        document_id="doc",
        document_title="Verifier 批量 TDD",
        nodes=[*parents, *children],
        parent_candidates=candidates,
        cross_links=[],
    )


class _BatchAwareVerifierClient:
    def __init__(
        self,
        *,
        classification: str = "direct_parent",
        omit_children: set[str] | None = None,
        bad_parent_children: set[str] | None = None,
    ):
        self.classification = classification
        self.omit_children = omit_children or set()
        self.bad_parent_children = bad_parent_children or set()
        self.calls: list[dict] = []

    @staticmethod
    def _child_output(
        item: dict,
        *,
        classification: str,
        bad_parent: bool,
    ) -> dict:
        child_id = item["child"]["id"]
        evaluations = [
            {
                "parent_id": (
                    f"unknown:{candidate['parent']['id']}"
                    if bad_parent and index == 0
                    else candidate["parent"]["id"]
                ),
                "classification": classification,
                "verifier_score": 0.91,
                "reason": "批量校验测试结论",
            }
            for index, candidate in enumerate(item["candidates"])
        ]
        return {
            "child_id": child_id,
            "evaluations": evaluations,
        }

    async def complete_json(self, **kwargs):
        payload = json.loads(kwargs["user_prompt"])
        self.calls.append(payload)
        if "children" not in payload:
            child_id = payload["child"]["id"]
            if child_id in self.omit_children:
                return {"child_id": child_id, "evaluations": []}
            return self._child_output(
                payload,
                classification=self.classification,
                bad_parent=child_id in self.bad_parent_children,
            )

        outputs = []
        for item in payload["children"]:
            child_id = item["child"]["id"]
            if child_id in self.omit_children:
                continue
            outputs.append(
                self._child_output(
                    item,
                    classification=self.classification,
                    bad_parent=child_id in self.bad_parent_children,
                )
            )
        return {"children": outputs}


class VerifierBatchingTDDTests(unittest.IsolatedAsyncioTestCase):
    def test_verifier_stats_keep_old_payload_compatible_and_serialize_children(
        self,
    ):
        legacy = VerifierRoleRunStats.model_validate(
            {
                "requested_batches": 2,
                "attempted_batches": 2,
                "succeeded_batches": 1,
                "fallback_batches": 1,
            }
        )

        self.assertEqual(legacy.requested_children, 0)
        self.assertEqual(legacy.succeeded_children, 0)
        self.assertEqual(legacy.fallback_children, 0)
        self.assertEqual(
            VerifierRoleRunStats(
                requested_batches=1,
                attempted_batches=1,
                succeeded_batches=1,
                fallback_batches=1,
                requested_children=4,
                succeeded_children=2,
                fallback_children=2,
            ).model_dump(mode="json"),
            {
                "requested_batches": 1,
                "attempted_batches": 1,
                "succeeded_batches": 1,
                "fallback_batches": 1,
                "requested_children": 4,
                "succeeded_children": 2,
                "fallback_children": 2,
            },
        )

    async def test_standard_verifier_batches_four_children_per_http_call(self):
        graph = _graph(8)
        client = _BatchAwareVerifierClient()

        result = await verify_parent_candidates(
            graph,
            verifier=RoleRuntime("qwen", "test", client, True),
            second_verifier=None,
            arbiter=None,
            mode="standard",
        )

        self.assertEqual(len(client.calls), 2)
        prompt_children = [
            item
            for call in client.calls
            for item in call["children"]
        ]
        self.assertEqual(
            {item["child"]["id"] for item in prompt_children},
            {f"child-{index}" for index in range(8)},
        )
        self.assertTrue(
            all(len(item["candidates"]) == 3 for item in prompt_children)
        )
        self.assertTrue(
            all(
                set(item["evidence_scope_unit_ids"])
                >= {
                    f"unit:{item['child']['id']}",
                    *{
                        f"edge:{item['child']['id']}:"
                        f"{candidate['parent']['id']}"
                        for candidate in item["candidates"]
                    },
                }
                for item in prompt_children
            )
        )
        self.assertEqual(result.stats.primary.requested_batches, 2)
        self.assertEqual(result.stats.primary.attempted_batches, 2)
        self.assertEqual(result.stats.primary.succeeded_batches, 2)
        self.assertEqual(result.stats.primary.fallback_batches, 0)
        self.assertEqual(result.stats.primary.requested_children, 8)
        self.assertEqual(result.stats.primary.succeeded_children, 8)
        self.assertEqual(result.stats.primary.fallback_children, 0)
        self.assertEqual(len(result.votes), 24)

    async def test_bad_or_missing_child_only_falls_back_that_child(self):
        graph = _graph(4, parents_per_child=2)
        client = _BatchAwareVerifierClient(
            omit_children={"child-1"},
            bad_parent_children={"child-2"},
        )

        result = await verify_parent_candidates(
            graph,
            verifier=RoleRuntime("qwen", "test", client, True),
            second_verifier=None,
            arbiter=None,
            mode="standard",
        )

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(result.stats.primary.requested_batches, 1)
        self.assertEqual(result.stats.primary.attempted_batches, 1)
        self.assertEqual(result.stats.primary.succeeded_batches, 1)
        self.assertEqual(result.stats.primary.fallback_batches, 1)
        self.assertEqual(result.stats.primary.requested_children, 4)
        self.assertEqual(result.stats.primary.succeeded_children, 2)
        self.assertEqual(result.stats.primary.fallback_children, 2)
        for child_id in {"child-0", "child-3"}:
            self.assertTrue(
                all(
                    votes[0].actor == "qwen"
                    for (parent_id, voted_child_id), votes
                    in result.votes.items()
                    if voted_child_id == child_id
                )
            )
        for child_id in {"child-1", "child-2"}:
            self.assertTrue(
                all(
                    votes[0].actor == "deterministic-verifier"
                    for (parent_id, voted_child_id), votes
                    in result.votes.items()
                    if voted_child_id == child_id
                )
            )
        self.assertTrue(any("child-1" in item for item in result.warnings))
        self.assertTrue(any("child-2" in item for item in result.warnings))
        self.assertFalse(any("child-0" in item for item in result.warnings))
        self.assertFalse(any("child-3" in item for item in result.warnings))

    async def test_precision_secondary_and_arbiter_batch_by_role(self):
        graph = _graph(8, parents_per_child=2)
        primary = _BatchAwareVerifierClient(
            classification="direct_parent"
        )
        secondary = _BatchAwareVerifierClient(classification="sibling")
        arbiter = _BatchAwareVerifierClient(
            classification="direct_parent"
        )

        result = await verify_parent_candidates(
            graph,
            verifier=RoleRuntime("qwen", "primary", primary, True),
            second_verifier=RoleRuntime(
                "qwen",
                "secondary",
                secondary,
                True,
            ),
            arbiter=RoleRuntime("qwen", "arbiter", arbiter, True),
            mode="precision",
        )

        self.assertEqual(len(primary.calls), 2)
        self.assertEqual(len(secondary.calls), 2)
        self.assertEqual(len(arbiter.calls), 2)
        for role_stats in (
            result.stats.primary,
            result.stats.secondary,
            result.stats.arbiter,
        ):
            self.assertEqual(role_stats.requested_batches, 2)
            self.assertEqual(role_stats.attempted_batches, 2)
            self.assertEqual(role_stats.succeeded_batches, 2)
            self.assertEqual(role_stats.fallback_batches, 0)
            self.assertEqual(role_stats.requested_children, 8)
            self.assertEqual(role_stats.succeeded_children, 8)
            self.assertEqual(role_stats.fallback_children, 0)
        self.assertTrue(
            all(
                votes[-1].actor == "qwen-arbiter"
                for votes in result.votes.values()
            )
        )

    async def test_high_evidence_high_margin_same_branch_bypasses_model(self):
        primary_parent = _node(
            "primary-parent",
            role="branch_topic",
            origin="structural",
        ).model_copy(update={"branch_id": "branch:shared"})
        alternative_parent = _node(
            "alternative-parent",
            role="branch_topic",
            origin="structural",
        ).model_copy(update={"branch_id": "branch:shared"})
        child = _node("child").model_copy(
            update={"branch_id": "branch:shared"}
        )
        graph = NormalizedGraph(
            document_id="doc",
            document_title="确定性父边直通 TDD",
            nodes=[primary_parent, alternative_parent, child],
            parent_candidates=[
                NormalizedParentCandidate(
                    parent_id=primary_parent.id,
                    child_id=child.id,
                    score=0.94,
                    classification="direct_parent",
                    evidence=[
                        EvidenceRef(
                            unit_id="unit:child",
                            excerpt="同分支直接父边证据",
                        )
                    ],
                ),
                NormalizedParentCandidate(
                    parent_id=alternative_parent.id,
                    child_id=child.id,
                    score=0.7,
                    classification="direct_parent",
                    evidence=[
                        EvidenceRef(
                            unit_id="unit:child",
                            excerpt="低分备选父边证据",
                        )
                    ],
                ),
            ],
            cross_links=[],
        )
        client = _BatchAwareVerifierClient()

        result = await verify_parent_candidates(
            graph,
            verifier=RoleRuntime("qwen", "test", client, True),
            second_verifier=None,
            arbiter=None,
            mode="standard",
        )

        self.assertEqual(client.calls, [])
        self.assertEqual(result.stats.primary.requested_batches, 0)
        self.assertEqual(result.stats.primary.requested_children, 0)
        self.assertTrue(
            all(
                votes == [
                    next(
                        vote
                        for vote in votes
                        if vote.actor == "deterministic-verifier"
                    )
                ]
                for votes in result.votes.values()
            )
        )

    async def test_only_risky_parent_choices_reach_model(self):
        shared_parent = _node(
            "shared-parent",
            role="branch_topic",
            origin="structural",
        ).model_copy(update={"branch_id": "branch:shared"})
        close_parent = _node(
            "close-parent",
            role="branch_topic",
            origin="structural",
        ).model_copy(update={"branch_id": "branch:shared"})
        cross_parent = _node(
            "cross-parent",
            role="branch_topic",
            origin="structural",
        ).model_copy(update={"branch_id": "branch:other"})
        root_a = _node(
            "root-a",
            role="root_topic",
            origin="structural",
        ).model_copy(
            update={
                "branch_id": None,
                "is_root_candidate": True,
            }
        )
        root_b = _node(
            "root-b",
            role="root_topic",
            origin="structural",
        ).model_copy(
            update={
                "branch_id": None,
                "is_root_candidate": True,
            }
        )
        low_margin = _node("low-margin").model_copy(
            update={"branch_id": "branch:shared"}
        )
        cross_branch = _node("cross-branch").model_copy(
            update={"branch_id": "branch:shared"}
        )
        abstract = _node("abstract", origin="abstractive").model_copy(
            update={"branch_id": "branch:shared"}
        )
        missing_evidence = _node("missing-evidence").model_copy(
            update={"branch_id": "branch:shared"}
        )
        root_conflict = _node("root-conflict").model_copy(
            update={"branch_id": "branch:shared"}
        )

        def candidate(
            parent: NormalizedNode,
            child: NormalizedNode,
            score: float,
            *,
            with_evidence: bool = True,
        ) -> NormalizedParentCandidate:
            return NormalizedParentCandidate(
                parent_id=parent.id,
                child_id=child.id,
                score=score,
                classification="direct_parent",
                evidence=(
                    [
                        EvidenceRef(
                            unit_id=f"unit:{child.id}",
                            excerpt=f"{child.id} 的直接父边证据",
                        )
                    ]
                    if with_evidence
                    else []
                ),
            )

        graph = NormalizedGraph(
            document_id="doc",
            document_title="风险选择 TDD",
            nodes=[
                shared_parent,
                close_parent,
                cross_parent,
                root_a,
                root_b,
                low_margin,
                cross_branch,
                abstract,
                missing_evidence,
                root_conflict,
            ],
            parent_candidates=[
                candidate(shared_parent, low_margin, 0.9),
                candidate(close_parent, low_margin, 0.82),
                candidate(cross_parent, cross_branch, 0.94),
                candidate(shared_parent, abstract, 0.94),
                candidate(
                    shared_parent,
                    missing_evidence,
                    0.94,
                    with_evidence=False,
                ),
                candidate(root_a, root_conflict, 0.94),
                candidate(root_b, root_conflict, 0.7),
            ],
            cross_links=[],
        )
        client = _BatchAwareVerifierClient()

        result = await verify_parent_candidates(
            graph,
            verifier=RoleRuntime("qwen", "test", client, True),
            second_verifier=None,
            arbiter=None,
            mode="standard",
        )

        requested_children = {
            item["child"]["id"]
            for call in client.calls
            for item in call["children"]
        }
        self.assertEqual(
            requested_children,
            {
                low_margin.id,
                cross_branch.id,
                abstract.id,
                root_conflict.id,
            },
        )
        self.assertEqual(result.stats.primary.requested_children, 4)
        self.assertTrue(
            all(
                vote.actor == "deterministic-verifier"
                for (parent_id, child_id), votes in result.votes.items()
                if child_id == missing_evidence.id
                for vote in votes
            )
        )

    async def test_rejected_only_parent_becomes_provisional_not_infeasible(self):
        root = _node(
            "root",
            role="root_topic",
            origin="structural",
        ).model_copy(
            update={
                "branch_id": None,
                "is_root_candidate": True,
            }
        )
        child = _node(
            "required-topic",
            role="branch_topic",
            origin="abstractive",
        ).model_copy(update={"branch_id": "branch:required"})
        graph = NormalizedGraph(
            document_id="doc",
            document_title="父边降级合同",
            nodes=[root, child],
            parent_candidates=[
                NormalizedParentCandidate(
                    parent_id=root.id,
                    child_id=child.id,
                    score=0.9,
                    classification="direct_parent",
                    evidence=[
                        EvidenceRef(
                            unit_id="unit:required-topic",
                            excerpt="必选主题的候选父边证据",
                        )
                    ],
                )
            ],
            cross_links=[],
        )
        client = _BatchAwareVerifierClient(
            classification="ancestor_only"
        )

        verified = await verify_parent_candidates(
            graph,
            verifier=RoleRuntime("qwen", "test", client, True),
            second_verifier=None,
            arbiter=None,
            mode="standard",
        )
        candidate = verified.graph.parent_candidates[0]
        solved = solve_topology(
            SolveRequest(graph=verified.graph),
            limits=TopologyLimits(
                max_active_nodes=8,
                max_root_fanout=4,
                max_node_fanout=4,
            ),
        )

        self.assertEqual(candidate.classification, "ancestor_only")
        self.assertTrue(candidate.provisional)
        self.assertEqual(solved.solver_status, "OPTIMAL")
        self.assertTrue(solved.tree_edges[0].provisional)


if __name__ == "__main__":
    unittest.main()
