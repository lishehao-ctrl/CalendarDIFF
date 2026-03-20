#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Literal

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_GMAIL_PATH = REPO_ROOT / "tests" / "fixtures" / "private" / "email_pool" / "year_timeline_gmail" / "samples.jsonl"
FULL_SIM_PATH = REPO_ROOT / "tests" / "fixtures" / "private" / "email_pool" / "year_timeline_full_sim" / "samples.jsonl"
OUTPUT_DIR = REPO_ROOT / "data" / "secondary_filter"
TRAIN_PATH = OUTPUT_DIR / "gmail_train.jsonl"
EVAL_PATH = OUTPUT_DIR / "gmail_eval.jsonl"
SHADOW_PATH = OUTPUT_DIR / "gmail_shadow_candidates.jsonl"
HIGH_RISK_EVAL_PATH = OUTPUT_DIR / "gmail_high_risk_eval.jsonl"
REPORT_PATH = OUTPUT_DIR / "DATASET_REPORT.md"
SPEC_OUTPUT_PATH = REPO_ROOT / "specs" / "backend" / "2026-03-20-gmail-secondary-filter" / "OUTPUT.md"

Split = Literal["train", "eval", "shadow"]
Label = Literal["relevant", "non_target", "uncertain"]
Source = Literal["synthetic", "pseudo_labeled"]

TRAIN_LABEL_QUOTAS = {"relevant": 3500, "non_target": 4301, "uncertain": 4199}
EVAL_LABEL_QUOTAS = {"relevant": 420, "non_target": 600, "uncertain": 480}
SHADOW_LABEL_QUOTAS = {"relevant": 900, "non_target": 1200, "uncertain": 900}
LABEL_QUOTAS: dict[Split, dict[Label, int]] = {
    "train": TRAIN_LABEL_QUOTAS,
    "eval": EVAL_LABEL_QUOTAS,
    "shadow": SHADOW_LABEL_QUOTAS,
}
SPLIT_TO_QUARTERS: dict[Split, tuple[str, ...]] = {
    "train": ("WI", "SP"),
    "eval": ("SU",),
    "shadow": ("FA",),
}

REQUIRED_PATTERN_FAMILIES = {
    "shipping_subscription_bait",
    "recruiting_career_internship_bait",
    "newsletter_digest_campus_weekly",
    "lms_wrapper_only",
    "piazza_ed_forum_summary",
    "academic_admin_noise",
    "broad_audience_deadline_mutation",
    "explicit_graded_item_unchanged",
    "real_due_date_change",
    "new_graded_item_announcement",
    "bulk_schedule_mutation",
    "exam_logistics_non_target",
    "exam_time_change_target",
    "mixed_signal_uncertain",
}
EXTRA_PATTERN_FAMILIES = {
    "quoted_thread_conflict",
    "stale_deadline_in_reply_chain",
    "weak_sender_strong_time_signal",
    "strong_sender_weak_signal",
    "academic_wrapper_with_true_change",
}
ALL_PATTERN_FAMILIES = REQUIRED_PATTERN_FAMILIES | EXTRA_PATTERN_FAMILIES
RELEVANT_LIKE_FAMILIES = {
    "quoted_thread_conflict",
    "stale_deadline_in_reply_chain",
    "strong_sender_weak_signal",
}
TARGET_UNCERTAIN_SOURCE_FAMILIES = {
    "real_due_date_change",
    "new_graded_item_announcement",
    "exam_time_change_target",
    "broad_audience_deadline_mutation",
    "bulk_schedule_mutation",
    "academic_wrapper_with_true_change",
    "weak_sender_strong_time_signal",
}

CLUSTER_BLUEPRINTS: dict[str, dict[Label, str]] = {
    "shipping_like": {
        "relevant": "weak_sender_strong_time_signal",
        "non_target": "shipping_subscription_bait",
        "uncertain": "mixed_signal_uncertain",
    },
    "recruiting_like": {
        "relevant": "weak_sender_strong_time_signal",
        "non_target": "recruiting_career_internship_bait",
        "uncertain": "mixed_signal_uncertain",
    },
    "digest_like": {
        "relevant": "broad_audience_deadline_mutation",
        "non_target": "newsletter_digest_campus_weekly",
        "uncertain": "mixed_signal_uncertain",
    },
    "lms_like": {
        "relevant": "academic_wrapper_with_true_change",
        "non_target": "lms_wrapper_only",
        "uncertain": "quoted_thread_conflict",
    },
    "forum_like": {
        "relevant": "academic_wrapper_with_true_change",
        "non_target": "piazza_ed_forum_summary",
        "uncertain": "stale_deadline_in_reply_chain",
    },
    "admin_like": {
        "relevant": "broad_audience_deadline_mutation",
        "non_target": "academic_admin_noise",
        "uncertain": "strong_sender_weak_signal",
    },
    "exam_like": {
        "relevant": "exam_time_change_target",
        "non_target": "exam_logistics_non_target",
        "uncertain": "quoted_thread_conflict",
    },
    "static_like": {
        "relevant": "real_due_date_change",
        "non_target": "explicit_graded_item_unchanged",
        "uncertain": "stale_deadline_in_reply_chain",
    },
    "new_item_like": {
        "relevant": "new_graded_item_announcement",
        "non_target": "explicit_graded_item_unchanged",
        "uncertain": "mixed_signal_uncertain",
    },
    "bulk_like": {
        "relevant": "bulk_schedule_mutation",
        "non_target": "academic_admin_noise",
        "uncertain": "strong_sender_weak_signal",
    },
}

CLUSTER_BUNDLE_COUNTS: dict[Split, dict[str, int]] = {
    "train": {
        "shipping_like": 220,
        "recruiting_like": 220,
        "digest_like": 220,
        "lms_like": 300,
        "forum_like": 300,
        "admin_like": 260,
        "exam_like": 260,
        "static_like": 320,
        "new_item_like": 300,
        "bulk_like": 300,
    },
    "eval": {
        "shipping_like": 36,
        "recruiting_like": 34,
        "digest_like": 34,
        "lms_like": 46,
        "forum_like": 46,
        "admin_like": 36,
        "exam_like": 36,
        "static_like": 48,
        "new_item_like": 42,
        "bulk_like": 42,
    },
    "shadow": {
        "shipping_like": 80,
        "recruiting_like": 80,
        "digest_like": 76,
        "lms_like": 104,
        "forum_like": 104,
        "admin_like": 88,
        "exam_like": 88,
        "static_like": 108,
        "new_item_like": 96,
        "bulk_like": 96,
    },
}

FAMILY_LABEL: dict[str, Label] = {
    "shipping_subscription_bait": "non_target",
    "recruiting_career_internship_bait": "non_target",
    "newsletter_digest_campus_weekly": "non_target",
    "lms_wrapper_only": "non_target",
    "piazza_ed_forum_summary": "non_target",
    "academic_admin_noise": "non_target",
    "broad_audience_deadline_mutation": "relevant",
    "explicit_graded_item_unchanged": "non_target",
    "real_due_date_change": "relevant",
    "new_graded_item_announcement": "relevant",
    "bulk_schedule_mutation": "relevant",
    "exam_logistics_non_target": "non_target",
    "exam_time_change_target": "relevant",
    "mixed_signal_uncertain": "uncertain",
    "quoted_thread_conflict": "uncertain",
    "stale_deadline_in_reply_chain": "uncertain",
    "weak_sender_strong_time_signal": "relevant",
    "strong_sender_weak_signal": "uncertain",
    "academic_wrapper_with_true_change": "relevant",
}

FAMILY_BAIT_TERMS: dict[str, tuple[str, ...]] = {
    "shipping_subscription_bait": ("project", "assignment", "quiz", "deadline", "due"),
    "recruiting_career_internship_bait": ("project", "submission", "deadline", "final"),
    "newsletter_digest_campus_weekly": ("assignment", "final", "project", "quiz"),
    "lms_wrapper_only": ("assignment", "submission", "grade"),
    "piazza_ed_forum_summary": ("quiz", "project", "assignment"),
    "academic_admin_noise": ("submission", "grade", "deadline"),
    "broad_audience_deadline_mutation": ("assignment", "deadline", "project"),
    "explicit_graded_item_unchanged": ("grade", "assignment", "unchanged"),
    "real_due_date_change": ("due", "deadline", "project"),
    "new_graded_item_announcement": ("assignment", "quiz", "project"),
    "bulk_schedule_mutation": ("future", "assignment", "schedule"),
    "exam_logistics_non_target": ("final", "exam", "quiz"),
    "exam_time_change_target": ("final", "exam", "scheduled"),
    "mixed_signal_uncertain": ("assignment", "project", "quiz"),
    "quoted_thread_conflict": ("deadline", "assignment", "reply"),
    "stale_deadline_in_reply_chain": ("deadline", "thread", "updated"),
    "weak_sender_strong_time_signal": ("project", "due", "deadline"),
    "strong_sender_weak_signal": ("assignment", "maybe", "follow-up"),
    "academic_wrapper_with_true_change": ("assignment", "update", "submission"),
}

FAMILY_WRAPPER_STYLES: dict[str, tuple[str, ...]] = {
    "shipping_subscription_bait": ("promo_footer", "short_alert", "forwarded_notice"),
    "recruiting_career_internship_bait": ("short_alert", "digest_list", "reply_chain"),
    "newsletter_digest_campus_weekly": ("digest_list", "forwarded_notice", "newsletter_block"),
    "lms_wrapper_only": ("canvas_wrapper", "reply_chain", "forwarded_notice"),
    "piazza_ed_forum_summary": ("forum_digest", "reply_chain", "canvas_wrapper"),
    "academic_admin_noise": ("plain_notice", "digest_list", "department_notice"),
    "broad_audience_deadline_mutation": ("department_notice", "plain_notice", "newsletter_block"),
    "explicit_graded_item_unchanged": ("plain_notice", "canvas_wrapper", "department_notice"),
    "real_due_date_change": ("plain_notice", "reply_chain", "department_notice"),
    "new_graded_item_announcement": ("plain_notice", "canvas_wrapper", "forwarded_notice"),
    "bulk_schedule_mutation": ("department_notice", "plain_notice", "reply_chain"),
    "exam_logistics_non_target": ("department_notice", "plain_notice", "digest_list"),
    "exam_time_change_target": ("department_notice", "plain_notice", "reply_chain"),
    "mixed_signal_uncertain": ("reply_chain", "canvas_wrapper", "forwarded_notice"),
    "quoted_thread_conflict": ("reply_chain", "forwarded_notice", "canvas_wrapper"),
    "stale_deadline_in_reply_chain": ("reply_chain", "forwarded_notice", "forum_digest"),
    "weak_sender_strong_time_signal": ("forwarded_notice", "short_alert", "reply_chain"),
    "strong_sender_weak_signal": ("department_notice", "plain_notice", "reply_chain"),
    "academic_wrapper_with_true_change": ("canvas_wrapper", "reply_chain", "forum_digest"),
}

LEAK_PHRASES = {
    "this is intentionally gray",
    "should not be hard-suppressed",
    "wrapper subject aside",
    "should still reach the llm",
    "this should be suppressible",
    "this mailbox is not monitored",
    "should not create a canonical event",
    "suppress before llm",
}
PLACEHOLDER_PHRASES = {"COURSE", "ITEM1", "ITEM2", "EVENT_NAME"}
COURSE_TOKEN_RE = re.compile(r"\b([A-Za-z]{2,5})[\s\-]?(\d{1,3}[A-Za-z]?)\b")
EMAIL_RE = re.compile(r"<([^>]+)>")
QUOTE_PREFIX_RE = re.compile(r"^>\s*", re.M)
NON_ACADEMIC_DOMAIN_HINTS = (
    "parcelpilot.com",
    "shipdeck.com",
    "careers.",
    "billing.",
    "news.",
    "digest.",
    "alerts.",
)
ACADEMIC_DOMAIN_HINTS = (
    "ucsd.edu",
    "canvas",
    "gradescope",
    "piazza",
    "edstem",
    "courses.",
    "teaching.",
    "department.",
)
UNCHANGED_HINTS = (
    "unchanged",
    "still the same",
    "no change to the due date",
    "the due time remains",
    "no update to the assignment deadline",
    "deadline stays as posted",
)
RELEVANT_HINTS = (
    "is now due",
    " is due ",
    "the current due time is",
    "the updated due time is",
    "the new exam time is",
    "moved to",
    "rescheduled to",
    "now lands at",
    "now moves to",
    "posted and due",
    "will be held at",
    "future items now move",
)
HEDGING_HINTS = (
    "likely",
    "tentatively",
    "expect to",
    "should still follow the current canvas entry",
    "we are checking",
    "do not rely on this yet",
)
ACADEMIC_NON_TARGET_HINTS = (
    "office hours",
    "discussion",
    "waitlist",
    "roster",
    "format details",
    "review session",
    "grade posted",
    "feedback available",
)


