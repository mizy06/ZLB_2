from __future__ import annotations

import asyncio
import json
import math
import re
import unicodedata
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal

from pylatexenc.latex2text import LatexNodes2Text
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
    _structured_json_call_kwargs,
)
from .architecture_schemas import TerminalGoldGate
from .model_provider import ModelProviderError, model_call_scope
from .pdf_math_geometry import _candidate_issues
from .pdf_page_knowledge import (
    PageKnowledgeExtraction,
    PageKnowledgeNode,
    _formula_evidence_key,
    _page_node_field_disposition,
    page_knowledge_issues,
)


PAGE_LAYOUT_SCHEMA_VERSION = "page-layout-v3"
PAGE_LAYOUT_NODE_SCHEMA_VERSION = "page-layout-nodes-v4"
PAGE_LAYOUT_ROLE = "pdf_page_layout_extractor"
PAGE_LAYOUT_NODE_ROLE = "pdf_layout_node_extractor"
PAGE_LAYOUT_TIMEOUT_SECONDS = 120.0
PAGE_LAYOUT_RETRY_TIMEOUT_SECONDS = 180.0
PAGE_LAYOUT_MAX_OUTPUT_TOKENS = 9000
PAGE_LAYOUT_NODE_MAX_OUTPUT_TOKENS = 2500
PAGE_LAYOUT_NODE_REASONING_TOKEN_RESERVE = 1536

_TERMINAL_NO_FURTHER_GATE = TerminalGoldGate(
    name_teaches_novice=True,
    no_further_bullet_decomposition=True,
    minimum_knowledge_atom=False,
)
_TERMINAL_ATOM_GATE = TerminalGoldGate(
    name_teaches_novice=True,
    no_further_bullet_decomposition=False,
    minimum_knowledge_atom=True,
)

LayoutProfile = Literal["dots", "chandra"]
LayoutCategory = Literal[
    "heading",
    "paragraph",
    "formula",
    "table",
    "list",
    "caption",
    "figure",
    "footnote",
    "header",
    "footer",
    "other",
]

_PRIVATE_USE_OR_REPLACEMENT = re.compile(r"[\ue000-\uf8ff\ufffd]")
_MARKDOWN_FENCE = re.compile(r"```")
_TEXT_POWER = re.compile(r"10\^\s*(-?\d+)")
_LATEX_POWER = re.compile(r"10\^\{?\s*(-?\d+)\s*\}?")
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
_FORMULA_RELATION = re.compile(r"[=≈≤≥<>→⇒]")
_STRICT_FORMULA_RELATION = re.compile(r"[=≈≤≥<>]")
_COMPLEX_MATH_SIGNAL = re.compile(
    r"(?:"
    r"10\^\s*-?\d+"
    r"|[/∫∑Σ√]"
    r"|[A-Za-zΑ-ω]\s*[_^]\s*\w+"
    r"|[+*×]"
    r")"
)
_UNIT_SUBSCRIPT_CORRUPTION = re.compile(
    r"(?<![A-Za-z])(?:H_[zZ]|H_\{[zZ]\})(?![A-Za-z])"
)
_DANGLING_TEXT_SUFFIX = re.compile(
    r"(?:是一种|等于|由于|因此|从而|可达|满足|表示|称为)$"
)
_SCIENTIFIC_POWER_MARKER_MISSING = re.compile(
    r"(?:小到|达到|约为|为|>|<).{0,12}10\s*-\s*\d{1,3}"
)
_SCIENTIFIC_NOTATION = re.compile(r"10\^\s*-?\d+")
_INLINE_MATH_SPAN = re.compile(r"\$[^$]+\$")
_MARKDOWN_STRONG = re.compile(r"(?:\*\*|__)(.+?)(?:\*\*|__)")
_MARKDOWN_EMPHASIS = re.compile(r"\*([^*\n]+)\*")
_QUOTED_ATOMIC_CLAIM = re.compile(r"[“\"]([^”\"\n]{6,})[”\"]")
_FALLBACK_STANDALONE_CONNECTIVES = frozenset(
    {
        "令",
        "有",
        "设",
        "则",
        "故",
        "即",
        "得",
        "其中",
        "因此",
        "所以",
    }
)
_ISOLATED_MATH_IDENTIFIER = re.compile(
    r"[A-Za-zΑ-Ωα-ω]"
    r"(?:\s*[_^]\s*\{?[A-Za-z0-9Α-Ωα-ω]+\}?)?"
)
_LATEX_COMMAND = re.compile(r"\\[A-Za-z]+")
_LATEX_FRACTION_COMMAND = re.compile(r"\\(?:d?frac)(?![A-Za-z])")
_LATEX_DISPLAY_FRACTION_COMMAND = re.compile(r"\\dfrac(?![A-Za-z])")
_SUPPORTED_CANONICAL_LATEX_COMMANDS = frozenset(
    {
        r"\Delta",
        r"\Gamma",
        r"\Lambda",
        r"\Omega",
        r"\Phi",
        r"\Pi",
        r"\Psi",
        r"\Sigma",
        r"\Theta",
        r"\alpha",
        r"\approx",
        r"\bar",
        r"\beta",
        r"\cdot",
        r"\chi",
        r"\cong",
        r"\cos",
        r"\cot",
        r"\delta",
        r"\dfrac",
        r"\epsilon",
        r"\eta",
        r"\exp",
        r"\frac",
        r"\gamma",
        r"\ge",
        r"\geq",
        r"\hat",
        r"\hbar",
        r"\infty",
        r"\int",
        r"\iota",
        r"\kappa",
        r"\lambda",
        r"\le",
        r"\left",
        r"\leq",
        r"\ln",
        r"\log",
        r"\mathbb",
        r"\mathbf",
        r"\mathrm",
        r"\mathit",
        r"\mp",
        r"\mu",
        r"\nabla",
        r"\ne",
        r"\neq",
        r"\nu",
        r"\omega",
        r"\operatorname",
        r"\overline",
        r"\partial",
        r"\phi",
        r"\pi",
        r"\pm",
        r"\prod",
        r"\psi",
        r"\rho",
        r"\right",
        r"\rightarrow",
        r"\sigma",
        r"\simeq",
        r"\sim",
        r"\sin",
        r"\sqrt",
        r"\sum",
        r"\tan",
        r"\tau",
        r"\text",
        r"\theta",
        r"\tilde",
        r"\times",
        r"\to",
        r"\upsilon",
        r"\varepsilon",
        r"\varphi",
        r"\varrho",
        r"\varsigma",
        r"\vartheta",
        r"\vec",
        r"\xi",
        r"\zeta",
    }
)
_SIMPLE_SCRIPT_BODY = re.compile(
    r"(?:[−+\-]?\d+|[A-Za-zΑ-ωℏΔΩΦΨλμν∂φπθξ]|"
    r"[\u3400-\u9fff]+)"
)
_NUMERIC_VALUE_SUFFIX = re.compile(
    r"(?:"
    r"\d+(?:\.\d+)?(?:\s*(?:×|x|·|\*|\\times|\\cdot)\s*"
    r"10\^\{?\s*[−+\-]?\d+\s*\}?)?"
    r"|10\^\{?\s*[−+\-]?\d+\s*\}?"
    r")(?:\s|\\[,;:! ])*$"
)
_DELTA_V_CANONICAL = re.compile(r"Δ\s*v(?![A-Za-z])")
_DELTA_V_LATEX = re.compile(r"\\Delta\s+v(?![A-Za-z])")
_FREQUENCY_UNIT = re.compile(
    r"(?<![A-Za-z])Hz(?![A-Za-z])|"
    r"\\(?:mathrm|text)\{\s*Hz\s*\}"
)
_SCIENTIFIC_VALUE_SPAN = re.compile(
    r"(?<![A-Za-z0-9_^])"
    r"(?:\d+(?:\.\d+)?\s*(?:×|x|·|\*)\s*)?"
    r"10\^\s*[−+\-]?\d+"
    r"(?:\s*[A-Za-zΩμ]+(?:\s*\^\s*[−+\-]?\d+)?"
    r"(?:\s*(?:/|·)\s*[A-Za-zΩμ]+"
    r"(?:\s*\^\s*[−+\-]?\d+)?)*"
    r")?"
)
_ASSIGNMENT_ITEM = re.compile(
    r"^[A-Za-zΑ-ωΔ](?:_[A-Za-z0-9]+)?\s*=\s*"
    r"[−+\-]?[A-Za-zΑ-ωΔ\d.]+(?:\^[−-]?\d+)?$"
)
_EMBEDDED_SIMPLE_ASSIGNMENT = re.compile(
    r"(?<![A-Za-z0-9_^])"
    r"(?P<formula>"
    r"[A-Za-zΑ-ωΔ](?:\s*_\s*[A-Za-z0-9]+)?"
    r"\s*=\s*"
    r"[−+\-]?(?:"
    r"[A-Za-zΑ-ωΔ]+"
    r"(?:\s*_\s*[A-Za-z0-9]+)?"
    r"(?:\s*\^\s*[−+\-]?\d+)?"
    r"|"
    r"\d+(?:\.\d+)?"
    r"(?:\s*/\s*\d+(?:\.\d+)?)?"
    r")"
    r")"
    r"(?![A-Za-z0-9_^/])"
)
_ENUMERATED_VALUE = re.compile(r"^[−+\-]?\d+(?:\.\d+)?$")
_LATEX_UNICODE_SYMBOLS = (
    (re.compile(r"\\Delta(?![A-Za-z])"), ("Δ",)),
    (re.compile(r"\\Omega(?![A-Za-z])"), ("Ω",)),
    (re.compile(r"\\Phi(?![A-Za-z])"), ("Φ",)),
    (re.compile(r"\\Psi(?![A-Za-z])"), ("Ψ",)),
    (re.compile(r"\\hbar(?![A-Za-z])"), ("ℏ", "ħ")),
    (re.compile(r"\\lambda(?![A-Za-z])"), ("λ",)),
    (re.compile(r"\\mu(?![A-Za-z])"), ("μ",)),
    (re.compile(r"\\nu(?![A-Za-z])"), ("ν",)),
    (re.compile(r"\\partial(?![A-Za-z])"), ("∂",)),
    (re.compile(r"\\phi(?![A-Za-z])"), ("φ",)),
    (re.compile(r"\\pi(?![A-Za-z])"), ("π",)),
    (re.compile(r"\\theta(?![A-Za-z])"), ("θ",)),
    (re.compile(r"\\varphi(?![A-Za-z])"), ("φ",)),
    (re.compile(r"\\xi(?![A-Za-z])"), ("ξ",)),
)
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
_STRUCTURE_PRIME_TRANSLATION = str.maketrans(
    {
        "′": "'",
        "’": "'",
        "ʹ": "'",
    }
)
_STRUCTURE_SUPERSCRIPT_BEFORE_SUBSCRIPT = re.compile(
    r"(?P<base>[A-Za-zΑ-ωℏΔΩΦΨλμν∂φπθξ]"
    r"[\u0300-\u036f\u20d0-\u20ff]*)"
    r"\^(?P<sup>\{?(?:[−+\-]?\d+|"
    r"[A-Za-zΑ-ωℏΔΩΦΨλμν∂φπθξ])\}?)"
    r"_(?P<sub>\{?(?:[−+\-]?\d+|"
    r"[A-Za-zΑ-ωℏΔΩΦΨλμν∂φπθξ])\}?)"
)
_BLOCK_SEPARATOR_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "caption",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tbody",
    "tfoot",
    "thead",
    "tr",
    "ul",
}

