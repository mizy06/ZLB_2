# ZLB Mind Map Agent

将课程 PDF、PPTX、DOCX、TXT 或 Markdown 转换为带文本与视觉证据、唯一根和唯一主父节点的课程思维导图。

## C+ 架构

当前 `experiment/bone` 已接入 C+ 主流程骨架和第一轮 P0 工程硬门；AI PDF
已增加逐页多模态严格节点抽取，并以 `direct -> layout_nodes` 失败页级级联
作为生产默认输入链路。复杂公式的跨文档生产准确率、原子 Content Unit、
真实 embedding/reranker、独立模型家族和 stage 级精确续跑仍未闭环，不能
描述为“完整实现”或已经完成正式 92 页生产验收。

```text
确定性解析与视觉资产提取
  -> Text / Visual Content Unit Ledger
  -> Global Theme Synthesizer
  -> Root Planner
  -> 一级主题的一层确定性子分支 + Branch Team 子图并发执行
  -> 共享 SQLite 证据黑板
  -> Merge / Reassignment / Coverage Audit
  -> 结构受限父候选池 + Top-k 上限
  -> 独立校验 / 双校验 / 仲裁
  -> OR-Tools CP-SAT 主树求解
  -> NetworkX 硬校验
  -> 人工复核与图版本
  -> 主树 + 跨链 + 证据 + 质量报告
```

核心实现：

- `backend/app/cplus_pipeline.py`：LangGraph Main Supervisor 与阶段检查点。
- `backend/app/agents.py`：主题规划、一层子分支、Branch Team、覆盖审计、视觉融合和父边校验。
- `backend/app/blackboard.py`：SQLite job、内容单元、候选、模型调用、复核事务、检查点和图版本。
- `backend/app/model_provider.py`：共享连接池、Provider 并发门、有限重试、`Retry-After`、熔断和 attempt 审计。
- `backend/app/pdf_page_transcription.py`：PDF 全页多模态转录、完整 canonical
  公式门、页级重试和幂等 checkpoint。
- `backend/app/visual_analysis.py`：整页视觉理解、bbox 决策与区域裁剪。
- `backend/app/mindmap_engine/`：稳定归一、结构受限父池、CP-SAT、NetworkX 校验和视觉资产服务。
- `backend/app/review_service.py`：人工保留、删除、改父、改名和版本写入。
- `backend/app/mindmap_layout.py`：right-first 双侧实际尺寸布局、AABB 间距门和 raster 预算。
- `frontend/src/`：right-first 树形工作台、任务恢复/取消、双质量门、证据 Inspector 和复核队列。

详细设计到代码的映射见 [docs/CPLUS_IMPLEMENTATION.md](docs/CPLUS_IMPLEMENTATION.md)。

## 本地启动

后端使用 Python 3.12：

```powershell
python -m venv .venv312
.\.venv312\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv312\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

另开一个终端启动前端：

```powershell
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

访问：

- 工作台：`http://127.0.0.1:5173`
- 后端 API：`http://127.0.0.1:8000/docs`
- 外部引擎健康检查：`http://127.0.0.1:8000/v1/mindmap/health`

生产镜像会把前端静态文件和后端合并到同一个服务，工作台和 API 使用同源地址。

## 历史与本地保存

- queued、running、failed、cancelled 和 completed 任务均写入 SQLite 历史。
- 用户取消保持 cancelled；优雅停机任务写回 queued/interrupted，重启后从
  保留源文件重新排队，而不是从中断 stage 精确续跑。
- 工作台顶部的“历史记录”可重新打开或删除历史任务。
- 图版本、人工复核结果和质量报告会随历史任务一起保留。
- 结果工具栏的“保存 JSON”会下载完整结构化结果。
- 主树画布右下角的下载按钮会保存高清 PNG。

## 模型角色

当前工作台的全部模型角色统一使用一个 Provider，但文本与视觉使用独立模型
配置：

- 文本生成、父边校验和仲裁：`QWEN_MODEL`
- PDF 单页转录和整页视觉分析：`QWEN_VISION_MODEL`
- 采样温度：默认 `0.1`，用于降低结构化抽取的发散度
- 生成、父边校验、视觉理解与仲裁使用独立提示词和逻辑调用；它们仍是同一
  Qwen 模型家族，不应解释为统计独立的第二模型。

本地开发默认文本模型为 `qwen3.7-max`，默认视觉模型为
`qwen3.7-plus`。两者不再隐式共用：Qwen 上游把 `qwen3.7-max` 标记为
text-only，把 `qwen3.7-plus` 标记为 image/video；未知视觉型号在生产环境
按 text-only 处理并 fail closed。

2026-07-26 的 Token Plan 与 `qwen3.8-max-preview` 实测只保留为历史容量和
协议实验，不能证明端点可用于自定义应用后端，也不能作为正式重跑或公网切换
资格。生产启动会拒绝 `sk-sp-` Token Plan key、Token Plan/Coding Plan
endpoint、`preview` 模型、无效 HTTPS endpoint、非 Qwen 模型及已知
text-only 的视觉模型。生产 Compose 不为端点或两个模型提供默认值，必须
显式提供标准 DashScope endpoint、正式文本/视觉模型和对应凭据。

Qwen 请求使用 `temperature=0.1`、受限 `max_completion_tokens`、
`thinking_budget` 和 JSON Object 输出约束。模型检查只读取 `/models`，
不会为了检查权限额外发起一次推理；它不能替代正式视觉模型的真实图片 canary。
视觉请求使用 `image_url`。

AI PDF 在 `vision_nodes_strict` 模式下执行：

```text
PDF -> 按配置 DPI 渲染全部页面
    -> direct 页图到 PageKnowledgeExtraction
    -> canonical 公式/证据/bbox/置信度质量门
    -> 只对 direct 失败页执行 dots layout_nodes
    -> 合并通过页，未恢复页继续阻断发布
```

