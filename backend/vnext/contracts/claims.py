from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from .base import FrozenContract
from .common import (
    ArtifactProducerRef,
    ArtifactRef,
    ArtifactType,
    ClaimId,
    DecisionEvent,
    RegionId,
    RuntimeRole,
    SourceId,
    require_artifact_type,
)
from .evidence import EvidenceNamespace, EvidenceRef, require_evidence_namespace


LedgerId = Annotated[
    str,
    StringConstraints(pattern=r"^ledger_[0-9a-f]{32}$"),
]
AuditId = Annotated[
    str,
    StringConstraints(pattern=r"^omission_audit_[0-9a-f]{32}$"),
]
RecordedInteractionId = Annotated[
    str,
    StringConstraints(pattern=r"^interaction_[0-9a-f]{32}$"),
]


class ClaimType(StrEnum):
    DEFINITION = "definition"
    PROPERTY = "property"
    MECHANISM = "mechanism"
    REACTION = "reaction"
    CONDITION = "condition"
    COMPARISON = "comparison"
    EXAMPLE = "example"
    EXCEPTION = "exception"
    PROCEDURE = "procedure"
    WARNING = "warning"
    SUMMARY = "summary"
    INSTRUCTION = "instruction"
    STRUCTURAL_FACT = "structural_fact"


class InstructionalRole(StrEnum):
    DEFINITION = "definition"
    PRINCIPLE = "principle"
    PROCEDURE = "procedure"
    COMPARISON = "comparison"
    APPLICATION = "application"
    EXERCISE = "exercise"
    REVIEW = "review"
    EXAMPLE = "example"
    WARNING = "warning"
    OTHER = "other"


class ClaimNovelty(StrEnum):
    SOURCE_EXPLICIT = "source_explicit"
    SOURCE_RESTATEMENT = "source_restatement"
    PLANNER_CONTEXT = "planner_context"
    EXTERNAL_EXTENSION = "external_extension"


class ClaimScope(StrEnum):
    OBJECT = "object"
    PAGE = "page"
    REGION = "region"
    DOCUMENT = "document"


class ExtractionStatus(StrEnum):
    CANDIDATE = "candidate"
    EXTRACTED = "extracted"
    PARTIAL = "partial"
    UNRESOLVED = "unresolved"
    REJECTED = "rejected"


class SourceEntailmentStatus(StrEnum):
    UNASSESSED = "unassessed"
    ENTAILED = "entailed"
    PARTIAL = "partial"
    CONTRADICTED = "contradicted"
    INSUFFICIENT = "insufficient"


class ExternalValidityStatus(StrEnum):
    NOT_CHECKED = "not_checked"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    DISAMBIGUATES = "disambiguates"
    NORMALIZES = "normalizes"
    EXTENDS = "extends"
    UNRESOLVED = "unresolved"


class ClaimPublicationStatus(StrEnum):
    CANDIDATE = "candidate"
    CORE = "core"
    ENRICHED_OVERLAY = "enriched_overlay"
    WITHHELD = "withheld"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class Mention(FrozenContract):
    text: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    source_ids: tuple[SourceId, ...]
    normalized_name: str | None = None

    @model_validator(mode="after")
    def require_source(self) -> "Mention":
        if not self.source_ids:
            raise ValueError("claim mention requires source provenance")
        return self


class ClaimQualifier(FrozenContract):
    key: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    value: Annotated[str, StringConstraints(min_length=1, max_length=2048)]
    source_evidence_refs: tuple[EvidenceRef, ...]

    @model_validator(mode="after")
    def validate_evidence(self) -> "ClaimQualifier":
        require_evidence_namespace(
            self.source_evidence_refs,
            frozenset(
                {EvidenceNamespace.COURSEWARE, EvidenceNamespace.HUMAN}
            ),
            field_name="qualifier source_evidence_refs",
        )
        return self


