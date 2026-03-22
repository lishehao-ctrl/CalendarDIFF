# CalendarDIFF

CalendarDIFF 是一个单机部署、单体后端的截止日期变更工作台，用来把课程里真正影响成绩的时间变化收敛到一个流程里。

它不是一个“所有课程邮件分类器”。
它的核心目标是：

1. 接入 Canvas ICS 和 Gmail
2. 建立 canonical baseline
3. 产出安全可审阅的 proposal
4. 把后续 replay 变化集中到一个日常 review lane

## 当前产品形态

当前用户可见的主 lane：

- `Overview`
- `Sources`
- `Changes`
- `Families`
- `Manual`
- `Settings`

重要区分：

- `Initial Review` 是首次导入后的阶段性基线审阅
- `Changes` 是 baseline 建好之后的日常 replay 审阅

推荐用户心智：

1. 注册 / 登录
2. 完成 onboarding
3. 接入必需的 Canvas ICS
4. 按需接入 Gmail
5. 选择初始 monitoring window
6. 完成 `Initial Review`
7. 日常使用 `Changes`

## 默认运行时

CalendarDIFF 现在默认只运行一个后端进程。

- 后端入口：`services.app_api.main:app`
- 前端：`frontend/` 下的 Next.js
- 基础设施：PostgreSQL + Redis

默认本地端口：

- Backend: `8200`
- Frontend: `3000`
- PostgreSQL: `5432`
- Redis: `6379`

旧的 split-service 拓扑不再是默认仓库路径。

## 本地启动

1. 复制 `.env.example` 为 `.env` 并填写必要配置。
2. 安装后端依赖。
3. 安装前端依赖：

```bash
cd frontend && npm install
```

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

`SERVICE_NAME` 只接受 `backend`。

## 公开 HTTP 接口

当前公开 route group：

- `/auth/*`
- `/settings/profile`
- `/sources/*`
- `/onboarding/*`
- `/changes*`
- `/families*`
- `/manual/events*`
- `/health`

当前 onboarding 相关接口：

- `POST /onboarding/registrations`
- `GET /onboarding/status`
- `POST /onboarding/canvas-ics`
- `POST /onboarding/gmail/oauth-sessions`
- `POST /onboarding/gmail-skip`
- `POST /onboarding/monitoring-window`

## 运行时真相

`sync_requests` 是当前唯一用户可见的运行时状态机。

细粒度运行时真相在：

- `stage`
- `substage`
- `stage_updated_at`
- `progress_json`

用户可见的 source posture 和 workspace posture 都应该基于这些显式状态生成，而不是继续从旧 payload 里猜。

## 当前已上线的产品 contract

前端现在已经可以直接消费：

- `GET /changes/summary`
  - `workspace_posture`
- `GET /changes`
  - 每条 item 上的 `decision_support`
- `GET /sources`
  - `source_product_phase`
  - `source_recovery`
- `GET /sources/{source_id}/observability`
  - `bootstrap_summary`
  - `source_product_phase`
  - `source_recovery`

## 可选集成

当前仍支持：

- Gmail OAuth
- Canvas ICS
- SMTP
- fixture / probe 脚本

部署规则：

- BERT / Gmail secondary filter 不是必需运行路径
- 生产默认仍应保持：
  - `GMAIL_SECONDARY_FILTER_MODE=off`
  - `GMAIL_SECONDARY_FILTER_PROVIDER=noop`

推荐架构约束：

- 把 Gmail secondary filter 当成可插拔模块，而不是生产必需依赖
- 训练/评估资产与主运行路径分开
- 只通过配置切换运行模式：
  - `off`
  - `shadow`
  - `enforce`
- onboarding、source intake、review、deploy health 都不能依赖 BERT 模块在线

## OpenAPI

默认快照：

```text
contracts/openapi/public-service.json
```

刷新方式：

```bash
python scripts/update_openapi_snapshots.py
```

## 部署

当前生产环境：

- 域名：`cal.shehao.app`
- 主机：`ubuntu@54.152.242.119`
- 应用目录：`/home/ubuntu/apps/CalendarDIFF`

共享主机规则：

- CalendarDIFF 只拥有 `cal.shehao.app`
- RPG 保持在 `rpg.shehao.app`

改线上前先读：

- `skills/aws-release/SKILL.md`
- `docs/deploy_three_layer_runtime.md`
- `docs/nginx_live_routing_architecture.md`

常规 AWS 同步入口：

```bash
scripts/release_aws_main.sh
```

这个脚本现在是完整发布动作，不只是同步 git：

- 把 AWS checkout 同步到本地 `HEAD`
- 重建并重启 `frontend` 和 `public-service`
- 校验 `health` 与 `login`

这次真实生产发布流程记录在：

- `docs/production_release_runbook_2026_03_21.md`

## 验证基线

后端回归：

```bash
pytest tests/test_review_items_summary_api.py \
  tests/test_review_change_source_summary_api.py \
  tests/test_source_sync_progress_api.py \
  tests/test_source_read_bridge.py \
  tests/test_openapi_contract_snapshots.py \
  tests/test_review_changes_unified.py \
  tests/test_review_changes_batch_api.py \
  tests/test_review_edits_api.py
```

前端回归：

```bash
cd frontend
npm run typecheck
npm run lint
NEXT_DIST_DIR=.next-prod npm run build
```
