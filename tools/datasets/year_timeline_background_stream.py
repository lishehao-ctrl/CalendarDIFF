from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

BackgroundCategory = Literal[
    "personal_finance",
    "commerce",
    "package_subscription",
    "account_security",
    "housing",
    "campus_admin",
    "student_services",
    "clubs_and_events",
    "newsletter",
    "jobs_and_careers",
    "calendar_wrapper",
    "academic_non_target",
    "lms_wrapper_noise",
]
BackgroundGroup = Literal["unrelated_general", "academic_non_target", "wrapper_clutter"]
BackgroundSenderRole = Literal[
    "no_reply_automation",
    "campus_office",
    "housing_sender",
    "student_services_sender",
    "student_org",
    "recruiter",
    "commerce_sender",
    "security_alert_sender",
    "lms_wrapper_sender",
    "calendar_service",
    "newsletter_sender",
    "finance_sender",
]
BackgroundStructure = Literal[
    "short_notification",
    "long_newsletter",
    "wrapper_quoted",
    "list_digest",
    "footer_heavy_promo",
]
WeekStage = Literal["setup_release", "early_ramp", "first_pressure", "project_push", "late_crunch", "finals_rollover"]

DEFAULT_BACKGROUND_SEED = 20260318
BACKGROUND_PER_BATCH = 204
ACADEMIC_NON_TARGET_PER_BATCH = 36
WRAPPER_CLUTTER_PER_BATCH = 54
UNRELATED_GENERAL_PER_BATCH = 114


@dataclass(frozen=True)
class BackgroundEmailPlan:
    message_id: str
    thread_id: str
    subject: str
    body_text: str
    from_header: str
    label_ids: list[str]
    internal_date: str
    history_batch: int
    history_global_batch: int
    semester: int
    batch: int
    phase_label: str
    week_stage: WeekStage
    background_category: BackgroundCategory
    background_group: BackgroundGroup
    sender_role: BackgroundSenderRole
    message_structure: BackgroundStructure
    background_topic: str
    bait_terms: list[str] = field(default_factory=list)
    is_false_positive_bait: bool = False
    season_tag: str = ""
    non_target_reason: str = ""
    course_hint: str | None = None


@dataclass(frozen=True)
class BackgroundBatchPlan:
    semester: int
    batch: int
    global_batch: int
    phase_label: str
    week_stage: WeekStage
    start_iso: str
    messages: list[BackgroundEmailPlan]


@dataclass(frozen=True)
class YearTimelineBackgroundStream:
    version: str
    seed: int
    total_messages: int
    batches: list[BackgroundBatchPlan]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


FINANCIAL_SENDERS = ("Mission Bay Credit Union", "North Harbor Bank", "Anchor Card Services")
COMMERCE_SENDERS = ("ParcelHub", "ShopRunner", "Campus Market", "CloudStorage Plus")
SECURITY_SENDERS = ("accounts@example.edu", "SecureLogin", "Auth Shield")
HOUSING_SENDERS = ("Triton Housing", "Mesa Utilities", "Campus Maintenance", "Residential Life")
CAMPUS_SENDERS = ("Transportation Services", "Registrar Updates", "Student Health", "Campus Billing")
STUDENT_SERVICES_SENDERS = ("Academic Advising", "EASy Requests", "Enrollment Services", "Student Accessibility Office")
CLUB_SENDERS = ("Triton Volunteers", "Quiz Bowl Club", "Robotics Society", "Project Showcase Team")
NEWSLETTER_SENDERS = ("Morning Roundup", "Student Digest", "Campus Weekly", "Tech Briefing")
RECRUITER_SENDERS = ("Vertex Recruiting", "Northwind Careers", "Campus Talent Desk", "Gradient Labs Recruiting")
CALENDAR_SENDERS = ("Calendar", "Events Calendar", "RSVP Service")
LMS_SENDERS = ("Canvas Notifications", "Piazza Digest", "Gradescope Updates")

COURSE_CONTEXTS: dict[str, tuple[str, ...]] = {
    "WI26": ("CSE120", "CSE151A", "MATH18"),
    "SP26": ("CSE120", "CSE151A", "MATH20C"),
    "SU26": ("CSE151A", "DSC10", "COGS108"),
    "FA26": ("CSE120", "DSC10", "CHEM6A"),
}

