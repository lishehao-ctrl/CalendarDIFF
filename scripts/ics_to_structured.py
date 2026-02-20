#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.modules.sync.deadline_engine import ICSDeadlineEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert an ICS file to structured JSON output")
    parser.add_argument("--input", required=True, help="Path to input ICS file")
    parser.add_argument("--output", required=False, help="Path to output JSON file")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON with indentation")
    return parser.parse_args()


def build_payload(input_path: Path) -> dict[str, object]:
    content = input_path.read_bytes()
    engine = ICSDeadlineEngine()
    courses = engine.parse_and_group(content)

    total_deadlines = sum(len(course.deadlines) for course in courses)

    return {
        "source_file": str(input_path),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "course_count": len(courses),
        "total_deadlines": total_deadlines,
        "courses": [
            {
                "course_label": course.course_label,
                "deadline_count": len(course.deadlines),
                "deadlines": [
                    {
                        "uid": deadline.uid,
                        "title": deadline.title,
                        "ddl_type": deadline.ddl_type.value,
                        "start_at_utc": deadline.start_at_utc.isoformat(),
                        "end_at_utc": deadline.end_at_utc.isoformat(),
                    }
                    for deadline in course.deadlines
                ],
            }
            for course in courses
        ],
    }


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
