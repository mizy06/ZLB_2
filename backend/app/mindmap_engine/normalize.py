from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Literal

from ..semantic_dedupe import are_mergeable_exact_duplicates
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
_CONTROL_MARKERS = (
    "[上文衔接]",
    "【上文衔接】",
    "[continued]",
    "[continuation]",
)
_GENERIC_LABELS = {
    "本章",
    "概述",
    "总结",
    "课程内容",
    "基础知识",
    "核心内容",
    "知识点",
    "案例",
    "介绍",
    "补充主题",
    "视觉知识",
    "视觉内容",
    "图片内容",
    "图示内容",
    "关键要点",
}
_STANDALONE_CONNECTIVES = {
    "但是",
    "然而",
    "并且",
    "而且",
    "因此",
    "所以",
    "因为",
    "如果",
    "即使",
    "以及",
    "其中",
    "同时",
}
_SENTENCE_STEM_PREFIX = re.compile(
    r"^(?:"
    r"这(?:说明|表明|意味着|证明)"
    r"|由此(?:可见|说明|表明|得到)"
    r"|(?:可以|可)(?:看出|得到|说明|表明)"
    r"|例如(?:对于)?|比如|所以(?!然)|因此|故而|于是"
    r"|由于|因为|若|如果|当|设|则"
    r"|(?:提出|证明|说明|表明|发现|给出|得到|获得)了"
    r")"
)
_RAW_SECTION_ECHO = re.compile(
    r"^(?:[*△▲]\s*)?(?:"
    r"§\s*\d"
    r"|第\s*(?:\d+|[一二三四五六七八九十百]+)\s*章"
    r"|[一二三四五六七八九十]+\s*[.、．]"
    r"|\d{1,2}\s*(?:[、．]|\.(?!\d))"
    r")"
)
_BIOGRAPHY_CAPTION = re.compile(
    r"(?:^|\d{4}\s*年|年)"
    r"诺贝尔.{0,18}(?:奖获得者|奖得主)"
)
_GENERIC_VISUAL_CAPTION = re.compile(
    r"^(?:"
    r"(?:蓝|红|黑|白|彩色|黑白)?框(?:内)?公式"
    r"|对比示意图|示意图|曲线图|照片|图片|截图"
    r")$"
)
_PHOTO_CAPTION = re.compile(r"(?:照片|图片|截图|影像)$")
_LAYOUT_VISUAL_CAPTION = re.compile(
    r"^(?:"
    r"并列|左右|上下|左(?:侧|图)|右(?:侧|图)|"
    r"上(?:方|图)|下(?:方|图)|页面|画面|带标注"
    r").*(?:图|公式|照片|图片|截图|视场)$"
)
_INCOMPLETE_SUFFIXES = (
    "即使",
    "但是",
    "因为",
    "由于",
    "通过",
    "对于",
    "关于",
    "以及",
    "的",
    "了",
    "不",
    "而",
)
_TRUNCATED_TRAILING_MIN_LENGTH = {
    "描": 8,
    "碰": 4,
}
_BRACKET_PAIRS = {
    "(": ")",
    "（": "）",
    "[": "]",
    "【": "】",
    "{": "}",
    "《": "》",
}
_FORMULA_INTRO_WITHOUT_BODY = re.compile(
    r"(?:"
    r"应有|可得|写为|表示为|关系为|公式为|分别为|如下"
    r")\s*[：:]?\s*(?:即\s*)?(?:\d{1,3})?\s*$"
)
_DANGLING_DIRECTIONAL_SYMBOL = re.compile(
    r"(?:从|由|向|到)\s*"
    r"[A-Za-zΑ-ω][A-Za-zΑ-ω0-9_₀-₉]*\s*$"
)
_DANGLING_DEFINITION_CONNECTIVE = re.compile(
    r"(?:^|[\s，,；;：:])"
    r"(?:即|因此|所以|其中|分别|如下|以及|并且|而|则)"
    r"\s*(?:\d{1,3})?\s*$"
)
_SHORT_DEPENDENT_DEFINITION = re.compile(
    r"[\u3400-\u9fff]{2,10}的[。.]?$"
)
_TRAILING_FORMULA_OPERATOR = re.compile(
    r"(?:=|≈|≃|≤|≥|<|>|→|←|⇒|⇔|[+\-×÷])\s*$"
)
_GLUED_STATE_COMPARISON = re.compile(
    r"(?:非)?[\u3400-\u9fff]{1,12}状态\s*"
    r"[A-Za-z]?\s*[<>]\s*"
    r"(?:非)?[\u3400-\u9fff]{1,12}状态\s*"
    r"可(?:达到|达)"
)
_DUPLICATED_PREDICATE_GLUE = re.compile(r"可达到.{0,32}可达")
_LAYOUT_NUMBER_GLUE = re.compile(
    r"(?:好|坏)\s*[\u3400-\u9fffA-Za-z-]{2,16}"
    r"\s*[：:]\s*\d(?=\s|$)"
)
_DOCUMENT_FOOTER_GLUE = re.compile(
    r"第\s*\d+\s*章\s*(?:结束|完)"
)
_DEFINITION_ISSUE_PATTERNS = (
    _FORMULA_INTRO_WITHOUT_BODY,
    _DANGLING_DIRECTIONAL_SYMBOL,
    _DANGLING_DEFINITION_CONNECTIVE,
    _SHORT_DEPENDENT_DEFINITION,
    _TRAILING_FORMULA_OPERATOR,
    _GLUED_STATE_COMPARISON,
    _DUPLICATED_PREDICATE_GLUE,
    _LAYOUT_NUMBER_GLUE,
    _DOCUMENT_FOOTER_GLUE,
)
_LEADING_ENUMERATION = re.compile(
    r"^(?:"
    r"\d{1,2}\s*(?:[、．]|\.(?!\d))"
    r"|[一二三四五六七八九十]+\s*[.、．]"
    r")\s*"
)
_MATERIAL_RELATION = re.compile(
    r"(?:~=|≈|≃|=|>=|<=|≥|≤|>|<)"
)
_FORMULA_LABEL_RELATION = re.compile(
    r"(?:~=|≈|≃|==?|>=?|<=?|≥|≤|>>|<<|→|⇒|⇔)"
)
_CJK_IDENTIFIER_SUBSCRIPT = re.compile(r"_[\u3400-\u9fff]+")
_BARE_QUANTITY_LABEL = re.compile(
    r"^[~≈≃]?\s*[+\-−]?\d+(?:\.\d+)?"
    r"(?:\s*(?:×|x|\*)\s*10"
    r"(?:\^[+\-]?\d+|[⁺⁻]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+))?"
    r"\s*(?:"
    r"Å|[fpnumμkMGT]?m|Hz|[fpnumμkMGT]?eV|J(?:/T)?|K|"
    r"[fpnumμkMGT]?W|rad|sr|Pa|T|V|A|C|N|s|%"
    r")\s*$",
    re.IGNORECASE,
)
_PLACEHOLDER_GLYPH = re.compile(r"[\u25a1\ufffd]")
_CHEMICAL_STRUCTURE_RELATION = re.compile(
    r"(?:=|≈|≤|≥|→|⇒|⇌|⟶|⟷|--?>)"
)
_CHEMICAL_STRUCTURE_WORD = re.compile(r"[A-Za-z]+")
_CHEMICAL_ELEMENT_SEQUENCE = re.compile(r"(?:[A-Z][a-z]?)+")