@dataclass(frozen=True)
class Donor:
    sample_id: str
    quarter: str
    source_bucket: str
    source_kind: str
    pattern_family: str
    label: Label
    from_header: str
    subject: str
    body_text: str
    snippet: str
    message_id: str | None
    notify_email: str | None
    known_course_tokens: list[str]
    course_label: str | None
    raw_type: str | None
    event_name: str | None
    due_phrase: str | None
    previous_due_phrase: str | None
    sender_domain: str


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    split: Split
    quarter: str
    intended_label: Label
    pattern_family: str
    cluster_id: str
    neighbor_key: str
    sender_persona: str
    sender_domain_style: str
    wrapper_style: str
    bait_terms: tuple[str, ...]
    course_identity_style: str
    ambiguity_level: str
    body_has_authoritative_line: bool
    subject_is_misleading: bool
    has_quoted_thread: bool
    donor_family: str
    source_mode: Source


@dataclass(frozen=True)
class RawDraft:
    scenario: Scenario
    sample_id: str
    source: Source
    notify_email: str | None
    message_id: str | None
    from_header: str
    subject: str
    snippet: str
    body_text: str
    label_ids: list[str]
    known_course_tokens: list[str]
    metadata_quarter: str
    metadata_pattern_family: str
    derived_from: str


@dataclass(frozen=True)
class BlindLabelResult:
    sample_id: str
    label: Label
    confidence: float
    reason: str
    suppress_before_llm: bool


@dataclass(frozen=True)
class ReviewDecision:
    sample_id: str
    decision: Literal["keep", "reject"]
    final_label: Label
    final_confidence: float
    final_reason: str
    quality_penalty: float
    correction_applied: bool


def main() -> None:
    donors = load_donors()
    scenario_grid = phase1_build_scenario_grid()
    raw_drafts = phase2_generate_raw_drafts(scenarios=scenario_grid, donors=donors)
    mutated_drafts = phase3_adversarial_mutation(raw_drafts=raw_drafts, donors=donors)
    combined_drafts = raw_drafts + mutated_drafts
    blind_labels = phase4_blind_label_pass(combined_drafts)
    review_decisions = phase5_reviewer_pass(combined_drafts, blind_labels)
    datasets = phase6_curate_dataset(combined_drafts, blind_labels, review_decisions)
    validate_outputs(datasets)
    write_outputs(datasets)


def load_donors() -> dict[str, list[Donor]]:
    core_rows = load_jsonl(CORE_GMAIL_PATH)
    full_rows = load_jsonl(FULL_SIM_PATH)
    background_rows = [row for row in full_rows if row.get("full_sim_layer") == "background_noise"]

    donors_by_key: dict[str, list[Donor]] = defaultdict(list)
    for row in core_rows:
        label, family = classify_core_donor(row)
        donor = make_donor(row=row, label=label, pattern_family=family, source_bucket="year_timeline_gmail")
        for key in donor_index_keys(donor):
            donors_by_key[key].append(donor)
    for row in background_rows:
        label, family = classify_background_donor(row)
        donor = make_donor(row=row, label=label, pattern_family=family, source_bucket="year_timeline_full_sim")
        for key in donor_index_keys(donor):
            donors_by_key[key].append(donor)
    return donors_by_key


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def classify_core_donor(row: dict[str, Any]) -> tuple[Label, str]:
    kind = str(row.get("message_kind") or "")
    text = lower_blob(row)
    if kind == "atomic_new":
        return "relevant", "new_graded_item_announcement"
    if kind == "directive":
        return "relevant", "bulk_schedule_mutation"
    if kind == "atomic_change":
        if any(token in text for token in ("exam", "midterm", "final")):
            return "relevant", "exam_time_change_target"
        if "all sections" in text or "all students" in text:
            return "relevant", "broad_audience_deadline_mutation"
        return "relevant", "real_due_date_change"
    if kind == "reminder_noise":
        return "non_target", "explicit_graded_item_unchanged"
    if kind == "lab_noise":
        return "non_target", "academic_admin_noise"
    return "non_target", "exam_logistics_non_target" if "exam" in text or "final" in text else "academic_admin_noise"


def classify_background_donor(row: dict[str, Any]) -> tuple[Label, str]:
    category = str(row.get("background_category") or "")
    text = lower_blob(row)
    sender = str(row.get("from_header") or "").lower()
    if category in {"commerce", "package_subscription"}:
        return "non_target", "shipping_subscription_bait"
    if category == "jobs_and_careers":
        return "non_target", "recruiting_career_internship_bait"
    if category == "newsletter":
        return "non_target", "newsletter_digest_campus_weekly"
    if category == "lms_wrapper_noise":
        if "piazza" in sender or "ed discussion" in sender or "forum" in text:
            if any(phrase in text for phrase in UNCHANGED_HINTS):
                return "non_target", "piazza_ed_forum_summary"
            return "uncertain", "piazza_ed_forum_summary"
        if any(phrase in text for phrase in UNCHANGED_HINTS):
            return "non_target", "lms_wrapper_only"
        return "uncertain", "quoted_thread_conflict"
    if category == "calendar_wrapper":
        return "uncertain", "mixed_signal_uncertain"
    if category == "academic_non_target":
        if any(term in text for term in ("review session", "format", "seating", "materials")):
            return "non_target", "exam_logistics_non_target"
        if any(phrase in text for phrase in UNCHANGED_HINTS):
            return "non_target", "explicit_graded_item_unchanged"
        return "uncertain", "strong_sender_weak_signal"
    if category in {"campus_admin", "campus_general", "student_services", "housing"}:
        return "non_target", "academic_admin_noise"
    return "non_target", "academic_admin_noise"


def make_donor(*, row: dict[str, Any], label: Label, pattern_family: str, source_bucket: str) -> Donor:
    quarter = derive_quarter(row)
    from_header = str(row.get("from_header") or "")
    draft = row.get("expected_semantic_event_draft")
    raw_type = str(draft.get("raw_type") or "") if isinstance(draft, dict) else ""
    event_name = str(draft.get("event_name") or "") if isinstance(draft, dict) else ""
    due_phrase = None
    previous_due_phrase = None
    if isinstance(draft, dict) and draft.get("due_date") and draft.get("due_time"):
        due_phrase = f"{draft['due_date']} {draft['due_time']} UTC"
    body = str(row.get("body_text") or "")
    due_matches = re.findall(r"(20\d{2}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})", body)
    if due_matches:
        if due_phrase is None:
            due_phrase = f"{due_matches[-1][0]} {due_matches[-1][1]} UTC"
        if len(due_matches) > 1:
            previous_due_phrase = f"{due_matches[0][0]} {due_matches[0][1]} UTC"
    if previous_due_phrase is None:
        prev = row.get("previous_due_iso")
        if prev:
            match = re.search(r"(20\d{2}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})", str(prev))
            if match:
                previous_due_phrase = f"{match.group(1)} {match.group(2)} UTC"
    return Donor(
        sample_id=str(row.get("sample_id") or row.get("message_id") or ""),
        quarter=quarter,
        source_bucket=source_bucket,
        source_kind=str(row.get("sample_source") or "synthetic"),
        pattern_family=pattern_family,
        label=label,
        from_header=from_header,
        subject=str(row.get("subject") or ""),
        body_text=body,
        snippet=normalize_snippet(row.get("snippet"), body),
        message_id=str(row.get("message_id")) if row.get("message_id") else None,
        notify_email=extract_notify_email(from_header),
        known_course_tokens=collect_course_tokens(row),
        course_label=normalize_course_label(str(row.get("course_label") or row.get("course_hint") or "")) or donor_course_from_draft(draft),
        raw_type=raw_type or None,
        event_name=event_name or None,
        due_phrase=due_phrase,
        previous_due_phrase=previous_due_phrase,
        sender_domain=extract_domain(from_header),
    )


def donor_index_keys(donor: Donor) -> Iterable[str]:
    yield "any"
    yield f"quarter:{donor.quarter}"
    yield f"label:{donor.label}"
    yield f"family:{donor.pattern_family}"
    yield f"quarter:{donor.quarter}:label:{donor.label}"
    yield f"quarter:{donor.quarter}:family:{donor.pattern_family}"
    if donor.course_label:
        yield f"course:{donor.course_label}"


def phase1_build_scenario_grid() -> list[Scenario]:
    scenarios: list[Scenario] = []
    for split, cluster_counts in CLUSTER_BUNDLE_COUNTS.items():
        quarter_cycle = SPLIT_TO_QUARTERS[split]
        global_index = 0
        for cluster_name, bundle_count in cluster_counts.items():
            for bundle_index in range(bundle_count):
                quarter = quarter_cycle[(bundle_index + len(cluster_name)) % len(quarter_cycle)]
                shared = shared_bundle_features(cluster_name=cluster_name, split=split, quarter=quarter, bundle_index=bundle_index)
                for label in ("relevant", "non_target", "uncertain"):
                    family = CLUSTER_BLUEPRINTS[cluster_name][label]  # type: ignore[index]
                    scenario = Scenario(
                        scenario_id=f"scn-{split}-{cluster_name}-{bundle_index:05d}-{label}",
                        split=split,
                        quarter=quarter,
                        intended_label=label,  # type: ignore[arg-type]
                        pattern_family=family,
                        cluster_id=cluster_name,
                        neighbor_key=f"{split}:{cluster_name}:{bundle_index:05d}",
                        sender_persona=shared["sender_persona"],
                        sender_domain_style=shared["sender_domain_style"],
                        wrapper_style=shared["wrapper_style"],
                        bait_terms=shared["bait_terms"],
                        course_identity_style=shared["course_identity_style"],
                        ambiguity_level=shared["ambiguity_level"],
                        body_has_authoritative_line=shared["body_has_authoritative_line"] if label != "non_target" else False,
                        subject_is_misleading=shared["subject_is_misleading"],
                        has_quoted_thread=shared["has_quoted_thread"] if label != "non_target" or cluster_name in {"lms_like", "forum_like"} else False,
                        donor_family=shared["donor_family_by_label"][label],
                        source_mode="pseudo_labeled",
                    )
                    scenarios.append(scenario)
                    global_index += 1
    return scenarios


def shared_bundle_features(*, cluster_name: str, split: Split, quarter: str, bundle_index: int) -> dict[str, Any]:
    bait = FAMILY_BAIT_TERMS[CLUSTER_BLUEPRINTS[cluster_name]["non_target"]]
    sender_personas = {
        "shipping_like": ("generic_no_reply", "course_staff_forward", "student_forward"),
        "recruiting_like": ("generic_no_reply", "course_staff_forward", "student_forward"),
        "digest_like": ("campus_digest", "department_digest", "course_staff_alias"),
        "lms_like": ("lms_wrapper", "course_staff_alias", "ta_sender"),
        "forum_like": ("forum_digest", "course_staff_alias", "ta_sender"),
        "admin_like": ("department_admin", "course_staff_alias", "testing_center"),
        "exam_like": ("testing_center", "professor_sender", "course_staff_alias"),
        "static_like": ("course_staff_alias", "ta_sender", "lms_wrapper"),
        "new_item_like": ("course_staff_alias", "lms_wrapper", "professor_sender"),
        "bulk_like": ("course_staff_alias", "department_admin", "professor_sender"),
    }[cluster_name]
    domain_styles = {
        "shipping_like": ("mail.ops", "notify.mail", "messages"),
        "recruiting_like": ("careers", "recruiting", "mail.jobs"),
        "digest_like": ("digest", "news", "weekly"),
        "lms_like": ("canvas", "gradescope", "courses"),
        "forum_like": ("piazza", "edstem", "forum"),
        "admin_like": ("department", "students", "registrar"),
        "exam_like": ("testing", "courses", "faculty"),
        "static_like": ("courses", "teaching", "canvas"),
        "new_item_like": ("courses", "canvas", "faculty"),
        "bulk_like": ("courses", "faculty", "department"),
    }[cluster_name]
    wrapper_styles = {
        "shipping_like": ("promo_footer", "forwarded_notice", "short_alert"),
        "recruiting_like": ("short_alert", "reply_chain", "digest_list"),
        "digest_like": ("digest_list", "newsletter_block", "forwarded_notice"),
        "lms_like": ("canvas_wrapper", "reply_chain", "forwarded_notice"),
        "forum_like": ("forum_digest", "reply_chain", "canvas_wrapper"),
        "admin_like": ("department_notice", "plain_notice", "digest_list"),
        "exam_like": ("department_notice", "reply_chain", "plain_notice"),
        "static_like": ("plain_notice", "reply_chain", "canvas_wrapper"),
        "new_item_like": ("plain_notice", "canvas_wrapper", "forwarded_notice"),
        "bulk_like": ("department_notice", "plain_notice", "reply_chain"),
    }[cluster_name]
    course_styles = ("compact", "spaced", "dash", "catalog")
    ambiguity_cycle = ("low", "medium", "high")
    donor_by_label = {
        "relevant": CLUSTER_BLUEPRINTS[cluster_name]["relevant"],
        "non_target": CLUSTER_BLUEPRINTS[cluster_name]["non_target"],
        "uncertain": CLUSTER_BLUEPRINTS[cluster_name]["uncertain"],
    }
    return {
        "sender_persona": sender_personas[(bundle_index + len(split)) % len(sender_personas)],
        "sender_domain_style": domain_styles[(bundle_index + len(quarter)) % len(domain_styles)],
        "wrapper_style": wrapper_styles[(bundle_index + len(cluster_name)) % len(wrapper_styles)],
        "bait_terms": (
            bait[(bundle_index + 0) % len(bait)],
            bait[(bundle_index + 1) % len(bait)],
        ),
        "course_identity_style": course_styles[(bundle_index + len(cluster_name)) % len(course_styles)],
        "ambiguity_level": ambiguity_cycle[(bundle_index + len(quarter)) % len(ambiguity_cycle)],
        "body_has_authoritative_line": cluster_name not in {"shipping_like", "recruiting_like"},
        "subject_is_misleading": cluster_name in {"shipping_like", "recruiting_like", "digest_like", "lms_like", "forum_like"} or bundle_index % 3 == 0,
        "has_quoted_thread": cluster_name in {"lms_like", "forum_like", "exam_like"} or bundle_index % 4 == 0,
        "donor_family_by_label": donor_by_label,
    }


