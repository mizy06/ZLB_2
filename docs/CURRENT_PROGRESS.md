# 当前进度

更新时间：2026-07-30

## vNext 执行书状态

`experiment/new_bone` 已按 `MINDMAP_EXECUTION_PLAYBOOK.md` 完成本机工具、Q0
代码候选、自动攻击矩阵和全量验证。当前执行基线 HEAD 为
`4b28c75025481509dccdb28fe3459ee33ea27f4d`。

- `gh 2.96.0` 已认证为 `mizy06`；GitHub-first CLI 复查完成。
- 远端总控 issue 为 `#26`，Q0/Q1/epic/Gate 工作包为 `#1` 至 `#25`。
- CodeGraph 1.5.0 已建立并同步：215 files、5774 nodes、17652 edges。
- Q0 八项 P0 的本地实现完成；integrated red-team 为 13 tests。
- vNext 为 182/182，完整 backend 为 718 tests、1 skip。
- frontend 7/7、typecheck、build、Playwright 2/2 通过。
- vNext renderer 的 1366x768、390x844、320px reflow、200% 文本、键盘、
  DOM tree、Canvas pixel 和 overflow/overlap 检查通过。
- schema 为 36 contracts、36 schema files 加 manifest。
- legacy OpenAPI snapshot 未变化。

Gate 仍为 `HOLD / INCOMPLETE`：当前实现者不能自批 Q0；Q1 缺 60 真实文档、
双标/仲裁/calibration/sealed blind；Q3 缺教师/学生和辅助技术研究；Runtime
缺完整 vNext process-kill、contention、cost、backup/restore 与 RTO/RPO；
Q2/Q4 未获前置 Gate 授权；Q5 无 internal StageAuthorization。live private
model/search、internal allowlist、public route 和 canary 均保持关闭。

完整证据与逐 Gate verdict：
`docs/MINDMAP_EXECUTION_EVIDENCE_2026-07-30.md`。

## 总体状态

`experiment/bone` 已从串行知识图谱 Demo 升级为可运行的 C+ 课程思维导图
Agent，并完成第一轮 P0 TDD 硬化。当前仍缺完整原子 Content Unit、
复杂公式的生产准确率、真实 embedding/reranker、独立模型家族和 stage 精确
续跑。AI PDF 生产默认已改为 `direct_layout_fallback`：完整 direct 后只把
失败页交给 `layout_nodes`，两套 checkpoint 独立；未恢复页继续阻断发布，
确定性 selector fallback 进入 `degraded_pages` 和 C+ publish gate。当前仍
没有包含节点生成、父边、去重和导出的新 92 页正式生产 task/run；详细边界见
`MINDMAP_ROOT_CAUSE_ANALYSIS.md` 第 19 节。

v40 的 26 页 direct canary 为 17/26；9 个失败页的独立 layout probe 恢复
8 页，剩余 p71 在另一轮 direct 诊断中通过。该互补性已经由通用自动级联代码
承接，但必须由使用正式 Qwen endpoint 的同一次 26 页 canary 证明，不能拼接
旧结果。

当前已增加 source-bound 外置质量 oracle 和独立 evaluator。同一份正式
26 页报告必须同时满足 26 页全部 clean、请求策略匹配、53/53 canonical
公式、66/66 Required Coverage、逐页 `has_knowledge` 断言和完整 manifest
身份。历史 v43 报告回放仅为 44/53、63/66，并缺少 manifest，退出码为 2。

当前主任务入口不再使用：

```text
chunk -> 模型一次生成节点和自由关系 -> 字符串归一
```

而是使用：

```text
PDF 全页渲染与严格 PageExtraction（AI PDF）
  -> 证据账本
  -> 全局根与一级主题
  -> 一层确定性子分支与并发 Branch Team
  -> 全局合并与覆盖审计
  -> 结构受限父候选池与 Top-k 上限
  -> 独立校验 / 仲裁
  -> CP-SAT 合法主树
  -> 人工复核
  -> 图版本
```

