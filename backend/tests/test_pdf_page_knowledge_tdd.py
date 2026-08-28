from __future__ import annotations

import hashlib
import re
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from pydantic import ValidationError

from backend.app.agents import RoleRuntime, run_branch_teams
from backend.app.architecture_schemas import BranchPlan
from backend.app.blackboard import SQLiteBlackboard
from backend.app.mindmap_engine.schemas import RenderResponse, RenderedPage
from backend.app.model_provider import ModelProviderError
from backend.app.pdf_layout_knowledge import (
    LayoutKnowledgePageResult,
    PAGE_LAYOUT_NODE_SCHEMA_VERSION,
    PAGE_LAYOUT_SCHEMA_VERSION,
    PageLayoutExtraction,
)
from backend.app.pdf_page_knowledge import (
    PAGE_KNOWLEDGE_SCHEMA_VERSION,
    PageKnowledgeExtraction,
    PageKnowledgeNode,
    _input_hash,
    extract_pdf_page_knowledge,
    page_knowledge_issues,
)
from backend.app.schemas import ParsedDocument, SourceBlock


TERMINAL_GOLD_GATE = {
    "name_teaches_novice": True,
    "no_further_bullet_decomposition": True,
    "minimum_knowledge_atom": False,
}


class _FakePageKnowledgeClient:
    supports_multimodal = True

    def __init__(
        self,
        responses: dict[int, list[dict | Exception]],
    ):
        self.responses = {
            page: list(items)
            for page, items in responses.items()
        }
        self.calls: list[dict] = []

    async def complete_multimodal_json(self, **kwargs):
        self.calls.append(kwargs)
        match = re.search(r"提取第 (\d+) 页", kwargs["user_prompt"])
        if not match:
            raise AssertionError("page number missing from prompt")
        page = int(match.group(1))
        response = self.responses[page].pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _NoBranchExtractionClient:
    def __init__(self):
        self.calls = 0

    async def complete_json(self, **_kwargs):
        self.calls += 1
        raise AssertionError("direct page nodes must bypass branch extraction")


class _FakeLayoutKnowledgeClient:
    supports_multimodal = True

    def __init__(self, layout_responses: dict[int, list[dict]]):
        self.layout_responses = {
            page: list(items)
            for page, items in layout_responses.items()
        }
        self.layout_calls: list[int] = []
        self.node_calls: list[int] = []

    async def complete_multimodal_json(self, **kwargs):
        match = re.search(r"解析第 (\d+) 页", kwargs["user_prompt"])
        if not match:
            raise AssertionError("layout page number missing from prompt")
        page = int(match.group(1))
        self.layout_calls.append(page)
        return self.layout_responses[page].pop(0)

    async def complete_json(self, **kwargs):
        match = re.search(r"从第 (\d+) 页", kwargs["user_prompt"])
        if not match:
            raise AssertionError("node page number missing from prompt")
        page = int(match.group(1))
        self.node_calls.append(page)
        return {
            "page": page,
            "complete": True,
            "confidence": 0.98,
            "heading_block_id": "",
            "has_knowledge": True,
            "no_knowledge_reason": "",
            "nodes": [
                {
                    "temp_id": f"formula-{page}",
                    "name": "Δν/ν≈10^-6",
                    "type": "formula",
                    "role": "formula",
                    "block_id": f"p{page:04d}:b000",
                    "formula_index": 0,
                    "confidence": 0.98,
                    "terminal_gold_gate": TERMINAL_GOLD_GATE,
                }
            ],
        }


class _FakeAuditedPageKnowledgeClient(_FakePageKnowledgeClient):
    def __init__(
        self,
        *,
        direct_responses: dict[int, list[dict | Exception]],
        layout_responses: dict[int, list[dict]],
    ):
        super().__init__(direct_responses)
        self.layout_responses = {
            page: list(items)
            for page, items in layout_responses.items()
        }
        self.layout_calls: list[int] = []
        self.node_calls: list[int] = []

    async def complete_multimodal_json(self, **kwargs):
        prompt = kwargs["user_prompt"]
        layout_match = re.search(r"解析第 (\d+) 页", prompt)
        if layout_match:
            page = int(layout_match.group(1))
            self.layout_calls.append(page)
            return self.layout_responses[page].pop(0)
        return await super().complete_multimodal_json(**kwargs)

    async def complete_json(self, **kwargs):
        match = re.search(r"从第 (\d+) 页", kwargs["user_prompt"])
        if not match:
            raise AssertionError("node page number missing from prompt")
        page = int(match.group(1))
        self.node_calls.append(page)
        raise AssertionError(
            "successful layout-only audit must not call the node selector"
        )


def _page_payload(
    page: int,
    *,
    confidence: float = 0.98,
    formula_text: str = "Δν/ν≈10^-6",
) -> dict:
    return {
        "page": page,
        "complete": True,
        "confidence": confidence,
        "heading": "激光的纵模",
        "has_knowledge": True,
        "no_knowledge_reason": "",
        "nodes": [
            {
                "temp_id": "relative-linewidth",
                "name": "谱线相对宽度",
                "type": "formula",
                "role": "formula",
                "definition": f"谱线相对宽度满足 {formula_text}",
                "evidence_text": formula_text,
                "formula_text": formula_text,
                "formula_latex": (
                    r"\frac{\Delta\nu}{\nu}\approx 10^{-6}"
                ),
                "bbox": [0.1, 0.2, 0.7, 0.2],
                "confidence": confidence,
                "terminal_gold_gate": TERMINAL_GOLD_GATE,
            }
        ],
    }


def _short_relation_payload(page: int) -> dict:
    return {
        "page": page,
        "complete": True,
        "confidence": 0.98,
        "heading": "角动量和磁矩",
        "has_knowledge": True,
        "no_knowledge_reason": "",
        "nodes": [
            {
                "temp_id": "relationship",
                "name": "角动量和磁矩的关系",
                "type": "concept",
                "role": "other",
                "definition": (
                    "角动量 L⃗ 与磁矩 μ⃗ 之间存在对应关系，"
                    "记为 L⃗ → μ⃗。"
                ),
                "evidence_text": "角动量和磁矩的关系",
                "formula_text": "",
                "formula_latex": "",
                "bbox": [0.1, 0.1, 0.5, 0.1],
                "confidence": 0.98,
                "terminal_gold_gate": TERMINAL_GOLD_GATE,
            }
        ],
    }


def _short_relation_layout_payload(page: int) -> dict:
    return {
        "page": page,
        "complete": True,
        "confidence": 0.98,
        "coordinate_space": "normalized_1000",
        "blocks": [
            {
                "bbox": [100, 100, 600, 180],
                "category": "Text",
                "text": "角动量和磁矩的关系",
                "confidence": 0.98,
            },
            {
                "bbox": [200, 220, 500, 300],
                "category": "Formula",
                "text": "L⃗ → μ⃗",
                "formulas": [
                    {
                        "text": "L⃗ → μ⃗",
                        "latex": r"\vec{L}\rightarrow\vec{\mu}",
                    }
                ],
                "confidence": 0.98,
            },
        ],
    }


def _concept_payload(
    page: int,
    *,
    confidence: float = 0.98,
) -> dict:
    return {
        "page": page,
        "complete": True,
        "confidence": confidence,
        "heading": "普通概念",
        "has_knowledge": True,
        "no_knowledge_reason": "",
        "nodes": [
            {
                "temp_id": "concept",
                "name": "稳定的普通概念",
                "type": "concept",
                "role": "definition",
                "definition": "稳定的普通概念具有清晰且连续的定义。",
                "evidence_text": "稳定的普通概念具有清晰且连续的定义。",
                "bbox": [0.1, 0.1, 0.6, 0.1],
                "confidence": confidence,
                "terminal_gold_gate": TERMINAL_GOLD_GATE,
            }
        ],
    }


def _algebra_node(
    *,
    temp_id: str,
    name: str,
    formula_text: str,
    formula_latex: str,
    y: float,
) -> dict:
    return {
        "temp_id": temp_id,
        "name": name,
        "type": "formula",
        "role": "formula",
        "definition": f"{name}满足 {formula_text}",
        "evidence_text": formula_text,
        "formula_text": formula_text,
        "formula_latex": formula_latex,
        "bbox": [0.1, y, 0.5, 0.1],
        "confidence": 0.98,
        "terminal_gold_gate": TERMINAL_GOLD_GATE,
    }


def _algebra_payload(page: int, nodes: list[dict]) -> dict:
    return {
        "page": page,
        "complete": True,
        "confidence": 0.98,
        "heading": "数学关系",
        "has_knowledge": True,
        "no_knowledge_reason": "",
        "nodes": nodes,
    }


def _no_knowledge_payload(page: int) -> dict:
    return {
        "page": page,
        "complete": True,
        "confidence": 0.98,
        "heading": "课程目录",
        "has_knowledge": False,
        "no_knowledge_reason": (
            "页面仅含目录、章节标题和导航，不含可发布知识事实。"
        ),
        "nodes": [],
    }


def _rendered_fixture(
    root: Path,
    *,
    page_count: int,
) -> tuple[RenderResponse, Path]:
    data_root = root / "data"
    render_id = "page-knowledge-fixture"
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
        document_id="doc-page-knowledge",
        filename="fixture.pdf",
        file_type="pdf",
        title="公式课程",
        blocks=[],
        parse_metadata={"pdf_page_count": page_count},
    )


def _runtime(client) -> RoleRuntime:
    return RoleRuntime(
        provider="qwen",
        model="qwen3.8-max-preview",
        client=client,
        available=True,
    )


async def _run_direct_page_fixture(
    responses: list[dict | Exception],
    *,
    max_page_attempts: int,
):
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        rendered, data_root = _rendered_fixture(root, page_count=1)
        blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
        run_id = blackboard.start_run(
            run_id="run_partial_page",
            task_id="task_partial_page",
            mode="precision",
        )
        client = _FakePageKnowledgeClient({1: responses})
        result = await extract_pdf_page_knowledge(
            document=_document(1),
            rendered=rendered,
            runtime=_runtime(client),
            data_root=data_root,
            checkpoint_store=blackboard,
            run_id=run_id,
            source_sha256="source-sha",
            prompt_version="page-knowledge-prompt-v1",
            render_dpi=192,
            min_confidence=0.85,
            concurrency=1,
            max_page_attempts=max_page_attempts,
        )
        checkpoint = blackboard.load_checkpoint(
            run_id,
            "page_knowledge:0001",
        )
        return result, checkpoint, list(client.calls)


def _layout_payload(page: int, *, confidence: float = 0.98) -> dict:
    return {
        "page": page,
        "complete": True,
        "confidence": confidence,
        "coordinate_space": "normalized_1000",
        "blocks": [
            {
                "bbox": [100, 200, 800, 400],
                "category": "Formula",
                "text": "Δν/ν≈10^-6",
                "latex": r"\frac{\Delta\nu}{\nu}\approx10^{-6}",
                "confidence": confidence,
            }
        ],
    }