@dataclass(frozen=True)
class CandidateFieldDisposition:
    action: Literal[
        "accept",
        "repair_label_keep_claim",
        "trim_definition_keep_claim",
        "repair_label_and_trim_definition_keep_claim",
        "reextract_candidate",
        "reject_entire_node",
    ]
    name: str
    definition: str
    label_issues: tuple[str, ...]
    definition_issues: tuple[str, ...]
    allow_root: bool
    allow_section_label: bool
    allow_formula_label: bool


def normalized_key(value: str) -> str:
    return _KEY_PATTERN.sub("", value).casefold()


def _has_unbalanced_brackets(value: str) -> bool:
    closing_to_opening = {
        closing: opening for opening, closing in _BRACKET_PAIRS.items()
    }
    bracket_stack: list[str] = []
    for character in value:
        if character in _BRACKET_PAIRS:
            bracket_stack.append(character)
        elif character in closing_to_opening:
            if (
                not bracket_stack
                or bracket_stack[-1] != closing_to_opening[character]
            ):
                return True
            bracket_stack.pop()
    return bool(bracket_stack)


def _is_formula_only_label(value: str) -> bool:
    if not _FORMULA_LABEL_RELATION.search(value):
        return False
    without_cjk_subscripts = _CJK_IDENTIFIER_SUBSCRIPT.sub(
        "_x",
        value,
    )
    return re.search(r"[\u3400-\u9fff]", without_cjk_subscripts) is None


def _is_spaced_chemical_structure_fragment(value: str) -> bool:
    if (
        re.search(r"[\u3400-\u9fff]", value)
        or _CHEMICAL_STRUCTURE_RELATION.search(value)
    ):
        return False
    words = _CHEMICAL_STRUCTURE_WORD.findall(value)
    if len(words) < 4:
        return False
    if any(
        _CHEMICAL_ELEMENT_SEQUENCE.fullmatch(word) is None
        and word.casefold() not in {"r", "x"}
        for word in words
    ):
        return False
    isolated_placeholders = sum(
        word.casefold()
        in {"r", "x", "o", "oh", "h", "n", "c", "cl", "br", "i"}
        for word in words
    )
    return isolated_placeholders >= 2


