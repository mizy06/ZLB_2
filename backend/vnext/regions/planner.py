from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Protocol

from backend.vnext.artifacts.canonical import canonical_json_bytes
from backend.vnext.artifacts.local_store import LocalArtifactStore
from backend.vnext.contracts.artifacts import ArtifactEnvelope
from backend.vnext.contracts.common import (
    ArtifactProducerRef,
    ArtifactRef,
    ArtifactType,
    ProducerRef,
    RuntimeRole,
)
from backend.vnext.contracts.evidence import EvidenceRef
from backend.vnext.contracts.inventory import (
    InventoryEntry,
    InventoryEntryKind,
    InventoryImportance,
    InventoryInspectionStatus,
    SourceInventory,
)
from backend.vnext.contracts.model_semantics import (
    RegionDecisionVerification,
    RegionPlannerProposal,
    RegionVerificationVerdict,
)
from backend.vnext.contracts.regions import (
    GateAssessment,
    RegionChildLabel,
    RegionPlan,
    RegionPlanStatus,
    RegionProposalAction,
    RegionSourceAssignment,
    RegionSplitCertificate,
    SourceAssignmentDisposition,
    SplitDecision,
    SplitEvidenceMode,
    SplitProposal,
    StopProposal,
)
from backend.vnext.contracts.source import (
    BlockIR,
    BlockKind,
    OutlineEntryIR,
    SourceObservationIR,
)

from .gates import evaluate_split_certificate, evaluate_stop_proposal


REGION_PLANNER_VERSION = "1.0.0"
REGION_VERIFIER_VERSION = "1.0.0"

_FRAGMENT_PREFIX = re.compile(
    r"^(?:and|or|but|because|therefore|which|that|以及|并且|因此|由于)\b",
    re.IGNORECASE,
)
_DANGLING_SUFFIX = re.compile(
    r"(?:是|为|包括|由于|因此|从而|and|or|because|which|that)$",
    re.IGNORECASE,
)
_SEMANTIC_CHAR = re.compile(r"[A-Za-z0-9\u3400-\u9fffΑ-ω]")
_GENERIC_LABELS = frozenset(
    {
        "course content",
        "other topics",
        "other",
        "miscellaneous",
        "课程内容",
        "其他",
        "其他主题",
    }
)

_GLOBAL_PLANNER = ArtifactProducerRef(
    producer_id="vnext-explicit-global-region-planner",
    producer_version=REGION_PLANNER_VERSION,
    role=RuntimeRole.GLOBAL_STRUCTURE_PLANNER,
)
_RECURSIVE_PLANNER = ArtifactProducerRef(
    producer_id="vnext-explicit-recursive-region-planner",
    producer_version=REGION_PLANNER_VERSION,
    role=RuntimeRole.RECURSIVE_REGION_PLANNER,
)
_REGION_VERIFIER = ArtifactProducerRef(
    producer_id="vnext-explicit-region-decision-verifier",
    producer_version=REGION_VERIFIER_VERSION,
    role=RuntimeRole.REGION_DECISION_VERIFIER,
)
_SYNTHETIC_ANCHOR_PRODUCER = ProducerRef(
    producer_id="vnext-unresolved-root-anchor",
    producer_version=REGION_PLANNER_VERSION,
)


