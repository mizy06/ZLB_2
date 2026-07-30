from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from backend.app.mindmap_engine.normalize import normalize_graph
from backend.app.mindmap_engine.schemas import (
    CrossLinkCandidateIn,
    EvidenceRef,
    NodeCandidateIn,
    NormalizeRequest,
    ParentCandidateIn,
    SolveRequest,
)
from backend.app.mindmap_engine.topology import solve_topology
from backend.app.semantic_dedupe import are_mergeable_exact_duplicates


class SemanticDedupeColdImportTDDTests(unittest.TestCase):
    def test_semantic_dedupe_and_agents_import_in_clean_processes(self):
        repository_root = Path(__file__).resolve().parents[2]
        imports = (
            (
                "from backend.app.semantic_dedupe "
                "import are_mergeable_exact_duplicates; "
                "assert callable(are_mergeable_exact_duplicates)"
            ),
            (
                "from backend.app.agents import _select_branch_candidates; "
                "assert callable(_select_branch_candidates)"
            ),
        )

        for statement in imports:
            with self.subTest(statement=statement):
                completed = subprocess.run(
                    [sys.executable, "-c", statement],
                    cwd=repository_root,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    completed.stderr,
                )


def candidate(
    temp_id: str,
    name: str,
    definition: str,
    *,
    type_: str = "concept",
    role: str = "concept",
    origin: str = "explicit",
    branch_id: str | None = "branch-a",
    root: bool = False,
    unit_id: str | None = None,
    page: int | None = None,
    asset_id: str | None = None,
    media_asset_ids: list[str] | None = None,
) -> NodeCandidateIn:
    evidence = []
    if unit_id is not None or page is not None or asset_id is not None:
        evidence.append(
            EvidenceRef(
                unit_id=unit_id,
                chunk_id=(
                    unit_id
                    if unit_id is not None
                    and unit_id.startswith("chunk_")
                    else None
                ),
                excerpt=definition,
                page=page,
                asset_id=asset_id,
            )
        )
    return NodeCandidateIn(
        temp_id=temp_id,
        name=name,
        type=type_,
        role=role,
        definition=definition,
        origin=origin,
        branch_id=branch_id,
        is_root_candidate=root,
        evidence=evidence,
        support_unit_ids=[unit_id] if unit_id is not None else [],
        media_asset_ids=media_asset_ids or [],
    )


def assert_symmetric(
    case: unittest.TestCase,
    expected: bool,
    left: NodeCandidateIn,
    right: NodeCandidateIn,
) -> None:
    case.assertIs(
        are_mergeable_exact_duplicates(left, right),
        expected,
    )
    case.assertIs(
        are_mergeable_exact_duplicates(right, left),
        expected,
    )


