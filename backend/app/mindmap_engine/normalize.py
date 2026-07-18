from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from .schemas import (
    CrossLinkCandidateIn,
    EvidenceRef,
    NodeCandidateIn,
    NormalizeRequest,
    NormalizedCrossLinkCandidate,
    NormalizedGraph,
    NormalizedNode,
    NormalizedParentCandidate,
    ParentCandidateIn,
)


_KEY_PATTERN = re.compile(r"[\s·•,，。；;:：()（）【】\[\]{}《》<>_-]+")


def normalized_key(value: str) -> str:
    return _KEY_PATTERN.sub("", value).casefold()


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _dedupe_evidence(items: list[EvidenceRef], limit: int = 16) -> list[EvidenceRef]:
    seen: set[tuple] = set()
    result: list[EvidenceRef] = []
    for item in items:
        key = (
            item.unit_id,
            item.chunk_id,
            item.excerpt,
            item.page,
            item.slide,
            tuple(item.bbox or []),
            item.asset_id,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _candidate_rank(candidate: NodeCandidateIn) -> tuple[float, int, int, int]:
    evidence_bonus = min(len(candidate.evidence), 4) * 0.03
    support_bonus = min(len(candidate.support_unit_ids), 6) * 0.02
    definition_bonus = min(len(candidate.definition), 180) / 1800
    return (
        candidate.confidence + evidence_bonus + support_bonus + definition_bonus,
        len(candidate.definition),
        -len(candidate.name),
        -len(candidate.temp_id),
    )


def _merge_nodes(
    request: NormalizeRequest,
) -> tuple[list[NormalizedNode], dict[str, str], list[str]]:
    grouped: dict[str, list[NodeCandidateIn]] = defaultdict(list)
    for candidate in request.nodes:
        key = normalized_key(candidate.name)
        if key:
            grouped[key].append(candidate)

    warnings: list[str] = []
    nodes: list[NormalizedNode] = []
    reference_to_id: dict[str, str] = {}

    for key, candidates in grouped.items():
        ordered = sorted(candidates, key=_candidate_rank, reverse=True)
        primary = ordered[0]
        node_id = _stable_id("node", key)
        aliases: set[str] = set(primary.aliases)
        temp_ids: set[str] = set()
        support_ids: set[str] = set()
        media_ids: set[str] = set()
        evidence: list[EvidenceRef] = []
        definitions: list[str] = []

        for candidate in ordered:
            temp_ids.add(candidate.temp_id)
            aliases.update(candidate.aliases)
            if candidate.name != primary.name:
                aliases.add(candidate.name)
            support_ids.update(candidate.support_unit_ids)
            media_ids.update(candidate.media_asset_ids)
            evidence.extend(candidate.evidence)
            if candidate.definition:
                definitions.append(candidate.definition)

        is_root_candidate = any(item.is_root_candidate for item in candidates)
        origin = (
            "synthesized_root"
            if is_root_candidate
            else max(candidates, key=lambda item: _candidate_rank(item)).origin
        )
        role = "root_topic" if is_root_candidate else (primary.role or primary.type)
        confidence = round(
            sum(item.confidence for item in candidates) / len(candidates),
            4,
        )
        activation_scores = [
            item.activation_score
            for item in candidates
            if item.activation_score is not None
        ]
        activation_score = (
            sum(activation_scores) / len(activation_scores)
            if activation_scores
            else confidence
        )
        node = NormalizedNode(
            id=node_id,
            temp_ids=sorted(temp_ids),
            name=primary.name.strip(),
            type=primary.type,
            role=role,
            definition=max(definitions, key=len) if definitions else "",
            aliases=sorted(alias for alias in aliases if alias.strip()),
            origin=origin,
            branch_id=primary.branch_id,
            confidence=confidence,
            optional=(
                False
                if is_root_candidate
                else all(item.optional for item in candidates)
            ),
            activation_score=round(activation_score, 4),
            activation_cost=round(
                max(item.activation_cost for item in candidates),
                4,
            ),
            is_root_candidate=is_root_candidate,
            evidence=_dedupe_evidence(evidence),
            support_unit_ids=sorted(support_ids),
            media_asset_ids=sorted(media_ids),
        )
        nodes.append(node)

        references = {
            primary.name,
            normalized_key(primary.name),
            node_id,
            *temp_ids,
            *aliases,
        }
        for reference in references:
            if not reference:
                continue
            reference_to_id[reference] = node_id
            reference_to_id[normalized_key(reference)] = node_id

        if len(candidates) > 1:
            warnings.append(
                f"节点“{primary.name}”合并了 {len(candidates)} 个同名或规范化重复候选。"
            )

    if not any(node.is_root_candidate for node in nodes):
        title = request.document_title.strip() or "课程主题"
        key = normalized_key(title) or request.document_id
        root_id = _stable_id("node", f"root:{key}")
        support_ids = sorted(
            {
                unit_id
                for node in nodes
                for unit_id in node.support_unit_ids
            }
        )
        root = NormalizedNode(
            id=root_id,
            temp_ids=["generated_root"],
            name=title,
            type="root_topic",
            role="root_topic",
            definition=f"{title}的课程思维导图中心主题",
            aliases=[],
            origin="synthesized_root",
            confidence=0.72,
            optional=False,
            activation_score=0.72,
            activation_cost=0,
            is_root_candidate=True,
            evidence=[
                EvidenceRef(
                    unit_id="document:title",
                    chunk_id=request.document_id,
                    excerpt=title,
                )
            ],
            support_unit_ids=support_ids,
            media_asset_ids=[],
        )
        nodes.append(root)
        reference_to_id[root_id] = root_id
        reference_to_id["generated_root"] = root_id
        reference_to_id[title] = root_id
        reference_to_id[normalized_key(title)] = root_id
        warnings.append("输入没有根候选，已使用文档标题生成可审计的保底根候选。")

    nodes.sort(
        key=lambda item: (
            not item.is_root_candidate,
            item.branch_id or "",
            -item.confidence,
            item.name,
        )
    )
    return nodes, reference_to_id, warnings


def _resolve_reference(reference: str, references: dict[str, str]) -> str | None:
    return references.get(reference) or references.get(normalized_key(reference))


def _character_bigrams(value: str) -> set[str]:
    key = normalized_key(value)
    if len(key) < 2:
        return {key} if key else set()
    return {key[index : index + 2] for index in range(len(key) - 1)}


def _role_compatibility(parent: NormalizedNode, child: NormalizedNode) -> float:
    if parent.is_root_candidate:
        return 0.35
    matrix = {
        ("branch_topic", "concept"): 0.64,
        ("branch_topic", "principle"): 0.64,
        ("branch_topic", "method"): 0.62,
        ("branch_topic", "process"): 0.62,
        ("branch_topic", "formula"): 0.56,
        ("branch_topic", "example"): 0.5,
        ("concept", "example"): 0.58,
        ("concept", "formula"): 0.48,
        ("principle", "method"): 0.62,
        ("principle", "formula"): 0.6,
        ("principle", "example"): 0.5,
        ("method", "step"): 0.7,
        ("method", "example"): 0.58,
        ("process", "step"): 0.78,
        ("system", "concept"): 0.52,
        ("system", "method"): 0.46,
        ("visual_knowledge", "concept"): 0.34,
    }
    score = matrix.get((parent.role, child.role), 0.24)
    if parent.origin in {"abstractive", "structural"}:
        score += 0.12
    if parent.role in {"example", "warning", "formula", "step"}:
        score -= 0.2
    return max(0, min(score, 1))


def _suggestion_score(parent: NormalizedNode, child: NormalizedNode) -> float:
    score = _role_compatibility(parent, child)
    if parent.branch_id and parent.branch_id == child.branch_id:
        score += 0.14
    elif (
        parent.branch_id
        and child.branch_id
        and parent.branch_id != child.branch_id
        and not parent.is_root_candidate
    ):
        score -= 0.16

    combined_child_text = f"{child.name} {child.definition}".casefold()
    if parent.name.casefold() in combined_child_text:
        score += 0.16

    parent_bigrams = _character_bigrams(parent.name)
    child_bigrams = _character_bigrams(child.name)
    union = parent_bigrams | child_bigrams
    if union:
        score += 0.08 * (len(parent_bigrams & child_bigrams) / len(union))

    if parent.confidence >= child.confidence:
        score += 0.03
    return round(max(0, min(score, 0.92)), 4)


def _suggest_parent_candidates(
    nodes: list[NormalizedNode],
    existing: list[NormalizedParentCandidate],
    max_per_child: int,
) -> list[NormalizedParentCandidate]:
    by_pair = {
        (candidate.parent_id, candidate.child_id): candidate
        for candidate in existing
    }
    incoming_count: dict[str, int] = defaultdict(int)
    for candidate in existing:
        if not candidate.provisional:
            incoming_count[candidate.child_id] += 1

    for child in nodes:
        if child.is_root_candidate:
            continue
        suggestions: list[NormalizedParentCandidate] = []
        for parent in nodes:
            if parent.id == child.id or child.is_root_candidate:
                continue
            if (parent.id, child.id) in by_pair:
                continue
            score = _suggestion_score(parent, child)
            if score < 0.28:
                continue
            suggestions.append(
                NormalizedParentCandidate(
                    parent_id=parent.id,
                    child_id=child.id,
                    score=score,
                    classification="uncertain",
                    provisional=False,
                )
            )
        suggestions.sort(key=lambda item: item.score, reverse=True)
        remaining = max(max_per_child - incoming_count[child.id], 0)
        for candidate in suggestions[:remaining]:
            by_pair[(candidate.parent_id, candidate.child_id)] = candidate
    return list(by_pair.values())


def _combined_parent_score(candidate: ParentCandidateIn) -> float:
    component_values = [
        candidate.section_prior,
        candidate.semantic_score,
        candidate.reranker_score,
        candidate.verifier_score,
        candidate.evidence_support,
        candidate.granularity_fit,
        candidate.sibling_coherence,
    ]
    populated = [value for value in component_values if value > 0]
    component_score = (
        sum(populated) / len(populated)
        if populated
        else candidate.score
    )
    score = (
        0.5 * candidate.score
        + 0.5 * component_score
        - 0.25 * candidate.skipped_level_penalty
        - 0.25 * candidate.role_conflict_penalty
    )
    if candidate.classification == "direct_parent":
        score += 0.08
    elif candidate.classification == "ancestor_only":
        score -= 0.12
    elif candidate.classification in {"sibling", "cross_link"}:
        score -= 0.35
    elif candidate.classification in {"unrelated", "uncertain"}:
        score -= 0.5
    return round(max(0, min(score, 1)), 4)


def _normalize_parent_candidates(
    candidates: list[ParentCandidateIn],
    nodes: list[NormalizedNode],
    references: dict[str, str],
    max_per_child: int,
) -> tuple[list[NormalizedParentCandidate], list[str]]:
    warnings: list[str] = []
    node_by_id = {node.id: node for node in nodes}
    grouped: dict[tuple[str, str], list[NormalizedParentCandidate]] = defaultdict(list)

    for candidate in candidates:
        parent_id = _resolve_reference(candidate.parent, references)
        child_id = _resolve_reference(candidate.child, references)
        if not parent_id or not child_id:
            warnings.append(
                f"父边候选 {candidate.parent} -> {candidate.child} 引用了未知节点，已忽略。"
            )
            continue
        if parent_id == child_id:
            continue
        if node_by_id[child_id].is_root_candidate:
            continue
        grouped[(parent_id, child_id)].append(
            NormalizedParentCandidate(
                parent_id=parent_id,
                child_id=child_id,
                score=_combined_parent_score(candidate),
                classification=candidate.classification,
                provisional=candidate.provisional,
                evidence=_dedupe_evidence(candidate.evidence),
            )
        )

    normalized: list[NormalizedParentCandidate] = []
    for pair, items in grouped.items():
        best = max(items, key=lambda item: item.score)
        evidence = _dedupe_evidence(
            [evidence for item in items for evidence in item.evidence]
        )
        normalized.append(best.model_copy(update={"evidence": evidence}))

    incoming: dict[str, list[NormalizedParentCandidate]] = defaultdict(list)
    for candidate in normalized:
        incoming[candidate.child_id].append(candidate)

    root_nodes = [node for node in nodes if node.is_root_candidate]
    for child in nodes:
        if child.is_root_candidate:
            continue
        child_candidates = incoming.get(child.id, [])
        existing_parents = {item.parent_id for item in child_candidates}

        branch_topics = [
            node
            for node in nodes
            if node.id != child.id
            and node.role == "branch_topic"
            and node.branch_id
            and node.branch_id == child.branch_id
        ]
        for branch_topic in branch_topics[:2]:
            if branch_topic.id in existing_parents:
                continue
            fallback = NormalizedParentCandidate(
                parent_id=branch_topic.id,
                child_id=child.id,
                score=0.24,
                classification="uncertain",
                provisional=True,
            )
            child_candidates.append(fallback)
            existing_parents.add(branch_topic.id)

        for root in root_nodes:
            if root.id in existing_parents:
                continue
            fallback = NormalizedParentCandidate(
                parent_id=root.id,
                child_id=child.id,
                score=0.12,
                classification="uncertain",
                provisional=True,
            )
            child_candidates.append(fallback)

        child_candidates.sort(
            key=lambda item: (item.provisional, -item.score, item.parent_id)
        )
        incoming[child.id] = child_candidates[:max_per_child]

    flattened = [
        candidate
        for child_id in sorted(incoming)
        for candidate in incoming[child_id]
    ]
    suggested = _suggest_parent_candidates(nodes, flattened, max_per_child)
    regrouped: dict[str, list[NormalizedParentCandidate]] = defaultdict(list)
    for candidate in suggested:
        regrouped[candidate.child_id].append(candidate)
    limited: list[NormalizedParentCandidate] = []
    for child_id in sorted(regrouped):
        child_candidates = sorted(
            regrouped[child_id],
            key=lambda item: (item.provisional, -item.score, item.parent_id),
        )
        nonprovisional = [
            item for item in child_candidates if not item.provisional
        ][:max_per_child]
        provisional = [
            item for item in child_candidates if item.provisional
        ]
        limited.extend(nonprovisional)
        if provisional:
            limited.append(max(provisional, key=lambda item: item.score))
    return limited, warnings


def _normalize_cross_links(
    candidates: list[CrossLinkCandidateIn],
    references: dict[str, str],
) -> tuple[list[NormalizedCrossLinkCandidate], list[str]]:
    warnings: list[str] = []
    best_by_signature: dict[
        tuple[str, str, str],
        NormalizedCrossLinkCandidate,
    ] = {}
    for candidate in candidates:
        source_id = _resolve_reference(candidate.source, references)
        target_id = _resolve_reference(candidate.target, references)
        if not source_id or not target_id:
            warnings.append(
                f"跨链候选 {candidate.source} -> {candidate.target} 引用了未知节点，已忽略。"
            )
            continue
        if source_id == target_id:
            continue
        normalized = NormalizedCrossLinkCandidate(
            source_id=source_id,
            target_id=target_id,
            relation=candidate.relation,
            score=candidate.score,
            evidence=_dedupe_evidence(candidate.evidence),
        )
        signature = (source_id, candidate.relation, target_id)
        previous = best_by_signature.get(signature)
        if not previous or normalized.score > previous.score:
            best_by_signature[signature] = normalized
    return list(best_by_signature.values()), warnings


def normalize_graph(request: NormalizeRequest) -> NormalizedGraph:
    nodes, references, node_warnings = _merge_nodes(request)
    parents, parent_warnings = _normalize_parent_candidates(
        request.parent_candidates,
        nodes,
        references,
        request.max_parents_per_node,
    )
    cross_links, cross_warnings = _normalize_cross_links(
        request.cross_links,
        references,
    )
    return NormalizedGraph(
        document_id=request.document_id,
        document_title=request.document_title,
        nodes=nodes,
        parent_candidates=parents,
        cross_links=cross_links,
        warnings=[*node_warnings, *parent_warnings, *cross_warnings],
    )
