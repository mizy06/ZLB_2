from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import uuid
from collections.abc import AsyncIterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Annotated, BinaryIO
from urllib.parse import quote

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.staticfiles import StaticFiles
from .architecture_schemas import (
    HistoryItem,
    JobInteractionView,
    JobRefinementRequest,
    JobView,
    MindMapLoopConfig,
    MindMapLoopRound,
    ReviewResolutionRequest,
    ReviewResolutionResponse,
    RunMode,
    default_mindmap_loop,
)
from .auth import (
    Principal,
    require_api_principal,
)
from .blackboard import SQLiteBlackboard
from .cplus_pipeline import run_cplus_pipeline
from .config import (
    PROJECT_ROOT,
    settings,
    validate_production_qwen_configuration,
)
from .document_parser import SUPPORTED_TYPES
from .editorial_ppt_pipeline import (
    ARCHITECTURE_NAME as EDITORIAL_PPT_ARCHITECTURE_NAME,
    editorial_ppt_enabled,
    run_editorial_ppt_pipeline,
)
from .export_service import render_mindmap_png
from .human_loop import (
    finish_active_interaction,
    initialize_interaction_manifest,
    interaction_views,
    normalize_human_instruction,
    queue_refinement_manifest,
)
from .job_events import JobEventHub
from .job_runtime import JobRuntime, monotonic_progress
from .mindmap_engine.router import router as mindmap_engine_router
from .model_provider import OpenAICompatibleClient
from .agent_prompts import THEME_SYNTHESIZER_PROMPT_SHA256
from .pdf_page_knowledge import (
    PAGE_KNOWLEDGE_SCHEMA_VERSION,
    PDF_PAGE_KNOWLEDGE_PROMPT_SHA256,
)
from .pdf_layout_knowledge import (
    PAGE_LAYOUT_NODE_SCHEMA_VERSION,
    PAGE_LAYOUT_SCHEMA_VERSION,
)
from .pdf_page_transcription import (
    PAGE_TRANSCRIPTION_SCHEMA_VERSION,
    PDF_PAGE_TRANSCRIPTION_PROMPT_SHA256,
)
from .qwen_provider import QwenClient
from .review_service import resolve_review_item
from .runtime_manifest import (
    poppler_version as _poppler_version,
    runtime_versions as _runtime_versions,
    sanitize_endpoint as _sanitized_endpoint,
)
from .single_shot_ppt_pipeline import (
    run_single_shot_ppt_pipeline,
    single_shot_ppt_enabled,
)
from .upload_validation import (
    LEGACY_OFFICE_SUFFIXES,
    UploadValidationError,
    convert_legacy_office,
    validate_upload_path,
)


UPLOAD_DIR = PROJECT_ROOT / "backend" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
FRONTEND_DIST_DIR = PROJECT_ROOT / "frontend" / "dist"
JOB_UPLOAD_SUFFIXES = SUPPORTED_TYPES | set(LEGACY_OFFICE_SUFFIXES)

app = FastAPI(
    title="ZLB Mind Map Agent",
    version="2.0.0",
    docs_url=None if settings.production else "/docs",
    redoc_url=None if settings.production else "/redoc",
    openapi_url=None if settings.production else "/openapi.json",
)
if not settings.production:
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
job_runtime = JobRuntime(settings.max_concurrent_jobs)
job_events = JobEventHub()
export_semaphore = asyncio.Semaphore(settings.export_concurrency)
job_control_lock = asyncio.Lock()


def _owner_scope(principal: Principal) -> str | None:
    # Existing pre-auth local graph versions have an empty owner. Production
    # always supplies a concrete owner and therefore remains fail-closed.
    return None if principal.id == "local-development" else principal.id


def _copy_upload_limited(
    source: BinaryIO,
    target: Path,
    limit: int,
) -> tuple[int, str]:
    total = 0
    digest = hashlib.sha256()
    try:
        with target.open("xb") as handle:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise UploadValidationError("上传文件大小超过限制。")
                digest.update(chunk)
                handle.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return total, digest.hexdigest()


