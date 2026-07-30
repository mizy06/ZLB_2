from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.vnext.artifacts.local_store import LocalArtifactStore
from backend.vnext.contracts.regions import (
    RegionPlanStatus,
    RegionProposalAction,
    SplitDecision,
)
from backend.vnext.orchestration.source_shadow import run_source_shadow
from backend.vnext.regions.planner import plan_explicit_regions


class VNextExplicitRegionPlannerTests(unittest.TestCase):
    def test_explicit_outline_builds_verified_top_down_region_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "course.md"
            source_path.write_text(
                "# Carbonyl Chemistry\n"
                "## Foundations\n"
                "Aldehydes are carbonyl compounds.\n"
                "## Applications\n"
                "Ketones are used in synthesis.\n",
                encoding="utf-8",
            )
            store = LocalArtifactStore(root / "shadow")
            source_result = run_source_shadow(
                source_path,
                owner_id="tenant-a",
                store=store,
            )

            result = plan_explicit_regions(
                source_result.source_observation,
                source_result.source_inventory,
                owner_id="tenant-a",
                source_ref=store.ref(source_result.source_envelope),
                inventory_ref=store.ref(source_result.inventory_envelope),
                store=store,
            )

            self.assertEqual(len(result.final_plans), 3)
            root_plan = next(
                plan
                for plan in result.final_plans
                if plan.parent_region_id is None
            )
            self.assertEqual(root_plan.status, RegionPlanStatus.ACCEPTED)
            self.assertEqual(
                root_plan.proposed_action,
                RegionProposalAction.SPLIT,
            )
            self.assertEqual(len(root_plan.child_region_ids), 2)
            child_plans = [
                plan
                for plan in result.final_plans
                if plan.parent_region_id == root_plan.region_id
            ]
            self.assertEqual(len(child_plans), 2)
            self.assertTrue(
                all(
                    plan.status is RegionPlanStatus.ACCEPTED
                    and plan.proposed_action is RegionProposalAction.STOP
                    and plan.ancestor_path == (root_plan.region_id,)
                    for plan in child_plans
                )
            )
            self.assertEqual(len(result.split_certificates), 1)
            certificate = result.split_certificates[0]
            self.assertEqual(
                certificate.decision,
                SplitDecision.ACCEPT_SPLIT,
            )
            self.assertFalse(
                certificate.uses_capacity_as_semantic_evidence
            )
            inventory_ids = {
                entry.source_id
                for entry in source_result.source_inventory.all_entries()
            }
            self.assertEqual(
                {
                    item.source_id
                    for item in certificate.source_assignment_map
                },
                inventory_ids,
            )
            leaf_ids = {plan.region_id for plan in child_plans}
            self.assertTrue(result.source_to_leaf_region)
            self.assertTrue(
                set(result.source_to_leaf_region.values()) <= leaf_ids
            )

    def test_missing_unique_explicit_root_stays_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "course.md"
            source_path.write_text(
                "## Foundations\n"
                "A fact.\n"
                "## Applications\n"
                "Another fact.\n",
                encoding="utf-8",
            )
            store = LocalArtifactStore(root / "shadow")
            source_result = run_source_shadow(
                source_path,
                owner_id="tenant-a",
                store=store,
            )

            result = plan_explicit_regions(
                source_result.source_observation,
                source_result.source_inventory,
                owner_id="tenant-a",
                source_ref=store.ref(source_result.source_envelope),
                inventory_ref=store.ref(source_result.inventory_envelope),
                store=store,
            )

            self.assertEqual(len(result.final_plans), 1)
            self.assertEqual(
                result.final_plans[0].status,
                RegionPlanStatus.UNRESOLVED,
            )
            self.assertEqual(result.accepted_plan_refs, ())
            self.assertEqual(result.source_to_leaf_region, {})
            self.assertEqual(
                set(result.unresolved_source_ids),
                {
                    entry.source_id
                    for entry in (
                        source_result.source_inventory.all_entries()
                    )
                },
            )

    def test_fragmentary_child_label_rejects_split_without_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "course.md"
            source_path.write_text(
                "# Carbonyl Chemistry\n"
                "## and\n"
                "A fact.\n"
                "## Applications\n"
                "Another fact.\n",
                encoding="utf-8",
            )
            store = LocalArtifactStore(root / "shadow")
            source_result = run_source_shadow(
                source_path,
                owner_id="tenant-a",
                store=store,
            )

            result = plan_explicit_regions(
                source_result.source_observation,
                source_result.source_inventory,
                owner_id="tenant-a",
                source_ref=store.ref(source_result.source_envelope),
                inventory_ref=store.ref(source_result.inventory_envelope),
                store=store,
            )

            self.assertEqual(len(result.split_certificates), 1)
            self.assertEqual(
                result.split_certificates[0].decision,
                SplitDecision.REJECT_SPLIT,
            )
            self.assertEqual(len(result.final_plans), 1)
            self.assertEqual(
                result.final_plans[0].status,
                RegionPlanStatus.UNRESOLVED,
            )
            self.assertFalse(result.source_to_leaf_region)


if __name__ == "__main__":
    unittest.main()
