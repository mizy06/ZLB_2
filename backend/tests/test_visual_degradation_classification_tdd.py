from __future__ import annotations

import unittest

from backend.app.cplus_pipeline import (
    _render_warning_degraded_components,
)


class VisualDegradationClassificationTDDTests(unittest.TestCase):
    def test_benign_deduplication_warnings_do_not_block_publish(self):
        components = _render_warning_degraded_components(
            [
                "幻灯片 1 的 picture 与同页已有视觉资产感知重复，已跳过重复副本。",
                "幻灯片 2 的 picture 与已有视觉资产感知重复，"
                "已复用 native_0001_1 并保留出现位置。",
            ]
        )

        self.assertEqual(components, [])

    def test_machine_readable_render_failures_map_to_stable_components(self):
        components = _render_warning_degraded_components(
            [
                "[visual_degraded:render_budget] 仅栅格化部分页面。",
                "[visual_degraded:render_failure] PPTX 整页渲染不可用。",
                "[visual_degraded:native_extraction] 图表缺少渲染页。",
                "[visual_degraded:render_budget] 重复预算提示。",
            ]
        )

        self.assertEqual(
            components,
            [
                "visual_render_budget",
                "visual_rendering",
                "visual_native_extraction",
            ],
        )


if __name__ == "__main__":
    unittest.main()
