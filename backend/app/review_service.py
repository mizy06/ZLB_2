from __future__ import annotations

from collections import Counter

import networkx as nx

from .agents import stable_id
from .architecture_schemas import (
    DecisionRecord,
    MindMapNode,
    MindMapResult,
    MindMapTreeEdge,
    ReviewResolutionRequest,
)
from .blackboard import SQLiteBlackboard, utc_now
from .mindmap_engine.validate import build_quality_report


def _selected_subject_node(
    result: MindMapResult,
    review,
) -> str:
    node_ids = {node.id for node in result.nodes}
    if review.type == "competing_parent":
        targets = {edge.target for edge in result.tree_edges}
        for subject_id in review.subject_ids:
            if subject_id in targets:
                return subject_id
    return next(
        (subject_id for subject_id in review.subject_ids if subject_id in node_ids),
        "",
    )


def _recompute_depths(
    root_id: str,
    nodes: list[MindMapNode],
    edges: list[MindMapTreeEdge],
) -> list[MindMapNode]:
    graph = nx.DiGraph()
    graph.add_nodes_from(node.id for node in nodes)
    graph.add_edges_from((edge.source, edge.target) for edge in edges)
    if root_id not in graph or not nx.is_directed_acyclic_graph(graph):
        raise ValueError("人工修改会导致主树无根或出现环。")
    reachable = nx.descendants(graph, root_id) | {root_id}
    if reachable != set(graph.nodes):
        raise ValueError("人工修改会产生无法从根到达的节点。")
    parent_by_child = {edge.target: edge.source for edge in edges}
    depths = nx.single_source_shortest_path_length(graph, root_id)
    return [
        node.model_copy(
            update={
                "depth": int(depths[node.id]),
                "parent_id": parent_by_child.get(node.id),
            }
        )
        for node in nodes
    ]


def _replace_quality(
    result: MindMapResult,
    nodes: list[MindMapNode],
    edges: list[MindMapTreeEdge],
    pending_reviews: int,
):
    base = build_quality_report(nodes, edges, len(result.cross_links))
    quality_gate = (
        base.topology_valid
        and base.evidence_coverage == 1
        and base.provisional_edge_count == 0
        and result.quality_report.weighted_content_coverage
        >= (0.86 if result.mode == "precision" else 0.78)
    )
    return result.quality_report.model_copy(
        update={
            **base.model_dump(),
            "review_item_count": pending_reviews,
            "quality_gate_passed": quality_gate,
        }
    )


def _change_parent(
    result: MindMapResult,
    child_id: str,
    parent_id: str,
) -> tuple[list[MindMapNode], list[MindMapTreeEdge]]:
    node_ids = {node.id for node in result.nodes}
    if child_id == result.root_id:
        raise ValueError("根节点不能设置父节点。")
    if parent_id not in node_ids or child_id not in node_ids:
        raise ValueError("父节点或子节点不存在。")
    graph = nx.DiGraph()
    graph.add_nodes_from(node_ids)
    graph.add_edges_from(
        (edge.source, edge.target)
        for edge in result.tree_edges
        if edge.target != child_id
    )
    graph.add_edge(parent_id, child_id)
    if not nx.is_directed_acyclic_graph(graph):
        raise ValueError("改父会产生环。")
    edges = [
        edge
        for edge in result.tree_edges
        if edge.target != child_id
    ]
    edges.append(
        MindMapTreeEdge(
            id=stable_id("tree", parent_id, child_id),
            source=parent_id,
            target=child_id,
            score=1,
            provisional=False,
            classification="direct_parent",
            verifier_votes=[],
        )
    )
    nodes = _recompute_depths(result.root_id, result.nodes, edges)
    return nodes, edges