def real_export_duplicate_pairs(
) -> tuple[tuple[NodeCandidateIn, NodeCandidateIn], ...]:
    """Five manually adjudicated duplicate pairs from the formal export."""

    return (
        (
            candidate(
                "node_1756c63ce29d",
                "能级公式 E_n = E_1/n²",
                "氢原子第 n 能级的能量等于基态能量 E_1 除以 n 的平方，"
                "体现主量子数对能量的决定作用。",
                type_="formula",
                role="formula",
                branch_id="branch_07d04c9a0a95",
                unit_id="visual:crop_0014",
                page=33,
                asset_id="crop_0014",
                media_asset_ids=["crop_0014"],
            ),
            candidate(
                "node_0e6866b39433",
                "氢原子能级公式",
                "E_n = (1/n²)E₁，其中 E₁ ≈ -13.6 eV 为基态能量，"
                "能级随 n² 反比分布。",
                branch_id="branch_9e086e38d847",
                unit_id="chunk_2a2ed523fb",
                page=9,
                media_asset_ids=["crop_0003"],
            ),
        ),
        (
            candidate(
                "node_291d6cebd7da",
                "角动量 z 分量公式 L_z = m_l ħ",
                "角动量在 z 方向的分量等于磁量子数 m_l "
                "乘以约化普朗克常数 ħ，体现空间量子化。",
                type_="formula",
                role="formula",
                branch_id="branch_07d04c9a0a95",
                unit_id="visual:crop_0016",
                page=33,
                asset_id="crop_0016",
                media_asset_ids=["crop_0016"],
            ),
            candidate(
                "node_aa0d214380e7",
                "Lz本征值谱",
                "氢原子中角动量z分量算符Lz的本征值谱，"
                "本征值为mlℏ，其中ml为磁量子数。",
                branch_id="branch_8b284b12f0fa",
                unit_id="chunk_58793e665b",
                page=19,
            ),
        ),
        (
            candidate(
                "node_0d11c5d3a7c6",
                "银原子束分裂为两束的实验结果",
                "银原子束通过非均匀磁场后在探测屏上形成两条分离的"
                "沉积痕迹，而非连续分布，直接证实了角动量空间量子化。",
                role="observation",
                branch_id="branch_d3319bf7a3be",
                unit_id="chunk_b53b98ed9e",
                page=37,
                media_asset_ids=["crop_0018"],
            ),
            candidate(
                "node_1bba23e210ce",
                "斯特恩—盖拉赫实验",
                "1922年为验证角动量空间量子化而设计的实验，"
                "银原子束通过非均匀磁场后分裂为两束，"
                "证实了角动量的空间量子化。",
                type_="branch_topic",
                role="branch_topic",
                origin="structural",
                branch_id="branch_d3319bf7a3be",
                unit_id="chunk_b53b98ed9e",
                page=37,
                media_asset_ids=["crop_0017", "crop_0018"],
            ),
        ),
        (
            candidate(
                "node_4238e9e9372a",
                "原子实极化示意图",
                "黄色实心圆表示原子实，红点表示正电荷重心，"
                "绿点表示负电荷重心；左侧蓝点表示价电子，"
                "负电荷重心向远离价电子方向偏移，图下标注原子实极化。",
                type_="visual_knowledge",
                role="visual_knowledge",
                branch_id="branch_8cdcbb80a001",
                unit_id="visual:crop_0021",
                page=48,
                asset_id="crop_0021",
                media_asset_ids=["crop_0021"],
            ),
            candidate(
                "node_215ff773f001",
                "原子实极化",
                "价电子排斥原子实负电荷使其重心偏移，形成指向价电子的"
                "偶极子，导致价电子附加负电势能。",
                branch_id="branch_8cdcbb80a001",
                unit_id="chunk_3daf50ed00",
                page=48,
                media_asset_ids=["crop_0021"],
            ),
        ),
        (
            candidate(
                "node_7f13298e6418",
                "激光纵模强度分布示意图",
                "横轴为频率ν，纵轴为强度I；多个等间隔纵模尖峰被"
                "高斯包络线调制，包络峰值为I0，半高线为I0/2；"
                "标注中心频率ν0、纵模间隔Δν_k、谱线宽度Δν。",
                type_="visual_knowledge",
                role="visual_knowledge",
                branch_id="branch_118eaa93f280",
                unit_id="visual:crop_0037",
                page=88,
                asset_id="crop_0037",
                media_asset_ids=["crop_0037"],
            ),
            candidate(
                "node_9ee405fc8d45",
                "纵模强度高斯包络分布",
                "各纵模的强度受增益曲线（高斯包络）调制，"
                "包络峰值为 I₀，半高宽对应谱线宽度 Δν，"
                "在此范围内纵模可振荡输出。",
                branch_id="branch_118eaa93f280",
                unit_id="chunk_1621a13bc7",
                page=88,
                media_asset_ids=["crop_0037"],
            ),
        ),
    )


