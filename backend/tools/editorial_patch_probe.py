from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import sqlite3
import statistics
import time
from pathlib import Path
from typing import Annotated, Any, Literal, Sequence

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from backend.app.config import settings
from backend.app.editorial_ppt_pipeline import (
    EditorialBrief,
    EditorialIssueDecision,
    EditorialMindMap,
    EditorialReviewIssue,
    EditorialReviewReport,
    _review_user_prompt,
    _select_revision_images,
    _validate_mindmap,
    _validate_review_report,
)
from backend.app.editorial_ppt_prompts import (
    CONTENT_OMISSION_REVIEWER_PROMPT,
    MULTILEVEL_STRUCTURE_REVIEWER_PROMPT,
    PRUNING_REVIEWER_PROMPT,
)
from backend.app.mindmap_engine.schemas import RenderResponse
from backend.app.model_provider import ModelCallContext, model_call_context
from backend.app.qwen_provider import QwenClient
from backend.app.single_shot_ppt_pipeline import SingleShotNode, _encode_slide_images


DEFAULT_RUN_ID = "run_5f12cf210eb1465b"
DEFAULT_BLACKBOARD = Path(
    "/var/lib/docker/volumes/"
    "zlb-mindmap-single-shot-data/_data/blackboard.sqlite3"
)
DEFAULT_DATA_ROOT = Path(
    "/var/lib/docker/volumes/zlb-mindmap-single-shot-data/_data"
)
DEFAULT_MODEL = "qwen3.8-max-preview"
DEFAULT_OUTPUT_DIR = Path("/tmp/editorial-patch-probe")
PATCH_SYSTEM_PROMPT = """你是课程 PPT 思维导图的全局总编。你必须通过增量 Patch 修订当前导图，
不能返回或重写完整 mindmap。

你会收到当前导图、同一轮全部 blocker/major 审稿意见，以及与问题有关的原始幻灯片图片。
审稿人只有建议权；你要逐项裁决，并保持统一的编辑思路。

硬性规则：
1. 每个输入 issue_id 必须恰好返回一个 decision，不得遗漏、重复或新增 issue_id。
2. 只做解决问题所必需的最小修改。拒绝的问题可以没有对应操作。
3. operations 按给定顺序执行。只能使用 schema 中列出的操作，不能夹带完整图谱或任意字段。
4. update_node 只填写确实变化的字段；move_node 专门修改父边；节点 id 永远不可修改或复用。
5. delete_node 只能删除叶节点。若要删除非叶节点，必须先移动或删除其子节点。
6. position_node 只调整一个节点及其完整子树在同级中的位置。使用 first、last、
   before_sibling_id、after_sibling_id 四种锚点之一；锚点必须与目标具有同一父节点。
7. add_node 必须使用新的稳定 id，parent_id 必须指向执行到该步时已经存在的节点，且不能新增第二个根。
8. 内容遗漏可通过 add_node 或 update_node.definition 解决，不要求一律增加可见节点。
9. 剪枝优先合并或降级进 definition；只有明显不重要且不损害主线时才删除。
10. 所有事实和 source_slides 必须由所给 PPT 图片支持；不得猜测公式、条件、数值或因果关系。
11. 修订后必须保持恰好一个根、连通、无环，并遵守最大深度。未声明修改的节点必须原样保留。
12. 只输出符合 JSON Schema 的 JSON 对象，不要输出 Markdown、解释、完整 mindmap 或思维过程。"""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NodeChanges(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=96)
    role: Literal[
        "root",
        "topic",
        "concept",
        "definition",
        "principle",
        "formula",
        "step",
        "example",
        "warning",
        "visual",
    ] | None = None
    definition: str | None = Field(default=None, min_length=1, max_length=800)
    source_slides: list[int] | None = Field(
        default=None,
        min_length=1,
        max_length=150,
    )
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def require_change(self) -> "NodeChanges":
        if not self.model_dump(exclude_none=True):
            raise ValueError("update_node requires at least one changed field")
        return self


class BriefChanges(StrictModel):
    learning_goal: str | None = Field(default=None, min_length=4, max_length=800)
    audience: str | None = Field(default=None, min_length=2, max_length=240)
    organizing_principle: str | None = Field(
        default=None,
        min_length=4,
        max_length=800,
    )
    level_semantics: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=8,
    )
    importance_policy: str | None = Field(
        default=None,
        min_length=4,
        max_length=1000,
    )
    pruning_policy: str | None = Field(
        default=None,
        min_length=4,
        max_length=1000,
    )

    @model_validator(mode="after")
    def require_change(self) -> "BriefChanges":
        if not self.model_dump(exclude_none=True):
            raise ValueError("update_brief requires at least one changed field")
        return self


