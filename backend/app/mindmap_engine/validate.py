from __future__ import annotations

from collections import Counter

import networkx as nx

from .schemas import (
    EngineQualityReport,
    NormalizedNode,
    TreeEdge,
    ValidateRequest,
)


def build_quality_report(
    nodes: list[NormalizedNode],
    tree_edges: list[TreeEdge],
    cross_link_count: int = 0,
) -> EngineQualityReport:
    node_ids = {node.id for node in nodes}
    graph = nx.DiGraph()
    graph.add_nodes_from(node_ids)

    warnings: list[str] = []
    invalid_endpoint_count = 0
    for edge in tree_edges:
        if edge.source not in node_ids or edge.target not in node_ids:
            invalid_endpoint_count += 1
            continue
        graph.add_edge(edge.source, edge.target)

    indegree = Counter(edge.target for edge in tree_edges if edge.target in node_ids)
    roots = [node_id for node_id in node_ids if indegree[node_id] == 0]
    multiple_parent_count = sum(1 for count in indegree.values() if count > 1)
    cycle_count = 0 if nx.is_directed_acyclic_graph(graph) else 1

    orphan_count = 0
    if len(roots) == 1:
        reachable = nx.descendants(graph, roots[0]) | {roots[0]}
        orphan_count = len(node_ids - reachable)
    else:
        orphan_count = max(len(node_ids) - len(roots), 0)

    evidence_nodes = sum(
        1
        for node in nodes
        if node.evidence or node.support_unit_ids or node.media_asset_ids
    )
    evidence_coverage = (
        round(evidence_nodes / len(nodes), 4)
        if nodes
        else 0
    )
    provisional_count = sum(1 for edge in tree_edges if edge.provisional)
    conflict_count = (
        invalid_endpoint_count
        + multiple_parent_count
        + cycle_count
        + abs(len(roots) - 1)
    )
    topology_valid = (
        bool(nodes)
        and len(roots) == 1
        and multiple_parent_count == 0
        and cycle_count == 0
        and orphan_count == 0
        and invalid_endpoint_count == 0
        and len(tree_edges) == max(len(nodes) - 1, 0)
    )

    if len(roots) != 1:
        warnings.append(f"主树应有 1 个根，当前检测到 {len(roots)} 个。")
    if multiple_parent_count:
        warnings.append(f"{multiple_parent_count} 个节点拥有多个主父节点。")
    if cycle_count:
        warnings.append("主树包含环。")
    if orphan_count:
        warnings.append(f"{orphan_count} 个节点无法从根到达。")
    if invalid_endpoint_count:
        warnings.append(f"{invalid_endpoint_count} 条主边引用了不存在的节点。")
    if provisional_count:
        warnings.append(
            f"{provisional_count} 条临时保底父边必须经过人工复核后才能发布。"
        )
    if evidence_coverage < 1:
        warnings.append("部分节点缺少直接证据、聚合支持集或视觉资产。")

    return EngineQualityReport(
        node_count=len(nodes),
        tree_edge_count=len(tree_edges),
        cross_link_count=cross_link_count,
        root_count=len(roots),
        orphan_count=orphan_count,
        conflict_count=conflict_count,
        provisional_edge_count=provisional_count,
        evidence_coverage=evidence_coverage,
        topology_valid=topology_valid,
        warnings=warnings,
    )


def validate_graph(request: ValidateRequest) -> EngineQualityReport:
    return build_quality_report(
        request.nodes,
        request.tree_edges,
        len(request.cross_links),
    )
