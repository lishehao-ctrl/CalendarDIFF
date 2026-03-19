from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

EventType = Literal["deadline", "quiz", "project", "exam"]
MessageKind = Literal["atomic_new", "atomic_change", "directive", "reminder_noise", "lab_noise", "admin_noise"]
ActorRole = Literal["professor", "ta", "course_staff_alias", "canvas_wrapper", "lab_coordinator", "department_admin"]
AuthorityLevel = Literal["high", "medium", "low", "system"]
CourseArchetype = Literal[
    "programming_systems",
    "math_problem_set",
    "project_heavy_ml",
    "lab_report_science",
    "discussion_reading",
]
TeachingStyle = Literal["strict_canvas", "email_heavy", "staff_alias_driven", "ta_reminder_heavy"]
ChannelBehavior = Literal["canvas_first", "email_first", "same_batch", "canvas_plus_1_batch", "email_plus_1_batch"]
ChannelTimingMode = Literal["canvas_first", "email_first", "same_batch", "canvas_plus_1_batch", "email_plus_1_batch", "calendar_only"]
WeekStage = Literal["setup_release", "early_ramp", "first_pressure", "project_push", "late_crunch", "finals_rollover"]
MessageIntent = Literal[
    "authoritative_new",
    "authoritative_change",
    "policy_change",
    "pre_notice",
    "confirmation",
    "reminder",
    "wrapper_notice",
    "lab_logistics",
    "admin_rollover",
]
JunkProfile = Literal[
    "formal_explanation",
    "ops_short",
    "alias_broadcast",
    "lms_wrapper",
    "lab_logistics",
    "department_bureaucracy",
    "faq_digest",
    "project_checklist",
]
IcsChangeKind = Literal[
    "stable",
    "newly_posted",
    "due_date_shift",
    "due_time_shift",
    "title_alias_change",
    "removed",
    "exam_schedule_change",
]

DEFAULT_SEMESTERS = 4
DEFAULT_BATCHES_PER_SEMESTER = 12
DEFAULT_BATCH_SIZE = 12
DEFAULT_SEED = 20260317
TOTAL_BATCHES = DEFAULT_SEMESTERS * DEFAULT_BATCHES_PER_SEMESTER

PHASES = (
    {"semester": 1, "label": "WI26", "start": datetime(2026, 1, 12, 17, 0, tzinfo=UTC), "courses": ("CSE120", "CSE151A", "MATH18")},
    {"semester": 2, "label": "SP26", "start": datetime(2026, 4, 6, 17, 0, tzinfo=UTC), "courses": ("CSE120", "CSE151A", "MATH20C")},
    {"semester": 3, "label": "SU26", "start": datetime(2026, 6, 29, 17, 0, tzinfo=UTC), "courses": ("CSE151A", "DSC10", "COGS108")},
    {"semester": 4, "label": "FA26", "start": datetime(2026, 9, 28, 17, 0, tzinfo=UTC), "courses": ("CSE120", "DSC10", "CHEM6A")},
)


@dataclass(frozen=True)
class CourseAnchor:
    label: str
    dept: str
    number: int
    suffix: str | None


@dataclass(frozen=True)
class CourseStaffProfile:
    professor_name: str
    ta_names: tuple[str, ...]
    course_alias_name: str
    lab_coordinator_name: str
    department_admin_name: str


@dataclass(frozen=True)
class CourseProfile:
    course_label: str
    course_archetype: CourseArchetype
    teaching_style: TeachingStyle
    channel_behavior: ChannelBehavior
    aliases: dict[EventType, tuple[str, ...]]
    staff: CourseStaffProfile
    alias_drift_strength: int
    inventory_target: int


@dataclass(frozen=True)
class PhaseProfile:
    phase_label: str
    season_name: str
    is_summer: bool
    compression_days: int
    bureaucracy_level: int


COURSE_PROFILES: dict[str, CourseProfile] = {
    "CSE120": CourseProfile(
        course_label="CSE120",
        course_archetype="programming_systems",
        teaching_style="staff_alias_driven",
        channel_behavior="same_batch",
        aliases={
            "deadline": ("Homework", "HW", "Problem Set"),
            "quiz": ("Quiz", "Check-in", "Weekly Quiz"),
            "project": ("Project Milestone", "Milestone", "Project Checkpoint"),
            "exam": ("Midterm", "Exam", "Assessment"),
        },
        staff=CourseStaffProfile(
            professor_name="Prof. Elena Park",
            ta_names=("Mina Chen", "Alex Romero"),
            course_alias_name="CSE 120 Course Staff",
            lab_coordinator_name="CSE 120 Labs",
            department_admin_name="CSE Undergraduate Office",
        ),
        alias_drift_strength=2,
        inventory_target=5,
    ),
    "MATH18": CourseProfile(
        course_label="MATH18",
        course_archetype="math_problem_set",
        teaching_style="email_heavy",
        channel_behavior="email_first",
        aliases={
            "deadline": ("Homework", "Worksheet", "Practice Set"),
            "quiz": ("Quiz", "Concept Quiz", "Short Quiz"),
            "project": ("Modeling Task", "Applied Task", "Mini Project"),
            "exam": ("Midterm", "Exam", "Written Exam"),
        },
        staff=CourseStaffProfile(
            professor_name="Prof. Hannah Doyle",
            ta_names=("Eric Xu", "Nora Patel"),
            course_alias_name="Math 18 Staff",
            lab_coordinator_name="Math 18 Sections",
            department_admin_name="Mathematics Student Affairs",
        ),
        alias_drift_strength=2,
        inventory_target=5,
    ),
    "CSE151A": CourseProfile(
        course_label="CSE151A",
        course_archetype="project_heavy_ml",
        teaching_style="ta_reminder_heavy",
        channel_behavior="canvas_plus_1_batch",
        aliases={
            "deadline": ("Programming Assignment", "PA", "Homework"),
            "quiz": ("Quiz", "Code Quiz", "Checkpoint Quiz"),
            "project": ("Project Milestone", "Milestone", "Deliverable"),
            "exam": ("Midterm", "Exam", "Coding Exam"),
        },
        staff=CourseStaffProfile(
            professor_name="Prof. Theo Raman",
            ta_names=("Jordan Lee", "Priya Sethi"),
            course_alias_name="CSE 151A Staff",
            lab_coordinator_name="CSE 151A Project Pods",
            department_admin_name="CSE Advising",
        ),
        alias_drift_strength=3,
        inventory_target=5,
    ),
    "MATH20C": CourseProfile(
        course_label="MATH20C",
        course_archetype="math_problem_set",
        teaching_style="strict_canvas",
        channel_behavior="email_plus_1_batch",
        aliases={
            "deadline": ("Homework", "Problem Set", "Written Homework"),
            "quiz": ("Quiz", "Recitation Quiz", "Short Quiz"),
            "project": ("Applied Task", "Worksheet Project", "Mini Project"),
            "exam": ("Midterm", "Exam", "Written Exam"),
        },
        staff=CourseStaffProfile(
            professor_name="Prof. Marco Silva",
            ta_names=("Sofia Kim", "Daniel Ng"),
            course_alias_name="Math 20C Staff",
            lab_coordinator_name="Math 20C Discussion",
            department_admin_name="Mathematics Student Affairs",
        ),
        alias_drift_strength=1,
        inventory_target=5,
    ),
    "DSC10": CourseProfile(
        course_label="DSC10",
        course_archetype="discussion_reading",
        teaching_style="email_heavy",
        channel_behavior="email_first",
        aliases={
            "deadline": ("Homework", "Lab Homework", "Notebook Submission"),
            "quiz": ("Reading Quiz", "Quiz", "Knowledge Check"),
            "project": ("Notebook Milestone", "Checkpoint", "Project Milestone"),
            "exam": ("Midterm", "Exam", "Timed Assessment"),
        },
        staff=CourseStaffProfile(
            professor_name="Prof. Leila Nouri",
            ta_names=("Sam Wu", "Ari Flores"),
            course_alias_name="DSC 10 Staff",
            lab_coordinator_name="DSC 10 Tutors",
            department_admin_name="Data Science Student Affairs",
        ),
        alias_drift_strength=3,
        inventory_target=4,
    ),
    "COGS108": CourseProfile(
        course_label="COGS108",
        course_archetype="project_heavy_ml",
        teaching_style="email_heavy",
        channel_behavior="canvas_first",
        aliases={
            "deadline": ("Assignment", "Project Task", "Homework"),
            "quiz": ("Reading Quiz", "Concept Quiz", "Quiz"),
            "project": ("Team Deliverable", "Milestone", "Project Milestone"),
            "exam": ("Final Checkpoint", "Exam", "Assessment"),
        },
        staff=CourseStaffProfile(
            professor_name="Prof. Daniel Kim",
            ta_names=("Lena Ortiz", "Ben Shah"),
            course_alias_name="COGS 108 Staff",
            lab_coordinator_name="COGS 108 Labs",
            department_admin_name="Cognitive Science Student Affairs",
        ),
        alias_drift_strength=3,
        inventory_target=4,
    ),
    "CHEM6A": CourseProfile(
        course_label="CHEM6A",
        course_archetype="lab_report_science",
        teaching_style="strict_canvas",
        channel_behavior="canvas_first",
        aliases={
            "deadline": ("Homework", "Problem Set", "Chem Homework"),
            "quiz": ("Quiz", "Short Quiz", "Knowledge Check"),
            "project": ("Lab Report", "Report", "Write-up"),
            "exam": ("Midterm", "Exam", "Chemistry Exam"),
        },
        staff=CourseStaffProfile(
            professor_name="Prof. Rina Patel",
            ta_names=("Owen Brooks", "Yuna Choi"),
            course_alias_name="CHEM 6A Staff",
            lab_coordinator_name="CHEM 6A Labs",
            department_admin_name="Chemistry Instruction Office",
        ),
        alias_drift_strength=1,
        inventory_target=4,
    ),
}


