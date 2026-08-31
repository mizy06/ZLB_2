import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from backend.app.document_parser import parse_documents
from backend.app.editorial_input import (
    build_editorial_input_bundle,
    classify_input,
    classify_inputs,
)
from backend.app.editorial_ppt_pipeline import (
    _draft_user_prompt,
    _compact_editorial_context,
    _manifest_with_source_refs,
    _source_reference_count,
    _source_unit_reference,
    _text_context_with_source_refs,
    EditorialMindMap,
    EditorialBrief,
)
from backend.app.single_shot_ppt_pipeline import SingleShotNode
from backend.app.architecture_schemas import JobView
from backend.app.config import (
    QWEN38_MAX_CONTEXT_WINDOW_TOKENS,
    QWEN38_MAX_INPUT_TOKENS_WITH_THINKING,
)
from backend.app.mindmap_engine.visuals import render_documents, resolve_asset_path


def _write_text_pdf(path: Path, text: str) -> None:
    stream = f"BT /F1 18 Tf 20 150 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(output)


class TestMultiDocAndContextCompaction(unittest.IsolatedAsyncioTestCase):
    def test_editorial_input_classification_matrix(self):
        self.assertEqual(classify_input(Path("lesson.pdf")), "visual")
        self.assertEqual(classify_input(Path("lesson.pptx")), "visual")
        self.assertEqual(classify_input(Path("lesson.docx")), "visual")
        self.assertEqual(classify_input(Path("notes.txt")), "text")
        self.assertEqual(classify_input(Path("notes.md")), "text")
        self.assertEqual(classify_input(Path("notes.markdown")), "text")
        self.assertEqual(
            classify_inputs([Path("lesson.pdf"), Path("lesson.docx")]),
            "visual",
        )
        self.assertEqual(
            classify_inputs([Path("notes.md"), Path("facts.txt")]),
            "text",
        )
        self.assertEqual(
            classify_inputs([Path("lesson.pdf"), Path("notes.md")]),
            "mixed",
        )

    def test_editorial_bundle_preserves_source_boundaries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = root / "first.md"
            second = root / "second.txt"
            first.write_text("# 第一份\n\n第一份事实。", encoding="utf-8")
            second.write_text("第二份事实。", encoding="utf-8")
            bundle = build_editorial_input_bundle(
                [first, second],
                ["first.md", "second.txt"],
            )
            self.assertEqual(bundle.input_mode, "text")
            self.assertIn("[document: first.md]", bundle.text_context)
            self.assertIn("[/document: first.md]", bundle.text_context)
            self.assertIn("[document: second.txt]", bundle.text_context)
            self.assertIn("[/document: second.txt]", bundle.text_context)
            self.assertEqual(
                [item["filename"] for item in bundle.document_manifest],
                ["first.md", "second.txt"],
            )
            self.assertEqual(len(bundle.document.blocks), 3)

    def test_markdown_pdf_and_mixed_bundle_are_parseable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            markdown = root / "notes.md"
            markdown.write_text(
                "# Markdown notes\n\n反射与折射属于光的传播现象。",
                encoding="utf-8",
            )
            pdf = root / "lesson.pdf"
            _write_text_pdf(pdf, "PDF optics fact")

            markdown_bundle = build_editorial_input_bundle(
                [markdown],
                ["notes.md"],
            )
            pdf_bundle = build_editorial_input_bundle(
                [pdf],
                ["lesson.pdf"],
            )
            mixed_bundle = build_editorial_input_bundle(
                [markdown, pdf],
                ["notes.md", "lesson.pdf"],
            )

            self.assertEqual(markdown_bundle.input_mode, "text")
            self.assertIn("反射与折射", markdown_bundle.text_context)
            self.assertEqual(pdf_bundle.input_mode, "visual")
            self.assertIn("PDF optics fact", pdf_bundle.text_context)
            self.assertEqual(mixed_bundle.input_mode, "mixed")
            self.assertEqual(
                [item["filename"] for item in mixed_bundle.document_manifest],
                ["notes.md", "lesson.pdf"],
            )
            self.assertIn("[document: notes.md]", mixed_bundle.text_context)
            self.assertIn("[document: lesson.pdf]", mixed_bundle.text_context)

    def test_pdf_render_produces_preview_for_refinement_attachment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pdf = root / "lesson.pdf"
            _write_text_pdf(pdf, "PDF preview")
            rendered = render_documents(
                [pdf],
                ["lesson.pdf"],
                root / "data",
            )
            self.assertEqual(len(rendered.pages), 1)
            page_path = resolve_asset_path(
                root / "data",
                rendered.render_id,
                rendered.pages[0].filename,
            )
            self.assertTrue(page_path.is_file())

    def test_mixed_input_uses_distinct_visual_and_text_source_refs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            markdown = root / "notes.md"
            markdown.write_text(
                "# 透镜\n\n凸透镜会聚平行光。",
                encoding="utf-8",
            )
            pdf = root / "lesson.pdf"
            _write_text_pdf(pdf, "Lens focal length")
            bundle = build_editorial_input_bundle(
                [markdown, pdf],
                ["notes.md", "lesson.pdf"],
            )
            visual_page_count = 1
            text_unit_count = len(bundle.document.blocks)
            manifest = _manifest_with_source_refs(
                bundle.document_manifest,
                input_mode="mixed",
                visual_page_count=visual_page_count,
            )
            text_context = _text_context_with_source_refs(
                document=bundle.document,
                input_mode="mixed",
                visual_page_count=visual_page_count,
                fallback=bundle.text_context,
            )
            source_count = _source_reference_count(
                input_mode="mixed",
                visual_page_count=visual_page_count,
                text_unit_count=text_unit_count,
            )
            prompt = _draft_user_prompt(
                filename="notes.md & lesson.pdf",
                slide_count=source_count,
                max_depth=4,
                document_manifest=manifest,
                input_mode="mixed",
                text_context=text_context,
                visual_page_count=visual_page_count,
                text_unit_count=text_unit_count,
            )

            self.assertEqual(source_count, 1 + text_unit_count)
            self.assertEqual(manifest[0]["source_ref_start"], 2)
            self.assertIn("[source_ref: 2]", text_context)
            self.assertIn("不是文档序号", prompt)
            self.assertIn("视觉页使用 1 到 1", prompt)
            self.assertEqual(
                _source_unit_reference(
                    1,
                    input_mode="mixed",
                    visual_page_count=1,
                ),
                ("slide", 1),
            )
            self.assertEqual(
                _source_unit_reference(
                    3,
                    input_mode="mixed",
                    visual_page_count=1,
                ),
                ("text", 2),
            )

    def test_render_documents_uses_one_collection_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_root = root / "data"
            first = root / "first.png"
            second = root / "second.png"
            from PIL import Image

            Image.new("RGB", (20, 12), "white").save(first)
            Image.new("RGB", (20, 12), "black").save(second)
            rendered = render_documents(
                [first, second],
                ["first.png", "second.png"],
                data_root,
            )
            self.assertTrue(rendered.render_id)
            self.assertEqual(rendered.filename, "first.png & second.png")
            self.assertEqual(
                [page.page for page in rendered.pages],
                [1, 2],
            )
            self.assertEqual(
                {page.render_id for page in rendered.pages},
                {rendered.render_id},
            )
            for page in rendered.pages:
                self.assertTrue(
                    resolve_asset_path(
                        data_root,
                        rendered.render_id,
                        page.filename,
                    ).is_file()
                )
            manifest = json.loads(
                (
                    data_root
                    / "assets"
                    / rendered.render_id
                    / "manifest.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                [item["filename"] for item in manifest["documents"]],
                ["first.png", "second.png"],
            )

    def test_parse_documents_single(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f1 = Path(tmpdir) / "doc1.txt"
            f1.write_text("这是第一份文档的内容。", encoding="utf-8")
            parsed = parse_documents([f1], ["doc1.txt"])
            self.assertEqual(parsed.filename, "doc1.txt")
            self.assertEqual(len(parsed.blocks), 1)

    def test_parse_documents_multi(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f1 = Path(tmpdir) / "doc1.txt"
            f1.write_text("文档一内容。", encoding="utf-8")
            f2 = Path(tmpdir) / "doc2.txt"
            f2.write_text("文档二内容。", encoding="utf-8")
            parsed = parse_documents([f1, f2], ["doc1.txt", "doc2.txt"])
            self.assertTrue("doc1.txt" in parsed.filename and "doc2.txt" in parsed.filename)
            self.assertEqual(len(parsed.blocks), 2)
            self.assertTrue(parsed.blocks[0].heading.startswith("[doc1.txt]"))
            self.assertTrue(parsed.blocks[1].heading.startswith("[doc2.txt]"))
            self.assertTrue(parsed.parse_metadata.get("multi_document"))
            self.assertEqual(len(parsed.parse_metadata.get("documents", [])), 2)

    def test_draft_user_prompt_multi_document(self):
        manifest = [
            {"filename": "part1.pptx", "start_slide": 1, "end_slide": 10, "page_count": 10},
            {"filename": "part2.pptx", "start_slide": 11, "end_slide": 25, "page_count": 15},
        ]
        prompt = _draft_user_prompt(
            filename="part1.pptx & part2.pptx",
            slide_count=25,
            max_depth=4,
            document_manifest=manifest,
        )
        self.assertIn("输入多文档总数：2 份", prompt)
        self.assertIn("part1.pptx", prompt)
        self.assertIn("part2.pptx", prompt)
        self.assertIn("slide_0001 ~ slide_0010", prompt)
        self.assertIn("slide_0011 ~ slide_0025", prompt)
        self.assertIn("幻灯片总数：25", prompt)

    def test_job_view_context_fields(self):
        job = JobView(
            id="task_123",
            status="running",
            stage="editorial_review",
            progress=50,
            context_tokens=45000,
            max_context_tokens=QWEN38_MAX_CONTEXT_WINDOW_TOKENS,
            context_usage=45000 / QWEN38_MAX_CONTEXT_WINDOW_TOKENS,
        )
        self.assertEqual(job.context_tokens, 45000)
        self.assertEqual(
            job.max_context_tokens,
            QWEN38_MAX_CONTEXT_WINDOW_TOKENS,
        )
        self.assertAlmostEqual(job.context_usage, 0.045, places=3)

    async def test_compact_editorial_context(self):
        mock_client = MagicMock()
        mock_client.complete_json = AsyncMock(
            return_value={"summary": "压缩后的核心审稿共识与图谱骨架摘要。"}
        )

        mindmap = EditorialMindMap(
            title="多文档课程导图",
            editorial_brief=EditorialBrief(
                learning_goal="掌握多文档知识体系",
                audience="测试受众",
                organizing_principle="按主题结构展开",
                level_semantics=["根主题", "子主题"],
                importance_policy="保留关键概念与定义",
                pruning_policy="精简冗余背景描述",
            ),
            nodes=[
                SingleShotNode(id="root", name="课程核心", definition="核心知识体系", role="root", parent_id=None, depth=0, source_slides=[1]),
                SingleShotNode(id="n1", name="子模块一", definition="子模块定义", role="topic", depth=1, parent_id="root", source_slides=[1, 2]),
            ],
        )

        summary, tokens_after = await _compact_editorial_context(
            client=mock_client,
            model="qwen3.8-flash",
            current=mindmap,
            decisions=[],
            issues=[],
            filename="doc1.pptx & doc2.pptx",
            current_tokens=850000,
            max_tokens=QWEN38_MAX_INPUT_TOKENS_WITH_THINKING,
            output_tokens=2_000,
        )

        self.assertIn("压缩后的核心审稿共识", summary)
        mock_client.complete_json.assert_awaited_once()
        self.assertEqual(
            mock_client.complete_json.await_args.kwargs["max_tokens"],
            2_000,
        )
        self.assertEqual(
            mock_client.complete_json.await_args.kwargs[
                "max_completion_tokens"
            ],
            2_000,
        )
        self.assertEqual(
            mock_client.complete_json.await_args.kwargs["model"],
            "qwen3.8-flash",
        )
        # Industry convention ~30%
        self.assertEqual(
            tokens_after,
            int(QWEN38_MAX_INPUT_TOKENS_WITH_THINKING * 0.30),
        )


if __name__ == "__main__":
    unittest.main()
