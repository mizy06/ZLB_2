from __future__ import annotations

import unittest
from types import SimpleNamespace

from backend.app.editorial_ppt_pipeline import (
    EditorialBrief,
    EditorialMindMap,
)
from backend.app.single_shot_ppt_pipeline import SingleShotNode
from backend.app.editorial_patch import (
    AddNode,
    DeleteNode,
    EditorialPatch,
    MoveNode,
    NodeChanges,
    PatchApplicationError,
    PositionNode,
    UpdateNode,
    apply_patch_transactionally,
    validate_decision_effects,
)


def _node(
    node_id: str,
    *,
    parent_id: str | None,
    role: str = "concept",
) -> SingleShotNode:
    return SingleShotNode(
        id=node_id,
        name=node_id,
        role=role,
        definition=f"{node_id} definition",
        parent_id=parent_id,
        source_slides=[1],
        confidence=0.9,
    )


def _mindmap() -> EditorialMindMap:
    return EditorialMindMap(
        title="Patch fixture",
        editorial_brief=EditorialBrief(
            learning_goal="Understand the patch fixture",
            audience="Students",
            organizing_principle="Concept hierarchy",
            level_semantics=["Topic", "Concept"],
            importance_policy="Keep concepts needed for understanding.",
            pruning_policy="Remove only clearly redundant material.",
        ),
        nodes=[
            _node("root", parent_id=None, role="root"),
            _node("a", parent_id="root"),
            _node("b", parent_id="root"),
            _node("b-child", parent_id="b"),
        ],
    )


class EditorialPatchTests(unittest.TestCase):
    def test_applies_valid_operations_and_preserves_untouched_nodes(self) -> None:
        current = _mindmap()
        patch = EditorialPatch(
            decisions=[
                {
                    "issue_id": "issue-1",
                    "decision": "accepted",
                    "reason": "The change fixes the reported issue.",
                    "affected_node_ids": ["a", "c"],
                }
            ],
            operations=[
                UpdateNode(
                    op="update_node",
                    target_id="a",
                    changes=NodeChanges(definition="Revised definition"),
                ),
                AddNode(
                    op="add_node",
                    node=_node("c", parent_id="root"),
                ),
                PositionNode(
                    op="position_node",
                    target_id="c",
                    position="first",
                ),
                PositionNode(
                    op="position_node",
                    target_id="a",
                    position="last",
                ),
            ],
        )

        revised, effects = apply_patch_transactionally(
            current,
            patch,
        )
        self.assertEqual(
            [node.id for node in revised.nodes if node.parent_id == "root"],
            ["c", "b", "a"],
        )
        self.assertEqual(
            [node.id for node in revised.nodes],
            ["root", "c", "b", "b-child", "a"],
        )
        self.assertEqual(effects.changed_fields_by_node, {"a": ["definition"]})
        self.assertEqual(effects.added_node_ids, ["c"])
        self.assertTrue(effects.graph_changed)

    def test_failed_patch_leaves_original_unchanged(self) -> None:
        current = _mindmap()
        before = current.model_dump_json()
        patch = EditorialPatch(
            decisions=[
                {
                    "issue_id": "issue-1",
                    "decision": "accepted",
                    "reason": "Attempt an invalid non-leaf deletion.",
                    "affected_node_ids": ["root"],
                }
            ],
            operations=[
                DeleteNode(op="delete_node", target_id="root"),
            ],
        )

        with self.assertRaises(PatchApplicationError):
            apply_patch_transactionally(
                current,
                patch,
            )

        self.assertEqual(current.model_dump_json(), before)

    def test_cycle_created_by_move_is_rejected_atomically(self) -> None:
        current = _mindmap().model_copy(
            update={
                "nodes": [
                    _node("root", parent_id=None, role="root"),
                    _node("a", parent_id="root"),
                    _node("child", parent_id="a"),
                ]
            }
        )
        before = current.model_dump_json()
        patch = EditorialPatch(
            decisions=[
                {
                    "issue_id": "issue-1",
                    "decision": "accepted",
                    "reason": "Attempt an invalid cyclic move.",
                    "affected_node_ids": ["a"],
                }
            ],
            operations=[
                MoveNode(
                    op="move_node",
                    target_id="a",
                    new_parent_id="child",
                ),
            ],
        )

        with self.assertRaises(PatchApplicationError):
            apply_patch_transactionally(
                current,
                patch,
            )

        self.assertEqual(current.model_dump_json(), before)

    def test_skips_satisfied_position_but_accepted_decision_has_no_effect(
        self,
    ) -> None:
        current = _mindmap()
        patch = EditorialPatch(
            decisions=[
                {
                    "issue_id": "issue-1",
                    "decision": "accepted",
                    "reason": "Attempt a redundant position operation.",
                    "affected_node_ids": ["a"],
                }
            ],
            operations=[
                PositionNode(
                    op="position_node",
                    target_id="a",
                    position="first",
                ),
            ],
        )

        revised, effects = apply_patch_transactionally(current, patch)

        self.assertEqual(revised, current)
        self.assertFalse(effects.graph_changed)
        self.assertEqual(len(effects.skipped_operations), 1)
        self.assertEqual(effects.skipped_operations[0].op, "position_node")
        with self.assertRaisesRegex(
            PatchApplicationError,
            "accepted decision has no matching",
        ):
            validate_decision_effects(
                patch,
                [
                    SimpleNamespace(
                        id="issue-1",
                        suggested_action="move_subtree",
                    )
                ],
                effects,
            )

    def test_rejected_noop_does_not_block_other_valid_operations(self) -> None:
        current = _mindmap()
        patch = EditorialPatch(
            decisions=[
                {
                    "issue_id": "resolved-move",
                    "decision": "rejected",
                    "reason": "The node already has the requested parent.",
                    "affected_node_ids": ["a"],
                },
                {
                    "issue_id": "rewrite-b",
                    "decision": "accepted",
                    "reason": "The definition needs a substantive rewrite.",
                    "affected_node_ids": ["b"],
                },
            ],
            operations=[
                MoveNode(
                    op="move_node",
                    target_id="a",
                    new_parent_id="root",
                ),
                UpdateNode(
                    op="update_node",
                    target_id="b",
                    changes=NodeChanges(
                        definition="A shorter and clearer definition."
                    ),
                ),
            ],
        )

        revised, effects = apply_patch_transactionally(current, patch)
        validate_decision_effects(
            patch,
            [
                SimpleNamespace(
                    id="resolved-move",
                    suggested_action="move_subtree",
                ),
                SimpleNamespace(
                    id="rewrite-b",
                    suggested_action="rewrite_definition",
                ),
            ],
            effects,
        )

        self.assertEqual(
            next(node for node in revised.nodes if node.id == "b").definition,
            "A shorter and clearer definition.",
        )
        self.assertEqual(len(effects.skipped_operations), 1)
        self.assertEqual(effects.skipped_operations[0].target_id, "a")


if __name__ == "__main__":
    unittest.main()
