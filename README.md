# ZLB Mind Map Agent

将课程材料整理成可追溯、可继续编辑的思维导图工作台。当前产品以
TopoMind/拓知工作台为前端，后端使用 Qwen 视觉与文本模型完成全局编排，
并把任务、图版本、来源引用和运行记录保存到 SQLite。

## 当前发布基线

截至 **2026-08-31**，`main` 的实际生产入口是：

```text
editorial_ppt_vision
  -> editorial-ppt-vision-loop
```

它的流程是“全局主编生成初稿 -> 可选多角色审校 -> 主编修订 -> 本地结构校验
与版本写入”。当前生产镜像不是旧 C+ 主流程，也不是 vNext shadow 流程。

已核验的本地运行时基线：

```text
image:    zlb-mindmap-agent:local-20260831
image ID:  sha256:b4ff4b115e30fa58441016b9d34698a92209cc067e23dbe1c4e01dac872b49d7
user:     10001:10001
pipeline: editorial_ppt_vision
```

镜像标签中的 revision 为
`4c2e205cb7c749f58d9a51e6129ed321114bfc17`。这是该次部署构建的镜像标识，
对应 `main` 的发布提交。

本次发布从 Composer 的 slash-command 菜单移除了 `/fork`、`/undo`、
`/thinking`、`/btw`、`/goal` 和 `/clear`；goal、side chat、thinking、fork
和 undo 能力仍可通过各自的界面入口使用。

## 能力范围

- 上传一份或多份课程材料，支持 `PDF`、`PPT/PPTX`、`DOC/DOCX`、`TXT` 和
  `MD/Markdown`。
- 对 PDF、PPTX、DOCX 做页面渲染；PPTX 中可提取的原生图片、表格、图表和
  图形会保留为视觉资产元数据。
- 初始任务同时利用可提取文本和视觉页面；扫描版或文本解析失败的视觉文档
  仍可尝试使用页面图像。
- 输出唯一根节点的主树、节点定义、来源页/来源单元引用、质量报告、警告、
  运行清单和图版本。
- 工作台提供历史记录、任务恢复、任务取消、节点变更流、运行过程流和
  JSON/PNG 导出。
- 生成后可以用自然语言继续修改，并可附加新课件或图片。二次输入会先由
  路由模型判断为：
  `guidance_only`（指导当前图）、`new_graph`（独立重生成）或
  `merge_graph`（与新材料合并）。
- 每次修改都绑定期望图版本；版本不匹配时拒绝写入，避免覆盖较新的结果。
- 每个账号只能读取自己的任务、历史、源文件、图版本和导出物。

### 输入限制

- 默认单文件大小上限为 80 MiB。
- 默认单份文档最多 150 页或幻灯片。
- 图片总像素、OOXML 解压大小和压缩比例均有独立限制。
- 初始工作台任务必须启用 AI；当前 editorial 生产路线没有无模型生成
  fallback。
- 二次输入可以附带 `PNG`、`JPG/JPEG` 或 `WEBP` 作为指导图片或新材料预览。

## 当前架构

```text
课程文件
  -> 文件签名、类型、大小、页数和压缩包安全校验
  -> 文本解析 + 页面/幻灯片渲染
  -> 全局主编生成完整思维导图初稿
  -> 可选内容遗漏、剪枝、多级结构审校
  -> 主编增量 Patch 或完整修订
  -> Pydantic 树约束与结果质量状态校验
  -> SQLite 黑板、运行清单、图版本和视觉资产
  -> 工作台实时展示与 JSON/PNG 导出
```

### 模型角色

主编是必需角色；内容遗漏、剪枝和多级结构是可配置的审校角色，最多可配置
6 轮。默认工作台使用 Qwen Provider，文本和视觉模型可以分别配置。

审校角色可以使用不同模型 ID，但它们仍属于同一 Provider 体系，不能把角色
数量解释为统计独立的模型家族。Responses 会话缓存、临时图片 URL 和上下文
压缩可用时会被使用；不可用时回退到兼容的多图或文本调用。

当前 editorial 路线的几个重要边界：

- 主树由全局主编直接维护，当前生产镜像不运行旧 C+ 的 CP-SAT/NetworkX
  求解链。
- `cross_links` 字段为历史合同兼容而保留，当前 editorial 结果不生成跨链。
- 旧 C+ 的 content-unit coverage 指标不作为当前 editorial 结果的主质量
  计算；内容遗漏由审校角色提出，最终结果仍会保留 warning、review issue
  和 degraded 状态。
