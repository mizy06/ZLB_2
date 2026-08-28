from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend.app import main
from backend.app.architecture_schemas import JobView
from backend.app.blackboard import SQLiteBlackboard
from backend.app.job_runtime import JobRuntime


def seed_running_job(
    board: SQLiteBlackboard,
    root: Path,
    *,
    task_id: str,
) -> Path:
    source = root / f"{task_id}.txt"
    source.write_text("课程内容", encoding="utf-8")
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
        use_ai=True,
        owner_id="owner-a",
    )
    board.start_run(
        run_id=f"run-{task_id}",
        task_id=task_id,
        mode="standard",
    )
    return source


def run_status(board: SQLiteBlackboard, task_id: str) -> str:
    with sqlite3.connect(board.path) as connection:
        row = connection.execute(
            "SELECT status FROM runs WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    if row is None:
        raise AssertionError(f"missing run for {task_id}")
    return str(row[0])


class JobRecoveryTDDTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_requeue_resets_attempt_progress_and_run_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            board = SQLiteBlackboard(root / "blackboard.sqlite3")
            task_id = "restart-progress-task"
            source = seed_running_job(board, root, task_id=task_id)
            board.upsert_job(
                task_id=task_id,
                status="running",
                stage="solve",
                progress=88,
                message="正在求解",
                mode="standard",
                source_path=str(source),
                filename=source.name,
                model="qwen3.8-max-preview",
                provider="qwen",
                use_ai=True,
                owner_id="owner-a",
            )

            with (
                patch.object(main, "blackboard", board),
                patch.object(main, "jobs", {}),
                patch.object(main, "_schedule_job") as schedule,
            ):
                await main.recover_jobs()

            persisted = board.load_job(task_id)
            persisted_run_status = run_status(board, task_id)

        self.assertEqual(persisted["status"], "queued")
        self.assertEqual(persisted["stage"], "recovered")
        self.assertEqual(persisted["progress"], 0)
        self.assertEqual(persisted_run_status, "queued")
        schedule.assert_called_once()

    async def test_missing_recovery_source_marks_job_and_run_failed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            board = SQLiteBlackboard(root / "blackboard.sqlite3")
            task_id = "missing-source-task"
            source = seed_running_job(board, root, task_id=task_id)
            source.unlink()

            with (
                patch.object(main, "blackboard", board),
                patch.object(main, "jobs", {}),
                patch.object(main, "_schedule_job") as schedule,
            ):
                await main.recover_jobs()

            persisted = board.load_job(task_id)
            persisted_run_status = run_status(board, task_id)

        self.assertEqual(persisted["status"], "failed")
        self.assertEqual(persisted["stage"], "failed")
        self.assertEqual(persisted_run_status, "failed")
        schedule.assert_not_called()

    async def test_pipeline_failure_marks_job_and_run_failed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            board = SQLiteBlackboard(root / "blackboard.sqlite3")
            task_id = "failed-task"
            source = seed_running_job(board, root, task_id=task_id)
            in_memory_jobs = {
                task_id: JobView(
                    id=task_id,
                    status="queued",
                    stage="queued",
                    progress=0,
                    message="等待处理",
                    mode="standard",
                )
            }
            with (
                patch.object(main, "blackboard", board),
                patch.object(main, "jobs", in_memory_jobs),
                patch.object(
                    main,
                    "run_editorial_ppt_pipeline",
                    AsyncMock(side_effect=RuntimeError("provider failed")),
                ),
            ):
                await main._execute_job(
                    task_id,
                    source,
                    source.name,
                    "qwen3.8-max-preview",
                    "qwen",
                    "standard",
                    True,
                )

            persisted = board.load_job(task_id)
            persisted_run_status = run_status(board, task_id)

        self.assertEqual(persisted["status"], "failed")
        self.assertEqual(persisted_run_status, "failed")

    async def test_shutdown_cancellation_stays_recoverable_for_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            board = SQLiteBlackboard(root / "blackboard.sqlite3")
            runtime = JobRuntime(max_concurrent=1)
            task_id = "shutdown-task"
            source = seed_running_job(board, root, task_id=task_id)
            in_memory_jobs = {
                task_id: JobView(
                    id=task_id,
                    status="queued",
                    stage="queued",
                    progress=0,
                    message="等待处理",
                    mode="standard",
                )
            }
            started = asyncio.Event()
            release = asyncio.Event()

            async def interrupted_pipeline(**_kwargs):
                started.set()
                await release.wait()

            async def worker():
                await main._execute_job(
                    task_id,
                    source,
                    source.name,
                    "qwen3.8-max-preview",
                    "qwen",
                    "standard",
                    True,
                )

            with (
                patch.object(main, "blackboard", board),
                patch.object(main, "jobs", in_memory_jobs),
                patch.object(main, "job_runtime", runtime),
                patch.object(
                    main,
                    "run_editorial_ppt_pipeline",
                    interrupted_pipeline,
                ),
            ):
                runtime.submit(task_id, worker)
                await asyncio.wait_for(started.wait(), timeout=1)
                await runtime.cancel(task_id, reason="shutdown")

            persisted = board.load_job(task_id)
            persisted_run_status = run_status(board, task_id)

        self.assertEqual(persisted["status"], "queued")
        self.assertEqual(persisted["stage"], "interrupted")
        self.assertEqual(persisted_run_status, "queued")


if __name__ == "__main__":
    unittest.main()