def _run_manifest(
    *,
    source_sha256: str,
    source_size: int,
    filename: str,
    provider: str,
    model: str,
    page_count: int | None,
) -> dict:
    uses_page_knowledge = (
        settings.pdf_transcription_mode.casefold()
        == "vision_nodes_strict"
    )
    uses_layout_nodes = False
    pdf_page_schema_version = (
        PAGE_KNOWLEDGE_SCHEMA_VERSION
        if uses_page_knowledge
        else PAGE_TRANSCRIPTION_SCHEMA_VERSION
    )
    pdf_page_prompt_version = (
        settings.pdf_page_knowledge_prompt_version
        if uses_page_knowledge
        else settings.pdf_page_transcription_prompt_version
    )
    pdf_page_prompt_sha256 = (
        PDF_PAGE_KNOWLEDGE_PROMPT_SHA256
        if uses_page_knowledge
        else PDF_PAGE_TRANSCRIPTION_PROMPT_SHA256
    )
    return {
        "source_sha256": source_sha256,
        "source_size_bytes": source_size,
        "source_filename": filename,
        "source_page_count": page_count,
        "git_sha": os.getenv("GIT_SHA", "unknown"),
        "image_digest": os.getenv("IMAGE_DIGEST", "unknown"),
        "parser_version": settings.parser_version,
        "prompt_version": settings.prompt_version,
        "prompt_versions": {
            "pipeline": settings.prompt_version,
            "theme": {
                "version": settings.theme_prompt_version,
                "sha256": THEME_SYNTHESIZER_PROMPT_SHA256,
            },
            "pdf_page_knowledge": {
                "version": settings.pdf_page_knowledge_prompt_version,
                "sha256": PDF_PAGE_KNOWLEDGE_PROMPT_SHA256,
            },
            "pdf_page_transcription": {
                "version": settings.pdf_page_transcription_prompt_version,
                "sha256": PDF_PAGE_TRANSCRIPTION_PROMPT_SHA256,
            },
        },
        "schema_version": settings.schema_version,
        "layout_version": settings.layout_version,
        "provider": provider,
        "model": model,
        "text_model": model,
        "vision_model": settings.qwen_vision_model,
        "provider_endpoint": _sanitized_endpoint(settings.qwen_base_url),
        "qwen_production_profile": settings.qwen_production_profile,
        "pdf_page_transcription": {
            "mode": settings.pdf_transcription_mode,
            "extraction_profile": "direct",
            "schema_version": pdf_page_schema_version,
            "prompt_version": pdf_page_prompt_version,
            "prompt_sha256": pdf_page_prompt_sha256,
            "layout_schema_version": (
                PAGE_LAYOUT_SCHEMA_VERSION
                if uses_layout_nodes
                else None
            ),
            "layout_node_schema_version": (
                PAGE_LAYOUT_NODE_SCHEMA_VERSION
                if uses_layout_nodes
                else None
            ),
            "output_contract": (
                "PageKnowledgeExtraction"
                if uses_page_knowledge
                else "PageExtraction"
            ),
            "source_mode": "direct_visual_only",
            "text_intermediate_built": False,
            "render_dpi": settings.pdf_transcription_dpi,
            "concurrency": settings.pdf_transcription_concurrency,
            "max_page_attempts": settings.pdf_transcription_max_attempts,
            "min_confidence": settings.pdf_transcription_min_confidence,
        },
        "runtime_versions": dict(_runtime_versions()),
    }


def _require_coding_model(provider: str, model: str) -> None:
    if provider != "qwen":
        raise HTTPException(status_code=400, detail="不支持的模型服务商。")
    try:
        MindMapLoopRound(editor_model=model)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"模型 ID 格式无效：{model!r}",
        ) from exc


def _require_qwen_model(provider: str, model: str) -> None:
    _require_coding_model(provider, model)
    if not model.strip().casefold().startswith("qwen"):
        raise HTTPException(status_code=400, detail="仅支持 Qwen 系列模型。")


def _loop_config_from_record(record: dict) -> MindMapLoopConfig:
    payload = record.get("manifest", {}).get("loop_config")
    if payload:
        return MindMapLoopConfig.model_validate(payload)
    return default_mindmap_loop(record.get("model") or settings.qwen_model)


def _parse_loop_submission(
    loop_config: str,
    model: str,
) -> tuple[MindMapLoopConfig, str]:
    if not loop_config.strip():
        return default_mindmap_loop(model), ""
    payload = json.loads(loop_config)
    if not isinstance(payload, dict):
        raise ValueError("loop_config 必须是 JSON 对象。")
    human_instruction = normalize_human_instruction(
        payload.pop("human_instruction", "")
    )
    return MindMapLoopConfig.model_validate(payload), human_instruction


def _finish_job_interaction(
    task_id: str,
    *,
    status: str,
    graph_version: int | None = None,
    error: str | None = None,
) -> None:
    record = blackboard.load_job(task_id)
    if not record:
        return
    manifest = finish_active_interaction(
        record.get("manifest", {}),
        status=status,
        graph_version=graph_version,
        error=error,
    )
    blackboard.update_job_manifest(task_id, manifest)


