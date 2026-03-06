#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime, parsedate_to_datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROUND_IDS = (0, 1, 2, 3)


@dataclass(frozen=True)
class RoundScenario:
    round_id: int
    difficulty: str
    alias_profile: str
    course_label: str
    title: str
    subject: str
    due_iso: str
    message_id: str | None
    body_text: str


@dataclass(frozen=True)
class SemesterBatchScenario:
    semester: int
    batch: int
    global_batch: int
    start_iso: str
    ics_events: list[dict[str, Any]]
    gmail_messages: list[dict[str, Any]]


SCENARIOS: dict[int, RoundScenario] = {
    0: RoundScenario(
        round_id=0,
        difficulty="baseline",
        alias_profile="none",
        course_label="CSE8A",
        title="CSE8A HW1 Deadline",
        subject="CSE8A HW1 Deadline",
        due_iso="2026-03-10T23:59:00Z",
        message_id=None,
        body_text="Baseline round with no new Gmail history records.",
    ),
    1: RoundScenario(
        round_id=1,
        difficulty="simple",
        alias_profile="canonical",
        course_label="CSE8A",
        title="CSE8A HW1 Deadline",
        subject="CSE8A HW1 Deadline",
        due_iso="2026-03-10T23:59:00Z",
        message_id="gmail-r1-msg",
        body_text=(
            "Course: CSE8A.\n"
            "Homework 1 deadline is 2026-03-10T23:59:00Z.\n"
            "Submit on Gradescope before the due time."
        ),
    ),
    2: RoundScenario(
        round_id=2,
        difficulty="medium",
        alias_profile="updated-wording",
        course_label="CSE 8A",
        title="[Update] CSE 8A HW1 Deadline",
        subject="Re: Update cse_8a hw1 deadline moved",
        due_iso="2026-03-11T21:00:00Z",
        message_id="gmail-r2-msg",
        body_text=(
            "Update notice for CSE 8A.\n"
            "HW1 timeline was adjusted after grading infra maintenance.\n"
            "New due timestamp: 2026-03-11T21:00:00Z."
        ),
    ),
    3: RoundScenario(
        round_id=3,
        difficulty="alias-heavy",
        alias_profile="multi-alias-same-subject",
        course_label="CSE-8A",
        title="Fwd: cSe_8A HW1 deadline",
        subject="[Reminder] CSE8A hw-1 DEADLINE",
        due_iso="2026-03-12T20:30:00Z",
        message_id="gmail-r3-msg",
        body_text=(
            "Reminder for the same course entity: CSE8A / cSe_8A / CSE 8A.\n"
            "HW-1 final timestamp is 2026-03-12T20:30:00Z.\n"
            "Treat all aliases above as the same subject."
        ),
    ),
}


