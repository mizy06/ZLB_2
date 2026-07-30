from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import cplus_pipeline
from backend.app.blackboard import SQLiteBlackboard


SOURCE = """# 课程结构

## 第一部分

第一部分定义核心概念并说明基本原理。

## 第二部分

第二部分给出方法步骤和应用示例。
"""


async def _noop_progress(
    stage: str,
    progress: int,
    message: str,
) -> None:
    del stage, progress, message


class SolverFallbackDegradedTDDTests(unittest.IsolatedAsyncioTestCase):
    async def _run_with_solver_status(self, status: str):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "course.md"
            source.write_text(SOURCE, encoding="utf-8")
            blackboard = SQLiteBlackboard(root / "blackboard.sqlite3")
            real_solver = cplus_pipeline.solve_topology

            def solve_with_status(request):
                solved = real_solver(request)
                return solved.model_copy(update={"solver_status": status})

            with patch.object(
                cplus_pipeline,
                "solve_topology",
                side_effect=solve_with_status,
            ):
                return await cplus_pipeline.run_cplus_pipeline(
                    task_id=f"task_solver_{status.lower()}",
                    file_path=source,
                    filename=source.name,
                    model="qwen3.8-max-preview",
                    provider="qwen",
                    mode="standard",
                    use_ai=False,
                    progress=_noop_progress,
                    blackboard=blackboard,
                )

    async def test_greedy_fallback_blocks_publish_as_degraded(self):
        result = await self._run_with_solver_status("GREEDY_FALLBACK")

        self.assertIn(
            "topology_solver_fallback",
            result.degraded_components,
        )
        self.assertFalse(result.quality_report.publish_gate_passed)
        self.assertFalse(result.quality_report.quality_gate_passed)

    async def test_successful_solver_statuses_do_not_add_fallback_degradation(
        self,
    ):
        for status in ("OPTIMAL", "FEASIBLE"):
            with self.subTest(status=status):
                result = await self._run_with_solver_status(status)
                self.assertNotIn(
                    "topology_solver_fallback",
                    result.degraded_components,
                )


if __name__ == "__main__":
    unittest.main()
