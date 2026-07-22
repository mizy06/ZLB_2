from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from .agent_prompts import (
    ARBITER_PROMPT,
    BRANCH_EXTRACTOR_PROMPT,
    PARENT_VERIFIER_PROMPT,
    THEME_SYNTHESIZER_PROMPT,
)
from .architecture_schemas import (
    BranchPlan,
    ContentUnit,
    ModelVote,
    RunMode,
)
from .kimi_provider import ModelProviderError, OpenAICompatibleClient
from .heuristics import heuristic_extract
from .mindmap_engine.normalize import normalized_key
from .mindmap_engine.schemas import (
    CrossLinkCandidateIn,
    EvidenceRef,
    NodeCandidateIn,
    NormalizedGraph,
    NormalizedNode,
    NormalizedParentCandidate,
    ParentCandidateIn,
    VisualAsset,
)
from .schemas import Chunk, ParsedDocument


GENERIC_LABELS = {
    "本章",
    "概述",
    "总结",
    "课程内容",
    "基础知识",
    "核心内容",
    "知识点",
    "案例",
    "介绍",
}
CROSS_LINK_RELATIONS = {
    "depends_on",
    "causes",
    "precedes",
    "contrasts_with",
    "used_for",
}


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1(":".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


@dataclass(frozen=True)
class RoleRuntime:
    provider: str
    model: str
    client: OpenAICompatibleClient | None
    available: bool
    unavailable_reason: str = ""


class ThemeNodeSpec(BaseModel):
    temp_id: str
    name: str
    definition: str = ""
    support_unit_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)


class ThemePlanOutput(BaseModel):
    root_candidates: list[ThemeNodeSpec]
    branch_topics: list[ThemeNodeSpec]


class BranchNodeOutput(BaseModel):
    temp_id: str
    name: str
    type: str = "concept"
    role: str = "concept"
    definition: str = ""
    origin: Literal["explicit", "abstractive", "structural"] = "explicit"
    confidence: float = Field(default=0.5, ge=0, le=1)
    optional: bool = False
    activation_score: float | None = Field(default=None, ge=0, le=1)
    activation_cost: float = Field(default=0, ge=0, le=1)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    support_unit_ids: list[str] = Field(default_factory=list)
    media_asset_ids: list[str] = Field(default_factory=list)


class BranchExtractionOutput(BaseModel):
    nodes: list[BranchNodeOutput] = Field(default_factory=list)
    cross_links: list[CrossLinkCandidateIn] = Field(default_factory=list)


class ParentVerificationOutput(BaseModel):
    parent: str
    child: str
    classification: Literal[
        "direct_parent",
        "ancestor_only",
        "sibling",
        "cross_link",
        "unrelated",
        "uncertain",
    ]
    verifier_score: float = Field(default=0.5, ge=0, le=1)
    reason: str = ""


class BranchTeamState(TypedDict, total=False):
    branch: BranchPlan
    units: list[ContentUnit]
    chunks: list[Chunk]
    runtime: RoleRuntime
    nodes: list[NodeCandidateIn]
    parent_candidates: list[ParentCandidateIn]
    cross_links: list[CrossLinkCandidateIn]
    warnings: list[str]
    used_model: bool


class BranchTeamResult(BaseModel):
    branch: BranchPlan
    nodes: list[NodeCandidateIn]
    parent_candidates: list[ParentCandidateIn]
    cross_links: list[CrossLinkCandidateIn]
    warnings: list[str] = Field(default_factory=list)
    used_model: bool = False


def _unit_role(text: str) -> str:
    compact = text[:240]
    if re.search(r"(是指|定义为|称为|即)", compact):
        return "definition"
    if re.search(r"(步骤|首先|然后|最后|流程)", compact):
        return "step"
    if re.search(r"(公式|方程|定理|原理)", compact):
        return "formula" if re.search(r"[=≈∑Σ∫]", compact) else "principle"
    if re.search(r"(例如|示例|案例)", compact):
        return "example"
    if re.search(r"(注意|警告|避免|禁止)", compact):
        return "warning"
    return "other"


def _importance(chunk: Chunk) -> float:
    score = 0.42
    if chunk.heading:
        score += 0.18
    if re.search(r"(定义|原理|方法|步骤|公式|结论|注意)", chunk.text[:500]):
        score += 0.16
    score += min(len(chunk.text), 1800) / 1800 * 0.12
    return round(min(score, 1), 4)


def build_content_units(
    document: ParsedDocument,
    chunks: list[Chunk],
    assets: list[VisualAsset],
) -> list[ContentUnit]:
    units: list[ContentUnit] = []
    for chunk in chunks:
        heading_path = [chunk.heading] if chunk.heading else []
        units.append(
            ContentUnit(
                id=chunk.id,
                document_id=document.document_id,
                kind="text",
                branch_hint=chunk.heading,
                importance=_importance(chunk),
                text=chunk.text,
                heading_path=heading_path,
                unit_role=_unit_role(chunk.text),
                evidence_excerpt=chunk.text[:240],
                page=chunk.page_start,
                slide=chunk.slide_start,
            )
        )

    seen_visual_hashes: set[str] = set()
    for asset in assets:
        if asset.visual_kind == "full_page":
            continue
        duplicate = bool(asset.sha1 and asset.sha1 in seen_visual_hashes)
        if asset.sha1:
            seen_visual_hashes.add(asset.sha1)
        has_knowledge = bool(
            asset.ocr_text.strip()
            or asset.visual_kind in {"chart", "table", "group_diagram", "formula"}
        )
        units.append(
            ContentUnit(
                id=f"visual:{asset.asset_id}",
                document_id=document.document_id,
                kind="visual",
                branch_hint=None,
                importance=0.72 if has_knowledge else 0.18,
                status="rejected" if duplicate else "uncovered",
                evidence_excerpt=asset.ocr_text[:240],
                page=asset.source_page,
                slide=asset.source_slide,
                bbox=asset.bbox,
                asset_id=asset.asset_id,
                visual_kind=asset.visual_kind,
                visual_action=(
                    "standalone_node"
                    if has_knowledge
                    else "attach_as_media"
                ),
                ocr_text=asset.ocr_text,
                summary=asset.ocr_text[:240],
                knowledge_claims=(
                    [line for line in asset.ocr_text.splitlines() if line.strip()][:8]
                    if has_knowledge
                    else []
                ),
                perceptual_hash=asset.sha1,
                knowledge_score=0.78 if has_knowledge else 0.25,
                decorative_score=0.9 if duplicate else (0.65 if not has_knowledge else 0.08),
            )
        )
    return units


