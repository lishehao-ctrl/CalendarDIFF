# Gmail EMAIL Source MVP Runbook

## 目标

在现有 Input -> Sync -> Change -> Notify 主链路上，验证 Gmail 邮件输入（`type=email`, `provider=gmail`）可用，并确认 baseline-first、增量同步、变更入库和通知行为。

## 前置条件

1. 后端已启动：`http://localhost:8000`
2. PostgreSQL schema 已升级到 head
3. 已配置 `.env`:

```env
APP_BASE_URL=http://localhost:8000
GMAIL_OAUTH_CLIENT_ID=...
GMAIL_OAUTH_CLIENT_SECRET=...
GMAIL_OAUTH_REDIRECT_URI=http://localhost:8000/v1/oauth/gmail/callback
GMAIL_OAUTH_SCOPE=https://www.googleapis.com/auth/gmail.readonly
```

4. Google Cloud Console 已创建 OAuth Client（Web application）
5. Redirect URI 已加入：`http://localhost:8000/v1/oauth/gmail/callback`

## 本地启动

```bash
docker compose up -d postgres
scripts/reset_postgres_db.sh
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

打开 `http://localhost:8000/ui`。

## UI 创建 Gmail Input

1. 先选择一个 User（若没有会自动创建默认 user）。
2. 在 Input Layer 的 `Connect Gmail Input` 卡片填写：
   - `Gmail Label`（可选，名称语义，如 `INBOX`）
   - `From Contains`（可选）
   - `Subject Keywords`（可选，逗号分隔，OR 语义）
3. 点击 `Connect Gmail`。
4. 完成 Google OAuth 授权后，浏览器回跳 `ui`，看到成功 toast。

说明：
- 本流程不需要 `name` 字段。
- Gmail input 默认是 Global（`user_term_id=NULL`，不绑定学期）。

## 同步语义验收

### 1) Baseline-first

1. 对新 Gmail input 执行第一次 `Sync now`。
2. 预期：
   - `changes_created=0`
   - `is_baseline_sync=true`
   - 不发通知
   - 仅更新 Gmail cursor（historyId）

### 2) 增量变化

1. 发送一封新邮件，命中过滤条件。
2. 再次 `Sync now`。
3. 预期：
   - `changes_created > 0`
   - run 状态为 `CHANGED`（通知失败时为 `EMAIL_FAILED`）
   - 每封新邮件生成一条 Change，`event_uid=message_id`

### 3) 去重

1. 对同样的增量窗口重复 sync。
2. 预期：已入库的 `message_id` 不重复创建 Change。

## 数据检查

### Input 视图

```bash
curl -sS -H "X-API-Key: <APP_API_KEY>" \
  "http://localhost:8000/v1/inputs"
```

关注字段：
- `type=email`
- `provider=gmail`
- `gmail_label`
- `gmail_from_contains`
- `gmail_subject_keywords`
- `gmail_account_email`

### Changes 视图

```bash
curl -sS -H "X-API-Key: <APP_API_KEY>" \
  "http://localhost:8000/v1/inputs/<id>/changes?limit=20"
```

关注 `after_json`：
- `subject`
- `snippet`
- `internal_date`
- `from`
- `gmail_message_id`
- `open_in_gmail_url`

### Runs 时间线

```bash
curl -sS -H "X-API-Key: <APP_API_KEY>" \
  "http://localhost:8000/v1/inputs/<id>/runs?limit=20"
```

关注：
- baseline: `NO_CHANGE`
- 增量成功: `CHANGED`
- 通知失败: `EMAIL_FAILED`

## 常见问题

1. OAuth start 返回 503：
   - 检查 `GMAIL_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI` 是否配置并重启后端。
2. 回调后失败：
   - 检查 Redirect URI 是否与 Google Console 完全一致。
3. 没有任何 Change：
   - 首次 sync 是 baseline-first，不会产出变更。
   - 检查 label/from/subject 过滤是否过严。