def label_quality_issues(
    value: str,
    *,
    allow_root: bool = False,
    allow_section_label: bool = False,
    allow_formula_label: bool = False,
) -> list[str]:
    """Return deterministic reasons that make a label unsafe to publish.

    This gate is intentionally conservative about obvious extraction
    fragments.  It does not try to decide whether a valid phrase is an
    important concept; that remains the job of the semantic critic.
    """

    label = value.strip()
    issues: list[str] = []
    if not label:
        return ["empty"]
    max_length = (
        160
        if allow_formula_label
        else (80 if allow_root else 48)
    )
    if len(label) < 2:
        issues.append("too_short")
    if len(label) > max_length:
        issues.append("too_long")
    if "\n" in label or "\r" in label:
        issues.append("multiline")
    if any(
        unicodedata.category(character) in {"Cc", "Cf"}
        for character in label
    ):
        issues.append("control_character")
    if any(marker.casefold() in label.casefold() for marker in _CONTROL_MARKERS):
        issues.append("control_marker")
    if normalized_key(label) in {
        normalized_key(item) for item in _GENERIC_LABELS
    }:
        issues.append("generic")
    if label.endswith("关键要点"):
        issues.append("generic_summary")
    if _SENTENCE_STEM_PREFIX.search(label):
        issues.append("sentence_stem")
    if not allow_section_label and _RAW_SECTION_ECHO.search(label):
        issues.append("raw_section_echo")
    if _BIOGRAPHY_CAPTION.search(label):
        issues.append("biography_caption")
    if _GENERIC_VISUAL_CAPTION.search(label):
        issues.append("generic_visual")
    if _PHOTO_CAPTION.search(label):
        issues.append("photo_caption")
    if _LAYOUT_VISUAL_CAPTION.search(label):
        issues.append("layout_visual_caption")
    if label in _STANDALONE_CONNECTIVES:
        issues.append("standalone_connective")
    if label.startswith("的"):
        issues.append("dangling_prefix")
    if label.endswith(_INCOMPLETE_SUFFIXES):
        issues.append("dangling_suffix")
    trailing_character = label[-1:]
    if len(label) >= _TRUNCATED_TRAILING_MIN_LENGTH.get(
        trailing_character,
        len(label) + 1,
    ):
        issues.append("truncated_trailing_character")
    if re.search(r"[，,；;：:。！？!?]$", label):
        issues.append("sentence_fragment")
    if re.search(r"(?:…{1,2}|\.{3,})$", label):
        issues.append("ellipsis")
    if _PLACEHOLDER_GLYPH.search(label):
        issues.append("placeholder_glyph")
    if _has_unbalanced_brackets(label):
        issues.append("unbalanced_brackets")
    if _BARE_QUANTITY_LABEL.fullmatch(label):
        issues.append("bare_quantity")
    if _is_spaced_chemical_structure_fragment(label):
        issues.append("spaced_chemical_structure_fragment")
    if not allow_formula_label and _is_formula_only_label(label):
        issues.append("formula_label_requires_formula_role")
    return list(dict.fromkeys(issues))


def is_publishable_label(
    value: str,
    *,
    allow_root: bool = False,
    allow_section_label: bool = False,
    allow_formula_label: bool = False,
) -> bool:
    return not label_quality_issues(
        value,
        allow_root=allow_root,
        allow_section_label=allow_section_label,
        allow_formula_label=allow_formula_label,
    )


def definition_quality_issues(value: str) -> list[str]:
    """Return obvious reasons an explicit definition is unsafe to publish.

    Empty text is treated as "the label is the claim" for backwards
    compatibility.  This gate rejects only present-but-broken definitions;
    structural/root candidates are exempted by their callers.
    """

    definition = value.strip()
    if not definition:
        return []
    compact = re.sub(r"\s+", " ", definition).strip()
    issues: list[str] = []
    if _PLACEHOLDER_GLYPH.search(compact):
        issues.append("placeholder_glyph")
    if _has_unbalanced_brackets(compact):
        issues.append("unbalanced_brackets")
    if _FORMULA_INTRO_WITHOUT_BODY.search(compact):
        issues.append("formula_intro_without_body")
    if _DANGLING_DIRECTIONAL_SYMBOL.search(compact):
        issues.append("dangling_directional_symbol")
    if _DANGLING_DEFINITION_CONNECTIVE.search(compact):
        issues.append("dangling_connective")
    if (
        _SHORT_DEPENDENT_DEFINITION.fullmatch(compact)
        and not re.search(
            r"(?:是|为|属于|称为|定义为|表现为)",
            compact,
        )
    ):
        issues.append("dependent_fragment")
    if _TRAILING_FORMULA_OPERATOR.search(compact):
        issues.append("trailing_formula_operator")
    if _GLUED_STATE_COMPARISON.search(compact):
        issues.append("glued_state_comparison")
    if _DUPLICATED_PREDICATE_GLUE.search(compact):
        issues.append("duplicated_predicate_glue")
    if _LAYOUT_NUMBER_GLUE.search(compact):
        issues.append("layout_number_glue")
    if _DOCUMENT_FOOTER_GLUE.search(compact):
        issues.append("document_footer_glue")
    return list(dict.fromkeys(issues))


