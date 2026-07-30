from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.app.mindmap_engine.schemas import (
    EvidenceRef,
    NormalizedGraph,
    NormalizedNode,
    NormalizedParentCandidate,
    SolveRequest,
)
from backend.app.mindmap_engine.topology import solve_topology


def evidence(unit_id: str, excerpt: str = "可审计关系原文") -> EvidenceRef:
    return EvidenceRef(unit_id=unit_id, excerpt=excerpt)


def node(
    node_id: str,
    name: str,
    *,
    role: str = "concept",
    origin: str = "explicit",
    root: bool = False,
    optional: bool = False,
    support: list[str] | None = None,
    node_evidence: list[EvidenceRef] | None = None,
) -> NormalizedNode:
    return NormalizedNode(
        id=node_id,
        temp_ids=[node_id],
        name=name,
        type="root_topic" if root else role,
        role="root_topic" if root else role,
        definition=f"{name}定义",
        aliases=[],
        origin="synthesized_root" if root else origin,
        branch_id=None if root else "branch-a",
        confidence=0.85,
        optional=False if root else optional,
        activation_score=0.8,
        activation_cost=0.1,
        is_root_candidate=root,
        evidence=(
            [evidence(f"unit-{node_id}")]
            if node_evidence is None
            else node_evidence
        ),
        support_unit_ids=(
            [f"unit-{node_id}"] if support is None else support
        ),
        media_asset_ids=[],
    )


def parent(
    parent_id: str,
    child_id: str,
    score: float,
    *,
    relation_evidence: list[EvidenceRef] | None = None,
) -> NormalizedParentCandidate:
    return NormalizedParentCandidate(
        parent_id=parent_id,
        child_id=child_id,
        score=score,
        classification="direct_parent",
        evidence=(
            [evidence(f"edge-{parent_id}-{child_id}")]
            if relation_evidence is None
            else relation_evidence
        ),
    )


class TopologyFallbackTDDTests(unittest.TestCase):
    def test_same_depth_tree_edges_preserve_normalized_node_source_order(self):
        graph = NormalizedGraph(
            document_id="doc",
            document_title="课程",
            nodes=[
                node("root", "课程", root=True),
                node(
                    "z-early",
                    "早期章节",
                    role="branch_topic",
                    origin="abstractive",
                ),
                node(
                    "a-late",
                    "后续章节",
                    role="branch_topic",
                    origin="abstractive",
                ),
            ],
            parent_candidates=[
                parent("root", "z-early", 0.95),
                parent("root", "a-late", 0.95),
            ],
            cross_links=[],
        )

        solved = solve_topology(SolveRequest(graph=graph))

        self.assertEqual(
            [
                edge.target
                for edge in solved.tree_edges
                if edge.source == solved.root_id
            ],
            ["z-early", "a-late"],
            msg=(
                "same-depth siblings must retain normalized/source order; "
                "sorting by hashed target id corrupts the exported chapter "
                "sequence"
            ),
        )

    def test_greedy_fallback_does_not_keep_single_child_optional_abstraction(self):
        graph = NormalizedGraph(
            document_id="doc",
            document_title="课程",
            nodes=[
                node("root", "课程", root=True),
                node(
                    "abstract",
                    "薄弱抽象",
                    role="branch_topic",
                    origin="structural",
                    optional=True,
                ),
                node("leaf", "明确知识点"),
            ],
            parent_candidates=[
                parent("root", "abstract", 0.9),
                parent("abstract", "leaf", 0.9),
                parent("root", "leaf", 0.5),
            ],
            cross_links=[],
        )

        with patch(
            "backend.app.mindmap_engine.topology._solve_with_cp_sat",
            side_effect=RuntimeError("forced fallback"),
        ):
            solved = solve_topology(SolveRequest(graph=graph))

        self.assertEqual(solved.solver_status, "GREEDY_FALLBACK")
        self.assertNotIn("abstract", {item.id for item in solved.nodes})
        self.assertEqual(
            next(item.source for item in solved.tree_edges if item.target == "leaf"),
            "root",
        )

    def test_abstract_review_counts_unique_support_units(self):
        shared = evidence("shared-unit", "同一条支持原文")
        graph = NormalizedGraph(
            document_id="doc",
            document_title="课程",
            nodes=[
                node("root", "课程", root=True),
                node(
                    "abstract",
                    "抽象主题",
                    role="branch_topic",
                    origin="structural",
                    support=["shared-unit"],
                    node_evidence=[shared],
                ),
                node("leaf", "明确知识点"),
            ],
            parent_candidates=[
                parent("root", "abstract", 0.9),
                parent("abstract", "leaf", 0.9),
            ],
            cross_links=[],
        )

        solved = solve_topology(SolveRequest(graph=graph))

        abstract_reviews = [
            item
            for item in solved.review_items
            if item.type == "abstract_parent"
            and "abstract" in item.subject_ids
        ]
        self.assertEqual(len(abstract_reviews), 1)
        self.assertEqual(
            abstract_reviews[0].alternatives[0]["support_count"],
            1,
        )

    def test_competing_parent_alternatives_keep_relation_evidence(self):
        first_evidence = evidence("edge-first-child", "第一父主题包含子主题")
        second_evidence = evidence("edge-second-child", "第二父主题包含子主题")
        graph = NormalizedGraph(
            document_id="doc",
            document_title="课程",
            nodes=[
                node("root", "课程", root=True),
                node("first", "第一父主题"),
                node("second", "第二父主题"),
                node("child", "子主题"),
            ],
            parent_candidates=[
                parent("root", "first", 0.95),
                parent("root", "second", 0.95),
                parent(
                    "first",
                    "child",
                    0.9,
                    relation_evidence=[first_evidence],
                ),
                parent(
                    "second",
                    "child",
                    0.86,
                    relation_evidence=[second_evidence],
                ),
            ],
            cross_links=[],
        )

        solved = solve_topology(SolveRequest(graph=graph))
        review = next(
            item
            for item in solved.review_items
            if item.type == "competing_parent"
            and "child" in item.subject_ids
        )
        alternatives = {
            item["parent_id"]: item for item in review.alternatives
        }

        self.assertEqual(
            alternatives["first"]["evidence"],
            [first_evidence.model_dump(mode="json")],
        )
        self.assertEqual(
            alternatives["second"]["evidence"],
            [second_evidence.model_dump(mode="json")],
        )


if __name__ == "__main__":
    unittest.main()
