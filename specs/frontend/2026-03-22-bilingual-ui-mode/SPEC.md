# CalendarDIFF 中英双模式前端实现 Spec

## Summary

这轮 handoff 给 UI agent 的目标是：

- 在**不改后端 contract**的前提下
- 给 CalendarDIFF 做一个可用、稳定、可扩展的 `English / 中文` 双模式前端壳层
- 先把**前端自己拥有的语言**全部收进统一 i18n 基础设施
- 不去假装“后端已经是多语言系统”

这是一轮 **frontend-only phase 1**。

它的目标不是“一次性把所有用户可见文本完全双语化”，而是先把正确的前端基石搭起来，让后续后端语言字段/错误码接入时不需要重做页面。

## Core Decision

### 1. 这轮只做前端双语壳层

本轮 UI agent 只改前端：

- 不改数据库
- 不改 API shape
- 不改后端 message 文本
- 不增加 locale-prefixed routes

也就是说：

- `en`
- `zh-CN`

这两个模式先由前端负责切换与渲染。

### 2. 语言来源先用前端本地持久化

本轮因为不改后端，所以用户语言偏好先不落 `users` 表。

优先级固定为：

1. 用户手动选择的本地设置
2. 浏览器语言
3. 默认 `en`

本地持久化建议：

- `localStorage`
- key: `calendardiff.locale`

允许值固定为：

- `en`
- `zh-CN`

### 3. 不做多语言路由

本轮不做：

- `/en/...`
- `/zh/...`
- middleware based locale routing

所有现有 URL 保持不变。

双语只影响页面内容，不影响路由结构。

### 4. 不翻译业务数据和证据内容

以下内容**不能**由前端自动翻译：

- `event_name`
- `family_name`
- `raw_type`
- `course_display`
- Gmail snippet
- ICS title / description
- evidence preview 原文
- API 返回的业务数据内容

原因：

- 这些是 canonical 数据或 frozen evidence
- 系统翻译会污染证据与语义

只能翻译：

- 页面壳层
- 操作按钮
- section title
- helper copy
- empty/error/loading state
- 本地可控的 UI 文案

### 5. 不前端硬翻后端自由文本

当前后端还会直接返回大量英文人类可读文本，例如：

- `source_recovery.impact_summary`
- `source_recovery.next_action_label`
- `operator_guidance.message`
- `decision_support.why_now`
- `decision_support.suggested_action_reason`
- `decision_support.risk_summary`
- 各种 `HTTPException(detail="...")`

这轮前端**不要**做这些危险行为：

- 基于英文字符串做匹配翻译
- 把英文 message 送第三方翻译
- 自己猜 backend message 的语义并重写

规则：

- 后端自由文本保留原样显示
- 前端只翻译页面壳层
- 在 spec / output 里明确标记：这些是 backend-owned language gaps

## Target Architecture

## A. Frontend i18n foundation

需要新增一套很轻的前端 i18n 基础设施：

- `frontend/lib/i18n/`
- `frontend/lib/i18n/locales.ts`
- `frontend/lib/i18n/dictionaries/en.ts`
- `frontend/lib/i18n/dictionaries/zh-CN.ts`
- `frontend/lib/i18n/provider.tsx`
- `frontend/lib/i18n/use-locale.ts`

最小能力：

- 获取当前 locale
- 切换 locale
- 读取字典
- 提供 `t(key)` 或等价 helper

要求：

- 只支持扁平或浅层 key
- 不要引入新 i18n 库
- 使用现有 Next + React 基础设施

### Locale state

建议提供：

- `LocaleProvider`
- `useLocale()`
- `useT()`

Provider 需要输出：

- `locale`
- `setLocale`
- `dictionary`

## B. Formatter layer

当前很多 formatter 写死了英文或 `en-US`。

必须把这些集中改成 locale-aware：

- `frontend/lib/presenters.ts`
- 任何 `Intl.DateTimeFormat("en-US", ...)`
- 任何直接 `toLocaleString()` 但没传 locale 的地方

规则：

- formatter 从 locale context 取当前 locale
- English 用 `en-US`
- 中文用 `zh-CN`

最少要覆盖：

- 时间
- 日期
- 状态标签格式化
- 数字展示（如 token count）

## C. Language switch entry

这轮先把语言切换入口放在：

- `Settings`

如果 UI agent 认为壳层顶部也需要快速入口，可以作为 secondary enhancement，但不是必须。

`Settings` 最少需要：

- 当前语言 badge / field
- `English`
- `中文`

切换后要求：

- 立即生效
- 不需要重新登录
- 页面内可直接刷新 copy

## In-Scope Pages

这轮需要翻的，是**前端拥有文案**的页面：