class AddNode(StrictModel):
    op: Literal["add_node"]
    node: SingleShotNode


class UpdateNode(StrictModel):
    op: Literal["update_node"]
    target_id: str = Field(min_length=1, max_length=96)
    changes: NodeChanges


class DeleteNode(StrictModel):
    op: Literal["delete_node"]
    target_id: str = Field(min_length=1, max_length=96)


class MoveNode(StrictModel):
    op: Literal["move_node"]
    target_id: str = Field(min_length=1, max_length=96)
    new_parent_id: str = Field(min_length=1, max_length=96)


class PositionNode(StrictModel):
    op: Literal["position_node"]
    target_id: str = Field(min_length=1, max_length=96)
    position: Literal["first", "last"] | None = None
    before_sibling_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=96,
    )
    after_sibling_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=96,
    )

    @model_validator(mode="after")
    def require_one_anchor(self) -> "PositionNode":
        anchors = (
            self.position,
            self.before_sibling_id,
            self.after_sibling_id,
        )
        if sum(value is not None for value in anchors) != 1:
            raise ValueError("position_node requires exactly one position anchor")
        return self


class UpdateBrief(StrictModel):
    op: Literal["update_brief"]
    changes: BriefChanges


PatchOperation = Annotated[
    AddNode
    | UpdateNode
    | DeleteNode
    | MoveNode
    | PositionNode
    | UpdateBrief,
    Field(discriminator="op"),
]
class EditorialPatch(StrictModel):
    decisions: list[EditorialIssueDecision] = Field(min_length=1, max_length=48)
    operations: list[PatchOperation] = Field(default_factory=list, max_length=64)


class PatchApplicationError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _operation_target(operation: PatchOperation) -> str:
    if isinstance(operation, AddNode):
        return operation.node.id
    if isinstance(operation, UpdateBrief):
        return "$editorial_brief"
    return operation.target_id


def validate_decision_coverage(
    patch: EditorialPatch,
    issues: Sequence[EditorialReviewIssue],
) -> None:
    expected = [issue.id for issue in issues]
    actual = [decision.issue_id for decision in patch.decisions]
    if len(actual) != len(set(actual)):
        raise PatchApplicationError("patch contains duplicate issue decisions")
    if set(actual) != set(expected):
        raise PatchApplicationError(
            "patch decision coverage mismatch "
            f"(missing={sorted(set(expected) - set(actual))}, "
            f"extra={sorted(set(actual) - set(expected))})"
        )


