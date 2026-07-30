from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from backend.tests.vnext_test_support import (
    accepted_concept,
    accepted_relation,
    artifact_producer,
    courseware_evidence,
    graph,
)
from backend.vnext.artifacts.canonical import payload_digest
from backend.vnext.artifacts.local_store import LocalArtifactStore
from backend.vnext.contracts.common import ArtifactRef, ArtifactType
from backend.vnext.contracts.graph import (
    CanonicalConcept,
    CanonicalRelation,
    CanonicalStatus,
    EvidenceAuthority,
    HierarchyDirectness,
    SemanticRelation,
    VerifierClassification,
    VerifierDecision,
)
from backend.vnext.contracts.common import RuntimeRole
from backend.vnext.contracts.presentation import (
    MediaProjectionContract,
    PresentationMedium,
    ProjectionMediaBundle,
)
from backend.vnext.orchestration.shadow_pipeline import run_shadow_pipeline
from backend.vnext.presentation import (
    PresentationBlocked,
    build_projection_media_bundle,
)
from backend.vnext.projection import build_diagnostic_projection


NOW = datetime(2026, 7, 29, 15, 0, tzinfo=UTC)
VALID_SOURCE = (
    "# Carbonyl Chemistry\n"
    "## Foundations\n"
    "Aldehydes are terminal carbonyl compounds.\n"
    "## Applications\n"
    "Ketones are used in synthesis.\n"
)


def _projection_ref(projection) -> ArtifactRef:
    return ArtifactRef(
        owner_id="owner-a",
        artifact_id=f"art_{'8' * 32}",
        artifact_type=ArtifactType.DIAGNOSTIC_PROJECTION,
        payload_digest=payload_digest(projection),
    )


def _bundle_from_source(root: Path):
    source_path = root / "course.md"
    source_path.write_text(VALID_SOURCE, encoding="utf-8")
    store = LocalArtifactStore(root / "artifacts")
    result = run_shadow_pipeline(
        source_path,
        owner_id="owner-a",
        store=store,
    )
    bundle = build_projection_media_bundle(
        result.canonical_graph,
        result.projection,
        canonical_graph_ref=store.ref(
            result.canonical_graph_envelope
        ),
        projection_ref=store.ref(result.projection_envelope),
        created_at=NOW,
    )
    return result, bundle


