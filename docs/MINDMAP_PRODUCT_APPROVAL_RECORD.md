# 思维导图 vNext 产品审批记录：ADR-03 至 ADR-12

- 审批日期：2026-07-30
- 审批角色：产品经理独立审批
- 审批范围：ADR-03 至 ADR-12 的方向、实施授权和启用授权
- 事故基线：公网 v56 “醛和酮”任务
- 权威 Workflow：`docs/MINDMAP_WORKFLOW_SPEC.md`
- 整改背景：`docs/MINDMAP_SYSTEM_REDESIGN.md`
- 实验实现清点：`docs/VNEXT_IMPLEMENTATION_MATRIX.md`
- 完整执行书：`docs/MINDMAP_EXECUTION_PLAYBOOK.md`
- 结论性质：架构决定和分阶段授权；当前另有学生竞赛模式覆盖条款

---

## 学生竞赛授权覆盖

2026-07-30，项目所有者确认本项目实际为学生参赛项目。当前交付目标从生产发布
准备调整为本地或隔离环境的竞赛演示。

| 项目 | 竞赛决定 |
| --- | --- |
| 八项 Q0 代码安全与诚实性修复 | 保留；自动测试全绿后接受 |
| 独立多人签署 | 取消硬性要求 |
| 60 份 Gold、sealed blind、双标/仲裁 | 取消竞赛硬门 |
| 20 人用户研究与生产统计 | 取消竞赛硬门 |
| 完整 fault matrix、RTO/RPO、灾备 | 取消竞赛硬门 |
| Q2/Q4 paired blind、internal allowlist、canary、多签 | 移出竞赛范围 |
| 实际参赛材料端到端演练 | 保留，提交作品前由项目所有者完成 |
| 密钥、owner 隔离、私有数据和失败诚实性 | 保留，不得豁免 |

因此当前候选可标记为 `ACCEPTED FOR COMPETITION DEMO`，但不得据此宣称生产级
质量、生产 SLO、多租户安全认证或正式公网发布资格。后文 ADR-03 至 ADR-12 的
生产门保留为未来产品化参考，不阻断当前参赛候选。

## 0. 审批方法

### 0.1 三轴决定

每个 ADR 分别审批三件事，禁止用一个“批准”同时替代：

| 轴 | 回答的问题 |
| --- | --- |
| `DESIGN` | 产品方向和系统原则是否成立 |
| `IMPLEMENTATION` | 当前是否值得投入工程、标注和研究资源 |
| `ACTIVATION` | 能力是否可用于离线、shadow、内部用户或公网用户 |

本文使用以下决定：

| 决定 | 含义 |
| --- | --- |
| `APPROVE` | 方向或精确范围成立 |
| `APPROVE_WITH_REVISION` | 核心方向成立，但原提案中的部分技术、数字或边界被修改 |
| `SPLIT_DECISION` | 同一 ADR 中一部分批准，另一部分明确延后或否决 |
| `GO_NOW` | 可以进入当前实施队列；不表示已经启动 |
| `GO_AFTER_GATE` | 只有本文指定的前置证据通过后才能开始该子项 |
| `HOLD` | 当前不应投入正式实现或不得启用 |
| `NO_GO` | 明确禁止当前启用；解除需要新的证据包和书面授权 |

实施批准不自动构成启动指令，shadow 批准不自动构成公网批准。

### 0.2 产品审批准则

每项决定按以下顺序判断：

1. **用户结果**：是否直接减少错根、正文残片、错层级、遗漏和首屏混乱。
2. **真值诚实**：系统能否区分“执行完成”“质量通过”和“已经发布”。
3. **证据充分**：阈值、模型组合和基础设施选择是否有真实数据支持。
4. **风险隔离**：语义、安全、隐私、运行和展示故障是否能独立停止。
5. **依赖顺序**：是否在质量问题尚未证明解决前过早建设发布或基础设施。
6. **可逆性**：失败时能否停止、撤回和回到最后一个已知良好的 vNext 版本。
7. **成本收益**：新增模型、搜索和基础设施是否产生可测量的净产品价值。
8. **最小完整性**：优先实现最小但闭环的方案，不为“架构完整感”堆组件。

### 0.3 当前产品事实

当前 168 个 vNext 专项测试只证明若干实验原语可执行，不证明导图质量已过门。
审批复核确认至少存在以下 P0 假绿灯：

1. 产生 open `ReplanRequest` 后仍继续生成 Canonical/Projection。
2. durable quality 的最终 PASS 没有与全部失败 hard metric 做合取。
3. Inventory 只枚举同一 parser 已经看到的对象，parser 漏项仍可能从分母消失。
4. Shadow API 使用全局 token，并信任调用方提交 owner header。
5. Release readiness 和 canary observation 可由调用方构造，Governor 未从受信存储
   重建完整前序证明。
6. Canonical builder 为自己生成的关系构造 verifier 支持票。
7. Projection 使用输入顺序的第一条父边，改变 relation 顺序即可改变用户看到的树。
8. Legacy adapter 硬编码多个 quality/publish gate 为 `true`。

因此，本审批把“关闭对应 P0”作为所有外部启用的共同前置，而不是把它们当成普通
技术债。

### 0.4 总体结论