class ExactFormulaDedupeTDDTests(unittest.TestCase):
    def test_exact_cross_branch_claim_merges_and_aggregates_provenance(self):
        first = candidate(
            "potential-page-17",
            "氢原子中电子的电势能",
            "氢原子中电子的电势能 U = -e^2/(4πε_0r)",
            type_="formula",
            role="formula",
            branch_id="branch-wavefunction",
            unit_id="unit-page-17",
            page=17,
        )
        repeated = candidate(
            "potential-page-24",
            "氢原子中电子的电势能",
            "氢原子中电子的电势能 U = - e^2 / (4πε_0 r)",
            type_="formula",
            role="formula",
            branch_id="branch-radial",
            unit_id="unit-page-24",
            page=24,
        )

        assert_symmetric(self, True, first, repeated)
        normalized = normalize_graph(
            NormalizeRequest(
                document_id="doc",
                document_title="原子物理",
                nodes=[first, repeated],
            )
        )
        merged = next(
            node
            for node in normalized.nodes
            if set(node.temp_ids)
            == {"potential-page-17", "potential-page-24"}
        )
        self.assertEqual(
            {item.page for item in merged.evidence},
            {17, 24},
        )

    def test_same_label_complementary_cross_branch_claims_remain_separate(self):
        formula = candidate(
            "potential-formula",
            "氢原子中电子的电势能",
            "氢原子中电子的电势能 U = -e^2/(4πε_0r)",
            type_="formula",
            role="formula",
            branch_id="branch-wavefunction",
            unit_id="unit-page-17",
            page=17,
        )
        consequence = candidate(
            "potential-consequence",
            "氢原子中电子的电势能",
            "该电势能使束缚态电子的总能量低于零。",
            branch_id="branch-spectrum",
            unit_id="unit-page-24",
            page=24,
        )

        assert_symmetric(self, False, formula, consequence)

    def test_real_cross_modal_formula_pairs_merge_across_pages_and_branches(
        self,
    ):
        for left, right in real_export_duplicate_pairs()[:2]:
            with self.subTest(left=left.temp_id, right=right.temp_id):
                assert_symmetric(self, True, left, right)

    def test_conflicting_formula_relationship_is_rejected(self):
        source_formula = candidate(
            "standing-wave-source",
            "谐振条件",
            "谐振腔驻波条件为 nL=kλ/2。",
            type_="formula",
            role="formula",
            unit_id="chunk-cavity",
            page=80,
        )
        changed_formula = candidate(
            "standing-wave-changed",
            "谐振条件",
            "谐振腔驻波条件为 nkλ/2=L。",
            type_="formula",
            role="formula",
            unit_id="chunk-cavity",
            page=80,
        )

        assert_symmetric(self, False, source_formula, changed_formula)

    def test_internal_wrong_formula_cannot_be_laundered_by_source_evidence(
        self,
    ):
        correct = candidate(
            "standing-wave-correct",
            "谐振腔驻波条件",
            "谐振腔驻波条件为 nL=kλ/2。",
            type_="formula",
            role="formula",
            unit_id="chunk-cavity",
            page=86,
        )
        conflicting_definition = candidate(
            "standing-wave-bad-definition",
            "谐振腔驻波条件",
            "谐振腔驻波条件为 nkλ/2=L。",
            type_="formula",
            role="formula",
            unit_id="chunk-cavity",
            page=86,
        ).model_copy(
            update={
                "evidence": [
                    EvidenceRef(
                        unit_id="chunk-cavity",
                        excerpt="源页驻波条件为 nL=kλ/2。",
                        page=86,
                    )
                ]
            }
        )
        conflicting_name = candidate(
            "standing-wave-bad-name",
            "错误驻波公式 nkλ/2=L",
            "谐振腔驻波边界条件。",
            type_="formula",
            role="formula",
            unit_id="chunk-cavity",
            page=86,
        ).model_copy(
            update={
                "evidence": [
                    EvidenceRef(
                        unit_id="chunk-cavity",
                        excerpt="源页驻波条件为 nL=kλ/2。",
                        page=86,
                    )
                ]
            }
        )

        for corrupted in (
            conflicting_definition,
            conflicting_name,
        ):
            with self.subTest(temp_id=corrupted.temp_id):
                assert_symmetric(self, False, corrupted, correct)

    def test_correct_cross_modal_evidence_can_still_supply_formula_identity(
        self,
    ):
        visual = candidate(
            "standing-wave-visual",
            "谐振腔驻波示意图",
            "图示谐振腔两端的驻波边界条件。",
            type_="visual_knowledge",
            role="visual_knowledge",
            unit_id="visual:crop-cavity",
            page=86,
            asset_id="crop-cavity",
            media_asset_ids=["crop-cavity"],
        ).model_copy(
            update={
                "evidence": [
                    EvidenceRef(
                        unit_id="visual:crop-cavity",
                        excerpt="源页给出 nL=kλ/2。",
                        page=86,
                        asset_id="crop-cavity",
                    )
                ]
            }
        )
        text = candidate(
            "standing-wave-text",
            "谐振腔驻波条件",
            "驻波波长满足 λ=2nL/k。",
            type_="formula",
            role="formula",
            unit_id="chunk-cavity",
            page=86,
        ).model_copy(
            update={
                "evidence": [
                    EvidenceRef(
                        unit_id="chunk-cavity",
                        excerpt="原式为 nL=kλ/2。",
                        page=86,
                    )
                ]
            }
        )

        assert_symmetric(self, True, visual, text)


class ProvenanceGroundedDedupeTDDTests(unittest.TestCase):
    def test_real_non_formula_duplicate_pairs_merge(self):
        for left, right in real_export_duplicate_pairs()[2:]:
            with self.subTest(left=left.temp_id, right=right.temp_id):
                assert_symmetric(self, True, left, right)

    def test_same_page_is_not_semantic_equality(self):
        inversion = candidate(
            "population-inversion",
            "粒子数反转",
            "高能级粒子数 N₂ 大于低能级粒子数 N₁，"
            "是产生光放大的必要条件。",
            unit_id="chunk-laser-slide",
            page=72,
        )
        resonator = candidate(
            "frequency-selection",
            "光学谐振腔选频",
            "光学谐振腔利用边界条件选择允许振荡的频率。",
            unit_id="chunk-laser-slide",
            page=72,
        )

        assert_symmetric(self, False, inversion, resonator)

    def test_shared_media_and_similar_name_do_not_override_different_claims(
        self,
    ):
        polarization = candidate(
            "core-polarization",
            "原子实效应",
            "价电子排斥原子实中的负电荷，引起原子实极化。",
            page=48,
            asset_id="crop-core",
            media_asset_ids=["crop-core"],
        )
        penetration = candidate(
            "orbital-penetration",
            "原子实效应",
            "价电子轨道贯穿原子实区域，改变不同轨道的屏蔽程度。",
            page=48,
            asset_id="crop-core",
            media_asset_ids=["crop-core"],
        )

        assert_symmetric(self, False, polarization, penetration)

    def test_reversed_causality_and_changed_number_are_rejected(self):
        cases = (
            (
                candidate(
                    "cause-forward",
                    "粒子数反转与泵浦",
                    "泵浦过程导致粒子数反转。",
                    unit_id="chunk-cause",
                    page=73,
                ),
                candidate(
                    "cause-reversed",
                    "粒子数反转与泵浦",
                    "粒子数反转导致泵浦过程。",
                    unit_id="chunk-cause",
                    page=73,
                ),
            ),
            (
                candidate(
                    "efficiency-30",
                    "转换效率",
                    "该激光器的能量转换效率为30%。",
                    unit_id="chunk-efficiency",
                    page=91,
                ),
                candidate(
                    "efficiency-40",
                    "转换效率",
                    "该激光器的能量转换效率为40%。",
                    unit_id="chunk-efficiency",
                    page=91,
                ),
            ),
        )

        for left, right in cases:
            with self.subTest(left=left.temp_id, right=right.temp_id):
                assert_symmetric(self, False, left, right)


