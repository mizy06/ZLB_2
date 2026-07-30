from __future__ import annotations

from collections import Counter

import networkx as nx

from .agents import coverage_statistics, stable_id
from .architecture_schemas import (
    CoverageSummary,
    DecisionRecord,
    MindMapCrossLink,
    MindMapNode,
    MindMapResult,
    MindMapTreeEdge,
    ReviewItemView,
    ReviewResolutionRequest,
)
from .blackboard import SQLiteBlackboard, utc_now
from .mindmap_engine.normalize import (
    is_publishable_node_label,
    normalized_key,
)
from .mindmap_engine.schemas import EvidenceRef
from .mindmap_engine.validate import build_quality_report


_ALLOWED_REVIEW_ACTIONS = {
    "root_choice": {"keep", "accept_root"},
    "competing_parent": {"keep", "change_parent", "rename"},
    "abstract_parent": {"keep", "delete", "rename"},
    "uncovered_content": {"keep", "rename"},
    "cross_link": {"keep"},
}


def _validate_review_action(review, action: str) -> None:
    allowed = _ALLOWED_REVIEW_ACTIONS.get(review.type, set())
    if action not in allowed:
        raise ValueError(
            f"{review.type} 复核类型不支持 {action} 动作。"
        )


def _selected_subject_node(
    result: MindMapResult,
    review,
) -> str:
    node_ids = {node.id for node in result.nodes}
    explicit = getattr(review, "subject_id", "")
    if explicit:
        if explicit not in node_ids:
            raise ValueError("复核项指向的节点已不存在。")
        return explicit
    if review.type == "competing_parent":
        parent_ids = {
            str(item.get("parent_id") or "")
            for item in review.alternatives
            if item.get("parent_id")
        }
        non_parent_subjects = [
            subject_id
            for subject_id in review.subject_ids
            if subject_id in node_ids and subject_id not in parent_ids
        ]
        if len(non_parent_subjects) == 1:
            return non_parent_subjects[0]
        selected_targets = [
            edge.target
            for edge in result.tree_edges
            if edge.source in review.subject_ids
            and edge.target in review.subject_ids
        ]
        if len(set(selected_targets)) == 1:
            return selected_targets[0]
    selected = next(
        (subject_id for subject_id in review.subject_ids if subject_id in node_ids),
        "",
    )
    if not selected:
        raise ValueError("复核项没有明确的节点 subject。")
    return selected


def _refresh_node_review_state(
    *,
    root_id: str,
    nodes: list[MindMapNode],
    edges: list[MindMapTreeEdge],
    reviews: list[ReviewItemView],
) -> list[MindMapNode]:
    node_ids = {node.id for node in nodes}
    risk_by_node: dict[str, float] = {}
    for review in reviews:
        if review.status != "pending":
            continue
        subject_id = ""
        if review.type == "root_choice" and root_id in node_ids:
            subject_id = root_id
        elif review.subject_id in node_ids:
            subject_id = review.subject_id
        elif review.type == "competing_parent":
            selected_targets = {
                edge.target
                for edge in edges
                if edge.source in review.subject_ids
                and edge.target in review.subject_ids
                and edge.target in node_ids
            }
            if len(selected_targets) == 1:
                subject_id = next(iter(selected_targets))
        if not subject_id:
            subject_id = next(
                (
                    member_id
                    for member_id in review.subject_ids
                    if member_id in node_ids
                ),
                "",
            )
        if subject_id:
            risk_by_node[subject_id] = max(
                risk_by_node.get(subject_id, 0),
                review.risk_score,
            )

    return [
        node.model_copy(
            update={
                "status": (
                    "needs_review"
                    if risk_by_node.get(node.id, 0)
                    else "accepted"
                ),
                "risk_score": round(risk_by_node.get(node.id, 0), 4),
            }
        )
        for node in nodes
    ]


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
    cross_links: list[MindMapCrossLink],
    pending_reviews: int,
):
    base = build_quality_report(nodes, edges, len(cross_links))
    covered, weighted_coverage, branch_coverage = coverage_statistics(
        result.content_units,
        nodes,
    )
    eligible_units = [
        unit
        for unit in result.content_units
        if unit.status != "rejected" and unit.importance > 0.15
    ]
    abstract_nodes = [
        node
        for node in nodes
        if node.origin in {"abstractive", "structural"}
    ]
    supported_abstract = [
        node
        for node in abstract_nodes
        if len(
            {
                *node.support_unit_ids,
                *[
                    item.unit_id or item.chunk_id
                    for item in node.evidence
                    if item.unit_id or item.chunk_id
                ],
            }
        )
        >= 2
    ]
    abstraction_support_rate = (
        len(supported_abstract) / len(abstract_nodes)
        if abstract_nodes
        else 1
    )
    direct_parent_confidence = (
        sum(edge.score for edge in edges) / len(edges)
        if edges
        else 1
    )
    structural_gate = base.topology_valid
    publish_gate = (
        base.topology_valid
        and base.conflict_count == 0
        and base.evidence_coverage == 1
        and base.provisional_edge_count == 0
        and pending_reviews == 0
        and not result.degraded_components
        and len(nodes) <= 150
        and all(edge.classification == "direct_parent" for edge in edges)
        and all(edge.evidence for edge in edges)
        and weighted_coverage
        >= (0.86 if result.mode == "precision" else 0.78)
    )
    return result.quality_report.model_copy(
        update={
            **base.model_dump(),
            "weighted_content_coverage": weighted_coverage,
            "direct_parent_confidence": round(
                direct_parent_confidence,
                4,
            ),
            "abstraction_support_rate": round(
                abstraction_support_rate,
                4,
            ),
            "review_item_count": pending_reviews,
            "structural_gate_passed": structural_gate,
            "publish_gate_passed": publish_gate,
            "quality_gate_passed": publish_gate,
            "coverage": CoverageSummary(
                total_units=len(eligible_units),
                covered_units=sum(
                    1 for unit in eligible_units if unit.id in covered
                ),
                weighted_coverage=weighted_coverage,
                uncovered_unit_ids=[
                    unit.id
                    for unit in eligible_units
                    if unit.id not in covered
                ],
                branch_coverage=branch_coverage,
            ),
        }
    )


