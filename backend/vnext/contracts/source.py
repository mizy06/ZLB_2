from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from .base import FrozenContract
from .common import (
    ArtifactRef,
    ArtifactType,
    InterpretationStatus,
    ProducerRef,
    SemVer,
    Sha256Digest,
    SourceId,
    StringValue,
    require_artifact_type,
)
from .evidence import EvidenceNamespace, EvidenceRef, require_evidence_namespace


HypothesisId = Annotated[
    str,
    StringConstraints(pattern=r"^hyp_[0-9a-f]{32}$"),
]


class SourceLayer(StrEnum):
    NATIVE = "native"
    OCR = "ocr"
    VLM = "vlm"
    RENDERER = "renderer"
    HUMAN_CORRECTION = "human_correction"


class CoordinateUnit(StrEnum):
    POINT = "point"
    PIXEL = "pixel"
    NORMALIZED = "normalized"


class PageRole(StrEnum):
    COVER = "cover"
    TOC = "toc"
    SECTION_DIVIDER = "section_divider"
    CONTENT = "content"
    EXAMPLE = "example"
    RESEARCH_ASIDE = "research_aside"
    REVIEW = "review"
    EXERCISE = "exercise"
    ANSWER = "answer"
    APPENDIX = "appendix"
    DECORATION = "decoration"
    UNKNOWN = "unknown"


class ContinuityRelation(StrEnum):
    SAME_SECTION = "same_section"
    CONTINUED_FROM = "continued_from"
    CONTINUED_TO = "continued_to"
    ASIDE_OF = "aside_of"
    RETURNS_TO = "returns_to"
    REVIEW_OF = "review_of"
    REPETITION_OF = "repetition_of"


class BlockKind(StrEnum):
    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    CAPTION = "caption"
    NOTE = "note"
    TABLE_TEXT = "table_text"
    FORMULA_TEXT = "formula_text"
    REACTION_TEXT = "reaction_text"
    OTHER = "other"


class NativeObjectKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    TABLE = "table"
    FORMULA = "formula"
    CHEMICAL_REACTION = "chemical_reaction"
    CHART = "chart"
    SHAPE = "shape"
    GROUP = "group"
    NOTE = "note"
    LINK = "link"
    OTHER = "other"


class OrderSignalKind(StrEnum):
    NATIVE_SEQUENCE = "native_sequence"
    TITLE_PRIORITY = "title_priority"
    COLUMN_GEOMETRY = "column_geometry"
    GROUP_MEMBERSHIP = "group_membership"
    Z_ORDER = "z_order"
    VISUAL_FLOW = "visual_flow"


class HypothesisKind(StrEnum):
    CONTINUITY = "continuity"
    OUTLINE_ALIGNMENT = "outline_alignment"
    SECTION_INTERVAL = "section_interval"
    TITLE_MATCH = "title_match"


class PageDimensions(FrozenContract):
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    unit: CoordinateUnit


class BoundingBox(FrozenContract):
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    unit: CoordinateUnit

    @model_validator(mode="after")
    def validate_normalized_bounds(self) -> "BoundingBox":
        if self.unit is CoordinateUnit.NORMALIZED and (
            self.x > 1
            or self.y > 1
            or self.width > 1
            or self.height > 1
            or self.x + self.width > 1
            or self.y + self.height > 1
        ):
            raise ValueError("normalized bbox must remain inside 0..1")
        return self


class CharSpan(FrozenContract):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str | None = None

    @model_validator(mode="after")
    def validate_order(self) -> "CharSpan":
        if self.end <= self.start:
            raise ValueError("char span end must be greater than start")
        return self


class ParserManifest(FrozenContract):
    parser_name: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    parser_version: SemVer
    parser_major: int = Field(ge=1)
    renderer_version: SemVer | None = None
    dependency_digest: Sha256Digest
    configuration: tuple[StringValue, ...] = ()