def _set_job(task_id: str, **updates) -> None:
    with jobs_lock:
        current = jobs.get(task_id)
    persisted = blackboard.load_job(task_id)
    if current is None and persisted is None:
        raise KeyError(task_id)
    if current is None:
        current = JobView(
            id=task_id,
            status=persisted["status"],
            stage=persisted["stage"],
            progress=persisted["progress"],
            message=persisted["message"],
            mode=persisted["mode"],
            loop_config=_loop_config_from_record(persisted),
            error=persisted["error"],
        )
    requested_progress = updates.get("progress", current.progress)
    reset_progress = (
        updates.get("status") == "queued"
        and updates.get("stage") in {"queued", "recovered"}
    )
    updates["progress"] = (
        max(0, min(int(requested_progress), 100))
        if reset_progress
        else monotonic_progress(current.progress, requested_progress)
    )
    updated = current.model_copy(update=updates)
    with jobs_lock:
        jobs[task_id] = updated
    record = persisted or {}
    blackboard.upsert_job(
        task_id=task_id,
        status=updated.status,
        stage=updated.stage,
        progress=updated.progress,
        message=updated.message,
        error=updated.error,
        mode=updated.mode,
        source_path=record.get("source_path", ""),
        filename=record.get("filename", ""),
        model=record.get("model", ""),
        provider=record.get("provider", ""),
        use_ai=record.get("use_ai", True),
        owner_id=record.get("owner_id", ""),
        manifest=record.get("manifest", {}),
    )