def _parse_iso(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    return parsed.astimezone(UTC)


def _to_epoch_ms(value: str) -> str:
    return str(int(_parse_iso(value).timestamp() * 1000))


def _to_base64url(text: str) -> str:
    encoded = base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")
    return encoded.rstrip("=")


def _history_id_for_round(round_id: int) -> str:
    return {0: "100", 1: "110", 2: "120", 3: "130"}[round_id]


def _history_id_for_global_batch(global_batch: int) -> str:
    return str(100000 + (global_batch * 10))


def _messages_since_round(start_history_id: str | None, current_round: int) -> list[str]:
    if current_round <= 0:
        return []
    try:
        start = int(start_history_id) if start_history_id is not None else 0
    except ValueError:
        start = 0

    timeline = [
        (110, SCENARIOS[1].message_id),
        (120, SCENARIOS[2].message_id),
        (130, SCENARIOS[3].message_id),
    ]
    current_history = int(_history_id_for_round(current_round))
    out: list[str] = []
    for history_id, message_id in timeline:
        if message_id is None:
            continue
        if start < history_id <= current_history:
            out.append(message_id)
    return out


def _scenario_for_message_id(message_id: str) -> RoundScenario | None:
    for scenario in SCENARIOS.values():
        if scenario.message_id == message_id:
            return scenario
    return None


def _with_run_tag(text: str, run_tag: str) -> str:
    cleaned = run_tag.strip()
    if not cleaned:
        return text
    return f"{text} {cleaned}"


def _build_ics_content(round_id: int, *, run_tag: str) -> bytes:
    scenario = SCENARIOS[round_id]
    if round_id == 0:
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//CalendarDIFF//FakeSource//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            "END:VCALENDAR",
        ]
        return ("\r\n".join(lines) + "\r\n").encode("utf-8")

    uid = "cse8a-hw1-deadline"
    start_dt = _parse_iso(scenario.due_iso)
    end_dt = start_dt + timedelta(hours=1)
    summary = _with_run_tag(scenario.title, run_tag)
    description = (
        f"Round {scenario.round_id} ({scenario.difficulty}).\n"
        f"Primary alias: {scenario.course_label}.\n"
        "Subject variants for same entity: CSE8A / cSe_8A / CSE 8A.\n"
        f"Current due timestamp: {scenario.due_iso}.\n"
        "Keep this as the same assignment topic across rounds."
    )
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//CalendarDIFF//FakeSource//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"SUMMARY:{summary}",
        f"DTSTART:{start_dt.strftime('%Y%m%dT%H%M%SZ')}",
        f"DTEND:{end_dt.strftime('%Y%m%dT%H%M%SZ')}",
        f"DESCRIPTION:{description}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def _build_semester_ics_content(scenario: SemesterBatchScenario, *, run_tag: str) -> bytes:
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//CalendarDIFF//SemesterDemo//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for event in scenario.ics_events:
        due_iso = str(event.get("due_iso") or "")
        if not due_iso:
            continue
        start_dt = _parse_iso(due_iso)
        end_dt = start_dt + timedelta(hours=1)
        uid = str(event.get("event_uid") or event.get("event_id") or f"s{scenario.semester}b{scenario.batch}")
        title = _with_run_tag(str(event.get("title") or "Untitled Event"), run_tag)
        course = event.get("course")
        course_label = ""
        if isinstance(course, dict):
            course_label = str(course.get("label") or "").strip()
        event_type = str(event.get("event_type") or "deadline")
        event_index = int(event.get("event_index") or 1)
        description = (
            f"Semester: {scenario.semester}\n"
            f"Batch: {scenario.batch}\n"
            f"Course: {course_label}\n"
            f"Event type: {event_type}\n"
            f"Event index: {event_index}\n"
            f"Due timestamp: {due_iso}\n"
            "This ICS event belongs to deterministic semester demo workload."
        )
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"SUMMARY:{title}",
                f"DTSTART:{start_dt.strftime('%Y%m%dT%H%M%SZ')}",
                f"DTEND:{end_dt.strftime('%Y%m%dT%H%M%SZ')}",
                f"DESCRIPTION:{description}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def _load_semester_batch_scenarios(path: str | None) -> list[SemesterBatchScenario]:
    if path is None or not path.strip():
        return []
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("scenario manifest root must be an object")
    plans_raw = payload.get("plans")
    if not isinstance(plans_raw, list):
        raise ValueError("scenario manifest missing plans list")
    scenarios: list[SemesterBatchScenario] = []
    for semester_plan in plans_raw:
        if not isinstance(semester_plan, dict):
            continue
        semester = int(semester_plan.get("semester") or 0)
        batches_raw = semester_plan.get("batches")
        if not isinstance(batches_raw, list):
            continue
        for batch_plan in batches_raw:
            if not isinstance(batch_plan, dict):
                continue
            batch = int(batch_plan.get("batch") or 0)
            global_batch = int(batch_plan.get("global_batch") or 0)
            start_iso = str(batch_plan.get("start_iso") or "")
            ics_events = batch_plan.get("ics_events")
            gmail_messages = batch_plan.get("gmail_messages")
            if not isinstance(ics_events, list) or not isinstance(gmail_messages, list):
                continue
            scenarios.append(
                SemesterBatchScenario(
                    semester=semester,
                    batch=batch,
                    global_batch=global_batch,
                    start_iso=start_iso,
                    ics_events=[row for row in ics_events if isinstance(row, dict)],
                    gmail_messages=[row for row in gmail_messages if isinstance(row, dict)],
                )
            )
    scenarios.sort(key=lambda row: row.global_batch)
    return scenarios


