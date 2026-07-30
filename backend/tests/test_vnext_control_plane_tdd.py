from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from backend.vnext.artifacts.local_store import LocalArtifactStore
from backend.vnext.contracts.common import (
    ArtifactProducerRef,
    RuntimeRole,
    StringValue,
)
from backend.vnext.contracts.control import (
    DeclaredRunManifest,
    EvidenceMode,
    ExecutionStatus,
    PublicationStatus,
    QualityAttestation,
    QualityGateDecision,
    QualityMetric,
    QualityStatus,
    RunBudget,
    RunManifest,
    RunProfile,
    StageCommit,
    StageCommitStatus,
)
from backend.vnext.orchestration.control_store import (
    CompareAndSwapConflict,
    ControlPlaneError,
    LeaseConflict,
    SQLiteControlStore,
    next_manifest_revision,
    ordered_stage_input_digest,
    stage_idempotency_key,
)
from backend.vnext.source_ir import parse_source

from backend.tests.vnext_test_support import digest


def _manifest(
    *,
    source_hash: str,
    run_digit: str = "1",
    owner_id: str = "tenant-a",
    now: datetime,
) -> RunManifest:
    return RunManifest(
        manifest_id=f"run_manifest_{run_digit * 32}",
        run_id=f"run_{run_digit * 32}",
        revision=1,
        owner_id=owner_id,
        declared=DeclaredRunManifest(
            source_hash=source_hash,
            profile=RunProfile.STANDARD,
            evidence_mode=EvidenceMode.SOURCE_ONLY,
            no_egress=True,
            budget=RunBudget(
                max_wall_seconds=600,
                max_model_calls=0,
                max_search_queries=0,
                max_search_fetches=0,
                max_cost_microunits=0,
                vlm_concurrency=0,
                text_concurrency=1,
                search_concurrency=0,
            ),
            code_revision="test-revision",
            dependency_digest=digest("1"),
            parser_policy_digest=digest("2"),
            renderer_policy_digest=digest("3"),
            prompt_policy_digest=digest("4"),
            tool_policy_digest=digest("5"),
            search_policy_digest=digest("6"),
            schema_digests=(
                StringValue(
                    key="source_observation_ir",
                    value=digest("7"),
                ),
            ),
            random_seed=0,
        ),
        created_at=now,
        updated_at=now,
    )


def _source_artifact(
    root: Path,
    *,
    owner_id: str = "tenant-a",
    suffix: str = "",
):
    source_path = root / f"course{suffix}.md"
    source_path.write_text(
        f"# Course {suffix}\nA fact {suffix}.\n",
        encoding="utf-8",
    )
    source = parse_source(source_path)
    artifact_store = LocalArtifactStore(root / "artifacts")
    envelope = artifact_store.put(
        owner_id=owner_id,
        role=RuntimeRole.DOCUMENT_INTERPRETER,
        payload=source,
        producer=ArtifactProducerRef(
            producer_id="vnext-source-observer",
            producer_version="1.0.0",
            role=RuntimeRole.DOCUMENT_INTERPRETER,
        ),
    )
    return source, artifact_store, envelope


def _stage_commit(
    *,
    manifest: RunManifest,
    stage_key: str,
    output_ref,
    lease_epoch: int,
    now: datetime,
    idempotency_key: str | None = None,
) -> StageCommit:
    policy_digest = digest("8")
    return StageCommit(
        run_id=manifest.run_id,
        owner_id=manifest.owner_id,
        stage_key=stage_key,
        idempotency_key=(
            idempotency_key
            or stage_idempotency_key(
                owner_id=manifest.owner_id,
                stage_contract_major=1,
                ordered_input_digests=(),
                policy_digests=(policy_digest,),
            )
        ),
        input_digest=ordered_stage_input_digest(()),
        policy_digest=policy_digest,
        output_ref=output_ref,
        attempt=1,
        lease_epoch=lease_epoch,
        status=StageCommitStatus.COMMITTED,
        created_at=now,
        updated_at=now,
    )


class VNextControlContractTests(unittest.TestCase):
    def test_execution_quality_and_publication_are_orthogonal(self):
        now = datetime(2026, 7, 29, tzinfo=UTC)
        manifest = _manifest(source_hash=digest("a"), now=now)
        payload = manifest.model_dump(mode="python")
        payload.update(
            {
                "execution_status": ExecutionStatus.SUCCEEDED,
                "quality_status": QualityStatus.BLOCKED_SEMANTIC,
                "publication_status": PublicationStatus.PUBLISHED,
            }
        )

        with self.assertRaisesRegex(
            ValidationError,
            "passed quality",
        ):
            RunManifest.model_validate(payload)

    def test_source_only_manifest_cannot_enable_egress(self):
        now = datetime(2026, 7, 29, tzinfo=UTC)
        manifest = _manifest(source_hash=digest("a"), now=now)
        declared = manifest.declared.model_dump(mode="python")
        declared["no_egress"] = False

        with self.assertRaisesRegex(ValidationError, "no_egress"):
            DeclaredRunManifest.model_validate(declared)


