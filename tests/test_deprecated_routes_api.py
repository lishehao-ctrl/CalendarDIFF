from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/v1/sources", None),
        ("GET", "/v1/status", None),
        ("GET", "/v1/review_candidates", None),
        ("POST", "/v1/review_candidates/abc/route", {"route": "review"}),
        ("GET", "/v1/changes/feed", None),
        ("GET", "/v1/changes?input_id=1", None),
        ("GET", "/v1/snapshots?input_id=1", None),
        ("POST", "/v1/user", {"notify_email": "legacy@example.com"}),
        ("GET", "/v1/user/terms", None),
        ("POST", "/v1/user/terms", {}),
        ("PATCH", "/v1/user/terms/1", {}),
        ("POST", "/v1/inputs/ics", {"url": "https://example.com/legacy.ics"}),
        ("GET", "/v1/inputs/1/runs?limit=1", None),
        ("GET", "/v1/inputs/1/deadlines", None),
        ("GET", "/v1/inputs/1/changes", None),
        ("GET", "/v1/inputs/1/snapshots", None),
        ("PATCH", "/v1/inputs/1/changes/1/viewed", {"viewed": True}),
        ("GET", "/v1/inputs/1/changes/1/evidence/before/preview", None),
        ("GET", "/v1/inputs/1/changes/1/evidence/before/download", None),
        ("GET", "/v1/changes/1/evidence/before/download", None),
        ("GET", "/v1/emails/queue?route=review", None),
        ("POST", "/v1/emails/email-1/route", {"route": "archive"}),
        ("POST", "/v1/emails/email-1/mark_viewed", None),
        ("POST", "/v1/emails/email-1/apply", {}),
        ("GET", "/v1/notification_prefs", None),
        ("POST", "/v1/notifications/send_digest_now", {}),
        ("POST", "/v1/dev/inject_notify", {"change_id": 1}),
    ],
)
def test_removed_routes_return_404(client, method: str, path: str, payload: dict | None) -> None:
    headers = {"X-API-Key": "test-api-key"}
    response = client.request(method, path, headers=headers, json=payload)
    assert response.status_code == 404
