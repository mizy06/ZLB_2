from __future__ import annotations

from enum import StrEnum
from typing import Annotated, ClassVar, Literal

from pydantic import StringConstraints, model_validator

from .base import FrozenContract
from .common import (
    ArtifactRef,
    ArtifactType,
    Sha256Digest,
    SourceId,
    require_artifact_type,
)
from .evidence import EvidenceNamespace, EvidenceRef, require_evidence_namespace


InventoryId = Annotated[
    str,
    StringConstraints(pattern=r"^inventory_[0-9a-f]{32}$"),
]
InventoryEntryId = Annotated[
    str,
    StringConstraints(pattern=r"^inventory_entry_[0-9a-f]{32}$"),
]


class InventoryEntryKind(StrEnum):
    PAGE = "page"
    BLOCK = "block"
    TABLE_CELL = "table_cell"
    FORMULA_REGION = "formula_region"
    REACTION_REGION = "reaction_region"
    VISUAL_REGION = "visual_region"
    OUTLINE = "outline"
    UNRESOLVED = "unresolved"


class InventoryImportance(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    MUST_HAVE = "must_have"


class InventoryInspectionStatus(StrEnum):
    MUST_INSPECT = "must_inspect"
    UNRESOLVED = "unresolved"
    HUMAN_MUST_HAVE = "human_must_have"


class InventoryEntry(FrozenContract):
    inventory_entry_id: InventoryEntryId
    source_id: SourceId
    source_kind: InventoryEntryKind
    page_id: SourceId | None = None
    importance: InventoryImportance = InventoryImportance.NORMAL
    inspection_status: InventoryInspectionStatus = (
        InventoryInspectionStatus.MUST_INSPECT
    )
    declared_role: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ] | None = None
    evidence_refs: tuple[EvidenceRef, ...]

    @model_validator(mode="after")
    def validate_evidence(self) -> "InventoryEntry":
        require_evidence_namespace(
            self.evidence_refs,
            frozenset(
                {
                    EvidenceNamespace.COURSEWARE,
                    EvidenceNamespace.HUMAN,
                    EvidenceNamespace.SYSTEM,
                }
            ),
            field_name="inventory entry evidence_refs",
        )
        return self


class HumanMustHaveRef(FrozenContract):
    human_ref: EvidenceRef
    source_ids: tuple[SourceId, ...]
    rationale: Annotated[
        str,
        StringConstraints(min_length=1, max_length=2048),
    ]

    @model_validator(mode="after")
    def require_human_namespace(self) -> "HumanMustHaveRef":
        if self.human_ref.namespace is not EvidenceNamespace.HUMAN:
            raise ValueError("human_ref must use the human evidence namespace")
        if not self.source_ids:
            raise ValueError("human must-have reference requires source IDs")
        return self


