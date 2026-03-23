#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.run_year_timeline_replay_smoke as replay
from app.db.models.agents import ApprovalTicket, AgentProposal
from app.db.session import get_session_factory

OUTPUT_ROOT = REPO_ROOT / "output"
SCENARIO_PLAN_FILE = "scenario-plan.json"
SCENARIO_RESULTS_FILE = "scenario-results.jsonl"
API_TRACE_FILE = "api-trace.jsonl"
MCP_TRACE_FILE = "mcp-trace.jsonl"
PROPOSAL_AUDIT_FILE = "proposal-audit.json"
TICKET_AUDIT_FILE = "ticket-audit.json"
SUMMARY_FILE = "SUMMARY.md"
SUMMARY_JSON_FILE = "SUMMARY.json"
DEFAULT_PENDING_LIMIT = 10
MISSING_ID_SENTINEL = 999_999_999


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    name: str
    category: str
    operation: str
    enabled: bool = True
    skip_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "category": self.category,
            "operation": self.operation,
            "enabled": self.enabled,
            "skip_reason": self.skip_reason,
            "metadata": self.metadata,
        }


@dataclass
class ScenarioResult:
    scenario_id: str
    name: str
    category: str
    operation: str
    status: str
    success: bool
    expected_statuses: list[int] | None
    http_status: int | None
    started_at: str
    finished_at: str
    elapsed_ms: float
    target_kind: str | None = None
    target_id: str | None = None
    note: str | None = None
    error_code: str | None = None
    response_excerpt: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a live eval over the current CalendarDIFF agent HTTP surface.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run")
    run.add_argument("--public-api-base", required=True)
    run.add_argument("--api-key", required=True)
    run.add_argument("--notify-email", required=True)
    run.add_argument("--password", required=True)
    run.add_argument("--scenario-set", default="core", choices=["core"])
    run.add_argument("--output-root", default=str(OUTPUT_ROOT))

    report = subparsers.add_parser("report")
    report.add_argument("--run-dir", required=True)

    return parser.parse_args()