class TableCellIR(FrozenContract):
    cell_id: SourceId
    row_index: int = Field(ge=0)
    column_index: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    text: str = ""
    is_header: bool = False
    header_cell_refs: tuple[SourceId, ...] = ()
    bbox: BoundingBox | None = None
    evidence_refs: tuple[EvidenceRef, ...] = ()

    @model_validator(mode="after")
    def validate_evidence(self) -> "TableCellIR":
        if not self.evidence_refs:
            raise ValueError("table cell requires source evidence")
        require_evidence_namespace(
            self.evidence_refs,
            frozenset(
                {EvidenceNamespace.COURSEWARE, EvidenceNamespace.SYSTEM}
            ),
            field_name="table cell evidence_refs",
        )
        return self


class TableIR(FrozenContract):
    row_count: int = Field(ge=1)
    column_count: int = Field(ge=1)
    caption: str | None = None
    cells: tuple[TableCellIR, ...]

    @model_validator(mode="after")
    def validate_cells(self) -> "TableIR":
        occupied: set[tuple[int, int]] = set()
        ids: set[str] = set()
        for cell in self.cells:
            if cell.cell_id in ids:
                raise ValueError(f"duplicate table cell ID: {cell.cell_id}")
            ids.add(cell.cell_id)
            if (
                cell.row_index + cell.row_span > self.row_count
                or cell.column_index + cell.column_span > self.column_count
            ):
                raise ValueError("table cell extends beyond declared dimensions")
            coordinates = {
                (row, column)
                for row in range(
                    cell.row_index,
                    cell.row_index + cell.row_span,
                )
                for column in range(
                    cell.column_index,
                    cell.column_index + cell.column_span,
                )
            }
            if occupied & coordinates:
                raise ValueError("table cell spans overlap")
            occupied.update(coordinates)
        for cell in self.cells:
            unknown_headers = set(cell.header_cell_refs) - ids
            if unknown_headers:
                raise ValueError(
                    "table cell references unknown headers: "
                    + ", ".join(sorted(unknown_headers))
                )
        return self


class FormulaSymbol(FrozenContract):
    symbol: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    confidence: float = Field(ge=0, le=1)
    bbox: BoundingBox | None = None


class FormulaIR(FrozenContract):
    display_text: str
    latex: str | None = None
    ast_serialization: str | None = None
    render_ref: EvidenceRef
    symbols: tuple[FormulaSymbol, ...] = ()
    parse_status: Literal["parsed", "partial", "unresolved"] = "unresolved"

    @model_validator(mode="after")
    def require_parsed_representation(self) -> "FormulaIR":
        if self.parse_status == "parsed" and not self.display_text.strip():
            raise ValueError("parsed formula requires display text")
        return self


class ReactionParticipant(FrozenContract):
    label: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    coefficient: str | None = None
    evidence_refs: tuple[EvidenceRef, ...] = ()


class ReactionCondition(FrozenContract):
    text: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    evidence_refs: tuple[EvidenceRef, ...]


class ChemicalReactionIR(FrozenContract):
    reactants: tuple[ReactionParticipant, ...]
    products: tuple[ReactionParticipant, ...]
    reagents: tuple[ReactionParticipant, ...] = ()
    conditions: tuple[ReactionCondition, ...] = ()
    arrow: Annotated[
        str,
        StringConstraints(min_length=1, max_length=32),
    ] = "->"
    arrow_evidence_refs: tuple[EvidenceRef, ...] = ()
    direction: Literal["forward", "reverse", "equilibrium", "unknown"] = (
        "unknown"
    )
    direction_evidence_refs: tuple[EvidenceRef, ...] = ()
    step: int | None = Field(default=None, ge=1)
    step_evidence_refs: tuple[EvidenceRef, ...] = ()
    parse_status: Literal["parsed", "partial", "unresolved"] = "unresolved"

    @model_validator(mode="after")
    def require_visible_sides(self) -> "ChemicalReactionIR":
        if self.parse_status == "parsed" and (
            not self.reactants or not self.products
        ):
            raise ValueError(
                "parsed reactions require reactants and products"
            )
        if self.parse_status == "parsed":
            participants = (
                *self.reactants,
                *self.products,
                *self.reagents,
            )
            if any(not item.evidence_refs for item in participants):
                raise ValueError(
                    "parsed reaction participants require provenance"
                )
            if any(
                not condition.evidence_refs
                for condition in self.conditions
            ):
                raise ValueError(
                    "parsed reaction conditions require provenance"
                )
            if not self.arrow_evidence_refs:
                raise ValueError("parsed reaction arrow requires provenance")
            if (
                self.direction != "unknown"
                and not self.direction_evidence_refs
            ):
                raise ValueError(
                    "parsed reaction direction requires provenance"
                )
            if self.step is not None and not self.step_evidence_refs:
                raise ValueError(
                    "parsed reaction step requires provenance"
                )
        return self


