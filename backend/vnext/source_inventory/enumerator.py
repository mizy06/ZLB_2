from __future__ import annotations

import hashlib
from pathlib import Path

from backend.vnext.artifacts.canonical import canonical_json_bytes
from backend.vnext.contracts.common import ArtifactRef
from backend.vnext.contracts.evidence import EvidenceNamespace, EvidenceRef
from backend.vnext.contracts.inventory import (
    InventoryEntry,
    InventoryEntryKind,
    InventoryImportance,
    InventoryInspectionStatus,
    RawSourceManifest,
    SourceInventory,
)
from backend.vnext.contracts.source import (
    BlockIR,
    BlockKind,
    NativeObjectIR,
    NativeObjectKind,
    OutlineEntryIR,
    PageIR,
    SourceObservationIR,
    UnresolvedRegionIR,
)

from .raw_manifest import inspect_raw_source


INVENTORY_POLICY_VERSION = "source-inventory-v1"


def _stable_token(prefix: str, value: object) -> str:
    digest = hashlib.sha256(
        b"zlb-vnext-inventory-v1\0" + canonical_json_bytes(value)
    ).hexdigest()
    return prefix + digest[:32]


def _evidence(
    source_id: str,
    existing: tuple[EvidenceRef, ...],
) -> tuple[EvidenceRef, ...]:
    if existing:
        return existing
    return (
        EvidenceRef(
            namespace=EvidenceNamespace.COURSEWARE,
            ref_id=source_id,
        ),
    )


def _importance_for_block(block: BlockIR) -> InventoryImportance:
    if block.kind in {
        BlockKind.TITLE,
        BlockKind.HEADING,
        BlockKind.FORMULA_TEXT,
        BlockKind.REACTION_TEXT,
    }:
        return InventoryImportance.HIGH
    if len(block.text.strip()) >= 240:
        return InventoryImportance.HIGH
    return InventoryImportance.NORMAL


def _importance_for_object(
    obj: NativeObjectIR,
) -> InventoryImportance:
    if obj.kind in {
        NativeObjectKind.FORMULA,
        NativeObjectKind.CHEMICAL_REACTION,
        NativeObjectKind.TABLE,
        NativeObjectKind.CHART,
    }:
        return InventoryImportance.HIGH
    return InventoryImportance.NORMAL


def _inspection_for_object(
    obj: NativeObjectIR,
) -> InventoryInspectionStatus:
    if obj.formula and obj.formula.parse_status != "parsed":
        return InventoryInspectionStatus.UNRESOLVED
    if obj.reaction and obj.reaction.parse_status != "parsed":
        return InventoryInspectionStatus.UNRESOLVED
    return InventoryInspectionStatus.MUST_INSPECT


def _entry(
    *,
    source_hash: str,
    source_id: str,
    kind: InventoryEntryKind,
    page_id: str | None,
    importance: InventoryImportance,
    inspection_status: InventoryInspectionStatus,
    declared_role: str | None,
    evidence_refs: tuple[EvidenceRef, ...],
) -> InventoryEntry:
    return InventoryEntry(
        inventory_entry_id=_stable_token(
            "inventory_entry_",
            {
                "policy": INVENTORY_POLICY_VERSION,
                "source_hash": source_hash,
                "source_id": source_id,
                "source_kind": kind.value,
            },
        ),
        source_id=source_id,
        source_kind=kind,
        page_id=page_id,
        importance=importance,
        inspection_status=inspection_status,
        declared_role=declared_role,
        evidence_refs=_evidence(source_id, evidence_refs),
    )


def _page_entry(
    source: SourceObservationIR,
    page: PageIR,
) -> InventoryEntry:
    return _entry(
        source_hash=source.source_hash,
        source_id=page.page_id,
        kind=InventoryEntryKind.PAGE,
        page_id=page.page_id,
        importance=InventoryImportance.NORMAL,
        inspection_status=InventoryInspectionStatus.MUST_INSPECT,
        declared_role="page",
        evidence_refs=(page.render_ref,),
    )


def _block_entry(
    source: SourceObservationIR,
    block: BlockIR,
) -> InventoryEntry:
    return _entry(
        source_hash=source.source_hash,
        source_id=block.block_id,
        kind=InventoryEntryKind.BLOCK,
        page_id=block.page_id,
        importance=_importance_for_block(block),
        inspection_status=InventoryInspectionStatus.MUST_INSPECT,
        declared_role=block.kind.value,
        evidence_refs=block.evidence_refs,
    )


def _outline_entry(
    source: SourceObservationIR,
    item: OutlineEntryIR,
) -> InventoryEntry:
    return _entry(
        source_hash=source.source_hash,
        source_id=item.outline_entry_id,
        kind=InventoryEntryKind.OUTLINE,
        page_id=item.target_page_id,
        importance=InventoryImportance.HIGH,
        inspection_status=InventoryInspectionStatus.MUST_INSPECT,
        declared_role=f"outline_level_{item.observed_level}",
        evidence_refs=item.evidence_refs,
    )


def _unresolved_entry(
    source: SourceObservationIR,
    item: UnresolvedRegionIR,
) -> InventoryEntry:
    return _entry(
        source_hash=source.source_hash,
        source_id=item.region_source_id,
        kind=InventoryEntryKind.UNRESOLVED,
        page_id=item.page_id,
        importance=InventoryImportance.HIGH,
        inspection_status=InventoryInspectionStatus.UNRESOLVED,
        declared_role=item.reason_code,
        evidence_refs=item.evidence_refs,
    )