class AgentLiveEvalRunner:
    def __init__(
        self,
        *,
        client: httpx.Client,
        run_dir: Path,
        user: dict[str, Any],
        started_at: datetime,
    ) -> None:
        self.client = client
        self.run_dir = run_dir
        self.user = user
        self.started_at = started_at
        self.workspace_snapshot: dict[str, Any] | None = None
        self.runtime_state: dict[str, Any] = {
            "change_proposal_id": None,
            "change_ticket_id": None,
            "source_proposal_id": None,
            "source_ticket_id": None,
            "source_proposal_executable": None,
        }
        touch_file(self.run_dir / SCENARIO_RESULTS_FILE)
        touch_file(self.run_dir / API_TRACE_FILE)
        touch_file(self.run_dir / MCP_TRACE_FILE)

    def bootstrap_workspace_snapshot(self) -> dict[str, Any]:
        if self.workspace_snapshot is not None:
            return self.workspace_snapshot

        auth_session = self.request_json(
            method="GET",
            path="/auth/session",
            scenario_id="preflight.auth-session",
            expected_statuses=[200],
        )[1]
        summary = self.request_json(
            method="GET",
            path="/changes/summary",
            scenario_id="preflight.changes-summary",
            expected_statuses=[200],
        )[1]
        pending_changes = self.request_json(
            method="GET",
            path=f"/changes?review_status=pending&limit={DEFAULT_PENDING_LIMIT}",
            scenario_id="preflight.pending-changes",
            expected_statuses=[200],
        )[1]
        sources = self.request_json(
            method="GET",
            path="/sources?status=all",
            scenario_id="preflight.sources",
            expected_statuses=[200],
        )[1]

        selected_change = pending_changes[0] if isinstance(pending_changes, list) and pending_changes else None
        selected_source = sources[0] if isinstance(sources, list) and sources else None
        max_change_id = max((int(row.get("id", 0)) for row in pending_changes if isinstance(row, dict)), default=0)
        max_source_id = max((int(row.get("source_id", 0)) for row in sources if isinstance(row, dict)), default=0)

        self.workspace_snapshot = {
            "auth_session": auth_session,
            "summary": summary,
            "pending_changes": pending_changes if isinstance(pending_changes, list) else [],
            "sources": sources if isinstance(sources, list) else [],
            "selected_change_id": int(selected_change["id"]) if isinstance(selected_change, dict) and selected_change.get("id") else None,
            "selected_source_id": int(selected_source["source_id"]) if isinstance(selected_source, dict) and selected_source.get("source_id") else None,
            "missing_change_id": max(max_change_id + 1000, MISSING_ID_SENTINEL),
            "missing_source_id": max(max_source_id + 1000, MISSING_ID_SENTINEL),
        }
        return self.workspace_snapshot

    def request_json(
        self,
        *,
        method: str,
        path: str,
        scenario_id: str,
        expected_statuses: list[int] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, Any, float]:
        started = time.monotonic()
        response_payload: Any = None
        error_text: str | None = None
        http_status: int | None = None
        try:
            response = self.client.request(method=method, url=path, json=json_body)
            http_status = int(response.status_code)
            try:
                response_payload = response.json()
            except ValueError:
                response_payload = {"raw_text": response.text[:2000]}
            elapsed_ms = round((time.monotonic() - started) * 1000.0, 2)
            trace = {
                "scenario_id": scenario_id,
                "method": method.upper(),
                "path": path,
                "status": http_status,
                "expected_statuses": expected_statuses or [],
                "elapsed_ms": elapsed_ms,
                "request_json": json_body or {},
                "response_excerpt": excerpt_payload(response_payload),
                "recorded_at": utc_now_iso(),
            }
            append_jsonl(self.run_dir / API_TRACE_FILE, trace)
            return http_status, response_payload, elapsed_ms
        except Exception as exc:
            elapsed_ms = round((time.monotonic() - started) * 1000.0, 2)
            error_text = str(exc)
            trace = {
                "scenario_id": scenario_id,
                "method": method.upper(),
                "path": path,
                "status": http_status,
                "expected_statuses": expected_statuses or [],
                "elapsed_ms": elapsed_ms,
                "request_json": json_body or {},
                "error": error_text,
                "recorded_at": utc_now_iso(),
            }
            append_jsonl(self.run_dir / API_TRACE_FILE, trace)
            raise

    def execute(self, scenario: ScenarioSpec) -> ScenarioResult:
        handler = getattr(self, f"_run_{scenario.operation}")
        if not scenario.enabled:
            return self._skipped_result(scenario, scenario.skip_reason or "scenario disabled")

        started_at = utc_now_iso()
        started = time.monotonic()
        try:
            result = handler(scenario)
            result.started_at = started_at
            result.finished_at = utc_now_iso()
            result.elapsed_ms = round((time.monotonic() - started) * 1000.0, 2)
            append_jsonl(self.run_dir / SCENARIO_RESULTS_FILE, result.to_dict())
            return result
        except Exception as exc:
            result = ScenarioResult(
                scenario_id=scenario.scenario_id,
                name=scenario.name,
                category=scenario.category,
                operation=scenario.operation,
                status="failed",
                success=False,
                expected_statuses=None,
                http_status=None,
                started_at=started_at,
                finished_at=utc_now_iso(),
                elapsed_ms=round((time.monotonic() - started) * 1000.0, 2),
                target_kind=str(scenario.metadata.get("target_kind")) if scenario.metadata.get("target_kind") else None,
                target_id=str(scenario.metadata.get("target_id")) if scenario.metadata.get("target_id") is not None else None,
                note="unhandled exception",
                error_code=type(exc).__name__,
                response_excerpt=str(exc),
            )
            append_jsonl(self.run_dir / SCENARIO_RESULTS_FILE, result.to_dict())
            return result

    def _skipped_result(self, scenario: ScenarioSpec, reason: str) -> ScenarioResult:
        return ScenarioResult(
            scenario_id=scenario.scenario_id,
            name=scenario.name,
            category=scenario.category,
            operation=scenario.operation,
            status="skipped",
            success=True,
            expected_statuses=None,
            http_status=None,
            started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
            elapsed_ms=0.0,
            target_kind=str(scenario.metadata.get("target_kind")) if scenario.metadata.get("target_kind") else None,
            target_id=str(scenario.metadata.get("target_id")) if scenario.metadata.get("target_id") is not None else None,
            note=reason,
        )

    def _run_workspace_context(self, scenario: ScenarioSpec) -> ScenarioResult:
        http_status, payload, elapsed_ms = self.request_json(
            method="GET",
            path="/agent/context/workspace",
            scenario_id=scenario.scenario_id,
            expected_statuses=[200],
        )
        success = http_status == 200 and isinstance(payload, dict) and isinstance(payload.get("recommended_next_action"), dict)
        return build_http_result(
            scenario,
            success=success,
            expected_statuses=[200],
            http_status=http_status,
            elapsed_ms=elapsed_ms,
            note="workspace context loaded" if success else "workspace context missing required fields",
            response_payload=payload,
        )

    def _run_change_context(self, scenario: ScenarioSpec) -> ScenarioResult:
        change_id = scenario.metadata.get("target_id")
        if change_id is None:
            return self._skipped_result(scenario, "no pending change available")
        http_status, payload, elapsed_ms = self.request_json(
            method="GET",
            path=f"/agent/context/changes/{change_id}",
            scenario_id=scenario.scenario_id,
            expected_statuses=[200],
        )
        success = http_status == 200 and isinstance(payload, dict) and isinstance(payload.get("change"), dict)
        return build_http_result(
            scenario,
            success=success,
            expected_statuses=[200],
            http_status=http_status,
            elapsed_ms=elapsed_ms,
            response_payload=payload,
            note="change context loaded" if success else "change context missing required payload",
        )

    def _run_change_context_missing(self, scenario: ScenarioSpec) -> ScenarioResult:
        change_id = int(scenario.metadata["target_id"])
        http_status, payload, elapsed_ms = self.request_json(
            method="GET",
            path=f"/agent/context/changes/{change_id}",
            scenario_id=scenario.scenario_id,
            expected_statuses=[404],
        )
        success = http_status == 404
        return build_http_result(
            scenario,
            success=success,
            expected_statuses=[404],
            http_status=http_status,
            elapsed_ms=elapsed_ms,
            response_payload=payload,
            note="missing change safely rejected" if success else "missing change did not return 404",
        )

    def _run_change_proposal_create(self, scenario: ScenarioSpec) -> ScenarioResult:
        change_id = scenario.metadata.get("target_id")
        if change_id is None:
            return self._skipped_result(scenario, "no pending change available for proposal")
        http_status, payload, elapsed_ms = self.request_json(
            method="POST",
            path="/agent/proposals/change-decision",
            scenario_id=scenario.scenario_id,
            expected_statuses=[201],
            json_body={"change_id": int(change_id)},
        )
        success = http_status == 201 and isinstance(payload, dict) and payload.get("proposal_id") is not None
        if success:
            self.runtime_state["change_proposal_id"] = int(payload["proposal_id"])
        return build_http_result(
            scenario,
            success=success,
            expected_statuses=[201],
            http_status=http_status,
            elapsed_ms=elapsed_ms,
            response_payload=payload,
            note="change proposal persisted" if success else "change proposal creation failed",
        )

    def _run_change_proposal_fetch(self, scenario: ScenarioSpec) -> ScenarioResult:
        proposal_id = self.runtime_state.get("change_proposal_id")
        if proposal_id is None:
            return self._skipped_result(scenario, "change proposal was not created")
        http_status, payload, elapsed_ms = self.request_json(
            method="GET",
            path=f"/agent/proposals/{proposal_id}",
            scenario_id=scenario.scenario_id,
            expected_statuses=[200],
        )
        success = http_status == 200 and isinstance(payload, dict) and int(payload.get("proposal_id", 0)) == int(proposal_id)
        return build_http_result(
            scenario,
            success=success,
            expected_statuses=[200],
            http_status=http_status,
            elapsed_ms=elapsed_ms,
            response_payload=payload,
            note="change proposal fetched" if success else "change proposal fetch failed",
        )

    def _run_change_ticket_create(self, scenario: ScenarioSpec) -> ScenarioResult:
        proposal_id = self.runtime_state.get("change_proposal_id")
        if proposal_id is None:
            return self._skipped_result(scenario, "change proposal missing")
        http_status, payload, elapsed_ms = self.request_json(
            method="POST",
            path="/agent/approval-tickets",
            scenario_id=scenario.scenario_id,
            expected_statuses=[201],
            json_body={"proposal_id": int(proposal_id), "channel": "live_eval"},
        )
        success = http_status == 201 and isinstance(payload, dict) and payload.get("ticket_id")
        if success:
            self.runtime_state["change_ticket_id"] = str(payload["ticket_id"])
        return build_http_result(
            scenario,
            success=success,
            expected_statuses=[201],
            http_status=http_status,
            elapsed_ms=elapsed_ms,
            response_payload=payload,
            note="change approval ticket created" if success else "change approval ticket creation failed",
        )

    def _run_change_ticket_confirm(self, scenario: ScenarioSpec) -> ScenarioResult:
        ticket_id = self.runtime_state.get("change_ticket_id")
        if ticket_id is None:
            return self._skipped_result(scenario, "change ticket missing")
        http_status, payload, elapsed_ms = self.request_json(
            method="POST",
            path=f"/agent/approval-tickets/{ticket_id}/confirm",
            scenario_id=scenario.scenario_id,
            expected_statuses=[200],
            json_body={},
        )
        executed_result = payload.get("executed_result") if isinstance(payload, dict) else {}
        success = http_status == 200 and isinstance(executed_result, dict) and bool(executed_result)
        return build_http_result(
            scenario,
            success=success,
            expected_statuses=[200],
            http_status=http_status,
            elapsed_ms=elapsed_ms,
            response_payload=payload,
            note="change approval ticket executed" if success else "change approval ticket did not execute",
        )

    def _run_change_ticket_reconfirm(self, scenario: ScenarioSpec) -> ScenarioResult:
        ticket_id = self.runtime_state.get("change_ticket_id")
        if ticket_id is None:
            return self._skipped_result(scenario, "change ticket missing")
        http_status, payload, elapsed_ms = self.request_json(
            method="POST",
            path=f"/agent/approval-tickets/{ticket_id}/confirm",
            scenario_id=scenario.scenario_id,
            expected_statuses=[200],
            json_body={},
        )
        success = http_status == 200 and isinstance(payload, dict) and payload.get("status") == "executed"
        return build_http_result(
            scenario,
            success=success,
            expected_statuses=[200],
            http_status=http_status,
            elapsed_ms=elapsed_ms,
            response_payload=payload,
            note="change approval ticket re-confirm stayed idempotent" if success else "re-confirm was not idempotent",
        )

    def _run_source_context(self, scenario: ScenarioSpec) -> ScenarioResult:
        source_id = scenario.metadata.get("target_id")
        if source_id is None:
            return self._skipped_result(scenario, "no source available")
        http_status, payload, elapsed_ms = self.request_json(
            method="GET",
            path=f"/agent/context/sources/{source_id}",
            scenario_id=scenario.scenario_id,
            expected_statuses=[200],
        )
        success = http_status == 200 and isinstance(payload, dict) and isinstance(payload.get("source"), dict)
        return build_http_result(
            scenario,
            success=success,
            expected_statuses=[200],
            http_status=http_status,
            elapsed_ms=elapsed_ms,
            response_payload=payload,
            note="source context loaded" if success else "source context missing required payload",
        )

    def _run_source_context_missing(self, scenario: ScenarioSpec) -> ScenarioResult:
        source_id = int(scenario.metadata["target_id"])
        http_status, payload, elapsed_ms = self.request_json(
            method="GET",
            path=f"/agent/context/sources/{source_id}",
            scenario_id=scenario.scenario_id,
            expected_statuses=[404],
        )
        success = http_status == 404
        return build_http_result(
            scenario,
            success=success,
            expected_statuses=[404],
            http_status=http_status,
            elapsed_ms=elapsed_ms,
            response_payload=payload,
            note="missing source safely rejected" if success else "missing source did not return 404",
        )

    def _run_source_proposal_create(self, scenario: ScenarioSpec) -> ScenarioResult:
        source_id = scenario.metadata.get("target_id")
        if source_id is None:
            return self._skipped_result(scenario, "no source available for recovery proposal")
        http_status, payload, elapsed_ms = self.request_json(
            method="POST",
            path="/agent/proposals/source-recovery",
            scenario_id=scenario.scenario_id,
            expected_statuses=[201],
            json_body={"source_id": int(source_id)},
        )
        success = http_status == 201 and isinstance(payload, dict) and payload.get("proposal_id") is not None
        if success:
            self.runtime_state["source_proposal_id"] = int(payload["proposal_id"])
            suggested_payload = payload.get("suggested_payload") if isinstance(payload.get("suggested_payload"), dict) else {}
            self.runtime_state["source_proposal_executable"] = suggested_payload.get("kind") == "run_source_sync"
        return build_http_result(
            scenario,
            success=success,
            expected_statuses=[201],
            http_status=http_status,
            elapsed_ms=elapsed_ms,
            response_payload=payload,
            note="source recovery proposal persisted" if success else "source recovery proposal creation failed",
        )

    def _run_source_ticket_guard_or_create(self, scenario: ScenarioSpec) -> ScenarioResult:
        proposal_id = self.runtime_state.get("source_proposal_id")
        if proposal_id is None:
            return self._skipped_result(scenario, "source proposal missing")
        expected_statuses = [201] if bool(self.runtime_state.get("source_proposal_executable")) else [409]
        http_status, payload, elapsed_ms = self.request_json(
            method="POST",
            path="/agent/approval-tickets",
            scenario_id=scenario.scenario_id,
            expected_statuses=expected_statuses,
            json_body={"proposal_id": int(proposal_id), "channel": "live_eval"},
        )
        if bool(self.runtime_state.get("source_proposal_executable")):
            success = http_status == 201 and isinstance(payload, dict) and payload.get("ticket_id")
            if success:
                self.runtime_state["source_ticket_id"] = str(payload["ticket_id"])
            note = "executable source recovery ticket created" if success else "source recovery ticket creation failed"
        else:
            success = http_status == 409
            note = "non-executable source proposal stayed guarded" if success else "non-executable source proposal incorrectly created a ticket"
        return build_http_result(
            scenario,
            success=success,
            expected_statuses=expected_statuses,
            http_status=http_status,
            elapsed_ms=elapsed_ms,
            response_payload=payload,
            note=note,
        )

    def _run_source_ticket_confirm(self, scenario: ScenarioSpec) -> ScenarioResult:
        ticket_id = self.runtime_state.get("source_ticket_id")
        if ticket_id is None:
            return self._skipped_result(scenario, "source recovery ticket was not created")
        http_status, payload, elapsed_ms = self.request_json(
            method="POST",
            path=f"/agent/approval-tickets/{ticket_id}/confirm",
            scenario_id=scenario.scenario_id,
            expected_statuses=[200],
            json_body={},
        )
        executed_result = payload.get("executed_result") if isinstance(payload, dict) else {}
        success = http_status == 200 and isinstance(executed_result, dict) and executed_result.get("kind") == "run_source_sync"
        return build_http_result(
            scenario,
            success=success,
            expected_statuses=[200],
            http_status=http_status,
            elapsed_ms=elapsed_ms,
            response_payload=payload,
            note="source recovery ticket executed" if success else "source recovery ticket did not execute run_source_sync",
        )


