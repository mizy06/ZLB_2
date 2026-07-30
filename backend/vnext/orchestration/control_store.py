from __future__ import annotations

import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock

from backend.vnext.artifacts.canonical import (
    canonical_json_bytes,
    payload_digest,
)
from backend.vnext.artifacts.local_store import LocalArtifactStore
from backend.vnext.contracts.common import (
    ArtifactProducerRef,
    ArtifactRef,
    RuntimeRole,
)
from backend.vnext.contracts.control import (
    ExecutionStatus,
    PublicationStatus,
    QualityAttestation,
    QualityStatus,
    RunManifest,
    StageCommit,
    StageCommitStatus,
)
from backend.vnext.contracts.release import (
    CanaryDecision,
    CanaryObservation,
    CanaryStage,
    CanaryTransitionDecision,
    ReleaseEvent,
    ReleaseEventType,
    ReleasePointerSnapshot,
    ReleaseReadinessEvidence,
    RollbackRecord,
)


class ControlPlaneError(RuntimeError):
    pass


class LeaseConflict(ControlPlaneError):
    pass


class CompareAndSwapConflict(ControlPlaneError):
    pass


class ReleaseEventIntegrityError(ControlPlaneError):
    pass


@dataclass(frozen=True, slots=True)
class StageLease:
    run_id: str
    stage_key: str
    lease_epoch: int
    worker_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class OutboxItem:
    outbox_id: int
    run_id: str
    stage_key: str
    output_ref: ArtifactRef


@dataclass(frozen=True, slots=True)
class PointerRecord:
    owner_id: str
    pointer_key: str
    artifact_ref: ArtifactRef
    version: int
    updated_at: datetime


def stage_idempotency_key(
    *,
    owner_id: str,
    stage_contract_major: int,
    ordered_input_digests: tuple[str, ...],
    policy_digests: tuple[str, ...],
) -> str:
    if stage_contract_major < 1:
        raise ValueError("stage_contract_major must be at least 1")
    return payload_digest(
        {
            "ordered_input_digests": ordered_input_digests,
            "owner_id": owner_id,
            "policy_digests": policy_digests,
            "stage_contract_major": stage_contract_major,
        }
    )


def ordered_stage_input_digest(
    input_refs: tuple[ArtifactRef, ...],
) -> str:
    return payload_digest(
        [item.payload_digest for item in input_refs]
    )


def next_manifest_revision(
    current: RunManifest,
    *,
    execution_status: ExecutionStatus | None = None,
    quality_status: QualityStatus | None = None,
    publication_status: PublicationStatus | None = None,
    observed=None,
    now: datetime | None = None,
) -> RunManifest:
    timestamp = now or datetime.now(UTC)
    payload = current.model_dump(mode="python")
    payload.update(
        {
            "manifest_id": "run_manifest_" + secrets.token_hex(16),
            "revision": current.revision + 1,
            "observed": observed or current.observed,
            "execution_status": execution_status or current.execution_status,
            "quality_status": quality_status or current.quality_status,
            "publication_status": (
                publication_status or current.publication_status
            ),
            "updated_at": timestamp,
            "supersedes": current.manifest_id,
        }
    )
    return RunManifest.model_validate(payload)