class StructuralProtectionTDDTests(unittest.TestCase):
    def test_roots_and_two_structural_topics_are_never_semantically_merged(
        self,
    ):
        root = candidate(
            "root",
            "量子物理",
            "课程总主题。",
            type_="root_topic",
            role="root_topic",
            origin="synthesized_root",
            branch_id=None,
            root=True,
            unit_id="chunk-root",
            page=1,
        )
        concept = candidate(
            "root-like-concept",
            "量子物理",
            "课程总主题。",
            unit_id="chunk-root",
            page=1,
        )
        topic_a = candidate(
            "topic-a",
            "角动量空间量子化",
            "角动量投影只能取分立值。",
            type_="branch_topic",
            role="branch_topic",
            origin="structural",
            branch_id="branch-a",
            unit_id="chunk-topic",
            page=30,
        )
        topic_b = candidate(
            "topic-b",
            "角动量空间量子化",
            "角动量投影只能取分立值。",
            type_="branch_topic",
            role="branch_topic",
            origin="structural",
            branch_id="branch-a",
            unit_id="chunk-topic",
            page=30,
        )

        assert_symmetric(self, False, root, concept)
        assert_symmetric(self, False, topic_a, topic_b)

    def test_structural_parent_and_complementary_child_are_both_kept(self):
        topic = candidate(
            "stern-gerlach-topic",
            "斯特恩—盖拉赫实验",
            "银原子束通过非均匀磁场后分裂为两束，"
            "证实角动量空间量子化。",
            type_="branch_topic",
            role="branch_topic",
            origin="structural",
            branch_id="branch-sg",
            unit_id="chunk-sg",
            page=37,
        )
        contradiction = candidate(
            "old-theory-contradiction",
            "旧量子理论与实验的矛盾",
            "旧理论中银原子基态满足 l=0，预言银原子束应形成一束，"
            "但实验观察到两束；这一矛盾说明旧理论失败。",
            role="observation",
            branch_id="branch-sg",
            unit_id="chunk-sg",
            page=37,
        )

        assert_symmetric(self, False, topic, contradiction)


