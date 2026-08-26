from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.app import main
from backend.app.architecture_schemas import (
    ContentUnit,
    JobRefinementRequest,
    JobView,
    default_mindmap_loop,
)
from backend.app.agents import RoleRuntime, synthesize_themes
from backend.app.auth import Principal
from backend.app.blackboard import SQLiteBlackboard
from backend.app.cplus_pipeline import run_cplus_pipeline
from backend.app.human_loop import (
    HUMAN_GUIDANCE_POLICY,
    build_human_guidance,
    finish_active_interaction,
    initialize_interaction_manifest,
    interaction_views,
    normalize_human_instruction,
    queue_refinement_manifest,
)
from backend.app.job_events import JobEventHub
from backend.app.job_runtime import JobRuntime
from backend.app.schemas import ParsedDocument


async def noop_progress(_stage: str, _progress: int, _message: str) -> None:
    return None


class HumanLoopHelperTests(unittest.TestCase):
    def test_guidance_keeps_instruction_separate_from_previous_graph(self):
        previous = SimpleNamespace(
            graph_version=2,
            root_id="root",
            tree_edges=[SimpleNamespace(source="root", target="child")],
            nodes=[
                SimpleNamespace(
                    id="root",
                    name="课程",
                    role="root",
                    depth=0,
                    branch_id=None,
                ),
                SimpleNamespace(
                    id="child",
                    name="原有分支",
                    role="branch_topic",
                    depth=1,
                    branch_id="branch-1",
                ),
            ],
        )

        guidance = build_human_guidance("删掉第二个分支", previous)

        self.assertEqual(guidance["instruction"], "删掉第二个分支")
        self.assertEqual(guidance["policy"], HUMAN_GUIDANCE_POLICY)
        self.assertEqual(guidance["previous_graph"]["graph_version"], 2)
        self.assertEqual(
            guidance["previous_graph"]["nodes"][1]["parent_id"],
            "root",
        )
        self.assertNotIn(
            "删掉第二个分支",
            {
                node["name"]
                for node in guidance["previous_graph"]["nodes"]
            },
        )

    def test_interaction_manifest_tracks_revision_lifecycle(self):
        initial = initialize_interaction_manifest({}, "面向初学者")
        completed = finish_active_interaction(
            initial,
            status="completed",
            graph_version=1,
        )
        refined = queue_refinement_manifest(
            completed,
            instruction="合并重复分支",
            current_graph_version=1,
        )
        views = interaction_views(
            refined,
            job_status="running",
        )

        self.assertEqual(len(views), 2)
        self.assertEqual(views[0].status, "completed")
        self.assertEqual(views[0].result_graph_version, 1)
        self.assertEqual(views[1].kind, "revision")
        self.assertEqual(views[1].instruction, "合并重复分支")
        self.assertEqual(views[1].base_graph_version, 1)
        self.assertEqual(views[1].status, "running")

    def test_instruction_validation_rejects_blank_and_oversized_text(self):
        with self.assertRaisesRegex(ValueError, "不能为空"):
            normalize_human_instruction("   ", allow_empty=False)
        with self.assertRaisesRegex(ValueError, "8000"):
            normalize_human_instruction("x" * 8001)

    def test_new_revision_preserves_a_failed_prior_turn(self):
        initial = initialize_interaction_manifest({}, "生成初稿")
        failed = finish_active_interaction(
            initial,
            status="failed",
            error="provider timeout",
        )

        refined = queue_refinement_manifest(
            failed,
            instruction="重试并减少分支",
            current_graph_version=1,
        )
        views = interaction_views(refined, job_status="queued")

        self.assertEqual(views[0].status, "failed")
        self.assertEqual(views[0].error, "provider timeout")
        self.assertEqual(views[1].status, "queued")


class _CapturingThemeClient:
    def __init__(self):
        self.payload: dict = {}

    async def complete_json(self, **kwargs):
        self.payload = json.loads(kwargs["user_prompt"])
        return {
            "root_candidates": [
                {
                    "temp_id": "root",
                    "name": "课程",
                    "definition": "课程知识",
                    "support_unit_ids": ["unit-1"],
                    "confidence": 0.9,
                }
            ],
            "branch_topics": [
                {
                    "temp_id": "branch",
                    "name": "传播规律",
                    "definition": "反射与折射",
                    "support_unit_ids": ["unit-1"],
                    "confidence": 0.8,
                }
            ],
        }


class HumanGuidancePromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_theme_prompt_keeps_guidance_outside_source_units(self):
        client = _CapturingThemeClient()
        runtime = RoleRuntime(
            provider="qwen",
            model="qwen3.8-max-preview",
            client=client,
            available=True,
        )
        document = ParsedDocument(
            document_id="doc-1",
            filename="course.md",
            file_type="md",
            title="课程",
            blocks=[],
        )
        units = [
            ContentUnit(
                id="unit-1",
                document_id=document.document_id,
                kind="text",
                text="反射与折射都描述光的传播方向变化。",
                summary="光的反射与折射",
            )
        ]

        await synthesize_themes(
            document,
            units,
            runtime,
            human_guidance=build_human_guidance("面向初学者"),
        )

        self.assertEqual(
            client.payload["human_guidance"]["instruction"],
            "面向初学者",
        )
        self.assertEqual(
            client.payload["content_units"][0]["summary"],
            "光的反射与折射",
        )
        self.assertNotIn(
            "面向初学者",
            json.dumps(
                client.payload["content_units"],
                ensure_ascii=False,
            ),
        )


class HumanLoopRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_refine_requeues_same_task_and_resets_event_generation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "course.md"
            source.write_text(
                "# 光学\n\n反射遵循反射定律。\n\n折射会改变传播方向。",
                encoding="utf-8",
            )
            board = SQLiteBlackboard(root / "blackboard.sqlite3")
            task_id = "task-human-loop"
            manifest = initialize_interaction_manifest(
                {
                    "loop_config": default_mindmap_loop(
                        "qwen3.8-max-preview"
                    ).model_dump(mode="json")
                },
                "面向初学者组织",
            )
            board.upsert_job(
                task_id=task_id,
                status="queued",
                stage="queued",
                progress=0,
                message="等待处理",
                mode="standard",
                source_path=str(source),
                filename=source.name,
                model="qwen3.8-max-preview",
                provider="qwen",
                use_ai=False,
                owner_id="owner-a",
                manifest=manifest,
            )
            result = await run_cplus_pipeline(
                task_id=task_id,
                file_path=source,
                filename=source.name,
                model="qwen3.8-max-preview",
                provider="qwen",
                mode="standard",
                use_ai=False,
                progress=noop_progress,
                blackboard=board,
                user_instruction="面向初学者组织",
            )
            completed_manifest = finish_active_interaction(
                manifest,
                status="completed",
                graph_version=result.graph_version,
            )
            board.upsert_job(
                task_id=task_id,
                status="completed",
                stage="complete",
                progress=100,
                message="思维导图已生成",
                mode="standard",
                source_path=str(source),
                filename=source.name,
                model="qwen3.8-max-preview",
                provider="qwen",
                use_ai=False,
                owner_id="owner-a",
                manifest=completed_manifest,
            )

            hub = JobEventHub()
            await hub.publish(task_id, "job_complete", stage="complete")
            runtime = JobRuntime(max_concurrent=1)
            in_memory_jobs = {
                task_id: JobView(
                    id=task_id,
                    status="completed",
                    stage="complete",
                    progress=100,
                    message="思维导图已生成",
                    result=result,
                )
            }
            with (
                patch.object(main, "blackboard", board),
                patch.object(main, "job_events", hub),
                patch.object(main, "job_runtime", runtime),
                patch.object(main, "job_control_lock", asyncio.Lock()),
                patch.object(main, "jobs", in_memory_jobs),
                patch.object(main, "_schedule_job") as schedule,
            ):
                response = await main.refine_job(
                    task_id,
                    JobRefinementRequest(
                        instruction="把反射和折射合并为传播规律",
                        expected_graph_version=result.graph_version,
                    ),
                    Principal(id="owner-a"),
                )

            persisted = board.load_job(task_id, owner_id="owner-a")
            interactions = interaction_views(
                persisted["manifest"],
                job_status=persisted["status"],
                result=result,
            )
            stream = hub.stream(task_id)
            first_event = await anext(stream)
            await stream.aclose()

        self.assertEqual(response.id, task_id)
        self.assertEqual(response.status, "queued")
        self.assertEqual(persisted["progress"], 0)
        self.assertEqual(len(interactions), 2)
        self.assertEqual(interactions[-1].kind, "revision")
        self.assertEqual(
            interactions[-1].instruction,
            "把反射和折射合并为传播规律",
        )
        self.assertEqual(first_event.kind, "status")
        self.assertEqual(first_event.stage, "queued")
        schedule.assert_called_once()


if __name__ == "__main__":
    unittest.main()
