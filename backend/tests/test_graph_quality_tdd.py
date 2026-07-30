from __future__ import annotations

import json
import unittest

from backend.app.agents import (
    RoleRuntime,
    ThemeNodeSpec,
    ThemePlanOutput,
    _branch_scout,
    _granularity_critic,
    _select_branch_candidates,
    _validate_branch_extraction_payload,
    audit_coverage,
    build_branch_plans,
    build_global_parent_candidates,
    canonicalize_semantic_duplicates,
    coverage_statistics,
    run_branch_teams,
    theme_nodes,
    verify_parent_candidates,
)
from backend.app.architecture_schemas import (
    BranchPlan,
    ContentUnit,
    ModelSelection,
)
from backend.app.cplus_pipeline import _enrich_result, quality_gate_failures
from backend.app.mindmap_engine.normalize import (
    candidate_field_disposition,
    definition_quality_issues,
    is_publishable_label,
    label_quality_issues,
    normalize_graph,
)
from backend.app.mindmap_engine.schemas import (
    EvidenceRef,
    EngineQualityReport,
    NodeCandidateIn,
    NormalizeRequest,
    NormalizedGraph,
    NormalizedNode,
    NormalizedParentCandidate,
    ParentCandidateIn,
    ReviewItem,
    SolveRequest,
    SolveResponse,
    TreeEdge,
)
from backend.app.mindmap_engine.topology import (
    TopologyLimits,
    solve_topology,
)
from backend.app.schemas import Chunk, ParsedDocument


def evidence(unit_id: str, excerpt: str = "可审计原文") -> EvidenceRef:
    return EvidenceRef(unit_id=unit_id, chunk_id=unit_id, excerpt=excerpt)


def real_export_claim_candidates() -> dict[str, NodeCandidateIn]:
    cases = {
        "node_7bf97ce023f0": (
            "全同粒子组成的系统必须考虑这种不可分辨性",
            "全同粒子组成的系统必须考虑这种不可分辨性。\n"
            "以两个粒子组成的系统为例： 设粒子1、2均可分别处在"
            "状态A或B，相应波函数分别为\uf079A(1) 、\uf079A(2)、"
            "\uf079B(1)、\uf079B(2)；\n"
            "设它们组成的系统的波函数为\uf079 (1,2)，"
            "则由于粒子不可分辨，应有：\n\n即 54",
            "chunk_a817710541",
        ),
        "node_816f1764f4b6": (
            "吸收（absorption）",
            "2. 吸收（absorption）\n"
            "若原子处在某个能量为E1的低能级，另有某个能量为E2"
            "的高能级。 当入射光子的能量h\uf06e 等于 E2 −E1时，"
            "原子就可能吸收光 E ● N 2 2 子而从低能级跃迁到高能级，"
            " h\uf06e 这个过程称为吸收。 E1 ● N1\n\n"
            "设 N1、N2 分别为单位体积中处于E1 、E2能级的原子数。"
            "则单位体积中单位时间内，因吸收光子而从 E1",
            "chunk_a04f049a01",
        ),
        "node_dc3bf4e60d44": (
            "受激辐射有光放大作用",
            "受激辐射有光放大作用： E2 ● N2 全同光子"
            "（频率、相位、振动方 h\uf06e 向和传播方向相同） "
            "E1 ● N 好激光器： 1 单位体积中单位时间内，"
            "从E2→ E1的受激辐\n\n射的原子数为\n\n"
            "W21 =B21·\uf072(\uf06e、T)——单个原子在单位时间内"
            "发生受激辐射过程的概率。\nB21—— 受激辐射系数 71",
            "chunk_9436b09bf5",
        ),
        "node_c670e6117e91": (
            "亮度和强度极高",
            "3.亮度和强度极高：\n亮度： B～ ～\n\n"
            "\uf044p 光源亮度：\n\n\uf044\uf057 \uf044S\n\n"
            "强度：非聚焦状态 I > 聚焦状态可达到脉冲瞬时功率"
            "可达 > 10 14 W 可产生108K的高温，"
            "引起核聚变第28章结束 92",
            "chunk_d80f816aa9",
        ),
        "node_29ace7e15619": (
            "这说明原来对原子中电子运动的描述",
            "不完全的",
            "chunk_7aa8563d93",
        ),
        "node_a3a6ab6d1310": (
            "粒子数反转",
            "高能级粒子数N2大于低能级粒子数N1的非热平衡态，"
            "是产生光放大的必要条件",
            "chunk_9c75f7a2a9",
        ),
    }
    return {
        node_id: NodeCandidateIn(
            temp_id=node_id,
            name=name,
            definition=definition,
            branch_id="formal-export",
            evidence=[evidence(unit_id)],
        )
        for node_id, (name, definition, unit_id) in cases.items()
    }


def real_export_label_candidates() -> dict[str, NodeCandidateIn]:
    cases = {
        "node_95dbb5717f59": (
            "*§28.3 微观粒子的不可分辨性， 费米子和玻色子",
            "*§28.3 微观粒子的不可分辨性， 费米子和玻色子\n"
            "一. 微观粒子的全同性\n"
            "同一种微观粒子的质量、自旋、电荷等固有性质都是完全"
            "相同的，不能区分。不过经典理论尚可根据运动轨道来区分"
            "同种粒子。而根据量子理论，微观粒子的运动状态是用波函数"
            "描写的，它们并没有确定的轨道，因此也是不可区分的。"
            "量子物理把这称做“不可分辨性”， 或“全同性”。 53",
            "concept",
            "chunk_5975b6b439",
        ),
        "node_60c9f83e0a98": (
            "视觉知识",
            "页面下半部分以公式形式给出轨道角动量与自旋角动量的"
            "量子化表达式，以及相应量子数的取值范围与定义。",
            "visual_knowledge",
            "visual:crop_0019",
        ),
        "node_6fdf30d629c9": (
            "定态条件关键要点",
            "玻尔模型解得的轨道半径与能级公式，r_1标注为玻尔半径，"
            "给出数值5.29×10^-11 m，基态能量约-13.6 eV。",
            "visual_knowledge",
            "visual:crop_0003",
        ),
        "node_c6d1501a3300": (
            "五. 激光的特点",
            "五. 激光的特点\n"
            "1.相干性极好\n"
            "\uf0a8时间相干性好，相干长度可达几十公里。\n"
            "\uf0a8空间相干性好，激光波面上各个点可以做到都是相干的。\n"
            "2.方向性极好\n"
            "发散角可小到 \uf07e10 -4rad（\uf07e0.1\uf0a2）\n\n"
            "投射到月球（38万公里）光斑直径仅约 2公里，"
            "测地—月距离精度达几厘米。 91",
            "concept",
            "chunk_a1982b6323",
        ),
        "node_7789f0e94aa9": (
            "三. 激光器的实例",
            "三. 激光器的实例: He - Ne 气体激光器\n"
            "He —Ne 气体激光器的粒子数反转\n\n"
            "He是辅助物质，Ne是激活物质， "
            "He与 Ne之比为5∶1 \uf07e 10∶1 。\n\n77",
            "concept",
            "chunk_3574cc3034",
        ),
        "node_29ace7e15619": (
            "这说明原来对原子中电子运动的描述",
            "不完全的",
            "concept",
            "chunk_7aa8563d93",
        ),
        "node_dcd7f15f10b1": (
            "所以考虑到自旋轨道耦合能后，有",
            "所以考虑到自旋轨道耦合能后，有：\n\n"
            "这样，一个与量子数 n、l 对应的能级就分裂成了两个"
            "能级。相应于该能级跃迁的一条谱线，就分成了两条谱线。"
            "自旋轨道耦合引起的能量差很小，典型值\uf07e10 -5eV。"
            "所以能级分裂形成的两条谱线的波长十分接近，这样形成的"
            "光谱线组合，称作光谱的精细结构（fine structure）。 51",
            "concept",
            "chunk_86e8798c94",
        ),
        "node_b39d4bc5104c": (
            "角动量的量子化关键要点",
            "夫兰克—赫兹实验（点击） 用低速电子轰击汞原子，"
            "观察它们之间的相互作用和能量传递过程，从而证明原子"
            "内部量子化能级的存在。\n\n"
            "汞原子的第一激发态能级4.9eV\n\n"
            "玻尔理论与夫兰克—赫兹实验在物理学的发展史中起到了"
            "重要的作用。",
            "concept",
            "chunk_15c92912d5",
        ),
        "node_e18ce90f9925": (
            "例如 l =1时， 而",
            "例如 l =1时， 而\n\n"
            "它们的经典矢量耦合模型图为： j =3/2 j =1/2\n\n"
            "考虑到自旋轨道耦合，原子的状态可表示为：\n\n"
            "轨道角动量量子量子数 l 的代号，"
            "l = 0,1,2,3,4\uf0bc对应S,P,D,F,G \uf0bc "
            "n j 如： n = 3 l = 1 3P3/2 "
            "主量子数 总角动量量子量子数 j = 3/2 44",
            "concept",
            "chunk_54a5ac444b",
        ),
        "node_e00f33f3d2c3": (
            "电子的自旋轨道耦合关键要点",
            "回忆n相同， l 不同的电子 P21 P20 n = 2 径向概率分布\n\n"
            "分析非常靠近 0 4 原子核的情况 l 小的靠近 "
            "P32 P31P30 n = 3\n\n核的概率大， 能量低。 0 9\n\n47",
            "concept",
            "chunk_a6eeac8d37",
        ),
    }
    return {
        node_id: NodeCandidateIn(
            temp_id=node_id,
            name=name,
            definition=definition,
            type=role,
            role=role,
            branch_id="formal-label-export",
            evidence=[evidence(unit_id, definition)],
        )
        for node_id, (name, definition, role, unit_id) in cases.items()
    }