async def _execute_job(
    task_id: str,
    path: Path,
    filename: str,
    model: str,
    provider: str,
    mode: RunMode,
    use_ai: bool,
    loop_config: MindMapLoopConfig | None = None,
    user_instruction: str = "",
    previous_result=None,
) -> None:
    resolved_loop = loop_config or default_mindmap_loop(model)
    _set_job(
        task_id,
        status="running",
        stage="starting",
        progress=4,
        message="任务已启动",
    )
    await job_events.publish(
        task_id,
        "status",
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
        await job_events.publish(
            task_id,
            "status",
            stage=stage,
            progress=progress,
            message=message,
        )

    async def publish_model_output(event: dict) -> None:
        payload = dict(event)
        kind = payload.pop("kind")
        await job_events.publish(task_id, kind, **payload)

    try:
        job_record = blackboard.load_job(task_id)
        manifest = (job_record.get("manifest") if job_record else {}) or {}
        multi_paths = [Path(p) for p in manifest.get("source_paths", [])] or [path]
        multi_filenames = manifest.get("filenames") or [filename]
        pipeline_family = _pipeline_family(multi_paths)
        if pipeline_family == "editorial":
            result = await run_editorial_ppt_pipeline(
                task_id=task_id,
                file_path=multi_paths[0],
                file_paths=multi_paths,
                filename=filename,
                filenames=multi_filenames,
                model=model,
                provider=provider,
                mode=mode,
                use_ai=use_ai,
                progress=update,
                blackboard=blackboard,
                loop_config=resolved_loop,
                model_output=publish_model_output,
                user_instruction=user_instruction,
                previous_result=previous_result,
            )
        elif pipeline_family == "single-shot":
            result = await run_single_shot_ppt_pipeline(
                task_id=task_id,
                file_path=path,
                filename=filename,
                model=model,
                provider=provider,
                mode=mode,
                use_ai=use_ai,
                progress=update,
                blackboard=blackboard,
                user_instruction=user_instruction,
                previous_result=previous_result,
            )
        else:
            result = await run_cplus_pipeline(
                task_id=task_id,
                file_path=multi_paths[0],
                file_paths=multi_paths,
                filename=filename,
                filenames=multi_filenames,
                model=model,
                provider=provider,
                mode=mode,
                use_ai=use_ai,
                progress=update,
                blackboard=blackboard,
                user_instruction=user_instruction,
                previous_result=previous_result,
            )
        _finish_job_interaction(
            task_id,
            status="completed",
            graph_version=result.graph_version,
        )
        _set_job(
            task_id,
            status="completed",
            stage="complete",
            progress=100,
            message="思维导图已生成",
            result=result,
        )
        await job_events.publish(
            task_id,
            "job_complete",
            stage="complete",
            progress=100,
            message="思维导图已生成",
        )
    except asyncio.CancelledError:
        cancellation_reason = job_runtime.cancel_reason(task_id)
        interrupted_by_shutdown = cancellation_reason == "shutdown"
        if not interrupted_by_shutdown:
            _finish_job_interaction(task_id, status="cancelled")
        _set_job(
            task_id,
            status="queued" if interrupted_by_shutdown else "cancelled",
            stage="interrupted" if interrupted_by_shutdown else "cancelled",
            message=(
                "服务关闭中，任务已保留并将在重启后重新排队。"
                if interrupted_by_shutdown
                else "任务已取消，原件已保留，可重新提交。"
            ),
            error=None,
        )
        run_id = blackboard.load_run_id(task_id)
        if run_id:
            blackboard.update_run(
                run_id,
                status="queued" if interrupted_by_shutdown else "cancelled",
                stage=(
                    "interrupted"
                    if interrupted_by_shutdown
                    else "cancelled"
                ),
            )
        if not interrupted_by_shutdown:
            await job_events.publish(
                task_id,
                "job_cancelled",
                stage="cancelled",
                message="任务已取消。",
            )
        raise
    except Exception as exc:
        _finish_job_interaction(
            task_id,
            status="failed",
            error=str(exc),
        )
        _set_job(
            task_id,
            status="failed",
            stage="failed",
            message="任务执行失败",
            error=str(exc),
        )
        run_id = blackboard.load_run_id(task_id)
        if run_id:
            blackboard.update_run(
                run_id,
                status="failed",
                stage="failed",
            )
        await job_events.publish(
            task_id,
            "job_failed",
            stage="failed",
            message="任务执行失败",
        )


def _pipeline_family(path_or_paths: Path | list[Path]) -> str:
    paths = path_or_paths if isinstance(path_or_paths, list) else [path_or_paths]
    if paths and all(p.suffix.lower() == ".pptx" for p in paths):
        if editorial_ppt_enabled():
            return "editorial"
        if single_shot_ppt_enabled():
            return "single-shot"
    return "cplus"


def _schedule_job(record: dict) -> None:
    task_id = record["task_id"]
    path = Path(record["source_path"])
    manifest = record.get("manifest", {})
    base_graph_version = int(manifest.get("base_graph_version") or 0)
    previous_result = (
        blackboard.load_latest_result(task_id)
        if base_graph_version > 0
        else None
    )

    async def worker() -> None:
        await _execute_job(
            task_id,
            path,
            record["filename"] or path.name,
            record["model"],
            record["provider"],
            record["mode"],
            record["use_ai"],
            _loop_config_from_record(record),
            str(manifest.get("active_instruction") or ""),
            previous_result,
        )

    job_runtime.submit(task_id, worker)


def _job_view_from_record(
    record: dict,
    *,
    result=None,
) -> JobView:
    manifest = record.get("manifest") or {}
    ctx_tokens = manifest.get("context_tokens", record.get("context_tokens", 0))
    max_ctx = manifest.get("max_context_tokens", record.get("max_context_tokens", 131072))
    ctx_usage = manifest.get("context_usage", (ctx_tokens / max_ctx if max_ctx > 0 else 0.0))
    return JobView(
        id=record["task_id"],
        status=record["status"],
        stage=record["stage"],
        progress=record["progress"],
        message=record["message"],
        mode=record["mode"],
        loop_config=_loop_config_from_record(record),
        result=result,
        error=record["error"],
        context_tokens=ctx_tokens,
        max_context_tokens=max_ctx,
        context_usage=ctx_usage,
    )


def _cleanup_expired_sources() -> None:
    if settings.source_retention_hours <= 0:
        return
    cutoff = datetime.now(UTC) - timedelta(
        hours=settings.source_retention_hours
    )
    for record in blackboard.list_jobs(
        statuses={"completed", "failed", "cancelled"},
        limit=500,
    ):
        try:
            updated = datetime.fromisoformat(record["updated_at"])
        except ValueError:
            continue
        if updated > cutoff:
            continue
        source = Path(record["source_path"])
        if source.parent == UPLOAD_DIR.resolve():
            source.unlink(missing_ok=True)


@app.on_event("startup")
async def recover_jobs() -> None:
    validate_production_qwen_configuration(settings)
    await asyncio.to_thread(_cleanup_expired_sources)
    for record in blackboard.list_jobs(
        statuses={"queued", "running"},
        limit=500,
    ):
        path = Path(record["source_path"])
        if not path.is_file():
            blackboard.upsert_job(
                **{
                    **{
                        key: record[key]
                        for key in (
                            "task_id",
                            "mode",
                            "source_path",
                            "filename",
                            "model",
                            "provider",
                            "use_ai",
                            "owner_id",
                        )
                    },
                    "status": "failed",
                    "stage": "failed",
                    "progress": record["progress"],
                    "message": "服务恢复时未找到保留的源文件。",
                    "error": "source file missing during recovery",
                    "manifest": record["manifest"],
                }
            )
            run_id = blackboard.load_run_id(record["task_id"])
            if run_id:
                blackboard.update_run(
                    run_id,
                    status="failed",
                    stage="failed",
                )
            continue
        blackboard.upsert_job(
            task_id=record["task_id"],
            status="queued",
            stage="recovered",
            # Recovery currently restarts the pipeline from parse. Keeping a
            # stale 70-90% value would falsely imply stage-exact resume and
            # would also pin all early updates behind monotonic_progress().
            progress=0,
            message="服务重启后已重新排队。",
            mode=record["mode"],
            source_path=record["source_path"],
            filename=record["filename"],
            model=record["model"],
            provider=record["provider"],
            use_ai=record["use_ai"],
            owner_id=record["owner_id"],
            manifest=record["manifest"],
        )
        run_id = blackboard.load_run_id(record["task_id"])
        if run_id:
            blackboard.update_run(
                run_id,
                status="queued",
                stage="recovered",
            )
        refreshed = blackboard.load_job(record["task_id"])
        with jobs_lock:
            jobs[record["task_id"]] = _job_view_from_record(refreshed)
        _schedule_job(refreshed)


@app.on_event("shutdown")
async def shutdown_runtime() -> None:
    await job_runtime.cancel_all(reason="shutdown")
    await OpenAICompatibleClient.close_shared_clients()


@app.get("/api/health")
async def health():
    editorial = editorial_ppt_enabled()
    single_shot = single_shot_ppt_enabled()
    ppt_vision_only = editorial or single_shot
    return {
        "status": "ok",
        "workspace": {
            "name": settings.workspace_name,
            "key_configured": settings.key_configured,
        },
        "environment": settings.environment,
        "auth_required": False,
        "auth_configured": False,
        "default_model": settings.qwen_model,
        "providers": {
            "qwen": {
                "configured": settings.key_configured,
                "default_model": settings.qwen_model,
            },
        },
        "architecture": {
            "name": (
                EDITORIAL_PPT_ARCHITECTURE_NAME
                if editorial
                else "single-shot-ppt-vision"
                if single_shot
                else "C+"
            ),
            "blackboard": "sqlite",
            "topology_solver": (
                "disabled"
                if ppt_vision_only
                else "ortools-cp-sat"
            ),
            "graph_validator": (
                "pydantic-local-tree+multi-role-review"
                if editorial
                else "pydantic-local-tree"
                if single_shot
                else "networkx"
            ),
            "loop": {
                "max_rounds": 6,
                "roles": [
                    {
                        "id": "global_editor",
                        "label": "主编",
                        "required": True,
                        "uses_images": True,
                    },
                    {
                        "id": "content_omission",
                        "label": "内容遗漏",
                        "required": False,
                        "uses_images": True,
                    },
                    {
                        "id": "pruning",
                        "label": "剪枝",
                        "required": False,
                        "uses_images": False,
                    },
                    {
                        "id": "multilevel_structure",
                        "label": "多级结构",
                        "required": False,
                        "uses_images": False,
                    },
                ],
                "example": default_mindmap_loop(
                    settings.qwen_vision_model
                ).model_dump(mode="json"),
            },
        },
        "supported_extensions": sorted(JOB_UPLOAD_SUFFIXES),
    }


@app.get("/api/models")
async def models(
    provider: str = "qwen",
    _principal: Principal = Depends(require_api_principal),
):
    if provider != "qwen":
        raise HTTPException(status_code=400, detail="不支持的模型服务商。")
    client = QwenClient(settings)
    default_model = settings.qwen_model
    try:
        available = await client.list_models()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    preferred = list(dict.fromkeys(available))
    if default_model not in preferred:
        preferred.insert(0, default_model)
    else:
        preferred.remove(default_model)
        preferred.insert(0, default_model)
    return {"models": preferred, "count": len(available)}


@app.post("/api/model-check")
async def model_check(
    model: str = Form(...),
    provider: str = Form(default="qwen"),
    _principal: Principal = Depends(require_api_principal),
):
    _require_coding_model(provider, model)
    client = QwenClient(settings)
    ok, message = await client.check_model(model)
    return {
        "ok": ok,
        "model": model,
        "provider": provider,
        "message": message,
    }


@app.post("/api/jobs", response_model=JobView)
async def create_job(
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] | None = File(default=None),
    model: str = Form(default=settings.qwen_model),
    provider: str = Form(default="qwen"),
    loop_config: str = Form(default=""),
    use_ai: bool = Form(default=True),
    principal: Principal = Depends(require_api_principal),
):
    _require_coding_model(provider, model)
    try:
        configured_loop, human_instruction = _parse_loop_submission(
            loop_config,
            model,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Mindmap loop 配置无效：{exc}",
        ) from exc
    for selected_model in configured_loop.all_models():
        _require_coding_model(provider, selected_model)
    primary_model = configured_loop.rounds[0].editor_model
    mode: RunMode = "standard"

    raw_uploads = [f for f in (files or []) if f and getattr(f, "filename", None)]
    if file is not None and getattr(file, "filename", None) and file not in raw_uploads:
        raw_uploads.insert(0, file)

    if not raw_uploads:
        raise HTTPException(
            status_code=400,
            detail="请上传至少一份 PDF、PPT、PPTX、DOC、DOCX、TXT 或 MD 文件。",
        )

    task_id = uuid.uuid4().hex[:12]
    saved_paths: list[Path] = []
    saved_filenames: list[str] = []
    saved_sizes: list[int] = []
    saved_digests: list[str] = []
    total_pages: int = 0

    for idx, upload_file in enumerate(raw_uploads):
        suffix = Path(upload_file.filename or "").suffix.lower()
        if suffix not in JOB_UPLOAD_SUFFIXES:
            raise HTTPException(
                status_code=400,
                detail=f"文件 {upload_file.filename} 格式不受支持，请上传 PDF、PPT、PPTX、DOC、DOCX、TXT 或 MD 文件。",
            )
        path = (UPLOAD_DIR / f"{task_id}_{idx}{suffix}").resolve()
        original_path = path
        converted_path: Path | None = None
        try:
            source_size, source_sha256 = await asyncio.to_thread(
                _copy_upload_limited,
                upload_file.file,
                path,
                settings.max_upload_bytes,
            )
            inspection = await asyncio.to_thread(
                validate_upload_path,
                path,
                filename=upload_file.filename or path.name,
                content_type=upload_file.content_type or "",
                settings=settings,
            )
            if suffix in LEGACY_OFFICE_SUFFIXES:
                converted_path = await asyncio.to_thread(
                    convert_legacy_office,
                    original_path,
                )
                inspection = await asyncio.to_thread(
                    validate_upload_path,
                    converted_path,
                    filename=converted_path.name,
                    content_type="",
                    settings=settings,
                )
                original_path.unlink(missing_ok=True)
                path = converted_path
            saved_paths.append(path)
            saved_filenames.append(upload_file.filename or path.name)
            saved_sizes.append(source_size)
            saved_digests.append(source_sha256)
            if inspection.page_count:
                total_pages += inspection.page_count
        except UploadValidationError as exc:
            original_path.unlink(missing_ok=True)
            if converted_path is not None:
                converted_path.unlink(missing_ok=True)
            status_code = 413 if "大小超过" in str(exc) else 422
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        finally:
            await upload_file.close()

    primary_path = saved_paths[0]
    display_filename = " & ".join(saved_filenames[:2]) + (f" 等{len(saved_filenames)}份文档" if len(saved_filenames) > 2 else "")
    total_size = sum(saved_sizes)
    combined_sha256 = hashlib.sha256("::".join(saved_digests).encode()).hexdigest()

    job = JobView(
        id=task_id,
        status="queued",
        stage="queued",
        progress=0,
        message="文件已接收，等待处理",
        mode=mode,
        loop_config=configured_loop,
        context_tokens=0,
        max_context_tokens=131072,
        context_usage=0.0,
    )
    manifest = _run_manifest(
        source_sha256=combined_sha256,
        source_size=total_size,
        filename=display_filename,
        provider=provider,
        model=primary_model,
        page_count=total_pages or None,
    )
    manifest = initialize_interaction_manifest(
        manifest,
        human_instruction,
    )
    manifest.update(
        {
            "loop_config": configured_loop.model_dump(mode="json"),
            "selected_models": configured_loop.all_models(),
            "source_paths": [str(p) for p in saved_paths],
            "filenames": saved_filenames,
            "multi_document": len(saved_paths) > 1,
            "context_tokens": 0,
            "max_context_tokens": 131072,
            "context_usage": 0.0,
        }
    )
    blackboard.upsert_job(
        task_id=task_id,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        message=job.message,
        mode=mode,
        source_path=str(primary_path),
        filename=display_filename,
        model=primary_model,
        provider=provider,
        use_ai=use_ai,
        owner_id=principal.id,
        manifest=manifest,
    )
    with jobs_lock:
        jobs[task_id] = job
    await job_events.publish(
        task_id,
        "status",
        stage="queued",
        progress=0,
        message="文件已接收，等待处理",
        context_tokens=0,
        max_context_tokens=131072,
        context_usage=0.0,
    )
    record = blackboard.load_job(task_id, owner_id=principal.id)
    _schedule_job(record)
    return job