## 已完成

- LangGraph Main Supervisor。
- 可复用、并发执行的 Branch Team 子图；当前只做一级主题到一层子分支，
  尚不是真正递归到第三层。
- 文本与视觉 Content Unit Ledger。
- 根候选、一级主题和结构节点。
- 显式节点抽取与确定性阶段降级。
- PPTX/PDF 页面渲染、原生视觉提取、VLM bbox 分析与裁剪。
- AI PDF `vision_strict` 全页多模态转录；公式 canonical+LaTeX、页码、bbox、
  PUA、完整性和置信度质量门；页级重试与 input-hash checkpoint。
- 失败或低置信 PDF 页从下游模型输入移除并标记 degraded，不静默使用旧
  parser 残缺文本；`pdfplumber` 几何候选仅保留为审计元数据。
- `standalone_node`、`attach_as_media`、`decompose`、`ignore_decoration`
  视觉动作及状态账本：装饰项保存为 rejected，区域裁剪失败保存为 deferred，
  `decompose` 裁剪记录整页父资产，native/VLM crop 做 IoU+pHash 对账。
- deferred 视觉单元与主题、分支和模型 payload 隔离；`attach_as_media` 可进入
  分支上下文，但仅由 attach 单元支持的独立节点会被拒绝。复合区域拆成多个
  子 region、整页失败落账和所有 NMS 抑制项独立落账仍未完成。
- 同义归一、分支归属、视觉媒体融合和覆盖补建。
- root/branch/structural 结构受限父候选池与 Top-k 上限；真实
  embedding/reranker 尚未实现。
- 标准档独立校验。
- 高精档第二校验与分歧仲裁路径。
- OR-Tools CP-SAT 唯一根、唯一父、深度和抽象节点约束。
- NetworkX 无环、连通、根可达与证据硬校验。
- 主树与跨链分离。
- SQLite 共享黑板。
- 内容单元、节点候选、父边候选、跨链候选和决策记录持久化。
- 可读阶段检查点、保留原件和服务重启重排；尚不是 stage input hash 精确续跑。
- 人工保留、删除、改父、改名和版本化。
- 任务删除时同步删除黑板记录和视觉资产。
- React 树形工作台、跨链开关、证据侧栏、质量门、节点表和复核队列。
- 桌面端与移动端响应式布局。
- 百炼外部引擎接口和低代码蓝图兼容。
- 文本生成/校验/仲裁使用 `QWEN_MODEL`，PDF 页转录与整页视觉理解使用
  `QWEN_VISION_MODEL`；本地默认分别为 text-only 的 `qwen3.7-max` 和
  image/video 的 `qwen3.7-plus`，生产 Compose 仍要求二者显式配置。角色使用
  同一 Provider，不具备统计独立性。
- age 密文启动时仅在后端进程内解密 Qwen Key。
- SQLite 历史记录列表、恢复和删除入口。
- JSON 与 PNG 本地导出实现；Playwright Desktop Chrome 与 Pixel 7 已覆盖
  session、本地任务、历史和真实下载。
- 前后端同源生产镜像与持久化 Compose 配置；是否可部署取决于 token、
  age secret 权限 preflight 和 TLS 反向代理。
- page/slide/heading 切块硬边界和 `context_before` overlap 元数据。
- 统一异常标签发布门、保守 fallback 和 150 节点/fanout 预算。
- child 级批量父候选校验和正式边 `direct_parent + evidence` 工程硬门；
  当前 support mapping 非空不等于直接父关系已有业务金标证明。
- shared AsyncClient、有限重试、`Retry-After`、Provider 熔断和 model attempt
  审计；调用上下文已记录 branch/input unit，token/cost、Prompt/Schema hash
  和完整结果缓存仍未实现。
- queued/running/failed/cancelled job 持久化、全局任务并发门、用户取消与停机
  中断区分、停机后重新排队；恢复仍是从保留源文件重排，不是 stage 精确续跑。
