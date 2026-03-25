from __future__ import annotations

import app.modules.agents.gateway as agent_gateway
from app.modules.agents.gateway import AgentGatewayOrigin


def test_create_change_decision_proposal_uses_default_web_origin(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_create(*, db, user_id, change_id, origin_kind, origin_label, origin_request_id, language_code=None):  # type: ignore[no-untyped-def]
        captured["db"] = db
        captured["user_id"] = user_id
        captured["change_id"] = change_id
        captured["origin_kind"] = origin_kind
        captured["origin_label"] = origin_label
        captured["origin_request_id"] = origin_request_id
        captured["language_code"] = language_code
        return {"proposal_id": 77}

    monkeypatch.setattr(agent_gateway, "create_change_decision_proposal_with_origin", _fake_create)
    monkeypatch.setattr(
        agent_gateway,
        "serialize_agent_proposal",
        lambda row, language_code=None: {"proposal_id": row["proposal_id"]},
    )

    result = agent_gateway.create_change_decision_proposal(db="db", user_id=12, change_id=34)

    assert result == {"proposal_id": 77}
    assert captured == {
        "db": "db",
        "user_id": 12,
        "change_id": 34,
        "origin_kind": "web",
        "origin_label": "embedded_agent",
        "origin_request_id": None,
        "language_code": None,
    }


def test_create_approval_ticket_for_proposal_uses_explicit_origin(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_create(*, db, user_id, proposal_id, channel, origin_kind, origin_label, origin_request_id):  # type: ignore[no-untyped-def]
        captured["db"] = db
        captured["user_id"] = user_id
        captured["proposal_id"] = proposal_id
        captured["channel"] = channel
        captured["origin_kind"] = origin_kind
        captured["origin_label"] = origin_label
        captured["origin_request_id"] = origin_request_id
        return {"ticket_id": "ticket-1"}

    monkeypatch.setattr(agent_gateway, "create_approval_ticket", _fake_create)
    monkeypatch.setattr(agent_gateway, "serialize_approval_ticket", lambda row: {"ticket_id": row["ticket_id"]})

    result = agent_gateway.create_approval_ticket_for_proposal(
        db="db",
        user_id=45,
        proposal_id=78,
        channel="mcp",
        origin=AgentGatewayOrigin(kind="mcp", label="create_approval_ticket", request_id="req-9"),
    )

    assert result == {"ticket_id": "ticket-1"}
    assert captured == {
        "db": "db",
        "user_id": 45,
        "proposal_id": 78,
        "channel": "mcp",
        "origin_kind": "mcp",
        "origin_label": "create_approval_ticket",
        "origin_request_id": "req-9",
    }
