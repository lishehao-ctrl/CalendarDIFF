from __future__ import annotations

from app.modules.ingestion.eval.contracts import IcsEvalResult, MailEvalResult
from app.modules.ingestion.eval.scoring import summarize_eval_results, summary_to_dict


def test_eval_report_payload_contains_required_sections() -> None:
    mail_results = [
        MailEvalResult(
            email_id="mail-1",
            gold_label="DROP",
            gold_event_type=None,
            predicted_label="DROP",
            predicted_event_type=None,
            structured_success=True,
            ambiguous=False,
        )
    ]
    ics_results = [
        IcsEvalResult(
            pair_id="ics-1",
            expected_diff_class="NO_CHANGE",
            predicted_diff_class="NO_CHANGE",
            expected_changed_uids=[],
            predicted_changed_uids=[],
            structured_success=True,
            ambiguous=False,
        )
    ]

    summary = summarize_eval_results(mail_results=mail_results, ics_results=ics_results)
    payload = summary_to_dict(summary)

    assert "mail" in payload
    assert "ics" in payload
    assert "thresholds" in payload
    assert "threshold_check" in payload
    assert "failed_checks" in payload
    assert "passed" in payload

    mail_keys = {
        "structured_success_rate",
        "label_accuracy",
        "event_macro_f1",
        "event_confusion_matrix",
        "ambiguous_macro_f1",
        "non_ambiguous_macro_f1",
    }
    assert mail_keys.issubset(payload["mail"].keys())

    ics_keys = {
        "structured_success_rate",
        "diff_accuracy",
        "uid_hit_rate",
        "diff_confusion_matrix",
    }
    assert ics_keys.issubset(payload["ics"].keys())