ACADEMIC_TOPICS = {
    "setup_release": (
        ("office hours schedule", "office hours expanded before the first quiz, but no assignment due date changed"),
        ("discussion logistics", "discussion rooms changed, and the worksheet/report timing is unchanged"),
        ("lab checkoff routing", "lab checkoff routing moved sections around, but the graded write-up deadline is unchanged"),
        ("lecture notes posted", "lecture note uploads are available, while the monitored homework timing stays unchanged"),
        ("EASy attendance notice", "attendance accommodation instructions were posted, but no graded event time moved"),
        ("section waitlist admin", "discussion waitlist handling changed and the graded submission schedule is unchanged"),
    ),
    "early_ramp": (
        ("grade posted", "a grade was posted for feedback only; no new deadline was introduced"),
        ("solutions released", "solution files are available now, but the original submission window is closed and unchanged"),
        ("lecture moved", "lecture moved online for one meeting, and homework timing stays the same"),
        ("regrade process", "regrade instructions were posted, but they do not define a canonical monitored due-time signal"),
        ("office-hours overflow", "overflow office hours were added, yet the assignment timing remains unchanged"),
        ("enrollment logistics", "late add and enrollment routing changed, while monitored course work timing did not"),
    ),
    "first_pressure": (
        ("review session", "a review session was added before the quiz/final, but no monitored event time moved"),
        ("exam format note", "the exam format was clarified, but the scheduled exam time is unchanged"),
        ("section swap", "students may swap sections this week, while the report/homework deadline remains unchanged"),
        ("lab safety reminder", "lab safety paperwork reopened, but the graded write-up deadline is unchanged"),
        ("lecture reading note", "reading guidance changed before the quiz, while the canonical due time stayed fixed"),
        ("gradebook clarification", "gradebook weighting was clarified without introducing a new monitored deadline"),
    ),
    "project_push": (
        ("project Q&A", "the project Q&A thread is active, but milestone timing is still the same"),
        ("office-hours overflow", "overflow office hours were added, but deliverable due times stay unchanged"),
        ("lab section moved", "lab sections moved, report unchanged"),
        ("team logistics", "team-formation logistics changed, but the monitored project deadline did not"),
        ("solutions commentary", "solution commentary was posted for reference only, not as a new deadline"),
        ("advisor note", "advisor guidance mentioned submission strategy without changing any canonical due time"),
    ),
    "late_crunch": (
        ("grade release", "mid-quarter grades were posted and comments are available; no new due signal exists"),
        ("review worksheet", "a review worksheet was uploaded and is optional, not a new graded assignment"),
        ("practice quiz", "a practice quiz opened, but it is not a monitored graded event"),
        ("regrade reminder", "regrade routing reopened briefly, but canonical event timing is unchanged"),
        ("discussion overflow", "extra discussion seating opened up while the monitored homework due time stayed fixed"),
        ("lecture recording note", "lecture recordings were reposted and do not create a new monitored item"),
    ),
    "finals_rollover": (
        ("final review", "review session details were posted for finals week, and official exam timing remains unchanged"),
        ("grade correction window", "grade correction submissions are due, but that is not a canonical course event deadline"),
        ("solution digest", "solution digest posted after the final; no monitored due change is present"),
        ("exam format FAQ", "the exam FAQ was updated, but the official timed assessment window stayed fixed"),
        ("office-hours triage", "finals office-hours triage changed without moving any monitored deadline"),
        ("post-final survey", "a course wrap-up survey opened and should not create a canonical event"),
    ),
}

GENERIC_TOPICS: dict[BackgroundCategory, tuple[tuple[str, str], ...]] = {
    "personal_finance": (
        ("tuition installment", "billing reminder only; this is not tied to monitored course work"),
        ("credit card statement", "card payment timing only and unrelated to any class deliverable"),
        ("bank verification", "banking verification or statement review only; not a course-event signal"),
        ("autopay confirmation", "autopay confirmation timing is personal finance noise, not academic timing"),
    ),
    "commerce": (
        ("promo sale", "commerce and promo timing only; no academic schedule changed"),
        ("shopping cart reminder", "cart-expiration messaging is unrelated to any monitored class event"),
        ("travel booking", "travel or booking reminders can say deadline/final without being course signals"),
        ("device deal", "commercial discount language is intentionally noisy and non-academic"),
    ),
    "package_subscription": (
        ("package delivery", "delivery-window timing only; not a monitored course deadline"),
        ("subscription renewal", "renewal timing is commercial account noise and not a canonical event"),
        ("trial ending", "subscription trial expiry is unrelated to the course timeline"),
        ("shipment exception", "shipping exception alerts are non-target noise despite action wording"),
    ),
    "account_security": (
        ("sign-in alert", "account access verification only; not an academic event"),
        ("password reset", "credential reset timing is security noise and not a class signal"),
        ("device approval", "device approval or MFA follow-up only; unrelated to course events"),
        ("verification code", "verification timing is operational security noise"),
    ),
    "housing": (
        ("lease renewal", "housing contract timing only; no course deliverable changed"),
        ("maintenance window", "maintenance scheduling is residential noise, not a monitored academic event"),
        ("utility bill", "utility payment timing belongs to housing/admin noise"),
        ("room inspection", "room inspection logistics are unrelated to course work timing"),
    ),
    "campus_admin": (
        ("parking permit", "campus admin operations only; no canonical course event should be created"),
        ("registrar notice", "registrar paperwork or hold messaging is non-target admin clutter"),
        ("transit pass", "transit logistics use deadline wording without carrying monitored course semantics"),
        ("student health form", "health paperwork timing is campus admin noise, not academic timing"),
    ),
    "student_services": (
        ("advising follow-up", "student services or advising workflows are not monitored course-event signals"),
        ("EASy request", "EASy routing can mention deadlines but does not imply a course deadline mutation"),
        ("enrollment hold", "enrollment bureaucracy timing is administrative and non-target"),
        ("accessibility paperwork", "paperwork timing from student services should be filtered before LLM"),
    ),
    "clubs_and_events": (
        ("RSVP reminder", "club RSVP language is event noise, not a monitored graded item"),
        ("volunteer shift", "volunteer logistics can look assignment-like but are non-target"),
        ("project showcase", "showcase/event timing is social noise despite project wording"),
        ("hackathon signup", "event signup timing is unrelated to canonical course events"),
    ),
    "jobs_and_careers": (
        ("internship application", "recruiting logistics are unrelated to monitored course deadlines"),
        ("networking night", "career networking timing is non-target even when it uses deadline language"),
        ("final round availability", "recruiter scheduling is operational job-search noise"),
        ("resume review", "career-center review windows can resemble assignment prompts without academic semantics"),
    ),
    "newsletter": (
        ("campus digest", "digest content bundles many prompts together and should stay non-target"),
        ("student newsletter", "newsletter action prompts are intentionally noisy and non-canonical"),
        ("tech briefing", "digest summaries can mention final/project terms without course semantics"),
        ("weekly roundup", "roundup items are aggregate clutter, not a direct course signal"),
    ),
    "calendar_wrapper": (
        ("calendar RSVP", "calendar forwarding summaries are wrappers, not authoritative course timing"),
        ("event reminder", "calendar wrappers bundle actions without creating monitored course facts"),
        ("schedule digest", "calendar digests are noise even when they mention deadlines"),
        ("invite follow-up", "invite reminders are wrapper clutter rather than canonical academic signals"),
    ),
    "lms_wrapper_noise": (
        ("canvas comment", "an LMS comment or notification was posted, but no monitored deadline changed"),
        ("gradescope digest", "wrapper digest only; grade or assignment wording is non-target here"),
        ("piazza thread", "discussion thread activity is present without a canonical due-time mutation"),
        ("rubric posted", "rubric or comment-posted wrappers should not become monitored events"),
    ),
}


