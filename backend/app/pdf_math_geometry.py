from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping, Sequence


_PRIVATE_USE_OR_REPLACEMENT = re.compile(r"[\ue000-\uf8ff\ufffd]")
_RELATION = re.compile(r"[=≈≃≅≤≥<>]")
_DIGITS = re.compile(r"\d{1,3}")
_POWER = re.compile(r"[−-]?\d{1,3}")
_SUBSCRIPT = re.compile(r"[A-Za-z]")
_TRIG_MULTIPLIER_SUFFIX = re.compile(
    r"(?:sin|cos|tan|cot|ctg|sec|csc|sinh|cosh|tanh)"
    r"[A-Za-zΑ-ωΔ]+$",
    re.IGNORECASE,
)
_CJK_SPACE = re.compile(
    r"([\u3400-\u9fff：])\s+(?=[\u3400-\u9fff])"
)
_SYMBOL_FONT_PUA_TRANSLATION = str.maketrans(
    {
        "\uf03e": ">",
        "\uf040": "≈",
        "\uf044": "Δ",
        "\uf057": "Ω",
        "\uf06c": "λ",
        "\uf06e": "ν",
        "\uf0b4": "×",
        "\uf0bb": "≈",
        "\uf0d7": "·",
        "\uf0de": "⇒",
    }
)


@dataclass(frozen=True, slots=True)
class PdfGlyph:
    text: str
    font: str
    size: float
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class MathLayoutCandidate:
    canonical: str
    source_bbox: tuple[float, float, float, float]
    confidence: float
    kind: str
    origin: str = "pdfplumber-geometry"
    issues: tuple[str, ...] = ()


@dataclass(slots=True)
class _GeometryToken:
    text: str
    font: str
    size: float
    x0: float
    x1: float
    top: float
    bottom: float

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.x0, self.top, self.x1, self.bottom)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _glyph_text(text: str, font: str) -> str:
    if "symbol" in font.casefold():
        return text.translate(_SYMBOL_FONT_PUA_TRANSLATION)
    return text


def _tokens_from_chars(
    chars: Iterable[Mapping[str, Any]],
) -> list[_GeometryToken]:
    tokens: list[_GeometryToken] = []
    ordered = sorted(
        (
            char
            for char in chars
            if str(char.get("text", "")).strip()
        ),
        key=lambda char: (
            round(_number(char.get("top")), 1),
            _number(char.get("x0")),
        ),
    )
    for char in ordered:
        font = str(char.get("fontname", ""))
        text = _glyph_text(str(char.get("text", "")), font)
        token = _GeometryToken(
            text=text,
            font=font,
            size=_number(char.get("size")),
            x0=_number(char.get("x0")),
            x1=_number(char.get("x1")),
            top=_number(char.get("top")),
            bottom=_number(char.get("bottom")),
        )
        if tokens:
            previous = tokens[-1]
            gap = token.x0 - previous.x1
            same_span = (
                previous.font == token.font
                and abs(previous.top - token.top) <= 1.1
                and abs(previous.bottom - token.bottom) <= 1.1
                and abs(previous.size - token.size) <= 1.0
                and -token.size * 0.2
                <= gap
                <= max(2.5, token.size * 0.2)
            )
            if same_span:
                previous.text += token.text
                previous.x1 = max(previous.x1, token.x1)
                continue
        tokens.append(token)
    return tokens


def _find_script(
    base: _GeometryToken,
    tokens: Sequence[_GeometryToken],
    *,
    kind: str,
    pattern: re.Pattern[str],
) -> _GeometryToken | None:
    script_tokens: list[_GeometryToken] = []
    for token in tokens:
        if token is base or token.size >= base.size * 0.84:
            continue
        if not (
            base.x1 - base.size * 0.22
            <= token.x0
            <= base.x1 + base.size * 0.7
        ):
            continue
        if kind == "super":
            aligned = (
                base.top - base.size * 0.48
                <= token.top
                <= base.top + base.size * 0.17
                and token.bottom
                <= base.bottom - base.size * 0.22
            )
        else:
            aligned = (
                base.top + base.size * 0.28
                <= token.top
                <= base.top + base.size * 0.9
                and token.bottom
                <= base.bottom + base.size * 0.3
            )
        if aligned:
            script_tokens.append(token)

    clusters: list[_GeometryToken] = []
    for token in sorted(script_tokens, key=lambda item: item.x0):
        if clusters:
            previous = clusters[-1]
            gap = token.x0 - previous.x1
            same_cluster = (
                abs(previous.top - token.top) <= 1.1
                and abs(previous.bottom - token.bottom) <= 1.1
                and abs(previous.size - token.size) <= 1.0
                and -token.size * 0.2
                <= gap
                <= max(2.5, token.size * 0.2)
            )
            if same_cluster:
                previous.text += token.text
                previous.x1 = max(previous.x1, token.x1)
                continue
        clusters.append(
            _GeometryToken(
                text=token.text,
                font=token.font,
                size=token.size,
                x0=token.x0,
                x1=token.x1,
                top=token.top,
                bottom=token.bottom,
            )
        )

    candidates: list[tuple[float, _GeometryToken]] = []
    for token in clusters:
        if pattern.fullmatch(token.text):
            candidates.append((abs(token.x0 - base.x1), token))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])[1]


