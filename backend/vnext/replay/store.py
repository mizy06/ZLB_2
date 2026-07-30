from __future__ import annotations

import hashlib
import json
import os
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.vnext.artifacts.canonical import (
    canonical_json_bytes,
    payload_digest,
)
from backend.vnext.artifacts.local_store import LocalArtifactStore
from backend.vnext.contracts.common import (
    ArtifactProducerRef,
    ArtifactRef,
    RuntimeRole,
    StringValue,
)
from backend.vnext.contracts.evidence import EvidenceNamespace, EvidenceRef
from backend.vnext.contracts.graph import CanonicalExplicitGraph
from backend.vnext.contracts.integrations import RecordedInteraction
from backend.vnext.contracts.projection import (
    DiagnosticProjection,
    ProjectionPurpose,
)
from backend.vnext.projection import build_diagnostic_projection


_SECRET_METADATA_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "credential",
        "password",
        "secret",
        "token",
    }
)


@dataclass(frozen=True, slots=True)
class ReplayedInteraction:
    manifest: RecordedInteraction
    request: Any
    response: Any
    tool_results: tuple[Any, ...]


class RecordedReplayStore:
    """Immutable local snapshots for no-network recorded response replay."""

    def __init__(self, root: Path):
        self.root = root

    def record(
        self,
        *,
        owner_id: str,
        run_id: str,
        stage_key: str,
        role: RuntimeRole,
        provider: str,
        model_revision: str,
        request: Any,
        response: Any,
        tool_results: tuple[Any, ...] = (),
        provider_metadata: Mapping[str, Any] | None = None,
    ) -> RecordedInteraction:
        metadata = dict(provider_metadata or {})
        forbidden = {
            key
            for key in metadata
            if key.casefold() in _SECRET_METADATA_KEYS
        }
        if forbidden:
            raise ValueError(
                "provider metadata contains secret-like keys: "
                + ", ".join(sorted(forbidden))
            )
        interaction_id = "interaction_" + secrets.token_hex(16)
        request_bytes = canonical_json_bytes(request)
        response_bytes = canonical_json_bytes(response)
        tool_bytes = tuple(
            canonical_json_bytes(result) for result in tool_results
        )
        request_ref = EvidenceRef(
            namespace=EvidenceNamespace.SYSTEM,
            ref_id=f"sys:replay:{interaction_id}:request",
            content_digest=payload_digest(request),
        )
        response_ref = EvidenceRef(
            namespace=EvidenceNamespace.SYSTEM,
            ref_id=f"sys:replay:{interaction_id}:response",
            content_digest=payload_digest(response),
        )
        tool_refs = tuple(
            EvidenceRef(
                namespace=EvidenceNamespace.SYSTEM,
                ref_id=f"sys:replay:{interaction_id}:tool:{index}",
                content_digest=payload_digest(result),
            )
            for index, result in enumerate(tool_results)
        )
        manifest = RecordedInteraction(
            interaction_id=interaction_id,
            run_id=run_id,
            owner_id=owner_id,
            stage_key=stage_key,
            role=role,
            provider=provider,
            model_revision=model_revision,
            request_ref=request_ref,
            response_ref=response_ref,
            tool_result_refs=tool_refs,
            request_digest=payload_digest(request),
            response_digest=payload_digest(response),
            tool_result_digests=tuple(
                payload_digest(result) for result in tool_results
            ),
            provider_metadata=tuple(
                StringValue(key=str(key), value=str(value))
                for key, value in sorted(metadata.items())
            ),
            created_at=datetime.now(UTC),
        )
        interactions_root = self._interactions_root(owner_id)
        interactions_root.mkdir(parents=True, exist_ok=True)
        target = interactions_root / interaction_id
        pending = interactions_root / (
            f".pending-{interaction_id}-{secrets.token_hex(8)}"
        )
        pending.mkdir(exist_ok=False)
        try:
            self._write_once(pending / "request.jcs.json", request_bytes)
            self._write_once(pending / "response.jcs.json", response_bytes)
            self._write_once(
                pending / "tool-results.jcs.json",
                canonical_json_bytes(list(tool_results)),
            )
            self._write_once(
                pending / "manifest.jcs.json",
                canonical_json_bytes(manifest),
            )
            pending.rename(target)
            self._fsync_directory(interactions_root)
        except Exception:
            for child in pending.iterdir() if pending.exists() else ():
                child.unlink(missing_ok=True)
            if pending.exists():
                pending.rmdir()
            raise
        return manifest

    def load(
        self,
        *,
        owner_id: str,
        interaction_id: str,
    ) -> ReplayedInteraction:
        root = self._interactions_root(owner_id) / interaction_id
        manifest = RecordedInteraction.model_validate_json(
            (root / "manifest.jcs.json").read_bytes()
        )
        if manifest.owner_id != owner_id:
            raise PermissionError("recorded interaction owner mismatch")
        request = json.loads(
            (root / "request.jcs.json").read_text(encoding="utf-8")
        )
        response = json.loads(
            (root / "response.jcs.json").read_text(encoding="utf-8")
        )
        tool_results = tuple(
            json.loads(
                (root / "tool-results.jcs.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        if payload_digest(request) != manifest.request_digest:
            raise ValueError("recorded request digest mismatch")
        if payload_digest(response) != manifest.response_digest:
            raise ValueError("recorded response digest mismatch")
        if tuple(payload_digest(item) for item in tool_results) != (
            manifest.tool_result_digests
        ):
            raise ValueError("recorded tool result digest mismatch")
        return ReplayedInteraction(
            manifest=manifest,
            request=request,
            response=response,
            tool_results=tool_results,
        )

    def replay(
        self,
        *,
        owner_id: str,
        interaction_id: str,
        expected_request: Any,
    ) -> ReplayedInteraction:
        recorded = self.load(
            owner_id=owner_id,
            interaction_id=interaction_id,
        )
        if payload_digest(expected_request) != (
            recorded.manifest.request_digest
        ):
            raise ValueError(
                "recorded response replay request does not match snapshot"
            )
        return recorded

    def _interactions_root(self, owner_id: str) -> Path:
        owner_scope = hashlib.sha256(
            ("zlb-vnext-replay-owner-v1\0" + owner_id).encode("utf-8")
        ).hexdigest()
        return self.root / "owners" / owner_scope / "interactions"

    @staticmethod
    def _write_once(path: Path, content: bytes) -> None:
        with path.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def deterministic_replay_projection(
    *,
    owner_id: str,
    graph_ref: ArtifactRef,
    artifact_store: LocalArtifactStore,
    purpose: ProjectionPurpose = ProjectionPurpose.DIAGNOSTIC,
    medium: str = "json",
    node_budget: int = 48,
) -> tuple[DiagnosticProjection, ArtifactRef]:
    stored_graph = artifact_store.get(
        owner_id=owner_id,
        artifact_id=graph_ref.artifact_id,
    )
    if not isinstance(stored_graph.payload, CanonicalExplicitGraph):
        raise TypeError("deterministic replay input is not a canonical graph")
    projection = build_diagnostic_projection(
        stored_graph.payload,
        canonical_graph_ref=graph_ref,
        purpose=purpose,
        medium=medium,
        node_budget=node_budget,
    )
    envelope = artifact_store.put(
        owner_id=owner_id,
        role=RuntimeRole.PROJECTION_PLANNER,
        payload=projection,
        producer=ArtifactProducerRef(
            producer_id="vnext-deterministic-replay-projection",
            producer_version="1.0.0",
            role=RuntimeRole.PROJECTION_PLANNER,
        ),
        input_refs=(graph_ref,),
    )
    return projection, artifact_store.ref(envelope)


def migration_replay(
    payload: Any,
    *,
    upcaster: Callable[[Any], Any],
) -> Any:
    """Apply a pure upcaster to a detached copy of an old payload."""

    detached = json.loads(canonical_json_bytes(payload))
    migrated = upcaster(detached)
    canonical_json_bytes(migrated)
    return migrated
