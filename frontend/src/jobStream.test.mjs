import test from "node:test";
import assert from "node:assert/strict";

import {
  emptyJobStreamState,
  mergeJobEvents,
} from "../.test-dist/jobStream.js";

const event = (id, kind, overrides = {}) => ({
  id,
  task_id: "task-1",
  kind,
  created_at: "2026-08-02T00:00:00Z",
  stage: "editorial_review_1_pruning",
  progress: null,
  message: "",
  call_id: "editorial_review_1_pruning",
  round_number: 1,
  role: "pruning_reviewer",
  model: "model-a",
  delta: "",
  ...overrides,
});

test("stream events assemble one live role output", () => {
  const state = mergeJobEvents(emptyJobStreamState(), [
    event(1, "model_start"),
    event(2, "model_delta", { delta: "{\"issues\":" }),
    event(3, "model_delta", { delta: "[]}" }),
    event(4, "model_complete"),
  ]);

  assert.equal(state.calls.length, 1);
  assert.equal(state.calls[0].output, "{\"issues\":[]}");
  assert.equal(state.calls[0].status, "completed");
});

test("replayed event ids are ignored instead of duplicating output", () => {
  const initial = mergeJobEvents(emptyJobStreamState(), [
    event(1, "model_start"),
    event(2, "model_delta", { delta: "hello" }),
  ]);
  const replayed = mergeJobEvents(initial, [
    event(2, "model_delta", { delta: "hello" }),
    event(3, "model_complete"),
  ]);

  assert.equal(replayed.calls[0].output, "hello");
  assert.equal(replayed.calls[0].status, "completed");
});

test("status events retain one live row per pipeline stage", () => {
  const state = mergeJobEvents(emptyJobStreamState(), [
    event(1, "status", {
      call_id: "",
      stage: "parse",
      progress: 10,
      message: "解析课程材料",
    }),
    event(2, "status", {
      call_id: "",
      stage: "parse",
      progress: 20,
      message: "解析完成",
    }),
    event(3, "status", {
      call_id: "",
      stage: "themes",
      progress: 30,
      message: "生成全局主题",
    }),
  ]);

  assert.equal(state.steps.length, 2);
  assert.equal(state.steps[0].status, "completed");
  assert.equal(state.steps[0].progress, 20);
  assert.equal(state.steps[1].status, "running");
});

test("terminal events close the active pipeline step", () => {
  const state = mergeJobEvents(emptyJobStreamState(), [
    event(1, "status", {
      call_id: "",
      stage: "finalize",
      progress: 95,
      message: "写入图版本",
    }),
    event(2, "job_complete", {
      call_id: "",
      stage: "complete",
      progress: 100,
    }),
  ]);

  assert.equal(state.steps[0].status, "completed");
});
