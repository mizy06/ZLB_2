# 思维导图全链路根因归因报告

- 审计日期：2026-07-25（北京时间）
- TDD 修复落地日期：2026-07-24～2026-07-25（北京时间）
- 审计对象：`/root/ZLB_2`、公网/候选容器、SQLite 历史、用户附图、2026-07-24 上传的测试课件、2026-07-25 正式完成态重跑及 source-gold 人工复核
- GitHub 基线：`origin/experiment/bone@297da939835dc9b748a33bd80d368702d7de687d`
- 设计基线：`docs/superpowers/specs/2026-07-17-mind-map-agent-framework-design.md`
- 结论性质：代码级根因审计，不是仅凭界面现象作出的模型效果评价
- 阅读口径：第 2～13 节记录 **2026-07-23 历史部署快照**；第 14 节记录 **2026-07-24 TDD 工作树**；第 15 节记录 **第一次公网重跑和第二次重跑前的候选验收快照**；第 16 节记录 **第二次失败重跑及第三轮部署前 TDD**；第 17～18 节记录 **2026-07-25 完成态与历史 checkpoint 回放**；第 19 节记录 **2026-07-26 单页多模态转录转向后的当前口径**，并覆盖旧的弱公式 oracle 结论。历史现在时表述均按“当时实现”理解。

## 1. 2026-07-25 当前执行结论

当前 TDD 工作树已经把历史故障中的多项工程根因分别收紧：页/slide/heading
边界、异常标签门、fallback 隔离、分支/节点/fanout 预算、child 级批量父候选
校验、Provider 连接复用与熔断、任务持久化与取消、复核 CAS 事务、right-first
AABB 布局、PNG 像素预算、主 API/资产鉴权和上传边界均已有自动化硬门。
2026-07-25 同一 92 页 PDF 已在 v4 公网镜像中完成一次正式 precision 重跑，
并完成 138 节点逐节点人工 Claim Precision、Evidence Alignment 与 Required
Coverage 复核。完成态证明布局工程门已经通过，也证明性能 SLA、内容准确性和
发布门仍未达标。

但是，当前实现仍不能认定为与私仓 C+ 设计完全一致。原子 Content Unit、
OCR/公式与对象级 provenance、真正递归 Branch Planner、embedding/reranker、
中层 abstraction induction、独立模型家族、主树冻结后的跨链、stage 精确续跑、
完整复合区域视觉状态机和业务金标准确率仍未完成。尤其要区分：

| 对象 | 2026-07-25 状态 |
| --- | --- |
| 当前工作树 | 第三轮部署前后端全量回归为 195/195、Provider 22/22、Qwen policy 10/10、前端 7/7；正式重跑后又加入四 child/verifier HTTP 批量、严格 evidence matcher、label/definition 止损门和对应 TDD。后置修改已有定向回归，但不能沿用 195/195 冒充新的统一全量终态 |
| 7 条历史图 | 仍是旧算法结果，不会因代码升级自动获得新语义 |
| 当前公网容器 | `http://175.178.196.235:5173/` 运行 `zlb-mindmap-agent:tdd-v4-20260725T032034Z`，image ID 为 `sha256:2fedb0a26d47ce2d557f32710ba3938dda50f68e8fe21dd03c7a0a4367571d29`；容器健康，宿主对外映射 5173 |
| 第一次公网重跑 | 92 页 precision 任务 `1f5cf23f834a` / 运行 `run_34d43d8339d249cf` 在 25 分 51.699 秒后止损取消，停在 `branches / 42%`，没有 graph version；它是性能故障证据，不是完成态 SLA |
| 第二次公网重跑 | 任务 `07f9f6d79d7b` / 运行 `run_1bae38967995454c` 在约 19 分 42 秒后因重复 `branch_topic` ID 写库失败；它证明了 18/19 Branch timeout 和 SQLite UNIQUE 是两个独立故障 |
| 第三次正式完成态重跑 | 任务 `54c6aa316702` / 运行 `run_c1e873dd28764e24` 完成于 17 分 2.8 秒；138 节点、137 条树边、30 条跨链，结构门通过，质量门和发布门未通过 |
| 正式布局验收 | 生产 CJK 字体下 22/22 通过；根分支 `right/right/right/left/left`，最小 AABB 间距 32px，PNG 为 2178×6481，无 renderer 新增截断 |
| 正式人工质量 | Required Coverage `67.5/88=76.70%`；Claim Precision `91/105=86.67%`；Evidence Alignment `95/105=90.48%`；仍有 4 个垃圾节点、15 个完全重复节点、18 个 partial claim、1 个 contradicted claim 和 7 个错挂/薄弱主题段 |
| 测试课件 | 压缩包包含 10 个 PDF、共 639 页，没有 `.pptx`；主样本为 92 页 `精细1-量子物理原子中的电子.pdf`，SHA-256 为 `a36cf7a439a5d06fe9830e5fa6219836ecc63326ed53903a323bdd4078db54f9` |

2026-07-23 历史部署最重要的问题不是“模型不够强”，而是以下三条确定性故障链
同时存在：

```text
PDF/PPT 物理断行或公式乱码
  -> 跨页粗 chunk 和错误页码
  -> 分支模型失败
  -> 启发式把短行/残句当节点
  -> 节点默认 optional=false
  -> CP-SAT 强制激活
  -> topology_valid=true / coverage=100%
  -> 错误节点正式发布
```

```text
chunk 近似 Content Unit
  -> 未认领视觉/文本进入“补充主题”
  -> 机械拆成大量 singleton Branch Plan
  -> 节点和字符相似父候选爆炸
  -> 每条 Top-k 父边分别调用模型
  -> 精细模式达到约 1700 次校验/仲裁调用
  -> 20～48 分钟任务耗时
```

```text
节点数超预算 + 一级根分支过多
  -> 前端与 PNG 各自执行一套 360° 径向布局
  -> 半径只按整层密度估计，不计算子树真实包围盒
  -> 无碰撞检测和消解
  -> 295 对框碰撞 + 11087×9709 超大 PNG
```

因此，用户提出的第 2～5 项不能统一归咎于“第 1 项架构没有完全实现”：

- 约 30 分钟耗时的直接根因包括大粒度结构化请求、调用数量、timeout
  policy、stage/leaf checkpoint 和 Provider 调度。正式完成态已经降到 17 分
  2.8 秒，但仍超过 12 分钟目标；其中 verify 202 次调用耗时 477.89 秒，
  Branch 19 次调用耗时 354.85 秒，两阶段合计占墙钟 81.42%。
- 文字异常截断来自解析、OCR/公式文本保真、模型输出、fallback、label/
  definition 资格门和视觉摘点状态机的独立 Bug。正式图的 renderer 没有新增
  截断，但持久节点中仍存在公式截断、断句、页脚/图例粘连和 4 个垃圾节点。
- PNG 重叠是独立布局算法缺陷；新 right-first/AABB 布局已在正式 138 节点图
  中用生产 CJK 字体 22/22 通过，不依赖语义架构先完整。
- 子节点准确性仍受 claim 自足性、公式/量纲校验、语义去重、父边选择和
  source-gold 覆盖影响。人工三指标已经给出单文档基线，但质量门和发布门均
  为 false，工程结构合法不能替代业务准确率。

## 2. 审计基线与证据边界

### 2.1 历史、首次公网版和候选版必须分开

| 基线 | 可核验事实 | 本报告如何使用 |
| --- | --- | --- |
| GitHub 私仓 | 2026-07-23 通过 `git ls-remote` 确认 `origin/experiment/bone` 为 `297da93`；设计文档来自提交 `34bd120` | 用于判断设计一致性 |
| 2026-07-23 工作区与部署快照 | 当时工作区位于 `experiment/bone@297da93`，部署镜像为 `sha256:63750b13...`，包含未提交的 Qwen 迁移和前端/导出修改 | 用于还原旧代码机制和旧安全面 |
| 2026-07-24 第一版公网 TDD 镜像 | image ID `sha256:19a51fb...`，已部署到公网并承载第一次 92 页重跑；它早于最新长文档性能/PDF 输入补丁 | 用于第一次公网重跑的真实运行证据，不能代表当前候选代码 |
| 2026-07-24 当前 TDD 工作树/候选 | 在同一分支上继续进行未提交的并行 TDD 修复；最新测试状态见 14.7，候选验收和第一次重跑见第 15 节 | 用于当前修复结论；候选尚未替换公网 |
| 2026-07-25 v3 公网镜像 | 承载第二次 92 页正式重跑；19 个叶中 18 个 timeout，随后因重复 `branch_topic` ID 触发 SQLite UNIQUE 失败 | 用于区分 Provider 长尾与本地 ID/事务故障，详见第 16 节 |
| 2026-07-25 v4 公网完成态 | image ID `sha256:2fedb0a...`；同一 92 页 PDF 完成任务 `54c6aa316702`，产出 graph version、JSON、PNG、model-call、资源、字体布局和人工 source-gold 证据 | 用于当前完成分钟数、布局验收、人工准确率和未实现项判定，详见第 17 节 |
| 七条历史结果 | 七次任务均在当前镜像构建前完成；持久化的 `model_selection` 显示首条为 Kimi，后六条为 DeepSeek 文本生成/校验加 Qwen 视觉 | 用于历史耗时、失败率、结果质量和稳定性量化 |
| 上传的 2026-07-24 测试集 | 10 个 PDF、639 页；主样本 92 页，原件和 SHA-256 已保留；没有 `.pptx` | 用于真实 PDF 解析白盒、Qwen-only 重跑和后续业务验收 |

2026-07-23 部署不是 GitHub `experiment/bone` 的 clean commit 构建物。历史图版本又没有记录 `git_sha`、镜像 digest、prompt/schema/layout 版本，因此旧任务只能按其持久化模型角色和阶段数据还原，不能假定由 2026-07-24 Qwen-only 工作树生成。

本报告对每条结论采用以下证据口径：

- **设计证据**：私仓设计文档及其验收门。
- **旧代码证据**：2026-07-23 23:08 部署镜像与当时工作区一致的源码。
- **新代码证据**：2026-07-24 TDD 工作树、失败测试记录和最终回归。
- **历史证据**：`/var/lib/docker/volumes/zlb-mindmap_zlb-mindmap-data/_data/blackboard.sqlite3` 中的 run、checkpoint 和 graph version。
- **视觉证据**：用户提供的异常节点截图、目标右优先布局图，以及对保存图版本按当前布局算法的碰撞计算。
- **公网重跑证据**：第一版 TDD 公网卷中的 job/run、checkpoint、`model_calls`、容器资源和取消终态。
- **真实输入对照证据**：上传原 PDF、pypdf/Poppler 逐页文本对照，以及候选容器内的 `pdftotext -layout` 实际回退结果。
- **正式完成态证据**：v4 重跑的 job/run/checkpoint、model-call、资源、graph、JSON/PNG 和字体感知布局报告。
- **人工质量证据**：`source-gold` 下逐节点 Claim Precision、Evidence Alignment、Required Coverage 和主题层级审计。

### 2.2 历史样本限制

- 历史共 7 条，全部是 PDF；2026-07-24 新上传的测试包也只有 10 个 PDF、共 639 页，没有真实 `.pptx`。PPTX 阅读顺序、SmartArt、原生图表和备注页问题只能由代码与微型测试证明，不能伪称为真实 PPTX 历史实测。
- 2026-07-23 旧任务的上传原件曾在终态后删除，因此那 7 条只能依靠 graph/checkpoint 回放；2026-07-24 新测试包和主样本原件已经单独保留，可用于后续重跑。两类证据不能混为一谈。
- graph version 保留了解析后的逐页文本和渲染页图片，因此可以检查标签、证据片段、页码和视觉覆盖，但不能恢复原始对象层、字体、动画、隐藏页或 PPTX z-order。
- 当前已经为这一个 92 页 PDF 建立逐节点人工 rubric，可给出 Required
  Coverage、Claim Precision 和 Evidence Alignment 的单文档基线；但仍没有
  多文档、多标注者、多解结构和直接父边金标。因此不能把单文档三指标外推为
  全业务准确率，也不能给出父边 P/R/F1 或祖先 F1。

### 2.3 历史任务总览

`source blocks` 对 PDF 近似为有文本的页数，不包含纯空白页。

| 任务 | 文件 | 档位 | 分钟 | Source blocks | Chunks | Units | 最终节点 | 待复核 | 临时边 | Gate |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `3828b9e160bb` | 标准1-量子物理薛定谔方程.pdf | standard | 20.61 | 59 | 7 | 48 | 166 | 75 | 2 | 失败 |
| `4ba57632b48c` | 精细5-烯烃和消除反应.pdf | standard | 37.60 | 48 | 2 | 73 | 291 | 159 | 0 | **通过** |
| `59103adf7c51` | 标准2-RNA Processing I.pdf | standard | 25.49 | 90 | 19 | 46 | 203 | 58 | 0 | **通过** |
| `749e4e76fb55` | 精细1-量子物理原子中的电子.pdf | precision | 47.91 | 92 | 10 | 61 | 311 | 172 | 6 | 失败 |
| `4949dd7d51a4` | 标准3-The genetics of cancer.pdf | standard | 24.97 | 64 | 12 | 38 | 249 | 80 | 2 | 失败 |
| `8db068a6c04a` | 精细1-量子物理原子中的电子.pdf | precision | 24.75 | 92 | 10 | 64 | 336 | 197 | 29 | 失败 |
| `5454a893077c` | 标准4-二重积分的计算.pdf | standard | 2.41 | 41 | 10 | 45 | 159 | 3 | 2 | 失败 |

设计适用范围是 20～150 页或幻灯片、最终 30～150 个语义节点。七个结果全部超过 150 个节点；两个被现有 Gate 判定为通过的结果仍分别有 159 和 58 个待复核项。

## 3. 2026-07-23 旧实现与 C+ 设计一致性

| 设计能力 | 2026-07-23 旧实现 | 判断 | 直接影响 |
| --- | --- | --- | --- |
| LangGraph Main Supervisor | 有固定的 10 阶段 StateGraph | 基本一致 | 有编排骨架，但不支持 checkpoint resume 和局部重跑 |
| 结构感知确定性解析 | PDF 每页只调用 `pypdf.extract_text()`；PPTX 整页拼成一个 block | 不一致 | 阅读顺序、bbox、标题层级、OCR、公式和 provenance 丢失 |
| 教学信息级 Content Unit | 一个 chunk 直接变成一个文本 Content Unit | 不一致 | 一个 unit 横跨多页和多个主题，证据页、主题规划和图文关联全部变粗 |
| Global Theme / Root Planner | 有模型和 fallback，但只读取每 unit 头部摘要，且不验证覆盖互斥 | 部分一致 | 后半文档和大量视觉不进入稳定骨架 |
| 递归 Branch Team | 有子图和并发，但递归依据 unit 数和首行标签机械拆分 | 形式一致、算法不一致 | 375 units 产生 338 plans、321 个 leaf |
| Node Scout / Granularity Critic | 有名称相同的阶段 | 语义未实现 | 粒度门只查长度、泛词和“是否有任一证据” |
| Abstraction Induction | 仅补一个预先规划的 branch label | 不一致 | 没有节点簇归纳，图天然扁平 |
| Merge & Reassignment | 同分支 SequenceMatcher 和全局精确名合并 | 不一致 | 无跨分支语义重分配，反而可能错误吞并同名异义节点 |
| Embedding + Reranker Top-k | 字符 bigram、角色常数和 branch 常数 | 未实现 | 父候选稠密、方向性弱、无边证据 |
| 独立校验器 / 仲裁器 | 当前所有角色均为同一 Qwen 模型；历史 DeepSeek 也同时承担生成和校验 | 不一致 | 第二票不是独立证据，错误相关性高 |
| CP-SAT 激活/拒绝节点并全局优化 | 能保证唯一根、唯一父、深度；大多数 explicit 节点被强制激活 | 部分一致 | 合法树不等于正确树，求解器不能淘汰大多数坏节点 |
| Coverage + Abstraction 双向审计 | branch topic 的 support IDs 可自证 100% 覆盖；无真正 abstraction audit | 不一致 | 质量指标出现假健康 |
| 主树冻结后生成跨链 | 跨链在 Branch 抽取阶段生成 | 不一致 | 跨链未基于最终树去冗余和校验 |
| 多模态第一等知识源 | 有渲染、Qwen bbox 和裁剪，但仅顺序分析前 24 页 | 部分一致 | 长课件后部视觉静默缺失，前部视觉被放大 |
| 少量高风险 HITL | 有复核队列，但动作不全、无事务，并存在选错 subject Bug | 不一致 | 43.4% 节点规模的复核量，人工操作仍可破坏语义 |
| 可追溯观测 | 有 `model_calls` 表、checkpoint 和图版本 | 形式存在、闭环缺失 | `model_calls` 全库 0 行，checkpoint 只写不读，无法复现调用成本和失败 |
| 设计验收指标 | 当前 Gate 只看拓扑、任一 support、coverage 和 provisional | 不一致 | 不检查节点精确率、父边准确率、复核率、降级率、稳定性和视觉召回 |

历史结论：旧实现不是最初的串行 Demo，但也不是设计文档所定义的完整 C+。它更准确的描述是“C+ 阶段名和数据结构已接通，核心语义算法、失败语义和发布门仍是原型级占位实现”。2026-07-24 修复后的当前差距见 14.6 节。

### 3.1 最容易误导排障的概念混用

`docs/CPLUS_IMPLEMENTATION.md`、README 和界面把多个“已有字段/阶段”描述成“能力已实现”，但代码行为并不等价。这些命名混乱会让问题被误判成单纯的 prompt 或模型波动：

| 2026-07-23 名称或宣称 | 当时实际行为 |
| --- | --- |
| `ContentUnit` | 文本路径基本是整个 1800 字跨页 chunk，不是教学信息原子 |
| “结构感知解析” | PDF 一页一个 raw text block；PPTX 一 slide 一个拼接 block |
| “递归 Branch Planner” | 按 unit 数、heading/首行字符串递归切组 |
| `coverage_budget` | 只存字段，从未参与拆分、节点数或模型调用约束 |
| `Abstraction Induction` | 缺少同名 branch label 时补一个预设 label |
| `canonicalize_semantic_duplicates` | 同分支 `SequenceMatcher`；随后全局 exact normalized name 合并 |
| `reranker_score` | Schema 有字段，主流程没有真实 embedding/reranker |
| “独立校验/第二校验/仲裁” | 不同逻辑调用角色，但当前全部是同一 Qwen Provider/模型 |
| `perceptual_hash` | 保存的是文件 SHA1，不是感知哈希 |
| `decompose` | 多个扁平 crop/unit，没有 parent asset 和组合关系 |
| “checkpoint 恢复” | 阶段 payload 只写不读，服务重启不能续跑 running task |
| `evidence_coverage=1` | 节点有任一 evidence/support/media 字段，不校验证据真实支持 |
| `weighted_content_coverage=1` | unit ID 被结构 topic support 集声明，不等价于显式知识覆盖 |
| `direct_parent_confidence` | 所选边分数平均值，不是人工金标准确率 |
| “质量门通过” | 当前只代表有限工程门，不代表少量复核或语义正确 |
| “超过 120 节点概览” | 过滤 `depth > 2`，实际可继续显示 258 个节点 |
| “历史恢复” | 只能恢复已有最终 graph version，不能恢复 queued/running/failed |

文档和 UI 必须改用精确名称，避免把“数据结构存在”“逻辑角色分开”和“能力已按设计实现”混为一谈。

## 4. 2026-07-23 历史跨阶段量化证据

### 4.1 分支和节点爆炸

- 7 次历史共有 375 个 Content Unit，却生成 338 个 Branch Plan、321 个叶分支，其中 305 个叶分支只有一个 unit。
- 平均每个叶分支只有 1.17 个 unit；这不是“语义内聚后的递归团队”，而是接近一 unit 一团队。
- 最终共有 1715 个节点，每图 159～336 个，全部越过设计目标上限 150。
- `8db068a6c04a` 从 64 units 生成 63 plans、60 leaf、56 singleton，normalize 后 338 节点，最终 336 节点；根直属分支达到 35 个。

### 4.2 父边和质量失真

- 七次 verify checkpoint 共包含 13,503 条父候选；全部没有边级 evidence。
- 最终 1708 条树边也全部没有边级 evidence。
- 其中 161 条最终边的 classification 不是 `direct_parent`，占 9.43%；另有 41 条 provisional。
- 共生成 744 个待复核项，相当于最终节点数的 43.4%。
- 七次最终 `weighted_content_coverage` 和 `evidence_coverage` 都是 1，但这是结构节点 support IDs 覆盖了 unit ID，不代表知识点正确抽取。
- `4ba57632b48c` 在 159 个待复核、24 条非 direct 边、抽象支持率 6.94% 的情况下 Gate 通过。
- `59103adf7c51` 在 58 个待复核、20 条非 direct 边、抽象支持率 17.86% 的情况下 Gate 通过。

### 4.3 标签和重复运行稳定性

- 七图至少包含 16 个字面量 `[上文衔接]` 节点、31 个括号不完整标签、145 个长度恰好为 32 的疑似硬截断标签。
- 典型异常包括：`的光谱结构（即使`、`但是`、`原子沉积层不`、`与管壁碰`、`微观粒子的运动状态是用波函数描`。
- 同一 `document_id=doc_149dd6c519d4` 的两次运行分别得到 311 和 336 个节点。
- 按原始节点名集合比较，交集/并集为 163/484，Jaccard 为 33.7%；按去空白、标点等规范化后约为 34%～36%。按“父名 -> 子名”比较最终树边，交集/并集仅 5/640，Jaccard 为 0.78%。

### 4.4 30 分钟任务的真实瓶颈

排除首条 Kimi 历史和余额耗尽、快速失败的 `5454a893077c` 后，5 个有效 DeepSeek+Qwen 任务：

- 平均总耗时 32.1 分钟，中位数 25.5 分钟。
- 按相邻 checkpoint 时间差估算，父边 verify 平均占 65.3%，Branch 抽取占 23.6%，视觉 ledger 占 7.6%，主题生成占 3.3%；解析、normalize、求解和 finalize 不是主要瓶颈。
- 七次 verify 阶段分别耗时约 596、1346、942、2247、997、765、28 秒。
- 七次 Branch 阶段分别耗时约 361、673、390、417、285、510、6 秒。
- `8db068a6c04a` 的 precision 路径理论上执行 1655 次 verifier 调用和 54 次仲裁，共 1709 次；只有 334 张 verifier 票和 32 张 arbiter 票来自有效模型输出，其余静默变成确定性票。
- 同源 `749e4e76fb55` 的模型成功率更高，verify 反而耗时 37.4 分钟；`8db...` 的 24.75 分钟部分来自请求更快失败，不能被解释为性能优化。
- `591...`、`749...`、`4949...`、`8db...` 的运行时间发生重叠。系统没有全局任务/Provider 限流，多任务会叠加各自 4 路分支和 8 路校验并发，历史耗时还包含配额争抢。

当前公网已切换为 Qwen-only 第一版 TDD 镜像，但第一次 92 页 precision
重跑在 25 分 51.699 秒时仍停在 Branch 阶段并被止损取消，不能充当完成态
SLA。它新增证明了“大请求 + 固定 token 预算 + `3×180s` 重试”这一条与
历史逐边调用不同但同样独立的性能根因，详见第 15 节。第二次重跑必须使用
最新候选并跑到 graph version，才能与这里的旧 DeepSeek/Kimi 分钟数比较。

### 4.5 PNG 和画布

- `8db068a6c04a` 的当前 PNG 算法输出为 `11087×9709`，约 1.076 亿像素。
- 按实际节点尺寸做 AABB 交叠检查，有 295 对节点框碰撞，涉及 226 个节点。
- 前端所谓“超过 120 节点时折叠”只是过滤 `depth > 2`；该图仍显示 258 个节点，并有 92 对碰撞。
- 用户目标附图表现为中心节点两侧展开、右侧优先、空间不足后转左；当前实现是完整 360° 径向分配，算法目标本身就不同。

## 5. 2026-07-23 旧实现逐阶段根因

### 5.1 上传、原件和可复现性

代码位置：`backend/app/main.py:199`、`backend/app/main.py:216`、`backend/app/main.py:231`、`backend/app/main.py:126`、`backend/app/document_parser.py:17`。

1. 上传只校验文件扩展名，未校验 MIME/magic、大小、页数、压缩比或恶意内容。
2. `shutil.copyfileobj` 在 async handler 内同步执行，大文件会阻塞事件循环。
3. 任意任务立即 `asyncio.create_task`，不保存 Task handle，不经过持久队列或全局并发门。
4. 成功或失败都立即删除上传原件，失败 29 分钟后也不能从 checkpoint 重放。
5. document ID 使用 SHA1 前 12 位，但相同 source hash 没有解析、视觉、模型或布局缓存。
6. run 没有固化 code/prompt/schema/parser/layout 版本，导致本次“历史旧 Provider、当前新镜像、GitHub clean branch”三套基线漂移。

结果：历史可以看到派生文本和图片，却无法重放原始解析，也无法证明两次相同文档使用了完全相同的代码和提示词。

### 5.2 PDF/PPTX 解析不是结构感知解析

代码位置：`backend/app/document_parser.py:22`、`backend/app/document_parser.py:32`、`backend/app/document_parser.py:113`。

PDF 路径每页只执行一次 `pypdf.Page.extract_text()`，整页作为一个 `SourceBlock`。它没有：

- bbox、阅读顺序、多栏恢复、标题类型和章节路径；
- 页眉页脚/页码模板去重；
- CJK 硬换行合并、英文断词去连字符；
- OCR 和字符置信度；
- 公式、上下标、PUA 字符和表格结构恢复。

历史物理课件已经出现 ` h=`、倒序上下标和 PUA 字符；代码仍把它们当普通文本。扫描 PDF 或纯视觉 PPTX 在“没有文本 block”时会直接报“需要先接入 OCR”，视觉渲染尚未开始。

PPTX 路径按 `slide.shapes` 的 OOXML/z-order 拼接，而不是 placeholder、top-left 和组内阅读顺序；整页仍只有一个 block。正文和表格失去 bbox，未递归恢复 group/SmartArt、notes、公式、隐藏状态和 chart 数据。当前历史没有 `.pptx`，这一项必须用真实 PPTX 金标补测。

### 5.3 Chunk 主动污染正文并破坏 provenance

代码位置：`backend/app/chunking.py:9`、`backend/app/chunking.py:42`、`backend/app/chunking.py:55`、`backend/app/chunking.py:69`。

1. 只按终止标点切句；没有标点的长公式/文本按裸字符位置截断，可切开术语、括号和公式。
2. 1800 字 chunk 不以 page/slide/heading 为硬边界，可跨十几页。
3. 上一 chunk 尾部 240 字被复制成新的 `SourceBlock`，并把 `[上文衔接]` 写入模型可抽取正文。
4. overlap block 没有原始 page/slide，却与下一块内容混合。
5. Chunk 虽计算 `page_start/page_end`，后续 Content Unit 和 Evidence 只保留 start。
6. heading 取 chunk 内最后一个带 heading 的 block，可能误标此前内容。

历史 `8db...` 的 92 页被压成 10 个文本 unit，平均每 unit 跨 9.2 页、最大 12 页；`4ba...` 的 48 页只有 2 个文本 unit，平均 24 页、最大 34 页。PDF 文本 Content Unit 的 `heading_path` 全为空，`8db...` 的 10 个 chunk 中 9 个含字面量 `[上文衔接]`。

### 5.4 异常截图的精确触发链

用户截图中的 `的光谱结构（即使` 不是随机模型幻觉，而是可逐行还原的代码 Bug：

1. 源第 11 页原句为“但是，不能说明氢原子光谱线的强度和复杂原子\n的光谱结构（即使是类H离子和He）”。
2. `backend/app/heuristics.py:9` 的定义正则允许任意单字“是”作为定义分隔符。
3. 正则把“即使是”中的“是”误当谓词，name 变为 `的光谱结构（即使`，definition 变为 `类H离子和He）`。
4. `backend/app/heuristics.py:31` 只清理有限尾部字符，不拒绝开头“的”、未闭合括号或断尾。
5. `backend/app/heuristics.py:70` 又把任意 2～32 字、无 `。！？` 的 PDF 硬换行直接建成节点。
6. 对应 Branch 模型返回无效 JSON后，`backend/app/agents.py:751` 采用完整启发式 fallback。
7. `backend/app/agents.py:773` 的粒度门不查句法、括号和首尾虚词，因此放行。
8. `BranchNodeOutput.optional` 默认 false；`backend/app/mindmap_engine/topology.py:287` 强制激活。

同一 excerpt 因 chunk 跨页和 overlap，可分别被报告为第 1 页或第 13 页，真实来源却是第 11 页。对 `8db...` 中能在解析页原文定位的 111 条文本证据抽样核验，101 条 reported page 不包含该 excerpt，错页约 91%。这是 `page_start` 冒充证据页的系统性错误，不是模型偶发错误。

### 5.5 Content Unit 只是换名后的 chunk

代码位置：`backend/app/agents.py:147`、`backend/app/agents.py:162`、`backend/app/agents.py:172`。

- `build_content_units` 一 chunk 直接一 unit，不拆 definition、claim、formula、step、example 或 warning。
- `unit_role` 只扫描前 240 字，importance 只看前 500 字、heading 和总长度。
- `evidence_excerpt` 固定为 chunk 前 240 字，page 固定为 `page_start`，page_end 丢失。
- 一个 unit 内的几十个节点共享同一个 coarse unit ID 和错误位置。

这与设计“教学信息单元 + 精确证据坐标”不一致，也是后续主题摘要、视觉附近文本、覆盖统计和父边证据无法可信的共同上游原因。

### 5.6 视觉链路全量渲染、只看前 24 页

代码位置：`backend/app/config.py:193`、`backend/app/mindmap_engine/visuals.py:72`、`backend/app/visual_analysis.py:71`、`backend/app/visual_analysis.py:104`、`backend/app/visual_analysis.py:117`、`backend/app/visual_analysis.py:164`。

1. PDF 先以 144 DPI 全量渲染并保存所有页面；Qwen 视觉分析随后直接取 `rendered.pages[:24]`。
2. 不是按目录、图密度、文本贫乏页或章节分层采样；第 25 页以后没有 visual unit、deferred 记录或 warning。
3. Qwen prompt 只有页面图片和页号，没有该页文本、章节路径和相邻页上下文。
4. 图文 nearby 要求视觉页号等于 text unit 的单个 `page_start`；跨页 unit 的中间页面永远匹配不到。
5. `8db...` 的 54 个视觉 unit 全来自前 24 页，只有 3 个带 nearby text；`4ba...` 的 71 个视觉 unit 中 0 个关联文本。
6. 任一页成功即把视觉组件视为成功；即使大量页失败或成功页返回 0 regions，也不形成整体 degraded。

视觉动作也没有形成闭环：

- `ignore_decoration` 直接丢弃，不保存 rejected 决策；失败页也不产生 `unparsed_visual`。
- bbox 只检查四个值处于 0～1 和宽高大于 0，不验证 `x+w <= 1`、`y+h <= 1`、最小面积、IoU/NMS 或区域数量。
- `decompose` 没有真正保存父资产关系；`parent_asset_id` 未写入。
- `perceptual_hash` 实际写入文件 SHA1，只能去除字节完全相同图片，不能识别缩放/裁剪 Logo。
- native PPTX asset 与 Qwen crop 分两批加入，没有跨来源 reconcile。
- Branch prompt 不带 visual_action、bbox、knowledge_claims 和 nearby IDs；attach 图仍可能被当独立节点抽取。

### 5.7 主题只看每个粗 unit 的开头

代码位置：`backend/app/agents.py:249`、`backend/app/agents.py:317`、`backend/app/agents.py:330`。

- 主题输入最多 80 个 unit，每个 text unit 优先使用固定前 240 字的 `evidence_excerpt`，不是章节级 map-reduce 摘要。
- `8db...` 主题模型实际只看到约 2400/17576 字，即 13.7%；其他长任务也只有约 14%～18%。
- 模型返回只过滤不存在的 support ID，不验证支持非空、一级主题互斥、章节一致或整体覆盖。
- fallback 取 unit 第一行并截 32 字；overlap unit 第一行正是 `[上文衔接]`。
- 模型未认领的所有 unit 无条件进入“补充主题”。

同源 92 页文档的一次运行主题模型降级为“文件名 + `[上文衔接]`”，另一次得到 5 个正常主题，说明当前表示、错误降级和无缓存共同造成高漂移。

### 5.8 Branch Plan 机械拆分制造 singleton

代码位置：`backend/app/agents.py:394`、`backend/app/agents.py:426`、`backend/app/agents.py:446`、`backend/app/agents.py:489`。

- 拆分依据只有 unit 数量、heading 或 `_short_label` 首行，不计算 embedding cohesion、教学必要性或兄弟粒度。
- 没有 heading 的视觉摘要通常各不相同，于是几乎每张图形成 singleton child plan。
- `coverage_budget` 只被赋值，从未被任何代码读取或约束节点数。
- parent plan 和 leaf plan 都创建 branch_topic；一级 plan 为非 optional，并携带整组 unit IDs。
- 一个 unit 的 structural branch 不满足设计“至少概括多个子节点/单元”的资格，但 base theme node 已先创建。

结果是分支调用数、结构节点数和根侧 fanout 同时爆炸，并为后续 O(N²) 父候选奠定规模。

### 5.9 分支降级会直接发布残句

代码位置：`backend/app/agents.py:564`、`backend/app/agents.py:661`、`backend/app/agents.py:719`、`backend/app/agents.py:751`、`backend/app/agents.py:773`。

1. Branch 模型整个输出由一个 Pydantic Schema 一次性校验；任一 cross-link/evidence 字段错误、未知 relation 或越界 activation cost 都能拖垮整批合法 nodes。
2. 模型失败后不是 defer/retry/repair，而是完整采用启发式结果。
3. 历史 7/7 任务都出现 `branch_extraction_model` 降级。
4. 启发式候选默认 non-optional，且没有 `needs_review` 发布隔离。
5. 粒度门只验证 2～48 字、非少数 exact 泛词、存在任一 evidence/support；不验证原子性、教学价值、事实蕴含、括号、断句、OCR 噪声和公式完整性。
6. 模型 evidence 只验证 unit ID 存在，不验证 excerpt 是该 source span 的子串。

因此，fallback 在当前系统中不是“保守降级”，而是“降低语义质量后继续正式发布”。

### 5.10 合并、视觉融合和 Coverage 名称与行为不符

代码位置：`backend/app/agents.py:977`、`backend/app/agents.py:1034`、`backend/app/agents.py:1174`、`backend/app/mindmap_engine/normalize.py:66`、`backend/app/agents.py:1517`。

`canonicalize_semantic_duplicates` 实际只在同一 branch 内使用 `SequenceMatcher >= 0.94`，并跳过 branch topic；它既不是 embedding 语义去重，也不执行跨分支 reassignment。

