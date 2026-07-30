from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from backend.app.architecture_schemas import (
    Chunk,
    ContentUnit,
    CoverageSummary,
    DecisionRecord,
    EvidenceRef as LegacyEvidenceRef,
    MindMapCrossLink,
    MindMapNode,
    MindMapQualityReport,
    MindMapResult,
    MindMapTreeEdge,
    ModelSelection,
    ModelVote,
    ParsedDocument,
)
from backend.vnext.contracts.claims import ClaimLedger, InstructionalRole
from backend.vnext.contracts.common import DecisionEvent, RuntimeRole
from backend.vnext.contracts.control import RunManifest, RunProfile
from backend.vnext.contracts.graph import (
    CanonicalExplicitGraph,
    CanonicalRelation,
    CanonicalStatus,
    ConceptOrigin,
    HierarchyDirectness,
    SemanticRelation,
)
from backend.vnext.contracts.inventory import (
    InventoryEntry,
    InventoryImportance,
    SourceInventory,
)
from backend.vnext.contracts.claims import OmissionAudit
from backend.vnext.contracts.projection import (
    DiagnosticProjection,
    ProjectionQualityStatus,
)
from backend.vnext.contracts.source import (
    BlockKind,
    NativeObjectKind,
    SourceObservationIR,
)
from backend.vnext.projection.validation import (
    validate_projection_against_graph,
)


class LegacyAdaptationBlocked(ValueError):
    pass


_CROSS_LINK_RELATIONS = {
    SemanticRelation.DEPENDS_ON: "depends_on",
    SemanticRelation.PREREQUISITE: "depends_on",
    SemanticRelation.CAUSES: "causes",
    SemanticRelation.PRECEDES: "precedes",
    SemanticRelation.CONTRASTS: "contrasts_with",
    SemanticRelation.USED_FOR: "used_for",
}
_ORIGIN_MAP = {
    ConceptOrigin.EXPLICIT: "explicit",
    ConceptOrigin.OUTLINE_ANCHOR: "structural",
    ConceptOrigin.PLANNER_INDUCED_REGION: "abstractive",
    ConceptOrigin.EXTERNAL_REFERENCE: "explicit",
}
_UNIT_ROLE_MAP = {
    InstructionalRole.DEFINITION: "definition",
    InstructionalRole.PRINCIPLE: "principle",
    InstructionalRole.PROCEDURE: "step",
    InstructionalRole.COMPARISON: "principle",
    InstructionalRole.APPLICATION: "example",
    InstructionalRole.EXERCISE: "example",
    InstructionalRole.REVIEW: "other",
    InstructionalRole.EXAMPLE: "example",
    InstructionalRole.WARNING: "warning",
    InstructionalRole.OTHER: "other",
}


