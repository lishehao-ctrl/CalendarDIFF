from __future__ import annotations

from collections import Counter
from dataclasses import asdict

from app.modules.ingestion.eval.contracts import EvalSummary, IcsEvalResult, MailEvalResult, ThresholdDecision

MAIL_EVENT_CLASSES = [
    "deadline",
    "exam",
    "schedule_change",
    "assignment",
    "action_required",
    "announcement",
    "grade",
    "null",
]
ICS_DIFF_CLASSES = ["DUE_CHANGED", "CREATED", "NO_CHANGE", "REMOVED_CANDIDATE", "PARSE_FAILED"]

DEFAULT_THRESHOLDS: dict[str, float] = {
    "mail.event_macro_f1": 0.85,
    "ics.diff_accuracy": 0.92,
    "mail.structured_success_rate": 0.98,
    "ics.structured_success_rate": 0.98,
}


def summarize_eval_results(
    *,
    mail_results: list[MailEvalResult],
    ics_results: list[IcsEvalResult],
    thresholds: dict[str, float] | None = None,
) -> EvalSummary:
    mail_metrics = compute_mail_metrics(results=mail_results)
    ics_metrics = compute_ics_metrics(results=ics_results)
    decision = evaluate_thresholds(
        mail_metrics=mail_metrics,
        ics_metrics=ics_metrics,
        thresholds=thresholds,
    )
    return EvalSummary(
        mail_metrics=mail_metrics,
        ics_metrics=ics_metrics,
        decision=decision,
    )


def compute_mail_metrics(*, results: list[MailEvalResult]) -> dict:
    total = len(results)
    if total == 0:
        return {
            "total_samples": 0,
            "structured_success_rate": 0.0,
            "label_accuracy": 0.0,
            "event_macro_f1": 0.0,
            "ambiguous_macro_f1": 0.0,
            "non_ambiguous_macro_f1": 0.0,
            "event_confusion_matrix": _empty_confusion(MAIL_EVENT_CLASSES),
            "error_code_counts": {},
        }

    success_count = sum(1 for row in results if row.structured_success)
    label_correct = sum(1 for row in results if row.predicted_label == row.gold_label)

    gold_events = [_normalize_mail_event(label=row.gold_label, event_type=row.gold_event_type) for row in results]
    predicted_events = [
        _normalize_mail_event(label=row.predicted_label, event_type=row.predicted_event_type) for row in results
    ]

    confusion = _build_confusion_matrix(
        labels=MAIL_EVENT_CLASSES,
        y_true=gold_events,
        y_pred=predicted_events,
    )

    ambiguous_mask = [row.ambiguous for row in results]
    ambiguous_true = [gold for gold, keep in zip(gold_events, ambiguous_mask, strict=True) if keep]
    ambiguous_pred = [pred for pred, keep in zip(predicted_events, ambiguous_mask, strict=True) if keep]
    non_ambiguous_true = [gold for gold, keep in zip(gold_events, ambiguous_mask, strict=True) if not keep]
    non_ambiguous_pred = [pred for pred, keep in zip(predicted_events, ambiguous_mask, strict=True) if not keep]

    error_counts = Counter(row.error_code for row in results if row.error_code)

    return {
        "total_samples": total,
        "structured_success_rate": _round(success_count / total),
        "label_accuracy": _round(label_correct / total),
        "event_macro_f1": _macro_f1(
            labels=MAIL_EVENT_CLASSES,
            y_true=gold_events,
            y_pred=predicted_events,
        ),
        "ambiguous_macro_f1": _macro_f1(
            labels=MAIL_EVENT_CLASSES,
            y_true=ambiguous_true,
            y_pred=ambiguous_pred,
        ),
        "non_ambiguous_macro_f1": _macro_f1(
            labels=MAIL_EVENT_CLASSES,
            y_true=non_ambiguous_true,
            y_pred=non_ambiguous_pred,
        ),
        "event_confusion_matrix": confusion,
        "error_code_counts": dict(error_counts),
    }


