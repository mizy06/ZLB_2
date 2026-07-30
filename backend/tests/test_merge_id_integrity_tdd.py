from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.app.agents import canonicalize_semantic_duplicates
from backend.app.blackboard import SQLiteBlackboard
from backend.app.mindmap_engine.schemas import EvidenceRef, NodeCandidateIn


class MergeIdentityTDDTests(unittest.TestCase):
    def test_exact_temp_id_merges_before_branch_topic_semantic_exemption(self):
        base_topic = NodeCandidateIn(
            temp_id="topic:branch-a",
            name="量子基础",
            type="branch_topic",
            role="branch_topic",
            definition="课程一级主题",
            origin="structural",
            branch_id="branch-a",
            confidence=0.72,
            optional=False,
            support_unit_ids=["unit-a"],
        )
        branch_team_topic = NodeCandidateIn(
            temp_id="topic:branch-a",
            name="量子力学的核心框架",
            type="branch_topic",
            role="branch_topic",
            definition="分支团队归纳出的课程一级主题",
            origin="abstractive",
            branch_id="branch-a",
            confidence=0.91,
            optional=False,
            evidence=[
                EvidenceRef(
                    unit_id="unit-b",
                    excerpt="量子态、测量与演化构成核心框架",
                )
            ],
            support_unit_ids=["unit-b"],
        )
        independent_topic = NodeCandidateIn(
            temp_id="topic:branch-b",
            name="量子力学的核心框架",
            type="branch_topic",
            role="branch_topic",
            definition="另一个结构分支",
            origin="structural",
            branch_id="branch-b",
            confidence=0.8,
            optional=False,
            support_unit_ids=["unit-c"],
        )

        merged = canonicalize_semantic_duplicates(
            [base_topic, branch_team_topic, independent_topic]
        )

        self.assertEqual(
            len({candidate.temp_id for candidate in merged}),
            len(merged),
        )
        branch_a = [
            candidate
            for candidate in merged
            if candidate.temp_id == "topic:branch-a"
        ]
        self.assertEqual(len(branch_a), 1)
        self.assertEqual(branch_a[0].name, "量子力学的核心框架")
        self.assertIn("量子基础", branch_a[0].aliases)
        self.assertEqual(
            branch_a[0].support_unit_ids,
            ["unit-a", "unit-b"],
        )
        self.assertEqual(
            [item.unit_id for item in branch_a[0].evidence],
            ["unit-b"],
        )
        self.assertEqual(
            [candidate.temp_id for candidate in merged].count(
                "topic:branch-b"
            ),
            1,
        )

    def test_same_branch_fuzzy_names_do_not_merge_conflicting_claims(self):
        shared_evidence = EvidenceRef(
            unit_id="unit-cavity",
            excerpt="驻波条件为 nL=kλ/2。",
            page=86,
        )
        source = NodeCandidateIn(
            temp_id="standing-wave-source",
            name="谐振腔两端反射镜驻波边界条件",
            definition="驻波条件为 nL=kλ/2。",
            branch_id="branch-cavity",
            evidence=[shared_evidence],
            support_unit_ids=["unit-cavity"],
            confidence=0.9,
        )
        conflicting = NodeCandidateIn(
            temp_id="standing-wave-conflict",
            name="谐振腔两端反射镜驻波边界条件式",
            definition="驻波条件为 nkλ/2=L。",
            branch_id="branch-cavity",
            evidence=[shared_evidence],
            support_unit_ids=["unit-cavity"],
            confidence=0.89,
        )

        merged = canonicalize_semantic_duplicates([source, conflicting])

        self.assertEqual(
            {candidate.temp_id for candidate in merged},
            {source.temp_id, conflicting.temp_id},
        )

    def test_same_branch_algebraic_duplicates_merge_without_name_similarity(
        self,
    ):
        source = NodeCandidateIn(
            temp_id="standing-wave-source",
            name="谐振腔驻波条件",
            definition="驻波条件为 nL=kλ/2。",
            branch_id="branch-cavity",
            evidence=[
                EvidenceRef(
                    unit_id="unit-cavity",
                    excerpt="驻波条件为 nL=kλ/2。",
                    page=86,
                )
            ],
            support_unit_ids=["unit-cavity"],
            confidence=0.9,
        )
        equivalent = NodeCandidateIn(
            temp_id="standing-wave-equivalent",
            name="允许振荡波长",
            definition="允许波长满足 λ=2nL/k。",
            branch_id="branch-cavity",
            evidence=[
                EvidenceRef(
                    unit_id="unit-cavity",
                    excerpt="允许波长满足 λ=2nL/k。",
                    page=86,
                )
            ],
            support_unit_ids=["unit-cavity"],
            confidence=0.88,
        )

        merged = canonicalize_semantic_duplicates([source, equivalent])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].temp_id, source.temp_id)
        self.assertIn(equivalent.name, merged[0].aliases)
        self.assertEqual(
            {item.excerpt for item in merged[0].evidence},
            {
                "驻波条件为 nL=kλ/2。",
                "允许波长满足 λ=2nL/k。",
            },
        )

    def test_conflicting_nonstructural_same_temp_id_is_not_field_blended(
        self,
    ):
        supported = NodeCandidateIn(
            temp_id="branch-a:node-1",
            name="谐振腔驻波条件",
            definition="驻波条件为 nL=kλ/2。",
            branch_id="branch-a",
            confidence=0.94,
            evidence=[
                EvidenceRef(
                    unit_id="unit-cavity",
                    excerpt="驻波条件为 nL=kλ/2。",
                    page=86,
                )
            ],
            support_unit_ids=["unit-cavity"],
        )
        conflicting = NodeCandidateIn(
            temp_id="branch-a:node-1",
            name="错误驻波条件",
            definition="驻波条件为 nkλ/2=L。",
            branch_id="branch-a",
            confidence=0.7,
            evidence=[
                EvidenceRef(
                    unit_id="unit-cavity",
                    excerpt="驻波条件为 nL=kλ/2。",
                    page=86,
                )
            ],
            support_unit_ids=["unit-cavity"],
        )

        merged = canonicalize_semantic_duplicates(
            [supported, conflicting]
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].name, supported.name)
        self.assertEqual(merged[0].definition, supported.definition)
        self.assertNotIn(conflicting.name, merged[0].aliases)
        self.assertEqual(
            [item.excerpt for item in merged[0].evidence],
            ["驻波条件为 nL=kλ/2。"],
        )

    def test_conflicting_formula_labels_with_same_temp_id_are_not_blended(
        self,
    ):
        supported = NodeCandidateIn(
            temp_id="branch-a:node-label",
            name="驻波条件 nL=kλ/2",
            definition="",
            branch_id="branch-a",
            confidence=0.94,
            evidence=[
                EvidenceRef(
                    unit_id="unit-cavity",
                    excerpt="驻波条件为 nL=kλ/2。",
                    page=86,
                )
            ],
            support_unit_ids=["unit-cavity"],
        )
        conflicting = NodeCandidateIn(
            temp_id="branch-a:node-label",
            name="驻波条件 nkλ/2=L",
            definition="",
            branch_id="branch-a",
            confidence=0.7,
            evidence=[
                EvidenceRef(
                    unit_id="unit-other",
                    excerpt="模型产生的错误公式。",
                    page=86,
                )
            ],
            support_unit_ids=["unit-other"],
        )

        merged = canonicalize_semantic_duplicates(
            [supported, conflicting]
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].name, supported.name)
        self.assertNotIn(conflicting.name, merged[0].aliases)
        self.assertEqual(
            [item.unit_id for item in merged[0].evidence],
            ["unit-cavity"],
        )


