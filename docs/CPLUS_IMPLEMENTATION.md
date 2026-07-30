# C+ 架构实现映射

日期：2026-07-28

> 状态说明：本文描述已接通的 C+ 主流程和 P0 硬门，不代表设计中的全部
> 语义能力已经完成。AI PDF 已增加逐页多模态严格转录；其生产准确率、原子
> Content Unit、复杂公式通用识别、embedding/reranker、独立模型家族和
> stage 精确续跑仍是明确缺口。

对应设计：[思维导图 Agent 框架设计](superpowers/specs/2026-07-17-mind-map-agent-framework-design.md)

## 1. Supervisor 与阶段

`backend/app/cplus_pipeline.py` 使用 LangGraph `StateGraph` 实现 Main Supervisor：

```text
parse
  -> strict PDF page transcription
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

每个阶段写入并可读取 SQLite 检查点。服务重启当前会复用 run 并从保留原件
重新排队；尚未按 stage input hash 精确跳过已完成调用。任何关键模型降级都会
进入 warnings/model_calls，并阻止 publish gate。

## 2. 内容单元与视觉

AI PDF 在 `MINDMAP_PDF_TRANSCRIPTION_MODE=vision_strict` 时先执行：

1. 用 Poppler 按配置 DPI 渲染全部页面，不受普通视觉抽样页数限制。
2. 使用独立的 `QWEN_VISION_MODEL` 对每页输出严格 `PageExtraction` JSON。
3. 公式块必须同时包含单行 Unicode canonical 文本与 LaTeX。
4. bbox、页码、完整性、置信度、残余 PUA、空操作数、孤立指数、不完整分式和
   LaTeX 括号均进入页级质量门。
5. 通过页按 source/image/prompt/schema/provider/model hash checkpoint；
   失败只重试该页。
6. 失败或低置信页不回退到 parser 残缺文本，不进入下游模型输入，并把 run
   标记为 `pdf_page_transcription` degraded。

本地默认文本模型为 `qwen3.7-max`，默认视觉模型为 `qwen3.7-plus`。
Qwen 上游明确把前者判为 text-only、后者判为 image/video；未知视觉型号在
生产环境 fail closed。2026-07-26 的 Token Plan 与
`qwen3.8-max-preview` 实测只保留为历史容量和协议实验，不能作为自定义应用
后端的生产资格证据。并发探测在 8 路时 8/8 页面通过质量门，12 路时 12/12
HTTP 成功但只有 11/12 通过质量门，故当前严格默认页并发和 Provider 并发
均为 8；该并发值仍需用正式端点重新验证。

同一 92 页 PDF 的隔离分页转录耗时 325.399 秒，107/107 HTTP 成功，80/92 页
通过，12 页被严格质量门拒绝。p86 仍缺两条目标式，p92 四条目标未全部恢复为
完整公式块；该结果是输入层容量与质量证据，不是完整 C+ 生产 task/run 或
公式 100% 准确率证明。

`pdfplumber` 字符几何恢复仍用于确定性审计和回归，但候选只写入
`pdf_geometry_math` 元数据，`injected_into_text=false`。它不再是生产模型
输入，因此几何层的局部成功不能替代逐页视觉转录验收。

`MINDMAP_PDF_TRANSCRIPTION_MODE=vision_nodes_strict` 会直接生成
`PageKnowledgeExtraction`。其内部 profile 由
`MINDMAP_PDF_PAGE_EXTRACTION_MODE` 控制：

- `direct` 保持原有单次页图到节点合同。
- `layout_nodes` 先按 dots.ocr 契约提取并验收布局块，再让模型只选择
  `block_id/formula_index/type/role/name`；证据、公式和 bbox 由代码继承。
- `direct_layout_fallback` 先执行完整 `direct`，只把 direct 失败页交给
  `layout_nodes`，再按原页号合并结果。这是当前代码和生产 Compose 默认值。

`direct` 与 `layout_nodes` 使用独立页级 checkpoint，输入 hash 包含 profile。
布局和节点选择分别局部重试，已成功页面不会因其他页面失败而重新调用。自动
级联在 metadata 中记录 direct/fallback attempted、accepted、failed、called
和 reused 页面。未恢复页面继续使 `complete=false`；确定性 selector fallback
写入 `degraded_pages` 并进入 C+ `degraded_components`，即使页面内容完整也
不能通过 publish gate。

GitHub-first 检索参考了 Apache-2.0
[Guardrails reask 路径回填实现](https://github.com/guardrails-ai/guardrails/blob/35c87e910daefe707f7e25916e6d5cf1d4fd3149/guardrails/actions/reask.py)
和 Apache-2.0
[olmOCR 页级 fallback 与 fallback page 计数](https://github.com/allenai/olmocr/blob/8854eda39eea58eab2724e84ad3cd0994f3b31cf/olmocr/pipeline.py)。
Guardrails 假设固定路径可原位替换，不能直接处理本仓库可变长、可重排的节点
列表；olmOCR 的 fallback 输出合同也不同。因此没有复制外部代码，只复用
“失败页局部兜底、显式记录 fallback、按文档门限阻断”的通用模式，并沿用
仓库现有两个 profile。

`backend/app/agents.py` 将同页/同 slide chunk 转换为 `ContentUnit`，保留：

- `chunk_id`
- 标题路径
- PDF 页码
- PPTX 幻灯片号
- 教学角色
- 重要度
- 原文证据

page/slide/heading 是切块硬边界，overlap 只保存在 `context_before`，不进入可
抽取正文。当前 unit 仍未完整拆成 claim/definition/formula/step 等原子层。

`backend/app/visual_analysis.py` 处理整页视觉：

1. 使用 `QWEN_VISION_MODEL` 的 OpenAI-compatible 多模态接口分析页面；
   文本角色独立使用 `QWEN_MODEL`。
2. 输出归一化 bbox。
3. 调用 `mindmap_engine.visuals.crop_regions` 裁剪。
4. 将知识区域转换为视觉 Content Unit。
5. `attach_as_media` 与附近文本节点融合，不强制成为独立节点。

当前状态机还会：

- 将 `ignore_decoration` 保存为 rejected unit，而不是静默消失。
- 将单框/批量区域裁剪失败保存为 deferred unit，并保留页码、bbox、OCR、
  summary 和 claims；deferred unit 不进入主题、分支或模型 payload。
- 为 `decompose` 裁剪写入整页 `parent_asset_id`。
- 按同页、IoU ≥ 0.5 和 pHash 距离 ≤ 4 对账 native 与 VLM crop；删除重复
  crop 时保留 rejected 决策单元指向 native asset。
- 允许 `attach_as_media` 进入 Branch Prompt，但拒绝仅由 attach 单元支持的
  独立节点。

PPTX 原生图片、图表、表格和组合图由 `mindmap_engine/visuals.py` 提取。当前
仍没有复合区域到多个子 region 的 schema，也没有完整对象级 PPT provenance；
整页渲染/VLM 失败和所有 NMS 抑制项也尚未逐项形成可复核 rejected unit。

## 3. Global Theme 与 Root Planner

`synthesize_themes` 生成 1–3 个根候选和一级主题。

- 模型可用：使用严格 JSON 输出。
- 模型不可用：根据文档标题、标题路径和内容单元生成确定性计划。
- 所有根和抽象主题必须带 `support_unit_ids`。

`build_branch_plans` 当前将一级主题确定性拆成一层子分支（实际使用 depth 1/2，
不是递归到第三层）；一级分支最多 8、leaf 最多 24，禁止新增结构 singleton，
并用 `coverage_budget` 限制节点/调用规模。真正递归规划仍是设计缺口。

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

上述 `Abstraction Induction` 是子图阶段名称，不等于已实现独立的语义抽象归纳
模型；当前主要依靠主题/结构候选、支持单元和模型提示，真正 abstraction
induction 仍是能力缺口。

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
- `jobs`

所有实际 Provider attempt 写入 `model_calls`，并通过隔离的调用 scope 记录
stage、branch ID 和 input unit IDs；token/cost、Prompt/Schema hash 与完整结果
缓存尚未实现。queued/running/failed/cancelled 任务写入 jobs；用户取消保持
cancelled，优雅停机写回 queued/interrupted，服务重启后从保留源文件重排。

## 6. 合并与审计

`canonicalize_semantic_duplicates` 执行：

- 标准化同名去重。
- 同分支近似名称合并。
- alias、证据、支持集和媒体合并。

`fuse_visual_media` 将 `attach_as_media` 视觉资产绑定到附近文本节点；仅由
attach 单元支持的独立节点会在发布前被拒绝。

`audit_coverage` 定位未覆盖的重要内容单元，并为有可定位证据的单元补建可拒绝
显式候选。deferred 视觉单元被硬隔离，不会因覆盖补建重新进入节点生成。

## 7. 父候选与校验

候选来源：

- 根到一级主题。
- 父分支到子分支。
- 分支主题到显式节点。
- 章节先验。
- 角色兼容。
- 名称和定义相似度。
- 模型或启发式局部建议。

父池限制为 root/branch/structural。每个 child 的 Top-k 在一次模型请求中批量
比较，严格校验模型返回的 child/parent ID；不再逐边调用。这将模型调用量约束
在配置上限内，是结构与启发式工程召回，不是设计中的 embedding + reranker，
concept 中层召回仍弱。

生产 Compose 要求显式配置 `QWEN_BASE_URL`、`QWEN_MODEL` 和
`QWEN_VISION_MODEL`。生产启动拒绝 Token Plan/Coding Plan key 或 endpoint、
`preview` 模型、无效 HTTPS endpoint、非 Qwen 模型和 text-only 视觉模型；
仍需验证正式端点、两个模型和凭据可调用，并由 run manifest 记录脱敏端点、
两个模型、转录参数和运行时依赖版本。

标准档：

- 一个独立 Qwen 校验调用。

高精档：

- 高风险候选前两名增加第二个独立 Qwen 校验调用。
- 两票分类不一致时调用独立 Qwen 仲裁角色。
- 校验器不可用时保留确定性票和降级记录。

## 8. 拓扑求解

`backend/app/mindmap_engine/topology.py` 使用 CP-SAT：

- 根候选恰好激活一个。
- 每个激活非根节点恰好一个父节点。
- 深度沿父边递增。
- 可选抽象节点至少拥有两个激活子节点。
- 临时保底边承担目标惩罚。

求解失败时使用确定性 NetworkX 贪心兜底。兜底边必须标记 `provisional` 并进入人工复核。

正式边要求 `direct_parent` 且 evidence 非空；当前部分 evidence 是共享 unit 的
结构 support mapping，只证明可定位和工程资格，不证明源材料已语义蕴含该直接
父子关系。CP-SAT 当前优化合法性、边分和节点预算，不代表语义全局最优。

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

每个动作要求 `expected_graph_version`，并在一个 SQLite
`BEGIN IMMEDIATE` 事务中：

1. 写入 human `DecisionRecord`。
2. 将复核项标记为 `resolved`。
3. 重新计算深度和质量。
4. 保存新 `graph_version`。

rename 也必须通过统一标签资格门；复核后会重算拓扑冲突、显式内容覆盖、
平均边分、抽象支持和 publish gate。平均边分仍不是人工父边准确率。

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

前端使用 right-first 双侧实际尺寸树布局，根分支按约 62% 高度预算优先向右，
溢出后后续分支转左；AABB 安全间距至少 24px，概览实际可见节点不超过 120。
跨链可独立开关。Inspector 显示：

- 定义、角色、来源、深度和风险。
- 父节点、子节点和跨链。
- 原文与视觉证据。
- 独立校验票。
- 决策历史。

主树与跨链在输出契约中分离，但跨链候选当前仍可在 Branch 阶段产生，尚不是
主树冻结后的独立全局召回。

## 11. 安全、保留与删除

- Provider Key 只在后端配置中读取。
- 源文件按 retention 保留以支持重放，显式删除任务时一并清理。
- 原始视觉资产按 `render_id` 隔离。
- 运行中删除先取消并等待后台 Task，再删除 SQLite、源文件和资产。
- 生产 API 使用 token + HttpOnly session 和 owner 隔离；engine/asset token
  缺失时 fail-closed。
- 资产 URL 不写 query token；同源浏览器依赖 HttpOnly session，非浏览器请求
  使用 `Authorization` 或 `X-Engine-Token`。
- 上传执行字节、页数、MIME/magic、OOXML、解压总量、压缩比和图片像素预算
  校验。
- Compose 启动前只用 `lstat` 检查 age secret 必须为普通文件、非 symlink、
  `UID=0`、`GID=10001`、`0440`，通过后才 `exec` 启动 uvicorn。
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

截至 2026-07-29，当前源码可发现 530 项后端测试；宿主 `.venv` 实际为
Python 3.11.6，只作为逻辑回归，最近一次资源受控分组结果为
526 PASS、1 SKIP，唯一 SKIP 是宿主缺少 age/age-keygen。前端在固定
Node 22.23.1、
pnpm 10.14.0 下 `pnpm test` 为 7/7 GREEN，
`pnpm exec tsc -b --pretty false`、`pnpm build`、`git diff --check`、
`compileall` 和显式生产模型占位下的 Compose config 均为 GREEN。Vite 的
`699.49 kB` chunk size warning 是非阻断体积告警。endpoint 相关宿主回归
为 85/85；当前 backend 在 v55 的 Python 3.12.13 安全运行形态下按五个
顺序容器运行 530/530，真实 age
往返不再 SKIP。仓库外未找到可独立运行且
不写入 `runtime/` 的 export evaluator，因此本轮没有新的独立 export
evaluator 计数。

最新已构建镜像为 `zlb-mindmap-agent:candidate-v55-20260729`，image ID
`sha256:cef2cd93255ce391c6f121b8bd4c339e190eabff88dae5352d351c74c2d82c0c`，
`GIT_SHA=297da939835dc9b748a33bd80d368702d7de687d-dirty`，
`Config.User=10001:10001`。镜像内 Python 3.12.13、pypdf 6.14.2、
pdfplumber 0.11.10、pylatexenc 2.11、pdfminer.six 20260107、Poppler
25.03.0、cryptography 49.0.0、age 1.2.1，`pip check` 通过。v55 固定以
v54 image ID
`sha256:7b7bd6ea56f2fc9d6347b7cc8501e50889c64178732958255c52e25c9e1fc9e4`
为 base，只覆盖 Qwen 生产 endpoint allowlist 和对应 hardening TDD；
应用树为
`12ca0b11fc0e5e1d89208ed4cab0a0b0ed8c8aa8e4146c33955eea7950071915`，
overlay tree 为
`078cc6f35b84e572e2296a9b828a2a452252be6d1980ca7cbb26d8cb31fa9f10`，
scope 为 `production-qwen-endpoint-allowlist`。image labels 记录 base
digest、应用树 SHA、overlay tree/scope、依赖清单 SHA 和 dirty revision。
v50 的独立
分页 canary manifest 会记录脱敏 endpoint、文本/视觉模型、prompt/schema
hash 和同一组运行时版本。v50
生产形态隔离实例位于 `127.0.0.1:18139`，通过加密占位 secret metadata
preflight、read-only rootfs、non-root/resource constraints 和鉴权探针；
模型列表 502 后 session 仍有效，并完成一个 `use_ai=false` manifest 验证。
容器重启后同一任务的 JSON/PNG SHA-256 分别保持为
`7e866c27789b797fa50f485c3da4d023b3c9ccbe6a29e178688d3a6d15fa2df6`
和
`a2e715c83c03f70855e353ebfa15f79fb530d6da76312367f3a4dd2bf8e44f98`。
同一 v50 image 还使用全新已知测试令牌、tmpfs 数据目录和回环端口完成
Playwright Desktop Chrome 与 Pixel 7 回归，2/2 通过；两个
`use_ai=false` 任务均 completed、各 12 节点，临时实例随后移除。
从宿主直接向 v50 容器的真实 Python PID 发送 `SIGKILL` 后，
`unless-stopped` 自动重启，`RestartCount=1`、health 恢复，既有历史与
JSON/PNG 哈希保持不变。运维侧 `docker kill` 会被 Docker 视为手工停止，
不能替代这项异常退出测试。v51 隔离实例位于 `127.0.0.1:18141`，使用独立
卷和新生成的无效测试 age secret；安全运行合同、鉴权和 `use_ai=false` 任务
通过。重启前后 JSON/PNG SHA-256 分别保持为
`d7c31092226a81335a4420e572ac3a0118085332a773b499a48739245bf06ee2`
和
`98be5a4dc4400b947ae39f2c59c81e750a3e07188f8f4bab9c8767848a4452fc`。

v51 还用当前 evaluator 生成的两页合成 artifact 完成隔离
`freeze -> tamper reject -> prepare-volumes -> cutover -> rollback`。
该 artifact 只验证部署 admission，不是生产质量证据。backup manifest
SHA-256 为
`be570793894dafc003a0ab36e2a24fcdeb366cf37273a5696d4704212d9ca7d8`，
evaluation SHA-256 为
`fd305c4d637e385fcb2bb56714715ed2e61d6774a671da4719af757fe337bffd`。
只增加一个换行的合法 JSON 在活动容器 inspect/rename 前以退出码 2 拒绝；
使用原 artifact 后成功切换到带 backup SHA/role 标签的新卷，历史和 JSON/PNG
与基线一致，rollback 又恢复原容器名、原卷和 restart policy。备份 SQLite
`quick_check=ok`，记录 1 job、1 run、1 graph version、0 model calls。

v52 进一步完成签名版隔离
`freeze -> artifact tamper reject -> bad signature reject -> prepare-volumes
-> cutover -> restart -> rollback`。backup manifest SHA-256 为
`f83881cf7b3f3f6b8afb38cba4ba3414b22c98b8500fb0d9832f47c3906b64fd`；
evaluation 与 signature sidecar SHA-256 分别为
`4c5f36af48b502d5dbf15d3ad347a0b63044778511a5edc8028480ae1f97df1d`
和
`d6761aa0ffc7e74b17973ca0f99e172bba3e68d646e02f903416a99913dc4d88`。
artifact 修改与坏签名均在活动容器 inspect/rename 前退出 2。合法 cutover、
候选重启与 rollback 后，基线任务 JSON/PNG SHA-256 始终分别为
`79986fea052817548d8fbd24359a8599cb8710abaadd6660bfdb7ec694d5211f`
和
`e23392692b6e956af4218999a238b99fe64faff82bca8376e22247b5979cdbaa`；
rollback 恢复精确 v51、原卷、原容器名与 `unless-stopped`。

保留的 `zlb-v52-isolated-20260728` 位于 `127.0.0.1:18143`，生产安全合同、
secret preflight、health 和鉴权通过。它自己的 `use_ai=false` 任务
`ef25543dc824` completed，进程重启前后 JSON/PNG SHA-256 分别保持为
`24b8e6daabd166d5d5575dcfa970da993c647c3d3646a05a8a65641b571f09fd`
与
`cd667fb67303658ea52cb27451f182a3de4fd2d8c9f1480ccd82bcfe792dcfe8`。
恢复卷 SQLite `quick_check=ok`，当前有 2 jobs、2 runs、2 graph versions、
0 model calls；不同测试 principal 之间的任务保持 404 owner 隔离。

验证结束后只执行 Docker 官方 Buildx cache prune，回收 1.139MB；没有删除
image、container 或 volume。清理前后均为 75 个 image ID、46 个容器和
85 个卷，BuildKit cache 现为 0B，公网 v4 与 v50 隔离实例仍 healthy。

v48 的 Playwright Desktop Chrome 与 Pixel 7 在
`/api/models` 返回 502 时仍可完成登录、本地任务、历史和 JSON/PNG 下载，
生产隔离容器重启后再次 2/2 通过。本地镜像没有推送 registry，因此没有
RepoDigest。

旧 Token Plan/preview 生产配置会阻止生产启动；标准 DashScope +
`qwen3.7-max` + `qwen3.7-plus` 占位配置通过静态资格门。该验证没有调用模型，
正式文本/视觉调用、26 页 canary 和 92 页生产重跑仍依赖标准正式凭据。

v12 的 p35 独立 canary 为 clean `accepted`；四路 16 页 canary 为 58/58
canonical 公式、32/32 Required Coverage、87 节点、0 duplicate、262.733 秒，
但只有 13 页 clean，p17/p32/p35 因
`node_selector_deterministic_fallback` 为 degraded。完整 artifact SHA-256
为 `9a29294114202cc7e5004178bd9c587059f042bccb8f9decb7281dac71c65e8c`。

当前 `backend.tools.production_backup` 已覆盖一致性 SQLite online backup、
uploads/assets 快照、恢复卷标签校验、端口预检、`--no-build` Compose 切换和
有界回滚清理。隔离全流程
`freeze -> prepare-volumes -> cutover -> rollback` 已通过，备份 manifest
SHA-256 为
`f6f40741c433f771cb7e85e59c9f8084f0a3d728aef8d7dfb2bde4fb19f7c6b1`。

后续部署门审计发现这条旧流程没有把统一 evaluator artifact 绑定进 freeze
manifest，因而 backup、卷和 image ID 正确仍不足以证明候选通过内容质量门。
v51 要求 `freeze` 与 `cutover` 都显式提供同一个
`--quality-evaluation`：前者在停服务前校验 candidate image、正式
Qwen/age/direct-layout 身份、当前 evaluator/canonical 模块 SHA、全部通用
子门与非空证明，并记录 artifact SHA；后者在容器 inspect、端口预检和 rename
前复验该 SHA 和 image ID。旧备份没有质量身份时拒绝切换。该合同已通过镜像
内 514/514、无模型隔离运行和 admission 全流程验证。

隔离演练随后证明，仅绑定 SHA 仍不能确认 artifact 由受信任 evaluator
产生。当前工作树已在此合同上增加 Ed25519 provenance：evaluator 使用仓库外
age 密文和独立 identity，在内存解密私钥后签最终 artifact 原始字节，生产
CLI 不接受明文私钥路径；`freeze`/`cutover` 强制接收
`--quality-signature` 和 `--quality-public-key`，验证 sidecar schema、
artifact SHA、公钥 DER SHA 和 64 字节签名；freeze manifest 保存完整签名
身份，cutover 在任何容器 inspect/rename 前重新验签并做完整身份等值比较。
这项改动使用已锁定的 `cryptography==49.0.0`，没有手写密码学或增加 Cosign
二进制。离线 `quality_signing_key` 在内存生成 Ed25519 PKCS#8 后直接通过
stdin 交给镜像已固定的 age 1.2.1 加密，只排他创建私钥密文、公钥和版本化
trust record。签名门已进入 v52，信任锚已进入 v53，age 私钥托管已进入
v54。真实 age 往返、admission 验签和 artifact 篡改拒绝探针通过；正式签名
Qwen evaluator artifact 仍未产生。

后续信任根审计补上了签名者身份门：仅由同一命令同时提供签名与公钥仍允许
任意新 key pair 自洽通过。`freeze`/`cutover` 因此额外强制
`--quality-public-key-sha256`，它必须来自独立密钥批准记录，而不是待验
sidecar。工具计算实际 Ed25519 公钥 DER SHA-256，并要求实际公钥、sidecar
身份和批准指纹三者一致；`trust_anchor_sha256` 会进入 freeze manifest，并
在 cutover 前完整对拍。该变更已进入 v53；聚焦 evaluator/backup 35/35、
宿主和镜像内完整 519/519、`pip check` 均通过。错误信任锚在停服务前拒绝，
正确信任锚能进入既有停写窗口门。

保留的 `zlb-v53-isolated-20260728` 位于 `127.0.0.1:18144`，安全运行合同、
secret preflight、health 和 401/401/200 鉴权通过。`use_ai=false` 任务
`27c9f6f9ad02` completed；重启前后 JSON/PNG SHA-256 分别保持为
`413c380481e4a30abeeac12763688b7e012f1f7bd129981487ce81684e25313f`
和
`b5ee9e5a9a4ba80a657d9c812ab4e641bd58683f54508fd514528d8a8e092d3d`。
SQLite `quick_check=ok`，1 job、1 run、1 graph version、0 model calls。

恢复卷实例已验证 3 个 jobs、10 个 runs、8 个 graph versions、339 个
model calls、999 个资产和 10 条历史；同一旧图 JSON/PNG 在容器重启前后
逐字节一致。当前仍没有真实模型 PDF 浏览器流程或公网 TLS E2E，也没有
真实 92 页源 PPTX 的 Qwen-only 生产 SLA 和人工多解金标。默认 Compose 文件名对应的 age secret
仍为 `root:root 0600`；隔离验证使用的 `.prod` 副本为 `root:10001 0440`，
正式部署必须显式指向通过 preflight 的文件。

仓库内工程硬门为：

```text
topology_valid == true
evidence_coverage == 1
provisional_edge_count == 0
pending_review_count == 0
degraded_components == []
all labels are publishable
all formal edges are direct_parent and have evidence
node_count <= 150
```

内容覆盖阈值按运行档位分别为 0.78 和 0.86。业务精度指标需要使用设计文档约定的开发集、校准集和盲测集继续校准。

当前公网映射的 `zlb-mindmap` 容器仍使用 v4 image ID
`sha256:2fedb0a26d47ce2d557f32710ba3938dda50f68e8fe21dd03c7a0a4367571d29`；
本轮未部署、重启或替换该容器。本地
`zlb-mindmap-agent:rollback-v4-20260725` 已明确指向该镜像，不能用当前公网
行为证明 v55 修复已上线。