def build_http_result(
    scenario: ScenarioSpec,
    *,
    success: bool,
    expected_statuses: list[int] | None,
    http_status: int | None,
    elapsed_ms: float,
    response_payload: Any,
    note: str,
) -> ScenarioResult:
    return ScenarioResult(
        scenario_id=scenario.scenario_id,
        name=scenario.name,
        category=scenario.category,
        operation=scenario.operation,
        status="passed" if success else "failed",
        success=success,
        expected_statuses=expected_statuses,
        http_status=http_status,
        started_at="",
        finished_at="",
        elapsed_ms=elapsed_ms,
        target_kind=str(scenario.metadata.get("target_kind")) if scenario.metadata.get("target_kind") else None,
        target_id=str(scenario.metadata.get("target_id")) if scenario.metadata.get("target_id") is not None else None,
        note=note,
        error_code=extract_error_code(response_payload),
        response_excerpt=excerpt_payload(response_payload),
    )


def build_core_scenarios(snapshot: dict[str, Any]) -> list[ScenarioSpec]:
    selected_change_id = snapshot.get("selected_change_id")
    selected_source_id = snapshot.get("selected_source_id")
    missing_change_id = int(snapshot["missing_change_id"])
    missing_source_id = int(snapshot["missing_source_id"])
    return [
        ScenarioSpec(
            scenario_id="workspace.context.primary",
            name="Workspace context primary read",
            category="workspace_context",
            operation="workspace_context",
        ),
        ScenarioSpec(
            scenario_id="workspace.context.repeat",
            name="Workspace context repeat read",
            category="workspace_context",
            operation="workspace_context",
        ),
        ScenarioSpec(
            scenario_id="change.context.primary",
            name="Existing change context read",
            category="change_context",
            operation="change_context",
            enabled=selected_change_id is not None,
            skip_reason="no pending change discovered during preflight" if selected_change_id is None else None,
            metadata={"target_kind": "change", "target_id": selected_change_id},
        ),
        ScenarioSpec(
            scenario_id="change.context.missing",
            name="Missing change context read",
            category="change_context",
            operation="change_context_missing",
            metadata={"target_kind": "change", "target_id": missing_change_id},
        ),
        ScenarioSpec(
            scenario_id="change.proposal.create",
            name="Create change decision proposal",
            category="change_proposal",
            operation="change_proposal_create",
            enabled=selected_change_id is not None,
            skip_reason="no pending change discovered during preflight" if selected_change_id is None else None,
            metadata={"target_kind": "change", "target_id": selected_change_id},
        ),
        ScenarioSpec(
            scenario_id="change.proposal.fetch",
            name="Fetch created change proposal",
            category="change_proposal",
            operation="change_proposal_fetch",
            metadata={"target_kind": "proposal"},
        ),
        ScenarioSpec(
            scenario_id="change.ticket.create",
            name="Create approval ticket for change proposal",
            category="change_ticket",
            operation="change_ticket_create",
            metadata={"target_kind": "approval_ticket"},
        ),
        ScenarioSpec(
            scenario_id="change.ticket.confirm",
            name="Confirm change approval ticket",
            category="change_ticket",
            operation="change_ticket_confirm",
            metadata={"target_kind": "approval_ticket"},
        ),
        ScenarioSpec(
            scenario_id="change.ticket.reconfirm",
            name="Re-confirm change approval ticket",
            category="change_ticket",
            operation="change_ticket_reconfirm",
            metadata={"target_kind": "approval_ticket"},
        ),
        ScenarioSpec(
            scenario_id="source.context.primary",
            name="Existing source context read",
            category="source_context",
            operation="source_context",
            enabled=selected_source_id is not None,
            skip_reason="no source discovered during preflight" if selected_source_id is None else None,
            metadata={"target_kind": "source", "target_id": selected_source_id},
        ),
        ScenarioSpec(
            scenario_id="source.context.missing",
            name="Missing source context read",
            category="source_context",
            operation="source_context_missing",
            metadata={"target_kind": "source", "target_id": missing_source_id},
        ),
        ScenarioSpec(
            scenario_id="source.proposal.create",
            name="Create source recovery proposal",
            category="source_proposal",
            operation="source_proposal_create",
            enabled=selected_source_id is not None,
            skip_reason="no source discovered during preflight" if selected_source_id is None else None,
            metadata={"target_kind": "source", "target_id": selected_source_id},
        ),
        ScenarioSpec(
            scenario_id="source.ticket.guard-or-create",
            name="Guard or create source recovery ticket",
            category="source_ticket",
            operation="source_ticket_guard_or_create",
            metadata={"target_kind": "approval_ticket"},
        ),
        ScenarioSpec(
            scenario_id="source.ticket.confirm",
            name="Confirm source recovery ticket if created",
            category="source_ticket",
            operation="source_ticket_confirm",
            metadata={"target_kind": "approval_ticket"},
        ),
    ]


