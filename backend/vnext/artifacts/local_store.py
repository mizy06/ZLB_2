from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from backend.vnext.contracts.artifacts import ArtifactEnvelope
from backend.vnext.contracts.base import FrozenContract
from backend.vnext.contracts.common import (
    ArtifactId,
    ArtifactProducerRef,
    ArtifactRef,
    RuntimeRole,
)
from backend.vnext.contracts.evidence import EvidenceRef
from backend.vnext.contracts.registry import (
    CONTRACT_BY_ARTIFACT_TYPE,
    registration_for_model,
)
from backend.vnext.orchestration.permissions import assert_submission_allowed

from .canonical import (
    canonical_json_bytes,
    new_artifact_id,
    payload_digest,
)


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    envelope: ArtifactEnvelope
    payload: FrozenContract


class LocalArtifactStore:
    """Independent owner-scoped store for local shadow runs."""

    def __init__(self, root: Path):
        self.root = root

    def put(
        self,
        *,
        owner_id: str,
        role: RuntimeRole,
        payload: FrozenContract,
        producer: ArtifactProducerRef,
        input_refs: tuple[ArtifactRef, ...] = (),
        external_snapshot_refs: tuple[EvidenceRef, ...] = (),
        supersedes: ArtifactRef | None = None,
    ) -> ArtifactEnvelope:
        if producer.role is not role:
            raise ValueError(
                "artifact producer role must match the authorized writer"
            )
        artifact_type = assert_submission_allowed(role, payload)
        registration = registration_for_model(payload)
        artifact_id = new_artifact_id()
        digest = payload_digest(payload)
        envelope = ArtifactEnvelope(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            schema_id=registration.schema_id,
            payload_schema_version=registration.version,
            owner_id=owner_id,
            payload_digest=digest,
            producer=producer,
            input_refs=input_refs,
            external_snapshot_refs=external_snapshot_refs,
            created_at=datetime.now(UTC),
            supersedes=supersedes,
        )
        artifacts_root = self._artifacts_root(owner_id)
        artifacts_root.mkdir(parents=True, exist_ok=True)
        artifact_dir = artifacts_root / artifact_id
        pending_dir = artifacts_root / (
            f".pending-{artifact_id}-{secrets.token_hex(8)}"
        )
        pending_dir.mkdir(exist_ok=False)
        try:
            self._write_once(
                pending_dir / "payload.jcs.json",
                canonical_json_bytes(payload),
            )
            self._write_once(
                pending_dir / "envelope.jcs.json",
                canonical_json_bytes(envelope),
            )
            pending_dir.rename(artifact_dir)
            self._fsync_directory(artifacts_root)
        except Exception:
            for filename in ("payload.jcs.json", "envelope.jcs.json"):
                (pending_dir / filename).unlink(missing_ok=True)
            if pending_dir.exists():
                pending_dir.rmdir()
            raise
        return envelope

    def get(self, *, owner_id: str, artifact_id: ArtifactId) -> StoredArtifact:
        artifact_dir = self._artifact_dir(owner_id, artifact_id)
        envelope = ArtifactEnvelope.model_validate_json(
            (artifact_dir / "envelope.jcs.json").read_bytes()
        )
        if envelope.owner_id != owner_id:
            raise PermissionError("artifact owner mismatch")
        registration = CONTRACT_BY_ARTIFACT_TYPE.get(envelope.artifact_type)
        if registration is None or registration.model is ArtifactEnvelope:
            raise ValueError("unsupported stored payload contract")
        payload_bytes = (artifact_dir / "payload.jcs.json").read_bytes()
        payload = registration.model.model_validate_json(payload_bytes)
        if payload_digest(payload) != envelope.payload_digest:
            raise ValueError("stored artifact payload digest mismatch")
        return StoredArtifact(envelope=envelope, payload=payload)

    def ref(self, envelope: ArtifactEnvelope) -> ArtifactRef:
        return ArtifactRef(
            owner_id=envelope.owner_id,
            artifact_id=envelope.artifact_id,
            artifact_type=envelope.artifact_type,
            payload_digest=envelope.payload_digest,
        )

    def list_envelopes(
        self,
        *,
        owner_id: str,
    ) -> tuple[ArtifactEnvelope, ...]:
        artifacts_root = self._artifacts_root(owner_id)
        if not artifacts_root.is_dir():
            return ()
        envelopes: list[ArtifactEnvelope] = []
        for artifact_dir in sorted(artifacts_root.glob("art_*")):
            if not artifact_dir.is_dir():
                continue
            envelope = ArtifactEnvelope.model_validate_json(
                (artifact_dir / "envelope.jcs.json").read_bytes()
            )
            if envelope.owner_id != owner_id:
                raise PermissionError("artifact owner mismatch")
            envelopes.append(envelope)
        return tuple(envelopes)

    def exists_for_other_owner(
        self,
        *,
        owner_id: str,
        artifact_id: ArtifactId,
    ) -> bool:
        current_scope = self._artifacts_root(owner_id).parent.name
        owners_root = self.root / "owners"
        if not owners_root.is_dir():
            return False
        return any(
            owner_dir.name != current_scope
            and (owner_dir / "artifacts" / artifact_id).is_dir()
            for owner_dir in owners_root.iterdir()
            if owner_dir.is_dir()
        )

    def reconcile_pending(self, *, owner_id: str) -> tuple[str, ...]:
        artifacts_root = self._artifacts_root(owner_id)
        if not artifacts_root.is_dir():
            return ()
        removed: list[str] = []
        for pending_dir in artifacts_root.glob(".pending-art_*"):
            if not pending_dir.is_dir():
                continue
            children = {path.name for path in pending_dir.iterdir()}
            if not children <= {
                "payload.jcs.json",
                "envelope.jcs.json",
            }:
                continue
            for filename in children:
                (pending_dir / filename).unlink()
            pending_dir.rmdir()
            removed.append(pending_dir.name)
        if removed:
            self._fsync_directory(artifacts_root)
        return tuple(sorted(removed))

    def _artifact_dir(self, owner_id: str, artifact_id: str) -> Path:
        return self._artifacts_root(owner_id) / artifact_id

    def _artifacts_root(self, owner_id: str) -> Path:
        owner_scope = hashlib.sha256(
            ("zlb-vnext-owner-v1\0" + owner_id).encode("utf-8")
        ).hexdigest()
        return self.root / "owners" / owner_scope / "artifacts"

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
