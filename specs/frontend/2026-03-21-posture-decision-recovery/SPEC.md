# CalendarDIFF Workspace Posture + Decision Support + Source Recovery Spec

## Summary

当前 MVP 已经具备基本产品主线：

1. 接入 `Gmail / ICS`
2. 建立 baseline
3. 做 `Initial Review`
4. 进入日常 `Replay Review`

但从第一次上手用户的心智看，还差最后一层“产品闭环”。

当前主要缺口不是缺功能，而是缺 3 组明确的产品真相：

- `workspace_posture`
- `change_decision_support`
- `source_recovery`

如果没有这 3 组真相，前端只能继续用零散字段拼心智：

- 用户不知道自己是否已经完成首轮导入审阅
- 用户在 `Changes` 中看到 proposal，但不知道为什么现在轮到自己处理
- 用户在 `Sources` 看到 runtime 状态，但不知道数据到底还能不能信、下一步该做什么

这份 spec 的目标是把这 3 组真相定为正式产品层 contract，然后让 UI 按固定信息层级实现。

## Product Decision

### 1. `Initial Review` 需要明确“完成感”

用户不应该自己推断：

- “我是不是已经做完 baseline review 了？”
- “系统是不是已经开始稳定监测了？”

系统必须显式告诉用户：

- 当前 workspace 正处于哪个阶段
- 距离 baseline review 完成还差多少
- 做完之后会进入什么状态

### 2. `Changes` 必须先回答“为什么现在处理”

`Changes` 的主任务不是展示更多 diff，而是帮助用户做安全决策。

每条 change 在 UI 中首先要回答：

- 这是什么变化
- 为什么现在进入队列
- 系统建议怎么处理
- 处理后会影响什么

### 3. `Sources` 必须表达“数据可信度”和“恢复路径”

用户进入 `Sources` 时，最核心的问题不是：

- 当前 stage 是什么
- provider reduce 卡了多久

而是：

- 现在这条 source 的数据还可信吗
- 影响范围是什么
- 我下一步要做什么

运行时细节仍然保留，但应降为 secondary information。

## Canonical Product Truth

### A. `workspace_posture`

这是整个 workspace 的顶层产品状态，用来驱动：

- `Overview`
- `Initial Review`
- `Changes`
- workspace 顶部提示条

建议后端挂在 `GET /changes/summary` 中返回，或者单独抽为聚合 view model。

字段：

- `workspace_posture.phase`
  - `baseline_import`
  - `initial_review`
  - `monitoring_live`
  - `attention_required`
- `workspace_posture.initial_review`
  - `pending_count`
  - `reviewed_count`
  - `total_count`
  - `completion_percent`
  - `completed_at`
- `workspace_posture.monitoring`
  - `live_since`
  - `replay_active`
  - `active_source_count`
- `workspace_posture.next_action`
  - `lane`
    - `sources`
    - `initial_review`
    - `changes`
    - `families`
    - `manual`
  - `label`
  - `reason`

约束：

- 这组字段是 product truth，不让前端自己用 `baseline_review_pending + source bootstrap summary` 拼一个伪 posture
- 旧字段如 `recommended_lane` 可以保留一段时间，但以 `workspace_posture` 为准

### B. `change_decision_support`

这是每条 change 的产品级决策辅助信息。

建议返回在：

- `GET /changes`
- `GET /changes/{id}`
- 或详情相关接口的 item payload

字段：

- `decision_support.why_now`
- `decision_support.suggested_action`
  - `approve`
  - `reject`
  - `edit`
  - `review_carefully`
- `decision_support.suggested_action_reason`
- `decision_support.risk_level`
  - `low`
  - `medium`
  - `high`
- `decision_support.risk_summary`
- `decision_support.key_facts`
  - 2 到 4 条字符串
- `decision_support.outcome_preview`
  - `approve`
  - `reject`
  - `edit`

字段语义：

- `why_now`
  解释为什么这条 item 此刻进入 inbox
- `suggested_action`
  是推荐，不是强制
- `risk_summary`
  是做错决定会影响什么
