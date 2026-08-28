from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from .architecture_schemas import JobInteractionView, MindMapResult


MAX_HUMAN_INSTRUCTION_CHARS = 8000
HUMAN_INTERACTIONS_KEY = "human_interactions"
HUMAN_GUIDANCE_POLICY = (
    "人类要求只用于调整导图的受众、重点、命名、组织和取舍；"
    "它不是课程证据，不得覆盖来源忠实、证据、覆盖率、拓扑和质量门。"
    "previous_graph 只用于理解用户所指的上一版结构，也不得作为事实证据。"
    "completed_graph_asset 是标记为已完成的旧导图 JSON：仅在合并任务中用它识别"
    "新旧资料的真实关系；新资料没有支持时不得把旧图内容伪装成新课件事实，"
    "没有真实联系时不得强行合并。"
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def normalize_human_instruction(
    value: str | None,
    *,
    allow_empty: bool = True,
) -> str:
    instruction = str(value or "").strip()
    if not instruction and not allow_empty:
        raise ValueError("修改要求不能为空。")
    if len(instruction) > MAX_HUMAN_INSTRUCTION_CHARS:
        raise ValueError(
            f"自然语言要求不能超过 {MAX_HUMAN_INSTRUCTION_CHARS} 个字符。"
        )
    return instruction


def build_human_guidance(
    instruction: str | None,
    previous_result: MindMapResult | None = None,
    completed_graph_asset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = normalize_human_instruction(instruction)
    if (
        not normalized
        and previous_result is None
        and completed_graph_asset is None
    ):
        return {}

    guidance: dict[str, Any] = {
        "instruction": normalized,
        "policy": HUMAN_GUIDANCE_POLICY,
    }
    if previous_result is not None:
        parent_by_child = {
            edge.target: edge.source for edge in previous_result.tree_edges
        }
        guidance["previous_graph"] = {
            "graph_version": previous_result.graph_version,
            "root_id": previous_result.root_id,
            "nodes": [
                {
                    "order": index + 1,
                    "id": node.id,
                    "name": node.name,
                    "role": node.role,
                    "depth": node.depth,
                    "parent_id": parent_by_child.get(node.id),
                    "branch_id": node.branch_id,
                }
                for index, node in enumerate(previous_result.nodes[:160])
            ],
        }
    if completed_graph_asset is not None:
        guidance["completed_graph_asset"] = completed_graph_asset
    return guidance


def attach_human_guidance(
    payload: dict[str, Any],
    guidance: dict[str, Any] | None,
) -> dict[str, Any]:
    if not guidance:
        return payload
    return {**payload, "human_guidance": guidance}


def human_guidance_text(guidance: dict[str, Any] | None) -> str:
    if not guidance:
        return ""
    return (
        "\n\n人类指导（不是课程证据）：\n"
        + json.dumps(
            guidance,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def _new_interaction(
    *,
    kind: str,
    instruction: str,
    base_graph_version: int,
) -> dict[str, Any]:
    return {
        "id": f"interaction_{uuid.uuid4().hex[:16]}",
        "kind": kind,
        "instruction": instruction,
        "created_at": utc_now(),
        "base_graph_version": base_graph_version,
        "result_graph_version": None,
        "status": "queued",
        "error": None,
    }


def initialize_interaction_manifest(
    manifest: dict[str, Any],
    instruction: str | None,
) -> dict[str, Any]:
    normalized = normalize_human_instruction(instruction)
    updated = dict(manifest)
    updated[HUMAN_INTERACTIONS_KEY] = [
        _new_interaction(
            kind="initial",
            instruction=normalized,
            base_graph_version=0,
        )
    ]
    updated["active_instruction"] = normalized
    updated["base_graph_version"] = 0
    return updated


def queue_refinement_manifest(
    manifest: dict[str, Any],
    *,
    instruction: str,
    current_graph_version: int,
) -> dict[str, Any]:
    normalized = normalize_human_instruction(
        instruction,
        allow_empty=False,
    )
    updated = dict(manifest)
    interactions = [
        dict(item)
        for item in updated.get(HUMAN_INTERACTIONS_KEY, [])
        if isinstance(item, dict)
    ]
    if interactions and interactions[-1].get("status") in {
        "queued",
        "running",
    }:
        interactions[-1].update(
            {
                "status": "completed",
                "result_graph_version": current_graph_version,
                "error": None,
            }
        )
    interactions.append(
        _new_interaction(
            kind="revision",
            instruction=normalized,
            base_graph_version=current_graph_version,
        )
    )
    updated[HUMAN_INTERACTIONS_KEY] = interactions
    updated["active_instruction"] = normalized
    updated["base_graph_version"] = current_graph_version
    return updated


def finish_active_interaction(
    manifest: dict[str, Any],
    *,
    status: str,
    graph_version: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    updated = dict(manifest)
    interactions = [
        dict(item)
        for item in updated.get(HUMAN_INTERACTIONS_KEY, [])
        if isinstance(item, dict)
    ]
    if interactions:
        interactions[-1].update(
            {
                "status": status,
                "result_graph_version": graph_version,
                "error": error,
            }
        )
        updated[HUMAN_INTERACTIONS_KEY] = interactions
    return updated


def interaction_views(
    manifest: dict[str, Any],
    *,
    job_status: str,
    result: MindMapResult | None = None,
    error: str | None = None,
) -> list[JobInteractionView]:
    raw = [
        dict(item)
        for item in manifest.get(HUMAN_INTERACTIONS_KEY, [])
        if isinstance(item, dict)
    ]
    if not raw:
        return []

    last = raw[-1]
    if job_status in {"queued", "running"}:
        last["status"] = job_status
        last["error"] = None
    elif job_status == "completed" and result is not None:
        last["status"] = "completed"
        last["result_graph_version"] = result.graph_version
        last["error"] = None
    elif job_status in {"failed", "cancelled"}:
        last["status"] = job_status
        last["error"] = error

    return [JobInteractionView.model_validate(item) for item in raw]