| ADR | DESIGN | IMPLEMENTATION | ACTIVATION | 产品优先级 |
| --- | --- | --- | --- | --- |
| ADR-03 Inferred Region | `APPROVE_WITH_REVISION` | `GO_AFTER_GATE`：先有 Gold 和 fail-closed Gate | public-fixture shadow 可条件解锁；用户可见 `NO_GO` | P1 |
| ADR-04 Search | `APPROVE_WITH_REVISION` | Gateway/recorded `GO_NOW`；live transport `GO_AFTER_GATE` | source-only 保持默认；私有内容 live egress `NO_GO` | P2 |
| ADR-05 Model Portfolio | `APPROVE_WITH_REVISION` | manifest、盲审、校准 `GO_NOW` | 只限内部 pilot；用户档位和 production `HOLD` | P1 |
| ADR-06 Gold/Quality | `APPROVE` | `GO_NOW` | 可阻断 shadow/CI；统计 PASS 和公网 `NO_GO` | P0 |
| ADR-07 Durable Control | `SPLIT_DECISION` | StageCommit/cancel/cost `GO_NOW`；Postgres/Temporal `HOLD` | vNext shadow only | P1/P3 |
| ADR-08 Status/API | `SPLIT_DECISION` | 内部三状态和 fail-closed adapter `GO_NOW`；公共 API `HOLD` | internal/shadow only；公共迁移 `NO_GO` | P0 |
| ADR-09 Canonical/Projection | `APPROVE_WITH_REVISION` | candidate contract 和 P0 修复 `GO_NOW`；1.0 freeze `HOLD` | diagnostic/internal only | P0 |
| ADR-10 Attestation/Revocation | `SPLIT_DECISION` | closure、provenance、withdraw `GO_NOW`；2-of-3 `HOLD` | release simulation only | P3 |
| ADR-11 Product/HITL/A11y | `APPROVE` | `GO_NOW` | 内部可用性研究可启用；公网 `NO_GO` | P0 |
| ADR-12 Canary | `APPROVE_WITH_REVISION` | policy、simulator、rollback drill `GO_NOW` | internal allowlist 条件解锁；public canary `NO_GO` | P3 |

这不是十项全绿。被明确延后的主要事项是：

- 用具体厂商或同一套基础设施绑定产品架构；
- 未经数据校准就冻结模型、预算、阈值、节点数和 canary 百分比；
- 私有课件 live web egress；
- 未版本化修改公共 API；
- 在没有真实签名主体分离时实施 2-of-3；
- 在语义质量尚未证明前迁移 Postgres/Temporal；
- 任何公网流量切换。

---

## 1. 跨 ADR 执行门

### 1.1 Q0：结果诚实门

在任何 live model、live search、内部 allowlist 或公网候选启用前，必须关闭与该路径
有关的全部 P0：

- open replan 物理阻断教学 Canonical、Projection、legacy adapter 和 release pointer；
- quality decision 由所有适用 hard metric 的合取计算；
- Source Inventory 有独立于主 parser 的 raw/package/render 对账来源；
- owner 从认证 principal 派生；
- relation verifier 不能由 Canonical builder 自签；
- Projection parent policy 对输入排列不敏感；
- legacy adapter 只能消费 published pointer 和真实 attestation；
- release/canary 事实由 Governor 从受信 store 加载。

Q0 没有软豁免。任一项未完成，只允许受限开发和诊断 artifact。

### 1.2 Q1：评测可信门

必须先完成：

- Gold contract、标注指南、多合法结构表达和 source-group 隔离；
- development、calibration、sealed blind 三个集合的不可变 manifest；
- 每个关键维度的双人标注、分歧和专家仲裁记录；
- hard metric 分母、`INCOMPLETE` 语义和 worst-document/slice 报告；
- 阈值在 calibration 上冻结，sealed blind 不用于调参；
- “醛和酮”作为回归反例，但不作为唯一质量证明。

### 1.3 Q2：语义候选门

Inferred Region、Precision 和 grounded-assist 必须分别与 source-only explicit baseline
做同文档、同 source-group 的盲评。候选只有同时满足以下条件才可晋级：

- 不增加错 root、错一级、严重 premature STOP、高价值遗漏或伪父边；
- 在预注册的目标 slice 上产生可测量净提升；
- 最差文档和最差 slice 不被 pooled average 掩盖；
- 增加的成本、延迟和人工复核负担处于已批准预算；
- 五次真实运行没有出现新的 P0，且严重错误不因随机采样偶发消失。

没有统计把握时结论是 `INCONCLUSIVE/HOLD`，不是 PASS。

### 1.4 Q3：产品可理解门

内部用户必须能：

- 快速识别 root、一级章节和当前 section；
- 区分课件内容、外部辅助、未决、被拒绝和已发布；
- 从节点返回精确页、对象、表格单元格、公式或反应区域；
- 理解系统为何停止，而不是把 blocked 状态误认为生成失败或完成；
- 在桌面、移动端和键盘/辅助技术下完成核心任务；
- 在 review 任务中只回答一个清楚问题，并知道决定的影响范围。

“醛和酮”验收必须直接检查：root/L1 无正文残片，首屏不堆满全部节点，不使用任意
左右分桶表达语义，章节顺序和展开行为稳定。

### 1.5 Q4：外部能力安全门

任何 live search 必须先通过租户同意、query minimization、DLP、SSRF、DNS/redirect、
prompt injection、owner 隔离、snapshot、retention、deletion 和 kill switch 演练。
外部证据污染 core 的次数必须为 0。

### 1.6 Q5：发布可信门

任何 internal allowlist 或 public canary 必须：

- 使用完整 artifact closure 和 evaluator provenance；
- 从受信 store 重建 readiness，而不是接受调用方 boolean；
- 有顺序不可跳跃的 release event；
- 有 sticky assignment、不可复用样本和预注册 look schedule；
- 有最后一个已知良好的 vNext pointer，或明确的 feature-off/diagnostic-only 回退；
- 完成撤回、取消、备份恢复和 rollback drill。