- `outcome_preview`
  是按钮旁边需要展示的后果文案

约束：

- 没有把握时，后端返回 `review_carefully`
- 不允许前端用 change_type、priority、proposal_sources 自己硬推“推荐动作”

### C. `source_recovery`

这是 source 层的产品恢复模型。

建议挂在：

- `GET /sources`
- `GET /sources/{id}/observability`

字段：

- `source_recovery.trust_state`
  - `trusted`
  - `stale`
  - `partial`
  - `blocked`
- `source_recovery.impact_summary`
- `source_recovery.next_action`
  - `reconnect_gmail`
  - `update_ics`
  - `retry_sync`
  - `wait`
- `source_recovery.next_action_label`
- `source_recovery.last_good_sync_at`
- `source_recovery.degraded_since`
- `source_recovery.recovery_steps`
  - 1 到 3 条字符串

约束：

- 这是用户可见模型，不是纯 runtime 投影
- `stage/substage/progress` 继续保留，但只作为 technical detail

## Page Responsibilities

### 1. `Overview`

页面问题：

- “我现在处于哪个阶段？”
- “下一步该去哪？”

必须显示的 primary 信息：

- 当前 `workspace_posture.phase`
- baseline review 进度或 monitoring live 状态
- 一个明确主 CTA

信息层级：

- primary
  - workspace phase headline
  - progress bar / completion state
  - next action CTA
- secondary
  - source count
  - attention count
  - replay health summary

具体行为：

- `baseline_import`
  - headline: `Building your baseline`
  - CTA: `Open Sources`
- `initial_review`
  - headline: `Initial Review in progress`
  - progress bar: `reviewed / total`
  - CTA: `Open Initial Review`
- `monitoring_live`
  - headline: `Monitoring is live`
  - CTA: `Open Changes`
- `attention_required`
  - headline: `Source attention required`
  - CTA: `Open Sources`

禁止事项：

- 不要让 `Overview` 默认永远只给 `Open Changes`
- 不要把 runtime stage 文本直接扔给用户

### 2. `Initial Review`

页面问题：

- “我离完成 baseline 还差多少？”
- “做完这批后系统会进入什么状态？”

必须显示的 primary 信息：

- 明确的 progress bar
- pending / reviewed / total
- 完成后进入 monitoring 的说明

信息层级：

- primary
  - completion percent
  - remaining items
  - completion CTA / batch CTA
- secondary
  - course grouping
  - evidence
  - source references

完成态要求：

- 当 `pending_count == 0`
  - 显示明确完成态
  - headline: `Initial Review complete`
  - body: `Monitoring is now live for your connected sources.`
  - CTA: `Open Replay Review`

禁止事项：

- 不要把 `Initial Review` 做成普通 `Changes` 的视觉翻版
- 不要让用户处理完最后一条后没有完成反馈

### 3. `Changes`

页面问题：

- “为什么这条现在需要我处理？”
- “建议我怎么处理？”

必须显示的 primary 信息：

- `why_now`
- `suggested_action`
- `risk`
- 按钮后果

信息层级：

- primary
  - why you are seeing this
  - suggested action
  - risk summary
  - approve / reject / edit outcome preview
- secondary
  - diff detail
  - evidence
  - canonical/proposal comparison
  - source references

每条 detail 区的标准结构：

1. `What changed`
2. `Why you're seeing this`
3. `Suggested action`
4. `Risk`
5. `Evidence`
6. `Technical details`

按钮文案要求：

- `Approve`
  附带说明：`Update live deadline`
- `Reject`
  附带说明：`Keep current version`
- `Edit then approve`
  附带说明：`Correct details before updating live state`

禁止事项：

- 不要让用户先看到大量 raw evidence 才理解上下文
- 不要让 UI 靠 heuristics 自己标“建议 approve”

### 4. `Sources`

页面问题：

- “这条 source 现在还能不能信？”
- “出问题时我该怎么恢复？”

必须显示的 primary 信息：

- `trust_state`
- `impact_summary`
- `next_action`

信息层级：

- primary
  - source phase
  - trust state
  - impact summary
  - next action button
