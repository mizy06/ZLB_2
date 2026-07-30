from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from backend.vnext.artifacts.canonical import (
    canonical_json_bytes,
    payload_digest,
)
from backend.vnext.contracts.common import (
    ArtifactProducerRef,
    RuntimeRole,
)
from backend.vnext.contracts.control import (
    ModelPortfolioManifest,
    ModelSlot,
    TaskBudgetSlice,
    TaskEnvelope,
)
from backend.vnext.contracts.inventory import SourceInventory
from backend.vnext.contracts.model_semantics import (
    REGION_DECISION_VERIFICATION_SCHEMA_ID,
    REGION_PLANNER_PROPOSAL_SCHEMA_ID,
    RegionDecisionVerification,
    RegionPlannerProposal,
    RegionVerificationVerdict,
)
from backend.vnext.contracts.regions import RegionProposalAction
from backend.vnext.contracts.source import (
    NativeObjectKind,
    SourceObservationIR,
)
from backend.vnext.model_runtime import ModelCall, StructuredModelAdapter
from backend.vnext.model_runtime.router import require_independent_pair

from .planner import (
    ExplicitRegionDecisionContext,
    RegionSemanticDecision,
    enumerate_explicit_region_decision_contexts,
)


MODEL_REGION_STAGE_VERSION = "1.0.0"
MODEL_REGION_PLANNER_PROMPT_VERSION = (
    "explicit-top-down-region-proposal-v1"
)
MODEL_REGION_VERIFIER_PROMPT_VERSION = (
    "independent-region-decision-verification-v1"
)

_GLOBAL_TASK_PREFIX = "region-plan-proposal:global:"
_RECURSIVE_TASK_PREFIX = "region-plan-proposal:recursive:"
_VERIFIER_TASK_PREFIX = "region-decision-verification:"

_PLANNER_SYSTEM_PROMPT = (
    "You are a top-down Region Planner operating only on explicit source "
    "anchors. Use only the supplied source cards. Repeat the exact anchor "
    "quote. SPLIT may contain only the supplied direct child anchor IDs in "
    "their supplied order; STOP is allowed only when there are no direct "
    "child anchors; otherwise abstain with UNRESOLVED. Do not create source "
    "IDs, region IDs, parents, ancestor paths, memberships, evidence refs, "
    "or publication states."
)
_VERIFIER_SYSTEM_PROMPT = (
    "You are an independent Region Decision Verifier. Evaluate only the "
    "supplied planner proposal and source cards. Do not create or reorder "
    "anchors, propose another parent, or write region IDs, memberships, "
    "evidence refs, or publication states. ACCEPT only when every semantic "
    "check is supported; otherwise REJECT or mark UNRESOLVED."
)