单页只在本页范围内重试；通过的页使用 source/image/prompt/schema/model hash
复用 checkpoint。失败或低置信页不会静默回退到残缺 parser 文本，而是从模型
输入中移除，并将 `pdf_page_knowledge` 标记为 degraded，从而阻止发布。
`direct` 与 `layout_nodes` 使用独立 checkpoint；layout 只接收 direct 失败页。
若 layout 的模型 selector 未通过合同而使用确定性 selector fallback，页面
内容可以保留，但该页写入 `degraded_pages`，C+ publish gate 必须失败，不能
记作 clean model success。
`pdfplumber` 几何候选只保存在 `pdf_geometry_math` 审计元数据中，
`injected_into_text=false`，不再参与模型输入。

`MINDMAP_PDF_PAGE_EXTRACTION_MODE` 支持：

- `direct`：只运行页图到节点的直接抽取。
- `layout_nodes`：只运行 dots 布局抽取与受布局约束的节点选择。
- `direct_layout_fallback`：先运行完整 direct，只对失败页运行
  `layout_nodes`。这是当前代码和生产 Compose 的默认值。

当前强约束禁止为了让开发集转绿，在生产 prompt 或代码中加入页码、答案、
benchmark 或单学科专用分支。开发 canary 的 canonical 答案只能存在于测试和
evaluator；生产代码继续由 AST/prompt 扫描测试约束。

### 2026-07-29 当前候选状态

- 最新已构建镜像是 `candidate-v55-20260729`
  (`sha256:cef2cd93255ce391c6f121b8bd4c339e190eabff88dae5352d351c74c2d82c0c`)。
  它固定以 v54 image ID
  `sha256:7b7bd6ea56f2fc9d6347b7cc8501e50889c64178732958255c52e25c9e1fc9e4`
  为 base，只覆盖 Qwen 生产 endpoint allowlist 和对应 TDD；镜像标签记录
  精确 base digest、应用树 SHA、overlay tree/scope、依赖清单 SHA 和 dirty
  git revision。v55 在 Python 3.12.13、non-root、read-only、cap-drop、
  no-new-privileges、3 GiB、2 CPU、256 PIDs 且无外网的五组顺序运行中为
  530/530 GREEN，真实 age 往返不再 SKIP。
- 当前源码新增独立 `pdf_page_knowledge_evaluator`，使用绑定源 PDF SHA 与
  完整选页集合的外置 oracle，统一检查 clean/degraded/failed、模型请求策略、
  53 条 canonical 公式、66 条 Required Coverage 和完整 artifact/manifest
  身份。evaluator 只接受仓库外 age 密文和独立 age identity，在内存解密
  Ed25519 私钥并签署最终 artifact 原始字节；生产 CLI 不接受明文私钥路径。
  admission 要求签名、公钥和独立批准的公钥 DER SHA-256 信任锚三者一致。
  evaluator 不被 `backend/app` 导入，oracle 不进入生产 prompt。
- 历史 v43 的同一次 26 页报告虽然标记 26/26 clean，新门仅得到 44/53
  canonical 公式、63/66 Required Coverage，并因缺少当前合同要求的 manifest 返回
  `manifest_missing` 和退出码 2；旧 clean 计数不能再作为完整质量结论。
- v48 已在 `127.0.0.1:18136` 使用全新数据卷完成非 root、只读 rootfs、
  资源限制、API/engine/asset 鉴权和 session 验证。Playwright 1.62.0 的
  Desktop Chrome 与 Pixel 7 项目均在模型列表返回 502 时完成登录、本地任务、
  历史、真实 JSON/PNG 下载和横向溢出检查；容器重启后再次 2/2 通过。
- v50 image 也已在全新测试令牌、tmpfs 数据目录和回环端口上完成相同的
  Playwright Desktop Chrome 与 Pixel 7 回归，2/2 通过；两个 `use_ai=false`
  任务均 completed、各 12 节点。测试未读取现有实例 token，临时实例已移除。
- v48 还在 `127.0.0.1:18137` 挂载从 v4 演练备份恢复的卷，验证 3 个 jobs、
  10 个 runs、8 个 graph versions、339 个 model calls、999 个资产和 10 条
  历史均可读取；同一旧图的 JSON/PNG 在重启前后 SHA-256 一致。
- 上述占位探针没有完成真实模型调用。v55 仍需标准 DashScope 正式凭据完成
  文本/视觉实际调用、26 页 canary 和 92 页正式重跑，才能晋级。
- 本机 `.prod` age 文件通过 `root:10001 0440` metadata preflight 且可解密，
  但生产资格探针返回 `token_plan_key`；没有向标准 DashScope 发出文本或视觉
  请求，该文件不能用于正式 canary。
- 独立 canary CLI 现在强制 `MINDMAP_ENV=production` 并在读取 PDF 前复用
  `validate_production_qwen_configuration`。使用当前 `.prod` 密文的
  Python 3.12 实探针先返回 `token_plan_key`，没有进入 PDF 解析；runner
  文件 SHA 同时写入 manifest。
- v40 的 26 页 direct canary 为 17/26；对 9 个 direct 失败页单独运行
  `layout_nodes` 时恢复 8 页。p71 在独立 direct 诊断中通过，说明两条链路
  互补，但这些分散运行不能人工拼成 26/26 生产证据。
- 26 页与 92 页正式 canary 必须使用标准 DashScope endpoint、正式 Qwen
  文本/视觉模型和对应生产凭据；旧 Token Plan 结果不得拼接为生产证据。

正式使用前先在独立 evaluator 主机执行一次密钥仪式。私钥在内存生成后直接
通过 stdin 交给 age，加密完成前不会写入文件系统：

