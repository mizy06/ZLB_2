from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import statistics
import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from PIL import Image

from backend.app.agents import (
    QWEN_LOW_REASONING_TOKEN_RESERVE,
    RoleRuntime,
)
from backend.app.blackboard import SQLiteBlackboard
from backend.app.config import (
    Settings,
    settings,
    validate_production_qwen_configuration,
)
from backend.app.document_parser import parse_document
from backend.app.mindmap_engine.schemas import RenderedPage, RenderResponse
from backend.app.model_provider import ModelCallContext, model_call_context
from backend.app.pdf_layout_knowledge import (
    PAGE_LAYOUT_MAX_OUTPUT_TOKENS,
    PAGE_LAYOUT_NODE_MAX_OUTPUT_TOKENS,
    PAGE_LAYOUT_NODE_REASONING_TOKEN_RESERVE,
    PAGE_LAYOUT_RETRY_TIMEOUT_SECONDS,
    PAGE_LAYOUT_NODE_SCHEMA_VERSION,
    PAGE_LAYOUT_SCHEMA_VERSION,
    PAGE_LAYOUT_TIMEOUT_SECONDS,
)
from backend.app.pdf_page_knowledge import (
    PAGE_KNOWLEDGE_MAX_COMPLETION_TOKENS,
    PAGE_KNOWLEDGE_SCHEMA_VERSION,
    PAGE_KNOWLEDGE_THINKING_BUDGET,
    PAGE_KNOWLEDGE_TIMEOUT_SECONDS,
    PDF_PAGE_KNOWLEDGE_PROMPT_SHA256,
    extract_pdf_page_knowledge,
)
from backend.app.qwen_provider import QwenClient
from backend.app.runtime_manifest import runtime_versions, sanitize_endpoint
from backend.app.schemas import ParsedDocument, SourceBlock


class _RecordingQwenClient(QwenClient):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.payloads: list[dict[str, Any]] = []

    async def complete_multimodal_json(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]:
        user_prompt = str(kwargs.get("user_prompt") or "")
        page_match = re.search(r"提取第\s*(\d+)\s*页", user_prompt)
        attempt_match = re.search(r"第\s*(\d+)\s*次独立尝试", user_prompt)
        record = {
            "mapped_page": int(page_match.group(1)) if page_match else None,
            "attempt": (
                int(attempt_match.group(1)) if attempt_match else None
            ),
        }
        try:
            payload = await super().complete_multimodal_json(**kwargs)
        except Exception as exc:
            self.payloads.append(
                {
                    **record,
                    "error_type": type(exc).__name__,
                }
            )
            raise
        self.payloads.append({**record, "payload": payload})
        return payload


def _validate_canary_runtime_settings(configured: Settings) -> None:
    if not configured.production:
        raise RuntimeError(
            "Formal PDF canary requires MINDMAP_ENV=production."
        )
    validate_production_qwen_configuration(configured)


def _parse_pages(value: str) -> tuple[int, ...]:
    pages: list[int] = []
    for item in value.split(","):
        text = item.strip()
        if not text:
            continue
        try:
            page = int(text)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"invalid page number: {text}"
            ) from exc
        if page < 1:
            raise argparse.ArgumentTypeError("page numbers must be positive")
        if page in pages:
            raise argparse.ArgumentTypeError(
                f"duplicate page number: {page}"
            )
        pages.append(page)
    if not pages:
        raise argparse.ArgumentTypeError("at least one page is required")
    return tuple(pages)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    rank = max(math.ceil(percentile * len(ordered)) - 1, 0)
    return round(ordered[min(rank, len(ordered) - 1)], 3)


