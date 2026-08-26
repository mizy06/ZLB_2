from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from backend.app.architecture_schemas import (
    MindMapLoopConfig,
    MindMapLoopRound,
)
from backend.app.blackboard import SQLiteBlackboard
from backend.app.editorial_ppt_pipeline import (
    ARCHITECTURE_NAME,
    PIPELINE_MODE,
    EditorialMindMap,
    EditorialReviewReport,
    _load_cached_render,
    _render_cache_input_hash,
    _validate_review_report,
    editorial_ppt_enabled,
    run_editorial_ppt_pipeline,
)
from backend.app.editorial_ppt_prompts import (
    CONTENT_OMISSION_REVIEWER_PROMPT,
    EDITORIAL_PROMPT_SHA256,
    EDITORIAL_IMAGE_CONTEXT_PROMPT,
    GLOBAL_EDITOR_DRAFT_PROMPT,
    GLOBAL_EDITOR_PATCH_PROMPT,
    GLOBAL_EDITOR_PATCH_REPAIR_PROMPT,
    GLOBAL_EDITOR_REVISION_PROMPT,
    MULTILEVEL_STRUCTURE_REVIEWER_PROMPT,
    PRUNING_REVIEWER_PROMPT,
)
from backend.app.main import health
from backend.app.mindmap_engine.schemas import RenderResponse, RenderedPage
from backend.app.model_provider import ModelProviderError, StoredResponseJSON


def _brief() -> dict:
    return {
        "learning_goal": "理解导数的定义、几何意义与必要条件。",
        "audience": "首次学习导数的大学生",
        "organizing_principle": "按照概念定义、几何解释和适用条件组织。",
        "level_semantics": [
            "根节点表示课程主题",
            "一级节点表示主要知识分区",
            "叶节点表示可独立学习的结论",
        ],
        "importance_policy": "保留定义、原理、条件和关键辨析。",
        "pruning_policy": "删除目录与重复内容，次要说明降级到 definition。",
    }


def _draft_payload(*, revised: bool = False) -> dict:
    nodes = [
        {
            "id": "root",
            "name": "导数概念",
            "role": "root",
            "definition": "导数的定义、几何意义与适用条件。",
            "parent_id": None,
            "source_slides": [1, 2],
            "confidence": 0.94,
        },
        {
            "id": "definition",
            "name": "导数是增量比的极限",
            "role": "definition",
            "definition": "函数增量与自变量增量之比在增量趋零时的极限。",
            "parent_id": "root",
            "source_slides": [1],
            "confidence": 0.91,
        },
    ]
    if revised:
        nodes.append(
            {
                "id": "continuity",
                "name": "可导必连续但连续未必可导",
                "role": "principle",
                "definition": "可导性蕴含连续性，反向关系一般不成立。",
                "parent_id": "root",
                "source_slides": [2],
                "confidence": 0.9,
            }
        )
    return {
        "title": "导数概念",
        "editorial_brief": _brief(),
        "nodes": nodes,
    }


def _empty_report(role: str) -> dict:
    return {
        "reviewer_role": role,
        "summary": "未发现阻断问题。",
        "issues": [],
    }


class _FakeEditorialClient:
    supports_responses = True
    supports_temporary_uploads = True

    def __init__(self):
        self.calls: list[dict] = []
        self.upload_calls: list[dict] = []
        self.content_review_count = 0
        self.response_count = 0

    async def upload_temporary_files(self, **kwargs):
        self.upload_calls.append(kwargs)
        return [
            (label, f"oss://editorial-test/{path.name}")
            for label, path in kwargs["files"]
        ]

    def _payload_for_prompt(self, **kwargs):
        prompt = kwargs["system_prompt"]
        user_prompt = kwargs["user_prompt"]
        if (
            prompt == EDITORIAL_IMAGE_CONTEXT_PROMPT
            and GLOBAL_EDITOR_DRAFT_PROMPT in user_prompt
        ):
            return _draft_payload()
        if (
            prompt == EDITORIAL_IMAGE_CONTEXT_PROMPT
            and CONTENT_OMISSION_REVIEWER_PROMPT in user_prompt
        ):
            self.content_review_count += 1
            if self.content_review_count == 1:
                return {
                    "reviewer_role": "content_omission",
                    "summary": "发现一项重要知识遗漏。",
                    "issues": [
                        {
                            "id": "continuity-missing",
                            "issue_type": "important_omission",
                            "severity": "major",
                            "scope": "global",
                            "affected_node_ids": ["root"],
                            "source_slides": [2],
                            "diagnosis": "当前图没有表达可导与连续的关系。",
                            "why_it_matters": "这是理解可导条件边界的关键辨析。",
                            "suggested_action": "add_node",
                        }
                    ],
                }
            return _empty_report("content_omission")
        if prompt == GLOBAL_EDITOR_PATCH_PROMPT:
            match = re.search(
                r"content_omission:[0-9a-f]{16}",
                kwargs["user_prompt"],
            )
            if match is None:
                raise AssertionError("patch prompt omitted canonical issue ID")
            return {
                "decisions": [
                    {
                        "issue_id": match.group(0),
                        "decision": "accepted",
                        "reason": "补入可导与连续关系作为关键辨析节点。",
                        "affected_node_ids": ["continuity"],
                    }
                ],
                "operations": [
                    {
                        "op": "add_node",
                        "node": _draft_payload(revised=True)["nodes"][-1],
                    }
                ],
            }
        if prompt == GLOBAL_EDITOR_REVISION_PROMPT:
            match = re.search(
                r"content_omission:[0-9a-f]{16}",
                kwargs["user_prompt"],
            )
            if match is None:
                raise AssertionError("revision prompt omitted canonical issue ID")
            return {
                "mindmap": _draft_payload(revised=True),
                "decisions": [
                    {
                        "issue_id": match.group(0),
                        "decision": "accepted",
                        "reason": "补入可导与连续关系作为关键辨析节点。",
                        "affected_node_ids": ["continuity"],
                    }
                ],
            }
        raise AssertionError("unexpected multi-image prompt")

    def _stored_response(self, payload: dict, **kwargs) -> StoredResponseJSON:
        self.response_count += 1
        cached_tokens = 900 if kwargs.get("previous_response_id") else 0
        return StoredResponseJSON(
            payload=payload,
            response_id=f"resp_editorial_{self.response_count}",
            status="completed",
            usage={
                "input_tokens": 1200,
                "input_tokens_details": {
                    "cached_tokens": cached_tokens,
                },
            },
        )

    async def complete_response_json(self, **kwargs):
        self.calls.append({"kind": "response", **kwargs})
        return self._stored_response(
            self._payload_for_prompt(**kwargs),
            **kwargs,
        )

    async def complete_multi_image_json(self, **kwargs):
        self.calls.append({"kind": "images", **kwargs})
        return self._payload_for_prompt(**kwargs)

    async def complete_json(self, **kwargs):
        self.calls.append({"kind": "text", **kwargs})
        prompt = kwargs["system_prompt"]
        if prompt == PRUNING_REVIEWER_PROMPT:
            return _empty_report("pruning")
        if prompt == MULTILEVEL_STRUCTURE_REVIEWER_PROMPT:
            return _empty_report("multilevel_structure")
        raise AssertionError("unexpected text prompt")


