from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from backend.app.architecture_schemas import MindMapResult
from backend.vnext.adapters import (
    LegacyAdaptationBlocked,
    to_legacy_result,
)
from backend.vnext.artifacts.canonical import payload_digest
from backend.vnext.artifacts.local_store import LocalArtifactStore
from backend.vnext.contracts.common import ArtifactProducerRef, RuntimeRole
from backend.vnext.contracts.control import (
    PublicationStatus,
    QualityAttestation,
    QualityGateDecision,
    QualityMetric,
)
from backend.vnext.orchestration.control_store import (
    SQLiteControlStore,
    next_manifest_revision,
)
from backend.vnext.orchestration.durable_pipeline import (
    run_durable_shadow_pipeline,
)
from backend.vnext.orchestration.release import PUBLISHED_POINTER_KEY
from backend.vnext.projection import build_diagnostic_projection

from backend.tests.vnext_test_support import digest


VALID_SOURCE = (
    "# Carbonyl Chemistry\n"
    "## Foundations\n"
    "Aldehydes are terminal carbonyl compounds.\n"
    "## Applications\n"
    "Ketones are used in synthesis.\n"
)


def _published_candidate(
    root: Path,
    *,
    source_text: str = VALID_SOURCE,
    run_digit: str = "1",
):
    source_path = root / f"course-{run_digit}.md"
    source_path.write_text(source_text, encoding="utf-8")
    artifacts = LocalArtifactStore(root / f"artifacts-{run_digit}")
    control = SQLiteControlStore(root / f"control-{run_digit}.sqlite3")
    result = run_durable_shadow_pipeline(
        source_path,
        owner_id="owner-a",
        artifact_store=artifacts,
        control_store=control,
        worker_id=f"legacy-test-{run_digit}",
        run_id=f"run_{run_digit * 32}",
    )
    published = next_manifest_revision(
        result.run_manifest,
        publication_status=PublicationStatus.PUBLISHED,
    )
    control.compare_and_swap_manifest(
        published,
        expected_revision=result.run_manifest.revision,
    )
    projection_ref = artifacts.ref(result.shadow.projection_envelope)
    control.publish_pointer(
        published,
        pointer_key=PUBLISHED_POINTER_KEY,
        artifact_ref=projection_ref,
        expected_version=None,
    )
    return source_path, artifacts, control, result, published