随后 normalize 又按去标点后的 exact name 在全图合并，忽略 branch、role、type 和 definition。合并后只保留 primary 的单个 branch/type/role，confidence 取平均、definition 取最长、optional 使用 `all()`；同名异义和同名不同粒度会丢语义。历史出现 `[上文衔接]` 横跨多个分支合并，以及 person/concept、formula/result/concept 的角色混合。

视觉融合只在 nearby unit ID 有交集时，按交集数和候选 confidence 选一个节点，没有判断图文是否表达同一知识。

Coverage 的关键误区是“结构节点自证覆盖”：

1. 未认领 unit 全部被放入某个 leaf plan。
2. `theme_nodes` 为 branch topic 写入该 plan 的全部 `support_unit_ids`。
3. Coverage 将任何节点 support ID 视为该 unit 已被知识节点覆盖。
4. 七次历史的强制 `coverage_*` 补点实际都是 0；残句不是补点产生，而是 fallback 产生。
5. 但 `audit_coverage` 仍有潜在危险旁路：未来若真发现未覆盖 unit，会取首行截 32 字，创建 `optional=false` 节点，并在不经过粒度门的情况下立即标 covered。

所以当前 `coverage=1` 只说明“每个 unit ID 被某个结构节点声明过”，不能说明重要知识被准确抽取。

### 5.11 没有真正的中层抽象和层级归纳

代码位置：`backend/app/agents.py:839`、`backend/app/agents.py:865`、`backend/app/agents.py:1084`。

- `_abstraction_induction` 不聚类、不归纳，只在缺少同名节点时补一个 branch label。
- Branch 输出 Schema 只有 nodes 和 cross_links，不输出局部树或 parent hints。
- `_local_parent_retriever` 把当前 branch topic 连接到该分支全部节点，天然形成星形。
- 全局父边先硬编码 root -> top branch、parent branch -> child branch、branch -> explicit node。
- 其余召回在所有节点间两两计算角色常数、同 branch 奖励、字符串包含和字符 bigram；没有 embedding、reranker、章节方向性、粒度方向或边证据。
- 父边组合分只平均非零字段；缺失 reranker/evidence 等特征不会被惩罚。

这解释了为什么公式、人物、图片摘要和残句会被提升到过高层级，也解释了树边在两次相同文档运行中几乎不稳定。

### 5.12 父边校验既慢又不独立

代码位置：`backend/app/agents.py:1293`、`backend/app/agents.py:1384`、`backend/app/cplus_pipeline.py:734`、`backend/app/model_provider.py:67`、`backend/app/model_provider.py:189`、`backend/app/cplus_pipeline.py:140`。

算法问题：

- 每个 child 的 Top-3 候选逐边调用一次模型，不是一次让模型比较该 child 的所有父候选。
- precision 对 Top-2 再逐边调用；`len(competitors)>1` 对绝大多数节点恒成立，因此高风险门几乎失去筛选作用。
- 第二校验与仲裁和第一校验使用同一 Provider/同一模型。当前是全角色 Qwen，历史是生成与校验均为 DeepSeek，均不满足独立模型家族设计。
- competitor 只带候选 ID/分数等边数据，不带每个竞争父节点的完整语义和对应 source spans。
- 模型输出中的 parent/child 字段不与请求 pair 校验。
- 两票一致时直接取第二票；不一致时取仲裁最后一票，没有可靠加权或校准。
- 逐边异常被静默改成 deterministic vote，不产生 warning 或实际 fallback ratio；pipeline 只检查任务开始时的 `runtime.available`。

运行问题：

- 每次 `/models` 和 chat 调用都新建 `httpx.AsyncClient`，千级请求无法复用 TCP/TLS 连接。
- 固定 180 秒 timeout，没有 429/5xx 重试、Retry-After、指数退避、错误分类或熔断。
- 余额不足等永久错误仍会逐边继续请求。`5454...` 的预期 426 次首校验全部失败后仍“完成”。
- `model_calls` 表存在，但七次历史为 0 行；token、费用、延迟、失败类、重试和真实调用数不可观测。

### 5.13 CP-SAT 只保证合法拓扑

代码位置：`backend/app/mindmap_engine/topology.py:235`、`backend/app/mindmap_engine/topology.py:287`、`backend/app/mindmap_engine/topology.py:299`、`backend/app/mindmap_engine/topology.py:354`。

当前硬约束只保证：一个激活根、每个激活非根一个入边、沿边深度递增，以及 optional 抽象节点至少两个出边。

缺失的设计约束包括：

- 正式树边必须为 verified `direct_parent`；
- 边必须有可定位、支持父子关系的 evidence；
- 节点总预算、一级 fanout 和分支容量；
- branch consistency、角色兼容、粒度方向和兄弟一致性；
- 抽象节点必须由实际选中子节点支持；
- content coverage、冗余、层级跳跃、深度和额外节点成本。

所有 non-optional 非根节点都有 `active == 1`。启发式 explicit 节点和 coverage 补点默认 non-optional，因此求解器只能给坏节点找父边，不能拒绝坏节点。

目标函数只有边分、根置信和 optional 节点激活收益。classification 只是此前被折入较低分，不是硬过滤；低分但 non-provisional 的 sibling/unrelated/uncertain 边仍可能优于受罚的 provisional 边。Greedy fallback 同样优先 non-provisional，而不要求 direct parent。

CP-SAT 使用 8 workers，未固定可复现求解配置；在大量等分/近等分候选下，重复运行漂移还可能被放大。

### 5.14 质量门把“形式合法”误报为“知识正确”

代码位置：`backend/app/mindmap_engine/validate.py:15`、`backend/app/cplus_pipeline.py:388`、`backend/app/cplus_pipeline.py:417`。

- `evidence_coverage` 只检查节点是否有任一 evidence/support/media，不校验 ID 有效、excerpt 与位置匹配、证据蕴含节点。
- abstraction support 把 support IDs 数和 evidence 条数直接相加，可能重复计算同一 unit，也不检查语义内聚。
- `direct_parent_confidence` 实际是所选边 score 的平均，不是直接父边准确率。
- quality gate 只检查 topology、节点形式证据、无 provisional 和 weighted coverage。
- 不检查 node count、非法标签、非 direct 正式边、边证据、pending reviews、抽象有效率、降级比例、实际模型成功率、重复运行稳定性和视觉页覆盖。

前端又在任何 Gate 失败场景固定显示“主树合法，仍有质量项需要复核”，没有先判断 `topology_valid`，见 `frontend/src/App.tsx:552`。这会把“结构校验失败”和“语义待复核”混为一类。

### 5.15 跨链时序与复核闭环错误

代码位置：`backend/app/cplus_pipeline.py:601`、`backend/app/mindmap_engine/topology.py:39`、`backend/app/review_service.py:19`、`backend/app/review_service.py:124`、`backend/app/review_service.py:164`。

- 跨链在 Branch 抽取时生成，早于主树冻结，与设计顺序相反。
- 最终选择只看 score >= 0.7、存在任一 evidence、每 source 最多两条；不验证方向、事实、祖先冗余、树边重复或跨分支教学价值。
- 无证据 cross-link 会创建 review 后从结果 cross_links 中移除；UI 又只有“保留”，keep 无法把候选重新加入，缺少 accept/reject 闭环。
- provisional edge review 的 `subject_ids` 顺序是 `[parent, child]`；`_selected_subject_node` 却取第一个同时出现在整棵树 targets 中的 ID。如果 parent 本身不是根，它也通常在 targets 中，人工改父/删除会误操作 parent 而不是问题 child。
- delete 会把所有孩子直接接到祖父并赋 score=1/direct_parent，不重新做语义校验，也不清理 dangling cross-links 和其他引用 review。
- change_parent 可选任意现存节点并直接赋 score=1，不校验候选 evidence、角色或最大深度。
- 多步 DB 更新没有单事务、expected graph version 或 compare-and-swap；并发复核可丢失更新并把 resolved 覆盖回 pending。
- 人工修改后沿用旧 weighted coverage、abstraction support、direct-parent confidence 和 coverage summary。
- 设计要求的 merge、split、recrop 和真正切根未实现；前端 rename/accept_root 也不可达。

### 5.16 布局和导出是独立根因

代码位置：`frontend/src/components/GraphCanvas.tsx:39`、`frontend/src/components/GraphCanvas.tsx:65`、`frontend/src/components/GraphCanvas.tsx:185`、`backend/app/export_service.py:28`、`backend/app/export_service.py:103`、`backend/app/main.py:313`。

前端和 PNG 分别实现了一套不同的径向布局：

- 半径只按整层节点数、最大宽高和圆周估计；不计算每个子树的实际 bbox 和局部角密度。
- 根扇区按 leaf count 比例分配，密集子树会被压入狭小角区。
- 没有 AABB/OBB 碰撞检测、最小间距约束或迭代消解。
- children 按显示名称排序，不按源章节/页序，结构顺序会漂移。
- 前端先把文本截成 2～4 行，后端 PIL 再用另一套尺寸和截断规则；预览和导出不会一致。
- PNG 总是同步生成全图，没有节点概览预算、像素上限、缓存或 worker 隔离。
- async export handler 内直接执行 CPU/内存密集的 Pillow 渲染，会阻塞服务。

所以“框重叠”不能归因于 C+ 未完整实现。只要给当前算法一个局部密集树，即使节点语义完全正确，也会发生碰撞。

### 5.17 队列、恢复、历史和前端状态

代码位置：`backend/app/main.py:53`、`backend/app/main.py:71`、`backend/app/blackboard.py:390`、`backend/app/blackboard.py:404`、`backend/app/blackboard.py:440`、`frontend/src/App.tsx:137`。

- jobs 只存在于进程内 dict，无 TTL、上限、持久状态、Task handle 和 cancel。
- 删除运行任务不会先取消/等待后台 Task；后台仍可能写已删除 run、job 和资产，形成竞态。
- checkpoint 只有写入方法，全仓没有 `load_checkpoint`，LangGraph compile 也没有 checkpointer；它是审计快照，不是恢复点。
- 服务重启后只能从 graph version 恢复完成任务；running/failed 没有最终 version 时返回 404，history 也因 inner join graph_versions 不显示它们。
- parent/node/cross-link 保存采用 upsert 但不删除本阶段已淘汰项，表内可能保留跨阶段 stale candidates；checkpoint 才是当时完整集合。
- graph version 每次保存完整多 MB payload；复核次数多时会重复保存全文、assets、nodes 和 reviews。
- history 为显示小摘要仍逐条解析完整 graph JSON；内存 jobs 又长期缓存完整 result。
- 当前卷约 177 MB；SQLite 中 checkpoints 约 16.9 MB、graph_versions 约 11.4 MB、review_items 约 7.6 MB，且没有 retention、配额、GC 或 VACUUM 策略。
- 前端每 700ms `setInterval` 轮询，无 AbortController、单飞和响应序号；慢请求可重叠并由旧响应覆盖新状态。
- 30 分钟任务单客户端产生约 1200～1760 次 GET；刷新不恢复 active task，运行中换文件还会 `setJob(null)`，造成后台孤儿任务。

### 5.18 2026-07-23 公开部署快照的安全问题

代码位置：`compose.prod.yml:7`、`backend/app/main.py:129`、`backend/app/main.py:199`、`backend/app/main.py:245`、`backend/app/mindmap_engine/router.py:67`、`backend/app/mindmap_engine/router.py:79`、`backend/app/mindmap_engine/visuals.py:37`、`Dockerfile:18`。

- 主 `/api` 没有认证、owner 或 tenant；任何访问者可列历史、下载全文/图片、提交复核、删除任务和消耗模型余额。
- engine/asset token 未配置时 fail-open；Compose 当前没有设置这两个 token。
- 23:08 本机无认证实测 `/api/history`、`/docs`、一个 asset URL 均返回 HTTP 200；服务端口绑定 `0.0.0.0`，因此不是仅本机问题。
- 配置 asset token 时又把长期 token 放入 URL query，并持久化进图 JSON，可能进入日志和 referrer。
- `/api/health` 暴露 Provider base URL、secret source/error 等运维细节。
- 不受限文档由 root 容器内 LibreOffice/pdftoppm 解析；Compose 无 mem/cpu/pids、cap_drop、read_only 或转换 worker 隔离。

这是独立的生产发布阻断项，与导图语义质量无关。

## 6. 对用户五项问题的归因边界

| 用户问题 | 直接根因 | 架构不完整的贡献 | 独立问题 |
| --- | --- | --- | --- |
| 1. 是否与 ZLB_2 设计一致 | Content Unit、Abstraction、Merge/Reassign、Embedding/Reranker、独立校验、Coverage Audit、HITL 和观测均未达到设计语义 | 核心结论本身 | 当前部署还来自 dirty build，未与 GitHub commit 一一对应 |
| 2. 约 30 分钟 | 历史 singleton/逐边校验；首次公网重跑又暴露 24-unit 大叶、固定 5000/7000 输出预算、三次 180 秒整请求重试 | 缺少语义分支预算和真正 Top-k/Reranker会放大 | per-call retry policy、stage deadline、增量 checkpoint、进度/降级持久化、Provider 调度均是独立工程问题 |
| 3. 文字截断/莫名摘点 | pypdf 静默漏字、跨页 chunk、`[上文衔接]`、定义正则、弱标签门，以及“只要含等号就当合法短公式”的条件顺序错误 | Content Unit 和资格门不符合设计会放大 | 解析器、噪声判别和 warning-to-degraded 协议是明确实现 Bug，不需要等待完整 C+ 才能修 |
| 4. PNG 重叠 | 双套径向布局、错误密度模型、无碰撞检测、全图同步 raster | 节点过多增加严重度 | 布局算法在任意密集合法树上都会失败，必须独立重写 |
| 5. 子节点准确性差 | 粗证据、fallback 正式发布、无真抽象、字符父召回、非 direct 边可选、假 coverage/gate | 多个核心 C+ 语义环节缺失 | Provider/schema 失败、源文件删除、无金标和人工复核 Bug 也独立存在 |

## 7. 修复优先级

### P0：先阻止错误结果和数据风险继续发布

| 编号 | 修复 | 关键模块 | 完成定义 |
| --- | --- | --- | --- |
| P0-1 | 固化 run manifest 和源文件 | main、blackboard、部署 | 每个 run 记录 source SHA256、git/image digest、parser/prompt/schema/layout/model 版本；原件按加密留存策略可重放 |
| P0-2 | 原子 SourceSpan / Content Unit | document_parser、chunking、schemas | page/slide、bbox/offset、reading order、block type、confidence 完整；禁止跨页粗 unit 和正文 overlap marker |
| P0-3 | 标签硬门与保守 fallback | heuristics、agents | 首尾虚词、括号、控制字符、页码、OCR/公式噪声、断句和 excerpt 蕴含校验；fallback 默认 deferred/needs_review |
| P0-4 | 修正节点激活、Coverage 和发布 Gate | topology、validate、cplus_pipeline | 坏节点可被拒绝；结构节点不能自证 explicit coverage；非 direct/无边证据/pending/degraded/非法标签均阻止发布 |
| P0-5 | child 级批量父候选比较 | normalize、agents、Provider | 每 child 一次排序全部父候选；实际 fallback 可观测；precision 只复核高风险子集；parent verifier/arbiter 总调用目标不超过 200 |
| P0-6 | Provider 连接池、限流、熔断和 model_calls | model_provider、queue、blackboard | 共享 AsyncClient；全局并发/令牌桶；永久错误快速熔断；每次 attempt 记录 latency/tokens/error/fallback |
| P0-7 | 统一 right-first 零碰撞 LayoutResult | GraphCanvas、export_service | 前端/PNG/SVG 共用坐标；实际尺寸布局；AABB overlap=0；右侧优先、溢出后左侧 |
| P0-8 | 鉴权、资源隔离和上传限额 | main、router、compose、Dockerfile | 所有数据端点鉴权和逐资源授权；文件/页数/解压比限额；转换非 root 隔离；未认证返回 401 |

### P1：恢复设计中的语义能力

1. 按页/节 map-reduce 生成全覆盖章节摘要；目录约束 4～8 个一级主题。
2. Root Planner 输出 unit 的 primary assignment 和有理由的 secondary assignment；unassigned 超阈值时重规划，不创建巨大“补充主题”。
3. 使用 section hierarchy + embedding cohesion 合并 singleton；leaf branch 需要多 unit，`coverage_budget` 变成真实节点/调用预算。
4. Node Scout 先输出原子 claims，再做 label canonicalization、教学价值和重复判定；合法 node 与原始 claim 分层保存。
5. 真正对高内聚 child cluster 归纳中层父节点，校验 `too_broad/too_narrow/mixed/redundant/unsupported`。
6. 跨分支语义 merge/reassignment 使用 embedding + reranker，同时保留 role 和多 branch membership；冲突进入 review。
7. 第二校验使用独立模型家族或独立判别器，而不是同模型第二次采样。
8. 视觉按章节/图密度/文本贫乏度覆盖全课件；native 与 crop 做 bbox IoU、pHash、OCR semantic reconcile；严格执行 attach/decompose/ignore。
9. checkpoint 可读取并按 stage input hash 恢复；模型输出按 source/model/prompt/schema hash 缓存。
10. 复核变成一个事务：pending + expected_version CAS、图修改、完整派生指标重算和新 version 一次提交。

### P2：形成可持续评测和运营闭环

1. 建立设计要求的 12 份开发、18 份校准、30 份盲测多解金标集。
2. 主树通过后再全局生成和独立校验 cross-links。
3. 图版本改为增量变更或共享不可变大对象，增加 schema migration 和资产引用 GC。
4. HITL 补齐 merge、split、recrop、切根、跨链接受/拒绝和局部重求解。
5. 建立 queue depth、stage latency、model attempt、429/余额、fallback ratio、tokens/cost、export memory 和 quality 指标告警。

## 8. 目标算法设计

### 8.1 输入、证据和节点

```text
原文件（content-addressed）
  -> PDF/PPTX layout adapter + OCR/formula adapter
  -> SourceSpan(page/slide, bbox, offsets, type, confidence)
  -> 同页/同节语义段落
  -> atomic Content Unit（claim/definition/formula/step/example）
  -> Node Scout 候选
  -> 证据蕴含 + 标签完整性 + 教学价值 + 去重硬门
  -> accepted candidate / deferred review / rejected with reason
```

关键规则：

- page/slide/heading 是切分硬边界；跨页表格必须显式持有多个 source spans。
- overlap 只能作为 `context_before/context_after` 元数据，不得复制进可抽取正文。
- 模型只能返回 unit/span ID；最终 page/slide/bbox 由系统回填，不能信任模型填写的位置。
- explicit node 的 excerpt 必须是对应 span 的原文子串；normalized text 与 raw text 双存。
- fallback 可以提高召回，但不能直接成为 accepted non-optional node。

### 8.2 主题、抽象和父边

```text
全文章节摘要 + 目录 + 视觉摘要
  -> 4～8 个一级主题及覆盖预算
  -> unit primary assignment
  -> 分支内 embedding cluster
  -> explicit nodes + optional abstraction candidates
  -> deterministic/embedding/reranker 父候选 Top-k
  -> 每个 child 一次批量直接父排序
  -> 高风险 child 独立二次校验/仲裁
  -> CP-SAT 节点激活 + direct-parent 边选择
  -> coverage audit + abstraction audit
```

正式边的必要条件应是：`classification=direct_parent`、证据有效、父子角色/粒度不冲突。没有正式候选时只能产生 provisional + review，不能用 unrelated/sibling 边凑成“合法树”。

CP-SAT 目标至少包含：

```text
edge_quality
+ explicit_claim_coverage
+ cluster_cohesion
+ hierarchy_directness
+ section_consistency
- unsupported_abstraction
- duplicate_node
- extra_node_complexity
- depth/fanout_violation
- role_conflict
```

### 8.3 Right-first 双侧零碰撞布局

前端、PNG 和后续 SVG/PDF 只接受同一个版本化 `LayoutResult`：

```text
LayoutResult:
  layout_version
  graph_version
  node_boxes: {node_id: x, y, width, height, side}
  edge_routes: {edge_id: points}
  canvas: {width, height}
  overlap_count
```

推荐算法：

1. 使用最终字体和换行规则测量每个节点真实宽高，不在布局后再次改变尺寸。
2. 按源章节/页序稳定排序根分支；自底向上计算 `subtree_height = max(node_height, sum(child subtree heights + gaps))`。
3. 先把根分支顺序放到右侧，右侧使用约 62% 的总高度预算；第一个放不下的分支及后续分支转到左侧，不交替抖动。
4. 两侧分别按 subtree interval 垂直居中；x 由 side、depth、相邻层最大 box width 和固定 column gap 决定。
5. 边从父/子框左右边缘锚点出发，使用稳定 Bezier 或正交路线，不穿过节点框。
6. 完成后执行 sweep-line AABB 检查；任何交叠或小于 24 px 安全间距都视为布局失败并扩展对应子树区间。
7. 超过概览预算时按完整子树折叠，实际 visible node 必须 `<=120`，而不是简单过滤 depth。
8. PNG 设置最大像素/内存预算并进入 export worker；超限提供 SVG 或分块导出，结果按 `(graph_version, layout_hash)` 缓存。

这与用户附图的“优先向右，地方不够再向左”一致，也能让预览和导出坐标完全一致。

### 8.4 两级质量门

不要继续用一个布尔值混合所有质量概念：

- `structural_gate`：唯一根、唯一父、无环、根可达、端点存在。
- `publish_gate`：structural 通过，并且非法标签=0、正式非 direct 边=0、边证据=100%、pending review=0、关键 fallback=0、节点预算满足、视觉遗漏已显式报告、业务指标达到档位阈值。

Coverage 也必须拆开：

- `source_span_coverage`：重要原始内容是否被处理或明确 deferred/rejected。
- `explicit_claim_coverage`：是否存在通过资格门的显式知识 claim。
- `abstraction_support_coverage`：抽象父是否由多个不同 child/unit 语义支持。
- branch topic 和 root 的 aggregate support 不能计入 explicit claim coverage。

## 9. 验收指标

| 类别 | 工程硬门 |
| --- | --- |
| Provenance | 100% explicit node 的 excerpt 可在记录的 page/slide+bbox/span 精确定位；错页率=0；missing location=0 |
| 标签 | `[上文衔接]`、首尾虚词、未配对括号、纯页码、控制字符、明显截断标签均为 0 |
| Unit | 普通跨页 text unit=0；overlap 重复正文=0；扫描/纯视觉页有 OCR 或显式 deferred |
| 视觉 | `analyzed_pages + explicitly_deferred_pages = rendered_pages`；未报告跳过页=0；attach 转独立节点=0；native/crop 重复=0 |
| 主题 | 一级主题通常 4～8 且受目录约束；primary assignment >=95%；singleton structural branch=0 |
| 规模 | 最终节点 30～150；概览 visible nodes <=120 |
| 节点业务指标 | 原型节点精确率 >=0.82，试用 >=0.90；无证据正式节点=0 |
| 层级 | 正式树边 100% direct_parent 且有边证据；原型直接父准确率 >=0.72，试用 >=0.84 |
| 复核 | publish gate 时 pending=0、provisional=0；原型复核决策占比 <=0.30，试用 <=0.15 |
| 稳定性 | 同 source/model/prompt/parser 版本：ledger 一致；节点名 Jaccard >=0.85；命名树边 Jaccard >=0.75，试用阶段继续提高 |
| 降级 | 无 silent fallback；任何实际 fallback 都进入 model_calls/warnings；关键阶段 fallback 时 publish gate=false |
| 性能 | 92 页 precision 冷运行目标 P95 <=10～12 分钟；parent verifier+arbiter 调用 <=200；需在当前 Qwen-only 镜像实测确认 |
| 布局 | 10/120/336/1000 节点夹具 AABB overlap=0，最小间距 >=24 px；前端/PNG 同节点坐标误差 <=1 px |
| 导出 | 336 节点冷导出目标 <3 秒、缓存 <200 ms、峰值内存 <256 MiB；超预算不允许同步生成超大 raster |
| 恢复 | 每个阶段强杀后从最近 checkpoint 继续，不重复已提交模型调用；failed/cancelled 在 history 可见 |
| 安全 | 未认证数据/资产/变更端点返回 401；跨 owner 返回 403/404；超限文件 413；公网只暴露 TLS 入口 |

原设计中的祖先 F1、跨链精确率、知识图像召回和根/一级主题评分也必须保留，不能用当前 coverage 和平均边分替代。

## 10. 回归测试矩阵

| 层 | 必测夹具 | 核心断言 |
| --- | --- | --- |
| PDF 断行 | 第 11 页“复杂原子\n的光谱结构（即使是类H离子和He）” | 不产生 `的光谱结构（即使`；证据页=11；括号完整 |
| Chunk overlap | 两页边界且上一页末尾有短标题 | `[上文衔接]` 不进入正文/节点；内容不重复；span 仍指向原页 |
| OCR/公式 | 扫描 PDF、PUA 和公式密集 PDF | 不在 parse 阶段失败；公式作为结构化或低置信 deferred，不作为乱码节点 |
| PPTX 顺序 | title/body/table/chart/group/SmartArt/notes/hidden slide | 阅读顺序、slide+bbox、父组和对象类型正确；真实 PPTX E2E |
| Content Unit | 定义、公式、例题同页 | 拆成原子 unit，不跨页；每个 unit 可精确回源 |
| 视觉上限 | 92 页且第 80 页有唯一知识图 | 报告并处理第 80 页；analyzed+deferred=92；无静默截断 |
| 视觉 reconcile | 同一图片作为 native、整页 crop、缩放 Logo | pHash/IoU 去重；decompose parent-child 完整；attach 不被独立发布 |
| Schema 部分失败 | 合法 nodes + 非法 cross-link | 保留合法 nodes；坏字段单独拒绝/修复；model_calls 记录失败类 |
| 标签门 | `但是`、`与管壁碰`、未闭合括号、32 字断尾 | 全部 reject/defer，不能 accepted |
| Coverage | branch topic 支持全部 units，但无 explicit claims | explicit claim coverage=0，publish gate=false |
| Merge | 不同 branch 同名、role/definition 冲突 | 不静默合并；保留 membership 或产生 review |
| Abstraction | 两个内聚簇和一个混合簇 | 只为内聚簇建抽象父；混合簇 reject/review |
| Parent verifier | 一 child 五候选、返回错误 parent/child ID | 单次批量排序；ID 不匹配拒绝；不产生 silent fallback |
| Solver | 只有 unrelated/sibling 候选 | 只能 provisional + review，不能选择为正式边 |
| Quality gate | pending、degraded、非法标签、非 direct 边各一例 | 任一条件存在时 publish gate=false |
| 稳定性 | 同一 source 连续运行 5 次 | ledger 相同；节点/边 Jaccard 达门；差异带明确模型版本 |
| 布局 | 10/120/336/1000 节点、最长中英文标签、局部高 fanout | overlap=0；右优先溢出转左；稳定顺序；坐标跨导出一致 |
| Export 资源 | 336 节点并发 10 次导出 | 有队列/缓存/像素上限；不 OOM；health P95 不明显退化 |
| Provisional review | 非根 parent -> child 临时边 | 操作对象严格是 edge.target，不误改 parent |
| Review 并发 | 同 version 两个并发动作 100 轮 | 一个成功一个 409 或正确串行；无 lost update/resolved 回滚 |
| Delete review | 删除有 children/cross-links/reviews 的节点 | 无 dangling endpoint；重新校验父边和全部质量指标 |
| 恢复/取消 | 每个 stage 强杀、运行中删除、余额耗尽 | 可恢复/可取消；永久错误一次探测后熔断；资产无孤儿 |
| API 安全 | 匿名、跨 owner、超大/畸形/zip bomb 文件 | 401/403/413；转换器资源受限；日志无 key/token |

截至 2026-07-24，当前测试已经覆盖其中大量工程硬门，包括断行/页边界、
视觉状态、分支容量、Provider 错误语义、父边批量校验、求解、复核事务、
鉴权、上传和 right-first AABB 布局；完整后端为 161/161，性能专项 8/8，
PDF 输入专项 8/8，前端 7/7。仍未覆盖或未达到业务闭环的重点包括：
真实 `.pptx` 对象层、OCR/公式语义恢复、解析漏字召回率、候选第 30 页的混合
PUA+轴+残缺公式、语义分支内聚度、人工节点/父边金标、浏览器字体坐标一致性
和第二次 92 页完成态重跑。

## 11. 实施顺序与止损原则

建议按以下顺序实施，不能先调 prompt 再观察：

1. **先冻结可复现基线**：clean commit 构建、run manifest、保留源文件、model_calls、固定评测集。
2. **先阻止坏数据发布**：SourceSpan、标签硬门、fallback deferred、solver 可拒绝节点、publish gate。
3. **再压缩规模和调用**：章节主题、semantic branch、节点预算、child 级父候选批量校验、连接池/限流/缓存。
4. **再提高语义结构**：真正 abstraction induction、跨分支 merge/reassignment、embedding/reranker、独立校验。
5. **并行独立修布局**：统一 LayoutResult、right-first tidy tree、碰撞硬断言、export worker。
6. **最后用金标校准阈值**：没有节点/父边人工金标前，不把 coverage 或平均模型分包装成准确率。

以下情况必须直接阻止发布，而不是继续显示“主树合法”：

- 任何关键阶段静默 fallback；
- 任一 accepted label 不完整；
- 任一正式边非 direct_parent 或无边证据；
- 任一 pending/provisional；
- 视觉页被静默跳过；
- 节点数、根 fanout 或布局碰撞越过硬门；
- run 无法追溯到 source/code/model/prompt/schema/layout 版本。

## 12. 尚未验证的事项

1. 新上传测试包包含 10 个 PDF、639 页，没有 `.pptx`。因此可以逐页对照 PDF 内容，但仍不能完成“PPTX 对象、SmartArt、notes、hidden slide、z-order”级人工评测；必须另补真实 `.pptx` 金标。
2. Qwen-only 第一版公网镜像已经产生一次 92 页运行现场，但在 Branch 阶段止损取消，没有 graph version；旧 DeepSeek/Kimi 分钟数和这次 25 分 51.699 秒都不能作为最新候选的完成态 SLA。
3. 旧历史镜像没有固化 image/git digest，无法做到字节级还原；当前控制流中与根因相关的解析、chunk、分支、校验、求解和质量门逻辑仍可直接核验。
4. 295 对 PNG 碰撞和 92 对前端概览碰撞是对保存图版本按当前两套布局算法的 AABB 计算；修复后必须把同一检查变成自动测试，而不是继续人工看图。
5. 节点精确率、直接父准确率、祖先 F1 和视觉召回仍需人工多解金标；本报告证明当前结果不满足必要条件，但不伪造一个未经标注的“准确率”。
6. 候选容器真实第 30 页当前仍会被错误标成 `uncovered`；在对应 TDD 转绿、候选重建并完成真实页复验前，不能宣称 PDF 垃圾摘点问题已经完全解决。

## 13. 最终归因

本次问题的总根因可以归纳为四层：

1. **证据层失真**：结构解析、原子 Content Unit 和 provenance 未实现，原文断行和错误页码进入后续阶段。
2. **候选层失控**：模型失败后启发式残片正式发布，Branch Plan/节点/父候选没有预算，抽象和语义召回名存实亡。
3. **收口层只保合法、不保正确**：CP-SAT 强制激活大多数节点并允许非 direct 边，Coverage 和 Gate 又以 ID 存在替代语义正确。
4. **运行与呈现层缺少工程硬门**：千级逐边调用、无连接复用/熔断/队列/恢复，双套径向布局无碰撞检测，公开 API 又没有鉴权和资源限制。

修复的核心不是继续扩充阶段名，而是把每一阶段的输入、输出、失败状态和发布资格变成可验证的硬契约。只有在 provenance、节点资格、direct-parent、publish gate 和零碰撞布局都成为自动化门禁后，模型升级才会真正转化为结果质量，而不是被现有确定性缺陷抵消。

## 14. 2026-07-24 TDD 修复实施附录

### 14.1 如何阅读本报告的“旧事实”和“当前事实”

第 2～13 节记录的是 2026-07-23 审计快照及当时部署的根因；第 1 节和本节记录的是 2026-07-24 当前 TDD 工作树。两类事实不能混用：

- 历史 7 个任务及其 20～48 分钟耗时、1715 个节点、13503 条父候选、295 对 PNG 碰撞，仍是旧实现的有效证据。
- 旧历史 graph version 不会因为代码升级自动变成新算法结果；它们只能用于回归布局、兼容加载和根因对照。
- 以下“已修复”表示新代码和自动化夹具已经通过，不表示旧图的业务语义已被自动纠正。
- 第一版 TDD 镜像已经部署到公网，但最新长文档/PDF 补丁目前只在本地候选验收；“公网已部署第一版”不等于“当前工作树已部署”，更不等于第二次重跑已经完成。
- 当前已有真实 PDF 测试原件，但仍没有真实源 `.pptx` 和人工多解金标，因此不能把工程门通过等同于节点业务准确率达标。

### 14.2 并行 Agent 与文件所有权

本轮先采用四条互不覆盖的主 TDD 工作流，再按第一次回归暴露的边界追加七条收尾工作流。追加工作流按文件所有权串行接管可能重叠的核心文件，避免并发覆盖用户已有的 dirty worktree 修改。

| 工作流 | 所有权 | 先写的失败测试 | 主要目标 |
| --- | --- | --- | --- |
| 输入/证据/视觉 | parser、chunking、heuristics、visual analysis | `test_input_pipeline_tdd.py` | 页边界、断行、标签、bbox、视觉覆盖与去重 |
| 图语义/父边/求解 | agents、normalize、topology、validate、cplus | `test_graph_quality_tdd.py`、`test_topology_fallback_tdd.py`、`test_normalize_structural_identity_tdd.py` | 节点预算、父边批量校验、身份/provenance、CP-SAT/greedy 等价、发布门 |
| 布局/PNG | pure layout、export、GraphCanvas | `test_layout_tdd.py` | right-first、实际尺寸、零碰撞、像素预算 |
| 运行/安全/复核 | provider、blackboard、main、review、compose | `test_ops_tdd.py`、`test_runtime_security_tdd.py`、前端生命周期测试 | 连接复用、熔断、任务恢复、CAS、鉴权、上传边界 |
| 资产 URL 与会话鉴权 | visuals、engine router、auth | `test_asset_auth_tdd.py` | URL 去长期 token；session/header 鉴权；query token 失效 |
| 任务状态与复核派生量 | main、job runtime、review、model-call context | `test_job_recovery_tdd.py`、`test_ops_tdd.py`、`reviewActions.test.mjs` | job/run 同步失败；shutdown 可恢复；复核契约与完整重算；并发上下文隔离 |
| 生产路由与外部视觉上传 | main、engine router、upload validation、config | `test_production_hardening_tdd.py`、`test_engine_upload_tdd.py` | docs 404；有界复制；真实格式、像素预算和临时文件清理 |
| age secret 非 root 启动前检查 | secret preflight、compose | `test_secret_preflight_tdd.py` | 只检查元数据；拒绝 symlink/world-readable；通过后 `exec` |
| 视觉 ledger 状态机 | visual analysis、theme/branch payload、C+ degraded 分类 | `test_visual_state_tdd.py`、`test_visual_degradation_classification_tdd.py`、`test_graph_quality_tdd.py` | ignored/rejected、crop deferred、occurrence provenance、budget/partial degraded、良性去重告警不阻断发布、attach-only 隔离 |
| verifier 运行时降级 | verifier stats、pipeline publish gate | `test_verifier_degraded_tdd.py` | primary/secondary/arbiter partial/failed fallback 可观测且阻止 publish |
| 代码—文档与隔离部署复核 | 文档、Dockerfile、Compose、历史验收记录 | 只读审计 + 最终验收矩阵 | 删除过度声明；区分 config、旧镜像验收、当前最终镜像与公网部署 |