class NativeObjectIR(FrozenContract):
    object_id: SourceId
    page_id: SourceId
    kind: NativeObjectKind
    bbox: BoundingBox | None = None
    native_order_hint: int | None = Field(default=None, ge=0)
    parent_group_id: SourceId | None = None
    text: str = ""
    asset_ref: EvidenceRef | None = None
    table: TableIR | None = None
    formula: FormulaIR | None = None
    reaction: ChemicalReactionIR | None = None
    source_layer: SourceLayer
    observation_status: InterpretationStatus = InterpretationStatus.OBSERVED
    producer: ProducerRef
    evidence_refs: tuple[EvidenceRef, ...] = ()
    supersedes: SourceId | None = None

    @model_validator(mode="after")
    def validate_typed_payload(self) -> "NativeObjectIR":
        expected = {
            NativeObjectKind.TABLE: "table",
            NativeObjectKind.FORMULA: "formula",
            NativeObjectKind.CHEMICAL_REACTION: "reaction",
        }
        populated = {
            name
            for name in ("table", "formula", "reaction")
            if getattr(self, name) is not None
        }
        required = expected.get(self.kind)
        if required and populated != {required}:
            raise ValueError(
                f"{self.kind.value} object requires only {required} payload"
            )
        if not required and populated:
            raise ValueError(
                f"{self.kind.value} object cannot carry "
                f"{', '.join(sorted(populated))} payload"
            )
        if self.kind is NativeObjectKind.IMAGE and self.asset_ref is None:
            raise ValueError("image object requires an asset_ref")
        require_evidence_namespace(
            self.evidence_refs,
            frozenset(
                {EvidenceNamespace.COURSEWARE, EvidenceNamespace.SYSTEM}
            ),
            field_name="native object evidence_refs",
        )
        return self


class BlockIR(FrozenContract):
    block_id: SourceId
    page_id: SourceId
    kind: BlockKind
    text: str
    bbox: BoundingBox | None = None
    native_order_hint: int | None = Field(default=None, ge=0)
    native_object_id: SourceId | None = None
    parent_group_id: SourceId | None = None
    source_layer: SourceLayer
    source_confidence: float = Field(ge=0, le=1)
    char_spans: tuple[CharSpan, ...] = ()
    observation_status: InterpretationStatus
    producer: ProducerRef
    evidence_refs: tuple[EvidenceRef, ...] = ()
    supersedes: SourceId | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> "BlockIR":
        require_evidence_namespace(
            self.evidence_refs,
            frozenset(
                {EvidenceNamespace.COURSEWARE, EvidenceNamespace.SYSTEM}
            ),
            field_name="block evidence_refs",
        )
        return self


class ObservedOrderSignal(FrozenContract):
    signal_id: SourceId
    kind: OrderSignalKind
    ordered_source_ids: tuple[SourceId, ...]
    producer: ProducerRef
    evidence_refs: tuple[EvidenceRef, ...] = ()

    @model_validator(mode="after")
    def require_order(self) -> "ObservedOrderSignal":
        if len(self.ordered_source_ids) < 2:
            raise ValueError("order signal requires at least two source IDs")
        return self


