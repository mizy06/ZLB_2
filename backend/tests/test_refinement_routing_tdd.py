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
from backend.app.editorial_input import build_editorial_input_bundle
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

    async def test_classifier_accepts_markdown_pdf_and_mixed_attachments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            markdown = root / "notes.md"
            markdown.write_text(
                "# 新章节\n\n反射与折射的定义和区别。",
                encoding="utf-8",
            )
            pdf = root / "lesson.pdf"
            _write_text_pdf(pdf, "PDF optics fact")
            data_root = root / "data"
            client = _RouterClient(
                {
                    "route": "merge_graph",
                    "rationale": "用户明确要求将两份新资料并入当前导图。",
                }
            )
            with (
                patch(
                    "backend.app.refinement_routing.settings",
                    SimpleNamespace(
                        mindmap_data_dir=data_root,
                        asset_public_base_url="",
                        asset_access_token="",
                    ),
                ),
                patch(
                    "backend.app.refinement_routing.render_mindmap_png",
                    return_value=b"current-map",
                ),
            ):
                decision = await classify_refinement(
                    current_result=object(),
                    instruction="把新资料并入当前导图",
                    attachment_paths=[markdown, pdf],
                    attachment_filenames=["notes.md", "lesson.pdf"],
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
            self.assertEqual(
                payload["attachment_names"],
                ["notes.md", "lesson.pdf"],
            )
            self.assertIn("反射与折射", payload["attachment_text_context"])
            self.assertIn("PDF optics fact", payload["attachment_text_context"])

    async def test_classifier_avoids_qwen_response_format_abort(self):
        client = _RouterClient(
            {
                "route": "guidance_only",
                "rationale": "截图用于标注当前导图的修改位置。",
            }
        )
        with (
            patch(
                "backend.app.refinement_routing.render_mindmap_png",
                return_value=b"current-map",
            ),
            patch(
                "backend.app.refinement_routing._render_attachment_preview_paths",
                return_value=[],
            ),
            patch(
                "backend.app.refinement_routing._attachment_text_context",
                return_value="",
            ),
        ):
            decision = await classify_refinement(
                current_result=object(),
                instruction="按截图标注修改",
                model="qwen3.8-max",
                client=client,
            )

        self.assertEqual(decision.route, "guidance_only")
        self.assertEqual(len(client.calls), 1)
        self.assertFalse(client.calls[0]["use_response_format"])
        self.assertEqual(client.calls[0]["max_tokens"], 1500)


class RefinementSchedulingTests(unittest.IsolatedAsyncioTestCase):
    def test_legacy_file_field_deduplicates_the_same_browser_upload(self):
        legacy = UploadFile(
            file=BytesIO(b"ppt"),
            filename="course.pptx",
            size=3,
            headers={"content-type": "application/octet-stream"},
        )
        multi = UploadFile(
            file=BytesIO(b"ppt"),
            filename="course.pptx",
            size=3,
            headers={"content-type": "application/octet-stream"},
        )
        other = UploadFile(
            file=BytesIO(b"pdf"),
            filename="notes.pdf",
            size=3,
            headers={"content-type": "application/pdf"},
        )

        self.assertTrue(main._same_upload_submission(legacy, multi))
        self.assertFalse(main._same_upload_submission(legacy, other))

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

    async def test_markdown_and_pdf_uploads_are_saved_for_editorial_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf_bytes_path = root / "lesson.pdf"
            _write_text_pdf(pdf_bytes_path, "PDF fact")
            uploads = [
                UploadFile(
                    file=BytesIO(
                        b"# Uploaded notes\n\nMarkdown fact."
                    ),
                    filename="notes.md",
                ),
                UploadFile(
                    file=BytesIO(pdf_bytes_path.read_bytes()),
                    filename="lesson.pdf",
                ),
            ]
            upload_dir = root / "uploads"
            upload_dir.mkdir()
            with patch.object(main, "UPLOAD_DIR", upload_dir):
                paths, filenames, sizes, digests, page_count = (
                    await main._save_job_uploads(
                        task_id="refinement-upload",
                        uploads=uploads,
                        allowed_suffixes=main.REFINEMENT_UPLOAD_SUFFIXES,
                    )
                )

            self.assertEqual(filenames, ["notes.md", "lesson.pdf"])
            self.assertEqual(len(paths), 2)
            self.assertEqual(len(sizes), 2)
            self.assertTrue(all(digests))
            self.assertEqual(page_count, 1)
            bundle = build_editorial_input_bundle(paths, filenames)
            self.assertEqual(bundle.input_mode, "mixed")
            self.assertIn("Markdown fact", bundle.text_context)
            self.assertIn("PDF fact", bundle.text_context)

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

    async def test_queue_manifest_tracks_md_pdf_inputs_for_each_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.md"
            source.write_text("原始课程", encoding="utf-8")
            markdown = root / "notes.md"
            markdown.write_text("新增章节", encoding="utf-8")
            pdf = root / "lesson.pdf"
            _write_text_pdf(pdf, "PDF fact")
            uploaded_paths = [markdown, pdf]
            uploaded_names = ["notes.md", "lesson.pdf"]

            class _Blackboard:
                def __init__(self, initial_record):
                    self.record = initial_record
                    self.last_upsert = None

                def upsert_job(self, **kwargs):
                    self.last_upsert = kwargs
                    self.record = {
                        **self.record,
                        "status": kwargs["status"],
                        "stage": kwargs["stage"],
                        "progress": kwargs["progress"],
                        "message": kwargs["message"],
                        "source_path": kwargs["source_path"],
                        "filename": kwargs["filename"],
                        "manifest": kwargs["manifest"],
                    }

                def load_job(self, _task_id, owner_id=None):
                    del owner_id
                    return self.record

            for route in ("guidance_only", "new_graph", "merge_graph"):
                record = {
                    "task_id": f"task-{route}",
                    "source_path": str(source),
                    "filename": source.name,
                    "model": "qwen3.8-max-preview",
                    "provider": "qwen",
                    "mode": "standard",
                    "use_ai": True,
                    "owner_id": "owner-a",
                    "error": None,
                    "manifest": {
                        "source_paths": [str(source)],
                        "filenames": [source.name],
                        "multi_document": False,
                    },
                }
                board = _Blackboard(record)
                result = SimpleNamespace(
                    graph_version=1,
                    run_id="run-1",
                )
                events = SimpleNamespace(
                    drop=AsyncMock(),
                    publish=AsyncMock(),
                )
                with (
                    patch.object(main, "blackboard", board),
                    patch.object(main, "job_events", events),
                    patch.object(main, "jobs", {}),
                    patch.object(main, "_job_view_from_record", return_value=None),
                    patch.object(main, "_schedule_job"),
                    patch.object(
                        main,
                        "completed_graph_asset",
                        return_value={
                            "asset_type": "completed_mindmap_json",
                            "status": "completed",
                        },
                    ),
                    patch.object(
                        main,
                        "classify_refinement",
                        new=AsyncMock(
                            return_value=RefinementRoutingDecision(
                                route=route,
                                rationale="测试路由契约",
                            )
                        ),
                    ),
                    patch.object(
                        main,
                        "materialize_guidance_images",
                        return_value=[root / "guidance.png"],
                    ),
                ):
                    await main._queue_classified_refinement(
                        task_id=record["task_id"],
                        record=record,
                        result=result,
                        instruction="处理新增资料",
                        attachment_paths=uploaded_paths,
                        attachment_filenames=uploaded_names,
                        attachment_sizes=[10, 20],
                        attachment_digests=["md-digest", "pdf-digest"],
                        attachment_page_count=1,
                    )

                manifest = board.last_upsert["manifest"]
                if route == "guidance_only":
                    self.assertEqual(
                        manifest["source_paths"],
                        [str(source)],
                    )
                    self.assertEqual(manifest["filenames"], [source.name])
                    self.assertEqual(manifest["multi_document"], False)
                else:
                    self.assertEqual(
                        manifest["source_paths"],
                        [str(markdown), str(pdf)],
                    )
                    self.assertEqual(
                        manifest["filenames"],
                        uploaded_names,
                    )
                    self.assertTrue(manifest["multi_document"])
                if route == "merge_graph":
                    self.assertEqual(
                        manifest["completed_graph_asset"]["status"],
                        "completed",
                    )
                else:
                    self.assertNotIn("completed_graph_asset", manifest)

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
