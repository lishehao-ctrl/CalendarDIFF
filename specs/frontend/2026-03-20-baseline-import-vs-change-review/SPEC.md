# CalendarDIFF Baseline Import vs Change Review Spec

## Summary

当前系统把两种完全不同的工作混在同一个 `Changes` review 心智里：

1. 第一次接入 source 时建立初始基线
2. 已有基线之后处理真正的后续变化

这在技术上保守，但从用户心智看并不合理。

用户不会自然接受：

- “我第一次导入时，几十个新事件也要像后续变化一样逐条审批”

这份 spec 的目标是把产品语义收敛成两条不同工作流：

- `Baseline import`
- `Change review`

并让前后端按同一个模型协作。

## Product Decision

### 1. Baseline 与 Replay 明确分开

- `baseline import`:
  source 首次导入时建立初始 canonical state
- `replay review`:
  canonical 已存在后，处理后续真正变化

### 2. `Changes` 不再承担首次导入主负担

- `Changes` 主 lane 只服务“变化”
- baseline 只保留少量高风险项进入 review
- 不再让普通 `Changes` 承接整批 bootstrap created items

### 3. `ICS bootstrap` 默认更激进

对于 `ICS` 首次导入：

- 高置信
- identity 完整
- family/raw_type 可解析
- due_date / due_time 正常
- 没有冲突 observation

则直接写入 canonical baseline，不进入普通 `Changes`

只把这些项保留为 bootstrap review：

- 时间异常
- identity 歧义
- 与已有 canonical/state 冲突
- family/raw type 无法稳定解析

### 4. `Gmail bootstrap` 默认更保守

对于 `Gmail` 首次导入：

- 只把高置信且值得确认的新项送入人工 review
- 大量弱候选不直接污染普通 `Changes`
- 优先 review：
  - 明确 due/time signal
  - 和已有 ICS/canonical 冲突
  - 指向 grade-relevant deliverable 且 identity 足够稳定

### 5. 初次导入 review 不是日常 review

初次导入阶段的少量人工确认应使用单独心智：

- `Initial Review`
- `Import Review`
- 或 `Baseline Review`

它不是一个永久一级导航，而是一个阶段性工作台。

### 6. `Sources` 承担 bootstrap 解释责任

用户第一次接入 source 时，最自然的问题不是：

- “有哪些 change 待审批？”

而是：

- “这次导入了什么？”
- “哪些是可信 baseline？”
- “哪些东西还需要我确认？”

所以 `Sources` 必须承担：

- baseline import summary
- bootstrap trust posture
- review-required count

### 7. `Overview` 负责区分当前是 import 还是 change

`Overview` 不应只说：

- “Open Changes”

它必须先判断：

- 当前优先任务是 `Import Review`
- 还是正常 `Changes`

## User Mental Model

### 新用户

新用户的理解应该是：

1. 我连上 source
2. 系统先导入一个初始基线
3. 它只把少量可疑项拿出来给我确认
4. 以后真的有变化，再去 `Changes`

### 老用户

老用户的理解应该是：

1. `Changes` 只表示增量变化
2. `Sources` 负责 source 健康和导入状态
3. `Families` 负责命名治理

## Backend Changes

### 1. `changes` 增加 intake 语义字段

`Change` DTO 需要显式返回：

- `intake_phase`
  - `baseline`
  - `replay`
- `review_bucket`
  - `initial_review`
  - `changes`

约束：

- 旧数据默认按 `replay/changes` 投影
- 新逻辑按 source bootstrap state 决定归属

### 2. Baseline auto-accept 规则

后端在 proposal rebuild / apply 阶段增加一个 baseline decision layer：

- `baseline_auto_accept`
- `baseline_review_required`
- `baseline_ignore`

其中：

- `ICS bootstrap created`:
  优先 `baseline_auto_accept`
- `Gmail bootstrap created`:
  优先 `baseline_review_required` 或 `baseline_ignore`

### 3. Source observability 增加 bootstrap summary

建议在 `/sources/{id}/observability` 上增加：

- `bootstrap_summary`
  - `imported_count`
  - `review_required_count`
  - `ignored_count`
  - `conflict_count`
  - `state`
    - `idle`
    - `running`
    - `review_required`
    - `completed`

### 4. `/changes/summary` 增加基线路由信息

建议增加：

- `baseline_review_pending`
- `recommended_lane`
  - `sources`
  - `initial_review`
  - `changes`
  - `families`
  - `null`
- `recommended_lane_reason_code`
  - `baseline_review_pending`
  - `runtime_attention_required`
  - `changes_pending`
  - `family_governance_pending`
  - `all_clear`

### 5. `Changes` listing 支持 bucket filter

`GET /changes`

新增 query:

- `review_bucket=initial_review|changes`
- `intake_phase=baseline|replay`

默认：

- 不带参数时返回普通 `changes`

### 6. Optional: 单独聚合 endpoint

如果前端需要单独页面，可以新增：

- `GET /changes/initial-review/summary`

但更推荐先在现有 `changes/summary` 与 `changes list` 上加字段，不新增一堆新 API。

## Frontend Changes

### 1. `Overview`

新增一种主 CTA 分支：

- 如果 `baseline_review_pending > 0`
  主 CTA = `Open Initial Review`
- 否则才是 `Open Changes`

### 2. `Sources`

在 source card/detail 上增加 baseline summary 区域：

- Imported
- Needs review
- Ignored
- Conflicts

并明确写：

- `Importing baseline`
- `Baseline ready`
- `Needs initial review`

### 3. `Initial Review`

新增一个阶段性工作台：

- 默认不做一级导航
- 从 `Overview` / `Sources` 进入
- 只展示 `review_bucket=initial_review`

页面行为：

- 按课程分组
- 支持 batch accept
- 支持“只看冲突项”

### 4. `Changes`

普通 `Changes` 只展示：

- `review_bucket=changes`

不再把大量 bootstrap created items 混进来。

### 5. `Families`

不变。

但如果 bootstrap review 暴露出大量命名歧义，`Overview` 可以继续把用户导向 `Families`。

## UX Rules

### 1. 不要把 baseline 说成 “changes”

对于 bootstrap 阶段：

- 用 `import`
- 用 `baseline`
- 用 `initial review`

不要继续把它叫：

- pending changes

### 2. 高密度批量动作优先

`Initial Review` 的第一原则是减少点击数。

优先提供：

- 按课程 accept all
- 按 family accept all
- Accept all low-risk

### 3. 不新增长期导航噪音

`Initial Review` 是临时阶段性工作，不应该长期占一个顶级导航位。

## Acceptance Criteria

### Backend

- `ICS bootstrap created` 的大部分低风险项不再进入普通 `Changes`
- `Gmail bootstrap created` 不再大规模污染普通 `Changes`
- `changes/summary` 能区分 baseline review 和 replay review
- `sources/observability` 能解释 bootstrap import 结果

### Frontend

- `Overview` 能明确路由到 `Initial Review` 或 `Changes`
- `Sources` 能解释 baseline import 进展和结果
- `Changes` 不再承担 baseline import 主工作量
- `Initial Review` 能支持 grouped / batch review

## Rollout Order

1. 后端先增加 `intake_phase / review_bucket / baseline_review_pending / bootstrap_summary`
2. 前端先按新字段做 route / card / CTA 调整
3. 再逐步把 `ICS bootstrap created` auto-accept 落地
4. 最后收紧 `Gmail bootstrap created` 的 review gating