@app.get("/api/history", response_model=list[HistoryItem])
async def history(
    limit: int = 50,
    principal: Principal = Depends(require_api_principal),
):
    return blackboard.list_history(
        limit=limit,
        owner_id=_owner_scope(principal),
    )


@app.get("/api/jobs/{task_id}", response_model=JobView)
async def get_job(
    task_id: str,
    principal: Principal = Depends(require_api_principal),
):
    owner_id = _owner_scope(principal)
    record = blackboard.load_job(task_id, owner_id=owner_id)
    persisted = blackboard.load_latest_result(
        task_id,
        owner_id=owner_id,
    )
    if record:
        job = _job_view_from_record(record, result=persisted)
    elif persisted:
        job = JobView(
            id=task_id,
            status="completed",
            stage="complete",
            progress=100,
            message="已从共享黑板恢复图版本",
            mode=persisted.mode,
            result=persisted,
        )
    else:
        raise HTTPException(status_code=404, detail="任务不存在或服务已重启。")
    with jobs_lock:
        jobs[task_id] = job
    return job


@app.get(
    "/api/jobs/{task_id}/interactions",
    response_model=list[JobInteractionView],
    include_in_schema=False,
)
async def get_job_interactions(
    task_id: str,
    principal: Principal = Depends(require_api_principal),
):
    owner_id = _owner_scope(principal)
    record = blackboard.load_job(task_id, owner_id=owner_id)
    if not record:
        raise HTTPException(status_code=404, detail="任务不存在。")
    result = blackboard.load_latest_result(task_id, owner_id=owner_id)
    return interaction_views(
        record.get("manifest", {}),
        job_status=record["status"],
        result=result,
        error=record["error"],
    )