class FakeSourceState:
    def __init__(self, *, semester_scenarios: list[SemesterBatchScenario] | None = None) -> None:
        self._lock = threading.Lock()
        self._semester_scenarios = semester_scenarios or []
        self.mode = "semester" if self._semester_scenarios else "round"
        self.round_id = 0
        self.semester = 1
        self.batch = 0
        self.run_tag = ""
        self.counters = {
            "ics_fetch_count": 0,
            "ics_event_served_count": 0,
            "gmail_profile_count": 0,
            "gmail_history_count": 0,
            "gmail_message_count": 0,
            "gmail_history_message_count": 0,
        }
        self.semester_batch_counters: dict[str, dict[str, int]] = {}
        self._scenarios_by_semester_batch: dict[tuple[int, int], SemesterBatchScenario] = {}
        self._scenarios_by_global_batch: dict[int, SemesterBatchScenario] = {}
        self._message_to_global_batch: dict[str, int] = {}
        for scenario in self._semester_scenarios:
            self._scenarios_by_semester_batch[(scenario.semester, scenario.batch)] = scenario
            self._scenarios_by_global_batch[scenario.global_batch] = scenario
            for message in scenario.gmail_messages:
                message_id = str(message.get("message_id") or "")
                if message_id:
                    self._message_to_global_batch[message_id] = scenario.global_batch

    def set_round(self, round_id: int) -> None:
        if round_id not in ROUND_IDS:
            raise ValueError(f"round must be one of {ROUND_IDS}")
        with self._lock:
            self.round_id = round_id

    def set_semester_batch(self, *, semester: int, batch: int) -> None:
        with self._lock:
            if batch < 0:
                raise ValueError("batch must be >= 0")
            if batch == 0:
                self.semester = semester
                self.batch = 0
                return
            if (semester, batch) not in self._scenarios_by_semester_batch:
                raise ValueError(f"unknown semester/batch: semester={semester} batch={batch}")
            self.semester = semester
            self.batch = batch

    def set_run_tag(self, run_tag: str) -> None:
        with self._lock:
            self.run_tag = run_tag.strip()[:48]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            scenario = self._scenarios_by_semester_batch.get((self.semester, self.batch))
            return {
                "mode": self.mode,
                "round": self.round_id,
                "semester": self.semester,
                "batch": self.batch,
                "run_tag": self.run_tag,
                "counters": dict(self.counters),
                "semester_batch_counters": dict(self.semester_batch_counters),
                "scenario": {
                    "global_batch": scenario.global_batch if scenario is not None else 0,
                    "ics_count": len(scenario.ics_events) if scenario is not None else 0,
                    "gmail_count": len(scenario.gmail_messages) if scenario is not None else 0,
                },
            }

    def increment(self, key: str) -> None:
        with self._lock:
            self.counters[key] = int(self.counters.get(key, 0)) + 1
            if self.mode != "semester":
                return
            counter_key = f"s{self.semester:02d}b{self.batch:02d}"
            target = self.semester_batch_counters.setdefault(
                counter_key,
                {
                    "ics_fetch_count": 0,
                    "ics_event_served_count": 0,
                    "gmail_profile_count": 0,
                    "gmail_history_count": 0,
                    "gmail_message_count": 0,
                    "gmail_history_message_count": 0,
                },
            )
            target[key] = int(target.get(key, 0)) + 1

    def add_counter(self, key: str, value: int) -> None:
        if value == 0:
            return
        with self._lock:
            self.counters[key] = int(self.counters.get(key, 0)) + int(value)
            if self.mode != "semester":
                return
            counter_key = f"s{self.semester:02d}b{self.batch:02d}"
            target = self.semester_batch_counters.setdefault(
                counter_key,
                {
                    "ics_fetch_count": 0,
                    "ics_event_served_count": 0,
                    "gmail_profile_count": 0,
                    "gmail_history_count": 0,
                    "gmail_message_count": 0,
                    "gmail_history_message_count": 0,
                },
            )
            target[key] = int(target.get(key, 0)) + int(value)

    def history_id_for_current(self) -> str:
        if self.mode != "semester":
            return _history_id_for_round(self.round_id)
        scenario = self._scenarios_by_semester_batch.get((self.semester, self.batch))
        if scenario is None:
            return _history_id_for_global_batch(0)
        return _history_id_for_global_batch(scenario.global_batch)

    def messages_since(self, start_history_id: str | None) -> list[str]:
        if self.mode != "semester":
            return _messages_since_round(start_history_id, self.round_id)
        try:
            start = int(start_history_id) if start_history_id is not None else 0
        except ValueError:
            start = 0
        scenario = self._scenarios_by_semester_batch.get((self.semester, self.batch))
        current_global = scenario.global_batch if scenario is not None else 0
        current_history = int(_history_id_for_global_batch(current_global))
        out: list[str] = []
        for global_batch in sorted(self._scenarios_by_global_batch):
            history_id = int(_history_id_for_global_batch(global_batch))
            if start < history_id <= current_history:
                batch_scenario = self._scenarios_by_global_batch[global_batch]
                for message in batch_scenario.gmail_messages:
                    message_id = str(message.get("message_id") or "")
                    if message_id:
                        out.append(message_id)
        return out

    def current_semester_scenario(self) -> SemesterBatchScenario | None:
        return self._scenarios_by_semester_batch.get((self.semester, self.batch))

    def scenario_for_message_id(self, message_id: str) -> tuple[SemesterBatchScenario | None, dict[str, Any] | None]:
        global_batch = self._message_to_global_batch.get(message_id)
        if global_batch is None:
            return None, None
        scenario = self._scenarios_by_global_batch.get(global_batch)
        if scenario is None:
            return None, None
        for message in scenario.gmail_messages:
            if str(message.get("message_id") or "") == message_id:
                return scenario, message
        return scenario, None

    def history_rows_for_message_ids(self, message_ids: list[str]) -> list[dict[str, Any]]:
        grouped: dict[int, list[str]] = {}
        for message_id in message_ids:
            global_batch = self._message_to_global_batch.get(message_id)
            if global_batch is None:
                continue
            grouped.setdefault(global_batch, []).append(message_id)
        rows: list[dict[str, Any]] = []
        for global_batch in sorted(grouped):
            rows.append(
                {
                    "id": _history_id_for_global_batch(global_batch),
                    "messagesAdded": [{"message": {"id": message_id}} for message_id in grouped[global_batch]],
                }
            )
        return rows


