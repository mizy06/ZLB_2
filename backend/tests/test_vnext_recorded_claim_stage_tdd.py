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
from backend.vnext.claims import (
    ModelClaimStageError,
    RecordedClaimModelStage,
    audit_claim_omissions,
    prepare_model_claim_tasks,
)
from backend.vnext.cli import main
from backend.vnext.contracts.claims import (
    ClaimPublicationStatus,
    ClaimType,
    InstructionalRole,
)
from backend.vnext.contracts.common import RuntimeRole
from backend.vnext.contracts.control import (
    ExecutionStatus,
    ModelSlot,
    ReplayMode,
)
from backend.vnext.contracts.model_semantics import (
    ClaimProposal,
    ClaimProposalBatch,
)
from backend.vnext.model_runtime import (
    ProviderEndpoint,
    StructuredModelAdapter,
    TransportResponse,
)
from backend.vnext.orchestration.source_shadow import run_source_shadow
from backend.vnext.orchestration.control_store import SQLiteControlStore
from backend.vnext.orchestration.durable_pipeline import (
    SimulatedWorkerCrash,
    run_durable_shadow_pipeline,
)
from backend.vnext.regions import plan_explicit_regions
from backend.vnext.replay.store import RecordedReplayStore


VALID_SOURCE = (
    "# Carbonyl Chemistry\n"
    "## Foundations\n"
    "Aldehydes are terminal carbonyl compounds.\n"
    "## Applications\n"
    "Ketones are used in synthesis.\n"
)
RUN_ID = f"run_{'a' * 32}"


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


def _endpoint() -> ProviderEndpoint:
    return ProviderEndpoint(
        provider="recording-provider",
        base_url="https://recording.example/v1",
        model_revision="claim-model-20260701",
        model_family="claim-family",
    )


def _slot() -> ModelSlot:
    return ModelSlot(
        slot="claim_extractor",
        provider="recording-provider",
        model_revision="claim-model-20260701",
        model_family="claim-family",
        independence_group=None,
        independence_calibrated=False,
        context_limit=128000,
        structured_output=True,
        region="cn",
        price_input_microunits_per_million=0,
        price_output_microunits_per_million=0,
    )


def _response(batch: ClaimProposalBatch) -> TransportResponse:
    return TransportResponse(
        status_code=200,
        headers={},
        payload={
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": batch.model_dump_json(),
                    },
                }
            ]
        },
    )


def _proposal_for(card) -> ClaimProposal:
    structural = (
        card.source_kind == "outline"
        or card.declared_role in {"heading", "title"}
    )
    return ClaimProposal(
        source_id=card.source_id,
        source_quote=card.text,
        claim_type=(
            ClaimType.STRUCTURAL_FACT
            if structural
            else ClaimType.PROPERTY
        ),
        instructional_role=(
            InstructionalRole.OTHER
            if structural
            else InstructionalRole.PRINCIPLE
        ),
        predicate="organizes" if structural else "states",
    )


def _batch_for(task, *, unresolved: set[str] | None = None):
    unresolved_ids = unresolved or set()
    proposals = tuple(
        sorted(
            (
                _proposal_for(card)
                for card in task.cards
                if card.source_id not in unresolved_ids
            ),
            key=lambda item: (
                item.source_id,
                item.source_quote,
                item.claim_type.value,
                item.predicate,
            ),
        )
    )
    return ClaimProposalBatch(
        proposals=proposals,
        unresolved_source_ids=tuple(sorted(unresolved_ids)),
    )


def _source_and_planning(root: Path):
    source_path = root / "course.md"
    source_path.write_text(VALID_SOURCE, encoding="utf-8")
    store = LocalArtifactStore(root / "artifacts")
    source = run_source_shadow(
        source_path,
        owner_id="tenant-a",
        store=store,
    )
    planning = plan_explicit_regions(
        source.source_observation,
        source.source_inventory,
        owner_id="tenant-a",
        source_ref=store.ref(source.source_envelope),
        inventory_ref=store.ref(source.inventory_envelope),
        store=store,
    )
    tasks, automatic_unresolved = prepare_model_claim_tasks(
        source.source_observation,
        source.source_inventory,
        planning,
        owner_id="tenant-a",
        run_id=RUN_ID,
    )
    return store, source, planning, tasks, automatic_unresolved