@app.post(
    "/api/jobs/{task_id}/refine",
    response_model=JobView,
    include_in_schema=False,
)
async def refine_job(
    task_id: str,
    request: JobRefinementRequest,
    principal: Principal = Depends(require_api_principal),
):
    owner_id = _owner_scope(principal)
    async with job_control_lock:
        record = blackboard.load_job(task_id, owner_id=owner_id)
        if not record:
            raise HTTPException(status_code=404, detail="任务不存在。")
        if (
            record["status"] in {"queued", "running"}
            or job_runtime.has_task(task_id)
        ):
            raise HTTPException(status_code=409, detail="任务正在处理中。")
        result = blackboard.load_latest_result(task_id, owner_id=owner_id)
        if not result:
            raise HTTPException(
                status_code=409,
                detail="只有已经出图的任务可以继续修改。",
            )
        if request.expected_graph_version != result.graph_version:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"图版本冲突：期望 v{request.expected_graph_version}，"
                    f"当前为 v{result.graph_version}。"
                ),
            )
        source_path = Path(record["source_path"])
        if not source_path.is_file():
            raise HTTPException(
                status_code=410,
                detail="原始文件已过期或缺失，无法继续修改。",
            )

        manifest = queue_refinement_manifest(
            record.get("manifest", {}),
            instruction=request.instruction,
            current_graph_version=result.graph_version,
        )
        blackboard.upsert_job(
            task_id=task_id,
            status="queued",
            stage="queued",
            progress=0,
            message="修改要求已接收，等待处理",
            mode=record["mode"],
            source_path=record["source_path"],
            filename=record["filename"],
            model=record["model"],
            provider=record["provider"],
            use_ai=record["use_ai"],
            owner_id=record["owner_id"],
            error=None,
            manifest=manifest,
        )
        await job_events.drop(task_id)
        queued = blackboard.load_job(task_id, owner_id=owner_id)
        with jobs_lock:
            jobs[task_id] = _job_view_from_record(queued, result=result)
        await job_events.publish(
            task_id,
            "status",
            stage="queued",
            progress=0,
            message="修改要求已接收，等待处理",
        )
        _schedule_job(queued)
        return _job_view_from_record(queued, result=result)