def phase2_generate_raw_drafts(*, scenarios: list[Scenario], donors: dict[str, list[Donor]]) -> list[RawDraft]:
    drafts: list[RawDraft] = []
    for index, scenario in enumerate(scenarios):
        donor = choose_donor(scenario=scenario, donors=donors, ordinal=index)
        drafts.append(generate_raw_draft(scenario=scenario, donor=donor, ordinal=index))
    return drafts


def choose_donor(*, scenario: Scenario, donors: dict[str, list[Donor]], ordinal: int) -> Donor:
    keys = [
        f"quarter:{scenario.quarter}:family:{scenario.donor_family}",
        f"quarter:{scenario.quarter}:label:{FAMILY_LABEL[scenario.donor_family]}",
        f"family:{scenario.donor_family}",
        f"label:{FAMILY_LABEL[scenario.donor_family]}",
        "any",
    ]
    pool: list[Donor] = []
    for key in keys:
        pool = donors.get(key, [])
        if pool:
            break
    if not pool:
        raise RuntimeError(f"no donor pool for {scenario.donor_family}")
    return pool[ordinal % len(pool)]


def generate_raw_draft(*, scenario: Scenario, donor: Donor, ordinal: int) -> RawDraft:
    course_label = render_course_label(donor.course_label or "CSE120", style=scenario.course_identity_style)
    course_tokens = render_course_tokens(course_label) if family_needs_course_context(scenario.pattern_family) else []
    bait_terms = list(scenario.bait_terms)
    sender = apply_sender_variation(
        render_from_header(scenario=scenario, donor=donor, course_label=course_label, ordinal=ordinal),
        scenario=scenario,
        donor=donor,
        course_label=course_label,
        ordinal=ordinal,
    )
    subject = apply_subject_variation(
        render_subject(scenario=scenario, donor=donor, course_label=course_label, bait_terms=bait_terms, ordinal=ordinal),
        scenario=scenario,
        donor=donor,
        course_label=course_label,
        bait_terms=bait_terms,
        ordinal=ordinal,
    )
    body = apply_body_variation(
        render_body(scenario=scenario, donor=donor, course_label=course_label, bait_terms=bait_terms, ordinal=ordinal),
        scenario=scenario,
        donor=donor,
        course_label=course_label,
        bait_terms=bait_terms,
        ordinal=ordinal,
    )
    if scenario.intended_label == "non_target" and family_needs_course_context(scenario.pattern_family) and not course_tokens and donor.known_course_tokens:
        course_tokens = donor.known_course_tokens[:]
    snippet = normalize_snippet(None, body)
    message_id = donor.message_id if scenario.source_mode == "pseudo_labeled" else None
    return RawDraft(
        scenario=scenario,
        sample_id=f"raw-{scenario.scenario_id}",
        source=scenario.source_mode,
        notify_email=extract_notify_email(sender),
        message_id=message_id,
        from_header=sender,
        subject=subject,
        snippet=snippet,
        body_text=body,
        label_ids=["INBOX"],
        known_course_tokens=course_tokens,
        metadata_quarter=scenario.quarter,
        metadata_pattern_family=scenario.pattern_family,
        derived_from=donor.sample_id,
    )


def phase3_adversarial_mutation(*, raw_drafts: list[RawDraft], donors: dict[str, list[Donor]]) -> list[RawDraft]:
    mutations: list[RawDraft] = []
    for ordinal, draft in enumerate(raw_drafts):
        mutation_specs = mutation_targets_for_draft(draft)
        for local_index, target in enumerate(mutation_specs):
            donor = choose_donor(
                scenario=replace(
                    draft.scenario,
                    intended_label=target["label"],  # type: ignore[arg-type]
                    pattern_family=target["family"],
                    donor_family=target["donor_family"],
                    source_mode="synthetic",
                    ambiguity_level=target["ambiguity_level"],
                    body_has_authoritative_line=target["authoritative"],
                    has_quoted_thread=target["quoted_thread"],
                    subject_is_misleading=target["misleading_subject"],
                ),
                donors=donors,
                ordinal=ordinal + local_index + 7,
            )
            mutated = mutate_raw_draft(
                draft=draft,
                donor=donor,
                new_label=target["label"],
                new_family=target["family"],
                ordinal=ordinal,
                local_index=local_index,
                ambiguity_level=target["ambiguity_level"],
                authoritative=target["authoritative"],
                quoted_thread=target["quoted_thread"],
                misleading_subject=target["misleading_subject"],
            )
            mutations.append(mutated)
    return mutations


def mutation_targets_for_draft(draft: RawDraft) -> list[dict[str, Any]]:
    family = draft.scenario.pattern_family
    label = draft.scenario.intended_label
    cluster = draft.scenario.cluster_id
    relevant_family = CLUSTER_BLUEPRINTS[cluster]["relevant"]
    non_target_family = CLUSTER_BLUEPRINTS[cluster]["non_target"]
    uncertain_family = CLUSTER_BLUEPRINTS[cluster]["uncertain"]
    targets: list[dict[str, Any]] = []
    if label == "relevant":
        targets.append({
            "label": "uncertain",
            "family": uncertain_family,
            "donor_family": uncertain_family,
            "ambiguity_level": "high",
            "authoritative": False,
            "quoted_thread": True,
            "misleading_subject": True,
        })
        if family not in {"weak_sender_strong_time_signal", "academic_wrapper_with_true_change"}:
            targets.append({
                "label": "non_target",
                "family": non_target_family,
                "donor_family": non_target_family,
                "ambiguity_level": "low",
                "authoritative": False,
                "quoted_thread": draft.scenario.has_quoted_thread,
                "misleading_subject": True,
            })
    elif label == "non_target":
        targets.append({
            "label": "uncertain",
            "family": uncertain_family,
            "donor_family": uncertain_family,
            "ambiguity_level": "high",
            "authoritative": False,
            "quoted_thread": True,
            "misleading_subject": True,
        })
        targets.append({
            "label": "relevant",
            "family": relevant_family,
            "donor_family": relevant_family,
            "ambiguity_level": "medium",
            "authoritative": True,
            "quoted_thread": draft.scenario.wrapper_style in {"canvas_wrapper", "forum_digest", "reply_chain"},
            "misleading_subject": True,
        })
    else:
        targets.append({
            "label": "relevant",
            "family": relevant_family,
            "donor_family": relevant_family,
            "ambiguity_level": "low",
            "authoritative": True,
            "quoted_thread": False,
            "misleading_subject": draft.scenario.subject_is_misleading,
        })
        targets.append({
            "label": "non_target",
            "family": non_target_family,
            "donor_family": non_target_family,
            "ambiguity_level": "low",
            "authoritative": False,
            "quoted_thread": draft.scenario.has_quoted_thread,
            "misleading_subject": True,
        })
    return targets


def mutate_raw_draft(
    *,
    draft: RawDraft,
    donor: Donor,
    new_label: Label,
    new_family: str,
    ordinal: int,
    local_index: int,
    ambiguity_level: str,
    authoritative: bool,
    quoted_thread: bool,
    misleading_subject: bool,
) -> RawDraft:
    mutated_scenario = replace(
        draft.scenario,
        scenario_id=f"{draft.scenario.scenario_id}-m{local_index}",
        intended_label=new_label,
        pattern_family=new_family,
        donor_family=new_family,
        ambiguity_level=ambiguity_level,
        body_has_authoritative_line=authoritative,
        has_quoted_thread=quoted_thread,
        subject_is_misleading=misleading_subject,
        source_mode="synthetic",
    )
    mutated = generate_raw_draft(scenario=mutated_scenario, donor=donor, ordinal=ordinal * 3 + local_index + 11)
    return replace(mutated, sample_id=f"mut-{draft.scenario.scenario_id}-{new_family}-{local_index:02d}", derived_from=draft.sample_id)


def phase4_blind_label_pass(raw_drafts: list[RawDraft]) -> dict[str, BlindLabelResult]:
    return {draft.sample_id: blind_label_one(draft) for draft in raw_drafts}


def blind_label_one(draft: RawDraft) -> BlindLabelResult:
    text = f"{draft.subject}\n{draft.body_text}".lower()
    course_tokens = [token.lower() for token in draft.known_course_tokens]
    has_course_token = any(token and token in text for token in course_tokens) or bool(course_tokens)
    sender_domain = extract_domain(draft.from_header)
    academic_sender = any(hint in sender_domain for hint in ACADEMIC_DOMAIN_HINTS)
    nonacademic_sender = any(hint in sender_domain for hint in NON_ACADEMIC_DOMAIN_HINTS)
    explicit_non_target = any(phrase in text for phrase in UNCHANGED_HINTS)
    exam_logistics_only = any(term in text for term in ("review session", "seating", "permitted materials", "format details")) and "is now due" not in text and "moved to" not in text
    quoted_thread = bool(QUOTE_PREFIX_RE.search(draft.body_text))
    hedged = any(term in text for term in HEDGING_HINTS)
    strong_time_line = any(term in text for term in RELEVANT_HINTS)
    wrapper_like = any(term in text for term in ("canvas notification", "forwarded message", "digest", "reply above this line", "forum summary", "you are receiving this"))
    newsletter_like = any(term in text for term in ("digest:", "newsletter", "weekly", "unsubscribe"))
    recruiting_like = any(term in text for term in ("recruiter", "internship", "application", "candidate")) and not has_course_token
    shipping_like = any(term in text for term in ("delivery", "shipment", "renewal", "tracking")) and not has_course_token

    if strong_time_line and (has_course_token or academic_sender):
        if hedged or quoted_thread and explicit_non_target:
            return BlindLabelResult(draft.sample_id, "uncertain", 0.64, "academic timing appears but quote or hedging leaves conflict", False)
        return BlindLabelResult(draft.sample_id, "relevant", 0.97 if academic_sender else 0.9, "clear academic time signal remains in the message", False)
    if explicit_non_target and (has_course_token or academic_sender):
        return BlindLabelResult(draft.sample_id, "non_target", 0.97, "academic context is present but the message explicitly says timing is unchanged", True)
    if exam_logistics_only and has_course_token:
        return BlindLabelResult(draft.sample_id, "non_target", 0.95, "exam logistics appear without an explicit exam time change", True)
    if wrapper_like and has_course_token:
        if quoted_thread or hedged:
            return BlindLabelResult(draft.sample_id, "uncertain", 0.68, "wrapper-heavy academic message could still hide a real timing change", False)
        return BlindLabelResult(draft.sample_id, "non_target", 0.94, "wrapper or forum summary lacks a concrete timing mutation", True)
    if recruiting_like or shipping_like or newsletter_like or nonacademic_sender and not has_course_token:
        return BlindLabelResult(draft.sample_id, "non_target", 0.96, "non-academic bait dominates and no course timeline signal is visible", True)
    if has_course_token or academic_sender or any(term in text for term in ACADEMIC_NON_TARGET_HINTS):
        return BlindLabelResult(draft.sample_id, "uncertain", 0.63, "academic context is present but the time signal is too weak to suppress", False)
    return BlindLabelResult(draft.sample_id, "non_target", 0.92, "general inbox noise without academic time signal", True)