def _record_stage(
    root: Path,
    tasks,
    batches,
) -> RecordedClaimModelStage:
    replay_store = RecordedReplayStore(root / "replay")
    transport = QueueTransport([_response(batch) for batch in batches])
    adapter = StructuredModelAdapter(
        [_endpoint()],
        transport=transport,
        replay_store=replay_store,
    )
    sequences = {}
    for task in tasks:
        result = adapter.invoke(task.call, ClaimProposalBatch)
        sequences[task.task_key] = result.interaction_ids
    return RecordedClaimModelStage(
        adapter=adapter,
        model_slot=_slot(),
        replay_sequences=sequences,
    )


class VNextRecordedClaimStageTests(unittest.TestCase):
    def test_proposal_contract_requires_unique_disjoint_partition(self):
        source_a = f"src:block:{'1' * 64}"
        source_b = f"src:block:{'2' * 64}"
        proposal_a = ClaimProposal(
            source_id=source_a,
            source_quote="A",
            claim_type=ClaimType.PROPERTY,
            instructional_role=InstructionalRole.PRINCIPLE,
            predicate="states",
        )
        proposal_b = proposal_a.model_copy(
            update={"source_id": source_b, "source_quote": "B"}
        )

        self.assertEqual(
            ClaimProposalBatch(
                proposals=(proposal_b, proposal_a)
            ).proposals,
            (proposal_b, proposal_a),
        )
        with self.assertRaisesRegex(ValidationError, "unique"):
            ClaimProposalBatch(proposals=(proposal_a, proposal_a))
        with self.assertRaisesRegex(
            ValidationError,
            "both proposed and unresolved",
        ):
            ClaimProposalBatch(
                proposals=(proposal_a,),
                unresolved_source_ids=(source_a,),
            )

    def test_recorded_stage_binds_quotes_evidence_and_interactions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (
                store,
                source,
                planning,
                tasks,
                automatic_unresolved,
            ) = _source_and_planning(root)
            self.assertEqual(automatic_unresolved, ())
            stage = _record_stage(
                root,
                tasks,
                tuple(_batch_for(task) for task in tasks),
            )

            prepared = stage.prepare(
                source.source_observation,
                source.source_inventory,
                planning,
                owner_id="tenant-a",
                run_id=RUN_ID,
            )
            result = stage.build_ledger(
                prepared,
                source_hash=source.source_observation.source_hash,
                document_ir_ref=store.ref(source.source_envelope),
                region_plan_refs=planning.accepted_plan_refs,
            )

            self.assertEqual(
                result.interaction_count,
                len(tasks),
            )
            self.assertEqual(
                len(result.ledger.recorded_interaction_ids),
                len(tasks),
            )
            self.assertFalse(result.ledger.unresolved_source_ids)
            self.assertTrue(result.ledger.producer.prompt_digest)
            self.assertTrue(result.ledger.claims)
            self.assertTrue(
                all(
                    claim.extractor.model_revision
                    == "claim-model-20260701"
                    for claim in result.ledger.claims
                )
            )
            self.assertTrue(
                all(
                    claim.fidelity_verifier is not None
                    and claim.fidelity_verifier.producer_id
                    != claim.extractor.producer_id
                    for claim in result.ledger.claims
                )
            )
            instruction_claims = [
                claim
                for claim in result.ledger.claims
                if claim.claim_type is ClaimType.INSTRUCTION
            ]
            self.assertTrue(
                all(
                    claim.publication_status
                    is ClaimPublicationStatus.WITHHELD
                    for claim in instruction_claims
                )
            )

    def test_model_abstention_is_unresolved_not_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store, source, planning, tasks, _ = _source_and_planning(root)
            target = next(
                card.source_id
                for task in tasks
                for card in task.cards
                if card.declared_role == "paragraph"
            )
            batches = tuple(
                _batch_for(
                    task,
                    unresolved=(
                        {target}
                        if any(
                            card.source_id == target
                            for card in task.cards
                        )
                        else set()
                    ),
                )
                for task in tasks
            )
            stage = _record_stage(root, tasks, batches)
            prepared = stage.prepare(
                source.source_observation,
                source.source_inventory,
                planning,
                owner_id="tenant-a",
                run_id=RUN_ID,
            )
            result = stage.build_ledger(
                prepared,
                source_hash=source.source_observation.source_hash,
                document_ir_ref=store.ref(source.source_envelope),
                region_plan_refs=planning.accepted_plan_refs,
            )
            ledger_envelope = store.put(
                owner_id="tenant-a",
                role=RuntimeRole.CLAIM_ATOMIZER,
                payload=result.ledger,
                producer=result.ledger.producer,
                input_refs=(
                    store.ref(source.source_envelope),
                    *planning.accepted_plan_refs,
                ),
            )

            audit = audit_claim_omissions(
                source.source_inventory,
                result.ledger,
                source_inventory_ref=store.ref(
                    source.inventory_envelope
                ),
                claim_ledger_ref=store.ref(ledger_envelope),
                structurally_accounted_source_ids=(
                    planning.structurally_accounted_source_ids
                ),
                forced_unresolved_source_ids=(
                    planning.unresolved_source_ids
                ),
            )

            self.assertIn(target, result.ledger.unresolved_source_ids)
            self.assertIn(target, audit.unresolved_source_ids)
            self.assertNotIn(target, audit.omitted_source_ids)

    def test_unverifiable_quote_and_missing_partition_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store, source, planning, tasks, _ = _source_and_planning(root)
            first_task = tasks[0]
            bad_proposals = list(_batch_for(first_task).proposals)
            bad_proposals[0] = bad_proposals[0].model_copy(
                update={"source_quote": "invented source text"}
            )
            bad_proposals.sort(
                key=lambda item: (
                    item.source_id,
                    item.source_quote,
                    item.claim_type.value,
                    item.predicate,
                )
            )
            batches = [
                ClaimProposalBatch(proposals=tuple(bad_proposals)),
                *(_batch_for(task) for task in tasks[1:]),
            ]
            stage = _record_stage(root, tasks, tuple(batches))
            prepared = stage.prepare(
                source.source_observation,
                source.source_inventory,
                planning,
                owner_id="tenant-a",
                run_id=RUN_ID,
            )
            with self.assertRaisesRegex(
                ModelClaimStageError,
                "not an exact source span",
            ):
                stage.build_ledger(
                    prepared,
                    source_hash=source.source_observation.source_hash,
                    document_ir_ref=store.ref(source.source_envelope),
                    region_plan_refs=planning.accepted_plan_refs,
                )

            incomplete = ClaimProposalBatch(
                proposals=_batch_for(first_task).proposals[:-1]
            )
            missing_stage = _record_stage(
                root,
                tasks,
                (
                    incomplete,
                    *(_batch_for(task) for task in tasks[1:]),
                ),
            )
            missing_prepared = missing_stage.prepare(
                source.source_observation,
                source.source_inventory,
                planning,
                owner_id="tenant-a",
                run_id=RUN_ID,
            )
            with self.assertRaisesRegex(
                ModelClaimStageError,
                "did not reconcile source IDs",
            ):
                missing_stage.build_ledger(
                    missing_prepared,
                    source_hash=source.source_observation.source_hash,
                    document_ir_ref=store.ref(source.source_envelope),
                    region_plan_refs=planning.accepted_plan_refs,
                )

    def test_durable_pipeline_replays_then_reuses_model_claim_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "course.md"
            source_path.write_text(VALID_SOURCE, encoding="utf-8")
            artifacts = LocalArtifactStore(root / "artifacts")
            control = SQLiteControlStore(root / "control.sqlite3")
            baseline = run_durable_shadow_pipeline(
                source_path,
                owner_id="tenant-a",
                artifact_store=artifacts,
                control_store=control,
                worker_id="worker-baseline",
                run_id=f"run_{'1' * 32}",
            )
            model_run_id = f"run_{'2' * 32}"
            tasks, automatic_unresolved = prepare_model_claim_tasks(
                baseline.shadow.source.source_observation,
                baseline.shadow.source.source_inventory,
                baseline.shadow.planning,
                owner_id="tenant-a",
                run_id=model_run_id,
            )
            self.assertEqual(automatic_unresolved, ())
            stage = _record_stage(
                root,
                tasks,
                tuple(_batch_for(task) for task in tasks),
            )
            transport = stage.adapter.transport
            self.assertIsInstance(transport, QueueTransport)
            recorded_request_count = len(transport.requests)

            model_run = run_durable_shadow_pipeline(
                source_path,
                owner_id="tenant-a",
                artifact_store=artifacts,
                control_store=control,
                worker_id="worker-model",
                run_id=model_run_id,
                claim_model_stage=stage,
            )

            self.assertEqual(
                model_run.run_manifest.execution_status,
                ExecutionStatus.SUCCEEDED,
            )
            self.assertTrue(model_run.run_manifest.declared.no_egress)
            self.assertEqual(
                model_run.run_manifest.observed.replay_mode,
                ReplayMode.RECORDED_RESPONSE_REPLAY,
            )
            self.assertEqual(
                model_run.run_manifest.observed.model_call_count,
                len(tasks),
            )
            self.assertEqual(
                model_run.run_manifest.declared.budget.max_model_calls,
                len(tasks),
            )
            self.assertEqual(
                tuple(
                    slot.slot
                    for slot in model_run.run_manifest.declared
                    .model_portfolio.slots
                ),
                ("claim_extractor",),
            )
            self.assertEqual(
                len(
                    model_run.shadow.claim_ledger
                    .recorded_interaction_ids
                ),
                len(tasks),
            )
            self.assertEqual(
                set(model_run.reused_stages),
                {"source-shadow", "explicit-region-planning"},
            )
            model_stage = next(
                item
                for item in model_run.run_manifest.observed.stages
                if item.stage_key == "recorded-model-claim-ledger"
            )
            self.assertFalse(model_stage.reused)
            self.assertEqual(len(transport.requests), recorded_request_count)

            reused = run_durable_shadow_pipeline(
                source_path,
                owner_id="tenant-a",
                artifact_store=artifacts,
                control_store=control,
                worker_id="worker-reuse",
                run_id=f"run_{'3' * 32}",
                claim_model_stage=stage,
            )
            expected_stages = {
                "source-shadow",
                "explicit-region-planning",
                "recorded-model-claim-ledger",
                "omission-and-region-audit",
                "relation-proposal",
                "independent-relation-assessment",
                "canonical-explicit-graph",
                "diagnostic-projection",
            }

            self.assertEqual(set(reused.reused_stages), expected_stages)
            self.assertEqual(
                reused.run_manifest.observed.model_call_count,
                0,
            )
            self.assertEqual(
                reused.shadow.claim_ledger_envelope.artifact_id,
                model_run.shadow.claim_ledger_envelope.artifact_id,
            )
            self.assertEqual(
                reused.shadow.projection_envelope.artifact_id,
                model_run.shadow.projection_envelope.artifact_id,
            )
            self.assertEqual(len(transport.requests), recorded_request_count)

    def test_model_stage_crash_replays_snapshot_and_quarantines_orphan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "course.md"
            source_path.write_text(VALID_SOURCE, encoding="utf-8")
            artifacts = LocalArtifactStore(root / "artifacts")
            control = SQLiteControlStore(root / "control.sqlite3")
            baseline = run_durable_shadow_pipeline(
                source_path,
                owner_id="tenant-a",
                artifact_store=artifacts,
                control_store=control,
                worker_id="worker-baseline",
                run_id=f"run_{'4' * 32}",
            )
            model_run_id = f"run_{'5' * 32}"
            tasks, _ = prepare_model_claim_tasks(
                baseline.shadow.source.source_observation,
                baseline.shadow.source.source_inventory,
                baseline.shadow.planning,
                owner_id="tenant-a",
                run_id=model_run_id,
            )
            stage = _record_stage(
                root,
                tasks,
                tuple(_batch_for(task) for task in tasks),
            )
            transport = stage.adapter.transport
            self.assertIsInstance(transport, QueueTransport)
            recorded_request_count = len(transport.requests)
            before = {
                envelope.artifact_id
                for envelope in artifacts.list_envelopes(
                    owner_id="tenant-a"
                )
            }

            with self.assertRaises(SimulatedWorkerCrash):
                run_durable_shadow_pipeline(
                    source_path,
                    owner_id="tenant-a",
                    artifact_store=artifacts,
                    control_store=control,
                    worker_id="worker-crash",
                    run_id=model_run_id,
                    claim_model_stage=stage,
                    crash_after_stage="recorded-model-claim-ledger",
                )
            after_crash = {
                envelope.artifact_id
                for envelope in artifacts.list_envelopes(
                    owner_id="tenant-a"
                )
            }
            orphan_candidates = after_crash - before
            self.assertEqual(len(orphan_candidates), 1)
            self.assertEqual(len(transport.requests), recorded_request_count)

            resumed = run_durable_shadow_pipeline(
                source_path,
                owner_id="tenant-a",
                artifact_store=artifacts,
                control_store=control,
                worker_id="worker-crash",
                run_id=model_run_id,
                claim_model_stage=stage,
            )

            self.assertEqual(
                resumed.run_manifest.execution_status,
                ExecutionStatus.SUCCEEDED,
            )
            self.assertEqual(
                resumed.run_manifest.observed.model_call_count,
                len(tasks),
            )
            self.assertEqual(len(transport.requests), recorded_request_count)
            self.assertTrue(
                orphan_candidates
                <= set(
                    control.find_orphan_artifacts(
                        owner_id="tenant-a",
                        artifact_store=artifacts,
                    )
                )
            )

    def test_recorded_claim_shadow_cli_has_no_live_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "course.md"
            source_path.write_text(VALID_SOURCE, encoding="utf-8")
            artifacts = LocalArtifactStore(root / "artifacts")
            control_path = root / "control.sqlite3"
            baseline = run_durable_shadow_pipeline(
                source_path,
                owner_id="tenant-a",
                artifact_store=artifacts,
                control_store=SQLiteControlStore(control_path),
                worker_id="worker-baseline",
                run_id=f"run_{'6' * 32}",
            )
            cli_run_id = f"run_{'7' * 32}"
            tasks, _ = prepare_model_claim_tasks(
                baseline.shadow.source.source_observation,
                baseline.shadow.source.source_inventory,
                baseline.shadow.planning,
                owner_id="tenant-a",
                run_id=cli_run_id,
            )
            stage = _record_stage(
                root,
                tasks,
                tuple(_batch_for(task) for task in tasks),
            )
            replay_map = root / "claim-replay-map.json"
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
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(
                    [
                        "recorded-claim-shadow",
                        "--input",
                        str(source_path),
                        "--owner",
                        "tenant-a",
                        "--root",
                        str(root / "artifacts"),
                        "--control-db",
                        str(control_path),
                        "--replay-root",
                        str(root / "replay"),
                        "--replay-map",
                        str(replay_map),
                        "--run-id",
                        cli_run_id,
                        "--provider",
                        "recording-provider",
                        "--model-revision",
                        "claim-model-20260701",
                        "--model-family",
                        "claim-family",
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["no_egress"])
            self.assertEqual(
                payload["replay_mode"],
                "recorded_response_replay",
            )
            self.assertEqual(payload["model_call_count"], len(tasks))
            self.assertEqual(
                len(payload["recorded_interaction_ids"]),
                len(tasks),
            )
            self.assertEqual(payload["publication_status"], "draft")


if __name__ == "__main__":
    unittest.main()
