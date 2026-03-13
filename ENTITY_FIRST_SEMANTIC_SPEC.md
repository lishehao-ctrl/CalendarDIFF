# Entity-First Semantic Spec

## 1. 目的

这份文档定义 CalendarDIFF 当前与未来清理工作的第一性原理目标。

它只回答三件事：

1. 系统的主数据模型到底应该是什么。
2. 哪些旧表达已经不再允许继续出现在 repo 里。
3. 另一个 agent 在做清理时，什么算完成，什么不算。

这份文档是根级别的单一真相来源。若与旧文档、旧测试、旧命名冲突，以本文件为准。

## 2. 第一性原理

### 2.1 稳定身份

- 系统内部唯一稳定身份是 `entity_uid`。
- `entity_uid` 不从 `course + family + ordinal` 推导。
- `entity_uid` 不因为 family 合并、rename、ordinal 重排而变化。

### 2.2 canonical 只来自 semantic

- `event_entities` 是唯一 canonical aggregate root。
- 已批准的用户可见事件状态，只能落在 `event_entities`。
- 任何 review approve、manual canonical edit、notification display，都必须围绕 `event_entities` 的 approved semantic state。

### 2.3 source 只提供事实与证据

- `input_sources` 表示外部连接器和同步入口。
- `source_event_observations` 表示原始观测事实。
- source 不再承担 canonical identity。
- source-specific id 只用于追踪、审计、回放、evidence 锚点。

### 2.4 review 的本质是 semantic proposal

- `changes` 是 semantic proposal queue 和 audit log。
- `changes` 的主语义是：
  - 某个 `user_id`
  - 某个 `entity_uid`
  - 某次 semantic delta
- `changes` 不是旧 canonical `Input/Event` 的差异快照兼容层。

### 2.5 用户展示是 projection，不是 identity

- 用户主展示统一使用 `course + family + ordinal`。
- 这是 display projection，不是内部主键。
- 任意 UI、通知、摘要、review 列表，都应该优先消费 display projection，而不是暴露 source-specific 结构。

### 2.6 frozen evidence 必须自包含

- review evidence 必须冻结在 `changes` 上。
- evidence preview 不能依赖文件系统路径。
- evidence preview 不能依赖当前 observation 是否还存在。
- evidence preview 不能依赖 source secret、cursor、snapshot 表。

## 3. 活跃模型

## 3.1 保留为一等模型的表

- `users`
- `user_sessions`
- `input_sources`
- `input_source_configs`
- `input_source_secrets`
- `input_source_cursors`
- `sync_requests`
- `ingest_jobs`
- `ingest_results`
- `source_event_observations`
- `event_entities`
- `event_entity_links`
- `event_link_candidates`
- `event_link_blocks`
- `event_link_alerts`
- `changes`
- `course_work_item_label_families`
- `course_work_item_raw_types`
- `course_raw_type_suggestions`
- `notifications`
- `digest_send_log`
- integration outbox/inbox 相关表

## 3.2 已移除的 canonical 层

这些结构不再是活跃 runtime model，不应继续被实现或叙述为现行架构：

- `inputs`
- `events`
- `snapshots`
- `snapshot_events`

如果 repo 中仍然出现它们，应该被视为待清理对象，除非该处明确是在描述历史迁移背景。

## 4. `event_entities` 规范

`event_entities` 是唯一 approved canonical state。

它至少应显式承载这些 approved semantic 字段：

- `entity_uid`
- `user_id`
- `semantic_identity_key`
- `lifecycle`
- `course_dept`
- `course_number`
- `course_suffix`
- `course_quarter`
- `course_year2`
- `family_id`
- `family_name`
- `raw_type`
- `event_name`
- `ordinal`
- `due_date`
- `due_time`
- `time_precision`

### 4.1 lifecycle

`lifecycle` 只有两种状态：

- `active`
- `removed`

规则：

- approve remove 不删除 row，而是标记 `removed`
- 后续重新识别到同一 `entity_uid` 时，重新激活该 row

## 5. `changes` 规范

`changes` 是 review queue，也是 audit log。

它至少应承载：

- `user_id`
- `entity_uid`
- `change_type`
- `change_origin`
- `detected_at`
- `before_semantic_json`
- `after_semantic_json`
- `delta_seconds`
- `review_status`
- `primary_source_ref_json`
- `proposal_sources_json`
- `before_evidence_json`
- `after_evidence_json`
- review metadata

### 5.1 允许的 change_type

- `created`
- `due_changed`
- `removed`

### 5.2 允许的 change_origin

- `ingest_proposal`
- `manual_canonical_edit`

### 5.3 行为规则

- `approve`:
  - 将 `after_semantic_json` 应用到 `event_entities`
  - `removed` 类型改写 `event_entities.lifecycle = removed`
- `reject`:
  - 不改 approved entity state
- `proposal edit`:
  - 只改 pending `changes.after_semantic_json`
- `canonical edit`:
  - 直接改 `event_entities`
  - 同时写一条 `changes` 审计记录

## 6. 数据流规范

主链路必须是：

`input_sources -> source_event_observations -> semantic proposal rebuild -> changes -> approve into event_entities -> notifications`

### 6.1 ingest