class ReadingOrderHypothesis(FrozenContract):
    hypothesis_id: HypothesisId
    ordered_block_ids: tuple[SourceId, ...]
    confidence: float = Field(ge=0, le=1)
    interpretation_status: InterpretationStatus
    producer: ProducerRef
    evidence_refs: tuple[EvidenceRef, ...]
    supersedes: HypothesisId | None = None

    @model_validator(mode="after")
    def require_inferred_status(self) -> "ReadingOrderHypothesis":
        if self.interpretation_status is InterpretationStatus.OBSERVED:
            raise ValueError(
                "reading order belongs to the interpretation layer"
            )
        return self


class RoleHypothesis(FrozenContract):
    hypothesis_id: HypothesisId
    role: PageRole
    confidence: float = Field(ge=0, le=1)
    interpretation_status: InterpretationStatus
    producer: ProducerRef
    evidence_refs: tuple[EvidenceRef, ...]
    supersedes: HypothesisId | None = None

    @model_validator(mode="after")
    def require_inferred_status(self) -> "RoleHypothesis":
        if self.interpretation_status is InterpretationStatus.OBSERVED:
            raise ValueError("page role is a hypothesis, not an observation")
        return self


class PageIR(FrozenContract):
    page_id: SourceId
    physical_index: int = Field(ge=0)
    logical_number: str | None = None
    dimensions: PageDimensions
    blocks: tuple[BlockIR, ...] = ()
    native_objects: tuple[NativeObjectIR, ...] = ()
    observed_order_signals: tuple[ObservedOrderSignal, ...] = ()
    reading_order_hypotheses: tuple[ReadingOrderHypothesis, ...] = ()
    role_hypotheses: tuple[RoleHypothesis, ...] = ()
    render_ref: EvidenceRef

    @model_validator(mode="after")
    def validate_page_membership(self) -> "PageIR":
        for block in self.blocks:
            if block.page_id != self.page_id:
                raise ValueError("block page_id does not match containing page")
        for obj in self.native_objects:
            if obj.page_id != self.page_id:
                raise ValueError(
                    "native object page_id does not match containing page"
                )
        if self.render_ref.namespace not in {
            EvidenceNamespace.COURSEWARE,
            EvidenceNamespace.SYSTEM,
        }:
            raise ValueError("render_ref must be courseware or system evidence")
        return self


class OutlineEntryIR(FrozenContract):
    outline_entry_id: SourceId
    label: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    observed_level: int = Field(ge=1)
    source_order: int = Field(ge=0)
    target_page_id: SourceId | None = None
    native_target: str | None = None
    producer: ProducerRef
    evidence_refs: tuple[EvidenceRef, ...]


class InterpretationHypothesis(FrozenContract):
    hypothesis_id: HypothesisId
    hypothesis_type: HypothesisKind
    subject_source_ids: tuple[SourceId, ...]
    related_source_ids: tuple[SourceId, ...] = ()
    label: Annotated[
        str,
        StringConstraints(min_length=1, max_length=1024),
    ]
    continuity_relation: ContinuityRelation | None = None
    confidence: float = Field(ge=0, le=1)
    interpretation_status: InterpretationStatus
    producer: ProducerRef
    evidence_refs: tuple[EvidenceRef, ...]
    supersedes: HypothesisId | None = None

    @model_validator(mode="after")
    def validate_hypothesis(self) -> "InterpretationHypothesis":
        if self.interpretation_status is InterpretationStatus.OBSERVED:
            raise ValueError(
                "interpretation hypotheses cannot be recorded as observations"
            )
        if (
            self.hypothesis_type is HypothesisKind.CONTINUITY
            and self.continuity_relation is None
        ):
            raise ValueError(
                "continuity hypothesis requires continuity_relation"
            )
        if (
            self.hypothesis_type is not HypothesisKind.CONTINUITY
            and self.continuity_relation is not None
        ):
            raise ValueError(
                "continuity_relation is only valid for continuity hypotheses"
            )
        return self