class _PatchRecoveryEditorialClient(_FakeEditorialClient):
    def __init__(self, *, repair_succeeds: bool):
        super().__init__()
        self.repair_succeeds = repair_succeeds

    @staticmethod
    def _issue_id(user_prompt: str) -> str:
        match = re.search(
            r"content_omission:[0-9a-f]{16}",
            user_prompt,
        )
        if match is None:
            raise AssertionError("revision prompt omitted canonical issue ID")
        return match.group(0)

    def _valid_patch(self, user_prompt: str) -> dict:
        return {
            "decisions": [
                {
                    "issue_id": self._issue_id(user_prompt),
                    "decision": "accepted",
                    "reason": "补入可导与连续关系作为关键辨析节点。",
                    "affected_node_ids": ["continuity"],
                }
            ],
            "operations": [
                {
                    "op": "add_node",
                    "node": _draft_payload(revised=True)["nodes"][-1],
                }
            ],
        }

    def _invalid_patch(self, user_prompt: str) -> dict:
        return {
            "decisions": [
                {
                    "issue_id": self._issue_id(user_prompt),
                    "decision": "accepted",
                    "reason": "错误地宣称已修复，但没有产生实际图变更。",
                    "affected_node_ids": ["root"],
                }
            ],
            "operations": [],
        }

    async def complete_response_json(self, **kwargs):
        prompt = kwargs["system_prompt"]
        if prompt == GLOBAL_EDITOR_PATCH_PROMPT:
            self.calls.append({"kind": "response", **kwargs})
            return self._stored_response(
                self._invalid_patch(kwargs["user_prompt"]),
                **kwargs,
            )
        if prompt == GLOBAL_EDITOR_PATCH_REPAIR_PROMPT:
            self.calls.append({"kind": "response", **kwargs})
            if self.repair_succeeds:
                payload = self._valid_patch(kwargs["user_prompt"])
            else:
                payload = self._invalid_patch(kwargs["user_prompt"])
            return self._stored_response(payload, **kwargs)
        return await super().complete_response_json(**kwargs)


class _SessionResetEditorialClient(_FakeEditorialClient):
    def __init__(self):
        super().__init__()
        self.failed_continuation = False

    async def complete_response_json(self, **kwargs):
        if (
            not self.failed_continuation
            and kwargs.get("previous_response_id") is not None
        ):
            self.failed_continuation = True
            self.calls.append({"kind": "response", **kwargs})
            raise ModelProviderError("stored response expired")
        return await super().complete_response_json(**kwargs)


class _UnavailableResponsesEditorialClient(_FakeEditorialClient):
    async def complete_response_json(self, **kwargs):
        self.calls.append({"kind": "response", **kwargs})
        raise ModelProviderError("Responses endpoint unavailable")


