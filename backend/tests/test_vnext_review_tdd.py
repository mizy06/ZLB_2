from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from backend.tests.vnext_test_support import (
    accepted_concept,
    accepted_relation,
    artifact_ref,
    concept_id,
    graph,
    region_id,
    source_id,
)
from backend.vnext.contracts.common import (
    ArtifactType,
    DecisionEvent,
    RuntimeRole,
)
from backend.vnext.contracts.graph import CanonicalExplicitGraph
from backend.vnext.contracts.review import (
    ReplayStage,
    ReviewAction,
    ReviewDecision,
    ReviewKind,
    ReviewOption,
    ReviewStatus,
    ReviewTask,
)
from backend.vnext.review import (
    HumanDecisionOverride,
    ReviewConflict,
    SQLiteReviewStore,
    assert_human_decisions_preserved,
    plan_affected_replay,
    review_decision_event,
)


NOW = datetime(2026, 7, 29, 13, 0, tzinfo=UTC)
RUN_ID = f"run_{'1' * 32}"
REVIEW_ID = f"review_{'2' * 32}"


def _option(
    digit: str,
    action: ReviewAction,
    *,
    targets: tuple[str, ...] = (),
) -> ReviewOption:
    return ReviewOption(
        option_id=f"review_option_{digit * 32}",
        action=action,
        label=action.value,
        target_ids=tuple(sorted(targets)),
    )


def _task(
    *,
    action: ReviewAction = ReviewAction.CHANGE_PARENT,
    subject_ids: tuple[str, ...] | None = None,
    targets: tuple[str, ...] = (),
    base_type: ArtifactType = ArtifactType.CANONICAL_EXPLICIT_GRAPH,
    minimum_replan_region_id: str | None = None,
) -> ReviewTask:
    if subject_ids is None:
        subject_ids = (concept_id("2"),)
    options = tuple(
        sorted(
            (
                _option("a", action, targets=targets),
                _option("b", ReviewAction.NO_SUITABLE_PARENT),
            ),
            key=lambda item: item.option_id,
        )
    )
    return ReviewTask(
        review_id=REVIEW_ID,
        owner_id="owner-a",
        run_id=RUN_ID,
        revision=1,
        review_kind=(
            ReviewKind.VISUAL
            if action is ReviewAction.RECROP_VISUAL
            else ReviewKind.REGION_STRUCTURE
            if action is ReviewAction.REQUEST_REGION_REPLAN
            else ReviewKind.PARENT_COMPETITION
        ),
        question="Which reviewed action is supported by the evidence?",
        subject_ids=tuple(sorted(subject_ids)),
        options=options,
        base_artifact_ref=artifact_ref(base_type, "9"),
        minimum_replan_region_id=minimum_replan_region_id,
        created_at=NOW,
        updated_at=NOW,
    )


def _decision(
    task: ReviewTask,
    *,
    action: ReviewAction,
    targets: tuple[str, ...] = (),
    digit: str = "3",
) -> ReviewDecision:
    selected = next(
        option
        for option in task.options
        if option.action is action and option.target_ids == tuple(
            sorted(targets)
        )
    )
    return ReviewDecision(
        decision_id=f"review_decision_{digit * 32}",
        review_id=task.review_id,
        owner_id=task.owner_id,
        run_id=task.run_id,
        expected_review_revision=task.revision,
        selected_option_id=selected.option_id,
        action=action,
        target_ids=tuple(sorted(targets)),
        actor="human:teacher-1",
        rationale="The local evidence supports this reviewed choice.",
        created_at=NOW,
    )


def _graph() -> CanonicalExplicitGraph:
    return graph(
        (
            accepted_concept("1", "Root"),
            accepted_concept("2", "Child"),
            accepted_concept("3", "Grandchild"),
            accepted_concept("4", "Alternative parent"),
        ),
        (
            accepted_relation("a", "1", "2"),
            accepted_relation("b", "2", "3"),
            accepted_relation("c", "1", "4"),
        ),
    )


