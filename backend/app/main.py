from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .bailian import BailianClient, DeepSeekClient
from .config import PROJECT_ROOT, settings
from .document_parser import SUPPORTED_TYPES
from .mindmap_engine.router import router as mindmap_engine_router
from .pipeline import run_pipeline
from .schemas import JobView


UPLOAD_DIR = PROJECT_ROOT / "backend" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="ZLB Knowledge Map Demo", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(mindmap_engine_router)

jobs: dict[str, JobView] = {}
jobs_lock = Lock()


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
        result = await run_pipeline(
            task_id=task_id,
            file_path=path,
            filename=filename,
            model=model,
            provider=provider,
            use_ai=use_ai,
            progress=update,
        )
        _set_job(
            task_id,
            status="completed",
            stage="complete",
            progress=100,
            message="知识图谱已生成",
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
        },
        "default_model": settings.model,
        "providers": {
            "bailian": {
                "configured": settings.key_configured,
                "default_model": settings.model,
            },
            "deepseek": {
                "configured": bool(settings.deepseek_api_key),
                "default_model": settings.deepseek_model,
            },
        },
        "supported_extensions": sorted(SUPPORTED_TYPES),
    }


@app.get("/api/models")
async def models(provider: str = "bailian"):
    client = (
        DeepSeekClient(settings)
        if provider == "deepseek"
        else BailianClient(settings)
    )
    try:
        available = await client.list_models()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if provider == "deepseek":
        return {"models": available, "count": len(available)}

    preferred = [
        model
        for model in available
        if any(token in model.lower() for token in ("qwen", "deepseek", "glm"))
        and not any(token in model.lower() for token in ("image", "ocr", "realtime"))
    ]
    return {"models": preferred[:80], "count": len(available)}


@app.post("/api/model-check")
async def model_check(
    model: str = Form(...),
    provider: str = Form(default="bailian"),
):
    client = (
        DeepSeekClient(settings)
        if provider == "deepseek"
        else BailianClient(settings)
    )
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
    model: str = Form(default=settings.model),
    provider: str = Form(default="bailian"),
    use_ai: bool = Form(default=True),
):
    if provider not in {"bailian", "deepseek"}:
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
            use_ai,
        )
    )
    return job


@app.get("/api/jobs/{task_id}", response_model=JobView)
async def get_job(task_id: str):
    with jobs_lock:
        job = jobs.get(task_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在或服务已重启。")
    return job


@app.get("/api")
async def root():
    return {
        "name": "ZLB Knowledge Map Demo",
        "docs": "/docs",
        "workspace": settings.workspace_name,
    }