def _decorate_token(
    token: _GeometryToken,
    tokens: Sequence[_GeometryToken],
) -> str:
    text = token.text
    if text == "10":
        exponent = _find_script(
            token,
            tokens,
            kind="super",
            pattern=_POWER,
        )
        if exponent:
            power = exponent.text.replace("−", "-")
            return f"10^{power}"
        return text

    if text == "m" or text == "cm" or text.endswith("/cm"):
        exponent = _find_script(
            token,
            tokens,
            kind="super",
            pattern=_DIGITS,
        )
        if exponent:
            return f"{text}^{exponent.text}"
        return text

    if re.fullmatch(r"(?:Δ)?[A-Za-zΑ-ω]+", text):
        subscript = _find_script(
            token,
            tokens,
            kind="sub",
            pattern=_SUBSCRIPT,
        )
        if subscript:
            return f"{text}_{subscript.text}"
    return text


def _bbox_union(
    tokens: Sequence[_GeometryToken],
) -> tuple[float, float, float, float]:
    if not tokens:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        min(token.x0 for token in tokens),
        min(token.top for token in tokens),
        max(token.x1 for token in tokens),
        max(token.bottom for token in tokens),
    )


def _candidate_issues(canonical: str) -> tuple[str, ...]:
    compact = re.sub(r"\s+", "", canonical)
    issues: list[str] = []
    if _PRIVATE_USE_OR_REPLACEMENT.search(canonical):
        issues.append("residual_private_use_glyph")
    if "==" in compact:
        issues.append("empty_relation_operand")
    if compact and (
        _RELATION.match(compact) or _RELATION.search(compact[-1:])
    ):
        issues.append("missing_relation_operand")
    if any(
        compact.count(opening) != compact.count(closing)
        for opening, closing in (("(", ")"), ("[", "]"), ("{", "}"))
    ):
        issues.append("unbalanced_delimiter")
    if canonical.rstrip().endswith(("，", ",", "；", ";", "：", ":")):
        issues.append("trailing_layout_punctuation")
    if "ˆ" in canonical:
        issues.append("unresolved_layout_diacritic")
    if re.search(r"(?:×|x|\*)10(?!\^-?\d)", compact):
        issues.append("scientific_exponent_missing")
    if re.search(r"(?<![\d^])10(?:1[1-9]|[2-9]\d)\s*W/cm2", compact):
        issues.append("collapsed_scientific_exponent")
    if (
        re.search(r"\bE_[A-Za-z0-9]+=[^=]*/n(?:$|[A-Za-z])", compact)
        and not re.search(r"/n(?:\^2|²)", compact)
    ):
        issues.append("indexed_energy_denominator_incomplete")
    fraction_suffix = re.search(r"\)([A-Za-zΑ-ωΔ]+)$", compact)
    if (
        "/" in compact
        and fraction_suffix
        and not _TRIG_MULTIPLIER_SUFFIX.fullmatch(
            fraction_suffix.group(1)
        )
    ):
        issues.append("orphan_fraction_suffix")
    if re.search(
        r"\bd([A-Za-zΑ-ω])/\1=[−-]?[A-Za-zΑ-ω]$",
        compact,
    ):
        issues.append("differential_factor_missing")
    if re.search(
        r"^N(?:_[^/=]+)?/N(?:_[^=]+)?=e$",
        compact,
    ):
        issues.append("decay_exponent_missing")
    if "/" in compact:
        for left, right in re.findall(
            r"([^=≈<>]*)/([^=≈<>]*)",
            compact,
        ):
            if not left or not right:
                issues.append("incomplete_fraction")
                break
    return tuple(dict.fromkeys(issues))