禁止自动回退到已知质量失败的 v56。

---

## 2. ADR-03：Inferred Region

### 2.1 产品判断

**方向成立。** 只依赖显式目录和标题无法覆盖无目录、目录不完整或正文真实结构与目录
不一致的课件。若永远停在 explicit-only，系统会在一批真实文档上只能输出过粗、
不完整或大量 unresolved 的结果。

但原始设想“把全文交给模型，由模型持续划区，直到模型判断结束”不能直接批准。
它把停止权和结构权同时交给同一个模型，仍会重现 v56 的正文残片、错误根和局部
自洽问题。

### 2.2 审批决定

- `DESIGN = APPROVE_WITH_REVISION`
- `IMPLEMENTATION = GO_AFTER_GATE`
- `ACTIVATION = PUBLIC_FIXTURE_SHADOW_AFTER_Q0_Q1`
- 私有课件、用户可见教学图和公网发布：`NO_GO`

### 2.3 批准范围

- Global Planner 可依据完整 Global Structure Pack 提出 root 和一级 inferred Region。
- Recursive Planner 只能在 accepted parent scope 内提出下一层 split/stop。
- 每个 inferred Region 必须标明 inference 类型、source scope、边界证据和替代方案。
- Planner 只提交 proposal；独立 verifier 和确定性 Gate 决定接受、拒绝或 unresolved。
- 显式锚点与 inferred 结构冲突时必须显式记录，禁止静默覆盖。
- Source assignment、Inventory 对账、strict subset、MRA 和 replan 规则继续有效。
- 模型必须可以 `ABSTAIN/UNRESOLVED`；资源上限不得转换成语义 STOP。
- 可以在公开或授权去标识 fixture 上比较 explicit-only 与 inferred candidate。

### 2.4 不批准

- 单次 whole-document prompt 直接输出完整可发布树。
- Planner 自己决定自己的 split/stop 已通过。
- bottom-up Agent 因看到 Claim cluster 而直接补建父节点。
- 用最大深度、页数、token 或节点容量证明主题已经完整。
- 未经 blind evaluation 就让 inferred Region 替换 explicit baseline。
- 把文档标题缺失、解析失败或证据不足转成模型自由想象根主题。

### 2.5 开始实施前置

1. ADR-06 的 Region Gold、split/stop oracle 和严重错误分类可用。
2. open replan 阻断链已经关闭。
3. Inventory 不再只依赖同一 parser 的输出。
4. inferred proposal、verifier 和 Gate 使用不同 producer identity。
5. 先冻结 explicit-only baseline 和同文档对照协议。

### 2.6 完成证据

- 无目录、目录不完整、错误目录和跨页主题 fixture 均有 accepted/unresolved oracle。
- root/L1、split/stop、boundary、same-region、replan 和 first-error-mass 可计算。
- 候选在目标 slice 上优于 explicit-only，且不增加任何 promotion-blocking serious error。
- proposal 顺序扰动、label 改写和重复运行不会让 Gate 失去稳定性。
- 任一 open replan 会使受影响 subtree quarantined，并阻止正式 Canonical/Projection。
- “醛和酮”不再出现正文残片成为 root/L1 的回归。

### 2.7 Stop 条件

出现下列任一情况，停止该 candidate 的晋级并回到设计或标注阶段：

- 错 root/一级主题、严重 premature STOP 或高价值遗漏；
- inferred 只提高 coverage，却降低 direct parent 或 ancestor 质量；
- replan 在 A/B 状态间振荡；
- verifier 与 planner 错误高度同源，否决门形同虚设；
- 结构提升只出现在单个测试文档或单一课程模板；
- 成本和延迟增加，但用户任务成功率没有改善。

---

## 3. ADR-04：Search

### 3.1 产品判断

**联网搜索有价值，但不是当前结构混乱的首要修复。** 它适合术语、命名、符号、
标准和关系消歧；不能补偿 Source IR、Region Gate 或 Projection 的错误。先把搜索
接入一个会错误建树的系统，只会让错误结构获得更多看似可信的文本。

“每个认知 Agent 都有搜索能力”的正确产品含义是：每个角色都可以提交
`SearchIntent`，而不是每个角色都可以直接联网或默认执行搜索。

### 3.2 审批决定

- `DESIGN = APPROVE_WITH_REVISION`
- Gateway、Query Compiler、policy、recorded replay：`IMPLEMENTATION = GO_NOW`
- public-fixture live transport：`IMPLEMENTATION = GO_AFTER_Q0_Q1_Q4`
- 私有/受限课件 live egress：`ACTIVATION = NO_GO`
- `enriched_overlay` 用户启用：`HOLD`

### 3.3 批准范围

- `source_only`、`grounded_assist`、`enriched_overlay` 三种 evidence mode 合同。
- `source_only` 为默认，Manifest 冻结后禁止静默升级。
- 所有认知 Agent 可提交受限 trigger code 的 `SearchIntent`。
- Gateway 本地重新编译、最小化、分类和 DLP 检查 query。
- Agent 无直接网络权限；Fetcher 使用独立网络身份和 ACL。
- 课件证据与 external evidence 分 namespace、分 coverage、分 publication authority。
- 保存不可变 raw response 和 sanitized derivative，绑定精确引用 selector。
- Search 失败、预算耗尽或 provider outage 不得破坏 source-only 主链。
- 可先使用 recorded fixture、公开语料和安全攻击夹具验证完整闭环。

### 3.4 修订和否决

- **WARC 不是强制产品格式。** 必须保存足以审计和 replay 的原始响应、DNS、
  redirect、header、body digest 和 sanitizer lineage；WARC 仅在确有互操作收益时采用。