def node_label_policy(
    candidate: NodeCandidateIn | NormalizedNode,
) -> tuple[bool, bool, bool]:
    allow_root = bool(
        candidate.is_root_candidate
        or candidate.role == "root_topic"
        or candidate.type == "root_topic"
    )
    allow_section_label = bool(
        allow_root
        or candidate.role in {"branch_topic", "structural"}
        or candidate.type in {"branch_topic", "structural"}
        or candidate.origin == "structural"
    )
    allow_formula_label = bool(
        candidate.role == "formula"
        or candidate.type.strip().casefold() == "formula"
    )
    return allow_root, allow_section_label, allow_formula_label


def is_publishable_node_label(
    candidate: NodeCandidateIn | NormalizedNode,
) -> bool:
    allow_root, allow_section_label, allow_formula_label = (
        node_label_policy(candidate)
    )
    return is_publishable_label(
        candidate.name,
        allow_root=allow_root,
        allow_section_label=allow_section_label,
        allow_formula_label=allow_formula_label,
    )


def _safe_label_repair(candidate: NodeCandidateIn) -> str | None:
    """Return only deterministic labels anchored in the existing claim.

    This deliberately handles a small set of high-confidence extraction
    shapes observed in the formal export.  It never changes definition,
    evidence, provenance, or source bindings, and it declines ambiguous
    sentence stems instead of guessing a topic.
    """

    source = unicodedata.normalize(
        "NFKC",
        " ".join(
            [
                candidate.name,
                candidate.definition,
                *(item.excerpt or "" for item in candidate.evidence),
            ]
        ),
    )
    source = re.sub(r"\s+", " ", source).strip()
    repaired: str | None = None

    if (
        "微观粒子的全同性" in source
        and "不可分辨性" in source
        and ("固有性质" in source or "不可区分" in source)
    ):
        repaired = "微观粒子的不可分辨性（全同性）"
    elif all(
        anchor in source
        for anchor in ("轨道角动量", "自旋角动量", "量子化")
    ):
        repaired = "轨道角动量与自旋角动量的量子化"
    elif (
        "玻尔半径" in source
        and "基态能量" in source
        and ("玻尔模型" in source or "E_1" in source)
    ):
        repaired = "玻尔半径与氢原子基态能量"
    elif all(
        anchor in source
        for anchor in ("激光", "相干性", "方向性")
    ):
        repaired = "激光的相干性与方向性"
    elif (
        re.search(r"\bHe\s*[-—–]\s*Ne\b", source, re.IGNORECASE)
        and "辅助物质" in source
        and "激活物质" in source
    ):
        repaired = "He–Ne 激光器的介质组成"

    if repaired and not label_quality_issues(repaired):
        return repaired
    return None


def _safe_definition_repair(
    name: str,
    definition: str,
) -> str | None:
    """Return only source-preserving trims; never synthesize missing claims."""

    compact = re.sub(r"\s+", " ", definition).strip()
    leading_source = _LEADING_ENUMERATION.sub("", compact)
    if leading_source.startswith(name):
        following = leading_source[len(name) :].lstrip()
        if following[:1] in "。！？!?":
            repaired = f"{name}{following[0]}"
            if not definition_quality_issues(repaired):
                return repaired
        if following[:1] in "：:" and not definition_quality_issues(name):
            return name

    issue_starts = [
        match.start()
        for pattern in _DEFINITION_ISSUE_PATTERNS
        if (match := pattern.search(compact)) is not None
    ]
    if issue_starts:
        prefix = compact[: min(issue_starts)].rstrip(" ，,：:；;")
        sentence_ends = list(re.finditer(r"[。！？!?]", prefix))
        if sentence_ends:
            repaired = prefix[: sentence_ends[-1].end()].strip()
            if (
                repaired
                and not definition_quality_issues(repaired)
            ):
                return repaired

    # Slide/OCR definitions frequently begin with the already-supported
    # label and then glue diagram text after a colon.  Keeping that exact
    # source clause is safer than reconstructing the missing explanation.
    leading_clause = re.split(r"[：:]", leading_source, maxsplit=1)[0].strip()
    if (
        leading_clause
        and normalized_key(leading_clause) == normalized_key(name)
        and not definition_quality_issues(leading_clause)
    ):
        return leading_clause
    return None


