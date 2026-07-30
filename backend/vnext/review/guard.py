from __future__ import annotations

import hashlib

from backend.vnext.contracts.common import DecisionEvent, RuntimeRole
from backend.vnext.contracts.graph import CanonicalExplicitGraph
from backend.vnext.contracts.review import ReviewDecision


class HumanDecisionOverride(ValueError):
    pass


def review_decision_event(decision: ReviewDecision) -> DecisionEvent:
    digest = hashlib.sha256(
        (
            "zlb-vnext-review-decision-event-v1\0"
            + decision.decision_id
        ).encode("utf-8")
    ).hexdigest()
    supersedes = None
    if decision.supersedes is not None:
        supersedes_digest = hashlib.sha256(
            (
                "zlb-vnext-review-decision-event-v1\0"
                + decision.supersedes
            ).encode("utf-8")
        ).hexdigest()
        supersedes = "decision_" + supersedes_digest[:32]
    return DecisionEvent(
        decision_id="decision_" + digest[:32],
        actor=decision.actor,
        decision=decision.action.value,
        reason_codes=(
            "human_review",
            f"review_id:{decision.review_id}",
        ),
        evidence_refs=decision.evidence_refs,
        created_at=decision.created_at,
        supersedes=supersedes,
    )


def assert_human_decisions_preserved(
    previous: CanonicalExplicitGraph,
    candidate: CanonicalExplicitGraph,
) -> None:
    previous_events = _events(previous)
    candidate_events = _events(candidate)
    previous_human = {
        event_id: event
        for event_id, event in previous_events.items()
        if _is_human(event)
    }
    missing = sorted(set(previous_human) - set(candidate_events))
    if missing:
        raise HumanDecisionOverride(
            "candidate graph dropped human decisions: "
            + ", ".join(missing)
        )
    machine_supersedes = sorted(
        event.decision_id
        for event in candidate_events.values()
        if (
            event.supersedes in previous_human
            and not _is_human(event)
        )
    )
    if machine_supersedes:
        raise HumanDecisionOverride(
            "machine decisions cannot supersede human decisions: "
            + ", ".join(machine_supersedes)
        )


def _events(
    graph: CanonicalExplicitGraph,
) -> dict[str, DecisionEvent]:
    events = [
        *graph.decision_log,
        *(
            event
            for concept in graph.concepts
            for event in concept.decision_history
        ),
        *(
            event
            for relation in graph.relations
            for event in relation.decision_history
        ),
    ]
    by_id = {event.decision_id: event for event in events}
    if len(by_id) != len(events):
        raise HumanDecisionOverride(
            "decision IDs must remain globally unique in a graph version"
        )
    return by_id


def _is_human(event: DecisionEvent) -> bool:
    return (
        not isinstance(event.actor, RuntimeRole)
        and str(event.actor).startswith("human:")
    )