def build_year_timeline_background_stream(*, manifest: dict[str, Any], seed: int = DEFAULT_BACKGROUND_SEED) -> YearTimelineBackgroundStream:
    rng = random.Random(seed)
    batch_plans: list[BackgroundBatchPlan] = []
    total_messages = 0

    for phase in manifest.get("plans", []):
        if not isinstance(phase, dict):
            continue
        semester = int(phase.get("semester") or 0)
        phase_label = str(phase.get("phase_label") or "")
        for batch in phase.get("batches", []):
            if not isinstance(batch, dict):
                continue
            batch_no = int(batch.get("batch") or 0)
            global_batch = int(batch.get("global_batch") or 0)
            batch_start = datetime.fromisoformat(str(batch.get("start_iso")))
            week_stage = str(batch.get("week_stage") or _week_stage_for_batch(batch_no))
            season_tag = _season_tag(phase_label=phase_label, batch=batch_no, week_stage=week_stage)
            category_counts = _category_counts_for_batch(phase_label=phase_label, batch=batch_no, week_stage=week_stage)

            messages: list[BackgroundEmailPlan] = []
            slot = 0
            for category in _category_emission_order(phase_label=phase_label, batch=batch_no):
                count = category_counts.get(category, 0)
                for local_index in range(count):
                    messages.append(
                        _build_background_message(
                            rng=rng,
                            semester=semester,
                            batch=batch_no,
                            global_batch=global_batch,
                            phase_label=phase_label,
                            week_stage=week_stage,  # type: ignore[arg-type]
                            season_tag=season_tag,
                            batch_start=batch_start,
                            category=category,
                            slot=slot,
                            local_index=local_index,
                        )
                    )
                    slot += 1
            if len(messages) != BACKGROUND_PER_BATCH:
                raise RuntimeError(f"background batch expected {BACKGROUND_PER_BATCH} messages, got {len(messages)}")
            messages.sort(key=lambda row: (row.internal_date, row.message_id))
            batch_plans.append(
                BackgroundBatchPlan(
                    semester=semester,
                    batch=batch_no,
                    global_batch=global_batch,
                    phase_label=phase_label,
                    week_stage=week_stage,  # type: ignore[arg-type]
                    start_iso=batch_start.isoformat(),
                    messages=messages,
                )
            )
            total_messages += len(messages)

    return YearTimelineBackgroundStream(
        version="year-timeline-background-v1",
        seed=seed,
        total_messages=total_messages,
        batches=batch_plans,
    )


def build_background_email_samples(*, manifest: dict[str, Any], seed: int = DEFAULT_BACKGROUND_SEED) -> list[dict[str, Any]]:
    stream = build_year_timeline_background_stream(manifest=manifest, seed=seed)
    samples: list[dict[str, Any]] = []
    for batch in stream.batches:
        for message in batch.messages:
            sample = {
                "sample_id": message.message_id,
                "sample_source": "synthetic.year_timeline.background",
                "message_id": message.message_id,
                "thread_id": message.thread_id,
                "subject": message.subject,
                "from_header": message.from_header,
                "snippet": build_snippet(message.body_text),
                "body_text": message.body_text,
                "internal_date": message.internal_date,
                "label_ids": list(message.label_ids),
                "collection_bucket": "year_timeline_full_sim",
                "notes": ", ".join(
                    [
                        message.background_category,
                        message.sender_role,
                        message.message_structure,
                        *(message.bait_terms or []),
                    ]
                ),
                "message_kind": "background_noise",
                "expected_mode": "unknown",
                "expected_record_type": None,
                "expected_semantic_event_draft": None,
                "expected_directive": None,
                "hard_case_tags": [],
                "background_category": message.background_category,
                "background_group": message.background_group,
                "background_sender_role": message.sender_role,
                "message_structure": message.message_structure,
                "background_topic": message.background_topic,
                "bait_terms": list(message.bait_terms),
                "is_false_positive_bait": message.is_false_positive_bait,
                "season_tag": message.season_tag,
                "non_target_reason": message.non_target_reason,
                "course_hint": message.course_hint,
                "history_batch": message.history_batch,
                "history_global_batch": message.history_global_batch,
                "phase_label": message.phase_label,
                "week_stage": message.week_stage,
                "full_sim_layer": "background_noise",
                "prefilter_expected_route": "skip_unknown",
                "prefilter_reason_family": _prefilter_reason_family_for_category(message.background_category),
                "prefilter_target_class": "non_target",
                "prefilter_should_match_course_token": message.course_hint is not None,
                "prefilter_sender_strength": _prefilter_sender_strength(message.sender_role),
                "prefilter_keyword_bait": list(message.bait_terms),
            }
            samples.append(sample)
    return samples


def build_snippet(body_text: str, *, max_chars: int = 180) -> str:
    return " ".join(body_text.strip().split())[:max_chars]


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


