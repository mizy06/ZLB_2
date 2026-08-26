from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, AsyncIterator, Literal

from pydantic import BaseModel


JobEventKind = Literal[
    "status",
    "model_start",
    "model_delta",
    "model_complete",
    "model_error",
    "job_complete",
    "job_failed",
    "job_cancelled",
    "usage",
    "compaction",
]
TERMINAL_EVENT_KINDS = {
    "job_complete",
    "job_failed",
    "job_cancelled",
}


class JobEvent(BaseModel):
    model_config = {"extra": "allow"}

    id: int
    task_id: str
    kind: JobEventKind
    created_at: str
    stage: str = ""
    progress: int | None = None
    message: str = ""
    call_id: str = ""
    round_number: int | None = None
    role: str = ""
    model: str = ""
    delta: str = ""
    context_tokens: int | None = None
    max_context_tokens: int | None = None
    context_usage: float | None = None
    total_tokens: int | None = None
    tokensBefore: int | None = None
    tokensAfter: int | None = None
    summary: str | None = None
    usage: dict[str, Any] | None = None


@dataclass
class _JobEventBuffer:
    events: deque[JobEvent]
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    next_id: int = 1
    terminal: bool = False


class JobEventHub:
    def __init__(self, *, max_events_per_job: int = 8_000):
        self.max_events_per_job = max(100, int(max_events_per_job))
        self._buffers: dict[str, _JobEventBuffer] = {}

    def _buffer(self, task_id: str) -> _JobEventBuffer:
        return self._buffers.setdefault(
            task_id,
            _JobEventBuffer(events=deque(maxlen=self.max_events_per_job)),
        )

    def has_events(self, task_id: str) -> bool:
        buffer = self._buffers.get(task_id)
        return bool(buffer and buffer.events)

    async def publish(
        self,
        task_id: str,
        kind: JobEventKind,
        **payload,
    ) -> JobEvent:
        buffer = self._buffer(task_id)
        async with buffer.condition:
            event = JobEvent(
                id=buffer.next_id,
                task_id=task_id,
                kind=kind,
                created_at=datetime.now(UTC).isoformat(),
                **payload,
            )
            buffer.next_id += 1
            buffer.events.append(event)
            if kind in TERMINAL_EVENT_KINDS:
                buffer.terminal = True
            buffer.condition.notify_all()
        return event

    async def stream(
        self,
        task_id: str,
        *,
        after_id: int = 0,
    ) -> AsyncIterator[JobEvent]:
        buffer = self._buffer(task_id)
        cursor = max(0, int(after_id))
        while True:
            async with buffer.condition:
                pending = [
                    event for event in buffer.events if event.id > cursor
                ]
                if not pending and buffer.terminal:
                    return
                if not pending:
                    await buffer.condition.wait()
                    continue
            for event in pending:
                cursor = event.id
                yield event

    async def drop(self, task_id: str) -> None:
        buffer = self._buffers.pop(task_id, None)
        if buffer is None:
            return
        async with buffer.condition:
            buffer.terminal = True
            buffer.condition.notify_all()
