# 思维导图 vNext 执行证据与 Gate 结论

- 执行日期：2026-07-30
- 执行书：`docs/MINDMAP_EXECUTION_PLAYBOOK.md`
- 分支：`experiment/new_bone`
- 执行基线 HEAD：`4b28c75025481509dccdb28fe3459ee33ea27f4d`
- 最终程序结论：`HOLD / INCOMPLETE`
- 激活结论：`REJECTED FOR ACTIVATION`
- 公网、internal allowlist、live private model/search：`NO-GO`

本报告区分三件事：

1. 本仓库中可执行的代码和自动测试是否完成。
2. 独立 reviewer、真实 Gold、真实用户和真实运维证据是否存在。
3. 当前候选是否获准发布。

自动测试通过不能替代第 2、3 项。实现者没有给自己的 Gate 签 PASS。

## 1. 候选身份

```text
branch:
  experiment/new_bone

HEAD:
  4b28c75025481509dccdb28fe3459ee33ea27f4d

code-only changed-file manifest:
  62 files

code-only manifest sha256:
  ac541ac93311f860c932e085ad38c7b3364edfa8e895aebe0e5f92b8823d1e3d

schema manifest sha256:
  c71af4d5b80f6519ce8699835122b958873363095ddafde96f64e2331a7c5966

legacy OpenAPI snapshot:
  sha256:111e35217a1e0c1896ec8b860658b5f9be544e36cb2132686fac5ed73ec116ea

vNext renderer semantic fingerprint:
  sha256:080bf4a88dd3807b53d70b05fb9b525e21873c7644a4719e5fb07da9ee1ed114
```

code-only manifest 排除本报告和其他 `docs/` 更新，包含 `.gitignore`、backend
实现、测试和生成 schema。工作树没有 reset、checkout 或覆盖用户提交。

## 2. M0 证据

| 项目 | 结果 |
| --- | --- |
| Python | `3.12.3` |
| Node.js | `22.23.2` |
| pnpm | `10.14.0` |
| gh | `2.96.0`，已认证为 `mizy06`，仓库权限 `ADMIN` |
| CodeGraph | `1.5.0`，215 files、5774 nodes、17652 edges、WAL、up to date |
| schema | 36 contracts、36 schema、37 files including manifest |
| public API | legacy snapshot tests 通过，无 path/model 漂移 |
| publication | vNext 无 publish/legacy public route，renderer 固定 `publication_enabled=false` |
| live egress | recorded/deterministic source-only，默认 `no_egress=true` |

`gh auth status` 已确认账号 `mizy06`，认证 scope 为 `repo`、`workflow`、
`read:org` 和 `gist`。实现前的公开 GitHub-first 使用 Web/REST、raw source、
commit/tag 和本地依赖源码完成；认证后又补跑 `gh search issues/prs/code`。

M0-03 远端执行骨架已经建立：

