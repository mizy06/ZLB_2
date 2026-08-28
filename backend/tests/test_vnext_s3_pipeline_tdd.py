from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.vnext.artifacts.canonical import payload_digest
from backend.vnext.artifacts.local_store import LocalArtifactStore
from backend.vnext.canonical_graph import (
    build_canonical_explicit_graph,
    build_relation_assessment_ledger,
    build_relation_proposal_ledger,
)
from backend.vnext.claims import (
    atomize_source_claims,
    audit_claim_omissions,
    evaluate_omission_audit,
)
from backend.vnext.contracts.common import (
    ArtifactProducerRef,
    ArtifactRef,
    ArtifactType,
    RuntimeRole,
)
from backend.vnext.contracts.graph import (
    CanonicalStatus,
    GraphAuditItem,
    HierarchyDirectness,
)
from backend.vnext.contracts.projection import (
    ProjectionQualityStatus,
)
from backend.vnext.orchestration.source_shadow import run_source_shadow
from backend.vnext.projection import build_diagnostic_projection
from backend.vnext.regions import plan_explicit_regions

from backend.tests.vnext_test_support import (
    accepted_concept,
    accepted_relation,
    artifact_id,
    graph as graph_fixture,
)


def _producer(
    producer_id: str,
    role: RuntimeRole,
) -> ArtifactProducerRef:
    return ArtifactProducerRef(
        producer_id=producer_id,
        producer_version="1.0.0",
        role=role,
    )


