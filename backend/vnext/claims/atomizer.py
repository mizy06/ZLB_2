from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping

from backend.vnext.artifacts.canonical import canonical_json_bytes
from backend.vnext.contracts.claims import (
    ClaimLedger,
    ClaimNovelty,
    ClaimPublicationStatus,
    ClaimRecord,
    ClaimScope,
    ClaimType,
    ExternalValidityStatus,
    ExtractionStatus,
    InstructionalRole,
    Mention,
    SourceEntailmentStatus,
)
from backend.vnext.contracts.common import (
    ArtifactProducerRef,
    ArtifactRef,
    RuntimeRole,
)
from backend.vnext.contracts.evidence import EvidenceRef
from backend.vnext.contracts.source import (
    BlockIR,
    BlockKind,
    NativeObjectIR,
    NativeObjectKind,
    OutlineEntryIR,
    PageRole,
    SourceObservationIR,
    TableCellIR,
)


ATOMIZER_VERSION = "1.0.0"
FIDELITY_VERSION = "1.0.0"

_WHITESPACE = re.compile(r"\s+")
_INSTRUCTION_CUE = re.compile(
    r"^(?:"
    r"请|完成|回答|计算|选择|判断|讨论|思考|练习|写出|指出|证明|"
    r"complete|answer|calculate|choose|select|discuss|consider|"
    r"write|identify|prove"
    r")",
    re.IGNORECASE,
)
_WARNING_CUE = re.compile(
    r"(?:注意|警告|不得|禁止|warning|caution|must not)",
    re.IGNORECASE,
)
_EXAMPLE_CUE = re.compile(
    r"(?:例如|举例|例题|example|case study)",
    re.IGNORECASE,
)
_COMPARISON_CUE = re.compile(
    r"(?:相比|区别|不同于|优于|劣于|versus|compared with|whereas)",
    re.IGNORECASE,
)
_DEFINITION_CUE = re.compile(
    r"(?:称为|定义为|是指|是一种|\brefers to\b|\bis an?\b|\bare\b)",
    re.IGNORECASE,
)
_PROCEDURE_CUE = re.compile(
    r"(?:步骤|流程|首先|然后|最后|step|procedure|first|then|finally)",
    re.IGNORECASE,
)
_SUMMARY_CUE = re.compile(
    r"(?:总结|小结|回顾|summary|review)",
    re.IGNORECASE,
)

_ATOMIZER = ArtifactProducerRef(
    producer_id="vnext-source-claim-atomizer",
    producer_version=ATOMIZER_VERSION,
    role=RuntimeRole.CLAIM_ATOMIZER,
)
_FIDELITY_VERIFIER = ArtifactProducerRef(
    producer_id="vnext-deterministic-fidelity-verifier",
    producer_version=FIDELITY_VERSION,
    role=RuntimeRole.CLAIM_FIDELITY_VERIFIER,
)


def _stable_id(prefix: str, value: object) -> str:
    digest = hashlib.sha256(
        b"zlb-vnext-claim-id-v1\0" + canonical_json_bytes(value)
    ).hexdigest()
    return prefix + digest[:32]