- [总控 issue #26](https://github.com/mizy06/ZLB_2/issues/26)
- Q0 八项 P0 issue：`#1` 至 `#8`
- Q1 六项 Gold/quality issue：`#9` 至 `#14`
- Runtime、Q2、Q3、Q4、Q5 epic：`#15` 至 `#19`
- Q0-Q5 Gate review：`#20` 至 `#25`

| Work package | Remote issue | 实现 owner | 必需独立 verdict |
| --- | --- | --- | --- |
| Q0-01 replan barrier | `#8` | Semantic Structure Lead | Quality Lead |
| Q0-02 quality conjunction | `#3` | Quality Lead | Schema Steward |
| Q0-03 raw inventory | `#1` | Source Fidelity Lead | Independent Red Team |
| Q0-04 principal owner | `#7` | Runtime Lead | Security Lead |
| Q0-05 trusted governor | `#2` | Release Lead | Quality Lead |
| Q0-06 relation stages | `#6` | Semantic Lead | Model/Quality reviewer |
| Q0-07 view parent policy | `#4` | Product/HITL Lead | Semantic Lead |
| Q0-08 legacy closure | `#5` | Runtime Lead | Product Approver |
| Q0-09 integrated attack/Gate | `#20` | Independent Red Team | Product Approver |

Issue 中的实际人员仍标为 `TBD`；创建 issue 不能替代独立 owner/reviewer 分配，
因此 M0 和 Q0 Gate 继续为 `HOLD`。

## 3. GitHub-First

既有查询和采用/拒绝记录见 `docs/VNEXT_IMPLEMENTATION_MATRIX.md` 第 6 节。
本轮追加检查：

```text
current repository:
  RawSourceManifest
  RelationAssessmentLedger
  evaluate_quality_gate
  notes_slide
  cNvPr / descr / show

upstream:
  scanny/python-pptx
  docling-project/docling

versions:
  python-pptx 1.0.2
```

证据：

- [python-pptx v1.0.2](https://github.com/scanny/python-pptx/tree/v1.0.2)
- [python-pptx modernization commit](https://github.com/scanny/python-pptx/commit/c38d5f5c6850ae3aefdc3a86dbf9bd0af35cf346)
- [python-pptx MIT license](https://github.com/scanny/python-pptx/blob/master/LICENSE)

上游 `has_notes_slide` 可以无副作用判断 notes part，但访问 `notes_slide` 可能创建
新 part；公开 `cNvPr` 类型也没有完整暴露 alt-text 属性。认证后的 issue/PR 查询
没有找到同时覆盖 hidden/notes/alt/off-slide 与本项目 owner-scoped Inventory 的
兼容实现；code search 只确认了 `python-pptx` 的 notes API/source/tests/docs 和
Docling 的 notes 读取路径。最终采用标准库 ZIP/XML 的最小只读 inspector，没有
复制上游代码或增加生产依赖。

## 4. Q0 实现证据

| 项目 | 本地代码与攻击结果 | 状态 |
| --- | --- | --- |
| Q0-01 Open Replan | open/accepted quarantine；closed 绑定 closure digest + TreeRevision；durable reuse 保留 terminal replan artifact | `EVIDENCE_COMPLETE / HOLD` |
| Q0-02 Quality | 纯 evaluator；`BLOCK > INCOMPLETE > REVIEW > PASS`；空 hard set、缺阈值均 INCOMPLETE；contract/store 重验证 | `EVIDENCE_COMPLETE / HOLD` |
| Q0-03 Inventory | PDF native/render/parser；PPTX ZIP/XML hidden/notes/alt/off-slide/object；mismatch 进入 `MUST_HAVE + unresolved` | `EVIDENCE_COMPLETE / HOLD` |
| Q0-04 Principal | owner 只来自 `PrincipalContext`；header 无 authority；跨 owner 404 并记录 security event | `EVIDENCE_COMPLETE / HOLD` |
| Q0-05 Governor | readiness/observation 只允许 trusted aggregator 写；Governor 从 SQLite 重载 run/evidence/observation | `EVIDENCE_COMPLETE / HOLD` |
| Q0-06 Relation | proposal、assessment、canonical 为三个 artifact/stage；verifier 唯一输入是 proposal ref；canonical 拒绝语义改写 | `EVIDENCE_COMPLETE / HOLD` |
| Q0-07 Parent | 与 relation 输入顺序无关；同优先级 tie 使用稳定诊断选择并强制 review | `EVIDENCE_COMPLETE / HOLD` |
| Q0-08 Adapter | 只接受 published pointer、PASS attestation、published trusted run；legacy PASS 字段派生而非硬编码 | `EVIDENCE_COMPLETE / HOLD` |
| Q0-09 Red Team | 13 个 integrated attack test 全绿 | `SELF-EXECUTED / HOLD` |

`HOLD` 原因不是自动测试失败，而是执行书明确禁止实现者给自己的 Q0 Gate 签署
`ACCEPTED`。还需要独立 Red Team、Schema Steward、对应 reviewer 和 Product
Approver 对 schema diff、攻击覆盖和残余风险给出 verdict。

## 5. 后续 Gate 审计

| Gate | 已有基础 | 缺失硬证据 | 结论 |
| --- | --- | --- | --- |
| Q1 Gold | Gold/evaluator contract、source-group leakage、worst slice、risk coverage、five-run stability 工具 | 12/18/30 共 60 真实文档、双标、SME 仲裁、sealed custodian、冻结阈值、一次 blind | `HOLD / INCOMPLETE` |
| Q3 Product | 三状态、overview/focus、evidence、review、Web/Mobile/PNG/PDF/JSON、自动 a11y contract | 8 教师、12 学生、两轮研究、真实屏幕阅读器/低视力/打印任务、不同领域任务 | `HOLD / INCOMPLETE` |
| Runtime | lease、CAS、stage reuse、outbox、orphan、deterministic replay、release transaction | vNext heartbeat/cancel/cost 完整闭环、每边界真实 SIGTERM/SIGKILL、contention、backup/restore、RTO/RPO | `HOLD / INCOMPLETE` |
| Q2 Semantic | recorded explicit Region/Claim 与 router contract | Q0/Q1 独立 ACCEPT、真正 replan loop、inferred Region、live public fixture、paired blind、模型独立性校准 | `NOT AUTHORIZED / HOLD` |
| Q4 Search | SearchIntent、默认拒绝 Gateway、SSRF/redirect/MIME/injection/snapshot tests | Q0/Q1 ACCEPT、真实 public-fixture connector、threat model、retention/deletion、blind value pilot | `NOT AUTHORIZED / HOLD` |
| Q5 Release | closure digest、append-only event、pointer CAS、withdraw/rollback primitives、canary simulator | Q0-Q4 verdict、产品研究、runtime DR、API 决定、StageAuthorization、签名/key rotation 外部证据 | `HOLD / INCOMPLETE` |
| Public canary | 无 route、无流量任务 | 新 StageAuthorization 和全部前序 Gate | `NO-GO` |

历史 legacy 容器的 kill/backup/restore 记录不能替代 vNext 当前候选的完整 Runtime
fault matrix；合成 fixture 也不能替代真实 Gold 或真实用户研究。

## 6. 自动验证

```text
.venv/bin/python -m unittest discover -s backend/tests -p 'test_vnext*.py' -v
  Ran 182 tests in 20.802s
  OK

.venv/bin/python -m unittest discover -s backend/tests -v
  Ran 718 tests in 32.707s
  OK (skipped=1)

.venv/bin/python -m backend.vnext.cli export-schemas --check
  {"changed": []}

.venv/bin/python -m pip check
  No broken requirements found.

git diff --check
.venv/bin/python -m compileall -q backend/app backend/vnext backend/tests
  passed

cd frontend && pnpm test
  7 passed

cd frontend && pnpm exec tsc -b --pretty false
  passed

cd frontend && pnpm build
  passed

cd frontend && pnpm exec playwright test
  2 passed
```

视觉证据：

- 1366x768：Canvas visible，3504 个采样非白像素。
- 390x844：outline + detail，Canvas 按产品策略隐藏，目标最小 44px。
- 320x800：无横向溢出、无重叠、无可见文本裁切。
- 200% 文本：无横向溢出、无重叠、键盘 traversal 成功。
- 四组均有同步 DOM tree、长描述、semantic fingerprint match、0 console error。

隔离报告：

```text
/root/.codex/visualizations/2026/07/30/
019fb153-89cb-7e62-8733-a1e40af3260c/
vnext-final-vTLrGf/visual-checks.json
```

该 JSON 同时记录 code-only manifest digest
`ac541ac93311f860c932e085ad38c7b3364edfa8e895aebe0e5f92b8823d1e3d`
和 render bundle ID `render_bundle_3a19378c2997f2676bb4fb2d0368a4bd`。

已知 warning：

- Starlette `TestClient`/`httpx` deprecation，非阻断，不在 Q0 升级依赖。
- Vite 699.49 kB chunk warning，非阻断。
- 唯一 skip 是宿主缺少 `age`/`age-keygen` 的 legacy 密钥往返。

## 7. 回滚与禁用

- vNext shadow API 默认关闭；保持 `VNEXT_SHADOW_ENABLED=false`。
- vNext 没有 public publish route、legacy route 或默认 rollout。
- renderer 合同固定 `publication_enabled=false`。
- model/search 保持 recorded/source-only/no-egress。
- 不创建 internal allowlist，不写 public pointer，不切流量。
- 候选通过 Draft PR 发布；代码回滚应使用
  `git revert <candidate-commit>`，不得使用 reset 覆盖用户历史。
- schema 如未获 Steward 兼容批准，整批 proposal/assessment/raw-manifest
  contract 保持不激活，不做部分启用。

## 8. 最终 Verdict

```text
Q0 code candidate: EVIDENCE_COMPLETE
Q0 independent Gate: HOLD
Q1: HOLD / INCOMPLETE
Q3: HOLD / INCOMPLETE
Runtime: HOLD / INCOMPLETE
Q2: NOT AUTHORIZED
Q4: NOT AUTHORIZED
Q5: HOLD / INCOMPLETE
Internal allowlist: NO-GO
Public canary: NO-GO
```

因此本轮允许声称：

> 八项 Q0 P0 的本地代码候选和自动攻击矩阵已经完成并全绿，默认关闭和
> fail-closed 边界保持有效。

本轮不允许声称：

> Q0 已由独立团队 ACCEPTED，产品质量已被真实 Gold/用户研究证明，或 vNext
> 可以进入 internal/public 流量。
