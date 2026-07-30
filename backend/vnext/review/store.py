from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.vnext.artifacts.canonical import canonical_json_bytes
from backend.vnext.contracts.review import (
    ReviewDecision,
    ReviewStatus,
    ReviewTask,
)


class ReviewStoreError(RuntimeError):
    pass


class ReviewConflict(ReviewStoreError):
    pass


class SQLiteReviewStore:
    """Owner-scoped append-only review revisions with optimistic CAS."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=30,
            isolation_level=None,
        )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS review_task_revisions (
                    review_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    payload BLOB NOT NULL,
                    PRIMARY KEY (review_id, owner_id, revision)
                );

                CREATE TABLE IF NOT EXISTS review_decisions (
                    decision_id TEXT PRIMARY KEY,
                    review_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    expected_review_revision INTEGER NOT NULL,
                    payload BLOB NOT NULL,
                    UNIQUE (
                        review_id,
                        owner_id,
                        expected_review_revision
                    )
                );

                CREATE INDEX IF NOT EXISTS review_task_owner_status_idx
                    ON review_task_revisions (owner_id, status);
                CREATE INDEX IF NOT EXISTS review_decision_review_idx
                    ON review_decisions (review_id, owner_id);
                """
            )

    def create_task(self, task: ReviewTask) -> None:
        if task.revision != 1 or task.status is not ReviewStatus.PENDING:
            raise ValueError(
                "new review task must be pending revision 1"
            )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO review_task_revisions (
                        review_id,
                        owner_id,
                        revision,
                        status,
                        payload
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        task.review_id,
                        task.owner_id,
                        task.revision,
                        task.status.value,
                        canonical_json_bytes(task),
                    ),
                )
                connection.commit()
        except sqlite3.IntegrityError as exc:
            raise ReviewConflict("review task already exists") from exc

    def load_latest(
        self,
        review_id: str,
        *,
        owner_id: str,
    ) -> ReviewTask:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload
                FROM review_task_revisions
                WHERE review_id = ? AND owner_id = ?
                ORDER BY revision DESC
                LIMIT 1
                """,
                (review_id, owner_id),
            ).fetchone()
        if row is None:
            raise KeyError("review task not found")
        return ReviewTask.model_validate_json(row[0])

    def list_revisions(
        self,
        review_id: str,
        *,
        owner_id: str,
    ) -> tuple[ReviewTask, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM review_task_revisions
                WHERE review_id = ? AND owner_id = ?
                ORDER BY revision
                """,
                (review_id, owner_id),
            ).fetchall()
        return tuple(ReviewTask.model_validate_json(row[0]) for row in rows)

    def list_decisions(
        self,
        review_id: str,
        *,
        owner_id: str,
    ) -> tuple[ReviewDecision, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM review_decisions
                WHERE review_id = ? AND owner_id = ?
                ORDER BY expected_review_revision, decision_id
                """,
                (review_id, owner_id),
            ).fetchall()
        return tuple(
            ReviewDecision.model_validate_json(row[0]) for row in rows
        )

    def resolve(self, decision: ReviewDecision) -> ReviewTask:
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT payload
                    FROM review_task_revisions
                    WHERE review_id = ? AND owner_id = ?
                    ORDER BY revision DESC
                    LIMIT 1
                    """,
                    (decision.review_id, decision.owner_id),
                ).fetchone()
                if row is None:
                    raise KeyError("review task not found")
                current = ReviewTask.model_validate_json(row[0])
                self._validate_decision(current, decision)
                connection.execute(
                    """
                    INSERT INTO review_decisions (
                        decision_id,
                        review_id,
                        owner_id,
                        expected_review_revision,
                        payload
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        decision.decision_id,
                        decision.review_id,
                        decision.owner_id,
                        decision.expected_review_revision,
                        canonical_json_bytes(decision),
                    ),
                )
                resolved_payload = current.model_dump(mode="json")
                resolved_payload.update(
                    {
                        "revision": current.revision + 1,
                        "status": ReviewStatus.RESOLVED.value,
                        "resolution_decision_id": decision.decision_id,
                        "updated_at": decision.created_at,
                        "supersedes_revision": current.revision,
                    }
                )
                resolved = ReviewTask.model_validate(resolved_payload)
                connection.execute(
                    """
                    INSERT INTO review_task_revisions (
                        review_id,
                        owner_id,
                        revision,
                        status,
                        payload
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        resolved.review_id,
                        resolved.owner_id,
                        resolved.revision,
                        resolved.status.value,
                        canonical_json_bytes(resolved),
                    ),
                )
                connection.commit()
                return resolved
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise ReviewConflict(
                    "review decision lost optimistic concurrency race"
                ) from exc
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _validate_decision(
        current: ReviewTask,
        decision: ReviewDecision,
    ) -> None:
        if current.status is not ReviewStatus.PENDING:
            raise ReviewConflict("review task is not pending")
        if current.run_id != decision.run_id:
            raise ReviewConflict("review decision run mismatch")
        if current.revision != decision.expected_review_revision:
            raise ReviewConflict(
                "review decision expected revision is stale"
            )
        option = next(
            (
                item
                for item in current.options
                if item.option_id == decision.selected_option_id
            ),
            None,
        )
        if option is None:
            raise ReviewConflict(
                "review decision selected an unknown option"
            )
        if (
            option.action is not decision.action
            or option.target_ids != decision.target_ids
        ):
            raise ReviewConflict(
                "review decision does not match the selected option"
            )