def _remap_document(
    source: ParsedDocument,
    original_pages: Sequence[int],
) -> tuple[ParsedDocument, dict[int, int], dict[int, int]]:
    original_to_mapped = {
        original_page: index
        for index, original_page in enumerate(original_pages, start=1)
    }
    mapped_to_original = {
        mapped_page: original_page
        for original_page, mapped_page in original_to_mapped.items()
    }
    blocks = [
        SourceBlock(
            text=block.text,
            page=original_to_mapped[block.page],
            heading=block.heading,
        )
        for block in source.blocks
        if block.page in original_to_mapped
    ]
    remapped = source.model_copy(
        update={
            "blocks": blocks,
            "warnings": [],
            "parse_metadata": {
                "pdf_page_count": len(original_pages),
                "source_pdf_page_count": source.parse_metadata.get(
                    "pdf_page_count"
                ),
                "pdf_geometry_math": source.parse_metadata.get(
                    "pdf_geometry_math",
                    {},
                ),
                "original_page_map": {
                    str(mapped): original
                    for mapped, original in mapped_to_original.items()
                },
            },
        }
    )
    return remapped, original_to_mapped, mapped_to_original


def _prepare_render(
    *,
    image_dir: Path,
    data_root: Path,
    original_pages: Sequence[int],
    render_id: str,
) -> RenderResponse:
    destination = data_root / "assets" / render_id
    destination.mkdir(parents=True, exist_ok=True)
    pages: list[RenderedPage] = []
    for mapped_page, original_page in enumerate(original_pages, start=1):
        source = image_dir / f"page_{original_page:04d}.png"
        if not source.is_file():
            raise FileNotFoundError(
                f"rendered source page is missing: {source}"
            )
        filename = f"page_{mapped_page:04d}.png"
        target = destination / filename
        shutil.copy2(source, target)
        with Image.open(target) as image:
            width, height = image.size
        pages.append(
            RenderedPage(
                asset_id=f"{render_id}:page:{mapped_page:04d}",
                render_id=render_id,
                filename=filename,
                url=f"/assets/{render_id}/{filename}",
                page=mapped_page,
                width=width,
                height=height,
            )
        )
    return RenderResponse(
        render_id=render_id,
        filename="canary.pdf",
        pages=pages,
        native_visuals=[],
    )