def apply_patch_transactionally(
    current: EditorialMindMap,
    patch: EditorialPatch,
    *,
    slide_count: int,
    max_depth: int,
) -> EditorialMindMap:
    working = copy.deepcopy(current.model_dump(mode="json"))
    nodes: list[dict[str, Any]] = working["nodes"]

    def node_map() -> dict[str, dict[str, Any]]:
        return {str(node["id"]): node for node in nodes}

    def descendant_ids(root_id: str) -> set[str]:
        children_by_parent: dict[str, list[str]] = {}
        for node in nodes:
            parent_id = node["parent_id"]
            if parent_id is not None:
                children_by_parent.setdefault(str(parent_id), []).append(
                    str(node["id"])
                )
        descendants: set[str] = set()
        pending = list(children_by_parent.get(root_id, []))
        while pending:
            node_id = pending.pop()
            if node_id in descendants:
                continue
            descendants.add(node_id)
            pending.extend(children_by_parent.get(node_id, []))
        return descendants

    def subtree_block(root_id: str) -> list[dict[str, Any]]:
        subtree_ids = {root_id, *descendant_ids(root_id)}
        positions = [
            index
            for index, node in enumerate(nodes)
            if node["id"] in subtree_ids
        ]
        if not positions:
            raise PatchApplicationError(f"subtree root does not exist: {root_id}")
        expected = list(range(positions[0], positions[-1] + 1))
        if positions != expected or nodes[positions[0]]["id"] != root_id:
            raise PatchApplicationError(
                f"node order does not contain a contiguous subtree: {root_id}"
            )
        return nodes[positions[0] : positions[-1] + 1]

    def insertion_index_after_subtree(root_id: str) -> int:
        block_ids = {root_id, *descendant_ids(root_id)}
        positions = [
            index
            for index, node in enumerate(nodes)
            if node["id"] in block_ids
        ]
        if not positions:
            raise PatchApplicationError(f"parent does not exist: {root_id}")
        return positions[-1] + 1

    for index, operation in enumerate(patch.operations, start=1):
        by_id = node_map()
        try:
            if isinstance(operation, AddNode):
                node = operation.node.model_dump(mode="json")
                if node["id"] in by_id:
                    raise PatchApplicationError(
                        f"add_node id already exists: {node['id']}"
                    )
                if node["parent_id"] is None or node["role"] == "root":
                    raise PatchApplicationError(
                        "add_node cannot create another root"
                    )
                if node["parent_id"] not in by_id:
                    raise PatchApplicationError(
                        f"add_node parent does not exist: {node['parent_id']}"
                    )
                nodes.insert(
                    insertion_index_after_subtree(str(node["parent_id"])),
                    node,
                )
                continue

            if isinstance(operation, UpdateBrief):
                working["editorial_brief"].update(
                    operation.changes.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                )
                EditorialBrief.model_validate(working["editorial_brief"])
                continue

            target_id = operation.target_id
            target = by_id.get(target_id)
            if target is None:
                raise PatchApplicationError(
                    f"{operation.op} target does not exist: {target_id}"
                )

            if isinstance(operation, UpdateNode):
                changes = operation.changes.model_dump(
                    mode="json",
                    exclude_none=True,
                )
                if target["parent_id"] is None and changes.get("role") not in {
                    None,
                    "root",
                }:
                    raise PatchApplicationError(
                        "update_node cannot change the root to a non-root role"
                    )
                if target["parent_id"] is not None and changes.get("role") == "root":
                    raise PatchApplicationError(
                        "update_node cannot create another root role"
                    )
                target.update(changes)
                continue

            if isinstance(operation, DeleteNode):
                if target["parent_id"] is None:
                    raise PatchApplicationError("delete_node cannot delete root")
                children = [
                    node["id"]
                    for node in nodes
                    if node["parent_id"] == target_id
                ]
                if children:
                    raise PatchApplicationError(
                        f"delete_node target is not a leaf: {target_id}"
                    )
                nodes[:] = [node for node in nodes if node["id"] != target_id]
                continue

            if isinstance(operation, MoveNode):
                if target["parent_id"] is None:
                    raise PatchApplicationError("move_node cannot move root")
                if operation.new_parent_id not in by_id:
                    raise PatchApplicationError(
                        "move_node parent does not exist: "
                        + operation.new_parent_id
                    )
                if operation.new_parent_id == target_id:
                    raise PatchApplicationError(
                        "move_node cannot parent a node to itself"
                    )
                if operation.new_parent_id in descendant_ids(target_id):
                    raise PatchApplicationError(
                        "move_node cannot move a node below its descendant"
                    )
                if target["parent_id"] == operation.new_parent_id:
                    continue
                block = subtree_block(target_id)
                block_ids = {node["id"] for node in block}
                nodes[:] = [
                    node for node in nodes if node["id"] not in block_ids
                ]
                target["parent_id"] = operation.new_parent_id
                insert_at = insertion_index_after_subtree(
                    operation.new_parent_id
                )
                nodes[insert_at:insert_at] = block
                continue

            if isinstance(operation, PositionNode):
                parent_id = target["parent_id"]
                if parent_id is None:
                    raise PatchApplicationError(
                        "position_node cannot position root"
                    )
                block = subtree_block(target_id)
                block_ids = {node["id"] for node in block}
                nodes[:] = [
                    node for node in nodes if node["id"] not in block_ids
                ]
                remaining_by_id = node_map()
                if operation.position == "first":
                    insert_at = next(
                        index
                        for index, node in enumerate(nodes)
                        if node["id"] == parent_id
                    ) + 1
                elif operation.position == "last":
                    insert_at = insertion_index_after_subtree(parent_id)
                else:
                    sibling_id = (
                        operation.before_sibling_id
                        or operation.after_sibling_id
                    )
                    sibling = remaining_by_id.get(str(sibling_id))
                    if sibling is None:
                        raise PatchApplicationError(
                            f"position_node sibling does not exist: {sibling_id}"
                        )
                    if sibling["parent_id"] != parent_id:
                        raise PatchApplicationError(
                            "position_node anchor must share the target parent"
                        )
                    if operation.before_sibling_id is not None:
                        insert_at = next(
                            index
                            for index, node in enumerate(nodes)
                            if node["id"] == sibling_id
                        )
                    else:
                        insert_at = insertion_index_after_subtree(
                            str(sibling_id)
                        )
                nodes[insert_at:insert_at] = block
                continue

            raise PatchApplicationError(f"unsupported operation: {operation.op}")
        except (TypeError, ValueError) as exc:
            if isinstance(exc, PatchApplicationError):
                raise PatchApplicationError(
                    f"operation {index} failed: {exc}"
                ) from exc
            raise PatchApplicationError(
                f"operation {index} failed validation: {exc}"
            ) from exc

    try:
        revised = EditorialMindMap.model_validate(working)
        return _validate_mindmap(
            revised,
            slide_count=slide_count,
            max_depth=max_depth,
        )
    except ValueError as exc:
        raise PatchApplicationError(
            f"patched mindmap failed final validation: {exc}"
        ) from exc