class RawSourceManifest(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    source_hash: Sha256Digest
    source_format: Annotated[
        str,
        StringConstraints(min_length=1, max_length=32),
    ]
    inspector_policy_version: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    parser_major: int
    native_page_count: int | None = None
    rendered_page_count: int | None = None
    parser_page_count: int
    native_object_count: int | None = None
    parser_object_count: int
    native_outline_count: int | None = None
    parser_outline_count: int
    hidden_page_count: int = 0
    parser_hidden_page_count: int = 0
    notes_count: int = 0
    parser_notes_count: int = 0
    alt_text_count: int = 0
    parser_alt_text_count: int = 0
    off_slide_object_count: int = 0
    parser_off_slide_object_count: int = 0
    package_entry_count: int | None = None
    unresolved_checks: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=128)],
        ...,
    ] = ()
    mismatch_codes: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=128)],
        ...,
    ] = ()

    @model_validator(mode="after")
    def validate_manifest(self) -> "RawSourceManifest":
        count_fields = (
            self.native_page_count,
            self.rendered_page_count,
            self.parser_page_count,
            self.native_object_count,
            self.parser_object_count,
            self.native_outline_count,
            self.parser_outline_count,
            self.hidden_page_count,
            self.parser_hidden_page_count,
            self.notes_count,
            self.parser_notes_count,
            self.alt_text_count,
            self.parser_alt_text_count,
            self.off_slide_object_count,
            self.parser_off_slide_object_count,
            self.package_entry_count,
        )
        if any(value is not None and value < 0 for value in count_fields):
            raise ValueError("raw source manifest counts cannot be negative")
        for values, label in (
            (self.unresolved_checks, "unresolved checks"),
            (self.mismatch_codes, "mismatch codes"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"raw source manifest {label} must be unique")
            if values != tuple(sorted(values)):
                raise ValueError(
                    f"raw source manifest {label} must be deterministic"
                )
        return self


class SourceInventory(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    inventory_id: InventoryId
    document_ir_ref: ArtifactRef
    raw_manifest: RawSourceManifest
    page_entries: tuple[InventoryEntry, ...]
    block_entries: tuple[InventoryEntry, ...] = ()
    table_cell_entries: tuple[InventoryEntry, ...] = ()
    formula_region_entries: tuple[InventoryEntry, ...] = ()
    reaction_region_entries: tuple[InventoryEntry, ...] = ()
    visual_region_entries: tuple[InventoryEntry, ...] = ()
    outline_entries: tuple[InventoryEntry, ...] = ()
    unresolved_entries: tuple[InventoryEntry, ...] = ()
    human_must_have_refs: tuple[HumanMustHaveRef, ...] = ()
    inventory_policy_version: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    supersedes: ArtifactRef | None = None

    _ENTRY_FIELDS: ClassVar[tuple[tuple[str, InventoryEntryKind], ...]] = (
        ("page_entries", InventoryEntryKind.PAGE),
        ("block_entries", InventoryEntryKind.BLOCK),
        ("table_cell_entries", InventoryEntryKind.TABLE_CELL),
        ("formula_region_entries", InventoryEntryKind.FORMULA_REGION),
        ("reaction_region_entries", InventoryEntryKind.REACTION_REGION),
        ("visual_region_entries", InventoryEntryKind.VISUAL_REGION),
        ("outline_entries", InventoryEntryKind.OUTLINE),
        ("unresolved_entries", InventoryEntryKind.UNRESOLVED),
    )

    def all_entries(self) -> tuple[InventoryEntry, ...]:
        return tuple(
            entry
            for field_name, _ in self._ENTRY_FIELDS
            for entry in getattr(self, field_name)
        )

    @model_validator(mode="after")
    def validate_inventory(self) -> "SourceInventory":
        if (
            self.document_ir_ref.artifact_type.value
            != "source_observation_ir"
        ):
            raise ValueError(
                "document_ir_ref must reference SourceObservationIR"
            )
        require_artifact_type(
            self.supersedes,
            ArtifactType.SOURCE_INVENTORY,
            field_name="supersedes",
        )
        if self.supersedes and self.supersedes.owner_id != (
            self.document_ir_ref.owner_id
        ):
            raise ValueError("inventory supersedes must remain owner-scoped")
        entries = self.all_entries()
        if not self.page_entries:
            raise ValueError("inventory must retain every page")
        entry_ids = [entry.inventory_entry_id for entry in entries]
        source_ids = [entry.source_id for entry in entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("inventory entry IDs must be unique")
        if len(source_ids) != len(set(source_ids)):
            raise ValueError(
                "each source object must have exactly one inventory entry"
            )
        for field_name, expected_kind in self._ENTRY_FIELDS:
            for entry in getattr(self, field_name):
                if entry.source_kind is not expected_kind:
                    raise ValueError(
                        f"{field_name} can only contain "
                        f"{expected_kind.value} entries"
                    )
        known_source_ids = set(source_ids)
        for must_have in self.human_must_have_refs:
            unknown = set(must_have.source_ids) - known_source_ids
            if unknown:
                raise ValueError(
                    "human must-have references unknown source IDs: "
                    + ", ".join(sorted(unknown))
                )
        return self
