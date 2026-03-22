from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.modules.runtime.connectors.gmail_second_filter import (
    SAFE_NON_TARGET_REASON_CODES,
    _build_compact_v2_text,
    classify_safe_non_target_heuristic,
)
from app.modules.runtime.connectors.source_orchestrator import route_gmail_message

FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "private" / "email_pool"
DEFAULT_BUCKET = "year_timeline_full_sim"
DEFAULT_CHECKPOINT = REPO_ROOT / "training" / "gmail_secondary_filter" / "output" / "distilbert-compact-v2-full"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output"
LABELS = ["relevant", "non_target", "uncertain"]
LABEL_TO_ID = {label: index for index, label in enumerate(LABELS)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate current prefilter + compact_v2 BERT on full-sim Gmail fixtures.")
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--checkpoint", default=str(DEFAULT_CHECKPOINT))
    parser.add_argument("--threshold", type=float, default=0.995)
    parser.add_argument("--limit", type=int, default=-1)
    parser.add_argument("--output-json", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_bucket_rows(args.bucket)
    if args.limit >= 0:
        rows = rows[: args.limit]

    known_course_tokens = derive_known_course_tokens(rows)
    tokenizer = AutoTokenizer.from_pretrained(args.checkpoint)
    model = AutoModelForSequenceClassification.from_pretrained(args.checkpoint)
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    model.to(device)
    model.eval()

    prefilter_pass = 0
    prefilter_skip = 0
    expected_target = 0
    expected_non_target = 0

    bert_calls = 0
    bert_errors = 0
    bert_input_tokens: list[int] = []
    bert_latency_ms: list[float] = []
    label_counts = Counter()
    dataset_reason_counts = Counter()
    runtime_safe_reason_counts = Counter()
    runtime_suppressed_reason_counts = Counter()

    global_tp = global_fp = global_tn = global_fn = 0
    safe_tp = safe_fp = safe_tn = safe_fn = 0

    for row in rows:
        target_class = str(row.get("prefilter_target_class") or "non_target")
        if target_class == "target_signal":
            expected_target += 1
        else:
            expected_non_target += 1

        should_parse = _passes_primary_prefilter(
            row=row,
            known_course_tokens=known_course_tokens,
        )
        if not should_parse:
            prefilter_skip += 1
            continue

        prefilter_pass += 1
        bert_calls += 1
        text = _build_compact_v2_text(
            from_header=row.get("from_header"),
            subject=row.get("subject"),
            snippet=row.get("snippet"),
            body_text=row.get("body_text"),
            label_ids=row.get("label_ids") or [],
            max_chars=1200,
        )
        token_count = len(tokenizer(text, truncation=False)["input_ids"])
        bert_input_tokens.append(token_count)

        try:
            started = time.perf_counter()
            encoded = tokenizer(text, truncation=True, max_length=256, return_tensors="pt")
            encoded = {key: value.to(device) for key, value in encoded.items()}
            with torch.no_grad():
                logits = model(**encoded).logits.detach().cpu().numpy()
            probs = softmax(logits)[0]
            latency_ms = (time.perf_counter() - started) * 1000.0
            bert_latency_ms.append(latency_ms)
        except Exception:
            bert_errors += 1
            continue

        predicted_label = LABELS[int(np.argmax(probs))]
        non_target_prob = float(probs[LABEL_TO_ID["non_target"]])
        label_counts[predicted_label] += 1

        reason_family = str(
            row.get("prefilter_reason_family")
            or row.get("background_category")
            or row.get("message_kind")
            or "unknown"
        )
        dataset_reason_counts[reason_family] += 1

        runtime_safe = classify_safe_non_target_heuristic(
            from_header=row.get("from_header"),
            subject=row.get("subject"),
            snippet=row.get("snippet"),
            body_text=row.get("body_text"),
            known_course_tokens=known_course_tokens,
        )
        runtime_safe_reason_counts[runtime_safe.reason_code] += 1

        suppress_global = non_target_prob >= float(args.threshold)
        suppress_safe = (
            suppress_global
            and runtime_safe.risk_band == "safe"
            and runtime_safe.reason_code in SAFE_NON_TARGET_REASON_CODES
        )
        is_non_target = target_class != "target_signal"
        if suppress_safe:
            runtime_suppressed_reason_counts[runtime_safe.reason_code] += 1

        if suppress_global and is_non_target:
            global_tp += 1
        elif suppress_global and not is_non_target:
            global_fp += 1
        elif (not suppress_global) and is_non_target:
            global_fn += 1
        else:
            global_tn += 1

        if suppress_safe and is_non_target:
            safe_tp += 1
        elif suppress_safe and not is_non_target:
            safe_fp += 1
        elif (not suppress_safe) and is_non_target:
            safe_fn += 1
        else:
            safe_tn += 1

    report = {
        "bucket": args.bucket,
        "sample_count": len(rows),
        "prefilter": {
            "pass_count": prefilter_pass,
            "skip_count": prefilter_skip,
            "pass_rate": ratio(prefilter_pass, len(rows)),
            "skip_rate": ratio(prefilter_skip, len(rows)),
            "expected_target_count": expected_target,
            "expected_non_target_count": expected_non_target,
        },
        "bert": {
            "call_count": bert_calls,
            "error_count": bert_errors,
            "success_count": bert_calls - bert_errors,
            "label_counts": dict(label_counts),
            "top_dataset_reason_families": dict(dataset_reason_counts.most_common(12)),
            "top_runtime_safe_reasons": dict(runtime_safe_reason_counts.most_common(12)),
            "top_runtime_suppressed_reasons": dict(runtime_suppressed_reason_counts.most_common(12)),
            "input_tokens": summarize_numeric(bert_input_tokens),
            "latency_ms": summarize_numeric(bert_latency_ms),
        },
        "stack_global_threshold": {
            "tp": global_tp,
            "fp": global_fp,
            "tn": global_tn,
            "fn": global_fn,
            "filter_rate_overall": ratio(global_tp + global_fp, len(rows)),
            "precision": ratio(global_tp, global_tp + global_fp),
            "recall_on_non_target_after_prefilter": ratio(global_tp, global_tp + global_fn),
            "final_to_llm_count": prefilter_pass - (global_tp + global_fp),
        },
        "stack_safe_threshold": {
            "safe_reason_families": sorted(SAFE_NON_TARGET_REASON_CODES),
            "tp": safe_tp,
            "fp": safe_fp,
            "tn": safe_tn,
            "fn": safe_fn,
            "filter_rate_overall": ratio(safe_tp + safe_fp, len(rows)),
            "precision": ratio(safe_tp, safe_tp + safe_fp),
            "recall_on_non_target_after_prefilter": ratio(safe_tp, safe_tp + safe_fn),
            "final_to_llm_count": prefilter_pass - (safe_tp + safe_fp),
        },
    }

    output_path = (
        Path(args.output_json).expanduser().resolve()
        if args.output_json
        else DEFAULT_OUTPUT_DIR / "year_timeline_full_sim_prefilter_bert_report.json"
    )
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def load_bucket_rows(bucket: str) -> list[dict[str, Any]]:
    path = FIXTURE_ROOT / bucket / "samples.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def derive_known_course_tokens(rows: list[dict[str, Any]]) -> set[str]:
    tokens: set[str] = set()
    for row in rows:
        tokens.update(tokens_for_course_text(str(row.get("course_label") or "")))
        tokens.update(tokens_for_course_text(str(row.get("course_hint") or "")))
        draft = row.get("expected_semantic_event_draft")
        if isinstance(draft, dict):
            dept = str(draft.get("course_dept") or "").strip()
            number = draft.get("course_number")
            suffix = str(draft.get("course_suffix") or "").strip()
            if dept and number:
                tokens.update(tokens_for_course_text(f"{dept} {number}{suffix}"))
    return {token for token in tokens if token}


def tokens_for_course_text(value: str) -> set[str]:
    cleaned = value.strip().lower()
    if not cleaned:
        return set()
    compact = "".join(cleaned.split())
    spaced = " ".join(cleaned.split())
    out = {compact, spaced}
    letters = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in cleaned)
    normalized = " ".join(letters.split())
    if normalized:
        out.add(normalized)
        parts = normalized.split()
        if len(parts) == 1:
            split = split_course_token(parts[0])
            if split:
                out.add(split)
        if len(parts) >= 2:
            out.add(f"{parts[0]}{''.join(parts[1:])}")
    return out


def split_course_token(value: str) -> str | None:
    prefix = []
    suffix = []
    hit_digit = False
    for char in value:
        if char.isdigit():
            hit_digit = True
        if hit_digit:
            suffix.append(char)
        else:
            prefix.append(char)
    if prefix and suffix:
        return f"{''.join(prefix)} {''.join(suffix)}"
    return None


def softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=-1, keepdims=True)
    exp = np.exp(shifted)
    return exp / np.sum(exp, axis=-1, keepdims=True)


def _passes_primary_prefilter(*, row: dict[str, Any], known_course_tokens: set[str]) -> bool:
    decision = route_gmail_message(
        from_header=str(row.get("from_header") or ""),
        subject=str(row.get("subject") or ""),
        snippet=str(row.get("snippet") or ""),
        body_text=str(row.get("body_text") or ""),
        explicit_sender_signal=False,
        explicit_subject_signal=False,
        known_course_tokens=known_course_tokens,
    )
    return decision.route == "parse"


def ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def summarize_numeric(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "avg": None, "p50": None, "p95": None, "max": None}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "avg": round(mean(ordered), 4),
        "p50": round(percentile(ordered, 0.50), 4),
        "p95": round(percentile(ordered, 0.95), 4),
        "max": round(ordered[-1], 4),
    }


def percentile(values: list[float], p: float) -> float:
    index = min(len(values) - 1, int(len(values) * p))
    return values[index]


if __name__ == "__main__":
    main()