def to_legacy_result(
    *,
    task_id: str,
    run_id: str,
    graph_version: int,
    filename: str,
    file_type: str,
    source: SourceObservationIR,
    inventory: SourceInventory,
    claims: ClaimLedger,
    omission_audit: OmissionAudit,
    graph: CanonicalExplicitGraph,
    projection: DiagnosticProjection,
    run_manifest: RunManifest | None = None,
    mode: RunProfile | str = RunProfile.STANDARD,
    title: str | None = None,
) -> MindMapResult:
    """Lossily down-convert a publishable vNext projection for old readers."""

    validate_projection_against_graph(projection, graph)
    if projection.quality_status is not ProjectionQualityStatus.PASSED:
        raise LegacyAdaptationBlocked(
            "legacy result requires a quality-passed projection"
        )
    if projection.aggregation_map or any(
        item.startswith("view:") for item in projection.included_ids
    ):
        raise LegacyAdaptationBlocked(
            "legacy result cannot represent view aggregation nodes"
        )
    accepted_concepts = {
        concept.concept_id: concept
        for concept in graph.concepts
        if concept.status is CanonicalStatus.ACCEPTED
    }
    included = set(projection.included_ids)
    hidden_accepted = set(accepted_concepts) - included
    if hidden_accepted:
        raise LegacyAdaptationBlocked(
            "legacy result cannot hide accepted canonical concepts"
        )

    hierarchy_by_id = {
        relation.relation_id: relation
        for relation in graph.relations
        if (
            relation.status is CanonicalStatus.ACCEPTED
            and relation.hierarchy_directness
            is HierarchyDirectness.DIRECT
        )
    }
    selected_relations: list[CanonicalRelation] = []
    parent_by_child: dict[str, str] = {}
    for selection in projection.parent_selections:
        relation = hierarchy_by_id.get(
            selection.selected_parent_edge_id
        )
        if relation is None:
            raise LegacyAdaptationBlocked(
                "projection selected a non-hierarchy parent edge"
            )
        selected_relations.append(relation)
        parent_by_child[selection.child_concept_id] = relation.source_id
    roots = tuple(
        concept_id
        for concept_id in sorted(accepted_concepts)
        if concept_id not in parent_by_child
    )
    if len(roots) != 1:
        raise LegacyAdaptationBlocked(
            "legacy result requires exactly one selected root"
        )
    root_id = roots[0]
    missing_parents = (
        set(accepted_concepts) - {root_id} - set(parent_by_child)
    )
    if missing_parents:
        raise LegacyAdaptationBlocked(
            "legacy result cannot represent parentless accepted concepts"
        )

    source_index = _source_index(source)
    claim_by_id = {claim.claim_id: claim for claim in claims.claims}
    evidence_for_concept = {
        concept_id: tuple(
            _legacy_evidence(item, source_index)
            for item in concept.source_evidence_refs
        )
        for concept_id, concept in accepted_concepts.items()
    }
    depths = _depths(
        root_id,
        tuple(
            (relation.source_id, relation.target_id)
            for relation in selected_relations
        ),
    )
    nodes = [
        MindMapNode(
            id=concept.concept_id,
            temp_ids=list(concept.source_claim_ids)
            or [concept.concept_id],
            name=concept.canonical_name,
            type=concept.semantic_kind.value,
            role=concept.pedagogical_role.value,
            definition=_definition(concept.source_claim_ids, claim_by_id),
            aliases=list(concept.aliases),
            origin=_ORIGIN_MAP[concept.origin],
            branch_id=concept.scope,
            confidence=_concept_confidence(concept),
            optional=False,
            activation_score=_concept_confidence(concept),
            activation_cost=0,
            is_root_candidate=concept.concept_id == root_id,
            evidence=list(evidence_for_concept[concept.concept_id]),
            explicit_evidence_unit_ids=[
                item.unit_id
                for item in evidence_for_concept[concept.concept_id]
                if item.unit_id
            ],
            support_unit_ids=[
                item.ref_id for item in concept.source_evidence_refs
            ],
            media_asset_ids=[],
            depth=depths[concept.concept_id],
            parent_id=parent_by_child.get(concept.concept_id),
            status="accepted",
            risk_score=0,
        )
        for concept in sorted(
            accepted_concepts.values(),
            key=lambda item: (depths[item.concept_id], item.concept_id),
        )
    ]
    tree_edges = [
        MindMapTreeEdge(
            id=relation.relation_id,
            source=relation.source_id,
            target=relation.target_id,
            score=_relation_score(relation),
            provisional=False,
            evidence=[
                _legacy_evidence(item, source_index)
                for item in relation.edge_evidence_refs
            ],
            classification="direct_parent",
            verifier_votes=_legacy_votes(relation),
        )
        for relation in sorted(
            selected_relations,
            key=lambda item: item.relation_id,
        )
    ]
    cross_links: list[MindMapCrossLink] = []
    unsupported_cross_links: list[str] = []
    for relation in graph.relations:
        if (
            relation.status is not CanonicalStatus.ACCEPTED
            or relation.hierarchy_directness
            is not HierarchyDirectness.NON_HIERARCHICAL
            or relation.source_id not in accepted_concepts
            or relation.target_id not in accepted_concepts
        ):
            continue
        legacy_relation = _CROSS_LINK_RELATIONS.get(
            relation.semantic_relation
        )
        if legacy_relation is None:
            unsupported_cross_links.append(relation.relation_id)
            continue
        cross_links.append(
            MindMapCrossLink(
                id=relation.relation_id,
                source=relation.source_id,
                target=relation.target_id,
                relation=legacy_relation,
                score=_relation_score(relation),
                evidence=[
                    _legacy_evidence(item, source_index)
                    for item in relation.edge_evidence_refs
                ],
                verifier_votes=_legacy_votes(relation),
            )
        )

    parsed_document, chunks = _legacy_document(
        source,
        filename=filename,
        file_type=file_type,
        title=title or accepted_concepts[root_id].canonical_name,
    )
    content_units = _legacy_content_units(
        source,
        inventory,
        claims,
        omission_audit,
        source_index=source_index,
    )
    all_evidenced = all(node.evidence for node in nodes)
    warnings = [
        "vNext Canonical DAG was lossily projected to one legacy parent.",
        "Legacy down-conversion is one-way; round-trip import is forbidden.",
        "vNext visual asset payloads remain in source artifacts and were "
        "not embedded in the legacy result.",
    ]
    alternate_count = sum(
        len(item.alternate_parent_edge_ids)
        for item in projection.parent_selections
    )
    if alternate_count:
        warnings.append(
            f"{alternate_count} alternate canonical parent edges were "
            "omitted by the legacy single-parent contract."
        )
    if unsupported_cross_links:
        warnings.append(
            f"{len(unsupported_cross_links)} cross-links used relations "
            "unsupported by the legacy enum and were omitted."
        )
    quality = MindMapQualityReport(
        node_count=len(nodes),
        tree_edge_count=len(tree_edges),
        cross_link_count=len(cross_links),
        root_count=1,
        orphan_count=0,
        conflict_count=0,
        provisional_edge_count=0,
        evidence_coverage=1.0 if all_evidenced else 0.0,
        topology_valid=True,
        warnings=warnings,
        weighted_content_coverage=omission_audit.must_have_recall,
        direct_parent_confidence=(
            sum(edge.score for edge in tree_edges) / len(tree_edges)
            if tree_edges
            else 1.0
        ),
        abstraction_support_rate=1.0,
        review_item_count=0,
        structural_gate_passed=True,
        publish_gate_passed=True,
        quality_gate_passed=True,
        coverage=_coverage_summary(
            inventory,
            omission_audit,
        ),
    )
    selected_mode = (
        mode.value if isinstance(mode, RunProfile) else str(mode)
    )
    if selected_mode not in {"standard", "precision"}:
        raise ValueError("legacy adapter mode must be standard or precision")
    model_selection = _model_selection(run_manifest)
    degraded_components = (
        list(run_manifest.observed.degraded_components)
        if run_manifest
        else []
    )
    manifest_payload: dict[str, Any] = (
        run_manifest.model_dump(mode="json")
        if run_manifest
        else {}
    )
    manifest_payload["legacy_adapter"] = {
        "adapter_version": "1.0.0",
        "lossy": True,
        "round_trip": "forbidden",
        "canonical_graph_id": graph.graph_id,
        "projection_id": projection.projection_id,
    }
    return MindMapResult(
        task_id=task_id,
        run_id=run_id,
        graph_version=graph_version,
        document=parsed_document,
        chunks=chunks,
        content_units=content_units,
        root_id=root_id,
        nodes=nodes,
        tree_edges=tree_edges,
        cross_links=cross_links,
        assets=[],
        quality_report=quality,
        review_items=[],
        decision_records=_decision_records(graph, run_id, root_id),
        mode=selected_mode,
        extraction_mode="mixed",
        model_selection=model_selection,
        degraded_components=degraded_components,
        warnings=warnings,
        solver_status="VNEXT_PROJECTION",
        run_manifest=manifest_payload,
    )


