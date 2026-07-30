# vNext Clean-Room 实施矩阵

- 日期：2026-07-29
- 分支：`experiment/new_bone`
- 基线提交：`297da939835dc9b748a33bd80d368702d7de687d`
- 决策依据：`docs/MINDMAP_SYSTEM_REDESIGN.md` ADR-01
- 历史规格：`docs/superpowers/specs/2026-07-17-mind-map-agent-framework-design.md`
- 2026-07-30 产品审批：`docs/MINDMAP_PRODUCT_APPROVAL_RECORD.md`
- 完整执行书：`docs/MINDMAP_EXECUTION_PLAYBOOK.md`
- 当前结论：受限 S0-S3 shadow 与真实多介质 renderer 的代码和自动验证已完成；
  八项 P0 仍须关闭，生产替换仍为 No-Go

## 1. 状态定义

| 状态 | 含义 |
| --- | --- |
| 已实现 | 存在可执行代码、冻结合同和自动化测试 |
| 合同已实现，运行锁定 | 合同、策略和拒绝路径存在，但默认不启用真实外部能力 |
| 待外部证据 | 需要真实数据、标注者、用户研究、运维演练或审批，不能由代码测试替代 |
| No-Go | ADR-01 或最终发布决策明确禁止当前启用 |

“已实现”只表示本仓库中的受限 shadow 行为可执行，不表示模型质量、生产 SLO、
公网发布或教师/学生可用性已经得到证明。

## 2. Clean-Room 边界

| 不变量 | 实现 | 验证 | 状态 |
| --- | --- | --- | --- |
| 新语义链独立于旧 C+ 闭环 | `backend/vnext/` | `test_vnext_architecture_tdd.py` | 已实现 |
| 旧 runtime 不导入 vNext | AST 双向依赖扫描 | `test_legacy_runtime_does_not_import_vnext_during_s0` | 已实现 |
| vNext 不导入旧语义模块 | 禁止 `agents`、`blackboard`、`normalize`、`topology` 等 | `test_clean_room_never_imports_legacy_semantic_modules` | 已实现 |
| 唯一例外是单向旧结果 adapter | `backend/vnext/adapters/legacy_result.py` 只读 `MindMapResult` 类型 | `test_vnext_legacy_adapter_tdd.py` | 已实现 |
| Region 只由 top-down planner 写入 | `backend/vnext/orchestration/permissions.py` | `test_region_plan_has_only_top_down_writers` | 已实现 |
| Bottom-up 只能提交 `ReplanRequest` | 同上 | `test_bottom_up_role_can_only_write_replan_request` | 已实现 |
| 不修改旧 HTTP 和持久化图合同 | vNext 无 legacy route/schema 注册 | `test_vnext_legacy_contract_snapshot_tdd.py` | 已实现 |
| Shadow API 默认关闭且无导入副作用 | `backend/vnext/api/app.py` | `test_vnext_shadow_api_tdd.py` | 已实现 |

运行时唯一允许的 legacy import 为：

```text
backend.vnext.adapters.legacy_result
  -> backend.app.architecture_schemas
```

该 adapter 是有损、单向输出边界；其结果禁止回读成 Canonical Graph。

## 3. S0-S4 阶段