- 人工复核 expected-version CAS、单事务图版本提交、rename 标签门和派生质量重算。
- right-first 双侧实际尺寸布局；10/120/336/1000 节点夹具零碰撞。
- 生产 API 鉴权、owner 隔离、上传 magic/page/zip bomb/图片像素限制和非 root
  容器；视觉资产 URL 不再写长期 query token，仅接受同源 HttpOnly session
  或 `Authorization`/`X-Engine-Token`；像素上限由
  `MINDMAP_MAX_IMAGE_PIXELS` 配置。
- age secret 启动前以 `lstat` 验证普通文件、非 symlink、`root:10001` 和
  `0440`，验证通过后才 `exec` 启动服务。
- run manifest 记录脱敏端点、文本/视觉模型、页转录参数，以及 Python、
  pypdf、pdfplumber、pdfminer.six、Poppler、git 和镜像版本。
- 生产 Compose 显式要求 `QWEN_BASE_URL`、`QWEN_MODEL` 和
  `QWEN_VISION_MODEL`，不再把本地预览默认值当作生产基线。
- 质量 evaluator 的生产 CLI 不再接受明文私钥路径。离线密钥仪式在内存生成
  Ed25519 PKCS#8，通过 stdin 交给 age 加密，只落盘 `0600` 密文、`0644`
  公钥和不含私钥的版本化 trust record；签名时以有界 stdin 解密并在使用后
  尽力清零缓冲区。

## 验证记录

- 当前源码可发现 530 项后端测试。为避免在 3.6 GiB 宿主上再次造成资源压力，
  最近一次按五个独立进程分组运行的合并结果为 526 PASS、1 SKIP；唯一 SKIP
  是宿主没有 `age`/`age-keygen` 的真实加密往返。新增竞态测试后的
  signer/evaluator/backup 聚焦集为 42 PASS、1 SKIP，本轮 endpoint 相关
  宿主回归为 85/85。此前启动过一次单进程
  `unittest discover`，因资源压力主动中止，不能把分组结果描述成该单命令
  已通过。
- 宿主 `.venv` 实际为 Python 3.11.6，只作为逻辑回归；v55 在
  Python 3.12.13、非 root、read-only/cap-drop/no-new-privileges、
  3 GiB、2 CPU、256 PIDs 和无外网形态下按五个顺序容器运行，530/530
  GREEN。真实 age/age-keygen 往返在镜像内执行并通过，不再 SKIP。
- 覆盖 C+ 启发式夹具、ASGI API、上传校验、任务恢复、人工复核、资产鉴权、
  secret preflight、视觉状态机、CP-SAT 和布局等代码路径；这不是浏览器或
  真实 92 页源 PPTX 的生产 E2E/SLA。
- 前端 `pnpm test`：7/7 GREEN。
- Playwright 1.62.0：v47 未修复前端在 `/api/models` 返回 502 时桌面/移动
  2/2 RED；v48 源码和生产隔离镜像均为 2/2 GREEN，容器重启后再次 2/2
  GREEN。覆盖 session、模型不可用状态、`use_ai=false` 任务、历史抽屉、
  JSON/PNG 下载、画布可见性和横向溢出。
- `pnpm exec tsc -b --pretty false`、`pnpm build`、`git diff --check`、
  `compileall` 和显式生产模型占位下的 Compose config：GREEN。
  Vite 的 `699.49 kB` chunk size warning 是非阻断体积告警，不是构建失败。
- 仓库外未找到可独立运行且不写入 `runtime/` 的 export evaluator，本轮未用
  历史 5/5 替代新结果。
- 历史 Token Plan 的 `/models` 没有 `qwen3-vl-plus`；真实 p88 页面曾证明
  `qwen3.8-max-preview` 接受 `image_url` 并通过页级质量门。该结果只证明
  历史协议兼容和容量，不是生产资格证据。
