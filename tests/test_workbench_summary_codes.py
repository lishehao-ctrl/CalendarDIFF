from __future__ import annotations

from app.modules.workbench.summary_service import _recommend_workbench_lane
from app.modules.workbench.workspace_posture import build_workspace_posture


def test_recommend_workbench_lane_exposes_reason_codes() -> None:
    lane, lane_reason_code, action_reason, action_reason_code, action_reason_params = _recommend_workbench_lane(
        baseline_review_pending=2,
        changes_pending=0,
        families_attention_count=0,
        sources_summary={"blocking_count": 0},
    )
    assert lane == "initial_review"
    assert lane_reason_code == "baseline_review_pending"
    assert action_reason_code == "workbench.summary.baseline_review_pending"
    assert action_reason_params == {"pending_count": 2}
    assert "2 baseline import items" in action_reason


def test_workspace_posture_next_action_exposes_reason_code() -> None:
    payload = build_workspace_posture(
        baseline_review_pending=0,
        baseline_review_reviewed=0,
        baseline_review_total=0,
        baseline_review_completed_at=None,
        changes_pending=3,
        families_attention_count=0,
        manual_active_count=0,
        sources_summary={"blocking_count": 0, "active_count": 1},
        source_product_phases=["monitoring_live"],
        monitoring_live_since=None,
        replay_active=False,
    )
    assert payload["next_action"]["lane"] == "changes"
    assert payload["next_action"]["reason_code"] == "workspace_posture.next_action.replay_changes_pending"
    assert payload["next_action"]["reason_params"] == {"pending_count": 3}