def _short_label(text: str, fallback: str) -> str:
    first = text.strip().splitlines()[0] if text.strip() else fallback
    first = first.lstrip("#").strip()
    first = re.split(r"[。！？；;:：]", first)[0].strip()
    first = re.sub(r"^\d+(?:\.\d+)*[\s、.)）-]*", "", first)
    return (first or fallback)[:32]


def _fallback_theme_plan(
    document: ParsedDocument,
    units: list[ContentUnit],
) -> ThemePlanOutput:
    active_units = [unit for unit in units if unit.status != "rejected"]
    support_ids = [unit.id for unit in active_units]
    root = ThemeNodeSpec(
        temp_id="root_document_title",
        name=document.title,
        definition=f"{document.title}的课程知识体系",
        support_unit_ids=support_ids,
        confidence=0.9,
    )

    grouped: dict[str, list[str]] = defaultdict(list)
    for unit in active_units:
        if unit.kind != "text":
            continue
        label = (
            unit.heading_path[0]
            if unit.heading_path
            else _short_label(unit.text, document.title)
        )
        if normalized_key(label) == normalized_key(document.title):
            label = _short_label(unit.text, label)
        grouped[label].append(unit.id)

    if len(grouped) > 8:
        ranked = sorted(
            grouped.items(),
            key=lambda item: (-len(item[1]), item[0]),
        )
        retained = dict(ranked[:7])
        overflow = [
            unit_id
            for _, unit_ids in ranked[7:]
            for unit_id in unit_ids
        ]
        retained[f"{document.title}延伸主题"] = overflow
        grouped = retained

    branches: list[ThemeNodeSpec] = []
    for index, (label, unit_ids) in enumerate(grouped.items(), start=1):
        if label in GENERIC_LABELS:
            label = f"{document.title}主题 {index}"
        branches.append(
            ThemeNodeSpec(
                temp_id=f"branch_{index}",
                name=label,
                definition=f"围绕{label}组织的课程内容",
                support_unit_ids=unit_ids,
                confidence=min(0.72 + 0.02 * len(unit_ids), 0.9),
            )
        )

    if not branches:
        branches = [
            ThemeNodeSpec(
                temp_id="branch_1",
                name=f"{document.title}核心主题",
                definition=f"{document.title}的主要知识内容",
                support_unit_ids=support_ids,
                confidence=0.72,
            )
        ]
    return ThemePlanOutput(root_candidates=[root], branch_topics=branches)


async def synthesize_themes(
    document: ParsedDocument,
    units: list[ContentUnit],
    runtime: RoleRuntime,
) -> tuple[ThemePlanOutput, bool, list[str]]:
    fallback = _fallback_theme_plan(document, units)
    if not runtime.available or not runtime.client:
        warning = (
            f"全局主题模型不可用，已使用确定性主题规划："
            f"{runtime.unavailable_reason or '未配置模型'}"
        )
        return fallback, False, [warning]

    summaries = [
        {
            "unit_id": unit.id,
            "heading_path": unit.heading_path,
            "kind": unit.kind,
            "summary": (
                unit.summary
                or unit.evidence_excerpt
                or unit.text[:280]
            ),
            "importance": unit.importance,
        }
        for unit in sorted(units, key=lambda item: item.importance, reverse=True)[:80]
        if unit.status != "rejected"
    ]
    prompt = json.dumps(
        {
            "document_title": document.title,
            "content_units": summaries,
        },
        ensure_ascii=False,
    )
    try:
        payload = await runtime.client.complete_json(
            model=runtime.model,
            system_prompt=THEME_SYNTHESIZER_PROMPT,
            user_prompt=prompt,
            max_tokens=5000,
        )
        plan = ThemePlanOutput.model_validate(payload)
        valid_ids = {unit.id for unit in units}
        roots = [
            item.model_copy(
                update={
                    "support_unit_ids": [
                        unit_id
                        for unit_id in item.support_unit_ids
                        if unit_id in valid_ids
                    ]
                }
            )
            for item in plan.root_candidates[:3]
            if item.name.strip() and item.name not in GENERIC_LABELS
        ]
        branches = [
            item.model_copy(
                update={
                    "support_unit_ids": [
                        unit_id
                        for unit_id in item.support_unit_ids
                        if unit_id in valid_ids
                    ]
                }
            )
            for item in plan.branch_topics[:12]
            if item.name.strip() and item.name not in GENERIC_LABELS
        ]
        if not roots or not branches:
            raise ValueError("主题模型没有给出可用根或一级主题")
        return ThemePlanOutput(root_candidates=roots, branch_topics=branches), True, []
    except (ModelProviderError, ValueError) as exc:
        return fallback, False, [f"全局主题生成失败，已降级：{exc}"]


