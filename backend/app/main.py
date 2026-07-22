from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from pathlib import Path
from threading import Lock
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from .architecture_schemas import (
    HistoryItem,
    JobView,
    ReviewResolutionRequest,
    ReviewResolutionResponse,
    RunMode,
)
from .kimi_provider import KimiClient
from .blackboard import SQLiteBlackboard
from .cplus_pipeline import run_cplus_pipeline
from .config import PROJECT_ROOT, settings
from .document_parser import SUPPORTED_TYPES
from .export_service import render_mindmap_png
from .mindmap_engine.router import router as mindmap_engine_router
from .review_service import resolve_review_item


UPLOAD_DIR = PROJECT_ROOT / "backend" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
FRONTEND_DIST_DIR = PROJECT_ROOT / "frontend" / "dist"

app = FastAPI(title="ZLB Mind Map Agent", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(mindmap_engine_router)
if (FRONTEND_DIST_DIR / "assets").is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST_DIR / "assets"),
        name="frontend-assets",
    )

jobs: dict[str, JobView] = {}
jobs_lock = Lock()
blackboard = SQLiteBlackboard(settings.blackboard_path)


def _set_job(task_id: str, **updates) -> None:
    with jobs_lock:
        current = jobs[task_id]
        jobs[task_id] = current.model_copy(update=updates)


async def _execute_job(
    task_id: str,
    path: Path,
    filename: str,
    model: str,
    provider: str,
    mode: RunMode,
    use_ai: bool,
) -> None:
    _set_job(
        task_id,
        status="running",
        stage="starting",
        progress=4,
        message="任务已启动",
    )

    async def update(stage: str, progress: int, message: str) -> None:
        _set_job(
            task_id,
            status="running",
            stage=stage,
            progress=progress,
            message=message,
        )

    try:
        result = await run_cplus_pipeline(
            task_id=task_id,
            file_path=path,
            filename=filename,
            model=model,
            provider=provider,
            mode=mode,
            use_ai=use_ai,
            progress=update,
            blackboard=blackboard,
        )
        _set_job(
            task_id,
            status="completed",
            stage="complete",
            progress=100,
            message="思维导图已生成",
            result=result,
        )
    except Exception as exc:
        _set_job(
            task_id,
            status="failed",
            stage="failed",
            message="任务执行失败",
            error=str(exc),
        )
    finally:
        path.unlink(missing_ok=True)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "workspace": {
            "name": settings.workspace_name,
            "id_suffix": settings.workspace_id[-6:] if settings.workspace_id else "",
            "key_configured": settings.key_configured,
            "secret_source": settings.kimi_secret_source,
            "secret_error": settings.kimi_secret_error,
        },
        "default_model": settings.kimi_model,
        "providers": {
            "kimi": {
                "configured": settings.key_configured,
                "default_model": settings.kimi_model,
                "base_url": settings.kimi_base_url,
            },
        },
        "architecture": {
            "name": "C+",
            "blackboard": "sqlite",
            "topology_solver": "ortools-cp-sat",
            "graph_validator": "networkx",
            "modes": ["standard", "precision"],
        },
        "supported_extensions": sorted(SUPPORTED_TYPES),
    }


@app.get("/api/models")
async def models(provider: str = "kimi"):
    if provider != "kimi":
        raise HTTPException(status_code=400, detail="仅支持 Kimi 服务商。")
    client = KimiClient(settings)
    try:
        available = await client.list_models()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    preferred = [
        model
        for model in available
        if model == settings.kimi_model or model.startswith("kimi-k3")
    ]
    if settings.kimi_model not in preferred:
        preferred.insert(0, settings.kimi_model)
    return {"models": preferred, "count": len(available)}


@app.post("/api/model-check")
async def model_check(
    model: str = Form(...),
    provider: str = Form(default="kimi"),
):
    if provider != "kimi":
        raise HTTPException(status_code=400, detail="仅支持 Kimi 服务商。")
    client = KimiClient(settings)
    ok, message = await client.check_model(model)
    return {
        "ok": ok,
        "model": model,
        "provider": provider,
        "message": message,
    }


@app.post("/api/jobs", response_model=JobView)
async def create_job(
    file: UploadFile = File(...),
    model: str = Form(default=settings.kimi_model),
    provider: str = Form(default="kimi"),
    mode: RunMode = Form(default="standard"),
    use_ai: bool = Form(default=True),
):
    if provider != "kimi":
        raise HTTPException(status_code=400, detail="不支持的模型服务商。")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_TYPES:
        raise HTTPException(
            status_code=400,
            detail="请上传 PDF、PPTX、DOCX、TXT 或 MD 文件。",
        )

    task_id = uuid.uuid4().hex[:12]
    path = UPLOAD_DIR / f"{task_id}{suffix}"
    with path.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)

    job = JobView(
        id=task_id,
        status="queued",
        stage="queued",
        progress=0,
        message="文件已接收，等待处理",
        mode=mode,
    )
    with jobs_lock:
        jobs[task_id] = job
    asyncio.create_task(
        _execute_job(
            task_id,
            path,
            file.filename or path.name,
            model,
            provider,
            mode,
            use_ai,
        )
    )
    return job