def normalized_node(
    node_id: str,
    name: str,
    *,
    role: str = "concept",
    origin: str = "explicit",
    branch_id: str | None = "b1",
    optional: bool = True,
    root: bool = False,
    confidence: float = 0.8,
    support: list[str] | None = None,
    with_evidence: bool = True,
) -> NormalizedNode:
    unit_id = f"u:{node_id}"
    return NormalizedNode(
        id=node_id,
        temp_ids=[node_id],
        name=name,
        type="root_topic" if root else role,
        role="root_topic" if root else role,
        definition=f"{name}定义",
        aliases=[],
        origin="synthesized_root" if root else origin,
        branch_id=None if root else branch_id,
        confidence=confidence,
        optional=False if root else optional,
        activation_score=confidence,
        activation_cost=0.05,
        is_root_candidate=root,
        evidence=[evidence(unit_id)] if with_evidence else [],
        support_unit_ids=support or ([unit_id] if with_evidence else []),
        media_asset_ids=[],
    )


class BatchVerifierClient:
    def __init__(self, *, bad_ids: bool = False):
        self.calls: list[dict] = []
        self.bad_ids = bad_ids

    async def complete_json(self, **kwargs):
        payload = json.loads(kwargs["user_prompt"])
        self.calls.append(payload)
        children = []
        for child_item in payload["children"]:
            child_id = (
                "unknown-child"
                if self.bad_ids
                else child_item["child"]["id"]
            )
            evaluations = []
            for index, item in enumerate(child_item["candidates"]):
                evaluations.append(
                    {
                        "parent_id": (
                            "unknown-parent"
                            if self.bad_ids and index == 0
                            else item["parent"]["id"]
                        ),
                        "classification": (
                            "direct_parent" if index == 0 else "sibling"
                        ),
                        "verifier_score": (
                            0.92 if index == 0 else 0.25
                        ),
                        "reason": "批量比较后的直接父判断",
                    }
                )
            children.append(
                {
                    "child_id": child_id,
                    "evaluations": evaluations,
                }
            )
        return {"children": children}


class AttachOnlyBranchClient:
    def __init__(self):
        self.prompt: dict = {}

    async def complete_json(self, **kwargs):
        self.prompt = json.loads(kwargs["user_prompt"])
        return {
            "nodes": [
                {
                    "temp_id": "bad-media-node",
                    "name": "装饰性配图",
                    "type": "concept",
                    "origin": "explicit",
                    "confidence": 0.9,
                    "evidence": [
                        {
                            "unit_id": "visual-attach",
                            "excerpt": "仅作为附近文字的说明配图",
                        }
                    ],
                }
            ],
            "cross_links": [],
        }


class PartiallyMalformedBranchClient:
    async def complete_json(self, **_kwargs):
        return {
            "nodes": [
                {
                    "temp_id": "valid-node",
                    "name": "波函数概率密度",
                    "definition": "概率密度由波函数模平方给出。",
                    "origin": "explicit",
                    "confidence": 0.92,
                    "evidence": [
                        {
                            "unit_id": "u1",
                            "excerpt": "概率密度由波函数模平方给出",
                        }
                    ],
                    "support_unit_ids": ["u1"],
                }
            ],
            "cross_links": [
                {
                    "source": "波函数",
                    "target": "概率密度",
                    "relation": "causes",
                    "score": 0.8,
                    "evidence": ["u1"],
                }
            ],
        }


class NonObjectBranchClient:
    async def complete_json(self, **_kwargs):
        return ["unexpected", "top-level", "array"]


class ClaimFidelityBranchClient:
    async def complete_json(self, **_kwargs):
        return {
            "nodes": [
                {
                    "temp_id": "conflicting-standing-wave",
                    "name": "谐振腔驻波条件",
                    "definition": "谐振腔驻波条件为 nkλ/2=L。",
                    "origin": "explicit",
                    "confidence": 0.95,
                    "evidence": [
                        {
                            "unit_id": "standing-wave",
                            "excerpt": "驻波条件为 nL=kλ/2",
                        }
                    ],
                    "support_unit_ids": ["standing-wave"],
                },
                {
                    "temp_id": "dimensionless-linewidth",
                    "name": "超高稳频线宽",
                    "definition": "输出线宽可小到10^-15量级。",
                    "origin": "explicit",
                    "confidence": 0.9,
                    "evidence": [
                        {
                            "unit_id": "linewidth",
                            "excerpt": "相对线宽 Δν/ν≈10^-15",
                        }
                    ],
                    "support_unit_ids": ["linewidth"],
                },
                {
                    "temp_id": "conflicting-formula-label",
                    "name": "驻波公式 nkλ/2=L",
                    "definition": "谐振腔驻波边界条件。",
                    "origin": "explicit",
                    "confidence": 0.9,
                    "evidence": [
                        {
                            "unit_id": "standing-wave",
                            "excerpt": "驻波条件为 nL=kλ/2",
                        }
                    ],
                    "support_unit_ids": ["standing-wave"],
                },
                {
                    "temp_id": "supported-ratio",
                    "name": "相对线宽",
                    "definition": "相对线宽满足 Δν/ν≈10^-15。",
                    "origin": "explicit",
                    "confidence": 0.92,
                    "evidence": [
                        {
                            "unit_id": "linewidth",
                            "excerpt": "相对线宽 Δν/ν≈10^-15",
                        }
                    ],
                    "support_unit_ids": ["linewidth"],
                },
            ],
            "cross_links": [],
        }


class SoftClaimFidelityBranchClient:
    async def complete_json(self, **_kwargs):
        return {
            "nodes": [
                {
                    "temp_id": "soft-missing-formula",
                    "name": "氢原子能级",
                    "definition": "氢原子能级满足 E_n=E_1/n²。",
                    "origin": "explicit",
                    "confidence": 0.88,
                    "evidence": [
                        {
                            "unit_id": "energy-level",
                            "excerpt": "氢原子能级随主量子数变化",
                        }
                    ],
                    "support_unit_ids": ["energy-level"],
                }
            ],
            "cross_links": [],
        }


