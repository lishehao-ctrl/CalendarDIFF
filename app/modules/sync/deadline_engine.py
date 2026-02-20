from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.modules.sync.ics_parser import ICSParser
from app.modules.sync.normalizer import build_fingerprint_uid, infer_course_label
from app.modules.sync.types import RawICSEvent


class DDLType(str, Enum):
    ASSIGNMENT = "assignment"
    PROJECT = "project"
    QUIZ = "quiz"
    EXAM = "exam"
    LAB = "lab"
    DISCUSSION = "discussion"
    OTHER = "other"


@dataclass(frozen=True)
class DeadlineRecord:
    uid: str
    course_label: str
    title: str
    ddl_type: DDLType
    start_at_utc: datetime
    end_at_utc: datetime


@dataclass(frozen=True)
class CourseDeadlineGroup:
    course_label: str
    deadlines: list[DeadlineRecord]


class ICSDeadlineEngine:
    def __init__(self, parser: ICSParser | None = None) -> None:
        self._parser = parser or ICSParser()

    def parse_content(self, content: bytes) -> list[DeadlineRecord]:
        raw_events = self._parser.parse(content)
        return self._to_deadlines(raw_events)

    def group_by_course(self, deadlines: list[DeadlineRecord]) -> list[CourseDeadlineGroup]:
        grouped: dict[str, list[DeadlineRecord]] = defaultdict(list)
        for item in deadlines:
            grouped[item.course_label].append(item)

        groups: list[CourseDeadlineGroup] = []
        for course_label, items in grouped.items():
            sorted_items = sorted(items, key=lambda row: (row.start_at_utc, row.title, row.uid))
            groups.append(CourseDeadlineGroup(course_label=course_label, deadlines=sorted_items))

        return sorted(groups, key=lambda group: group.course_label)

    def parse_and_group(self, content: bytes) -> list[CourseDeadlineGroup]:
        deadlines = self.parse_content(content)
        return self.group_by_course(deadlines)

    def _to_deadlines(self, raw_events: list[RawICSEvent]) -> list[DeadlineRecord]:
        deduped: dict[str, DeadlineRecord] = {}
        for raw in raw_events:
            title = raw.summary.strip() or "Untitled"
            course_label = infer_course_label(raw.summary, raw.description)
            uid = raw.uid.strip() if raw.uid else ""
            if not uid:
                uid = build_fingerprint_uid(title=title, start_at_utc=raw.dtstart, end_at_utc=raw.dtend)

            deduped[uid] = DeadlineRecord(
                uid=uid,
                course_label=course_label,
                title=title,
                ddl_type=infer_ddl_type(raw.summary, raw.description),
                start_at_utc=raw.dtstart,
                end_at_utc=raw.dtend,
            )

        return sorted(deduped.values(), key=lambda row: (row.course_label, row.start_at_utc, row.title, row.uid))


def infer_ddl_type(summary: str, description: str) -> DDLType:
    text = f"{summary} {description}".lower()

    for ddl_type, regexes in DDL_PATTERNS:
        if any(regex.search(text) for regex in regexes):
            return ddl_type

    return DDLType.OTHER


def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, flags=re.IGNORECASE)


DDL_PATTERNS: tuple[tuple[DDLType, tuple[re.Pattern[str], ...]], ...] = (
    (DDLType.EXAM, (_compile(r"\b(midterm|final|exam|考试|期中|期末)\b"),)),
    (DDLType.QUIZ, (_compile(r"\b(quiz|测验|小测)\b"),)),
    (DDLType.PROJECT, (_compile(r"\b(project|milestone|capstone|项目|里程碑)\b"),)),
    (DDLType.ASSIGNMENT, (_compile(r"\b(hw\d*|homework|assignment|pset|作业|习题)\b"),)),
    (DDLType.LAB, (_compile(r"\b(lab|实验)\b"),)),
    (DDLType.DISCUSSION, (_compile(r"\b(discussion|论坛|讨论)\b"),)),
)
