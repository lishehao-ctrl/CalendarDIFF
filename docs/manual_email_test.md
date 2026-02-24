# Manual Email Test (MailHog)

## Preconditions

在开始前，确保以下条件满足：

1. 后端已运行在 `http://localhost:8000`。
2. 你有有效的 `APP_API_KEY`（用于 `X-API-Key` 请求头）。
3. PostgreSQL 与 schema 已就绪（例如已执行 `scripts/reset_postgres_db.sh`）。
4. 通知开关开启：`ENABLE_NOTIFICATIONS=true`。
5. 变更 SMTP 环境变量后需要重启后端进程（配置在进程启动时加载）。

---

## 1) Start MailHog (1025/8025)

先清理旧容器（如果有），再启动固定版本：

```bash
docker rm -f calendardiff-mailhog 2>/dev/null || true
docker run --name calendardiff-mailhog -d -p 1025:1025 -p 8025:8025 mailhog/mailhog:v1.0.1
docker ps --filter "name=calendardiff-mailhog"
```

验证：

1. MailHog Web UI 可访问：`http://localhost:8025`
2. 容器状态为 `Up`。

---

## 2) SMTP Environment Variables (No Auth, STARTTLS=false)

在 `.env` 中使用以下示例（与项目当前配置别名一致）：

```env
ENABLE_NOTIFICATIONS=true
SMTP_HOST=127.0.0.1
SMTP_PORT=1025
SMTP_USER=
SMTP_PASS=
SMTP_USE_TLS=false
SMTP_FROM=no-reply@example.com
SMTP_TO=notify@example.com
```

说明：

1. MailHog 默认无鉴权，`SMTP_USER/SMTP_PASS` 为空即可。
2. `SMTP_USE_TLS=false` 等价于本项目下的 “STARTTLS=false”。
3. 通知收件人由 User 决定（`user.notify_email`）；若为空则回退 `SMTP_TO`。

---

## 3) Serve Local test.ics via python http.server

在单独终端创建并托管本地 ICS（v1）：

```bash
mkdir -p /tmp/calendardiff-mailtest
cat > /tmp/calendardiff-mailtest/test.ics <<'ICS'
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//CalendarDIFF Manual Email Test//EN
BEGIN:VEVENT
UID:manual-email-test-1
DTSTART:20260224T090000Z
DTEND:20260224T100000Z
SUMMARY:CSE 151A Homework 1
DESCRIPTION:submit to portal
END:VEVENT
END:VCALENDAR
ICS
cd /tmp/calendardiff-mailtest
python3 -m http.server 18080
```

后续 input URL 使用：

- `http://127.0.0.1:18080/test.ics`

---

## 4) Onboarding Register + Baseline Sync (No Email Expected)

### 4.1 设置请求变量

```bash
export BASE_URL="http://localhost:8000"
export API_KEY="<APP_API_KEY>"
```

### 4.2 完成 onboarding register（必填 notify_email + first term + ICS URL）

首次运行或 reset DB 后，调用一体化注册接口并直接获得 `input_id`：

```bash
REGISTER_RESPONSE=$(
  curl -sS -X POST "${BASE_URL}/v1/onboarding/register" \
    -H "X-API-Key: ${API_KEY}" \
    -H "Content-Type: application/json" \
    -d '{
      "notify_email": "notify@example.com",
      "term": {
        "code": "WI26",
        "label": "Winter 2026",
        "starts_on": "2026-01-06",
        "ends_on": "2026-03-21"
      },
      "ics": {
        "url": "http://127.0.0.1:18080/test.ics"
      }
    }'
)
echo "${REGISTER_RESPONSE}" | python3 -m json.tool
INPUT_ID=$(echo "${REGISTER_RESPONSE}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["input_id"])')
echo "INPUT_ID=${INPUT_ID}"
```

期望：

1. `status=ready`
2. `is_baseline_sync=true`
3. `changes_created=0`

如需调整 user 资料（可选），继续使用 `PATCH /v1/user`：

```bash
curl -sS -X PATCH "${BASE_URL}/v1/user" \
  -H "X-API-Key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "notify_email": "notify@example.com",
    "calendar_delay_seconds": 120
  }' \
  | python3 -m json.tool
```

### 4.3 验证 onboarding status 为 ready

```bash
curl -sS "${BASE_URL}/v1/onboarding/status" \
  -H "X-API-Key: ${API_KEY}" \
  | python3 -m json.tool
```