_CATEGORY_ALIASES: dict[str, LayoutCategory] = {
    "caption": "caption",
    "figure": "figure",
    "footnote": "footnote",
    "formula": "formula",
    "handwriting": "paragraph",
    "list": "list",
    "list-item": "list",
    "page-footer": "footer",
    "page-header": "header",
    "paragraph": "paragraph",
    "picture": "figure",
    "section-header": "heading",
    "table": "table",
    "text": "paragraph",
    "title": "heading",
}


DOTS_LAYOUT_SYSTEM_PROMPT = """你是忠实的文档布局解析器。遵循 dots.ocr 的布局类别和阅读顺序契约，只依据当前页面图像输出原文，不解释、不总结、不翻译、不补全。

只输出一个 JSON 对象：
{
  "page": 1,
  "complete": true,
  "confidence": 0.0,
  "coordinate_space": "normalized_1000",
  "blocks": [
    {
      "bbox": [x1, y1, x2, y2],
      "category": "Caption|Footnote|Formula|List-item|Page-footer|Page-header|Picture|Section-header|Table|Text|Title",
      "text": "页面中连续可见的原文",
      "formulas": [
        {
          "text": "该块中连续完整的 Unicode canonical 公式",
          "latex": "与 text 完全等价的 LaTeX"
        }
      ],
      "confidence": 0.0
    }
  ]
}

规则：
1. bbox 是严格位于 0..1000 的归一化角点坐标 [x1,y1,x2,y2]，blocks 按人类阅读顺序排列。
2. Formula 块至少有一个 formulas 项；其他块只要含 =、≈、>、<、→、⇒ 等复杂关系式，也必须列出对应 formulas。同一块有多条独立关系式时必须逐条列出，不能只列其中一部分。同一块中每个 formulas.text 都必须由该块 text 中连续可见的完整表达式支持。公式 text 用 ^ 和 _ 表示上下标，必须保留负号、分母、微分项和单位。
3. 指数的正负号和数字必须逐字保留，不得把 10^-k 恢复为 10^k。公式跨行时合并完整等式链，不得让块以 =、≈、>、< 开头。
4. Table 的 text 使用 HTML；其他非公式块保留原文，可使用 Markdown 行内格式，但不得使用代码围栏。
5. Picture 不臆造图中不可读内容；无可提取文字时 text 可省略。
6. 任何关键字符无法确认时 complete=false 并降低对应 confidence，不得猜测。
7. 不要输出 JSON 之外的文字。"""


CHANDRA_LAYOUT_SYSTEM_PROMPT = """你是忠实的文档布局解析器。遵循 Chandra 的 HTML、阅读顺序、data-label 和归一化 data-bbox 契约，只依据当前页面图像转录，不解释、不总结、不翻译、不推导。

只输出一个 JSON 对象：
{
  "page": 1,
  "complete": true,
  "confidence": 0.0,
  "html": "<div data-label=\\"...\\">...</div>"
}

HTML 规则：
1. 每个布局块是一个顶层 div，必须有 data-label、data-bbox 和 data-confidence。
2. data-bbox 格式为 "x1 y1 x2 y2"，坐标归一化到 0..1000；顶层 div 按阅读顺序排列。
3. data-label 使用 Caption、Footnote、Formula、List-item、Page-footer、Page-header、Picture、Section-header、Table、Text 或 Title。
4. 数学必须放在 <math data-canonical="Unicode canonical 公式">等价 LaTeX</math> 中。data-canonical 用 ^ 和 _ 表示上下标，保留负号、分母、微分项和单位。
5. 指数的正负号和数字必须逐字保留，不得把 10^-k 恢复为 10^k。同一块有多条独立关系式时必须逐条列出。公式跨行时合并完整等式链，不得让公式以 =、≈、>、< 开头。
6. 表格使用合法 HTML table；上下标可使用 sup/sub；化学式和图表标签保持原文。
7. 任何关键字符无法确认时 complete=false 并降低 confidence，不得猜测。
8. html 字符串之外仍须保持整个响应为有效 JSON，不要输出 Markdown 代码块。"""


LAYOUT_NODE_SYSTEM_PROMPT = """你是受约束的原子知识节点选择器。输入已经是通过质量门的 PDF 单页布局块；你只能选择和引用这些块，不得重新转录页面，不得重写证据、公式或坐标。

只输出一个 JSON 对象：
{
  "page": 1,
  "complete": true,
  "confidence": 0.0,
  "heading_block_id": "标题块 ID；没有则为空字符串",
  "has_knowledge": true,
  "no_knowledge_reason": "",
  "nodes": [
    {
      "temp_id": "本页唯一短 ID",
      "name": "必须是所引用块中的连续原文片段",
      "type": "concept|definition|principle|formula|result|example|step|warning|other",
      "role": "definition|principle|formula|example|step|warning|other",
      "block_id": "必须引用输入中的一个完整块",
      "formula_index": null,
      "confidence": 0.0,
      "terminal_gold_gate": {
        "name_teaches_novice": true,
        "no_further_bullet_decomposition": true,
        "minimum_knowledge_atom": false
      }
    }
  ]
}

规则：
1. evidence_text 和 bbox 由代码从 block_id 继承，你不得输出这两个字段。
2. formula_text 和 formula_latex 由代码从已验收布局继承并自动补齐，你不得输出这两个字段。
3. definition 也由代码设为完整块原文，你不得输出 definition。
4. name 必须逐字复制所引用块中的一个连续原文片段，长度为 2..48 个字符，保持单行、自足；不得使用章节编号、句子开头、连接词、句末标点、未闭合括号或截断短语，不得加入页面上没有的学科、对象或结论。只有当短词或短术语本身就能完整教会一个从未学过该知识的学生时，name 才能以短词结束；否则必须选择块中包含必要对象、条件、关系或结论的完整解释性短语。若块内没有这样的连续短语，不要输出该节点。
5. 每个清晰公式块都要选择一个短名称，并填写从 0 开始的对应 formula_index；非公式块必须填写 null。名称优先使用块中可见的公式名称、定义项或等式左侧，不得把超长整条公式当作 name。formula_text 和 formula_latex 仍由代码从已验收 formulas 继承。
6. 每个节点只表达一个原子事实。不要抽取纯页码、页眉页脚、装饰、坐标轴碎片、反应式中失去键线和箭头后形成的 O/OH/R/Cl 等孤立字母串，或空泛图示。
7. 每个节点必须填写 terminal_gold_gate。name_teaches_novice 必须为 true；no_further_bullet_decomposition 表示该知识已不适合继续分条列点，minimum_knowledge_atom 表示该知识已是最小知识原子，后两项是严格或关系。只有名称教学充分且两个终止条件至少一个为 true 时才可选择该节点。
8. 页面有知识但无法在单个连续块中得到直接支持时 complete=false，不得拼接不同块伪造证据。
9. 每页最多 12 个节点，不要输出 JSON 之外的文字。"""


class LayoutFormula(BaseModel):
    text: str
    latex: str

    @field_validator("text")
    @classmethod
    def validate_formula_text(cls, value: str) -> str:
        text = value.strip().rstrip("，。；;：:,")
        if not text:
            raise ValueError("layout formulas require canonical text")
        text = _normalize_supported_latex_canonical(text)
        if "^" not in text:
            text = _SUPERSCRIPT_SEQUENCE.sub(
                lambda match: "^"
                + match.group(0).translate(
                    _SUPERSCRIPT_TRANSLATION
                ),
                text,
            )
        if "_" not in text:
            text = _SUBSCRIPT_SEQUENCE.sub(
                lambda match: "_"
                + match.group(0).translate(
                    _SUBSCRIPT_TRANSLATION
                ),
                text,
            )
        text = (
            text.replace(r"\Delta", "Δ")
            .replace(r"\nu", "ν")
            .replace(r"\lambda", "λ")
            .replace(r"\Omega", "Ω")
            .replace(r"\hbar", "ℏ")
            .replace(r"\partial", "∂")
            .replace(r"\times", "×")
            .replace(r"\cdot", "·")
            .replace(r"\approx", "≈")
            .replace(r"\cong", "≈")
            .replace(r"\sim", "~")
            .replace(r"\pm", "±")
            .replace("≅", "≈")
            .replace("≃", "≈")
        )
        text = re.sub(
            r"(?P<marker>[_^])\{(?P<body>[^{}]+)\}",
            _collapse_simple_script_group,
            text,
        )
        return _repair_numeric_hz_unit(text)

    @field_validator("latex")
    @classmethod
    def validate_formula_latex(cls, value: str) -> str:
        latex = value.strip()
        if not latex:
            raise ValueError("layout formulas require latex")
        latex = re.sub(
            r"10\^(?!\{)(-?\d+)",
            r"10^{\1}",
            latex,
        )
        latex = re.sub(r"\\(?:cong|simeq)", r"\\approx", latex)
        return _repair_numeric_hz_unit(latex)


class PageLayoutBlock(BaseModel):
    block_id: str
    category: LayoutCategory
    text: str
    formulas: list[LayoutFormula] = Field(default_factory=list)
    bbox: list[float]
    confidence: float = Field(ge=0, le=1)

    @field_validator("block_id", "text")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("layout block fields must not be empty")
        return text

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
            raise ValueError("bbox origin and size are invalid")
        if x + width > 1 + 1e-9 or y + height > 1 + 1e-9:
            raise ValueError("bbox must fit inside the normalized page")
        return [
            round(x, 6),
            round(y, 6),
            round(width, 6),
            round(height, 6),
        ]

    @model_validator(mode="after")
    def validate_formula_block(self):
        if self.category == "formula" and not self.formulas:
            raise ValueError("formula blocks require canonical formulas")
        return self


class PageLayoutExtraction(BaseModel):
    profile: LayoutProfile
    page: int = Field(ge=1)
    complete: bool
    confidence: float = Field(ge=0, le=1)
    blocks: list[PageLayoutBlock] = Field(default_factory=list)


