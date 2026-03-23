# Output

## Status

- Implemented in frontend

## UI changes

- `Families`
  - 主页面用户语言已切成 `Observed label / Canonical family`
  - `Raw Types` 子区改成 `Observed labels`
  - family list / detail 现在优先展示治理意义：
    - observed label count
    - active event count
    - pending change impact unavailable 明确标缺口
  - observed-label 行现在先展示：
    - source 原始标签
    - 当前 canonical family
    - impact summary
  - relink 从直接提交改成 `preview -> confirm`
  - relink preview sheet 现在展示：
    - 当前 family
    - 目标 family
    - active event sample
    - related suggestion count
    - future imports note
    - pending change impact gap note
- `Changes`
  - detail 区新增 `Observed label mapping` block
  - block 使用现有 `label-learning preview` 数据展示：
    - observed label
    - current family
    - mapping explanation
    - `Open Families` CTA
  - `Approve and learn` 的按钮文案同步切成 canonical-family 语言

## 主要改动文件

- [family-management-panel.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/family-management-panel.tsx)
- [review-changes-panel.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/review-changes-panel.tsx)
- [types.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/types.ts)
- [families.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/api/families.ts)
- [changes.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/api/changes.ts)
- [en.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/i18n/dictionaries/en.ts)
- [zh-CN.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/i18n/dictionaries/zh-CN.ts)

## Backend gaps encountered

- 当前 frontend contract 里没有“某个 observed-label relink 会影响多少 pending changes”的正式字段。
  - 本轮没有前端伪造这个数字。
  - relink preview 里明确标记为 unavailable。
- 当前 frontend contract 里没有 dedicated relink preview endpoint。
  - 本轮用 client-side aggregation 先做 preview：
    - `GET /families/raw-types`
    - `GET /families/raw-type-suggestions`
    - `GET /manual/events`
- `Changes` mapping block 依赖现有 `label-learning preview`。
  - 只有当该 projection 可用时才显示。
  - 不根据 `change_type` 或其他 heuristic 自己推断 mapping。

## Validation

- `npm run typecheck`
- `npm run lint`
- `NEXT_DIST_DIR=.next-prod npm run build`

结果：

- 通过

## Follow-ups

- 如果后端后续提供 relink impact preview / pending-change impact 字段，可以把 preview sheet 从“明确缺口”升级成完整影响列表。
- 如果后端后续提供 family-level pending change counts，可以把 family card 的 impact fact 从 unavailable 升级为真实数字。
- 下一轮可以继续压缩 `Families` 页 technical density，把课程筛选、family detail、suggestions 的节奏再做得更轻一点。
