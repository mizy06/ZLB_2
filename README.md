# ZLB Mind Map Agent

将课程 PDF、PPTX、DOCX、TXT 或 Markdown 转换为带文本与视觉证据的思维导图。

## 架构

```text
百炼低代码：
  文档解析 -> 全局主题 -> 分支候选 -> 父边校验 -> 视觉理解

外部 mindmap-engine：
  页面渲染/裁剪 -> 稳定归一 -> Top-k 父候选
  -> CP-SAT 主树求解 -> 硬校验 -> 质量报告
```

现有本地 Demo 继续使用 LangGraph。百炼验证路线通过 HTTP API 节点调用外部引擎，模型只生成候选和判别票，代码负责稳定 ID、去重、证据绑定和合法主树。

## 本地启动

后端使用 Python 3.12：

```powershell
python -m venv .venv312
.\.venv312\Scripts\python.exe -m pip install -r backend\requirements.txt
$env:DEEPSEEK_API_KEY = Read-Host "DeepSeek API Key"
$env:EXTERNAL_ENGINE_TOKEN = Read-Host "External Engine Token"
.\.venv312\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

另开一个终端启动前端：

```powershell
cd frontend
pnpm install
pnpm dev
```

访问：

- 工作台：`http://127.0.0.1:5173`
- 后端 API：`http://127.0.0.1:8000/docs`
- 外部引擎健康检查：`http://127.0.0.1:8000/v1/mindmap/health`

百炼工作空间 API Key 会自动从根目录的 `ZLB-apiKey-*.csv` 读取。DeepSeek Key 只从环境变量读取，不会发送到前端。

## 模型服务

- `deepseek`：默认模型 `deepseek-v4-flash`
- `bailian`：默认模型 `qwen3.7-plus`
- 任一模型不可用时，当前 chunk 自动降级为本地启发式抽取

## 外部 Mind Map Engine

百炼工作流难以稳定实现的能力已拆成独立模块：

- `mindmap_engine/normalize.py`：候选归一、稳定 ID、Top-k 父候选。
- `mindmap_engine/topology.py`：OR-Tools CP-SAT 主树求解和 NetworkX 兜底。
- `mindmap_engine/validate.py`：唯一根、唯一父、无环、根可达和证据校验。
- `mindmap_engine/visuals.py`：PPTX/PDF 页面渲染、原生图片提取和 bbox 裁剪。
- `mindmap_engine/router.py`：供百炼 API 节点调用的 FastAPI 接口。

主要接口：

- `POST /v1/chunks`
- `POST /v1/mindmap/normalize`
- `POST /v1/mindmap/solve`
- `POST /v1/mindmap/validate`
- `POST /v1/mindmap/assemble`
- `POST /v1/mindmap/visuals/render`
- `POST /v1/mindmap/visuals/crop`
- `GET /v1/mindmap/assets/{render_id}/{filename}`

除健康检查外，配置了 `EXTERNAL_ENGINE_TOKEN` 时，调用方需要发送：

```text
Authorization: Bearer <token>
```

视觉资产 URL 使用 `ASSET_PUBLIC_BASE_URL` 作为公网前缀。建议同时设置独立的 `ASSET_ACCESS_TOKEN`。

## Docker 部署

镜像安装 LibreOffice Impress 与 Poppler，用于把 PPTX/PDF 渲染为可供百炼视觉模型分析的页面图片：

```powershell
docker build -t zlb-mindmap-engine .
docker run --rm -p 8000:8000 `
  -e EXTERNAL_ENGINE_TOKEN=change-me `
  -e ASSET_ACCESS_TOKEN=change-me `
  -e ASSET_PUBLIC_BASE_URL=https://your-public-engine.example.com `
  zlb-mindmap-engine
```

## 百炼工作流

[workflow/bailian-workflow-blueprint.yaml](workflow/bailian-workflow-blueprint.yaml) 是 C+ v0.2 低代码画布节点蓝图。

它刻意不冒充百炼控制台导出的官方 DSL。建议按照蓝图搭建后，从百炼控制台导出正式 DSL；DeepSeek Key 作为 API 节点服务端鉴权配置，不写入 DSL。

详细组装步骤见 [docs/BAILIAN_LOW_CODE_VALIDATION.md](docs/BAILIAN_LOW_CODE_VALIDATION.md)。

## 示例

[examples/machine-learning-basics.md](examples/machine-learning-basics.md) 可用于快速验证完整流程。

外部组装接口示例见 [workflow/examples/mindmap-assemble-request.json](workflow/examples/mindmap-assemble-request.json)。
