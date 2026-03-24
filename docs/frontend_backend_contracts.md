# Frontend/Backend Contracts

## Purpose

这份文档给前端/UI agent 一个直接可消费的后端 contract 对接表。

目标：

- 不再让前端根据英文自由文本猜语义
- 优先消费后端返回的 `*_code` / `*_params`
- 仅在 code 缺失时，才退回英文 `message`

## Consumption Rule

前端所有 backend-owned product copy 都按这个优先级处理：

1. 使用 `message_code` / `reason_code` / `impact_code` / 其他 code 字段
2. 使用对应的 `*_params`
3. 如果 code 不存在，再回退到后端返回的英文 `message`

不要：

- 基于英文 message 做字符串匹配翻译
- 自己猜 code 缺失时的业务语义
- 翻译业务数据字段或 evidence 原文

## Auth

### `GET /auth/session`

用户对象已包含：

- `language_code`

允许值：

- `en`
- `zh-CN`

前端用途：

- 未来可作为已登录用户的权威语言偏好

### Auth/API error detail codes

- `auth.authentication_required`
  - 英文默认：`Authentication required`
  - params: `{}`
- `auth.user_onboarding_incomplete`
  - 英文默认：由后端 onboarding status message 填充
  - params: `{}`
- `auth.notify_email_exists`
  - 英文默认：`notify_email already exists`
  - params: `{}`
- `auth.validation_error`
  - 英文默认：具体 validation message
  - params: `{}`
- `auth.invalid_credentials`
  - 英文默认：`invalid credentials`
  - params: `{}`

## Settings

### `GET /settings/profile`

用户对象已包含：

- `language_code`

### Settings/API error detail codes

- `settings.notify_email_cannot_be_cleared`
  - 英文默认：`notify_email cannot be cleared`
  - params: `{}`
- `settings.validation_error`
  - 英文默认：具体 validation message
  - params: `{}`
- `settings.channel_account_not_found`
  - 英文默认：`Channel account not found`
  - params: `{}`

### Channel account fields

Applies to:

- `GET /settings/channel-accounts`
- `POST /settings/channel-accounts`
- `DELETE /settings/channel-accounts/{account_id}`

Fields:

- `channel_type`
- `status`
- `verification_status`

Frontend guidance:

- treat Settings as the canonical management surface for external social channel bindings
- do not invent Telegram/WeChat webhook states beyond these fields

### Channel delivery audit fields

Applies to:

- `GET /settings/channel-deliveries`

Fields:

- `delivery_kind`
- `status`
- `summary_code`
- `detail_code`
- `cta_code`
- `origin_kind`
- `origin_label`

Frontend guidance:

- use this endpoint as the canonical recent outbound social delivery audit surface
- do not derive delivery history from approval tickets alone
- approval-ticket transitions now auto-write delivery audit rows even before real Telegram/Slack sending exists

## Sources

## A. `operator_guidance`

字段：

- `recommended_action`
- `severity`
- `reason_code`
- `message`
- `message_code`
- `message_params`

### Current `message_code` values

- `sources.operator_guidance.source_idle`
  - 英文默认：`No active sync is running. Continue reviewing changes.`
  - params: `{}`
- `sources.operator_guidance.sync_queued`
  - 英文默认：`Source sync is queued. Continue reviewing current changes; more changes may appear later.`
  - params: `{}`
- `sources.operator_guidance.sync_running`
  - 英文默认：`This source is still processing. You can review current changes, but new changes may still arrive.`
  - params: `{}`
- `sources.operator_guidance.sync_progress_stale`
  - 英文默认：`This source has not reported fresh progress recently. Wait for runtime recovery before making lane-changing decisions.`
  - params: `{}`
- `sources.operator_guidance.active_sync_failed`
  - 英文默认：`The active source sync failed. Investigate runtime health before trusting this lane to be current.`
  - params: `{}`
- `sources.operator_guidance.latest_sync_failed`
  - 英文默认：`The latest source sync failed. Investigate source/runtime health before trusting this lane to be current.`
  - params: `{}`

前端建议：

- `reason_code` 继续保留作逻辑判断
- `message_code` 用于最终用户文案

## B. `source_recovery`

字段：

- `trust_state`
- `impact_summary`
- `impact_code`
- `next_action`
- `next_action_label`
- `recovery_steps`
- `recovery_step_codes`

### Current `impact_code` values

- `sources.recovery.gmail.oauth_disconnected`
- `sources.recovery.ics.rebind_pending`
- `sources.recovery.gmail.runtime_failed`
- `sources.recovery.ics.runtime_failed`
- `sources.recovery.gmail.runtime_stalled`
- `sources.recovery.ics.runtime_stalled`
- `sources.recovery.baseline.running`
- `sources.recovery.baseline.review_required`
- `sources.recovery.gmail.active_sync`
- `sources.recovery.ics.active_sync`
- `sources.recovery.gmail.trusted`
- `sources.recovery.ics.trusted`

### Current `recovery_step_codes` values

