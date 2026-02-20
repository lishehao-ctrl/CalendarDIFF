from __future__ import annotations

from app.modules.sync.deadline_engine import DDLType, ICSDeadlineEngine


SAMPLE_ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Deadline Diff//EN
BEGIN:VEVENT
UID:cse-hw-1
DTSTART:20260224T090000Z
DTEND:20260224T100000Z
SUMMARY:CSE 151A Homework 1
DESCRIPTION:submit to portal
END:VEVENT
BEGIN:VEVENT
UID:cse-quiz-1
DTSTART:20260225T090000Z
DTEND:20260225T093000Z
SUMMARY:CSE151A Quiz 1
DESCRIPTION:in class
END:VEVENT
BEGIN:VEVENT
UID:math-project
DTSTART:20260226T090000Z
DTEND:20260226T100000Z
SUMMARY:MATH 20A Project Milestone
DESCRIPTION:proposal checkpoint
END:VEVENT
BEGIN:VEVENT
UID:cse-rq-7
DTSTART:20260226T120000Z
DTEND:20260226T123000Z
SUMMARY:RQ07 [CSE100_WI26_A00]
DESCRIPTION:Reading quiz
END:VEVENT
BEGIN:VEVENT
UID:cgs-reflection-5
DTSTART:20260227T120000Z
DTEND:20260227T123000Z
SUMMARY:Week #5 Reflection [CGS124_WI26_A00]
DESCRIPTION:Please answer in 150 words or more.
END:VEVENT
BEGIN:VEVENT
DTSTART:20260227T090000Z
DTEND:20260227T100000Z
SUMMARY:General Deadline
DESCRIPTION:no course info
END:VEVENT
END:VCALENDAR
"""


def test_deadline_engine_outputs_courses_and_various_ddls() -> None:
    engine = ICSDeadlineEngine()

    grouped = engine.parse_and_group(SAMPLE_ICS)

    assert len(grouped) == 5

    by_course = {group.course_label: group for group in grouped}
    assert "CSE 151A" in by_course
    assert "CSE 100" in by_course
    assert "CGS 124" in by_course
    assert "MATH 20A" in by_course
    assert "Unknown" in by_course

    cse_types = {item.ddl_type for item in by_course["CSE 151A"].deadlines}
    assert DDLType.ASSIGNMENT in cse_types
    assert DDLType.QUIZ in cse_types

    cse100_types = {item.ddl_type for item in by_course["CSE 100"].deadlines}
    assert cse100_types == {DDLType.QUIZ}

    cgs124_items = by_course["CGS 124"].deadlines
    assert len(cgs124_items) == 1
    assert cgs124_items[0].ddl_type == DDLType.OTHER

    math_types = {item.ddl_type for item in by_course["MATH 20A"].deadlines}
    assert math_types == {DDLType.PROJECT}

    unknown_items = by_course["Unknown"].deadlines
    assert len(unknown_items) == 1
    assert unknown_items[0].ddl_type == DDLType.OTHER
    assert unknown_items[0].uid.startswith("fp:")