| 阶段 | 设计范围 | 当前证据 | 状态 |
| --- | --- | --- | --- |
| S0 合同冻结 | IR、Inventory、Region、Claim、Graph、Projection、Artifact | 34 个注册合同、34 个 schema 加 `manifest.json`；确定性导出与 RFC 8785 digest | 已实现 |
| S1 Source Shadow | PDF/PPTX/DOCX/TXT/Markdown、outline、对象、表格、假设 | `source_ir/parser.py`、`source_inventory/enumerator.py`；空页/空 slide/标题/表格 fixture | 已实现 |
| S2 Claim 与遗漏审计 | source-only claim、独立分母、三类状态、遗漏硬门 | `claims/atomizer.py`、`claims/omission.py`、`claims/audit.py` | 已实现 |
| S3 显式 top-down Region | 显式 outline/title 递归、split/stop gate、bottom-up replan | `regions/planner.py`、`regions/gates.py`、`regions/auditor.py` | 已实现 |
| S3 Canonical/Projection | explicit-only DAG、未决节点、DAG 到单父诊断视图 | `canonical_graph/builder.py`、`projection/` | 已实现 |
| S3 durable shadow | manifest、lease、CAS、outbox、stage reuse、orphan reconciliation | `orchestration/control_store.py`、`durable_pipeline.py` | 已实现 |
| S3 recorded semantic stage | 局部 `TaskEnvelope`、严格 Claim/Region proposal、独立 Region veto、完整 interaction replay | `claims/model_stage.py`、`regions/model_stage.py`、`model_runtime/adapter.py`、两个 recorded CLI | 已实现；无 live endpoint |
| S3 多介质呈现 | 同一 Projection 输出 Web/Mobile/PNG/PDF/JSON | `presentation/builder.py`、`pagination.py`、`renderer.py`、`render-shadow` CLI | 已实现；发布保持锁定 |
| S4 评测工具 | 每文档/分层门、risk-coverage、五次稳定性、泄漏检测 | `contracts/quality.py`、`quality/evaluator.py`、`pilot-evaluate` CLI | 已实现 |
| S4 真实 pilot | 12 development、18 calibration、30 sealed blind，多标注者 | 默认 policy 在数据或阈值不完整时返回 `incomplete` | 待外部证据 |
| S4 可用性 | 8 名教师、12 名学生，桌面/移动各半 | 尚无真实研究结果 | 待外部证据 |

S1 的“已实现”限定于当前原生 parser 能观察到的对象。真实 OCR/VLM、复杂公式和
化学反应若不能可靠解析，会保持原始区域或 `unresolved`，不会被自然语言猜补。

## 4. 需求到代码

