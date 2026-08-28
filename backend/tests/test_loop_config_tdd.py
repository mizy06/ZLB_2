from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from backend.app import main
from backend.app.architecture_schemas import (
    MindMapLoopConfig,
    MindMapLoopRound,
    default_mindmap_loop,
)
from backend.app.job_events import JobEventHub


class MindMapLoopConfigTests(unittest.TestCase):
    def test_current_editorial_loop_is_the_default_example(self):
        config = default_mindmap_loop("qwen3.8-max-preview")

        self.assertEqual(len(config.rounds), 1)
        round_config = config.rounds[0]
        self.assertEqual(round_config.editor_model, "qwen3.8-max-preview")
        self.assertEqual(
            round_config.reviewer_models(),
            [
                ("content_omission", "qwen3.8-max-preview"),
                ("pruning", "qwen3.8-max-preview"),
                ("multilevel_structure", "qwen3.8-max-preview"),
            ],
        )

    def test_reviewers_are_optional_but_editor_is_required(self):
        config = MindMapLoopConfig(
            rounds=[MindMapLoopRound(editor_model="qwen3.7-plus")]
        )

        self.assertEqual(config.rounds[0].reviewer_models(), [])
        with self.assertRaises(ValidationError):
            MindMapLoopConfig.model_validate(
                {"rounds": [{"editor_model": ""}]}
            )

    def test_round_count_and_model_ids_are_bounded(self):
        with self.assertRaises(ValidationError):
            MindMapLoopConfig(rounds=[])
        with self.assertRaises(ValidationError):
            MindMapLoopConfig(
                rounds=[
                    MindMapLoopRound(editor_model=f"model-{index}")
                    for index in range(7)
                ]
            )
        with self.assertRaises(ValidationError):
            MindMapLoopRound(editor_model="model name with spaces")


class JobEventHubTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_replays_after_event_id_and_stops_at_terminal(self):
        hub = JobEventHub(max_events_per_job=100)
        await hub.publish("task-1", "status", message="queued")
        second = await hub.publish(
            "task-1",
            "model_delta",
            call_id="round-1-editor",
            delta="{",
        )
        await hub.publish("task-1", "job_complete", message="done")

        replayed = [
            event
            async for event in hub.stream("task-1", after_id=second.id)
        ]

        self.assertEqual([event.kind for event in replayed], ["job_complete"])

    async def test_waiting_stream_receives_new_model_delta(self):
        hub = JobEventHub(max_events_per_job=100)

        async def receive_one():
            async for event in hub.stream("task-2"):
                return event
            return None

        waiting = asyncio.create_task(receive_one())
        await asyncio.sleep(0)
        await hub.publish(
            "task-2",
            "model_delta",
            call_id="draft",
            delta="hello",
        )

        event = await waiting
        self.assertIsNotNone(event)
        self.assertEqual(event.delta, "hello")

    async def test_sse_route_resumes_after_last_event_id(self):
        hub = JobEventHub(max_events_per_job=100)
        await hub.publish("task-3", "status", message="queued")
        await hub.publish(
            "task-3",
            "model_delta",
            call_id="draft",
            delta="hello",
        )
        await hub.publish("task-3", "job_complete", message="done")

        class FakeBlackboard:
            @staticmethod
            def load_job(_task_id, *, owner_id=None):
                return {
                    "status": "completed",
                    "stage": "complete",
                    "progress": 100,
                    "message": "done",
                }

        with (
            patch.object(main, "job_events", hub),
            patch.object(main, "blackboard", FakeBlackboard()),
        ):
            stream = main.stream_job_events(
                "task-3",
                last_event_id=1,
                principal=SimpleNamespace(id="local-development"),
            )
            first = await anext(stream)
            await stream.aclose()

        self.assertEqual(first.id, "2")
        self.assertEqual(first.data.kind, "model_delta")
