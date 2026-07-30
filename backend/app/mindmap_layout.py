from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import ceil, isfinite, sqrt
from typing import Iterable, Literal, Mapping, Sequence


LayoutSide = Literal["root", "right", "left"]


@dataclass(frozen=True, slots=True)
class NodeSize:
    width: float
    height: float

    def __post_init__(self) -> None:
        if (
            not isfinite(self.width)
            or not isfinite(self.height)
            or self.width <= 0
            or self.height <= 0
        ):
            raise ValueError("node width and height must be finite positive values")


@dataclass(frozen=True, slots=True)
class LayoutPoint:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class LayoutBox:
    left: float
    top: float
    right: float
    bottom: float


@dataclass(frozen=True, slots=True)
class LayoutResult:
    positions: dict[str, LayoutPoint]
    sizes: dict[str, NodeSize]
    boxes: dict[str, LayoutBox]
    side_by_node: dict[str, LayoutSide]
    root_children_right: tuple[str, ...]
    root_children_left: tuple[str, ...]
    subtree_extents: dict[str, float]
    canvas_width: int
    canvas_height: int
    content_bounds: LayoutBox


@dataclass(frozen=True, slots=True)
class VisibilityResult:
    visible_node_ids: tuple[str, ...]
    hidden_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class RasterPlan:
    width: int
    height: int
    scale: float


@dataclass(slots=True)
class _OrderedTree:
    node_ids: list[str]
    children: dict[str, list[str]]
    parent: dict[str, str]
    depth: dict[str, int]
    traversal: list[str]


