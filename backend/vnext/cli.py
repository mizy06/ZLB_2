from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.vnext.artifacts.local_store import LocalArtifactStore
from backend.vnext.claims import RecordedClaimModelStage
from backend.vnext.contracts.common import ArtifactProducerRef, RuntimeRole
from backend.vnext.contracts.control import (
    ModelPortfolioManifest,
    ModelSlot,
)
from backend.vnext.contracts.exporter import (
    DEFAULT_SCHEMA_DIR,
    write_schema_bundle,
)
from backend.vnext.contracts.graph import CanonicalExplicitGraph
from backend.vnext.contracts.projection import DiagnosticProjection
from backend.vnext.contracts.quality import (
    PilotDataset,
    PilotGateDecision,
)
from backend.vnext.contracts.registry import CONTRACT_BY_NAME
from backend.vnext.orchestration.shadow_pipeline import (
    run_shadow_pipeline,
)
from backend.vnext.orchestration.control_store import SQLiteControlStore
from backend.vnext.orchestration.durable_pipeline import (
    run_durable_shadow_pipeline,
)
from backend.vnext.orchestration.source_shadow import run_source_shadow
from backend.vnext.model_runtime import (
    ProviderEndpoint,
    StructuredModelAdapter,
)
from backend.vnext.presentation import (
    PresentationRenderStore,
    build_projection_media_bundle,
)
from backend.vnext.quality import evaluate_pilot
from backend.vnext.regions import RecordedRegionModelStage
from backend.vnext.replay.store import RecordedReplayStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m backend.vnext.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    export = commands.add_parser("export-schemas")
    export.add_argument("--check", action="store_true")
    export.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_SCHEMA_DIR,
    )

    validate = commands.add_parser("validate")
    validate.add_argument(
        "--contract",
        choices=sorted(CONTRACT_BY_NAME),
        required=True,
    )
    validate.add_argument("--input", type=Path, required=True)

    store = commands.add_parser("shadow-store")
    store.add_argument(
        "--contract",
        choices=sorted(
            name
            for name, registration in CONTRACT_BY_NAME.items()
            if registration.artifact_type is not None
        ),
        required=True,
    )
    store.add_argument("--input", type=Path, required=True)
    store.add_argument("--owner", required=True)
    store.add_argument("--root", type=Path, required=True)
    store.add_argument(
        "--role",
        choices=[role.value for role in RuntimeRole],
        required=True,
    )
    store.add_argument("--producer", required=True)
    store.add_argument("--producer-version", required=True)

    source_shadow = commands.add_parser("source-shadow")
    source_shadow.add_argument("--input", type=Path, required=True)
    source_shadow.add_argument("--owner", required=True)
    source_shadow.add_argument("--root", type=Path, required=True)

    pipeline_shadow = commands.add_parser("pipeline-shadow")
    pipeline_shadow.add_argument("--input", type=Path, required=True)
    pipeline_shadow.add_argument("--owner", required=True)
    pipeline_shadow.add_argument("--root", type=Path, required=True)

    durable_shadow = commands.add_parser("durable-shadow")
    durable_shadow.add_argument("--input", type=Path, required=True)
    durable_shadow.add_argument("--owner", required=True)
    durable_shadow.add_argument("--root", type=Path, required=True)
    durable_shadow.add_argument("--control-db", type=Path, required=True)
    durable_shadow.add_argument("--run-id")
    durable_shadow.add_argument("--worker", default="cli-worker")

    recorded_claim_shadow = commands.add_parser(
        "recorded-claim-shadow"
    )
    recorded_claim_shadow.add_argument(
        "--input",
        type=Path,
        required=True,
    )
    recorded_claim_shadow.add_argument("--owner", required=True)
    recorded_claim_shadow.add_argument(
        "--root",
        type=Path,
        required=True,
    )
    recorded_claim_shadow.add_argument(
        "--control-db",
        type=Path,
        required=True,
    )
    recorded_claim_shadow.add_argument(
        "--replay-root",
        type=Path,
        required=True,
    )
    recorded_claim_shadow.add_argument(
        "--replay-map",
        type=Path,
        required=True,
    )
    recorded_claim_shadow.add_argument("--run-id", required=True)
    recorded_claim_shadow.add_argument(
        "--worker",
        default="cli-recorded-claim-worker",
    )
    recorded_claim_shadow.add_argument("--provider", required=True)
    recorded_claim_shadow.add_argument(
        "--model-revision",
        required=True,
    )
    recorded_claim_shadow.add_argument(
        "--model-family",
        required=True,
    )
    recorded_claim_shadow.add_argument(
        "--model-region",
        default="recorded",
    )
    recorded_claim_shadow.add_argument(
        "--context-limit",
        type=int,
        default=128000,
    )

    recorded_region_shadow = commands.add_parser(
        "recorded-region-shadow"
    )
    recorded_region_shadow.add_argument(
        "--input",
        type=Path,
        required=True,
    )
    recorded_region_shadow.add_argument("--owner", required=True)
    recorded_region_shadow.add_argument(
        "--root",
        type=Path,
        required=True,
    )
    recorded_region_shadow.add_argument(
        "--control-db",
        type=Path,
        required=True,
    )
    recorded_region_shadow.add_argument(
        "--replay-root",
        type=Path,
        required=True,
    )
    recorded_region_shadow.add_argument(
        "--replay-map",
        type=Path,
        required=True,
    )
    recorded_region_shadow.add_argument(
        "--portfolio",
        type=Path,
        required=True,
    )
    recorded_region_shadow.add_argument("--run-id", required=True)
    recorded_region_shadow.add_argument(
        "--worker",
        default="cli-recorded-region-worker",
    )

    pilot_evaluate = commands.add_parser("pilot-evaluate")
    pilot_evaluate.add_argument("--input", type=Path, required=True)

    render_shadow = commands.add_parser("render-shadow")
    render_shadow.add_argument("--owner", required=True)
    render_shadow.add_argument(
        "--artifact-root",
        type=Path,
        required=True,
    )
    render_shadow.add_argument(
        "--canonical-artifact",
        required=True,
    )
    render_shadow.add_argument(
        "--projection-artifact",
        required=True,
    )
    render_shadow.add_argument(
        "--output-root",
        type=Path,
        required=True,
    )
    render_shadow.add_argument("--font-path", type=Path)
    return parser


