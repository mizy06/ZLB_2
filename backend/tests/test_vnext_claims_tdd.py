from __future__ import annotations

import unittest

from pydantic import ValidationError

from backend.vnext.contracts.claims import (
    ClaimNovelty,
    ClaimPublicationStatus,
    ClaimRecord,
    ClaimScope,
    ClaimType,
    ExternalValidityStatus,
    ExtractionStatus,
    InstructionalRole,
    SourceEntailmentStatus,
)
from backend.vnext.contracts.common import RuntimeRole

from backend.tests.vnext_test_support import (
    artifact_producer,
    claim_id,
    courseware_evidence,
    external_evidence,
    region_id,
)


def _claim(**updates) -> ClaimRecord:
    values = {
        "claim_id": claim_id("1"),
        "leaf_region_id": region_id("1"),
        "claim_type": ClaimType.DEFINITION,
        "normalized_text": "An aldehyde contains a terminal carbonyl group.",
        "source_text": "Aldehydes contain a terminal carbonyl group.",
        "predicate": "contains",
        "instructional_role": InstructionalRole.DEFINITION,
        "novelty": ClaimNovelty.SOURCE_EXPLICIT,
        "scope": ClaimScope.REGION,
        "source_evidence_refs": (courseware_evidence("1"),),
        "external_evidence_refs": (),
        "extraction_confidence": 0.95,
        "extraction_status": ExtractionStatus.EXTRACTED,
        "source_entailment_status": SourceEntailmentStatus.ENTAILED,
        "external_validity_status": ExternalValidityStatus.NOT_CHECKED,
        "publication_status": ClaimPublicationStatus.CORE,
        "extractor": artifact_producer(
            "1",
            RuntimeRole.CLAIM_ATOMIZER,
        ),
        "fidelity_verifier": artifact_producer(
            "2",
            RuntimeRole.CLAIM_FIDELITY_VERIFIER,
        ),
    }
    values.update(updates)
    return ClaimRecord(**values)


class VNextClaimStateTests(unittest.TestCase):
    def test_instruction_cannot_be_promoted_to_core_fact(self):
        with self.assertRaisesRegex(ValidationError, "instruction"):
            _claim(
                claim_type=ClaimType.INSTRUCTION,
                normalized_text="Complete the following conversion.",
                source_text="Complete the following conversion.",
                predicate="instructs",
                instructional_role=InstructionalRole.EXERCISE,
            )

    def test_external_only_claim_cannot_be_published_as_core(self):
        with self.assertRaisesRegex(ValidationError, "source evidence"):
            _claim(
                source_evidence_refs=(),
                external_evidence_refs=(external_evidence("2"),),
                novelty=ClaimNovelty.EXTERNAL_EXTENSION,
            )

    def test_extraction_entailment_external_and_publication_states_stay_split(
        self,
    ):
        claim = _claim(
            source_entailment_status=SourceEntailmentStatus.INSUFFICIENT,
            external_validity_status=ExternalValidityStatus.SUPPORTS,
            publication_status=ClaimPublicationStatus.WITHHELD,
            external_resolver=artifact_producer(
                "3",
                RuntimeRole.DOMAIN_RESOLVER,
            ),
        )

        self.assertEqual(claim.extraction_status.value, "extracted")
        self.assertEqual(
            claim.source_entailment_status.value,
            "insufficient",
        )
        self.assertEqual(
            claim.external_validity_status.value,
            "supports",
        )
        self.assertEqual(claim.publication_status.value, "withheld")

    def test_enriched_overlay_requires_external_evidence(self):
        with self.assertRaisesRegex(ValidationError, "external evidence"):
            _claim(
                publication_status=ClaimPublicationStatus.ENRICHED_OVERLAY,
            )

    def test_claim_extractor_cannot_self_verify(self):
        extractor = artifact_producer(
            "4",
            RuntimeRole.CLAIM_ATOMIZER,
        )
        verifier = artifact_producer(
            "4",
            RuntimeRole.CLAIM_FIDELITY_VERIFIER,
        )
        with self.assertRaisesRegex(ValidationError, "verify its own"):
            _claim(
                extractor=extractor,
                fidelity_verifier=verifier,
            )


if __name__ == "__main__":
    unittest.main()