class UnresolvedRegionIR(FrozenContract):
    region_source_id: SourceId
    page_id: SourceId
    bbox: BoundingBox
    reason_code: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    transcription: str | None = None
    producer: ProducerRef
    evidence_refs: tuple[EvidenceRef, ...]
    supersedes: SourceId | None = None


class SourceObservationIR(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_id: SourceId
    source_hash: Sha256Digest
    source_revision: int = Field(default=1, ge=1)
    parser_manifest: ParserManifest
    pages: tuple[PageIR, ...]
    outline_entries: tuple[OutlineEntryIR, ...] = ()
    interpretation_hypotheses: tuple[InterpretationHypothesis, ...] = ()
    unresolved_regions: tuple[UnresolvedRegionIR, ...] = ()
    supersedes: ArtifactRef | None = None

    @field_validator("pages")
    @classmethod
    def require_pages(cls, value: tuple[PageIR, ...]) -> tuple[PageIR, ...]:
        if not value:
            raise ValueError("SourceObservationIR must retain every source page")
        physical = [page.physical_index for page in value]
        if len(physical) != len(set(physical)):
            raise ValueError("physical page indices must be unique")
        return value

    @model_validator(mode="after")
    def validate_source_identity(self) -> "SourceObservationIR":
        require_artifact_type(
            self.supersedes,
            ArtifactType.SOURCE_OBSERVATION_IR,
            field_name="supersedes",
        )
        require_evidence_namespace(
            tuple(_iter_evidence_refs(self)),
            frozenset(
                {
                    EvidenceNamespace.COURSEWARE,
                    EvidenceNamespace.HUMAN,
                    EvidenceNamespace.SYSTEM,
                }
            ),
            field_name="SourceObservationIR evidence",
        )
        source_ids: list[str] = [self.document_id]
        hypothesis_ids: list[str] = []
        page_ids = {page.page_id for page in self.pages}
        source_ids.extend(page_ids)
        for page in self.pages:
            for block in page.blocks:
                source_ids.append(block.block_id)
            for obj in page.native_objects:
                source_ids.append(obj.object_id)
                if obj.table:
                    source_ids.extend(cell.cell_id for cell in obj.table.cells)
            source_ids.extend(
                signal.signal_id for signal in page.observed_order_signals
            )
            hypothesis_ids.extend(
                item.hypothesis_id
                for item in page.reading_order_hypotheses
            )
            hypothesis_ids.extend(
                item.hypothesis_id for item in page.role_hypotheses
            )
        source_ids.extend(
            item.outline_entry_id for item in self.outline_entries
        )
        source_ids.extend(
            item.region_source_id for item in self.unresolved_regions
        )
        hypothesis_ids.extend(
            item.hypothesis_id for item in self.interpretation_hypotheses
        )
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source IDs must be unique within one revision")
        if len(hypothesis_ids) != len(set(hypothesis_ids)):
            raise ValueError(
                "hypothesis IDs must be unique within one revision"
            )
        for entry in self.outline_entries:
            if entry.target_page_id and entry.target_page_id not in page_ids:
                raise ValueError(
                    "outline target_page_id must reference a retained page"
                )
        for unresolved in self.unresolved_regions:
            if unresolved.page_id not in page_ids:
                raise ValueError(
                    "unresolved region must reference a retained page"
                )
        return self


def _iter_evidence_refs(value):
    if isinstance(value, EvidenceRef):
        yield value
        return
    if isinstance(value, FrozenContract):
        for field_name in type(value).model_fields:
            yield from _iter_evidence_refs(getattr(value, field_name))
        return
    if isinstance(value, tuple):
        for item in value:
            yield from _iter_evidence_refs(item)