def build_branch_plans(
    theme_plan: ThemePlanOutput,
    units: list[ContentUnit],
    *,
    max_units_per_leaf: int = 8,
    max_depth: int = 3,
) -> list[BranchPlan]:
    unit_by_id = {unit.id: unit for unit in units}
    claimed: set[str] = set()
    plans: list[BranchPlan] = []

    for topic in theme_plan.branch_topics:
        unit_ids = [
            unit_id
            for unit_id in topic.support_unit_ids
            if unit_id in unit_by_id and unit_by_id[unit_id].status != "rejected"
        ]
        claimed.update(unit_ids)
        if not unit_ids:
            continue
        plans.append(
            BranchPlan(
                id=stable_id("branch", topic.temp_id, topic.name),
                label=topic.name,
                description=topic.definition,
                unit_ids=unit_ids,
                depth=1,
                cohesion=topic.confidence,
                coverage_budget=max(12, len(unit_ids) * 3),
            )
        )

    unclaimed = [
        unit.id
        for unit in units
        if unit.id not in claimed and unit.status != "rejected"
    ]
    if unclaimed:
        plans.append(
            BranchPlan(
                id=stable_id("branch", "unassigned"),
                label="补充主题",
                description="全局主题规划未覆盖的内容单元",
                unit_ids=unclaimed,
                depth=1,
                cohesion=0.45,
                coverage_budget=max(12, len(unclaimed) * 3),
            )
        )

    expanded: list[BranchPlan] = []

    def split(plan: BranchPlan) -> None:
        if len(plan.unit_ids) <= max_units_per_leaf or plan.depth >= max_depth:
            expanded.append(plan)
            return

        source_units = [unit_by_id[unit_id] for unit_id in plan.unit_ids]
        grouped: dict[str, list[str]] = defaultdict(list)
        for unit in source_units:
            label = (
                unit.heading_path[-1]
                if unit.heading_path
                else _short_label(unit.text or unit.summary, plan.label)
            )
            grouped[label].append(unit.id)

        if len(grouped) <= 1:
            grouped = {
                f"{plan.label} {index // max_units_per_leaf + 1}": plan.unit_ids[
                    index : index + max_units_per_leaf
                ]
                for index in range(0, len(plan.unit_ids), max_units_per_leaf)
            }

        parent = plan.model_copy(update={"leaf": False})
        expanded.append(parent)
        for index, (label, unit_ids) in enumerate(grouped.items(), start=1):
            child = BranchPlan(
                id=stable_id("branch", plan.id, str(index), label),
                label=label if label != plan.label else f"{plan.label} {index}",
                description=f"{plan.label}下的局部主题",
                unit_ids=unit_ids,
                parent_branch_id=plan.id,
                depth=plan.depth + 1,
                cohesion=0.58,
                coverage_budget=max(8, len(unit_ids) * 3),
            )
            split(child)

    for plan in plans:
        split(plan)
    return expanded


def theme_nodes(
    theme_plan: ThemePlanOutput,
    branch_plans: list[BranchPlan],
) -> list[NodeCandidateIn]:
    nodes: list[NodeCandidateIn] = []
    for item in theme_plan.root_candidates:
        nodes.append(
            NodeCandidateIn(
                temp_id=item.temp_id,
                name=item.name,
                type="root_topic",
                role="root_topic",
                definition=item.definition,
                origin="synthesized_root",
                confidence=item.confidence,
                optional=False,
                activation_score=item.confidence,
                is_root_candidate=True,
                support_unit_ids=item.support_unit_ids,
            )
        )

    plan_by_label = {
        normalized_key(item.name): item
        for item in theme_plan.branch_topics
    }
    for plan in branch_plans:
        topic = plan_by_label.get(normalized_key(plan.label))
        confidence = topic.confidence if topic else max(plan.cohesion, 0.55)
        nodes.append(
            NodeCandidateIn(
                temp_id=f"topic:{plan.id}",
                name=plan.label,
                type="branch_topic",
                role="branch_topic",
                definition=plan.description,
                origin="abstractive" if plan.depth == 1 else "structural",
                branch_id=plan.id,
                confidence=confidence,
                optional=False if plan.depth == 1 else True,
                activation_score=confidence,
                activation_cost=0.08 if plan.depth == 1 else 0.18,
                support_unit_ids=plan.unit_ids,
            )
        )
    return nodes


def _to_node_candidate(
    output: BranchNodeOutput,
    branch: BranchPlan,
) -> NodeCandidateIn:
    temp_id = (
        output.temp_id
        if output.temp_id.startswith(f"{branch.id}:")
        else f"{branch.id}:{output.temp_id}"
    )
    return NodeCandidateIn(
        temp_id=temp_id,
        name=output.name.strip(),
        type=output.type,
        role=output.role,
        definition=output.definition.strip(),
        origin=output.origin,
        branch_id=branch.id,
        confidence=output.confidence,
        optional=output.optional,
        activation_score=output.activation_score,
        activation_cost=output.activation_cost,
        evidence=output.evidence,
        support_unit_ids=output.support_unit_ids,
        media_asset_ids=output.media_asset_ids,
    )


