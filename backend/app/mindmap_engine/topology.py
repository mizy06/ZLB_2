from __future__ import annotations

import hashlib
from collections import defaultdict

import networkx as nx
from ortools.sat.python import cp_model

from .schemas import (
    CrossLink,
    NormalizedGraph,
    NormalizedNode,
    NormalizedParentCandidate,
    ReviewItem,
    SolveRequest,
    SolveResponse,
    TreeEdge,
)
from .validate import build_quality_report


def _stable_id(prefix: str, *parts: str) -> str:
    signature = ":".join(parts)
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _edge_from_candidate(candidate: NormalizedParentCandidate) -> TreeEdge:
    return TreeEdge(
        id=_stable_id("tree", candidate.parent_id, candidate.child_id),
        source=candidate.parent_id,
        target=candidate.child_id,
        score=candidate.score,
        provisional=candidate.provisional,
        evidence=candidate.evidence,
    )


def _select_cross_links(
    graph: NormalizedGraph,
    active_ids: set[str],
    review_items: list[ReviewItem],
) -> list[CrossLink]:
    selected: list[CrossLink] = []
    outgoing_count: dict[str, int] = defaultdict(int)
    for candidate in sorted(
        graph.cross_links,
        key=lambda item: (-item.score, item.source_id, item.target_id),
    ):
        if candidate.source_id not in active_ids or candidate.target_id not in active_ids:
            continue
        if candidate.score < 0.7:
            continue
        if not candidate.evidence:
            review_items.append(
                ReviewItem(
                    id=_stable_id(
                        "review",
                        "cross_link",
                        candidate.source_id,
                        candidate.target_id,
                        candidate.relation,
                    ),
                    type="cross_link",
                    risk_score=round(1 - candidate.score, 4),
                    subject_ids=[candidate.source_id, candidate.target_id],
                    reason="跨链候选没有绑定可审计证据。",
                    alternatives=[
                        {
                            "relation": candidate.relation,
                            "score": candidate.score,
                        }
                    ],
                )
            )
            continue
        if outgoing_count[candidate.source_id] >= 2:
            continue
        selected.append(
            CrossLink(
                id=_stable_id(
                    "cross",
                    candidate.source_id,
                    candidate.relation,
                    candidate.target_id,
                ),
                source=candidate.source_id,
                target=candidate.target_id,
                relation=candidate.relation,
                score=candidate.score,
                evidence=candidate.evidence,
            )
        )
        outgoing_count[candidate.source_id] += 1
    return selected


def _review_selected_structure(
    request: SolveRequest,
    root_id: str,
    active_nodes: list[NormalizedNode],
    selected_edges: list[TreeEdge],
) -> list[ReviewItem]:
    graph = request.graph
    reviews: list[ReviewItem] = []
    root_candidates = sorted(
        (node for node in graph.nodes if node.is_root_candidate),
        key=lambda item: item.confidence,
        reverse=True,
    )
    if len(root_candidates) > 1:
        selected_root = next(node for node in root_candidates if node.id == root_id)
        alternatives = [
            {
                "node_id": node.id,
                "name": node.name,
                "confidence": node.confidence,
                "selected": node.id == root_id,
            }
            for node in root_candidates
        ]
        second_score = max(
            (
                node.confidence
                for node in root_candidates
                if node.id != root_id
            ),
            default=0,
        )
        gap = max(selected_root.confidence - second_score, 0)
        if gap < (0.15 if request.mode == "precision" else 0.08):
            reviews.append(
                ReviewItem(
                    id=_stable_id("review", "root", root_id),
                    type="root_choice",
                    risk_score=round(1 - gap, 4),
                    subject_ids=[node.id for node in root_candidates],
                    reason="多个根候选得分接近，需要确认中心主题。",
                    alternatives=alternatives,
                )
            )

    candidates_by_child: dict[str, list[NormalizedParentCandidate]] = defaultdict(list)
    for candidate in graph.parent_candidates:
        candidates_by_child[candidate.child_id].append(candidate)

    for edge in selected_edges:
        if edge.provisional:
            reviews.append(
                ReviewItem(
                    id=_stable_id("review", "provisional", edge.source, edge.target),
                    type="competing_parent",
                    risk_score=1,
                    subject_ids=[edge.source, edge.target],
                    reason="求解器选择了临时保底父边，发布前必须人工确认。",
                    alternatives=[
                        {
                            "parent_id": item.parent_id,
                            "score": item.score,
                            "provisional": item.provisional,
                        }
                        for item in sorted(
                            candidates_by_child[edge.target],
                            key=lambda item: item.score,
                            reverse=True,
                        )[:5]
                    ],
                )
            )
            continue

        ranked = sorted(
            (
                item
                for item in candidates_by_child[edge.target]
                if not item.provisional
            ),
            key=lambda item: item.score,
            reverse=True,
        )
        if len(ranked) < 2:
            continue
        top_score = ranked[0].score
        second_score = ranked[1].score
        gap = max(top_score - second_score, 0)
        threshold = 0.15 if request.mode == "precision" else 0.08
        if gap < threshold:
            reviews.append(
                ReviewItem(
                    id=_stable_id("review", "parent", edge.target),
                    type="competing_parent",
                    risk_score=round(1 - gap, 4),
                    subject_ids=[
                        edge.target,
                        ranked[0].parent_id,
                        ranked[1].parent_id,
                    ],
                    reason="两个直接父节点候选得分接近。",
                    alternatives=[
                        {
                            "parent_id": item.parent_id,
                            "score": item.score,
                            "classification": item.classification,
                        }
                        for item in ranked[:5]
                    ],
                )
            )

    for node in active_nodes:
        if node.origin not in {"abstractive", "structural"}:
            continue
        support_count = len(node.support_unit_ids) + len(node.evidence)
        margin = node.activation_score - node.activation_cost
        if support_count < 2 or margin < 0.15:
            reviews.append(
                ReviewItem(
                    id=_stable_id("review", "abstract", node.id),
                    type="abstract_parent",
                    risk_score=round(max(0, 1 - max(margin, 0)), 4),
                    subject_ids=[node.id],
                    reason="抽象父节点支持量或激活收益不足。",
                    alternatives=[
                        {
                            "activation_score": node.activation_score,
                            "activation_cost": node.activation_cost,
                            "support_count": support_count,
                        }
                    ],
                )
            )
    return reviews


