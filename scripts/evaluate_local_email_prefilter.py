from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.modules.runtime.connectors.gmail_fetcher import matches_gmail_source_filters

FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "private" / "email_pool"
DERIVED_SET_ROOT = FIXTURE_ROOT / "derived_sets"
DEFAULT_BUCKET = "year_timeline_full_sim"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the current Gmail source prefilter on local email-pool fixtures.")
    parser.add_argument("--bucket", action="append", default=None, help="Bucket(s) under tests/fixtures/private/email_pool. Defaults to year_timeline_full_sim.")
    parser.add_argument("--derived-set", action="append", default=None, help="Derived set name(s) under tests/fixtures/private/email_pool/derived_sets.")
    parser.add_argument("--limit", type=int, default=-1, help="Optional cap after selection. Use -1 for all.")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    selected = select_rows(
        buckets=args.bucket or [DEFAULT_BUCKET],
        derived_sets=args.derived_set or [],
        limit=args.limit,
    )
    rows = [row for bucket_rows in selected.values() for row in bucket_rows]
    report = evaluate_prefilter_rows(rows)
    report["selected_buckets"] = list(selected.keys())
    report["selected_sample_count"] = len(rows)
    if args.derived_set:
        report["derived_sets"] = list(args.derived_set)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print(render_text_summary(report))


def select_rows(*, buckets: list[str], derived_sets: list[str], limit: int) -> dict[str, list[dict[str, Any]]]:
    ordered_buckets: list[str] = []
    seen: set[str] = set()
    for bucket in buckets:
        if bucket in seen:
            continue
        seen.add(bucket)
        ordered_buckets.append(bucket)

    rows_by_bucket = {bucket: load_bucket_rows(bucket) for bucket in ordered_buckets}
    if derived_sets:
        wanted_by_bucket: dict[str, set[str]] = {bucket: set() for bucket in ordered_buckets}
        for name in derived_sets:
            payload = load_derived_set(name)
            for bucket, sample_ids in payload.items():
                wanted_by_bucket.setdefault(bucket, set()).update(sample_ids)
                if bucket not in rows_by_bucket:
                    rows_by_bucket[bucket] = load_bucket_rows(bucket)
                    ordered_buckets.append(bucket)
        rows_by_bucket = {
            bucket: [row for row in rows if str(row.get("sample_id") or "") in wanted_by_bucket.get(bucket, set())]
            for bucket, rows in rows_by_bucket.items()
            if wanted_by_bucket.get(bucket)
        }

    if limit >= 0:
        rows_by_bucket = {bucket: rows[:limit] for bucket, rows in rows_by_bucket.items()}
    return rows_by_bucket