def _season_tag(*, phase_label: str, batch: int, week_stage: str) -> str:
    if phase_label == "SP26" and 4 <= batch <= 10:
        return "internship-season"
    if phase_label == "FA26" and week_stage == "finals_rollover":
        return "holiday-commerce"
    if phase_label == "SU26":
        return "summer-compressed"
    if week_stage == "setup_release":
        return "quarter-start"
    if week_stage == "finals_rollover":
        return "finals-window"
    return "regular-term"


def _category_emission_order(*, phase_label: str, batch: int) -> tuple[BackgroundCategory, ...]:
    del phase_label
    if batch % 2 == 0:
        return (
            "campus_admin",
            "student_services",
            "calendar_wrapper",
            "newsletter",
            "personal_finance",
            "housing",
            "academic_non_target",
            "commerce",
            "package_subscription",
            "lms_wrapper_noise",
            "jobs_and_careers",
            "clubs_and_events",
            "account_security",
        )
    return (
        "personal_finance",
        "commerce",
        "package_subscription",
        "account_security",
        "housing",
        "campus_admin",
        "student_services",
        "clubs_and_events",
        "jobs_and_careers",
        "newsletter",
        "calendar_wrapper",
        "academic_non_target",
        "lms_wrapper_noise",
    )


def _category_counts_for_batch(*, phase_label: str, batch: int, week_stage: str) -> dict[BackgroundCategory, int]:
    unrelated_weights = {
        "personal_finance": 1.0,
        "commerce": 1.2,
        "package_subscription": 1.0,
        "account_security": 0.8,
        "housing": 0.9,
        "campus_admin": 0.9,
        "student_services": 0.9,
        "clubs_and_events": 0.7,
        "jobs_and_careers": 0.9,
    }
    wrapper_weights = {
        "newsletter": 1.0,
        "calendar_wrapper": 0.9,
        "lms_wrapper_noise": 1.1,
    }

    if week_stage == "setup_release":
        unrelated_weights["campus_admin"] += 0.7
        unrelated_weights["student_services"] += 0.5
        unrelated_weights["account_security"] += 0.4
        unrelated_weights["housing"] += 0.2
        unrelated_weights["jobs_and_careers"] -= 0.3
        wrapper_weights["calendar_wrapper"] += 0.6
        wrapper_weights["lms_wrapper_noise"] += 0.3
    elif week_stage == "early_ramp":
        unrelated_weights["campus_admin"] += 0.2
        unrelated_weights["student_services"] += 0.3
        wrapper_weights["calendar_wrapper"] += 0.2
    elif week_stage == "first_pressure":
        unrelated_weights["jobs_and_careers"] += 0.2
        unrelated_weights["student_services"] += 0.2
        wrapper_weights["newsletter"] += 0.2
        wrapper_weights["lms_wrapper_noise"] += 0.2
    elif week_stage == "project_push":
        unrelated_weights["jobs_and_careers"] += 0.5
        unrelated_weights["clubs_and_events"] += 0.1
        unrelated_weights["commerce"] -= 0.2
        wrapper_weights["newsletter"] += 0.4
    elif week_stage == "late_crunch":
        unrelated_weights["personal_finance"] += 0.3
        unrelated_weights["package_subscription"] += 0.2
        unrelated_weights["jobs_and_careers"] += 0.4
        wrapper_weights["lms_wrapper_noise"] += 0.3
    elif week_stage == "finals_rollover":
        unrelated_weights["commerce"] += 0.8
        unrelated_weights["package_subscription"] += 0.4
        unrelated_weights["clubs_and_events"] += 0.3
        unrelated_weights["campus_admin"] -= 0.4
        unrelated_weights["jobs_and_careers"] -= 0.3
        wrapper_weights["lms_wrapper_noise"] += 0.8
        wrapper_weights["calendar_wrapper"] -= 0.3

    if phase_label == "SP26" and 4 <= batch <= 10:
        unrelated_weights["jobs_and_careers"] += 0.8
        unrelated_weights["commerce"] -= 0.3
        unrelated_weights["clubs_and_events"] -= 0.2
    if phase_label == "FA26" and batch >= 10:
        unrelated_weights["commerce"] += 0.5
        unrelated_weights["package_subscription"] += 0.3
        unrelated_weights["housing"] += 0.2
        unrelated_weights["clubs_and_events"] += 0.2
    if phase_label == "SU26":
        unrelated_weights["commerce"] += 0.5
        unrelated_weights["clubs_and_events"] += 0.3
        unrelated_weights["housing"] += 0.2
        unrelated_weights["campus_admin"] -= 0.4
        unrelated_weights["jobs_and_careers"] -= 0.2
        wrapper_weights["newsletter"] -= 0.2
        wrapper_weights["calendar_wrapper"] += 0.2

    counts: dict[BackgroundCategory, int] = {"academic_non_target": ACADEMIC_NON_TARGET_PER_BATCH}
    counts.update(_allocate_weighted_counts(total=UNRELATED_GENERAL_PER_BATCH, weights=unrelated_weights))
    counts.update(_allocate_weighted_counts(total=WRAPPER_CLUTTER_PER_BATCH, weights=wrapper_weights))
    return counts


def _allocate_weighted_counts(total: int, weights: dict[str, float]) -> dict[Any, int]:
    positive = {key: max(value, 0.05) for key, value in weights.items()}
    weight_sum = sum(positive.values())
    raw = {key: total * value / weight_sum for key, value in positive.items()}
    counts = {key: int(value) for key, value in raw.items()}
    remainder = total - sum(counts.values())
    ordered = sorted(raw.items(), key=lambda item: (item[1] - int(item[1]), item[0]), reverse=True)
    for index in range(remainder):
        counts[ordered[index % len(ordered)][0]] += 1
    return counts