- 任务状态为 `completed` 只表示流水线完成并写入结果，不等于
  `quality_gate_passed` 或 `publish_gate_passed` 为真。
- 当前服务不提供网页搜索或外部知识检索；课件之外的内容不能被默认为
  课程事实。

## 本地开发

### 前置条件

- Python 3.12
- Node.js 22
- pnpm 10.14.0
- LibreOffice 和 Poppler（需要处理视觉文档时）
- `age`（使用加密 Qwen 密钥文件时）

### 安装

在仓库根目录执行：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt

cd frontend
corepack enable
pnpm install --frozen-lockfile
cd ..
```

### 启动后端

开发环境可以直接使用环境变量提供 Qwen Key：

```bash
export MINDMAP_ENV=development
export MINDMAP_PIPELINE_MODE=editorial_ppt_vision
export QWEN_API_KEY='替换为本地开发密钥'

.venv/bin/python -m uvicorn backend.app.main:app \
  --reload \
  --host 127.0.0.1 \
  --port 8000
```

也可以不设置 `QWEN_API_KEY`，先启动服务查看健康检查和前端；没有可用
Provider 凭据时，模型列表或生成请求会失败。

若使用 age 密文，改为设置：

```bash
export QWEN_SECRETS_FILE="$PWD/runtime/secrets/qwen.enc.env.age"
export QWEN_AGE_IDENTITY_FILE="$PWD/runtime/secrets/qwen-age-identity.txt"
```

后端会在进程内解密 `QWEN_API_KEY`，不会把明文写回文件、前端或 SQLite。

### 启动前端

另开终端：

```bash
cd frontend
pnpm dev
```

Vite 默认监听 `http://127.0.0.1:5175`；端口被占用时会选择下一个可用端口。
`/api` 请求默认代理到 `http://127.0.0.1:8000`，也可以用
`MINDMAP_SERVER_URL` 覆盖后端地址。

开发环境地址：

- 工作台：`http://127.0.0.1:5175`
- FastAPI 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/api/health`

生产环境会关闭 `/docs`、`/redoc` 和 `/openapi.json`。

## 账号与数据隔离

工作台使用本地账号和 HttpOnly session cookie：

- `POST /api/auth/register` 注册账号并自动登录。
- `POST /api/auth/login` 登录。
- `POST /api/auth/logout` 注销当前 session。
- `GET /api/auth/me` 查询当前账号。
- session 默认有效期为 30 天，HTTPS 请求会设置 Secure cookie。
- 未登录访问受保护的任务、历史和模型接口会返回 `401`。
- owner 始终从认证 principal 派生，客户端不能通过自定义 owner header
  读取其他账号的数据。

首次注册账号时，历史上写入临时 `public-workbench` owner 的旧任务会交给该
账号；之后注册的账号不会看到这些记录。

默认数据目录为 `.data/mindmap_engine/`，其中包含：

```text
blackboard.sqlite3  任务、运行、图版本和模型调用记录
auth.sqlite3        账号、密码摘要和 session 记录
assets/             页面渲染图和视觉资产
```

上传源文件默认保留 72 小时；可用
`MINDMAP_SOURCE_RETENTION_HOURS=0` 关闭自动清理。服务重启会把仍处于
`queued/running` 的任务从保留源文件重新排队，当前不是 stage 精确续跑。

## 配置

### Provider 与模型

| 变量 | 默认值或要求 | 说明 |
| --- | --- | --- |
| `QWEN_API_KEY` | 无默认值 | 直接提供 Qwen Key；也可改用 age 文件 |
| `QWEN_SECRETS_FILE` | `runtime/secrets/qwen.enc.env.age` | age 加密 ENV 文件 |
| `QWEN_AGE_IDENTITY_FILE` | `runtime/secrets/qwen-age-identity.txt` | age 私钥文件 |
| `AGE_EXECUTABLE` | 自动查找 `age` | 指定 age 可执行文件 |
| `QWEN_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | OpenAI-compatible endpoint |
| `QWEN_MODEL` | `qwen3.7-max` | 默认文本模型 |
| `QWEN_VISION_MODEL` | `qwen3.7-plus` | 默认视觉模型 |
| `QWEN_TEMPERATURE` | `0.1` | 采样温度，范围会被限制在 0 到 2 |
| `MINDMAP_QWEN_PRODUCTION_PROFILE` | `standard` | 生产配置资格 profile |

