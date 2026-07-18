from __future__ import annotations

import secrets
import shutil
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..chunking import chunk_document
from ..config import settings
from ..schemas import ParsedDocument
from .normalize import normalize_graph
from .schemas import (
    AssembleRequest,
    CropRequest,
    EngineQualityReport,
    NormalizeRequest,
    NormalizedGraph,
    RenderResponse,
    SolveRequest,
    SolveResponse,
    ValidateRequest,
    VisualUnit,
)
from .service import assemble_mindmap
from .topology import solve_topology
from .validate import validate_graph
from .visuals import (
    RENDER_TYPES,
    crop_regions,
    render_document,
    resolve_asset_path,
)


router = APIRouter(prefix="/v1", tags=["mindmap-engine"])


class ChunkingRequest(BaseModel):
    document: ParsedDocument
    max_chars: int = Field(default=1800, ge=200, le=12000)
    overlap_chars: int = Field(default=240, ge=0, le=2000)


def _provided_token(
    authorization: str | None,
    x_engine_token: str | None,
) -> str:
    if x_engine_token:
        return x_engine_token
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def require_engine_token(
    authorization: str | None = Header(default=None),
    x_engine_token: str | None = Header(default=None),
) -> None:
    expected = settings.external_engine_token
    if not expected:
        return
    provided = _provided_token(authorization, x_engine_token)
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="外部引擎鉴权失败。")


def require_asset_token(
    token: str = Query(default=""),
    authorization: str | None = Header(default=None),
    x_engine_token: str | None = Header(default=None),
) -> None:
    expected = settings.asset_access_token
    if not expected:
        return
    provided = token or _provided_token(authorization, x_engine_token)
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="视觉资产鉴权失败。")


@router.get("/mindmap/health")
async def engine_health():
    return {
        "status": "ok",
        "auth_required": bool(settings.external_engine_token),
        "asset_public_base_url_configured": bool(settings.asset_public_base_url),
        "data_dir": str(settings.mindmap_data_dir),
        "solver": "ortools-cp-sat",
        "graph": "networkx",
    }


@router.post(
    "/chunks",
    dependencies=[Depends(require_engine_token)],
)
async def create_chunks(request: ChunkingRequest):
    chunks = chunk_document(
        request.document,
        max_chars=request.max_chars,
        overlap_chars=request.overlap_chars,
    )
    return {
        "document_id": request.document.document_id,
        "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
    }


@router.post(
    "/mindmap/normalize",
    response_model=NormalizedGraph,
    dependencies=[Depends(require_engine_token)],
)
async def normalize_candidates(request: NormalizeRequest):
    return normalize_graph(request)


@router.post(
    "/mindmap/solve",
    response_model=SolveResponse,
    dependencies=[Depends(require_engine_token)],
)
async def solve_graph(request: SolveRequest):
    return solve_topology(request)


@router.post(
    "/mindmap/validate",
    response_model=EngineQualityReport,
    dependencies=[Depends(require_engine_token)],
)
async def validate_mindmap(request: ValidateRequest):
    return validate_graph(request)


@router.post(
    "/mindmap/assemble",
    response_model=SolveResponse,
    dependencies=[Depends(require_engine_token)],
)
async def assemble_graph(request: AssembleRequest):
    return assemble_mindmap(request)


@router.post(
    "/mindmap/visuals/render",
    response_model=RenderResponse,
    dependencies=[Depends(require_engine_token)],
)
async def render_visual_document(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in RENDER_TYPES:
        raise HTTPException(
            status_code=400,
            detail="请上传 PDF、PPTX、PNG、JPG、JPEG 或 WEBP。",
        )

    upload_dir = settings.mindmap_data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_path = upload_dir / f"{uuid.uuid4().hex[:16]}{suffix}"
    try:
        with upload_path.open("wb") as handle:
            shutil.copyfileobj(file.file, handle)
        return render_document(
            upload_path,
            file.filename or upload_path.name,
            settings.mindmap_data_dir,
            settings.asset_public_base_url,
            settings.asset_access_token,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        upload_path.unlink(missing_ok=True)


@router.post(
    "/mindmap/visuals/crop",
    response_model=list[VisualUnit],
    dependencies=[Depends(require_engine_token)],
)
async def crop_visual_regions(request: CropRequest):
    try:
        return crop_regions(
            request,
            settings.mindmap_data_dir,
            settings.asset_public_base_url,
            settings.asset_access_token,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/mindmap/assets/{render_id}/{filename}",
    dependencies=[Depends(require_asset_token)],
)
async def get_visual_asset(render_id: str, filename: str):
    try:
        path = resolve_asset_path(
            settings.mindmap_data_dir,
            render_id,
            filename,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path)
