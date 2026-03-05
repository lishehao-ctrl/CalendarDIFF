from __future__ import annotations

import base64
import socket
import subprocess
import sys
import time

import httpx


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
                if isinstance(payload, dict) and "round" in payload:
                    return
        except Exception:
            pass
        time.sleep(0.1)
    raise AssertionError("fake source provider did not become ready")


def _decode_base64url(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", errors="replace")


def test_fake_source_provider_contract() -> None:
    port = _find_free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "scripts/fake_source_provider.py",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}") as client:
            _wait_until_ready(client)

            initial_state = client.get("/__admin/state").json()
            assert initial_state["round"] == 0

            first_ics = client.get("/ics/calendar.ics")
            assert first_ics.status_code == 200
            assert "BEGIN:VCALENDAR" in first_ics.text
            etag = first_ics.headers.get("etag")
            assert etag

            second_ics = client.get("/ics/calendar.ics", headers={"If-None-Match": etag})
            assert second_ics.status_code == 304

            set_round = client.post("/__admin/round", json={"round": 1}).json()
            assert set_round["round"] == 1

            profile = client.get("/gmail/v1/users/me/profile").json()
            assert profile["historyId"] == "110"

            history = client.get("/gmail/v1/users/me/history", params={"startHistoryId": "100"}).json()
            assert history["historyId"] == "110"
            message_id = history["history"][0]["messagesAdded"][0]["message"]["id"]

            message = client.get(f"/gmail/v1/users/me/messages/{message_id}").json()
            assert message["id"] == message_id
            assert "INBOX" in message["labelIds"]
            decoded_body = _decode_base64url(message["payload"]["body"]["data"])
            assert "CSE8A" in decoded_body

            state = client.get("/__admin/state").json()
            assert state["counters"]["ics_fetch_count"] >= 2
            assert state["counters"]["gmail_profile_count"] >= 1
            assert state["counters"]["gmail_history_count"] >= 1
            assert state["counters"]["gmail_message_count"] >= 1

            tagged = client.post("/__admin/round", json={"round": 1, "run_tag": "smoke-tag"}).json()
            assert tagged["round"] == 1
            assert tagged["run_tag"] == "smoke-tag"

            keep_tag = client.post("/__admin/round", json={"round": 2}).json()
            assert keep_tag["round"] == 2
            assert keep_tag["run_tag"] == "smoke-tag"

            tagged_history = client.get("/gmail/v1/users/me/history", params={"startHistoryId": "110"}).json()
            tagged_message_id = tagged_history["history"][0]["messagesAdded"][0]["message"]["id"]
            tagged_message = client.get(f"/gmail/v1/users/me/messages/{tagged_message_id}").json()
            assert "smoke-tag" in tagged_message["snippet"]
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
