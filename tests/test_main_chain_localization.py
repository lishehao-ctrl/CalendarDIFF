from __future__ import annotations

from types import SimpleNamespace

from app.db.models.review import ChangeIntakePhase, ChangeType
from app.modules.agents.schemas import serialize_agent_proposal
from app.modules.changes.decision_support import build_change_decision_support
from app.modules.sources.recovery_projection import build_source_recovery_payload
from app.modules.workbench.workspace_posture import build_workspace_posture


def test_workspace_posture_localizes_next_action_in_chinese() -> None:
    payload = build_workspace_posture(
        baseline_review_pending=3,
        baseline_review_reviewed=1,
        baseline_review_total=4,
        baseline_review_completed_at=None,
        changes_pending=0,
        families_attention_count=0,
        manual_active_count=0,
        sources_summary={"active_count": 1, "blocking_count": 0, "message": ""},
        source_product_phases=["needs_initial_review"],
        monitoring_live_since=None,
        replay_active=False,
        language_code="zh-CN",
    )

    assert payload["next_action"]["label"] == "打开初始审核"
    assert "还有 3 条基线项目需要审核" in payload["next_action"]["reason"]


def test_change_decision_support_localizes_structured_copy_in_chinese() -> None:
    change = SimpleNamespace(
        change_type=ChangeType.CREATED,
        intake_phase=ChangeIntakePhase.REPLAY,
        before_semantic_json=None,
        after_semantic_json={
            "course_dept": "cse",
            "course_number": 120,
            "event_name": "Project proposal",
            "due_date": "2026-03-28",
            "due_time": "18:00:00",
            "time_precision": "datetime",
        },
    )

    payload = build_change_decision_support(
        change=change,
        primary_source={"provider": "gmail"},
        change_summary=None,
        language_code="zh-CN",
    )

    assert payload["why_now"].startswith("新的 Gmail 信号")
    assert payload["suggested_action_reason"].startswith("如果项目和时间都正确")
    assert payload["risk_summary"].startswith("通过后会在工作区里新增")
    assert payload["key_facts"][0] == "课程：CSE 120"


def test_source_recovery_localizes_steps_in_chinese() -> None:
    payload = build_source_recovery_payload(
        provider="gmail",
        oauth_connection_status="not_connected",
        runtime_state=None,
        operator_guidance=None,
        bootstrap_summary=None,
        active_payload=None,
        latest_replay_payload=None,
        bootstrap_payload=None,
        language_code="zh-CN",
    )

    assert payload["impact_summary"].startswith("在重新连接邮箱之前")
    assert payload["next_action_label"] == "重新连接 Gmail"
    assert payload["recovery_steps"][0] == "重新连接邮箱，恢复接入。"


def test_agent_proposal_serializer_localizes_summary_from_context() -> None:
    row = SimpleNamespace(
        id=101,
        user_id=1,
        proposal_type=SimpleNamespace(value="change_decision"),
        status=SimpleNamespace(value="open"),
        target_kind="change",
        target_id="42",
        summary="Approve this change in Replay Review.",
        summary_code="agents.proposals.change_decision.approve.summary",
        reason="If the item and time look correct, approving it makes the new item live immediately.",
        reason_code="changes.created.suggested_action_reason",
        risk_level="medium",
        confidence=0.8,
        suggested_action="approve",
        origin_kind="web",
        origin_label="embedded_agent",
        origin_request_id=None,
        payload_json={"kind": "change_decision", "change_id": 42, "decision": "approve"},
        context_json={"review_bucket": "changes"},
        target_snapshot_json={"review_bucket": "changes"},
        expires_at=None,
        created_at=None,
        updated_at=None,
    )

    payload = serialize_agent_proposal(row, language_code="zh-CN")

    assert payload["summary"] == "在 回放审核 中通过这条变更。"
    assert payload["reason"].startswith("如果项目和时间都正确")
