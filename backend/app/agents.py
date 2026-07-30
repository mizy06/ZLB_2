from __future__ import annotations

import asyncio
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

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
from .claim_fidelity import claim_fidelity_issues
from .model_provider import (
    ModelProviderError,
    OpenAICompatibleClient,
    model_call_scope,
)
from .heuristics import heuristic_extract
from .mindmap_engine.normalize import (
    candidate_field_disposition,
    definition_quality_issues,
    is_publishable_label,
    normalized_key,
)
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
from .semantic_dedupe import are_mergeable_exact_duplicates
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
MAX_ROOT_BRANCHES = 8
MAX_LEAF_BRANCHES = 24
MAX_BRANCH_NODE_BUDGET = 24
THEME_SAMPLE_LIMIT = 32
THEME_MIN_TEXT_SAMPLES = 24
THEME_MAX_VISUAL_SAMPLES = 8
THEME_SUMMARY_MAX_CHARS = 280
THEME_MAX_OUTPUT_TOKENS = 5000
BRANCH_MAX_OUTPUT_TOKENS = 7000
QWEN_LOW_REASONING_TOKEN_RESERVE = 4096
THEME_THINKING_TOKEN_BUDGET = 1024
STRUCTURED_JSON_TIMEOUT_SECONDS = 90.0
THEME_JSON_TIMEOUT_SECONDS = 120.0
VERIFIER_JSON_TIMEOUT_SECONDS = 60.0
VERIFIER_CHILD_BATCH_SIZE = 4
VERIFIER_DIRECT_EDGE_MIN_SCORE = 0.78
VERIFIER_COMPETITIVE_MARGIN = 0.15
_MATERIAL_IDENTITY_LABEL = re.compile(
    r"(?:"
    r"[=≈≃≠<>≤≥→⇒]"
    r"|[-+]?\d+(?:\.\d+)?(?:[eE^][-+]?\d+)?%?"
    r"|导致|引起|造成|使得|促进|抑制|正比|反比"
    r")"
)


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


def _structured_json_call_kwargs(
    runtime: RoleRuntime,
    answer_token_budget: int,
    *,
    timeout_seconds: float = STRUCTURED_JSON_TIMEOUT_SECONDS,
    reasoning_token_reserve: int = QWEN_LOW_REASONING_TOKEN_RESERVE,
    thinking_token_budget: int | None = None,
) -> dict[str, object]:
    options: dict[str, object] = {
        "max_tokens": answer_token_budget,
        "max_attempts": 1,
        "timeout_seconds": timeout_seconds,
    }
    if (
        runtime.provider.casefold() == "qwen"
        or runtime.model.casefold().startswith("qwen3.8")
    ):
        reasoning_reserve = (
            thinking_token_budget
            if thinking_token_budget is not None
            else reasoning_token_reserve
        )
        options.update(
            {
                "max_completion_tokens": (
                    answer_token_budget
                    + reasoning_reserve
                ),
                "thinking_budget": reasoning_reserve,
            }
        )
    return options


class VerifierRoleRunStats(BaseModel):
    """Track physical HTTP batches separately from per-child outcomes.

    A mixed physical batch counts as both succeeded and fallback because
    valid children keep their model votes while invalid children degrade
    independently.
    """

    requested_batches: int = Field(default=0, ge=0)
    attempted_batches: int = Field(default=0, ge=0)
    succeeded_batches: int = Field(default=0, ge=0)
    fallback_batches: int = Field(default=0, ge=0)
    requested_children: int = Field(default=0, ge=0)
    succeeded_children: int = Field(default=0, ge=0)
    fallback_children: int = Field(default=0, ge=0)


class ParentVerificationRunStats(BaseModel):
    primary: VerifierRoleRunStats = Field(
        default_factory=VerifierRoleRunStats
    )
    secondary: VerifierRoleRunStats = Field(
        default_factory=VerifierRoleRunStats
    )
    arbiter: VerifierRoleRunStats = Field(
        default_factory=VerifierRoleRunStats
    )


@dataclass(frozen=True)
class ParentVerificationResult:
    graph: NormalizedGraph
    votes: dict[tuple[str, str], list[ModelVote]]
    warnings: list[str]
    stats: ParentVerificationRunStats

    def __iter__(self):
        """Keep existing graph/votes/warnings unpacking source-compatible."""

        yield self.graph
        yield self.votes
        yield self.warnings


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
    optional: bool = True
    activation_score: float | None = Field(default=None, ge=0, le=1)
    activation_cost: float = Field(default=0, ge=0, le=1)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    support_unit_ids: list[str] = Field(default_factory=list)
    media_asset_ids: list[str] = Field(default_factory=list)


class BranchExtractionOutput(BaseModel):
    nodes: list[BranchNodeOutput] = Field(default_factory=list)
    cross_links: list[CrossLinkCandidateIn] = Field(default_factory=list)


def _validate_branch_extraction_payload(
    payload: Any,
) -> tuple[BranchExtractionOutput, list[str]]:
    if not isinstance(payload, dict):
        raise ValueError("branch payload 顶层必须是对象（JSON 对象）")
    raw_nodes = payload.get("nodes", [])
    if not isinstance(raw_nodes, list):
        raise ValueError("branch nodes 必须是数组")
    nodes: list[BranchNodeOutput] = []
    warnings: list[str] = []
    for index, raw_node in enumerate(raw_nodes):
        try:
            nodes.append(BranchNodeOutput.model_validate(raw_node))
        except ValueError:
            warnings.append(f"nodes[{index}] schema 无效，已丢弃")

    raw_cross_links = payload.get("cross_links", [])
    cross_links: list[CrossLinkCandidateIn] = []
    if not isinstance(raw_cross_links, list):
        warnings.append("cross_links schema 无效，已整体丢弃")
    else:
        for index, raw_cross_link in enumerate(raw_cross_links):
            try:
                cross_links.append(
                    CrossLinkCandidateIn.model_validate(raw_cross_link)
                )
            except ValueError:
                warnings.append(
                    f"cross_links[{index}] schema 无效，已丢弃"
                )
    return (
        BranchExtractionOutput(nodes=nodes, cross_links=cross_links),
        warnings,
    )


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


class ParentBatchEvaluation(BaseModel):
    parent_id: str
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


class ParentVerificationBatchOutput(BaseModel):
    children: list[Any]


class ParentVerificationChildOutput(BaseModel):
    child_id: str
    evaluations: list[ParentBatchEvaluation] = Field(default_factory=list)


@dataclass(frozen=True)
class _ParentVerificationRequest:
    child: NormalizedNode
    candidates: tuple[NormalizedParentCandidate, ...]


@dataclass(frozen=True)
class _ParentVoteBatchResult:
    votes: dict[str, dict[str, ModelVote]]
    errors: dict[str, str]
    warnings: list[str]
    stats: VerifierRoleRunStats


class BranchTeamState(TypedDict, total=False):
    branch: BranchPlan
    units: list[ContentUnit]
    chunks: list[Chunk]
    runtime: RoleRuntime
    seed_nodes: list[NodeCandidateIn]
    seed_source_unit_ids: list[str]
    seeded_unit_ids: list[str]
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


_PAGE_NUMBER_ONLY = re.compile(
    r"^(?:第\s*)?\d{1,4}(?:\s*页)?$",
    re.IGNORECASE,
)
_QUIZ_MARKER = re.compile(
    r"(?:单选题|多选题|判断题|选择题|提交|查看答案)"
)
_MEANINGFUL_TEXT_WORD = re.compile(
    r"[\u3400-\u9fff]{2,}|[A-Za-z]{3,}|[Α-ω]{2,}"
)
_PRIVATE_USE_OR_REPLACEMENT_GLYPH = re.compile(r"[\ue000-\uf8ff\ufffd]")


def _text_without_page_markers(text: str) -> str:
    lines = [
        line.strip()
        for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
        if line.strip() and not _PAGE_NUMBER_ONLY.fullmatch(line.strip())
    ]
    return "\n".join(lines).strip()


def _is_meaningful_short_formula(text: str) -> bool:
    compact = re.sub(r"\s+", "", _text_without_page_markers(text))
    relation = re.search(r"[=≈≃≅≤≥<>]", compact)
    if relation:
        left = compact[: relation.start()]
        right = compact[relation.end() :]
        return bool(
            re.search(r"[\w\u3400-\u9fffΑ-ω]", left)
            and re.search(r"[\w\u3400-\u9fffΑ-ω]", right)
        )
    return bool(
        re.search(r"[∫∑Σ√]", compact)
        and len(re.findall(r"[\w\u3400-\u9fffΑ-ω]", compact)) >= 3
    )


def _is_private_use_glyph_noise(text: str) -> bool:
    compact = re.sub(r"\s+", "", _text_without_page_markers(text))
    if not compact:
        return False
    private_use_count = len(_PRIVATE_USE_OR_REPLACEMENT_GLYPH.findall(compact))
    return (
        private_use_count >= 4
        and private_use_count / len(compact) >= 0.15
    )


def _is_incomplete_quiz_ui(text: str) -> bool:
    if not _QUIZ_MARKER.search(text):
        return False
    lines = [
        line.strip()
        for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
        if line.strip()
    ]
    bare_options = sum(
        bool(re.fullmatch(r"[A-HＡ-Ｈ][、.)）:]?", line, re.IGNORECASE))
        for line in lines
    )
    if bare_options < 2:
        bare_options = len(
            re.findall(
                r"(?:^|\s)[A-HＡ-Ｈ](?=\s|$)",
                text,
                re.IGNORECASE,
            )
        )
    option_payloads = sum(
        bool(
            re.match(
                r"^[A-HＡ-Ｈ](?:[、.)）:]\s*|\s+)\S+",
                line,
                re.IGNORECASE,
            )
        )
        for line in lines
    )
    return bare_options >= 2 and option_payloads == 0