class VNextSQLiteControlPlaneTests(unittest.TestCase):
    def test_manifest_compare_and_swap_rejects_stale_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime(2026, 7, 29, tzinfo=UTC)
            control = SQLiteControlStore(Path(tmp) / "control.sqlite3")
            manifest = _manifest(source_hash=digest("a"), now=now)
            control.create_run(manifest)
            running = next_manifest_revision(
                manifest,
                execution_status=ExecutionStatus.RUNNING,
                now=now + timedelta(seconds=1),
            )
            control.compare_and_swap_manifest(
                running,
                expected_revision=1,
            )

            with self.assertRaisesRegex(
                CompareAndSwapConflict,
                "stale",
            ):
                control.compare_and_swap_manifest(
                    next_manifest_revision(
                        manifest,
                        execution_status=ExecutionStatus.CANCELLED,
                        now=now + timedelta(seconds=2),
                    ),
                    expected_revision=1,
                )

            loaded = control.load_run(
                manifest.run_id,
                owner_id=manifest.owner_id,
            )
            self.assertEqual(loaded, running)

    def test_expired_lease_fences_stale_worker_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, artifact_store, envelope = _source_artifact(root)
            output_ref = artifact_store.ref(envelope)
            now = datetime(2026, 7, 29, tzinfo=UTC)
            manifest = _manifest(source_hash=source.source_hash, now=now)
            control = SQLiteControlStore(root / "control.sqlite3")
            control.create_run(manifest)
            first = control.acquire_stage_lease(
                run_id=manifest.run_id,
                stage_key="source-observation",
                worker_id="worker-a",
                ttl_seconds=10,
                now=now,
            )
            with self.assertRaises(LeaseConflict):
                control.acquire_stage_lease(
                    run_id=manifest.run_id,
                    stage_key="source-observation",
                    worker_id="worker-b",
                    ttl_seconds=10,
                    now=now + timedelta(seconds=1),
                )
            second = control.acquire_stage_lease(
                run_id=manifest.run_id,
                stage_key="source-observation",
                worker_id="worker-b",
                ttl_seconds=10,
                now=now + timedelta(seconds=11),
            )
            self.assertEqual(second.lease_epoch, first.lease_epoch + 1)

            with self.assertRaisesRegex(
                CompareAndSwapConflict,
                "stale",
            ):
                control.commit_stage(
                    _stage_commit(
                        manifest=manifest,
                        stage_key="source-observation",
                        output_ref=output_ref,
                        lease_epoch=first.lease_epoch,
                        now=now + timedelta(seconds=11),
                    ),
                    worker_id="worker-a",
                    now=now + timedelta(seconds=11),
                )

            committed = control.commit_stage(
                _stage_commit(
                    manifest=manifest,
                    stage_key="source-observation",
                    output_ref=output_ref,
                    lease_epoch=second.lease_epoch,
                    now=now + timedelta(seconds=11),
                ),
                worker_id="worker-b",
                now=now + timedelta(seconds=11),
            )
            self.assertEqual(
                committed.status,
                StageCommitStatus.COMMITTED,
            )

    def test_idempotency_accepts_one_output_and_supports_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_source, artifact_store, first_envelope = _source_artifact(
                root,
                suffix="-a",
            )
            _, _, second_envelope = _source_artifact(root, suffix="-b")
            now = datetime(2026, 7, 29, tzinfo=UTC)
            first_manifest = _manifest(
                source_hash=first_source.source_hash,
                run_digit="1",
                now=now,
            )
            second_manifest = _manifest(
                source_hash=first_source.source_hash,
                run_digit="2",
                now=now,
            )
            control = SQLiteControlStore(root / "control.sqlite3")
            control.create_run(first_manifest)
            control.create_run(second_manifest)
            lease = control.acquire_stage_lease(
                run_id=first_manifest.run_id,
                stage_key="source-observation",
                worker_id="worker-a",
                ttl_seconds=30,
                now=now,
            )
            key = stage_idempotency_key(
                owner_id="tenant-a",
                stage_contract_major=1,
                ordered_input_digests=(),
                policy_digests=(digest("8"),),
            )
            committed = control.commit_stage(
                _stage_commit(
                    manifest=first_manifest,
                    stage_key="source-observation",
                    output_ref=artifact_store.ref(first_envelope),
                    lease_epoch=lease.lease_epoch,
                    now=now,
                    idempotency_key=key,
                ),
                worker_id="worker-a",
                now=now,
            )
            reusable = control.find_committed_stage(
                owner_id="tenant-a",
                idempotency_key=key,
            )
            self.assertEqual(reusable, committed)
            reused = control.record_stage_reuse(
                run_id=second_manifest.run_id,
                stage_key="source-observation",
                attempt=1,
                committed=committed,
                now=now + timedelta(seconds=1),
            )
            self.assertEqual(reused.status, StageCommitStatus.REUSED)
            self.assertEqual(reused.output_ref, committed.output_ref)

            second_lease = control.acquire_stage_lease(
                run_id=second_manifest.run_id,
                stage_key="source-observation-conflict",
                worker_id="worker-b",
                ttl_seconds=30,
                now=now,
            )
            with self.assertRaisesRegex(
                CompareAndSwapConflict,
                "another output",
            ):
                control.commit_stage(
                    _stage_commit(
                        manifest=second_manifest,
                        stage_key="source-observation-conflict",
                        output_ref=artifact_store.ref(second_envelope),
                        lease_epoch=second_lease.lease_epoch,
                        now=now,
                        idempotency_key=key,
                    ),
                    worker_id="worker-b",
                    now=now,
                )

    def test_outbox_pointer_quality_gate_and_orphan_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, artifact_store, committed_envelope = _source_artifact(
                root,
                suffix="-committed",
            )
            _, _, orphan_envelope = _source_artifact(
                root,
                suffix="-orphan",
            )
            now = datetime(2026, 7, 29, tzinfo=UTC)
            manifest = _manifest(source_hash=source.source_hash, now=now)
            control = SQLiteControlStore(root / "control.sqlite3")
            control.create_run(manifest)
            lease = control.acquire_stage_lease(
                run_id=manifest.run_id,
                stage_key="source-observation",
                worker_id="worker-a",
                ttl_seconds=30,
                now=now,
            )
            commit = control.commit_stage(
                _stage_commit(
                    manifest=manifest,
                    stage_key="source-observation",
                    output_ref=artifact_store.ref(committed_envelope),
                    lease_epoch=lease.lease_epoch,
                    now=now,
                ),
                worker_id="worker-a",
                now=now,
            )
            outbox = control.claim_outbox(worker_id="publisher")
            self.assertEqual(len(outbox), 1)
            self.assertEqual(outbox[0].output_ref, commit.output_ref)
            control.acknowledge_outbox(
                outbox[0].outbox_id,
                worker_id="publisher",
            )
            self.assertEqual(
                control.claim_outbox(worker_id="publisher"),
                (),
            )
            self.assertEqual(
                control.find_orphan_artifacts(
                    owner_id="tenant-a",
                    artifact_store=artifact_store,
                ),
                (orphan_envelope.artifact_id,),
            )

            with self.assertRaises(ControlPlaneError):
                control.publish_pointer(
                    manifest,
                    pointer_key="public-projection",
                    artifact_ref=commit.output_ref,
                    expected_version=None,
                )
            release = next_manifest_revision(
                manifest,
                execution_status=ExecutionStatus.SUCCEEDED,
                quality_status=QualityStatus.PASSED,
                publication_status=PublicationStatus.RELEASE_CANDIDATE,
                now=now + timedelta(seconds=1),
            )
            pointer = control.publish_pointer(
                release,
                pointer_key="public-projection",
                artifact_ref=commit.output_ref,
                expected_version=None,
            )
            self.assertEqual(pointer.version, 1)
            with self.assertRaises(CompareAndSwapConflict):
                control.compare_and_swap_pointer(
                    owner_id="tenant-a",
                    pointer_key="public-projection",
                    artifact_ref=commit.output_ref,
                    expected_version=0,
                )

            attestation = QualityAttestation(
                attestation_id=f"attestation_{'1' * 32}",
                owner_id="tenant-a",
                artifact_ref=commit.output_ref,
                evaluator=ArtifactProducerRef(
                    producer_id="vnext-quality-auditor",
                    producer_version="1.0.0",
                    role=RuntimeRole.QUALITY_AUDITOR,
                ),
                policy_digest=digest("9"),
                closure_digest=digest("a"),
                evaluator_build_digest=digest("b"),
                metrics=(
                    QualityMetric(
                        name="topology_valid",
                        value=1,
                        threshold=1,
                        passed=True,
                    ),
                ),
                gate_decision=QualityGateDecision.PASS,
                created_at=now,
            )
            control.record_quality_attestation(attestation)


if __name__ == "__main__":
    unittest.main()