def _make_candidate(
    canonical: str,
    tokens: Sequence[_GeometryToken],
    *,
    confidence: float,
    kind: str,
) -> MathLayoutCandidate | None:
    canonical = canonical.strip()
    if not canonical:
        return None
    issues = _candidate_issues(canonical)
    if issues:
        return None
    return MathLayoutCandidate(
        canonical=canonical,
        source_bbox=_bbox_union(tokens),
        confidence=confidence,
        kind=kind,
    )


def _fraction_side(
    side_tokens: Sequence[_GeometryToken],
    all_tokens: Sequence[_GeometryToken],
) -> str:
    if not side_tokens:
        return ""
    main_size = max(token.size for token in side_tokens)
    main_tokens = [
        token
        for token in side_tokens
        if token.size >= main_size * 0.82
    ]
    return "".join(
        _decorate_token(token, all_tokens)
        for token in sorted(main_tokens, key=lambda item: item.x0)
    )


def _fraction_text(numerator: str, denominator: str) -> str:
    if any(operator in numerator for operator in ("+", "−")):
        numerator = f"({numerator})"
    if any(operator in denominator for operator in ("×", "·", "+", "−")):
        denominator = f"({denominator})"
    return f"{numerator}/{denominator}"


def _horizontal_fraction_candidates(
    tokens: Sequence[_GeometryToken],
    lines: Iterable[Mapping[str, Any]],
) -> list[MathLayoutCandidate]:
    horizontal_lines = []
    for line in lines:
        x0 = _number(line.get("x0"))
        x1 = _number(line.get("x1"))
        top = _number(line.get("top"))
        bottom = _number(line.get("bottom"), top)
        width = _number(line.get("width"), x1 - x0)
        if abs(top - bottom) < 1 and 20 <= width <= 220:
            horizontal_lines.append(
                {
                    "x0": x0,
                    "x1": x1,
                    "top": top,
                    "bottom": bottom,
                    "width": width,
                }
            )

    groups: list[tuple[float, list[dict[str, float]]]] = []
    for line in sorted(
        horizontal_lines,
        key=lambda item: (round(item["top"], 1), item["x0"]),
    ):
        if groups and abs(line["top"] - groups[-1][0]) <= 2:
            groups[-1][1].append(line)
        else:
            groups.append((line["top"], [line]))

    candidates: list[MathLayoutCandidate] = []
    for line_y, group in groups:
        fractions: list[
            tuple[float, float, str, list[_GeometryToken]]
        ] = []
        for line in group:
            inside = [
                token
                for token in tokens
                if token.x1 >= line["x0"] - 3
                and token.x0 <= line["x1"] + 3
            ]
            numerator_tokens = [
                token
                for token in inside
                if 0
                <= line_y - token.bottom
                <= max(16, token.size * 0.55)
                and token.size >= 18
            ]
            denominator_tokens = [
                token
                for token in inside
                if 0
                <= token.top - line_y
                <= max(16, token.size * 0.55)
                and token.size >= 18
            ]
            numerator = _fraction_side(numerator_tokens, tokens)
            denominator = _fraction_side(denominator_tokens, tokens)
            if numerator and denominator:
                fractions.append(
                    (
                        line["x0"],
                        line["x1"],
                        _fraction_text(numerator, denominator),
                        [*numerator_tokens, *denominator_tokens],
                    )
                )
        if not fractions:
            continue

        left = min(item[0] for item in fractions)
        right = max(item[1] for item in fractions)
        equation_tokens: list[_GeometryToken] = []
        elements: list[tuple[float, str]] = [
            ((x0 + x1) / 2, fraction)
            for x0, x1, fraction, _ in fractions
        ]
        for _, _, _, fraction_tokens in fractions:
            equation_tokens.extend(fraction_tokens)
        for token in tokens:
            if token.size < 24:
                continue
            if abs(token.center_y - line_y) > 9:
                continue
            if not left - 100 <= token.x0 <= right + 80:
                continue
            if any(
                token.x0 >= x0 - 3 and token.x1 <= x1 + 3
                for x0, x1, _, _ in fractions
            ):
                continue
            elements.append(
                (token.x0, _decorate_token(token, tokens))
            )
            equation_tokens.append(token)

        canonical = "".join(
            text for _, text in sorted(elements, key=lambda item: item[0])
        )
        if "/" not in canonical or not _RELATION.search(canonical):
            continue
        full = _make_candidate(
            canonical,
            equation_tokens,
            confidence=0.98,
            kind="horizontal_fraction_equation",
        )
        if full:
            candidates.append(full)

        ordered_fractions = sorted(fractions, key=lambda item: item[0])
        if len(ordered_fractions) < 2:
            continue
        first_x0, first_x1, first_fraction, _ = ordered_fractions[0]
        last_x0, last_x1, _, _ = ordered_fractions[-1]
        prefix = "".join(
            token.text
            for token in sorted(equation_tokens, key=lambda item: item.x0)
            if token.x1 < first_x0
            and abs(token.center_y - line_y) <= 9
        )
        suffix = "".join(
            token.text
            for token in sorted(equation_tokens, key=lambda item: item.x0)
            if token.x0 > last_x1
            and abs(token.center_y - line_y) <= 9
        )
        simplified = f"{prefix}{first_fraction}{suffix}"
        if (
            prefix.endswith("=")
            and _RELATION.search(suffix)
            and first_x1 <= last_x0
        ):
            concise = _make_candidate(
                simplified,
                equation_tokens,
                confidence=0.99,
                kind="horizontal_fraction_identity",
            )
            if concise:
                candidates.append(concise)
    return candidates