def candidate_field_disposition(
    candidate: NodeCandidateIn,
) -> CandidateFieldDisposition:
    """Apply one shared field policy for branch critique and normalization."""

    name = candidate.name.strip()
    definition = candidate.definition.strip()
    (
        allow_root,
        allow_section_label,
        allow_formula_label,
    ) = node_label_policy(candidate)
    label_issues = tuple(
        label_quality_issues(
            name,
            allow_root=allow_root,
            allow_section_label=allow_section_label,
            allow_formula_label=allow_formula_label,
        )
    )
    definition_issues = tuple(
        definition_quality_issues(definition)
    )
    structural_candidate = allow_root or allow_section_label
    explicit_definition_failure = bool(
        candidate.origin == "explicit"
        and not structural_candidate
        and definition_issues
    )
    action: Literal[
        "accept",
        "repair_label_keep_claim",
        "trim_definition_keep_claim",
        "repair_label_and_trim_definition_keep_claim",
        "reextract_candidate",
        "reject_entire_node",
    ]

    if label_issues:
        repaired_name = (
            None
            if structural_candidate
            else _safe_label_repair(candidate)
        )
        if repaired_name is None:
            action = (
                "reject_entire_node"
                if explicit_definition_failure
                else "reextract_candidate"
            )
        elif explicit_definition_failure:
            repaired_definition = _safe_definition_repair(
                repaired_name,
                definition,
            )
            if repaired_definition is None:
                action = "reextract_candidate"
            else:
                action = "repair_label_and_trim_definition_keep_claim"
                name = repaired_name
                definition = repaired_definition
        else:
            action = "repair_label_keep_claim"
            name = repaired_name
    elif explicit_definition_failure:
        repaired = _safe_definition_repair(name, definition)
        if repaired is None:
            action = "reextract_candidate"
        else:
            action = "trim_definition_keep_claim"
            definition = repaired
    else:
        action = "accept"

    return CandidateFieldDisposition(
        action=action,
        name=name,
        definition=definition,
        label_issues=label_issues,
        definition_issues=definition_issues,
        allow_root=allow_root,
        allow_section_label=allow_section_label,
        allow_formula_label=allow_formula_label,
    )


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


def _identity_rank(
    candidate: NodeCandidateIn,
) -> tuple[int, float, int, int, int]:
    if (
        candidate.is_root_candidate
        or candidate.role == "root_topic"
        or candidate.type == "root_topic"
    ):
        identity_priority = 2
    elif (
        candidate.role in {"branch_topic", "structural"}
        or candidate.type in {"branch_topic", "structural"}
        or candidate.origin == "structural"
    ):
        identity_priority = 1
    else:
        identity_priority = 0
    return (identity_priority, *_candidate_rank(candidate))


def _candidate_preference_key(
    candidate: NodeCandidateIn,
    *,
    identity_aware: bool,
) -> tuple:
    score, definition_length, negative_name_length, negative_id_length = (
        _candidate_rank(candidate)
    )
    identity_priority = (
        _identity_rank(candidate)[0]
        if identity_aware
        else 0
    )
    return (
        -identity_priority,
        -score,
        -definition_length,
        -negative_name_length,
        -negative_id_length,
        candidate.temp_id.casefold(),
        candidate.name.casefold(),
        candidate.definition,
    )


def _select_primary(candidates: list[NodeCandidateIn]) -> NodeCandidateIn:
    """Choose a stable survivor independent of input/model response order."""

    return min(
        candidates,
        key=lambda item: _candidate_preference_key(
            item,
            identity_aware=True,
        ),
    )


def _ordered_candidates(
    candidates: list[NodeCandidateIn],
) -> list[NodeCandidateIn]:
    return sorted(
        candidates,
        key=lambda item: _candidate_preference_key(
            item,
            identity_aware=False,
        ),
    )


def _is_root_identity(candidate: NodeCandidateIn) -> bool:
    return bool(
        candidate.is_root_candidate
        or candidate.role == "root_topic"
        or candidate.type == "root_topic"
        or candidate.origin == "synthesized_root"
    )


def _is_structural_identity(candidate: NodeCandidateIn) -> bool:
    return bool(
        candidate.role in {"branch_topic", "structural"}
        or candidate.type in {"branch_topic", "structural"}
        or candidate.origin == "structural"
    )


