# CalendarDIFF

[![Language: English](https://img.shields.io/badge/Language-English-2ea44f)](./README.md)
[![Language: 中文](https://img.shields.io/badge/Language-%E4%B8%AD%E6%96%87-0ea5e9)](./README.zh-CN.md)

Live app / 在线地址: [cal.shehao.app](https://cal.shehao.app)

CalendarDIFF is a semantic-first deadline inbox for students who need one trustworthy place to reconcile coursework from multiple sources.

CalendarDIFF 是一个面向学生的语义优先 deadline inbox，用来把多个来源里的课程任务整合成一份可审核、可信任的最终清单。

## Overview / 项目简介

Instead of treating every source as ground truth, CalendarDIFF:

1. ingests source records from Canvas ICS and Gmail
2. normalizes them into source observations
3. proposes semantic changes
4. lets users review and approve the final state

CalendarDIFF 不会把任意单一来源直接当成最终真相，而是：

1. 从 Canvas ICS、Gmail 等来源摄取记录
2. 归一化成 source observations
3. 生成待审核的 semantic changes
4. 由用户批准后，才写入最终可信状态

## Highlights / 亮点

1. Multi-source reconciliation / 多源整合  
   Combine Canvas ICS and Gmail into one reviewable deadline inbox.
   把 Canvas ICS 和 Gmail 汇总到同一个可审核的 deadline inbox 里。

2. Semantic-first identity / 语义优先识别  
   Internal identity is stable via `entity_uid`, while user-facing display stays intuitive with `course + family + ordinal`.
   内部通过稳定的 `entity_uid` 维持身份一致性，用户侧则保持 `course + family + ordinal` 的直观展示。

3. Review before commit / 审核后生效  
   Incoming source data becomes pending `changes`; only approved changes update `event_entities`.
   新进入的数据先变成待审核 `changes`，只有批准后才会写入 `event_entities`。

4. Delta-first ingestion / 增量优先摄取  
   ICS uses RFC-based delta detection so only changed VEVENT components go through expensive parsing.
   ICS 使用基于 RFC 的 delta detection，只对真正变化的 VEVENT component 做高成本解析。

5. Frozen evidence / 冻结证据  
   Review previews remain readable even after source data changes.
   即使源数据后续变化，review 预览里仍然能看到当时冻结下来的证据。

6. Manual correction path / 支持人工修正  
   Users can directly correct due dates when parser output is imperfect.
   当 parser 结果不理想时，用户可以直接手动修正 due date。

7. Notification-ready / 及时提醒  
   New pending changes can immediately trigger review notifications.
   一旦产生新的 pending changes，就可以立即触发 review 通知。

## Core Flow / 核心流程

High-level flow / 主流程：

1. ingest input sources and build source observations  
   摄取输入源并生成 source observations
2. apply deterministic ICS delta handling first  
   先执行确定性的 ICS 增量处理
3. send only changed records to LLM parsing  
   仅把变化记录送入 LLM 解析
4. generate pending review proposals in `changes`  
   在 `changes` 中生成待审核提案
5. approve proposals into `event_entities`  
   用户批准后写入 `event_entities`
6. send review notifications  
   发送 review 通知

Key runtime rules / 关键运行规则：

1. ICS canonical fields such as `title/start/end/status/location` remain parser/source-deterministic.  
   ICS 的关键字段保持 deterministic，不交给 LLM 重写。
2. LLM contributes semantic enrichment such as course parsing, event parts, and link signals.  
   LLM 主要负责 course parse、event parts、link signals 等语义增强。
3. Candidate link review is separate from the canonical pending-notification chain.  
   link candidate 审核与 canonical change 通知链路分离。
4. Approved semantic state lives in `event_entities`.  
   已批准的最终状态统一保存在 `event_entities`。

## Runtime Topology / 运行架构

Current runtime / 当前运行拓扑：

1. `public-service` (`services.public_api.main:app`)
2. `input-service` (`services.input_api.main:app`, internal metrics/runtime only)
3. `ingest-service` (`services.ingest_api.main:app`)
4. `llm-service` (`services.llm_api.main:app`)
5. `review-service` (`services.review_api.main:app`, internal apply/runtime only)
6. `notification-service` (`services.notification_api.main:app`)
7. `postgres`
8. `redis`

Public traffic goes through the unified public gateway, while internal services handle ingest, parsing, review, and notification work.

用户流量统一经过 public gateway，内部服务分别处理 ingest、LLM parsing、review 和 notification。

## Quick Start / 快速开始

Useful guides / 推荐先读：

- `docs/frontend_console_release_acceptance.md`
- `docs/deploy_three_layer_runtime.md`
- `docs/nginx_live_routing_architecture.md`
- `docs/architecture.md`

### 1. Install Dependencies / 安装依赖

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
cd frontend && npm install && cd ..
```

### 2. Start the Full Local Stack / 启动本地完整栈

```bash
scripts/dev_stack.sh up
```

This launcher will / 这个启动器会：

1. start `postgres` and `redis` via `docker compose`
2. apply schema with `python -m alembic upgrade head`
3. start `frontend`, `public-service`, `input-service`, `ingest-service`, `llm-service`, `review-service`, and `notification-service`
4. write pid/log files under `output/dev-stack/`
5. keep PostgreSQL and Redis running unless you explicitly stop them with `scripts/dev_stack.sh down --infra`
6. support `scripts/dev_stack.sh reset` to reset the configured database and restart the stack

`down --infra` only stops the `postgres` and `redis` services defined in this repo. It does not stop unrelated local instances already using the same ports.

`down --infra` 只会停止本仓库 docker compose 定义的 `postgres` 和 `redis`，不会影响你机器上其他占用相同端口的实例。

Helpful commands / 常用命令：

```bash
scripts/dev_stack.sh status
scripts/dev_stack.sh logs frontend
scripts/dev_stack.sh logs all
scripts/dev_stack.sh reset
scripts/dev_stack.sh down
scripts/dev_stack.sh down --infra
```

### 3. Manual Startup / 手动逐个服务启动

If you want to run services one by one / 如果你想逐个启动服务：

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

## Docker Compose / 容器编排

Run the full local stack / 启动完整本地栈：

```bash
docker compose up --build
```

Compose includes / 默认包含：

1. `postgres`
2. `redis`
3. `public-service`
4. `input-service`
5. `ingest-service`
6. `llm-service`
7. `review-service`
8. `notification-service`
9. `frontend`

Default host ports / 默认暴露端口：

1. `frontend` on `localhost:3000`
2. `public-service` on `localhost:8000`

For day-to-day local work, prefer `scripts/dev_stack.sh up` and the `820x` port set.

日常本地开发更推荐使用 `scripts/dev_stack.sh up`，以及 `820x` 端口组。

`input-service`, `review-service`, `ingest-service`, `llm-service`, and `notification-service` are internal-only in default compose. Use `docker-compose.dev.yml` if you want internal port exposure for debugging.

默认 compose 下，`input-service`、`review-service`、`ingest-service`、`llm-service`、`notification-service` 仅供内部访问；如果调试需要暴露内部端口，请使用 `docker-compose.dev.yml`。

If you enable Gmail OAuth under compose, set `HOST_SECRETS_DIR` to the parent directory of `GMAIL_OAUTH_CLIENT_SECRETS_FILE`.

如果你在 compose 下启用 Gmail OAuth，请把 `HOST_SECRETS_DIR` 设为 `GMAIL_OAUTH_CLIENT_SECRETS_FILE` 所在目录的父目录。

## Core Environment Variables / 核心环境变量

### Required / 必填

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

### Ingestion LLM / Ingestion LLM 配置

```env
APP_LLM_OPENAI_MODEL=
INGESTION_LLM_MODEL=
INGESTION_LLM_BASE_URL=
INGESTION_LLM_API_KEY=
```

Under `docker compose`, `INGESTION_LLM_MODEL`, `INGESTION_LLM_BASE_URL`, and `INGESTION_LLM_API_KEY` are required. Compose will fail fast if any are blank.

在 `docker compose` 下，`INGESTION_LLM_MODEL`、`INGESTION_LLM_BASE_URL`、`INGESTION_LLM_API_KEY` 都是必填；为空时 compose 会直接失败。

### OAuth Runtime Config / OAuth 运行配置

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

Input-service logs the effective OAuth runtime values on startup, including:

1. final Gmail redirect URI
2. registered callback routes
3. OAuth key source (`OAUTH_TOKEN_ENCRYPTION_KEY` or `APP_SECRET_KEY`)

`input-service` 启动时会输出最终生效的 OAuth 配置，包括：

1. Gmail redirect URI
2. 注册的 callback routes
3. OAuth key 的来源（`OAUTH_TOKEN_ENCRYPTION_KEY` 或 `APP_SECRET_KEY`）

### Optional Gmail Endpoint Overrides / Gmail 本地覆盖配置

```env
GMAIL_API_BASE_URL=http://127.0.0.1:8765/gmail/v1/users/me
GMAIL_OAUTH_TOKEN_URL=http://127.0.0.1:8765/oauth2/token
GMAIL_OAUTH_AUTHORIZE_URL=http://127.0.0.1:8765/oauth2/auth
```

### Worker Intervals / Worker 轮询间隔

```env
INGESTION_TICK_SECONDS=2
LLM_SERVICE_ENABLE_WORKER=true
REVIEW_APPLY_TICK_SECONDS=2
NOTIFICATION_TICK_SECONDS=5
```

### Notification Sink Mode / 通知输出模式

```env
# smtp (default) or jsonl (for local demo without real email side effects)
NOTIFY_SINK_MODE=smtp
NOTIFY_JSONL_PATH=data/smoke/notify_sink.jsonl
```

### Real Gmail SMTP Notifications / 真实 Gmail SMTP 发信

Use this when you want real outgoing reminder emails.

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

Operational notes / 运行说明：

1. Gmail App Password requires 2-Step Verification.  
   Gmail App Password 需要先开启两步验证。
2. Keep `SMTP_USERNAME` and `SMTP_FROM_EMAIL` aligned unless you intentionally use aliases.  
   除非你明确在用 alias，否则 `SMTP_USERNAME` 和 `SMTP_FROM_EMAIL` 最好保持一致。
3. `SMTP_FROM_NAME` controls the human-readable sender name.  
   `SMTP_FROM_NAME` 控制发件人显示名。
4. Turn on `ENABLE_NOTIFICATIONS=true` before expecting notification delivery.  
   想让通知真的发出去，记得打开 `ENABLE_NOTIFICATIONS=true`。

### Unified Public API Base URL / 统一公开 API 地址

```env
BACKEND_BASE_URL=http://localhost:8200
```

## Internal Ops Auth / 内部运维认证

`/internal/*` endpoints no longer accept `X-API-Key`.

`/internal/*` 接口不再接受 `X-API-Key`。

Use service-token headers / 请使用 service token 请求头：

```http
X-Service-Name: ops
X-Service-Token: <INTERNAL_SERVICE_TOKEN_OPS>
```

Worker toggles / Worker 开关：

```env
INGEST_SERVICE_ENABLE_WORKER=true
REVIEW_SERVICE_ENABLE_APPLY_WORKER=true
NOTIFICATION_SERVICE_ENABLE_WORKER=true
ENABLE_NOTIFICATIONS=false
```

## Health Checks / 健康检查

```bash
curl -s http://localhost:8200/health
curl -s http://localhost:8201/health
curl -s http://localhost:8202/health
curl -s http://localhost:8203/health
curl -s http://localhost:8204/health
curl -s http://localhost:8205/health
```

## Smoke Tests / 冒烟测试

### Real Source Smoke / 真实源三轮冒烟

```bash
python scripts/smoke_real_sources_three_rounds.py \
  --public-api-base http://127.0.0.1:8200 \
  --report data/synthetic/ddlchange_160/qa/real_source_smoke_report.json
```

### Semester Demo Smoke / 学期演示冒烟

Use online LLM + local JSONL notification sink. This flow does not require Gmail OAuth.

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

Notification flush endpoint / 通知刷新接口：

```http
POST /internal/notifications/flush
X-Service-Name: ops
X-Service-Token: <INTERNAL_SERVICE_TOKEN_OPS>
```

Online pytest wrapper / 在线 pytest 封装：

```bash
RUN_SEMESTER_DEMO_SMOKE=true \
SEMESTER_DEMO_NOTIFICATION_JSONL=data/smoke/notify_sink.jsonl \
pytest -q tests/test_semester_demo_online.py
```

Full closure check / 完整闭环检查：

```bash
python scripts/smoke_microservice_closure.py \
  --public-api-base http://127.0.0.1:8200 \
  --input-internal-base http://127.0.0.1:8201 \
  --review-internal-base http://127.0.0.1:8203 \
  --ingest-internal-base http://127.0.0.1:8202 \
  --notify-internal-base http://127.0.0.1:8204 \
  --llm-internal-base http://127.0.0.1:8205
```

SLO check / SLO 检查：

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

OpenAPI snapshots / OpenAPI 快照更新：

```bash
python scripts/update_openapi_snapshots.py
```

## Review Model / 审核模型

Review-service supports both proposal review and direct canonical edit.

Review-service 同时支持 proposal review 和 direct canonical edit。

Key behavior / 关键行为：

1. `POST /review/edits/preview`
2. `POST /review/edits` with `mode=canonical`
3. target can be provided by `change_id` or `entity_uid`
4. date-only `patch.due_at` is normalized to `23:59` in `users.timezone_name`
5. conflicting pending changes for the same `entity_uid` are auto-rejected
6. canonical edit writes an approved audit change and emits `review.decision.approved`

## Local Quality Checks / 本地质量检查

Run in this order / 推荐按这个顺序运行：

```bash
mypy .
flake8 .
python -m build
```

Notes / 说明：

1. `mypy` uses `explicit_package_bases`, so `services/*/main.py` does not collide as duplicate top-level `main`.
2. `flake8` excludes environment/vendor/history-heavy paths such as `.venv`, `tools`, and `app/db/migrations`.
3. `python -m build` requires the `build` package, which is already included in `requirements.txt`.

## Testing / 测试

```bash
source .venv/bin/activate
python -m pytest -q
```

## API and Docs / API 与文档

API snapshots / API 快照：

1. `docs/api_surface_current.md`
2. `docs/event_contracts.md`

Core docs / 核心文档：

1. `docs/frontend_console_release_acceptance.md`
2. `docs/deploy_three_layer_runtime.md`
3. `docs/architecture.md`
4. `docs/service_table_ownership.md`
5. `docs/ops_microservice_slo.md`
6. `docs/dataflow_input_to_notification.md`
7. `docs/archive/README.md`