| 设计要求 | 主要实现 | 主要测试 | 状态与边界 |
| --- | --- | --- | --- |
| 冻结、严格、不可变合同 | `contracts/base.py`、`contracts/registry.py`、`contracts/exporter.py` | `test_vnext_contracts_tdd.py`、`test_vnext_schema_bundle_tdd.py` | 已实现 |
| Owner-scoped opaque artifact | `artifacts/canonical.py`、`artifacts/local_store.py` | `test_vnext_contracts_tdd.py` | 已实现 |
| 原子可见与 pending reconciliation | `artifacts/local_store.py` | `test_shadow_store_reconciles_uncommitted_pending_directory` | 已实现 |
| Document IR 与 interpretation 分账 | `contracts/source.py`、`source_ir/parser.py` | `test_vnext_source_ir_tdd.py`、`test_vnext_source_shadow_tdd.py` | 已实现 |
| PDF outline/空页保留 | `source_ir/parser.py` | `test_pdf_retains_blank_pages_and_nested_outline` | 已实现 |
| PPTX 原生对象、空 slide、表格 | `source_ir/parser.py` | `test_pptx_retains_empty_slides_objects_tables_and_headers` | 已实现 |
| DOCX 标题、表格、未知分页 | `source_ir/parser.py` | `test_docx_preserves_heading_table_and_unresolved_pagination` | 已实现 |
| 独立 Source Inventory | `source_inventory/enumerator.py` | `test_vnext_claim_pipeline_tdd.py` | 已实现 |
| Source Inventory 全量对账 | `contracts/regions.py`、`regions/planner.py` | `test_vnext_gates_tdd.py`、`test_vnext_region_planner_tdd.py` | 已实现 |
| Split/Stop 不能以容量冒充语义 | `regions/gates.py` | `test_capacity_semantics_cannot_pass_split`、`test_safety_limit_cannot_turn_mixed_region_into_stop` | 已实现 |
| Bottom-up replan 最小祖先约束 | `regions/auditor.py`、`regions/gates.py` | `test_replan_must_target_affected_ancestor_path` | 已实现 |
| Claim 状态正交 | `contracts/claims.py` | `test_vnext_claims_tdd.py` | 已实现 |
| Claim Atomizer 不可自证 | `claims/atomizer.py`、合同 producer 校验 | `test_claim_extractor_cannot_self_verify` | 已实现 |
| 模型只提 Claim 候选 | `contracts/model_semantics.py`、`claims/model_stage.py` | `test_vnext_recorded_claim_stage_tdd.py` | 已实现；模型不能写稳定 ID、provenance、publication 或父边 |
| 模型只评估显式 Region 锚点 | `contracts/model_semantics.py`、`regions/model_stage.py`、`regions/planner.py` | `test_vnext_recorded_region_stage_tdd.py` | 已实现；模型不能写 Region ID、parent、ancestor path、membership 或发布状态 |
| Region verifier veto 不可覆盖 | `regions/model_stage.py`、`regions/planner.py` | `test_independent_verifier_veto_keeps_region_unresolved` | 已实现；否决后父 Region 保持 unresolved，不递归创建子 Region |
| 模型 abstain 不隐藏分母 | `ClaimLedger.unresolved_source_ids`、`claims/omission.py` | `test_model_abstention_is_unresolved_not_omitted` | 已实现 |
| 指令/练习不冒充 core fact | `claims/atomizer.py` | `test_instruction_cannot_be_promoted_to_core_fact` | 已实现 |
| 独立遗漏审计与高价值硬门 | `claims/omission.py`、`claims/audit.py` | `test_missing_high_value_source_is_not_hidden` | 已实现 |
| Canonical DAG 可多父、必须无环 | `contracts/graph.py`、`canonical_graph/builder.py` | `test_vnext_graph_projection_tdd.py` | 已实现 |
| Parentless 不补根 | `canonical_graph/builder.py`、`projection/builder.py` | `test_parentless_claim_is_blocked_not_promoted_to_root` | 已实现 |
| Veto 只能用新证据和新对象重开 | `contracts/graph.py` | `test_rejected_relation_cannot_reopen_without_novel_evidence` | 已实现 |
| TOC 只可直接认证 `topic_contains` | `canonical_graph/builder.py` | `test_outline_cannot_certify_is_a` | 已实现 |
| 跨链不改变 Projection parent | `contracts/crosslinks.py`、`canonical_graph/cross_links.py` | `test_vnext_cross_links_tdd.py` | 已实现 |
| 高风险跨链要求独立双票 | `canonical_graph/cross_links.py` | `test_high_risk_cross_link_waits_for_second_independent_vote` | 已实现 |
| Canonical 多父到 View 单父 | `contracts/projection.py`、`projection/validation.py` | `test_projection_records_alternate_canonical_parent` | 已实现 |
| 执行、质量、发布状态正交 | `contracts/control.py` | `test_execution_quality_and_publication_are_orthogonal` | 已实现 |
| Durable lease/CAS/outbox/reuse | `orchestration/control_store.py`、`durable_pipeline.py` | `test_vnext_control_plane_tdd.py`、`test_vnext_durable_pipeline_tdd.py` | 已实现；嵌套 Region replay 保持前序，单机 SQLite shadow |
| 三类 replay | `replay/store.py`、`model_runtime/adapter.py` | `test_vnext_replay_search_tdd.py`、`test_vnext_model_runtime_tdd.py` | 已实现；初始输出、retry、schema repair 和 fallback 可按完整 interaction 序列回放 |
| Provider 结构化输出与 repair | `model_runtime/adapter.py`、`claims/model_stage.py`、`regions/model_stage.py` | `test_vnext_model_runtime_tdd.py`、两个 recorded stage TDD | 已接入 durable recorded Claim 与显式 Region stage；live provider 仍锁定 |
| Provider retry/circuit/fallback | `model_runtime/adapter.py` | 同上 | 已实现 |
| Standard/Precision verifier 独立性路由 | `model_runtime/router.py` | 同上 | 已实现；独立组仍需真实 calibration |
| SearchIntent/EvidenceBundle | `contracts/integrations.py` | `test_vnext_replay_search_tdd.py` | 合同已实现，默认 no-egress |
| SSRF、重定向、脱敏、不可变 snapshot | `search/gateway.py` | `test_vnext_replay_search_tdd.py` | 已实现；没有生产 connector/fetch transport |
| Append-only 人工复核 | `contracts/review.py`、`review/store.py` | `test_vnext_review_tdd.py` | 已实现 |
| 最小受影响子树回放 | `review/planner.py`、`review/guard.py` | `test_vnext_review_tdd.py` | 已实现 |
| Pilot 最差文档/分层与稳定性 | `quality/evaluator.py` | `test_vnext_quality_harness_tdd.py` | 已实现；默认阈值未冻结 |
| Standalone shadow HTTP | `api/app.py` | `test_vnext_shadow_api_tdd.py` | 已实现，默认锁定，无发布路由 |
| 单向 legacy 下转换 | `adapters/legacy_result.py` | `test_vnext_legacy_adapter_tdd.py` | 已实现，不接旧 route/SQLite |
| Canary 阶段、release ledger 与安全回滚 | `contracts/release.py`、`orchestration/control_store.py`、`orchestration/release.py` | `test_vnext_release_governor_tdd.py` | HOLD/ADVANCE/ROLLBACK append-only 落账；指针与事件同事务；公网流量 No-Go |
| Web/Mobile/PNG/PDF/JSON 一致性 | `contracts/presentation.py`、`presentation/builder.py`、`presentation/pagination.py`、`presentation/renderer.py` | `test_vnext_presentation_tdd.py`、`test_vnext_presentation_renderer_tdd.py` | 已实现真实文件、原子 owner scope、digest 校验、CJK fail-closed；`publication_enabled=false` |

