import test from "node:test";
import assert from "node:assert/strict";

import {
  addLoopRound,
  createExampleLoop,
  plannedModelCalls,
  removeLoopRound,
  selectedLoopModels,
  setEditorModel,
  setReviewerEnabled,
  setReviewerModel,
} from "../.test-dist/loopConfig.js";

test("the current all-role loop is the editable example", () => {
  const config = createExampleLoop("model-a");

  assert.equal(config.rounds.length, 1);
  assert.deepEqual(selectedLoopModels(config), ["model-a"]);
  assert.equal(plannedModelCalls(config), 5);
});

test("reviewers are optional while every round keeps an editor", () => {
  let config = createExampleLoop("model-a");
  config = setReviewerEnabled(
    config,
    0,
    "pruning",
    false,
    "model-a",
  );
  config = addLoopRound(config, "model-a");
  config = setEditorModel(config, 1, "model-b");
  config = setReviewerModel(
    config,
    1,
    "content_omission",
    "model-c",
  );

  assert.equal(config.rounds[0].pruning_model, null);
  assert.equal(config.rounds[1].editor_model, "model-b");
  assert.equal(config.rounds[1].content_omission_model, "model-c");
  assert.deepEqual(selectedLoopModels(config), [
    "model-a",
    "model-b",
    "model-c",
  ]);
});

test("at least one round is always retained", () => {
  const config = createExampleLoop("model-a");

  assert.deepEqual(removeLoopRound(config, 0), config);
});
