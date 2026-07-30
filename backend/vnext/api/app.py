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
class PrincipalContext:
    subject: str
    tenant: str
    audience: str
    scopes: frozenset[str]
    owner_id: str


@dataclass(frozen=True, slots=True)
class ShadowAPISettings:
    enabled: bool
    service_token: str = field(repr=False)
    ingest_root: Path
    artifact_root: Path
    control_db: Path
    worker_id: str = "vnext-shadow-api-worker"
    max_source_bytes: int = 100 * 1024 * 1024
    principal_subject: str = "service:vnext-shadow"
    principal_tenant: str = "tenant-a"
    principal_owner_id: str = "owner-a"
    principal_audience: str = "zlb-vnext-shadow"
    principal_scopes: tuple[str, ...] = ("vnext:run", "vnext:read")
    required_audience: str = "zlb-vnext-shadow"

    def __post_init__(self) -> None:
        if self.enabled and not self.service_token:
            raise ValueError(
                "enabled vNext shadow API requires a service token"
            )
        if not self.worker_id.strip():
            raise ValueError("shadow API worker_id must not be empty")
        if self.max_source_bytes < 1:
            raise ValueError("shadow API max_source_bytes must be positive")
        principal_values = (
            self.principal_subject,
            self.principal_tenant,
            self.principal_owner_id,
            self.principal_audience,
            self.required_audience,
        )
        if any(not value.strip() for value in principal_values):
            raise ValueError("shadow API principal fields must not be empty")
        if not self.principal_scopes:
            raise ValueError("shadow API principal requires at least one scope")
        if any(not scope.strip() for scope in self.principal_scopes):
            raise ValueError("shadow API principal scopes must not be empty")

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
            principal_subject=os.getenv(
                "VNEXT_SHADOW_PRINCIPAL_SUBJECT",
                "service:vnext-shadow",
            ),
            principal_tenant=os.getenv(
                "VNEXT_SHADOW_PRINCIPAL_TENANT",
                "tenant-a",
            ),
            principal_owner_id=os.getenv(
                "VNEXT_SHADOW_PRINCIPAL_OWNER",
                "owner-a",
            ),
            principal_audience=os.getenv(
                "VNEXT_SHADOW_PRINCIPAL_AUDIENCE",
                "zlb-vnext-shadow",
            ),
            principal_scopes=tuple(
                scope.strip()
                for scope in os.getenv(
                    "VNEXT_SHADOW_PRINCIPAL_SCOPES",
                    "vnext:run,vnext:read",
                ).split(",")
                if scope.strip()
            ),
            required_audience=os.getenv(
                "VNEXT_SHADOW_REQUIRED_AUDIENCE",
                "zlb-vnext-shadow",
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
    application.state.security_events = []

    def services() -> tuple[LocalArtifactStore, SQLiteControlStore]:
        nonlocal artifact_store, control_store
        with service_lock:
            if artifact_store is None:
                artifact_store = LocalArtifactStore(settings.artifact_root)
            if control_store is None:
                control_store = SQLiteControlStore(settings.control_db)
        return artifact_store, control_store

    def principal_context(
        authorization: Annotated[str | None, Header()] = None,
        x_vnext_owner: Annotated[str | None, Header()] = None,
    ) -> PrincipalContext:
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
        principal = PrincipalContext(
            subject=settings.principal_subject,
            tenant=settings.principal_tenant,
            audience=settings.principal_audience,
            scopes=frozenset(settings.principal_scopes),
            owner_id=settings.principal_owner_id,
        )
        if principal.audience != settings.required_audience:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="principal_audience_forbidden",
            )
        if x_vnext_owner is not None:
            supplied_owner = x_vnext_owner.strip()
            if (
                not supplied_owner
                or len(supplied_owner) > 256
                or any(char in supplied_owner for char in "\r\n\0")
                or supplied_owner != principal.owner_id
            ):
                application.state.security_events.append(
                    {
                        "code": "owner_header_mismatch",
                        "subject": principal.subject,
                        "tenant": principal.tenant,
                    }
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="owner_header_not_authoritative",
                )
        return principal

    def run_principal(
        principal: PrincipalContext = Depends(principal_context),
    ) -> PrincipalContext:
        if "vnext:run" not in principal.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="principal_scope_forbidden",
            )
        return principal

    def read_principal(
        principal: PrincipalContext = Depends(principal_context),
    ) -> PrincipalContext:
        if "vnext:read" not in principal.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="principal_scope_forbidden",
            )
        return principal

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
        principal: PrincipalContext = Depends(run_principal),
    ) -> ShadowRunResponse:
        owner_id = principal.owner_id
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
        principal: PrincipalContext = Depends(read_principal),
    ) -> RunManifest:
        owner_id = principal.owner_id
        _, control_store = services()
        manifest = control_store.load_run(
            run_id,
            owner_id=owner_id,
        )
        if manifest is None:
            if control_store.run_exists_for_other_owner(
                run_id,
                owner_id=owner_id,
            ):
                application.state.security_events.append(
                    {
                        "code": "run_cross_owner_probe",
                        "subject": principal.subject,
                        "tenant": principal.tenant,
                    }
                )
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
        principal: PrincipalContext = Depends(read_principal),
    ) -> StoredArtifactResponse:
        owner_id = principal.owner_id
        artifact_store, _ = services()
        try:
            stored = artifact_store.get(
                owner_id=owner_id,
                artifact_id=artifact_id,
            )
        except FileNotFoundError as exc:
            if artifact_store.exists_for_other_owner(
                owner_id=owner_id,
                artifact_id=artifact_id,
            ):
                application.state.security_events.append(
                    {
                        "code": "artifact_cross_owner_probe",
                        "subject": principal.subject,
                        "tenant": principal.tenant,
                    }
                )
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