- ingest 仍然负责写 observation 和 link 相关表
- ingest/rebuild 比较的是：
  - observation-derived semantic candidate
  - approved `event_entities` state

### 6.2 proposal rebuild 规则

- 没有 approved entity + 有有效 candidate => `created`
- 有 approved active entity + 没有有效 candidate => `removed`
- 有 approved entity + candidate materially changed => `due_changed`
- 有 approved entity + candidate equivalent => no-op / 关闭 pending proposal

### 6.3 notifications

- enqueue 由 `user_id + change_ids` 驱动
- `review.pending.created` payload 必须使用：
  - `user_id`
  - `change_ids`
  - `deliver_after`
- notification 内容从 semantic payload 和 display projection 派生

## 7. API 与前端规范

### 7.1 稳定路由族

这次清理不要求改动主 route family：

- `/sources`
- `/sync-requests`
- `/review/*`
- `/users/*`

### 7.2 review DTO 原则

- `ReviewChange` 应以 semantic payload 为核心
- 保留：
  - `before_event`
  - `after_event`
  - `proposal_sources`
  - `primary_source`
- 不允许再依赖模糊的旧 fallback 语义，例如把旧 canonical id 假装成 source id

### 7.3 primary source

`primary_source` 是新的单一 source 指针，应显式包含：

- `source_id`
- `source_kind`
- `provider`
- `external_event_id`

## 8. 允许与禁止的表达

## 8.1 应优先使用的表达

- `entity_uid`
- `event_entities`
- `approved semantic state`
- `before_semantic_json`
- `after_semantic_json`
- `primary_source`
- `primary_source_ref_json`
- `proposal_sources`
- `frozen evidence`
- `review_label`
- `user_id`

## 8.2 需要清理的旧表达

这些词如果出现在 runtime、测试、文档、OpenAPI 快照中，默认应被清掉：

- `proposal_entity_uid`
- `before_json`
- `after_json`
- `Change.input_id`
- `canonical_input_id`
- `input_label`
- `materialize_change_snapshot`
- `save_ics(` 这类依赖旧文件证据写法的主流程调用
- `canonical input bootstrap`
- `user/canonical input loading`
- 将 `inputs/events/snapshots/snapshot_events` 描述成活跃主模型
- 从 `app.db.models.review` 导入旧 `Input` / `InputType` / `Event` / `Snapshot`

## 8.3 允许保留的合法词

下面这些词虽然长得像旧表达，但仍然是合法的：

- `input_sources`
- `input-service`
- `sync input source` 这类字面描述外部连接器的文本
- 通用英语里的 `event`，只要不是在描述旧 `events` 表
- ICS delta/parser 领域里的 `snapshot`，只要不是旧 `snapshots` 表
- `X-Event-Id` 这类外部协议/header
- link alert/candidate 上的 `evidence_snapshot_json`，如果它是当前活跃 schema 的正式字段

## 9. 清理优先级

另一个 agent 做 repo 清理时，优先级按这个顺序：

1. runtime code
2. backend tests
3. frontend types / DTO 消费
4. OpenAPI snapshots
5. docs
6. scripts / tooling / guard

原则：

- 先清运行时语义，再清外围叙述
- 先删兼容别名，再修调用点
- 不为了“兼容旧命名”继续保留中间层

## 10. 非目标

这份 spec 不要求：

- 保留旧数据库内容
- 为旧 canonical 层做 backfill
- 为 repo 外部消费者维持旧 DTO 兼容
- 因为历史测试存在而继续维护旧模型

## 11. 完成定义

一次清理工作完成，至少要满足：

1. runtime code 不再依赖已移除 canonical 层
2. review / notify / ingest 的主语义只围绕 `entity_uid + semantic`
3. 核心测试不再 seed/assert `Input/Event/Snapshot`
4. OpenAPI 快照不再暴露旧 semantic alias
5. docs 不再把旧 canonical 表讲成现行架构
6. repo guard 可以阻止旧词重新回流

## 12. 验证命令

建议至少执行：

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_review_items_summary_api.py \
  tests/test_core_ingest_pending_proposal_rebuild.py \
  tests/test_review_change_evidence_preview_api.py \
  tests/test_review_changes_batch_api.py \
  tests/test_review_edits_api.py \
  tests/test_review_change_source_summary_api.py \
  tests/test_review_label_learning_api.py \
  tests/test_core_ingest_pending_outbox_contract.py \
  tests/test_notify_jsonl_sink.py \
  tests/test_openapi_contract_snapshots.py \
  tests/test_no_legacy_semantic_cleanup_strings.py
```

如有改动 OpenAPI：

```bash
PYTHONPATH=. python scripts/update_openapi_snapshots.py
```

如有改动 Python runtime：

```bash
python -m compileall app services
```

如有改动前端类型或 review DTO 消费：

```bash
cd frontend
npm run typecheck
npm run lint
NEXT_DIST_DIR=.next-prod npm run build
```

## 13. 对另一个 agent 的工作预期

另一个 agent 如果基于本 spec 接手清理，应该：

1. 先读本文件，再扫 repo
2. 只保留 entity-first semantic 语言
3. 不把兼容层继续包装成“临时合理”
4. 做完后明确报告：
   - 改了什么
   - 删了什么
   - 验证了什么
   - 还剩什么风险或待清项
