from __future__ import annotations

import asyncio
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from backend.vnext.artifacts.local_store import LocalArtifactStore
from backend.vnext.contracts.control import RunManifest
from backend.vnext.orchestration.control_store import SQLiteControlStore
from backend.vnext.orchestration.durable_pipeline import (
    run_durable_shadow_pipeline,
)


OwnerHeader = Annotated[
    str,
    StringConstraints(min_length=1, max_length=256),
]
ArtifactIdPath = Annotated[
    str,
    StringConstraints(pattern=r"^art_[0-9a-f]{32}$"),
]
RunIdPath = Annotated[
    str,
    StringConstraints(pattern=r"^run_[0-9a-f]{32}$"),
]
_ALLOWED_SUFFIXES = frozenset(
    {".pdf", ".pptx", ".docx", ".txt", ".md", ".markdown"}
)


@dataclass(frozen=True, slots=True)
class ShadowAPISettings:
    enabled: bool
    service_token: str = field(repr=False)
    ingest_root: Path
    artifact_root: Path
    control_db: Path
    worker_id: str = "vnext-shadow-api-worker"
    max_source_bytes: int = 100 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.enabled and not self.service_token:
            raise ValueError(
                "enabled vNext shadow API requires a service token"
            )
        if not self.worker_id.strip():
            raise ValueError("shadow API worker_id must not be empty")
        if self.max_source_bytes < 1:
            raise ValueError("shadow API max_source_bytes must be positive")

    @classmethod
    def from_env(cls) -> "ShadowAPISettings":
        root = Path(
            os.getenv("VNEXT_SHADOW_ROOT", ".data/vnext-shadow")
        )
        return cls(
            enabled=os.getenv("VNEXT_SHADOW_API_ENABLED", "") == "1",
            service_token=os.getenv("VNEXT_SHADOW_API_TOKEN", ""),
            ingest_root=Path(
                os.getenv(
                    "VNEXT_SHADOW_INGEST_ROOT",
                    str(root / "ingest"),
                )
            ),
            artifact_root=Path(
                os.getenv(
                    "VNEXT_SHADOW_ARTIFACT_ROOT",
                    str(root / "artifacts"),
                )
            ),
            control_db=Path(
                os.getenv(
                    "VNEXT_SHADOW_CONTROL_DB",
                    str(root / "control.sqlite3"),
                )
            ),
            worker_id=os.getenv(
                "VNEXT_SHADOW_WORKER_ID",
                "vnext-shadow-api-worker",
            ),
            max_source_bytes=int(
                os.getenv(
                    "VNEXT_SHADOW_MAX_SOURCE_BYTES",
                    str(100 * 1024 * 1024),
                )
            ),
        )


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ShadowRunRequest(_StrictModel):
    source_path: Annotated[
        str,
        StringConstraints(min_length=1, max_length=1024),
    ]
    run_id: RunIdPath | None = None


class ShadowRunResponse(_StrictModel):
    run_manifest: RunManifest
    projection_artifact_id: ArtifactIdPath
    canonical_graph_artifact_id: ArtifactIdPath
    reused_stages: tuple[str, ...] = ()


class StoredArtifactResponse(_StrictModel):
    envelope: dict[str, Any]
    payload: dict[str, Any]


def create_shadow_app(settings: ShadowAPISettings) -> FastAPI:
    application = FastAPI(
        title="ZLB vNext Shadow API",
        version="0.1.0",
        description=(
            "Default-locked clean-room shadow service. Publication is "
            "intentionally unavailable."
        ),
    )
    service_lock = Lock()
    artifact_store: LocalArtifactStore | None = None
    control_store: SQLiteControlStore | None = None

    def services() -> tuple[LocalArtifactStore, SQLiteControlStore]:
        nonlocal artifact_store, control_store
        with service_lock:
            if artifact_store is None:
                artifact_store = LocalArtifactStore(settings.artifact_root)
            if control_store is None:
                control_store = SQLiteControlStore(settings.control_db)
        return artifact_store, control_store

    def owner_context(
        authorization: Annotated[str | None, Header()] = None,
        x_vnext_owner: Annotated[str | None, Header()] = None,
    ) -> str:
        if not settings.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="vnext_shadow_api_locked",
            )
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing_bearer_token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = authorization.removeprefix("Bearer ")
        if not secrets.compare_digest(token, settings.service_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_bearer_token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if (
            x_vnext_owner is None
            or not x_vnext_owner.strip()
            or len(x_vnext_owner) > 256
            or any(char in x_vnext_owner for char in "\r\n\0")
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_owner_header",
            )
        return x_vnext_owner.strip()

    @application.get("/healthz")
    def health() -> dict[str, Any]:
        return {
            "service": "zlb-vnext-shadow",
            "enabled": settings.enabled,
            "publication": "disabled",
        }

    @application.post(
        "/v1/shadow/runs",
        response_model=ShadowRunResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_run(
        request: ShadowRunRequest,
        owner_id: str = Depends(owner_context),
    ) -> ShadowRunResponse:
        source_path = _resolve_source_path(settings, request.source_path)
        artifact_store, control_store = services()
        result = await asyncio.to_thread(
            run_durable_shadow_pipeline,
            source_path,
            owner_id=owner_id,
            artifact_store=artifact_store,
            control_store=control_store,
            worker_id=settings.worker_id,
            run_id=request.run_id,
        )
        return ShadowRunResponse(
            run_manifest=result.run_manifest,
            projection_artifact_id=(
                result.shadow.projection_envelope.artifact_id
            ),
            canonical_graph_artifact_id=(
                result.shadow.canonical_graph_envelope.artifact_id
            ),
            reused_stages=result.reused_stages,
        )

    @application.get(
        "/v1/shadow/runs/{run_id}",
        response_model=RunManifest,
    )
    def get_run(
        run_id: RunIdPath,
        owner_id: str = Depends(owner_context),
    ) -> RunManifest:
        _, control_store = services()
        manifest = control_store.load_run(
            run_id,
            owner_id=owner_id,
        )
        if manifest is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="run_not_found",
            )
        return manifest

    @application.get(
        "/v1/shadow/artifacts/{artifact_id}",
        response_model=StoredArtifactResponse,
    )
    def get_artifact(
        artifact_id: ArtifactIdPath,
        owner_id: str = Depends(owner_context),
    ) -> StoredArtifactResponse:
        artifact_store, _ = services()
        try:
            stored = artifact_store.get(
                owner_id=owner_id,
                artifact_id=artifact_id,
            )
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="artifact_not_found",
            ) from exc
        return StoredArtifactResponse(
            envelope=stored.envelope.model_dump(mode="json"),
            payload=stored.payload.model_dump(mode="json"),
        )

    return application


def _resolve_source_path(
    settings: ShadowAPISettings,
    source_path: str,
) -> Path:
    relative = Path(source_path)
    if relative.is_absolute():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="absolute_source_path_forbidden",
        )
    ingest_root = settings.ingest_root.resolve()
    try:
        candidate = (ingest_root / relative).resolve(strict=True)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="source_not_found",
        ) from exc
    try:
        candidate.relative_to(ingest_root)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source_path_outside_ingest_root",
        ) from exc
    if not candidate.is_file():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source_is_not_a_regular_file",
        )
    if candidate.suffix.casefold() not in _ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="unsupported_source_type",
        )
    if candidate.stat().st_size > settings.max_source_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="source_exceeds_shadow_limit",
        )
    return candidate


app = create_shadow_app(ShadowAPISettings.from_env())
