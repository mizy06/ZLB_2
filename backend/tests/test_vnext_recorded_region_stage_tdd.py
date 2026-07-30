from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from backend.vnext.artifacts.local_store import LocalArtifactStore
from backend.vnext.claims import RecordedClaimModelStage
from backend.vnext.cli import main
from backend.vnext.contracts.common import ArtifactType, RuntimeRole
from backend.vnext.contracts.control import (
    ExecutionStatus,
    ModelSlot,
    ReplayMode,
)
from backend.vnext.contracts.model_semantics import (
    RegionDecisionVerification,
    RegionPlannerProposal,
    RegionSplitSemanticAssessment,
    RegionStopSemanticAssessment,
    RegionVerificationVerdict,
)
from backend.vnext.contracts.regions import (
    RegionPlanStatus,
    RegionProposalAction,
    SplitDecision,
)
from backend.vnext.model_runtime import (
    ProviderEndpoint,
    StructuredModelAdapter,
    TransportResponse,
)
from backend.vnext.orchestration.control_store import SQLiteControlStore
from backend.vnext.orchestration.durable_pipeline import (
    SimulatedWorkerCrash,
    run_durable_shadow_pipeline,
)
from backend.vnext.orchestration.source_shadow import run_source_shadow
from backend.vnext.regions import (
    ModelRegionStageError,
    RecordedRegionModelStage,
    plan_explicit_regions,
    prepare_region_planner_tasks,
    prepare_region_verifier_task,
)
from backend.vnext.replay.store import RecordedReplayStore


VALID_SOURCE = (
    "# Carbonyl Chemistry\n"
    "## Foundations\n"
    "Aldehydes are terminal carbonyl compounds.\n"
    "## Applications\n"
    "Ketones are used in synthesis.\n"
)
RUN_ID = f"run_{'c' * 32}"


class QueueTransport:
    def __init__(self, responses: list[TransportResponse]):
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def post(
        self,
        endpoint: ProviderEndpoint,
        payload: dict[str, Any],
    ) -> TransportResponse:
        self.requests.append(json.loads(json.dumps(payload)))
        return self.responses.pop(0)


class FailTransport:
    def __init__(self):
        self.requests = 0

    def post(
        self,
        endpoint: ProviderEndpoint,
        payload: dict[str, Any],
    ) -> TransportResponse:
        self.requests += 1
        raise AssertionError("recorded region stage attempted live transport")


def _endpoint(
    provider: str,
    revision: str,
    family: str,
) -> ProviderEndpoint:
    return ProviderEndpoint(
        provider=provider,
        base_url=f"https://{provider}.example/v1",
        model_revision=revision,
        model_family=family,
    )


GLOBAL_ENDPOINT = _endpoint(
    "global-region-provider",
    "global-region-20260701",
    "region-planner-family",
)
RECURSIVE_ENDPOINT = _endpoint(
    "recursive-region-provider",
    "recursive-region-20260701",
    "region-planner-family",
)
VERIFIER_ENDPOINT = _endpoint(
    "region-verifier-provider",
    "region-verifier-20260701",
    "independent-region-verifier-family",
)
CLAIM_ENDPOINT = _endpoint(
    "claim-provider",
    "claim-20260701",
    "claim-family",
)


def _slot(
    slot: str,
    endpoint: ProviderEndpoint,
    *,
    independence_group: str,
) -> ModelSlot:
    return ModelSlot(
        slot=slot,
        provider=endpoint.provider,
        model_revision=endpoint.model_revision,
        model_family=endpoint.model_family,
        independence_group=independence_group,
        independence_calibrated=False,
        context_limit=128000,
        structured_output=True,
        region="recorded",
        price_input_microunits_per_million=0,
        price_output_microunits_per_million=0,
    )


GLOBAL_SLOT = _slot(
    "global_structure_planner",
    GLOBAL_ENDPOINT,
    independence_group="region-planner",
)
RECURSIVE_SLOT = _slot(
    "recursive_region_planner",
    RECURSIVE_ENDPOINT,
    independence_group="region-planner",
)
VERIFIER_SLOT = _slot(
    "region_decision_verifier",
    VERIFIER_ENDPOINT,
    independence_group="region-verifier",
)
CLAIM_SLOT = _slot(
    "claim_extractor",
    CLAIM_ENDPOINT,
    independence_group="claim-extractor",
)


