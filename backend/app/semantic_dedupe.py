from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
import re
from typing import TYPE_CHECKING
import unicodedata

from .claim_fidelity import hard_claim_fidelity_issues

if TYPE_CHECKING:
    from .mindmap_engine.schemas import NodeCandidateIn


__all__ = ["are_mergeable_exact_duplicates"]


_SUBSCRIPT_TRANSLATION = str.maketrans(
    {
        "₀": "_0",
        "₁": "_1",
        "₂": "_2",
        "₃": "_3",
        "₄": "_4",
        "₅": "_5",
        "₆": "_6",
        "₇": "_7",
        "₈": "_8",
        "₉": "_9",
        "ₐ": "_a",
        "ₑ": "_e",
        "ₕ": "_h",
        "ᵢ": "_i",
        "ⱼ": "_j",
        "ₖ": "_k",
        "ₗ": "_l",
        "ₘ": "_m",
        "ₙ": "_n",
        "ₒ": "_o",
        "ₚ": "_p",
        "ᵣ": "_r",
        "ₛ": "_s",
        "ₜ": "_t",
        "ᵤ": "_u",
        "ᵥ": "_v",
        "ₓ": "_x",
    }
)
_SUPERSCRIPT_TRANSLATION = str.maketrans(
    {
        "⁰": "^0",
        "¹": "^1",
        "²": "^2",
        "³": "^3",
        "⁴": "^4",
        "⁵": "^5",
        "⁶": "^6",
        "⁷": "^7",
        "⁸": "^8",
        "⁹": "^9",
        "⁻": "^-",
    }
)
_MATH_RELATION = re.compile(
    r"(?P<left>[A-Za-z0-9_λΛνΝΔδμΜπΠσΣωΩħℏ"
    r"+\-*/^().·×\s]{1,80}?)"
    r"(?P<relation>~=|≈|≃|=|>=|<=|≥|≤|>|<)"
    r"(?P<right>[A-Za-z0-9_λΛνΝΔδμΜπΠσΣωΩħℏ"
    r"+\-*/^().·×\s]{1,80})"
)
_TOKEN = re.compile(
    r"(?:\d+(?:\.\d+)?)"
    r"|(?:[A-Za-z](?:_[A-Za-z0-9]+)?)"
    r"|(?:[λΛνΝΔδμΜπΠσΣωΩħ])"
    r"|(?:[()+\-*/^])"
)
_NUMBER = re.compile(
    r"(?<![A-Za-z_\u0370-\u03ff])"
    r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?%?"
    r"(?![A-Za-z_])"
)
_SENTENCE_SPLIT = re.compile(r"[。！？!?；;，,\n]+")
_CAUSAL_MARKERS = ("导致", "引起", "造成", "使得", "促进", "抑制")
_OPPOSITE_TERM_PAIRS = (
    ("增加", "减少"),
    ("增大", "减小"),
    ("升高", "降低"),
    ("提高", "降低"),
    ("高于", "低于"),
    ("大于", "小于"),
    ("吸引", "排斥"),
    ("促进", "抑制"),
    ("正比", "反比"),
)
_STRUCTURAL_EXTENSION_MARKERS = (
    "旧理论",
    "理论预言",
    "理论预测",
    "理论应",
    "矛盾",
    "失败",
    "不能解释",
    "无法解释",
    "局限",
    "反例",
    "可用于",
    "应用于",
    "技术",
)
_GENERIC_ANCHORS = {
    "一个",
    "一种",
    "其中",
    "通过",
    "表示",
    "说明",
    "定义",
    "概念",
    "实验",
    "结果",
    "示意图",
    "本征值",
}
_GENERIC_DEFINITIONS = {
    "文档中出现的主题或术语",
}
_PROSE_SEPARATOR = "\x00"