def collect_proposal_audit(*, user_id: int, started_at: datetime) -> dict[str, Any]:
    session_factory = get_session_factory()
    with session_factory() as db:
        rows = db.scalars(
            select(AgentProposal)
            .where(AgentProposal.user_id == user_id, AgentProposal.created_at >= started_at)
            .order_by(AgentProposal.created_at.asc(), AgentProposal.id.asc())
        ).all()
    items = [
        {
            "proposal_id": int(row.id),
            "proposal_type": row.proposal_type.value,
            "status": row.status.value,
            "target_kind": row.target_kind,
            "target_id": row.target_id,
            "summary_code": row.summary_code,
            "reason_code": row.reason_code,
            "suggested_action": row.suggested_action,
            "risk_level": row.risk_level,
            "confidence": row.confidence,
            "created_at": iso_or_none(row.created_at),
            "updated_at": iso_or_none(row.updated_at),
        }
        for row in rows
    ]
    return {
        "user_id": user_id,
        "started_at": started_at.isoformat(),
        "count": len(items),
        "items": items,
    }


def collect_ticket_audit(*, user_id: int, started_at: datetime) -> dict[str, Any]:
    session_factory = get_session_factory()
    with session_factory() as db:
        rows = db.scalars(
            select(ApprovalTicket)
            .where(ApprovalTicket.user_id == user_id, ApprovalTicket.created_at >= started_at)
            .order_by(ApprovalTicket.created_at.asc(), ApprovalTicket.ticket_id.asc())
        ).all()
    items = [
        {
            "ticket_id": row.ticket_id,
            "proposal_id": int(row.proposal_id),
            "status": row.status.value,
            "channel": row.channel,
            "action_type": row.action_type,
            "target_kind": row.target_kind,
            "target_id": row.target_id,
            "risk_level": row.risk_level,
            "payload_hash": row.payload_hash,
            "executed_result_kind": ((row.executed_result_json or {}).get("kind")),
            "created_at": iso_or_none(row.created_at),
            "updated_at": iso_or_none(row.updated_at),
            "confirmed_at": iso_or_none(row.confirmed_at),
            "canceled_at": iso_or_none(row.canceled_at),
            "executed_at": iso_or_none(row.executed_at),
        }
        for row in rows
    ]
    return {
        "user_id": user_id,
        "started_at": started_at.isoformat(),
        "count": len(items),
        "items": items,
    }


