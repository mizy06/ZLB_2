from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator

from .base import FrozenContract


SemVer = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$"),
]
Sha256Digest = Annotated[
    str,
    StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$"),
]
SourceId = Annotated[
    str,
    StringConstraints(
        pattern=r"^src:[a-z][a-z0-9_-]{1,31}:[0-9a-f]{64}$"
    ),
]
ArtifactId = Annotated[
    str,
    StringConstraints(pattern=r"^art_[0-9a-f]{32}$"),
]
RegionId = Annotated[
    str,
    StringConstraints(pattern=r"^reg_[0-9a-f]{32}$"),
]
ClaimId = Annotated[
    str,
    StringConstraints(pattern=r"^claim_[0-9a-f]{32}$"),
]
ConceptId = Annotated[
    str,
    StringConstraints(pattern=r"^concept_[0-9a-f]{32}$"),
]
RelationId = Annotated[
    str,
    StringConstraints(pattern=r"^relation_[0-9a-f]{32}$"),
]
ProjectionId = Annotated[
    str,
    StringConstraints(pattern=r"^projection_[0-9a-f]{32}$"),
]
RequestId = Annotated[
    str,
    StringConstraints(pattern=r"^replan_[0-9a-f]{32}$"),
]
OwnerId = Annotated[str, StringConstraints(min_length=1, max_length=256)]
SchemaId = Annotated[
    str,
    StringConstraints(pattern=r"^urn:zlb:vnext:schema:[a-z0-9-]+:[0-9.]+$"),
]


class ArtifactType(StrEnum):
    SOURCE_OBSERVATION_IR = "source_observation_ir"
    SOURCE_INVENTORY = "source_inventory"
    REGION_PLAN = "region_plan"
    REGION_SPLIT_CERTIFICATE = "region_split_certificate"
    REPLAN_REQUEST = "replan_request"
    CLAIM_LEDGER = "claim_ledger"
    OMISSION_AUDIT = "omission_audit"
    CANONICAL_EXPLICIT_GRAPH = "canonical_explicit_graph"
    DIAGNOSTIC_PROJECTION = "diagnostic_projection"


class RuntimeRole(StrEnum):
    RUN_GOVERNOR = "run_governor"
    DOCUMENT_INTERPRETER = "document_interpreter"
    SOURCE_INVENTORY_AUDITOR = "source_inventory_auditor"
    GLOBAL_STRUCTURE_PLANNER = "global_structure_planner"
    RECURSIVE_REGION_PLANNER = "recursive_region_planner"
    REGION_DECISION_VERIFIER = "region_decision_verifier"
    CLAIM_ATOMIZER = "claim_atomizer"
    OMISSION_AUDITOR = "omission_auditor"
    BOTTOM_UP_REGION_AUDITOR = "bottom_up_region_auditor"
    CLAIM_FIDELITY_VERIFIER = "claim_fidelity_verifier"
    DOMAIN_RESOLVER = "domain_resolver"
    CANONICALIZER = "canonicalizer"
    RELATION_VERIFIER_A = "relation_verifier_a"
    RELATION_VERIFIER_B = "relation_verifier_b"
    ARBITER = "arbiter"
    QUALITY_AUDITOR = "quality_auditor"
    PROJECTION_PLANNER = "projection_planner"


ARTIFACT_WRITERS: dict[ArtifactType, frozenset[RuntimeRole]] = {
    ArtifactType.SOURCE_OBSERVATION_IR: frozenset(
        {RuntimeRole.DOCUMENT_INTERPRETER}
    ),
    ArtifactType.SOURCE_INVENTORY: frozenset(
        {RuntimeRole.SOURCE_INVENTORY_AUDITOR}
    ),
    ArtifactType.REGION_PLAN: frozenset(
        {
            RuntimeRole.GLOBAL_STRUCTURE_PLANNER,
            RuntimeRole.RECURSIVE_REGION_PLANNER,
        }
    ),
    ArtifactType.REGION_SPLIT_CERTIFICATE: frozenset(
        {RuntimeRole.REGION_DECISION_VERIFIER}
    ),
    ArtifactType.REPLAN_REQUEST: frozenset(
        {RuntimeRole.BOTTOM_UP_REGION_AUDITOR}
    ),
    ArtifactType.CLAIM_LEDGER: frozenset({RuntimeRole.CLAIM_ATOMIZER}),
    ArtifactType.OMISSION_AUDIT: frozenset(
        {RuntimeRole.OMISSION_AUDITOR}
    ),
    ArtifactType.CANONICAL_EXPLICIT_GRAPH: frozenset(
        {RuntimeRole.CANONICALIZER}
    ),
    ArtifactType.DIAGNOSTIC_PROJECTION: frozenset(
        {RuntimeRole.PROJECTION_PLANNER}
    ),
}


class InterpretationStatus(StrEnum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    CONTESTED = "contested"
    HUMAN_CONFIRMED = "human_confirmed"
    REJECTED = "rejected"


class ArtifactRef(FrozenContract):
    owner_id: OwnerId
    artifact_id: ArtifactId
    artifact_type: ArtifactType
    payload_digest: Sha256Digest


def require_artifact_type(
    ref: ArtifactRef | None,
    expected: ArtifactType,
    *,
    field_name: str,
) -> None:
    if ref is not None and ref.artifact_type is not expected:
        raise ValueError(
            f"{field_name} must reference {expected.value}"
        )


class ProducerRef(FrozenContract):
    producer_id: Annotated[
        str,
        StringConstraints(min_length=1, max_length=160),
    ]
    producer_version: SemVer
    model_revision: str | None = Field(default=None, max_length=256)
    prompt_digest: Sha256Digest | None = None


class ArtifactProducerRef(ProducerRef):
    role: RuntimeRole


class DecisionEvent(FrozenContract):
    decision_id: Annotated[
        str,
        StringConstraints(pattern=r"^decision_[0-9a-f]{32}$"),
    ]
    actor: RuntimeRole | Annotated[
        str,
        StringConstraints(pattern=r"^human:[A-Za-z0-9._:@-]{1,128}$"),
    ]
    decision: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    reason_codes: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=128)],
        ...,
    ] = ()
    evidence_refs: tuple["EvidenceRef", ...] = ()
    created_at: datetime
    supersedes: Annotated[
        str,
        StringConstraints(pattern=r"^decision_[0-9a-f]{32}$"),
    ] | None = None

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value


class StringValue(FrozenContract):
    key: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    value: Annotated[str, StringConstraints(max_length=4096)]


from .evidence import EvidenceRef  # noqa: E402

DecisionEvent.model_rebuild()