@dataclass(frozen=True)
class _Monomial:
    coefficient: Fraction
    powers: tuple[tuple[str, int], ...]

    @classmethod
    def constant(cls, value: Fraction) -> _Monomial:
        return cls(value, ())

    @classmethod
    def variable(cls, name: str) -> _Monomial:
        return cls(Fraction(1), ((name, 1),))

    def multiplied_by(self, other: _Monomial) -> _Monomial:
        powers = dict(self.powers)
        for name, exponent in other.powers:
            powers[name] = powers.get(name, 0) + exponent
            if powers[name] == 0:
                del powers[name]
        return _Monomial(
            self.coefficient * other.coefficient,
            tuple(sorted(powers.items())),
        )

    def divided_by(self, other: _Monomial) -> _Monomial:
        if other.coefficient == 0:
            raise ValueError("division by zero")
        powers = dict(self.powers)
        for name, exponent in other.powers:
            powers[name] = powers.get(name, 0) - exponent
            if powers[name] == 0:
                del powers[name]
        return _Monomial(
            self.coefficient / other.coefficient,
            tuple(sorted(powers.items())),
        )

    def raised_to(self, exponent: int) -> _Monomial:
        if exponent < 0 and self.coefficient == 0:
            raise ValueError("zero cannot have a negative exponent")
        return _Monomial(
            self.coefficient**exponent,
            tuple(
                (name, power * exponent)
                for name, power in self.powers
                if power * exponent
            ),
        )

    def negated(self) -> _Monomial:
        return _Monomial(-self.coefficient, self.powers)


@dataclass(frozen=True)
class _FormulaRecord:
    fingerprint: str
    relation: str
    subject: str | None
    material: bool
    variables: frozenset[str]


class _MonomialParser:
    def __init__(self, expression: str):
        prepared = _prepare_identifiers(expression)
        self.tokens = _TOKEN.findall(prepared)
        self.index = 0
        compact = re.sub(r"\s+", "", prepared)
        if "".join(self.tokens) != compact:
            raise ValueError("unsupported expression")

    def parse(self) -> _Monomial:
        result = self._parse_product()
        if self.index != len(self.tokens):
            raise ValueError("trailing expression content")
        return result

    def _parse_product(self) -> _Monomial:
        result = self._parse_factor()
        while self.index < len(self.tokens):
            token = self.tokens[self.index]
            if token == ")":
                break
            if token == "*":
                self.index += 1
                result = result.multiplied_by(self._parse_factor())
                continue
            if token == "/":
                self.index += 1
                result = result.divided_by(self._parse_factor())
                continue
            if token in {"+", "-", "^"}:
                raise ValueError("non-monomial expression")
            result = result.multiplied_by(self._parse_factor())
        return result

    def _parse_factor(self) -> _Monomial:
        sign = 1
        while self.index < len(self.tokens):
            token = self.tokens[self.index]
            if token not in {"+", "-"}:
                break
            if token == "-":
                sign *= -1
            self.index += 1

        if self.index >= len(self.tokens):
            raise ValueError("missing factor")
        token = self.tokens[self.index]
        self.index += 1
        if token == "(":
            value = self._parse_product()
            if (
                self.index >= len(self.tokens)
                or self.tokens[self.index] != ")"
            ):
                raise ValueError("unclosed parenthesis")
            self.index += 1
        elif token == ")" or token in {"*", "/", "^"}:
            raise ValueError("unexpected operator")
        elif re.fullmatch(r"\d+(?:\.\d+)?", token):
            value = _Monomial.constant(Fraction(token))
        else:
            value = _Monomial.variable(_canonical_identifier(token))

        if self.index < len(self.tokens) and self.tokens[self.index] == "^":
            self.index += 1
            exponent_sign = 1
            if (
                self.index < len(self.tokens)
                and self.tokens[self.index] in {"+", "-"}
            ):
                if self.tokens[self.index] == "-":
                    exponent_sign = -1
                self.index += 1
            if (
                self.index >= len(self.tokens)
                or not self.tokens[self.index].isdigit()
            ):
                raise ValueError("unsupported exponent")
            exponent = exponent_sign * int(self.tokens[self.index])
            self.index += 1
            value = value.raised_to(exponent)

        return value.negated() if sign < 0 else value


