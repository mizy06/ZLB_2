from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from backend.vnext.artifacts.local_store import LocalArtifactStore
from backend.vnext.claims import (
    atomize_source_claims,
    audit_claim_omissions,
)
from backend.vnext.cli import main
from backend.vnext.contracts.common import (
    ArtifactProducerRef,
    RuntimeRole,
)
from backend.vnext.contracts.projection import ProjectionQualityStatus
from backend.vnext.orchestration.shadow_pipeline import run_shadow_pipeline
from backend.vnext.orchestration.source_shadow import run_source_shadow
from backend.vnext.regions import (
    audit_regions_bottom_up,
    plan_explicit_regions,
)


class VNextShadowSupervisorTests(unittest.TestCase):
    def test_supervisor_archives_complete_explicit_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "course.md"
            source_path.write_text(
                "# Course\n"
                "## Concepts\n"
                "Aldehydes are terminal carbonyl compounds.\n"
                "## Uses\n"
                "Ketones are used in synthesis.\n",
                encoding="utf-8",
            )
            store = LocalArtifactStore(root / "shadow")

            result = run_shadow_pipeline(
                source_path,
                owner_id="tenant-a",
                store=store,
            )

            self.assertEqual(result.replan_requests, ())
            self.assertEqual(
                result.projection.quality_status,
                ProjectionQualityStatus.PASSED,
            )
            for envelope in (
                result.source.source_envelope,
                result.source.inventory_envelope,
                *result.planning.final_plan_envelopes,
                *result.planning.split_certificate_envelopes,
                result.claim_ledger_envelope,
                result.omission_audit_envelope,
                result.canonical_graph_envelope,
                result.projection_envelope,
            ):
                loaded = store.get(
                    owner_id="tenant-a",
                    artifact_id=envelope.artifact_id,
                )
                self.assertEqual(
                    loaded.envelope.payload_digest,
                    envelope.payload_digest,
                )

    def test_bottom_up_auditor_emits_request_without_mutating_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "course.md"
            source_path.write_text(
                "# Course\n"
                "## Concepts\n"
                "Aldehydes are terminal carbonyl compounds.\n"
                "## Uses\n"
                "Ketones are used in synthesis.\n",
                encoding="utf-8",
            )
            store = LocalArtifactStore(root / "shadow")
            source = run_source_shadow(
                source_path,
                owner_id="tenant-a",
                store=store,
            )
            source_ref = store.ref(source.source_envelope)
            inventory_ref = store.ref(source.inventory_envelope)
            planning = plan_explicit_regions(
                source.source_observation,
                source.source_inventory,
                owner_id="tenant-a",
                source_ref=source_ref,
                inventory_ref=inventory_ref,
                store=store,
            )
            fact_id = next(
                entry.source_id
                for entry in source.source_inventory.block_entries
                if "Aldehydes" in next(
                    block.text
                    for page in source.source_observation.pages
                    for block in page.blocks
                    if block.block_id == entry.source_id
                )
            )
            mapping = dict(planning.source_to_leaf_region)
            mapping.pop(fact_id)
            ledger = atomize_source_claims(
                source.source_observation,
                document_ir_ref=source_ref,
                region_plan_refs=planning.accepted_plan_refs,
                source_to_leaf_region=mapping,
            )
            ledger_envelope = store.put(
                owner_id="tenant-a",
                role=RuntimeRole.CLAIM_ATOMIZER,
                payload=ledger,
                producer=ArtifactProducerRef(
                    producer_id="vnext-source-claim-atomizer",
                    producer_version="1.0.0",
                    role=RuntimeRole.CLAIM_ATOMIZER,
                ),
                input_refs=(source_ref, *planning.accepted_plan_refs),
            )
            audit = audit_claim_omissions(
                source.source_inventory,
                ledger,
                source_inventory_ref=inventory_ref,
                claim_ledger_ref=store.ref(ledger_envelope),
                structurally_accounted_source_ids=(
                    planning.structurally_accounted_source_ids
                ),
                forced_unresolved_source_ids=(
                    planning.unresolved_source_ids
                ),
            )
            before = planning.final_plans

            requests = audit_regions_bottom_up(
                planning,
                source.source_inventory,
                audit,
            )

            self.assertEqual(planning.final_plans, before)
            self.assertEqual(len(requests), 1)
            self.assertIn(fact_id, requests[0].omitted_source_ids)
            self.assertEqual(
                requests[0].minimum_replan_ancestor_id,
                requests[0].affected_region_id,
            )

    def test_unresolved_document_produces_blocked_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "course.md"
            source_path.write_text(
                "## First topic\nA fact.\n"
                "## Second topic\nAnother fact.\n",
                encoding="utf-8",
            )

            result = run_shadow_pipeline(
                source_path,
                owner_id="tenant-a",
                store=LocalArtifactStore(root / "shadow"),
            )

            self.assertEqual(result.planning.accepted_plan_refs, ())
            self.assertEqual(
                result.projection.quality_status,
                ProjectionQualityStatus.BLOCKED_SEMANTIC,
            )
            self.assertTrue(
                any(
                    item.severity == "blocking"
                    for item in result.projection.diagnostics
                )
            )

    def test_pipeline_shadow_cli_reports_artifact_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "course.md"
            source_path.write_text(
                "# Course\n"
                "## Concepts\nA fact.\n"
                "## Uses\nAnother fact.\n",
                encoding="utf-8",
            )
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(
                    [
                        "pipeline-shadow",
                        "--input",
                        str(source_path),
                        "--owner",
                        "tenant-a",
                        "--root",
                        str(root / "shadow"),
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["quality_status"], "passed")
            self.assertRegex(
                payload["canonical_graph_artifact_id"],
                r"^art_[0-9a-f]{32}$",
            )
            self.assertRegex(
                payload["projection_artifact_id"],
                r"^art_[0-9a-f]{32}$",
            )


if __name__ == "__main__":
    unittest.main()
