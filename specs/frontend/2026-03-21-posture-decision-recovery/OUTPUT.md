# Output

## 改动页面

- `Overview`
  - 顶部 hero 改为直接消费 `workspace_posture.phase`。
  - 主 CTA 改为直接消费 `workspace_posture.next_action`，不再默认导向 `Changes`。
  - `initial_review` 阶段显示明确 progress bar、`reviewed / total` 和剩余 pending。
  - `monitoring_live` 阶段明确表达系统已进入稳定监测。
  - 四张 secondary cards 保留，但优先级退到 posture hero 之后。

- `Initial Review`
  - 页面顶部改成阶段头部，而不是纯粹复用 `Changes` 的 queue copy。
  - 固定显示 `pending / reviewed / total` 和 progress bar。
  - `pending_count == 0` 时显示明确完成态：
    - headline: `Initial Review complete`
    - body: `Monitoring is now live for your connected sources.`
    - CTA: `Open Replay Review`

- `Changes`
  - detail 区新增前置 `Decision support` block。
  - 在 evidence 之前固定回答：
    - `Why you're seeing this`
    - `Suggested action`
    - `Risk`
    - `Key facts`
  - 决策按钮旁新增 `outcome_preview` 文案：
    - approve
    - reject
    - edit
  - `decision_support` 缺失时仍保留旧 evidence-first fallback。
  - `Initial Review` lane 的 hero 也同步改成带 progress / completion 的版本。

- `Sources`
  - list card 优先显示：
    - `source_product_phase`
    - `source_recovery.trust_state`
    - `source_recovery.impact_summary`
    - `source_recovery.next_action_label`
  - bootstrap/import 结果保留，但降为 secondary summary：
    - imported
    - needs review
    - ignored
    - conflicts
  - source detail hero 和 `Current Posture` 区改为 trust / impact / next action first。
  - stage / substage / tokens / latency 保留在 secondary / tertiary 区。

## 使用到的后端字段

- `GET /changes/summary`
  - `workspace_posture.phase`
  - `workspace_posture.initial_review.pending_count`
  - `workspace_posture.initial_review.reviewed_count`
  - `workspace_posture.initial_review.total_count`
  - `workspace_posture.initial_review.completion_percent`
  - `workspace_posture.initial_review.completed_at`
  - `workspace_posture.monitoring.live_since`
  - `workspace_posture.monitoring.replay_active`
  - `workspace_posture.monitoring.active_source_count`
  - `workspace_posture.next_action.lane`
  - `workspace_posture.next_action.label`
  - `workspace_posture.next_action.reason`

- `GET /changes`
  - `decision_support.why_now`
  - `decision_support.suggested_action`
  - `decision_support.suggested_action_reason`
  - `decision_support.risk_level`
  - `decision_support.risk_summary`
  - `decision_support.key_facts`
  - `decision_support.outcome_preview.approve`
  - `decision_support.outcome_preview.reject`
  - `decision_support.outcome_preview.edit`

- `GET /sources`
  - `source_product_phase`
  - `source_recovery.trust_state`
  - `source_recovery.impact_summary`
  - `source_recovery.next_action`
  - `source_recovery.next_action_label`
  - `source_recovery.last_good_sync_at`
  - `source_recovery.degraded_since`
  - `source_recovery.recovery_steps`

- `GET /sources/{id}/observability`
  - `source_product_phase`
  - `source_recovery.*`
  - `bootstrap_summary.imported_count`
  - `bootstrap_summary.review_required_count`
  - `bootstrap_summary.ignored_count`
  - `bootstrap_summary.conflict_count`

## Preview / demo backend

- `frontend/lib/demo-backend.ts` 已同步补齐这轮 preview contract：
  - `workspace_posture`
  - per-change `decision_support`
  - per-source `source_product_phase`
  - per-source `source_recovery`
- 额外补了一个已审 baseline item，用于 preview 中展示真实的 `Initial Review` progress。

## 清理掉的前端旧债

- 删除了不再被引用的 `frontend/lib/import-review.ts`。
- `Overview` 和 `Sources` 不再用前端 heuristic 去拼 baseline/import posture。

## 尚未落地的 backend gaps

- 当前没有专门的 source action endpoint 与 `source_recovery.next_action=wait` 一一对应。
  - 前端现在只把它作为明确文案展示，并把 CTA 导向现有 lane（例如 `Initial Review` 或 source detail）。
- `Initial Review` 的“完成感”目前是页面级完成态，不依赖额外的 backend completion ceremony。

## Preview / smoke 验证结果

- 命令验证已通过：
  - `npm run typecheck`
  - `npm run lint`
  - `NEXT_DIST_DIR=.next-prod npm run build`

- Playwright 已验证：
  - `/preview`
    - hero 使用 `workspace_posture`
    - CTA 指向 `Initial Review`
  - `/preview/initial-review`
    - 顶部显示 progress / counts
    - detail 中先显示 decision support，再显示 evidence
  - `/preview/changes`
    - replay lane 与 baseline lane 分离
    - detail 首屏先回答 why / suggested action / risk
    - buttons 显示 outcome preview
  - `/preview/sources`
    - source cards 先显示 trust / impact / next step
    - bootstrap/import counts 仍可见但降级
  - `/preview/sources/2`
    - detail hero 与 posture card 已改为 recovery-first hierarchy

- 额外移动端抽查：
  - `/preview/changes`
    - mobile sheet 可打开，decision support block 顺序正确
  - `/preview/sources`
    - source cards 在窄屏下未出现按钮挤出或文字重叠