def _source_index(source: SourceObservationIR) -> dict[str, dict[str, Any]]:
    is_slides = "ppt" in source.parser_manifest.parser_name.casefold()
    result: dict[str, dict[str, Any]] = {}
    for page in source.pages:
        page_number = page.physical_index + 1
        common = {
            "page": None if is_slides else page_number,
            "slide": page_number if is_slides else None,
        }
        result[page.page_id] = {
            **common,
            "text": "\n".join(
                block.text for block in page.blocks if block.text
            ),
            "bbox": None,
            "kind": "page",
            "asset_id": None,
        }
        for block in page.blocks:
            result[block.block_id] = {
                **common,
                "text": block.text,
                "bbox": _bbox(block.bbox),
                "kind": block.kind.value,
                "asset_id": None,
            }
        for obj in page.native_objects:
            text = obj.text
            if obj.formula:
                text = obj.formula.display_text
            elif obj.reaction:
                text = _reaction_text(obj)
            elif obj.table:
                text = "\n".join(
                    cell.text for cell in obj.table.cells if cell.text
                )
            result[obj.object_id] = {
                **common,
                "text": text,
                "bbox": _bbox(obj.bbox),
                "kind": obj.kind.value,
                "asset_id": (
                    obj.asset_ref.ref_id if obj.asset_ref else None
                ),
            }
            if obj.table:
                for cell in obj.table.cells:
                    result[cell.cell_id] = {
                        **common,
                        "text": cell.text,
                        "bbox": _bbox(cell.bbox),
                        "kind": "table_cell",
                        "asset_id": None,
                    }
    for outline in source.outline_entries:
        page = result.get(outline.target_page_id or "", {})
        result[outline.outline_entry_id] = {
            "page": page.get("page"),
            "slide": page.get("slide"),
            "text": outline.label,
            "bbox": None,
            "kind": "outline",
            "asset_id": None,
        }
    return result