@dataclass(frozen=True)
class TimelineIcsEventPlan:
    event_id: str
    entity_uid: str
    title: str
    due_iso: str
    event_type: EventType
    event_index: int
    course: CourseAnchor
    family_label: str
    ordinal: int
    phase_label: str
    continuity_key: str
    canonical_event_name: str
    course_archetype: CourseArchetype
    teaching_style: TeachingStyle
    channel_behavior: ChannelBehavior
    week_stage: WeekStage
    channel_timing_mode: ChannelTimingMode
    ics_change_kind: IcsChangeKind
    hard_case_tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TimelineGmailMessagePlan:
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
    family_label: str
    ordinal: int
    message_kind: MessageKind
    continuity_key: str | None
    expected_link_outcome: str = "none"
    canonical_event_name: str | None = None
    previous_due_iso: str | None = None
    selector_ordinals: list[int] = field(default_factory=list)
    directive_scope_mode: str | None = None
    current_due_weekday: str | None = None
    move_weekday: str | None = None
    set_due_date: str | None = None
    hard_case_tags: list[str] = field(default_factory=list)
    actor_role: ActorRole = "course_staff_alias"
    authority_level: AuthorityLevel = "medium"
    channel_timing_mode: ChannelTimingMode = "same_batch"
    message_intent: MessageIntent = "reminder"
    junk_profile: JunkProfile = "ops_short"
    course_archetype: CourseArchetype = "programming_systems"
    teaching_style: TeachingStyle = "staff_alias_driven"
    channel_behavior: ChannelBehavior = "same_batch"
    week_stage: WeekStage = "setup_release"


@dataclass(frozen=True)
class BatchPlan:
    semester: int
    batch: int
    global_batch: int
    start_iso: str
    phase_label: str
    week_stage: WeekStage
    ics_events: list[TimelineIcsEventPlan]
    gmail_messages: list[TimelineGmailMessagePlan]


@dataclass(frozen=True)
class SemesterPlan:
    semester: int
    phase_label: str
    courses: list[str]
    batches: list[BatchPlan]


@dataclass(frozen=True)
class YearTimelineManifest:
    version: str
    seed: int
    semesters: int
    batches_per_semester: int
    batch_size: int
    plans: list[SemesterPlan]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _TimelineItemState:
    course: CourseAnchor
    course_archetype: CourseArchetype
    teaching_style: TeachingStyle
    channel_behavior: ChannelBehavior
    family_label: str
    event_type: EventType
    ordinal: int
    due_at: datetime
    entity_uid: str
    event_id: str
    continuity_key: str
    title: str
    created_global_batch: int
    canonical_event_name: str
    week_stage: WeekStage
    channel_timing_mode: ChannelTimingMode
    ics_change_kind: IcsChangeKind
    visible_in_ics_from_batch: int
    hard_case_tags: list[str]
    title_alias_variant: int = 0
    removed: bool = False


@dataclass(frozen=True)
class _EmailSignal:
    item: _TimelineItemState
    kind: Literal["atomic_new", "atomic_change"]
    actor_role: ActorRole
    authority_level: AuthorityLevel
    channel_timing_mode: ChannelTimingMode
    message_intent: MessageIntent
    junk_profile: JunkProfile
    subject_alias: str
    body_alias: str
    hard_case_tags: tuple[str, ...]
    previous_due_iso: str | None = None
    narrative_hint: str | None = None


def build_year_timeline_manifest(
    *,
    semesters: int = DEFAULT_SEMESTERS,
    batches_per_semester: int = DEFAULT_BATCHES_PER_SEMESTER,
    batch_size: int = DEFAULT_BATCH_SIZE,
    seed: int = DEFAULT_SEED,
) -> YearTimelineManifest:
    if semesters != DEFAULT_SEMESTERS:
        raise ValueError(f"semesters must be {DEFAULT_SEMESTERS} for the current year timeline builder")
    if batches_per_semester != DEFAULT_BATCHES_PER_SEMESTER:
        raise ValueError(f"batches_per_semester must be {DEFAULT_BATCHES_PER_SEMESTER} for the current year timeline builder")
    if batch_size != DEFAULT_BATCH_SIZE:
        raise ValueError(f"batch_size must be {DEFAULT_BATCH_SIZE} for the current year timeline builder")

    rng = random.Random(seed)
    ordinal_counters: dict[tuple[str, EventType], int] = {}
    phase_plans: list[SemesterPlan] = []
    global_batch = 0

    for phase in PHASES[:semesters]:
        semester = int(phase["semester"])
        phase_label = str(phase["label"])
        phase_profile = _phase_profile(phase_label)
        courses = [str(value) for value in phase["courses"]]
        course_states = {course_label: [] for course_label in courses}
        batches: list[BatchPlan] = []

        for batch in range(1, batches_per_semester + 1):
            global_batch += 1
            batch_start = phase["start"] + timedelta(days=(batch - 1) * 7)
            week_stage = _week_stage_for_batch(batch)
            selected_ics, gmail_messages = _build_batch(
                rng=rng,
                semester=semester,
                phase_label=phase_label,
                phase_profile=phase_profile,
                batch=batch,
                global_batch=global_batch,
                batch_start=batch_start,
                batch_size=batch_size,
                course_labels=courses,
                course_states=course_states,
                ordinal_counters=ordinal_counters,
                week_stage=week_stage,
            )
            batches.append(
                BatchPlan(
                    semester=semester,
                    batch=batch,
                    global_batch=global_batch,
                    start_iso=batch_start.isoformat(),
                    phase_label=phase_label,
                    week_stage=week_stage,
                    ics_events=selected_ics,
                    gmail_messages=gmail_messages,
                )
            )

        phase_plans.append(
            SemesterPlan(
                semester=semester,
                phase_label=phase_label,
                courses=courses,
                batches=batches,
            )
        )

    return YearTimelineManifest(
        version="year-timeline-current",
        seed=seed,
        semesters=semesters,
        batches_per_semester=batches_per_semester,
        batch_size=batch_size,
        plans=phase_plans,
    )


