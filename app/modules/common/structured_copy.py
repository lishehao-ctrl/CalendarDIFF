from __future__ import annotations

import re
from collections.abc import Iterable

from app.modules.common.language import DEFAULT_LANGUAGE_CODE, LanguageCodeLiteral, normalize_language_code

Primitive = str | int | float | bool | None

_VAR_PATTERN = re.compile(r"\{(\w+)\}")

_CATALOG: dict[LanguageCodeLiteral, dict[str, str]] = {
    "en": {
        "workbench.summary.runtime_attention_required": "Source runtime needs attention before relying on lane state to be current.",
        "workbench.summary.baseline_review_pending": "{pending_count} baseline import items still need initial review before daily replay becomes the default workflow.",
        "workbench.summary.changes_pending": "{pending_count} pending change proposals are waiting for review decisions.",
        "workbench.summary.family_governance_pending": "Family or observed-label governance items need attention.",
        "workbench.summary.all_clear": "No immediate lane action is required.",
        "workspace_posture.next_action.sources_attention_required.label": "Open Sources",
        "workspace_posture.next_action.sources_attention_required.reason": "{message}",
        "workspace_posture.next_action.baseline_import_running.label": "Open Sources",
        "workspace_posture.next_action.baseline_import_running.reason": "At least one source is still building its baseline import.",
        "workspace_posture.next_action.initial_review_pending.label": "Open Initial Review",
        "workspace_posture.next_action.initial_review_pending.reason": "{pending_count} baseline items still need review before monitoring is fully live.",
        "workspace_posture.next_action.replay_changes_pending.label": "Open Replay Review",
        "workspace_posture.next_action.replay_changes_pending.reason": "{pending_count} replay changes are waiting for review decisions.",
        "workspace_posture.next_action.families_attention_required.label": "Open Families",
        "workspace_posture.next_action.families_attention_required.reason": "Naming governance still needs attention.",
        "workspace_posture.next_action.manual_repairs_active.label": "Open Manual",
        "workspace_posture.next_action.manual_repairs_active.reason": "Fallback manual repairs are still active.",
        "workspace_posture.next_action.monitoring_live_default.label": "Open Replay Review",
        "workspace_posture.next_action.monitoring_live_default.reason": "Monitoring is live. Replay Review is the main daily workspace.",

        "changes.removed.why_now": "The latest {source_label} observation no longer supports this live item.",
        "changes.removed.suggested_action_reason": "Removing a live item changes canonical state and should be confirmed carefully.",
        "changes.removed.risk_summary": "Approving will remove the current live deadline from the workspace.",
        "changes.removed.outcome.approve": "Remove the live item from the workspace.",
        "changes.removed.outcome.reject": "Keep the current live item unchanged.",
        "changes.removed.outcome.edit": "Adjust the canonical item before deciding whether to remove it.",
        "changes.due_changed.why_now": "A new {source_label} signal changed the effective time for an existing item.",
        "changes.due_changed.suggested_action_reason.approve": "The item identity looks stable and the proposal mainly changes the effective due time.",
        "changes.due_changed.suggested_action_reason.edit": "The item probably needs an update, but the proposed time should be corrected before approval.",
        "changes.due_changed.risk_summary": "Approving will update the live deadline shown in the workspace.",
        "changes.due_changed.outcome.approve": "Update the live deadline to the proposed time.",
        "changes.due_changed.outcome.reject": "Keep the current live deadline unchanged.",
        "changes.due_changed.outcome.edit": "Correct the proposed time before updating the live deadline.",
        "changes.baseline_created.why_now": "This baseline item was imported from {source_label} and still needs confirmation before monitoring is fully live.",
        "changes.baseline_created.suggested_action_reason": "If the item identity and time look right, approving it helps finish Initial Review faster.",
        "changes.baseline_created.risk_summary": "Approving adds this item into the live baseline used for future replay detection.",
        "changes.baseline_created.outcome.approve": "Add this item into the live baseline.",
        "changes.baseline_created.outcome.reject": "Leave this item out of the live baseline.",
        "changes.baseline_created.outcome.edit": "Correct the imported details before adding the item into the live baseline.",
        "changes.created.why_now": "A new {source_label} signal looks like a newly announced grade-relevant item.",
        "changes.created.suggested_action_reason": "If the item and time look correct, approving it makes the new item live immediately.",
        "changes.created.risk_summary": "Approving will add a new live item to the workspace.",
        "changes.created.outcome.approve": "Create a new live item in the workspace.",
        "changes.created.outcome.reject": "Ignore this proposed new item.",
        "changes.created.outcome.edit": "Correct the item details before creating the live item.",
        "changes.key_fact.course": "Course: {value}",
        "changes.key_fact.item": "Item: {value}",
        "changes.key_fact.proposed_time": "Proposed time: {value}",
        "changes.key_fact.primary_source": "Primary source: {value}",
        "changes.key_fact.time_change": "Time change: {value}",
        "changes.key_fact.effective_time": "Effective time: {value}",
        "changes.key_fact.current_time": "Current time: {value}",

        "workbench.sources_summary.sources_missing": "No active sources are connected yet.",
        "sources.operator_guidance.sync_queued": "Source sync is queued. Continue reviewing current changes; more changes may appear later.",
        "sources.operator_guidance.sync_progress_stale": "This source has not reported fresh progress recently. Wait for runtime recovery before making lane-changing decisions.",
        "sources.operator_guidance.sync_running": "This source is still processing. You can review current changes, but new changes may still arrive.",
        "sources.operator_guidance.active_sync_failed": "The active source sync failed. Investigate runtime health before trusting this lane to be current.",
        "sources.operator_guidance.latest_sync_failed": "The latest source sync failed. Investigate source/runtime health before trusting this lane to be current.",
        "sources.operator_guidance.source_idle": "No active sync is running. Continue reviewing changes.",

        "sources.recovery.gmail.oauth_disconnected": "New Gmail-based changes may be missing until the mailbox is reconnected.",
        "sources.recovery.ics.rebind_pending": "Canvas ICS needs updated monitoring settings before new calendar updates can be trusted.",
        "sources.recovery.gmail.runtime_failed": "The latest Gmail sync failed, so recent email-based changes may be missing.",
        "sources.recovery.ics.runtime_failed": "The latest Canvas ICS sync failed, so recent calendar changes may be missing.",
        "sources.recovery.source.runtime_failed": "The latest source sync failed, so recent changes may be missing.",
        "sources.recovery.gmail.runtime_stalled": "The current Gmail sync has stopped reporting fresh progress, so new email-based changes are not trustworthy yet.",
        "sources.recovery.ics.runtime_stalled": "The current Canvas ICS sync has stopped reporting fresh progress, so new calendar changes are not trustworthy yet.",
        "sources.recovery.source.runtime_stalled": "The current source sync has stopped reporting fresh progress, so new changes are not trustworthy yet.",
        "sources.recovery.baseline.running": "Baseline import is still building this source before steady-state monitoring begins.",
        "sources.recovery.baseline.review_required": "Baseline import finished, but Initial Review still has items waiting before this source is fully trusted.",
        "sources.recovery.gmail.active_sync": "New Gmail-based changes may still arrive while this sync is running.",
        "sources.recovery.ics.active_sync": "Calendar-backed changes may still update while this sync is running.",
        "sources.recovery.source.active_sync": "New changes may still arrive while this sync is running.",
        "sources.recovery.gmail.trusted": "This mailbox is connected and contributing to live monitoring.",
        "sources.recovery.ics.trusted": "This calendar feed is connected and contributing to live monitoring.",
        "sources.recovery.source.trusted": "This source is connected and contributing to live monitoring.",
        "sources.recovery.next_action.reconnect_gmail": "Reconnect Gmail",
        "sources.recovery.next_action.update_ics": "Update Canvas ICS",
        "sources.recovery.next_action.retry_sync": "Retry sync",
        "sources.recovery.next_action.wait_for_runtime": "Wait for runtime",
        "sources.recovery.next_action.wait_for_baseline": "Wait for baseline import",
        "sources.recovery.next_action.finish_initial_review": "Finish Initial Review",
        "sources.recovery.next_action.wait_for_sync": "Wait for sync",
        "sources.recovery.next_action.none": "No action needed",
        "sources.recovery.gmail.step.reconnect_mailbox": "Reconnect the mailbox to restore intake.",
        "sources.recovery.gmail.step.wait_for_sync": "Wait for the next sync to finish before trusting new email-backed changes.",
        "sources.recovery.ics.step.confirm_feed_settings": "Open the Canvas ICS connection flow and confirm the current feed settings.",
        "sources.recovery.ics.step.run_sync_after_update": "Run another sync after saving the updated link.",
        "sources.recovery.runtime_failed.step.retry_sync": "Retry the source sync.",
        "sources.recovery.runtime_failed.step.investigate_if_repeat": "If the next sync also fails, investigate the source connection before trusting new changes.",
        "sources.recovery.runtime_stalled.step.wait": "Let the current runtime work finish or recover.",
        "sources.recovery.runtime_stalled.step.resume_after_progress": "Only trust new changes after progress starts moving again or the sync completes.",
        "sources.recovery.baseline.running.step.wait": "Wait for the initial import to complete.",
        "sources.recovery.baseline.running.step.review_after_import": "Review any baseline items before treating this source as fully live.",
        "sources.recovery.baseline.review_required.step.finish_initial_review": "Finish Initial Review for this source.",
        "sources.recovery.baseline.review_required.step.use_replay_after_review": "After that, use Replay Review for day-to-day change handling.",
        "sources.recovery.active_sync.step.review_current_changes": "Current changes can still be reviewed.",
        "sources.recovery.active_sync.step.expect_more_after_completion": "Expect more changes to appear after the active sync completes.",

        "agents.context.workspace.baseline_review_pending": "Baseline import review is not finished yet.",
        "agents.context.change_already_reviewed": "This change has already been reviewed.",
        "agents.context.gmail_oauth_not_connected": "Gmail is not currently connected.",
        "agents.context.family.pending_raw_type_suggestions": "{pending_count} observed-label suggestions still need review.",
        "agents.context.family.review_family_detail": "{canonical_label} is ready for canonical label and relink review.",
        "agents.context.change.action.approve": "Approve change",
        "agents.context.change.action.reject": "Reject change",
        "agents.context.change.action.edit": "Edit before approval",
        "agents.context.change.action.review_carefully": "Review carefully",
        "agents.context.source.action.continue_review": "Continue review",
        "agents.context.source.action.continue_review_with_caution": "Continue review with caution",
        "agents.context.source.action.wait_for_runtime": "Wait for runtime",
        "agents.context.source.action.investigate_runtime": "Investigate runtime",
        "agents.lane.sources": "Sources",
        "agents.lane.initial_review": "Initial Review",
        "agents.lane.changes": "Replay Review",
        "agents.lane.families": "Families",
        "agents.lane.manual": "Manual",

        "agents.proposals.change_decision.approve.summary": "Approve this change in {lane_label}.",
        "agents.proposals.change_decision.reject.summary": "Reject this change in {lane_label}.",
        "agents.proposals.change_decision.edit.summary": "Open web edit flow before approving this change in {lane_label}.",
        "agents.proposals.change_decision.review_carefully.summary": "Review this high-risk change carefully in {lane_label}.",
        "agents.proposals.source_recovery.reconnect_gmail.summary": "Reconnect {provider_label} before trusting this source again.",
        "agents.proposals.source_recovery.retry_sync.summary": "Run another sync for {provider_label}.",
        "agents.proposals.source_recovery.update_ics.summary": "Update {provider_label} settings before the next sync.",
        "agents.proposals.source_recovery.wait.summary": "Wait for {provider_label} runtime progress before taking further action.",
    },
    "zh-CN": {
        "workbench.summary.runtime_attention_required": "在依赖当前 lane 状态之前，先处理来源运行侧的问题。",
        "workbench.summary.baseline_review_pending": "还有 {pending_count} 条基线导入项目需要先完成初始审核，日常回放工作流才会成为默认入口。",
        "workbench.summary.changes_pending": "还有 {pending_count} 条待处理变更提议在等待审核决定。",
        "workbench.summary.family_governance_pending": "标准归类或观察标签治理仍有待处理项。",
        "workbench.summary.all_clear": "当前没有必须立即处理的 lane 动作。",
        "workspace_posture.next_action.sources_attention_required.label": "打开来源",
        "workspace_posture.next_action.sources_attention_required.reason": "{message}",
        "workspace_posture.next_action.baseline_import_running.label": "打开来源",
        "workspace_posture.next_action.baseline_import_running.reason": "至少有一个来源仍在建立基线导入。",
        "workspace_posture.next_action.initial_review_pending.label": "打开初始审核",
        "workspace_posture.next_action.initial_review_pending.reason": "还有 {pending_count} 条基线项目需要审核，监测才会正式进入日常模式。",
        "workspace_posture.next_action.replay_changes_pending.label": "打开回放审核",
        "workspace_posture.next_action.replay_changes_pending.reason": "还有 {pending_count} 条回放变更在等待审核。",
        "workspace_posture.next_action.families_attention_required.label": "打开 Families",
        "workspace_posture.next_action.families_attention_required.reason": "命名治理仍然需要处理。",
        "workspace_posture.next_action.manual_repairs_active.label": "打开手动",
        "workspace_posture.next_action.manual_repairs_active.reason": "手动兜底项仍然处于启用状态。",
        "workspace_posture.next_action.monitoring_live_default.label": "打开回放审核",
        "workspace_posture.next_action.monitoring_live_default.reason": "监测已进入日常模式。回放审核是主要的日常工作区。",

        "changes.removed.why_now": "最新的 {source_label} 观察结果不再支持这条实时项目。",
        "changes.removed.suggested_action_reason": "移除一条实时项目会改变标准状态，因此需要谨慎确认。",
        "changes.removed.risk_summary": "通过后会把当前实时截止时间从工作区中移除。",
        "changes.removed.outcome.approve": "从工作区中移除这条实时项目。",
        "changes.removed.outcome.reject": "保留当前实时项目不变。",
        "changes.removed.outcome.edit": "先调整标准项目，再决定是否移除。",
        "changes.due_changed.why_now": "新的 {source_label} 信号改变了现有项目的实际时间。",
        "changes.due_changed.suggested_action_reason.approve": "项目身份看起来稳定，这次提议主要是在调整实际截止时间。",
        "changes.due_changed.suggested_action_reason.edit": "项目可能确实需要更新，但在通过前应该先修正提议时间。",
        "changes.due_changed.risk_summary": "通过后会更新工作区里显示的实时截止时间。",
        "changes.due_changed.outcome.approve": "把实时截止时间更新为提议的时间。",
        "changes.due_changed.outcome.reject": "保留当前实时截止时间不变。",
        "changes.due_changed.outcome.edit": "先修正提议时间，再更新实时截止时间。",
        "changes.baseline_created.why_now": "这条基线项目来自 {source_label} 的首次导入，在监测正式进入日常模式前仍需确认。",
        "changes.baseline_created.suggested_action_reason": "如果项目身份和时间都看起来正确，尽快通过有助于完成初始审核。",
        "changes.baseline_created.risk_summary": "通过后会把这条项目加入后续回放检测使用的实时基线。",
        "changes.baseline_created.outcome.approve": "把这条项目加入实时基线。",
        "changes.baseline_created.outcome.reject": "不把这条项目加入实时基线。",
        "changes.baseline_created.outcome.edit": "先修正导入内容，再把它加入实时基线。",
        "changes.created.why_now": "新的 {source_label} 信号看起来像一条新出现的成绩相关项目。",
        "changes.created.suggested_action_reason": "如果项目和时间都正确，尽快通过会让新项目立即进入实时状态。",
        "changes.created.risk_summary": "通过后会在工作区里新增一条实时项目。",
        "changes.created.outcome.approve": "在工作区里创建一条新的实时项目。",
        "changes.created.outcome.reject": "忽略这条新项目提议。",
        "changes.created.outcome.edit": "先修正项目细节，再创建实时项目。",
        "changes.key_fact.course": "课程：{value}",
        "changes.key_fact.item": "项目：{value}",
        "changes.key_fact.proposed_time": "提议时间：{value}",
        "changes.key_fact.primary_source": "主来源：{value}",
        "changes.key_fact.time_change": "时间变化：{value}",
        "changes.key_fact.effective_time": "生效时间：{value}",
        "changes.key_fact.current_time": "当前时间：{value}",

        "workbench.sources_summary.sources_missing": "当前还没有任何已连接的活跃来源。",
        "sources.operator_guidance.sync_queued": "来源同步已进入队列。你可以继续审核当前变更，但稍后可能还会出现新的变更。",
        "sources.operator_guidance.sync_progress_stale": "这个来源最近没有上报新的进度。在进度恢复前，不要做会改变工作区状态的决定。",
        "sources.operator_guidance.sync_running": "这个来源仍在处理中。你可以审核当前变更，但新变更可能还会继续进入。",
        "sources.operator_guidance.active_sync_failed": "当前来源同步失败了。在确认这条工作区仍然可信之前，请先检查运行状态。",
        "sources.operator_guidance.latest_sync_failed": "最近一次来源同步失败了。在确认这条工作区仍然可信之前，请先检查来源或运行状态。",
        "sources.operator_guidance.source_idle": "当前没有来源同步在运行，可以继续审核现有变更。",

        "sources.recovery.gmail.oauth_disconnected": "在重新连接邮箱之前，新的 Gmail 相关变更可能会漏掉。",
        "sources.recovery.ics.rebind_pending": "在更新监测设置之前，Canvas ICS 的新日历更新还不能完全信任。",
        "sources.recovery.gmail.runtime_failed": "最近一次 Gmail 同步失败了，所以最近的邮件相关变更可能会漏掉。",
        "sources.recovery.ics.runtime_failed": "最近一次 Canvas ICS 同步失败了，所以最近的日历变更可能会漏掉。",
        "sources.recovery.source.runtime_failed": "最近一次来源同步失败了，所以最近的变更可能会漏掉。",
        "sources.recovery.gmail.runtime_stalled": "当前 Gmail 同步已经停止上报新进度，所以新的邮件相关变更暂时不可信。",
        "sources.recovery.ics.runtime_stalled": "当前 Canvas ICS 同步已经停止上报新进度，所以新的日历变更暂时不可信。",
        "sources.recovery.source.runtime_stalled": "当前来源同步已经停止上报新进度，所以新的变更暂时不可信。",
        "sources.recovery.baseline.running": "这个来源的基线导入仍在建立，监测还没有进入稳定状态。",
        "sources.recovery.baseline.review_required": "基线导入已经完成，但初始审核还有待处理项目，这个来源还不能完全信任。",
        "sources.recovery.gmail.active_sync": "这次同步运行期间，新的 Gmail 相关变更仍可能继续进入。",
        "sources.recovery.ics.active_sync": "这次同步运行期间，日历相关变更仍可能继续更新。",
        "sources.recovery.source.active_sync": "这次同步运行期间，新的变更仍可能继续进入。",
        "sources.recovery.gmail.trusted": "这个邮箱已连接，并且正在参与实时监测。",
        "sources.recovery.ics.trusted": "这个日历订阅已连接，并且正在参与实时监测。",
        "sources.recovery.source.trusted": "这个来源已连接，并且正在参与实时监测。",
        "sources.recovery.next_action.reconnect_gmail": "重新连接 Gmail",
        "sources.recovery.next_action.update_ics": "更新 Canvas ICS",
        "sources.recovery.next_action.retry_sync": "重试同步",
        "sources.recovery.next_action.wait_for_runtime": "等待运行恢复",
        "sources.recovery.next_action.wait_for_baseline": "等待基线导入完成",
        "sources.recovery.next_action.finish_initial_review": "完成初始审核",
        "sources.recovery.next_action.wait_for_sync": "等待同步完成",
        "sources.recovery.next_action.none": "暂时无需处理",
        "sources.recovery.gmail.step.reconnect_mailbox": "重新连接邮箱，恢复接入。",
        "sources.recovery.gmail.step.wait_for_sync": "等下一次同步完成后，再信任新的邮件相关变更。",
        "sources.recovery.ics.step.confirm_feed_settings": "打开 Canvas ICS 连接流程，确认当前订阅设置。",
        "sources.recovery.ics.step.run_sync_after_update": "保存更新后的链接后，再运行一次同步。",
        "sources.recovery.runtime_failed.step.retry_sync": "先重试一次来源同步。",
        "sources.recovery.runtime_failed.step.investigate_if_repeat": "如果下一次同步仍然失败，再检查来源连接是否有问题。",
        "sources.recovery.runtime_stalled.step.wait": "先等待当前运行继续推进或恢复。",
        "sources.recovery.runtime_stalled.step.resume_after_progress": "只有在进度重新推进或同步完成后，再信任新的变更。",
        "sources.recovery.baseline.running.step.wait": "先等待首次导入完成。",
        "sources.recovery.baseline.running.step.review_after_import": "导入完成后，先处理基线项目，再把这个来源视为完全可用。",
        "sources.recovery.baseline.review_required.step.finish_initial_review": "先完成这个来源的初始审核。",
        "sources.recovery.baseline.review_required.step.use_replay_after_review": "完成之后，再回到回放审核处理日常变更。",
        "sources.recovery.active_sync.step.review_current_changes": "当前已出现的变更仍然可以继续审核。",
        "sources.recovery.active_sync.step.expect_more_after_completion": "同步完成后，可能还会有更多变更进入。",

        "agents.context.workspace.baseline_review_pending": "基线导入审核还没有完成。",
        "agents.context.change_already_reviewed": "这条变更已经审核过了。",
        "agents.context.gmail_oauth_not_connected": "Gmail 当前没有连接。",
        "agents.context.family.pending_raw_type_suggestions": "还有 {pending_count} 条原始标签建议需要审核。",
        "agents.context.family.review_family_detail": "{canonical_label} 已可以进入标准归类与重连预览审核。",
        "agents.context.change.action.approve": "通过变更",
        "agents.context.change.action.reject": "拒绝变更",
        "agents.context.change.action.edit": "通过前先编辑",
        "agents.context.change.action.review_carefully": "仔细审核",
        "agents.context.source.action.continue_review": "继续审核",
        "agents.context.source.action.continue_review_with_caution": "谨慎继续审核",
        "agents.context.source.action.wait_for_runtime": "等待运行恢复",
        "agents.context.source.action.investigate_runtime": "检查运行状态",
        "agents.lane.sources": "来源",
        "agents.lane.initial_review": "初始审核",
        "agents.lane.changes": "回放审核",
        "agents.lane.families": "Families",
        "agents.lane.manual": "手动",

        "agents.proposals.change_decision.approve.summary": "在 {lane_label} 中通过这条变更。",
        "agents.proposals.change_decision.reject.summary": "在 {lane_label} 中拒绝这条变更。",
        "agents.proposals.change_decision.edit.summary": "先打开网页编辑流程，再在 {lane_label} 中通过这条变更。",
        "agents.proposals.change_decision.review_carefully.summary": "在 {lane_label} 中仔细审核这条高风险变更。",
        "agents.proposals.source_recovery.reconnect_gmail.summary": "在再次信任这个来源之前，先重新连接 {provider_label}。",
        "agents.proposals.source_recovery.retry_sync.summary": "为 {provider_label} 再运行一次同步。",
        "agents.proposals.source_recovery.update_ics.summary": "在下一次同步前，先更新 {provider_label} 设置。",
        "agents.proposals.source_recovery.wait.summary": "先等待 {provider_label} 运行进度，再决定下一步。",
    },
}


