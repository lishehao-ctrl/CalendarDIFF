你负责 CalendarDIFF 的前端产品层实现，只做 UI，不改后端语义。

请严格按这几个原则实现：

1. 首页 `Overview` 必须以 `GET /changes/summary` 为主数据源。
2. 不要在前端重新推断 `recommended_lane`；直接消费 backend 返回的：
   - `recommended_lane`
   - `recommended_lane_reason_code`
   - `recommended_action_reason`
3. `Changes` 是主工作台。
4. `Families` 是治理台，不是 inbox。
5. `Manual` 是 fallback。
6. `Sources` 是连接与 runtime observability 中心。
7. 如果发现字段不够，不要前端硬猜，直接记录缺口给后端。

当前最值得先做的真实接线路径：

- `Overview`
  - hero CTA
  - lane cards
  - source posture summary
- `Sources`
  - list
  - detail
  - bootstrap vs replay sections
- `Changes`
  - pending queue
  - detail
  - decision/edit/evidence

实现时请优先保证：

- 页面职能清晰
- lane 边界清晰
- 不暴露后端内部术语
- 不在 UI 里自建另一套产品逻辑

如果需要具体页面与字段，请以 `SPEC.md` 为准。