- `/login`
- `/register`
- `/onboarding`
- `/`
- `/sources`
- `/sources/[sourceId]`
- `/sources/connect/gmail`
- `/sources/connect/canvas-ics`
- `/changes`
- `/changes/[changeId]/[mode]`
- `/families`
- `/manual`
- `/settings`
- `/privacy`
- `/terms`
- `/preview*`

规则：

- preview 页面也要共享同一套字典
- preview 不可以继续写死另一套文案

## Out-of-Scope For This Phase

以下内容不在这轮 UI agent 范围内：

- 数据库 `language_code`
- 后端 message code 化
- 通知邮件双语
- API 错误 detail 的正式多语言化
- SSR locale negotiation
- SEO locale pages

## Translation Ownership

### 前端拥有的文案

这些必须进入字典：

- page titles
- subtitles
- CTA labels
- section labels
- loading labels
- empty state
- error state（前端自己写的）
- banner 文案（前端自己写的）
- helper copy
- legal page 壳层 copy
- login/register/onboarding 壳层 copy
- sidebar labels / descriptions

### 后端拥有的文案

这些本轮不要翻：

- `decision_support.*` 的自由文本
- `source_recovery.impact_summary`
- `source_recovery.next_action_label`
- `operator_guidance.message`
- 任意后端 `detail`

但是 UI agent 需要在相关页面保留良好层级：

- 页面壳层是本地语言
- 后端自由文本可以原样嵌入 secondary block

## UX Rules

### 1. 语言切换不改变信息架构

只换语言，不换页面结构。

### 2. 不要把中文模式做成“全部缩写”

中文 copy 仍然要保留清楚层级，不要为了短而牺牲语义。

### 3. 英文和中文都要自然

避免：

- 中文直接逐词翻译英文
- 英文像机器翻译

### 4. Legal / auth / onboarding 语气保持产品化

不要因为进入双语而把 copy 变成僵硬术语表。

## File Guidance

UI agent 重点会改这些：

- `frontend/components/app-shell.tsx`
- `frontend/components/login-page-client.tsx`
- `frontend/components/onboarding-wizard.tsx`
- `frontend/components/overview-page-client.tsx`
- `frontend/components/sources-panel.tsx`
- `frontend/components/source-detail-panel.tsx`
- `frontend/components/gmail-source-setup-panel.tsx`
- `frontend/components/canvas-ics-setup-panel.tsx`
- `frontend/components/review-changes-panel.tsx`
- `frontend/components/review-change-edit-page-client.tsx`
- `frontend/components/family-management-panel.tsx`
- `frontend/components/manual-workbench-panel.tsx`
- `frontend/components/settings-panel.tsx`
- `frontend/components/legal-page.tsx`
- `frontend/lib/presenters.ts`

建议新增：

- `frontend/lib/i18n/*`

## Implementation Order

1. 落 locale provider + dictionary loader
2. 落 `Settings` 语言切换入口
3. 改 formatter 为 locale-aware
4. 改 app shell / sidebar / shared data states
5. 改 auth + onboarding
6. 改 main workspace pages
7. 改 legal + preview
8. 最后检查所有页面是否还有硬编码英文残留

## Acceptance Criteria

### Functional

- 用户可以在前端切换 `English / 中文`
- 切换后主页面壳层文案立即变化
- 刷新页面后语言选择仍然保留
- preview 页面也跟随同一语言设置

### Content

- 前端拥有的英文文案不再散落硬编码
- 至少主工作区的壳层已完成双语
- 后端自由文本没有被前端乱翻译

### Formatting

- 时间展示跟随 locale
- 数字展示跟随 locale
- 状态标签不再只按英文 Title Case 生成

### Validation

- `npm run typecheck`
- `npm run lint`
- `NEXT_DIST_DIR=.next-prod npm run build`

### Manual smoke

至少人工检查：

- `/login`
- `/onboarding`
- `/`
- `/sources`
- `/changes`
- `/settings`
- `/privacy`
- `/terms`

分别在：

- `en`
- `zh-CN`

下看一遍。

## Backend Gaps To Record, Not Fix

UI agent 需要在 `OUTPUT.md` 明确记录这些不是前端可独立解决的问题：

- `decision_support.*` 仍是英文 backend-owned text
- `source_recovery.*` 中的人类可读句子仍是英文 backend-owned text
- API `detail` 文本仍是英文
- 用户语言偏好本轮只存在前端本地，不会跨设备同步

## Final Note

如果 UI agent 严格按这份 spec 做，当前阶段可以认为：

- “双语前端壳层” 是前端负责
- “真正完整的全站双语产品” 仍需要后端 phase 2

这轮不要越界去补 phase 2。
