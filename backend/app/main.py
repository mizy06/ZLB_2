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
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from .architecture_schemas import (
    HistoryItem,
    JobInteractionView,
    JobRefinementRequest,
    JobView,
    MindMapLoopConfig,
    MindMapLoopRound,
    RunMode,
    default_mindmap_loop,
)
from .auth import (
    AccountAlreadyExistsError,
    AccountInputError,
    InvalidCredentialsError,
    Principal,
    account_store,
    clear_session_cookie,
    require_api_principal,
    session_token_from_request,
    set_session_cookie,
)
from .blackboard import SQLiteBlackboard
from .config import (
    PROJECT_ROOT,
    model_context_window_tokens,
    settings,
    validate_production_qwen_configuration,
)
from .document_parser import SUPPORTED_TYPES
from .editorial_ppt_pipeline import (
    ARCHITECTURE_NAME as EDITORIAL_PPT_ARCHITECTURE_NAME,
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
from .model_provider import OpenAICompatibleClient
from .qwen_provider import QwenClient
from .refinement_routing import (
    RefinementRoutingDecision,
    classify_refinement,
    completed_graph_asset,
    materialize_guidance_images,
)
from .runtime_manifest import (
    poppler_version as _poppler_version,
    runtime_versions as _runtime_versions,
    sanitize_endpoint as _sanitized_endpoint,
)
from .upload_validation import (
    IMAGE_FORMATS,
    LEGACY_OFFICE_SUFFIXES,
    UploadValidationError,
    convert_legacy_office,
    validate_upload_path,
)


UPLOAD_DIR = PROJECT_ROOT / "backend" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
FRONTEND_DIST_DIR = PROJECT_ROOT / "frontend" / "dist"
JOB_UPLOAD_SUFFIXES = (
    SUPPORTED_TYPES
    | set(LEGACY_OFFICE_SUFFIXES)
)
REFINEMENT_UPLOAD_SUFFIXES = JOB_UPLOAD_SUFFIXES | set(IMAGE_FORMATS)

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
    return principal.id


class AccountCredentials(BaseModel):
    username: str
    password: str


class AccountResponse(BaseModel):
    id: str
    username: str
    created_at: str


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


async def _save_job_uploads(
    *,
    task_id: str,
    uploads: list[UploadFile],
    allowed_suffixes: set[str] | frozenset[str] = JOB_UPLOAD_SUFFIXES,
) -> tuple[list[Path], list[str], list[int], list[str], int]:
    saved_paths: list[Path] = []
    saved_filenames: list[str] = []
    saved_sizes: list[int] = []
    saved_digests: list[str] = []
    total_pages = 0

    for index, upload_file in enumerate(uploads):
        suffix = Path(upload_file.filename or "").suffix.lower()
        if suffix not in allowed_suffixes:
            if allowed_suffixes == REFINEMENT_UPLOAD_SUFFIXES:
                supported_formats = (
                    "PDF、PPT、PPTX、DOC、DOCX、TXT、MD、PNG、JPG、JPEG 或 WEBP"
                )
            else:
                supported_formats = "PDF、PPT、PPTX、DOC、DOCX、TXT 或 MD"
            raise HTTPException(
                status_code=400,
                detail=(
                    f"文件 {upload_file.filename} 格式不受支持，请上传 "
                    f"{supported_formats} 文件。"
                ),
            )
        path = (UPLOAD_DIR / f"{task_id}_{index}{suffix}").resolve()
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

    return (
        saved_paths,
        saved_filenames,
        saved_sizes,
        saved_digests,
        total_pages,
    )


def _same_upload_submission(
    first: UploadFile,
    second: UploadFile,
) -> bool:
    if first is second:
        return True
    first_name = str(first.filename or "").strip()
    second_name = str(second.filename or "").strip()
    if not first_name or first_name != second_name:
        return False
    first_size = getattr(first, "size", None)
    second_size = getattr(second, "size", None)
    if first_size is None or second_size is None:
        return False
    return (
        int(first_size) == int(second_size)
        and str(first.content_type or "") == str(second.content_type or "")
    )


def _run_manifest(
    *,
    source_sha256: str,
    source_size: int,
    filename: str,
    provider: str,
    model: str,
    page_count: int | None,
) -> dict:
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
            "editorial_pipeline": settings.prompt_version,
        },
        "architecture": EDITORIAL_PPT_ARCHITECTURE_NAME,
        "schema_version": settings.schema_version,
        "layout_version": settings.layout_version,
        "provider": provider,
        "model": model,
        "text_model": model,
        "vision_model": settings.qwen_vision_model,
        "provider_endpoint": _sanitized_endpoint(settings.qwen_base_url),
        "qwen_production_profile": settings.qwen_production_profile,
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
    completed_graph_asset_payload: dict | None = None,
    guidance_image_paths: list[Path] | None = None,
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
    await job_events.publish(
        task_id,
        "agent_started",
        stage="starting",
        progress=4,
        message="Agent 已启动，正在准备输入",
    )
    await job_events.publish(
        task_id,
        "context_preparing",
        stage="context_preparing",
        progress=6,
        message="正在分类文档、准备文本上下文和视觉页面",
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
            completed_graph_asset=completed_graph_asset_payload,
            guidance_image_paths=guidance_image_paths,
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


def _schedule_job(record: dict) -> None:
    task_id = record["task_id"]
    path = Path(record["source_path"])
    manifest = record.get("manifest", {})
    base_graph_version = int(manifest.get("base_graph_version") or 0)
    refinement_route = str(manifest.get("refinement_route") or "")
    previous_result = (
        blackboard.load_latest_result(task_id)
        if base_graph_version > 0
        and refinement_route in {"", "guidance_only"}
        else None
    )
    completed_graph_asset_payload = (
        manifest.get("completed_graph_asset")
        if refinement_route == "merge_graph"
        else None
    )
    guidance_image_paths = [
        Path(path)
        for path in manifest.get("guidance_image_paths", [])
        if isinstance(path, str) and Path(path).is_file()
    ]

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
            (
                completed_graph_asset_payload
                if isinstance(completed_graph_asset_payload, dict)
                else None
            ),
            guidance_image_paths,
        )

    job_runtime.submit(task_id, worker)