- **不批准统一永久保留。** Retention 必须按数据分类、租户同意、版权和删除要求配置。
- **不批准全 Agent 默认搜索。** 没有固定触发理由时 Gateway 必须拒绝。
- **不批准用外部 taxonomy 单独认证 core split、Claim 或父边。**
- **不批准私有长句、notes、题目答案或内部标识符出站。**
- **不批准首期抓取外部 PPTX、ZIP、任意附件或执行网页脚本。**

### 3.5 完成证据

- source-only 模式网络调用为 0。
- SSRF、private/metadata IP、DNS rebinding、redirect、MIME、压缩炸弹测试全部 fail closed。
- query redaction、owner cache isolation、consent 撤销和 deletion 可重复演练。
- raw snapshot、sanitized derivative、quote selector 和 replay digest 一致。
- 外部内容不能修改系统任务、权限、预算、schema 或工具调用。
- 同文档 A/B 盲评证明 grounded-assist 在预注册歧义 slice 上有净提升。
- 搜索关闭或失败时，已提交 SourceObservationIR 和 source-only 结果不改变。

### 3.6 Stop 条件

- 任一敏感数据出站、跨 owner 泄漏、SSRF 或权限提升；
- 外部-only 内容进入 core 或提高 courseware coverage；
- 无法删除、撤回或重放已用于决定的外部证据；
- 搜索显著增加结构错误、延迟或成本，却没有产品任务收益；
- trigger 退化为“遇到不确定就搜”，产生大量无必要查询。

---

## 4. ADR-05：Standard / Precision 与模型组合

### 4.1 产品判断

能力槽、盲审和错误相关性校准是正确方向。把“两个厂商”“两个模型名”直接称为
独立，或者先固定 Precision 为 Standard 的 2.5 倍成本，都没有充分证据。

Standard / Precision 首期应是内部运行 profile，不应先包装成用户可购买档位。
只有 Precision 稳定降低严重错误，并且成本、延迟和人工负担可解释，才值得产品化。

### 4.2 审批决定

- `DESIGN = APPROVE_WITH_REVISION`
- manifest、slot router、blind ordering、independence calibration：
  `IMPLEMENTATION = GO_NOW`
- 内部 Standard/Precision 对照 pilot：`ACTIVATION = GO_AFTER_Q0_Q1`
- 用户可见档位、价格承诺和 production routing：`HOLD`

### 4.3 批准范围

- 使用能力槽而不是“一个 run 一个模型”的 ModelPortfolioManifest。
- 记录精确 model revision、prompt/tool digest、区域、成本、延迟和有效期。
- Planner、Extractor、Verifier、Arbiter 的权限和输出 schema 分离。
- Verifier 看不到 proposer 身份、confidence、候选原始排序和其他票。
- 同模型重复采样只用于稳定性，不计算为独立票。
- 通过 calibration 记录错误相关性、double-fault、位置偏差、自偏好和领域 slice。
- 模型 revision 或 prompt/material policy 变化后，独立性 attestation 自动失效。

### 4.4 不批准

- 冻结具体模型厂商、alias 或 endpoint 为长期产品架构。
- 把不同 provider 自动视为独立。
- 固定 `2.5x`、64/128 task、2/3 replan 等数字为生产承诺。
- 在没有成对盲评前向用户宣传 Precision 更准确。
- 缺少第二票时用启发式补齐高风险结构。
- 让 Arbiter 成为无证据的第三次多数投票。

### 4.5 完成证据

- 每个发布候选的 model revision 和 independence group 可追溯。
- Standard 与 Precision 在同一 source-group 上做配对盲评。
- Precision 对预注册 serious-error 指标有可信净改善，且最差 slice 不退化。
- 成本、wall time、失败率、review burden 和质量收益同时报告。
- 任一 verifier pair 在换序、措辞和 proposer self-preference 测试中稳定。
- 找不到低相关 verifier pair 时，Precision 正确返回 review/withheld。

### 4.6 Stop 条件

- Precision 只增加 token 或票数，没有降低严重错误；
- verifier double-fault 仍集中在同一结构错误；
- 模型 alias 漂移导致结果无法重放；
- 延迟或价格使目标用户不能接受；
- 模型组合复杂度阻碍 ADR-06、ADR-09 和 ADR-11 的更高优先级工作。

---

## 5. ADR-06：Gold、指标、阈值、CI 和 LLM Judge

### 5.1 产品判断

**这是当前最高优先级基础设施。** 没有可信 Gold 和 fail-closed 质量系统，就无法
判断 inferred Region、搜索、多模型或新 Projection 是改善还是换一种混乱。

### 5.2 审批决定

- `DESIGN = APPROVE`
- `IMPLEMENTATION = GO_NOW`
- invariant/hard-gate CI 可立即阻断 shadow candidate
- statistical quality PASS、生产声明和公网发布：`NO_GO`，直到 Q1/Q2 完成

### 5.3 批准范围

- GoldDocument 保存 Source Inventory、Region 约束、atomic Claim、多合法 parent、
  required/allowed/forbidden path、Projection task 和安全 oracle。
- source_group 按原始 hash、近重复指纹、metadata 和人工审查隔离。
- development 用于调试，calibration 用于冻结阈值，sealed blind 只用于独立评估。
- 每份关键样本至少双人标注；root/L1 和高风险父边由学科专家仲裁。
- 质量以 hard gate 合取、指标向量、最差文档、最差 slice、risk-coverage 和稳定性表达。
- `INCOMPLETE` 是正式结果；分母、阈值、gold 或稳定性缺失时不能 PASS。
- 60 文档只批准为初始 pilot 最低工作量，不批准为生产充分样本。
- 现有候选阈值只作为 calibration 起点，不作为预先写死的验收答案。
- LLM Judge 只用于 shadow metric、风险排序和人工复核召回。

