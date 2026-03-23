# Observed Label / Canonical Family UI Spec

## Summary

这轮前端的目标不是“把 Families 做得更像数据库面板”，而是把它变成一个用户可理解的治理工作台。

页面必须帮助用户一眼回答：

1. 系统原始看到了什么词
2. 这个词现在归到哪个稳定类别
3. 我改这个映射，会影响哪里

因此 UI 的核心改造方向是：

- 从 `raw type / family` 术语切换为产品词
- 从 edit-first 切换为 impact-first
- 从直接 relink 切换为 preview-then-confirm

## Core Decisions

### 1. 主产品词改为

- `Observed label / 原始标签`
- `Canonical family / 稳定类别`

在页面中：

- 不再把 `Raw Types` 作为主标题
- 可以保留内部变量名，但用户不再先看到它

### 2. Families 页每条映射都要显示影响范围

最低要显示：

- 影响多少事件
- 影响多少 pending changes
- 会影响后续同类导入

### 3. relink 必须先 preview，再确认

用户不能直接在下拉框里改完就提交。

必须先看到：

- 当前 `Observed label -> Canonical family`
- 改后 `Observed label -> Canonical family`
- 会影响的 event / change 示例

### 4. Changes 页要解释 mapping 对 proposal 的影响

在 `Changes` detail 中补一块轻量上下文：

- `Observed label`
- `Current family`
- mapping explanation

例如：

- `Observed label: write-up`
- `Current family: Problem Set`
- `This change looks like this because the observed label is currently mapped to Problem Set.`

## Page changes

## A. Families list

当前：

- 更像 canonical family editor 列表

目标：

- 默认先显示治理意义，而不是字段编辑

每个 family card 至少显示：

- `Canonical family`
- 课程
- `Observed labels: N`
- `Active events: N`
- `Pending changes: N`

## B. Observed labels tab

当前：

- 主要是 `raw type` 列表 + move 下拉框

目标：

- 变成清晰的映射表

每一行：

- 左：`Observed label`
- 右：`Canonical family`
- 下方：impact summary

动作：

- 主按钮：
  - `Move to Project`
  - `Keep in Problem Set`

不要让用户直接思考：

- `family_id`
- `raw_type_id`

## C. Relink preview sheet

当用户准备变更映射时，弹出 preview：

- headline:
  - `Move "write-up" to Project?`
- before / after:
  - `Current family: Problem Set`
  - `After move: Project`
- impact:
  - `4 active events`
  - `2 pending changes`
  - `future imports with "write-up" will follow Project`
- samples:
  - affected events
  - affected change proposals

主 CTA：

- `Confirm move to Project`

secondary CTA：

- `Keep in Problem Set`

## D. Changes detail mapping block

在 `Decision support` 下面或旁边加一个轻量 mapping block：

- `Observed label`
- `Current family`
- 一句解释
- `Open Families` CTA

这块只在后端提供 mapping projection 时显示。

## Copy guidance

固定解释文案建议：

- `The system keeps the source's original label, then maps it into your chosen canonical family.`
- `系统先保留来源里的原始叫法，再把它归入你定义的稳定类别。`

固定例子建议：

- `proj`, `project`, `final project` -> `Project`

## Out of scope

- 不改后端语义
- 不翻译 evidence 原文
- 不改 `Manual` / `Sources` 主结构
- 不在这轮重做整个 `Families` 路由树

## Acceptance Criteria

- 用户在 `Families` 页第一页就能看到“原始标签 -> 稳定类别”的映射关系
- 用户能在提交 relink 前看到影响范围 preview
- `Changes` detail 能显示 mapping explanation
- 页面文案不再把内部 `raw type` 当主产品语言

## Validation

- `npm run typecheck`
- `npm run lint`
- `NEXT_DIST_DIR=.next-prod npm run build`

手工 smoke：

- `Families` list
- `Observed labels` tab
- relink preview
- `Changes` detail mapping block