- 真实页面并发探测在 1/2/4/6/8 路均为 HTTP 与质量门全通过；12 路为
  12/12 HTTP 200、11/12 质量门通过，无 429、超时或传输错误。严格默认采用
  页并发/Provider 并发 8。
- 92 页隔离分页转录总计 325.399 秒：107/107 HTTP 成功，15 次页级重试，
  80/92 页通过；失败页为
  `17, 18, 21, 29, 30, 32, 34, 35, 42, 47, 62, 87`。p86 仍缺两条目标式，
  p92 四条目标未全部形成完整公式块，因此 `complete=false`，不能晋级。
- v12 16 页 `dots layout_nodes` canary 为 58/58 canonical 公式、
  32/32 Required Coverage、87 节点、0 duplicate、262.733 秒。36 次 HTTP
  attempt 全部为 HTTP 200/stop，HTTP p50/p95/max 为
  22.957/40.002/87.996 秒。按当前三态口径为 13 `accepted`、p17/p32/p35
  `degraded`、0 `failed`，完成度 16/16；三页节点选择均在两次未通过质量门
  后使用确定性 fallback。artifact SHA-256 为
  `9a29294114202cc7e5004178bd9c587059f042bccb8f9decb7281dac71c65e8c`。
- v12 p35 独立单页 canary 为 clean `accepted`，74.336 秒、6/6 公式、
  2/2 Required Coverage、11 节点、0 duplicate；artifact SHA-256 为
  `9b40e30671f40f8c6b045161f1b6384dc91f74a4d5749407a444b9f10dbd798b`。
  该页在四路并发全页 canary 中仍降级，不能据单页结果宣称 selector 稳定。
- canary 答案和 Required Coverage 只存在于
  `backend/tools/pdf_layout_ab.py`、外置 source-gold oracle 与测试。生产
  prompt 不含这些答案；
  自动化测试扫描全部生产 prompt、禁止生产模块导入 canary oracle，并用 AST
  禁止针对 canary 页码写生产分支。当前任务强约束禁止为了转绿加入页码、
  答案、benchmark、单学科或单版式专用生产分支。
- `backend.tools.pdf_page_knowledge_evaluator` 将同一次 canary report 与
  oracle 的 SHA-256 写入总评估 artifact，严格绑定源 PDF SHA 和有序选页；
  空页规则、错源、错页、缺 manifest、缺请求策略、任一 degraded/failed、
  任一公式或 Required Coverage 缺失都会非零退出。当前工作树还支持用仓库外
  Ed25519 私钥签署最终 artifact 原始字节，signature sidecar 绑定 artifact
  SHA-256 和公钥 DER SHA-256。
- 示例课件结果：
  - 15 个节点。
  - 14 条主树边。
  - 拓扑合法。
  - 最终节点证据覆盖率 100%。
  - 重要内容加权覆盖率 100%。
- PPTX 原生图片提取：通过。
- 视觉 bbox 裁剪：通过。
- 临时保底边强制复核：通过。
- 人工复核产生新图版本：通过。
- 10/120/336/1000 节点布局夹具：无 AABB 碰撞。
- 最新已构建 v55 镜像：
  `zlb-mindmap-agent:candidate-v55-20260729`，image ID
  `sha256:cef2cd93255ce391c6f121b8bd4c339e190eabff88dae5352d351c74c2d82c0c`，
  `GIT_SHA=297da939835dc9b748a33bd80d368702d7de687d-dirty`，
  `Config.User=10001:10001`；镜像内 Python 3.12.13、pypdf 6.14.2、
  pdfplumber 0.11.10、pylatexenc 2.11、pdfminer.six 20260107、Poppler
  25.03.0、cryptography 49.0.0、age 1.2.1，`pip check` 通过。v55 固定使用
  v54 image ID
  `sha256:7b7bd6ea56f2fc9d6347b7cc8501e50889c64178732958255c52e25c9e1fc9e4`
  为 base，只覆盖 Qwen 生产 endpoint allowlist 和对应 hardening TDD；
  应用树为
  `12ca0b11fc0e5e1d89208ed4cab0a0b0ed8c8aa8e4146c33955eea7950071915`，
  overlay tree 为
  `078cc6f35b84e572e2296a9b828a2a452252be6d1980ca7cbb26d8cb31fa9f10`。
  base digest、应用树 SHA、overlay tree/scope、依赖清单 SHA 和 dirty
  revision 均写入 image labels。镜像内生产安全形态为 530/530；
  该本地镜像未推送 registry，因此没有 RepoDigest。
