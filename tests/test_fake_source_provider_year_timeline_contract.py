from __future__ import annotations

import base64
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from tools.datasets.year_timeline_scenarios import build_year_timeline_manifest, write_year_timeline_manifest


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


def test_fake_source_provider_year_timeline_contract(tmp_path: Path) -> None:
    manifest = build_year_timeline_manifest()
    manifest_path = tmp_path / "year_timeline_manifest.json"
    write_year_timeline_manifest(manifest_path, manifest)
    final_batch = manifest.plans[-1].batches[-1]
    expected_by_id = {row.message_id: row for row in final_batch.gmail_messages}

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
            set_batch = client.post("/__admin/semester-batch", json={"semester": 4, "batch": 12, "run_tag": "year-smoke"}).json()
            assert set_batch["semester"] == 4
            assert set_batch["batch"] == 12
            assert set_batch["scenario"]["ics_count"] == 12
            assert set_batch["scenario"]["gmail_count"] == 12

            first_ics = client.get("/ics/calendar.ics")
            assert first_ics.status_code == 200
            assert first_ics.text.count("BEGIN:VEVENT") == 12

            previous_history_id = str(100000 + ((final_batch.global_batch - 1) * 10))
            history = client.get("/gmail/v1/users/me/history", params={"startHistoryId": previous_history_id}).json()
            assert history["history"]
            message_id = history["history"][0]["messagesAdded"][0]["message"]["id"]
            expected_message = expected_by_id[message_id]

            message = client.get(f"/gmail/v1/users/me/messages/{message_id}").json()
            headers = {row["name"]: row["value"] for row in message["payload"]["headers"]}
            assert headers["Subject"].startswith(expected_message.subject)
            assert headers["From"] == expected_message.from_header
            body_data = message["payload"]["body"]["data"]
            decoded_body = _decode_base64url(body_data)
            assert "Course:" in decoded_body
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_fake_source_provider_can_overlay_full_sim_email_bucket(tmp_path: Path) -> None:
    manifest = build_year_timeline_manifest()
    manifest_path = tmp_path / "year_timeline_manifest.json"
    write_year_timeline_manifest(manifest_path, manifest)
    full_sim_ids = set()
    for line in Path("tests/fixtures/private/email_pool/year_timeline_full_sim/samples.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        message_id = row.get("message_id")
        if isinstance(message_id, str) and message_id:
            full_sim_ids.add(message_id)

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
            "--email-bucket",
            "year_timeline_full_sim",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}") as client:
            _wait_until_ready(client)
            set_batch = client.post("/__admin/semester-batch", json={"semester": 4, "batch": 12}).json()
            assert set_batch["scenario"]["gmail_count"] > 12

            previous_history_id = str(100000 + ((manifest.plans[-1].batches[-1].global_batch - 1) * 10))
            history = client.get("/gmail/v1/users/me/history", params={"startHistoryId": previous_history_id}).json()
            assert history["history"]
            listed = client.get("/gmail/v1/users/me/messages", params={"labelIds": "INBOX"}).json()
            assert isinstance(listed.get("messages"), list)
            assert listed["messages"]
            message_id = history["history"][0]["messagesAdded"][0]["message"]["id"]
            assert message_id in full_sim_ids
            message = client.get(f"/gmail/v1/users/me/messages/{message_id}").json()
            headers = {row["name"]: row["value"] for row in message["payload"]["headers"]}
            assert isinstance(headers["Subject"], str) and headers["Subject"]
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
