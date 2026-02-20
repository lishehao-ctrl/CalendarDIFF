from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SAMPLE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Deadline Diff//EN
BEGIN:VEVENT
UID:item-1
DTSTART:20260224T090000Z
DTEND:20260224T100000Z
SUMMARY:Week #5 Reflection [CGS124_WI26_A00]
DESCRIPTION:Please answer in 150 words or more.
END:VEVENT
BEGIN:VEVENT
UID:item-2
DTSTART:20260225T090000Z
DTEND:20260225T100000Z
SUMMARY:Quiz 1 [CSE151A_WI26_A00]
DESCRIPTION:Respondus required.
END:VEVENT
END:VCALENDAR
"""


def test_cli_outputs_structured_json_to_stdout(tmp_path: Path) -> None:
    ics_path = tmp_path / "sample.ics"
    ics_path.write_text(SAMPLE_ICS, encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/ics_to_structured.py",
            "--input",
            str(ics_path),
            "--pretty",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)

    assert payload["source_file"].endswith("sample.ics")
    assert payload["course_count"] == 2
    assert payload["total_deadlines"] == 2

    course_labels = {course["course_label"] for course in payload["courses"]}
    assert course_labels == {"CGS 124", "CSE 151A"}

    for course in payload["courses"]:
        assert "deadline_count" in course
        for item in course["deadlines"]:
            assert {"uid", "title", "ddl_type", "start_at_utc", "end_at_utc"}.issubset(item.keys())


def test_cli_writes_to_output_file(tmp_path: Path) -> None:
    ics_path = tmp_path / "sample.ics"
    output_path = tmp_path / "output" / "structured.json"
    ics_path.write_text(SAMPLE_ICS, encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/ics_to_structured.py",
            "--input",
            str(ics_path),
            "--output",
            str(output_path),
            "--pretty",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert output_path.is_file()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["total_deadlines"] == 2


def test_cli_returns_error_on_missing_file(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.ics"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/ics_to_structured.py",
            "--input",
            str(missing_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Input file not found" in result.stderr