@app.get(
    "/api/jobs/{task_id}/events",
    response_class=EventSourceResponse,
)
async def stream_job_events(
    task_id: str,
    last_event_id: Annotated[int | None, Header()] = None,
    principal: Principal = Depends(require_api_principal),
) -> AsyncIterable[ServerSentEvent]:
    record = blackboard.load_job(
        task_id,
        owner_id=_owner_scope(principal),
    )
    if not record:
        raise HTTPException(status_code=404, detail="任务不存在。")
    terminal_kind = {
        "completed": "job_complete",
        "failed": "job_failed",
        "cancelled": "job_cancelled",
    }.get(record["status"])
    if terminal_kind and not job_events.has_events(task_id):
        await job_events.publish(
            task_id,
            terminal_kind,
            stage=record["stage"],
            progress=record["progress"],
            message=record["message"],
        )
    async for event in job_events.stream(
        task_id,
        after_id=last_event_id or 0,
    ):
        yield ServerSentEvent(
            data=event,
            id=str(event.id),
            retry=1_000,
        )


@app.post("/api/jobs/{task_id}/cancel", response_model=JobView)
async def cancel_job(
    task_id: str,
    principal: Principal = Depends(require_api_principal),
):
    record = blackboard.load_job(
        task_id,
        owner_id=_owner_scope(principal),
    )
    if not record:
        raise HTTPException(status_code=404, detail="任务不存在。")
    if record["status"] in {"completed", "failed", "cancelled"}:
        return _job_view_from_record(
            record,
            result=blackboard.load_latest_result(
                task_id,
                owner_id=_owner_scope(principal),
            ),
        )
    await job_runtime.cancel(task_id)
    after_cancel = blackboard.load_job(
        task_id,
        owner_id=_owner_scope(principal),
    )
    if after_cancel and after_cancel["status"] in {"queued", "running"}:
        _set_job(
            task_id,
            status="cancelled",
            stage="cancelled",
            message="任务已取消。",
            error=None,
        )
        await job_events.publish(
            task_id,
            "job_cancelled",
            stage="cancelled",
            message="任务已取消。",
        )
    refreshed = blackboard.load_job(
        task_id,
        owner_id=_owner_scope(principal),
    )
    return _job_view_from_record(refreshed)