def _heuristic_branch_extract(
    branch: BranchPlan,
    chunks: list[Chunk],
    units: list[ContentUnit],
) -> BranchExtractionOutput:
    nodes: list[BranchNodeOutput] = []
    cross_links: list[CrossLinkCandidateIn] = []
    unit_by_id = {unit.id: unit for unit in units}
    for chunk in chunks:
        extraction = heuristic_extract(chunk)
        for candidate in extraction.nodes:
            evidence = [
                EvidenceRef(
                    unit_id=chunk.id,
                    chunk_id=item.chunk_id,
                    excerpt=item.excerpt,
                    page=item.page,
                    slide=item.slide,
                )
                for item in candidate.evidence
            ]
            nodes.append(
                BranchNodeOutput(
                    temp_id=f"{branch.id}:{candidate.temp_id}",
                    name=candidate.name,
                    type=candidate.type,
                    role=candidate.type,
                    definition=candidate.definition,
                    origin="explicit",
                    confidence=candidate.confidence,
                    evidence=evidence,
                )
            )
        for edge in extraction.edges:
            if edge.predicate not in CROSS_LINK_RELATIONS:
                continue
            cross_links.append(
                CrossLinkCandidateIn(
                    source=edge.source,
                    target=edge.target,
                    relation=edge.predicate,
                    score=edge.confidence,
                    evidence=[
                        EvidenceRef(
                            unit_id=item.chunk_id,
                            chunk_id=item.chunk_id,
                            excerpt=item.excerpt,
                            page=item.page,
                            slide=item.slide,
                        )
                        for item in edge.evidence
                    ],
                )
            )

    for unit in units:
        if unit.kind != "visual" or unit.status == "rejected":
            continue
        if (
            unit.visual_action not in {"standalone_node", "decompose"}
            or unit.knowledge_score < 0.55
            or not unit.asset_id
        ):
            continue
        label = _short_label(
            unit.summary or unit.ocr_text or unit.visual_kind or "视觉知识",
            "视觉知识",
        )
        nodes.append(
            BranchNodeOutput(
                temp_id=f"{branch.id}:{unit.id}",
                name=label,
                type="visual_knowledge",
                role=(
                    "table"
                    if unit.visual_kind == "table"
                    else "visual_knowledge"
                ),
                definition=unit.summary or unit.ocr_text,
                origin="explicit",
                confidence=unit.knowledge_score,
                evidence=[
                    EvidenceRef(
                        unit_id=unit.id,
                        excerpt=unit.evidence_excerpt,
                        page=unit.page,
                        slide=unit.slide,
                        bbox=unit.bbox,
                        asset_id=unit.asset_id,
                    )
                ],
                media_asset_ids=[unit.asset_id],
            )
        )
    return BranchExtractionOutput(nodes=nodes, cross_links=cross_links)


async def _branch_scout(state: BranchTeamState) -> dict:
    branch = state["branch"]
    units = state["units"]
    chunks = state["chunks"]
    runtime = state["runtime"]
    warnings = list(state.get("warnings", []))

    if not branch.leaf:
        return {
            "nodes": [],
            "cross_links": [],
            "used_model": False,
            "warnings": warnings,
        }

    fallback = _heuristic_branch_extract(branch, chunks, units)
    if not runtime.available or not runtime.client:
        warnings.append(
            f"分支“{branch.label}”使用本地抽取："
            f"{runtime.unavailable_reason or '模型不可用'}"
        )
        return {
            "nodes": [
                _to_node_candidate(item, branch)
                for item in fallback.nodes
            ],
            "cross_links": fallback.cross_links,
            "used_model": False,
            "warnings": warnings,
        }

    prompt_units = [
        {
            "unit_id": unit.id,
            "chunk_id": unit.id if unit.kind == "text" else None,
            "kind": unit.kind,
            "heading_path": unit.heading_path,
            "page": unit.page,
            "slide": unit.slide,
            "text": (unit.text or unit.summary or unit.ocr_text)[:2600],
            "asset_id": unit.asset_id,
        }
        for unit in units
    ]
    try:
        payload = await runtime.client.complete_json(
            model=runtime.model,
            system_prompt=BRANCH_EXTRACTOR_PROMPT,
            user_prompt=json.dumps(
                {
                    "branch": branch.model_dump(mode="json"),
                    "content_units": prompt_units,
                },
                ensure_ascii=False,
            ),
            max_tokens=7000,
        )
        extraction = BranchExtractionOutput.model_validate(payload)
        valid_unit_ids = {unit.id for unit in units}
        validated_nodes: list[NodeCandidateIn] = []
        for item in extraction.nodes:
            evidence = [
                evidence
                for evidence in item.evidence
                if (evidence.unit_id or evidence.chunk_id) in valid_unit_ids
            ]
            support_ids = [
                unit_id
                for unit_id in item.support_unit_ids
                if unit_id in valid_unit_ids
            ]
            validated_nodes.append(
                _to_node_candidate(
                    item.model_copy(
                        update={
                            "evidence": evidence,
                            "support_unit_ids": support_ids,
                        }
                    ),
                    branch,
                )
            )
        if not validated_nodes:
            raise ValueError("模型没有返回带有效证据的节点")
        return {
            "nodes": validated_nodes,
            "cross_links": extraction.cross_links,
            "used_model": True,
            "warnings": warnings,
        }
    except (ModelProviderError, ValueError) as exc:
        warnings.append(f"分支“{branch.label}”模型抽取失败，已局部降级：{exc}")
        return {
            "nodes": [
                _to_node_candidate(item, branch)
                for item in fallback.nodes
            ],
            "cross_links": fallback.cross_links,
            "used_model": False,
            "warnings": warnings,
        }


def _candidate_rank(candidate: NodeCandidateIn) -> tuple[float, int, int]:
    support = len(candidate.evidence) + len(candidate.support_unit_ids)
    return (
        candidate.confidence + min(support, 4) * 0.04,
        len(candidate.definition),
        -len(candidate.name),
    )


async def _granularity_critic(state: BranchTeamState) -> dict:
    grouped: dict[str, list[NodeCandidateIn]] = defaultdict(list)
    warnings = list(state.get("warnings", []))
    for candidate in state.get("nodes", []):
        name = candidate.name.strip()
        key = normalized_key(name)
        if (
            not key
            or name in GENERIC_LABELS
            or len(name) < 2
            or len(name) > 48
        ):
            warnings.append(f"候选“{name or candidate.temp_id}”未通过粒度资格门。")
            continue
        if not candidate.evidence and not candidate.support_unit_ids:
            warnings.append(f"候选“{name}”缺少证据，已拒绝。")
            continue
        grouped[key].append(candidate)

    merged: list[NodeCandidateIn] = []
    for candidates in grouped.values():
        primary = max(candidates, key=_candidate_rank)
        aliases = set(primary.aliases)
        evidence: list[EvidenceRef] = []
        support_ids: set[str] = set()
        media_ids: set[str] = set()
        for candidate in candidates:
            if candidate.name != primary.name:
                aliases.add(candidate.name)
            aliases.update(candidate.aliases)
            evidence.extend(candidate.evidence)
            support_ids.update(candidate.support_unit_ids)
            media_ids.update(candidate.media_asset_ids)
        merged.append(
            primary.model_copy(
                update={
                    "aliases": sorted(aliases),
                    "evidence": _dedupe_evidence(evidence),
                    "support_unit_ids": sorted(support_ids),
                    "media_asset_ids": sorted(media_ids),
                }
            )
        )
    return {"nodes": merged, "warnings": warnings}