def _build_background_message(
    *,
    rng: random.Random,
    semester: int,
    batch: int,
    global_batch: int,
    phase_label: str,
    week_stage: WeekStage,
    season_tag: str,
    batch_start: datetime,
    category: BackgroundCategory,
    slot: int,
    local_index: int,
) -> BackgroundEmailPlan:
    group = _group_for_category(category)
    sender_role = _sender_role_for_category(category=category, local_index=local_index, phase_label=phase_label, week_stage=week_stage)
    structure = _structure_for_category(category=category, sender_role=sender_role, local_index=local_index)
    bait_terms = _bait_terms_for_category(category=category, week_stage=week_stage, local_index=local_index)
    course_hint = _course_hint_for_category(category, phase_label=phase_label, local_index=local_index)
    background_topic, topic_line = _topic_for_category(category=category, week_stage=week_stage, local_index=local_index)
    subject = _subject_for_category(
        category=category,
        sender_role=sender_role,
        structure=structure,
        bait_terms=bait_terms,
        course_hint=course_hint,
        background_topic=background_topic,
        week_stage=week_stage,
        season_tag=season_tag,
        local_index=local_index,
    )
    body_text, non_target_reason = _body_for_category(
        category=category,
        sender_role=sender_role,
        structure=structure,
        bait_terms=bait_terms,
        course_hint=course_hint,
        background_topic=background_topic,
        topic_line=topic_line,
        week_stage=week_stage,
        season_tag=season_tag,
        batch=batch,
        local_index=local_index,
    )
    internal_date = _background_internal_date(
        batch_start=batch_start,
        category=category,
        local_index=local_index,
        slot=slot,
        phase_label=phase_label,
        week_stage=week_stage,
    )
    return BackgroundEmailPlan(
        message_id=f"bg-y{semester:02d}-b{batch:02d}-{slot:03d}",
        thread_id=f"thread-bg-y{semester:02d}-b{batch:02d}-{category}-{local_index:02d}",
        subject=subject,
        body_text=body_text,
        from_header=_from_header_for_sender_role(sender_role=sender_role, local_index=local_index),
        label_ids=_label_ids_for_category(category),
        internal_date=internal_date.isoformat(),
        history_batch=batch,
        history_global_batch=global_batch,
        semester=semester,
        batch=batch,
        phase_label=phase_label,
        week_stage=week_stage,
        background_category=category,
        background_group=group,
        sender_role=sender_role,
        message_structure=structure,
        background_topic=background_topic,
        bait_terms=bait_terms,
        is_false_positive_bait=bool(bait_terms),
        season_tag=season_tag,
        non_target_reason=non_target_reason,
        course_hint=course_hint,
    )


def _group_for_category(category: BackgroundCategory) -> BackgroundGroup:
    if category == "academic_non_target":
        return "academic_non_target"
    if category in {"newsletter", "calendar_wrapper", "lms_wrapper_noise"}:
        return "wrapper_clutter"
    return "unrelated_general"


def _sender_role_for_category(*, category: BackgroundCategory, local_index: int, phase_label: str, week_stage: WeekStage) -> BackgroundSenderRole:
    if category == "personal_finance":
        return "finance_sender"
    if category == "commerce":
        return "commerce_sender"
    if category == "package_subscription":
        return "commerce_sender"
    if category == "account_security":
        return "security_alert_sender"
    if category == "housing":
        return "housing_sender"
    if category == "campus_admin":
        return "campus_office"
    if category == "student_services":
        return "student_services_sender"
    if category == "clubs_and_events":
        return "student_org"
    if category == "newsletter":
        return "newsletter_sender"
    if category == "jobs_and_careers":
        return "recruiter"
    if category == "calendar_wrapper":
        return "calendar_service"
    if category == "lms_wrapper_noise":
        return "lms_wrapper_sender"
    if phase_label == "SU26" and week_stage == "finals_rollover" and local_index % 2 == 0:
        return "lms_wrapper_sender"
    return "campus_office"


def _structure_for_category(*, category: BackgroundCategory, sender_role: BackgroundSenderRole, local_index: int) -> BackgroundStructure:
    if category in {"newsletter", "calendar_wrapper"}:
        return "list_digest" if local_index % 3 == 0 else "wrapper_quoted"
    if category == "lms_wrapper_noise":
        return "wrapper_quoted"
    if category in {"commerce", "package_subscription", "clubs_and_events"}:
        return "footer_heavy_promo" if local_index % 2 == 0 else "short_notification"
    if category in {"jobs_and_careers", "campus_admin", "student_services"} and local_index % 4 == 0:
        return "long_newsletter"
    if category == "housing" and local_index % 3 == 0:
        return "list_digest"
    if sender_role in {"security_alert_sender", "finance_sender"}:
        return "short_notification"
    return "list_digest" if local_index % 5 == 0 else "short_notification"


def _bait_terms_for_category(*, category: BackgroundCategory, week_stage: WeekStage, local_index: int) -> list[str]:
    pool: dict[BackgroundCategory, tuple[str, ...]] = {
        "personal_finance": ("deadline", "due", "final", "submission"),
        "commerce": ("due", "final", "project"),
        "package_subscription": ("deadline", "due", "submission", "project"),
        "account_security": ("final", "submission", "due"),
        "housing": ("deadline", "due", "final"),
        "campus_admin": ("deadline", "submission", "final"),
        "student_services": ("deadline", "assignment", "submission"),
        "clubs_and_events": ("quiz", "project", "due"),
        "newsletter": ("assignment", "final", "project"),
        "jobs_and_careers": ("project", "submission", "deadline"),
        "calendar_wrapper": ("final", "deadline", "project"),
        "academic_non_target": ("grade", "assignment", "quiz", "project", "final", "submission"),
        "lms_wrapper_noise": ("grade", "assignment", "project", "submission", "quiz", "final"),
    }
    terms = list(pool[category])
    count = 2 if category in {"academic_non_target", "lms_wrapper_noise"} and week_stage in {"first_pressure", "late_crunch", "finals_rollover"} else 1
    if category == "account_security" and local_index % 4 == 0:
        count = 0
    return [terms[(local_index + offset) % len(terms)] for offset in range(count)]


