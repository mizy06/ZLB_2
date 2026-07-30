# vNext Clean-Room 代码清点

- 清点日期：2026-07-29
- 分支：`experiment/new_bone`
- 基线提交：`297da939835dc9b748a33bd80d368702d7de687d`
- 决策依据：`docs/MINDMAP_SYSTEM_REDESIGN.md` ADR-01

## 1. 工作树基线

开始 S0 前，工作树已有大量用户改动：

- 40 个 tracked 文件被修改；
- 2 个 tracked 文件被删除；
- 64 个 untracked 文件；
- 后端测试静态声明数为 536。

这些内容全部视为用户工作。本次没有回退、覆盖或重排任何旧实现，只在
`backend/vnext/`、独立 vNext 测试/夹具和两份 vNext 文档中新增实现；依赖文件只
增加 `rfc8785==0.1.4`。

## 2. 旧架构污染面

旧双向 C+ 的结构权威不是集中在一个 Agent，而是分布于抽取、分桶、候选生成、
normalize、solver 和完成状态。因此不能通过替换一个 prompt 或 Agent 获得干净的
单向结构链。

| 位置 | 当前行为 | 对 ADR-01 的风险 |
| --- | --- | --- |
| `backend/app/agents.py:909` | 从 ContentUnit 回猜 fallback root/主题 | 源正文重新取得高层结构权威 |
| `backend/app/agents.py:1318` | 按叶容量和节点权重分组 | 调度容量可转化为语义分区 |
| `backend/app/agents.py:1631` | 从正文候选生成 leaf label | 正文残片可成为结构标签 |
| `backend/app/agents.py:2949` | 每个 BranchPlan 补 branch topic | 容量 bucket 直接升级为结构节点 |
| `backend/app/agents.py:3058` | 共享 unit 生成“结构支持映射”文本 | 召回重叠被伪装成关系证据 |
| `backend/app/agents.py:3369` | 为 root/branch/concept 建全局父候选 | Bottom-up 内容参与补父 |
| `backend/app/agents.py:4305` | 无正式父边时把最高分候选改为 provisional | verifier 否决不再单调 |
| `backend/app/mindmap_engine/normalize.py:1159` | 缺根时合成 root | 后层可以补建根 |
| `backend/app/mindmap_engine/normalize.py:1519` | 为 branch/root 追加 provisional 父边 | 无证据父边重新进入候选 |
| `backend/app/mindmap_engine/topology.py:64` | provisional 边可被选择 | provisional 可进入成品树 |
| `backend/app/mindmap_engine/topology.py:609` | greedy fallback 把必选孤儿直接接根 | parentless 不能 abstain |
| `backend/app/pdf_page_knowledge.py:1257` | 页抽取直接产出 ContentUnit/NodeCandidate | Document IR 与发布候选未分层 |
| `backend/app/cplus_pipeline.py:1426` | finalize 保存图并把 run 标为 completed | quality 失败仍可成为完成结果 |
| `backend/app/main.py:330` | 无条件显示“思维导图已生成” | execution success 与 publish 混用 |

结论：`agents.py`、`normalize.py`、`topology.py`、`cplus_pipeline.py` 和
`pdf_page_knowledge.py` 共同构成旧语义闭环。对其中任一处做局部修补，都会让新
合同继续受旧状态、旧候选和旧 fallback 影响。

## 3. 旧公共与持久化边界

以下表面当前均假设单根、完整树和 legacy 状态枚举：

- `backend/app/architecture_schemas.py` 的 `MindMapResult`、`JobView` 和 review
  请求/响应；
- `backend/app/mindmap_engine/schemas.py` 的 normalize/solve/render 合同；
- `/api/jobs`、历史版本、review、JSON/PNG export；
- legacy SQLite graph version、job/run 和 review 表；
- `frontend/src/types.ts`、GraphCanvas、ReviewQueue 和导出流程。

S0 不修改这些类型、路由、SQLite schema、历史 payload 或前端。当前 OpenAPI 和
公共模型已经使用 RFC 8785/SHA-256 指纹冻结。

## 4. 可复用分类

可以继续复用或在后续通过窄 adapter 包装的基础设施：

- `backend/app/auth.py`
- `backend/app/upload_validation.py`
- `backend/app/secret_preflight.py`
- `backend/app/job_runtime.py`
- `backend/app/runtime_manifest.py`

只能作为行为参考或后续 adapter 候选：

- `backend/app/mindmap_engine/visuals.py` 的 render/crop 能力；
- `backend/app/model_provider.py` 的通用 HTTP retry/circuit 行为；
- `PageExtraction`、`PageLayoutBlock` 等低层读取结果；
- `backend/app/claim_fidelity.py`；
- `backend/app/pdf_math_geometry.py`。

禁止被 vNext 语义包直接导入：

- `backend.app.agents`
- `backend.app.cplus_pipeline`
- `backend.app.architecture_schemas`
- `backend.app.mindmap_engine.normalize`
- `backend.app.mindmap_engine.topology`
- `backend.app.review_service`
- `backend.app.visual_analysis`
- `backend.app.pdf_page_knowledge`
- `backend.app.blackboard`
- legacy public/graph schema 模块

架构测试通过 AST 扫描执行该边界。未来唯一允许的 legacy 方向是
`backend/vnext/adapters/legacy_result.py -> MindMapResult`，且该 adapter 的输出
禁止回读为 Canonical Graph。

## 5. Clean-Room 落点

```text
backend/vnext/
  contracts/
  artifacts/
  source_ir/
  source_inventory/
  regions/
  claims/
  canonical_graph/
  projection/
  orchestration/
  adapters/
```

S0 入口是独立 CLI 和独立 owner-scoped filesystem shadow store。它不导入
`main.py`，不打开 legacy blackboard，也不注册 HTTP route。

## 6. 当前结论

采用“新增隔离实现，不在旧闭环内渐进替换”的路径是必要条件，不是代码风格偏好。
只有在 S1-S3 的 source fidelity、omission、split/stop、replan 和 explicit-edge
门通过后，才能讨论单向 adapter 或 shadow 调度接入；在此之前旧链保持只读基线。
