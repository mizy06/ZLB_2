from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Iterable

from pydantic import BaseModel

from .architecture_schemas import MindMapResult


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _json_value(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        separators=(",", ":"),
    )


class SQLiteBlackboard:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL UNIQUE,
            document_id TEXT,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            degraded_components_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS content_units (
            run_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            branch_id TEXT,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (run_id, item_id),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS node_claims (
            run_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            branch_id TEXT,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (run_id, item_id),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS parent_candidates (
            run_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            branch_id TEXT,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (run_id, item_id),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS cross_link_candidates (
            run_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            branch_id TEXT,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (run_id, item_id),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS decision_records (
            run_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (run_id, item_id),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS review_items (
            run_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            resolution_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (run_id, item_id),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS checkpoints (
            run_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (run_id, stage),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS graph_versions (
            run_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (run_id, version),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS model_calls (
            run_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            branch_id TEXT,
            provider TEXT,
            model TEXT,
            role TEXT NOT NULL,
            status TEXT NOT NULL,
            latency_ms INTEGER,
            input_unit_ids_json TEXT NOT NULL DEFAULT '[]',
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            PRIMARY KEY (run_id, item_id),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_runs_task_id ON runs(task_id);
        CREATE INDEX IF NOT EXISTS idx_units_run_branch
            ON content_units(run_id, branch_id);
        CREATE INDEX IF NOT EXISTS idx_claims_run_branch
            ON node_claims(run_id, branch_id);
        CREATE INDEX IF NOT EXISTS idx_reviews_run_status
            ON review_items(run_id, status);
        """
        with self._lock, self._connect() as connection:
            connection.executescript(schema)

    def start_run(
        self,
        *,
        run_id: str,
        task_id: str,
        mode: str,
        document_id: str = "",
    ) -> None:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    run_id, task_id, document_id, mode, status, stage,
                    degraded_components_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'running', 'starting', '[]', ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    run_id = excluded.run_id,
                    document_id = excluded.document_id,
                    mode = excluded.mode,
                    status = excluded.status,
                    stage = excluded.stage,
                    degraded_components_json = excluded.degraded_components_json,
                    updated_at = excluded.updated_at
                """,
                (run_id, task_id, document_id, mode, now, now),
            )

    def update_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        document_id: str | None = None,
        degraded_components: list[str] | None = None,
    ) -> None:
        updates: list[str] = ["updated_at = ?"]
        values: list[Any] = [utc_now()]
        if status is not None:
            updates.append("status = ?")
            values.append(status)
        if stage is not None:
            updates.append("stage = ?")
            values.append(stage)
        if document_id is not None:
            updates.append("document_id = ?")
            values.append(document_id)
        if degraded_components is not None:
            updates.append("degraded_components_json = ?")
            values.append(_json_value(degraded_components))
        values.append(run_id)
        with self._lock, self._connect() as connection:
            connection.execute(
                f"UPDATE runs SET {', '.join(updates)} WHERE run_id = ?",
                values,
            )

    def _upsert_items(
        self,
        table: str,
        run_id: str,
        items: Iterable[Any],
        *,
        id_getter,
        status_getter=lambda item: "candidate",
        branch_getter=lambda item: None,
    ) -> None:
        rows = [
            (
                run_id,
                id_getter(item),
                branch_getter(item),
                status_getter(item),
                _json_value(item),
                utc_now(),
            )
            for item in items
        ]
        if not rows:
            return
        with self._lock, self._connect() as connection:
            connection.executemany(
                f"""
                INSERT INTO {table} (
                    run_id, item_id, branch_id, status, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, item_id) DO UPDATE SET
                    branch_id = excluded.branch_id,
                    status = excluded.status,
                    payload_json = excluded.payload_json
                """,
                rows,
            )

    def save_content_units(self, run_id: str, items: Iterable[Any]) -> None:
        self._upsert_items(
            "content_units",
            run_id,
            items,
            id_getter=lambda item: item.id,
            status_getter=lambda item: item.status,
            branch_getter=lambda item: item.branch_hint,
        )

    def save_node_claims(self, run_id: str, items: Iterable[Any]) -> None:
        self._upsert_items(
            "node_claims",
            run_id,
            items,
            id_getter=lambda item: (
                getattr(item, "temp_id", None)
                or getattr(item, "id")
            ),
            status_getter=lambda item: getattr(item, "status", "candidate"),
            branch_getter=lambda item: getattr(item, "branch_id", None),
        )

    def save_parent_candidates(
        self,
        run_id: str,
        items: Iterable[Any],
        *,
        branch_id: str | None = None,
    ) -> None:
        self._upsert_items(
            "parent_candidates",
            run_id,
            items,
            id_getter=lambda item: (
                f"{getattr(item, 'parent', getattr(item, 'parent_id', ''))}:"
                f"{getattr(item, 'child', getattr(item, 'child_id', ''))}"
            ),
            branch_getter=lambda item: branch_id,
        )

    def save_cross_link_candidates(
        self,
        run_id: str,
        items: Iterable[Any],
        *,
        branch_id: str | None = None,
    ) -> None:
        self._upsert_items(
            "cross_link_candidates",
            run_id,
            items,
            id_getter=lambda item: (
                f"{getattr(item, 'source', getattr(item, 'source_id', ''))}:"
                f"{getattr(item, 'relation', '')}:"
                f"{getattr(item, 'target', getattr(item, 'target_id', ''))}"
            ),
            branch_getter=lambda item: branch_id,
        )

    def save_decision_records(self, run_id: str, items: Iterable[Any]) -> None:
        rows = [
            (run_id, item.id, _json_value(item), item.timestamp)
            for item in items
        ]
        if not rows:
            return
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO decision_records (
                    run_id, item_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id, item_id) DO UPDATE SET
                    payload_json = excluded.payload_json
                """,
                rows,
            )

    def save_review_items(self, run_id: str, items: Iterable[Any]) -> None:
        now = utc_now()
        rows = [
            (
                run_id,
                item.id,
                getattr(item, "status", "pending"),
                _json_value(item),
                now,
                now,
            )
            for item in items
        ]
        if not rows:
            return
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO review_items (
                    run_id, item_id, status, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, item_id) DO UPDATE SET
                    status = excluded.status,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                rows,
            )

    def resolve_review(self, run_id: str, item_id: str, resolution: dict) -> None:
        now = utc_now()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE review_items
                SET status = 'resolved', resolution_json = ?, updated_at = ?
                WHERE run_id = ? AND item_id = ?
                """,
                (_json_value(resolution), now, run_id, item_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(item_id)

    def checkpoint(self, run_id: str, stage: str, payload: Any) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO checkpoints (run_id, stage, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id, stage) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (run_id, stage, _json_value(payload), utc_now()),
            )
        self.update_run(run_id, stage=stage)

    def save_graph_version(self, run_id: str, result: MindMapResult) -> int:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version "
                "FROM graph_versions WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            version = int(row["version"]) + 1
            payload = result.model_copy(update={"graph_version": version})
            connection.execute(
                """
                INSERT INTO graph_versions (
                    run_id, version, payload_json, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (run_id, version, _json_value(payload), utc_now()),
            )
        return version

    def load_latest_result(self, task_id: str) -> MindMapResult | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT graph_versions.payload_json
                FROM graph_versions
                JOIN runs ON runs.run_id = graph_versions.run_id
                WHERE runs.task_id = ?
                ORDER BY graph_versions.version DESC
                LIMIT 1
                """,
                (task_id,),
            ).fetchone()
        if not row:
            return None
        return MindMapResult.model_validate_json(row["payload_json"])

    def list_history(self, limit: int = 50) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 100))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    runs.task_id,
                    runs.mode,
                    runs.created_at,
                    graph_versions.version,
                    graph_versions.payload_json,
                    graph_versions.created_at AS version_created_at
                FROM runs
                JOIN graph_versions
                    ON graph_versions.run_id = runs.run_id
                WHERE graph_versions.version = (
                    SELECT MAX(latest.version)
                    FROM graph_versions AS latest
                    WHERE latest.run_id = runs.run_id
                )
                ORDER BY graph_versions.created_at DESC
                LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()

        history: list[dict[str, Any]] = []
        for row in rows:
            result = MindMapResult.model_validate_json(row["payload_json"])
            history.append(
                {
                    "task_id": str(row["task_id"]),
                    "title": result.document.title,
                    "filename": result.document.filename,
                    "file_type": result.document.file_type,
                    "mode": result.mode,
                    "extraction_mode": result.extraction_mode,
                    "graph_version": int(row["version"]),
                    "node_count": result.quality_report.node_count,
                    "review_count": sum(
                        1
                        for item in result.review_items
                        if item.status == "pending"
                    ),
                    "quality_gate_passed": (
                        result.quality_report.quality_gate_passed
                    ),
                    "created_at": str(row["created_at"]),
                    "updated_at": str(row["version_created_at"]),
                }
            )
        return history

    def list_graph_versions(self, task_id: str) -> list[int]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT graph_versions.version
                FROM graph_versions
                JOIN runs ON runs.run_id = graph_versions.run_id
                WHERE runs.task_id = ?
                ORDER BY graph_versions.version
                """,
                (task_id,),
            ).fetchall()
        return [int(row["version"]) for row in rows]

    def load_graph_version(
        self,
        task_id: str,
        version: int,
    ) -> MindMapResult | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT graph_versions.payload_json
                FROM graph_versions
                JOIN runs ON runs.run_id = graph_versions.run_id
                WHERE runs.task_id = ? AND graph_versions.version = ?
                """,
                (task_id, version),
            ).fetchone()
        if not row:
            return None
        return MindMapResult.model_validate_json(row["payload_json"])

    def load_run_id(self, task_id: str) -> str | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT run_id FROM runs WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return str(row["run_id"]) if row else None

    def delete_task(self, task_id: str) -> str | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT run_id FROM runs WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if not row:
                return None
            run_id = str(row["run_id"])
            connection.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            return run_id
