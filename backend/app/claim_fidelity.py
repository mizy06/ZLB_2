from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable, Literal


ClaimFidelityIssueCode = Literal[
    "unsupported_relation",
    "unsupported_number",
    "extreme_scientific_value_missing_dimension",
    "conflicting_relation",
]
ClaimFidelityIssueSeverity = Literal["soft", "hard"]


@dataclass(frozen=True, slots=True)
class ClaimFidelityIssue:
    code: ClaimFidelityIssueCode
    fragment: str
    severity: ClaimFidelityIssueSeverity = "soft"


@dataclass(frozen=True, slots=True)
class _RelationClaim:
    fragment: str
    left: str
    operator: str
    right: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _Monomial:
    coefficient: Fraction
    powers: tuple[tuple[str, int], ...]
    factor_inventory: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class _MonomialRelation:
    coefficient: Fraction
    powers: tuple[tuple[str, int], ...]
    factor_inventory: tuple[tuple[str, int], ...]


_SUPERSCRIPT_DIGITS = str.maketrans(
    {
        "⁰": "0",
        "¹": "1",
        "²": "2",
        "³": "3",
        "⁴": "4",
        "⁵": "5",
        "⁶": "6",
        "⁷": "7",
        "⁸": "8",
        "⁹": "9",
        "⁺": "+",
        "⁻": "-",
    }
)
_SUPERSCRIPT_RUN = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+")
_SUBSCRIPT_CHARACTERS = {
    "₀": "0",
    "₁": "1",
    "₂": "2",
    "₃": "3",
    "₄": "4",
    "₅": "5",
    "₆": "6",
    "₇": "7",
    "₈": "8",
    "₉": "9",
    "ₐ": "a",
    "ₑ": "e",
    "ₕ": "h",
    "ᵢ": "i",
    "ⱼ": "j",
    "ₖ": "k",
    "ₗ": "l",
    "ₘ": "m",
    "ₙ": "n",
    "ₒ": "o",
    "ₚ": "p",
    "ᵣ": "r",
    "ₛ": "s",
    "ₜ": "t",
    "ᵤ": "u",
    "ᵥ": "v",
    "ₓ": "x",
}
_SUBSCRIPT_TRANSLATION = str.maketrans(_SUBSCRIPT_CHARACTERS)
_SUBSCRIPT_RUN = re.compile(
    "[" + re.escape("".join(_SUBSCRIPT_CHARACTERS)) + "]+"
)
_CANONICAL_TRANSLATION = str.maketrans(
    {
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
        "∕": "/",
        "≃": "≈",
        "≅": "≈",
        "∼": "≈",
        "~": "≈",
        "ℏ": "ħ",
    }
)
_RELATION_OPERATOR = re.compile(r"<=|>=|!=|≤|≥|≈|∝|=|<|>")
_HARD_COMPARABLE_RELATION_OPERATORS = frozenset({"=", "≈"})
_MONOMIAL_NUMBER = re.compile(
    r"(?:\d+(?:\.\d+)?e[+-]?\d+|\d+(?:\.\d+)?)"
)
_NUMBER = re.compile(
    r"(?<![\d.])(?:"
    r"(?:\d+(?:\.\d+)?\*)?10\^[+-]?\d+"
    r"|\d+(?:\.\d+)?e[+-]?\d+"
    r"|\d+(?:\.\d+)?"
    r")(?![\d.])"
)
_SCIENTIFIC_NUMBER = re.compile(
    r"(?<![\d.])(?:"
    r"(?:(?:\d+(?:\.\d+)?)\*)?10\^(?P<power_exp>[+-]?\d+)"
    r"|(?:\d+(?:\.\d+)?)e(?P<e_exp>[+-]?\d+)"
    r")(?![\d.])"
)
_DIMENSIONLESS_MARKERS = (
    "概率",
    "相对",
    "比值",
    "比率",
    "比例",
    "无量纲",
    "归一化",
    "占比",
    "误差率",
    "数量",
    "个数",
    "计数",
    "倍数",
    "probability",
    "relative",
    "ratio",
    "fraction",
    "dimensionless",
    "normalized",
    "normalised",
)
_UNIT_MARKERS = tuple(
    sorted(
        {
            "thz",
            "ghz",
            "mhz",
            "khz",
            "hz",
            "gev",
            "mev",
            "kev",
            "ev",
            "nm",
            "μm",
            "um",
            "mm",
            "cm",
            "km",
            "kg",
            "mg",
            "μg",
            "ns",
            "μs",
            "us",
            "ms",
            "mol",
            "pa",
            "kpa",
            "mpa",
            "gpa",
            "wb",
            "lm",
            "lx",
            "m/s",
            "m*s",
            "s^-1",
            "rad",
            "sr",
            "米",
            "秒",
            "赫兹",
            "焦耳",
            "电子伏特",
            "开尔文",
            "特斯拉",
            "帕斯卡",
            "瓦特",
            "伏特",
            "安培",
            "库仑",
            "欧姆",
            "流明",
            "勒克斯",
            "m",
            "s",
            "g",
            "k",
            "a",
            "v",
            "w",
            "j",
            "t",
        },
        key=lambda item: (-len(item), item),
    )
)