def write_year_timeline_manifest(path: Path, manifest: YearTimelineManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _build_batch(
    *,
    rng: random.Random,
    semester: int,
    phase_label: str,
    phase_profile: PhaseProfile,
    batch: int,
    global_batch: int,
    batch_start: datetime,
    batch_size: int,
    course_labels: list[str],
    course_states: dict[str, list[_TimelineItemState]],
    ordinal_counters: dict[tuple[str, EventType], int],
    week_stage: WeekStage,
) -> tuple[list[TimelineIcsEventPlan], list[TimelineGmailMessagePlan]]:
    new_signals: list[_EmailSignal] = []
    change_signals: list[_EmailSignal] = []
    professor_confirmation_items: list[_TimelineItemState] = []

    for course_label in course_labels:
        profile = COURSE_PROFILES[course_label]
        states = course_states[course_label]
        _prune_states(states=states, batch_start=batch_start, global_batch=global_batch)
        _ensure_inventory(
            rng=rng,
            profile=profile,
            semester=semester,
            phase_label=phase_label,
            phase_profile=phase_profile,
            batch=batch,
            global_batch=global_batch,
            batch_start=batch_start,
            week_stage=week_stage,
            states=states,
            ordinal_counters=ordinal_counters,
        )

        new_item = _create_released_item(
            rng=rng,
            profile=profile,
            semester=semester,
            phase_label=phase_label,
            phase_profile=phase_profile,
            batch=batch,
            global_batch=global_batch,
            batch_start=batch_start,
            week_stage=week_stage,
            ordinal_counters=ordinal_counters,
        )
        states.append(new_item)
        new_signals.append(_build_new_signal(item=new_item, batch=batch, global_batch=global_batch))

        change_signal, needs_professor_confirmation = _apply_primary_change(
            rng=rng,
            profile=profile,
            phase_profile=phase_profile,
            batch=batch,
            global_batch=global_batch,
            batch_start=batch_start,
            week_stage=week_stage,
            states=states,
            new_item=new_item,
        )
        change_signals.append(change_signal)
        if needs_professor_confirmation:
            professor_confirmation_items.append(change_signal.item)

        _apply_extra_ics_realism(
            rng=rng,
            profile=profile,
            phase_profile=phase_profile,
            batch=batch,
            global_batch=global_batch,
            batch_start=batch_start,
            week_stage=week_stage,
            states=states,
            exclude_keys={new_item.continuity_key, change_signal.item.continuity_key},
        )

        states.sort(key=lambda row: (row.due_at, row.ordinal, row.event_id))
        active_rows = [row for row in states if not row.removed]
        max_active = profile.inventory_target + (1 if not phase_profile.is_summer else 0)
        if len(active_rows) > max_active:
            overflow = len(active_rows) - max_active
            for row in active_rows[:overflow]:
                if row.visible_in_ics_from_batch < global_batch and row.due_at < batch_start + timedelta(days=5):
                    row.removed = True
                    row.ics_change_kind = "removed"
                    row.channel_timing_mode = "calendar_only"
                    row.hard_case_tags = _dedupe_tags(row.hard_case_tags + ["quarter_rollover_admin_noise"] if week_stage == "finals_rollover" else row.hard_case_tags)

    visible_items = sorted(
        [
            row
            for states in course_states.values()
            for row in states
            if not row.removed and row.visible_in_ics_from_batch <= global_batch
        ],
        key=lambda row: (row.due_at, row.course.label, row.ordinal, row.event_id),
    )
    selected_items = visible_items[:batch_size]
    ics_events = [_serialize_ics_event(row=row, phase_label=phase_label) for row in selected_items]

    directive_messages = _apply_directives_for_batch(
        phase_label=phase_label,
        phase_profile=phase_profile,
        batch=batch,
        global_batch=global_batch,
        batch_start=batch_start,
        week_stage=week_stage,
        course_states=course_states,
        semester=semester,
    )
    reminder_messages = _build_reminder_messages(
        rng=rng,
        semester=semester,
        phase_label=phase_label,
        batch=batch,
        global_batch=global_batch,
        batch_start=batch_start,
        week_stage=week_stage,
        selected_items=selected_items,
        professor_confirmation_items=professor_confirmation_items,
    )
    lab_message = _build_lab_noise_message(
        semester=semester,
        phase_label=phase_label,
        batch=batch,
        global_batch=global_batch,
        batch_start=batch_start,
        week_stage=week_stage,
        course_label=course_labels[(global_batch + 1) % len(course_labels)],
    )
    admin_message = _build_admin_noise_message(
        semester=semester,
        phase_label=phase_label,
        batch=batch,
        global_batch=global_batch,
        batch_start=batch_start,
        week_stage=week_stage,
        course_label=course_labels[(global_batch + 2) % len(course_labels)],
    )

    messages: list[TimelineGmailMessagePlan] = []
    message_slot = 0
    for signal in change_signals[:3]:
        messages.append(
            _realize_atomic_message(
                signal=signal,
                semester=semester,
                phase_label=phase_label,
                batch=batch,
                global_batch=global_batch,
                batch_start=batch_start,
                week_stage=week_stage,
                slot=message_slot,
            )
        )
        message_slot += 1
    for signal in new_signals[:3]:
        messages.append(
            _realize_atomic_message(
                signal=signal,
                semester=semester,
                phase_label=phase_label,
                batch=batch,
                global_batch=global_batch,
                batch_start=batch_start,
                week_stage=week_stage,
                slot=message_slot,
            )
        )
        message_slot += 1
    for message in directive_messages[:2]:
        messages.append(_renumber_message(message=message, semester=semester, batch=batch, slot=message_slot))
        message_slot += 1
    for message in (lab_message, admin_message):
        messages.append(_renumber_message(message=message, semester=semester, batch=batch, slot=message_slot))
        message_slot += 1
    for message in reminder_messages[:2]:
        messages.append(_renumber_message(message=message, semester=semester, batch=batch, slot=message_slot))
        message_slot += 1

    if len(messages) != batch_size:
        raise RuntimeError(f"expected {batch_size} gmail messages, got {len(messages)}")
    return ics_events, messages


def _phase_profile(phase_label: str) -> PhaseProfile:
    if phase_label == "SU26":
        return PhaseProfile(
            phase_label=phase_label,
            season_name="summer",
            is_summer=True,
            compression_days=3,
            bureaucracy_level=1,
        )
    if phase_label == "WI26":
        season = "winter"
    elif phase_label == "SP26":
        season = "spring"
    else:
        season = "fall"
    return PhaseProfile(
        phase_label=phase_label,
        season_name=season,
        is_summer=False,
        compression_days=0,
        bureaucracy_level=3,
    )


def _week_stage_for_batch(batch: int) -> WeekStage:
    if batch == 1:
        return "setup_release"
    if batch in {2, 3}:
        return "early_ramp"
    if batch in {4, 5}:
        return "first_pressure"
    if batch in {6, 7, 8}:
        return "project_push"
    if batch in {9, 10}:
        return "late_crunch"
    return "finals_rollover"


def _prune_states(*, states: list[_TimelineItemState], batch_start: datetime, global_batch: int) -> None:
    states[:] = [
        row
        for row in states
        if (not row.removed and row.due_at >= batch_start - timedelta(days=28))
        or row.visible_in_ics_from_batch > global_batch
    ]


def _ensure_inventory(
    *,
    rng: random.Random,
    profile: CourseProfile,
    semester: int,
    phase_label: str,
    phase_profile: PhaseProfile,
    batch: int,
    global_batch: int,
    batch_start: datetime,
    week_stage: WeekStage,
    states: list[_TimelineItemState],
    ordinal_counters: dict[tuple[str, EventType], int],
) -> None:
    active = [row for row in states if not row.removed]
    while len(active) < profile.inventory_target:
        event_type = _event_type_for_context(
            profile=profile,
            phase_profile=phase_profile,
            week_stage=week_stage,
            selector=len(active) + batch + global_batch,
        )
        item = _create_item(
            profile=profile,
            semester=semester,
            phase_label=phase_label,
            batch=batch,
            global_batch=global_batch,
            batch_start=batch_start,
            phase_profile=phase_profile,
            week_stage=week_stage,
            event_type=event_type,
            ordinal_counters=ordinal_counters,
            lead_days=_lead_days_for_item(
                profile=profile,
                phase_profile=phase_profile,
                week_stage=week_stage,
                event_type=event_type,
                ordinal_seed=len(active) + global_batch,
                prefill=True,
            ),
            visible_in_ics_from_batch=global_batch,
            channel_timing_mode="canvas_first",
            ics_change_kind="stable",
            hard_case_tags=[],
            title_alias_variant=rng.randint(0, min(profile.alias_drift_strength, 1)),
        )
        states.append(item)
        active.append(item)


def _create_released_item(
    *,
    rng: random.Random,
    profile: CourseProfile,
    semester: int,
    phase_label: str,
    phase_profile: PhaseProfile,
    batch: int,
    global_batch: int,
    batch_start: datetime,
    week_stage: WeekStage,
    ordinal_counters: dict[tuple[str, EventType], int],
) -> _TimelineItemState:
    event_type = _event_type_for_context(
        profile=profile,
        phase_profile=phase_profile,
        week_stage=week_stage,
        selector=batch + global_batch + profile.inventory_target,
    )
    channel_mode = _new_item_channel_mode(profile=profile, batch=batch, global_batch=global_batch)
    visible_from = global_batch + 1 if channel_mode == "canvas_plus_1_batch" and global_batch < TOTAL_BATCHES else global_batch
    tags: list[str] = []
    if channel_mode == "canvas_plus_1_batch":
        tags.append("email_only_pre_announcement")
    item = _create_item(
        profile=profile,
        semester=semester,
        phase_label=phase_label,
        batch=batch,
        global_batch=global_batch,
        batch_start=batch_start,
        phase_profile=phase_profile,
        week_stage=week_stage,
        event_type=event_type,
        ordinal_counters=ordinal_counters,
        lead_days=_lead_days_for_item(
            profile=profile,
            phase_profile=phase_profile,
            week_stage=week_stage,
            event_type=event_type,
            ordinal_seed=batch + global_batch + rng.randint(0, 3),
            prefill=False,
        ),
        visible_in_ics_from_batch=visible_from,
        channel_timing_mode=channel_mode,
        ics_change_kind="newly_posted",
        hard_case_tags=tags,
        title_alias_variant=0,
    )
    return item


def _create_item(
    *,
    profile: CourseProfile,
    semester: int,
    phase_label: str,
    batch: int,
    global_batch: int,
    batch_start: datetime,
    phase_profile: PhaseProfile,
    week_stage: WeekStage,
    event_type: EventType,
    ordinal_counters: dict[tuple[str, EventType], int],
    lead_days: int,
    visible_in_ics_from_batch: int,
    channel_timing_mode: ChannelTimingMode,
    ics_change_kind: IcsChangeKind,
    hard_case_tags: list[str],
    title_alias_variant: int,
) -> _TimelineItemState:
    course = _parse_course_label(profile.course_label)
    key = (course.label, event_type)
    ordinal = ordinal_counters.get(key, 0) + 1
    ordinal_counters[key] = ordinal
    family_label = profile.aliases[event_type][0]
    due_at = _due_at_for_new_item(
        batch_start=batch_start,
        phase_profile=phase_profile,
        event_type=event_type,
        lead_days=lead_days,
        ordinal=ordinal,
        course_number=course.number,
    )
    continuity_key = f"{course.label.lower()}-{event_type}-{ordinal}"
    entity_uid = f"{phase_label.lower()}-{continuity_key}@year-timeline.synthetic"
    event_id = f"{phase_label.lower()}-{continuity_key}"
    title = _ics_title(profile=profile, course=course, event_type=event_type, ordinal=ordinal, alias_variant=title_alias_variant)
    canonical_event_name = f"{family_label} {ordinal}"
    return _TimelineItemState(
        course=course,
        course_archetype=profile.course_archetype,
        teaching_style=profile.teaching_style,
        channel_behavior=profile.channel_behavior,
        family_label=family_label,
        event_type=event_type,
        ordinal=ordinal,
        due_at=due_at,
        entity_uid=entity_uid,
        event_id=event_id,
        continuity_key=continuity_key,
        title=title,
        created_global_batch=global_batch,
        canonical_event_name=canonical_event_name,
        week_stage=week_stage,
        channel_timing_mode=channel_timing_mode,
        ics_change_kind=ics_change_kind,
        visible_in_ics_from_batch=visible_in_ics_from_batch,
        hard_case_tags=list(hard_case_tags),
        title_alias_variant=title_alias_variant,
    )


def _apply_primary_change(
    *,
    rng: random.Random,
    profile: CourseProfile,
    phase_profile: PhaseProfile,
    batch: int,
    global_batch: int,
    batch_start: datetime,
    week_stage: WeekStage,
    states: list[_TimelineItemState],
    new_item: _TimelineItemState,
) -> tuple[_EmailSignal, bool]:
    candidates = [
        row
        for row in states
        if row is not new_item and not row.removed and row.visible_in_ics_from_batch <= global_batch and row.due_at >= batch_start + timedelta(days=1)
    ]
    if not candidates:
        candidates = [row for row in states if row is not new_item and not row.removed]
    target = candidates[(global_batch + len(states) + len(profile.course_label)) % len(candidates)]
    previous_due_iso = target.due_at.isoformat()
    change_kind = _primary_change_kind(profile=profile, week_stage=week_stage, target=target, batch=batch, global_batch=global_batch)

    if change_kind == "due_time_shift":
        minutes = 30 if (global_batch + target.ordinal) % 2 == 0 else -45
        target.due_at = target.due_at + timedelta(minutes=minutes)
    elif change_kind == "exam_schedule_change":
        target.due_at = (target.due_at + timedelta(days=2)).replace(hour=18, minute=30)
    else:
        shift_days = 1 if phase_profile.is_summer else 2 if week_stage == "finals_rollover" else 1
        target.due_at = target.due_at + timedelta(days=shift_days)
        if target.event_type == "deadline":
            target.due_at = target.due_at.replace(hour=23, minute=59)
        if target.event_type == "project":
            target.due_at = target.due_at.replace(hour=20, minute=0)

    if (global_batch + target.ordinal + len(profile.course_label)) % 4 == 0:
        target.title_alias_variant = (target.title_alias_variant + 1) % len(profile.aliases[target.event_type])
    target.title = _ics_title(
        profile=profile,
        course=target.course,
        event_type=target.event_type,
        ordinal=target.ordinal,
        alias_variant=target.title_alias_variant,
    )
    target.ics_change_kind = change_kind
    target.channel_timing_mode = _change_channel_mode(profile=profile, batch=batch, global_batch=global_batch, change_kind=change_kind)
    target.week_stage = week_stage

    actor_role = _actor_role_for_change(profile=profile, target=target, batch=batch, global_batch=global_batch)
    needs_professor_confirmation = actor_role == "professor" and (batch + global_batch + target.ordinal) % 3 == 0
    hard_case_tags = _hard_case_tags_for_atomic(
        item=target,
        alias=_gmail_alias(profile=profile, item=target, batch=batch, global_batch=global_batch, kind="atomic_change"),
        kind="atomic_change",
        actor_role=actor_role,
        batch=batch,
        global_batch=global_batch,
    )
    if needs_professor_confirmation:
        hard_case_tags.extend(["ta_pre_notice_then_professor_confirm", "role_authority_conflict"])
    target.hard_case_tags = _dedupe_tags(target.hard_case_tags + list(hard_case_tags))

    return (
        _EmailSignal(
            item=target,
            kind="atomic_change",
            actor_role=actor_role,
            authority_level=_authority_for_role(actor_role),
            channel_timing_mode=target.channel_timing_mode,
            message_intent="confirmation" if needs_professor_confirmation else "authoritative_change",
            junk_profile=_junk_profile_for_role(actor_role, change=True),
            subject_alias=_gmail_alias(profile=profile, item=target, batch=batch, global_batch=global_batch, kind="atomic_change"),
            body_alias=_gmail_alias(profile=profile, item=target, batch=batch + 1, global_batch=global_batch, kind="atomic_change"),
            hard_case_tags=tuple(_dedupe_tags(hard_case_tags)),
            previous_due_iso=previous_due_iso,
            narrative_hint="A TA heads-up circulated first; this message is the course-level confirmation." if needs_professor_confirmation else None,
        ),
        needs_professor_confirmation,
    )


def _apply_extra_ics_realism(
    *,
    rng: random.Random,
    profile: CourseProfile,
    phase_profile: PhaseProfile,
    batch: int,
    global_batch: int,
    batch_start: datetime,
    week_stage: WeekStage,
    states: list[_TimelineItemState],
    exclude_keys: set[str],
) -> None:
    visible = [
        row
        for row in states
        if not row.removed and row.visible_in_ics_from_batch <= global_batch and row.continuity_key not in exclude_keys
    ]
    if not visible:
        return

    due_time_candidate = visible[(batch + global_batch + len(profile.course_label)) % len(visible)]
    if (batch + global_batch + due_time_candidate.ordinal) % 2 == 0:
        due_time_candidate.due_at = due_time_candidate.due_at + timedelta(minutes=30 if week_stage != "finals_rollover" else 60)
        due_time_candidate.ics_change_kind = "due_time_shift"
        due_time_candidate.channel_timing_mode = "calendar_only"
        due_time_candidate.hard_case_tags = _dedupe_tags(due_time_candidate.hard_case_tags + ["calendar_only_due_time_shift"])

    if len(visible) >= 2 and (batch + len(profile.course_label)) % 3 == 0:
        alias_target = visible[(global_batch + due_time_candidate.ordinal) % len(visible)]
        alias_target.title_alias_variant = (alias_target.title_alias_variant + profile.alias_drift_strength) % len(profile.aliases[alias_target.event_type])
        alias_target.title = _ics_title(
            profile=profile,
            course=alias_target.course,
            event_type=alias_target.event_type,
            ordinal=alias_target.ordinal,
            alias_variant=alias_target.title_alias_variant,
        )
        alias_target.ics_change_kind = "title_alias_change"
        alias_target.hard_case_tags = _dedupe_tags(alias_target.hard_case_tags + ["same_item_multi_alias_same_week"])

    removable = [
        row
        for row in visible
        if row.due_at >= batch_start + timedelta(days=2) and row.event_type != "exam"
    ]
    if removable and week_stage in {"late_crunch", "finals_rollover"} and (global_batch + len(profile.course_label)) % (5 if phase_profile.is_summer else 7) == 0:
        row = removable[rng.randrange(len(removable))]
        row.removed = True
        row.ics_change_kind = "removed"
        row.channel_timing_mode = "calendar_only"
        row.hard_case_tags = _dedupe_tags(row.hard_case_tags + ["quarter_rollover_admin_noise"])


def _serialize_ics_event(*, row: _TimelineItemState, phase_label: str) -> TimelineIcsEventPlan:
    return TimelineIcsEventPlan(
        event_id=row.event_id,
        entity_uid=row.entity_uid,
        title=row.title,
        due_iso=row.due_at.isoformat(),
        event_type=row.event_type,
        event_index=row.ordinal,
        course=row.course,
        family_label=row.family_label,
        ordinal=row.ordinal,
        phase_label=phase_label,
        continuity_key=row.continuity_key,
        canonical_event_name=row.canonical_event_name,
        course_archetype=row.course_archetype,
        teaching_style=row.teaching_style,
        channel_behavior=row.channel_behavior,
        week_stage=row.week_stage,
        channel_timing_mode=row.channel_timing_mode,
        ics_change_kind=row.ics_change_kind,
        hard_case_tags=list(row.hard_case_tags),
    )


def _build_new_signal(*, item: _TimelineItemState, batch: int, global_batch: int) -> _EmailSignal:
    profile = COURSE_PROFILES[item.course.label]
    actor_role = _actor_role_for_new(profile=profile, item=item, batch=batch, global_batch=global_batch)
    hard_case_tags = _hard_case_tags_for_atomic(
        item=item,
        alias=_gmail_alias(profile=profile, item=item, batch=batch, global_batch=global_batch, kind="atomic_new"),
        kind="atomic_new",
        actor_role=actor_role,
        batch=batch,
        global_batch=global_batch,
    )
    return _EmailSignal(
        item=item,
        kind="atomic_new",
        actor_role=actor_role,
        authority_level=_authority_for_role(actor_role),
        channel_timing_mode=item.channel_timing_mode,
        message_intent="wrapper_notice" if actor_role == "canvas_wrapper" else "authoritative_new",
        junk_profile=_junk_profile_for_role(actor_role, change=False),
        subject_alias=_gmail_alias(profile=profile, item=item, batch=batch, global_batch=global_batch, kind="atomic_new"),
        body_alias=_gmail_alias(profile=profile, item=item, batch=batch + 1, global_batch=global_batch, kind="atomic_new"),
        hard_case_tags=tuple(_dedupe_tags(hard_case_tags)),
        previous_due_iso=None,
        narrative_hint="Canvas may lag by one sync cycle for the calendar view." if item.channel_timing_mode == "canvas_plus_1_batch" else None,
    )


def _apply_directives_for_batch(
    *,
    phase_label: str,
    phase_profile: PhaseProfile,
    batch: int,
    global_batch: int,
    batch_start: datetime,
    week_stage: WeekStage,
    course_states: dict[str, list[_TimelineItemState]],
    semester: int,
) -> list[TimelineGmailMessagePlan]:
    directives: list[TimelineGmailMessagePlan] = []

    target_course_label = list(course_states)[(global_batch + batch) % len(course_states)]
    profile = COURSE_PROFILES[target_course_label]
    quiz_rows = [row for row in course_states[target_course_label] if not row.removed and row.event_type == "quiz" and row.due_at > batch_start]
    if not quiz_rows:
        quiz_rows = [row for row in course_states[target_course_label] if not row.removed and row.due_at > batch_start]
    if quiz_rows:
        current_weekday = quiz_rows[0].due_at.strftime("%A").lower()
        next_weekday = "friday" if current_weekday != "friday" else "monday"
        for row in quiz_rows:
            row.due_at = _move_to_weekday(row.due_at, next_weekday).replace(hour=23, minute=0)
            row.ics_change_kind = "due_date_shift"
            row.channel_timing_mode = "same_batch"
        anchor = quiz_rows[0]
        alias = profile.aliases[anchor.event_type][1]
        directives.append(
            TimelineGmailMessagePlan(
                message_id="",
                thread_id=f"thread-y{semester:02d}-b{batch:02d}-{anchor.course.label.lower()}-directive-all-matching",
                subject=f"[{anchor.course.label}] Instructor policy: future {alias.lower()}s move to {next_weekday.title()}",
                body_text=_directive_body(
                    profile=profile,
                    phase_label=phase_label,
                    week_stage=week_stage,
                    alias=alias,
                    current_weekday=current_weekday,
                    move_weekday=next_weekday,
                    set_due_date=None,
                    selector_ordinals=[],
                    anchor_due_iso=anchor.due_at.isoformat(),
                ),
                from_header=_from_header_for_role(role="professor", profile=profile, course=anchor.course),
                label_ids=["INBOX", "CATEGORY_UPDATES"],
                internal_date=_directive_message_time(batch_start=batch_start, timing_mode="same_batch", slot=6).isoformat(),
                due_iso=anchor.due_at.isoformat(),
                event_type=anchor.event_type,
                event_index=anchor.ordinal,
                history_batch=batch,
                history_global_batch=global_batch,
                course=anchor.course,
                family_label=anchor.family_label,
                ordinal=anchor.ordinal,
                message_kind="directive",
                continuity_key=anchor.continuity_key,
                expected_link_outcome="none",
                canonical_event_name=anchor.canonical_event_name,
                selector_ordinals=[],
                directive_scope_mode="all_matching",
                current_due_weekday=current_weekday,
                move_weekday=next_weekday,
                set_due_date=None,
                hard_case_tags=["future_matching_directive", "all_matching"],
                actor_role="professor",
                authority_level="high",
                channel_timing_mode="same_batch",
                message_intent="policy_change",
                junk_profile="formal_explanation",
                course_archetype=profile.course_archetype,
                teaching_style=profile.teaching_style,
                channel_behavior=profile.channel_behavior,
                week_stage=week_stage,
            )
        )

    range_course_label = list(course_states)[(global_batch + batch + 1) % len(course_states)]
    range_profile = COURSE_PROFILES[range_course_label]
    directive_rows = [
        row
        for row in course_states[range_course_label]
        if not row.removed and row.event_type in {"deadline", "project"} and row.due_at > batch_start
    ]
    if len(directive_rows) < 2:
        directive_rows = [row for row in course_states[range_course_label] if not row.removed and row.event_type != "exam" and row.due_at > batch_start]
    selector_rows = _directive_selector_pool(directive_rows)
    if len(selector_rows) >= 2:
        selector_rows = selector_rows[:3] if len(selector_rows) >= 3 and batch % 3 != 0 else selector_rows[:2]
        target_date = (batch_start + timedelta(days=18 + (batch % 4) - phase_profile.compression_days)).date().isoformat()
        for row in selector_rows:
            row.due_at = row.due_at.replace(
                year=int(target_date[:4]),
                month=int(target_date[5:7]),
                day=int(target_date[8:10]),
                hour=23,
                minute=59,
            )
            row.ics_change_kind = "due_date_shift"
        anchor = selector_rows[0]
        alias = range_profile.aliases[anchor.event_type][-1]
        selector_ordinals = [row.ordinal for row in selector_rows]
        scope_mode = "ordinal_range" if len(selector_ordinals) >= 3 else "ordinal_list"
        range_text = f"{selector_ordinals[0]}-{selector_ordinals[-1]}" if scope_mode == "ordinal_range" else ", ".join(str(value) for value in selector_ordinals)
        directives.append(
            TimelineGmailMessagePlan(
                message_id="",
                thread_id=f"thread-y{semester:02d}-b{batch:02d}-{anchor.course.label.lower()}-directive-range",
                subject=f"[{anchor.course.label}] {alias} {range_text} now due {target_date}",
                body_text=_directive_body(
                    profile=range_profile,
                    phase_label=phase_label,
                    week_stage=week_stage,
                    alias=alias,
                    current_weekday=None,
                    move_weekday=None,
                    set_due_date=target_date,
                    selector_ordinals=selector_ordinals,
                    anchor_due_iso=anchor.due_at.isoformat(),
                ),
                from_header=_from_header_for_role(role="course_staff_alias", profile=range_profile, course=anchor.course),
                label_ids=["INBOX", "CATEGORY_UPDATES"],
                internal_date=_directive_message_time(batch_start=batch_start, timing_mode="same_batch", slot=7).isoformat(),
                due_iso=anchor.due_at.isoformat(),
                event_type=anchor.event_type,
                event_index=anchor.ordinal,
                history_batch=batch,
                history_global_batch=global_batch,
                course=anchor.course,
                family_label=anchor.family_label,
                ordinal=anchor.ordinal,
                message_kind="directive",
                continuity_key=anchor.continuity_key,
                expected_link_outcome="none",
                canonical_event_name=anchor.canonical_event_name,
                selector_ordinals=selector_ordinals,
                directive_scope_mode=scope_mode,
                current_due_weekday=None,
                move_weekday=None,
                set_due_date=target_date,
                hard_case_tags=[scope_mode, "directive_set_due_date"],
                actor_role="course_staff_alias",
                authority_level="medium",
                channel_timing_mode="same_batch",
                message_intent="policy_change",
                junk_profile="alias_broadcast",
                course_archetype=range_profile.course_archetype,
                teaching_style=range_profile.teaching_style,
                channel_behavior=range_profile.channel_behavior,
                week_stage=week_stage,
            )
        )
    if len(directives) < 2:
        fallback_rows = [
            row
            for rows in course_states.values()
            for row in rows
            if not row.removed and row.event_type != "exam" and row.due_at > batch_start
        ]
        selector_rows = _directive_selector_pool(fallback_rows)
        if len(selector_rows) >= 2:
            selector_rows = selector_rows[:2]
            anchor = selector_rows[0]
            anchor_profile = COURSE_PROFILES[anchor.course.label]
            selector_ordinals = [row.ordinal for row in selector_rows]
            target_date = (batch_start + timedelta(days=16 - phase_profile.compression_days)).date().isoformat()
            for row in selector_rows:
                row.due_at = row.due_at.replace(
                    year=int(target_date[:4]),
                    month=int(target_date[5:7]),
                    day=int(target_date[8:10]),
                    hour=23,
                    minute=59,
                )
                row.ics_change_kind = "due_date_shift"
            directives.append(
                TimelineGmailMessagePlan(
                    message_id="",
                    thread_id=f"thread-y{semester:02d}-b{batch:02d}-{anchor.course.label.lower()}-directive-fallback",
                    subject=f"[{anchor.course.label}] {anchor_profile.aliases[anchor.event_type][0]} {selector_ordinals[0]}, {selector_ordinals[1]} now due {target_date}",
                    body_text=_directive_body(
                        profile=anchor_profile,
                        phase_label=phase_label,
                        week_stage=week_stage,
                        alias=anchor_profile.aliases[anchor.event_type][0],
                        current_weekday=None,
                        move_weekday=None,
                        set_due_date=target_date,
                        selector_ordinals=selector_ordinals,
                        anchor_due_iso=anchor.due_at.isoformat(),
                    ),
                    from_header=_from_header_for_role(role="course_staff_alias", profile=anchor_profile, course=anchor.course),
                    label_ids=["INBOX", "CATEGORY_UPDATES"],
                    internal_date=_directive_message_time(batch_start=batch_start, timing_mode="same_batch", slot=7).isoformat(),
                    due_iso=anchor.due_at.isoformat(),
                    event_type=anchor.event_type,
                    event_index=anchor.ordinal,
                    history_batch=batch,
                    history_global_batch=global_batch,
                    course=anchor.course,
                    family_label=anchor.family_label,
                    ordinal=anchor.ordinal,
                    message_kind="directive",
                    continuity_key=anchor.continuity_key,
                    expected_link_outcome="none",
                    canonical_event_name=anchor.canonical_event_name,
                    selector_ordinals=selector_ordinals,
                    directive_scope_mode="ordinal_list",
                    current_due_weekday=None,
                    move_weekday=None,
                    set_due_date=target_date,
                    hard_case_tags=["ordinal_list", "directive_set_due_date"],
                    actor_role="course_staff_alias",
                    authority_level="medium",
                    channel_timing_mode="same_batch",
                    message_intent="policy_change",
                    junk_profile="alias_broadcast",
                    course_archetype=anchor_profile.course_archetype,
                    teaching_style=anchor_profile.teaching_style,
                    channel_behavior=anchor_profile.channel_behavior,
                    week_stage=week_stage,
                )
            )
    return directives[:2]


def _build_reminder_messages(
    *,
    rng: random.Random,
    semester: int,
    phase_label: str,
    batch: int,
    global_batch: int,
    batch_start: datetime,
    week_stage: WeekStage,
    selected_items: list[_TimelineItemState],
    professor_confirmation_items: list[_TimelineItemState],
) -> list[TimelineGmailMessagePlan]:
    reminders: list[TimelineGmailMessagePlan] = []

    if professor_confirmation_items:
        item = professor_confirmation_items[0]
        profile = COURSE_PROFILES[item.course.label]
        reminders.append(
            TimelineGmailMessagePlan(
                message_id="",
                thread_id=f"thread-y{semester:02d}-b{batch:02d}-{item.course.label.lower()}-ta-prenotice-{item.ordinal}",
                subject=f"[{item.course.label}] quick heads-up on {profile.aliases[item.event_type][0]} {item.ordinal}",
                body_text=(
                    f"Course: {item.course.label}\n"
                    f"Phase: {phase_label}\n"
                    "Posting a heads-up before section.\n"
                    "The instructor is still finalizing the timing language, so please keep using the currently posted Canvas deadline for now.\n"
                    "Office hours, rubric bullets, and submission instructions remain unchanged.\n"
                    "If anything moves, the professor note will be the authoritative update."
                ),
                from_header=_from_header_for_role(role="ta", profile=profile, course=item.course),
                label_ids=["INBOX", "CATEGORY_UPDATES"],
                internal_date=_noise_message_time(batch_start=batch_start, slot=10).isoformat(),
                due_iso=item.due_at.isoformat(),
                event_type=item.event_type,
                event_index=item.ordinal,
                history_batch=batch,
                history_global_batch=global_batch,
                course=item.course,
                family_label=item.family_label,
                ordinal=item.ordinal,
                message_kind="reminder_noise",
                continuity_key=item.continuity_key,
                expected_link_outcome="none",
                canonical_event_name=item.canonical_event_name,
                hard_case_tags=["ta_pre_notice_then_professor_confirm", "role_authority_conflict"],
                actor_role="ta",
                authority_level="low",
                channel_timing_mode="email_first",
                message_intent="pre_notice",
                junk_profile="ops_short",
                course_archetype=profile.course_archetype,
                teaching_style=profile.teaching_style,
                channel_behavior=profile.channel_behavior,
                week_stage=week_stage,
            )
        )

    reminder_slots = [11, 12]
    seen_keys = {row.continuity_key for row in reminders if row.continuity_key}
    for slot in reminder_slots:
        reminder_item = selected_items[(global_batch + batch + slot + rng.randint(0, 2)) % len(selected_items)]
        if reminder_item.continuity_key in seen_keys and len(selected_items) > 1:
            reminder_item = selected_items[(global_batch + batch + slot + 1) % len(selected_items)]
        seen_keys.add(reminder_item.continuity_key)
        reminder_profile = COURSE_PROFILES[reminder_item.course.label]
        reminders.append(
            TimelineGmailMessagePlan(
                message_id="",
                thread_id=f"thread-y{semester:02d}-b{batch:02d}-{reminder_item.course.label.lower()}-reminder-{reminder_item.ordinal}-{slot}",
                subject=f"[{reminder_item.course.label}] reminder: {reminder_profile.aliases[reminder_item.event_type][0]} {reminder_item.ordinal}",
                body_text=(
                    f"Course: {reminder_item.course.label}\n"
                    f"Phase: {phase_label}\n"
                    "Reminder only: the graded item itself is unchanged.\n"
                    f"The currently posted deadline remains {reminder_item.due_at.isoformat()}.\n"
                    "Please read the submission instructions, office-hours note, and FAQ before emailing staff.\n"
                    "No new change is introduced here."
                ),
                from_header=_from_header_for_role(role="ta", profile=reminder_profile, course=reminder_item.course),
                label_ids=["INBOX", "CATEGORY_UPDATES"],
                internal_date=_noise_message_time(batch_start=batch_start, slot=slot).isoformat(),
                due_iso=reminder_item.due_at.isoformat(),
                event_type=reminder_item.event_type,
                event_index=reminder_item.ordinal,
                history_batch=batch,
                history_global_batch=global_batch,
                course=reminder_item.course,
                family_label=reminder_item.family_label,
                ordinal=reminder_item.ordinal,
                message_kind="reminder_noise",
                continuity_key=reminder_item.continuity_key,
                expected_link_outcome="none",
                canonical_event_name=reminder_item.canonical_event_name,
                actor_role="ta",
                authority_level="low",
                channel_timing_mode="same_batch",
                message_intent="reminder",
                junk_profile="faq_digest",
                course_archetype=reminder_profile.course_archetype,
                teaching_style=reminder_profile.teaching_style,
                channel_behavior=reminder_profile.channel_behavior,
                week_stage=week_stage,
            )
        )
    return reminders[:2]


def _build_lab_noise_message(
    *,
    semester: int,
    phase_label: str,
    batch: int,
    global_batch: int,
    batch_start: datetime,
    week_stage: WeekStage,
    course_label: str,
) -> TimelineGmailMessagePlan:
    profile = COURSE_PROFILES[course_label]
    course = _parse_course_label(course_label)
    return TimelineGmailMessagePlan(
        message_id="",
        thread_id=f"thread-y{semester:02d}-b{batch:02d}-{course.label.lower()}-lab-noise",
        subject=f"[{course.label}] lab sections, room notes, and staffing for this week",
        body_text=(
            f"Course: {course.label}\n"
            f"Phase: {phase_label}\n"
            "Lab logistics only.\n"
            "Please check section staffing, room/Zoom logistics, PPE reminders, and checkoff routing below.\n"
            "Rubric expectations, late policy, and submission windows are unchanged.\n"
            "This message should not be treated as a graded deadline change."
        ),
        from_header=_from_header_for_role(role="lab_coordinator", profile=profile, course=course),
        label_ids=["INBOX", "CATEGORY_UPDATES"],
        internal_date=_noise_message_time(batch_start=batch_start, slot=8).isoformat(),
        due_iso=(batch_start + timedelta(hours=16)).isoformat(),
        event_type="deadline",
        event_index=0,
        history_batch=batch,
        history_global_batch=global_batch,
        course=course,
        family_label="Lab Logistics",
        ordinal=0,
        message_kind="lab_noise",
        continuity_key=None,
        expected_link_outcome="none",
        canonical_event_name=None,
        actor_role="lab_coordinator",
        authority_level="medium",
        channel_timing_mode="same_batch",
        message_intent="lab_logistics",
        junk_profile="lab_logistics",
        course_archetype=profile.course_archetype,
        teaching_style=profile.teaching_style,
        channel_behavior=profile.channel_behavior,
        week_stage=week_stage,
    )


def _build_admin_noise_message(
    *,
    semester: int,
    phase_label: str,
    batch: int,
    global_batch: int,
    batch_start: datetime,
    week_stage: WeekStage,
    course_label: str,
) -> TimelineGmailMessagePlan:
    profile = COURSE_PROFILES[course_label]
    course = _parse_course_label(course_label)
    hard_tags = ["quarter_rollover_admin_noise"] if week_stage == "finals_rollover" else []
    return TimelineGmailMessagePlan(
        message_id="",
        thread_id=f"thread-y{semester:02d}-b{batch:02d}-{course.label.lower()}-admin-noise",
        subject=f"[{course.label}] registrar and end-of-term admin notes",
        body_text=(
            f"Course: {course.label}\n"
            f"Phase: {phase_label}\n"
            "Administrative note only.\n"
            "This email collects mailing footer text, exam seating logistics, roster cleanup, accommodation routing, and portal reminders.\n"
            "No graded due date is created or modified here.\n"
            + ("Quarter rollover processing is still happening; expect noisy reminders from multiple campus systems.\n" if week_stage == "finals_rollover" else "")
            + "Students should ignore this for deadline tracking."
        ),
        from_header=_from_header_for_role(role="department_admin", profile=profile, course=course),
        label_ids=["INBOX", "CATEGORY_UPDATES"],
        internal_date=_noise_message_time(batch_start=batch_start, slot=9).isoformat(),
        due_iso=(batch_start + timedelta(hours=17)).isoformat(),
        event_type="deadline",
        event_index=0,
        history_batch=batch,
        history_global_batch=global_batch,
        course=course,
        family_label="Admin Update",
        ordinal=0,
        message_kind="admin_noise",
        continuity_key=None,
        expected_link_outcome="none",
        canonical_event_name=None,
        hard_case_tags=hard_tags,
        actor_role="department_admin",
        authority_level="medium",
        channel_timing_mode="same_batch",
        message_intent="admin_rollover",
        junk_profile="department_bureaucracy",
        course_archetype=profile.course_archetype,
        teaching_style=profile.teaching_style,
        channel_behavior=profile.channel_behavior,
        week_stage=week_stage,
    )


def _realize_atomic_message(
    *,
    signal: _EmailSignal,
    semester: int,
    phase_label: str,
    batch: int,
    global_batch: int,
    batch_start: datetime,
    week_stage: WeekStage,
    slot: int,
) -> TimelineGmailMessagePlan:
    profile = COURSE_PROFILES[signal.item.course.label]
    subject = _signal_subject(
        signal=signal,
        profile=profile,
    )
    message_time = _signal_message_time(batch_start=batch_start, timing_mode=signal.channel_timing_mode, slot=slot)
    body_text = _signal_body(
        signal=signal,
        profile=profile,
        phase_label=phase_label,
        week_stage=week_stage,
        internal_date_iso=message_time.isoformat(),
    )
    return TimelineGmailMessagePlan(
        message_id=f"y{semester:02d}-b{batch:02d}-gmail-{slot:03d}",
        thread_id=f"thread-y{semester:02d}-b{batch:02d}-{signal.item.course.label.lower()}-{signal.kind}-{signal.item.ordinal}",
        subject=subject,
        body_text=body_text,
        from_header=_from_header_for_role(role=signal.actor_role, profile=profile, course=signal.item.course),
        label_ids=["INBOX", "CATEGORY_UPDATES"],
        internal_date=message_time.isoformat(),
        due_iso=signal.item.due_at.isoformat(),
        event_type=signal.item.event_type,
        event_index=signal.item.ordinal,
        history_batch=batch,
        history_global_batch=global_batch,
        course=signal.item.course,
        family_label=signal.item.family_label,
        ordinal=signal.item.ordinal,
        message_kind=signal.kind,
        continuity_key=signal.item.continuity_key,
        expected_link_outcome="auto_link",
        canonical_event_name=signal.item.canonical_event_name,
        previous_due_iso=signal.previous_due_iso,
        hard_case_tags=list(signal.hard_case_tags),
        actor_role=signal.actor_role,
        authority_level=signal.authority_level,
        channel_timing_mode=signal.channel_timing_mode,
        message_intent=signal.message_intent,
        junk_profile=signal.junk_profile,
        course_archetype=signal.item.course_archetype,
        teaching_style=signal.item.teaching_style,
        channel_behavior=signal.item.channel_behavior,
        week_stage=week_stage,
    )


def _signal_subject(*, signal: _EmailSignal, profile: CourseProfile) -> str:
    alias = signal.subject_alias
    ordinal = signal.item.ordinal
    course = signal.item.course
    if signal.actor_role == "canvas_wrapper":
        action = "Assignment created" if signal.kind == "atomic_new" else "Assignment updated"
        return f"Canvas Notification - {course.label}: {action} for {alias} {ordinal}"
    if signal.actor_role == "professor":
        if signal.kind == "atomic_new":
            return f"[{course.label}] instructor note: {alias} {ordinal} is now on the quarter calendar"
        return f"[{course.label}] instructor update: {alias} {ordinal} timing confirmed"
    if signal.actor_role == "ta":
        return f"[{course.label}] quick note on {alias} {ordinal}"
    if signal.kind == "atomic_new":
        return f"[{course.label}] {alias} {ordinal} posted"
    return f"[{course.label}] {alias} {ordinal} due date updated"


def _signal_body(
    *,
    signal: _EmailSignal,
    profile: CourseProfile,
    phase_label: str,
    week_stage: WeekStage,
    internal_date_iso: str,
) -> str:
    item = signal.item
    due_phrase = _due_phrase_for_signal(
        due_iso=item.due_at.isoformat(),
        internal_date_iso=internal_date_iso,
        hard_case_tags=list(signal.hard_case_tags),
    )
    previous_due_phrase = _human_due_phrase(signal.previous_due_iso) if signal.previous_due_iso else None
    signal_line = _signal_line(signal=signal, due_phrase=due_phrase, previous_due_phrase=previous_due_phrase)
    extras = []
    if "single_item_all_sections" in signal.hard_case_tags:
        extras.append("This applies to every enrolled section, but it still refers to one graded item.")
    if "same_item_multi_alias_same_week" in signal.hard_case_tags:
        extras.append(
            f"{signal.body_alias} {item.ordinal}, {profile.aliases[item.event_type][0]} {item.ordinal}, and {signal.subject_alias} {item.ordinal} all refer to the same deliverable."
        )
    if "email_only_pre_announcement" in signal.hard_case_tags:
        extras.append("Canvas calendar sync may lag until the next batch, so email is the first signal here.")
    if signal.channel_timing_mode in {"canvas_first", "email_plus_1_batch"}:
        extras.append("Canvas already carries the structured inventory update; this email adds rationale and audience guidance.")
    if signal.narrative_hint:
        extras.append(signal.narrative_hint)

    pre, mid, post = _junk_blocks_for_signal(
        role=signal.actor_role,
        junk_profile=signal.junk_profile,
        profile=profile,
        item=item,
        week_stage=week_stage,
    )
    parts = [
        f"Course: {item.course.label}\n",
        f"Phase: {phase_label}\n",
        pre,
        "\n",
        signal_line,
        "\n",
        mid,
    ]
    for extra in extras:
        parts.extend(["\n", extra])
    parts.extend(["\n", post])
    return "".join(parts).strip()


def _signal_line(*, signal: _EmailSignal, due_phrase: str, previous_due_phrase: str | None) -> str:
    alias = signal.body_alias
    ordinal = signal.item.ordinal
    if signal.kind == "atomic_new":
        return f"The current graded item signal is: {alias} {ordinal} is posted, and the working due time is {due_phrase}."
    previous_line = f" The previous posted time was {previous_due_phrase}." if previous_due_phrase else ""
    return f"The current graded item signal is: {alias} {ordinal} now lands at {due_phrase}.{previous_line}"


def _directive_body(
    *,
    profile: CourseProfile,
    phase_label: str,
    week_stage: WeekStage,
    alias: str,
    current_weekday: str | None,
    move_weekday: str | None,
    set_due_date: str | None,
    selector_ordinals: list[int],
    anchor_due_iso: str,
) -> str:
    junk = (
        "Please ignore the LMS wrapper text below unless you need submission instructions, FAQ routing, or office-hours reminders.\n"
        "Rubric wording and grade weights are unchanged.\n"
    )
    if set_due_date:
        ordinal_phrase = f"{selector_ordinals[0]}-{selector_ordinals[-1]}" if len(selector_ordinals) >= 3 else ", ".join(str(value) for value in selector_ordinals)
        signal = f"{alias} {ordinal_phrase} are now due on {set_due_date}."
    else:
        signal = f"All future {alias.lower()}s currently landing on {current_weekday} now move to {move_weekday}."
    return (
        f"Course: {profile.course_label}\n"
        f"Phase: {phase_label}\n"
        f"Week stage: {week_stage}\n"
        f"{junk}"
        f"{signal}\n"
        f"Use {anchor_due_iso} as the first authoritative anchor when reconciling existing items.\n"
        "This is a directive affecting multiple existing graded items."
    )


def _junk_blocks_for_signal(
    *,
    role: ActorRole,
    junk_profile: JunkProfile,
    profile: CourseProfile,
    item: _TimelineItemState,
    week_stage: WeekStage,
) -> tuple[str, str, str]:
    if role == "professor":
        return (
            "Thanks for the patience while we aligned grading capacity, room availability, and the Canvas calendar.\n"
            "The policy below is the version we will hold students to.",
            "Submission instructions, rubric rows, and office-hours details stay as already posted.\n"
            "Please do not infer any extra-credit change from this note.",
            f"Best,\n{profile.staff.professor_name}",
        )
    if role == "ta":
        return (
            "Short operational heads-up before lab.\n"
            "I am repeating the staff guidance so nobody misses it in the queue.",
            "The FAQ, troubleshooting checklist, and section logistics are unchanged.\n"
            "If the instructor posts a policy correction, that version wins.",
            f"Thanks,\n{profile.staff.ta_names[0]}",
        )
    if role == "canvas_wrapper":
        return (
            "You can reply to this notification from Inbox.\n"
            "This message was sent because content in Canvas changed.\n"
            "View the item in your browser to see comments, rubric rows, and submission details.",
            "Course summary, gradebook links, office-hours cards, and submission help text may appear above or below the timing line.\n"
            "Only the explicit assignment timing sentence should be treated as the signal.",
            "Canvas Notification Center",
        )
    if role == "course_staff_alias":
        return (
            "Operational announcement from the course alias.\n"
            "Please read the timing line and not the mailing footer as the actionable part.",
            "Section staffing, FAQ entries, and autograder instructions are included for convenience.\n"
            "Grade weights and rubric points are unchanged.",
            profile.staff.course_alias_name,
        )
    return (
        "Administrative wrapper text.",
        "No new grading policy is implied here.",
        "CalendarDIFF synthetic generator",
    )


def _new_item_channel_mode(*, profile: CourseProfile, batch: int, global_batch: int) -> ChannelTimingMode:
    if profile.channel_behavior == "canvas_plus_1_batch" and batch not in {12}:
        return "canvas_plus_1_batch" if global_batch % 2 == 0 else "email_first"
    if profile.channel_behavior == "email_first":
        return "email_first"
    if profile.channel_behavior == "canvas_first":
        return "canvas_first"
    if profile.channel_behavior == "email_plus_1_batch":
        return "canvas_first"
    return "same_batch"


def _change_channel_mode(
    *,
    profile: CourseProfile,
    batch: int,
    global_batch: int,
    change_kind: IcsChangeKind,
) -> ChannelTimingMode:
    if change_kind == "due_time_shift":
        return "calendar_only"
    if profile.channel_behavior == "email_plus_1_batch":
        return "email_plus_1_batch"
    if profile.channel_behavior == "canvas_first":
        return "canvas_first"
    if profile.channel_behavior == "email_first":
        return "email_first"
    if profile.channel_behavior == "canvas_plus_1_batch":
        return "same_batch" if batch % 3 else "email_first"
    return "same_batch"


def _actor_role_for_new(*, profile: CourseProfile, item: _TimelineItemState, batch: int, global_batch: int) -> ActorRole:
    if profile.teaching_style == "strict_canvas" or (profile.channel_behavior == "canvas_first" and (batch + item.ordinal) % 2 == 0):
        return "canvas_wrapper"
    if item.event_type in {"project", "exam"} and (batch + global_batch) % 4 == 0:
        return "professor"
    if profile.teaching_style == "ta_reminder_heavy" and (batch + item.ordinal) % 3 == 0:
        return "ta"
    return "course_staff_alias"


def _actor_role_for_change(*, profile: CourseProfile, target: _TimelineItemState, batch: int, global_batch: int) -> ActorRole:
    if target.event_type in {"exam", "project"} or weeklike(batch=batch):
        return "professor" if (batch + global_batch + target.ordinal) % 2 == 0 else "course_staff_alias"
    if profile.teaching_style == "strict_canvas" and target.event_type == "deadline":
        return "canvas_wrapper"
    if profile.teaching_style == "ta_reminder_heavy" and (batch + target.ordinal) % 2 == 1:
        return "professor"
    return "course_staff_alias"


def weeklike(*, batch: int) -> bool:
    return batch in {4, 5, 9, 10, 11}


def _authority_for_role(role: ActorRole) -> AuthorityLevel:
    if role == "professor":
        return "high"
    if role == "canvas_wrapper":
        return "system"
    if role in {"course_staff_alias", "lab_coordinator", "department_admin"}:
        return "medium"
    return "low"


def _junk_profile_for_role(role: ActorRole, *, change: bool) -> JunkProfile:
    if role == "professor":
        return "formal_explanation"
    if role == "ta":
        return "ops_short"
    if role == "canvas_wrapper":
        return "lms_wrapper"
    if role == "course_staff_alias":
        return "alias_broadcast" if change else "project_checklist"
    return "faq_digest"


def _from_header_for_role(*, role: ActorRole, profile: CourseProfile, course: CourseAnchor) -> str:
    suffix = course.suffix.lower() if course.suffix is not None else ""
    alias_prefix = f"{course.dept.lower()}{course.number}{suffix}"
    if role == "professor":
        local = profile.staff.professor_name.lower().replace("prof. ", "").replace(" ", ".")
        return f"{profile.staff.professor_name} <{local}@faculty.example.edu>"
    if role == "ta":
        name = profile.staff.ta_names[0]
        local = name.lower().replace(" ", ".")
        return f"{name} <{local}@ta.example.edu>"
    if role == "course_staff_alias":
        return f"{profile.staff.course_alias_name} <{alias_prefix}-staff@courses.example.edu>"
    if role == "canvas_wrapper":
        return f"Canvas Notifications <notifications@canvas.example.edu>"
    if role == "lab_coordinator":
        local = profile.staff.lab_coordinator_name.lower().replace(" ", "-")
        return f"{profile.staff.lab_coordinator_name} <{local}@ops.example.edu>"
    local = profile.staff.department_admin_name.lower().replace(" ", "-")
    return f"{profile.staff.department_admin_name} <{local}@admin.example.edu>"


def _signal_message_time(*, batch_start: datetime, timing_mode: ChannelTimingMode, slot: int) -> datetime:
    if timing_mode in {"email_first", "canvas_plus_1_batch"}:
        return batch_start + timedelta(hours=8, minutes=slot * 7)
    if timing_mode in {"canvas_first", "email_plus_1_batch"}:
        return batch_start + timedelta(hours=15, minutes=slot * 5)
    if timing_mode == "calendar_only":
        return batch_start + timedelta(hours=16, minutes=slot * 3)
    return batch_start + timedelta(hours=11, minutes=slot * 6)


def _directive_message_time(*, batch_start: datetime, timing_mode: ChannelTimingMode, slot: int) -> datetime:
    return _signal_message_time(batch_start=batch_start, timing_mode=timing_mode, slot=slot)


def _noise_message_time(*, batch_start: datetime, slot: int) -> datetime:
    return batch_start + timedelta(hours=9 + slot, minutes=(slot * 11) % 40)


def _renumber_message(*, message: TimelineGmailMessagePlan, semester: int, batch: int, slot: int) -> TimelineGmailMessagePlan:
    return replace(
        message,
        message_id=f"y{semester:02d}-b{batch:02d}-gmail-{slot:03d}",
    )


def _event_type_for_context(
    *,
    profile: CourseProfile,
    phase_profile: PhaseProfile,
    week_stage: WeekStage,
    selector: int,
) -> EventType:
    stage_pool: dict[CourseArchetype, dict[WeekStage, tuple[EventType, ...]]] = {
        "programming_systems": {
            "setup_release": ("deadline", "project"),
            "early_ramp": ("deadline", "quiz", "deadline"),
            "first_pressure": ("quiz", "deadline", "exam"),
            "project_push": ("project", "quiz", "deadline"),
            "late_crunch": ("project", "deadline", "quiz"),
            "finals_rollover": ("project", "exam", "deadline"),
        },
        "math_problem_set": {
            "setup_release": ("deadline",),
            "early_ramp": ("deadline", "quiz"),
            "first_pressure": ("deadline", "quiz", "exam"),
            "project_push": ("deadline", "quiz"),
            "late_crunch": ("deadline", "exam"),
            "finals_rollover": ("exam", "deadline"),
        },
        "project_heavy_ml": {
            "setup_release": ("project", "deadline"),
            "early_ramp": ("deadline", "project"),
            "first_pressure": ("project", "quiz"),
            "project_push": ("project", "project", "quiz"),
            "late_crunch": ("project", "deadline"),
            "finals_rollover": ("project", "exam"),
        },
        "lab_report_science": {
            "setup_release": ("deadline", "quiz"),
            "early_ramp": ("deadline", "quiz"),
            "first_pressure": ("quiz", "exam"),
            "project_push": ("project", "deadline"),
            "late_crunch": ("project", "quiz"),
            "finals_rollover": ("exam", "project"),
        },
        "discussion_reading": {
            "setup_release": ("deadline",),
            "early_ramp": ("quiz", "deadline"),
            "first_pressure": ("quiz", "deadline"),
            "project_push": ("project", "quiz"),
            "late_crunch": ("deadline", "project"),
            "finals_rollover": ("exam", "project"),
        },
    }
    pool = list(stage_pool[profile.course_archetype][week_stage])
    if phase_profile.is_summer and week_stage in {"early_ramp", "project_push"}:
        pool = pool + ["project"]
    return pool[selector % len(pool)]


def _lead_days_for_item(
    *,
    profile: CourseProfile,
    phase_profile: PhaseProfile,
    week_stage: WeekStage,
    event_type: EventType,
    ordinal_seed: int,
    prefill: bool,
) -> int:
    base_by_stage = {
        "setup_release": 9,
        "early_ramp": 8,
        "first_pressure": 6,
        "project_push": 7,
        "late_crunch": 5,
        "finals_rollover": 4,
    }[week_stage]
    event_adjust = {"deadline": 0, "quiz": -1, "project": 3, "exam": 5}[event_type]
    compression = -phase_profile.compression_days
    prefill_bonus = -2 if prefill else 0
    archetype_adjust = 1 if profile.course_archetype == "project_heavy_ml" and event_type == "project" else 0
    return max(2, base_by_stage + event_adjust + compression + prefill_bonus + ((ordinal_seed + profile.alias_drift_strength) % 3) + archetype_adjust)


def _due_at_for_new_item(
    *,
    batch_start: datetime,
    phase_profile: PhaseProfile,
    event_type: EventType,
    lead_days: int,
    ordinal: int,
    course_number: int,
) -> datetime:
    due_at = batch_start + timedelta(days=lead_days)
    hour_map = {
        "deadline": 23,
        "quiz": 17 if course_number % 2 == 0 else 19,
        "project": 20,
        "exam": 18,
    }
    minute_map = {
        "deadline": 59,
        "quiz": 0 if ordinal % 2 == 0 else 30,
        "project": 0,
        "exam": 30,
    }
    if phase_profile.is_summer and event_type in {"quiz", "project"}:
        due_at = due_at - timedelta(days=1)
    return due_at.replace(hour=hour_map[event_type], minute=minute_map[event_type])


def _primary_change_kind(
    *,
    profile: CourseProfile,
    week_stage: WeekStage,
    target: _TimelineItemState,
    batch: int,
    global_batch: int,
) -> IcsChangeKind:
    if target.event_type == "exam" or week_stage == "finals_rollover":
        return "exam_schedule_change"
    if (batch + global_batch + target.ordinal + len(profile.course_label)) % 4 == 0:
        return "due_time_shift"
    return "due_date_shift"


def _ics_title(*, profile: CourseProfile, course: CourseAnchor, event_type: EventType, ordinal: int, alias_variant: int) -> str:
    aliases = profile.aliases[event_type]
    label = aliases[alias_variant % len(aliases)]
    return f"{course.label} {label} {ordinal}"


def _gmail_alias(*, profile: CourseProfile, item: _TimelineItemState, batch: int, global_batch: int, kind: MessageKind) -> str:
    aliases = profile.aliases[item.event_type]
    if kind == "directive":
        return aliases[min(1, len(aliases) - 1)]
    if item.course_archetype == "math_problem_set" and kind == "atomic_change":
        return aliases[(batch + item.ordinal) % len(aliases)]
    return aliases[(batch + global_batch + item.ordinal + item.title_alias_variant) % len(aliases)]


def _hard_case_tags_for_atomic(
    *,
    item: _TimelineItemState,
    alias: str,
    kind: Literal["atomic_new", "atomic_change"],
    actor_role: ActorRole,
    batch: int,
    global_batch: int,
) -> list[str]:
    tags: list[str] = []
    if (batch + item.ordinal) % 4 == 0:
        tags.append("single_item_all_sections")
    if (global_batch + item.ordinal) % 3 == 0:
        tags.append("relative_time_phrase")
    else:
        tags.append("absolute_human_phrase")
    if item.course.suffix is not None:
        tags.append("suffix_sensitive")
    alias_lower = alias.lower()
    if alias_lower.startswith("hw"):
        tags.append("alias_hw")
    if "problem set" in alias_lower:
        tags.append("alias_problem_set")
    if actor_role == "canvas_wrapper":
        tags.append("canvas_wrapper_with_signal_buried")
    if kind == "atomic_new" and item.channel_timing_mode == "canvas_plus_1_batch":
        tags.append("email_only_pre_announcement")
    if item.course_archetype in {"project_heavy_ml", "discussion_reading"} and (batch + global_batch + item.ordinal) % 4 == 1:
        tags.append("same_item_multi_alias_same_week")
    return _dedupe_tags(tags)


def _directive_selector_pool(rows: list[_TimelineItemState]) -> list[_TimelineItemState]:
    grouped: dict[tuple[str, str, str], list[_TimelineItemState]] = {}
    for row in sorted(rows, key=lambda item: (item.family_label, item.ordinal, item.event_type)):
        grouped.setdefault((row.course.label, row.family_label, row.event_type), []).append(row)

    candidate_groups: list[list[_TimelineItemState]] = []
    for group in grouped.values():
        unique_rows: list[_TimelineItemState] = []
        seen_ordinals: set[int] = set()
        for row in group:
            if row.ordinal in seen_ordinals:
                continue
            seen_ordinals.add(row.ordinal)
            unique_rows.append(row)
        if len(unique_rows) >= 2:
            candidate_groups.append(unique_rows)

    if candidate_groups:
        candidate_groups.sort(key=lambda group: (-len(group), group[0].course.label, group[0].ordinal, group[0].family_label))
        return candidate_groups[0]
    return []


def _due_phrase_for_signal(*, due_iso: str, internal_date_iso: str, hard_case_tags: list[str]) -> str:
    if "relative_time_phrase" in hard_case_tags:
        return _relative_due_phrase(due_iso=due_iso, internal_date_iso=internal_date_iso)
    return _human_due_phrase(due_iso)


def _move_to_weekday(value: datetime, weekday_name: str) -> datetime:
    wanted = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }[weekday_name]
    shift = (wanted - value.weekday()) % 7
    return value + timedelta(days=shift)