@dataclass(slots=True)
class _AnchorNode:
    entry: OutlineEntryIR
    position: tuple[int, int, int]
    support_source_ids: tuple[str, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    children: list["_AnchorNode"] = field(default_factory=list)
    region_id: str = ""


@dataclass(frozen=True, slots=True)
class RegionPlanningResult:
    final_plans: tuple[RegionPlan, ...]
    final_plan_envelopes: tuple[ArtifactEnvelope, ...]
    split_certificates: tuple[RegionSplitCertificate, ...]
    split_certificate_envelopes: tuple[ArtifactEnvelope, ...]
    accepted_plan_refs: tuple[ArtifactRef, ...]
    plan_ref_by_region: Mapping[str, ArtifactRef]
    source_to_leaf_region: Mapping[str, str]
    structurally_accounted_source_ids: tuple[str, ...]
    unresolved_source_ids: tuple[str, ...]
    root_region_id: str
    recorded_interaction_ids: tuple[str, ...] = ()
    repaired_decisions: int = 0
    model_providers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExplicitRegionDecisionContext:
    region_id: str
    anchor_source_id: str
    anchor_label: str
    parent_region_id: str | None
    ancestor_path: tuple[str, ...]
    child_anchor_source_ids: tuple[str, ...]
    child_anchor_labels: tuple[str, ...]
    primary_source_ids: tuple[str, ...]
    secondary_source_ids: tuple[str, ...]
    planner_role: RuntimeRole


@dataclass(frozen=True, slots=True)
class RegionSemanticDecision:
    proposal: RegionPlannerProposal
    verification: RegionDecisionVerification | None
    planner_producer: ArtifactProducerRef
    verifier_producer: ArtifactProducerRef | None
    interaction_ids: tuple[str, ...]
    repaired_decisions: int
    providers: tuple[str, ...]


class ExplicitRegionDecisionProvider(Protocol):
    def decide(
        self,
        context: ExplicitRegionDecisionContext,
    ) -> RegionSemanticDecision: ...

    def finish(self) -> None: ...


def load_region_planning_result(
    *,
    owner_id: str,
    root_plan_ref: ArtifactRef,
    store: LocalArtifactStore,
) -> RegionPlanningResult:
    """Reconstruct a committed region tree from immutable plan artifacts."""

    if root_plan_ref.artifact_type is not ArtifactType.REGION_PLAN:
        raise ValueError("root_plan_ref must reference RegionPlan")
    root_stored = store.get(
        owner_id=owner_id,
        artifact_id=root_plan_ref.artifact_id,
    )
    if not isinstance(root_stored.payload, RegionPlan):
        raise TypeError("root plan artifact payload is not RegionPlan")
    envelopes = tuple(
        envelope
        for envelope in store.list_envelopes(owner_id=owner_id)
        if envelope.artifact_type is ArtifactType.REGION_PLAN
    )
    candidates: dict[str, list[tuple[ArtifactEnvelope, RegionPlan]]] = {}
    for envelope in envelopes:
        stored = store.get(
            owner_id=owner_id,
            artifact_id=envelope.artifact_id,
        )
        if not isinstance(stored.payload, RegionPlan):
            continue
        if stored.payload.status is RegionPlanStatus.PROPOSED:
            continue
        candidates.setdefault(stored.payload.region_id, []).append(
            (envelope, stored.payload)
        )

    selected: list[tuple[ArtifactEnvelope, RegionPlan]] = [
        (root_stored.envelope, root_stored.payload)
    ]
    seen = {root_stored.payload.region_id}
    stack = list(reversed(root_stored.payload.child_region_ids))
    while stack:
        region_id = stack.pop()
        if region_id in seen:
            continue
        options = candidates.get(region_id, [])
        if not options:
            raise ValueError(
                f"committed region tree is missing child {region_id}"
            )
        envelope, plan = max(
            options,
            key=lambda item: (
                item[0].created_at,
                item[0].artifact_id,
            ),
        )
        selected.append((envelope, plan))
        seen.add(region_id)
        stack.extend(reversed(plan.child_region_ids))

    certificates: list[RegionSplitCertificate] = []
    certificate_envelopes: list[ArtifactEnvelope] = []
    accepted_refs: list[ArtifactRef] = []
    ref_by_region: dict[str, ArtifactRef] = {}
    source_to_leaf: dict[str, str] = {}
    structurally_accounted: set[str] = set()
    unresolved_sources: set[str] = set()
    for envelope, plan in selected:
        plan_ref = store.ref(envelope)
        ref_by_region[plan.region_id] = plan_ref
        unresolved_sources.update(plan.unresolved_source_ids)
        if plan.status is RegionPlanStatus.ACCEPTED:
            accepted_refs.append(plan_ref)
        if (
            plan.status is RegionPlanStatus.ACCEPTED
            and plan.proposed_action is RegionProposalAction.STOP
        ):
            for source_id in plan.primary_source_memberships:
                source_to_leaf.setdefault(source_id, plan.region_id)
        if plan.split_certificate_ref is None:
            continue
        stored_certificate = store.get(
            owner_id=owner_id,
            artifact_id=plan.split_certificate_ref.artifact_id,
        )
        if not isinstance(
            stored_certificate.payload,
            RegionSplitCertificate,
        ):
            raise TypeError(
                "split certificate artifact has the wrong payload"
            )
        certificates.append(stored_certificate.payload)
        certificate_envelopes.append(stored_certificate.envelope)
        for assignment in stored_certificate.payload.source_assignment_map:
            if assignment.disposition in {
                SourceAssignmentDisposition.EXPLICITLY_NONCLAIM,
                SourceAssignmentDisposition.SECONDARY_CROSS_CUTTING,
            }:
                structurally_accounted.add(assignment.source_id)
            elif assignment.disposition is (
                SourceAssignmentDisposition.UNRESOLVED
            ):
                unresolved_sources.add(assignment.source_id)

    return RegionPlanningResult(
        final_plans=tuple(plan for _, plan in selected),
        final_plan_envelopes=tuple(
            envelope for envelope, _ in selected
        ),
        split_certificates=tuple(certificates),
        split_certificate_envelopes=tuple(certificate_envelopes),
        accepted_plan_refs=tuple(accepted_refs),
        plan_ref_by_region=MappingProxyType(ref_by_region),
        source_to_leaf_region=MappingProxyType(source_to_leaf),
        structurally_accounted_source_ids=tuple(
            sorted(structurally_accounted)
        ),
        unresolved_source_ids=tuple(sorted(unresolved_sources)),
        root_region_id=root_stored.payload.region_id,
    )


def _stable_id(prefix: str, value: object) -> str:
    digest = hashlib.sha256(
        b"zlb-vnext-region-id-v1\0" + canonical_json_bytes(value)
    ).hexdigest()
    return prefix + digest[:32]


def _unique_evidence(
    evidence_refs: list[EvidenceRef],
) -> tuple[EvidenceRef, ...]:
    unique: dict[tuple[str, str], EvidenceRef] = {}
    for evidence in evidence_refs:
        unique[(evidence.namespace.value, evidence.ref_id)] = evidence
    return tuple(unique.values())


def _normalized(text: str) -> str:
    return " ".join(text.split()).strip()


def _label_is_self_contained(label: str) -> bool:
    value = _normalized(label)
    folded = value.casefold()
    if not 2 <= len(value) <= 160:
        return False
    if folded in _GENERIC_LABELS:
        return False
    if _FRAGMENT_PREFIX.search(value) or _DANGLING_SUFFIX.search(value):
        return False
    if not _SEMANTIC_CHAR.search(value):
        return False
    if value.endswith((",", "，", ":", "：", ";", "；")):
        return False
    return True


def _source_positions(
    source: SourceObservationIR,
) -> tuple[
    dict[str, tuple[int, int, int]],
    dict[str, BlockIR],
]:
    positions: dict[str, tuple[int, int, int]] = {}
    blocks_by_id: dict[str, BlockIR] = {}
    page_index_by_id = {
        page.page_id: page.physical_index for page in source.pages
    }
    for page in source.pages:
        positions[page.page_id] = (page.physical_index, -1000, 0)
        for object_index, obj in enumerate(page.native_objects):
            order = (
                obj.native_order_hint
                if obj.native_order_hint is not None
                else object_index
            )
            positions[obj.object_id] = (page.physical_index, order, 10)
            if obj.table is not None:
                for cell_index, cell in enumerate(obj.table.cells):
                    positions[cell.cell_id] = (
                        page.physical_index,
                        order,
                        20 + cell_index,
                    )
        for block_index, block in enumerate(page.blocks):
            order = (
                block.native_order_hint
                if block.native_order_hint is not None
                else block_index
            )
            positions[block.block_id] = (page.physical_index, order, 30)
            blocks_by_id[block.block_id] = block
    for item in source.outline_entries:
        matches = [
            block
            for page in source.pages
            if page.page_id == item.target_page_id
            for block in page.blocks
            if block.kind in {BlockKind.TITLE, BlockKind.HEADING}
            and _normalized(block.text).casefold()
            == _normalized(item.label).casefold()
        ]
        if matches:
            positions[item.outline_entry_id] = positions[
                matches[0].block_id
            ]
        elif item.target_page_id in page_index_by_id:
            positions[item.outline_entry_id] = (
                page_index_by_id[item.target_page_id],
                -900 + item.source_order,
                0,
            )
    for item in source.unresolved_regions:
        positions[item.region_source_id] = (
            page_index_by_id[item.page_id],
            1_000_000,
            0,
        )
    return positions, blocks_by_id


def _anchor_nodes(
    source: SourceObservationIR,
    positions: Mapping[str, tuple[int, int, int]],
) -> list[_AnchorNode]:
    nodes: list[_AnchorNode] = []
    for entry in sorted(
        source.outline_entries,
        key=lambda item: item.source_order,
    ):
        matching_blocks = tuple(
            block
            for page in source.pages
            if page.page_id == entry.target_page_id
            for block in page.blocks
            if block.kind in {BlockKind.TITLE, BlockKind.HEADING}
            and _normalized(block.text).casefold()
            == _normalized(entry.label).casefold()
        )
        evidence = list(entry.evidence_refs)
        support_ids = [entry.outline_entry_id]
        for block in matching_blocks:
            support_ids.append(block.block_id)
            evidence.extend(block.evidence_refs)
        nodes.append(
            _AnchorNode(
                entry=entry,
                position=positions.get(
                    entry.outline_entry_id,
                    (0, entry.source_order, 0),
                ),
                support_source_ids=tuple(support_ids),
                evidence_refs=_unique_evidence(evidence),
            )
        )

    roots: list[_AnchorNode] = []
    stack: list[_AnchorNode] = []
    for node in nodes:
        while (
            stack
            and node.entry.observed_level
            <= stack[-1].entry.observed_level
        ):
            stack.pop()
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)
    return roots