```bash
umask 077
install -d -m 0700 /secure/quality-evaluator
age-keygen -o /secure/quality-evaluator/age-identity.txt
AGE_RECIPIENT="$(
  age-keygen -y /secure/quality-evaluator/age-identity.txt
)"

.venv/bin/python -m backend.tools.quality_signing_key \
  --age-recipient "$AGE_RECIPIENT" \
  --encrypted-private-key-output \
    /secure/quality-evaluator/quality-ed25519-private.pem.age \
  --public-key-output \
    /secure/quality-evaluator/quality-ed25519-public.pem \
  --trust-record-output \
    /secure/quality-evaluator/quality-ed25519-trust.json
```

工具以排他创建方式输出 `0600` age 密文、`0644` PEM 公钥和 `0644` trust
record，拒绝覆盖已有文件。trust record 记录公钥 DER、PEM 和私钥密文的
SHA-256，不包含明文私钥。

正式 26 页报告生成后，使用同一 artifact 执行：

```bash
.venv/bin/python -m backend.tools.pdf_page_knowledge_evaluator \
  --report /path/to/26-page-canary.json \
  --oracle backend/tests/fixtures/quantum_92page_26page_quality_oracle.json \
  --output /path/to/26-page-evaluation.json \
  --signing-key-age \
    /secure/quality-evaluator/quality-ed25519-private.pem.age \
  --signing-key-age-identity \
    /secure/quality-evaluator/age-identity.txt \
  --signature-output /path/to/26-page-evaluation.sig.json
```

age identity 和加密私钥只能保存在 evaluator 主机的仓库外受控路径，不得
复制进应用镜像、运行目录或 Git。部署侧只接收 PEM 公钥、evaluation、
signature sidecar，以及经独立批准流程交接的 trust record
`public_key_sha256`；不得从待验 sidecar 自行推导批准值。

### 2026-07-26 分页转录实测

使用现有 Qwen Token Plan、`qwen3.8-max-preview`、192 DPI、单次请求 180 秒
超时，对真实 PDF 页面做并发探测：

| 并发 | HTTP 200 | 质量门通过 | 墙钟 | 吞吐 |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1/1 | 1/1 | 24.54s | 2.45 页/分 |
| 2 | 2/2 | 2/2 | 19.70s | 6.09 页/分 |
| 4 | 4/4 | 4/4 | 22.07s | 10.87 页/分 |
| 6 | 6/6 | 6/6 | 34.55s | 10.42 页/分 |
| 8 | 8/8 | 8/8 | 28.69s | 16.73 页/分 |
| 12 | 12/12 | 11/12 | 36.46s | 19.75 页/分 |

未观察到 429、超时或传输错误，说明已观察到的传输容量至少为 12；并发 12
有一页被内容质量门拒绝，因此严格生产默认采用并发 8，而不是把 HTTP 200
等同于页面可接收。

同一 92 页 PDF 使用页并发和 Provider 并发均为 8、最多两次页级尝试：

- 渲染 42.712 秒，转录 282.687 秒，总计 325.399 秒，19.527 页/分；
- 107/107 次 HTTP 请求成功，15 次页级重试，无 429、超时或传输错误；
- HTTP 延迟 p50 17.890 秒、p95 40.610 秒、最大 50.353 秒；
- 80/92 页通过严格质量门；失败页为
  `17, 18, 21, 29, 30, 32, 34, 35, 42, 47, 62, 87`；
- p84、p85、p88 的目标公式已恢复；p86 仍缺 `ν_k`、`Δν_k` 目标式，
  p92 的四个强度/功率/温度目标未全部作为完整公式块恢复。

因此该分页转录运行的 `complete=false`。它证明 8 路分页转换可在约 5 分
25 秒完成传输和质量检查，但不是公式 100% 准确、完整 C+ 任务完成或公网生产
晋级证据。

### 2026-07-26 16 页 `layout_nodes` canary

在旧 92 页转录后，又对 16 个跨学科高风险页面运行了 `dots` 布局转录加节点
选择 canary。当前 v12 完整 artifact 的 SHA-256 为
`9a29294114202cc7e5004178bd9c587059f042bccb8f9decb7281dac71c65e8c`：

- 58/58 个 canonical 公式完整匹配，Required Coverage 为 32/32；
- 生成 87 个节点，duplicate 为 0；
- 墙钟 262.733 秒，共 36 次 HTTP attempt，36 次均为 HTTP 200/stop；
- HTTP p50/p95/max 为 22.957/40.002/87.996 秒；
- 按当前三态口径为 13 页 `accepted`、p17/p32/p35 `degraded`、0 页
  `failed`，页面完成度 16/16；三页均因节点选择两次未通过质量门后使用
  `node_selector_deterministic_fallback`，不能记作 clean model success；
- p35 独立单页复测为 clean `accepted`，74.336 秒、6/6 公式、2/2 Required
  Coverage、11 节点、0 duplicate。这与四路并发时 p35 降级共同说明当前
  selector 结果仍有运行间波动。

这轮 canary 已恢复所选 p86/p87 和 p92 的完整目标内容，但它不是 92 页全量
生产 task/run，也没有验证最终父边、全局去重、PNG 或总 SLA。当前生产
prompt 不包含 canary 页码、完整答案或 Required Coverage 文本；
答案只存在于 `backend/tools/pdf_layout_ab.py`、外置 oracle 和测试。
确定性后处理只做通用
格式等价、受支持 LaTeX 转 Unicode 以及由同页可见证据支持的修复。当前硬
约束禁止为了开发集转绿，在生产 prompt 或代码中加入页码、答案、benchmark、
单学科或单版式专用分支。

运行档位：

- `standard`：Qwen 生成角色 + 独立 Qwen 校验角色 + CP-SAT。
- `precision`：高风险父边增加第二个独立 Qwen 校验调用；分歧时调用独立
  Qwen 仲裁角色。

