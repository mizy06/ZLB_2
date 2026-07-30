from __future__ import annotations

import unittest

from backend.app.agents import coverage_statistics
from backend.app.architecture_schemas import ContentUnit
from backend.app.mindmap_engine.normalize import normalize_graph
from backend.app.mindmap_engine.schemas import (
    EvidenceRef,
    NodeCandidateIn,
    NormalizeRequest,
)


class NormalizeStructuralIdentityTDDTests(unittest.TestCase):
    def test_normalize_repairs_safe_definitions_and_reextracts_hard_case(self):
        normalized = normalize_graph(
            NormalizeRequest(
                document_id="doc-definition-boundary",
                document_title="量子物理",
                nodes=[
                    NodeCandidateIn(
                        temp_id="root",
                        name="量子物理",
                        type="root_topic",
                        role="root_topic",
                        origin="synthesized_root",
                        is_root_candidate=True,
                        definition="",
                        optional=False,
                    ),
                    NodeCandidateIn(
                        temp_id="structural-empty",
                        name="§28.2 电子自旋与自旋轨道耦合",
                        type="branch_topic",
                        role="branch_topic",
                        origin="structural",
                        definition="",
                        branch_id="branch-structural",
                        support_unit_ids=["structural-unit"],
                    ),
                    NodeCandidateIn(
                        temp_id="node_7bf97ce023f0",
                        name="全同粒子组成的系统必须考虑这种不可分辨性",
                        definition=(
                            "全同粒子组成的系统必须考虑这种不可分辨性。\n"
                            "以两个粒子组成的系统为例：设粒子1、2可处在"
                            "状态A或B。\n设系统波函数时，应有：\n\n即 54"
                        ),
                        branch_id="branch-explicit",
                        evidence=[
                            EvidenceRef(
                                unit_id="chunk_a817710541",
                                excerpt="真实课件原文",
                            )
                        ],
                    ),
                    NodeCandidateIn(
                        temp_id="node_c670e6117e91",
                        name="亮度和强度极高",
                        definition=(
                            "3.亮度和强度极高：亮度：B～ ～ "
                            "强度：非聚焦状态 I > 聚焦状态可达到"
                            "脉冲瞬时功率可达 > 10 14 W "
                            "第28章结束 92"
                        ),
                        branch_id="branch-explicit",
                        evidence=[
                            EvidenceRef(
                                unit_id="chunk_d80f816aa9",
                                excerpt="真实课件原文",
                            )
                        ],
                    ),
                    NodeCandidateIn(
                        temp_id="node_29ace7e15619",
                        name="这说明原来对原子中电子运动的描述",
                        definition="不完全的",
                        branch_id="branch-explicit",
                        evidence=[
                            EvidenceRef(
                                unit_id="chunk_7aa8563d93",
                                excerpt="真实课件原文",
                            )
                        ],
                    ),
                    NodeCandidateIn(
                        temp_id="node_a3a6ab6d1310",
                        name="粒子数反转",
                        definition=(
                            "高能级粒子数N2大于低能级粒子数N1的"
                            "非热平衡态，是产生光放大的必要条件"
                        ),
                        branch_id="branch-explicit",
                        evidence=[
                            EvidenceRef(
                                unit_id="chunk_9c75f7a2a9",
                                excerpt="N2大于N1",
                            )
                        ],
                    ),
                    NodeCandidateIn(
                        temp_id="good-formula",
                        name="氢原子能级",
                        type="formula",
                        role="formula",
                        definition="E_n = E_1/n²",
                        branch_id="branch-explicit",
                        evidence=[
                            EvidenceRef(
                                unit_id="good-formula-unit",
                                excerpt="E_n = E_1/n²",
                            )
                        ],
                    ),
                ],
            )
        )

        temp_ids = {
            temp_id
            for node in normalized.nodes
            for temp_id in node.temp_ids
        }
        self.assertIn("root", temp_ids)
        self.assertIn("structural-empty", temp_ids)
        self.assertIn("node_7bf97ce023f0", temp_ids)
        self.assertIn("node_c670e6117e91", temp_ids)
        self.assertIn("node_a3a6ab6d1310", temp_ids)
        self.assertIn("good-formula", temp_ids)
        self.assertNotIn("node_29ace7e15619", temp_ids)
        node_by_temp_id = {
            temp_id: node
            for node in normalized.nodes
            for temp_id in node.temp_ids
        }
        self.assertEqual(
            node_by_temp_id["node_7bf97ce023f0"].definition,
            "全同粒子组成的系统必须考虑这种不可分辨性。",
        )
        self.assertEqual(
            node_by_temp_id["node_c670e6117e91"].definition,
            "亮度和强度极高",
        )
        self.assertTrue(
            any("安全裁剪" in warning for warning in normalized.warnings)
        )
        self.assertTrue(
            any(
                "node_29ace7e15619" in warning and "重抽取" in warning
                for warning in normalized.warnings
            )
        )

    def test_normalize_repairs_supported_labels_without_rewriting_claims(self):
        supported = {
            "node_95dbb5717f59": (
                "*§28.3 微观粒子的不可分辨性， 费米子和玻色子",
                "*§28.3 微观粒子的不可分辨性， 费米子和玻色子\n"
                "一. 微观粒子的全同性\n"
                "同一种微观粒子的固有性质完全相同。量子物理把这种"
                "不可区分称做“不可分辨性”，或“全同性”。",
                "微观粒子的不可分辨性（全同性）",
            ),
            "node_60c9f83e0a98": (
                "视觉知识",
                "页面下半部分以公式形式给出轨道角动量与自旋角动量的"
                "量子化表达式，以及相应量子数的取值范围与定义。",
                "轨道角动量与自旋角动量的量子化",
            ),
            "node_6fdf30d629c9": (
                "定态条件关键要点",
                "玻尔模型解得的轨道半径与能级公式，r_1标注为"
                "玻尔半径，基态能量约-13.6 eV。",
                "玻尔半径与氢原子基态能量",
            ),
            "node_c6d1501a3300": (
                "五. 激光的特点",
                "五. 激光的特点\n1.相干性极好\n2.方向性极好",
                "激光的相干性与方向性",
            ),
            "node_7789f0e94aa9": (
                "三. 激光器的实例",
                "三. 激光器的实例: He - Ne 气体激光器\n"
                "He是辅助物质，Ne是激活物质，He与Ne之比为5∶1。",
                "He–Ne 激光器的介质组成",
            ),
        }
        partial = {
            "node_29ace7e15619": (
                "这说明原来对原子中电子运动的描述",
                "不完全的",
            ),
            "node_dcd7f15f10b1": (
                "所以考虑到自旋轨道耦合能后，有",
                "所以考虑到自旋轨道耦合能后，有：能级发生分裂。",
            ),
            "node_b39d4bc5104c": (
                "角动量的量子化关键要点",
                "夫兰克—赫兹实验证明原子内部量子化能级的存在。",
            ),
            "node_e18ce90f9925": (
                "例如 l =1时， 而",
                "例如 l =1时，而它们的经典矢量耦合模型为图示。",
            ),
            "node_e00f33f3d2c3": (
                "电子的自旋轨道耦合关键要点",
                "l 小的电子靠近原子核的概率大，能量低。",
            ),
        }
        request_nodes = [
            NodeCandidateIn(
                temp_id=node_id,
                name=name,
                definition=definition,
                type="visual_knowledge"
                if node_id in {
                    "node_60c9f83e0a98",
                    "node_6fdf30d629c9",
                }
                else "concept",
                role="visual_knowledge"
                if node_id in {
                    "node_60c9f83e0a98",
                    "node_6fdf30d629c9",
                }
                else "concept",
                branch_id="formal-label-export",
                evidence=[
                    EvidenceRef(
                        unit_id=f"unit:{node_id}",
                        excerpt=definition,
                    )
                ],
            )
            for node_id, (name, definition, _) in supported.items()
        ]
        request_nodes.extend(
            NodeCandidateIn(
                temp_id=node_id,
                name=name,
                definition=definition,
                branch_id="formal-label-export",
                evidence=[
                    EvidenceRef(
                        unit_id=f"unit:{node_id}",
                        excerpt=definition,
                    )
                ],
            )
            for node_id, (name, definition) in partial.items()
        )

        normalized = normalize_graph(
            NormalizeRequest(
                document_id="doc-label-boundary",
                document_title="量子物理",
                nodes=request_nodes,
            )
        )

        node_by_temp_id = {
            temp_id: node
            for node in normalized.nodes
            for temp_id in node.temp_ids
        }
        self.assertEqual(
            set(node_by_temp_id) & set(supported),
            set(supported),
        )
        self.assertFalse(set(node_by_temp_id) & set(partial))
        for node_id, (_, original_definition, expected_name) in (
            supported.items()
        ):
            with self.subTest(node_id=node_id):
                repaired = node_by_temp_id[node_id]
                self.assertEqual(repaired.name, expected_name)
                self.assertEqual(
                    repaired.definition,
                    original_definition,
                )
                self.assertTrue(
                    any(
                        node_id in warning
                        and "label" in warning
                        and "字段级安全精炼" in warning
                        for warning in normalized.warnings
                    )
                )
        for node_id in partial:
            with self.subTest(node_id=node_id):
                self.assertTrue(
                    any(
                        node_id in warning
                        and "deferred/review" in warning
                        for warning in normalized.warnings
                    )
                )

    def test_normalize_rejects_legacy_coverage_repair_provenance(self):
        normalized = normalize_graph(
            NormalizeRequest(
                document_id="doc-legacy-coverage",
                document_title="激光原理",
                nodes=[
                    NodeCandidateIn(
                        temp_id="root",
                        name="激光原理",
                        type="root_topic",
                        role="root_topic",
                        origin="synthesized_root",
                        is_root_candidate=True,
                        optional=False,
                    ),
                    NodeCandidateIn(
                        temp_id="coverage_legacy",
                        name="粒子数反转",
                        branch_id="coverage-branch",
                        evidence=[
                            EvidenceRef(
                                unit_id="coverage-unit",
                                excerpt="N2大于N1",
                            )
                        ],
                    ),
                    NodeCandidateIn(
                        temp_id="model:population-inversion",
                        name="粒子数反转",
                        branch_id="model-branch",
                        evidence=[
                            EvidenceRef(
                                unit_id="model-unit",
                                excerpt="N2大于N1",
                            )
                        ],
                    ),
                ],
            )
        )

        population_nodes = [
            node for node in normalized.nodes if node.name == "粒子数反转"
        ]
        self.assertEqual(len(population_nodes), 1)
        self.assertEqual(population_nodes[0].branch_id, "model-branch")
        self.assertTrue(
            any(
                "coverage_legacy" in warning and "覆盖补点" in warning
                for warning in normalized.warnings
            )
        )

    def test_normalize_rejects_nonsemantic_export_labels_at_final_boundary(self):
        bad_labels = [
            "这说明原来对原子中电子运动的描述",
            "例如 l =1时， 而",
            "所以考虑到自旋轨道耦合能后，有",
            "视觉知识",
            "并列两个圆形视场照片",
            "年诺贝尔物理学奖获得者 ——泡利",
            "§28.2 电子自旋与自旋轨道耦合",
            "激光的特点关键要点",
        ]
        good_labels = [
            "粒子数反转",
            "斯特恩—盖拉赫实验",
            "受激辐射",
            "能级公式 E_n = E_1/n²",
        ]
        normalized = normalize_graph(
            NormalizeRequest(
                document_id="doc-label-boundary",
                document_title="量子物理",
                nodes=[
                    NodeCandidateIn(
                        temp_id="root",
                        name="量子物理",
                        type="root_topic",
                        role="root_topic",
                        origin="synthesized_root",
                        is_root_candidate=True,
                        confidence=0.95,
                        optional=False,
                    ),
                    *[
                        NodeCandidateIn(
                            temp_id=f"bad-{index}",
                            name=name,
                            branch_id="branch",
                            evidence=[
                                EvidenceRef(
                                    unit_id=f"bad-unit-{index}",
                                    excerpt="真实课件原文",
                                )
                            ],
                        )
                        for index, name in enumerate(bad_labels)
                    ],
                    *[
                        NodeCandidateIn(
                            temp_id=f"good-{index}",
                            name=name,
                            branch_id="branch",
                            evidence=[
                                EvidenceRef(
                                    unit_id=f"good-unit-{index}",
                                    excerpt="真实课件原文",
                                )
                            ],
                        )
                        for index, name in enumerate(good_labels)
                    ],
                ],
            )
        )

        names = {node.name for node in normalized.nodes}
        self.assertTrue(set(good_labels) <= names)
        self.assertTrue(set(bad_labels).isdisjoint(names))
        for label in bad_labels:
            with self.subTest(label=label):
                self.assertTrue(
                    any(label in warning for warning in normalized.warnings)
                )

    def test_explicit_duplicate_cannot_overwrite_branch_topic_identity(self):
        normalized = normalize_graph(
            NormalizeRequest(
                document_id="doc-structural-merge",
                document_title="优化课程",
                nodes=[
                    NodeCandidateIn(
                        temp_id="root",
                        name="优化课程",
                        type="root_topic",
                        role="root_topic",
                        origin="synthesized_root",
                        is_root_candidate=True,
                        confidence=0.95,
                        optional=False,
                    ),
                    NodeCandidateIn(
                        temp_id="structural-topic",
                        name="训练 机制",
                        type="branch_topic",
                        role="branch_topic",
                        origin="structural",
                        branch_id="branch-1",
                        confidence=0.35,
                        optional=False,
                        activation_score=0.4,
                        support_unit_ids=["u-structural"],
                        evidence=[
                            EvidenceRef(
                                unit_id="u-structural",
                                excerpt="本节介绍训练机制。",
                            )
                        ],
                    ),
                    NodeCandidateIn(
                        temp_id="explicit-concept",
                        name="训练机制",
                        type="concept",
                        role="concept",
                        origin="explicit",
                        branch_id="branch-1",
                        confidence=0.99,
                        optional=True,
                        activation_score=0.99,
                        definition="训练机制描述参数如何在迭代中更新。",
                        aliases=["参数更新流程"],
                        evidence=[
                            EvidenceRef(
                                unit_id="u-explicit",
                                excerpt="参数在每轮训练后更新。",
                            )
                        ],
                    ),
                ],
            )
        )

        merged = next(
            node
            for node in normalized.nodes
            if set(node.temp_ids) == {"structural-topic", "explicit-concept"}
        )

        self.assertEqual(merged.name, "训练 机制")
        self.assertEqual(merged.role, "branch_topic")
        self.assertEqual(merged.type, "branch_topic")
        self.assertEqual(merged.origin, "structural")
        self.assertFalse(merged.optional)
        self.assertEqual(
            merged.definition,
            "训练机制描述参数如何在迭代中更新。",
        )
        self.assertIn("训练机制", merged.aliases)
        self.assertIn("参数更新流程", merged.aliases)
        self.assertEqual(
            {item.unit_id for item in merged.evidence},
            {"u-structural", "u-explicit"},
        )

        units = [
            ContentUnit(
                id="u-structural",
                document_id="doc-structural-merge",
                kind="text",
                text="本节介绍训练机制。",
                evidence_excerpt="本节介绍训练机制。",
            ),
            ContentUnit(
                id="u-explicit",
                document_id="doc-structural-merge",
                kind="text",
                text="参数在每轮训练后更新。",
                evidence_excerpt="参数在每轮训练后更新。",
            ),
        ]
        covered, _, _ = coverage_statistics(units, [merged])

        self.assertEqual(covered, {"u-explicit"})


if __name__ == "__main__":
    unittest.main()
