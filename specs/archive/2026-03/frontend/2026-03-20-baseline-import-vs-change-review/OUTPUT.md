# Decision Memo

## Final Direction

- `baseline import` 和 `replay review` 必须分开
- `Changes` 只承接真正后续变化
- `Sources` 负责解释 source bootstrap import
- `Overview` 负责把用户导向 `Initial Review` 或普通 `Changes`
- `Initial Review` 是阶段性工作台，不做长期一级导航

## Backend Requirements

- `Change` DTO 增加：
  - `intake_phase`
  - `review_bucket`
- `/changes/summary` 增加：
  - `baseline_review_pending`
  - 新的 `recommended_lane_reason_code`
- `/sources/{id}/observability` 增加：
  - `bootstrap_summary`

## Frontend Requirements

- `Overview` hero/CTA 按 baseline vs replay 区分
- `Sources` source card/detail 展示 import summary
- `Changes` 默认只展示 `review_bucket=changes`
- 新增 `Initial Review` 页面用于 bootstrap anomalies