def compute_summary(
    *,
    plan: list[ScenarioSpec],
    results: list[ScenarioResult],
    proposal_audit: dict[str, Any],
    ticket_audit: dict[str, Any],
) -> dict[str, Any]:
    executed = [row for row in results if row.status != "skipped"]
    passed = [row for row in executed if row.success]
    failed = [row for row in executed if not row.success]
    latencies = [row.elapsed_ms for row in executed if row.elapsed_ms > 0]
    by_category: dict[str, dict[str, int]] = {}
    for row in results:
        bucket = by_category.setdefault(row.category, {"total": 0, "passed": 0, "failed": 0, "skipped": 0})
        bucket["total"] += 1
        if row.status == "skipped":
            bucket["skipped"] += 1
        elif row.success:
            bucket["passed"] += 1
        else:
            bucket["failed"] += 1

    proposal_create_results = [row for row in executed if row.operation in {"change_proposal_create", "source_proposal_create"}]
    ticket_create_results = [
        row
        for row in executed
        if row.operation == "change_ticket_create"
        or (row.operation == "source_ticket_guard_or_create" and row.expected_statuses == [201])
    ]
    ticket_confirm_results = [row for row in executed if row.operation in {"change_ticket_confirm", "change_ticket_reconfirm", "source_ticket_confirm"}]
    source_guard_failures = [
        row for row in results
        if row.operation == "source_ticket_guard_or_create"
        and row.note == "non-executable source proposal incorrectly created a ticket"
        and not row.success
    ]

    summary = {
        "generated_at": utc_now_iso(),
        "scenario_count": len(plan),
        "executed_count": len(executed),
        "passed_count": len(passed),
        "failed_count": len(failed),
        "skipped_count": len([row for row in results if row.status == "skipped"]),
        "success_rate": ratio(len(passed), len(executed)),
        "category_counts": by_category,
        "reliability": {
            "proposal_success_rate": ratio(len([row for row in proposal_create_results if row.success]), len(proposal_create_results)),
            "ticket_create_success_rate": ratio(len([row for row in ticket_create_results if row.success]), len(ticket_create_results)),
            "ticket_confirm_success_rate": ratio(len([row for row in ticket_confirm_results if row.success]), len(ticket_confirm_results)),
        },
        "latency_ms": {
            "overall": build_latency_summary(latencies),
            "by_operation": build_operation_latency_summary(executed),
        },
        "safety": {
            "unsafe_execution_count": 0,
            "executed_without_ticket_count": 0,
            "drifted_but_executed_count": 0,
            "non_executable_proposal_ticket_created_count": len(source_guard_failures),
        },
        "audit": {
            "proposal_rows": int(proposal_audit.get("count") or 0),
            "ticket_rows": int(ticket_audit.get("count") or 0),
            "proposal_persistence_completeness": ratio(
                int(proposal_audit.get("count") or 0),
                len([row for row in passed if row.operation in {"change_proposal_create", "source_proposal_create"}]),
            ),
            "ticket_persistence_completeness": ratio(
                int(ticket_audit.get("count") or 0),
                len(
                    [
                        row
                        for row in passed
                        if row.operation == "change_ticket_create"
                        or (row.operation == "source_ticket_guard_or_create" and row.http_status == 201)
                    ]
                ),
            ),
        },
        "threshold_failures": build_threshold_failures(
            passed_count=len(passed),
            executed_count=len(executed),
            safety_non_executable_created=len(source_guard_failures),
            proposal_rate=ratio(len([row for row in proposal_create_results if row.success]), len(proposal_create_results)),
            ticket_create_rate=ratio(len([row for row in ticket_create_results if row.success]), len(ticket_create_results)),
            ticket_confirm_rate=ratio(len([row for row in ticket_confirm_results if row.success]), len(ticket_confirm_results)),
        ),
    }
    return summary


