#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from jsonschema import Draft202012Validator


EXPECTED_MAIL_TOTAL = 120
EXPECTED_ICS_TOTAL = 40
EXPECTED_SAMPLE_TOTAL = 160
EXPECTED_MAIL_AMBIGUOUS = 42
EXPECTED_ICS_AMBIGUOUS = 14
EXPECTED_AMBIGUOUS_TOTAL = 56
EXPECTED_MIXED_TOTAL = 24

EXPECTED_MAIL_KEEP = 86
EXPECTED_MAIL_DROP = 34
EXPECTED_EVENT_TYPE_KEEP = {
    "deadline": 30,
    "exam": 12,
    "schedule_change": 18,
    "assignment": 12,
    "action_required": 8,
    "announcement": 4,
    "grade": 2,
}
EXPECTED_DROP_BUCKETS = {
    "digest/newsletter/noise": 12,
    "grade-only non-actionable": 8,
    "generic announcement": 8,
    "admin/social noise": 6,
}

EXPECTED_ICS_CLASS_COUNTS = {
    "DUE_CHANGED": 18,
    "CREATED": 10,
    "NO_CHANGE": 6,
    "REMOVED_CANDIDATE": 6,
}
EXPECTED_ICS_AMBIGUOUS_BY_CLASS = {
    "DUE_CHANGED": 7,
    "CREATED": 2,
    "NO_CHANGE": 0,
    "REMOVED_CANDIDATE": 5,
}

AMBIGUITY_TAGS = [
    "relative_time_no_tz",
    "missing_timezone",
    "timezone_abbrev_conflict",
    "dual_due_dates_old_new_unclear",
    "tentative_language",
    "forwarded_thread_conflict",
    "multi_course_collision",
    "datetime_typo_or_impossible",
    "grace_period_soft_deadline",
    "holiday_shift_unspecified",
    "removed_vs_cancelled_unclear",
    "course_alias_mismatch",
]

# Longform gates
MAIL_BODY_MIN_LEN = 900
MAIL_BODY_P50_MIN = 1100
MAIL_BODY_P90_MAX = 1600
ICS_DESC_MIN_LEN = 450
ICS_DESC_P50_MIN = 550
MAIL_INTRA_SUBJECT_SIM_MAX = 0.997
ICS_INTRA_SUBJECT_SIM_MAX = 0.995

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
TOKEN_RE = re.compile(r"[a-z0-9\u4e00-\u9fff]+", re.IGNORECASE)
SENT_SPLIT_RE = re.compile(r"(?<=[\.!?。！？])\s+")


@dataclass
class ValidationState:
    errors: list[str]
    warnings: list[str]

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate synthetic ddlchange_160 dataset.")
    parser.add_argument(
        "--dataset-root",
        default="data/synthetic/ddlchange_160",
        help="Dataset root directory.",
    )
    parser.add_argument(
        "--schema",
        default="tools/labeling/schema/email_label.json",
        help="Mail gold JSON schema path.",
    )
    parser.add_argument(
        "--report",
        default="data/synthetic/ddlchange_160/qa/validation_report.json",
        help="Validation report output path.",
    )
    return parser.parse_args()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_no}: expected JSON object")
            rows.append(payload)
    return rows