def _job_view_from_record(
    record: dict,
    *,
    result=None,
) -> JobView:
    manifest = record.get("manifest") or {}
    ctx_tokens = manifest.get("context_tokens", record.get("context_tokens", 0))
    configured_ctx = model_context_window_tokens(
        str(record.get("model") or "")
    )
    stored_ctx = manifest.get(
        "max_context_tokens",
        record.get("max_context_tokens", configured_ctx),
    )
    # Jobs created before the Qwen 3.8 capacity fix persisted its former
    # 131K output cap as a context limit. Preserve their token count but
    # expose the model's real context window to the client.
    max_ctx = (
        configured_ctx
        if configured_ctx > 131_072 and stored_ctx == 131_072
        else stored_ctx
    )
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


@app.post("/api/auth/register", response_model=AccountResponse)
async def register_account(
    credentials: AccountCredentials,
    request: Request,
    response: Response,
):
    try:
        account, token, first_account = account_store(settings).register(
            credentials.username,
            credentials.password,
        )
    except AccountAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AccountInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if first_account:
        # Jobs created before account auth used the temporary public owner (or
        # an empty owner in older local versions). Give those records to the
        # first account without changing the existing graph/run schema.
        blackboard.reassign_owner(settings.workbench_owner_id, account.id)
        blackboard.reassign_owner("", account.id)
    set_session_cookie(response, request, token)
    return AccountResponse(**account.as_dict())


@app.post("/api/auth/login", response_model=AccountResponse)
async def login_account(
    credentials: AccountCredentials,
    request: Request,
    response: Response,
):
    try:
        account, token = account_store(settings).login(
            credentials.username,
            credentials.password,
        )
    except (AccountInputError, InvalidCredentialsError) as exc:
        raise HTTPException(status_code=401, detail="用户名或密码错误。") from exc
    set_session_cookie(response, request, token)
    return AccountResponse(**account.as_dict())


@app.post("/api/auth/logout")
async def logout_account(request: Request, response: Response):
    account_store(settings).logout(session_token_from_request(request))
    clear_session_cookie(response)
    return {"loggedOut": True}