生产 `standard` profile 会在启动时 fail closed，检查 HTTPS、endpoint 路径、
允许的 Qwen endpoint、Key 类型、Qwen 模型名称和视觉模型能力。Token Plan、
trial、preview、text-only 视觉模型或未批准 endpoint 不能直接冒充标准生产
配置。代码保留显式批准 profile，但必须精确匹配其全部约束，不能作为默认值。

### 存储、限制与并发

| 变量 | 默认值 | 说明 |
| --- | ---: | --- |
| `MINDMAP_ENV` | `development` | 生产设为 `production` |
| `MINDMAP_PIPELINE_MODE` | 空 | 当前发布路径使用 `editorial_ppt_vision` |
| `MINDMAP_DATA_DIR` | `.data/mindmap_engine` | SQLite、资产和运行数据目录 |
| `MINDMAP_BLACKBOARD_PATH` | 数据目录下 `blackboard.sqlite3` | 黑板数据库路径 |
| `MINDMAP_WORKBENCH_OWNER_ID` | `public-workbench` | 旧记录迁移兼容值，不是认证凭据 |
| `MINDMAP_MAX_UPLOAD_BYTES` | `83886080` | 每个上传文件的字节上限 |
| `MINDMAP_MAX_DOCUMENT_PAGES` | `150` | 单份文档页/幻灯片上限 |
| `MINDMAP_MAX_IMAGE_PIXELS` | `40000000` | 图片像素总量上限 |
| `MINDMAP_MAX_ZIP_UNCOMPRESSED_BYTES` | `300 MiB` | OOXML 解压大小上限 |
| `MINDMAP_MAX_ZIP_COMPRESSION_RATIO` | `120` | OOXML 压缩比例上限 |
| `MINDMAP_SOURCE_RETENTION_HOURS` | `72` | 已结束任务源文件保留时间 |
| `MINDMAP_MAX_CONCURRENT_JOBS` | `1` | 同时运行的任务数 |
| `MINDMAP_PROVIDER_CONCURRENCY` | `8` | Provider 请求并发数 |
| `MINDMAP_PROVIDER_TIMEOUT_SECONDS` | `180` | 本地 Provider 请求超时 |
| `MINDMAP_PROVIDER_MAX_ATTEMPTS` | `3` | 本地 Provider 最大尝试次数 |
| `MINDMAP_EXPORT_CONCURRENCY` | `1` | PNG 导出并发数 |

### Editorial 调优

以下变量用于实验或容量调优，未设置时使用代码默认值：

```text
MINDMAP_EDITORIAL_RENDER_DPI=120
MINDMAP_EDITORIAL_IMAGE_MAX_EDGE=1280
MINDMAP_EDITORIAL_JPEG_QUALITY=82
MINDMAP_EDITORIAL_RESPONSES_ENABLED=true
MINDMAP_EDITORIAL_UPLOAD_CONCURRENCY=8
MINDMAP_EDITORIAL_TIMEOUT_SECONDS=300
MINDMAP_EDITORIAL_MAX_REVISIONS=1
MINDMAP_EDITORIAL_MAX_DEPTH=6
MINDMAP_EDITORIAL_PATCH_REVISIONS=false
MINDMAP_EDITORIAL_FULL_REWRITE_FALLBACK=false
MINDMAP_EDITORIAL_DRAFT_MAX_OUTPUT_TOKENS=24000
MINDMAP_EDITORIAL_REVIEW_MAX_OUTPUT_TOKENS=12000
MINDMAP_EDITORIAL_REVISION_MAX_OUTPUT_TOKENS=24000
MINDMAP_EDITORIAL_PATCH_MAX_OUTPUT_TOKENS=7000
MINDMAP_EDITORIAL_VISUAL_COMPACTOR_MODEL=qwen3-vl-flash
MINDMAP_EDITORIAL_CONTEXT_COMPACTOR_MODEL=qwen3.8-flash
```

`loop_config` 也可以在 `POST /api/jobs` 中按轮次指定主编和审校模型；每轮最多
包含主编、内容遗漏、剪枝和多级结构四类角色。

仓库中仍能看到 `MINDMAP_PDF_*`、`MINDMAP_SINGLE_SHOT_*` 等旧实验配置。
它们不构成当前生产 editorial 路线的公共配置合同，除非正在运行相应的
实验/诊断代码，否则不要据此判断当前镜像行为。

## HTTP API

### 公开接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/api/auth/register` | 注册并建立 session |
| `POST` | `/api/auth/login` | 登录并建立 session |
| `POST` | `/api/auth/logout` | 注销 session |
| `GET` | `/api/health` | 健康状态、架构名称和支持扩展名 |