def _normalize_language_code_or_default(value: str | None) -> LanguageCodeLiteral:
    if value is None:
        return DEFAULT_LANGUAGE_CODE
    try:
        return normalize_language_code(value)
    except ValueError:
        return DEFAULT_LANGUAGE_CODE


def _interpolate(text: str, params: dict[str, Primitive] | None) -> str:
    if not params:
        return text

    def replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        value = params.get(key)
        return "" if value is None else str(value)

    return _VAR_PATTERN.sub(replacer, text)


def render_structured_text(
    *,
    code: str | None,
    language_code: str | None,
    params: dict[str, Primitive] | None = None,
    fallback: str | None = None,
) -> str:
    locale = _normalize_language_code_or_default(language_code)
    normalized_code = str(code or "").strip()
    template = _CATALOG.get(locale, {}).get(normalized_code)
    if template is None and locale != "en":
        template = _CATALOG["en"].get(normalized_code)
    if template is None:
        return fallback or normalized_code
    return _interpolate(template, params)


def render_structured_list(
    *,
    codes: Iterable[str],
    language_code: str | None,
    fallback_items: Iterable[str] | None = None,
    params: dict[str, Primitive] | None = None,
) -> list[str]:
    fallback_list = list(fallback_items or [])
    rendered: list[str] = []
    for index, code in enumerate(codes):
        fallback = fallback_list[index] if index < len(fallback_list) else None
        rendered.append(
            render_structured_text(
                code=code,
                language_code=language_code,
                params=params,
                fallback=fallback,
            )
        )
    return rendered


__all__ = [
    "render_structured_list",
    "render_structured_text",
]
