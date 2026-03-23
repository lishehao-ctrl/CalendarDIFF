你负责 CalendarDIFF 的前端产品层实现，只做 UI，不改后端语义或数据库逻辑。

这次的目标不是重新做视觉，而是把用户心智从“第一次导入和后续变化混在一起”改成两条清晰工作流：

- `Baseline import`
- `Replay review`

请把自己当成产品层实现者，而不是样式执行者。你的任务是：

1. 让用户一眼知道现在是在：
   - 建立初始基线
   - 还是处理后续变化
2. 不再让普通 `Changes` 承担第一次导入的大量 created items
3. 让 `Sources` 解释 source bootstrap/import 的结果
4. 给阶段性 baseline 审核一个单独心智：
   - `Initial Review`
   - 或 `Import Review`

实现约束：

- 只改前端
- 不改 API 语义
- 不前端硬猜后端本来没有返回的字段
- 如果后端字段不够，直接列缺口，不要自己重建业务逻辑

页面层要求：

- `Overview`
  - 必须能区分：
    - `Initial Review`
    - 普通 `Changes`
  - CTA 不要再默认总是 `Open Changes`
- `Sources`
  - 必须能展示 bootstrap/import 结果摘要
  - 至少预留这些信息位：
    - imported
    - needs review
    - ignored
    - conflicts
- `Changes`
  - 只承接后续变化的心智
  - 不再把 baseline import 当成日常 pending queue
- `Initial Review`
  - 作为阶段性工作台
  - 不做永久一级导航

交互原则：

- 用户第一次接 source 后，默认应该理解成“系统先帮我建立基线”
- 用户日常再打开 app，才进入“今天有哪些变化要确认”
- 不要把 bootstrap summary 做成开发者日志面板
- 不要暴露 runtime/internal 名词

你优先交付：

1. `Overview` 的 lane 区分和 CTA
2. `Sources` 的 bootstrap/import 解释层
3. `Initial Review` 页面原型或 preview
4. `Changes` 的角色收敛

如果需要具体字段、行为边界、页面职责和 rollout 顺序，以 `SPEC.md` 为准。