有代码变更的工作流均执行了“旧实现 RED -> 最小修复 -> targeted GREEN -> 全量回归”；只读审计工作流不伪造 RED 测试，而是将发现转成文档边界或交给对应代码工作流补测试。

### 14.3 根因到代码修复的逐项闭环

| 原根因 | 代码/算法级修复 | 自动化硬门 | 当前状态 |
| --- | --- | --- | --- |
| chunk 跨页且把 `[上文衔接]` 写进正文 | page/slide/heading 成为硬边界；overlap 迁移到 `Chunk.context_before` | 正文不含 marker；旧 Chunk 可加载；chunk 不跨页 | 已实现 |
| PDF/PPT 物理断行、错误阅读顺序和 legacy Symbol PUA 公式丢失 | PDF layout 模式、英文断词修复、中文硬换行合并；含数学 PUA 的正文页也与 Poppler 比较；恢复 `λ/ν/×/≈/⇒`、`Δν/ν`、`10^-15`、`nL=kλ_k/2`、`λ_k=2nL/k`；PPT 标题优先后按 top/left | 中英文断行、PPT 空间顺序、数学页回退和真实 p85/p86/p88 公式夹具 | 已实现已知课件模式；扫描件、通用公式 OCR 和复杂版面仍未完成 |
| heuristic/模型把残句、虚词、未闭合括号或污染字段正式建点 | parser 清理 + heuristic/critic/normalize 共用 `is_publishable_label` 和 `candidate_field_disposition`；按字段执行 repair/trim/reextract/reject，不再静默截 32/36 字，也不再把“命中一个坏字段”一律解释为整节点删除 | 历史异常 label/definition 逐项 RED；5 个合法 label 修复保留、4 个 definition 裁剪保留、真正双字段坏节点拒绝 | 已实现字段级处置 |
| 合法长根标题在 PNG 包装层被省略号截断，看起来像生成阶段断句 | exporter 对 root 按合法长度预算最多 8 行完整换行，并按实际行数增高节点框，不再用固定四行截断 | 合法长 root 文本逐字保留、无 `…`、高度随行数增长且布局仍零碰撞 | 已实现导出显示修复 |
| fallback 节点默认 mandatory 并静默发布 | fallback/coverage repair 默认 optional；激活后产生 pending review | fallback 节点不可无声 accepted | 已实现 |
| branch topic 的 support IDs 自证 explicit coverage | structural/abstractive/root 不再计入 explicit claim coverage | 只有结构 topic 时 coverage 不得为 100% | 已实现 |
| explicit 节点只要引用存在的 unit ID，伪造 excerpt 也能自证 coverage | 新增统一 evidence-source matcher：文本 excerpt 去空白归一后必须是 unit text/evidence/OCR/summary/claim 的子串；视觉证据必须匹配 asset；audit 与复核重算共用该规则 | 引用正确 unit ID 但 excerpt 来自另一知识点时 weighted coverage=0 | 已实现来源一致性门；仍不是语义蕴含或精确 span |
| normalize 合并同名 structural topic 与 explicit concept 时，高置信 explicit 可覆盖结构身份，或 structural evidence 反向冒充 explicit provenance | 节点 identity 采用独立结构优先级选择；合并 evidence 的同时单独保存 `explicit_evidence_unit_ids`，coverage 只认 explicit 来源 | structural role/origin/mandatory 身份保留；只有 explicit 候选贡献的 unit 被计入内容覆盖 | 已实现身份与 provenance 分离 |
| unit 在候选阶段标为 covered，支持它的候选节点求解落选后仍保持 covered | `_enrich_result` 以最终 `solved.nodes` 重新运行 coverage；只有最终 accepted explicit evidence 支持的 unit 保持 covered，候选态假覆盖回退 deferred | 候选节点不在 solved tree 时 unit status=deferred 且进入 uncovered IDs | 已实现最终态 ledger 对账 |
| singleton Branch Plan、overflow 污染和超大叶分支 | 一级分支最多 8、leaf 最多 24；按 `max_units_per_leaf` 先计算全局必需叶数，每个 planning unit 在叶层恰好出现一次，每叶最多 8；容量不可能时显式失败 | 136-unit 现场形状得到不超过 24 个 leaf、最大 8 units、无遗漏/重复；193-unit 不可满足形状拒绝 | 容量硬门已实现；overflow 仍是确定性扩展分支，尚未做语义重聚类，不是真正递归 Planner |
| 跨分支同名被全局静默合并 | 跨 branch 同名保留独立 ID并告警 | 同名不同 branch 仍有两个节点 | 已实现 |
| 同分支 fuzzy name 或 evidence 中的正确公式可把冲突 claim “洗白”并误并 | 删除 `SequenceMatcher>=0.94` 合并入口；改用 provenance-grounded、complete-link 的确定性语义去重；公式用精确有理数与变量幂判定代数等价，并保护冲突公式/数字、反向因果、同页异 claim、结构节点和互补父子事实 | 五组正式跨模态重复可合并；`nkλ/2=L` 不得与 `nL=kλ_k/2` 合并；错误 definition 不得借 evidence 中正确公式进入簇；输入顺序不影响 survivor/ID/evidence | 已实现保守语义去重；仍没有 embedding/reranker 和跨分支重分配 |
| 同一分支存量节点规范化同名未计为质量冲突 | `build_quality_report` 按 `(branch_id, normalized_key(name))` 计数，并把重复数加入 `conflict_count` | 空白变体同名触发 warning 且 publish gate=false | 已实现 |
| concept 两两扫描造成 O(N²) 父候选 | 父池限制为 root/branch/structural；不再生成大批 concept→concept 伪边 | 80 leaf 场景候选为线性边界 | 已实现 |
| 每条 Top-k 父边单独调用模型，随后虽改成每 child 一次但仍产生大量物理 HTTP | 同一 child 的全部候选作为一个逻辑单元，最多 4 个 child 合并为一次物理 HTTP；primary、secondary、arbiter 分角色批量；坏 child 只局部 fallback | 8 child 只发 2 个 HTTP batch；缺失/未知 child 不污染同批其他 child；batch/child 双层统计 | 已实现 4-child batching；完整 92 页生产墙钟尚待重跑 |
| verifier 实际调用失败后用确定性票兜底，但只写 warning、不标记 degraded | 每轮返回 primary/secondary/arbiter 的 requested/succeeded/fallback batch 统计；按部分失败或全失败写入结构化 degraded component | standard partial/all fallback、precision second/arbiter failure 均阻止 publish | 已实现运行时降级闭环 |
| 非 direct、无 evidence 边可成为正式主树边 | 只有 `direct_parent + evidence` 具备正式求解资格；否则 provisional + review。结构父边可由父子共享 unit 生成 support mapping | unrelated/sibling/空 evidence 不能正式发布；结构 mapping 可追溯 | 工程资格门已实现；support mapping 不等于父子关系语义蕴含 |
| competing-parent review alternatives 丢失候选关系 evidence | review view 的每个 parent alternative 保留 classification、score、provisional 和序列化 evidence | change_parent 可验证并继承所选候选的真实关系证据 | 已实现 |
| CP-SAT 强制保留坏 explicit 节点，或用高父边分补偿负 activation margin | optional 节点可不激活；CP-SAT 与 greedy 对 `activation_score<=activation_cost` 的 optional 节点硬拒；增加 150 节点、root fanout 8、普通 fanout 12、固定种子 | 弱节点即使有 0.82 合法父边也不激活；求解稳定 | 已实现工程拒绝门 |
| greedy fallback 可保留只有一个 child 的 optional abstraction，与 CP-SAT 语义不等价 | greedy 完成选边后识别 fanout<2 的 optional structural/abstractive 节点，排除后重新求解 | 强制 fallback 时单 child 抽象被移除，leaf 重新挂到合法 parent | 已实现求解器等价门 |
| abstraction support 把同一 unit 在 support IDs 与 evidence 中重复计数 | 所有 abstraction review/质量指标先对 unit ID 求集合，再判断至少 2 个独立支持 | 同一 unit 出现在两个字段时 support_count=1 | 已实现唯一支持计数 |
| 一个布尔 Gate 混淆结构合法和可发布 | 增加 structural/publish 双门；pending、degraded、非法标签、非 direct、无边证据、超预算均阻止 publish | 每个失败条件独立测试 | 已实现 |
| provisional review 可能把 parent 当 child | `ReviewItemView` 固化 `subject_id/subject_type`；服务只操作显式 subject | `[parent, child]` 顺序下仍只修改 child | 已实现 |
| `_enrich_result` 生成复核卡片时把选定 subject 覆盖为最后一个 preview member | 保留 `_review_subject()` 的 `subject_id`，预览循环改用独立 `member_id` | parent/child 不同且 child 排在首位时，最终卡片仍指向选定 child/tree edge | 已实现 |
| 前端展示的 review 动作与后端事务允许集合不一致 | 前端抽出 `reviewActionsForType`，与后端 action matrix 逐类型镜像测试 | cross-link 不出现节点变更动作；其余类型动作集合与后端一致 | 已实现 |
| 人工复核分多次写库，无版本竞争保护 | 请求必须携带 `expected_graph_version`；review、图修改、指标重算、decision、version 在一个 `BEGIN IMMEDIATE` 事务提交 | stale version 无任何部分写入 | 已实现 |
| 删除中间节点伪造 score=1 direct edge | 清理关联 cross-links/reviews；子节点仅生成降权 `uncertain + provisional` 重连并进入复核 | replacement score<1 且 publish=false | 已实现 |
| rename 可写入异常残片，复核后沿用旧质量指标 | rename 复用 `is_publishable_label`；每次复核重新计算拓扑、冲突、weighted coverage、coverage summary、平均边分、abstraction support 与 publish gate | 非法 rename 无部分写入；`conflict_count>0` 阻止 publish | 已实现 |
| 每次 Provider 请求新建 AsyncClient | 按 Provider/base URL 共享 AsyncClient 和 keep-alive pool；全局 Provider semaphore | 多次逻辑调用复用 Client | 已实现 |
| precision 五个逻辑角色对同一 Qwen 模型重复执行五次 `/models` 预检 | `build_role_runtimes` 只创建并预检一个 checked runtime，generator/verifier/vision/second/arbiter 共享同一已检查 client 与 availability | precision 五角色断言 `check_model` 仅调用一次 | 已实现 |
| 重试所有错误，或把任意 400 都当成 Provider 全局故障 | 只重试 timeout/429/5xx并读取 `Retry-After`；普通 400 仅终止当前逻辑请求，只有 401/402/403 或鉴权/余额/配额类错误打开全局熔断 | 429 可重试；普通 400 一次失败但下一请求可成功；401 后第二次零网络请求 | 已实现分层错误语义 |
| Provider 可用极大的 `Retry-After` 让 worker 休眠数小时 | 所有指数退避和秒数/HTTP-date `Retry-After` 先经过配置上限，再经过 300 秒硬上限；NaN/inf/overflow 回落到上限 | `Retry-After: 86400` 被限制到配置值；配置超大仍不超过硬上限 | 已实现等待时间硬边界 |
| `model_calls` 表为空且并发 stage 上下文可串扰 | frozen `ModelCallContext` + 可嵌套 `model_call_scope` 将 run/stage/branch/input units 注入每个实际 HTTP attempt；记录 latency/status/error/attempt | 并发安全嵌套 scope；branch 与 input unit IDs 可在 SQLite 查询 | 已实现基础追踪；token/cost/hash/cache 未实现 |
| checkpoint 只写不读，候选表遗留 stale rows | 增加 checkpoint 读取；阶段集合保存改为 replace；run 重启复用原 run ID | checkpoint round-trip；淘汰候选从表中消失 | 已实现基础恢复 |
| job 仅内存、不能 cancel、重启后 404 | jobs 表持久化 queued/running/failed/cancelled；保存 Task handle、全局 job semaphore、取消并 await；保留源文件后重启重排 | 并发=1 串行、cancel finally 完成、非终态重开可读 | 已实现重排恢复 |
| pipeline 异常只更新 job 或 run 一侧 | pipeline 失败统一把 `jobs` 与 `runs` 写成 failed | 故障夹具断言两表状态一致 | 已实现 |
| 服务停机和用户取消共用 cancelled 语义 | `JobRuntime.cancel(reason=...)` 区分 user 与 shutdown；停机写回 `queued/interrupted`，启动时重排；用户操作仍为 cancelled | shutdown 后 job queued/stage interrupted、run queued | 已实现可恢复停机语义；仍非 stage 精确续跑 |
| 从 parse 重排却沿用上次 70%～90% 进度 | `upsert_job` 对 `queued/recovered` 允许显式重置 progress，`recover_jobs` 在重新排队时写 0；后续仍使用单调进度 | 旧 88% running job 恢复后变为 queued/recovered/0 | 已实现 attempt 级进度重置 |
| 恢复时源文件缺失只把 job 标 failed | missing-source 分支同时查询 run ID 并写 `runs.status/stage=failed` | 源文件缺失时 job/run 同步 failed 且不调度 | 已实现 |
| 进度 4% 后被 pipeline 3% 倒退 | 所有进度更新使用 bounded monotonic merge | 42→3 保持 42 | 已实现 |
| 上传只看扩展名且无限制 | SHA256 流式复制；字节、PDF/PPT 页数、MIME、magic、OOXML marker、解压总量和压缩比硬门 | spoof、超大、超页、zip bomb 均拒绝 | 已实现 |
| 外部视觉 render 上传无有界复制/真实格式验证，图片可形成像素炸弹 | engine route 复用 `copy_upload_limited` 和统一验证；PNG/JPEG/WEBP 用 Pillow、PPTX 用 python-pptx、PDF 用 pypdf；复制/校验卸载到线程；render 前检查 `width×height` | 超大 413；伪装/损坏 422；临时文件总是清理；`MINDMAP_MAX_IMAGE_PIXELS` 生效 | 已实现 |
| 主 API 无认证和 owner | 生产环境未配置 token 时 fail-closed；HttpOnly session；所有数据路由按 owner 查询 | production 缺 token 关闭；错误 token 拒绝 | 已实现 |
| engine/asset token 空时 fail-open | production 缺 engine token 时 engine 返回 503；资产端在 asset/API 两种认证都未配置时返回 503，已配置认证但请求无有效凭据时返回 401；健康信息不再暴露 data dir 或 secret 错误 | 无认证配置 fail-closed；无效凭据不降级放行 | 已实现 |
| 长期 asset token 被持久化进 URL query | 资产 URL 构造移除 query token，并剥离 `ASSET_PUBLIC_BASE_URL` 自带 query/fragment；资产读取只接受同源 HttpOnly API session、Bearer 或 `X-Engine-Token` | URL 无 secret；`?token=` 不再鉴权；合法 session/header 可读取 | 已实现 |
| production 禁用 docs 后仍由 SPA fallback 返回 200 | SPA catch-all 对 `/docs`、`/redoc`、`/openapi.json` 及子路径显式 404 | production 文档路径全部 404 | 已实现 |
| 运行任务删除和后台写库竞态 | delete 先 cancel/await，再删除 DB、源文件和资产 | JobRuntime cancel 等待 cleanup | 已实现 |
| `ignore_decoration`、crop 失败和视觉重复项在 ledger 中静默消失或跨页误去重 | decoration 保存 rejected unit；单项/批次 crop 失败保存 deferred；同页 pHash 重复去副本，跨页/跨 slide 重复复用内容但保留 occurrence unit/asset provenance；decompose 指回全页父资产；deferred 从模型 payload 隔离 | ignored/deferred 保留 page/bbox/claim；同页只留一份；跨页出现位置不消失；attach-only 不得建独立节点 | 已实现第一层状态机；复合区域子 region schema 等仍缺 |
| 视觉 page budget 在全量栅格后才生效，或部分页面分析失败仍被当成完整视觉结果 | PDF/PPTX 在 raster 前分层选页；render budget、analysis page budget、partial page failure 写结构化 warning，并进入 publish-blocking degraded component | 5 页预算 2 只 raster 第 1/5 页；预算跳页/部分失败均 `analysis_complete=false` | 已实现预算前止损与降级信号；业务全页召回仍未实现 |
| C+ ledger 把所有 `rendered.warnings` 一律解释为 `visual_rendering` degraded | `_render_warning_degraded_components` 只解析 `[visual_degraded:*]` 机器码；`render_budget`、`render_failure`、`native_extraction` 映射为稳定 component，普通 pHash 同页去重和跨页复用提示只作为可观测 warning 保留 | 两类良性重复提示得到空 degraded 列表；三类机器码准确映射且重复 code 去重 | 已实现告警/状态协议分离，避免重复 logo 误关 publish |
| PNG 在 async API 同步生成 | export semaphore + `asyncio.to_thread`；布局层在分配前限制 16M pixels/8192 dimension | 大图不会先分配一亿像素 | 已实现 |
| 双套 360° 径向布局重叠 | Python/TypeScript 分别实现同一 right-first 合同：实际框尺寸、bottom-up extent、62% 右预算、溢出后全左 | Python 10/120/336/1000 节点夹具最小间距 >=24；PNG 使用该布局 | 已实现算法合同；尚非单一持久化 LayoutResult |
| 前端 700ms `setInterval` 重叠轮询 | 请求完成后才安排下一次，900ms～10s 指数退避；localStorage 恢复 task；running 状态禁止换文件；支持 cancel | 前端生命周期 4 项测试 | 已实现 |
| UI 把结构失败也写成“主树合法” | 根据 structural、publish、degraded、pending 分别显示 failed/degraded/review/passed | 四种状态映射测试 | 已实现 |
| Compose secret `mode` 声明给出虚假安全感，非 root 进程实际可能读不到或被迫 world-readable | 启动前只用 `lstat` 验证普通文件、非 symlink、UID 0、GID 10001、0440，通过后 `exec` uvicorn；删除无效 `mode: 0444` 声明 | 10 项 preflight/Compose 测试 | preflight 已实现；公网使用的 Qwen 生产 secret 已按 UID/GID/mode 门验收，token 文件本身保持宿主 root-only；不得改为 world-readable |
| 容器 root、公网双端口、无资源约束 | 非 root UID 10001；read-only、cap_drop ALL、no-new-privileges、CPU/内存/PID 限制；最终公网仅映射宿主 5173 | Compose 静态配置、候选和公网 runtime 可验证 | 第一版 TDD 镜像已公网切换，旧 8000 宿主映射已关闭；最新候选尚未切换，且当前仍是明文 HTTP |

#### 14.3.1 二次审计新增的独立根因

第一次四路修复后继续按“写入点—状态机—发布资格—生产入口”逆向追踪，新增发现并非 C+ 语义架构缺失的同义反复，而是彼此独立的实现错误：

| 混乱点 | 代码级根因 | 若不单独修复的后果 |
| --- | --- | --- |
| job 显示 failed、run 仍 running | 异常处理在两个持久化实体上没有统一终态提交 | history、恢复器和运维判断互相矛盾 |
| shutdown 被记成用户 cancelled | cancellation 没有原因字段，优雅停机与业务取消共用一条分支 | 可恢复任务在重启前被永久终结 |
| 从 parse 重排时 UI 仍停在旧 88% | blackboard upsert 对所有状态一律 `MAX(old,new)`，内存更新又要求单调；没有“新 attempt”重置语义 | 用户误以为 stage 精确续跑，早期 parse/theme 进度全部被旧高水位遮蔽 |
| 恢复源文件丢失后 run 仍显示 running | missing-source 异常分支只更新 jobs 表，没有同步 runs 终态 | 无法恢复的任务持续污染运行中统计，与 job 详情矛盾 |
| 复核完成但 coverage/conflict/发布门仍是旧值 | review 修改图后只保存部分字段，派生指标没有从新图重算 | 人工改坏图后仍可能显示可发布，或修好后仍被旧失败状态阻塞 |
| 复核卡片 subject 偶发指向 preview 列表最后一个成员 | `_enrich_result` 的 preview 循环复用了 `subject_id` 变量名，覆盖先前选定的 child/edge subject | 用户执行 keep/delete/change_parent 时可能操作错误节点，且下游服务本身的 subject 保护无法弥补错误 view |
| 图中看见省略号就误判为模型生成了残句 | 节点语义值与 PNG 显示值共用有限 `max_lines` 包装，合法根标题在 render 阶段被截断 | 排查被带偏到 prompt/模型，实际是 exporter 的展示层二次截断 |
| `unit_id` 合法就被当成“原文支持” | coverage 只校验外键存在，不检查 excerpt 是否来自该 unit | 模型可把 A 段 ID 与 B 段断言拼接，coverage 仍虚假升到 100%，复核重算也会复制该假象 |
| 同名合并把“结构身份”和“显式证据来源”压成一个 origin | normalize 只选一个 primary candidate 的 role/origin，却把所有 evidence 混在一起 | 高置信 explicit 覆盖 mandatory branch topic 身份，或 structural support 被错误计成 explicit coverage |
| candidate ledger 的 covered 被当成 final ledger | coverage audit 在求解前更新 unit，`_enrich_result` 原样发布该状态，没有按 solver 实际保留节点反向对账 | 被 solver 拒绝的知识点从 uncovered 列表消失，publish gate 获得乐观输入 |
| 高分父边可以“买下”负收益 optional 节点 | CP-SAT 目标中的 edge score 权重高于负 activation margin，greedy 又只看是否存在可选父边 | 低质量边缘摘录即使节点价值低于成本，仍被正式挂入树 |
| CP-SAT 与 greedy 对 optional abstraction 的资格不同 | greedy 只要能挂边就保留抽象节点，没有执行“至少两个 child”语义 | CP-SAT 异常切到 fallback 后，同一输入会多出单 child 空壳抽象 |
| support ID 与 evidence 指向同一 unit 被算成两个支持 | abstraction review/quality 直接相加两个列表长度 | 单条原文可伪装为“至少两条独立材料”，抽象父被低估风险 |
| parent review alternative 只保存 parent_id/score | relation classification/evidence 在生成复核卡片时丢失 | change_parent 无法证明新边资格，只能伪造或盲信人工选择 |
| verifier fallback 只有自然语言 warning | runtime 标记 available 后，单批或整批调用失败仍用确定性票返回，degraded 只看启动时 availability | 独立校验实际上未执行，publish gate 却可能仍为 true |
| 同分支规范化同名不进入质量冲突 | normalize/复核之外的存量图缺少最终 duplicate audit | 旧图或其他写入路径可保留两个视觉不同、语义同名的正式节点 |
| 资产 URL 带长期 query token | URL 生成层把认证材料当资源标识持久化 | token 进入图 JSON、日志、缓存和 referrer |
| production docs 禁用但仍 HTTP 200 | FastAPI docs route 被关闭后，请求落入 SPA catch-all | 安全扫描误判、路由边界模糊，未来还可能意外暴露内部页面 |
| engine 图片入口与主上传入口规则不一致 | 两条 route 分别复制和验证文件，外部 engine 路径绕过字节/格式/像素预算 | 畸形文件造成 500、事件循环阻塞或大像素内存压力 |
| Compose 写了 secret mode 即假定容器可读 | bind-backed Compose secret 不保证声明 mode 真正落盘，且容器以 UID/GID 10001 运行 | 要么启动失败，要么运维为“能跑”把密钥改成 world-readable |
| 视觉 ignored/crop failure 被直接丢弃 | 决策、资产和 ContentUnit 没有完整状态转换，异常分支只 warning/continue | coverage 无法区分“确认为装饰”与“分析失败”，后续模型还可能消费半成品 |
| pHash 去重不区分“同页副本”和“跨页再次出现” | 全局 seen hash 直接删除后续匹配项 | 同一教学图在另一页承担新的上下文时，其 occurrence provenance 被抹掉 |
| page budget 在全量 raster 后才裁剪分析列表 | 渲染层不知道视觉页预算，92 页仍先生成全部大图 | 即使 VLM 只看少量页，CPU、磁盘和内存开销仍接近全量 |
| 视觉跳页/单页失败只产生普通 warning | warning 没有机器可判定的 budget/partial failure code | publish gate 无法区分“没有知识图”和“根本没分析完” |
| 所有 render warning 都被升级为同一个 `visual_rendering` degraded | C+ ledger 把人类可读提示和状态机信号混用，只要 `rendered.warnings` 非空就关闭 publish，没有解析可枚举错误类型 | 常见 logo、模板图片或教学图的正常 pHash 同页去重/跨页复用也被误判为渲染失败；同时真正的 budget、render failure、native extraction 无法稳定分组件归因 |
| 并发模型调用共享可变 stage | model-call 上下文原先通过可变对象跨嵌套任务传播 | branch、stage、input unit 归因串线，延迟和错误分析失真 |
| precision 启动前重复五次模型可用性检查 | 五个逻辑角色各自调用 `_runtime()`，虽然 Provider/model 相同仍重复访问 `/models` | 增加固定网络延迟、配额/限流触发面，并可能让同一任务五个角色得到不一致 availability |
| 一个分支 prompt 过长导致整个 Provider 熔断 120 秒 | “当前请求不可重试”和“账号/端点全局不可用”共用 `_open_circuit`；任意 HTTP 400 都污染共享 circuit state | 单个 request-scoped 输入错误让后续无关主题、父边和视觉调用直接失败，形成长任务级联降级 |
| 无上限信任 `Retry-After` | Provider 可返回极大秒数或远未来 HTTP-date，worker 原样 sleep | 单次 429 可把一个任务冻结数小时，放大队列长尾且难以取消定位 |

这些问题分别属于持久化一致性、取消语义、身份/provenance、求解器等价性、复核派生状态、视觉 occurrence、视觉告警/发布状态协议、凭据传递、路由、上传资源治理、文件权限和可观测性。它们即使在完整 C+ 语义算法上也会独立发生，因此不能以“架构尚未完整”为理由延后。

#### 14.3.2 复核契约的 TDD 收口

二次审计继续从“review type -> subject -> action -> 新图 -> DecisionRecord”逐步回放，并已将以下契约从 RED 收口为 GREEN：

| 复核契约 | 已证明的旧失败路径 | 当前硬门 | 当前状态 |
| --- | --- | --- | --- |
| review type/action 矩阵 | 不同 subject 共用一组动作，cross-link 也可能看到节点 delete/change-parent | 后端 `_ALLOWED_REVIEW_ACTIONS` 和前端 `reviewActionsForType` 使用同一矩阵；非法组合在事务前拒绝 | 已实现并有前后端镜像测试 |
| rename 规范化同名冲突 | rename 到同分支已有名称的空白/大小写等规范化变体，制造重复节点 | 同分支 `normalized_key` 冲突原子拒绝；图版本、review 状态和节点名均不变 | 已实现 |
| cross-link delete 的 subject 路由 | cross-link review 的 delete 误入 node delete，把 source node 删除 | cross-link 当前只允许 keep；delete 在任何图变更前拒绝，不触发节点删除/重连 | 已实现保护；跨链显式 reject 动作仍未提供 |
| 无关系 evidence 的 keep | 人工 keep 仅凭动作把空 evidence 的 provisional edge 认证为 direct parent | 当前父边必须唯一且 evidence 非空，否则 review 保持 pending、图版本不变 | 已实现 |
| change_parent 候选资格与证据 | 任意现存 parent 可被赋满分 direct edge，候选 relation evidence 丢失 | 新 parent 必须来自 review alternatives、classification=`direct_parent` 且 evidence 非空；新 edge 继承候选 score/evidence | 已实现 |
| 父边复核 DecisionRecord subject | keep/change-parent 记录指向 parent/node ID，无法回放最终选中的边 | `subject_type=tree_edge` 且 `subject_id` 为复核后真实 edge ID | 已实现 |
| review 后 node status/risk 派生量 | 卡片 resolved 后节点仍保持旧 `needs_review/risk_score` | 从全部剩余 pending reviews 重算 node status/risk，再与质量报告、版本和 decision 同事务提交 | 已实现 |

这些条目与 CAS、显式 subject、非法残片 rename 和质量指标重算共同形成完整事务边界：动作必须先适用于该 review type，再定位正确 subject，再验证关系证据，最后重算所有派生状态。当前仍缺 merge/split/recrop/跨链显式 reject/真正切根/局部子树重跑等设计动作。

#### 14.3.3 当前代码审计锚点

第 5 节的行号属于 2026-07-23 历史快照。当前工作树应按函数入口核验；以下行号是 2026-07-24 本次复核时的快照，后续并行补丁若插入代码，以函数名为准：

| 链路 | 当前实现入口 |
| --- | --- |
| PDF/PPT 解析与 chunk 边界 | `backend/app/document_parser.py:31` `_reflow_pdf_text`；`:178` `parse_document`；`backend/app/chunking.py:46` `chunk_document` |
| 标签、evidence 和 coverage | `backend/app/mindmap_engine/normalize.py:155` `is_publishable_label`；`backend/app/agents.py:328` `_evidence_matches_unit`；`:2075` `coverage_statistics` |
| Branch、父边与 verifier | `backend/app/agents.py:512` `build_branch_plans`；`:1858` `verify_parent_candidates`；`backend/app/cplus_pipeline.py:346` `verifier_degraded_components` |
| 最终 ledger、质量门与 solver | `backend/app/cplus_pipeline.py:432` `_enrich_result`；`backend/app/mindmap_engine/topology.py:633` `solve_topology` |
| 人工复核 | `backend/app/review_service.py:164` `_replace_quality`；`:458` `resolve_review_item` |
| 前端复核动作 | `frontend/src/reviewActions.ts` `reviewActionsForType`；`frontend/src/reviewActions.test.mjs` |
| Provider 与 model-call 追踪 | `backend/app/model_provider.py:448` `OpenAICompatibleClient._request`；同文件 `ModelCallContext/model_call_scope` |
| job/run 恢复 | `backend/app/main.py:200` `_execute_job`；`:346` `recover_jobs`；`backend/app/blackboard.py:230` `upsert_job` |
| 视觉、资产和上传 | `backend/app/visual_analysis.py:280` `analyze_visual_pages`；`backend/app/cplus_pipeline.py:217` `_render_warning_degraded_components`；`backend/app/mindmap_engine/router.py:91` `require_asset_token`；`backend/app/mindmap_engine/visuals.py:129` `_asset_url`；`backend/app/upload_validation.py:53/171` |
| 布局与 PNG | `backend/app/mindmap_layout.py:212` `compute_mindmap_layout`；`backend/app/export_service.py:88` `build_mindmap_layout` |
| secret 启动前检查 | `backend/app/secret_preflight.py:20` `validate_secret_file` |

### 14.4 30 分钟瓶颈的算法变化

旧算法的主要调用规模近似为：

```text
branch_calls ~= leaf_branch_count
verify_calls ~= Σ_child TopK(child)
precision_calls ~= first_votes + second_votes + per-edge arbiters
```

在历史 `8db...` 中，这条路径理论上达到约 1709 次父边校验/仲裁调用。

新算法改变为：

```text
leaf_branch_count <= 24
first_verify_http_calls <= ceil(number_of_children_with_competition / 4)
second_verify_http_calls <= ceil(high_risk_children / 4)
arbiter_http_calls <= ceil(disputed_high_risk_children / 4)
```

因此：

- standard 的 Top-3 路径先由“每 candidate 一次”收敛为“每 child 一个逻辑
  比较单元”，当前又把最多 4 个 child 合成一次物理 HTTP。8 个 child 的
  TDD 固定为 2 个 batch，而不是 8 个请求。
- precision 的首轮、二审、仲裁分别按相同的 4-child 上限批量，角色间不混批；
  任一返回缺 child、未知 parent 或坏 schema 时，只对该 child 走 fallback，
  其他 child 的模型票继续有效。该上界减少物理 HTTP 数，不代表远端每批
  latency 会线性下降。
- 对历史 `8db...` 这类 60 个 leaf 的过度切分夹具，当前硬预算把 leaf 上界压到 24，因此该夹具的分支抽取调用上界理论上至少降低 60%；不能外推为所有文档耗时都降低 60%。
- 共享 Client 避免每个逻辑请求都重新构造连接池；Provider 和 job semaphore 将并发限制在配置上界，避免历史中每个任务各自叠加 4×/8× 的无界放大。它们约束并发和连接重用，不代表网络竞争、TLS 重连或 Provider 排队已经消失。
- precision 的 generator/verifier/vision/second/arbiter 现在共享一次模型可用性预检，固定 `/models` 调用从 5 次降为 1 次；这减少启动延迟和限流触发面，但不是历史 30 分钟的主瓶颈。
- 普通 400（例如单个 prompt 过长）不重试当前请求，但不会再阻断后续无关调用；只有 401/402/403 或鉴权、余额、配额类账号级错误打开共享熔断。这样避免一个 branch 的输入错误扩散成全任务 120 秒降级。
- `Retry-After` 和指数退避现在同时受配置上限与 300 秒硬上限约束，避免一次 429 把 worker 挂起数小时；该上限仍需结合真实配额策略调优。
- PDF/PPTX 视觉页预算在 raster 前执行，长文档不会为了最终只分析少量页而先生成全部页面图片；预算跳页和部分分析失败会明确 degraded，不再以“更快但静默不完整”换取 publish。

这些是代码级调用上界和资源竞争模型的变化，不是新 Qwen-only 生产 SLA。
当前已有一次 92 页 precision 公网运行，但它运行在最新性能补丁之前，并在
`branches / 42%` 被取消，没有完成态 graph version；它只能证明旧 per-call
重试策略的长尾，不能证明最新候选耗时。真实 P50/P95 仍必须在保留源文件、
固定 `qwen3.8-max-preview`、固定并发配置并跑到终态后重新统计，不能仅凭
161/161 或一次取消任务宣称已经降到某个确定分钟数。

### 14.5 布局修复的历史回放

对旧保存图版本使用 Python 布局/导出实现做本地回放：

| 任务 | 节点 | 根分支右/左 | 新 AABB 碰撞 | 逻辑画布 | 安全 raster |
| --- | ---: | ---: | ---: | ---: | ---: |
| `8db068a6c04a` | 336 | 21 / 14 | 0 | 3241×14686 | 1808×8192 |
| `749e4e76fb55` | 311 | 7 / 7 | 0 | 2440×12436 | 1608×8192 |