## 5. 历史规格的处理

`2026-07-17-mind-map-agent-framework-design.md` 仍作为产品目标和历史 C+ 设计记录，
但以下内容已由 2026-07-29 的 ADR-01 替代：

| 历史设计 | 当前决定 |
| --- | --- |
| 双向建图 | 结构只向下生长，证据从下向上验收 |
| Bottom-up cluster 补建父节点 | 只能提交 `ReplanRequest` |
| 无父节点时 provisional root fallback | 保持 unresolved/abstained，禁止补根 |
| 强制输出完整单父树 | Canonical 保留 DAG 和未决项，Projection 才选择展示主父 |
| Solver 为合法树发明保底边 | Solver 只能选择已验证关系；当前 explicit shadow 不启用旧 solver |
| 质量失败仍交付图 | 只保留诊断 artifact，禁止发布表达 |

继续保留的目标包括：

- PPTX、PDF、DOCX、TXT 和 Markdown 输入；
- 文本、表格、公式、反应和视觉区域的一等 provenance；
- 主层级与非层级跨链分离；
- 标准与高精档的模型角色和独立验证要求；
- 人工复核、局部失效、回放、审计和多介质一致性；
- 每文档、最差分层、稳定性和可用性质量门。

## 6. GitHub-First 记录

当前环境没有 `gh`。实现前已检查当前仓库历史、公开 GitHub issue/PR/source、
上游文档、release 和许可证。采用的是公开 API、行为约束或设计模式；除依赖包
本身外，没有复制上游项目代码。

采用或直接参考：