def _candidate_provenance_keys(
    candidate: NodeCandidateIn,
) -> set[tuple[str, str]]:
    keys = {
        ("unit", unit_id)
        for unit_id in candidate.support_unit_ids
        if unit_id
    }
    keys.update(
        ("asset", asset_id)
        for asset_id in candidate.media_asset_ids
        if asset_id
    )
    for evidence in candidate.evidence:
        if evidence.unit_id:
            keys.add(("unit", evidence.unit_id))
        if evidence.chunk_id:
            keys.add(("unit", evidence.chunk_id))
        if evidence.asset_id:
            keys.add(("asset", evidence.asset_id))
        if evidence.page is not None:
            keys.add(("page", str(evidence.page)))
        if evidence.slide is not None:
            keys.add(("slide", str(evidence.slide)))
    return keys


def _legacy_exact_identity_mergeable(
    left: NodeCandidateIn,
    right: NodeCandidateIn,
) -> bool:
    """Retain only two narrow, backwards-compatible identity merges.

    Semantic equivalence remains the normal path.  The exceptions are an
    empty structural placeholder paired with its exact same-branch explicit
    label, and legacy branchless same-label candidates from different source
    units.  Shared-source same-label candidates are deliberately *not*
    assumed equal because one slide/media often contains several claims.
    """

    if normalized_key(left.name) != normalized_key(right.name):
        return False
    if _is_root_identity(left) or _is_root_identity(right):
        return False
    if left.branch_id != right.branch_id:
        return False

    left_structural = _is_structural_identity(left)
    right_structural = _is_structural_identity(right)
    if left_structural and right_structural:
        return False
    if left_structural or right_structural:
        structural = left if left_structural else right
        return not structural.definition.strip()

    if left.branch_id is not None:
        return False
    if _candidate_provenance_keys(left) & _candidate_provenance_keys(right):
        return False
    combined_claim = " ".join(
        (
            left.name,
            left.definition,
            right.name,
            right.definition,
        )
    )
    return not _MATERIAL_RELATION.search(combined_claim)


def _candidate_pair_mergeable(
    left: NodeCandidateIn,
    right: NodeCandidateIn,
) -> bool:
    return bool(
        are_mergeable_exact_duplicates(left, right)
        or _legacy_exact_identity_mergeable(left, right)
    )


def _is_structural_scaffold(candidate: NodeCandidateIn) -> bool:
    if not _is_structural_identity(candidate):
        return False
    definition = re.sub(r"\s+", " ", candidate.definition).strip()
    return bool(
        not definition
        or definition.endswith("下的局部主题")
    )


def _absorb_unambiguous_structural_scaffolds(
    clusters: list[list[tuple[int, NodeCandidateIn]]],
) -> list[list[tuple[int, NodeCandidateIn]]]:
    """Fold a pure navigation placeholder into its exact-label claim.

    This is the only controlled exception to complete-link clustering.  It
    applies to one singleton structural scaffold, one unambiguous explicit
    target cluster in the same branch, and never combines two structural
    candidates.  The scaffold carries hierarchy/support provenance but no
    independent material claim.
    """

    scaffold_indices_by_identity: dict[
        tuple[str | None, str],
        list[int],
    ] = defaultdict(list)
    for cluster_index, cluster in enumerate(clusters):
        if len(cluster) != 1:
            continue
        candidate = cluster[0][1]
        if _is_structural_scaffold(candidate):
            scaffold_indices_by_identity[
                (candidate.branch_id, normalized_key(candidate.name))
            ].append(cluster_index)

    absorbed: set[int] = set()
    for identity, scaffold_indices in sorted(
        scaffold_indices_by_identity.items()
    ):
        if len(scaffold_indices) != 1:
            continue
        scaffold_index = scaffold_indices[0]
        targets: list[int] = []
        for target_index, cluster in enumerate(clusters):
            if target_index == scaffold_index:
                continue
            if any(
                _is_structural_identity(candidate)
                for _, candidate in cluster
            ):
                continue
            if any(
                (
                    candidate.branch_id,
                    normalized_key(candidate.name),
                )
                == identity
                for _, candidate in cluster
            ):
                targets.append(target_index)
        if len(targets) != 1:
            continue
        clusters[targets[0]].extend(clusters[scaffold_index])
        absorbed.add(scaffold_index)

    return [
        cluster
        for index, cluster in enumerate(clusters)
        if index not in absorbed
    ]


def _semantic_clusters(
    candidates: list[NodeCandidateIn],
) -> list[list[NodeCandidateIn]]:
    """Build deterministic complete-link duplicate clusters.

    ``are_mergeable_exact_duplicates`` is intentionally pairwise rather than
    transitive.  Requiring a candidate to agree with every existing cluster
    member prevents an A≈B≈C chain from hiding a direct A/C contradiction.
    """

    indexed = list(enumerate(candidates))
    ordered = sorted(
        indexed,
        key=lambda item: (
            item[1].temp_id.casefold(),
            normalized_key(item[1].name),
            item[1].branch_id or "",
            item[1].definition,
        ),
    )
    clusters: list[list[tuple[int, NodeCandidateIn]]] = []
    for source_index, candidate in ordered:
        for cluster in clusters:
            if all(
                _candidate_pair_mergeable(candidate, existing)
                for _, existing in cluster
            ):
                cluster.append((source_index, candidate))
                break
        else:
            clusters.append([(source_index, candidate)])

    clusters = _absorb_unambiguous_structural_scaffolds(clusters)
    clusters.sort(
        key=lambda items: min(source_index for source_index, _ in items)
    )
    return [
        [candidate for _, candidate in cluster]
        for cluster in clusters
    ]


