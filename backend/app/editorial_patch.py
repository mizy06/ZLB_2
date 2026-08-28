from __future__ import annotations

import copy
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .single_shot_ppt_pipeline import SingleShotNode


MindMapT = TypeVar("MindMapT", bound=BaseModel)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EditorialIssueDecision(BaseModel):
    issue_id: str = Field(min_length=1, max_length=120)
    decision: Literal["accepted", "partially_accepted", "rejected"]
    reason: str = Field(min_length=4, max_length=1000)
    affected_node_ids: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("issue_id", "reason")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("affected_node_ids")
    @classmethod
    def normalize_node_ids(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class NodeChanges(_StrictModel):
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


class BriefChanges(_StrictModel):
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


class AddNode(_StrictModel):
    op: Literal["add_node"]
    node: SingleShotNode


class UpdateNode(_StrictModel):
    op: Literal["update_node"]
    target_id: str = Field(min_length=1, max_length=96)
    changes: NodeChanges


class DeleteNode(_StrictModel):
    op: Literal["delete_node"]
    target_id: str = Field(min_length=1, max_length=96)


class MoveNode(_StrictModel):
    op: Literal["move_node"]
    target_id: str = Field(min_length=1, max_length=96)
    new_parent_id: str = Field(min_length=1, max_length=96)


class PositionNode(_StrictModel):
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


class UpdateBrief(_StrictModel):
    op: Literal["update_brief"]
    changes: BriefChanges


PatchOperation = (
    AddNode
    | UpdateNode
    | DeleteNode
    | MoveNode
    | PositionNode
    | UpdateBrief
)


class EditorialPatch(_StrictModel):
    decisions: list[EditorialIssueDecision] = Field(min_length=1, max_length=48)
    operations: list[PatchOperation] = Field(default_factory=list, max_length=64)


class SkippedPatchOperation(BaseModel):
    index: int = Field(ge=1)
    op: str = Field(min_length=1, max_length=48)
    target_id: str | None = Field(default=None, max_length=96)
    reason: str = Field(min_length=1, max_length=240)


class PatchEffects(BaseModel):
    added_node_ids: list[str] = Field(default_factory=list)
    deleted_node_ids: list[str] = Field(default_factory=list)
    changed_fields_by_node: dict[str, list[str]] = Field(default_factory=dict)
    repositioned_node_ids: list[str] = Field(default_factory=list)
    editorial_brief_changed: bool = False
    skipped_operations: list[SkippedPatchOperation] = Field(default_factory=list)

    @property
    def graph_changed(self) -> bool:
        return bool(
            self.added_node_ids
            or self.deleted_node_ids
            or self.changed_fields_by_node
            or self.repositioned_node_ids
            or self.editorial_brief_changed
        )


class PatchApplicationError(ValueError):
    pass


def validate_decision_coverage(
    patch: EditorialPatch,
    issues: list[Any],
) -> None:
    expected = [str(issue.id) for issue in issues]
    actual = [decision.issue_id for decision in patch.decisions]
    if len(actual) != len(set(actual)):
        raise PatchApplicationError("patch contains duplicate issue decisions")
    if set(actual) != set(expected):
        raise PatchApplicationError(
            "patch decision coverage mismatch "
            f"(missing={sorted(set(expected) - set(actual))}, "
            f"extra={sorted(set(actual) - set(expected))})"
        )


def _node_fields_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(node["id"]): node for node in payload["nodes"]}


def _sibling_indexes(payload: dict[str, Any]) -> dict[str, int]:
    next_index: dict[str | None, int] = {}
    indexes: dict[str, int] = {}
    for node in payload["nodes"]:
        parent_id = node["parent_id"]
        indexes[str(node["id"])] = next_index.get(parent_id, 0)
        next_index[parent_id] = indexes[str(node["id"])] + 1
    return indexes


def patch_effects(before: BaseModel, after: BaseModel) -> PatchEffects:
    before_payload = before.model_dump(mode="json")
    after_payload = after.model_dump(mode="json")
    before_nodes = _node_fields_by_id(before_payload)
    after_nodes = _node_fields_by_id(after_payload)
    changed_fields: dict[str, list[str]] = {}
    for node_id in sorted(before_nodes.keys() & after_nodes.keys()):
        fields = sorted(
            field
            for field in before_nodes[node_id]
            if before_nodes[node_id].get(field) != after_nodes[node_id].get(field)
        )
        if fields:
            changed_fields[node_id] = fields
    before_indexes = _sibling_indexes(before_payload)
    after_indexes = _sibling_indexes(after_payload)
    repositioned = sorted(
        node_id
        for node_id in before_nodes.keys() & after_nodes.keys()
        if before_nodes[node_id]["parent_id"] == after_nodes[node_id]["parent_id"]
        and before_indexes[node_id] != after_indexes[node_id]
    )
    return PatchEffects(
        added_node_ids=sorted(after_nodes.keys() - before_nodes.keys()),
        deleted_node_ids=sorted(before_nodes.keys() - after_nodes.keys()),
        changed_fields_by_node=changed_fields,
        repositioned_node_ids=repositioned,
        editorial_brief_changed=(
            before_payload.get("editorial_brief")
            != after_payload.get("editorial_brief")
        ),
    )