def parse_ics_events(path: Path, state: ValidationState) -> dict[str, dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    if "BEGIN:VCALENDAR" not in text or "END:VCALENDAR" not in text:
        state.error(f"{path}: missing VCALENDAR wrapper")
    lines = text.splitlines()
    events: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current is None:
                state.error(f"{path}: END:VEVENT without BEGIN:VEVENT")
            else:
                events.append(current)
            current = None
            continue
        if current is not None and ":" in line:
            key, value = line.split(":", 1)
            current[key] = value

    by_uid: dict[str, dict[str, str]] = {}
    for idx, event in enumerate(events):
        missing = [key for key in ("UID", "DTSTART", "DTEND", "SUMMARY") if key not in event]
        if missing:
            state.error(f"{path}: VEVENT #{idx+1} missing fields {missing}")
            continue
        uid = event["UID"]
        if uid in by_uid:
            state.error(f"{path}: duplicate UID in same snapshot: {uid}")
            continue
        by_uid[uid] = event
    return by_uid


def has_cjk(text: str) -> bool:
    return CJK_RE.search(text) is not None


def ensure_files_exist(dataset_root: Path, state: ValidationState) -> dict[str, Path]:
    files = {
        "manifest": dataset_root / "dataset_manifest.json",
        "taxonomy": dataset_root / "ambiguity_taxonomy.md",
        "readme": dataset_root / "README.md",
        "rewrite_spec": dataset_root / "longform_rewrite_spec.md",
        "mail_raw": dataset_root / "mail" / "raw_mail_120.jsonl",
        "mail_gold": dataset_root / "mail" / "gold_mail_120.jsonl",
        "mail_ambiguity": dataset_root / "mail" / "ambiguity_mail_120.jsonl",
        "ics_index": dataset_root / "ics" / "pair_index_40.jsonl",
        "ics_gold": dataset_root / "ics" / "gold_diff_40.jsonl",
        "ics_ambiguity": dataset_root / "ics" / "ambiguity_40.jsonl",
        "review_mail": dataset_root / "qa" / "review_log_mail.jsonl",
        "review_ics": dataset_root / "qa" / "review_log_ics.jsonl",
    }
    for key, path in files.items():
        if not path.is_file():
            state.error(f"required file missing [{key}]: {path}")
    return files


def _percentile(values: list[int], p: float) -> int:
    if not values:
        return 0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    idx = int((len(ordered) - 1) * p)
    return ordered[idx]


def _stats(values: list[int]) -> dict[str, float]:
    if not values:
        return {"count": 0, "min": 0, "p50": 0, "p90": 0, "max": 0, "avg": 0.0}
    return {
        "count": len(values),
        "min": min(values),
        "p50": _percentile(values, 0.50),
        "p90": _percentile(values, 0.90),
        "max": max(values),
        "avg": round(float(mean(values)), 2),
    }


def _normalize_text(text: str) -> str:
    lowered = text.lower()
    tokens = TOKEN_RE.findall(lowered)
    return " ".join(tokens)


def _token_set(text: str) -> set[str]:
    return set(TOKEN_RE.findall(text.lower()))


def _similarity_score(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    seq = difflib.SequenceMatcher(None, a, b).ratio()
    ta = _token_set(a)
    tb = _token_set(b)
    if ta or tb:
        jac = len(ta & tb) / len(ta | tb)
    else:
        jac = 1.0
    return (0.7 * seq) + (0.3 * jac)


def _max_cluster_similarity(cluster_texts: dict[str, list[str]]) -> tuple[float, dict[str, float]]:
    max_global = 0.0
    per_cluster: dict[str, float] = {}
    for cluster, values in cluster_texts.items():
        max_local = 0.0
        for i in range(len(values)):
            for j in range(i + 1, len(values)):
                score = _similarity_score(values[i], values[j])
                if score > max_local:
                    max_local = score
        per_cluster[cluster] = round(max_local, 4)
        if max_local > max_global:
            max_global = max_local
    return round(max_global, 4), per_cluster


def _mail_guard_pass(*, label: str, event_type: str | None, body_text: str) -> bool:
    text = body_text.lower()
    keyword_map = {
        "deadline": ["deadline", "due", "submission"],
        "exam": ["exam", "attendance", "timing"],
        "schedule_change": ["schedule", "location", "meeting"],
        "assignment": ["assignment", "deliverable", "workflow"],
        "action_required": ["action", "required", "follow-up"],
        "announcement": ["announcement", "operational", "confirm"],
        "grade": ["grade", "regrade", "publication"],
        None: ["informational", "non-actionable", "no new due", "no immediate action"],
    }
    expected = keyword_map.get(event_type, keyword_map[None]) if label == "KEEP" else keyword_map[None]
    return any(token in text for token in expected)


def _ics_guard_pass(*, diff_class: str, focus_text: str) -> bool:
    text = focus_text.lower()
    keyword_map = {
        "DUE_CHANGED": ["due", "shift", "schedule", "changed"],
        "CREATED": ["created", "new", "appears"],
        "NO_CHANGE": ["no-change", "stable", "remain", "unchanged", "no_change", "pair context"],
        "REMOVED_CANDIDATE": ["removed", "absent", "candidate", "debounce"],
    }
    expected = keyword_map.get(diff_class, [])
    return bool(expected) and any(token in text for token in expected)


def _split_sentences(text: str) -> list[str]:
    chunks = [part.strip() for part in SENT_SPLIT_RE.split(text) if part.strip()]
    return chunks if chunks else [text.strip()]


def validate_mail(
    *,
    files: dict[str, Path],
    schema_path: Path,
    state: ValidationState,
) -> dict[str, Any]:
    raw_rows = read_jsonl(files["mail_raw"])
    gold_rows = read_jsonl(files["mail_gold"])
    amb_rows = read_jsonl(files["mail_ambiguity"])

    if len(raw_rows) != EXPECTED_MAIL_TOTAL:
        state.error(f"mail raw rows expected {EXPECTED_MAIL_TOTAL}, got {len(raw_rows)}")
    if len(gold_rows) != EXPECTED_MAIL_TOTAL:
        state.error(f"mail gold rows expected {EXPECTED_MAIL_TOTAL}, got {len(gold_rows)}")
    if len(amb_rows) != EXPECTED_MAIL_TOTAL:
        state.error(f"mail ambiguity rows expected {EXPECTED_MAIL_TOTAL}, got {len(amb_rows)}")

    raw_ids = [row.get("email_id") for row in raw_rows]
    gold_ids = [row.get("email_id") for row in gold_rows]
    amb_ids = [row.get("email_id") for row in amb_rows]

    if len(set(raw_ids)) != len(raw_ids):
        state.error("mail raw email_id contains duplicates")
    if len(set(gold_ids)) != len(gold_ids):
        state.error("mail gold email_id contains duplicates")
    if len(set(amb_ids)) != len(amb_ids):
        state.error("mail ambiguity email_id contains duplicates")

    if set(raw_ids) != set(gold_ids):
        state.error("mail raw/gold email_id sets do not match")
    if set(raw_ids) != set(amb_ids):
        state.error("mail raw/ambiguity email_id sets do not match")

    schema_payload = read_json(schema_path)
    validator = Draft202012Validator(schema_payload)

    label_counter: Counter[str] = Counter()
    keep_event_counter: Counter[str] = Counter()
    drop_bucket_counter: Counter[str] = Counter()
    mixed_mail_count = 0
    body_lengths: list[int] = []

    raw_by_id = {row["email_id"]: row for row in raw_rows if isinstance(row.get("email_id"), str)}
    gold_by_id = {row["email_id"]: row for row in gold_rows if isinstance(row.get("email_id"), str)}

    semantic_total = 0
    semantic_pass = 0
    cluster_texts: dict[str, list[str]] = defaultdict(list)

    for row in raw_rows:
        body = row.get("body_text")
        if isinstance(body, str):
            body_lengths.append(len(body))
            if has_cjk(body):
                mixed_mail_count += 1

    for row in gold_rows:
        email_id = row.get("email_id")
        if not isinstance(email_id, str):
            state.error("mail gold row missing string email_id")
            continue

        errors = sorted(validator.iter_errors(row), key=lambda err: list(err.path))
        if errors:
            state.error(f"mail gold schema invalid for {email_id}: {errors[0].message}")

        label = row.get("label")
        label_counter[str(label)] += 1

        if label == "DROP":
            if row.get("event_type") is not None:
                state.error(f"{email_id}: DROP row must have event_type=null")
            if row.get("action_items") != []:
                state.error(f"{email_id}: DROP row must have action_items=[]")
            raw_extract = row.get("raw_extract")
            if not isinstance(raw_extract, dict):
                state.error(f"{email_id}: DROP row raw_extract must be object")
            else:
                if raw_extract.get("deadline_text") is not None:
                    state.error(f"{email_id}: DROP row raw_extract.deadline_text must be null")
                if raw_extract.get("time_text") is not None:
                    state.error(f"{email_id}: DROP row raw_extract.time_text must be null")
                if raw_extract.get("location_text") is not None:
                    state.error(f"{email_id}: DROP row raw_extract.location_text must be null")
            notes = row.get("notes")
            if isinstance(notes, str) and notes.startswith("drop bucket: "):
                bucket = notes.replace("drop bucket: ", "", 1).strip()
                drop_bucket_counter[bucket] += 1
        elif label == "KEEP":
            event_type = row.get("event_type")
            if not isinstance(event_type, str):
                state.error(f"{email_id}: KEEP row must have string event_type")
            else:
                keep_event_counter[event_type] += 1
        else:
            state.error(f"{email_id}: invalid label {label!r}")

    if label_counter.get("KEEP", 0) != EXPECTED_MAIL_KEEP:
        state.error(f"mail KEEP expected {EXPECTED_MAIL_KEEP}, got {label_counter.get('KEEP', 0)}")
    if label_counter.get("DROP", 0) != EXPECTED_MAIL_DROP:
        state.error(f"mail DROP expected {EXPECTED_MAIL_DROP}, got {label_counter.get('DROP', 0)}")

    if dict(keep_event_counter) != EXPECTED_EVENT_TYPE_KEEP:
        state.error(f"mail keep event distribution mismatch: got {dict(keep_event_counter)}")
    if dict(drop_bucket_counter) != EXPECTED_DROP_BUCKETS:
        state.error(f"mail drop bucket distribution mismatch: got {dict(drop_bucket_counter)}")

    ambiguity_counter = 0
    ambiguous_tag_counter: Counter[str] = Counter()
    for row in amb_rows:
        email_id = row.get("email_id")
        is_ambiguous = bool(row.get("is_ambiguous"))
        tags = row.get("ambiguity_tags")
        alt = row.get("alternative_interpretation")
        if not isinstance(tags, list):
            state.error(f"{email_id}: ambiguity_tags must be array")
            continue
        if is_ambiguous:
            ambiguity_counter += 1
            if len(tags) == 0:
                state.error(f"{email_id}: ambiguous row must have at least one tag")
            if not isinstance(alt, str) or not alt.strip():
                state.error(f"{email_id}: ambiguous row must have alternative_interpretation")
            ambiguous_tag_counter.update([tag for tag in tags if isinstance(tag, str)])
        else:
            if tags:
                state.error(f"{email_id}: non-ambiguous row must have empty ambiguity_tags")
            if alt is not None:
                state.error(f"{email_id}: non-ambiguous row must have alternative_interpretation=null")

    if ambiguity_counter != EXPECTED_MAIL_AMBIGUOUS:
        state.error(f"mail ambiguous expected {EXPECTED_MAIL_AMBIGUOUS}, got {ambiguity_counter}")

    # Longform length gates
    length_stats = _stats(body_lengths)
    if length_stats["min"] < MAIL_BODY_MIN_LEN:
        state.error(f"mail body min length expected >= {MAIL_BODY_MIN_LEN}, got {length_stats['min']}")
    if length_stats["p50"] < MAIL_BODY_P50_MIN:
        state.error(f"mail body p50 expected >= {MAIL_BODY_P50_MIN}, got {length_stats['p50']}")
    if length_stats["p90"] > MAIL_BODY_P90_MAX:
        state.error(f"mail body p90 expected <= {MAIL_BODY_P90_MAX}, got {length_stats['p90']}")

    # Semantic guard + similarity checks
    for email_id, raw_row in raw_by_id.items():
        gold_row = gold_by_id.get(email_id)
        if gold_row is None:
            continue
        body = raw_row.get("body_text")
        if not isinstance(body, str):
            state.error(f"{email_id}: body_text must be string")
            continue
        semantic_total += 1
        label = str(gold_row.get("label"))
        event_type = gold_row.get("event_type") if label == "KEEP" else None
        if _mail_guard_pass(label=label, event_type=event_type if isinstance(event_type, str) else None, body_text=body):
            semantic_pass += 1
        else:
            state.error(f"{email_id}: semantic guard failed for label={label} event_type={event_type}")

        cluster = str(event_type) if label == "KEEP" else "DROP"
        cluster_texts[cluster].append(_normalize_text(body))

    similarity_max, similarity_per_cluster = _max_cluster_similarity(cluster_texts)
    if similarity_max > MAIL_INTRA_SUBJECT_SIM_MAX:
        state.error(
            f"mail intra-subject similarity max expected <= {MAIL_INTRA_SUBJECT_SIM_MAX}, got {similarity_max}"
        )

    semantic_rate = round((semantic_pass / semantic_total), 4) if semantic_total else 0.0

    return {
        "raw_rows": len(raw_rows),
        "gold_rows": len(gold_rows),
        "ambiguity_rows": len(amb_rows),
        "keep_count": label_counter.get("KEEP", 0),
        "drop_count": label_counter.get("DROP", 0),
        "event_type_keep": dict(keep_event_counter),
        "drop_bucket_counts": dict(drop_bucket_counter),
        "ambiguous_count": ambiguity_counter,
        "mixed_mail_count": mixed_mail_count,
        "ambiguous_tag_counter": dict(ambiguous_tag_counter),
        "body_length_stats": length_stats,
        "semantic_guard": {"total": semantic_total, "passed": semantic_pass, "pass_rate": semantic_rate},
        "intra_subject_similarity_max": similarity_max,
        "intra_subject_similarity_by_cluster": similarity_per_cluster,
    }


def validate_ics(*, dataset_root: Path, files: dict[str, Path], state: ValidationState) -> dict[str, Any]:
    pair_rows = read_jsonl(files["ics_index"])
    gold_rows = read_jsonl(files["ics_gold"])
    amb_rows = read_jsonl(files["ics_ambiguity"])

    if len(pair_rows) != EXPECTED_ICS_TOTAL:
        state.error(f"ics pair index rows expected {EXPECTED_ICS_TOTAL}, got {len(pair_rows)}")
    if len(gold_rows) != EXPECTED_ICS_TOTAL:
        state.error(f"ics gold rows expected {EXPECTED_ICS_TOTAL}, got {len(gold_rows)}")
    if len(amb_rows) != EXPECTED_ICS_TOTAL:
        state.error(f"ics ambiguity rows expected {EXPECTED_ICS_TOTAL}, got {len(amb_rows)}")

    pair_ids = [row.get("pair_id") for row in pair_rows]
    gold_ids = [row.get("pair_id") for row in gold_rows]
    amb_ids = [row.get("pair_id") for row in amb_rows]
    if len(set(pair_ids)) != len(pair_ids):
        state.error("ics pair index has duplicate pair_id")
    if len(set(gold_ids)) != len(gold_ids):
        state.error("ics gold has duplicate pair_id")
    if len(set(amb_ids)) != len(amb_ids):
        state.error("ics ambiguity has duplicate pair_id")
    if set(pair_ids) != set(gold_ids):
        state.error("ics pair index/gold pair_id sets do not match")
    if set(pair_ids) != set(amb_ids):
        state.error("ics pair index/ambiguity pair_id sets do not match")

    pair_map = {row["pair_id"]: row for row in pair_rows if isinstance(row.get("pair_id"), str)}
    gold_map = {row["pair_id"]: row for row in gold_rows if isinstance(row.get("pair_id"), str)}
    amb_map = {row["pair_id"]: row for row in amb_rows if isinstance(row.get("pair_id"), str)}

    class_counter: Counter[str] = Counter()
    amb_by_class: Counter[str] = Counter()
    ambiguity_counter = 0
    mixed_ics_count = 0
    ambiguous_tag_counter: Counter[str] = Counter()

    desc_lengths: list[int] = []
    semantic_total = 0
    semantic_pass = 0
    cluster_texts: dict[str, list[str]] = defaultdict(list)

    for pair_id, pair in pair_map.items():
        before_rel = pair.get("before_path")
        after_rel = pair.get("after_path")
        if not isinstance(before_rel, str) or not isinstance(after_rel, str):
            state.error(f"{pair_id}: before_path/after_path must be strings")
            continue

        before_path = dataset_root / before_rel
        after_path = dataset_root / after_rel
        if not before_path.is_file():
            state.error(f"{pair_id}: before file missing: {before_path}")
            continue
        if not after_path.is_file():
            state.error(f"{pair_id}: after file missing: {after_path}")
            continue

        before_text = before_path.read_text(encoding="utf-8")
        after_text = after_path.read_text(encoding="utf-8")
        if has_cjk(before_text) or has_cjk(after_text):
            mixed_ics_count += 1

        before_events = parse_ics_events(before_path, state)
        after_events = parse_ics_events(after_path, state)

        for event_map in (before_events, after_events):
            for uid, ev in event_map.items():
                desc = ev.get("DESCRIPTION")
                if not isinstance(desc, str) or not desc.strip():
                    state.error(f"{pair_id}: uid={uid} missing DESCRIPTION")
                    continue
                desc_lengths.append(len(desc))

        gold = gold_map.get(pair_id)
        if gold is None:
            state.error(f"{pair_id}: missing gold row")
            continue
        diff_class = gold.get("expected_diff_class")
        changed = gold.get("expected_changed_uids")
        removed_requires_history = gold.get("removed_requires_history")
        if not isinstance(diff_class, str):
            state.error(f"{pair_id}: expected_diff_class must be string")
            continue
        class_counter[diff_class] += 1

        if not isinstance(changed, list) or not all(isinstance(uid, str) for uid in changed):
            state.error(f"{pair_id}: expected_changed_uids must be list[str]")
            continue

        focus_texts: list[str] = []

        if diff_class == "DUE_CHANGED":
            for uid in changed:
                if uid not in before_events:
                    state.error(f"{pair_id}: DUE_CHANGED uid {uid} missing in before snapshot")
                    continue
                if uid not in after_events:
                    state.error(f"{pair_id}: DUE_CHANGED uid {uid} missing in after snapshot")
                    continue
                before_dt = (before_events[uid]["DTSTART"], before_events[uid]["DTEND"])
                after_dt = (after_events[uid]["DTSTART"], after_events[uid]["DTEND"])
                if before_dt == after_dt:
                    state.error(f"{pair_id}: DUE_CHANGED uid {uid} has identical DTSTART/DTEND")
                if isinstance(before_events[uid].get("DESCRIPTION"), str):
                    focus_texts.append(before_events[uid]["DESCRIPTION"])
                if isinstance(after_events[uid].get("DESCRIPTION"), str):
                    focus_texts.append(after_events[uid]["DESCRIPTION"])
            if removed_requires_history is not False:
                state.error(f"{pair_id}: DUE_CHANGED must have removed_requires_history=false")
        elif diff_class == "CREATED":
            for uid in changed:
                if uid in before_events:
                    state.error(f"{pair_id}: CREATED uid {uid} unexpectedly exists in before snapshot")
                if uid not in after_events:
                    state.error(f"{pair_id}: CREATED uid {uid} missing in after snapshot")
                if uid in after_events and isinstance(after_events[uid].get("DESCRIPTION"), str):
                    focus_texts.append(after_events[uid]["DESCRIPTION"])
            if removed_requires_history is not False:
                state.error(f"{pair_id}: CREATED must have removed_requires_history=false")
        elif diff_class == "NO_CHANGE":
            if changed:
                state.error(f"{pair_id}: NO_CHANGE must have empty expected_changed_uids")
            before_repr = {(uid, e["DTSTART"], e["DTEND"], e["SUMMARY"]) for uid, e in before_events.items()}
            after_repr = {(uid, e["DTSTART"], e["DTEND"], e["SUMMARY"]) for uid, e in after_events.items()}
            if before_repr != after_repr:
                state.error(f"{pair_id}: NO_CHANGE snapshots differ semantically")
            if removed_requires_history is not False:
                state.error(f"{pair_id}: NO_CHANGE must have removed_requires_history=false")
            non_baseline = [uid for uid in before_events if "baseline" not in uid]
            if non_baseline:
                uid0 = sorted(non_baseline)[0]
                desc0 = before_events[uid0].get("DESCRIPTION")
                if isinstance(desc0, str):
                    focus_texts.append(desc0)
        elif diff_class == "REMOVED_CANDIDATE":
            for uid in changed:
                if uid not in before_events:
                    state.error(f"{pair_id}: REMOVED_CANDIDATE uid {uid} missing in before snapshot")
                if uid in after_events:
                    state.error(f"{pair_id}: REMOVED_CANDIDATE uid {uid} still present in after snapshot")
                if uid in before_events and isinstance(before_events[uid].get("DESCRIPTION"), str):
                    focus_texts.append(before_events[uid]["DESCRIPTION"])
            if removed_requires_history is not True:
                state.error(f"{pair_id}: REMOVED_CANDIDATE must have removed_requires_history=true")
        else:
            state.error(f"{pair_id}: invalid expected_diff_class {diff_class!r}")

        if focus_texts:
            semantic_total += 1
            joined_focus = " ".join(focus_texts)
            if _ics_guard_pass(diff_class=diff_class, focus_text=joined_focus):
                semantic_pass += 1
            else:
                state.error(f"{pair_id}: semantic guard failed for diff_class={diff_class}")
            cluster_texts[diff_class].append(_normalize_text(joined_focus))

        amb = amb_map.get(pair_id)
        if amb is None:
            state.error(f"{pair_id}: missing ambiguity row")
            continue
        is_ambiguous = bool(amb.get("is_ambiguous"))
        tags = amb.get("ambiguity_tags")
        alt = amb.get("alternative_interpretation")
        if not isinstance(tags, list):
            state.error(f"{pair_id}: ambiguity_tags must be array")
            continue

        if is_ambiguous:
            ambiguity_counter += 1
            amb_by_class[diff_class] += 1
            if len(tags) == 0:
                state.error(f"{pair_id}: ambiguous row must have at least one tag")
            if not isinstance(alt, str) or not alt.strip():
                state.error(f"{pair_id}: ambiguous row must have alternative_interpretation")
            ambiguous_tag_counter.update([tag for tag in tags if isinstance(tag, str)])
        else:
            if tags:
                state.error(f"{pair_id}: non-ambiguous row must have empty ambiguity_tags")
            if alt is not None:
                state.error(f"{pair_id}: non-ambiguous row must have alternative_interpretation=null")

    class_counter_full = {key: class_counter.get(key, 0) for key in EXPECTED_ICS_CLASS_COUNTS}
    amb_by_class_full = {key: amb_by_class.get(key, 0) for key in EXPECTED_ICS_AMBIGUOUS_BY_CLASS}

    if class_counter_full != EXPECTED_ICS_CLASS_COUNTS:
        state.error(f"ics class distribution mismatch: got {class_counter_full}")
    if amb_by_class_full != EXPECTED_ICS_AMBIGUOUS_BY_CLASS:
        state.error(f"ics ambiguous-by-class mismatch: got {amb_by_class_full}")
    if ambiguity_counter != EXPECTED_ICS_AMBIGUOUS:
        state.error(f"ics ambiguous expected {EXPECTED_ICS_AMBIGUOUS}, got {ambiguity_counter}")

    # Longform length gates
    desc_stats = _stats(desc_lengths)
    if desc_stats["min"] < ICS_DESC_MIN_LEN:
        state.error(f"ics DESCRIPTION min length expected >= {ICS_DESC_MIN_LEN}, got {desc_stats['min']}")
    if desc_stats["p50"] < ICS_DESC_P50_MIN:
        state.error(f"ics DESCRIPTION p50 expected >= {ICS_DESC_P50_MIN}, got {desc_stats['p50']}")

    similarity_max, similarity_per_cluster = _max_cluster_similarity(cluster_texts)
    if similarity_max > ICS_INTRA_SUBJECT_SIM_MAX:
        state.error(
            f"ics intra-subject similarity max expected <= {ICS_INTRA_SUBJECT_SIM_MAX}, got {similarity_max}"
        )

    semantic_rate = round((semantic_pass / semantic_total), 4) if semantic_total else 0.0

    return {
        "pair_rows": len(pair_rows),
        "gold_rows": len(gold_rows),
        "ambiguity_rows": len(amb_rows),
        "class_counts": class_counter_full,
        "ambiguous_by_class": amb_by_class_full,
        "ambiguous_count": ambiguity_counter,
        "mixed_ics_count": mixed_ics_count,
        "ambiguous_tag_counter": dict(ambiguous_tag_counter),
        "description_length_stats": desc_stats,
        "semantic_guard": {"total": semantic_total, "passed": semantic_pass, "pass_rate": semantic_rate},
        "intra_subject_similarity_max": similarity_max,
        "intra_subject_similarity_by_cluster": similarity_per_cluster,
    }


def validate_manifest(files: dict[str, Path], state: ValidationState) -> dict[str, Any]:
    manifest = read_json(files["manifest"])
    counts = manifest.get("counts", {})
    if counts.get("mail_total") != EXPECTED_MAIL_TOTAL:
        state.error(f"manifest counts.mail_total expected {EXPECTED_MAIL_TOTAL}, got {counts.get('mail_total')}")
    if counts.get("ics_pair_total") != EXPECTED_ICS_TOTAL:
        state.error(f"manifest counts.ics_pair_total expected {EXPECTED_ICS_TOTAL}, got {counts.get('ics_pair_total')}")
    if counts.get("sample_total") != EXPECTED_SAMPLE_TOTAL:
        state.error(f"manifest counts.sample_total expected {EXPECTED_SAMPLE_TOTAL}, got {counts.get('sample_total')}")
    if counts.get("ambiguous_total") != EXPECTED_AMBIGUOUS_TOTAL:
        state.error(
            f"manifest counts.ambiguous_total expected {EXPECTED_AMBIGUOUS_TOTAL}, got {counts.get('ambiguous_total')}"
        )

    if manifest.get("revision") != "longform_mainline":
        state.error(f"manifest revision expected 'longform_mainline', got {manifest.get('revision')!r}")

    longform = manifest.get("longform_profile")
    if not isinstance(longform, dict):
        state.error("manifest missing longform_profile")
    return manifest


def validate_tag_coverage(
    *,
    mail_metrics: dict[str, Any],
    ics_metrics: dict[str, Any],
    state: ValidationState,
) -> dict[str, int]:
    combined = Counter(mail_metrics["ambiguous_tag_counter"]) + Counter(ics_metrics["ambiguous_tag_counter"])
    for tag in AMBIGUITY_TAGS:
        count = combined.get(tag, 0)
        if count < 3:
            state.error(f"ambiguity tag {tag!r} count expected >=3, got {count}")
    extra_tags = set(combined) - set(AMBIGUITY_TAGS)
    if extra_tags:
        state.warn(f"unexpected ambiguity tags found: {sorted(extra_tags)}")
    return dict(combined)


def validate_review_logs(files: dict[str, Path], state: ValidationState) -> dict[str, Any]:
    review_mail = read_jsonl(files["review_mail"])
    review_ics = read_jsonl(files["review_ics"])
    if len(review_mail) != EXPECTED_MAIL_TOTAL:
        state.error(f"review_log_mail rows expected {EXPECTED_MAIL_TOTAL}, got {len(review_mail)}")
    if len(review_ics) != EXPECTED_ICS_TOTAL:
        state.error(f"review_log_ics rows expected {EXPECTED_ICS_TOTAL}, got {len(review_ics)}")

    for row in review_mail:
        if row.get("notes") != "longform_rewrite_passed":
            state.error(f"review_log_mail missing longform marker for {row.get('email_id')}")
    for row in review_ics:
        if row.get("notes") != "longform_rewrite_passed":
            state.error(f"review_log_ics missing longform marker for {row.get('pair_id')}")

    return {"review_mail_rows": len(review_mail), "review_ics_rows": len(review_ics)}


def main() -> int:
    args = parse_args()
    dataset_root = Path(args.dataset_root).resolve()
    schema_path = Path(args.schema).resolve()
    report_path = Path(args.report).resolve()

    state = ValidationState(errors=[], warnings=[])

    if not dataset_root.is_dir():
        print(f"Dataset root not found: {dataset_root}", file=sys.stderr)
        return 1
    if not schema_path.is_file():
        print(f"Schema file not found: {schema_path}", file=sys.stderr)
        return 1

    files = ensure_files_exist(dataset_root, state)
    if state.errors:
        report = {
            "dataset_root": str(dataset_root),
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "passed": False,
            "errors": state.errors,
            "warnings": state.warnings,
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Validation failed early with {len(state.errors)} errors.")
        return 1

    manifest = validate_manifest(files, state)
    mail_metrics = validate_mail(files=files, schema_path=schema_path, state=state)
    ics_metrics = validate_ics(dataset_root=dataset_root, files=files, state=state)
    review_metrics = validate_review_logs(files, state)
    tag_coverage = validate_tag_coverage(mail_metrics=mail_metrics, ics_metrics=ics_metrics, state=state)

    mixed_total = int(mail_metrics["mixed_mail_count"]) + int(ics_metrics["mixed_ics_count"])
    if mixed_total != EXPECTED_MIXED_TOTAL:
        state.error(f"mixed language sample count expected {EXPECTED_MIXED_TOTAL}, got {mixed_total}")

    if (mail_metrics["raw_rows"] + ics_metrics["pair_rows"]) != EXPECTED_SAMPLE_TOTAL:
        state.error(
            "combined sample total mismatch: "
            f"mail={mail_metrics['raw_rows']} + ics={ics_metrics['pair_rows']} != {EXPECTED_SAMPLE_TOTAL}"
        )
    if (mail_metrics["ambiguous_count"] + ics_metrics["ambiguous_count"]) != EXPECTED_AMBIGUOUS_TOTAL:
        state.error(
            "combined ambiguous total mismatch: "
            f"mail={mail_metrics['ambiguous_count']} + ics={ics_metrics['ambiguous_count']} != {EXPECTED_AMBIGUOUS_TOTAL}"
        )

    mail_sem = mail_metrics["semantic_guard"]
    ics_sem = ics_metrics["semantic_guard"]
    overall_sem_total = int(mail_sem["total"]) + int(ics_sem["total"])
    overall_sem_pass = int(mail_sem["passed"]) + int(ics_sem["passed"])
    overall_sem_rate = round((overall_sem_pass / overall_sem_total), 4) if overall_sem_total else 0.0

    if overall_sem_rate < 1.0:
        state.error(f"semantic guard pass rate expected 1.0, got {overall_sem_rate}")

    report = {
        "dataset_id": manifest.get("dataset_id", "ddlchange_160"),
        "dataset_root": str(dataset_root),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "passed": len(state.errors) == 0,
        "summary": {
            "sample_total": mail_metrics["raw_rows"] + ics_metrics["pair_rows"],
            "mail_total": mail_metrics["raw_rows"],
            "ics_pair_total": ics_metrics["pair_rows"],
            "ambiguous_total": mail_metrics["ambiguous_count"] + ics_metrics["ambiguous_count"],
            "mixed_language_total": mixed_total,
        },
        "metrics": {
            "mail": {
                "keep_count": mail_metrics["keep_count"],
                "drop_count": mail_metrics["drop_count"],
                "event_type_keep": mail_metrics["event_type_keep"],
                "drop_bucket_counts": mail_metrics["drop_bucket_counts"],
                "ambiguous_count": mail_metrics["ambiguous_count"],
                "mixed_mail_count": mail_metrics["mixed_mail_count"],
            },
            "ics": {
                "class_counts": ics_metrics["class_counts"],
                "ambiguous_by_class": ics_metrics["ambiguous_by_class"],
                "ambiguous_count": ics_metrics["ambiguous_count"],
                "mixed_ics_count": ics_metrics["mixed_ics_count"],
            },
            "mail_body_length_stats": mail_metrics["body_length_stats"],
            "ics_description_length_stats": ics_metrics["description_length_stats"],
            "intra_subject_similarity_max": {
                "mail": mail_metrics["intra_subject_similarity_max"],
                "ics": ics_metrics["intra_subject_similarity_max"],
            },
            "intra_subject_similarity_by_cluster": {
                "mail": mail_metrics["intra_subject_similarity_by_cluster"],
                "ics": ics_metrics["intra_subject_similarity_by_cluster"],
            },
            "semantic_guardrail_pass_rate": {
                "mail": mail_sem["pass_rate"],
                "ics": ics_sem["pass_rate"],
                "overall": overall_sem_rate,
            },
            "ambiguity_tag_coverage": tag_coverage,
            "review_logs": review_metrics,
        },
        "errors": state.errors,
        "warnings": state.warnings,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(
        f"Validation {'PASSED' if report['passed'] else 'FAILED'}: "
        f"errors={len(state.errors)} warnings={len(state.warnings)} report={report_path}"
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