class VNextS3PipelineTests(unittest.TestCase):
    def test_explicit_shadow_pipeline_reaches_valid_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "course.md"
            source_path.write_text(
                "# Carbonyl Chemistry\n"
                "## Foundations\n"
                "Aldehydes are compounds with a terminal carbonyl group.\n"
                "## Applications\n"
                "Ketones are used in organic synthesis.\n",
                encoding="utf-8",
            )
            store = LocalArtifactStore(root / "shadow")
            source_result = run_source_shadow(
                source_path,
                owner_id="tenant-a",
                store=store,
            )
            source_ref = store.ref(source_result.source_envelope)
            inventory_ref = store.ref(source_result.inventory_envelope)
            planning = plan_explicit_regions(
                source_result.source_observation,
                source_result.source_inventory,
                owner_id="tenant-a",
                source_ref=source_ref,
                inventory_ref=inventory_ref,
                store=store,
            )
            ledger = atomize_source_claims(
                source_result.source_observation,
                document_ir_ref=source_ref,
                region_plan_refs=planning.accepted_plan_refs,
                source_to_leaf_region=planning.source_to_leaf_region,
            )
            ledger_envelope = store.put(
                owner_id="tenant-a",
                role=RuntimeRole.CLAIM_ATOMIZER,
                payload=ledger,
                producer=_producer(
                    "vnext-source-claim-atomizer",
                    RuntimeRole.CLAIM_ATOMIZER,
                ),
                input_refs=(source_ref, *planning.accepted_plan_refs),
            )
            ledger_ref = store.ref(ledger_envelope)
            audit = audit_claim_omissions(
                source_result.source_inventory,
                ledger,
                source_inventory_ref=inventory_ref,
                claim_ledger_ref=ledger_ref,
                structurally_accounted_source_ids=(
                    planning.structurally_accounted_source_ids
                ),
                forced_unresolved_source_ids=(
                    planning.unresolved_source_ids
                ),
            )
            audit_envelope = store.put(
                owner_id="tenant-a",
                role=RuntimeRole.OMISSION_AUDITOR,
                payload=audit,
                producer=_producer(
                    "vnext-source-omission-auditor",
                    RuntimeRole.OMISSION_AUDITOR,
                ),
                input_refs=(inventory_ref, ledger_ref),
            )
            audit_ref = store.ref(audit_envelope)

            self.assertTrue(
                evaluate_omission_audit(
                    source_result.source_inventory,
                    audit,
                ).accepted
            )
            proposal_ledger = build_relation_proposal_ledger(
                ledger,
                planning,
                source_observation_ref=source_ref,
                claim_ledger_ref=ledger_ref,
                additional_input_refs=(audit_ref,),
            )
            proposal_envelope = store.put(
                owner_id="tenant-a",
                role=RuntimeRole.RELATION_PROPOSER,
                payload=proposal_ledger,
                producer=_producer(
                    "vnext-explicit-relation-proposer",
                    RuntimeRole.RELATION_PROPOSER,
                ),
                input_refs=(
                    source_ref,
                    ledger_ref,
                    *planning.accepted_plan_refs,
                    audit_ref,
                ),
            )
            proposal_ref = store.ref(proposal_envelope)
            relation_ledger = build_relation_assessment_ledger(
                proposal_ledger,
            )
            relation_envelope = store.put(
                owner_id="tenant-a",
                role=RuntimeRole.RELATION_VERIFIER_A,
                payload=relation_ledger,
                producer=_producer(
                    "vnext-explicit-relation-verifier-a",
                    RuntimeRole.RELATION_VERIFIER_A,
                ),
                input_refs=(proposal_ref,),
            )
            relation_ref = store.ref(relation_envelope)
            canonical = build_canonical_explicit_graph(
                ledger,
                planning,
                source_observation_ref=source_ref,
                claim_ledger_ref=ledger_ref,
                relation_assessment_ledger=relation_ledger,
                additional_input_refs=(audit_ref,),
            )
            canonical_envelope = store.put(
                owner_id="tenant-a",
                role=RuntimeRole.CANONICALIZER,
                payload=canonical,
                producer=_producer(
                    "vnext-explicit-canonicalizer",
                    RuntimeRole.CANONICALIZER,
                ),
                input_refs=(
                    source_ref,
                    ledger_ref,
                    *planning.accepted_plan_refs,
                    audit_ref,
                    proposal_ref,
                    relation_ref,
                ),
            )
            canonical_ref = store.ref(canonical_envelope)
            projection = build_diagnostic_projection(
                canonical,
                canonical_graph_ref=canonical_ref,
            )
            projection_envelope = store.put(
                owner_id="tenant-a",
                role=RuntimeRole.PROJECTION_PLANNER,
                payload=projection,
                producer=_producer(
                    "vnext-diagnostic-projection-planner",
                    RuntimeRole.PROJECTION_PLANNER,
                ),
                input_refs=(canonical_ref,),
            )

            self.assertFalse(canonical.unresolved_items)
            self.assertTrue(canonical.concepts)
            self.assertTrue(canonical.relations)
            self.assertTrue(
                all(
                    relation.status is CanonicalStatus.ACCEPTED
                    and relation.edge_evidence_refs
                    and relation.verifier_decisions
                    and relation.region_plan_ref
                    in canonical.region_plan_refs
                    for relation in canonical.relations
                )
            )
            accepted_ids = {
                concept.concept_id
                for concept in canonical.concepts
                if concept.status is CanonicalStatus.ACCEPTED
            }
            incoming = {
                relation.target_id
                for relation in canonical.relations
                if relation.status is CanonicalStatus.ACCEPTED
                and relation.hierarchy_directness
                is HierarchyDirectness.DIRECT
            }
            self.assertEqual(len(accepted_ids - incoming), 1)
            self.assertEqual(
                projection.quality_status,
                ProjectionQualityStatus.PASSED,
            )
            self.assertEqual(
                len(projection.parent_selections),
                len(accepted_ids) - 1,
            )
            self.assertIsNotNone(projection.projection_hash)
            self.assertEqual(
                projection_envelope.payload_digest,
                payload_digest(projection),
            )

    def test_projection_records_alternate_canonical_parent(self):
        canonical = graph_fixture(
            (
                accepted_concept("1", "Parent A"),
                accepted_concept("2", "Parent B"),
                accepted_concept("3", "Shared child"),
            ),
            (
                accepted_relation("4", "1", "3"),
                accepted_relation("5", "2", "3"),
            ),
        )
        digest = payload_digest(canonical)
        graph_ref = ArtifactRef(
            owner_id="owner-a",
            artifact_id=artifact_id("9"),
            artifact_type=ArtifactType.CANONICAL_EXPLICIT_GRAPH,
            payload_digest=digest,
        )

        projection = build_diagnostic_projection(
            canonical,
            canonical_graph_ref=graph_ref,
        )

        selection = next(
            item
            for item in projection.parent_selections
            if item.child_concept_id
            == accepted_concept("3", "Shared child").concept_id
        )
        self.assertEqual(len(selection.alternate_parent_edge_ids), 1)
        self.assertEqual(
            projection.quality_status,
            ProjectionQualityStatus.BLOCKED_SEMANTIC,
        )

    def test_parentless_claim_is_blocked_not_promoted_to_root(self):
        canonical = graph_fixture(
            (accepted_concept("1", "Parentless claim"),),
            (),
        ).model_copy(
            update={
                "unresolved_items": (
                    GraphAuditItem(
                        item_type="concept",
                        item_id=accepted_concept(
                            "1",
                            "Parentless claim",
                        ).concept_id,
                        reason_codes=(
                            "accepted_claim_without_accepted_parent",
                        ),
                    ),
                )
            }
        )
        graph_ref = ArtifactRef(
            owner_id="owner-a",
            artifact_id=artifact_id("8"),
            artifact_type=ArtifactType.CANONICAL_EXPLICIT_GRAPH,
            payload_digest=payload_digest(canonical),
        )

        projection = build_diagnostic_projection(
            canonical,
            canonical_graph_ref=graph_ref,
        )

        self.assertEqual(
            projection.quality_status,
            ProjectionQualityStatus.BLOCKED_SEMANTIC,
        )
        self.assertTrue(
            any(
                diagnostic.code == "accepted_claim_parent_unresolved"
                for diagnostic in projection.diagnostics
            )
        )


if __name__ == "__main__":
    unittest.main()