def _merge_nodes(
    request: NormalizeRequest,
) -> tuple[list[NormalizedNode], dict[str, str], list[str]]:
    prepared: list[NodeCandidateIn] = []
    warnings: list[str] = []
    for candidate in request.nodes:
        if candidate.temp_id.startswith("coverage_"):
            warnings.append(
                f"候选“{candidate.temp_id}”来自旧版覆盖补点，"
                "已转人工复核且不进入正式图。"
            )
            continue
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
                f"字段资格门无法安全修复（{','.join(reasons) or 'unknown'}），"
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
        prepared.append(candidate)

    grouped = _semantic_clusters(prepared)
    cluster_identities: list[tuple[str, str]] = []
    cluster_primaries: list[NodeCandidateIn] = []
    for candidates in grouped:
        primary = _select_primary(candidates)
        scope = (
            "__root__"
            if any(item.is_root_candidate for item in candidates)
            else primary.branch_id or "__global__"
        )
        cluster_primaries.append(primary)
        cluster_identities.append((normalized_key(primary.name), scope))
    identity_counts = Counter(cluster_identities)

    nodes: list[NormalizedNode] = []
    reference_claims: dict[str, set[str]] = defaultdict(set)

    for cluster_index, candidates in enumerate(grouped):
        ordered = _ordered_candidates(candidates)
        primary = cluster_primaries[cluster_index]
        key, scope = cluster_identities[cluster_index]
        node_identity = f"{scope}:{key}"
        if identity_counts[(key, scope)] > 1:
            cluster_token = "|".join(
                sorted(item.temp_id for item in candidates)
            )
            node_identity = f"{node_identity}:claim:{cluster_token}"
        node_id = _stable_id("node", node_identity)
        aliases: set[str] = set(primary.aliases)
        temp_ids: set[str] = set()
        support_ids: set[str] = set()
        explicit_evidence_unit_ids: set[str] = set()
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
            if candidate.origin == "explicit":
                explicit_evidence_unit_ids.update(
                    item.unit_id or item.chunk_id
                    for item in candidate.evidence
                    if item.unit_id or item.chunk_id
                )
            if candidate.definition:
                definitions.append(candidate.definition)

        is_root_candidate = any(item.is_root_candidate for item in candidates)
        origin = (
            "synthesized_root"
            if is_root_candidate
            else primary.origin
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
            definition=(
                max(definitions, key=lambda value: (len(value), value))
                if definitions
                else ""
            ),
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
            evidence=_dedupe_evidence(
                evidence,
                limit=max(16, len(evidence)),
            ),
            explicit_evidence_unit_ids=sorted(
                explicit_evidence_unit_ids
            ),
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
            reference_claims[reference].add(node_id)
            reference_claims[normalized_key(reference)].add(node_id)

        if len(candidates) > 1:
            source_identities = {
                (
                    normalized_key(candidate.name),
                    candidate.branch_id or "__global__",
                )
                for candidate in candidates
            }
            if len(source_identities) > 1:
                warnings.append(
                    f"节点“{primary.name}”通过严格语义等价合并了 "
                    f"{len(candidates)} 个候选；survivor="
                    f"{primary.temp_id}，temp_id、source/evidence 与 media "
                    "provenance 已汇总。"
                )
            else:
                warnings.append(
                    f"节点“{primary.name}”合并了 {len(candidates)} 个"
                    "同名或规范化重复候选。"
                )

    output_by_label: dict[str, list[NormalizedNode]] = defaultdict(list)
    for node in nodes:
        if normalized_key(node.name):
            output_by_label[normalized_key(node.name)].append(node)
    for key, matching_nodes in sorted(output_by_label.items()):
        if len(matching_nodes) <= 1:
            continue
        branches = {
            node.branch_id
            for node in matching_nodes
            if node.branch_id
        }
        matching = matching_nodes[0].name
        if len(branches) > 1:
            warnings.append(
                f"检测到跨分支同名候选“{matching}”，已保留为独立节点，"
                "名称引用将视为歧义。"
            )
        else:
            warnings.append(
                f"检测到同分支同名但命题不等价的候选“{matching}”，"
                "已保留为独立节点，名称引用将视为歧义。"
            )

    if not any(node.is_root_candidate for node in nodes):
        title = request.document_title.strip() or "课程主题"
        if not is_publishable_label(
            title,
            allow_root=True,
            allow_section_label=True,
        ):
            title = "文档中心主题"
        key = normalized_key(title) or request.document_id
        root_id = _stable_id("node", f"root:{key}")
        support_ids = sorted(
            {
                unit_id
                for node in nodes
                for unit_id in [
                    *node.support_unit_ids,
                    *[
                        item.unit_id or item.chunk_id
                        for item in node.evidence
                        if item.unit_id or item.chunk_id
                    ],
                ]
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
        for reference in {
            root_id,
            "generated_root",
            title,
            normalized_key(title),
        }:
            reference_claims[reference].add(root_id)
        warnings.append("输入没有根候选，已使用文档标题生成可审计的保底根候选。")

    reference_to_id: dict[str, str] = {}
    for reference, target_ids in reference_claims.items():
        if len(target_ids) == 1:
            reference_to_id[reference] = next(iter(target_ids))
            continue
        if reference and reference == normalized_key(reference):
            warnings.append(
                f"节点引用“{reference}”对应多个跨分支节点，"
                "必须使用 temp_id 或规范化 node id。"
            )

    # ``grouped`` preserves the caller's first-seen order.  That order is
    # the source/chapter order established by branch planning.  Only move
    # root candidates to the front; sorting siblings by hashed branch IDs
    # destroys the course sequence before topology/export can preserve it.
    original_order = {
        node.id: index
        for index, node in enumerate(nodes)
    }
    nodes.sort(
        key=lambda item: (
            not item.is_root_candidate,
            original_order[item.id],
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
        remaining = max(max_per_child - incoming_count[child.id], 0)
        if remaining <= 0:
            continue

        # Candidate generation is deliberately role- and branch-constrained.
        # Comparing every concept with every other concept produced O(N²)
        # uncertain pseudo-edges without adding useful recall.
        if child.role == "branch_topic":
            parent_pool = [node for node in nodes if node.is_root_candidate]
        else:
            parent_pool = [
                node
                for node in nodes
                if node.id != child.id
                and node.branch_id
                and node.branch_id == child.branch_id
                and (
                    node.role == "branch_topic"
                    or node.origin in {"abstractive", "structural"}
                )
            ]
        suggestions: list[NormalizedParentCandidate] = []
        for parent in parent_pool:
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
                    provisional=True,
                )
            )
        suggestions.sort(
            key=lambda item: (-item.score, item.parent_id, item.child_id)
        )
        for candidate in suggestions[:remaining]:
            by_pair[(candidate.parent_id, candidate.child_id)] = candidate
    return list(by_pair.values())


def _node_evidence_unit_ids(node: NormalizedNode) -> set[str]:
    return {
        *node.support_unit_ids,
        *[
            item.unit_id or item.chunk_id
            for item in node.evidence
            if item.unit_id or item.chunk_id
        ],
    }


def _structural_edge_evidence(
    parent: NormalizedNode,
    child: NormalizedNode,
) -> list[EvidenceRef]:
    """Build auditable evidence for root/topic structural edges.

    A support mapping is acceptable only for synthesized/structural parents.
    Concept-to-concept hierarchy still requires explicit relation evidence.
    """

    if not (
        parent.is_root_candidate
        or parent.role == "branch_topic"
        or parent.origin in {"abstractive", "structural"}
    ):
        return []
    parent_units = _node_evidence_unit_ids(parent)
    child_units = _node_evidence_unit_ids(child)
    shared = sorted(parent_units & child_units)
    if not shared:
        return []
    child_evidence = [
        item
        for item in child.evidence
        if (item.unit_id or item.chunk_id) in set(shared)
    ]
    if child_evidence:
        return _dedupe_evidence(child_evidence, limit=4)
    return [
        EvidenceRef(
            unit_id=unit_id,
            excerpt=f"结构支持映射：{parent.name} → {child.name}",
        )
        for unit_id in shared[:4]
    ]


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
        edge_evidence = _dedupe_evidence(candidate.evidence)
        if (
            candidate.classification == "direct_parent"
            and not edge_evidence
        ):
            edge_evidence = _structural_edge_evidence(
                node_by_id[parent_id],
                node_by_id[child_id],
            )
        if (
            candidate.classification == "direct_parent"
            and not candidate.provisional
            and not edge_evidence
        ):
            warnings.append(
                f"正式父边候选 {candidate.parent} -> {candidate.child} "
                "缺少关系证据，将不会作为可发布直接父边。"
            )
        grouped[(parent_id, child_id)].append(
            NormalizedParentCandidate(
                parent_id=parent_id,
                child_id=child_id,
                score=_combined_parent_score(candidate),
                classification=candidate.classification,
                provisional=candidate.provisional,
                evidence=edge_evidence,
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