def canonicalize_claim_text(value: str) -> str:
    """Normalize compatibility glyphs without fuzzy or semantic matching."""

    value = _SUPERSCRIPT_RUN.sub(
        lambda match: "^" + match.group(0).translate(_SUPERSCRIPT_DIGITS),
        value,
    )
    value = _SUBSCRIPT_RUN.sub(
        lambda match: "_"
        + match.group(0).translate(_SUBSCRIPT_TRANSLATION),
        value,
    )
    value = unicodedata.normalize("NFKC", value)
    value = value.translate(_CANONICAL_TRANSLATION)
    return "".join(
        character
        for character in value.casefold()
        if not character.isspace()
        and unicodedata.category(character) != "Cf"
    )


def _is_cjk(character: str) -> bool:
    return (
        "\u3400" <= character <= "\u4dbf"
        or "\u4e00" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
    )


def _is_operand_character(character: str) -> bool:
    if character.isdigit():
        return True
    if character.isalpha() and not _is_cjk(character):
        return True
    return character in "_.+-*/^%ħπ∞"


def _relation_claims(canonical_definition: str) -> tuple[_RelationClaim, ...]:
    claims: list[_RelationClaim] = []
    seen: set[tuple[int, int, str]] = set()
    for operator_match in _RELATION_OPERATOR.finditer(canonical_definition):
        left_start = operator_match.start()
        while (
            left_start > 0
            and _is_operand_character(
                canonical_definition[left_start - 1]
            )
        ):
            left_start -= 1
        right_end = operator_match.end()
        while (
            right_end < len(canonical_definition)
            and _is_operand_character(canonical_definition[right_end])
        ):
            right_end += 1
        left = canonical_definition[
            left_start : operator_match.start()
        ].strip(".")
        right = canonical_definition[
            operator_match.end() : right_end
        ].strip(".")
        if not left or not right:
            continue
        fragment = (
            left
            + operator_match.group(0)
            + right
        )
        key = (left_start, right_end, fragment)
        if key in seen:
            continue
        seen.add(key)
        claims.append(
            _RelationClaim(
                fragment=fragment,
                left=left,
                operator=operator_match.group(0),
                right=right,
                start=left_start,
                end=right_end,
            )
        )
    return tuple(claims)


def _parse_monomial(expression: str) -> _Monomial | None:
    """Parse a narrow product/division expression without fuzzy matching."""

    coefficient = Fraction(1)
    powers: Counter[str] = Counter()
    inventory: Counter[str] = Counter()
    index = 0
    pending_direction = 1
    needs_factor = True

    while index < len(expression):
        character = expression[index]
        if character in "*/":
            if needs_factor:
                return None
            pending_direction = -1 if character == "/" else 1
            needs_factor = True
            index += 1
            continue
        if character in "+-%∞":
            return None

        number_match = _MONOMIAL_NUMBER.match(expression, index)
        factor: str | Fraction
        inventory_key: str
        if number_match is not None:
            number_text = number_match.group(0)
            try:
                factor = Fraction(number_text)
            except (ValueError, ZeroDivisionError):
                return None
            inventory_key = f"number:{factor}"
            index = number_match.end()
        elif character.isalpha() and not _is_cjk(character):
            factor_end = index + 1
            if (
                factor_end < len(expression)
                and expression[factor_end] == "_"
            ):
                subscript_start = factor_end + 1
                if subscript_start >= len(expression):
                    return None
                subscript_end = subscript_start + 1
                if expression[subscript_start].isdigit():
                    while (
                        subscript_end < len(expression)
                        and expression[subscript_end].isdigit()
                    ):
                        subscript_end += 1
                elif not (
                    expression[subscript_start].isalpha()
                    and not _is_cjk(expression[subscript_start])
                ):
                    return None
                factor_end = subscript_end
            factor = expression[index:factor_end]
            inventory_key = f"symbol:{factor}"
            index = factor_end
        else:
            return None

        exponent = 1
        if index < len(expression) and expression[index] == "^":
            exponent_start = index + 1
            exponent_end = exponent_start
            if (
                exponent_end < len(expression)
                and expression[exponent_end] in "+-"
            ):
                exponent_end += 1
            digit_start = exponent_end
            while (
                exponent_end < len(expression)
                and expression[exponent_end].isdigit()
            ):
                exponent_end += 1
            if digit_start == exponent_end:
                return None
            exponent = int(expression[exponent_start:exponent_end])
            index = exponent_end

        signed_exponent = pending_direction * exponent
        inventory[inventory_key] += abs(exponent)
        if isinstance(factor, Fraction):
            if factor == 0 and signed_exponent < 0:
                return None
            coefficient *= factor ** signed_exponent
        else:
            powers[factor] += signed_exponent
        pending_direction = 1
        needs_factor = False

    if needs_factor:
        return None
    return _Monomial(
        coefficient=coefficient,
        powers=tuple(sorted(
            (symbol, power)
            for symbol, power in powers.items()
            if power
        )),
        factor_inventory=tuple(sorted(
            (factor, count)
            for factor, count in inventory.items()
            if count
        )),
    )