def _normalized(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _unique_evidence(
    evidence_refs: list[EvidenceRef],
) -> tuple[EvidenceRef, ...]:
    unique: dict[tuple[str, str], EvidenceRef] = {}
    for evidence in evidence_refs:
        unique[(evidence.namespace.value, evidence.ref_id)] = evidence
    return tuple(unique.values())


def _page_roles(source: SourceObservationIR) -> dict[str, set[PageRole]]:
    return {
        page.page_id: {item.role for item in page.role_hypotheses}
        for page in source.pages
    }


def _claim_classification(
    text: str,
    *,
    block_kind: BlockKind | None = None,
    object_kind: NativeObjectKind | None = None,
    page_roles: set[PageRole] | None = None,
) -> tuple[ClaimType, InstructionalRole, str]:
    body = _normalized(text)
    roles = page_roles or set()
    if _INSTRUCTION_CUE.search(body) or PageRole.EXERCISE in roles:
        return ClaimType.INSTRUCTION, InstructionalRole.EXERCISE, "instructs"
    if object_kind is NativeObjectKind.CHEMICAL_REACTION or (
        block_kind is BlockKind.REACTION_TEXT
    ):
        return ClaimType.REACTION, InstructionalRole.PRINCIPLE, "reacts"
    if object_kind is NativeObjectKind.FORMULA or (
        block_kind is BlockKind.FORMULA_TEXT
    ):
        return ClaimType.PROPERTY, InstructionalRole.PRINCIPLE, "states_formula"
    if block_kind in {BlockKind.TITLE, BlockKind.HEADING}:
        return (
            ClaimType.STRUCTURAL_FACT,
            InstructionalRole.OTHER,
            "organizes",
        )
    if _WARNING_CUE.search(body):
        return ClaimType.WARNING, InstructionalRole.WARNING, "warns"
    if _EXAMPLE_CUE.search(body) or PageRole.EXAMPLE in roles:
        return ClaimType.EXAMPLE, InstructionalRole.EXAMPLE, "illustrates"
    if _COMPARISON_CUE.search(body):
        return ClaimType.COMPARISON, InstructionalRole.COMPARISON, "compares"
    if _PROCEDURE_CUE.search(body):
        return ClaimType.PROCEDURE, InstructionalRole.PROCEDURE, "describes"
    if _SUMMARY_CUE.search(body) or PageRole.REVIEW in roles:
        return ClaimType.SUMMARY, InstructionalRole.REVIEW, "summarizes"
    if _DEFINITION_CUE.search(body):
        return ClaimType.DEFINITION, InstructionalRole.DEFINITION, "defines"
    return ClaimType.PROPERTY, InstructionalRole.PRINCIPLE, "states"


def _publication_for(
    claim_type: ClaimType,
    *,
    source_entailment: SourceEntailmentStatus,
) -> ClaimPublicationStatus:
    if claim_type is ClaimType.INSTRUCTION:
        return ClaimPublicationStatus.WITHHELD
    if claim_type is ClaimType.STRUCTURAL_FACT:
        return ClaimPublicationStatus.CANDIDATE
    if source_entailment is SourceEntailmentStatus.ENTAILED:
        return ClaimPublicationStatus.CORE
    if source_entailment is SourceEntailmentStatus.PARTIAL:
        return ClaimPublicationStatus.NEEDS_REVIEW
    return ClaimPublicationStatus.WITHHELD


def _fidelity_status(
    normalized_text: str,
    source_text: str,
) -> SourceEntailmentStatus:
    normalized_source = _normalized(source_text)
    if normalized_text == normalized_source:
        return SourceEntailmentStatus.ENTAILED
    if normalized_text and normalized_text in normalized_source:
        return SourceEntailmentStatus.PARTIAL
    return SourceEntailmentStatus.INSUFFICIENT


def _claim(
    *,
    source_hash: str,
    leaf_region_id: str,
    locator: object,
    text: str,
    evidence_refs: tuple[EvidenceRef, ...],
    claim_type: ClaimType,
    instructional_role: InstructionalRole,
    predicate: str,
    subject_mentions: tuple[Mention, ...] = (),
    object_mentions: tuple[Mention, ...] = (),
    scope: ClaimScope = ClaimScope.OBJECT,
) -> ClaimRecord:
    normalized_text = _normalized(text)
    entailment = _fidelity_status(normalized_text, text)
    return ClaimRecord(
        claim_id=_stable_id(
            "claim_",
            {
                "leaf_region_id": leaf_region_id,
                "locator": locator,
                "source_hash": source_hash,
            },
        ),
        leaf_region_id=leaf_region_id,
        claim_type=claim_type,
        normalized_text=normalized_text,
        source_text=text,
        subject_mentions=subject_mentions,
        predicate=predicate,
        object_mentions=object_mentions,
        instructional_role=instructional_role,
        novelty=ClaimNovelty.SOURCE_EXPLICIT,
        scope=scope,
        source_evidence_refs=evidence_refs,
        extraction_confidence=1.0,
        extraction_status=ExtractionStatus.EXTRACTED,
        source_entailment_status=entailment,
        external_validity_status=ExternalValidityStatus.NOT_CHECKED,
        publication_status=_publication_for(
            claim_type,
            source_entailment=entailment,
        ),
        extractor=_ATOMIZER,
        fidelity_verifier=_FIDELITY_VERIFIER,
    )


def _region_for(
    source_to_region: Mapping[str, str],
    source_ids: tuple[str, ...],
) -> str | None:
    if any(source_id not in source_to_region for source_id in source_ids):
        return None
    regions = {source_to_region[source_id] for source_id in source_ids}
    if len(regions) != 1:
        return None
    return next(iter(regions))


def _matching_outline(
    source: SourceObservationIR,
    block: BlockIR,
) -> tuple[OutlineEntryIR, ...]:
    normalized = _normalized(block.text).casefold()
    return tuple(
        item
        for item in source.outline_entries
        if item.target_page_id == block.page_id
        and _normalized(item.label).casefold() == normalized
    )


def _block_claim(
    source: SourceObservationIR,
    block: BlockIR,
    native_object: NativeObjectIR | None,
    source_to_region: Mapping[str, str],
    roles: set[PageRole],
) -> ClaimRecord | None:
    evidence = list(block.evidence_refs)
    source_ids = [block.block_id]
    if native_object and native_object.kind in {
        NativeObjectKind.FORMULA,
        NativeObjectKind.CHEMICAL_REACTION,
    }:
        evidence.extend(native_object.evidence_refs)
        source_ids.append(native_object.object_id)
    matches = _matching_outline(source, block)
    for item in matches:
        evidence.extend(item.evidence_refs)
        source_ids.append(item.outline_entry_id)
    leaf_region_id = _region_for(source_to_region, tuple(source_ids))
    if leaf_region_id is None:
        return None
    claim_type, instructional_role, predicate = _claim_classification(
        block.text,
        block_kind=block.kind,
        object_kind=native_object.kind if native_object else None,
        page_roles=roles,
    )
    return _claim(
        source_hash=source.source_hash,
        leaf_region_id=leaf_region_id,
        locator={"block_id": block.block_id},
        text=block.text,
        evidence_refs=_unique_evidence(evidence),
        claim_type=claim_type,
        instructional_role=instructional_role,
        predicate=predicate,
    )


def _table_cell_claim(
    source: SourceObservationIR,
    *,
    table_object: NativeObjectIR,
    cell: TableCellIR,
    source_to_region: Mapping[str, str],
    include_table_block: BlockIR | None,
) -> ClaimRecord | None:
    assert table_object.table is not None
    source_ids = [cell.cell_id, *cell.header_cell_refs]
    evidence = list(cell.evidence_refs)
    header_by_id = {
        item.cell_id: item for item in table_object.table.cells
    }
    subject_mentions: list[Mention] = []
    for header_id in cell.header_cell_refs:
        header = header_by_id[header_id]
        evidence.extend(header.evidence_refs)
        if header.text.strip():
            subject_mentions.append(
                Mention(
                    text=header.text.strip(),
                    source_ids=(header.cell_id,),
                )
            )
    if include_table_block is not None:
        source_ids.append(include_table_block.block_id)
        evidence.extend(include_table_block.evidence_refs)
    leaf_region_id = _region_for(source_to_region, tuple(source_ids))
    if leaf_region_id is None or not cell.text.strip():
        return None
    claim_type = (
        ClaimType.STRUCTURAL_FACT
        if cell.is_header
        else ClaimType.PROPERTY
    )
    return _claim(
        source_hash=source.source_hash,
        leaf_region_id=leaf_region_id,
        locator={"table_cell_id": cell.cell_id},
        text=cell.text,
        evidence_refs=_unique_evidence(evidence),
        claim_type=claim_type,
        instructional_role=InstructionalRole.OTHER,
        predicate="table_header" if cell.is_header else "table_value",
        subject_mentions=tuple(subject_mentions),
        object_mentions=(
            Mention(text=cell.text.strip(), source_ids=(cell.cell_id,)),
        ),
    )


def _outline_claim(
    source: SourceObservationIR,
    item: OutlineEntryIR,
    source_to_region: Mapping[str, str],
) -> ClaimRecord | None:
    leaf_region_id = _region_for(
        source_to_region,
        (item.outline_entry_id,),
    )
    if leaf_region_id is None:
        return None
    return _claim(
        source_hash=source.source_hash,
        leaf_region_id=leaf_region_id,
        locator={"outline_entry_id": item.outline_entry_id},
        text=item.label,
        evidence_refs=item.evidence_refs,
        claim_type=ClaimType.STRUCTURAL_FACT,
        instructional_role=InstructionalRole.OTHER,
        predicate="organizes",
        scope=ClaimScope.REGION,
    )


def atomize_source_claims(
    source: SourceObservationIR,
    *,
    document_ir_ref: ArtifactRef,
    region_plan_refs: tuple[ArtifactRef, ...],
    source_to_leaf_region: Mapping[str, str],
) -> ClaimLedger:
    """Build a source-only ledger without consulting external evidence."""

    claims: list[ClaimRecord] = []
    claimed_outline_ids: set[str] = set()
    roles_by_page = _page_roles(source)
    for page in source.pages:
        objects_by_id = {
            item.object_id: item for item in page.native_objects
        }
        table_blocks_by_object = {
            block.native_object_id: block
            for block in page.blocks
            if block.kind is BlockKind.TABLE_TEXT
            and block.native_object_id is not None
        }
        for block in page.blocks:
            native_object = (
                objects_by_id.get(block.native_object_id)
                if block.native_object_id
                else None
            )
            if native_object and native_object.kind is NativeObjectKind.TABLE:
                continue
            claim = _block_claim(
                source,
                block,
                native_object,
                source_to_leaf_region,
                roles_by_page.get(page.page_id, set()),
            )
            if claim is None:
                continue
            claims.append(claim)
            claimed_outline_ids.update(
                item.outline_entry_id
                for item in _matching_outline(source, block)
            )

        for obj in page.native_objects:
            if obj.kind is not NativeObjectKind.TABLE or obj.table is None:
                continue
            table_block = table_blocks_by_object.get(obj.object_id)
            first_cell = True
            for cell in obj.table.cells:
                claim = _table_cell_claim(
                    source,
                    table_object=obj,
                    cell=cell,
                    source_to_region=source_to_leaf_region,
                    include_table_block=table_block if first_cell else None,
                )
                first_cell = False
                if claim is not None:
                    claims.append(claim)

    for item in source.outline_entries:
        if item.outline_entry_id in claimed_outline_ids:
            continue
        claim = _outline_claim(source, item, source_to_leaf_region)
        if claim is not None:
            claims.append(claim)

    claims.sort(key=lambda item: item.claim_id)
    return ClaimLedger(
        ledger_id=_stable_id(
            "ledger_",
            {
                "document_ir_digest": document_ir_ref.payload_digest,
                "region_plan_digests": [
                    item.payload_digest for item in region_plan_refs
                ],
                "source_hash": source.source_hash,
            },
        ),
        document_ir_ref=document_ir_ref,
        region_plan_refs=region_plan_refs,
        claims=tuple(claims),
        producer=_ATOMIZER,
    )