class FormalCheckpointOvermergeRegressionTDDTests(unittest.TestCase):
    def test_shared_heuristic_placeholder_is_not_a_material_claim(self):
        first = candidate(
            "branch_f82e2e76f51c:tmp_004fe786",
            "对玻尔氢原子理论的回顾",
            "文档中出现的主题或术语",
            branch_id="branch_f82e2e76f51c",
            unit_id="chunk_192971b064",
            page=2,
        ).model_copy(
            update={
                "evidence": [
                    EvidenceRef(
                        unit_id="chunk_192971b064",
                        excerpt="一.对玻尔氢原子理论的回顾",
                        page=2,
                    )
                ]
            }
        )
        second = candidate(
            "branch_f82e2e76f51c:tmp_1c8db253",
            "卢瑟福原子核式模型",
            "文档中出现的主题或术语",
            branch_id="branch_f82e2e76f51c",
            unit_id="chunk_192971b064",
            page=2,
        ).model_copy(
            update={
                "evidence": [
                    EvidenceRef(
                        unit_id="chunk_192971b064",
                        excerpt="1. 卢瑟福原子核式模型",
                        page=2,
                    )
                ]
            }
        )

        assert_symmetric(self, False, first, second)

    def test_trivial_shared_assignments_do_not_merge_different_claims(self):
        principal_quantum_number = candidate(
            "branch_07d04c9a0a95:node_2",
            "主量子数 n",
            "取值为 n = 1, 2, 3, …，决定氢原子电子的能量（能级）。",
            branch_id="branch_07d04c9a0a95",
            unit_id="chunk_eab7419cdd",
            page=33,
        )
        radial_maximum = candidate(
            "branch_07d04c9a0a95:node_8",
            "基态径向概率最大处为玻尔半径",
            "当 n=1, l=0（基态）时，电子径向概率密度在 "
            "r = a₀（玻尔半径）处取最大值。",
            role="key_result",
            branch_id="branch_07d04c9a0a95",
            unit_id="chunk_eab7419cdd",
            page=31,
        )
        bohr_quantization = candidate(
            "branch_9e086e38d847:node_3",
            "量子化条件",
            "玻尔假设电子轨道角动量量子化，mvr = nħ，"
            "n = 1, 2, 3…",
            branch_id="branch_9e086e38d847",
            unit_id="chunk_ed4a6e490f",
            page=7,
        )

        assert_symmetric(
            self,
            False,
            principal_quantum_number,
            radial_maximum,
        )
        assert_symmetric(
            self,
            False,
            principal_quantum_number,
            bohr_quantization,
        )

    def test_one_shared_formula_does_not_absorb_a_broader_formula_panel(self):
        lz_formula = candidate(
            "branch_07d04c9a0a95:node_7",
            "角动量 z 分量公式 L_z = m_l ħ",
            "角动量在 z 方向的分量等于磁量子数 m_l "
            "乘以约化普朗克常数 ħ，体现空间量子化。",
            type_="formula",
            role="formula",
            branch_id="branch_07d04c9a0a95",
            unit_id="visual:crop_0016",
            page=33,
            asset_id="crop_0016",
        )
        broader_panel = candidate(
            "branch_2740b390de3c:visual:crop_0019",
            "轨道角动量与自旋角动量的量子化",
            "页面下半部分给出 L = √(l(l+1))ℏ、"
            "L_z = m_l ħ、S = √(s(s+1))ℏ、"
            "S_z = m_s ħ，以及各量子数的取值范围。",
            type_="visual_knowledge",
            role="visual_knowledge",
            branch_id="branch_2740b390de3c",
            unit_id="visual:crop_0019",
            page=41,
            asset_id="crop_0019",
        )

        assert_symmetric(self, False, lz_formula, broader_panel)

    def test_structural_topic_does_not_absorb_one_supported_child_claim(self):
        branch_topic = candidate(
            "topic:branch_486286f9be82",
            "全同粒子统计与泡利不相容原理",
            "覆盖微观粒子不可分辨性、波函数对称与反对称、"
            "费米子与玻色子的分类、泡利不相容原理的表述",
            type_="branch_topic",
            role="branch_topic",
            origin="structural",
            branch_id="branch_486286f9be82",
            unit_id="chunk_93ebac4102",
            page=56,
        )
        spin_statistics = candidate(
            "branch_486286f9be82:node_9",
            "自旋-统计定理（自旋决定对称类型）",
            "全同粒子按自旋分为两类：半整数自旋→反对称（费米子），"
            "整数自旋→对称（玻色子），自旋决定了波函数的交换对称性。",
            origin="abstractive",
            branch_id="branch_486286f9be82",
            unit_id="chunk_93ebac4102",
            page=56,
        )

        assert_symmetric(self, False, branch_topic, spin_statistics)

    def test_shared_page_vocabulary_does_not_merge_complementary_facts(self):
        cases = (
            (
                candidate(
                    "branch_3c03a41b7dc6:node_7",
                    "壳层",
                    "具有相同主量子数n的电子组成一个壳层，"
                    "依次记为K, L, M, N, O, P…",
                    branch_id="branch_3c03a41b7dc6",
                    unit_id="chunk_1039fd3f0e",
                    page=60,
                ),
                candidate(
                    "branch_3c03a41b7dc6:node_8",
                    "支壳层",
                    "具有相同n和l的电子组成一个支壳层，"
                    "依次记为s, p, d, f, g, h…",
                    branch_id="branch_3c03a41b7dc6",
                    unit_id="chunk_1039fd3f0e",
                    page=60,
                ),
            ),
            (
                candidate(
                    "branch_8cdcbb80a001:node_2",
                    "量子数亏损",
                    "碱金属能级公式中修正主量子数的参数，"
                    "反映价电子能量低于同主量子数氢原子能级的程度",
                    branch_id="branch_8cdcbb80a001",
                    unit_id="chunk_0b9aead0cd",
                    page=49,
                ),
                candidate(
                    "branch_8cdcbb80a001:node_3",
                    "碱金属能级低于氢原子能级",
                    "由于轨道贯穿和原子实极化，碱金属中主量子数为n的"
                    "价电子能量低于相同n的氢原子电子能量",
                    branch_id="branch_8cdcbb80a001",
                    unit_id="chunk_0b9aead0cd",
                    page=49,
                ),
            ),
            (
                candidate(
                    "branch_486286f9be82:node_7",
                    "泡利不相容原理",
                    "不能有两个全同的费米子处于同一单量子态；"
                    "当A=B时反对称波函数恒为零，由此导出该原理。",
                    branch_id="branch_486286f9be82",
                    unit_id="chunk_d254389069",
                    page=57,
                ),
                candidate(
                    "branch_486286f9be82:node_8",
                    "玻色子不受泡利不相容原理制约",
                    "对称波函数在A=B时不为零，因此一个单量子态"
                    "可容纳多个玻色子。",
                    branch_id="branch_486286f9be82",
                    unit_id="chunk_d254389069",
                    page=57,
                ),
            ),
        )

        for left, right in cases:
            with self.subTest(left=left.temp_id, right=right.temp_id):
                assert_symmetric(self, False, left, right)