- v50 的分页 canary 会把脱敏 endpoint、文本/视觉模型、credential source、
  prompt/schema hash、并发/重试参数和运行时版本写入同一份 SQLite run
  manifest 与 JSON 报告；布局 A/B artifact 的 endpoint 也已脱敏。
- 本机 `.prod` age secret 通过 `root:10001 0440` metadata preflight 且能
  正常解密，但生产资格探针明确返回 `token_plan_key`。该探针未发出模型请求，
  不能替代标准 DashScope 正式凭据。
- 正式 canary CLI 强制 `MINDMAP_ENV=production`，并在解析 PDF 前复用生产
  Qwen 资格门；使用当前 `.prod` 密文的 Python 3.12 实探针先 fail closed。
  canary runner SHA 写入 manifest，总 evaluator 还记录自身与 canonical
  模块 SHA。
- v50 生产形态隔离容器 `zlb-v50-isolated-20260728` 绑定
  `127.0.0.1:18139`，使用全新卷，满足 non-root、read-only rootfs、
  cap drop、no-new-privileges、3 GiB、2 CPU 和 256 PIDs。未认证 history
  返回 401，有效 session/history 返回 200，模型列表 502 后 session 仍有效。
  一个 `use_ai=false` 任务完成并持久化了标准 DashScope endpoint、两个正式
  模型和 Python/PDF 工具版本；容器重启后任务 `10dc594affec` 的 JSON/PNG
  SHA-256 仍分别为
  `7e866c27789b797fa50f485c3da4d023b3c9ccbe6a29e178688d3a6d15fa2df6`
  和
  `a2e715c83c03f70855e353ebfa15f79fb530d6da76312367f3a4dd2bf8e44f98`。
  这不是实际 Qwen 文本或视觉调用。
- 同一 v50 image 使用全新已知测试令牌、tmpfs 数据目录和回环端口完成
  Playwright Desktop Chrome 与 Pixel 7 回归，2/2 GREEN；两个
  `use_ai=false` 任务均 completed、各 12 节点，真实 JSON/PNG 下载、画布
  可见性和横向溢出均通过。测试未读取现有实例 token，临时实例已移除。
- 从宿主直接向 v50 隔离实例的真实 Python PID 发送 `SIGKILL` 后，
  `unless-stopped` 自动重启，`RestartCount=1`、health 恢复；历史仍为 1 条，
  任务 `10dc594affec` 的 JSON/PNG 哈希保持不变。运维侧 `docker kill` 属于
  手工停止并抑制 restart policy，不能当作进程崩溃测试。
- v51 生产形态隔离容器 `zlb-v51-isolated-20260728` 绑定
  `127.0.0.1:18141`，使用独立卷和新生成的无效测试 Qwen age 密文，没有读取
  既有实例凭据。non-root、read-only rootfs、cap drop、
  no-new-privileges、3 GiB、2 CPU、256 PIDs、secret preflight 和 health
  通过；未认证/错误 token history 为 401，有效 Bearer token 为 200。
  `use_ai=false` 任务 `e70fe35cac8a` completed；重启前后 JSON/PNG
  SHA-256 分别保持为
  `d7c31092226a81335a4420e572ac3a0118085332a773b499a48739245bf06ee2`
  和
  `98be5a4dc4400b947ae39f2c59c81e750a3e07188f8f4bab9c8767848a4452fc`。
  这不是模型调用或统一质量门通过证据。