def _load_contract(name: str, path: Path):
    registration = CONTRACT_BY_NAME[name]
    return registration.model.model_validate_json(path.read_bytes())


def _load_replay_sequences(
    path: Path,
    *,
    stage_name: str,
) -> dict[str, tuple[str, ...]]:
    replay_payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(replay_payload, dict):
        raise ValueError(
            f"recorded {stage_name} replay map must be a JSON object"
        )
    replay_sequences: dict[str, tuple[str, ...]] = {}
    for task_key, interaction_ids in replay_payload.items():
        if not isinstance(task_key, str) or not isinstance(
            interaction_ids,
            list,
        ):
            raise ValueError(
                f"recorded {stage_name} replay map values must be arrays"
            )
        if not all(
            isinstance(interaction_id, str)
            for interaction_id in interaction_ids
        ):
            raise ValueError(
                f"recorded {stage_name} interaction IDs must be strings"
            )
        replay_sequences[task_key] = tuple(interaction_ids)
    return replay_sequences


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "export-schemas":
        changed = write_schema_bundle(args.output, check=args.check)
        if args.check and changed:
            print(json.dumps({"stale": list(changed)}, sort_keys=True))
            return 1
        print(json.dumps({"changed": list(changed)}, sort_keys=True))
        return 0
    if args.command == "validate":
        payload = _load_contract(args.contract, args.input)
        print(
            json.dumps(
                {
                    "contract": args.contract,
                    "schema_version": payload.schema_version,
                    "valid": True,
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "source-shadow":
        store = LocalArtifactStore(args.root)
        result = run_source_shadow(
            args.input,
            owner_id=args.owner,
            store=store,
        )
        print(
            json.dumps(
                {
                    "document_id": result.source_observation.document_id,
                    "inventory_id": result.source_inventory.inventory_id,
                    "pages": len(result.source_observation.pages),
                    "source_artifact": (
                        result.source_envelope.model_dump(mode="json")
                    ),
                    "inventory_artifact": (
                        result.inventory_envelope.model_dump(mode="json")
                    ),
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "pipeline-shadow":
        store = LocalArtifactStore(args.root)
        result = run_shadow_pipeline(
            args.input,
            owner_id=args.owner,
            store=store,
        )
        print(
            json.dumps(
                {
                    "canonical_graph_artifact_id": (
                        result.canonical_graph_envelope.artifact_id
                    ),
                    "document_id": (
                        result.source.source_observation.document_id
                    ),
                    "omitted_source_count": len(
                        result.omission_audit.omitted_source_ids
                    ),
                    "projection_artifact_id": (
                        result.projection_envelope.artifact_id
                    ),
                    "quality_status": (
                        result.projection.quality_status.value
                    ),
                    "replan_request_count": len(
                        result.replan_requests
                    ),
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "durable-shadow":
        result = run_durable_shadow_pipeline(
            args.input,
            owner_id=args.owner,
            artifact_store=LocalArtifactStore(args.root),
            control_store=SQLiteControlStore(args.control_db),
            worker_id=args.worker,
            run_id=args.run_id,
        )
        print(
            json.dumps(
                {
                    "execution_status": (
                        result.run_manifest.execution_status.value
                    ),
                    "projection_artifact_id": (
                        result.shadow.projection_envelope.artifact_id
                    ),
                    "publication_status": (
                        result.run_manifest.publication_status.value
                    ),
                    "quality_status": (
                        result.run_manifest.quality_status.value
                    ),
                    "reused_stages": list(result.reused_stages),
                    "run_id": result.run_manifest.run_id,
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "recorded-claim-shadow":
        replay_sequences = _load_replay_sequences(
            args.replay_map,
            stage_name="claim",
        )
        endpoint = ProviderEndpoint(
            provider=args.provider,
            base_url="https://recorded.invalid/v1",
            model_revision=args.model_revision,
            model_family=args.model_family,
        )
        claim_stage = RecordedClaimModelStage(
            adapter=StructuredModelAdapter(
                (endpoint,),
                replay_store=RecordedReplayStore(args.replay_root),
            ),
            model_slot=ModelSlot(
                slot="claim_extractor",
                provider=args.provider,
                model_revision=args.model_revision,
                model_family=args.model_family,
                independence_group=None,
                independence_calibrated=False,
                context_limit=args.context_limit,
                structured_output=True,
                region=args.model_region,
                price_input_microunits_per_million=0,
                price_output_microunits_per_million=0,
            ),
            replay_sequences=replay_sequences,
        )
        result = run_durable_shadow_pipeline(
            args.input,
            owner_id=args.owner,
            artifact_store=LocalArtifactStore(args.root),
            control_store=SQLiteControlStore(args.control_db),
            worker_id=args.worker,
            run_id=args.run_id,
            claim_model_stage=claim_stage,
        )
        print(
            json.dumps(
                {
                    "claim_ledger_artifact_id": (
                        result.shadow.claim_ledger_envelope.artifact_id
                    ),
                    "execution_status": (
                        result.run_manifest.execution_status.value
                    ),
                    "model_call_count": (
                        result.run_manifest.observed.model_call_count
                    ),
                    "no_egress": result.run_manifest.declared.no_egress,
                    "projection_artifact_id": (
                        result.shadow.projection_envelope.artifact_id
                    ),
                    "publication_status": (
                        result.run_manifest.publication_status.value
                    ),
                    "quality_status": (
                        result.run_manifest.quality_status.value
                    ),
                    "recorded_interaction_ids": list(
                        result.shadow.claim_ledger
                        .recorded_interaction_ids
                    ),
                    "replay_mode": (
                        result.run_manifest.observed.replay_mode.value
                    ),
                    "reused_stages": list(result.reused_stages),
                    "run_id": result.run_manifest.run_id,
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "recorded-region-shadow":
        replay_sequences = _load_replay_sequences(
            args.replay_map,
            stage_name="region",
        )
        portfolio = ModelPortfolioManifest.model_validate_json(
            args.portfolio.read_bytes()
        )
        slots = {slot.slot: slot for slot in portfolio.slots}
        required_slots = {
            "global_structure_planner",
            "recursive_region_planner",
            "region_decision_verifier",
        }
        if set(slots) != required_slots:
            raise ValueError(
                "recorded region portfolio must contain exactly: "
                + ", ".join(sorted(required_slots))
            )
        endpoints = tuple(
            ProviderEndpoint(
                provider=slot.provider,
                base_url="https://recorded.invalid/v1",
                model_revision=slot.model_revision,
                model_family=slot.model_family,
            )
            for slot in portfolio.slots
        )
        region_stage = RecordedRegionModelStage(
            adapter=StructuredModelAdapter(
                endpoints,
                replay_store=RecordedReplayStore(args.replay_root),
            ),
            global_planner_slot=slots["global_structure_planner"],
            recursive_planner_slot=slots[
                "recursive_region_planner"
            ],
            verifier_slot=slots["region_decision_verifier"],
            replay_sequences=replay_sequences,
        )
        result = run_durable_shadow_pipeline(
            args.input,
            owner_id=args.owner,
            artifact_store=LocalArtifactStore(args.root),
            control_store=SQLiteControlStore(args.control_db),
            worker_id=args.worker,
            run_id=args.run_id,
            region_model_stage=region_stage,
        )
        print(
            json.dumps(
                {
                    "execution_status": (
                        result.run_manifest.execution_status.value
                    ),
                    "model_call_count": (
                        result.run_manifest.observed.model_call_count
                    ),
                    "no_egress": result.run_manifest.declared.no_egress,
                    "projection_artifact_id": (
                        result.shadow.projection_envelope.artifact_id
                    ),
                    "publication_status": (
                        result.run_manifest.publication_status.value
                    ),
                    "quality_status": (
                        result.run_manifest.quality_status.value
                    ),
                    "recorded_interaction_ids": list(
                        result.shadow.planning.recorded_interaction_ids
                    ),
                    "replay_mode": (
                        result.run_manifest.observed.replay_mode.value
                    ),
                    "reused_stages": list(result.reused_stages),
                    "root_region_id": (
                        result.shadow.planning.root_region_id
                    ),
                    "run_id": result.run_manifest.run_id,
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "pilot-evaluate":
        dataset = PilotDataset.model_validate_json(
            args.input.read_bytes()
        )
        report = evaluate_pilot(dataset)
        print(
            json.dumps(
                report.model_dump(mode="json"),
                sort_keys=True,
            )
        )
        return {
            PilotGateDecision.PASS: 0,
            PilotGateDecision.BLOCK: 2,
            PilotGateDecision.INCOMPLETE: 3,
        }[report.gate_decision]
    if args.command == "render-shadow":
        artifact_store = LocalArtifactStore(args.artifact_root)
        stored_graph = artifact_store.get(
            owner_id=args.owner,
            artifact_id=args.canonical_artifact,
        )
        stored_projection = artifact_store.get(
            owner_id=args.owner,
            artifact_id=args.projection_artifact,
        )
        if not isinstance(
            stored_graph.payload,
            CanonicalExplicitGraph,
        ):
            raise TypeError(
                "canonical artifact is not CanonicalExplicitGraph"
            )
        if not isinstance(
            stored_projection.payload,
            DiagnosticProjection,
        ):
            raise TypeError(
                "projection artifact is not DiagnosticProjection"
            )
        media_bundle = build_projection_media_bundle(
            stored_graph.payload,
            stored_projection.payload,
            canonical_graph_ref=artifact_store.ref(
                stored_graph.envelope
            ),
            projection_ref=artifact_store.ref(
                stored_projection.envelope
            ),
        )
        render_store = PresentationRenderStore(args.output_root)
        rendered = render_store.render(
            stored_graph.payload,
            stored_projection.payload,
            media_bundle,
            owner_id=args.owner,
            font_path=args.font_path,
        )
        directory = render_store.directory(
            owner_id=args.owner,
            render_bundle_id=rendered.render_bundle_id,
        )
        print(
            json.dumps(
                {
                    "files": [
                        item.relative_path for item in rendered.files
                    ],
                    "publication_enabled": (
                        rendered.publication_enabled
                    ),
                    "render_bundle_id": rendered.render_bundle_id,
                    "render_directory": str(directory),
                    "semantic_fingerprint": (
                        rendered.semantic_fingerprint
                    ),
                },
                sort_keys=True,
            )
        )
        return 0
    payload = _load_contract(args.contract, args.input)
    store = LocalArtifactStore(args.root)
    envelope = store.put(
        owner_id=args.owner,
        role=RuntimeRole(args.role),
        payload=payload,
        producer=ArtifactProducerRef(
            producer_id=args.producer,
            producer_version=args.producer_version,
            role=RuntimeRole(args.role),
        ),
    )
    print(envelope.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
