#!/usr/bin/env python3
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

ExpectedLinkOutcome = Literal["suffix_required_missing", "suffix_mismatch", "auto_link", "none"]
EventType = Literal["exam", "deadline", "project", "quiz"]

SEMESTER_COURSE_MATRIX: tuple[tuple[str, ...], ...] = (
    ("CSE151A", "CSE151B", "CSE120"),
    ("CSE120", "MATH18"),
    ("CSE151A", "CSE120"),
)


@dataclass(frozen=True)
class CourseAnchor:
    label: str
    dept: str
    number: int
    suffix: str | None


@dataclass(frozen=True)
class IcsEventPlan:
    event_id: str
    event_uid: str
    title: str
    due_iso: str
    event_type: EventType
    event_index: int
    course: CourseAnchor


@dataclass(frozen=True)
class GmailMessagePlan:
    message_id: str
    thread_id: str
    subject: str
    body_text: str
    from_header: str
    label_ids: list[str]
    internal_date: str
    due_iso: str
    event_type: EventType
    event_index: int
    history_batch: int
    history_global_batch: int
    course: CourseAnchor
    expected_link_outcome: ExpectedLinkOutcome = "none"


@dataclass(frozen=True)
class BatchPlan:
    semester: int
    batch: int
    global_batch: int
    start_iso: str
    ics_events: list[IcsEventPlan]
    gmail_messages: list[GmailMessagePlan]


@dataclass(frozen=True)
class SemesterPlan:
    semester: int
    courses: list[str]
    batches: list[BatchPlan]


@dataclass(frozen=True)
class ScenarioManifest:
    version: str
    seed: int
    semesters: int
    batches_per_semester: int
    batch_size: int
    plans: list[SemesterPlan]

    def to_dict(self) -> dict:
        return asdict(self)


def build_scenario_manifest(
    *,
    semesters: int = 3,
    batches_per_semester: int = 10,
    batch_size: int = 10,
    seed: int = 20260305,
) -> ScenarioManifest:
    if semesters != 3:
        raise ValueError("semesters must be 3 for this fixed high-fidelity demo")
    if batches_per_semester != 10:
        raise ValueError("batches_per_semester must be 10 for this fixed high-fidelity demo")
    if batch_size != 10:
        raise ValueError("batch_size must be 10 for this fixed high-fidelity demo")

    rng = random.Random(seed)
    plans: list[SemesterPlan] = []
    base_start = datetime(2026, 1, 12, 17, 0, tzinfo=UTC)
    global_batch = 0

    for semester_idx in range(1, semesters + 1):
        courses = list(SEMESTER_COURSE_MATRIX[semester_idx - 1])
        batches: list[BatchPlan] = []
        for batch_idx in range(1, batches_per_semester + 1):
            global_batch += 1
            batch_start = base_start + timedelta(days=(semester_idx - 1) * 120 + (batch_idx - 1) * 5)
            ics_events, gmail_messages = _build_batch_rows(
                rng=rng,
                semester=semester_idx,
                batch=batch_idx,
                global_batch=global_batch,
                batch_start=batch_start,
                courses=courses,
                batch_size=batch_size,
            )
            batches.append(
                BatchPlan(
                    semester=semester_idx,
                    batch=batch_idx,
                    global_batch=global_batch,
                    start_iso=batch_start.isoformat(),
                    ics_events=ics_events,
                    gmail_messages=gmail_messages,
                )
            )
        plans.append(SemesterPlan(semester=semester_idx, courses=courses, batches=batches))

    return ScenarioManifest(
        version="semester-demo-v2",
        seed=seed,
        semesters=semesters,
        batches_per_semester=batches_per_semester,
        batch_size=batch_size,
        plans=plans,
    )


