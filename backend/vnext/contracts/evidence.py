from __future__ import annotations

from enum import StrEnum
import re
from typing import Annotated

from pydantic import GetJsonSchemaHandler, StringConstraints, model_validator
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema

from .base import FrozenContract
from .common import ArtifactRef, Sha256Digest


class EvidenceNamespace(StrEnum):
    COURSEWARE = "courseware"
    EXTERNAL = "external"
    HUMAN = "human"
    SYSTEM = "system"


EvidenceId = Annotated[
    str,
    StringConstraints(min_length=6, max_length=256),
]


class EvidenceRef(FrozenContract):
    namespace: EvidenceNamespace
    ref_id: EvidenceId
    artifact_ref: ArtifactRef | None = None
    content_digest: Sha256Digest | None = None

    @model_validator(mode="after")
    def require_namespace_prefix(self) -> "EvidenceRef":
        patterns = {
            EvidenceNamespace.COURSEWARE: (
                r"^src:[a-z][a-z0-9_-]{1,31}:[0-9a-f]{64}$"
            ),
            EvidenceNamespace.EXTERNAL: (
                r"^ext:[A-Za-z0-9][A-Za-z0-9._:/-]{1,251}$"
            ),
            EvidenceNamespace.HUMAN: (
                r"^human:[A-Za-z0-9][A-Za-z0-9._:@/-]{1,249}$"
            ),
            EvidenceNamespace.SYSTEM: (
                r"^sys:[A-Za-z0-9][A-Za-z0-9._:@/-]{1,251}$"
            ),
        }[self.namespace]
        if not re.fullmatch(patterns, self.ref_id):
            raise ValueError(
                f"invalid {self.namespace.value} evidence identifier"
            )
        return self

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        schema = handler(core_schema)
        conditions = (
            (
                EvidenceNamespace.COURSEWARE.value,
                r"^src:[a-z][a-z0-9_-]{1,31}:[0-9a-f]{64}$",
            ),
            (
                EvidenceNamespace.EXTERNAL.value,
                r"^ext:[A-Za-z0-9][A-Za-z0-9._:/-]{1,251}$",
            ),
            (
                EvidenceNamespace.HUMAN.value,
                r"^human:[A-Za-z0-9][A-Za-z0-9._:@/-]{1,249}$",
            ),
            (
                EvidenceNamespace.SYSTEM.value,
                r"^sys:[A-Za-z0-9][A-Za-z0-9._:@/-]{1,251}$",
            ),
        )
        schema["allOf"] = [
            {
                "if": {
                    "properties": {"namespace": {"const": namespace}},
                    "required": ["namespace"],
                },
                "then": {
                    "properties": {"ref_id": {"pattern": pattern}},
                },
            }
            for namespace, pattern in conditions
        ]
        return schema


def require_evidence_namespace(
    refs: tuple[EvidenceRef, ...],
    allowed: frozenset[EvidenceNamespace],
    *,
    field_name: str,
) -> None:
    invalid = sorted(
        {
            ref.namespace.value
            for ref in refs
            if ref.namespace not in allowed
        }
    )
    if invalid:
        raise ValueError(
            f"{field_name} contains forbidden evidence namespaces: "
            f"{', '.join(invalid)}"
        )