def _response(model) -> TransportResponse:
    return TransportResponse(
        status_code=200,
        headers={},
        payload={
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": model.model_dump_json()},
                }
            ]
        },
    )


def _proposal(task) -> RegionPlannerProposal:
    if task.context.child_anchor_source_ids:
        return RegionPlannerProposal(
            anchor_source_id=task.context.anchor_source_id,
            anchor_quote=task.context.anchor_label,
            action=RegionProposalAction.SPLIT,
            child_anchor_source_ids=(
                task.context.child_anchor_source_ids
            ),
            rationale="The explicit direct headings form coherent children.",
        )
    return RegionPlannerProposal(
        anchor_source_id=task.context.anchor_source_id,
        anchor_quote=task.context.anchor_label,
        action=RegionProposalAction.STOP,
        stop_assessment=RegionStopSemanticAssessment(
            single_instructional_intent=True,
            claims_have_comparable_granularity=True,
            further_split_would_fragment_or_duplicate=True,
            no_mixed_theme_evidence=True,
        ),
        rationale="The explicit leaf has one instructional intent.",
    )


def _verification(
    task,
    proposal: RegionPlannerProposal,
    *,
    accept: bool = True,
) -> RegionDecisionVerification:
    supporting = (
        task.context.anchor_source_id,
        *task.context.child_anchor_source_ids,
    )
    if proposal.action is RegionProposalAction.SPLIT:
        split = RegionSplitSemanticAssessment(
            parent_common_concept_supported=accept,
            child_labels_self_contained=True,
            sibling_separation=True,
            within_region_cohesion=True,
            sibling_granularity_comparable=True,
            boundaries_explainable=True,
        )
        return RegionDecisionVerification(
            anchor_source_id=task.context.anchor_source_id,
            action=proposal.action,
            verdict=(
                RegionVerificationVerdict.ACCEPT
                if accept
                else RegionVerificationVerdict.REJECT
            ),
            supporting_source_ids=supporting,
            split_assessment=split,
            rationale=(
                "Independent source evidence supports the split."
                if accept
                else "The parent common concept is not supported."
            ),
        )
    stop = RegionStopSemanticAssessment(
        single_instructional_intent=accept,
        claims_have_comparable_granularity=True,
        further_split_would_fragment_or_duplicate=True,
        no_mixed_theme_evidence=True,
    )
    return RegionDecisionVerification(
        anchor_source_id=task.context.anchor_source_id,
        action=proposal.action,
        verdict=(
            RegionVerificationVerdict.ACCEPT
            if accept
            else RegionVerificationVerdict.REJECT
        ),
        supporting_source_ids=supporting,
        stop_assessment=stop,
        rationale=(
            "Independent source evidence supports stopping."
            if accept
            else "The source region has mixed instructional intent."
        ),
    )


def _source(root: Path):
    source_path = root / "course.md"
    source_path.write_text(VALID_SOURCE, encoding="utf-8")
    store = LocalArtifactStore(root / "prep-artifacts")
    result = run_source_shadow(
        source_path,
        owner_id="tenant-a",
        store=store,
    )
    return source_path, store, result


