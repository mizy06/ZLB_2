from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.vnext.contracts.exporter import (
    DEFAULT_SCHEMA_DIR,
    JSON_SCHEMA_DIALECT,
    contract_schema,
    write_schema_bundle,
)
from backend.vnext.contracts.registry import CONTRACTS


def _object_schemas(value):
    if isinstance(value, dict):
        if value.get("type") == "object":
            yield value
        for child in value.values():
            yield from _object_schemas(child)
    elif isinstance(value, list):
        for child in value:
            yield from _object_schemas(child)


class VNextSchemaBundleTests(unittest.TestCase):
    def test_registry_freezes_all_s0_root_contracts(self):
        self.assertEqual(
            [item.name for item in CONTRACTS],
            [
                "SourceObservationIR",
                "SourceInventory",
                "RegionPlan",
                "RegionSplitCertificate",
                "ReplanRequest",
                "ClaimLedger",
                "ClaimProposalBatch",
                "RegionPlannerProposal",
                "RegionDecisionVerification",
                "OmissionAudit",
                "RelationProposalLedger",
                "RelationAssessmentLedger",
                "CanonicalExplicitGraph",
                "DiagnosticProjection",
                "ArtifactEnvelope",
                "RunManifest",
                "StageCommit",
                "QualityAttestation",
                "TaskEnvelope",
                "ModelPortfolioManifest",
                "RecordedInteraction",
                "SearchIntent",
                "EvidenceBundle",
                "PilotDataset",
                "PilotEvaluationReport",
                "ReviewTask",
                "ReviewDecision",
                "AffectedReplayPlan",
                "CrossLinkProposalLedger",
                "CrossLinkResolutionLedger",
                "CanaryPolicy",
                "CanaryTransitionDecision",
                "RollbackRecord",
                "ReleaseEvent",
                "ProjectionMediaBundle",
                "RenderedPresentationBundle",
            ],
        )

    def test_schemas_use_2020_12_and_forbid_unknown_object_fields(self):
        for registration in CONTRACTS:
            with self.subTest(contract=registration.name):
                schema = contract_schema(registration)
                self.assertEqual(schema["$schema"], JSON_SCHEMA_DIALECT)
                self.assertEqual(schema["$id"], registration.schema_id)
                object_schemas = tuple(_object_schemas(schema))
                self.assertTrue(object_schemas)
                self.assertTrue(
                    all(
                        item.get("additionalProperties") is False
                        for item in object_schemas
                    )
                )

    def test_evidence_namespace_prefix_rules_are_archived_in_schema(self):
        schema = contract_schema(CONTRACTS[0])
        evidence_schema = schema["$defs"]["EvidenceRef"]

        self.assertEqual(len(evidence_schema["allOf"]), 4)
        self.assertEqual(
            {
                condition["if"]["properties"]["namespace"]["const"]
                for condition in evidence_schema["allOf"]
            },
            {"courseware", "external", "human", "system"},
        )

    def test_artifact_type_schema_bindings_are_archived_in_schema(self):
        envelope = next(
            item for item in CONTRACTS if item.name == "ArtifactEnvelope"
        )
        schema = contract_schema(envelope)

        self.assertEqual(len(schema["allOf"]), 11)
        self.assertEqual(
            {
                condition["if"]["properties"]["artifact_type"]["const"]
                for condition in schema["allOf"]
            },
            {
                item.artifact_type.value
                for item in CONTRACTS
                if item.artifact_type is not None
            },
        )
        bottom_up_rule = next(
            condition
            for condition in schema["allOf"]
            if condition["if"]["properties"]["artifact_type"]["const"]
            == "replan_request"
        )
        self.assertEqual(
            bottom_up_rule["then"]["properties"]["producer"][
                "properties"
            ]["role"]["enum"],
            ["bottom_up_region_auditor"],
        )

    def test_schema_export_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            first = write_schema_bundle(output)
            second = write_schema_bundle(output, check=True)

            self.assertEqual(len(first), 37)
            self.assertEqual(second, ())
            manifest = json.loads(
                (output / "manifest.json").read_text(encoding="ascii")
            )
            self.assertEqual(len(manifest["contracts"]), 36)

    def test_checked_in_bundle_matches_models(self):
        self.assertEqual(
            write_schema_bundle(DEFAULT_SCHEMA_DIR, check=True),
            (),
        )


if __name__ == "__main__":
    unittest.main()