- `sources.recovery.gmail.step.reconnect_mailbox`
- `sources.recovery.gmail.step.wait_for_sync`
- `sources.recovery.ics.step.confirm_feed_settings`
- `sources.recovery.ics.step.run_sync_after_update`
- `sources.recovery.runtime_failed.step.retry_sync`
- `sources.recovery.runtime_failed.step.investigate_if_repeat`
- `sources.recovery.runtime_stalled.step.wait`
- `sources.recovery.runtime_stalled.step.resume_after_progress`
- `sources.recovery.baseline.running.step.wait`
- `sources.recovery.baseline.running.step.review_after_import`
- `sources.recovery.baseline.review_required.step.finish_initial_review`
- `sources.recovery.baseline.review_required.step.use_replay_after_review`
- `sources.recovery.active_sync.step.review_current_changes`
- `sources.recovery.active_sync.step.expect_more_after_completion`

前端建议：

- `impact_summary` 仍可作为英文 fallback
- `impact_code` 才是双语主入口
- `next_action_label` 目前仍是 backend-owned英文，暂时保留 fallback

## C. Sources/API error detail codes

- `sources.create.gmail_source_exists`
- `sources.create.ics_source_exists`
- `sources.validation_error`
- `sources.invalid_status_filter`
- `sources.patch.validation_error`
- `sources.sync.monitoring_window_update_pending`
- `sources.sync.monitoring_not_started`
- `sources.sync.source_inactive`
- `sources.sync.request_not_found`

全部默认 params：

- `{}`

例外：

- `sources.create.gmail_source_exists`
  - 还会带 `existing_source_id`
- `sources.create.ics_source_exists`
  - 还会带 `existing_source_id`

## Onboarding

## A. `GET /onboarding/status`

字段：

- `message`
- `message_code`
- `message_params`
- `source_health.message`
- `source_health.message_code`
- `source_health.message_params`

### Current stage `message_code` values

- `onboarding.stage.needs_canvas_ics`
- `onboarding.stage.needs_gmail_or_skip`
- `onboarding.stage.needs_monitoring_window`
- `onboarding.stage.ready`

### Current source health `message_code` values

- `onboarding.source_health.disconnected`
- `onboarding.source_health.attention`
- `onboarding.source_health.healthy`

params currently:

- `{}`

## B. Onboarding/API error detail codes

- `onboarding.notify_email_managed_by_auth`
- `onboarding.canvas_required_before_monitoring_window`
- `onboarding.canvas_ics.validation_error`
- `onboarding.gmail_oauth.unavailable`
- `onboarding.monitoring_window.validation_error`

params currently:

- `{}`

## Changes

## A. `decision_support`

字段：

- `why_now`
- `why_now_code`
- `suggested_action_reason`
- `suggested_action_reason_code`
- `risk_summary`
- `risk_summary_code`
- `key_fact_items`
- `outcome_preview_codes`

### Current `why_now_code` values

- `changes.removed.why_now`
- `changes.due_changed.why_now`
- `changes.baseline_created.why_now`
- `changes.created.why_now`

### Current `suggested_action_reason_code` values

- `changes.removed.suggested_action_reason`
- `changes.due_changed.suggested_action_reason.approve`
- `changes.due_changed.suggested_action_reason.edit`
- `changes.baseline_created.suggested_action_reason`

## Agent

## A. Proposal lifecycle fields

Applies to:

- `GET /agent/proposals`
- `GET /agent/proposals/{proposal_id}`
- all proposal-create endpoints

Fields:

- `owner_user_id`
- `origin_kind`
- `origin_label`
- `lifecycle_code`
- `execution_mode`
- `execution_mode_code`
- `next_step_code`
- `can_create_ticket`

### Current `lifecycle_code` values

- `agents.proposal.lifecycle.open`
- `agents.proposal.lifecycle.accepted`
- `agents.proposal.lifecycle.rejected`
- `agents.proposal.lifecycle.expired`
- `agents.proposal.lifecycle.superseded`

### Current `execution_mode_code` values

- `agents.proposal.execution_mode.approval_ticket_required`
- `agents.proposal.execution_mode.web_only`

### Current `next_step_code` values

- `agents.proposal.next_step.create_ticket`
- `agents.proposal.next_step.open_web_flow`
- `agents.proposal.next_step.completed`
- `agents.proposal.next_step.dismissed`
- `agents.proposal.next_step.expired`
- `agents.proposal.next_step.superseded`

Frontend guidance:

- use these fields instead of inferring state from `status + suggested_payload.kind`
- `can_create_ticket` is the canonical execution affordance gate
- `origin_kind/origin_label` is the canonical audit source for where the proposal came from

## B. Approval ticket lifecycle fields

Applies to:

- `GET /agent/approval-tickets`
- `GET /agent/approval-tickets/{ticket_id}`
- create / confirm / cancel ticket responses

Fields:

- `owner_user_id`
- `origin_kind`
- `origin_label`
- `lifecycle_code`
- `next_step_code`
- `confirm_summary_code`
- `cancel_summary_code`
- `transition_message_code`
- `social_safe_cta_code`
- `can_confirm`
- `can_cancel`
- `last_transition_kind`
- `last_transition_label`

### Current `lifecycle_code` values