def _course_hint_for_category(category: BackgroundCategory, *, phase_label: str, local_index: int) -> str | None:
    if category not in {"academic_non_target", "lms_wrapper_noise"}:
        return None
    courses = COURSE_CONTEXTS.get(phase_label) or ("CSE120",)
    return courses[local_index % len(courses)]


def _topic_for_category(*, category: BackgroundCategory, week_stage: WeekStage, local_index: int) -> tuple[str, str]:
    if category == "academic_non_target":
        return ACADEMIC_TOPICS[week_stage][local_index % len(ACADEMIC_TOPICS[week_stage])]
    topic_rows = GENERIC_TOPICS[category]
    return topic_rows[local_index % len(topic_rows)]


def _subject_for_category(
    *,
    category: BackgroundCategory,
    sender_role: BackgroundSenderRole,
    structure: BackgroundStructure,
    bait_terms: list[str],
    course_hint: str | None,
    background_topic: str,
    week_stage: WeekStage,
    season_tag: str,
    local_index: int,
) -> str:
    bait = bait_terms[0] if bait_terms else "update"
    if category == "personal_finance":
        return f"Action needed: {background_topic} {bait} reminder"
    if category == "commerce":
        return f"{background_topic.title()} {bait} update"
    if category == "package_subscription":
        return f"{background_topic.title()} {bait} notice"
    if category == "account_security":
        return f"{background_topic.title()} {'deadline' if bait == 'final' else bait}"
    if category == "housing":
        return f"{background_topic.title()} {bait} update"
    if category == "campus_admin":
        return f"{background_topic.title()} {bait} notice"
    if category == "student_services":
        return f"{background_topic.title()} {bait} follow-up"
    if category == "clubs_and_events":
        return f"{background_topic.title()}: {bait} reminder"
    if category == "newsletter":
        return f"{season_tag.replace('-', ' ').title()} digest: {bait}, events, and inbox clutter"
    if category == "jobs_and_careers":
        return f"{background_topic.title()} {bait} update"
    if category == "calendar_wrapper":
        prefix = "Fwd: " if structure == "wrapper_quoted" else ""
        return f"{prefix}Calendar: {background_topic.title()} {bait}"
    if category == "academic_non_target":
        return f"[{course_hint}] {background_topic} and {bait} note"
    return f"Canvas/Piazza: {background_topic} for [{course_hint}]"


