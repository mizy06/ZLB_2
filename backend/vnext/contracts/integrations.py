from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from .base import FrozenContract
from .common import (
    OwnerId,
    RuntimeRole,
    Sha256Digest,
    StringValue,
)
from .control import RunId, StageKey
from .evidence import EvidenceNamespace, EvidenceRef


InteractionId = Annotated[
    str,
    StringConstraints(pattern=r"^interaction_[0-9a-f]{32}$"),
]
SearchIntentId = Annotated[
    str,
    StringConstraints(pattern=r"^search_intent_[0-9a-f]{32}$"),
]
EvidenceBundleId = Annotated[
    str,
    StringConstraints(pattern=r"^evidence_bundle_[0-9a-f]{32}$"),
]
SnapshotId = Annotated[
    str,
    StringConstraints(pattern=r"^snapshot_[0-9a-f]{32}$"),
]


class RecordedInteraction(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    interaction_id: InteractionId
    run_id: RunId
    owner_id: OwnerId
    stage_key: StageKey
    role: RuntimeRole
    provider: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    model_revision: Annotated[
        str,
        StringConstraints(min_length=1, max_length=256),
    ]
    request_ref: EvidenceRef
    response_ref: EvidenceRef
    tool_result_refs: tuple[EvidenceRef, ...] = ()
    request_digest: Sha256Digest
    response_digest: Sha256Digest
    tool_result_digests: tuple[Sha256Digest, ...] = ()
    provider_metadata: tuple[StringValue, ...] = ()
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("interaction timestamp requires timezone")
        return value

    @model_validator(mode="after")
    def validate_snapshot_refs(self) -> "RecordedInteraction":
        refs = (
            self.request_ref,
            self.response_ref,
            *self.tool_result_refs,
        )
        if any(ref.namespace is not EvidenceNamespace.SYSTEM for ref in refs):
            raise ValueError(
                "recorded interaction payload refs must use system namespace"
            )
        if len(self.tool_result_refs) != len(self.tool_result_digests):
            raise ValueError(
                "tool result refs and digests must have equal length"
            )
        return self


class EvidencePurpose(StrEnum):
    DISAMBIGUATE = "disambiguate"
    NORMALIZE = "normalize"
    CONFLICT_CHECK = "conflict_check"
    EXTEND = "extend"


class DataClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class ExternalRelation(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    DISAMBIGUATES = "disambiguates"
    NORMALIZES = "normalizes"
    EXTENDS = "extends"
    UNRESOLVED = "unresolved"


class SearchIntent(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    intent_id: SearchIntentId
    run_id: RunId
    owner_id: OwnerId
    agent_role: RuntimeRole
    question: Annotated[
        str,
        StringConstraints(min_length=1, max_length=1024),
    ]
    query_candidates: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=256)],
        ...,
    ] = Field(min_length=1, max_length=12)
    allowed_domains: tuple[str, ...] = ()
    blocked_domains: tuple[str, ...] = ()
    evidence_purpose: EvidencePurpose
    trigger_code: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    tenant_consent_ref: EvidenceRef | None = None
    data_classification: DataClassification
    redaction_policy: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    max_queries: int = Field(ge=1, le=36)
    max_fetches: int = Field(ge=1, le=72)
    freshness_hours: int | None = Field(default=None, ge=1)
    source_priority: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_search_intent(self) -> "SearchIntent":
        overlap = {
            domain.casefold() for domain in self.allowed_domains
        } & {domain.casefold() for domain in self.blocked_domains}
        if overlap:
            raise ValueError(
                "allowed and blocked search domains must be disjoint"
            )
        if (
            self.tenant_consent_ref is not None
            and self.tenant_consent_ref.namespace
            is not EvidenceNamespace.HUMAN
        ):
            raise ValueError(
                "tenant consent must use the human evidence namespace"
            )
        return self