def _dedupe_evidence(items: list[EvidenceRef]) -> list[EvidenceRef]:
    seen: set[tuple] = set()
    result: list[EvidenceRef] = []
    for item in items:
        signature = (
            item.unit_id,
            item.chunk_id,
            item.excerpt,
            item.page,
            item.slide,
            tuple(item.bbox or []),
            item.asset_id,
        )
        if signature in seen:
            continue
        seen.add(signature)
        result.append(item)
    return result[:16]


async def _abstraction_induction(state: BranchTeamState) -> dict:
    branch = state["branch"]
    nodes = list(state.get("nodes", []))
    if not any(
        normalized_key(node.name) == normalized_key(branch.label)
        for node in nodes
    ):
        nodes.append(
            NodeCandidateIn(
                temp_id=f"topic:{branch.id}",
                name=branch.label,
                type="branch_topic",
                role="branch_topic",
                definition=branch.description,
                origin="abstractive" if branch.depth == 1 else "structural",
                branch_id=branch.id,
                confidence=max(branch.cohesion, 0.58),
                optional=branch.depth > 1,
                activation_score=max(branch.cohesion, 0.58),
                activation_cost=0.1 if branch.depth == 1 else 0.18,
                support_unit_ids=branch.unit_ids,
            )
        )
    return {"nodes": nodes}


async def _local_parent_retriever(state: BranchTeamState) -> dict:
    branch = state["branch"]
    nodes = state.get("nodes", [])
    parent_candidates: list[ParentCandidateIn] = []
    for node in nodes:
        if normalized_key(node.name) == normalized_key(branch.label):
            continue
        parent_candidates.append(
            ParentCandidateIn(
                parent=branch.label,
                child=node.temp_id,
                score=0.76 if node.origin == "explicit" else 0.68,
                classification="direct_parent",
                section_prior=0.88,
                semantic_score=0.62,
                evidence_support=0.9 if node.evidence else 0.65,
                granularity_fit=0.72,
            )
        )
    return {"parent_candidates": parent_candidates}


async def _local_verifier(state: BranchTeamState) -> dict:
    branch = state["branch"]
    nodes = []
    warnings = list(state.get("warnings", []))
    valid_units = set(branch.unit_ids)
    for node in state.get("nodes", []):
        evidence_units = {
            item.unit_id or item.chunk_id
            for item in node.evidence
            if item.unit_id or item.chunk_id
        }
        support_units = set(node.support_unit_ids)
        if node.origin == "explicit" and not (evidence_units & valid_units):
            warnings.append(f"分支“{branch.label}”中的“{node.name}”证据越界，已过滤。")
            continue
        if node.origin in {"abstractive", "structural"}:
            supported = len(support_units & valid_units)
            if supported < 2 and node.optional:
                warnings.append(f"抽象候选“{node.name}”支持不足，已过滤。")
                continue
        nodes.append(node)
    return {"nodes": nodes, "warnings": warnings}


def create_branch_team():
    builder = StateGraph(BranchTeamState)
    builder.add_node("node_scout", _branch_scout)
    builder.add_node("granularity_critic", _granularity_critic)
    builder.add_node("abstraction_induction", _abstraction_induction)
    builder.add_node("parent_retriever", _local_parent_retriever)
    builder.add_node("local_verifier", _local_verifier)
    builder.add_edge(START, "node_scout")
    builder.add_edge("node_scout", "granularity_critic")
    builder.add_edge("granularity_critic", "abstraction_induction")
    builder.add_edge("abstraction_induction", "parent_retriever")
    builder.add_edge("parent_retriever", "local_verifier")
    builder.add_edge("local_verifier", END)
    return builder.compile()


async def run_branch_teams(
    branch_plans: list[BranchPlan],
    units: list[ContentUnit],
    chunks: list[Chunk],
    runtime: RoleRuntime,
    *,
    concurrency: int = 4,
) -> list[BranchTeamResult]:
    unit_by_id = {unit.id: unit for unit in units}
    chunk_by_id = {chunk.id: chunk for chunk in chunks}
    team = create_branch_team()
    semaphore = asyncio.Semaphore(max(concurrency, 1))

    async def run_one(branch: BranchPlan) -> BranchTeamResult:
        async with semaphore:
            branch_units = [
                unit_by_id[unit_id]
                for unit_id in branch.unit_ids
                if unit_id in unit_by_id
            ]
            branch_chunks = [
                chunk_by_id[unit_id]
                for unit_id in branch.unit_ids
                if unit_id in chunk_by_id
            ]
            state = await team.ainvoke(
                {
                    "branch": branch,
                    "units": branch_units,
                    "chunks": branch_chunks,
                    "runtime": runtime,
                    "warnings": [],
                    "nodes": [],
                    "parent_candidates": [],
                    "cross_links": [],
                    "used_model": False,
                }
            )
            return BranchTeamResult(
                branch=branch,
                nodes=state.get("nodes", []),
                parent_candidates=state.get("parent_candidates", []),
                cross_links=state.get("cross_links", []),
                warnings=state.get("warnings", []),
                used_model=state.get("used_model", False),
            )

    return await asyncio.gather(*(run_one(branch) for branch in branch_plans))