def _legacy_evidence(
    evidence,
    source_index: dict[str, dict[str, Any]],
) -> LegacyEvidenceRef:
    source = source_index.get(evidence.ref_id, {})
    return LegacyEvidenceRef(
        unit_id=evidence.ref_id,
        excerpt=str(source.get("text", ""))[:2048],
        page=source.get("page"),
        slide=source.get("slide"),
        bbox=source.get("bbox"),
        asset_id=source.get("asset_id"),
    )


def _legacy_document(
    source: SourceObservationIR,
    *,
    filename: str,
    file_type: str,
    title: str,
) -> tuple[ParsedDocument, list[Chunk]]:
    is_slides = "ppt" in source.parser_manifest.parser_name.casefold()
    blocks: list[dict[str, Any]] = []
    chunks: list[Chunk] = []
    index = 0
    for page in source.pages:
        for block in page.blocks:
            page_number = page.physical_index + 1
            heading = (
                block.text
                if block.kind in {BlockKind.TITLE, BlockKind.HEADING}
                else None
            )
            blocks.append(
                {
                    "text": block.text,
                    "page": None if is_slides else page_number,
                    "slide": page_number if is_slides else None,
                    "heading": heading,
                }
            )
            chunks.append(
                Chunk(
                    id=block.block_id,
                    index=index,
                    text=block.text,
                    heading=heading,
                    page_start=None if is_slides else page_number,
                    page_end=None if is_slides else page_number,
                    slide_start=page_number if is_slides else None,
                    slide_end=page_number if is_slides else None,
                )
            )
            index += 1
    return (
        ParsedDocument(
            document_id=source.document_id,
            filename=filename,
            file_type=file_type,
            title=title,
            blocks=blocks,
            parse_metadata={
                "adapter": "vnext-legacy-result-1.0.0",
                "source_hash": source.source_hash,
                "source_revision": source.source_revision,
            },
            warnings=[],
        ),
        chunks,
    )