def _delete_node(
    result: MindMapResult,
    node_id: str,
) -> tuple[list[MindMapNode], list[MindMapTreeEdge]]:
    if node_id == result.root_id:
        raise ValueError("不能删除当前根节点。")
    parent_by_child = {
        edge.target: edge.source
        for edge in result.tree_edges
    }
    parent_id = parent_by_child.get(node_id)
    if not parent_id:
        raise ValueError("待删除节点没有可用父节点。")
    child_ids = [
        edge.target
        for edge in result.tree_edges
        if edge.source == node_id
    ]
    nodes = [node for node in result.nodes if node.id != node_id]
    edges = [
        edge
        for edge in result.tree_edges
        if edge.source != node_id and edge.target != node_id
    ]
    for child_id in child_ids:
        edges.append(
            MindMapTreeEdge(
                id=stable_id("tree", parent_id, child_id),
                source=parent_id,
                target=child_id,
                score=1,
                provisional=False,
                classification="direct_parent",
                verifier_votes=[],
            )
        )
    nodes = _recompute_depths(result.root_id, nodes, edges)
    return nodes, edges


def resolve_review_item(
    *,
    blackboard: SQLiteBlackboard,
    task_id: str,
    review_id: str,
    request: ReviewResolutionRequest,
) -> MindMapResult:
    result = blackboard.load_latest_result(task_id)
    if not result:
        raise KeyError(task_id)
    review = next(
        (item for item in result.review_items if item.id == review_id),
        None,
    )
    if not review:
        raise KeyError(review_id)
    if review.status == "resolved":
        raise ValueError("该复核项已经处理。")

    subject_id = _selected_subject_node(result, review)
    nodes = list(result.nodes)
    edges = list(result.tree_edges)
    decision = request.action
    reason_codes = [f"human_{request.action}"]

    if request.action == "change_parent":
        nodes, edges = _change_parent(
            result,
            subject_id,
            request.parent_id or "",
        )
    elif request.action == "delete":
        nodes, edges = _delete_node(result, subject_id)
    elif request.action == "rename":
        nodes = [
            node.model_copy(update={"name": request.label.strip()})
            if node.id == subject_id
            else node
            for node in nodes
        ]
    elif request.action == "accept_root":
        requested_root = request.parent_id or subject_id
        if requested_root != result.root_id:
            raise ValueError("当前图版本未激活该根候选，需重新求解后才能切换。")
    elif request.action != "keep":
        raise ValueError("不支持的复核动作。")

    resolution = {
        "action": request.action,
        "parent_id": request.parent_id,
        "label": request.label,
        "reason": request.reason,
        "resolved_at": utc_now(),
    }
    review_items = [
        item.model_copy(
            update={"status": "resolved", "resolution": resolution}
        )
        if item.id == review_id
        else item
        for item in result.review_items
    ]
    pending_count = sum(1 for item in review_items if item.status == "pending")
    quality = _replace_quality(result, nodes, edges, pending_count)
    record = DecisionRecord(
        id=stable_id(
            "decision",
            result.run_id,
            "human",
            review_id,
            str(result.graph_version + 1),
        ),
        run_id=result.run_id,
        subject_type=(
            "tree_edge"
            if request.action == "change_parent"
            else "node"
        ),
        subject_id=subject_id or review_id,
        actor="human",
        actor_version="review-workbench-v1",
        decision=decision,
        reason_codes=reason_codes,
        evidence_unit_ids=review.evidence_unit_ids,
        timestamp=utc_now(),
    )
    updated = result.model_copy(
        update={
            "graph_version": 0,
            "nodes": nodes,
            "tree_edges": edges,
            "review_items": review_items,
            "decision_records": [*result.decision_records, record],
            "quality_report": quality,
        }
    )
    blackboard.resolve_review(result.run_id, review_id, resolution)
    blackboard.save_decision_records(result.run_id, [record])
    blackboard.save_review_items(result.run_id, review_items)
    version = blackboard.save_graph_version(result.run_id, updated)
    return updated.model_copy(update={"graph_version": version})