任一模型角色不可用时只降级对应阶段。关键 fallback 会进入
`degraded_components`/`warnings` 并阻止发布。视觉装饰项会作为 rejected
单元留账，区域裁剪失败会作为 deferred 单元留账并与生成 payload 隔离；
`decompose` 裁剪保留整页父资产，native/VLM crop 会按 IoU+pHash 对账。
`attach_as_media` 可作为媒体上下文，但仅由 attach 单元支持的独立节点不能
发布。复合区域拆成多个子 region、整页失败和所有 NMS 抑制项的完整落账仍缺失。

## 配置

支持以下环境变量：

```text
QWEN_API_KEY
QWEN_BASE_URL
QWEN_MODEL
QWEN_VISION_MODEL
QWEN_TEMPERATURE
QWEN_SECRETS_FILE
QWEN_AGE_IDENTITY_FILE
AGE_EXECUTABLE

MINDMAP_DATA_DIR
MINDMAP_BLACKBOARD_PATH
MINDMAP_SOLVER_TIMEOUT_SECONDS
MINDMAP_VISION_MAX_PAGES
MINDMAP_PDF_TRANSCRIPTION_MODE
MINDMAP_PDF_PAGE_EXTRACTION_MODE
MINDMAP_PDF_TRANSCRIPTION_DPI
MINDMAP_PDF_TRANSCRIPTION_CONCURRENCY
MINDMAP_PDF_TRANSCRIPTION_MAX_ATTEMPTS
MINDMAP_PDF_TRANSCRIPTION_MIN_CONFIDENCE
MINDMAP_ENV
MINDMAP_API_TOKEN
MINDMAP_MAX_UPLOAD_BYTES
MINDMAP_MAX_DOCUMENT_PAGES
MINDMAP_MAX_IMAGE_PIXELS
MINDMAP_MAX_CONCURRENT_JOBS
MINDMAP_PROVIDER_CONCURRENCY
MINDMAP_PROVIDER_TIMEOUT_SECONDS
MINDMAP_PROVIDER_MAX_ATTEMPTS
MINDMAP_PROVIDER_RETRY_BASE_SECONDS
MINDMAP_PROVIDER_RETRY_DELAY_CAP_SECONDS
MINDMAP_PROVIDER_CIRCUIT_COOLDOWN_SECONDS
MINDMAP_EXPORT_CONCURRENCY
MINDMAP_SOURCE_RETENTION_HOURS

EXTERNAL_ENGINE_TOKEN
ASSET_ACCESS_TOKEN
ASSET_PUBLIC_BASE_URL
```

后端启动时按以下顺序取得密钥：

1. 当前进程已有的 `QWEN_API_KEY`。
2. 使用本机 age 私钥解密 `qwen.enc.env.age`，只在内存中解析并写入当前后端进程的 `QWEN_API_KEY`。

默认密文和私钥位于仓库的 `runtime/secrets/`。可通过环境变量覆盖。解密过程不会生成明文文件，API Key 不会发送到前端、日志或 SQLite 决策记录。`runtime/` 已被 Git 忽略。

浏览器视觉资产 URL 不再携带长期 query token；同源页面使用 HttpOnly session，
非浏览器客户端使用 `Authorization` 或 `X-Engine-Token`。若设置跨域
`ASSET_PUBLIC_BASE_URL`，浏览器不会自动继承当前同源 session，生产建议通过
同源反向代理暴露资产。不要把 `ASSET_ACCESS_TOKEN` 放回 URL query。

每次 Provider attempt 会关联 stage、branch 和 input unit；当前尚未记录
token/cost，也没有全部模型角色的完整结果缓存。PDF 页转录 checkpoint 已包含
source SHA、page、image SHA、prompt/schema、provider 和 model 输入 hash。
每个 run manifest 记录脱敏端点、文本/视觉模型、页转录参数，以及 Python、
pypdf、pdfplumber、pdfminer.six、Poppler、git 和镜像版本。

## 任务 API

- `POST /api/jobs`：上传课件并启动 C+ Supervisor。
- `POST /api/jobs/{task_id}/cancel`：取消并等待后台 Task 收口。
- `GET /api/jobs/{task_id}`：读取任务和最新图版本。
- `GET /api/jobs/{task_id}/versions`：列出图版本。
- `GET /api/jobs/{task_id}/versions/{version}`：读取指定版本。
- `POST /api/jobs/{task_id}/reviews/{review_id}/resolve`：提交人工复核。
- `DELETE /api/jobs/{task_id}`：删除任务、黑板记录和视觉资产。

低代码外部引擎接口保持兼容：

- `POST /v1/chunks`
- `POST /v1/mindmap/normalize`
- `POST /v1/mindmap/solve`
- `POST /v1/mindmap/validate`
- `POST /v1/mindmap/assemble`
- `POST /v1/mindmap/visuals/render`
- `POST /v1/mindmap/visuals/crop`
- `GET /v1/mindmap/assets/{render_id}/{filename}`

## 质量门

主任务结果同时报告：

- 唯一根、唯一父、无环和根可达。
- 最终节点证据覆盖率。
- 重要内容加权覆盖率。
- 抽象节点支持率。
- 主父边平均工程分数（不是人工金标准确率）。
- 临时保底边数量。
- 待人工复核数量。

结果区分结构门和发布门。发布门至少要求：

```text
topology_valid == true
evidence_coverage == 1
provisional_edge_count == 0
pending_review_count == 0
degraded_components == []
all(labels are publishable)
all(tree_edges are direct_parent and have evidence)
node_count <= 150
weighted_content_coverage >= 0.78  # standard
weighted_content_coverage >= 0.86  # precision
```

其中边 `evidence` 当前表示可定位的共享 unit/support mapping 工程资格，
不等于源材料已语义蕴含该直接父子关系；直接父准确率仍需人工金标评测。
跨链当前仍可能在 Branch 阶段产生，不是主树冻结后的独立全局召回。

## 测试

```powershell
.\.venv312\Scripts\python.exe -m unittest discover -s backend\tests -v

cd frontend
pnpm test
pnpm build
```