def _legacy_content_units(
    source: SourceObservationIR,
    inventory: SourceInventory,
    claims: ClaimLedger,
    omission: OmissionAudit,
    *,
    source_index: dict[str, dict[str, Any]],
) -> list[ContentUnit]:
    claim_by_source: dict[str, list] = defaultdict(list)
    for claim in claims.claims:
        for evidence in claim.source_evidence_refs:
            claim_by_source[evidence.ref_id].append(claim)
    accounted = set(omission.accounted_source_ids)
    nonclaim = set(omission.explicitly_nonclaim_source_ids)
    units: list[ContentUnit] = []
    for entry in sorted(
        inventory.all_entries(),
        key=lambda item: item.source_id,
    ):
        if entry.source_kind.value == "page":
            continue
        source_item = source_index.get(entry.source_id, {})
        linked_claims = claim_by_source.get(entry.source_id, [])
        role = (
            _UNIT_ROLE_MAP[linked_claims[0].instructional_role]
            if linked_claims
            else "other"
        )
        kind = (
            "visual"
            if entry.source_kind.value
            in {
                "formula_region",
                "reaction_region",
                "visual_region",
            }
            else "text"
        )
        status = (
            "covered"
            if entry.source_id in accounted
            else "rejected"
            if entry.source_id in nonclaim
            else "deferred"
        )
        units.append(
            ContentUnit(
                id=entry.source_id,
                document_id=source.document_id,
                kind=kind,
                importance=_importance(entry),
                status=status,
                text=str(source_item.get("text", "")),
                unit_role=role,
                evidence_excerpt=str(source_item.get("text", ""))[:2048],
                page=source_item.get("page"),
                slide=source_item.get("slide"),
                bbox=source_item.get("bbox"),
                asset_id=source_item.get("asset_id"),
                visual_kind=(
                    str(source_item.get("kind", ""))
                    if kind == "visual"
                    else None
                ),
                visual_action=(
                    "attach_as_media"
                    if kind == "visual"
                    else "unclassified"
                ),
                summary=(
                    linked_claims[0].normalized_text
                    if linked_claims
                    else ""
                ),
                knowledge_claims=[
                    claim.normalized_text for claim in linked_claims
                ],
            )
        )
    return units


def _coverage_summary(
    inventory: SourceInventory,
    omission: OmissionAudit,
) -> CoverageSummary:
    eligible = [
        entry
        for entry in inventory.all_entries()
        if entry.source_kind.value != "page"
    ]
    covered = set(omission.accounted_source_ids)
    return CoverageSummary(
        total_units=len(eligible),
        covered_units=sum(
            entry.source_id in covered for entry in eligible
        ),
        weighted_coverage=omission.must_have_recall,
        uncovered_unit_ids=sorted(
            {
                *omission.omitted_source_ids,
                *omission.unresolved_source_ids,
            }
        ),
        branch_coverage={},
    )


def _model_selection(
    manifest: RunManifest | None,
) -> ModelSelection:
    if manifest is None:
        return ModelSelection(
            generator_provider="vnext-shadow",
            verifier_provider="vnext-shadow",
        )
    slots = {
        slot.slot: slot for slot in manifest.declared.model_portfolio.slots
    }
    generator = (
        slots.get("global_structure_planner")
        or slots.get("claim_extractor")
    )
    verifier = (
        slots.get("verifier_a")
        or slots.get("region_decision_verifier")
    )
    vision = slots.get("vlm_reader")
    arbiter = slots.get("arbiter")
    return ModelSelection(
        generator_provider=(
            generator.provider if generator else "vnext-shadow"
        ),
        generator_model=(
            generator.model_revision if generator else None
        ),
        verifier_provider=(
            verifier.provider if verifier else "vnext-shadow"
        ),
        verifier_model=(
            verifier.model_revision if verifier else None
        ),
        vision_provider=vision.provider if vision else None,
        vision_model=vision.model_revision if vision else None,
        arbiter_provider=arbiter.provider if arbiter else None,
        arbiter_model=arbiter.model_revision if arbiter else None,
    )


