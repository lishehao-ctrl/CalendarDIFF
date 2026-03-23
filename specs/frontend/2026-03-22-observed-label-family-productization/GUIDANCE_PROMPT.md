你负责 CalendarDIFF 的前端 Families/Changes productization，只做 UI，不改后端语义。

目标：

- 用户不需要理解 `raw type / family` 这两个内部术语
- 用户一眼就能理解：
  - 原始看到了什么词
  - 现在归到哪个稳定类别
  - 改这个映射会影响哪里

你要做的事：

1. 把主产品语言改成：
   - `Observed label / 原始标签`
   - `Canonical family / 稳定类别`
2. `Families` 页默认显示 impact-first 信息
3. relink 改成 preview-then-confirm
4. `Changes` detail 补 mapping explanation block

严格约束：

- 不自己猜后端还没返回的数据
- 如果 preview / impact 字段还没到位，只能明确标缺口，不要前端伪造
- 不把 DB ids 暴露成主交互语言

实现优先级：

1. Families observed-label list
2. relink preview sheet
3. Changes mapping block

完成后把页面改动、缺口和 smoke 结果写进 `OUTPUT.md`。
