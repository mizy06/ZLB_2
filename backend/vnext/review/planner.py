from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence

from backend.vnext.contracts.common import ArtifactRef
from backend.vnext.contracts.graph import (
    CanonicalExplicitGraph,
    CanonicalStatus,
    HierarchyDirectness,
    SemanticRelation,
)
from backend.vnext.contracts.review import (
    AffectedReplayPlan,
    ReplayStage,
    ReviewAction,
    ReviewDecision,
    ReviewTask,
)


_HIERARCHY_RELATIONS = frozenset(
    {
        SemanticRelation.TOPIC_CONTAINS,
        SemanticRelation.IS_A,
        SemanticRelation.PART_OF,
        SemanticRelation.STAGE_OF,
        SemanticRelation.EXAMPLE_OF,
    }
)
_SOURCE_ACTIONS = frozenset(
    {
        ReviewAction.RECROP_VISUAL,
        ReviewAction.APPLY_SOURCE_CORRECTION,
    }
)
_REGION_ACTIONS = frozenset(
    {
        ReviewAction.REQUEST_REGION_REPLAN,
    }
)
_CROSS_LINK_ACTIONS = frozenset(
    {
        ReviewAction.ACCEPT_CROSS_LINK,
        ReviewAction.REJECT_CROSS_LINK,
    }
)
_LABEL_ACTIONS = frozenset(
    {
        ReviewAction.RENAME_CONCEPT,
    }
)


def plan_affected_replay(
    graph: CanonicalExplicitGraph,
    *,
    graph_ref: ArtifactRef,
    task: ReviewTask,
    decision: ReviewDecision,
    source_to_concept_ids: Mapping[str, Sequence[str]] | None = None,
) -> AffectedReplayPlan:
    _validate_context(graph_ref, task, decision)
    option = next(
        (
            item
            for item in task.options
            if item.option_id == decision.selected_option_id
        ),
        None,
    )
    if option is None or (
        option.action is not decision.action
        or option.target_ids != decision.target_ids
    ):
        raise ValueError("review decision does not match task option")

    concept_ids = {item.concept_id for item in graph.concepts}
    relation_ids = {item.relation_id for item in graph.relations}
    subject_concepts = {
        item for item in task.subject_ids if item in concept_ids
    }
    target_concepts = {
        item for item in decision.target_ids if item in concept_ids
    }
    affected_sources: set[str] = set()
    if decision.action in _SOURCE_ACTIONS:
        affected_sources.update(task.subject_ids)
        mapping = source_to_concept_ids or {}
        for source_id in affected_sources:
            subject_concepts.update(mapping.get(source_id, ()))

    subtree_roots = set(subject_concepts)
    if decision.action is ReviewAction.MERGE_CONCEPTS:
        subtree_roots.update(target_concepts)
    affected_concepts = _descendants(graph, subtree_roots)
    affected_concepts.update(target_concepts)
    affected_relations = {
        relation.relation_id
        for relation in graph.relations
        if (
            relation.source_id in affected_concepts
            or relation.target_id in affected_concepts
        )
    }
    affected_relations.update(
        item
        for item in (*task.subject_ids, *decision.target_ids)
        if item in relation_ids
    )

    stages = _invalidated_stages(decision.action)
    if (
        decision.action in _REGION_ACTIONS
        and task.minimum_replan_region_id is None
    ):
        raise ValueError(
            "region replan decision requires minimum_replan_region_id"
        )
    base_refs = [task.base_artifact_ref]
    if graph_ref.artifact_id != task.base_artifact_ref.artifact_id:
        base_refs.append(graph_ref)
    plan_digest = hashlib.sha256(
        (
            "zlb-vnext-review-replay-v1\0"
            + decision.decision_id
            + "\0"
            + graph_ref.payload_digest
            + "\0"
            + decision.action.value
        ).encode("utf-8")
    ).hexdigest()
    reason_codes = {
        f"human_action:{decision.action.value}",
        "minimum_affected_scope",
        "preserve_human_decision",
    }
    if affected_concepts:
        reason_codes.add("affected_subtree")
    if affected_sources:
        reason_codes.add("source_revision_required")
    return AffectedReplayPlan(
        replay_plan_id="replay_plan_" + plan_digest[:32],
        owner_id=task.owner_id,
        run_id=task.run_id,
        review_id=task.review_id,
        decision_id=decision.decision_id,
        base_artifact_refs=tuple(base_refs),
        affected_concept_ids=tuple(sorted(affected_concepts)),
        affected_relation_ids=tuple(sorted(affected_relations)),
        affected_source_ids=tuple(sorted(affected_sources)),
        invalidated_stages=tuple(sorted(stages, key=str)),
        minimum_replan_region_id=task.minimum_replan_region_id,
        preserve_human_decision_ids=(decision.decision_id,),
        reason_codes=tuple(sorted(reason_codes)),
        created_at=decision.created_at,
    )