def patch_locality(
    before: EditorialMindMap,
    after: EditorialMindMap,
    patch: EditorialPatch,
) -> dict[str, Any]:
    before_nodes = {
        node.id: node.model_dump(mode="json") for node in before.nodes
    }
    after_nodes = {
        node.id: node.model_dump(mode="json") for node in after.nodes
    }
    changed_existing = sorted(
        node_id
        for node_id in before_nodes.keys() & after_nodes.keys()
        if before_nodes[node_id] != after_nodes[node_id]
    )
    declared_mutations = {
        operation.target_id
        for operation in patch.operations
        if isinstance(operation, (UpdateNode, MoveNode))
    }
    undeclared_mutations = sorted(set(changed_existing) - declared_mutations)
    return {
        "added_node_ids": sorted(after_nodes.keys() - before_nodes.keys()),
        "deleted_node_ids": sorted(before_nodes.keys() - after_nodes.keys()),
        "changed_existing_node_ids": changed_existing,
        "undeclared_mutation_node_ids": undeclared_mutations,
        "untouched_nodes_preserved": not undeclared_mutations,
    }


def _load_checkpoint(
    connection: sqlite3.Connection,
    run_id: str,
    stage: str,
) -> Any:
    row = connection.execute(
        """
        SELECT payload_json
        FROM checkpoints
        WHERE run_id = ? AND stage = ?
        """,
        (run_id, stage),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"checkpoint not found: {run_id}/{stage}")
    return json.loads(row[0])


def load_fixture(
    blackboard_path: Path,
    run_id: str,
) -> tuple[str, EditorialMindMap, list[EditorialReviewIssue], RenderResponse]:
    connection = sqlite3.connect(blackboard_path)
    try:
        graph_payload = _load_checkpoint(
            connection,
            run_id,
            "editorial_graph_v1",
        )
        review_payload = _load_checkpoint(
            connection,
            run_id,
            "editorial_review_packet_1",
        )
        render_payload = _load_checkpoint(
            connection,
            run_id,
            "editorial_render",
        )
        row = connection.execute(
            """
            SELECT jobs.filename
            FROM runs
            JOIN jobs ON jobs.task_id = runs.task_id
            WHERE runs.run_id = ?
            """,
            (run_id,),
        ).fetchone()
    finally:
        connection.close()
    filename = str(row[0]) if row else f"{run_id}.pptx"
    graph = EditorialMindMap.model_validate(graph_payload)
    issues = [
        EditorialReviewIssue.model_validate(item)
        for item in review_payload["issues"]
        if item["severity"] in {"blocker", "major"}
    ]
    rendered = RenderResponse.model_validate(render_payload["rendered"])
    return filename, graph, issues, rendered


def _patch_user_prompt(
    *,
    filename: str,
    slide_count: int,
    max_depth: int,
    current: EditorialMindMap,
    issues: Sequence[EditorialReviewIssue],
) -> str:
    payload = {
        "filename": filename,
        "slide_count": slide_count,
        "max_depth": max_depth,
        "current_mindmap": current.model_dump(mode="json"),
        "blocking_review_issues": [
            issue.model_dump(mode="json") for issue in issues
        ],
    }
    schema = json.dumps(
        EditorialPatch.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        "图片标签与 source_slides 使用相同页码语义。请输出一次增量修订。\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + "\nJSON Schema："
        + schema
    )


