# Observed Label / Canonical Family Productization Spec

## Summary

当前 `Families` 功能在工程上已经稳定，但产品心智还停留在内部术语层：

- `raw type`
- `family`
- `relink`

这导致用户需要先理解内部模型，才能理解自己在做什么。

这轮后端重构的目标不是改 semantic core，而是把现有稳定能力投影成更直观的产品 contract：

1. 系统原始看到了什么词
2. 这个词现在被归到哪个稳定类别
3. 改这个映射会影响哪里

后端要做的是：

- 保持当前稳定语义不变
- 提供面向产品的 additive DTO / preview / impact 数据
- 允许前端彻底停止以 `raw_type_id / family_id` 这类内部维护视角组织主交互

## Product Decisions

### 1. 对外产品语言改成 `Observed label / Canonical family`

内部模型仍然可以保留：

- `raw_type`
- `family_id`

但新的 public product-facing projection 应该优先暴露：

- `observed_label`
- `canonical_family_label`

规则：

- 这是 projection rename，不是 semantic model rename
- 不要求本轮删除 DB/ORM 内部命名
- 但新增 public DTO 不再把 `raw_type` 作为唯一主字段

### 2. `Families` 的关键问题是“影响范围”，不是“字段编辑”

用户真正需要知道的是：

- 这个原始标签当前影响多少事件
- 当前影响多少 pending changes
- 改掉后会波及哪些 UI / canonical surface

因此后端必须提供影响范围统计，而不是只给列表和 ids。

### 3. relink 必须有 preview

用户不能在不知道影响的情况下直接把：

- `write-up`
- 从 `Problem Set`
- 改到 `Project`

后端需要提供一个 preview contract，明确告诉前端：

- 当前归类
- 目标归类
- 会影响哪些 event / change / future ingest

## Invariants

- `event_entities` 仍是唯一 canonical approved state
- `course_work_item_raw_types` 仍是治理层，不变成 canonical identity
- `course_work_item_label_families` 仍是 canonical label governance，不变成 parser truth
- 任何新字段都只是 projection / explanation，不改变 apply 语义
- 不允许把 `course + family + ordinal` 重新当作稳定 identity

## Scope

## Phase 1. Additive product projection

新增或扩展 DTO，使前端能停止直接暴露内部术语。

### A. `GET /families`

现有 `CourseWorkItemFamilyResponse` 扩展：

- `canonical_family_label`
  - same as canonical label, but product-facing naming
- `observed_label_count`
- `active_event_count`
- `pending_change_count`

兼容策略：

- 继续保留 `canonical_label`
- 新字段为 additive

### B. `GET /families/raw-types`

现有 `CourseRawTypeResponse` 扩展：

- `observed_label`
  - alias of current `raw_type`
- `canonical_family_label`
- `active_event_count`
- `pending_change_count`
- `future_ingest_effect`
  - string enum:
    - `same_label_will_follow_target_family`

兼容策略：

- 保留 `raw_type`
- 新 projection 字段 additive

### C. `GET /changes`

现有 `ChangeItemResponse` 扩展：

- `observed_label`
- `canonical_family_label`
- `mapping_explanation_code`
- `mapping_explanation_params`

示例 code：

- `changes.mapping.current_family_from_observed_label`

参数至少包含：

- `observed_label`
- `canonical_family_label`

目的：

- 让前端在 `Changes` detail 里解释：
  - “这条 change 之所以长这样，是因为当前原始标签被归到了某个稳定类别。”

## Phase 2. Relink preview endpoint

新增 endpoint：

- `POST /families/raw-types/relink-preview`

请求：

- `raw_type_id`
- `family_id`

返回建议：

- `raw_type_id`
- `observed_label`
- `current_family_id`
- `current_family_label`
- `target_family_id`
- `target_family_label`
- `impact_counts`
  - `active_event_count`
  - `pending_change_count`
  - `manual_event_count`
- `affected_event_samples`
  - up to 5
- `affected_change_samples`
  - up to 5
- `before_after_examples`
  - array of:
    - `before_display_label`
    - `after_display_label`
    - `reason_code`

### Preview semantics

preview 只读，不写任何状态。

它回答：

- 当前 `observed_label -> current family`
- 改后 `observed_label -> target family`
- 会影响哪些现有投影

## Phase 3. Product-oriented raw-type move response

现有：

- `POST /families/raw-types/relink`

扩展 response：

- `observed_label`
- `previous_family_label`
- `current_family_label`
- `impact_counts`
  - optional but recommended

这样前端成功提示就能从：

- `Moved write-up into its new family.`

升级成：

- `write-up 现在归到 Project。影响 4 个事件，2 条 pending changes。`

## Phase 4. Family detail aggregates

为了让 `Families` detail panel 不必自己拼数据，扩 `GET /families` 或新增 detail endpoint：

- `GET /families/{family_id}`

返回：

- `canonical_family_label`
- `observed_labels`
- `active_event_count`
- `pending_change_count`
- `recent_changed_items`
- `affected_manual_event_count`

如果本轮不想加 detail endpoint，可以先把大部分信息塞进 list payload，但长期更建议单独 detail。

## Data derivation rules

### `observed_label_count`

来源：

- `course_work_item_raw_types`
  - count by `family_id`

### `active_event_count`

来源：

- `event_entities`
  - `lifecycle=active`
  - family match

### `pending_change_count`

来源：

- `changes`
  - `review_status=pending`
  - match current projected family

### `mapping_explanation`

规则：

- 当 `observed_label` 和 `canonical_family_label` 都存在时，总是返回
- 不依赖前端硬猜

### `before_after_examples`

规则：

- preview 时只需要示例，不要求全量 materialize
- 采样应稳定、确定性
- 样本顺序优先：
  - pending changes
  - recent active manual events
  - recent active canonical events

## Likely backend files

- [schemas.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/families/schemas.py)
- [router.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/families/router.py)
- [family_service.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/families/family_service.py)
- [raw_type_service.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/families/raw_type_service.py)
- [application_service.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/families/application_service.py)
- [change_listing_service.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/changes/change_listing_service.py)
- [schemas.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/changes/schemas.py)

## Out of scope

- 不改 DB 表名
- 不改内部 ORM 命名
- 不改 parser / apply semantic logic
- 不在本轮删除旧字段
- 不在本轮做 frontend 结构实现

## Acceptance Criteria

### API

- `GET /families` 返回 family impact counts
- `GET /families/raw-types` 返回 observed label + target family projection
- `POST /families/raw-types/relink-preview` 可用
- `POST /families/raw-types/relink` 返回 product-facing labels
- `GET /changes` 返回 observed label + canonical family projection

### Semantics

- 所有新增字段只读，不改 canonical state
- preview endpoint 不产生副作用
- impact counts 与当前数据库真相一致

### Tests

- families list / raw-types response contract tests
- relink preview tests
- relink apply response tests
- changes listing includes mapping projection tests
- OpenAPI snapshot update

## Validation

优先跑：

- `python -m py_compile ...`
- families / changes 相关 targeted pytest
- `python scripts/update_openapi_snapshots.py`

建议目标测试：

- `tests/test_review_changes_unified.py`
- `tests/test_review_change_source_summary_api.py`
- `tests/test_openapi_contract_snapshots.py`
- 新增 families preview / impact tests
