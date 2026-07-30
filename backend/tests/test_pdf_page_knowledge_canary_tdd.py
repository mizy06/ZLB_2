from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from backend.app.schemas import ParsedDocument, SourceBlock
from backend.app.pdf_page_knowledge import PageKnowledgeExtraction
from backend.tools import pdf_page_knowledge_canary as canary
from backend.tools.pdf_page_knowledge_canary import (
    _canary_manifest,
    _model_call_summary,
    _page_reports,
    _remap_document,
    _validate_canary_runtime_settings,
)


class PdfPageKnowledgeCanaryTests(unittest.TestCase):
    def test_formal_canary_requires_production_environment(self):
        configured = replace(
            canary.settings,
            environment="development",
            qwen_api_key="sk-standard-placeholder",
            qwen_base_url=(
                "https://dashscope.aliyuncs.com/compatible-mode/v1"
            ),
            qwen_model="qwen3.7-max",
            qwen_vision_model="qwen3.7-plus",
        )

        with self.assertRaisesRegex(RuntimeError, "MINDMAP_ENV=production"):
            _validate_canary_runtime_settings(configured)

    def test_formal_canary_rejects_token_plan_before_model_calls(self):
        configured = replace(
            canary.settings,
            environment="production",
            qwen_api_key="sk-sp-placeholder",
            qwen_base_url=(
                "https://dashscope.aliyuncs.com/compatible-mode/v1"
            ),
            qwen_model="qwen3.7-max",
            qwen_vision_model="qwen3.7-plus",
        )

        with self.assertRaisesRegex(RuntimeError, "token_plan_key"):
            _validate_canary_runtime_settings(configured)

    def test_formal_canary_accepts_static_standard_qwen_contract(self):
        configured = replace(
            canary.settings,
            environment="production",
            qwen_api_key="sk-standard-placeholder",
            qwen_base_url=(
                "https://dashscope.aliyuncs.com/compatible-mode/v1"
            ),
            qwen_model="qwen3.7-max",
            qwen_vision_model="qwen3.7-plus",
        )

        _validate_canary_runtime_settings(configured)

    def test_formal_canary_accepts_explicit_cn_token_plan_preview_profile(self):
        configured = replace(
            canary.settings,
            environment="production",
            qwen_api_key="sk-sp-placeholder",
            qwen_base_url=(
                "https://token-plan.cn-beijing.maas.aliyuncs.com/"
                "compatible-mode/v1"
            ),
            qwen_model="qwen3.8-max-preview",
            qwen_vision_model="qwen3.8-max-preview",
            qwen_production_profile="approved_cn_token_plan_preview",
        )

        _validate_canary_runtime_settings(configured)

    def test_manifest_records_sanitized_provider_and_runtime_identity(self):
        configured = replace(
            canary.settings,
            qwen_base_url=(
                "https://user:secret@provider.example/v1/?token=hidden"
            ),
            qwen_model="qwen3.7-max",
            qwen_vision_model="qwen3.7-plus",
            qwen_secret_source="age",
            qwen_production_profile="standard",
            pdf_page_extraction_mode="direct_layout_fallback",
        )
        versions = {
            "python": "3.12.11",
            "pypdf": "6.14.2",
            "pdfplumber": "0.11.10",
            "pdfminer.six": "20260107",
            "pylatexenc": "2.11",
            "poppler": "25.03.0",
        }
        with (
            patch.object(canary, "settings", configured),
            patch.object(canary, "runtime_versions", return_value=versions),
        ):
            manifest = _canary_manifest(
                source_sha256="source-sha",
                source_page_count=92,
                pages=(17, 42),
                render_dpi=192,
                concurrency=8,
                max_attempts=3,
                min_confidence=0.85,
            )

        self.assertEqual(
            manifest["provider_endpoint"],
            "https://provider.example/v1",
        )
        self.assertEqual(manifest["text_model"], "qwen3.7-max")
        self.assertEqual(manifest["vision_model"], "qwen3.7-plus")
        self.assertEqual(manifest["credential_source"], "age")
        self.assertEqual(manifest["qwen_production_profile"], "standard")
        self.assertEqual(manifest["runtime_versions"], versions)
        self.assertEqual(
            manifest["schema_versions"]["page_knowledge"],
            canary.PAGE_KNOWLEDGE_SCHEMA_VERSION,
        )
        self.assertEqual(
            manifest["prompt"]["sha256"],
            canary.PDF_PAGE_KNOWLEDGE_PROMPT_SHA256,
        )
        self.assertEqual(
            manifest["runner"]["sha256"],
            canary._sha256(Path(canary.__file__).resolve()),
        )
        self.assertNotIn("secret", str(manifest))
        self.assertNotIn("hidden", str(manifest))

    def test_remaps_selected_pages_without_carrying_unselected_blocks(self):
        source = ParsedDocument(
            document_id="doc_source",
            filename="source.pdf",
            file_type="pdf",
            title="Source",
            blocks=[
                SourceBlock(text="page two", page=2, heading="A"),
                SourceBlock(text="page six", page=6, heading="B"),
                SourceBlock(text="page eleven", page=11, heading="C"),
            ],
            parse_metadata={
                "pdf_page_count": 92,
                "pdf_geometry_math": {
                    "attempted_pages": [6, 34],
                    "candidates": [
                        {
                            "page": 6,
                            "canonical": "A=B",
                        }
                    ],
                    "injected_into_text": False,
                },
            },
            warnings=["source warning"],
        )

        remapped, original_to_mapped, mapped_to_original = _remap_document(
            source,
            (6, 2),
        )

        self.assertEqual(original_to_mapped, {6: 1, 2: 2})
        self.assertEqual(mapped_to_original, {1: 6, 2: 2})
        self.assertEqual(
            [(block.page, block.text) for block in remapped.blocks],
            [(2, "page two"), (1, "page six")],
        )
        self.assertEqual(remapped.parse_metadata["pdf_page_count"], 2)
        self.assertEqual(
            remapped.parse_metadata["original_page_map"],
            {"1": 6, "2": 2},
        )
        self.assertEqual(
            remapped.parse_metadata["pdf_geometry_math"],
            source.parse_metadata["pdf_geometry_math"],
        )
        self.assertEqual(remapped.warnings, [])

    def test_model_call_summary_checks_bounded_production_policy(self):
        model_calls = [
            {
                "item_id": "call-1",
                "status": "success",
                "latency_ms": 1200,
                "input_unit_ids": ["page:1"],
                "details": {
                    "request_policy": {
                        "max_completion_tokens": 5000,
                        "thinking_budget": 1024,
                        "timeout_seconds": 90.0,
                    },
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 50,
                        "total_tokens": 150,
                    },
                    "finish_reason": "stop",
                    "status_code": 200,
                },
            },
            {
                "item_id": "call-2",
                "status": "success",
                "latency_ms": 2400,
                "input_unit_ids": ["page:2"],
                "details": {
                    "request_policy": {
                        "max_completion_tokens": 5000,
                        "thinking_budget": 1024,
                        "timeout_seconds": 90.0,
                    },
                    "usage": {
                        "prompt_tokens": 80,
                        "completion_tokens": 40,
                        "total_tokens": 120,
                    },
                    "finish_reason": "stop",
                    "status_code": 200,
                },
            },
        ]

        summary = _model_call_summary(model_calls)

        self.assertTrue(summary["request_policy_all_match"])
        self.assertEqual(summary["usage"]["prompt_tokens"], 180)
        self.assertEqual(summary["usage"]["completion_tokens"], 90)
        self.assertEqual(summary["usage"]["total_tokens"], 270)
        self.assertEqual(summary["finish_reason_counts"], {"stop": 2})
        self.assertEqual(summary["latency_seconds"]["p50"], 1.2)
        self.assertEqual(summary["latency_seconds"]["p95"], 2.4)

    def test_model_call_summary_accepts_profile_specific_policies(self):
        model_calls = [
            {
                "item_id": "direct",
                "role": "page_knowledge",
                "status": "success",
                "latency_ms": 1000,
                "details": {
                    "request_policy": {
                        "max_completion_tokens": 5000,
                        "thinking_budget": 1024,
                        "timeout_seconds": 90.0,
                    },
                },
            },
            {
                "item_id": "layout-first",
                "role": "page_layout_dots",
                "status": "success",
                "latency_ms": 2000,
                "details": {
                    "request_policy": {
                        "max_completion_tokens": 13096,
                        "thinking_budget": 4096,
                        "timeout_seconds": 120.0,
                    },
                },
            },
            {
                "item_id": "layout-retry",
                "role": "page_layout_dots",
                "status": "success",
                "latency_ms": 3000,
                "details": {
                    "request_policy": {
                        "max_completion_tokens": 13096,
                        "thinking_budget": 4096,
                        "timeout_seconds": 180.0,
                    },
                },
            },
            {
                "item_id": "selector",
                "role": "page_layout_nodes",
                "status": "success",
                "latency_ms": 4000,
                "details": {
                    "request_policy": {
                        "max_completion_tokens": 4036,
                        "thinking_budget": 1536,
                        "timeout_seconds": 120.0,
                    },
                },
            },
        ]

        summary = _model_call_summary(model_calls)

        self.assertTrue(summary["request_policy_all_match"])
        self.assertEqual(
            summary["request_policy_by_role"]["page_layout_dots"],
            {
                "call_count": 2,
                "expected": {
                    "max_completion_tokens": 13096,
                    "thinking_budget": 4096,
                    "timeout_seconds": [120.0, 180.0],
                },
                "all_match": True,
            },
        )
        self.assertTrue(
            summary["request_policy_by_role"]["page_layout_nodes"][
                "all_match"
            ]
        )

    def test_page_report_distinguishes_direct_and_fallback_checkpoints(self):
        extraction = PageKnowledgeExtraction(
            page=1,
            complete=True,
            confidence=0.98,
            heading="公式",
            has_knowledge=False,
            no_knowledge_reason="页面只有章节导航，没有可发布知识。",
            nodes=[],
        )
        result = type(
            "Result",
            (),
            {
                "extractions": [extraction],
                "degraded_pages": [1],
            },
        )()
        checkpoints = [
            {
                "stage": "page_knowledge:0001",
                "payload": {
                    "status": "failed",
                    "issues": ["direct_failed"],
                },
            },
            {
                "stage": "page_knowledge:layout_nodes:0001",
                "payload": {
                    "status": "accepted",
                    "issues": [],
                },
            },
        ]

        reports = _page_reports(
            result=result,
            checkpoints=checkpoints,
            mapped_to_original={1: 17},
        )

        self.assertEqual(reports[0]["status"], "degraded")
        self.assertEqual(reports[0]["direct_status"], "failed")
        self.assertEqual(reports[0]["fallback_status"], "accepted")
        self.assertTrue(reports[0]["fallback_attempted"])


if __name__ == "__main__":
    unittest.main()