def _usage_from_attempts(attempts: Sequence[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for attempt in attempts:
        usage = (attempt.get("details") or {}).get("usage") or {}
        for key, value in usage.items():
            if isinstance(value, (int, float)):
                totals[key] = totals.get(key, 0.0) + float(value)
    return totals


async def generate_patch(
    *,
    client: QwenClient,
    model: str,
    prompt: str,
    images: Sequence[tuple[str, str]],
    run_number: int,
    attempts: list[dict[str, Any]],
) -> tuple[EditorialPatch, float, int]:
    started = time.monotonic()
    with model_call_context(
        ModelCallContext(
            run_id=f"editorial_patch_probe_{run_number}",
            recorder=attempts.append,
            role="global_editor_patch_probe",
            stage=f"patch_probe_{run_number}",
            input_unit_ids=tuple(label for label, _ in images),
        )
    ):
        payload = await client.complete_multi_image_json(
            model=model,
            system_prompt=PATCH_SYSTEM_PROMPT,
            user_prompt=prompt,
            images=images,
            max_tokens=7000,
            max_completion_tokens=10072,
            max_attempts=1,
            thinking_budget=3072,
            timeout_seconds=360,
            accept_complete_json_on_length=True,
        )
    elapsed = time.monotonic() - started
    output_chars = len(_canonical(payload))
    return EditorialPatch.model_validate(payload), elapsed, output_chars


async def review_valid_patch(
    *,
    client: QwenClient,
    model: str,
    filename: str,
    images: Sequence[tuple[str, str]],
    current: EditorialMindMap,
    original_issues: Sequence[EditorialReviewIssue],
    decisions: Sequence[EditorialIssueDecision],
) -> dict[str, Any]:
    decision_by_id = {item.issue_id: item for item in decisions}
    role_specs = (
        (
            "content_omission",
            CONTENT_OMISSION_REVIEWER_PROMPT,
            True,
        ),
        ("pruning", PRUNING_REVIEWER_PROMPT, False),
        (
            "multilevel_structure",
            MULTILEVEL_STRUCTURE_REVIEWER_PROMPT,
            False,
        ),
    )

    async def run_role(
        role: Literal[
            "content_omission",
            "pruning",
            "multilevel_structure",
        ],
        system_prompt: str,
        use_images: bool,
    ) -> EditorialReviewReport:
        historical = [
            {
                "issue": issue.model_dump(mode="json"),
                "decision": (
                    decision_by_id[issue.id].model_dump(mode="json")
                    if issue.id in decision_by_id
                    else None
                ),
            }
            for issue in original_issues
        ]
        prompt = _review_user_prompt(
            filename=filename,
            slide_count=len(images),
            review_round=2,
            current=current,
            historical_review_items=historical,
        ) + "\n额外格式限制：summary 不超过 300 个汉字。"
        attempts: list[dict[str, Any]] = []
        with model_call_context(
            ModelCallContext(
                run_id="editorial_patch_probe_review",
                recorder=attempts.append,
                role=f"{role}_reviewer",
                stage=f"patch_probe_review_{role}",
                input_unit_ids=(
                    tuple(label for label, _ in images)
                    if use_images
                    else tuple(node.id for node in current.nodes)
                ),
            )
        ):
            if use_images:
                payload = await client.complete_multi_image_json(
                    model=model,
                    system_prompt=system_prompt,
                    user_prompt=prompt,
                    images=images,
                    cache_static_images=True,
                    max_tokens=9000,
                    max_completion_tokens=11048,
                    max_attempts=1,
                    thinking_budget=2048,
                    timeout_seconds=360,
                    accept_complete_json_on_length=True,
                )
            else:
                payload = await client.complete_json(
                    model=model,
                    system_prompt=system_prompt,
                    user_prompt=prompt,
                    max_tokens=9000,
                    max_completion_tokens=11048,
                    max_attempts=1,
                    thinking_budget=2048,
                    timeout_seconds=360,
                    accept_complete_json_on_length=True,
                )
        role_history = [
            issue
            for issue in original_issues
            if issue.id.startswith(f"{role}:")
        ]
        report = _validate_review_report(
            payload,
            expected_role=role,
            current=current,
            slide_count=len(images),
            historical_issues=role_history,
        )
        return report

    reports = await asyncio.gather(
        *(run_role(*spec) for spec in role_specs),
        return_exceptions=True,
    )
    valid_reports = [
        report
        for report in reports
        if isinstance(report, EditorialReviewReport)
    ]
    failures = [str(report) for report in reports if isinstance(report, Exception)]
    remaining = [
        issue
        for report in valid_reports
        for issue in report.issues
        if issue.severity in {"blocker", "major"}
    ]
    original_ids = {issue.id for issue in original_issues}
    remaining_ids = {issue.id for issue in remaining}
    return {
        "reviewer_failures": failures,
        "reports": [
            report.model_dump(mode="json") for report in valid_reports
        ],
        "remaining_blocker_major_count": len(remaining),
        "original_issue_ids_still_reported": sorted(
            original_ids & remaining_ids
        ),
        "new_blocker_major_ids": sorted(remaining_ids - original_ids),
    }


def _target_jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    return len(left & right) / len(left | right)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe whether Qwen can emit reliable transactional patches."
    )
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--blackboard", type=Path, default=DEFAULT_BLACKBOARD)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--max-depth", type=int, default=5)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--replay-dir",
        type=Path,
        help="Reapply previously generated run_N.json patches without regenerating.",
    )
    parser.add_argument(
        "--current-artifact",
        type=Path,
        help="Use patched_mindmap from an earlier run_N.json as current input.",
    )
    parser.add_argument(
        "--issues-summary",
        type=Path,
        help="Use blocker/major issues from an earlier summary semantic review.",
    )
    parser.add_argument(
        "--skip-review",
        action="store_true",
        help="Skip the three real reviewers after a valid patch is found.",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    if args.repetitions < 1:
        raise ValueError("--repetitions must be positive")
    if not settings.qwen_api_key:
        raise RuntimeError("Qwen is not configured in this process")

    filename, current, issues, rendered = load_fixture(
        args.blackboard,
        args.run_id,
    )
    if bool(args.current_artifact) != bool(args.issues_summary):
        raise ValueError(
            "--current-artifact and --issues-summary must be supplied together"
        )
    if args.current_artifact:
        current_payload = json.loads(
            args.current_artifact.read_text(encoding="utf-8")
        )
        current = EditorialMindMap.model_validate(
            current_payload["patched_mindmap"]
        )
        review_summary = json.loads(
            args.issues_summary.read_text(encoding="utf-8")
        )
        issues = [
            EditorialReviewIssue.model_validate(issue)
            for report in review_summary["semantic_review"]["reports"]
            for issue in report["issues"]
            if issue["severity"] in {"blocker", "major"}
        ]
    all_images = await asyncio.to_thread(
        _encode_slide_images,
        rendered,
        args.data_root,
        env_prefix="MINDMAP_EDITORIAL",
    )
    selected_images = _select_revision_images(
        all_images,
        current=current,
        issues=issues,
    )
    if not selected_images:
        selected_images = all_images
    prompt = _patch_user_prompt(
        filename=filename,
        slide_count=len(all_images),
        max_depth=args.max_depth,
        current=current,
        issues=issues,
    )
    client = QwenClient(settings)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    valid_outputs: list[tuple[EditorialPatch, EditorialMindMap]] = []

    print(
        f"fixture={filename} slides={len(all_images)} "
        f"issues={len(issues)} selected_images={len(selected_images)}"
    )
    for run_number in range(1, args.repetitions + 1):
        attempts: list[dict[str, Any]] = []
        patch: EditorialPatch | None = None
        result: dict[str, Any] = {
            "run_number": run_number,
            "schema_valid": False,
            "application_valid": False,
            "tree_valid": False,
            "rollback_preserved": True,
        }
        original_fingerprint = _fingerprint(current.model_dump(mode="json"))
        try:
            replay_metrics: dict[str, Any] = {}
            if args.replay_dir:
                replay_payload = json.loads(
                    (args.replay_dir / f"run_{run_number}.json").read_text(
                        encoding="utf-8"
                    )
                )
                patch = EditorialPatch.model_validate(replay_payload["patch"])
                replay_metrics = dict(replay_payload.get("metrics") or {})
                elapsed = float(replay_metrics.get("latency_seconds") or 0)
                output_chars = int(replay_metrics.get("output_chars") or 0)
            else:
                patch, elapsed, output_chars = await generate_patch(
                    client=client,
                    model=args.model,
                    prompt=prompt,
                    images=selected_images,
                    run_number=run_number,
                    attempts=attempts,
                )
            result.update(
                {
                    "schema_valid": True,
                    "replayed": bool(args.replay_dir),
                    "latency_seconds": round(elapsed, 3),
                    "output_chars": output_chars,
                    "operation_count": len(patch.operations),
                    "operation_types": [
                        operation.op for operation in patch.operations
                    ],
                    "operation_targets": [
                        _operation_target(operation)
                        for operation in patch.operations
                    ],
                    "decision_ids": [
                        decision.issue_id for decision in patch.decisions
                    ],
                    "usage": (
                        replay_metrics.get("usage", {})
                        if args.replay_dir
                        else _usage_from_attempts(attempts)
                    ),
                }
            )
            validate_decision_coverage(patch, issues)
            revised = apply_patch_transactionally(
                current,
                patch,
                slide_count=len(all_images),
                max_depth=args.max_depth,
            )
            locality = patch_locality(current, revised, patch)
            result.update(
                {
                    "application_valid": True,
                    "tree_valid": True,
                    "locality": locality,
                    "patched_node_count": len(revised.nodes),
                    "patched_graph_chars": len(
                        _canonical(revised.model_dump(mode="json"))
                    ),
                }
            )
            valid_outputs.append((patch, revised))
            artifact = {
                "patch": patch.model_dump(mode="json"),
                "patched_mindmap": revised.model_dump(mode="json"),
                "metrics": result,
            }
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
            result["rollback_preserved"] = (
                _fingerprint(current.model_dump(mode="json"))
                == original_fingerprint
            )
            artifact = {
                "metrics": result,
                "attempts": attempts,
            }
            if patch is not None:
                artifact["patch"] = patch.model_dump(mode="json")
        (args.output_dir / f"run_{run_number}.json").write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        results.append(result)
        print(
            f"run={run_number} schema={result['schema_valid']} "
            f"apply={result['application_valid']} "
            f"ops={result.get('operation_count', 0)} "
            f"latency={result.get('latency_seconds', 'n/a')}s"
        )

    target_sets = [
        set(result.get("operation_targets") or [])
        for result in results
        if result["schema_valid"]
    ]
    pairwise_target_jaccard = [
        _target_jaccard(target_sets[left], target_sets[right])
        for left in range(len(target_sets))
        for right in range(left + 1, len(target_sets))
    ]
    latencies = [
        float(result["latency_seconds"])
        for result in results
        if "latency_seconds" in result
    ]
    summary: dict[str, Any] = {
        "fixture": {
            "run_id": args.run_id,
            "filename": filename,
            "slide_count": len(all_images),
            "selected_image_count": len(selected_images),
            "input_issue_count": len(issues),
            "input_node_count": len(current.nodes),
        },
        "model": args.model,
        "repetitions": args.repetitions,
        "structured_output_success_rate": (
            sum(result["schema_valid"] for result in results)
            / args.repetitions
        ),
        "patch_application_success_rate": (
            sum(result["application_valid"] for result in results)
            / args.repetitions
        ),
        "tree_validation_success_rate": (
            sum(result["tree_valid"] for result in results)
            / args.repetitions
        ),
        "rollback_preservation_rate": (
            sum(result["rollback_preserved"] for result in results)
            / args.repetitions
        ),
        "untouched_node_preservation_rate": (
            sum(
                bool((result.get("locality") or {}).get(
                    "untouched_nodes_preserved"
                ))
                for result in results
            )
            / args.repetitions
        ),
        "median_latency_seconds": (
            round(statistics.median(latencies), 3) if latencies else None
        ),
        "mean_pairwise_target_jaccard": (
            round(statistics.mean(pairwise_target_jaccard), 4)
            if pairwise_target_jaccard
            else None
        ),
        "runs": results,
    }
    if valid_outputs and not args.skip_review:
        patch, revised = valid_outputs[0]
        print("running semantic reviewers for the first valid patch")
        summary["semantic_review"] = await review_valid_patch(
            client=client,
            model=args.model,
            filename=filename,
            images=all_images,
            current=revised,
            original_issues=issues,
            decisions=patch.decisions,
        )

    summary_path = args.output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"summary={summary_path}")
    return 0 if valid_outputs else 2


def main() -> int:
    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
