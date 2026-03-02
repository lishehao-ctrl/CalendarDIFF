from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from app.modules.ingestion.eval.contracts import MailEvalResult, MailEvalSample
from app.modules.ingestion.llm_parsers import LlmParseError, ParserContext, parse_gmail_payload

_ALLOWED_KEEP_EVENT_TYPES = {
    "deadline",
    "exam",
    "schedule_change",
    "assignment",
    "action_required",
    "announcement",
    "grade",
}


def run_mail_eval(*, samples: list[MailEvalSample], max_workers: int = 4) -> list[MailEvalResult]:
    if not samples:
        return []

    workers = max(int(max_workers), 1)
    indexed_results: dict[int, MailEvalResult] = {}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_run_single_mail_sample, index=index, sample=sample): index
            for index, sample in enumerate(samples)
        }
        for future in as_completed(future_map):
            index = future_map[future]
            indexed_results[index] = future.result()

    return [indexed_results[index] for index in range(len(samples))]


def predict_mail_from_records(*, records: list[dict]) -> tuple[str, str | None]:
    best_event_type: str | None = None
    best_confidence = float("-inf")
    candidate_seen = False

    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("record_type") != "gmail.message.extracted":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue

        candidate_seen = True
        confidence_raw = payload.get("confidence")
        if isinstance(confidence_raw, (int, float)):
            confidence = float(confidence_raw)
        else:
            confidence = 0.0

        event_type_raw = payload.get("event_type")
        normalized_event_type = _normalize_event_type(event_type_raw)

        # On tie, keep first occurrence by updating only when confidence is strictly better.
        if confidence > best_confidence:
            best_confidence = confidence
            best_event_type = normalized_event_type

    if not candidate_seen:
        return "DROP", None
    if best_event_type is None or best_event_type == "other":
        return "DROP", None
    if best_event_type in _ALLOWED_KEEP_EVENT_TYPES:
        return "KEEP", best_event_type
    return "DROP", None


def _run_single_mail_sample(*, index: int, sample: MailEvalSample) -> MailEvalResult:
    payload = {
        "message_id": sample.email_id,
        "subject": sample.subject,
        "body_text": sample.body_text,
        "snippet": _build_snippet(sample.body_text),
        "from_header": sample.from_addr,
        "internal_date": sample.date,
        "label_ids": [],
    }
    context = ParserContext(
        source_id=10_000 + index,
        provider="gmail",
        source_kind="email",
        request_id=f"mail-eval-{sample.email_id}",
    )

    try:
        parser_output = parse_gmail_payload(
            db=None,  # type: ignore[arg-type]
            payload=payload,
            context=context,
        )
    except LlmParseError as exc:
        return MailEvalResult(
            email_id=sample.email_id,
            gold_label=sample.gold_label,
            gold_event_type=sample.gold_event_type,
            predicted_label=None,
            predicted_event_type=None,
            structured_success=False,
            ambiguous=sample.ambiguous,
            error_code=exc.code,
            error_message=str(exc),
        )

    predicted_label, predicted_event_type = predict_mail_from_records(records=parser_output.records)
    return MailEvalResult(
        email_id=sample.email_id,
        gold_label=sample.gold_label,
        gold_event_type=sample.gold_event_type,
        predicted_label=predicted_label,  # type: ignore[arg-type]
        predicted_event_type=predicted_event_type,
        structured_success=True,
        ambiguous=sample.ambiguous,
        error_code=None,
        error_message=None,
    )


def _normalize_event_type(raw_value: object) -> str | None:
    if not isinstance(raw_value, str):
        return None
    cleaned = raw_value.strip().lower()
    return cleaned or None


def _build_snippet(body_text: str | None) -> str:
    if not isinstance(body_text, str):
        return ""
    text = body_text.strip()
    if not text:
        return ""
    return text[:280]