def _monomial_relation(
    relation: _RelationClaim,
) -> _MonomialRelation | None:
    if relation.operator not in _HARD_COMPARABLE_RELATION_OPERATORS:
        return None
    left = _parse_monomial(relation.left)
    right = _parse_monomial(relation.right)
    if left is None or right is None or right.coefficient == 0:
        return None

    powers = Counter(dict(left.powers))
    powers.subtract(dict(right.powers))
    inventory = Counter(dict(left.factor_inventory))
    inventory.update(dict(right.factor_inventory))
    return _MonomialRelation(
        coefficient=left.coefficient / right.coefficient,
        powers=tuple(sorted(
            (symbol, power)
            for symbol, power in powers.items()
            if power
        )),
        factor_inventory=tuple(sorted(
            (factor, count)
            for factor, count in inventory.items()
            if count
        )),
    )


def _relations_are_equivalent(
    first: _MonomialRelation,
    second: _MonomialRelation,
) -> bool:
    if (
        first.coefficient == second.coefficient
        and first.powers == second.powers
    ):
        return True
    if first.coefficient == 0 or second.coefficient == 0:
        return False
    inverted_powers = tuple(
        (symbol, -power)
        for symbol, power in first.powers
    )
    return (
        second.coefficient == 1 / first.coefficient
        and second.powers == inverted_powers
    )


def _factor_inventory_parts(
    inventory: tuple[tuple[str, int], ...],
) -> tuple[Counter[str], dict[str, Counter[str | None]]]:
    numbers: Counter[str] = Counter()
    symbols: dict[str, Counter[str | None]] = {}
    for factor, count in inventory:
        kind, _, value = factor.partition(":")
        if kind == "number":
            numbers[value] += count
            continue
        if kind != "symbol":
            continue
        base, separator, subscript = value.partition("_")
        symbols.setdefault(base, Counter())[
            subscript if separator else None
        ] += count
    return numbers, symbols


def _definition_inventory_corresponds_to_evidence(
    definition_inventory: tuple[tuple[str, int], ...],
    evidence_inventory: tuple[tuple[str, int], ...],
) -> bool:
    definition_numbers, definition_symbols = _factor_inventory_parts(
        definition_inventory
    )
    evidence_numbers, evidence_symbols = _factor_inventory_parts(
        evidence_inventory
    )
    if definition_numbers != evidence_numbers:
        return False
    if definition_symbols.keys() != evidence_symbols.keys():
        return False

    for base, definition_subscripts in definition_symbols.items():
        remaining_evidence = evidence_symbols[base].copy()
        for subscript, count in definition_subscripts.items():
            if subscript is None:
                continue
            if remaining_evidence[subscript] < count:
                return False
            remaining_evidence[subscript] -= count
        definition_unspecified = definition_subscripts[None]
        remaining_count = sum(remaining_evidence.values())
        if definition_unspecified != remaining_count:
            return False
    return True


def _has_conflicting_evidence_relation(
    definition_relation: _RelationClaim,
    evidence_relations: tuple[_RelationClaim, ...],
) -> bool:
    definition_monomial = _monomial_relation(definition_relation)
    if definition_monomial is None:
        return False

    for evidence_relation in evidence_relations:
        if evidence_relation.operator != definition_relation.operator:
            continue
        evidence_monomial = _monomial_relation(evidence_relation)
        if evidence_monomial is None:
            continue
        if _relations_are_equivalent(
            definition_monomial,
            evidence_monomial,
        ):
            continue
        if _definition_inventory_corresponds_to_evidence(
            definition_monomial.factor_inventory,
            evidence_monomial.factor_inventory,
        ):
            return True
    return False