def _assign_region_ids(
    node: _AnchorNode,
    *,
    source_hash: str,
    parent_path: tuple[str, ...],
) -> None:
    node.region_id = _stable_id(
        "reg_",
        {
            "anchor": node.entry.outline_entry_id,
            "parent_path": parent_path,
            "source_hash": source_hash,
        },
    )
    for child in node.children:
        _assign_region_ids(
            child,
            source_hash=source_hash,
            parent_path=(*parent_path, node.region_id),
        )


def _entry_by_source(
    inventory: SourceInventory,
) -> dict[str, InventoryEntry]:
    return {entry.source_id: entry for entry in inventory.all_entries()}


def _child_assignments(
    *,
    parent: _AnchorNode,
    children: tuple[_AnchorNode, ...],
    scope_source_ids: tuple[str, ...],
    inventory_by_source: Mapping[str, InventoryEntry],
    positions: Mapping[str, tuple[int, int, int]],
) -> tuple[
    tuple[RegionSourceAssignment, ...],
    dict[str, list[str]],
    dict[str, list[str]],
    set[str],
    set[str],
]:
    primary: dict[str, list[str]] = {
        child.region_id: [] for child in children
    }
    secondary: dict[str, list[str]] = {
        child.region_id: [] for child in children
    }
    structurally_accounted: set[str] = set()
    unresolved: set[str] = set()
    support_owner = {
        source_id: child.region_id
        for child in children
        for source_id in child.support_source_ids
    }
    parent_support = set(parent.support_source_ids)
    ordered_children = tuple(sorted(children, key=lambda item: item.position))
    assignments: list[RegionSourceAssignment] = []
    child_pages: dict[int, tuple[str, ...]] = {}
    for page_index in {
        child.position[0] for child in ordered_children
    }:
        child_pages[page_index] = tuple(
            child.region_id
            for child in ordered_children
            if child.position[0] == page_index
        )

    for source_id in scope_source_ids:
        entry = inventory_by_source[source_id]
        if (
            entry.source_kind is InventoryEntryKind.UNRESOLVED
            or entry.inspection_status
            is InventoryInspectionStatus.UNRESOLVED
        ):
            assignments.append(
                RegionSourceAssignment(
                    source_id=source_id,
                    disposition=SourceAssignmentDisposition.UNRESOLVED,
                    rationale="Source observation remains explicitly unresolved.",
                )
            )
            unresolved.add(source_id)
            continue
        if source_id in parent_support:
            assignments.append(
                RegionSourceAssignment(
                    source_id=source_id,
                    disposition=(
                        SourceAssignmentDisposition.EXPLICITLY_NONCLAIM
                    ),
                    rationale=(
                        "Source object is the accepted parent structure "
                        "anchor, not a leaf claim denominator."
                    ),
                )
            )
            structurally_accounted.add(source_id)
            continue
        owner = support_owner.get(source_id)
        if owner is not None:
            primary[owner].append(source_id)
            assignments.append(
                RegionSourceAssignment(
                    source_id=source_id,
                    disposition=SourceAssignmentDisposition.PRIMARY_REGION,
                    region_ids=(owner,),
                    rationale="Explicit child outline/title support.",
                )
            )
            continue
        position = positions.get(source_id)
        if entry.source_kind is InventoryEntryKind.PAGE and position:
            page_regions = child_pages.get(position[0], ())
            if page_regions:
                for region_id in page_regions:
                    secondary[region_id].append(source_id)
                assignments.append(
                    RegionSourceAssignment(
                        source_id=source_id,
                        disposition=(
                            SourceAssignmentDisposition
                            .SECONDARY_CROSS_CUTTING
                        ),
                        region_ids=page_regions,
                        rationale=(
                            "Page container spans one or more explicit "
                            "child anchors."
                        ),
                    )
                )
                structurally_accounted.add(source_id)
                continue
        if position is None:
            assignments.append(
                RegionSourceAssignment(
                    source_id=source_id,
                    disposition=SourceAssignmentDisposition.UNRESOLVED,
                    rationale="No deterministic source-order position.",
                )
            )
            unresolved.add(source_id)
            continue
        selected = ordered_children[0]
        for child in ordered_children:
            if child.position <= position:
                selected = child
            else:
                break
        primary[selected.region_id].append(source_id)
        assignments.append(
            RegionSourceAssignment(
                source_id=source_id,
                disposition=SourceAssignmentDisposition.PRIMARY_REGION,
                region_ids=(selected.region_id,),
                rationale=(
                    "Source-order interval under the nearest explicit "
                    "child anchor."
                ),
            )
        )
    return (
        tuple(assignments),
        primary,
        secondary,
        structurally_accounted,
        unresolved,
    )