- v51 还使用当前 evaluator 生成的两页合成 artifact 完成隔离
  `freeze -> tamper reject -> prepare-volumes -> cutover -> rollback`。
  artifact 只用于部署线路测试，不具备生产资格。backup manifest SHA-256 为
  `be570793894dafc003a0ab36e2a24fcdeb366cf37273a5696d4704212d9ca7d8`，
  evaluation SHA-256 为
  `fd305c4d637e385fcb2bb56714715ed2e61d6774a671da4719af757fe337bffd`。
  仅追加换行的合法 JSON 因 SHA 不匹配在 inspect/rename 前退出 2；原 artifact
  成功切换到带 manifest/role 标签的新恢复卷，随后 rollback 恢复原容器名、
  原卷和 `unless-stopped`。基线、切换态和回滚态的 JSON/PNG 三次逐字节一致。
  备份 SQLite `quick_check=ok`，包含 1 job、1 run、1 graph version、
  0 model calls。
- v52 已完成签名版隔离
  `freeze -> artifact tamper reject -> bad signature reject -> prepare-volumes
  -> cutover -> restart -> rollback`。freeze backup manifest SHA-256 为
  `f83881cf7b3f3f6b8afb38cba4ba3414b22c98b8500fb0d9832f47c3906b64fd`，
  evaluation SHA-256 为
  `4c5f36af48b502d5dbf15d3ad347a0b63044778511a5edc8028480ae1f97df1d`，
  signature sidecar SHA-256 为
  `d6761aa0ffc7e74b17973ca0f99e172bba3e68d646e02f903416a99913dc4d88`。
  两种篡改均在活动容器 inspect/rename 前退出 2；合法 cutover、候选重启和
  rollback 前后的 JSON/PNG SHA-256 始终分别为
  `79986fea052817548d8fbd24359a8599cb8710abaadd6660bfdb7ec694d5211f`
  与
  `e23392692b6e956af4218999a238b99fe64faff82bca8376e22247b5979cdbaa`。
  rollback 恢复精确 v51、原卷、原容器名和 `unless-stopped`。
- 保留的 `zlb-v52-isolated-20260728` 位于 `127.0.0.1:18143`，使用恢复卷
  和独立测试 principal。安全运行合同、secret preflight、health 和
  401/401/200 鉴权通过；自己的 `use_ai=false` 任务 `ef25543dc824`
  completed。重启前后 JSON/PNG SHA-256 分别保持为
  `24b8e6daabd166d5d5575dcfa970da993c647c3d3646a05a8a65641b571f09fd`
  与
  `cd667fb67303658ea52cb27451f182a3de4fd2d8c9f1480ccd82bcfe792dcfe8`。
  SQLite `quick_check=ok`，卷中共有 2 jobs、2 runs、2 graph versions、
  0 model calls；不同 principal 之间的任务保持 404 隔离。
- 只执行 `docker buildx prune --all --force`，回收 1.139MB 可再生 BuildKit
  cache；未执行 system/image/container/volume prune。清理前后均为 75 个
  image ID、46 个容器和 85 个卷，BuildKit cache 现为 0B，公网 v4 和 v50
  隔离实例仍 healthy。
- v48 已通过加密占位 secret metadata preflight、read-only rootfs、
  non-root/resource constraints 和 API/engine/asset fail-closed 鉴权探针。
  隔离容器 `zlb-v48-isolated-20260728` 绑定 `127.0.0.1:18136`；模型列表
  返回 502 时，有效 session 不再被撤销，桌面/移动 E2E 在容器重启前后均
  2/2 通过。
- 恢复卷实例 `zlb-v48-history-20260728` 绑定 `127.0.0.1:18137`，已核对
  3 个 jobs、10 个 runs、8 个 graph versions、339 个 model calls、
  999 个资产和空 uploads；10 条历史可读取，旧图 JSON/PNG 在重启前后
  SHA-256 一致。
