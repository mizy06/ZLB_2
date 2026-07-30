from __future__ import annotations

import unittest
from collections import Counter

from backend.app.agents import (
    ThemeNodeSpec,
    ThemePlanOutput,
    build_branch_plans,
    canonicalize_semantic_duplicates,
    theme_nodes,
)
from backend.app.architecture_schemas import BranchPlan, ContentUnit
from backend.app.mindmap_engine.schemas import NodeCandidateIn


def _text_unit(
    unit_id: str,
    *,
    heading: str | None = None,
    page: int | None = None,
    slide: int | None = None,
) -> ContentUnit:
    return ContentUnit(
        id=unit_id,
        document_id="branch-assignment",
        kind="text",
        text=f"{unit_id}对应的完整课程知识。",
        evidence_excerpt=f"{unit_id}对应的完整课程知识",
        heading_path=[heading] if heading else [],
        page=page,
        slide=slide,
    )


def _visual_unit(
    unit_id: str,
    *,
    heading: str | None = None,
    page: int | None = None,
    nearby_text_ids: list[str] | None = None,
) -> ContentUnit:
    return ContentUnit(
        id=unit_id,
        document_id="branch-assignment",
        kind="visual",
        summary=f"{unit_id}对应的知识图示",
        evidence_excerpt=f"{unit_id}对应的知识图示",
        heading_path=[heading] if heading else [],
        page=page,
        asset_id=f"asset-{unit_id}",
        visual_kind="diagram",
        visual_action="standalone_node",
        nearby_text_ids=nearby_text_ids or [],
        knowledge_score=0.9,
    )


def _theme(
    temp_id: str,
    name: str,
    unit_ids: list[str],
    *,
    confidence: float = 0.9,
) -> ThemeNodeSpec:
    return ThemeNodeSpec(
        temp_id=temp_id,
        name=name,
        support_unit_ids=unit_ids,
        confidence=confidence,
    )


def _root_label_by_leaf_unit(
    plans: list[BranchPlan],
) -> dict[str, str]:
    roots = {
        plan.id: plan
        for plan in plans
        if plan.depth == 1
    }
    result: dict[str, str] = {}
    for leaf in (plan for plan in plans if plan.leaf):
        root_id = leaf.parent_branch_id or leaf.id
        root = roots[root_id]
        for unit_id in leaf.unit_ids:
            result[unit_id] = root.label
    return result


