# Semester Demo 测试报告（中文）

## 测试范围
- 目标：验证 `ICS fake source + Gmail-compatible fake inbox + input/ingest/llm/review/notify` 的真实联调闭环。
- 真实部分：LLM 调用走线上配置的 `INGESTION_LLM_*`。
- 模拟部分：Gmail inbox 走 fake provider；通知走 `jsonl` sink 和 `POST /internal/notifications/flush`。
- 排除项：OAuth/Gmail callback/redirect/client secrets、真实 SMTP。

## 环境快照
- 数据库：使用隔离测试库 `deadline_diff_test`，已重建并迁移到 head。
- Redis：宿主机 `127.0.0.1:6379` 可达，联调前已 `FLUSHDB`。
- 服务：`input(8001)`、`review(8000)`、`ingest(8002)`、`notification(8004)`、`llm(8005)` 全部 `/health=200`。
- 运行模式：
  - `ENABLE_NOTIFICATIONS=true`
  - `NOTIFY_SINK_MODE=jsonl`
  - `NOTIFICATION_SERVICE_ENABLE_WORKER=false`
  - `INGEST_SERVICE_ENABLE_WORKER=true`
  - `REVIEW_SERVICE_ENABLE_APPLY_WORKER=true`
  - `LLM_SERVICE_ENABLE_WORKER=true`
  - `GMAIL_API_BASE_URL=http://127.0.0.1:8765/gmail/v1/users/me`

## 执行命令
- 离线守卫与回归：相关 14 个测试文件，结果 `30 passed`。
- 主联调：
  - `python scripts/smoke_semester_demo.py --input-api-base http://127.0.0.1:8001 --review-api-base http://127.0.0.1:8000 --ingest-api-base http://127.0.0.1:8002 --notify-api-base http://127.0.0.1:8004 --llm-api-base http://127.0.0.1:8005 --api-key "$APP_API_KEY" --ops-token "$INTERNAL_SERVICE_TOKEN_OPS" --notification-jsonl data/smoke/notify_sink.jsonl --report data/synthetic/semester_demo/qa/semester_demo_report.json`
- 质量门禁：
  - `mypy .`
  - `flake8 .`
  - `python -m build`

## 结果汇总
- 离线守卫：通过。
- 主联调：通过。
- 质量门禁：通过。
- 最终结论：`通过`。

## 关键验收项
- 结构化报告：`semester_demo_report.json` 中 `passed=true`。
- `fatal_errors=[]`
- `failed_assertions=0`
- 每学期规模：
  - Semester 1: `ICS=100`, `Gmail=100`
  - Semester 2: `ICS=100`, `Gmail=100`
  - Semester 3: `ICS=100`, `Gmail=100`
- 通知链路：
  - `notification_flush.batches_flushed=30`
  - `notification_flush.enqueued_notifications=30`
  - `notification_flush.processed_slots=2`
  - `notification_flush.sent_count=1`
  - `notification_flush.failed_count=0`
- JSONL sink：
  - `rows_delta=1`

## Edge Case 覆盖分析
- 已覆盖并在联调中通过：
  - suffix 缺失：`suffix_required_missing`
  - suffix 错配：`suffix_mismatch`
  - suffix 精确匹配：`auto_link`
  - 同课程别名/大小写/分隔符变化
  - Gmail baseline round 0
  - `label_id=INBOX` 过滤路径
  - flush 触发通知发送
  - JSONL sink 写入 `run_id/semester/batch`
  - fake inbox 保留 `thread_id/from_header/label_ids/internalDate`
- 规模判断：当前基线规模已能覆盖目标 edge cases，暂无必要扩到 `3x15x15`。

## LLM 表现分析
- 真实 LLM 调用已发生并成功参与主联调。
- 从服务日志可观察到：
  - `calendar_event_enrichment` 多次成功返回 `200`
  - `gmail_message_extract` 多次成功返回 `200`
- 指标侧未见：
  - rate limit
  - retry schedule
  - notify failure
- 现有结论：LLM 调用链路已经打通，且在本轮基线规模下可稳定工作。

## 问题与修复摘要
本轮联调前，先后修复了以下阻断：
- `xautoclaim` 返回值兼容性问题
- `LLM_ENQUEUE_PENDING` 被 `next_retry_at` 误阻塞的问题
- `parse_pipeline` Gmail 分支缩进错误
- `calendar delta` 仍输出 legacy `uid` 的问题
- `MessagePreflight` 在 DB/queue 竞态下错误 ack 的问题
- `APP_LLM_OPENAI_MODEL` 对 `INGESTION_LLM_MODEL` 的 fallback
- 在线 smoke pytest 被 `tests/conftest.py` 夹具环境污染的问题
- review decision 响应状态比较逻辑错误（`approve` vs `approved`）

## 风险与后续建议
- 当前主联调已经通过，可以作为后端闭环验证基线。
- 在线 pytest 包装测试仍然会重复跑一次 full smoke，执行时间较长，建议后续单独给它加一个“快速模式”或缩小默认规模。
- 如果后续要做更高置信度压测，再考虑扩到 `3x15x15`。

## 最终结论
- 结论：`通过`
- 本轮主联调已验证：fake ICS/fake Gmail inbox + 真实 LLM + review + notify 的后端闭环可跑通。
