from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from backend.vnext.artifacts.canonical import (
    canonical_json_bytes,
    new_artifact_id,
    payload_digest,
    stable_source_id,
)
from backend.vnext.artifacts.local_store import LocalArtifactStore
from backend.vnext.contracts.common import (
    ArtifactRef,
    ArtifactType,
    InterpretationStatus,
    RuntimeRole,
)
from backend.vnext.contracts.artifacts import ArtifactEnvelope
from backend.vnext.contracts.evidence import EvidenceNamespace, EvidenceRef
from backend.vnext.contracts.regions import (
    BoundaryError,
    ReplanAction,
    ReplanRequest,
)
from backend.vnext.contracts.source import (
    PageDimensions,
    PageIR,
    ParserManifest,
    RoleHypothesis,
    SourceObservationIR,
)

from backend.tests.vnext_test_support import (
    courseware_evidence,
    artifact_id,
    artifact_producer,
    digest,
    external_evidence,
    producer,
    region_id,
    source_id,
)


class VNextContractFoundationTests(unittest.TestCase):
    def test_rfc8785_digest_is_order_independent(self):
        left = {"b": 1, "a": [3, 2, 1]}
        right = {"a": [3, 2, 1], "b": 1}

        self.assertEqual(
            canonical_json_bytes(left),
            b'{"a":[3,2,1],"b":1}',
        )
        self.assertEqual(payload_digest(left), payload_digest(right))

    def test_rfc8785_rejects_non_string_object_keys(self):
        with self.assertRaisesRegex(TypeError, "string keys"):
            canonical_json_bytes({1: "ambiguous", "1": "collision"})

    def test_stable_source_id_scope_is_explicit(self):
        arguments = {
            "kind": "page",
            "source_hash": digest("a"),
            "parser_major": 1,
            "locator": {"physical_index": 0},
        }

        first = stable_source_id(**arguments)
        second = stable_source_id(**arguments)
        parser_upgrade = stable_source_id(
            **{**arguments, "parser_major": 2}
        )

        self.assertEqual(first, second)
        self.assertNotEqual(first, parser_upgrade)
        self.assertTrue(first.startswith("src:page:"))

    def test_artifact_ids_are_opaque_and_not_content_derived(self):
        first = new_artifact_id()
        second = new_artifact_id()

        self.assertRegex(first, r"^art_[0-9a-f]{32}$")
        self.assertNotEqual(first, second)

    def test_artifact_envelope_binds_type_schema_and_version(self):
        with self.assertRaisesRegex(
            ValidationError,
            "same contract",
        ):
            ArtifactEnvelope(
                artifact_id=artifact_id("a"),
                artifact_type=ArtifactType.REPLAN_REQUEST,
                schema_id=(
                    "urn:zlb:vnext:schema:region-plan:1.0.0"
                ),
                payload_schema_version="1.0.0",
                owner_id="owner-a",
                payload_digest=digest("a"),
                producer=artifact_producer(
                    "a",
                    RuntimeRole.BOTTOM_UP_REGION_AUDITOR,
                ),
                created_at="2026-07-29T00:00:00Z",
            )

    def test_artifact_supersedes_same_owner_and_type_only(self):
        with self.assertRaisesRegex(ValidationError, "same artifact type"):
            ArtifactEnvelope(
                artifact_id=artifact_id("a"),
                artifact_type=ArtifactType.REPLAN_REQUEST,
                schema_id=(
                    "urn:zlb:vnext:schema:replan-request:1.0.0"
                ),
                payload_schema_version="1.0.0",
                owner_id="owner-a",
                payload_digest=digest("a"),
                producer=artifact_producer(
                    "a",
                    RuntimeRole.BOTTOM_UP_REGION_AUDITOR,
                ),
                created_at="2026-07-29T00:00:00Z",
                supersedes=ArtifactRef(
                    owner_id="owner-a",
                    artifact_id=artifact_id("b"),
                    artifact_type=ArtifactType.REGION_PLAN,
                    payload_digest=digest("b"),
                ),
            )

    def test_artifact_envelope_rejects_wrong_writer_role(self):
        with self.assertRaisesRegex(ValidationError, "cannot produce"):
            ArtifactEnvelope(
                artifact_id=artifact_id("c"),
                artifact_type=ArtifactType.REPLAN_REQUEST,
                schema_id=(
                    "urn:zlb:vnext:schema:replan-request:1.0.0"
                ),
                payload_schema_version="1.0.0",
                owner_id="owner-a",
                payload_digest=digest("c"),
                producer=artifact_producer(
                    "c",
                    RuntimeRole.CANONICALIZER,
                ),
                created_at="2026-07-29T00:00:00Z",
            )

    def test_evidence_namespaces_cannot_be_mixed(self):
        with self.assertRaises(ValidationError):
            EvidenceRef(
                namespace=EvidenceNamespace.EXTERNAL,
                ref_id=source_id("block", "a"),
            )

    def test_source_observation_keeps_role_as_hypothesis(self):
        page_id = source_id("page", "1")
        role = RoleHypothesis(
            hypothesis_id=f"hyp_{'1' * 32}",
            role="toc",
            confidence=0.95,
            interpretation_status=InterpretationStatus.INFERRED,
            producer=producer("1"),
            evidence_refs=(courseware_evidence("1", kind="page"),),
        )
        source = SourceObservationIR(
            document_id=source_id("doc", "a"),
            source_hash=digest("a"),
            parser_manifest=ParserManifest(
                parser_name="fixture-parser",
                parser_version="1.0.0",
                parser_major=1,
                dependency_digest=digest("b"),
            ),
            pages=(
                PageIR(
                    page_id=page_id,
                    physical_index=0,
                    dimensions=PageDimensions(
                        width=612,
                        height=792,
                        unit="point",
                    ),
                    role_hypotheses=(role,),
                    render_ref=EvidenceRef(
                        namespace=EvidenceNamespace.SYSTEM,
                        ref_id="sys:render:page-1",
                    ),
                ),
            ),
        )

        self.assertEqual(
            source.pages[0].role_hypotheses[0].role.value,
            "toc",
        )
        with self.assertRaises(ValidationError):
            RoleHypothesis(
                hypothesis_id=f"hyp_{'2' * 32}",
                role="toc",
                confidence=1,
                interpretation_status=InterpretationStatus.OBSERVED,
                producer=producer("2"),
                evidence_refs=(courseware_evidence("1", kind="page"),),
            )

    def test_external_evidence_cannot_rewrite_source_interpretation(self):
        page_id = source_id("page", "2")
        role = RoleHypothesis(
            hypothesis_id=f"hyp_{'3' * 32}",
            role="content",
            confidence=0.6,
            interpretation_status=InterpretationStatus.INFERRED,
            producer=producer("3"),
            evidence_refs=(external_evidence("3"),),
        )

        with self.assertRaisesRegex(ValidationError, "forbidden"):
            SourceObservationIR(
                document_id=source_id("doc", "b"),
                source_hash=digest("b"),
                parser_manifest=ParserManifest(
                    parser_name="fixture-parser",
                    parser_version="1.0.0",
                    parser_major=1,
                    dependency_digest=digest("c"),
                ),
                pages=(
                    PageIR(
                        page_id=page_id,
                        physical_index=0,
                        dimensions=PageDimensions(
                            width=612,
                            height=792,
                            unit="point",
                        ),
                        role_hypotheses=(role,),
                        render_ref=EvidenceRef(
                            namespace=EvidenceNamespace.SYSTEM,
                            ref_id="sys:render:page-2",
                        ),
                    ),
                ),
            )

    def test_contracts_are_frozen_and_forbid_unknown_fields(self):
        request = ReplanRequest(
            request_id=f"replan_{'1' * 32}",
            affected_region_id=region_id("1"),
            minimum_replan_ancestor_id=region_id("1"),
            boundary_errors=(
                BoundaryError(
                    source_id=source_id("block", "1"),
                    current_region_id=region_id("1"),
                    reason="mixed theme",
                ),
            ),
            requested_action=ReplanAction.RESPLIT,
            evidence_refs=(courseware_evidence("1"),),
        )

        with self.assertRaises(ValidationError):
            ReplanRequest.model_validate(
                {
                    **request.model_dump(mode="json"),
                    "replacement_parent_id": region_id("2"),
                }
            )
        with self.assertRaises(ValidationError):
            request.requested_action = ReplanAction.RENAME_REGION

    def test_shadow_store_is_owner_scoped_and_role_checked(self):
        request = ReplanRequest(
            request_id=f"replan_{'3' * 32}",
            affected_region_id=region_id("3"),
            minimum_replan_ancestor_id=region_id("3"),
            boundary_errors=(
                BoundaryError(
                    source_id=source_id("block", "3"),
                    current_region_id=region_id("3"),
                    reason="boundary drift",
                ),
            ),
            requested_action=ReplanAction.MOVE_BOUNDARY,
            evidence_refs=(courseware_evidence("3"),),
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalArtifactStore(Path(tmp))
            first = store.put(
                owner_id="tenant-a",
                role=RuntimeRole.BOTTOM_UP_REGION_AUDITOR,
                payload=request,
                producer=artifact_producer(
                    "3",
                    RuntimeRole.BOTTOM_UP_REGION_AUDITOR,
                ),
            )
            second = store.put(
                owner_id="tenant-b",
                role=RuntimeRole.BOTTOM_UP_REGION_AUDITOR,
                payload=request,
                producer=artifact_producer(
                    "3",
                    RuntimeRole.BOTTOM_UP_REGION_AUDITOR,
                ),
            )

            self.assertNotEqual(first.artifact_id, second.artifact_id)
            loaded = store.get(
                owner_id="tenant-a",
                artifact_id=first.artifact_id,
            )
            self.assertEqual(loaded.payload, request)
            self.assertEqual(
                tuple(
                    store._artifacts_root("tenant-a").glob(".pending-*")
                ),
                (),
            )
            with self.assertRaises(FileNotFoundError):
                store.get(
                    owner_id="tenant-b",
                    artifact_id=first.artifact_id,
                )
            with self.assertRaises(ValueError):
                store.put(
                    owner_id="tenant-a",
                    role=RuntimeRole.CANONICALIZER,
                    payload=request,
                    producer=artifact_producer(
                        "4",
                        RuntimeRole.CANONICALIZER,
                    ),
                )

    def test_shadow_store_rejects_mismatched_producer_role(self):
        request = ReplanRequest(
            request_id=f"replan_{'4' * 32}",
            affected_region_id=region_id("4"),
            minimum_replan_ancestor_id=region_id("4"),
            boundary_errors=(
                BoundaryError(
                    source_id=source_id("block", "4"),
                    current_region_id=region_id("4"),
                    reason="mixed theme",
                ),
            ),
            requested_action=ReplanAction.RESPLIT,
            evidence_refs=(courseware_evidence("4"),),
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalArtifactStore(Path(tmp))
            with self.assertRaisesRegex(ValueError, "producer role"):
                store.put(
                    owner_id="tenant-a",
                    role=RuntimeRole.BOTTOM_UP_REGION_AUDITOR,
                    payload=request,
                    producer=artifact_producer(
                        "4",
                        RuntimeRole.CANONICALIZER,
                    ),
                )

    def test_shadow_store_reconciles_uncommitted_pending_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalArtifactStore(Path(tmp))
            artifacts_root = store._artifacts_root("tenant-a")
            pending = (
                artifacts_root
                / f".pending-art_{'a' * 32}-{'b' * 16}"
            )
            pending.mkdir(parents=True)
            (pending / "payload.jcs.json").write_text(
                "{}",
                encoding="ascii",
            )

            removed = store.reconcile_pending(owner_id="tenant-a")

            self.assertEqual(removed, (pending.name,))
            self.assertFalse(pending.exists())


if __name__ == "__main__":
    unittest.main()
