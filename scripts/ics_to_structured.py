#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.modules.sync.ics_parser import ICSParser
from app.modules.sync.normalizer import build_fingerprint_uid, infer_course_label


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert an ICS file to structured JSON output")
    parser.add_argument("--input", required=True, help="Path to input ICS file")
    parser.add_argument("--output", required=False, help="Path to output JSON file")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON with indentation")
    return parser.parse_args()


def build_payload(input_path: Path) -> dict[str, object]:
    content = input_path.read_bytes()
    parser = ICSParser()
    raw_events = parser.parse(content)

    grouped: dict[str, list[dict[str, str]]] = {}
    for raw in raw_events:
        title = raw.summary.strip() or "Untitled"
        course_label = infer_course_label(raw.summary, raw.description)
        uid = (raw.uid or "").strip() or build_fingerprint_uid(title=title, start_at_utc=raw.dtstart, end_at_utc=raw.dtend)
        ddl_type = _infer_ddl_type(raw.summary, raw.description)
        grouped.setdefault(course_label, []).append(
            {
                "uid": uid,
                "title": title,
                "ddl_type": ddl_type,
                "start_at_utc": raw.dtstart.isoformat(),
                "end_at_utc": raw.dtend.isoformat(),
            }
        )

    courses = [
        {
            "course_label": course_label,
            "deadline_count": len(items),
            "deadlines": sorted(items, key=lambda row: (row["start_at_utc"], row["title"], row["uid"])),
        }
        for course_label, items in sorted(grouped.items(), key=lambda item: item[0])
    ]
    total_deadlines = sum(len(course["deadlines"]) for course in courses)

    return {
        "source_file": str(input_path),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "course_count": len(courses),
        "total_deadlines": total_deadlines,
        "courses": [
            course for course in courses
        ],
    }


def _infer_ddl_type(summary: str, description: str) -> str:
    text_pairs = (summary, description)
    for text in text_pairs:
        exam_or_quiz = _infer_exam_quiz(text)
        if exam_or_quiz is not None:
            return exam_or_quiz
        for ddl_type, patterns in _OTHER_DDL_PATTERNS:
            if any(pattern.search(text) for pattern in patterns):
                return ddl_type
    return "other"


def _infer_exam_quiz(text: str) -> str | None:
    candidates: list[tuple[int, str]] = []
    for ddl_type, pattern in _EXAM_QUIZ_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            candidates.append((match.start(), ddl_type))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


_EXAM_QUIZ_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("exam", re.compile(r"\b(midterm|final|exam|test|考试|期中|期末)\b", re.IGNORECASE)),
    ("quiz", re.compile(r"\b(quiz|测验|小测)\b", re.IGNORECASE)),
)


_OTHER_DDL_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    ("project", (re.compile(r"\b(project|milestone|capstone|项目|里程碑)\b", re.IGNORECASE),)),
    ("assignment", (re.compile(r"\b(hw\d*|homework|assignment|pset|作业|习题)\b", re.IGNORECASE),)),
    ("lab", (re.compile(r"\b(lab|实验)\b", re.IGNORECASE),)),
    ("discussion", (re.compile(r"\b(discussion|论坛|讨论)\b", re.IGNORECASE),)),
)


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)

    if not input_path.is_file():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1

    try:
        payload = build_payload(input_path)
    except Exception as exc:
        print(f"Failed to parse ICS: {exc}", file=sys.stderr)
        return 1

    indent = 2 if args.pretty else None
    serialized = json.dumps(payload, ensure_ascii=False, indent=indent)
    if args.pretty:
        serialized += "\n"

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(serialized, encoding="utf-8")
    else:
        sys.stdout.write(serialized)
        if not args.pretty:
            sys.stdout.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