def phase5_reviewer_pass(raw_drafts: list[RawDraft], blind_results: dict[str, BlindLabelResult]) -> dict[str, ReviewDecision]:
    signature_counts = Counter(normalize_signature(draft) for draft in raw_drafts)
    decisions: dict[str, ReviewDecision] = {}
    for draft in raw_drafts:
        blind = blind_results[draft.sample_id]
        text = f"{draft.subject}\n{draft.body_text}"
        lowered = text.lower()
        quality_penalty = 0.0
        if any(phrase in lowered for phrase in LEAK_PHRASES):
            decisions[draft.sample_id] = ReviewDecision(
                sample_id=draft.sample_id,
                decision="reject",
                final_label=blind.label,
                final_confidence=blind.confidence,
                final_reason="answer-leaking phrase detected",
                quality_penalty=1.0,
                correction_applied=False,
            )
            continue
        if any(token in text for token in PLACEHOLDER_PHRASES):
            decisions[draft.sample_id] = ReviewDecision(
                sample_id=draft.sample_id,
                decision="reject",
                final_label=blind.label,
                final_confidence=blind.confidence,
                final_reason="placeholder text detected",
                quality_penalty=1.0,
                correction_applied=False,
            )
            continue
        if signature_counts[normalize_signature(draft)] > 6:
            quality_penalty += 0.2
        review_label, review_confidence, review_reason = reviewer_label(draft)
        correction = False
        final_label = blind.label
        final_confidence = blind.confidence
        final_reason = blind.reason
        if review_label != blind.label:
            if review_label == "uncertain" and blind.label == "non_target":
                final_label = "uncertain"
                final_confidence = min(blind.confidence, review_confidence)
                final_reason = review_reason
                correction = True
                quality_penalty += 0.1
            elif review_label == blind.label:
                pass
            elif review_confidence >= 0.96 and blind.confidence < 0.7:
                final_label = review_label
                final_confidence = review_confidence
                final_reason = review_reason
                correction = True
                quality_penalty += 0.05
            else:
                decisions[draft.sample_id] = ReviewDecision(
                    sample_id=draft.sample_id,
                    decision="reject",
                    final_label=blind.label,
                    final_confidence=blind.confidence,
                    final_reason="blind and reviewer labels conflict without strong resolution",
                    quality_penalty=0.6,
                    correction_applied=False,
                )
                continue
        decisions[draft.sample_id] = ReviewDecision(
            sample_id=draft.sample_id,
            decision="keep",
            final_label=final_label,
            final_confidence=round(max(0.01, final_confidence - quality_penalty), 3),
            final_reason=final_reason,
            quality_penalty=quality_penalty,
            correction_applied=correction,
        )
    return decisions


def reviewer_label(draft: RawDraft) -> tuple[Label, float, str]:
    text = f"{draft.subject}\n{draft.body_text}".lower()
    quoted = bool(QUOTE_PREFIX_RE.search(draft.body_text))
    strong = any(term in text for term in RELEVANT_HINTS)
    unchanged = any(term in text for term in UNCHANGED_HINTS)
    hedged = any(term in text for term in HEDGING_HINTS)
    has_course = bool(draft.known_course_tokens)
    sender_domain = extract_domain(draft.from_header)
    academic_sender = any(hint in sender_domain for hint in ACADEMIC_DOMAIN_HINTS)
    wrapper = any(term in text for term in ("canvas notification", "forum summary", "digest", "forwarded message"))
    if strong and has_course and not hedged and not (quoted and unchanged):
        return "relevant", 0.98, "reviewer found a clean academic timing line"
    if unchanged and (has_course or academic_sender):
        return "non_target", 0.97, "reviewer found an explicit unchanged statement"
    if wrapper and has_course:
        return "uncertain", 0.66, "reviewer keeps wrapper-heavy academic content for LLM"
    if academic_sender or has_course:
        return "uncertain", 0.62, "reviewer prefers uncertain on weak academic signals"
    return "non_target", 0.95, "reviewer sees non-academic or clearly suppressible noise"


def phase6_curate_dataset(
    raw_drafts: list[RawDraft],
    blind_results: dict[str, BlindLabelResult],
    review_decisions: dict[str, ReviewDecision],
) -> dict[Split, list[dict[str, Any]]]:
    kept: dict[Split, dict[Label, list[tuple[RawDraft, ReviewDecision]]]] = {
        split: {label: [] for label in ("relevant", "non_target", "uncertain")}
        for split in ("train", "eval", "shadow")
    }
    for draft in raw_drafts:
        decision = review_decisions[draft.sample_id]
        if decision.decision != "keep":
            continue
        kept[draft.scenario.split][decision.final_label].append((draft, decision))

    datasets: dict[Split, list[dict[str, Any]]] = {}
    for split in ("train", "eval", "shadow"):
        rows: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for label in ("relevant", "non_target", "uncertain"):
            selected = select_diverse_examples(
                items=sorted(
                    kept[split][label],
                    key=lambda item: (
                        item[1].quality_penalty,
                        -item[1].final_confidence,
                        item[0].scenario.pattern_family,
                        item[0].sample_id,
                    ),
                ),
                count=LABEL_QUOTAS[split][label],
                group_key=lambda item: item[0].scenario.pattern_family,
                unique_key=lambda item: template_signature(item[0]),
            )
            if len(selected) < LABEL_QUOTAS[split][label]:
                raise RuntimeError(f"not enough curated rows for {split}/{label}: {len(selected)}")
            for draft, decision in selected:
                row = materialize_output_row(draft=draft, decision=decision)
                if row["sample_id"] in seen_ids:
                    continue
                seen_ids.add(row["sample_id"])
                rows.append(row)
        rows.sort(key=lambda row: (row["metadata"]["quarter"], row["metadata"]["pattern_family"], row["sample_id"]))
        datasets[split] = rows
    return datasets


def select_diverse_examples(
    *,
    items: list[tuple[RawDraft, ReviewDecision]],
    count: int,
    group_key: Any,
    unique_key: Any,
) -> list[tuple[RawDraft, ReviewDecision]]:
    grouped: dict[str, list[tuple[RawDraft, ReviewDecision]]] = defaultdict(list)
    for item in items:
        grouped[str(group_key(item))].append(item)
    ordered_groups = sorted(grouped)
    out: list[tuple[RawDraft, ReviewDecision]] = []
    seen_unique: dict[str, int] = defaultdict(int)
    index = 0
    max_unique_reuse = 12
    while len(out) < count and ordered_groups:
        group = ordered_groups[index % len(ordered_groups)]
        bucket = grouped[group]
        while bucket and seen_unique[unique_key(bucket[0])] >= max_unique_reuse:
            bucket.pop(0)
        if bucket:
            chosen = bucket.pop(0)
            seen_unique[unique_key(chosen)] += 1
            out.append(chosen)
        index += 1
        if all(not grouped[key] for key in ordered_groups):
            break
    return out[:count]


def materialize_output_row(*, draft: RawDraft, decision: ReviewDecision) -> dict[str, Any]:
    resolved_family = resolved_pattern_family(draft=draft, final_label=decision.final_label)
    relevant_like = is_relevant_like(
        final_label=decision.final_label,
        pattern_family=resolved_family,
        body_text=draft.body_text,
        from_header=draft.from_header,
    )
    return {
        "sample_id": final_sample_id(draft=draft, decision=decision, pattern_family=resolved_family),
        "source": draft.source,
        "label": decision.final_label,
        "weight": 1.0,
        "notify_email": draft.notify_email,
        "message_id": draft.message_id,
        "from_header": draft.from_header,
        "subject": draft.subject,
        "snippet": draft.snippet,
        "body_text": draft.body_text,
        "label_ids": ["INBOX"],
        "known_course_tokens": draft.known_course_tokens,
        "metadata": {
            "pseudo_label_confidence": decision.final_confidence,
            "pseudo_label_reason": decision.final_reason,
            "split": draft.scenario.split,
            "derived_from": draft.derived_from,
            "quarter": draft.metadata_quarter,
            "pattern_family": resolved_family,
            "relevant_like": relevant_like,
            "risk_tier": risk_tier_for(final_label=decision.final_label, relevant_like=relevant_like),
        },
    }


def final_sample_id(*, draft: RawDraft, decision: ReviewDecision, pattern_family: str) -> str:
    digest = hashlib.sha1(draft.sample_id.encode("utf-8")).hexdigest()[:10]
    return f"sf-{draft.scenario.split}-{decision.final_label}-{pattern_family}-{digest}"


def resolved_pattern_family(*, draft: RawDraft, final_label: Label) -> str:
    current_family = draft.metadata_pattern_family
    if final_label == "uncertain":
        if current_family in TARGET_UNCERTAIN_SOURCE_FAMILIES:
            if has_old_new_conflict(draft.body_text):
                return "stale_deadline_in_reply_chain"
            if looks_like_reply_or_wrapper(draft.body_text, draft.subject):
                return "quoted_thread_conflict"
            if strong_sender_for_uncertain(draft.from_header) and has_candidate_time_signal(draft.body_text):
                return "strong_sender_weak_signal"
            return "mixed_signal_uncertain"
        if current_family == "strong_sender_weak_signal" and not (strong_sender_for_uncertain(draft.from_header) and has_candidate_time_signal(draft.body_text)):
            return "mixed_signal_uncertain"
    if current_family in REQUIRED_PATTERN_FAMILIES:
        return current_family
    if FAMILY_LABEL.get(current_family) == final_label:
        return current_family
    cluster_map = CLUSTER_BLUEPRINTS.get(draft.scenario.cluster_id)
    if cluster_map:
        return cluster_map[final_label]
    return current_family


