# Multi-Agent API Smoke Spec

## Summary

这份 spec 定义“多个 subagent 通过现有 public API 做全年 smoke test”时，应该选哪套数据集、怎么分工、怎么推进、以及如何判断结果是否可信。

结论先行：

- 主 smoke 数据集组合应固定为：
  - ICS: `year_timeline`
  - Gmail: `year_timeline_full_sim`
- `year_timeline_mixed` 不是主 smoke 数据源。
  - 它适合静态 regression / bundle materialization
  - 不适合多 agent chronological human-in-loop smoke

原因：

- `year_timeline` 提供稳定的全年 chronological backbone
- `year_timeline_full_sim` 提供真实 inbox 压力，包括大量 junk / wrapper / academic non-target / unrelated noise
- 两者组合既保留 Gmail/ICS 对应关系，又保留真实使用时的噪声环境

## Dataset Choice

### Primary smoke dataset

主 smoke 固定使用：

- ICS timeline: `data/synthetic/year_timeline_demo/year_timeline_manifest.json`
- Gmail bucket: `tests/fixtures/private/email_pool/year_timeline_full_sim`

如果需要缩小窗口：

- ICS 用 `year_timeline` 的 derived set
- Gmail 用 `year_timeline_full_sim_smoke_*` 这类缩小版 derived set

### Why not `year_timeline_gmail` alone

`year_timeline_gmail` 适合：

- parser regression
- prefilter regression
- targeted Gmail prompt/cache probe

但它不适合主 smoke，因为：

- 它的噪声层不如 `year_timeline_full_sim` 完整
- 它更像“目标课程邮件主集合”，不像真实邮箱

### Why not `year_timeline_mixed` as the main source

`year_timeline_mixed` 适合：

- static mixed regression
- bundle materializer
- small deterministic replay contract

但不适合主 smoke，因为：

- 它不是“长期连续使用中的 inbox + calendar 环境”
- 它更像回归测试材料，不像真实用户每天收到的流

## Recommended Test Modes

### Mode A: Fast smoke

适用：

- 新分支快速验收
- runtime 修复后先看是否还会立即卡死

配置：

- ICS: small derived set
- Gmail: `year_timeline_full_sim_smoke_*`
- checkpoint: 2-4 个

目标：

- 快速发现 bootstrap/replay/runtime 卡死
- 快速验证 agent 协作 API 工作流

### Mode B: Monthly smoke

适用：

- 多 agent 协作逻辑稳定性
- 用户决策与系统演化联动

配置：

- ICS: `year_timeline`
- Gmail: `year_timeline_full_sim`
- 只跑一个季度或 1-2 个月

目标：

- 验证 checkpoint 协作流程
- 验证 `Changes / Families / Manual / Sources` 角色分工

### Mode C: Full-year smoke

适用：

- 最终稳定性验收
- 多 agent API-only 年度系统测试

配置：

- ICS: `year_timeline`
- Gmail: `year_timeline_full_sim`
- 全年 chronological replay

目标：

- 验证全年推进
- 验证噪声压力下的真实工作流
- 验证 bootstrap/replay/token/cache/latency/operator burden

## Multi-Agent Role Design

### Agent 1: Driver

唯一职责：

- 启动 replay / acceptance run
- 轮询 checkpoint
- 分发 checkpoint 上下文
- 汇总各 agent 的动作结果
- 调用 `resume`

Driver 不做细粒度审批决策，避免它既当协调者又当操作者。

### Agent 2: Changes Operator

职责：

- 处理 pending changes
- 执行 approve / reject / edit-then-approve
- 记录为什么做这个决策

它是主执行者，因为 `Changes` 是产品主工作台。

### Agent 3: Families Operator

职责：

- 处理 naming drift
- 执行 family create / rename / raw-type relink
- 审 raw-type suggestion

它只在需要治理时介入，不常驻主路径。

### Agent 4: Sources + Manual Auditor

职责：

- 看 source posture / observability
- 判断当前是否该暂停相信系统
- 在必要时用 `Manual` 做 fallback create / update / delete

这个角色本质上是“系统健康 + fallback”守门员。

## Coordination Protocol

### Shared rule

所有 agent 都只能通过现有 public API 动作，不允许：

- 直改 DB
- 用内部 service
- 修改 fixture 状态

### Driver outputs at each checkpoint

每个 checkpoint，Driver 必须发给其他 agent：

- run dir
- checkpoint index
- absolute time / batch label
- pending changes summary
- source posture summary
- family suggestion summary
- manual count

### Decision precedence

固定优先级：

1. `Changes`
2. `Sources`
3. `Families`
4. `Manual`

解释：

- 先保证 timeline truth
- 再判断 source trustworthiness
- 再做 naming truth
- 最后才做 fallback patch

## Public API Usage Contract

### Driver

Driver 主要调用：

- `scripts/run_year_timeline_backend_acceptance.py`
- `scripts/run_year_timeline_replay_smoke.py`
- `GET /sources`
- `GET /sources/{source_id}/observability`
- `GET /changes`
- `GET /families/raw-type-suggestions`
- `GET /manual/events`

### Changes Operator

- `GET /changes`
- `GET /changes/{change_id}`
- `GET /changes/{change_id}/edit-context`
- `GET /changes/{change_id}/evidence/{side}/preview`
- `POST /changes/{change_id}/decisions`
- `POST /changes/batch/decisions`
- `POST /changes/edits/preview`
- `POST /changes/edits`
- `POST /changes/{change_id}/label-learning/preview`
- `POST /changes/{change_id}/label-learning`

### Families Operator

- `GET /families`
- `POST /families`
- `PATCH /families/{family_id}`
- `GET /families/courses`
- `GET /families/raw-types`
- `POST /families/raw-types/relink`
- `GET /families/raw-type-suggestions`
- `POST /families/raw-type-suggestions/{suggestion_id}/decisions`

### Sources + Manual Auditor

- `GET /sources`
- `GET /sources/{source_id}/observability`
- `GET /sources/{source_id}/sync-history`
- `GET /sync-requests/{request_id}`
- `GET /manual/events`
- `POST /manual/events`
- `PATCH /manual/events/{entity_uid}`
- `DELETE /manual/events/{entity_uid}`

## Smoke Success Criteria

### Runtime success

- bootstrap 自然完成
- replay 能继续推进
- agent 不需要 DB 干预
- source posture 信息足够支撑暂停/继续判断

### Semantic success

- `Changes` 仍然承担主要工作量
- `Families` 只在 naming drift 时介入
- `Manual` 是少量 fallback，不变成主路径
- Gmail/ICS 对应关系在全年推进中保持可解释

### Dataset realism success

- Gmail 里有大量 unrelated/junk/distractive 内容
- 但主时间轴仍由 `year_timeline` 约束
- agent 需要真的判断，而不是靠低噪声样本轻松过关

## Recommended Execution Order

1. 用 `year_timeline + year_timeline_full_sim` 跑 2-4 checkpoint fast smoke
2. 通过后跑一个月度窗口
3. 最后跑 full-year smoke

不要直接让多个 agent 一上来就跑全年。

## Assumptions

- 使用现有 public API
- 不引入新 smoke-only backend endpoints
- Driver 可以使用现有 acceptance / replay harness
- 其他 agent 只做 API operator，不做实现修改