class SQLiteControlStore:
    """Single-host control plane with CAS, leases, stage commits, and outbox."""

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
        connection.execute("PRAGMA synchronous = FULL")
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
            owner_scope TEXT NOT NULL,
            current_revision INTEGER NOT NULL,
            manifest_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS run_manifest_versions (
            run_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            manifest_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (run_id, revision),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS stage_leases (
            run_id TEXT NOT NULL,
            stage_key TEXT NOT NULL,
            lease_epoch INTEGER NOT NULL,
            worker_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (run_id, stage_key),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS stage_commits (
            run_id TEXT NOT NULL,
            owner_scope TEXT NOT NULL,
            stage_key TEXT NOT NULL,
            attempt INTEGER NOT NULL,
            idempotency_key TEXT NOT NULL,
            status TEXT NOT NULL,
            output_artifact_id TEXT,
            commit_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (run_id, stage_key, attempt),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );
        CREATE UNIQUE INDEX IF NOT EXISTS
            idx_stage_committed_idempotency
        ON stage_commits(owner_scope, idempotency_key)
        WHERE status = 'committed';
        CREATE INDEX IF NOT EXISTS idx_stage_run
            ON stage_commits(run_id, stage_key);
        CREATE TABLE IF NOT EXISTS outbox (
            outbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            stage_key TEXT NOT NULL,
            output_ref_json TEXT NOT NULL,
            status TEXT NOT NULL,
            worker_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_outbox_status
            ON outbox(status, outbox_id);
        CREATE TABLE IF NOT EXISTS pointers (
            owner_scope TEXT NOT NULL,
            pointer_key TEXT NOT NULL,
            artifact_ref_json TEXT NOT NULL,
            version INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (owner_scope, pointer_key)
        );
        CREATE TABLE IF NOT EXISTS release_events (
            owner_scope TEXT NOT NULL,
            release_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            event_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            decision_id TEXT,
            rollback_id TEXT,
            previous_event_digest TEXT,
            event_digest TEXT NOT NULL,
            event_json TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            PRIMARY KEY (owner_scope, release_id, sequence),
            UNIQUE (owner_scope, event_id),
            CHECK (
                (
                    event_type = 'canary_decision'
                    AND decision_id IS NOT NULL
                    AND rollback_id IS NULL
                )
                OR (
                    event_type = 'rollback'
                    AND decision_id IS NULL
                    AND rollback_id IS NOT NULL
                )
            )
        );
        CREATE UNIQUE INDEX IF NOT EXISTS
            idx_release_event_decision
        ON release_events(owner_scope, decision_id)
        WHERE decision_id IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS
            idx_release_event_rollback
        ON release_events(owner_scope, rollback_id)
        WHERE rollback_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_release_event_release
            ON release_events(owner_scope, release_id, sequence);
        CREATE TRIGGER IF NOT EXISTS release_events_no_update
        BEFORE UPDATE ON release_events
        BEGIN
            SELECT RAISE(ABORT, 'release events are append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS release_events_no_delete
        BEFORE DELETE ON release_events
        BEGIN
            SELECT RAISE(ABORT, 'release events are append-only');
        END;
        CREATE TABLE IF NOT EXISTS quality_attestations (
            attestation_id TEXT PRIMARY KEY,
            owner_scope TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            attestation_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_quality_artifact
            ON quality_attestations(owner_scope, artifact_id, created_at);
        CREATE TABLE IF NOT EXISTS release_readiness_evidence (
            owner_scope TEXT NOT NULL,
            release_id TEXT NOT NULL,
            evidence_digest TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            recorder_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (owner_scope, release_id)
        );
        CREATE TRIGGER IF NOT EXISTS release_readiness_no_update
        BEFORE UPDATE ON release_readiness_evidence
        BEGIN
            SELECT RAISE(ABORT, 'release readiness evidence is append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS release_readiness_no_delete
        BEFORE DELETE ON release_readiness_evidence
        BEGIN
            SELECT RAISE(ABORT, 'release readiness evidence is append-only');
        END;
        CREATE TABLE IF NOT EXISTS canary_observations (
            owner_scope TEXT NOT NULL,
            release_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            observation_digest TEXT NOT NULL,
            observation_json TEXT NOT NULL,
            recorder_json TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            PRIMARY KEY (owner_scope, observation_digest)
        );
        CREATE INDEX IF NOT EXISTS idx_canary_observation_release
            ON canary_observations(
                owner_scope, release_id, stage, observed_at
            );
        CREATE TRIGGER IF NOT EXISTS canary_observations_no_update
        BEFORE UPDATE ON canary_observations
        BEGIN
            SELECT RAISE(ABORT, 'canary observations are append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS canary_observations_no_delete
        BEFORE DELETE ON canary_observations
        BEGIN
            SELECT RAISE(ABORT, 'canary observations are append-only');
        END;
        """
        with self._lock, self._connect() as connection:
            connection.executescript(schema)

    @staticmethod
    def _owner_scope(owner_id: str) -> str:
        return hashlib.sha256(
            ("zlb-vnext-control-owner-v1\0" + owner_id).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _json(model) -> str:
        return canonical_json_bytes(model).decode("utf-8")

    @staticmethod
    def _parse_time(value: str) -> datetime:
        return datetime.fromisoformat(value)

    def create_run(self, manifest: RunManifest) -> None:
        if manifest.revision != 1:
            raise ValueError("create_run requires manifest revision 1")
        owner_scope = self._owner_scope(manifest.owner_id)
        manifest_json = self._json(manifest)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO runs (
                    run_id, owner_scope, current_revision, manifest_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest.run_id,
                    owner_scope,
                    manifest.revision,
                    manifest_json,
                    manifest.created_at.isoformat(),
                    manifest.updated_at.isoformat(),
                ),
            )
            connection.execute(
                """
                INSERT INTO run_manifest_versions (
                    run_id, revision, manifest_json, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    manifest.run_id,
                    manifest.revision,
                    manifest_json,
                    manifest.updated_at.isoformat(),
                ),
            )

    def load_run(
        self,
        run_id: str,
        *,
        owner_id: str | None = None,
    ) -> RunManifest | None:
        query = "SELECT owner_scope, manifest_json FROM runs WHERE run_id = ?"
        with self._lock, self._connect() as connection:
            row = connection.execute(query, (run_id,)).fetchone()
        if row is None:
            return None
        if owner_id is not None and row["owner_scope"] != self._owner_scope(
            owner_id
        ):
            return None
        return RunManifest.model_validate_json(row["manifest_json"])

    def run_exists_for_other_owner(
        self,
        run_id: str,
        *,
        owner_id: str,
    ) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT owner_scope FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return (
            row is not None
            and row["owner_scope"] != self._owner_scope(owner_id)
        )

    def compare_and_swap_manifest(
        self,
        manifest: RunManifest,
        *,
        expected_revision: int,
    ) -> None:
        if manifest.revision != expected_revision + 1:
            raise ValueError("manifest revision must increment by one")
        owner_scope = self._owner_scope(manifest.owner_id)
        manifest_json = self._json(manifest)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                """
                SELECT owner_scope, current_revision, manifest_json
                FROM runs WHERE run_id = ?
                """,
                (manifest.run_id,),
            ).fetchone()
            if current is None:
                raise CompareAndSwapConflict("run does not exist")
            if current["owner_scope"] != owner_scope:
                raise PermissionError("run owner mismatch")
            previous = RunManifest.model_validate_json(
                current["manifest_json"]
            )
            if (
                int(current["current_revision"]) != expected_revision
                or manifest.supersedes != previous.manifest_id
            ):
                raise CompareAndSwapConflict("stale run manifest revision")
            updated = connection.execute(
                """
                UPDATE runs
                SET current_revision = ?, manifest_json = ?, updated_at = ?
                WHERE run_id = ? AND current_revision = ?
                """,
                (
                    manifest.revision,
                    manifest_json,
                    manifest.updated_at.isoformat(),
                    manifest.run_id,
                    expected_revision,
                ),
            )
            if updated.rowcount != 1:
                raise CompareAndSwapConflict("manifest CAS failed")
            connection.execute(
                """
                INSERT INTO run_manifest_versions (
                    run_id, revision, manifest_json, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    manifest.run_id,
                    manifest.revision,
                    manifest_json,
                    manifest.updated_at.isoformat(),
                ),
            )

    def acquire_stage_lease(
        self,
        *,
        run_id: str,
        stage_key: str,
        worker_id: str,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> StageLease:
        if ttl_seconds < 1:
            raise ValueError("lease ttl must be positive")
        timestamp = now or datetime.now(UTC)
        expires_at = timestamp + timedelta(seconds=ttl_seconds)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT lease_epoch, worker_id, expires_at, status
                FROM stage_leases
                WHERE run_id = ? AND stage_key = ?
                """,
                (run_id, stage_key),
            ).fetchone()
            if row is None:
                epoch = 1
                connection.execute(
                    """
                    INSERT INTO stage_leases (
                        run_id, stage_key, lease_epoch, worker_id,
                        expires_at, status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'running', ?)
                    """,
                    (
                        run_id,
                        stage_key,
                        epoch,
                        worker_id,
                        expires_at.isoformat(),
                        timestamp.isoformat(),
                    ),
                )
            else:
                current_expiry = self._parse_time(row["expires_at"])
                active = (
                    row["status"] == "running"
                    and current_expiry > timestamp
                )
                if active and row["worker_id"] != worker_id:
                    raise LeaseConflict("stage lease is held by another worker")
                if active:
                    epoch = int(row["lease_epoch"])
                else:
                    epoch = int(row["lease_epoch"]) + 1
                connection.execute(
                    """
                    UPDATE stage_leases
                    SET lease_epoch = ?, worker_id = ?, expires_at = ?,
                        status = 'running', updated_at = ?
                    WHERE run_id = ? AND stage_key = ?
                    """,
                    (
                        epoch,
                        worker_id,
                        expires_at.isoformat(),
                        timestamp.isoformat(),
                        run_id,
                        stage_key,
                    ),
                )
        return StageLease(
            run_id=run_id,
            stage_key=stage_key,
            lease_epoch=epoch,
            worker_id=worker_id,
            expires_at=expires_at,
        )

    def find_committed_stage(
        self,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> StageCommit | None:
        owner_scope = self._owner_scope(owner_id)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT commit_json FROM stage_commits
                WHERE owner_scope = ? AND idempotency_key = ?
                    AND status = 'committed'
                """,
                (owner_scope, idempotency_key),
            ).fetchone()
        return (
            StageCommit.model_validate_json(row["commit_json"])
            if row
            else None
        )

    def commit_stage(
        self,
        commit: StageCommit,
        *,
        worker_id: str,
        now: datetime | None = None,
    ) -> StageCommit:
        if commit.status is not StageCommitStatus.COMMITTED:
            raise ValueError("commit_stage requires committed status")
        assert commit.output_ref is not None
        timestamp = now or datetime.now(UTC)
        owner_scope = self._owner_scope(commit.owner_id)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT owner_scope FROM runs WHERE run_id = ?",
                (commit.run_id,),
            ).fetchone()
            if run is None or run["owner_scope"] != owner_scope:
                raise PermissionError("stage run owner mismatch")
            existing = connection.execute(
                """
                SELECT commit_json FROM stage_commits
                WHERE owner_scope = ? AND idempotency_key = ?
                    AND status = 'committed'
                """,
                (owner_scope, commit.idempotency_key),
            ).fetchone()
            if existing is not None:
                previous = StageCommit.model_validate_json(
                    existing["commit_json"]
                )
                if previous.output_ref != commit.output_ref:
                    raise CompareAndSwapConflict(
                        "idempotency key already committed another output"
                    )
                return previous
            lease = connection.execute(
                """
                SELECT lease_epoch, worker_id, expires_at, status
                FROM stage_leases
                WHERE run_id = ? AND stage_key = ?
                """,
                (commit.run_id, commit.stage_key),
            ).fetchone()
            if (
                lease is None
                or int(lease["lease_epoch"]) != commit.lease_epoch
                or lease["worker_id"] != worker_id
                or lease["status"] != "running"
                or self._parse_time(lease["expires_at"]) < timestamp
            ):
                raise CompareAndSwapConflict(
                    "stage commit lease epoch is stale or expired"
                )
            commit_json = self._json(commit)
            connection.execute(
                """
                INSERT INTO stage_commits (
                    run_id, owner_scope, stage_key, attempt,
                    idempotency_key, status, output_artifact_id,
                    commit_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    commit.run_id,
                    owner_scope,
                    commit.stage_key,
                    commit.attempt,
                    commit.idempotency_key,
                    commit.status.value,
                    commit.output_ref.artifact_id,
                    commit_json,
                    commit.created_at.isoformat(),
                    commit.updated_at.isoformat(),
                ),
            )
            connection.execute(
                """
                INSERT INTO outbox (
                    run_id, stage_key, output_ref_json, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', ?, ?)
                """,
                (
                    commit.run_id,
                    commit.stage_key,
                    self._json(commit.output_ref),
                    timestamp.isoformat(),
                    timestamp.isoformat(),
                ),
            )
            connection.execute(
                """
                UPDATE stage_leases
                SET status = 'committed', updated_at = ?
                WHERE run_id = ? AND stage_key = ?
                    AND lease_epoch = ?
                """,
                (
                    timestamp.isoformat(),
                    commit.run_id,
                    commit.stage_key,
                    commit.lease_epoch,
                ),
            )
        return commit

    def record_stage_reuse(
        self,
        *,
        run_id: str,
        stage_key: str,
        attempt: int,
        committed: StageCommit,
        now: datetime | None = None,
    ) -> StageCommit:
        timestamp = now or datetime.now(UTC)
        payload = committed.model_dump(mode="python")
        payload.update(
            {
                "run_id": run_id,
                "stage_key": stage_key,
                "attempt": attempt,
                "lease_epoch": 0,
                "status": StageCommitStatus.REUSED,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        )
        reused = StageCommit.model_validate(payload)
        owner_scope = self._owner_scope(reused.owner_id)
        with self._lock, self._connect() as connection:
            run = connection.execute(
                "SELECT owner_scope FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if run is None or run["owner_scope"] != owner_scope:
                raise PermissionError("stage reuse run owner mismatch")
            connection.execute(
                """
                INSERT INTO stage_commits (
                    run_id, owner_scope, stage_key, attempt,
                    idempotency_key, status, output_artifact_id,
                    commit_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reused.run_id,
                    owner_scope,
                    reused.stage_key,
                    reused.attempt,
                    reused.idempotency_key,
                    reused.status.value,
                    reused.output_ref.artifact_id,
                    self._json(reused),
                    timestamp.isoformat(),
                    timestamp.isoformat(),
                ),
            )
        return reused

    def list_run_commits(
        self,
        *,
        run_id: str,
        owner_id: str,
    ) -> tuple[StageCommit, ...]:
        owner_scope = self._owner_scope(owner_id)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT commit_json FROM stage_commits
                WHERE run_id = ? AND owner_scope = ?
                ORDER BY created_at, stage_key, attempt
                """,
                (run_id, owner_scope),
            ).fetchall()
        return tuple(
            StageCommit.model_validate_json(row["commit_json"])
            for row in rows
        )

    def claim_outbox(
        self,
        *,
        worker_id: str,
        limit: int = 100,
        now: datetime | None = None,
    ) -> tuple[OutboxItem, ...]:
        timestamp = now or datetime.now(UTC)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT outbox_id, run_id, stage_key, output_ref_json
                FROM outbox
                WHERE status = 'pending'
                ORDER BY outbox_id
                LIMIT ?
                """,
                (max(1, min(limit, 1000)),),
            ).fetchall()
            ids = [int(row["outbox_id"]) for row in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                connection.execute(
                    f"""
                    UPDATE outbox
                    SET status = 'claimed', worker_id = ?, updated_at = ?
                    WHERE outbox_id IN ({placeholders})
                    """,
                    (worker_id, timestamp.isoformat(), *ids),
                )
        return tuple(
            OutboxItem(
                outbox_id=int(row["outbox_id"]),
                run_id=str(row["run_id"]),
                stage_key=str(row["stage_key"]),
                output_ref=ArtifactRef.model_validate_json(
                    row["output_ref_json"]
                ),
            )
            for row in rows
        )

    def acknowledge_outbox(
        self,
        outbox_id: int,
        *,
        worker_id: str,
        now: datetime | None = None,
    ) -> None:
        timestamp = now or datetime.now(UTC)
        with self._lock, self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE outbox
                SET status = 'published', updated_at = ?
                WHERE outbox_id = ? AND status = 'claimed'
                    AND worker_id = ?
                """,
                (timestamp.isoformat(), outbox_id, worker_id),
            )
            if updated.rowcount != 1:
                raise CompareAndSwapConflict("outbox acknowledgement failed")

    def compare_and_swap_pointer(
        self,
        *,
        owner_id: str,
        pointer_key: str,
        artifact_ref: ArtifactRef,
        expected_version: int | None,
        now: datetime | None = None,
    ) -> PointerRecord:
        if artifact_ref.owner_id != owner_id:
            raise PermissionError("pointer artifact owner mismatch")
        timestamp = now or datetime.now(UTC)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _, pointer = self._compare_and_swap_pointer_in_connection(
                connection,
                owner_id=owner_id,
                pointer_key=pointer_key,
                artifact_ref=artifact_ref,
                expected_version=expected_version,
                now=timestamp,
            )
            return pointer

    def load_pointer(
        self,
        *,
        owner_id: str,
        pointer_key: str,
    ) -> PointerRecord | None:
        with self._lock, self._connect() as connection:
            return self._load_pointer_in_connection(
                connection,
                owner_id=owner_id,
                pointer_key=pointer_key,
            )

    def publish_pointer(
        self,
        manifest: RunManifest,
        *,
        pointer_key: str,
        artifact_ref: ArtifactRef,
        expected_version: int | None,
    ) -> PointerRecord:
        self._validate_publish_manifest(manifest)
        return self.compare_and_swap_pointer(
            owner_id=manifest.owner_id,
            pointer_key=pointer_key,
            artifact_ref=artifact_ref,
            expected_version=expected_version,
        )

    def append_release_decision(
        self,
        *,
        owner_id: str,
        decision: CanaryTransitionDecision,
        expected_release_sequence: int | None,
    ) -> ReleaseEvent:
        if decision.decision is CanaryDecision.ADVANCE:
            raise ValueError(
                "advance decision must be recorded with its pointer change"
            )
        owner_scope = self._owner_scope(owner_id)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._find_release_event_in_connection(
                connection,
                owner_id=owner_id,
                owner_scope=owner_scope,
                identity_column="decision_id",
                identity_value=decision.decision_id,
            )
            if existing is not None:
                self._assert_same_decision(existing, decision)
                return existing
            return self._append_release_event_in_connection(
                connection,
                owner_id=owner_id,
                owner_scope=owner_scope,
                release_id=decision.release_id,
                event_type=ReleaseEventType.CANARY_DECISION,
                decision=decision,
                rollback=None,
                pointer_before=None,
                pointer_after=None,
                expected_release_sequence=expected_release_sequence,
                recorded_at=decision.decided_at,
            )

    def publish_pointer_with_release_decision(
        self,
        manifest: RunManifest,
        decision: CanaryTransitionDecision,
        *,
        pointer_key: str,
        artifact_ref: ArtifactRef,
        expected_pointer_version: int | None,
        expected_release_sequence: int | None,
    ) -> tuple[PointerRecord, ReleaseEvent]:
        self._validate_publish_manifest(manifest)
        if decision.decision is not CanaryDecision.ADVANCE:
            raise ValueError(
                "release pointer publication requires advance decision"
            )
        if artifact_ref.owner_id != manifest.owner_id:
            raise PermissionError("pointer artifact owner mismatch")
        owner_scope = self._owner_scope(manifest.owner_id)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._find_release_event_in_connection(
                connection,
                owner_id=manifest.owner_id,
                owner_scope=owner_scope,
                identity_column="decision_id",
                identity_value=decision.decision_id,
            )
            if existing is not None:
                self._assert_same_decision(existing, decision)
                self._assert_pointer_retry(
                    existing,
                    pointer_key=pointer_key,
                    artifact_ref=artifact_ref,
                    expected_pointer_version=expected_pointer_version,
                )
                if existing.pointer_after is None:
                    raise ReleaseEventIntegrityError(
                        "advance event has no resulting pointer"
                    )
                return (
                    self._pointer_from_snapshot(
                        manifest.owner_id,
                        existing.pointer_after,
                    ),
                    existing,
                )
            before, pointer = (
                self._compare_and_swap_pointer_in_connection(
                    connection,
                    owner_id=manifest.owner_id,
                    pointer_key=pointer_key,
                    artifact_ref=artifact_ref,
                    expected_version=expected_pointer_version,
                    now=decision.decided_at,
                )
            )
            event = self._append_release_event_in_connection(
                connection,
                owner_id=manifest.owner_id,
                owner_scope=owner_scope,
                release_id=decision.release_id,
                event_type=ReleaseEventType.CANARY_DECISION,
                decision=decision,
                rollback=None,
                pointer_before=(
                    self._pointer_snapshot(before)
                    if before is not None
                    else None
                ),
                pointer_after=self._pointer_snapshot(pointer),
                expected_release_sequence=expected_release_sequence,
                recorded_at=decision.decided_at,
            )
            return pointer, event

    def rollback_pointer_with_release_event(
        self,
        *,
        owner_id: str,
        release_id: str,
        candidate_artifact_ref: ArtifactRef,
        pointer_key: str,
        stable_pointer_key: str,
        expected_pointer_version: int,
        expected_release_sequence: int | None,
        reason_codes: tuple[str, ...],
        rolled_back_at: datetime,
    ) -> tuple[PointerRecord, RollbackRecord, ReleaseEvent]:
        if candidate_artifact_ref.owner_id != owner_id:
            raise PermissionError("rollback candidate owner mismatch")
        if expected_pointer_version < 1:
            raise ValueError(
                "rollback expected pointer version must be positive"
            )
        normalized_reasons = tuple(sorted(set(reason_codes)))
        if not normalized_reasons:
            raise ValueError("rollback requires reason codes")
        owner_scope = self._owner_scope(owner_id)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rollback_id = self._rollback_id(
                owner_id=owner_id,
                release_id=release_id,
                from_artifact_ref=candidate_artifact_ref,
                pointer_key=pointer_key,
                expected_pointer_version=expected_pointer_version,
                reason_codes=normalized_reasons,
            )
            existing = self._find_release_event_in_connection(
                connection,
                owner_id=owner_id,
                owner_scope=owner_scope,
                identity_column="rollback_id",
                identity_value=rollback_id,
            )
            if existing is not None:
                self._assert_same_rollback_request(
                    existing,
                    rollback_id=rollback_id,
                    release_id=release_id,
                    owner_id=owner_id,
                    from_artifact_ref=candidate_artifact_ref,
                    pointer_key=pointer_key,
                    expected_pointer_version=expected_pointer_version,
                    reason_codes=normalized_reasons,
                )
                if existing.rollback is None or existing.pointer_after is None:
                    raise ReleaseEventIntegrityError(
                        "rollback event is incomplete"
                    )
                return (
                    self._pointer_from_snapshot(
                        owner_id,
                        existing.pointer_after,
                    ),
                    existing.rollback,
                    existing,
                )
            stable = self._load_pointer_in_connection(
                connection,
                owner_id=owner_id,
                pointer_key=stable_pointer_key,
            )
            if stable is None:
                raise ValueError(
                    "rollback requires an existing stable published pointer"
                )
            current = self._load_pointer_in_connection(
                connection,
                owner_id=owner_id,
                pointer_key=pointer_key,
            )
            if current is None:
                raise ValueError("canary pointer does not exist")
            if current.artifact_ref != candidate_artifact_ref:
                raise ValueError(
                    "canary pointer no longer references this candidate"
                )
            _, pointer = self._compare_and_swap_pointer_in_connection(
                connection,
                owner_id=owner_id,
                pointer_key=pointer_key,
                artifact_ref=stable.artifact_ref,
                expected_version=expected_pointer_version,
                now=rolled_back_at,
            )
            rollback = RollbackRecord(
                rollback_id=rollback_id,
                release_id=release_id,
                owner_id=owner_id,
                from_artifact_ref=current.artifact_ref,
                restored_artifact_ref=stable.artifact_ref,
                pointer_key=pointer_key,
                pointer_version=pointer.version,
                reason_codes=normalized_reasons,
                rolled_back_at=rolled_back_at,
            )
            event = self._append_release_event_in_connection(
                connection,
                owner_id=owner_id,
                owner_scope=owner_scope,
                release_id=release_id,
                event_type=ReleaseEventType.ROLLBACK,
                decision=None,
                rollback=rollback,
                pointer_before=self._pointer_snapshot(current),
                pointer_after=self._pointer_snapshot(pointer),
                expected_release_sequence=expected_release_sequence,
                recorded_at=rolled_back_at,
            )
            return pointer, rollback, event

    def list_release_events(
        self,
        *,
        owner_id: str,
        release_id: str,
    ) -> tuple[ReleaseEvent, ...]:
        owner_scope = self._owner_scope(owner_id)
        with self._lock, self._connect() as connection:
            return self._load_release_events_in_connection(
                connection,
                owner_id=owner_id,
                owner_scope=owner_scope,
                release_id=release_id,
            )

    @staticmethod
    def _validate_publish_manifest(manifest: RunManifest) -> None:
        if manifest.execution_status is not ExecutionStatus.SUCCEEDED:
            raise ControlPlaneError("cannot publish an unfinished run")
        if manifest.quality_status is not QualityStatus.PASSED:
            raise ControlPlaneError("cannot publish a run that failed quality")
        if manifest.publication_status not in {
            PublicationStatus.RELEASE_CANDIDATE,
            PublicationStatus.PUBLISHED,
        }:
            raise ControlPlaneError(
                "run manifest is not a release candidate"
            )

    def _load_pointer_in_connection(
        self,
        connection: sqlite3.Connection,
        *,
        owner_id: str,
        pointer_key: str,
    ) -> PointerRecord | None:
        row = connection.execute(
            """
            SELECT artifact_ref_json, version, updated_at
            FROM pointers
            WHERE owner_scope = ? AND pointer_key = ?
            """,
            (self._owner_scope(owner_id), pointer_key),
        ).fetchone()
        if row is None:
            return None
        return PointerRecord(
            owner_id=owner_id,
            pointer_key=pointer_key,
            artifact_ref=ArtifactRef.model_validate_json(
                row["artifact_ref_json"]
            ),
            version=int(row["version"]),
            updated_at=self._parse_time(row["updated_at"]),
        )

    def _compare_and_swap_pointer_in_connection(
        self,
        connection: sqlite3.Connection,
        *,
        owner_id: str,
        pointer_key: str,
        artifact_ref: ArtifactRef,
        expected_version: int | None,
        now: datetime,
    ) -> tuple[PointerRecord | None, PointerRecord]:
        if artifact_ref.owner_id != owner_id:
            raise PermissionError("pointer artifact owner mismatch")
        owner_scope = self._owner_scope(owner_id)
        before = self._load_pointer_in_connection(
            connection,
            owner_id=owner_id,
            pointer_key=pointer_key,
        )
        if before is None:
            if expected_version not in {None, 0}:
                raise CompareAndSwapConflict(
                    "pointer does not exist at expected version"
                )
            version = 1
            connection.execute(
                """
                INSERT INTO pointers (
                    owner_scope, pointer_key, artifact_ref_json,
                    version, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    owner_scope,
                    pointer_key,
                    self._json(artifact_ref),
                    version,
                    now.isoformat(),
                ),
            )
        else:
            if expected_version != before.version:
                raise CompareAndSwapConflict("stale pointer version")
            version = before.version + 1
            updated = connection.execute(
                """
                UPDATE pointers
                SET artifact_ref_json = ?, version = ?, updated_at = ?
                WHERE owner_scope = ? AND pointer_key = ?
                    AND version = ?
                """,
                (
                    self._json(artifact_ref),
                    version,
                    now.isoformat(),
                    owner_scope,
                    pointer_key,
                    before.version,
                ),
            )
            if updated.rowcount != 1:
                raise CompareAndSwapConflict("pointer CAS failed")
        return (
            before,
            PointerRecord(
                owner_id=owner_id,
                pointer_key=pointer_key,
                artifact_ref=artifact_ref,
                version=version,
                updated_at=now,
            ),
        )

    @staticmethod
    def _pointer_snapshot(
        pointer: PointerRecord,
    ) -> ReleasePointerSnapshot:
        return ReleasePointerSnapshot(
            pointer_key=pointer.pointer_key,
            artifact_ref=pointer.artifact_ref,
            version=pointer.version,
            updated_at=pointer.updated_at,
        )

    @staticmethod
    def _pointer_from_snapshot(
        owner_id: str,
        snapshot: ReleasePointerSnapshot,
    ) -> PointerRecord:
        if snapshot.artifact_ref.owner_id != owner_id:
            raise ReleaseEventIntegrityError(
                "release pointer snapshot owner mismatch"
            )
        return PointerRecord(
            owner_id=owner_id,
            pointer_key=snapshot.pointer_key,
            artifact_ref=snapshot.artifact_ref,
            version=snapshot.version,
            updated_at=snapshot.updated_at,
        )

    @staticmethod
    def _release_event_id(
        *,
        owner_id: str,
        release_id: str,
        event_type: ReleaseEventType,
        source_record_id: str,
    ) -> str:
        digest = hashlib.sha256(
            (
                "zlb-vnext-release-event-v1\0"
                + owner_id
                + "\0"
                + release_id
                + "\0"
                + event_type.value
                + "\0"
                + source_record_id
            ).encode("utf-8")
        ).hexdigest()
        return "release_event_" + digest[:32]

    @staticmethod
    def _rollback_id(
        *,
        owner_id: str,
        release_id: str,
        from_artifact_ref: ArtifactRef,
        pointer_key: str,
        expected_pointer_version: int,
        reason_codes: tuple[str, ...],
    ) -> str:
        digest = hashlib.sha256(
            b"zlb-vnext-rollback-v2\0"
            + canonical_json_bytes(
                {
                    "expected_pointer_version": expected_pointer_version,
                    "from_artifact_ref": from_artifact_ref,
                    "owner_id": owner_id,
                    "pointer_key": pointer_key,
                    "reason_codes": reason_codes,
                    "release_id": release_id,
                }
            )
        ).hexdigest()
        return "rollback_" + digest[:32]

    @staticmethod
    def _normalized_release_sequence(value: int | None) -> int:
        if value is None:
            return 0
        if value < 0:
            raise ValueError(
                "expected release sequence cannot be negative"
            )
        return value

    def _append_release_event_in_connection(
        self,
        connection: sqlite3.Connection,
        *,
        owner_id: str,
        owner_scope: str,
        release_id: str,
        event_type: ReleaseEventType,
        decision: CanaryTransitionDecision | None,
        rollback: RollbackRecord | None,
        pointer_before: ReleasePointerSnapshot | None,
        pointer_after: ReleasePointerSnapshot | None,
        expected_release_sequence: int | None,
        recorded_at: datetime,
    ) -> ReleaseEvent:
        latest = connection.execute(
            """
            SELECT sequence, event_digest
            FROM release_events
            WHERE owner_scope = ? AND release_id = ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (owner_scope, release_id),
        ).fetchone()
        current_sequence = int(latest["sequence"]) if latest else 0
        if current_sequence != self._normalized_release_sequence(
            expected_release_sequence
        ):
            raise CompareAndSwapConflict(
                "stale release event sequence"
            )
        sequence = current_sequence + 1
        previous_digest = (
            str(latest["event_digest"]) if latest is not None else None
        )
        if decision is not None:
            source_record_id = decision.decision_id
            decision_id = decision.decision_id
            rollback_id = None
        elif rollback is not None:
            source_record_id = rollback.rollback_id
            decision_id = None
            rollback_id = rollback.rollback_id
        else:
            raise ValueError("release event requires a source record")
        event_id = self._release_event_id(
            owner_id=owner_id,
            release_id=release_id,
            event_type=event_type,
            source_record_id=source_record_id,
        )
        event_payload = {
            "schema_version": "1.0.0",
            "event_id": event_id,
            "owner_id": owner_id,
            "release_id": release_id,
            "sequence": sequence,
            "event_type": event_type,
            "previous_event_digest": previous_digest,
            "decision": decision,
            "rollback": rollback,
            "pointer_before": pointer_before,
            "pointer_after": pointer_after,
            "recorded_at": recorded_at,
        }
        draft = ReleaseEvent.model_validate(
            {
                **event_payload,
                "event_digest": "sha256:" + ("0" * 64),
            }
        )
        event = ReleaseEvent.model_validate(
            {
                **draft.model_dump(mode="python"),
                "event_digest": payload_digest(
                    draft.model_dump(
                        mode="json",
                        exclude={"event_digest"},
                    )
                ),
            }
        )
        connection.execute(
            """
            INSERT INTO release_events (
                owner_scope, release_id, sequence, event_id,
                event_type, decision_id, rollback_id,
                previous_event_digest, event_digest, event_json,
                recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner_scope,
                release_id,
                sequence,
                event.event_id,
                event.event_type.value,
                decision_id,
                rollback_id,
                event.previous_event_digest,
                event.event_digest,
                self._json(event),
                event.recorded_at.isoformat(),
            ),
        )
        return event

    def _find_release_event_in_connection(
        self,
        connection: sqlite3.Connection,
        *,
        owner_id: str,
        owner_scope: str,
        identity_column: str,
        identity_value: str,
    ) -> ReleaseEvent | None:
        if identity_column not in {"decision_id", "rollback_id"}:
            raise ValueError("invalid release event identity column")
        row = connection.execute(
            f"""
            SELECT release_id
            FROM release_events
            WHERE owner_scope = ? AND {identity_column} = ?
            """,
            (owner_scope, identity_value),
        ).fetchone()
        if row is None:
            return None
        events = self._load_release_events_in_connection(
            connection,
            owner_id=owner_id,
            owner_scope=owner_scope,
            release_id=str(row["release_id"]),
        )
        for event in events:
            source_id = (
                event.decision.decision_id
                if event.decision is not None
                else event.rollback.rollback_id
                if event.rollback is not None
                else None
            )
            if source_id == identity_value:
                return event
        raise ReleaseEventIntegrityError(
            "release event identity index does not match payload"
        )

    def _load_release_events_in_connection(
        self,
        connection: sqlite3.Connection,
        *,
        owner_id: str,
        owner_scope: str,
        release_id: str,
    ) -> tuple[ReleaseEvent, ...]:
        rows = connection.execute(
            """
            SELECT release_id, sequence, event_id, event_type,
                   decision_id, rollback_id, previous_event_digest,
                   event_digest, event_json, recorded_at
            FROM release_events
            WHERE owner_scope = ? AND release_id = ?
            ORDER BY sequence
            """,
            (owner_scope, release_id),
        ).fetchall()
        events: list[ReleaseEvent] = []
        previous_digest: str | None = None
        for expected_sequence, row in enumerate(rows, start=1):
            try:
                event = ReleaseEvent.model_validate_json(
                    row["event_json"]
                )
            except Exception as exc:
                raise ReleaseEventIntegrityError(
                    "release event payload is invalid"
                ) from exc
            source_id = (
                event.decision.decision_id
                if event.decision is not None
                else event.rollback.rollback_id
                if event.rollback is not None
                else None
            )
            expected_event_id = (
                self._release_event_id(
                    owner_id=owner_id,
                    release_id=release_id,
                    event_type=event.event_type,
                    source_record_id=source_id,
                )
                if source_id is not None
                else None
            )
            expected_decision_id = (
                event.decision.decision_id
                if event.decision is not None
                else None
            )
            expected_rollback_id = (
                event.rollback.rollback_id
                if event.rollback is not None
                else None
            )
            if (
                event.owner_id != owner_id
                or event.release_id != release_id
                or event.sequence != expected_sequence
                or int(row["sequence"]) != expected_sequence
                or row["release_id"] != release_id
                or row["event_id"] != event.event_id
                or event.event_id != expected_event_id
                or row["event_type"] != event.event_type.value
                or row["decision_id"] != expected_decision_id
                or row["rollback_id"] != expected_rollback_id
                or row["previous_event_digest"] != previous_digest
                or event.previous_event_digest != previous_digest
                or row["recorded_at"] != event.recorded_at.isoformat()
            ):
                raise ReleaseEventIntegrityError(
                    "release event chain metadata mismatch"
                )
            computed_digest = payload_digest(
                event.model_dump(
                    mode="json",
                    exclude={"event_digest"},
                )
            )
            if (
                event.event_digest != computed_digest
                or row["event_digest"] != computed_digest
            ):
                raise ReleaseEventIntegrityError(
                    "release event digest mismatch"
                )
            if row["event_json"] != self._json(event):
                raise ReleaseEventIntegrityError(
                    "release event payload is not canonical"
                )
            events.append(event)
            previous_digest = event.event_digest
        return tuple(events)

    @staticmethod
    def _semantic_digest(model, *, exclude: set[str]) -> str:
        return payload_digest(
            model.model_dump(mode="json", exclude=exclude)
        )

    def _assert_same_decision(
        self,
        event: ReleaseEvent,
        decision: CanaryTransitionDecision,
    ) -> None:
        if event.decision is None:
            raise ReleaseEventIntegrityError(
                "decision identity points to another event type"
            )
        if self._semantic_digest(
            event.decision,
            exclude={"decided_at"},
        ) != self._semantic_digest(
            decision,
            exclude={"decided_at"},
        ):
            raise ReleaseEventIntegrityError(
                "decision ID was reused with different semantics"
            )

    @staticmethod
    def _assert_pointer_retry(
        event: ReleaseEvent,
        *,
        pointer_key: str,
        artifact_ref: ArtifactRef,
        expected_pointer_version: int | None,
    ) -> None:
        after = event.pointer_after
        before = event.pointer_before
        if (
            after is None
            or after.pointer_key != pointer_key
            or after.artifact_ref != artifact_ref
        ):
            raise ReleaseEventIntegrityError(
                "decision retry does not match stored pointer result"
            )
        if before is None:
            if expected_pointer_version not in {None, 0}:
                raise CompareAndSwapConflict(
                    "decision retry pointer expectation mismatch"
                )
        elif expected_pointer_version != before.version:
            raise CompareAndSwapConflict(
                "decision retry pointer expectation mismatch"
            )

    @staticmethod
    def _assert_same_rollback_request(
        event: ReleaseEvent,
        *,
        rollback_id: str,
        release_id: str,
        owner_id: str,
        from_artifact_ref: ArtifactRef,
        pointer_key: str,
        expected_pointer_version: int,
        reason_codes: tuple[str, ...],
    ) -> None:
        rollback = event.rollback
        before = event.pointer_before
        if (
            rollback is None
            or rollback.rollback_id != rollback_id
            or rollback.release_id != release_id
            or rollback.owner_id != owner_id
            or rollback.from_artifact_ref != from_artifact_ref
            or rollback.pointer_key != pointer_key
            or rollback.reason_codes != reason_codes
            or before is None
            or before.version != expected_pointer_version
        ):
            raise ReleaseEventIntegrityError(
                "rollback ID was reused with different semantics"
            )

    def record_quality_attestation(
        self,
        attestation: QualityAttestation,
    ) -> None:
        validated = QualityAttestation.model_validate(
            attestation.model_dump(mode="python")
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO quality_attestations (
                    attestation_id, owner_scope, artifact_id,
                    attestation_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    validated.attestation_id,
                    self._owner_scope(validated.owner_id),
                    validated.artifact_ref.artifact_id,
                    self._json(validated),
                    validated.created_at.isoformat(),
                ),
            )

    def load_quality_attestation(
        self,
        *,
        owner_id: str,
        artifact_ref: ArtifactRef,
    ) -> QualityAttestation | None:
        if artifact_ref.owner_id != owner_id:
            return None
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT attestation_json
                FROM quality_attestations
                WHERE owner_scope = ? AND artifact_id = ?
                ORDER BY created_at DESC, attestation_id DESC
                LIMIT 1
                """,
                (
                    self._owner_scope(owner_id),
                    artifact_ref.artifact_id,
                ),
            ).fetchone()
        if row is None:
            return None
        attestation = QualityAttestation.model_validate_json(
            row["attestation_json"]
        )
        if attestation.artifact_ref != artifact_ref:
            raise ControlPlaneError(
                "quality attestation artifact reference mismatch"
            )
        return attestation

    def record_release_readiness_evidence(
        self,
        evidence: ReleaseReadinessEvidence,
        *,
        recorder: ArtifactProducerRef,
    ) -> None:
        if recorder.role is not RuntimeRole.RELEASE_EVIDENCE_AGGREGATOR:
            raise PermissionError(
                "release readiness requires trusted evidence aggregator"
            )
        owner_scope = self._owner_scope(evidence.owner_id)
        digest = payload_digest(evidence)
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                """
                SELECT evidence_digest, evidence_json, recorder_json
                FROM release_readiness_evidence
                WHERE owner_scope = ? AND release_id = ?
                """,
                (owner_scope, evidence.release_id),
            ).fetchone()
            if existing is not None:
                if (
                    existing["evidence_digest"] != digest
                    or existing["evidence_json"] != self._json(evidence)
                    or existing["recorder_json"] != self._json(recorder)
                ):
                    raise CompareAndSwapConflict(
                        "release readiness evidence is already frozen"
                    )
                return
            connection.execute(
                """
                INSERT INTO release_readiness_evidence (
                    owner_scope, release_id, evidence_digest,
                    evidence_json, recorder_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    owner_scope,
                    evidence.release_id,
                    digest,
                    self._json(evidence),
                    self._json(recorder),
                    evidence.created_at.isoformat(),
                ),
            )

    def load_release_readiness_evidence(
        self,
        *,
        owner_id: str,
        release_id: str,
    ) -> ReleaseReadinessEvidence | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT evidence_digest, evidence_json, recorder_json
                FROM release_readiness_evidence
                WHERE owner_scope = ? AND release_id = ?
                """,
                (self._owner_scope(owner_id), release_id),
            ).fetchone()
        if row is None:
            return None
        recorder = ArtifactProducerRef.model_validate_json(
            row["recorder_json"]
        )
        if recorder.role is not RuntimeRole.RELEASE_EVIDENCE_AGGREGATOR:
            raise ControlPlaneError(
                "release readiness recorder role is not trusted"
            )
        evidence = ReleaseReadinessEvidence.model_validate_json(
            row["evidence_json"]
        )
        if (
            evidence.owner_id != owner_id
            or evidence.release_id != release_id
            or payload_digest(evidence) != row["evidence_digest"]
        ):
            raise ControlPlaneError(
                "release readiness evidence integrity mismatch"
            )
        return evidence

    def record_canary_observation(
        self,
        observation: CanaryObservation,
        *,
        owner_id: str,
        recorder: ArtifactProducerRef,
    ) -> None:
        if recorder.role is not RuntimeRole.CANARY_OBSERVATION_AGGREGATOR:
            raise PermissionError(
                "canary observation requires trusted aggregator"
            )
        digest = payload_digest(observation)
        owner_scope = self._owner_scope(owner_id)
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                """
                SELECT observation_json, recorder_json
                FROM canary_observations
                WHERE owner_scope = ? AND observation_digest = ?
                """,
                (owner_scope, digest),
            ).fetchone()
            if existing is not None:
                if (
                    existing["observation_json"]
                    != self._json(observation)
                    or existing["recorder_json"] != self._json(recorder)
                ):
                    raise CompareAndSwapConflict(
                        "canary observation digest collision"
                    )
                return
            connection.execute(
                """
                INSERT INTO canary_observations (
                    owner_scope, release_id, stage, observation_digest,
                    observation_json, recorder_json, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    owner_scope,
                    observation.release_id,
                    observation.stage.value,
                    digest,
                    self._json(observation),
                    self._json(recorder),
                    observation.observed_at.isoformat(),
                ),
            )

    def load_canary_observation(
        self,
        *,
        owner_id: str,
        release_id: str,
        stage: CanaryStage,
        observation_digest: str,
    ) -> CanaryObservation | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT observation_json, recorder_json
                FROM canary_observations
                WHERE owner_scope = ? AND release_id = ? AND stage = ?
                    AND observation_digest = ?
                """,
                (
                    self._owner_scope(owner_id),
                    release_id,
                    stage.value,
                    observation_digest,
                ),
            ).fetchone()
        if row is None:
            return None
        recorder = ArtifactProducerRef.model_validate_json(
            row["recorder_json"]
        )
        if recorder.role is not RuntimeRole.CANARY_OBSERVATION_AGGREGATOR:
            raise ControlPlaneError(
                "canary observation recorder role is not trusted"
            )
        observation = CanaryObservation.model_validate_json(
            row["observation_json"]
        )
        if (
            observation.release_id != release_id
            or observation.stage is not stage
            or payload_digest(observation) != observation_digest
        ):
            raise ControlPlaneError("canary observation integrity mismatch")
        return observation

    def referenced_artifact_ids(self, *, owner_id: str) -> set[str]:
        owner_scope = self._owner_scope(owner_id)
        artifact_ids: set[str] = set()
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT output_artifact_id FROM stage_commits
                WHERE owner_scope = ? AND output_artifact_id IS NOT NULL
                    AND status IN ('committed', 'reused')
                """,
                (owner_scope,),
            ).fetchall()
            artifact_ids.update(str(row[0]) for row in rows)
            pointer_rows = connection.execute(
                """
                SELECT artifact_ref_json FROM pointers
                WHERE owner_scope = ?
                """,
                (owner_scope,),
            ).fetchall()
            artifact_ids.update(
                ArtifactRef.model_validate_json(row[0]).artifact_id
                for row in pointer_rows
            )
            release_rows = connection.execute(
                """
                SELECT DISTINCT release_id
                FROM release_events
                WHERE owner_scope = ?
                ORDER BY release_id
                """,
                (owner_scope,),
            ).fetchall()
            for row in release_rows:
                events = self._load_release_events_in_connection(
                    connection,
                    owner_id=owner_id,
                    owner_scope=owner_scope,
                    release_id=str(row["release_id"]),
                )
                artifact_ids.update(
                    pointer.artifact_ref.artifact_id
                    for event in events
                    for pointer in (
                        event.pointer_before,
                        event.pointer_after,
                    )
                    if pointer is not None
                )
            attestation_rows = connection.execute(
                """
                SELECT artifact_id FROM quality_attestations
                WHERE owner_scope = ?
                """,
                (owner_scope,),
            ).fetchall()
            artifact_ids.update(str(row[0]) for row in attestation_rows)
            manifest_rows = connection.execute(
                """
                SELECT manifest_json FROM runs
                WHERE owner_scope = ?
                """,
                (owner_scope,),
            ).fetchall()
            for row in manifest_rows:
                manifest = RunManifest.model_validate_json(
                    row["manifest_json"]
                )
                artifact_ids.update(
                    ref.artifact_id
                    for stage in manifest.observed.stages
                    for ref in stage.artifact_refs
                )
        return artifact_ids

    def find_orphan_artifacts(
        self,
        *,
        owner_id: str,
        artifact_store: LocalArtifactStore,
    ) -> tuple[str, ...]:
        envelopes = artifact_store.list_envelopes(owner_id=owner_id)
        envelope_by_id = {
            envelope.artifact_id: envelope for envelope in envelopes
        }
        stored = set(envelope_by_id)
        referenced = self.referenced_artifact_ids(owner_id=owner_id)
        queue = list(referenced)
        while queue:
            artifact_id = queue.pop()
            envelope = envelope_by_id.get(artifact_id)
            if envelope is None:
                continue
            linked = {
                ref.artifact_id for ref in envelope.input_refs
            }
            if envelope.supersedes is not None:
                linked.add(envelope.supersedes.artifact_id)
            for linked_id in linked - referenced:
                referenced.add(linked_id)
                queue.append(linked_id)
        return tuple(
            sorted(stored - referenced)
        )
