from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from pydantic import ValidationError

from backend.app.agents import RoleRuntime
from backend.app.blackboard import SQLiteBlackboard
from backend.app.mindmap_engine.schemas import RenderResponse, RenderedPage
from backend.app.pdf_page_transcription import (
    PageExtraction,
    PageTranscriptionBlock,
    page_extraction_issues,
    transcribe_pdf_pages,
)
from backend.app.schemas import ParsedDocument


class _FakePageTranscriptionClient:
    supports_multimodal = True

    def __init__(self, responses: dict[int, list[dict]]):
        self.responses = {
            page: list(items)
            for page, items in responses.items()
        }
        self.calls: list[dict] = []

    async def complete_multimodal_json(self, **kwargs):
        self.calls.append(kwargs)
        match = re.search(r"转录第 (\d+) 页", kwargs["user_prompt"])
        if not match:
            raise AssertionError("page number missing from prompt")
        page = int(match.group(1))
        return self.responses[page].pop(0)


def _page_payload(
    page: int,
    *,
    confidence: float = 0.98,
    formula: bool = False,
) -> dict:
    block = (
        {
            "kind": "formula",
            "text": "线宽 Δν/ν≈10^-6",
            "latex": r"\frac{\Delta\nu}{\nu}\approx 10^{-6}",
            "bbox": [0.1, 0.2, 0.7, 0.2],
            "confidence": confidence,
        }
        if formula
        else {
            "kind": "paragraph",
            "text": f"第 {page} 页正文",
            "latex": "",
            "bbox": [0.1, 0.2, 0.7, 0.2],
            "confidence": confidence,
        }
    )
    return {
        "page": page,
        "complete": True,
        "confidence": confidence,
        "blocks": [block],
    }


def _rendered_fixture(
    root: Path,
    *,
    page_count: int,
) -> tuple[RenderResponse, Path]:
    data_root = root / "data"
    render_id = "page-transcription-fixture"
    render_dir = data_root / "assets" / render_id
    render_dir.mkdir(parents=True)
    pages: list[RenderedPage] = []
    for page_number in range(1, page_count + 1):
        filename = f"page_{page_number:04d}.png"
        image = Image.new("RGB", (320, 240), "white")
        image.save(render_dir / filename)
        pages.append(
            RenderedPage(
                asset_id=f"page_{page_number:04d}",
                render_id=render_id,
                filename=filename,
                url=f"/{filename}",
                page=page_number,
                width=image.width,
                height=image.height,
            )
        )
    return (
        RenderResponse(
            render_id=render_id,
            filename="fixture.pdf",
            pages=pages,
            native_visuals=[],
        ),
        data_root,
    )


def _document(page_count: int) -> ParsedDocument:
    return ParsedDocument(
        document_id="doc-page-transcription",
        filename="fixture.pdf",
        file_type="pdf",
        title="公式课程",
        blocks=[],
        parse_metadata={"pdf_page_count": page_count},
    )


def _runtime(client) -> RoleRuntime:
    return RoleRuntime(
        provider="qwen",
        model="qwen3-vl-plus",
        client=client,
        available=True,
    )


class PdfPageTranscriptionSchemaTDDTests(unittest.TestCase):
    def test_formula_blocks_require_canonical_text_latex_and_valid_bbox(self):
        with self.assertRaises(ValidationError):
            PageTranscriptionBlock(
                kind="formula",
                text="10^-6",
                latex="",
                bbox=[0.1, 0.1, 0.5, 0.2],
                confidence=0.9,
            )
        with self.assertRaises(ValidationError):
            PageTranscriptionBlock(
                kind="formula",
                text="10^-6",
                latex=r"10^{-6}",
                bbox=[0.8, 0.8, 0.3, 0.3],
                confidence=0.9,
            )

    def test_quality_gate_rejects_incomplete_formula_and_residual_pua(self):
        malformed = PageExtraction(
            page=1,
            complete=True,
            confidence=0.98,
            blocks=[
                PageTranscriptionBlock(
                    kind="formula",
                    text="N/N=e",
                    latex=r"N/N=e",
                    bbox=[0.1, 0.1, 0.5, 0.2],
                    confidence=0.98,
                ),
                PageTranscriptionBlock(
                    kind="paragraph",
                    text="残余字符 \uf040",
                    bbox=[0.1, 0.4, 0.5, 0.2],
                    confidence=0.98,
                ),
            ],
        )
        issues = page_extraction_issues(
            malformed,
            expected_page=1,
            min_confidence=0.85,
        )

        self.assertIn("block_0:decay_exponent_missing", issues)
        self.assertIn("block_1:residual_private_use_glyph", issues)

    def test_quality_gate_keeps_cross_font_negative_exponent_canonical(self):
        extraction = PageExtraction.model_validate(
            _page_payload(1, formula=True)
        )

        self.assertEqual(
            page_extraction_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
            (),
        )

    def test_92_page_oracle_requires_complete_canonical_formulas(self):
        expected_by_page = {
            84: [
                "ν=c/λ=3×10^8/(0.6328×10^-6)≈5×10^14",
            ],
            85: [
                "Δν/ν=1.3×10^9/(5×10^14)≈3×10^-6",
            ],
            86: [
                "nL=kλ_k/2",
                "λ_k=2nL/k",
            ],
            87: [
                "ν_k=c/λ=kc/2nL",
                "Δν_k=c/2nL",
            ],
            88: [
                "N=Δν/Δν_k=1.3×10^9/(1.5×10^8)≈8",
            ],
            92: [
                "非聚焦状态 I>10^11 W/m²",
                "聚焦状态 I>10^17 W/cm²",
                "脉冲瞬时功率可达 >10^14 W",
                "可产生 10^8 K 的高温",
            ],
        }
        latex_by_formula = {
            formula: rf"\mathrm{{{index}}}"
            for index, formula in enumerate(
                (
                    formula
                    for formulas in expected_by_page.values()
                    for formula in formulas
                ),
                start=1,
            )
        }

        for page, expected in expected_by_page.items():
            with self.subTest(page=page):
                extraction = PageExtraction(
                    page=page,
                    complete=True,
                    confidence=0.99,
                    blocks=[
                        PageTranscriptionBlock(
                            kind="formula",
                            text=formula,
                            latex=latex_by_formula[formula],
                            bbox=[0.1, 0.1 + index * 0.1, 0.8, 0.08],
                            confidence=0.99,
                        )
                        for index, formula in enumerate(expected)
                    ],
                )
                actual = [
                    block.text
                    for block in extraction.blocks
                    if block.kind == "formula"
                ]

                self.assertEqual(actual, expected)
                self.assertEqual(
                    page_extraction_issues(
                        extraction,
                        expected_page=page,
                        min_confidence=0.85,
                    ),
                    (),
                )


class PdfPageTranscriptionRuntimeTDDTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_each_page_is_called_once_and_success_is_checkpointed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=2)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_page_transcription",
                task_id="task_page_transcription",
                mode="precision",
                manifest={"source_sha256": "source-sha"},
            )
            client = _FakePageTranscriptionClient(
                {
                    1: [_page_payload(1, formula=True)],
                    2: [_page_payload(2)],
                }
            )

            first = await transcribe_pdf_pages(
                document=_document(2),
                rendered=rendered,
                runtime=_runtime(client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256="source-sha",
                prompt_version="page-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=2,
                max_page_attempts=2,
            )
            second = await transcribe_pdf_pages(
                document=_document(2),
                rendered=rendered,
                runtime=_runtime(client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256="source-sha",
                prompt_version="page-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=2,
                max_page_attempts=2,
            )

        self.assertTrue(first.complete)
        self.assertEqual(first.accepted_pages, [1, 2])
        self.assertEqual(first.called_pages, [1, 2])
        self.assertEqual(first.reused_pages, [])
        self.assertEqual(len(client.calls), 2)
        self.assertIn("10^-6", first.document.blocks[0].text)
        self.assertEqual(second.called_pages, [])
        self.assertEqual(second.reused_pages, [1, 2])
        self.assertEqual(len(client.calls), 2)
        metadata = second.document.parse_metadata["pdf_page_transcription"]
        self.assertEqual(metadata["model"], "qwen3-vl-plus")
        self.assertEqual(metadata["render_dpi"], 192)
        self.assertEqual(len(metadata["pages"]), 2)

    async def test_low_confidence_retry_is_local_to_the_failed_page(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=2)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_page_retry",
                task_id="task_page_retry",
                mode="precision",
            )
            client = _FakePageTranscriptionClient(
                {
                    1: [
                        _page_payload(1, confidence=0.4),
                        _page_payload(1, confidence=0.98),
                    ],
                    2: [_page_payload(2, confidence=0.98)],
                }
            )

            result = await transcribe_pdf_pages(
                document=_document(2),
                rendered=rendered,
                runtime=_runtime(client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256="source-sha",
                prompt_version="page-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=2,
                max_page_attempts=2,
            )

        page_calls = [
            int(re.search(r"转录第 (\d+) 页", call["user_prompt"]).group(1))
            for call in client.calls
        ]
        self.assertTrue(result.complete)
        self.assertEqual(page_calls.count(1), 2)
        self.assertEqual(page_calls.count(2), 1)

    async def test_failed_page_is_omitted_and_blocks_publication(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=2)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_page_failure",
                task_id="task_page_failure",
                mode="precision",
            )
            client = _FakePageTranscriptionClient(
                {
                    1: [_page_payload(1, confidence=0.98)],
                    2: [_page_payload(2, confidence=0.4)],
                }
            )

            result = await transcribe_pdf_pages(
                document=_document(2),
                rendered=rendered,
                runtime=_runtime(client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256="source-sha",
                prompt_version="page-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=2,
                max_page_attempts=1,
            )

        self.assertFalse(result.complete)
        self.assertEqual(result.accepted_pages, [1])
        self.assertEqual(result.failed_pages, [2])
        self.assertEqual([block.page for block in result.document.blocks], [1])
        self.assertTrue(
            any(
                "pdf_transcription_degraded:page_failure" in warning
                for warning in result.warnings
            )
        )


if __name__ == "__main__":
    unittest.main()