测试覆盖页/slide 硬边界、异常标签、视觉采样与 pHash、分支/节点预算、child
级父边校验、CP-SAT 拒绝、复核 CAS 事务、Provider 重试/熔断、任务取消、
上传边界、10/120/336/1000 节点零碰撞布局和前端任务状态机。

截至 2026-07-29，当前源码可发现 530 项后端测试。宿主 `.venv` 实际为
Python 3.11.6，只作为逻辑回归；为避免资源压力，宿主最近一次五进程分组
合并结果为 526 PASS、1 SKIP，唯一 SKIP 是缺少 age/age-keygen。v54 在
完成签名私钥托管后为 527/527；本轮 endpoint 相关宿主回归为 85/85。
v55 在 Python 3.12.13、非 root、read-only/cap-drop/no-new-privileges、
资源限制和无外网形态下按五个顺序容器运行，530/530 GREEN。前端在固定
Node 22.23.1、pnpm 10.14.0 下
`pnpm test` 为 7/7 GREEN，
`pnpm exec tsc -b --pretty false` 和 `pnpm build` 成功；`git diff --check`、
`compileall` 和显式生产模型占位下的 Compose config 也均为 GREEN。Vite 在
production build 中报告 `699.49 kB` chunk size warning，这是非阻断体积告警，
不是构建失败。v55 继承统一 evaluator、oracle、签名信任锚 admission、
age 加密私钥托管和离线密钥仪式，并新增正式 Qwen endpoint allowlist；
上述能力均由 Python 3.12 回归覆盖。
仓库外没有找到可独立运行且不写入
`runtime/` 的 export evaluator，因此没有沿用历史 5/5 冒充本轮结果。

浏览器层已补充 Playwright 1.62.0 Desktop Chrome 与 Pixel 7 回归：v47
未修复前端在 `/api/models` 返回 502 时 2/2 RED；v48 源码与生产镜像在
session、模型不可用状态、本地任务、历史、JSON/PNG 下载和横向溢出上 2/2
GREEN，且生产隔离容器重启后再次 2/2 GREEN。这仍不能替代真实源 PPTX、
正式模型生产 SLA、进程强杀恢复或人工业务金标。

## Docker

镜像安装 age、LibreOffice Impress 与 Poppler，并在构建阶段生成前端生产包：

```powershell
docker build -t zlb-mindmap-agent .
```

生产部署使用 `compose.prod.yml`。服务器需要在
`runtime/secrets/` 中提供：

```text
qwen.enc.env.age
qwen-age-identity.txt
```

生产 Compose 要求显式提供三个不同用途的 token，并建议由 TLS 反向代理
转发到仅监听主机回环地址的 `5173`：

```bash
sudo chown 0:10001 -- \
  runtime/secrets/qwen-age-identity.txt \
  runtime/secrets/qwen.enc.env.age
sudo chmod 0440 -- \
  runtime/secrets/qwen-age-identity.txt \
  runtime/secrets/qwen.enc.env.age

.venv/bin/python -m backend.app.secret_preflight \
  --expected-uid 0 \
  --expected-gid 10001 \
  --expected-mode 0440 \
  runtime/secrets/qwen-age-identity.txt \
  runtime/secrets/qwen.enc.env.age

export MINDMAP_API_TOKEN="..."
export EXTERNAL_ENGINE_TOKEN="..."
export ASSET_ACCESS_TOKEN="..."
export QWEN_BASE_URL="https://正式生产端点/v1"
export QWEN_MODEL="受支持的正式文本模型"
export QWEN_VISION_MODEL="受支持的正式视觉模型"
export QWEN_AGE_IDENTITY_SOURCE_FILE="runtime/secrets/qwen-age-identity.txt"
export QWEN_ENCRYPTED_ENV_SOURCE_FILE="runtime/secrets/qwen.enc.env.age"
```

Compose 只映射 `127.0.0.1:5173`，容器使用非 root UID、只读根文件系统、
`cap_drop: ALL`、`no-new-privileges`、CPU/内存/PID 限制。SQLite、资产和
保留源文件分别进入持久卷。`runtime/`、私钥、公钥和明文 ENV 均被 Git 忽略。
本地 Compose 的 file-secret 不支持用 YAML `mode/uid/gid` 改写宿主权限，
因此宿主 `root:10001 0440` 和 preflight 是实际启动前置条件，不能只看
`docker compose config` 成功。

端点和两个模型变量必须与实际凭据一起显式配置，并写入新任务的 run
manifest。`preview` 模型、Token Plan/Coding Plan endpoint 或 key、无效
endpoint 及 text-only 视觉模型都会阻止生产启动。

正式切换不在停写窗口内现场构建镜像。先完成候选镜像测试和隔离验收，再阻断
反向代理的新写请求，使用 `backend.tools.production_backup` 完成一致性备份、
新卷恢复、`--no-build` 切换和可回滚保留：