def _decision_context(
    node: _AnchorNode,
    *,
    parent_region_id: str | None,
    ancestor_path: tuple[str, ...],
    primary_source_ids: tuple[str, ...],
    secondary_source_ids: tuple[str, ...],
) -> ExplicitRegionDecisionContext:
    return ExplicitRegionDecisionContext(
        region_id=node.region_id,
        anchor_source_id=node.entry.outline_entry_id,
        anchor_label=node.entry.label,
        parent_region_id=parent_region_id,
        ancestor_path=ancestor_path,
        child_anchor_source_ids=tuple(
            child.entry.outline_entry_id for child in node.children
        ),
        child_anchor_labels=tuple(
            child.entry.label for child in node.children
        ),
        primary_source_ids=primary_source_ids,
        secondary_source_ids=secondary_source_ids,
        planner_role=(
            RuntimeRole.GLOBAL_STRUCTURE_PLANNER
            if parent_region_id is None
            else RuntimeRole.RECURSIVE_REGION_PLANNER
        ),
    )


def enumerate_explicit_region_decision_contexts(
    source: SourceObservationIR,
    inventory: SourceInventory,
) -> tuple[ExplicitRegionDecisionContext, ...]:
    """Return all potential explicit split/stop contexts in preorder."""

    positions, _ = _source_positions(source)
    roots = _anchor_nodes(source, positions)
    if len(roots) != 1:
        return ()
    root = roots[0]
    _assign_region_ids(
        root,
        source_hash=source.source_hash,
        parent_path=(),
    )
    inventory_by_source = _entry_by_source(inventory)
    contexts: list[ExplicitRegionDecisionContext] = []

    def visit(
        node: _AnchorNode,
        *,
        parent_region_id: str | None,
        ancestor_path: tuple[str, ...],
        primary_source_ids: tuple[str, ...],
        secondary_source_ids: tuple[str, ...],
    ) -> None:
        children = tuple(node.children)
        if len(children) == 1:
            return
        contexts.append(
            _decision_context(
                node,
                parent_region_id=parent_region_id,
                ancestor_path=ancestor_path,
                primary_source_ids=primary_source_ids,
                secondary_source_ids=secondary_source_ids,
            )
        )
        if not children:
            return
        (
            _,
            child_primary,
            child_secondary,
            _,
            _,
        ) = _child_assignments(
            parent=node,
            children=children,
            scope_source_ids=primary_source_ids,
            inventory_by_source=inventory_by_source,
            positions=positions,
        )
        child_ancestor_path = (*ancestor_path, node.region_id)
        for child in children:
            visit(
                child,
                parent_region_id=node.region_id,
                ancestor_path=child_ancestor_path,
                primary_source_ids=tuple(
                    child_primary[child.region_id]
                ),
                secondary_source_ids=tuple(
                    child_secondary[child.region_id]
                ),
            )

    visit(
        root,
        parent_region_id=None,
        ancestor_path=(),
        primary_source_ids=tuple(
            entry.source_id for entry in inventory.all_entries()
        ),
        secondary_source_ids=(),
    )
    return tuple(contexts)


def _planner_for(parent_region_id: str | None) -> ArtifactProducerRef:
    return _GLOBAL_PLANNER if parent_region_id is None else _RECURSIVE_PLANNER


def _planner_name(parent_region_id: str | None) -> str:
    return (
        "global_structure_planner"
        if parent_region_id is None
        else "recursive_region_planner"
    )


def _unresolved_plan(
    *,
    node: _AnchorNode,
    parent_region_id: str | None,
    ancestor_path: tuple[str, ...],
    primary_source_ids: tuple[str, ...],
    secondary_source_ids: tuple[str, ...],
    unresolved_source_ids: tuple[str, ...],
    reason: str,
    plan_version: int = 1,
    supersedes: ArtifactRef | None = None,
) -> RegionPlan:
    unresolved = set(unresolved_source_ids)
    primary = tuple(
        source_id
        for source_id in primary_source_ids
        if source_id not in unresolved
    )
    return RegionPlan(
        region_id=node.region_id,
        plan_version=plan_version,
        parent_region_id=parent_region_id,
        ancestor_path=ancestor_path,
        theme_label=node.entry.label,
        theme_definition=reason,
        primary_source_memberships=primary,
        secondary_source_memberships=secondary_source_ids,
        unresolved_source_ids=tuple(sorted(unresolved)),
        proposed_action=RegionProposalAction.UNRESOLVED,
        evidence_refs=node.evidence_refs,
        planner_attempt=1,
        planner=_planner_name(parent_region_id),
        status=RegionPlanStatus.UNRESOLVED,
        supersedes=supersedes,
    )