@app.get("/api/auth/me", response_model=AccountResponse)
async def current_account(
    principal: Principal = Depends(require_api_principal),
):
    account = account_store(settings).account_for_principal(principal)
    if account is None:
        raise HTTPException(status_code=401, detail="请先登录。")
    return AccountResponse(**account.as_dict())


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "workspace": {
            "name": settings.workspace_name,
            "key_configured": settings.key_configured,
        },
        "environment": settings.environment,
        "auth_required": True,
        "auth_configured": True,
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
            ),
            "blackboard": "sqlite",
            "topology_solver": "disabled",
            "graph_validator": "pydantic-local-tree+multi-role-review",
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
    if (
        file is not None
        and getattr(file, "filename", None)
        and not any(
            _same_upload_submission(file, selected)
            for selected in raw_uploads
        )
    ):
        raw_uploads.insert(0, file)

    if not raw_uploads:
        raise HTTPException(
            status_code=400,
            detail=(
                "请上传至少一份 PDF、PPT、PPTX、DOC、DOCX、TXT 或 MD 文件。"
            ),
        )

    task_id = uuid.uuid4().hex[:12]
    (
        saved_paths,
        saved_filenames,
        saved_sizes,
        saved_digests,
        total_pages,
    ) = await _save_job_uploads(
        task_id=task_id,
        uploads=raw_uploads,
    )

    primary_path = saved_paths[0]
    display_filename = " & ".join(saved_filenames[:2]) + (f" 等{len(saved_filenames)}份文档" if len(saved_filenames) > 2 else "")
    total_size = sum(saved_sizes)
    combined_sha256 = hashlib.sha256("::".join(saved_digests).encode()).hexdigest()
    context_limit = model_context_window_tokens(primary_model)

    job = JobView(
        id=task_id,
        status="queued",
        stage="queued",
        progress=0,
        message="文件已接收，等待处理",
        mode=mode,
        loop_config=configured_loop,
        context_tokens=0,
        max_context_tokens=context_limit,
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
            "max_context_tokens": context_limit,
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
        max_context_tokens=context_limit,
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


async def _queue_classified_refinement(
    *,
    task_id: str,
    record: dict,
    result,
    instruction: str,
    attachment_paths: list[Path] | None = None,
    attachment_filenames: list[str] | None = None,
    attachment_sizes: list[int] | None = None,
    attachment_digests: list[str] | None = None,
    attachment_page_count: int = 0,
) -> JobView:
    paths = list(attachment_paths or [])
    filenames = list(attachment_filenames or [path.name for path in paths])
    if len(paths) != len(filenames):
        raise HTTPException(status_code=422, detail="二次输入文件信息无效。")

    if not record["use_ai"]:
        raise HTTPException(
            status_code=503,
            detail="二次输入路由必须由模型判断；当前任务未启用 AI。",
        )
    try:
        decision = await classify_refinement(
            current_result=result,
            instruction=instruction,
            attachment_paths=paths,
            attachment_filenames=filenames,
            model=(
                settings.qwen_vision_model.strip()
                or record["model"]
            ),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"二次输入路由模型调用失败：{exc}",
        ) from exc

    route = decision.route
    source_path = Path(record["source_path"])
    source_paths = [
        Path(path)
        for path in record.get("manifest", {}).get("source_paths", [])
        if isinstance(path, str)
    ] or [source_path]
    source_filenames = list(
        record.get("manifest", {}).get("filenames") or [record["filename"]]
    )
    record_source_path = record["source_path"]
    record_filename = record["filename"]

    if route in {"new_graph", "merge_graph"}:
        if paths:
            source_paths = paths
            source_filenames = filenames
            record_source_path = str(paths[0])
            record_filename = " & ".join(filenames[:2]) + (
                f" 等{len(filenames)}份文档" if len(filenames) > 2 else ""
            )
        if not source_paths or not all(path.is_file() for path in source_paths):
            raise HTTPException(
                status_code=410,
                detail="新一轮完整生成缺少可用的课件文件。",
            )

    manifest = queue_refinement_manifest(
        record.get("manifest", {}),
        instruction=instruction,
        current_graph_version=result.graph_version,
    )
    manifest.update(
        {
            "refinement_route": route,
            "refinement_rationale": decision.rationale,
            "guidance_image_paths": [],
        }
    )
    manifest.pop("completed_graph_asset", None)

    if route == "guidance_only":
        guidance_image_paths = await asyncio.to_thread(
            materialize_guidance_images,
            task_id=task_id,
            graph_version=result.graph_version,
            current_result=result,
            attachment_paths=paths,
            attachment_filenames=filenames,
        )
        manifest["guidance_image_paths"] = [
            str(path) for path in guidance_image_paths
        ]
    else:
        manifest.update(
            {
                "source_paths": [str(path) for path in source_paths],
                "filenames": source_filenames,
                "multi_document": len(source_paths) > 1,
            }
        )
        if paths:
            manifest.update(
                {
                    "source_sha256": hashlib.sha256(
                        "::".join(attachment_digests or []).encode()
                    ).hexdigest(),
                    "source_size_bytes": sum(attachment_sizes or []),
                    "source_filename": record_filename,
                    "source_page_count": attachment_page_count or None,
                }
            )
        if route == "merge_graph":
            manifest["completed_graph_asset"] = completed_graph_asset(result)

    blackboard.upsert_job(
        task_id=task_id,
        status="queued",
        stage="queued",
        progress=0,
        message="二次输入已分类，等待处理",
        mode=record["mode"],
        source_path=record_source_path,
        filename=record_filename,
        model=record["model"],
        provider=record["provider"],
        use_ai=record["use_ai"],
        owner_id=record["owner_id"],
        error=None,
        manifest=manifest,
    )
    await job_events.drop(task_id)
    queued = blackboard.load_job(task_id, owner_id=record["owner_id"])
    with jobs_lock:
        jobs[task_id] = _job_view_from_record(queued, result=result)
    await job_events.publish(
        task_id,
        "status",
        stage="queued",
        progress=0,
        message="二次输入已分类，等待处理",
    )
    _schedule_job(queued)
    return _job_view_from_record(queued, result=result)


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
        return await _queue_classified_refinement(
            task_id=task_id,
            record=record,
            result=result,
            instruction=request.instruction,
        )


@app.post(
    "/api/jobs/{task_id}/refine-with-files",
    response_model=JobView,
    include_in_schema=False,
)
async def refine_job_with_files(
    task_id: str,
    instruction: str = Form(...),
    expected_graph_version: int = Form(...),
    files: list[UploadFile] | None = File(default=None),
    principal: Principal = Depends(require_api_principal),
):
    try:
        request = JobRefinementRequest(
            instruction=instruction,
            expected_graph_version=expected_graph_version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raw_uploads = [
        upload
        for upload in (files or [])
        if upload and getattr(upload, "filename", None)
    ]
    if not raw_uploads:
        raise HTTPException(status_code=400, detail="请附加至少一份二次输入文件。")

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
        (
            attachment_paths,
            attachment_filenames,
            attachment_sizes,
            attachment_digests,
            attachment_page_count,
        ) = await _save_job_uploads(
            task_id=f"{task_id}_refinement_{uuid.uuid4().hex[:8]}",
            uploads=raw_uploads,
            allowed_suffixes=REFINEMENT_UPLOAD_SUFFIXES,
        )
        return await _queue_classified_refinement(
            task_id=task_id,
            record=record,
            result=result,
            instruction=request.instruction,
            attachment_paths=attachment_paths,
            attachment_filenames=attachment_filenames,
            attachment_sizes=attachment_sizes,
            attachment_digests=attachment_digests,
            attachment_page_count=attachment_page_count,
        )


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
    v: int | None = None,
    principal: Principal = Depends(require_api_principal),
):
    owner_id = _owner_scope(principal)
    result = (
        blackboard.load_graph_version(task_id, v, owner_id=owner_id)
        if v is not None
        else blackboard.load_latest_result(task_id, owner_id=owner_id)
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
        "architecture": EDITORIAL_PPT_ARCHITECTURE_NAME,
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