def canonicalize_semantic_duplicates(
    candidates: list[NodeCandidateIn],
) -> list[NodeCandidateIn]:
    ordered = sorted(candidates, key=_candidate_rank, reverse=True)
    canonical: list[NodeCandidateIn] = []
    for candidate in ordered:
        if candidate.is_root_candidate or candidate.role == "branch_topic":
            canonical.append(candidate)
            continue
        match_index: int | None = None
        for index, existing in enumerate(canonical):
            if existing.is_root_candidate or existing.role == "branch_topic":
                continue
            if candidate.branch_id != existing.branch_id:
                continue
            ratio = SequenceMatcher(
                None,
                normalized_key(candidate.name),
                normalized_key(existing.name),
            ).ratio()
            if ratio >= 0.94:
                match_index = index
                break
        if match_index is None:
            canonical.append(candidate)
            continue
        existing = canonical[match_index]
        canonical[match_index] = existing.model_copy(
            update={
                "aliases": sorted(
                    {
                        *existing.aliases,
                        *candidate.aliases,
                        candidate.name,
                    }
                ),
                "evidence": _dedupe_evidence(
                    [*existing.evidence, *candidate.evidence]
                ),
                "support_unit_ids": sorted(
                    {
                        *existing.support_unit_ids,
                        *candidate.support_unit_ids,
                    }
                ),
                "media_asset_ids": sorted(
                    {
                        *existing.media_asset_ids,
                        *candidate.media_asset_ids,
                    }
                ),
                "confidence": max(existing.confidence, candidate.confidence),
            }
        )
    return canonical


def fuse_visual_media(
    candidates: list[NodeCandidateIn],
    units: list[ContentUnit],
) -> list[NodeCandidateIn]:
    fused = list(candidates)
    for unit in units:
        if (
            unit.kind != "visual"
            or unit.visual_action != "attach_as_media"
            or not unit.asset_id
        ):
            continue
        nearby_ids = set(unit.nearby_text_ids)
        ranked: list[tuple[int, float, int]] = []
        for index, candidate in enumerate(fused):
            evidence_ids = {
                item.unit_id or item.chunk_id
                for item in candidate.evidence
                if item.unit_id or item.chunk_id
            }
            overlap = len(nearby_ids & evidence_ids)
            if overlap:
                ranked.append((overlap, candidate.confidence, index))
        if not ranked:
            continue
        _, _, index = max(ranked)
        candidate = fused[index]
        fused[index] = candidate.model_copy(
            update={
                "media_asset_ids": sorted(
                    {*candidate.media_asset_ids, unit.asset_id}
                ),
                "evidence": _dedupe_evidence(
                    [
                        *candidate.evidence,
                        EvidenceRef(
                            unit_id=unit.id,
                            excerpt=unit.evidence_excerpt,
                            page=unit.page,
                            slide=unit.slide,
                            bbox=unit.bbox,
                            asset_id=unit.asset_id,
                        ),
                    ]
                ),
            }
        )
    return fused


def build_global_parent_candidates(
    theme_plan: ThemePlanOutput,
    branch_plans: list[BranchPlan],
    nodes: list[NodeCandidateIn],
    local_candidates: list[ParentCandidateIn],
) -> list[ParentCandidateIn]:
    result = list(local_candidates)
    roots = [item for item in nodes if item.is_root_candidate]
    plan_by_id = {plan.id: plan for plan in branch_plans}
    topic_by_branch = {
        item.branch_id: item
        for item in nodes
        if item.role == "branch_topic" and item.branch_id
    }

    for plan in branch_plans:
        topic = topic_by_branch.get(plan.id)
        if not topic:
            continue
        if plan.parent_branch_id:
            parent_topic = topic_by_branch.get(plan.parent_branch_id)
            if parent_topic:
                result.append(
                    ParentCandidateIn(
                        parent=parent_topic.temp_id,
                        child=topic.temp_id,
                        score=0.92,
                        classification="direct_parent",
                        section_prior=0.95,
                        semantic_score=0.8,
                        verifier_score=0.82,
                        evidence_support=0.88,
                        granularity_fit=0.9,
                    )
                )
        else:
            for root in roots:
                result.append(
                    ParentCandidateIn(
                        parent=root.temp_id,
                        child=topic.temp_id,
                        score=0.95,
                        classification="direct_parent",
                        section_prior=0.96,
                        semantic_score=0.86,
                        verifier_score=0.86,
                        evidence_support=0.9,
                        granularity_fit=0.94,
                    )
                )

    for node in nodes:
        if node.is_root_candidate or node.role == "branch_topic":
            continue
        branch_id = node.branch_id
        topic = topic_by_branch.get(branch_id)
        if not topic and branch_id:
            plan = plan_by_id.get(branch_id)
            while plan and plan.parent_branch_id and not topic:
                topic = topic_by_branch.get(plan.parent_branch_id)
                plan = plan_by_id.get(plan.parent_branch_id)
        if topic:
            result.append(
                ParentCandidateIn(
                    parent=topic.temp_id,
                    child=node.temp_id,
                    score=0.82 if node.origin == "explicit" else 0.76,
                    classification="direct_parent",
                    section_prior=0.92,
                    semantic_score=0.66,
                    verifier_score=0.72,
                    evidence_support=0.9 if node.evidence else 0.72,
                    granularity_fit=0.78,
                )
            )
    return _dedupe_parent_inputs(result)


def _dedupe_parent_inputs(
    candidates: list[ParentCandidateIn],
) -> list[ParentCandidateIn]:
    best: dict[tuple[str, str], ParentCandidateIn] = {}
    for candidate in candidates:
        key = (candidate.parent, candidate.child)
        previous = best.get(key)
        if not previous or candidate.score > previous.score:
            best[key] = candidate
    return list(best.values())