def _is_axis_or_symbol_text_fragment(text: str) -> bool:
    body = _text_without_page_markers(text)
    if not body or _MEANINGFUL_TEXT_WORD.search(body):
        return False
    if _is_meaningful_short_formula(body):
        return False
    tokens = [
        token.casefold()
        for token in re.findall(
            r"[A-Za-z]+|[Α-ω]+|[\u3400-\u9fff]+",
            body,
        )
    ]
    axis_tokens = {
        "x",
        "y",
        "z",
        "r",
        "t",
        "o",
        "θ",
        "φ",
        "ϕ",
        "ρ",
        "ψ",
    }
    if (
        len(tokens) >= 2
        and all(token in axis_tokens for token in tokens)
        and (
            len(tokens) <= 3
            or len(set(tokens)) <= max(2, len(tokens) // 2)
        )
    ):
        return True
    return not tokens and bool(re.search(r"[^\w\s]", body))


def _text_unit_disposition(text: str) -> tuple[str, float | None]:
    """Classify only unmistakable extraction debris; retain terse knowledge."""

    body = _text_without_page_markers(text)
    compact = re.sub(r"\s+", "", body)
    if not compact:
        return "rejected", 0.02
    if _is_private_use_glyph_noise(body):
        return "deferred", 0.1
    if _is_meaningful_short_formula(body):
        return "uncovered", None
    if not re.search(r"[\w\u3400-\u9fffΑ-ω]", compact, re.UNICODE):
        return "rejected", 0.04
    if _is_incomplete_quiz_ui(body):
        return "deferred", 0.12
    if _is_axis_or_symbol_text_fragment(body):
        return "deferred", 0.1
    return "uncovered", None


def build_content_units(
    document: ParsedDocument,
    chunks: list[Chunk],
    assets: list[VisualAsset],
) -> list[ContentUnit]:
    units: list[ContentUnit] = []
    for chunk in chunks:
        heading_path = [chunk.heading] if chunk.heading else []
        status, importance_ceiling = _text_unit_disposition(chunk.text)
        importance = _importance(chunk)
        if importance_ceiling is not None:
            importance = min(importance, importance_ceiling)
        units.append(
            ContentUnit(
                id=chunk.id,
                document_id=document.document_id,
                kind="text",
                branch_hint=chunk.heading,
                importance=importance,
                status=status,
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
    first = re.sub(r"^\[(?:上文衔接|continued|continuation)\]\s*", "", first)
    first = re.split(r"[。！？；;:：]", first)[0].strip()
    first = re.sub(r"^\d+(?:\.\d+)*[\s、.)）-]*", "", first)
    if is_publishable_label(first) and len(first) <= 32:
        return first
    fallback = fallback.strip()
    if is_publishable_label(fallback):
        return fallback
    return "待复核课程要点"


def _is_planning_unit(unit: ContentUnit) -> bool:
    return unit.status in {"uncovered", "covered"}


def _spread_indices(length: int) -> list[int]:
    """Order positions by source coverage: start, end, then widest gaps."""

    if length <= 0:
        return []
    selected: list[int] = []
    remaining = set(range(length))
    while remaining:
        if not selected:
            choice = 0
        elif len(selected) == 1 and length > 1:
            choice = length - 1
        else:
            choice = max(
                remaining,
                key=lambda index: (
                    min(abs(index - item) for item in selected),
                    -index,
                ),
            )
        selected.append(choice)
        remaining.remove(choice)
    return selected


def _unit_source_position(
    original_index: int,
    unit: ContentUnit,
) -> tuple[int, int, int]:
    if unit.page is not None:
        return 0, unit.page, original_index
    if unit.slide is not None:
        return 1, unit.slide, original_index
    return 2, original_index, original_index


def _stratified_unit_sample(
    units: list[ContentUnit],
    limit: int,
) -> list[ContentUnit]:
    """Round-robin chapters while spreading selections across source order."""

    if limit <= 0 or not units:
        return []
    indexed_units = list(enumerate(units))
    grouped: dict[str, list[tuple[int, ContentUnit]]] = defaultdict(list)
    for original_index, unit in indexed_units:
        chapter = (
            unit.heading_path[0].strip()
            if unit.heading_path and unit.heading_path[0].strip()
            else (unit.branch_hint or "").strip()
            or "__ungrouped__"
        )
        grouped[chapter].append((original_index, unit))

    ordered_groups = sorted(
        grouped.values(),
        key=lambda group: min(
            _unit_source_position(index, unit)
            for index, unit in group
        ),
    )
    queues: list[list[ContentUnit]] = []
    for group in ordered_groups:
        ordered = sorted(
            group,
            key=lambda item: (
                _unit_source_position(item[0], item[1]),
                -item[1].importance,
                item[1].id,
            ),
        )
        spread = _spread_indices(len(ordered))
        queues.append([ordered[index][1] for index in spread])

    group_order = _spread_indices(len(queues))
    cursors = [0] * len(queues)
    sampled: list[ContentUnit] = []
    while len(sampled) < min(limit, len(units)):
        progressed = False
        for group_index in group_order:
            cursor = cursors[group_index]
            if cursor >= len(queues[group_index]):
                continue
            sampled.append(queues[group_index][cursor])
            cursors[group_index] += 1
            progressed = True
            if len(sampled) >= limit:
                break
        if not progressed:
            break
    return sampled


def _theme_sample_units(units: list[ContentUnit]) -> list[ContentUnit]:
    active_units = [unit for unit in units if _is_planning_unit(unit)]
    text_units = [unit for unit in active_units if unit.kind == "text"]
    visual_units = [unit for unit in active_units if unit.kind == "visual"]

    visual_target = min(
        len(visual_units),
        THEME_MAX_VISUAL_SAMPLES,
    )
    text_target = min(
        len(text_units),
        max(
            THEME_MIN_TEXT_SAMPLES,
            THEME_SAMPLE_LIMIT - visual_target,
        ),
        THEME_SAMPLE_LIMIT,
    )
    visual_target = min(
        visual_target,
        THEME_SAMPLE_LIMIT - text_target,
    )
    return [
        *_stratified_unit_sample(text_units, text_target),
        *_stratified_unit_sample(visual_units, visual_target),
    ]


def _theme_output_token_budget(sample_count: int) -> int:
    expected_branches = min(
        MAX_ROOT_BRANCHES,
        max(1, (max(sample_count, 1) + 3) // 4),
    )
    estimated = 640 + expected_branches * 320 + sample_count * 24
    return min(THEME_MAX_OUTPUT_TOKENS, max(1024, estimated))


def _branch_output_token_budget(coverage_budget: int) -> int:
    estimated = 1000 + max(coverage_budget, 1) * 250
    return min(BRANCH_MAX_OUTPUT_TOKENS, max(1200, estimated))


_EVIDENCE_CHARACTER_TRANSLATION = str.maketrans(
    {
        "。": ".",
        "｡": ".",
        "、": ",",
        "﹑": ",",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "「": '"',
        "」": '"',
        "『": '"',
        "』": '"',
        "【": "[",
        "】": "]",
        "〔": "[",
        "〕": "]",
        "〖": "[",
        "〗": "]",
        "−": "-",
        "﹣": "-",
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "―": "-",
        "×": "*",
        "✕": "*",
        "⨉": "*",
        "⋅": "*",
        "∙": "*",
        "∗": "*",
        "·": "*",
    }
)
_OCR_HYPHENATED_LINE_BREAK = re.compile(
    r"(?<=[A-Za-z]{2})-[ \t]*(?:\r\n|\r|\n|\u2028|\u2029)"
    r"[ \t]*(?=[A-Za-z]{2})"
)
_GENERIC_EVIDENCE_EXCERPTS = {
    "主要内容",
    "基本内容",
    "相关内容",
    "重要内容",
    "基本概念",
    "核心概念",
    "主要概念",
    "基本原理",
    "主要原理",
    "实验结果",
    "重要结论",
    "相关知识点",
    "本章内容",
    "如图所示",
    "具体如下",
    "定义如下",
}
_EVIDENCE_RELATION_OPERATOR = re.compile(
    r"(?:<=|>=|==|!=|=|<|>|≤|≥|≈|→|⇒|∝)"
)


def _normalized_evidence_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.translate(_EVIDENCE_CHARACTER_TRANSLATION)
    normalized = _OCR_HYPHENATED_LINE_BREAK.sub("", normalized)
    normalized = normalized.replace("\u00ad", "")
    return "".join(
        character
        for character in normalized.casefold()
        if not character.isspace()
        and unicodedata.category(character) != "Cf"
    )


def _evidence_excerpt_is_specific(
    normalized_excerpt: str,
) -> bool:
    semantic_characters = [
        character
        for character in normalized_excerpt
        if character.isalnum()
    ]
    semantic_text = "".join(semantic_characters)
    if semantic_text in _GENERIC_EVIDENCE_EXCERPTS:
        return False
    cjk_count = sum(
        "\u3400" <= character <= "\u9fff"
        for character in semantic_characters
    )
    if cjk_count >= 3:
        return True
    if len(semantic_characters) >= 6:
        return True
    for relation in _EVIDENCE_RELATION_OPERATOR.finditer(
        normalized_excerpt
    ):
        if any(
            character.isalnum()
            for character in normalized_excerpt[: relation.start()]
        ) and any(
            character.isalnum()
            for character in normalized_excerpt[relation.end() :]
        ):
            return True
    math_operators = set("=<>≤≥≈+-*/∫∑√")
    return (
        len(semantic_characters) >= 3
        and any(
            character in math_operators
            for character in normalized_excerpt
        )
    )


def _evidence_ref_binds_unit(
    evidence_ref: EvidenceRef,
    unit: ContentUnit,
) -> bool:
    declared_unit_id = evidence_ref.unit_id or evidence_ref.chunk_id
    if declared_unit_id and declared_unit_id != unit.id:
        return False
    if (
        evidence_ref.asset_id
        and evidence_ref.asset_id != unit.asset_id
    ):
        return False
    return bool(
        declared_unit_id
        or (
            unit.kind == "visual"
            and unit.asset_id
            and evidence_ref.asset_id == unit.asset_id
        )
    )


def _content_unit_claim_sources(unit: ContentUnit) -> tuple[str, ...]:
    return tuple(
        value
        for value in (
            unit.text,
            unit.evidence_excerpt,
            unit.ocr_text,
            unit.summary,
            *unit.knowledge_claims,
        )
        if value
    )


def _evidence_matches_unit(
    evidence_ref: EvidenceRef,
    unit: ContentUnit,
) -> bool:
    """Require evidence to resolve to the claimed source, not just its ID."""

    if not _evidence_ref_binds_unit(evidence_ref, unit):
        return False
    if (
        unit.kind == "visual"
        and unit.asset_id
        and evidence_ref.asset_id == unit.asset_id
    ):
        return True
    excerpt = _normalized_evidence_text(evidence_ref.excerpt)
    if not excerpt or not _evidence_excerpt_is_specific(excerpt):
        return False
    return any(
        excerpt in source
        for value in _content_unit_claim_sources(unit)
        if (source := _normalized_evidence_text(value))
    )


def _fallback_theme_plan(
    document: ParsedDocument,
    units: list[ContentUnit],
) -> ThemePlanOutput:
    active_units = [unit for unit in units if _is_planning_unit(unit)]
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

    sampled_units = _theme_sample_units(units)
    summaries = [
        {
            "unit_id": unit.id,
            "heading_path": unit.heading_path,
            "kind": unit.kind,
            "page": unit.page,
            "slide": unit.slide,
            "summary": (
                unit.summary
                or unit.evidence_excerpt
                or unit.text[:280]
            )[:THEME_SUMMARY_MAX_CHARS],
            "importance": unit.importance,
        }
        for unit in sampled_units
    ]
    prompt = json.dumps(
        {
            "document_title": document.title,
            "content_units": summaries,
            "sampling": {
                "strategy": "text_visual_source_stratified",
                "text_count": sum(
                    item["kind"] == "text" for item in summaries
                ),
                "visual_count": sum(
                    item["kind"] == "visual" for item in summaries
                ),
                "sample_limit": THEME_SAMPLE_LIMIT,
            },
        },
        ensure_ascii=False,
    )
    try:
        with model_call_scope(
            input_unit_ids=tuple(
                item["unit_id"] for item in summaries
            )
        ):
            answer_token_budget = _theme_output_token_budget(
                len(summaries)
            )
            payload = await runtime.client.complete_json(
                model=runtime.model,
                system_prompt=THEME_SYNTHESIZER_PROMPT,
                user_prompt=prompt,
                **_structured_json_call_kwargs(
                    runtime,
                    answer_token_budget,
                    timeout_seconds=THEME_JSON_TIMEOUT_SECONDS,
                    thinking_token_budget=THEME_THINKING_TOKEN_BUDGET,
                ),
            )
        plan = ThemePlanOutput.model_validate(payload)
        ordered_valid_ids = [
            unit.id for unit in units if _is_planning_unit(unit)
        ]
        valid_ids = set(ordered_valid_ids)
        model_roots = [
            item.model_copy(
                update={
                    "support_unit_ids": ordered_valid_ids,
                }
            )
            for item in plan.root_candidates[:3]
            if item.name.strip() and item.name not in GENERIC_LABELS
        ]
        document_title = document.title.strip()
        if (
            document_title
            and document_title not in GENERIC_LABELS
            and is_publishable_label(
                document_title,
                allow_root=True,
                allow_section_label=True,
            )
        ):
            roots = [
                ThemeNodeSpec(
                    temp_id="root_document_title",
                    name=document_title,
                    definition=f"{document_title}的课程知识体系",
                    support_unit_ids=ordered_valid_ids,
                    confidence=1,
                )
            ]
        else:
            roots = sorted(
                model_roots,
                key=lambda item: item.confidence,
                reverse=True,
            )[:1]
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
        covered_sample_ids = {
            unit_id
            for branch in branches
            for unit_id in branch.support_unit_ids
        }
        missing_sample_ids = [
            unit.id
            for unit in sampled_units
            if unit.id not in covered_sample_ids
        ]
        if not covered_sample_ids:
            raise ValueError("主题模型一级主题没有绑定任何输入内容单元")
        warnings = []
        if missing_sample_ids:
            warnings.append(
                "主题模型一级主题未认领 "
                f"{len(missing_sample_ids)}/{len(sampled_units)} "
                "个采样内容单元，将由确定性分支规划补齐。"
            )
        return (
            ThemePlanOutput(root_candidates=roots, branch_topics=branches),
            True,
            warnings,
        )
    except (ModelProviderError, ValueError) as exc:
        return fallback, False, [f"全局主题生成失败，已降级：{exc}"]


def _unit_heading_keys(unit: ContentUnit) -> set[str]:
    values = [
        *unit.heading_path,
        unit.branch_hint or "",
    ]
    return {
        key
        for value in values
        if (key := normalized_key(value.strip()))
    }


def _unit_source_coordinate(
    unit: ContentUnit,
) -> tuple[Literal["page", "slide"], int] | None:
    if unit.page is not None:
        return "page", unit.page
    if unit.slide is not None:
        return "slide", unit.slide
    return None


def _ordered_unit_ids(
    unit_ids: list[str],
    unit_by_id: dict[str, ContentUnit],
) -> list[str]:
    original_order = {
        unit_id: index
        for index, unit_id in enumerate(unit_ids)
    }

    def key(unit_id: str) -> tuple[int, int, int, int, str]:
        unit = unit_by_id[unit_id]
        coordinate = _unit_source_coordinate(unit)
        if coordinate is None:
            return (
                1,
                10**12,
                0 if unit.kind == "text" else 1,
                original_order[unit_id],
                unit_id,
            )
        coordinate_kind, position = coordinate
        return (
            0 if coordinate_kind == "page" else 1,
            position,
            0 if unit.kind == "text" else 1,
            original_order[unit_id],
            unit_id,
        )

    return sorted(unit_ids, key=key)


def _plan_source_key(
    plan: BranchPlan,
    unit_by_id: dict[str, ContentUnit],
    fallback_order: int,
) -> tuple[int, int, int, str]:
    coordinates = [
        coordinate
        for unit_id in plan.unit_ids
        if (
            coordinate := _unit_source_coordinate(unit_by_id[unit_id])
        )
        is not None
    ]
    if not coordinates:
        return (2, 10**12, fallback_order, plan.id)
    coordinate_kind, position = min(
        coordinates,
        key=lambda item: (
            0 if item[0] == "page" else 1,
            item[1],
        ),
    )
    return (
        0 if coordinate_kind == "page" else 1,
        position,
        fallback_order,
        plan.id,
    )


_SECTION_LABEL = re.compile(
    r"^(?:[*△▲]?\s*)?(?:§\s*\d+(?:\.\d+)*|第\s*\d+\s*章)"
)
_SOURCE_SECTION_PREFIX = re.compile(
    r"^(?:[*△▲]?\s*)?"
    r"(?:§\s*\d+(?:\.\d+)*|第\s*\d+\s*章)\s*"
)
_SOURCE_ENUMERATION_PREFIX = re.compile(
    r"^(?:"
    r"[（(]?[一二三四五六七八九十]+[）)]?[.、．]?\s*"
    r"|\d{1,2}[.、．]\s*"
    r")"
)
_LEAF_TOPIC_TERMS = re.compile(
    r"(?:"
    r"理论|实验|原理|处理|量子化|概率分布|本征值谱|"
    r"耦合|双线|光谱|辐射|系数|条件|反转|泵浦|"
    r"振荡|激光器|谐振腔|纵模|能级|量子数|壳层|"
    r"排布|特点|组成部分|统计|不相容"
    r")"
)
_LEAF_BAD_PREFIX = re.compile(
    r"^(?:"
    r"右端|左端|上式|下式|例如|若|设|则|解得|应该|"
    r"只有|因为|为了|由于|而|年为|和(?:\s|有)|"
    r"上述|其中|此模型"
    r")"
)
_LEAF_FORMULA_FRAGMENT = re.compile(
    r"^(?:"
    r"[A-Za-zΑ-ω]\d*\s*(?:[⇒=>]|[—–-]{1,2})"
    r"|[A-Za-zΑ-ω]\s+"
    r")"
)
_LEAF_DECORATIVE_LABEL = re.compile(
    r"(?:历史)?(?:黑白)?照片|(?:示意图|曲线图)$"
)


def _leaf_label_candidate(
    raw_line: str,
) -> tuple[str, int]:
    line = raw_line.strip()
    if not line or _PAGE_NUMBER_ONLY.fullmatch(line):
        return "", 0
    if _PRIVATE_USE_OR_REPLACEMENT_GLYPH.search(line):
        return "", 0

    had_numbering = bool(
        _SOURCE_SECTION_PREFIX.match(line)
        or _SOURCE_ENUMERATION_PREFIX.match(line)
    )
    line = _SOURCE_SECTION_PREFIX.sub("", line, count=1)
    line = _SOURCE_ENUMERATION_PREFIX.sub("", line, count=1)
    line = re.sub(r"^[•●◆◇▪■□▲△*+\-—–\s]+", "", line)
    line = re.sub(r"[（(]\s*点击\s*[）)]", "", line)
    line = re.sub(r"\s+\d{1,3}$", "", line).strip()

    if re.match(r"^(?:小结|总结)\s*[：:]", line):
        line = re.split(r"[：:]", line, maxsplit=1)[1].strip()

    topic_match = re.match(
        r"^(.{2,46}?"
        r"(?:理论|实验|原理|处理|量子化|概率分布|本征值谱|"
        r"耦合|双线|光谱|辐射|系数|条件|反转|泵浦|"
        r"振荡|激光器|谐振腔|纵模|能级|量子数|壳层|"
        r"排布|特点|组成部分|统计|不相容))"
        r"(?=[：:，,。；;\s（(]|$)",
        line,
    )
    extracted_topic = topic_match is not None
    if topic_match is not None:
        line = topic_match.group(1).strip()
    else:
        line = re.split(
            r"[，,。！？；;:：]",
            line,
            maxsplit=1,
        )[0].strip()
        line = re.split(r"(?:解得|可得|表明)", line, maxsplit=1)[0].strip()

    if not line or len(line) > 48:
        return "", 0
    if _LEAF_BAD_PREFIX.match(line):
        return "", 0
    if _LEAF_FORMULA_FRAGMENT.match(line):
        return "", 0
    if _LEAF_DECORATIVE_LABEL.search(line):
        return "", 0
    if not is_publishable_label(line):
        return "", 0
    if _text_unit_disposition(line)[0] != "uncovered":
        return "", 0

    score = 0
    if had_numbering:
        score += 80
    if extracted_topic:
        score += 45
    if _LEAF_TOPIC_TERMS.search(line):
        score += 40
    if 4 <= len(line) <= 28:
        score += 20
    elif len(line) <= 36:
        score += 10
    return line, score


def _balanced_leaf_unit_groups(
    unit_ids: list[str],
    unit_by_id: dict[str, ContentUnit],
    max_units_per_leaf: int,
    *,
    unit_node_weights: dict[str, int] | None = None,
    max_node_weight_per_leaf: int | None = None,
) -> list[list[str]]:
    """Partition source-ordered units without splitting a page when possible."""

    weights = {
        unit_id: max(
            1,
            int((unit_node_weights or {}).get(unit_id, 1)),
        )
        for unit_id in unit_ids
    }
    weight_capacity = (
        max_node_weight_per_leaf
        if max_node_weight_per_leaf is not None
        else sum(weights.values()) or 1
    )
    if weight_capacity < 1:
        raise ValueError("max_node_weight_per_leaf 必须至少为 1")
    overweight_units = [
        unit_id
        for unit_id, weight in weights.items()
        if weight > weight_capacity
    ]
    if overweight_units:
        raise ValueError(
            "单个规划单元的直接节点权重超过叶分支容量："
            f"{overweight_units[0]}={weights[overweight_units[0]]}>"
            f"{weight_capacity}"
        )

    atomic_groups: list[list[str]] = []
    atomic_keys: list[tuple[str, int | str]] = []
    for unit_id in unit_ids:
        coordinate = _unit_source_coordinate(unit_by_id[unit_id])
        key: tuple[str, int | str] = (
            coordinate if coordinate is not None else ("unit", unit_id)
        )
        if atomic_groups and atomic_keys[-1] == key:
            atomic_groups[-1].append(unit_id)
        else:
            atomic_keys.append(key)
            atomic_groups.append([unit_id])

    capacity_groups: list[list[str]] = []
    for group in atomic_groups:
        if (
            len(group) <= max_units_per_leaf
            and sum(weights[unit_id] for unit_id in group)
            <= weight_capacity
        ):
            capacity_groups.append(group)
            continue
        current: list[str] = []
        current_weight = 0
        for unit_id in group:
            weight = weights[unit_id]
            if current and (
                len(current) >= max_units_per_leaf
                or current_weight + weight > weight_capacity
            ):
                capacity_groups.append(current)
                current = []
                current_weight = 0
            current.append(unit_id)
            current_weight += weight
        if current:
            capacity_groups.append(current)
    atomic_groups = capacity_groups

    total_units = len(unit_ids)
    total_weight = sum(weights.values())
    minimum_group_count = max(
        1,
        (total_units + max_units_per_leaf - 1) // max_units_per_leaf,
        (total_weight + weight_capacity - 1) // weight_capacity,
    )
    atom_count = len(atomic_groups)
    prefix_sizes = [0]
    prefix_weights = [0]
    for group in atomic_groups:
        prefix_sizes.append(prefix_sizes[-1] + len(group))
        prefix_weights.append(
            prefix_weights[-1]
            + sum(weights[unit_id] for unit_id in group)
        )

    for group_count in range(minimum_group_count, atom_count + 1):
        memo: dict[
            tuple[int, int],
            tuple[int, tuple[int, ...]] | None,
        ] = {}

        def solve(
            start: int,
            remaining: int,
        ) -> tuple[int, tuple[int, ...]] | None:
            key = (start, remaining)
            if key in memo:
                return memo[key]
            if remaining == 0:
                result = (0, ()) if start == atom_count else None
                memo[key] = result
                return result
            if atom_count - start < remaining:
                memo[key] = None
                return None

            best: tuple[int, tuple[int, ...]] | None = None
            max_end = atom_count - remaining + 1
            for end in range(start + 1, max_end + 1):
                size = prefix_sizes[end] - prefix_sizes[start]
                weight = prefix_weights[end] - prefix_weights[start]
                if size > max_units_per_leaf:
                    break
                if weight > weight_capacity:
                    break
                suffix = solve(end, remaining - 1)
                if suffix is None:
                    continue
                unit_deviation = size * group_count - total_units
                weight_deviation = weight * group_count - total_weight
                undersized = max(
                    0,
                    min(3, max_units_per_leaf) - size,
                )
                cost = (
                    unit_deviation * unit_deviation
                    + weight_deviation * weight_deviation
                    + undersized * undersized * group_count * group_count * 4
                    + suffix[0]
                )
                candidate = (cost, (end, *suffix[1]))
                if best is None or candidate < best:
                    best = candidate
            memo[key] = best
            return best

        solution = solve(0, group_count)
        if solution is None:
            continue
        boundaries = solution[1]
        result: list[list[str]] = []
        start = 0
        for end in boundaries:
            result.append(
                [
                    unit_id
                    for group in atomic_groups[start:end]
                    for unit_id in group
                ]
            )
            start = end
        return result

    raise ValueError(
        "内容单元无法在保持源页原子组和叶分支容量时完成无损规划"
    )


def _consolidate_plans_for_leaf_capacity(
    plans: list[BranchPlan],
    unit_by_id: dict[str, ContentUnit],
    max_units_per_leaf: int,
    *,
    unit_node_weights: dict[str, int],
    max_node_weight_per_leaf: int | None,
) -> list[BranchPlan] | None:
    """Merge adjacent weak roots only when root-local packing wastes capacity."""

    if len(plans) < 2:
        return None

    segment_cache: dict[
        tuple[int, int],
        tuple[list[str], list[list[str]], int],
    ] = {}

    def segment_payload(
        start: int,
        end: int,
    ) -> tuple[list[str], list[list[str]], int]:
        key = (start, end)
        if key in segment_cache:
            return segment_cache[key]
        segment = plans[start:end]
        merged_unit_ids = _ordered_unit_ids(
            list(
                dict.fromkeys(
                    unit_id
                    for plan in segment
                    for unit_id in plan.unit_ids
                )
            ),
            unit_by_id,
        )
        leaf_groups = _balanced_leaf_unit_groups(
            merged_unit_ids,
            unit_by_id,
            max_units_per_leaf,
            unit_node_weights=unit_node_weights,
            max_node_weight_per_leaf=max_node_weight_per_leaf,
        )
        representative_index = max(
            range(start, end),
            key=lambda index: (
                sum(
                    unit_node_weights[unit_id]
                    for unit_id in plans[index].unit_ids
                ),
                len(plans[index].unit_ids),
                plans[index].cohesion,
                -index,
            ),
        )
        result = (
            merged_unit_ids,
            leaf_groups,
            representative_index,
        )
        segment_cache[key] = result
        return result

    best: tuple[
        tuple[int, int, int, float, int, tuple[tuple[int, int], ...]],
        list[tuple[int, int]],
    ] | None = None
    boundary_count = len(plans) - 1
    for boundary_mask in range(1 << boundary_count):
        segments: list[tuple[int, int]] = []
        start = 0
        for boundary_index in range(boundary_count):
            if boundary_mask & (1 << boundary_index):
                segments.append((start, boundary_index + 1))
                start = boundary_index + 1
        segments.append((start, len(plans)))

        leaf_count = sum(
            len(segment_payload(start, end)[1])
            for start, end in segments
        )
        if leaf_count > MAX_LEAF_BRANCHES:
            continue

        lost_indices = {
            index
            for start, end in segments
            for index in range(start, end)
            if index != segment_payload(start, end)[2]
        }
        score = (
            -len(segments),
            sum(
                unit_node_weights[unit_id]
                for index in lost_indices
                for unit_id in plans[index].unit_ids
            ),
            sum(
                len(plans[index].unit_ids)
                for index in lost_indices
            ),
            round(
                sum(plans[index].cohesion for index in lost_indices),
                8,
            ),
            leaf_count,
            tuple(segments),
        )
        candidate = (score, segments)
        if best is None or candidate[0] < best[0]:
            best = candidate

    if best is None:
        return None

    consolidated: list[BranchPlan] = []
    for start, end in best[1]:
        merged_unit_ids, _, representative_index = segment_payload(
            start,
            end,
        )
        representative = plans[representative_index]
        if end - start == 1:
            consolidated.append(representative)
            continue
        segment = plans[start:end]
        total_units = sum(len(plan.unit_ids) for plan in segment)
        weighted_cohesion = (
            sum(
                plan.cohesion * len(plan.unit_ids)
                for plan in segment
            )
            / max(total_units, 1)
        )
        consolidated.append(
            representative.model_copy(
                update={
                    "unit_ids": merged_unit_ids,
                    "cohesion": min(
                        representative.cohesion,
                        weighted_cohesion,
                    ),
                }
            )
        )
    return consolidated


def _leaf_source_label(
    plan: BranchPlan,
    unit_ids: list[str],
    unit_by_id: dict[str, ContentUnit],
    *,
    leaf_index: int,
    used_keys: set[str],
) -> str:
    excluded_keys = {
        normalized_key(plan.label),
        normalized_key(_leaf_label_candidate(plan.label)[0]),
        *(
            normalized_key(heading)
            for unit_id in unit_ids
            for heading in unit_by_id[unit_id].heading_path
            if heading.strip()
        ),
        *(
            normalized_key(_leaf_label_candidate(heading)[0])
            for unit_id in unit_ids
            for heading in unit_by_id[unit_id].heading_path
            if heading.strip()
        ),
    }
    text_candidates: list[tuple[int, int, str]] = []
    visual_candidates: list[tuple[int, int, str]] = []
    source_index = 0
    for unit_id in unit_ids:
        unit = unit_by_id[unit_id]
        source = unit.text or unit.summary or unit.ocr_text
        for raw_line in source.splitlines():
            source_index += 1
            line = raw_line.strip()
            if not line or _PAGE_NUMBER_ONLY.fullmatch(line):
                continue
            if _SECTION_LABEL.match(line):
                continue
            candidate, score = _leaf_label_candidate(line)
            key = normalized_key(candidate)
            if (
                not key
                or key in excluded_keys
                or key in used_keys
            ):
                continue
            role_bonus = (
                10
                if unit.unit_role
                in {"definition", "principle", "formula", "example"}
                else 0
            )
            target = (
                text_candidates
                if unit.kind == "text"
                else visual_candidates
            )
            target.append((score + role_bonus, -source_index, candidate))

    candidates = [
        *text_candidates,
        *[
            (score - 10, source_order, candidate)
            for score, source_order, candidate in visual_candidates
        ],
    ]
    if candidates:
        candidate = max(candidates)[2]
        used_keys.add(normalized_key(candidate))
        return candidate

    coordinates = [
        coordinate
        for unit_id in unit_ids
        if (
            coordinate := _unit_source_coordinate(unit_by_id[unit_id])
        )
        is not None
    ]
    if coordinates:
        coordinate_kind = coordinates[0][0]
        positions = [
            position
            for kind, position in coordinates
            if kind == coordinate_kind
        ]
        if positions:
            start, end = min(positions), max(positions)
            location = (
                f"第{start}页"
                if coordinate_kind == "page" and start == end
                else f"第{start}–{end}页"
                if coordinate_kind == "page"
                else f"第{start}张"
                if start == end
                else f"第{start}–{end}张"
            )
            fallback = f"{plan.label}（{location}）"
            key = normalized_key(fallback)
            if is_publishable_label(fallback) and key not in used_keys:
                used_keys.add(key)
                return fallback

    fallback = f"{plan.label}·分段{leaf_index}"
    used_keys.add(normalized_key(fallback))
    return fallback


def _assign_pending_units_to_plans(
    plans: list[BranchPlan],
    pending_ids: list[str],
    unit_by_id: dict[str, ContentUnit],
) -> list[BranchPlan]:
    """Attach overflow/unclaimed units without changing retained semantics."""

    plan_by_id = {plan.id: plan for plan in plans}
    plan_order = {
        plan.id: index
        for index, plan in enumerate(plans)
    }
    assigned_ids = {
        plan.id: list(plan.unit_ids)
        for plan in plans
    }
    assigned_plan_by_unit = {
        unit_id: plan.id
        for plan in plans
        for unit_id in plan.unit_ids
    }
    plan_heading_keys: dict[str, set[str]] = {}
    plan_source_coordinates: dict[
        str,
        list[tuple[Literal["page", "slide"], int]],
    ] = {}
    for plan in plans:
        headings = {normalized_key(plan.label)}
        coordinates: list[
            tuple[Literal["page", "slide"], int]
        ] = []
        for unit_id in plan.unit_ids:
            unit = unit_by_id[unit_id]
            headings.update(_unit_heading_keys(unit))
            coordinate = _unit_source_coordinate(unit)
            if coordinate is not None:
                coordinates.append(coordinate)
        plan_heading_keys[plan.id] = {
            heading for heading in headings if heading
        }
        plan_source_coordinates[plan.id] = coordinates

    def source_distance(unit: ContentUnit, plan_id: str) -> int | None:
        coordinate = _unit_source_coordinate(unit)
        if coordinate is None:
            return None
        kind, position = coordinate
        candidates = [
            abs(position - anchor_position)
            for anchor_kind, anchor_position
            in plan_source_coordinates[plan_id]
            if anchor_kind == kind
        ]
        return min(candidates) if candidates else None

    def stable_plan_rank(plan_id: str) -> tuple[int, int, str]:
        return (
            len(assigned_ids[plan_id]),
            plan_order[plan_id],
            plan_id,
        )

    def select_target(unit: ContentUnit) -> str:
        nearby_counts: Counter[str] = Counter()
        for nearby_id in unit.nearby_text_ids:
            nearby = unit_by_id.get(nearby_id)
            target_id = assigned_plan_by_unit.get(nearby_id)
            if nearby is not None and nearby.kind == "text" and target_id:
                nearby_counts[target_id] += 1
        if nearby_counts:
            return min(
                nearby_counts,
                key=lambda plan_id: (
                    -nearby_counts[plan_id],
                    source_distance(unit, plan_id)
                    if source_distance(unit, plan_id) is not None
                    else 10**12,
                    stable_plan_rank(plan_id),
                ),
            )

        heading_keys = _unit_heading_keys(unit)
        heading_matches = {
            plan_id: heading_keys & plan_heading_keys[plan_id]
            for plan_id in plan_by_id
        }
        heading_matches = {
            plan_id: matches
            for plan_id, matches in heading_matches.items()
            if matches
        }
        if heading_matches:
            return min(
                heading_matches,
                key=lambda plan_id: (
                    -max(
                        len(heading)
                        for heading in heading_matches[plan_id]
                    ),
                    -len(heading_matches[plan_id]),
                    source_distance(unit, plan_id)
                    if source_distance(unit, plan_id) is not None
                    else 10**12,
                    stable_plan_rank(plan_id),
                ),
            )

        source_distances = {
            plan_id: distance
            for plan_id in plan_by_id
            if (
                distance := source_distance(unit, plan_id)
            ) is not None
        }
        if source_distances:
            return min(
                source_distances,
                key=lambda plan_id: (
                    source_distances[plan_id],
                    stable_plan_rank(plan_id),
                ),
            )
        return min(plan_by_id, key=stable_plan_rank)

    ordered_pending_ids = [
        *(
            unit_id
            for unit_id in pending_ids
            if unit_by_id[unit_id].kind == "text"
        ),
        *(
            unit_id
            for unit_id in pending_ids
            if unit_by_id[unit_id].kind != "text"
        ),
    ]
    for unit_id in ordered_pending_ids:
        unit = unit_by_id[unit_id]
        target_id = select_target(unit)
        assigned_ids[target_id].append(unit_id)
        assigned_plan_by_unit[unit_id] = target_id

    return [
        plan.model_copy(
            update={
                "unit_ids": assigned_ids[plan.id],
                "coverage_budget": min(
                    MAX_BRANCH_NODE_BUDGET,
                    max(3, len(assigned_ids[plan.id]) * 2),
                ),
            }
        )
        for plan in plans
    ]


def build_branch_plans(
    theme_plan: ThemePlanOutput,
    units: list[ContentUnit],
    *,
    max_units_per_leaf: int = 8,
    max_depth: int = 3,
    unit_node_weights: dict[str, int] | None = None,
    max_node_weight_per_leaf: int | None = None,
) -> list[BranchPlan]:
    unit_by_id = {unit.id: unit for unit in units}
    node_weights = {
        unit.id: max(
            1,
            int((unit_node_weights or {}).get(unit.id, 1)),
        )
        for unit in units
    }

    def coverage_budget(unit_ids: list[str]) -> int:
        estimate = (
            sum(node_weights[unit_id] for unit_id in unit_ids)
            if unit_node_weights is not None
            else len(unit_ids) * 2
        )
        return min(MAX_BRANCH_NODE_BUDGET, max(3, estimate))

    claimed: set[str] = set()
    plans: list[BranchPlan] = []

    ranked_topics = sorted(
        enumerate(theme_plan.branch_topics),
        key=lambda item: (
            -item[1].confidence,
            -len(item[1].support_unit_ids),
            item[0],
        ),
    )
    overflow_ids: list[str] = []
    for _, topic in ranked_topics:
        unit_ids = [
            unit_id
            for unit_id in topic.support_unit_ids
            if (
                unit_id in unit_by_id
                and _is_planning_unit(unit_by_id[unit_id])
                and unit_id not in claimed
            )
        ]
        if not unit_ids:
            continue
        claimed.update(unit_ids)
        if len(plans) >= MAX_ROOT_BRANCHES:
            overflow_ids.extend(unit_ids)
            continue
        label = (
            topic.name.strip()
            if is_publishable_label(
                topic.name,
                allow_section_label=True,
            )
            else _short_label(
                unit_by_id[unit_ids[0]].text
                or unit_by_id[unit_ids[0]].summary,
                "其他课程要点",
            )
        )
        plans.append(
            BranchPlan(
                id=stable_id("branch", topic.temp_id, label),
                label=label,
                description=topic.definition,
                unit_ids=unit_ids,
                depth=1,
                cohesion=topic.confidence,
                coverage_budget=coverage_budget(unit_ids),
            )
        )

    unclaimed = [
        unit.id
        for unit in units
        if unit.id not in claimed and _is_planning_unit(unit)
    ]
    pending_ids = list(dict.fromkeys([*overflow_ids, *unclaimed]))
    if pending_ids and plans:
        plans = _assign_pending_units_to_plans(
            plans,
            pending_ids,
            unit_by_id,
        )
    elif pending_ids:
        first_unit = unit_by_id[pending_ids[0]]
        label = _short_label(
            first_unit.text or first_unit.summary,
            "其他课程要点",
        )
        plans.append(
            BranchPlan(
                id=stable_id("branch", "unassigned"),
                label=label,
                description="全局主题规划未覆盖的内容单元",
                unit_ids=pending_ids,
                depth=1,
                cohesion=0.45,
                coverage_budget=coverage_budget(pending_ids),
            )
        )

    plan_order = {
        plan.id: index
        for index, plan in enumerate(plans)
    }
    plans = [
        plan.model_copy(
            update={
                "unit_ids": _ordered_unit_ids(
                    plan.unit_ids,
                    unit_by_id,
                ),
                "coverage_budget": coverage_budget(plan.unit_ids),
            }
        )
        for plan in plans
    ]
    plans.sort(
        key=lambda plan: _plan_source_key(
            plan,
            unit_by_id,
            plan_order[plan.id],
        )
    )

    if max_units_per_leaf < 1:
        raise ValueError("max_units_per_leaf 必须至少为 1")

    required_leaf_groups: list[
        tuple[BranchPlan, list[list[str]]]
    ] = []
    for plan in plans:
        leaf_groups = _balanced_leaf_unit_groups(
            plan.unit_ids,
            unit_by_id,
            max_units_per_leaf,
            unit_node_weights=node_weights,
            max_node_weight_per_leaf=max_node_weight_per_leaf,
        )
        required_count = len(leaf_groups)
        if required_count > 1 and plan.depth >= max_depth:
            raise ValueError(
                f"分支“{plan.label}”需要 {required_count} 个叶分支，"
                f"但已达到 max_depth={max_depth}"
            )
        required_leaf_groups.append((plan, leaf_groups))

    total_required_leaves = sum(
        len(leaf_groups)
        for _, leaf_groups in required_leaf_groups
    )
    if total_required_leaves > MAX_LEAF_BRANCHES:
        consolidated = _consolidate_plans_for_leaf_capacity(
            plans,
            unit_by_id,
            max_units_per_leaf,
            unit_node_weights=node_weights,
            max_node_weight_per_leaf=max_node_weight_per_leaf,
        )
        if consolidated is None:
            raise ValueError(
                f"{len(unit_by_id)} 个内容单元至少需要 "
                f"{total_required_leaves} 个叶分支，超过全局上限 "
                f"{MAX_LEAF_BRANCHES}；不能在保持每叶最多 "
                f"{max_units_per_leaf} 个单元时无损规划"
            )
        plans = [
            plan.model_copy(
                update={
                    "coverage_budget": coverage_budget(plan.unit_ids),
                }
            )
            for plan in consolidated
        ]
        required_leaf_groups = [
            (
                plan,
                _balanced_leaf_unit_groups(
                    plan.unit_ids,
                    unit_by_id,
                    max_units_per_leaf,
                    unit_node_weights=node_weights,
                    max_node_weight_per_leaf=max_node_weight_per_leaf,
                ),
            )
            for plan in plans
        ]

    expanded: list[BranchPlan] = []
    for plan, leaf_groups in required_leaf_groups:
        if len(leaf_groups) == 1:
            expanded.append(plan)
            continue

        expanded.append(plan.model_copy(update={"leaf": False}))
        used_leaf_label_keys = {normalized_key(plan.label)}
        for index, unit_ids in enumerate(leaf_groups, start=1):
            proposed_label = _leaf_source_label(
                plan,
                unit_ids,
                unit_by_id,
                leaf_index=index,
                used_keys=used_leaf_label_keys,
            )
            expanded.append(
                BranchPlan(
                    id=stable_id(
                        "branch",
                        plan.id,
                        str(index),
                        proposed_label,
                    ),
                    label=proposed_label,
                    description=f"{plan.label}下的局部主题",
                    unit_ids=unit_ids,
                    parent_branch_id=plan.id,
                    depth=plan.depth + 1,
                    cohesion=max(0.5, plan.cohesion - 0.08),
                    coverage_budget=coverage_budget(unit_ids),
                )
            )

    leaves = [plan for plan in expanded if plan.leaf]
    occurrences = Counter(
        unit_id
        for leaf in leaves
        for unit_id in leaf.unit_ids
    )
    expected_ids = {
        unit.id for unit in units if _is_planning_unit(unit)
    }
    if (
        len(leaves) > MAX_LEAF_BRANCHES
        or any(
            len(leaf.unit_ids) > max_units_per_leaf
            for leaf in leaves
        )
        or (
            max_node_weight_per_leaf is not None
            and any(
                sum(node_weights[unit_id] for unit_id in leaf.unit_ids)
                > max_node_weight_per_leaf
                for leaf in leaves
            )
        )
        or set(occurrences) != expected_ids
        or any(
            occurrences[unit_id] != 1
            for unit_id in expected_ids
        )
    ):
        raise RuntimeError("叶分支规划未满足全局容量或无损覆盖约束")
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
        # Branch extraction emits candidates, not publication mandates.
        # Keeping them optional lets the topology solver reject weak or
        # conflicting concepts even when a model incorrectly sets false.
        optional=True,
        activation_score=(
            output.activation_score
            if output.activation_score is not None
            else output.confidence
        ),
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
                    excerpt=(
                        chunk.text[:500].strip()
                        if (
                            chunk.heading
                            and normalized_key(item.excerpt)
                            == normalized_key(chunk.heading)
                            and not _evidence_excerpt_is_specific(
                                _normalized_evidence_text(item.excerpt)
                            )
                        )
                        else item.excerpt
                    ),
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
                    optional=True,
                    activation_score=candidate.confidence,
                    activation_cost=0.55,
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
        if unit.kind != "visual" or not _is_planning_unit(unit):
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
                optional=True,
                activation_score=unit.knowledge_score,
                activation_cost=0.45,
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


def _branch_prompt_unit(unit: ContentUnit) -> dict[str, object]:
    payload: dict[str, object] = {
        "unit_id": unit.id,
        "kind": unit.kind,
        "text": (unit.text or unit.summary or unit.ocr_text)[:2600],
    }
    if unit.heading_path:
        payload["heading_path"] = unit.heading_path
    if unit.page is not None:
        payload["page"] = unit.page
    if unit.slide is not None:
        payload["slide"] = unit.slide
    if unit.kind == "visual":
        if unit.asset_id:
            payload["asset_id"] = unit.asset_id
        if unit.visual_kind:
            payload["visual_kind"] = unit.visual_kind
        if unit.visual_action:
            payload["visual_action"] = unit.visual_action
        payload["knowledge_claims"] = unit.knowledge_claims
        if unit.nearby_text_ids:
            payload["nearby_text_ids"] = unit.nearby_text_ids
        if unit.bbox is not None:
            payload["bbox"] = unit.bbox
        if unit.parent_asset_id:
            payload["parent_asset_id"] = unit.parent_asset_id
    return payload


async def _branch_scout(state: BranchTeamState) -> dict:
    branch = state["branch"]
    all_units = [
        unit
        for unit in state["units"]
        if _is_planning_unit(unit)
    ]
    all_unit_ids = {unit.id for unit in all_units}
    seed_source_unit_ids = set(
        state.get("seed_source_unit_ids", [])
    )
    seeded_nodes: list[NodeCandidateIn] = []
    seeded_unit_ids = set(state.get("seeded_unit_ids", [])) & all_unit_ids
    for candidate in state.get("seed_nodes", []):
        candidate_unit_ids = _candidate_unit_ids(candidate)
        valid_seed_ids = seed_source_unit_ids or all_unit_ids
        candidate_unit_ids &= valid_seed_ids
        if not candidate_unit_ids:
            continue
        if not seed_source_unit_ids:
            seeded_unit_ids.update(candidate_unit_ids & all_unit_ids)
        seeded_nodes.append(
            candidate.model_copy(
                update={
                    "temp_id": (
                        candidate.temp_id
                        if candidate.temp_id.startswith(f"{branch.id}:")
                        else f"{branch.id}:{candidate.temp_id}"
                    ),
                    "branch_id": branch.id,
                    "optional": True,
                }
            )
        )
    units = [
        unit
        for unit in all_units
        if unit.id not in seeded_unit_ids
    ]
    remaining_unit_ids = {unit.id for unit in units}
    chunks = [
        chunk
        for chunk in state["chunks"]
        if chunk.id in remaining_unit_ids
    ]
    runtime = state["runtime"]
    warnings = list(state.get("warnings", []))
    unit_order = [
        *state.get("seed_source_unit_ids", []),
        *[
            unit.id
            for unit in all_units
            if unit.id not in seeded_unit_ids
        ],
    ]

    if not branch.leaf:
        return {
            "nodes": [],
            "cross_links": [],
            "used_model": False,
            "warnings": warnings,
        }

    if seeded_nodes and not units:
        return {
            "nodes": seeded_nodes,
            "cross_links": [],
            "used_model": True,
            "warnings": warnings,
        }

    fallback = _heuristic_branch_extract(branch, chunks, units)
    if not runtime.available or not runtime.client:
        warnings.append(
            f"分支“{branch.label}”使用本地抽取："
            f"{runtime.unavailable_reason or '模型不可用'}"
        )
        fallback_candidates = [
            *[
                _to_node_candidate(item, branch)
                for item in fallback.nodes
            ],
        ]
        fallback_nodes = _select_branch_candidates(
            fallback_candidates,
            coverage_budget=branch.coverage_budget,
            unit_order=unit_order,
        )
        fallback_nodes = [*seeded_nodes, *fallback_nodes]
        if len(fallback.nodes) > branch.coverage_budget:
            warnings.append(
                f"分支“{branch.label}”本地候选超过 coverage_budget="
                f"{branch.coverage_budget}，已按单元覆盖优先并按证据分截断。"
            )
        return {
            "nodes": fallback_nodes,
            "cross_links": fallback.cross_links,
            "used_model": bool(seeded_nodes),
            "warnings": warnings,
        }

    prompt_units = [_branch_prompt_unit(unit) for unit in units]
    try:
        answer_token_budget = _branch_output_token_budget(
            branch.coverage_budget
        )
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
            **_structured_json_call_kwargs(
                runtime,
                answer_token_budget,
            ),
        )
        extraction, schema_warnings = _validate_branch_extraction_payload(
            payload
        )
        warnings.extend(
            f"分支“{branch.label}”模型输出 {warning}"
            for warning in schema_warnings
        )
        unit_by_id = {unit.id: unit for unit in units}
        valid_unit_ids = set(unit_by_id)
        validated_nodes: list[NodeCandidateIn] = []
        for item in extraction.nodes:
            validated_evidence: list[EvidenceRef] = []
            for evidence_ref in item.evidence:
                unit_id = evidence_ref.unit_id or evidence_ref.chunk_id
                unit = unit_by_id.get(unit_id or "")
                if unit is None or not _evidence_matches_unit(
                    evidence_ref,
                    unit,
                ):
                    continue
                validated_evidence.append(
                    evidence_ref.model_copy(
                        update={
                            "unit_id": unit.id,
                            "chunk_id": unit.id if unit.kind == "text" else None,
                            "page": unit.page,
                            "slide": unit.slide,
                            "bbox": unit.bbox,
                            "asset_id": unit.asset_id,
                        }
                    )
                )
            support_ids = [
                unit_id
                for unit_id in item.support_unit_ids
                if unit_id in valid_unit_ids
            ]
            if item.origin == "explicit" and not validated_evidence:
                warnings.append(
                    f"分支“{branch.label}”拒绝了没有原文匹配证据的"
                    f"显式节点“{item.name}”。"
                )
                continue
            referenced_ids = {
                *support_ids,
                *[
                    evidence_ref.unit_id or evidence_ref.chunk_id
                    for evidence_ref in validated_evidence
                    if evidence_ref.unit_id or evidence_ref.chunk_id
                ],
            }
            if (
                item.origin == "explicit"
                and referenced_ids
                and all(
                    unit_by_id[unit_id].kind == "visual"
                    and unit_by_id[unit_id].visual_action
                    == "attach_as_media"
                    for unit_id in referenced_ids
                )
            ):
                warnings.append(
                    f"分支“{branch.label}”拒绝了仅由 attach_as_media "
                    f"单元支持的独立节点“{item.name}”。"
                )
                continue
            if item.origin == "explicit":
                claim_sources = tuple(
                    source
                    for unit_id in referenced_ids
                    for source in _content_unit_claim_sources(
                        unit_by_id[unit_id]
                    )
                )
                claim_issues = tuple(
                    issue
                    for claim_field in (item.name, item.definition)
                    if claim_field.strip()
                    for issue in claim_fidelity_issues(
                        claim_field,
                        claim_sources,
                    )
                )
                hard_claim_issues = [
                    issue
                    for issue in claim_issues
                    if issue.severity == "hard"
                ]
                if hard_claim_issues:
                    issue_codes = ",".join(
                        sorted(
                            {
                                issue.code
                                for issue in hard_claim_issues
                            }
                        )
                    )
                    warnings.append(
                        f"分支“{branch.label}”候选“{item.temp_id}”"
                        f"（{item.name}）命中 claim fidelity 硬门"
                        f"（{issue_codes}），已转 deferred/reextract，"
                        "不进入正式候选。"
                    )
                    continue
                soft_claim_issues = [
                    issue
                    for issue in claim_issues
                    if issue.severity == "soft"
                ]
                if soft_claim_issues:
                    issue_codes = ",".join(
                        sorted(
                            {
                                issue.code
                                for issue in soft_claim_issues
                            }
                        )
                    )
                    warnings.append(
                        f"分支“{branch.label}”候选“{item.temp_id}”"
                        f"（{item.name}）存在软证据缺口"
                        f"（{issue_codes}）；当前文本/OCR 可能未保留"
                        "完整公式或数字，保留候选并等待源页/视觉复核。"
                    )
            validated_nodes.append(
                _to_node_candidate(
                    item.model_copy(
                        update={
                            "evidence": validated_evidence,
                            "support_unit_ids": support_ids,
                        }
                    ),
                    branch,
                )
            )
        if not validated_nodes:
            raise ValueError("模型没有返回带有效证据的节点")
        if len(validated_nodes) > branch.coverage_budget:
            warnings.append(
                f"分支“{branch.label}”模型候选超过 coverage_budget="
                f"{branch.coverage_budget}，已按单元覆盖优先并按证据分截断。"
            )
        validated_nodes = _select_branch_candidates(
            validated_nodes,
            coverage_budget=branch.coverage_budget,
            unit_order=unit_order,
        )
        validated_nodes = [*seeded_nodes, *validated_nodes]
        return {
            "nodes": validated_nodes,
            "cross_links": extraction.cross_links,
            "used_model": True,
            "warnings": warnings,
        }
    except (ModelProviderError, ValueError) as exc:
        warnings.append(f"分支“{branch.label}”模型抽取失败，已局部降级：{exc}")
        fallback_candidates = [
            *[
                _to_node_candidate(item, branch)
                for item in fallback.nodes
            ],
        ]
        fallback_nodes = _select_branch_candidates(
            fallback_candidates,
            coverage_budget=branch.coverage_budget,
            unit_order=unit_order,
        )
        fallback_nodes = [*seeded_nodes, *fallback_nodes]
        if len(fallback.nodes) > branch.coverage_budget:
            warnings.append(
                f"分支“{branch.label}”降级候选超过 coverage_budget="
                f"{branch.coverage_budget}，已按单元覆盖优先截断。"
            )
        return {
            "nodes": fallback_nodes,
            "cross_links": fallback.cross_links,
            "used_model": bool(seeded_nodes),
            "warnings": warnings,
        }


def _candidate_rank(candidate: NodeCandidateIn) -> tuple[float, int, int]:
    support = len(candidate.evidence) + len(candidate.support_unit_ids)
    return (
        candidate.confidence + min(support, 4) * 0.04,
        len(candidate.definition),
        -len(candidate.name),
    )


def _merge_node_candidates(
    existing: NodeCandidateIn,
    candidate: NodeCandidateIn,
) -> NodeCandidateIn:
    primary = max((existing, candidate), key=_candidate_rank)
    secondary = candidate if primary is existing else existing
    aliases = {
        *existing.aliases,
        *candidate.aliases,
    }
    if secondary.name != primary.name:
        aliases.add(secondary.name)
    return primary.model_copy(
        update={
            "aliases": sorted(aliases),
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
            "confidence": max(
                existing.confidence,
                candidate.confidence,
            ),
            "optional": existing.optional and candidate.optional,
            "activation_score": max(
                existing.activation_score or existing.confidence,
                candidate.activation_score or candidate.confidence,
            ),
        }
    )


def _is_structural_candidate_identity(
    candidate: NodeCandidateIn,
) -> bool:
    return bool(
        candidate.is_root_candidate
        or candidate.role in {"root_topic", "branch_topic", "structural"}
        or candidate.type in {"root_topic", "branch_topic", "structural"}
        or candidate.origin in {"synthesized_root", "structural"}
    )


def _resolve_same_temp_id(
    existing: NodeCandidateIn,
    candidate: NodeCandidateIn,
) -> NodeCandidateIn:
    """Avoid blending two material claims that reused one model temp ID."""

    existing_structural = _is_structural_candidate_identity(existing)
    candidate_structural = _is_structural_candidate_identity(candidate)
    if existing_structural and candidate_structural:
        return _merge_node_candidates(existing, candidate)
    if existing_structural != candidate_structural:
        return existing if existing_structural else candidate
    if are_mergeable_exact_duplicates(existing, candidate):
        return _merge_node_candidates(existing, candidate)
    if (
        not existing.definition.strip()
        and not candidate.definition.strip()
        and not _MATERIAL_IDENTITY_LABEL.search(existing.name)
        and not _MATERIAL_IDENTITY_LABEL.search(candidate.name)
        and not (
            existing.branch_id
            and candidate.branch_id
            and existing.branch_id != candidate.branch_id
        )
    ):
        # Some branch payloads repeat one model temp ID while splitting its
        # evidence across otherwise label-only candidates. Preserve that
        # provenance, but never use this compatibility path for equations,
        # numeric claims, causal claims, or cross-branch ID collisions.
        return _merge_node_candidates(existing, candidate)
    return max((existing, candidate), key=_candidate_rank)


def _select_branch_candidates(
    candidates: list[NodeCandidateIn],
    *,
    coverage_budget: int,
    unit_order: list[str],
) -> list[NodeCandidateIn]:
    if coverage_budget <= 0 or not candidates:
        return []
    exact: list[NodeCandidateIn] = []
    exact_index: dict[str, int] = {}
    for candidate in candidates:
        index = exact_index.get(candidate.temp_id)
        if index is None:
            exact_index[candidate.temp_id] = len(exact)
            exact.append(candidate)
        else:
            exact[index] = _resolve_same_temp_id(
                exact[index],
                candidate,
            )
    ranked = sorted(exact, key=_candidate_rank, reverse=True)
    units_by_candidate = {
        candidate.temp_id: _candidate_unit_ids(candidate)
        for candidate in ranked
    }
    selected: list[NodeCandidateIn] = []
    selected_ids: set[str] = set()
    covered_units: set[str] = set()

    for unit_id in dict.fromkeys(unit_order):
        if unit_id in covered_units:
            continue
        candidate = next(
            (
                item
                for item in ranked
                if (
                    item.temp_id not in selected_ids
                    and unit_id in units_by_candidate[item.temp_id]
                )
            ),
            None,
        )
        if candidate is None:
            continue
        selected.append(candidate)
        selected_ids.add(candidate.temp_id)
        covered_units.update(units_by_candidate[candidate.temp_id])
        if len(selected) >= coverage_budget:
            break

    if len(selected) < coverage_budget:
        for candidate in ranked:
            if candidate.temp_id in selected_ids:
                continue
            selected.append(candidate)
            selected_ids.add(candidate.temp_id)
            if len(selected) >= coverage_budget:
                break

    return sorted(selected, key=_candidate_rank, reverse=True)


async def _granularity_critic(state: BranchTeamState) -> dict:
    grouped: dict[str, list[NodeCandidateIn]] = defaultdict(list)
    warnings = list(state.get("warnings", []))
    for candidate in state.get("nodes", []):
        disposition = candidate_field_disposition(candidate)
        if disposition.action in {
            "reextract_candidate",
            "reject_entire_node",
        }:
            reasons = [
                *(f"label:{item}" for item in disposition.label_issues),
                *(
                    f"definition:{item}"
                    for item in disposition.definition_issues
                ),
            ]
            rejection = (
                "name 与 definition 均不自足，已整节点拒绝并需要重抽取"
                if disposition.action == "reject_entire_node"
                else "无法安全确定发布字段，需要重抽取候选"
            )
            warnings.append(
                f"候选“{candidate.temp_id}”（{candidate.name}）"
                f"未通过字段资格门（{','.join(reasons) or 'unknown'}），"
                f"{rejection}；当前内容留待 deferred/review。"
            )
            continue
        if disposition.action in {
            "repair_label_keep_claim",
            "repair_label_and_trim_definition_keep_claim",
        }:
            warnings.append(
                f"候选“{candidate.temp_id}”的 label 已从"
                f"“{candidate.name}”字段级安全精炼为"
                f"“{disposition.name}”；definition、证据与来源绑定"
                "保持不变。"
            )
        if disposition.action in {
            "trim_definition_keep_claim",
            "repair_label_and_trim_definition_keep_claim",
        }:
            warnings.append(
                f"候选“{candidate.temp_id}”（{candidate.name}）"
                "的 definition 已按完整源句安全裁剪；"
                "label、证据与来源绑定保持不变。"
            )
        candidate = candidate.model_copy(
            update={
                "name": disposition.name,
                "definition": disposition.definition,
            }
        )
        name = candidate.name
        key = normalized_key(name)
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
    support_unit_ids = list(
        dict.fromkeys(
            [
                *branch.unit_ids,
                *state.get("seed_source_unit_ids", []),
            ]
        )
    )
    topic_index = next(
        (
            index
            for index, node in enumerate(nodes)
            if node.role == "branch_topic"
            and normalized_key(node.name) == normalized_key(branch.label)
        ),
        None,
    )
    if topic_index is None:
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
                support_unit_ids=support_unit_ids,
            )
        )
    else:
        topic = nodes[topic_index]
        nodes[topic_index] = topic.model_copy(
            update={
                "branch_id": branch.id,
                "support_unit_ids": sorted(
                    {
                        *topic.support_unit_ids,
                        *support_unit_ids,
                    }
                ),
            }
        )
    return {"nodes": nodes}


def _candidate_unit_ids(candidate: NodeCandidateIn) -> set[str]:
    return {
        *candidate.support_unit_ids,
        *[
            item.unit_id or item.chunk_id
            for item in candidate.evidence
            if item.unit_id or item.chunk_id
        ],
    }


def _plan_seed_node_routes(
    planning_unit_ids: list[str],
    seed_nodes: list[NodeCandidateIn],
    seed_unit_projection: dict[str, str],
) -> tuple[list[str | None], set[str], Counter[str]]:
    """Assign each seed node to one planning unit in stable source order."""

    source_order = {
        unit_id: index
        for index, unit_id in enumerate(planning_unit_ids)
    }
    valid_ids = set(source_order)
    owners: list[str | None] = []
    seeded_planning_ids: set[str] = set()
    owner_counts: Counter[str] = Counter()
    for candidate in seed_nodes:
        projected_ids = {
            projected_id
            for unit_id in _candidate_unit_ids(candidate)
            if (
                projected_id := seed_unit_projection.get(
                    unit_id,
                    unit_id,
                )
            )
            in valid_ids
        }
        seeded_planning_ids.update(projected_ids)
        owner = (
            min(
                projected_ids,
                key=lambda unit_id: (
                    source_order[unit_id],
                    unit_id,
                ),
            )
            if projected_ids
            else None
        )
        owners.append(owner)
        if owner is not None:
            owner_counts[owner] += 1
    return owners, seeded_planning_ids, owner_counts


def _support_mapping_evidence(
    parent: NodeCandidateIn,
    child: NodeCandidateIn,
) -> list[EvidenceRef]:
    shared = sorted(_candidate_unit_ids(parent) & _candidate_unit_ids(child))
    if not shared:
        return []
    shared_set = set(shared)
    direct = [
        item
        for item in child.evidence
        if (item.unit_id or item.chunk_id) in shared_set
    ]
    if direct:
        return _dedupe_evidence(direct)[:4]
    return [
        EvidenceRef(
            unit_id=unit_id,
            excerpt=f"结构支持映射：{parent.name} → {child.name}",
        )
        for unit_id in shared[:4]
    ]


async def _local_parent_retriever(state: BranchTeamState) -> dict:
    branch = state["branch"]
    nodes = state.get("nodes", [])
    parent_candidates: list[ParentCandidateIn] = []
    topic = next(
        (
            node
            for node in nodes
            if normalized_key(node.name) == normalized_key(branch.label)
            and node.role == "branch_topic"
        ),
        None,
    )
    if topic is None:
        return {"parent_candidates": []}
    for node in nodes:
        if node.temp_id == topic.temp_id:
            continue
        edge_evidence = _support_mapping_evidence(topic, node)
        parent_candidates.append(
            ParentCandidateIn(
                parent=topic.temp_id,
                child=node.temp_id,
                score=0.76 if node.origin == "explicit" else 0.68,
                classification="direct_parent",
                section_prior=0.88,
                semantic_score=0.62,
                evidence_support=0.9 if edge_evidence else 0,
                granularity_fit=0.72,
                evidence=edge_evidence,
            )
        )
    return {"parent_candidates": parent_candidates}


async def _local_verifier(state: BranchTeamState) -> dict:
    branch = state["branch"]
    nodes = []
    warnings = list(state.get("warnings", []))
    valid_units = {
        *branch.unit_ids,
        *state.get("seed_source_unit_ids", []),
    }
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
    seed_nodes: list[NodeCandidateIn] | None = None,
    seed_unit_projection: dict[str, str] | None = None,
) -> list[BranchTeamResult]:
    unit_by_id = {unit.id: unit for unit in units}
    chunk_by_id = {chunk.id: chunk for chunk in chunks}
    seed_nodes = list(seed_nodes or [])
    seed_unit_projection = dict(seed_unit_projection or {})
    (
        seed_node_owners,
        seeded_planning_ids,
        _seed_owner_counts,
    ) = _plan_seed_node_routes(
        [unit.id for unit in units],
        seed_nodes,
        seed_unit_projection,
    )
    routed_seed_nodes = list(zip(seed_nodes, seed_node_owners))
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
            branch_unit_ids = set(branch.unit_ids)
            branch_seed_source_ids = {
                unit_id
                for candidate, owner in routed_seed_nodes
                if owner in branch_unit_ids
                for unit_id in _candidate_unit_ids(candidate)
            }
            branch_seed_nodes = [
                candidate
                for candidate, owner in routed_seed_nodes
                if owner in branch_unit_ids
            ]
            seeded_unit_ids = seeded_planning_ids & branch_unit_ids
            with model_call_scope(
                branch_id=branch.id,
                input_unit_ids=tuple(branch.unit_ids),
            ):
                state = await team.ainvoke(
                    {
                        "branch": branch,
                        "units": branch_units,
                        "chunks": branch_chunks,
                        "runtime": runtime,
                        "seed_nodes": branch_seed_nodes,
                        "seed_source_unit_ids": sorted(
                            branch_seed_source_ids
                        ),
                        "seeded_unit_ids": sorted(seeded_unit_ids),
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
    exact: list[NodeCandidateIn] = []
    exact_index: dict[str, int] = {}
    for candidate in candidates:
        index = exact_index.get(candidate.temp_id)
        if index is None:
            exact_index[candidate.temp_id] = len(exact)
            exact.append(candidate)
        else:
            exact[index] = _resolve_same_temp_id(
                exact[index],
                candidate,
            )

    structural: list[NodeCandidateIn] = []
    structural_index: dict[tuple[str, ...], int] = {}
    semantic_candidates: list[NodeCandidateIn] = []
    for candidate in exact:
        if not (
            candidate.is_root_candidate
            or candidate.role == "branch_topic"
        ):
            semantic_candidates.append(candidate)
            continue
        if candidate.role == "branch_topic":
            key = (
                "branch_topic",
                candidate.branch_id or candidate.temp_id,
                normalized_key(candidate.name),
            )
        else:
            key = ("root", candidate.temp_id)
        index = structural_index.get(key)
        if index is None:
            structural_index[key] = len(structural)
            structural.append(candidate)
        else:
            structural[index] = _merge_node_candidates(
                structural[index],
                candidate,
            )

    ordered = sorted(
        semantic_candidates,
        key=_candidate_rank,
        reverse=True,
    )
    canonical: list[NodeCandidateIn] = list(structural)
    for candidate in ordered:
        match_index: int | None = None
        for index, existing in enumerate(canonical):
            if existing.is_root_candidate or existing.role == "branch_topic":
                continue
            if candidate.temp_id == existing.temp_id:
                match_index = index
                break
            if candidate.branch_id != existing.branch_id:
                continue
            if are_mergeable_exact_duplicates(candidate, existing):
                match_index = index
                break
        if match_index is None:
            canonical.append(candidate)
            continue
        canonical[match_index] = _merge_node_candidates(
            canonical[match_index],
            candidate,
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
                edge_evidence = _support_mapping_evidence(parent_topic, topic)
                result.append(
                    ParentCandidateIn(
                        parent=parent_topic.temp_id,
                        child=topic.temp_id,
                        score=0.92,
                        classification="direct_parent",
                        section_prior=0.95,
                        semantic_score=0.8,
                        verifier_score=0.82,
                        evidence_support=0.88 if edge_evidence else 0,
                        granularity_fit=0.9,
                        evidence=edge_evidence,
                    )
                )
        else:
            for root in roots:
                edge_evidence = _support_mapping_evidence(root, topic)
                result.append(
                    ParentCandidateIn(
                        parent=root.temp_id,
                        child=topic.temp_id,
                        score=0.95,
                        classification="direct_parent",
                        section_prior=0.96,
                        semantic_score=0.86,
                        verifier_score=0.86,
                        evidence_support=0.9 if edge_evidence else 0,
                        granularity_fit=0.94,
                        evidence=edge_evidence,
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
            edge_evidence = _support_mapping_evidence(topic, node)
            result.append(
                ParentCandidateIn(
                    parent=topic.temp_id,
                    child=node.temp_id,
                    score=0.82 if node.origin == "explicit" else 0.76,
                    classification="direct_parent",
                    section_prior=0.92,
                    semantic_score=0.66,
                    verifier_score=0.72,
                    evidence_support=0.9 if edge_evidence else 0,
                    granularity_fit=0.78,
                    evidence=edge_evidence,
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
    # Coverage audit is an accounting/review boundary.  It must not convert
    # raw OCR, captions, or an uncovered source section into a publishable
    # graph node merely to improve a coverage metric.
    del branch_plans
    unit_by_id = {unit.id: unit for unit in units}
    covered: set[str] = set()
    for candidate in candidates:
        if candidate.origin != "explicit":
            continue
        covered.update(
            unit_id
            for item in candidate.evidence
            if (unit_id := item.unit_id or item.chunk_id) in unit_by_id
            and _evidence_matches_unit(item, unit_by_id[unit_id])
        )

    updated_units: list[ContentUnit] = []
    warnings: list[str] = []
    for unit in units:
        if unit.status == "rejected":
            updated_units.append(unit)
            continue
        if unit.id in covered:
            updated_units.append(unit.model_copy(update={"status": "covered"}))
            continue
        if (
            unit.kind == "visual"
            and unit.visual_action == "attach_as_media"
        ):
            updated_units.append(unit.model_copy(update={"status": "deferred"}))
            warnings.append(
                f"未覆盖视觉单元 {unit.id} 标记为 attach_as_media，"
                "没有可融合的附近文字节点，已转人工复核而不补建独立节点。"
            )
            continue
        updated_units.append(unit.model_copy(update={"status": "deferred"}))
        source_text = unit.text or unit.summary or unit.ocr_text
        if re.search(
            r"\[(?:上文衔接|continued|continuation)\]",
            source_text,
            re.IGNORECASE,
        ):
            warnings.append(
                f"未覆盖内容单元 {unit.id} 含上下文拼接标记，"
                "未通过内容资格门，已转人工复核且不补建节点。"
            )
        else:
            warnings.append(
                f"未覆盖内容单元 {unit.id} 已转人工复核；"
                "Coverage Audit 不会用原始章节标题、OCR 残片或媒体描述补建节点。"
            )
    return updated_units, [], warnings


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


def _parent_verification_scope_unit_ids(
    request: _ParentVerificationRequest,
    node_by_id: dict[str, NormalizedNode],
) -> tuple[str, ...]:
    unit_ids = set(request.child.support_unit_ids)
    unit_ids.update(
        unit_id
        for evidence_ref in request.child.evidence
        if (unit_id := evidence_ref.unit_id or evidence_ref.chunk_id)
    )
    for candidate in request.candidates:
        parent = node_by_id[candidate.parent_id]
        unit_ids.update(parent.support_unit_ids)
        unit_ids.update(
            unit_id
            for evidence_ref in parent.evidence
            if (unit_id := evidence_ref.unit_id or evidence_ref.chunk_id)
        )
        unit_ids.update(
            unit_id
            for evidence_ref in candidate.evidence
            if (unit_id := evidence_ref.unit_id or evidence_ref.chunk_id)
        )
    return tuple(sorted(unit_ids))


def _parent_verification_prompt_item(
    request: _ParentVerificationRequest,
    node_by_id: dict[str, NormalizedNode],
    prior_votes: dict[tuple[str, str], list[ModelVote]] | None,
) -> dict[str, Any]:
    child = request.child
    return {
        "child": child.model_dump(mode="json"),
        "evidence_scope_unit_ids": list(
            _parent_verification_scope_unit_ids(request, node_by_id)
        ),
        "candidates": [
            {
                "parent": node_by_id[candidate.parent_id].model_dump(
                    mode="json"
                ),
                "candidate": candidate.model_dump(mode="json"),
                "prior_votes": [
                    vote.model_dump(mode="json")
                    for vote in (prior_votes or {}).get(
                        (candidate.parent_id, child.id),
                        [],
                    )
                ],
            }
            for candidate in request.candidates
        ],
    }


def _fallback_parent_votes(
    request: _ParentVerificationRequest,
    node_by_id: dict[str, NormalizedNode],
) -> dict[str, ModelVote]:
    return {
        candidate.parent_id: _heuristic_parent_vote(
            node_by_id[candidate.parent_id],
            request.child,
            candidate,
        )
        for candidate in request.candidates
    }


async def _batch_parent_votes(
    runtime: RoleRuntime,
    requests: list[_ParentVerificationRequest],
    node_by_id: dict[str, NormalizedNode],
    *,
    system_prompt: str = PARENT_VERIFIER_PROMPT,
    prior_votes: dict[tuple[str, str], list[ModelVote]] | None = None,
    actor_suffix: str = "",
) -> _ParentVoteBatchResult:
    active_requests = [
        request for request in requests if request.candidates
    ]
    requested_count = len(active_requests)
    fallbacks = {
        request.child.id: _fallback_parent_votes(request, node_by_id)
        for request in active_requests
    }
    if not active_requests:
        return _ParentVoteBatchResult(
            votes=fallbacks,
            errors={},
            warnings=[],
            stats=VerifierRoleRunStats(),
        )
    if not runtime.available or not runtime.client:
        return _ParentVoteBatchResult(
            votes=fallbacks,
            errors={},
            warnings=[],
            stats=VerifierRoleRunStats(
                requested_batches=1,
                fallback_batches=1,
                requested_children=requested_count,
                fallback_children=requested_count,
            ),
        )

    prompt_payload = {
        "children": [
            _parent_verification_prompt_item(
                request,
                node_by_id,
                prior_votes,
            )
            for request in active_requests
        ],
    }
    scope_unit_ids = sorted(
        {
            unit_id
            for request in active_requests
            for unit_id in _parent_verification_scope_unit_ids(
                request,
                node_by_id,
            )
        }
    )
    branch_ids = {
        request.child.branch_id
        for request in active_requests
        if request.child.branch_id
    }
    scope_kwargs: dict[str, Any] = {
        "input_unit_ids": tuple(scope_unit_ids),
    }
    if len(branch_ids) == 1:
        scope_kwargs["branch_id"] = next(iter(branch_ids))

    try:
        with model_call_scope(**scope_kwargs):
            answer_token_budget = max(
                1600,
                sum(
                    len(request.candidates)
                    for request in active_requests
                )
                * 550,
            )
            payload = await runtime.client.complete_json(
                model=runtime.model,
                system_prompt=system_prompt,
                user_prompt=json.dumps(
                    prompt_payload,
                    ensure_ascii=False,
                ),
                **_structured_json_call_kwargs(
                    runtime,
                    answer_token_budget,
                    timeout_seconds=VERIFIER_JSON_TIMEOUT_SECONDS,
                ),
            )
    except ModelProviderError:
        errors = {
            request.child.id: "模型调用失败"
            for request in active_requests
        }
        return _ParentVoteBatchResult(
            votes=fallbacks,
            errors=errors,
            warnings=[],
            stats=VerifierRoleRunStats(
                requested_batches=1,
                attempted_batches=1,
                fallback_batches=1,
                requested_children=requested_count,
                fallback_children=requested_count,
            ),
        )

    try:
        output = ParentVerificationBatchOutput.model_validate(payload)
    except ValueError:
        errors = {
            request.child.id: "返回顶层结构无效"
            for request in active_requests
        }
        return _ParentVoteBatchResult(
            votes=fallbacks,
            errors=errors,
            warnings=[],
            stats=VerifierRoleRunStats(
                requested_batches=1,
                attempted_batches=1,
                fallback_batches=1,
                requested_children=requested_count,
                fallback_children=requested_count,
            ),
        )

    expected = {
        request.child.id: request for request in active_requests
    }
    accepted: dict[str, dict[str, ModelVote]] = {}
    errors: dict[str, str] = {}
    warnings: list[str] = []
    seen_child_ids: set[str] = set()
    actor = runtime.provider + actor_suffix

    for raw_child in output.children:
        child_id = (
            raw_child.get("child_id")
            if isinstance(raw_child, dict)
            and isinstance(raw_child.get("child_id"), str)
            else None
        )
        if child_id is None:
            warnings.append(
                "父候选批量校验返回了无法识别的 child 项，已忽略。"
            )
            continue
        if child_id not in expected:
            warnings.append(
                f"父候选批量校验返回了未知 child_id={child_id}，已忽略。"
            )
            continue
        if child_id in seen_child_ids:
            accepted.pop(child_id, None)
            errors[child_id] = f"返回了重复 child_id={child_id}"
            continue
        seen_child_ids.add(child_id)
        try:
            child_output = ParentVerificationChildOutput.model_validate(
                raw_child
            )
        except ValueError:
            errors[child_id] = "返回 child 结构无效"
            continue

        expected_parent_ids = {
            candidate.parent_id
            for candidate in expected[child_id].candidates
        }
        returned_parent_ids = [
            evaluation.parent_id
            for evaluation in child_output.evaluations
        ]
        returned_parent_id_set = set(returned_parent_ids)
        unknown = returned_parent_id_set - expected_parent_ids
        missing = expected_parent_ids - returned_parent_id_set
        if unknown:
            errors[child_id] = (
                "返回了未知 parent_id="
                + ",".join(sorted(unknown))
            )
            continue
        if missing:
            errors[child_id] = (
                "遗漏 parent_id="
                + ",".join(sorted(missing))
            )
            continue
        if len(returned_parent_id_set) != len(returned_parent_ids):
            errors[child_id] = "返回了重复 parent_id"
            continue
        accepted[child_id] = {
            evaluation.parent_id: ModelVote(
                actor=actor,
                model=runtime.model,
                classification=evaluation.classification,
                score=evaluation.verifier_score,
                reason=evaluation.reason,
            )
            for evaluation in child_output.evaluations
        }

    for child_id in expected:
        if child_id not in accepted and child_id not in errors:
            errors[child_id] = f"遗漏 child_id={child_id}"

    votes = dict(fallbacks)
    votes.update(accepted)
    succeeded_count = len(accepted)
    return _ParentVoteBatchResult(
        votes=votes,
        errors=errors,
        warnings=warnings,
        stats=VerifierRoleRunStats(
            requested_batches=1,
            attempted_batches=1,
            succeeded_batches=int(succeeded_count > 0),
            fallback_batches=int(succeeded_count < requested_count),
            requested_children=requested_count,
            succeeded_children=succeeded_count,
            fallback_children=requested_count - succeeded_count,
        ),
    )


async def _run_parent_vote_batches(
    runtime: RoleRuntime,
    requests: list[_ParentVerificationRequest],
    node_by_id: dict[str, NormalizedNode],
    semaphore: asyncio.Semaphore,
    *,
    system_prompt: str = PARENT_VERIFIER_PROMPT,
    prior_votes: dict[tuple[str, str], list[ModelVote]] | None = None,
    actor_suffix: str = "",
) -> _ParentVoteBatchResult:
    async def run_batch(
        batch: list[_ParentVerificationRequest],
    ) -> _ParentVoteBatchResult:
        async with semaphore:
            return await _batch_parent_votes(
                runtime,
                batch,
                node_by_id,
                system_prompt=system_prompt,
                prior_votes=prior_votes,
                actor_suffix=actor_suffix,
            )

    active_requests = [
        request for request in requests if request.candidates
    ]
    batches = [
        active_requests[index : index + VERIFIER_CHILD_BATCH_SIZE]
        for index in range(
            0,
            len(active_requests),
            VERIFIER_CHILD_BATCH_SIZE,
        )
    ]
    if not batches:
        return _ParentVoteBatchResult(
            votes={},
            errors={},
            warnings=[],
            stats=VerifierRoleRunStats(),
        )
    results = await asyncio.gather(
        *(run_batch(batch) for batch in batches)
    )
    return _ParentVoteBatchResult(
        votes={
            child_id: votes
            for result in results
            for child_id, votes in result.votes.items()
        },
        errors={
            child_id: error
            for result in results
            for child_id, error in result.errors.items()
        },
        warnings=[
            warning
            for result in results
            for warning in result.warnings
        ],
        stats=_sum_verifier_role_stats(
            [result.stats for result in results]
        ),
    )


def _sum_verifier_role_stats(
    items: list[VerifierRoleRunStats],
) -> VerifierRoleRunStats:
    return VerifierRoleRunStats(
        requested_batches=sum(item.requested_batches for item in items),
        attempted_batches=sum(item.attempted_batches for item in items),
        succeeded_batches=sum(item.succeeded_batches for item in items),
        fallback_batches=sum(item.fallback_batches for item in items),
        requested_children=sum(item.requested_children for item in items),
        succeeded_children=sum(item.succeeded_children for item in items),
        fallback_children=sum(item.fallback_children for item in items),
    )


def _unavailable_verifier_role_stats(
    requests: list[_ParentVerificationRequest],
) -> VerifierRoleRunStats:
    requested_children = sum(
        bool(request.candidates) for request in requests
    )
    requested_batches = (
        requested_children + VERIFIER_CHILD_BATCH_SIZE - 1
    ) // VERIFIER_CHILD_BATCH_SIZE
    return VerifierRoleRunStats(
        requested_batches=requested_batches,
        fallback_batches=requested_batches,
        requested_children=requested_children,
        fallback_children=requested_children,
    )


def _consensus_vote(votes: list[ModelVote]) -> ModelVote:
    if not votes:
        return ModelVote(
            actor="deterministic-consensus",
            classification="uncertain",
            score=0,
            reason="没有可用校验票。",
        )
    classifications = {vote.classification for vote in votes}
    if len(classifications) == 1:
        return ModelVote(
            actor="vote-consensus",
            classification=votes[0].classification,
            score=round(
                sum(vote.score for vote in votes) / len(votes),
                4,
            ),
            reason="独立校验票结论一致。",
        )
    return ModelVote(
        actor="deterministic-consensus",
        classification="uncertain",
        score=round(min(vote.score for vote in votes), 4),
        reason="独立校验票冲突且没有可靠仲裁结论。",
    )


def _apply_verified_vote(
    candidate: NormalizedParentCandidate,
    final_vote: ModelVote,
) -> NormalizedParentCandidate:
    direct = final_vote.classification == "direct_parent"
    combined = (
        0.45 * candidate.score + 0.55 * final_vote.score
        if direct
        else 0.35 * candidate.score + 0.25 * final_vote.score
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


def _requires_model_parent_verification(
    child: NormalizedNode,
    candidates: list[NormalizedParentCandidate],
    node_by_id: dict[str, NormalizedNode],
    *,
    root_candidate_count: int,
) -> bool:
    if not candidates:
        return False
    if child.origin in {"abstractive", "structural"}:
        return True

    top = candidates[0]
    if (
        top.score < VERIFIER_DIRECT_EDGE_MIN_SCORE
        or top.classification != "direct_parent"
    ):
        return True
    if (
        len(candidates) > 1
        and top.score - candidates[1].score
        < VERIFIER_COMPETITIVE_MARGIN
    ):
        return True

    for candidate in candidates:
        parent = node_by_id[candidate.parent_id]
        if candidate.classification != "direct_parent":
            return True
        if (
            parent.branch_id
            and child.branch_id
            and parent.branch_id != child.branch_id
        ):
            return True
        if (
            parent.origin in {"abstractive", "structural"}
            and parent.role != "branch_topic"
        ):
            return True
        if parent.is_root_candidate and root_candidate_count > 1:
            return True
    return False


async def verify_parent_candidates(
    graph: NormalizedGraph,
    *,
    verifier: RoleRuntime,
    second_verifier: RoleRuntime | None,
    arbiter: RoleRuntime | None,
    mode: RunMode,
    concurrency: int = 8,
) -> ParentVerificationResult:
    node_by_id = {node.id: node for node in graph.nodes}
    root_candidate_count = sum(
        node.is_root_candidate for node in graph.nodes
    )
    by_child: dict[str, list[NormalizedParentCandidate]] = defaultdict(list)
    for candidate in graph.parent_candidates:
        by_child[candidate.child_id].append(candidate)
    semaphore = asyncio.Semaphore(max(concurrency, 1))
    child_ids = sorted(by_child)
    ranked_by_child: dict[
        str,
        list[NormalizedParentCandidate],
    ] = {}
    model_targets_by_child: dict[
        str,
        list[NormalizedParentCandidate],
    ] = {}
    votes_by_pair: dict[tuple[str, str], list[ModelVote]] = {}
    warnings: list[str] = []

    for child_id in child_ids:
        child = node_by_id[child_id]
        ranked = sorted(
            by_child[child_id],
            key=lambda item: (
                item.provisional,
                -item.score,
                item.parent_id,
            ),
        )
        ranked_by_child[child_id] = ranked
        eligible_model_targets = [
            item
            for item in ranked
            if not item.provisional and item.evidence
        ][:3]
        model_targets = (
            eligible_model_targets
            if _requires_model_parent_verification(
                child,
                eligible_model_targets,
                node_by_id,
                root_candidate_count=root_candidate_count,
            )
            else []
        )
        model_targets_by_child[child_id] = model_targets
        votes_by_pair.update(
            {
                (candidate.parent_id, child_id): [
                    _heuristic_parent_vote(
                        node_by_id[candidate.parent_id],
                        child,
                        candidate,
                    )
                ]
                for candidate in ranked
            }
        )

    primary_requests = [
        _ParentVerificationRequest(
            child=node_by_id[child_id],
            candidates=tuple(model_targets_by_child[child_id]),
        )
        for child_id in child_ids
        if model_targets_by_child[child_id]
    ]
    primary_result = await _run_parent_vote_batches(
        verifier,
        primary_requests,
        node_by_id,
        semaphore,
    )
    warnings.extend(primary_result.warnings)
    for request in primary_requests:
        child = request.child
        first_error = primary_result.errors.get(child.id)
        if first_error:
            warnings.append(
                f"子节点“{child.name}”父候选批量校验失败，"
                f"已使用确定性校验：{first_error}"
            )
        for parent_id, vote in primary_result.votes.get(
            child.id,
            {},
        ).items():
            votes_by_pair[(parent_id, child.id)] = [vote]

    high_risk_child_ids = [
        child_id
        for child_id in child_ids
        if (
            mode == "precision"
            and (
                node_by_id[child_id].origin
                in {"abstractive", "structural"}
                or len(model_targets_by_child[child_id]) > 1
                or any(
                    node_by_id[item.parent_id].is_root_candidate
                    for item in model_targets_by_child[child_id]
                )
            )
        )
        and model_targets_by_child[child_id]
    ]
    secondary_requests = [
        _ParentVerificationRequest(
            child=node_by_id[child_id],
            candidates=tuple(model_targets_by_child[child_id][:2]),
        )
        for child_id in high_risk_child_ids
    ]
    secondary_stats = VerifierRoleRunStats()
    if (
        secondary_requests
        and second_verifier is not None
        and second_verifier.available
        and second_verifier.client is not None
    ):
        secondary_result = await _run_parent_vote_batches(
            second_verifier,
            secondary_requests,
            node_by_id,
            semaphore,
        )
        secondary_stats = secondary_result.stats
        warnings.extend(secondary_result.warnings)
        for request in secondary_requests:
            child = request.child
            second_error = secondary_result.errors.get(child.id)
            if second_error:
                warnings.append(
                    f"子节点“{child.name}”第二批量校验失败，"
                    f"已保留首轮结论：{second_error}"
                )
                continue
            for parent_id, vote in secondary_result.votes.get(
                child.id,
                {},
            ).items():
                votes_by_pair[(parent_id, child.id)].append(vote)
    elif secondary_requests:
        secondary_stats = _unavailable_verifier_role_stats(
            secondary_requests
        )

    arbiter_requests: list[_ParentVerificationRequest] = []
    for request in secondary_requests:
        disputed = [
            candidate
            for candidate in request.candidates
            if len(
                {
                    vote.classification
                    for vote in votes_by_pair[
                        (candidate.parent_id, request.child.id)
                    ]
                }
            )
            > 1
        ]
        if disputed:
            arbiter_requests.append(
                _ParentVerificationRequest(
                    child=request.child,
                    candidates=tuple(disputed),
                )
            )

    arbiter_stats = VerifierRoleRunStats()
    if (
        arbiter_requests
        and arbiter is not None
        and arbiter.available
        and arbiter.client is not None
    ):
        arbiter_result = await _run_parent_vote_batches(
            arbiter,
            arbiter_requests,
            node_by_id,
            semaphore,
            system_prompt=ARBITER_PROMPT,
            prior_votes=votes_by_pair,
            actor_suffix="-arbiter",
        )
        arbiter_stats = arbiter_result.stats
        warnings.extend(arbiter_result.warnings)
        for request in arbiter_requests:
            child = request.child
            arbiter_error = arbiter_result.errors.get(child.id)
            if arbiter_error:
                warnings.append(
                    f"子节点“{child.name}”批量仲裁失败，"
                    f"冲突边已标记 uncertain：{arbiter_error}"
                )
                continue
            for parent_id, vote in arbiter_result.votes.get(
                child.id,
                {},
            ).items():
                votes_by_pair[(parent_id, child.id)].append(vote)
    elif arbiter_requests:
        arbiter_stats = _unavailable_verifier_role_stats(
            arbiter_requests
        )
        for request in arbiter_requests:
            warnings.append(
                f"子节点“{request.child.name}”需要仲裁但仲裁器不可用，"
                "冲突边已标记 uncertain。"
            )

    verified: list[NormalizedParentCandidate] = []
    for child_id in child_ids:
        for candidate in ranked_by_child[child_id]:
            pair = (candidate.parent_id, child_id)
            votes = votes_by_pair[pair]
            if votes[-1].actor.endswith("-arbiter"):
                final_vote = votes[-1]
            elif len(votes) > 1:
                final_vote = _consensus_vote(votes)
                votes.append(final_vote)
            else:
                final_vote = votes[0]
            verified.append(
                _apply_verified_vote(candidate, final_vote)
            )

    verified_by_child: dict[
        str,
        list[NormalizedParentCandidate],
    ] = defaultdict(list)
    for candidate in verified:
        verified_by_child[candidate.child_id].append(candidate)
    repaired_verified: list[NormalizedParentCandidate] = []
    for child_id in child_ids:
        child_candidates = verified_by_child[child_id]
        selectable = any(
            candidate.provisional
            or (
                candidate.classification == "direct_parent"
                and candidate.evidence
            )
            for candidate in child_candidates
        )
        if not selectable and child_candidates:
            fallback = max(
                child_candidates,
                key=lambda item: (item.score, item.parent_id),
            )
            child_candidates = [
                item.model_copy(update={"provisional": True})
                if item is fallback
                else item
                for item in child_candidates
            ]
            warnings.append(
                f"子节点“{node_by_id[child_id].name}”校验后没有正式父边，"
                "已保留最高分候选为 provisional 并进入复核。"
            )
        repaired_verified.extend(child_candidates)
    verified = repaired_verified

    stats = ParentVerificationRunStats(
        primary=primary_result.stats,
        secondary=secondary_stats,
        arbiter=arbiter_stats,
    )
    if primary_requests and not verifier.available:
        warnings.append("独立父边校验模型不可用，已使用确定性校验器。")
    if secondary_requests and mode == "precision" and (
        second_verifier is None or not second_verifier.available
    ):
        warnings.append("高精档第二校验器不可用，相关风险项将保留人工复核。")
    return ParentVerificationResult(
        graph=graph.model_copy(update={"parent_candidates": verified}),
        votes=votes_by_pair,
        warnings=warnings,
        stats=stats,
    )


def coverage_statistics(
    units: list[ContentUnit],
    nodes: list[NormalizedNode],
) -> tuple[set[str], float, dict[str, float]]:
    unit_by_id = {unit.id: unit for unit in units}
    covered: set[str] = set()
    for node in nodes:
        structural_node = (
            node.is_root_candidate
            or node.role in {"root_topic", "branch_topic", "structural"}
            or node.type in {"root_topic", "branch_topic", "structural"}
            or node.origin == "structural"
        )
        if not is_publishable_label(
            node.name,
            allow_root=node.is_root_candidate,
            allow_section_label=structural_node,
            allow_formula_label=bool(
                node.role == "formula"
                or node.type == "formula"
            ),
        ):
            continue
        if (
            node.origin == "explicit"
            and not structural_node
            and definition_quality_issues(node.definition)
        ):
            continue
        explicit_evidence_unit_ids = set(
            node.explicit_evidence_unit_ids
        )
        covered.update(
            unit_id
            for item in node.evidence
            if (unit_id := item.unit_id or item.chunk_id) in unit_by_id
            and (
                node.origin == "explicit"
                or unit_id in explicit_evidence_unit_ids
            )
            and _evidence_matches_unit(item, unit_by_id[unit_id])
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