### 5.4 不批准

- 单一总分或 pooled average 抵消 hard failure。
- 在 sealed blind 上反复调阈值。
- 用一个“醛和酮”结果或 168 个合同测试宣称质量通过。
- 删除 unresolved 或困难 Claim 来提高 precision。
- LLM Judge 单独发布、覆盖 hard gate 或替代专家 gold。
- 未报告置信区间、分母和 worst-case 就声称改进。

### 5.5 完成证据

- 标注指南、原始标注票、仲裁、版本、seal 和 digest 完整。
- 标注一致性按 root、Region、Claim、relation 和 product task 分维度报告。
- 一致性不足时先修订合同/指南，不通过降低阈值制造一致。
- 任一 hard metric `passed=false` 时最终 gate 必为 BLOCK。
- 任何未冻结阈值、数据缺失或泄漏都产生 INCOMPLETE/BLOCK。
- “小而完美”、错误祖先级联、错误 TOC 和多合法图 fixture 均有可执行 oracle。
- 真实五次运行同时报告均值、最小值和 serious-error 复现。

### 5.6 Stop 条件

- source-group 泄漏或 sealed blind 被开发人员看见并用于调参；
- 标注者无法稳定理解关键概念，说明合同本身尚未可评；
- 指标鼓励删除难项、制造 singleton 或只优化视觉整齐；
- Judge 与专家严重分歧却仍被用于放行；
- 数据集不覆盖真实输入格式、领域、语言和视觉复杂度。

---

## 6. ADR-07：StageCommit v2、Postgres、Temporal 和 Cancel

### 6.1 产品判断

该 ADR 原提案把“必须拥有的运行语义”和“可能采用的基础设施产品”绑在了一起，
需要拆分审批。

StageCommit、CAS、heartbeat、outbox、durable cancel、成本账本和 fault injection
直接防止重复结果、错误恢复和越权发布，应批准。Postgres 和 Temporal 是候选实现，
不是产品目标；在语义质量尚未证明、现有 shadow 尚无真实并发瓶颈时提前迁移会
消耗主线资源。

### 6.2 审批决定

- `DESIGN = SPLIT_DECISION`
- StageCommit v2、lease/heartbeat、outbox、cancel/cost：
  `IMPLEMENTATION = GO_NOW`
- Postgres 迁移：`HOLD`，等待真实多 writer、RPO 或 pointer 需求证据
- Temporal：当前作为指定技术方案 `NO_GO`；durable workflow capability 保留，
  需要后续比较性 ADR
- `ACTIVATION = VNEXT_SHADOW_ONLY`

### 6.3 批准范围

- 仅在独立 vNext store 中实现新合同，不修改 legacy SQLite schema。
- immutable artifact 与 terminal StageCommit 共同构成 durable checkpoint。
- worker 使用 lease epoch、cancel epoch、heartbeat 和 CAS fencing。
- interaction 先落账，artifact 验证后再提交业务事实。
- outbox、orphan reconciliation、idempotency 和 append-only cost ledger。
- 对模型已接受但记录未完成的请求标记 ambiguous external effect，禁止盲重试。
- 按每个 commit 边界执行 kill、duplicate、cancel/commit race 和恢复测试。

### 6.4 延后和否决

- 不批准因为“公网最终大概率需要”就立即迁移 Postgres。
- 不批准把 Temporal history 当作产品 artifact 或 publication 权威。
- 不批准新增 durable engine 后仍让 Activity 假设 exactly-once。
- 不批准在没有回填、双读、PITR、failover 和回滚证据时切换 control store。
- 不批准把基础设施完成度当作语义质量完成度。

### 6.5 Postgres / Durable Engine 解锁证据

- 当前 SQLite/checkpointer 在批准的并发或故障矩阵上确实失败；
- 失败对应明确用户或发布风险，且不能用更小改动解决；
- 候选方案完成许可、安全、运维、成本和版本兼容比较；
- 有 immutable export、双读比对、回填、回滚和灾备方案；
- 迁移不触碰 legacy schema，不阻塞 ADR-06/09/11 的产品主线。

### 6.6 Stop 条件

- 基础设施工作开始早于 Q0/Q1，挤占结构质量和产品验证；
- 新引擎仍不能证明取消、重复副作用和 pointer 原子性；
- 迁移需要修改未批准的公共 API 或 legacy persisted graph；
- 故障测试只能靠 mock 通过，真实 kill/restart/restore 不通过；
- 运营复杂度大幅增加，却没有对应的可靠性收益。

---

## 7. ADR-08：执行、质量、发布状态与 Legacy API

### 7.1 产品判断

执行成功、质量通过和已发布必须分开，这是修复“publish=false 仍被当成已生成”
的核心产品决定，应立即批准。

但 Workflow 中给旧 API 的精确状态映射仍可能把语义阻断伪装成基础设施失败，
也可能破坏只认识旧枚举的客户端。内部三状态与公共 API 迁移必须拆开。

### 7.2 审批决定

- `DESIGN = SPLIT_DECISION`
- vNext 内部三状态、诊断状态和 fail-closed adapter：
  `IMPLEMENTATION = GO_NOW`
- 现有公共 HTTP schema/enum 的精确修改：`HOLD`
- 新状态 internal/shadow UX：可在 Q0 后启用
- 公共 API 迁移和旧客户端切换：`ACTIVATION = NO_GO`

