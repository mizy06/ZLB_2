from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any


WorkerFactory = Callable[[], Awaitable[Any]]


def monotonic_progress(current: int, requested: int) -> int:
    return max(0, min(max(int(current), int(requested)), 100))


class JobRuntime:
    def __init__(self, max_concurrent: int):
        self._semaphore = asyncio.Semaphore(max(int(max_concurrent), 1))
        self._tasks: dict[str, asyncio.Task] = {}
        self._cancel_reasons: dict[str, str] = {}

    def submit(self, task_id: str, worker: WorkerFactory) -> asyncio.Task:
        existing = self._tasks.get(task_id)
        if existing and not existing.done():
            raise ValueError(f"任务 {task_id} 已在运行。")

        async def guarded() -> Any:
            async with self._semaphore:
                return await worker()

        task = asyncio.create_task(guarded(), name=f"mindmap-job:{task_id}")
        self._tasks[task_id] = task

        def remove(completed: asyncio.Task) -> None:
            if self._tasks.get(task_id) is completed:
                self._tasks.pop(task_id, None)

        task.add_done_callback(remove)
        return task

    def has_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        return bool(task and not task.done())

    def cancel_reason(self, task_id: str) -> str:
        return self._cancel_reasons.get(task_id, "")

    async def wait(self, task_id: str) -> Any:
        task = self._tasks.get(task_id)
        if task is None:
            # A task may finish between a caller observing state and waiting.
            await asyncio.sleep(0)
            return None
        return await task

    async def cancel(
        self,
        task_id: str,
        *,
        reason: str = "user",
    ) -> bool:
        task = self._tasks.get(task_id)
        if not task or task.done():
            return False
        self._cancel_reasons[task_id] = reason
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            if self._tasks.get(task_id) is task:
                self._tasks.pop(task_id, None)
            self._cancel_reasons.pop(task_id, None)
        return True

    async def cancel_all(self, *, reason: str = "shutdown") -> None:
        task_ids = list(self._tasks)
        await asyncio.gather(
            *(
                self.cancel(task_id, reason=reason)
                for task_id in task_ids
            ),
            return_exceptions=True,
        )
