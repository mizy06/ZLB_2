import {
  ChevronDown,
  Crown,
  Image,
  Layers3,
  Plus,
  RotateCcw,
  ScanSearch,
  Scissors,
  Trash2,
} from "lucide-react";

import {
  MAX_LOOP_ROUNDS,
  addLoopRound,
  plannedModelCalls,
  removeLoopRound,
  reviewerModelFields,
  setEditorModel,
  setReviewerEnabled,
  setReviewerModel,
} from "../loopConfig";
import type {
  MindMapLoopConfig,
  MindMapReviewerRole,
} from "../types";

const reviewerRoles: Array<{
  id: MindMapReviewerRole;
  label: string;
  icon: typeof ScanSearch;
  usesImages: boolean;
}> = [
  {
    id: "content_omission",
    label: "内容遗漏",
    icon: ScanSearch,
    usesImages: true,
  },
  {
    id: "pruning",
    label: "剪枝",
    icon: Scissors,
    usesImages: false,
  },
  {
    id: "multilevel_structure",
    label: "多级结构",
    icon: Layers3,
    usesImages: false,
  },
];

type LoopBuilderProps = {
  config: MindMapLoopConfig;
  example: MindMapLoopConfig;
  models: string[];
  disabled?: boolean;
  onChange: (config: MindMapLoopConfig) => void;
};

function ModelSelect({
  value,
  models,
  disabled,
  label,
  onChange,
}: {
  value: string;
  models: string[];
  disabled: boolean;
  label: string;
  onChange: (model: string) => void;
}) {
  const options = models.includes(value) ? models : [value, ...models];
  return (
    <div className="loop-model-select">
      <select
        aria-label={label}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((model) => (
          <option value={model} key={model}>
            {model}
          </option>
        ))}
      </select>
      <ChevronDown size={14} />
    </div>
  );
}

export function LoopBuilder({
  config,
  example,
  models,
  disabled = false,
  onChange,
}: LoopBuilderProps) {
  const fallbackModel =
    models[0] || config.rounds[0]?.editor_model || "qwen3.8-max-preview";
  return (
    <section className="loop-builder" aria-label="Mindmap loop">
      <header className="loop-builder-header">
        <div>
          <strong>Mindmap loop</strong>
          <span>
            {config.rounds.length} 轮 · 预计 {plannedModelCalls(config)} 次模型调用
          </span>
        </div>
        <button
          type="button"
          className="icon-button"
          title="恢复当前示例"
          aria-label="恢复当前示例"
          disabled={disabled}
          onClick={() => onChange({
            rounds: example.rounds.map((round) => ({ ...round })),
          })}
        >
          <RotateCcw size={15} />
        </button>
      </header>

      <div className="loop-rounds">
        {config.rounds.map((round, roundIndex) => (
          <article className="loop-round" key={`round-${roundIndex}`}>
            <header>
              <div>
                <span>{String(roundIndex + 1).padStart(2, "0")}</span>
                <strong>第 {roundIndex + 1} 轮</strong>
              </div>
              <button
                type="button"
                className="icon-button danger"
                title="删除本轮"
                aria-label={`删除第 ${roundIndex + 1} 轮`}
                disabled={disabled || config.rounds.length === 1}
                onClick={() =>
                  onChange(removeLoopRound(config, roundIndex))
                }
              >
                <Trash2 size={14} />
              </button>
            </header>

            <div className="loop-role required">
              <div className="loop-role-heading">
                <span className="loop-role-icon editor">
                  <Crown size={14} />
                </span>
                <strong>主编</strong>
                <small>必选</small>
                <Image size={13} aria-label="读取幻灯片" />
              </div>
              <ModelSelect
                value={round.editor_model}
                models={models}
                disabled={disabled}
                label={`第 ${roundIndex + 1} 轮主编模型`}
                onChange={(model) =>
                  onChange(setEditorModel(config, roundIndex, model))
                }
              />
            </div>

            {reviewerRoles.map((role) => {
              const field = reviewerModelFields[role.id];
              const selectedModel = round[field];
              const enabled = Boolean(selectedModel);
              const RoleIcon = role.icon;
              return (
                <div
                  className={`loop-role optional ${enabled ? "enabled" : ""}`}
                  key={role.id}
                >
                  <label className="loop-role-heading">
                    <input
                      type="checkbox"
                      checked={enabled}
                      disabled={disabled}
                      onChange={(event) =>
                        onChange(
                          setReviewerEnabled(
                            config,
                            roundIndex,
                            role.id,
                            event.target.checked,
                            round.editor_model || fallbackModel,
                          ),
                        )
                      }
                    />
                    <span className="loop-role-checkbox" />
                    <span className="loop-role-icon">
                      <RoleIcon size={14} />
                    </span>
                    <strong>{role.label}</strong>
                    {role.usesImages && (
                      <Image size={13} aria-label="读取幻灯片" />
                    )}
                  </label>
                  {enabled && (
                    <ModelSelect
                      value={String(selectedModel)}
                      models={models}
                      disabled={disabled}
                      label={`第 ${roundIndex + 1} 轮${role.label}模型`}
                      onChange={(model) =>
                        onChange(
                          setReviewerModel(
                            config,
                            roundIndex,
                            role.id,
                            model,
                          ),
                        )
                      }
                    />
                  )}
                </div>
              );
            })}
          </article>
        ))}
      </div>

      <button
        type="button"
        className="add-round"
        disabled={disabled || config.rounds.length >= MAX_LOOP_ROUNDS}
        onClick={() => onChange(addLoopRound(config, fallbackModel))}
      >
        <Plus size={15} />
        添加一轮
        <span>{config.rounds.length}/{MAX_LOOP_ROUNDS}</span>
      </button>
    </section>
  );
}