### 需要 session cookie 的接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/auth/me` | 当前账号 |
| `GET` | `/api/models` | 查询 Qwen 可用模型 |
| `POST` | `/api/model-check` | 检查一个模型是否可用 |
| `POST` | `/api/jobs` | 上传一份或多份材料并创建任务 |
| `GET` | `/api/history` | 当前账号的历史任务 |
| `GET` | `/api/jobs/{task_id}` | 任务状态和最新图版本 |
| `GET` | `/api/jobs/{task_id}/interactions` | 初始生成和后续修改记录 |
| `GET` | `/api/jobs/{task_id}/events` | SSE 实时事件流 |
| `POST` | `/api/jobs/{task_id}/cancel` | 取消任务 |
| `POST` | `/api/jobs/{task_id}/refine` | 以自然语言修改当前图 |
| `POST` | `/api/jobs/{task_id}/refine-with-files` | 带附件的二次输入 |
| `GET` | `/api/jobs/{task_id}/versions` | 列出图版本 |
| `GET` | `/api/jobs/{task_id}/versions/{version}` | 读取指定图版本 |
| `GET` | `/api/jobs/{task_id}/export.json` | 下载最新完整 JSON |
| `GET` | `/api/jobs/{task_id}/export.png` | 下载最新 PNG |
| `GET` | `/api/jobs/{task_id}/export.png?v={version}` | 下载指定版本 PNG |
| `DELETE` | `/api/jobs/{task_id}` | 删除任务、源文件和关联资产 |

`POST /api/jobs` 使用 `multipart/form-data`。常用字段如下：

```text
files        重复上传字段，可传多份材料
file         单文件兼容字段
provider     当前为 qwen
model        主编模型 ID
use_ai       当前必须为 true
loop_config  JSON 编排配置，可附带 human_instruction
```

`/api/jobs/{task_id}/events` 的事件包括任务阶段、模型开始/增量/结束、上下文
用量、上下文压缩、任务完成、失败和取消。客户端同时使用 SSE 和任务状态
轮询，以便在浏览器刷新或连接重试后恢复。

### 旧引擎接口边界

`backend/app/mindmap_engine/router.py`、旧 solver 模块和低代码蓝图仍保留在
仓库中供历史测试、迁移和实验参考，但当前 `backend.app.main:app` 没有把旧
`/v1` router 注册为工作台生产入口。生产 Docker 阶段也会移除退休的 C+ 运行时、
测试和工具。不要把旧 `/v1` 路径写入当前客户端集成。

## Docker 与生产 Compose

### 构建

`Dockerfile` 会：

1. 使用 Node 22 和 pnpm 10.14.0 构建前端；
2. 使用 Python 3.12 安装锁定的后端依赖；
3. 安装 age、LibreOffice Impress/Writer 和 Poppler；
4. 以 UID/GID `10001:10001` 运行；
5. 删除生产不需要的测试、工具和退休 C+ 求解模块；
6. 内置前端静态文件并通过 Uvicorn 提供同源服务。

本地重新构建示例：

```bash
sudo docker build \
  --build-arg GIT_SHA="$(git rev-parse HEAD)" \
  -t zlb-mindmap-agent:local .
```

### 使用已核验镜像部署

`compose.prod.yml` 要求显式提供镜像引用、镜像 ID、Qwen 配置和引擎兼容 token。
示例中的 token 只能替换为部署环境自己的值：

```bash
export MINDMAP_IMAGE_REF=zlb-mindmap-agent:local-20260831
export IMAGE_DIGEST=sha256:b4ff4b115e30fa58441016b9d34698a92209cc067e23dbe1c4e01dac872b49d7
export EXTERNAL_ENGINE_TOKEN='替换为部署环境 token'
export QWEN_BASE_URL='https://dashscope.aliyuncs.com/compatible-mode/v1'
export QWEN_MODEL='受支持的正式文本模型'
export QWEN_VISION_MODEL='受支持的正式视觉模型'
export QWEN_AGE_IDENTITY_SOURCE_FILE='./runtime/secrets/qwen-age-identity.txt'
export QWEN_ENCRYPTED_ENV_SOURCE_FILE='./runtime/secrets/qwen.enc.env.age'
```

准备 age secret：

```bash
sudo chown 0:10001 -- \
  runtime/secrets/qwen-age-identity.txt \
  runtime/secrets/qwen.enc.env.age
sudo chmod 0440 -- \
  runtime/secrets/qwen-age-identity.txt \
  runtime/secrets/qwen.enc.env.age

.venv/bin/python -m backend.app.secret_preflight \
  --expected-uid 0 \
  --expected-gid 10001 \
  --expected-mode 0440 \
  runtime/secrets/qwen-age-identity.txt \
  runtime/secrets/qwen.enc.env.age
```

