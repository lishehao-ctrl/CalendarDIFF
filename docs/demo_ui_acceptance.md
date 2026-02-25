# Demo UI 验收执行手册（PostgreSQL + 单进程）

## 简要逻辑

当前是“单进程 + 单入口”模式：

1. FastAPI 负责业务 API 与 UI 静态文件托管。
2. UI 静态文件来自 `frontend/out`（由 `frontend` 项目构建）。
3. `apiKey` 通过后端 `/ui/app-config.js` 注入。
4. 验收入口固定为 `http://localhost:8000/ui`。

## 验收前启动步骤

1. 构建 UI 静态资源：

```bash
cd frontend
npm ci
npm run build
cd ..
```

2. 启动 PostgreSQL：

```bash
docker compose up -d postgres
```

3. 重置数据库（推荐）：

```bash
scripts/reset_postgres_db.sh
```

4. 启动后端：

```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

5. 只用这个地址验收：

- `http://localhost:8000/ui`

## 验收清单（逐项通过）

1. 配置注入正常  
执行：

```bash
curl http://localhost:8000/ui/app-config.js
```

期望：返回里有 `window.__APP_CONFIG__` 且包含 `apiKey`。

2. UI 主页面可打开  
访问 `http://localhost:8000/ui`。  
期望：页面正常渲染，不出现 `Configuration Missing / Missing API key`。

3. Inputs 列表与健康面板可读  
期望：页面顶部健康卡片有 run 计数和 `next_expected_check` 信息；Inputs 区域可刷新。

4. 创建 input 成功  
先完成 onboarding；在 Input Layer 的 `Add Calendar Input` 卡片填写 `url`。  
期望：toast 显示创建成功，input 出现在表格。

5. 第一次手动同步是 baseline  
点击 `Sync now`。  
期望：toast 包含 `baseline established, no diff generated`，Diff Review 初始无噪声变化。

6. Diff 审阅交互正常  
在有变化后，Unread 中点 `Mark Viewed`。  
期望：该卡片立刻从 Unread 消失；切换 All 可看到其 viewed 状态；点 `Mark Unread` 后可回到 Unread。

7. Evidence 下载可用  
在 diff 卡片点击 `Download Before ICS` 和 `Download After ICS`。  
期望：两份 `.ics` 文件都能下载且可打开。

8. Identity upsert 逻辑正常  
用相同 ICS URL 再创建一次 Calendar input。  
期望：提示 upsert existing，不新增第二条同身份 input，历史 runs/changes 保留。

9. 健康统计随操作变化  
多次 sync 后刷新健康卡。  
期望：`last_run_*`、`cumulative_*`、`next_expected_check_at` 有合理变化。

10. 定时同步可观察  
等待调度器自然触发，检查 `last_checked_at` 与 health 中 run 相关字段是否推进。

## 常见误区与快速排查

1. 打开 `http://localhost:8000/ui` 返回 `UI assets are missing`  
原因：`frontend/out` 未构建。  
处理：执行 `cd frontend && npm ci && npm run build`。

2. `curl /ui/app-config.js` 没有 `apiKey`  
原因：`.env` 中 `APP_API_KEY` 未配置。  
处理：补齐 `.env` 并重启后端。

3. `scripts/reset_postgres_db.sh` 认证失败  
原因：本地 PostgreSQL 凭据与 `.env` 不一致。  
处理：对齐 `DATABASE_URL` 与 compose 的 `postgres/postgres`，或更新 compose 环境变量。

4. `npm install` 报 `ENOENT package.json`  
原因：在项目根目录执行了 npm。  
处理：先 `cd frontend` 再执行 npm 命令。

## 验收通过标准（最小集合）

1. `http://localhost:8000/ui` 能稳定打开且无 `Configuration Missing`。  
2. 创建 input、manual sync、baseline-first、diff review、evidence download 全链路可用。  
3. identity upsert 行为正确且不制造历史噪声。  
4. `/health` 与页面健康卡显示 scheduler 字段且随操作变化。