class NormalizeSemanticDedupeIntegrationTDDTests(unittest.TestCase):
    @staticmethod
    def _root() -> NodeCandidateIn:
        return candidate(
            "root",
            "量子物理",
            "课程总主题。",
            type_="root_topic",
            role="root_topic",
            origin="synthesized_root",
            branch_id=None,
            root=True,
            unit_id="document:title",
            page=1,
        )

    def _normalize_gold_pairs(
        self,
        *,
        reverse: bool = False,
    ):
        pairs = real_export_duplicate_pairs()
        children = [item for pair in pairs for item in pair]
        if reverse:
            children.reverse()
        root = self._root()
        parent_candidates = [
            ParentCandidateIn(
                parent=root.temp_id,
                child=item.temp_id,
                score=0.94 - index * 0.01,
                classification="direct_parent",
                verifier_score=0.9,
                evidence=[
                    EvidenceRef(
                        unit_id=f"edge:{item.temp_id}",
                        excerpt=f"{root.name}包含{item.name}",
                    )
                ],
            )
            for index, item in enumerate(children)
        ]
        normalized = normalize_graph(
            NormalizeRequest(
                document_id="formal-export-semantic-dedupe",
                document_title="量子物理",
                nodes=[root, *children],
                parent_candidates=parent_candidates,
                cross_links=[
                    CrossLinkCandidateIn(
                        source=pairs[0][1].temp_id,
                        target=pairs[3][0].temp_id,
                        relation="depends_on",
                        score=0.91,
                        evidence=[
                            EvidenceRef(
                                unit_id="edge:cross-modal",
                                excerpt="能级关系用于解释原子实效应。",
                            )
                        ],
                    )
                ],
            )
        )
        return pairs, normalized

    def test_normalize_merges_all_five_gold_pairs_and_preserves_provenance(
        self,
    ):
        pairs, normalized = self._normalize_gold_pairs()
        self.assertEqual(len(normalized.nodes), 6)

        node_by_temp_id = {
            temp_id: node
            for node in normalized.nodes
            for temp_id in node.temp_ids
        }
        for left, right in pairs:
            with self.subTest(left=left.temp_id, right=right.temp_id):
                merged = node_by_temp_id[left.temp_id]
                self.assertIs(merged, node_by_temp_id[right.temp_id])
                self.assertEqual(
                    set(merged.temp_ids),
                    {left.temp_id, right.temp_id},
                )
                expected_units = {
                    *left.support_unit_ids,
                    *right.support_unit_ids,
                }
                self.assertTrue(
                    expected_units <= set(merged.support_unit_ids)
                )
                evidence_units = {
                    item.unit_id or item.chunk_id
                    for item in merged.evidence
                    if item.unit_id or item.chunk_id
                }
                self.assertTrue(expected_units <= evidence_units)
                self.assertTrue(
                    {
                        *left.media_asset_ids,
                        *right.media_asset_ids,
                    }
                    <= set(merged.media_asset_ids)
                )
                self.assertTrue(
                    {left.name, right.name}
                    <= {merged.name, *merged.aliases}
                )

        stern_gerlach = node_by_temp_id["node_1bba23e210ce"]
        self.assertEqual(stern_gerlach.name, "斯特恩—盖拉赫实验")
        self.assertEqual(stern_gerlach.type, "branch_topic")
        self.assertEqual(stern_gerlach.role, "branch_topic")
        self.assertEqual(stern_gerlach.origin, "structural")

        node_ids = {node.id for node in normalized.nodes}
        self.assertTrue(normalized.parent_candidates)
        self.assertTrue(
            all(
                edge.parent_id in node_ids and edge.child_id in node_ids
                for edge in normalized.parent_candidates
            )
        )
        self.assertEqual(len(normalized.cross_links), 1)
        self.assertTrue(
            all(
                edge.source_id in node_ids and edge.target_id in node_ids
                for edge in normalized.cross_links
            )
        )
        self.assertEqual(
            normalized.cross_links[0].source_id,
            node_by_temp_id["node_0e6866b39433"].id,
        )
        self.assertEqual(
            normalized.cross_links[0].target_id,
            node_by_temp_id["node_4238e9e9372a"].id,
        )

        solved = solve_topology(SolveRequest(graph=normalized))
        self.assertTrue(solved.quality.topology_valid)
        self.assertEqual(len(solved.tree_edges), len(solved.nodes) - 1)
        reachable = {solved.root_id}
        while True:
            expanded = {
                edge.target
                for edge in solved.tree_edges
                if edge.source in reachable
            }
            if expanded <= reachable:
                break
            reachable.update(expanded)
        self.assertEqual(reachable, node_ids)
        self.assertTrue(
            any("语义等价" in warning for warning in normalized.warnings)
        )

    def test_semantic_survivor_and_merged_fields_are_input_order_independent(
        self,
    ):
        pairs, forward = self._normalize_gold_pairs()
        _, reverse = self._normalize_gold_pairs(reverse=True)

        forward_by_pair = {
            frozenset(node.temp_ids): node
            for node in forward.nodes
        }
        reverse_by_pair = {
            frozenset(node.temp_ids): node
            for node in reverse.nodes
        }
        for pair in pairs:
            key = frozenset(item.temp_id for item in pair)
            with self.subTest(pair=sorted(key)):
                left = forward_by_pair[key]
                right = reverse_by_pair[key]
                self.assertEqual(
                    left.model_dump(),
                    right.model_dump(),
                )

    def test_structural_scaffold_is_absorbed_into_its_exact_claim_cluster(
        self,
    ):
        observation, topic_claim = real_export_duplicate_pairs()[2]
        explicit_topic_claim = topic_claim.model_copy(
            update={
                "temp_id": "stern-gerlach-explicit",
                "type": "concept",
                "role": "experiment",
                "origin": "explicit",
            }
        )
        scaffold = topic_claim.model_copy(
            update={
                "temp_id": "topic:branch_d3319bf7a3be",
                "definition": "电子自旋与自旋轨道耦合下的局部主题",
                "evidence": [],
                "support_unit_ids": [
                    "chunk_b53b98ed9e",
                    "visual:crop_0018",
                ],
                "media_asset_ids": [],
            }
        )
        normalized = normalize_graph(
            NormalizeRequest(
                document_id="semantic-scaffold-absorption",
                document_title="量子物理",
                nodes=[
                    self._root(),
                    explicit_topic_claim,
                    observation,
                    scaffold,
                ],
            )
        )

        merged = next(
            node
            for node in normalized.nodes
            if explicit_topic_claim.temp_id in node.temp_ids
        )
        self.assertEqual(
            set(merged.temp_ids),
            {
                explicit_topic_claim.temp_id,
                observation.temp_id,
                scaffold.temp_id,
            },
        )
        self.assertEqual(merged.name, "斯特恩—盖拉赫实验")
        self.assertEqual(merged.role, "branch_topic")
        self.assertEqual(merged.origin, "structural")
        self.assertIn("chunk_b53b98ed9e", merged.support_unit_ids)
        self.assertTrue(merged.evidence)

    def test_semantic_merge_does_not_truncate_source_evidence(self):
        left, right = real_export_duplicate_pairs()[0]
        left_evidence = [
            EvidenceRef(
                unit_id=f"left-unit-{index}",
                excerpt=f"E_n = E_1/n² 左侧证据 {index}",
                page=index + 1,
            )
            for index in range(12)
        ]
        right_evidence = [
            EvidenceRef(
                unit_id=f"right-unit-{index}",
                excerpt=f"E_n = E_1/n² 右侧证据 {index}",
                page=index + 21,
            )
            for index in range(12)
        ]
        left = left.model_copy(
            update={
                "evidence": left_evidence,
                "support_unit_ids": [
                    item.unit_id for item in left_evidence
                ],
            }
        )
        right = right.model_copy(
            update={
                "evidence": right_evidence,
                "support_unit_ids": [
                    item.unit_id for item in right_evidence
                ],
            }
        )

        normalized = normalize_graph(
            NormalizeRequest(
                document_id="semantic-evidence-union",
                document_title="量子物理",
                nodes=[self._root(), left, right],
            )
        )
        merged = next(
            node
            for node in normalized.nodes
            if left.temp_id in node.temp_ids
        )
        expected_units = {
            *(item.unit_id for item in left_evidence),
            *(item.unit_id for item in right_evidence),
        }
        self.assertEqual(
            {
                item.unit_id
                for item in merged.evidence
                if item.unit_id
            },
            expected_units,
        )
        self.assertEqual(
            set(merged.explicit_evidence_unit_ids),
            expected_units,
        )
        self.assertEqual(
            set(merged.support_unit_ids),
            expected_units,
        )

    def test_normalize_does_not_merge_protected_or_conflicting_claims(self):
        root = self._root()
        root_like = candidate(
            "root-like-concept",
            "量子物理",
            "课程总主题。",
            branch_id="branch-root-like",
            unit_id="chunk-root",
            page=1,
        )
        structural_a = candidate(
            "structural-a",
            "角动量空间量子化",
            "角动量投影只能取分立值。",
            type_="branch_topic",
            role="branch_topic",
            origin="structural",
            branch_id="branch-structural",
            unit_id="chunk-structural",
            page=30,
        )
        structural_b = structural_a.model_copy(
            update={"temp_id": "structural-b"}
        )
        protected_pairs = [
            (root, root_like),
            (structural_a, structural_b),
            (
                candidate(
                    "standing-wave-source",
                    "谐振条件",
                    "谐振腔驻波条件为 nL=kλ/2。",
                    type_="formula",
                    role="formula",
                    branch_id="branch-formula",
                    unit_id="chunk-cavity",
                    page=80,
                ),
                candidate(
                    "standing-wave-changed",
                    "谐振条件",
                    "谐振腔驻波条件为 nkλ/2=L。",
                    type_="formula",
                    role="formula",
                    branch_id="branch-formula",
                    unit_id="chunk-cavity",
                    page=80,
                ),
            ),
            (
                candidate(
                    "efficiency-30",
                    "转换效率",
                    "该激光器的能量转换效率为30%。",
                    branch_id="branch-number",
                    unit_id="chunk-efficiency",
                    page=91,
                ),
                candidate(
                    "efficiency-40",
                    "转换效率",
                    "该激光器的能量转换效率为40%。",
                    branch_id="branch-number",
                    unit_id="chunk-efficiency",
                    page=91,
                ),
            ),
            (
                candidate(
                    "cause-forward",
                    "粒子数反转与泵浦",
                    "泵浦过程导致粒子数反转。",
                    branch_id="branch-cause",
                    unit_id="chunk-cause",
                    page=73,
                ),
                candidate(
                    "cause-reversed",
                    "粒子数反转与泵浦",
                    "粒子数反转导致泵浦过程。",
                    branch_id="branch-cause",
                    unit_id="chunk-cause",
                    page=73,
                ),
            ),
            (
                candidate(
                    "core-polarization",
                    "原子实效应",
                    "价电子排斥原子实中的负电荷，引起原子实极化。",
                    branch_id="branch-core",
                    page=48,
                    asset_id="crop-core",
                    media_asset_ids=["crop-core"],
                ),
                candidate(
                    "orbital-penetration",
                    "原子实效应",
                    "价电子轨道贯穿原子实区域，改变不同轨道的屏蔽程度。",
                    branch_id="branch-core",
                    page=48,
                    asset_id="crop-core",
                    media_asset_ids=["crop-core"],
                ),
            ),
            (
                candidate(
                    "stern-gerlach-topic",
                    "斯特恩—盖拉赫实验",
                    "银原子束通过非均匀磁场后分裂为两束，"
                    "证实角动量空间量子化。",
                    type_="branch_topic",
                    role="branch_topic",
                    origin="structural",
                    branch_id="branch-sg",
                    unit_id="chunk-sg",
                    page=37,
                ),
                candidate(
                    "old-theory-contradiction",
                    "旧量子理论与实验的矛盾",
                    "旧理论中银原子基态满足 l=0，预言银原子束应形成一束，"
                    "但实验观察到两束；这一矛盾说明旧理论失败。",
                    role="observation",
                    branch_id="branch-sg",
                    unit_id="chunk-sg",
                    page=37,
                ),
            ),
        ]
        unique = {
            item.temp_id: item
            for pair in protected_pairs
            for item in pair
        }
        normalized = normalize_graph(
            NormalizeRequest(
                document_id="semantic-dedupe-negative-controls",
                document_title="量子物理",
                nodes=list(unique.values()),
            )
        )
        node_by_temp_id = {
            temp_id: node
            for node in normalized.nodes
            for temp_id in node.temp_ids
        }
        self.assertEqual(set(node_by_temp_id), set(unique))
        for left, right in protected_pairs:
            with self.subTest(left=left.temp_id, right=right.temp_id):
                self.assertNotEqual(
                    node_by_temp_id[left.temp_id].id,
                    node_by_temp_id[right.temp_id].id,
                )

    def test_semantic_clustering_requires_pairwise_compatibility(self):
        root = self._root()
        nodes = [
            candidate(
                "claim-a",
                "命题甲",
                "第一个命题。",
                branch_id="branch-chain",
                unit_id="chunk-chain",
            ),
            candidate(
                "claim-b",
                "命题乙",
                "第二个命题。",
                branch_id="branch-chain",
                unit_id="chunk-chain",
            ),
            candidate(
                "claim-c",
                "命题丙",
                "第三个冲突命题。",
                branch_id="branch-chain",
                unit_id="chunk-chain",
            ),
        ]
        mergeable_pairs = {
            frozenset({"claim-a", "claim-b"}),
            frozenset({"claim-b", "claim-c"}),
        }

        def mergeable(left: NodeCandidateIn, right: NodeCandidateIn) -> bool:
            return (
                frozenset({left.temp_id, right.temp_id})
                in mergeable_pairs
            )

        with patch(
            "backend.app.mindmap_engine.normalize."
            "are_mergeable_exact_duplicates",
            side_effect=mergeable,
            create=True,
        ):
            normalized = normalize_graph(
                NormalizeRequest(
                    document_id="semantic-dedupe-complete-link",
                    document_title="量子物理",
                    nodes=[root, *nodes],
                )
            )

        clusters = {
            frozenset(node.temp_ids)
            for node in normalized.nodes
            if not node.is_root_candidate
        }
        self.assertEqual(
            clusters,
            {
                frozenset({"claim-a", "claim-b"}),
                frozenset({"claim-c"}),
            },
        )


if __name__ == "__main__":
    unittest.main()
