# C+ 架构实现映射

日期：2026-07-22

对应设计：[思维导图 Agent 框架设计](superpowers/specs/2026-07-17-mind-map-agent-framework-design.md)

## 1. Supervisor 与阶段

`backend/app/cplus_pipeline.py` 使用 LangGraph `StateGraph` 实现 Main Supervisor：

```text
parse
  -> ledger
  -> themes
  -> branch_plan
  -> branches
  -> merge_audit
  -> normalize
  -> verify
  -> solve
  -> finalize
```

每个阶段写入 SQLite 检查点。模型失败只降级当前阶段，其他分支和求解继续执行。

## 2. 内容单元与视觉

`backend/app/agents.py` 将 chunk 转换为 `ContentUnit`，保留：

- `chunk_id`
- 标题路径
- PDF 页码
- PPTX 幻灯片号
- 教学角色
- 重要度
- 原文证据

`backend/app/visual_analysis.py` 处理整页视觉：

1. 使用 Kimi K3 多模态兼容接口分析页面。
2. 输出归一化 bbox。
3. 调用 `mindmap_engine.visuals.crop_regions` 裁剪。
4. 将知识区域转换为视觉 Content Unit。
5. `attach_as_media` 与附近文本节点融合，不强制成为独立节点。

PPTX 原生图片、图表、表格和组合图由 `mindmap_engine/visuals.py` 提取。

## 3. Global Theme 与 Root Planner

`synthesize_themes` 生成 1–3 个根候选和一级主题。

- 模型可用：使用严格 JSON 输出。
- 模型不可用：根据文档标题、标题路径和内容单元生成确定性计划。
- 所有根和抽象主题必须带 `support_unit_ids`。

`build_branch_plans` 将一级主题递归拆分到最多三层，并为每个分支设置内容预算。

## 4. Branch Team

每个 Branch Team 是独立 LangGraph 子图：

```text
Node Scout
  -> Granularity Critic
  -> Abstraction Induction
  -> Parent Retriever
  -> Local Verifier
```

子图内部状态按调用隔离。多个分支通过 `asyncio` 并发运行，只向黑板提交候选和局部判断，不提交最终树。

## 5. 共享证据黑板

`backend/app/blackboard.py` 使用 SQLite WAL，表包括：

- `runs`
- `content_units`
- `node_claims`
- `parent_candidates`
- `cross_link_candidates`
- `decision_records`
- `review_items`
- `checkpoints`
- `graph_versions`
- `model_calls`

所有图版本保存完整输出契约。服务重启后，`GET /api/jobs/{task_id}` 可从黑板恢复最新版本。

## 6. 合并与审计

`canonicalize_semantic_duplicates` 执行：

- 标准化同名去重。
- 同分支近似名称合并。
- alias、证据、支持集和媒体合并。

`fuse_visual_media` 将 `attach_as_media` 视觉资产绑定到附近文本节点。

`audit_coverage` 定位未覆盖的重要内容单元，并为有可靠证据的单元补建显式候选。视觉装饰和低知识分素材进入 `deferred` 或 `rejected`，不静默丢弃。

## 7. 父候选与校验

候选来源：

- 根到一级主题。
- 父分支到子分支。
- 分支主题到显式节点。
- 章节先验。
- 角色兼容。
- 名称和定义相似度。
- 模型或启发式局部建议。

每个子节点只保留 Top-k 候选。模型校验限定在每个子节点的前三名，避免 O(n²) 调用。

标准档：

- 一个独立 Kimi 校验调用。

高精档：

- 高风险候选前两名增加第二个独立 Kimi 校验调用。
- 两票分类不一致时调用独立 Kimi 仲裁角色。
- 校验器不可用时保留确定性票和降级记录。

## 8. 拓扑求解

`backend/app/mindmap_engine/topology.py` 使用 CP-SAT：

- 根候选恰好激活一个。
- 每个激活非根节点恰好一个父节点。
- 深度沿父边递增。
- 可选抽象节点至少拥有两个激活子节点。
- 临时保底边承担目标惩罚。

求解失败时使用确定性 NetworkX 贪心兜底。兜底边必须标记 `provisional` 并进入人工复核。

`validate.py` 二次校验：

- 唯一根。
- 唯一父。
- 无环。
- 根可达。
- 边端点存在。
- 边数为 `nodes - 1`。
- 最终节点证据可追溯。

## 9. 人工复核与版本

`backend/app/review_service.py` 支持：

- 保留。
- 删除非根节点并安全重接子节点。
- 改父并检查环和根可达。
- 改名。
- 确认当前根。

每个动作：

1. 写入 human `DecisionRecord`。
2. 将复核项标记为 `resolved`。
3. 重新计算深度和质量。
4. 保存新 `graph_version`。

## 10. 输出与前端

`MindMapResult` 输出：

- `task_id`
- `run_id`
- `graph_version`
- 文档、chunks 和 Content Units
- `root_id`
- `nodes`
- `tree_edges`
- `cross_links`
- `assets`
- `quality_report`
- `review_items`
- `decision_records`
- 模型角色与降级组件

前端使用 Cytoscape `breadthfirst` 呈现主树，跨链可独立开关。Inspector 显示：

- 定义、角色、来源、深度和风险。
- 父节点、子节点和跨链。
- 原文与视觉证据。
- 独立校验票。
- 决策历史。

## 11. 安全与删除

- Provider Key 只在后端配置中读取。
- 上传文件在任务结束后删除。
- 原始视觉资产按 `render_id` 隔离。
- 删除任务时同步删除 SQLite 记录和资产目录。
- 共享黑板不记录完整模型隐藏推理。

## 12. 验收

自动测试覆盖：

- 解析与稳定 ID。
- 候选归一。
- CP-SAT 主树。
- 临时父边复核。
- PPTX 视觉提取。
- bbox 裁剪。
- C+ 端到端。
- SQLite 图恢复。
- 人工复核图版本。

仓库内工程硬门为：

```text
topology_valid == true
evidence_coverage == 1
provisional_edge_count == 0
```

内容覆盖阈值按运行档位分别为 0.78 和 0.86。业务精度指标需要使用设计文档约定的开发集、校准集和盲测集继续校准。