### 7.3 批准范围

- `execution_status`、`quality_status`、`publication_status` 正交保存。
- `succeeded + blocked/review + draft` 是合法且重要的产品结果。
- 只有 Publication Pointer 的目标可以对旧客户端表示为 completed。
- blocked/review 不返回公开 `MindMapResult`，也不显示“思维导图已生成”。
- legacy adapter 单向、不可回读、无法无损表达时 fail closed。
- 历史 `completed + publish=false` 不改写，只做 sidecar 诊断。
- owner 必须由认证 principal 派生，不能由 owner header 决定。

### 7.4 不批准

- 当前就修改旧状态 enum、响应 schema 或历史持久化合同。
- 把所有 `succeeded + blocked` 永久映射为通用 `failed`，掩盖真实原因。
- adapter 自行合成 structural/quality/publish gate 为 `true`。
- draft Projection 直接下转换为 completed legacy result。
- 由调用方提交 publication status、quality PASS 或 owner。

### 7.5 公共 API 解锁证据

- 完整客户端和消费者清点，包括前端、脚本、导出、监控和第三方调用；
- OpenAPI snapshot、旧客户端契约和历史任务读取测试；
- 选择 additive sidecar、版本化 `/v2` 或明确迁移方案；
- blocked/review/published 的产品文案与行为通过用户测试；
- dual-read/dual-report 阶段无状态歧义；
- adapter P0 和 owner P0 已关闭。

### 7.6 Stop 条件

- 任一客户端仍把 blocked/draft 当 completed；
- 旧接口为了兼容而伪造 PASS；
- 内部状态被压回单一 enum，无法定位失败阶段；
- 公共迁移无法回滚或会改写历史记录；
- 安全 principal 与 owner scope 仍未绑定。

---

## 8. ADR-09：Canonical / Projection 1.0

### 8.1 产品判断

Canonical DAG 与面向具体任务的单父 Projection 分离，是兼顾知识正确性和思维导图
可读性的正确产品架构，应批准。

当前 vNext v0 仍存在 relation 自签和 `visible[0]` 选父两个 P0，且默认节点预算、
布局和 1.0 schema 尚未通过真实产品研究。因此批准实现和修复，不批准立即冻结 1.0
或公开导出。

### 8.2 审批决定

- `DESIGN = APPROVE_WITH_REVISION`
- Canonical/Projection candidate、独立 relation task、确定性 view policy：
  `IMPLEMENTATION = GO_NOW`
- 正式 `1.0` freeze：`HOLD`
- diagnostic/internal rendering：Q0 后可启用
- 用户发布、公开 PNG/PDF/JSON：`ACTIVATION = NO_GO`

### 8.3 批准范围

- Canonical 保存多父、未决、拒绝、证据和历史；Projection 为具体任务选择一个显示父。
- Projection 只能选择 accepted direct canonical edge，不能发明 semantic parent。
- relation assessment 来自独立 task，Canonical builder 不得构造自己的支持票。
- parent policy 必须版本化、确定、对 relation 输入排列不敏感。
- 无法稳定选父时进入 review/diagnostic，禁止选列表第一项。
- 每个 Projection 保存 LossManifest、alternate/suppressed edge、aggregation mapping。
- overview、section focus、review、diagnostic、search、export 使用不同 view purpose。
- 默认 overview 按稳定 source order 呈现，不使用任意左右分桶表达语义。
- 首屏只展示课程骨架和少量锚点；完整 Canonical 通过展开、聚焦和搜索访问。
- Web、mobile、PNG、PDF 和 JSON 共享同一 semantic fingerprint。

### 8.4 待校准

- overview 32、section 48、mobile 18、root 下 5-9 个一级节点；
- 单侧、径向或其他 geometry 的最终视觉策略；
- aggregation 的默认触发和标签；
- 1.0 schema 的兼容保证和 upcaster；
- 不同课程类型的默认 view policy。

这些数字和策略可作为原型起点，不能为了达标隐藏 Canonical 内容或改变语义。

### 8.5 完成证据

- relation 顺序全排列或随机扰动不改变 selected parent 和 semantic fingerprint。
- 每个显示节点除 root 外恰有一个合法显示父，且无 root fallback。
- independent relation verifier 的 producer、model/policy 和 evidence 可追溯。
- LossManifest 完整列出全部隐藏、聚合、alternate 和 suppressed 项。
- 跨介质只允许 geometry 差异，不允许节点、标签、父边和状态差异。
- “醛和酮”overview 无正文残片 root/L1，章节顺序稳定，首屏不再堆叠 250 余节点。
- 教师/学生能从 overview 进入 section 并找到精确证据。

### 8.6 Stop 条件

- 输入 relation 顺序改变用户看到的树；
- 为了单根或节点预算自动补边、升根、删难项；
- Projection label 或聚合改变 Canonical 含义；
- Web、PNG、PDF、JSON 的语义指纹不一致；
- 视觉更整齐但章节定位、理解或来源追溯没有改善；
- 1.0 freeze 早于 Gold、兼容评审和至少两轮形成性产品研究。

---

## 9. ADR-10：Quality / Release / Security 签名与撤回

### 9.1 产品判断

完整 closure digest、evaluator provenance、trusted-store Governor、撤回和不可变
ReleaseEvent 是真实发布所必需的。固定 `2-of-3` 或指定 Cosign 不是当前必然正确的
组织方案；如果三个签名最终由同一服务身份控制，只会制造审批幻觉。

### 9.2 审批决定

- `DESIGN = SPLIT_DECISION`
- closure digest、evaluator build、provenance、withdraw/revoke：
  `IMPLEMENTATION = GO_NOW`
