from __future__ import annotations

from datetime import datetime, timezone
import importlib

from app.db.models.shared import User

agent_router = importlib.import_module("app.modules.agents.router")


def _create_user(db_session, *, email: str) -> User:
    user = User(
        email=email,
        password_hash="hash",
        timezone_name="America/Los_Angeles",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_agent_command_plan_route_returns_structured_run(client, db_session, auth_headers, monkeypatch) -> None:
    user = _create_user(db_session, email="agent-command-plan@example.com")

    monkeypatch.setattr(
        agent_router,
        "plan_workspace_command_for_user",
        lambda **kwargs: {
            "command_id": "cmd-1",
            "owner_user_id": user.id,
            "input_text": kwargs["input_text"],
            "scope_kind": "workspace",
            "scope_id": None,
            "language_code": "en",
            "language_resolution_source": "explicit",
            "status": "planned",
            "status_reason": None,
            "plan": [
                {
                    "step_id": "step_1",
                    "title": "Review workspace",
                    "reason": "Need current context first.",
                    "tool_name": "get_workspace_context",
                    "target_kind": "workspace",
                    "args": {},
                    "depends_on": [],
                    "risk_level": "low",
                    "execution_boundary": "read_only",
                }
            ],
            "execution_results": [],
            "executed_at": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    response = client.post(
        "/agent/commands/plan",
        headers=auth_headers(client, user=user),
        json={"input_text": "review the workspace"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["command_id"] == "cmd-1"
    assert payload["status"] == "planned"
    assert payload["plan"][0]["tool_name"] == "get_workspace_context"


def test_agent_command_execute_route_returns_updated_run(client, db_session, auth_headers, monkeypatch) -> None:
    user = _create_user(db_session, email="agent-command-execute@example.com")

    monkeypatch.setattr(
        agent_router,
        "execute_agent_command_run_for_user",
        lambda **kwargs: {
            "command_id": kwargs["command_id"],
            "owner_user_id": user.id,
            "input_text": "approve the change",
            "scope_kind": "workspace",
            "scope_id": None,
            "language_code": "en",
            "language_resolution_source": "explicit",
            "status": "completed",
            "status_reason": None,
            "plan": [],
            "execution_results": [
                {
                    "step_id": "step_1",
                    "status": "succeeded",
                    "output_summary": {"proposal_id": 12},
                    "error_text": None,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                }
            ],
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    response = client.post(
        "/agent/commands/cmd-1/execute",
        headers=auth_headers(client, user=user),
        json={"selected_step_ids": ["step_1"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["command_id"] == "cmd-1"
    assert payload["status"] == "completed"
    assert payload["execution_results"][0]["output_summary"]["proposal_id"] == 12