class SearchQueryRecord(FrozenContract):
    query: Annotated[
        str,
        StringConstraints(min_length=1, max_length=256),
    ]
    result_count: int = Field(ge=0)
    executed_at: datetime

    @field_validator("executed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("search query timestamp requires timezone")
        return value


class FetchSnapshot(FrozenContract):
    snapshot_id: SnapshotId
    canonical_url: Annotated[
        str,
        StringConstraints(min_length=8, max_length=2048),
    ]
    resolved_ip: Annotated[
        str,
        StringConstraints(min_length=2, max_length=64),
    ]
    status_code: int = Field(ge=100, le=599)
    mime_type: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    content_hash: Sha256Digest
    sanitized_content_ref: EvidenceRef
    byte_count: int = Field(ge=0)
    redirect_chain: tuple[str, ...] = ()
    fetched_at: datetime
    sanitizer_version: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    injection_signals: tuple[str, ...] = ()

    @field_validator("fetched_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fetch timestamp requires timezone")
        return value

    @model_validator(mode="after")
    def require_system_snapshot_ref(self) -> "FetchSnapshot":
        if (
            self.sanitized_content_ref.namespace
            is not EvidenceNamespace.SYSTEM
        ):
            raise ValueError(
                "sanitized snapshot content must use system namespace"
            )
        return self


class ExternalEvidenceRecord(FrozenContract):
    external_ref_id: EvidenceRef
    snapshot_id: SnapshotId
    canonical_url: Annotated[
        str,
        StringConstraints(min_length=8, max_length=2048),
    ]
    publisher: Annotated[
        str,
        StringConstraints(min_length=1, max_length=256),
    ]
    title: Annotated[
        str,
        StringConstraints(min_length=1, max_length=512),
    ]
    published_at: datetime | None = None
    fetched_at: datetime
    content_hash: Sha256Digest
    quote_span: Annotated[
        str,
        StringConstraints(min_length=1, max_length=1024),
    ]
    relation_to_claim: ExternalRelation
    trust_tier: Literal["primary", "authoritative", "secondary", "unknown"]
    license_note: Annotated[
        str,
        StringConstraints(min_length=1, max_length=512),
    ]

    @field_validator("published_at", "fetched_at")
    @classmethod
    def require_timezone(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError("external evidence timestamps require timezone")
        return value

    @model_validator(mode="after")
    def require_external_namespace(self) -> "ExternalEvidenceRecord":
        if self.external_ref_id.namespace is not EvidenceNamespace.EXTERNAL:
            raise ValueError(
                "external evidence record requires external namespace"
            )
        return self


class SearchBudgetUsage(FrozenContract):
    queries: int = Field(ge=0)
    fetches: int = Field(ge=0)
    downloaded_bytes: int = Field(ge=0)


class EvidenceBundle(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    bundle_id: EvidenceBundleId
    intent_id: SearchIntentId
    run_id: RunId
    owner_id: OwnerId
    decision: Literal["allowed", "denied", "partial"]
    denial_reasons: tuple[str, ...] = ()
    query_log: tuple[SearchQueryRecord, ...] = ()
    results: tuple[ExternalEvidenceRecord, ...] = ()
    fetch_snapshots: tuple[FetchSnapshot, ...] = ()
    conflicts: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    budget_usage: SearchBudgetUsage
    gateway_policy_version: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]

    @model_validator(mode="after")
    def validate_bundle(self) -> "EvidenceBundle":
        if self.decision == "denied" and not self.denial_reasons:
            raise ValueError("denied evidence bundle requires reasons")
        if self.decision == "denied" and (
            self.results or self.fetch_snapshots
        ):
            raise ValueError("denied search cannot contain fetched evidence")
        snapshot_ids = {
            snapshot.snapshot_id for snapshot in self.fetch_snapshots
        }
        if any(
            result.snapshot_id not in snapshot_ids for result in self.results
        ):
            raise ValueError(
                "external evidence must reference a retained snapshot"
            )
        return self