| 主题 | 上游证据 | 采用方式 |
| --- | --- | --- |
| JSON Schema | `https://github.com/pydantic/pydantic/blob/main/docs/concepts/json_schema.md` | 使用 Pydantic 原生 Draft 2020-12 导出 |
| RFC 8785 | `https://github.com/trailofbits/rfc8785.py/releases/tag/v0.1.4` | 使用 Apache-2.0、Python 3.12 兼容的 `rfc8785==0.1.4` |
| PDF outline | `https://github.com/docling-project/docling/pull/3688` | 采用 bookmark/ToC 作为高优先级结构信号的原则 |
| Heading hierarchy | `https://github.com/docling-project/docling/pull/3633` | 上游只调整推断层级且保持 heading 集合与顺序；Region partition、稳定 ID 和 parent 继续由本地代码持有 |
| HTTP retry | `https://github.com/encode/httpx/pull/2311` | retry 保持在应用层，并限制次数 |
| Structured output | `https://github.com/openai/openai-python/commit/4f404262955cb711c56c07cce52076b6107303e5` | 本地 schema validation 与定向 repair |
| Incomplete structured response | `https://github.com/openai/openai-python/issues/2486` | incomplete/refusal 不能当作有效 Region 决策；继续由本地严格验证 fail closed |
| 429 分类 | `https://github.com/openai/openai-python/pull/3507` | 区分可重试限流和配额硬失败 |
| Durable model side effects | `https://github.com/langchain-ai/langgraph/issues/8039`、`https://github.com/langchain-ai/langgraph/issues/7417`、`https://github.com/langchain-ai/langgraph/pull/8055` | 上游仍存在 checkpoint 后重复执行风险；不依赖未合并修复，先冻结 interaction snapshot，再由 CAS stage 消费 |
| Strict structured schema | `https://github.com/openai/openai-python/pull/2743` | 所有模型输出合同继续强制 `additionalProperties=false`，本地校验后最多一次定向 repair |
| DAG 校验 | `https://github.com/networkx/networkx/commit/e1193f66d97d45f814616562c052af36526d97af` | 参考成熟 DAG 原语，不手写一般图理论库 |
| Group split | `https://github.com/scikit-learn/scikit-learn/commit/6f8b95aa2234102acc3804fc8c7a3e6bd0506bfb` | 冻结 source-group 隔离语义 |
| Dataset digest | `https://github.com/mlflow/mlflow/pull/22274` | 数据集和 policy 分别 digest，避免弱摘要 |
| Shadow API | `https://github.com/fastapi/fastapi/commit/1d211b9c1009d577f39fa2b19b10d9a93a72a0ed` | 使用现有 FastAPI/Pydantic 模式，不改旧应用 |
| Rollout/rollback | `https://github.com/argoproj/argo-rollouts/commit/22276e383a04c85b9bcdc6a108e0578031ed2304`、`https://github.com/argoproj/argo-rollouts/issues/3039`、`https://github.com/argoproj/argo-rollouts/pull/4281`、`https://github.com/argoproj/argo-rollouts/issues/4732`、`https://github.com/argoproj/argo-rollouts/releases/tag/v1.9.1` | 采用分阶段门和独立稳定指针；上游历史依赖可回收资源、Event/日志/指标，坏 revision 标记方案仍未合并，因此本地另建 owner-scoped hash-chain ledger |
| Accessibility | `https://github.com/w3c/wcag/commit/6b34f25b875f94629c2d009863093106a1a713ee` | 固化 reflow、字号、对比度和目标尺寸合同 |
| Raster/PNG | `https://github.com/python-pillow/Pillow/blob/main/docs/reference/ImageDraw.rst` | 复用已锁定 Pillow 12.3.0 的绘制、字体和 PNG metadata API |
| PDF 文件 | `https://github.com/py-pdf/pypdf/blob/main/docs/user/handling-outlines.md`、`https://github.com/py-pdf/pypdf/blob/main/docs/user/adding-pdf-annotations.md` | 复用已锁定 pypdf 6.14.2 写入 bookmark、URI annotation 和 metadata |
| 真实 viewport 验收 | `https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/server/registry/dependencies.ts` | 使用仓库锁定 Playwright 1.62.0；宿主依赖通过官方 `install-deps chromium` 补齐 |

检索 `SourceObservationIR`、`RegionSplitCertificate`、
`minimum_replan_ancestor_id`、课程专用 Claim/Region/cross-link/pilot/review/media
合同后，没有发现同时满足 owner 隔离、Source Inventory 外部分母、top-down-only
结构权威和最小祖先重规划的兼容实现。因此这些部分使用最小本地实现。

本轮另检索 Docling `#3633`、OpenAI Python `#2486`/`#2743` 和 LangGraph
`#8039`。没有上游实现同时提供“仅显式锚点评估、Source Inventory 对账、
代码持有 Region ID/parent、独立 verifier veto、不可变 replay 和 durable CAS”；
因此复用现有 Pydantic 严格合同、recorded adapter 和 vNext stage 机制，没有新增
依赖或复制上游代码。

另检索 Argo Rollouts 的 EventRecorder、`revisionHistoryLimit`、AnalysisRun
history/TTL、rollout duration audit 和 bad-revision rollback issue/PR。其状态与
事件机制不提供本项目所需的永久逐 release 序号、previous digest、幂等追加和
指针原子提交，因此 release event store 使用现有 SQLite/CAS 模式最小实现，
未复制上游代码或引入新依赖。

未采用：

- Import Linter：现有 AST 测试已足以冻结当前小型 package 边界，无需新增依赖。
- GraphRAG/community detection：可以提供 split hint，但不能认证课程直接父边。
- Docling 全量替换：当前只借鉴 IR/provenance 思路，避免在语义整改前扩大 parser
  迁移范围。
- Temporal/Postgres：单机 shadow 尚未用真实并发和故障证据证明必须迁移。

## 7. 验证结果

2026-07-29 本分支执行：

