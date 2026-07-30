from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from backend.vnext.artifacts.canonical import (
    canonical_json_bytes,
    payload_digest,
)
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
    SourceEntailmentStatus,
)
from backend.vnext.contracts.common import (
    ArtifactProducerRef,
    ArtifactRef,
    RuntimeRole,
)
from backend.vnext.contracts.control import (
    ModelPortfolioManifest,
    ModelSlot,
    TaskBudgetSlice,
    TaskEnvelope,
)
from backend.vnext.contracts.evidence import (
    EvidenceNamespace,
    EvidenceRef,
)
from backend.vnext.contracts.inventory import (
    InventoryEntryKind,
    SourceInventory,
)
from backend.vnext.contracts.model_semantics import (
    CLAIM_PROPOSAL_BATCH_SCHEMA_ID,
    ClaimProposalBatch,
)
from backend.vnext.contracts.source import (
    ChemicalReactionIR,
    NativeObjectKind,
    SourceObservationIR,
)
from backend.vnext.model_runtime import (
    ModelCall,
    StructuredModelAdapter,
)
from backend.vnext.regions.planner import RegionPlanningResult


MODEL_CLAIM_STAGE_VERSION = "1.0.0"
MODEL_CLAIM_PROMPT_VERSION = "source-only-claim-proposal-v1"

_SYSTEM_PROMPT = (
    "You are a source-only Claim Atomizer. Use only the supplied source "
    "cards. Select exact, contiguous quote spans; classify each selected "
    "span; and abstain when a card cannot be safely atomized. Do not invent "
    "IDs, facts, evidence, parent relationships, or publication decisions. "
    "Every supplied source_id must appear in at least one proposal or in "
    "unresolved_source_ids."
)
_FIDELITY_VERIFIER = ArtifactProducerRef(
    producer_id="vnext-exact-quote-fidelity-verifier",
    producer_version=MODEL_CLAIM_STAGE_VERSION,
    role=RuntimeRole.CLAIM_FIDELITY_VERIFIER,
)


