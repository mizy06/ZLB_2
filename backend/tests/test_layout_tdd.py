from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from backend.app.export_service import (
    build_mindmap_layout,
    render_mindmap_png,
)
from backend.app.mindmap_layout import (
    NodeSize,
    collapse_tree_to_budget,
    compute_mindmap_layout,
    find_spacing_violations,
    plan_raster_size,
)


def make_balanced_tree(
    node_count: int,
    *,
    fanout: int = 4,
) -> tuple[list[str], list[tuple[str, str]]]:
    node_ids = [f"node_{index:04d}" for index in range(node_count)]
    edges = [
        (node_ids[(index - 1) // fanout], node_ids[index])
        for index in range(1, node_count)
    ]
    return node_ids, edges


def varied_sizes(node_ids: list[str]) -> dict[str, NodeSize]:
    sizes: dict[str, NodeSize] = {}
    for index, node_id in enumerate(node_ids):
        if index == 0:
            sizes[node_id] = NodeSize(width=230, height=86)
        elif index % 37 == 0:
            # Represents a long bilingual/formula label after actual wrapping.
            sizes[node_id] = NodeSize(width=420, height=218)
        else:
            sizes[node_id] = NodeSize(
                width=168 + (index % 3) * 18,
                height=58 + (index % 4) * 13,
            )
    return sizes


def make_export_result(node_count: int) -> SimpleNamespace:
    nodes = [
        SimpleNamespace(
            id=f"node_{index:04d}",
            name=(
                "课程总览"
                if index == 0
                else f"第 {index} 个知识节点及其完整说明"
            ),
            role="root_topic" if index == 0 else "concept",
            confidence=0.86,
        )
        for index in range(node_count)
    ]
    edges = [
        SimpleNamespace(
            source=nodes[0].id,
            target=node.id,
            provisional=False,
        )
        for node in nodes[1:]
    ]
    return SimpleNamespace(
        nodes=nodes,
        tree_edges=edges,
        root_id=nodes[0].id,
        document=SimpleNamespace(title="大型课程思维导图"),
    )


class MindMapLayoutTDDTests(unittest.TestCase):
    def test_layout_has_no_aabb_spacing_violations_at_all_target_scales(self):
        for node_count in (10, 120, 336, 1000):
            with self.subTest(node_count=node_count):
                node_ids, edges = make_balanced_tree(node_count)
                layout = compute_mindmap_layout(
                    node_ids=node_ids,
                    edges=edges,
                    root_id=node_ids[0],
                    sizes=varied_sizes(node_ids),
                )

                self.assertEqual(set(layout.positions), set(node_ids))
                self.assertEqual(
                    find_spacing_violations(layout, minimum_gap=24),
                    [],
                )
                self.assertGreaterEqual(layout.canvas_width, 1)
                self.assertGreaterEqual(layout.canvas_height, 1)

    def test_right_first_switches_once_at_the_height_budget(self):
        root = "root"
        children = [
            "zeta",
            "alpha",
            "theta",
            "beta",
            "eta",
            "gamma",
            "delta",
            "epsilon",
            "iota",
            "kappa",
        ]
        node_ids = [root, *children]
        edges = [(root, child_id) for child_id in children]
        sizes = {
            node_id: NodeSize(width=180, height=64)
            for node_id in node_ids
        }

        layout = compute_mindmap_layout(
            node_ids=node_ids,
            edges=edges,
            root_id=root,
            sizes=sizes,
            right_ratio=0.62,
        )

        # Equal-height branches should put approximately 62% on the right.
        self.assertEqual(layout.root_children_right, tuple(children[:6]))
        self.assertEqual(layout.root_children_left, tuple(children[6:]))
        # The source/tree-edge order is preserved; labels are not sorted.
        self.assertEqual(
            (*layout.root_children_right, *layout.root_children_left),
            tuple(children),
        )
        side_sequence = [layout.side_by_node[node_id] for node_id in children]
        self.assertNotIn("right", side_sequence[side_sequence.index("left") :])

    def test_subtree_extent_uses_real_node_height_bottom_up(self):
        node_ids = ["root", "branch", "short_a", "short_b", "long_label"]
        edges = [
            ("root", "branch"),
            ("branch", "short_a"),
            ("branch", "short_b"),
            ("short_b", "long_label"),
        ]
        sizes = {
            "root": NodeSize(width=230, height=80),
            "branch": NodeSize(width=190, height=260),
            "short_a": NodeSize(width=168, height=58),
            "short_b": NodeSize(width=168, height=58),
            "long_label": NodeSize(width=460, height=240),
        }

        layout = compute_mindmap_layout(
            node_ids=node_ids,
            edges=edges,
            root_id="root",
            sizes=sizes,
        )

        self.assertGreaterEqual(layout.subtree_extents["branch"], 260)
        self.assertGreaterEqual(layout.subtree_extents["short_b"], 240)
        self.assertEqual(
            find_spacing_violations(layout, minimum_gap=24),
            [],
        )

    def test_publishable_long_root_label_is_wrapped_without_ellipsis(self):
        result = make_export_result(2)
        root_label = (
            "面向复杂工程系统的多源证据融合与可靠决策课程知识体系"
            "及其完整实践方法、验证框架、运行治理、人工复核和持续演进机制"
            "以及跨场景迁移评估体系"
        )
        result.nodes[0].name = root_label

        class FixedWidthFont:
            @staticmethod
            def getlength(value: str) -> int:
                return len(value) * 16

        with patch(
            "backend.app.export_service._font",
            return_value=FixedWidthFont(),
        ):
            layout, labels = build_mindmap_layout(result)

        rendered = labels[result.root_id]
        self.assertEqual(rendered.replace("\n", ""), root_label)
        self.assertNotIn("…", rendered)
        self.assertGreater(layout.sizes[result.root_id].height, 72)
        self.assertEqual(
            find_spacing_violations(layout, minimum_gap=24),
            [],
        )

    def test_budgeted_visibility_never_exceeds_120_and_hides_whole_subtrees(self):
        for node_count in (120, 336, 1000):
            with self.subTest(node_count=node_count):
                node_ids, edges = make_balanced_tree(node_count)
                visibility = collapse_tree_to_budget(
                    node_ids=node_ids,
                    edges=edges,
                    root_id=node_ids[0],
                    max_visible=120,
                )
                visible = set(visibility.visible_node_ids)
                children: dict[str, list[str]] = {}
                for source, target in edges:
                    children.setdefault(source, []).append(target)

                self.assertLessEqual(len(visible), 120)
                self.assertIn(node_ids[0], visible)
                self.assertEqual(
                    sum(visibility.hidden_counts.values()),
                    node_count - len(visible),
                )

                # Once a node is hidden, its complete descendant subtree is hidden.
                for hidden_id in set(node_ids) - visible:
                    pending = list(children.get(hidden_id, []))
                    while pending:
                        descendant = pending.pop()
                        self.assertNotIn(descendant, visible)
                        pending.extend(children.get(descendant, []))

    def test_raster_plan_never_allocates_the_full_huge_canvas(self):
        plan = plan_raster_size(
            canvas_width=11_087,
            canvas_height=9_709,
            max_pixels=16_000_000,
            max_dimension=8_192,
        )

        self.assertLess(plan.scale, 1)
        self.assertLessEqual(plan.width * plan.height, 16_000_000)
        self.assertLessEqual(max(plan.width, plan.height), 8_192)
        self.assertGreater(plan.width, 0)
        self.assertGreater(plan.height, 0)

    def test_png_uses_shared_layout_and_respects_allocation_limits(self):
        result = make_export_result(336)
        layout, _ = build_mindmap_layout(result)
        self.assertEqual(
            find_spacing_violations(layout, minimum_gap=24),
            [],
        )

        with (
            patch("backend.app.export_service.MAX_PNG_PIXELS", 750_000),
            patch("backend.app.export_service.MAX_PNG_DIMENSION", 1_200),
        ):
            png = render_mindmap_png(result)

        with Image.open(BytesIO(png)) as image:
            self.assertLessEqual(image.width * image.height, 750_000)
            self.assertLessEqual(max(image.size), 1_200)


if __name__ == "__main__":
    unittest.main()