```bash
export CANDIDATE_IMAGE="<validated-candidate-tag>"
export CANDIDATE_IMAGE_ID="<validated-candidate-image-id>"
export QUALITY_EVALUATION="<validated-evaluation-json>"
export QUALITY_SIGNATURE="<validated-evaluation-signature-json>"
export QUALITY_PUBLIC_KEY="<trusted-evaluator-ed25519-public-key-pem>"
export QUALITY_PUBLIC_KEY_SHA256="<approved-public-key-der-sha256>"
export BACKUP_DIR="<final-backup-directory>"
export CANDIDATE_DATA_VOLUME="<new-candidate-data-volume>"
export CANDIDATE_UPLOADS_VOLUME="<new-candidate-uploads-volume>"
export ROLLBACK_CONTAINER="<rollback-container-name>"

.venv/bin/python -m backend.tools.production_backup freeze \
  --container zlb-mindmap \
  --rollback-image zlb-mindmap-agent:rollback-v4-20260725 \
  --candidate-image "$CANDIDATE_IMAGE" \
  --quality-evaluation "$QUALITY_EVALUATION" \
  --quality-signature "$QUALITY_SIGNATURE" \
  --quality-public-key "$QUALITY_PUBLIC_KEY" \
  --quality-public-key-sha256 "$QUALITY_PUBLIC_KEY_SHA256" \
  --output "$BACKUP_DIR" \
  --stop-container \
  --stop-timeout-seconds 60

.venv/bin/python -m backend.tools.production_backup prepare-volumes \
  --backup-dir "$BACKUP_DIR" \
  --data-volume "$CANDIDATE_DATA_VOLUME" \
  --uploads-volume "$CANDIDATE_UPLOADS_VOLUME"

.venv/bin/python -m backend.tools.production_backup cutover \
  --backup-dir "$BACKUP_DIR" \
  --compose-file compose.prod.yml \
  --project-name zlb-production \
  --active-container zlb-mindmap \
  --rollback-container "$ROLLBACK_CONTAINER" \
  --image-ref "$CANDIDATE_IMAGE" \
  --expected-image-id "$CANDIDATE_IMAGE_ID" \
  --quality-evaluation "$QUALITY_EVALUATION" \
  --quality-signature "$QUALITY_SIGNATURE" \
  --quality-public-key "$QUALITY_PUBLIC_KEY" \
  --quality-public-key-sha256 "$QUALITY_PUBLIC_KEY_SHA256" \
  --data-volume "$CANDIDATE_DATA_VOLUME" \
  --uploads-volume "$CANDIDATE_UPLOADS_VOLUME" \
  --bind-host 127.0.0.1 \
  --public-port 5173 \
  --health-url http://127.0.0.1:5173/api/health \
  --health-timeout-seconds 90
```

`QUALITY_PUBLIC_KEY_SHA256` 必须来自密钥批准/交接记录中的公钥 DER
SHA-256，不能从正在验收的 signature sidecar 临时复制。`freeze` 会在停止
生产容器前先要求实际 Ed25519 公钥匹配该独立信任锚，再验证统一质量 artifact
的原始字节和 signature sidecar，随后验证 candidate image ID、
Qwen/age/direct-layout manifest、当前 evaluator 与 canonical oracle 模块
SHA-256、全部通用子门，以及非空的公式、Required Coverage 和知识证明。
artifact SHA-256、signature sidecar SHA-256、公钥 DER SHA-256、算法和 image
ID 会写入最终备份 manifest，其中 `trust_anchor_sha256` 明确记录批准的信任根。
`cutover` 会在 inspect 活动容器、探测端口或 rename 前使用同一批准指纹重新
验签，并要求完整质量身份与 freeze manifest 逐字段一致。旧备份 manifest
缺少签名或信任锚身份时 fail closed；不能只凭备份存在、镜像 tag、一份结构
合法的自制 JSON，或随签名一起提供的任意新公钥进入切换。

需要回滚时使用备份 manifest 中记录的精确 v4 image ID：

```bash
.venv/bin/python -m backend.tools.production_backup rollback \
  --active-container zlb-mindmap \
  --rollback-container "$ROLLBACK_CONTAINER" \
  --expected-image-id sha256:2fedb0a26d47ce2d557f32710ba3938dda50f68e8fe21dd03c7a0a4367571d29
```

`cutover` 会在重命名旧容器前真实探测宿主 IP/端口；候选清理会区分
`created/exited` 和 `running` 状态并有界等待名称释放。Compose 启动固定使用
`--no-build`。任何候选部署或健康检查失败都会尝试恢复保留容器；仍需在切换后
逐项验证历史、鉴权和真实 JSON/PNG 导出，再解除外部停写。

2026-07-29 最新已构建镜像为
`zlb-mindmap-agent:candidate-v55-20260729`，image ID：

```text
sha256:cef2cd93255ce391c6f121b8bd4c339e190eabff88dae5352d351c74c2d82c0c
```

镜像内 `GIT_SHA=297da939835dc9b748a33bd80d368702d7de687d-dirty`，
`Config.User=10001:10001`，Python 3.12.13、pypdf 6.14.2、pdfplumber
0.11.10、pylatexenc 2.11、pdfminer.six 20260107、Poppler 25.03.0，
cryptography 49.0.0，`pip check` 通过。v55 以固定 v54 image ID
`sha256:7b7bd6ea56f2fc9d6347b7cc8501e50889c64178732958255c52e25c9e1fc9e4`
为 base，只覆盖 `backend/app/config.py` 和对应生产 hardening TDD；
应用树为
`12ca0b11fc0e5e1d89208ed4cab0a0b0ed8c8aa8e4146c33955eea7950071915`，
overlay tree 为
`078cc6f35b84e572e2296a9b828a2a452252be6d1980ca7cbb26d8cb31fa9f10`，
scope 为 `production-qwen-endpoint-allowlist`。镜像内 Python 3.12 在 non-root、
read-only、cap-drop/no-new-privileges、3 GiB、2 CPU、256 PIDs 和无外网
形态下五组顺序运行 530/530；Compose config、标准/第三方/计划型 endpoint
admission、真实 age 往返、签名 admission 与篡改拒绝探针均通过。

v53 的信任锚 admission 演练使用临时测试 key：错误的批准指纹即使同时传入
`--stop-container` 也在停服务前退出 2，源容器保持 running 且未生成备份；
正确指纹能通过验签，随后因未传 `--stop-container` 按停写合同拒绝。保留的
`zlb-v53-isolated-20260728` 位于 `127.0.0.1:18144`，安全合同和
401/401/200 鉴权通过；`use_ai=false` 任务 `27c9f6f9ad02` completed，
重启前后 JSON/PNG SHA-256 分别保持为
`413c380481e4a30abeeac12763688b7e012f1f7bd129981487ce81684e25313f`
和
`b5ee9e5a9a4ba80a657d9c812ab4e641bd58683f54508fd514528d8a8e092d3d`。
SQLite `quick_check=ok`，卷中有 1 job、1 run、1 graph version、0 model calls。

