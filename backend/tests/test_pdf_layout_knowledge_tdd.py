from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from backend.app.agents import RoleRuntime
from backend.app.pdf_layout_knowledge import (
    LayoutNodeSelection,
    PAGE_LAYOUT_NODE_REASONING_TOKEN_RESERVE,
    PageLayoutExtraction,
    extract_page_layout_knowledge,
    extract_layout_nodes,
    materialize_layout_selection,
    page_layout_issues,
    parse_chandra_layout,
    parse_dots_layout,
    reconcile_layout_formulas,
)
from backend.app.pdf_page_knowledge import (
    PageKnowledgeExtraction,
    page_knowledge_issues,
)
from backend.tools.pdf_layout_ab import (
    CANARY_PAGES,
    EXPECTED_FORMULAS,
    REQUIRED_TEXT,
    _benchmark_page_status,
    _formula_audit,
)


TERMINAL_GOLD_GATE = {
    "name_teaches_novice": True,
    "no_further_bullet_decomposition": True,
    "minimum_knowledge_atom": False,
}


class _FakeLayoutNodeClient:
    def __init__(self, payload: dict | list[dict]):
        self.payloads = (
            list(payload)
            if isinstance(payload, list)
            else [payload]
        )
        self.calls: list[dict] = []

    async def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        payload = self.payloads.pop(0)
        if isinstance(payload, dict):
            for node in payload.get("nodes", []):
                if isinstance(node, dict):
                    node.setdefault(
                        "terminal_gold_gate",
                        TERMINAL_GOLD_GATE,
                    )
        return payload


class _FakePageLayoutClient:
    def __init__(self, payloads: list[dict]):
        self.payloads = list(payloads)
        self.calls: list[dict] = []

    async def complete_multimodal_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.payloads.pop(0)


def _runtime(client) -> RoleRuntime:
    return RoleRuntime(
        provider="qwen",
        model="qwen3.8-max-preview",
        client=client,
        available=True,
    )


