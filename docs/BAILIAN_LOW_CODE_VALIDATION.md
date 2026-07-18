# 百炼低代码组装与验证

## 1. 责任边界

留在百炼工作流：

- 开始节点与文件输入。
- 大文档解析。
- 批处理与循环。
- 全局主题规划模型。
- 分支节点抽取模型。
- 父节点独立校验模型。
- 视觉页面理解模型。
- 条件判断和最终输出。

放在外部 `mindmap-engine`：

- PPTX/PDF 页面渲染。
- 原生图片提取和 bbox 裁剪。
- 稳定 ID、节点归一与去重。
- Top-k 父节点候选召回。
- OR-Tools CP-SAT 主树求解。
- NetworkX 图校验。
- 临时保底边标记与复核项生成。
- 视觉资产存储和访问。

百炼 API 节点最长等待 600 秒，因此外部能力被拆成短时同步接口，不把完整长任务塞进单次 API 调用。

## 2. 部署外部引擎

### 2.1 环境变量

```text
EXTERNAL_ENGINE_TOKEN=<百炼 API 节点使用的 Bearer Token>
ASSET_ACCESS_TOKEN=<视觉资产 URL 的访问 Token>
ASSET_PUBLIC_BASE_URL=https://<公网 HTTPS 域名>
MINDMAP_DATA_DIR=/app/.data/mindmap_engine
MINDMAP_SOLVER_TIMEOUT_SECONDS=5
```

`ASSET_PUBLIC_BASE_URL` 必须能被百炼视觉节点访问。生产环境必须使用 HTTPS。

### 2.2 Docker

```bash
docker build -t zlb-mindmap-engine .
docker run -d \
  --name zlb-mindmap-engine \
  -p 8000:8000 \
  -e EXTERNAL_ENGINE_TOKEN="$EXTERNAL_ENGINE_TOKEN" \
  -e ASSET_ACCESS_TOKEN="$ASSET_ACCESS_TOKEN" \
  -e ASSET_PUBLIC_BASE_URL="$ASSET_PUBLIC_BASE_URL" \
  -v zlb-mindmap-data:/app/.data/mindmap_engine \
  zlb-mindmap-engine
```

### 2.3 健康检查

```bash
curl https://<公网域名>/v1/mindmap/health
```

预期：

```json
{
  "status": "ok",
  "solver": "ortools-cp-sat",
  "graph": "networkx"
}
```

## 3. 百炼画布配置

参考：

- `workflow/bailian-workflow-blueprint.yaml`
- `workflow/prompts/`
- `workflow/schemas/`

蓝图不是官方 DSL。应在控制台搭建并测试后，导出官方 DSL 作为基准。

### 3.1 开始节点

输入：

- `document`：文件。
- `generator_model`：默认 Qwen。
- `verifier_model`：使用不同模型家族。
- `mode`：`standard` 或 `precision`。

### 3.2 文档解析

使用百炼大文档解析节点。

在其后增加脚本转换节点，将输出映射为：

```json
{
  "document_id": "doc_xxx",
  "filename": "course.pptx",
  "file_type": "pptx",
  "title": "课程标题",
  "blocks": [
    {
      "text": "正文",
      "page": null,
      "slide": 1,
      "heading": "章节标题"
    }
  ]
}
```

### 3.3 调用切块接口

API 节点：

```text
POST ${GRAPH_SERVICE_URL}/v1/chunks
Authorization: Bearer ${GRAPH_SERVICE_TOKEN}
```

请求：

```json
{
  "document": "${mapped_document}",
  "max_chars": 1800,
  "overlap_chars": 240
}
```

### 3.4 视觉页面渲染

API 节点使用 multipart 上传原始文件：

```text
POST ${GRAPH_SERVICE_URL}/v1/mindmap/visuals/render
```

响应：

- `pages`：整页图片 URL，供视觉模型分析。
- `native_visuals`：PPTX 原生图片及图表/表格/组合图坐标。
- `warnings`：本次渲染降级信息。

