from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import (
    GetJsonSchemaHandler,
    field_validator,
    model_validator,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema

from .base import FrozenContract
from .common import (
    ARTIFACT_WRITERS,
    ArtifactId,
    ArtifactProducerRef,
    ArtifactRef,
    ArtifactType,
    OwnerId,
    SchemaId,
    SemVer,
    Sha256Digest,
)
from .evidence import (
    EvidenceNamespace,
    EvidenceRef,
    require_evidence_namespace,
)

_SCHEMA_BINDINGS = {
    ArtifactType.SOURCE_OBSERVATION_IR: (
        "urn:zlb:vnext:schema:source-observation-ir:1.0.0",
        "1.0.0",
    ),
    ArtifactType.SOURCE_INVENTORY: (
        "urn:zlb:vnext:schema:source-inventory:1.0.0",
        "1.0.0",
    ),
    ArtifactType.REGION_PLAN: (
        "urn:zlb:vnext:schema:region-plan:1.0.0",
        "1.0.0",
    ),
    ArtifactType.REGION_SPLIT_CERTIFICATE: (
        "urn:zlb:vnext:schema:region-split-certificate:1.0.0",
        "1.0.0",
    ),
    ArtifactType.REPLAN_REQUEST: (
        "urn:zlb:vnext:schema:replan-request:1.0.0",
        "1.0.0",
    ),
    ArtifactType.CLAIM_LEDGER: (
        "urn:zlb:vnext:schema:claim-ledger:1.0.0",
        "1.0.0",
    ),
    ArtifactType.OMISSION_AUDIT: (
        "urn:zlb:vnext:schema:omission-audit:1.0.0",
        "1.0.0",
    ),
    ArtifactType.CANONICAL_EXPLICIT_GRAPH: (
        "urn:zlb:vnext:schema:canonical-explicit-graph:0.1.0",
        "0.1.0",
    ),
    ArtifactType.DIAGNOSTIC_PROJECTION: (
        "urn:zlb:vnext:schema:diagnostic-projection:0.1.0",
        "0.1.0",
    ),
}


class ArtifactEnvelope(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    artifact_id: ArtifactId
    artifact_type: ArtifactType
    schema_id: SchemaId
    payload_schema_version: SemVer
    owner_id: OwnerId
    payload_digest: Sha256Digest
    canonicalization_profile: Literal["RFC8785"] = "RFC8785"
    producer: ArtifactProducerRef
    input_refs: tuple[ArtifactRef, ...] = ()
    external_snapshot_refs: tuple[EvidenceRef, ...] = ()
    created_at: datetime
    supersedes: ArtifactRef | None = None

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value

    @model_validator(mode="after")
    def enforce_owner_scope(self) -> "ArtifactEnvelope":
        expected_schema_id, expected_version = _SCHEMA_BINDINGS[
            self.artifact_type
        ]
        if (
            self.schema_id != expected_schema_id
            or self.payload_schema_version != expected_version
        ):
            raise ValueError(
                "artifact_type, schema_id, and payload_schema_version "
                "must identify the same contract"
            )
        if self.producer.role not in ARTIFACT_WRITERS[self.artifact_type]:
            raise ValueError(
                f"{self.producer.role.value} cannot produce "
                f"{self.artifact_type.value}"
            )
        foreign = [
            ref.artifact_id
            for ref in self.input_refs
            if ref.owner_id != self.owner_id
        ]
        if self.supersedes and self.supersedes.owner_id != self.owner_id:
            foreign.append(self.supersedes.artifact_id)
        if foreign:
            raise ValueError(
                "artifact references must remain within the envelope owner: "
                + ", ".join(sorted(foreign))
            )
        input_ids = [ref.artifact_id for ref in self.input_refs]
        if len(input_ids) != len(set(input_ids)):
            raise ValueError("input_refs cannot contain duplicate artifacts")
        if self.artifact_id in input_ids:
            raise ValueError("artifact cannot list itself as an input")
        if self.supersedes:
            if self.supersedes.artifact_id == self.artifact_id:
                raise ValueError("artifact cannot supersede itself")
            if self.supersedes.artifact_type is not self.artifact_type:
                raise ValueError(
                    "supersedes must reference the same artifact type"
                )
        require_evidence_namespace(
            self.external_snapshot_refs,
            frozenset({EvidenceNamespace.EXTERNAL}),
            field_name="external_snapshot_refs",
        )
        for ref in self.external_snapshot_refs:
            if ref.artifact_ref and ref.artifact_ref.owner_id != self.owner_id:
                raise ValueError(
                    "external snapshot references must remain owner-scoped"
                )
        snapshot_ids = [
            ref.ref_id for ref in self.external_snapshot_refs
        ]
        if len(snapshot_ids) != len(set(snapshot_ids)):
            raise ValueError(
                "external_snapshot_refs cannot contain duplicates"
            )
        return self

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        schema = handler(core_schema)
        schema["allOf"] = [
            {
                "if": {
                    "properties": {
                        "artifact_type": {
                            "const": artifact_type.value,
                        }
                    },
                    "required": ["artifact_type"],
                },
                "then": {
                    "properties": {
                        "schema_id": {"const": schema_id},
                        "payload_schema_version": {
                            "const": version,
                        },
                        "producer": {
                            "properties": {
                                "role": {
                                    "enum": sorted(
                                        role.value
                                        for role in ARTIFACT_WRITERS[
                                            artifact_type
                                        ]
                                    )
                                }
                            },
                            "required": ["role"],
                        },
                    }
                },
            }
            for artifact_type, (schema_id, version) in (
                _SCHEMA_BINDINGS.items()
            )
        ]
        return schema