class PdfLayoutProfileTDDTests(unittest.TestCase):
    def test_dots_pixel_bbox_and_formula_are_normalized(self):
        extraction = parse_dots_layout(
            {
                "page": 84,
                "complete": True,
                "confidence": 0.96,
                "coordinate_space": "pixels",
                "blocks": [
                    {
                        "bbox": [100, 200, 900, 400],
                        "category": "Formula",
                        "text": (
                            "ν=c/λ=3×10^8/(0.6328×10^-6)"
                            "≈5×10^14 Hz"
                        ),
                        "latex": (
                            r"\nu=\frac{c}{\lambda}="
                            r"\frac{3\times10^{8}}"
                            r"{0.6328\times10^{-6}}"
                            r"\approx5\times10^{14}\,\mathrm{Hz}"
                        ),
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=84,
            image_width=1000,
            image_height=800,
        )

        block = extraction.blocks[0]
        self.assertEqual(block.bbox, [0.1, 0.25, 0.8, 0.25])
        self.assertEqual(block.category, "formula")
        self.assertIn("10^-6", block.formulas[0].text)
        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=84,
                min_confidence=0.85,
            ),
            (),
        )

    def test_dots_rejects_formula_without_equivalent_latex(self):
        with self.assertRaises(ValueError):
            parse_dots_layout(
                [
                    {
                        "bbox": [0, 0, 100, 100],
                        "category": "Formula",
                        "text": "10^-6",
                    }
                ],
                expected_page=1,
                image_width=100,
                image_height=100,
            )

    def test_dots_gate_requires_inline_inequality_formula_contract(self):
        extraction = parse_dots_layout(
            {
                "page": 92,
                "complete": True,
                "confidence": 0.96,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 200],
                        "category": "Text",
                        "text": "光强满足 I > P/S",
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=92,
            image_width=1920,
            image_height=1440,
        )

        self.assertIn(
            "block_0:formula_contract_missing",
            page_layout_issues(
                extraction,
                expected_page=92,
                min_confidence=0.85,
            ),
        )

    def test_dots_gate_requires_inline_arrow_formula_contract(self):
        extraction = parse_dots_layout(
            {
                "page": 62,
                "complete": True,
                "confidence": 0.96,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 200],
                        "category": "Text",
                        "text": "经验规律：(n+0.7l)大→E大",
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=62,
            image_width=1920,
            image_height=1440,
        )

        self.assertIn(
            "block_0:formula_contract_missing",
            page_layout_issues(
                extraction,
                expected_page=62,
                min_confidence=0.85,
            ),
        )

    def test_dots_gate_allows_leading_arrow_natural_language_relation(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 200],
                        "category": "Text",
                        "text": "→ A_21 增大，则 B_12 也增大",
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
            (),
        )

    def test_chandra_html_preserves_nested_text_math_and_bbox(self):
        extraction = parse_chandra_layout(
            {
                "page": 92,
                "complete": True,
                "confidence": 0.97,
                "html": (
                    '<div data-label="Section-header" '
                    'data-bbox="100 50 900 120" data-confidence="0.98">'
                    "<h2>激光的特性</h2></div>"
                    '<div data-label="Text" '
                    'data-bbox="100 180 900 300" data-confidence="0.96">'
                    "<p>脉冲瞬时功率可达 "
                    '<math data-canonical=">10^14 W">'
                    r">10^{14}\,\mathrm{W}</math></p></div>"
                ),
            },
            expected_page=92,
        )

        self.assertEqual(len(extraction.blocks), 2)
        heading, paragraph = extraction.blocks
        self.assertEqual(heading.category, "heading")
        self.assertEqual(heading.text, "激光的特性")
        self.assertEqual(paragraph.bbox, [0.1, 0.18, 0.8, 0.12])
        self.assertEqual(
            paragraph.text,
            "脉冲瞬时功率可达 >10^14 W",
        )
        self.assertEqual(
            paragraph.formulas[0].text,
            "脉冲瞬时功率可达 >10^14 W",
        )
        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=92,
                min_confidence=0.85,
            ),
            (),
        )

    def test_chandra_html_rejects_math_without_canonical_text(self):
        with self.assertRaisesRegex(ValueError, "math_missing"):
            parse_chandra_layout(
                {
                    "page": 1,
                    "complete": True,
                    "confidence": 0.95,
                    "html": (
                        '<div data-label="Formula" '
                        'data-bbox="0 0 1000 200">'
                        r"<math>10^{-6}</math></div>"
                    ),
                },
                expected_page=1,
            )

    def test_chandra_normalizes_unicode_scripts_before_quality_gate(self):
        extraction = parse_chandra_layout(
            {
                "page": 92,
                "complete": True,
                "confidence": 0.95,
                "html": (
                    '<div data-label="Formula" '
                    'data-bbox="0 0 1000 200">'
                    '<math data-canonical="I>10¹⁷ W/cm²">'
                    r"I>10^17\,\mathrm{W/cm^2}</math></div>"
                ),
            },
            expected_page=92,
        )

        self.assertEqual(
            extraction.blocks[0].formulas[0].text,
            "I>10^17 W/cm^2",
        )
        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=92,
                min_confidence=0.85,
            ),
            (),
        )

    def test_chandra_reconstructs_html_superscripts_as_latex(self):
        extraction = parse_chandra_layout(
            {
                "page": 92,
                "complete": True,
                "confidence": 0.95,
                "html": (
                    '<div data-label="Text" '
                    'data-bbox="0 0 1000 200">'
                    "非聚焦状态 "
                    '<math data-canonical="I > 10^{11} W/m^{2}">'
                    "I &gt; 10<sup>11</sup> W/m<sup>2</sup>"
                    "</math></div>"
                ),
            },
            expected_page=92,
        )

        formula = extraction.blocks[0].formulas[0]
        self.assertEqual(formula.text, "I > 10^11 W/m^2")
        self.assertEqual(formula.latex, "I > 10^{11} W/m^{2}")
        self.assertEqual(
            extraction.blocks[0].text,
            "非聚焦状态 I > 10^11 W/m^2",
        )
        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=92,
                min_confidence=0.85,
            ),
            (),
        )

    def test_layout_gate_rejects_formula_sign_mismatch(self):
        extraction = parse_chandra_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "html": (
                    '<div data-label="Formula" '
                    'data-bbox="0 0 1000 200">'
                    '<math data-canonical="10^6">'
                    r"10^{-6}</math></div>"
                ),
            },
            expected_page=1,
        )

        self.assertIn(
            "block_0:formula_0:formula_text_latex_exponent_mismatch",
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
        )

    def test_layout_gate_rejects_unit_subscript_and_dangling_text(self):
        extraction = parse_dots_layout(
            {
                "page": 42,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 200],
                        "category": "Formula",
                        "text": "R=H_z",
                        "latex": "R=H_z",
                        "confidence": 0.95,
                    },
                    {
                        "bbox": [100, 300, 900, 400],
                        "category": "Text",
                        "text": "电子自旋是一种",
                        "confidence": 0.95,
                    },
                ],
            },
            expected_page=42,
            image_width=1920,
            image_height=1440,
        )

        issues = page_layout_issues(
            extraction,
            expected_page=42,
            min_confidence=0.85,
        )
        self.assertIn("block_0:unit_subscript_corruption", issues)
        self.assertIn("block_1:dangling_text_suffix", issues)

    def test_layout_gate_allows_colon_introducing_following_list(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 200],
                        "category": "Text",
                        "text": "激活物质应满足：",
                        "confidence": 0.95,
                    },
                    {
                        "bbox": [100, 220, 900, 320],
                        "category": "List-item",
                        "text": "有三个或更多能级。",
                        "confidence": 0.95,
                    },
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
            (),
        )

    def test_layout_gate_rejects_missing_scientific_power_marker(self):
        extraction = parse_dots_layout(
            {
                "page": 85,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 200],
                        "category": "Text",
                        "text": "在超高稳频条件下，却会小到10-15",
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=85,
            image_width=1920,
            image_height=1440,
        )

        self.assertIn(
            "block_0:scientific_power_marker_missing",
            page_layout_issues(
                extraction,
                expected_page=85,
                min_confidence=0.85,
            ),
        )

    def test_layout_gate_requires_unsupplemented_formula_contract(self):
        extraction = parse_dots_layout(
            {
                "page": 92,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 200],
                        "category": "Text",
                        "text": "波长满足 λ = c/ν",
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=92,
            image_width=1920,
            image_height=1440,
        )

        self.assertIn(
            "block_0:formula_contract_missing",
            page_layout_issues(
                extraction,
                expected_page=92,
                min_confidence=0.85,
            ),
        )

    def test_dots_uses_formula_mapping_for_inline_markdown_math(self):
        extraction = parse_dots_layout(
            {
                "page": 85,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 200],
                        "category": "Text",
                        "text": (
                            "而He-Ne激光器输出激光的 "
                            r"$\frac{\Delta\nu}{\nu}$"
                        ),
                        "formulas": [
                            {
                                "text": "Δν/ν",
                                "latex": r"\frac{\Delta\nu}{\nu}",
                            }
                        ],
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=85,
            image_width=1920,
            image_height=1440,
        )

        self.assertEqual(
            extraction.blocks[0].text,
            "而He-Ne激光器输出激光的 Δν/ν",
        )

    def test_dots_removes_inline_markdown_emphasis_markers(self):
        extraction = parse_dots_layout(
            {
                "page": 88,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 200],
                        "category": "Text",
                        "text": "可使输出*纵模个数减少*。",
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=88,
            image_width=1920,
            image_height=1440,
        )

        self.assertEqual(
            extraction.blocks[0].text,
            "可使输出纵模个数减少。",
        )

    def test_dots_normalizes_simple_inline_math_commands(self):
        extraction = parse_dots_layout(
            {
                "page": 86,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 200],
                        "category": "Text",
                        "text": r"$\lambda_k$—真空中的波长",
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=86,
            image_width=1920,
            image_height=1440,
        )

        self.assertEqual(
            extraction.blocks[0].text,
            "λ_k—真空中的波长",
        )

    def test_formula_oracle_does_not_accept_a_short_fragment(self):
        audit = _formula_audit(
            ["Δν/ν"],
            ["Δν/ν=1.3×10^9/(5×10^14)≈3×10^-6"],
        )

        self.assertEqual(audit["exact_count"], 0)

    def test_formula_oracle_accepts_equivalent_derivative_notation(self):
        audit = _formula_audit(
            ["-iℏ d/dx Ψ(x) = a Ψ(x)"],
            ["-iℏdΨ(x)/dx=aΨ(x)"],
        )

        self.assertEqual(audit["exact_count"], 1)
        self.assertEqual(
            _formula_audit(
                ["-iℏ d/dy Ψ(x) = a Ψ(x)"],
                ["-iℏdΨ(x)/dx=aΨ(x)"],
            )["exact_count"],
            0,
        )

    def test_formula_oracle_accepts_unicode_similarity_operator(self):
        self.assertEqual(
            _formula_audit(
                ["c ∼ 3 × 10^8 m/s"],
                ["c~3×10^8 m/s"],
            )["exact_count"],
            1,
        )

    def test_formula_oracle_accepts_split_conjunctive_relations(self):
        expected = "∂C_x/∂t=∂C_y/∂t=0,∂C_z/∂t≠0"

        self.assertEqual(
            _formula_audit(
                [
                    "∂C_x/∂t = ∂C_y/∂t = 0",
                    "∂C_z/∂t ≠ 0",
                ],
                [expected],
            )["exact_count"],
            1,
        )
        self.assertEqual(
            _formula_audit(
                ["∂C_x/∂t = ∂C_y/∂t = 0"],
                [expected],
            )["exact_count"],
            0,
        )

    def test_p34_oracle_requires_visible_derivation_not_inferred_shortcut(
        self,
    ):
        expected = (
            "L⃗→μ⃗",
            (
                "μ⃗=-i·πr^2·n̂=(-v/(2πr))·e·πr^2·n̂="
                "(-e/(2m_e))·m_evr·n̂=(-e/(2m_e))L⃗"
            ),
            "μ_z=(-e/(2m_e))L_z=(-e/(2m_e))·m_lℏ",
        )
        observed = (
            "L⃗ → μ⃗",
            (
                "μ⃗ = -i · πr^2 · n̂ = (-v)/(2πr) · e · "
                "πr^2 · n̂ = (-e)/(2m_e) · m_e vr · n̂ = "
                "(-e)/(2m_e) L⃗"
            ),
            (
                "μ_z = (-e)/(2m_e) L_z = "
                "(-e)/(2m_e) · m_l ℏ"
            ),
        )

        self.assertEqual(EXPECTED_FORMULAS[34], expected)
        self.assertEqual(
            _formula_audit(observed, expected)["exact_count"],
            3,
        )
        self.assertEqual(
            _formula_audit(["L⃗=m_evrn̂"], expected)["exact_count"],
            0,
        )

    def test_p42_oracle_requires_complete_spin_magnitude_derivation(self):
        expected = (
            "S=√(s(s+1))ℏ=√(1/2(1/2+1))ℏ=(√3/2)ℏ"
        )

        self.assertIn(expected, EXPECTED_FORMULAS[42])
        self.assertEqual(
            _formula_audit([expected], [expected])["exact_count"],
            1,
        )
        self.assertEqual(
            _formula_audit(
                ["S=√(s(s+1))ℏ=(√3/2)ℏ"],
                [expected],
            )["exact_count"],
            0,
        )

    def test_16_page_canary_oracle_is_complete(self):
        self.assertEqual(len(CANARY_PAGES), 16)
        self.assertEqual(
            sum(
                len(EXPECTED_FORMULAS[page])
                for page in CANARY_PAGES
            ),
            58,
        )
        self.assertEqual(
            sum(len(REQUIRED_TEXT[page]) for page in CANARY_PAGES),
            32,
        )

    def test_canary_does_not_count_fallback_as_clean_acceptance(self):
        self.assertEqual(
            _benchmark_page_status(
                available=True,
                issues=["node_selector_deterministic_fallback"],
            ),
            "degraded",
        )
        self.assertEqual(
            _benchmark_page_status(available=True, issues=[]),
            "accepted",
        )
        self.assertEqual(
            _benchmark_page_status(
                available=False,
                issues=["ModelProviderError"],
            ),
            "failed",
        )

    def test_layout_formula_normalizes_unbraced_latex_power(self):
        extraction = parse_dots_layout(
            {
                "page": 84,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 200],
                        "category": "Formula",
                        "text": "ν≈5×10^14 Hz",
                        "latex": r"\nu\approx5\times10^14\,Hz",
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=84,
            image_width=1920,
            image_height=1440,
        )

        self.assertIn(
            r"10^{14}",
            extraction.blocks[0].formulas[0].latex,
        )
        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=84,
                min_confidence=0.85,
            ),
            (),
        )

    def test_fraction_followed_by_trig_multiplier_is_not_orphaned(self):
        extraction = parse_dots_layout(
            {
                "page": 21,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 220],
                        "category": "Formula",
                        "text": "Y_10(θ,φ)=√(3/(4π))cosθ",
                        "latex": (
                            r"Y_{10}(\theta,\varphi)="
                            r"\sqrt{\frac{3}{4\pi}}\cos\theta"
                        ),
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=21,
            image_width=1920,
            image_height=1440,
        )

        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=21,
                min_confidence=0.85,
            ),
            (),
        )

    def test_parser_supplements_enumerated_assignment_formulas(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 300],
                        "category": "Text",
                        "text": (
                            "q = 4，j = 0, 1\n"
                            "r = a^2"
                        ),
                        "formulas": [
                            {
                                "text": "r = a^2",
                                "latex": "r = a^2",
                            }
                        ],
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        self.assertEqual(
            [
                formula.text
                for formula in extraction.blocks[0].formulas
            ],
            ["r = a^2", "q = 4，j = 0, 1"],
        )
        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
            (),
        )

    def test_parser_supplements_embedded_simple_assignment_formula(self):
        extraction = parse_dots_layout(
            {
                "page": 31,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 300],
                        "category": "Text",
                        "text": (
                            "电子出现在 r = r_1 的单位厚度球壳层内的"
                            "概率最大。"
                        ),
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=31,
            image_width=1000,
            image_height=1000,
        )

        self.assertEqual(
            [
                formula.model_dump()
                for formula in extraction.blocks[0].formulas
            ],
            [{"text": "r = r_1", "latex": "r = r_{1}"}],
        )
        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=31,
                min_confidence=0.85,
            ),
            (),
        )

    def test_parser_supplements_embedded_numeric_fraction_assignment(self):
        extraction = parse_dots_layout(
            {
                "page": 44,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 300],
                        "category": "Figure",
                        "text": "j = 3/2  √15ħ/2  J⃗  S⃗  √3ħ/2",
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=44,
            image_width=1000,
            image_height=1000,
        )

        self.assertEqual(
            [
                formula.model_dump()
                for formula in extraction.blocks[0].formulas
            ],
            [{"text": "j = 3/2", "latex": "j = 3/2"}],
        )
        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=44,
                min_confidence=0.85,
            ),
            (),
        )

    def test_parser_does_not_supplement_partial_symbolic_fraction(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 300],
                        "category": "Text",
                        "text": "波长满足 λ = c / ν",
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        self.assertEqual(extraction.blocks[0].formulas, [])
        self.assertIn(
            "block_0:formula_contract_missing",
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
        )

    def test_parser_normalizes_supported_latex_canonical_formula_text(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 300],
                        "category": "Formula",
                        "text": r"\Psi(\xi) = A e^{b\xi}",
                        "latex": r"\Psi(\xi) = A e^{b\xi}",
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        self.assertEqual(
            extraction.blocks[0].formulas[0].text,
            "Ψ(ξ) = A e^{bξ}",
        )
        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
            (),
        )

    def test_gate_rejects_unknown_latex_in_canonical_formula_text(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 300],
                        "category": "Formula",
                        "text": r"\mystery{\xi} = 1",
                        "latex": r"\mystery{\xi} = 1",
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        self.assertIn(
            "block_0:formula_0:canonical_text_contains_latex",
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
        )

    def test_gate_rejects_unicode_latex_symbol_mismatch(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 300],
                        "category": "Formula",
                        "text": "Δv = 2.5 Hz",
                        "latex": r"\Delta \nu = 2.5\,\mathrm{Hz}",
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        self.assertIn(
            "block_0:formula_0:formula_text_latex_symbol_mismatch",
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
        )

    def test_parser_repairs_visible_latex_formula_decorations(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 220],
                        "category": "Formula",
                        "text": "L̂_z Φ = L_z Φ",
                        "formulas": [
                            {
                                "text": "L_z Φ = L_z Φ",
                                "latex": r"\hat{L}_z \Phi = L_z \Phi",
                            }
                        ],
                        "confidence": 0.95,
                    },
                    {
                        "bbox": [100, 260, 900, 380],
                        "category": "Formula",
                        "text": "p⃗ = mv⃗",
                        "formulas": [
                            {
                                "text": "p = mv",
                                "latex": r"\vec{p} = m\vec{v}",
                            }
                        ],
                        "confidence": 0.95,
                    },
                    {
                        "bbox": [100, 420, 900, 540],
                        "category": "Formula",
                        "text": "x̅ = 1",
                        "formulas": [
                            {
                                "text": "x = 1",
                                "latex": r"\bar{x} = 1",
                            }
                        ],
                        "confidence": 0.95,
                    },
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        self.assertEqual(
            [
                formula.text
                for block in extraction.blocks
                for formula in block.formulas
            ],
            ["L̂_z Φ= L_z Φ", "p⃗ = mv⃗", "x̅ = 1"],
        )
        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
            (),
        )

    def test_gate_rejects_latex_decoration_without_visible_support(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 220],
                        "category": "Formula",
                        "text": "L_z Φ = L_z Φ",
                        "formulas": [
                            {
                                "text": "L_z Φ = L_z Φ",
                                "latex": r"\hat{L}_z \Phi = L_z \Phi",
                            }
                        ],
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        self.assertIn(
            "block_0:formula_0:formula_text_latex_decoration_mismatch",
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
        )

    def test_gate_counts_repeated_decorations_without_false_mismatch(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 220],
                        "category": "Formula",
                        "text": "L̂^2 = L̂_x^2 + L̂_y^2 + L̂_z^2",
                        "formulas": [
                            {
                                "text": "L̂^2 = L̂_x^2 + L̂_y^2 + L̂_z^2",
                                "latex": (
                                    r"\hat{L}^2 = \hat{L}_x^2 + "
                                    r"\hat{L}_y^2 + \hat{L}_z^2"
                                ),
                            }
                        ],
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
            (),
        )

    def test_gate_accepts_unicode_macron_as_latex_bar_equivalent(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 220],
                        "category": "Formula",
                        "text": "τ = t̄ = 1/A_21",
                        "formulas": [
                            {
                                "text": "τ = t̄ = 1/A_21",
                                "latex": (
                                    r"\tau = \bar{t} = "
                                    r"\frac{1}{A_{21}}"
                                ),
                            }
                        ],
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
            (),
        )

    def test_same_block_relation_continuation_merges_text_and_latex(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 300],
                        "category": "Formula",
                        "text": "p⃗ = mv⃗ = qE n̂",
                        "formulas": [
                            {
                                "text": "p⃗ = mv⃗",
                                "latex": r"\vec{p} = m\vec{v}",
                            },
                            {
                                "text": "= qE n̂",
                                "latex": r"= qE \hat{n}",
                            },
                        ],
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        formula = extraction.blocks[0].formulas[0]
        self.assertEqual(formula.text, "p⃗ = mv⃗ = qE n̂")
        self.assertEqual(
            formula.latex,
            r"\vec{p} = m\vec{v} = qE \hat{n}",
        )
        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
            (),
        )

    def test_parser_repairs_missing_fraction_structure_from_latex(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 300],
                        "category": "Formula",
                        "text": "推导得 dF(x)G = iℏ q dx",
                        "formulas": [
                            {
                                "text": "dF(x)G = iℏ q dx",
                                "latex": (
                                    r"\frac{dF(x)}{G} = "
                                    r"\frac{i}{\hbar} q\,dx"
                                ),
                            }
                        ],
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        block = extraction.blocks[0]
        self.assertEqual(block.text, "推导得 dF(x)/G = i/ℏ q dx")
        self.assertEqual(
            block.formulas[0].text,
            "dF(x)/G = i/ℏ q dx",
        )
        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
            (),
        )

    def test_parser_repairs_missing_dfrac_structure_from_latex(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 300],
                        "category": "Formula",
                        "text": "测量关系 R = xy ·z",
                        "formulas": [
                            {
                                "text": "R = xy ·z",
                                "latex": r"R = \dfrac{x}{y \cdot z}",
                            }
                        ],
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        formula = extraction.blocks[0].formulas[0]
        self.assertEqual(formula.text, "R = x/y ·z")
        self.assertEqual(
            _formula_audit([formula.text], ["R=x/(y·z)"])["exact_count"],
            1,
        )
        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
            (),
        )

    def test_gate_rejects_disagreeing_fraction_structure(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 300],
                        "category": "Formula",
                        "text": "a = b/c",
                        "formulas": [
                            {
                                "text": "a = b/c",
                                "latex": r"a = \frac{b}{d}",
                            }
                        ],
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        self.assertIn(
            "block_0:formula_0:formula_text_latex_structure_mismatch",
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
        )

    def test_fraction_structure_accepts_cot_ctg_alias(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 300],
                        "category": "Formula",
                        "text": "y = 1/x + ctgθ",
                        "formulas": [
                            {
                                "text": "y = 1/x + ctgθ",
                                "latex": (
                                    r"y = \frac{1}{x} + \cot\theta"
                                ),
                            }
                        ],
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        self.assertEqual(
            extraction.blocks[0].formulas[0].text,
            "y = 1/x + ctgθ",
        )
        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
            (),
        )

    def test_fraction_structure_accepts_unicode_prime_alias(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 300],
                        "category": "Formula",
                        "text": "ν̃ = R(1/n^2 - 1/n′^2)",
                        "formulas": [
                            {
                                "text": "ν̃ = R(1/n^2 - 1/n′^2)",
                                "latex": (
                                    r"\tilde{\nu} = R\left("
                                    r"\frac{1}{n^2} - "
                                    r"\frac{1}{n'^2}\right)"
                                ),
                            }
                        ],
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
            (),
        )

    def test_fraction_structure_accepts_nonformula_context_affixes(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 300],
                        "category": "Formula",
                        "text": "波数 ν̃ = R(1/n^2 - 1/n′^2) ——经验方程",
                        "formulas": [
                            {
                                "text": (
                                    "波数 ν̃ = R(1/n^2 - 1/n′^2) "
                                    "——经验方程"
                                ),
                                "latex": (
                                    r"\tilde{\nu} = R\left("
                                    r"\frac{1}{n^2} - "
                                    r"\frac{1}{n'^2}\right)"
                                ),
                            }
                        ],
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
            (),
        )

    def test_fraction_structure_accepts_equivalent_script_order(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 300],
                        "category": "Formula",
                        "text": "L̂^2_x = 1/sinθ",
                        "formulas": [
                            {
                                "text": "L̂^2_x = 1/sinθ",
                                "latex": (
                                    r"\hat{L}_x^2 = "
                                    r"\frac{1}{\sin\theta}"
                                ),
                            }
                        ],
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
            (),
        )

    def test_parser_repairs_numeric_hz_unit_subscript(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 300],
                        "category": "Formula",
                        "text": "f = 2×10^7 H_z",
                        "latex": (
                            r"f = 2\times10^7\,"
                            r"\mathrm{H_{z}}"
                        ),
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        self.assertEqual(
            extraction.blocks[0].formulas[0].text,
            "f = 2×10^7 Hz",
        )
        self.assertEqual(
            extraction.blocks[0].formulas[0].latex,
            r"f = 2\times10^{7}\,\mathrm{Hz}",
        )
        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
            (),
        )

    def test_parser_uses_page_frequency_symbol_to_repair_delta_v(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 200],
                        "category": "Text",
                        "text": "横轴频率记作 ν",
                        "confidence": 0.95,
                    },
                    {
                        "bbox": [100, 240, 900, 360],
                        "category": "Formula",
                        "text": "Δv = 2.5×10^4 Hz",
                        "latex": r"\Delta v = 2.5\times10^4\,\mathrm{Hz}",
                        "confidence": 0.95,
                    },
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        self.assertEqual(
            extraction.blocks[1].formulas[0].text,
            "Δν = 2.5×10^4 Hz",
        )
        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
            (),
        )

    def test_parser_supplements_scientific_value_formula_contracts(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 220],
                        "category": "Text",
                        "text": "峰值压力可达 > 10^5 Pa",
                        "confidence": 0.95,
                    },
                    {
                        "bbox": [100, 260, 900, 380],
                        "category": "Text",
                        "text": "样品温度达到10^7 K后发生变化",
                        "confidence": 0.95,
                    },
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        self.assertEqual(
            extraction.blocks[0].formulas[0].text,
            "峰值压力可达 > 10^5 Pa",
        )
        self.assertEqual(
            extraction.blocks[1].formulas[0].text,
            "10^7 K",
        )
        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
            (),
        )

    def test_adjacent_relation_only_formula_line_is_merged(self):
        extraction = parse_dots_layout(
            {
                "page": 42,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 800, 180],
                        "category": "Formula",
                        "text": "S=√(s(s+1))ℏ",
                        "latex": r"S=\sqrt{s(s+1)}\hbar",
                        "confidence": 0.95,
                    },
                    {
                        "bbox": [120, 185, 820, 250],
                        "category": "Formula",
                        "text": "=√3/2ℏ",
                        "latex": r"=\frac{\sqrt{3}}{2}\hbar",
                        "confidence": 0.94,
                    },
                ],
            },
            expected_page=42,
            image_width=1920,
            image_height=1440,
        )

        self.assertEqual(len(extraction.blocks), 1)
        self.assertEqual(
            extraction.blocks[0].formulas[0].text,
            "S=√(s(s+1))ℏ =√3/2ℏ",
        )
        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=42,
                min_confidence=0.85,
            ),
            (),
        )

    def test_formula_label_is_merged_with_its_adjacent_formula(self):
        extraction = parse_dots_layout(
            {
                "page": 87,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 180],
                        "category": "Text",
                        "text": "相邻两种频率的间隔为",
                        "confidence": 0.95,
                    },
                    {
                        "bbox": [150, 185, 850, 260],
                        "category": "Formula",
                        "text": "Δν_k=c/(2nL)",
                        "latex": r"\Delta\nu_k=\frac{c}{2nL}",
                        "confidence": 0.95,
                    },
                ],
            },
            expected_page=87,
            image_width=1920,
            image_height=1440,
        )

        self.assertEqual(len(extraction.blocks), 1)
        self.assertEqual(
            extraction.blocks[0].text,
            "相邻两种频率的间隔为\nΔν_k=c/(2nL)",
        )

    def test_side_by_side_formula_label_is_merged(self):
        extraction = parse_dots_layout(
            {
                "page": 87,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [50, 100, 450, 200],
                        "category": "Text",
                        "text": "相邻两种频率的间隔为",
                        "confidence": 0.95,
                    },
                    {
                        "bbox": [550, 100, 900, 220],
                        "category": "Formula",
                        "text": "Δν_k=c/(2nL)",
                        "latex": r"\Delta\nu_k=\frac{c}{2nL}",
                        "confidence": 0.95,
                    },
                ],
            },
            expected_page=87,
            image_width=1920,
            image_height=1440,
        )

        self.assertEqual(len(extraction.blocks), 1)
        self.assertIn(
            "相邻两种频率的间隔为",
            extraction.blocks[0].text,
        )

    def test_colon_terminated_formula_label_is_merged(self):
        extraction = parse_dots_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 450, 180],
                        "category": "Text",
                        "text": "变量替换后的守恒关系：",
                        "confidence": 0.96,
                    },
                    {
                        "bbox": [120, 190, 700, 320],
                        "category": "Formula",
                        "text": "x = y + 1",
                        "latex": "x = y + 1",
                        "confidence": 0.95,
                    },
                ],
            },
            expected_page=1,
            image_width=1000,
            image_height=1000,
        )

        self.assertEqual(len(extraction.blocks), 1)
        self.assertEqual(
            extraction.blocks[0].text,
            "变量替换后的守恒关系：\nx = y + 1",
        )

    def test_formula_with_inline_layout_label_uses_complete_block_text(self):
        extraction = parse_dots_layout(
            {
                "page": 17,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 300],
                        "category": "Formula",
                        "text": (
                            "L^2=L_x^2+L_y^2+L_z^2（直角坐标）"
                            "=-ℏ^2[...]（球极）"
                        ),
                        "formula_text": (
                            "L^2=L_x^2+L_y^2+L_z^2=-ℏ^2[...]"
                        ),
                        "latex": (
                            r"L^2=L_x^2+L_y^2+L_z^2=-\hbar^2[\cdots]"
                        ),
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=17,
            image_width=1920,
            image_height=1440,
        )

        block = extraction.blocks[0]
        self.assertEqual(block.formulas[0].text, block.text)
        self.assertEqual(
            page_layout_issues(
                extraction,
                expected_page=17,
                min_confidence=0.85,
            ),
            (),
        )

    def test_layout_gate_rejects_formula_missing_from_block_text(self):
        extraction = parse_dots_layout(
            {
                "page": 17,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [70, 178, 610, 630],
                        "category": "Formula",
                        "text": (
                            "L̂_x = iℏ(sinφ ∂/∂θ + "
                            "ctgθ cosφ /∂φ); "
                            "L̂_y = iℏ(-cosφ ∂/∂θ + "
                            "ctgθ sinφ ∂/∂φ); "
                            "L̂_z = -iℏ ∂/∂φ"
                        ),
                        "formulas": [
                            {
                                "text": (
                                    "L̂_x = iℏ(sinφ ∂/∂θ + "
                                    "ctgθ cosφ ∂/∂φ)"
                                ),
                                "latex": r"\hat L_x=i\hbar(\cdots)",
                            },
                            {
                                "text": (
                                    "L̂_y = iℏ(-cosφ ∂/∂θ + "
                                    "ctgθ sinφ ∂/∂φ)"
                                ),
                                "latex": r"\hat L_y=i\hbar(\cdots)",
                            },
                            {
                                "text": "L̂_z = -iℏ ∂/∂φ",
                                "latex": r"\hat L_z=-i\hbar\partial/\partial\varphi",
                            },
                        ],
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=17,
            image_width=1920,
            image_height=1440,
        )

        self.assertIn(
            "block_0:formula_0:formula_not_in_block_text",
            page_layout_issues(
                extraction,
                expected_page=17,
                min_confidence=0.85,
            ),
        )

    def test_contextualized_formula_drops_redundant_prefix_formula(self):
        extraction = parse_dots_layout(
            {
                "page": 17,
                "complete": True,
                "confidence": 0.95,
                "coordinate_space": "normalized_1000",
                "blocks": [
                    {
                        "bbox": [100, 100, 900, 300],
                        "category": "Formula",
                        "text": (
                            "L^2=L_x^2+L_y^2+L_z^2（直角坐标）"
                            "=-ℏ^2[...]（球极）"
                        ),
                        "formulas": [
                            {
                                "text": "L^2=L_x^2+L_y^2+L_z^2",
                                "latex": "L^2=L_x^2+L_y^2+L_z^2",
                            },
                            {
                                "text": "=-ℏ^2[...]",
                                "latex": r"=-\hbar^2[\cdots]",
                            },
                        ],
                        "confidence": 0.95,
                    }
                ],
            },
            expected_page=17,
            image_width=1920,
            image_height=1440,
        )

        self.assertEqual(len(extraction.blocks[0].formulas), 1)
        self.assertEqual(
            extraction.blocks[0].formulas[0].text,
            extraction.blocks[0].text,
        )

    def test_chandra_skips_empty_picture_and_accepts_list_bbox(self):
        extraction = parse_chandra_layout(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "html": (
                    '<div data-label="Picture" '
                    'data-bbox="[0, 0, 500, 500]"></div>'
                    '<div data-label="Text" '
                    'data-bbox="[100, 600, 900, 700]">正文</div>'
                ),
            },
            expected_page=1,
        )

        self.assertEqual(len(extraction.blocks), 1)
        self.assertEqual(extraction.blocks[0].text, "正文")
        self.assertEqual(
            extraction.blocks[0].bbox,
            [0.1, 0.6, 0.8, 0.1],
        )