def _change_parent(
    result: MindMapResult,
    review,
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
    alternative = next(
        (
            item
            for item in review.alternatives
            if str(item.get("parent_id") or "") == parent_id
        ),
        None,
    )
    if alternative is None:
        raise ValueError("所选父节点不在当前复核候选中。")
    classification = str(
        alternative.get("classification") or "uncertain"
    )
    if classification not in {
        "direct_parent",
        "ancestor_only",
        "sibling",
        "cross_link",
        "unrelated",
        "uncertain",
    }:
        classification = "uncertain"
    if classification != "direct_parent":
        raise ValueError("所选父节点尚未被验证为直接父节点。")
    evidence = [
        item
        if isinstance(item, EvidenceRef)
        else EvidenceRef.model_validate(item)
        for item in (alternative.get("evidence") or [])
    ]
    if not evidence:
        raise ValueError("所选父节点缺少可审计的关系证据。")
    score = max(0, min(float(alternative.get("score", 0.5)), 1))
    edges.append(
        MindMapTreeEdge(
            id=stable_id("tree", parent_id, child_id),
            source=parent_id,
            target=child_id,
            score=score,
            provisional=False,
            evidence=evidence,
            classification=classification,
            verifier_votes=[],
        )
    )
    nodes = _recompute_depths(result.root_id, result.nodes, edges)
    return nodes, edges


def _delete_node(
    result: MindMapResult,
    node_id: str,
) -> tuple[
    list[MindMapNode],
    list[MindMapTreeEdge],
    list[MindMapCrossLink],
    list[ReviewItemView],
]:
    if node_id == result.root_id:
        raise ValueError("不能删除当前根节点。")
    incoming_edge = next(
        (edge for edge in result.tree_edges if edge.target == node_id),
        None,
    )
    if not incoming_edge:
        raise ValueError("待删除节点没有可用父节点。")
    parent_id = incoming_edge.source
    outgoing_edges = [
        edge
        for edge in result.tree_edges
        if edge.source == node_id
    ]
    nodes = [node for node in result.nodes if node.id != node_id]
    edges = [
        edge
        for edge in result.tree_edges
        if edge.source != node_id and edge.target != node_id
    ]
    replacement_reviews: list[ReviewItemView] = []
    for child_edge in outgoing_edges:
        child_id = child_edge.target
        evidence = []
        seen_evidence: set[tuple] = set()
        for item in [*incoming_edge.evidence, *child_edge.evidence]:
            signature = (
                item.unit_id,
                item.chunk_id,
                item.excerpt,
                item.page,
                item.slide,
                tuple(item.bbox or []),
                item.asset_id,
            )
            if signature in seen_evidence:
                continue
            seen_evidence.add(signature)
            evidence.append(item)
        replacement_score = round(
            min(incoming_edge.score, child_edge.score) * 0.8,
            4,
        )
        replacement_id = stable_id("tree", parent_id, child_id)
        edges.append(
            MindMapTreeEdge(
                id=replacement_id,
                source=parent_id,
                target=child_id,
                score=replacement_score,
                provisional=True,
                evidence=evidence,
                classification="uncertain",
                verifier_votes=[],
            )
        )
        replacement_reviews.append(
            ReviewItemView(
                id=stable_id(
                    "review",
                    "human_delete_reparent",
                    parent_id,
                    child_id,
                ),
                type="competing_parent",
                risk_score=1,
                subject_ids=[parent_id, child_id],
                subject_id=child_id,
                subject_type="tree_edge",
                reason=(
                    "删除中间节点后生成了保守的临时父边，"
                    "必须重新确认直接父节点。"
                ),
                alternatives=[
                    {
                        "parent_id": parent_id,
                        "score": replacement_score,
                        "classification": "uncertain",
                        "provisional": True,
                    }
                ],
            )
        )
    nodes = _recompute_depths(result.root_id, nodes, edges)
    cross_links = [
        link
        for link in result.cross_links
        if link.source != node_id and link.target != node_id
    ]
    return nodes, edges, cross_links, replacement_reviews


def _confirm_selected_edge(
    result: MindMapResult,
    child_id: str,
) -> list[MindMapTreeEdge]:
    selected = [
        edge for edge in result.tree_edges if edge.target == child_id
    ]
    if len(selected) != 1:
        raise ValueError("待确认节点没有唯一的当前父边。")
    if not selected[0].evidence:
        raise ValueError("当前父边缺少可审计的关系证据，不能直接确认。")
    return [
        edge.model_copy(
            update={
                "provisional": False,
                "classification": "direct_parent",
            }
        )
        if edge.target == child_id
        else edge
        for edge in result.tree_edges
    ]


def resolve_review_item(
    *,
    blackboard: SQLiteBlackboard,
    task_id: str,
    review_id: str,
    request: ReviewResolutionRequest,
    owner_id: str | None = None,
) -> MindMapResult:
    result = blackboard.load_latest_result(task_id, owner_id=owner_id)
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
    if request.expected_graph_version != result.graph_version:
        raise ValueError(
            f"图版本冲突：期望 v{request.expected_graph_version}，"
            f"当前为 v{result.graph_version}。"
        )

    _validate_review_action(review, request.action)
    subject_id = _selected_subject_node(result, review)
    nodes = list(result.nodes)
    edges = list(result.tree_edges)
    cross_links = list(result.cross_links)
    replacement_reviews: list[ReviewItemView] = []
    decision = request.action
    reason_codes = [f"human_{request.action}"]

    if request.action == "change_parent":
        nodes, edges = _change_parent(
            result,
            review,
            subject_id,
            request.parent_id or "",
        )
    elif request.action == "delete":
        (
            nodes,
            edges,
            cross_links,
            replacement_reviews,
        ) = _delete_node(result, subject_id)
    elif request.action == "rename":
        label = request.label.strip()
        subject = next(node for node in nodes if node.id == subject_id)
        renamed_subject = subject.model_copy(update={"name": label})
        if not is_publishable_node_label(renamed_subject):
            raise ValueError("新名称未通过节点标签发布资格门。")
        label_key = normalized_key(label)
        if any(
            node.id != subject_id
            and node.branch_id == subject.branch_id
            and normalized_key(node.name) == label_key
            for node in nodes
        ):
            raise ValueError("同一分支已存在规范化同名节点，不能重复命名。")
        nodes = [
            node.model_copy(update={"name": label})
            if node.id == subject_id
            else node
            for node in nodes
        ]
    elif request.action == "accept_root":
        requested_root = request.parent_id or subject_id
        if requested_root != result.root_id:
            raise ValueError("当前图版本未激活该根候选，需重新求解后才能切换。")
    elif request.action == "keep" and review.type == "competing_parent":
        edges = _confirm_selected_edge(result, subject_id)

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
        if (
            item.id == review_id
            or subject_id not in item.subject_ids
            or request.action != "delete"
        )
    ]
    review_items.extend(replacement_reviews)
    nodes = _refresh_node_review_state(
        root_id=result.root_id,
        nodes=nodes,
        edges=edges,
        reviews=review_items,
    )
    pending_count = sum(1 for item in review_items if item.status == "pending")
    quality = _replace_quality(
        result,
        nodes,
        edges,
        cross_links,
        pending_count,
    )
    decision_subject_type = "node"
    decision_subject_id = subject_id or review_id
    if review.type == "root_choice":
        decision_subject_type = "root"
        decision_subject_id = result.root_id
    elif (
        review.type == "competing_parent"
        and request.action in {"keep", "change_parent"}
    ):
        selected_edge = next(
            (edge for edge in edges if edge.target == subject_id),
            None,
        )
        if not selected_edge:
            raise ValueError("复核后的父边不存在。")
        decision_subject_type = "tree_edge"
        decision_subject_id = selected_edge.id
    elif review.type == "cross_link":
        selected_link = next(
            (
                link
                for link in cross_links
                if link.id == review.subject_id
                or (
                    link.source in review.subject_ids
                    and link.target in review.subject_ids
                )
            ),
            None,
        )
        decision_subject_type = "cross_link"
        decision_subject_id = (
            selected_link.id
            if selected_link
            else review.subject_id or review.id
        )

    record = DecisionRecord(
        id=stable_id(
            "decision",
            result.run_id,
            "human",
            review_id,
            str(result.graph_version + 1),
        ),
        run_id=result.run_id,
        subject_type=decision_subject_type,
        subject_id=decision_subject_id,
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
            "cross_links": cross_links,
            "review_items": review_items,
            "decision_records": [*result.decision_records, record],
            "quality_report": quality,
        }
    )
    version = blackboard.commit_review_resolution(
        run_id=result.run_id,
        review_id=review_id,
        expected_version=request.expected_graph_version,
        result=updated,
        decision=record,
        resolution=resolution,
    )
    return updated.model_copy(update={"graph_version": version})