### 3.5 视觉理解与裁剪

对 `pages` 做批处理，使用 `prompts/analyze-visual-page.system.txt` 和 `schemas/visual-page-analysis.schema.json`。

过滤 `ignore_decoration` 后调用：

```text
POST ${GRAPH_SERVICE_URL}/v1/mindmap/visuals/crop
```

请求中的 bbox 必须是 `[x, y, width, height]`，且全部归一化到 0–1。

### 3.6 全局主题规划

使用：

- `prompts/plan-themes.system.txt`
- `schemas/theme-plan.schema.json`

根候选必须：

- 1–3 个。
- 具有支持单元。
- 避免空泛标题。

### 3.7 分支节点抽取

对 `/v1/chunks` 返回的 chunks 批处理。

使用：

- `prompts/extract-node-claims.system.txt`
- `schemas/node-claims.schema.json`

### 3.8 第一次归一

将根候选、一级主题、文本节点和视觉节点拉平后调用：

```text
POST ${GRAPH_SERVICE_URL}/v1/mindmap/normalize
```

该接口返回：

- 稳定节点 ID。
- 去重结果。
- Top-k 父节点候选。
- 临时保底父边。

### 3.9 父节点批量校验

对 `normalize.parent_candidates` 批处理。

使用：

- `prompts/verify-parent.system.txt`
- `schemas/parent-verification.schema.json`

校验输出必须保留 `parent` 和 `child`，以便脚本节点回填 `verifier_score`。

### 3.10 最终组装

调用：

```text
POST ${GRAPH_SERVICE_URL}/v1/mindmap/assemble
```

本地可用示例：

- `workflow/examples/mindmap-assemble-request.json`

接口返回：

- `root_id`
- `nodes`
- `tree_edges`
- `cross_links`
- `review_items`
- `quality`
- `solver_status`

## 4. 质量门

低代码验证阶段至少要求：

```text
quality.topology_valid == true
quality.evidence_coverage == 1
quality.provisional_edge_count == 0
```

如果 `provisional_edge_count > 0`，主树仍然保持合法，但对应边必须进入人工确认，不能直接发布。

## 5. 标准档与高精档

标准档：

- 一个生成模型。
- 一个独立父边校验模型。
- CP-SAT 求解。

高精档：

- 根、抽象父节点和竞争父边增加第二校验模型。
- 两个校验模型分歧时增加仲裁节点。
- 仲裁后仍不确定才进入人工队列。

## 6. 验证顺序

1. 使用 `workflow/examples/mindmap-assemble-request.json` 直接调用远端 `/assemble`。
2. 在百炼中只搭建文档解析、节点抽取和 `/assemble`，先验证文本主树。
3. 加入第一次 `/normalize` 和父边批量校验。
4. 加入视觉渲染、视觉分析与裁剪分支。
5. 切换 `precision`，验证第二校验和仲裁。
6. 导出百炼官方 DSL，记录模型、Prompt 和 Schema 版本。

## 7. 常见问题

### API 节点返回 401

检查：

- `Authorization` 是否为 `Bearer <token>`。
- 远端 `EXTERNAL_ENGINE_TOKEN` 是否一致。

### 页面图片 URL 无法被视觉节点读取

检查：

- `ASSET_PUBLIC_BASE_URL` 是否是公网 HTTPS。
- URL 中是否携带有效 `token`。
- 防火墙和反向代理是否允许 GET 资产路径。

### PPTX 只有原生图片，没有整页页面

远端缺少 LibreOffice 或 Poppler。使用本仓库 Dockerfile 部署可自动安装。

### 求解结果存在 review_items

这不代表主树非法。检查：

- 是否选择了 `provisional` 保底父边。
- 两个父候选得分是否接近。
- 抽象节点支持单元是否不足。

### 画布脚本节点无法安装第三方库

这是预期边界。脚本节点只做字段映射、数组拉平和票数合并；图算法、渲染和持久化全部调用外部服务。
