from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.architecture_schemas import MindMapResult
from backend.vnext.adapters import (
    LegacyAdaptationBlocked,
    to_legacy_result,
)
from backend.vnext.artifacts.local_store import LocalArtifactStore
from backend.vnext.orchestration.shadow_pipeline import run_shadow_pipeline
from backend.vnext.projection import build_diagnostic_projection


VALID_SOURCE = (
    "# Carbonyl Chemistry\n"
    "## Foundations\n"
    "Aldehydes are terminal carbonyl compounds.\n"
    "## Applications\n"
    "Ketones are used in synthesis.\n"
)


class VNextLegacyAdapterTests(unittest.TestCase):
    def test_publishable_projection_downconverts_one_way(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "course.md"
            source_path.write_text(VALID_SOURCE, encoding="utf-8")
            store = LocalArtifactStore(root / "artifacts")
            result = run_shadow_pipeline(
                source_path,
                owner_id="owner-a",
                store=store,
            )

            legacy = to_legacy_result(
                task_id="legacy-task-1",
                run_id=f"run_{'1' * 32}",
                graph_version=1,
                filename=source_path.name,
                file_type="md",
                source=result.source.source_observation,
                inventory=result.source.source_inventory,
                claims=result.claim_ledger,
                omission_audit=result.omission_audit,
                graph=result.canonical_graph,
                projection=result.projection,
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
            result = run_shadow_pipeline(
                source_path,
                owner_id="owner-a",
                store=LocalArtifactStore(root / "artifacts"),
            )

            with self.assertRaisesRegex(
                LegacyAdaptationBlocked,
                "quality-passed",
            ):
                to_legacy_result(
                    task_id="legacy-task-2",
                    run_id=f"run_{'2' * 32}",
                    graph_version=1,
                    filename=source_path.name,
                    file_type="md",
                    source=result.source.source_observation,
                    inventory=result.source.source_inventory,
                    claims=result.claim_ledger,
                    omission_audit=result.omission_audit,
                    graph=result.canonical_graph,
                    projection=result.projection,
                )

    def test_budget_aggregation_cannot_silently_drop_accepted_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "course.md"
            source_path.write_text(VALID_SOURCE, encoding="utf-8")
            store = LocalArtifactStore(root / "artifacts")
            result = run_shadow_pipeline(
                source_path,
                owner_id="owner-a",
                store=store,
            )
            compact = build_diagnostic_projection(
                result.canonical_graph,
                canonical_graph_ref=store.ref(
                    result.canonical_graph_envelope
                ),
                node_budget=2,
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
                    source=result.source.source_observation,
                    inventory=result.source.source_inventory,
                    claims=result.claim_ledger,
                    omission_audit=result.omission_audit,
                    graph=result.canonical_graph,
                    projection=compact,
                )


if __name__ == "__main__":
    unittest.main()