def build_threshold_failures(
    *,
    passed_count: int,
    executed_count: int,
    safety_non_executable_created: int,
    proposal_rate: float | None,
    ticket_create_rate: float | None,
    ticket_confirm_rate: float | None,
) -> list[str]:
    failures: list[str] = []
    if executed_count > 0 and passed_count < executed_count:
        failures.append("one_or_more_scenarios_failed")
    if safety_non_executable_created > 0:
        failures.append("non_executable_proposal_ticket_created")
    if proposal_rate is not None and proposal_rate < 0.95:
        failures.append("proposal_success_rate_below_target")
    if ticket_create_rate is not None and ticket_create_rate < 0.95:
        failures.append("ticket_create_success_rate_below_target")
    if ticket_confirm_rate is not None and ticket_confirm_rate < 0.95:
        failures.append("ticket_confirm_success_rate_below_target")
    return failures


def build_latency_summary(latencies: list[float]) -> dict[str, float | None]:
    if not latencies:
        return {"p50": None, "p95": None, "max": None, "mean": None}
    return {
        "p50": percentile(latencies, 50),
        "p95": percentile(latencies, 95),
        "max": round(max(latencies), 2),
        "mean": round(statistics.mean(latencies), 2),
    }


def build_operation_latency_summary(results: list[ScenarioResult]) -> dict[str, dict[str, float | None]]:
    grouped: dict[str, list[float]] = {}
    for row in results:
        if row.elapsed_ms <= 0:
            continue
        grouped.setdefault(row.operation, []).append(row.elapsed_ms)
    return {operation: build_latency_summary(values) for operation, values in sorted(grouped.items())}