class ClaimRecord(FrozenContract):
    claim_id: ClaimId
    leaf_region_id: RegionId
    claim_type: ClaimType
    normalized_text: Annotated[
        str,
        StringConstraints(min_length=1, max_length=8192),
    ]
    source_text: str
    subject_mentions: tuple[Mention, ...] = ()
    predicate: Annotated[
        str,
        StringConstraints(min_length=1, max_length=512),
    ]
    object_mentions: tuple[Mention, ...] = ()
    qualifiers: tuple[ClaimQualifier, ...] = ()
    instructional_role: InstructionalRole
    novelty: ClaimNovelty
    scope: ClaimScope
    source_evidence_refs: tuple[EvidenceRef, ...]
    external_evidence_refs: tuple[EvidenceRef, ...] = ()
    extraction_confidence: float = Field(ge=0, le=1)
    extraction_status: ExtractionStatus
    source_entailment_status: SourceEntailmentStatus
    external_validity_status: ExternalValidityStatus
    publication_status: ClaimPublicationStatus
    extractor: ArtifactProducerRef
    fidelity_verifier: ArtifactProducerRef | None = None
    external_resolver: ArtifactProducerRef | None = None
    duplicate_of: ClaimId | None = None
    review_of: tuple[ClaimId, ...] = ()
    decision_history: tuple[DecisionEvent, ...] = ()
    supersedes: ClaimId | None = None

    @model_validator(mode="after")
    def validate_claim_state(self) -> "ClaimRecord":
        if self.extractor.role is not RuntimeRole.CLAIM_ATOMIZER:
            raise ValueError("claim extractor must use claim_atomizer role")
        if self.fidelity_verifier:
            if self.fidelity_verifier.role is not (
                RuntimeRole.CLAIM_FIDELITY_VERIFIER
            ):
                raise ValueError(
                    "fidelity verifier must use claim_fidelity_verifier role"
                )
            if (
                self.fidelity_verifier.producer_id
                == self.extractor.producer_id
            ):
                raise ValueError(
                    "claim extractor cannot verify its own claim"
                )
        if self.external_resolver and self.external_resolver.role is not (
            RuntimeRole.DOMAIN_RESOLVER
        ):
            raise ValueError(
                "external resolver must use domain_resolver role"
            )
        require_evidence_namespace(
            self.source_evidence_refs,
            frozenset(
                {EvidenceNamespace.COURSEWARE, EvidenceNamespace.HUMAN}
            ),
            field_name="source_evidence_refs",
        )
        require_evidence_namespace(
            self.external_evidence_refs,
            frozenset({EvidenceNamespace.EXTERNAL}),
            field_name="external_evidence_refs",
        )
        if self.extraction_status in {
            ExtractionStatus.EXTRACTED,
            ExtractionStatus.PARTIAL,
        } and not self.source_evidence_refs:
            raise ValueError(
                "extracted claims require courseware source evidence"
            )
        if (
            self.source_entailment_status
            is not SourceEntailmentStatus.UNASSESSED
            and self.fidelity_verifier is None
        ):
            raise ValueError(
                "assessed source entailment requires a fidelity verifier"
            )
        if (
            self.external_validity_status
            is not ExternalValidityStatus.NOT_CHECKED
            and self.external_resolver is None
        ):
            raise ValueError(
                "assessed external validity requires a domain resolver"
            )
        if self.publication_status is ClaimPublicationStatus.CORE:
            if self.extraction_status not in {
                ExtractionStatus.EXTRACTED,
                ExtractionStatus.PARTIAL,
            }:
                raise ValueError(
                    "core claim must have been extracted from source"
                )
            if self.claim_type is ClaimType.INSTRUCTION:
                raise ValueError(
                    "instruction cannot be published as a core fact"
                )
            if not self.source_evidence_refs:
                raise ValueError("core claim cannot be external-only")
            if self.source_entailment_status not in {
                SourceEntailmentStatus.ENTAILED,
                SourceEntailmentStatus.PARTIAL,
            }:
                raise ValueError(
                    "core claim requires source entailment or partial support"
                )
            if self.novelty is ClaimNovelty.EXTERNAL_EXTENSION:
                raise ValueError(
                    "external extension cannot be published as a core claim"
                )
        if (
            self.publication_status
            is ClaimPublicationStatus.ENRICHED_OVERLAY
            and not self.external_evidence_refs
        ):
            raise ValueError(
                "enriched overlay claim requires external evidence"
            )
        if self.duplicate_of == self.claim_id:
            raise ValueError("claim cannot be a duplicate of itself")
        if self.supersedes == self.claim_id:
            raise ValueError("claim cannot supersede itself")
        return self


