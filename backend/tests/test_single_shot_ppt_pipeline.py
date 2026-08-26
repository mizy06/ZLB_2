from __future__ import annotations

import asyncio
import base64
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image
from pydantic import ValidationError

from backend.app.blackboard import SQLiteBlackboard
from backend.app.config import settings
from backend.app.mindmap_engine.schemas import RenderResponse, RenderedPage
from backend.app.main import _pipeline_family, health
from backend.app.model_provider import OpenAICompatibleClient
from backend.app.single_shot_ppt_pipeline import (
    PIPELINE_MODE,
    SingleShotMindMap,
    _encode_slide_images,
    run_single_shot_ppt_pipeline,
    single_shot_ppt_enabled,
)


def _model_payload() -> dict:
    return {
        "title": "导数概念",
        "nodes": [
            {
                "id": "root",
                "name": "导数概念",
                "role": "root",
                "definition": "导数的概念、几何意义与计算基础。",
                "parent_id": None,
                "source_slides": [1, 2],
                "confidence": 0.94,
            },
            {
                "id": "definition",
                "name": "导数定义",
                "role": "definition",
                "definition": "函数增量与自变量增量之比的极限。",
                "parent_id": "root",
                "source_slides": [1],
                "confidence": 0.9,
            },
            {
                "id": "geometry",
                "name": "几何意义",
                "role": "concept",
                "definition": "导数表示曲线在给定点处切线的斜率。",
                "parent_id": "root",
                "source_slides": [2],
                "confidence": 0.88,
            },
        ],
    }


class MultiImageClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_multi_image_completion_uses_one_labeled_user_message(self):
        client = OpenAICompatibleClient(
            settings=settings,
            api_key="test-key",
            base_url="https://example.invalid/v1",
            provider_name="Qwen",
            api_key_env_name="QWEN_API_KEY",
            temperature=0,
        )
        client._chat = AsyncMock(return_value='{"ok":true}')

        result = await client.complete_multi_image_json(
            model="qwen-vl-test",
            system_prompt="system",
            user_prompt="build map",
            images=[
                ("slide_0001", "data:image/jpeg;base64,AAA"),
                ("slide_0002", "data:image/jpeg;base64,BBB"),
            ],
            max_attempts=1,
        )

        self.assertEqual(result, {"ok": True})
        client._chat.assert_awaited_once()
        kwargs = client._chat.await_args.kwargs
        self.assertEqual(kwargs["max_attempts"], 1)
        self.assertEqual(len(kwargs["messages"]), 2)
        content = kwargs["messages"][1]["content"]
        self.assertEqual(
            [part["type"] for part in content],
            ["text", "text", "image_url", "text", "image_url"],
        )
        self.assertEqual(content[1]["text"], "vision_id=slide_0001")
        self.assertEqual(content[3]["text"], "vision_id=slide_0002")

    async def test_multi_image_completion_can_cache_static_image_prefix(self):
        client = OpenAICompatibleClient(
            settings=settings,
            api_key="test-key",
            base_url="https://example.invalid/v1",
            provider_name="Qwen",
            api_key_env_name="QWEN_API_KEY",
            temperature=0,
        )
        client._chat = AsyncMock(return_value='{"ok":true}')

        await client.complete_multi_image_json(
            model="qwen-vl-test",
            system_prompt="system",
            user_prompt="review current graph",
            images=[
                ("slide_0001", "data:image/jpeg;base64,AAA"),
                ("slide_0002", "data:image/jpeg;base64,BBB"),
            ],
            cache_static_images=True,
            max_attempts=1,
        )

        messages = client._chat.await_args.kwargs["messages"]
        self.assertEqual(len(messages), 3)
        content = messages[1]["content"]
        self.assertEqual(
            [part["type"] for part in content],
            [
                "text",
                "image_url",
                "text",
                "image_url",
                "text",
            ],
        )
        self.assertEqual(content[0]["text"], "vision_id=slide_0001")
        self.assertEqual(content[2]["text"], "vision_id=slide_0002")
        self.assertEqual(
            content[4]["cache_control"],
            {"type": "ephemeral"},
        )
        self.assertEqual(messages[2]["content"], "review current graph")

    async def test_cached_image_prefix_is_stable_across_dynamic_tasks(self):
        client = OpenAICompatibleClient(
            settings=settings,
            api_key="test-key",
            base_url="https://example.invalid/v1",
            provider_name="Qwen",
            api_key_env_name="QWEN_API_KEY",
            temperature=0,
        )
        client._chat = AsyncMock(return_value='{"ok":true}')
        images = [
            ("slide_0001", "data:image/jpeg;base64,AAA"),
            ("slide_0002", "data:image/jpeg;base64,BBB"),
        ]

        await client.complete_multi_image_json(
            model="qwen-vl-test",
            system_prompt="shared editorial image context",
            user_prompt="build draft",
            images=images,
            cache_static_images=True,
            max_attempts=1,
        )
        await client.complete_multi_image_json(
            model="qwen-vl-test",
            system_prompt="shared editorial image context",
            user_prompt="review omissions",
            images=images,
            cache_static_images=True,
            max_attempts=1,
        )

        first_messages = client._chat.await_args_list[0].kwargs["messages"]
        second_messages = client._chat.await_args_list[1].kwargs["messages"]
        self.assertEqual(first_messages[:2], second_messages[:2])
        self.assertEqual(first_messages[2]["content"], "build draft")
        self.assertEqual(second_messages[2]["content"], "review omissions")