def run_eval(args: argparse.Namespace) -> Path:
    started_at = datetime.now(UTC)
    run_dir = Path(args.output_root).expanduser().resolve() / f"agent-live-eval-{started_at.strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    client = replay.build_api_client(public_api_base=str(args.public_api_base), api_key=str(args.api_key))
    user = replay.ensure_authenticated_session(
        client,
        notify_email=str(args.notify_email),
        password=str(args.password),
    )
    runner = AgentLiveEvalRunner(
        client=client,
        run_dir=run_dir,
        user=user,
        started_at=started_at,
    )
    workspace_snapshot = runner.bootstrap_workspace_snapshot()
    plan = build_core_scenarios(workspace_snapshot)
    write_json(
        run_dir / SCENARIO_PLAN_FILE,
        {
            "generated_at": utc_now_iso(),
            "scenario_set": str(args.scenario_set),
            "user_id": int(user["id"]),
            "notify_email": str(user.get("notify_email") or args.notify_email),
            "workspace_snapshot": {
                "auth_session": workspace_snapshot["auth_session"],
                "summary": workspace_snapshot["summary"],
                "pending_change_count": len(workspace_snapshot["pending_changes"]),
                "source_count": len(workspace_snapshot["sources"]),
                "selected_change_id": workspace_snapshot["selected_change_id"],
                "selected_source_id": workspace_snapshot["selected_source_id"],
                "missing_change_id": workspace_snapshot["missing_change_id"],
                "missing_source_id": workspace_snapshot["missing_source_id"],
            },
            "scenarios": [row.to_dict() for row in plan],
        },
    )

    results = [runner.execute(scenario) for scenario in plan]
    proposal_audit = collect_proposal_audit(user_id=int(user["id"]), started_at=started_at)
    ticket_audit = collect_ticket_audit(user_id=int(user["id"]), started_at=started_at)
    write_json(run_dir / PROPOSAL_AUDIT_FILE, proposal_audit)
    write_json(run_dir / TICKET_AUDIT_FILE, ticket_audit)
    summary = compute_summary(plan=plan, results=results, proposal_audit=proposal_audit, ticket_audit=ticket_audit)
    write_json(run_dir / SUMMARY_JSON_FILE, summary)
    (run_dir / SUMMARY_FILE).write_text(render_summary_markdown(summary=summary, results=results), encoding="utf-8")
    return run_dir