def audit_coverage(
    units: list[ContentUnit],
    candidates: list[NodeCandidateIn],
    branch_plans: list[BranchPlan],
) -> tuple[list[ContentUnit], list[NodeCandidateIn], list[str]]:
    covered: set[str] = set()
    for candidate in candidates:
        covered.update(candidate.support_unit_ids)
        covered.update(
            item.unit_id or item.chunk_id
            for item in candidate.evidence
            if item.unit_id or item.chunk_id
        )

    plan_by_unit: dict[str, BranchPlan] = {}
    for plan in branch_plans:
        if not plan.leaf:
            continue
        for unit_id in plan.unit_ids:
            plan_by_unit[unit_id] = plan

    updated_units: list[ContentUnit] = []
    additions: list[NodeCandidateIn] = []
    warnings: list[str] = []
    for unit in units:
        if unit.status == "rejected":
            updated_units.append(unit)
            continue
        if unit.id in covered:
            updated_units.append(unit.model_copy(update={"status": "covered"}))
            continue
        if unit.kind == "visual" and unit.knowledge_score < 0.55:
            updated_units.append(unit.model_copy(update={"status": "deferred"}))
            continue
        plan = plan_by_unit.get(unit.id)
        if not plan:
            updated_units.append(unit.model_copy(update={"status": "deferred"}))
            continue

        label = _short_label(
            unit.text or unit.summary or unit.ocr_text,
            plan.label,
        )
        if label in GENERIC_LABELS or normalized_key(label) == normalized_key(plan.label):
            label = f"{plan.label}要点"
        evidence = EvidenceRef(
            unit_id=unit.id,
            chunk_id=unit.id if unit.kind == "text" else None,
            excerpt=unit.evidence_excerpt or unit.text[:220],
            page=unit.page,
            slide=unit.slide,
            bbox=unit.bbox,
            asset_id=unit.asset_id,
        )
        additions.append(
            NodeCandidateIn(
                temp_id=stable_id("coverage", unit.id),
                name=label,
                type="visual_knowledge" if unit.kind == "visual" else "concept",
                role="visual_knowledge" if unit.kind == "visual" else "concept",
                definition=(unit.summary or unit.text[:180]),
                origin="explicit",
                branch_id=plan.id,
                confidence=max(0.52, unit.importance),
                optional=False,
                activation_score=max(0.52, unit.importance),
                evidence=[evidence],
                media_asset_ids=[unit.asset_id] if unit.asset_id else [],
            )
        )
        updated_units.append(unit.model_copy(update={"status": "covered"}))
        warnings.append(f"覆盖审计为未覆盖内容单元 {unit.id} 补建了显式候选。")
    return updated_units, additions, warnings


def _heuristic_parent_vote(
    parent: NormalizedNode,
    child: NormalizedNode,
    candidate: NormalizedParentCandidate,
) -> ModelVote:
    classification = candidate.classification
    score = candidate.score
    reason = "沿用候选召回结果。"
    if parent.is_root_candidate and child.role == "branch_topic":
        classification, score = "direct_parent", max(score, 0.94)
        reason = "根节点直接组织一级主题。"
    elif parent.is_root_candidate:
        classification, score = "ancestor_only", min(max(score, 0.4), 0.62)
        reason = "根节点更适合作为祖先，优先经过一级主题。"
    elif parent.role == "branch_topic" and parent.branch_id == child.branch_id:
        classification, score = "direct_parent", max(score, 0.82)
        reason = "节点与分支主题一致，粒度适合作为直接父子。"
    elif (
        parent.branch_id
        and child.branch_id
        and parent.branch_id != child.branch_id
    ):
        classification, score = "unrelated", min(score, 0.28)
        reason = "候选跨越不同分支，缺少直接层级证据。"
    elif parent.role in {"example", "warning", "formula", "step"}:
        classification, score = "sibling", min(score, 0.3)
        reason = "父节点语义角色不适合作为上位主题。"
    elif normalized_key(parent.name) in normalized_key(
        f"{child.name}{child.definition}"
    ):
        classification, score = "direct_parent", max(score, 0.72)
        reason = "子节点名称或定义显式包含父主题。"
    elif candidate.provisional:
        classification, score = "uncertain", candidate.score
        reason = "仅有保底连接，缺少可靠直接父证据。"
    return ModelVote(
        actor="deterministic-verifier",
        model=None,
        classification=classification,
        score=round(max(0, min(score, 1)), 4),
        reason=reason,
    )


async def _model_parent_vote(
    runtime: RoleRuntime,
    parent: NormalizedNode,
    child: NormalizedNode,
    candidate: NormalizedParentCandidate,
    competitors: list[NormalizedParentCandidate],
) -> ModelVote:
    if not runtime.available or not runtime.client:
        return _heuristic_parent_vote(parent, child, candidate)
    prompt = json.dumps(
        {
            "parent": parent.model_dump(mode="json"),
            "child": child.model_dump(mode="json"),
            "candidate": candidate.model_dump(mode="json"),
            "competitors": [
                item.model_dump(mode="json")
                for item in competitors[:4]
            ],
        },
        ensure_ascii=False,
    )
    try:
        payload = await runtime.client.complete_json(
            model=runtime.model,
            system_prompt=PARENT_VERIFIER_PROMPT,
            user_prompt=prompt,
            max_tokens=1200,
        )
        vote = ParentVerificationOutput.model_validate(payload)
        return ModelVote(
            actor=runtime.provider,
            model=runtime.model,
            classification=vote.classification,
            score=vote.verifier_score,
            reason=vote.reason,
        )
    except (ModelProviderError, ValueError):
        return _heuristic_parent_vote(parent, child, candidate)


