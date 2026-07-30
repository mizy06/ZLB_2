from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .agents import (
    RoleRuntime,
    _evidence_excerpt_is_specific,
    _normalized_evidence_text,
)
from .architecture_schemas import ContentUnit
from .claim_fidelity import claim_fidelity_issues
from .mindmap_engine.schemas import (
    EvidenceRef,
    NodeCandidateIn,
    RenderResponse,
    RenderedPage,
)
from .mindmap_engine.normalize import candidate_field_disposition
from .model_provider import ModelProviderError, model_call_scope
from .pdf_math_geometry import _candidate_issues
from .schemas import ParsedDocument, SourceBlock


PAGE_KNOWLEDGE_SCHEMA_VERSION = "page-knowledge-v9"
PAGE_KNOWLEDGE_ROLE = "pdf_page_knowledge_extractor"
PAGE_KNOWLEDGE_TIMEOUT_SECONDS = 90.0
PAGE_KNOWLEDGE_MAX_OUTPUT_TOKENS = 3600
PAGE_KNOWLEDGE_MAX_COMPLETION_TOKENS = 5000
PAGE_KNOWLEDGE_THINKING_BUDGET = 1024
PDF_KNOWLEDGE_DEGRADED = "[pdf_knowledge_degraded:page_failure]"
PDF_LAYOUT_NODES_FALLBACK = "[pdf_layout_nodes_fallback]"
PageKnowledgeExtractionProfile = Literal[
    "direct",
    "layout_nodes",
    "direct_layout_fallback",
]
_PRIVATE_USE_OR_REPLACEMENT = re.compile(r"[\ue000-\uf8ff\ufffd]")
_MARKDOWN_FENCE = re.compile(r"```")
_TEXT_POWER = re.compile(r"10\^\s*(-?\d+)")
_LATEX_POWER = re.compile(r"10\^\{\s*(-?\d+)\s*\}")
_LATEX_DECORATION_MARKS = (
    (re.compile(r"\\hat(?![A-Za-z])"), "\N{COMBINING CIRCUMFLEX ACCENT}"),
    (
        re.compile(r"\\vec(?![A-Za-z])"),
        "\N{COMBINING RIGHT ARROW ABOVE}",
    ),
    (re.compile(r"\\bar(?![A-Za-z])"), "\N{COMBINING OVERLINE}"),
)
_CANONICAL_DECORATION_MARKS = frozenset(
    mark for _, mark in _LATEX_DECORATION_MARKS
)
_DECORATION_MARK_ALIASES = {
    "\N{COMBINING MACRON}": "\N{COMBINING OVERLINE}",
}
_FORMULA_RELATION = re.compile(r"[=≈≤≥<>]")
_FORMULA_AUDIT_RELATION = re.compile(r"[=≈≤≥<>→⇒]")
_COMPLEX_MATH_SIGNAL = re.compile(
    r"(?:"
    r"10\^\s*-?\d+"
    r"|[/∫∑Σ√]"
    r"|[A-Za-zΑ-ω]\s*[_^]\s*\w+"
    r"|[+*×]"
    r")"
)
_STRONG_FORMULA_SIGNAL = re.compile(
    r"(?:10\^\s*-?\d+|[/∫∑Σ√]|[+*×])"
)
_SUBSCRIPT_FORMULA_SIGNAL = re.compile(
    r"[A-Za-zΑ-ω]\s*[_^]\s*\w+"
)
_FORMULA_PROSE_CONNECTOR = re.compile(r"(?:当|时|则|或|以及)")
_FORMULA_SEPARATOR = re.compile(r"[,，;；:：。]")
_SUPERSCRIPT_SEQUENCE = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼]+")
_SUBSCRIPT_SEQUENCE = re.compile(r"[₀₁₂₃₄₅₆₇₈₉₊₋₌]+")
_SUPERSCRIPT_TRANSLATION = str.maketrans(
    "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼",
    "0123456789+-=",
)
_SUBSCRIPT_TRANSLATION = str.maketrans(
    "₀₁₂₃₄₅₆₇₈₉₊₋₌",
    "0123456789+-=",
)
_PRIME_TRANSLATION = str.maketrans(
    {
        "′": "'",
        "″": "''",
        "‴": "'''",
        "⁗": "''''",
    }
)
_FORMULA_GROUPING = re.compile(r"[\(\)\[\]\{\}_^·]")
_SIMPLE_SCRIPT_PAIR = re.compile(
    r"(?P<base>[A-Za-zΑ-ω])(?:"
    r"\^(?P<sup_first>[-+]?[A-Za-zΑ-ω0-9']+)"
    r"_(?P<sub_second>[-+]?[A-Za-zΑ-ω0-9']+)"
    r"|_(?P<sub_first>[-+]?[A-Za-zΑ-ω0-9']+)"
    r"\^(?P<sup_second>[-+]?[A-Za-zΑ-ω0-9']+)"
    r")"
)
_FORMULA_LAYOUT_ANNOTATION = re.compile(
    r"[（(](?:直角坐标|笛卡尔坐标|球极|球坐标|极坐标)[）)]"
)
_DIMENSIONLESS_RATIO = re.compile(
    r"[A-Za-zΑ-ωΔ]+\d*/[A-Za-zΑ-ωΔ]+\d*"
)

PDF_PAGE_KNOWLEDGE_PROMPT = """你是 PDF 单页知识节点抽取器。只依据当前页面图像提取可独立发布、可由页面原文直接支持的原子知识节点。

只输出一个 JSON 对象：
{
  "page": 1,
  "complete": true,
  "confidence": 0.0,
  "heading": "页面所属章节或标题；无法确认则为空字符串",
  "has_knowledge": true,
  "no_knowledge_reason": "",
  "discarded_temp_ids": [],
  "nodes": [
    {
      "temp_id": "本页内唯一短 ID",
      "name": "自足、简洁的知识点名称",
      "type": "concept|definition|principle|formula|result|example|step|warning|other",
      "role": "definition|principle|formula|example|step|warning|other",
      "definition": "只写页面证据直接支持的一个原子事实，不推导、不补充",
      "evidence_text": "从当前页面逐字抄录、足以支持该节点的最小连续证据",
      "formula_text": "若节点含公式，写单行 Unicode canonical 公式，否则为空字符串",
      "formula_latex": "若节点含公式，写对应 LaTeX，否则为空字符串",
      "bbox": [x, y, width, height],
      "confidence": 0.0
    }
  ]
}

规则：
1. bbox 使用 0..1 的归一化 [左, 上, 宽, 高]，例如 [0.1,0.2,0.5,0.1]；宽高不是右下角坐标，且框必须完整位于页面内并覆盖 evidence_text。
2. 每个节点只表达一个原子事实。name 必须是 2..48 个字符的单行、名词性、自足标签，不得使用章节编号、句子开头、连接词、句末标点或截断短语；不要输出章节目录、纯页码、按钮、装饰、坐标轴碎片、人物照片或空泛的“示意图”节点。
3. evidence_text 必须是页面中的连续原文，不得总结、改写或拼接不同区域。
4. definition 可以压缩表达，但数字、正负号、指数、下标、分母、单位、关系方向和因果方向必须与 evidence_text 完全一致。
5. 含复杂公式的节点必须同时输出 formula_text 与 formula_latex；formula_text 使用 ^ 表示上标、_ 表示下标。type=result 时 role 使用 other，不要输出 role=result。
6. 指数的正负号和数字必须逐字保留，不得把 10^-k 恢复为 10^k；不得遗漏公式中的下标、分母、微分项或单位。
7. formula_text 只能规范化页面实际显示的表达式，不得引入页面没有显示的变量名；evidence_text 必须连续覆盖该表达式。
8. 页面有知识但任何关键字符无法确认时，将 complete 设为 false，不要猜。
9. 页面确实没有可发布知识时，has_knowledge=false、nodes=[]，并填写 no_knowledge_reason。
10. 每页最多输出 12 个最重要的原子节点，宁可合并同一事实的重复表述，不得截断公式或证据。
11. 首次尝试时 discarded_temp_ids 必须为空。修复尝试中，只有当系统列出的坏节点属于误抽取的孤立标签、低置信碎片或无法形成连续证据的非公式关系时，才可把原 temp_id 放入 discarded_temp_ids；公式、数字、单位、定义和关键事实不得撤回。
12. 不要输出 Markdown 代码块或 JSON 之外的文字。"""

PDF_PAGE_KNOWLEDGE_PROMPT_SHA256 = hashlib.sha256(
    PDF_PAGE_KNOWLEDGE_PROMPT.encode("utf-8")
).hexdigest()


class CheckpointStore(Protocol):
    def load_checkpoint(self, run_id: str, stage: str) -> Any | None: ...

    def checkpoint(self, run_id: str, stage: str, payload: Any) -> None: ...

    def list_reusable_checkpoints(
        self,
        run_id: str,
        stage: str,
        input_hash: str,
    ) -> list[tuple[str, Any]]: ...