class ModelClaimStageError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ClaimSourceCard:
    source_id: str
    source_kind: str
    declared_role: str | None
    text: str
    scope: ClaimScope
    evidence_refs: tuple[EvidenceRef, ...]

    def prompt_payload(self) -> dict[str, object]:
        return {
            "declared_role": self.declared_role,
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class ModelClaimTask:
    task_key: str
    region_id: str
    envelope: TaskEnvelope
    call: ModelCall
    cards: tuple[ClaimSourceCard, ...]
    prompt_digest: str


@dataclass(frozen=True, slots=True)
class PreparedRecordedClaimStage:
    tasks: tuple[ModelClaimTask, ...]
    automatic_unresolved_source_ids: tuple[str, ...]
    stage_policy_digest: str


@dataclass(frozen=True, slots=True)
class ModelClaimLedgerResult:
    ledger: ClaimLedger
    interaction_count: int
    repaired_batches: int
    providers: tuple[str, ...]


def _stable_id(prefix: str, value: object) -> str:
    digest = hashlib.sha256(
        b"zlb-vnext-model-claim-v1\0" + canonical_json_bytes(value)
    ).hexdigest()
    return prefix + digest[:32]


def _normalized(text: str) -> str:
    return " ".join(text.split()).strip()


def _unique_evidence(
    evidence_refs: Sequence[EvidenceRef],
) -> tuple[EvidenceRef, ...]:
    unique: dict[tuple[str, str], EvidenceRef] = {}
    for evidence in evidence_refs:
        if evidence.namespace not in {
            EvidenceNamespace.COURSEWARE,
            EvidenceNamespace.HUMAN,
        }:
            continue
        unique[(evidence.namespace.value, evidence.ref_id)] = evidence
    return tuple(unique.values())


def _reaction_text(reaction: ChemicalReactionIR) -> str:
    left = " + ".join(item.label for item in reaction.reactants)
    right = " + ".join(item.label for item in reaction.products)
    if not left or not right:
        return ""
    body = f"{left} {reaction.arrow} {right}"
    conditions = "; ".join(item.text for item in reaction.conditions)
    return body if not conditions else f"{body}; {conditions}"


def _source_material(
    source: SourceObservationIR,
) -> dict[str, tuple[str, ClaimScope, tuple[EvidenceRef, ...]]]:
    material: dict[
        str,
        tuple[str, ClaimScope, tuple[EvidenceRef, ...]],
    ] = {}
    for page in source.pages:
        for block in page.blocks:
            material[block.block_id] = (
                block.text,
                ClaimScope.OBJECT,
                _unique_evidence(block.evidence_refs),
            )
        for obj in page.native_objects:
            if obj.kind is NativeObjectKind.TABLE and obj.table is not None:
                for cell in obj.table.cells:
                    material[cell.cell_id] = (
                        cell.text,
                        ClaimScope.OBJECT,
                        _unique_evidence(cell.evidence_refs),
                    )
                continue
            text = obj.text
            if obj.kind is NativeObjectKind.FORMULA and obj.formula:
                text = obj.formula.display_text or text
            elif (
                obj.kind is NativeObjectKind.CHEMICAL_REACTION
                and obj.reaction
            ):
                text = text or _reaction_text(obj.reaction)
            material[obj.object_id] = (
                text,
                ClaimScope.OBJECT,
                _unique_evidence(obj.evidence_refs),
            )
    for item in source.outline_entries:
        material[item.outline_entry_id] = (
            item.label,
            ClaimScope.REGION,
            _unique_evidence(item.evidence_refs),
        )
    for item in source.unresolved_regions:
        material[item.region_source_id] = (
            "",
            ClaimScope.OBJECT,
            _unique_evidence(item.evidence_refs),
        )
    return material


def prepare_model_claim_tasks(
    source: SourceObservationIR,
    inventory: SourceInventory,
    planning: RegionPlanningResult,
    *,
    owner_id: str,
    run_id: str,
    max_cards_per_task: int = 48,
    max_output_tokens: int = 8192,
    max_cost_microunits_per_task: int = 0,
) -> tuple[tuple[ModelClaimTask, ...], tuple[str, ...]]:
    if max_cards_per_task < 1:
        raise ValueError("max_cards_per_task must be positive")
    material = _source_material(source)
    cards_by_region: dict[str, list[ClaimSourceCard]] = {}
    automatic_unresolved: set[str] = set(planning.unresolved_source_ids)
    for entry in inventory.all_entries():
        if entry.source_kind is InventoryEntryKind.PAGE:
            continue
        region_id = planning.source_to_leaf_region.get(entry.source_id)
        source_material = material.get(entry.source_id)
        if region_id is None:
            if entry.source_id not in (
                planning.structurally_accounted_source_ids
            ):
                automatic_unresolved.add(entry.source_id)
            continue
        if source_material is None:
            automatic_unresolved.add(entry.source_id)
            continue
        text, scope, evidence_refs = source_material
        normalized_text = _normalized(text)
        if not normalized_text or not evidence_refs:
            automatic_unresolved.add(entry.source_id)
            continue
        cards_by_region.setdefault(region_id, []).append(
            ClaimSourceCard(
                source_id=entry.source_id,
                source_kind=entry.source_kind.value,
                declared_role=entry.declared_role,
                text=normalized_text,
                scope=scope,
                evidence_refs=evidence_refs,
            )
        )

    tasks: list[ModelClaimTask] = []
    for region_id, cards in cards_by_region.items():
        for offset in range(0, len(cards), max_cards_per_task):
            chunk = tuple(cards[offset : offset + max_cards_per_task])
            chunk_index = offset // max_cards_per_task + 1
            task_key = (
                f"claim-proposal:{region_id}:{chunk_index:04d}"
            )
            idempotency_key = payload_digest(
                {
                    "cards": [
                        {
                            "evidence": [
                                item.model_dump(mode="json")
                                for item in card.evidence_refs
                            ],
                            "scope": card.scope.value,
                            **card.prompt_payload(),
                        }
                        for card in chunk
                    ],
                    "prompt_version": MODEL_CLAIM_PROMPT_VERSION,
                    "region_id": region_id,
                    "schema_id": CLAIM_PROPOSAL_BATCH_SCHEMA_ID,
                }
            )
            envelope = TaskEnvelope(
                artifact_version="1.0.0",
                source_ids=tuple(card.source_id for card in chunk),
                role_policy=RuntimeRole.CLAIM_ATOMIZER,
                budget_slice=TaskBudgetSlice(
                    max_wall_seconds=120,
                    max_calls=1,
                    max_cost_microunits=max_cost_microunits_per_task,
                ),
                output_schema=CLAIM_PROPOSAL_BATCH_SCHEMA_ID,
                expected_artifact_version="1.0.0",
                idempotency_key=idempotency_key,
            )
            user_prompt = canonical_json_bytes(
                {
                    "source_cards": [
                        card.prompt_payload() for card in chunk
                    ],
                    "task_envelope": envelope,
                }
            ).decode("utf-8")
            prompt_digest = payload_digest(
                {
                    "system_prompt": _SYSTEM_PROMPT,
                    "user_prompt": user_prompt,
                }
            )
            tasks.append(
                ModelClaimTask(
                    task_key=task_key,
                    region_id=region_id,
                    envelope=envelope,
                    call=ModelCall(
                        owner_id=owner_id,
                        run_id=run_id,
                        stage_key=task_key,
                        role=RuntimeRole.CLAIM_ATOMIZER,
                        system_prompt=_SYSTEM_PROMPT,
                        user_prompt=user_prompt,
                        max_output_tokens=max_output_tokens,
                        random_seed=0,
                    ),
                    cards=chunk,
                    prompt_digest=prompt_digest,
                )
            )
    return tuple(tasks), tuple(sorted(automatic_unresolved))


def _publication_status(
    claim_type: ClaimType,
) -> ClaimPublicationStatus:
    if claim_type is ClaimType.INSTRUCTION:
        return ClaimPublicationStatus.WITHHELD
    if claim_type is ClaimType.STRUCTURAL_FACT:
        return ClaimPublicationStatus.CANDIDATE
    return ClaimPublicationStatus.CORE


def _claims_from_batch(
    task: ModelClaimTask,
    batch: ClaimProposalBatch,
    *,
    source_hash: str,
    provider: str,
    model_revision: str,
) -> tuple[tuple[ClaimRecord, ...], tuple[str, ...]]:
    card_by_id = {card.source_id: card for card in task.cards}
    expected_ids = set(card_by_id)
    proposed_ids = {item.source_id for item in batch.proposals}
    unresolved_ids = set(batch.unresolved_source_ids)
    observed_ids = proposed_ids | unresolved_ids
    unknown = observed_ids - expected_ids
    missing = expected_ids - observed_ids
    if unknown:
        raise ModelClaimStageError(
            "model claim batch references unknown source IDs: "
            + ", ".join(sorted(unknown))
        )
    if missing:
        raise ModelClaimStageError(
            "model claim batch did not reconcile source IDs: "
            + ", ".join(sorted(missing))
        )

    extractor = ArtifactProducerRef(
        producer_id="vnext-model-claim-atomizer",
        producer_version=MODEL_CLAIM_STAGE_VERSION,
        role=RuntimeRole.CLAIM_ATOMIZER,
        model_revision=model_revision,
        prompt_digest=task.prompt_digest,
    )
    claims: list[ClaimRecord] = []
    for proposal in batch.proposals:
        card = card_by_id[proposal.source_id]
        quote = _normalized(proposal.source_quote)
        if not quote or quote not in card.text:
            raise ModelClaimStageError(
                "model claim quote is not an exact source span for "
                f"{proposal.source_id}"
            )
        claims.append(
            ClaimRecord(
                claim_id=_stable_id(
                    "claim_",
                    {
                        "claim_type": proposal.claim_type.value,
                        "leaf_region_id": task.region_id,
                        "model_revision": model_revision,
                        "predicate": proposal.predicate,
                        "prompt_digest": task.prompt_digest,
                        "provider": provider,
                        "source_hash": source_hash,
                        "source_id": proposal.source_id,
                        "source_quote": quote,
                    },
                ),
                leaf_region_id=task.region_id,
                claim_type=proposal.claim_type,
                normalized_text=quote,
                source_text=quote,
                predicate=proposal.predicate,
                instructional_role=proposal.instructional_role,
                novelty=ClaimNovelty.SOURCE_EXPLICIT,
                scope=card.scope,
                source_evidence_refs=card.evidence_refs,
                extraction_confidence=1,
                extraction_status=ExtractionStatus.EXTRACTED,
                source_entailment_status=SourceEntailmentStatus.ENTAILED,
                external_validity_status=(
                    ExternalValidityStatus.NOT_CHECKED
                ),
                publication_status=_publication_status(
                    proposal.claim_type
                ),
                extractor=extractor,
                fidelity_verifier=_FIDELITY_VERIFIER,
            )
        )
    return tuple(claims), tuple(sorted(unresolved_ids))


class RecordedClaimModelStage:
    def __init__(
        self,
        *,
        adapter: StructuredModelAdapter,
        model_slot: ModelSlot,
        replay_sequences: Mapping[str, Sequence[str]],
        max_cards_per_task: int = 48,
        max_output_tokens: int = 8192,
    ):
        if model_slot.slot != "claim_extractor":
            raise ValueError(
                "recorded claim stage requires claim_extractor slot"
            )
        if not model_slot.structured_output:
            raise ValueError(
                "recorded claim stage requires structured output"
            )
        if adapter.replay_store is None:
            raise ValueError(
                "recorded claim stage requires a replay store"
            )
        if not any(
            endpoint.provider == model_slot.provider
            and endpoint.model_revision == model_slot.model_revision
            for endpoint in adapter.endpoints
        ):
            raise ValueError(
                "claim extractor slot does not match adapter endpoint"
            )
        normalized_sequences = {
            str(key): tuple(value)
            for key, value in replay_sequences.items()
        }
        all_ids = [
            interaction_id
            for sequence in normalized_sequences.values()
            for interaction_id in sequence
        ]
        if any(not sequence for sequence in normalized_sequences.values()):
            raise ValueError(
                "recorded claim task sequences must not be empty"
            )
        if len(all_ids) != len(set(all_ids)):
            raise ValueError(
                "recorded interactions cannot be reused across claim tasks"
            )
        self.adapter = adapter
        self.model_slot = model_slot
        self.replay_sequences = normalized_sequences
        self.max_cards_per_task = max_cards_per_task
        self.max_output_tokens = max_output_tokens

    @property
    def portfolio(self) -> ModelPortfolioManifest:
        return ModelPortfolioManifest(slots=(self.model_slot,))

    @property
    def recorded_interaction_count(self) -> int:
        return sum(
            len(sequence)
            for sequence in self.replay_sequences.values()
        )

    @property
    def prompt_policy_digest(self) -> str:
        return payload_digest(
            {
                "model_slot": self.model_slot,
                "prompt_version": MODEL_CLAIM_PROMPT_VERSION,
                "schema": ClaimProposalBatch.model_json_schema(
                    mode="validation"
                ),
            }
        )

    def execution_policy_digest(self, *, owner_id: str) -> str:
        assert self.adapter.replay_store is not None
        snapshots: list[dict[str, object]] = []
        for task_key, sequence in sorted(self.replay_sequences.items()):
            interactions = []
            for interaction_id in sequence:
                recorded = self.adapter.replay_store.load(
                    owner_id=owner_id,
                    interaction_id=interaction_id,
                )
                manifest = recorded.manifest
                if (
                    manifest.provider != self.model_slot.provider
                    or manifest.model_revision
                    != self.model_slot.model_revision
                ):
                    raise ValueError(
                        "recorded claim interaction is outside the "
                        "declared model slot"
                    )
                interactions.append(
                    {
                        "model_revision": manifest.model_revision,
                        "provider": manifest.provider,
                        "request_digest": manifest.request_digest,
                        "response_digest": manifest.response_digest,
                        "tool_result_digests": (
                            manifest.tool_result_digests
                        ),
                    }
                )
            snapshots.append(
                {
                    "interactions": interactions,
                    "task_key": task_key,
                }
            )
        return payload_digest(
            {
                "prompt_policy_digest": self.prompt_policy_digest,
                "recorded_snapshots": snapshots,
            }
        )

    def prepare(
        self,
        source: SourceObservationIR,
        inventory: SourceInventory,
        planning: RegionPlanningResult,
        *,
        owner_id: str,
        run_id: str,
    ) -> PreparedRecordedClaimStage:
        tasks, automatic_unresolved = prepare_model_claim_tasks(
            source,
            inventory,
            planning,
            owner_id=owner_id,
            run_id=run_id,
            max_cards_per_task=self.max_cards_per_task,
            max_output_tokens=self.max_output_tokens,
        )
        task_keys = {task.task_key for task in tasks}
        sequence_keys = set(self.replay_sequences)
        if task_keys != sequence_keys:
            missing = task_keys - sequence_keys
            extra = sequence_keys - task_keys
            details = []
            if missing:
                details.append(
                    "missing=" + ",".join(sorted(missing))
                )
            if extra:
                details.append("extra=" + ",".join(sorted(extra)))
            raise ModelClaimStageError(
                "recorded claim sequences do not match prepared tasks: "
                + "; ".join(details)
            )
        return PreparedRecordedClaimStage(
            tasks=tasks,
            automatic_unresolved_source_ids=automatic_unresolved,
            stage_policy_digest=self.execution_policy_digest(
                owner_id=owner_id
            ),
        )

    def build_ledger(
        self,
        prepared: PreparedRecordedClaimStage,
        *,
        source_hash: str,
        document_ir_ref: ArtifactRef,
        region_plan_refs: tuple[ArtifactRef, ...],
    ) -> ModelClaimLedgerResult:
        claims: list[ClaimRecord] = []
        unresolved = set(
            prepared.automatic_unresolved_source_ids
        )
        interaction_ids: list[str] = []
        providers: list[str] = []
        repaired_batches = 0
        for task in prepared.tasks:
            result = self.adapter.replay_sequence(
                task.call,
                ClaimProposalBatch,
                self.replay_sequences[task.task_key],
            )
            if result.used_fallback:
                raise ModelClaimStageError(
                    "recorded claim stage fallback is outside the "
                    "declared model portfolio"
                )
            batch_claims, batch_unresolved = _claims_from_batch(
                task,
                result.value,
                source_hash=source_hash,
                provider=result.provider,
                model_revision=result.model_revision,
            )
            claims.extend(batch_claims)
            unresolved.update(batch_unresolved)
            interaction_ids.extend(result.interaction_ids)
            providers.append(result.provider)
            repaired_batches += int(result.repaired)

        claims.sort(key=lambda item: item.claim_id)
        recorded_ids = tuple(interaction_ids)
        producer = ArtifactProducerRef(
            producer_id="vnext-recorded-model-claim-stage",
            producer_version=MODEL_CLAIM_STAGE_VERSION,
            role=RuntimeRole.CLAIM_ATOMIZER,
            prompt_digest=self.prompt_policy_digest,
        )
        ledger = ClaimLedger(
            ledger_id=_stable_id(
                "ledger_",
                {
                    "claims": [
                        item.model_dump(mode="json") for item in claims
                    ],
                    "document_ir_digest": document_ir_ref.payload_digest,
                    "recorded_interaction_ids": recorded_ids,
                    "region_plan_digests": [
                        item.payload_digest
                        for item in region_plan_refs
                    ],
                    "stage_policy_digest": (
                        prepared.stage_policy_digest
                    ),
                    "unresolved_source_ids": sorted(unresolved),
                },
            ),
            document_ir_ref=document_ir_ref,
            region_plan_refs=region_plan_refs,
            claims=tuple(claims),
            producer=producer,
            unresolved_source_ids=tuple(sorted(unresolved)),
            recorded_interaction_ids=recorded_ids,
        )
        return ModelClaimLedgerResult(
            ledger=ledger,
            interaction_count=len(recorded_ids),
            repaired_batches=repaired_batches,
            providers=tuple(sorted(set(providers))),
        )