def are_mergeable_exact_duplicates(
    left: NodeCandidateIn,
    right: NodeCandidateIn,
) -> bool:
    """Return whether two candidates state the same material claim.

    The predicate deliberately has no fuzzy-name or embedding fallback.
    Formula identity may bridge pages and branches.  Prose identity requires
    shared provenance plus several exact claim anchors and no detected
    contradiction.
    """

    if _is_root(left) or _is_root(right):
        return False
    if (
        _has_internal_hard_claim_conflict(left)
        or _has_internal_hard_claim_conflict(right)
    ):
        return False

    left_structural = _is_structural(left)
    right_structural = _is_structural(right)
    if left_structural and right_structural:
        return False

    structural = left if left_structural else right if right_structural else None
    explicit = right if left_structural else left if right_structural else None
    if structural is not None:
        if not _is_branch_topic(structural):
            return False
        if structural.branch_id != explicit.branch_id:
            return False
        if not _has_shared_provenance(structural, explicit):
            return False
        if _has_structural_extension(explicit, structural):
            return False

    left_body = _claim_body(left)
    right_body = _claim_body(right)
    if left_body and right_body:
        if _has_opposite_terms(left_body, right_body):
            return False
        if _has_reversed_causality(left_body, right_body):
            return False
        if _has_numeric_conflict(left_body, right_body):
            return False

    left_formulas = _formula_records(left)
    right_formulas = _formula_records(right)
    if _formula_subject_conflict(left_formulas, right_formulas):
        return False

    shared_formulas = {
        item.fingerprint for item in left_formulas if item.material
    } & {
        item.fingerprint for item in right_formulas if item.material
    }
    if (
        shared_formulas
        and _formula_contexts_are_compatible(
            left_formulas,
            right_formulas,
            shared_formulas,
        )
    ):
        return True
    if _has_exact_claim_identity(left, right, left_body, right_body):
        return True
    if (
        any(item.material for item in left_formulas)
        or any(item.material for item in right_formulas)
    ):
        return False

    if not _has_shared_provenance(left, right):
        return False

    if not left_body or not right_body:
        return False

    anchors = _shared_exact_anchors(left_body, right_body)
    return _prose_equivalence_supported(
        left,
        right,
        left_body,
        right_body,
        anchors,
    )


def _has_exact_claim_identity(
    left: NodeCandidateIn,
    right: NodeCandidateIn,
    left_body: str,
    right_body: str,
) -> bool:
    left_name = _claim_text_key(left.name)
    right_name = _claim_text_key(right.name)
    left_claim = _claim_text_key(left_body)
    right_claim = _claim_text_key(right_body)
    return bool(
        left_name
        and left_name == right_name
        and left_claim
        and left_claim == right_claim
        and len(left_claim) >= 8
    )


@lru_cache(maxsize=8192)
def _field_has_hard_evidence_conflict(
    value: str,
    evidence_excerpts: tuple[str, ...],
) -> bool:
    return bool(
        value.strip()
        and hard_claim_fidelity_issues(
            value,
            evidence_excerpts,
        )
    )


def _has_internal_hard_claim_conflict(
    candidate: NodeCandidateIn,
) -> bool:
    evidence_excerpts = tuple(
        evidence.excerpt.strip()
        for evidence in candidate.evidence
        if evidence.excerpt.strip()
    )
    if not evidence_excerpts:
        return False
    return bool(
        _field_has_hard_evidence_conflict(
            candidate.name,
            evidence_excerpts,
        )
        or _field_has_hard_evidence_conflict(
            candidate.definition,
            evidence_excerpts,
        )
    )


def _is_root(candidate: NodeCandidateIn) -> bool:
    return bool(
        candidate.is_root_candidate
        or candidate.role == "root_topic"
        or candidate.type == "root_topic"
        or candidate.origin == "synthesized_root"
    )


def _is_branch_topic(candidate: NodeCandidateIn) -> bool:
    return bool(
        candidate.role == "branch_topic"
        or candidate.type == "branch_topic"
    )


def _is_structural(candidate: NodeCandidateIn) -> bool:
    return bool(
        _is_branch_topic(candidate)
        or candidate.role == "structural"
        or candidate.type == "structural"
        or candidate.origin == "structural"
    )


def _has_structural_extension(
    explicit: NodeCandidateIn,
    structural: NodeCandidateIn,
) -> bool:
    explicit_text = _claim_body(explicit)
    structural_text = _claim_body(structural)
    if any(
        marker in explicit_text and marker not in structural_text
        for marker in _STRUCTURAL_EXTENSION_MARKERS
    ):
        return True
    explicit_formulas = {
        item.fingerprint for item in _formula_records(explicit)
    }
    structural_formulas = {
        item.fingerprint for item in _formula_records(structural)
    }
    return bool(explicit_formulas - structural_formulas)


def _candidate_units(candidate: NodeCandidateIn) -> set[str]:
    result = {item for item in candidate.support_unit_ids if item}
    for evidence in candidate.evidence:
        if evidence.unit_id:
            result.add(evidence.unit_id)
        if evidence.chunk_id:
            result.add(evidence.chunk_id)
    return result