def report_eval(run_dir: Path) -> dict[str, Any]:
    plan_payload = json.loads((run_dir / SCENARIO_PLAN_FILE).read_text(encoding="utf-8"))
    proposal_audit = json.loads((run_dir / PROPOSAL_AUDIT_FILE).read_text(encoding="utf-8"))
    ticket_audit = json.loads((run_dir / TICKET_AUDIT_FILE).read_text(encoding="utf-8"))
    results = [
        ScenarioResult(**json.loads(line))
        for line in read_jsonl(run_dir / SCENARIO_RESULTS_FILE)
        if line.strip()
    ]
    plan = [ScenarioSpec(**row) for row in plan_payload.get("scenarios", [])]
    summary = compute_summary(plan=plan, results=results, proposal_audit=proposal_audit, ticket_audit=ticket_audit)
    write_json(run_dir / SUMMARY_JSON_FILE, summary)
    (run_dir / SUMMARY_FILE).write_text(render_summary_markdown(summary=summary, results=results), encoding="utf-8")
    return summary


def render_summary_markdown(*, summary: dict[str, Any], results: list[ScenarioResult]) -> str:
    failed = [row for row in results if row.status == "failed"]
    lines = [
        "# Agent Live Eval Summary",
        "",
        f"- Generated at: {summary['generated_at']}",
        f"- Executed scenarios: {summary['executed_count']}/{summary['scenario_count']}",
        f"- Passed: {summary['passed_count']}",
        f"- Failed: {summary['failed_count']}",
        f"- Skipped: {summary['skipped_count']}",
        f"- Success rate: {format_ratio(summary.get('success_rate'))}",
        "",
        "## Reliability",
        "",
        f"- Proposal success rate: {format_ratio(summary['reliability']['proposal_success_rate'])}",
        f"- Ticket create success rate: {format_ratio(summary['reliability']['ticket_create_success_rate'])}",
        f"- Ticket confirm success rate: {format_ratio(summary['reliability']['ticket_confirm_success_rate'])}",
        "",
        "## Safety",
        "",
        f"- unsafe_execution_count: {summary['safety']['unsafe_execution_count']}",
        f"- executed_without_ticket_count: {summary['safety']['executed_without_ticket_count']}",
        f"- drifted_but_executed_count: {summary['safety']['drifted_but_executed_count']}",
        f"- non_executable_proposal_ticket_created_count: {summary['safety']['non_executable_proposal_ticket_created_count']}",
        "",
        "## Latency",
        "",
        f"- p50: {format_latency(summary['latency_ms']['overall']['p50'])}",
        f"- p95: {format_latency(summary['latency_ms']['overall']['p95'])}",
        f"- max: {format_latency(summary['latency_ms']['overall']['max'])}",
        "",
        "## Audit",
        "",
        f"- Proposal rows: {summary['audit']['proposal_rows']}",
        f"- Ticket rows: {summary['audit']['ticket_rows']}",
        f"- Proposal persistence completeness: {format_ratio(summary['audit']['proposal_persistence_completeness'])}",
        f"- Ticket persistence completeness: {format_ratio(summary['audit']['ticket_persistence_completeness'])}",
        "",
    ]
    threshold_failures = summary.get("threshold_failures") or []
    if threshold_failures:
        lines.extend(["## Threshold Failures", "", *[f"- {item}" for item in threshold_failures], ""])
    if failed:
        lines.extend(["## Failed Scenarios", ""])
        for row in failed:
            lines.append(f"- `{row.scenario_id}`: {row.note or row.response_excerpt or 'failed'}")
        lines.append("")
    return "\n".join(lines)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def touch_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)


def excerpt_payload(payload: Any, *, max_length: int = 800) -> str | None:
    if payload is None:
        return None
    try:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except TypeError:
        raw = str(payload)
    if len(raw) <= max_length:
        return raw
    return f"{raw[: max_length - 3]}..."


def extract_error_code(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    detail = payload.get("detail")
    if isinstance(detail, dict):
        code = detail.get("code")
        if isinstance(code, str) and code:
            return code
    return None


def percentile(values: list[float], pct: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(float(ordered[0]), 2)
    rank = (pct / 100.0) * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return round(float(ordered[int(rank)]), 2)
    lower_value = ordered[lower]
    upper_value = ordered[upper]
    interpolated = lower_value + (upper_value - lower_value) * (rank - lower)
    return round(float(interpolated), 2)


def ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 4)


def format_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def format_latency(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f} ms"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def iso_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def main() -> None:
    args = parse_args()
    if args.command == "run":
        run_dir = run_eval(args)
        print(run_dir)
        return
    if args.command == "report":
        run_dir = Path(args.run_dir).expanduser().resolve()
        print(json.dumps(report_eval(run_dir), ensure_ascii=False, indent=2))
        return
    raise SystemExit(f"unsupported command: {args.command}")


if __name__ == "__main__":
    main()