```text
.venv/bin/python -m backend.vnext.cli export-schemas
  -> {"changed": []}

.venv/bin/python -m backend.vnext.cli export-schemas --check
  -> {"changed": []}

registry / generated schema count
  -> 34 contracts, 34 schema files, 35 files including manifest.json

.venv/bin/python -m unittest discover -s backend/tests -p 'test_vnext*.py' -v
  -> 168 passed

.venv/bin/python -m unittest discover -s backend/tests -v
  -> 704 tests run, 1 skipped

git diff --check
  -> passed

.venv/bin/python -m compileall -q backend/app backend/vnext backend/tests
  -> passed

.venv/bin/python -m pip check
  -> No broken requirements found

Playwright Chromium, 1366x768 and 390x844
  -> Canvas nonblank: 108228 non-white pixels
  -> cross-link toggle changed canvas hash: 1509434204 -> 1730844780
  -> 5/5 desktop chapter buttons in first viewport
  -> 8/8 mobile tree targets are 44 px
  -> no text clipping, body overflow, section overlap, or console errors
```

真实文件预览使用 8 节点中文图和 1 条已验证跨链，语义指纹为
`sha256:bca8712ae047007e4516bf9decc439f07418d5e049333bf61c0a31eb2d9c218a`。
输出包含 standalone HTML、1 张 PNG tile、7 页带书签和证据 URI annotation 的 PDF、
canonical JSON；桌面和移动截图保存在隔离的 Codex visualization 目录，不进入仓库。

Recorded semantic stages 另以真实 parser、Source Inventory、RegionPlan 和不可变
replay snapshot 运行：

- 每个 leaf Region 只接收局部 `TaskEnvelope` 和 source cards；
- 每个 source 必须绑定精确原文引句或显式进入 unresolved；
- replay 覆盖 initial、schema repair、retry 和 fallback 的完整 interaction 序列；
- worker 在 Ledger 写入后、CAS commit 前崩溃时，恢复只重放 snapshot，不增加
  transport 请求，并能识别未提交 artifact 为 orphan；
- 第二个相同 run policy 可复用
  `recorded-model-claim-ledger` 及全部下游 stage；
- 隔离 CLI 为 `recorded-claim-shadow`，endpoint 固定为 `.invalid` 哨兵地址，
  Manifest 保持 `no_egress=true`、`publication_status=draft`。
- Global/Recursive Region Planner 只看到当前显式 anchor、直接 child anchors 和
  scope source cards；模型合同没有稳定 Region ID、parent、ancestor path、
  membership、evidence ref 或 publication 字段。
- SPLIT 必须逐项、按 source order 重复全部直接 child anchor；STOP 只允许没有
  直接 child anchor；任何重排、越界 source 或不完整决定都 fail closed。
- 独立 Region Decision Verifier 的 REJECT/UNRESOLVED 不能被确定性 gate 覆盖，
  受影响 Region 保持 unresolved；代码继续独占 partition、稳定 ID、parent、
  `RegionPlan`、`RegionSplitCertificate` 和 artifact 写入。
- `recorded-model-explicit-region-planning` 支持写 artifact 后、CAS 前崩溃恢复；
  相同 source/policy 的后续运行直接复用 stage，不读取 replay response，也不触发
  transport。
- Region 与 Claim recorded stage 可以组合模型 portfolio、prompt/tool policy
  digest 和调用预算；隔离 CLI `recorded-region-shadow` 只接受严格的三槽
  `ModelPortfolioManifest` 与 replay map，endpoint 同样固定为 `.invalid`。

真实规格 Markdown 另以隔离临时 artifact/control root 连续运行两次。第一次结果为
`succeeded + review_required + draft`；第二次复用了
`source-shadow`、`explicit-region-planning`、`claim-ledger`、
`omission-and-region-audit`、`canonical-explicit-graph` 和
`diagnostic-projection` 全部六个阶段，并返回相同 Projection artifact ID。

2026-07-30 编制执行书前重新验证：

```text
.venv/bin/python -m unittest discover -s backend/tests -p 'test_vnext*.py' -v
  -> Ran 168 tests in 14.645s, OK

.venv/bin/python -m backend.vnext.cli export-schemas --check
  -> {"changed": []}
```

该复核只冻结执行起点，不改变八项 P0 和生产 No-Go 结论。