def _candidate_assets(candidate: NodeCandidateIn) -> set[str]:
    result = {item for item in candidate.media_asset_ids if item}
    result.update(
        evidence.asset_id
        for evidence in candidate.evidence
        if evidence.asset_id
    )
    return result


def _candidate_locations(
    candidate: NodeCandidateIn,
) -> tuple[set[int], set[int]]:
    pages = {
        evidence.page
        for evidence in candidate.evidence
        if evidence.page is not None
    }
    slides = {
        evidence.slide
        for evidence in candidate.evidence
        if evidence.slide is not None
    }
    return pages, slides


def _has_shared_provenance(
    left: NodeCandidateIn,
    right: NodeCandidateIn,
) -> bool:
    if _candidate_units(left) & _candidate_units(right):
        return True
    if _candidate_assets(left) & _candidate_assets(right):
        return True
    left_pages, left_slides = _candidate_locations(left)
    right_pages, right_slides = _candidate_locations(right)
    return bool(
        left_pages & right_pages
        or left_slides & right_slides
    )


def _claim_body(candidate: NodeCandidateIn) -> str:
    definition = candidate.definition.strip()
    if (
        definition
        and _claim_text_key(definition) not in {
            _claim_text_key(item)
            for item in _GENERIC_DEFINITIONS
        }
    ):
        return definition
    excerpts = [
        evidence.excerpt.strip()
        for evidence in candidate.evidence
        if (
            evidence.excerpt.strip()
            and _claim_text_key(evidence.excerpt)
            not in {
                _claim_text_key(item)
                for item in _GENERIC_DEFINITIONS
            }
        )
    ]
    return "。".join(excerpts) or candidate.name.strip()


def _claim_text_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\W_]+", "", normalized)


def _candidate_formula_text(candidate: NodeCandidateIn) -> str:
    parts = [candidate.name, candidate.definition]
    parts.extend(
        evidence.excerpt
        for evidence in candidate.evidence
        if evidence.excerpt
    )
    return "\n".join(parts)


def _translate_math_characters(value: str) -> str:
    translated = value.translate(_SUBSCRIPT_TRANSLATION)
    translated = translated.translate(_SUPERSCRIPT_TRANSLATION)
    translated = translated.replace("\\hbar", "ħ")
    translated = translated.replace("\\lambda", "λ")
    translated = translated.replace("\\nu", "ν")
    translated = re.sub(
        r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}",
        r"(\1)/(\2)",
        translated,
    )
    translated = unicodedata.normalize("NFKC", translated)
    return (
        translated.replace("ℏ", "ħ")
        .replace("·", "*")
        .replace("×", "*")
        .replace("−", "-")
        .replace("–", "-")
        .replace("—", "-")
    )


