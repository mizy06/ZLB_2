from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from backend.app.agent_prompts import (
    ARBITER_PROMPT,
    BRANCH_EXTRACTOR_PROMPT,
    PARENT_VERIFIER_PROMPT,
    THEME_SYNTHESIZER_PROMPT,
    VISUAL_ANALYZER_PROMPT,
)
from backend.app.model_provider import SYSTEM_PROMPT as MODEL_SYSTEM_PROMPT
from backend.app.pdf_layout_knowledge import (
    CHANDRA_LAYOUT_SYSTEM_PROMPT,
    DOTS_LAYOUT_SYSTEM_PROMPT,
    LAYOUT_NODE_SYSTEM_PROMPT,
)
from backend.app.pdf_page_knowledge import PDF_PAGE_KNOWLEDGE_PROMPT
from backend.app.pdf_page_transcription import PDF_PAGE_TRANSCRIPTION_PROMPT
from backend.tools.pdf_layout_ab import (
    CANARY_PAGES,
    EXPECTED_FORMULAS,
    REQUIRED_TEXT,
)


class PromptQualityContractTDDTests(unittest.TestCase):
    def test_production_prompts_do_not_contain_canary_answers(self):
        prompts = "\n".join(
            (
                MODEL_SYSTEM_PROMPT,
                THEME_SYNTHESIZER_PROMPT,
                BRANCH_EXTRACTOR_PROMPT,
                PARENT_VERIFIER_PROMPT,
                ARBITER_PROMPT,
                VISUAL_ANALYZER_PROMPT,
                PDF_PAGE_TRANSCRIPTION_PROMPT,
                PDF_PAGE_KNOWLEDGE_PROMPT,
                DOTS_LAYOUT_SYSTEM_PROMPT,
                CHANDRA_LAYOUT_SYSTEM_PROMPT,
                LAYOUT_NODE_SYSTEM_PROMPT,
            )
        )
        compact_prompt = "".join(prompts.split())

        for page, formulas in EXPECTED_FORMULAS.items():
            for formula in formulas:
                with self.subTest(page=page, formula=formula):
                    self.assertNotIn(
                        "".join(formula.split()),
                        compact_prompt,
                    )
        for page, required_items in REQUIRED_TEXT.items():
            for required in required_items:
                with self.subTest(page=page, required=required):
                    self.assertNotIn(
                        "".join(required.split()),
                        compact_prompt,
                    )
        for benchmark_fragment in (
            "10^-6",
            "10^6",
            ">10^14W",
            "P>10^14W",
        ):
            with self.subTest(fragment=benchmark_fragment):
                self.assertNotIn(
                    benchmark_fragment,
                    compact_prompt,
                )

        oracle_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "quantum_92page_26page_quality_oracle.json"
        )
        oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
        for page, assertions in oracle["pages"].items():
            expected_items = (
                assertions["canonical_formulas"]
                + assertions["required_text"]
            )
            for expected in expected_items:
                with self.subTest(page=page, expected=expected):
                    self.assertNotIn(
                        "".join(expected.split()),
                        compact_prompt,
                    )

    def test_production_code_has_no_canary_page_specific_branches(self):
        app_root = Path(__file__).resolve().parents[1] / "app"
        canary_pages = set(CANARY_PAGES)

        for source in app_root.rglob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                names = {
                    child.id.casefold()
                    for child in ast.walk(node)
                    if isinstance(child, ast.Name)
                }
                attributes = {
                    child.attr.casefold()
                    for child in ast.walk(node)
                    if isinstance(child, ast.Attribute)
                }
                if not any(
                    "page" in name for name in names | attributes
                ):
                    continue
                compared_pages = {
                    child.value
                    for child in ast.walk(node)
                    if isinstance(child, ast.Constant)
                    and isinstance(child.value, int)
                    and not isinstance(child.value, bool)
                }
                with self.subTest(
                    source=source.name,
                    line=node.lineno,
                ):
                    self.assertTrue(
                        canary_pages.isdisjoint(compared_pages),
                        "production code branches on a canary page number",
                    )

    def test_production_modules_do_not_import_canary_oracles(self):
        app_root = Path(__file__).resolve().parents[1] / "app"

        for source in app_root.rglob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            imported_modules: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_modules.extend(
                        alias.name for alias in node.names
                    )
                elif isinstance(node, ast.ImportFrom):
                    imported_modules.append(node.module or "")
            with self.subTest(source=source.name):
                self.assertFalse(
                    any(
                        module.endswith("tools.pdf_layout_ab")
                        or module.endswith("pdf_layout_ab")
                        for module in imported_modules
                    )
                )

    def test_branch_prompt_requires_atomic_source_faithful_claims(self):
        compact_prompt = "".join(BRANCH_EXTRACTOR_PROMPT.split())
        required_contracts = [
            "原文逐字可核验",
            "公式、数字、正负号、上下标、单位和比值",
            "不得猜测、补全、改写或交换等式两边",
            "名词性、自足",
            "章节标题、句子开头、连接词、图注",
            "实际知识载荷",
            "“有公式”“有列表”“示意图”",
            "同一命题",
            "一个节点",
        ]

        for contract in required_contracts:
            with self.subTest(contract=contract):
                self.assertIn("".join(contract.split()), compact_prompt)

    def test_visual_prompt_suppresses_axes_photos_and_text_duplicates(self):
        compact_prompt = "".join(VISUAL_ANALYZER_PROMPT.split())
        required_contracts = [
            "纯坐标轴",
            "刻度",
            "人物照片",
            "附近文字",
            "同一命题",
            "attach_as_media",
            "实际公式、数值、变量关系或可复述结论",
        ]

        for contract in required_contracts:
            with self.subTest(contract=contract):
                self.assertIn("".join(contract.split()), compact_prompt)

    def test_layout_node_prompt_requires_publishable_labels(self):
        compact_prompt = "".join(LAYOUT_NODE_SYSTEM_PROMPT.split())
        required_contracts = [
            "2..48",
            "名词性",
            "单行",
            "章节编号",
            "句末标点",
            "formula_index",
        ]

        for contract in required_contracts:
            with self.subTest(contract=contract):
                self.assertIn("".join(contract.split()), compact_prompt)


if __name__ == "__main__":
    unittest.main()