- cryptographic signer abstraction 和 key rotation 测试：可以实施
- 固定 Quality/Release/Security `2-of-3`、Cosign 或具体 KMS：
  `HOLD`
- `ACTIVATION = RELEASE_SIMULATION_ONLY`

### 9.3 批准范围

- QualityAttestation 绑定完整 artifact closure、policy 和 evaluator build。
- 任一 material input 变化自动使旧 attestation 失效。
- Governor 只从受信 store 加载 attestation、security result、API approval、
  canary observation 和 pointer history。
- release、rollback、withdraw、supersede 和 revoke 形成 append-only event。
- 已撤回 revision 不可重新发布，除非新 closure 和新授权完整通过。
- signer identity、key version、签名时间和有效期可审计。

### 9.4 不批准

- 调用方自报 readiness boolean 或 report digest。
- 同一进程同时生成质量事实、批准事实和安全事实，却包装成多方签名。
- 在没有密钥生命周期、轮换、撤销和审计主体时引入签名工具。
- 用签名替代质量 Gold、安全红队或产品研究。
- 删除历史 artifact 来完成撤回。

### 9.5 2-of-3 解锁证据

- 明确三个真实独立的责任主体和事故响应职责；
- 威胁模型证明多签能降低已识别风险，而不是只增加流程；
- signer compromise、key rotation、revocation 和 emergency withdrawal 演练通过；
- live search 启用时 Security 具有不可绕过的 veto；
- 运维团队能在目标恢复时间内完成撤回。

### 9.6 Stop 条件

- release 仍可由一个调用方构造全部证明；
- closure 不包含 source、Inventory、Region、Claim、Graph、Projection 和 evaluator；
- 密钥丢失或轮换会让系统无法撤回；
- 签名通过但 hard metric、owner 或 artifact integrity 失败；
- 治理复杂度超过团队真实职责分工。

---

## 10. ADR-11：产品 UX、HITL 和可访问性

### 10.1 产品判断

**批准并列为 P0。** 当前问题不是后台是否成功生成 JSON，而是用户看到的图是否能
理解、能追溯、能识别未决，并且不会被系统误导为“已经完成”。诊断 UX、局部 review
和可访问性不是发布前美化，而是质量合同的一部分。

### 10.2 审批决定

- `DESIGN = APPROVE`
- `IMPLEMENTATION = GO_NOW`
- 内部形成性测试：`ACTIVATION = GO_AFTER_Q0`
- 公网用户、公开分享和正式导出：`NO_GO`，直到 Q3/Q5

### 10.3 批准范围

- blocked_document/claim/semantic/evidence、review_required、draft 和 published
  有不同界面、文案和允许操作。
- blocked/review 状态只显示诊断、影响范围和下一步，不显示完成态教学图。
- ReviewTask 一次只问一个问题，提供 2-3 个具体选项和有限首屏证据。
- 客户端只提交 option 和 rationale，服务端推导 action/target。
- 人工决定 append-only，有 revision fence、影响分析和最小局部 replay。
- 人工不能绕过 owner、lineage、证据、无环、quality 和 pointer 硬门。
- overview、section、证据追溯、review 和导出形成完整任务流。
- Web 以 WCAG 2.2 AA 相关要求为基线；Canvas 同步提供 DOM tree/长描述。
- PNG 必须随附结构化可访问等价物。
- 公开 PDF 若声称可访问，必须通过批准的 PDF/UA profile；否则必须明确限制并提供
  可访问 HTML 等价物。

### 10.4 修订

- 8 名教师、12 名学生只批准为首轮形成性研究起点，不是生产统计证明。
- SUS、任务时间、节点字号和目标尺寸候选值用于发现问题，最终门需结合真实用户校准。
- review 数量不设“越多越安全”。当一份文档需要大量专家修图时，应判为系统性质量
  阻断，而不是把产品变成人工制图工具。
- 不要求用户理解内部 Agent、Gate 或 artifact 术语；界面只表达任务、证据和结果状态。

### 10.5 完成证据

- 用户不会把 blocked/review/draft 误认为 published。
- 教师和学生能完成章节定位、概念理解、来源追溯、冲突复核和导出阅读。
- 键盘、屏幕阅读器、低视力、移动端和桌面核心流程均被真实验证。
- 390x844 和 1366x768 无文本裁切、重叠、不可触达控件或状态遮挡。
- 首屏不展示完整大图微缩图；移动端默认章节大纲和详情。
- review 决定产生可预测的 affected replay，未受影响分支不重算。
- “醛和酮”测试中用户能快速识别课程骨架，并指出节点对应的课件证据。

### 10.6 Stop 条件

- 用户仍把质量阻断理解为“系统已经生成，只是有警告”；
- review 任务含糊、一次处理多个问题或要求编辑原始 JSON；
- 人工复核量随文档规模线性爆炸；
- 外部扩展、课件事实和未决项视觉上不可区分；
- 为适配移动端把整图缩小到不可读；
- 可访问性问题被推迟到 public canary 后处理。

---

## 11. ADR-12：Canary、样本、Sticky Assignment 和 Rollback

### 11.1 产品判断

分阶段 canary、sticky assignment、顺序事件和 fail-closed rollback 是正确方向。
但 `1% -> 5% -> 20% -> 50%`、固定 72 小时和固定样本数只能是初始候选，不能在
未知流量、基线风险和严重错误率下被提前批准为通用策略。

### 11.2 审批决定

- `DESIGN = APPROVE_WITH_REVISION`
- policy contract、simulator、sticky assignment、append-only events、
  rollback/withdraw drill：`IMPLEMENTATION = GO_NOW`