def _record_stage(
    root: Path,
    source,
    *,
    run_id: str,
    reject_root: bool = False,
    mutate_root_children: bool = False,
) -> tuple[RecordedRegionModelStage, FailTransport]:
    replay_store = RecordedReplayStore(root / "region-replay")
    tasks = prepare_region_planner_tasks(
        source.source_observation,
        source.source_inventory,
        owner_id="tenant-a",
        run_id=run_id,
    )
    sequences: dict[str, tuple[str, ...]] = {}
    for index, task in enumerate(tasks):
        if reject_root and index > 0:
            break
        proposal = _proposal(task)
        if mutate_root_children and index == 0:
            proposal = proposal.model_copy(
                update={
                    "child_anchor_source_ids": tuple(
                        reversed(proposal.child_anchor_source_ids)
                    )
                }
            )
        endpoint = (
            GLOBAL_ENDPOINT
            if task.context.planner_role
            is RuntimeRole.GLOBAL_STRUCTURE_PLANNER
            else RECURSIVE_ENDPOINT
        )
        transport = QueueTransport([_response(proposal)])
        recorded = StructuredModelAdapter(
            (endpoint,),
            transport=transport,
            replay_store=replay_store,
        ).invoke(task.call, RegionPlannerProposal)
        sequences[task.task_key] = recorded.interaction_ids
        if mutate_root_children and index == 0:
            break
        verifier_task = prepare_region_verifier_task(task, proposal)
        verification = _verification(
            task,
            proposal,
            accept=not (reject_root and index == 0),
        )
        verifier_transport = QueueTransport([_response(verification)])
        verified = StructuredModelAdapter(
            (VERIFIER_ENDPOINT,),
            transport=verifier_transport,
            replay_store=replay_store,
        ).invoke(
            verifier_task.call,
            RegionDecisionVerification,
        )
        sequences[verifier_task.task_key] = verified.interaction_ids
        if reject_root and index == 0:
            break

    fail_transport = FailTransport()
    stage = RecordedRegionModelStage(
        adapter=StructuredModelAdapter(
            (
                GLOBAL_ENDPOINT,
                RECURSIVE_ENDPOINT,
                VERIFIER_ENDPOINT,
            ),
            transport=fail_transport,
            replay_store=replay_store,
        ),
        global_planner_slot=GLOBAL_SLOT,
        recursive_planner_slot=RECURSIVE_SLOT,
        verifier_slot=VERIFIER_SLOT,
        replay_sequences=sequences,
    )
    return stage, fail_transport


class VNextRecordedRegionContractTests(unittest.TestCase):
    def test_model_contract_cannot_write_region_ids_or_parent_edges(self):
        anchor = f"src:outline:{'1' * 64}"
        child_a = f"src:outline:{'2' * 64}"
        child_b = f"src:outline:{'3' * 64}"

        proposal = RegionPlannerProposal(
            anchor_source_id=anchor,
            anchor_quote="Carbonyl Chemistry",
            action=RegionProposalAction.SPLIT,
            child_anchor_source_ids=(child_a, child_b),
            rationale="Two explicit child headings.",
        )

        self.assertEqual(
            proposal.child_anchor_source_ids,
            (child_a, child_b),
        )
        with self.assertRaisesRegex(ValidationError, "extra"):
            RegionPlannerProposal(
                **proposal.model_dump(mode="python"),
                region_id=f"reg_{'4' * 32}",
                parent_region_id=f"reg_{'5' * 32}",
            )
        with self.assertRaisesRegex(ValidationError, "child anchors"):
            RegionPlannerProposal(
                anchor_source_id=anchor,
                anchor_quote="Carbonyl Chemistry",
                action=RegionProposalAction.SPLIT,
                child_anchor_source_ids=(child_a,),
                rationale="Only one child.",
            )
        with self.assertRaisesRegex(ValidationError, "stop assessment"):
            RegionPlannerProposal(
                anchor_source_id=anchor,
                anchor_quote="Carbonyl Chemistry",
                action=RegionProposalAction.STOP,
                rationale="Missing semantic checks.",
            )