def _materialized_layout(
    page: int,
    *,
    confidence: float = 0.98,
) -> PageLayoutExtraction:
    return PageLayoutExtraction(
        profile="dots",
        page=page,
        complete=True,
        confidence=confidence,
        blocks=[
            {
                "block_id": f"p{page:04d}:b000",
                "category": "formula",
                "text": "Δν/ν≈10^-6",
                "formulas": [
                    {
                        "text": "Δν/ν≈10^-6",
                        "latex": (
                            r"\frac{\Delta\nu}{\nu}\approx10^{-6}"
                        ),
                    }
                ],
                "bbox": [0.1, 0.2, 0.7, 0.2],
                "confidence": confidence,
            }
        ],
    )


class PdfPageKnowledgeSchemaTDDTests(unittest.TestCase):
    def test_terminal_gold_gate_requires_novice_name_and_or_stop_condition(self):
        missing_gate = _page_payload(1)
        missing_gate["nodes"][0].pop("terminal_gold_gate")
        extraction = PageKnowledgeExtraction.model_validate(missing_gate)
        self.assertIn(
            "node_0:terminal_gold_gate_missing",
            page_knowledge_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
        )

        failed_or_gate = _page_payload(1)
        failed_or_gate["nodes"][0]["terminal_gold_gate"] = {
            "name_teaches_novice": True,
            "no_further_bullet_decomposition": False,
            "minimum_knowledge_atom": False,
        }
        with self.assertRaises(ValidationError):
            PageKnowledgeExtraction.model_validate(failed_or_gate)

    def test_formula_nodes_require_canonical_latex_and_valid_bbox(self):
        with self.assertRaises(ValidationError):
            PageKnowledgeNode(
                temp_id="formula",
                name="谱线相对宽度",
                type="formula",
                role="formula",
                definition="谱线相对宽度满足 10^-6",
                evidence_text="10^-6",
                formula_text="10^-6",
                formula_latex="",
                bbox=[0.1, 0.1, 0.5, 0.2],
                confidence=0.9,
            )
        with self.assertRaises(ValidationError):
            PageKnowledgeNode(
                temp_id="formula",
                name="谱线相对宽度",
                type="formula",
                role="formula",
                definition="谱线相对宽度满足 10^-6",
                evidence_text="10^-6",
                formula_text="10^-6",
                formula_latex=r"10^{-6}",
                bbox=[0.8, 0.8, 0.3, 0.3],
                confidence=0.9,
            )

    def test_quality_gate_keeps_signed_power_and_rejects_malformed_claim(self):
        valid = PageKnowledgeExtraction.model_validate(_page_payload(1))
        malformed = PageKnowledgeExtraction.model_validate(
            _page_payload(1, formula_text="Δν/ν≈10^6")
        )

        self.assertEqual(
            page_knowledge_issues(
                valid,
                expected_page=1,
                min_confidence=0.85,
            ),
            (),
        )
        self.assertIn(
            "node_0:missing_negative_exponent",
            page_knowledge_issues(
                malformed,
                expected_page=1,
                min_confidence=0.85,
            ),
        )

    def test_quality_gate_rejects_formula_decoration_mismatch(self):
        payload = _algebra_payload(
            1,
            [
                _algebra_node(
                    temp_id="angular-momentum",
                    name="角动量算符模方",
                    formula_text=(
                        "L̂^2=L̂·L̂=L̂_x^2+L̂_y^2+L̂_z^2"
                    ),
                    formula_latex=(
                        r"\hat{L}^2=\hat{\vec{L}}\cdot"
                        r"\hat{\vec{L}}="
                        r"\hat{L}_x^2+\hat{L}_y^2+\hat{L}_z^2"
                    ),
                    y=0.2,
                )
            ],
        )
        mismatch = PageKnowledgeExtraction.model_validate(payload)

        self.assertIn(
            "node_0:formula_text_latex_decoration_mismatch",
            page_knowledge_issues(
                mismatch,
                expected_page=1,
                min_confidence=0.85,
            ),
        )

        payload["nodes"][0].update(
            {
                "definition": (
                    "角动量算符模方满足 "
                    "L̂^2=L̂⃗·L̂⃗=L̂_x^2+L̂_y^2+L̂_z^2"
                ),
                "evidence_text": (
                    "L̂^2=L̂⃗·L̂⃗=L̂_x^2+L̂_y^2+L̂_z^2"
                ),
                "formula_text": (
                    "L̂^2=L̂⃗·L̂⃗=L̂_x^2+L̂_y^2+L̂_z^2"
                ),
            }
        )
        matching = PageKnowledgeExtraction.model_validate(payload)

        self.assertNotIn(
            "node_0:formula_text_latex_decoration_mismatch",
            page_knowledge_issues(
                matching,
                expected_page=1,
                min_confidence=0.85,
            ),
        )

    def test_quality_gate_rejects_labels_the_branch_gate_would_drop(self):
        payload = _page_payload(4)
        payload["nodes"][0].update(
            {
                "name": "后来发现在其他波段还存在谱线。",
                "type": "result",
                "role": "other",
                "definition": "后来发现在其他波段还存在谱线。",
                "evidence_text": "后来发现在其他波段还存在谱线。",
                "formula_text": "",
                "formula_latex": "",
            }
        )
        extraction = PageKnowledgeExtraction.model_validate(payload)

        issues = page_knowledge_issues(
            extraction,
            expected_page=4,
            min_confidence=0.85,
        )

        self.assertIn("node_0:label_sentence_fragment", issues)
        self.assertIn("node_0:field_reextract_candidate", issues)

    def test_formula_evidence_allows_typography_but_keeps_exponent_sign(self):
        payload = _page_payload(84)
        payload["nodes"][0].update(
            {
                "name": "光频率计算",
                "definition": (
                    "频率ν=c/λ，代入c=3×10^8、"
                    "λ=0.6328×10^-6，得ν≈5×10^14 Hz。"
                ),
                "evidence_text": (
                    "ν = c/λ = 3×10⁸/(0.6328×10⁻⁶) "
                    "≈ 5×10¹⁴Hz"
                ),
                "formula_text": (
                    "ν = c/λ = (3×10^8)/(0.6328×10^-6) "
                    "≈ 5×10^14 Hz"
                ),
                "formula_latex": (
                    r"\nu=\frac{c}{\lambda}="
                    r"\frac{3\times10^{8}}{0.6328\times10^{-6}}"
                    r"\approx5\times10^{14}\,\mathrm{Hz}"
                ),
            }
        )
        extraction = PageKnowledgeExtraction.model_validate(payload)

        self.assertEqual(
            page_knowledge_issues(
                extraction,
                expected_page=84,
                min_confidence=0.85,
            ),
            (),
        )

        payload["nodes"][0].update(
            {
                "definition": "频率计算错误地写成10^6。",
                "evidence_text": "频率计算实际为10⁻⁶。",
                "formula_text": "10^6",
                "formula_latex": r"10^{6}",
            }
        )
        malformed = PageKnowledgeExtraction.model_validate(payload)
        self.assertIn(
            "node_0:formula_not_in_evidence",
            page_knowledge_issues(
                malformed,
                expected_page=84,
                min_confidence=0.85,
            ),
        )

    def test_formula_evidence_normalizes_unicode_prime_marks(self):
        payload = _page_payload(6)
        payload["nodes"][0].update(
            {
                "name": "光谱波数关系",
                "definition": (
                    "波数满足ν̃=1/λ=R(1/n²-1/n′²)。"
                ),
                "evidence_text": (
                    "ν̃ = 1/λ = R (1/n² − 1/n′²)"
                ),
                "formula_text": (
                    "ν̃ = 1/λ = R(1/n^2 - 1/n'^2)"
                ),
                "formula_latex": (
                    r"\tilde{\nu}=\frac{1}{\lambda}="
                    r"R\left(\frac{1}{n^2}-\frac{1}{n'^2}\right)"
                ),
            }
        )
        extraction = PageKnowledgeExtraction.model_validate(payload)

        self.assertNotIn(
            "node_0:formula_not_in_evidence",
            page_knowledge_issues(
                extraction,
                expected_page=6,
                min_confidence=0.85,
            ),
        )

    def test_formula_evidence_normalizes_subscript_superscript_order(self):
        payload = _page_payload(7)
        payload["nodes"][0].update(
            {
                "name": "抽象算符分量关系",
                "definition": "抽象算符分量满足A_i²+B_j³=C_k⁴。",
                "evidence_text": "A²_i + B³_j = C⁴_k",
                "formula_text": "A_i^2 + B_j^3 = C_k^4",
                "formula_latex": (
                    r"A_i^2 + B_j^3 = C_k^4"
                ),
            }
        )
        extraction = PageKnowledgeExtraction.model_validate(payload)

        self.assertNotIn(
            "node_0:formula_not_in_evidence",
            page_knowledge_issues(
                extraction,
                expected_page=7,
                min_confidence=0.85,
            ),
        )

        payload["nodes"][0].update(
            {
                "definition": "抽象算符分量满足A_i²+B_j³=C_k⁴。",
                "evidence_text": "A²_q + B³_j = C⁴_k",
            }
        )
        mismatched = PageKnowledgeExtraction.model_validate(payload)
        self.assertIn(
            "node_0:formula_not_in_evidence",
            page_knowledge_issues(
                mismatched,
                expected_page=7,
                min_confidence=0.85,
            ),
        )

    def test_dimensionless_ratio_value_does_not_require_a_formula_wrapper(self):
        payload = _page_payload(85)
        payload["nodes"][0].update(
            {
                "name": "超高稳频相对线宽",
                "type": "result",
                "role": "other",
                "definition": (
                    "He-Ne激光器输出激光的Δν/ν在超高稳频条件下"
                    "会小到10^-15。"
                ),
                "evidence_text": (
                    "He-Ne激光器输出激光的 Δν/ν 在超高稳频条件下，"
                    "会小到10⁻¹⁵"
                ),
                "formula_text": "",
                "formula_latex": "",
            }
        )
        extraction = PageKnowledgeExtraction.model_validate(payload)

        self.assertEqual(
            page_knowledge_issues(
                extraction,
                expected_page=85,
                min_confidence=0.85,
            ),
            (),
        )

    def test_formula_evidence_allows_explicit_or_implicit_multiplication(self):
        payload = _page_payload(87)
        payload["nodes"][0].update(
            {
                "name": "纵模频率",
                "definition": "纵模频率满足ν_k=c/λ_k=k·c/(2nL)。",
                "evidence_text": "ν_k = c/λ_k = kc/2nL",
                "formula_text": "ν_k = c/λ_k = k·c/(2nL)",
                "formula_latex": (
                    r"\nu_k=\frac{c}{\lambda_k}="
                    r"\frac{kc}{2nL}"
                ),
            }
        )
        extraction = PageKnowledgeExtraction.model_validate(payload)

        self.assertEqual(
            page_knowledge_issues(
                extraction,
                expected_page=87,
                min_confidence=0.85,
            ),
            (),
        )

    def test_formula_evidence_normalizes_hbar_and_legacy_approximation(self):
        payload = _page_payload(42)
        payload["nodes"][0].update(
            {
                "name": "自旋角动量",
                "definition": "自旋角动量满足S=sqrt(s(s+1)) hbar。",
                "evidence_text": "S = √s(s+1) ℏ",
                "formula_text": "S = sqrt(s(s+1)) hbar",
                "formula_latex": r"S=\sqrt{s(s+1)}\hbar",
            }
        )
        extraction = PageKnowledgeExtraction.model_validate(payload)
        self.assertEqual(
            page_knowledge_issues(
                extraction,
                expected_page=42,
                min_confidence=0.85,
            ),
            (),
        )

        payload = _page_payload(88)
        payload["nodes"][0].update(
            {
                "name": "纵模个数",
                "definition": "纵模个数计算结果约为8。",
                "evidence_text": (
                    "N=Δν/Δν_k=1.3×10⁹/(1.5×10⁸)≅8"
                ),
                "formula_text": (
                    "N=Δν/Δν_k=1.3×10^9/(1.5×10^8)≅8"
                ),
                "formula_latex": (
                    r"N=\frac{\Delta\nu}{\Delta\nu_k}="
                    r"\frac{1.3\times10^{9}}{1.5\times10^{8}}\cong8"
                ),
            }
        )
        extraction = PageKnowledgeExtraction.model_validate(payload)
        self.assertIn("≈8", extraction.nodes[0].formula_text)
        self.assertIn(r"\approx", extraction.nodes[0].formula_latex)
        self.assertEqual(
            page_knowledge_issues(
                extraction,
                expected_page=88,
                min_confidence=0.85,
            ),
            (),
        )

    def test_formula_evidence_ignores_layout_connectors_and_vector_marks(self):
        cases = (
            {
                "name": "并列关系",
                "definition": "a=1且b=a+1。",
                "evidence_text": "a = 1     b = a + 1",
                "formula_text": "a=1; b=a+1",
                "formula_latex": r"a=1;\ b=a+1",
            },
            {
                "name": "条件关系",
                "definition": "x=0时，向量A等于向量B且m=n。",
                "evidence_text": "x = 0时，A = B，m = n",
                "formula_text": "x=0: A⃗=B⃗, m=n",
                "formula_latex": r"x=0:\ \vec{A}=\vec{B},\ m=n",
            },
        )

        for index, fields in enumerate(cases, start=1):
            with self.subTest(case=index):
                payload = _page_payload(index)
                payload["nodes"][0].update(fields)
                extraction = PageKnowledgeExtraction.model_validate(payload)

                self.assertNotIn(
                    "node_0:formula_not_in_evidence",
                    page_knowledge_issues(
                        extraction,
                        expected_page=index,
                        min_confidence=0.85,
                    ),
                )

    def test_simple_inline_condition_does_not_require_formula_wrapper(self):
        payload = _page_payload(9)
        payload["nodes"][0].update(
            {
                "name": "跃迁条件",
                "type": "principle",
                "role": "principle",
                "definition": "当E_i>E_f时发生跃迁。",
                "evidence_text": "当 E_i > E_f 时发生跃迁",
                "formula_text": "",
                "formula_latex": "",
            }
        )
        extraction = PageKnowledgeExtraction.model_validate(payload)

        self.assertNotIn(
            "node_0:formula_contract_missing",
            page_knowledge_issues(
                extraction,
                expected_page=9,
                min_confidence=0.85,
            ),
        )

    def test_multiple_relations_in_one_field_require_formula_wrapper(self):
        payload = _page_payload(9)
        payload["nodes"][0].update(
            {
                "name": "并列约束",
                "type": "principle",
                "role": "principle",
                "definition": "当E_i>E_f且m=n时满足并列约束。",
                "evidence_text": "当 E_i > E_f 且 m = n 时满足并列约束",
                "formula_text": "",
                "formula_latex": "",
            }
        )
        extraction = PageKnowledgeExtraction.model_validate(payload)

        self.assertIn(
            "node_0:formula_contract_missing",
            page_knowledge_issues(
                extraction,
                expected_page=9,
                min_confidence=0.85,
            ),
        )

    def test_result_role_and_unambiguous_corner_bbox_are_normalized(self):
        node = PageKnowledgeNode(
            temp_id="result",
            name="频率间隔结果",
            type="result",
            role="result",
            definition="频率间隔为1.5×10^8 Hz。",
            evidence_text="频率间隔为1.5×10⁸Hz",
            bbox=[0.1, 0.7, 0.8, 0.9],
            confidence=0.92,
        )

        self.assertEqual(node.role, "other")
        self.assertEqual(node.bbox, [0.1, 0.7, 0.7, 0.2])

    def test_formula_cannot_hide_in_a_non_formula_node(self):
        payload = _page_payload(1)
        payload["nodes"][0].update(
            {
                "type": "concept",
                "role": "other",
                "definition": "非聚焦状态 I>10^11 W/m²",
                "evidence_text": "非聚焦状态 I>10^11 W/m²",
                "formula_text": "",
                "formula_latex": "",
            }
        )
        extraction = PageKnowledgeExtraction.model_validate(payload)

        self.assertIn(
            "node_0:formula_contract_missing",
            page_knowledge_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
            ),
        )

    def test_no_knowledge_claim_conflicting_with_parser_signal_is_rejected(self):
        extraction = PageKnowledgeExtraction(
            page=1,
            complete=True,
            confidence=0.98,
            heading="",
            has_knowledge=False,
            no_knowledge_reason="页面仅为装饰",
            nodes=[],
        )

        self.assertIn(
            "no_knowledge_conflicts_parser_signal",
            page_knowledge_issues(
                extraction,
                expected_page=1,
                min_confidence=0.85,
                page_has_text_signal=True,
            ),
        )


