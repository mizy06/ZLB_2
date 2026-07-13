from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from .schemas import (
    ChunkExtraction,
    KnowledgeEdge,
    KnowledgeNode,
    QualityReport,
)


def _key(name: str) -> str:
    return re.sub(r"[\s·•,，。；;:：()（）_-]+", "", name).casefold()


def build_graph(
    extractions: list[ChunkExtraction],
) -> tuple[list[KnowledgeNode], list[KnowledgeEdge], QualityReport]:
    node_groups: dict[str, list] = defaultdict(list)
    for extraction in extractions:
        for node in extraction.nodes:
            if _key(node.name):
                node_groups[_key(node.name)].append(node)

    nodes: list[KnowledgeNode] = []
    name_to_id: dict[str, str] = {}
    for normalized, candidates in node_groups.items():
        candidates.sort(key=lambda item: item.confidence, reverse=True)
        primary = candidates[0]
        node_id = f"node_{hashlib.sha1(normalized.encode()).hexdigest()[:10]}"
        evidence = []
        aliases = set(primary.aliases)
        chunks = set()
        definitions = []
        for candidate in candidates:
            aliases.update(candidate.aliases)
            if candidate.name != primary.name:
                aliases.add(candidate.name)
            if candidate.definition:
                definitions.append(candidate.definition)
            for item in candidate.evidence:
                if (item.chunk_id, item.excerpt) not in {
                    (seen.chunk_id, seen.excerpt) for seen in evidence
                }:
                    evidence.append(item)
                chunks.add(item.chunk_id)
        node = KnowledgeNode(
            id=node_id,
            name=primary.name,
            type=primary.type,
            definition=max(definitions, key=len) if definitions else "",
            aliases=sorted(aliases),
            confidence=round(
                sum(item.confidence for item in candidates) / len(candidates), 3
            ),
            evidence=evidence[:8],
            source_chunks=sorted(chunks),
        )
        nodes.append(node)
        for candidate in candidates:
            name_to_id[_key(candidate.name)] = node_id

    node_by_id = {node.id: node for node in nodes}
    edge_groups: dict[tuple[str, str, str], list] = defaultdict(list)
    for extraction in extractions:
        for edge in extraction.edges:
            source_id = name_to_id.get(_key(edge.source))
            target_id = name_to_id.get(_key(edge.target))
            if not source_id or not target_id or source_id == target_id:
                continue
            edge_groups[(source_id, edge.predicate, target_id)].append(edge)

    edges: list[KnowledgeEdge] = []
    for (source_id, predicate, target_id), candidates in edge_groups.items():
        evidence = [
            item
            for candidate in candidates
            for item in candidate.evidence
        ][:8]
        signature = f"{source_id}:{predicate}:{target_id}"
        edges.append(
            KnowledgeEdge(
                id=f"edge_{hashlib.sha1(signature.encode()).hexdigest()[:10]}",
                source=source_id,
                predicate=predicate,
                target=target_id,
                confidence=round(
                    sum(item.confidence for item in candidates) / len(candidates),
                    3,
                ),
                evidence=evidence,
            )
        )

    degree = defaultdict(int)
    for edge in edges:
        degree[edge.source] += 1
        degree[edge.target] += 1
    isolated = sum(1 for node in nodes if degree[node.id] == 0)
    evidence_nodes = sum(1 for node in nodes if node.evidence)
    warnings: list[str] = []
    if isolated and nodes:
        warnings.append(f"{isolated} 个节点暂未形成可靠关系，建议进入补边或人工复核。")
    if any(not node.definition for node in nodes):
        warnings.append("部分候选节点缺少明确原文定义。")

    nodes.sort(key=lambda item: (-degree[item.id], -item.confidence, item.name))
    edges.sort(key=lambda item: item.confidence, reverse=True)
    report = QualityReport(
        node_count=len(nodes),
        edge_count=len(edges),
        isolated_node_count=isolated,
        evidence_coverage=round(evidence_nodes / len(nodes), 3) if nodes else 0,
        warnings=warnings,
    )
    return nodes, edges, report