- `agents.ticket.lifecycle.open`
- `agents.ticket.lifecycle.executed`
- `agents.ticket.lifecycle.canceled`
- `agents.ticket.lifecycle.expired`
- `agents.ticket.lifecycle.failed`

### Current `next_step_code` values

- `agents.ticket.next_step.confirm_or_cancel`
- `agents.ticket.next_step.completed`
- `agents.ticket.next_step.canceled`
- `agents.ticket.next_step.expired`
- `agents.ticket.next_step.investigate_failure`

Frontend guidance:

- use `can_confirm` / `can_cancel` as the canonical button gate
- do not infer confirm/cancel availability only from `status`
- use `origin_kind/origin_label` for ticket creation audit
- use `last_transition_kind/last_transition_label` for latest state transition audit
- use `transition_message_code` as the canonical status-copy entrypoint for social cards
- use `social_safe_cta_code` only when rendering low-risk confirm actions outside the web app

## C. Recent agent activity fields

Applies to:

- `GET /agent/activity/recent`

Fields:

- `owner_user_id`
- `lifecycle_code`
- `next_step_code`
- `origin_kind`
- `origin_label`
- `execution_mode`
- `execution_mode_code`
- `confirm_summary_code`
- `cancel_summary_code`
- `transition_message_code`
- `social_safe_cta_code`
- `can_create_ticket`
- `can_confirm`
- `can_cancel`
- `last_transition_kind`
- `last_transition_label`

Frontend guidance:

- this endpoint is the canonical recent-agent-history surface
- use `summary_code` / `detail_code` / lifecycle fields together
- do not rebuild recent activity by joining proposals and tickets in the client
- use `origin_*` and `last_transition_*` fields for audit timeline UI
- for ticket rows, use transition/cta codes instead of deriving social card copy in the client
- `changes.created.suggested_action_reason`

### Current `risk_summary_code` values

- `changes.removed.risk_summary`
- `changes.due_changed.risk_summary`
- `changes.baseline_created.risk_summary`
- `changes.created.risk_summary`

### Current `outcome_preview_codes`

Removed:

- `changes.removed.outcome.approve`
- `changes.removed.outcome.reject`
- `changes.removed.outcome.edit`

Due changed:

- `changes.due_changed.outcome.approve`
- `changes.due_changed.outcome.reject`
- `changes.due_changed.outcome.edit`

Baseline created:

- `changes.baseline_created.outcome.approve`
- `changes.baseline_created.outcome.reject`
- `changes.baseline_created.outcome.edit`

Created:

- `changes.created.outcome.approve`
- `changes.created.outcome.reject`
- `changes.created.outcome.edit`

### `key_fact_items`

前端应优先使用：

- `code`
- `value`

当前 `code` 值：

- `course`
- `item`
- `proposed_time`
- `primary_source`
- `time_change`
- `effective_time`
- `current_time`

不要再从英文 `key_facts` 文本二次解析。

## B. Workbench summary / workspace posture

### `GET /changes/summary`

字段：

- `sources.message`
- `sources.message_code`
- `sources.message_params`
- `recommended_action_reason`
- `recommended_action_reason_code`
- `recommended_action_reason_params`
- `workspace_posture.next_action.reason`
- `workspace_posture.next_action.reason_code`
- `workspace_posture.next_action.reason_params`

### Current summary `recommended_action_reason_code`

- `workbench.summary.runtime_attention_required`
- `workbench.summary.baseline_review_pending`
- `workbench.summary.changes_pending`
- `workbench.summary.family_governance_pending`
- `workbench.summary.all_clear`

### Current `workspace_posture.next_action.reason_code`

- `workspace_posture.next_action.sources_attention_required`
- `workspace_posture.next_action.baseline_import_running`
- `workspace_posture.next_action.initial_review_pending`
- `workspace_posture.next_action.replay_changes_pending`
- `workspace_posture.next_action.families_attention_required`
- `workspace_posture.next_action.manual_repairs_active`
- `workspace_posture.next_action.monitoring_live_default`

### Params

Some codes carry counts:

- `workbench.summary.baseline_review_pending`
  - `{ pending_count }`
- `workbench.summary.changes_pending`
  - `{ pending_count }`
- `workbench.summary.family_governance_pending`
  - `{ attention_count }`
- `workspace_posture.next_action.initial_review_pending`
  - `{ pending_count }`
- `workspace_posture.next_action.replay_changes_pending`
  - `{ pending_count }`
- `workspace_posture.next_action.families_attention_required`
  - `{ attention_count }`
- `workspace_posture.next_action.manual_repairs_active`
  - `{ active_event_count }`

## Suggested frontend integration order

1. `language_code`
   - use as account-level locale source once UI switch is stable
2. `Sources`
   - consume `operator_guidance.message_code`
   - consume `source_recovery.impact_code`
3. `Onboarding`
   - consume `message_code` and `source_health.message_code`
4. `Changes`
   - consume decision support codes
5. `Overview`
   - consume workbench summary / workspace posture codes

## Fallback rule

如果任何 code 尚未在前端字典中实现：

- 显示后端 `message`
- 不要隐藏这条信息

即：

- code-first
- message fallback
- never blank
