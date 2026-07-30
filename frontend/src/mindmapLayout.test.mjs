import assert from "node:assert/strict";
import test from "node:test";

import {
  mindMapLabelMaxLines,
  wrapMindMapLabel,
} from "../.test-dist/mindmapLayout.js";

test("long root labels wrap completely instead of looking model-truncated", () => {
  const label =
    "面向复杂工程系统的多源证据融合与可靠决策课程知识体系" +
    "及其完整实践方法、验证框架、运行治理、人工复核和持续演进机制" +
    "以及跨场景迁移评估体系";
  const maxLines = mindMapLabelMaxLines({
    isRoot: true,
    isBranch: false,
    hasMedia: true,
  });
  const wrapped = wrapMindMapLabel(label, 13, maxLines);

  assert.equal(maxLines, 8);
  assert.equal(wrapped.replaceAll("\n", ""), label);
  assert.equal(wrapped.includes("…"), false);
});