- secondary
  - latest sync
  - bootstrap summary
  - replay summary
- tertiary
  - stage
  - substage
  - progress age
  - token / cache / latency

Source card 标准结构：

1. source identity
2. current product phase
3. trust state badge
4. impact summary sentence
5. one primary action
6. optional technical details drawer / section

异常状态示例：

- Gmail token 失效
  - `trust_state=blocked`
  - `impact_summary=New Gmail-based changes may be missing until the mailbox is reconnected.`
  - `next_action_label=Reconnect Gmail`
- ICS feed 临时失败
  - `trust_state=partial`
  - `impact_summary=Your existing reviewed items remain visible, but new calendar updates may be delayed.`
  - `next_action_label=Retry sync`

禁止事项：

- 不要把 `Sources` 首页做成 operator observability wall
- 不要让 `RUNNING / FAILED / provider_reduce` 成为首要用户文案

### 5. `Families`

不做结构性重排，但要配合新 posture：

- 只在 `workspace_posture.next_action.lane == families` 时被突出推荐
- 不承担 baseline completion 或 source recovery 的解释责任

### 6. `Manual`

继续保持 fallback lane：

- 只在系统无法安全表达 canonical state 时出现
- 不承担 source repair 或 baseline review 的主工作

### 7. `Settings`

无需承担导流职责：

- 只保留 account / timezone / notification defaults
- 不出现 transitional workflow messaging

## Backend Contract Changes

### `GET /changes/summary`

新增：

- `workspace_posture`

保留现有：

- `changes_pending`
- `baseline_review_pending`
- `recommended_lane`

但新前端优先读取：

- `workspace_posture.phase`
- `workspace_posture.next_action`

### `GET /changes`

新增每条 item：

- `decision_support`

### `GET /changes/{id}`

新增：

- `decision_support`

### `GET /sources`

新增每条 source：

- `source_product_phase`
  - `importing_baseline`
  - `needs_initial_review`
  - `monitoring_live`
  - `needs_attention`
- `source_recovery`

### `GET /sources/{id}/observability`

新增：

- `source_recovery`

保留现有：

- `bootstrap`
- `bootstrap_summary`
- `latest_replay`
- `active`
- `operator_guidance`

但前端信息层级改为：

- `source_recovery` first
- observability second

## Frontend Implementation Scope

### Phase 1

只改信息层级，不发明新交互：

- `Overview`
  - workspace phase hero
  - strong primary CTA
- `Initial Review`
  - visible completion progress
  - visible completion state
- `Changes`
  - decision support block
- `Sources`
  - trust state + recovery action block

### Phase 2

在 API 已补齐后再做：

- richer completion ceremony in `Initial Review`
- per-change recommendation styling polish
- source technical details collapse

## UI Constraints

- 只使用后端显式字段，不允许前端硬猜业务语义
- 如果字段暂未返回，允许 UI 显示：
  - `Unavailable until backend support lands`
  - 但不要 fallback 到复杂 heuristic
- primary 区域只讲产品心智
- technical detail 区域才讲 runtime truth

## Acceptance Criteria

### User understanding

第一次上手用户应能在 5 秒内回答：

1. 我现在是在建 baseline、做 Initial Review，还是已经进入稳定监测？
2. 当前这条 change 为什么需要我处理？
3. 当前这条 source 还能不能信？
4. 我下一步该做什么？

### Overview

- 用户能直接看懂当前 workspace phase
- CTA 与当前 posture 一致

### Initial Review

- 用户能看懂自己离完成 baseline review 还差多少
- 完成最后一条后有明显完成态

### Changes

- 每条 item 都先展示 decision support，再展示 raw evidence
- approve / reject / edit 的后果是明示的

### Sources

- 用户首先看到 trust state 和 next action
- runtime stage 退居 technical details

## Non-Goals

- 不在这一轮新增顶级 lane
- 不在这一轮重做视觉体系
- 不在这一轮引入新的状态管理框架
- 不让 `Families` 或 `Manual` 承担本不属于自己的心智解释责任