`8db...` 的一次本地回放中，新 PNG 约 2.40 秒、峰值 RSS 约 205 MB、文件约 439 KB。旧算法为 295 对碰撞、`11087×9709`、约 1.076 亿像素。这证明 PNG 重叠是可独立修复的布局算法问题，不依赖先完成全部语义架构。

这组数字不是浏览器 E2E、并发导出 P95 或生产容器 SLA，也不会修正旧图节点本身的语义。Python 与 TypeScript 当前分别实现同一 right-first 合同，但文字测量、字体和坐标尚未由一个服务端持久化 `LayoutResult` 统一下发，因此不能把“Python 回放零碰撞”扩大为“所有浏览器/字体/导出坐标完全一致”。

### 14.6 当前仍未完全实现的设计能力

本轮显著收紧了 C+ 的硬门，但仍不能宣称与设计文档“完全一致”：

1. **Content Unit 仍不是完整原子 claim 层**：已禁止普通文本跨页并改善 provenance，但 text unit 仍以同页 chunk 为主，尚未系统拆成 definition/formula/step/example，也没有给每个 claim 建立精确字符 span。
2. **PPTX 对象级 provenance 未完成**：当前基础阅读顺序优先 title 后按 top/left，但 placeholder、group/SmartArt、chart 数据、notes、hidden 状态、公式和对象 bbox/父组仍未形成可审计的统一对象模型。
3. **OCR/公式/layout adapter 只完成已知模式，不是通用公式解析器**：
   当前会对数学 PUA 页触发 Poppler 比较，并恢复本样本中的
   `λ/ν/×/≈/⇒`、相对线宽、负指数和驻波分式；但扫描 PDF、任意字体映射、
   复杂公式、双栏和表格仍缺专用 OCR/版面/公式 AST 与置信度。
4. **Branch Planner 不是设计中的真正递归团队**：当前先建最多 8 个一级 plan，再做一次确定性均衡切组，实际只产生一层 child branch；`max_depth` 合同没有对应的多轮“重新评估内聚度后递归/停止”执行。
5. **Embedding + reranker 未落地**：父池已从 O(N²) concept 扫描收敛为 root/branch/structural 受限池，但所谓 Top-k 仍不是向量召回和真实 reranker。
6. **Abstraction induction 和跨 branch reassignment 仍未完整**：当前已有
   provenance-grounded、公式感知、complete-link 的确定性 semantic dedupe，
   能处理已知跨模态/跨页重复并保护冲突 claim；但尚未实现完整
   “高内聚 child cluster -> 抽象父 -> too broad/narrow/mixed 审计”，也没有
   embedding/reranker 驱动的跨 branch merge/reassignment。
7. **正式父边 evidence 仍不是关系蕴含证明**：concept-to-concept 要求显式 relation evidence，但 root/topic/structural 边可由共享 unit 生成 support mapping；它证明父子节点引用了同一材料，不证明原文蕴含“该 parent 是该 child 的直接上位概念”。
8. **独立模型家族未实现**：生成、校验、二审和仲裁当前仍可由同一 Qwen 家族承担；逻辑角色、不同 prompt 和两轮调用不等于统计独立校验。
9. **跨链时序仍早于主树冻结**：cross-link 候选在 Branch 抽取/merge 阶段产生，再随图一起 normalize/solve；尚未在主树冻结后进行独立的跨链召回、祖先冗余过滤和方向校验。
10. **Provider 仍缺结构修复重试和备用 Provider**：已有网络级重试、bounded `Retry-After`、分层熔断、attempt 追踪，以及 verifier partial/failed 结构化降级，但 schema/JSON 局部修复、结构化重试、备用模型/Provider 与语义结果缓存尚未实现。
11. **checkpoint 是可读审计点，不是 stage 精确续跑**：服务重启后从保留源文件重新排队并复用 run；尚未按 stage input hash 跳过已提交模型调用，也没有 LangGraph checkpointer/interrupt 级恢复。
12. **HITL 动作仍有限**：action matrix、同名 rename、父边 evidence、真实 edge DecisionRecord 和 node risk/status 已闭环，但当前仍只有 keep/delete/change_parent/rename/accept_root 的受限集合；缺 merge、split、recrop、真正切换根、局部子树重跑、cross-link 显式 reject 和可恢复 interrupt。
13. **CP-SAT 主要求合法受限树，不是语义全局最优**：节点/深度/fanout/单父、activation margin 和 optional abstraction 最少两个 child 已在 CP-SAT/greedy 间收敛，但完整的关系蕴含、抽象质量、章节连续性、跨簇惩罚和人工偏好尚未进入可校准的全局软目标。
14. **视觉状态机仍不完整**：decompose 目前是“全页父资产 -> 单个区域 crop”，不是“复合区域 -> 多个子 region”的 schema；跨页 occurrence 和 budget/partial degraded 已闭环，但整页 render/VLM 失败因没有 bbox/claim 仍无法落成逐项 unit；NMS 抑制项及同页 pHash 抑制项也没有独立 rejected unit；业务若要求逐页视觉召回，仍需突破 page budget 做分批全量处理。
15. **`model_calls` 仍缺成本与可复现实验键**：run/stage/branch/input units、attempt、latency、status、error 已记录，但 token、费用、prompt/schema hash、完整 response hash 与结果缓存仍待实现。
16. **源文件 retention 仍缺生产治理**：已有重排所需的保留和显式删除，但应用层加密、租户配额、GC、删除审计和保留周期尚未闭环。
17. **转换器仍在应用容器内**：Compose 配置为非 root、read-only 并限制 CPU/内存/PID/capability，但 LibreOffice/pdftoppm 尚未拆到更强隔离的 worker。
18. **布局还不是单一持久化结果**：Python 与 TypeScript 共享算法合同而非同一份坐标；字体/文字测量仍可能不同，服务端没有 versioned `LayoutResult` JSON、SVG、缓存和浏览器坐标一致性回归。
19. **浏览器端到端与业务准确率仍未验证**：第一版 TDD 公网容器已通过非 root、read-only、鉴权、资产和健康检查，并执行过一次未完成的 92 页 PDF 任务；但最新候选仍没有完成浏览器/移动端、真实下载、进程强杀重启和完整第二次重跑 E2E。当前也没有真实源 PPTX、节点多解标注和直接父边人工金标，因此不能给出节点精确率、父边准确率或祖先 F1。

这些剩余项分别属于语义能力、可恢复性、评测和生产隔离，不能反向否定本轮已经独立修复的文字截断路径、调用规模、复核事务、资产凭据和布局碰撞；反过来，本轮工程硬门通过也不能被包装为上述语义能力或业务准确率已经完成。

### 14.7 TDD 和回归证据

最终验收矩阵使用以下命令：

```text
.venv/bin/python -m unittest discover -s backend/tests -v
cd frontend && pnpm test
cd frontend && pnpm build
git diff --check
.venv/bin/python -m compileall -q backend/app backend/tests
MINDMAP_API_TOKEN=... EXTERNAL_ENGINE_TOKEN=... ASSET_ACCESS_TOKEN=... \
  docker compose -f compose.prod.yml config --quiet
docker build --build-arg GIT_SHA="$(git rev-parse HEAD)-dirty" \
  -t zlb-mindmap-agent:tdd .
```

截至 2026-07-24，历史工程根因的大部分 TDD 已收口，长文档性能和 PDF 输入
专项也已加入完整回归；但真实第 30 页刚暴露的新分类 RED 仍在另线修复。
因此这里的 GREEN 表示已被现有测试覆盖的合同，不表示所有真实输入组合均已
覆盖，也不表示第二次课件重跑、业务精度或生产耗时 SLA 已达成：

| 验收项 | 当前证据 | 结论 |
| --- | --- | --- |
| 后端完整套件 | `.venv/bin/python -m unittest discover -s backend/tests -v` 得到 `Ran 161 tests`、`OK` | 161/161 GREEN |
| 长文档性能专项 | `backend/tests/test_long_document_performance_tdd.py` 覆盖 136 planning units、分层抽样、token 预算和 per-call retry | 8/8 GREEN；证明调用/容量合同，不是生产分钟数 |
| PDF 输入专项 | `backend/tests/test_pdf_input_quality_tdd.py` 覆盖 layout 提取、低质页回退、warning/metadata、章节 heading、垃圾 unit 和合法短公式/题目 | 8/8 GREEN；真实第 30 页混合噪声尚未被原夹具覆盖 |
| 前端单元测试 | `pnpm test` 覆盖任务生命周期、质量状态和 review action contract | 7/7 GREEN |
| 损坏文件错误语义 | 损坏 PDF 夹具会由底层解析器打印一次 `EOF marker not found`，对应请求仍按测试预期返回 422，套件通过 | 非测试失败；后续可收敛底层日志噪声 |
| 前端 production build | `pnpm build` 成功；Vite 报告 `699.34 kB` chunk size warning | GREEN；这是非阻断体积告警，不是构建失败或浏览器性能结论 |
| 静态与 Compose 配置 | `git diff --check`、`compileall`、`docker compose -f compose.prod.yml config --quiet` 全部成功 | GREEN |
| 公网第一版 TDD 镜像 | `sha256:19a51fb5530d32e48046591fdc0d6a49e0ef5145b9e7f4fd2128e48678102868`；非 root/read-only/auth/asset/health 通过，7 条旧历史可见，宿主只公开 5173 | 已部署并健康；早于最新性能/PDF 补丁 |
| 当前候选 runtime | 仅绑定 `127.0.0.1:18081`；具备 `pdftotext` 并已用真实 PDF 做解析白盒 | 尚未切换公网；第 30 页新 RED 修复和重建前不得晋级 |
| 浏览器/移动端/进程重启 E2E | 没有新证据 | 未验证 |
| 第一次 92 页 Qwen-only 运行 | task `1f5cf23f834a` / run `run_34d43d8339d249cf`，25 分 51.699 秒后取消，停在 `branches / 42%`，无 graph version | 已形成性能/可观测性证据；不是成功基准 |
| 第二次 92 页运行与业务金标 | 最新候选尚未完成同源重跑；没有人工多解标注 | 不得给出新完成分钟数或准确率 |
| 公网传输 | 当前入口为明文 HTTP，因此显式设置 `MINDMAP_SESSION_COOKIE_SECURE=false` | 功能可用但不是 TLS 终态；接入 HTTPS 后必须恢复 secure cookie |

### 14.8 新的止损结论

在当前 TDD 工作树和已覆盖的自动化路径中，以下工程性绕过已被硬门阻止：

- 把已覆盖夹具中的首尾虚词、上下文 marker、纯页码或未闭合标签作为正式节点；混合 PUA+轴+公式的第 30 页例外见 15.5；
- 用 branch/root 的 aggregate support 冒充 explicit claim coverage；
- 只用合法 unit ID 搭配不属于该 unit 的伪造 excerpt 冒充 weighted content coverage；
- 让求解已拒绝的候选继续把 ContentUnit 留在 covered 状态；
- 用一条高分父边补偿 optional 节点的零/负 activation margin；
- 在 greedy fallback 中保留只有一个 child 的 optional 抽象父；
- 把同一 unit 在 support/evidence 两个字段重复计成两条抽象支持；
- 用 sibling、ancestor、unrelated 或空 evidence 边作为正式 direct parent；
- 在 review alternative 丢失关系 evidence 后伪造 change-parent 正式边；
- 让 verifier 真实调用 partial/all fallback 只留 warning 而不进入 degraded；
- 把 fallback、pending review、degraded stage 或超 150 节点结果标为可发布；
- 保留同分支规范化同名节点而不计入 conflict；
- 删除中间节点后伪造满分 direct edge；
- 让前端向 cross-link review 提交后端不允许的节点变更动作；
- 用完整 360° 径向分配和超大 raster 掩盖布局冲突；
- 在视觉预算生效前 raster 全文，或把预算跳页/部分失败包装成完整视觉分析；
- 因正常 pHash 同页去重或跨页复用提示关闭 publish，或把 render budget、render failure、native extraction 混成不可区分的单一视觉失败；
- 在 Provider 永久错误后继续进行数百次无意义请求；
- 无上限执行 Provider 给出的 `Retry-After`；
- 在生产 token 缺失时开放历史、导出、复核或删除接口；
- 把长期资产 token 写入 URL query，或用 query token 读取资产；
- 让禁用的 production docs 路径掉入 SPA 返回 200；
- 让 shutdown 取消把可恢复任务永久写成 cancelled；
- 在不重算冲突、coverage 和 publish gate 的情况下提交人工复核；
- 未通过 UID/GID/mode preflight 就启动读取 age secret 的非 root 服务。

这里的“evidence 硬门”仍只是工程发布资格：结构边的 support mapping 可审计但不证明直接父子语义正确。相同地，right-first 的 Python 回放零碰撞不等于所有浏览器字体已经 E2E 一致；161/161、性能 8/8、PDF 输入 8/8、前端 7/7 和第一版公网隔离验收，也不等于最新候选已经公网切换、第二次重跑已经完成或真实业务 SLA 已经达标。

因此，第 2～5 项现在分别由性能预算、标签/证据门、布局不变量和 publish gate 独立约束；它们不再被笼统归结为“第 1 项架构没有完全实现”。更准确的当前状态是：第 2、4 项已有针对其直接工程根因的 TDD 修复；第 3 项的大多数历史路径已加硬门，但真实第 30 页又发现一个独立条件顺序 Bug，仍需完成 TDD；第 5 项已阻断若干明显错误发布路径但业务准确率仍待真实 PDF 完成态重跑、源 PPTX 与人工金标验证。第 1 项剩余差距继续保留在 14.6 节，作为下一阶段语义能力和评测工作，而不是其余问题的免责理由。

## 15. 第一次公网重跑后的代码/算法级再归因

### 15.1 运行基线和证据边界

本节状态截点是 **2026-07-24 第一次公网重跑已取消、最新候选尚未替换
公网、第二次重跑尚未开始**。不能把本地候选、当前公网和未来第二次结果混写：

| 对象 | 已核验事实 |
| --- | --- |
| 公网服务 | `http://175.178.196.235:5173/`，第一版 TDD 镜像 `sha256:19a51fb5530d32e48046591fdc0d6a49e0ef5145b9e7f4fd2128e48678102868` |
| 公网隔离 | 非 root `10001:10001`、read-only rootfs、`cap-drop ALL`、`no-new-privileges`、3 GiB 内存、2 CPU、256 PIDs；宿主只公开 5173 |
| 传输边界 | 入口仍是明文 HTTP，所以当前显式使用 `MINDMAP_SESSION_COOKIE_SECURE=false`；这不是 TLS 终态 |
| 测试包 | 10 个 PDF、639 页，没有 `.pptx` |
| 主样本 | `精细1-量子物理原子中的电子.pdf`，92 页，SHA-256 `a36cf7a439a5d06fe9830e5fa6219836ecc63326ed53903a323bdd4078db54f9` |
| 固定重跑参数 | `provider=qwen`、`model=qwen3.8-max-preview`、`mode=precision`、`use_ai=true` |
| 当前候选 | 最新性能/PDF 工作树仅在本机候选端口验收；尚未替换公网，也尚未给出第二次重跑结果 |

上传包没有 PPTX 是一个必须明确的事实：本轮可以对 92 页 PDF 的原文、页码、
公式和图示做逐页核验，但不能把它表述成对 PowerPoint 对象层的验收。

### 15.2 第一次公网重跑的完整现场

第一次公网任务和运行记录为：

| 字段 | 值 |
| --- | --- |
| task ID | `1f5cf23f834a` |
| run ID | `run_34d43d8339d249cf` |
| 开始时间 | 2026-07-24 17:32:35.605，北京时间 |
| 取消时间 | 2026-07-24 17:58:27.304，北京时间 |
| wall time | 25 分 51.699 秒 |
| 取消时状态 | `branches / 42%` |
| 最终持久化状态 | job 和 run 均为 `cancelled` |
| graph version | 无；finalize 从未执行 |

阶段耗时恰好解释了整个 wall time：

| 阶段 | 耗时 | 现场解释 |
| --- | ---: | --- |
| parse | 1.690 秒 | 不是性能瓶颈 |
| ledger | 118.669 秒 | 文本/视觉账本和模型调用有实际成本，但远小于后续超时 |
| themes | 541.780 秒 | 三次请求均约 180 秒超时，固定损失约 9 分钟 |
| branch_plan | 0.018 秒 | 确定性规划本身几乎无耗时 |
| branches | 889.542 秒 | 取消前约 14 分 49.5 秒仍未完成整批 Branch Team |

`model_calls` 共记录 47 个 HTTP attempt：

- 30 个成功：`model_check` 1 个、`ledger` 24 个、`branches` 5 个。
- 17 个 `retryable_error`：`themes` 3 个、`branches` 14 个，均为 timeout。
- 以每个 logical call 的首个 attempt 为基准，实际发生 10 个 retry attempt。
- themes 的一个逻辑请求完整执行三次约 180 秒 attempt（首轮 + 两次重试）后
  才进入确定性 fallback。
- Branch 现场中，首批四个大请求各自执行三次完整约 180 秒 attempt
  （首轮 + 两次重试），单个逻辑请求可占约 540 秒；较小 Branch 请求可在
  约 56～163 秒成功。因此证据支持
  “请求粒度/预算/超时策略不匹配”，不支持“Provider 完全不可用”。

容器峰值内存约 324.2 MiB / 3 GiB，没有 OOM、容器重启或 cgroup 终止。
因此第一次任务慢的主因是远端模型请求和本地请求编排，不是宿主 CPU/内存
耗尽。取消后原件仍保留，但因为 Branch 结果没有增量提交，已成功的 5 个
Branch 模型调用没有形成可恢复的 `branches` checkpoint，也没有最终图。

### 15.3 性能故障的代码级因果链

第一次公网镜像中的故障不是一个“Qwen 慢”结论，而是以下可定位的算法与
状态机组合：

#### 15.3.1 Theme 抽样先发生语义欠覆盖

当次有 136 个 planning units：92 个 text、44 个 visual。第一版实现按
`importance` 全局降序后直接取前 80 个，实际样本为 36 text + 44 visual：

```text
136 planning units
  -> importance 全局 Top-80
  -> 44 个高 importance visual 全部进入
  -> text 只剩 36 个
  -> 56/92 个 text 未进入 Theme prompt
```

旧 prompt 又没有 `page` / `slide` 字段，模型不能显式判断章节连续性、文档尾部
和视觉/文本是否来自同一位置。即使这次 Theme 调用成功，它得到的也不是稳定的
92 页文本主脊。这是子节点准确性和 overflow 污染的前置直接根因，不是单纯的
延迟问题。

#### 15.3.2 有确定性 fallback，却继承全局 `3×180s`

`synthesize_themes()` 和 `_branch_scout()` 都有确定性 fallback；但第一版
`OpenAICompatibleClient.complete_json()` 没有 per-call attempt/stage budget，
两者自动继承 Provider 全局 `max_attempts=3` 与 180 秒 timeout。结果是：

```text
一个可降级逻辑请求
  -> timeout 180s
  -> 整个 prompt 从头重发
  -> timeout 180s
  -> 再次整请求重发
  -> timeout 180s
  -> 约 540s 后才执行本来就存在的 fallback
```

这不是重试“可靠性增强”，而是在已知有低成本 fallback 的阶段反复支付同一个
大请求的最坏时间。网络 retry、JSON/schema repair 和业务 fallback 应是三种
不同策略，不能共用一个全局 attempt 数。

#### 15.3.3 Coverage overflow 被塞进最后一个主题，造成语义污染

Theme fallback 只按 text heading/首行聚类；视觉 unit 和未被主题认领的内容会
进入 `unclaimed`。`build_branch_plans()` 在一级分支达到 8 个后，又把低排名
topic 和全部 unclaimed units 合并进最后一个保留 plan。现场形状为前 8 个主题
先覆盖 72 个 units，剩余 64 个 overflow/unclaimed units 被塞入最后一个只有
8 个 units 的主题，形成一个 72-unit 混合 Branch。

即使代码把标签改成“扩展主题”，它也没有重新计算：

- 64 个 overflow 与原最后主题的语义内聚度；
- 文本和视觉是否属于相同章节；
- 是否应该拆成多个新的一级主题；
- 原主题名是否还可作为这一大组的父概念。

因此这是 **coverage 形式完整、主题语义被污染**。它会让后续模型在一个
Branch prompt 中同时处理互不相关章节，直接降低节点总结和父边质量。

#### 15.3.4 Leaf cap 的计算把“每叶最多 8”降成了软建议

第一版 planner 先把全局 24 个 leaf 按 8 个 root 平均，得到
`per_root_leaf_cap=3`，再执行近似：

```text
desired_count =
  min(per_root_leaf_cap,
      ceil(unit_count / max_units_per_leaf),
      coverage_budget // 3)
```

对上面的 72-unit Branch，`ceil(72/8)=9`，但 `per_root_leaf_cap=3` 把结果
压成 3 个 leaf，于是每个 leaf 变成 24 units。参数名虽然叫
`max_units_per_leaf=8`，实际没有后置不变量检查。这就是接口语义和算法行为
不一致：为了满足全局数量上限，代码静默违反了单请求输入上限。

#### 15.3.5 固定 7000 输出预算把超大叶送入慢路径

Theme 无论预期输出多少都使用 `max_tokens=5000`，Branch 无论 2 units 还是
24 units 都使用 `max_tokens=7000`。输出上限不是实际输出长度，但会影响
Provider 的调度、生成上限和超时风险；再叠加 24-unit 输入和完整 JSON schema，
首批大 Branch 反复命中 180 秒 timeout。小 Branch 能成功，进一步证明需要按
预期记录数缩放 token budget，并在请求过大时先拆分，而不是把 timeout 当作
唯一背压。

#### 15.3.6 Branch 是 all-or-nothing checkpoint

`branch_team_node()` 调用 `run_branch_teams()`，后者用 `asyncio.gather()` 等待
所有 leaf；只有 gather 全部返回后才：

1. 汇总 `used_count`；
2. 计算 `branch_extraction_model` degraded；
3. 写 `branches` checkpoint；
4. 把进度推进到下一阶段。

因此一个 Branch 成功不会形成独立 checkpoint。最后一个慢请求或用户取消会
让整批未提交，无法从已完成 leaf 继续。这是任务恢复和 30 分钟体验的独立
根因，即使完整实现 C+ 的语义算法也仍会发生。

#### 15.3.7 固定 42% 和 degraded 延迟是两个可观测性 Bug

Branch 阶段只在入口调用一次：

```text
progress("branches", 42, "正在并行运行分支团队")
```

没有 `completed_leaves / total_leaves`、当前重试 attempt、已 fallback 数或阶段
deadline，所以任务近 15 分钟始终显示 42%。这不是“前端轮询失败”，而是后端
没有产生更细状态。

Theme 失败后，`global_theme_model` 只加入 LangGraph 内存 state；Branch 部分
失败的 degraded 又要等 gather 完成后才计算。`runs.degraded_components_json`
主要在 finalize 时由最终 result 写入。第一次任务在 Branch 取消，所以即使
Theme 已经三次超时并 fallback，run 的 degraded 列表仍为空。这会让运维把
“已降级且重试中”误看成“只是正常处理中”。

### 15.4 当前性能 TDD 已证明什么，仍缺什么

`backend/tests/test_long_document_performance_tdd.py` 当前 8/8 GREEN，已经把
第一次现场转成以下 provider-free 合同：

- 136 planning units 在叶层恰好覆盖一次，无遗漏、无重复；
- leaf 总数不超过 24，每 leaf 不超过 8 units；
- 193 units 在 `24×8` 容量下数学上不可满足时显式报错，不再静默突破上限；
- Theme 样本最多 80，其中 text 至少 56、visual 最多 24，并覆盖所有章节和
  文档尾部；
- Theme prompt 明确包含 `page` / `slide`；
- Theme/Branch token 随预期输出规模增长，并分别受 5000/7000 硬上限约束；
- `complete_json()` 支持 per-call attempt 控制；
- 有确定性 fallback 的 Theme/Branch 使用单次 attempt，不再继承 `3×180s`。

这些 GREEN 消除了第一次现场中最确定的容量和重试放大器，但不能过度声明：

1. overflow 当前仍会进入一个显式“扩展主题”，容量正确不等于语义内聚；
2. Branch 仍是整批 gather 后 checkpoint，没有 leaf 级增量恢复；
3. job 进度仍没有 leaf 完成数、重试/降级明细；
4. run degraded 仍未在每个阶段失败时立即持久化；
5. 单次 attempt 只消除重复 540 秒，不保证单个 180 秒请求本身足够快；
6. 没有第二次完整公网运行，不能从 8/8 推导真实完成分钟数。

### 15.5 PDF 静默漏字和第 30 页误判的代码级根因

#### 15.5.1 解析速度不是问题，文本保真度才是

对 92 页主样本做只读逐页对照：

- pypdf 文本总量约为 Poppler 的 74.9%；
- 29 页的 pypdf 文本量低于对应 Poppler 页的 70%；
- 36 页包含 U+Fxxx 私用区字符；
- 89/92 页仍保留纯页码；
- 解析本身约 1.35 秒，和第一次公网 parse 1.690 秒一致，不是长耗时主因。

“抽得很快”不能替代“抽得完整”。字符仍然像正常 Unicode 时，pypdf 的漏字
不会自动触发异常；后续模型只能总结已经丢失的文本，任何 prompt 都无法恢复
未进入 Content Unit 的知识。

#### 15.5.2 当前混合解析的有效改进

PDF 输入专项 8/8 已实现：

- pypdf 优先使用 layout 模式；
- 只有明确低质页才逐页调用固定参数的 `pdftotext -layout`；
- 工具缺失、超时或失败时保留 pypdf，并记录结构化 warning/metadata；
- 从 PDF 首行保守识别 `第N章`、`§N.M`，不把普通编号正文误当章节；
- 纯页码和省略号 reject，明显 PUA/轴/UI 残片 defer；
- 合法短公式、定义和完整选择题继续保持 eligible。

真实样本中，候选容器确认第 26 页被 reject；第 30 页实际执行并采用了
`pdftotext` fallback。这证明 Docker 运行时确实具备 Poppler，而不是只在 mock
测试里声称有 fallback。

#### 15.5.3 第 30 页为什么仍被标成 `uncovered`

第 30 页 fallback 文本同时包含 PUA 字符、`z/y` 坐标轴碎片和残缺球谐公式，
但其中也有等号。当前判别链近似为：

```text
_text_unit_disposition(text)
  -> _is_private_use_glyph_noise()
       仅在 PUA 数量和占比超过阈值时命中
  -> _is_meaningful_short_formula()
       只要关系符两侧各有字母/数字/中日韩字符即可为真
  -> 立即返回 uncovered
  -> axis/symbol fragment 检查不再有机会 defer
```

而 `_is_axis_or_symbol_text_fragment()` 自身也先调用“合法短公式”保护，所以
这个含等号的混合垃圾文本会再次绕过 axis 门。根因不是“公式一定无法解析”，
而是 **局部合法 token 被用来豁免整段混合输入**：

- 没有先计算 PUA、轴 token、残缺括号/公式和可读自然语言的组合风险；
- 公式合法性只检查等号两侧“存在字符”，不检查公式结构完整度；
- 没有把“含一个可能合法公式”与“整页可以作为文本知识 unit”分开；
- fallback 被采用时只记录 `used_pages`，不会因为内容仍有混合风险自动 degraded。

正确策略应是先做组合风险判别，再做窄范围公式保留：合法公式可单独抽成
formula span；其余 PUA/坐标轴残片应 reject/defer，不能因一个等号把整页设为
`uncovered`。对应真实第 30 页必须成为固定回归夹具，同时继续保护
`E = hν`、`∫ψ*ψ dτ = 1`、玻尔半径定义等合法短公式。

#### 15.5.4 Parse warning 当前不会阻止发布

`parse_node()` 只是把 `document.warnings` 追加到结果 warnings。C+ 当前只把
特定 `[visual_degraded:*]` 机器码映射为 degraded component，没有把
`[pdf_parse_degraded:*]` 映射到 publish gate。因此：

```text
pdftotext unavailable / failed / low-quality retained
  -> 用户最终可能看到 warning
  -> runs.degraded_components_json 不一定含 pdf_parse
  -> publish gate 不会仅因关键页解析不完整而关闭
```

这是 warning、运行状态和发布资格协议不一致。下一步应至少区分：

- fallback 成功且输出通过质量门：可继续，不降级；
- 非关键页低置信但视觉证据已覆盖：显式 deferred，可按策略继续；
- 关键页两种 extractor 均低质、工具缺失或解析失败：写稳定
  `pdf_text_extraction` degraded component，并阻止 publish；
- warning 必须带页码、extractor、状态和后续处置，不能只留自然语言。

### 15.6 第 2～5 项的独立直接根因矩阵

下面的边界是本报告最终归因，不允许用“C+ 尚未完整”替代：

| 用户问题 | 独立直接根因 | C+ 未完整如何放大 | 不能归因给 C+ 的部分 |
| --- | --- | --- | --- |
| 2. 约 30 分钟 | 大 Theme/Branch prompt、固定 5000/7000 token、全局 `3×180s`、24-unit 叶、all-or-nothing checkpoint、固定 42% | 真正语义分支和缓存可进一步减少调用 | timeout/retry policy、进度、checkpoint、资源与 Provider 调度是普通分布式系统问题 |
| 3. 截断/垃圾摘点 | pypdf 漏字、PUA/轴/公式条件顺序、fallback 质量判定、parse warning 不阻断、历史标签正则 | 原子 span/OCR/公式 adapter 可提高保真度 | 第 30 页“等号豁免整段垃圾”是确定性分类 Bug |
| 4. PNG 重叠 | 旧 360° 径向布局没有真实框尺寸、子树 extent、碰撞检查和 raster 预算 | 节点爆炸会加重拥挤 | 任意合法密集树都可触发；right-first/AABB 可独立修复 |
| 5. 子节点准确性差 | Theme 欠覆盖、overflow 混入错误主题、粗 unit、fallback、父边证据不足、假 coverage、无人工金标 | 原子 Content Unit、abstraction、embedding/reranker、独立校验是核心能力 | 解析漏字、错误 unit disposition、失败发布语义和评测缺失仍是独立实现/流程问题 |

换言之，第 1 项解释“为什么系统离目标架构还有差距”，但第 2～5 项各自都有
可以单测、复现和修复的直接因果链。即使明天完整实现 C+ 阶段名，如果仍保留
三次 180 秒整请求重试、等号豁免混合噪声、all-or-nothing checkpoint 或无
AABB 布局，第 2～4 项仍会继续发生。

### 15.7 第二次 92 页重跑的验收标准

第二次重跑尚未产生结果。只有满足下面标准后，才可把最新候选晋级并评价
“优化后效果”；任何一项失败都应保留现场并继续修复，而不是覆盖第一次证据。

#### 15.7.1 重跑前置门

1. 第 30 页真实混合 PUA/轴/残缺公式先形成 RED，并在修复后 GREEN；合法短
   公式和完整选择题保护测试必须继续 GREEN。
2. 完整后端、长文档性能专项、PDF 输入专项、前端测试、build、compileall 和
   `git diff --check` 全部通过；测试总数变化时记录新的确切数字。
3. 候选容器继续满足非 root、read-only、cap-drop、no-new-privileges、资源
   上限、鉴权、资产鉴权、docs 404 和 secret preflight。
4. 候选只在隔离数据卷验收；切换公网前对在线 SQLite 做一致性 backup，并
   增量同步 uploads。不得让新旧代码同时写同一个 SQLite。
5. 固化候选 image ID、Git SHA、parser/prompt/schema/layout/model 配置和主
   PDF SHA-256；不能只记录“latest”标签。

#### 15.7.2 运行和可观测性门

1. 使用完全相同的 92 页 PDF 和固定参数
   `qwen / qwen3.8-max-preview / precision / use_ai=true`，创建新的 task/run，
   不覆盖 `1f5cf23f834a` / `run_34d43d8339d249cf`。
2. Theme 和每个 Branch 的实际 `max_attempts` 必须为 1；不得再次出现同一
   逻辑请求连续 `3×180s`。
3. 记录每个 stage、logical call、attempt、branch/input units、latency、
   status 和 fallback；任何 fallback 必须立即进入 degraded，并使
   `publish_gate=false`。
4. Branch 进度至少报告 `completed/total`、失败/降级数，不能再次固定显示
   42%；已完成 leaf 应增量 checkpoint，取消/重启后不得从零重做。
5. 必须运行到 completed 并生成 graph version，才能称为完成态基准。单次
   smoke 目标为不超过 12 分钟；P95 仍需多次冷运行，不能由单样本替代。
6. 记录容器峰值 RSS、CPU、重启/OOM 和 Provider 错误。若再次变慢，必须用
   stage/call 证据定位，不能凭资源猜测。

#### 15.7.3 输入和节点质量门

1. 解析 metadata 必须列出 fallback candidate/attempted/used/failed/retained
   页；任何关键页低质保留必须转成 publish-blocking degraded。
2. 至少恢复并核验 `第28章`、`§28.1`、`§28.2`、`§28.3`、`§28.4`、
   `§28.5` 的章节边界；不得只靠文件名生成一级主题。
3. 第 26 页噪声不得成为正式节点；第 30 页的 PUA、`z/y/θ` 轴碎片和残缺公式
   不得以 `uncovered` 文本 unit 进入模型；若公式无法可靠恢复，应 deferred。
4. 禁止纯页码、`…………`、裸 `A/B/C/D/提交`、人物照片、残缺公式句，以及
   以“为/是/的/则/有/引起”等残句开头或结尾的正式节点。
5. 每个正式 explicit 节点必须有可在对应页找到的 excerpt；每条正式父边必须
   是 `direct_parent` 且有关系 evidence。结构 support mapping 不能冒充人工
   已确认的直接父关系。

#### 15.7.4 源文内容准确性门

人工逐页核验至少覆盖五个一级章节：

1. `§28.1` 氢原子的量子力学处理，约第 2～33 页；
2. `§28.2` 电子自旋与自旋轨道耦合，约第 34～52 页；
3. `§28.3` 微观粒子不可分辨性、费米子和玻色子，约第 53～57 页；
4. `§28.4` 核外电子排布，约第 58～63 页；
5. `§28.5` 激光，约第 64～92 页。

必须检查的关键关系至少包括：玻尔三条件及局限、夫兰克—赫兹实验、
`Lz/L²` 与空间量子化、波函数概率和 `n/l/ml`、Stern–Gerlach 与
`s=1/2, ms=±1/2`、`J=L+S` 和 `j=l±1/2`、Na 双线/精细结构、费米子与
玻色子的交换对称性、壳层容量 `2n²`、自发/吸收/受激辐射与爱因斯坦系数、
粒子数反转/泵浦/光振荡、He–Ne 工作机理及 632.8 nm/1.15 μm/3.39 μm、
谐振腔纵模与三组成、激光的相干性/方向性/高亮度。