def _usage_totals(model_calls: Sequence[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for call in model_calls:
        usage = call.get("details", {}).get("usage", {})
        if not isinstance(usage, dict):
            continue
        for key, value in usage.items():
            if (
                isinstance(key, str)
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
            ):
                totals[key] = totals.get(key, 0.0) + float(value)
    return {
        key: int(value) if value.is_integer() else round(value, 3)
        for key, value in sorted(totals.items())
    }


def _model_call_summary(
    model_calls: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    latencies = [
        float(call["latency_ms"]) / 1000
        for call in model_calls
        if isinstance(call.get("latency_ms"), (int, float))
    ]
    expected_direct_policy = {
        "max_completion_tokens": PAGE_KNOWLEDGE_MAX_COMPLETION_TOKENS,
        "thinking_budget": PAGE_KNOWLEDGE_THINKING_BUDGET,
        "timeout_seconds": PAGE_KNOWLEDGE_TIMEOUT_SECONDS,
    }
    expected_policies = {
        "page_knowledge": expected_direct_policy,
        "page_layout": {
            "max_completion_tokens": (
                PAGE_LAYOUT_MAX_OUTPUT_TOKENS
                + QWEN_LOW_REASONING_TOKEN_RESERVE
            ),
            "thinking_budget": QWEN_LOW_REASONING_TOKEN_RESERVE,
            "timeout_seconds": [
                PAGE_LAYOUT_TIMEOUT_SECONDS,
                PAGE_LAYOUT_RETRY_TIMEOUT_SECONDS,
            ],
        },
        "page_layout_nodes": {
            "max_completion_tokens": (
                PAGE_LAYOUT_NODE_MAX_OUTPUT_TOKENS
                + PAGE_LAYOUT_NODE_REASONING_TOKEN_RESERVE
            ),
            "thinking_budget": PAGE_LAYOUT_NODE_REASONING_TOKEN_RESERVE,
            "timeout_seconds": PAGE_LAYOUT_TIMEOUT_SECONDS,
        },
    }

    def policy_contract(role: str) -> dict[str, Any] | None:
        if role == "page_layout_nodes":
            return expected_policies["page_layout_nodes"]
        if role.startswith("page_layout_"):
            return expected_policies["page_layout"]
        if not role or role == "page_knowledge":
            return expected_direct_policy
        return None

    def policy_matches(
        policy: dict[str, Any],
        expected: dict[str, Any] | None,
    ) -> bool:
        if expected is None:
            return False
        for key, expected_value in expected.items():
            actual = policy.get(key)
            if isinstance(expected_value, list):
                if actual not in expected_value:
                    return False
            elif actual != expected_value:
                return False
        return True

    policy_rows: list[tuple[str, dict[str, Any], bool]] = []
    for call in model_calls:
        policy = call.get("details", {}).get("request_policy", {})
        if not policy:
            continue
        role = str(call.get("role") or "")
        policy_rows.append(
            (
                role or "page_knowledge",
                policy,
                policy_matches(policy, policy_contract(role)),
            )
        )
    policy_by_role: dict[str, dict[str, Any]] = {}
    for role in sorted({row[0] for row in policy_rows}):
        role_rows = [row for row in policy_rows if row[0] == role]
        policy_by_role[role] = {
            "call_count": len(role_rows),
            "expected": policy_contract(role),
            "all_match": all(row[2] for row in role_rows),
        }
    finish_reasons = Counter(
        str(call.get("details", {}).get("finish_reason"))
        for call in model_calls
        if call.get("details", {}).get("finish_reason")
    )
    status_counts = Counter(
        str(call.get("status") or "unknown")
        for call in model_calls
    )
    return {
        "call_count": len(model_calls),
        "status_counts": dict(sorted(status_counts.items())),
        "latency_seconds": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": round(max(latencies), 3) if latencies else 0.0,
            "mean": (
                round(statistics.fmean(latencies), 3)
                if latencies
                else 0.0
            ),
        },
        "usage": _usage_totals(model_calls),
        "finish_reason_counts": dict(sorted(finish_reasons.items())),
        "expected_request_policy": expected_direct_policy,
        "expected_request_policies": expected_policies,
        "request_policy_count": len(policy_rows),
        "request_policy_all_match": (
            bool(policy_rows) and all(row[2] for row in policy_rows)
        ),
        "request_policy_by_role": policy_by_role,
        "calls": [
            {
                "item_id": call.get("item_id"),
                "role": call.get("role"),
                "status": call.get("status"),
                "latency_ms": call.get("latency_ms"),
                "input_unit_ids": call.get("input_unit_ids", []),
                "usage": call.get("details", {}).get("usage", {}),
                "finish_reason": call.get("details", {}).get(
                    "finish_reason"
                ),
                "request_policy": call.get("details", {}).get(
                    "request_policy", {}
                ),
                "status_code": call.get("details", {}).get("status_code"),
                "error_type": call.get("details", {}).get("error_type"),
                "error_code": call.get("details", {}).get("error_code"),
            }
            for call in model_calls
        ],
    }


def _canary_manifest(
    *,
    source_sha256: str,
    source_page_count: int,
    pages: Sequence[int],
    render_dpi: int,
    concurrency: int,
    max_attempts: int,
    min_confidence: float,
) -> dict[str, Any]:
    uses_layout_nodes = settings.pdf_page_extraction_mode in {
        "layout_nodes",
        "direct_layout_fallback",
    }
    return {
        "kind": "pdf_page_knowledge_canary",
        "source_sha256": source_sha256,
        "source_page_count": source_page_count,
        "image_digest": os.getenv("IMAGE_DIGEST", "unknown"),
        "git_sha": os.getenv("GIT_SHA", "unknown"),
        "provider": "qwen",
        "text_model": settings.qwen_model,
        "vision_model": settings.qwen_vision_model,
        "provider_endpoint": sanitize_endpoint(settings.qwen_base_url),
        "credential_source": settings.qwen_secret_source,
        "qwen_production_profile": settings.qwen_production_profile,
        "extraction_profile": settings.pdf_page_extraction_mode,
        "prompt": {
            "version": settings.pdf_page_knowledge_prompt_version,
            "sha256": PDF_PAGE_KNOWLEDGE_PROMPT_SHA256,
        },
        "runner": {
            "module": "backend.tools.pdf_page_knowledge_canary",
            "sha256": _sha256(Path(__file__).resolve()),
        },
        "schema_versions": {
            "page_knowledge": PAGE_KNOWLEDGE_SCHEMA_VERSION,
            "page_layout": (
                PAGE_LAYOUT_SCHEMA_VERSION if uses_layout_nodes else None
            ),
            "page_layout_nodes": (
                PAGE_LAYOUT_NODE_SCHEMA_VERSION
                if uses_layout_nodes
                else None
            ),
        },
        "original_pages": list(pages),
        "mapped_pages": list(range(1, len(pages) + 1)),
        "render_dpi": render_dpi,
        "concurrency": concurrency,
        "max_page_attempts": max_attempts,
        "min_confidence": min_confidence,
        "runtime_versions": dict(runtime_versions()),
    }


def _page_reports(
    *,
    result,
    checkpoints: Sequence[dict[str, Any]],
    mapped_to_original: dict[int, int],
) -> list[dict[str, Any]]:
    extractions = {item.page: item for item in result.extractions}
    degraded_pages = set(getattr(result, "degraded_pages", []))
    direct_checkpoint_by_page: dict[int, dict[str, Any]] = {}
    fallback_checkpoint_by_page: dict[int, dict[str, Any]] = {}
    for checkpoint in checkpoints:
        stage = str(checkpoint.get("stage") or "")
        if not stage.startswith("page_knowledge:"):
            continue
        try:
            mapped_page = int(stage.rsplit(":", 1)[-1])
        except ValueError:
            continue
        payload = checkpoint.get("payload")
        if not isinstance(payload, dict):
            continue
        if stage.startswith("page_knowledge:layout_nodes:"):
            fallback_checkpoint_by_page[mapped_page] = payload
        elif stage == f"page_knowledge:{mapped_page:04d}":
            direct_checkpoint_by_page[mapped_page] = payload

    pages: list[dict[str, Any]] = []
    for mapped_page, original_page in sorted(mapped_to_original.items()):
        extraction = extractions.get(mapped_page)
        direct_checkpoint = direct_checkpoint_by_page.get(mapped_page, {})
        fallback_checkpoint = fallback_checkpoint_by_page.get(
            mapped_page,
            {},
        )
        checkpoint = fallback_checkpoint or direct_checkpoint
        best_partial = checkpoint.get("best_partial")
        if not isinstance(best_partial, dict):
            best_partial = {}
        pages.append(
            {
                "original_page": original_page,
                "mapped_page": mapped_page,
                "status": (
                    "degraded"
                    if extraction is not None
                    and mapped_page in degraded_pages
                    else "accepted"
                    if extraction is not None
                    else checkpoint.get("status", "missing")
                ),
                "direct_status": direct_checkpoint.get(
                    "status",
                    "missing",
                ),
                "fallback_attempted": bool(fallback_checkpoint),
                "fallback_status": fallback_checkpoint.get(
                    "status",
                    "not_attempted",
                ),
                "attempts": checkpoint.get(
                    "attempt", checkpoint.get("attempts", 0)
                ),
                "issues": checkpoint.get("issues", []),
                "terminal_issues": checkpoint.get(
                    "terminal_issues", []
                ),
                "unresolved_node_count": checkpoint.get(
                    "unresolved_node_count", 0
                ),
                "unresolved_temp_ids": checkpoint.get(
                    "unresolved_temp_ids", []
                ),
                "anonymous_unresolved_node_count": checkpoint.get(
                    "anonymous_unresolved_node_count", 0
                ),
                "discarded_temp_ids": checkpoint.get(
                    "discarded_temp_ids", []
                ),
                "discarded_node_count": checkpoint.get(
                    "discarded_node_count", 0
                ),
                "no_knowledge_consensus_attempts": checkpoint.get(
                    "no_knowledge_consensus_attempts", 0
                ),
                "best_partial_node_count": len(
                    best_partial.get("nodes", [])
                ),
                "heading": extraction.heading if extraction else "",
                "has_knowledge": (
                    extraction.has_knowledge if extraction else None
                ),
                "no_knowledge_reason": (
                    extraction.no_knowledge_reason if extraction else ""
                ),
                "confidence": (
                    extraction.confidence if extraction else None
                ),
                "nodes": [
                    node.model_dump(mode="json")
                    for node in extraction.nodes
                ]
                if extraction
                else best_partial.get("nodes", []),
            }
        )
    return pages


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    _validate_canary_runtime_settings(settings)
    source_pdf = args.pdf.resolve()
    image_dir = args.image_dir.resolve()
    data_root = args.data_root.resolve()
    output = args.output.resolve()
    if not source_pdf.is_file():
        raise FileNotFoundError(f"source PDF is missing: {source_pdf}")
    if not image_dir.is_dir():
        raise FileNotFoundError(f"image directory is missing: {image_dir}")
    if not settings.key_configured:
        raise RuntimeError(
            settings.qwen_secret_error or "Qwen credential is unavailable"
        )

    source_document = await asyncio.to_thread(
        parse_document,
        source_pdf,
        source_pdf.name,
    )
    source_page_count = int(
        source_document.parse_metadata.get("pdf_page_count") or 0
    )
    invalid_pages = [
        page for page in args.pages if page > source_page_count
    ]
    if invalid_pages:
        raise ValueError(
            "pages exceed source PDF page count: "
            + ",".join(str(page) for page in invalid_pages)
        )

    document, _original_to_mapped, mapped_to_original = _remap_document(
        source_document,
        args.pages,
    )
    source_sha256 = await asyncio.to_thread(_sha256, source_pdf)
    render_id = (
        "v39-production-canary-"
        + hashlib.sha256(
            (
                source_sha256
                + ":"
                + ",".join(str(page) for page in args.pages)
            ).encode("ascii")
        ).hexdigest()[:16]
    )
    rendered = await asyncio.to_thread(
        _prepare_render,
        image_dir=image_dir,
        data_root=data_root,
        original_pages=args.pages,
        render_id=render_id,
    )

    blackboard = SQLiteBlackboard(data_root / "canary-blackboard.sqlite3")
    run_id = f"run_canary_{uuid.uuid4().hex[:16]}"
    task_id = f"task_canary_{uuid.uuid4().hex[:16]}"
    manifest = _canary_manifest(
        source_sha256=source_sha256,
        source_page_count=source_page_count,
        pages=args.pages,
        render_dpi=args.render_dpi,
        concurrency=args.concurrency,
        max_attempts=args.max_attempts,
        min_confidence=args.min_confidence,
    )
    blackboard.start_run(
        run_id=run_id,
        task_id=task_id,
        mode="precision",
        document_id=document.document_id,
        manifest=manifest,
    )
    client = (
        _RecordingQwenClient(settings)
        if args.capture_payloads
        else QwenClient(settings)
    )
    runtime = RoleRuntime(
        provider="qwen",
        model=settings.qwen_vision_model,
        client=client,
        available=settings.key_configured,
        unavailable_reason=settings.qwen_secret_error,
    )
    started = time.perf_counter()
    try:
        context = ModelCallContext(
            run_id=run_id,
            recorder=blackboard.record_model_call,
            role="pdf_page_knowledge_canary",
        )
        with model_call_context(context):
            result = await extract_pdf_page_knowledge(
                document=document,
                rendered=rendered,
                runtime=runtime,
                data_root=data_root,
                checkpoint_store=blackboard,
                run_id=run_id,
                source_sha256=source_sha256,
                prompt_version=settings.pdf_page_knowledge_prompt_version,
                render_dpi=args.render_dpi,
                min_confidence=args.min_confidence,
                concurrency=args.concurrency,
                max_page_attempts=args.max_attempts,
                extraction_profile=settings.pdf_page_extraction_mode,
            )
    finally:
        await QwenClient.close_shared_clients()
    elapsed = round(time.perf_counter() - started, 3)
    blackboard.update_run(
        run_id,
        status="completed" if result.complete else "failed",
        stage="page_knowledge_canary",
        degraded_components=[] if result.complete else ["pdf_page_knowledge"],
    )

    model_calls = blackboard.list_model_calls(run_id)
    checkpoints = blackboard.list_checkpoints(run_id)
    page_reports = _page_reports(
        result=result,
        checkpoints=checkpoints,
        mapped_to_original=mapped_to_original,
    )
    accepted_original_pages = [
        mapped_to_original[page] for page in result.accepted_pages
    ]
    degraded_original_pages = [
        mapped_to_original[page] for page in result.degraded_pages
    ]
    clean_accepted_original_pages = sorted(
        set(accepted_original_pages) - set(degraded_original_pages)
    )
    failed_original_pages = [
        mapped_to_original[page] for page in result.failed_pages
    ]
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "task_id": task_id,
        "manifest": manifest,
        "image_digest": os.getenv("IMAGE_DIGEST", ""),
        "git_sha": os.getenv("GIT_SHA", ""),
        "source_sha256": source_sha256,
        "source_page_count": source_page_count,
        "selected_original_pages": list(args.pages),
        "mapped_page_count": len(args.pages),
        "provider": "qwen",
        "provider_endpoint": manifest["provider_endpoint"],
        "text_model": settings.qwen_model,
        "vision_model": settings.qwen_vision_model,
        "model": settings.qwen_vision_model,
        "qwen_production_profile": settings.qwen_production_profile,
        "extraction_profile": settings.pdf_page_extraction_mode,
        "prompt_version": settings.pdf_page_knowledge_prompt_version,
        "render_dpi": args.render_dpi,
        "concurrency": args.concurrency,
        "max_attempts": args.max_attempts,
        "min_confidence": args.min_confidence,
        "runtime_versions": manifest["runtime_versions"],
        "complete": result.complete,
        "elapsed_seconds": elapsed,
        "accepted_original_pages": accepted_original_pages,
        "clean_accepted_original_pages": clean_accepted_original_pages,
        "degraded_original_pages": degraded_original_pages,
        "failed_original_pages": failed_original_pages,
        "accepted_page_count": len(accepted_original_pages),
        "clean_accepted_page_count": len(clean_accepted_original_pages),
        "degraded_page_count": len(degraded_original_pages),
        "failed_page_count": len(failed_original_pages),
        "node_count": len(result.node_candidates),
        "warnings": result.warnings,
        "profile_metadata": result.document.parse_metadata.get(
            "pdf_page_knowledge",
            {},
        ),
        "model_calls": _model_call_summary(model_calls),
        "pages": page_reports,
    }
    if isinstance(client, _RecordingQwenClient):
        report["raw_attempts"] = client.payloads
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run selected PDF pages through the production page knowledge "
            "extractor with fresh checkpoints."
        )
    )
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--image-dir", type=Path, required=True)
    parser.add_argument("--pages", type=_parse_pages, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--min-confidence", type=float, default=0.85)
    parser.add_argument("--render-dpi", type=int, default=192)
    parser.add_argument("--capture-payloads", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = asyncio.run(_run(args))
    print(
        json.dumps(
            {
                "complete": report["complete"],
                "accepted_page_count": report["accepted_page_count"],
                "failed_original_pages": report["failed_original_pages"],
                "elapsed_seconds": report["elapsed_seconds"],
                "report": str(args.output.resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