def _join_geometry_row(
    row_tokens: Sequence[_GeometryToken],
    all_tokens: Sequence[_GeometryToken],
) -> str:
    canonical = " ".join(
        _decorate_token(token, all_tokens)
        for token in sorted(row_tokens, key=lambda item: item.x0)
    )
    canonical = re.sub(r"\s+([：，。])", r"\1", canonical)
    while _CJK_SPACE.search(canonical):
        canonical = _CJK_SPACE.sub(r"\1", canonical)
    canonical = re.sub(r"\bW\s+m\^2\b", "W/m²", canonical)
    canonical = canonical.replace("W/cm^2", "W/cm²")
    canonical = canonical.replace("/cm^2", "/cm²")
    canonical = re.sub(r"\s*·\s*", "·", canonical)
    return canonical.strip()


def _scientific_line_candidates(
    tokens: Sequence[_GeometryToken],
) -> list[MathLayoutCandidate]:
    candidates: list[MathLayoutCandidate] = []
    keywords = (
        "强度",
        "聚焦状态",
        "功率",
        "产生",
        "线宽",
        "亮度",
    )
    for base in (token for token in tokens if token.text == "10"):
        exponent = _find_script(
            base,
            tokens,
            kind="super",
            pattern=_POWER,
        )
        if not exponent:
            continue
        row_tokens = [
            token
            for token in tokens
            if token.size >= base.size * 0.9
            and abs(token.bottom - base.bottom) <= base.size * 0.2
            and base.x0 - 350 <= token.x0 <= base.x1 + 220
        ]
        canonical = _join_geometry_row(row_tokens, tokens)
        if not any(keyword in canonical for keyword in keywords):
            continue
        if not re.search(r"10\^-?\d{1,3}", canonical):
            continue
        candidate = _make_candidate(
            canonical,
            [*row_tokens, exponent],
            confidence=0.97,
            kind="scientific_notation_line",
        )
        if candidate:
            candidates.append(candidate)
    return candidates


def extract_math_layout_candidates(
    page: Any,
) -> list[MathLayoutCandidate]:
    """Recover canonical math from pdfplumber glyph and vector geometry.

    The PDF decoding and geometry model come from pdfplumber/pdfminer.  This
    adapter only converts unambiguous size, baseline, and horizontal-rule
    relationships into searchable one-line equivalents.
    """

    tokens = _tokens_from_chars(getattr(page, "chars", ()))
    if not tokens:
        return []
    candidates = [
        *_horizontal_fraction_candidates(
            tokens,
            getattr(page, "lines", ()),
        ),
        *_scientific_line_candidates(tokens),
    ]
    unique: dict[str, MathLayoutCandidate] = {}
    for candidate in candidates:
        current = unique.get(candidate.canonical)
        if current is None or candidate.confidence > current.confidence:
            unique[candidate.canonical] = candidate
    return list(unique.values())
