# ZLB Mind Map Agent

将课程 PDF、PPTX、DOCX、TXT 或 Markdown 转换为带文本与视觉证据、唯一根和唯一主父节点的课程思维导图。

## C+ 架构

当前 `experiment/bone` 已接入完整的高代码 C+ 主流程：

```text
确定性解析与视觉资产提取
  -> Text / Visual Content Unit Ledger
  -> Global Theme Synthesizer
  -> Root Planner
  -> 递归 Branch Team 子图并发执行
  -> 共享 SQLite 证据黑板
  -> Merge / Reassignment / Coverage Audit
  -> Top-k 父候选召回
  -> 独立校验 / 双校验 / 仲裁
  -> OR-Tools CP-SAT 主树求解
  -> NetworkX 硬校验
  -> 人工复核与图版本
  -> 主树 + 跨链 + 证据 + 质量报告
```

核心实现：

- `backend/app/cplus_pipeline.py`：LangGraph Main Supervisor 与阶段检查点。
- `backend/app/agents.py`：主题规划、递归 Branch Team、覆盖审计、视觉融合和父边校验。
- `backend/app/blackboard.py`：SQLite 内容单元、候选、决策、复核项、检查点和图版本。
- `backend/app/visual_analysis.py`：整页视觉理解、bbox 决策与区域裁剪。
- `backend/app/mindmap_engine/`：稳定归一、Top-k 召回、CP-SAT、NetworkX 校验和视觉资产服务。
- `backend/app/review_service.py`：人工保留、删除、改父、改名和版本写入。
- `frontend/src/`：树形工作台、跨链开关、证据 Inspector、质量门和复核队列。

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

- 每次成功生成的导图都会自动写入 SQLite 历史记录。
- 工作台顶部的“历史记录”可重新打开或删除历史任务。
- 图版本、人工复核结果和质量报告会随历史任务一起保留。
- 结果工具栏的“保存 JSON”会下载完整结构化结果。
- 主树画布右下角的下载按钮会保存高清 PNG。

## 模型角色

当前工作台只启用 Kimi Provider：

- API 地址：`https://api.moonshot.cn/v1`
- 模型 ID：`kimi-k3`
- 推理强度：`low`、`high` 或 `max`，默认 `low`
- 生成、父边校验、视觉理解与仲裁使用独立提示词和独立模型调用

Kimi K3 的请求使用 `reasoning_effort` 和 `max_completion_tokens`，不显式发送旧的 `temperature` 参数。模型检查只读取 `/models`，不会为了检查权限额外发起一次推理。

运行档位：

- `standard`：Kimi 生成角色 + 独立 Kimi 校验角色 + CP-SAT。
- `precision`：高风险父边增加第二个独立 Kimi 校验调用；分歧时调用独立仲裁角色。

任一角色不可用时只降级对应阶段。最终结果会在 `degraded_components` 和 `warnings` 中说明，不会静默丢弃。

## 配置

支持以下环境变量：

```text
KIMI_API_KEY
MOONSHOT_API_KEY
KIMI_BASE_URL
KIMI_MODEL
KIMI_REASONING_EFFORT
KIMI_SECRETS_FILE
KIMI_AGE_IDENTITY_FILE
AGE_EXECUTABLE

MINDMAP_DATA_DIR
MINDMAP_BLACKBOARD_PATH
MINDMAP_SOLVER_TIMEOUT_SECONDS
MINDMAP_VISION_MAX_PAGES

EXTERNAL_ENGINE_TOKEN
ASSET_ACCESS_TOKEN
ASSET_PUBLIC_BASE_URL
```

后端启动时按以下顺序取得密钥：

1. 当前进程已有的 `KIMI_API_KEY`。
2. 当前进程已有的 `MOONSHOT_API_KEY`，并映射为 `KIMI_API_KEY`。
3. 使用本机 age 私钥解密 `kimi.enc.env.age`，只在内存中解析并写入当前后端进程的 `KIMI_API_KEY`。

默认密文位置是仓库上一级的 `kimi.enc.env.age`，默认私钥位置是仓库上一级的 `.secrets/kimi-age-identity.txt`。可通过环境变量覆盖。解密过程不会生成明文文件，API Key 不会发送到前端、日志或 SQLite 决策记录。

## 任务 API

- `POST /api/jobs`：上传课件并启动 C+ Supervisor。
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
- 主父边平均置信度。
- 临时保底边数量。
- 待人工复核数量。

默认质量门：

```text
topology_valid == true
evidence_coverage == 1
provisional_edge_count == 0
weighted_content_coverage >= 0.78  # standard
weighted_content_coverage >= 0.86  # precision
```

## 测试

```powershell
.\.venv312\Scripts\python.exe -m unittest discover -s backend\tests -v

cd frontend
pnpm build
```

测试覆盖旧解析兼容层、稳定 chunk ID、PPTX 位置、候选归一、CP-SAT 主树、临时边复核、视觉裁剪、C+ 端到端流水线、SQLite 恢复和人工图版本。

## Docker

镜像安装 age、LibreOffice Impress 与 Poppler，并在构建阶段生成前端生产包：

```powershell
docker build -t zlb-mindmap-agent .
```

生产部署使用 `compose.prod.yml`。服务器需要在
`runtime/secrets/` 中提供：

```text
kimi.enc.env.age
kimi-age-identity.txt
```

随后运行：

```powershell
docker compose -f compose.prod.yml up -d --build
```

Compose 默认将同一个生产服务映射到主机的 `5173` 和 `8000`，SQLite 历史记录保存在 Docker 持久卷中。`runtime/`、私钥、公钥和明文 ENV 均被 Git 忽略。

## 历史低代码资料

[workflow/bailian-workflow-blueprint.yaml](workflow/bailian-workflow-blueprint.yaml) 和相关说明仅作为早期低代码验证资料保留，不参与当前 Kimi Provider 的本地主任务。
