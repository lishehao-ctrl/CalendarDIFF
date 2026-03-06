from __future__ import annotations

import base64
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from scripts.semester_demo_scenarios import build_scenario_manifest, write_scenario_manifest


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def _wait_until_ready(client: httpx.Client, *, timeout_seconds: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            response = client.get("/__admin/state", timeout=1.0)
            if response.status_code == 200:
                payload = response.json()
                if isinstance(payload, dict) and "mode" in payload:
                    return
        except Exception:
            pass
        time.sleep(0.1)
    raise AssertionError("fake source provider did not become ready")


def _decode_base64url(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", errors="replace")


def test_fake_source_provider_semester_batch_contract(tmp_path: Path) -> None:
    manifest = build_scenario_manifest(seed=20260305)
    manifest_path = tmp_path / "scenario_manifest.json"
    write_scenario_manifest(manifest_path, manifest)

    port = _find_free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "scripts/fake_source_provider.py",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--scenario-manifest",
            str(manifest_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}") as client:
            _wait_until_ready(client)

            initial_state = client.get("/__admin/state").json()
            assert initial_state["mode"] == "semester"
            assert initial_state["batch"] == 0

            set_batch = client.post(
                "/__admin/semester-batch",
                json={"semester": 1, "batch": 1, "run_tag": "semester-smoke"},
            ).json()
            assert set_batch["semester"] == 1
            assert set_batch["batch"] == 1
            assert set_batch["scenario"]["ics_count"] == 10
            assert set_batch["scenario"]["gmail_count"] == 10

            first_ics = client.get("/ics/calendar.ics")
            assert first_ics.status_code == 200
            assert first_ics.text.count("BEGIN:VEVENT") == 10
            assert "Semester: 1" in first_ics.text

            profile = client.get("/gmail/v1/users/me/profile").json()
            assert isinstance(profile.get("historyId"), str)

            history = client.get("/gmail/v1/users/me/history", params={"startHistoryId": "100000"}).json()
            assert isinstance(history.get("history"), list)
            assert history["history"]
            message_id = history["history"][0]["messagesAdded"][0]["message"]["id"]

            message = client.get(f"/gmail/v1/users/me/messages/{message_id}").json()
            assert message["id"] == message_id
            body_data = message["payload"]["body"]["data"]
            decoded_body = _decode_base64url(body_data)
            assert "Due timestamp:" in decoded_body

            state = client.get("/__admin/state").json()
            batch_counter = state["semester_batch_counters"]["s01b01"]
            assert batch_counter["ics_fetch_count"] >= 1
            assert batch_counter["ics_event_served_count"] >= 10
            assert batch_counter["gmail_history_count"] >= 1
            assert batch_counter["gmail_history_message_count"] >= 10
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
