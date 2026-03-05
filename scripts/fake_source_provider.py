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
            "Course: CSE8A.\\n"
            "Homework 1 deadline is 2026-03-10T23:59:00Z.\\n"
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
            "Update notice for CSE 8A.\\n"
            "HW1 timeline was adjusted after grading infra maintenance.\\n"
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
            "Reminder for the same course entity: CSE8A / cSe_8A / CSE 8A.\\n"
            "HW-1 final timestamp is 2026-03-12T20:30:00Z.\\n"
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


class FakeSourceState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.round_id = 0
        self.run_tag = ""
        self.counters = {
            "ics_fetch_count": 0,
            "gmail_profile_count": 0,
            "gmail_history_count": 0,
            "gmail_message_count": 0,
        }

    def set_round(self, round_id: int) -> None:
        if round_id not in ROUND_IDS:
            raise ValueError(f"round must be one of {ROUND_IDS}")
        with self._lock:
            self.round_id = round_id

    def set_run_tag(self, run_tag: str) -> None:
        with self._lock:
            self.run_tag = run_tag.strip()[:48]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "round": self.round_id,
                "run_tag": self.run_tag,
                "counters": dict(self.counters),
                "scenario": SCENARIOS[self.round_id].__dict__,
            }

    def increment(self, key: str) -> None:
        with self._lock:
            self.counters[key] = int(self.counters.get(key, 0)) + 1


def _history_id_for_round(round_id: int) -> str:
    return {0: "100", 1: "110", 2: "120", 3: "130"}[round_id]


def _messages_since(start_history_id: str | None, current_round: int) -> list[str]:
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
        f"Round {scenario.round_id} ({scenario.difficulty}).\\n"
        f"Primary alias: {scenario.course_label}.\\n"
        "Subject variants for same entity: CSE8A / cSe_8A / CSE 8A.\\n"
        f"Current due timestamp: {scenario.due_iso}.\\n"
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
    return ("\\r\\n".join(lines) + "\\r\\n").encode("utf-8")


def create_handler(state: FakeSourceState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FakeSourceProvider/1.0"

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
                round_id = int(snapshot["round"])
                run_tag = str(snapshot.get("run_tag") or "")
                etag = f'"fake-ics-round-{round_id}"'
                last_modified_dt = datetime(2026, 3, 1 + round_id, 12, 0, 0, tzinfo=UTC)
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

                content = _build_ics_content(round_id, run_tag=run_tag)
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
                round_id = int(state.snapshot()["round"])
                payload: dict[str, Any] = {
                    "emailAddress": "fake.student@example.edu",
                    "historyId": _history_id_for_round(round_id),
                }
                self._json_response(HTTPStatus.OK, payload)
                return

            if path == "/gmail/v1/users/me/history":
                state.increment("gmail_history_count")
                round_id = int(state.snapshot()["round"])
                start_history_id = query.get("startHistoryId", [None])[0]
                message_ids = _messages_since(start_history_id, round_id)
                history_rows = []
                for message_id in message_ids:
                    history_rows.append(
                        {
                            "id": _history_id_for_round(round_id),
                            "messagesAdded": [
                                {
                                    "message": {
                                        "id": message_id,
                                    }
                                }
                            ],
                        }
                    )
                history_payload: dict[str, Any] = {
                    "historyId": _history_id_for_round(round_id),
                    "history": history_rows,
                }
                self._json_response(HTTPStatus.OK, history_payload)
                return

            if path.startswith("/gmail/v1/users/me/messages/"):
                state.increment("gmail_message_count")
                message_id = path.rsplit("/", 1)[-1]
                scenario = _scenario_for_message_id(message_id)
                if scenario is None:
                    self._json_response(HTTPStatus.NOT_FOUND, {"error": {"message": "message not found"}})
                    return
                run_tag = str(state.snapshot().get("run_tag") or "")
                subject = _with_run_tag(scenario.subject, run_tag)
                body_text = _with_run_tag(scenario.body_text, run_tag)
                body_data = _to_base64url(body_text)
                message_payload: dict[str, Any] = {
                    "id": message_id,
                    "threadId": f"thread-{message_id}",
                    "labelIds": ["INBOX", "CATEGORY_PERSONAL"],
                    "snippet": subject,
                    "historyId": _history_id_for_round(scenario.round_id),
                    "internalDate": _to_epoch_ms(scenario.due_iso),
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
                snapshot = state.snapshot()
                self._json_response(HTTPStatus.OK, snapshot)
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    state = FakeSourceState()
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