期望：

1. `stage=ready`
2. `registered_user_id` 非空
3. `first_input_id` 为上一步返回的 `INPUT_ID`

### 4.4 用 API 验证 baseline 无邮件

查看 `GET /v1/inputs`（重点看 `last_email_sent_at`）：

```bash
curl -sS "${BASE_URL}/v1/inputs" \
  -H "X-API-Key: ${API_KEY}" \
  | python3 -c 'import sys,json,os; sid=int(os.environ["INPUT_ID"]); rows=json.load(sys.stdin); row=next(r for r in rows if r["id"]==sid); print(json.dumps({"id": row["id"], "display_label": row["display_label"], "last_email_sent_at": row["last_email_sent_at"], "last_result": row["last_result"]}, ensure_ascii=False, indent=2))'
```

查看 `GET /v1/inputs/{id}/runs?limit=20`（重点看最近一条 status）：

```bash
curl -sS "${BASE_URL}/v1/inputs/${INPUT_ID}/runs?limit=20" \
  -H "X-API-Key: ${API_KEY}" \
  | python3 -c 'import sys,json; rows=json.load(sys.stdin); latest=rows[0] if rows else {}; print(json.dumps({"status": latest.get("status"), "error_code": latest.get("error_code"), "changes_count": latest.get("changes_count")}, ensure_ascii=False, indent=2))'
```

期望：

1. `last_email_sent_at` 仍为 `null`
2. 最新 run `status=NO_CHANGE`（来自 onboarding 触发的 baseline run）

---

## 5) Modify ICS and Run Second Sync (CHANGED + Email Expected)

### 5.1 覆盖 test.ics 为 v2（制造真实变更）

```bash
cat > /tmp/calendardiff-mailtest/test.ics <<'ICS'
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//CalendarDIFF Manual Email Test//EN
BEGIN:VEVENT
UID:manual-email-test-1
DTSTART:20260224T100000Z
DTEND:20260224T110000Z
SUMMARY:CSE 151A Homework 1
DESCRIPTION:submit to portal
END:VEVENT
END:VCALENDAR
ICS
```

### 5.2 第二次手动 sync

```bash
curl -sS -X POST "${BASE_URL}/v1/inputs/${INPUT_ID}/sync" \
  -H "X-API-Key: ${API_KEY}" \
  | python3 -m json.tool
```

期望：

1. `is_baseline_sync=false`
2. `changes_created > 0`
3. `email_sent=true`

### 5.3 验证邮件与状态

1. 打开 MailHog UI：`http://localhost:8025`，应看到新邮件。
2. 再查 inputs：

```bash
curl -sS "${BASE_URL}/v1/inputs" \
  -H "X-API-Key: ${API_KEY}" \
  | python3 -c 'import sys,json,os; sid=int(os.environ["INPUT_ID"]); rows=json.load(sys.stdin); row=next(r for r in rows if r["id"]==sid); print(json.dumps({"last_email_sent_at": row["last_email_sent_at"], "last_result": row["last_result"]}, ensure_ascii=False, indent=2))'
```

3. 再查 runs：

```bash
curl -sS "${BASE_URL}/v1/inputs/${INPUT_ID}/runs?limit=20" \
  -H "X-API-Key: ${API_KEY}" \
  | python3 -c 'import sys,json; rows=json.load(sys.stdin); latest=rows[0] if rows else {}; print(json.dumps({"status": latest.get("status"), "error_code": latest.get("error_code"), "changes_count": latest.get("changes_count")}, ensure_ascii=False, indent=2))'
```

期望：

1. `last_email_sent_at` 非 `null`
2. 最新 run `status=CHANGED`

---

## 6) Failure Case: Wrong SMTP_PORT -> EMAIL_FAILED

### 6.1 记录当前 `last_email_sent_at`

```bash
PREV_LAST_EMAIL_SENT_AT=$(
  curl -sS "${BASE_URL}/v1/inputs" \
    -H "X-API-Key: ${API_KEY}" \
    | python3 -c 'import sys,json,os; sid=int(os.environ["INPUT_ID"]); rows=json.load(sys.stdin); row=next(r for r in rows if r["id"]==sid); print(row["last_email_sent_at"] or "null")'
)
echo "PREV_LAST_EMAIL_SENT_AT=${PREV_LAST_EMAIL_SENT_AT}"
```