class VNextLegacyAdapterTests(unittest.TestCase):
    def test_publishable_projection_downconverts_one_way(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (
                source_path,
                _artifacts,
                control,
                result,
                published,
            ) = _published_candidate(
                root,
            )

            legacy = to_legacy_result(
                task_id="legacy-task-1",
                run_id=result.run_manifest.run_id,
                graph_version=1,
                filename=source_path.name,
                file_type="md",
                source=result.shadow.source.source_observation,
                inventory=result.shadow.source.source_inventory,
                claims=result.shadow.claim_ledger,
                omission_audit=result.shadow.omission_audit,
                graph=result.shadow.canonical_graph,
                projection=result.shadow.projection,
                owner_id="owner-a",
                control_store=control,
                run_manifest=published,
            )

            MindMapResult.model_validate(legacy.model_dump(mode="json"))
            self.assertEqual(
                len(legacy.tree_edges),
                len(legacy.nodes) - 1,
            )
            self.assertTrue(legacy.quality_report.publish_gate_passed)
            self.assertTrue(legacy.quality_report.quality_gate_passed)
            self.assertTrue(
                all(not edge.provisional for edge in legacy.tree_edges)
            )
            self.assertEqual(legacy.solver_status, "VNEXT_PROJECTION")
            self.assertTrue(
                legacy.run_manifest["legacy_adapter"]["lossy"]
            )
            self.assertEqual(
                legacy.run_manifest["legacy_adapter"]["round_trip"],
                "forbidden",
            )
            self.assertTrue(
                any(
                    "round-trip" in warning
                    for warning in legacy.warnings
                )
            )

    def test_quality_blocked_projection_cannot_become_legacy_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "course.md"
            source_path.write_text(
                "## First\nA fact.\n## Second\nAnother fact.\n",
                encoding="utf-8",
            )
            artifacts = LocalArtifactStore(root / "artifacts")
            control = SQLiteControlStore(root / "control.sqlite3")
            result = run_durable_shadow_pipeline(
                source_path,
                owner_id="owner-a",
                artifact_store=artifacts,
                control_store=control,
                worker_id="legacy-blocked",
                run_id=f"run_{'2' * 32}",
            )

            with self.assertRaisesRegex(
                LegacyAdaptationBlocked,
                "published pointer",
            ):
                to_legacy_result(
                    task_id="legacy-task-2",
                    run_id=f"run_{'2' * 32}",
                    graph_version=1,
                    filename=source_path.name,
                    file_type="md",
                    source=result.shadow.source.source_observation,
                    inventory=result.shadow.source.source_inventory,
                    claims=result.shadow.claim_ledger,
                    omission_audit=result.shadow.omission_audit,
                    graph=result.shadow.canonical_graph,
                    projection=result.shadow.projection,
                    owner_id="owner-a",
                    control_store=control,
                )

    def test_budget_aggregation_cannot_silently_drop_accepted_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (
                source_path,
                store,
                control,
                result,
                published,
            ) = _published_candidate(
                root,
                run_digit="3",
            )
            compact = build_diagnostic_projection(
                result.shadow.canonical_graph,
                canonical_graph_ref=store.ref(
                    result.shadow.canonical_graph_envelope
                ),
                node_budget=2,
            )
            compact_envelope = store.put(
                owner_id="owner-a",
                role=RuntimeRole.PROJECTION_PLANNER,
                payload=compact,
                producer=ArtifactProducerRef(
                    producer_id="legacy-test-compact-projection",
                    producer_version="1.0.0",
                    role=RuntimeRole.PROJECTION_PLANNER,
                ),
                input_refs=(
                    store.ref(result.shadow.canonical_graph_envelope),
                ),
            )
            compact_ref = store.ref(compact_envelope)
            control.record_quality_attestation(
                QualityAttestation(
                    attestation_id=f"attestation_{'4' * 32}",
                    owner_id="owner-a",
                    artifact_ref=compact_ref,
                    evaluator=ArtifactProducerRef(
                        producer_id="legacy-test-quality-auditor",
                        producer_version="1.0.0",
                        role=RuntimeRole.QUALITY_AUDITOR,
                    ),
                    policy_digest=digest("4"),
                    closure_digest=payload_digest(
                        {"projection": compact_ref.payload_digest}
                    ),
                    evaluator_build_digest=digest("5"),
                    metrics=(
                        QualityMetric(
                            name="structural_integrity",
                            value=1,
                            threshold=1,
                            passed=True,
                        ),
                    ),
                    gate_decision=QualityGateDecision.PASS,
                    created_at=datetime(2026, 7, 30, tzinfo=UTC),
                )
            )
            current_pointer = control.load_pointer(
                owner_id="owner-a",
                pointer_key=PUBLISHED_POINTER_KEY,
            )
            assert current_pointer is not None
            control.publish_pointer(
                published,
                pointer_key=PUBLISHED_POINTER_KEY,
                artifact_ref=compact_ref,
                expected_version=current_pointer.version,
            )

            with self.assertRaisesRegex(
                LegacyAdaptationBlocked,
                "aggregation",
            ):
                to_legacy_result(
                    task_id="legacy-task-3",
                    run_id=f"run_{'3' * 32}",
                    graph_version=1,
                    filename=source_path.name,
                    file_type="md",
                    source=result.shadow.source.source_observation,
                    inventory=result.shadow.source.source_inventory,
                    claims=result.shadow.claim_ledger,
                    omission_audit=result.shadow.omission_audit,
                    graph=result.shadow.canonical_graph,
                    projection=compact,
                    owner_id="owner-a",
                    control_store=control,
                    run_manifest=published,
                )


if __name__ == "__main__":
    unittest.main()