class VNextReviewStoreTests(unittest.TestCase):
    def test_resolution_is_append_only_and_stale_decision_is_fenced(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteReviewStore(Path(tmp) / "review.sqlite3")
            task = _task(targets=(concept_id("4"),))
            decision = _decision(
                task,
                action=ReviewAction.CHANGE_PARENT,
                targets=(concept_id("4"),),
            )
            store.create_task(task)

            resolved = store.resolve(decision)

            self.assertEqual(resolved.revision, 2)
            self.assertEqual(resolved.status, ReviewStatus.RESOLVED)
            self.assertEqual(
                resolved.resolution_decision_id,
                decision.decision_id,
            )
            self.assertEqual(
                tuple(item.revision for item in store.list_revisions(
                    task.review_id,
                    owner_id=task.owner_id,
                )),
                (1, 2),
            )
            self.assertEqual(
                store.list_decisions(
                    task.review_id,
                    owner_id=task.owner_id,
                ),
                (decision,),
            )
            with self.assertRaises(ReviewConflict):
                store.resolve(
                    _decision(
                        task,
                        action=ReviewAction.CHANGE_PARENT,
                        targets=(concept_id("4"),),
                        digit="4",
                    )
                )
            with self.assertRaises(KeyError):
                store.load_latest(
                    task.review_id,
                    owner_id="owner-b",
                )


class VNextAffectedReplayTests(unittest.TestCase):
    def test_change_parent_invalidates_only_moved_subtree_and_consumers(self):
        task = _task(targets=(concept_id("4"),))
        decision = _decision(
            task,
            action=ReviewAction.CHANGE_PARENT,
            targets=(concept_id("4"),),
        )

        plan = plan_affected_replay(
            _graph(),
            graph_ref=artifact_ref(
                ArtifactType.CANONICAL_EXPLICIT_GRAPH,
                "9",
            ),
            task=task,
            decision=decision,
        )

        self.assertEqual(
            set(plan.affected_concept_ids),
            {
                concept_id("2"),
                concept_id("3"),
                concept_id("4"),
            },
        )
        self.assertNotIn(concept_id("1"), plan.affected_concept_ids)
        self.assertEqual(
            set(plan.invalidated_stages),
            {
                ReplayStage.CANONICAL_GRAPH,
                ReplayStage.CROSS_LINKS,
                ReplayStage.PROJECTION,
                ReplayStage.EXPORTS,
                ReplayStage.QUALITY,
            },
        )
        self.assertNotIn(
            ReplayStage.REGION_PLANNING,
            plan.invalidated_stages,
        )
        self.assertNotIn(
            ReplayStage.SOURCE_OBSERVATION,
            plan.invalidated_stages,
        )

    def test_recrop_replays_source_slice_and_mapped_concept_subtree(self):
        visual_source = source_id("object", "d")
        task = _task(
            action=ReviewAction.RECROP_VISUAL,
            subject_ids=(visual_source,),
            base_type=ArtifactType.SOURCE_OBSERVATION_IR,
        )
        decision = _decision(
            task,
            action=ReviewAction.RECROP_VISUAL,
        )

        plan = plan_affected_replay(
            _graph(),
            graph_ref=artifact_ref(
                ArtifactType.CANONICAL_EXPLICIT_GRAPH,
                "8",
            ),
            task=task,
            decision=decision,
            source_to_concept_ids={
                visual_source: (concept_id("2"),),
            },
        )

        self.assertEqual(plan.affected_source_ids, (visual_source,))
        self.assertEqual(
            set(plan.affected_concept_ids),
            {concept_id("2"), concept_id("3")},
        )
        self.assertIn(
            ReplayStage.SOURCE_OBSERVATION,
            plan.invalidated_stages,
        )
        self.assertIn(
            ReplayStage.CLAIM_LEDGER,
            plan.invalidated_stages,
        )
        self.assertNotIn(
            ReplayStage.REGION_PLANNING,
            plan.invalidated_stages,
        )

    def test_region_replan_requires_minimum_ancestor(self):
        task = _task(
            action=ReviewAction.REQUEST_REGION_REPLAN,
            targets=(),
            minimum_replan_region_id=None,
        )
        decision = _decision(
            task,
            action=ReviewAction.REQUEST_REGION_REPLAN,
        )

        with self.assertRaisesRegex(
            ValueError,
            "minimum_replan_region_id",
        ):
            plan_affected_replay(
                _graph(),
                graph_ref=artifact_ref(
                    ArtifactType.CANONICAL_EXPLICIT_GRAPH,
                    "9",
                ),
                task=task,
                decision=decision,
            )

        valid_task = _task(
            action=ReviewAction.REQUEST_REGION_REPLAN,
            minimum_replan_region_id=region_id("a"),
        )
        valid_decision = _decision(
            valid_task,
            action=ReviewAction.REQUEST_REGION_REPLAN,
        )
        plan = plan_affected_replay(
            _graph(),
            graph_ref=artifact_ref(
                ArtifactType.CANONICAL_EXPLICIT_GRAPH,
                "9",
            ),
            task=valid_task,
            decision=valid_decision,
        )
        self.assertEqual(
            plan.minimum_replan_region_id,
            region_id("a"),
        )
        self.assertIn(
            ReplayStage.REGION_PLANNING,
            plan.invalidated_stages,
        )


class VNextHumanDecisionGuardTests(unittest.TestCase):
    def test_machine_recompute_cannot_drop_or_supersede_human_decision(self):
        task = _task(targets=(concept_id("4"),))
        decision = _decision(
            task,
            action=ReviewAction.CHANGE_PARENT,
            targets=(concept_id("4"),),
        )
        human_event = review_decision_event(decision)
        base_payload = _graph().model_dump(mode="json")
        previous = CanonicalExplicitGraph.model_validate(
            {
                **base_payload,
                "decision_log": [human_event.model_dump(mode="json")],
            }
        )

        with self.assertRaises(HumanDecisionOverride):
            assert_human_decisions_preserved(previous, _graph())

        machine_event = DecisionEvent(
            decision_id=f"decision_{'e' * 32}",
            actor=RuntimeRole.CANONICALIZER,
            decision="replace_human_parent",
            reason_codes=("recompute",),
            created_at=NOW,
            supersedes=human_event.decision_id,
        )
        machine_candidate = CanonicalExplicitGraph.model_validate(
            {
                **base_payload,
                "decision_log": [
                    human_event.model_dump(mode="json"),
                    machine_event.model_dump(mode="json"),
                ],
            }
        )
        with self.assertRaisesRegex(
            HumanDecisionOverride,
            "machine decisions",
        ):
            assert_human_decisions_preserved(
                previous,
                machine_candidate,
            )

        next_human = DecisionEvent(
            decision_id=f"decision_{'f' * 32}",
            actor="human:teacher-2",
            decision="change_parent",
            reason_codes=("new_evidence",),
            created_at=NOW,
            supersedes=human_event.decision_id,
        )
        human_candidate = CanonicalExplicitGraph.model_validate(
            {
                **base_payload,
                "decision_log": [
                    human_event.model_dump(mode="json"),
                    next_human.model_dump(mode="json"),
                ],
            }
        )

        assert_human_decisions_preserved(previous, human_candidate)


if __name__ == "__main__":
    unittest.main()
