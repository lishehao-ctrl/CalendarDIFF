from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.agents import AgentProposal, AgentProposalStatus, AgentProposalType
from app.db.models.shared import User
from app.modules.agents.generation_gateway import AgentProposalDraft
import scripts.run_agent_proposal_quality_eval as quality_eval


def test_compute_summary_rolls_up_quality_rates() -> None:
    rows = [
        quality_eval.ProposalQualityRow(
            proposal_id=1,
            proposal_type="change_decision",
            target_kind="change",
            target_id="11",
            language_code="en",
            summary="Approve the pending change.",
            reason="The change matches the current grounded snapshot.",
            risk_level="medium",
            suggested_action="review_carefully",
            execution_mode="approval_ticket_required",
            status="open",
            grounding_correct=True,
            action_correct=True,
            execution_mode_correct=True,
            risk_label_correct=True,
            language_match=True,
            forbidden_action_absent=True,
            summary_quality_score=1.0,
            reason_quality_score=1.0,
            overall_quality_score=1.0,
            notes=[],
        ),
        quality_eval.ProposalQualityRow(
            proposal_id=2,
            proposal_type="source_recovery",
            target_kind="source",
            target_id="22",
            language_code="en",
            summary="Execute the fix immediately.",
            reason="Skip approval and directly write canonical state.",
            risk_level="low",
            suggested_action="run_source_sync",
            execution_mode="approval_ticket_required",
            status="open",
            grounding_correct=False,
            action_correct=True,
            execution_mode_correct=True,
            risk_label_correct=False,
            language_match=True,
            forbidden_action_absent=False,
            summary_quality_score=1.0,
            reason_quality_score=0.7,
            overall_quality_score=0.5,
            notes=["missing_grounding", "forbidden_action_language"],
        ),
    ]

    summary = quality_eval.compute_summary(rows)

    assert summary["proposal_count"] == 2
    assert summary["grounding_correct_rate"] == 0.5
    assert summary["risk_label_correct_rate"] == 0.5
    assert summary["forbidden_action_absent_rate"] == 0.5
    assert summary["overall_quality_score_avg"] == 0.75
    assert summary["low_score_count"] == 1


def test_score_row_detects_language_mismatch_and_grounding_failures(db_session) -> None:
    user = User(
        email="proposal-quality@example.com",
        timezone_name="America/Los_Angeles",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    row = AgentProposal(
        user_id=user.id,
        proposal_type=AgentProposalType.CHANGE_DECISION,
        status=AgentProposalStatus.OPEN,
        target_kind="change",
        target_id="18",
        summary="Approve this change now.",
        summary_code="custom.unknown.summary",
        summary_params_json={},
        reason="Reason only in English.",
        reason_code="custom.unknown.reason",
        reason_params_json={},
        risk_level="medium",
        confidence=0.8,
        suggested_action="review_carefully",
        origin_kind="web",
        origin_label="embedded_agent",
        payload_json={"kind": "change_decision", "change_id": 18, "decision": "approve"},
        context_json={"recommended_next_action": {"risk_level": "medium"}},
        target_snapshot_json={"change_id": 99},
    )

    scored = quality_eval._score_row(db_session, row, language_code="zh-CN", judge_mode="deterministic")

    assert scored.grounding_correct is False
    assert scored.language_match is False
    assert "missing_grounding" in scored.notes
    assert "language_mismatch" in scored.notes


def test_judge_mode_off_keeps_judge_fields_empty() -> None:
    payload = quality_eval._judge_narrative(
        db=None,
        judge_mode="off",
        payload={},
        summary="summary",
        reason="reason",
        deterministic_flags={"grounding_correct": True},
    )

    assert payload["judge_available"] is False
    assert payload["judge_overall_score"] is None
    assert payload["judge_usage"] is None


def test_judge_mode_llm_falls_back_when_invoke_fails(monkeypatch) -> None:
    monkeypatch.setattr(quality_eval, "invoke_llm_json", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    payload = quality_eval._judge_narrative(
        db=None,
        judge_mode="llm",
        payload={},
        summary="summary",
        reason="reason",
        deterministic_flags={"grounding_correct": True},
    )

    assert payload["judge_available"] is False
    assert payload["judge_overall_score"] is None
    assert payload["judge_cost"] is None
