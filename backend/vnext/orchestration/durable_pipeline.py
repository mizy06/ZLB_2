from __future__ import annotations

import hashlib
import importlib.metadata
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, TypeVar

from backend.vnext.artifacts.canonical import payload_digest
from backend.vnext.artifacts.local_store import (
    LocalArtifactStore,
    StoredArtifact,
)
from backend.vnext.canonical_graph import (
    build_canonical_explicit_graph,
    build_relation_assessment_ledger,
    build_relation_proposal_ledger,
)
from backend.vnext.claims import (
    ModelClaimLedgerResult,
    PreparedRecordedClaimStage,
    RecordedClaimModelStage,
    atomize_source_claims,
    audit_claim_omissions,
)
from backend.vnext.contracts.artifacts import ArtifactEnvelope
from backend.vnext.contracts.claims import ClaimLedger, OmissionAudit
from backend.vnext.contracts.common import (
    ArtifactProducerRef,
    ArtifactRef,
    RuntimeRole,
    StringValue,
)
from backend.vnext.contracts.control import (
    DeclaredRunManifest,
    EvidenceMode,
    ExecutionStatus,
    ModelPortfolioManifest,
    ObservedRunManifest,
    ObservedStage,
    PublicationStatus,
    QualityAttestation,
    QualityGateDecision,
    QualityMetric,
    QualityStatus,
    RunBudget,
    RunManifest,
    RunProfile,
    ReplayMode,
    StageCommit,
    StageCommitStatus,
    evaluate_quality_gate,
)
from backend.vnext.contracts.exporter import contract_schema
from backend.vnext.contracts.graph import (
    CanonicalExplicitGraph,
    CanonicalStatus,
    RelationAssessmentLedger,
    RelationProposalLedger,
)
from backend.vnext.contracts.inventory import SourceInventory
from backend.vnext.contracts.projection import (
    DiagnosticProjection,
    ProjectionQualityStatus,
)
from backend.vnext.contracts.registry import CONTRACTS
from backend.vnext.contracts.regions import ReplanRequest
from backend.vnext.contracts.source import SourceObservationIR
from backend.vnext.projection import build_diagnostic_projection
from backend.vnext.regions import (
    RecordedRegionModelStage,
    RegionPlanningResult,
    audit_regions_bottom_up,
    load_region_planning_result,
    plan_explicit_regions,
)

from .control_store import (
    SQLiteControlStore,
    next_manifest_revision,
    stage_idempotency_key,
)
from .shadow_pipeline import ShadowPipelineResult
from .source_shadow import SourceShadowResult, run_source_shadow


T = TypeVar("T")


