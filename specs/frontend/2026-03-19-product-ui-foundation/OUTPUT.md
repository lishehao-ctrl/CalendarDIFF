# Output Notes

## Backend Truth Ready For UI

当前后端已提供可直接给 UI 使用的 workbench/intake 聚合入口：

- `GET /changes/summary`

该接口已经包含：

- pending changes 数
- backend 推荐的 lane
- 推荐原因
- sources posture 汇总
- families governance attention
- manual fallback summary

## Frontend Implementation Priority

1. `Overview`
2. `Sources`
3. `Changes`
4. `Families`
5. `Manual`
6. `Settings`

## Do Not Rebuild In UI

- 不要自己计算 `recommended_lane`
- 不要自己拼 `Overview` 的 lane 选择器
- 不要把 `Families` 或 `Manual` 提升为默认首页动作

## Known Product Gap

即使有了新的 `/changes/summary`，`Families / Manual` 的进入理由在 operator 心智上仍然偏弱。

UI 可以用 `recommended_action_reason` 做基础解释，但后续后端可能还会继续补更细的 lane routing reason。
