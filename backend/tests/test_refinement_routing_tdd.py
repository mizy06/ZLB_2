from __future__ import annotations

import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, UploadFile

from backend.app import main
from backend.app.editorial_ppt_prompts import (
    HUMAN_REFINEMENT_IMAGE_CONTEXT_PROMPT,
)
from backend.app.refinement_routing import (
    REFINEMENT_ROUTER_PROMPT,
    RefinementRoutingDecision,
    classify_refinement,
)


class _RouterClient:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[dict] = []

    async def complete_multi_image_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload


class RefinementRoutingTests(unittest.IsolatedAsyncioTestCase):
    def test_router_schema_rejects_unknown_route(self):
        with self.assertRaises(ValueError):
            RefinementRoutingDecision(
                route="attachment_present",
                rationale="不能依据附件机械判断",
            )

    def test_router_prompt_carries_all_three_route_contracts(self):
        self.assertIn("guidance_only", REFINEMENT_ROUTER_PROMPT)
        self.assertIn("截图、批注图、样式参考图通常是 guidance_only", REFINEMENT_ROUTER_PROMPT)
        self.assertIn("new_graph", REFINEMENT_ROUTER_PROMPT)
        self.assertIn("携带旧图 JSON", REFINEMENT_ROUTER_PROMPT)
        self.assertIn("merge_graph", REFINEMENT_ROUTER_PROMPT)
        self.assertIn("不应硬加", REFINEMENT_ROUTER_PROMPT)
        self.assertIn("绝不能根据是否上传附件", REFINEMENT_ROUTER_PROMPT)
        self.assertIn("信息不足或意图模糊时，保守选择 guidance_only", REFINEMENT_ROUTER_PROMPT)

    async def test_classifier_receives_current_map_and_attachment_preview(self):
        client = _RouterClient(
            {
                "route": "merge_graph",
                "rationale": "用户明确要求把新章节并入现有课程结构。",
            }
        )
        current = object()
        attachment = Path("new-course.png")
        with (
            patch(
                "backend.app.refinement_routing.render_mindmap_png",
                return_value=b"current-map",
            ),
            patch(
                "backend.app.refinement_routing._render_attachment_preview_paths",
                return_value=[attachment],
            ),
            patch(
                "backend.app.refinement_routing._attachment_text_context",
                return_value="[attachment: new-course.png]\n新章节\n[/attachment: new-course.png]",
            ),
            patch(
                "backend.app.refinement_routing._image_data_url",
                return_value="data:image/jpeg;base64,PREVIEW",
            ),
        ):
            decision = await classify_refinement(
                current_result=current,
                instruction="把新章节加入现有导图",
                attachment_paths=[attachment],
                attachment_filenames=["new-course.png"],
                model="qwen-vl-test",
                client=client,
            )

        self.assertEqual(decision.route, "merge_graph")
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertEqual(
            [label for label, _ in call["images"]],
            ["current_mindmap", "attachment_preview_01"],
        )
        payload = json.loads(call["user_prompt"])
        self.assertEqual(payload["user_instruction"], "把新章节加入现有导图")
        self.assertEqual(payload["attachment_names"], ["new-course.png"])
        self.assertIn("新章节", payload["attachment_text_context"])


class RefinementSchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_ai_cannot_bypass_model_route_classifier(self):
        result = SimpleNamespace(graph_version=1)
        record = {
            "use_ai": False,
            "source_path": "missing.md",
            "filename": "missing.md",
            "mode": "standard",
            "model": "qwen3.8-max",
            "provider": "qwen",
            "owner_id": "owner-a",
            "manifest": {},
        }
        with self.assertRaises(HTTPException) as context:
            await main._queue_classified_refinement(
                task_id="task-no-ai",
                record=record,
                result=result,
                instruction="请重新生成一张独立的新图",
            )

        self.assertEqual(context.exception.status_code, 503)
        self.assertIn("必须由模型判断", str(context.exception.detail))

    async def test_images_are_allowed_only_for_refinement_uploads(self):
        with tempfile.TemporaryDirectory() as tmp:
            upload = UploadFile(
                file=BytesIO(b"not-a-real-image"),
                filename="guidance.png",
            )
            with patch.object(main, "UPLOAD_DIR", Path(tmp)):
                with self.assertRaises(HTTPException):
                    await main._save_job_uploads(
                        task_id="initial",
                        uploads=[upload],
                    )

            valid = BytesIO()
            from PIL import Image

            Image.new("RGB", (4, 4), "white").save(valid, format="PNG")
            valid.seek(0)
            upload = UploadFile(file=valid, filename="guidance.png")
            with patch.object(main, "UPLOAD_DIR", Path(tmp)):
                paths, filenames, *_ = await main._save_job_uploads(
                    task_id="refinement",
                    uploads=[upload],
                    allowed_suffixes=main.REFINEMENT_UPLOAD_SUFFIXES,
                )

            self.assertEqual(filenames, ["guidance.png"])
            self.assertEqual(paths[0].suffix, ".png")
            self.assertTrue(paths[0].is_file())

    async def test_schedule_carries_only_the_asset_for_each_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.md"
            source.write_text("source", encoding="utf-8")
            guidance = root / "guidance.png"
            guidance.write_bytes(b"png")

            class _Blackboard:
                def load_latest_result(self, _task_id):
                    return "previous-result"

            class _Runtime:
                def __init__(self):
                    self.worker = None

                def submit(self, _task_id, worker):
                    self.worker = worker

            for route, expected_previous, expected_asset, expected_images in (
                ("guidance_only", "previous-result", None, [guidance]),
                ("new_graph", None, None, []),
                ("merge_graph", None, {"status": "completed"}, []),
            ):
                runtime = _Runtime()
                execute = AsyncMock()
                record = {
                    "task_id": f"task-{route}",
                    "source_path": str(source),
                    "filename": source.name,
                    "model": "qwen3.8-max-preview",
                    "provider": "qwen",
                    "mode": "standard",
                    "use_ai": True,
                    "manifest": {
                        "base_graph_version": 1,
                        "refinement_route": route,
                        "active_instruction": "update",
                        "guidance_image_paths": [str(guidance)]
                        if route == "guidance_only"
                        else [],
                        "completed_graph_asset": expected_asset,
                    },
                }
                with (
                    patch.object(main, "blackboard", _Blackboard()),
                    patch.object(main, "job_runtime", runtime),
                    patch.object(main, "_execute_job", execute),
                ):
                    main._schedule_job(record)
                    await runtime.worker()

                args = execute.await_args.args
                self.assertEqual(args[9], expected_previous)
                self.assertEqual(args[10], expected_asset)
                self.assertEqual(args[11], expected_images)

    async def test_guidance_execution_uses_main_editor(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pptx"
            guidance = Path(tmp) / "map.png"
            source.write_bytes(b"source")
            guidance.write_bytes(b"guidance")
            record = {
                "task_id": "task-guidance",
                "manifest": {
                    "source_paths": [str(source)],
                    "filenames": ["source.pptx"],
                },
            }
            blackboard = SimpleNamespace(load_job=lambda _task_id: record)
            job_events = SimpleNamespace(publish=AsyncMock())
            previous = object()
            editorial = AsyncMock(
                return_value=SimpleNamespace(
                    graph_version=2,
                    degraded_components=[],
                )
            )
            with (
                patch.object(main, "blackboard", blackboard),
                patch.object(main, "job_events", job_events),
                patch.object(main, "run_editorial_ppt_pipeline", editorial),
                patch.object(main, "_set_job"),
                patch.object(main, "_finish_job_interaction"),
            ):
                await main._execute_job(
                    "task-guidance",
                    source,
                    "source.pptx",
                    "qwen3.8-max-preview",
                    "qwen",
                    "standard",
                    True,
                    previous_result=previous,
                    guidance_image_paths=[guidance],
                )

        editorial.assert_awaited_once()
        self.assertIs(
            editorial.await_args.kwargs["previous_result"],
            previous,
        )
        self.assertEqual(
            editorial.await_args.kwargs["guidance_image_paths"],
            [guidance],
        )

    async def test_guidance_editor_prompt_is_explicitly_visual_only(self):
        self.assertIn("当前思维导图渲染图", HUMAN_REFINEMENT_IMAGE_CONTEXT_PROMPT)
        self.assertIn("不是原始课程事实来源", HUMAN_REFINEMENT_IMAGE_CONTEXT_PROMPT)
        self.assertIn("截图中的", HUMAN_REFINEMENT_IMAGE_CONTEXT_PROMPT)
        self.assertIn("装饰、示例或命令式文字", HUMAN_REFINEMENT_IMAGE_CONTEXT_PROMPT)


if __name__ == "__main__":
    unittest.main()
