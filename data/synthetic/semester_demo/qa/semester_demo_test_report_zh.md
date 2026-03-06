# Semester Demo 测试报告（中文）

## 测试范围
- 目标：验证 `ICS fake source + Gmail-compatible fake inbox + input/ingest/llm/review/notify` 的真实联调闭环。
- 真实部分：LLM 调用走线上配置的 `INGESTION_LLM_*`。
- 模拟部分：Gmail inbox 使用 fake provider；notification 使用 `jsonl` sink 和 `/internal/notifications/flush`。
- 排除项：OAuth/Gmail callback/redirect/client secrets、真实 SMTP。

## 环境快照
- 数据库：`postgres` 已启动并执行 `alembic upgrade head`。
- Redis：额外启动宿主机 `6379` 的 `redis:7-alpine` 容器，供本地服务访问。
- 服务：`input(8001)`、`review(8000)`、`ingest(8002)`、`notification(8004)`、`llm(8005)` 均返回 `/health = 200`。
- 运行模式：
  - `ENABLE_NOTIFICATIONS=true`
  - `NOTIFY_SINK_MODE=jsonl`
  - `NOTIFICATION_SERVICE_ENABLE_WORKER=false`
  - `INGEST_SERVICE_ENABLE_WORKER=true`
  - `REVIEW_SERVICE_ENABLE_APPLY_WORKER=true`
  - `LLM_SERVICE_ENABLE_WORKER=true`
  - `GMAIL_API_BASE_URL=http://127.0.0.1:8765/gmail/v1/users/me`

## 执行命令
- 离线守卫：
  - `pytest -q tests/test_notify_jsonl_sink.py tests/test_notify_flush_api.py tests/test_fake_source_provider_semester_contract.py tests/test_semester_demo_scenarios.py tests/test_semester_demo_report_schema.py tests/test_internal_service_auth.py tests/test_digest_scheduler_idempotency.py tests/test_email_notifications.py tests/test_fake_source_provider_contract.py tests/test_real_source_smoke_report_schema.py`
- 主联调：
  - `python scripts/smoke_semester_demo.py --input-api-base http://127.0.0.1:8001 --review-api-base http://127.0.0.1:8000 --ingest-api-base http://127.0.0.1:8002 --notify-api-base http://127.0.0.1:8004 --llm-api-base http://127.0.0.1:8005 --api-key "$APP_API_KEY" --ops-token "$INTERNAL_SERVICE_TOKEN_OPS" --notification-jsonl data/smoke/notify_sink.jsonl --report data/synthetic/semester_demo/qa/semester_demo_report.json`
- 在线包装：
  - `RUN_SEMESTER_DEMO_SMOKE=true pytest -q tests/test_semester_demo_online.py`
- 质量门禁：
  - `mypy .`
  - `flake8 .`
  - `python -m build`

## 结果汇总
- 离线守卫：通过，`20 passed`。
- 质量门禁：通过，`mypy . / flake8 . / python -m build` 全通过。
- 主联调：失败。
- 在线 pytest 包装：失败。
- 最终结论：`未通过`。

## 关键验收项结果
- 服务健康检查：通过。
- fake Gmail inbox 协议：离线测试通过，运行期也确认 ingest 有访问 fake provider。
- suffix 断言：未进入运行时验证阶段，未实际执行。
- notification flush：未进入执行阶段，`jsonl` 无发送记录。
- LLM 真实调用：未真正发生成功调用。

## 关键证据
- 主联调报告：`data/synthetic/semester_demo/qa/semester_demo_report.json`
- 本轮主联调最终失败点：
  - `fatal_errors = ["sync request timed out request_id=3ec2b84f22804036b519e57a5f01c3aa"]`
  - 失败发生在：`semester=1 / batch=1 / source=ics`
- 数据库证据：
  - `sync_requests` 中存在 4 条 pending/running 请求。
  - `ingest_jobs` 中最新 ICS/Gmail 请求停留在：`status=CLAIMED` 且 `workflow_stage=LLM_ENQUEUE_PENDING`。
- 指标证据：
  - input metrics：`sync_requests_pending=4`
  - ingest metrics：`ingest_jobs_pending=4`，`ingest_jobs_dead_letter=2`
  - llm metrics：`queue_depth_stream=0`，`queue_depth_retry=0`，`llm_calls_total_1m=0`
  - notify status：`notification_pending=0`，`notification_sent=0`，`digest_sent=0`
- 日志证据：
  - ingest 日志中确实访问了 fake provider：`ingest_fake_gmail_calls=23`
  - 但后续没有形成 LLM 处理和通知发送。
  - `notify_sink.jsonl` 行数：`0`

## Edge Case 覆盖分析
- 已覆盖（离线/契约级）：
  - suffix 缺失
  - suffix 错配
  - suffix 精确匹配
  - fake inbox 的 `thread_id / from_header / label_ids / internalDate`
  - flush 空状态与 JSONL 上下文写入
- 未覆盖（运行期未走到）：
  - suffix 三类在真实联调中的命中
  - mixed review decision 后的 notify flush 行为
  - notification JSONL 增长
  - LLM 输出稳定性/格式重试/延迟分布
- 结论：当前不是“规模不足”，而是“在 batch 1 前就被流水线阻断”。现阶段不建议扩规模，先修阻断点。

## LLM 表现分析
- 本轮测试要求真实 LLM，但运行结果显示：
  - `llm-service /internal/metrics` 中 `llm_calls_total_1m = 0`
  - 说明请求没有真正进入 LLM 调用阶段。
- 因此当前无法评估：
  - LLM 时延
  - 格式重试
  - 输出稳定性
  - rate limit / timeout 的业务影响

## 问题与根因
### 阻断问题 1：LLM 队列未收到任务
- 现象：`ingest_jobs` 停在 `CLAIMED + LLM_ENQUEUE_PENDING`。
- 同时 `llm-service` 指标显示队列深度为 0，且没有 LLM 调用发生。
- 推断：connector 已抓到 fake ICS/Gmail 内容，但 parse task 没有成功进入 LLM stream queue，导致 `sync_request` 一直不落到 `SUCCEEDED+applied`。
- 影响：主联调在 `semester 1 / batch 1` 即超时，后续 review/notify 全部无法验证。

### 阻断问题 2：在线 pytest 包装和 live 服务的 API key 不一致
- `tests/test_semester_demo_online.py` 失败信息：`GET /onboarding/status failed status=401 body={"detail":"Invalid API key"}`。
- 推断：pytest 运行时环境中的 `APP_API_KEY` 与已启动 live 服务读取的 `.env` 中 key 不一致。
- 影响：在线 smoke 包装当前不能直接作为 live 服务验证入口。

## 风险与后续建议
- 先修复 `LLM_ENQUEUE_PENDING` 到 parse queue 的投递链路，再重跑当前规模。
- 修复后不要立即扩规模，先在 `3x10x10` 基线上确认：
  - `llm_calls_total_1m > 0`
  - `suffix_assertions` 全通过
  - `notification_sink.rows_delta > 0`
- 统一 `APP_API_KEY` 的来源，保证 `tests/test_semester_demo_online.py` 和 live 服务使用同一值。
- 在下一轮测试中额外记录：
  - LLM 每批调用数
  - flush 每批 sent_count
  - 每学期 edge-case 实际命中次数

## 最终结论
- 结论：`未通过`
- 原因：系统已完成 fake inbox 拉取，但在 `LLM_ENQUEUE_PENDING -> LLM queue` 这一步阻断，导致真实 LLM、review、notification 无法完成闭环验证。
