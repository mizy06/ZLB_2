from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import document_parser


class _FakePage:
    def __init__(self, text: str):
        self.text = text

    def extract_text(self, **kwargs):
        return self.text


class PdfHeadingContinuityTDDTests(unittest.TestCase):
    def test_pdf_blocks_inherit_current_heading_and_switch_on_new_heading(self):
        pages = [
            _FakePage("课程导入\n本页尚未进入正式章节。"),
            _FakePage("第28章 原子中的电子\n本章研究原子结构。"),
            _FakePage("玻尔模型的适用范围\n这里只是普通正文首行。"),
            _FakePage("§28.1 氢原子的量子力学处理\n定态薛定谔方程。"),
            _FakePage("径向方程与角向方程\n继续讲解上一节内容。"),
            _FakePage(
                "*§28.3 微观粒子的不可分辨性，\n"
                "费米子和玻色子\n交换对称性。"
            ),
            _FakePage("全同粒子体系\n继续讲解交换对称性。"),
        ]
        reader = type("_Reader", (), {"pages": pages})()

        with patch.object(document_parser, "PdfReader", return_value=reader):
            blocks = document_parser._parse_pdf(Path("fixture.pdf"))

        self.assertEqual(
            [block.heading for block in blocks],
            [
                None,
                "第28章 原子中的电子",
                "第28章 原子中的电子",
                "§28.1 氢原子的量子力学处理",
                "§28.1 氢原子的量子力学处理",
                "§28.3 微观粒子的不可分辨性，费米子和玻色子",
                "§28.3 微观粒子的不可分辨性，费米子和玻色子",
            ],
        )

    def test_ordinary_first_lines_never_create_or_replace_heading_context(self):
        ordinary_before_heading = "课程导入\n本页尚未进入正式章节。"
        ordinary_after_heading = "径向方程与角向方程\n继续讲解上一节内容。"
        pages = [
            _FakePage(ordinary_before_heading),
            _FakePage("§28.5 激光\n激光的基本原理。"),
            _FakePage(ordinary_after_heading),
        ]
        reader = type("_Reader", (), {"pages": pages})()

        with patch.object(document_parser, "PdfReader", return_value=reader):
            blocks = document_parser._parse_pdf(Path("fixture.pdf"))

        self.assertIsNone(
            document_parser._infer_pdf_heading(ordinary_before_heading)
        )
        self.assertIsNone(
            document_parser._infer_pdf_heading(ordinary_after_heading)
        )
        self.assertEqual(
            [block.heading for block in blocks],
            [None, "§28.5 激光", "§28.5 激光"],
        )


if __name__ == "__main__":
    unittest.main()