### 6.2 把 SMTP 端口改错并重启后端

方式一（推荐，临时覆盖，不改 `.env`）：

```bash
source .venv/bin/activate
SMTP_PORT=1 uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

方式二：直接改 `.env` 的 `SMTP_PORT=1`，然后正常重启后端。

### 6.3 再次修改 ICS 为 v3（确保有新变化）

```bash
cat > /tmp/calendardiff-mailtest/test.ics <<'ICS'
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//CalendarDIFF Manual Email Test//EN
BEGIN:VEVENT
UID:manual-email-test-1
DTSTART:20260224T110000Z
DTEND:20260224T120000Z
SUMMARY:CSE 151A Homework 1
DESCRIPTION:submit to portal
END:VEVENT
END:VCALENDAR
ICS
```

### 6.4 再执行一次手动 sync

```bash
curl -sS -X POST "${BASE_URL}/v1/inputs/${INPUT_ID}/sync" \
  -H "X-API-Key: ${API_KEY}" \
  | python3 -m json.tool
```

期望：

1. `changes_created > 0`
2. `email_sent=false`
3. `last_error` 包含 SMTP 连接失败信息（例如连接拒绝/超时）

### 6.5 用 API 验证失败语义

`GET /v1/inputs/{id}/runs?limit=20`：

```bash
curl -sS "${BASE_URL}/v1/inputs/${INPUT_ID}/runs?limit=20" \
  -H "X-API-Key: ${API_KEY}" \
  | python3 -c 'import sys,json; rows=json.load(sys.stdin); latest=rows[0] if rows else {}; print(json.dumps({"status": latest.get("status"), "error_code": latest.get("error_code"), "error_message": latest.get("error_message")}, ensure_ascii=False, indent=2))'
```

`GET /v1/inputs`（确认 `last_email_sent_at` 不变）：

```bash
CUR_LAST_EMAIL_SENT_AT=$(
  curl -sS "${BASE_URL}/v1/inputs" \
    -H "X-API-Key: ${API_KEY}" \
    | python3 -c 'import sys,json,os; sid=int(os.environ["INPUT_ID"]); rows=json.load(sys.stdin); row=next(r for r in rows if r["id"]==sid); print(row["last_email_sent_at"] or "null")'
)
echo "CUR_LAST_EMAIL_SENT_AT=${CUR_LAST_EMAIL_SENT_AT}"
test "${CUR_LAST_EMAIL_SENT_AT}" = "${PREV_LAST_EMAIL_SENT_AT}" && echo "OK: unchanged" || echo "UNEXPECTED: changed"
```

期望：

1. 最新 run `status=EMAIL_FAILED`
2. 最新 run `error_code=email_send_failed`
3. `last_email_sent_at` 与失败前记录值一致（不更新）

---

## 7) Verification Checklist (API + MailHog UI)

| 检查项 | 通过标准 |
|---|---|
| Baseline 首次 sync | `is_baseline_sync=true`，`changes_created=0`，无邮件 |
| 第二次变更 sync | `status=CHANGED`，`email_sent=true`，MailHog 收到邮件 |
| SMTP 失败场景 | `status=EMAIL_FAILED`，`error_code=email_send_failed` |
| 失败后发信时间 | `last_email_sent_at` 不更新 |
| API 验证覆盖 | 已使用 `GET /v1/inputs` 与 `GET /v1/inputs/{id}/runs?limit=20` |

---

## Troubleshooting

1. MailHog 收件箱为空：
   - 检查 `ENABLE_NOTIFICATIONS=true`
   - 检查 `SMTP_*` 是否指向 `127.0.0.1:1025`
   - 检查本次 run 是否 baseline 或 `NO_CHANGE`（两者都不会发邮件）
2. 一直没有 `CHANGED`：
   - 确保你真的修改了 ICS 事件内容（不要只改空白）
   - 可直接修改 `DTSTART/DTEND` 以制造确定变化
3. 邮件发送到了意外地址：
   - 当前版本使用 user 级收件人：检查 `PATCH /v1/user` 设置的 `notify_email`
   - 若 user.notify_email 为空，会回退到 `SMTP_TO`
4. API 返回 401/403：
   - 检查 `X-API-Key` 与当前 `APP_API_KEY` 是否一致
5. 改了 SMTP 变量但行为未变化：
   - 后端进程未重启；重启后再测试