def _human_due_phrase(due_iso: str | None) -> str:
    if due_iso is None:
        return ""
    due_at = datetime.fromisoformat(due_iso)
    return due_at.strftime("%A, %B %d at %I:%M %p UTC")


def _relative_due_phrase(*, due_iso: str, internal_date_iso: str) -> str:
    due_at = datetime.fromisoformat(due_iso)
    internal_date = datetime.fromisoformat(internal_date_iso)
    day_delta = (due_at.date() - internal_date.date()).days
    rendered_time = due_at.strftime("%I:%M %p").lstrip("0")
    if due_at.hour == 12 and due_at.minute == 0:
        rendered_time = "noon"
    if day_delta == 0:
        return f"tonight by {rendered_time}"
    if day_delta == 1:
        return f"tomorrow at {rendered_time}"
    if 1 < day_delta <= 6:
        return f"this {due_at.strftime('%A')} at {rendered_time}"
    return _human_due_phrase(due_iso)


def _dedupe_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


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
    return CourseAnchor(label=cleaned, dept=dept, number=int(number_token), suffix=suffix_token)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a one-year Gmail + ICS synthetic scenario manifest.")
    parser.add_argument(
        "--output",
        default="data/synthetic/year_timeline_demo/year_timeline_manifest.json",
        help="Output manifest path.",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--batches-per-semester", type=int, default=DEFAULT_BATCHES_PER_SEMESTER)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_year_timeline_manifest(
        seed=args.seed,
        batches_per_semester=args.batches_per_semester,
        batch_size=args.batch_size,
    )
    output_path = Path(args.output)
    write_year_timeline_manifest(output_path, manifest)
    print(output_path)


if __name__ == "__main__":
    main()


__all__ = [
    "BatchPlan",
    "CourseAnchor",
    "SemesterPlan",
    "TimelineGmailMessagePlan",
    "TimelineIcsEventPlan",
    "YearTimelineManifest",
    "build_year_timeline_manifest",
    "write_year_timeline_manifest",
]
