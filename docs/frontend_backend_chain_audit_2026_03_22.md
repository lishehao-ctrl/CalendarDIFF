# Frontend/Backend Chain Audit 2026-03-22

## Scope

本轮在生产环境 `https://cal.shehao.app` 做了真实联调审计：

- 前端使用 Playwright 逐条点击真实按钮
- 后端同时监控 AWS `public-service` 容器日志
- 重点验证用户主路径是否真的打到后端、是否真的改变状态、以及页面是否正确回显

## 已验证通过的链路

这些链路已经在生产环境通过“前端点击 + 后端日志”双重确认：

- `Overview -> Open Sources`
- `Sources -> Canvas ICS detail -> Run sync`
- `Changes -> Edit then approve -> Preview changes`
- `Changes -> Reject`
- `Manual -> Create`
- `Manual -> Update`
- `Manual -> Delete`
- `Sources/connect/gmail -> Connect Gmail`

说明：

- `Manual` 的 smoke 数据已经在验证结束后删除，没有残留
- `Sources -> Canvas ICS detail -> Run sync` 现在能够自动从 `Queued` 收敛回 `Succeeded`

## 仍需要改进的点

### 1. `Changes` evidence 的 `after preview` 仍然会打 404

现象：

- `Changes` 页打开某些 item 时，console 仍会出现
  - `/api/backend/changes/{id}/evidence/after/preview -> 404`
- UI 虽然能降级到 raw / fallback 文案，不会直接阻塞主路径

影响：

- 会制造前端错误噪音
- 用户看到的是“Structured preview unavailable”，但并不知道这是数据缺失还是接口缺失

建议：

- 要么补齐 `after preview` 的真实后端能力
- 要么前端只在后端明确声明 `after preview` 可用时才发请求
- 不要继续保留“每次都请求，然后靠 404 降级”的模式

### 2. `Changes -> Approve` 的高风险删除链还没有在生产做最终验收

现状：

- 这轮只验证了较低风险的 `Reject`
- 当前唯一 pending item 属于 removed 类变更，`Approve` 会直接影响 live canonical state

影响：

- 目前还不能说“生产环境里 approve 删除链已完全验过”

建议：

- 准备一个低风险、可控、可回滚的 approve 样本
- 单独验证：
  - 前端按钮
  - `/changes/{id}/decisions`
  - canonical state 变化
  - 变更消失后的 queue / overview / source posture 是否一致

### 3. `Families` 写路径还没做生产复验

现状：

- 只验证了页面可达和 tab 切换
- 没有在生产上重跑：
  - family rename
  - raw type relink
  - suggestion apply

影响：

- `Families` 目前只能说“页面能打开”，还不能说“写路径已验收”

建议：

- 用一个最小课程样本重跑三条写链
- 每条都要同时确认：
  - 页面即时回显
  - 后端写请求
  - 再次刷新后的持久状态

### 4. `release_aws_main.sh` 已能重建容器，但校验还不够严格

现象：

- 这轮脚本已经升级为：
  - git sync
  - `docker compose up -d --build frontend public-service`
  - nginx / `health` / `login` 校验
- 但在容器刚启动时，`/health` 有过瞬时 `502`

影响：

- 当前脚本的 verify 还可能把“短暂启动窗口”与“真实失败”混在一起
- 同时 `curl` 校验也没有强制要求非 200 直接失败

建议：

- 对 `health` 增加短轮询重试
- 用严格状态码校验，而不是只打印响应文本
- 把“容器刚启动后的短暂 502”从“真实发布失败”里区分出来

### 5. `Source detail` 虽然已修成自动轮询，但手动 sync 期间仍可继续点 `Run sync`

现象：

- 当前页面在 active sync 未终结时仍显示可点击的 `Run sync`

影响：

- 用户可能连续触发多次手动 sync
- 即使后端可容忍，用户心智上也会觉得“不确定有没有点成功”

建议：

- active sync 非终态时禁用 `Run sync`
- 按当前 active request 明确显示：
  - 正在运行
  - 最近更新时间
  - 当前阶段

### 6. Gmail connect 页的状态语义已修正，但建议再补一个“为什么现在是 reconnect required”的更直白解释

现状：

- 现在页面已能正确显示 `Reconnect required`
- 但用户仍需要自己理解：
  - source 还在
  - mailbox access 已断
  - replay 不可信

建议：

- 增加一行更产品化的说明，例如：
  - “Source record still exists, but Gmail authorization has expired or been disconnected.”
- 让用户不用自己把 `source`、`oauth`、`replay` 三层概念拼起来

## 建议的后续顺序

建议按这个顺序继续收口：

1. 修 `Changes evidence after preview 404`
2. 验 `Changes -> Approve`
3. 验 `Families` 三条写路径
4. 强化 `release_aws_main.sh` 的健康校验
5. 禁用 active sync 期间重复点击 `Run sync`

## 当前结论

当前系统的主链路已经明显更稳：

- `Sources`
- `Changes` 的 preview / reject
- `Manual`
- Gmail OAuth 发起

都已经跑通并和后端日志对上。

剩余工作不再是“大面积断链”，而是：

- 个别接口残缺
- 高风险路径尚未最终验收
- 一些状态投影和发布细节还可以更严谨