async def _arbiter_vote(
    runtime: RoleRuntime,
    parent: NormalizedNode,
    child: NormalizedNode,
    candidate: NormalizedParentCandidate,
    votes: list[ModelVote],
) -> ModelVote:
    if not runtime.available or not runtime.client:
        ranked = sorted(votes, key=lambda item: item.score, reverse=True)
        return ModelVote(
            actor="deterministic-arbiter",
            classification=ranked[0].classification,
            score=ranked[0].score,
            reason="仲裁模型不可用，采用证据分更高的独立票。",
        )
    try:
        payload = await runtime.client.complete_json(
            model=runtime.model,
            system_prompt=ARBITER_PROMPT,
            user_prompt=json.dumps(
                {
                    "parent": parent.model_dump(mode="json"),
                    "child": child.model_dump(mode="json"),
                    "candidate": candidate.model_dump(mode="json"),
                    "votes": [
                        vote.model_dump(mode="json")
                        for vote in votes
                    ],
                },
                ensure_ascii=False,
            ),
            max_tokens=1200,
        )
        output = ParentVerificationOutput.model_validate(payload)
        return ModelVote(
            actor=f"{runtime.provider}-arbiter",
            model=runtime.model,
            classification=output.classification,
            score=output.verifier_score,
            reason=output.reason,
        )
    except (ModelProviderError, ValueError):
        return await _arbiter_vote(
            RoleRuntime("deterministic", "", None, False),
            parent,
            child,
            candidate,
            votes,
        )


async def verify_parent_candidates(
    graph: NormalizedGraph,
    *,
    verifier: RoleRuntime,
    second_verifier: RoleRuntime | None,
    arbiter: RoleRuntime | None,
    mode: RunMode,
    concurrency: int = 8,
) -> tuple[
    NormalizedGraph,
    dict[tuple[str, str], list[ModelVote]],
    list[str],
]:
    node_by_id = {node.id: node for node in graph.nodes}
    by_child: dict[str, list[NormalizedParentCandidate]] = defaultdict(list)
    for candidate in graph.parent_candidates:
        by_child[candidate.child_id].append(candidate)
    model_verified_pairs: set[tuple[str, str]] = set()
    second_verified_pairs: set[tuple[str, str]] = set()
    for child_id, child_candidates in by_child.items():
        ranked = sorted(
            (item for item in child_candidates if not item.provisional),
            key=lambda item: item.score,
            reverse=True,
        )
        model_verified_pairs.update(
            (item.parent_id, child_id)
            for item in ranked[:3]
        )
        second_verified_pairs.update(
            (item.parent_id, child_id)
            for item in ranked[:2]
        )
    semaphore = asyncio.Semaphore(max(concurrency, 1))
    warnings: list[str] = []
    votes_by_pair: dict[tuple[str, str], list[ModelVote]] = {}

    async def verify_one(
        candidate: NormalizedParentCandidate,
    ) -> NormalizedParentCandidate:
        parent = node_by_id[candidate.parent_id]
        child = node_by_id[candidate.child_id]
        competitors = sorted(
            by_child[candidate.child_id],
            key=lambda item: item.score,
            reverse=True,
        )
        pair = (candidate.parent_id, candidate.child_id)
        async with semaphore:
            if pair in model_verified_pairs:
                first = await _model_parent_vote(
                    verifier,
                    parent,
                    child,
                    candidate,
                    competitors,
                )
            else:
                first = _heuristic_parent_vote(parent, child, candidate)
            votes = [first]
            high_risk = (
                mode == "precision"
                and pair in second_verified_pairs
                and (
                    child.origin in {"abstractive", "structural"}
                    or parent.is_root_candidate
                    or len(competitors) > 1
                )
            )
            if high_risk and second_verifier:
                second = await _model_parent_vote(
                    second_verifier,
                    parent,
                    child,
                    candidate,
                    competitors,
                )
                votes.append(second)
                if (
                    second.classification != first.classification
                    and arbiter is not None
                ):
                    votes.append(
                        await _arbiter_vote(
                            arbiter,
                            parent,
                            child,
                            candidate,
                            votes,
                        )
                    )

        final_vote = votes[-1]
        votes_by_pair[(candidate.parent_id, candidate.child_id)] = votes
        direct = final_vote.classification == "direct_parent"
        combined = (
            0.45 * candidate.score
            + 0.55 * final_vote.score
            if direct
            else 0.35 * candidate.score
            + 0.25 * final_vote.score
        )
        if final_vote.classification == "ancestor_only":
            combined *= 0.55
        elif final_vote.classification in {"sibling", "cross_link"}:
            combined *= 0.3
        elif final_vote.classification == "unrelated":
            combined *= 0.1
        elif final_vote.classification == "uncertain":
            combined *= 0.45
        return candidate.model_copy(
            update={
                "score": round(max(0, min(combined, 1)), 4),
                "classification": final_vote.classification,
            }
        )

    verified = await asyncio.gather(
        *(verify_one(candidate) for candidate in graph.parent_candidates)
    )
    if not verifier.available:
        warnings.append("独立父边校验模型不可用，已使用确定性校验器。")
    if mode == "precision" and (
        second_verifier is None or not second_verifier.available
    ):
        warnings.append("高精档第二校验器不可用，相关风险项将保留人工复核。")
    return (
        graph.model_copy(update={"parent_candidates": verified}),
        votes_by_pair,
        warnings,
    )


def coverage_statistics(
    units: list[ContentUnit],
    nodes: list[NormalizedNode],
) -> tuple[set[str], float, dict[str, float]]:
    covered: set[str] = set()
    for node in nodes:
        covered.update(node.support_unit_ids)
        covered.update(
            item.unit_id or item.chunk_id
            for item in node.evidence
            if item.unit_id or item.chunk_id
        )
    eligible = [
        unit
        for unit in units
        if unit.status != "rejected" and unit.importance > 0.15
    ]
    total_weight = sum(unit.importance for unit in eligible)
    covered_weight = sum(
        unit.importance for unit in eligible if unit.id in covered
    )
    weighted = covered_weight / total_weight if total_weight else 1
    branch_totals: Counter[str] = Counter()
    branch_covered: Counter[str] = Counter()
    for unit in eligible:
        branch = unit.branch_hint or "未分配"
        branch_totals[branch] += 1
        if unit.id in covered:
            branch_covered[branch] += 1
    branch_coverage = {
        branch: round(branch_covered[branch] / total, 4)
        for branch, total in branch_totals.items()
    }
    return covered, round(weighted, 4), branch_coverage