class LayoutNodeDraft(BaseModel):
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
    block_id: str
    formula_index: int | None = Field(default=None, ge=0)
    confidence: float = Field(ge=0, le=1)
    terminal_gold_gate: TerminalGoldGate | None = None

    @field_validator(
        "temp_id",
        "name",
        "type",
        "block_id",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("layout node fields must not be empty")
        return text

    @field_validator("role", mode="before")
    @classmethod
    def normalize_result_role(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip().casefold() == "result":
            return "other"
        return value


class LayoutNodeSelection(BaseModel):
    page: int = Field(ge=1)
    complete: bool
    confidence: float = Field(ge=0, le=1)
    heading_block_id: str = ""
    has_knowledge: bool = True
    no_knowledge_reason: str = ""
    nodes: list[LayoutNodeDraft] = Field(default_factory=list, max_length=12)

    @field_validator("heading_block_id", "no_knowledge_reason")
    @classmethod
    def normalize_optional_text(cls, value: str) -> str:
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


class LayoutKnowledgePageResult(BaseModel):
    layout: PageLayoutExtraction | None = None
    extraction: PageKnowledgeExtraction | None = None
    layout_attempts: int = 0
    node_attempts: int = 0
    issues: list[str] = Field(default_factory=list)


def _category(value: Any) -> LayoutCategory:
    normalized = str(value or "").strip().casefold().replace("_", "-")
    return _CATEGORY_ALIASES.get(normalized, "other")


def _collapse_simple_script_group(match: re.Match[str]) -> str:
    marker = match.group("marker")
    body = match.group("body").strip()
    if _SIMPLE_SCRIPT_BODY.fullmatch(body):
        return f"{marker}{body}"
    return f"{marker}{{{body}}}"


def _matching_brace(value: str, start: int) -> int | None:
    depth = 0
    for index in range(start, len(value)):
        if value[index] == "{":
            depth += 1
        elif value[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _protect_latex_script_groups(
    value: str,
) -> tuple[str, dict[str, str]]:
    parts: list[str] = []
    replacements: dict[str, str] = {}
    cursor = 0
    token_index = 0
    while cursor < len(value):
        marker = value[cursor]
        group_start = cursor + 1
        while group_start < len(value) and value[group_start].isspace():
            group_start += 1
        if marker not in {"^", "_"} or (
            group_start >= len(value) or value[group_start] != "{"
        ):
            parts.append(marker)
            cursor += 1
            continue
        group_end = _matching_brace(value, group_start)
        if group_end is None:
            parts.append(marker)
            cursor += 1
            continue
        token = f"ZLBXLATEXSCRIPT{token_index}X"
        while token in value:
            token_index += 1
            token = f"ZLBXLATEXSCRIPT{token_index}X"
        body = value[group_start + 1 : group_end]
        canonical_body = _normalize_supported_latex_canonical(body)
        replacements[token] = _collapse_simple_script_group(
            re.match(
                r"(?P<marker>[_^])\{(?P<body>.*)\}",
                f"{marker}{{{canonical_body}}}",
            )
        )
        parts.extend((marker, token))
        token_index += 1
        cursor = group_end + 1
    return "".join(parts), replacements


def _normalize_supported_latex_canonical(value: str) -> str:
    commands = set(_LATEX_COMMAND.findall(value))
    if not commands or not commands.issubset(
        _SUPPORTED_CANONICAL_LATEX_COMMANDS
    ):
        return value
    protected, replacements = _protect_latex_script_groups(value)
    converted = LatexNodes2Text().latex_to_text(protected)
    for token, replacement in replacements.items():
        converted = converted.replace(f"^{token}", replacement)
        converted = converted.replace(f"_{token}", replacement)
    return converted.replace("ħ", "ℏ")


def _latex_decoration_counts(value: str) -> Counter[str]:
    return Counter(
        {
            mark: len(pattern.findall(value))
            for pattern, mark in _LATEX_DECORATION_MARKS
            if pattern.search(value)
        }
    )


def _canonical_decoration_signature(
    value: str,
) -> Counter[tuple[str, str]]:
    signature: Counter[tuple[str, str]] = Counter()
    base = ""
    for character in unicodedata.normalize("NFD", value):
        decoration = _DECORATION_MARK_ALIASES.get(character, character)
        if decoration in _CANONICAL_DECORATION_MARKS:
            if base:
                signature[(base, decoration)] += 1
            continue
        if unicodedata.category(character) != "Mn":
            base = character
    return signature


def _canonical_decoration_counts(value: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for (_, mark), count in _canonical_decoration_signature(value).items():
        counts[mark] += count
    return counts


def _repair_formula_decorations(
    text: str,
    formula: LayoutFormula,
) -> LayoutFormula:
    expected_counts = _latex_decoration_counts(formula.latex)
    if not expected_counts:
        return formula
    actual_counts = _canonical_decoration_counts(formula.text)
    if actual_counts == expected_counts:
        return formula

    latex_canonical = _normalize_supported_latex_canonical(formula.latex)
    if _LATEX_COMMAND.search(latex_canonical):
        return formula
    derived_signature = _canonical_decoration_signature(latex_canonical)
    visible_signature = _canonical_decoration_signature(text)
    derived_counts = _canonical_decoration_counts(latex_canonical)
    if (
        derived_counts != expected_counts
        or not derived_signature
        or derived_signature - visible_signature
        or _formula_evidence_key(latex_canonical)
        not in _formula_evidence_key(text)
    ):
        return formula
    return formula.model_copy(update={"text": latex_canonical})


def _latex_fraction_canonical(formula: LayoutFormula) -> str:
    if not _LATEX_FRACTION_COMMAND.search(formula.latex):
        return ""
    supported_latex = _LATEX_DISPLAY_FRACTION_COMMAND.sub(
        r"\\frac",
        formula.latex,
    )
    canonical = _normalize_supported_latex_canonical(
        supported_latex.replace(r"\cot", "cot")
    )
    if _LATEX_COMMAND.search(canonical):
        return ""
    return canonical


def _formula_structure_key(value: str) -> str:
    normalized = value.translate(_STRUCTURE_PRIME_TRANSLATION)
    normalized = _STRUCTURE_SUPERSCRIPT_BEFORE_SUBSCRIPT.sub(
        lambda match: (
            f"{match.group('base')}_"
            f"{match.group('sub').strip('{}')}^"
            f"{match.group('sup').strip('{}')}"
        ),
        normalized,
    )
    return _formula_evidence_key(normalized).replace("ctg", "cot")


def _formula_structure_skeleton(value: str) -> str:
    return _formula_structure_key(value).replace("/", "")


def _formula_structures_equivalent(
    formula_text: str,
    latex_canonical: str,
) -> bool:
    formula_key = _formula_structure_key(formula_text)
    latex_key = _formula_structure_key(latex_canonical)
    if formula_key == latex_key:
        return True
    if not latex_key or latex_key not in formula_key:
        return False
    prefix, suffix = formula_key.split(latex_key, 1)
    affixes = f"{prefix}{suffix}"
    return not _FORMULA_RELATION.search(affixes) and "/" not in affixes


def _repair_formula_structures(
    text: str,
    formulas: list[LayoutFormula],
) -> tuple[str, list[LayoutFormula]]:
    repaired_text = text
    repaired_formulas: list[LayoutFormula] = []
    for formula in formulas:
        latex_canonical = _latex_fraction_canonical(formula)
        formula_key = _formula_structure_key(formula.text)
        latex_key = _formula_structure_key(latex_canonical)
        if (
            latex_canonical
            and formula_key
            and latex_key
            and formula_key != latex_key
            and _formula_structure_skeleton(formula.text)
            == _formula_structure_skeleton(latex_canonical)
            and _FORMULA_RELATION.search(formula.text)
            and re.search(r"[A-Za-zΑ-ωℏ∂]", formula.text)
            and formula.text in repaired_text
        ):
            repaired_text = repaired_text.replace(
                formula.text,
                latex_canonical,
                1,
            )
            repaired_formulas.append(
                formula.model_copy(update={"text": latex_canonical})
            )
        else:
            repaired_formulas.append(formula)
    return repaired_text, repaired_formulas


def _repair_numeric_hz_unit(value: str) -> str:
    parts: list[str] = []
    cursor = 0
    for match in _UNIT_SUBSCRIPT_CORRUPTION.finditer(value):
        prefix = value[: match.start()]
        numeric_prefix = re.sub(
            r"\\(?:mathrm|text)\{\s*$",
            "",
            prefix,
        )
        parts.append(value[cursor : match.start()])
        parts.append(
            "Hz"
            if _NUMERIC_VALUE_SUFFIX.search(numeric_prefix)
            else match.group(0)
        )
        cursor = match.end()
    parts.append(value[cursor:])
    return "".join(parts)


def _normalized_visible_text(parts: list[str]) -> str:
    raw = "".join(parts).replace("\r\n", "\n").replace("\r", "\n")
    lines = [
        re.sub(r"[ \t\f\v]+", " ", line).strip()
        for line in raw.splitlines()
    ]
    return "\n".join(line for line in lines if line).strip()


def _corner_bbox(
    value: Any,
    *,
    x_scale: float,
    y_scale: float,
) -> list[float]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 4
        or any(not isinstance(item, (int, float)) for item in value)
    ):
        raise ValueError("layout bbox must be [x1, y1, x2, y2]")
    x1, y1, x2, y2 = (float(item) for item in value)
    if (
        not all(math.isfinite(item) for item in (x1, y1, x2, y2))
        or x_scale <= 0
        or y_scale <= 0
        or x1 < 0
        or y1 < 0
        or x2 <= x1
        or y2 <= y1
        or x2 > x_scale + 1e-6
        or y2 > y_scale + 1e-6
    ):
        raise ValueError("layout bbox is outside its coordinate space")
    return [
        round(x1 / x_scale, 6),
        round(y1 / y_scale, 6),
        round((x2 - x1) / x_scale, 6),
        round((y2 - y1) / y_scale, 6),
    ]


class _VisibleHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag.casefold() == "br":
            self.parts.append("\n")
        elif tag.casefold() in {"td", "th"} and self.parts:
            self.parts.append("\t")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in _BLOCK_SEPARATOR_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _visible_html(value: str) -> str:
    parser = _VisibleHtmlParser()
    parser.feed(value)
    parser.close()
    return _normalized_visible_text(parser.parts)


def _replace_inline_math_spans(
    text: str,
    formulas: list[LayoutFormula],
) -> str:
    spans = list(_INLINE_MATH_SPAN.finditer(text))
    if not spans or len(spans) != len(formulas):
        return text
    parts: list[str] = []
    cursor = 0
    for span, formula in zip(spans, formulas):
        parts.append(text[cursor:span.start()])
        parts.append(formula.text)
        cursor = span.end()
    parts.append(text[cursor:])
    return "".join(parts)


def _strip_markdown_emphasis(text: str) -> str:
    stripped = _MARKDOWN_STRONG.sub(r"\1", text)
    return _MARKDOWN_EMPHASIS.sub(r"\1", stripped)


def _normalize_inline_math_text(text: str) -> str:
    normalized = _normalize_supported_latex_canonical(text)
    normalized = (
        normalized.replace("$", "")
        .replace(r"\Delta", "Δ")
        .replace(r"\nu", "ν")
        .replace(r"\lambda", "λ")
        .replace(r"\Omega", "Ω")
        .replace(r"\hbar", "ℏ")
        .replace(r"\partial", "∂")
    )
    return _repair_numeric_hz_unit(normalized)


def _dedupe_layout_formulas(
    formulas: list[LayoutFormula],
) -> list[LayoutFormula]:
    keys = [_formula_evidence_key(formula.text) for formula in formulas]
    deduped: list[LayoutFormula] = []
    for index, formula in enumerate(formulas):
        key = keys[index]
        if not key:
            deduped.append(formula)
            continue
        if any(
            other_index != index
            and key != other_key
            and key in other_key
            for other_index, other_key in enumerate(keys)
        ):
            continue
        if any(
            _formula_evidence_key(item.text) == key
            for item in deduped
        ):
            continue
        deduped.append(formula)
    return deduped


def _contextualize_formulas(
    text: str,
    formulas: list[LayoutFormula],
) -> list[LayoutFormula]:
    continued: list[LayoutFormula] = []
    merged_continuation = False
    for formula in formulas:
        if (
            continued
            and "missing_relation_operand"
            in _candidate_issues(formula.text)
        ):
            merged_continuation = True
            previous = continued.pop()
            continued.append(
                LayoutFormula(
                    text=f"{previous.text} {formula.text}",
                    latex=f"{previous.latex} {formula.latex}",
                )
            )
        else:
            continued.append(formula)

    contextualized: list[LayoutFormula] = []
    for raw_formula in continued:
        formula = _repair_formula_decorations(text, raw_formula)
        issues = _candidate_issues(formula.text)
        formula_key = _formula_evidence_key(formula.text)
        text_key = _formula_evidence_key(text)
        if (
            merged_continuation
            and len(continued) == 1
            and formula_key
            and formula_key in text_key
            and text != formula.text
        ):
            contextualized.append(
                formula.model_copy(update={"text": text})
            )
        elif (
            "missing_relation_operand" in issues
            and formula.text in text
            and text != formula.text
        ):
            contextualized.append(
                formula.model_copy(update={"text": text})
            )
        elif (
            len(continued) == 1
            and formula_key
            and formula_key not in text_key
            and _FORMULA_RELATION.search(text)
        ):
            contextualized.append(
                formula.model_copy(update={"text": text})
            )
        else:
            contextualized.append(formula)
    return _dedupe_layout_formulas(contextualized)


def _bbox_union(first: list[float], second: list[float]) -> list[float]:
    x1 = min(first[0], second[0])
    y1 = min(first[1], second[1])
    x2 = max(first[0] + first[2], second[0] + second[2])
    y2 = max(first[1] + first[3], second[1] + second[3])
    return [
        round(x1, 6),
        round(y1, 6),
        round(x2 - x1, 6),
        round(y2 - y1, 6),
    ]


def _continuation_geometry(
    previous: PageLayoutBlock,
    current: PageLayoutBlock,
) -> bool:
    previous_right = previous.bbox[0] + previous.bbox[2]
    current_right = current.bbox[0] + current.bbox[2]
    overlap = max(
        min(previous_right, current_right)
        - max(previous.bbox[0], current.bbox[0]),
        0,
    )
    min_width = min(previous.bbox[2], current.bbox[2])
    vertical_gap = current.bbox[1] - (
        previous.bbox[1] + previous.bbox[3]
    )
    return (
        overlap >= min_width * 0.1
        and -0.03 <= vertical_gap <= 0.12
    )


def _merge_formula_continuations(
    blocks: list[PageLayoutBlock],
) -> list[PageLayoutBlock]:
    merged: list[PageLayoutBlock] = []
    for block in blocks:
        leading_relation = bool(
            block.formulas
            and "missing_relation_operand"
            in _candidate_issues(block.formulas[0].text)
        )
        previous = merged[-1] if merged else None
        if (
            leading_relation
            and previous is not None
            and previous.formulas
            and _continuation_geometry(previous, block)
        ):
            previous_formula = previous.formulas[-1]
            continuation = block.formulas[0]
            combined_formula = LayoutFormula(
                text=f"{previous_formula.text} {continuation.text}",
                latex=f"{previous_formula.latex} {continuation.latex}",
            )
            combined_text = f"{previous.text}\n{block.text}".strip()
            merged[-1] = previous.model_copy(
                update={
                    "category": "formula",
                    "text": combined_text,
                    "formulas": [
                        *previous.formulas[:-1],
                        combined_formula,
                        *block.formulas[1:],
                    ],
                    "bbox": _bbox_union(previous.bbox, block.bbox),
                    "confidence": min(
                        previous.confidence,
                        block.confidence,
                    ),
                }
            )
            continue
        merged.append(block)
    return merged


def _label_formula_geometry(
    label: PageLayoutBlock,
    formula: PageLayoutBlock,
) -> bool:
    label_right = label.bbox[0] + label.bbox[2]
    formula_right = formula.bbox[0] + formula.bbox[2]
    horizontal_overlap = max(
        min(label_right, formula_right)
        - max(label.bbox[0], formula.bbox[0]),
        0,
    )
    vertical_overlap = max(
        min(
            label.bbox[1] + label.bbox[3],
            formula.bbox[1] + formula.bbox[3],
        )
        - max(label.bbox[1], formula.bbox[1]),
        0,
    )
    min_height = min(label.bbox[3], formula.bbox[3])
    horizontal_gap = formula.bbox[0] - label_right
    same_row = (
        vertical_overlap >= min_height * 0.25
        and -0.05 <= horizontal_gap <= 0.25
    )
    stacked = (
        horizontal_overlap
        >= min(label.bbox[2], formula.bbox[2]) * 0.1
        and -0.03
        <= formula.bbox[1] - (label.bbox[1] + label.bbox[3])
        <= 0.12
    )
    return same_row or stacked


def _merge_formula_labels(
    blocks: list[PageLayoutBlock],
) -> list[PageLayoutBlock]:
    merged: list[PageLayoutBlock] = []
    for block in blocks:
        previous = merged[-1] if merged else None
        if (
            block.formulas
            and previous is not None
            and previous.category == "paragraph"
            and len(previous.text) <= 80
            and previous.text.rstrip().endswith(("为", "：", ":"))
            and _label_formula_geometry(previous, block)
        ):
            combined_text = f"{previous.text}\n{block.text}".strip()
            merged[-1] = block.model_copy(
                update={
                    "text": combined_text,
                    "formulas": _contextualize_formulas(
                        combined_text,
                        block.formulas,
                    ),
                    "bbox": _bbox_union(previous.bbox, block.bbox),
                    "confidence": min(
                        previous.confidence,
                        block.confidence,
                    ),
                }
            )
            continue
        merged.append(block)
    return merged


def _finalize_layout_blocks(
    blocks: list[PageLayoutBlock],
) -> list[PageLayoutBlock]:
    return _merge_formula_labels(
        _merge_formula_continuations(blocks)
    )


def _requires_layout_formula(text: str) -> bool:
    if _SCIENTIFIC_NOTATION.search(text):
        return True
    stripped = text.lstrip()
    if stripped.startswith(("→", "⇒")):
        relation_text = stripped[1:].lstrip()
        if (
            re.search(r"[\u3400-\u9fff]", relation_text)
            and not _STRICT_FORMULA_RELATION.search(relation_text)
        ):
            return False
    return bool(
        _FORMULA_RELATION.search(text)
        and _COMPLEX_MATH_SIGNAL.search(text)
    )


def _enumerated_assignment_lines(text: str) -> tuple[str, ...]:
    candidates: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip().rstrip("，,；;。.")
        if not line or re.search(r"[\u3400-\u9fff]", line):
            continue
        parts = [
            part.strip()
            for part in re.split(r"[,，]", line)
            if part.strip()
        ]
        if len(parts) < 2:
            continue
        assignment_count = sum(
            1 for part in parts if _ASSIGNMENT_ITEM.fullmatch(part)
        )
        if assignment_count < 1:
            continue
        if not all(
            _ASSIGNMENT_ITEM.fullmatch(part)
            or _ENUMERATED_VALUE.fullmatch(part)
            for part in parts
        ):
            continue
        candidates.append(line)
    return tuple(dict.fromkeys(candidates))


def _simple_assignment_latex(value: str) -> str:
    latex = value.replace("，", ",")
    latex = re.sub(
        r"([A-Za-zΑ-ωΔ])_([A-Za-z0-9]+)",
        r"\1_{\2}",
        latex,
    )
    return re.sub(r"\^([−-]?\d+)", r"^{\1}", latex)


def _scientific_formula_candidates(text: str) -> tuple[str, ...]:
    candidates: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip().rstrip("，,；;。.")
        spans = list(_SCIENTIFIC_VALUE_SPAN.finditer(line))
        if not spans:
            continue
        if _FORMULA_RELATION.search(line):
            candidates.append(line)
        else:
            candidates.extend(
                match.group(0).strip() for match in spans
            )
    return tuple(dict.fromkeys(candidate for candidate in candidates if candidate))


def _scientific_formula_latex(value: str) -> str:
    latex = value
    replacements = (
        ("Δ", r"\Delta "),
        ("Ω", r"\Omega "),
        ("Φ", r"\Phi "),
        ("Ψ", r"\Psi "),
        ("λ", r"\lambda "),
        ("μ", r"\mu "),
        ("ν", r"\nu "),
        ("ℏ", r"\hbar "),
        ("∂", r"\partial "),
        ("×", r"\times "),
        ("·", r"\cdot "),
        ("≈", r"\approx "),
        ("≤", r"\leq "),
        ("≥", r"\geq "),
        ("→", r"\rightarrow "),
        ("±", r"\pm "),
    )
    for source, target in replacements:
        latex = latex.replace(source, target)
    latex = re.sub(
        r"10\^\s*([−+\-]?\d+)",
        r"10^{\1}",
        latex,
    )
    latex = re.sub(
        r"(?<=[A-Za-z])\^\s*([−+\-]?\d+)",
        r"^{\1}",
        latex,
    )
    latex = re.sub(
        r"([\u3400-\u9fff]+)",
        r"\\text{\1}",
        latex,
    )
    return re.sub(r"[ \t]+", " ", latex).strip()


def _supplement_scientific_formulas(
    text: str,
    formulas: list[LayoutFormula],
) -> list[LayoutFormula]:
    supplemented = list(formulas)
    formula_keys = {
        _formula_evidence_key(formula.text)
        for formula in supplemented
    }
    for candidate in _scientific_formula_candidates(text):
        candidate_key = _formula_evidence_key(candidate)
        if not candidate_key or any(
            candidate_key in formula_key
            for formula_key in formula_keys
        ):
            continue
        supplemented.append(
            LayoutFormula(
                text=candidate,
                latex=_scientific_formula_latex(candidate),
            )
        )
        formula_keys.add(candidate_key)
    return _dedupe_layout_formulas(supplemented)


def _supplement_enumerated_formulas(
    text: str,
    formulas: list[LayoutFormula],
) -> list[LayoutFormula]:
    supplemented = list(formulas)
    formula_keys = {
        _formula_evidence_key(formula.text)
        for formula in supplemented
    }
    for candidate in _enumerated_assignment_lines(text):
        candidate_key = _formula_evidence_key(candidate)
        if not candidate_key or any(
            candidate_key in formula_key
            for formula_key in formula_keys
        ):
            continue
        supplemented.append(
            LayoutFormula(
                text=candidate,
                latex=_simple_assignment_latex(candidate),
            )
        )
        formula_keys.add(candidate_key)
    return _dedupe_layout_formulas(supplemented)


def _supplement_embedded_assignment_formulas(
    text: str,
    formulas: list[LayoutFormula],
) -> list[LayoutFormula]:
    supplemented = list(formulas)
    formula_keys = {
        _formula_evidence_key(formula.text)
        for formula in supplemented
    }
    for match in _EMBEDDED_SIMPLE_ASSIGNMENT.finditer(text):
        candidate = re.sub(r"\s+", " ", match.group("formula")).strip()
        if re.match(
            r"\s*(?:[/+*×±−-]|[=≈≤≥<>→⇒])",
            text[match.end() :],
        ):
            continue
        if not _COMPLEX_MATH_SIGNAL.search(candidate):
            continue
        candidate_key = _formula_evidence_key(candidate)
        if not candidate_key or any(
            candidate_key in formula_key
            for formula_key in formula_keys
        ):
            continue
        supplemented.append(
            LayoutFormula(
                text=candidate,
                latex=_simple_assignment_latex(candidate),
            )
        )
        formula_keys.add(candidate_key)
    return _dedupe_layout_formulas(supplemented)


def _repair_page_frequency_symbols(
    blocks: list[PageLayoutBlock],
) -> list[PageLayoutBlock]:
    visible_nu_blocks = {
        index
        for index, block in enumerate(blocks)
        if "ν" in block.text
    }
    repaired: list[PageLayoutBlock] = []
    for index, block in enumerate(blocks):
        if not any(
            other_index != index for other_index in visible_nu_blocks
        ):
            repaired.append(block)
            continue
        formulas: list[LayoutFormula] = []
        formula_changed = False
        for formula in block.formulas:
            if (
                _DELTA_V_CANONICAL.search(formula.text)
                and _FREQUENCY_UNIT.search(
                    f"{formula.text}\n{formula.latex}"
                )
            ):
                formulas.append(
                    formula.model_copy(
                        update={
                            "text": _DELTA_V_CANONICAL.sub(
                                "Δν",
                                formula.text,
                            ),
                            "latex": _DELTA_V_LATEX.sub(
                                r"\\Delta \\nu",
                                formula.latex,
                            ),
                        }
                    )
                )
                formula_changed = True
            else:
                formulas.append(formula)
        repaired.append(
            block.model_copy(
                update={
                    "text": _DELTA_V_CANONICAL.sub("Δν", block.text),
                    "formulas": formulas,
                }
            )
            if formula_changed
            else block
        )
    return repaired


def parse_dots_layout(
    payload: dict[str, Any] | list[Any],
    *,
    expected_page: int,
    image_width: int,
    image_height: int,
) -> PageLayoutExtraction:
    if isinstance(payload, list):
        metadata: dict[str, Any] = {}
        raw_blocks = payload
    elif isinstance(payload, dict):
        metadata = payload
        raw_blocks = (
            payload.get("blocks")
            or payload.get("elements")
            or payload.get("layout")
        )
    else:
        raise ValueError("dots layout response must be JSON")
    if not isinstance(raw_blocks, list):
        raise ValueError("dots layout response has no block list")

    coordinate_space = str(
        metadata.get("coordinate_space") or "pixels"
    ).strip().casefold()
    if coordinate_space in {"normalized", "0..1", "unit"}:
        x_scale = y_scale = 1.0
    elif coordinate_space in {"normalized_1000", "0..1000", "1000"}:
        x_scale = y_scale = 1000.0
    else:
        x_scale = float(image_width)
        y_scale = float(image_height)

    blocks: list[PageLayoutBlock] = []
    page_confidence = float(metadata.get("confidence", 1.0))
    for index, raw_block in enumerate(raw_blocks):
        if not isinstance(raw_block, dict):
            raise ValueError("dots layout blocks must be objects")
        category = _category(
            raw_block.get("category") or raw_block.get("label")
        )
        raw_text = raw_block.get("text")
        text = str(raw_text or "").strip()
        formulas: list[LayoutFormula] = []
        raw_formulas = raw_block.get("formulas")
        if isinstance(raw_formulas, list):
            formulas = [
                LayoutFormula.model_validate(formula)
                for formula in raw_formulas
            ]
        if category == "formula":
            canonical = str(
                raw_block.get("canonical_text")
                or raw_block.get("formula_text")
                or text
            ).strip()
            latex = str(raw_block.get("latex") or "").strip()
            if not formulas:
                formulas = [LayoutFormula(text=canonical, latex=latex)]
            text = str(raw_block.get("evidence_text") or canonical).strip()
        elif category == "table" and "<" in text and ">" in text:
            text = _visible_html(text)
        text = _replace_inline_math_spans(text, formulas)
        text = _strip_markdown_emphasis(text)
        text = _normalize_inline_math_text(text)
        text, formulas = _repair_formula_structures(text, formulas)
        formulas = _contextualize_formulas(text, formulas)
        formulas = _supplement_enumerated_formulas(text, formulas)
        formulas = _supplement_embedded_assignment_formulas(
            text,
            formulas,
        )
        formulas = _supplement_scientific_formulas(text, formulas)
        if not text and category == "figure":
            continue
        blocks.append(
            PageLayoutBlock(
                block_id=f"p{expected_page:04d}:b{index:03d}",
                category=category,
                text=text,
                formulas=formulas,
                bbox=_corner_bbox(
                    raw_block.get("bbox"),
                    x_scale=x_scale,
                    y_scale=y_scale,
                ),
                confidence=float(
                    raw_block.get("confidence", page_confidence)
                ),
            )
        )

    return PageLayoutExtraction(
        profile="dots",
        page=int(metadata.get("page", expected_page)),
        complete=bool(metadata.get("complete", True)),
        confidence=page_confidence,
        blocks=_finalize_layout_blocks(
            _repair_page_frequency_symbols(blocks)
        ),
    )


class _ChandraHtmlParser(HTMLParser):
    def __init__(
        self,
        *,
        expected_page: int,
        page_confidence: float,
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.expected_page = expected_page
        self.page_confidence = page_confidence
        self.blocks: list[PageLayoutBlock] = []
        self.errors: list[str] = []
        self._capture: dict[str, Any] | None = None
        self._div_depth = 0
        self._math_depth = 0
        self._math_parts: list[str] = []
        self._math_canonical = ""

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.casefold()
        attributes = {
            key.casefold(): value
            for key, value in attrs
            if value is not None
        }
        if self._capture is None:
            if tag != "div":
                return
            label = attributes.get("data-label")
            bbox = attributes.get("data-bbox")
            if label is None and bbox is None:
                return
            if not label or not bbox:
                self.errors.append("layout_div_missing_required_attribute")
                return
            self._capture = {
                "label": label,
                "bbox": bbox,
                "confidence": attributes.get("data-confidence"),
                "parts": [],
                "formulas": [],
            }
            self._div_depth = 1
            return

        if tag == "div":
            self._div_depth += 1
        if tag == "br":
            self._capture["parts"].append("\n")
        elif tag in {"td", "th"} and self._capture["parts"]:
            self._capture["parts"].append("\t")
        if self._math_depth:
            if tag == "sup":
                self._math_parts.append("^{")
            elif tag == "sub":
                self._math_parts.append("_{")
            elif tag == "br":
                self._math_parts.append(" ")
        if tag == "math":
            if self._math_depth:
                self.errors.append("nested_math")
            self._math_depth += 1
            self._math_parts = []
            self._math_canonical = str(
                attributes.get("data-canonical") or ""
            ).strip()

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if self._capture is None:
            return
        if tag == "math" and self._math_depth:
            latex = "".join(self._math_parts).strip()
            if self._math_canonical and latex:
                formula = LayoutFormula(
                    text=self._math_canonical,
                    latex=latex,
                )
                self._capture["formulas"].append(formula)
                self._capture["parts"].append(formula.text)
            else:
                self.errors.append("math_missing_canonical_or_latex")
            self._math_depth -= 1
            self._math_parts = []
            self._math_canonical = ""
        elif tag in {"sup", "sub"} and self._math_depth:
            self._math_parts.append("}")
        elif tag in _BLOCK_SEPARATOR_TAGS and tag != "div":
            self._capture["parts"].append("\n")

        if tag != "div":
            return
        self._div_depth -= 1
        if self._div_depth:
            return
        self._finalize_block()

    def handle_data(self, data: str) -> None:
        if self._capture is None:
            return
        if self._math_depth:
            self._math_parts.append(data)
        else:
            self._capture["parts"].append(data)

    def close(self) -> None:
        super().close()
        if self._capture is not None:
            self.errors.append("unclosed_layout_div")

    def _finalize_block(self) -> None:
        if self._capture is None:
            return
        try:
            bbox_values = [
                float(item)
                for item in re.findall(
                    r"-?\d+(?:\.\d+)?",
                    str(self._capture["bbox"]),
                )
            ]
            text = _normalized_visible_text(self._capture["parts"])
            text, formulas = _repair_formula_structures(
                text,
                list(self._capture["formulas"]),
            )
            category = _category(self._capture["label"])
            if category == "figure" and not text:
                return
            try:
                confidence = float(
                    self._capture["confidence"]
                    or self.page_confidence
                )
            except (TypeError, ValueError):
                confidence = self.page_confidence
            block = PageLayoutBlock(
                block_id=(
                    f"p{self.expected_page:04d}:"
                    f"b{len(self.blocks):03d}"
                ),
                category=category,
                text=text,
                formulas=_contextualize_formulas(
                    text,
                    formulas,
                ),
                bbox=_corner_bbox(
                    bbox_values,
                    x_scale=1000,
                    y_scale=1000,
                ),
                confidence=confidence,
            )
            self.blocks.append(block)
        except ValidationError as exc:
            error_types = sorted(
                {
                    str(error.get("type") or "validation_error")
                    for error in exc.errors()
                }
            )
            self.errors.append(
                "invalid_layout_div:" + ",".join(error_types)
            )
        except (TypeError, ValueError):
            self.errors.append("invalid_layout_div:value_error")
        finally:
            self._capture = None
            self._div_depth = 0
            self._math_depth = 0
            self._math_parts = []
            self._math_canonical = ""


def parse_chandra_layout(
    payload: dict[str, Any],
    *,
    expected_page: int,
) -> PageLayoutExtraction:
    if not isinstance(payload, dict):
        raise ValueError("chandra layout response must be an object")
    html = payload.get("html")
    if not isinstance(html, str) or not html.strip():
        raise ValueError("chandra layout response has no html")
    page_confidence = float(payload.get("confidence", 1.0))
    parser = _ChandraHtmlParser(
        expected_page=expected_page,
        page_confidence=page_confidence,
    )
    parser.feed(html)
    parser.close()
    if parser.errors:
        raise ValueError(",".join(dict.fromkeys(parser.errors)))
    return PageLayoutExtraction(
        profile="chandra",
        page=int(payload.get("page", expected_page)),
        complete=bool(payload.get("complete", True)),
        confidence=page_confidence,
        blocks=_finalize_layout_blocks(parser.blocks),
    )


def _formula_issues(formula: LayoutFormula) -> list[str]:
    issues = list(_candidate_issues(formula.text))
    if _LATEX_COMMAND.search(formula.text):
        issues.append("canonical_text_contains_latex")
    if any(
        latex_pattern.search(formula.latex)
        and not any(symbol in formula.text for symbol in symbols)
        for latex_pattern, symbols in _LATEX_UNICODE_SYMBOLS
    ):
        issues.append("formula_text_latex_symbol_mismatch")
    expected_decorations = _latex_decoration_counts(formula.latex)
    actual_decorations = _canonical_decoration_counts(formula.text)
    if expected_decorations != actual_decorations:
        issues.append("formula_text_latex_decoration_mismatch")
    latex_fraction_canonical = _latex_fraction_canonical(formula)
    if (
        latex_fraction_canonical
        and not _formula_structures_equivalent(
            formula.text,
            latex_fraction_canonical,
        )
    ):
        issues.append("formula_text_latex_structure_mismatch")
    if formula.latex.count("{") != formula.latex.count("}"):
        issues.append("unbalanced_latex_braces")
    text_powers = _TEXT_POWER.findall(
        formula.text.replace("−", "-").replace("–", "-")
    )
    latex_powers = _LATEX_POWER.findall(formula.latex)
    if len(text_powers) != len(latex_powers):
        issues.append("formula_text_latex_exponent_count_mismatch")
    else:
        for text_power, latex_power in zip(text_powers, latex_powers):
            if text_power != latex_power:
                issues.append("formula_text_latex_exponent_mismatch")
    return list(dict.fromkeys(issues))


def page_layout_issues(
    extraction: PageLayoutExtraction,
    *,
    expected_page: int,
    min_confidence: float,
) -> tuple[str, ...]:
    issues: list[str] = []
    if extraction.page != expected_page:
        issues.append("page_mismatch")
    if not extraction.complete:
        issues.append("page_marked_incomplete")
    if extraction.confidence < min_confidence:
        issues.append("page_confidence_below_threshold")
    if not extraction.blocks:
        issues.append("page_has_no_blocks")

    seen_ids: set[str] = set()
    for index, block in enumerate(extraction.blocks):
        prefix = f"block_{index}"
        if block.block_id in seen_ids:
            issues.append(f"{prefix}:duplicate_block_id")
        seen_ids.add(block.block_id)
        if block.confidence < min_confidence:
            issues.append(f"{prefix}:confidence_below_threshold")
        combined = "\n".join(
            [
                block.text,
                *(
                    f"{formula.text}\n{formula.latex}"
                    for formula in block.formulas
                ),
            ]
        )
        if _PRIVATE_USE_OR_REPLACEMENT.search(combined):
            issues.append(f"{prefix}:residual_private_use_glyph")
        if _MARKDOWN_FENCE.search(combined):
            issues.append(f"{prefix}:markdown_fence")
        if _UNIT_SUBSCRIPT_CORRUPTION.search(combined):
            issues.append(f"{prefix}:unit_subscript_corruption")
        if _SCIENTIFIC_POWER_MARKER_MISSING.search(block.text):
            issues.append(f"{prefix}:scientific_power_marker_missing")
        following_block = (
            extraction.blocks[index + 1]
            if index + 1 < len(extraction.blocks)
            else None
        )
        introduces_following_list = (
            block.text.rstrip().endswith(("：", ":"))
            and following_block is not None
            and following_block.category == "list"
        )
        if (
            block.category in {"paragraph", "list", "caption"}
            and not introduces_following_list
            and _DANGLING_TEXT_SUFFIX.search(block.text.rstrip("，。；;：:"))
        ):
            issues.append(f"{prefix}:dangling_text_suffix")
        if not block.formulas and _requires_layout_formula(block.text):
            issues.append(f"{prefix}:formula_contract_missing")
        block_text_key = _formula_evidence_key(block.text)
        formula_keys = [
            _formula_evidence_key(formula.text)
            for formula in block.formulas
        ]
        if any(
            (
                candidate_key := _formula_evidence_key(candidate)
            )
            and not any(
                candidate_key in formula_key
                for formula_key in formula_keys
            )
            for candidate in _enumerated_assignment_lines(block.text)
        ):
            issues.append(f"{prefix}:formula_span_missing")
        for formula_index, formula in enumerate(block.formulas):
            for issue in _formula_issues(formula):
                issues.append(
                    f"{prefix}:formula_{formula_index}:{issue}"
                )
            formula_key = _formula_evidence_key(formula.text)
            if formula_key and formula_key not in block_text_key:
                issues.append(
                    f"{prefix}:formula_{formula_index}:"
                    "formula_not_in_block_text"
                )
    return tuple(dict.fromkeys(issues))


def _selection_payload(layout: PageLayoutExtraction) -> str:
    payload = {
        "page": layout.page,
        "profile": layout.profile,
        "blocks": [
            {
                "block_id": block.block_id,
                "category": block.category,
                "text": block.text,
                "formula_count": len(block.formulas),
            }
            for block in layout.blocks
            if block.category not in {"header", "footer"}
        ],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _unique_named_formula_index(
    block: PageLayoutBlock,
    name: str,
) -> int | None:
    name_key = _formula_evidence_key(name)
    if not name_key:
        return None
    formula_keys = [
        _formula_evidence_key(formula.text)
        for formula in block.formulas
    ]
    exact_matches = [
        index
        for index, formula_key in enumerate(formula_keys)
        if formula_key and formula_key == name_key
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    contained_matches = [
        index
        for index, formula_key in enumerate(formula_keys)
        if formula_key and formula_key in name_key
    ]
    if len(contained_matches) == 1:
        return contained_matches[0]
    return None


def _publishable_materialized_node(
    node: PageKnowledgeNode,
) -> PageKnowledgeNode | None:
    disposition = _page_node_field_disposition(node)
    if disposition.action in {
        "reextract_candidate",
        "reject_entire_node",
    }:
        return None
    if not _evidence_excerpt_is_specific(
        _normalized_evidence_text(node.evidence_text)
    ):
        return None
    return node.model_copy(
        update={
            "name": disposition.name,
            "definition": disposition.definition,
        }
    )


def _supplement_layout_formulas(
    *,
    layout: PageLayoutExtraction,
    nodes: list[PageKnowledgeNode],
) -> list[PageKnowledgeNode]:
    reconciled = list(nodes)
    referenced_formula_keys = {
        key
        for node in reconciled
        if (key := _formula_evidence_key(node.formula_text))
    }
    used_temp_ids = {node.temp_id for node in reconciled}

    for block in layout.blocks:
        for formula_index, formula in enumerate(block.formulas):
            formula_key = _formula_evidence_key(formula.text)
            if not formula_key or formula_key in referenced_formula_keys:
                continue

            evidence_matches = [
                index
                for index, node in enumerate(reconciled)
                if (
                    not node.formula_text
                    and formula_key
                    in _formula_evidence_key(node.evidence_text)
                )
            ]
            if len(evidence_matches) == 1:
                index = evidence_matches[0]
                upgraded = reconciled[index].model_copy(
                    update={
                        "formula_text": formula.text,
                        "formula_latex": formula.latex,
                    }
                )
                materialized = _publishable_materialized_node(upgraded)
                if materialized is not None:
                    reconciled[index] = materialized
                    referenced_formula_keys.add(formula_key)
                    continue

            if len(reconciled) >= 12:
                replace_index = next(
                    (
                        index
                        for index in range(len(reconciled) - 1, -1, -1)
                        if not reconciled[index].formula_text
                    ),
                    None,
                )
                if replace_index is None:
                    continue
                used_temp_ids.discard(reconciled[replace_index].temp_id)
                reconciled.pop(replace_index)

            temp_id = (
                f"supplement-{block.block_id}-{formula_index:02d}"
            )
            suffix = 1
            while temp_id in used_temp_ids:
                temp_id = (
                    f"supplement-{block.block_id}-"
                    f"{formula_index:02d}-{suffix:02d}"
                )
                suffix += 1
            supplemental = PageKnowledgeNode(
                temp_id=temp_id,
                name=(
                    _formula_result_label(formula.text)
                    or formula.text
                ),
                type="formula",
                role="formula",
                definition=block.text,
                evidence_text=block.text,
                formula_text=formula.text,
                formula_latex=formula.latex,
                bbox=block.bbox,
                confidence=block.confidence,
                terminal_gold_gate=_TERMINAL_ATOM_GATE,
            )
            materialized = _publishable_materialized_node(supplemental)
            if materialized is None:
                continue
            reconciled.append(materialized)
            used_temp_ids.add(materialized.temp_id)
            referenced_formula_keys.add(formula_key)

    return reconciled


def reconcile_layout_formulas(
    *,
    layout: PageLayoutExtraction,
    extraction: PageKnowledgeExtraction,
) -> PageKnowledgeExtraction:
    if layout.page != extraction.page:
        raise ValueError("layout audit page does not match extraction page")
    nodes = _supplement_layout_formulas(
        layout=layout,
        nodes=list(extraction.nodes),
    )
    has_knowledge = extraction.has_knowledge or bool(nodes)
    return extraction.model_copy(
        update={
            "complete": extraction.complete and layout.complete,
            "confidence": min(
                extraction.confidence,
                layout.confidence,
            ),
            "has_knowledge": has_knowledge,
            "no_knowledge_reason": (
                "" if has_knowledge else extraction.no_knowledge_reason
            ),
            "nodes": nodes,
        }
    )


def materialize_layout_selection(
    layout: PageLayoutExtraction,
    selection: LayoutNodeSelection,
) -> PageKnowledgeExtraction:
    if selection.page != layout.page:
        raise ValueError("selection page does not match layout page")
    blocks = {block.block_id: block for block in layout.blocks}
    heading = ""
    if selection.heading_block_id:
        heading_block = blocks.get(selection.heading_block_id)
        if heading_block is None:
            raise ValueError("heading references an unknown layout block")
        if heading_block.category != "heading":
            raise ValueError("heading reference is not a heading block")
        heading = heading_block.text

    nodes: list[PageKnowledgeNode] = []
    referenced_formula_keys: set[str] = set()
    referenced_node_keys: set[tuple[str, str]] = set()
    dropped_node_issues: list[str] = []
    for draft in selection.nodes:
        block = blocks.get(draft.block_id)
        if block is None:
            raise ValueError("node references an unknown layout block")
        if (
            len(block.text) < 24
            and block.text.rstrip().endswith(("：", ":"))
        ):
            continue
        normalized_name = "".join(draft.name.split()).casefold()
        normalized_evidence = "".join(block.text.split()).casefold()
        formula_text = ""
        formula_latex = ""
        formula_key = ""
        formula_index = draft.formula_index
        inferred_formula_index = _unique_named_formula_index(
            block,
            draft.name,
        )
        if inferred_formula_index is not None:
            formula_index = inferred_formula_index
        elif formula_index is None:
            if len(block.formulas) == 1:
                formula_index = 0
            elif block.formulas:
                continue
        if formula_index is not None:
            if formula_index >= len(block.formulas):
                continue
            formula = block.formulas[formula_index]
            formula_text = formula.text
            formula_latex = formula.latex
            formula_key = _formula_evidence_key(formula_text)
            if formula_key in referenced_formula_keys:
                continue
        name = draft.name
        if inferred_formula_index is not None:
            name = formula_text
        if (
            normalized_name not in normalized_evidence
            or re.match(r"^\s*[=≈≤≥<>]", name)
            or _DANGLING_TEXT_SUFFIX.search(
                name.rstrip("，。；;：:")
            )
        ):
            name = formula_text or block.text
        candidate = PageKnowledgeNode(
            temp_id=draft.temp_id,
            name=name,
            type=draft.type,
            role=draft.role,
            definition=block.text,
            evidence_text=block.text,
            formula_text=formula_text,
            formula_latex=formula_latex,
            bbox=block.bbox,
            confidence=block.confidence,
            terminal_gold_gate=draft.terminal_gold_gate,
        )
        materialized = _publishable_materialized_node(candidate)
        if materialized is None:
            disposition = _page_node_field_disposition(candidate)
            dropped_node_issues.extend(
                f"label_{issue}"
                for issue in disposition.label_issues
            )
            dropped_node_issues.extend(
                f"definition_{issue}"
                for issue in disposition.definition_issues
            )
            if disposition.action in {
                "reextract_candidate",
                "reject_entire_node",
            }:
                dropped_node_issues.append(
                    f"field_{disposition.action}"
                )
            if not _evidence_excerpt_is_specific(
                _normalized_evidence_text(candidate.evidence_text)
            ):
                dropped_node_issues.append("evidence_not_specific")
            continue
        node_key = (
            "".join(materialized.name.split()).casefold(),
            normalized_evidence,
        )
        if node_key in referenced_node_keys:
            continue
        referenced_node_keys.add(node_key)
        if formula_key:
            referenced_formula_keys.add(formula_key)
        nodes.append(materialized)

    nodes = _supplement_layout_formulas(
        layout=layout,
        nodes=nodes,
    )

    referenced_evidence = {
        "".join(node.evidence_text.split()).casefold()
        for node in nodes
    }
    for block in layout.blocks:
        if len(nodes) >= 12:
            break
        if not _is_supplemental_nonformula_block(block):
            continue
        evidence_key = "".join(block.text.split()).casefold()
        if not evidence_key or evidence_key in referenced_evidence:
            continue
        supplemental = PageKnowledgeNode(
            temp_id=(
                f"supplement-{block.block_id}-"
                f"{len(nodes):02d}"
            ),
            name=block.text,
            type="concept",
            role="other",
            definition=block.text,
            evidence_text=block.text,
            bbox=block.bbox,
            confidence=block.confidence,
            terminal_gold_gate=_TERMINAL_NO_FURTHER_GATE,
        )
        materialized = _publishable_materialized_node(supplemental)
        if materialized is None:
            repaired_name = (
                _statement_subject_label(block.text)
                or _conditional_result_label(block.text)
            )
            if repaired_name is None:
                continue
            supplemental = supplemental.model_copy(
                update={"name": repaired_name}
            )
            materialized = _publishable_materialized_node(supplemental)
            if materialized is None:
                continue
        nodes.append(materialized)
        referenced_evidence.add(evidence_key)

    if selection.has_knowledge and not nodes:
        detail = ",".join(dict.fromkeys(dropped_node_issues))
        raise ValueError(
            "selection contains no publishable layout nodes"
            + (f": {detail}" if detail else "")
        )

    return PageKnowledgeExtraction(
        page=layout.page,
        complete=layout.complete and selection.complete,
        confidence=layout.confidence,
        heading=heading,
        has_knowledge=selection.has_knowledge,
        no_knowledge_reason=selection.no_knowledge_reason,
        nodes=nodes,
    )


def _is_low_information_fallback_text(value: str) -> bool:
    compact = re.sub(r"\s+", "", value).strip("，。；;：:")
    return (
        compact in _FALLBACK_STANDALONE_CONNECTIVES
        or _ISOLATED_MATH_IDENTIFIER.fullmatch(compact) is not None
    )


def _is_fallback_nonformula_block(block: PageLayoutBlock) -> bool:
    if block.formulas or block.category in {
        "heading",
        "header",
        "footer",
        "figure",
        "footnote",
    }:
        return False
    if len(block.text) < 24 and block.text.rstrip().endswith(("：", ":")):
        return False
    return not _is_low_information_fallback_text(block.text)


def _is_supplemental_nonformula_block(
    block: PageLayoutBlock,
) -> bool:
    return (
        block.category != "caption"
        and _is_fallback_nonformula_block(block)
    )


def _conditional_result_label(value: str) -> str | None:
    compact = re.sub(r"\s+", " ", value).strip(" ，,；;：:。！？!?")
    if not compact.startswith(("当", "若", "如果")):
        return None
    separators = [
        match.end()
        for match in re.finditer(r"(?:时|则)", compact)
    ]
    for start in reversed(separators):
        candidate = compact[start:].strip(" ，,；;：:")
        if candidate and not _page_node_field_disposition(
            PageKnowledgeNode(
                temp_id="conditional-result",
                name=candidate,
                type="concept",
                role="other",
                definition=value,
                evidence_text=value,
                bbox=[0, 0, 1, 1],
                confidence=1,
            )
        ).label_issues:
            return candidate
    return None


def _formula_result_label(value: str) -> str | None:
    compact = re.sub(r"\s+", " ", value).strip(" ，,；;：:。！？!?")
    clauses = [
        clause.strip()
        for clause in re.split(r"[，,；;。！？!?]", compact)
        if clause.strip()
    ]
    relation = re.compile(r"(?:≈|=|≤|≥|<|>|~|∝)")
    result_marker = re.compile(
        r"(?:估算出的|计算得到的|可得|得到|得出|表明|说明|则)"
    )
    for clause in reversed(clauses):
        if relation.search(clause) is None:
            continue
        starts = [
            match.end()
            for match in result_marker.finditer(clause)
        ]
        for start in [*reversed(starts), 0]:
            candidate = clause[start:].strip(" ，,；;：:")
            if (
                not 2 <= len(candidate) <= 48
                or relation.search(candidate) is None
            ):
                continue
            disposition = _page_node_field_disposition(
                PageKnowledgeNode(
                    temp_id="formula-result",
                    name=candidate,
                    type="concept",
                    role="other",
                    definition=value,
                    evidence_text=value,
                    bbox=[0, 0, 1, 1],
                    confidence=1,
                )
            )
            if not disposition.label_issues:
                return candidate
    return None


def _statement_subject_label(value: str) -> str | None:
    compact = re.sub(r"\s+", " ", value).strip(" ，,；;：:。！？!?")
    compact = re.sub(r"^[♦◆◇•·▪▫]\s*", "", compact)
    candidates: list[str] = []
    locative = re.search(
        r"(?:在|于)(?P<label>.{2,40}?)(?:上|中|内)"
        r"(?:集聚|存在|发生|产生|形成)",
        compact,
    )
    if locative is not None:
        candidates.append(locative.group("label"))
    predicate = re.search(
        r"(?P<label>.{2,40}?)(?:都是|是|具有|受到|包括|称为)",
        compact,
    )
    if predicate is not None:
        candidates.append(predicate.group("label"))
    for candidate in candidates:
        candidate = candidate.strip(" ，,；;：:")
        if not 2 <= len(candidate) <= 48:
            continue
        disposition = _page_node_field_disposition(
            PageKnowledgeNode(
                temp_id="statement-subject",
                name=candidate,
                type="concept",
                role="other",
                definition=value,
                evidence_text=value,
                bbox=[0, 0, 1, 1],
                confidence=1,
            )
        )
        if not disposition.label_issues:
            return candidate
    return None


def _fallback_layout_selection(
    layout: PageLayoutExtraction,
) -> LayoutNodeSelection:
    heading_block = next(
        (
            block
            for block in layout.blocks
            if block.category == "heading"
        ),
        None,
    )
    drafts: list[LayoutNodeDraft] = []
    for block in layout.blocks:
        if len(drafts) >= 12:
            break
        if block.category == "heading":
            quoted_claim = _QUOTED_ATOMIC_CLAIM.search(block.text)
            if quoted_claim:
                drafts.append(
                    LayoutNodeDraft(
                        temp_id=f"fallback-{block.block_id}",
                        name=quoted_claim.group(1),
                        type="principle",
                        role="principle",
                        block_id=block.block_id,
                        confidence=block.confidence,
                        terminal_gold_gate=_TERMINAL_NO_FURTHER_GATE,
                    )
                )
            continue
        if block.category in {
            "header",
            "footer",
            "figure",
            "footnote",
        }:
            continue
        if block.formulas:
            for formula_index, formula in enumerate(block.formulas):
                if len(drafts) >= 12:
                    break
                drafts.append(
                    LayoutNodeDraft(
                        temp_id=f"fallback-{block.block_id}-{formula_index}",
                        name=(
                            _formula_result_label(formula.text)
                            or formula.text
                        ),
                        type="formula",
                        role="formula",
                        block_id=block.block_id,
                        formula_index=formula_index,
                        confidence=block.confidence,
                        terminal_gold_gate=_TERMINAL_ATOM_GATE,
                    )
                )
        elif _is_fallback_nonformula_block(block):
            drafts.append(
                LayoutNodeDraft(
                    temp_id=f"fallback-{block.block_id}",
                    name=(
                        _statement_subject_label(block.text)
                        or block.text
                    ),
                    type="concept",
                    role="other",
                    block_id=block.block_id,
                    confidence=block.confidence,
                    terminal_gold_gate=_TERMINAL_NO_FURTHER_GATE,
                )
            )
    return LayoutNodeSelection(
        page=layout.page,
        complete=layout.complete,
        confidence=layout.confidence,
        heading_block_id=(
            heading_block.block_id if heading_block is not None else ""
        ),
        has_knowledge=bool(drafts),
        no_knowledge_reason=(
            "" if drafts else "已验收布局中没有可发布知识块"
        ),
        nodes=drafts,
    )


def _validation_issue_codes(exc: ValidationError) -> list[str]:
    issues: list[str] = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error.get("loc", ()))
        error_type = str(error.get("type") or "validation_error")
        issues.append(
            f"{location}:{error_type}" if location else error_type
        )
    return list(dict.fromkeys(issues))


def _repair_layout_selection_payload(
    payload: Any,
    layout: PageLayoutExtraction,
) -> Any:
    if not isinstance(payload, dict):
        return payload
    raw_nodes = payload.get("nodes")
    if not isinstance(raw_nodes, list):
        return payload

    blocks = {block.block_id: block for block in layout.blocks}
    repaired = dict(payload)
    heading_block_id = repaired.get("heading_block_id")
    if isinstance(heading_block_id, str):
        heading_block = blocks.get(heading_block_id.strip())
        if (
            heading_block is not None
            and heading_block.category != "heading"
        ):
            repaired["heading_block_id"] = ""
    repaired_nodes: list[Any] = []
    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            repaired_nodes.append(raw_node)
            continue
        node = dict(raw_node)
        block_id = node.get("block_id")
        if not isinstance(block_id, str) or not block_id.strip():
            name = node.get("name")
            if isinstance(name, str) and name.strip():
                normalized_name = "".join(name.split()).casefold()
                matches = [
                    block
                    for block in layout.blocks
                    if normalized_name
                    in "".join(block.text.split()).casefold()
                ]
                if len(matches) == 1:
                    block_id = matches[0].block_id
                    node["block_id"] = block_id
        block = (
            blocks.get(block_id.strip())
            if isinstance(block_id, str) and block_id.strip()
            else None
        )
        if block is not None:
            if node.get("confidence") in {None, ""}:
                node["confidence"] = block.confidence
            formula_index = node.get("formula_index")
            if (
                not block.formulas
                or isinstance(formula_index, bool)
                or not isinstance(formula_index, int)
                or formula_index < 0
                or formula_index >= len(block.formulas)
            ):
                node["formula_index"] = None
        repaired_nodes.append(node)

    repaired["nodes"] = repaired_nodes
    return repaired


async def extract_layout_nodes(
    *,
    layout: PageLayoutExtraction,
    runtime: RoleRuntime,
    min_confidence: float,
    max_attempts: int,
) -> tuple[PageKnowledgeExtraction | None, int, list[str]]:
    if not runtime.available or runtime.client is None:
        return None, 0, ["model_unavailable"]
    attempts = max(int(max_attempts), 1)
    fallback_selection = _fallback_layout_selection(layout)
    page_has_knowledge_signal = fallback_selection.has_knowledge
    last_issues: list[str] = []
    for attempt in range(1, attempts + 1):
        repair = ""
        if last_issues:
            repair = (
                "\n上一次输出未通过质量门："
                + "、".join(last_issues[:10])
                + "。只修正节点选择、块引用、name 和 terminal_gold_gate；"
                "不得自行输出或改写 evidence、formula、bbox。"
                "name 必须是块内连续原文中的 2..48 字符单行自足表达，"
                "不得含章节编号、句子开头、连接词或句末标点；短词本身"
                "不能教会零基础学生时不得选择。terminal_gold_gate 中"
                "name_teaches_novice 必须为 true，两个终止条件至少一个"
                "为 true。"
            )
        try:
            with model_call_scope(
                role=PAGE_LAYOUT_NODE_ROLE,
                input_unit_ids=(f"page:{layout.page}",),
                stage="page_layout_nodes",
            ):
                payload = await runtime.client.complete_json(
                    model=runtime.model,
                    system_prompt=LAYOUT_NODE_SYSTEM_PROMPT,
                    user_prompt=(
                        f"从第 {layout.page} 页已验收布局块选择原子节点。"
                        f"{repair}\n输入布局 JSON：\n"
                        f"{_selection_payload(layout)}"
                    ),
                    **_structured_json_call_kwargs(
                        runtime,
                        PAGE_LAYOUT_NODE_MAX_OUTPUT_TOKENS,
                        timeout_seconds=PAGE_LAYOUT_TIMEOUT_SECONDS,
                        reasoning_token_reserve=(
                            PAGE_LAYOUT_NODE_REASONING_TOKEN_RESERVE
                        ),
                    ),
                )
            selection = LayoutNodeSelection.model_validate(
                _repair_layout_selection_payload(payload, layout)
            )
            extraction = materialize_layout_selection(layout, selection)
            issues = page_knowledge_issues(
                extraction,
                expected_page=layout.page,
                min_confidence=min_confidence,
                page_has_text_signal=page_has_knowledge_signal,
            )
            if not issues:
                return extraction, attempt, []
            last_issues = list(issues)
        except ValidationError as exc:
            last_issues = _validation_issue_codes(exc)
        except ModelProviderError as exc:
            del exc
            last_issues = ["ModelProviderError"]
        except ValueError as exc:
            last_issues = [" ".join(str(exc).split())[:160]]
    fallback = materialize_layout_selection(
        layout,
        fallback_selection,
    )
    fallback_issues = page_knowledge_issues(
        fallback,
        expected_page=layout.page,
        min_confidence=min_confidence,
        page_has_text_signal=page_has_knowledge_signal,
    )
    if not fallback_issues:
        return (
            fallback,
            attempts,
            [
                "node_selector_deterministic_fallback",
                *last_issues[:6],
            ],
        )
    return None, attempts, [
        *last_issues,
        *(f"fallback:{issue}" for issue in fallback_issues),
    ]


async def extract_page_layout_knowledge(
    *,
    image_path: Path,
    page: int,
    runtime: RoleRuntime,
    profile: LayoutProfile,
    min_confidence: float,
    max_layout_attempts: int,
    max_node_attempts: int,
    extract_nodes: bool = True,
) -> LayoutKnowledgePageResult:
    if not runtime.available or runtime.client is None:
        return LayoutKnowledgePageResult(issues=["model_unavailable"])
    if not image_path.is_file():
        return LayoutKnowledgePageResult(issues=["image_not_found"])

    from PIL import Image

    from .pdf_page_knowledge import _data_url

    with Image.open(image_path) as image:
        image_width, image_height = image.size
    image_data_url = await asyncio.to_thread(_data_url, image_path)
    prompt = (
        DOTS_LAYOUT_SYSTEM_PROMPT
        if profile == "dots"
        else CHANDRA_LAYOUT_SYSTEM_PROMPT
    )
    layout_attempt_limit = max(int(max_layout_attempts), 1)
    last_issues: list[str] = []
    layout: PageLayoutExtraction | None = None
    layout_attempt = 0
    for layout_attempt in range(1, layout_attempt_limit + 1):
        repair = ""
        if last_issues:
            repair = (
                " 上一次输出未通过布局质量门："
                + "、".join(last_issues[:10])
                + "。逐项修正，尤其核对负指数、分母、下标和 bbox。"
            )
            if any(
                "formula_not_in_block_text" in issue
                for issue in last_issues
            ):
                repair += (
                    " 同一 block 的 formulas.text 必须逐项由 block.text "
                    "中的连续完整表达式支持；若 block.text 漏字符，"
                    "必须同步修正原文转录。"
                )
            if any(
                "formula_span_missing" in issue
                for issue in last_issues
            ):
                repair += (
                    " 同一 block 中每条独立赋值或枚举关系式都必须"
                    "分别列入 formulas，不能只列其中一部分。"
                )
            if any(
                "canonical_text_contains_latex" in issue
                or "formula_text_latex_symbol_mismatch" in issue
                for issue in last_issues
            ):
                repair += (
                    " formulas.text 只能使用 Unicode canonical 文本，"
                    "不得含反斜杠 LaTeX 命令；希腊字母和数学符号必须与"
                    "同项 latex 完全一致。"
                )
        try:
            with model_call_scope(
                role=PAGE_LAYOUT_ROLE,
                input_unit_ids=(f"page:{page}",),
                stage=f"page_layout_{profile}",
            ):
                payload = await runtime.client.complete_multimodal_json(
                    model=runtime.model,
                    system_prompt=prompt,
                    user_prompt=(
                        f"解析第 {page} 页。图像像素尺寸为 "
                        f"{image_width}×{image_height}。{repair}"
                    ),
                    image_data_url=image_data_url,
                    **_structured_json_call_kwargs(
                        runtime,
                        PAGE_LAYOUT_MAX_OUTPUT_TOKENS,
                        timeout_seconds=(
                            PAGE_LAYOUT_TIMEOUT_SECONDS
                            if layout_attempt == 1
                            else PAGE_LAYOUT_RETRY_TIMEOUT_SECONDS
                        ),
                    ),
                )
            layout = (
                parse_dots_layout(
                    payload,
                    expected_page=page,
                    image_width=image_width,
                    image_height=image_height,
                )
                if profile == "dots"
                else parse_chandra_layout(
                    payload,
                    expected_page=page,
                )
            )
            issues = page_layout_issues(
                layout,
                expected_page=page,
                min_confidence=min_confidence,
            )
            if not issues:
                break
            last_issues = list(issues)
            layout = None
        except ValidationError as exc:
            last_issues = _validation_issue_codes(exc)
            layout = None
        except ModelProviderError as exc:
            del exc
            last_issues = ["ModelProviderError"]
            layout = None
        except ValueError as exc:
            last_issues = [" ".join(str(exc).split())[:160]]
            layout = None

    if layout is None:
        return LayoutKnowledgePageResult(
            layout_attempts=layout_attempt,
            issues=last_issues,
        )

    if not extract_nodes:
        return LayoutKnowledgePageResult(
            layout=layout,
            layout_attempts=layout_attempt,
        )

    extraction, node_attempts, node_issues = await extract_layout_nodes(
        layout=layout,
        runtime=runtime,
        min_confidence=min_confidence,
        max_attempts=max_node_attempts,
    )
    return LayoutKnowledgePageResult(
        layout=layout,
        extraction=extraction,
        layout_attempts=layout_attempt,
        node_attempts=node_attempts,
        issues=node_issues,
    )
