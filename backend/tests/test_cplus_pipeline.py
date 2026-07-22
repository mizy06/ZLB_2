from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.architecture_schemas import (
    ReviewItemView,
    ReviewResolutionRequest,
)
from backend.app.blackboard import SQLiteBlackboard
from backend.app.cplus_pipeline import run_cplus_pipeline
from backend.app.export_service import render_mindmap_png
from backend.app.review_service import resolve_review_item


SAMPLE = """# 机器学习基础

机器学习是让计算机从数据中学习规律的方法。

## 监督学习

监督学习使用带标签样本学习输入到输出的映射。
分类用于预测离散标签，回归用于预测连续数值。

## 无监督学习

无监督学习处理没有标签的数据。
聚类用于发现样本中的群组结构。

## 模型评估

训练集用于拟合模型，验证集用于选择参数，测试集用于评估泛化能力。
"""


async def noop_progress(stage: str, progress: int, message: str) -> None:
    return None


class CPlusPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_heuristic_pipeline_builds_versioned_rooted_tree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "course.md"
            path.write_text(SAMPLE, encoding="utf-8")
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")

            result = await run_cplus_pipeline(
                task_id="task_demo",
                file_path=path,
                filename=path.name,
                model="kimi-k3",
                provider="kimi",
                mode="standard",
                use_ai=False,
                progress=noop_progress,
                blackboard=blackboard,
            )

            self.assertEqual(result.graph_version, 1)
            self.assertTrue(result.quality_report.topology_valid)
            self.assertEqual(result.quality_report.root_count, 1)
            self.assertEqual(len(result.tree_edges), len(result.nodes) - 1)
            self.assertEqual(result.quality_report.evidence_coverage, 1)
            self.assertGreaterEqual(
                result.quality_report.weighted_content_coverage,
                0.78,
            )
            self.assertTrue(all(node.depth >= 0 for node in result.nodes))
            self.assertEqual(
                [1],
                blackboard.list_graph_versions("task_demo"),
            )
            restored = blackboard.load_latest_result("task_demo")
            self.assertIsNotNone(restored)
            self.assertEqual(restored.root_id, result.root_id)
            history = blackboard.list_history()
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["task_id"], "task_demo")
            self.assertEqual(history[0]["title"], result.document.title)
            self.assertEqual(history[0]["node_count"], len(result.nodes))
            self.assertEqual(history[0]["graph_version"], 1)
            png = render_mindmap_png(result)
            self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))

    async def test_human_review_creates_new_graph_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "course.md"
            path.write_text(SAMPLE, encoding="utf-8")
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            result = await run_cplus_pipeline(
                task_id="task_review",
                file_path=path,
                filename=path.name,
                model="kimi-k3",
                provider="kimi",
                mode="standard",
                use_ai=False,
                progress=noop_progress,
                blackboard=blackboard,
            )
            subject = next(node for node in result.nodes if node.id != result.root_id)
            review = ReviewItemView(
                id="review_manual",
                type="abstract_parent",
                risk_score=0.7,
                subject_ids=[subject.id],
                reason="测试人工改名",
                evidence_unit_ids=[
                    item.unit_id or item.chunk_id
                    for item in subject.evidence
                    if item.unit_id or item.chunk_id
                ],
            )
            augmented = result.model_copy(
                update={
                    "graph_version": 0,
                    "review_items": [*result.review_items, review],
                }
            )
            blackboard.save_review_items(result.run_id, [review])
            blackboard.save_graph_version(result.run_id, augmented)

            updated = resolve_review_item(
                blackboard=blackboard,
                task_id="task_review",
                review_id=review.id,
                request=ReviewResolutionRequest(
                    action="rename",
                    label="人工确认主题",
                    reason="更符合课程术语",
                ),
            )

            self.assertEqual(updated.graph_version, 3)
            self.assertEqual(
                next(node for node in updated.nodes if node.id == subject.id).name,
                "人工确认主题",
            )
            self.assertEqual(
                next(item for item in updated.review_items if item.id == review.id).status,
                "resolved",
            )
            self.assertEqual(updated.decision_records[-1].actor, "human")


if __name__ == "__main__":
    unittest.main()
