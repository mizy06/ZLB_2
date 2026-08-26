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
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL UNIQUE,
            document_id TEXT,
            owner_id TEXT NOT NULL DEFAULT '',
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            manifest_json TEXT NOT NULL DEFAULT '{}',
            degraded_components_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs (
            task_id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            progress INTEGER NOT NULL DEFAULT 0,
            message TEXT NOT NULL DEFAULT '',
            error TEXT,
            mode TEXT NOT NULL,
            source_path TEXT NOT NULL DEFAULT '',
            filename TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT '',
            use_ai INTEGER NOT NULL DEFAULT 1,
            manifest_json TEXT NOT NULL DEFAULT '{}',
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
        CREATE INDEX IF NOT EXISTS idx_jobs_owner_status
            ON jobs(owner_id, status);
        CREATE INDEX IF NOT EXISTS idx_units_run_branch
            ON content_units(run_id, branch_id);
        CREATE INDEX IF NOT EXISTS idx_claims_run_branch
            ON node_claims(run_id, branch_id);
        CREATE INDEX IF NOT EXISTS idx_reviews_run_status
            ON review_items(run_id, status);
        """
        with self._lock, self._connect() as connection:
            connection.executescript(schema)
            self._ensure_column(
                connection,
                "runs",
                "owner_id",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                connection,
                "runs",
                "manifest_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_owner_id "
                "ON runs(owner_id)"
            )

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})")
        }
        if column not in columns:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    def upsert_job(
        self,
        *,
        task_id: str,
        status: str,
        stage: str,
        progress: int,
        message: str,
        mode: str,
        source_path: str = "",
        filename: str = "",
        model: str = "",
        provider: str = "",
        use_ai: bool = True,
        owner_id: str = "",
        error: str | None = None,
        manifest: dict[str, Any] | None = None,
    ) -> None:
        now = utc_now()
        bounded_progress = max(0, min(int(progress), 100))
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    task_id, owner_id, status, stage, progress, message,
                    error, mode, source_path, filename, model, provider,
                    use_ai, manifest_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    owner_id = CASE
                        WHEN excluded.owner_id != '' THEN excluded.owner_id
                        ELSE jobs.owner_id
                    END,
                    status = excluded.status,
                    stage = excluded.stage,
                    progress = CASE
                        WHEN excluded.status = 'queued'
                            AND excluded.stage IN ('queued', 'recovered')
                            THEN excluded.progress
                        ELSE MAX(jobs.progress, excluded.progress)
                    END,
                    message = excluded.message,
                    error = excluded.error,
                    mode = excluded.mode,
                    source_path = CASE
                        WHEN excluded.source_path != '' THEN excluded.source_path
                        ELSE jobs.source_path
                    END,
                    filename = CASE
                        WHEN excluded.filename != '' THEN excluded.filename
                        ELSE jobs.filename
                    END,
                    model = CASE
                        WHEN excluded.model != '' THEN excluded.model
                        ELSE jobs.model
                    END,
                    provider = CASE
                        WHEN excluded.provider != '' THEN excluded.provider
                        ELSE jobs.provider
                    END,
                    use_ai = excluded.use_ai,
                    manifest_json = CASE
                        WHEN excluded.manifest_json != '{}' THEN excluded.manifest_json
                        ELSE jobs.manifest_json
                    END,
                    updated_at = excluded.updated_at
                """,
                (
                    task_id,
                    owner_id,
                    status,
                    stage,
                    bounded_progress,
                    message,
                    error,
                    mode,
                    source_path,
                    filename,
                    model,
                    provider,
                    int(use_ai),
                    _json_value(manifest or {}),
                    now,
                    now,
                ),
            )

    def update_job_manifest(
        self,
        task_id: str,
        manifest: dict[str, Any],
    ) -> None:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET manifest_json = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (_json_value(manifest), utc_now(), task_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(task_id)

    @staticmethod
    def _job_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "task_id": str(row["task_id"]),
            "owner_id": str(row["owner_id"]),
            "status": str(row["status"]),
            "stage": str(row["stage"]),
            "progress": int(row["progress"]),
            "message": str(row["message"]),
            "error": str(row["error"]) if row["error"] is not None else None,
            "mode": str(row["mode"]),
            "source_path": str(row["source_path"]),
            "filename": str(row["filename"]),
            "model": str(row["model"]),
            "provider": str(row["provider"]),
            "use_ai": bool(row["use_ai"]),
            "manifest": json.loads(row["manifest_json"] or "{}"),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def load_job(
        self,
        task_id: str,
        *,
        owner_id: str | None = None,
    ) -> dict[str, Any] | None:
        query = "SELECT * FROM jobs WHERE task_id = ?"
        values: list[Any] = [task_id]
        if owner_id is not None:
            query += " AND owner_id = ?"
            values.append(owner_id)
        with self._lock, self._connect() as connection:
            row = connection.execute(query, values).fetchone()
        return self._job_row(row) if row else None

    def list_jobs(
        self,
        *,
        statuses: Iterable[str] | None = None,
        owner_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        status_values = list(statuses or [])
        if status_values:
            placeholders = ",".join("?" for _ in status_values)
            clauses.append(f"status IN ({placeholders})")
            values.extend(status_values)
        if owner_id is not None:
            clauses.append("owner_id = ?")
            values.append(owner_id)
        query = "SELECT * FROM jobs"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC LIMIT ?"
        values.append(max(1, min(int(limit), 500)))
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._job_row(row) for row in rows]

    def start_run(
        self,
        *,
        run_id: str,
        task_id: str,
        mode: str,
        document_id: str = "",
        owner_id: str = "",
        manifest: dict[str, Any] | None = None,
    ) -> str:
        now = utc_now()
        with self._lock, self._connect() as connection:
            job = connection.execute(
                "SELECT owner_id, manifest_json FROM jobs WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            resolved_owner = owner_id or (
                str(job["owner_id"]) if job else ""
            )
            resolved_manifest = dict(manifest or {})
            if job and not resolved_manifest:
                resolved_manifest = json.loads(job["manifest_json"] or "{}")
            existing = connection.execute(
                "SELECT run_id FROM runs WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            actual_run_id = str(existing["run_id"]) if existing else run_id
            if existing:
                connection.execute(
                    """
                    UPDATE runs
                    SET document_id = ?, owner_id = ?, mode = ?,
                        status = 'running', stage = 'starting',
                        manifest_json = ?, degraded_components_json = '[]',
                        updated_at = ?
                    WHERE task_id = ?
                    """,
                    (
                        document_id,
                        resolved_owner,
                        mode,
                        _json_value(resolved_manifest),
                        now,
                        task_id,
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO runs (
                        run_id, task_id, document_id, owner_id, mode,
                        status, stage, manifest_json,
                        degraded_components_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'running', 'starting', ?, '[]', ?, ?)
                    """,
                    (
                        actual_run_id,
                        task_id,
                        document_id,
                        resolved_owner,
                        mode,
                        _json_value(resolved_manifest),
                        now,
                        now,
                    ),
                )
            connection.execute(
                """
                UPDATE jobs
                SET status = 'running', stage = 'starting',
                    updated_at = ?
                WHERE task_id = ?
                """,
                (now, task_id),
            )
        return actual_run_id

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
            job_updates: list[str] = ["updated_at = ?"]
            job_values: list[Any] = [utc_now()]
            if status is not None:
                job_updates.append("status = ?")
                job_values.append(status)
                if status == "completed":
                    job_updates.append("progress = 100")
            if stage is not None:
                job_updates.append("stage = ?")
                job_values.append(stage)
            job_values.append(run_id)
            connection.execute(
                f"""
                UPDATE jobs
                SET {", ".join(job_updates)}
                WHERE task_id = (
                    SELECT task_id FROM runs WHERE run_id = ?
                )
                """,
                job_values,
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
        resolved_items: list[tuple[Any, Any]] = []
        seen_ids: set[Any] = set()
        duplicate_ids: set[Any] = set()
        for item in items:
            item_id = id_getter(item)
            if item_id in seen_ids:
                duplicate_ids.add(item_id)
            else:
                seen_ids.add(item_id)
            resolved_items.append((item_id, item))
        if duplicate_ids:
            formatted_ids = ", ".join(
                sorted(str(item_id) for item_id in duplicate_ids)
            )
            raise ValueError(
                f"{table} contains duplicate item IDs: {formatted_ids}"
            )
        rows = [
            (
                run_id,
                item_id,
                branch_getter(item),
                status_getter(item),
                _json_value(item),
                utc_now(),
            )
            for item_id, item in resolved_items
        ]
        with self._lock, self._connect() as connection:
            connection.execute(
                f"DELETE FROM {table} WHERE run_id = ?",
                (run_id,),
            )
            if rows:
                connection.executemany(
                    f"""
                    INSERT INTO {table} (
                        run_id, item_id, branch_id, status, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
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
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM review_items WHERE run_id = ?",
                (run_id,),
            )
            if rows:
                connection.executemany(
                    """
                    INSERT INTO review_items (
                        run_id, item_id, status, payload_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
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

    def load_checkpoint(self, run_id: str, stage: str) -> Any | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM checkpoints
                WHERE run_id = ? AND stage = ?
                """,
                (run_id, stage),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def list_reusable_checkpoints(
        self,
        run_id: str,
        stage: str,
        input_hash: str,
        *,
        limit: int = 20,
    ) -> list[tuple[str, Any]]:
        bounded_limit = max(1, min(int(limit), 100))
        with self._lock, self._connect() as connection:
            current = connection.execute(
                "SELECT owner_id FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if not current:
                return []
            rows = connection.execute(
                """
                SELECT checkpoints.run_id, checkpoints.payload_json
                FROM checkpoints
                JOIN runs ON runs.run_id = checkpoints.run_id
                WHERE checkpoints.stage = ?
                    AND checkpoints.run_id != ?
                    AND runs.owner_id = ?
                ORDER BY checkpoints.created_at DESC, checkpoints.run_id
                """,
                (
                    stage,
                    run_id,
                    str(current["owner_id"]),
                ),
            ).fetchall()

        reusable: list[tuple[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, ValueError):
                continue
            if (
                isinstance(payload, dict)
                and payload.get("input_hash") == input_hash
            ):
                reusable.append((str(row["run_id"]), payload))
                if len(reusable) >= bounded_limit:
                    break
        return reusable

    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT stage, payload_json, created_at
                FROM checkpoints
                WHERE run_id = ?
                ORDER BY created_at
                """,
                (run_id,),
            ).fetchall()
        return [
            {
                "stage": str(row["stage"]),
                "payload": json.loads(row["payload_json"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def record_model_call(
        self,
        record: dict[str, Any] | None = None,
        **values: Any,
    ) -> None:
        payload = {**(record or {}), **values}
        run_id = str(payload.get("run_id") or "")
        if not run_id:
            return
        item_id = str(payload.get("item_id") or "")
        if not item_id:
            raise ValueError("model call requires item_id")
        details = dict(payload.get("details") or {})
        if "attempt" in payload and "attempt" not in details:
            details["attempt"] = payload["attempt"]
        if "operation" in payload and "operation" not in details:
            details["operation"] = payload["operation"]
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO model_calls (
                    run_id, item_id, branch_id, provider, model, role,
                    status, latency_ms, input_unit_ids_json, details_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, item_id) DO UPDATE SET
                    status = excluded.status,
                    latency_ms = excluded.latency_ms,
                    details_json = excluded.details_json
                """,
                (
                    run_id,
                    item_id,
                    payload.get("branch_id"),
                    payload.get("provider"),
                    payload.get("model"),
                    str(payload.get("role") or "unspecified"),
                    str(payload.get("status") or "unknown"),
                    payload.get("latency_ms"),
                    _json_value(payload.get("input_unit_ids") or []),
                    _json_value(details),
                    utc_now(),
                ),
            )

    def list_model_calls(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM model_calls
                WHERE run_id = ?
                ORDER BY created_at, item_id
                """,
                (run_id,),
            ).fetchall()
        return [
            {
                "run_id": str(row["run_id"]),
                "item_id": str(row["item_id"]),
                "branch_id": row["branch_id"],
                "provider": row["provider"],
                "model": row["model"],
                "role": str(row["role"]),
                "status": str(row["status"]),
                "latency_ms": row["latency_ms"],
                "input_unit_ids": json.loads(
                    row["input_unit_ids_json"] or "[]"
                ),
                "details": json.loads(row["details_json"] or "{}"),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def save_graph_version(
        self,
        run_id: str,
        result: MindMapResult,
        *,
        expected_version: int | None = None,
    ) -> int:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version "
                "FROM graph_versions WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            current_version = int(row["version"])
            if (
                expected_version is not None
                and current_version != expected_version
            ):
                raise ValueError(
                    f"图版本冲突：期望 v{expected_version}，"
                    f"当前为 v{current_version}。"
                )
            version = current_version + 1
            manifest_row = connection.execute(
                "SELECT manifest_json FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            manifest = (
                json.loads(manifest_row["manifest_json"] or "{}")
                if manifest_row
                else {}
            )
            payload = result.model_copy(
                update={
                    "graph_version": version,
                    "run_manifest": result.run_manifest or manifest,
                }
            )
            connection.execute(
                """
                INSERT INTO graph_versions (
                    run_id, version, payload_json, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (run_id, version, _json_value(payload), utc_now()),
            )
        return version

    def commit_review_resolution(
        self,
        *,
        run_id: str,
        review_id: str,
        expected_version: int,
        result: MindMapResult,
        decision: Any,
        resolution: dict[str, Any],
    ) -> int:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            version_row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version "
                "FROM graph_versions WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            current_version = int(version_row["version"])
            if current_version != expected_version:
                raise ValueError(
                    f"图版本冲突：期望 v{expected_version}，"
                    f"当前为 v{current_version}。"
                )

            review_row = connection.execute(
                """
                SELECT status
                FROM review_items
                WHERE run_id = ? AND item_id = ?
                """,
                (run_id, review_id),
            ).fetchone()
            if not review_row:
                raise KeyError(review_id)
            if str(review_row["status"]) == "resolved":
                raise ValueError("该复核项已经处理。")

            version = current_version + 1
            manifest_row = connection.execute(
                "SELECT manifest_json FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            manifest = (
                json.loads(manifest_row["manifest_json"] or "{}")
                if manifest_row
                else {}
            )
            versioned = result.model_copy(
                update={
                    "graph_version": version,
                    "run_manifest": result.run_manifest or manifest,
                }
            )
            connection.execute(
                "DELETE FROM review_items WHERE run_id = ?",
                (run_id,),
            )
            review_rows = []
            for item in versioned.review_items:
                item_resolution = getattr(item, "resolution", None)
                review_rows.append(
                    (
                        run_id,
                        item.id,
                        getattr(item, "status", "pending"),
                        _json_value(item),
                        (
                            _json_value(item_resolution)
                            if item_resolution is not None
                            else None
                        ),
                        now,
                        now,
                    )
                )
            if review_rows:
                connection.executemany(
                    """
                    INSERT INTO review_items (
                        run_id, item_id, status, payload_json,
                        resolution_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    review_rows,
                )

            connection.execute(
                """
                INSERT INTO decision_records (
                    run_id, item_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id, item_id) DO UPDATE SET
                    payload_json = excluded.payload_json
                """,
                (
                    run_id,
                    decision.id,
                    _json_value(decision),
                    decision.timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO graph_versions (
                    run_id, version, payload_json, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (run_id, version, _json_value(versioned), now),
            )
            connection.execute(
                """
                UPDATE runs
                SET stage = 'review', updated_at = ?
                WHERE run_id = ?
                """,
                (now, run_id),
            )
        return version

    def load_latest_result(
        self,
        task_id: str,
        *,
        owner_id: str | None = None,
    ) -> MindMapResult | None:
        owner_clause = ""
        values: list[Any] = [task_id]
        if owner_id is not None:
            owner_clause = " AND runs.owner_id = ?"
            values.append(owner_id)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT graph_versions.payload_json
                FROM graph_versions
                JOIN runs ON runs.run_id = graph_versions.run_id
                WHERE runs.task_id = ?
                {owner_clause}
                ORDER BY graph_versions.version DESC
                LIMIT 1
                """,
                values,
            ).fetchone()
        if not row:
            return None
        return MindMapResult.model_validate_json(row["payload_json"])

    @staticmethod
    def _history_result_fields(result: MindMapResult) -> dict[str, Any]:
        return {
            "title": result.document.title,
            "filename": result.document.filename,
            "file_type": result.document.file_type,
            "mode": result.mode,
            "extraction_mode": result.extraction_mode,
            "graph_version": result.graph_version,
            "node_count": result.quality_report.node_count,
            "review_count": sum(
                1
                for item in result.review_items
                if item.status == "pending"
            ),
            "quality_gate_passed": (
                result.quality_report.quality_gate_passed
            ),
        }

    def list_history(
        self,
        limit: int = 50,
        *,
        owner_id: str | None = None,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 100))
        jobs = self.list_jobs(
            owner_id=owner_id,
            limit=bounded_limit,
        )
        history: list[dict[str, Any]] = []
        job_task_ids: set[str] = set()
        for job in jobs:
            task_id = job["task_id"]
            job_task_ids.add(task_id)
            result = self.load_latest_result(
                task_id,
                owner_id=owner_id,
            )
            if result:
                fields = self._history_result_fields(result)
            else:
                filename = job["filename"] or Path(
                    job["source_path"]
                ).name
                fields = {
                    "title": Path(filename).stem or "未命名任务",
                    "filename": filename,
                    "file_type": Path(filename).suffix.lstrip(".").lower(),
                    "mode": job["mode"],
                    "extraction_mode": "heuristic",
                    "graph_version": 0,
                    "node_count": 0,
                    "review_count": 0,
                    "quality_gate_passed": False,
                }
            history.append(
                {
                    "task_id": task_id,
                    **fields,
                    "status": job["status"],
                    "stage": job["stage"],
                    "progress": job["progress"],
                    "error": job["error"],
                    "created_at": job["created_at"],
                    "updated_at": job["updated_at"],
                }
            )

        owner_clause = ""
        values: list[Any] = []
        if owner_id is not None:
            owner_clause = " AND runs.owner_id = ?"
            values.append(owner_id)
        values.append(bounded_limit)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
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
                {owner_clause}
                ORDER BY graph_versions.created_at DESC
                LIMIT ?
                """,
                values,
            ).fetchall()

        for row in rows:
            task_id = str(row["task_id"])
            if task_id in job_task_ids:
                continue
            result = MindMapResult.model_validate_json(row["payload_json"])
            history.append(
                {
                    "task_id": task_id,
                    **self._history_result_fields(result),
                    "graph_version": int(row["version"]),
                    "status": "completed",
                    "stage": "complete",
                    "progress": 100,
                    "error": None,
                    "created_at": str(row["created_at"]),
                    "updated_at": str(row["version_created_at"]),
                }
            )
        history.sort(
            key=lambda item: str(item["updated_at"]),
            reverse=True,
        )
        return history[:bounded_limit]

    def list_graph_versions(
        self,
        task_id: str,
        *,
        owner_id: str | None = None,
    ) -> list[int]:
        owner_clause = ""
        values: list[Any] = [task_id]
        if owner_id is not None:
            owner_clause = " AND runs.owner_id = ?"
            values.append(owner_id)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT graph_versions.version
                FROM graph_versions
                JOIN runs ON runs.run_id = graph_versions.run_id
                WHERE runs.task_id = ?
                {owner_clause}
                ORDER BY graph_versions.version
                """,
                values,
            ).fetchall()
        return [int(row["version"]) for row in rows]

    def load_graph_version(
        self,
        task_id: str,
        version: int,
        *,
        owner_id: str | None = None,
    ) -> MindMapResult | None:
        owner_clause = ""
        values: list[Any] = [task_id, version]
        if owner_id is not None:
            owner_clause = " AND runs.owner_id = ?"
            values.append(owner_id)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT graph_versions.payload_json
                FROM graph_versions
                JOIN runs ON runs.run_id = graph_versions.run_id
                WHERE runs.task_id = ? AND graph_versions.version = ?
                {owner_clause}
                """,
                values,
            ).fetchone()
        if not row:
            return None
        return MindMapResult.model_validate_json(row["payload_json"])

    def load_run_id(
        self,
        task_id: str,
        *,
        owner_id: str | None = None,
    ) -> str | None:
        query = "SELECT run_id FROM runs WHERE task_id = ?"
        values: list[Any] = [task_id]
        if owner_id is not None:
            query += " AND owner_id = ?"
            values.append(owner_id)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                query,
                values,
            ).fetchone()
        return str(row["run_id"]) if row else None

    def load_run_manifest(self, task_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT manifest_json FROM runs WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return json.loads(row["manifest_json"] or "{}") if row else None

    def delete_task(
        self,
        task_id: str,
        *,
        owner_id: str | None = None,
    ) -> str | None:
        owner_clause = ""
        values: list[Any] = [task_id]
        if owner_id is not None:
            owner_clause = " AND owner_id = ?"
            values.append(owner_id)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                f"SELECT run_id FROM runs WHERE task_id = ?{owner_clause}",
                values,
            ).fetchone()
            job = connection.execute(
                f"SELECT task_id FROM jobs WHERE task_id = ?{owner_clause}",
                values,
            ).fetchone()
            if not row and not job:
                return None
            run_id = str(row["run_id"]) if row else ""
            if run_id:
                connection.execute(
                    "DELETE FROM runs WHERE run_id = ?",
                    (run_id,),
                )
            connection.execute(
                "DELETE FROM jobs WHERE task_id = ?",
                (task_id,),
            )
            return run_id or f"job:{task_id}"