验收不只查“这些词是否出现”，还要查：

- 是否被挂在正确章节和直接父节点下；
- 是否把实验、定义、条件、结果混成同一个残缺节点；
- 数值、量子数、正负号和上下标是否与源页一致；
- 章节尾部和文档尾部是否因 Theme 抽样再次丢失；
- overflow/扩展主题中是否混入互不相关章节。

没有人工标注前，不输出未经证明的节点精确率、父边准确率或祖先 F1。

#### 15.7.5 PNG/画布门

完成态 graph 必须同时导出 JSON 和 PNG，并执行生产白盒检查：

- 所有节点框 AABB overlap=0，安全间距至少 24 px；
- 根分支按源顺序形成“右侧有序前缀 + 左侧有序后缀”，一旦溢出转左，后续
  不得再跳回右侧；
- 根标题完整显示，不得因 renderer 的行数上限产生省略号；
- raster 不超过 1600 万像素且任一维不超过 8192；
- 超预算时缩放或提供矢量/分块策略，不能重新分配一亿像素大图；
- 浏览器和 PNG 若仍由两套实现计算坐标，必须分别检查，不能只用 Python
  回放代替前端验收。

只有运行、解析、语义和布局四组门同时通过，第二次结果才可以用于判断第 2～5
项是否真正改善。否则应保留 task/run、checkpoint、model_calls、源文件、JSON
和 PNG 作为下一轮 TDD 证据，不得用“C+ 还没完全实现”笼统结案。

## 16. 2026-07-25 公网正式重跑失败与第三轮 TDD 根因闭环

本节记录 2026-07-25 北京时间发生的第二次公网正式重跑、它暴露的新直接根因，
以及第三轮部署前 TDD。它取代第 15 节中“第二次重跑尚未开始”的状态描述，但
不改写第 15 节作为第一次取消任务现场的历史证据。

### 16.1 第二次公网正式重跑现场

第二次任务运行在已完成 v3 数据迁移的公网镜像
`sha256:b3aa69f5e047213a7ccc6854d0b0d29148a9e85ac9903d1cb323eba56041d45e`
上，固定输入和参数仍为：

```text
source:
  精细1-量子物理原子中的电子.pdf
sha256:
  a36cf7a439a5d06fe9830e5fa6219836ecc63326ed53903a323bdd4078db54f9
provider/model:
  qwen / qwen3.8-max-preview
mode/use_ai:
  precision / true
```

运行标识和终态：

| 字段 | 值 |
| --- | --- |
| task ID | `07f9f6d79d7b` |
| run ID | `run_1bae38967995454c` |
| 开始时间 | 2026-07-25 10:05:50，北京时间 |
| 失败时间 | 约 2026-07-25 10:25:32，北京时间 |
| 终态 | job=`failed`、run=`failed`、stage=`failed`、progress=`60%` |
| 最后开始阶段 | `merge_audit` |
| graph version | 无 |
| 最终错误 | `UNIQUE constraint failed: node_claims.run_id, node_claims.item_id` |

本次不是资源故障：容器没有 OOM、重启或 cgroup kill。阶段和模型调用证据为：

- `model_check` 1 次成功，约 0.157 秒；
- `ledger` 24 次成功，累计模型 latency 约 282.193 秒，阶段 wall time 约
  110 秒；
- `themes` 1 次成功，约 168.304 秒，`max_attempts=1`；
- Branch Planner 产生 19 个叶分支；
- 18 个叶分支约 180 秒后 timeout，1 个叶分支约 177.094 秒成功；
- Branch 并发为 4，19 个请求形成五波，阶段 wall time 约 15 分钟；
- `merge_audit` 刚开始即因重复 `item_id` 失败。

证据已保存在：

```text
runtime/rerun-results/20260725-quantum-precision-v3-07f9f6d79d7b/
```

目录中的 job、run、checkpoint、model-call、progress、container-stats 和 SHA
文件均为 `0600`。这次失败同时包含“远端模型长尾”和“本地数据库唯一键”
两个独立故障，不能把数据库错误说成 timeout 的结果，也不能把二者都归因于
C+ 架构未完整。

### 16.2 新发现的六条独立确定性故障链

#### 16.2.1 思考预算没有真正受控

当时只给 Theme/Branch 设置了 `max_tokens`。对
`qwen3.8-max-preview` 这类思考模型，它不能可靠约束隐藏思考过程；模型默认
高思考强度时，即使一个 Branch 只有 6～7 个 unit，也可能持续到 180 秒。

因此：

```text
6～7 个 unit 的结构化抽取
  -> 只限制最终 JSON token
  -> 隐藏思考预算仍高
  -> 18/19 叶命中 180 秒
```

这是 Provider 请求策略 Bug，不是“课件 92 页所以必然慢”。第三轮改为：

- `reasoning_effort=low`；
- `max_completion_tokens = 可见回答预算 + 4096`，控制思考和回答的总生成上界；
- Theme、Branch、视觉调用单次 timeout 90 秒；
- 父边 verifier 单次 timeout 60 秒；
- 所有这些可确定性 fallback 的结构化调用 `max_attempts=1`。

#### 16.2.2 Theme 返回顺序污染源页连续性

旧 `build_branch_plans()` 直接沿用模型返回的 `support_unit_ids` 顺序。失败
运行的实际叶分支曾出现：

```text
2, 3, 5, 9, 12, 16, 19
```

以及：

```text
21, 23, 25, 28, 31, 33 + 第 5 页视觉
```

这会把相距很远的章节片段塞进同一 prompt，同时恶化耗时、标签和总结精度。
第三轮在分组前按 page/slide、text-before-visual 和原始稳定序重排，并用无损
不变量检查每个 planning unit 恰好进入一个叶分支。

#### 16.2.3 根主题顺序被 confidence 排序破坏

失败 checkpoint 重建出的根顺序曾为：

```text
§28.1 -> §28.2 -> §28.5 -> §28.4 -> §28.3
```

这不是源课件顺序。confidence 只能用于候选质量，不能覆盖课程叙事顺序。
第三轮以每个主题最早 page/slide 为主排序键，模型 confidence 不再决定最终
根子树顺序。

#### 16.2.4 Solver 又按哈希 ID 二次打乱

即使 Branch Planner 已恢复源序，CP-SAT 和 greedy fallback 原先还会按
`(depth, target_id)` 对最终节点/边排序。`target_id` 是哈希标识，不承载
课程顺序；PNG 和浏览器布局按 edge 输入序展开，因此 solver 会二次打乱同层
兄弟节点。

第三轮在 normalize、CP-SAT 和 greedy 三处统一保留 first-seen/source order，
只把根节点稳定放在首位，不再使用哈希 ID 作为同深度课程排序键。

#### 16.2.5 同页正文和视觉被“均分 unit”切到相邻叶

初步修复把 19 个叶都变成连续页后，白盒重建仍出现：

- 第 17 页正文和 4 个视觉 unit 被拆到两个叶；
- 第 25、29、84、88 页的正文/公式/图被拆到相邻叶；
- 叶标签因此从孤立视觉或公式残片取得，例如“历史黑白照片”、
  “A ⇒ 输出”“右端应为能量差”。

直接根因是按 `len(unit_ids) / leaf_count` 均分，而不是按 page/slide 原子组
分区。第三轮新增动态规划分区：

1. 先把同一 page/slide 的 text/visual 组成不可拆原子组；
2. 在每叶 `<=8 units` 的硬约束内求最均衡的连续分区；
3. 只有单页本身超过容量时才允许在该页内拆分；
4. 保留全局 `<=24 leaves`、无遗漏、无重复合同。

对失败 checkpoint 重建后的结果仍为 19 个叶，但同一根主题内
`split-pages=0`。叶标签改为优先从文本标题、编号小节和课程术语评分选取，
视觉标签只在没有合格文本时参与，并拒绝公式变量、方向说明、照片和“示意图”
类装饰标签。重建后的标签包括“斯特恩—盖拉赫实验”“电子的自旋轨道耦合”
“碱金属光谱的精细结构”“原子的激发和辐射”“受激辐射”“光学谐振腔”
“纵模个数计算公式”“激光的特点”，不再使用“子主题N”或前述垃圾残片。

这项修复独立于模型：即使模型完全不变，同页原子组被拆和标签选错仍是本地
确定性算法 Bug。

#### 16.2.6 `branch_topic` 重复 ID 触发唯一键失败

`theme_nodes()` 会创建：

```text
topic:{branch.id}
```

每个 Branch Team 的 `_abstraction_induction()` 又可能创建相同 `temp_id`。
旧 `canonicalize_semantic_duplicates()` 对 `branch_topic` 做结构角色豁免，
却没有先按 exact `temp_id` 合并。失败 checkpoint 重建证据为：

```text
raw nodes: 214
duplicate topic IDs: 10
```

随后 `save_node_claims()` 在同一 `executemany` 中插入重复
`(run_id,item_id)`，触发 SQLite UNIQUE。第三轮修复为：

- 语义近似去重和结构角色豁免之前，先按 exact `temp_id` 合并；
- 合并 evidence、support units、media、alias、confidence 和 activation；
- blackboard 在执行 `DELETE` 和批量插入前先验证输入 ID 唯一；
- 非法重复现在抛带 table/冲突 ID 的领域 `ValueError`，旧快照保持原子不变。

使用失败 checkpoint 离线重建：

```text
canonical_1: 202 nodes, duplicate IDs=0
coverage additions: 41
final: 239 nodes, duplicate IDs=0
```

### 16.3 真实单叶基准与“整份响应原子丢弃”

第三轮只执行了一次真实 Qwen 单叶请求，样本为连续 p79～84 的 He–Ne/谐振腔
叶，未写生产数据库、未挂生产卷：

| 指标 | 结果 |
| --- | ---: |
| units | 7（6 text + 1 visual） |
| 源字符 | text 848；合计 1047 |
| compact prompt | 3638 chars / 5761 UTF-8 bytes |
| visible answer budget | 4500 |
| reasoning reserve | 4096 |
| `max_completion_tokens` | 8596 |
| `reasoning_effort` | `low` |
| timeout / attempts | 90 秒 / 1 |
| 保守 wall 上界 | 58.306 秒以内成功 |

该 wall 上界还包含一次性容器启动、age secret 解密和 checkpoint 重建，真实
Provider latency 不会高于 58.306 秒。因最初 harness 在后处理异常前没有先
落 provider telemetry，精确 latency、usage 和 reasoning token 不可恢复；
遵守“只发一次”约束，没有为补指标再次请求。

模型原始返回 9 个 nodes、8 个 cross-links：

- 9/9 节点名称唯一且通过标签门；
- 9 条节点 evidence 中 8 条严格匹配源 unit；
- 8 条 cross-link 把 `evidence` 错写成 unit ID 字符串，而 schema 需要
  `EvidenceRef` 对象。

旧行为会因任一 cross-link schema 错误而丢弃整份 Branch，并回退到 heuristic。
第三轮新增分项校验：逐个验证 node 和 cross-link，保留有效 node，丢弃坏
cross-link 并记录 warning。对同一份保存响应做 `--network none` 重放后：

```text
used_model=true
retained valid nodes=8
dropped invalid cross-links=8
fallback links=0
```

同时补上两个失败安全门：

- 顶层 JSON 若不是 object，转换为可捕获 `ValueError` 并局部 fallback，不再
  由 `.get()` 触发未捕获 `AttributeError`；
- 候选预算选择前先按 exact `temp_id` 合并，避免后写覆盖导致 evidence/support
  丢失。

基准证据位于：

```text
runtime/benchmarks/20260725-single-leaf-qwen-low-total90/
```

全部文件为 `0600`，响应通过离线重放且 SHA 保持不变。

### 16.4 Provider 完成语义与错误信息安全

第三轮还修复了两个会间接制造垃圾节点或泄露源文的 Provider 协议问题：

1. HTTP 200 不再等于“完整成功”。只有 `finish_reason=stop`、字段缺失或
   `null` 被接受；`length`、`content_filter` 等即使 content 恰好可解析为
   JSON，也作为截断/非正常结束失败，进入受控 fallback。
2. HTTP 4xx/5xx 不再把 Provider 原始 `message` 拼进异常、持久 warning、
   telemetry 或熔断原因。对外只保留 HTTP status 和通过严格字符白名单的
   error code；401/鉴权/配额永久错误仍可熔断，普通请求级 400 不会污染后续
   调用。

这两项分别防止“半截 JSON 被当成完整节点集”和“Provider 回显 PPT 原文/API
key 后被写入数据库”，不属于 C+ 语义架构差距。

### 16.5 视觉媒体状态与原生/VLM 富化

视觉链路还存在两条不依赖完整 C+ 架构的确定性 Bug，它们会直接制造垃圾节点
或丢失已经得到的视觉语义。

#### 16.5.1 `attach_as_media` 被 Coverage Audit 反向建成节点

`attach_as_media` 的语义是“作为附近文本节点的媒体证据”，不是独立教学概念。
旧 coverage repair 在媒体未成功融合时，仍会把该视觉 unit 当成“未覆盖知识”
补建 standalone visual node，于是照片、图例和上下文插图会变成用户看到的
“莫名其妙摘点”。

第三轮合同改为：

- 成功融合时，只把资产加入目标节点的 `media_asset_ids`；
- 无法融合时，把 unit 标记为 `deferred` 并记录 warning；
- Coverage Audit 不得把 `attach_as_media` 或 deferred media 补成正式节点。

#### 16.5.2 pHash 命中原生资产后丢失 VLM 语义富化

同一图片既可能来自 PPTX/PDF 原生对象，也可能来自渲染页的 VLM crop。旧逻辑
在 pHash 命中时只把 crop 当作重复项拒绝，没有把 VLM 已产生的 summary、
knowledge claims、action 和 knowledge score 回填到语义较弱的原生
Content Unit，形成“像素去重成功、语义却被去掉”的结果。

第三轮逻辑复用同一 asset ID 和 occurrence provenance，并用 VLM 结果受约束地
富化弱原生 unit。`cplus_pipeline._merge_content_units()` 对相同 ID 执行合并；
其他无法解释的 ID 冲突显式报错，不再静默保留两个会互相覆盖的 unit。

这两项分别属于媒体状态机和内容单元合并 Bug，不能归结为模型质量或 C+ 架构
尚未完整实现。

### 16.6 第三轮 TDD 证据

第三轮遵循先 RED、后最小修复、再扩大回归：

- reasoning/总预算/timeout 接线测试先因参数缺失失败；
- source-order、page-atomic leaf、垃圾结构标签测试先失败；
- duplicate branch topic/blackboard 原子性测试先暴露 SQLite UNIQUE；
- malformed cross-link 测试先证明一条坏 link 会丢整份有效 node；
- 顶层数组测试先复现未捕获 `AttributeError`；
- `finish_reason=length/content_filter` 测试先证明被错误接受；
- HTTP error echo 测试先证明源文本/API key 可进入异常。

部署前最终回归口径：

```text
backend:
  .venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'
frontend:
  pnpm test
  pnpm build
static:
  .venv/bin/python -m compileall -q backend
  git diff --check
```

截至本节整理时已经确认的结果为：

- 后端全量回归 `195/195`；
- Provider 定向回归 `22/22`；
- Qwen policy 定向回归 `10/10`；
- 前端 `7/7`；
- Python compileall 通过；
- production build 通过，仍有既知的约 699 kB Vite chunk size 非阻断告警。

后端全量结果来自 2026-07-25 的实际终态；此前失败的非对象 Branch payload
用例最终定位为同一异常的两层文案合同不一致，而不是 fallback 算法失效。
统一为“顶层必须是对象（JSON 对象）”后，目标回退、白盒校验和 malformed
cross-link salvage 定向回归 `3/3`，随后全量 `195/195`。文档去重及并发修改
结束后，`git diff --check` 也已重新执行通过。

这些测试证明的是已编码合同和已固定夹具，不是完整 92 页生产准确率。

### 16.7 第 2～5 项更新后的独立归因矩阵

| 用户问题 | 2026-07-25 新增直接证据 | 当前直接修复 | 仍不能声称完成的部分 |
| --- | --- | --- | --- |
| 2. 约 30 分钟 | 19 叶中 18 个撞 180 秒；非 OOM；同一思考模型默认预算过高 | low reasoning、总 completion budget、90/60 秒单次 timeout、单 attempt、连续页小叶、compact prompt | 尚无 stage deadline、连续 timeout 熔断、leaf 增量 checkpoint；必须以新镜像整份重跑计时 |
| 3. 截断/垃圾摘点 | 同页 text/visual 被均分拆开，标签取到照片/公式/方向说明；截断 finish 可能被当成功；`attach_as_media` 被 coverage 补成节点；原生资产去重时丢失 VLM 富化 | page-atomic DP、文本标题评分、噪声标签门、partial schema salvage、非 stop 拒绝、media deferred、原生/VLM 受约束合并 | OCR/公式 span、真实 PPTX 对象层和更多未知课件仍需金标 |
| 4. PNG 重叠 | 仍是旧 360°/无 AABB 的独立布局缺陷，与本次模型 timeout/UNIQUE 无因果关系 | right-first、真实框高、24px AABB、raster budget、源序 sibling | 浏览器与 PNG 尚非同一持久坐标；需在新完成图和生产字体内再次验收 |
| 5. 子节点准确性 | unit/model/root/solver 三重乱序、整份响应因一条坏 link 回退、同页证据拆叶 | 源序、同页原子组、有效 node 分项保留、exact-ID merge、证据严格匹配 | 原子 claim、embedding/reranker、独立模型家族、人工父边金标和业务 P/R/F1 仍未完成 |

因此新的失败再次证明：第 2～5 项有各自可以复现、写测试并修复的直接原因。
“C+ 未完全实现”只解释能力上限，不能替代 timeout policy、ID 唯一性、页原子
分组、schema 容错或布局碰撞的具体归因。

### 16.8 本次部署后仍需明确列为未实现

即使第三轮新镜像和整份重跑成功，以下要求仍不能被悄悄标成已完成：

1. Branch/视觉/verifier 只有 per-call timeout，没有真正 stage deadline；
   连续 timeout 后尚不能让所有排队请求立即走 heuristic。
2. Branch 仍在整批完成后写完整 checkpoint；没有逐 leaf 增量提交和精确续跑。
3. Branch 进度仍不足以展示每个 leaf 的 completed/failed/fallback 数。
4. 当前 page-atomic DP 是确定性连续分组，不是设计中的多轮语义 cohesion
   递归 Branch Planner。
5. 原子 Content Unit、OCR/公式恢复、PPTX group/SmartArt/chart/notes/object
   provenance、embedding/reranker 和主树冻结后跨链仍未完成。
6. 生成、校验、二审和仲裁仍可使用同一 Qwen 模型家族，不是统计独立验证。
7. Python/TypeScript 仍分别计算布局，尚无服务端持久化、版本化的唯一
   `LayoutResult`。
8. 当前公网仍为明文 HTTP；HTTPS、secure cookie 终态和浏览器/移动端 E2E
   尚未完成。
9. 单叶 58.306 秒是一次样本的保守上界，不是完整运行 P95；完整 92 页重跑
   成功前不能宣称 12 分钟 SLA 已达成。
10. Required Coverage、Claim Precision、Evidence Alignment 必须由源 PDF
    人工 rubric 评估；`evidence_coverage=1` 和工程 confidence 不能替代人工
    准确率。

这些剩余项将作为部署后验收和下一轮 TDD 输入，而不是把已经独立修复的性能、
垃圾标签、重复 ID、部分 schema 和布局问题重新归结为“架构还没完全做完”。

## 17. 2026-07-25 正式完成态重跑与独立人工质量审查

本节记录第三次 92 页公网正式重跑、生产字体布局验收、138 节点逐节点人工
审查，以及完成态之后继续进行的 verifier batching、evidence matcher 和
label/definition 资格门 TDD。它取代第 15、16 节中“尚无完整成功重跑”的当前
状态描述；第 15、16 节仍保留为两次失败现场及其根因证据。

正式证据目录为：

```text
runtime/rerun-results/20260725-quantum-precision-v4-54c6aa316702/
```

总摘要为：

```text
runtime/rerun-results/20260725-quantum-precision-v4-54c6aa316702/
  evidence/rerun-summary.json
```

摘要及人工复核文件权限均为 `0600`。汇总只保留任务、运行、版本、阶段统计、
聚合质量和审计结论，不保存凭据、原始模型输入或 Provider 响应正文。

### 17.1 正式完成态基线

固定输入与运行身份：

| 字段 | 值 |
| --- | --- |
| 文件 | `精细1-量子物理原子中的电子.pdf` |
| SHA-256 | `a36cf7a439a5d06fe9830e5fa6219836ecc63326ed53903a323bdd4078db54f9` |
| 页数 | 92 |
| task | `54c6aa316702` |
| run | `run_c1e873dd28764e24` |
| mode | `precision` |
| provider/model | `qwen / qwen3.8-max-preview` |
| 终态 | job=`completed`、run=`completed`、stage=`complete` |
| 权威墙钟 | `1022.765832s`，报告值 `1022.77s`，即 **17 分 2.8 秒** |
| 权威墙钟来源 | `job-record.csv` 的 `updated_at - created_at` |

阶段时间：

| 阶段 | 秒 | 占总墙钟判断 |
| --- | ---: | --- |
| parse | 1.642452 | 非瓶颈 |
| ledger | 121.141671 | 有视觉/账本模型成本，但不是主瓶颈 |
| themes | 66.597999 | 单次较长调用 |
| branch_plan | 0.039982 | 确定性规划不是瓶颈 |
| branches | **354.845367** | 第一主瓶颈之一 |
| merge_audit | 0.124382 | 非瓶颈 |
| normalize | 0.086593 | 非瓶颈 |
| verify | **477.889170** | 最大瓶颈 |
| solve | 0.265424 | CP-SAT 不是耗时根因 |
| finalize | 0.132792 | 非瓶颈 |

Branches 与 verify 合计占权威墙钟 **81.42%**。模型调用共 247 次：

- `model_check=1`；
- `ledger=24`；
- `themes=1`；
- `branches=19`；
- `verify=202`；
- 243 次成功，4 次持久状态为 `retryable_error`；
- 4 次失败的语义错误类型均为 timeout，其中 Branch 3 次约 90 秒，
  verifier 1 次约 60.8 秒。

`progress.tsv` 终态显示 `timeout=0,error=4`，是状态分类口径差异：持久状态
使用 `retryable_error`，而错误详情中的语义类型是 timeout。后续监控不得只看
`timeout` 计数列而漏报真实 timeout。

本次仍不是资源故障：

- CPU 峰值 28.68%；
- 内存峰值 233.7 MiB / 3 GiB，即 7.61%；
- PIDs 峰值 14；
- 无 OOM、无 restart，终态容器健康。

最终图为 138 个节点、137 条树边、30 条跨链，唯一根、全可达、无环、无孤儿，
solver=`OPTIMAL`。这些只证明结构不变量成立，不证明 claim、父边或教学顺序
全部正确。

### 17.2 问题 2：17 分钟性能的独立代码/算法根因

正式完成态把历史“约 30 分钟”问题缩短到 17 分 2.8 秒，但没有达到 12 分钟
整文 smoke 目标。当前剩余性能瓶颈不是 parse、normalize、solver 或机器内存，
而是两个可单独定位的远端调用面：

```text
19 个 Branch 结构化抽取请求
  -> 16 成功平均约 64.9 秒
  -> 3 个在约 90 秒 timeout
  -> Branch wall 354.85 秒
```

```text
父边校验按一个 child 一次 HTTP 请求
  -> primary / secondary / arbiter 风险路径累计 202 次 verify 调用
  -> 201 成功平均约 18.3 秒
  -> 1 次约 60.8 秒 timeout
  -> verify wall 477.89 秒
```

正式镜像已经把同一 child 的多个 parent candidate 放进一次比较，但 HTTP 层
仍基本是“一 child 一请求”，所以 138 节点图仍产生 202 次 verify-role 调用。
这说明“候选批量比较”和“多 child HTTP batching”是两个不同层次，不能因为
前者存在就宣称调用规模已经解决。

完成态后的 TDD 在当前工作树增加：

- `VERIFIER_CHILD_BATCH_SIZE=4`；
- primary、secondary、arbiter 分角色把四个 child 放进一次 HTTP 请求；
- 每个 child 仍在一次响应中比较其全部候选父；
- 返回遗漏、未知 parent 或坏 child 时，只让该 child 使用 deterministic
  fallback，不再原子丢弃同批其他 child；
- 结构化统计区分 requested、attempted、succeeded、fallback child 数，并映射
  到 partial/failed degraded component。

批量 TDD 已证明 8 个 child 的 standard 校验从 8 个 HTTP 请求降到 2 个；
precision 的 primary、secondary 和 arbiter 也分别按四 child 分批。它尚未在
新的 92 页完成态中重新计时，所以不能把理论约四倍 HTTP 数量下降直接写成
新的生产分钟数。

仍未实现的 stage deadline、连续 timeout 熔断、逐 leaf checkpoint 和精确
续跑会继续放大长尾。它们是普通任务编排和远端调用工程问题；递归 Branch
Planner、embedding/reranker 等 C+ 能力可能进一步减少工作量，但不是修复
timeout policy、HTTP 批量或 checkpoint 的前置条件。

### 17.3 问题 3：文字截断和“莫名摘点”的独立根因

字体感知验收确认 renderer 没有新增标签截断，`label_truncation_count=0`。
因此本次正式图中仍可见的异常文字，主要已经在节点生成和持久化之前形成，
不能再归因于 PNG 画布裁切。

人工逐节点复核发现的代表性异常：

| 节点 | 表现 | 直接根因 |
| --- | --- | --- |
| `node_7bf97ce023f0` | definition 在“应有：即 54”处结束，交换公式消失 | 原页 OCR/文本序列和生成摘要未保持完整公式，旧 definition 门未拒绝 |
| `node_29ace7e15619` | label 为“这说明原来对原子中电子运动的描述”，definition 只有“不完全的” | 一个原句被拆成两个非自足字段 |
| `node_816f1764f4b6` | 吸收段落在“从 E1”处突然终止 | 原始 OCR 长段落直接进入节点，缺少句级安全边界 |
| `node_dcd7f15f10b1` | “所以考虑到自旋轨道耦合能后，有”作为标题 | sentence stem 被当成概念 label |
| `node_e18ce90f9925` | “例如 l=1 时，而”作为标题 | 例句引导和尾部连接词没有被粒度门拦截 |
| `node_dc3bf4e60d44` | 混入“好激光器：1”、能级图例和断词 | OCR/版面文本粘连后以整页段落发布 |
| `node_c670e6117e91` | 非聚焦/聚焦强度缺操作数和单位，并粘入“第28章结束” | 公式恢复失败、谓语粘连和页脚去除失败 |

4 个明显垃圾节点也进入了正式图：

1. 泡利奖项、国籍和生卒年人物背景；
2. 只描述水平线、括号和 `n/n′` 的能级图；
3. 只描述人物/圆形视场和 `30/40/50/60` 刻度的照片节点；
4. 只描述 `I/ν/ν₀/Δν` 轴和半高宽图例的孤立曲线节点。

这条故障链由多个独立环节共同组成：

```text
PDF/OCR 公式、上下标、PUA、页脚或图例未恢复
  -> 模型收到非自足长段或视觉描述
  -> label/definition 只做局部语法检查
  -> visual knowledge / 原始 OCR 被提升为独立节点
  -> topology 为其找到合法父边
  -> 结构合法的垃圾节点进入图和 PNG
```

其中解析与公式恢复属于输入保真；sentence stem、generic visual 和 definition
尾部污染属于资格门；照片/图例变节点属于视觉 action/融合状态机；最终发布
属于质量门。它们都可以在不完成完整 C+ 的情况下分别写 RED、修复和回归。

### 17.4 问题 4：PNG 重叠已由独立布局算法解决

正式完成图的权威验收文件为 `acceptance-report-font-aware.json`。使用生产
字体 `Noto Sans CJK JP` 重新测量文本和节点框后：

- 22/22 检查通过；
- 根分支侧序为 `right/right/right/left/left`；
- 子树保持在分配侧；
- sibling/source order 单调；
- AABB 最小实测间距 32px，高于要求的 24px；
- AABB violation 为 0；
- PNG 与 JSON 布局坐标一致；
- PNG 为 2178×6481，共 14,115,618 pixels，低于 1600 万像素和 8192 单边上限；
- renderer 没有新增文字截断。

一次较早的非字体感知检查错误地按缺少生产 CJK 字体的框高重建布局，得到
5956px 高度并误报 `png.matches_json_layout` 失败；它已经被字体感知报告取代。
这说明布局验收也必须固定字体文件及其 hash，不能只用默认字体估算。

旧问题的直接根因仍是 360° 径向分配、整层密度半径、无真实文本框、无子树
extent 和无碰撞消解。right-first、真实框高、子树包围盒和 AABB 间距已经
独立修正这条链，不需要先完成原子 Content Unit、embedding 或父边金标。

当前残余不是本次 PNG 重叠，而是 Python 和 TypeScript 仍可分别计算布局，
尚未持久化一个版本化的唯一 `LayoutResult`。未来若浏览器重新布局，仍可能
出现预览与已验收 PNG 漂移。

### 17.5 问题 5：子节点内容准确性的独立人工结论

本次不再用 `confidence`、`evidence_coverage`、模型成功率或 topology 合法率
替代业务准确率。对 138 个节点逐项检查 `name + definition`，并核对声明的
page/excerpt 与 source-gold，得到：

| 指标 | 分子 / 分母 | 结果 |
| --- | ---: | ---: |
| Required Coverage | 67.5 / 88 | **76.70%** |
| Claim Precision | 91 / 105 | **86.67%** |
| Evidence Alignment | 95 / 105 | **90.48%** |

138 个节点的 Claim Precision 人工分类为：

- supported：82；
- partially supported：18；
- contradicted：1；
- nonclaim noise：4；
- grouping only：18，不进入精度分母；
- duplicate only：15，不进入精度分母。

最严重的两条内容错误：

1. `node_02e1ca52d0e3` 把源公式 `nL=kλ_k/2` 写为
   `nkλ/2=L`，把折射率和纵模编号错误乘到波长侧。这是 contradicted claim，
   不是排版差异。
2. `node_7591952fe5e7` 把源页的相对线宽
   `Δν/ν≈10⁻¹⁵` 写成无量纲“线宽 10⁻¹⁵”，同时把超高稳频过度归因于
   少数驻波频率。这同时是量纲丢失和因果过推断。

Required gold 中 H04 与 L13 完全缺失：

- H04：玻尔理论可解释氢光谱波长，但不能解释谱线强度、复杂原子光谱，且仍是
  保留经典轨道的半经典理论；
- L13：Ne 的 632.8 nm、1.15 μm、3.39 μm 三条强激光谱线。

另有 7 个主题段错挂或边界薄弱。代表性错误包括：

- 轨道贯穿/径向概率内容挂在“电子的自旋轨道耦合”；
- 吸收概率 `W12` 挂在“受激辐射”；
- He→Ne 共振转移和粒子数反转机制挂在“光学谐振腔选频原理”。

这些 claim 本身有时可以从源页得到支持，所以 Claim Precision 仍可能记 1；
但错误 parent/path 会破坏学习顺序和导图可用性。节点事实准确率与父边/主题
准确率必须分开评价。

正式结果的 structural gate=true，但 quality gate=false、publish gate=false。
阻断项包括：

- 45 个 pending review；
- 2 条 provisional parent edge；
- weighted content coverage 仅 0.8014；
- non-direct parent、缺边证据；
- `visual_render_budget`、`visual_understanding_model`、
  `branch_extraction_model`、`independent_parent_verifier_partial`
  四个 degraded component。

所以“结构合法、布局 22/22、模型成功率 98.38%”均不能推出“子节点总结已经好”。
内容问题分别来自公式/量纲校验、claim 自足性、语义去重、父边召回和 source-gold
覆盖，不应全部归结为“架构未完整”。

### 17.6 完成态后的 label/definition/coverage 安全门独立审查

正式图完成后，工作树又加入更严格的 label、definition 和 evidence 门。第一轮
对真实 138 节点离线复放发现：污染规则本身大体能命中目标，但当时
“字段命中即整节点拒绝”的处置粒度过粗，会误杀合法知识。下面 17.6.1～
17.6.3 保留这次 RED 审计及其覆盖代价；当前代码已经改为字段级 typed
disposition，不应再把这些表述读成当前仍会整节点误杀。

#### 17.6.1 Label 门

Label 门命中 22 个节点：

- 9 个 duplicate only；
- 5 个 partially supported；
- 3 个 nonclaim noise；
- **5 个人工判定 supported 的合法节点**。

5 个合法误杀是：

| 原节点 label | 触发原因 | 应有行为 |
| --- | --- | --- |
| `*§28.3 微观粒子的不可分辨性，费米子和玻色子` | `raw_section_echo` | 精炼为“微观粒子的不可分辨性（全同性）”，保留 I01 合法定义 |
| `视觉知识` | `generic` | 根据定义精炼为“轨道角动量与自旋角动量的量子化”，补全公式 |
| `定态条件关键要点` | `generic_summary` | 精炼为“玻尔半径与氢原子基态能量” |
| `五. 激光的特点` | `raw_section_echo` | 精炼为“激光的相干性与方向性”，保留 L18 |
| `三. 激光器的实例` | `raw_section_echo` | 精炼为“He–Ne 激光器的介质组成”，保留 L09 |

这些 label 确实不适合作为最终显示名，但 definition 和 evidence 中存在合法
知识。正确处置是 `repair_label_keep_claim`，不是 `reject_entire_node`。

当前 `candidate_field_disposition()`、Branch critic 与 normalize 已共用同一
处置结果。上述 5 个正式样本均有 TDD 锁定为
`repair_label_keep_claim`，分别精炼显示名并原样保留合法 definition；另有
4 个 label/definition 主题错配或悬空片段转
`reextract_candidate`，真正双字段不可恢复的节点才
`reject_entire_node`。

#### 17.6.2 Definition 门

Definition 门命中 5 个显式节点，5 个文本都确有污染，但只有一个适合整删：

- `node_29ace7e15619`：label 是悬空句，definition 只有“不完全的”；
  name/definition 都不可恢复，可整节点拒绝。
- `node_7bf97ce023f0`：首句和 label 的“全同粒子系统必须考虑不可分辨性”
  合法，后半公式截断；应裁到合法句或清空 definition，以 label-as-claim
  保留，交换公式对应 coverage 继续 deferred。
- `node_816f1764f4b6`：吸收共振条件与 E1→E2 完整，只有末尾概率段截断；
  应裁剪后保留并重抽取尾段。
- `node_dc3bf4e60d44`：受激辐射方向、同频同相同偏振、光放大和
  `W21=B21ρ` 均存在；应删除版面污染并保留 L04 核心。
