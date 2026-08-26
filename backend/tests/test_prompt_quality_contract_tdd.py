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
            "正在学习这门课程的学生",
            "原文逐字可核验",
            "公式、数字、正负号、上下标、单位和比值",
            "不得猜测、补全、改写或交换等式两边",
            "最小完整知识结论",
            "对象、属性、数值、单位、适用条件、因果方向或例外",
            "不得只写“丙醛沸点”“反应条件”“影响因素”",
            "48个字符内且不带句末标点",
            "无需再查原文",
            "完整不等于补充材料之外的教材常识",
            "每个事实断言",
            "不得自行补充原因、机理、用途或评价",
            "章节标题、句子开头、连接词、图注",
            "实际知识载荷",
            "“有公式”“有列表”“示意图”",
            "同一命题",
            "一个节点",
            "same_path_upper_nodes",
            "other_path_upper_nodes",
            "same_section_nodes",
            "不能作为事实证据",
            "同级竞争总结",
            "完整表达一枝且只能表达一枝",
            "不得把可分别成立、可分别归属的",
            "唯一强制逐字输出原文的字段",
            "不要为了逐字复刻PPT整句",
            "封闭的父级语义区域",
            "子节点是父节点范围内的类别、组成、步骤、属性、实例或具体结论",
            "不构成归属关系",
            "无越界的完整覆盖",
            "彼此职责互斥并保持相近粒度",
            "继续拆分后会明显小于其他同级节点",
            "当前branch是最终叶分支",
            "不必强行压缩成短词",
            "短词或短术语本身就能完整教会一个从未学过该知识的学生",
            "必须改写为包含必要对象、条件、关系或结论的完整解释性短语",
            "terminal_gold_gate",
            "name_teaches_novice",
            "no_further_bullet_decomposition",
            "minimum_knowledge_atom",
            "严格的或关系",
            "两个终止条件都为false时必须继续拆分",
            "一至三句精准阐释",
            "联网检索确有必要",
            "外部知识用于definition的背景解释",
            "不能据此改变原文核心结论、公式、数值、单位、条件或因果方向",
            "discarded_units",
            "边缘、科普性或纯介绍性",
            "不得因为内容难解释、证据不清、公式复杂、输出预算不足",
        ]

        for contract in required_contracts:
            with self.subTest(contract=contract):
                self.assertIn("".join(contract.split()), compact_prompt)

    def test_theme_prompt_avoids_competing_overview_branches(self):
        compact_prompt = "".join(THEME_SYNTHESIZER_PROMPT.split())
        required_contracts = [
            "一级主题之间必须职责互斥",
            "不能让一个主题吞并明显属于另一个主题的内容",
            "题名单元应并入承载其正文知识的实质主题",
            "不得为了覆盖题名单元单独创建",
            "“概述”“导论”“基础知识”",
            "重复根名称的机械分支",
            "形成完整分区",
            "合起来全覆盖",
            "单个主题不超出根主题",
            "必须且只能出现在一个一级主题",
            "完整表达一枝且只能表达一枝",
            "不得用“A、B和C”“X及Y”",
            "与其他一级主题规模相当的独立分枝",
            "同一分类层面和相近语义粒度",
        ]

        for contract in required_contracts:
            with self.subTest(contract=contract):
                self.assertIn("".join(contract.split()), compact_prompt)

    def test_parent_prompts_require_strict_scope_containment(self):
        for prompt_name, prompt in (
            ("verifier", PARENT_VERIFIER_PROMPT),
            ("arbiter", ARBITER_PROMPT),
        ):
            compact_prompt = "".join(prompt.split())
            required_contracts = [
                "全部语义",
                "父节点",
                "恰好高一层",
                "同义",
                "同粒度",
                "因果",
                "先后",
                "依赖",
                "用途",
                "对比",
                "A、B和C",
                "direct_parent",
            ]
            for contract in required_contracts:
                with self.subTest(
                    prompt=prompt_name,
                    contract=contract,
                ):
                    self.assertIn(
                        "".join(contract.split()),
                        compact_prompt,
                    )

    def test_source_prompts_keep_verbatim_text_in_evidence_only(self):
        branch_prompt = "".join(BRANCH_EXTRACTOR_PROMPT.split())
        page_prompt = "".join(PDF_PAGE_KNOWLEDGE_PROMPT.split())

        self.assertIn(
            "excerpt是唯一强制逐字输出原文的字段",
            branch_prompt,
        )
        self.assertIn(
            "evidence_text必须是页面中的连续原文",
            page_prompt,
        )
        self.assertIn(
            "这是唯一强制逐字抄录原文的字段",
            page_prompt,
        )
        self.assertIn(
            "name和definition应做受证据约束的语义压缩",
            page_prompt,
        )
        for contract in (
            "短词或短术语本身就能完整教会一个从未学过该知识的学生",
            "terminal_gold_gate",
            "name_teaches_novice",
            "no_further_bullet_decomposition",
            "minimum_knowledge_atom",
            "后两项是严格或关系",
            "O/OH/R/Cl",
            "失去键线",
        ):
            with self.subTest(contract=contract):
                self.assertIn(
                    "".join(contract.split()),
                    page_prompt,
                )

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
            "单行",
            "章节编号",
            "句末标点",
            "formula_index",
            "从未学过该知识的学生",
            "terminal_gold_gate",
            "name_teaches_novice",
            "no_further_bullet_decomposition",
            "minimum_knowledge_atom",
            "严格或关系",
            "O/OH/R/Cl",
        ]

        for contract in required_contracts:
            with self.subTest(contract=contract):
                self.assertIn("".join(contract.split()), compact_prompt)


if __name__ == "__main__":
    unittest.main()
