from __future__ import annotations

import unittest

from pydantic import ValidationError

from backend.vnext.artifacts.canonical import payload_digest
from backend.vnext.contracts.common import ArtifactRef, ArtifactType
from backend.vnext.contracts.graph import (
    CanonicalRelation,
    CanonicalStatus,
    EvidenceAuthority,
    HierarchyDirectness,
    SemanticRelation,
)
from backend.vnext.contracts.projection import (
    DiagnosticProjection,
    LayoutProfile,
    ProjectionParentSelection,
    ProjectionPurpose,
    ProjectionQualityStatus,
)
from backend.vnext.projection import validate_projection_against_graph

from backend.tests.vnext_test_support import (
    accepted_concept,
    accepted_relation,
    artifact_id,
    concept_id,
    courseware_evidence,
    digest,
    graph,
    producer,
    relation_id,
)


class VNextCanonicalGraphTests(unittest.TestCase):
    def test_parentless_accepted_concept_remains_valid_without_root_fallback(
        self,
    ):
        result = graph((accepted_concept("1", "Unresolved parent"),), ())

        self.assertEqual(result.relations, ())

    def test_two_accepted_parents_remain_in_canonical_dag(self):
        result = graph(
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

        self.assertEqual(len(result.relations), 2)

    def test_external_only_relation_cannot_be_accepted(self):
        with self.assertRaisesRegex(
            ValidationError,
            "external",
        ):
            accepted_relation(
                "4",
                "1",
                "2",
                authority=EvidenceAuthority.EXTERNAL_ONLY,
            )

    def test_outline_cannot_certify_is_a(self):
        with self.assertRaisesRegex(
            ValidationError,
            "outline evidence",
        ):
            accepted_relation(
                "4",
                "1",
                "2",
                relation=SemanticRelation.IS_A,
                authority=EvidenceAuthority.OUTLINE_STRUCTURAL,
                region_plan_ref=ArtifactRef(
                    owner_id="owner-a",
                    artifact_id=artifact_id("3"),
                    artifact_type=ArtifactType.REGION_PLAN,
                    payload_digest=digest("3"),
                ),
            )

    def test_outline_parent_requires_declared_region_plan_support(self):
        with self.assertRaisesRegex(ValidationError, "RegionPlan support"):
            accepted_relation(
                "4",
                "1",
                "2",
                authority=EvidenceAuthority.OUTLINE_STRUCTURAL,
            )

    def test_direct_hierarchy_cycle_is_rejected(self):
        concepts = (
            accepted_concept("1", "A"),
            accepted_concept("2", "B"),
        )

        with self.assertRaisesRegex(ValidationError, "acyclic"):
            graph(
                concepts,
                (
                    accepted_relation("3", "1", "2"),
                    accepted_relation("4", "2", "1"),
                ),
            )

    def test_rejected_relation_cannot_reopen_without_novel_evidence(self):
        evidence = courseware_evidence("4")
        old = CanonicalRelation(
            relation_id=relation_id("4"),
            source_id=concept_id("1"),
            target_id=concept_id("2"),
            semantic_relation=SemanticRelation.TOPIC_CONTAINS,
            hierarchy_directness=HierarchyDirectness.DIRECT,
            evidence_authority=EvidenceAuthority.COURSEWARE_DIRECT,
            edge_evidence_refs=(evidence,),
            status=CanonicalStatus.REJECTED,
            rejection_reasons=("verifier_veto",),
        )
        reopened = accepted_relation("5", "1", "2").model_copy(
            update={
                "edge_evidence_refs": (evidence,),
                "supersedes": relation_id("4"),
            }
        )

        with self.assertRaisesRegex(ValidationError, "novel"):
            graph(
                (
                    accepted_concept("1", "Parent"),
                    accepted_concept("2", "Child"),
                ),
                (old, reopened),
            )


class VNextProjectionTests(unittest.TestCase):
    def _projection(
        self,
        canonical_graph,
        *,
        edge_id: str,
    ) -> DiagnosticProjection:
        graph_digest = payload_digest(canonical_graph)
        return DiagnosticProjection(
            projection_id=f"projection_{'1' * 32}",
            canonical_graph_ref=ArtifactRef(
                owner_id="owner-a",
                artifact_id=artifact_id("9"),
                artifact_type=ArtifactType.CANONICAL_EXPLICIT_GRAPH,
                payload_digest=graph_digest,
            ),
            canonical_hash=graph_digest,
            purpose=ProjectionPurpose.OVERVIEW,
            included_ids=(concept_id("1"), concept_id("2")),
            parent_selections=(
                ProjectionParentSelection(
                    child_concept_id=concept_id("2"),
                    selected_parent_edge_id=edge_id,
                ),
            ),
            projection_parent_edge_ids=(edge_id,),
            layout_profile=LayoutProfile(
                profile_id="overview-web",
                medium="web",
                direction="source_order_single_side",
                node_budget=32,
            ),
            quality_status=ProjectionQualityStatus.PASSED,
        )

    def test_projection_can_only_select_accepted_canonical_parent(self):
        rejected = CanonicalRelation(
            relation_id=relation_id("3"),
            source_id=concept_id("1"),
            target_id=concept_id("2"),
            semantic_relation=SemanticRelation.TOPIC_CONTAINS,
            hierarchy_directness=HierarchyDirectness.DIRECT,
            evidence_authority=EvidenceAuthority.COURSEWARE_DIRECT,
            edge_evidence_refs=(courseware_evidence("3"),),
            status=CanonicalStatus.REJECTED,
            rejection_reasons=("insufficient_directness",),
        )
        canonical = graph(
            (
                accepted_concept("1", "Parent"),
                accepted_concept("2", "Child"),
            ),
            (rejected,),
        )
        projection = self._projection(
            canonical,
            edge_id=rejected.relation_id,
        )

        with self.assertRaisesRegex(ValueError, "accepted"):
            validate_projection_against_graph(projection, canonical)

    def test_projection_selects_existing_direct_parent(self):
        relation = accepted_relation("3", "1", "2")
        canonical = graph(
            (
                accepted_concept("1", "Parent"),
                accepted_concept("2", "Child"),
            ),
            (relation,),
        )
        projection = self._projection(
            canonical,
            edge_id=relation.relation_id,
        )

        validate_projection_against_graph(projection, canonical)


if __name__ == "__main__":
    unittest.main()