def _body_for_category(
    *,
    category: BackgroundCategory,
    sender_role: BackgroundSenderRole,
    structure: BackgroundStructure,
    bait_terms: list[str],
    course_hint: str | None,
    background_topic: str,
    topic_line: str,
    week_stage: WeekStage,
    season_tag: str,
    batch: int,
    local_index: int,
) -> tuple[str, str]:
    bait_line = _bait_line(category=category, bait_terms=bait_terms, course_hint=course_hint, week_stage=week_stage, local_index=local_index)
    if category == "academic_non_target":
        body = _render_body_structure(
            structure=structure,
            intro=f"Course context: {course_hint}",
            signal_like_line=f"{topic_line}.",
            clutter_lines=[
                bait_line,
                "Please read the office-hours note, the FAQ thread, and the discussion logistics before replying all.",
                "This email is academic context only and should not create a monitored event in the canonical timeline.",
            ],
            footer=_footer_for_sender(sender_role=sender_role),
        )
        return body, f"academic_non_target:{background_topic}"
    if category == "lms_wrapper_noise":
        body = _render_body_structure(
            structure=structure,
            intro=f"You are receiving this notification because activity occurred in {course_hint}.",
            signal_like_line=f"{topic_line}.",
            clutter_lines=[
                bait_line,
                "> quoted thread fragment: please review the project thread before the final demo",
                "Replying by email may not post to the correct LMS thread.",
            ],
            footer=_footer_for_sender(sender_role=sender_role),
        )
        return body, f"lms_wrapper_noise:{background_topic}"
    if category == "calendar_wrapper":
        body = _render_body_structure(
            structure=structure,
            intro="Calendar forwarding summary",
            signal_like_line=f"{topic_line}.",
            clutter_lines=[
                bait_line,
                "> forwarded invite block",
                f"Season tag: {season_tag}. Multiple action prompts may be bundled into one wrapper.",
            ],
            footer="Manage calendar notifications in settings.",
        )
        return body, f"calendar_wrapper:{background_topic}"
    if category == "newsletter":
        body = _render_body_structure(
            structure=structure,
            intro=f"{season_tag.replace('-', ' ').title()} newsletter",
            signal_like_line=f"{topic_line}.",
            clutter_lines=[
                bait_line,
                "- item 1: campus event roundup",
                "- item 2: project fair recap",
                "- item 3: final reminders from unrelated lists",
            ],
            footer="Unsubscribe | Manage preferences | View in browser",
        )
        return body, f"newsletter_digest:{background_topic}"
    if category == "jobs_and_careers":
        body = _render_body_structure(
            structure=structure,
            intro="Recruiting workflow update",
            signal_like_line=f"{topic_line}.",
            clutter_lines=[
                bait_line,
                "Several action prompts may appear together because employers batch multiple reminders into one thread.",
                f"Batch marker: {batch}",
            ],
            footer="This mailbox is not monitored.",
        )
        return body, f"jobs_career_noise:{background_topic}"
    if category == "clubs_and_events":
        body = _render_body_structure(
            structure=structure,
            intro="Student org update",
            signal_like_line=f"{topic_line}.",
            clutter_lines=[
                bait_line,
                "Bring friends, RSVP if you can, and ignore any assignment-like phrasing if you are testing parser precision.",
            ],
            footer="Sent by a registered student organization.",
        )
        return body, f"club_event_noise:{background_topic}"
    if category == "student_services":
        body = _render_body_structure(
            structure=structure,
            intro="Student services notice",
            signal_like_line=f"{topic_line}.",
            clutter_lines=[
                bait_line,
                "Advising and paperwork reminders intentionally include course-like wording in this dataset.",
            ],
            footer="Please use the student services portal for follow-up.",
        )
        return body, f"student_services_noise:{background_topic}"
    if category == "campus_admin":
        body = _render_body_structure(
            structure=structure,
            intro="Campus operations notice",
            signal_like_line=f"{topic_line}.",
            clutter_lines=[
                bait_line,
                f"Season tag: {season_tag}. Setup/admin mail is intentionally denser near quarter boundaries.",
            ],
            footer="Please do not reply to this automated campus message.",
        )
        return body, f"campus_admin_noise:{background_topic}"
    if category == "housing":
        body = _render_body_structure(
            structure=structure,
            intro="Housing and utilities update",
            signal_like_line=f"{topic_line}.",
            clutter_lines=[
                bait_line,
                "Residential timelines are intentionally mixed with due/final wording to pressure-test the prefilter.",
            ],
            footer="Manage lease and housing preferences in the resident portal.",
        )
        return body, f"housing_noise:{background_topic}"
    if category == "account_security":
        body = _render_body_structure(
            structure=structure,
            intro="Security alert",
            signal_like_line=f"{topic_line}.",
            clutter_lines=[
                bait_line,
                "If this was not you, reset your password or review your session history.",
            ],
            footer="Security mailbox | no-reply",
        )
        return body, f"account_security_noise:{background_topic}"
    if category == "package_subscription":
        body = _render_body_structure(
            structure=structure,
            intro="Package and subscription update",
            signal_like_line=f"{topic_line}.",
            clutter_lines=[
                bait_line,
                "Renewal and shipment prompts are intentionally noisy in this stream.",
            ],
            footer="Track shipment | Manage subscription | Update delivery preferences",
        )
        return body, f"package_subscription_noise:{background_topic}"
    if category == "commerce":
        body = _render_body_structure(
            structure=structure,
            intro="Order and subscription update",
            signal_like_line=f"{topic_line}.",
            clutter_lines=[
                bait_line,
                "Promotional footers and action prompts are intentionally noisy here.",
            ],
            footer="View order | Track package | Update subscription preferences",
        )
        return body, f"commerce_noise:{background_topic}"
    body = _render_body_structure(
        structure=structure,
        intro="Finance alert",
        signal_like_line=f"{topic_line}.",
        clutter_lines=[
            bait_line,
            "Please keep this for your records.",
        ],
        footer="Member services | secure message center",
    )
    return body, f"personal_finance_noise:{background_topic}"


def _bait_line(*, category: BackgroundCategory, bait_terms: list[str], course_hint: str | None, week_stage: WeekStage, local_index: int) -> str:
    if not bait_terms:
        return "No explicit bait phrase in this message."
    bait = ", ".join(bait_terms)
    if category == "academic_non_target":
        samples = (
            f"The {bait} wording is present because {course_hint} staff mentioned grade release, quiz review, or assignment comments with no due-time mutation.",
            f"Students may see {bait} in the thread, but the lecture/lab logistics remain non-target and non-canonical.",
            f"One line says 'lab section moved, report unchanged' so the bait is intentional while the target semantics remain absent.",
        )
        return samples[local_index % len(samples)]
    generic = (
        f"False-positive bait terms included here: {bait}.",
        f"The wording contains {bait} even though the message is unrelated to monitored course deadlines.",
        f"Parser-bait phrase pack: {bait}.",
    )
    if week_stage == "finals_rollover":
        return generic[(local_index + 1) % len(generic)]
    return generic[local_index % len(generic)]


def _render_body_structure(
    *,
    structure: BackgroundStructure,
    intro: str,
    signal_like_line: str,
    clutter_lines: list[str],
    footer: str,
) -> str:
    if structure == "short_notification":
        return "\n".join([intro, signal_like_line, *clutter_lines[:1], footer])
    if structure == "long_newsletter":
        return "\n".join([intro, "", signal_like_line, "", *clutter_lines, "", footer])
    if structure == "wrapper_quoted":
        quoted = "\n".join(f"> {line}" for line in clutter_lines[:2])
        return "\n".join([intro, signal_like_line, quoted, footer])
    if structure == "list_digest":
        bullets = "\n".join(f"- {line}" for line in clutter_lines)
        return "\n".join([intro, signal_like_line, bullets, footer])
    repeated_footer = f"{footer}\n{footer}"
    return "\n".join([intro, signal_like_line, *clutter_lines, repeated_footer])


def _footer_for_sender(*, sender_role: BackgroundSenderRole) -> str:
    if sender_role == "lms_wrapper_sender":
        return "Canvas/Piazza wrapper footer: view thread in browser | manage notification settings"
    if sender_role == "calendar_service":
        return "Calendar service footer: yes / maybe / no | change RSVP status"
    if sender_role == "newsletter_sender":
        return "Email preferences | View digest online | Unsubscribe"
    return "Automated footer | Contact support if needed"