class BlackboardIdentityTDDTests(unittest.TestCase):
    def test_duplicate_claim_ids_preserve_previous_snapshot_and_raise_domain_error(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "blackboard.sqlite3"
            board = SQLiteBlackboard(database)
            board.start_run(
                run_id="run-identity",
                task_id="task-identity",
                mode="precision",
            )
            board.save_node_claims(
                "run-identity",
                [
                    NodeCandidateIn(
                        temp_id="existing-claim",
                        name="已保存候选",
                    )
                ],
            )

            failure: Exception | None = None
            try:
                board.save_node_claims(
                    "run-identity",
                    [
                        NodeCandidateIn(
                            temp_id="duplicate-claim",
                            name="重复候选一",
                        ),
                        NodeCandidateIn(
                            temp_id="duplicate-claim",
                            name="重复候选二",
                        ),
                    ],
                )
            except Exception as exc:  # noqa: BLE001 - assert boundary type below
                failure = exc

            with sqlite3.connect(database) as connection:
                rows = connection.execute(
                    "SELECT item_id, payload_json FROM node_claims "
                    "WHERE run_id = ? ORDER BY item_id",
                    ("run-identity",),
                ).fetchall()

        self.assertEqual([row[0] for row in rows], ["existing-claim"])
        self.assertEqual(json.loads(rows[0][1])["name"], "已保存候选")
        self.assertIsInstance(failure, ValueError)
        self.assertNotIsInstance(failure, sqlite3.IntegrityError)
        self.assertIn("node_claims", str(failure))
        self.assertIn("duplicate-claim", str(failure))


if __name__ == "__main__":
    unittest.main()
