from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from backend.vnext.contracts.graph import CanonicalExplicitGraph
from backend.vnext.contracts.presentation import (
    MediaNodeIdentity,
    MediaParentIdentity,
    MediaViewEdgeIdentity,
)


MAX_PNG_NODES_PER_TILE = 32
MAX_PDF_NODES_PER_PAGE = 48
SOURCE_LINKS_PER_PAGE = 24


@dataclass(frozen=True, slots=True)
class PdfPagePlan:
    kind: str
    title: str
    node_ids: tuple[str, ...] = ()
    evidence_ref_ids: tuple[str, ...] = ()
    bookmark_parent_title: str | None = None


def presentation_tree(
    nodes: tuple[MediaNodeIdentity, ...],
    parents: tuple[MediaParentIdentity, ...],
    view_edges: tuple[MediaViewEdgeIdentity, ...],
) -> tuple[str, dict[str, str], dict[str, tuple[str, ...]]]:
    order = {item.node_id: item.source_order for item in nodes}
    parent_by_child = {
        item.child_id: item.parent_id for item in parents
    }
    for edge in view_edges:
        parent_by_child.setdefault(edge.target_id, edge.source_id)
    roots = [
        item.node_id
        for item in nodes
        if item.node_id not in parent_by_child
    ]
    if len(roots) != 1:
        raise ValueError(
            "publishable presentation requires exactly one display root"
        )
    children: dict[str, list[str]] = {
        item.node_id: [] for item in nodes
    }
    for child_id, parent_id in parent_by_child.items():
        if parent_id not in children or child_id not in children:
            raise ValueError(
                "presentation parent map references an unknown node"
            )
        children[parent_id].append(child_id)
    ordered_children = {
        node_id: tuple(
            sorted(child_ids, key=lambda value: order[value])
        )
        for node_id, child_ids in children.items()
    }
    visited: set[str] = set()
    stack = [roots[0]]
    while stack:
        node_id = stack.pop()
        if node_id in visited:
            raise ValueError("presentation hierarchy contains a cycle")
        visited.add(node_id)
        stack.extend(reversed(ordered_children[node_id]))
    if visited != set(order):
        raise ValueError(
            "presentation hierarchy must reach every visible node"
        )
    return roots[0], parent_by_child, ordered_children


def plan_png_tiles(
    nodes: tuple[MediaNodeIdentity, ...],
    parents: tuple[MediaParentIdentity, ...],
    view_edges: tuple[MediaViewEdgeIdentity, ...],
) -> tuple[tuple[str, ...], ...]:
    root_id, _, children = presentation_tree(
        nodes,
        parents,
        view_edges,
    )
    ordered = _preorder(root_id, children)
    non_root = [node_id for node_id in ordered if node_id != root_id]
    tile_count = max(
        1,
        math.ceil(len(nodes) / MAX_PNG_NODES_PER_TILE),
    )
    if not non_root:
        return ((root_id,),)
    group_size = math.ceil(len(non_root) / tile_count)
    return tuple(
        (root_id, *non_root[offset : offset + group_size])
        for offset in range(0, len(non_root), group_size)
    )


def plan_pdf_pages(
    nodes: tuple[MediaNodeIdentity, ...],
    parents: tuple[MediaParentIdentity, ...],
    view_edges: tuple[MediaViewEdgeIdentity, ...],
    graph: CanonicalExplicitGraph,
) -> tuple[PdfPagePlan, ...]:
    root_id, _, children = presentation_tree(
        nodes,
        parents,
        view_edges,
    )
    label_by_id = {item.node_id: item.label for item in nodes}
    pages: list[PdfPagePlan] = []
    direct_children = children[root_id]
    overview_chunks = _chunks(
        direct_children,
        MAX_PDF_NODES_PER_PAGE - 1,
    ) or ((),)
    for index, chunk in enumerate(overview_chunks, start=1):
        title = "Overview" if index == 1 else f"Overview {index}"
        pages.append(
            PdfPagePlan(
                kind="overview",
                title=title,
                node_ids=(root_id, *chunk),
            )
        )

    for chapter_id in direct_children:
        descendants = tuple(
            node_id
            for node_id in _preorder(chapter_id, children)
            if node_id != chapter_id
        )
        chunks = _chunks(
            descendants,
            MAX_PDF_NODES_PER_PAGE - 1,
        ) or ((),)
        chapter_title = label_by_id[chapter_id]
        for index, chunk in enumerate(chunks, start=1):
            title = (
                chapter_title
                if index == 1
                else f"{chapter_title} ({index})"
            )
            pages.append(
                PdfPagePlan(
                    kind="chapter",
                    title=title,
                    node_ids=(chapter_id, *chunk),
                    bookmark_parent_title=chapter_title,
                )
            )

    evidence_ids = _source_evidence_ids(nodes, graph)
    evidence_chunks = _chunks(evidence_ids, SOURCE_LINKS_PER_PAGE) or ((),)
    for index, chunk in enumerate(evidence_chunks, start=1):
        pages.append(
            PdfPagePlan(
                kind="sources",
                title=(
                    "Sources and review"
                    if index == 1
                    else f"Sources and review ({index})"
                ),
                evidence_ref_ids=chunk,
            )
        )
    return tuple(pages)


def _source_evidence_ids(
    nodes: tuple[MediaNodeIdentity, ...],
    graph: CanonicalExplicitGraph,
) -> tuple[str, ...]:
    concept_by_id = {
        concept.concept_id: concept for concept in graph.concepts
    }
    observed: list[str] = []
    seen: set[str] = set()
    for node in nodes:
        concept = concept_by_id.get(node.node_id)
        if concept is None:
            continue
        for evidence in concept.source_evidence_refs:
            if evidence.ref_id in seen:
                continue
            seen.add(evidence.ref_id)
            observed.append(evidence.ref_id)
    return tuple(observed)


def _preorder(
    root_id: str,
    children: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    ordered: list[str] = []
    stack = [root_id]
    while stack:
        node_id = stack.pop()
        ordered.append(node_id)
        stack.extend(reversed(children[node_id]))
    return tuple(ordered)


def _chunks(
    values: Iterable[str],
    size: int,
) -> tuple[tuple[str, ...], ...]:
    if size < 1:
        raise ValueError("page chunk size must be positive")
    materialized = tuple(values)
    return tuple(
        materialized[offset : offset + size]
        for offset in range(0, len(materialized), size)
    )