class VNextRecordedRegionStageTests(unittest.TestCase):
    def test_recorded_stage_preserves_code_owned_topology_and_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, prep_store, source = _source(root)
            baseline = plan_explicit_regions(
                source.source_observation,
                source.source_inventory,
                owner_id="tenant-a",
                source_ref=prep_store.ref(source.source_envelope),
                inventory_ref=prep_store.ref(source.inventory_envelope),
                store=prep_store,
            )
            stage, fail_transport = _record_stage(
                root,
                source,
                run_id=RUN_ID,
            )
            model_store = LocalArtifactStore(root / "model-artifacts")
            model_source = run_source_shadow(
                root / "course.md",
                owner_id="tenant-a",
                store=model_store,
            )
            provider = stage.bind(
                model_source.source_observation,
                model_source.source_inventory,
                owner_id="tenant-a",
                run_id=RUN_ID,
            )

            result = plan_explicit_regions(
                model_source.source_observation,
                model_source.source_inventory,
                owner_id="tenant-a",
                source_ref=model_store.ref(model_source.source_envelope),
                inventory_ref=model_store.ref(
                    model_source.inventory_envelope
                ),
                store=model_store,
                decision_provider=provider,
            )

            baseline_shape = {
                (
                    item.region_id,
                    item.parent_region_id,
                    item.child_region_ids,
                )
                for item in baseline.final_plans
            }
            model_shape = {
                (
                    item.region_id,
                    item.parent_region_id,
                    item.child_region_ids,
                )
                for item in result.final_plans
            }
            self.assertEqual(model_shape, baseline_shape)
            self.assertEqual(
                len(result.recorded_interaction_ids),
                6,
            )
            self.assertEqual(result.repaired_decisions, 0)
            self.assertEqual(fail_transport.requests, 0)
            self.assertTrue(
                all(
                    item.status is RegionPlanStatus.ACCEPTED
                    for item in result.final_plans
                )
            )
            root_plan = next(
                item
                for item in result.final_plans
                if item.parent_region_id is None
            )
            self.assertEqual(root_plan.theme_label, "Carbonyl Chemistry")
            self.assertEqual(
                result.split_certificates[0].verifier.model_revision,
                VERIFIER_SLOT.model_revision,
            )
            self.assertEqual(
                result.split_certificate_envelopes[0]
                .producer.model_revision,
                VERIFIER_SLOT.model_revision,
            )

    def test_recorded_planner_cannot_reorder_explicit_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, store, source = _source(root)
            stage, fail_transport = _record_stage(
                root,
                source,
                run_id=RUN_ID,
                mutate_root_children=True,
            )
            provider = stage.bind(
                source.source_observation,
                source.source_inventory,
                owner_id="tenant-a",
                run_id=RUN_ID,
            )

            with self.assertRaisesRegex(
                ModelRegionStageError,
                "direct child anchors",
            ):
                plan_explicit_regions(
                    source.source_observation,
                    source.source_inventory,
                    owner_id="tenant-a",
                    source_ref=store.ref(source.source_envelope),
                    inventory_ref=store.ref(source.inventory_envelope),
                    store=store,
                    decision_provider=provider,
                )

            self.assertEqual(fail_transport.requests, 0)
            self.assertFalse(
                any(
                    item.artifact_type is ArtifactType.REGION_PLAN
                    for item in store.list_envelopes(owner_id="tenant-a")
                )
            )

    def test_independent_verifier_veto_keeps_region_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, store, source = _source(root)
            stage, _ = _record_stage(
                root,
                source,
                run_id=RUN_ID,
                reject_root=True,
            )
            provider = stage.bind(
                source.source_observation,
                source.source_inventory,
                owner_id="tenant-a",
                run_id=RUN_ID,
            )

            result = plan_explicit_regions(
                source.source_observation,
                source.source_inventory,
                owner_id="tenant-a",
                source_ref=store.ref(source.source_envelope),
                inventory_ref=store.ref(source.inventory_envelope),
                store=store,
                decision_provider=provider,
            )

            self.assertEqual(len(result.final_plans), 1)
            self.assertEqual(
                result.final_plans[0].status,
                RegionPlanStatus.UNRESOLVED,
            )
            self.assertEqual(
                result.split_certificates[0].decision,
                SplitDecision.REJECT_SPLIT,
            )
            self.assertEqual(result.source_to_leaf_region, {})

    def test_durable_region_stage_replays_reuses_and_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path, _, source = _source(root)
            model_run_id = f"run_{'d' * 32}"
            stage, fail_transport = _record_stage(
                root,
                source,
                run_id=model_run_id,
            )
            artifacts = LocalArtifactStore(root / "durable-artifacts")
            control = SQLiteControlStore(root / "control.sqlite3")

            with self.assertRaises(SimulatedWorkerCrash):
                run_durable_shadow_pipeline(
                    source_path,
                    owner_id="tenant-a",
                    artifact_store=artifacts,
                    control_store=control,
                    worker_id="region-worker",
                    run_id=model_run_id,
                    region_model_stage=stage,
                    crash_after_stage=(
                        "recorded-model-explicit-region-planning"
                    ),
                )
            after_crash = {
                item.artifact_id
                for item in artifacts.list_envelopes(owner_id="tenant-a")
            }

            resumed = run_durable_shadow_pipeline(
                source_path,
                owner_id="tenant-a",
                artifact_store=artifacts,
                control_store=control,
                worker_id="region-worker",
                run_id=model_run_id,
                region_model_stage=stage,
            )

            self.assertEqual(
                resumed.run_manifest.execution_status,
                ExecutionStatus.SUCCEEDED,
            )
            self.assertEqual(
                resumed.run_manifest.observed.replay_mode,
                ReplayMode.RECORDED_RESPONSE_REPLAY,
            )
            self.assertEqual(
                resumed.run_manifest.observed.model_call_count,
                6,
            )
            self.assertEqual(
                tuple(
                    slot.slot
                    for slot in resumed.run_manifest.declared
                    .model_portfolio.slots
                ),
                (
                    "global_structure_planner",
                    "recursive_region_planner",
                    "region_decision_verifier",
                ),
            )
            self.assertEqual(fail_transport.requests, 0)
            self.assertTrue(
                after_crash
                & set(
                    control.find_orphan_artifacts(
                        owner_id="tenant-a",
                        artifact_store=artifacts,
                    )
                )
            )

            reused = run_durable_shadow_pipeline(
                source_path,
                owner_id="tenant-a",
                artifact_store=artifacts,
                control_store=control,
                worker_id="region-reuse",
                run_id=f"run_{'e' * 32}",
                region_model_stage=stage,
            )
            self.assertEqual(
                reused.run_manifest.observed.model_call_count,
                0,
            )
            self.assertIn(
                "recorded-model-explicit-region-planning",
                reused.reused_stages,
            )
            self.assertEqual(fail_transport.requests, 0)

    def test_region_and_claim_recorded_policies_compose(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path, _, source = _source(root)
            run_id = f"run_{'f' * 32}"
            region_stage, region_transport = _record_stage(
                root,
                source,
                run_id=run_id,
                reject_root=True,
            )
            claim_transport = FailTransport()
            claim_stage = RecordedClaimModelStage(
                adapter=StructuredModelAdapter(
                    (CLAIM_ENDPOINT,),
                    transport=claim_transport,
                    replay_store=RecordedReplayStore(
                        root / "claim-replay"
                    ),
                ),
                model_slot=CLAIM_SLOT,
                replay_sequences={},
            )

            result = run_durable_shadow_pipeline(
                source_path,
                owner_id="tenant-a",
                artifact_store=LocalArtifactStore(root / "artifacts"),
                control_store=SQLiteControlStore(
                    root / "control.sqlite3"
                ),
                worker_id="combined-worker",
                run_id=run_id,
                region_model_stage=region_stage,
                claim_model_stage=claim_stage,
            )

            self.assertEqual(
                result.run_manifest.execution_status,
                ExecutionStatus.SUCCEEDED,
            )
            self.assertEqual(
                result.run_manifest.observed.model_call_count,
                2,
            )
            self.assertEqual(
                result.run_manifest.declared.budget.max_model_calls,
                2,
            )
            self.assertEqual(
                tuple(
                    slot.slot
                    for slot in result.run_manifest.declared
                    .model_portfolio.slots
                ),
                (
                    "global_structure_planner",
                    "recursive_region_planner",
                    "region_decision_verifier",
                    "claim_extractor",
                ),
            )
            self.assertEqual(region_transport.requests, 0)
            self.assertEqual(claim_transport.requests, 0)

    def test_recorded_region_shadow_cli_has_no_live_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path, _, source = _source(root)
            run_id = f"run_{'9' * 32}"
            stage, _ = _record_stage(
                root,
                source,
                run_id=run_id,
            )
            replay_map = root / "region-replay-map.json"
            replay_map.write_text(
                json.dumps(
                    {
                        key: list(value)
                        for key, value in stage.replay_sequences.items()
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            portfolio_path = root / "region-portfolio.json"
            portfolio_path.write_text(
                stage.portfolio.model_dump_json(),
                encoding="utf-8",
            )
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(
                    [
                        "recorded-region-shadow",
                        "--input",
                        str(source_path),
                        "--owner",
                        "tenant-a",
                        "--root",
                        str(root / "cli-artifacts"),
                        "--control-db",
                        str(root / "cli-control.sqlite3"),
                        "--replay-root",
                        str(root / "region-replay"),
                        "--replay-map",
                        str(replay_map),
                        "--portfolio",
                        str(portfolio_path),
                        "--run-id",
                        run_id,
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["no_egress"])
            self.assertEqual(
                payload["replay_mode"],
                "recorded_response_replay",
            )
            self.assertEqual(payload["model_call_count"], 6)
            self.assertEqual(
                len(payload["recorded_interaction_ids"]),
                6,
            )
            self.assertEqual(payload["publication_status"], "draft")


if __name__ == "__main__":
    unittest.main()