class ModelRegionStageError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RegionSourceCard:
    source_id: str
    source_kind: str
    declared_role: str | None
    text: str

    def prompt_payload(self) -> dict[str, object]:
        return {
            "declared_role": self.declared_role,
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class RegionPlannerTask:
    task_key: str
    context: ExplicitRegionDecisionContext
    envelope: TaskEnvelope
    call: ModelCall
    cards: tuple[RegionSourceCard, ...]
    prompt_digest: str


@dataclass(frozen=True, slots=True)
class RegionVerifierTask:
    task_key: str
    planner_task: RegionPlannerTask
    proposal: RegionPlannerProposal
    envelope: TaskEnvelope
    call: ModelCall
    prompt_digest: str


def _reaction_text(reaction) -> str:
    left = " + ".join(item.label for item in reaction.reactants)
    right = " + ".join(item.label for item in reaction.products)
    if not left or not right:
        return ""
    body = f"{left} {reaction.arrow} {right}"
    conditions = "; ".join(item.text for item in reaction.conditions)
    return body if not conditions else f"{body}; {conditions}"


def _source_text(source: SourceObservationIR) -> dict[str, str]:
    values: dict[str, str] = {}
    for page in source.pages:
        values[page.page_id] = f"page {page.physical_index}"
        for block in page.blocks:
            values[block.block_id] = block.text
        for obj in page.native_objects:
            text = obj.text
            if obj.kind is NativeObjectKind.FORMULA and obj.formula:
                text = obj.formula.display_text or text
            elif (
                obj.kind is NativeObjectKind.CHEMICAL_REACTION
                and obj.reaction is not None
            ):
                text = text or _reaction_text(obj.reaction)
            values[obj.object_id] = text
            if obj.table is not None:
                for cell in obj.table.cells:
                    values[cell.cell_id] = cell.text
    for item in source.outline_entries:
        values[item.outline_entry_id] = item.label
    for item in source.unresolved_regions:
        values[item.region_source_id] = ""
    return values


def _planner_task_key(
    context: ExplicitRegionDecisionContext,
) -> str:
    prefix = (
        _GLOBAL_TASK_PREFIX
        if context.planner_role
        is RuntimeRole.GLOBAL_STRUCTURE_PLANNER
        else _RECURSIVE_TASK_PREFIX
    )
    return prefix + context.anchor_source_id


def _verifier_task_key(
    context: ExplicitRegionDecisionContext,
) -> str:
    return _VERIFIER_TASK_PREFIX + context.anchor_source_id


def _cards_for_context(
    source: SourceObservationIR,
    inventory: SourceInventory,
    context: ExplicitRegionDecisionContext,
    *,
    max_cards_per_task: int,
) -> tuple[RegionSourceCard, ...]:
    inventory_by_id = {
        item.source_id: item for item in inventory.all_entries()
    }
    text_by_id = _source_text(source)
    ordered_ids = (
        context.anchor_source_id,
        *context.child_anchor_source_ids,
        *context.primary_source_ids,
        *context.secondary_source_ids,
    )
    unique_ids = tuple(dict.fromkeys(ordered_ids))
    if len(unique_ids) > max_cards_per_task:
        raise ModelRegionStageError(
            "recorded region scope exceeds source card budget"
        )
    cards: list[RegionSourceCard] = []
    for source_id in unique_ids:
        entry = inventory_by_id.get(source_id)
        if entry is None:
            raise ModelRegionStageError(
                f"region context references unknown source {source_id}"
            )
        cards.append(
            RegionSourceCard(
                source_id=source_id,
                source_kind=entry.source_kind.value,
                declared_role=entry.declared_role,
                text=text_by_id.get(source_id, ""),
            )
        )
    return tuple(cards)


def _planner_prompt_payload(
    task_context: ExplicitRegionDecisionContext,
    cards: tuple[RegionSourceCard, ...],
) -> dict[str, object]:
    return {
        "anchor_label": task_context.anchor_label,
        "anchor_source_id": task_context.anchor_source_id,
        "direct_child_anchor_labels": (
            task_context.child_anchor_labels
        ),
        "direct_child_anchor_source_ids": (
            task_context.child_anchor_source_ids
        ),
        "source_cards": [item.prompt_payload() for item in cards],
    }


def _build_region_planner_task(
    source: SourceObservationIR,
    inventory: SourceInventory,
    context: ExplicitRegionDecisionContext,
    *,
    owner_id: str,
    run_id: str,
    max_cards_per_task: int,
    max_output_tokens: int,
) -> RegionPlannerTask:
    cards = _cards_for_context(
        source,
        inventory,
        context,
        max_cards_per_task=max_cards_per_task,
    )
    task_key = _planner_task_key(context)
    prompt_payload = _planner_prompt_payload(context, cards)
    envelope = TaskEnvelope(
        artifact_version="1.0.0",
        source_ids=tuple(item.source_id for item in cards),
        role_policy=context.planner_role,
        budget_slice=TaskBudgetSlice(
            max_wall_seconds=120,
            max_calls=1,
            max_cost_microunits=0,
        ),
        output_schema=REGION_PLANNER_PROPOSAL_SCHEMA_ID,
        expected_artifact_version="1.0.0",
        idempotency_key=payload_digest(
            {
                "prompt_payload": prompt_payload,
                "prompt_version": MODEL_REGION_PLANNER_PROMPT_VERSION,
                "role": context.planner_role.value,
                "schema_id": REGION_PLANNER_PROPOSAL_SCHEMA_ID,
            }
        ),
    )
    user_prompt = canonical_json_bytes(
        {
            "region_context": prompt_payload,
            "task_envelope": envelope,
        }
    ).decode("utf-8")
    prompt_digest = payload_digest(
        {
            "system_prompt": _PLANNER_SYSTEM_PROMPT,
            "user_prompt": user_prompt,
        }
    )
    return RegionPlannerTask(
        task_key=task_key,
        context=context,
        envelope=envelope,
        call=ModelCall(
            owner_id=owner_id,
            run_id=run_id,
            stage_key=task_key,
            role=context.planner_role,
            system_prompt=_PLANNER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_output_tokens=max_output_tokens,
            random_seed=0,
        ),
        cards=cards,
        prompt_digest=prompt_digest,
    )


def prepare_region_planner_tasks(
    source: SourceObservationIR,
    inventory: SourceInventory,
    *,
    owner_id: str,
    run_id: str,
    max_cards_per_task: int = 128,
    max_output_tokens: int = 4096,
) -> tuple[RegionPlannerTask, ...]:
    return tuple(
        _build_region_planner_task(
            source,
            inventory,
            context,
            owner_id=owner_id,
            run_id=run_id,
            max_cards_per_task=max_cards_per_task,
            max_output_tokens=max_output_tokens,
        )
        for context in enumerate_explicit_region_decision_contexts(
            source,
            inventory,
        )
    )


def prepare_region_verifier_task(
    planner_task: RegionPlannerTask,
    proposal: RegionPlannerProposal,
    *,
    max_output_tokens: int = 4096,
) -> RegionVerifierTask:
    task_key = _verifier_task_key(planner_task.context)
    prompt_payload = {
        "planner_proposal": proposal,
        "region_context": _planner_prompt_payload(
            planner_task.context,
            planner_task.cards,
        ),
    }
    envelope = TaskEnvelope(
        artifact_version="1.0.0",
        source_ids=planner_task.envelope.source_ids,
        role_policy=RuntimeRole.REGION_DECISION_VERIFIER,
        budget_slice=TaskBudgetSlice(
            max_wall_seconds=120,
            max_calls=1,
            max_cost_microunits=0,
        ),
        output_schema=REGION_DECISION_VERIFICATION_SCHEMA_ID,
        expected_artifact_version="1.0.0",
        idempotency_key=payload_digest(
            {
                "prompt_payload": prompt_payload,
                "prompt_version": MODEL_REGION_VERIFIER_PROMPT_VERSION,
                "schema_id": REGION_DECISION_VERIFICATION_SCHEMA_ID,
            }
        ),
    )
    user_prompt = canonical_json_bytes(
        {
            **prompt_payload,
            "task_envelope": envelope,
        }
    ).decode("utf-8")
    prompt_digest = payload_digest(
        {
            "system_prompt": _VERIFIER_SYSTEM_PROMPT,
            "user_prompt": user_prompt,
        }
    )
    return RegionVerifierTask(
        task_key=task_key,
        planner_task=planner_task,
        proposal=proposal,
        envelope=envelope,
        call=ModelCall(
            owner_id=planner_task.call.owner_id,
            run_id=planner_task.call.run_id,
            stage_key=task_key,
            role=RuntimeRole.REGION_DECISION_VERIFIER,
            system_prompt=_VERIFIER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_output_tokens=max_output_tokens,
            random_seed=0,
        ),
        prompt_digest=prompt_digest,
    )


def _slot_for_task_key(
    task_key: str,
    *,
    global_planner_slot: ModelSlot,
    recursive_planner_slot: ModelSlot,
    verifier_slot: ModelSlot,
) -> tuple[ModelSlot, RuntimeRole]:
    if task_key.startswith(_GLOBAL_TASK_PREFIX):
        return global_planner_slot, RuntimeRole.GLOBAL_STRUCTURE_PLANNER
    if task_key.startswith(_RECURSIVE_TASK_PREFIX):
        return (
            recursive_planner_slot,
            RuntimeRole.RECURSIVE_REGION_PLANNER,
        )
    if task_key.startswith(_VERIFIER_TASK_PREFIX):
        return verifier_slot, RuntimeRole.REGION_DECISION_VERIFIER
    raise ValueError(f"unknown recorded region task key {task_key!r}")


class RecordedRegionDecisionProvider:
    def __init__(
        self,
        *,
        stage: "RecordedRegionModelStage",
        source: SourceObservationIR,
        inventory: SourceInventory,
        owner_id: str,
        run_id: str,
        allowed_task_keys: frozenset[str],
    ):
        self.stage = stage
        self.source = source
        self.inventory = inventory
        self.owner_id = owner_id
        self.run_id = run_id
        self.allowed_task_keys = allowed_task_keys
        self.used_task_keys: set[str] = set()

    @property
    def stage_policy_digest(self) -> str:
        return self.stage.execution_policy_digest(owner_id=self.owner_id)

    def _sequence(self, task_key: str) -> tuple[str, ...]:
        if task_key not in self.allowed_task_keys:
            raise ModelRegionStageError(
                "recorded region task is outside explicit contexts"
            )
        try:
            sequence = self.stage.replay_sequences[task_key]
        except KeyError as exc:
            raise ModelRegionStageError(
                f"recorded region sequence is missing for {task_key}"
            ) from exc
        self.used_task_keys.add(task_key)
        return sequence

    @staticmethod
    def _assert_result_slot(
        *,
        result,
        slot: ModelSlot,
        task_key: str,
    ) -> None:
        if (
            result.provider != slot.provider
            or result.model_revision != slot.model_revision
        ):
            raise ModelRegionStageError(
                f"recorded region result for {task_key} is outside "
                "the declared model slot"
            )
        if result.used_fallback:
            raise ModelRegionStageError(
                "recorded region fallback is outside the declared slot"
            )

    @staticmethod
    def _validate_proposal(
        task: RegionPlannerTask,
        proposal: RegionPlannerProposal,
    ) -> None:
        context = task.context
        if proposal.anchor_source_id != context.anchor_source_id:
            raise ModelRegionStageError(
                "region proposal references another anchor"
            )
        if proposal.anchor_quote != context.anchor_label:
            raise ModelRegionStageError(
                "region proposal anchor quote is not exact"
            )
        if proposal.action is RegionProposalAction.SPLIT:
            if (
                proposal.child_anchor_source_ids
                != context.child_anchor_source_ids
            ):
                raise ModelRegionStageError(
                    "region proposal must preserve all direct child anchors "
                    "in source order"
                )
        elif proposal.action is RegionProposalAction.STOP:
            if context.child_anchor_source_ids:
                raise ModelRegionStageError(
                    "region with direct child anchors cannot STOP"
                )

    @staticmethod
    def _validate_verification(
        task: RegionVerifierTask,
        verification: RegionDecisionVerification,
    ) -> None:
        proposal = task.proposal
        context = task.planner_task.context
        if (
            verification.anchor_source_id
            != proposal.anchor_source_id
            or verification.action is not proposal.action
        ):
            raise ModelRegionStageError(
                "region verification does not match planner proposal"
            )
        card_ids = {
            item.source_id for item in task.planner_task.cards
        }
        unknown = set(verification.supporting_source_ids) - card_ids
        if unknown:
            raise ModelRegionStageError(
                "region verification references unknown source IDs: "
                + ", ".join(sorted(unknown))
            )
        if verification.verdict is RegionVerificationVerdict.ACCEPT:
            required = {
                context.anchor_source_id,
                *context.child_anchor_source_ids,
            }
            missing = required - set(
                verification.supporting_source_ids
            )
            if missing:
                raise ModelRegionStageError(
                    "accepted region verification omitted explicit anchors: "
                    + ", ".join(sorted(missing))
                )

    def decide(
        self,
        context: ExplicitRegionDecisionContext,
    ) -> RegionSemanticDecision:
        planner_task = _build_region_planner_task(
            self.source,
            self.inventory,
            context,
            owner_id=self.owner_id,
            run_id=self.run_id,
            max_cards_per_task=self.stage.max_cards_per_task,
            max_output_tokens=self.stage.max_output_tokens,
        )
        planner_slot = (
            self.stage.global_planner_slot
            if context.planner_role
            is RuntimeRole.GLOBAL_STRUCTURE_PLANNER
            else self.stage.recursive_planner_slot
        )
        planner_result = self.stage.adapter.replay_sequence(
            planner_task.call,
            RegionPlannerProposal,
            self._sequence(planner_task.task_key),
        )
        self._assert_result_slot(
            result=planner_result,
            slot=planner_slot,
            task_key=planner_task.task_key,
        )
        proposal = planner_result.value
        self._validate_proposal(planner_task, proposal)
        planner_producer = ArtifactProducerRef(
            producer_id=(
                "vnext-recorded-global-region-planner"
                if context.planner_role
                is RuntimeRole.GLOBAL_STRUCTURE_PLANNER
                else "vnext-recorded-recursive-region-planner"
            ),
            producer_version=MODEL_REGION_STAGE_VERSION,
            role=context.planner_role,
            model_revision=planner_result.model_revision,
            prompt_digest=planner_task.prompt_digest,
        )
        if proposal.action is RegionProposalAction.UNRESOLVED:
            return RegionSemanticDecision(
                proposal=proposal,
                verification=None,
                planner_producer=planner_producer,
                verifier_producer=None,
                interaction_ids=planner_result.interaction_ids,
                repaired_decisions=int(planner_result.repaired),
                providers=(planner_result.provider,),
            )

        verifier_task = prepare_region_verifier_task(
            planner_task,
            proposal,
            max_output_tokens=self.stage.max_output_tokens,
        )
        verifier_result = self.stage.adapter.replay_sequence(
            verifier_task.call,
            RegionDecisionVerification,
            self._sequence(verifier_task.task_key),
        )
        self._assert_result_slot(
            result=verifier_result,
            slot=self.stage.verifier_slot,
            task_key=verifier_task.task_key,
        )
        verification = verifier_result.value
        self._validate_verification(verifier_task, verification)
        verifier_producer = ArtifactProducerRef(
            producer_id="vnext-recorded-region-decision-verifier",
            producer_version=MODEL_REGION_STAGE_VERSION,
            role=RuntimeRole.REGION_DECISION_VERIFIER,
            model_revision=verifier_result.model_revision,
            prompt_digest=verifier_task.prompt_digest,
        )
        return RegionSemanticDecision(
            proposal=proposal,
            verification=verification,
            planner_producer=planner_producer,
            verifier_producer=verifier_producer,
            interaction_ids=(
                *planner_result.interaction_ids,
                *verifier_result.interaction_ids,
            ),
            repaired_decisions=(
                int(planner_result.repaired)
                + int(verifier_result.repaired)
            ),
            providers=(
                planner_result.provider,
                verifier_result.provider,
            ),
        )

    def finish(self) -> None:
        supplied = set(self.stage.replay_sequences)
        if self.used_task_keys != supplied:
            missing = supplied - self.used_task_keys
            raise ModelRegionStageError(
                "recorded region sequences contain unused tasks: "
                + ", ".join(sorted(missing))
            )


class RecordedRegionModelStage:
    def __init__(
        self,
        *,
        adapter: StructuredModelAdapter,
        global_planner_slot: ModelSlot,
        recursive_planner_slot: ModelSlot,
        verifier_slot: ModelSlot,
        replay_sequences: Mapping[str, Sequence[str]],
        max_cards_per_task: int = 128,
        max_output_tokens: int = 4096,
    ):
        expected_slots = (
            (global_planner_slot, "global_structure_planner"),
            (recursive_planner_slot, "recursive_region_planner"),
            (verifier_slot, "region_decision_verifier"),
        )
        for slot, expected_name in expected_slots:
            if slot.slot != expected_name:
                raise ValueError(
                    f"recorded region stage requires {expected_name} slot"
                )
            if not slot.structured_output:
                raise ValueError(
                    "recorded region slots require structured output"
                )
            if not any(
                endpoint.provider == slot.provider
                and endpoint.model_revision == slot.model_revision
                for endpoint in adapter.endpoints
            ):
                raise ValueError(
                    f"{expected_name} slot does not match adapter endpoint"
                )
        require_independent_pair(
            global_planner_slot,
            verifier_slot,
            require_calibrated=False,
        )
        require_independent_pair(
            recursive_planner_slot,
            verifier_slot,
            require_calibrated=False,
        )
        if adapter.replay_store is None:
            raise ValueError(
                "recorded region stage requires a replay store"
            )
        if max_cards_per_task < 1:
            raise ValueError("max_cards_per_task must be positive")
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        normalized_sequences = {
            str(key): tuple(value)
            for key, value in replay_sequences.items()
        }
        if any(not sequence for sequence in normalized_sequences.values()):
            raise ValueError(
                "recorded region task sequences must not be empty"
            )
        all_ids = [
            interaction_id
            for sequence in normalized_sequences.values()
            for interaction_id in sequence
        ]
        if len(all_ids) != len(set(all_ids)):
            raise ValueError(
                "recorded interactions cannot be reused across region tasks"
            )
        for task_key in normalized_sequences:
            _slot_for_task_key(
                task_key,
                global_planner_slot=global_planner_slot,
                recursive_planner_slot=recursive_planner_slot,
                verifier_slot=verifier_slot,
            )
        self.adapter = adapter
        self.global_planner_slot = global_planner_slot
        self.recursive_planner_slot = recursive_planner_slot
        self.verifier_slot = verifier_slot
        self.replay_sequences = normalized_sequences
        self.max_cards_per_task = max_cards_per_task
        self.max_output_tokens = max_output_tokens

    @property
    def portfolio(self) -> ModelPortfolioManifest:
        return ModelPortfolioManifest(
            slots=(
                self.global_planner_slot,
                self.recursive_planner_slot,
                self.verifier_slot,
            )
        )

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
                "planner_prompt_version": (
                    MODEL_REGION_PLANNER_PROMPT_VERSION
                ),
                "planner_schema": RegionPlannerProposal.model_json_schema(
                    mode="validation"
                ),
                "slots": self.portfolio,
                "verifier_prompt_version": (
                    MODEL_REGION_VERIFIER_PROMPT_VERSION
                ),
                "verifier_schema": (
                    RegionDecisionVerification.model_json_schema(
                        mode="validation"
                    )
                ),
            }
        )

    def execution_policy_digest(self, *, owner_id: str) -> str:
        assert self.adapter.replay_store is not None
        snapshots: list[dict[str, object]] = []
        for task_key, sequence in sorted(self.replay_sequences.items()):
            slot, role = _slot_for_task_key(
                task_key,
                global_planner_slot=self.global_planner_slot,
                recursive_planner_slot=self.recursive_planner_slot,
                verifier_slot=self.verifier_slot,
            )
            interactions = []
            for interaction_id in sequence:
                recorded = self.adapter.replay_store.load(
                    owner_id=owner_id,
                    interaction_id=interaction_id,
                )
                manifest = recorded.manifest
                if (
                    manifest.stage_key != task_key
                    or manifest.role is not role
                    or manifest.provider != slot.provider
                    or manifest.model_revision != slot.model_revision
                ):
                    raise ValueError(
                        "recorded region interaction is outside its "
                        "declared task slot"
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

    def bind(
        self,
        source: SourceObservationIR,
        inventory: SourceInventory,
        *,
        owner_id: str,
        run_id: str,
    ) -> RecordedRegionDecisionProvider:
        tasks = prepare_region_planner_tasks(
            source,
            inventory,
            owner_id=owner_id,
            run_id=run_id,
            max_cards_per_task=self.max_cards_per_task,
            max_output_tokens=self.max_output_tokens,
        )
        allowed = {
            key
            for task in tasks
            for key in (
                task.task_key,
                _verifier_task_key(task.context),
            )
        }
        extra = set(self.replay_sequences) - allowed
        if extra:
            raise ModelRegionStageError(
                "recorded region sequences target unknown explicit contexts: "
                + ", ".join(sorted(extra))
            )
        return RecordedRegionDecisionProvider(
            stage=self,
            source=source,
            inventory=inventory,
            owner_id=owner_id,
            run_id=run_id,
            allowed_task_keys=frozenset(allowed),
        )