def _decision_records(
    graph: CanonicalExplicitGraph,
    run_id: str,
    root_id: str,
) -> list[DecisionRecord]:
    records: list[DecisionRecord] = []
    records.extend(
        _decision_record(event, run_id, "run", root_id)
        for event in graph.decision_log
    )
    for concept in graph.concepts:
        records.extend(
            _decision_record(
                event,
                run_id,
                "node",
                concept.concept_id,
            )
            for event in concept.decision_history
        )
    for relation in graph.relations:
        subject_type = (
            "tree_edge"
            if relation.hierarchy_directness
            is HierarchyDirectness.DIRECT
            else "cross_link"
        )
        records.extend(
            _decision_record(
                event,
                run_id,
                subject_type,
                relation.relation_id,
            )
            for event in relation.decision_history
        )
    return sorted(records, key=lambda item: (item.timestamp, item.id))


def _decision_record(
    event: DecisionEvent,
    run_id: str,
    subject_type: str,
    subject_id: str,
) -> DecisionRecord:
    actor = (
        "human"
        if not isinstance(event.actor, RuntimeRole)
        else "model"
        if event.actor
        in {
            RuntimeRole.GLOBAL_STRUCTURE_PLANNER,
            RuntimeRole.RECURSIVE_REGION_PLANNER,
            RuntimeRole.CLAIM_ATOMIZER,
            RuntimeRole.CLAIM_FIDELITY_VERIFIER,
            RuntimeRole.DOMAIN_RESOLVER,
            RuntimeRole.RELATION_VERIFIER_A,
            RuntimeRole.RELATION_VERIFIER_B,
            RuntimeRole.ARBITER,
        }
        else "code"
    )
    return DecisionRecord(
        id=event.decision_id,
        run_id=run_id,
        subject_type=subject_type,
        subject_id=subject_id,
        actor=actor,
        actor_version=str(event.actor),
        decision=event.decision,
        reason_codes=list(event.reason_codes),
        evidence_unit_ids=[item.ref_id for item in event.evidence_refs],
        timestamp=event.created_at.isoformat(),
    )


def _legacy_votes(relation: CanonicalRelation) -> list[ModelVote]:
    return [
        ModelVote(
            actor=vote.verifier.producer_id,
            model=vote.verifier.model_revision,
            classification=vote.classification.value,
            score=1.0 if vote.supports_relation else 0.0,
            reason="; ".join(vote.reason_codes),
        )
        for vote in relation.verifier_decisions
    ]


def _definition(
    claim_ids: tuple[str, ...],
    claim_by_id: dict[str, Any],
) -> str:
    for claim_id in claim_ids:
        claim = claim_by_id.get(claim_id)
        if claim is not None:
            return claim.source_text or claim.normalized_text
    return ""


def _concept_confidence(concept) -> float:
    if not concept.confidence_components:
        return 1.0
    return sum(
        item.score for item in concept.confidence_components
    ) / len(concept.confidence_components)


def _relation_score(relation: CanonicalRelation) -> float:
    if not relation.verifier_decisions:
        return 0.0
    return sum(
        1.0 if item.supports_relation else 0.0
        for item in relation.verifier_decisions
    ) / len(relation.verifier_decisions)


def _depths(
    root_id: str,
    edges: tuple[tuple[str, str], ...],
) -> dict[str, int]:
    children: dict[str, list[str]] = defaultdict(list)
    for parent, child in edges:
        children[parent].append(child)
    depths = {root_id: 0}
    queue = deque([root_id])
    while queue:
        parent = queue.popleft()
        for child in sorted(children.get(parent, ())):
            if child in depths:
                continue
            depths[child] = depths[parent] + 1
            queue.append(child)
    return depths


def _bbox(value) -> list[float] | None:
    if value is None:
        return None
    return [value.x, value.y, value.width, value.height]


def _reaction_text(obj) -> str:
    reaction = obj.reaction
    if reaction is None:
        return obj.text
    reactants = " + ".join(item.label for item in reaction.reactants)
    products = " + ".join(item.label for item in reaction.products)
    return f"{reactants} {reaction.arrow} {products}".strip()


def _importance(entry: InventoryEntry) -> float:
    return {
        InventoryImportance.LOW: 0.25,
        InventoryImportance.NORMAL: 0.5,
        InventoryImportance.HIGH: 0.8,
        InventoryImportance.MUST_HAVE: 1.0,
    }[entry.importance]