class SingleShotSchemaTests(unittest.TestCase):
    def test_tree_schema_rejects_cycles(self):
        payload = _model_payload()
        payload["nodes"][1]["parent_id"] = "geometry"
        payload["nodes"][2]["parent_id"] = "definition"

        with self.assertRaises(ValidationError):
            SingleShotMindMap.model_validate(payload)

    def test_pipeline_mode_is_opt_in(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MINDMAP_PIPELINE_MODE", None)
            self.assertFalse(single_shot_ppt_enabled())
        with patch.dict(
            os.environ,
            {"MINDMAP_PIPELINE_MODE": PIPELINE_MODE},
        ):
            self.assertTrue(single_shot_ppt_enabled())

    def test_health_describes_the_experiment_contract(self):
        with patch.dict(
            os.environ,
            {"MINDMAP_PIPELINE_MODE": PIPELINE_MODE},
        ):
            payload = asyncio.run(health())
        self.assertEqual(
            payload["architecture"]["name"],
            "single-shot-ppt-vision",
        )
        self.assertEqual(
            payload["architecture"]["topology_solver"],
            "disabled",
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

    def test_single_shot_mode_only_claims_normalized_pptx(self):
        with patch.dict(
            os.environ,
            {"MINDMAP_PIPELINE_MODE": PIPELINE_MODE},
        ):
            self.assertEqual(
                _pipeline_family(Path("course.pptx")),
                "single-shot",
            )
            self.assertEqual(_pipeline_family(Path("course.pdf")), "cplus")
            self.assertEqual(_pipeline_family(Path("course.docx")), "cplus")
            self.assertEqual(_pipeline_family(Path("course.md")), "cplus")

    def test_editorial_image_encoding_defaults_to_1280_long_edge(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            render_id = "render_editorial_edge"
            render_dir = data_root / "assets" / render_id
            render_dir.mkdir(parents=True)
            filename = "page_0001.png"
            Image.new("RGB", (2000, 1000), "white").save(
                render_dir / filename
            )
            rendered = RenderResponse(
                render_id=render_id,
                filename="course.pptx",
                pages=[
                    RenderedPage(
                        asset_id="page_0001",
                        render_id=render_id,
                        filename=filename,
                        url=f"/assets/{filename}",
                        page=1,
                        width=2000,
                        height=1000,
                    )
                ],
                native_visuals=[],
            )
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("MINDMAP_EDITORIAL_IMAGE_MAX_EDGE", None)
                encoded = _encode_slide_images(
                    rendered,
                    data_root,
                    env_prefix="MINDMAP_EDITORIAL",
                )
                standard_encoded = _encode_slide_images(
                    rendered,
                    data_root,
                    env_prefix="MINDMAP_EDITORIAL",
                    max_edge=1152,
                )

        raw = base64.b64decode(encoded[0][1].split(",", 1)[1])
        with Image.open(BytesIO(raw)) as image:
            self.assertEqual(image.size, (1280, 640))
        standard_raw = base64.b64decode(
            standard_encoded[0][1].split(",", 1)[1]
        )
        with Image.open(BytesIO(standard_raw)) as image:
            self.assertEqual(image.size, (1152, 576))


class _FakeVisionClient:
    def __init__(self):
        self.calls: list[dict] = []

    async def complete_multi_image_json(self, **kwargs):
        self.calls.append(kwargs)
        return _model_payload()


class SingleShotPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_pipeline_sends_every_slide_in_exactly_one_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "course.pptx"
            source.write_bytes(b"synthetic-pptx")
            data_root = root / "data"
            blackboard = SQLiteBlackboard(data_root / "blackboard.sqlite3")
            client = _FakeVisionClient()
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
                render_id = "render_test"
                render_dir = render_root / "assets" / render_id
                render_dir.mkdir(parents=True)
                pages = []
                for page_number, color in (
                    (1, (255, 255, 255)),
                    (2, (220, 235, 255)),
                ):
                    filename = f"page_{page_number:04d}.png"
                    Image.new("RGB", (640, 360), color).save(
                        render_dir / filename
                    )
                    pages.append(
                        RenderedPage(
                            asset_id=f"page_{page_number:04d}",
                            render_id=render_id,
                            filename=filename,
                            url=f"/assets/{filename}",
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
            with patch(
                "backend.app.single_shot_ppt_pipeline.settings",
                fake_settings,
            ):
                result = await run_single_shot_ppt_pipeline(
                    task_id="task-single-shot",
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

            self.assertEqual(len(client.calls), 1)
            self.assertEqual(
                [label for label, _ in client.calls[0]["images"]],
                ["slide_0001", "slide_0002"],
            )
            self.assertEqual(client.calls[0]["max_attempts"], 1)
            self.assertEqual(result.graph_version, 1)
            self.assertEqual(result.solver_status, "SINGLE_SHOT_MODEL_TREE")
            self.assertEqual(result.quality_report.coverage.covered_units, 2)
            self.assertFalse(result.quality_report.quality_gate_passed)
            self.assertTrue(
                all(
                    node.role == "branch_topic"
                    for node in result.nodes
                    if node.depth == 1
                )
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
            self.assertEqual(
                result.document.parse_metadata["model_call_count"],
                1,
            )
            self.assertNotIn(
                "branches",
                [stage for stage, _, _ in progress_events],
            )
            stored = blackboard.load_latest_result("task-single-shot")
            self.assertIsNotNone(stored)
            self.assertEqual(stored.root_id, result.root_id)

    async def test_pipeline_rejects_non_pptx_before_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "course.pdf"
            source.write_bytes(b"%PDF-synthetic")
            client = _FakeVisionClient()

            async def progress(_stage: str, _value: int, _message: str):
                return None

            with self.assertRaisesRegex(ValueError, "仅支持 PPTX"):
                await run_single_shot_ppt_pipeline(
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


if __name__ == "__main__":
    unittest.main()