def plan_explicit_regions(
    source: SourceObservationIR,
    inventory: SourceInventory,
    *,
    owner_id: str,
    source_ref: ArtifactRef,
    inventory_ref: ArtifactRef,
    store: LocalArtifactStore,
    decision_provider: ExplicitRegionDecisionProvider | None = None,
) -> RegionPlanningResult:
    """Persist an explicit-only, top-down RegionPlan tree."""

    positions, _ = _source_positions(source)
    roots = _anchor_nodes(source, positions)
    inventory_by_source = _entry_by_source(inventory)
    all_source_ids = tuple(entry.source_id for entry in inventory.all_entries())
    final_plans: list[RegionPlan] = []
    final_envelopes: list[ArtifactEnvelope] = []
    certificates: list[RegionSplitCertificate] = []
    certificate_envelopes: list[ArtifactEnvelope] = []
    accepted_refs: list[ArtifactRef] = []
    ref_by_region: dict[str, ArtifactRef] = {}
    source_to_leaf: dict[str, str] = {}
    structurally_accounted: set[str] = set()
    unresolved_sources: set[str] = set()
    recorded_interaction_ids: list[str] = []
    repaired_decisions = 0
    model_providers: set[str] = set()

    def recorded_decision(
        context: ExplicitRegionDecisionContext,
    ) -> RegionSemanticDecision | None:
        nonlocal repaired_decisions
        if decision_provider is None:
            return None
        decision = decision_provider.decide(context)
        if decision.planner_producer.role is not context.planner_role:
            raise ValueError(
                "recorded region planner producer role mismatch"
            )
        if decision.proposal.action is RegionProposalAction.UNRESOLVED:
            if (
                decision.verification is not None
                or decision.verifier_producer is not None
            ):
                raise ValueError(
                    "unresolved region proposal cannot carry verifier output"
                )
        elif (
            decision.verification is None
            or decision.verifier_producer is None
            or decision.verifier_producer.role
            is not RuntimeRole.REGION_DECISION_VERIFIER
        ):
            raise ValueError(
                "recorded split/stop requires region decision verifier"
            )
        recorded_interaction_ids.extend(decision.interaction_ids)
        repaired_decisions += decision.repaired_decisions
        model_providers.update(decision.providers)
        return decision

    if len(roots) != 1:
        evidence = tuple(
            page.render_ref for page in source.pages[:1]
        )
        synthetic_entry = OutlineEntryIR(
            outline_entry_id=source.document_id,
            label="Unresolved document structure",
            observed_level=1,
            source_order=0,
            target_page_id=source.pages[0].page_id,
            native_target=None,
            producer=_SYNTHETIC_ANCHOR_PRODUCER,
            evidence_refs=evidence,
        )
        root = _AnchorNode(
            entry=synthetic_entry,
            position=(0, -1000, 0),
            support_source_ids=(),
            evidence_refs=evidence,
            region_id=_stable_id(
                "reg_",
                {
                    "document": source.document_id,
                    "reason": "missing_unique_explicit_root",
                },
            ),
        )
        plan = _unresolved_plan(
            node=root,
            parent_region_id=None,
            ancestor_path=(),
            primary_source_ids=all_source_ids,
            secondary_source_ids=(),
            unresolved_source_ids=all_source_ids,
            reason=(
                "A unique explicit root could not be proven from source "
                "outline/title observations."
            ),
        )
        envelope = store.put(
            owner_id=owner_id,
            role=RuntimeRole.GLOBAL_STRUCTURE_PLANNER,
            payload=plan,
            producer=_GLOBAL_PLANNER,
            input_refs=(source_ref, inventory_ref),
        )
        final_plans.append(plan)
        final_envelopes.append(envelope)
        ref_by_region[root.region_id] = store.ref(envelope)
        unresolved_sources.update(all_source_ids)
        if decision_provider is not None:
            decision_provider.finish()
        return RegionPlanningResult(
            final_plans=tuple(final_plans),
            final_plan_envelopes=tuple(final_envelopes),
            split_certificates=(),
            split_certificate_envelopes=(),
            accepted_plan_refs=(),
            plan_ref_by_region=MappingProxyType(ref_by_region),
            source_to_leaf_region=MappingProxyType(source_to_leaf),
            structurally_accounted_source_ids=(),
            unresolved_source_ids=tuple(sorted(unresolved_sources)),
            root_region_id=root.region_id,
            recorded_interaction_ids=(),
            repaired_decisions=0,
            model_providers=(),
        )

    root = roots[0]
    _assign_region_ids(
        root,
        source_hash=source.source_hash,
        parent_path=(),
    )

    def persist_node(
        node: _AnchorNode,
        *,
        parent_region_id: str | None,
        ancestor_path: tuple[str, ...],
        primary_source_ids: tuple[str, ...],
        secondary_source_ids: tuple[str, ...],
    ) -> None:
        children = tuple(node.children)
        context = _decision_context(
            node,
            parent_region_id=parent_region_id,
            ancestor_path=ancestor_path,
            primary_source_ids=primary_source_ids,
            secondary_source_ids=secondary_source_ids,
        )
        semantic = (
            recorded_decision(context)
            if len(children) != 1
            else None
        )
        planner = (
            semantic.planner_producer
            if semantic is not None
            else _planner_for(parent_region_id)
        )
        planner_role = planner.role
        input_refs = (
            source_ref,
            inventory_ref,
            *(
                (ref_by_region[parent_region_id],)
                if parent_region_id in ref_by_region
                else ()
            ),
        )
        if len(children) == 1:
            plan = _unresolved_plan(
                node=node,
                parent_region_id=parent_region_id,
                ancestor_path=ancestor_path,
                primary_source_ids=primary_source_ids,
                secondary_source_ids=secondary_source_ids,
                unresolved_source_ids=primary_source_ids,
                reason=(
                    "Exactly one stable child anchor remains; neither a "
                    "semantic split nor a leaf STOP can be certified."
                ),
            )
            envelope = store.put(
                owner_id=owner_id,
                role=planner_role,
                payload=plan,
                producer=planner,
                input_refs=input_refs,
            )
            final_plans.append(plan)
            final_envelopes.append(envelope)
            ref_by_region[node.region_id] = store.ref(envelope)
            unresolved_sources.update(primary_source_ids)
            return

        if (
            semantic is not None
            and semantic.proposal.action
            is RegionProposalAction.UNRESOLVED
        ):
            plan = _unresolved_plan(
                node=node,
                parent_region_id=parent_region_id,
                ancestor_path=ancestor_path,
                primary_source_ids=primary_source_ids,
                secondary_source_ids=secondary_source_ids,
                unresolved_source_ids=primary_source_ids,
                reason=semantic.proposal.rationale,
            )
            envelope = store.put(
                owner_id=owner_id,
                role=planner_role,
                payload=plan,
                producer=planner,
                input_refs=input_refs,
            )
            final_plans.append(plan)
            final_envelopes.append(envelope)
            ref_by_region[node.region_id] = store.ref(envelope)
            unresolved_sources.update(primary_source_ids)
            return

        if not children:
            if (
                semantic is not None
                and semantic.proposal.action
                is not RegionProposalAction.STOP
            ):
                raise ValueError(
                    "recorded leaf region proposal must STOP or abstain"
                )
            high_unresolved = tuple(
                source_id
                for source_id in primary_source_ids
                if inventory_by_source[source_id].inspection_status
                is InventoryInspectionStatus.UNRESOLVED
                and inventory_by_source[source_id].importance
                in {
                    InventoryImportance.HIGH,
                    InventoryImportance.MUST_HAVE,
                }
            )
            if semantic is None:
                single_instructional_intent = True
                claims_have_comparable_granularity = True
                further_split_would_fragment_or_duplicate = True
                no_mixed_theme_evidence = True
                stop_rationale = (
                    "The explicit source anchor has no stable child "
                    "heading; further structure would be non-explicit."
                )
                decision_verifier = _REGION_VERIFIER
            else:
                proposal_assessment = (
                    semantic.proposal.stop_assessment
                )
                verification = semantic.verification
                verifier_assessment = (
                    verification.stop_assessment
                    if verification is not None
                    else None
                )
                if (
                    proposal_assessment is None
                    or verifier_assessment is None
                    or semantic.verifier_producer is None
                ):
                    raise ValueError(
                        "recorded STOP decision is incomplete"
                    )
                verifier_accepted = (
                    verification.verdict
                    is RegionVerificationVerdict.ACCEPT
                )
                single_instructional_intent = (
                    proposal_assessment.single_instructional_intent
                    and verifier_assessment.single_instructional_intent
                    and verifier_accepted
                )
                claims_have_comparable_granularity = (
                    proposal_assessment
                    .claims_have_comparable_granularity
                    and verifier_assessment
                    .claims_have_comparable_granularity
                    and verifier_accepted
                )
                further_split_would_fragment_or_duplicate = (
                    proposal_assessment
                    .further_split_would_fragment_or_duplicate
                    and verifier_assessment
                    .further_split_would_fragment_or_duplicate
                    and verifier_accepted
                )
                no_mixed_theme_evidence = (
                    proposal_assessment.no_mixed_theme_evidence
                    and verifier_assessment.no_mixed_theme_evidence
                    and verifier_accepted
                )
                stop_rationale = (
                    semantic.proposal.rationale
                    + " Independent verification: "
                    + verification.rationale
                )
                decision_verifier = semantic.verifier_producer
            stop = StopProposal(
                single_instructional_intent=single_instructional_intent,
                no_unhandled_stable_subheading=True,
                claims_have_comparable_granularity=(
                    claims_have_comparable_granularity
                ),
                inventory_reconciled=True,
                further_split_would_fragment_or_duplicate=(
                    further_split_would_fragment_or_duplicate
                ),
                no_high_importance_omission=not high_unresolved,
                no_mixed_theme_evidence=no_mixed_theme_evidence,
                rationale=stop_rationale,
                evidence_refs=node.evidence_refs,
            )
            stop_primary = tuple(
                source_id
                for source_id in primary_source_ids
                if source_id not in set(high_unresolved)
            )
            proposed = RegionPlan(
                region_id=node.region_id,
                plan_version=1,
                parent_region_id=parent_region_id,
                ancestor_path=ancestor_path,
                theme_label=node.entry.label,
                theme_definition=(
                    semantic.proposal.rationale
                    if semantic is not None
                    else (
                        "Explicit leaf region anchored by source "
                        "outline/title."
                    )
                ),
                primary_source_memberships=stop_primary,
                secondary_source_memberships=secondary_source_ids,
                unresolved_source_ids=high_unresolved,
                proposed_action=RegionProposalAction.STOP,
                stop_proposal=stop,
                evidence_refs=node.evidence_refs,
                planner_attempt=1,
                planner=_planner_name(parent_region_id),
                status=RegionPlanStatus.PROPOSED,
            )
            proposed_envelope = store.put(
                owner_id=owner_id,
                role=planner_role,
                payload=proposed,
                producer=planner,
                input_refs=input_refs,
            )
            proposed_ref = store.ref(proposed_envelope)
            gate = evaluate_stop_proposal(stop)
            if gate.accepted:
                final = proposed.model_copy(
                    update={
                        "plan_version": 2,
                        "decision_verifier": decision_verifier,
                        "status": RegionPlanStatus.ACCEPTED,
                        "supersedes": proposed_ref,
                    }
                )
                envelope = store.put(
                    owner_id=owner_id,
                    role=planner_role,
                    payload=final,
                    producer=planner,
                    input_refs=(*input_refs, proposed_ref),
                    supersedes=proposed_ref,
                )
                final_ref = store.ref(envelope)
                accepted_refs.append(final_ref)
                ref_by_region[node.region_id] = final_ref
                for source_id in stop_primary:
                    source_to_leaf.setdefault(source_id, node.region_id)
            else:
                final = _unresolved_plan(
                    node=node,
                    parent_region_id=parent_region_id,
                    ancestor_path=ancestor_path,
                    primary_source_ids=primary_source_ids,
                    secondary_source_ids=secondary_source_ids,
                    unresolved_source_ids=primary_source_ids,
                    reason="; ".join(gate.reason_codes),
                    plan_version=2,
                    supersedes=proposed_ref,
                )
                envelope = store.put(
                    owner_id=owner_id,
                    role=planner_role,
                    payload=final,
                    producer=planner,
                    input_refs=(*input_refs, proposed_ref),
                    supersedes=proposed_ref,
                )
                ref_by_region[node.region_id] = store.ref(envelope)
                unresolved_sources.update(primary_source_ids)
            final_plans.append(final)
            final_envelopes.append(envelope)
            return

        if (
            semantic is not None
            and semantic.proposal.action
            is not RegionProposalAction.SPLIT
        ):
            raise ValueError(
                "recorded non-leaf region proposal must SPLIT or abstain"
            )
        (
            assignments,
            child_primary,
            child_secondary,
            structural_ids,
            unresolved_ids,
        ) = _child_assignments(
            parent=node,
            children=children,
            scope_source_ids=primary_source_ids,
            inventory_by_source=inventory_by_source,
            positions=positions,
        )
        child_ids = tuple(child.region_id for child in children)
        evidence_modes = (
            SplitEvidenceMode.OUTLINE,
            SplitEvidenceMode.TITLE,
        )
        partitioned_ids = structural_ids | unresolved_ids
        plan_primary_ids = tuple(
            source_id
            for source_id in primary_source_ids
            if source_id not in partitioned_ids
        )
        proposed = RegionPlan(
            region_id=node.region_id,
            plan_version=1,
            parent_region_id=parent_region_id,
            ancestor_path=ancestor_path,
            theme_label=node.entry.label,
            theme_definition=(
                semantic.proposal.rationale
                if semantic is not None
                else (
                    "Explicit source region partitioned only by observed "
                    "outline/title anchors."
                )
            ),
            primary_source_memberships=plan_primary_ids,
            secondary_source_memberships=secondary_source_ids,
            explicitly_excluded_source_ids=tuple(sorted(structural_ids)),
            unresolved_source_ids=tuple(sorted(unresolved_ids)),
            child_region_ids=child_ids,
            proposed_action=RegionProposalAction.SPLIT,
            split_proposal=SplitProposal(
                child_region_ids=child_ids,
                rationale=(
                    semantic.proposal.rationale
                    if semantic is not None
                    else (
                        "Direct child outline/title anchors define the "
                        "split."
                    )
                ),
                evidence_modes=evidence_modes,
                evidence_refs=_unique_evidence(
                    [
                        evidence
                        for child in children
                        for evidence in child.evidence_refs
                    ]
                ),
            ),
            evidence_refs=node.evidence_refs,
            planner_attempt=1,
            planner=_planner_name(parent_region_id),
            status=RegionPlanStatus.PROPOSED,
        )
        proposed_envelope = store.put(
            owner_id=owner_id,
            role=planner_role,
            payload=proposed,
            producer=planner,
            input_refs=input_refs,
        )
        proposed_ref = store.ref(proposed_envelope)
        if semantic is None:
            split_assessment = None
            verification = None
            verifier_accepted = True
            verifier = _REGION_VERIFIER
        else:
            verification = semantic.verification
            split_assessment = (
                verification.split_assessment
                if verification is not None
                else None
            )
            if (
                split_assessment is None
                or semantic.verifier_producer is None
            ):
                raise ValueError(
                    "recorded SPLIT decision is incomplete"
                )
            verifier_accepted = (
                verification.verdict
                is RegionVerificationVerdict.ACCEPT
            )
            verifier = semantic.verifier_producer
        child_labels = tuple(
            RegionChildLabel(
                child_region_id=child.region_id,
                label=child.entry.label,
                label_self_contained=(
                    _label_is_self_contained(child.entry.label)
                    and (
                        split_assessment is None
                        or split_assessment.child_labels_self_contained
                    )
                ),
                has_independent_source_support=bool(child.evidence_refs),
                source_support_refs=child.evidence_refs,
            )
            for child in children
        )
        labels_distinct = len(
            {_normalized(child.entry.label).casefold() for child in children}
        ) == len(children)
        label_levels = [child.entry.observed_level for child in children]
        accepted_shape = (
            all(item.label_self_contained for item in child_labels)
            and labels_distinct
            and all(child_primary[child.region_id] for child in children)
            and verifier_accepted
        )
        certificate = RegionSplitCertificate(
            parent_region_id=node.region_id,
            parent_common_concept=node.entry.label,
            parent_common_concept_supported=(
                bool(node.evidence_refs)
                and (
                    split_assessment is None
                    or split_assessment.parent_common_concept_supported
                )
            ),
            child_region_ids=child_ids,
            child_labels=child_labels,
            source_assignment_map=assignments,
            boundary_evidence=_unique_evidence(
                [
                    evidence
                    for child in children
                    for evidence in child.evidence_refs
                ]
            ),
            sibling_separation=GateAssessment(
                passed=(
                    labels_distinct
                    and (
                        split_assessment is None
                        or split_assessment.sibling_separation
                    )
                ),
                rationale=(
                    verification.rationale
                    if verification is not None
                    else (
                        "Sibling labels are distinct explicit source "
                        "anchors."
                        if labels_distinct
                        else (
                            "Sibling labels collide after normalization."
                        )
                    )
                ),
                evidence_refs=_unique_evidence(
                    [
                        evidence
                        for child in children
                        for evidence in child.evidence_refs
                    ]
                ),
            ),
            within_region_cohesion=GateAssessment(
                passed=(
                    split_assessment is None
                    or split_assessment.within_region_cohesion
                ),
                rationale=(
                    verification.rationale
                    if verification is not None
                    else (
                        "Each child is a deterministic source-order "
                        "interval under one explicit anchor."
                    )
                ),
                evidence_refs=_unique_evidence(
                    [
                        evidence
                        for child in children
                        for evidence in child.evidence_refs
                    ]
                ),
            ),
            sibling_granularity_comparable=(
                max(label_levels) - min(label_levels) <= 1
                and (
                    split_assessment is None
                    or (
                        split_assessment
                        .sibling_granularity_comparable
                    )
                )
            ),
            boundaries_explainable=(
                split_assessment is None
                or split_assessment.boundaries_explainable
            ),
            inventory_reconciled=(
                {item.source_id for item in assignments}
                == set(primary_source_ids)
            ),
            residual_source_ids=tuple(sorted(unresolved_ids)),
            cross_cutting_source_ids=tuple(
                sorted(
                    item.source_id
                    for item in assignments
                    if item.disposition
                    is SourceAssignmentDisposition.SECONDARY_CROSS_CUTTING
                )
            ),
            uses_capacity_as_semantic_evidence=False,
            decision=(
                SplitDecision.ACCEPT_SPLIT
                if accepted_shape
                else SplitDecision.REJECT_SPLIT
            ),
            verifier=verifier,
        )
        certificate_envelope = store.put(
            owner_id=owner_id,
            role=RuntimeRole.REGION_DECISION_VERIFIER,
            payload=certificate,
            producer=verifier,
            input_refs=(source_ref, inventory_ref, proposed_ref),
        )
        certificate_ref = store.ref(certificate_envelope)
        certificates.append(certificate)
        certificate_envelopes.append(certificate_envelope)
        gate = evaluate_split_certificate(
            certificate,
            evidence_modes=evidence_modes,
        )
        if gate.accepted:
            final = proposed.model_copy(
                update={
                    "plan_version": 2,
                    "split_certificate_ref": certificate_ref,
                    "status": RegionPlanStatus.ACCEPTED,
                    "supersedes": proposed_ref,
                }
            )
            envelope = store.put(
                owner_id=owner_id,
                role=planner_role,
                payload=final,
                producer=planner,
                input_refs=(
                    *input_refs,
                    proposed_ref,
                    certificate_ref,
                ),
                supersedes=proposed_ref,
            )
            final_ref = store.ref(envelope)
            accepted_refs.append(final_ref)
            ref_by_region[node.region_id] = final_ref
            structurally_accounted.update(structural_ids)
            unresolved_sources.update(unresolved_ids)
            final_plans.append(final)
            final_envelopes.append(envelope)
            child_ancestor_path = (*ancestor_path, node.region_id)
            for child in children:
                persist_node(
                    child,
                    parent_region_id=node.region_id,
                    ancestor_path=child_ancestor_path,
                    primary_source_ids=tuple(
                        child_primary[child.region_id]
                    ),
                    secondary_source_ids=tuple(
                        child_secondary[child.region_id]
                    ),
                )
            return

        final = _unresolved_plan(
            node=node,
            parent_region_id=parent_region_id,
            ancestor_path=ancestor_path,
            primary_source_ids=primary_source_ids,
            secondary_source_ids=secondary_source_ids,
            unresolved_source_ids=primary_source_ids,
            reason="; ".join(gate.reason_codes),
            plan_version=2,
            supersedes=proposed_ref,
        )
        envelope = store.put(
            owner_id=owner_id,
            role=planner_role,
            payload=final,
            producer=planner,
            input_refs=(
                *input_refs,
                proposed_ref,
                certificate_ref,
            ),
            supersedes=proposed_ref,
        )
        final_plans.append(final)
        final_envelopes.append(envelope)
        ref_by_region[node.region_id] = store.ref(envelope)
        unresolved_sources.update(primary_source_ids)

    persist_node(
        root,
        parent_region_id=None,
        ancestor_path=(),
        primary_source_ids=all_source_ids,
        secondary_source_ids=(),
    )
    if decision_provider is not None:
        decision_provider.finish()
    return RegionPlanningResult(
        final_plans=tuple(final_plans),
        final_plan_envelopes=tuple(final_envelopes),
        split_certificates=tuple(certificates),
        split_certificate_envelopes=tuple(certificate_envelopes),
        accepted_plan_refs=tuple(accepted_refs),
        plan_ref_by_region=MappingProxyType(ref_by_region),
        source_to_leaf_region=MappingProxyType(source_to_leaf),
        structurally_accounted_source_ids=tuple(
            sorted(structurally_accounted)
        ),
        unresolved_source_ids=tuple(sorted(unresolved_sources)),
        root_region_id=root.region_id,
        recorded_interaction_ids=tuple(recorded_interaction_ids),
        repaired_decisions=repaired_decisions,
        model_providers=tuple(sorted(model_providers)),
    )