@app.get("/api/history", response_model=list[HistoryItem])
async def history(limit: int = 50):
    return blackboard.list_history(limit=limit)


@app.get("/api/jobs/{task_id}", response_model=JobView)
async def get_job(task_id: str):
    with jobs_lock:
        job = jobs.get(task_id)
    if not job:
        persisted = blackboard.load_latest_result(task_id)
        if persisted:
            job = JobView(
                id=task_id,
                status="completed",
                stage="complete",
                progress=100,
                message="已从共享黑板恢复图版本",
                mode=persisted.mode,
                result=persisted,
            )
            with jobs_lock:
                jobs[task_id] = job
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在或服务已重启。")
    return job


@app.get("/api/jobs/{task_id}/versions")
async def list_versions(task_id: str):
    versions = blackboard.list_graph_versions(task_id)
    if not versions:
        raise HTTPException(status_code=404, detail="任务不存在或尚无图版本。")
    return {"task_id": task_id, "versions": versions}


def _download_headers(title: str, suffix: str) -> dict[str, str]:
    cleaned = "".join(
        character
        for character in title.strip()
        if character not in {'"', "\r", "\n"}
    )[:80] or "mindmap"
    encoded = quote(f"{cleaned}.{suffix}")
    return {
        "Content-Disposition": (
            f'attachment; filename="mindmap.{suffix}"; '
            f"filename*=UTF-8''{encoded}"
        )
    }


@app.get("/api/jobs/{task_id}/export.json")
async def export_json(task_id: str):
    result = blackboard.load_latest_result(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="任务不存在或尚无图版本。")
    content = json.dumps(
        result.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
    )
    return Response(
        content=content,
        media_type="application/json",
        headers=_download_headers(result.document.title, "json"),
    )


@app.get("/api/jobs/{task_id}/export.png")
async def export_png(task_id: str):
    result = blackboard.load_latest_result(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="任务不存在或尚无图版本。")
    return Response(
        content=render_mindmap_png(result),
        media_type="image/png",
        headers=_download_headers(result.document.title, "png"),
    )


@app.get("/api/jobs/{task_id}/versions/{version}")
async def get_version(task_id: str, version: int):
    result = blackboard.load_graph_version(task_id, version)
    if not result:
        raise HTTPException(status_code=404, detail="指定图版本不存在。")
    return result


@app.post(
    "/api/jobs/{task_id}/reviews/{review_id}/resolve",
    response_model=ReviewResolutionResponse,
)
async def resolve_review(
    task_id: str,
    review_id: str,
    request: ReviewResolutionRequest,
):
    try:
        result = resolve_review_item(
            blackboard=blackboard,
            task_id=task_id,
            review_id=review_id,
            request=request,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务或复核项不存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    with jobs_lock:
        current = jobs.get(task_id)
        if current:
            jobs[task_id] = current.model_copy(update={"result": result})
    return ReviewResolutionResponse(
        task_id=task_id,
        review_id=review_id,
        graph_version=result.graph_version,
        result=result,
    )


@app.delete("/api/jobs/{task_id}")
async def delete_job(task_id: str):
    result = blackboard.load_latest_result(task_id)
    run_id = blackboard.delete_task(task_id)
    with jobs_lock:
        jobs.pop(task_id, None)
    for upload in UPLOAD_DIR.glob(f"{task_id}.*"):
        upload.unlink(missing_ok=True)

    if result:
        assets_root = (settings.mindmap_data_dir / "assets").resolve()
        render_ids = {asset.render_id for asset in result.assets if asset.render_id}
        for render_id in render_ids:
            target = (assets_root / render_id).resolve()
            if target.parent == assets_root and target.is_dir():
                shutil.rmtree(target)

    if not run_id:
        raise HTTPException(status_code=404, detail="任务不存在。")
    return {"deleted": True, "task_id": task_id}


@app.get("/api")
async def root():
    return {
        "name": "ZLB Mind Map Agent",
        "docs": "/docs",
        "workspace": settings.workspace_name,
        "architecture": "C+",
    }


@app.get("/{full_path:path}", include_in_schema=False)
async def frontend(full_path: str):
    if full_path.startswith(("api/", "v1/")):
        raise HTTPException(status_code=404, detail="接口不存在。")

    index = FRONTEND_DIST_DIR / "index.html"
    if not index.is_file():
        return HTMLResponse(
            "前端生产文件尚未构建，请使用 Vite 开发服务访问工作台。",
            status_code=503,
        )

    target = (FRONTEND_DIST_DIR / full_path).resolve()
    dist_root = FRONTEND_DIST_DIR.resolve()
    if target.is_relative_to(dist_root) and target.is_file():
        return FileResponse(target)
    return FileResponse(index)
