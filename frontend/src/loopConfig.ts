import type {
  MindMapLoopConfig,
  MindMapLoopRound,
  MindMapReviewerRole,
} from "./types";

export const MAX_LOOP_ROUNDS = 6;

export const reviewerModelFields: Record<
  MindMapReviewerRole,
  keyof MindMapLoopRound
> = {
  content_omission: "content_omission_model",
  pruning: "pruning_model",
  multilevel_structure: "multilevel_structure_model",
};

export function createExampleLoop(model: string): MindMapLoopConfig {
  return {
    rounds: [
      {
        editor_model: model,
        content_omission_model: model,
        pruning_model: model,
        multilevel_structure_model: model,
      },
    ],
  };
}

export function cloneLoopConfig(
  config: MindMapLoopConfig,
): MindMapLoopConfig {
  return {
    rounds: config.rounds.map((round) => ({ ...round })),
  };
}

export function normalizeLoopConfig(
  config: MindMapLoopConfig | null | undefined,
  fallbackModel: string,
): MindMapLoopConfig {
  const rounds = config?.rounds
    .slice(0, MAX_LOOP_ROUNDS)
    .filter((round) => Boolean(round.editor_model))
    .map((round) => ({ ...round }));
  return rounds?.length ? { rounds } : createExampleLoop(fallbackModel);
}

export function addLoopRound(
  config: MindMapLoopConfig,
  fallbackModel: string,
): MindMapLoopConfig {
  if (config.rounds.length >= MAX_LOOP_ROUNDS) return config;
  const template =
    config.rounds.at(-1) ?? createExampleLoop(fallbackModel).rounds[0];
  return {
    rounds: [...config.rounds, { ...template }],
  };
}

export function removeLoopRound(
  config: MindMapLoopConfig,
  index: number,
): MindMapLoopConfig {
  if (config.rounds.length <= 1) return config;
  return {
    rounds: config.rounds.filter((_, roundIndex) => roundIndex !== index),
  };
}

export function setEditorModel(
  config: MindMapLoopConfig,
  index: number,
  model: string,
): MindMapLoopConfig {
  return updateRound(config, index, (round) => ({
    ...round,
    editor_model: model,
  }));
}

export function setReviewerEnabled(
  config: MindMapLoopConfig,
  index: number,
  role: MindMapReviewerRole,
  enabled: boolean,
  fallbackModel: string,
): MindMapLoopConfig {
  const field = reviewerModelFields[role];
  return updateRound(config, index, (round) => ({
    ...round,
    [field]: enabled ? round[field] || fallbackModel : null,
  }));
}

export function setReviewerModel(
  config: MindMapLoopConfig,
  index: number,
  role: MindMapReviewerRole,
  model: string,
): MindMapLoopConfig {
  const field = reviewerModelFields[role];
  return updateRound(config, index, (round) => ({
    ...round,
    [field]: model,
  }));
}

export function selectedLoopModels(config: MindMapLoopConfig): string[] {
  return [
    ...new Set(
      config.rounds.flatMap((round) =>
        [
          round.editor_model,
          round.content_omission_model,
          round.pruning_model,
          round.multilevel_structure_model,
        ].filter((model): model is string => Boolean(model)),
      ),
    ),
  ];
}

export function plannedModelCalls(config: MindMapLoopConfig): number {
  return (
    1
    + config.rounds.reduce(
      (total, round) =>
        total
        + 1
        + [
          round.content_omission_model,
          round.pruning_model,
          round.multilevel_structure_model,
        ].filter(Boolean).length,
      0,
    )
  );
}

function updateRound(
  config: MindMapLoopConfig,
  index: number,
  update: (round: MindMapLoopRound) => MindMapLoopRound,
): MindMapLoopConfig {
  return {
    rounds: config.rounds.map((round, roundIndex) =>
      roundIndex === index ? update(round) : round,
    ),
  };
}
