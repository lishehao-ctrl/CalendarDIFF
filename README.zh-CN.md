# CalendarDIFF

CalendarDIFF 现在默认只运行一个后端进程。

## 默认运行时
- 后端入口：`services.app_api.main:app`
- 兼容别名：`services.public_api.main:app`
- 前端：`frontend/` 下的 Next.js
- 基础设施：PostgreSQL + Redis
- 默认端口：
  - Backend `8200`
  - Frontend `3000`
  - PostgreSQL `5432`
  - Redis `6379`

旧的 split-service 拓扑已经退出默认仓库路径，仓库默认心智不再是 `input/ingest/review/notification/llm` 多进程启动。

## 本地启动
1. 复制 `.env.example` 为 `.env` 并填写必要配置。
2. 安装后端依赖。
3. 安装前端依赖：`cd frontend && npm install`。
4. 启动默认栈：

```bash
./scripts/dev_stack.sh up
```

常用命令：

```bash
./scripts/dev_stack.sh status
./scripts/dev_stack.sh logs backend
./scripts/dev_stack.sh logs frontend
./scripts/dev_stack.sh down
./scripts/dev_stack.sh down --infra
./scripts/dev_stack.sh reset
```

健康检查：

```bash
curl http://127.0.0.1:8200/health
```

## 直接启动后端
```bash
SERVICE_NAME=backend RUN_MIGRATIONS=true PORT=8200 ./scripts/start_service.sh
```

`SERVICE_NAME` 现在只接受 `backend`。

## 公开 HTTP 接口
- `/auth/*`
- `/profile/me`
- `/sources/*`
- `/review/changes*`
- `/review/links*`
- `/review/course-work-item-families*`
- `/review/course-work-item-raw-types*`
- `/events/manual*`
- `/onboarding/*`
- `/health`

## OpenAPI
仓库只保留一份默认快照：

```text
contracts/openapi/public-service.json
```

刷新方式：

```bash
python scripts/update_openapi_snapshots.py
```

## Worker 模型
单体后端内部仍会运行 ingest、review-apply、notification、llm 这些 worker loop，但它们现在是同一个 backend 进程里的后台任务，不再是独立服务。

保留的 worker 开关：
- `INGEST_SERVICE_ENABLE_WORKER`
- `REVIEW_SERVICE_ENABLE_APPLY_WORKER`
- `NOTIFICATION_SERVICE_ENABLE_WORKER`
- `LLM_SERVICE_ENABLE_WORKER`

## 可选集成
Gmail OAuth、Canvas ICS、SMTP、fixture/probe 脚本仍然保留，但它们不再属于默认运行时叙事。

## 验证基线
后端回归：

```bash
pytest tests/test_core_ingest_gmail_directive_apply.py \
  tests/test_core_ingest_apply_calendar_delta.py \
  tests/test_input_gmail_source_api.py \
  tests/test_input_ics_source_api.py \
  tests/test_input_oauth_service.py \
  tests/test_onboarding_flow_api.py \
  tests/test_review_*.py \
  tests/test_manual_events_api.py \
  tests/test_course_work_item_families_api.py \
  tests/test_course_raw_types_api.py \
  tests/test_users_timezone_api.py \
  tests/test_openapi_contract_snapshots.py \
  tests/test_runtime_entrypoints.py
```

前端回归：

```bash
cd frontend
npm run typecheck
npm run lint
NEXT_DIST_DIR=.next-prod npm run build
```