class BranchAssignmentTDDTests(unittest.TestCase):
    def assert_lossless_leaf_contract(
        self,
        plans: list[BranchPlan],
        units: list[ContentUnit],
    ) -> None:
        leaves = [plan for plan in plans if plan.leaf]
        occurrences = Counter(
            unit_id
            for leaf in leaves
            for unit_id in leaf.unit_ids
        )
        planning_ids = {unit.id for unit in units}

        self.assertLessEqual(len(leaves), 24)
        self.assertTrue(
            all(len(leaf.unit_ids) <= 8 for leaf in leaves)
        )
        self.assertEqual(set(occurrences), planning_ids)
        self.assertTrue(
            all(occurrences[unit_id] == 1 for unit_id in planning_ids)
        )

    def test_unclaimed_text_and_visual_units_follow_semantic_precedence(
        self,
    ) -> None:
        chapter_a = "第一章 量子基础"
        chapter_b = "第二章 激光原理"
        units = [
            _text_unit("a-core", heading=chapter_a, page=4),
            _text_unit("b-core", heading=chapter_b, page=80),
            # Rule 2 must beat page proximity: page 78 is near B, but its
            # heading is an exact match for A.
            _text_unit("a-by-heading", heading=chapter_a, page=78),
            # Rule 3: no semantic link, so page 77 belongs to nearby B.
            _text_unit("b-by-page", page=77),
            # Rule 1 must beat page proximity: this visual is on page 79 but
            # explicitly points at A's claimed text.
            _visual_unit(
                "a-visual-by-nearby",
                page=79,
                nearby_text_ids=["a-core"],
            ),
            # nearby_text_ids may point at an initially unclaimed text unit;
            # after that text is assigned by heading, the visual follows it.
            _visual_unit(
                "a-visual-via-unclaimed-text",
                page=81,
                nearby_text_ids=["a-by-heading"],
            ),
            # A visual without nearby text still follows an exact heading
            # match before source distance.
            _visual_unit(
                "b-visual-by-heading",
                heading=chapter_b,
                page=5,
            ),
        ]
        plan = ThemePlanOutput(
            root_candidates=[],
            branch_topics=[
                _theme("topic-a", chapter_a, ["a-core"]),
                _theme("topic-b", chapter_b, ["b-core"]),
            ],
        )

        plans = build_branch_plans(plan, units)
        assignment = _root_label_by_leaf_unit(plans)

        self.assertEqual(
            [item.label for item in plans if item.depth == 1],
            [chapter_a, chapter_b],
            msg="unclaimed units must not rename or corrupt retained topics",
        )
        self.assertEqual(assignment["a-by-heading"], chapter_a)
        self.assertEqual(assignment["b-by-page"], chapter_b)
        self.assertEqual(assignment["a-visual-by-nearby"], chapter_a)
        self.assertEqual(
            assignment["a-visual-via-unclaimed-text"],
            chapter_a,
        )
        self.assertEqual(assignment["b-visual-by-heading"], chapter_b)
        self.assert_lossless_leaf_contract(plans, units)

    def test_ninth_topic_overflow_is_not_dumped_into_last_retained_topic(
        self,
    ) -> None:
        retained_units = [
            _text_unit(
                f"retained-{index}",
                heading=f"第{index + 1}章",
                page=(index + 1) * 10,
            )
            for index in range(8)
        ]
        overflow = _text_unit(
            "overflow-near-first",
            heading="第1章",
            page=11,
        )
        units = [*retained_units, overflow]
        topics = [
            _theme(
                f"topic-{index}",
                f"第{index + 1}章",
                [retained_units[index].id],
                confidence=0.99 - index * 0.01,
            )
            for index in range(8)
        ]
        topics.append(
            _theme(
                "topic-overflow",
                "第九补充章",
                [overflow.id],
                confidence=0.5,
            )
        )

        plans = build_branch_plans(
            ThemePlanOutput(
                root_candidates=[],
                branch_topics=topics,
            ),
            units,
        )
        root_labels = [
            item.label for item in plans if item.depth == 1
        ]
        assignment = _root_label_by_leaf_unit(plans)

        self.assertEqual(
            root_labels,
            [f"第{index + 1}章" for index in range(8)],
        )
        self.assertEqual(assignment[overflow.id], "第1章")
        self.assertNotEqual(assignment[overflow.id], root_labels[-1])
        self.assert_lossless_leaf_contract(plans, units)

    def test_slide_distance_fallback_is_nearest_and_repeatable(self) -> None:
        units = [
            _text_unit("early", heading="开篇主题", slide=2),
            _text_unit("late", heading="收束主题", slide=40),
            _text_unit("unclaimed", slide=38),
        ]
        theme_plan = ThemePlanOutput(
            root_candidates=[],
            branch_topics=[
                _theme("early-topic", "开篇主题", ["early"]),
                _theme("late-topic", "收束主题", ["late"]),
            ],
        )

        first = build_branch_plans(theme_plan, units)
        second = build_branch_plans(theme_plan, units)

        self.assertEqual(
            _root_label_by_leaf_unit(first),
            _root_label_by_leaf_unit(second),
        )
        self.assertEqual(
            _root_label_by_leaf_unit(first)["unclaimed"],
            "收束主题",
        )
        self.assert_lossless_leaf_contract(first, units)

    def test_root_topics_and_leaf_units_follow_source_order_not_model_confidence(
        self,
    ) -> None:
        early_heading = "§1 早期基础"
        late_heading = "§2 后续应用"
        units = [
            _text_unit("early-1", heading=early_heading, page=2),
            _text_unit("early-2", heading=early_heading, page=3),
            _text_unit("late-1", heading=late_heading, page=40),
            _text_unit("late-2", heading=late_heading, page=41),
        ]
        theme_plan = ThemePlanOutput(
            root_candidates=[],
            branch_topics=[
                _theme(
                    "late",
                    late_heading,
                    ["late-2", "late-1"],
                    confidence=0.99,
                ),
                _theme(
                    "early",
                    early_heading,
                    ["early-2", "early-1"],
                    confidence=0.61,
                ),
            ],
        )

        plans = build_branch_plans(theme_plan, units)
        roots = [plan for plan in plans if plan.depth == 1]

        self.assertEqual(
            [plan.label for plan in roots],
            [early_heading, late_heading],
        )
        self.assertEqual(roots[0].unit_ids, ["early-1", "early-2"])
        self.assertEqual(roots[1].unit_ids, ["late-1", "late-2"])

    def test_split_leaves_are_contiguous_and_have_distinct_source_labels(
        self,
    ) -> None:
        heading = "§28.5 激光"
        titles = [
            "自发辐射",
            "吸收过程",
            "受激辐射",
            "爱因斯坦系数",
            "粒子数反转",
            "泵浦机制",
            "光振荡",
            "He-Ne激光器",
            "光学谐振腔",
            "纵模选择",
            "激光器三组成",
            "激光的特点",
        ]
        units = [
            ContentUnit(
                id=f"unit-{index:02d}",
                document_id="branch-assignment",
                kind="text",
                text=f"{title}\n第{index + 1}项课程正文。",
                evidence_excerpt=title,
                heading_path=[heading],
                page=64 + index,
            )
            for index, title in enumerate(titles)
        ]
        scrambled_ids = [
            units[index].id
            for index in (8, 0, 10, 2, 6, 4, 11, 1, 9, 3, 7, 5)
        ]

        plans = build_branch_plans(
            ThemePlanOutput(
                root_candidates=[],
                branch_topics=[
                    _theme("laser", heading, scrambled_ids),
                ],
            ),
            units,
            max_units_per_leaf=4,
        )
        leaves = [plan for plan in plans if plan.leaf]

        self.assertEqual(
            [
                [
                    next(unit.page for unit in units if unit.id == unit_id)
                    for unit_id in leaf.unit_ids
                ]
                for leaf in leaves
            ],
            [
                [64, 65, 66, 67],
                [68, 69, 70, 71],
                [72, 73, 74, 75],
            ],
        )
        normalized_labels = [leaf.label.casefold() for leaf in leaves]
        self.assertEqual(len(set(normalized_labels)), len(leaves))
        self.assertNotIn(heading.casefold(), normalized_labels)
        self.assertTrue(
            all("子主题" not in leaf.label for leaf in leaves),
            msg=f"observed synthetic leaf labels: {[leaf.label for leaf in leaves]}",
        )

    def test_leaf_partition_never_splits_a_page_cluster_when_it_fits(
        self,
    ) -> None:
        heading = "§28.5 激光"
        units = [
            ContentUnit(
                id="p1-text",
                document_id="branch-assignment",
                kind="text",
                text="自发辐射",
                evidence_excerpt="自发辐射",
                heading_path=[heading],
                page=1,
            ),
            _visual_unit("p1-visual-a", heading=heading, page=1),
            _visual_unit("p1-visual-b", heading=heading, page=1),
            _text_unit("p2-text", heading=heading, page=2),
            _text_unit("p3-text", heading=heading, page=3),
            ContentUnit(
                id="p4-text",
                document_id="branch-assignment",
                kind="text",
                text="光学谐振腔",
                evidence_excerpt="光学谐振腔",
                heading_path=[heading],
                page=4,
            ),
            _visual_unit("p4-visual-a", heading=heading, page=4),
            _visual_unit("p4-visual-b", heading=heading, page=4),
            _text_unit("p5-text", heading=heading, page=5),
            _text_unit("p6-text", heading=heading, page=6),
        ]
        plans = build_branch_plans(
            ThemePlanOutput(
                root_candidates=[],
                branch_topics=[
                    _theme(
                        "laser",
                        heading,
                        [unit.id for unit in reversed(units)],
                    ),
                ],
            ),
            units,
            max_units_per_leaf=4,
        )
        leaves = [plan for plan in plans if plan.leaf]
        leaf_by_unit = {
            unit_id: leaf.id
            for leaf in leaves
            for unit_id in leaf.unit_ids
        }

        self.assertEqual(
            {
                leaf_by_unit["p1-text"],
                leaf_by_unit["p1-visual-a"],
                leaf_by_unit["p1-visual-b"],
            },
            {leaf_by_unit["p1-text"]},
        )
        self.assertEqual(
            {
                leaf_by_unit["p4-text"],
                leaf_by_unit["p4-visual-a"],
                leaf_by_unit["p4-visual-b"],
            },
            {leaf_by_unit["p4-text"]},
        )
        self.assert_lossless_leaf_contract(plans, units)

    def test_leaf_labels_skip_formula_fragments_and_decorative_visuals(
        self,
    ) -> None:
        heading = "§28 课程主题"
        units = [
            ContentUnit(
                id="bohr",
                document_id="branch-assignment",
                kind="text",
                text=(
                    "右端应为能量差\n"
                    "玻尔氢原子理论（1913）\n"
                    "定态条件"
                ),
                evidence_excerpt="玻尔氢原子理论（1913）",
                heading_path=[heading],
                page=1,
            ),
            _text_unit("bohr-detail", heading=heading, page=2),
            ContentUnit(
                id="photo",
                document_id="branch-assignment",
                kind="visual",
                summary="历史黑白照片：玻尔在黑板前讲解。",
                evidence_excerpt="历史黑白照片",
                heading_path=[heading],
                page=3,
                asset_id="asset-photo",
                visual_kind="photo",
                visual_action="attach_as_media",
            ),
            ContentUnit(
                id="franck-hertz",
                document_id="branch-assignment",
                kind="text",
                text="夫兰克—赫兹实验（点击） 用于验证原子能级量子化。",
                evidence_excerpt="夫兰克—赫兹实验",
                heading_path=[heading],
                page=4,
            ),
            ContentUnit(
                id="gain-chart",
                document_id="branch-assignment",
                kind="visual",
                summary="激光增益曲线与纵模分布示意图",
                evidence_excerpt="激光增益曲线与纵模分布示意图",
                heading_path=[heading],
                page=5,
                asset_id="asset-gain",
                visual_kind="chart",
                visual_action="standalone_node",
                knowledge_score=0.9,
            ),
            ContentUnit(
                id="formula-fragment",
                document_id="branch-assignment",
                kind="text",
                text="A ⇒ 输出\n只有产生相长干涉才有输出。",
                evidence_excerpt="只有产生相长干涉才有输出",
                heading_path=[heading],
                page=6,
            ),
            ContentUnit(
                id="laser-features",
                document_id="branch-assignment",
                kind="text",
                text="五. 激光的特点\n相干性极好\n方向性极好",
                evidence_excerpt="激光的特点",
                heading_path=[heading],
                page=7,
            ),
            _text_unit("laser-detail", heading=heading, page=8),
        ]
        plans = build_branch_plans(
            ThemePlanOutput(
                root_candidates=[],
                branch_topics=[
                    _theme(
                        "course-topic",
                        heading,
                        [unit.id for unit in units],
                    ),
                ],
            ),
            units,
            max_units_per_leaf=4,
        )
        labels = [plan.label for plan in plans if plan.leaf]

        self.assertEqual(len(labels), 2)
        self.assertIn("玻尔", labels[0])
        self.assertIn("激光的特点", labels[1])
        for forbidden in (
            "右端应为能量差",
            "历史黑白照片",
            "A ⇒ 输出",
            "激光增益曲线与纵模分布示意图",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, labels)

    def test_duplicate_branch_topic_candidates_merge_before_persistence(self):
        plan = BranchPlan(
            id="branch-one",
            label="量子基础",
            description="量子基础课程主题",
            unit_ids=["unit-a", "unit-b"],
            coverage_budget=4,
        )
        base = theme_nodes(
            ThemePlanOutput(
                root_candidates=[],
                branch_topics=[
                    _theme(
                        "theme-one",
                        plan.label,
                        plan.unit_ids,
                    )
                ],
            ),
            [plan],
        )
        duplicate = NodeCandidateIn(
            temp_id=f"topic:{plan.id}",
            name=plan.label,
            type="branch_topic",
            role="branch_topic",
            definition=plan.description,
            origin="abstractive",
            branch_id=plan.id,
            confidence=0.88,
            optional=False,
            activation_score=0.88,
            support_unit_ids=["unit-b", "unit-c"],
        )

        merged = canonicalize_semantic_duplicates([*base, duplicate])
        topic_ids = [
            item.temp_id
            for item in merged
            if item.role == "branch_topic"
        ]

        self.assertEqual(topic_ids, [f"topic:{plan.id}"])
        topic = next(
            item for item in merged if item.temp_id == f"topic:{plan.id}"
        )
        self.assertEqual(
            topic.support_unit_ids,
            ["unit-a", "unit-b", "unit-c"],
        )


if __name__ == "__main__":
    unittest.main()