def _prepare_identifiers(expression: str) -> str:
    prepared = _translate_math_characters(expression)
    prepared = re.sub(
        r"(?<![A-Za-z0-9_])E_?([nN0-9])(?![A-Za-z0-9_])",
        lambda match: f"E_{match.group(1).lower()}",
        prepared,
    )
    prepared = re.sub(
        r"(?<![A-Za-z0-9_])L_?([xXyYzZ])(?![A-Za-z0-9_])",
        lambda match: f"L_{match.group(1).lower()}",
        prepared,
    )
    prepared = re.sub(
        r"(?<![A-Za-z0-9_])m_?([lLsSjJ])(?![A-Za-z0-9_ħ])",
        lambda match: f"m_{match.group(1).lower()}",
        prepared,
    )
    prepared = re.sub(
        r"(?<![A-Za-z0-9_])ml(?=ħ)",
        "m_l",
        prepared,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", "", prepared)


def _canonical_identifier(value: str) -> str:
    aliases = {
        "ħ": "hbar",
        "λ": "lambda",
        "Λ": "lambda",
        "ν": "nu",
        "Ν": "nu",
        "Δ": "delta",
        "δ": "delta",
        "μ": "mu",
        "Μ": "mu",
        "π": "pi",
        "Π": "pi",
        "σ": "sigma",
        "Σ": "sigma",
        "ω": "omega",
        "Ω": "omega",
    }
    return aliases.get(value, value.casefold())


def _parse_monomial(expression: str) -> _Monomial | None:
    try:
        return _MonomialParser(expression).parse()
    except (ValueError, ZeroDivisionError):
        return None


def _monomial_key(value: _Monomial) -> str:
    coefficient = value.coefficient
    powers = ",".join(
        f"{name}^{exponent}" for name, exponent in value.powers
    )
    return (
        f"{coefficient.numerator}/{coefficient.denominator}"
        f"|{powers}"
    )


def _single_variable(value: _Monomial | None) -> str | None:
    if (
        value is not None
        and value.coefficient == 1
        and len(value.powers) == 1
        and value.powers[0][1] == 1
    ):
        return value.powers[0][0]
    return None


def _formula_record(
    left: str,
    relation: str,
    right: str,
) -> _FormulaRecord | None:
    normalized_relation = {
        "≈": "~=",
        "≃": "~=",
        "≥": ">=",
        "≤": "<=",
    }.get(relation, relation)
    left_value = _parse_monomial(left)
    right_value = _parse_monomial(right)
    if left_value is None or right_value is None:
        return None

    left_subject = _single_variable(left_value)
    right_subject = _single_variable(right_value)
    subject = left_subject or right_subject
    variables = {
        name
        for value in (left_value, right_value)
        for name, _ in value.powers
    }
    left_compound = bool(
        len(left_value.powers) > 1
        or any(abs(exponent) != 1 for _, exponent in left_value.powers)
    )
    right_compound = bool(
        len(right_value.powers) > 1
        or any(abs(exponent) != 1 for _, exponent in right_value.powers)
    )
    material = bool(
        len(variables) >= 2
        and (
            normalized_relation not in {"=", "~="}
            or left_compound
            or right_compound
        )
    )
    if normalized_relation in {"=", "~="}:
        try:
            ratio = left_value.divided_by(right_value)
            inverse = right_value.divided_by(left_value)
        except (ValueError, ZeroDivisionError):
            return None
        ratio_key = min(_monomial_key(ratio), _monomial_key(inverse))
        fingerprint = f"{normalized_relation}:{ratio_key}"
    else:
        fingerprint = (
            f"{normalized_relation}:"
            f"{_monomial_key(left_value)}:"
            f"{_monomial_key(right_value)}"
        )
    return _FormulaRecord(
        fingerprint=fingerprint,
        relation=normalized_relation,
        subject=subject,
        material=material,
        variables=frozenset(variables),
    )


def _implicit_formula_records(value: str) -> list[_FormulaRecord]:
    compact = re.sub(r"\s+", "", _translate_math_characters(value))
    if "本征值" not in compact:
        return []
    subject = re.search(r"(?:L_z|Lz)", compact, flags=re.IGNORECASE)
    right = re.search(
        r"本征值(?:谱)?[^。；;，,]{0,24}?(?:为|是)"
        r"(?P<right>(?:m_l|ml)\*?ħ)",
        compact,
        flags=re.IGNORECASE,
    )
    if subject is None or right is None:
        return []
    record = _formula_record(subject.group(0), "=", right.group("right"))
    return [record] if record is not None else []


def _formula_records(candidate: NodeCandidateIn) -> tuple[_FormulaRecord, ...]:
    text = _translate_math_characters(_candidate_formula_text(candidate))
    records: list[_FormulaRecord] = []
    seen: set[str] = set()
    for match in _MATH_RELATION.finditer(text):
        record = _formula_record(
            match.group("left").strip(),
            match.group("relation"),
            match.group("right").strip(),
        )
        if record is None or record.fingerprint in seen:
            continue
        seen.add(record.fingerprint)
        records.append(record)
    for record in _implicit_formula_records(text):
        if record.fingerprint in seen:
            continue
        seen.add(record.fingerprint)
        records.append(record)
    return tuple(records)


def _formula_subject_conflict(
    left: tuple[_FormulaRecord, ...],
    right: tuple[_FormulaRecord, ...],
) -> bool:
    for left_item in left:
        if left_item.subject is None:
            continue
        for right_item in right:
            if (
                left_item.subject == right_item.subject
                and left_item.relation == right_item.relation
                and left_item.fingerprint != right_item.fingerprint
            ):
                return True
    return False


def _formula_contexts_are_compatible(
    left: tuple[_FormulaRecord, ...],
    right: tuple[_FormulaRecord, ...],
    shared_fingerprints: set[str],
) -> bool:
    """Reject panels that merely contain one formula from a broader claim.

    An extra material relation is allowed only when it defines a symbol that
    participates in the shared formula (for example ``E_1≈-13.6 eV`` beside
    ``E_n=E_1/n²``).  An independent ``S_z=m_s ħ`` panel must not collapse
    into a node whose claim is only ``L_z=m_l ħ``.
    """

    shared_variables = {
        variable
        for record in (*left, *right)
        if record.fingerprint in shared_fingerprints
        for variable in record.variables
    }
    for record in (*left, *right):
        if (
            not record.material
            or record.fingerprint in shared_fingerprints
        ):
            continue
        if (
            record.subject is None
            or record.subject not in shared_variables
        ):
            return False
    return True


def _normalize_prose(value: str) -> str:
    value = _translate_math_characters(value).casefold()
    value = value.replace("的", "").replace("了", "")
    result: list[str] = []
    separated = True
    for character in value:
        if (
            "\u4e00" <= character <= "\u9fff"
            or character.isalnum()
            or character in "_λνδμσπωħ"
        ):
            result.append(character)
            separated = False
        elif not separated:
            result.append(_PROSE_SEPARATOR)
            separated = True
    if result and result[-1] == _PROSE_SEPARATOR:
        result.pop()
    return "".join(result)


def _shared_exact_anchors(left: str, right: str) -> tuple[str, ...]:
    left_text = _normalize_prose(left)
    right_text = _normalize_prose(right)
    if not left_text or not right_text:
        return ()

    previous = [0] * (len(right_text) + 1)
    matches: list[tuple[int, int, int, str]] = []
    for left_index, left_character in enumerate(left_text, start=1):
        current = [0] * (len(right_text) + 1)
        if left_character == _PROSE_SEPARATOR:
            previous = current
            continue
        for right_index, right_character in enumerate(right_text, start=1):
            if (
                right_character == _PROSE_SEPARATOR
                or left_character != right_character
            ):
                continue
            length = previous[right_index - 1] + 1
            current[right_index] = length
            match_ended = (
                left_index == len(left_text)
                or right_index == len(right_text)
                or left_text[left_index] != right_text[right_index]
            )
            if length >= 3 and match_ended:
                start_left = left_index - length
                start_right = right_index - length
                matches.append(
                    (
                        start_left,
                        start_right,
                        length,
                        left_text[start_left:left_index],
                    )
                )
        previous = current

    selected: list[tuple[int, int, int, str]] = []
    seen_text: set[str] = set()
    for item in sorted(matches, key=lambda match: (-match[2], match[3])):
        start_left, start_right, length, text = item
        if text in seen_text or text in _GENERIC_ANCHORS:
            continue
        if text.isdigit():
            continue
        if any(
            _intervals_overlap(
                start_left,
                start_left + length,
                prior[0],
                prior[0] + prior[2],
            )
            or _intervals_overlap(
                start_right,
                start_right + length,
                prior[1],
                prior[1] + prior[2],
            )
            for prior in selected
        ):
            continue
        selected.append(item)
        seen_text.add(text)
    return tuple(item[3] for item in selected)


def _intervals_overlap(
    left_start: int,
    left_end: int,
    right_start: int,
    right_end: int,
) -> bool:
    return max(left_start, right_start) < min(left_end, right_end)


def _anchors_are_sufficient(anchors: tuple[str, ...]) -> bool:
    if any(len(anchor) >= 12 for anchor in anchors):
        return True
    score = sum(max(1, min(len(anchor), 8) - 2) for anchor in anchors)
    return bool(
        (len(anchors) >= 3 and score >= 3)
        or (len(anchors) >= 2 and score >= 7)
    )


def _is_visual_candidate(candidate: NodeCandidateIn) -> bool:
    return bool(
        candidate.role == "visual_knowledge"
        or candidate.type == "visual_knowledge"
        or any(
            item.startswith("visual:")
            for item in candidate.support_unit_ids
        )
    )


def _visual_label_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(
        r"(?:示意图|图示|曲线图|分布图|照片|图片|截图|图)$",
        "",
        normalized,
    )
    return re.sub(
        r"[^0-9a-z\u3400-\u9fffλνδμσπωħ]+",
        "",
        normalized,
    )


def _label_bigrams(value: str) -> set[str]:
    if len(value) < 2:
        return {value} if value else set()
    return {
        value[index : index + 2]
        for index in range(len(value) - 1)
    }


def _visual_label_similarity(
    left: NodeCandidateIn,
    right: NodeCandidateIn,
) -> float:
    left_key = _visual_label_key(left.name)
    right_key = _visual_label_key(right.name)
    if not left_key or not right_key:
        return 0
    if left_key in right_key or right_key in left_key:
        return 1
    left_bigrams = _label_bigrams(left_key)
    right_bigrams = _label_bigrams(right_key)
    union = left_bigrams | right_bigrams
    if not union:
        return 0
    return len(left_bigrams & right_bigrams) / len(union)


def _anchor_coverage(
    left_body: str,
    right_body: str,
    anchors: tuple[str, ...],
) -> float:
    left_length = len(
        _normalize_prose(left_body).replace(_PROSE_SEPARATOR, "")
    )
    right_length = len(
        _normalize_prose(right_body).replace(_PROSE_SEPARATOR, "")
    )
    denominator = min(left_length, right_length)
    if denominator <= 0:
        return 0
    return min(
        1,
        sum(len(anchor) for anchor in anchors) / denominator,
    )


def _prose_equivalence_supported(
    left: NodeCandidateIn,
    right: NodeCandidateIn,
    left_body: str,
    right_body: str,
    anchors: tuple[str, ...],
) -> bool:
    if not anchors:
        return False

    coverage = _anchor_coverage(
        left_body,
        right_body,
        anchors,
    )
    longest_anchor = max(len(anchor) for anchor in anchors)
    anchor_characters = sum(len(anchor) for anchor in anchors)

    if _is_structural(left) or _is_structural(right):
        return bool(
            longest_anchor >= 10
            and coverage >= 0.4
        )

    visual_pair = (
        _is_visual_candidate(left)
        != _is_visual_candidate(right)
    )
    shared_asset = bool(
        _candidate_assets(left) & _candidate_assets(right)
    )
    if visual_pair and shared_asset:
        return bool(
            _anchors_are_sufficient(anchors)
            and coverage >= 0.2
            and _visual_label_similarity(left, right) >= 0.3
        )

    return bool(
        (
            longest_anchor >= 12
            and coverage >= 0.45
        )
        or (
            coverage >= 0.75
            and anchor_characters >= 8
        )
    )


def _has_opposite_terms(left: str, right: str) -> bool:
    left_text = _normalize_prose(left)
    right_text = _normalize_prose(right)
    for positive, negative in _OPPOSITE_TERM_PAIRS:
        if (
            positive in left_text
            and negative in right_text
            and negative not in left_text
            and positive not in right_text
        ):
            return True
        if (
            negative in left_text
            and positive in right_text
            and positive not in left_text
            and negative not in right_text
        ):
            return True
    return False


def _causal_edges(value: str) -> tuple[tuple[str, str], ...]:
    edges: list[tuple[str, str]] = []
    translated = _translate_math_characters(value)
    for sentence in _SENTENCE_SPLIT.split(translated):
        for marker in _CAUSAL_MARKERS:
            if marker not in sentence:
                continue
            source, target = sentence.split(marker, maxsplit=1)
            source_key = _normalize_prose(source).replace(
                _PROSE_SEPARATOR,
                "",
            )
            target_key = _normalize_prose(target).replace(
                _PROSE_SEPARATOR,
                "",
            )
            if len(source_key) >= 2 and len(target_key) >= 2:
                edges.append((source_key[-24:], target_key[:24]))
    return tuple(edges)


def _same_causal_entity(left: str, right: str) -> bool:
    return bool(
        left == right
        or (len(left) >= 4 and left in right)
        or (len(right) >= 4 and right in left)
    )


def _has_reversed_causality(left: str, right: str) -> bool:
    for left_source, left_target in _causal_edges(left):
        for right_source, right_target in _causal_edges(right):
            if (
                _same_causal_entity(left_source, right_target)
                and _same_causal_entity(left_target, right_source)
            ):
                return True
    return False


def _numeric_claims(value: str) -> set[str]:
    normalized = _translate_math_characters(value)
    return {
        match.group(0).lstrip("+")
        for match in _NUMBER.finditer(normalized)
    }


def _has_numeric_conflict(left: str, right: str) -> bool:
    left_numbers = _numeric_claims(left)
    right_numbers = _numeric_claims(right)
    if not left_numbers or not right_numbers:
        return False
    if left_numbers == right_numbers:
        return False
    return bool(
        not left_numbers & right_numbers
        or (
            len(left_numbers) == 1
            and len(right_numbers) == 1
        )
    )