class PageKnowledgeNode(BaseModel):
    temp_id: str
    name: str
    type: str = "concept"
    role: Literal[
        "definition",
        "principle",
        "formula",
        "example",
        "step",
        "warning",
        "other",
    ] = "other"
    definition: str
    evidence_text: str
    formula_text: str = ""
    formula_latex: str = ""
    bbox: list[float]
    confidence: float = Field(ge=0, le=1)

    @field_validator(
        "temp_id",
        "name",
        "type",
        "definition",
        "evidence_text",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("page knowledge node fields must not be empty")
        return text

    @field_validator("formula_text", "formula_latex")
    @classmethod
    def normalize_optional_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("role", mode="before")
    @classmethod
    def normalize_result_role(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip().casefold() == "result":
            return "other"
        return value

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, value: list[float]) -> list[float]:
        if len(value) != 4:
            raise ValueError("bbox must contain four values")
        if any(not isinstance(item, (int, float)) for item in value):
            raise ValueError("bbox values must be numeric")
        x, y, width, height = (float(item) for item in value)
        if not all(math.isfinite(item) for item in (x, y, width, height)):
            raise ValueError("bbox values must be finite")
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            raise ValueError("bbox must have non-negative origin and positive size")
        if x + width > 1 + 1e-9 or y + height > 1 + 1e-9:
            right, bottom = width, height
            if (
                right <= 1 + 1e-9
                and bottom <= 1 + 1e-9
                and right > x
                and bottom > y
            ):
                width = right - x
                height = bottom - y
            else:
                raise ValueError("bbox must fit inside the normalized page")
        return [
            round(x, 6),
            round(y, 6),
            round(width, 6),
            round(height, 6),
        ]

    @model_validator(mode="after")
    def validate_formula_contract(self):
        self.formula_text = (
            self.formula_text.replace("≅", "≈").replace("≃", "≈")
        )
        self.formula_latex = re.sub(
            r"\\(?:cong|simeq)",
            r"\\approx",
            self.formula_latex,
        )
        has_text = bool(self.formula_text)
        has_latex = bool(self.formula_latex)
        if has_text != has_latex:
            raise ValueError("formula text and latex must be provided together")
        if (
            self.role == "formula"
            or self.type.strip().casefold() == "formula"
        ) and not has_text:
            raise ValueError("formula nodes require canonical text and latex")
        return self


class PageKnowledgeExtraction(BaseModel):
    page: int = Field(ge=1)
    complete: bool
    confidence: float = Field(ge=0, le=1)
    heading: str = ""
    has_knowledge: bool = True
    no_knowledge_reason: str = ""
    nodes: list[PageKnowledgeNode] = Field(
        default_factory=list,
        max_length=12,
    )

    @field_validator("heading", "no_knowledge_reason")
    @classmethod
    def normalize_page_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_knowledge_contract(self):
        if self.has_knowledge and not self.nodes:
            raise ValueError("knowledge pages require at least one node")
        if not self.has_knowledge and self.nodes:
            raise ValueError("non-knowledge pages must not contain nodes")
        if not self.has_knowledge and not self.no_knowledge_reason:
            raise ValueError("non-knowledge pages require a reason")
        return self


class _PageKnowledgeEnvelope(BaseModel):
    page: int = Field(ge=1)
    complete: bool
    confidence: float = Field(ge=0, le=1)
    heading: str = ""
    has_knowledge: bool = True
    no_knowledge_reason: str = ""
    discarded_temp_ids: list[str] = Field(
        default_factory=list,
        max_length=12,
    )
    nodes: list[Any] = Field(default_factory=list)

    @field_validator("heading", "no_knowledge_reason")
    @classmethod
    def normalize_page_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("discarded_temp_ids")
    @classmethod
    def validate_discarded_temp_ids(cls, value: list[str]) -> list[str]:
        normalized = [str(item).strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("discarded temp ids must not be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("discarded temp ids must be unique")
        return normalized


@dataclass(frozen=True)
class _PagePayloadValidation:
    envelope: _PageKnowledgeEnvelope | None
    valid_nodes: tuple[tuple[int, PageKnowledgeNode], ...]
    issues: tuple[str, ...]
    invalid_temp_ids: tuple[str, ...]
    anonymous_invalid_count: int
    invalid_issues_by_temp_id: tuple[
        tuple[str, tuple[str, ...]],
        ...,
    ]


class PdfPageKnowledgeResult(BaseModel):
    document: ParsedDocument
    extractions: list[PageKnowledgeExtraction] = Field(default_factory=list)
    content_units: list[ContentUnit] = Field(default_factory=list)
    node_candidates: list[NodeCandidateIn] = Field(default_factory=list)
    complete: bool = False
    accepted_pages: list[int] = Field(default_factory=list)
    degraded_pages: list[int] = Field(default_factory=list)
    failed_pages: list[int] = Field(default_factory=list)
    reused_pages: list[int] = Field(default_factory=list)
    called_pages: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class _LayoutAuditSummary:
    result: PdfPageKnowledgeResult
    audited_pages: tuple[int, ...] = ()
    accepted_pages: tuple[int, ...] = ()
    failed_pages: tuple[int, ...] = ()
    reused_pages: tuple[int, ...] = ()
    called_pages: tuple[int, ...] = ()
    supplemented_formula_count: int = 0


def _page_node_field_disposition(node: PageKnowledgeNode):
    return candidate_field_disposition(
        NodeCandidateIn(
            temp_id=node.temp_id,
            name=node.name,
            type=node.type,
            role=node.role,
            definition=node.definition,
            origin="explicit",
            confidence=node.confidence,
            evidence=[
                EvidenceRef(
                    excerpt=node.evidence_text,
                    page=None,
                    bbox=node.bbox,
                )
            ],
        )
    )


def _normalized_formula(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("−", "-").replace("–", "-")
    return "".join(character for character in normalized if not character.isspace())


def _script_sequence(
    match: re.Match[str],
    *,
    marker: str,
    translation: dict[int, str],
) -> str:
    return marker + match.group(0).translate(translation)


def _formula_evidence_key(value: str) -> str:
    value = _FORMULA_LAYOUT_ANNOTATION.sub("", value)
    normalized = _SUPERSCRIPT_SEQUENCE.sub(
        lambda match: _script_sequence(
            match,
            marker="^",
            translation=_SUPERSCRIPT_TRANSLATION,
        ),
        value,
    )
    normalized = _SUBSCRIPT_SEQUENCE.sub(
        lambda match: _script_sequence(
            match,
            marker="_",
            translation=_SUBSCRIPT_TRANSLATION,
        ),
        normalized,
    )
    normalized = unicodedata.normalize("NFKC", normalized)
    normalized = "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Mn"
    )
    normalized = _SIMPLE_SCRIPT_PAIR.sub(
        lambda match: (
            f"{match.group('base')}_"
            f"{match.group('sub_first') or match.group('sub_second')}"
            f"^{match.group('sup_first') or match.group('sup_second')}"
        ),
        normalized,
    )
    normalized = normalized.translate(_PRIME_TRANSLATION)
    normalized = re.sub(r"sqrt", "√", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"hbar", "ħ", normalized, flags=re.IGNORECASE)
    normalized = (
        normalized.replace("−", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("ℏ", "ħ")
        .replace("≅", "≈")
        .replace("≃", "≈")
        .replace("，", ",")
        .replace("～", "~")
        .replace("∼", "~")
    )
    normalized = "".join(
        character for character in normalized if not character.isspace()
    )
    normalized = _FORMULA_PROSE_CONNECTOR.sub("", normalized)
    normalized = _FORMULA_SEPARATOR.sub("", normalized)
    return _FORMULA_GROUPING.sub("", normalized)


def _formula_supported_by_evidence(node: PageKnowledgeNode) -> bool:
    formula_key = _formula_evidence_key(node.formula_text)
    evidence_key = _formula_evidence_key(node.evidence_text)
    return bool(formula_key and formula_key in evidence_key)


def _requires_formula_contract(node: PageKnowledgeNode) -> bool:
    if node.formula_text:
        return False
    math_fields = [
        text
        for text in (node.definition, node.evidence_text)
        if (
            _FORMULA_RELATION.search(text)
            and _COMPLEX_MATH_SIGNAL.search(text)
        )
    ]
    if not math_fields:
        return False
    if any(
        _STRONG_FORMULA_SIGNAL.search(text)
        or len(_FORMULA_RELATION.findall(text)) > 1
        for text in math_fields
    ):
        return True
    return bool(
        any(_SUBSCRIPT_FORMULA_SIGNAL.search(text) for text in math_fields)
        and re.match(r"^\s*[A-Za-zΑ-ω]", node.evidence_text)
    )


def _has_explicit_dimensionless_ratio(node: PageKnowledgeNode) -> bool:
    return bool(_DIMENSIONLESS_RATIO.search(
        _formula_evidence_key(node.evidence_text)
    ))


def _formula_sign_issues(node: PageKnowledgeNode) -> list[str]:
    text_powers = _TEXT_POWER.findall(_normalized_formula(node.formula_text))
    latex_powers = _LATEX_POWER.findall(node.formula_latex)
    issues: list[str] = []
    for text_power, latex_power in zip(text_powers, latex_powers):
        if text_power == latex_power:
            continue
        if (
            latex_power.startswith("-")
            and not text_power.startswith("-")
            and text_power == latex_power[1:]
        ):
            issues.append("missing_negative_exponent")
        else:
            issues.append("formula_text_latex_exponent_mismatch")
    if len(text_powers) != len(latex_powers):
        issues.append("formula_text_latex_exponent_count_mismatch")
    return issues


def _formula_decoration_issues(node: PageKnowledgeNode) -> list[str]:
    expected = Counter(
        {
            mark: len(pattern.findall(node.formula_latex))
            for pattern, mark in _LATEX_DECORATION_MARKS
            if pattern.search(node.formula_latex)
        }
    )
    actual: Counter[str] = Counter()
    for character in unicodedata.normalize("NFD", node.formula_text):
        decoration = _DECORATION_MARK_ALIASES.get(character, character)
        if decoration in _CANONICAL_DECORATION_MARKS:
            actual[decoration] += 1
    if expected != actual:
        return ["formula_text_latex_decoration_mismatch"]
    return []


def _page_metadata_issues(
    extraction: PageKnowledgeExtraction | _PageKnowledgeEnvelope,
    *,
    expected_page: int,
    min_confidence: float,
    page_has_text_signal: bool,
    allow_empty_knowledge_nodes: bool = False,
) -> list[str]:
    issues: list[str] = []
    if extraction.page != expected_page:
        issues.append("page_mismatch")
    if not extraction.complete:
        issues.append("page_marked_incomplete")
    if extraction.confidence < min_confidence:
        issues.append("page_confidence_below_threshold")
    if len(extraction.nodes) > 12:
        issues.append("page_node_limit_exceeded")
    if (
        extraction.has_knowledge
        and not extraction.nodes
        and not allow_empty_knowledge_nodes
    ):
        issues.append("knowledge_page_without_nodes")
    if not extraction.has_knowledge and extraction.nodes:
        issues.append("non_knowledge_page_has_nodes")
    if (
        not extraction.has_knowledge
        and not extraction.no_knowledge_reason
    ):
        issues.append("no_knowledge_reason_missing")
    if not extraction.has_knowledge and page_has_text_signal:
        issues.append("no_knowledge_conflicts_parser_signal")
    return issues


def _page_node_issues(
    node: PageKnowledgeNode,
    *,
    prefix: str,
    min_confidence: float,
) -> list[str]:
    issues: list[str] = []
    if node.confidence < min_confidence:
        issues.append(f"{prefix}:confidence_below_threshold")
    combined = "\n".join(
        (
            node.name,
            node.definition,
            node.evidence_text,
            node.formula_text,
            node.formula_latex,
        )
    )
    if _PRIVATE_USE_OR_REPLACEMENT.search(combined):
        issues.append(f"{prefix}:residual_private_use_glyph")
    if _MARKDOWN_FENCE.search(combined):
        issues.append(f"{prefix}:markdown_fence")
    field_disposition = _page_node_field_disposition(node)
    issues.extend(
        f"{prefix}:label_{issue}"
        for issue in field_disposition.label_issues
    )
    issues.extend(
        f"{prefix}:definition_{issue}"
        for issue in field_disposition.definition_issues
    )
    if field_disposition.action in {
        "reextract_candidate",
        "reject_entire_node",
    }:
        issues.append(f"{prefix}:field_{field_disposition.action}")
    normalized_evidence = _normalized_evidence_text(node.evidence_text)
    if not _evidence_excerpt_is_specific(normalized_evidence):
        issues.append(f"{prefix}:evidence_not_specific")
    if _requires_formula_contract(node):
        issues.append(f"{prefix}:formula_contract_missing")
    formula_supported = _formula_supported_by_evidence(node)
    if node.formula_text:
        for formula_issue in _candidate_issues(node.formula_text):
            if formula_issue == "orphan_fraction_suffix":
                continue
            issues.append(f"{prefix}:{formula_issue}")
        if not formula_supported:
            issues.append(f"{prefix}:formula_not_in_evidence")
        if node.formula_latex.count("{") != node.formula_latex.count("}"):
            issues.append(f"{prefix}:unbalanced_latex_braces")
        issues.extend(
            f"{prefix}:{issue}"
            for issue in _formula_sign_issues(node)
        )
        issues.extend(
            f"{prefix}:{issue}"
            for issue in _formula_decoration_issues(node)
        )
    for field_name, claim in (
        ("name", node.name),
        ("definition", node.definition),
        ("formula", node.formula_text),
    ):
        if not claim:
            continue
        for claim_issue in claim_fidelity_issues(
            claim,
            (node.evidence_text,),
        ):
            if claim_issue.severity != "hard":
                continue
            if field_name == "formula" and formula_supported:
                continue
            if (
                claim_issue.code
                == "extreme_scientific_value_missing_dimension"
                and (
                    formula_supported
                    or _has_explicit_dimensionless_ratio(node)
                )
            ):
                continue
            issues.append(f"{prefix}:{field_name}_{claim_issue.code}")
    return issues


def page_knowledge_issues(
    extraction: PageKnowledgeExtraction,
    *,
    expected_page: int,
    min_confidence: float,
    page_has_text_signal: bool = False,
) -> tuple[str, ...]:
    issues = _page_metadata_issues(
        extraction,
        expected_page=expected_page,
        min_confidence=min_confidence,
        page_has_text_signal=page_has_text_signal,
    )
    seen_temp_ids: set[str] = set()
    for index, node in enumerate(extraction.nodes):
        prefix = f"node_{index}"
        if node.temp_id in seen_temp_ids:
            issues.append(f"{prefix}:duplicate_temp_id")
        seen_temp_ids.add(node.temp_id)
        issues.extend(
            _page_node_issues(
                node,
                prefix=prefix,
                min_confidence=min_confidence,
            )
        )

    return tuple(dict.fromkeys(issues))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _input_hash(
    *,
    source_sha256: str,
    page: RenderedPage,
    image_sha256: str,
    prompt_version: str,
    provider: str,
    model: str,
    knowledge_schema_version: str = PAGE_KNOWLEDGE_SCHEMA_VERSION,
    extraction_profile: PageKnowledgeExtractionProfile = "direct",
    profile_schema_versions: tuple[str, str] | None = None,
) -> str:
    payload_data = {
        "source_sha256": source_sha256,
        "page": page.page,
        "image_sha256": image_sha256,
        "prompt_version": prompt_version,
        "schema_version": knowledge_schema_version,
        "provider": provider,
        "model": model,
    }
    if extraction_profile != "direct":
        payload_data["extraction_profile"] = extraction_profile
        if profile_schema_versions is not None:
            payload_data["profile_schema_versions"] = list(
                profile_schema_versions
            )
    payload = json.dumps(
        payload_data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _checkpoint_stage(
    page_number: int,
    extraction_profile: PageKnowledgeExtractionProfile = "direct",
) -> str:
    if extraction_profile == "direct":
        return f"page_knowledge:{page_number:04d}"
    return (
        f"page_knowledge:{extraction_profile}:"
        f"{page_number:04d}"
    )


def _extraction_profile(
    value: str,
) -> PageKnowledgeExtractionProfile:
    normalized = value.strip().casefold()
    if normalized not in {
        "direct",
        "layout_nodes",
        "direct_layout_fallback",
    }:
        raise ValueError("unsupported PDF page extraction profile")
    return normalized  # type: ignore[return-value]


def _validation_issue_codes(exc: ValidationError) -> list[str]:
    issues: list[str] = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error.get("loc", ()))
        error_type = str(error.get("type") or "validation_error")
        issues.append(
            f"{location}:{error_type}" if location else error_type
        )
    return list(dict.fromkeys(issues))


def _indexed_validation_issue_codes(
    exc: ValidationError,
    *,
    node_index: int,
) -> list[str]:
    issues: list[str] = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error.get("loc", ()))
        error_type = str(error.get("type") or "validation_error")
        suffix = (
            f"{location}:{error_type}"
            if location
            else error_type
        )
        issues.append(f"node_{node_index}:{suffix}")
    return list(dict.fromkeys(issues))


def _validate_page_payload_items(
    payload: Any,
    *,
    expected_page: int,
    min_confidence: float,
    page_has_text_signal: bool,
    allow_empty_knowledge_nodes: bool = False,
) -> _PagePayloadValidation:
    try:
        envelope = _PageKnowledgeEnvelope.model_validate(payload)
    except ValidationError as exc:
        return _PagePayloadValidation(
            envelope=None,
            valid_nodes=(),
            issues=tuple(_validation_issue_codes(exc)),
            invalid_temp_ids=(),
            anonymous_invalid_count=0,
            invalid_issues_by_temp_id=(),
        )

    issues = _page_metadata_issues(
        envelope,
        expected_page=expected_page,
        min_confidence=min_confidence,
        page_has_text_signal=page_has_text_signal,
        allow_empty_knowledge_nodes=allow_empty_knowledge_nodes,
    )
    if (
        envelope.page != expected_page
        or len(envelope.nodes) > 12
        or not envelope.has_knowledge
    ):
        return _PagePayloadValidation(
            envelope=envelope,
            valid_nodes=(),
            issues=tuple(dict.fromkeys(issues)),
            invalid_temp_ids=(),
            anonymous_invalid_count=0,
            invalid_issues_by_temp_id=(),
        )

    valid_nodes: list[tuple[int, PageKnowledgeNode]] = []
    invalid_temp_ids: set[str] = set()
    anonymous_invalid_count = 0
    invalid_issues_by_temp_id: dict[str, list[str]] = {}
    seen_temp_ids: set[str] = set()
    for index, raw_node in enumerate(envelope.nodes):
        raw_temp_id = (
            str(raw_node.get("temp_id") or "").strip()
            if isinstance(raw_node, dict)
            else ""
        )
        try:
            node = PageKnowledgeNode.model_validate(raw_node)
        except ValidationError as exc:
            node_issues = _indexed_validation_issue_codes(
                exc,
                node_index=index,
            )
            if raw_temp_id:
                invalid_temp_ids.add(raw_temp_id)
                invalid_issues_by_temp_id.setdefault(
                    raw_temp_id,
                    [],
                ).extend(node_issues)
            else:
                anonymous_invalid_count += 1
            issues.extend(node_issues)
            continue
        node_issues = _page_node_issues(
            node,
            prefix=f"node_{index}",
            min_confidence=min_confidence,
        )
        if node.temp_id in seen_temp_ids:
            node_issues.append(f"node_{index}:duplicate_temp_id")
        seen_temp_ids.add(node.temp_id)
        if node_issues:
            invalid_temp_ids.add(node.temp_id)
            invalid_issues_by_temp_id.setdefault(
                node.temp_id,
                [],
            ).extend(node_issues)
            issues.extend(node_issues)
            continue
        valid_nodes.append((index, node))

    return _PagePayloadValidation(
        envelope=envelope,
        valid_nodes=tuple(valid_nodes),
        issues=tuple(dict.fromkeys(issues)),
        invalid_temp_ids=tuple(sorted(invalid_temp_ids)),
        anonymous_invalid_count=anonymous_invalid_count,
        invalid_issues_by_temp_id=tuple(
            (
                temp_id,
                tuple(dict.fromkeys(issue_codes)),
            )
            for temp_id, issue_codes
            in sorted(invalid_issues_by_temp_id.items())
        ),
    )


def _node_issues_allow_discard(issues: set[str]) -> bool:
    if not issues:
        return False
    return all(
        (
            issue.endswith(":confidence_below_threshold")
            or issue.endswith(":evidence_not_specific")
            or ":label_" in issue
            or issue.endswith(":field_reextract_candidate")
        )
        for issue in issues
    )


def _page_node_identity(node: PageKnowledgeNode) -> str:
    return json.dumps(
        {
            "evidence_text": _normalized_evidence_text(
                node.evidence_text
            ),
            "formula_text": _formula_evidence_key(node.formula_text),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _eligible_repair_nodes(
    preserved_nodes: list[PageKnowledgeNode],
    incoming_nodes: tuple[tuple[int, PageKnowledgeNode], ...],
    *,
    unresolved_temp_ids: set[str],
    anonymous_unresolved_count: int,
) -> tuple[
    tuple[tuple[int, PageKnowledgeNode], ...],
    list[str],
]:
    if (
        not preserved_nodes
        and not unresolved_temp_ids
        and anonymous_unresolved_count == 0
    ):
        return incoming_nodes, []

    preserved_identities = {
        _page_node_identity(node)
        for node in preserved_nodes
    }
    anonymous_slots = anonymous_unresolved_count
    eligible: list[tuple[int, PageKnowledgeNode]] = []
    issues: list[str] = []
    for source_index, node in incoming_nodes:
        identity = _page_node_identity(node)
        if identity in preserved_identities:
            eligible.append((source_index, node))
            continue
        if node.temp_id in unresolved_temp_ids:
            eligible.append((source_index, node))
            continue
        if anonymous_slots:
            eligible.append((source_index, node))
            anonymous_slots -= 1
            continue
        issues.append(f"node_{source_index}:unexpected_repair_node")
    return tuple(eligible), issues


def _merge_page_nodes(
    preserved_nodes: list[PageKnowledgeNode],
    incoming_nodes: tuple[tuple[int, PageKnowledgeNode], ...],
) -> tuple[
    list[PageKnowledgeNode],
    list[PageKnowledgeNode],
    list[str],
    list[str],
]:
    merged = list(preserved_nodes)
    identities = {
        _page_node_identity(node)
        for node in preserved_nodes
    }
    temp_ids = {node.temp_id for node in preserved_nodes}
    added: list[PageKnowledgeNode] = []
    rejected_temp_ids: list[str] = []
    issues: list[str] = []
    for source_index, node in incoming_nodes:
        identity = _page_node_identity(node)
        if identity in identities:
            continue
        if node.temp_id in temp_ids:
            rejected_temp_ids.append(node.temp_id)
            issues.append(
                f"node_{source_index}:duplicate_preserved_temp_id"
            )
            continue
        merged.append(node)
        identities.add(identity)
        temp_ids.add(node.temp_id)
        added.append(node)
    return merged, added, issues, rejected_temp_ids


def _partial_page_payload(
    envelope: _PageKnowledgeEnvelope,
    nodes: list[PageKnowledgeNode],
    *,
    attempt: int,
) -> dict[str, Any]:
    return {
        "page": envelope.page,
        "complete": False,
        "confidence": envelope.confidence,
        "heading": envelope.heading,
        "has_knowledge": envelope.has_knowledge,
        "no_knowledge_reason": envelope.no_knowledge_reason,
        "nodes": [
            node.model_dump(mode="json")
            for node in nodes
        ],
        "source_attempt": attempt,
    }


def _preserved_nodes_prompt(
    nodes: list[PageKnowledgeNode],
) -> str:
    if not nodes:
        return ""
    summaries = [
        {
            "temp_id": node.temp_id,
            "name": node.name,
            "evidence_text": node.evidence_text,
            "formula_text": node.formula_text,
            "bbox": node.bbox,
        }
        for node in nodes
    ]
    serialized = json.dumps(
        summaries,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        "以下节点已经逐项通过 schema 和质量门，系统会保留它们，"
        f"不要在本次 nodes 中重复输出：{serialized}。"
        "本次 nodes 只输出上次被拒绝或遗漏节点的完整替代项；"
        "能确认原 temp_id 时保持不变。"
    )


def _repair_targets_prompt(
    temp_ids: set[str],
    anonymous_count: int,
) -> str:
    parts: list[str] = []
    if temp_ids:
        parts.append(
            "仍待替代的 temp_id 为 "
            + json.dumps(
                sorted(temp_ids),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        parts.append(
            "若其中某项只是误抽取的孤立标签、低置信碎片或没有连续证据"
            "支持的非公式关系，可把原 temp_id 放入 discarded_temp_ids；"
            "公式、数字、单位、定义、硬 fidelity 问题和关键事实不得撤回"
        )
    if anonymous_count:
        parts.append(
            f"另有 {anonymous_count} 个无法识别 temp_id 的坏节点槽位"
        )
    if not parts:
        return ""
    return "；".join(parts) + "。不得用无关新节点冒充这些修复项。"


def _repair_guidance(issues: list[str]) -> str:
    guidance: list[str] = []
    if any(
        ":label_" in issue or ":field_" in issue
        for issue in issues
    ):
        guidance.append(
            "每个 name 必须逐字取自同一证据块中的连续片段，"
            "长度为 2..48 个字符，保持单行、名词性和自足；"
            "不得使用章节编号、句子开头、连接词、句末标点、"
            "未闭合括号或截断短语。"
        )
    if any("evidence_not_specific" in issue for issue in issues):
        guidance.append(
            "不要把孤立变量、坐标轴文字、连接词、纯标点或过短碎片"
            "单独选为节点；应选择能直接支持一个原子事实的完整连续块。"
        )
    if any("formula_not_in_evidence" in issue for issue in issues):
        guidance.append(
            "每个 formula_text 必须由同一节点 evidence_text 中连续可见的"
            "完整表达式支持；不得只抄说明文字，也不得自造变量。"
            "页面没有显示变量名时，不得为数值关系擅自补变量名；"
            "左操作数必须从证据逐字复制，包括会改变含义的自然语言量名"
            "和限定词。"
        )
    if any("missing_relation_operand" in issue for issue in issues):
        guidance.append(
            "formula_text 和 evidence_text 都不得以 =、≈、>、< 等关系符开头；"
            "跨行等式链必须合并到同一个节点，并从最左侧操作数开始。"
        )
    if any("formula_contract_missing" in issue for issue in issues):
        guidance.append(
            "含关系符且带分式、上下标、科学计数法或运算符的复杂表达式，"
            "必须同时填写 formula_text 和 formula_latex。"
        )
    if any("bbox" in issue for issue in issues):
        guidance.append(
            "bbox 必须严格使用 [左,上,宽,高]，且左+宽≤1、上+高≤1。"
        )
    if any("confidence_below_threshold" in issue for issue in issues):
        guidance.append(
            "无法达到高置信度的图表推断或碎片不要输出；只保留页面文字"
            "和清晰公式直接支持的节点。"
        )
    if "no_knowledge_conflicts_parser_signal" in issues:
        guidance.append(
            "解析层检测到本页存在文本，请独立复核：若这些文本只是目录、"
            "章节索引、导航或装饰，继续设置 has_knowledge=false 并说明；"
            "否则必须提取可发布节点。"
        )
    return "".join(guidance)


def _cached_extraction(
    checkpoint: Any,
    *,
    input_hash: str,
    expected_page: int,
    min_confidence: float,
    page_has_text_signal: bool,
    prompt_version: str,
    provider: str,
    model: str,
    extraction_profile: PageKnowledgeExtractionProfile,
    profile_schema_versions: tuple[str, str] | None = None,
) -> PageKnowledgeExtraction | None:
    if not isinstance(checkpoint, dict):
        return None
    if checkpoint.get("status") != "accepted":
        return None
    if checkpoint.get("input_hash") != input_hash:
        return None
    if checkpoint.get("schema_version") != PAGE_KNOWLEDGE_SCHEMA_VERSION:
        return None
    if checkpoint.get("prompt_version") != prompt_version:
        return None
    if checkpoint.get("provider") != provider:
        return None
    if checkpoint.get("model") != model:
        return None
    if checkpoint.get("extraction_profile") != extraction_profile:
        return None
    if extraction_profile == "layout_nodes":
        if profile_schema_versions is None:
            return None
        layout_schema_version, node_schema_version = profile_schema_versions
        if checkpoint.get("layout_schema_version") != layout_schema_version:
            return None
        if (
            checkpoint.get("layout_node_schema_version")
            != node_schema_version
        ):
            return None
    try:
        extraction = PageKnowledgeExtraction.model_validate(
            checkpoint.get("extraction")
        )
    except ValueError:
        return None
    cached_issues = page_knowledge_issues(
        extraction,
        expected_page=expected_page,
        min_confidence=min_confidence,
        page_has_text_signal=page_has_text_signal,
    )
    if (
        cached_issues == ("no_knowledge_conflicts_parser_signal",)
        and not extraction.has_knowledge
        and int(checkpoint.get("no_knowledge_consensus_attempts") or 0) >= 2
    ):
        return extraction
    if cached_issues:
        return None
    return extraction


def _parser_text_signal_pages(document: ParsedDocument) -> set[int]:
    pages: set[int] = set()
    for block in document.blocks:
        if block.page is None:
            continue
        semantic_characters = [
            character
            for character in block.text
            if character.isalnum() or "\u3400" <= character <= "\u9fff"
        ]
        if len(semantic_characters) >= 12:
            pages.add(block.page)
    return pages


def _stable_unit_id(
    page_number: int,
    node: PageKnowledgeNode,
) -> str:
    payload = json.dumps(
        {
            "page": page_number,
            "name": node.name,
            "definition": node.definition,
            "evidence_text": node.evidence_text,
            "formula_text": node.formula_text,
            "bbox": node.bbox,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return (
        f"pdfk:p{page_number:04d}:"
        f"{hashlib.sha256(payload).hexdigest()[:16]}"
    )


def _node_importance(node: PageKnowledgeNode) -> float:
    base = (
        0.84
        if node.role in {"definition", "principle", "formula"}
        else 0.74
    )
    return min(max(base * 0.6 + node.confidence * 0.4, 0), 1)


def _definition_with_canonical_formula(node: PageKnowledgeNode) -> str:
    definition = node.definition.strip()
    formula = node.formula_text.strip()
    if not formula:
        return definition
    formula_key = _formula_evidence_key(formula)
    definition_key = _formula_evidence_key(definition)
    if formula_key and formula_key in definition_key:
        return definition
    return "\n".join(item for item in (definition, formula) if item)


def _knowledge_records(
    *,
    document: ParsedDocument,
    rendered_by_page: dict[int, RenderedPage],
    extractions: list[PageKnowledgeExtraction],
) -> tuple[list[SourceBlock], list[ContentUnit], list[NodeCandidateIn]]:
    blocks: list[SourceBlock] = []
    units: list[ContentUnit] = []
    candidates: list[NodeCandidateIn] = []
    for extraction in sorted(extractions, key=lambda item: item.page):
        rendered_page = rendered_by_page[extraction.page]
        for node in extraction.nodes:
            unit_id = _stable_unit_id(extraction.page, node)
            unit = ContentUnit(
                id=unit_id,
                document_id=document.document_id,
                kind="text",
                branch_hint=extraction.heading or None,
                importance=_node_importance(node),
                status="uncovered",
                text=node.evidence_text,
                heading_path=(
                    [extraction.heading]
                    if extraction.heading
                    else []
                ),
                unit_role=node.role,
                evidence_excerpt=node.evidence_text,
                page=extraction.page,
                bbox=node.bbox,
                asset_id=rendered_page.asset_id,
            )
            evidence = EvidenceRef(
                unit_id=unit_id,
                excerpt=node.evidence_text,
                page=extraction.page,
                bbox=node.bbox,
                asset_id=rendered_page.asset_id,
            )
            candidate = NodeCandidateIn(
                temp_id=f"direct:{unit_id}",
                name=node.name,
                type=node.type,
                role=node.role,
                definition=_definition_with_canonical_formula(node),
                origin="explicit",
                confidence=node.confidence,
                optional=True,
                activation_score=node.confidence,
                activation_cost=0.12,
                evidence=[evidence],
                support_unit_ids=[unit_id],
            )
            blocks.append(
                SourceBlock(
                    text=node.evidence_text,
                    page=extraction.page,
                    heading=extraction.heading or None,
                )
            )
            units.append(unit)
            candidates.append(candidate)
    return blocks, units, candidates


def _formula_audit_risk_pages(
    *,
    document: ParsedDocument,
    direct: PdfPageKnowledgeResult,
) -> set[int]:
    metadata = document.parse_metadata
    geometry = metadata.get("pdf_geometry_math")
    candidate_original_pages: set[int] = set()
    if isinstance(geometry, dict):
        for candidate in geometry.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue
            try:
                page = int(candidate.get("page"))
            except (TypeError, ValueError):
                continue
            if candidate.get("issues"):
                continue
            candidate_original_pages.add(page)

    original_page_map = metadata.get("original_page_map")
    original_to_mapped: dict[int, int] = {}
    if isinstance(original_page_map, dict):
        for mapped, original in original_page_map.items():
            try:
                original_to_mapped[int(original)] = int(mapped)
            except (TypeError, ValueError):
                continue
    geometry_pages = (
        {
            original_to_mapped[page]
            for page in candidate_original_pages
            if page in original_to_mapped
        }
        if original_to_mapped
        else set(candidate_original_pages)
    )
    return geometry_pages & set(direct.accepted_pages)


def _layout_audit_input_hash(
    *,
    source_sha256: str,
    page: RenderedPage,
    image_sha256: str,
    prompt_version: str,
    provider: str,
    model: str,
    layout_schema_version: str,
    extraction: PageKnowledgeExtraction,
) -> str:
    payload = json.dumps(
        {
            "source_sha256": source_sha256,
            "page": page.page,
            "image_sha256": image_sha256,
            "prompt_version": prompt_version,
            "schema_version": PAGE_KNOWLEDGE_SCHEMA_VERSION,
            "layout_schema_version": layout_schema_version,
            "provider": provider,
            "model": model,
            "direct_extraction": extraction.model_dump(mode="json"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _layout_formula_keys(layout: Any) -> set[str]:
    return {
        key
        for block in layout.blocks
        for formula in block.formulas
        if (key := _formula_evidence_key(formula.text))
    }


def _layout_audit_issues(
    *,
    original: PageKnowledgeExtraction,
    reconciled: PageKnowledgeExtraction,
    layout: Any,
    min_confidence: float,
    page_has_text_signal: bool,
) -> tuple[str, ...]:
    issues = list(
        page_knowledge_issues(
            reconciled,
            expected_page=original.page,
            min_confidence=min_confidence,
            page_has_text_signal=page_has_text_signal,
        )
    )
    layout_formula_keys = _layout_formula_keys(layout)
    if not layout_formula_keys:
        issues.append("layout_audit_no_formula")

    layout_block_keys = [
        _formula_evidence_key(block.text)
        for block in layout.blocks
    ]
    original_formula_keys = {
        key
        for node in original.nodes
        if (key := _formula_evidence_key(node.formula_text))
    }
    for formula_key in sorted(original_formula_keys):
        if not any(
            formula_key in block_key
            for block_key in layout_block_keys
        ):
            issues.append("layout_audit_missing_direct_formula")
            break

    reconciled_formula_keys = {
        key
        for node in reconciled.nodes
        if (key := _formula_evidence_key(node.formula_text))
    }
    if not layout_formula_keys <= reconciled_formula_keys:
        issues.append("layout_audit_unrepresented_formula")
    return tuple(dict.fromkeys(issues))


async def _audit_direct_formula_pages(
    *,
    document: ParsedDocument,
    rendered: RenderResponse,
    runtime: RoleRuntime,
    data_root: Path,
    checkpoint_store: CheckpointStore,
    run_id: str,
    source_sha256: str,
    prompt_version: str,
    min_confidence: float,
    concurrency: int,
    max_page_attempts: int,
    direct: PdfPageKnowledgeResult,
) -> _LayoutAuditSummary:
    risk_pages = sorted(
        _formula_audit_risk_pages(
            document=document,
            direct=direct,
        )
    )
    if not risk_pages:
        return _LayoutAuditSummary(result=direct)

    from .pdf_layout_knowledge import (
        PAGE_LAYOUT_SCHEMA_VERSION,
        PageLayoutExtraction,
        extract_page_layout_knowledge,
        reconcile_layout_formulas,
    )

    direct_by_page = {
        extraction.page: extraction
        for extraction in direct.extractions
    }
    rendered_by_page = {page.page: page for page in rendered.pages}
    parser_text_signal_pages = _parser_text_signal_pages(document)
    render_dir = data_root / "assets" / rendered.render_id
    semaphore = asyncio.Semaphore(max(int(concurrency), 1))
    attempt_limit = max(int(max_page_attempts), 1)

    async def audit_one(
        page_number: int,
    ) -> tuple[
        int,
        PageKnowledgeExtraction | None,
        bool,
        bool,
        int,
    ]:
        original = direct_by_page[page_number]
        rendered_page = rendered_by_page.get(page_number)
        if rendered_page is None:
            return page_number, None, False, False, 0
        source = render_dir / rendered_page.filename
        if not source.is_file():
            return page_number, None, False, False, 0

        image_sha256 = await asyncio.to_thread(_sha256_file, source)
        input_hash = _layout_audit_input_hash(
            source_sha256=source_sha256,
            page=rendered_page,
            image_sha256=image_sha256,
            prompt_version=prompt_version,
            provider=runtime.provider,
            model=runtime.model,
            layout_schema_version=PAGE_LAYOUT_SCHEMA_VERSION,
            extraction=original,
        )
        stage = f"page_knowledge:layout_audit:{page_number:04d}"
        checkpoint = await asyncio.to_thread(
            checkpoint_store.load_checkpoint,
            run_id,
            stage,
        )
        if (
            isinstance(checkpoint, dict)
            and checkpoint.get("status") == "accepted"
            and checkpoint.get("input_hash") == input_hash
            and checkpoint.get("schema_version")
            == PAGE_KNOWLEDGE_SCHEMA_VERSION
            and checkpoint.get("layout_schema_version")
            == PAGE_LAYOUT_SCHEMA_VERSION
            and checkpoint.get("provider") == runtime.provider
            and checkpoint.get("model") == runtime.model
            and checkpoint.get("prompt_version") == prompt_version
        ):
            try:
                cached_layout = PageLayoutExtraction.model_validate(
                    checkpoint.get("layout")
                )
                cached_extraction = PageKnowledgeExtraction.model_validate(
                    checkpoint.get("extraction")
                )
            except ValueError:
                pass
            else:
                cached_issues = _layout_audit_issues(
                    original=original,
                    reconciled=cached_extraction,
                    layout=cached_layout,
                    min_confidence=min_confidence,
                    page_has_text_signal=(
                        page_number in parser_text_signal_pages
                    ),
                )
                if not cached_issues:
                    return (
                        page_number,
                        cached_extraction,
                        True,
                        False,
                        int(
                            checkpoint.get(
                                "supplemented_formula_count"
                            )
                            or 0
                        ),
                    )

        async with semaphore:
            layout_result = await extract_page_layout_knowledge(
                image_path=source,
                page=page_number,
                runtime=runtime,
                profile="dots",
                min_confidence=min_confidence,
                max_layout_attempts=attempt_limit,
                max_node_attempts=attempt_limit,
                extract_nodes=False,
            )
        issues = list(layout_result.issues)
        reconciled: PageKnowledgeExtraction | None = None
        supplemented_formula_count = 0
        if layout_result.layout is not None:
            try:
                reconciled = reconcile_layout_formulas(
                    layout=layout_result.layout,
                    extraction=original,
                )
            except ValueError as exc:
                issues.append(
                    " ".join(str(exc).split())[:160] or "ValueError"
                )
            else:
                issues.extend(
                    _layout_audit_issues(
                        original=original,
                        reconciled=reconciled,
                        layout=layout_result.layout,
                        min_confidence=min_confidence,
                        page_has_text_signal=(
                            page_number in parser_text_signal_pages
                        ),
                    )
                )
                original_formula_keys = {
                    key
                    for node in original.nodes
                    if (
                        key := _formula_evidence_key(
                            node.formula_text
                        )
                    )
                }
                reconciled_formula_keys = {
                    key
                    for node in reconciled.nodes
                    if (
                        key := _formula_evidence_key(
                            node.formula_text
                        )
                    )
                }
                supplemented_formula_count = len(
                    reconciled_formula_keys - original_formula_keys
                )
        issues = list(dict.fromkeys(issues))
        accepted = reconciled is not None and not issues
        payload = {
            "schema_version": PAGE_KNOWLEDGE_SCHEMA_VERSION,
            "layout_schema_version": PAGE_LAYOUT_SCHEMA_VERSION,
            "status": "accepted" if accepted else "failed",
            "input_hash": input_hash,
            "image_sha256": image_sha256,
            "provider": runtime.provider,
            "model": runtime.model,
            "prompt_version": prompt_version,
            "extraction_profile": "layout_audit",
            "layout_profile": "dots",
            "layout_attempts": layout_result.layout_attempts,
            "issues": issues,
            "supplemented_formula_count": supplemented_formula_count,
            "layout": (
                layout_result.layout.model_dump(mode="json")
                if layout_result.layout is not None
                else None
            ),
            "extraction": (
                reconciled.model_dump(mode="json")
                if accepted and reconciled is not None
                else None
            ),
        }
        await asyncio.to_thread(
            checkpoint_store.checkpoint,
            run_id,
            stage,
            payload,
        )
        return (
            page_number,
            reconciled if accepted else None,
            False,
            True,
            supplemented_formula_count if accepted else 0,
        )

    audit_results = await asyncio.gather(
        *(audit_one(page) for page in risk_pages)
    )
    accepted_audits: dict[int, PageKnowledgeExtraction] = {}
    failed_pages: list[int] = []
    reused_pages: list[int] = []
    called_pages: list[int] = []
    supplemented_formula_count = 0
    for (
        page_number,
        extraction,
        reused,
        called,
        supplemented,
    ) in audit_results:
        if extraction is None:
            failed_pages.append(page_number)
        else:
            accepted_audits[page_number] = extraction
        if reused:
            reused_pages.append(page_number)
        if called:
            called_pages.append(page_number)
        supplemented_formula_count += supplemented

    failed_page_set = set(failed_pages)
    updated_extractions = [
        accepted_audits.get(extraction.page, extraction)
        for extraction in direct.extractions
        if extraction.page not in failed_page_set
    ]
    accepted_pages = sorted(
        extraction.page for extraction in updated_extractions
    )
    all_failed_pages = sorted(
        set(direct.failed_pages) | failed_page_set
    )
    updated = direct.model_copy(
        update={
            "extractions": sorted(
                updated_extractions,
                key=lambda item: item.page,
            ),
            "complete": not all_failed_pages,
            "accepted_pages": accepted_pages,
            "failed_pages": all_failed_pages,
        }
    )
    return _LayoutAuditSummary(
        result=updated,
        audited_pages=tuple(risk_pages),
        accepted_pages=tuple(sorted(accepted_audits)),
        failed_pages=tuple(sorted(failed_pages)),
        reused_pages=tuple(sorted(reused_pages)),
        called_pages=tuple(sorted(called_pages)),
        supplemented_formula_count=supplemented_formula_count,
    )


def _merge_profile_results(
    *,
    document: ParsedDocument,
    rendered: RenderResponse,
    runtime: RoleRuntime,
    source_sha256: str,
    prompt_version: str,
    render_dpi: int,
    direct: PdfPageKnowledgeResult,
    fallback: PdfPageKnowledgeResult | None,
    layout_audit: _LayoutAuditSummary,
) -> PdfPageKnowledgeResult:
    extraction_by_page = {
        extraction.page: extraction
        for extraction in direct.extractions
    }
    if fallback is not None:
        extraction_by_page.update(
            {
                extraction.page: extraction
                for extraction in fallback.extractions
            }
        )
    extractions = [
        extraction_by_page[page]
        for page in sorted(extraction_by_page)
    ]
    expected_page_count = int(
        document.parse_metadata.get("pdf_page_count")
        or len(rendered.pages)
    )
    expected_pages = set(range(1, expected_page_count + 1))
    accepted_pages = sorted(extraction_by_page)
    failed_pages = sorted(expected_pages - set(accepted_pages))
    complete = not failed_pages
    fallback_attempted_pages = (
        sorted(direct.failed_pages)
        if fallback is not None
        else []
    )
    fallback_accepted_pages = (
        sorted(fallback.accepted_pages)
        if fallback is not None
        else []
    )
    fallback_failed_pages = (
        sorted(fallback.failed_pages)
        if fallback is not None
        else []
    )
    degraded_pages = sorted(
        set(direct.degraded_pages)
        | set(fallback.degraded_pages if fallback is not None else [])
    )

    warnings: list[str] = []
    if fallback is None:
        warnings.extend(
            warning
            for warning in direct.warnings
            if not (
                PDF_KNOWLEDGE_DEGRADED in warning
                and "计划抽取" in warning
            )
        )
    else:
        warnings.extend(
            warning
            for warning in direct.warnings
            if (
                "页知识节点未通过质量门" not in warning
                and "没有渲染结果" not in warning
                and not (
                    PDF_KNOWLEDGE_DEGRADED in warning
                    and "计划抽取" in warning
                )
            )
        )
        warnings.extend(
            warning
            for warning in fallback.warnings
            if not (
                PDF_KNOWLEDGE_DEGRADED in warning
                and "计划抽取" in warning
            )
        )
    if not complete:
        warnings.append(
            f"{PDF_KNOWLEDGE_DEGRADED} "
            f"计划抽取 {expected_page_count} 页，"
            f"成功 {len(accepted_pages)} 页，"
            f"失败或缺失 {len(failed_pages)} 页。"
        )
    warnings = list(dict.fromkeys(warnings))

    rendered_by_page = {page.page: page for page in rendered.pages}
    blocks, units, candidates = _knowledge_records(
        document=document,
        rendered_by_page=rendered_by_page,
        extractions=extractions,
    )
    reused_pages = sorted(
        set(direct.reused_pages)
        | set(fallback.reused_pages if fallback is not None else [])
    )
    called_pages = sorted(
        set(direct.called_pages)
        | set(fallback.called_pages if fallback is not None else [])
    )
    metadata = {
        "schema_version": PAGE_KNOWLEDGE_SCHEMA_VERSION,
        "prompt_version": prompt_version,
        "provider": runtime.provider,
        "model": runtime.model,
        "extraction_profile": "direct_layout_fallback",
        "profile_chain": ["direct", "layout_nodes"],
        "layout_profile": "dots",
        "render_id": rendered.render_id,
        "render_dpi": render_dpi,
        "source_sha256": source_sha256,
        "complete": complete,
        "accepted_pages": accepted_pages,
        "clean_accepted_pages": sorted(
            set(accepted_pages) - set(degraded_pages)
        ),
        "degraded_pages": degraded_pages,
        "failed_pages": failed_pages,
        "reused_pages": reused_pages,
        "called_pages": called_pages,
        "direct_accepted_pages": sorted(direct.accepted_pages),
        "direct_failed_pages": sorted(direct.failed_pages),
        "direct_reused_pages": sorted(direct.reused_pages),
        "direct_called_pages": sorted(direct.called_pages),
        "layout_audited_pages": list(layout_audit.audited_pages),
        "layout_audit_accepted_pages": list(
            layout_audit.accepted_pages
        ),
        "layout_audit_failed_pages": list(layout_audit.failed_pages),
        "layout_audit_reused_pages": list(layout_audit.reused_pages),
        "layout_audit_called_pages": list(layout_audit.called_pages),
        "layout_audit_supplemented_formula_count": (
            layout_audit.supplemented_formula_count
        ),
        "fallback_attempted_pages": fallback_attempted_pages,
        "fallback_accepted_pages": fallback_accepted_pages,
        "fallback_failed_pages": fallback_failed_pages,
        "fallback_reused_pages": (
            sorted(fallback.reused_pages)
            if fallback is not None
            else []
        ),
        "fallback_called_pages": (
            sorted(fallback.called_pages)
            if fallback is not None
            else []
        ),
        "node_count": len(candidates),
        "pages": [
            extraction.model_dump(mode="json")
            for extraction in extractions
        ],
    }
    updated_document = document.model_copy(
        update={
            "blocks": blocks,
            "warnings": list(
                dict.fromkeys([*document.warnings, *warnings])
            ),
            "parse_metadata": {
                **document.parse_metadata,
                "pdf_page_knowledge": metadata,
            },
        }
    )
    return PdfPageKnowledgeResult(
        document=updated_document,
        extractions=extractions,
        content_units=units,
        node_candidates=candidates,
        complete=complete,
        accepted_pages=accepted_pages,
        degraded_pages=degraded_pages,
        failed_pages=failed_pages,
        reused_pages=reused_pages,
        called_pages=called_pages,
        warnings=warnings,
    )


async def extract_pdf_page_knowledge(
    *,
    document: ParsedDocument,
    rendered: RenderResponse,
    runtime: RoleRuntime,
    data_root: Path,
    checkpoint_store: CheckpointStore,
    run_id: str,
    source_sha256: str,
    prompt_version: str,
    render_dpi: int,
    min_confidence: float,
    concurrency: int,
    max_page_attempts: int,
    extraction_profile: str = "direct",
    _target_pages: set[int] | None = None,
) -> PdfPageKnowledgeResult:
    selected_profile = _extraction_profile(extraction_profile)
    if selected_profile == "direct_layout_fallback":
        if _target_pages is not None:
            raise ValueError(
                "direct_layout_fallback does not accept target pages"
            )
        direct_result = await extract_pdf_page_knowledge(
            document=document,
            rendered=rendered,
            runtime=runtime,
            data_root=data_root,
            checkpoint_store=checkpoint_store,
            run_id=run_id,
            source_sha256=source_sha256,
            prompt_version=prompt_version,
            render_dpi=render_dpi,
            min_confidence=min_confidence,
            concurrency=concurrency,
            max_page_attempts=max_page_attempts,
            extraction_profile="direct",
        )
        layout_audit = await _audit_direct_formula_pages(
            document=document,
            rendered=rendered,
            runtime=runtime,
            data_root=data_root,
            checkpoint_store=checkpoint_store,
            run_id=run_id,
            source_sha256=source_sha256,
            prompt_version=prompt_version,
            min_confidence=min_confidence,
            concurrency=concurrency,
            max_page_attempts=max_page_attempts,
            direct=direct_result,
        )
        direct_result = layout_audit.result
        fallback_result = None
        if (
            direct_result.failed_pages
            and runtime.available
            and runtime.client is not None
        ):
            fallback_result = await extract_pdf_page_knowledge(
                document=document,
                rendered=rendered,
                runtime=runtime,
                data_root=data_root,
                checkpoint_store=checkpoint_store,
                run_id=run_id,
                source_sha256=source_sha256,
                prompt_version=prompt_version,
                render_dpi=render_dpi,
                min_confidence=min_confidence,
                concurrency=concurrency,
                max_page_attempts=max_page_attempts,
                extraction_profile="layout_nodes",
                _target_pages=set(direct_result.failed_pages),
            )
        return _merge_profile_results(
            document=document,
            rendered=rendered,
            runtime=runtime,
            source_sha256=source_sha256,
            prompt_version=prompt_version,
            render_dpi=render_dpi,
            direct=direct_result,
            fallback=fallback_result,
            layout_audit=layout_audit,
        )

    layout_profile = "dots" if selected_profile == "layout_nodes" else None
    full_page_count = int(
        document.parse_metadata.get("pdf_page_count")
        or len(rendered.pages)
    )
    all_expected_pages = set(range(1, full_page_count + 1))
    if _target_pages is None:
        expected_pages = all_expected_pages
    else:
        expected_pages = set(_target_pages)
        if not expected_pages <= all_expected_pages:
            raise ValueError("target pages fall outside the PDF page range")
    target_page_count = len(expected_pages)
    rendered_by_page = {page.page: page for page in rendered.pages}
    parser_text_signal_pages = _parser_text_signal_pages(document)
    missing_render_pages = sorted(expected_pages - rendered_by_page.keys())
    warnings: list[str] = []

    if not runtime.available or not runtime.client:
        reason = runtime.unavailable_reason or "视觉模型不可用"
        warning = (
            f"{PDF_KNOWLEDGE_DEGRADED} "
            f"PDF 页面知识节点抽取未执行：{reason}"
        )
        metadata = {
            "schema_version": PAGE_KNOWLEDGE_SCHEMA_VERSION,
            "prompt_version": prompt_version,
            "provider": runtime.provider,
            "model": runtime.model,
            "extraction_profile": selected_profile,
            "layout_profile": layout_profile,
            "render_id": rendered.render_id,
            "render_dpi": render_dpi,
            "complete": False,
            "accepted_pages": [],
            "clean_accepted_pages": [],
            "degraded_pages": [],
            "failed_pages": sorted(expected_pages),
            "reused_pages": [],
            "called_pages": [],
            "pages": [],
        }
        updated = document.model_copy(
            update={
                "blocks": [],
                "warnings": list(
                    dict.fromkeys([*document.warnings, warning])
                ),
                "parse_metadata": {
                    **document.parse_metadata,
                    "pdf_page_knowledge": metadata,
                },
            }
        )
        return PdfPageKnowledgeResult(
            document=updated,
            failed_pages=sorted(expected_pages),
            warnings=[warning],
        )

    render_dir = data_root / "assets" / rendered.render_id
    semaphore = asyncio.Semaphore(max(int(concurrency), 1))
    page_attempt_limit = max(int(max_page_attempts), 1)
    layout_extractor = None
    layout_node_extractor = None
    layout_result_model = None
    layout_model = None
    layout_issue_checker = None
    layout_schema_version = ""
    layout_node_schema_version = ""
    if selected_profile == "layout_nodes":
        from .pdf_layout_knowledge import (
            LayoutKnowledgePageResult,
            PAGE_LAYOUT_NODE_SCHEMA_VERSION,
            PAGE_LAYOUT_SCHEMA_VERSION,
            PageLayoutExtraction,
            extract_page_layout_knowledge,
            extract_layout_nodes,
            page_layout_issues,
        )

        layout_extractor = extract_page_layout_knowledge
        layout_node_extractor = extract_layout_nodes
        layout_result_model = LayoutKnowledgePageResult
        layout_model = PageLayoutExtraction
        layout_issue_checker = page_layout_issues
        layout_schema_version = PAGE_LAYOUT_SCHEMA_VERSION
        layout_node_schema_version = PAGE_LAYOUT_NODE_SCHEMA_VERSION

    async def extract_one(
        page: RenderedPage,
    ) -> tuple[
        PageKnowledgeExtraction | None,
        bool,
        bool,
        list[str],
    ]:
        source = render_dir / page.filename
        if not source.is_file():
            return (
                None,
                False,
                False,
                [f"第 {page.page} 页渲染图片不存在。"],
            )
        page_has_text_signal = bool(
            selected_profile == "direct"
            and page.page in parser_text_signal_pages
        )
        image_sha256 = await asyncio.to_thread(_sha256_file, source)
        input_hash = _input_hash(
            source_sha256=source_sha256,
            page=page,
            image_sha256=image_sha256,
            prompt_version=prompt_version,
            provider=runtime.provider,
            model=runtime.model,
            extraction_profile=selected_profile,
            profile_schema_versions=(
                (layout_schema_version, layout_node_schema_version)
                if selected_profile == "layout_nodes"
                else None
            ),
        )
        stage = _checkpoint_stage(page.page, selected_profile)
        profile_schema_versions = (
            (layout_schema_version, layout_node_schema_version)
            if selected_profile == "layout_nodes"
            else None
        )
        checkpoint = await asyncio.to_thread(
            checkpoint_store.load_checkpoint,
            run_id,
            stage,
        )
        cached = _cached_extraction(
            checkpoint,
            input_hash=input_hash,
            expected_page=page.page,
            min_confidence=min_confidence,
            page_has_text_signal=page_has_text_signal,
            prompt_version=prompt_version,
            provider=runtime.provider,
            model=runtime.model,
            extraction_profile=selected_profile,
            profile_schema_versions=profile_schema_versions,
        )
        if cached is not None:
            cached_warnings = (
                [
                    f"{PDF_LAYOUT_NODES_FALLBACK} "
                    f"第 {page.page} 页复用了确定性节点选择结果。"
                ]
                if isinstance(checkpoint, dict)
                and checkpoint.get("node_selection_fallback")
                else []
            )
            return cached, True, False, cached_warnings

        reusable_loader = getattr(
            checkpoint_store,
            "list_reusable_checkpoints",
            None,
        )
        if callable(reusable_loader):
            reusable_checkpoints = await asyncio.to_thread(
                reusable_loader,
                run_id,
                stage,
                input_hash,
            )
            for source_run_id, reusable_checkpoint in reusable_checkpoints:
                cached = _cached_extraction(
                    reusable_checkpoint,
                    input_hash=input_hash,
                    expected_page=page.page,
                    min_confidence=min_confidence,
                    page_has_text_signal=page_has_text_signal,
                    prompt_version=prompt_version,
                    provider=runtime.provider,
                    model=runtime.model,
                    extraction_profile=selected_profile,
                    profile_schema_versions=profile_schema_versions,
                )
                if cached is None:
                    continue
                copied_checkpoint = {
                    **reusable_checkpoint,
                    "reused_from_run_id": source_run_id,
                }
                await asyncio.to_thread(
                    checkpoint_store.checkpoint,
                    run_id,
                    stage,
                    copied_checkpoint,
                )
                cached_warnings = (
                    [
                        f"{PDF_LAYOUT_NODES_FALLBACK} "
                        f"第 {page.page} 页复用了确定性节点选择结果。"
                    ]
                    if reusable_checkpoint.get(
                        "node_selection_fallback"
                    )
                    else []
                )
                return cached, True, False, cached_warnings

        reusable_layout = None
        if (
            selected_profile == "layout_nodes"
            and isinstance(checkpoint, dict)
            and layout_model is not None
            and layout_issue_checker is not None
        ):
            prior_layout_schema = str(
                checkpoint.get("layout_schema_version") or ""
            )
            prior_node_schema = str(
                checkpoint.get("layout_node_schema_version") or ""
            )
            prior_knowledge_schema = str(
                checkpoint.get("schema_version") or ""
            )
            prior_input_hash = _input_hash(
                source_sha256=source_sha256,
                page=page,
                image_sha256=image_sha256,
                prompt_version=prompt_version,
                provider=runtime.provider,
                model=runtime.model,
                knowledge_schema_version=prior_knowledge_schema,
                extraction_profile="layout_nodes",
                profile_schema_versions=(
                    prior_layout_schema,
                    prior_node_schema,
                ),
            )
            checkpoint_matches_source = bool(
                checkpoint.get("status") == "accepted"
                and prior_knowledge_schema
                and prior_layout_schema == layout_schema_version
                and prior_node_schema
                and checkpoint.get("input_hash") == prior_input_hash
                and checkpoint.get("image_sha256") == image_sha256
                and checkpoint.get("provider") == runtime.provider
                and checkpoint.get("model") == runtime.model
                and checkpoint.get("prompt_version") == prompt_version
                and checkpoint.get("extraction_profile")
                == "layout_nodes"
            )
            if checkpoint_matches_source:
                try:
                    candidate_layout = layout_model.model_validate(
                        checkpoint.get("layout")
                    )
                    layout_issues = layout_issue_checker(
                        candidate_layout,
                        expected_page=page.page,
                        min_confidence=min_confidence,
                    )
                    if not layout_issues:
                        reusable_layout = candidate_layout
                except ValidationError:
                    reusable_layout = None

        if reusable_layout is not None and isinstance(checkpoint, dict):
            try:
                prior_extraction = PageKnowledgeExtraction.model_validate(
                    checkpoint.get("extraction")
                )
            except ValidationError:
                prior_extraction = None
            if prior_extraction is not None and not page_knowledge_issues(
                prior_extraction,
                expected_page=page.page,
                min_confidence=min_confidence,
                page_has_text_signal=page_has_text_signal,
            ):
                migrated_checkpoint = {
                    **checkpoint,
                    "schema_version": PAGE_KNOWLEDGE_SCHEMA_VERSION,
                    "layout_node_schema_version": (
                        layout_node_schema_version
                    ),
                    "input_hash": input_hash,
                }
                await asyncio.to_thread(
                    checkpoint_store.checkpoint,
                    run_id,
                    stage,
                    migrated_checkpoint,
                )
                cached_warnings = (
                    [
                        f"{PDF_LAYOUT_NODES_FALLBACK} "
                        f"第 {page.page} 页复用了确定性节点选择结果。"
                    ]
                    if checkpoint.get("node_selection_fallback")
                    else []
                )
                return prior_extraction, True, False, cached_warnings

        last_issues: list[str] = []
        layout_result = None
        preserved_nodes: list[PageKnowledgeNode] = []
        unresolved_temp_ids: set[str] = set()
        unresolved_issues_by_temp_id: dict[str, set[str]] = {}
        discarded_temp_ids: set[str] = set()
        no_knowledge_vote_count = 0
        anonymous_unresolved_count = 0
        unresolved_node_count = 0
        best_partial: dict[str, Any] | None = None
        best_partial_issues: list[str] = []
        best_partial_unresolved = 0
        best_partial_unresolved_temp_ids: list[str] = []
        best_partial_anonymous_unresolved = 0
        best_partial_discarded_temp_ids: list[str] = []
        best_partial_score: tuple[int, int, int, int] | None = None
        if (
            reusable_layout is not None
            and isinstance(checkpoint, dict)
            and layout_result_model is not None
        ):
            layout_result = layout_result_model(
                layout=reusable_layout,
                layout_attempts=int(
                    checkpoint.get("layout_attempts") or 0
                ),
            )
        async with semaphore:
            if selected_profile == "layout_nodes":
                try:
                    if (
                        layout_extractor is None
                        or layout_node_extractor is None
                        or layout_result_model is None
                    ):
                        raise ValueError("layout extractor unavailable")
                    if reusable_layout is not None:
                        (
                            upgraded_extraction,
                            node_attempts,
                            node_issues,
                        ) = await layout_node_extractor(
                            layout=reusable_layout,
                            runtime=runtime,
                            min_confidence=min_confidence,
                            max_attempts=page_attempt_limit,
                        )
                        layout_result = layout_result_model(
                            layout=reusable_layout,
                            extraction=upgraded_extraction,
                            layout_attempts=int(
                                checkpoint.get("layout_attempts") or 0
                            ),
                            node_attempts=node_attempts,
                            issues=node_issues,
                        )
                    else:
                        layout_result = await layout_extractor(
                            image_path=source,
                            page=page.page,
                            runtime=runtime,
                            profile="dots",
                            min_confidence=min_confidence,
                            max_layout_attempts=page_attempt_limit,
                            max_node_attempts=page_attempt_limit,
                        )
                    extraction = layout_result.extraction
                    last_issues = list(layout_result.issues)
                    if extraction is not None:
                        quality_issues = page_knowledge_issues(
                            extraction,
                            expected_page=page.page,
                            min_confidence=min_confidence,
                            page_has_text_signal=page_has_text_signal,
                        )
                        if quality_issues:
                            last_issues = list(
                                dict.fromkeys(
                                    [*last_issues, *quality_issues]
                                )
                            )
                            extraction = None
                    if extraction is not None:
                        used_fallback = (
                            "node_selector_deterministic_fallback"
                            in layout_result.issues
                        )
                        checkpoint_payload = {
                            "schema_version": PAGE_KNOWLEDGE_SCHEMA_VERSION,
                            "layout_schema_version": (
                                layout_schema_version
                            ),
                            "layout_node_schema_version": (
                                layout_node_schema_version
                            ),
                            "status": "accepted",
                            "input_hash": input_hash,
                            "image_sha256": image_sha256,
                            "provider": runtime.provider,
                            "model": runtime.model,
                            "prompt_version": prompt_version,
                            "extraction_profile": selected_profile,
                            "layout_profile": "dots",
                            "layout_attempts": (
                                layout_result.layout_attempts
                            ),
                            "node_attempts": layout_result.node_attempts,
                            "node_selection_fallback": used_fallback,
                            "issues": list(layout_result.issues),
                            "layout": (
                                layout_result.layout.model_dump(mode="json")
                                if layout_result.layout is not None
                                else None
                            ),
                            "extraction": extraction.model_dump(mode="json"),
                        }
                        await asyncio.to_thread(
                            checkpoint_store.checkpoint,
                            run_id,
                            stage,
                            checkpoint_payload,
                        )
                        fallback_warnings = (
                            [
                                f"{PDF_LAYOUT_NODES_FALLBACK} "
                                f"第 {page.page} 页节点选择器未通过合同，"
                                "已使用受布局约束的确定性结果。"
                            ]
                            if used_fallback
                            else []
                        )
                        return extraction, False, True, fallback_warnings
                except ValidationError as exc:
                    last_issues = _validation_issue_codes(exc)
                except ModelProviderError:
                    last_issues = ["ModelProviderError"]
                except ValueError as exc:
                    detail = " ".join(str(exc).split())[:160]
                    last_issues = [detail or "ValueError"]
            else:
                for attempt in range(1, page_attempt_limit + 1):
                    try:
                        repair_feedback = ""
                        if last_issues:
                            repair_feedback = (
                                "上一次输出未通过质量门："
                                + "、".join(last_issues[:8])
                                + "。"
                                + _repair_guidance(last_issues)
                                + "请逐项修正；不得删除页面中清晰可见的"
                                "关键公式，也不得猜测或引入页面未显示的变量。"
                                + _preserved_nodes_prompt(
                                    preserved_nodes
                                )
                                + _repair_targets_prompt(
                                    unresolved_temp_ids,
                                    anonymous_unresolved_count,
                                )
                            )
                        with model_call_scope(
                            role=PAGE_KNOWLEDGE_ROLE,
                            input_unit_ids=(f"page:{page.page}",),
                            stage="page_knowledge",
                        ):
                            payload = await (
                                runtime.client.complete_multimodal_json(
                                    model=runtime.model,
                                    system_prompt=PDF_PAGE_KNOWLEDGE_PROMPT,
                                    user_prompt=(
                                        f"提取第 {page.page} 页的知识节点。"
                                        f"页面像素尺寸："
                                        f"{page.width}×{page.height}。"
                                        f"这是本页第 {attempt} 次独立尝试。"
                                        f"{repair_feedback}"
                                    ),
                                    image_data_url=await asyncio.to_thread(
                                        _data_url,
                                        source,
                                    ),
                                    max_tokens=(
                                        PAGE_KNOWLEDGE_MAX_OUTPUT_TOKENS
                                    ),
                                    max_completion_tokens=(
                                        PAGE_KNOWLEDGE_MAX_COMPLETION_TOKENS
                                    ),
                                    thinking_budget=(
                                        PAGE_KNOWLEDGE_THINKING_BUDGET
                                    ),
                                    max_attempts=1,
                                    timeout_seconds=(
                                        PAGE_KNOWLEDGE_TIMEOUT_SECONDS
                                    ),
                                )
                            )
                        validation = _validate_page_payload_items(
                            payload,
                            expected_page=page.page,
                            min_confidence=min_confidence,
                            page_has_text_signal=page_has_text_signal,
                            allow_empty_knowledge_nodes=bool(
                                attempt > 1
                                and (
                                    preserved_nodes
                                    or unresolved_temp_ids
                                    or anonymous_unresolved_count
                                )
                            ),
                        )
                        if validation.envelope is None:
                            last_issues = list(validation.issues)
                            continue
                        if (
                            not validation.envelope.has_knowledge
                            and tuple(validation.issues)
                            == ("no_knowledge_conflicts_parser_signal",)
                            and not validation.envelope.discarded_temp_ids
                        ):
                            no_knowledge_vote_count += 1
                            last_issues = list(validation.issues)
                            if no_knowledge_vote_count < 2:
                                continue
                            extraction = PageKnowledgeExtraction(
                                page=validation.envelope.page,
                                complete=validation.envelope.complete,
                                confidence=validation.envelope.confidence,
                                heading=validation.envelope.heading,
                                has_knowledge=False,
                                no_knowledge_reason=(
                                    validation.envelope.no_knowledge_reason
                                ),
                                nodes=[],
                            )
                            await asyncio.to_thread(
                                checkpoint_store.checkpoint,
                                run_id,
                                stage,
                                {
                                    "schema_version": (
                                        PAGE_KNOWLEDGE_SCHEMA_VERSION
                                    ),
                                    "status": "accepted",
                                    "input_hash": input_hash,
                                    "image_sha256": image_sha256,
                                    "provider": runtime.provider,
                                    "model": runtime.model,
                                    "prompt_version": prompt_version,
                                    "extraction_profile": selected_profile,
                                    "attempt": attempt,
                                    "no_knowledge_consensus_attempts": (
                                        no_knowledge_vote_count
                                    ),
                                    "discarded_temp_ids": [],
                                    "discarded_node_count": 0,
                                    "extraction": extraction.model_dump(
                                        mode="json"
                                    ),
                                },
                            )
                            return extraction, False, True, []

                        incoming_temp_ids = {
                            node.temp_id
                            for _source_index, node
                            in validation.valid_nodes
                        } | set(validation.invalid_temp_ids)
                        discard_issues: list[str] = []
                        for temp_id in (
                            validation.envelope.discarded_temp_ids
                        ):
                            if attempt == 1:
                                discard_issues.append(
                                    f"discard_not_expected:{temp_id}"
                                )
                                continue
                            if temp_id not in unresolved_temp_ids:
                                discard_issues.append(
                                    f"discard_unknown_temp_id:{temp_id}"
                                )
                                continue
                            if temp_id in incoming_temp_ids:
                                discard_issues.append(
                                    f"discard_conflicts_with_node:{temp_id}"
                                )
                                continue
                            if not _node_issues_allow_discard(
                                unresolved_issues_by_temp_id.get(
                                    temp_id,
                                    set(),
                                )
                            ):
                                discard_issues.append(
                                    f"discard_not_allowed:{temp_id}"
                                )
                                continue
                            unresolved_temp_ids.remove(temp_id)
                            unresolved_issues_by_temp_id.pop(temp_id, None)
                            discarded_temp_ids.add(temp_id)

                        (
                            eligible_nodes,
                            unexpected_repair_issues,
                        ) = _eligible_repair_nodes(
                            preserved_nodes,
                            validation.valid_nodes,
                            unresolved_temp_ids=unresolved_temp_ids,
                            anonymous_unresolved_count=(
                                anonymous_unresolved_count
                            ),
                        )
                        (
                            merged_nodes,
                            added_nodes,
                            merge_issues,
                            merge_rejected_temp_ids,
                        ) = _merge_page_nodes(
                            preserved_nodes,
                            eligible_nodes,
                        )
                        unmatched_added_count = 0
                        for added_node in added_nodes:
                            if added_node.temp_id in unresolved_temp_ids:
                                unresolved_temp_ids.remove(
                                    added_node.temp_id
                                )
                                unresolved_issues_by_temp_id.pop(
                                    added_node.temp_id,
                                    None,
                                )
                            else:
                                unmatched_added_count += 1
                        anonymous_unresolved_count = max(
                            (
                                anonymous_unresolved_count
                                - unmatched_added_count
                            ),
                            0,
                        )
                        unresolved_temp_ids.update(
                            validation.invalid_temp_ids
                        )
                        for temp_id, issue_codes in (
                            validation.invalid_issues_by_temp_id
                        ):
                            unresolved_issues_by_temp_id.setdefault(
                                temp_id,
                                set(),
                            ).update(issue_codes)
                        unresolved_temp_ids.update(
                            merge_rejected_temp_ids
                        )
                        for temp_id in merge_rejected_temp_ids:
                            unresolved_issues_by_temp_id.setdefault(
                                temp_id,
                                set(),
                            ).add("duplicate_preserved_temp_id")
                        anonymous_unresolved_count = max(
                            anonymous_unresolved_count,
                            validation.anonymous_invalid_count,
                        )
                        unresolved_node_count = (
                            len(unresolved_temp_ids)
                            + anonymous_unresolved_count
                        )
                        preserved_nodes = merged_nodes
                        extraction: PageKnowledgeExtraction | None = None
                        merged_issues: list[str] = [
                            *validation.issues,
                            *discard_issues,
                            *unexpected_repair_issues,
                            *merge_issues,
                        ]
                        try:
                            extraction = PageKnowledgeExtraction(
                                page=validation.envelope.page,
                                complete=validation.envelope.complete,
                                confidence=validation.envelope.confidence,
                                heading=validation.envelope.heading,
                                has_knowledge=(
                                    validation.envelope.has_knowledge
                                ),
                                no_knowledge_reason=(
                                    validation.envelope.no_knowledge_reason
                                ),
                                nodes=preserved_nodes,
                            )
                        except ValidationError as exc:
                            merged_issues.extend(
                                _validation_issue_codes(exc)
                            )
                        if extraction is not None:
                            merged_issues.extend(
                                page_knowledge_issues(
                                    extraction,
                                    expected_page=page.page,
                                    min_confidence=min_confidence,
                                    page_has_text_signal=(
                                        page_has_text_signal
                                    ),
                                )
                            )
                        if unresolved_node_count:
                            merged_issues.append(
                                "unresolved_node_count:"
                                f"{unresolved_node_count}"
                            )
                        last_issues = list(
                            dict.fromkeys(merged_issues)
                        )
                        if extraction is not None and not last_issues:
                            await asyncio.to_thread(
                                checkpoint_store.checkpoint,
                                run_id,
                                stage,
                                {
                                    "schema_version": (
                                        PAGE_KNOWLEDGE_SCHEMA_VERSION
                                    ),
                                    "status": "accepted",
                                    "input_hash": input_hash,
                                    "image_sha256": image_sha256,
                                    "provider": runtime.provider,
                                    "model": runtime.model,
                                    "prompt_version": prompt_version,
                                    "extraction_profile": selected_profile,
                                    "attempt": attempt,
                                    "discarded_temp_ids": sorted(
                                        discarded_temp_ids
                                    ),
                                    "discarded_node_count": len(
                                        discarded_temp_ids
                                    ),
                                    "extraction": extraction.model_dump(
                                        mode="json"
                                    ),
                                },
                            )
                            return extraction, False, True, []

                        partial = _partial_page_payload(
                            validation.envelope,
                            preserved_nodes,
                            attempt=attempt,
                        )
                        partial_score = (
                            len(preserved_nodes),
                            -unresolved_node_count,
                            -len(last_issues),
                            attempt,
                        )
                        if (
                            best_partial_score is None
                            or partial_score > best_partial_score
                        ):
                            best_partial = partial
                            best_partial_issues = list(last_issues)
                            best_partial_unresolved = (
                                unresolved_node_count
                            )
                            best_partial_unresolved_temp_ids = sorted(
                                unresolved_temp_ids
                            )
                            best_partial_anonymous_unresolved = (
                                anonymous_unresolved_count
                            )
                            best_partial_discarded_temp_ids = sorted(
                                discarded_temp_ids
                            )
                            best_partial_score = partial_score
                        await asyncio.to_thread(
                            checkpoint_store.checkpoint,
                            run_id,
                            stage,
                            {
                                "schema_version": (
                                    PAGE_KNOWLEDGE_SCHEMA_VERSION
                                ),
                                "status": "partial",
                                "input_hash": input_hash,
                                "image_sha256": image_sha256,
                                "provider": runtime.provider,
                                "model": runtime.model,
                                "prompt_version": prompt_version,
                                "extraction_profile": selected_profile,
                                "attempt": attempt,
                                "issues": best_partial_issues,
                                "terminal_issues": last_issues,
                                "unresolved_node_count": (
                                    best_partial_unresolved
                                ),
                                "unresolved_temp_ids": (
                                    best_partial_unresolved_temp_ids
                                ),
                                "anonymous_unresolved_node_count": (
                                    best_partial_anonymous_unresolved
                                ),
                                "discarded_temp_ids": (
                                    best_partial_discarded_temp_ids
                                ),
                                "discarded_node_count": len(
                                    best_partial_discarded_temp_ids
                                ),
                                "best_partial": best_partial,
                            },
                        )
                    except ValidationError as exc:
                        last_issues = _validation_issue_codes(exc)
                    except (ModelProviderError, ValueError) as exc:
                        last_issues = [type(exc).__name__]

        failed_checkpoint = {
            "schema_version": PAGE_KNOWLEDGE_SCHEMA_VERSION,
            "status": "failed",
            "input_hash": input_hash,
            "image_sha256": image_sha256,
            "provider": runtime.provider,
            "model": runtime.model,
            "prompt_version": prompt_version,
            "extraction_profile": selected_profile,
            "attempts": page_attempt_limit,
            "issues": (
                best_partial_issues
                if best_partial is not None
                else last_issues
            ),
            "terminal_issues": last_issues,
        }
        if best_partial is not None:
            failed_checkpoint.update(
                {
                    "best_partial": best_partial,
                    "unresolved_node_count": best_partial_unresolved,
                    "unresolved_temp_ids": (
                        best_partial_unresolved_temp_ids
                    ),
                    "anonymous_unresolved_node_count": (
                        best_partial_anonymous_unresolved
                    ),
                    "discarded_temp_ids": (
                        best_partial_discarded_temp_ids
                    ),
                    "discarded_node_count": len(
                        best_partial_discarded_temp_ids
                    ),
                }
            )
        elif discarded_temp_ids:
            failed_checkpoint.update(
                {
                    "discarded_temp_ids": sorted(discarded_temp_ids),
                    "discarded_node_count": len(discarded_temp_ids),
                }
            )
        if layout_result is not None:
            failed_checkpoint.update(
                {
                    "layout_profile": "dots",
                    "layout_schema_version": layout_schema_version,
                    "layout_node_schema_version": (
                        layout_node_schema_version
                    ),
                    "layout_attempts": layout_result.layout_attempts,
                    "node_attempts": layout_result.node_attempts,
                    "layout": (
                        layout_result.layout.model_dump(mode="json")
                        if layout_result.layout is not None
                        else None
                    ),
                }
            )
        await asyncio.to_thread(
            checkpoint_store.checkpoint,
            run_id,
            stage,
            failed_checkpoint,
        )
        detail = "、".join(last_issues) or "unknown"
        return (
            None,
            False,
            True,
            [f"第 {page.page} 页知识节点未通过质量门：{detail}"],
        )

    page_numbers = sorted(expected_pages & set(rendered_by_page))
    page_results = await asyncio.gather(
        *(
            extract_one(rendered_by_page[page_number])
            for page_number in page_numbers
        )
    )

    extractions: list[PageKnowledgeExtraction] = []
    degraded_pages: list[int] = []
    reused_pages: list[int] = []
    called_pages: list[int] = []
    for page_number, (
        extraction,
        reused,
        called,
        page_warnings,
    ) in zip(page_numbers, page_results):
        warnings.extend(page_warnings)
        if any(
            PDF_LAYOUT_NODES_FALLBACK in warning
            for warning in page_warnings
        ):
            degraded_pages.append(page_number)
        if reused:
            reused_pages.append(page_number)
        if called:
            called_pages.append(page_number)
        if extraction is not None:
            extractions.append(extraction)

    accepted_pages = sorted(item.page for item in extractions)
    failed_pages = sorted(
        set(expected_pages - set(accepted_pages))
        | set(missing_render_pages)
    )
    if missing_render_pages:
        warnings.append(
            "以下页面没有渲染结果，未进入知识节点抽取："
            + "、".join(str(page) for page in missing_render_pages)
        )
    complete = (
        not failed_pages
        and len(accepted_pages) == target_page_count
    )
    if not complete:
        warnings.append(
            f"{PDF_KNOWLEDGE_DEGRADED} "
            f"计划抽取 {target_page_count} 页，"
            f"成功 {len(accepted_pages)} 页，"
            f"失败或缺失 {len(failed_pages)} 页。"
        )

    blocks, units, candidates = _knowledge_records(
        document=document,
        rendered_by_page=rendered_by_page,
        extractions=extractions,
    )
    metadata = {
        "schema_version": PAGE_KNOWLEDGE_SCHEMA_VERSION,
        "prompt_version": prompt_version,
        "provider": runtime.provider,
        "model": runtime.model,
        "extraction_profile": selected_profile,
        "layout_profile": layout_profile,
        "render_id": rendered.render_id,
        "render_dpi": render_dpi,
        "source_sha256": source_sha256,
        "complete": complete,
        "accepted_pages": accepted_pages,
        "clean_accepted_pages": sorted(
            set(accepted_pages) - set(degraded_pages)
        ),
        "degraded_pages": sorted(degraded_pages),
        "failed_pages": failed_pages,
        "reused_pages": reused_pages,
        "called_pages": called_pages,
        "node_count": len(candidates),
        "pages": [
            extraction.model_dump(mode="json")
            for extraction in sorted(
                extractions,
                key=lambda item: item.page,
            )
        ],
    }
    updated_document = document.model_copy(
        update={
            "blocks": blocks,
            "warnings": list(
                dict.fromkeys([*document.warnings, *warnings])
            ),
            "parse_metadata": {
                **document.parse_metadata,
                "pdf_page_knowledge": metadata,
            },
        }
    )
    return PdfPageKnowledgeResult(
        document=updated_document,
        extractions=sorted(extractions, key=lambda item: item.page),
        content_units=units,
        node_candidates=candidates,
        complete=complete,
        accepted_pages=accepted_pages,
        degraded_pages=sorted(degraded_pages),
        failed_pages=failed_pages,
        reused_pages=reused_pages,
        called_pages=called_pages,
        warnings=list(dict.fromkeys(warnings)),
    )