class VNextPresentationTests(unittest.TestCase):
    def test_all_media_share_one_semantic_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, bundle = _bundle_from_source(Path(tmp))

            self.assertEqual(
                tuple(item.medium for item in bundle.media),
                tuple(PresentationMedium),
            )
            first = bundle.media[0]
            for medium in bundle.media[1:]:
                self.assertEqual(medium.nodes, first.nodes)
                self.assertEqual(medium.parents, first.parents)
                self.assertEqual(medium.cross_links, first.cross_links)
                self.assertEqual(medium.hidden_ids, first.hidden_ids)
                self.assertEqual(
                    medium.semantic_fingerprint,
                    bundle.semantic_fingerprint,
                )
            web = next(
                item
                for item in bundle.media
                if item.medium is PresentationMedium.WEB
            )
            mobile = next(
                item
                for item in bundle.media
                if item.medium is PresentationMedium.MOBILE
            )
            self.assertTrue(web.accessibility.dom_outline_present)
            self.assertTrue(web.accessibility.keyboard_navigation)
            self.assertEqual(mobile.render_mode, "outline_detail")
            self.assertEqual(mobile.graphical_node_limit, 18)
            self.assertEqual(
                mobile.accessibility.minimum_target_size,
                44,
            )

    def test_medium_font_gates_are_hard_contracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, bundle = _bundle_from_source(Path(tmp))
            png = next(
                item
                for item in bundle.media
                if item.medium is PresentationMedium.PNG
            )
            payload = png.model_dump(mode="json")
            payload["accessibility"]["normal_node_font_size"] = 15

            with self.assertRaisesRegex(
                ValueError,
                "font size",
            ):
                MediaProjectionContract.model_validate(payload)

    def test_one_medium_cannot_mutate_label_or_parent_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, bundle = _bundle_from_source(Path(tmp))
            payload = bundle.model_dump(mode="json")
            payload["media"][1]["nodes"][0]["label"] = "Changed only on mobile"

            with self.assertRaisesRegex(
                ValueError,
                "identical projection semantics",
            ):
                ProjectionMediaBundle.model_validate(payload)

    def test_blocked_projection_cannot_create_publishable_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "course.md"
            source_path.write_text(
                "## First\nA fact.\n## Second\nAnother fact.\n",
                encoding="utf-8",
            )
            store = LocalArtifactStore(root / "artifacts")
            result = run_shadow_pipeline(
                source_path,
                owner_id="owner-a",
                store=store,
            )

            with self.assertRaisesRegex(
                PresentationBlocked,
                "quality-passed",
            ):
                build_projection_media_bundle(
                    result.canonical_graph,
                    result.projection,
                    canonical_graph_ref=store.ref(
                        result.canonical_graph_envelope
                    ),
                    projection_ref=store.ref(
                        result.projection_envelope
                    ),
                    created_at=NOW,
                )

    def test_large_projection_tiles_png_without_shrinking_mobile_map(self):
        concepts: list[CanonicalConcept] = []
        for index in range(40):
            template = accepted_concept("1", f"Concept {index}")
            payload = template.model_dump(mode="json")
            payload.update(
                {
                    "concept_id": f"concept_{index + 1:032x}",
                    "canonical_name": (
                        "Root" if index == 0 else f"Concept {index}"
                    ),
                    "source_claim_ids": (
                        f"claim_{index + 1:032x}",
                    ),
                }
            )
            concepts.append(CanonicalConcept.model_validate(payload))
        relations: list[CanonicalRelation] = []
        for index in range(1, 40):
            template = accepted_relation("a", "1", "2")
            payload = template.model_dump(mode="json")
            payload.update(
                {
                    "relation_id": f"relation_{index:032x}",
                    "source_id": concepts[0].concept_id,
                    "target_id": concepts[index].concept_id,
                    "source_claim_ids": (
                        f"claim_{index + 1:032x}",
                    ),
                }
            )
            relations.append(CanonicalRelation.model_validate(payload))
        canonical = graph(tuple(concepts), tuple(relations))
        canonical_ref = ArtifactRef(
            owner_id="owner-a",
            artifact_id=f"art_{'7' * 32}",
            artifact_type=ArtifactType.CANONICAL_EXPLICIT_GRAPH,
            payload_digest=payload_digest(canonical),
        )
        projection = build_diagnostic_projection(
            canonical,
            canonical_graph_ref=canonical_ref,
            node_budget=48,
        )

        bundle = build_projection_media_bundle(
            canonical,
            projection,
            canonical_graph_ref=canonical_ref,
            projection_ref=_projection_ref(projection),
            created_at=NOW,
        )

        png = next(
            item
            for item in bundle.media
            if item.medium is PresentationMedium.PNG
        )
        mobile = next(
            item
            for item in bundle.media
            if item.medium is PresentationMedium.MOBILE
        )
        self.assertEqual(len(png.nodes), 40)
        self.assertTrue(png.paginated)
        self.assertEqual(png.page_or_tile_count, 2)
        self.assertEqual(len(mobile.nodes), 40)
        self.assertEqual(mobile.graphical_node_limit, 18)
        self.assertEqual(mobile.render_mode, "outline_detail")

    def test_verified_cross_link_is_preserved_in_every_medium(self):
        concepts = (
            accepted_concept("1", "Course"),
            accepted_concept("2", "Cause"),
            accepted_concept("3", "Effect"),
        )
        hierarchy = (
            accepted_relation("1", "1", "2"),
            accepted_relation("2", "1", "3"),
        )
        evidence = courseware_evidence("4")
        cross_link = CanonicalRelation(
            relation_id=f"relation_{'4' * 32}",
            source_id=concepts[1].concept_id,
            target_id=concepts[2].concept_id,
            semantic_relation=SemanticRelation.CAUSES,
            hierarchy_directness=HierarchyDirectness.NON_HIERARCHICAL,
            evidence_authority=EvidenceAuthority.COURSEWARE_DIRECT,
            source_claim_ids=(f"claim_{'3' * 32}",),
            edge_evidence_refs=(evidence,),
            verifier_decisions=(
                VerifierDecision(
                    verifier=artifact_producer(
                        "4",
                        RuntimeRole.RELATION_VERIFIER_A,
                    ),
                    classification=VerifierClassification.SEMANTIC_LINK,
                    supports_relation=True,
                    courseware_evidence_refs=(evidence,),
                    reason_codes=("courseware_direct",),
                ),
            ),
            status=CanonicalStatus.ACCEPTED,
        )
        canonical = graph(concepts, (*hierarchy, cross_link))
        canonical_ref = ArtifactRef(
            owner_id="owner-a",
            artifact_id=f"art_{'7' * 32}",
            artifact_type=ArtifactType.CANONICAL_EXPLICIT_GRAPH,
            payload_digest=payload_digest(canonical),
        )
        projection = build_diagnostic_projection(
            canonical,
            canonical_graph_ref=canonical_ref,
        )

        bundle = build_projection_media_bundle(
            canonical,
            projection,
            canonical_graph_ref=canonical_ref,
            projection_ref=_projection_ref(projection),
            created_at=NOW,
        )

        for medium in bundle.media:
            self.assertEqual(
                tuple(item.relation_id for item in medium.cross_links),
                (cross_link.relation_id,),
            )


if __name__ == "__main__":
    unittest.main()