def load_bucket_rows(bucket: str) -> list[dict[str, Any]]:
    path = FIXTURE_ROOT / bucket / "samples.jsonl"
    if not path.exists():
        raise RuntimeError(f"bucket not found: {bucket}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_derived_set(name: str) -> dict[str, list[str]]:
    path = DERIVED_SET_ROOT / f"{name}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    sample_ids_by_bucket = payload.get("sample_ids_by_bucket")
    if not isinstance(sample_ids_by_bucket, dict):
        raise RuntimeError(f"derived set missing sample_ids_by_bucket: {name}")
    return {
        str(bucket): [str(sample_id) for sample_id in sample_ids if isinstance(sample_id, str)]
        for bucket, sample_ids in sample_ids_by_bucket.items()
        if isinstance(sample_ids, list)
    }


def evaluate_prefilter_rows(rows: list[dict[str, Any]], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    effective_config = config or {}
    known_course_tokens = derive_known_course_tokens(rows)

    parse_count = 0
    skip_count = 0
    target_total = 0
    target_parse = 0
    expected_match_count = 0
    correct_count = 0
    by_reason: dict[str, dict[str, Any]] = {}

    for row in rows:
        actual_route = "parse" if matches_gmail_source_filters(
            metadata=build_metadata(row),
            config=effective_config,
            known_course_tokens=known_course_tokens,
        ) else "skip_unknown"
        expected_route = normalize_expected_route(row)
        reason_family = normalize_reason_family(row)
        target_class = normalize_target_class(row)

        if actual_route == "parse":
            parse_count += 1
        else:
            skip_count += 1
        if expected_route == actual_route:
            correct_count += 1
        if expected_route:
            expected_match_count += 1
        if target_class == "target_signal":
            target_total += 1
            if actual_route == "parse":
                target_parse += 1

        bucket = by_reason.setdefault(
            reason_family,
            {
                "sample_count": 0,
                "parse_count": 0,
                "skip_count": 0,
                "target_signal_count": 0,
                "non_target_count": 0,
            },
        )
        bucket["sample_count"] += 1
        bucket["parse_count" if actual_route == "parse" else "skip_count"] += 1
        if target_class == "target_signal":
            bucket["target_signal_count"] += 1
        else:
            bucket["non_target_count"] += 1

    for reason_family, bucket in by_reason.items():
        sample_count = int(bucket["sample_count"])
        non_target_count = int(bucket["non_target_count"])
        parse_reason_count = int(bucket["parse_count"])
        skip_reason_count = int(bucket["skip_count"])
        bucket["parse_rate"] = ratio(parse_reason_count, sample_count)
        bucket["interception_rate"] = ratio(skip_reason_count, sample_count)
        bucket["false_positive_leak_rate"] = ratio(parse_reason_count, non_target_count) if non_target_count else None
        bucket["target_recall"] = ratio(parse_reason_count, int(bucket["target_signal_count"])) if bucket["target_signal_count"] else None

    return {
        "overall": {
            "sample_count": len(rows),
            "parse_count": parse_count,
            "skip_count": skip_count,
            "interception_rate": ratio(skip_count, len(rows)),
            "expected_route_accuracy": ratio(correct_count, expected_match_count),
        },
        "target_recall": {
            "target_signal_count": target_total,
            "parse_count": target_parse,
            "recall": ratio(target_parse, target_total),
        },
        "non_target_interception": {
            "sample_count": len(rows) - target_total,
            "skip_count": skip_count - (target_total - target_parse),
            "interception_rate": ratio(skip_count - (target_total - target_parse), len(rows) - target_total),
        },
        "by_reason_family": dict(sorted(by_reason.items())),
        "known_course_tokens": sorted(known_course_tokens),
        "config": effective_config,
    }


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
                course_text = f"{dept} {number}{suffix}"
                tokens.update(tokens_for_course_text(course_text))
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


def build_metadata(row: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        label_ids=row.get("label_ids") or [],
        from_header=row.get("from_header") or "",
        subject=row.get("subject") or "",
        snippet=row.get("snippet") or "",
        body_text=row.get("body_text") or "",
        internal_date=row.get("internal_date"),
    )


def normalize_expected_route(row: dict[str, Any]) -> str | None:
    raw = row.get("prefilter_expected_route")
    return str(raw) if isinstance(raw, str) and raw else None


def normalize_reason_family(row: dict[str, Any]) -> str:
    for key in ("prefilter_reason_family", "background_category", "message_kind"):
        raw = row.get(key)
        if isinstance(raw, str) and raw:
            return raw
    return "unknown"


def normalize_target_class(row: dict[str, Any]) -> str:
    raw = row.get("prefilter_target_class")
    if isinstance(raw, str) and raw:
        return raw
    return "target_signal" if normalize_expected_route(row) == "parse" else "non_target"


def ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def render_text_summary(report: dict[str, Any]) -> str:
    overall = report["overall"]
    target = report["target_recall"]
    non_target = report["non_target_interception"]
    lines = [
        f"Sample count: {overall['sample_count']}",
        f"Parse vs skip: {overall['parse_count']} parse, {overall['skip_count']} skip",
        f"Interception rate before LLM: {format_ratio(overall['interception_rate'])}",
        f"Expected-route accuracy: {format_ratio(overall['expected_route_accuracy'])}",
        f"Target recall at prefilter stage: {format_ratio(target['recall'])} ({target['parse_count']}/{target['target_signal_count']})",
        f"Non-target interception rate: {format_ratio(non_target['interception_rate'])} ({non_target['skip_count']}/{non_target['sample_count']})",
        "",
        "By reason family:",
    ]
    for reason_family, bucket in report["by_reason_family"].items():
        lines.append(
            f"- {reason_family}: {bucket['sample_count']} samples, "
            f"skip {bucket['skip_count']}, parse {bucket['parse_count']}, "
            f"interception {format_ratio(bucket['interception_rate'])}, "
            f"leak {format_ratio(bucket['false_positive_leak_rate'])}"
        )
    return "\n".join(lines)


def format_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"


if __name__ == "__main__":
    main()
