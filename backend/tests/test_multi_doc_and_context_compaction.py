import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from backend.app.document_parser import parse_documents
from backend.app.editorial_ppt_pipeline import (
    _draft_user_prompt,
    _compact_editorial_context,
    EditorialMindMap,
    EditorialBrief,
)
from backend.app.single_shot_ppt_pipeline import SingleShotNode
from backend.app.schemas import JobView


class TestMultiDocAndContextCompaction(unittest.IsolatedAsyncioTestCase):
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
            max_context_tokens=131072,
            context_usage=45000 / 131072,
        )
        self.assertEqual(job.context_tokens, 45000)
        self.assertEqual(job.max_context_tokens, 131072)
        self.assertAlmostEqual(job.context_usage, 0.3433, places=3)

    async def test_compact_editorial_context(self):
        mock_client = MagicMock()
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock(message=MagicMock(content="压缩后的核心审稿共识与图谱骨架摘要。"))]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

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
            model="qwen3.8-max",
            current=mindmap,
            decisions=[],
            issues=[],
            filename="doc1.pptx & doc2.pptx",
            current_tokens=115000,
            max_tokens=131072,
        )

        self.assertIn("压缩后的核心审稿共识", summary)
        # Industry convention ~30%
        self.assertEqual(tokens_after, int(131072 * 0.30))


if __name__ == "__main__":
    unittest.main()