`zlb-v55-isolated-20260729` 已在 `127.0.0.1:18146` 完成验证，复用既有
无效测试 Qwen age secret，没有读取正式凭据。secret preflight、health、
安全运行合同和未认证/错 token/有效 token 的 401/401/200 均通过；验证后
已停止但保留。v54 与 v53 隔离容器也保持停止并保留，公网 v4 未停止、重启
或替换。

v52 已完成 Ed25519 签名版隔离 admission 演练。演练使用独立 v51 源容器、
独立卷和回环端口 `18142`，以及明确不可晋级的两页合成 artifact 与临时测试
私钥。freeze backup manifest SHA-256 为
`f83881cf7b3f3f6b8afb38cba4ba3414b22c98b8500fb0d9832f47c3906b64fd`；
evaluation SHA-256 为
`4c5f36af48b502d5dbf15d3ad347a0b63044778511a5edc8028480ae1f97df1d`；
signature sidecar SHA-256 为
`d6761aa0ffc7e74b17973ca0f99e172bba3e68d646e02f903416a99913dc4d88`。
仅修改 artifact 字节和损坏签名内容都在活动容器 inspect/rename 前退出 2；
恢复原签名后，cutover 使用 v52 与带 manifest/role 标签的新卷成功启动。
基线、v52、v52 重启和 rollback 后的 JSON/PNG SHA-256 始终分别为
`79986fea052817548d8fbd24359a8599cb8710abaadd6660bfdb7ec694d5211f`
和
`e23392692b6e956af4218999a238b99fe64faff82bca8376e22247b5979cdbaa`。
rollback 恢复精确 v51、原卷、原容器名和 `restart=unless-stopped`；公网 v4
全程保持 healthy。

保留的生产形态 v52 隔离实例 `zlb-v52-isolated-20260728` 位于
`127.0.0.1:18143`，使用恢复卷和独立测试 principal。non-root、read-only
rootfs、cap drop、no-new-privileges、资源限制、secret preflight、health 和
401/401/200 鉴权通过。它自己的 `use_ai=false` 任务
`ef25543dc824` completed；重启前后 JSON/PNG SHA-256 分别保持为
`24b8e6daabd166d5d5575dcfa970da993c647c3d3646a05a8a65641b571f09fd`
和
`cd667fb67303658ea52cb27451f182a3de4fd2d8c9f1480ccd82bcfe792dcfe8`。
SQLite `quick_check=ok`，卷中共有 2 jobs、2 runs、2 graph versions、
0 model calls；不同测试 principal 看不到彼此任务，owner scope 返回 404。
这些结果仍不是正式 Qwen 模型质量证据。

生产形态隔离容器 `zlb-v51-isolated-20260728` 使用回环端口 `18141` 和独立
数据/上传卷。它使用新生成的无效测试 Qwen age 密文，不读取既有实例凭据；
secret metadata preflight、non-root、read-only rootfs、cap drop、
no-new-privileges、3 GiB、2 CPU、256 PIDs 和 health 均通过。未认证及错误
token 的 history 均为 401，有效 Bearer token 为 200。一个 `use_ai=false`
任务 `e70fe35cac8a` completed，run manifest 记录 v51 image ID、标准
DashScope 脱敏 endpoint、正式文本/视觉模型和固定运行时版本。JSON 为
24058 bytes、SHA-256
`d7c31092226a81335a4420e572ac3a0118085332a773b499a48739245bf06ee2`；
PNG 为 18403 bytes、SHA-256
`98be5a4dc4400b947ae39f2c59c81e750a3e07188f8f4bab9c8767848a4452fc`，
文件头为 `89504e470d0a1a0a`。容器重启后历史仍可读，两个导出文件逐字节
一致。这不是实际 Qwen 文本或视觉调用，也不是通过的统一质量 artifact。

同一 v51 隔离实例随后完成了当时的无签名 SHA admission 全流程演练。演练
使用由当前 evaluator 生成、明确标记为不可晋级的两页合成 artifact，只验证
部署线路：

```text
freeze
  -> tampered evaluation SHA 拒绝且不 rename
  -> prepare-volumes
  -> 原始 evaluation 成功 cutover
  -> 历史与 JSON/PNG 对拍
  -> rollback
  -> 原容器名、原卷和 restart policy 恢复
```

backup manifest SHA-256 为
`be570793894dafc003a0ab36e2a24fcdeb366cf37273a5696d4704212d9ca7d8`，
其中绑定的 evaluation SHA-256 为
`fd305c4d637e385fcb2bb56714715ed2e61d6774a671da4719af757fe337bffd`。
仅追加换行的 evaluation 仍是合法 JSON，但 cutover 以退出码 2 在 Docker
inspect/rename 前拒绝。成功切换和回滚后的 JSON/PNG 均与上述基线哈希一致；
备份 SQLite `quick_check=ok`，包含 1 job、1 run、1 graph version、0 model
calls。该合成 artifact 不能替代正式 26 页 source-gold evaluator 结果，也
不能证明 artifact 来自受信任 evaluator。当前工作树已经新增 Ed25519 签名门，
但该代码不在 v51 中；必须构建新候选并重新完成签名版隔离演练。

