from __future__ import annotations

from datetime import timezone

from app.modules.sync.ics_parser import ICSParser
from app.modules.sync.normalizer import build_fingerprint_uid, infer_course_label, normalize_events


SAMPLE_ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Deadline Diff//EN
BEGIN:VEVENT
UID:event-uid-1
DTSTART;TZID=America/Los_Angeles:20260221T100000
DTEND;TZID=America/Los_Angeles:20260221T110000
SUMMARY:CSE 151A Homework 2
DESCRIPTION:Assignment deadline
END:VEVENT
BEGIN:VEVENT
DTSTART:20260222T120000Z
DTEND:20260222T130000Z
SUMMARY:Project Milestone
DESCRIPTION:General reminder
END:VEVENT
END:VCALENDAR
"""


def test_ics_parser_converts_to_utc() -> None:
    parser = ICSParser()
    events = parser.parse(SAMPLE_ICS)

    assert len(events) == 2
    first = events[0]
    assert first.dtstart.tzinfo is not None
    assert first.dtstart.astimezone(timezone.utc).hour == 18


def test_normalizer_builds_fingerprint_for_missing_uid() -> None:
    parser = ICSParser()
    raw = parser.parse(SAMPLE_ICS)
    normalized = normalize_events(raw)

    uids = [item.uid for item in normalized]
    fingerprint_uids = [uid for uid in uids if uid.startswith("fp:")]
    assert len(fingerprint_uids) == 1

    fingerprint_event = next(item for item in normalized if item.uid.startswith("fp:"))
    fp1 = build_fingerprint_uid(
        title=fingerprint_event.title,
        start_at_utc=fingerprint_event.start_at_utc,
        end_at_utc=fingerprint_event.end_at_utc,
    )
    fp2 = build_fingerprint_uid(
        title=fingerprint_event.title,
        start_at_utc=fingerprint_event.start_at_utc,
        end_at_utc=fingerprint_event.end_at_utc,
    )
    assert fp1 == fp2


def test_infer_course_label_regex_and_fallback() -> None:
    assert infer_course_label("CSE 151A Final", "") == "CSE 151A"
    assert infer_course_label("CSE151A Quiz 1", "") == "CSE 151A"
    assert infer_course_label("CHEM 11 Lecture", "") == "CHEM 11"
    assert infer_course_label("Week #5 Reflection [CGS124_WI26_A00]", "Please answer in 150 words") == "CGS 124"
    assert (
        infer_course_label(
            "Quiz 1- Requires Respondus LockDown Browser [CSE151A_WI26_A00]",
            "Use lockdown browser",
        )
        == "CSE 151A"
    )
    assert infer_course_label("RQ07 [CSE100_WI26_A00]", "") == "CSE 100"
    assert infer_course_label("Week #5 Reflection", "Please answer in 150 words or more.") == "Unknown"
    assert infer_course_label("Reading 1", "Course reading notes.") == "Unknown"
    assert infer_course_label("Lecture 2", "Main topic introduction.") == "Unknown"
    assert infer_course_label("Module 3", "Class overview") == "Unknown"
    assert infer_course_label("General Event", "No class code") == "Unknown"