- internal allowlist：`ACTIVATION = GO_AFTER_Q0_Q1_Q2_Q3_Q5`
- public canary 和 default：`NO_GO`

### 11.3 批准范围

- rollout 必须逐阶段推进，不能跳过前序阶段或复用样本。
- assignment 以 owner/document/source_group 为稳定单位，避免同源材料跨版本污染。
- 每次 ADVANCE/HOLD/ROLLBACK 绑定同一 candidate digest、独立观察窗口和 event 序号。
- 任一 P0、安全、owner、gate bypass、质量失败公开结果立即 rollback/withdraw。
- evidence 不足返回 HOLD/INCONCLUSIVE。
- rollback 恢复最后一个已知良好的 vNext pointer。
- 尚无良好 vNext pointer 时回退为 feature-off 或 diagnostic-only。
- 禁止自动把流量交回已知错误的 v56 结果。

### 11.4 待校准

- 具体流量百分比和每档持续时间；
- 每个主要指标和严重事件上界所需的独立 source-group 数；
- look schedule、alpha spending 或 anytime-valid 方法；
- baseline、non-inferiority margin 和改进主指标；
- internal allowlist 的租户、领域和数据分类边界。

这些必须在 release-specific policy 中预注册，不能在看到结果后调整。

### 11.5 完成证据

- Governor 从受信 store 重建 readiness、quality closure、security 和前序 event。
- 调用方无法通过构造 boolean、样本数、stage 或随机 digest 推动 pointer。
- sticky assignment 在重试、登录设备变化和 worker 变化后保持稳定。
- rollback、withdraw、cancel、pointer CAS 和持续旧客户端读取演练通过。
- 每档报告独立 source-group、最差 slice、严重错误、质量、延迟、成本和人工负担。
- 任何 public candidate 都有最后良好 vNext 或 feature-off 回退。

### 11.6 Stop 条件

- 任一错 root/L1、严重 premature STOP、高价值遗漏或错误公开关系；
- privacy、安全、owner、pointer/event 或 gate bypass P0；
- 统计结论依赖节点/边数量而不是独立文档/source-group；
- 样本重复使用、阶段跳跃或观察窗口不独立；
- rollback 不能在目标时间完成；
- candidate 改变后继续沿用旧 canary 证据。

---

## 12. 实施顺序

### 12.1 Workstream A：先让结果可信

可以进入当前实施队列：

1. 关闭八项 P0，并建立 Q0 自动阻断。
2. ADR-06 Gold、质量合取、INCOMPLETE 和 sealed evaluation。
3. ADR-08 内部三状态、owner principal、legacy adapter fail-closed。
4. ADR-09 independent relation task、排列不变 Projection 和 LossManifest。
5. ADR-11 blocked/review/draft/published 产品流程和首轮可用性原型。
6. ADR-07 最小 StageCommit/cancel/cost/fault semantics。

该工作流的验收不是“代码合并”，而是能对真实文档诚实地产生：

```text
publishable teaching view
or
specific blocked/review diagnosis
```

### 12.2 Workstream B：再提高语义能力

Q0/Q1 通过后：

1. ADR-03 inferred Region public-fixture shadow。
2. ADR-05 Standard/Precision 配对校准。
3. 关闭真实 replan loop，并验证最小受影响祖先。

任何能力只在目标 slice 晋级，不要求一次替换所有文档类型。

### 12.3 Workstream C：最后增加外部能力和发布

Q0-Q3 通过后：

1. ADR-04 live public-fixture search 和安全红队。
2. ADR-10 closure/revocation/release simulation。
3. ADR-12 internal allowlist、rollback drill 和统计 policy。
4. 有真实触发证据时再评审 Postgres、durable engine 和多方签名。

### 12.4 每阶段产品审查包

每次申请晋级必须提交：

```text
candidate scope and user problem
exact code/model/prompt/policy/data digests
closed P0 list
gold and blind report
worst documents and serious errors
cost/latency/review burden
security/privacy evidence when applicable
UX findings
rollback/withdraw plan
known limitations
requested activation scope
```

缺一项时返回 `INCOMPLETE`，不靠口头解释补齐。

---

## 13. 最终授权

截至 2026-07-30：

- 学生竞赛覆盖条款已生效；本地或隔离竞赛演示按精简 DoD 验收。
- ADR-03 至 ADR-12 已完成产品审批，不再标记为笼统的 `PROPOSED FOR REVIEW`。
- 本文只批准各 ADR 明列的方向和实施范围；延后/否决条款同样具有约束力。
- Workstream A 可以进入实施排期，但本文没有自动启动代码修改。
- Workstream、任务编号、参考排期和逐项 DoD 以
  `docs/MINDMAP_EXECUTION_PLAYBOOK.md` 为准。
- 生产模式下，Inferred Region、live search、Standard/Precision live pilot、
  公共 API、正式 Canonical/Projection 1.0、release candidate、internal allowlist
  和 public canary 仍分别受 Q0-Q5 约束；这些门不属于当前竞赛交付。
- 私有课件 live web egress、公共 API 未版本化变更、Postgres/Temporal 直接迁移、
  固定 2-of-3 签名和公网流量切换当前均未获授权。
- 任一 material contract、gold denominator、模型/Judge、搜索策略、公共 API、
  publication 或 traffic scope 变化，必须形成新的书面审批或 release-specific
  StageAuthorization。

本审批的产品底线是：

> 宁可明确告诉用户“这一部分尚不能可靠生成”，也不再交付一张结构合法、
> 视觉完整、但知识层级混乱的图。