def _integrity_entry(
    source: SourceObservationIR,
    code: str,
) -> InventoryEntry:
    source_digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "code": code,
                "source_hash": source.source_hash,
            }
        )
    ).hexdigest()
    source_id = f"src:integrity:{source_digest}"
    return _entry(
        source_hash=source.source_hash,
        source_id=source_id,
        kind=InventoryEntryKind.UNRESOLVED,
        page_id=None,
        importance=InventoryImportance.MUST_HAVE,
        inspection_status=InventoryInspectionStatus.UNRESOLVED,
        declared_role=code,
        evidence_refs=(
            EvidenceRef(
                namespace=EvidenceNamespace.SYSTEM,
                ref_id=f"sys:source-integrity:{source_digest}",
                content_digest=source.source_hash,
            ),
        ),
    )


def enumerate_source_inventory(
    source: SourceObservationIR,
    *,
    source_path: Path,
    document_ir_ref: ArtifactRef,
) -> SourceInventory:
    """Enumerate the source denominator without reading any claim output."""

    raw_manifest: RawSourceManifest = inspect_raw_source(source_path, source)
    page_entries = tuple(_page_entry(source, page) for page in source.pages)
    block_entries = tuple(
        _block_entry(source, block)
        for page in source.pages
        for block in page.blocks
    )
    table_cell_entries: list[InventoryEntry] = []
    formula_entries: list[InventoryEntry] = []
    reaction_entries: list[InventoryEntry] = []
    visual_entries: list[InventoryEntry] = []
    for page in source.pages:
        for obj in page.native_objects:
            if obj.kind is NativeObjectKind.TABLE and obj.table:
                for cell in obj.table.cells:
                    table_cell_entries.append(
                        _entry(
                            source_hash=source.source_hash,
                            source_id=cell.cell_id,
                            kind=InventoryEntryKind.TABLE_CELL,
                            page_id=page.page_id,
                            importance=(
                                InventoryImportance.HIGH
                                if cell.is_header
                                else InventoryImportance.NORMAL
                            ),
                            inspection_status=(
                                InventoryInspectionStatus.MUST_INSPECT
                            ),
                            declared_role=(
                                "table_header"
                                if cell.is_header
                                else "table_cell"
                            ),
                            evidence_refs=cell.evidence_refs,
                        )
                    )
                continue
            if obj.kind is NativeObjectKind.FORMULA:
                formula_entries.append(
                    _entry(
                        source_hash=source.source_hash,
                        source_id=obj.object_id,
                        kind=InventoryEntryKind.FORMULA_REGION,
                        page_id=page.page_id,
                        importance=_importance_for_object(obj),
                        inspection_status=_inspection_for_object(obj),
                        declared_role="formula",
                        evidence_refs=obj.evidence_refs,
                    )
                )
                continue
            if obj.kind is NativeObjectKind.CHEMICAL_REACTION:
                reaction_entries.append(
                    _entry(
                        source_hash=source.source_hash,
                        source_id=obj.object_id,
                        kind=InventoryEntryKind.REACTION_REGION,
                        page_id=page.page_id,
                        importance=_importance_for_object(obj),
                        inspection_status=_inspection_for_object(obj),
                        declared_role="chemical_reaction",
                        evidence_refs=obj.evidence_refs,
                    )
                )
                continue
            if obj.kind in {
                NativeObjectKind.IMAGE,
                NativeObjectKind.CHART,
                NativeObjectKind.SHAPE,
                NativeObjectKind.GROUP,
            }:
                visual_entries.append(
                    _entry(
                        source_hash=source.source_hash,
                        source_id=obj.object_id,
                        kind=InventoryEntryKind.VISUAL_REGION,
                        page_id=page.page_id,
                        importance=_importance_for_object(obj),
                        inspection_status=(
                            InventoryInspectionStatus.MUST_INSPECT
                        ),
                        declared_role=obj.kind.value,
                        evidence_refs=obj.evidence_refs,
                    )
                )

    outline_entries = tuple(
        _outline_entry(source, item) for item in source.outline_entries
    )
    unresolved_entries = (
        *(
            _unresolved_entry(source, item)
            for item in source.unresolved_regions
        ),
        *(
            _integrity_entry(source, code)
            for code in raw_manifest.mismatch_codes
        ),
    )
    return SourceInventory(
        inventory_id=_stable_token(
            "inventory_",
            {
                "document_ir_digest": document_ir_ref.payload_digest,
                "policy": INVENTORY_POLICY_VERSION,
                "source_hash": source.source_hash,
            },
        ),
        document_ir_ref=document_ir_ref,
        raw_manifest=raw_manifest,
        page_entries=page_entries,
        block_entries=block_entries,
        table_cell_entries=tuple(table_cell_entries),
        formula_region_entries=tuple(formula_entries),
        reaction_region_entries=tuple(reaction_entries),
        visual_region_entries=tuple(visual_entries),
        outline_entries=outline_entries,
        unresolved_entries=unresolved_entries,
        inventory_policy_version=INVENTORY_POLICY_VERSION,
    )
