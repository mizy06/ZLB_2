from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import document_parser
from backend.app.agents import build_content_units
from backend.app.chunking import chunk_document
from backend.app.document_parser import parse_document
from backend.app.pdf_math_geometry import (
    MathLayoutCandidate,
    _candidate_issues,
    extract_math_layout_candidates,
)
from backend.app.schemas import ParsedDocument, SourceBlock


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "quantum_courseware_input_pages.json"
)


class _FakePage:
    def __init__(self, text: str):
        self.text = text
        self.calls: list[dict] = []

    def extract_text(self, **kwargs):
        self.calls.append(kwargs)
        return self.text


class _FakeGeometryPage:
    def __init__(self, chars: list[dict], lines: list[dict]):
        self.chars = chars
        self.lines = lines


def _glyph(
    text: str,
    *,
    x0: float,
    x1: float,
    top: float,
    bottom: float,
    size: float,
    font: str = "TimesNewRomanPS-BoldMT",
) -> dict:
    return {
        "text": text,
        "x0": x0,
        "x1": x1,
        "top": top,
        "bottom": bottom,
        "size": size,
        "fontname": font,
    }


def _fixture_pages() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class PdfInputQualityTDDTests(unittest.TestCase):
    def test_math_layout_normalization_does_not_rewrite_plain_subtraction(
        self,
    ):
        self.assertEqual(
            document_parser._prepare_pdf_math_layout(
                "误差由10 - 15得到，结果仍需复核。"
            ),
            "误差由10 - 15得到，结果仍需复核。",
        )
        self.assertIn(
            "10^-15",
            document_parser._prepare_pdf_math_layout(
                "在超高稳频条件下，线宽会小到10 - 15。"
            ),
        )

    def test_math_layout_normalization_recovers_approximately_equal_pua(
        self,
    ):
        self.assertEqual(
            document_parser._prepare_pdf_math_layout(
                "纵模个数 N=Δν/Δν_k \uf0408"
            ),
            "纵模个数 N=Δν/Δν_k ≈8",
        )

    def test_math_layout_normalization_recovers_full_longitudinal_mode_ratio(
        self,
    ):
        raw = (
            "     而氦氖激光器 632.8 nm 谱线的宽度为：\n"
            "         \uf044\uf06e =1.3×109 HZ\n"
            "因此，在\uf044\uf06e 区间中，可以存在的纵模个数为：\n"
            "          \uf044\uf06e    1.3 \uf0b4 10\n"
            "                       9\n"
            "       N=     =           \uf0408\n"
            "          \uf044\uf06e k 1.5 \uf0b4 10 8\n"
        )

        normalized = document_parser._prepare_pdf_math_layout(raw)
        page = _FakeGeometryPage(
            chars=[
                _glyph(
                    "9",
                    x0=401.5,
                    x1=412.5,
                    top=197.7,
                    bottom=219.3,
                    size=21.6,
                ),
                _glyph(
                    "\uf044\uf06e",
                    x0=218.4,
                    x1=264.4,
                    top=203.7,
                    bottom=236.1,
                    size=32.4,
                    font="SymbolMT",
                ),
                _glyph(
                    "1.3",
                    x0=304.5,
                    x1=345.2,
                    top=203.7,
                    bottom=236.1,
                    size=32.4,
                ),
                _glyph(
                    "\uf0b4",
                    x0=348.3,
                    x1=366.4,
                    top=203.7,
                    bottom=236.1,
                    size=32.4,
                    font="SymbolMT",
                ),
                _glyph(
                    "10",
                    x0=368.4,
                    x1=402.8,
                    top=203.7,
                    bottom=236.1,
                    size=32.4,
                ),
                _glyph(
                    "N",
                    x0=147.5,
                    x1=171.4,
                    top=224.6,
                    bottom=257.0,
                    size=32.4,
                ),
                _glyph(
                    "=",
                    x0=182.3,
                    x1=200.4,
                    top=224.6,
                    bottom=257.0,
                    size=32.4,
                    font="SymbolMT",
                ),
                _glyph(
                    "=",
                    x0=277.7,
                    x1=295.9,
                    top=224.6,
                    bottom=257.0,
                    size=32.4,
                    font="SymbolMT",
                ),
                _glyph(
                    "\uf040",
                    x0=425.4,
                    x1=443.6,
                    top=224.6,
                    bottom=257.0,
                    size=32.4,
                    font="SymbolMT",
                ),
                _glyph(
                    "8",
                    x0=451.1,
                    x1=467.6,
                    top=224.6,
                    bottom=257.0,
                    size=32.4,
                ),
                _glyph(
                    "8",
                    x0=401.5,
                    x1=412.5,
                    top=245.4,
                    bottom=267.0,
                    size=21.6,
                ),
                _glyph(
                    "\uf044\uf06e",
                    x0=211.1,
                    x1=257.1,
                    top=249.4,
                    bottom=281.8,
                    size=32.4,
                    font="SymbolMT",
                ),
                _glyph(
                    "1.5",
                    x0=304.5,
                    x1=345.2,
                    top=251.4,
                    bottom=283.8,
                    size=32.4,
                ),
                _glyph(
                    "\uf0b4",
                    x0=348.3,
                    x1=366.4,
                    top=251.4,
                    bottom=283.8,
                    size=32.4,
                    font="SymbolMT",
                ),
                _glyph(
                    "10",
                    x0=368.4,
                    x1=402.8,
                    top=251.4,
                    bottom=283.8,
                    size=32.4,
                ),
                _glyph(
                    "k",
                    x0=252.1,
                    x1=263.1,
                    top=266.0,
                    bottom=287.5,
                    size=21.6,
                ),
            ],
            lines=[
                {
                    "x0": 208.9,
                    "x1": 269.2,
                    "top": 241.4,
                    "bottom": 241.4,
                    "width": 60.3,
                },
                {
                    "x0": 304.4,
                    "x1": 416.9,
                    "top": 241.4,
                    "bottom": 241.4,
                    "width": 112.5,
                },
            ],
        )
        candidates = {
            candidate.canonical
            for candidate in extract_math_layout_candidates(page)
        }

        self.assertIn("Δν =1.3×10^9 HZ", normalized)
        self.assertIn("N=Δν/Δν_k≈8", candidates)
        self.assertTrue(
            any(
                "1.3×10^9/(1.5×10^8)" in candidate
                for candidate in candidates
            )
        )
        self.assertNotRegex(normalized, r"[\ue000-\uf8ff\ufffd]")
        self.assertTrue(
            all(
                not re.search(r"[\ue000-\uf8ff\ufffd]", candidate)
                for candidate in candidates
            )
        )

    def test_math_layout_normalization_recovers_intensity_exponents_and_units(
        self,
    ):
        raw = (
            "3.亮度和强度极高：\n"
            "                        11       2\n"
            "     强度：非聚焦状态 I > 10 W m\n"
            "        聚焦状态可达到 I \uf03e 1017 W/cm2\n"
            "        脉冲瞬时功率可达 > 10 14 W\n"
        )

        normalized = document_parser._prepare_pdf_math_layout(raw)
        page = _FakeGeometryPage(
            chars=[
                _glyph(
                    "11",
                    x0=436.4,
                    x1=458.6,
                    top=314.1,
                    bottom=335.5,
                    size=21.4,
                ),
                _glyph(
                    "2",
                    x0=540.4,
                    x1=551.5,
                    top=314.1,
                    bottom=335.5,
                    size=21.4,
                ),
                _glyph(
                    "强度：非聚焦状态",
                    x0=95.8,
                    x1=353.0,
                    top=318.3,
                    bottom=350.4,
                    size=32.1,
                    font="SimSun",
                ),
                _glyph(
                    "10",
                    x0=404.5,
                    x1=439.0,
                    top=320.1,
                    bottom=352.2,
                    size=32.1,
                ),
                _glyph(
                    "W",
                    x0=465.1,
                    x1=498.5,
                    top=320.1,
                    bottom=352.2,
                    size=32.1,
                ),
                _glyph(
                    "m",
                    x0=511.6,
                    x1=539.4,
                    top=320.1,
                    bottom=352.2,
                    size=32.1,
                ),
                _glyph(
                    "I",
                    x0=360.8,
                    x1=373.3,
                    top=320.7,
                    bottom=352.8,
                    size=32.1,
                ),
                _glyph(
                    ">",
                    x0=381.4,
                    x1=399.6,
                    top=320.7,
                    bottom=352.8,
                    size=32.1,
                ),
                _glyph(
                    "17",
                    x0=519.3,
                    x1=542.0,
                    top=362.1,
                    bottom=383.9,
                    size=21.8,
                ),
                _glyph(
                    "2",
                    x0=633.7,
                    x1=645.3,
                    top=362.1,
                    bottom=383.9,
                    size=21.8,
                ),
                _glyph(
                    "聚焦状态可达到",
                    x0=199.4,
                    x1=424.4,
                    top=363.9,
                    bottom=395.9,
                    size=32.0,
                    font="SimSun",
                ),
                _glyph(
                    "I",
                    x0=440.2,
                    x1=453.7,
                    top=368.2,
                    bottom=401.0,
                    size=32.7,
                ),
                _glyph(
                    "\uf03e",
                    x0=463.4,
                    x1=482.5,
                    top=368.2,
                    bottom=401.0,
                    size=32.7,
                    font="SymbolMT",
                ),
                _glyph(
                    "10",
                    x0=487.2,
                    x1=522.3,
                    top=368.2,
                    bottom=401.0,
                    size=32.7,
                ),
                _glyph(
                    "W/cm",
                    x0=549.2,
                    x1=633.7,
                    top=368.2,
                    bottom=401.0,
                    size=32.7,
                ),
            ],
            lines=[],
        )
        candidates = {
            candidate.canonical
            for candidate in extract_math_layout_candidates(page)
        }

        self.assertIn(
            "强度：非聚焦状态 I > 10^11 W/m²",
            candidates,
        )
        self.assertIn(
            "聚焦状态可达到 I > 10^17 W/cm²",
            candidates,
        )
        self.assertNotIn("1017 W/cm2", normalized)
        self.assertNotRegex(normalized, r"[\ue000-\uf8ff\ufffd]")

    def test_geometry_math_gate_keeps_signed_power_and_rejects_malformed(
        self,
    ):
        signed_power_page = _FakeGeometryPage(
            chars=[
                _glyph(
                    "线宽",
                    x0=100,
                    x1=170,
                    top=100,
                    bottom=132,
                    size=32,
                    font="SimSun",
                ),
                _glyph(
                    "10",
                    x0=180,
                    x1=212,
                    top=100,
                    bottom=132,
                    size=32,
                ),
                _glyph(
                    "−",
                    x0=211,
                    x1=220,
                    top=94,
                    bottom=115,
                    size=21,
                    font="SymbolMT",
                ),
                _glyph(
                    "6",
                    x0=221,
                    x1=232,
                    top=94,
                    bottom=115,
                    size=21,
                ),
                _glyph(
                    "Hz",
                    x0=238,
                    x1=275,
                    top=100,
                    bottom=132,
                    size=32,
                ),
            ],
            lines=[],
        )
        malformed_fraction_page = _FakeGeometryPage(
            chars=[
                _glyph(
                    "=",
                    x0=100,
                    x1=118,
                    top=120,
                    bottom=152,
                    size=32,
                    font="SymbolMT",
                ),
                _glyph(
                    "R(r",
                    x0=130,
                    x1=185,
                    top=98,
                    bottom=130,
                    size=32,
                ),
                _glyph(
                    "径向",
                    x0=130,
                    x1=195,
                    top=150,
                    bottom=182,
                    size=32,
                    font="SimSun",
                ),
            ],
            lines=[
                {
                    "x0": 128,
                    "x1": 198,
                    "top": 142,
                    "bottom": 142,
                    "width": 70,
                }
            ],
        )

        signed_candidates = {
            candidate.canonical
            for candidate in extract_math_layout_candidates(
                signed_power_page
            )
        }
        malformed_candidates = extract_math_layout_candidates(
            malformed_fraction_page
        )

        self.assertIn("线宽 10^-6 Hz", signed_candidates)
        self.assertNotIn("线宽 10^6 Hz", signed_candidates)
        self.assertEqual(malformed_candidates, [])

    def test_geometry_math_gate_rejects_incomplete_real_page_patterns(
        self,
    ):
        malformed = {
            "E_n=1/nE": "indexed_energy_denominator_incomplete",
            "E_n=E/n": "indexed_energy_denominator_incomplete",
            "E=(−13.6eV)/((n−Δ))Δ": "orphan_fraction_suffix",
            "dN/N=−A": "differential_factor_missing",
            "N/N=e": "decay_exponent_missing",
        }
        for canonical, issue in malformed.items():
            with self.subTest(canonical=canonical):
                self.assertIn(issue, _candidate_issues(canonical))

        complete = (
            "ν=(E_i−E_f)/h",
            "E_n=E_1/n^2",
            "E=−13.6eV/(n−Δ)^2",
            "dN/N=−A dt",
            "N=N(0)/e^At",
            "N/N_0=e^-At",
            "N=N(0)/e",
            "ν=c/λ=3×10^8/(0.6328×10^-6)≈5×10^14",
            "Δν/ν=1.3×10^9/(5×10^14)≈3×10^-6",
            "λ_k=2nL/k",
            "ν_k=c/λ=kc/2nL",
            "Δν_k=c/2nL",
            "N=Δν/Δν_k=1.3×10^9/(1.5×10^8)≈8",
            "B=Δp/(ΔS·ΔΩ)",
            "强度：非聚焦状态 I > 10^11 W/m²",
            "聚焦状态可达到 I > 10^17 W/cm²",
        )
        for canonical in complete:
            with self.subTest(canonical=canonical):
                self.assertEqual(_candidate_issues(canonical), ())

    def test_math_layout_comparison_recovers_ratio_and_standing_wave_formula(
        self,
    ):
        pages = [
            _FakePage(
                "而He—Ne激光器输出激光的\n"
                "在超高稳频条件下，却会小到10 - 15 为什么？\n"
                "A \uf0de 输出\nL\n"
                "某时刻A处的光有刚产生的，也有来回反射的。"
            ),
            _FakePage(
                "只有产生相长干涉才有输出。\n"
                "因为谐振腔两端反射镜处必是波节，\n"
                "所以有光程 ( k=1、2、3、…．)\n"
                "n—谐振腔内工作物质的折射率\n"
                "\uf06c—真空中的波长\nL"
            ),
        ]
        reader = type("_Reader", (), {"pages": pages})()
        fallback_by_page = {
            "1": (
                "       Δ\uf06e1.3 \uf0b4 109         −6\n"
                "       =           \uf0bb 3 \uf0b4 10\n"
                "     \uf06e    5 \uf0b4 1014\n\n"
                "                          Δ\uf06e\n"
                "而He—Ne激光器输出激光的\n"
                "                           \uf06e\n"
                "在超高稳频条件下，却会小到10 - 15\n"
                "                                 为什么？\n"
            ),
            "2": (
                " 只有产生相长干涉才有输出。\n"
                " 因为谐振腔两端反射镜处必是波节，\n"
                "             \uf06c k ( k=1、2、3、…．)\n"
                "所以有光程 nL = k\n"
                "              2\n"
                "n —谐振腔内工作物质的折射率\n"
                "       2 nL\n"
                "  \uf06ck =\n"
                "         k\n"
            ),
        }

        def run_pdftotext(command, **kwargs):
            page = command[command.index("-f") + 1]
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout=fallback_by_page[page],
                stderr="",
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "fixture.pdf"
            path.write_bytes(b"%PDF fixture")
            with (
                patch.object(document_parser, "PdfReader", return_value=reader),
                patch.object(
                    document_parser.shutil,
                    "which",
                    return_value="/usr/bin/pdftotext",
                ),
                patch.object(
                    document_parser.subprocess,
                    "run",
                    side_effect=run_pdftotext,
                ) as run,
            ):
                document = parse_document(path)

        self.assertEqual(run.call_count, 2)
        self.assertIn("Δν/ν", document.blocks[0].text)
        self.assertIn("10^-15", document.blocks[0].text)
        self.assertIn("nL = kλ_k/2", document.blocks[1].text)
        self.assertIn("λ_k = 2nL/k", document.blocks[1].text)
        self.assertIn(
            "nL = kλ_k/2；λ_k = 2nL/k",
            document.blocks[1].text,
        )
        fallback = document.parse_metadata["pdf_text_fallback"]
        self.assertEqual(fallback["candidate_pages"], [1, 2])
        self.assertEqual(fallback["math_comparison_pages"], [1, 2])
        self.assertEqual(fallback["used_pages"], [1, 2])

    def test_geometry_candidates_are_audit_metadata_not_parser_text(self):
        page = _FakePage(
            "在超高稳频条件下，\uf06e 线宽会小到10 - 15，需要复核。"
        )
        reader = type("_Reader", (), {"pages": [page]})()
        geometry_document = type(
            "_GeometryDocument",
            (),
            {
                "pages": [_FakeGeometryPage(chars=[], lines=[])],
                "close": lambda self: None,
            },
        )()
        candidate = MathLayoutCandidate(
            canonical="线宽 10^-6 Hz",
            source_bbox=(100, 100, 260, 140),
            confidence=0.97,
            kind="scientific_notation_line",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "fixture.pdf"
            path.write_bytes(b"%PDF fixture")
            with (
                patch.object(document_parser, "PdfReader", return_value=reader),
                patch.object(document_parser.shutil, "which", return_value=None),
                patch(
                    "pdfplumber.open",
                    return_value=geometry_document,
                ),
                patch.object(
                    document_parser,
                    "extract_math_layout_candidates",
                    return_value=[candidate],
                ),
            ):
                document = parse_document(path)

        geometry = document.parse_metadata["pdf_geometry_math"]
        self.assertFalse(geometry["injected_into_text"])
        self.assertEqual(geometry["candidate_count"], 1)
        self.assertEqual(
            geometry["candidates"][0]["canonical"],
            "线宽 10^-6 Hz",
        )
        self.assertNotIn("线宽 10^-6 Hz", document.blocks[0].text)

    def test_pdftotext_layout_runs_only_for_clearly_degraded_pages(self):
        pages = [
            _FakePage(
                "第28章 原子中的电子\n"
                "氢原子的量子力学处理包含完整的课程正文。"
            ),
            _FakePage("…………\n26"),
            _FakePage("光子能量定义为 E = hν"),
        ]
        reader = type("_Reader", (), {"pages": pages})()
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="径向方程的边界条件决定允许能级。\n26\n",
            stderr="",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "fixture.pdf"
            path.write_bytes(b"%PDF fixture")
            with (
                patch.object(document_parser, "PdfReader", return_value=reader),
                patch.object(
                    document_parser.shutil,
                    "which",
                    return_value="/usr/bin/pdftotext",
                ),
                patch.object(
                    document_parser.subprocess,
                    "run",
                    return_value=completed,
                ) as run,
            ):
                document = parse_document(path)

        self.assertEqual(run.call_count, 1)
        command = run.call_args.args[0]
        self.assertIn("-layout", command)
        self.assertEqual(command[command.index("-f") + 1], "2")
        self.assertEqual(command[command.index("-l") + 1], "2")
        self.assertIn(
            "径向方程的边界条件决定允许能级",
            next(block.text for block in document.blocks if block.page == 2),
        )
        fallback = document.parse_metadata["pdf_text_fallback"]
        self.assertEqual(fallback["candidate_pages"], [2])
        self.assertEqual(fallback["attempted_pages"], [2])
        self.assertEqual(fallback["used_pages"], [2])
        self.assertEqual(fallback["failed_pages"], [])
        self.assertTrue(fallback["tool_available"])

    def test_missing_pdftotext_keeps_pypdf_text_and_records_warning(self):
        page = _FakePage("…………\n26")
        reader = type("_Reader", (), {"pages": [page]})()

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "fixture.pdf"
            path.write_bytes(b"%PDF fixture")
            with (
                patch.object(document_parser, "PdfReader", return_value=reader),
                patch.object(document_parser.shutil, "which", return_value=None),
                patch.object(document_parser.subprocess, "run") as run,
            ):
                document = parse_document(path)

        run.assert_not_called()
        self.assertIn("…………", document.blocks[0].text)
        fallback = document.parse_metadata["pdf_text_fallback"]
        self.assertEqual(fallback["candidate_pages"], [1])
        self.assertEqual(fallback["attempted_pages"], [])
        self.assertEqual(fallback["used_pages"], [])
        self.assertFalse(fallback["tool_available"])
        self.assertTrue(
            any(
                "[pdf_parse_degraded:pdftotext_unavailable]" in warning
                for warning in document.warnings
            )
        )

    def test_failed_pdftotext_keeps_pypdf_text_and_records_page(self):
        page = _FakePage("…………\n26")
        reader = type("_Reader", (), {"pages": [page]})()

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "fixture.pdf"
            path.write_bytes(b"%PDF fixture")
            with (
                patch.object(document_parser, "PdfReader", return_value=reader),
                patch.object(
                    document_parser.shutil,
                    "which",
                    return_value="/usr/bin/pdftotext",
                ),
                patch.object(
                    document_parser.subprocess,
                    "run",
                    side_effect=subprocess.TimeoutExpired(
                        cmd="pdftotext",
                        timeout=20,
                    ),
                ),
            ):
                document = parse_document(path)

        self.assertIn("…………", document.blocks[0].text)
        fallback = document.parse_metadata["pdf_text_fallback"]
        self.assertEqual(fallback["attempted_pages"], [1])
        self.assertEqual(fallback["failed_pages"], [1])
        self.assertEqual(fallback["used_pages"], [])
        self.assertTrue(
            any(
                "[pdf_parse_degraded:pdftotext_failed]" in warning
                and "第 1 页" in warning
                for warning in document.warnings
            )
        )

    def test_courseware_chapter_markers_become_conservative_headings(self):
        fixtures = _fixture_pages()
        pages = [_FakePage(item["text"]) for item in fixtures]
        reader = type("_Reader", (), {"pages": pages})()

        with (
            patch.object(document_parser, "PdfReader", return_value=reader),
            patch.object(document_parser.shutil, "which", return_value=None),
        ):
            blocks = document_parser._parse_pdf(Path("fixture.pdf"))

        heading_by_page = {block.page: block.heading for block in blocks}
        for parsed_page, item in enumerate(fixtures, start=1):
            self.assertEqual(
                heading_by_page[parsed_page],
                item["expected_heading"],
            )

        self.assertIsNone(
            document_parser._infer_pdf_heading(
                "3. 氢原子光谱的实验规律\n正文"
            )
        )
        self.assertIsNone(
            document_parser._infer_pdf_heading(
                "第28章结束\n复习题"
            )
        )

    def test_courseware_noise_is_not_promoted_to_text_knowledge_units(self):
        fixtures = _fixture_pages()
        document = ParsedDocument(
            document_id="doc_quantum_courseware",
            filename="精细1-量子物理原子中的电子.pdf",
            file_type="pdf",
            title="原子中的电子",
            blocks=[
                SourceBlock(
                    text=item["text"],
                    page=item["page"],
                    heading=item["expected_heading"],
                )
                for item in fixtures
            ],
        )

        units = build_content_units(
            document,
            chunk_document(document, max_chars=1800),
            [],
        )
        status_by_page = {unit.page: unit.status for unit in units}

        for item in fixtures:
            self.assertEqual(
                status_by_page[item["page"]],
                item["expected_status"],
            )
        self.assertLessEqual(
            next(unit.importance for unit in units if unit.page == 30),
            0.15,
        )
        self.assertLessEqual(
            next(unit.importance for unit in units if unit.page == 63),
            0.15,
        )

    def test_short_equations_and_definitions_remain_eligible(self):
        document = ParsedDocument(
            document_id="doc_short_science",
            filename="short.pdf",
            file_type="pdf",
            title="短公式",
            blocks=[
                SourceBlock(text="E = hν", page=1),
                SourceBlock(
                    text="玻尔半径定义为 a₀ = 5.29×10⁻¹¹ m",
                    page=2,
                ),
                SourceBlock(text="∫ψ*ψ dτ = 1", page=3),
            ],
        )

        units = build_content_units(
            document,
            chunk_document(document, max_chars=1800),
            [],
        )

        self.assertEqual(
            [unit.status for unit in units],
            ["uncovered", "uncovered", "uncovered"],
        )
        self.assertTrue(all(unit.importance > 0.15 for unit in units))

    def test_pure_page_numbers_and_ellipsis_are_rejected_independently(self):
        document = ParsedDocument(
            document_id="doc_pagination_noise",
            filename="pagination.pdf",
            file_type="pdf",
            title="分页噪声",
            blocks=[
                SourceBlock(text="42", page=42),
                SourceBlock(text="…………", page=43),
            ],
        )

        units = build_content_units(
            document,
            chunk_document(document, max_chars=1800),
            [],
        )

        self.assertEqual(
            [unit.status for unit in units],
            ["rejected", "rejected"],
        )

    def test_complete_quiz_options_remain_eligible_text(self):
        document = ParsedDocument(
            document_id="doc_complete_quiz",
            filename="quiz.pdf",
            file_type="pdf",
            title="完整测验",
            blocks=[
                SourceBlock(
                    text=(
                        "单选题\n带负电的粒子是\n"
                        "A 电子\nB 质子\nC 中子\nD 光子\n提交"
                    ),
                    page=1,
                )
            ],
        )

        units = build_content_units(
            document,
            chunk_document(document, max_chars=1800),
            [],
        )

        self.assertEqual(units[0].status, "uncovered")


if __name__ == "__main__":
    unittest.main()