def create_handler(state: FakeSourceState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FakeSourceProvider/2.0"

        def _json_response(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _parse_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                return {}
            return payload if isinstance(payload, dict) else {}

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            if path == "/__admin/state":
                self._json_response(HTTPStatus.OK, state.snapshot())
                return

            if path == "/ics/calendar.ics":
                state.increment("ics_fetch_count")
                snapshot = state.snapshot()
                run_tag = str(snapshot.get("run_tag") or "")
                if state.mode == "semester":
                    semester = int(snapshot.get("semester") or 1)
                    batch = int(snapshot.get("batch") or 0)
                    semester_scenario = state.current_semester_scenario()
                    etag = f'"fake-ics-sem-{semester}-batch-{batch}"'
                    base_dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
                    last_modified_dt = base_dt + timedelta(days=(semester - 1) * 30 + batch)
                    content = (
                        _build_semester_ics_content(semester_scenario, run_tag=run_tag)
                        if semester_scenario is not None
                        else _build_ics_content(0, run_tag=run_tag)
                    )
                else:
                    round_id = int(snapshot["round"])
                    etag = f'"fake-ics-round-{round_id}"'
                    last_modified_dt = datetime(2026, 3, 1 + round_id, 12, 0, 0, tzinfo=UTC)
                    content = _build_ics_content(round_id, run_tag=run_tag)
                if state.mode == "semester" and semester_scenario is not None:
                    state.add_counter("ics_event_served_count", len(semester_scenario.ics_events))
                last_modified = format_datetime(last_modified_dt, usegmt=True)

                if_none_match = self.headers.get("If-None-Match")
                if if_none_match and if_none_match.strip() == etag:
                    self.send_response(HTTPStatus.NOT_MODIFIED)
                    self.send_header("ETag", etag)
                    self.send_header("Last-Modified", last_modified)
                    self.end_headers()
                    return

                if_modified_since = self.headers.get("If-Modified-Since")
                if if_modified_since:
                    try:
                        since_dt = parsedate_to_datetime(if_modified_since)
                        if since_dt.tzinfo is None:
                            since_dt = since_dt.replace(tzinfo=UTC)
                        if since_dt >= last_modified_dt:
                            self.send_response(HTTPStatus.NOT_MODIFIED)
                            self.send_header("ETag", etag)
                            self.send_header("Last-Modified", last_modified)
                            self.end_headers()
                            return
                    except Exception:
                        pass

                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/calendar; charset=utf-8")
                self.send_header("ETag", etag)
                self.send_header("Last-Modified", last_modified)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

            if path == "/gmail/v1/users/me/profile":
                state.increment("gmail_profile_count")
                payload: dict[str, Any] = {
                    "emailAddress": "fake.student@example.edu",
                    "historyId": state.history_id_for_current(),
                }
                self._json_response(HTTPStatus.OK, payload)
                return

            if path == "/gmail/v1/users/me/history":
                state.increment("gmail_history_count")
                start_history_id = query.get("startHistoryId", [None])[0]
                message_ids = state.messages_since(start_history_id)
                state.add_counter("gmail_history_message_count", len(message_ids))
                history_rows = state.history_rows_for_message_ids(message_ids)
                if state.mode != "semester":
                    history_rows = []
                    round_id = int(state.snapshot()["round"])
                    for message_id in message_ids:
                        history_rows.append(
                            {
                                "id": _history_id_for_round(round_id),
                                "messagesAdded": [{"message": {"id": message_id}}],
                            }
                        )
                history_payload: dict[str, Any] = {
                    "historyId": state.history_id_for_current(),
                    "history": history_rows,
                }
                self._json_response(HTTPStatus.OK, history_payload)
                return

            if path.startswith("/gmail/v1/users/me/messages/"):
                state.increment("gmail_message_count")
                message_id = path.rsplit("/", 1)[-1]
                run_tag = str(state.snapshot().get("run_tag") or "")

                if state.mode == "semester":
                    _, message = state.scenario_for_message_id(message_id)
                    if message is None:
                        self._json_response(HTTPStatus.NOT_FOUND, {"error": {"message": "message not found"}})
                        return
                    subject = _with_run_tag(str(message.get("subject") or "Untitled"), run_tag)
                    body_text = _with_run_tag(str(message.get("body_text") or ""), run_tag)
                    due_iso = str(message.get("due_iso") or datetime.now(UTC).isoformat())
                else:
                    round_scenario = _scenario_for_message_id(message_id)
                    if round_scenario is None:
                        self._json_response(HTTPStatus.NOT_FOUND, {"error": {"message": "message not found"}})
                        return
                    subject = _with_run_tag(round_scenario.subject, run_tag)
                    body_text = _with_run_tag(round_scenario.body_text, run_tag)
                    due_iso = round_scenario.due_iso

                body_data = _to_base64url(body_text)
                message_payload: dict[str, Any] = {
                    "id": message_id,
                    "threadId": f"thread-{message_id}",
                    "labelIds": ["INBOX", "CATEGORY_PERSONAL"],
                    "snippet": subject,
                    "historyId": state.history_id_for_current(),
                    "internalDate": _to_epoch_ms(due_iso),
                    "payload": {
                        "mimeType": "text/plain",
                        "headers": [
                            {"name": "Subject", "value": subject},
                            {"name": "From", "value": "Course Staff <staff@example.edu>"},
                        ],
                        "body": {
                            "size": len(body_text),
                            "data": body_data,
                        },
                    },
                }
                self._json_response(HTTPStatus.OK, message_payload)
                return

            if path == "/oauth2/auth":
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"fake oauth authorize endpoint")
                return

            self._json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            if path == "/__admin/round":
                payload = self._parse_json_body()
                round_raw = payload.get("round", query.get("round", [None])[0])
                has_run_tag = "run_tag" in payload or "run_tag" in query
                run_tag_raw = payload.get("run_tag", query.get("run_tag", [None])[0])
                try:
                    round_id = int(round_raw)
                    state.set_round(round_id)
                    if has_run_tag and isinstance(run_tag_raw, str):
                        state.set_run_tag(run_tag_raw)
                except Exception:
                    self._json_response(HTTPStatus.BAD_REQUEST, {"error": f"round must be one of {ROUND_IDS}"})
                    return
                self._json_response(HTTPStatus.OK, state.snapshot())
                return

            if path == "/__admin/semester-batch":
                payload = self._parse_json_body()
                semester_raw = payload.get("semester", query.get("semester", [None])[0])
                batch_raw = payload.get("batch", query.get("batch", [None])[0])
                has_run_tag = "run_tag" in payload or "run_tag" in query
                run_tag_raw = payload.get("run_tag", query.get("run_tag", [None])[0])
                try:
                    semester = int(semester_raw)
                    batch = int(batch_raw)
                    state.set_semester_batch(semester=semester, batch=batch)
                    if has_run_tag and isinstance(run_tag_raw, str):
                        state.set_run_tag(run_tag_raw)
                except Exception as exc:
                    self._json_response(
                        HTTPStatus.BAD_REQUEST,
                        {"error": f"invalid semester/batch pointer: {exc}"},
                    )
                    return
                self._json_response(HTTPStatus.OK, state.snapshot())
                return

            if path == "/oauth2/token":
                self._json_response(
                    HTTPStatus.OK,
                    {
                        "access_token": "fake-access-token",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                    },
                )
                return

            self._json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format
            del args

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run fake ICS/Gmail source provider for smoke tests.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind.")
    parser.add_argument(
        "--scenario-manifest",
        default=None,
        help="Optional semester demo scenario manifest JSON path.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    semester_scenarios = _load_semester_batch_scenarios(args.scenario_manifest)
    state = FakeSourceState(semester_scenarios=semester_scenarios)
    handler = create_handler(state)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    try:
        print(f"fake source provider listening on http://{args.host}:{args.port}", flush=True)
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