生产形态隔离容器 `zlb-v50-isolated-20260728` 使用回环端口 `18139`，完成
secret metadata preflight、非 root、只读 rootfs、health、资源限制和
API/engine/asset
fail-closed 鉴权；未认证 history 为 401，有效 session 和 history 为 200，
模型列表 502 后 session 仍有效。一个 `use_ai=false` 任务完成后，run manifest
记录标准 DashScope 脱敏 endpoint、`qwen3.7-max`、`qwen3.7-plus`、Python
3.12.13 和固定 PDF/Poppler 版本。容器重启后仍可读取任务
`10dc594affec`；JSON 为 42784 bytes，SHA-256
`7e866c27789b797fa50f485c3da4d023b3c9ccbe6a29e178688d3a6d15fa2df6`，
PNG 为 29020 bytes，SHA-256
`a2e715c83c03f70855e353ebfa15f79fb530d6da76312367f3a4dd2bf8e44f98`
且文件头为 `89504e470d0a1a0a`。这不是实际 Qwen 文本或视觉调用。

同一 v50 image 的临时浏览器实例使用全新已知测试令牌、tmpfs 数据目录和
`127.0.0.1:18140`，没有读取现有实例 token。Playwright 1.62.0 的 Desktop
Chrome 与 Pixel 7 均通过 session、模型列表 502、`use_ai=false`、历史、
真实 JSON/PNG 下载、画布可见性和横向溢出检查，结果 2/2；两个任务均
completed、各 12 节点。桌面截图为 `1440x1000`，移动端完整页面截图为
`1082x5898`，均通过非空像素检查。临时实例随后自动移除。

v50 还完成了真实进程异常退出恢复验证。Docker 上游明确说明运维侧
`docker stop/kill` 属于手工停止，会暂时抑制 restart policy，因此该命令不
能作为崩溃自动拉起测试。改为从宿主直接向隔离容器的真实 Python PID 发送
`SIGKILL` 后，`unless-stopped` 自动重启，`RestartCount=1`、health 恢复，
任务 `10dc594affec` 的历史数量与上述 JSON/PNG 哈希均不变。公网 v4 全程
保持 healthy。

v49 完整应用基线镜像仍保留为
`sha256:851af6cedb23bac039dcf48e0dd5641f02b1f2b3350a2ae2b5e6d4c87986d9b7`；
`zlb-v49-isolated-20260728` 仍位于 `127.0.0.1:18138`，未被 v50 删除或覆盖。

v48 生产形态隔离容器 `zlb-v48-isolated-20260728` 使用回环端口 `18136`；
模型列表 502 不再撤销有效 session，桌面/移动浏览器可继续使用历史和
`use_ai=false` 工作流，容器重启前后 E2E 均为 2/2。

恢复卷实例 `zlb-v48-history-20260728` 使用回环端口 `18137`，已核对 SQLite
`quick_check=ok`、3 个 jobs、10 个 runs、8 个 graph versions、339 个
model calls、999 个资产（152295421 bytes）和空 uploads；10 条历史可读取，
8 条包含可导出图版本。同一旧图的 JSON/PNG 在容器重启前后逐字节一致。
这仍是非最终演练备份的恢复验证，不能替代公网停写窗口内的最终一致性备份。

旧 Token Plan/preview 配置的实际 Uvicorn 启动以非零状态退出且未泄漏占位
token；标准 DashScope + `qwen3.7-max` + `qwen3.7-plus` 的占位配置通过静态
资格门。本地镜像没有推送 registry，因此没有 RepoDigest。当前运维工具已完成
一次独立的 `freeze -> prepare-volumes -> cutover -> rollback` 全流程演练，
备份 manifest SHA-256 为
`f6f40741c433f771cb7e85e59c9f8084f0a3d728aef8d7dfb2bde4fb19f7c6b1`。
正式任务和独立分页 canary 的 manifest 均会记录上述版本、脱敏端点、文本/
视觉模型和页转录参数；A/B 工具也不再把 endpoint 的 userinfo/query 写入
artifact。本地镜像没有推送 registry，因此没有 RepoDigest。

v50 验证结束后只执行 Docker 官方 `docker buildx prune --all --force`，
回收 1.139MB 可再生 BuildKit cache；没有执行 system/image/container/volume
prune。清理前后均为 75 个 image ID、46 个容器和 85 个卷，BuildKit cache
从 1.139MB 变为 0B，宿主仍约 1.3GB 可用。公网 v4 和 v50 隔离实例均保持
healthy。

宿主 default bridge 元数据仍指向 `docker0`，但该接口已不存在，普通
BuildKit 构建会报 `adding interface ... to bridge docker0 failed`。本次 v12
使用 `docker build --network=host` 构建；临时自定义 bridge 的创建、接入和
删除均通过。该现象与 Moby
[#42558](https://github.com/moby/moby/issues/42558) 记录的宿主网络管理服务
移除 Docker bridge 一致。正式切换仍必须使用 Compose 项目 bridge 做隔离预检，
不能据此假定 default bridge 已恢复。

默认 Compose 路径下的两个 age secret 仍是 `root:root 0600`；本次隔离验证
使用的 `.prod` 副本已经是 `root:10001 0440`。正式切换时必须让 Compose 指向
已通过 preflight 的文件，不能把 secret 改成 world-readable。当前公网映射的
`zlb-mindmap` 容器仍运行 v4 image ID
`sha256:2fedb0a26d47ce2d557f32710ba3938dda50f68e8fe21dd03c7a0a4367571d29`；
本轮未重启或替换该容器。本地 `zlb-mindmap-agent:rollback-v4-20260725`
明确指向该 image，供后续可回滚切换使用。README 描述的是仓库当前实现，不能
当作公网实例已经具备 v55 修复的证明。Ed25519 来源门、独立信任锚和 age
私钥托管已进入 v54，正式 endpoint allowlist 已进入 v55，并完成无模型隔离
验证，但尚无标准 DashScope 正式凭据、
真实 Qwen 26 页签名
evaluator artifact 或人工质量结论，仍不得进入正式停写或公网 cutover。

## 历史低代码资料

[workflow/bailian-workflow-blueprint.yaml](workflow/bailian-workflow-blueprint.yaml) 和相关说明仅作为早期低代码验证资料保留，不参与当前本地 C+ 主任务。