@app.get("/api/jobs/{task_id}/versions")
async def list_versions(
    task_id: str,
    principal: Principal = Depends(require_api_principal),
):
    versions = blackboard.list_graph_versions(
        task_id,
        owner_id=_owner_scope(principal),
    )
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
async def export_json(
    task_id: str,
    principal: Principal = Depends(require_api_principal),
):
    result = blackboard.load_latest_result(
        task_id,
        owner_id=_owner_scope(principal),
    )
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
async def export_png(
    task_id: str,
    principal: Principal = Depends(require_api_principal),
):
    result = blackboard.load_latest_result(
        task_id,
        owner_id=_owner_scope(principal),
    )
    if not result:
        raise HTTPException(status_code=404, detail="任务不存在或尚无图版本。")
    async with export_semaphore:
        content = await asyncio.to_thread(render_mindmap_png, result)
    return Response(
        content=content,
        media_type="image/png",
        headers=_download_headers(result.document.title, "png"),
    )


@app.get("/api/jobs/{task_id}/versions/{version}")
async def get_version(
    task_id: str,
    version: int,
    principal: Principal = Depends(require_api_principal),
):
    result = blackboard.load_graph_version(
        task_id,
        version,
        owner_id=_owner_scope(principal),
    )
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
    principal: Principal = Depends(require_api_principal),
):
    try:
        result = resolve_review_item(
            blackboard=blackboard,
            task_id=task_id,
            review_id=review_id,
            request=request,
            owner_id=_owner_scope(principal),
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
async def delete_job(
    task_id: str,
    principal: Principal = Depends(require_api_principal),
):
    owner_id = _owner_scope(principal)
    record = blackboard.load_job(task_id, owner_id=owner_id)
    result = blackboard.load_latest_result(task_id, owner_id=owner_id)
    if not record and not result:
        raise HTTPException(status_code=404, detail="任务不存在。")
    await job_runtime.cancel(task_id)
    run_id = blackboard.delete_task(task_id, owner_id=owner_id)
    with jobs_lock:
        jobs.pop(task_id, None)
    await job_events.drop(task_id)
    if record and record["source_path"]:
        upload = Path(record["source_path"]).resolve()
        if upload.parent == UPLOAD_DIR.resolve():
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
async def root(
    _principal: Principal = Depends(require_api_principal),
):
    return {
        "name": "ZLB Mind Map Agent",
        "docs": None if settings.production else "/docs",
        "workspace": settings.workspace_name,
        "architecture": "C+",
    }


@app.get("/{full_path:path}", include_in_schema=False)
async def frontend(full_path: str):
    if full_path.startswith(("api/", "v1/")):
        raise HTTPException(status_code=404, detail="接口不存在。")
    if settings.production and (
        full_path in {"docs", "redoc", "openapi.json"}
        or full_path.startswith(("docs/", "redoc/"))
    ):
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
