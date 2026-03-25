from __future__ import annotations

from types import SimpleNamespace

import app.modules.agents.generation_gateway as generation_gateway
from app.modules.agents.generation_gateway import (
    AgentProposalDraft,
    AgentProposalDraftRequest,
    generate_agent_proposal_draft,
)
from app.modules.llm_gateway import LlmGatewayError, LlmInvokeResult


def _draft_request(*, proposal_kind: str = "change_decision", target_kind: str = "change", target_id: str = "42") -> AgentProposalDraftRequest:
    return AgentProposalDraftRequest(
        proposal_kind=proposal_kind,  # type: ignore[arg-type]
        target_kind=target_kind,
        target_id=target_id,
        origin_request_id="mcp-req-123",
        deterministic_draft=AgentProposalDraft(
            summary="Approve this change in Replay Review.",
            summary_code="agents.proposals.change_decision.approve.summary",
            reason="The change looks safe and is ready to approve.",
            reason_code="agents.proposals.change_decision.reason",
            risk_level="medium",
            confidence=0.78,
            suggested_action="approve",
            payload_json={"kind": "change_decision", "change_id": 42, "decision": "approve"},
            context_json={"change_id": 42, "review_status": "pending"},
            target_snapshot_json={"change_id": 42, "review_status": "pending"},
        ),
    )


def test_generation_gateway_stays_deterministic_by_default(monkeypatch) -> None:
    called = {"count": 0}

    def _unexpected_invoke(*args, **kwargs):  # type: ignore[no-untyped-def]
        called["count"] += 1
        raise AssertionError("llm gateway should not be called in deterministic mode")

    monkeypatch.setattr(generation_gateway, "get_settings", lambda: SimpleNamespace(agent_generation_mode="deterministic"))
    monkeypatch.setattr(generation_gateway, "invoke_llm_json", _unexpected_invoke)

    draft_request = _draft_request()
    result = generate_agent_proposal_draft(None, draft_request=draft_request)  # type: ignore[arg-type]

    assert result == draft_request.deterministic_draft
    assert called["count"] == 0


def test_generation_gateway_uses_agent_profile_when_llm_assisted(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_invoke(db, *, invoke_request):  # type: ignore[no-untyped-def]
        del db
        captured["invoke_request"] = invoke_request
        return LlmInvokeResult(
            json_object={
                "summary": "Approve this replay change now.",
                "reason": "The due date moved and the current evidence stays internally consistent.",
            },
            provider_id="agent-env-default",
            protocol="chat_completions",
            model="qwen3.5-plus",
            latency_ms=8,
            raw_usage={},
        )

    monkeypatch.setattr(generation_gateway, "get_settings", lambda: SimpleNamespace(agent_generation_mode="llm_assisted"))
    monkeypatch.setattr(generation_gateway, "invoke_llm_json", _fake_invoke)

    draft_request = _draft_request()
    result = generate_agent_proposal_draft(None, draft_request=draft_request)  # type: ignore[arg-type]

    invoke_request = captured["invoke_request"]
    assert result.summary == "Approve this replay change now."
    assert result.reason == "The due date moved and the current evidence stays internally consistent."
    assert invoke_request.profile_family == "agent"
    assert invoke_request.task_name == "agent_change_decision_proposal_narrative"
    assert invoke_request.request_id == "mcp-req-123"


def test_generation_gateway_falls_back_when_llm_errors(monkeypatch) -> None:
    def _raise_gateway_error(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise LlmGatewayError(
            code="parse_llm_upstream_error",
            message="upstream failed",
            retryable=False,
            provider_id="agent-env-default",
            protocol="chat_completions",
        )

    monkeypatch.setattr(generation_gateway, "get_settings", lambda: SimpleNamespace(agent_generation_mode="llm_assisted"))
    monkeypatch.setattr(generation_gateway, "invoke_llm_json", _raise_gateway_error)

    draft_request = _draft_request(proposal_kind="source_recovery", target_kind="source", target_id="24")
    result = generate_agent_proposal_draft(None, draft_request=draft_request)  # type: ignore[arg-type]

    assert result == draft_request.deterministic_draft