def validate_decision_effects(
    patch: EditorialPatch,
    issues: list[Any],
    effects: PatchEffects,
) -> None:
    issue_by_id = {str(issue.id): issue for issue in issues}
    changed_ids = {
        *effects.added_node_ids,
        *effects.deleted_node_ids,
        *effects.changed_fields_by_node,
        *effects.repositioned_node_ids,
    }
    for decision in patch.decisions:
        if decision.decision == "rejected":
            continue
        issue = issue_by_id[decision.issue_id]
        if str(issue.suggested_action) == "manual_review":
            continue
        targets = set(decision.affected_node_ids)
        if targets and targets & changed_ids:
            continue
        if str(issue.suggested_action) in {
            "add_node",
            "restore_pruned",
            "split_node",
        } and effects.added_node_ids:
            continue
        if effects.editorial_brief_changed and not targets:
            continue
        raise PatchApplicationError(
            "accepted decision has no matching deterministic graph effect: "
            + decision.issue_id
        )


def apply_patch_transactionally(
    current: MindMapT,
    patch: EditorialPatch,
) -> tuple[MindMapT, PatchEffects]:
    working = copy.deepcopy(current.model_dump(mode="json"))
    nodes: list[dict[str, Any]] = working["nodes"]
    skipped_operations: list[SkippedPatchOperation] = []

    def node_map() -> dict[str, dict[str, Any]]:
        return {str(node["id"]): node for node in nodes}

    def skip_noop(
        index: int,
        operation: PatchOperation,
        reason: str,
    ) -> None:
        if isinstance(operation, AddNode):
            target_id = operation.node.id
        elif isinstance(operation, UpdateBrief):
            target_id = None
        else:
            target_id = operation.target_id
        skipped_operations.append(
            SkippedPatchOperation(
                index=index,
                op=operation.op,
                target_id=target_id,
                reason=reason,
            )
        )

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

    def current_siblings(target: dict[str, Any]) -> list[str]:
        return [
            str(node["id"])
            for node in nodes
            if node["parent_id"] == target["parent_id"]
        ]

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
                changes = operation.changes.model_dump(
                    mode="json",
                    exclude_none=True,
                )
                if all(
                    working["editorial_brief"].get(field) == value
                    for field, value in changes.items()
                ):
                    skip_noop(index, operation, "update_brief has no effect")
                    continue
                working["editorial_brief"].update(changes)
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
                if all(target.get(field) == value for field, value in changes.items()):
                    skip_noop(
                        index,
                        operation,
                        f"update_node has no effect: {target_id}",
                    )
                    continue
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
                    skip_noop(
                        index,
                        operation,
                        f"move_node has no effect: {target_id}",
                    )
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
                siblings = current_siblings(target)
                target_index = siblings.index(target_id)
                if operation.position == "first" and target_index == 0:
                    skip_noop(
                        index,
                        operation,
                        f"position_node has no effect: {target_id}",
                    )
                    continue
                if (
                    operation.position == "last"
                    and target_index == len(siblings) - 1
                ):
                    skip_noop(
                        index,
                        operation,
                        f"position_node has no effect: {target_id}",
                    )
                    continue
                sibling_id = (
                    operation.before_sibling_id
                    or operation.after_sibling_id
                )
                if sibling_id is not None:
                    sibling = by_id.get(sibling_id)
                    if sibling is None:
                        raise PatchApplicationError(
                            f"position_node sibling does not exist: {sibling_id}"
                        )
                    if sibling["parent_id"] != parent_id:
                        raise PatchApplicationError(
                            "position_node anchor must share the target parent"
                        )
                    sibling_index = siblings.index(sibling_id)
                    already_positioned = (
                        operation.before_sibling_id is not None
                        and target_index + 1 == sibling_index
                    ) or (
                        operation.after_sibling_id is not None
                        and sibling_index + 1 == target_index
                    )
                    if already_positioned:
                        skip_noop(
                            index,
                            operation,
                            f"position_node has no effect: {target_id}",
                        )
                        continue

                block = subtree_block(target_id)
                block_ids = {node["id"] for node in block}
                nodes[:] = [
                    node for node in nodes if node["id"] not in block_ids
                ]
                remaining_by_id = node_map()
                if operation.position == "first":
                    insert_at = next(
                        item_index
                        for item_index, node in enumerate(nodes)
                        if node["id"] == parent_id
                    ) + 1
                elif operation.position == "last":
                    insert_at = insertion_index_after_subtree(parent_id)
                else:
                    sibling = remaining_by_id[str(sibling_id)]
                    if sibling["parent_id"] != parent_id:
                        raise PatchApplicationError(
                            "position_node anchor must share the target parent"
                        )
                    if operation.before_sibling_id is not None:
                        insert_at = next(
                            item_index
                            for item_index, node in enumerate(nodes)
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
        revised = type(current).model_validate(working)
    except ValueError as exc:
        raise PatchApplicationError(
            f"patched mindmap failed final validation: {exc}"
        ) from exc
    effects = patch_effects(current, revised)
    effects.skipped_operations = skipped_operations
    return revised, effects