class ClaimLedger(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    ledger_id: LedgerId
    document_ir_ref: ArtifactRef
    region_plan_refs: tuple[ArtifactRef, ...]
    claims: tuple[ClaimRecord, ...]
    producer: ArtifactProducerRef
    unresolved_source_ids: tuple[SourceId, ...] = ()
    recorded_interaction_ids: tuple[RecordedInteractionId, ...] = ()
    supersedes: ArtifactRef | None = None

    @model_validator(mode="after")
    def validate_ledger(self) -> "ClaimLedger":
        if self.producer.role is not RuntimeRole.CLAIM_ATOMIZER:
            raise ValueError(
                "ClaimLedger producer must use claim_atomizer role"
            )
        if self.document_ir_ref.artifact_type.value != "source_observation_ir":
            raise ValueError(
                "document_ir_ref must reference SourceObservationIR"
            )
        if any(
            ref.artifact_type.value != "region_plan"
            for ref in self.region_plan_refs
        ):
            raise ValueError("region_plan_refs may only reference RegionPlan")
        require_artifact_type(
            self.supersedes,
            ArtifactType.CLAIM_LEDGER,
            field_name="supersedes",
        )
        owners = {
            self.document_ir_ref.owner_id,
            *(ref.owner_id for ref in self.region_plan_refs),
        }
        if self.supersedes:
            owners.add(self.supersedes.owner_id)
        if len(owners) != 1:
            raise ValueError("ClaimLedger references must remain owner-scoped")
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("ClaimLedger claim IDs must be unique")
        if len(self.unresolved_source_ids) != len(
            set(self.unresolved_source_ids)
        ):
            raise ValueError(
                "ClaimLedger unresolved source IDs must be unique"
            )
        if list(self.unresolved_source_ids) != sorted(
            self.unresolved_source_ids
        ):
            raise ValueError(
                "ClaimLedger unresolved source IDs must be sorted"
            )
        claimed_source_ids = {
            evidence.ref_id
            for claim in self.claims
            for evidence in claim.source_evidence_refs
        }
        overlap = claimed_source_ids & set(self.unresolved_source_ids)
        if overlap:
            raise ValueError(
                "ClaimLedger source IDs cannot be both claimed and "
                "unresolved: "
                + ", ".join(sorted(overlap))
            )
        if len(self.recorded_interaction_ids) != len(
            set(self.recorded_interaction_ids)
        ):
            raise ValueError(
                "ClaimLedger recorded interaction IDs must be unique"
            )
        if (
            self.recorded_interaction_ids
            and self.producer.prompt_digest is None
        ):
            raise ValueError(
                "recorded model claims require a prompt digest"
            )
        return self


class OmissionReason(FrozenContract):
    source_id: SourceId
    reason_code: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    explanation: Annotated[
        str,
        StringConstraints(min_length=1, max_length=2048),
    ]
    evidence_refs: tuple[EvidenceRef, ...]


class AuditorAttempt(FrozenContract):
    attempt: int = Field(ge=1)
    producer: ArtifactProducerRef
    input_digest: Annotated[
        str,
        StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$"),
    ]
    outcome: Literal["pass", "omission_found", "unresolved", "failed"]

    @model_validator(mode="after")
    def require_omission_auditor(self) -> "AuditorAttempt":
        if self.producer.role is not RuntimeRole.OMISSION_AUDITOR:
            raise ValueError(
                "auditor attempt must use omission_auditor role"
            )
        return self


class OmissionAudit(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    audit_id: AuditId
    source_inventory_ref: ArtifactRef
    claim_ledger_ref: ArtifactRef
    accounted_source_ids: tuple[SourceId, ...]
    omitted_source_ids: tuple[SourceId, ...]
    explicitly_nonclaim_source_ids: tuple[SourceId, ...]
    unresolved_source_ids: tuple[SourceId, ...]
    high_importance_omitted_source_ids: tuple[SourceId, ...] = ()
    must_have_recall: float = Field(ge=0, le=1)
    omission_reasons: tuple[OmissionReason, ...] = ()
    auditor_attempts: tuple[AuditorAttempt, ...]
    supersedes: ArtifactRef | None = None

    @model_validator(mode="after")
    def validate_audit_partition(self) -> "OmissionAudit":
        if self.source_inventory_ref.artifact_type.value != "source_inventory":
            raise ValueError(
                "source_inventory_ref must reference SourceInventory"
            )
        if self.claim_ledger_ref.artifact_type.value != "claim_ledger":
            raise ValueError(
                "claim_ledger_ref must reference ClaimLedger"
            )
        require_artifact_type(
            self.supersedes,
            ArtifactType.OMISSION_AUDIT,
            field_name="supersedes",
        )
        owners = {
            self.source_inventory_ref.owner_id,
            self.claim_ledger_ref.owner_id,
        }
        if self.supersedes:
            owners.add(self.supersedes.owner_id)
        if len(owners) != 1:
            raise ValueError("OmissionAudit references must remain owner-scoped")
        partitions = {
            "accounted": set(self.accounted_source_ids),
            "omitted": set(self.omitted_source_ids),
            "nonclaim": set(self.explicitly_nonclaim_source_ids),
            "unresolved": set(self.unresolved_source_ids),
        }
        names = tuple(partitions)
        for index, left in enumerate(names):
            for right in names[index + 1 :]:
                overlap = partitions[left] & partitions[right]
                if overlap:
                    raise ValueError(
                        f"omission audit partitions overlap between "
                        f"{left} and {right}: "
                        + ", ".join(sorted(overlap))
                    )
        if not set(self.high_importance_omitted_source_ids) <= partitions[
            "omitted"
        ]:
            raise ValueError(
                "high importance omissions must be included in omitted IDs"
            )
        reason_ids = {reason.source_id for reason in self.omission_reasons}
        missing_reasons = partitions["omitted"] - reason_ids
        if missing_reasons:
            raise ValueError(
                "every omitted source requires an omission reason: "
                + ", ".join(sorted(missing_reasons))
            )
        if not self.auditor_attempts:
            raise ValueError("OmissionAudit requires at least one attempt")
        require_evidence_namespace(
            tuple(
                ref
                for reason in self.omission_reasons
                for ref in reason.evidence_refs
            ),
            frozenset(
                {EvidenceNamespace.COURSEWARE, EvidenceNamespace.HUMAN}
            ),
            field_name="omission reason evidence",
        )
        return self
