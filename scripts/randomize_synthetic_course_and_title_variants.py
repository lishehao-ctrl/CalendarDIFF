#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from pathlib import Path

COURSE_FULL_RE = re.compile(r"^\s*([A-Za-z]{2,6})\s*([0-9]{1,3})([A-Za-z]{0,2})\s*$")
SUMMARY_SPLIT_RE = re.compile(r"^\s*([A-Za-z]{2,6}\s*\d{1,3}[A-Za-z]{0,2})\s*(.*)$")

MAIL_SUBJECT_VARIANTS: dict[str, list[str]] = {
    "Deadline update for assignment": [
        "Assignment deadline adjusted",
        "Deadline revision for assignment",
        "Assignment due-date window updated",
        "Assignment deadline policy refresh",
        "Deadline alignment notice for assignment",
    ],
    "Midterm logistics and timing": [
        "Midterm logistics + timing update",
        "Midterm timing and room logistics",
        "Midterm schedule logistics memo",
        "Midterm execution timeline update",
    ],
    "Section or OH schedule change": [
        "Section / OH schedule adjustment",
        "OH and section timetable change",
        "Schedule revision for section + office hours",
        "Section meeting/OH schedule refresh",
    ],
    "New assignment posted": [
        "New assignment now available",
        "Assignment release notice",
        "Assignment posted with workflow details",
        "Fresh assignment publish update",
    ],
    "Action required from enrolled students": [
        "Action required for enrolled students",
        "Required follow-up for enrolled students",
        "Student action needed (enrolled)",
        "Enrollment-linked action request",
    ],
    "Important course announcement": [
        "Important course announcement update",
        "Course announcement (important)",
        "High-priority course announcement",
        "Important announcement for this course",
    ],
    "Grade release and regrade timeline": [
        "Grade release + regrade window",
        "Grading release and regrade timeline",
        "Grade publication / regrade schedule",
        "Grade release timing and regrade policy",
    ],
    "Daily digest and thread summary": [
        "Daily digest + thread summary",
        "Thread digest and daily summary",
        "Daily discussion digest notice",
        "Digest update for daily thread activity",
    ],
    "Gradebook updated notice": [
        "Gradebook update notice",
        "Gradebook refreshed",
        "Gradebook status update",
        "Gradebook entries updated",
    ],
    "Weekly course announcement": [
        "Weekly course announcement update",
        "Course weekly bulletin",
        "Weekly announcement for this course",
        "Weekly operations announcement",
    ],
    "Campus admin update": [
        "Campus admin operations update",
        "Campus administration update",
        "Administrative campus notice",
        "Campus admin bulletin",
    ],
}

ICS_TAIL_VARIANTS: dict[str, list[str]] = {
    "Weekly Lecture": [
        "Weekly Lecture",
        "weekly lecture block",
        "Weekly lecture session",
        "weekly class sync",
        "Lecture cadence block",
    ],
    "Assignment Deadline": [
        "Assignment Deadline",
        "assignment due window",
        "Assignment DDL milestone",
        "deliverable deadline marker",
        "assignment due checkpoint",
    ],
    "Existing Task": [
        "Existing Task",
        "current task item",
        "ongoing task record",
        "active task entry",
    ],
    "作业截止时间更新": [
        "作业截止时间更新",
        "作业DDL更新",
        "作业截止调整",
        "作业时间窗口更新",
    ],
}



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Randomize synthetic mail/ics course aliases and title expressions.")
    parser.add_argument(
        "--dataset-root",
        default="data/synthetic/v2_ddlchange_160",
        help="Dataset root path.",
    )
    return parser.parse_args()