def write_scenario_manifest(path: Path, manifest: ScenarioManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _build_batch_rows(
    *,
    rng: random.Random,
    semester: int,
    batch: int,
    global_batch: int,
    batch_start: datetime,
    courses: list[str],
    batch_size: int,
) -> tuple[list[IcsEventPlan], list[GmailMessagePlan]]:
    ics_rows: list[IcsEventPlan] = []
    gmail_rows: list[GmailMessagePlan] = []
    event_types: tuple[EventType, ...] = ("exam", "deadline", "project", "quiz")

    special_suffix_cases = semester == 1 and batch == 1
    if special_suffix_cases:
        ics_rows.extend(
            [
                _build_ics_event(
                    semester=semester,
                    batch=batch,
                    item_index=0,
                    due_at=batch_start + timedelta(hours=3),
                    course=_parse_course_label("CSE151A"),
                    event_type="exam",
                    event_index=1,
                ),
                _build_ics_event(
                    semester=semester,
                    batch=batch,
                    item_index=1,
                    due_at=batch_start + timedelta(hours=4),
                    course=_parse_course_label("CSE151B"),
                    event_type="exam",
                    event_index=1,
                ),
            ]
        )
        gmail_rows.extend(
            [
                _build_gmail_message(
                    semester=semester,
                    batch=batch,
                    global_batch=global_batch,
                    item_index=0,
                    due_at=batch_start + timedelta(hours=3, minutes=10),
                    course=CourseAnchor(label="CSE151", dept="CSE", number=151, suffix=None),
                    event_type="exam",
                    event_index=1,
                    expected_link_outcome="suffix_required_missing",
                ),
                _build_gmail_message(
                    semester=semester,
                    batch=batch,
                    global_batch=global_batch,
                    item_index=1,
                    due_at=batch_start + timedelta(hours=3, minutes=20),
                    course=CourseAnchor(label="CSE151C", dept="CSE", number=151, suffix="C"),
                    event_type="exam",
                    event_index=1,
                    expected_link_outcome="suffix_mismatch",
                ),
                _build_gmail_message(
                    semester=semester,
                    batch=batch,
                    global_batch=global_batch,
                    item_index=2,
                    due_at=batch_start + timedelta(hours=3, minutes=30),
                    course=_parse_course_label("CSE151B"),
                    event_type="exam",
                    event_index=1,
                    expected_link_outcome="auto_link",
                ),
            ]
        )

    while len(ics_rows) < batch_size or len(gmail_rows) < batch_size:
        item_index = min(len(ics_rows), len(gmail_rows))
        course_label = courses[item_index % len(courses)]
        course = _parse_course_label(course_label)
        due_at = batch_start + timedelta(hours=6 + item_index)
        event_type = event_types[(global_batch + item_index) % len(event_types)]
        event_index = 1 + ((global_batch + item_index) % 3)
        if len(ics_rows) < batch_size:
            ics_rows.append(
                _build_ics_event(
                    semester=semester,
                    batch=batch,
                    item_index=item_index,
                    due_at=due_at,
                    course=course,
                    event_type=event_type,
                    event_index=event_index,
                )
            )
        if len(gmail_rows) < batch_size:
            gmail_rows.append(
                _build_gmail_message(
                    semester=semester,
                    batch=batch,
                    global_batch=global_batch,
                    item_index=item_index,
                    due_at=due_at + timedelta(minutes=rng.randint(0, 20)),
                    course=course,
                    event_type=event_type,
                    event_index=event_index,
                    expected_link_outcome="none",
                )
            )

    return ics_rows[:batch_size], gmail_rows[:batch_size]


def _build_ics_event(
    *,
    semester: int,
    batch: int,
    item_index: int,
    due_at: datetime,
    course: CourseAnchor,
    event_type: EventType,
    event_index: int,
) -> IcsEventPlan:
    event_id = f"s{semester:02d}-b{batch:02d}-ics-{item_index:03d}"
    title = f"{course.label} {event_type.title()} {event_index} Deadline"
    return IcsEventPlan(
        event_id=event_id,
        event_uid=f"{event_id}@calendar-diff.demo",
        title=title,
        due_iso=due_at.isoformat(),
        event_type=event_type,
        event_index=event_index,
        course=course,
    )


def _build_gmail_message(
    *,
    semester: int,
    batch: int,
    global_batch: int,
    item_index: int,
    due_at: datetime,
    course: CourseAnchor,
    event_type: EventType,
    event_index: int,
    expected_link_outcome: ExpectedLinkOutcome,
) -> GmailMessagePlan:
    message_id = f"s{semester:02d}-b{batch:02d}-gmail-{item_index:03d}"
    thread_id = f"thread-s{semester:02d}-b{batch:02d}-{course.label.lower()}-{event_type}-{event_index}"
    subject = f"[{course.label}] {event_type.title()} {event_index} deadline update"
    body_text = (
        f"Course: {course.label}\n"
        f"Type: {event_type}\n"
        f"Index: {event_index}\n"
        f"Due timestamp: {due_at.isoformat()}\n"
        "Please treat this as the latest authoritative update for planning."
    )
    return GmailMessagePlan(
        message_id=message_id,
        thread_id=thread_id,
        subject=subject,
        body_text=body_text,
        from_header=f"{course.label} Staff <staff+{course.dept.lower()}{course.number}@example.edu>",
        label_ids=["INBOX", "CATEGORY_PERSONAL"],
        internal_date=due_at.isoformat(),
        due_iso=due_at.isoformat(),
        event_type=event_type,
        event_index=event_index,
        history_batch=batch,
        history_global_batch=global_batch,
        course=course,
        expected_link_outcome=expected_link_outcome,
    )


def _parse_course_label(label: str) -> CourseAnchor:
    cleaned = label.strip().upper()
    idx = 0
    while idx < len(cleaned) and cleaned[idx].isalpha():
        idx += 1
    j = idx
    while j < len(cleaned) and cleaned[j].isdigit():
        j += 1
    dept = cleaned[:idx]
    number_token = cleaned[idx:j]
    suffix_token = cleaned[j:] or None
    if not dept or not number_token:
        raise ValueError(f"invalid course label: {label}")
    return CourseAnchor(
        label=cleaned,
        dept=dept,
        number=int(number_token),
        suffix=suffix_token,
    )


__all__ = [
    "BatchPlan",
    "CourseAnchor",
    "ExpectedLinkOutcome",
    "GmailMessagePlan",
    "IcsEventPlan",
    "ScenarioManifest",
    "SemesterPlan",
    "build_scenario_manifest",
    "write_scenario_manifest",
]
