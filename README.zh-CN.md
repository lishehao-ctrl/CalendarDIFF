# CalendarDIFF

[![Language: English](https://img.shields.io/badge/Language-English-2ea44f)](./README.md)
[![Language: 中文](https://img.shields.io/badge/Language-%E4%B8%AD%E6%96%87-0ea5e9)](./README.zh-CN.md)

Live app / 在线地址: [cal.shehao.app](https://cal.shehao.app)

CalendarDIFF 是一个给学生使用的截止日期收件箱。  
它会把 Canvas 日历和 Gmail 里的任务信息汇总到一起，先做语义比对，再由你审核确认，最后才更新最终任务清单。  
目标很直接：把“到底哪条 deadline 才是最新、最可信的”这件事变成可审核、可追溯的流程。

## 项目简介

CalendarDIFF 不会把任意单一来源直接当成“真相”，而是按下面这套流程处理：

1. 从 Canvas ICS、Gmail 等来源抓取原始记录
2. 统一整理成可比较的来源观察数据（`source observations`）
3. 生成待审核的语义变更（`changes`）
4. 只有在你批准后，才写入最终状态（`event_entities`）

## 核心亮点

1. 多源整合  
   把 Canvas ICS 和 Gmail 合并到同一个可审核的收件箱里。

2. 身份稳定、展示直观  
   系统内部用稳定的 `entity_uid` 保证同一任务不会“串号”，页面上仍然按 `course + family + ordinal` 直观展示。

3. 先审核，再生效  
   新数据先进入 `changes` 等待确认，批准后才会更新 `event_entities`。

4. 增量优先，降低成本  
   ICS 会先做增量检测，只把真正变化的 VEVENT 送去后续高成本解析。

5. 证据可回看  
   即使源数据之后变化，审核时看到的证据仍会保留，方便追踪决策依据。

6. 支持人工修正  
   当解析结果不理想时，你可以直接手动修正 due date。

7. 可立即触发提醒  
   一旦出现新的待审核变更，就可以马上触发 review 通知。

## 核心流程

主流程：

1. 摄取输入源并生成 `source observations`
2. 先执行确定性的 ICS 增量处理
3. 仅把变化记录送入 LLM 解析
4. 在 `changes` 中生成待审核提案
5. 用户批准后写入 `event_entities`
6. 发送 review 通知

关键规则：

1. ICS 的核心字段（`title/start/end/status/location`）保持来源可追溯和确定性，不交给 LLM 重写。
2. LLM 主要负责语义增强，例如课程解析、任务部件识别、链接信号提取。
3. link candidate 的审核链路与 canonical change 的通知链路分离。
4. 所有已批准的最终语义状态统一保存在 `event_entities`。

## 运行架构

当前运行拓扑：

1. `public-service` (`services.public_api.main:app`)
2. `input-service` (`services.input_api.main:app`, internal metrics/runtime only)
3. `ingest-service` (`services.ingest_api.main:app`)
4. `llm-service` (`services.llm_api.main:app`)
5. `review-service` (`services.review_api.main:app`, internal apply/runtime only)
6. `notification-service` (`services.notification_api.main:app`)
7. `postgres`
8. `redis`

用户流量统一经过 public gateway，内部服务分别处理 ingest、LLM parsing、review 和 notification。

## 快速开始

推荐先读：

- `docs/frontend_console_release_acceptance.md`
- `docs/deploy_three_layer_runtime.md`
- `docs/nginx_live_routing_architecture.md`
- `docs/architecture.md`

### 1. 安装依赖

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
cd frontend && npm install && cd ..
```

### 2. 启动本地完整栈

```bash
scripts/dev_stack.sh up
```

这个启动器会：

1. 通过 `docker compose` 启动 `postgres` 和 `redis`
2. 使用 `python -m alembic upgrade head` 执行数据库迁移
3. 启动 `frontend`、`public-service`、`input-service`、`ingest-service`、`llm-service`、`review-service`、`notification-service`
4. 在 `output/dev-stack/` 下写入 pid 和日志文件
5. 除非你手动执行 `scripts/dev_stack.sh down --infra`，否则会保持 PostgreSQL 和 Redis 继续运行
6. 支持 `scripts/dev_stack.sh reset`，用于重置配置数据库并重启整套服务

`down --infra` 只会停止本仓库 docker compose 定义的 `postgres` 和 `redis`，不会影响你机器上其他占用相同端口的实例。

常用命令：

```bash
scripts/dev_stack.sh status
scripts/dev_stack.sh logs frontend
scripts/dev_stack.sh logs all
scripts/dev_stack.sh reset
scripts/dev_stack.sh down
scripts/dev_stack.sh down --infra
```

### 3. 手动逐个服务启动

如果你想逐个启动服务：

```bash
docker compose up -d postgres redis
python -m alembic upgrade head
SERVICE_NAME=public RUN_MIGRATIONS=false PORT=8200 ./scripts/start_service.sh
SERVICE_NAME=input RUN_MIGRATIONS=false PORT=8201 ./scripts/start_service.sh
SERVICE_NAME=ingest RUN_MIGRATIONS=false PORT=8202 ./scripts/start_service.sh
SERVICE_NAME=review RUN_MIGRATIONS=false PORT=8203 ./scripts/start_service.sh
SERVICE_NAME=llm RUN_MIGRATIONS=false PORT=8205 ./scripts/start_service.sh
SERVICE_NAME=notification RUN_MIGRATIONS=false PORT=8204 ./scripts/start_service.sh
cd frontend && BACKEND_BASE_URL=http://127.0.0.1:8200 BACKEND_API_KEY="$APP_API_KEY" NEXT_DIST_DIR=.next-dev npm run dev -- --hostname 127.0.0.1 --port 3000
```

## 容器编排

启动完整本地栈：

```bash
docker compose up --build
```

默认包含：

1. `postgres`
2. `redis`
3. `public-service`
4. `input-service`
5. `ingest-service`
6. `llm-service`
7. `review-service`
8. `notification-service`
9. `frontend`

默认暴露端口：

1. `frontend` on `localhost:3000`
2. `public-service` on `localhost:8000`

日常本地开发更推荐使用 `scripts/dev_stack.sh up`，以及 `820x` 端口组。

默认 compose 下，`input-service`、`review-service`、`ingest-service`、`llm-service`、`notification-service` 仅供内部访问；如果调试需要暴露内部端口，请使用 `docker-compose.dev.yml`。

如果你在 compose 下启用 Gmail OAuth，请把 `HOST_SECRETS_DIR` 设为 `GMAIL_OAUTH_CLIENT_SECRETS_FILE` 所在目录的父目录。

## 核心环境变量

### 必填

```env
APP_API_KEY=dev-api-key-change-me
APP_SECRET_KEY=7J2Btjj4GW8jIP5MErM81QOZeK4c7xYknVxKsgKMnmk=
INTERNAL_SERVICE_TOKEN_INPUT=dev-internal-token-input
INTERNAL_SERVICE_TOKEN_INGEST=dev-internal-token-ingest
INTERNAL_SERVICE_TOKEN_REVIEW=dev-internal-token-review
INTERNAL_SERVICE_TOKEN_NOTIFICATION=dev-internal-token-notification
INTERNAL_SERVICE_TOKEN_LLM=dev-internal-token-llm
INTERNAL_SERVICE_TOKEN_OPS=dev-internal-token-ops
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/deadline_diff
REDIS_URL=redis://localhost:6379/0
PUBLIC_WEB_ORIGINS=http://localhost:8200,http://127.0.0.1:8200
```

### Ingestion LLM 配置

```env
APP_LLM_OPENAI_MODEL=
INGESTION_LLM_MODEL=
INGESTION_LLM_BASE_URL=
INGESTION_LLM_API_KEY=
```

在 `docker compose` 下，`INGESTION_LLM_MODEL`、`INGESTION_LLM_BASE_URL`、`INGESTION_LLM_API_KEY` 都是必填；为空时 compose 会直接失败。

### OAuth 运行配置

```env
# Priority for OAuth public base URL:
# OAUTH_PUBLIC_BASE_URL > PUBLIC_API_BASE_URL > APP_BASE_URL > http://localhost:8200
OAUTH_PUBLIC_BASE_URL=http://localhost:8200
OAUTH_ROUTE_PREFIX=
OAUTH_SESSION_ROUTE_TEMPLATE=/sources/{source_id}/oauth-sessions
OAUTH_CALLBACK_ROUTE_TEMPLATE=/oauth/callbacks/{provider}
OAUTH_CALLBACK_REQUIRE_API_KEY=false
OAUTH_STATE_TTL_MINUTES=10
# Optional override; falls back to APP_SECRET_KEY.
OAUTH_TOKEN_ENCRYPTION_KEY=
HOST_SECRETS_DIR=/tmp/calendardiff-secrets
GMAIL_OAUTH_CLIENT_SECRETS_FILE=/tmp/calendardiff-secrets/google_client_secret.json
GMAIL_OAUTH_SCOPE=https://www.googleapis.com/auth/gmail.readonly
GMAIL_OAUTH_ACCESS_TYPE=offline
GMAIL_OAUTH_PROMPT=consent
GMAIL_OAUTH_INCLUDE_GRANTED_SCOPES=true
```

`input-service` 启动时会输出最终生效的 OAuth 配置，包括：

1. Gmail redirect URI
2. 注册的 callback routes
3. OAuth key 的来源（`OAUTH_TOKEN_ENCRYPTION_KEY` 或 `APP_SECRET_KEY`）

### Gmail 本地覆盖配置

```env
GMAIL_API_BASE_URL=http://127.0.0.1:8765/gmail/v1/users/me
GMAIL_OAUTH_TOKEN_URL=http://127.0.0.1:8765/oauth2/token
GMAIL_OAUTH_AUTHORIZE_URL=http://127.0.0.1:8765/oauth2/auth
```

### Worker 轮询间隔

```env
INGESTION_TICK_SECONDS=2
LLM_SERVICE_ENABLE_WORKER=true
REVIEW_APPLY_TICK_SECONDS=2
NOTIFICATION_TICK_SECONDS=5
```

### 通知输出模式

```env
# smtp (default) or jsonl (for local demo without real email side effects)
NOTIFY_SINK_MODE=smtp
NOTIFY_JSONL_PATH=data/smoke/notify_sink.jsonl
```

### 真实 Gmail SMTP 发信

如果你想发送真实提醒邮件，可以使用这组 SMTP 配置。

```env
ENABLE_NOTIFICATIONS=true
NOTIFY_SINK_MODE=smtp
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USERNAME=your-account@gmail.com
SMTP_PASSWORD=<google-app-password>
SMTP_FROM_NAME=CalendarDIFF
SMTP_FROM_EMAIL=your-account@gmail.com
DEFAULT_NOTIFY_EMAIL=

APP_BASE_URL=https://cal.shehao.app
FRONTEND_APP_BASE_URL=https://cal.shehao.app
PUBLIC_WEB_ORIGINS=https://cal.shehao.app

NOTIFICATION_TICK_SECONDS=5
```

运行说明：

1. Gmail App Password 需要先开启两步验证。
2. 除非你明确在用 alias，否则 `SMTP_USERNAME` 和 `SMTP_FROM_EMAIL` 最好保持一致。
3. `SMTP_FROM_NAME` 控制发件人显示名。
4. 想让通知真的发出去，记得打开 `ENABLE_NOTIFICATIONS=true`。

### 统一公开 API 地址

```env
BACKEND_BASE_URL=http://localhost:8200
```

## 内部运维认证

`/internal/*` 接口不再接受 `X-API-Key`。

请使用 service token 请求头：

```http
X-Service-Name: ops
X-Service-Token: <INTERNAL_SERVICE_TOKEN_OPS>
```

Worker 开关：

```env
INGEST_SERVICE_ENABLE_WORKER=true
REVIEW_SERVICE_ENABLE_APPLY_WORKER=true
NOTIFICATION_SERVICE_ENABLE_WORKER=true
ENABLE_NOTIFICATIONS=false
```

## 健康检查

```bash
curl -s http://localhost:8200/health
curl -s http://localhost:8201/health
curl -s http://localhost:8202/health
curl -s http://localhost:8203/health
curl -s http://localhost:8204/health
curl -s http://localhost:8205/health
```

## 冒烟测试

### 真实源三轮冒烟

```bash
python scripts/smoke_real_sources_three_rounds.py \
  --public-api-base http://127.0.0.1:8200 \
  --report data/synthetic/ddlchange_160/qa/real_source_smoke_report.json
```

### 学期演示冒烟

这个流程使用在线 LLM 和本地 JSONL 通知输出，不需要 Gmail OAuth。

```bash
NOTIFY_SINK_MODE=jsonl \
NOTIFY_JSONL_PATH=data/smoke/notify_sink.jsonl \
python scripts/smoke_semester_demo.py \
  --public-api-base http://127.0.0.1:8200 \
  --ingest-internal-base http://127.0.0.1:8202 \
  --notify-internal-base http://127.0.0.1:8204 \
  --llm-internal-base http://127.0.0.1:8205 \
  --ops-token "${INTERNAL_SERVICE_TOKEN_OPS}" \
  --notification-jsonl data/smoke/notify_sink.jsonl \
  --report data/synthetic/semester_demo/qa/semester_demo_report.json
```

通知刷新接口：

```http
POST /internal/notifications/flush
X-Service-Name: ops
X-Service-Token: <INTERNAL_SERVICE_TOKEN_OPS>
```

在线 pytest 封装：

```bash
RUN_SEMESTER_DEMO_SMOKE=true \
SEMESTER_DEMO_NOTIFICATION_JSONL=data/smoke/notify_sink.jsonl \
pytest -q tests/test_semester_demo_online.py
```

完整闭环检查：

```bash
python scripts/smoke_microservice_closure.py \
  --public-api-base http://127.0.0.1:8200 \
  --input-internal-base http://127.0.0.1:8201 \
  --review-internal-base http://127.0.0.1:8203 \
  --ingest-internal-base http://127.0.0.1:8202 \
  --notify-internal-base http://127.0.0.1:8204 \
  --llm-internal-base http://127.0.0.1:8205
```

SLO 检查：

```bash
python scripts/ops_slo_check.py \
  --input-internal-base http://127.0.0.1:8201 \
  --ingest-internal-base http://127.0.0.1:8202 \
  --review-internal-base http://127.0.0.1:8203 \
  --notify-internal-base http://127.0.0.1:8204 \
  --llm-internal-base http://127.0.0.1:8205 \
  --ops-token "${INTERNAL_SERVICE_TOKEN_OPS}" \
  --json
```

OpenAPI 快照更新：

```bash
python scripts/update_openapi_snapshots.py
```

## 审核模型

Review-service 同时支持 proposal review 和 direct canonical edit。

关键行为：

1. `POST /review/edits/preview`
2. `POST /review/edits`，并设置 `mode=canonical`
3. 目标可以通过 `change_id` 或 `entity_uid` 指定
4. 仅日期格式的 `patch.due_at` 会在 `users.timezone_name` 时区下归一化为 `23:59`
5. 同一 `entity_uid` 的冲突 pending change 会被自动拒绝
6. canonical edit 会写入已批准审计变更，并发出 `review.decision.approved`

## 本地质量检查

推荐按这个顺序运行：

```bash
mypy .
flake8 .
python -m build
```

说明：

1. `mypy` 使用 `explicit_package_bases`，因此 `services/*/main.py` 不会因为同名 `main` 产生顶层模块冲突。
2. `flake8` 会排除 `.venv`、`tools`、`app/db/migrations` 等环境或历史路径。
3. `python -m build` 依赖 `build` 包，该依赖已包含在 `requirements.txt` 中。

## 测试

```bash
source .venv/bin/activate
python -m pytest -q
```

## API 与文档

API 快照：

1. `docs/api_surface_current.md`
2. `docs/event_contracts.md`

核心文档：

1. `docs/frontend_console_release_acceptance.md`
2. `docs/deploy_three_layer_runtime.md`
3. `docs/architecture.md`
4. `docs/service_table_ownership.md`
5. `docs/ops_microservice_slo.md`
6. `docs/dataflow_input_to_notification.md`
7. `docs/archive/README.md`