class GraphQualityTDDTests(unittest.IsolatedAsyncioTestCase):
    def test_non_object_branch_payload_is_a_fallback_safe_validation_error(self):
        with self.assertRaisesRegex(ValueError, "JSON 对象"):
            _validate_branch_extraction_payload([])  # type: ignore[arg-type]

    def test_branch_budget_keeps_one_candidate_per_supported_unit_first(self):
        candidates = [
            NodeCandidateIn(
                temp_id="u1-high",
                name="单元一高分候选",
                confidence=0.98,
                evidence=[evidence("u1")],
            ),
            NodeCandidateIn(
                temp_id="u1-second",
                name="单元一次高分候选",
                confidence=0.95,
                evidence=[evidence("u1")],
            ),
            NodeCandidateIn(
                temp_id="u2-lower",
                name="单元二必要候选",
                confidence=0.62,
                evidence=[evidence("u2")],
            ),
        ]

        selected = _select_branch_candidates(
            candidates,
            coverage_budget=2,
            unit_order=["u1", "u2"],
        )

        self.assertEqual(len(selected), 2)
        self.assertEqual(
            {
                ref.unit_id
                for candidate in selected
                for ref in candidate.evidence
            },
            {"u1", "u2"},
        )
        self.assertIn("u1-high", {candidate.temp_id for candidate in selected})

    def test_branch_budget_merges_duplicate_temp_ids_without_losing_units(self):
        selected = _select_branch_candidates(
            [
                NodeCandidateIn(
                    temp_id="duplicate-id",
                    name="高分表述",
                    confidence=0.9,
                    evidence=[evidence("u1")],
                ),
                NodeCandidateIn(
                    temp_id="duplicate-id",
                    name="补充表述",
                    confidence=0.8,
                    evidence=[evidence("u2")],
                ),
            ],
            coverage_budget=2,
            unit_order=["u1", "u2"],
        )

        self.assertEqual(len(selected), 1)
        self.assertEqual(
            {ref.unit_id for ref in selected[0].evidence},
            {"u1", "u2"},
        )
        self.assertIn("补充表述", selected[0].aliases)

    def test_review_view_keeps_the_selected_subject_when_previewing_members(self):
        root = normalized_node("root", "课程体系", root=True)
        parent = normalized_node(
            "parent",
            "父主题",
            role="branch_topic",
            origin="structural",
            optional=False,
        )
        child = normalized_node("child", "子主题")
        root_parent = TreeEdge(
            id="edge-root-parent",
            source=root.id,
            target=parent.id,
            score=0.9,
            evidence=[evidence("u:parent")],
        )
        parent_child = TreeEdge(
            id="edge-parent-child",
            source=parent.id,
            target=child.id,
            score=0.8,
            evidence=[evidence("u:child")],
        )
        normalized = NormalizedGraph(
            document_id="doc",
            document_title="课程体系",
            nodes=[root, parent, child],
            parent_candidates=[
                NormalizedParentCandidate(
                    parent_id=root.id,
                    child_id=parent.id,
                    score=0.9,
                    classification="direct_parent",
                    evidence=[evidence("u:parent")],
                ),
                NormalizedParentCandidate(
                    parent_id=parent.id,
                    child_id=child.id,
                    score=0.8,
                    classification="direct_parent",
                    evidence=[evidence("u:child")],
                ),
            ],
            cross_links=[],
        )
        solved = SolveResponse(
            document_id="doc",
            root_id=root.id,
            nodes=[root, parent, child],
            tree_edges=[root_parent, parent_child],
            cross_links=[],
            review_items=[
                ReviewItem(
                    id="review-parent-choice",
                    type="competing_parent",
                    risk_score=0.8,
                    # Deliberately put the selected child first. Preview
                    # iteration order must not overwrite the chosen subject.
                    subject_ids=[child.id, parent.id],
                    reason="父边存在竞争",
                )
            ],
            quality=EngineQualityReport(
                node_count=3,
                tree_edge_count=2,
                cross_link_count=0,
                root_count=1,
                orphan_count=0,
                conflict_count=0,
                provisional_edge_count=0,
                evidence_coverage=1,
                topology_valid=True,
            ),
            solver_status="OPTIMAL",
        )

        result = _enrich_result(
            {
                "task_id": "task-review-subject",
                "run_id": "run-review-subject",
                "mode": "standard",
                "document": ParsedDocument(
                    document_id="doc",
                    filename="course.md",
                    file_type="md",
                    title="课程体系",
                    blocks=[],
                ),
                "chunks": [],
                "content_units": [],
                "assets": [],
                "normalized_graph": normalized,
                "parent_votes": {},
                "solve_response": solved,
                "extraction_mode": "heuristic",
                "model_selection": ModelSelection(
                    generator_provider="heuristic",
                    verifier_provider="deterministic",
                ),
                "warnings": [],
                "degraded_components": [],
            }
        )

        self.assertEqual(result.review_items[0].subject_id, child.id)
        self.assertEqual(result.review_items[0].subject_type, "tree_edge")

    def test_final_content_unit_status_tracks_selected_nodes_not_candidate_pool(self):
        root = normalized_node("root", "课程体系", root=True)
        dropped = normalized_node("dropped", "低价值摘录").model_copy(
            update={
                "evidence": [
                    EvidenceRef(unit_id="u1", excerpt="低价值摘录原文")
                ],
                "support_unit_ids": [],
            }
        )
        normalized = NormalizedGraph(
            document_id="doc",
            document_title="课程体系",
            nodes=[root, dropped],
            parent_candidates=[],
            cross_links=[],
        )
        solved = SolveResponse(
            document_id="doc",
            root_id=root.id,
            nodes=[root],
            tree_edges=[],
            cross_links=[],
            review_items=[],
            quality=EngineQualityReport(
                node_count=1,
                tree_edge_count=0,
                cross_link_count=0,
                root_count=1,
                orphan_count=0,
                conflict_count=0,
                provisional_edge_count=0,
                evidence_coverage=1,
                topology_valid=True,
            ),
            solver_status="OPTIMAL",
        )
        unit = ContentUnit(
            id="u1",
            document_id="doc",
            kind="text",
            text="低价值摘录原文",
            evidence_excerpt="低价值摘录原文",
            importance=0.8,
            # This is the pre-solve candidate-pool state.
            status="covered",
        )

        result = _enrich_result(
            {
                "task_id": "task-final-coverage",
                "run_id": "run-final-coverage",
                "mode": "standard",
                "document": ParsedDocument(
                    document_id="doc",
                    filename="course.md",
                    file_type="md",
                    title="课程体系",
                    blocks=[],
                ),
                "chunks": [],
                "content_units": [unit],
                "assets": [],
                "normalized_graph": normalized,
                "parent_votes": {},
                "solve_response": solved,
                "extraction_mode": "heuristic",
                "model_selection": ModelSelection(
                    generator_provider="heuristic",
                    verifier_provider="deterministic",
                ),
                "warnings": [],
                "degraded_components": [],
            }
        )

        self.assertEqual(result.content_units[0].status, "deferred")
        self.assertEqual(
            result.quality_report.coverage.uncovered_unit_ids,
            ["u1"],
        )

    def test_label_gate_rejects_known_truncation_patterns(self):
        malformed = [
            "的光谱结构（即使",
            "但是",
            "原子沉积层不",
            "[上文衔接]",
            "与管壁碰",
            "微观粒子的运动状态是用波函数描",
        ]
        for label in malformed:
            with self.subTest(label=label):
                self.assertFalse(is_publishable_label(label))
        self.assertTrue(is_publishable_label("微观粒子的波函数描述"))
        for valid_label in ["素描", "触碰", "学生参与", "知识普及", "亲和"]:
            with self.subTest(valid_label=valid_label):
                self.assertTrue(is_publishable_label(valid_label))

    def test_label_gate_rejects_real_export_sentence_stems_and_media_captions(
        self,
    ):
        malformed = [
            "这说明原来对原子中电子运动的描述",
            "例如 l =1时， 而",
            "所以考虑到自旋轨道耦合能后，有",
            "提出了原子能量量子化",
            "视觉知识",
            "并列两个圆形视场照片",
            "蓝框公式",
            "对比示意图",
            "年诺贝尔物理学奖获得者 ——泡利",
            "1945年诺贝尔物理学奖获得者——泡利",
            "§28.2 电子自旋与自旋轨道耦合",
            "五. 激光的特点",
            "光学谐振腔关键要点",
        ]
        for label in malformed:
            with self.subTest(label=label):
                self.assertFalse(is_publishable_label(label))

        valid = [
            "粒子数反转",
            "斯特恩—盖拉赫实验",
            "受激辐射",
            "电子自旋假设的提出",
            "测量角动量",
            "能级公式 E_n = E_1/n²",
            "角动量 z 分量 L_z = m_l ħ",
            "角动量量子量子数",
        ]
        for label in valid:
            with self.subTest(label=label):
                self.assertTrue(is_publishable_label(label))

    async def test_granularity_gate_drops_malformed_labels(self):
        state = await _granularity_critic(
            {
                "nodes": [
                    NodeCandidateIn(
                        temp_id="bad",
                        name="的光谱结构（即使",
                        evidence=[evidence("u1")],
                    ),
                    NodeCandidateIn(
                        temp_id="good",
                        name="光谱结构",
                        evidence=[evidence("u1")],
                    ),
                ],
                "warnings": [],
            }
        )
        self.assertEqual([node.name for node in state["nodes"]], ["光谱结构"])
        self.assertTrue(any("资格门" in item for item in state["warnings"]))

    async def test_granularity_gate_drops_real_export_garbage_labels(self):
        rejected = [
            "这说明原来对原子中电子运动的描述",
            "例如 l =1时， 而",
            "所以考虑到自旋轨道耦合能后，有",
            "视觉知识",
            "并列两个圆形视场照片",
            "年诺贝尔物理学奖获得者 ——泡利",
            "§28.2 电子自旋与自旋轨道耦合",
        ]
        retained = [
            "粒子数反转",
            "斯特恩—盖拉赫实验",
            "受激辐射",
            "能级公式 E_n = E_1/n²",
        ]
        state = await _granularity_critic(
            {
                "nodes": [
                    NodeCandidateIn(
                        temp_id=f"candidate-{index}",
                        name=name,
                        type=(
                            "formula"
                            if name == "能级公式 E_n = E_1/n²"
                            else "concept"
                        ),
                        role=(
                            "formula"
                            if name == "能级公式 E_n = E_1/n²"
                            else "concept"
                        ),
                        definition="有完整原文支持的课程知识。",
                        evidence=[evidence(f"u-{index}")],
                    )
                    for index, name in enumerate([*rejected, *retained])
                ],
                "warnings": [],
            }
        )

        self.assertEqual(
            {node.name for node in state["nodes"]},
            set(retained),
        )
        for label in rejected:
            with self.subTest(label=label):
                self.assertTrue(
                    any(
                        label in warning and "资格门" in warning
                        for warning in state["warnings"]
                    )
                )

    def test_label_gate_rejects_bare_quantities_and_untyped_equations(self):
        for label in (
            "6328Å",
            "3.39μm",
            "5895.92Å",
        ):
            with self.subTest(label=label):
                self.assertIn(
                    "bare_quantity",
                    label_quality_issues(label),
                )

        for label in (
            "j = 3/2",
            "m_核 >> m_e ⇒ μ⃗_核 << μ⃗_e ⇒ μ⃗_核",
        ):
            with self.subTest(label=label):
                self.assertIn(
                    "formula_label_requires_formula_role",
                    label_quality_issues(label),
                )

        self.assertEqual(
            label_quality_issues(
                "E_n = E_1/n²",
                allow_formula_label=True,
            ),
            [],
        )

    def test_definition_gate_rejects_real_export_fragments_only(self):
        malformed = [
            (
                "全同粒子组成的系统必须考虑不可分辨性。"
                "由于粒子不可分辨，应有：即 54"
            ),
            (
                "单位体积中单位时间内，因吸收光子而从 E1"
            ),
            (
                "强度：非聚焦状态 I > 聚焦状态可达到"
                "脉冲瞬时功率可达 > 10¹⁴ W。"
            ),
            "不完全的",
            "n □ j 主量子数，总角动量量子数 j = 3/2 }",
            (
                "全同光子的频率与相位相同，E1 ● N "
                "好激光器：1 单位体积中发生受激辐射。"
            ),
            "跃迁概率 W21 =",
        ]
        for definition in malformed:
            with self.subTest(definition=definition):
                self.assertTrue(definition_quality_issues(definition))

        valid = [
            "高能级粒子数大于低能级粒子数。",
            "电子的内禀角动量。",
            "不能有两个全同费米子处于同一量子态。",
            "E_n = E_1/n²",
            "L_z = m_l ħ",
            "粒子数反转是 N₂>N₁ 的非热平衡态。",
            "波函数是对称的。",
            "该过程是可逆的。",
        ]
        for definition in valid:
            with self.subTest(definition=definition):
                self.assertEqual(definition_quality_issues(definition), [])

    def test_real_export_claim_disposition_repairs_four_and_reextracts_one(
        self,
    ):
        candidates = real_export_claim_candidates()
        repair_ids = {
            "node_7bf97ce023f0",
            "node_816f1764f4b6",
            "node_dc3bf4e60d44",
            "node_c670e6117e91",
        }
        supported_label_ids = {
            *repair_ids,
            "node_a3a6ab6d1310",
        }
        for node_id in supported_label_ids:
            with self.subTest(node_id=node_id):
                candidate = candidates[node_id]
                disposition = candidate_field_disposition(candidate)
                self.assertEqual(disposition.label_issues, ())
                expected = (
                    "trim_definition_keep_claim"
                    if node_id in repair_ids
                    else "accept"
                )
                self.assertEqual(disposition.action, expected)
                self.assertEqual(
                    definition_quality_issues(disposition.definition),
                    [],
                )
                if expected == "trim_definition_keep_claim":
                    self.assertNotEqual(
                        disposition.definition,
                        candidate.definition,
                    )

        rejected = candidate_field_disposition(
            candidates["node_29ace7e15619"]
        )
        self.assertEqual(rejected.action, "reject_entire_node")
        self.assertTrue(rejected.label_issues)
        self.assertTrue(rejected.definition_issues)

        raw_section = NodeCandidateIn(
            temp_id="structural-section",
            name="§28.2 电子自旋与自旋轨道耦合",
            type="branch_topic",
            role="branch_topic",
            origin="structural",
            definition="",
            support_unit_ids=["section-unit"],
        )
        section_disposition = candidate_field_disposition(raw_section)
        self.assertEqual(section_disposition.action, "accept")
        self.assertTrue(section_disposition.allow_section_label)

    def test_real_export_label_disposition_repairs_supported_claims_only(
        self,
    ):
        candidates = real_export_label_candidates()
        repaired_names = {
            "node_95dbb5717f59": "微观粒子的不可分辨性（全同性）",
            "node_60c9f83e0a98": "轨道角动量与自旋角动量的量子化",
            "node_6fdf30d629c9": "玻尔半径与氢原子基态能量",
            "node_c6d1501a3300": "激光的相干性与方向性",
            "node_7789f0e94aa9": "He–Ne 激光器的介质组成",
        }
        for node_id, expected_name in repaired_names.items():
            with self.subTest(node_id=node_id):
                candidate = candidates[node_id]
                disposition = candidate_field_disposition(candidate)
                self.assertEqual(
                    disposition.action,
                    "repair_label_keep_claim",
                )
                self.assertEqual(disposition.name, expected_name)
                self.assertEqual(
                    disposition.definition,
                    candidate.definition,
                )
                self.assertTrue(disposition.label_issues)
                self.assertTrue(is_publishable_label(disposition.name))

        partial_actions = {
            "node_29ace7e15619": "reject_entire_node",
            "node_dcd7f15f10b1": "reextract_candidate",
            "node_b39d4bc5104c": "reextract_candidate",
            "node_e18ce90f9925": "reextract_candidate",
            "node_e00f33f3d2c3": "reextract_candidate",
        }
        for node_id, expected_action in partial_actions.items():
            with self.subTest(node_id=node_id):
                disposition = candidate_field_disposition(
                    candidates[node_id]
                )
                self.assertEqual(disposition.action, expected_action)
                self.assertEqual(
                    disposition.name,
                    candidates[node_id].name,
                )

    async def test_granularity_gate_repairs_safe_fields_and_defers_hard_case(
        self,
    ):
        candidates = real_export_claim_candidates()
        structural = NodeCandidateIn(
            temp_id="structural-section",
            name="§28.2 电子自旋与自旋轨道耦合",
            type="branch_topic",
            role="branch_topic",
            origin="structural",
            definition="",
            support_unit_ids=["structural-unit"],
        )
        state = await _granularity_critic(
            {
                "nodes": [*candidates.values(), structural],
                "warnings": [],
            }
        )

        repaired_ids = {
            "node_7bf97ce023f0",
            "node_816f1764f4b6",
            "node_dc3bf4e60d44",
            "node_c670e6117e91",
        }
        self.assertEqual(
            {node.temp_id for node in state["nodes"]},
            {
                *repaired_ids,
                "node_a3a6ab6d1310",
                "structural-section",
            },
        )
        state_by_id = {node.temp_id: node for node in state["nodes"]}
        for node_id in repaired_ids:
            with self.subTest(node_id=node_id):
                self.assertNotEqual(
                    state_by_id[node_id].definition,
                    candidates[node_id].definition,
                )
                self.assertTrue(
                    any(
                        node_id in warning and "安全裁剪" in warning
                        for warning in state["warnings"]
                    )
                )
        self.assertTrue(
            any(
                "node_29ace7e15619" in warning
                and "重抽取" in warning
                for warning in state["warnings"]
            )
        )

        uncovered = ContentUnit(
            id="chunk_7aa8563d93",
            document_id="doc",
            kind="text",
            text="这说明原来对原子中电子运动的描述是不完全的。",
            evidence_excerpt="这说明原来对原子中电子运动的描述是不完全的。",
        )
        updated, additions, _ = audit_coverage(
            [uncovered],
            state["nodes"],
            [BranchPlan(id="b1", label="电子自旋", unit_ids=[uncovered.id])],
        )
        self.assertEqual(updated[0].status, "deferred")
        self.assertEqual(additions, [])

    async def test_granularity_gate_repairs_supported_labels_only(self):
        candidates = real_export_label_candidates()
        state = await _granularity_critic(
            {
                "nodes": list(candidates.values()),
                "warnings": [],
            }
        )

        expected_names = {
            "node_95dbb5717f59": "微观粒子的不可分辨性（全同性）",
            "node_60c9f83e0a98": "轨道角动量与自旋角动量的量子化",
            "node_6fdf30d629c9": "玻尔半径与氢原子基态能量",
            "node_c6d1501a3300": "激光的相干性与方向性",
            "node_7789f0e94aa9": "He–Ne 激光器的介质组成",
        }
        state_by_id = {node.temp_id: node for node in state["nodes"]}
        self.assertEqual(set(state_by_id), set(expected_names))
        for node_id, expected_name in expected_names.items():
            with self.subTest(node_id=node_id):
                repaired = state_by_id[node_id]
                original = candidates[node_id]
                self.assertEqual(repaired.name, expected_name)
                self.assertEqual(repaired.definition, original.definition)
                self.assertEqual(repaired.evidence, original.evidence)
                self.assertEqual(
                    repaired.support_unit_ids,
                    original.support_unit_ids,
                )
                self.assertTrue(
                    any(
                        node_id in warning
                        and "label" in warning
                        and "字段级安全精炼" in warning
                        for warning in state["warnings"]
                    )
                )

        for node_id in set(candidates) - set(expected_names):
            with self.subTest(node_id=node_id):
                self.assertTrue(
                    any(
                        node_id in warning
                        and "deferred/review" in warning
                        for warning in state["warnings"]
                    )
                )

    def test_leaf_planning_rejects_predicate_sentence_stem(self):
        labels = [
            "1. 提出了原子能量量子化。",
            "定态条件：电子处于定态时不辐射能量。",
            "玻尔半径描述氢原子的基态尺度。",
            "斯特恩—盖拉赫实验：银原子束分裂为两束。",
            "电子自旋是假设的内禀角动量。",
            "自旋轨道耦合形成总角动量。",
            "受激辐射：入射光子诱导同频同相光子。",
            "粒子数反转是产生激光的必要条件。",
            "光学谐振腔用于选频和光振荡。",
        ]
        units = [
            ContentUnit(
                id=f"u{index}",
                document_id="doc",
                kind="text",
                text=label,
                heading_path=["氢原子与激光"],
                evidence_excerpt=label,
                page=index,
            )
            for index, label in enumerate(labels, start=1)
        ]
        plans = build_branch_plans(
            ThemePlanOutput(
                root_candidates=[],
                branch_topics=[
                    ThemeNodeSpec(
                        temp_id="topic",
                        name="氢原子与激光",
                        support_unit_ids=[unit.id for unit in units],
                        confidence=0.9,
                    )
                ],
            ),
            units,
            max_units_per_leaf=3,
        )

        leaf_labels = [plan.label for plan in plans if plan.leaf]
        self.assertEqual(leaf_labels[0], "定态条件")
        self.assertNotIn("提出了原子能量量子化", leaf_labels)
        self.assertTrue(all(is_publishable_label(label) for label in leaf_labels))

    async def test_heuristic_fallback_is_optional_and_observable(self):
        branch = BranchPlan(
            id="b1",
            label="监督学习",
            unit_ids=["u1"],
            coverage_budget=3,
        )
        chunk = Chunk(
            id="u1",
            index=0,
            heading="监督学习",
            text="监督学习\n监督学习是指使用带标签样本进行训练。",
        )
        unit = ContentUnit(
            id="u1",
            document_id="doc",
            kind="text",
            text=chunk.text,
            heading_path=["监督学习"],
            evidence_excerpt=chunk.text,
        )
        state = await _branch_scout(
            {
                "branch": branch,
                "units": [unit],
                "chunks": [chunk],
                "runtime": RoleRuntime(
                    provider="qwen",
                    model="test",
                    client=None,
                    available=False,
                    unavailable_reason="离线测试",
                ),
                "warnings": [],
            }
        )
        self.assertTrue(state["nodes"])
        self.assertTrue(all(node.optional for node in state["nodes"]))
        self.assertLessEqual(len(state["nodes"]), branch.coverage_budget)
        self.assertTrue(any("本地抽取" in item for item in state["warnings"]))

    async def test_attach_as_media_is_context_only_not_a_standalone_node(self):
        client = AttachOnlyBranchClient()
        branch = BranchPlan(
            id="b1",
            label="量子态演化",
            unit_ids=["visual-attach"],
            coverage_budget=3,
        )
        unit = ContentUnit(
            id="visual-attach",
            document_id="doc",
            kind="visual",
            importance=0.6,
            status="uncovered",
            summary="仅作为附近文字的说明配图",
            evidence_excerpt="仅作为附近文字的说明配图",
            asset_id="asset-1",
            visual_action="attach_as_media",
            knowledge_score=0.6,
        )

        state = await _branch_scout(
            {
                "branch": branch,
                "units": [unit],
                "chunks": [],
                "runtime": RoleRuntime(
                    provider="qwen",
                    model="test",
                    client=client,
                    available=True,
                ),
                "warnings": [],
            }
        )

        prompt_unit = client.prompt["content_units"][0]
        self.assertEqual(prompt_unit["visual_action"], "attach_as_media")
        self.assertEqual(prompt_unit["knowledge_claims"], [])
        self.assertEqual(state["nodes"], [])
        self.assertTrue(
            any("attach_as_media" in warning for warning in state["warnings"])
        )

    def test_unfused_attach_as_media_is_deferred_not_coverage_repaired(self):
        branch = BranchPlan(
            id="b-attach-audit",
            label="量子态演化",
            unit_ids=["visual-attach"],
            coverage_budget=3,
        )
        unit = ContentUnit(
            id="visual-attach",
            document_id="doc",
            kind="visual",
            importance=0.8,
            status="uncovered",
            summary="仅作为附近文字的说明配图",
            evidence_excerpt="仅作为附近文字的说明配图",
            asset_id="asset-attach",
            visual_action="attach_as_media",
            knowledge_score=0.9,
        )

        updated, additions, warnings = audit_coverage(
            [unit],
            [],
            [branch],
        )

        self.assertEqual(additions, [])
        self.assertEqual(updated[0].status, "deferred")
        self.assertTrue(any("attach_as_media" in item for item in warnings))

    async def test_malformed_cross_link_does_not_discard_valid_model_nodes(self):
        branch = BranchPlan(
            id="b-partial-schema",
            label="波函数与概率",
            unit_ids=["u1"],
            coverage_budget=3,
        )
        unit = ContentUnit(
            id="u1",
            document_id="doc",
            kind="text",
            text="概率密度由波函数模平方给出",
            evidence_excerpt="概率密度由波函数模平方给出",
        )

        state = await _branch_scout(
            {
                "branch": branch,
                "units": [unit],
                "chunks": [],
                "runtime": RoleRuntime(
                    provider="qwen",
                    model="qwen3.8-max-preview",
                    client=PartiallyMalformedBranchClient(),
                    available=True,
                ),
                "warnings": [],
            }
        )

        self.assertTrue(state["used_model"])
        self.assertEqual(
            [node.name for node in state["nodes"]],
            ["波函数概率密度"],
        )
        self.assertEqual(state["cross_links"], [])
        self.assertTrue(
            any("cross_link" in warning for warning in state["warnings"])
        )

    async def test_non_object_branch_payload_falls_back_without_crashing(self):
        branch = BranchPlan(
            id="b-non-object",
            label="波函数与概率",
            unit_ids=["u1"],
            coverage_budget=3,
        )
        unit = ContentUnit(
            id="u1",
            document_id="doc",
            kind="text",
            text="概率密度由波函数模平方给出",
            evidence_excerpt="概率密度由波函数模平方给出",
        )

        state = await _branch_scout(
            {
                "branch": branch,
                "units": [unit],
                "chunks": [],
                "runtime": RoleRuntime(
                    provider="qwen",
                    model="qwen3.8-max-preview",
                    client=NonObjectBranchClient(),
                    available=True,
                ),
                "warnings": [],
            }
        )

        self.assertFalse(state["used_model"])
        self.assertTrue(
            any("顶层必须是对象" in warning for warning in state["warnings"])
        )

    async def test_branch_claim_gate_defers_only_deterministic_hard_errors(
        self,
    ):
        branch = BranchPlan(
            id="b-claim-hard",
            label="激光谐振腔",
            unit_ids=["standing-wave", "linewidth"],
            coverage_budget=6,
        )
        units = [
            ContentUnit(
                id="standing-wave",
                document_id="doc",
                kind="text",
                text="驻波条件为 nL=kλ/2（k=1,2,3,…）。",
                evidence_excerpt="驻波条件为 nL=kλ/2",
                page=86,
            ),
            ContentUnit(
                id="linewidth",
                document_id="doc",
                kind="text",
                text="超高稳频时相对线宽 Δν/ν≈10^-15。",
                evidence_excerpt="相对线宽 Δν/ν≈10^-15",
                page=85,
            ),
        ]

        state = await _branch_scout(
            {
                "branch": branch,
                "units": units,
                "chunks": [],
                "runtime": RoleRuntime(
                    provider="qwen",
                    model="test",
                    client=ClaimFidelityBranchClient(),
                    available=True,
                ),
                "warnings": [],
            }
        )

        self.assertTrue(state["used_model"])
        self.assertEqual(
            [node.temp_id for node in state["nodes"]],
            [f"{branch.id}:supported-ratio"],
        )
        self.assertTrue(
            any(
                "conflicting_relation" in warning
                and "conflicting-standing-wave" in warning
                for warning in state["warnings"]
            )
        )
        self.assertTrue(
            any(
                "extreme_scientific_value_missing_dimension" in warning
                and "dimensionless-linewidth" in warning
                for warning in state["warnings"]
            )
        )

    async def test_branch_claim_gate_keeps_soft_extraction_gaps(
        self,
    ):
        branch = BranchPlan(
            id="b-claim-soft",
            label="氢原子能级",
            unit_ids=["energy-level"],
            coverage_budget=3,
        )
        unit = ContentUnit(
            id="energy-level",
            document_id="doc",
            kind="text",
            text="氢原子能级随主量子数变化。",
            evidence_excerpt="氢原子能级随主量子数变化",
            page=9,
        )

        state = await _branch_scout(
            {
                "branch": branch,
                "units": [unit],
                "chunks": [],
                "runtime": RoleRuntime(
                    provider="qwen",
                    model="test",
                    client=SoftClaimFidelityBranchClient(),
                    available=True,
                ),
                "warnings": [],
            }
        )

        self.assertTrue(state["used_model"])
        self.assertEqual(
            [node.temp_id for node in state["nodes"]],
            [f"{branch.id}:soft-missing-formula"],
        )
        self.assertTrue(
            any(
                "unsupported_relation" in warning
                and "保留候选" in warning
                for warning in state["warnings"]
            )
        )

    def test_structural_topics_do_not_self_certify_coverage(self):
        unit = ContentUnit(
            id="u1",
            document_id="doc",
            kind="text",
            text="[上文衔接]",
            evidence_excerpt="[上文衔接]",
            importance=0.8,
        )
        topic = NodeCandidateIn(
            temp_id="topic:b1",
            name="量子力学",
            role="branch_topic",
            type="branch_topic",
            origin="abstractive",
            branch_id="b1",
            support_unit_ids=["u1"],
        )
        plan = BranchPlan(id="b1", label="量子力学", unit_ids=["u1"])

        updated, additions, warnings = audit_coverage([unit], [topic], [plan])

        self.assertEqual(updated[0].status, "deferred")
        self.assertEqual(additions, [])
        self.assertTrue(any("资格门" in warning for warning in warnings))

    def test_coverage_audit_defers_uncovered_unit_without_creating_node(self):
        unit = ContentUnit(
            id="u1",
            document_id="doc",
            kind="text",
            text="梯度下降通过迭代更新参数来降低损失函数。",
            evidence_excerpt="梯度下降通过迭代更新参数来降低损失函数。",
            importance=0.8,
        )
        plan = BranchPlan(id="b1", label="优化方法", unit_ids=["u1"])

        updated, additions, _ = audit_coverage([unit], [], [plan])

        self.assertEqual(updated[0].status, "deferred")
        self.assertEqual(additions, [])

    def test_coverage_audit_never_turns_raw_export_units_into_nodes(self):
        raw_units = [
            ContentUnit(
                id="sentence-stem",
                document_id="doc",
                kind="text",
                text="所以考虑到自旋轨道耦合能后，有：",
                evidence_excerpt="所以考虑到自旋轨道耦合能后，有：",
                importance=0.8,
            ),
            ContentUnit(
                id="biography",
                document_id="doc",
                kind="text",
                text=(
                    "1945年诺贝尔物理学奖获得者 ——泡利\n"
                    "奥地利人 Wolfgang Pauli 1900—1958"
                ),
                evidence_excerpt="1945年诺贝尔物理学奖获得者 ——泡利",
                importance=0.8,
            ),
            ContentUnit(
                id="raw-section",
                document_id="doc",
                kind="text",
                text=(
                    "§28.2 电子自旋与自旋轨道耦合\n"
                    "本页包含较长的原始OCR段落。"
                ),
                evidence_excerpt="§28.2 电子自旋与自旋轨道耦合",
                importance=0.8,
            ),
            ContentUnit(
                id="photo-caption",
                document_id="doc",
                kind="visual",
                summary="并列两个圆形视场照片",
                evidence_excerpt="30 40 50 60",
                asset_id="asset-photo",
                visual_action="standalone_node",
                knowledge_score=0.9,
                importance=0.8,
            ),
        ]
        plan = BranchPlan(
            id="b1",
            label="电子自旋",
            unit_ids=[unit.id for unit in raw_units],
        )

        updated, additions, warnings = audit_coverage(
            raw_units,
            [],
            [plan],
        )

        self.assertEqual(additions, [])
        self.assertTrue(all(unit.status == "deferred" for unit in updated))
        self.assertTrue(
            any("人工复核" in warning for warning in warnings),
            msg=warnings,
        )

    def test_fabricated_excerpt_cannot_self_certify_content_coverage(self):
        unit = ContentUnit(
            id="u1",
            document_id="doc",
            kind="text",
            text="梯度下降通过迭代更新参数来降低损失函数。",
            evidence_excerpt="梯度下降通过迭代更新参数来降低损失函数。",
            importance=0.8,
        )
        node = normalized_node("n1", "梯度下降").model_copy(
            update={
                "evidence": [
                    EvidenceRef(
                        unit_id="u1",
                        excerpt="牛顿法通过精确海森矩阵一步收敛。",
                    )
                ],
                "support_unit_ids": [],
                "origin": "explicit",
            }
        )

        covered, weighted, _ = coverage_statistics([unit], [node])

        self.assertEqual(covered, set())
        self.assertEqual(weighted, 0)

    def test_branch_plan_caps_root_leaf_and_structural_singletons(self):
        units = [
            ContentUnit(
                id=f"u{index}",
                document_id="doc",
                kind="text",
                text=f"主题{index}包含足够完整的课程知识。",
                heading_path=[f"章节{index}"],
                evidence_excerpt=f"主题{index}课程知识",
            )
            for index in range(24)
        ]
        topics = [
            ThemeNodeSpec(
                temp_id=f"t{index}",
                name=f"课程主题{index}",
                support_unit_ids=[f"u{index}", f"u{index + 12}"],
                confidence=0.9 - index * 0.01,
            )
            for index in range(12)
        ]
        plans = build_branch_plans(
            ThemePlanOutput(
                root_candidates=[
                    ThemeNodeSpec(
                        temp_id="root",
                        name="课程体系",
                        support_unit_ids=[unit.id for unit in units],
                    )
                ],
                branch_topics=topics,
            ),
            units,
            max_units_per_leaf=3,
        )

        self.assertLessEqual(
            len([plan for plan in plans if plan.depth == 1]),
            8,
        )
        self.assertLessEqual(len([plan for plan in plans if plan.leaf]), 24)
        self.assertFalse(
            any(
                plan.depth > 1 and plan.leaf and len(plan.unit_ids) == 1
                for plan in plans
            )
        )
        self.assertTrue(all(plan.coverage_budget <= 24 for plan in plans))

    def test_cross_branch_same_name_is_not_silently_merged(self):
        normalized = normalize_graph(
            NormalizeRequest(
                document_id="doc",
                document_title="课程体系",
                nodes=[
                    NodeCandidateIn(
                        temp_id="b1:n",
                        name="运行机制",
                        branch_id="b1",
                        evidence=[evidence("u1")],
                    ),
                    NodeCandidateIn(
                        temp_id="b2:n",
                        name="运行机制",
                        branch_id="b2",
                        evidence=[evidence("u2")],
                    ),
                ],
            )
        )

        duplicates = [
            node for node in normalized.nodes if node.name == "运行机制"
        ]
        self.assertEqual(len(duplicates), 2)
        self.assertNotEqual(duplicates[0].id, duplicates[1].id)
        self.assertTrue(any("跨分支同名" in item for item in normalized.warnings))

    def test_structural_parent_edges_receive_support_mapping_evidence(self):
        root = NodeCandidateIn(
            temp_id="root",
            name="机器学习",
            role="root_topic",
            type="root_topic",
            origin="synthesized_root",
            is_root_candidate=True,
            support_unit_ids=["u1"],
        )
        topic = NodeCandidateIn(
            temp_id="topic:b1",
            name="监督学习",
            role="branch_topic",
            type="branch_topic",
            origin="abstractive",
            branch_id="b1",
            support_unit_ids=["u1"],
        )
        child = NodeCandidateIn(
            temp_id="n1",
            name="分类",
            branch_id="b1",
            evidence=[evidence("u1", "分类预测离散标签")],
        )
        plan = BranchPlan(id="b1", label="监督学习", unit_ids=["u1"])
        candidates = build_global_parent_candidates(
            ThemePlanOutput(
                root_candidates=[],
                branch_topics=[],
            ),
            [plan],
            [root, topic, child],
            [],
        )

        self.assertTrue(candidates)
        self.assertTrue(
            all(
                candidate.evidence
                for candidate in candidates
                if candidate.classification == "direct_parent"
            )
        )

    async def test_chapter_root_and_same_name_leaf_keep_full_structural_coverage(
        self,
    ):
        planning_unit = ContentUnit(
            id="page-owner",
            document_id="doc",
            kind="text",
            text="本页包含能级结构和跃迁选择定则。",
            evidence_excerpt="本页包含能级结构和跃迁选择定则。",
        )
        source_units = [
            ContentUnit(
                id="claim-a",
                document_id="doc",
                kind="text",
                text="能级结构由量子数共同决定。",
                evidence_excerpt="能级结构由量子数共同决定。",
            ),
            ContentUnit(
                id="claim-b",
                document_id="doc",
                kind="text",
                text="跃迁选择定则限制允许发生的跃迁。",
                evidence_excerpt="跃迁选择定则限制允许发生的跃迁。",
            ),
        ]
        branch = BranchPlan(
            id="branch-spectrum",
            label="能级结构",
            description="原子光谱的能级结构",
            unit_ids=[planning_unit.id],
            coverage_budget=4,
        )
        seed_nodes = [
            NodeCandidateIn(
                temp_id="seed-a",
                name="能级结构",
                definition=source_units[0].text,
                origin="explicit",
                evidence=[
                    evidence(source_units[0].id, source_units[0].text)
                ],
            ),
            NodeCandidateIn(
                temp_id="seed-b",
                name="跃迁选择定则",
                definition=source_units[1].text,
                origin="explicit",
                evidence=[
                    evidence(source_units[1].id, source_units[1].text)
                ],
            ),
        ]
        results = await run_branch_teams(
            [branch],
            [planning_unit],
            [],
            RoleRuntime(
                provider="qwen",
                model="test",
                client=None,
                available=False,
                unavailable_reason="seeded page nodes",
            ),
            seed_nodes=seed_nodes,
            seed_unit_projection={
                source_units[0].id: planning_unit.id,
                source_units[1].id: planning_unit.id,
            },
        )

        branch_nodes = results[0].nodes
        topics = [
            node for node in branch_nodes if node.role == "branch_topic"
        ]
        self.assertEqual(len(topics), 1)
        self.assertEqual(
            set(topics[0].support_unit_ids),
            {planning_unit.id, source_units[0].id, source_units[1].id},
        )
        self.assertEqual(
            sum(node.origin == "explicit" for node in branch_nodes),
            2,
        )

        theme_plan = ThemePlanOutput(
            root_candidates=[
                ThemeNodeSpec(
                    temp_id="root",
                    name="第七章 原子光谱",
                    support_unit_ids=[planning_unit.id],
                    confidence=0.9,
                )
            ],
            branch_topics=[
                ThemeNodeSpec(
                    temp_id="theme-spectrum",
                    name=branch.label,
                    support_unit_ids=[planning_unit.id],
                    confidence=0.88,
                )
            ],
        )
        nodes = canonicalize_semantic_duplicates(
            [
                *theme_nodes(theme_plan, [branch]),
                *branch_nodes,
            ]
        )
        parent_candidates = build_global_parent_candidates(
            theme_plan,
            [branch],
            nodes,
            results[0].parent_candidates,
        )
        normalized = normalize_graph(
            NormalizeRequest(
                document_id="doc",
                document_title="第七章 原子光谱",
                nodes=nodes,
                parent_candidates=parent_candidates,
            )
        )
        solved = solve_topology(
            SolveRequest(graph=normalized),
            limits=TopologyLimits(
                max_active_nodes=16,
                max_root_fanout=4,
                max_node_fanout=8,
            ),
        )
        covered, weighted, _ = coverage_statistics(
            source_units,
            solved.nodes,
        )

        root = next(node for node in solved.nodes if node.is_root_candidate)
        self.assertEqual(root.name, "第七章 原子光谱")
        self.assertEqual(covered, {source_units[0].id, source_units[1].id})
        self.assertEqual(weighted, 1)
        self.assertEqual(solved.quality.provisional_edge_count, 0)
        self.assertTrue(solved.quality.topology_valid)

    def test_normalize_does_not_create_quadratic_leaf_to_leaf_pseudo_edges(self):
        nodes = [
            NodeCandidateIn(
                temp_id="root",
                name="课程体系",
                role="root_topic",
                type="root_topic",
                origin="synthesized_root",
                is_root_candidate=True,
                support_unit_ids=[f"u{index}" for index in range(80)],
            )
        ]
        parent_candidates: list[ParentCandidateIn] = []
        for branch_index in range(8):
            topic_id = f"topic:{branch_index}"
            nodes.append(
                NodeCandidateIn(
                    temp_id=topic_id,
                    name=f"分支主题{branch_index}",
                    role="branch_topic",
                    type="branch_topic",
                    origin="abstractive",
                    branch_id=f"b{branch_index}",
                    support_unit_ids=[
                        f"u{branch_index * 10 + offset}"
                        for offset in range(10)
                    ],
                )
            )
            parent_candidates.append(
                ParentCandidateIn(
                    parent="root",
                    child=topic_id,
                    score=0.9,
                    evidence=[evidence(f"u{branch_index * 10}")],
                )
            )
            for offset in range(10):
                child_id = f"n:{branch_index}:{offset}"
                unit_id = f"u{branch_index * 10 + offset}"
                nodes.append(
                    NodeCandidateIn(
                        temp_id=child_id,
                        name=f"知识点{branch_index}-{offset}",
                        branch_id=f"b{branch_index}",
                        optional=True,
                        evidence=[evidence(unit_id)],
                    )
                )
                parent_candidates.append(
                    ParentCandidateIn(
                        parent=topic_id,
                        child=child_id,
                        score=0.85,
                        evidence=[evidence(unit_id)],
                    )
                )

        normalized = normalize_graph(
            NormalizeRequest(
                document_id="doc",
                document_title="课程体系",
                nodes=nodes,
                parent_candidates=parent_candidates,
                max_parents_per_node=8,
            )
        )
        role_by_id = {node.id: node.role for node in normalized.nodes}

        self.assertLessEqual(
            len(normalized.parent_candidates),
            2 * (len(normalized.nodes) - 1),
        )
        self.assertFalse(
            any(
                role_by_id[candidate.parent_id] == "concept"
                and role_by_id[candidate.child_id] == "concept"
                and candidate.classification == "uncertain"
                for candidate in normalized.parent_candidates
            )
        )

    def test_solver_rejects_bad_optional_nodes_and_is_stable(self):
        root = normalized_node("root", "课程体系", root=True)
        topic = normalized_node(
            "topic",
            "核心方法",
            role="branch_topic",
            origin="abstractive",
            optional=False,
            support=["u:good"],
            with_evidence=False,
        )
        good = normalized_node("good", "梯度下降")
        bad = normalized_node("bad", "但是", confidence=0.99)
        wrong_relation = normalized_node(
            "wrong-relation",
            "验证数据",
            confidence=0.99,
        )
        missing_edge_evidence = normalized_node(
            "missing-edge-evidence",
            "测试数据",
            confidence=0.98,
        )
        graph = NormalizedGraph(
            document_id="doc",
            document_title="课程体系",
            nodes=[
                root,
                topic,
                good,
                bad,
                wrong_relation,
                missing_edge_evidence,
            ],
            parent_candidates=[
                NormalizedParentCandidate(
                    parent_id="root",
                    child_id="topic",
                    score=0.95,
                    classification="direct_parent",
                    evidence=[evidence("u:good")],
                ),
                NormalizedParentCandidate(
                    parent_id="topic",
                    child_id="good",
                    score=0.9,
                    classification="direct_parent",
                    evidence=[evidence("u:good")],
                ),
                NormalizedParentCandidate(
                    parent_id="topic",
                    child_id="bad",
                    score=0.99,
                    classification="direct_parent",
                    evidence=[evidence("u:bad")],
                ),
                NormalizedParentCandidate(
                    parent_id="topic",
                    child_id="wrong-relation",
                    score=0.99,
                    classification="sibling",
                    evidence=[evidence("u:wrong-relation")],
                ),
                NormalizedParentCandidate(
                    parent_id="topic",
                    child_id="missing-edge-evidence",
                    score=0.98,
                    classification="direct_parent",
                    evidence=[],
                ),
            ],
            cross_links=[],
        )

        first = solve_topology(SolveRequest(graph=graph))
        second = solve_topology(SolveRequest(graph=graph))

        selected_ids = {node.id for node in first.nodes}
        self.assertNotIn("bad", selected_ids)
        self.assertNotIn("wrong-relation", selected_ids)
        self.assertNotIn("missing-edge-evidence", selected_ids)
        self.assertEqual(
            [(edge.source, edge.target) for edge in first.tree_edges],
            [(edge.source, edge.target) for edge in second.tree_edges],
        )
        self.assertTrue(all(edge.evidence for edge in first.tree_edges))

    def test_solver_rejects_a_weak_optional_leaf_despite_a_common_parent_edge(self):
        root = normalized_node("root", "课程体系", root=True)
        weak = normalized_node("weak", "边缘摘录").model_copy(
            update={
                "activation_score": 0.05,
                "activation_cost": 1.0,
                "optional": True,
            }
        )
        result = solve_topology(
            SolveRequest(
                graph=NormalizedGraph(
                    document_id="doc",
                    document_title="课程体系",
                    nodes=[root, weak],
                    parent_candidates=[
                        NormalizedParentCandidate(
                            parent_id=root.id,
                            child_id=weak.id,
                            score=0.82,
                            classification="direct_parent",
                            evidence=[evidence("u:weak")],
                        )
                    ],
                    cross_links=[],
                )
            )
        )

        self.assertEqual([node.id for node in result.nodes], [root.id])
        self.assertEqual(result.tree_edges, [])

    def test_solver_enforces_node_and_fanout_budgets(self):
        root = normalized_node("root", "课程体系", root=True)
        nodes = [root]
        candidates: list[NormalizedParentCandidate] = []
        leaf_ids: list[str] = []
        for branch_index in range(8):
            branch_id = f"branch-{branch_index}"
            branch = normalized_node(
                branch_id,
                f"一级主题{branch_index}",
                role="branch_topic",
                origin="abstractive",
                optional=False,
                branch_id=f"b{branch_index}",
                support=[
                    f"u:{branch_id}",
                    f"u:{branch_id}:support",
                ],
                with_evidence=False,
            )
            nodes.append(branch)
            candidates.append(
                NormalizedParentCandidate(
                    parent_id=root.id,
                    child_id=branch.id,
                    score=0.95,
                    classification="direct_parent",
                    evidence=[evidence(f"u:{branch_id}")],
                )
            )
            for leaf_index in range(20):
                leaf_id = f"leaf-{branch_index}-{leaf_index}"
                leaf_ids.append(leaf_id)
                nodes.append(
                    normalized_node(
                        leaf_id,
                        f"知识单元{branch_index}-{leaf_index}",
                        branch_id=f"b{branch_index}",
                    )
                )
                candidates.append(
                    NormalizedParentCandidate(
                        parent_id=branch.id,
                        child_id=leaf_id,
                        score=0.9 - leaf_index * 0.001,
                        classification="direct_parent",
                        evidence=[evidence(f"u:{leaf_id}")],
                    )
                )
        for index, leaf_id in enumerate(leaf_ids[:80]):
            detail_id = f"detail-{index}"
            nodes.append(normalized_node(detail_id, f"细节知识{index}"))
            candidates.append(
                NormalizedParentCandidate(
                    parent_id=leaf_id,
                    child_id=detail_id,
                    score=0.8,
                    classification="direct_parent",
                    evidence=[evidence(f"u:{detail_id}")],
                )
            )
        result = solve_topology(
            SolveRequest(
                graph=NormalizedGraph(
                    document_id="doc",
                    document_title="课程体系",
                    nodes=nodes,
                    parent_candidates=candidates,
                    cross_links=[],
                )
            )
        )
        fanout: dict[str, int] = {}
        for edge in result.tree_edges:
            fanout[edge.source] = fanout.get(edge.source, 0) + 1

        self.assertLessEqual(len(result.nodes), 150)
        self.assertLessEqual(fanout.get(root.id, 0), 8)
        self.assertLessEqual(
            max(
                (
                    count
                    for node_id, count in fanout.items()
                    if node_id != root.id
                ),
                default=0,
            ),
            12,
        )

    def test_solver_accepts_larger_internal_limits_for_strict_page_graphs(
        self,
    ):
        root = normalized_node("root", "课程体系", root=True)
        nodes = [root]
        candidates: list[NormalizedParentCandidate] = []
        expected_ids = {root.id}
        for branch_index in range(8):
            branch = normalized_node(
                f"branch-{branch_index}",
                f"一级主题{branch_index}",
                role="branch_topic",
                origin="abstractive",
                optional=False,
                branch_id=f"b{branch_index}",
                support=[
                    f"u:branch-{branch_index}",
                    f"u:branch-{branch_index}:support",
                ],
                with_evidence=False,
            )
            nodes.append(branch)
            expected_ids.add(branch.id)
            candidates.append(
                NormalizedParentCandidate(
                    parent_id=root.id,
                    child_id=branch.id,
                    score=0.95,
                    classification="direct_parent",
                    evidence=[evidence(f"u:{branch.id}")],
                )
            )
            for leaf_index in range(20):
                leaf = normalized_node(
                    f"leaf-{branch_index}-{leaf_index}",
                    f"知识单元{branch_index}-{leaf_index}",
                    branch_id=f"b{branch_index}",
                )
                nodes.append(leaf)
                expected_ids.add(leaf.id)
                candidates.append(
                    NormalizedParentCandidate(
                        parent_id=branch.id,
                        child_id=leaf.id,
                        score=0.9,
                        classification="direct_parent",
                        evidence=[evidence(f"u:{leaf.id}")],
                    )
                )

        result = solve_topology(
            SolveRequest(
                graph=NormalizedGraph(
                    document_id="doc",
                    document_title="课程体系",
                    nodes=nodes,
                    parent_candidates=candidates,
                    cross_links=[],
                )
            ),
            limits=TopologyLimits(
                max_active_nodes=512,
                max_root_fanout=8,
                max_node_fanout=24,
            ),
        )
        fanout: dict[str, int] = {}
        for edge in result.tree_edges:
            fanout[edge.source] = fanout.get(edge.source, 0) + 1

        self.assertEqual({node.id for node in result.nodes}, expected_ids)
        self.assertEqual(len(result.nodes), 169)
        self.assertLessEqual(fanout.get(root.id, 0), 8)
        self.assertLessEqual(
            max(
                (
                    count
                    for node_id, count in fanout.items()
                    if node_id != root.id
                ),
                default=0,
            ),
            24,
        )

    def test_selected_fallback_node_is_pending_review(self):
        root = normalized_node("root", "课程体系", root=True)
        fallback = normalized_node("fallback", "梯度下降")
        fallback = fallback.model_copy(
            update={"temp_ids": ["b1:tmp_fallback"]}
        )
        result = solve_topology(
            SolveRequest(
                graph=NormalizedGraph(
                    document_id="doc",
                    document_title="课程体系",
                    nodes=[root, fallback],
                    parent_candidates=[
                        NormalizedParentCandidate(
                            parent_id=root.id,
                            child_id=fallback.id,
                            score=0.9,
                            classification="direct_parent",
                            evidence=[evidence("u:fallback")],
                        )
                    ],
                    cross_links=[],
                )
            )
        )

        self.assertIn(fallback.id, {node.id for node in result.nodes})
        self.assertTrue(
            any(
                review.type == "uncovered_content"
                and review.subject_ids == [fallback.id]
                for review in result.review_items
            )
        )

    def test_quality_gate_rejects_pending_degraded_and_non_direct_results(self):
        failures = quality_gate_failures(
            topology_valid=True,
            evidence_coverage=1,
            provisional_edge_count=0,
            weighted_coverage=0.95,
            required_coverage=0.78,
            nodes=[normalized_node("root", "课程体系", root=True)],
            edge_classifications=["ancestor_only"],
            edge_evidence=[[]],
            pending_review_count=1,
            degraded_components=["branch_extraction_model"],
            max_nodes=150,
        )

        self.assertIn("pending_review", failures)
        self.assertIn("degraded_components", failures)
        self.assertIn("non_direct_parent_edge", failures)
        self.assertIn("missing_edge_evidence", failures)

    def test_quality_gate_uses_the_same_section_label_policy_as_normalize(
        self,
    ):
        root = normalized_node("root", "课程体系", root=True)
        section = normalized_node(
            "section",
            "§28.2 电子自旋与自旋轨道耦合",
            role="branch_topic",
            origin="structural",
        )

        failures = quality_gate_failures(
            topology_valid=True,
            evidence_coverage=1,
            provisional_edge_count=0,
            weighted_coverage=0.95,
            required_coverage=0.78,
            nodes=[root, section],
            edge_classifications=["direct_parent"],
            edge_evidence=[[evidence("u:section")]],
            pending_review_count=0,
            degraded_components=[],
            max_nodes=150,
        )

        self.assertNotIn("illegal_label", failures)

    async def test_parent_verifier_batches_children_and_validates_ids(self):
        parents = [
            normalized_node(
                f"p{index}",
                f"父主题{index}",
                role="branch_topic",
                origin="abstractive",
                optional=False,
                support=["u:c0", "u:c1", "u:c2", "u:c3"],
                with_evidence=False,
            )
            for index in range(3)
        ]
        children = [
            normalized_node(f"c{index}", f"子知识点{index}")
            for index in range(4)
        ]
        candidates = [
            NormalizedParentCandidate(
                parent_id=parent.id,
                child_id=child.id,
                score=0.9 - parent_index * 0.1,
                classification="direct_parent",
                evidence=[evidence(f"u:{child.id}")],
            )
            for child in children
            for parent_index, parent in enumerate(parents)
        ]
        graph = NormalizedGraph(
            document_id="doc",
            document_title="课程体系",
            nodes=[*parents, *children],
            parent_candidates=candidates,
            cross_links=[],
        )
        client = BatchVerifierClient()
        verified, votes, warnings = await verify_parent_candidates(
            graph,
            verifier=RoleRuntime("qwen", "test", client, True),
            second_verifier=None,
            arbiter=None,
            mode="standard",
        )

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(votes), len(candidates))
        self.assertFalse(warnings)
        self.assertEqual(
            sum(
                candidate.classification == "direct_parent"
                for candidate in verified.parent_candidates
            ),
            len(children),
        )

        bad_client = BatchVerifierClient(bad_ids=True)
        _, _, bad_warnings = await verify_parent_candidates(
            graph,
            verifier=RoleRuntime("qwen", "test", bad_client, True),
            second_verifier=None,
            arbiter=None,
            mode="standard",
        )
        self.assertTrue(any("返回了未知" in item for item in bad_warnings))


if __name__ == "__main__":
    unittest.main()
