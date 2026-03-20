# CalendarDIFF Frontend Product Spec

## Summary

这份 spec 定义当前 CalendarDIFF 前端应该围绕什么心智来组织，以及每个页面的职责、交互边界和未来对接的后端接口。

产品不是“课程消息收件箱”，也不是“邮箱分类器”。它的主任务是：

1. 帮学生建立可信的 deadline truth
2. 告诉学生现在最该处理的是哪里
3. 把日常工作量集中在 `Changes`
4. 把命名治理放在 `Families`
5. 把缺口修补留给 `Manual`
6. 把接入健康、成本和 runtime 风险放在 `Sources`

当前前端信息架构固定为：

- `Overview`
- `Sources`
- `Changes`
- `Families`
- `Manual`
- `Settings`

其中：

- `Changes` 是主工作台
- `Families` 是治理台，不是主 inbox
- `Manual` 是 fallback，不是常用主入口
- `Sources` 是连接与运行状态中心
- `Overview` 是注意力路由页

## Product Mental Model

### 用户主心智

用户每天不会先想“我要去哪个技术模块”，而是只会想这几件事：

1. 今天有没有新的 deadline truth 需要我确认
2. 我的连接是不是还健康，系统是不是还在跑
3. 某些课的命名是不是越来越乱，需要整理
4. 系统漏了东西时，我怎么手动补一条

所以导航和页面职责必须服务这 4 个问题，而不是服务内部实现。

### 入口优先级

默认登录后的第一入口应是 `Overview`，不是 `Sources`。

原因：

- 新用户先要知道“现在要我做什么”
- 老用户也先要看“今天有没有 pending changes / source risk / naming drift”
- `Overview` 负责把注意力分发到其他 lane

### Lane 定位

- `Sources`: “我的连接和系统现在是否可信”
- `Changes`: “我现在要审批什么语义变化”
- `Families`: “我现在要整理什么命名/分类治理”
- `Manual`: “系统无法安全表达时，我手动修补 canonical state”
- `Settings`: “账户和时区”

## App Shell

### 全局导航

左侧主导航固定为：

- `Overview`
- `Sources`
- `Changes`
- `Families`
- `Manual`
- `Settings`

顶部全局区域固定为：

- 当前用户
- 当前时区
- 轻量系统状态

不要在一级导航中放技术词：

- 不要出现 `sync requests`
- 不要出现 `raw type suggestions`
- 不要出现 `ingest/apply/runtime kernel`

这些只允许出现在二级信息或开发者调试层。

### 全局设计原则

- 所有列表页面都必须有 `loading / empty / error`
- 所有危险动作都必须可逆或至少解释影响
- 所有页面都要有“这页是干什么的”一句话说明
- 所有页面都要能回答“下一步我该做什么”

## Page Specs

### 1. Overview

#### 角色

`Overview` 是注意力路由页，不是完整工作台。

它只做三件事：

1. 汇总今天最需要处理的工作
2. 告诉用户系统当前是否可信
3. 把用户路由到正确 lane

#### 页面内容

页面分成 4 个卡区：

- `Needs Review`
  - pending changes count
  - 最高优先 change 的一句摘要
  - CTA: `Open Changes`
- `Source Posture`
  - source 总数
  - 有无 active sync
  - 有无 failed / stale source
  - CTA: `Open Sources`
- `Naming Drift`
  - raw type suggestion count
  - family rebuild/status 风险
  - CTA: `Open Families`
- `Fallbacks`
  - manual event count
  - CTA: `Open Manual`

#### Backend Source Of Truth

`Overview` 不应再由前端同时 fan-out `changes + sources + families + manual` 后自己推断“现在该去哪条 lane”。

当前单一 truth 是：

- `GET /changes/summary`

当前 response 语义固定包含：

- `changes_pending`
- `recommended_lane`
  - `sources | changes | families | null`
- `recommended_lane_reason_code`
  - `runtime_attention_required`
  - `changes_pending`
  - `family_governance_pending`
  - `all_clear`
- `recommended_action_reason`
- `sources`
  - `active_count`
  - `running_count`
  - `queued_count`
  - `attention_count`
  - `blocking_count`
  - `recommended_action`
  - `severity`
  - `reason_code`
  - `message`
  - `related_request_id`
  - `progress_age_seconds`
- `families`
  - `attention_count`
  - `pending_raw_type_suggestions`
  - `mappings_state`
  - `last_rebuilt_at`
  - `last_error`
- `manual`
  - `active_event_count`
  - `lane_role`
- `generated_at`

前端约束：

- `Overview` 的主 CTA、hero 文案、badge 优先级，都必须优先消费 `recommended_lane + recommended_action_reason`
- 不允许前端自己重新实现 lane 推荐排序
- `sources` 卡区可以在 detail drill-down 时再 fan-out `/sources` 或 `/sources/{id}/observability`
- `families` 与 `manual` 卡区的轻量摘要，默认只读 `/changes/summary`

#### 当前可接 API

- `GET /changes/summary`
- `GET /sources`
- `GET /onboarding/status`
- 可选 fan-out:
  - `GET /sources/{source_id}/observability`
  - `GET /families/raw-type-suggestions?status=pending&limit=5`
  - `GET /manual/events`

