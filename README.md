# ZLB Knowledge Map Demo

将课程 PDF、PPTX、DOCX、TXT 或 Markdown 转换为带原文证据的知识图谱。

## 架构

```text
文档解析
  -> 结构感知 chunk
  -> DeepSeek / 百炼候选抽取
  -> 确定性节点归一
  -> 关系校验
  -> 质量报告与交互知识图
```

主流程使用 LangGraph。模型只生成候选节点和候选关系，代码负责实体归一、去重、证据绑定和图结构提交。

## 本地启动

后端使用 Python 3.12：

```powershell
python -m venv .venv312
.\.venv312\Scripts\python.exe -m pip install -r backend\requirements.txt
$env:DEEPSEEK_API_KEY = Read-Host "DeepSeek API Key"
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

百炼工作空间 API Key 会自动从根目录的 `ZLB-apiKey-*.csv` 读取。DeepSeek Key 只从环境变量读取，不会发送到前端。

## 模型服务

- `deepseek`：默认模型 `deepseek-v4-flash`
- `bailian`：默认模型 `qwen3.7-plus`
- 任一模型不可用时，当前 chunk 自动降级为本地启发式抽取

## 百炼工作流

[workflow/bailian-workflow-blueprint.yaml](workflow/bailian-workflow-blueprint.yaml) 是低代码画布的节点蓝图。

它刻意不冒充百炼控制台导出的官方 DSL。建议按照蓝图搭建后，从百炼控制台导出正式 DSL；DeepSeek Key 作为 API 节点服务端鉴权配置，不写入 DSL。

## 示例

[examples/machine-learning-basics.md](examples/machine-learning-basics.md) 可用于快速验证完整流程。