def _solve_with_cp_sat(
    request: SolveRequest,
) -> tuple[str, list[NormalizedNode], list[TreeEdge], str]:
    graph = request.graph
    nodes = graph.nodes
    node_by_id = {node.id: node for node in nodes}
    roots = [node for node in nodes if node.is_root_candidate]
    if not roots:
        raise ValueError("归一图没有根候选。")

    model = cp_model.CpModel()
    active = {
        node.id: model.new_bool_var(f"active_{index}")
        for index, node in enumerate(nodes)
    }
    depth = {
        node.id: model.new_int_var(0, request.max_depth, f"depth_{index}")
        for index, node in enumerate(nodes)
    }
    edge_vars = {
        (candidate.parent_id, candidate.child_id): model.new_bool_var(
            f"edge_{index}"
        )
        for index, candidate in enumerate(graph.parent_candidates)
    }

    root_ids = {node.id for node in roots}
    model.add(sum(active[node.id] for node in roots) == 1)

    incoming: dict[str, list] = defaultdict(list)
    outgoing: dict[str, list] = defaultdict(list)
    candidate_by_pair: dict[tuple[str, str], NormalizedParentCandidate] = {}
    for candidate in graph.parent_candidates:
        pair = (candidate.parent_id, candidate.child_id)
        variable = edge_vars[pair]
        candidate_by_pair[pair] = candidate
        incoming[candidate.child_id].append(variable)
        outgoing[candidate.parent_id].append(variable)
        model.add(variable <= active[candidate.parent_id])
        model.add(variable <= active[candidate.child_id])
        model.add(
            depth[candidate.child_id] == depth[candidate.parent_id] + 1
        ).only_enforce_if(variable)

    for node in nodes:
        node_active = active[node.id]
        model.add(depth[node.id] <= request.max_depth * node_active)
        if node.id in root_ids:
            model.add(depth[node.id] == 0)
            model.add(sum(incoming[node.id]) == 0)
            continue

        if not node.optional:
            model.add(node_active == 1)
        model.add(depth[node.id] >= node_active)
        model.add(sum(incoming[node.id]) == node_active)

        if node.optional and node.origin in {"abstractive", "structural"}:
            children = outgoing[node.id]
            if len(children) < 2:
                model.add(node_active == 0)
            else:
                model.add(sum(children) >= 2 * node_active)

    objective_terms = []
    for pair, variable in edge_vars.items():
        candidate = candidate_by_pair[pair]
        edge_score = int(round(candidate.score * 1000))
        if candidate.provisional:
            edge_score -= 350
        objective_terms.append(edge_score * variable)

    for node in nodes:
        if node.id in root_ids:
            objective_terms.append(int(round(node.confidence * 300)) * active[node.id])
        elif node.optional:
            activation_value = int(
                round((node.activation_score - node.activation_cost) * 250)
            )
            objective_terms.append(activation_value * active[node.id])

    model.maximize(sum(objective_terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = request.time_limit_seconds
    solver.parameters.num_search_workers = 8
    status = solver.solve(model)
    status_name = solver.status_name(status)
    if status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
        raise RuntimeError(f"CP-SAT 没有找到可行解：{status_name}")

    active_nodes = [
        node for node in nodes if solver.value(active[node.id]) == 1
    ]
    selected_edges = [
        _edge_from_candidate(candidate_by_pair[pair])
        for pair, variable in edge_vars.items()
        if solver.value(variable) == 1
    ]
    root_id = next(
        node.id
        for node in roots
        if solver.value(active[node.id]) == 1
    )

    selected_depths = {
        node.id: solver.value(depth[node.id])
        for node in active_nodes
    }
    active_nodes.sort(
        key=lambda item: (
            selected_depths[item.id],
            item.branch_id or "",
            item.name,
        )
    )
    selected_edges.sort(key=lambda item: (selected_depths[item.target], item.target))
    return root_id, active_nodes, selected_edges, status_name


def _solve_with_greedy_fallback(
    request: SolveRequest,
) -> tuple[str, list[NormalizedNode], list[TreeEdge], str]:
    graph = request.graph
    roots = sorted(
        (node for node in graph.nodes if node.is_root_candidate),
        key=lambda item: item.confidence,
        reverse=True,
    )
    if not roots:
        raise ValueError("归一图没有根候选。")
    root = roots[0]
    active_nodes = [
        node
        for node in graph.nodes
        if node.id == root.id
        or (
            not node.is_root_candidate
            and (
                not node.optional
                or node.activation_score - node.activation_cost >= 0.15
            )
        )
    ]
    active_ids = {node.id for node in active_nodes}
    candidates_by_child: dict[str, list[NormalizedParentCandidate]] = defaultdict(list)
    for candidate in graph.parent_candidates:
        if candidate.parent_id in active_ids and candidate.child_id in active_ids:
            candidates_by_child[candidate.child_id].append(candidate)

    selected: list[TreeEdge] = []
    tree = nx.DiGraph()
    tree.add_nodes_from(active_ids)
    for child in sorted(
        (node for node in active_nodes if node.id != root.id),
        key=lambda item: (item.branch_id or "", -item.confidence, item.name),
    ):
        ranked = sorted(
            candidates_by_child[child.id],
            key=lambda item: (item.provisional, -item.score),
        )
        choice: NormalizedParentCandidate | None = None
        for candidate in ranked:
            if candidate.parent_id == child.id:
                continue
            if nx.has_path(tree, child.id, candidate.parent_id):
                continue
            choice = candidate
            break
        if choice is None:
            choice = NormalizedParentCandidate(
                parent_id=root.id,
                child_id=child.id,
                score=0,
                classification="uncertain",
                provisional=True,
            )
        edge = _edge_from_candidate(choice)
        selected.append(edge)
        tree.add_edge(edge.source, edge.target)

    depths = nx.single_source_shortest_path_length(tree, root.id)
    for edge in list(selected):
        if depths.get(edge.target, request.max_depth + 1) <= request.max_depth:
            continue
        selected.remove(edge)
        tree.remove_edge(edge.source, edge.target)
        replacement = TreeEdge(
            id=_stable_id("tree", root.id, edge.target),
            source=root.id,
            target=edge.target,
            score=0,
            provisional=True,
        )
        selected.append(replacement)
        tree.add_edge(root.id, edge.target)

    active_nodes.sort(
        key=lambda item: (
            nx.shortest_path_length(tree, root.id, item.id)
            if nx.has_path(tree, root.id, item.id)
            else request.max_depth + 1,
            item.name,
        )
    )
    return root.id, active_nodes, selected, "GREEDY_FALLBACK"


def solve_topology(request: SolveRequest) -> SolveResponse:
    warnings = list(request.graph.warnings)
    try:
        root_id, active_nodes, tree_edges, solver_status = _solve_with_cp_sat(request)
    except Exception as exc:
        warnings.append(f"CP-SAT 求解失败，已使用确定性贪心兜底：{exc}")
        root_id, active_nodes, tree_edges, solver_status = _solve_with_greedy_fallback(
            request
        )

    review_items = _review_selected_structure(
        request,
        root_id,
        active_nodes,
        tree_edges,
    )
    active_ids = {node.id for node in active_nodes}
    cross_links = _select_cross_links(request.graph, active_ids, review_items)
    quality = build_quality_report(
        active_nodes,
        tree_edges,
        len(cross_links),
    )
    warnings.extend(quality.warnings)
    return SolveResponse(
        document_id=request.graph.document_id,
        root_id=root_id,
        nodes=active_nodes,
        tree_edges=tree_edges,
        cross_links=cross_links,
        review_items=review_items,
        quality=quality,
        solver_status=solver_status,
        warnings=list(dict.fromkeys(warnings)),
    )