#### 推荐未来接口

当前 `GET /changes/summary` 已经是 `Overview` 的聚合接口，不再推荐 UI 做 client-side lane aggregation。

未来如果要新增 `GET /overview`，它也只能是 `GET /changes/summary` 的语义扩展，而不是另一套推荐逻辑。

### 2. Sources

#### 角色

`Sources` 是连接与运行状态中心。

用户来到这里，是为了回答：

1. 哪些 source 已连接
2. 哪些 source 还没连接好
3. 哪些 source 正在跑
4. 哪些 source 卡住或失败了
5. bootstrap 和 replay 的成本/耗时是什么

#### 页面结构

建议用两层：

- Source list
- Source detail panel / source detail route

#### Source List

每个 source 卡片至少展示：

- provider
- display name
- connection state
- runtime state
- active guidance
- latest sync progress
- latest error if any

列表页 CTA：

- `Connect source`
- `Run sync`
- `Reconnect Gmail`
- `Open details`

#### Source Detail

每个 source detail 分 4 个区：

- `Connection`
  - provider
  - account email
  - config
  - active / archived
- `Current Posture`
  - operator guidance
  - active request
  - current stage / substage / progress
- `Bootstrap`
  - bootstrap request status
  - elapsed
  - llm usage summary
- `Replay History`
  - latest replay
  - recent sync history
  - per-request token/cache/latency facts

#### 当前可接 API

- `GET /sources`
- `POST /sources`
- `PATCH /sources/{source_id}`
- `POST /sources/{source_id}/oauth-sessions`
- `POST /sources/{source_id}/sync-requests`
- `GET /sources/{source_id}/observability`
- `GET /sources/{source_id}/sync-history`
- `GET /sync-requests/{request_id}`

#### 推荐未来接口

当前 `Sources` 可以接，但 detail 需要 client-side fan-out。

未来推荐增加：

- `GET /sources/{source_id}`
  - source base info + latest observability in one payload
- `GET /sources/overview`
  - all sources summary optimized for list page

### 3. Changes

#### 角色

`Changes` 是主工作台。

用户日常最常用的页面应该是这里。

#### 页面结构

建议采用双栏或三段式：

- 左侧: queue / filters
- 中间: selected change detail
- 右侧或下方: evidence / edit / learning

#### 列表区

必须支持：

- `pending / approved / rejected / all`
- source filter
- priority cues
- viewed state

列表项至少展示：

- before -> after 的变化感知
- change type
- course + event label
- primary source
- detected_at
- review status

#### 详情区

详情区必须清楚回答：

1. 这个 change 在说什么
2. 为什么系统认为它应该被审
3. approve 后 canonical state 会变成什么

应展示：

- before_display / after_display
- before_event / after_event
- primary_source
- proposal_sources
- change_summary
- viewed / reviewed metadata

#### 动作区

动作按优先级：

- `Approve`
- `Reject`
- `Edit then approve`
- `Mark viewed`
- `Learn label`

Evidence 区必须可切 `before / after`。

#### 当前可接 API

- `GET /changes/summary`
- `GET /changes`
- `GET /changes/{change_id}`
- `PATCH /changes/{change_id}/views`
- `POST /changes/{change_id}/decisions`
- `POST /changes/batch/decisions`
- `GET /changes/{change_id}/edit-context`
- `GET /changes/{change_id}/evidence/{side}/preview`
- `POST /changes/edits/preview`
- `POST /changes/edits`
- `POST /changes/{change_id}/label-learning/preview`
- `POST /changes/{change_id}/label-learning`

#### 推荐未来接口

当前足够支撑 v1 工作台。

未来推荐增加：

- cursor-based pagination
- explicit queue sort options
- `GET /changes/next-action`
  - 返回最值得先处理的 change

### 4. Families

#### 角色

`Families` 是治理台，不是 inbox。

它服务的是“命名真相”和“raw type 归属真相”。

#### 页面结构

建议分 3 个子区：

- `Families`
- `Raw Types`
- `Suggestions`

同时要有 course scope 切换。

#### Families 子区

用于：

- 查看 family 列表
- 新建 family
- rename / update family

列表字段：

- course_display
- canonical_label
- raw_types
- updated_at

#### Raw Types 子区

用于：

- 查看某课的 raw type
- relink 到另一个 family

#### Suggestions 子区

用于：

- 审 raw type suggestion
- approve / reject / dismiss

#### 当前可接 API

- `GET /families`
- `POST /families`
- `PATCH /families/{family_id}`
- `GET /families/status`
- `GET /families/courses`
- `GET /families/raw-types`
- `POST /families/raw-types/relink`
- `GET /families/raw-type-suggestions`
- `POST /families/raw-type-suggestions/{suggestion_id}/decisions`

#### 推荐未来接口

当前能做治理台，但不够优雅。

未来推荐增加：

- `GET /families/{family_id}`
- `GET /families/{family_id}/raw-types`
- `GET /families/overview`
  - 返回按课程分组的 family + raw type + suggestion 汇总

### 5. Manual