- `node_c670e6117e91`：“亮度和强度极高”、脉冲功率 `>10¹⁴ W` 和约
  `10⁸ K` 合法；应删除缺操作数公式、粘连谓语和页脚，保留 L19 安全句。

因此，“5 个 definition 命中都等价于 5 个全坏节点”是错误归因。当前安全门
已经支持 `trim_definition_keep_claim`、
`repair_label_and_trim_definition_keep_claim`、
`reextract_candidate` 和 `reject_entire_node` 等 typed disposition：
4 个正式污染 definition 只裁剪坏尾部并保留 claim，只有
`node_29ace7e15619` 整节点拒绝。

#### 17.6.3 Coverage 代价必须按当前口径重算

当前 `coverage_statistics()` 的 eligible 条件是：

```text
unit.status != rejected and unit.importance > 0.15
```

真实 eligible importance 分母为 **86.7231**，不是 86.9431。后者误把两个
importance 分别为 0.10 和 0.12、按当前规则不进分母的单元算入。

正式 export 持久化的 weighted content coverage 为 80.14%；在完成态之后更
严格的 evidence matcher 下，对同一 export 重新计算的基线为 **78.55%**。
两者是不同代码口径，不能混用。

下面是修复前“仍按整节点移除”策略的反事实模拟，用于量化错误处置会造成的
知识损失；它不是当前字段级实现的输出：

| 模拟 | 丢失唯一覆盖 unit | importance 损失 | coverage |
| --- | ---: | ---: | ---: |
| 当前 matcher 重算基线 | — | — | 78.55% |
| 仅整删 5 个 definition 命中 | 5 | 3.0479，下降 3.51pp | 75.04% |
| 仅整删 22 个 label 命中 | 25 | 17.8567，下降 20.59pp | 57.96% |
| label + definition 全部整删 | 29 | 20.2949，下降 23.40pp | **55.15%** |

仅 5 个 supported label 误杀就损失 3.4662 importance，约 4.00 个百分点。
在 source-gold 依赖上，I01、L09、L18 会失去唯一完整节点；definition 整删
又会让 L04、L19 直接缺失，并使 L03 从 fully 至多降为 partial。删除垃圾和
重复节点造成的 coverage 下降属于纠正虚假覆盖；删除 supported 或含合法核心
节点则是真实知识损失，报告必须分桶说明。

#### 17.6.4 仍会漏过的错误

字段正则门仍不是语义 verifier；当前工作树把职责拆成 parser、claim hard
gate、field disposition 和 semantic dedupe 后，历史问题的状态变为：

- 4 个 nonclaim noise 在确定性正式 checkpoint 回放中移除 3 个，纯
  “能级示意图”仍作为 1 个独立节点漏过；
- 三个只说“展开式/简洁表达/列表”而不展示实际内容的视觉节点已由
  visual/field 门大部清理，但泛化视觉概念仍需语义或人工复核；
- 里德伯公式节点若只说“包含 n 与 n′”而没有公式，句法门仍不能补造公式；
- 15 个 duplicate only 的回放结果为 6 个并入文档化目标、8 个移除、1 个
  保留为独立非重复 claim；normalize 形成 6 个双成员语义簇，人工金标潜在
  误并为 0；
- 错误驻波公式和丢失 `Δν/ν` 的无量纲 `10^-15` 不再依赖句法正则：新 parser
  先恢复 p85/p86 数学串，claim fidelity 硬门分别以
  `conflicting_relation` 和
  `extreme_scientific_value_missing_dimension` 拒绝。

后续门禁必须分工：

1. label 门处理显示名可读性；
2. definition 门处理句法完整性和字段污染；
3. evidence matcher 处理 unit 绑定、excerpt 特异性和源文包含；
4. semantic verifier 处理公式、量纲和因果；
5. dedupe 处理跨模态/跨分支同义重复。

### 17.7 Post-run verifier batching、evidence matcher 与 TDD

#### 17.7.1 Evidence matcher

正式镜像已要求 excerpt 出现在源 unit 中；完成态后的当前工作树进一步收紧：

- Unicode NFKC 和常见 OCR 标点/运算符归一化；
- 英文断词换行恢复；
- evidence 必须绑定声明的 unit/asset，不能只依赖一个合法外键；
- “主要内容、基本概念、实验结果、如图所示”等泛化短摘录不能认证 coverage；
- 普通摘录至少具有足够语义字符；极短数学摘录必须含关系/运算符；
- 分别检查 text、evidence excerpt、OCR、summary 和 knowledge claims，不再把
  所有字段先拼成一个字符串后制造跨字段伪匹配；
- review 后重新计算继续复用同一 `coverage_statistics()`，没有另开宽松旁路。

已有 review 测试失败最终定位为夹具使用“知识点原文”“另一段原文”等 5 字
占位摘录。修复只替换测试夹具为足够长、与 unit 严格一致的近原文，没有放宽
生产 evidence 安全门。

#### 17.7.2 Verifier batching

新增 batching TDD 覆盖：

- 8 child、每 child 3 parent 时只发 2 个 HTTP 请求；
- 同批缺 child 或返回未知 parent 时，只 fallback 受影响 child；
- precision 的 primary、secondary、arbiter 分角色分别批量；
- 每个 child 的全部 candidate 和 edge/unit evidence scope 仍保留。

这项修改直接针对正式运行的 202 次 verify 调用，但尚未有新的完整运行证明
实际 wall time。验收必须同时记录 HTTP/model-call 数、角色统计、partial
fallback 和 verify 阶段墙钟。

#### 17.7.3 TDD 口径

第三轮部署前统一回归为 backend 195/195、Provider 22/22、Qwen policy
10/10、frontend 7/7。完成态之后继续新增字段处置、claim fidelity、semantic
dedupe、verifier batching、冷启动循环依赖、同 temp ID 和 p88 PUA 回归。
当前工作树重新执行全量质量门的结果为：

- `unittest discover`：274/274 通过；
- `pytest backend/tests`：274/274、221 个 subtest 通过；
- frontend：7/7 通过，production build 成功；
- 独立 export evaluator：5/5 通过；
- 92 页零模型回放：历史弱 oracle 为 15/15；该结论已于 2026-07-26
  因 p88/p92 断言不完整而判定失效，不能再作为公式验收证据；
- Python compile、`git diff --check` 和 Compose placeholder config 通过。

274 是当前全量测试数，不能再与历史 195 相加。独立审查曾发现原 TDD 把
“视觉知识”“五. 激光的特点”等带合法 definition 的候选直接断言为整节点
删除；当前测试已改为“非法 label 被精炼、合法 claim 保留”，并分别锁定
repair、trim、reextract、reject 的字段级合同。

### 17.8 第 2～5 项完成态独立归因矩阵

| 用户问题 | 完成态直接证据 | 独立代码/算法根因 | 与 C+ 未完整的关系 |
| --- | --- | --- | --- |
| 2. 一个文件约 30 分钟 | 完成态 17 分 2.8 秒；verify 202 calls/477.89s，branches 354.85s，二者占 81.42%；非 CPU/OOM | 历史 verifier 没有多 child HTTP batching；当前已实现每批最多 4 child，但远端结构化调用长尾、per-call timeout、无 stage deadline、无 leaf checkpoint 仍独立存在 | 递归语义规划/缓存可进一步减少工作量，但 batching、timeout 和 checkpoint 可独立修复；新 batching 必须用完整生产重跑计时 |
| 3. 文字截断/摘点 | renderer 截断为 0，但旧节点中仍有断公式、sentence stem、图例/页脚粘连和 4 个垃圾节点；当前离线回放移除 3 个垃圾、仅剩“能级示意图” | PDF/OCR/公式保真、字段生成、label/definition typed disposition、视觉 action 和 publish 资格门 | 原子 provenance 会提高上限，但 PUA 映射、claim hard gate、状态机和字段级处置不是完整架构的前置依赖 |
| 4. PNG 框重叠 | 138 节点生产字体 22/22；最小间距 32px；right/right/right/left/left | 旧 360°/整层密度/无真实框和碰撞消解；已由 right-first/AABB 独立修复 | 节点过多只会加重旧算法，不是发生重叠的必要条件 |
| 5. 子节点准确性差 | Coverage 76.70%、Precision 86.67%、Evidence Alignment 90.48%；公式/量纲错误、4 垃圾、15 重复、18 partial、7 错挂 | claim 自足性、公式/量纲语义校验、证据对齐、去重、父边召回和 gold 缺口 | embedding/reranker、abstraction、独立模型家族属于未完成能力；但错误公式、证据错配、资格门误杀和父边错挂仍需分别负责 |

因此，第 1 项“未完全实现 C+”只能描述能力缺口，不能成为第 2～5 项的统一根因
或免责理由。完成态已经分别给出了性能、文本、布局和内容质量的独立可观测量。

### 17.9 完成态后仍未实现或未达成的 13 项

1. **Stage deadline 和连续 timeout 熔断未实现**：只有 per-call timeout；
   连续 timeout 后不能立即让排队 Branch/verifier 全部进入受控 fallback。
2. **逐 leaf checkpoint 和精确续跑未实现**：Branches 仍以整批 checkpoint
   为主，不能只重跑未提交 leaf。
3. **逐 leaf 进度未实现**：进度不能完整展示每个 leaf 的 completed、failed、
   fallback 数。
4. **递归语义 Branch Planner 未实现**：page-atomic 连续 DP 是确定性分区，
   不是多轮 semantic cohesion 递归规划。
5. **原子单元和对象级 provenance 不完整**：已知 PDF PUA、比例、负指数和
   驻波分式已有恢复，但通用 OCR/公式 AST、PPTX group、SmartArt、chart、
   notes 和对象级 provenance 尚未完成。
6. **Embedding/reranker 与跨分支重分配未实现**：当前 deterministic
   semantic dedupe 已处理保守的跨模态/跨页等价 claim，但父候选召回和真正
   merge/reassignment 仍没有 embedding/reranker；人工审计已有 7 个错挂/
   薄弱主题段。
7. **独立模型家族和备用 Provider 未实现**：生成、校验、视觉、二审和仲裁仍
   使用同一 Qwen 家族，逻辑角色不同不等于统计独立。
8. **唯一持久化 LayoutResult 未实现**：本次 PNG 22/22，但 Python/TypeScript
   仍没有共享一个版本化、可复用的服务端坐标结果。
9. **HTTPS 和浏览器/移动端 E2E 未完成**：当前仍为明文 HTTP，secure-cookie
   终态和完整浏览器/移动端验收缺失。
10. **12 分钟完整文档 SLA 未达成**：正式完成态为 17 分 2.8 秒；post-run
    verifier batching 尚未用完整 92 页重跑计时。
11. **Publish-ready 内容清理尚未由生产重跑证明**：v4 生产基线仍是
    Required Coverage 76.70%、4 垃圾、15 重复、18 partial、1 contradicted
    和两个必需 gold 缺失。当前历史候选离线回放已硬拒绝 contradicted/量纲
    错误、移除 3/4 垃圾并处置 14/15 duplicate，但它不会重新生成缺失 claim，
    也不是新的人工业务准确率。
12. **零 pending/零 provisional 发布状态未达成**：仍有 45 pending、2
    provisional、4 degraded component，publish gate=false。
13. **多文档与直接父边金标未完成**：人工三指标目前只覆盖这一个 92 页 PDF；
    没有多文档、多标注者、父边 P/R/F1 和祖先 F1。

这 13 项是下一轮实现和验收清单。它们不能反向抹掉本轮已经独立证明的布局
修复，也不能掩盖本轮仍独立存在的 verifier 长尾、字段污染、门禁误杀、内容
错误和父边错挂。

## 18. 2026-07-25 当前工作树的零模型正式 checkpoint 回放

> 2026-07-26 更正：本节的 15/15 是历史回放记录，不再是有效验收结论。
> 当时 p88 只检查同时出现 `N=` 和 `≈8`，p92 只检查零散数字和单位，无法
> 证明分母、指数符号、下标和完整公式均正确。当前有效口径见第 19 节。

本节记录完成态之后新增的 parser、claim fidelity、字段级处置、semantic
dedupe、上游 canonicalization 和 verifier batching TDD。它使用同一份 92 页
PDF 和 v4 完成任务的 9 个 checkpoint，但不重新调用 Theme、Branch、VLM、
verifier 或 arbiter 模型。

因此，本节回答的是：

> “如果把历史模型候选交给当前确定性代码，已知错误会如何被过滤、合并、归一
> 和求解？”

它不回答：

> “当前代码完整公网重跑需要多少分钟，模型会生成哪些新候选，人工准确率是否
> 已达标？”

后一个问题必须在新镜像公网切换后，用同一 PDF 从上传开始完整重跑并重新人工
审查。

### 18.1 可重复证据、隔离边界和输入身份

回放工具：

```text
runtime/tools/replay_quantum_v4_current.py
```

权威摘要：

```text
runtime/rerun-results/20260725-quantum-offline-current-v5/summary.json
```

同目录还保存：

- `parsed-document.json` 与逐页 `page-text.txt`；
- 历史 unit ID 覆盖后的 `replay-content-units.json`；
- `hard-claim-rejections.json` 与非硬缺口；
- canonical、normalized、solved 三阶段 JSON；
- source-gold lineage audit、node inventory 和 `SHA256SUMS`。

隔离合同为：

- Docker `--network none`；
- 容器 rootfs read-only；
- 当前仓库只读 bind mount；
- Python socket 连接在进程内再次 fail-closed；
- remote model calls 固定为 0；
- 只把生成的审计文件写入新的 runtime 结果目录；
- 使用现有生产镜像提供 `/usr/bin/pdftotext` 和依赖，但 import 的
  `backend/` 来自当前工作树。

源文件 SHA-256 仍为：

```text
a36cf7a439a5d06fe9830e5fa6219836ecc63326ed53903a323bdd4078db54f9
```

checkpoint 包含 parse、ledger、themes、branch_plan、branches、
merge_audit、normalize、verify、solve 共 9 个阶段；历史 merge_audit 输入为
185 个 node candidates、192 个 parent candidates 和 121 条 cross-link
candidates。

### 18.2 Parser 的第三条数学 PUA 根因：`` 没有映射为 `≈`

第一次运行回放得到 14/15，只失败：

```text
parser_required_anchors
```

p85 的 `Δν/ν` 与 `10^-15`、p86 的
`nL=kλ_k/2；λ_k=2nL/k` 均已恢复；失败来自 p88：

```text
N=Δν/Δν_k 8
```

字符 `` 是 U+F040。旧映射已经处理：

```text
U+F06C -> λ
U+F06E -> ν
U+F0B4 -> ×
U+F0BB -> ≈
U+F0DE -> ⇒
```

但遗漏了：

```text
U+F040 -> ≈
```

这说明“Poppler 回退成功”不等于“数学语义已恢复”；同一旧 Symbol 字体中的
近似号可由不同 PUA code point 表示。修复过程严格按 TDD：

1. 新增 p88 风格 `N=Δν/Δν_k \uf0408` RED；
2. 证明 `_prepare_pdf_math_layout()` 原样留下 PUA；
3. 增加 U+F040 的保守映射；
4. parser/claim fidelity 定向回归转 GREEN；
5. 重新运行完整离线回放，15/15 通过。

最终 parser 结果：

| 指标 | 结果 |
| --- | ---: |
| 页数 | 92 |
| parser wall | 2.119496 秒 |
| Poppler candidate pages | 32 |
| math comparison pages | 30 |
| 实际采用 fallback pages | 23 |
| failed pages | 0 |
| 低质结果仍保留 | 第 26 页 |
| p85 相对线宽锚点 | PASS |
| p86 驻波关系式锚点 | PASS |
| p88 纵模数 `≈8` 锚点 | PASS |
| p92 两个强度锚点 | PASS |

这条根因独立属于输入字形适配器，不是 Branch Planner、模型提示词或 C+ 架构
完整度问题。

### 18.3 Claim hard/soft 分层阻断两个严重事实错误

当前 Branch 输出门同时检查显式候选的 `name` 与 `definition`，并使用候选绑定
Content Unit 的完整 claim sources，而不是只用短 excerpt。问题分为：

- hard：存在确定性冲突或足以安全拒绝的量纲错误，转
  `deferred/reextract`，不进入正式候选；
- soft：当前文本/OCR 未抽出全部关系、数字或单位，但没有独立矛盾，保留候选
  并等待源页/视觉复核。

历史 185 个候选经新 parser 文本覆盖后，硬门得到：

| temp ID | 历史错误 | hard code | 结果 |
| --- | --- | --- | --- |
| `branch_118eaa93f280:node_1` | `nkλ/2=L` 与源 `nL=kλ_k/2` 冲突 | `conflicting_relation` | 拒绝 |
| `branch_118eaa93f280:node_7` | 把 `Δν/ν≈10^-15` 写成无单位“线宽 10^-15” | `extreme_scientific_value_missing_dimension` | 拒绝 |

计数为：

```text
input candidates: 185
hard rejected: 2
kept: 183
```

代数判断不是字符串模糊匹配。实现将乘除单项式表示为精确有理系数与变量幂：

- `λ_k=2nL/k` 与 `nL=kλ_k/2` 等价，不 hard reject；
- `nkλ/2=L` 与源式不等价，hard reject；
- `λ_k/λₖ`、`E_n/Eₙ`、`E_1/E₁`、`L_z/m_l` 保留下标变量身份；
- 来源未抽出 `E_n=E_1/n²` 时只产生 soft 缺口，不因 OCR 不完整盲删。

这条链修复的是“模型改写公式/量纲后仍被证据 ID 自证”的 claim fidelity
问题，不能归咎于架构未完整，也不能由布局或 topology 合法性替代。

### 18.4 上游 canonical 与 normalize 语义去重的代码级归因

旧上游仍有两个可独立制造混乱的入口：

1. 同 branch 的 `SequenceMatcher >= 0.94` 会把名称很像但公式冲突的节点合并；
2. 同一 `temp_id` 若直接字段混合，会把高分正确 claim 与低分错误
   name/definition/alias/evidence 拼成一个“看似证据更强”的节点。

当前修复为：

- fuzzy name 不再具有合并资格；
- 代数等价公式即使名称不像，也可以在 provenance 与上下文相容时合并；
- 冲突公式、冲突数字、反向因果、同页异 claim、结构节点、互补父子事实受到
  硬保护；
- 聚类使用 complete-link，簇内每一对都必须兼容；
- survivor、node ID、temp ID、evidence、parent/cross endpoint 全部确定化；
- 同 `temp_id` 的 structural 身份继续合并；
- 普通候选只有语义等价，或两者都没有 definition 且 label 不含公式、数字、
  因果断言时才合并 evidence；
- 一旦存在物质性冲突，只保留高排名 claim，不把 loser 的 name、definition、
  alias 或 evidence 混入。

回放结果：

```text
183 hard-gate survivors
  -> 179 canonical candidates
  -> 131 normalized nodes
  -> 110 solved nodes
```

细分为：

- canonical 阶段 4 个双成员 collapse；
- normalize 阶段 6 个双成员 semantic cluster；
- 15 个历史 duplicate-only：
  - 6 个并入人工文档化目标；
  - 8 个移除；
  - 1 个保留为独立非重复 claim；
- source-gold audit 的潜在误并为 0；
- 两次完整确定性 replay 的 signatures 完全一致；
- canonical lineage unresolved temp IDs 为 0。

节点从 185 降到 110 不能全部归因于 semantic dedupe。它至少包含四个桶：

1. 2 个 claim hard rejection；
2. 4 个 canonical collapse；
3. 6 个 normalize semantic merge；
4. 旧 `coverage_*` 自动补点、字段 reextract/reject、optional activation 和
   solver 淘汰。

任何报告若把 75 个节点的总下降都写成“语义去重删除了 75 个”，都会再次混淆
算法责任。

### 18.5 字段级处置的当前结论

当前合法 action 为：

```text
accept
repair_label_keep_claim
trim_definition_keep_claim
repair_label_and_trim_definition_keep_claim
reextract_candidate
reject_entire_node
```

正式回归夹具证明：

- 5 个合法但显示名不合格的节点被安全改名，definition 不改写；
- 4 个 definition 尾部含 OCR/页脚/断公式污染的节点被安全裁剪，核心 claim
  保留；
- 4 个 label/definition 主题错配或悬空片段进入 reextract；
- 只有 name 与 definition 都不可恢复的真正坏节点整删；
- critic 与 normalize 使用相同 disposition，避免一个阶段保留、下个阶段又按
  另一套规则误杀。

离线 solved graph 的最终字段审计为：

```text
invalid published labels: 0
invalid explicit definitions: 0
```

需要注意，历史 14 个“合法字段门目标”中有 12 个来源是旧
`coverage_*` 自动补点。当前 pipeline 已禁止把原始 export unit 机械补成正式
节点，所以它们在 checkpoint 回放中没有 lineage，不等于相应知识永远应该
缺失。正式新 Branch 生成必须用 source-gold 检查这些知识是否由新的、干净的
explicit candidate 重新覆盖。

### 18.6 拓扑、工程 coverage 与 source-gold 的边界

最终确定性结果：

| 指标 | 结果 |
| --- | ---: |
| normalized nodes | 131 |
| normalized parent candidates | 255 |
| normalized cross-links | 42 |
| solved nodes | 110 |
| tree edges | 109 |
| solved cross-links | 38 |
| reachable | 110 / 110 |
| invalid tree endpoints | 0 |
| invalid cross-link endpoints | 0 |
| duplicate graph IDs | 0 |
| solver | OPTIMAL |
| canonicalize + normalize + solve | 2.900720 秒 |

`coverage_statistics()` 在这个回放中的 solved weighted coverage 为 50.79%。
它不能与人工 Required Coverage 76.70% 直接比较，原因是：

- 当前 matcher 比 v4 生产时更严格；
- replay 复用历史 evidence/unit identity，只覆盖确定性后处理；
- 它不会重新调用 Branch 模型生成被旧 `coverage_*` 补点替代的合法 claim；
- source-gold 与工程 unit coverage 的分母、权重和判定规则不同。

source-gold lineage audit 也只回答“旧人工匹配节点的 lineage 是否仍存在”，
不是对新节点语义重新打分：

- 50 个有权重 gold 中，40 个仍有 solved lineage；
- 这些 lineage 对应的历史加权得分为 53.5 / 88；
- H04、L13 等原本缺失项不会被纯后处理凭空生成；
- A02、L03、L04、L18、L19 等 lineage 缺口必须在完整新生成后重新核对，
  不能因为垃圾节点被删除就视为覆盖改善。

因此当前回放同时证明两件事：

1. 公式硬错、字段污染、重复和图结构可以由确定性代码独立改善；
2. 仅清洗历史候选不能补回缺失知识，也不能证明子节点业务准确率已经达标。

### 18.7 仍然明确存在的内容与结构风险

即使历史弱 oracle 显示 15/15，以下问题仍未被这次零模型 replay 解决：

1. 4 个历史 nonclaim noise 中仍有 1 个“能级示意图”作为独立节点存活；
2. He–Ne 共振转移、粒子数反转与光学谐振腔等历史错挂 lineage 仍可能存活；
3. replay 沿用历史 verified parent candidates，没有重新执行当前 4-child
   verifier batching，因此不能评价新父边准确率；
4. H04、L13 和其他缺失 gold 需要 Branch 重新生成，确定性后处理无法补造；
5. 18 个历史 partially-supported claim 不能只按“lineage 还在/不在”判断
   当前 claim precision；
6. “能级示意图”、空泛公式图和少数视觉 caption 仍需更强 visual semantic
   action 或 publish review；
7. 没有 embedding/reranker、跨 branch reassignment、直接父边人工金标，
   7 个历史错挂问题尚无完整算法闭环。

这些残余分别属于视觉知识资格、生成召回、父边语义、评测和架构能力，不应被
压缩成一句“C+ 尚未完整”，也不应因为 110 节点拓扑合法而被忽略。

### 18.8 第 2～5 项的最新独立代码/算法归因

| 用户问题 | 最新确定性证据 | 当前直接根因/修复 | 仍需生产验证 |
| --- | --- | --- | --- |
| 2. 约 30 分钟 | v4 为 17:02.77；verify 477.89s/202 calls，branches 354.85s；当前本地 parser 2.12s、确定性后处理 2.90s | 历史瓶颈是远端 Branch/verifier 长尾和物理 HTTP 数；已实现低 reasoning、动态 token、单次 timeout/attempt、4-child verifier batching | 新镜像整份 92 页 wall、verify HTTP batch 数、stage duration；stage deadline、熔断和 leaf checkpoint 仍未实现 |
| 3. 文字截断/摘点 | p85/p86/p88/p92 数学锚点全恢复；2 个硬错拒绝；3/4 历史垃圾移除；最终非法 label/definition 为 0 | PUA 映射、堆叠分式恢复、claim hard gate、字段 typed disposition、visual attach/defer 状态分别负责 | “能级示意图”仍漏过；新生成是否再次产生空泛视觉/残句需逐节点审查 |
| 4. PNG 重叠 | v4 生产字体布局 22/22、最小间距 32px、right/right/right/left/left | 旧 360°、无真实框、无 subtree extent/AABB 消解；right-first 与字体感知框已独立修复 | 新 110～150 节点正式 export 仍需同一字体 SHA 的 22/22；唯一持久化 LayoutResult 尚缺 |
| 5. 子节点准确性 | 2 个严重错误在历史候选上确定性拒绝；15 duplicate 中 14 个合并/移除；0 潜在 gold 误并；但仅 40/50 weighted gold 有 solved lineage | 公式/量纲、字段污染、evidence 对齐、semantic dedupe 已分别修；缺失 claim、部分支持和错挂仍由 Branch 召回、视觉资格、父边 verifier/reranker 和 source-gold 负责 | 必须对完整新输出重算 Required Coverage、Claim Precision、Evidence Alignment、父边 P/R/F1；不得用 engineering coverage 或 topology 代替 |

这个矩阵再次满足用户的约束：第 2～5 项都有独立可复现、可测试、可修复的
直接根因；第 1 项“架构尚未完全一致”只描述能力上限，不是它们的共同免责
理由。

## 19. 2026-07-26 PDF 单页多模态严格转录转向

### 19.1 为什么旧 15/15 必须撤销

旧离线 replay 的公式断言不是 canonical 公式 oracle：

- p88 只要求同页同时存在 `N=` 与 `≈8`，即使
  `N=Δν/Δν_k=1.3×10^9/≈8` 或分母缺失也可能通过；
- p92 只要求若干数字和单位出现，不能证明强度、功率、温度分别绑定到正确
  量纲，也不能发现指数符号遗漏；
- p84/p85 的正负号、p86 的下标和若干残缺分式没有被全页逐式比较。

因此历史“15/15 PASS”只证明弱锚点出现，不能证明公式恢复正确。本文第 17、
18 节中所有把 15/15 当作公式质量终态的表述，均由本节覆盖。

新的代码级 oracle 对以下 canonical 文本逐项、逐页、完整相等，不再用零散
锚点拼接：

```text
p84 ν=c/λ=3×10^8/(0.6328×10^-6)≈5×10^14
p85 Δν/ν=1.3×10^9/(5×10^14)≈3×10^-6
p86 nL=kλ_k/2
p86 λ_k=2nL/k
p86 ν_k=c/λ=kc/2nL
p86 Δν_k=c/2nL
p88 N=Δν/Δν_k=1.3×10^9/(1.5×10^8)≈8
p92 非聚焦状态 I>10^11 W/m²
p92 聚焦状态 I>10^17 W/cm²
p92 峰值功率可达 10^14 W
p92 对应温度约 10^8 K
```

该 oracle 已进入自动化测试，但它目前是 schema/质量门的代码级验收，不是
新模型对真实 92 页 PDF 的生产准确率证明。

### 19.2 负指数跨字体 token 的确定性根因

`10^-6` 的负号和数字可能来自相邻、字号相同但字体名不同的 PDF token。旧
几何恢复按字体切分上标簇，导致负号单独成簇并在拼接时丢失，最终得到
`10^6`。当前几何层允许满足几何邻接、基线和小字号条件的跨字体 token 合并，
并由 `test_geometry_math_gate_keeps_signed_power_and_rejects_malformed`
锁定 `10^-6` 保留、`10^6` 拒绝。

同一轮全页几何审计把已知不完整的 p10/p27/p33/p49/p67/p72 候选过滤掉；剩余
候选只作为诊断证据。几何层仍不具备扫描件 OCR、矩阵、多行公式、积分上下限
和通用公式视觉识别，因此不能继续承担生产正文恢复职责。

### 19.3 新的生产输入合同

已批准并实现的主路径为：

```text
PDF
  -> Poppler 按配置 DPI 渲染全部页面
  -> QWEN_VISION_MODEL 每页独立 PageExtraction JSON
  -> canonical 公式、页码、bbox、PUA、完整性和置信度质量门
  -> 仅接收页进入 ParsedDocument/chunks/Content Units
```

关键隔离规则：

- 公式块必须同时包含 canonical `text` 和 `latex`；
- 页级 input hash 包含 source SHA、page、image SHA、prompt/schema、
  provider 和 model；
- 已接收页可幂等复用，失败页只在本页范围内重试；
- 失败、缺页或低置信页不静默使用旧 parser 文本；
- 失败页从模型输入移除，并标记
  `[pdf_transcription_degraded:page_failure]` /
  `pdf_page_transcription`，阻止发布；
- `pdfplumber` 几何候选只写入 `pdf_geometry_math` 审计元数据，
  `injected_into_text=false`。