def write_outputs(datasets: dict[Split, list[dict[str, Any]]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_jsonl(TRAIN_PATH, datasets["train"])
    write_jsonl(EVAL_PATH, datasets["eval"])
    write_jsonl(SHADOW_PATH, datasets["shadow"])
    write_jsonl(HIGH_RISK_EVAL_PATH, build_high_risk_eval_rows(datasets["eval"]))
    REPORT_PATH.write_text(render_report(datasets), encoding="utf-8")
    SPEC_OUTPUT_PATH.write_text(render_spec_output(datasets), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def validate_outputs(datasets: dict[Split, list[dict[str, Any]]]) -> None:
    required_keys = {
        "sample_id",
        "source",
        "label",
        "weight",
        "notify_email",
        "message_id",
        "from_header",
        "subject",
        "snippet",
        "body_text",
        "label_ids",
        "known_course_tokens",
        "metadata",
    }
    meta_keys = {
        "pseudo_label_confidence",
        "pseudo_label_reason",
        "split",
        "derived_from",
        "quarter",
        "pattern_family",
        "relevant_like",
        "risk_tier",
    }
    pattern_counter = Counter()
    for split, rows in datasets.items():
        expected_total = sum(LABEL_QUOTAS[split].values())
        if len(rows) != expected_total:
            raise RuntimeError(f"{split} expected {expected_total} rows, got {len(rows)}")
        label_counter = Counter(row["label"] for row in rows)
        if label_counter != Counter(LABEL_QUOTAS[split]):
            raise RuntimeError(f"{split} label counts mismatch: {label_counter} vs {LABEL_QUOTAS[split]}")
        seen: set[str] = set()
        for row in rows:
            if set(row) != required_keys:
                raise RuntimeError(f"{row['sample_id']} schema mismatch")
            if set(row["metadata"]) != meta_keys:
                raise RuntimeError(f"{row['sample_id']} metadata mismatch")
            if row["sample_id"] in seen:
                raise RuntimeError(f"duplicate sample_id in {split}: {row['sample_id']}")
            seen.add(row["sample_id"])
            if row["label_ids"] != ["INBOX"]:
                raise RuntimeError(f"{row['sample_id']} invalid label_ids")
            if row["source"] not in {"synthetic", "pseudo_labeled"}:
                raise RuntimeError(f"{row['sample_id']} invalid source {row['source']}")
            if row["label"] not in {"relevant", "non_target", "uncertain"}:
                raise RuntimeError(f"{row['sample_id']} invalid label {row['label']}")
            if not isinstance(row["metadata"]["relevant_like"], bool):
                raise RuntimeError(f"{row['sample_id']} relevant_like must be bool")
            if row["metadata"]["risk_tier"] not in {"low", "medium", "high", "critical"}:
                raise RuntimeError(f"{row['sample_id']} invalid risk_tier {row['metadata']['risk_tier']}")
            if any(phrase in row["body_text"].lower() or phrase in row["subject"].lower() for phrase in LEAK_PHRASES):
                raise RuntimeError(f"{row['sample_id']} leaked answer phrasing")
            pattern_counter[row["metadata"]["pattern_family"]] += 1
    missing = REQUIRED_PATTERN_FAMILIES - set(pattern_counter)
    if missing:
        raise RuntimeError(f"missing required pattern families: {sorted(missing)}")


def render_report(datasets: dict[Split, list[dict[str, Any]]]) -> str:
    all_rows = [row for split_rows in datasets.values() for row in split_rows]
    totals = Counter(row["label"] for row in all_rows)
    sources = Counter(row["source"] for row in all_rows)
    quarters = Counter(row["metadata"]["quarter"] for row in all_rows)
    families = Counter(row["metadata"]["pattern_family"] for row in all_rows)
    duplicate_metrics = compute_duplicate_metrics(datasets)
    overlap_metrics = compute_cross_split_overlap(datasets)
    high_risk_eval_rows = build_high_risk_eval_rows(datasets["eval"])
    relevant_like_total = sum(1 for row in all_rows if row["metadata"]["relevant_like"])
    high_risk_family_counts = Counter(row["metadata"]["pattern_family"] for row in high_risk_eval_rows)
    top_subjects = Counter(row["subject"] for row in all_rows).most_common(10)
    top_senders = Counter(row["from_header"] for row in all_rows).most_common(10)
    hardest = select_report_examples(sorted(all_rows, key=lambda row: (row["metadata"]["pseudo_label_confidence"], row["sample_id"])), count=10)
    bait_rows = select_report_examples(
        [row for row in all_rows if row["metadata"]["pattern_family"] in {
            "shipping_subscription_bait",
            "recruiting_career_internship_bait",
            "newsletter_digest_campus_weekly",
            "lms_wrapper_only",
            "piazza_ed_forum_summary",
        }],
        count=10,
    )
    uncertain_rows = select_report_examples([row for row in all_rows if row["label"] == "uncertain"], count=10)
    noisy_rows = select_report_examples(
        [
            row
            for row in all_rows
            if any(token in row["body_text"].lower() for token in ("&nbsp;", "<div", "sent from my", "forwarded message", "reply above this line"))
            or "fwd" in row["subject"].lower()
            or "re:" in row["subject"].lower()
        ],
        count=10,
    )
    quoted_rows = select_report_examples(
        [row for row in all_rows if ">" in row["body_text"] or "forwarded message" in row["body_text"].lower()],
        count=10,
    )
    lines = [
        "# Gmail Secondary Filter Dataset",
        "",
        "## Total Samples",
        "",
        f"- total: {len(all_rows)}",
        f"- train: {len(datasets['train'])}",
        f"- eval: {len(datasets['eval'])}",
        f"- shadow: {len(datasets['shadow'])}",
        f"- high_risk_eval: {len(high_risk_eval_rows)}",
        "",
        "## Label Distribution",
        "",
        *[f"- {label}: {totals[label]}" for label in ("relevant", "non_target", "uncertain")],
        "",
        "## Source Distribution",
        "",
        *[f"- {source}: {count}" for source, count in sorted(sources.items())],
        "",
        "## Quarter Distribution",
        "",
        *[f"- {quarter}: {quarters[quarter]}" for quarter in sorted(quarters)],
        "",
        "## Pattern Family Distribution",
        "",
        *[f"- {family}: {families[family]}" for family in sorted(families)],
        "",
        "## Relevant-Like Summary",
        "",
        f"- relevant_like=true total: {relevant_like_total}",
        f"- high_risk_eval: {len(high_risk_eval_rows)}",
        "",
        "## Exact Duplicate Ratio By Split",
        "",
        *[f"- {split}: {duplicate_metrics[split]['duplicate_ratio']:.4f} ({duplicate_metrics[split]['duplicate_count']} duplicate rows)" for split in ("train", "eval", "shadow")],
        "",
        "## Cross-Split Exact Overlap",
        "",
        f"- train vs eval: {overlap_metrics['train_eval']}",
        f"- train vs shadow: {overlap_metrics['train_shadow']}",
        f"- eval vs shadow: {overlap_metrics['eval_shadow']}",
        "",
        "## Top Repeated Subjects",
        "",
        *[f"- `{subject}`: {count}" for subject, count in top_subjects],
        "",
        "## Top Repeated Senders",
        "",
        *[f"- `{sender}`: {count}" for sender, count in top_senders],
        "",
        "## 10 Hardest Examples",
        "",
        *render_example_block(hardest),
        "",
        "## 10 Likely False-Positive Bait Examples",
        "",
        *render_example_block(bait_rows),
        "",
        "## 10 Uncertain Examples",
        "",
        *render_example_block(uncertain_rows),
        "",
        "## 10 Noisy Realistic Examples",
        "",
        *render_example_block(noisy_rows),
        "",
        "## 10 Quoted-Thread / Forwarded-Chain Examples",
        "",
        *render_example_block(quoted_rows),
        "",
        "## High-Risk Eval Slice",
        "",
        f"- rows: {len(high_risk_eval_rows)}",
        f"- relevant_like rows: {sum(1 for row in high_risk_eval_rows if row['metadata']['relevant_like'])}",
        f"- labels: {dict(Counter(row['label'] for row in high_risk_eval_rows))}",
        f"- families: {dict(high_risk_family_counts)}",
        "",
        "## Quality Gaps",
        "",
        "- No real post-prefilter Gmail production corpus is included in this pass; the dataset is donor-seeded from repo synthetic/full-sim material and then expanded deterministically.",
        "- Wrapper-heavy uncertain cases are strong, but the dataset still underrepresents truly messy HTML flattening and long multi-hop forwarding artifacts.",
        "- FA lives entirely in shadow and SU entirely in eval by design, so the chronological split is realistic but cross-quarter family balance is not perfectly uniform.",
        "",
    ]
    return "\n".join(lines)


def render_spec_output(datasets: dict[Split, list[dict[str, Any]]]) -> str:
    all_rows = [row for split_rows in datasets.values() for row in split_rows]
    families = Counter(row["metadata"]["pattern_family"] for row in all_rows)
    duplicate_metrics = compute_duplicate_metrics(datasets)
    overlap_metrics = compute_cross_split_overlap(datasets)
    relevant_like_total = sum(1 for row in all_rows if row["metadata"]["relevant_like"])
    high_risk_eval_rows = build_high_risk_eval_rows(datasets["eval"])
    return "\n".join(
        [
            "# Implementation Output Template",
            "",
            "## Dataset Artifacts",
            "",
            "- `data/secondary_filter/gmail_train.jsonl`",
            "- `data/secondary_filter/gmail_eval.jsonl`",
            "- `data/secondary_filter/gmail_shadow_candidates.jsonl`",
            "- `data/secondary_filter/gmail_high_risk_eval.jsonl`",
            "- `data/secondary_filter/DATASET_REPORT.md`",
            "",
            "## Dataset Summary",
            "",
            f"- train: `{len(datasets['train'])}`",
            f"- eval: `{len(datasets['eval'])}`",
            f"- shadow: `{len(datasets['shadow'])}`",
            f"- high_risk_eval: `{len(high_risk_eval_rows)}`",
            f"- relevant_like=true total: `{relevant_like_total}`",
            "",
            "## Pattern Coverage",
            "",
            *[f"- `{family}`: `{families[family]}`" for family in sorted(families)],
            "",
            "## Remaining Gaps",
            "",
            "- no real post-prefilter Gmail production rows were introduced in this pass",
            "- HTML/MIME flattening and long forwarding chains remain underrepresented",
            "- chronological split is realistic but not perfectly quarter-balanced across all families",
            "",
            "## Duplicate And Overlap Summary",
            "",
            *[f"- {split} exact duplicate ratio: {duplicate_metrics[split]['duplicate_ratio']:.4f}" for split in ("train", "eval", "shadow")],
            f"- train/eval overlap: {overlap_metrics['train_eval']}",
            f"- train/shadow overlap: {overlap_metrics['train_shadow']}",
            f"- eval/shadow overlap: {overlap_metrics['eval_shadow']}",
            "",
            "## Training Outputs",
            "",
            "- out of scope in this pass",
            "",
            "## Runtime Outputs",
            "",
            "- out of scope in this pass",
            "",
        ]
    )


def is_relevant_like(*, final_label: Label, pattern_family: str, body_text: str, from_header: str) -> bool:
    if final_label == "relevant":
        return True
    if final_label != "uncertain":
        return False
    if pattern_family in {"quoted_thread_conflict", "stale_deadline_in_reply_chain"}:
        return has_candidate_time_signal(body_text)
    if pattern_family == "strong_sender_weak_signal":
        return strong_sender_for_uncertain(from_header) and has_candidate_time_signal(body_text)
    return False


def risk_tier_for(*, final_label: Label, relevant_like: bool) -> str:
    if final_label == "relevant":
        return "critical"
    if final_label == "uncertain" and relevant_like:
        return "high"
    if final_label == "uncertain":
        return "medium"
    return "low"


def build_high_risk_eval_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = [
        row
        for row in rows
        if row["label"] == "relevant"
        or (
            row["label"] == "uncertain"
            and bool(row["metadata"].get("relevant_like"))
        )
    ]
    out.sort(key=lambda row: (row["label"], row["metadata"]["pattern_family"], row["sample_id"]))
    return out


def has_candidate_time_signal(body_text: str) -> bool:
    text = body_text.lower()
    return bool(
        re.search(r"20\d{2}-\d{2}-\d{2}", text)
        or re.search(r"\b\d{1,2}:\d{2}(:\d{2})?\b", text)
        or any(term in text for term in RELEVANT_HINTS)
    )


def has_old_new_conflict(body_text: str) -> bool:
    text = body_text.lower()
    date_hits = re.findall(r"20\d{2}-\d{2}-\d{2}", text)
    if len(set(date_hits)) >= 2:
        return True
    return "older time" in text or "previously appeared as" in text or "earlier thread" in text or "follow-up reply" in text


def looks_like_reply_or_wrapper(body_text: str, subject: str) -> bool:
    text = f"{subject}\n{body_text}".lower()
    return (
        "forwarded message" in text
        or "reply above this line" in text
        or "wrote:" in text
        or ">" in body_text
        or "canvas notification" in text
        or "forum summary" in text
    )


def strong_sender_for_uncertain(from_header: str) -> bool:
    sender = from_header.lower()
    return any(token in sender for token in ("prof.", "staff", "instruction", "registrar", "assessment", "testing center", "student affairs", "advising"))


def render_example_block(rows: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for row in rows:
        out.extend(
            [
                f"- `{row['sample_id']}`",
                f"  - label: `{row['label']}` | quarter: `{row['metadata']['quarter']}` | family: `{row['metadata']['pattern_family']}` | confidence: `{row['metadata']['pseudo_label_confidence']}`",
                f"  - subject: {row['subject']}",
                f"  - from: {row['from_header']}",
                f"  - why: {row['metadata']['pseudo_label_reason']}",
            ]
        )
    return out


def select_report_examples(rows: list[dict[str, Any]], *, count: int) -> list[dict[str, Any]]:
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_family[row["metadata"]["pattern_family"]].append(row)
    ordered = sorted(by_family)
    out: list[dict[str, Any]] = []
    index = 0
    while len(out) < count and ordered:
        key = ordered[index % len(ordered)]
        bucket = by_family[key]
        if bucket:
            out.append(bucket.pop(0))
        index += 1
        if all(not by_family[k] for k in ordered):
            break
    return out[:count]


def compute_duplicate_metrics(datasets: dict[Split, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for split, rows in datasets.items():
        hashes = [exact_text_hash(row) for row in rows]
        counts = Counter(hashes)
        duplicate_count = sum(value - 1 for value in counts.values() if value > 1)
        out[split] = {
            "duplicate_count": duplicate_count,
            "duplicate_ratio": duplicate_count / len(rows) if rows else 0.0,
        }
    return out


def compute_cross_split_overlap(datasets: dict[Split, list[dict[str, Any]]]) -> dict[str, int]:
    train = {exact_text_hash(row) for row in datasets["train"]}
    eval_ = {exact_text_hash(row) for row in datasets["eval"]}
    shadow = {exact_text_hash(row) for row in datasets["shadow"]}
    return {
        "train_eval": len(train & eval_),
        "train_shadow": len(train & shadow),
        "eval_shadow": len(eval_ & shadow),
    }


def exact_text_hash(row: dict[str, Any]) -> str:
    blob = f"{row['from_header']}\n{row['subject']}\n{row['body_text']}"
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def render_from_header(*, scenario: Scenario, donor: Donor, course_label: str, ordinal: int) -> str:
    course_slug = safe_course_slug(course_label)
    persona = scenario.sender_persona
    style = scenario.sender_domain_style
    if persona == "professor_sender":
        names = ("Prof. Elena Park", "Prof. Theo Raman", "Prof. Rina Patel", "Prof. Leila Nouri")
        name = names[ordinal % len(names)]
        return f"{name} <{name.lower().replace('prof. ', '').replace(' ', '.')}@{mail_domain('faculty', style)}>"
    if persona == "ta_sender":
        names = ("Mina Chen", "Jordan Lee", "Priya Sethi", "Alex Romero", "Sam Wu")
        name = names[ordinal % len(names)]
        return f"{name} <{name.lower().replace(' ', '.')}@{mail_domain('ta', style)}>"
    if persona == "course_staff_alias":
        return f"{course_label} Staff <{course_slug}-staff@{mail_domain('course_staff', style)}>"
    if persona == "department_admin":
        options = ("Registrar Updates", "Student Affairs", "Advising Office", "Academic Services")
        label = options[ordinal % len(options)]
        return f"{label} <noreply@{mail_domain('campus', style)}>"
    if persona == "testing_center":
        options = ("Testing Center", "Exam Services", "Assessment Office")
        label = options[ordinal % len(options)]
        return f"{label} <noreply@{mail_domain('campus', style)}>"
    if persona == "lms_wrapper":
        options = ("Canvas Notifications", "Gradescope Updates", "Course Site")
        label = options[ordinal % len(options)]
        domain = {
            "canvas": "canvas.instructure.com",
            "gradescope": "notify.gradescope-mail.com",
        }.get(style, f"notifications.{style}.edu")
        return f"{label} <notifications@{domain}>"
    if persona == "forum_digest":
        options = (
            "Piazza Digest <digest@piazza.com>",
            "Ed Discussion <notify@edstem.org>",
            "Forum Summary <summary@forum-mail.org>",
        )
        return options[ordinal % len(options)]
    if persona == "campus_digest":
        options = ("Campus Weekly", "Student Digest", "Department Roundup")
        label = options[ordinal % len(options)]
        return f"{label} <digest@{mail_domain('digest', style)}>"
    if persona == "department_digest":
        options = ("Instruction Digest", "Academic Bulletin", "Week Ahead")
        label = options[ordinal % len(options)]
        return f"{label} <digest@{mail_domain('digest', style)}>"
    if persona == "generic_no_reply":
        options = {
            "mail.ops": ("ParcelPilot", "Renewal Desk", "Billing Alert"),
            "notify.mail": ("ShipDeck", "Subscription Center", "Secure Login"),
            "messages": ("North Harbor Bank", "Payment Services", "Account Watch"),
            "careers": ("Gradient Labs Recruiting", "Vertex Recruiting", "Campus Talent Desk"),
            "recruiting": ("Northwind Careers", "Talent Network", "Recruiting Operations"),
            "mail.jobs": ("Career Match", "Internship Alerts", "Opportunity Desk"),
            "digest": ("Campus Weekly", "Tech Briefing", "Student Digest"),
            "news": ("Campus Weekly", "Department Roundup", "Morning Brief"),
            "weekly": ("Triton Weekly", "Week Ahead", "Community Digest"),
        }
        label = options.get(style, ("No Reply",))[ordinal % len(options.get(style, ("No Reply",)))]
        domain = {
            "mail.ops": "mail.parcelpilot.com",
            "notify.mail": "notify.renewals.app",
            "messages": "messages.accounthub.io",
            "careers": "careers.gradientlabs.ai",
            "recruiting": "mail.northwind.jobs",
            "mail.jobs": "alerts.opportunitydesk.ai",
            "digest": "digest.campusweekly.org",
            "news": "news.roundupcampus.org",
            "weekly": "weekly.weekahead.org",
        }.get(style, f"mail.{style}.org")
        return f"{label} <noreply@{domain}>"
    if persona == "course_staff_forward":
        return f"Fwd via {course_label} Staff <forward+{course_slug}@{mail_domain('forward', style)}>"
    return f"Student Forward <forwarded+{course_slug}@mailbox.example.org>"


def render_subject(*, scenario: Scenario, donor: Donor, course_label: str, bait_terms: list[str], ordinal: int) -> str:
    family = scenario.pattern_family
    bait = bait_terms[ordinal % len(bait_terms)]
    raw_type = donor.raw_type or infer_raw_type(donor, fallback="Assignment")
    event_name = donor.event_name or f"{raw_type} {2 + (ordinal % 6)}"
    if family == "shipping_subscription_bait":
        options = (
            f"Final reminder: your {bait} subscription renews tonight",
            f"{bait.title()} delivery window updated",
            f"Action needed: {bait} shipment cutoff",
        )
        return options[ordinal % len(options)]
    if family == "recruiting_career_internship_bait":
        options = (
            f"Internship application {bait} update",
            f"Recruiter follow-up on your {bait} submission",
            f"Career network reminder before the final round",
        )
        return options[ordinal % len(options)]
    if family == "newsletter_digest_campus_weekly":
        options = (
            f"Campus Weekly: {bait}, events, and student updates",
            f"Digest: project fair, final reminders, and campus notes",
            f"Week Ahead: assignment tips, social events, and billing notices",
        )
        return options[ordinal % len(options)]
    if family == "lms_wrapper_only":
        options = (
            f"Canvas Notification - {course_label}: activity in {raw_type.lower()}",
            f"Course site update for {course_label}",
            f"Gradescope notification for {course_label}",
        )
        return options[ordinal % len(options)]
    if family == "piazza_ed_forum_summary":
        options = (
            f"Piazza summary for {course_label}",
            f"Ed Discussion digest: {course_label} thread activity",
            f"Forum summary: {course_label} {bait} discussion",
        )
        return options[ordinal % len(options)]
    if family == "academic_admin_noise":
        options = (
            f"[{course_label}] roster, waitlist, and submission portal note",
            f"{course_label} admin reminder for this week",
            f"Academic services note for {course_label}",
        )
        return options[ordinal % len(options)]
    if family == "explicit_graded_item_unchanged":
        options = (
            f"[{course_label}] clarification on {raw_type.lower()}",
            f"{course_label} update: {event_name.lower()} details",
            f"Re: {course_label} {raw_type.lower()} thread",
        )
        return options[ordinal % len(options)]
    if family == "exam_logistics_non_target":
        options = (
            f"[{course_label}] final logistics update",
            f"{course_label} exam room and materials reminder",
            f"Quiz and final logistics for {course_label}",
        )
        return options[ordinal % len(options)]
    if family == "new_graded_item_announcement":
        options = (
            f"[{course_label}] {raw_type} posted",
            f"New item in {course_label}: {event_name}",
            f"Canvas Notification - {course_label}: new assignment",
        )
        return options[ordinal % len(options)]
    if family == "real_due_date_change":
        options = (
            f"[{course_label}] update on {event_name.lower()}",
            f"Re: {course_label} {raw_type.lower()} timing",
            f"{course_label} schedule note for {event_name}",
        )
        return options[ordinal % len(options)]
    if family == "bulk_schedule_mutation":
        options = (
            f"[{course_label}] course-wide schedule update",
            f"{course_label} future {raw_type.lower()} policy",
            f"All sections: {course_label} {raw_type.lower()} timing",
        )
        return options[ordinal % len(options)]
    if family == "broad_audience_deadline_mutation":
        options = (
            f"All students in {course_label}: assignment timing update",
            f"[{course_label}] broad announcement",
            f"{course_label} update for all sections",
        )
        return options[ordinal % len(options)]
    if family == "exam_time_change_target":
        options = (
            f"[{course_label}] exam room and timing update",
            f"{course_label} final notice",
            f"Re: {course_label} exam information",
        )
        return options[ordinal % len(options)]
    if family == "mixed_signal_uncertain":
        options = (
            f"Fwd: {course_label} assignment note",
            f"Re: [{course_label}] quick clarification before section",
            f"Canvas Notification - {course_label}: thread updated",
        )
        return options[ordinal % len(options)]
    if family == "quoted_thread_conflict":
        options = (
            f"Re: {course_label} {raw_type.lower()} thread",
            f"Fwd: {course_label} deadline question",
            f"{course_label} follow-up on earlier note",
        )
        return options[ordinal % len(options)]
    if family == "stale_deadline_in_reply_chain":
        options = (
            f"Re: {course_label} previous deadline note",
            f"Fwd: old {course_label} thread",
            f"{course_label} follow-up after reply chain",
        )
        return options[ordinal % len(options)]
    if family == "weak_sender_strong_time_signal":
        options = (
            f"Fwd: project reminder",
            f"Action needed for {course_label}",
            f"Update on your {bait} submission",
        )
        return options[ordinal % len(options)]
    if family == "strong_sender_weak_signal":
        options = (
            f"[{course_label}] small follow-up",
            f"{course_label} quick staff clarification",
            f"Re: {course_label} note from staff",
        )
        return options[ordinal % len(options)]
    options = (
        f"Canvas Notification - {course_label}: content updated",
        f"Forum update for {course_label}",
        f"Re: {course_label} wrapper thread",
    )
    return options[ordinal % len(options)]


def render_body(*, scenario: Scenario, donor: Donor, course_label: str, bait_terms: list[str], ordinal: int) -> str:
    family = scenario.pattern_family
    raw_type = donor.raw_type or infer_raw_type(donor, fallback="Assignment")
    event_name = donor.event_name or f"{raw_type} {2 + (ordinal % 6)}"
    due_phrase = donor.due_phrase or fallback_due_phrase(scenario.quarter, ordinal)
    previous_due = donor.previous_due_phrase or fallback_due_phrase(scenario.quarter, ordinal + 9)
    lines: list[str] = []

    needs_course_context = family_needs_course_context(family)
    if scenario.wrapper_style in {"canvas_wrapper", "forum_digest"} and needs_course_context:
        lines.extend(
            [
                f"You are receiving this message because there was activity in {course_label}.",
                "Replying by email may not post back to the course site.",
            ]
        )
    elif scenario.wrapper_style == "forwarded_notice":
        lines.extend(["Forwarded message", "---------- Forwarded message ----------"])
    elif scenario.wrapper_style == "newsletter_block":
        lines.extend(["Weekly roundup", "Top items from this list are below."])
    elif scenario.wrapper_style == "department_notice" and needs_course_context:
        lines.extend([f"Course: {course_label}", seasonal_intro(scenario.quarter)])
    elif needs_course_context:
        lines.append(f"Course: {course_label}")

    body_lines = family_body_lines(
        family=family,
        course_label=course_label,
        raw_type=raw_type,
        event_name=event_name,
        due_phrase=due_phrase,
        previous_due=previous_due,
        bait_terms=bait_terms,
        ambiguity_level=scenario.ambiguity_level,
        authoritative=scenario.body_has_authoritative_line,
    )
    lines.extend(body_lines)

    if scenario.has_quoted_thread:
        lines.extend(render_quoted_thread(family=family, course_label=course_label, raw_type=raw_type, previous_due=previous_due, due_phrase=due_phrase, ordinal=ordinal))

    if scenario.wrapper_style in {"promo_footer", "newsletter_block"}:
        lines.extend(["View in browser | Manage preferences | Unsubscribe"])
    elif scenario.wrapper_style in {"canvas_wrapper", "forum_digest"}:
        lines.extend(["Open the course site to view the full thread."])
    elif scenario.sender_persona in {"generic_no_reply", "department_admin", "testing_center"}:
        lines.extend(["Please do not reply to this automated message."])

    return "\n".join(lines).strip()


def apply_sender_variation(base: str, *, scenario: Scenario, donor: Donor, course_label: str, ordinal: int) -> str:
    display, email = split_from_header(base)
    local, domain = split_email(email)
    style_seed = style_index(scenario=scenario, ordinal=ordinal)
    display_variants = build_display_variants(
        display=display,
        scenario=scenario,
        course_label=course_label,
        ordinal=ordinal,
    )
    domain_variants = build_domain_variants(domain=domain, scenario=scenario, ordinal=ordinal)
    local_variants = build_local_variants(local=local, scenario=scenario, course_label=course_label, ordinal=ordinal)
    chosen_display = display_variants[style_seed % len(display_variants)]
    chosen_local = local_variants[(style_seed // 2) % len(local_variants)]
    chosen_domain = domain_variants[(style_seed // 3) % len(domain_variants)]
    return f"{chosen_display} <{chosen_local}@{chosen_domain}>"


def apply_subject_variation(
    base: str,
    *,
    scenario: Scenario,
    donor: Donor,
    course_label: str,
    bait_terms: list[str],
    ordinal: int,
) -> str:
    seed = style_index(scenario=scenario, ordinal=ordinal)
    prefix_pool = ["", "Re: ", "Fwd: ", "FW: ", "[EXTERNAL] ", "quick note: ", "update: "]
    suffix_pool = [
        "",
        " / all students",
        " - pls read",
        " // thread",
        " (updated)",
        " [digest]",
        " [follow-up]",
        " + one more thing",
    ]
    context_pool = [
        "",
        f" for {course_label}",
        f" before {quarter_hook(scenario.quarter)}",
        f" re {bait_terms[0]}",
        f" - {family_subject_hint(scenario.pattern_family, ordinal)}",
    ]
    subject = f"{prefix_pool[seed % len(prefix_pool)]}{base}{context_pool[(seed // 2) % len(context_pool)]}{suffix_pool[(seed // 3) % len(suffix_pool)]}"
    subject = inject_subject_noise(subject, scenario=scenario, ordinal=ordinal)
    return clean_text_noise(subject)


def apply_body_variation(
    base: str,
    *,
    scenario: Scenario,
    donor: Donor,
    course_label: str,
    bait_terms: list[str],
    ordinal: int,
) -> str:
    seed = style_index(scenario=scenario, ordinal=ordinal)
    lines = base.splitlines()
    header_bits = message_header_fragments(scenario=scenario, donor=donor, course_label=course_label, ordinal=ordinal)
    footer_bits = message_footer_fragments(scenario=scenario, donor=donor, ordinal=ordinal)
    clutter_bits = realistic_clutter_fragments(
        scenario=scenario,
        donor=donor,
        course_label=course_label,
        bait_terms=bait_terms,
        ordinal=ordinal,
    )

    if seed % 5 == 0:
        lines = header_bits + lines + clutter_bits[:1] + footer_bits
    elif seed % 5 == 1:
        midpoint = max(1, len(lines) // 2)
        lines = lines[:midpoint] + clutter_bits[:2] + lines[midpoint:] + footer_bits
    elif seed % 5 == 2:
        lines = header_bits[:2] + lines + footer_bits[:2]
    elif seed % 5 == 3:
        lines = lines + clutter_bits + footer_bits
    else:
        lines = header_bits[:1] + lines + clutter_bits[:2] + footer_bits[:1]

    if seed % 7 in {0, 4}:
        lines = apply_html_flattening(lines, seed=seed)
    if seed % 9 in {2, 5, 8}:
        lines = apply_typo_noise(lines, seed=seed, severity="light" if scenario.intended_label != "uncertain" else "medium")
    if seed % 11 in {3, 7}:
        lines = apply_spacing_noise(lines, seed=seed)
    if seed % 13 in {1, 6}:
        lines.append(mobile_signature(ordinal))
    return clean_text_noise("\n".join(lines))


def build_display_variants(*, display: str, scenario: Scenario, course_label: str, ordinal: int) -> list[str]:
    variants = [display]
    lowered = display.lower()
    if "prof." in lowered:
        bare = display.replace("Prof. ", "")
        first, *rest = bare.split()
        last = rest[-1] if rest else ""
        variants.extend([bare, f"{first} {last[:1]}." if last else first, f"{last}, {first}" if last else bare])
    elif "staff" in lowered:
        variants.extend(
            [
                f"{course_label} staff",
                f"{course_label} course staff",
                f"Instruction team for {course_label}",
                f"{course_label} instructional staff",
            ]
        )
    elif any(token in lowered for token in ("testing", "assessment", "exam")):
        variants.extend(["Exam Services", "Assessment Office", "Testing Ctr", "Testing Center Team"])
    elif any(token in lowered for token in ("canvas", "gradescope", "course site")):
        variants.extend(["Canvas Notifications", "Canvas", "Gradescope updates", "course site notifications"])
    elif any(token in lowered for token in ("digest", "weekly", "roundup")):
        variants.extend(["campus weekly", "Student Digest", "Week Ahead", "Campus roundup"])
    else:
        variants.extend([display.title(), display.lower(), display.upper() if ordinal % 17 == 0 else display])
    return unique_nonempty(variants)


def build_domain_variants(*, domain: str, scenario: Scenario, ordinal: int) -> list[str]:
    parts = domain.split(".")
    base = [domain]
    if len(parts) >= 2:
        tld = ".".join(parts[-2:])
        stem = parts[0]
        base.extend(
            [
                domain,
                f"mail.{tld}",
                f"notify.{tld}",
                f"updates.{tld}",
                f"{stem}-{scenario.quarter.lower()}.{tld}",
                f"{stem}{(ordinal % 9) + 1}.{tld}",
            ]
        )
    if scenario.sender_persona in {"lms_wrapper", "forum_digest"}:
        base.extend(["canvas.instructure.com", "notify.gradescope-mail.com", "piazza.com", "edstem.org"])
    return unique_nonempty(base)


def build_local_variants(*, local: str, scenario: Scenario, course_label: str, ordinal: int) -> list[str]:
    slug = safe_course_slug(course_label)
    variants = [local or "noreply"]
    variants.extend(
        [
            f"{(local or 'noreply').replace('.', '')}",
            f"{local or 'noreply'}{ordinal % 17}",
            f"{local or 'noreply'}+{scenario.quarter.lower()}",
            f"{slug}-{scenario.cluster_id}-{ordinal % 11}",
        ]
    )
    return unique_nonempty([re.sub(r"[^a-z0-9+._-]", "", value.lower()) for value in variants])


def split_from_header(value: str) -> tuple[str, str]:
    match = re.match(r"^(.*)\s+<([^>]+)>$", value.strip())
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return value.strip(), "noreply@example.org"


def split_email(value: str) -> tuple[str, str]:
    if "@" in value:
        local, domain = value.split("@", 1)
        return local, domain
    return value, "example.org"


def message_header_fragments(*, scenario: Scenario, donor: Donor, course_label: str, ordinal: int) -> list[str]:
    date_line = f"On {['Mon','Tue','Wed','Thu','Fri'][ordinal % 5]}, Mar {10 + (ordinal % 18)}, 2026 at {8 + (ordinal % 9)}:{'00' if ordinal % 2 == 0 else '37'} {'AM' if ordinal % 2 == 0 else 'PM'}"
    sender = donor.from_header or f"{course_label} Staff <staff@course-notify.edu>"
    subject = family_subject_hint(scenario.pattern_family, ordinal)
    headers = [
        f"{date_line}, {sender} wrote:",
        "Begin forwarded message:",
        f"From: {sender}",
        f"Subject: {subject}",
        "---------- Forwarded message ----------",
        "<div dir=\"ltr\">",
        "&nbsp;",
    ]
    return unique_nonempty(headers)


def message_footer_fragments(*, scenario: Scenario, donor: Donor, ordinal: int) -> list[str]:
    footers = [
        "View in browser | Manage preferences | Unsubscribe",
        "Tracking preferences | Email settings | Help center",
        "Open the course site for the full thread.",
        "Reply above this line if you need help.",
        "—",
        "Thanks,",
        "Sent from my iPhone",
    ]
    if scenario.pattern_family in {"shipping_subscription_bait", "recruiting_career_internship_bait"}:
        footers.extend(["Manage alerts | Update preferences", "Click here to change notification settings"])
    return unique_nonempty(footers)


def realistic_clutter_fragments(
    *,
    scenario: Scenario,
    donor: Donor,
    course_label: str,
    bait_terms: list[str],
    ordinal: int,
) -> list[str]:
    room = ["WLH 2207", "CENTR 109", "PCYNH 106", "RCLAS B02", "Zoom room 3"][ordinal % 5]
    section = ["A01", "A02", "B03", "B04", "C05"][ordinal % 5]
    tracker = f"ref {scenario.quarter}-{scenario.cluster_id[:3]}-{ordinal % 9000:04d}"
    fragments = [
        f"section {section} / room {room}",
        f"ticket {tracker}",
        f"please see the earlier {bait_terms[0]} note below",
        "html residue: &nbsp; <br> <br>",
        "---- original message ----",
        "reply above this line",
        "autogenerated summary follows",
    ]
    if family_needs_course_context(scenario.pattern_family):
        fragments.append(f"{course_label} thread count: {2 + (ordinal % 7)} replies")
    return unique_nonempty(fragments)


def apply_html_flattening(lines: list[str], *, seed: int) -> list[str]:
    out: list[str] = []
    for idx, line in enumerate(lines):
        if idx % 3 == seed % 3:
            out.append(f"<div>{line}</div>")
        elif idx % 4 == seed % 4:
            out.append(line.replace(" ", "&nbsp; "))
        else:
            out.append(line)
    if seed % 2 == 0:
        out.append("</div>")
    return out


def apply_typo_noise(lines: list[str], *, seed: int, severity: str) -> list[str]:
    replacements = {
        "assignment": "assignmnt",
        "schedule": "schedlue",
        "updated": "updatd",
        "clarification": "clarifcation",
        "discussion": "discusson",
        "notification": "notifcation",
        "students": "studnets",
        "because": "becuase",
        "available": "availble",
    }
    out: list[str] = []
    budget = 1 if severity == "light" else 2
    for idx, line in enumerate(lines):
        mutated = line
        if budget > 0 and (idx + seed) % 3 == 0:
            for src, dst in replacements.items():
                if src in mutated.lower():
                    mutated = re.sub(src, dst, mutated, count=1, flags=re.I)
                    budget -= 1
                    break
        if budget > 0 and (idx + seed) % 5 == 0:
            mutated = mutated.replace(":", " -", 1) if ":" in mutated else mutated + " .."
            budget -= 1
        out.append(mutated)
    return out


def apply_spacing_noise(lines: list[str], *, seed: int) -> list[str]:
    out: list[str] = []
    for idx, line in enumerate(lines):
        mutated = line
        if (idx + seed) % 2 == 0:
            mutated = mutated.replace("  ", " ").replace(" ", "  ", 1)
        if (idx + seed) % 5 == 0:
            mutated = mutated.rstrip(".") + "..."
        if (idx + seed) % 7 == 0:
            mutated = mutated.lower() if len(mutated) < 40 else mutated
        out.append(mutated)
    return out


def inject_subject_noise(subject: str, *, scenario: Scenario, ordinal: int) -> str:
    if (ordinal + len(scenario.pattern_family)) % 7 == 0:
        subject = subject.replace("Update", "update").replace("Reminder", "reminder")
    if (ordinal + len(scenario.cluster_id)) % 9 == 0:
        subject = subject.replace(":", " ::", 1) if ":" in subject else subject + " ?"
    if (ordinal + len(scenario.quarter)) % 11 == 0:
        subject = re.sub(r"\bAssignment\b", "Assigment", subject)
    if scenario.subject_is_misleading and ordinal % 5 == 0:
        subject = subject.replace("posted", "updated").replace("update", "notice")
    return subject


def mobile_signature(ordinal: int) -> str:
    options = [
        "sent from my iphone",
        "Sent from my iPhone",
        "Sent from my Pixel",
        "sent from mobile",
    ]
    return options[ordinal % len(options)]


def family_subject_hint(family: str, ordinal: int) -> str:
    hints = {
        "shipping_subscription_bait": ("renewal", "tracking", "delivery window", "cutoff"),
        "recruiting_career_internship_bait": ("candidate update", "resume follow-up", "availability", "final round"),
        "newsletter_digest_campus_weekly": ("roundup", "digest", "weekly note", "events"),
        "lms_wrapper_only": ("course activity", "site comment", "rubric entry", "gradebook"),
        "piazza_ed_forum_summary": ("thread summary", "forum reply", "discussion recap", "digest"),
        "academic_admin_noise": ("waitlist", "roster", "portal", "access"),
        "broad_audience_deadline_mutation": ("all sections", "course-wide", "everyone", "students"),
        "explicit_graded_item_unchanged": ("clarification", "same due time", "no deadline change", "details"),
        "real_due_date_change": ("time change", "due date", "schedule", "follow-up"),
        "new_graded_item_announcement": ("new item", "posted", "starter files", "announcement"),
        "bulk_schedule_mutation": ("future items", "policy", "schedule rule", "all matching"),
        "exam_logistics_non_target": ("seating", "materials", "room", "review session"),
        "exam_time_change_target": ("start time", "exam time", "new room/time", "timing"),
        "mixed_signal_uncertain": ("follow-up", "heard from section", "thread updated", "quick clarification"),
        "quoted_thread_conflict": ("older note", "reply chain", "deadline thread", "quoted message"),
        "stale_deadline_in_reply_chain": ("old thread", "earlier time", "reply below", "older message"),
        "weak_sender_strong_time_signal": ("forwarded", "copied", "from staff", "deadline"),
        "strong_sender_weak_signal": ("follow-up", "checking", "not final", "pending"),
        "academic_wrapper_with_true_change": ("wrapper", "course site", "update", "timing"),
    }
    pool = hints[family]
    return pool[ordinal % len(pool)]


def quarter_hook(quarter: str) -> str:
    return {"WI": "week 2", "SP": "mid-quarter", "SU": "summer session", "FA": "finals week"}.get(quarter, "this week")


def clean_text_noise(value: str) -> str:
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def style_index(*, scenario: Scenario, ordinal: int) -> int:
    token = f"{scenario.scenario_id}|{scenario.pattern_family}|{scenario.quarter}|{ordinal}"
    return int(hashlib.sha1(token.encode("utf-8")).hexdigest()[:8], 16)


def unique_nonempty(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        candidate = value.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        out.append(candidate)
    return out


def family_body_lines(
    *,
    family: str,
    course_label: str,
    raw_type: str,
    event_name: str,
    due_phrase: str,
    previous_due: str,
    bait_terms: list[str],
    ambiguity_level: str,
    authoritative: bool,
) -> list[str]:
    bait = ", ".join(bait_terms)
    if family == "shipping_subscription_bait":
        return [
            f"Your order summary includes terms like {bait} because this vendor reuses project-style language for promotions.",
            "The message is about delivery, renewal, billing, or account status.",
            "Tracking, payment timing, and renewal settings are available below.",
        ]
    if family == "recruiting_career_internship_bait":
        return [
            "This thread is about applications, recruiter scheduling, or networking follow-up.",
            f"The wording mentions {bait}, but it is tied to hiring workflow rather than course grading.",
            "Interview windows and résumé review notes follow in the footer.",
        ]
    if family == "newsletter_digest_campus_weekly":
        return [
            f"This digest bundles project fair, final reminders, and student events in one place, including bait terms like {bait}.",
            "Multiple unrelated campus items appear together with no single authoritative assignment change.",
            "See the bulleted summary below.",
        ]
    if family == "lms_wrapper_only":
        return [
            f"There was activity in {course_label} related to {raw_type.lower()}.",
            "A comment, gradebook entry, or rubric update is available on the course site.",
            "No new timing statement appears in this wrapper.",
        ]
    if family == "piazza_ed_forum_summary":
        return [
            f"A forum or digest summary for {course_label} is attached below.",
            f"Students discussed {bait}, but the summary itself does not carry a new due-time instruction.",
            "Open the discussion thread for context and replies.",
        ]
    if family == "academic_admin_noise":
        return [
            f"This note covers roster, waitlist, access, or portal logistics for {course_label}.",
            "It is course-adjacent and academic, but the topic is operational rather than deadline-bearing.",
            "Administrative details continue below.",
        ]
    if family == "explicit_graded_item_unchanged":
        return [
            f"Staff are clarifying details around {event_name}.",
            f"The due time remains {due_phrase}.",
            "Rubric wording, section logistics, or submission instructions may have changed, but the deadline did not.",
        ]
    if family == "exam_logistics_non_target":
        return [
            f"This message covers room, seating, materials, and arrival instructions for the {raw_type.lower()}.",
            "The scheduled start time is not being changed in this note.",
            "Please review the logistics checklist below before arriving.",
        ]
    if family == "new_graded_item_announcement":
        return [
            f"{event_name} is now available.",
            f"The current due time is {due_phrase}.",
            "Submission instructions and starter files are included after the main timing line.",
        ]
    if family == "real_due_date_change":
        return [
            f"{event_name} previously appeared as {previous_due}.",
            f"The updated due time is {due_phrase}.",
            "Everything else in the assignment description stays as posted.",
        ]
    if family == "bulk_schedule_mutation":
        return [
            f"All future {raw_type.lower()} items in {course_label} will now move to {due_phrase}.",
            "This is a policy-style schedule update affecting multiple graded items rather than a one-off reminder.",
            "Students in every section should follow the updated timing below.",
        ]
    if family == "broad_audience_deadline_mutation":
        return [
            f"This note goes to all students in {course_label}.",
            f"{event_name} now lands at {due_phrase}.",
            "Broad distribution does not change the fact that the timing statement is authoritative.",
        ]
    if family == "exam_time_change_target":
        return [
            f"The exam notice also includes logistics, but the scheduled time itself changed.",
            f"The new exam time is {due_phrase}.",
            "Room and permitted-material details follow the timing update.",
        ]
    if family == "mixed_signal_uncertain":
        lines = [
            f"Several replies in the thread mention {event_name}.",
            "One note points students back to the current course site entry while another implies the schedule may move.",
        ]
        if ambiguity_level == "high":
            lines.append("The message contains partial updates, forwarding clutter, and no clean final confirmation line.")
        else:
            lines.append(f"A tentative phrase references {due_phrase}, but the wording is not clean enough to rely on alone.")
        return lines
    if family == "quoted_thread_conflict":
        return [
            f"A quoted reply chain about {event_name} appears below.",
            f"Older text mentions {previous_due}, while the new reply references {due_phrase} without clearly stating which is final.",
            "The thread needs a more careful reader than a high-confidence suppressor.",
        ]
    if family == "stale_deadline_in_reply_chain":
        return [
            f"The reply chain still contains an earlier timestamp ({previous_due}).",
            f"A newer message hints at {due_phrase}, but the chain never cleanly resolves the conflict.",
            "Students could reasonably read this thread in different ways.",
        ]
    if family == "weak_sender_strong_time_signal":
        return [
            "Forwarding the timing note below in case you missed the original announcement.",
            f"{event_name} is due {due_phrase}.",
            "The forwarded wrapper and message headers are noisy, but the timing line above is explicit.",
        ]
    if family == "strong_sender_weak_signal":
        lines = [
            f"Staff are following up for {course_label}.",
            "The wording is hedged and never cleanly states whether the schedule actually changed.",
        ]
        if ambiguity_level == "high":
            lines.append("Students are asked to keep checking the course site while staff confirm details.")
        else:
            lines.append("A later confirmation may still be needed.")
        return lines
    return [
        f"The wrapper around {event_name} is noisy, but a concrete timing line appears in the middle of the message.",
        f"The current due time is {due_phrase}.",
        "Quoted replies and LMS text continue after the main update.",
    ]


def render_quoted_thread(*, family: str, course_label: str, raw_type: str, previous_due: str, due_phrase: str, ordinal: int) -> list[str]:
    old_line = {
        "quoted_thread_conflict": f"> Earlier thread: {raw_type} was listed at {previous_due}.",
        "stale_deadline_in_reply_chain": f"> Original message: the deadline showed as {previous_due}.",
        "mixed_signal_uncertain": f"> Earlier note: please keep following the current {course_label} site entry until confirmed.",
    }.get(family, f"> Earlier thread: students were told to use the older time {previous_due}.")
    new_line = {
        "quoted_thread_conflict": f"> Latest reply: someone referenced {due_phrase}, but not everyone agreed.",
        "stale_deadline_in_reply_chain": f"> Follow-up reply: there may be a new time around {due_phrase}.",
        "mixed_signal_uncertain": f"> Forwarded comment: another section heard {due_phrase}, but staff had not posted a final correction.",
    }.get(family, f"> Forwarded note: {due_phrase} appears later in the chain.")
    footer = f"> Thread id fragment {ordinal % 17 + 10}: older messages remain below."
    return [old_line, new_line, footer]


def phase_name_for_quarter(quarter: str) -> str:
    return {
        "WI": "winter quarter rollout and section churn",
        "SP": "spring quarter plus internship traffic",
        "SU": "compressed summer pacing",
        "FA": "fall quarter and finals overlap",
    }.get(quarter, "general academic timing")


def seasonal_intro(quarter: str) -> str:
    return phase_name_for_quarter(quarter)


def render_course_label(course_label: str, *, style: str) -> str:
    normalized = normalize_course_label(course_label) or "CSE120"
    match = re.match(r"^([A-Z]{2,5})(\d{1,3}[A-Z]?)$", normalized)
    if not match:
        return normalized
    dept, number = match.groups()
    if style == "compact":
        return f"{dept}{number}"
    if style == "spaced":
        return f"{dept} {number}"
    if style == "dash":
        return f"{dept}-{number}"
    return f"{dept} {number} / Course Update"


def render_course_tokens(course_label: str) -> list[str]:
    normalized = normalize_course_label(course_label)
    if not normalized:
        return []
    match = re.match(r"^([A-Z]{2,5})(\d{1,3}[A-Z]?)$", normalized)
    if not match:
        return [normalized.lower()]
    dept, number = match.groups()
    return [f"{dept.lower()}{number.lower()}", f"{dept.lower()} {number.lower()}"]


def safe_course_slug(course_label: str) -> str:
    normalized = normalize_course_label(course_label)
    if normalized:
        return normalized.lower()
    match = COURSE_TOKEN_RE.search(course_label)
    if match:
        candidate = normalize_course_label(f"{match.group(1)}{match.group(2)}")
        if candidate:
            return candidate.lower()
    return re.sub(r"[^a-z0-9]+", "", course_label.lower()) or "course"


def mail_domain(kind: str, style: str) -> str:
    table = {
        "faculty": {
            "faculty": "faculty-mail.edu",
            "courses": "faculty-course-updates.edu",
            "department": "faculty-department.edu",
            "registrar": "faculty-registrar.edu",
        },
        "ta": {
            "faculty": "ta-mail.edu",
            "courses": "ta-course-updates.edu",
            "piazza": "ta-forum-mail.edu",
            "edstem": "ta-forum-mail.edu",
        },
        "course_staff": {
            "courses": "course-notify.edu",
            "news": "course-news.edu",
            "weekly": "course-weekly.edu",
            "canvas": "course-canvas-notify.edu",
            "piazza": "course-forum-notify.edu",
            "edstem": "course-forum-notify.edu",
        },
        "campus": {
            "department": "department-updates.edu",
            "students": "student-services.edu",
            "registrar": "registrar-updates.edu",
            "testing": "assessment-notices.edu",
            "faculty": "faculty-admin.edu",
        },
        "digest": {
            "digest": "campusweekly.org",
            "news": "dept-roundup.org",
            "weekly": "weekahead.org",
        },
        "forward": {
            "courses": "course-forward.edu",
            "mail.ops": "forwarded-mail.org",
            "careers": "forwarded-mail.org",
            "notify.mail": "forwarded-mail.org",
            "messages": "forwarded-mail.org",
        },
    }
    return table.get(kind, {}).get(style, f"{style}.mail.edu")


def family_needs_course_context(family: str) -> bool:
    return family not in {
        "shipping_subscription_bait",
        "recruiting_career_internship_bait",
        "newsletter_digest_campus_weekly",
    }


def normalize_course_label(value: str) -> str | None:
    cleaned = value.strip().upper().replace("-", "").replace("_", "").replace("/", "")
    cleaned = cleaned.replace(" ", "")
    match = re.match(r"^([A-Z]{2,5})(\d{1,3}[A-Z]?)$", cleaned)
    if not match:
        return None
    return f"{match.group(1)}{match.group(2)}"


def donor_course_from_draft(draft: Any) -> str | None:
    if not isinstance(draft, dict):
        return None
    dept = str(draft.get("course_dept") or "").upper()
    number = str(draft.get("course_number") or "")
    suffix = str(draft.get("course_suffix") or "").upper()
    if dept and number:
        return f"{dept}{number}{suffix}"
    return None


def infer_raw_type(donor: Donor, *, fallback: str) -> str:
    if donor.raw_type:
        return donor.raw_type
    subject = donor.subject.lower()
    for token in ("homework", "project", "quiz", "midterm", "exam", "assignment", "problem set"):
        if token in subject:
            return token.title()
    return fallback


def fallback_due_phrase(quarter: str, seed: int) -> str:
    month = {"WI": 1, "SP": 4, "SU": 7, "FA": 10}.get(quarter, 1)
    day = 10 + (seed % 18)
    hour = 23 if seed % 3 else 19
    minute = "59" if hour == 23 else "00"
    return f"2026-{month:02d}-{day:02d} {hour:02d}:{minute}:00 UTC"


def derive_quarter(row: dict[str, Any]) -> str:
    phase = str(row.get("phase_label") or "")
    if len(phase) >= 2 and phase[:2].upper() in {"WI", "SP", "SU", "FA"}:
        return phase[:2].upper()
    draft = row.get("expected_semantic_event_draft")
    if isinstance(draft, dict):
        quarter = str(draft.get("course_quarter") or "").upper()
        if quarter in {"WI", "SP", "SU", "FA"}:
            return quarter
    return "unknown"


def collect_course_tokens(row: dict[str, Any]) -> list[str]:
    tokens: list[str] = []
    for candidate in [
        row.get("course_label"),
        row.get("course_hint"),
        *(row.get("known_course_tokens") or []),
    ]:
        if not candidate:
            continue
        normalized = normalize_course_label(str(candidate))
        if normalized:
            rendered = render_course_tokens(normalized)
            for token in rendered:
                if token not in tokens:
                    tokens.append(token)
    text = " ".join(str(row.get(key) or "") for key in ("subject", "body_text"))
    for match in COURSE_TOKEN_RE.finditer(text):
        normalized = normalize_course_label(f"{match.group(1)}{match.group(2)}")
        if normalized:
            for token in render_course_tokens(normalized):
                if token not in tokens:
                    tokens.append(token)
    return tokens[:6]


def extract_notify_email(from_header: str) -> str | None:
    match = EMAIL_RE.search(from_header)
    return match.group(1).strip() if match else None


def extract_domain(from_header: str) -> str:
    email = extract_notify_email(from_header)
    if not email or "@" not in email:
        return ""
    return email.split("@", 1)[1].lower()


def normalize_snippet(snippet: Any, body_text: Any, *, max_chars: int = 180) -> str:
    text = str(snippet or "").strip() or str(body_text or "").strip()
    return " ".join(text.split())[:max_chars]


def normalize_signature(draft: RawDraft) -> str:
    body = " ".join(draft.body_text.lower().split())[:220]
    subject = " ".join(draft.subject.lower().split())
    return f"{draft.scenario.pattern_family}|{subject}|{body}"


def template_signature(draft: RawDraft) -> str:
    text = f"{draft.from_header}\n{draft.subject}\n{draft.body_text}".lower()
    normalized = re.sub(r"20\d{2}-\d{2}-\d{2}", "<date>", text)
    normalized = re.sub(r"\d{1,2}:\d{2}(:\d{2})?", "<time>", normalized)
    normalized = re.sub(r"\b[a-z]{2,5}\s?-?\d{1,3}[a-z]?\b", "<course>", normalized)
    normalized = re.sub(r"<[^>]+>", "<email>", normalized)
    normalized = re.sub(r"\b[a-z0-9]{6,}\b", "<id>", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return f"{draft.scenario.pattern_family}|{normalized[:260]}"


def lower_blob(row: dict[str, Any]) -> str:
    return "\n".join(str(row.get(key) or "") for key in ("subject", "body_text", "from_header", "notes")).lower()


if __name__ == "__main__":
    main()