class PdfPageKnowledgeRuntimeTDDTests(unittest.IsolatedAsyncioTestCase):
    def test_layout_input_hash_includes_profile_contract_versions(self):
        page = RenderedPage(
            asset_id="page_0001",
            render_id="render",
            filename="page_0001.png",
            url="/page_0001.png",
            page=1,
            width=320,
            height=240,
        )
        common = {
            "source_sha256": "source-sha",
            "page": page,
            "image_sha256": "image-sha",
            "prompt_version": "prompt-v1",
            "provider": "qwen",
            "model": "qwen3.8-max-preview",
        }

        direct = _input_hash(**common)
        direct_with_versions = _input_hash(
            **common,
            profile_schema_versions=("old-layout", "old-nodes"),
        )
        layout_v2 = _input_hash(
            **common,
            extraction_profile="layout_nodes",
            profile_schema_versions=("page-layout-v2", "nodes-v1"),
        )
        layout_v3 = _input_hash(
            **common,
            extraction_profile="layout_nodes",
            profile_schema_versions=("page-layout-v3", "nodes-v1"),
        )

        self.assertEqual(direct, direct_with_versions)
        self.assertNotEqual(layout_v2, layout_v3)

    def test_input_hash_changes_with_prompt_model_and_schema(self):
        page = RenderedPage(
            asset_id="page_0001",
            render_id="render",
            filename="page_0001.png",
            url="/page_0001.png",
            page=1,
            width=320,
            height=240,
        )
        common = {
            "source_sha256": "source-sha",
            "page": page,
            "image_sha256": "image-sha",
            "prompt_version": "prompt-v1",
            "provider": "qwen",
            "model": "qwen3.8-max-preview",
        }
        baseline = _input_hash(**common)

        self.assertNotEqual(
            baseline,
            _input_hash(**{**common, "prompt_version": "prompt-v2"}),
        )
        self.assertNotEqual(
            baseline,
            _input_hash(**{**common, "model": "qwen3.8-max"}),
        )
        self.assertNotEqual(
            baseline,
            _input_hash(
                **common,
                knowledge_schema_version="page-knowledge-v0",
            ),
        )

    async def test_identical_page_checkpoint_is_reused_across_same_owner_runs(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            source_run_id = blackboard.start_run(
                run_id="run_cross_cache_source",
                task_id="task_cross_cache_source",
                mode="precision",
                owner_id="owner-a",
            )
            source_client = _FakePageKnowledgeClient(
                {1: [_page_payload(1)]}
            )
            source = await extract_pdf_page_knowledge(
                document=_document(1),
                rendered=rendered,
                runtime=_runtime(source_client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=source_run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=1,
            )
            target_run_id = blackboard.start_run(
                run_id="run_cross_cache_target",
                task_id="task_cross_cache_target",
                mode="precision",
                owner_id="owner-a",
            )
            target_client = _FakePageKnowledgeClient({})

            target = await extract_pdf_page_knowledge(
                document=_document(1),
                rendered=rendered,
                runtime=_runtime(target_client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=target_run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=1,
            )
            copied = blackboard.load_checkpoint(
                target_run_id,
                "page_knowledge:0001",
            )

        self.assertTrue(source.complete)
        self.assertEqual(source.called_pages, [1])
        self.assertTrue(target.complete)
        self.assertEqual(target.reused_pages, [1])
        self.assertEqual(target.called_pages, [])
        self.assertEqual(target_client.calls, [])
        self.assertEqual(
            copied["reused_from_run_id"],
            source_run_id,
        )
        self.assertEqual(copied["status"], "accepted")

    async def test_layout_nodes_checkpoint_is_reused_across_runs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            source_run_id = blackboard.start_run(
                run_id="run_layout_cross_cache_source",
                task_id="task_layout_cross_cache_source",
                mode="precision",
                owner_id="owner-a",
            )
            source_client = _FakeLayoutKnowledgeClient(
                {1: [_layout_payload(1)]}
            )
            source = await extract_pdf_page_knowledge(
                document=_document(1),
                rendered=rendered,
                runtime=_runtime(source_client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=source_run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=1,
                extraction_profile="layout_nodes",
            )
            target_run_id = blackboard.start_run(
                run_id="run_layout_cross_cache_target",
                task_id="task_layout_cross_cache_target",
                mode="precision",
                owner_id="owner-a",
            )
            target_client = _FakeLayoutKnowledgeClient({})

            target = await extract_pdf_page_knowledge(
                document=_document(1),
                rendered=rendered,
                runtime=_runtime(target_client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=target_run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=1,
                extraction_profile="layout_nodes",
            )
            copied = blackboard.load_checkpoint(
                target_run_id,
                "page_knowledge:layout_nodes:0001",
            )

        self.assertTrue(source.complete)
        self.assertTrue(target.complete)
        self.assertEqual(target.reused_pages, [1])
        self.assertEqual(target.called_pages, [])
        self.assertEqual(target_client.layout_calls, [])
        self.assertEqual(target_client.node_calls, [])
        self.assertEqual(copied["reused_from_run_id"], source_run_id)
        self.assertEqual(
            copied["layout_schema_version"],
            PAGE_LAYOUT_SCHEMA_VERSION,
        )
        self.assertEqual(
            copied["layout_node_schema_version"],
            PAGE_LAYOUT_NODE_SCHEMA_VERSION,
        )
        self.assertIsNotNone(copied["layout"])

    async def test_direct_formula_risk_page_gets_layout_only_audit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_layout_audit",
                task_id="task_layout_audit",
                mode="precision",
            )
            document = _document(1).model_copy(
                update={
                    "parse_metadata": {
                        "pdf_page_count": 1,
                        "pdf_geometry_math": {
                            "attempted_pages": [1],
                            "candidates": [
                                {
                                    "page": 1,
                                    "canonical": "A=B",
                                    "issues": [],
                                }
                            ],
                            "injected_into_text": False,
                        },
                    }
                }
            )
            client = _FakeAuditedPageKnowledgeClient(
                direct_responses={1: [_short_relation_payload(1)]},
                layout_responses={
                    1: [_short_relation_layout_payload(1)]
                },
            )

            result = await extract_pdf_page_knowledge(
                document=document,
                rendered=rendered,
                runtime=_runtime(client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=1,
                extraction_profile="direct_layout_fallback",
            )
            audit_checkpoint = blackboard.load_checkpoint(
                run_id,
                "page_knowledge:layout_audit:0001",
            )
            fallback_checkpoint = blackboard.load_checkpoint(
                run_id,
                "page_knowledge:layout_nodes:0001",
            )

        self.assertTrue(result.complete)
        self.assertEqual(client.layout_calls, [1])
        self.assertEqual(client.node_calls, [])
        self.assertEqual(
            [node.formula_text for node in result.extractions[0].nodes],
            ["", "L⃗ → μ⃗"],
        )
        self.assertEqual(audit_checkpoint["status"], "accepted")
        self.assertIsNone(fallback_checkpoint)
        metadata = result.document.parse_metadata["pdf_page_knowledge"]
        self.assertEqual(metadata["layout_audited_pages"], [1])
        self.assertEqual(metadata["layout_audit_failed_pages"], [])
        self.assertEqual(metadata["layout_audit_called_pages"], [1])

    async def test_original_geometry_page_mapping_triggers_canary_audit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_mapped_layout_audit",
                task_id="task_mapped_layout_audit",
                mode="precision",
            )
            document = _document(1).model_copy(
                update={
                    "parse_metadata": {
                        "pdf_page_count": 1,
                        "original_page_map": {"1": 34},
                        "pdf_geometry_math": {
                            "attempted_pages": [34],
                            "candidates": [
                                {
                                    "page": 34,
                                    "canonical": "A=B",
                                    "issues": [],
                                }
                            ],
                            "injected_into_text": False,
                        },
                    }
                }
            )
            client = _FakeAuditedPageKnowledgeClient(
                direct_responses={1: [_short_relation_payload(1)]},
                layout_responses={
                    1: [_short_relation_layout_payload(1)]
                },
            )

            result = await extract_pdf_page_knowledge(
                document=document,
                rendered=rendered,
                runtime=_runtime(client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=1,
                extraction_profile="direct_layout_fallback",
            )

        self.assertTrue(result.complete)
        self.assertEqual(client.layout_calls, [1])
        metadata = result.document.parse_metadata["pdf_page_knowledge"]
        self.assertEqual(metadata["layout_audited_pages"], [1])

    async def test_unselected_original_geometry_page_does_not_alias_canary_page(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_unmapped_geometry_page",
                task_id="task_unmapped_geometry_page",
                mode="precision",
            )
            document = _document(1).model_copy(
                update={
                    "parse_metadata": {
                        "pdf_page_count": 1,
                        "original_page_map": {"1": 34},
                        "pdf_geometry_math": {
                            "attempted_pages": [1],
                            "candidates": [],
                            "injected_into_text": False,
                        },
                    }
                }
            )
            client = _FakePageKnowledgeClient(
                {1: [_concept_payload(1)]}
            )

            result = await extract_pdf_page_knowledge(
                document=document,
                rendered=rendered,
                runtime=_runtime(client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=1,
                extraction_profile="direct_layout_fallback",
            )

        self.assertTrue(result.complete)
        metadata = result.document.parse_metadata["pdf_page_knowledge"]
        self.assertEqual(metadata["layout_audited_pages"], [])

    async def test_failed_layout_audit_invalidates_direct_and_falls_back(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_failed_layout_audit",
                task_id="task_failed_layout_audit",
                mode="precision",
            )
            document = _document(1).model_copy(
                update={
                    "parse_metadata": {
                        "pdf_page_count": 1,
                        "pdf_geometry_math": {
                            "attempted_pages": [1],
                            "candidates": [
                                {
                                    "page": 1,
                                    "canonical": "A=B",
                                    "issues": [],
                                }
                            ],
                            "injected_into_text": False,
                        },
                    }
                }
            )
            client = _FakePageKnowledgeClient(
                {1: [_short_relation_payload(1)]}
            )
            calls: list[bool] = []

            async def fake_layout_extractor(**kwargs):
                extract_nodes = bool(kwargs.get("extract_nodes", True))
                calls.append(extract_nodes)
                if not extract_nodes:
                    return LayoutKnowledgePageResult(
                        layout=None,
                        layout_attempts=1,
                        issues=["layout_audit_failed"],
                    )
                recovered = PageKnowledgeExtraction.model_validate(
                    {
                        **_short_relation_payload(1),
                        "nodes": [
                            {
                                "temp_id": "relation-formula",
                                "name": "L⃗ → μ⃗",
                                "type": "formula",
                                "role": "formula",
                                "definition": "L⃗ → μ⃗",
                                "evidence_text": "L⃗ → μ⃗",
                                "formula_text": "L⃗ → μ⃗",
                                "formula_latex": (
                                    r"\vec{L}\rightarrow\vec{\mu}"
                                ),
                                "bbox": [0.2, 0.22, 0.3, 0.08],
                                "confidence": 0.98,
                                "terminal_gold_gate": TERMINAL_GOLD_GATE,
                            }
                        ],
                    }
                )
                return LayoutKnowledgePageResult(
                    layout=_materialized_layout(1),
                    extraction=recovered,
                    layout_attempts=1,
                    node_attempts=1,
                    issues=[],
                )

            with patch(
                "backend.app.pdf_layout_knowledge."
                "extract_page_layout_knowledge",
                side_effect=fake_layout_extractor,
            ):
                result = await extract_pdf_page_knowledge(
                    document=document,
                    rendered=rendered,
                    runtime=_runtime(client),
                    data_root=data_root,
                    checkpoint_store=blackboard,
                    run_id=run_id,
                    source_sha256="source-sha",
                    prompt_version="page-knowledge-prompt-v1",
                    render_dpi=192,
                    min_confidence=0.85,
                    concurrency=1,
                    max_page_attempts=1,
                    extraction_profile="direct_layout_fallback",
                )

        self.assertTrue(result.complete)
        self.assertEqual(calls, [False, True])
        metadata = result.document.parse_metadata["pdf_page_knowledge"]
        self.assertEqual(metadata["direct_accepted_pages"], [])
        self.assertEqual(metadata["layout_audit_failed_pages"], [1])
        self.assertEqual(metadata["fallback_attempted_pages"], [1])
        self.assertEqual(metadata["fallback_accepted_pages"], [1])

    async def test_failed_layout_audit_and_fallback_leave_page_failed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_failed_audit_and_fallback",
                task_id="task_failed_audit_and_fallback",
                mode="precision",
            )
            document = _document(1).model_copy(
                update={
                    "parse_metadata": {
                        "pdf_page_count": 1,
                        "pdf_geometry_math": {
                            "attempted_pages": [1],
                            "candidates": [
                                {
                                    "page": 1,
                                    "canonical": "A=B",
                                    "issues": [],
                                }
                            ],
                            "injected_into_text": False,
                        },
                    }
                }
            )
            client = _FakePageKnowledgeClient(
                {1: [_short_relation_payload(1)]}
            )
            calls: list[bool] = []

            async def fake_layout_extractor(**kwargs):
                calls.append(bool(kwargs.get("extract_nodes", True)))
                return LayoutKnowledgePageResult(
                    layout=None,
                    layout_attempts=1,
                    issues=["layout_failed"],
                )

            with patch(
                "backend.app.pdf_layout_knowledge."
                "extract_page_layout_knowledge",
                side_effect=fake_layout_extractor,
            ):
                result = await extract_pdf_page_knowledge(
                    document=document,
                    rendered=rendered,
                    runtime=_runtime(client),
                    data_root=data_root,
                    checkpoint_store=blackboard,
                    run_id=run_id,
                    source_sha256="source-sha",
                    prompt_version="page-knowledge-prompt-v1",
                    render_dpi=192,
                    min_confidence=0.85,
                    concurrency=1,
                    max_page_attempts=1,
                    extraction_profile="direct_layout_fallback",
                )

        self.assertFalse(result.complete)
        self.assertEqual(calls, [False, True])
        self.assertEqual(result.accepted_pages, [])
        self.assertEqual(result.failed_pages, [1])
        metadata = result.document.parse_metadata["pdf_page_knowledge"]
        self.assertEqual(metadata["layout_audit_failed_pages"], [1])
        self.assertEqual(metadata["fallback_failed_pages"], [1])

    async def test_valid_direct_formula_skips_audit_without_geometry_risk(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_formula_signal_no_audit",
                task_id="task_formula_signal_no_audit",
                mode="precision",
            )
            client = _FakeAuditedPageKnowledgeClient(
                direct_responses={1: [_page_payload(1)]},
                layout_responses={1: [_layout_payload(1)]},
            )

            result = await extract_pdf_page_knowledge(
                document=_document(1),
                rendered=rendered,
                runtime=_runtime(client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=1,
                extraction_profile="direct_layout_fallback",
            )

        self.assertTrue(result.complete)
        self.assertEqual(client.layout_calls, [])
        self.assertEqual(client.node_calls, [])
        metadata = result.document.parse_metadata["pdf_page_knowledge"]
        self.assertEqual(metadata["layout_audited_pages"], [])

    async def test_ordinary_direct_page_skips_layout_audit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_no_layout_audit",
                task_id="task_no_layout_audit",
                mode="precision",
            )
            client = _FakePageKnowledgeClient(
                {1: [_concept_payload(1)]}
            )

            result = await extract_pdf_page_knowledge(
                document=_document(1),
                rendered=rendered,
                runtime=_runtime(client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=1,
                extraction_profile="direct_layout_fallback",
            )
            audit_checkpoint = blackboard.load_checkpoint(
                run_id,
                "page_knowledge:layout_audit:0001",
            )

        self.assertTrue(result.complete)
        self.assertIsNone(audit_checkpoint)
        metadata = result.document.parse_metadata["pdf_page_knowledge"]
        self.assertEqual(metadata["layout_audited_pages"], [])

    async def test_direct_layout_fallback_only_retries_direct_failures(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=2)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_direct_layout_fallback",
                task_id="task_direct_layout_fallback",
                mode="precision",
            )
            client = _FakePageKnowledgeClient(
                {
                    1: [_concept_payload(1)],
                    2: [_concept_payload(2, confidence=0.4)],
                }
            )
            layout_calls: list[int] = []

            async def fake_layout_extractor(**kwargs):
                page = int(kwargs["page"])
                layout_calls.append(page)
                if page != 2:
                    raise AssertionError(
                        "layout fallback must only receive direct failures"
                    )
                return LayoutKnowledgePageResult(
                    layout=_materialized_layout(page),
                    extraction=PageKnowledgeExtraction.model_validate(
                        _page_payload(page)
                    ),
                    layout_attempts=1,
                    node_attempts=1,
                    issues=["node_selector_deterministic_fallback"],
                )

            with patch(
                "backend.app.pdf_layout_knowledge."
                "extract_page_layout_knowledge",
                side_effect=fake_layout_extractor,
            ):
                result = await extract_pdf_page_knowledge(
                    document=_document(2),
                    rendered=rendered,
                    runtime=_runtime(client),
                    data_root=data_root,
                    checkpoint_store=blackboard,
                    run_id=run_id,
                    source_sha256="source-sha",
                    prompt_version="page-knowledge-prompt-v1",
                    render_dpi=192,
                    min_confidence=0.85,
                    concurrency=2,
                    max_page_attempts=1,
                    extraction_profile="direct_layout_fallback",
                )

            direct_page_1 = blackboard.load_checkpoint(
                run_id,
                "page_knowledge:0001",
            )
            direct_page_2 = blackboard.load_checkpoint(
                run_id,
                "page_knowledge:0002",
            )
            layout_page_1 = blackboard.load_checkpoint(
                run_id,
                "page_knowledge:layout_nodes:0001",
            )
            layout_page_2 = blackboard.load_checkpoint(
                run_id,
                "page_knowledge:layout_nodes:0002",
            )

        self.assertTrue(result.complete)
        self.assertEqual(result.accepted_pages, [1, 2])
        self.assertEqual(result.degraded_pages, [2])
        self.assertEqual(result.failed_pages, [])
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(layout_calls, [2])
        self.assertEqual(direct_page_1["status"], "accepted")
        self.assertEqual(direct_page_2["status"], "failed")
        self.assertIsNone(layout_page_1)
        self.assertEqual(layout_page_2["status"], "accepted")
        metadata = result.document.parse_metadata["pdf_page_knowledge"]
        self.assertEqual(
            metadata["extraction_profile"],
            "direct_layout_fallback",
        )
        self.assertEqual(metadata["direct_accepted_pages"], [1])
        self.assertEqual(metadata["fallback_attempted_pages"], [2])
        self.assertEqual(metadata["fallback_accepted_pages"], [2])
        self.assertEqual(metadata["degraded_pages"], [2])
        self.assertEqual(metadata["clean_accepted_pages"], [1])
        self.assertTrue(
            any(
                "[pdf_layout_nodes_fallback]" in warning
                for warning in result.warnings
            )
        )
        self.assertFalse(
            any(
                "第 2 页知识节点未通过质量门" in warning
                for warning in result.warnings
            )
        )
        self.assertFalse(
            any(
                "[pdf_knowledge_degraded:page_failure]" in warning
                for warning in result.warnings
            )
        )

    async def test_direct_layout_fallback_keeps_unrecovered_page_failed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=2)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_direct_layout_unrecovered",
                task_id="task_direct_layout_unrecovered",
                mode="precision",
            )
            client = _FakePageKnowledgeClient(
                {
                    1: [_concept_payload(1)],
                    2: [_concept_payload(2, confidence=0.4)],
                }
            )
            layout_calls: list[int] = []

            async def fake_layout_extractor(**kwargs):
                page = int(kwargs["page"])
                layout_calls.append(page)
                return LayoutKnowledgePageResult(
                    layout=_materialized_layout(page),
                    extraction=None,
                    layout_attempts=1,
                    node_attempts=1,
                    issues=["node_selector_failed"],
                )

            with patch(
                "backend.app.pdf_layout_knowledge."
                "extract_page_layout_knowledge",
                side_effect=fake_layout_extractor,
            ):
                result = await extract_pdf_page_knowledge(
                    document=_document(2),
                    rendered=rendered,
                    runtime=_runtime(client),
                    data_root=data_root,
                    checkpoint_store=blackboard,
                    run_id=run_id,
                    source_sha256="source-sha",
                    prompt_version="page-knowledge-prompt-v1",
                    render_dpi=192,
                    min_confidence=0.85,
                    concurrency=2,
                    max_page_attempts=1,
                    extraction_profile="direct_layout_fallback",
                )

            layout_page_2 = blackboard.load_checkpoint(
                run_id,
                "page_knowledge:layout_nodes:0002",
            )

        self.assertFalse(result.complete)
        self.assertEqual(result.accepted_pages, [1])
        self.assertEqual(result.failed_pages, [2])
        self.assertEqual(layout_calls, [2])
        self.assertEqual(layout_page_2["status"], "failed")
        metadata = result.document.parse_metadata["pdf_page_knowledge"]
        self.assertEqual(metadata["direct_accepted_pages"], [1])
        self.assertEqual(metadata["fallback_attempted_pages"], [2])
        self.assertEqual(metadata["fallback_accepted_pages"], [])
        self.assertEqual(metadata["fallback_failed_pages"], [2])
        self.assertTrue(
            any(
                "[pdf_knowledge_degraded:page_failure]" in warning
                for warning in result.warnings
            )
        )

    async def test_cross_run_cache_rejects_incompatible_checkpoint_contract(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            source_run_id = blackboard.start_run(
                run_id="run_cross_cache_bad_contract",
                task_id="task_cross_cache_bad_contract",
                mode="precision",
                owner_id="owner-a",
            )
            await extract_pdf_page_knowledge(
                document=_document(1),
                rendered=rendered,
                runtime=_runtime(
                    _FakePageKnowledgeClient({1: [_page_payload(1)]})
                ),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=source_run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=1,
            )
            incompatible = blackboard.load_checkpoint(
                source_run_id,
                "page_knowledge:0001",
            )
            incompatible["schema_version"] = "page-knowledge-v0"
            blackboard.checkpoint(
                source_run_id,
                "page_knowledge:0001",
                incompatible,
            )
            target_run_id = blackboard.start_run(
                run_id="run_cross_cache_reextract",
                task_id="task_cross_cache_reextract",
                mode="precision",
                owner_id="owner-a",
            )
            target_client = _FakePageKnowledgeClient(
                {1: [_page_payload(1)]}
            )

            target = await extract_pdf_page_knowledge(
                document=_document(1),
                rendered=rendered,
                runtime=_runtime(target_client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=target_run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=1,
            )

        self.assertTrue(target.complete)
        self.assertEqual(target.reused_pages, [])
        self.assertEqual(target.called_pages, [1])
        self.assertEqual(len(target_client.calls), 1)

    async def test_cross_run_cache_is_scoped_to_the_current_owner(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            source_run_id = blackboard.start_run(
                run_id="run_cross_owner_source",
                task_id="task_cross_owner_source",
                mode="precision",
                owner_id="owner-a",
            )
            await extract_pdf_page_knowledge(
                document=_document(1),
                rendered=rendered,
                runtime=_runtime(
                    _FakePageKnowledgeClient({1: [_page_payload(1)]})
                ),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=source_run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=1,
            )
            target_run_id = blackboard.start_run(
                run_id="run_cross_owner_target",
                task_id="task_cross_owner_target",
                mode="precision",
                owner_id="owner-b",
            )
            target_client = _FakePageKnowledgeClient(
                {1: [_page_payload(1)]}
            )

            target = await extract_pdf_page_knowledge(
                document=_document(1),
                rendered=rendered,
                runtime=_runtime(target_client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=target_run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=1,
            )

        self.assertTrue(target.complete)
        self.assertEqual(target.reused_pages, [])
        self.assertEqual(target.called_pages, [1])
        self.assertEqual(len(target_client.calls), 1)

    async def test_layout_nodes_retry_is_local_to_the_failed_page(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=2)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_layout_nodes_retry",
                task_id="task_layout_nodes_retry",
                mode="precision",
            )
            client = _FakeLayoutKnowledgeClient(
                {
                    1: [_layout_payload(1)],
                    2: [
                        _layout_payload(2, confidence=0.4),
                        _layout_payload(2),
                    ],
                }
            )

            result = await extract_pdf_page_knowledge(
                document=_document(2),
                rendered=rendered,
                runtime=_runtime(client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=2,
                max_page_attempts=2,
                extraction_profile="layout_nodes",
            )

        self.assertTrue(result.complete)
        self.assertEqual(result.accepted_pages, [1, 2])
        self.assertEqual(Counter(client.layout_calls), {1: 1, 2: 2})
        self.assertEqual(Counter(client.node_calls), {1: 1, 2: 1})

    async def test_layout_schema_upgrade_reuses_layout_and_reselects_nodes(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_layout_nodes_upgrade",
                task_id="task_layout_nodes_upgrade",
                mode="precision",
            )
            page = rendered.pages[0]
            source = (
                data_root
                / "assets"
                / rendered.render_id
                / page.filename
            )
            image_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
            layout = PageLayoutExtraction.model_validate(
                {
                    "profile": "dots",
                    "page": 1,
                    "complete": True,
                    "confidence": 0.98,
                    "blocks": [
                        {
                            "block_id": "p0001:b000",
                            "category": "formula",
                            "text": "Δν/ν≈10^-6",
                            "formulas": [
                                {
                                    "text": "Δν/ν≈10^-6",
                                    "latex": (
                                        r"\frac{\Delta\nu}{\nu}"
                                        r"\approx10^{-6}"
                                    ),
                                }
                            ],
                            "bbox": [0.1, 0.2, 0.7, 0.2],
                            "confidence": 0.98,
                        }
                    ],
                }
            )
            invalid_extraction = PageKnowledgeExtraction.model_validate(
                _page_payload(1)
            )
            invalid_extraction.nodes[0].name = (
                "后来发现在其他波段还存在谱线。"
            )
            old_node_schema = "page-layout-nodes-v1"
            prompt_version = "page-knowledge-prompt-v1"
            old_input_hash = _input_hash(
                source_sha256="source-sha",
                page=page,
                image_sha256=image_sha256,
                prompt_version=prompt_version,
                provider="qwen",
                model="qwen3.8-max-preview",
                knowledge_schema_version="page-knowledge-v3",
                extraction_profile="layout_nodes",
                profile_schema_versions=(
                    PAGE_LAYOUT_SCHEMA_VERSION,
                    old_node_schema,
                ),
            )
            blackboard.checkpoint(
                run_id,
                "page_knowledge:layout_nodes:0001",
                {
                    "schema_version": "page-knowledge-v3",
                    "layout_schema_version": PAGE_LAYOUT_SCHEMA_VERSION,
                    "layout_node_schema_version": old_node_schema,
                    "status": "accepted",
                    "input_hash": old_input_hash,
                    "image_sha256": image_sha256,
                    "provider": "qwen",
                    "model": "qwen3.8-max-preview",
                    "prompt_version": prompt_version,
                    "extraction_profile": "layout_nodes",
                    "layout_profile": "dots",
                    "layout_attempts": 1,
                    "node_attempts": 1,
                    "node_selection_fallback": False,
                    "issues": [],
                    "layout": layout.model_dump(mode="json"),
                    "extraction": invalid_extraction.model_dump(mode="json"),
                },
            )
            client = _FakeLayoutKnowledgeClient({})

            result = await extract_pdf_page_knowledge(
                document=_document(1),
                rendered=rendered,
                runtime=_runtime(client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256="source-sha",
                prompt_version=prompt_version,
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=2,
                extraction_profile="layout_nodes",
            )

        self.assertTrue(result.complete)
        self.assertEqual(result.called_pages, [1])
        self.assertEqual(client.layout_calls, [])
        self.assertEqual(client.node_calls, [1])

    async def test_layout_reselection_failure_preserves_reusable_layout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_layout_nodes_failed_upgrade",
                task_id="task_layout_nodes_failed_upgrade",
                mode="precision",
            )
            page = rendered.pages[0]
            source = (
                data_root
                / "assets"
                / rendered.render_id
                / page.filename
            )
            image_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
            layout = PageLayoutExtraction.model_validate(
                {
                    "profile": "dots",
                    "page": 1,
                    "complete": True,
                    "confidence": 0.98,
                    "blocks": [
                        {
                            "block_id": "p0001:b000",
                            "category": "formula",
                            "text": "Δν/ν≈10^-6",
                            "formulas": [
                                {
                                    "text": "Δν/ν≈10^-6",
                                    "latex": (
                                        r"\frac{\Delta\nu}{\nu}"
                                        r"\approx10^{-6}"
                                    ),
                                }
                            ],
                            "bbox": [0.1, 0.2, 0.7, 0.2],
                            "confidence": 0.98,
                        }
                    ],
                }
            )
            invalid_extraction = PageKnowledgeExtraction.model_validate(
                _page_payload(1)
            )
            invalid_extraction.nodes[0].name = (
                "后来发现在其他波段还存在谱线。"
            )
            old_node_schema = "page-layout-nodes-v1"
            prompt_version = "page-knowledge-prompt-v1"
            old_input_hash = _input_hash(
                source_sha256="source-sha",
                page=page,
                image_sha256=image_sha256,
                prompt_version=prompt_version,
                provider="qwen",
                model="qwen3.8-max-preview",
                knowledge_schema_version="page-knowledge-v3",
                extraction_profile="layout_nodes",
                profile_schema_versions=(
                    PAGE_LAYOUT_SCHEMA_VERSION,
                    old_node_schema,
                ),
            )
            blackboard.checkpoint(
                run_id,
                "page_knowledge:layout_nodes:0001",
                {
                    "schema_version": "page-knowledge-v3",
                    "layout_schema_version": PAGE_LAYOUT_SCHEMA_VERSION,
                    "layout_node_schema_version": old_node_schema,
                    "status": "accepted",
                    "input_hash": old_input_hash,
                    "image_sha256": image_sha256,
                    "provider": "qwen",
                    "model": "qwen3.8-max-preview",
                    "prompt_version": prompt_version,
                    "extraction_profile": "layout_nodes",
                    "layout_profile": "dots",
                    "layout_attempts": 1,
                    "node_attempts": 1,
                    "node_selection_fallback": False,
                    "issues": [],
                    "layout": layout.model_dump(mode="json"),
                    "extraction": invalid_extraction.model_dump(mode="json"),
                },
            )
            client = _FakeLayoutKnowledgeClient({})
            error = (
                "selection contains no publishable layout nodes: "
                "label_sentence_fragment"
            )

            with patch(
                "backend.app.pdf_layout_knowledge.extract_layout_nodes",
                side_effect=ValueError(error),
            ):
                result = await extract_pdf_page_knowledge(
                    document=_document(1),
                    rendered=rendered,
                    runtime=_runtime(client),
                    data_root=data_root,
                    checkpoint_store=blackboard,
                    run_id=run_id,
                    source_sha256="source-sha",
                    prompt_version=prompt_version,
                    render_dpi=192,
                    min_confidence=0.85,
                    concurrency=1,
                    max_page_attempts=2,
                    extraction_profile="layout_nodes",
                )
            failed = blackboard.load_checkpoint(
                run_id,
                "page_knowledge:layout_nodes:0001",
            )

        self.assertFalse(result.complete)
        self.assertEqual(result.failed_pages, [1])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["issues"], [error])
        self.assertEqual(
            failed["layout_schema_version"],
            PAGE_LAYOUT_SCHEMA_VERSION,
        )
        self.assertEqual(
            failed["layout_node_schema_version"],
            PAGE_LAYOUT_NODE_SCHEMA_VERSION,
        )
        self.assertEqual(failed["layout"], layout.model_dump(mode="json"))

    async def test_layout_schema_upgrade_reuses_valid_extraction_without_calls(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_layout_nodes_zero_call_upgrade",
                task_id="task_layout_nodes_zero_call_upgrade",
                mode="precision",
            )
            page = rendered.pages[0]
            source = (
                data_root
                / "assets"
                / rendered.render_id
                / page.filename
            )
            image_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
            layout = PageLayoutExtraction.model_validate(
                {
                    "profile": "dots",
                    "page": 1,
                    "complete": True,
                    "confidence": 0.98,
                    "blocks": [
                        {
                            "block_id": "p0001:b000",
                            "category": "formula",
                            "text": "Δν/ν≈10^-6",
                            "formulas": [
                                {
                                    "text": "Δν/ν≈10^-6",
                                    "latex": (
                                        r"\frac{\Delta\nu}{\nu}"
                                        r"\approx10^{-6}"
                                    ),
                                }
                            ],
                            "bbox": [0.1, 0.2, 0.7, 0.2],
                            "confidence": 0.98,
                        }
                    ],
                }
            )
            old_node_schema = "page-layout-nodes-v1"
            old_knowledge_schema = "page-knowledge-v3"
            prompt_version = "page-knowledge-prompt-v1"
            old_input_hash = _input_hash(
                source_sha256="source-sha",
                page=page,
                image_sha256=image_sha256,
                prompt_version=prompt_version,
                provider="qwen",
                model="qwen3.8-max-preview",
                knowledge_schema_version=old_knowledge_schema,
                extraction_profile="layout_nodes",
                profile_schema_versions=(
                    PAGE_LAYOUT_SCHEMA_VERSION,
                    old_node_schema,
                ),
            )
            blackboard.checkpoint(
                run_id,
                "page_knowledge:layout_nodes:0001",
                {
                    "schema_version": old_knowledge_schema,
                    "layout_schema_version": PAGE_LAYOUT_SCHEMA_VERSION,
                    "layout_node_schema_version": old_node_schema,
                    "status": "accepted",
                    "input_hash": old_input_hash,
                    "image_sha256": image_sha256,
                    "provider": "qwen",
                    "model": "qwen3.8-max-preview",
                    "prompt_version": prompt_version,
                    "extraction_profile": "layout_nodes",
                    "layout_profile": "dots",
                    "layout_attempts": 1,
                    "node_attempts": 1,
                    "node_selection_fallback": False,
                    "issues": [],
                    "layout": layout.model_dump(mode="json"),
                    "extraction": _page_payload(1),
                },
            )
            client = _FakeLayoutKnowledgeClient({})

            result = await extract_pdf_page_knowledge(
                document=_document(1),
                rendered=rendered,
                runtime=_runtime(client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256="source-sha",
                prompt_version=prompt_version,
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=2,
                extraction_profile="layout_nodes",
            )
            migrated = blackboard.load_checkpoint(
                run_id,
                "page_knowledge:layout_nodes:0001",
            )

        self.assertTrue(result.complete)
        self.assertEqual(result.reused_pages, [1])
        self.assertEqual(result.called_pages, [])
        self.assertEqual(client.layout_calls, [])
        self.assertEqual(client.node_calls, [])
        self.assertEqual(
            migrated["schema_version"],
            PAGE_KNOWLEDGE_SCHEMA_VERSION,
        )
        self.assertEqual(
            migrated["layout_node_schema_version"],
            PAGE_LAYOUT_NODE_SCHEMA_VERSION,
        )
        self.assertNotEqual(migrated["input_hash"], old_input_hash)
        self.assertEqual(
            migrated["layout"],
            layout.model_dump(mode="json"),
        )

    async def test_layout_nodes_profile_reuses_its_own_page_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_layout_nodes",
                task_id="task_layout_nodes",
                mode="precision",
            )
            direct_client = _FakePageKnowledgeClient(
                {1: [_page_payload(1)]}
            )
            layout = PageLayoutExtraction(
                profile="dots",
                page=1,
                complete=True,
                confidence=0.98,
                blocks=[
                    {
                        "block_id": "p0001:b000",
                        "category": "formula",
                        "text": "Δν/ν≈10^-6",
                        "formulas": [
                            {
                                "text": "Δν/ν≈10^-6",
                                "latex": (
                                    r"\frac{\Delta\nu}{\nu}"
                                    r"\approx10^{-6}"
                                ),
                            }
                        ],
                        "bbox": [0.1, 0.2, 0.7, 0.2],
                        "confidence": 0.98,
                    }
                ],
            )
            layout_result = LayoutKnowledgePageResult(
                layout=layout,
                extraction=PageKnowledgeExtraction.model_validate(
                    _page_payload(1)
                ),
                layout_attempts=2,
                node_attempts=1,
                issues=["node_selector_deterministic_fallback"],
            )

            with patch(
                "backend.app.pdf_layout_knowledge."
                "extract_page_layout_knowledge",
                return_value=layout_result,
            ) as extract_layout:
                first = await extract_pdf_page_knowledge(
                    document=_document(1),
                    rendered=rendered,
                    runtime=_runtime(direct_client),
                    data_root=data_root,
                    checkpoint_store=blackboard,
                    run_id=run_id,
                    source_sha256="source-sha",
                    prompt_version="page-knowledge-prompt-v1",
                    render_dpi=192,
                    min_confidence=0.85,
                    concurrency=1,
                    max_page_attempts=2,
                    extraction_profile="layout_nodes",
                )
                direct = await extract_pdf_page_knowledge(
                    document=_document(1),
                    rendered=rendered,
                    runtime=_runtime(direct_client),
                    data_root=data_root,
                    checkpoint_store=blackboard,
                    run_id=run_id,
                    source_sha256="source-sha",
                    prompt_version="page-knowledge-prompt-v1",
                    render_dpi=192,
                    min_confidence=0.85,
                    concurrency=1,
                    max_page_attempts=2,
                )
                second = await extract_pdf_page_knowledge(
                    document=_document(1),
                    rendered=rendered,
                    runtime=_runtime(direct_client),
                    data_root=data_root,
                    checkpoint_store=blackboard,
                    run_id=run_id,
                    source_sha256="source-sha",
                    prompt_version="page-knowledge-prompt-v1",
                    render_dpi=192,
                    min_confidence=0.85,
                    concurrency=1,
                    max_page_attempts=2,
                    extraction_profile="layout_nodes",
                )
                checkpoint = blackboard.load_checkpoint(
                    run_id,
                    "page_knowledge:layout_nodes:0001",
                )
                direct_checkpoint = blackboard.load_checkpoint(
                    run_id,
                    "page_knowledge:0001",
                )

        self.assertTrue(first.complete)
        self.assertEqual(first.degraded_pages, [1])
        self.assertEqual(first.called_pages, [1])
        self.assertEqual(second.called_pages, [])
        self.assertEqual(second.reused_pages, [1])
        self.assertEqual(second.degraded_pages, [1])
        self.assertTrue(direct.complete)
        self.assertEqual(direct.called_pages, [1])
        self.assertEqual(len(direct_client.calls), 1)
        extract_layout.assert_awaited_once()
        call = extract_layout.call_args.kwargs
        self.assertEqual(call["profile"], "dots")
        self.assertEqual(call["max_layout_attempts"], 2)
        self.assertEqual(call["max_node_attempts"], 2)
        metadata = first.document.parse_metadata["pdf_page_knowledge"]
        self.assertEqual(metadata["extraction_profile"], "layout_nodes")
        self.assertEqual(metadata["layout_profile"], "dots")
        self.assertTrue(
            any(
                "[pdf_layout_nodes_fallback]" in warning
                for warning in first.warnings
            )
        )
        self.assertTrue(
            any(
                "[pdf_layout_nodes_fallback]" in warning
                for warning in second.warnings
            )
        )
        self.assertEqual(checkpoint["extraction_profile"], "layout_nodes")
        self.assertEqual(checkpoint["layout_profile"], "dots")
        self.assertEqual(checkpoint["layout_attempts"], 2)
        self.assertEqual(checkpoint["node_attempts"], 1)
        self.assertEqual(
            checkpoint["issues"],
            ["node_selector_deterministic_fallback"],
        )
        self.assertEqual(checkpoint["layout"]["profile"], "dots")
        self.assertIsNotNone(direct_checkpoint)

    async def test_layout_nodes_accepts_heading_only_no_knowledge_page(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_heading_only_layout",
                task_id="task_heading_only_layout",
                mode="precision",
            )
            layout = PageLayoutExtraction.model_validate(
                {
                    "profile": "dots",
                    "page": 1,
                    "complete": True,
                    "confidence": 0.98,
                    "blocks": [
                        {
                            "block_id": "p0001:b000",
                            "category": "heading",
                            "text": "第28章 原子中的电子",
                            "bbox": [0.1, 0.1, 0.7, 0.08],
                            "confidence": 0.98,
                        },
                        {
                            "block_id": "p0001:b001",
                            "category": "heading",
                            "text": "§28.1 氢原子的量子力学处理",
                            "bbox": [0.1, 0.25, 0.7, 0.08],
                            "confidence": 0.98,
                        },
                    ],
                }
            )
            no_knowledge = PageKnowledgeExtraction.model_validate(
                {
                    "page": 1,
                    "complete": True,
                    "confidence": 0.98,
                    "heading": "第28章 原子中的电子",
                    "has_knowledge": False,
                    "no_knowledge_reason": "页面仅含章节目录",
                    "nodes": [],
                }
            )
            layout_result = LayoutKnowledgePageResult(
                layout=layout,
                extraction=no_knowledge,
                layout_attempts=1,
                node_attempts=1,
                issues=[],
            )

            with patch(
                "backend.app.pdf_layout_knowledge."
                "extract_page_layout_knowledge",
                return_value=layout_result,
            ):
                result = await extract_pdf_page_knowledge(
                    document=_document(1).model_copy(
                        update={
                            "blocks": [
                                SourceBlock(
                                    text=(
                                        "第28章 原子中的电子与"
                                        "氢原子的量子力学处理"
                                    ),
                                    page=1,
                                    heading="第28章 原子中的电子",
                                )
                            ]
                        }
                    ),
                    rendered=rendered,
                    runtime=_runtime(_FakeLayoutKnowledgeClient({})),
                    data_root=data_root,
                    checkpoint_store=blackboard,
                    run_id=run_id,
                    source_sha256="source-sha",
                    prompt_version="page-knowledge-prompt-v1",
                    render_dpi=192,
                    min_confidence=0.85,
                    concurrency=1,
                    max_page_attempts=2,
                    extraction_profile="layout_nodes",
                )

        self.assertTrue(result.complete)
        self.assertEqual(result.accepted_pages, [1])
        self.assertEqual(result.failed_pages, [])
        self.assertFalse(result.extractions[0].has_knowledge)

    async def test_direct_page_accepts_repeated_no_knowledge_consensus(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_no_knowledge_consensus",
                task_id="task_no_knowledge_consensus",
                mode="precision",
            )
            client = _FakePageKnowledgeClient(
                {1: [_no_knowledge_payload(1), _no_knowledge_payload(1)]}
            )
            document = _document(1).model_copy(
                update={
                    "blocks": [
                        SourceBlock(
                            text=(
                                "第28章 原子中的电子 "
                                "第28.1节 氢原子的量子力学处理"
                            ),
                            page=1,
                            heading="第28章 原子中的电子",
                        )
                    ]
                }
            )

            result = await extract_pdf_page_knowledge(
                document=document,
                rendered=rendered,
                runtime=_runtime(client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=2,
            )
            checkpoint = blackboard.load_checkpoint(
                run_id,
                "page_knowledge:0001",
            )
            reused = await extract_pdf_page_knowledge(
                document=document,
                rendered=rendered,
                runtime=_runtime(client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=2,
            )

        self.assertTrue(result.complete)
        self.assertEqual(len(client.calls), 2)
        self.assertFalse(result.extractions[0].has_knowledge)
        self.assertTrue(reused.complete)
        self.assertEqual(reused.reused_pages, [1])
        self.assertEqual(
            checkpoint["no_knowledge_consensus_attempts"],
            2,
        )

    async def test_one_no_knowledge_vote_does_not_hide_valid_nodes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_no_knowledge_then_nodes",
                task_id="task_no_knowledge_then_nodes",
                mode="precision",
            )
            client = _FakePageKnowledgeClient(
                {1: [_no_knowledge_payload(1), _page_payload(1)]}
            )
            document = _document(1).model_copy(
                update={
                    "blocks": [
                        SourceBlock(
                            text="谱线相对宽度满足明确的负指数关系",
                            page=1,
                        )
                    ]
                }
            )

            result = await extract_pdf_page_knowledge(
                document=document,
                rendered=rendered,
                runtime=_runtime(client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=2,
            )

        self.assertTrue(result.complete)
        self.assertTrue(result.extractions[0].has_knowledge)
        self.assertEqual(len(result.extractions[0].nodes), 1)

    async def test_retry_prompt_includes_previous_quality_gate_issues(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_page_knowledge_retry",
                task_id="task_page_knowledge_retry",
                mode="precision",
            )
            client = _FakePageKnowledgeClient(
                {
                    1: [
                        _page_payload(1, formula_text="Δν/ν≈10^6"),
                        _page_payload(1),
                    ]
                }
            )

            result = await extract_pdf_page_knowledge(
                document=_document(1),
                rendered=rendered,
                runtime=_runtime(client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=2,
            )

        self.assertTrue(result.complete)
        self.assertEqual(len(client.calls), 2)
        self.assertIn(
            "missing_negative_exponent",
            client.calls[1]["user_prompt"],
        )

    async def test_malformed_node_preserves_valid_sibling_in_checkpoint(self):
        valid = _algebra_node(
            temp_id="sum",
            name="变量求和关系",
            formula_text="c=a+b",
            formula_latex="c=a+b",
            y=0.1,
        )
        malformed = _algebra_node(
            temp_id="ratio",
            name="变量比值关系",
            formula_text="R=x/y",
            formula_latex=r"R=\frac{x}{y}",
            y=0.3,
        )
        malformed.pop("definition")

        result, checkpoint, _calls = await _run_direct_page_fixture(
            [_algebra_payload(1, [valid, malformed])],
            max_page_attempts=1,
        )

        self.assertFalse(result.complete)
        self.assertEqual(checkpoint["status"], "failed")
        self.assertEqual(
            [
                node["temp_id"]
                for node in checkpoint["best_partial"]["nodes"]
            ],
            ["sum"],
        )
        self.assertEqual(checkpoint["unresolved_node_count"], 1)
        self.assertTrue(
            any(
                issue.startswith("node_1:")
                for issue in checkpoint["issues"]
            )
        )

    async def test_retry_omitting_valid_node_preserves_and_merges_it(self):
        valid = _algebra_node(
            temp_id="sum",
            name="变量求和关系",
            formula_text="c=a+b",
            formula_latex="c=a+b",
            y=0.1,
        )
        malformed = _algebra_node(
            temp_id="ratio",
            name="变量比值关系",
            formula_text="R=x/y",
            formula_latex=r"R=\frac{x}{y}",
            y=0.3,
        )
        repaired = dict(malformed)
        malformed["evidence_text"] = "R=x/z"

        result, _checkpoint, calls = await _run_direct_page_fixture(
            [
                _algebra_payload(1, [valid, malformed]),
                _algebra_payload(1, [repaired]),
            ],
            max_page_attempts=2,
        )

        self.assertTrue(result.complete)
        self.assertEqual(
            {node.temp_id for node in result.extractions[0].nodes},
            {"sum", "ratio"},
        )
        self.assertIn('"temp_id":"sum"', calls[1]["user_prompt"])
        self.assertIn("node_1:formula_not_in_evidence", calls[1]["user_prompt"])

    async def test_repaired_node_merges_without_duplicate_preserved_node(self):
        valid = _algebra_node(
            temp_id="sum",
            name="变量求和关系",
            formula_text="c=a+b",
            formula_latex="c=a+b",
            y=0.1,
        )
        malformed = _algebra_node(
            temp_id="ratio",
            name="变量比值关系",
            formula_text="R=x/y",
            formula_latex=r"R=\frac{x}{y}",
            y=0.3,
        )
        repaired = dict(malformed)
        malformed.pop("definition")

        result, _checkpoint, _calls = await _run_direct_page_fixture(
            [
                _algebra_payload(1, [valid, malformed]),
                _algebra_payload(1, [valid, repaired]),
            ],
            max_page_attempts=2,
        )

        self.assertTrue(result.complete)
        self.assertEqual(len(result.extractions[0].nodes), 2)
        self.assertEqual(
            [node.temp_id for node in result.extractions[0].nodes],
            ["sum", "ratio"],
        )

    async def test_retry_ignores_preserved_source_with_bbox_jitter(self):
        valid = _algebra_node(
            temp_id="sum",
            name="变量求和关系",
            formula_text="c=a+b",
            formula_latex="c=a+b",
            y=0.1,
        )
        malformed = _algebra_node(
            temp_id="ratio",
            name="变量比值关系",
            formula_text="R=x/y",
            formula_latex=r"R=\frac{x}{y}",
            y=0.3,
        )
        malformed.pop("definition")
        reemitted = {
            **valid,
            "name": "变量加和关系",
            "bbox": [0.11, 0.11, 0.61, 0.11],
        }
        repaired = _algebra_node(
            temp_id="ratio",
            name="变量比值关系",
            formula_text="R=x/y",
            formula_latex=r"R=\frac{x}{y}",
            y=0.3,
        )

        result, _checkpoint, _calls = await _run_direct_page_fixture(
            [
                _algebra_payload(1, [valid, malformed]),
                _algebra_payload(1, [reemitted, repaired]),
            ],
            max_page_attempts=2,
        )

        self.assertTrue(result.complete)
        self.assertEqual(
            [node.name for node in result.extractions[0].nodes],
            ["变量求和关系", "变量比值关系"],
        )

    async def test_retry_still_rejects_unrelated_new_node(self):
        valid = _algebra_node(
            temp_id="sum",
            name="变量求和关系",
            formula_text="c=a+b",
            formula_latex="c=a+b",
            y=0.1,
        )
        malformed = _algebra_node(
            temp_id="ratio",
            name="变量比值关系",
            formula_text="R=x/y",
            formula_latex=r"R=\frac{x}{y}",
            y=0.3,
        )
        malformed.pop("definition")
        repaired = _algebra_node(
            temp_id="ratio",
            name="变量比值关系",
            formula_text="R=x/y",
            formula_latex=r"R=\frac{x}{y}",
            y=0.3,
        )
        unrelated = _algebra_node(
            temp_id="product",
            name="变量乘积关系",
            formula_text="p=a*b",
            formula_latex=r"p=a\cdot b",
            y=0.5,
        )

        result, checkpoint, _calls = await _run_direct_page_fixture(
            [
                _algebra_payload(1, [valid, malformed]),
                _algebra_payload(1, [repaired, unrelated]),
            ],
            max_page_attempts=2,
        )

        self.assertFalse(result.complete)
        self.assertIn(
            "node_1:unexpected_repair_node",
            checkpoint["terminal_issues"],
        )

    async def test_final_timeout_keeps_best_partial_but_page_stays_failed(self):
        valid = _algebra_node(
            temp_id="sum",
            name="变量求和关系",
            formula_text="c=a+b",
            formula_latex="c=a+b",
            y=0.1,
        )
        malformed = _algebra_node(
            temp_id="ratio",
            name="变量比值关系",
            formula_text="R=x/y",
            formula_latex=r"R=\frac{x}{y}",
            y=0.3,
        )
        malformed.pop("definition")

        result, checkpoint, _calls = await _run_direct_page_fixture(
            [
                _algebra_payload(1, [valid, malformed]),
                ModelProviderError("synthetic timeout"),
            ],
            max_page_attempts=2,
        )

        self.assertFalse(result.complete)
        self.assertEqual(checkpoint["status"], "failed")
        self.assertEqual(checkpoint["terminal_issues"], ["ModelProviderError"])
        self.assertEqual(
            [
                node["temp_id"]
                for node in checkpoint["best_partial"]["nodes"]
            ],
            ["sum"],
        )
        self.assertEqual(checkpoint["unresolved_node_count"], 1)

    async def test_unresolved_invalid_node_still_blocks_page_acceptance(self):
        valid = _algebra_node(
            temp_id="sum",
            name="变量求和关系",
            formula_text="c=a+b",
            formula_latex="c=a+b",
            y=0.1,
        )
        malformed = _algebra_node(
            temp_id="ratio",
            name="变量比值关系",
            formula_text="R=x/y",
            formula_latex=r"R=\frac{x}{y}",
            y=0.3,
        )
        malformed.pop("definition")
        unrelated = _algebra_node(
            temp_id="product",
            name="变量乘积关系",
            formula_text="p=a*b",
            formula_latex=r"p=a\cdot b",
            y=0.5,
        )

        result, checkpoint, _calls = await _run_direct_page_fixture(
            [
                _algebra_payload(1, [valid, malformed]),
                _algebra_payload(1, [unrelated]),
            ],
            max_page_attempts=2,
        )

        self.assertFalse(result.complete)
        self.assertEqual(result.failed_pages, [1])
        self.assertEqual(checkpoint["unresolved_node_count"], 1)
        self.assertEqual(
            [
                node["temp_id"]
                for node in checkpoint["best_partial"]["nodes"]
            ],
            ["sum"],
        )

    async def test_retry_can_explicitly_discard_optional_bad_node(self):
        valid = _algebra_node(
            temp_id="sum",
            name="变量求和关系",
            formula_text="c=a+b",
            formula_latex="c=a+b",
            y=0.1,
        )
        optional_bad = {
            "temp_id": "wavelength-label",
            "name": "跃迁波长标签",
            "type": "result",
            "role": "other",
            "definition": "图中标注了跃迁波长3.39μm。",
            "evidence_text": "3.39μm",
            "formula_text": "",
            "formula_latex": "",
            "bbox": [0.1, 0.4, 0.2, 0.1],
            "confidence": 0.98,
            "terminal_gold_gate": TERMINAL_GOLD_GATE,
        }
        discard = _algebra_payload(1, [])
        discard["discarded_temp_ids"] = ["wavelength-label"]

        result, checkpoint, calls = await _run_direct_page_fixture(
            [
                _algebra_payload(1, [valid, optional_bad]),
                discard,
            ],
            max_page_attempts=2,
        )

        self.assertTrue(result.complete)
        self.assertEqual(
            [node.temp_id for node in result.extractions[0].nodes],
            ["sum"],
        )
        self.assertEqual(
            checkpoint["discarded_temp_ids"],
            ["wavelength-label"],
        )
        self.assertIn("discarded_temp_ids", calls[1]["user_prompt"])

    async def test_retry_cannot_discard_formula_fidelity_failure(self):
        valid = _algebra_node(
            temp_id="sum",
            name="变量求和关系",
            formula_text="c=a+b",
            formula_latex="c=a+b",
            y=0.1,
        )
        malformed = _algebra_node(
            temp_id="ratio",
            name="变量比值关系",
            formula_text="R=x/y",
            formula_latex=r"R=\frac{x}{y}",
            y=0.3,
        )
        malformed["evidence_text"] = "R=x/z"
        discard = _algebra_payload(1, [])
        discard["discarded_temp_ids"] = ["ratio"]

        result, checkpoint, _calls = await _run_direct_page_fixture(
            [
                _algebra_payload(1, [valid, malformed]),
                discard,
            ],
            max_page_attempts=2,
        )

        self.assertFalse(result.complete)
        self.assertEqual(checkpoint["unresolved_temp_ids"], ["ratio"])
        self.assertIn(
            "discard_not_allowed:ratio",
            checkpoint["terminal_issues"],
        )

    async def test_direct_page_call_uses_bounded_production_budget(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_page_knowledge_timeout",
                task_id="task_page_knowledge_timeout",
                mode="precision",
            )
            client = _FakePageKnowledgeClient({1: [_page_payload(1)]})

            result = await extract_pdf_page_knowledge(
                document=_document(1),
                rendered=rendered,
                runtime=_runtime(client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=1,
            )

        self.assertTrue(result.complete)
        self.assertEqual(client.calls[0]["timeout_seconds"], 90.0)
        self.assertLessEqual(client.calls[0]["max_tokens"], 3600)
        self.assertLessEqual(
            client.calls[0]["max_completion_tokens"],
            5000,
        )
        self.assertEqual(client.calls[0]["thinking_budget"], 1024)

    async def test_retry_prompt_explains_formula_evidence_repairs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_page_knowledge_guidance",
                task_id="task_page_knowledge_guidance",
                mode="precision",
            )
            malformed = _page_payload(1)
            malformed["nodes"][0].update(
                {
                    "evidence_text": "脉冲瞬时功率可达 > 10¹⁴ W",
                    "formula_text": "P>10^14 W",
                    "formula_latex": r"P>10^{14}\,\mathrm{W}",
                }
            )
            client = _FakePageKnowledgeClient(
                {1: [malformed, _page_payload(1)]}
            )

            result = await extract_pdf_page_knowledge(
                document=_document(1),
                rendered=rendered,
                runtime=_runtime(client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=2,
            )

        self.assertTrue(result.complete)
        self.assertIn(
            "不得为数值关系擅自补变量名",
            client.calls[1]["user_prompt"],
        )

    async def test_direct_nodes_create_stable_units_candidates_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_page_knowledge",
                task_id="task_page_knowledge",
                mode="precision",
            )
            client = _FakePageKnowledgeClient({1: [_page_payload(1)]})

            first = await extract_pdf_page_knowledge(
                document=_document(1),
                rendered=rendered,
                runtime=_runtime(client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=2,
            )
            second = await extract_pdf_page_knowledge(
                document=_document(1),
                rendered=rendered,
                runtime=_runtime(client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=2,
            )

        self.assertTrue(first.complete)
        self.assertEqual(first.accepted_pages, [1])
        self.assertEqual(first.called_pages, [1])
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(first.content_units), 1)
        self.assertEqual(len(first.node_candidates), 1)
        unit = first.content_units[0]
        candidate = first.node_candidates[0]
        self.assertEqual(unit.id, second.content_units[0].id)
        self.assertEqual(unit.page, 1)
        self.assertEqual(unit.bbox, [0.1, 0.2, 0.7, 0.2])
        self.assertEqual(unit.evidence_excerpt, "Δν/ν≈10^-6")
        self.assertEqual(candidate.support_unit_ids, [unit.id])
        self.assertEqual(candidate.evidence[0].unit_id, unit.id)
        self.assertEqual(candidate.evidence[0].page, 1)
        self.assertEqual(candidate.evidence[0].bbox, unit.bbox)
        self.assertEqual(second.called_pages, [])
        self.assertEqual(second.reused_pages, [1])
        metadata = second.document.parse_metadata["pdf_page_knowledge"]
        self.assertTrue(metadata["complete"])
        self.assertEqual(metadata["accepted_pages"], [1])

    async def test_direct_candidate_preserves_canonical_formula_in_definition(
        self,
    ):
        payload = _page_payload(1)
        payload["nodes"][0]["definition"] = "谱线相对宽度约为百万分之一。"

        result, _checkpoint, _calls = await _run_direct_page_fixture(
            [payload],
            max_page_attempts=1,
        )

        self.assertTrue(result.complete)
        self.assertEqual(len(result.node_candidates), 1)
        self.assertEqual(
            result.node_candidates[0].definition,
            "谱线相对宽度约为百万分之一。\nΔν/ν≈10^-6",
        )

    async def test_failed_page_is_omitted_and_blocks_completion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=2)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_page_knowledge_failure",
                task_id="task_page_knowledge_failure",
                mode="precision",
            )
            client = _FakePageKnowledgeClient(
                {
                    1: [_page_payload(1)],
                    2: [_page_payload(2, confidence=0.4)],
                }
            )

            result = await extract_pdf_page_knowledge(
                document=_document(2),
                rendered=rendered,
                runtime=_runtime(client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=2,
                max_page_attempts=1,
            )

        self.assertFalse(result.complete)
        self.assertEqual(result.accepted_pages, [1])
        self.assertEqual(result.failed_pages, [2])
        self.assertEqual(
            {unit.page for unit in result.content_units},
            {1},
        )
        self.assertTrue(
            any(
                "[pdf_knowledge_degraded:page_failure]" in warning
                for warning in result.warnings
            )
        )

    async def test_branch_team_reuses_direct_nodes_without_second_extraction(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered, data_root = _rendered_fixture(root, page_count=1)
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            run_id = blackboard.start_run(
                run_id="run_direct_branch",
                task_id="task_direct_branch",
                mode="precision",
            )
            page_client = _FakePageKnowledgeClient({1: [_page_payload(1)]})
            extracted = await extract_pdf_page_knowledge(
                document=_document(1),
                rendered=rendered,
                runtime=_runtime(page_client),
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256="source-sha",
                prompt_version="page-knowledge-prompt-v1",
                render_dpi=192,
                min_confidence=0.85,
                concurrency=1,
                max_page_attempts=1,
            )
            branch_client = _NoBranchExtractionClient()
            branch = BranchPlan(
                id="branch_laser",
                label="激光",
                unit_ids=[extracted.content_units[0].id],
                coverage_budget=4,
            )

            results = await run_branch_teams(
                [branch],
                extracted.content_units,
                [],
                _runtime(branch_client),
                seed_nodes=extracted.node_candidates,
            )

        self.assertEqual(branch_client.calls, 0)
        self.assertTrue(results[0].used_model)
        direct = [
            node
            for node in results[0].nodes
            if node.role == "formula"
        ]
        self.assertEqual(len(direct), 1)
        self.assertEqual(direct[0].branch_id, branch.id)
        self.assertEqual(
            direct[0].evidence[0].unit_id,
            extracted.content_units[0].id,
        )


if __name__ == "__main__":
    unittest.main()