校验并启动：

```bash
sudo docker compose -f compose.prod.yml config --quiet
sudo docker compose -f compose.prod.yml up -d --no-build
curl --fail http://127.0.0.1:5173/api/health
```

默认部署合同：

- 宿主 `127.0.0.1:5173` 映射到容器 `8000`，建议由 TLS 反向代理对外提供服务。
- 只读 rootfs，`/tmp` 使用 512 MiB tmpfs。
- `cap_drop: ALL`、`no-new-privileges`、非 root、256 PID、2 CPU 和默认 3 GiB
  内存上限。
- SQLite/资产和上传源文件分别挂载持久卷。
- Compose 默认使用 `unless-stopped`，启动命令会先执行 secret metadata
  preflight，再 `exec` Uvicorn。
- `MINDMAP_BIND_HOST`、`MINDMAP_PUBLIC_PORT`、卷名和资源限制可以由部署环境
  覆盖，但不应放宽 secret 权限或关闭生产配置校验。

`EXTERNAL_ENGINE_TOKEN`、`ASSET_ACCESS_TOKEN` 和 `ASSET_PUBLIC_BASE_URL` 是
保留的引擎/资产兼容配置；它们不等于工作台用户登录凭据，也不会把 Qwen Key
传给浏览器。当前工作台主 API 仍以 `/api` 路由为准。

## 验证

常用静态检查和构建命令：

```bash
git diff --check
.venv/bin/python -m compileall -q backend/app backend/tests

cd frontend
pnpm test
pnpm exec tsc -b --pretty false
pnpm build
```

后端相关改动应运行：

```bash
.venv/bin/python -m unittest discover -s backend/tests -v
```

仓库还保留了 `test_vnext_*.py` 历史实验测试；这些测试依赖已经从当前生产
镜像移除的 `backend.vnext`，所以完整 discovery 可能出现旧模块导入错误。
发布核验使用排除该历史集合的当前生产运行时测试；不要为了让旧 vNext 测试
变绿而把退休运行时重新放回生产镜像。

最近一次发布核验（2026-08-31）包括：

- 当前生产运行时后端测试：`638 passed`；
- 前端：37 个测试文件、670 项测试通过；
- TypeScript typecheck、Vite production build、`compileall` 和
  `git diff --check` 通过；
- `zlb-mindmap-agent:local-20260831` 的 `/api/health` 探针返回
  `editorial-ppt-vision-loop`。

这些结果证明代码和运行时合同通过了本地/隔离验证，不等于对任意真实课件的
语义准确率、模型供应商 SLA 或公网部署质量作统计保证。真实部署仍需使用
目标环境的正式 Qwen 凭据和参赛/业务材料完成端到端验收。

## 代码与文档索引

- `backend/app/main.py`：FastAPI 应用、认证、任务生命周期、SSE 和导出。
- `backend/app/editorial_ppt_pipeline.py`：当前生产 editorial vision loop。
- `backend/app/editorial_input.py`：多文档分类、解析和来源边界。
- `backend/app/editorial_patch.py`：定向修改 Patch 与事务校验。
- `backend/app/human_loop.py`：自然语言指导与图版本交互记录。
- `backend/app/refinement_routing.py`：二次输入路由。
- `backend/app/blackboard.py`：SQLite 任务、运行和版本持久化。
- `backend/app/config.py`：Provider、生产资格、存储和限制配置。
- `frontend/src/main.ts`、`frontend/src/App.vue`：当前 Vite/Vue 工作台入口。
- `frontend/src/api/mindmapAgent.ts`：前端到 `/api` 工作台适配层。
- `Dockerfile`、`compose.prod.yml`：镜像构建和生产运行合同。

以下资料属于历史设计、实验或迁移上下文，不代表当前生产入口：

- `docs/CPLUS_IMPLEMENTATION.md`
- `docs/MINDMAP_ROOT_CAUSE_ANALYSIS.md`
- `docs/VNEXT_*`
- `docs/MINDMAP_EXECUTION_*`
- `compose.single-shot-ppt.yml`
- `workflow/bailian-workflow-blueprint.yaml`

修改当前产品行为时，先以 `backend/app/main.py`、`editorial_ppt_pipeline.py`、
`frontend/src/main.ts` 和 `compose.prod.yml` 为准，再参考历史文档。