class PdfLayoutNodeTDDTests(unittest.IsolatedAsyncioTestCase):
    async def test_layout_quality_retry_gets_extended_timeout(self):
        first_payload = {
            "page": 1,
            "complete": True,
            "confidence": 0.7,
            "coordinate_space": "normalized_1000",
            "blocks": [
                {
                    "bbox": [100, 100, 900, 200],
                    "category": "Text",
                    "text": "低置信度初稿",
                    "confidence": 0.7,
                }
            ],
        }
        second_payload = {
            "page": 1,
            "complete": True,
            "confidence": 0.95,
            "coordinate_space": "normalized_1000",
            "blocks": [
                {
                    "bbox": [100, 100, 900, 200],
                    "category": "Text",
                    "text": "修复后的原子事实",
                    "confidence": 0.95,
                }
            ],
        }
        client = _FakePageLayoutClient([first_payload, second_payload])
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "page.png"
            Image.new("RGB", (1000, 1000), color="white").save(image_path)

            result = await extract_page_layout_knowledge(
                image_path=image_path,
                page=1,
                runtime=_runtime(client),
                profile="dots",
                min_confidence=0.85,
                max_layout_attempts=2,
                max_node_attempts=1,
                extract_nodes=False,
            )

        self.assertIsNotNone(result.layout)
        self.assertEqual(result.layout_attempts, 2)
        self.assertEqual(result.issues, [])
        self.assertEqual(
            [call["timeout_seconds"] for call in client.calls],
            [120.0, 180.0],
        )

    def _layout(self) -> PageLayoutExtraction:
        return parse_chandra_layout(
            {
                "page": 84,
                "complete": True,
                "confidence": 0.97,
                "html": (
                    '<div data-label="Section-header" '
                    'data-bbox="100 50 900 120" data-confidence="0.98">'
                    "<h2>激光的纵模</h2></div>"
                    '<div data-label="Formula" '
                    'data-bbox="100 200 900 400" data-confidence="0.96">'
                    '<math data-canonical="Δν/ν≈10^-6">'
                    r"\frac{\Delta\nu}{\nu}\approx10^{-6}"
                    "</math></div>"
                ),
            },
            expected_page=84,
        )

    def test_materialization_inherits_evidence_formula_and_bbox(self):
        layout = self._layout()
        selection = LayoutNodeSelection(
            page=84,
            complete=True,
            confidence=0.95,
            heading_block_id="p0084:b000",
            has_knowledge=True,
            nodes=[
                {
                    "temp_id": "relative-linewidth",
                    "name": "Δν/ν≈10^-6",
                    "type": "formula",
                    "role": "formula",
                    "block_id": "p0084:b001",
                    "formula_index": 0,
                    "confidence": 0.94,
                }
            ],
        )

        extraction = materialize_layout_selection(layout, selection)
        node = extraction.nodes[0]
        self.assertEqual(extraction.heading, "激光的纵模")
        self.assertEqual(node.name, "Δν/ν≈10^-6")
        self.assertEqual(node.definition, "Δν/ν≈10^-6")
        self.assertEqual(node.evidence_text, "Δν/ν≈10^-6")
        self.assertEqual(node.formula_text, "Δν/ν≈10^-6")
        self.assertEqual(
            node.formula_latex,
            r"\frac{\Delta\nu}{\nu}\approx10^{-6}",
        )
        self.assertEqual(node.bbox, [0.1, 0.2, 0.8, 0.2])
        self.assertEqual(node.confidence, 0.96)
        self.assertEqual(extraction.confidence, 0.97)

    def test_materialization_drops_bad_nodes_but_keeps_valid_sibling(self):
        layout = PageLayoutExtraction.model_validate(
            {
                "profile": "dots",
                "page": 61,
                "complete": True,
                "confidence": 0.95,
                "blocks": [
                    {
                        "block_id": "p0061:b000",
                        "category": "paragraph",
                        "text": "泡利不相容原理",
                        "bbox": [0.1, 0.1, 0.4, 0.08],
                        "confidence": 0.95,
                    },
                    {
                        "block_id": "p0061:b001",
                        "category": "paragraph",
                        "text": "——泡利",
                        "bbox": [0.1, 0.25, 0.2, 0.08],
                        "confidence": 0.95,
                    },
                    {
                        "block_id": "p0061:b002",
                        "category": "paragraph",
                        "text": "后来发现在其他波段还存在谱线。",
                        "bbox": [0.1, 0.4, 0.6, 0.08],
                        "confidence": 0.95,
                    },
                ],
            }
        )
        selection = LayoutNodeSelection.model_validate(
            {
                "page": 61,
                "complete": True,
                "confidence": 0.95,
                "has_knowledge": True,
                "nodes": [
                    {
                        "temp_id": "pauli-principle",
                        "name": "泡利不相容原理",
                        "type": "principle",
                        "role": "principle",
                        "block_id": "p0061:b000",
                        "confidence": 0.95,
                    },
                    {
                        "temp_id": "pauli-caption",
                        "name": "——泡利",
                        "type": "concept",
                        "role": "other",
                        "block_id": "p0061:b001",
                        "confidence": 0.95,
                    },
                    {
                        "temp_id": "sentence-fragment",
                        "name": "后来发现在其他波段还存在谱线。",
                        "type": "result",
                        "role": "other",
                        "block_id": "p0061:b002",
                        "confidence": 0.95,
                    },
                ],
            }
        )

        extraction = materialize_layout_selection(layout, selection)

        self.assertEqual(
            [node.temp_id for node in extraction.nodes],
            ["pauli-principle"],
        )
        self.assertEqual(
            [node.name for node in extraction.nodes],
            ["泡利不相容原理"],
        )

    async def test_second_stage_receives_blocks_without_page_image(self):
        layout = self._layout()
        client = _FakeLayoutNodeClient(
            {
                "page": 84,
                "complete": True,
                "confidence": 0.95,
                "heading_block_id": "p0084:b000",
                "has_knowledge": True,
                "no_knowledge_reason": "",
                "nodes": [
                    {
                        "temp_id": "relative-linewidth",
                        "name": "Δν/ν≈10^-6",
                        "type": "formula",
                        "role": "formula",
                        "block_id": "p0084:b001",
                        "formula_index": 0,
                        "confidence": 0.94,
                    }
                ],
            }
        )

        extraction, attempts, issues = await extract_layout_nodes(
            layout=layout,
            runtime=_runtime(client),
            min_confidence=0.85,
            max_attempts=1,
        )

        self.assertIsNotNone(extraction)
        self.assertEqual(attempts, 1)
        self.assertEqual(issues, [])
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertNotIn("image_data_url", call)
        self.assertIn('"block_id":"p0084:b001"', call["user_prompt"])
        self.assertIn('"formula_count":1', call["user_prompt"])
        self.assertNotIn('"latex"', call["user_prompt"])
        self.assertNotIn('"bbox"', call["user_prompt"])
        self.assertEqual(call["max_tokens"], 2500)
        self.assertEqual(call["max_completion_tokens"], 4036)
        self.assertEqual(
            call["thinking_budget"],
            PAGE_LAYOUT_NODE_REASONING_TOKEN_RESERVE,
        )
        self.assertNotIn("reasoning_effort", call)
        self.assertEqual(call["max_attempts"], 1)
        self.assertEqual(call["timeout_seconds"], 120.0)

    async def test_invalid_label_retries_with_publishable_name_feedback(self):
        layout = PageLayoutExtraction.model_validate(
            {
                "profile": "dots",
                "page": 4,
                "complete": True,
                "confidence": 0.95,
                "blocks": [
                    {
                        "block_id": "p0004:b000",
                        "category": "paragraph",
                        "text": "其他波段的谱线随后也被发现。",
                        "bbox": [0.1, 0.1, 0.7, 0.1],
                        "confidence": 0.95,
                    }
                ],
            }
        )
        common = {
            "page": 4,
            "complete": True,
            "confidence": 0.95,
            "has_knowledge": True,
            "no_knowledge_reason": "",
        }
        client = _FakeLayoutNodeClient(
            [
                {
                    **common,
                    "nodes": [
                        {
                            "temp_id": "bad-label",
                            "name": "其他波段的谱线随后也被发现。",
                            "type": "result",
                            "role": "other",
                            "block_id": "p0004:b000",
                            "confidence": 0.95,
                        }
                    ],
                },
                {
                    **common,
                    "nodes": [
                        {
                            "temp_id": "fixed-label",
                            "name": "其他波段的谱线",
                            "type": "result",
                            "role": "other",
                            "block_id": "p0004:b000",
                            "confidence": 0.95,
                        }
                    ],
                },
            ]
        )

        extraction, attempts, issues = await extract_layout_nodes(
            layout=layout,
            runtime=_runtime(client),
            min_confidence=0.85,
            max_attempts=2,
        )

        self.assertIsNotNone(extraction)
        self.assertEqual(attempts, 2)
        self.assertEqual(issues, [])
        self.assertEqual(extraction.nodes[0].name, "其他波段的谱线")
        retry_prompt = client.calls[1]["user_prompt"]
        self.assertIn("label_sentence_fragment", retry_prompt)
        self.assertIn("2..48", retry_prompt)
        self.assertIn("零基础学生", retry_prompt)

    def test_invalid_supplemental_fragment_is_not_materialized(self):
        layout = PageLayoutExtraction.model_validate(
            {
                "profile": "dots",
                "page": 4,
                "complete": True,
                "confidence": 0.95,
                "blocks": [
                    {
                        "block_id": "p0004:b000",
                        "category": "paragraph",
                        "text": "里德伯方程",
                        "bbox": [0.1, 0.1, 0.3, 0.08],
                        "confidence": 0.95,
                    },
                    {
                        "block_id": "p0004:b001",
                        "category": "paragraph",
                        "text": "后来发现在其他波段还存在谱线。",
                        "bbox": [0.1, 0.3, 0.7, 0.1],
                        "confidence": 0.95,
                    },
                ],
            }
        )
        selection = LayoutNodeSelection.model_validate(
            {
                "page": 4,
                "complete": True,
                "confidence": 0.95,
                "has_knowledge": True,
                "nodes": [
                    {
                        "temp_id": "rydberg",
                        "name": "里德伯方程",
                        "type": "concept",
                        "role": "other",
                        "block_id": "p0004:b000",
                        "confidence": 0.95,
                    }
                ],
            }
        )

        extraction = materialize_layout_selection(layout, selection)

        self.assertEqual(
            [node.name for node in extraction.nodes],
            ["里德伯方程"],
        )

    def test_materialization_drops_latest_task_reaction_letter_fragments(self):
        noisy_fragments = [
            "OH O Na₂Cr₂O₇ H₂SO₄, H₂O R R R R",
            "O H₂SO₄, H₂O HgSO₄ R R CH₃",
            "O O Cl R AlCl₃ R",
        ]
        layout = PageLayoutExtraction.model_validate(
            {
                "profile": "dots",
                "page": 7,
                "complete": True,
                "confidence": 0.95,
                "blocks": [
                    {
                        "block_id": "p0007:valid",
                        "category": "paragraph",
                        "text": "二级醇氧化生成酮",
                        "bbox": [0.1, 0.1, 0.7, 0.08],
                        "confidence": 0.95,
                    },
                    *[
                        {
                            "block_id": f"p0007:noisy-{index}",
                            "category": "paragraph",
                            "text": fragment,
                            "bbox": [0.1, 0.2 + index * 0.1, 0.7, 0.08],
                            "confidence": 0.95,
                        }
                        for index, fragment in enumerate(noisy_fragments)
                    ],
                ],
            }
        )
        selection = LayoutNodeSelection.model_validate(
            {
                "page": 7,
                "complete": True,
                "confidence": 0.95,
                "has_knowledge": True,
                "nodes": [
                    {
                        "temp_id": "valid",
                        "name": "二级醇氧化生成酮",
                        "type": "principle",
                        "role": "principle",
                        "block_id": "p0007:valid",
                        "confidence": 0.95,
                        "terminal_gold_gate": TERMINAL_GOLD_GATE,
                    },
                    *[
                        {
                            "temp_id": f"noisy-{index}",
                            "name": fragment,
                            "type": "concept",
                            "role": "other",
                            "block_id": f"p0007:noisy-{index}",
                            "confidence": 0.95,
                            "terminal_gold_gate": TERMINAL_GOLD_GATE,
                        }
                        for index, fragment in enumerate(noisy_fragments)
                    ],
                ],
            }
        )

        extraction = materialize_layout_selection(layout, selection)

        self.assertEqual(
            [node.name for node in extraction.nodes],
            ["二级醇氧化生成酮"],
        )

    async def test_fallback_extracts_atomic_result_from_sentence_formula(self):
        formula_text = (
            "若把电子视为r =10^-16 m的小球，"
            "按 S ~ ℏ 估算出的电子表面速度 > c！"
        )
        layout = PageLayoutExtraction.model_validate(
            {
                "profile": "dots",
                "page": 40,
                "complete": True,
                "confidence": 0.95,
                "blocks": [
                    {
                        "block_id": "p0040:b003",
                        "category": "paragraph",
                        "text": formula_text,
                        "formulas": [
                            {
                                "text": formula_text,
                                "latex": (
                                    r"\text{若把电子视为}r =10^{-16} m"
                                    r"\text{的小球}，\text{按} S \sim \hbar "
                                    r"\text{估算出的电子表面速度} > c"
                                ),
                            }
                        ],
                        "bbox": [0.038, 0.57, 0.892, 0.17],
                        "confidence": 0.93,
                    }
                ],
            }
        )
        client = _FakeLayoutNodeClient(
            {
                "page": 40,
                "complete": True,
                "confidence": 0.95,
                "has_knowledge": True,
                "nodes": [
                    {
                        "temp_id": "malformed",
                        "name": "页面中不存在的节点",
                    }
                ],
            }
        )

        extraction, attempts, issues = await extract_layout_nodes(
            layout=layout,
            runtime=_runtime(client),
            min_confidence=0.85,
            max_attempts=1,
        )

        self.assertIsNotNone(extraction)
        self.assertEqual(attempts, 1)
        self.assertIn("node_selector_deterministic_fallback", issues)
        self.assertEqual(
            [node.name for node in extraction.nodes],
            ["电子表面速度 > c"],
        )
        self.assertEqual(extraction.nodes[0].formula_text, formula_text)
        self.assertIn("10^-16", extraction.nodes[0].formula_text)

    def test_unselected_sentence_formula_is_supplemented_atomically(self):
        formula_text = (
            "若把电子视为r =10^-16 m的小球，"
            "按 S ~ ℏ 估算出的电子表面速度 > c！"
        )
        layout = PageLayoutExtraction.model_validate(
            {
                "profile": "dots",
                "page": 40,
                "complete": True,
                "confidence": 0.95,
                "blocks": [
                    {
                        "block_id": "p0040:b000",
                        "category": "paragraph",
                        "text": "电子自旋有两种取向",
                        "bbox": [0.04, 0.1, 0.5, 0.08],
                        "confidence": 0.95,
                    },
                    {
                        "block_id": "p0040:b003",
                        "category": "paragraph",
                        "text": formula_text,
                        "formulas": [
                            {
                                "text": formula_text,
                                "latex": (
                                    r"\text{若把电子视为}r =10^{-16} m"
                                    r"\text{的小球}，\text{按} S \sim \hbar "
                                    r"\text{估算出的电子表面速度} > c"
                                ),
                            }
                        ],
                        "bbox": [0.038, 0.57, 0.892, 0.17],
                        "confidence": 0.93,
                    },
                ],
            }
        )
        selection = LayoutNodeSelection.model_validate(
            {
                "page": 40,
                "complete": True,
                "confidence": 0.95,
                "has_knowledge": True,
                "nodes": [
                    {
                        "temp_id": "spin-orientation",
                        "name": "电子自旋有两种取向",
                        "block_id": "p0040:b000",
                        "confidence": 0.95,
                    }
                ],
            }
        )

        extraction = materialize_layout_selection(layout, selection)

        formula_nodes = [
            node for node in extraction.nodes if node.formula_text
        ]
        self.assertEqual(len(formula_nodes), 1)
        self.assertEqual(formula_nodes[0].name, "电子表面速度 > c")
        self.assertEqual(formula_nodes[0].formula_text, formula_text)
        self.assertIn("10^-16", formula_nodes[0].formula_text)

    async def test_fallback_extracts_subject_labels_from_statements(self):
        layout = PageLayoutExtraction.model_validate(
            {
                "profile": "dots",
                "page": 79,
                "complete": True,
                "confidence": 0.95,
                "blocks": [
                    {
                        "block_id": "p0079:b002",
                        "category": "list",
                        "text": (
                            "♦ He的2³S和2¹S这两个能级都是亚稳态，"
                            "很难回到基态；"
                        ),
                        "bbox": [0.05, 0.25, 0.82, 0.12],
                        "confidence": 0.96,
                    },
                    {
                        "block_id": "p0079:b004",
                        "category": "paragraph",
                        "text": "在He的这两个激发态上集聚了较多的原子。",
                        "bbox": [0.05, 0.72, 0.72, 0.08],
                        "confidence": 0.97,
                    },
                ],
            }
        )
        client = _FakeLayoutNodeClient(
            {
                "page": 79,
                "complete": True,
                "confidence": 0.95,
                "has_knowledge": True,
                "nodes": [
                    {
                        "temp_id": "malformed",
                        "name": "页面中不存在的节点",
                    }
                ],
            }
        )

        extraction, attempts, issues = await extract_layout_nodes(
            layout=layout,
            runtime=_runtime(client),
            min_confidence=0.85,
            max_attempts=1,
        )

        self.assertIsNotNone(extraction)
        self.assertEqual(attempts, 1)
        self.assertIn("node_selector_deterministic_fallback", issues)
        self.assertEqual(
            [node.name for node in extraction.nodes],
            [
                "He的2³S和2¹S这两个能级",
                "He的这两个激发态",
            ],
        )

    async def test_heading_only_layout_accepts_no_knowledge_selection(self):
        layout = PageLayoutExtraction.model_validate(
            {
                "profile": "dots",
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "blocks": [
                    {
                        "block_id": "p0001:b000",
                        "category": "heading",
                        "text": "第六章 激光",
                        "bbox": [0.1, 0.1, 0.4, 0.08],
                        "confidence": 0.95,
                    },
                    {
                        "block_id": "p0001:b001",
                        "category": "heading",
                        "text": "(Laser)",
                        "bbox": [0.1, 0.2, 0.2, 0.06],
                        "confidence": 0.95,
                    },
                ],
            }
        )
        client = _FakeLayoutNodeClient(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "heading_block_id": "p0001:b000",
                "has_knowledge": False,
                "no_knowledge_reason": "页面仅含章节标题",
                "nodes": [],
            }
        )

        extraction, attempts, issues = await extract_layout_nodes(
            layout=layout,
            runtime=_runtime(client),
            min_confidence=0.85,
            max_attempts=1,
        )

        self.assertIsNotNone(extraction)
        self.assertEqual(attempts, 1)
        self.assertEqual(issues, [])
        self.assertFalse(extraction.has_knowledge)
        self.assertEqual(extraction.heading, "第六章 激光")

    async def test_heading_atomic_claim_rejects_no_knowledge_selection(self):
        layout = PageLayoutExtraction.model_validate(
            {
                "profile": "dots",
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "blocks": [
                    {
                        "block_id": "p0001:b000",
                        "category": "heading",
                        "text": "能量最小原理 “电子优先占据最低能态”",
                        "bbox": [0.1, 0.1, 0.7, 0.08],
                        "confidence": 0.95,
                    }
                ],
            }
        )
        client = _FakeLayoutNodeClient(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "heading_block_id": "p0001:b000",
                "has_knowledge": False,
                "no_knowledge_reason": "页面仅含章节标题",
                "nodes": [],
            }
        )

        extraction, attempts, issues = await extract_layout_nodes(
            layout=layout,
            runtime=_runtime(client),
            min_confidence=0.85,
            max_attempts=1,
        )

        self.assertIsNotNone(extraction)
        self.assertEqual(attempts, 1)
        self.assertIn("node_selector_deterministic_fallback", issues)
        self.assertTrue(extraction.has_knowledge)
        self.assertEqual(
            extraction.nodes[0].name,
            "电子优先占据最低能态",
        )

    async def test_fallback_deduplicates_identical_layout_evidence(self):
        layout = PageLayoutExtraction.model_validate(
            {
                "profile": "dots",
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "blocks": [
                    {
                        "block_id": "p0001:b000",
                        "category": "paragraph",
                        "text": "亚稳态",
                        "bbox": [0.1, 0.1, 0.2, 0.05],
                        "confidence": 0.95,
                    },
                    {
                        "block_id": "p0001:b001",
                        "category": "paragraph",
                        "text": "亚稳态",
                        "bbox": [0.6, 0.1, 0.2, 0.05],
                        "confidence": 0.95,
                    },
                    {
                        "block_id": "p0001:b002",
                        "category": "paragraph",
                        "text": "碰撞转移",
                        "bbox": [0.3, 0.3, 0.2, 0.05],
                        "confidence": 0.95,
                    },
                ],
            }
        )
        client = _FakeLayoutNodeClient(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "has_knowledge": True,
                "nodes": [
                    {
                        "temp_id": "malformed",
                        "name": "页面中不存在的节点",
                    }
                ],
            }
        )

        extraction, attempts, issues = await extract_layout_nodes(
            layout=layout,
            runtime=_runtime(client),
            min_confidence=0.85,
            max_attempts=1,
        )

        self.assertIsNotNone(extraction)
        self.assertEqual(attempts, 1)
        self.assertIn("node_selector_deterministic_fallback", issues)
        self.assertEqual(
            [node.evidence_text for node in extraction.nodes],
            ["亚稳态", "碰撞转移"],
        )

    async def test_malformed_selector_uses_explicit_deterministic_fallback(
        self,
    ):
        layout = self._layout()
        client = _FakeLayoutNodeClient(
            {
                "page": 84,
                "complete": True,
                "confidence": 0.95,
                "heading_block_id": "p0084:b000",
                "has_knowledge": True,
                "nodes": [
                    {
                        "temp_id": "malformed",
                        "name": "页面中不存在的节点",
                    }
                ],
            }
        )

        extraction, attempts, issues = await extract_layout_nodes(
            layout=layout,
            runtime=_runtime(client),
            min_confidence=0.85,
            max_attempts=1,
        )

        self.assertIsNotNone(extraction)
        self.assertEqual(attempts, 1)
        self.assertIn("node_selector_deterministic_fallback", issues)
        self.assertEqual(
            extraction.nodes[0].formula_text,
            "Δν/ν≈10^-6",
        )

    async def test_selector_repairs_uniquely_inherited_block_fields(self):
        layout = self._layout()
        client = _FakeLayoutNodeClient(
            {
                "page": 84,
                "complete": True,
                "confidence": 0.95,
                "heading_block_id": "p0084:b000",
                "has_knowledge": True,
                "no_knowledge_reason": "",
                "nodes": [
                    {
                        "temp_id": "relative-linewidth",
                        "name": "Δν/ν≈10^-6",
                        "type": "formula",
                        "role": "formula",
                    }
                ],
            }
        )

        extraction, attempts, issues = await extract_layout_nodes(
            layout=layout,
            runtime=_runtime(client),
            min_confidence=0.85,
            max_attempts=1,
        )

        self.assertIsNotNone(extraction)
        self.assertEqual(attempts, 1)
        self.assertEqual(issues, [])
        self.assertEqual(extraction.nodes[0].formula_text, "Δν/ν≈10^-6")
        self.assertEqual(extraction.nodes[0].confidence, 0.96)

    async def test_selector_clears_formula_index_for_nonformula_block(self):
        layout = PageLayoutExtraction.model_validate(
            {
                "profile": "dots",
                "page": 4,
                "complete": True,
                "confidence": 0.95,
                "blocks": [
                    {
                        "block_id": "p0004:b000",
                        "category": "paragraph",
                        "text": "里德伯常量描述氢原子光谱线的波数关系。",
                        "bbox": [0.1, 0.1, 0.7, 0.1],
                        "confidence": 0.95,
                    }
                ],
            }
        )
        client = _FakeLayoutNodeClient(
            {
                "page": 4,
                "complete": True,
                "confidence": 0.95,
                "heading_block_id": "",
                "has_knowledge": True,
                "no_knowledge_reason": "",
                "nodes": [
                    {
                        "temp_id": "rydberg-constant",
                        "name": "里德伯常量",
                        "type": "definition",
                        "role": "definition",
                        "block_id": "p0004:b000",
                        "formula_index": 0,
                        "confidence": 0.95,
                    }
                ],
            }
        )

        extraction, attempts, issues = await extract_layout_nodes(
            layout=layout,
            runtime=_runtime(client),
            min_confidence=0.85,
            max_attempts=1,
        )

        self.assertIsNotNone(extraction)
        self.assertEqual(attempts, 1)
        self.assertEqual(issues, [])
        self.assertEqual(len(extraction.nodes), 1)
        self.assertEqual(extraction.nodes[0].temp_id, "rydberg-constant")
        self.assertEqual(extraction.nodes[0].name, "里德伯常量")
        self.assertEqual(extraction.nodes[0].formula_text, "")

    async def test_selector_clears_known_nonheading_reference(self):
        layout = self._layout()
        client = _FakeLayoutNodeClient(
            {
                "page": 84,
                "complete": True,
                "confidence": 0.95,
                "heading_block_id": "p0084:b001",
                "has_knowledge": True,
                "no_knowledge_reason": "",
                "nodes": [
                    {
                        "temp_id": "relative-linewidth",
                        "name": "Δν/ν≈10^-6",
                        "type": "formula",
                        "role": "formula",
                        "block_id": "p0084:b001",
                        "confidence": 0.94,
                    }
                ],
            }
        )

        extraction, attempts, issues = await extract_layout_nodes(
            layout=layout,
            runtime=_runtime(client),
            min_confidence=0.85,
            max_attempts=1,
        )

        self.assertIsNotNone(extraction)
        self.assertEqual(attempts, 1)
        self.assertEqual(issues, [])
        self.assertEqual(extraction.heading, "")

    async def test_fallback_accepts_coordinate_annotation_inside_formula(
        self,
    ):
        layout = PageLayoutExtraction.model_validate(
            {
                "profile": "dots",
                "page": 17,
                "complete": True,
                "confidence": 0.95,
                "blocks": [
                    {
                        "block_id": "p0017:b005",
                        "category": "formula",
                        "text": (
                            "L̂^2 = L̂⃗ · L̂⃗ = "
                            "L̂_x^2 + L̂_y^2 + L̂_z^2 （直角坐标）\n"
                            "= -ℏ^2[1/sinθ ∂/∂θ "
                            "(sinθ ∂/∂θ)] （球极）"
                        ),
                        "formulas": [
                            {
                                "text": (
                                    "L̂^2 = L̂⃗ · L̂⃗ = "
                                    "L̂_x^2 + L̂_y^2 + L̂_z^2 "
                                    "= -ℏ^2[1/sinθ ∂/∂θ "
                                    "(sinθ ∂/∂θ)] （球极）"
                                ),
                                "latex": (
                                    r"\hat L^2=\vec{\hat L}\cdot"
                                    r"\vec{\hat L}="
                                    r"\hat L_x^2+\hat L_y^2+\hat L_z^2"
                                    r"=-\hbar^2[\cdots]"
                                ),
                            }
                        ],
                        "bbox": [0.088, 0.722, 0.864, 0.248],
                        "confidence": 0.95,
                    }
                ],
            }
        )
        client = _FakeLayoutNodeClient(
            {
                "page": 17,
                "complete": True,
                "confidence": 0.95,
                "has_knowledge": True,
                "nodes": [{"temp_id": "malformed", "name": "角动量"}],
            }
        )

        extraction, attempts, issues = await extract_layout_nodes(
            layout=layout,
            runtime=_runtime(client),
            min_confidence=0.85,
            max_attempts=1,
        )

        self.assertIsNotNone(extraction)
        self.assertEqual(attempts, 1)
        self.assertIn("node_selector_deterministic_fallback", issues)
        self.assertEqual(len(extraction.nodes), 1)

    async def test_fallback_keeps_heading_with_quoted_atomic_claim(self):
        layout = PageLayoutExtraction.model_validate(
            {
                "profile": "dots",
                "page": 62,
                "complete": True,
                "confidence": 0.95,
                "blocks": [
                    {
                        "block_id": "p0062:b000",
                        "category": "heading",
                        "text": (
                            "三. 能量最小原理 "
                            "“电子优先占据最低能态”"
                        ),
                        "bbox": [0.04, 0.04, 0.88, 0.07],
                        "confidence": 0.95,
                    },
                    {
                        "block_id": "p0062:b002",
                        "category": "paragraph",
                        "text": "经验规律：(n+0.7l)大→E大",
                        "bbox": [0.1, 0.8, 0.6, 0.07],
                        "confidence": 0.95,
                    },
                ],
            }
        )
        client = _FakeLayoutNodeClient(
            {
                "page": 62,
                "complete": True,
                "confidence": 0.95,
                "has_knowledge": True,
                "nodes": [
                    {
                        "temp_id": "malformed",
                        "name": "页面中不存在的节点",
                    }
                ],
            }
        )

        extraction, attempts, issues = await extract_layout_nodes(
            layout=layout,
            runtime=_runtime(client),
            min_confidence=0.85,
            max_attempts=1,
        )

        self.assertIsNotNone(extraction)
        self.assertEqual(attempts, 1)
        self.assertIn("node_selector_deterministic_fallback", issues)
        self.assertTrue(
            any(
                "电子优先占据最低能态" in node.evidence_text
                for node in extraction.nodes
            )
        )

    def test_single_formula_is_inherited_when_selector_omits_index(self):
        layout = self._layout()
        selection = LayoutNodeSelection(
            page=84,
            complete=True,
            confidence=0.95,
            has_knowledge=True,
            nodes=[
                {
                    "temp_id": "implicit-formula",
                    "name": "Δν/ν≈10^-6",
                    "type": "result",
                    "role": "other",
                    "block_id": "p0084:b001",
                    "confidence": 0.94,
                }
            ],
        )

        extraction = materialize_layout_selection(layout, selection)
        self.assertEqual(
            extraction.nodes[0].formula_text,
            "Δν/ν≈10^-6",
        )

    async def test_selector_infers_unique_formula_in_multi_formula_block(
        self,
    ):
        layout = PageLayoutExtraction.model_validate(
            {
                "profile": "dots",
                "page": 1,
                "complete": True,
                "confidence": 0.96,
                "blocks": [
                    {
                        "block_id": "p0001:b000",
                        "category": "paragraph",
                        "text": (
                            "a = 1\n"
                            "在条件成立时，b = 2，因此结果稳定。"
                        ),
                        "formulas": [
                            {"text": "a = 1", "latex": "a=1"},
                            {"text": "b = 2", "latex": "b=2"},
                        ],
                        "bbox": [0.1, 0.2, 0.8, 0.2],
                        "confidence": 0.96,
                    }
                ],
            }
        )
        client = _FakeLayoutNodeClient(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "has_knowledge": True,
                "nodes": [
                    {
                        "temp_id": "first",
                        "name": "a = 1",
                        "type": "formula",
                        "role": "formula",
                        "block_id": "p0001:b000",
                        "formula_index": None,
                        "confidence": 0.95,
                    },
                    {
                        "temp_id": "second",
                        "name": "在条件成立时，b = 2，因此结果稳定。",
                        "type": "result",
                        "role": "other",
                        "block_id": "p0001:b000",
                        "formula_index": None,
                        "confidence": 0.95,
                    },
                ],
            }
        )

        extraction, attempts, issues = await extract_layout_nodes(
            layout=layout,
            runtime=_runtime(client),
            min_confidence=0.85,
            max_attempts=1,
        )

        self.assertIsNotNone(extraction)
        self.assertEqual(attempts, 1)
        self.assertEqual(issues, [])
        self.assertEqual(
            [node.formula_text for node in extraction.nodes],
            ["a = 1", "b = 2"],
        )

    async def test_selector_drops_ambiguous_formula_wrapper_and_supplements(
        self,
    ):
        layout = PageLayoutExtraction.model_validate(
            {
                "profile": "dots",
                "page": 1,
                "complete": True,
                "confidence": 0.96,
                "blocks": [
                    {
                        "block_id": "p0001:b000",
                        "category": "paragraph",
                        "text": "条件为 a = 1，b = 2。",
                        "formulas": [
                            {"text": "a = 1", "latex": "a=1"},
                            {"text": "b = 2", "latex": "b=2"},
                        ],
                        "bbox": [0.1, 0.2, 0.8, 0.2],
                        "confidence": 0.96,
                    }
                ],
            }
        )
        client = _FakeLayoutNodeClient(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "has_knowledge": True,
                "nodes": [
                    {
                        "temp_id": "compound",
                        "name": "条件为 a = 1，b = 2。",
                        "type": "principle",
                        "role": "principle",
                        "block_id": "p0001:b000",
                        "formula_index": None,
                        "confidence": 0.95,
                    }
                ],
            }
        )

        extraction, attempts, issues = await extract_layout_nodes(
            layout=layout,
            runtime=_runtime(client),
            min_confidence=0.85,
            max_attempts=1,
        )

        self.assertIsNotNone(extraction)
        self.assertEqual(attempts, 1)
        self.assertEqual(issues, [])
        self.assertEqual(
            [node.formula_text for node in extraction.nodes],
            ["a = 1", "b = 2"],
        )
        self.assertTrue(
            all(node.temp_id.startswith("supplement-") for node in extraction.nodes)
        )

    def test_repeated_formula_drafts_are_materialized_once(self):
        layout = self._layout()
        selection = LayoutNodeSelection(
            page=84,
            complete=True,
            confidence=0.95,
            has_knowledge=True,
            nodes=[
                {
                    "temp_id": "first",
                    "name": "Δν/ν≈10^-6",
                    "type": "formula",
                    "role": "formula",
                    "block_id": "p0084:b001",
                    "confidence": 0.94,
                },
                {
                    "temp_id": "second",
                    "name": "= Δν/ν≈10^-6",
                    "type": "formula",
                    "role": "formula",
                    "block_id": "p0084:b001",
                    "confidence": 0.94,
                },
            ],
        )

        extraction = materialize_layout_selection(layout, selection)

        self.assertEqual(len(extraction.nodes), 1)
        self.assertEqual(extraction.nodes[0].formula_text, "Δν/ν≈10^-6")

    def test_unreferenced_formula_in_selected_block_is_supplemented(self):
        layout = PageLayoutExtraction(
            profile="dots",
            page=87,
            complete=True,
            confidence=0.96,
            blocks=[
                {
                    "block_id": "p0087:b000",
                    "category": "formula",
                    "text": "L~1m; n~1.0; c~3×10^8 m/s",
                    "formulas": [
                        {"text": "L~1m", "latex": r"L\sim1\,m"},
                        {"text": "n~1.0", "latex": r"n\sim1.0"},
                        {
                            "text": "c~3×10^8 m/s",
                            "latex": r"c\sim3\times10^{8}\,m/s",
                        },
                    ],
                    "bbox": [0.1, 0.2, 0.8, 0.2],
                    "confidence": 0.96,
                }
            ],
        )
        selection = LayoutNodeSelection(
            page=87,
            complete=True,
            confidence=0.95,
            has_knowledge=True,
            nodes=[
                {
                    "temp_id": "estimate",
                    "name": "L~1m",
                    "type": "formula",
                    "role": "formula",
                    "block_id": "p0087:b000",
                    "formula_index": 0,
                    "confidence": 0.94,
                }
            ],
        )

        extraction = materialize_layout_selection(layout, selection)
        self.assertEqual(
            [node.formula_text for node in extraction.nodes],
            ["L~1m", "n~1.0", "c~3×10^8 m/s"],
        )

    def test_omitted_short_relation_formula_block_is_supplemented(self):
        layout = PageLayoutExtraction(
            profile="dots",
            page=1,
            complete=True,
            confidence=0.96,
            blocks=[
                {
                    "block_id": "p0001:b000",
                    "category": "paragraph",
                    "text": "两个物理量之间的映射关系",
                    "bbox": [0.05, 0.05, 0.5, 0.08],
                    "confidence": 0.96,
                },
                {
                    "block_id": "p0001:b001",
                    "category": "formula",
                    "text": "A⃗ → B⃗",
                    "formulas": [
                        {
                            "text": "A⃗ → B⃗",
                            "latex": r"\vec{A} \rightarrow \vec{B}",
                        }
                    ],
                    "bbox": [0.2, 0.2, 0.3, 0.08],
                    "confidence": 0.96,
                },
            ],
        )
        selection = LayoutNodeSelection(
            page=1,
            complete=True,
            confidence=0.95,
            has_knowledge=True,
            nodes=[
                {
                    "temp_id": "relationship",
                    "name": "两个物理量之间的映射关系",
                    "type": "concept",
                    "role": "other",
                    "block_id": "p0001:b000",
                    "confidence": 0.95,
                    "terminal_gold_gate": TERMINAL_GOLD_GATE,
                }
            ],
        )

        extraction = materialize_layout_selection(layout, selection)

        self.assertEqual(
            [node.formula_text for node in extraction.nodes],
            ["", "A⃗ → B⃗"],
        )
        self.assertEqual(
            page_knowledge_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
                page_has_text_signal=True,
            ),
            (),
        )

    def test_layout_audit_upgrades_matching_numeric_evidence_in_place(self):
        layout = PageLayoutExtraction(
            profile="dots",
            page=1,
            complete=True,
            confidence=0.96,
            blocks=[
                {
                    "block_id": "p0001:b000",
                    "category": "formula",
                    "text": "脉冲瞬时功率可达 > 10^14 W",
                    "formulas": [
                        {
                            "text": "脉冲瞬时功率可达 > 10^14 W",
                            "latex": (
                                r"\text{脉冲瞬时功率可达 }"
                                r">10^{14}\,\mathrm{W}"
                            ),
                        }
                    ],
                    "bbox": [0.2, 0.2, 0.5, 0.08],
                    "confidence": 0.96,
                }
            ],
        )
        extraction = PageKnowledgeExtraction(
            page=1,
            complete=True,
            confidence=0.96,
            heading="激光",
            has_knowledge=True,
            nodes=[
                {
                    "temp_id": "pulse-power",
                    "name": "激光脉冲瞬时功率",
                    "type": "result",
                    "role": "other",
                    "definition": "脉冲瞬时功率可达 > 10 ¹⁴ W",
                    "evidence_text": "脉冲瞬时功率可达 > 10 ¹⁴ W",
                    "bbox": [0.2, 0.2, 0.5, 0.08],
                    "confidence": 0.96,
                    "terminal_gold_gate": TERMINAL_GOLD_GATE,
                }
            ],
        )

        reconciled = reconcile_layout_formulas(
            layout=layout,
            extraction=extraction,
        )

        self.assertEqual(len(reconciled.nodes), 1)
        self.assertEqual(reconciled.nodes[0].temp_id, "pulse-power")
        self.assertEqual(
            reconciled.nodes[0].formula_text,
            "脉冲瞬时功率可达 > 10^14 W",
        )
        self.assertEqual(
            page_knowledge_issues(
                reconciled,
                expected_page=1,
                min_confidence=0.85,
                page_has_text_signal=True,
            ),
            (),
        )

    def test_unreferenced_formulas_replace_trailing_nonformula_nodes_at_cap(
        self,
    ):
        formula_blocks = [
            {
                "block_id": f"p0001:b{index:03d}",
                "category": "formula",
                "text": f"f_{index} = {index}",
                "formulas": [
                    {
                        "text": f"f_{index} = {index}",
                        "latex": f"f_{index}={index}",
                    }
                ],
                "bbox": [0.05, 0.05 + index * 0.03, 0.4, 0.02],
                "confidence": 0.96,
            }
            for index in range(8)
        ]
        concept_blocks = [
            {
                "block_id": f"p0001:b{index + 8:03d}",
                "category": "paragraph",
                "text": f"概念 {index} 的原子事实",
                "bbox": [0.55, 0.05 + index * 0.04, 0.4, 0.03],
                "confidence": 0.95,
            }
            for index in range(6)
        ]
        layout = PageLayoutExtraction(
            profile="dots",
            page=1,
            complete=True,
            confidence=0.96,
            blocks=[*formula_blocks, *concept_blocks],
        )
        selection = LayoutNodeSelection(
            page=1,
            complete=True,
            confidence=0.95,
            has_knowledge=True,
            nodes=[
                *[
                    {
                        "temp_id": f"formula-{index}",
                        "name": f"f_{index} = {index}",
                        "type": "formula",
                        "role": "formula",
                        "block_id": f"p0001:b{index:03d}",
                        "formula_index": 0,
                        "confidence": 0.96,
                    }
                    for index in range(6)
                ],
                *[
                    {
                        "temp_id": f"concept-{index}",
                        "name": f"概念 {index} 的原子事实",
                        "type": "concept",
                        "role": "other",
                        "block_id": f"p0001:b{index + 8:03d}",
                        "confidence": 0.95,
                    }
                    for index in range(6)
                ],
            ],
        )

        extraction = materialize_layout_selection(layout, selection)

        self.assertEqual(len(extraction.nodes), 12)
        self.assertEqual(
            {
                node.formula_text
                for node in extraction.nodes
                if node.formula_text
            },
            {f"f_{index} = {index}" for index in range(8)},
        )
        self.assertEqual(
            sum(not node.formula_text for node in extraction.nodes),
            4,
        )

    def test_omitted_atomic_nonformula_block_is_supplemented(self):
        layout = PageLayoutExtraction(
            profile="dots",
            page=1,
            complete=True,
            confidence=0.96,
            blocks=[
                {
                    "block_id": "p0001:b000",
                    "category": "paragraph",
                    "text": "先比较两组实验的边界条件",
                    "bbox": [0.05, 0.05, 0.4, 0.08],
                    "confidence": 0.96,
                },
                {
                    "block_id": "p0001:b001",
                    "category": "paragraph",
                    "text": "当距离足够小时近似条件成立",
                    "bbox": [0.05, 0.18, 0.4, 0.08],
                    "confidence": 0.96,
                },
                {
                    "block_id": "p0001:b002",
                    "category": "caption",
                    "text": "图一：实验装置",
                    "bbox": [0.55, 0.05, 0.35, 0.05],
                    "confidence": 0.95,
                },
            ],
        )
        selection = LayoutNodeSelection(
            page=1,
            complete=True,
            confidence=0.95,
            has_knowledge=True,
            nodes=[
                {
                    "temp_id": "selected",
                    "name": "先比较两组实验的边界条件",
                    "type": "step",
                    "role": "step",
                    "block_id": "p0001:b000",
                    "confidence": 0.96,
                }
            ],
        )

        extraction = materialize_layout_selection(layout, selection)

        self.assertEqual(
            [node.evidence_text for node in extraction.nodes],
            [
                "先比较两组实验的边界条件",
                "当距离足够小时近似条件成立",
            ],
        )
        self.assertTrue(
            extraction.nodes[1].temp_id.startswith(
                "supplement-p0001:b001-"
            )
        )

    def test_formula_subexpression_does_not_hide_complete_formula(self):
        concept_blocks = [
            {
                "block_id": f"p0001:b{index + 1:03d}",
                "category": "paragraph",
                "text": f"概念 {index} 的原子事实",
                "bbox": [0.55, 0.05 + index * 0.03, 0.4, 0.02],
                "confidence": 0.95,
            }
            for index in range(11)
        ]
        layout = PageLayoutExtraction(
            profile="dots",
            page=1,
            complete=True,
            confidence=0.96,
            blocks=[
                {
                    "block_id": "p0001:b000",
                    "category": "formula",
                    "text": "∂B_z/∂z",
                    "formulas": [
                        {
                            "text": "∂B_z/∂z",
                            "latex": r"\frac{\partial B_z}{\partial z}",
                        }
                    ],
                    "bbox": [0.05, 0.05, 0.4, 0.02],
                    "confidence": 0.96,
                },
                *concept_blocks,
                {
                    "block_id": "p0001:b012",
                    "category": "formula",
                    "text": "F_z = μ_z ∂B_z/∂z",
                    "formulas": [
                        {
                            "text": "F_z = μ_z ∂B_z/∂z",
                            "latex": (
                                r"F_z=\mu_z"
                                r"\frac{\partial B_z}{\partial z}"
                            ),
                        }
                    ],
                    "bbox": [0.05, 0.45, 0.4, 0.02],
                    "confidence": 0.96,
                },
            ],
        )
        selection = LayoutNodeSelection(
            page=1,
            complete=True,
            confidence=0.95,
            has_knowledge=True,
            nodes=[
                {
                    "temp_id": "short-formula",
                    "name": "∂B_z/∂z",
                    "type": "formula",
                    "role": "formula",
                    "block_id": "p0001:b000",
                    "formula_index": 0,
                    "confidence": 0.96,
                },
                *[
                    {
                        "temp_id": f"concept-{index}",
                        "name": f"概念 {index} 的原子事实",
                        "type": "concept",
                        "role": "other",
                        "block_id": f"p0001:b{index + 1:03d}",
                        "confidence": 0.95,
                    }
                    for index in range(11)
                ],
            ],
        )

        extraction = materialize_layout_selection(layout, selection)

        self.assertEqual(
            {
                node.formula_text
                for node in extraction.nodes
                if node.formula_text
            },
            {"∂B_z/∂z", "F_z = μ_z ∂B_z/∂z"},
        )

    async def test_fallback_skips_connectives_and_isolated_math_labels(self):
        formula_blocks = [
            {
                "block_id": f"p0001:b{index:03d}",
                "category": "formula",
                "text": f"q_{index} = {index}",
                "formulas": [
                    {
                        "text": f"q_{index} = {index}",
                        "latex": f"q_{index}={index}",
                    }
                ],
                "bbox": [0.05, 0.04 + index * 0.04, 0.4, 0.03],
                "confidence": 0.96,
            }
            for index in range(8)
        ]
        noise_blocks = [
            {
                "block_id": f"p0001:b{index + 8:03d}",
                "category": "paragraph",
                "text": text,
                "bbox": [0.55, 0.04 + index * 0.04, 0.4, 0.03],
                "confidence": 0.95,
            }
            for index, text in enumerate(("令", "有", "z", "F_z"))
        ]
        layout = PageLayoutExtraction(
            profile="dots",
            page=1,
            complete=True,
            confidence=0.96,
            blocks=[
                *formula_blocks,
                *noise_blocks,
                {
                    "block_id": "p0001:b012",
                    "category": "paragraph",
                    "text": "系统稳定性由阻尼系数决定",
                    "bbox": [0.55, 0.25, 0.4, 0.05],
                    "confidence": 0.95,
                },
            ],
        )
        client = _FakeLayoutNodeClient(
            {
                "page": 1,
                "complete": True,
                "confidence": 0.95,
                "has_knowledge": True,
                "nodes": [
                    {
                        "temp_id": "malformed",
                        "name": "页面中不存在的节点",
                    }
                ],
            }
        )

        extraction, attempts, issues = await extract_layout_nodes(
            layout=layout,
            runtime=_runtime(client),
            min_confidence=0.85,
            max_attempts=1,
        )

        self.assertIsNotNone(extraction)
        self.assertEqual(attempts, 1)
        self.assertIn("node_selector_deterministic_fallback", issues)
        self.assertTrue(
            any(
                node.evidence_text == "系统稳定性由阻尼系数决定"
                for node in extraction.nodes
            )
        )
        self.assertTrue(
            all(
                node.name not in {"令", "有", "z", "F_z"}
                for node in extraction.nodes
            )
        )

    def test_unknown_block_reference_is_rejected(self):
        layout = self._layout()
        selection = LayoutNodeSelection(
            page=84,
            complete=True,
            confidence=0.95,
            has_knowledge=True,
            nodes=[
                {
                    "temp_id": "bad",
                    "name": "错误引用",
                    "type": "concept",
                    "role": "other",
                    "block_id": "missing",
                    "confidence": 0.94,
                }
            ],
        )

        with self.assertRaisesRegex(ValueError, "unknown layout block"):
            materialize_layout_selection(layout, selection)

    def test_unseen_name_falls_back_to_inherited_formula(self):
        layout = self._layout()
        selection = LayoutNodeSelection(
            page=84,
            complete=True,
            confidence=0.95,
            has_knowledge=True,
            nodes=[
                {
                    "temp_id": "bad-subject",
                    "name": "同步辐射谱线相对宽度",
                    "type": "formula",
                    "role": "formula",
                    "block_id": "p0084:b001",
                    "formula_index": 0,
                    "confidence": 0.94,
                }
            ],
        )

        extraction = materialize_layout_selection(layout, selection)
        self.assertEqual(
            extraction.nodes[0].name,
            "Δν/ν≈10^-6",
        )


if __name__ == "__main__":
    unittest.main()
