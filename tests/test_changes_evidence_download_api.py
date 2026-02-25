from __future__ import annotations


def test_download_change_evidence_route_removed(client, initialized_user) -> None:
    headers = {"X-API-Key": "test-api-key"}
    response = client.get("/v1/inputs/1/changes/1/evidence/before/download", headers=headers)
    assert response.status_code == 404