def _validate_context(
    graph_ref: ArtifactRef,
    task: ReviewTask,
    decision: ReviewDecision,
) -> None:
    if (
        graph_ref.owner_id != task.owner_id
        or decision.owner_id != task.owner_id
    ):
        raise ValueError("review replay context must remain owner-scoped")
    if decision.review_id != task.review_id:
        raise ValueError("review decision references another task")
    if decision.run_id != task.run_id:
        raise ValueError("review decision references another run")
    if decision.expected_review_revision != task.revision:
        raise ValueError("review decision targets a stale task revision")
    if graph_ref.artifact_type.value != "canonical_explicit_graph":
        raise ValueError("graph_ref must reference a canonical graph")


def _descendants(
    graph: CanonicalExplicitGraph,
    roots: set[str],
) -> set[str]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for relation in graph.relations:
        if (
            relation.status is CanonicalStatus.ACCEPTED
            and relation.semantic_relation in _HIERARCHY_RELATIONS
            and relation.hierarchy_directness
            is HierarchyDirectness.DIRECT
        ):
            adjacency[relation.source_id].add(relation.target_id)
    affected = set(roots)
    queue = deque(sorted(roots))
    while queue:
        current = queue.popleft()
        for child in sorted(adjacency.get(current, ())):
            if child in affected:
                continue
            affected.add(child)
            queue.append(child)
    return affected


def _invalidated_stages(action: ReviewAction) -> frozenset[ReplayStage]:
    downstream = {
        ReplayStage.CANONICAL_GRAPH,
        ReplayStage.CROSS_LINKS,
        ReplayStage.PROJECTION,
        ReplayStage.EXPORTS,
        ReplayStage.QUALITY,
    }
    if action in _SOURCE_ACTIONS:
        return frozenset(
            {
                ReplayStage.SOURCE_OBSERVATION,
                ReplayStage.SOURCE_INVENTORY,
                ReplayStage.CLAIM_LEDGER,
                ReplayStage.OMISSION_AUDIT,
                *downstream,
            }
        )
    if action in _REGION_ACTIONS:
        return frozenset(
            {
                ReplayStage.REGION_PLANNING,
                ReplayStage.CLAIM_LEDGER,
                ReplayStage.OMISSION_AUDIT,
                *downstream,
            }
        )
    if action in _CROSS_LINK_ACTIONS:
        return frozenset(
            {
                ReplayStage.CROSS_LINKS,
                ReplayStage.PROJECTION,
                ReplayStage.EXPORTS,
                ReplayStage.QUALITY,
            }
        )
    if action in _LABEL_ACTIONS:
        return frozenset(
            {
                ReplayStage.CANONICAL_GRAPH,
                ReplayStage.PROJECTION,
                ReplayStage.EXPORTS,
                ReplayStage.QUALITY,
            }
        )
    return frozenset(downstream)