def _number_claims(
    canonical_definition: str,
) -> tuple[tuple[str, int, int], ...]:
    return tuple(
        (match.group(0), match.start(), match.end())
        for match in _NUMBER.finditer(canonical_definition)
    )


def _has_unit_suffix(canonical_definition: str, end: int) -> bool:
    tail = canonical_definition[end : end + 16]
    if tail.startswith(("%", "‰")):
        return True
    for unit in _UNIT_MARKERS:
        if not tail.startswith(unit):
            continue
        following = tail[len(unit) : len(unit) + 1]
        if following and following.isascii() and following.isalpha():
            continue
        return True
    return False


def _has_dimensionless_context(
    canonical_definition: str,
    start: int,
    end: int,
    relations: tuple[_RelationClaim, ...],
) -> bool:
    context = canonical_definition[
        max(0, start - 32) : min(len(canonical_definition), end + 32)
    ]
    for marker in _DIMENSIONLESS_MARKERS:
        marker_start = context.find(marker)
        while marker_start >= 0:
            marker_end = marker_start + len(marker)
            if marker != "数量" or context[marker_end:marker_end + 1] != "级":
                return True
            marker_start = context.find(marker, marker_end)
    return any(
        relation.start <= start
        and end <= relation.end
        and "/" in relation.left
        for relation in relations
    )


def claim_fidelity_issues(
    definition: str,
    evidence_excerpts: Iterable[str],
) -> tuple[ClaimFidelityIssue, ...]:
    """Return deterministic formula, number, and dimension fidelity issues."""

    canonical_definition = canonicalize_claim_text(definition)
    canonical_evidence = tuple(
        canonical
        for excerpt in evidence_excerpts
        if (canonical := canonicalize_claim_text(excerpt))
    )
    relations = _relation_claims(canonical_definition)
    evidence_relations = tuple(
        relation
        for evidence in canonical_evidence
        for relation in _relation_claims(evidence)
    )
    issues: list[ClaimFidelityIssue] = []

    for relation in relations:
        relation_is_supported = any(
            relation.fragment in evidence
            for evidence in canonical_evidence
        )
        if relation_is_supported:
            continue
        issues.append(
            ClaimFidelityIssue(
                code="unsupported_relation",
                fragment=relation.fragment,
            )
        )
        if _has_conflicting_evidence_relation(
            relation,
            evidence_relations,
        ):
            issues.append(
                ClaimFidelityIssue(
                    code="conflicting_relation",
                    fragment=relation.fragment,
                    severity="hard",
                )
            )

    for number, _, _ in _number_claims(canonical_definition):
        if not any(number in evidence for evidence in canonical_evidence):
            issues.append(
                ClaimFidelityIssue(
                    code="unsupported_number",
                    fragment=number,
                )
            )

    for scientific_match in _SCIENTIFIC_NUMBER.finditer(
        canonical_definition
    ):
        exponent_text = (
            scientific_match.group("power_exp")
            or scientific_match.group("e_exp")
        )
        if abs(int(exponent_text)) < 6:
            continue
        if _has_unit_suffix(
            canonical_definition,
            scientific_match.end(),
        ):
            continue
        if _has_dimensionless_context(
            canonical_definition,
            scientific_match.start(),
            scientific_match.end(),
            relations,
        ):
            continue
        issues.append(
            ClaimFidelityIssue(
                code="extreme_scientific_value_missing_dimension",
                fragment=scientific_match.group(0),
                severity="hard",
            )
        )

    deduped: list[ClaimFidelityIssue] = []
    seen_issues: set[tuple[str, str]] = set()
    for issue in issues:
        key = (issue.code, issue.fragment)
        if key in seen_issues:
            continue
        seen_issues.add(key)
        deduped.append(issue)
    return tuple(deduped)


def claim_is_faithful(
    definition: str,
    evidence_excerpts: Iterable[str],
) -> bool:
    return not claim_fidelity_issues(definition, evidence_excerpts)


def hard_claim_fidelity_issues(
    definition: str,
    evidence_excerpts: Iterable[str],
) -> tuple[ClaimFidelityIssue, ...]:
    """Return only deterministic issues safe enough for a hard gate."""

    return tuple(
        issue
        for issue in claim_fidelity_issues(
            definition,
            evidence_excerpts,
        )
        if issue.severity == "hard"
    )