#### 角色

`Manual` 是 fallback lane。

用户只在这几种情况下进入：

- 系统漏掉了事件
- 系统无法安全表达
- 用户要直接修 canonical state

#### 页面结构

建议为：

- manual event list
- create / edit dialog
- delete confirmation

#### 页面内容

列表字段：

- course_display
- family_name
- event_name
- due_date / due_time
- lifecycle
- manual_support

#### 当前可接 API

- `GET /manual/events`
- `POST /manual/events`
- `PATCH /manual/events/{entity_uid}`
- `DELETE /manual/events/{entity_uid}`

#### 推荐未来接口

当前足够做 v1。

未来推荐增加：

- manual preview endpoint
- family search endpoint optimized for manual create form

### 6. Settings

#### 角色

`Settings` 只负责账户和时区，不混 source 与 onboarding。

#### 页面内容

- notify email
- email
- timezone
- timezone source
- calendar delay seconds

#### 当前可接 API

- `GET /settings/profile`
- `PATCH /settings/profile`

### 7. Onboarding

#### 角色

`Onboarding` 是独立流程，不应和主 app 混成一个 lane。

它回答的是：

- 用户是否注册完成
- Canvas ICS 是否已连接
- Gmail 是否已连接或跳过
- term binding 是否已完成

#### 页面状态

依据 `stage`：

- `needs_user`
- `needs_canvas_ics`
- `needs_gmail_or_skip`
- `needs_term_binding`
- `needs_term_renewal`
- `ready`

#### 当前可接 API

- `GET /onboarding/status`
- `POST /onboarding/registrations`
- `POST /onboarding/canvas-ics`
- `POST /onboarding/gmail/oauth-sessions`
- `POST /onboarding/gmail-skip`
- `POST /onboarding/term-binding`

## Cross-Page View Models

前端不要直接把 backend schema 原样铺到组件里。

建议先做 adapter 层：

- `OverviewCardVM`
- `SourceListItemVM`
- `SourceDetailVM`
- `ChangeListItemVM`
- `ChangeDetailVM`
- `FamilyListItemVM`
- `RawTypeItemVM`
- `RawTypeSuggestionVM`
- `ManualEventVM`
- `SettingsProfileVM`

原因：

- backend contract 会继续收口，但页面心智应稳定
- `Overview` 的 lane routing 不应散落在组件里
- `Sources` observability 和 `Changes` workbench 需要不同密度的 view model

## UI Agent Rules

UI agent 在实现时必须遵守这些约束：

- 不要在前端重新计算 `recommended_lane`
- 不要把 `Families` 当成主 inbox
- 不要把 `Manual` 做成默认入口
- 不要让 `Sources` detail 替代 `Overview` 的主决策入口
- 若 backend contract 缺字段，应回提后端补 contract，不要先在前端拼临时推断

## Handoff Note

当前后端最适合 UI agent 先接的页面优先级：

1. `Overview`
2. `Sources`
3. `Changes`
4. `Families`
5. `Manual`
6. `Settings`

其中：

- `Overview` 已有聚合 contract，可先做真实接线
- `Sources` 已有 observability 与 sync-history，可先做 detail
- `Changes` 已可做主工作台
- `Families` 与 `Manual` 先做标准 CRUD/治理台，不要再发明新 lane 心智

- 当前后端 response 已经够用，但仍偏 backend-native
- UI 需要更稳定的展示字段、CTA 状态和 empty state 文案
- adapter 层能把未来 API 聚合优化与 UI 解耦

## Recommended Frontend Routes

建议前端 route 结构：

- `/`
  - `Overview`
- `/sources`
- `/sources/[sourceId]`
- `/changes`
- `/changes/[changeId]`
- `/families`
- `/manual`
- `/settings`
- `/onboarding`
- `/login`

`Changes` 和 `Sources` 可先用 list + side panel，不强制独立 detail route；但 route 结构建议提前留好。

## API Integration Matrix

### 可直接接线

- `Onboarding`
- `Sources`
- `Changes`
- `Families`
- `Manual`
- `Settings`

### 需要前端聚合的地方

- `Overview`
- `Sources` list posture summary
- `Families` 的 course-grouped governance view

### 推荐未来补的聚合接口

- `GET /overview`
- `GET /sources/overview`
- `GET /sources/{source_id}`
- `GET /families/{family_id}`
- `GET /families/overview`

## Acceptance For UI Agent

UI 实现如果符合这份 spec，应满足：

1. 用户能在 5 秒内知道自己今天最该去哪一页
2. `Changes` 一眼看出“系统建议我做什么决策”
3. `Sources` 一眼看出“source 是否健康、是否在跑、是否值得信任”
4. `Families` 明显是治理页，而不是 review inbox
5. `Manual` 明显是 fallback，不喧宾夺主
6. 所有页面的 CTA 都能映射到现有 public API

## Assumptions

- 本 spec 以当前后端 public contract 为准
- 当前不要求前端直接暴露开发者级日志
- `Overview` 的最优解需要未来聚合接口，但 v1 可先做 client-side aggregation
- 这份 spec 定义页面职责与对接面，不定义具体视觉风格