- 旧 Token Plan/preview 配置会让生产 Uvicorn 启动非零退出；标准
  DashScope + `qwen3.7-max` + `qwen3.7-plus` 占位配置通过静态资格门。占位
  配置未发出模型请求，不能替代正式凭据的文本/视觉实际调用。
- 宿主 default bridge 元数据仍引用不存在的 `docker0`，普通 BuildKit 构建
  会失败；v12 使用 `docker build --network=host` 构建。Moby
  [#42558](https://github.com/moby/moby/issues/42558) 记录了宿主网络管理服务
  移除 Docker bridge 的同类根因。临时自定义 bridge 创建、接入和删除已通过，
  但 default bridge 尚未修复。
- `backend.tools.production_backup` 已支持 `create`、`verify`、`restore`、
  `freeze`、`prepare-volumes`、`cutover` 和 `rollback`。当前代码完成了一次
  隔离 `freeze -> prepare-volumes -> cutover -> rollback` 全流程演练，备份
  manifest SHA-256 为
  `f6f40741c433f771cb7e85e59c9f8084f0a3d728aef8d7dfb2bde4fb19f7c6b1`；
  history、job 和 PNG 在候选及回滚后均与基线一致。切换会在重命名旧容器前
  探测宿主端口，Compose 固定使用 `--no-build`，失败候选清理按状态选择普通
  `docker rm` 或 `--force` 并有界等待名称释放。
- 审计发现旧切换合同只绑定 backup、恢复卷与 candidate image ID，没有消费
  统一质量 evaluator artifact，因此一个未通过公式/coverage/knowledge 门的
  镜像仍可能进入 cutover。v51 已把 `--quality-evaluation` 设为 `freeze` 和
  `cutover` 的必选参数，绑定 artifact SHA、image ID 和非空通用质量证明，并
  通过镜像内 514/514 与无模型 admission 全流程演练。
- 该演练又暴露出 provenance 缺口：任何人都能制作结构合法的合成 evaluation，
  SHA 只能检测 freeze 后篡改，不能证明 artifact 来源。v52 已进一步
  强制 `--quality-signature` 和 `--quality-public-key`，使用
  `cryptography==49.0.0` 的 Ed25519 API验证原始 artifact 字节；freeze
  manifest 记录 signature sidecar SHA、artifact SHA、公钥指纹和算法，
  cutover 在容器 inspect/端口探测/rename 前重新验签并对完整身份做等值比较。
  缺 sidecar、artifact 修改、错公钥、坏签名和旧 manifest 都 fail closed。
  聚焦 evaluator/backup 测试为 34/34 GREEN，v52 镜像内全量 518/518 GREEN，
  签名版隔离 cutover/restart/rollback 已完成。正式 Qwen 签名 evaluator
  artifact 仍未产生。
- 继续审计发现“命令行同时传入签名和任意公钥”只能证明完整性，不能证明签名者
  已获批准。`freeze`/`cutover` 现额外强制
  `--quality-public-key-sha256`，将密钥批准记录中的 Ed25519 公钥 DER
  SHA-256 作为独立信任锚；实际公钥、sidecar 公钥身份和信任锚三者必须一致，
  `trust_anchor_sha256` 进入备份 manifest 并在 cutover 逐字段对拍。该改动
  已进入 v53：聚焦 evaluator/backup 35/35、宿主及镜像内全量 519/519，
  `pip check` 均通过。错误信任锚即使带 `--stop-container` 也在停服务前
  fail closed；正确信任锚能进入既有停写窗口门。
- 当前源码继续补齐了签名私钥托管：`quality_signing_key` 生成 age 密文、
  公钥和 trust record，evaluator 强制成组接收 `--signing-key-age`、
  `--signing-key-age-identity` 与 `--signature-output`。明文
  `--signing-key` 已从生产 CLI 删除。该改动已进入 v54；真实 age 往返、
  admission 验签和 artifact 篡改拒绝探针均通过。
- `zlb-v55-isolated-20260729` 已在 `127.0.0.1:18146` 完成验证，复用既有
  无效测试 Qwen age secret，没有读取正式凭据；secret preflight、health、
  non-root、read-only、cap drop、no-new-privileges、资源限制和
  401/401/200 鉴权通过。验证后已停止但保留；v54 与 v53 隔离容器也保持
  停止并保留。
- 保留的 `zlb-v53-isolated-20260728` 位于 `127.0.0.1:18144`，满足
  non-root、read-only rootfs、cap drop、no-new-privileges、3 GiB、2 CPU、
  256 PIDs 和 secret preflight；鉴权为 401/401/200。`use_ai=false` 任务
  `27c9f6f9ad02` completed，重启前后 JSON/PNG SHA-256 分别保持为
  `413c380481e4a30abeeac12763688b7e012f1f7bd129981487ce81684e25313f`
  和
  `b5ee9e5a9a4ba80a657d9c812ab4e641bd58683f54508fd514528d8a8e092d3d`；
  SQLite `quick_check=ok`，1 job、1 run、1 graph version、0 model calls。
- 桌面端/移动端历史抽屉、真实浏览器 JSON/PNG 下载、优雅重启和进程
  `SIGKILL` 自动恢复已通过；尚未执行真实模型 PDF 浏览器流程或公网 TLS
  入口 E2E。
- 当前公网映射的 `zlb-mindmap` 仍使用 v4 image ID
  `sha256:2fedb0a26d47ce2d557f32710ba3938dda50f68e8fe21dd03c7a0a4367571d29`；
  本轮未重启或替换。本地 `zlb-mindmap-agent:rollback-v4-20260725` 已明确
  指向该镜像，不能用当前公网行为证明 v55 修复已上线。

## 外部部署项

以下工作依赖账号或部署环境，不属于仓库内代码缺口：

- 在目标环境提供标准 DashScope 按量/正式服务凭据的 age 密文与对应本机
  age 私钥；当前 `.prod` 密文已确认仍是 Token Plan 凭据，不能用于本项目
  生产后端。
- 让正式 Compose 指向宿主 `UID=0`、`GID=10001`、`0440` 且通过
  `backend.app.secret_preflight` 的 age secret。本次验证用 `.prod` 副本已经
  满足该条件；默认文件名对应的两文件仍为 `root:root 0600`，不能改成
  world-readable。
- 在目标环境显式提供标准 Qwen endpoint、正式文本模型、正式多模态视觉模型
  与对应凭据，并验证实际调用和 run manifest 记录。`preview`、Token Plan/
  Coding Plan、无效 endpoint 或 text-only 视觉模型会阻止生产启动。
- 为视觉资产配置公网 HTTPS `ASSET_PUBLIC_BASE_URL`。
- 配置 `MINDMAP_API_TOKEN`、`EXTERNAL_ENGINE_TOKEN` 和
  `ASSET_ACCESS_TOKEN`，并用 TLS 反向代理转发回环端口。
- 使用开发集、校准集和盲测集校准业务阈值。
- 用真实源 PPTX 和人工多解金标评估节点摘要与直接父边；当前测试不能给出
  节点精确率、父边准确率或“30 分钟已降至多少分钟”的生产结论。
- 从上传开始正式重跑 92 页 PDF，并逐页/逐式核对 canonical 公式、总耗时、
  节点/父边准确率、去重和 PNG；当前尚无新的 task/run。

## 凭据处理

以下内容不会提交到 Git：

- `RAM.txt`
- `ZLB-apiKey-*.csv`
- `*apiKey*.csv`
- `.env`
- `*.local.env`
- `.secrets/`
- `*.age.pub`
- `*-identity.txt`
- `.data/`
- Python 虚拟环境
- 前端依赖和构建产物

本机 age 密文、私钥、公钥和明文 ENV 均不进入 Git。Provider Key 仅在后端进程内存在，不进入前端、提示词、日志、决策记录或图版本。