class _StreamingEditorialClient(_FakeEditorialClient):
    async def complete_response_json(self, **kwargs):
        result = await super().complete_response_json(**kwargs)
        callback = kwargs.get("stream_callback")
        if callback is not None:
            await callback(
                json.dumps(
                    result.payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        return result

    async def complete_json(self, **kwargs):
        result = await super().complete_json(**kwargs)
        callback = kwargs.get("stream_callback")
        if callback is not None:
            await callback(
                json.dumps(
                    result,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        return result


class EditorialPromptContractTests(unittest.TestCase):
    def test_role_prompts_preserve_single_writer_contract(self):
        self.assertIn("唯一的作者", GLOBAL_EDITOR_DRAFT_PROMPT)
        self.assertIn("不计算内容覆盖率", GLOBAL_EDITOR_DRAFT_PROMPT)
        self.assertIn("原始幻灯片", EDITORIAL_IMAGE_CONTEXT_PROMPT)
        self.assertIn("不能直接修改节点", CONTENT_OMISSION_REVIEWER_PROMPT)
        self.assertIn("高精度、低召回", PRUNING_REVIEWER_PROMPT)
        self.assertIn("rewrite_definition", PRUNING_REVIEWER_PROMPT)
        self.assertIn("宏观层 global", MULTILEVEL_STRUCTURE_REVIEWER_PROMPT)
        self.assertIn("当前的 parent_id", MULTILEVEL_STRUCTURE_REVIEWER_PROMPT)
        self.assertIn("最多报告 8 个", MULTILEVEL_STRUCTURE_REVIEWER_PROMPT)
        self.assertIn("diagnosis 不超过 260 字", MULTILEVEL_STRUCTURE_REVIEWER_PROMPT)
        self.assertIn("仍然存在", CONTENT_OMISSION_REVIEWER_PROMPT)
        self.assertIn("沿用历史 issue.id", PRUNING_REVIEWER_PROMPT)
        self.assertIn("不得重复提出", MULTILEVEL_STRUCTURE_REVIEWER_PROMPT)
        self.assertIn("唯一有权修改", GLOBAL_EDITOR_REVISION_PROMPT)
        self.assertIn("每个输入 issue_id", GLOBAL_EDITOR_REVISION_PROMPT)
        self.assertIn("只通过增量 Patch", GLOBAL_EDITOR_PATCH_PROMPT)
        self.assertIn("无效果操作", GLOBAL_EDITOR_PATCH_PROMPT)
        self.assertIn("当前导图仍保持原样", GLOBAL_EDITOR_PATCH_REPAIR_PROMPT)
        self.assertEqual(len(EDITORIAL_PROMPT_SHA256), 8)
        self.assertEqual(len(set(EDITORIAL_PROMPT_SHA256.values())), 8)
        review_schema = EditorialReviewReport.model_json_schema()
        self.assertEqual(
            review_schema["properties"]["issues"]["maxItems"],
            12,
        )
        issue_schema = review_schema["$defs"]["EditorialReviewIssue"]
        self.assertEqual(
            issue_schema["properties"]["diagnosis"]["maxLength"],
            600,
        )
        self.assertEqual(
            issue_schema["properties"]["why_it_matters"]["maxLength"],
            400,
        )

    def test_content_reviewer_cannot_return_pruning_action(self):
        current = EditorialMindMap.model_validate(_draft_payload())
        payload = {
            "reviewer_role": "content_omission",
            "summary": "错误地请求删除节点。",
            "issues": [
                {
                    "id": "bad-action",
                    "issue_type": "important_omission",
                    "severity": "major",
                    "scope": "node",
                    "affected_node_ids": ["definition"],
                    "source_slides": [1],
                    "diagnosis": "测试越权动作。",
                    "why_it_matters": "角色边界必须由代码强制执行。",
                    "suggested_action": "drop_node",
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "越权动作"):
            _validate_review_report(
                payload,
                expected_role="content_omission",
                current=current,
                slide_count=2,
            )

    def test_historical_issue_id_survives_diagnosis_rewording(self):
        current = EditorialMindMap.model_validate(_draft_payload())
        first = _validate_review_report(
            {
                "reviewer_role": "content_omission",
                "summary": "发现遗漏。",
                "issues": [
                    {
                        "id": "temporary",
                        "issue_type": "important_omission",
                        "severity": "major",
                        "scope": "global",
                        "affected_node_ids": ["root"],
                        "source_slides": [2],
                        "diagnosis": "当前图没有表达可导与连续的关系。",
                        "why_it_matters": "缺少关键的条件辨析。",
                        "suggested_action": "add_node",
                    }
                ],
            },
            expected_role="content_omission",
            current=current,
            slide_count=2,
        )
        historical_issue = first.issues[0]
        second = _validate_review_report(
            {
                "reviewer_role": "content_omission",
                "summary": "历史遗漏仍然存在。",
                "issues": [
                    {
                        "id": historical_issue.id,
                        "issue_type": "missing_distinction",
                        "severity": "major",
                        "scope": "global",
                        "affected_node_ids": ["root"],
                        "source_slides": [2],
                        "diagnosis": "尚未说明连续与可导之间的单向关系。",
                        "why_it_matters": "学生会误判两个条件等价。",
                        "suggested_action": "add_node",
                    }
                ],
            },
            expected_role="content_omission",
            current=current,
            slide_count=2,
            historical_issues=[historical_issue],
        )

        self.assertEqual(second.issues[0].id, historical_issue.id)

    def test_pruning_reviewer_can_request_definition_rewrite(self):
        current = EditorialMindMap.model_validate(_draft_payload())
        report = _validate_review_report(
            {
                "reviewer_role": "pruning",
                "summary": "定义过长，可保留节点并压缩表达。",
                "issues": [
                    {
                        "id": "verbose-definition",
                        "issue_type": "redundant_wording",
                        "severity": "major",
                        "scope": "node",
                        "affected_node_ids": ["definition"],
                        "source_slides": [1],
                        "diagnosis": "节点有独立价值，但定义重复父节点内容。",
                        "why_it_matters": "冗长表达降低画布可读性。",
                        "suggested_action": "rewrite_definition",
                    }
                ],
            },
            expected_role="pruning",
            current=current,
            slide_count=2,
        )

        self.assertEqual(
            report.issues[0].suggested_action,
            "rewrite_definition",
        )


class EditorialPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def _run_patch_recovery_fixture(
        self,
        client: _PatchRecoveryEditorialClient,
        *,
        mode: str = "standard",
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "course.pptx"
            source.write_bytes(b"synthetic-pptx")
            data_root = root / "data"
            blackboard = SQLiteBlackboard(data_root / "blackboard.sqlite3")

            def fake_render(
                _source_path,
                _filename,
                render_root,
                _public_base_url,
                _asset_token,
                *,
                max_pages,
                pdf_dpi,
            ):
                self.assertIsNone(max_pages)
                self.assertEqual(pdf_dpi, 120)
                render_id = "render_patch_recovery_test"
                render_dir = render_root / "assets" / render_id
                render_dir.mkdir(parents=True)
                pages = []
                for page_number in (1, 2):
                    page_filename = f"page_{page_number:04d}.png"
                    Image.new("RGB", (640, 360), "white").save(
                        render_dir / page_filename
                    )
                    pages.append(
                        RenderedPage(
                            asset_id=f"page_{page_number:04d}",
                            render_id=render_id,
                            filename=page_filename,
                            url=f"/assets/{page_filename}",
                            page=page_number,
                            width=640,
                            height=360,
                        )
                    )
                return RenderResponse(
                    render_id=render_id,
                    filename="course.pptx",
                    pages=pages,
                    native_visuals=[],
                )

            async def progress(_stage: str, _value: int, _message: str):
                return None

            fake_settings = SimpleNamespace(
                mindmap_data_dir=data_root,
                asset_public_base_url="",
                asset_access_token="",
                qwen_vision_model="qwen-vl-test",
            )
            with (
                patch(
                    "backend.app.editorial_ppt_pipeline.settings",
                    fake_settings,
                ),
                patch.dict(
                    os.environ,
                    {
                        "MINDMAP_EDITORIAL_MAX_REVISIONS": "1",
                        "MINDMAP_EDITORIAL_PATCH_REVISIONS": "true",
                        "MINDMAP_EDITORIAL_FULL_REWRITE_FALLBACK": "",
                    },
                    clear=False,
                ),
            ):
                return await run_editorial_ppt_pipeline(
                    task_id="task-patch-recovery",
                    file_path=source,
                    filename="course.pptx",
                    model="ignored-text-model",
                    provider="qwen",
                    mode=mode,
                    use_ai=True,
                    progress=progress,
                    blackboard=blackboard,
                    client=client,
                    render=fake_render,
                )

    async def test_pipeline_runs_draft_review_and_revision_without_terminal_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "course.pptx"
            source.write_bytes(b"synthetic-pptx")
            data_root = root / "data"
            blackboard = SQLiteBlackboard(data_root / "blackboard.sqlite3")
            client = _FakeEditorialClient()
            progress_events: list[tuple[str, int, str]] = []

            def fake_render(
                _source_path,
                _filename,
                render_root,
                _public_base_url,
                _asset_token,
                *,
                max_pages,
                pdf_dpi,
            ):
                self.assertIsNone(max_pages)
                self.assertEqual(pdf_dpi, 120)
                render_id = "render_editorial_test"
                render_dir = render_root / "assets" / render_id
                render_dir.mkdir(parents=True)
                pages = []
                for page_number, color in (
                    (1, (255, 255, 255)),
                    (2, (220, 235, 255)),
                ):
                    page_filename = f"page_{page_number:04d}.png"
                    Image.new("RGB", (640, 360), color).save(
                        render_dir / page_filename
                    )
                    pages.append(
                        RenderedPage(
                            asset_id=f"page_{page_number:04d}",
                            render_id=render_id,
                            filename=page_filename,
                            url=f"/assets/{page_filename}",
                            page=page_number,
                            width=640,
                            height=360,
                        )
                    )
                return RenderResponse(
                    render_id=render_id,
                    filename="course.pptx",
                    pages=pages,
                    native_visuals=[],
                    warnings=[],
                )

            async def progress(stage: str, value: int, message: str):
                progress_events.append((stage, value, message))

            fake_settings = SimpleNamespace(
                mindmap_data_dir=data_root,
                asset_public_base_url="",
                asset_access_token="",
                qwen_vision_model="qwen-vl-test",
            )
            with (
                patch(
                    "backend.app.editorial_ppt_pipeline.settings",
                    fake_settings,
                ),
                patch.dict(
                    os.environ,
                    {
                        "MINDMAP_EDITORIAL_MAX_REVISIONS": "2",
                        "MINDMAP_EDITORIAL_MAX_DEPTH": "6",
                        "MINDMAP_EDITORIAL_PATCH_REVISIONS": "true",
                        "MINDMAP_EDITORIAL_FULL_REWRITE_FALLBACK": "",
                        "MINDMAP_EDITORIAL_THINKING_BUDGET": "",
                        "MINDMAP_EDITORIAL_REVIEW_THINKING_BUDGET": "",
                        "MINDMAP_EDITORIAL_CONTENT_REVIEW_THINKING_BUDGET": "",
                        "MINDMAP_EDITORIAL_PATCH_THINKING_BUDGET": "",
                        "MINDMAP_EDITORIAL_IMAGE_MAX_EDGE": "",
                        "MINDMAP_EDITORIAL_DRAFT_MAX_OUTPUT_TOKENS": "14000",
                        "MINDMAP_EDITORIAL_REVIEW_MAX_OUTPUT_TOKENS": "12000",
                        "MINDMAP_EDITORIAL_PATCH_MAX_OUTPUT_TOKENS": "7000",
                    },
                    clear=False,
                ),
            ):
                result = await run_editorial_ppt_pipeline(
                    task_id="task-editorial",
                    file_path=source,
                    filename="course.pptx",
                    model="ignored-text-model",
                    provider="qwen",
                    mode="standard",
                    use_ai=True,
                    progress=progress,
                    blackboard=blackboard,
                    client=client,
                    render=fake_render,
                )

            self.assertEqual(len(client.calls), 5)
            self.assertEqual(len(client.upload_calls), 1)
            response_calls = [
                call for call in client.calls if call["kind"] == "response"
            ]
            self.assertEqual(len(response_calls), 3)
            self.assertEqual(
                [label for label, _ in response_calls[0]["images"]],
                ["slide_0001", "slide_0002"],
            )
            self.assertTrue(
                all(
                    url.startswith("oss://editorial-test/")
                    for _, url in response_calls[0]["images"]
                )
            )
            self.assertEqual(response_calls[1]["images"], [])
            self.assertEqual(response_calls[2]["images"], [])
            self.assertIsNone(response_calls[0]["previous_response_id"])
            self.assertEqual(
                response_calls[1]["previous_response_id"],
                "resp_editorial_1",
            )
            self.assertEqual(
                response_calls[2]["previous_response_id"],
                "resp_editorial_2",
            )
            self.assertTrue(
                all(call["session_cache"] for call in response_calls)
            )
            self.assertEqual(
                response_calls[0]["system_prompt"],
                EDITORIAL_IMAGE_CONTEXT_PROMPT,
            )
            self.assertEqual(
                response_calls[1]["system_prompt"],
                EDITORIAL_IMAGE_CONTEXT_PROMPT,
            )
            self.assertIn(
                GLOBAL_EDITOR_DRAFT_PROMPT,
                response_calls[0]["user_prompt"],
            )
            self.assertIn(
                CONTENT_OMISSION_REVIEWER_PROMPT,
                response_calls[1]["user_prompt"],
            )
            self.assertEqual(
                [call["reasoning_effort"] for call in response_calls],
                ["low", "minimal", "minimal"],
            )
            text_calls = [
                call for call in client.calls if call["kind"] == "text"
            ]
            self.assertTrue(text_calls)
            self.assertTrue(
                all(call["max_tokens"] == 4500 for call in text_calls)
            )
            self.assertEqual(
                result.document.parse_metadata["model_call_count"],
                5,
            )
            self.assertEqual(result.solver_status, "EDITORIAL_MODEL_TREE")
            self.assertEqual(result.quality_report.coverage.total_units, 0)
            self.assertEqual(
                result.quality_report.weighted_content_coverage,
                0,
            )
            self.assertTrue(result.quality_report.quality_gate_passed)
            self.assertEqual(result.run_manifest["final_review_issue_count"], 0)
            self.assertFalse(result.run_manifest["terminal_review_performed"])
            self.assertEqual(result.run_manifest["max_editorial_revisions"], 1)
            self.assertFalse(
                result.run_manifest["patch_revision_full_rewrite_fallback"]
            )
            self.assertEqual(
                result.run_manifest["image_context_cache_policy"],
                "responses-previous-response-session-cache-v1",
            )
            self.assertEqual(
                result.run_manifest["editorial_image_transport"],
                "dashscope_temporary_oss",
            )
            self.assertEqual(result.run_manifest["responses_chain_length"], 3)
            self.assertEqual(
                result.run_manifest["responses_cache_hit_count"],
                2,
            )
            self.assertEqual(
                result.run_manifest["responses_cached_tokens_total"],
                1800,
            )
            self.assertEqual(
                result.run_manifest["responses_chat_fallback_count"],
                0,
            )
            public_manifest = json.dumps(
                result.run_manifest,
                ensure_ascii=False,
            )
            self.assertNotIn("resp_editorial_", public_manifest)
            self.assertNotIn("oss://editorial-test/", public_manifest)
            self.assertEqual(
                result.run_manifest["editorial_image_max_edge"],
                1280,
            )
            self.assertEqual(
                result.run_manifest["draft_max_output_tokens"],
                9000,
            )
            self.assertEqual(
                result.run_manifest["review_max_output_tokens"],
                4500,
            )
            self.assertEqual(
                result.run_manifest["content_review_max_output_tokens"],
                3500,
            )
            self.assertEqual(
                result.run_manifest["patch_max_output_tokens"],
                4500,
            )
            self.assertEqual(
                result.run_manifest["convergence_reason"],
                "revision_budget_completed_without_terminal_review",
            )
            self.assertEqual(len(result.decision_records), 1)
            self.assertIn(
                "可导必连续但连续未必可导",
                [node.name for node in result.nodes],
            )
            self.assertTrue(
                all(not node.media_asset_ids for node in result.nodes)
            )
            self.assertTrue(
                all(asset.visual_kind == "full_slide" for asset in result.assets)
            )
            self.assertTrue(
                all(
                    evidence.asset_id
                    for node in result.nodes
                    for evidence in node.evidence
                )
            )
            self.assertIn(
                "editorial_review",
                [stage for stage, _, _ in progress_events],
            )
            session = blackboard.load_checkpoint(
                result.run_id,
                "editorial_response_session",
            )
            self.assertEqual(
                [item["image_count"] for item in session["chain"]],
                [2, 0, 0],
            )
            stored = blackboard.load_latest_result("task-editorial")
            self.assertIsNotNone(stored)
            self.assertEqual(stored.root_id, result.root_id)

    async def test_custom_loop_uses_selected_roles_models_and_stream_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "course.pptx"
            source.write_bytes(b"synthetic-pptx")
            data_root = root / "data"
            blackboard = SQLiteBlackboard(data_root / "blackboard.sqlite3")
            client = _StreamingEditorialClient()
            stream_events: list[dict] = []

            def fake_render(
                _source_path,
                _filename,
                render_root,
                _public_base_url,
                _asset_token,
                *,
                max_pages,
                pdf_dpi,
            ):
                self.assertIsNone(max_pages)
                self.assertEqual(pdf_dpi, 120)
                render_id = "render_custom_loop_test"
                render_dir = render_root / "assets" / render_id
                render_dir.mkdir(parents=True)
                pages = []
                for page_number in (1, 2):
                    page_filename = f"page_{page_number:04d}.png"
                    Image.new("RGB", (640, 360), "white").save(
                        render_dir / page_filename
                    )
                    pages.append(
                        RenderedPage(
                            asset_id=f"page_{page_number:04d}",
                            render_id=render_id,
                            filename=page_filename,
                            url=f"/assets/{page_filename}",
                            page=page_number,
                            width=640,
                            height=360,
                        )
                    )
                return RenderResponse(
                    render_id=render_id,
                    filename="course.pptx",
                    pages=pages,
                    native_visuals=[],
                )

            async def progress(_stage: str, _value: int, _message: str):
                return None

            async def model_output(event: dict):
                stream_events.append(event)

            loop_config = MindMapLoopConfig(
                rounds=[
                    MindMapLoopRound(
                        editor_model="qwen-editor-model",
                        content_omission_model="qwen-review-model",
                    )
                ]
            )
            fake_settings = SimpleNamespace(
                mindmap_data_dir=data_root,
                asset_public_base_url="",
                asset_access_token="",
                qwen_vision_model="qwen-vl-test",
            )
            with (
                patch(
                    "backend.app.editorial_ppt_pipeline.settings",
                    fake_settings,
                ),
                patch.dict(
                    os.environ,
                    {
                        "MINDMAP_EDITORIAL_PATCH_REVISIONS": "false",
                    },
                    clear=False,
                ),
            ):
                result = await run_editorial_ppt_pipeline(
                    task_id="task-custom-loop",
                    file_path=source,
                    filename="course.pptx",
                    model="legacy-model-is-not-used",
                    provider="qwen",
                    mode="standard",
                    use_ai=True,
                    progress=progress,
                    blackboard=blackboard,
                    loop_config=loop_config,
                    model_output=model_output,
                    client=client,
                    render=fake_render,
                )

            self.assertEqual(
                [call["model"] for call in client.calls],
                [
                    "qwen-editor-model",
                    "qwen-review-model",
                    "qwen-editor-model",
                ],
            )
            self.assertFalse(
                any(
                    call.get("system_prompt") == PRUNING_REVIEWER_PROMPT
                    for call in client.calls
                )
            )
            self.assertFalse(
                any(
                    call.get("system_prompt")
                    == MULTILEVEL_STRUCTURE_REVIEWER_PROMPT
                    for call in client.calls
                )
            )
            self.assertEqual(
                [event["kind"] for event in stream_events].count(
                    "model_delta"
                ),
                3,
            )
            self.assertEqual(
                result.run_manifest["loop_config"],
                loop_config.model_dump(mode="json"),
            )
            self.assertTrue(result.run_manifest["loop_configurable"])
            self.assertEqual(result.run_manifest["actual_model_calls"], 3)

    async def test_second_review_receives_historical_issue_and_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "course.pptx"
            source.write_bytes(b"synthetic-pptx")
            data_root = root / "data"
            blackboard = SQLiteBlackboard(data_root / "blackboard.sqlite3")
            client = _FakeEditorialClient()

            def fake_render(
                _source_path,
                _filename,
                render_root,
                _public_base_url,
                _asset_token,
                *,
                max_pages,
                pdf_dpi,
            ):
                self.assertIsNone(max_pages)
                self.assertEqual(pdf_dpi, 120)
                render_id = "render_history_test"
                render_dir = render_root / "assets" / render_id
                render_dir.mkdir(parents=True)
                pages = []
                for page_number in (1, 2):
                    page_filename = f"page_{page_number:04d}.png"
                    Image.new("RGB", (640, 360), "white").save(
                        render_dir / page_filename
                    )
                    pages.append(
                        RenderedPage(
                            asset_id=f"page_{page_number:04d}",
                            render_id=render_id,
                            filename=page_filename,
                            url=f"/assets/{page_filename}",
                            page=page_number,
                            width=640,
                            height=360,
                        )
                    )
                return RenderResponse(
                    render_id=render_id,
                    filename="course.pptx",
                    pages=pages,
                    native_visuals=[],
                )

            async def progress(_stage: str, _value: int, _message: str):
                return None

            fake_settings = SimpleNamespace(
                mindmap_data_dir=data_root,
                asset_public_base_url="",
                asset_access_token="",
                qwen_vision_model="qwen-vl-test",
            )
            with (
                patch(
                    "backend.app.editorial_ppt_pipeline.settings",
                    fake_settings,
                ),
                patch.dict(
                    os.environ,
                    {
                        "MINDMAP_EDITORIAL_MAX_REVISIONS": "2",
                        "MINDMAP_EDITORIAL_PATCH_REVISIONS": "true",
                        "MINDMAP_EDITORIAL_FULL_REWRITE_FALLBACK": "",
                    },
                    clear=False,
                ),
            ):
                result = await run_editorial_ppt_pipeline(
                    task_id="task-editorial-history",
                    file_path=source,
                    filename="course.pptx",
                    model="ignored-text-model",
                    provider="qwen",
                    mode="precision",
                    use_ai=True,
                    progress=progress,
                    blackboard=blackboard,
                    client=client,
                    render=fake_render,
                )

            content_calls = [
                call
                for call in client.calls
                if (
                    call["kind"] == "response"
                    and CONTENT_OMISSION_REVIEWER_PROMPT
                    in call["user_prompt"]
                )
            ]
            self.assertEqual(len(content_calls), 2)
            second_prompt = content_calls[1]["user_prompt"]
            self.assertIn('"historical_review_items":[', second_prompt)
            self.assertRegex(
                second_prompt,
                r"content_omission:[0-9a-f]{16}",
            )
            self.assertIn('"decision":"accepted"', second_prompt)
            self.assertEqual(
                result.run_manifest["convergence_reason"],
                "no_blocking_issues",
            )
            self.assertEqual(result.run_manifest["actual_model_calls"], 8)

    async def test_invalid_patch_is_repaired_once(self):
        client = _PatchRecoveryEditorialClient(repair_succeeds=True)

        result = await self._run_patch_recovery_fixture(client)

        self.assertEqual(result.run_manifest["patch_attempt_count"], 1)
        self.assertEqual(result.run_manifest["patch_repair_count"], 1)
        self.assertEqual(
            result.run_manifest["patch_full_rewrite_fallback_count"],
            0,
        )
        self.assertEqual(result.run_manifest["actual_model_calls"], 6)
        self.assertIn(
            "可导必连续但连续未必可导",
            [node.name for node in result.nodes],
        )
        self.assertTrue(result.quality_report.quality_gate_passed)

    async def test_standard_mode_preserves_graph_when_patch_repair_fails(self):
        client = _PatchRecoveryEditorialClient(repair_succeeds=False)

        result = await self._run_patch_recovery_fixture(client)

        self.assertEqual(result.run_manifest["patch_attempt_count"], 1)
        self.assertEqual(result.run_manifest["patch_repair_count"], 1)
        self.assertEqual(
            result.run_manifest["patch_full_rewrite_fallback_count"],
            0,
        )
        self.assertEqual(result.run_manifest["patch_failed_preserve_count"], 1)
        self.assertEqual(result.run_manifest["actual_model_calls"], 6)
        self.assertNotIn(
            "可导必连续但连续未必可导",
            [node.name for node in result.nodes],
        )
        self.assertEqual(
            result.run_manifest["convergence_reason"],
            "patch_revision_failed_preserved_previous",
        )
        self.assertTrue(
            any("保留上一有效版本" in warning for warning in result.warnings)
        )

    async def test_precision_mode_can_fall_back_to_full_rewrite(self):
        client = _PatchRecoveryEditorialClient(repair_succeeds=False)

        result = await self._run_patch_recovery_fixture(
            client,
            mode="precision",
        )

        self.assertTrue(
            result.run_manifest["patch_revision_full_rewrite_fallback"]
        )
        self.assertEqual(
            result.run_manifest["patch_full_rewrite_fallback_count"],
            1,
        )
        self.assertEqual(result.run_manifest["patch_failed_preserve_count"], 0)
        self.assertEqual(result.run_manifest["actual_model_calls"], 7)
        self.assertIn(
            "可导必连续但连续未必可导",
            [node.name for node in result.nodes],
        )
        self.assertTrue(
            any("回退到完整图重写" in warning for warning in result.warnings)
        )

    async def test_expired_response_chain_is_rebuilt_with_same_stable_urls(
        self,
    ):
        client = _SessionResetEditorialClient()

        result = await self._run_patch_recovery_fixture(client)

        response_calls = [
            call for call in client.calls if call["kind"] == "response"
        ]
        self.assertEqual(response_calls[0]["images"][0][0], "slide_0001")
        self.assertEqual(response_calls[1]["images"], [])
        self.assertIsNotNone(response_calls[1]["previous_response_id"])
        self.assertEqual(
            [label for label, _ in response_calls[2]["images"]],
            ["slide_0001", "slide_0002"],
        )
        self.assertIsNone(response_calls[2]["previous_response_id"])
        self.assertEqual(
            result.run_manifest["responses_chain_reset_count"],
            1,
        )
        self.assertEqual(
            result.run_manifest["responses_chat_fallback_count"],
            0,
        )
        self.assertTrue(
            any("重建上下文" in warning for warning in result.warnings)
        )

    async def test_unavailable_responses_falls_back_to_chat_with_urls(self):
        client = _UnavailableResponsesEditorialClient()

        result = await self._run_patch_recovery_fixture(client)

        image_calls = [
            call for call in client.calls if call["kind"] == "images"
        ]
        self.assertTrue(image_calls)
        self.assertTrue(
            all(
                url.startswith("oss://editorial-test/")
                for call in image_calls
                for _, url in call["images"]
            )
        )
        self.assertEqual(result.run_manifest["responses_chain_length"], 0)
        self.assertGreater(
            result.run_manifest["responses_chat_fallback_count"],
            0,
        )
        self.assertFalse(result.run_manifest["responses_api_final_active"])

    async def test_pipeline_rejects_non_pptx_before_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "course.pdf"
            source.write_bytes(b"%PDF-synthetic")
            client = _FakeEditorialClient()

            async def progress(_stage: str, _value: int, _message: str):
                return None

            with self.assertRaisesRegex(ValueError, "仅支持 PPTX"):
                await run_editorial_ppt_pipeline(
                    task_id="task-pdf",
                    file_path=source,
                    filename="course.pdf",
                    model="qwen-vl-test",
                    provider="qwen",
                    mode="standard",
                    use_ai=True,
                    progress=progress,
                    blackboard=SQLiteBlackboard(
                        root / "blackboard.sqlite3"
                    ),
                    client=client,
                )
            self.assertEqual(client.calls, [])


class EditorialRenderCacheTests(unittest.TestCase):
    def test_render_checkpoint_is_reused_for_same_source_and_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_root = root / "data"
            blackboard = SQLiteBlackboard(data_root / "blackboard.sqlite3")
            run_one = blackboard.start_run(
                run_id="run_cache_one",
                task_id="task-cache-one",
                mode="standard",
            )
            run_two = blackboard.start_run(
                run_id="run_cache_two",
                task_id="task-cache-two",
                mode="standard",
            )
            render_id = "rendercachetest"
            render_dir = data_root / "assets" / render_id
            render_dir.mkdir(parents=True)
            page_filename = "page_0001.png"
            Image.new("RGB", (640, 360), "white").save(
                render_dir / page_filename
            )
            rendered = RenderResponse(
                render_id=render_id,
                filename="first-name.pptx",
                pages=[
                    RenderedPage(
                        asset_id="page_0001",
                        render_id=render_id,
                        filename=page_filename,
                        url="/assets/page_0001.png",
                        page=1,
                        width=640,
                        height=360,
                    )
                ],
                native_visuals=[],
            )
            fake_settings = SimpleNamespace(
                mindmap_data_dir=data_root,
                asset_public_base_url="",
                asset_access_token="",
            )

            def fake_render():
                return None

            with patch(
                "backend.app.editorial_ppt_pipeline.settings",
                fake_settings,
            ):
                input_hash = _render_cache_input_hash(
                    source_digest="a" * 64,
                    render_dpi=120,
                    render=fake_render,
                )
                blackboard.checkpoint(
                    run_one,
                    "editorial_render",
                    {
                        "input_hash": input_hash,
                        "rendered": rendered,
                        "render_dpi": 120,
                    },
                )
                cached = _load_cached_render(
                    blackboard=blackboard,
                    run_id=run_two,
                    input_hash=input_hash,
                    filename="second-name.pptx",
                )

            self.assertIsNotNone(cached)
            cached_run_id, cached_render = cached
            self.assertEqual(cached_run_id, run_one)
            self.assertEqual(cached_render.filename, "second-name.pptx")
            self.assertEqual(cached_render.render_id, render_id)


class EditorialModeTests(unittest.TestCase):
    def test_pipeline_mode_is_opt_in(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MINDMAP_PIPELINE_MODE", None)
            self.assertFalse(editorial_ppt_enabled())
        with patch.dict(
            os.environ,
            {"MINDMAP_PIPELINE_MODE": PIPELINE_MODE},
        ):
            self.assertTrue(editorial_ppt_enabled())

    def test_health_describes_editorial_architecture(self):
        with patch.dict(
            os.environ,
            {"MINDMAP_PIPELINE_MODE": PIPELINE_MODE},
        ):
            payload = asyncio.run(health())
        self.assertEqual(payload["architecture"]["name"], ARCHITECTURE_NAME)
        self.assertEqual(
            payload["architecture"]["graph_validator"],
            "pydantic-local-tree+multi-role-review",
        )
        self.assertEqual(
            payload["supported_extensions"],
            [
                ".doc",
                ".docx",
                ".markdown",
                ".md",
                ".pdf",
                ".ppt",
                ".pptx",
                ".txt",
            ],
        )


if __name__ == "__main__":
    unittest.main()
