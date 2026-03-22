你负责 CalendarDIFF 的前端产品层实现，只做 UI，不改后端语义或数据库逻辑。

这次不是做新页面集合，而是把现有工作流的最后一层产品心智闭环做完整。

本轮只围绕三组真相：

- `workspace_posture`
- `change_decision_support`
- `source_recovery`

你的任务是：

1. 让用户在 `Overview` 一眼知道自己现在处于：
   - baseline import
   - initial review
   - monitoring live
   - attention required
2. 让 `Initial Review` 具有明确完成感，而不是处理完最后一条后无反馈
3. 让 `Changes` 先回答：
   - 为什么现在要我处理
   - 建议我怎么处理
   - 风险在哪
4. 让 `Sources` 先回答：
   - 这条 source 还可信吗
   - 影响范围是什么
   - 下一步该做什么

实现约束：

- 只改前端
- 不改 API 语义
- 不前端硬猜后端没有显式返回的业务字段
- 如果后端字段暂时不存在，只能明确标记缺口，不能自己编造 recommendation 或 trust model
- 不要把 runtime/internal stage 文本直接当首要用户文案

页面层优先级：

1. `Overview`
   - phase headline
   - 一个明确 CTA
2. `Initial Review`
   - progress
   - completion state
3. `Changes`
   - decision support block
   - action consequence copy
4. `Sources`
   - trust state
   - impact summary
   - next action

信息层级要求：

- primary: 产品心智
- secondary: 支撑解释
- tertiary: technical details

如果需要字段、页面职责、接口新增项、页面信息层级或 rollout 顺序，以 `SPEC.md` 为准。
