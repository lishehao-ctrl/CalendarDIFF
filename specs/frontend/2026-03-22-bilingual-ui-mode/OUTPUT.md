# Output

## 改动摘要

- 新增轻量前端 i18n 基础设施，支持 `en` / `zh-CN`
- 语言来源按优先级实现：
  1. `localStorage`
  2. 浏览器语言
  3. 默认 `en`
- `Settings` 新增 `English / 中文` 切换
- `App shell`、`Settings`、`Login / Register / Onboarding`、部分 page shell、通用 data states、logout、legal shell 已接入字典
- formatter 已改为跟随 locale，而不是写死 `en-US`
- preview 页面与正式页面共用同一套 locale provider / dictionaries / formatter
- 这一轮继续把主工作流页面壳层推进到同一套字典：
  - `Overview`
  - `Sources`
  - `Source detail`
  - `Sources connect flows`
  - `Changes`
  - `Families`
  - `Manual`
  - `Change edit`

## 新增的前端 i18n 基础设施

- [locales.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/i18n/locales.ts)
- [runtime.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/i18n/runtime.ts)
- [provider.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/i18n/provider.tsx)
- [use-locale.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/i18n/use-locale.ts)
- [en.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/i18n/dictionaries/en.ts)
- [zh-CN.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/i18n/dictionaries/zh-CN.ts)

接入点：

- [app/layout.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/app/layout.tsx)
- [presenters.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/presenters.ts)
- [source-observability.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/source-observability.ts)

## 已完成双语化的页面

- `Settings`
  - 页头
  - 账号 / 时区字段壳层
  - 语言切换
  - timezone picker 壳层
- `App shell`
  - 品牌标题
  - sidebar labels / descriptions
  - mobile nav labels / aria
  - workspace status shell
  - logout 文案
- `Login / Register`
  - 壳层 marketing copy
  - 表单 labels / CTA / placeholders
  - 前端拥有的 fallback error
- `Onboarding`
  - 顶部 page shell
  - 主要 step shell / CTA / loading labels
  - frontend-owned fallback errors
- `Overview`
  - posture hero copy
  - summary cards
  - CTA labels
- `Sources`
  - sources list hero / banners / counts / tools shell
  - source row CTA shell
  - source detail sections:
    - `Connection`
    - `Current Posture`
    - `Bootstrap`
    - `Replay History`
  - source connect flows:
    - Gmail mailbox setup shell
    - Canvas ICS setup shell
- `Manual`
  - add/edit sheet shell
  - filters
  - empty / validation / banner / CTA labels
- `Changes`
  - hero / lane framing
  - decision workspace shell
  - decision support headings
  - evidence / canonical / decision sections
  - mobile filter sheet shell
- `Families`
  - governance hero
  - subarea tabs
  - family list/detail shell
  - observed-label governance shell
  - relink preview sheet shell
  - suggestions shell
- `Change edit`
  - edit workspace labels
  - preview/result shell
- `Privacy / Terms`
  - shell title / summary / cover items / nav CTA
- `Common`
  - `LoadingState`
  - `ErrorState` heading
  - locale-aware date / status / number formatting

仍未完全收尽的前端-owned copy：

- 少量 technical-detail 级文案仍然是英文：
  - `Changes` evidence metadata / low-priority detail lines
  - `Sources` 部分 sync success / failure fallback sentence
  - `Manual` 个别统计行与 placeholder 示例值
- `legal` 正文正文内容仍保留英文版本，没有新增中文法务正文

## 仍保留英文的 backend-owned 文本

- `decision_support.*` 自由文本
- `source_recovery.*` 自由文本
- `operator_guidance.message`
- backend `HTTPException(detail="...")`
- Gmail snippet / ICS title / description
- business data:
  - `event_name`
  - `family_name`
  - `raw_type`
  - `course_display`

这些本轮按要求原样显示，不做前端猜测翻译。

## Validation

- `npm run typecheck`
- `npm run lint`
- `NEXT_DIST_DIR=.next-prod npm run build`

结果：

- 通过

## 本轮涉及的主要文件

- [provider.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/i18n/provider.tsx)
- [runtime.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/i18n/runtime.ts)
- [en.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/i18n/dictionaries/en.ts)
- [zh-CN.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/i18n/dictionaries/zh-CN.ts)
- [overview.ts](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/lib/overview.ts)
- [sources-panel.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/sources-panel.tsx)
- [source-detail-panel.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/source-detail-panel.tsx)
- [source-observability-sections.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/source-observability-sections.tsx)
- [gmail-source-setup-panel.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/gmail-source-setup-panel.tsx)
- [canvas-ics-setup-panel.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/canvas-ics-setup-panel.tsx)
- [review-changes-panel.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/review-changes-panel.tsx)
- [family-management-panel.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/family-management-panel.tsx)
- [manual-workbench-panel.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/manual-workbench-panel.tsx)
- [review-change-edit-page-client.tsx](/Users/lishehao/Desktop/Project/CalendarDIFF/frontend/components/review-change-edit-page-client.tsx)

## Manual smoke

- `en`
  - `Settings` 页默认英文壳层可正常渲染
  - `App shell` 英文导航可正常渲染
- `en / zh-CN`
  - `typecheck` / `lint` / `build` 都通过，说明共享字典、locale provider、formatter、preview/live route 依赖没有破坏编译
- `zh-CN`
  - provider / dictionaries / runtime 已接通
  - 本地语言切换会驱动 client-side locale state
  - 这轮没有额外跑 Playwright smoke；浏览器端中英文切换和逐页视觉检查仍建议下一轮继续做

## Follow-ups

- 继续把 `Sources / Changes / Manual` 的最深层 technical-detail copy 收进字典
- legal section body 视需求再补正式中文版本
- 若后端后续提供 code-based multilingual fields，再替换当前 backend-owned language gap
