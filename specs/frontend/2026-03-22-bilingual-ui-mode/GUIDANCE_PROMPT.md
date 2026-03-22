你负责 CalendarDIFF 的前端双语模式实现，只做前端，不改后端 contract、数据库、运行时语义。

这轮目标不是“把所有用户可见文本一次性完全双语化”，而是先把正确的前端 i18n 基石搭起来。

你要做的是：

1. 建立一套轻量前端 i18n 基础设施
   - locale provider
   - dictionaries
   - locale hook
   - 本地持久化
2. 在 `Settings` 提供 `English / 中文` 切换
3. 把前端拥有的页面壳层文案全部收进字典
4. 让 formatter 跟随 locale，而不是写死 `en-US`
5. 让 preview 页面也复用同一套双语机制

本轮严格约束：

- 不改 API shape
- 不加数据库字段
- 不做多语言路由
- 不引入新 i18n 库
- 不翻译业务数据或 evidence 原文
- 不根据英文后端 message 做字符串匹配翻译
- 不前端伪造“后端已经双语”

必须保留原样的内容：

- `event_name`
- `family_name`
- `raw_type`
- `course_display`
- Gmail snippet
- ICS description/title
- backend-owned decision support / recovery / error detail

你可以翻译的内容：

- 页面标题
- section 标题
- CTA
- loading / empty / error state
- banner
- auth / onboarding / legal 页面壳层
- sidebar labels
- formatter 的状态标签与日期数字展示

语言来源规则：

1. localStorage 中用户手动选择
2. 浏览器语言
3. 默认 `en`

只支持：

- `en`
- `zh-CN`

页面优先级：

1. `Settings`
2. `App shell`
3. `Login / Register / Onboarding`
4. `Overview / Sources / Changes / Families / Manual`
5. `Legal / Preview`

实现时如果遇到“这句是后端返回的英文自由文本，要不要翻”，答案是：

- 不翻
- 原样显示
- 在 `OUTPUT.md` 记录为 backend-owned language gap

如果需要页面范围、非目标、落地顺序、验收标准，以 `SPEC.md` 为准。