def _seed(parts: tuple[str, ...]) -> int:
    joined = "||".join(parts)
    digest = hashlib.sha256(joined.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")



def _rng(*parts: str) -> random.Random:
    return random.Random(_seed(parts))



def _random_case(text: str, *, rng: random.Random) -> str:
    out: list[str] = []
    for ch in text:
        if ch.isalpha():
            out.append(ch.upper() if rng.random() < 0.5 else ch.lower())
        else:
            out.append(ch)
    return "".join(out)



def _variant_course_label(label: str, *, salt: str) -> str:
    match = COURSE_FULL_RE.match(label)
    if not match:
        return label

    prefix, number, suffix = match.groups()
    rng = _rng("course", salt, label)
    prefix_v = _random_case(prefix, rng=rng)
    suffix_v = _random_case(suffix, rng=rng)

    sep1 = rng.choices(["", " ", "_", "-"], weights=[0.2, 0.35, 0.3, 0.15], k=1)[0]
    sep2 = ""
    if suffix_v:
        sep2 = rng.choices(["", "_", "-", " "], weights=[0.55, 0.2, 0.15, 0.1], k=1)[0]

    return f"{prefix_v}{sep1}{number}{sep2}{suffix_v}"



def _build_course_aliases(label: str, *, seed_key: str, count: int = 4) -> list[str]:
    aliases: list[str] = []
    for idx in range(count * 3):
        alias = _variant_course_label(label, salt=f"{seed_key}:{idx}")
        if alias not in aliases:
            aliases.append(alias)
        if len(aliases) >= count:
            break
    if not aliases:
        aliases = [label]
    while len(aliases) < count:
        aliases.append(aliases[-1])
    return aliases



def _course_match_pattern(label: str) -> re.Pattern[str]:
    match = COURSE_FULL_RE.match(label)
    if not match:
        return re.compile(re.escape(label))

    prefix, number, suffix = match.groups()
    prefix_p = re.escape(prefix)
    number_p = re.escape(number)
    suffix_p = re.escape(suffix)

    if suffix:
        pattern = rf"(?<![A-Za-z0-9]){prefix_p}\s*[_-]?\s*{number_p}\s*[_-]?\s*{suffix_p}(?![A-Za-z0-9])"
    else:
        pattern = rf"(?<![A-Za-z0-9]){prefix_p}\s*[_-]?\s*{number_p}(?![A-Za-z0-9])"
    return re.compile(pattern, flags=re.IGNORECASE)



def _replace_course_cycle(text: str, *, canonical_label: str, aliases: list[str], count: int | None = None) -> str:
    if not aliases:
        return text
    pattern = _course_match_pattern(canonical_label)
    idx = 0

    def repl(_: re.Match[str]) -> str:
        nonlocal idx
        value = aliases[idx % len(aliases)]
        idx += 1
        return value

    if count is None:
        return pattern.sub(repl, text)
    return pattern.sub(repl, text, count=count)



def _mail_subject_tail_variant(tail: str, *, seed_key: str) -> str:
    options = MAIL_SUBJECT_VARIANTS.get(tail)
    if not options:
        # Fallback keeps semantics while varying surface form.
        options = [tail, f"{tail} (updated)", f"Update: {tail}"]
    rng = _rng("mail-tail", seed_key, tail)
    return rng.choice(options)



def _ics_tail_variant(tail: str, *, seed_key: str) -> str:
    options = ICS_TAIL_VARIANTS.get(tail)
    if not options:
        options = [tail, f"{tail} update"]
    rng = _rng("ics-tail", seed_key, tail)
    return rng.choice(options)



def rewrite_mail(raw_mail_path: Path) -> int:
    rewritten = 0
    rows: list[dict] = []
    with raw_mail_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            subject = str(row.get("subject") or "")
            subject_match = re.match(r"^\[([^\]]+)\]\s*(.*)$", subject)
            if not subject_match:
                rows.append(row)
                continue

            canonical_course = subject_match.group(1).strip()
            subject_tail = subject_match.group(2).strip()
            email_id = str(row.get("email_id") or "")
            aliases = _build_course_aliases(canonical_course, seed_key=email_id, count=5)

            row["subject"] = f"[{aliases[0]}] {_mail_subject_tail_variant(subject_tail, seed_key=email_id)}"

            from_value = str(row.get("from") or "")
            row["from"] = _replace_course_cycle(
                from_value,
                canonical_label=canonical_course,
                aliases=[aliases[1]],
                count=1,
            )

            body_text = str(row.get("body_text") or "")
            row["body_text"] = _replace_course_cycle(
                body_text,
                canonical_label=canonical_course,
                aliases=[aliases[2], aliases[3], aliases[4]],
                count=None,
            )

            rows.append(row)
            rewritten += 1

    with raw_mail_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    return rewritten



def _rewrite_event_block(block_lines: list[str], *, file_key: str) -> list[str]:
    uid = ""
    summary_idx = None
    summary_value = ""
    description_idx = None
    description_value = ""

    for idx, line in enumerate(block_lines):
        if line.startswith("UID:"):
            uid = line[4:].strip()
        elif line.startswith("SUMMARY:"):
            summary_idx = idx
            summary_value = line[len("SUMMARY:") :].strip()
        elif line.startswith("DESCRIPTION:"):
            description_idx = idx
            description_value = line[len("DESCRIPTION:") :]

    if summary_idx is None or not summary_value:
        return block_lines

    sm = SUMMARY_SPLIT_RE.match(summary_value)
    if not sm:
        return block_lines

    course_label = sm.group(1).strip()
    title_tail = sm.group(2).strip() or "Weekly Lecture"

    event_key = uid or f"{file_key}:{summary_value}"
    aliases = _build_course_aliases(course_label, seed_key=f"ics:{event_key}", count=3)
    new_tail = _ics_tail_variant(title_tail, seed_key=f"ics:{event_key}")
    new_summary = f"{aliases[0]} {new_tail}".strip()

    block_lines[summary_idx] = f"SUMMARY:{new_summary}"

    if description_idx is not None:
        desc = description_value
        if summary_value in desc:
            desc = desc.replace(summary_value, new_summary)
        desc = _replace_course_cycle(
            desc,
            canonical_label=course_label,
            aliases=[aliases[1], aliases[2], aliases[0]],
            count=None,
        )
        block_lines[description_idx] = f"DESCRIPTION:{desc}"

    return block_lines



def rewrite_ics_pairs(ics_pairs_dir: Path) -> int:
    rewritten_files = 0
    for path in sorted(ics_pairs_dir.glob("*.ics")):
        lines = path.read_text(encoding="utf-8").splitlines()
        out_lines: list[str] = []
        in_event = False
        event_lines: list[str] = []

        for line in lines:
            if line == "BEGIN:VEVENT":
                in_event = True
                event_lines = [line]
                continue
            if in_event:
                event_lines.append(line)
                if line == "END:VEVENT":
                    out_lines.extend(_rewrite_event_block(event_lines, file_key=path.name))
                    in_event = False
                    event_lines = []
                continue
            out_lines.append(line)

        if in_event and event_lines:
            out_lines.extend(event_lines)

        content = "\n".join(out_lines).rstrip("\n") + "\n"
        path.write_text(content, encoding="utf-8")
        rewritten_files += 1

    return rewritten_files



def main() -> int:
    args = parse_args()
    dataset_root = Path(args.dataset_root)
    mail_raw_path = dataset_root / "mail" / "raw_mail_120.jsonl"
    ics_pairs_dir = dataset_root / "ics" / "pairs"

    if not mail_raw_path.is_file():
        raise SystemExit(f"missing mail raw file: {mail_raw_path}")
    if not ics_pairs_dir.is_dir():
        raise SystemExit(f"missing ics pairs dir: {ics_pairs_dir}")

    rewritten_mail = rewrite_mail(mail_raw_path)
    rewritten_ics = rewrite_ics_pairs(ics_pairs_dir)

    print(f"rewritten_mail_rows={rewritten_mail}")
    print(f"rewritten_ics_files={rewritten_ics}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
