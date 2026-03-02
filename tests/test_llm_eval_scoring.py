from __future__ import annotations

from app.modules.ingestion.eval.contracts import IcsEvalResult, MailEvalResult
from app.modules.ingestion.eval.scoring import (
    DEFAULT_THRESHOLDS,
    compute_ics_metrics,
    compute_mail_metrics,
    evaluate_thresholds,
    summarize_eval_results,
)


def test_compute_mail_metrics_perfect_prediction_reaches_macro_f1_one() -> None:
    results = [
        MailEvalResult(
            email_id="m1",
            gold_label="KEEP",
            gold_event_type="deadline",
            predicted_label="KEEP",
            predicted_event_type="deadline",
            structured_success=True,
            ambiguous=False,
        ),
        MailEvalResult(
            email_id="m2",
            gold_label="KEEP",
            gold_event_type="exam",
            predicted_label="KEEP",
            predicted_event_type="exam",
            structured_success=True,
            ambiguous=False,
        ),
        MailEvalResult(
            email_id="m3",
            gold_label="KEEP",
            gold_event_type="schedule_change",
            predicted_label="KEEP",
            predicted_event_type="schedule_change",
            structured_success=True,
            ambiguous=True,
        ),
        MailEvalResult(
            email_id="m4",
            gold_label="KEEP",
            gold_event_type="assignment",
            predicted_label="KEEP",
            predicted_event_type="assignment",
            structured_success=True,
            ambiguous=True,
        ),
        MailEvalResult(
            email_id="m5",
            gold_label="KEEP",
            gold_event_type="action_required",
            predicted_label="KEEP",
            predicted_event_type="action_required",
            structured_success=True,
            ambiguous=False,
        ),
        MailEvalResult(
            email_id="m6",
            gold_label="KEEP",
            gold_event_type="announcement",
            predicted_label="KEEP",
            predicted_event_type="announcement",
            structured_success=True,
            ambiguous=False,
        ),
        MailEvalResult(
            email_id="m7",
            gold_label="KEEP",
            gold_event_type="grade",
            predicted_label="KEEP",
            predicted_event_type="grade",
            structured_success=True,
            ambiguous=False,
        ),
        MailEvalResult(
            email_id="m8",
            gold_label="DROP",
            gold_event_type=None,
            predicted_label="DROP",
            predicted_event_type=None,
            structured_success=True,
            ambiguous=False,
        ),
    ]

    metrics = compute_mail_metrics(results=results)

    assert metrics["structured_success_rate"] == 1.0
    assert metrics["label_accuracy"] == 1.0
    assert metrics["event_macro_f1"] == 1.0


def test_compute_ics_metrics_and_threshold_decision() -> None:
    ics_results = [
        IcsEvalResult(
            pair_id="p1",
            expected_diff_class="DUE_CHANGED",
            predicted_diff_class="DUE_CHANGED",
            expected_changed_uids=["u1"],
            predicted_changed_uids=["u1"],
            structured_success=True,
            ambiguous=False,
        ),
        IcsEvalResult(
            pair_id="p2",
            expected_diff_class="CREATED",
            predicted_diff_class="NO_CHANGE",
            expected_changed_uids=["u2"],
            predicted_changed_uids=[],
            structured_success=True,
            ambiguous=True,
        ),
        IcsEvalResult(
            pair_id="p3",
            expected_diff_class="NO_CHANGE",
            predicted_diff_class=None,
            expected_changed_uids=[],
            predicted_changed_uids=[],
            structured_success=False,
            ambiguous=False,
            error_code="parse_llm_timeout",
            error_message="timeout",
        ),
    ]
    mail_results = [
        MailEvalResult(
            email_id="m1",
            gold_label="KEEP",
            gold_event_type="deadline",
            predicted_label="DROP",
            predicted_event_type=None,
            structured_success=True,
            ambiguous=False,
        )
    ]

    ics_metrics = compute_ics_metrics(results=ics_results)
    mail_metrics = compute_mail_metrics(results=mail_results)

    assert ics_metrics["structured_success_rate"] == 0.6667
    assert ics_metrics["diff_accuracy"] == 0.3333
    assert ics_metrics["uid_hit_rate"] == 0.5

    decision = evaluate_thresholds(mail_metrics=mail_metrics, ics_metrics=ics_metrics)
    assert decision.passed is False
    assert set(decision.failed_checks)


def test_summarize_eval_results_keeps_threshold_contract_keys() -> None:
    summary = summarize_eval_results(mail_results=[], ics_results=[])

    assert set(summary.decision.thresholds.keys()) == set(DEFAULT_THRESHOLDS.keys())
    assert set(summary.decision.threshold_check.keys()) == set(DEFAULT_THRESHOLDS.keys())