def _deduplicate(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _build_ordered_tree(
    node_ids: Sequence[str],
    edges: Sequence[tuple[str, str]],
    root_id: str,
) -> _OrderedTree:
    ordered_ids = _deduplicate(node_ids)
    node_set = set(ordered_ids)
    if root_id not in node_set:
        raise ValueError(f"root node {root_id!r} is not present")

    raw_children = {node_id: [] for node_id in ordered_ids}
    raw_parent: dict[str, str] = {}
    for source, target in edges:
        if (
            source not in node_set
            or target not in node_set
            or source == target
            or target == root_id
            or target in raw_parent
        ):
            continue
        raw_parent[target] = source
        raw_children[source].append(target)

    children = {node_id: [] for node_id in ordered_ids}
    parent: dict[str, str] = {}
    depth = {root_id: 0}
    traversal = [root_id]
    visited = {root_id}

    def walk_from(seed: str) -> None:
        stack = [seed]
        while stack:
            node_id = stack.pop()
            discovered: list[str] = []
            for child_id in raw_children[node_id]:
                if child_id in visited:
                    continue
                visited.add(child_id)
                parent[child_id] = node_id
                depth[child_id] = depth[node_id] + 1
                children[node_id].append(child_id)
                traversal.append(child_id)
                discovered.append(child_id)
            stack.extend(reversed(discovered))

    walk_from(root_id)

    # A valid solver result is one rooted tree. Keeping this deterministic
    # fallback makes layout/export resilient to old or partially reviewed
    # graph versions without silently dropping disconnected nodes.
    while len(visited) < len(ordered_ids):
        unvisited = set(ordered_ids) - visited
        seed = next(
            (
                node_id
                for node_id in ordered_ids
                if node_id in unvisited
                and raw_parent.get(node_id) not in unvisited
            ),
            next(node_id for node_id in ordered_ids if node_id in unvisited),
        )
        visited.add(seed)
        parent[seed] = root_id
        depth[seed] = 1
        children[root_id].append(seed)
        traversal.append(seed)
        walk_from(seed)

    return _OrderedTree(
        node_ids=ordered_ids,
        children=children,
        parent=parent,
        depth=depth,
        traversal=traversal,
    )


def _stack_centers(
    node_ids: Sequence[str],
    extents: Mapping[str, float],
    vertical_gap: float,
) -> dict[str, float]:
    if not node_ids:
        return {}
    total = sum(extents[node_id] for node_id in node_ids)
    total += vertical_gap * (len(node_ids) - 1)
    cursor = -total / 2
    centers: dict[str, float] = {}
    for node_id in node_ids:
        extent = extents[node_id]
        centers[node_id] = cursor + extent / 2
        cursor += extent + vertical_gap
    return centers


def _split_root_children(
    root_children: Sequence[str],
    extents: Mapping[str, float],
    vertical_gap: float,
    right_ratio: float,
) -> tuple[list[str], list[str]]:
    if not root_children:
        return [], []
    total_height = sum(extents[node_id] for node_id in root_children)
    total_height += vertical_gap * (len(root_children) - 1)
    right_budget = total_height * right_ratio
    right: list[str] = []
    left: list[str] = []
    used_height = 0.0
    switched = False
    for node_id in root_children:
        addition = extents[node_id] + (vertical_gap if right else 0)
        if not switched and (
            not right or used_height + addition <= right_budget
        ):
            right.append(node_id)
            used_height += addition
            continue
        switched = True
        left.append(node_id)
    return right, left


def compute_mindmap_layout(
    *,
    node_ids: Sequence[str],
    edges: Sequence[tuple[str, str]],
    root_id: str,
    sizes: Mapping[str, NodeSize],
    right_ratio: float = 0.62,
    vertical_gap: float = 32,
    horizontal_gap: float = 72,
    margin: float = 72,
    title_space: float = 84,
    minimum_canvas_width: int = 1200,
    minimum_canvas_height: int = 720,
) -> LayoutResult:
    """Lay out a mind map as a deterministic, right-first, two-sided tree.

    The algorithm uses the supplied final node dimensions. It computes every
    subtree's vertical extent bottom-up, assigns an ordered prefix of root
    branches to the right, and moves the first overflowing branch plus all
    following branches to the left.
    """

    if not 0 < right_ratio <= 1:
        raise ValueError("right_ratio must be in (0, 1]")
    if vertical_gap < 24:
        raise ValueError("vertical_gap must be at least the 24 px safety gap")
    if horizontal_gap < 24:
        raise ValueError("horizontal_gap must be at least the 24 px safety gap")
    if margin < 0 or title_space < 0:
        raise ValueError("margin and title_space cannot be negative")

    tree = _build_ordered_tree(node_ids, edges, root_id)
    missing_sizes = [
        node_id for node_id in tree.node_ids if node_id not in sizes
    ]
    if missing_sizes:
        raise ValueError(f"missing node sizes for: {', '.join(missing_sizes[:5])}")
    normalized_sizes = {
        node_id: sizes[node_id]
        for node_id in tree.node_ids
    }

    subtree_extents: dict[str, float] = {}
    for node_id in reversed(tree.traversal):
        child_ids = tree.children[node_id]
        children_height = sum(
            subtree_extents[child_id] for child_id in child_ids
        )
        if child_ids:
            children_height += vertical_gap * (len(child_ids) - 1)
        subtree_extents[node_id] = max(
            normalized_sizes[node_id].height,
            children_height,
        )

    max_width_by_depth: dict[int, float] = {}
    max_depth = 0
    for node_id in tree.node_ids:
        node_depth = tree.depth[node_id]
        max_depth = max(max_depth, node_depth)
        max_width_by_depth[node_depth] = max(
            max_width_by_depth.get(node_depth, 0),
            normalized_sizes[node_id].width,
        )

    column_x = {0: 0.0}
    for node_depth in range(1, max_depth + 1):
        previous_width = max_width_by_depth.get(node_depth - 1, 1)
        current_width = max_width_by_depth.get(node_depth, 1)
        column_x[node_depth] = (
            column_x[node_depth - 1]
            + previous_width / 2
            + horizontal_gap
            + current_width / 2
        )

    root_children = tree.children[root_id]
    right_children, left_children = _split_root_children(
        root_children,
        subtree_extents,
        vertical_gap,
        right_ratio,
    )
    raw_positions = {root_id: LayoutPoint(0, 0)}
    side_by_node: dict[str, LayoutSide] = {root_id: "root"}

    def place_subtree(seed: str, seed_y: float, side: LayoutSide) -> None:
        stack: list[tuple[str, float]] = [(seed, seed_y)]
        while stack:
            node_id, center_y = stack.pop()
            direction = 1 if side == "right" else -1
            raw_positions[node_id] = LayoutPoint(
                direction * column_x[tree.depth[node_id]],
                center_y,
            )
            side_by_node[node_id] = side
            child_ids = tree.children[node_id]
            if not child_ids:
                continue
            child_centers = _stack_centers(
                child_ids,
                subtree_extents,
                vertical_gap,
            )
            descendants = [
                (child_id, center_y + child_centers[child_id])
                for child_id in child_ids
            ]
            stack.extend(reversed(descendants))

    for branch_id, center_y in _stack_centers(
        right_children,
        subtree_extents,
        vertical_gap,
    ).items():
        place_subtree(branch_id, center_y, "right")
    for branch_id, center_y in _stack_centers(
        left_children,
        subtree_extents,
        vertical_gap,
    ).items():
        place_subtree(branch_id, center_y, "left")

    raw_boxes: dict[str, LayoutBox] = {}
    for node_id, point in raw_positions.items():
        size = normalized_sizes[node_id]
        raw_boxes[node_id] = LayoutBox(
            left=point.x - size.width / 2,
            top=point.y - size.height / 2,
            right=point.x + size.width / 2,
            bottom=point.y + size.height / 2,
        )

    min_x = min(box.left for box in raw_boxes.values())
    max_x = max(box.right for box in raw_boxes.values())
    min_y = min(box.top for box in raw_boxes.values())
    max_y = max(box.bottom for box in raw_boxes.values())
    content_width = max_x - min_x
    content_height = max_y - min_y
    canvas_width = max(
        minimum_canvas_width,
        ceil(content_width + margin * 2),
    )
    canvas_height = max(
        minimum_canvas_height,
        ceil(content_height + margin * 2 + title_space),
    )
    offset_x = (canvas_width - content_width) / 2 - min_x
    drawable_height = canvas_height - title_space
    offset_y = title_space + (drawable_height - content_height) / 2 - min_y

    positions = {
        node_id: LayoutPoint(
            x=point.x + offset_x,
            y=point.y + offset_y,
        )
        for node_id, point in raw_positions.items()
    }
    boxes = {
        node_id: LayoutBox(
            left=box.left + offset_x,
            top=box.top + offset_y,
            right=box.right + offset_x,
            bottom=box.bottom + offset_y,
        )
        for node_id, box in raw_boxes.items()
    }
    content_bounds = LayoutBox(
        left=min(box.left for box in boxes.values()),
        top=min(box.top for box in boxes.values()),
        right=max(box.right for box in boxes.values()),
        bottom=max(box.bottom for box in boxes.values()),
    )
    return LayoutResult(
        positions=positions,
        sizes=normalized_sizes,
        boxes=boxes,
        side_by_node=side_by_node,
        root_children_right=tuple(right_children),
        root_children_left=tuple(left_children),
        subtree_extents=subtree_extents,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        content_bounds=content_bounds,
    )


def find_spacing_violations(
    layout: LayoutResult,
    *,
    minimum_gap: float = 24,
) -> list[tuple[str, str]]:
    """Return box pairs whose AABBs do not have the requested safe gap."""

    if minimum_gap < 0:
        raise ValueError("minimum_gap cannot be negative")
    node_ids = list(layout.positions)
    violations: list[tuple[str, str]] = []
    for left_index, left_id in enumerate(node_ids):
        left_box = layout.boxes[left_id]
        for right_id in node_ids[left_index + 1 :]:
            right_box = layout.boxes[right_id]
            horizontal_gap = max(
                right_box.left - left_box.right,
                left_box.left - right_box.right,
                0,
            )
            vertical_gap = max(
                right_box.top - left_box.bottom,
                left_box.top - right_box.bottom,
                0,
            )
            if horizontal_gap < minimum_gap and vertical_gap < minimum_gap:
                violations.append((left_id, right_id))
    return violations


def collapse_tree_to_budget(
    *,
    node_ids: Sequence[str],
    edges: Sequence[tuple[str, str]],
    root_id: str,
    max_visible: int = 120,
) -> VisibilityResult:
    """Select an ancestor-closed overview and collapse remaining subtrees."""

    if max_visible < 1:
        raise ValueError("max_visible must be at least 1")
    tree = _build_ordered_tree(node_ids, edges, root_id)
    visible = {root_id}
    pending: deque[str] = deque([root_id])
    while pending and len(visible) < max_visible:
        parent_id = pending.popleft()
        for child_id in tree.children[parent_id]:
            if len(visible) >= max_visible:
                break
            visible.add(child_id)
            pending.append(child_id)

    hidden_counts: dict[str, int] = {}
    for node_id in tree.node_ids:
        if node_id in visible:
            continue
        ancestor_id = tree.parent.get(node_id, root_id)
        while ancestor_id not in visible:
            ancestor_id = tree.parent.get(ancestor_id, root_id)
        hidden_counts[ancestor_id] = hidden_counts.get(ancestor_id, 0) + 1

    return VisibilityResult(
        visible_node_ids=tuple(
            node_id for node_id in tree.node_ids if node_id in visible
        ),
        hidden_counts=hidden_counts,
    )


def plan_raster_size(
    *,
    canvas_width: int | float,
    canvas_height: int | float,
    max_pixels: int = 16_000_000,
    max_dimension: int = 8_192,
) -> RasterPlan:
    """Plan a bounded raster without ever allocating the logical full canvas."""

    if canvas_width <= 0 or canvas_height <= 0:
        raise ValueError("canvas dimensions must be positive")
    if max_pixels < 1 or max_dimension < 1:
        raise ValueError("raster limits must be positive")

    scale = min(
        1.0,
        max_dimension / canvas_width,
        max_dimension / canvas_height,
        sqrt(max_pixels / (canvas_width * canvas_height)),
    )
    while True:
        width = max(1, ceil(canvas_width * scale))
        height = max(1, ceil(canvas_height * scale))
        if (
            width * height <= max_pixels
            and width <= max_dimension
            and height <= max_dimension
        ):
            break
        scale *= 0.999
    return RasterPlan(width=width, height=height, scale=scale)