上游方案检索没有在私仓或 Qwen3-VL issue/PR 中找到可直接采用的“PDF 单页到
本项目 PageExtraction”实现。当前最小本地适配复用
[Qwen3-VL](https://github.com/QwenLM/Qwen3-VL) 的 Apache-2.0
OpenAI-compatible `image_url` 模式、现有 Provider 客户端、Poppler 渲染和
SQLite checkpoint，没有引入新的生产依赖。

### 19.4 当前 Qwen 端点与分页并发实测

以下是 2026-07-26 Token Plan 的历史技术实验，不是当前生产资格结论。该凭据
的 `/models` 当时可见：

```text
qwen3.8-max-preview
qwen3.7-max
qwen3.7-plus
qwen3.6-flash
```

没有名称包含 `vl`、`vision` 或 `ocr` 的模型，配置中的
`qwen3-vl-plus` 不可用。但真实 p88 页面证明 `qwen3.8-max-preview` 接受
OpenAI-compatible `image_url`，20.047 秒返回完整 `PageExtraction`，页面完整
度与置信度门通过，并恢复：

```text
Δν = 1.3 × 10^9 Hz
N = Δν / Δν_k = (1.3 × 10^9) / (1.5 × 10^8) ≅ 8
```

192 DPI、单次尝试、180 秒请求超时的真实页面并发探测结果：

| 并发 | HTTP 200 | 质量门通过 | wall | throughput | HTTP p95 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1/1 | 1/1 | 24.54s | 2.45 页/分 | 24.54s |
| 2 | 2/2 | 2/2 | 19.70s | 6.09 页/分 | 19.14s |
| 4 | 4/4 | 4/4 | 22.07s | 10.87 页/分 | 21.72s |
| 6 | 6/6 | 6/6 | 34.55s | 10.42 页/分 | 33.11s |
| 8 | 8/8 | 8/8 | 28.69s | 16.73 页/分 | 28.05s |
| 12 | 12/12 | 11/12 | 36.46s | 19.75 页/分 | 35.69s |

所有档位均无 429、超时或传输错误，所以观察到的传输容量至少为 12。并发 12
已有一页被质量门拒绝，最高“HTTP 与内容质量全通过”档位为 8；当前生产候选
因此把页级并发和 Provider 并发均设为 8。该容量结论必须使用标准 DashScope
正式凭据重新验证，不能直接用于公网自动化基线。

### 19.5 92 页隔离分页转录结果

使用同一 92 页 PDF、`qwen3.8-max-preview`、192 DPI、页并发/Provider 并发
均为 8、最多两次页级尝试：

| 指标 | 结果 |
| --- | --- |
| render | 42.712s |
| transcription | 282.687s |
| total | 325.399s |
| throughput | 19.527 页/分 |
| HTTP attempts | 107 |
| HTTP success | 107/107 |
| 429 / timeout / transport error | 0 / 0 / 0 |
| page retries | 15 |
| accepted pages | 80/92 |
| HTTP p50 / p95 / max | 17.890s / 40.610s / 50.353s |
| token usage | prompt 309113 / completion 168143 / total 477256 |

失败页为：

```text
17, 18, 21, 29, 30, 32, 34, 35, 42, 47, 62, 87
```

拒绝原因包括 schema `ValidationError`、`trailing_layout_punctuation`、
`orphan_fraction_suffix` 和 `missing_relation_operand`。质量门没有为提高
通过率而放宽。

逐式审计结果：

- p84 的 `Δν≈1.3×10^9 Hz` 和含 `10^-6` 的频率公式正确；
- p85 的 `Δν/ν≈3×10^-6` 正确；
- p88 的完整纵模数公式正确；
- p86 恢复 `nL=kλ_k/2`、`λ_k=2nL/k`，但仍缺 `ν_k`、`Δν_k` 目标式；
- p92 只把部分 B 相关表达识别为公式块，四个强度/功率/温度目标未全部恢复。

因此本次分页转录 `complete=false`。它证明 8 路全页转录在约 5 分 25 秒完成，
但不能宣称公式 100% 准确或页面完整。

### 19.6 当前仍不能晋级生产的门

这次转向解决的是“残缺 parser/几何公式进入模型输入”的确定性风险，不等于
92 页完整生产验收已经完成。当前生产启动会 fail closed 拒绝 Token Plan/
Coding Plan key 或 endpoint、`preview` 模型、无效 HTTPS endpoint、非 Qwen
模型和 text-only 视觉模型。正式重跑必须使用标准 DashScope endpoint、正式
Qwen 文本/视觉模型及相应凭据。其余门保持不变：

1. 新任务 manifest 已设计为记录脱敏端点、两个模型、页转录参数，以及
   Python、pypdf、pdfplumber、pdfminer.six、Poppler、git 和镜像版本；
2. 本节记录时最新已构建的是 v48 镜像
   `sha256:66dfb6abf5bb98e064b885224c480ef79513afe016e117aa1c9a07023ad013cd`
   已完成镜像内 493/493、生产配置 fail-closed/pass、桌面/移动浏览器、
   容器重启和恢复卷隔离运行态验证；它仍缺标准正式凭据的真实文本/视觉调用
   和 26/92 页生产结果；
3. `backend.tools.production_backup` 已完成一次隔离
   `freeze -> prepare-volumes -> cutover -> rollback` 全流程演练。备份
   manifest SHA-256 为
   `f6f40741c433f771cb7e85e59c9f8084f0a3d728aef8d7dfb2bde4fb19f7c6b1`，
   候选和回滚后的 history、job、PNG 均与停写前基线逐字节一致。v4 rollback
   tag 已建立，但这不是公网真实停写、备份或切换；
4. 新的完整 92 页生产 task/run 尚不存在，节点/父边准确率、去重和 PNG 指标
   均不能宣称达标；输入转录虽低于 12 分钟，但 80/92 不满足完整性门。

本节记录时的正式执行顺序收敛为：使用 v48 和标准 Qwen 凭据做实际模型预检及 26 页
canary/盲测，再阻断公网新写入，进入真实停写窗口并制作最终一致性备份，使用
已验证工具切换，完成公网鉴权、历史和导出检查，最后从上传开始重跑 92 页并
重新人工审查。

### 19.7 16 页 `layout_nodes` canary

第 19.5 节的 80/92 是第一次严格 `PageExtraction` 的历史结果。随后对 16 个
跨学科、高公式风险页面运行了 `dots` 布局转录加节点选择 canary；它是更新的
选页质量证据，但没有覆盖完整 92 页：

| 指标 | 结果 |
| --- | --- |
| 页面 | 17、18、21、29、32、34、35、42、47、62、84、85、86、87、88、92 |
| stage / concurrency | `layout_nodes` / 4 |
| wall | 262.733s |
| canonical formulas | 58/58 |
| Required Coverage | 32/32 |
| nodes / duplicates | 87 / 0 |
| HTTP attempts | 36 |
| HTTP success / timeout | 36 / 0 |
| HTTP p50 / p95 / max | 22.957s / 40.002s / 87.996s |
| tokens | prompt 65,819 / completion 62,385 / total 128,204 |

artifact SHA-256 为：

```text
9a29294114202cc7e5004178bd9c587059f042bccb8f9decb7281dac71c65e8c
```

按当前三态函数：

- 13 页为 `accepted`；
- p17、p32、p35 为 `degraded`，因为节点选择两次未通过质量门后使用
  `node_selector_deterministic_fallback`；
- 0 页为 `failed`，页面完成度为 16/16。

三页 fallback 输出仍达到对应 canonical 公式和 Required Coverage 100%，但
不能据此洗成 clean model success。p35 独立单页复测为 clean `accepted`，
74.336 秒、6/6 公式、2/2 Required Coverage、11 节点、0 duplicate；artifact
SHA-256 为
`9b40e30671f40f8c6b045161f1b6384dc91f74a4d5749407a444b9f10dbd798b`。
同一页在四路运行中降级，说明 selector 输出仍有运行间波动。p47 在四路运行
中第二次节点选择通过，最终 clean accepted。

这轮所有 36 次 HTTP 均为 200/stop，没有 429、timeout 或传输错误。因此三页
降级不是网络失败，而是节点选择返回内容未通过确定性质量门。当前实现正确地
保留了失败尝试和 fallback 标记，尚未解决 selector 稳定性。

这轮 canary 中，所选 p86/p87 的驻波关系和 p92 的强度、功率、温度目标均
通过完整 oracle。它纠正了“这些目标仍无法由新链路恢复”的当前质量判断，但
不改写第 19.5 节那次旧运行确实失败的历史事实，也不能外推为完整 92 页、
最终节点、父边、去重、PNG 和总 SLA 已通过。

### 19.8 是否形成了面向答案的 prompt 修补

当前任务硬约束禁止为了开发集转绿，在生产 prompt 或代码中加入页面特定、
答案特定、benchmark 特定、单学科或单版式专用修复。canary 答案只能存在于
评测层，不能被生产模块导入或用于运行时条件分支。

审计结论不是无条件的“从未发生”，而是发现并消除了一处边界漏洞后，当前实现
符合“答案只在评测层”的合同：

1. 旧 `PDF_PAGE_TRANSCRIPTION_PROMPT` 曾用精确示例要求不得把 `10^-6`
   写成 `10^6`。它没有页码分支，但与 canary 目标重合，会污染“prompt 完全
   不含 benchmark 答案”的结论。现已改成通用的“不得把负指数误写为正指数”。
2. 58 个公式和 32 个 Required Coverage 文本只保存在
   `backend/tools/pdf_layout_ab.py` 和测试，不被生产模块导入。
3. 生产确定性修复只接受通用、可解释的规则：受支持 LaTeX 命令转换、复合
   上下标保留、`ħ` 字形归一、数值上下文中的单位下标修复，以及同时存在频率
   单位和同页 `ν` 证据时的 `Δv -> Δν`。`~` 与 `∼` 只在 evaluator 中按格式
   等价处理，不要求模型复现单一字形。
4. 自动化测试现扫描全部生产 prompt，拒绝 canary 完整答案和关键 benchmark
   片段；AST 测试拒绝生产模块导入 canary oracle，也拒绝针对 16 个 canary
   页码写条件分支。
5. p17/p32/p35 fallback 被明确降级，模型输出未通过质量门时不再通过确定性
   结果洗成 clean acceptance。

GitHub-first 检索采用了
[dots.ocr 的布局 prompt 合同](https://github.com/studio-dots-ai/dots.ocr/blob/master/dots_ocr/utils/prompts.py)，
并参考其
[公式幻觉已知限制](https://github.com/studio-dots-ai/dots.ocr/issues/151)
保留严格质量门；LaTeX 解析使用维护中的 MIT
[pylatexenc](https://github.com/phfaist/pylatexenc)，固定为 2.11。对
`benchmark leakage prompt evaluation`、`do not contain canary answers`
等 GitHub issue/PR/code 查询没有找到可直接适配本仓库的维护实现，因此采用
上述最小本地测试合同，没有引入新的提示词框架。

据此，当前逐点补齐不是“看到 p84/p92 的答案后把答案写进生产 prompt”，而是
把开发集暴露出的通用解析类别固化为解析、质量门和 evaluator 规则。仍需坚持
开发 canary、校准集和盲测集分离；16 页全绿本身不能证明未对开发集过拟合，
只有未见过学科和版式的盲测结果才能继续支持该结论。

### 19.9 一致性备份与切换演练暴露的运维根因

第一次隔离 cutover 使用宿主端口 `18094`。该端口实际被 `sshd` 监听，Compose
已经创建候选容器后才在启动阶段返回 address already in use；随后候选进入
`Removal In Progress`，旧隔离容器保留在回滚名称下。公网 `5173`、v4 容器和
生产 volumes 全程未改动。

GitHub-first 检索结果：

- Docker Compose
  [#4950](https://github.com/docker/compose/issues/4950) 记录固定宿主端口被
  非 Docker 进程或其他容器占用时的相同失败形态，并要求先检查系统监听状态；
- Moby [#45510](https://github.com/moby/moby/issues/45510) 与
  [#36679](https://github.com/moby/moby/issues/36679) 记录删除失败后容器可能
  暂时或持续显示 `Removal In Progress`；
- Compose
  [#13630](https://github.com/docker/compose/pull/13630) 在测试场景通过随机
  宿主端口规避冲突，但正式公网端口必须固定，不能直接采用该策略。

上游没有提供可直接复用的“固定生产端口预检 + 保留旧容器 + 恢复卷 + 自动回滚”
实现，因此本仓库采用最小标准库适配：

1. `cutover` 在重命名旧容器前用 TCP bind 实际探测目标宿主地址和端口；
2. Docker inspect 只把明确的 `No such container/image/volume/object` 视为
   不存在，daemon 异常不再被吞掉；
3. `created/exited` 候选使用普通 `docker rm`，运行中候选才使用
   `docker rm --force`；
4. 删除命令即使返回 removal-in-progress，只要后续 inspect 确认名称释放，
   回滚仍继续；等待有 15 秒截止时间，不会无限卡住；
5. 保留容器的 image ID 在删除候选前验证，避免错误回滚镜像导致先破坏候选；
6. Compose candidate 固定使用 `--no-build`，恢复 volumes 必须带匹配的备份
   manifest SHA-256 与 data/uploads 角色标签。

回归测试覆盖端口冲突发生在 rename 前、created-state 普通删除、删除竞态后名称
释放、Docker daemon 错误不得伪装成 not-found。当前备份/部署/安全聚焦套件
48/48、宿主全量 379/379、v12 镜像内 379/379 均通过。

第二次完整隔离演练使用空闲端口 `18107`，结果为：

- freeze 后源容器 `restart=no` 且停止；
- SQLite online backup、assets/uploads/data-files 快照和 quick_check 通过；
- 候选 volumes 的 role 与 manifest SHA 标签匹配；
- candidate health、history、job、PNG 通过；
- 回滚后原 volumes、原端口和容器名恢复；
- history SHA-256
  `3b8d6fa4e04e6a0719f037b5f2fa9e267b3f49d6b625929ae8e5d62164057f16`、
  job SHA-256
  `50e9f90bc6fd06891a87be24d324de645796e2afbd2581ce0920e4c497ddeee0`、
  PNG SHA-256
  `dd0fb2f21173e4535845ccd349c598ee826134da9f58772078bfc3ddb772f98d`
  在切换前、候选和回滚后三次一致。

这证明仓库内备份/切换/回滚机制、v11 恢复卷兼容性和 v12 隔离运行时已通过，
不等于 v12 恢复卷/PNG 复验、公网停写窗口、公网切换或 92 页正式生产重跑已
完成。

### 19.10 宿主 default Docker bridge 缺失

构建 v12 时，普通 `docker build` 在 pip layer 创建 BuildKit 端点失败：

```text
adding interface ... to bridge docker0 failed: Device does not exist
```

Docker network metadata 仍声明 default bridge 名为 `docker0`，但宿主
`ip link` 已找不到该接口。GitHub-first 检索中，Moby
[#42558](https://github.com/moby/moby/issues/42558) 记录了相同现象：宿主
网络管理服务可能移除 Docker bridge，Docker 元数据却仍保留旧网络；上游维护者
将其归为外部网络管理冲突，而不是应用或 Dockerfile 缺陷。

本轮没有重启 Docker，也没有重启或替换公网 v4。v12 使用
`docker build --network=host` 完成构建。随后创建临时自定义 bridge、接入
v12 容器并删除网络均通过；v12 还在该自定义 bridge 上以
`127.0.0.1:18113 -> 8000` 完成 health 200 和 API 401/200 探针。因此目前
证据表明：

1. default bridge 构建路径仍损坏；
2. Docker 自定义 bridge 和 Compose-like 端口映射可用；
3. 正式切换前仍必须让 Compose 创建隔离项目网络并完成候选启动预检；
4. 不能把 `--network=host` 构建绕行描述为宿主 `docker0` 已修复。

### 19.11 `direct -> layout_nodes` 失败页级生产级联

2026-07-28 的 v40 26 页 direct canary 为 17/26，失败原页为
`17,20,34,44,52,71,78,79,80`。56/56 次 Qwen 调用均完成，墙钟
244.219 秒；这组失败主要是严格内容门拒绝，不是 Provider 传输失败。

对上述 9 页单独运行现有 `layout_nodes`：

- p17、p20、p34、p44、p52、p78、p79、p80 为 clean accepted；
- p71 failed；
- 23 次 HTTP attempt，墙钟 371.275 秒；
- layout canonical formula 与 Required Coverage 均为 100%。

p71 又在独立 direct 诊断中 clean accepted。因此两条 profile 的失败集合具有
互补性，但这些不同 run 的结果不能人工拼成 26/26。生产需要一次可审计的统一
orchestration。

GitHub-first 检索：

- Apache-2.0
  [Guardrails `merge_reask_output`](https://github.com/guardrails-ai/guardrails/blob/35c87e910daefe707f7e25916e6d5cf1d4fd3149/guardrails/actions/reask.py)
  按原失败 path 回填 repair，适用于固定结构；本仓库节点列表可变长、可重排，
  不能按列表位置直接采用；
- Pydantic
  [#10748](https://github.com/pydantic/pydantic/pull/10748)
  的 partial validation 只忽略截断输入的最后一个 collection item，不能处理
  任意位置的无效节点；
- Qwen3-VL
  [#1652](https://github.com/QwenLM/Qwen3-VL/issues/1652) 和
  [#761](https://github.com/QwenLM/Qwen3-VL/issues/761)
  说明严格结构输出依赖推理后端约束，单靠 prompt 不能保证 schema；
- Apache-2.0
  [olmOCR 页级 fallback](https://github.com/allenai/olmocr/blob/8854eda39eea58eab2724e84ad3cd0994f3b31cf/olmocr/pipeline.py)
  对失败页局部兜底，并显式记录 fallback page 数和文档级失败门。

没有找到可直接替代本仓库双 profile checkpoint、质量门和节点证据合同的维护
实现。因此采用最小仓库原生编排，没有增加生产依赖，也没有复制外部代码：

1. 新增 `direct_layout_fallback`，先运行完整 direct；
2. 只把 direct `failed_pages` 交给 `layout_nodes`；
3. 保留 `page_knowledge:NNNN` 与
   `page_knowledge:layout_nodes:NNNN` 两套 checkpoint；
4. 按原页号合并 extraction，恢复页不再保留 direct 失败告警；
5. metadata 记录 direct/fallback attempted、accepted、failed、called、
   reused 与最终 clean/degraded/failed 页面；
6. layout 未恢复页面继续使 `complete=false`；
7. `node_selector_deterministic_fallback` 页面保留内容但写入
   `degraded_pages`，C+ `degraded_components` 和 publish gate 必须失败。

当前任务强约束禁止为了开发集转绿，在生产 prompt 或代码中加入页码、答案、
benchmark、单学科或单版式专用分支。本轮没有修改 prompt，没有放宽公式、
evidence、bbox、置信度或 selector 质量门；新增测试使用通用两页夹具验证级联
范围、checkpoint、失败语义和 degraded 传播。

截至本节：

- 宿主后端全量 471/471；
- PDF/Qwen/生产配置聚焦套件 89/89；
- 前端 7/7、typecheck、production build、Compose config、compileall 和
  `git diff --check` 通过；
- v40 镜像内 463/463 是本轮修改前证据，不能晋级；
- 该截点之后已继续构建至 v45；当前资格结论由 19.12 节覆盖。

### 19.12 标准 Qwen 生产资格与独立视觉模型合同

2026-07-28 对生产模型合同继续审计时发现：工作树虽然已把默认文本模型改为
`qwen3.7-max`，但未显式设置 `QWEN_VISION_MODEL` 时视觉角色仍跟随文本模型。
这会把页图发送给 text-only 模型，`/models` 存在性检查也无法证明其支持图片。

GitHub-first 检索采用了 Apache-2.0 的 QwenLM/qwen-code 上游结论：

- [PR #4803](https://github.com/QwenLM/qwen-code/pull/4803) 将
  `qwen3.7-plus` 标记为 image/video，并明确 `qwen3.7-max` 为 text-only；
- [PR #5778](https://github.com/QwenLM/qwen-code/pull/5778) 将文本主模型与
  独立视觉模型分离，并对 text-only 视觉选择 fail closed；
- [PR #6072](https://github.com/QwenLM/qwen-code/pull/6072) 说明 Qwen/
  DashScope 使用 `enable_thinking`/`thinking_budget`，而不是把统一的
  `reasoning_effort` 原样发送给 Qwen 3.7。

当前最小仓库适配为：

1. 本地默认文本模型固定为 `qwen3.7-max`，默认视觉模型固定为
   `qwen3.7-plus`，不再隐式共用；
2. 生产资格门复用上游 modality pattern，未知视觉型号默认 text-only；
3. 生产启动拒绝 `sk-sp-` Token Plan key、Token Plan/Coding Plan endpoint、
   `preview` 模型、无效 HTTPS endpoint、非 Qwen 模型及 text-only 视觉模型；
4. 结构化 Qwen 调用使用有界 `thinking_budget` 和
   `max_completion_tokens`，不再由内部流水线发送 Qwen 3.7 不支持的
   `reasoning_effort=low`；
5. run manifest 继续记录脱敏 endpoint、文本/视觉模型和运行时版本；模型列表
   检查仍不是图片能力 canary，正式凭据必须用真实页面验证。

本节完成时最新已构建的是 v48 镜像
`sha256:66dfb6abf5bb98e064b885224c480ef79513afe016e117aa1c9a07023ad013cd`
已包含上述合同并完成镜像内 493/493。本节完成时宿主后端 493/493、前端 7/7、
typecheck、production build、Compose config、compileall 和
`git diff --check` 均通过。

Token Plan 与 `qwen3.8-max-preview` 的历史并发/canary 结果仍可说明协议兼容
和当时容量，但不能作为自定义应用后端的生产资格或正式 26/92 页重跑基线。
下一阶段外部前置条件是标准 DashScope 正式凭据，以及该凭据对
`qwen3.7-max` 和 `qwen3.7-plus` 的实际访问权限。

### 19.13 v47 镜像合同与隔离运行态

v46 镜像已经包含 19.12 的模型合同，但镜像内完整后端套件出现 5 个 error：
`test_secret_preflight_tdd.py` 需要读取 `/app/compose.prod.yml`，随后同一部署
合同类还会读取 `/app/Dockerfile`，而运行镜像只复制了 `backend/` 和前端产物。
这不是业务断言失败，也不能通过 skip 或放宽 oracle 处理。

GitHub-first 搜索覆盖当前私有仓库远端、Moby BuildKit issues/PR、Docker docs
和公开代码中的 `compose.prod.yml`/Dockerfile COPY 用法，没有找到与本仓库
“镜像内完整测试必须验证根部署合同文件”相匹配的现成实现。最小修复是在
Dockerfile 中显式把无密钥的 `Dockerfile`、`compose.prod.yml` 复制到
`/app`，继续让镜像内测试检查真实生产合同。

重建结果：

- tag：`zlb-mindmap-agent:candidate-v47-20260728`；
- image ID：
  `sha256:ea43fcab70850875702032f3c96d42e487f389f9ad2b628c27ef514c2c0b34b4`；
- 镜像内完整后端：493/493；
- `pip check`、非 root `10001:10001`、只读合同文件和前端产物读取：通过；
- Python 3.12.13、pypdf 6.14.2、pdfplumber 0.11.10、
  pdfminer.six 20260107、pylatexenc 2.11、Poppler 25.03.0。

配置与隔离结果：

- Token Plan key/endpoint 加 preview 模型时，配置函数和实际 Uvicorn 生产启动
  均非零退出，错误不包含占位 token；
- 标准 DashScope endpoint、`qwen3.7-max` 文本模型和 `qwen3.7-plus` 视觉
  模型的占位配置通过静态资格门；
- 空内容临时 secret 仅用于验证 `root:10001 0440` metadata preflight；
- `zlb-v47-isolated-20260728` 使用全新数据卷、上传卷和
  `127.0.0.1:18135`，通过 read-only rootfs、cap drop、no-new-privileges、
  CPU/内存/PID、API/engine/asset 鉴权及 session 注销检查；
- 一个 `use_ai=false` 文本任务完成，容器重启后 history/job 仍可读取，
  JSON/PNG 导出返回 200。

这些结果证明 v47 的镜像和无模型运行时合同，不证明标准 Qwen 凭据可用，也
不证明真实 PDF 的公式、节点、父边、去重、耗时和 PNG 指标。公网 v4 容器和
5173 端口在本节验证中未重启、未替换。

### 19.14 v48 登录边界、浏览器 E2E 与恢复卷兼容

v47 生产形态隔离实例暴露了一个独立于 Qwen 能力的部署阻断：前端
`authenticate()` 依次等待 `createSession()` 和 `getModels()`，直到两个请求
都成功才设置 `authenticated=true`。因此有效 session 已由后端签发后，只要
模型枚举因占位 endpoint、Provider 波动或权限不足返回 502，前端 catch 就会
把用户退回鉴权卡；历史、已有任务和 `use_ai=false` 工作流都不可达。

GitHub-first 搜索覆盖当前私有仓库的 issue/PR/code、公开
`createSession/getModels` 模式和 Playwright 上游。没有找到与本仓库同构、
可直接移植的认证实现；浏览器回归采用 Apache-2.0 的
[Playwright v1.62.0](https://github.com/microsoft/playwright/releases/tag/v1.62.0)
及其
[官方 Docker 运行方式](https://github.com/microsoft/playwright/blob/974edd3feb4adbbfca6ca741adf205cf87df2282/docs/src/docker.md)。
最小修复保持会话与模型能力发现为两个独立事实：

1. `createSession()` 成功后立即确认 authenticated 并清空输入 token；
2. `getModels()` 改为异步能力发现，成功时刷新列表，失败时保留默认模型并把
   模型状态标记为“模型列表不可用”；
3. session 请求本身失败仍 fail closed；
4. 移动端隐藏按钮文字后，历史和 JSON 导出链接使用稳定
   `aria-label/title`，浏览器测试只点击真实可见交互元素。

RED 证据来自未修复 v47 前端：Playwright 的 Desktop Chrome 和 Pixel 7
项目都在模型列表 502 后发现鉴权卡仍可见，2/2 失败。修复后的当前源码和 v48
生产镜像均覆盖：

- session 成功、模型列表 502 不撤销会话；
- 历史按钮与抽屉可用；
- `use_ai=false` 示例任务完成并显示画布；
- JSON 与 PNG 触发真实浏览器下载并校验内容/文件头；
- 桌面和移动页面无横向溢出。

v48 镜像证据：

- tag：`zlb-mindmap-agent:candidate-v48-20260728`；
- image ID：
  `sha256:66dfb6abf5bb98e064b885224c480ef79513afe016e117aa1c9a07023ad013cd`；
- frozen-lock 安装、原始 `pnpm build`、镜像内 493/493、`pip check` 和
  `compileall`：通过；
- `Config.User=10001:10001`、read-only rootfs、cap drop、
  no-new-privileges、3 GiB、2 CPU、256 PIDs：通过；
- `zlb-v48-isolated-20260728` 位于 `127.0.0.1:18136`，使用
  `root:10001 0440` 的一次性 age 加密占位 secret，通过 API/engine/asset
  fail-closed 和模型 502 无凭据泄漏探针；
- 生产镜像在容器重启前后均完成桌面/移动 2/2 E2E。

恢复卷实例 `zlb-v48-history-20260728` 位于 `127.0.0.1:18137`，挂载从 v4
非最终演练备份恢复的专用卷。验证结果为 SQLite `quick_check=ok`、3 个 jobs、
10 个 runs、8 个 graph versions、339 个 model calls、999 个资产
（152295421 bytes）、空 uploads；历史 API 返回 10 条，其中 8 条包含可导出
图版本。同一旧图的 JSON 和 PNG 在容器重启前后 SHA-256 一致。

这些证据关闭了“模型列表故障阻断有效 session”和“v48 无法读取 v4 恢复卷”
两项候选部署风险，但不等于正式生产完成。标准 DashScope 正式凭据的文本/
视觉实际调用、同一次 26 页 canary、真实停写窗口内的最终一致性备份、公网
切换与 92 页完整 task/run 仍未执行。公网 v4 容器和 5173 端口在本节验证中
未重启、未替换。

### 19.15 v49 canary manifest 可复现性与磁盘缓存边界

部署前审计发现正式任务 manifest 已记录脱敏 endpoint、文本/视觉模型、
prompt/schema hash 和 Python/PDF 工具版本，但独立
`pdf_page_knowledge_canary` 的 SQLite run manifest 只记录模型、页集和
extraction profile。这样即使后续 26 页 canary 通过，也不能由 artifact
本身证明它使用了正式 endpoint 和同一生产运行时。布局 A/B artifact 还会
原样写入 `QWEN_BASE_URL`，若 endpoint 带 userinfo 或 query，存在把敏感配置
写入报告的风险。

GitHub-first 搜索覆盖当前私有仓库、Qwen3-VL 官方
[document parsing cookbook](https://github.com/QwenLM/Qwen3-VL/blob/96588727e44c78b25ba03ea03b8e12f7e64fd0da/cookbooks/document_parsing.ipynb)、
Qwen3-VL [#610](https://github.com/QwenLM/Qwen3-VL/issues/610) 和
[#676](https://github.com/QwenLM/Qwen3-VL/issues/676)，以及 Docker 官方
BuildKit cache 文档。上游确认了页图文档解析、结构输出和 bbox 能力边界，
但没有可直接替代本仓库 run manifest 合同的实现。因此复用仓库已有逻辑，
没有修改生产 prompt、页级质量门或新增依赖：

1. endpoint 脱敏和运行时版本采集移入
   `backend.app.runtime_manifest`，正式任务继续通过兼容别名使用同一实现；
2. canary 的 SQLite run manifest 与 JSON 报告写入同一份 provider、
   脱敏 endpoint、文本/视觉模型、credential source、prompt/schema hash、
   并发/重试参数和运行时版本；
3. 布局 A/B artifact 的 `base_url` 与 `provider_endpoint` 都只保存脱敏值；
4. 新增测试证明 endpoint 的 userinfo/query 不进入 manifest，且主服务原有
   manifest 合同保持兼容。

验证结果：

- 宿主逻辑回归 494/494；宿主 `.venv` 实际为 Python 3.11.6，因此不作为
  生产运行时证据；
- v49 tag 为 `zlb-mindmap-agent:candidate-v49-20260728`，image ID 为
  `sha256:851af6cedb23bac039dcf48e0dd5641f02b1f2b3350a2ae2b5e6d4c87986d9b7`；
- 镜像内 Python 3.12.13、494/494、`pip check`、`compileall` 通过；
- `zlb-v49-isolated-20260728` 位于 `127.0.0.1:18138`，满足 non-root、
  read-only rootfs、cap drop、no-new-privileges、3 GiB、2 CPU、256 PIDs；
- 未认证 history 为 401，有效 session/history 为 200；模型列表 502 后
  session 仍有效；
- 一个 `use_ai=false` 任务完成，其 run manifest 记录标准 DashScope 脱敏
  endpoint、`qwen3.7-max`、`qwen3.7-plus`、Python 3.12.13、pypdf 6.14.2、
  pdfplumber 0.11.10、pdfminer.six 20260107、pylatexenc 2.11 和 Poppler
  25.03.0。

磁盘处置只执行了 Docker 官方定义的 BuildKit cache prune，没有执行
`docker system prune`、image/container/volume prune。第一次回收 6.523GB
cache accounting、宿主实际可用空间从约 1.2GB 增至 2.2GB；v49 构建后再次
回收 1.392GB BuildKit cache。v49 镜像、所有旧镜像、45 个容器、83 个卷、
演练备份和隔离 secret 目录均保留。当前可用空间约 1.3GB，仍属于高风险状态，
后续正式 26/92 页运行前需要确保输出与备份空间充足。

本节没有完成真实 Qwen 文本/视觉调用。标准 DashScope 正式凭据、同一次 26 页
canary、正式停写备份、公网可回滚切换和 92 页完整生产 task/run 仍是部署门。

### 19.16 26 页 source-bound 质量门与正式凭据探针

v49 manifest 补齐后继续审计发现：`pdf_page_knowledge_canary` 能证明同一次
运行的页面三态和模型请求策略，但不能在同一总 artifact 中证明 canonical
公式与 Required Coverage。历史 v43 报告把 26 页全部标为 clean；若仍只看
该计数，弱 oracle 会再次让残缺公式假通过。

GitHub-first 搜索覆盖当前私有仓库、Qwen3-VL document parsing cookbook、
QwenLM/qwen-code 的标准 DashScope 配置与多模态 PR
[#6978](https://github.com/QwenLM/qwen-code/pull/6978)、
[#4803](https://github.com/QwenLM/qwen-code/pull/4803)、
[#5778](https://github.com/QwenLM/qwen-code/pull/5778)，以及 Apache-2.0
的 olmOCR 页级外置规则评估实现
([commit ab294c6](https://github.com/allenai/olmocr/commit/ab294c6ab4471f452665484082e01841ca77f263))。
上游通用模式是把页级规则保存在候选输出之外并严格校验页覆盖；没有找到能
直接消费本仓库 `PageKnowledgeExtraction` artifact 的现成实现，因此采用
最小仓库适配，没有增加依赖：

1. 新增纯离线 `backend.tools.pdf_quality_oracle`，统一 canonical 公式和
   Required Coverage 比较；原布局 A/B 工具复用同一实现；
2. 新增 `backend.tools.pdf_page_knowledge_evaluator`，只消费一份 canary
   report 和一份外置 oracle，输出绑定二者 SHA-256 的总评估 artifact；
3. 26 页 source-gold 绑定 PDF SHA
   `a36cf7a439a5d06fe9830e5fa6219836ecc63326ed53903a323bdd4078db54f9`
   和有序选页，包含 53 条完整 canonical 公式、66 条 Required Coverage
   及逐页 `has_knowledge` 断言；每个选页至少有一项非空断言；
4. 评估门同时要求 26 页全部 clean、模型请求策略证据非空且全部匹配、
   credential source 为 age、`direct_layout_fallback`、脱敏 HTTPS endpoint、
   prompt/schema SHA、Python/PDF/Poppler 版本、git/image 身份完整一致；
5. oracle 只位于 evaluator/test fixture；生产 prompt 扫描、AST 页码分支
   扫描和“生产模块不得导入 oracle”测试继续 GREEN。

历史 v43 的同一次 26 页报告回放结果为：

- 页面三态：26/26 clean；
- canonical 公式：44/53；
- Required Coverage：63/66；
- artifact identity：`manifest_missing`；
- evaluator 退出码：2。

其中 p71 的 `W₂₁=B₂₁ρ(ν,T)` 丢失 `ρ`、p52 两个能级表达没有进入
`formula_text`、p82 未保留 632.8 nm 与“红光”的关联、p92 瞬时功率和
`10⁸ K` 未进入公式字段等均保持失败；没有通过页码或答案特化放宽。

本机 `.prod` age 文件的 UID/GID/mode preflight 通过，密文可由 age 正常
加载，但生产配置资格探针返回 `token_plan_key`。探针只输出 credential
source、布尔状态和问题码，没有输出密钥，也没有向标准 DashScope 发出模型
请求。因此当前外部阻断仍是可供自定义后端自动化调用的标准 DashScope 正式
凭据。

独立 canary CLI 原先只检查 key 是否存在，没有复用生产服务启动资格门；
直接运行工具可能绕过 Token Plan/preview 拒绝。当前修复强制
`MINDMAP_ENV=production`，并在解析 PDF、准备页图或发模型请求前调用
`validate_production_qwen_configuration`。使用 `.prod` age 文件和不存在的
PDF 路径做 Python 3.12 实探针时，进程先以 `token_plan_key` 退出，未进入
输入检查。canary runner SHA 写入 manifest；总 evaluator 同时记录自身和
共享 canonical 模块 SHA。

验证结果：

- 新 evaluator/oracle 与 prompt 边界专项：14/14；
- canary manifest、请求策略和生产资格门专项：8/8；
- 既有布局/oracle 回归：88/88；
- 宿主完整后端：507/507；
- 当前 backend 在 v49 的 Python 3.12.13、非 root、read-only rootfs、
  cap drop 和 no-new-privileges 运行形态下：507/507；
- `compileall` 与 `git diff --check`：通过。

本节当时仍未产生正式 Qwen 文本/视觉调用或新的 26 页生产 artifact，因此
没有晋级当时的 v49，也未触发停写、备份、公网切换或 92 页重跑。

### 19.17 v50 统一质量门增量镜像与隔离运行态

19.16 的 evaluator、外置 oracle 和 canary runner 属于部署资格工具，不被
`backend/app` 导入。构建前重新对拍确认当前 `backend/app` 与 v49 镜像内容
逐文件一致，requirements、constraints、Dockerfile 和 Compose 也未变化；
本轮新增文件集中在 `backend/tools` 和 `backend/tests`。宿主只剩约 1.3GB
可用空间，且本次约束禁止删除任何既有镜像、容器、卷、备份或 secret，因此
没有执行一轮会复制完整构建层的高风险全量重建。

GitHub-first 搜索覆盖当前私有仓库、Qwen3-VL document parsing cookbook、
QwenLM/qwen-code 的 artifact/manifest 相关 issue、PR 和代码、Docker Buildx
prune 实现与文档，以及 OCI Image Spec 的
[`org.opencontainers.image.revision`](https://github.com/opencontainers/image-spec/blob/main/annotations.md)
注解。上游没有能直接表达本仓库“固定已验证应用层，只替换离线资格工具和
测试”的现成镜像合同；因此采用最小增量镜像，并显式记录来源：

1. base 固定为 v49 image ID
   `sha256:851af6cedb23bac039dcf48e0dd5641f02b1f2b3350a2ae2b5e6d4c87986d9b7`，
   不依赖可漂移 tag；
2. 只复制 `backend/tools` 与 `backend/tests`，不覆盖 `/app/backend/app`、
   前端产物、依赖或系统包；
3. image labels 记录 OCI revision/base name/base digest，以及仓库自有的
   `backend-app-tree` 和 `overlay.scope=backend-tools-tests`；
4. 当前源码与镜像内 canary runner、evaluator、共享 canonical 模块和
   26 页 oracle 的 SHA-256 逐一一致。

构建与运行证据：

- tag：`zlb-mindmap-agent:candidate-v50-20260728`；
- image ID：
  `sha256:ee373710599ea8526818edd98f88b798cdebfe1acd26b2d955cc83bde77ba5f5`；
- image size：1013636895 bytes；相对 v49 的 unique 增量约 159.3kB；
- `Config.User=10001:10001`，revision 为
  `297da939835dc9b748a33bd80d368702d7de687d-dirty`；
- Python 3.12.13、pypdf 6.14.2、pdfplumber 0.11.10、
  pdfminer.six 20260107、pylatexenc 2.11、Poppler 25.03.0；
- 宿主 Python 3.11.6 逻辑回归 507/507；同一 backend 在 v49/v50 的
  Python 3.12.13、non-root、read-only rootfs、cap drop 和
  no-new-privileges 运行形态下均为 507/507；`pip check`、`compileall` 和
  `git diff --check` 通过。

`zlb-v50-isolated-20260728` 位于 `127.0.0.1:18139`，使用独立数据/上传卷，
满足 non-root、read-only rootfs、cap drop、no-new-privileges、3 GiB、
2 CPU、256 PIDs 和 `restart=unless-stopped`。未认证 history 为 401，
session/history 为 200，模型列表为 502，且 502 不撤销有效 session。
一个 `use_ai=false` 任务 `10dc594affec` 完成；容器重启后历史仍为 1 条，
JSON 为 42784 bytes、SHA-256
`7e866c27789b797fa50f485c3da4d023b3c9ccbe6a29e178688d3a6d15fa2df6`，
PNG 为 29020 bytes、SHA-256
`a2e715c83c03f70855e353ebfa15f79fb530d6da76312367f3a4dd2bf8e44f98`
且 PNG 文件头正确。该结果只证明无模型运行态、持久化和导出，不是实际 Qwen
文本或视觉调用。

为避免读取或转交现有实例 token，同一 v50 image 另以全新已知测试令牌、
tmpfs 数据/上传目录和 `127.0.0.1:18140` 启动临时实例。它保持 non-root、
read-only rootfs、cap drop、no-new-privileges、3 GiB、2 CPU 和 256 PIDs；
Playwright 1.62.0 的 Desktop Chrome 与 Pixel 7 项目均完成 session、模型
列表 502、`use_ai=false`、历史、真实 JSON/PNG 下载、画布可见性和横向溢出
检查，结果 2/2。两个任务均 completed、各 12 节点；桌面截图为
`1440x1000`、SHA-256
`efdd6f1eb2cb20ca939af09bbd0f45a1692345754f86c617a80679a5ed0298c1`，
移动端完整页面截图为 `1082x5898`、SHA-256
`1ff0ae834e35e7ed5bf363943ace31c43015014aef5be00ff196542fcdeffe88`，
二者均通过尺寸、颜色数和像素极值非空检查。当前工具环境不能直接打开本地
截图，因此这里不把像素检查扩大为人工视觉审查。临时实例随后自动移除。

进程强杀测试先暴露了一个容易误判的 Docker 语义：上游
[`restart policy` 文档](https://github.com/docker/docs/blob/main/content/manuals/engine/containers/start-containers-automatically.md)
和 Moby
[`daemon/monitor.go`](https://github.com/moby/moby/blob/cb7c8dd909cf7760eefe5b06229beffb41fa5a55/daemon/monitor.go)
区分手工停止与异常退出。运维侧 `docker kill` 被视为手工停止，会暂时抑制
`unless-stopped`；第一次测试因此没有自动拉起，已立即显式启动恢复。容器内
进程也不能用普通同 namespace 信号可靠终止 namespace PID 1。最终使用正确
方法：从宿主核对容器真实 PID 与 `comm=python` 后直接发送 `SIGKILL`。

这次宿主级进程异常退出触发 `unless-stopped` 自动重启，`RestartCount=1`，
新启动时间为 `2026-07-28T20:33:15.242983935Z`，容器恢复 healthy。重启后
history 仍为 1 条，任务 `10dc594affec` 的 JSON/PNG byte size、SHA-256 和
PNG 文件头与重启前完全一致；公网 v4 在整个测试期间保持 200/healthy。该结果
证明已完成图版本的进程崩溃恢复，不证明运行中的 branch 可以 stage 精确续跑。

空间清理遵循 Docker Buildx
[`prune`](https://github.com/docker/buildx/blob/master/docs/reference/buildx_prune.md)
边界，只执行 `docker buildx prune --all --force`，回收 1.139MB 可再生
BuildKit cache；没有执行 system/image/container/volume prune。清理前后均为
75 个 image ID、46 个容器和 85 个卷，BuildKit cache 从 1.139MB 变为 0B；
宿主仍约 1.3GB 可用，公网 v4 和 v50 隔离实例均保持 healthy。

当前公网 `zlb-mindmap` 仍运行 v4 image ID
`sha256:2fedb0a26d47ce2d557f32710ba3938dda50f68e8fe21dd03c7a0a4367571d29`
并映射 `0.0.0.0:5173`，本节未重启或替换。v50 仍缺标准 DashScope 正式凭据
下的真实文本/视觉调用、同一次 26 页 53/53 + 66/66 clean artifact、真实
停写窗口备份、公网可回滚切换和 92 页完整生产 task/run，因此不能晋级。

### 19.18 备份切换未绑定统一质量证明

进一步审计发现，19.9 的 `production_backup cutover` 只验证 backup
完整性、恢复卷标签、rollback/candidate image ID 和运行态健康。它没有消费
19.16 引入的统一 evaluator artifact，因此以下状态可以同时成立：

1. 备份、卷和 candidate image 身份全部正确；
2. candidate 的公式、Required Coverage、page state 或模型调用策略仍未通过；
3. cutover 仍继续进入活动容器 rename。

这不是 evaluator 本身的公式 oracle 缺陷，而是部署 admission contract
缺少 evaluator subject。GitHub-first 检索采用了以下上游语义：

- Cosign
  [`verify-attestation`](https://github.com/sigstore/cosign/blob/02389754144be1becf4e164a2d381e6dcacb18d1/doc/cosign_verify-attestation.md)
  要求在消费 artifact 前验证 attestation；
- in-toto
  [`Statement v1`](https://github.com/in-toto/attestation/blob/6fad7157dfb216034e28223c6b5c6b0f9c41bf28/spec/v1/statement.md)
  按 digest 绑定 subject；
- Kyverno
  [`verify-image-slsa`](https://github.com/kyverno/policies/blob/ef9843f08d25b3555fe69616f8612c9f915af5d4/other/verify-image-slsa/verify-image-slsa.yaml)
  展示了 admission 时同时验证 image 与 attestation 的成熟模式。

本仓库当前没有 registry RepoDigest、签名基础设施或可直接采用的 Cosign
公钥合同，因此没有引入新的生产依赖，而是按相同语义完成最小本地绑定：

1. `freeze` 和 `cutover` 的 CLI 均强制要求
   `--quality-evaluation`；
2. freeze 在停止生产容器前验证 evaluator schema、candidate image ID、
   Qwen provider、age credential source、direct-layout profile、当前
   evaluator/canonical 模块 SHA、全部通用子门，以及非空公式、coverage 和
   knowledge 证明；
3. freeze 将 evaluation 文件 SHA-256、candidate image ID、run/task/source
   身份写入 backup manifest；
4. cutover 在活动容器 inspect、端口预检或 rename 前重新验证 artifact，
   并要求其文件 SHA-256 与 image ID 同 freeze manifest 一致；
5. 旧 backup manifest 没有质量 artifact identity 时 fail closed。

新增 TDD 覆盖 candidate mismatch 在 Docker inspect/rename 前失败、六个子门
逐一缺失、六类空证明、evaluator 源码身份错配，以及 CLI 缺少质量 artifact
时退出。当前聚焦测试为 20/20。该改动已进入 v51，但尚未产生正式 Qwen
evaluator artifact，不能据此切换公网。

### 19.19 v51 admission overlay 与隔离验证

v51 从已核对 image ID 的 v50 tag 构建，只覆盖 `backend/tools` 与
`backend/tests`。构建前宿主与 v50 的 `/app/backend/app` 为同一组 39 个
文件，内容树 SHA-256
`06aab7314dbd8b8fd24d90f74db5134bfa6cb2b262cccc480e193f1a5e36cb0c`；
因此没有把工作树中的其他 dirty 改动重新打包。`.dockerignore` 新增
`frontend/.pnpm-store`、`.test-dist` 和 `*.tsbuildinfo`，实际 build context
为 3.05 MB。

镜像证据：

- tag：`zlb-mindmap-agent:candidate-v51-20260728`；
- image ID：
  `sha256:d8b77c8cace86d8f6fc424c79eb60b56a6942b63d05114463a83cf9c5e643fa8`；
- size：1014069069 bytes；
- base：
  `sha256:ee373710599ea8526818edd98f88b798cdebfe1acd26b2d955cc83bde77ba5f5`；
- overlay tree：
  `a91f766ad6707eec7b451fc3b5cd1f71709567416924189f8ffa244fa1d530be`；
- `Config.User=10001:10001`，revision 为
  `297da939835dc9b748a33bd80d368702d7de687d-dirty`；
- Python 3.12.13、pypdf 6.14.2、pdfplumber 0.11.10、
  pdfminer.six 20260107、pylatexenc 2.11、Poppler 25.03.0；
- `pip check`、宿主 514/514、镜像内 non-root/read-only/cap-drop/
  no-new-privileges 514/514、前端 7/7、typecheck、build、compileall、
  Compose config 和 `git diff --check` 通过。

第一轮镜像测试把 `/app/.data` tmpfs 以默认 root:root 挂载，导致两个测试
模块在导入时因 non-root 无法创建目录而失败；其余已加载测试通过。将 tmpfs
改为 `uid=10001,gid=10001,mode=0750` 后完整 514/514 通过。该失败属于验证
harness 权限错误，不是镜像应用回归，记录在此避免只保留最终 GREEN。

`zlb-v51-isolated-20260728` 位于 `127.0.0.1:18141`，使用独立数据/上传卷和
新生成的无效测试 Qwen age 密文，没有读取既有实例凭据。secret preflight、
non-root、read-only rootfs、cap drop、no-new-privileges、3 GiB、2 CPU、
256 PIDs 与 health 通过。未认证和错误 token 的 history 为 401，有效
Bearer token 为 200。

一个 `use_ai=false` 任务 `e70fe35cac8a` completed；run manifest 记录 v51
image ID、标准 DashScope 脱敏 endpoint、`qwen3.7-max`、
`qwen3.7-plus` 和固定运行时版本。JSON 为 24058 bytes、SHA-256
`d7c31092226a81335a4420e572ac3a0118085332a773b499a48739245bf06ee2`；
PNG 为 18403 bytes、SHA-256
`98be5a4dc4400b947ae39f2c59c81e750a3e07188f8f4bab9c8767848a4452fc`，
文件头正确。容器重启后历史仍为一条，两个导出逐字节一致。

公网 `zlb-mindmap` 全程仍是 v4 image ID
`sha256:2fedb0a26d47ce2d557f32710ba3938dda50f68e8fe21dd03c7a0a4367571d29`
并保持 healthy。v51 仍没有标准 DashScope 正式凭据的文本/视觉调用、同一次
26 页全门通过 artifact、最终停写备份、公网 cutover 或 92 页正式 task/run。

### 19.20 v51 admission 隔离全流程

为验证 19.18 的质量绑定不只存在于单元测试，本轮使用当前 evaluator 生成一份
明确不可用于晋级的两页合成 artifact。它绑定 v51 image ID，包含 2/2 合成
公式和 2/2 合成 Required Coverage，但没有真实 Qwen 调用，不能作为生产质量
证据。

身份：

- evaluation SHA-256：
  `fd305c4d637e385fcb2bb56714715ed2e61d6774a671da4719af757fe337bffd`；
- canary report SHA-256：
  `9f9bdac66c770fd8d62f1c92987781a3c84f5f1534312c3209e113f6ab2679ae`；
- oracle SHA-256：
  `8a4356f289130873bc10c2a9dcc2536e8b03d127b33d11ee0cc2b25e170a11df`；
- backup manifest SHA-256：
  `be570793894dafc003a0ab36e2a24fcdeb366cf37273a5696d4704212d9ca7d8`。

流程证据：

1. `freeze` 在停服务前验证 artifact，并把它的 SHA、v51 image ID、
   evaluator/canonical 模块 SHA 和 run/task/source 身份写入 backup
   manifest；
2. freeze 后 `zlb-v51-isolated-20260728` 为 stopped、`restart=no`，公网 v4
   和 v50 隔离实例仍 healthy；
3. 将 evaluation 复制后仅追加一个换行，JSON 语义不变但文件 SHA 改变；
   cutover 以退出码 2 返回 `quality evaluation SHA-256` mismatch，活动容器
   未被 inspect/rename，rollback 名称不存在；
4. `prepare-volumes` 创建的新 data/uploads 卷分别带
   `zlb.role=data/uploads` 和相同 backup manifest SHA 标签；
5. 使用 freeze 时的原 artifact 后，cutover 成功，活动实例使用新恢复卷并
   healthy；
6. 历史任务仍为 `e70fe35cac8a`，JSON/PNG SHA-256 与切换前分别保持
   `d7c31092226a81335a4420e572ac3a0118085332a773b499a48739245bf06ee2`
   和
   `98be5a4dc4400b947ae39f2c59c81e750a3e07188f8f4bab9c8767848a4452fc`；
7. rollback 删除候选、恢复原容器名、原数据/上传卷与
   `restart=unless-stopped`，两个导出哈希再次逐字节一致；
8. 备份 SQLite `quick_check=ok`，包含 1 job、1 run、1 graph version、
   0 model calls。

演练完成后 v51、v50 和公网 v4 三个实例均 healthy；恢复卷、备份和合成
artifact 均保留。该结果证明质量 artifact SHA 绑定、备份恢复和回滚在真实
Docker 路径生效，不证明任何真实 PDF 页、公式或模型质量已经达标，也不证明
artifact 来自受信任 evaluator。

### 19.21 evaluator artifact 缺少签名 provenance

19.20 的演练进一步暴露出一个独立 admission 缺口：SHA-256 可以证明 freeze
与 cutover 消费了相同字节，却不能证明这些字节由受信任 evaluator 产生。一份
手工构造、结构完整并自称全部子门通过的 JSON 仍可通过 v51 的结构验证。因而
v51 的 SHA 绑定只能防止 freeze 后替换，不能作为 artifact 来源证明。

GitHub-first 检索覆盖当前仓库、Sigstore/Cosign 的 code、open/closed issues、
merged PR、release、commit 和文档，以及 pyca/cryptography 的 Ed25519
实现、测试、PR 和文档：

- Cosign 的
  [`verify-blob`](https://github.com/sigstore/cosign/blob/main/doc/cosign_verify-blob.md)
  是最接近的成熟 blob 签名合同；当前稳定 release 为
  [`v3.1.2`](https://github.com/sigstore/cosign/releases/tag/v3.1.2)，近期
  [`#4785`](https://github.com/sigstore/cosign/pull/4785) 等改动继续强化
  bundle 输出。宿主和 v51 镜像均没有 Cosign，直接采用会增加新的生产
  二进制、bundle 生命周期和镜像供应链范围；
- pyca/cryptography 提供官方
  [Ed25519 sign/verify API](https://github.com/pyca/cryptography/blob/main/docs/hazmat/primitives/asymmetric/ed25519.rst)，并在
  [`#8703`](https://github.com/pyca/cryptography/pull/8703) 等上游测试中
  覆盖 Ed25519 序列化。仓库 constraints、宿主和既有 PDF 依赖链已经固定
  `cryptography==49.0.0`，许可证为 Apache-2.0 OR BSD-3-Clause。

因此 v52 当时采用最小本地实现，不手写密码学，也不引入新外部二进制：

1. evaluator 使用仓库外的未加密 PEM Ed25519 私钥签署最终 evaluation 原始
   字节，并输出版本化 JSON sidecar；
2. sidecar 记录 `ed25519` 算法、artifact SHA-256、公钥 DER SHA-256 和
   Base64 签名，不记录私钥或凭据；
3. `freeze` 与 `cutover` 除 `--quality-evaluation` 外，还强制要求
   `--quality-signature` 和 `--quality-public-key`；
4. admission 校验 sidecar schema、artifact SHA、公钥类型和指纹、Base64
   编码、64 字节签名及 Ed25519 验证结果；
5. freeze manifest 保存 evaluation 与签名完整身份；cutover 在活动容器
   inspect、端口探测和 rename 前重新验签，并要求完整身份与 freeze manifest
   逐字段相等；
6. artifact 修改、缺 sidecar、错公钥、坏签名、旧 manifest 和 freeze 后
   sidecar 替换都 fail closed。freeze 验签失败不会停止生产服务。

聚焦 evaluator/backup TDD 为 34/34 GREEN，compileall 和
`git diff --check` 通过。签名门已进入 v52 并完成签名版隔离演练，但尚未
使用受控正式私钥生成真实 26 页 Qwen evaluator artifact。签名只证明受控
私钥授权了 artifact，生产资格仍依赖私钥托管流程只签署真实 evaluator 输出。
这一未加密 PEM 托管方式后来被 19.25 的 age 密文方案取代，不再是当前生产
CLI 或部署指引。

### 19.22 v52 签名 admission 候选与隔离验证

v52 在不删除任何既有 image、container、volume、backup 或 secret 的前提下，
从固定 v51 image ID 构建增量 overlay：

- tag：`zlb-mindmap-agent:candidate-v52-20260728`；
- image ID：
  `sha256:7565388eaffb769f3223f20608257a83e24bdc704ae07ef1a6d2f9d9ca0f6876`；
- size：1014347746 bytes；
- base：
  `sha256:d8b77c8cace86d8f6fc424c79eb60b56a6942b63d05114463a83cf9c5e643fa8`；
- overlay scope：`backend-tools-tests-dependency-manifests`；
- overlay tree：
  `c4c59621160e64992ff1d99bdee4af838ae85a4f25479a5e6b69c187ebd4d629`；
- requirements SHA-256：
  `33a225c93b0a13e68b6a2ff33389a85e2e9700a080c646842789e7b9b37177e5`；
- constraints SHA-256：
  `e55746bc093d1faf0ab8fadab174ac4cbfa1989d4254cc8995e9dd690f36de76`。

构建前，宿主与 v51 的 `backend/app` 39 个文件逐 SHA-256 一致；v52 只覆盖
`backend/tools`、`backend/tests`、requirements 和 constraints。镜像内为
Python 3.12.13、cryptography 49.0.0、pypdf 6.14.2、pdfplumber 0.11.10，
`pip check` 通过。宿主全量后端为 518/518；v52 在 non-root、read-only
rootfs、cap-drop、no-new-privileges、3 GiB、2 CPU、256 PIDs 和生产可写
data/uploads tmpfs 合同下同样为 518/518。

第一轮只挂载 `/tmp` 的只读镜像测试出现 2 个 import error：
`main` 初始化 SQLite 时没有可写 `.data`。其余 503 个已加载测试通过。补齐与
生产一致、归属 `10001:10001` 的 data/uploads tmpfs 后完整 518/518
GREEN。这是验证 harness 漏挂生产卷，不是应用回归。

签名版 admission 使用独立 v51 源容器、独立卷、回环端口 `18142` 和临时测试
Ed25519 key；artifact 明确为两页合成数据，不具备晋级资格。身份为：

- freeze backup manifest SHA-256：
  `f83881cf7b3f3f6b8afb38cba4ba3414b22c98b8500fb0d9832f47c3906b64fd`；
- evaluation SHA-256：
  `4c5f36af48b502d5dbf15d3ad347a0b63044778511a5edc8028480ae1f97df1d`；
- signature sidecar SHA-256：
  `d6761aa0ffc7e74b17973ca0f99e172bba3e68d646e02f903416a99913dc4d88`；
- public key DER SHA-256：
  `bbd526358f21d148580a3f9adac6172568a4b8082698babc9fe0d36e8e30dffb`。

流程证据：

1. freeze 在停止源容器前验签，并将完整签名身份写入 backup manifest；
2. evaluation 仅追加换行后，cutover 以 artifact SHA mismatch 退出 2，源
   容器原名保留且 rollback 名称不存在；
3. 恢复 artifact 后损坏 Base64 签名内容，cutover 以 Ed25519 verification
   failed 退出 2，同样没有 inspect/rename 活动容器；
4. 恢复原 sidecar 后，prepare-volumes 创建带相同 backup SHA 与 data/uploads
   role 标签的新卷，合法 cutover 启动精确 v52；
5. 基线、v52 cutover、v52 进程重启和 rollback 后，同一任务 JSON/PNG
   SHA-256 始终分别为
   `79986fea052817548d8fbd24359a8599cb8710abaadd6660bfdb7ec694d5211f`
   与
   `e23392692b6e956af4218999a238b99fe64faff82bca8376e22247b5979cdbaa`；
6. rollback 恢复精确 v51、原数据/上传卷、原容器名和
   `restart=unless-stopped`；公网 v4 全程仍是
   `sha256:2fedb0a26d47ce2d557f32710ba3938dda50f68e8fe21dd03c7a0a4367571d29`
   且 healthy。

保留的 `zlb-v52-isolated-20260728` 位于 `127.0.0.1:18143`，使用恢复卷与
独立测试 principal。安全运行合同、secret preflight、health、未认证/错
token/有效 token 的 401/401/200 均通过。其 `use_ai=false` 任务
`ef25543dc824` completed，进程重启前后 JSON/PNG SHA-256 分别保持为
`24b8e6daabd166d5d5575dcfa970da993c647c3d3646a05a8a65641b571f09fd`
与
`cd667fb67303658ea52cb27451f182a3de4fd2d8c9f1480ccd82bcfe792dcfe8`。
SQLite `quick_check=ok`，恢复卷当前有 2 jobs、2 runs、2 graph versions、
0 model calls；不同 principal 访问彼此任务返回 404，证明 owner scope 没有
因恢复或切换被绕过。

该结果闭环了签名 provenance、备份、恢复卷、候选重启和 rollback 的仓库内与
隔离 Docker 证据。仍未闭环的是标准 DashScope 正式凭据、受控正式签名 key、
真实 26 页 Qwen evaluator artifact、人工 source-gold 审核、公网停写/cutover
和 92 页正式生产 task/run。

### 19.23 evaluator 签名信任锚

继续审计 v52 的 Ed25519 admission 后发现，签名校验仍把
`--quality-public-key` 与待验签名一起作为命令行输入。攻击者或误操作若同时
替换 artifact、signature sidecar 和公钥，三者仍可自洽通过；原实现证明了
字节完整性，却没有证明签名者属于预先批准的 key 集合。

按 GitHub-first 要求检索了 Sigstore/Cosign、in-toto 和 pyca/cryptography：

- Cosign
  [`verify-blob`](https://github.com/sigstore/cosign/blob/main/doc/cosign_verify-blob.md)
  的 key-based 路径要求验证方预先提供公钥；keyless 路径则要求 expected
  certificate identity 与 OIDC issuer。
- in-toto 的
  [`in_toto_verify`](https://github.com/in-toto/in-toto/blob/develop/in_toto/in_toto_verify.py)
  将授权 key 集合和 threshold 作为验证策略。
- Cosign/TUF 能提供完整信任根分发与轮换，但当前宿主和候选镜像没有 Cosign，
  引入它会同时增加二进制、bundle、TUF metadata 和轮换生命周期；其
  [`root-signing`](https://github.com/sigstore/root-signing)
  仓库展示的正是需要额外维护的信任根分发流程。

因此没有复制上游实现或增加新依赖，而是在现有 pyca Ed25519 验证路径上加入
最小信任锚合同：

1. `freeze` 和 `cutover` 强制要求 `--quality-public-key-sha256`；
2. 该值必须是 64 位小写 SHA-256，并来自独立的密钥批准/交接记录；
3. 工具对实际 Ed25519 公钥的 DER 编码计算 SHA-256；
4. 实际公钥指纹、signature sidecar 中的公钥身份和批准指纹必须三者一致；
5. `trust_anchor_sha256` 写入 freeze manifest，cutover 在 inspect、端口探测
   或 rename 前使用同一批准指纹重新验签并完整对拍。

该门不创建或读取正式私钥，也不把任何 key 写入仓库。正式密钥生成、离线托管、
双人批准和指纹的独立交接仍是外部运维前置条件。

### 19.24 v53 信任锚候选与隔离验证

v53 从固定 v52 image ID 做最小增量构建，不删除或替换任何既有 image、
container、volume、backup 或 secret：

- tag：`zlb-mindmap-agent:candidate-v53-20260728`；
- image ID：
  `sha256:7c14972c76d91c7f28a50350f68212450de8ae996605df57b903040547fdcdcc`；
- size：1014455911 bytes；
- base：
  `sha256:7565388eaffb769f3223f20608257a83e24bdc704ae07ef1a6d2f9d9ca0f6876`；
- overlay scope：`production-admission-trust-anchor`；
- overlay tree：
  `6404711241a7952e80a487f948ab58b96d09ae2ec40ec7d62d59fc695993a04e`。

overlay 只覆盖 `backend/tools/production_backup.py` 与
`backend/tests/test_production_backup_tdd.py`。两文件的宿主与镜像 SHA-256
逐字节一致；继承的应用树、requirements 和 constraints 身份保持不变。
聚焦 evaluator/backup 为 35/35 GREEN；宿主 Python 3.11 逻辑回归和镜像内
Python 3.12.13 的 non-root、read-only、cap-drop、no-new-privileges、
3 GiB、2 CPU、256 PIDs、生产 data/uploads tmpfs 形态均为 519/519 GREEN，
`pip check` 通过。

使用临时测试 Ed25519 key 对 v53 执行信任锚 admission 探针：

1. artifact、signature 和实际公钥彼此匹配，但传入错误批准指纹；
2. 即使同时传入 `--stop-container`，freeze 仍以
   `public key is not trusted` 退出 2；
3. 独立 v51 源容器保持 running，未创建 backup；
4. 使用正确批准指纹后能通过验签，随后因未传 `--stop-container` 在既有
   停写窗口门退出 2，证明不是由其他 artifact 门造成的假拒绝。

保留的 `zlb-v53-isolated-20260728` 位于 `127.0.0.1:18144`。它使用临时占位
Qwen age secret 和独立测试 token，没有读取真实凭据；安全合同、secret
preflight、health、未认证/错 token/有效 token 的 401/401/200 均通过。
`use_ai=false` 任务 `27c9f6f9ad02` completed，产生 3 个节点；重启前后
JSON/PNG SHA-256 分别保持为
`413c380481e4a30abeeac12763688b7e012f1f7bd129981487ce81684e25313f`
与
`b5ee9e5a9a4ba80a657d9c812ab4e641bd58683f54508fd514528d8a8e092d3d`。
SQLite `quick_check=ok`，当前有 1 job、1 run、1 graph version、0 model
calls。

v53 闭环了仓库内和镜像内的 signer trust-anchor 代码证据，但没有产生正式
Qwen 调用或正式签名质量 artifact。标准 DashScope 正式凭据、受控正式私钥和
独立批准指纹、同一次真实 26 页 canary、人工 source-gold 审核、正式停写/
cutover 及 92 页生产 task/run 仍未完成，因此公网 v4 不得切换。

### 19.25 evaluator 明文私钥托管缺口

v53 的签名与独立信任锚能够证明 artifact 来自获批 key，但 evaluator CLI
仍要求传入未加密 PEM 文件。即使文件位于仓库外，明文私钥仍会长期驻留文件
系统，并可能被主机备份、误配置权限或操作脚本复制。该缺口与签名算法是否正确
无关，属于签名者私钥的静态托管风险。

GitHub-first 复核覆盖当前仓库、FiloSottile/age 的 open/closed issue、PR、
代码和 release，以及 pyca/cryptography 的 Ed25519 与序列化文档：

- age
  [`v1.2.1`](https://github.com/FiloSottile/age/releases/tag/v1.2.1)
  是包含安全修复的固定版本，现有生产 Dockerfile 已锁定该版本；age CLI
  原生支持从 stdin 加密/解密，因此不需要创建中间明文文件；
- pyca/cryptography 官方
  [Ed25519 API](https://github.com/pyca/cryptography/blob/main/docs/hazmat/primitives/asymmetric/ed25519.rst)
  和
  [key serialization](https://github.com/pyca/cryptography/blob/main/docs/hazmat/primitives/asymmetric/serialization.rst)
  已覆盖当前所需 PKCS#8、PEM、DER 和签名能力；
- Cosign 的加密 key pair 能解决更大的签名生命周期，但会增加 Cosign
  二进制、口令交互、bundle 和轮换合同。当前 admission 已固定 pyca Ed25519
  sidecar 和独立 trust fingerprint，直接迁移会扩大改动面，未采用。

因此当前源码沿用既有 age 与 pyca，补上最小托管合同：

1. `backend.tools.quality_signing_key` 在内存生成 Ed25519 PKCS#8，立即通过
   stdin 交给 age recipient 加密，明文私钥不落盘；
2. 工具排他创建 `0600` 私钥密文、`0644` PEM 公钥和 `0644` 版本化 trust
   record，默认拒绝覆盖；trust record 只含公钥 DER/PEM、密文 SHA-256 和
   age recipient；
3. 文件创建使用 `O_CREAT|O_EXCL`。失败清理只删除本进程已成功取得并创建的
   路径，不会在并发竞争失败后删除另一进程创建的文件；
4. evaluator 删除明文 `--signing-key`，强制成组接收
   `--signing-key-age`、`--signing-key-age-identity` 和
   `--signature-output`；
5. age 密文读取上限为 64 KiB，解密超时 20 秒，明文输出上限为 16 KiB；
   age stderr 不进入异常文本，私钥必须解析为 Ed25519，签名后尽力清零
   `bytearray`；
6. signature sidecar 与 production admission 合同保持不变，不修改公共 HTTP
   API、SQLite schema 或持久化图合同。

当前源码可发现 527 项后端测试。宿主最近一次资源受控的分组全量结果为
526 PASS、1 SKIP，唯一 SKIP 是宿主缺少 `age`/`age-keygen` 的真实往返；
新增竞态测试后的 signer/evaluator/backup 聚焦集为 42 PASS、1 SKIP。

v54 从固定 v53 image ID 做最小增量构建：

- tag：`zlb-mindmap-agent:candidate-v54-20260728`；
- image ID：
  `sha256:7b7bd6ea56f2fc9d6347b7cc8501e50889c64178732958255c52e25c9e1fc9e4`；
- size：1014569264 bytes；
- base：
  `sha256:7c14972c76d91c7f28a50350f68212450de8ae996605df57b903040547fdcdcc`；
- overlay scope：`quality-signing-age-custody`；
- overlay tree：
  `3b4ca42ea9d054c5b0afd3e5dc4a11a0c52261eabdf749bd3922bc6e88605350`。

overlay 只覆盖
`backend/tools/pdf_page_knowledge_evaluator.py`、
`backend/tools/quality_signing_key.py` 和三个对应测试文件。v54 RootFS 以
v53 的全部 25 层为严格前缀，仅增加两个 COPY 层；五个覆盖文件的宿主与镜像
SHA-256 逐文件一致，应用树、requirements 和 constraints 标签保持不变。

v54 在 Python 3.12.13、non-root、read-only rootfs、cap-drop、
no-new-privileges、3 GiB、2 CPU、256 PIDs、生产 data/uploads tmpfs 和
`--network none` 形态下按五个顺序容器运行 527/527 GREEN。真实
age/age-keygen 往返不再 SKIP，`pip check`、Compose config、签名 admission
和 artifact 篡改拒绝探针均通过。

隔离容器 `zlb-v54-isolated-20260728` 绑定 `127.0.0.1:18145`，使用全新无效
测试 Qwen age secret，没有读取正式凭据。secret preflight、health、安全
运行合同和未认证/错 token/有效 token 的 401/401/200 均通过。v53 隔离容器
已停止但保留，公网 v4 仍为
`sha256:2fedb0a26d47ce2d557f32710ba3938dda50f68e8fe21dd03c7a0a4367571d29`
且 healthy。

v54 闭环了 age 私钥托管的代码、镜像和无模型隔离证据，但没有产生正式 Qwen
调用或正式签名质量 artifact。标准 DashScope 正式凭据、正式密钥仪式与独立
批准、同一次真实 26 页 canary、人工 source-gold 审核、正式停写/cutover
及 92 页生产 task/run 仍未完成，因此公网 v4 不得切换。

### 19.26 正式 Qwen endpoint 允许列表

继续审计生产资格门时发现，旧实现虽然会拒绝已知 Token Plan host，却会接受
任意 HTTPS 第三方 host。这样只能证明 endpoint 不是已知订阅计划，不能证明
生产流量确实发往标准 DashScope 或已批准的 Model Studio workspace。

GitHub-first 复核采用 QwenLM/qwen-code 的 Apache-2.0 官方 provider 配置：

- [Alibaba standard provider](https://github.com/QwenLM/qwen-code/blob/0c0ca5fed0e287b98d9be9e51d364d01be3d2041/packages/core/src/providers/presets/alibaba-standard.ts)
  列出北京、新加坡、美国弗吉尼亚和中国香港四个标准 OpenAI-compatible
  endpoint；
- [Alibaba Token Plan provider](https://github.com/QwenLM/qwen-code/blob/0c0ca5fed0e287b98d9be9e51d364d01be3d2041/packages/core/src/providers/presets/alibaba-token-plan.ts)
  将北京和新加坡 Token Plan 定义为独立 provider；
- [Alibaba Coding Plan provider](https://github.com/QwenLM/qwen-code/blob/0c0ca5fed0e287b98d9be9e51d364d01be3d2041/packages/core/src/providers/presets/alibaba-coding-plan.ts)
  使用独立的 `coding*.dashscope.aliyuncs.com/v1` endpoint 和 `sk-sp-`
  credential contract。

当前源码据此执行 fail-closed endpoint 校验：

1. 标准共享 endpoint 只接受四个官方 host；
2. workspace endpoint 只接受
   `llm-<workspace>.<region>.maas.aliyuncs.com/compatible-mode/v1`，且 region
   限于北京、新加坡、东京和法兰克福；
3. Token Plan、Coding Plan、trial、第三方 host、非 HTTPS、错误 path、
   userinfo、自定义端口、query 和 fragment 全部拒绝；
4. endpoint 校验不读取 PDF、页码、canonical 答案或学科内容，不修改任何
   抽取 prompt。

新增 TDD 在修复前对国际 Coding Plan 和新加坡 Token Plan 为 RED：两者分别
被误分类为 `invalid_endpoint` 和 `unapproved_endpoint`。补齐官方计划型
host 后，单测转为 GREEN；Qwen config/provider、canary/evaluator、
secret preflight 和 production hardening 聚焦回归为 85/85。

v55 从固定 v54 image ID 做最小增量构建：

- tag：`zlb-mindmap-agent:candidate-v55-20260729`；
- image ID：
  `sha256:cef2cd93255ce391c6f121b8bd4c339e190eabff88dae5352d351c74c2d82c0c`；
- size：1014606183 bytes；
- base：
  `sha256:7b7bd6ea56f2fc9d6347b7cc8501e50889c64178732958255c52e25c9e1fc9e4`；
- backend app tree：
  `12ca0b11fc0e5e1d89208ed4cab0a0b0ed8c8aa8e4146c33955eea7950071915`；
- overlay scope：`production-qwen-endpoint-allowlist`；
- overlay tree：
  `078cc6f35b84e572e2296a9b828a2a452252be6d1980ca7cbb26d8cb31fa9f10`。

overlay 只覆盖 `backend/app/config.py` 与
`backend/tests/test_production_hardening_tdd.py`。v54 的全部 27 个 RootFS
层是 v55 的严格前缀，v55 仅增加两个 COPY 层；两个覆盖文件的宿主与镜像
SHA-256、镜像内应用树和 image label 全部一致。

v55 在 Python 3.12.13、non-root、read-only rootfs、cap-drop、
no-new-privileges、3 GiB、2 CPU、256 PIDs、生产 data/uploads tmpfs 和
`--network none` 形态下按五个顺序容器运行 530/530 GREEN。`pip check`、
Compose config、标准 endpoint 接受、第三方 endpoint 拒绝和计划型 endpoint
拒绝探针均通过。

隔离容器 `zlb-v55-isolated-20260729` 已在 `127.0.0.1:18146` 完成验证，
复用既有无效测试 Qwen age secret，没有读取正式凭据。secret preflight、
health、安全运行合同和未认证/错 token/有效 token 的 401/401/200 均通过；
稳定态实测内存约 132 MiB，验证后已停止但保留。v54 与 v53 隔离容器也保持
停止并保留，公网 v4 仍为
`sha256:2fedb0a26d47ce2d557f32710ba3938dda50f68e8fe21dd03c7a0a4367571d29`
且 healthy。

v55 闭环了代码、镜像和无模型隔离层面的正式 endpoint 资格门，但没有生成
标准 DashScope 的真实文本/视觉调用证据。正式凭据、候选签名公钥指纹的独立
批准、同一次真实 26 页 canary、人工 source-gold 审核、正式停写/cutover
及 92 页生产 task/run 仍未完成，因此公网 v4 不得切换。