class SimulatedWorkerCrash(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DurablePipelineResult:
    run_manifest: RunManifest
    shadow: ShadowPipelineResult
    reused_stages: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _AuditStageResult:
    audit: OmissionAudit
    audit_envelope: ArtifactEnvelope
    replan_requests: tuple[ReplanRequest, ...]
    replan_envelopes: tuple[ArtifactEnvelope, ...]


@dataclass(frozen=True, slots=True)
class _ClaimStageResult:
    ledger: ClaimLedger
    ledger_envelope: ArtifactEnvelope
    interaction_count: int = 0
    repaired_batches: int = 0
    providers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _ModelRunPolicy:
    prompt_policy_digest: str
    tool_policy_digest: str
    portfolio: ModelPortfolioManifest
    replay_mode: ReplayMode
    max_model_calls: int


def _raw_source_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def _producer(
    producer_id: str,
    role: RuntimeRole,
) -> ArtifactProducerRef:
    return ArtifactProducerRef(
        producer_id=producer_id,
        producer_version="1.0.0",
        role=role,
    )


def _policy_digest(
    stage_key: str,
    *,
    code_revision: str,
) -> str:
    return payload_digest(
        {
            "code_revision": code_revision,
            "mode": "explicit_only_source_only",
            "stage": stage_key,
            "version": "1.0.0",
        }
    )


def _model_run_policy(
    region_model_stage: RecordedRegionModelStage | None,
    claim_model_stage: RecordedClaimModelStage | None,
    *,
    owner_id: str,
    code_revision: str,
) -> _ModelRunPolicy:
    if region_model_stage is None and claim_model_stage is None:
        return _ModelRunPolicy(
            prompt_policy_digest=_policy_digest(
                "no-live-prompts",
                code_revision=code_revision,
            ),
            tool_policy_digest=_policy_digest(
                "clean-room-tools",
                code_revision=code_revision,
            ),
            portfolio=ModelPortfolioManifest(),
            replay_mode=ReplayMode.LIVE,
            max_model_calls=0,
        )
    if region_model_stage is None:
        assert claim_model_stage is not None
        return _ModelRunPolicy(
            prompt_policy_digest=claim_model_stage.prompt_policy_digest,
            tool_policy_digest=(
                claim_model_stage.execution_policy_digest(
                    owner_id=owner_id
                )
            ),
            portfolio=claim_model_stage.portfolio,
            replay_mode=ReplayMode.RECORDED_RESPONSE_REPLAY,
            max_model_calls=claim_model_stage.recorded_interaction_count,
        )
    if claim_model_stage is None:
        return _ModelRunPolicy(
            prompt_policy_digest=region_model_stage.prompt_policy_digest,
            tool_policy_digest=(
                region_model_stage.execution_policy_digest(
                    owner_id=owner_id
                )
            ),
            portfolio=region_model_stage.portfolio,
            replay_mode=ReplayMode.RECORDED_RESPONSE_REPLAY,
            max_model_calls=region_model_stage.recorded_interaction_count,
        )
    return _ModelRunPolicy(
        prompt_policy_digest=payload_digest(
            {
                "claim": claim_model_stage.prompt_policy_digest,
                "region": region_model_stage.prompt_policy_digest,
            }
        ),
        tool_policy_digest=payload_digest(
            {
                "claim": claim_model_stage.execution_policy_digest(
                    owner_id=owner_id
                ),
                "region": region_model_stage.execution_policy_digest(
                    owner_id=owner_id
                ),
            }
        ),
        portfolio=ModelPortfolioManifest(
            slots=(
                *region_model_stage.portfolio.slots,
                *claim_model_stage.portfolio.slots,
            )
        ),
        replay_mode=ReplayMode.RECORDED_RESPONSE_REPLAY,
        max_model_calls=(
            region_model_stage.recorded_interaction_count
            + claim_model_stage.recorded_interaction_count
        ),
    )


def _initial_manifest(
    *,
    owner_id: str,
    source_hash: str,
    run_id: str,
    now: datetime,
    region_model_stage: RecordedRegionModelStage | None,
    claim_model_stage: RecordedClaimModelStage | None,
) -> RunManifest:
    code_revision = os.getenv("GIT_SHA", "working-tree")
    model_policy = _model_run_policy(
        region_model_stage,
        claim_model_stage,
        owner_id=owner_id,
        code_revision=code_revision,
    )
    dependencies = {
        name: _distribution_version(name)
        for name in (
            "langgraph",
            "networkx",
            "ortools",
            "pydantic",
            "pypdf",
            "python-docx",
            "python-pptx",
            "rfc8785",
        )
    }
    schema_digests = tuple(
        StringValue(
            key=registration.name,
            value=payload_digest(contract_schema(registration)),
        )
        for registration in CONTRACTS
    )
    return RunManifest(
        manifest_id="run_manifest_" + secrets.token_hex(16),
        run_id=run_id,
        revision=1,
        owner_id=owner_id,
        declared=DeclaredRunManifest(
            source_hash=source_hash,
            profile=RunProfile.STANDARD,
            evidence_mode=EvidenceMode.SOURCE_ONLY,
            no_egress=True,
            budget=RunBudget(
                max_wall_seconds=18 * 60,
                max_model_calls=model_policy.max_model_calls,
                max_search_queries=0,
                max_search_fetches=0,
                max_cost_microunits=0,
                vlm_concurrency=0,
                text_concurrency=6,
                search_concurrency=0,
            ),
            code_revision=code_revision,
            image_digest=None,
            dependency_digest=payload_digest(dependencies),
            parser_policy_digest=_policy_digest(
                "source-shadow",
                code_revision=code_revision,
            ),
            renderer_policy_digest=_policy_digest(
                "logical-render-references",
                code_revision=code_revision,
            ),
            prompt_policy_digest=model_policy.prompt_policy_digest,
            tool_policy_digest=model_policy.tool_policy_digest,
            search_policy_digest=_policy_digest(
                "no-egress",
                code_revision=code_revision,
            ),
            schema_digests=schema_digests,
            model_portfolio=model_policy.portfolio,
            random_seed=0,
        ),
        observed=ObservedRunManifest(
            replay_mode=model_policy.replay_mode
        ),
        created_at=now,
        updated_at=now,
    )


def _quality_status(
    projection_status: ProjectionQualityStatus,
) -> QualityStatus:
    return QualityStatus(projection_status.value)


class DurableShadowSupervisor:
    def __init__(
        self,
        *,
        artifact_store: LocalArtifactStore,
        control_store: SQLiteControlStore,
        worker_id: str,
        lease_ttl_seconds: int = 300,
        crash_after_stage: str | None = None,
        region_model_stage: RecordedRegionModelStage | None = None,
        claim_model_stage: RecordedClaimModelStage | None = None,
    ):
        self.artifact_store = artifact_store
        self.control_store = control_store
        self.worker_id = worker_id
        self.lease_ttl_seconds = lease_ttl_seconds
        self.crash_after_stage = crash_after_stage
        self.region_model_stage = region_model_stage
        self.claim_model_stage = claim_model_stage
        self._manifest: RunManifest | None = None
        self._reused_stages: list[str] = []

    def _record_observed_stage(
        self,
        *,
        stage_key: str,
        artifact_refs: tuple[ArtifactRef, ...],
        reused: bool,
        metrics: tuple[StringValue, ...] = (),
    ) -> None:
        assert self._manifest is not None
        stages = [
            stage
            for stage in self._manifest.observed.stages
            if stage.stage_key != stage_key
        ]
        stages.append(
            ObservedStage(
                stage_key=stage_key,
                artifact_refs=artifact_refs,
                metrics=metrics,
                reused=reused,
            )
        )
        observed = self._manifest.observed.model_copy(
            update={"stages": tuple(stages)}
        )
        updated = next_manifest_revision(
            self._manifest,
            observed=observed,
        )
        self.control_store.compare_and_swap_manifest(
            updated,
            expected_revision=self._manifest.revision,
        )
        self._manifest = updated

    def _record_model_claim_observation(
        self,
        result: _ClaimStageResult,
    ) -> None:
        assert self._manifest is not None
        observed = self._manifest.observed
        model_call_count = (
            observed.model_call_count + result.interaction_count
        )
        if model_call_count > (
            self._manifest.declared.budget.max_model_calls
        ):
            raise ValueError(
                "recorded model interactions exceeded declared budget"
            )
        degraded = list(observed.degraded_components)
        if (
            result.repaired_batches
            and "claim_model_schema_repair" not in degraded
        ):
            degraded.append("claim_model_schema_repair")
        updated_observed = observed.model_copy(
            update={
                "model_call_count": model_call_count,
                "degraded_components": tuple(degraded),
            }
        )
        updated = next_manifest_revision(
            self._manifest,
            observed=updated_observed,
        )
        self.control_store.compare_and_swap_manifest(
            updated,
            expected_revision=self._manifest.revision,
        )
        self._manifest = updated

    def _record_model_region_observation(
        self,
        result: RegionPlanningResult,
    ) -> None:
        assert self._manifest is not None
        observed = self._manifest.observed
        model_call_count = (
            observed.model_call_count
            + len(result.recorded_interaction_ids)
        )
        if model_call_count > (
            self._manifest.declared.budget.max_model_calls
        ):
            raise ValueError(
                "recorded model interactions exceeded declared budget"
            )
        degraded = list(observed.degraded_components)
        if (
            result.repaired_decisions
            and "region_model_schema_repair" not in degraded
        ):
            degraded.append("region_model_schema_repair")
        updated_observed = observed.model_copy(
            update={
                "model_call_count": model_call_count,
                "degraded_components": tuple(degraded),
            }
        )
        updated = next_manifest_revision(
            self._manifest,
            observed=updated_observed,
        )
        self.control_store.compare_and_swap_manifest(
            updated,
            expected_revision=self._manifest.revision,
        )
        self._manifest = updated

    def _run_stage(
        self,
        *,
        stage_key: str,
        ordered_input_digests: tuple[str, ...],
        fresh: Callable[[], T],
        reuse: Callable[[ArtifactRef], T],
        output_ref: Callable[[T], ArtifactRef],
        artifact_refs: Callable[[T], tuple[ArtifactRef, ...]],
        metrics: Callable[[T], tuple[StringValue, ...]] = lambda _: (),
        stage_policy_digest: str | None = None,
    ) -> T:
        assert self._manifest is not None
        policy = stage_policy_digest or _policy_digest(
            stage_key,
            code_revision=(
                self._manifest.declared.code_revision
            ),
        )
        idempotency_key = stage_idempotency_key(
            owner_id=self._manifest.owner_id,
            stage_contract_major=1,
            ordered_input_digests=ordered_input_digests,
            policy_digests=(policy,),
        )
        existing = self.control_store.find_committed_stage(
            owner_id=self._manifest.owner_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            assert existing.output_ref is not None
            value = reuse(existing.output_ref)
            current_commits = self.control_store.list_run_commits(
                run_id=self._manifest.run_id,
                owner_id=self._manifest.owner_id,
            )
            if not any(
                commit.stage_key == stage_key
                and commit.idempotency_key == idempotency_key
                for commit in current_commits
            ):
                attempt = 1 + max(
                    (
                        commit.attempt
                        for commit in current_commits
                        if commit.stage_key == stage_key
                    ),
                    default=0,
                )
                self.control_store.record_stage_reuse(
                    run_id=self._manifest.run_id,
                    stage_key=stage_key,
                    attempt=attempt,
                    committed=existing,
                )
            self._reused_stages.append(stage_key)
            self._record_observed_stage(
                stage_key=stage_key,
                artifact_refs=artifact_refs(value),
                reused=True,
                metrics=metrics(value),
            )
            return value

        lease = self.control_store.acquire_stage_lease(
            run_id=self._manifest.run_id,
            stage_key=stage_key,
            worker_id=self.worker_id,
            ttl_seconds=self.lease_ttl_seconds,
        )
        started_at = datetime.now(UTC)
        value = fresh()
        selected_output = output_ref(value)
        if self.crash_after_stage == stage_key:
            raise SimulatedWorkerCrash(
                f"simulated crash after {stage_key} artifact write"
            )
        current_commits = self.control_store.list_run_commits(
            run_id=self._manifest.run_id,
            owner_id=self._manifest.owner_id,
        )
        attempt = 1 + max(
            (
                commit.attempt
                for commit in current_commits
                if commit.stage_key == stage_key
            ),
            default=0,
        )
        commit = StageCommit(
            run_id=self._manifest.run_id,
            owner_id=self._manifest.owner_id,
            stage_key=stage_key,
            idempotency_key=idempotency_key,
            input_digest=payload_digest(ordered_input_digests),
            policy_digest=policy,
            output_ref=selected_output,
            attempt=attempt,
            lease_epoch=lease.lease_epoch,
            status=StageCommitStatus.COMMITTED,
            metrics=metrics(value),
            created_at=started_at,
            updated_at=datetime.now(UTC),
        )
        self.control_store.commit_stage(
            commit,
            worker_id=self.worker_id,
        )
        self._record_observed_stage(
            stage_key=stage_key,
            artifact_refs=artifact_refs(value),
            reused=False,
            metrics=metrics(value),
        )
        return value

    def run(
        self,
        path: Path,
        *,
        owner_id: str,
        run_id: str | None = None,
    ) -> DurablePipelineResult:
        source_path = path.resolve()
        source_hash = _raw_source_hash(source_path)
        resolved_run_id = run_id or ("run_" + secrets.token_hex(16))
        manifest = self.control_store.load_run(
            resolved_run_id,
            owner_id=owner_id,
        )
        if manifest is None:
            manifest = _initial_manifest(
                owner_id=owner_id,
                source_hash=source_hash,
                run_id=resolved_run_id,
                now=datetime.now(UTC),
                region_model_stage=self.region_model_stage,
                claim_model_stage=self.claim_model_stage,
            )
            self.control_store.create_run(manifest)
        elif manifest.declared.source_hash != source_hash:
            raise ValueError("run source hash does not match requested source")
        expected_model_policy = _model_run_policy(
            self.region_model_stage,
            self.claim_model_stage,
            owner_id=owner_id,
            code_revision=manifest.declared.code_revision,
        )
        if (
            manifest.declared.prompt_policy_digest
            != expected_model_policy.prompt_policy_digest
            or manifest.declared.tool_policy_digest
            != expected_model_policy.tool_policy_digest
            or manifest.declared.model_portfolio
            != expected_model_policy.portfolio
            or manifest.observed.replay_mode
            is not expected_model_policy.replay_mode
            or manifest.declared.budget.max_model_calls
            != expected_model_policy.max_model_calls
        ):
            raise ValueError(
                "run model policy does not match requested execution"
            )
        if manifest.execution_status is not ExecutionStatus.RUNNING:
            manifest = next_manifest_revision(
                manifest,
                execution_status=ExecutionStatus.RUNNING,
            )
            self.control_store.compare_and_swap_manifest(
                manifest,
                expected_revision=manifest.revision - 1,
            )
        self._manifest = manifest

        try:
            source = self._run_stage(
                stage_key="source-shadow",
                ordered_input_digests=(source_hash,),
                fresh=lambda: run_source_shadow(
                    source_path,
                    owner_id=owner_id,
                    store=self.artifact_store,
                ),
                reuse=self._load_source_shadow,
                output_ref=lambda value: self.artifact_store.ref(
                    value.inventory_envelope
                ),
                artifact_refs=lambda value: (
                    self.artifact_store.ref(value.source_envelope),
                    self.artifact_store.ref(value.inventory_envelope),
                ),
                metrics=lambda value: (
                    StringValue(
                        key="pages",
                        value=str(len(value.source_observation.pages)),
                    ),
                ),
            )
            source_ref = self.artifact_store.ref(source.source_envelope)
            inventory_ref = self.artifact_store.ref(
                source.inventory_envelope
            )
            planning_stage_key = (
                "recorded-model-explicit-region-planning"
                if self.region_model_stage is not None
                else "explicit-region-planning"
            )
            region_stage_policy = (
                self.region_model_stage.execution_policy_digest(
                    owner_id=owner_id
                )
                if self.region_model_stage is not None
                else None
            )
            planning = self._run_stage(
                stage_key=planning_stage_key,
                ordered_input_digests=(
                    source_ref.payload_digest,
                    inventory_ref.payload_digest,
                ),
                fresh=lambda: plan_explicit_regions(
                    source.source_observation,
                    source.source_inventory,
                    owner_id=owner_id,
                    source_ref=source_ref,
                    inventory_ref=inventory_ref,
                    store=self.artifact_store,
                    decision_provider=(
                        self.region_model_stage.bind(
                            source.source_observation,
                            source.source_inventory,
                            owner_id=owner_id,
                            run_id=resolved_run_id,
                        )
                        if self.region_model_stage is not None
                        else None
                    ),
                ),
                reuse=lambda ref: load_region_planning_result(
                    owner_id=owner_id,
                    root_plan_ref=ref,
                    store=self.artifact_store,
                ),
                output_ref=lambda value: value.plan_ref_by_region[
                    value.root_region_id
                ],
                artifact_refs=lambda value: (
                    *(
                        self.artifact_store.ref(envelope)
                        for envelope in value.final_plan_envelopes
                    ),
                    *(
                        self.artifact_store.ref(envelope)
                        for envelope in value.split_certificate_envelopes
                    ),
                ),
                metrics=lambda value: (
                    StringValue(
                        key="accepted_plans",
                        value=str(len(value.accepted_plan_refs)),
                    ),
                    StringValue(
                        key="unresolved_sources",
                        value=str(len(value.unresolved_source_ids)),
                    ),
                    StringValue(
                        key="recorded_interactions",
                        value=str(
                            len(value.recorded_interaction_ids)
                        ),
                    ),
                    StringValue(
                        key="interaction_sequence_digest",
                        value=payload_digest(
                            value.recorded_interaction_ids
                        ),
                    ),
                    StringValue(
                        key="repaired_decisions",
                        value=str(value.repaired_decisions),
                    ),
                ),
                stage_policy_digest=region_stage_policy,
            )
            if (
                self.region_model_stage is not None
                and planning_stage_key not in self._reused_stages
            ):
                self._record_model_region_observation(planning)
            claim_inputs = (
                source_ref.payload_digest,
                *(
                    ref.payload_digest
                    for ref in planning.accepted_plan_refs
                ),
            )
            if self.claim_model_stage is None:
                claim_stage_key = "claim-ledger"
                claim_stage = self._run_stage(
                    stage_key=claim_stage_key,
                    ordered_input_digests=claim_inputs,
                    fresh=lambda: self._build_ledger(
                        source,
                        planning,
                        source_ref,
                        owner_id,
                    ),
                    reuse=self._load_ledger,
                    output_ref=lambda value: self.artifact_store.ref(
                        value.ledger_envelope
                    ),
                    artifact_refs=lambda value: (
                        self.artifact_store.ref(
                            value.ledger_envelope
                        ),
                    ),
                    metrics=lambda value: (
                        StringValue(
                            key="claims",
                            value=str(len(value.ledger.claims)),
                        ),
                    ),
                )
            else:
                claim_stage_key = "recorded-model-claim-ledger"
                prepared_claim_stage = self.claim_model_stage.prepare(
                    source.source_observation,
                    source.source_inventory,
                    planning,
                    owner_id=owner_id,
                    run_id=resolved_run_id,
                )
                claim_stage = self._run_stage(
                    stage_key=claim_stage_key,
                    ordered_input_digests=claim_inputs,
                    stage_policy_digest=(
                        prepared_claim_stage.stage_policy_digest
                    ),
                    fresh=lambda: self._build_recorded_model_ledger(
                        source,
                        planning,
                        source_ref,
                        owner_id,
                        prepared_claim_stage,
                    ),
                    reuse=self._load_ledger,
                    output_ref=lambda value: self.artifact_store.ref(
                        value.ledger_envelope
                    ),
                    artifact_refs=lambda value: (
                        self.artifact_store.ref(
                            value.ledger_envelope
                        ),
                    ),
                    metrics=lambda value: (
                        StringValue(
                            key="claims",
                            value=str(len(value.ledger.claims)),
                        ),
                        StringValue(
                            key="unresolved_sources",
                            value=str(
                                len(
                                    value.ledger
                                    .unresolved_source_ids
                                )
                            ),
                        ),
                        StringValue(
                            key="recorded_interactions",
                            value=str(
                                len(
                                    value.ledger
                                    .recorded_interaction_ids
                                )
                            ),
                        ),
                        StringValue(
                            key="interaction_sequence_digest",
                            value=payload_digest(
                                value.ledger
                                .recorded_interaction_ids
                            ),
                        ),
                    ),
                )
                if claim_stage_key not in self._reused_stages:
                    self._record_model_claim_observation(claim_stage)
            ledger = claim_stage.ledger
            ledger_envelope = claim_stage.ledger_envelope
            ledger_ref = self.artifact_store.ref(ledger_envelope)
            audit_stage = self._run_stage(
                stage_key="omission-and-region-audit",
                ordered_input_digests=(
                    inventory_ref.payload_digest,
                    ledger_ref.payload_digest,
                    *(
                        ref.payload_digest
                        for ref in planning.accepted_plan_refs
                    ),
                ),
                fresh=lambda: self._build_audit(
                    source,
                    planning,
                    ledger,
                    inventory_ref,
                    ledger_ref,
                    owner_id,
                ),
                reuse=lambda ref: self._load_audit(
                    ref,
                    source,
                    planning,
                ),
                output_ref=lambda value: self.artifact_store.ref(
                    value.audit_envelope
                ),
                artifact_refs=lambda value: (
                    self.artifact_store.ref(value.audit_envelope),
                    *(
                        self.artifact_store.ref(envelope)
                        for envelope in value.replan_envelopes
                    ),
                ),
                metrics=lambda value: (
                    StringValue(
                        key="omitted_sources",
                        value=str(len(value.audit.omitted_source_ids)),
                    ),
                    StringValue(
                        key="replan_requests",
                        value=str(len(value.replan_requests)),
                    ),
                ),
            )
            audit_ref = self.artifact_store.ref(
                audit_stage.audit_envelope
            )
            replan_refs = tuple(
                self.artifact_store.ref(envelope)
                for envelope in audit_stage.replan_envelopes
            )
            (
                relation_proposal_ledger,
                relation_proposal_envelope,
            ) = self._run_stage(
                stage_key="relation-proposal",
                ordered_input_digests=(
                    source_ref.payload_digest,
                    ledger_ref.payload_digest,
                    *(
                        ref.payload_digest
                        for ref in planning.accepted_plan_refs
                    ),
                    audit_ref.payload_digest,
                    *(ref.payload_digest for ref in replan_refs),
                ),
                fresh=lambda: self._build_relation_proposal(
                    ledger,
                    planning,
                    source_ref,
                    ledger_ref,
                    audit_ref,
                    audit_stage.replan_requests,
                    replan_refs,
                    owner_id,
                ),
                reuse=self._load_relation_proposal,
                output_ref=lambda value: self.artifact_store.ref(value[1]),
                artifact_refs=lambda value: (
                    self.artifact_store.ref(value[1]),
                ),
                metrics=lambda value: (
                    StringValue(
                        key="proposed_relations",
                        value=str(len(value[0].proposed_relations)),
                    ),
                ),
            )
            relation_proposal_ref = self.artifact_store.ref(
                relation_proposal_envelope
            )
            (
                relation_assessment_ledger,
                relation_assessment_envelope,
            ) = self._run_stage(
                stage_key="independent-relation-assessment",
                ordered_input_digests=(
                    relation_proposal_ref.payload_digest,
                ),
                fresh=lambda: self._build_relation_assessment(
                    relation_proposal_ledger,
                    relation_proposal_ref,
                    owner_id,
                ),
                reuse=self._load_relation_assessment,
                output_ref=lambda value: self.artifact_store.ref(value[1]),
                artifact_refs=lambda value: (
                    self.artifact_store.ref(value[1]),
                ),
                metrics=lambda value: (
                    StringValue(
                        key="assessed_relations",
                        value=str(len(value[0].accepted_relations)),
                    ),
                ),
            )
            relation_assessment_ref = self.artifact_store.ref(
                relation_assessment_envelope
            )
            canonical, canonical_envelope = self._run_stage(
                stage_key="canonical-explicit-graph",
                ordered_input_digests=(
                    source_ref.payload_digest,
                    ledger_ref.payload_digest,
                    *(
                        ref.payload_digest
                        for ref in planning.accepted_plan_refs
                    ),
                    audit_ref.payload_digest,
                    *(ref.payload_digest for ref in replan_refs),
                    relation_proposal_ref.payload_digest,
                    relation_assessment_ref.payload_digest,
                ),
                fresh=lambda: self._build_graph(
                    ledger,
                    planning,
                    source_ref,
                    ledger_ref,
                    audit_ref,
                    audit_stage.replan_requests,
                    replan_refs,
                    relation_proposal_ref,
                    relation_assessment_ledger,
                    relation_assessment_ref,
                    owner_id,
                ),
                reuse=self._load_graph,
                output_ref=lambda value: self.artifact_store.ref(value[1]),
                artifact_refs=lambda value: (
                    self.artifact_store.ref(value[1]),
                ),
                metrics=lambda value: (
                    StringValue(
                        key="concepts",
                        value=str(len(value[0].concepts)),
                    ),
                    StringValue(
                        key="relations",
                        value=str(len(value[0].relations)),
                    ),
                ),
            )
            canonical_ref = self.artifact_store.ref(canonical_envelope)
            projection, projection_envelope = self._run_stage(
                stage_key="diagnostic-projection",
                ordered_input_digests=(canonical_ref.payload_digest,),
                fresh=lambda: self._build_projection(
                    canonical,
                    canonical_ref,
                    owner_id,
                ),
                reuse=self._load_projection,
                output_ref=lambda value: self.artifact_store.ref(value[1]),
                artifact_refs=lambda value: (
                    self.artifact_store.ref(value[1]),
                ),
                metrics=lambda value: (
                    StringValue(
                        key="quality_status",
                        value=value[0].quality_status.value,
                    ),
                ),
            )
        except SimulatedWorkerCrash:
            raise
        except Exception:
            assert self._manifest is not None
            failed = next_manifest_revision(
                self._manifest,
                execution_status=ExecutionStatus.FAILED,
            )
            self.control_store.compare_and_swap_manifest(
                failed,
                expected_revision=self._manifest.revision,
            )
            self._manifest = failed
            raise

        projection_ref = self.artifact_store.ref(projection_envelope)
        accepted_relations = [
            relation
            for relation in canonical.relations
            if relation.status is CanonicalStatus.ACCEPTED
        ]
        relation_evidence_coverage = (
            1.0
            if not accepted_relations
            else sum(
                bool(relation.edge_evidence_refs)
                for relation in accepted_relations
            )
            / len(accepted_relations)
        )
        source_integrity_mismatches = len(
            source.source_inventory.raw_manifest.mismatch_codes
        )
        open_replan_count = len(
            [
                request
                for request in audit_stage.replan_requests
                if request.status.value in {"open", "accepted"}
            ]
        )
        quality_metrics = (
            QualityMetric(
                name="source_integrity_mismatch_count",
                value=source_integrity_mismatches,
                threshold=0,
                passed=source_integrity_mismatches == 0,
            ),
            QualityMetric(
                name="omitted_source_count",
                value=len(audit_stage.audit.omitted_source_ids),
                threshold=0,
                passed=not audit_stage.audit.omitted_source_ids,
            ),
            QualityMetric(
                name="open_replan_count",
                value=open_replan_count,
                threshold=0,
                passed=open_replan_count == 0,
            ),
            QualityMetric(
                name="relation_verifier_coverage",
                value=relation_evidence_coverage,
                threshold=1,
                passed=relation_evidence_coverage == 1,
            ),
            QualityMetric(
                name="projection_not_blocked",
                value=(
                    0
                    if projection.quality_status
                    in {
                        ProjectionQualityStatus.BLOCKED_DOCUMENT,
                        ProjectionQualityStatus.BLOCKED_CLAIM,
                        ProjectionQualityStatus.BLOCKED_SEMANTIC,
                        ProjectionQualityStatus.BLOCKED_EVIDENCE,
                    }
                    else 1
                ),
                threshold=1,
                passed=(
                    projection.quality_status
                    not in {
                        ProjectionQualityStatus.BLOCKED_DOCUMENT,
                        ProjectionQualityStatus.BLOCKED_CLAIM,
                        ProjectionQualityStatus.BLOCKED_SEMANTIC,
                        ProjectionQualityStatus.BLOCKED_EVIDENCE,
                    }
                ),
            ),
            QualityMetric(
                name="projection_quality_passed",
                value=(
                    1
                    if projection.quality_status
                    is ProjectionQualityStatus.PASSED
                    else 0
                ),
                threshold=1,
                passed=(
                    projection.quality_status
                    is ProjectionQualityStatus.PASSED
                ),
                hard=False,
            ),
        )
        gate_decision = evaluate_quality_gate(quality_metrics)
        projected_quality_status = _quality_status(
            projection.quality_status
        )
        if gate_decision is QualityGateDecision.BLOCK:
            quality_status = (
                projected_quality_status
                if projected_quality_status
                in {
                    QualityStatus.BLOCKED_DOCUMENT,
                    QualityStatus.BLOCKED_CLAIM,
                    QualityStatus.BLOCKED_SEMANTIC,
                    QualityStatus.BLOCKED_EVIDENCE,
                }
                else (
                    QualityStatus.BLOCKED_SEMANTIC
                    if open_replan_count or relation_evidence_coverage < 1
                    else QualityStatus.BLOCKED_CLAIM
                )
            )
        elif gate_decision in {
            QualityGateDecision.INCOMPLETE,
            QualityGateDecision.REVIEW,
        }:
            quality_status = QualityStatus.REVIEW_REQUIRED
        else:
            quality_status = projected_quality_status
        evaluator_build_digest = _policy_digest(
            "quality-evaluator-build",
            code_revision=self._manifest.declared.code_revision,
        )
        closure_digest = payload_digest(
            {
                "audit": audit_ref.payload_digest,
                "canonical": canonical_ref.payload_digest,
                "claim_ledger": ledger_ref.payload_digest,
                "inventory": inventory_ref.payload_digest,
                "projection": projection_ref.payload_digest,
                "regions": [
                    ref.payload_digest
                    for ref in planning.accepted_plan_refs
                ],
                "relation_assessment": (
                    relation_assessment_ref.payload_digest
                ),
                "relation_proposal": relation_proposal_ref.payload_digest,
                "replans": [ref.payload_digest for ref in replan_refs],
                "source": source_ref.payload_digest,
            }
        )
        self.control_store.record_quality_attestation(
            QualityAttestation(
                attestation_id="attestation_" + secrets.token_hex(16),
                owner_id=owner_id,
                artifact_ref=projection_ref,
                evaluator=_producer(
                    "vnext-quality-auditor",
                    RuntimeRole.QUALITY_AUDITOR,
                ),
                policy_digest=_policy_digest(
                    "quality-gates",
                    code_revision=self._manifest.declared.code_revision,
                ),
                closure_digest=closure_digest,
                evaluator_build_digest=evaluator_build_digest,
                metrics=quality_metrics,
                gate_decision=gate_decision,
                created_at=datetime.now(UTC),
            )
        )
        final_manifest = next_manifest_revision(
            self._manifest,
            execution_status=ExecutionStatus.SUCCEEDED,
            quality_status=quality_status,
            publication_status=PublicationStatus.DRAFT,
        )
        self.control_store.compare_and_swap_manifest(
            final_manifest,
            expected_revision=self._manifest.revision,
        )
        self._manifest = final_manifest
        shadow = ShadowPipelineResult(
            source=source,
            planning=planning,
            claim_ledger=ledger,
            claim_ledger_envelope=ledger_envelope,
            omission_audit=audit_stage.audit,
            omission_audit_envelope=audit_stage.audit_envelope,
            replan_requests=audit_stage.replan_requests,
            replan_envelopes=audit_stage.replan_envelopes,
            relation_proposal_ledger=relation_proposal_ledger,
            relation_proposal_envelope=relation_proposal_envelope,
            relation_assessment_ledger=relation_assessment_ledger,
            relation_assessment_envelope=relation_assessment_envelope,
            canonical_graph=canonical,
            canonical_graph_envelope=canonical_envelope,
            projection=projection,
            projection_envelope=projection_envelope,
        )
        return DurablePipelineResult(
            run_manifest=final_manifest,
            shadow=shadow,
            reused_stages=tuple(self._reused_stages),
        )

    def _load_source_shadow(
        self,
        inventory_ref: ArtifactRef,
    ) -> SourceShadowResult:
        stored_inventory = self.artifact_store.get(
            owner_id=inventory_ref.owner_id,
            artifact_id=inventory_ref.artifact_id,
        )
        if not isinstance(stored_inventory.payload, SourceInventory):
            raise TypeError("source stage output is not SourceInventory")
        source_ref = stored_inventory.payload.document_ir_ref
        stored_source = self.artifact_store.get(
            owner_id=source_ref.owner_id,
            artifact_id=source_ref.artifact_id,
        )
        if not isinstance(stored_source.payload, SourceObservationIR):
            raise TypeError("inventory source reference is not SourceObservationIR")
        return SourceShadowResult(
            source_observation=stored_source.payload,
            source_envelope=stored_source.envelope,
            source_inventory=stored_inventory.payload,
            inventory_envelope=stored_inventory.envelope,
        )

    def _build_ledger(
        self,
        source: SourceShadowResult,
        planning: RegionPlanningResult,
        source_ref: ArtifactRef,
        owner_id: str,
    ) -> _ClaimStageResult:
        ledger = atomize_source_claims(
            source.source_observation,
            document_ir_ref=source_ref,
            region_plan_refs=planning.accepted_plan_refs,
            source_to_leaf_region=planning.source_to_leaf_region,
        )
        envelope = self.artifact_store.put(
            owner_id=owner_id,
            role=RuntimeRole.CLAIM_ATOMIZER,
            payload=ledger,
            producer=_producer(
                "vnext-source-claim-atomizer",
                RuntimeRole.CLAIM_ATOMIZER,
            ),
            input_refs=(source_ref, *planning.accepted_plan_refs),
        )
        return _ClaimStageResult(
            ledger=ledger,
            ledger_envelope=envelope,
        )

    def _build_recorded_model_ledger(
        self,
        source: SourceShadowResult,
        planning: RegionPlanningResult,
        source_ref: ArtifactRef,
        owner_id: str,
        prepared: PreparedRecordedClaimStage,
    ) -> _ClaimStageResult:
        assert self.claim_model_stage is not None
        result: ModelClaimLedgerResult = (
            self.claim_model_stage.build_ledger(
                prepared,
                source_hash=source.source_observation.source_hash,
                document_ir_ref=source_ref,
                region_plan_refs=planning.accepted_plan_refs,
            )
        )
        envelope = self.artifact_store.put(
            owner_id=owner_id,
            role=RuntimeRole.CLAIM_ATOMIZER,
            payload=result.ledger,
            producer=result.ledger.producer,
            input_refs=(source_ref, *planning.accepted_plan_refs),
        )
        return _ClaimStageResult(
            ledger=result.ledger,
            ledger_envelope=envelope,
            interaction_count=result.interaction_count,
            repaired_batches=result.repaired_batches,
            providers=result.providers,
        )

    def _load_ledger(
        self,
        ledger_ref: ArtifactRef,
    ) -> _ClaimStageResult:
        stored = self.artifact_store.get(
            owner_id=ledger_ref.owner_id,
            artifact_id=ledger_ref.artifact_id,
        )
        if not isinstance(stored.payload, ClaimLedger):
            raise TypeError("claim stage output is not ClaimLedger")
        providers = tuple(
            sorted(
                {
                    claim.extractor.model_revision
                    for claim in stored.payload.claims
                    if claim.extractor.model_revision is not None
                }
            )
        )
        return _ClaimStageResult(
            ledger=stored.payload,
            ledger_envelope=stored.envelope,
            interaction_count=len(
                stored.payload.recorded_interaction_ids
            ),
            providers=providers,
        )

    def _build_audit(
        self,
        source: SourceShadowResult,
        planning: RegionPlanningResult,
        ledger: ClaimLedger,
        inventory_ref: ArtifactRef,
        ledger_ref: ArtifactRef,
        owner_id: str,
    ) -> _AuditStageResult:
        audit = audit_claim_omissions(
            source.source_inventory,
            ledger,
            source_inventory_ref=inventory_ref,
            claim_ledger_ref=ledger_ref,
            structurally_accounted_source_ids=(
                planning.structurally_accounted_source_ids
            ),
            forced_unresolved_source_ids=planning.unresolved_source_ids,
        )
        audit_envelope = self.artifact_store.put(
            owner_id=owner_id,
            role=RuntimeRole.OMISSION_AUDITOR,
            payload=audit,
            producer=_producer(
                "vnext-source-omission-auditor",
                RuntimeRole.OMISSION_AUDITOR,
            ),
            input_refs=(inventory_ref, ledger_ref),
        )
        audit_ref = self.artifact_store.ref(audit_envelope)
        requests = audit_regions_bottom_up(
            planning,
            source.source_inventory,
            audit,
        )
        envelopes: list[ArtifactEnvelope] = []
        for request in requests:
            region_ref = planning.plan_ref_by_region.get(
                request.affected_region_id
            )
            inputs = (
                (audit_ref, region_ref)
                if region_ref is not None
                else (audit_ref,)
            )
            envelopes.append(
                self.artifact_store.put(
                    owner_id=owner_id,
                    role=RuntimeRole.BOTTOM_UP_REGION_AUDITOR,
                    payload=request,
                    producer=_producer(
                        "vnext-bottom-up-region-auditor",
                        RuntimeRole.BOTTOM_UP_REGION_AUDITOR,
                    ),
                    input_refs=inputs,
                )
            )
        return _AuditStageResult(
            audit=audit,
            audit_envelope=audit_envelope,
            replan_requests=requests,
            replan_envelopes=tuple(envelopes),
        )

    def _load_audit(
        self,
        audit_ref: ArtifactRef,
        source: SourceShadowResult,
        planning: RegionPlanningResult,
    ) -> _AuditStageResult:
        stored = self.artifact_store.get(
            owner_id=audit_ref.owner_id,
            artifact_id=audit_ref.artifact_id,
        )
        if not isinstance(stored.payload, OmissionAudit):
            raise TypeError("audit stage output is not OmissionAudit")
        linked: list[tuple[ReplanRequest, ArtifactEnvelope]] = []
        for envelope in self.artifact_store.list_envelopes(
            owner_id=audit_ref.owner_id
        ):
            if not any(
                ref.artifact_id == audit_ref.artifact_id
                for ref in envelope.input_refs
            ):
                continue
            try:
                candidate = self.artifact_store.get(
                    owner_id=audit_ref.owner_id,
                    artifact_id=envelope.artifact_id,
                )
            except (FileNotFoundError, ValueError):
                continue
            if (
                isinstance(candidate.payload, ReplanRequest)
            ):
                linked.append((candidate.payload, candidate.envelope))
        if linked:
            superseded_artifact_ids = {
                request.supersedes.artifact_id
                for request, _ in linked
                if request.supersedes is not None
            }
            terminal = tuple(
                (request, envelope)
                for request, envelope in linked
                if envelope.artifact_id not in superseded_artifact_ids
            )
            requests = tuple(
                request
                for request, _ in sorted(
                    terminal,
                    key=lambda item: (
                        item[0].affected_region_id,
                        item[0].request_id,
                        item[1].artifact_id,
                    ),
                )
            )
            envelopes = tuple(
                envelope
                for _, envelope in sorted(
                    terminal,
                    key=lambda item: (
                        item[0].affected_region_id,
                        item[0].request_id,
                        item[1].artifact_id,
                    ),
                )
            )
        else:
            requests = audit_regions_bottom_up(
                planning,
                source.source_inventory,
                stored.payload,
            )
            envelopes = ()
        return _AuditStageResult(
            audit=stored.payload,
            audit_envelope=stored.envelope,
            replan_requests=requests,
            replan_envelopes=envelopes,
        )

    def _build_graph(
        self,
        ledger: ClaimLedger,
        planning: RegionPlanningResult,
        source_ref: ArtifactRef,
        ledger_ref: ArtifactRef,
        audit_ref: ArtifactRef,
        replan_requests: tuple[ReplanRequest, ...],
        replan_refs: tuple[ArtifactRef, ...],
        relation_proposal_ref: ArtifactRef,
        relation_assessment_ledger: RelationAssessmentLedger,
        relation_assessment_ref: ArtifactRef,
        owner_id: str,
    ) -> tuple[CanonicalExplicitGraph, ArtifactEnvelope]:
        graph = build_canonical_explicit_graph(
            ledger,
            planning,
            source_observation_ref=source_ref,
            claim_ledger_ref=ledger_ref,
            relation_assessment_ledger=relation_assessment_ledger,
            replan_requests=replan_requests,
            additional_input_refs=(audit_ref, *replan_refs),
        )
        envelope = self.artifact_store.put(
            owner_id=owner_id,
            role=RuntimeRole.CANONICALIZER,
            payload=graph,
            producer=_producer(
                "vnext-explicit-canonicalizer",
                RuntimeRole.CANONICALIZER,
            ),
            input_refs=(
                source_ref,
                ledger_ref,
                *planning.accepted_plan_refs,
                audit_ref,
                *replan_refs,
                relation_proposal_ref,
                relation_assessment_ref,
            ),
        )
        return graph, envelope

    def _build_relation_proposal(
        self,
        ledger: ClaimLedger,
        planning: RegionPlanningResult,
        source_ref: ArtifactRef,
        ledger_ref: ArtifactRef,
        audit_ref: ArtifactRef,
        replan_requests: tuple[ReplanRequest, ...],
        replan_refs: tuple[ArtifactRef, ...],
        owner_id: str,
    ) -> tuple[RelationProposalLedger, ArtifactEnvelope]:
        proposal = build_relation_proposal_ledger(
            ledger,
            planning,
            source_observation_ref=source_ref,
            claim_ledger_ref=ledger_ref,
            replan_requests=replan_requests,
            additional_input_refs=(audit_ref, *replan_refs),
        )
        envelope = self.artifact_store.put(
            owner_id=owner_id,
            role=RuntimeRole.RELATION_PROPOSER,
            payload=proposal,
            producer=_producer(
                "vnext-explicit-relation-proposer",
                RuntimeRole.RELATION_PROPOSER,
            ),
            input_refs=(
                source_ref,
                ledger_ref,
                *planning.accepted_plan_refs,
                audit_ref,
                *replan_refs,
            ),
        )
        return proposal, envelope

    def _load_relation_proposal(
        self,
        proposal_ref: ArtifactRef,
    ) -> tuple[RelationProposalLedger, ArtifactEnvelope]:
        stored = self.artifact_store.get(
            owner_id=proposal_ref.owner_id,
            artifact_id=proposal_ref.artifact_id,
        )
        if not isinstance(stored.payload, RelationProposalLedger):
            raise TypeError(
                "relation stage output is not RelationProposalLedger"
            )
        return stored.payload, stored.envelope

    def _build_relation_assessment(
        self,
        proposal: RelationProposalLedger,
        proposal_ref: ArtifactRef,
        owner_id: str,
    ) -> tuple[RelationAssessmentLedger, ArtifactEnvelope]:
        assessment = build_relation_assessment_ledger(
            proposal,
        )
        envelope = self.artifact_store.put(
            owner_id=owner_id,
            role=RuntimeRole.RELATION_VERIFIER_A,
            payload=assessment,
            producer=_producer(
                "vnext-explicit-relation-verifier-a",
                RuntimeRole.RELATION_VERIFIER_A,
            ),
            input_refs=(proposal_ref,),
        )
        return assessment, envelope

    def _load_relation_assessment(
        self,
        assessment_ref: ArtifactRef,
    ) -> tuple[RelationAssessmentLedger, ArtifactEnvelope]:
        stored = self.artifact_store.get(
            owner_id=assessment_ref.owner_id,
            artifact_id=assessment_ref.artifact_id,
        )
        if not isinstance(stored.payload, RelationAssessmentLedger):
            raise TypeError(
                "relation stage output is not RelationAssessmentLedger"
            )
        return stored.payload, stored.envelope

    def _load_graph(
        self,
        graph_ref: ArtifactRef,
    ) -> tuple[CanonicalExplicitGraph, ArtifactEnvelope]:
        stored = self.artifact_store.get(
            owner_id=graph_ref.owner_id,
            artifact_id=graph_ref.artifact_id,
        )
        if not isinstance(stored.payload, CanonicalExplicitGraph):
            raise TypeError("graph stage output is not CanonicalExplicitGraph")
        return stored.payload, stored.envelope

    def _build_projection(
        self,
        graph: CanonicalExplicitGraph,
        graph_ref: ArtifactRef,
        owner_id: str,
    ) -> tuple[DiagnosticProjection, ArtifactEnvelope]:
        projection = build_diagnostic_projection(
            graph,
            canonical_graph_ref=graph_ref,
        )
        envelope = self.artifact_store.put(
            owner_id=owner_id,
            role=RuntimeRole.PROJECTION_PLANNER,
            payload=projection,
            producer=_producer(
                "vnext-diagnostic-projection-planner",
                RuntimeRole.PROJECTION_PLANNER,
            ),
            input_refs=(graph_ref,),
        )
        return projection, envelope

    def _load_projection(
        self,
        projection_ref: ArtifactRef,
    ) -> tuple[DiagnosticProjection, ArtifactEnvelope]:
        stored = self.artifact_store.get(
            owner_id=projection_ref.owner_id,
            artifact_id=projection_ref.artifact_id,
        )
        if not isinstance(stored.payload, DiagnosticProjection):
            raise TypeError("projection stage output is not DiagnosticProjection")
        return stored.payload, stored.envelope


def run_durable_shadow_pipeline(
    path: Path,
    *,
    owner_id: str,
    artifact_store: LocalArtifactStore,
    control_store: SQLiteControlStore,
    worker_id: str,
    run_id: str | None = None,
    crash_after_stage: str | None = None,
    region_model_stage: RecordedRegionModelStage | None = None,
    claim_model_stage: RecordedClaimModelStage | None = None,
) -> DurablePipelineResult:
    return DurableShadowSupervisor(
        artifact_store=artifact_store,
        control_store=control_store,
        worker_id=worker_id,
        crash_after_stage=crash_after_stage,
        region_model_stage=region_model_stage,
        claim_model_stage=claim_model_stage,
    ).run(
        path,
        owner_id=owner_id,
        run_id=run_id,
    )