唯一跳过项是需要本机同时安装 `age` 与 `age-keygen` 的真实密钥往返测试，与 vNext
实现无关。测试期间出现 Starlette `TestClient`/`httpx` deprecation warning；
现有锁定依赖功能正常，本次不为消除 warning 改动依赖栈。

## 8. 尚未完成且不能伪造的证据

### 8.1 外部数据和人员

- 60 份真实文档的 12/18/30 source-group 隔离数据集。
- 每份文档至少两名标注者和学科专家仲裁。
- 五次真实模型运行的节点及直接父边稳定性。
- 8 名教师、12 名学生的形成性可用性测试。
- 扩充后的独立 sealed blind set 和生产置信区间。

### 8.2 校准和运行证据

- 未冻结的 root/Region、split/stop、boundary、fragment 和 coverage 阈值。
- Verifier `independence_group` 的错误相关性、位置偏差、措辞偏差和自偏好校准。
- 真实 provider 成本、延迟、配额和模型 revision 漂移证据。
- 多 worker contention、kill/restart、备份恢复、RTO/RPO 和灾难恢复演练。
- 真实教师/学生任务、跨浏览器、辅助技术和打印链路的可用性与兼容性证据。

### 8.3 尚未接入或默认锁定

- Live provider 尚未获准接入 durable semantic stages；当前只允许 immutable
  recorded-response replay 的 Claim Atomizer、显式 Global/Recursive Region
  Planner 和 Region Decision Verifier。
- Recorded semantic stage 尚未扩展到 Relation Verifier、Arbiter 或 VLM reader。
- Search Gateway 没有生产 search connector 和真正绑定已验证 IP 的 fetch transport。
- 非显式 recursive Region 对私有、用户可见和正式发布仍是 No-Go；只有在 Q0/Q1
  后才可申请 public-fixture shadow。
- Presentation renderer 仅由隔离的 `render-shadow` CLI/store 调用，
  `publication_enabled=false`，尚未接入公网发布 route。
- ReleaseEvent 已作为独立逻辑账本接入单机 SQLite：owner/release 序号、稳定
  event ID、previous digest、幂等决策/回滚、禁止 UPDATE/DELETE 触发器和读取时
  链校验已实现；尚无外部签名锚点、多主机 writer、备份恢复或 RTO/RPO 演练证据。
- Standalone API 只提供受保护的 shadow run/read，不提供上传、发布或 legacy route。

## 9. 解锁顺序

1. 冻结 pilot 标注规范，收集 60 文档并运行 `pilot-evaluate`。
2. 用 calibration 结果冻结阈值和 verifier independence group。
3. 关闭 Q0 P0，以已完成的 recorded/no-egress Claim 与显式 Region stages 为基线，
   用 calibration 冻结 prompt、provider revision、预算和失败门，再按 ADR-03/05
   的范围解锁 public-fixture inferred Region 和内部模型 profile pilot。
4. 完成 live search 隐私、SSRF、prompt injection、retention 和 snapshot 红队后，
   再考虑租户 opt-in。
5. 对现有 renderer 完成教师/学生任务、跨浏览器、辅助技术和打印验收；证据齐备前
   保持 `publication_enabled=false`。
6. 完成 ADR-08 公共 API 迁移证据、Q0-Q5、并发/灾备/回滚演练和 blind set 扩充后，
   才可申请 internal allowlist；public canary 仍需 release-specific 授权。

## 10. 最终边界

当前可以准确声称：

> 独立 vNext 受限 shadow 已形成可执行的
> `Document IR + Source Inventory -> explicit top-down RegionPlan ->
> Claim Ledger -> Canonical DAG -> Diagnostic Projection` 主链，并具备不可变
> artifact、耐久控制、完整 recorded model interaction 回放、复核、评测、真实
> Web/PNG/PDF/JSON shadow 输出、默认拒绝搜索和发布治理基础。

当前不能声称：

> 已完成完整生产 Agent 框架、已达到教学质量、已通过公网发布门，或可以替换
> legacy v56。

因此本实现提供了 ADR-01/02 和后续 scoped approval 的实验基础，但不自动符合这些
ADR 的正式合同。完整生产目标必须保持未完成，直到第 8 节证据、八项 P0 和 Q0-Q5
逐项满足。