def _background_internal_date(
    *,
    batch_start: datetime,
    category: BackgroundCategory,
    local_index: int,
    slot: int,
    phase_label: str,
    week_stage: WeekStage,
) -> datetime:
    base_day = {
        "personal_finance": local_index % 7,
        "commerce": (local_index * 2 + 1) % 7,
        "package_subscription": (local_index * 2 + 3) % 7,
        "account_security": (local_index * 3) % 7,
        "housing": (local_index + 4) % 7,
        "campus_admin": (local_index + 1) % 5,
        "student_services": (local_index + 2) % 5,
        "clubs_and_events": (local_index + 2) % 7,
        "newsletter": local_index % 5,
        "jobs_and_careers": (local_index + 2) % 5,
        "calendar_wrapper": (local_index + 3) % 7,
        "academic_non_target": (local_index + 1) % 6,
        "lms_wrapper_noise": (local_index + 2) % 6,
    }[category]
    if week_stage == "finals_rollover" and category in {"academic_non_target", "lms_wrapper_noise"}:
        base_day = local_index % 4
    if phase_label == "SU26" and category in {"commerce", "clubs_and_events"}:
        base_day = (base_day + 1) % 7

    base_hour = {
        "personal_finance": 8,
        "commerce": 17,
        "package_subscription": 16,
        "account_security": 7,
        "housing": 11,
        "campus_admin": 9,
        "student_services": 13,
        "clubs_and_events": 18,
        "newsletter": 6,
        "jobs_and_careers": 10,
        "calendar_wrapper": 12,
        "academic_non_target": 15,
        "lms_wrapper_noise": 19,
    }[category]
    minute = (slot * 13 + local_index * 7 + len(phase_label) * 3) % 60
    return (batch_start + timedelta(days=base_day, hours=base_hour, minutes=minute)).astimezone(UTC)


def _from_header_for_sender_role(*, sender_role: BackgroundSenderRole, local_index: int) -> str:
    if sender_role == "finance_sender":
        sender = FINANCIAL_SENDERS[local_index % len(FINANCIAL_SENDERS)]
        return f"{sender} <alerts@{sender.lower().replace(' ', '')}.example.com>"
    if sender_role == "commerce_sender":
        sender = COMMERCE_SENDERS[local_index % len(COMMERCE_SENDERS)]
        return f"{sender} <offers@{sender.lower().replace(' ', '')}.example.com>"
    if sender_role == "security_alert_sender":
        sender = SECURITY_SENDERS[local_index % len(SECURITY_SENDERS)]
        return f"{sender} <security@auth.example.com>"
    if sender_role == "campus_office":
        sender = CAMPUS_SENDERS[local_index % len(CAMPUS_SENDERS)]
        return f"{sender} <noreply@campus.example.edu>"
    if sender_role == "housing_sender":
        sender = HOUSING_SENDERS[local_index % len(HOUSING_SENDERS)]
        return f"{sender} <housing@reslife.example.edu>"
    if sender_role == "student_services_sender":
        sender = STUDENT_SERVICES_SENDERS[local_index % len(STUDENT_SERVICES_SENDERS)]
        return f"{sender} <services@students.example.edu>"
    if sender_role == "student_org":
        sender = CLUB_SENDERS[local_index % len(CLUB_SENDERS)]
        return f"{sender} <hello@students.example.edu>"
    if sender_role == "newsletter_sender":
        sender = NEWSLETTER_SENDERS[local_index % len(NEWSLETTER_SENDERS)]
        return f"{sender} <digest@lists.example.com>"
    if sender_role == "recruiter":
        sender = RECRUITER_SENDERS[local_index % len(RECRUITER_SENDERS)]
        return f"{sender} <talent@careers.example.com>"
    if sender_role == "calendar_service":
        sender = CALENDAR_SENDERS[local_index % len(CALENDAR_SENDERS)]
        return f"{sender} <calendar@events.example.com>"
    sender = LMS_SENDERS[local_index % len(LMS_SENDERS)]
    return f"{sender} <notifications@lms.example.edu>"


def _label_ids_for_category(category: BackgroundCategory) -> list[str]:
    if category in {"commerce", "package_subscription"}:
        return ["INBOX", "CATEGORY_PROMOTIONS"]
    if category in {"newsletter"}:
        return ["INBOX", "CATEGORY_UPDATES"]
    if category in {"clubs_and_events"}:
        return ["INBOX", "CATEGORY_SOCIAL"]
    if category in {"calendar_wrapper", "lms_wrapper_noise", "academic_non_target", "campus_admin", "student_services"}:
        return ["INBOX", "CATEGORY_UPDATES"]
    return ["INBOX", "CATEGORY_PERSONAL"]


def _prefilter_reason_family_for_category(category: BackgroundCategory) -> str:
    mapping = {
        "personal_finance": "personal_finance",
        "commerce": "commerce",
        "package_subscription": "package_subscription",
        "account_security": "security",
        "housing": "housing",
        "campus_admin": "campus_admin",
        "student_services": "student_services",
        "clubs_and_events": "clubs_and_events",
        "newsletter": "newsletter_digest",
        "jobs_and_careers": "jobs",
        "calendar_wrapper": "calendar_wrapper_noise",
        "academic_non_target": "academic_non_target",
        "lms_wrapper_noise": "lms_wrapper_noise",
    }
    return mapping[category]


def _prefilter_sender_strength(sender_role: BackgroundSenderRole) -> str:
    if sender_role in {"lms_wrapper_sender", "calendar_service"}:
        return "strong"
    if sender_role in {"campus_office", "housing_sender", "student_services_sender"}:
        return "medium"
    if sender_role in {"newsletter_sender", "student_org", "commerce_sender", "recruiter", "finance_sender"}:
        return "weak"
    return "medium"


__all__ = [
    "BackgroundBatchPlan",
    "BackgroundEmailPlan",
    "YearTimelineBackgroundStream",
    "build_background_email_samples",
    "build_year_timeline_background_stream",
]