def compute_ics_metrics(*, results: list[IcsEvalResult]) -> dict:
    total = len(results)
    if total == 0:
        return {
            "total_pairs": 0,
            "structured_success_rate": 0.0,
            "diff_accuracy": 0.0,
            "uid_hit_rate": 0.0,
            "diff_confusion_matrix": _empty_confusion(ICS_DIFF_CLASSES),
            "error_code_counts": {},
        }

    success_count = sum(1 for row in results if row.structured_success)

    y_true = [row.expected_diff_class for row in results]
    y_pred = [row.predicted_diff_class or "PARSE_FAILED" for row in results]

    class_correct = sum(1 for truth, pred in zip(y_true, y_pred, strict=True) if truth == pred)
    confusion = _build_confusion_matrix(
        labels=ICS_DIFF_CLASSES,
        y_true=y_true,
        y_pred=y_pred,
    )

    total_expected_uids = 0
    matched_expected_uids = 0
    for row in results:
        expected = [uid for uid in row.expected_changed_uids if isinstance(uid, str) and uid]
        total_expected_uids += len(expected)
        predicted_set = {uid for uid in row.predicted_changed_uids if isinstance(uid, str) and uid}
        matched_expected_uids += sum(1 for uid in expected if uid in predicted_set)

    uid_hit_rate = 1.0 if total_expected_uids == 0 else matched_expected_uids / total_expected_uids

    error_counts = Counter(row.error_code for row in results if row.error_code)

    return {
        "total_pairs": total,
        "structured_success_rate": _round(success_count / total),
        "diff_accuracy": _round(class_correct / total),
        "uid_hit_rate": _round(uid_hit_rate),
        "diff_confusion_matrix": confusion,
        "error_code_counts": dict(error_counts),
    }


def evaluate_thresholds(
    *,
    mail_metrics: dict,
    ics_metrics: dict,
    thresholds: dict[str, float] | None = None,
) -> ThresholdDecision:
    threshold_values = dict(DEFAULT_THRESHOLDS)
    if thresholds is not None:
        threshold_values.update(thresholds)

    checks = {
        "mail.event_macro_f1": float(mail_metrics.get("event_macro_f1", 0.0)) >= threshold_values["mail.event_macro_f1"],
        "ics.diff_accuracy": float(ics_metrics.get("diff_accuracy", 0.0)) >= threshold_values["ics.diff_accuracy"],
        "mail.structured_success_rate": float(mail_metrics.get("structured_success_rate", 0.0))
        >= threshold_values["mail.structured_success_rate"],
        "ics.structured_success_rate": float(ics_metrics.get("structured_success_rate", 0.0))
        >= threshold_values["ics.structured_success_rate"],
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    return ThresholdDecision(
        thresholds=threshold_values,
        threshold_check=checks,
        failed_checks=failed_checks,
        passed=not failed_checks,
    )


def summary_to_dict(summary: EvalSummary) -> dict:
    decision_payload = asdict(summary.decision)
    return {
        "mail": summary.mail_metrics,
        "ics": summary.ics_metrics,
        **decision_payload,
    }


def _normalize_mail_event(*, label: str | None, event_type: str | None) -> str:
    if label != "KEEP":
        return "null"
    if not isinstance(event_type, str):
        return "null"
    normalized = event_type.strip().lower()
    if normalized in MAIL_EVENT_CLASSES:
        return normalized
    return "null"


def _macro_f1(*, labels: list[str], y_true: list[str], y_pred: list[str]) -> float:
    if not y_true or not y_pred:
        return 0.0

    total = 0.0
    for label in labels:
        tp = 0
        fp = 0
        fn = 0
        for truth, pred in zip(y_true, y_pred, strict=True):
            if truth == label and pred == label:
                tp += 1
            elif truth != label and pred == label:
                fp += 1
            elif truth == label and pred != label:
                fn += 1

        denominator = (2 * tp) + fp + fn
        f1 = 0.0 if denominator == 0 else (2 * tp) / denominator
        total += f1

    return _round(total / len(labels))


def _build_confusion_matrix(*, labels: list[str], y_true: list[str], y_pred: list[str]) -> dict[str, dict[str, int]]:
    matrix = _empty_confusion(labels)
    for truth, pred in zip(y_true, y_pred, strict=True):
        if truth not in matrix:
            matrix[truth] = {name: 0 for name in labels}
        if pred not in matrix[truth]:
            matrix[truth][pred] = 0
        matrix[truth][pred] += 1
    return matrix


def _empty_confusion(labels: list[str]) -> dict[str, dict[str, int]]:
    return {label: {pred: 0 for pred in labels} for label in labels}


def _round(value: float) -> float:
    return round(float(value), 4)
