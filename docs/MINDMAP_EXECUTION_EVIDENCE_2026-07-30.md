# 思维导图 vNext 竞赛执行证据

- 执行日期：2026-07-30
- 执行书：`docs/MINDMAP_EXECUTION_PLAYBOOK.md`
- 分支：`experiment/new_bone`
- 执行基线 HEAD：`4b28c75025481509dccdb28fe3459ee33ea27f4d`
- 当前 profile：`STUDENT COMPETITION`
- 最终程序结论：`ACCEPTED FOR COMPETITION`
- 激活结论：`LOCAL / ISOLATED DEMO READY`
- 实际参赛材料：`OWNER REHEARSAL PENDING`
- 生产、多租户公网和私有材料 live search：`NOT CLAIMED`

本报告区分三件事：

1. 本仓库中可执行的代码和自动测试是否完成。
2. 当前候选是否满足学生竞赛的演示、安全和回退底线。
3. 哪些生产级证据被明确移出当前范围。

自动测试、视觉检查和项目所有者授权共同构成竞赛验收；不据此声明生产质量。

## 1. 候选身份

```text
branch:
  experiment/new_bone

execution baseline:
  4b28c75025481509dccdb28fe3459ee33ea27f4d

code candidate commit:
  6a0b17e4099426fe729ab596aa3d8ffc9c9247b5

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

M0-03 的生产 Gate 骨架曾经建立：

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

项目定位调整后，这些 issue 将作为生产历史记录关闭或归档。竞赛 Profile 不要求
实际配置独立人员。

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
| Q0-01 Open Replan | open/accepted quarantine；closed 绑定 closure digest + TreeRevision；durable reuse 保留 terminal replan artifact | `COMPETITION_ACCEPTED` |
| Q0-02 Quality | 纯 evaluator；`BLOCK > INCOMPLETE > REVIEW > PASS`；空 hard set、缺阈值均 INCOMPLETE；contract/store 重验证 | `COMPETITION_ACCEPTED` |
| Q0-03 Inventory | PDF native/render/parser；PPTX ZIP/XML hidden/notes/alt/off-slide/object；mismatch 进入 `MUST_HAVE + unresolved` | `COMPETITION_ACCEPTED` |
| Q0-04 Principal | owner 只来自 `PrincipalContext`；header 无 authority；跨 owner 404 并记录 security event | `COMPETITION_ACCEPTED` |
| Q0-05 Governor | readiness/observation 只允许 trusted aggregator 写；Governor 从 SQLite 重载 run/evidence/observation | `COMPETITION_ACCEPTED` |
| Q0-06 Relation | proposal、assessment、canonical 为三个 artifact/stage；verifier 唯一输入是 proposal ref；canonical 拒绝语义改写 | `COMPETITION_ACCEPTED` |
| Q0-07 Parent | 与 relation 输入顺序无关；同优先级 tie 使用稳定诊断选择并强制 review | `COMPETITION_ACCEPTED` |
| Q0-08 Adapter | 只接受 published pointer、PASS attestation、published trusted run；legacy PASS 字段派生而非硬编码 | `COMPETITION_ACCEPTED` |
| Q0-09 Red Team | 13 个 integrated attack test 全绿 | `COMPETITION_ACCEPTED` |

学生竞赛 Profile 取消多人签署要求，但不取消任何已实现的 fail-closed 行为。

## 5. 生产 Gate 归档

| Gate | 已有基础 | 缺失硬证据 | 结论 |
| --- | --- | --- | --- |
| Q1 Gold | Gold/evaluator contract、source-group leakage、worst slice、risk coverage、five-run stability 工具 | 60 文档、双标、SME 仲裁、sealed blind | `NOT REQUIRED FOR COMPETITION` |
| Q3 Product | 三状态、overview/focus、evidence、review、自动 a11y contract | 20 人两轮研究和生产统计 | `NOT REQUIRED FOR COMPETITION` |
| Runtime | lease、CAS、stage reuse、outbox、orphan、deterministic replay | 完整 kill matrix、contention、RTO/RPO | `NOT REQUIRED FOR COMPETITION` |
| Q2 Semantic | recorded explicit Region/Claim 与 router contract | paired blind 和模型独立性统计 | `OPTIONAL / OUT OF SCOPE` |
| Q4 Search | 默认拒绝 Gateway 和安全测试 | production connector 与价值 pilot | `OPTIONAL / OUT OF SCOPE` |
| Q5 Release | closure、事件、pointer 和回滚 primitives | internal allowlist、canary、多签 | `OUT OF SCOPE` |
| Public canary | 无 route、无流量任务 | 生产授权 | `OUT OF SCOPE` |

若未来恢复生产声明，历史 legacy 容器的 kill/backup/restore 仍不能替代 vNext
当前候选的完整 Runtime fault matrix，合成 fixture 也不能替代真实 Gold 或真实
用户研究；这些限制不阻断当前竞赛 Profile。

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

## 7. 竞赛回退与边界

- vNext shadow API 默认关闭；保持 `VNEXT_SHADOW_ENABLED=false`。
- vNext 没有 public publish route、legacy route 或默认 rollout。
- renderer 合同固定 `publication_enabled=false`。
- model/search 保持 recorded/source-only/no-egress。
- 不创建 internal allowlist，不切生产流量；竞赛演示使用本地或隔离环境。
- 候选通过 Draft PR 发布；代码回滚应使用
  `git revert <candidate-commit>`，不得使用 reset 覆盖用户历史。
- schema 已通过确定性导出和兼容测试；竞赛演示继续使用现有 shadow 边界，不把
  proposal/assessment/raw-manifest 合同升级为生产公共接口。

## 8. 最终 Verdict

```text
Q0 code candidate: ACCEPTED FOR COMPETITION
Automated attack matrix: ACCEPTED
Local/isolated demo: READY
Actual competition-material rehearsal: PENDING OWNER INPUT
Q1/Q3/Runtime production evidence: ARCHIVED
Q2/Q4/Q5 production programs: OUT OF SCOPE
Production readiness: NOT CLAIMED
```

因此本轮允许声称：

> 八项 Q0 P0、自动攻击矩阵和演示视觉检查已经完成并全绿，候选可用于学生竞赛
> 的本地或隔离演示。

本轮不允许声称：

> 候选已获得生产认证、统计教学质量证明、多租户公网发布资格或私有数据联网许可。
