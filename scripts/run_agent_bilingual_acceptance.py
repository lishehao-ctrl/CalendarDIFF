#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from fastapi.testclient import TestClient
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.server import RequestContext
from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.run_agent_live_eval as live_eval
import scripts.run_claw_mcp_smoke as claw_smoke
from app.core.config import get_settings
from app.db.schema_guard import reset_schema_guard_cache
from app.db.session import reset_engine
from app.modules.agents.language_context import AgentLanguageContext, detect_agent_input_language, resolve_agent_language_context
from app.modules.agents.mcp_audit_service import list_mcp_tool_invocations
from app.modules.changes.change_listing_service import get_change
from services.mcp_server import main as mcp_main

OUTPUT_ROOT = REPO_ROOT / "output"
SCENARIO_PLAN_FILE = "scenario-plan.json"
REST_RESULTS_FILE = "rest-results.jsonl"
MCP_RESULTS_FILE = "mcp-results.jsonl"
MIXED_RESULTS_FILE = "mixed-language-results.jsonl"
MANUAL_NOTES_FILE = "manual-eval-notes.md"
SUMMARY_FILE = "SUMMARY.md"
SUMMARY_JSON_FILE = "SUMMARY.json"


@dataclass(frozen=True)
class AcceptanceResult:
    surface: str
    scenario_id: str
    success: bool
    expected_language_code: str | None
    actual_language_code: str | None
    account_language_code: str | None
    input_language_code: str | None
    language_resolution_source: str | None
    wrong_language: bool
    mixed_language_output: bool
    forbidden_translation_violation: bool
    note: str | None = None
    response_excerpt: str | None = None
    recorded_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if not payload["recorded_at"]:
            payload["recorded_at"] = live_eval.utc_now_iso()
        return payload


class AcceptanceFailure(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run bilingual agent acceptance against local CalendarDIFF backend + MCP surfaces.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run")
    run.add_argument("--email", default="agent-live-eval@example.com")
    run.add_argument("--other-email", default="agent-live-eval-other@example.com")
    run.add_argument("--password", default="password123")
    run.add_argument("--database-url", default=None)
    run.add_argument("--output-root", default=str(OUTPUT_ROOT))

    report = subparsers.add_parser("report")
    report.add_argument("--run-dir", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "run":
        run_dir = run_acceptance(args)
        print(run_dir)
        return
    run_dir = Path(args.run_dir).expanduser().resolve()
    print(json.dumps(load_summary(run_dir), ensure_ascii=False, indent=2))


def run_acceptance(args: argparse.Namespace) -> Path:
    run_dir = Path(args.output_root).expanduser().resolve() / f"agent-bilingual-acceptance-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    live_eval.touch_file(run_dir / REST_RESULTS_FILE)
    live_eval.touch_file(run_dir / MCP_RESULTS_FILE)
    live_eval.touch_file(run_dir / MIXED_RESULTS_FILE)

    rest_results = run_rest_agent_acceptance(run_dir=run_dir, args=args)
    mcp_results = run_mcp_acceptance(run_dir=run_dir, args=args)
    mixed_results = run_mixed_language_acceptance(run_dir=run_dir, args=args)
    manual_notes = run_manual_prompt_eval(run_dir=run_dir, args=args)
    backend_results = run_backend_sampling(run_dir=run_dir, args=args)

    scenario_plan = {
        "generated_at": live_eval.utc_now_iso(),
        "rest_agent": len(rest_results),
        "mcp_tools": len(mcp_results),
        "mixed_language": len(mixed_results),
        "backend_sampling": len(backend_results),
        "manual_prompt_count": len(manual_notes["items"]),
    }
    live_eval.write_json(run_dir / SCENARIO_PLAN_FILE, scenario_plan)
    (run_dir / MANUAL_NOTES_FILE).write_text(render_manual_notes(manual_notes), encoding="utf-8")

    summary = build_summary(
        rest_results=rest_results,
        mcp_results=mcp_results,
        mixed_results=mixed_results,
        backend_results=backend_results,
        manual_notes=manual_notes,
    )
    live_eval.write_json(run_dir / SUMMARY_JSON_FILE, summary)
    (run_dir / SUMMARY_FILE).write_text(render_summary(summary), encoding="utf-8")
    return run_dir


def run_rest_agent_acceptance(*, run_dir: Path, args: argparse.Namespace) -> list[AcceptanceResult]:
    fixture, client, headers = build_rest_fixture(args)
    change_id = int(fixture["pending_change_ids"][0])
    family_id = int(fixture["family_id"])
    source_id = int(fixture["source_id"])
    label_learning_change_id = int(fixture["label_learning_change_id"])
    family_relink_raw_type_id = int(fixture["family_relink_raw_type_id"])
    family_relink_target_family_id = int(fixture["family_relink_target_family_id"])

    scenarios: list[tuple[str, str, str, str, str | None, dict[str, Any] | None]] = [
        ("rest_agent", "rest.workspace.zh", "GET", "/agent/context/workspace?language_code=zh-CN", "zh-CN", None),
        ("rest_agent", "rest.workspace.en", "GET", "/agent/context/workspace?language_code=en", "en", None),
        ("rest_agent", "rest.change_context.zh", "GET", f"/agent/context/changes/{change_id}?language_code=zh-CN", "zh-CN", None),
        ("rest_agent", "rest.change_context.en", "GET", f"/agent/context/changes/{change_id}?language_code=en", "en", None),
        ("rest_agent", "rest.source_context.zh", "GET", f"/agent/context/sources/{source_id}?language_code=zh-CN", "zh-CN", None),
        ("rest_agent", "rest.source_context.en", "GET", f"/agent/context/sources/{source_id}?language_code=en", "en", None),
        ("rest_agent", "rest.family_context.zh", "GET", f"/agent/context/families/{family_id}?language_code=zh-CN", "zh-CN", None),
        ("rest_agent", "rest.family_context.en", "GET", f"/agent/context/families/{family_id}?language_code=en", "en", None),
    ]
    results: list[AcceptanceResult] = []
    proposal_ids: list[int] = []
    ticket_ids: list[str] = []

    for surface, scenario_id, method, path, language_code, payload in scenarios:
        response = client.request(method, path, headers=headers, json=payload)
        response_json = response.json()
        result = build_result_from_payload(
            surface=surface,
            scenario_id=scenario_id,
            expected_language_code=language_code,
            account_language_code=current_account_language(client, headers),
            response_json=response_json,
            success=response.status_code == 200,
            note=f"{method} {path}",
        )
        append_result(run_dir / REST_RESULTS_FILE, result)
        results.append(result)

    for language_code, target_change_id in (("zh-CN", change_id), ("en", int(fixture["pending_change_ids"][1]))):
        response = client.post(
            "/agent/proposals/change-decision",
            headers=headers,
            json={"change_id": target_change_id, "language_code": language_code},
        )
        response_json = response.json()
        if response.status_code == 201 and isinstance(response_json.get("proposal_id"), int):
            proposal_ids.append(int(response_json["proposal_id"]))
        result = build_result_from_payload(
            surface="rest_agent",
            scenario_id=f"rest.change_decision_proposal.{language_code}",
            expected_language_code=language_code,
            account_language_code=current_account_language(client, headers),
            response_json=response_json,
            success=response.status_code == 201,
            note="create change decision proposal",
        )
        append_result(run_dir / REST_RESULTS_FILE, result)
        results.append(result)

    for language_code in ("zh-CN", "en"):
        response = client.post(
            "/agent/proposals/change-edit-commit",
            headers=headers,
            json={
                "change_id": int(fixture["pending_change_ids"][2]),
                "language_code": language_code,
                "patch": {
                    "event_name": "作业三更新" if language_code == "zh-CN" else "Homework Three Updated",
                    "due_date": "2026-03-30",
                },
            },
        )
        response_json = response.json()
        if response.status_code == 201 and isinstance(response_json.get("proposal_id"), int):
            proposal_ids.append(int(response_json["proposal_id"]))
        result = build_result_from_payload(
            surface="rest_agent",
            scenario_id=f"rest.change_edit_proposal.{language_code}",
            expected_language_code=language_code,
            account_language_code=current_account_language(client, headers),
            response_json=response_json,
            success=response.status_code == 201,
            note="create change edit commit proposal",
        )
        append_result(run_dir / REST_RESULTS_FILE, result)
        results.append(result)

    for language_code in ("zh-CN", "en"):
        payloads = [
            ("source_recovery", "/agent/proposals/source-recovery", {"source_id": source_id, "language_code": language_code}),
            ("family_preview", "/agent/proposals/family-relink-preview", {"raw_type_id": family_relink_raw_type_id, "family_id": family_relink_target_family_id, "language_code": language_code}),
            ("family_commit", "/agent/proposals/family-relink-commit", {"raw_type_id": family_relink_raw_type_id, "family_id": family_relink_target_family_id, "language_code": language_code}),
            ("label_learning", "/agent/proposals/label-learning-commit", {"change_id": label_learning_change_id, "family_id": family_id, "language_code": language_code}),
        ]
        for label, path, payload in payloads:
            response = client.post(path, headers=headers, json=payload)
            response_json = response.json()
            if response.status_code == 201 and isinstance(response_json.get("proposal_id"), int):
                proposal_ids.append(int(response_json["proposal_id"]))
            protected = []
            if label.startswith("family"):
                protected = ["write-up", "Project"]
            elif label == "label_learning":
                protected = ["HW", "Homework"]
            result = build_result_from_payload(
                surface="rest_agent",
                scenario_id=f"rest.{label}.{language_code}",
                expected_language_code=language_code,
                account_language_code=current_account_language(client, headers),
                response_json=response_json,
                success=response.status_code == 201,
                note=f"create {label} proposal",
                protected_strings=protected,
            )
            append_result(run_dir / REST_RESULTS_FILE, result)
            results.append(result)

    for language_code in ("zh-CN", "en"):
        list_response = client.get(f"/agent/proposals?language_code={language_code}", headers=headers)
        list_json = list_response.json()
        result = build_result_from_payload(
            surface="rest_agent",
            scenario_id=f"rest.list_proposals.{language_code}",
            expected_language_code=language_code,
            account_language_code=current_account_language(client, headers),
            response_json=list_json[0] if isinstance(list_json, list) and list_json else {},
            success=list_response.status_code == 200,
            note="list proposals",
        )
        append_result(run_dir / REST_RESULTS_FILE, result)
        results.append(result)
        if proposal_ids:
            get_response = client.get(f"/agent/proposals/{proposal_ids[-1]}?language_code={language_code}", headers=headers)
            get_json = get_response.json()
            result = build_result_from_payload(
                surface="rest_agent",
                scenario_id=f"rest.get_proposal.{language_code}",
                expected_language_code=language_code,
                account_language_code=current_account_language(client, headers),
                response_json=get_json,
                success=get_response.status_code == 200,
                note="get proposal",
            )
            append_result(run_dir / REST_RESULTS_FILE, result)
            results.append(result)

    for language_code, proposal_id in zip(("zh-CN", "en"), proposal_ids[:2], strict=False):
        ticket_create = client.post(
            "/agent/approval-tickets",
            headers=headers,
            json={"proposal_id": proposal_id, "channel": "web", "language_code": language_code},
        )
        ticket_json = ticket_create.json()
        if ticket_create.status_code == 201 and isinstance(ticket_json.get("ticket_id"), str):
            ticket_ids.append(str(ticket_json["ticket_id"]))
        result = build_result_from_payload(
            surface="rest_agent",
            scenario_id=f"rest.create_ticket.{language_code}",
            expected_language_code=language_code,
            account_language_code=current_account_language(client, headers),
            response_json=ticket_json,
            success=ticket_create.status_code == 201,
            note="create approval ticket",
        )
        append_result(run_dir / REST_RESULTS_FILE, result)
        results.append(result)

    for language_code, ticket_id in zip(("zh-CN", "en"), ticket_ids, strict=False):
        get_response = client.get(f"/agent/approval-tickets/{ticket_id}?language_code={language_code}", headers=headers)
        get_json = get_response.json()
        result = build_result_from_payload(
            surface="rest_agent",
            scenario_id=f"rest.get_ticket.{language_code}",
            expected_language_code=language_code,
            account_language_code=current_account_language(client, headers),
            response_json=get_json,
            success=get_response.status_code == 200,
            note="get approval ticket",
        )
        append_result(run_dir / REST_RESULTS_FILE, result)
        results.append(result)

    for language_code in ("zh-CN", "en"):
        list_response = client.get(f"/agent/approval-tickets?language_code={language_code}", headers=headers)
        list_json = list_response.json()
        result = build_result_from_payload(
            surface="rest_agent",
            scenario_id=f"rest.list_tickets.{language_code}",
            expected_language_code=language_code,
            account_language_code=current_account_language(client, headers),
            response_json=list_json[0] if isinstance(list_json, list) and list_json else {},
            success=list_response.status_code == 200,
            note="list approval tickets",
        )
        append_result(run_dir / REST_RESULTS_FILE, result)
        results.append(result)

    for language_code, ticket_id in zip(("zh-CN", "en"), ticket_ids, strict=False):
        confirm_response = client.post(
            f"/agent/approval-tickets/{ticket_id}/confirm",
            headers=headers,
            json={"language_code": language_code},
        )
        confirm_json = confirm_response.json()
        result = build_result_from_payload(
            surface="rest_agent",
            scenario_id=f"rest.confirm_ticket.{language_code}",
            expected_language_code=language_code,
            account_language_code=current_account_language(client, headers),
            response_json=confirm_json,
            success=confirm_response.status_code == 200,
            note="confirm approval ticket",
        )
        append_result(run_dir / REST_RESULTS_FILE, result)
        results.append(result)

    cancel_change_id = int(fixture["pending_change_ids"][3])
    for language_code in ("zh-CN", "en"):
        proposal_response = client.post(
            "/agent/proposals/change-decision",
            headers=headers,
            json={"change_id": cancel_change_id, "language_code": language_code},
        )
        proposal_json = proposal_response.json()
        if not (proposal_response.status_code == 201 and isinstance(proposal_json.get("proposal_id"), int)):
            result = build_result_from_payload(
                surface="rest_agent",
                scenario_id=f"rest.cancel_ticket.{language_code}",
                expected_language_code=language_code,
                account_language_code=current_account_language(client, headers),
                response_json=proposal_json,
                success=False,
                note="failed to create proposal for cancel flow",
            )
            append_result(run_dir / REST_RESULTS_FILE, result)
            results.append(result)
            continue
        ticket_response = client.post(
            "/agent/approval-tickets",
            headers=headers,
            json={"proposal_id": int(proposal_json["proposal_id"]), "channel": "web", "language_code": language_code},
        )
        ticket_json = ticket_response.json()
        if not (ticket_response.status_code == 201 and isinstance(ticket_json.get("ticket_id"), str)):
            result = build_result_from_payload(
                surface="rest_agent",
                scenario_id=f"rest.cancel_ticket.{language_code}",
                expected_language_code=language_code,
                account_language_code=current_account_language(client, headers),
                response_json=ticket_json,
                success=False,
                note="failed to create ticket for cancel flow",
            )
            append_result(run_dir / REST_RESULTS_FILE, result)
            results.append(result)
            continue
        cancel_response = client.post(
            f"/agent/approval-tickets/{ticket_json['ticket_id']}/cancel",
            headers=headers,
            json={"language_code": language_code},
        )
        cancel_json = cancel_response.json()
        result = build_result_from_payload(
            surface="rest_agent",
            scenario_id=f"rest.cancel_ticket.{language_code}",
            expected_language_code=language_code,
            account_language_code=current_account_language(client, headers),
            response_json=cancel_json,
            success=cancel_response.status_code == 200,
            note="cancel approval ticket",
        )
        append_result(run_dir / REST_RESULTS_FILE, result)
        results.append(result)
    return results


def run_mcp_acceptance(*, run_dir: Path, args: argparse.Namespace) -> list[AcceptanceResult]:
    fixture = bootstrap_fixture(args)
    email = str(fixture["email"])
    change_ids = {
        "zh-CN": int(fixture["pending_change_ids"][0]),
        "en": int(fixture["pending_change_ids"][1]),
    }
    change_id = change_ids["zh-CN"]
    family_id = int(fixture["family_id"])
    source_id = int(fixture["source_id"])
    label_learning_change_id = int(fixture["label_learning_change_id"])
    family_relink_raw_type_id = int(fixture["family_relink_raw_type_id"])
    family_relink_target_family_id = int(fixture["family_relink_target_family_id"])
    results: list[AcceptanceResult] = []
    request_counter = {"value": 0}

    def next_ctx(label: str) -> Context:
        request_counter["value"] += 1
        request = SimpleNamespace(user=None)
        request_context = RequestContext(
            request_id=f"agent-bilingual-{request_counter['value']:02d}-{label}",
            meta=None,
            session=None,
            lifespan_context=None,
            request=request,
        )
        return Context(request_context=request_context, fastmcp=None)  # type: ignore[arg-type]

    tool_calls: list[tuple[str, Callable[..., Any], dict[str, Any]]] = []
    for language_code in ("zh-CN", "en"):
        tool_calls.extend(
            [
                (f"mcp.workspace.{language_code}", mcp_main.get_workspace_context_tool, {"email": email, "language_code": language_code, "ctx": next_ctx(f"workspace-{language_code}")}),
                (f"mcp.recent.{language_code}", mcp_main.get_recent_agent_activity_tool, {"email": email, "limit": 10, "language_code": language_code, "ctx": next_ctx(f"recent-{language_code}")}),
                (f"mcp.pending.{language_code}", mcp_main.list_pending_changes_tool, {"email": email, "limit": 10, "language_code": language_code, "ctx": next_ctx(f"pending-{language_code}")}),
                (f"mcp.sources.{language_code}", mcp_main.list_sources_tool, {"email": email, "status": "all", "language_code": language_code, "ctx": next_ctx(f"sources-{language_code}")}),
                (f"mcp.change_context.{language_code}", mcp_main.get_change_context_tool, {"change_id": change_id, "email": email, "language_code": language_code, "ctx": next_ctx(f"change-{language_code}")}),
                (f"mcp.source_context.{language_code}", mcp_main.get_source_context_tool, {"source_id": source_id, "email": email, "language_code": language_code, "ctx": next_ctx(f"source-{language_code}")}),
                (f"mcp.family_context.{language_code}", mcp_main.get_family_context_tool, {"family_id": family_id, "email": email, "language_code": language_code, "ctx": next_ctx(f"family-{language_code}")}),
                (f"mcp.create_change_proposal.{language_code}", mcp_main.create_change_decision_proposal_tool, {"change_id": change_ids[language_code], "email": email, "language_code": language_code, "ctx": next_ctx(f"proposal-change-{language_code}")}),
                (f"mcp.create_change_edit_proposal.{language_code}", mcp_main.create_change_edit_commit_proposal_tool, {"change_id": int(fixture["pending_change_ids"][1]), "patch": {"event_name": "作业四更新" if language_code == "zh-CN" else "Homework Four Updated", "due_date": "2026-03-31"}, "email": email, "language_code": language_code, "ctx": next_ctx(f"proposal-edit-{language_code}")}),
                (f"mcp.create_source_recovery.{language_code}", mcp_main.create_source_recovery_proposal_tool, {"source_id": source_id, "email": email, "language_code": language_code, "ctx": next_ctx(f"proposal-source-{language_code}")}),
                (f"mcp.create_family_preview.{language_code}", mcp_main.create_family_relink_preview_proposal_tool, {"raw_type_id": family_relink_raw_type_id, "family_id": family_relink_target_family_id, "email": email, "language_code": language_code, "ctx": next_ctx(f"proposal-family-preview-{language_code}")}),
                (f"mcp.create_family_commit.{language_code}", mcp_main.create_family_relink_commit_proposal_tool, {"raw_type_id": family_relink_raw_type_id, "family_id": family_relink_target_family_id, "email": email, "language_code": language_code, "ctx": next_ctx(f"proposal-family-commit-{language_code}")}),
                (f"mcp.create_label_learning.{language_code}", mcp_main.create_label_learning_commit_proposal_tool, {"change_id": label_learning_change_id, "family_id": family_id, "email": email, "language_code": language_code, "ctx": next_ctx(f"proposal-label-{language_code}")}),
            ]
        )

    latest_proposal_ids: dict[str, int] = {}
    decision_proposal_ids: dict[str, int] = {}
    latest_ticket_ids: dict[str, str] = {}
    for scenario_id, fn, kwargs in tool_calls:
        response = fn(**kwargs)
        payload = model_or_dict(response)
        language_code = kwargs.get("language_code")
        if scenario_id.startswith("mcp.create_") and isinstance(payload.get("proposal_id"), int):
            latest_proposal_ids[str(language_code)] = int(payload["proposal_id"])
        if scenario_id.startswith("mcp.create_change_proposal.") and isinstance(payload.get("proposal_id"), int):
            decision_proposal_ids[str(language_code)] = int(payload["proposal_id"])
        result = build_result_from_payload(
            surface="mcp_tools",
            scenario_id=scenario_id,
            expected_language_code=str(language_code) if isinstance(language_code, str) else None,
            account_language_code="en",
            response_json=payload,
            success=True,
            note=fn.__name__,
            protected_strings=["write-up", "Project"] if "family" in scenario_id else None,
        )
        append_result(run_dir / MCP_RESULTS_FILE, result)
        results.append(result)

    for language_code in ("zh-CN", "en"):
        proposal_id = latest_proposal_ids[str(language_code)]
        proposal_payload = model_or_dict(
            mcp_main.get_proposal_tool(
                proposal_id=proposal_id,
                email=email,
                language_code=language_code,
                ctx=next_ctx(f"get-proposal-{language_code}"),
            )
        )
        result = build_result_from_payload(
            surface="mcp_tools",
            scenario_id=f"mcp.get_proposal.{language_code}",
            expected_language_code=language_code,
            account_language_code="en",
            response_json=proposal_payload,
            success=True,
            note="get proposal",
        )
        append_result(run_dir / MCP_RESULTS_FILE, result)
        results.append(result)

        list_payload = model_or_dict(
            mcp_main.list_proposals_tool(
                email=email,
                status="all",
                limit=10,
                language_code=language_code,
                ctx=next_ctx(f"list-proposals-{language_code}"),
            )
        )
        first_item = (list_payload.get("items") or [{}])[0] if isinstance(list_payload, dict) else {}
        result = build_result_from_payload(
            surface="mcp_tools",
            scenario_id=f"mcp.list_proposals.{language_code}",
            expected_language_code=language_code,
            account_language_code="en",
            response_json=first_item,
            success=True,
            note="list proposals",
        )
        append_result(run_dir / MCP_RESULTS_FILE, result)
        results.append(result)

        ticket_payload = model_or_dict(
            mcp_main.create_approval_ticket_tool(
                proposal_id=decision_proposal_ids[str(language_code)],
                email=email,
                channel="mcp",
                language_code=language_code,
                ctx=next_ctx(f"create-ticket-{language_code}"),
            )
        )
        latest_ticket_ids[str(language_code)] = str(ticket_payload["ticket_id"])
        result = build_result_from_payload(
            surface="mcp_tools",
            scenario_id=f"mcp.create_ticket.{language_code}",
            expected_language_code=language_code,
            account_language_code="en",
            response_json=ticket_payload,
            success=True,
            note="create approval ticket",
        )
        append_result(run_dir / MCP_RESULTS_FILE, result)
        results.append(result)

        get_ticket_payload = model_or_dict(
            mcp_main.get_approval_ticket_tool(
                ticket_id=str(ticket_payload["ticket_id"]),
                email=email,
                language_code=language_code,
                ctx=next_ctx(f"get-ticket-{language_code}"),
            )
        )
        result = build_result_from_payload(
            surface="mcp_tools",
            scenario_id=f"mcp.get_ticket.{language_code}",
            expected_language_code=language_code,
            account_language_code="en",
            response_json=get_ticket_payload,
            success=True,
            note="get approval ticket",
        )
        append_result(run_dir / MCP_RESULTS_FILE, result)
        results.append(result)

        list_tickets_payload = model_or_dict(
            mcp_main.list_approval_tickets_tool(
                email=email,
                status="all",
                limit=10,
                language_code=language_code,
                ctx=next_ctx(f"list-tickets-{language_code}"),
            )
        )
        first_ticket = (list_tickets_payload.get("items") or [{}])[0] if isinstance(list_tickets_payload, dict) else {}
        result = build_result_from_payload(
            surface="mcp_tools",
            scenario_id=f"mcp.list_tickets.{language_code}",
            expected_language_code=language_code,
            account_language_code="en",
            response_json=first_ticket,
            success=True,
            note="list approval tickets",
        )
        append_result(run_dir / MCP_RESULTS_FILE, result)
        results.append(result)

        confirm_payload = model_or_dict(
            mcp_main.confirm_approval_ticket_tool(
                ticket_id=str(ticket_payload["ticket_id"]),
                email=email,
                language_code=language_code,
                ctx=next_ctx(f"confirm-ticket-{language_code}"),
            )
        )
        result = build_result_from_payload(
            surface="mcp_tools",
            scenario_id=f"mcp.confirm_ticket.{language_code}",
            expected_language_code=language_code,
            account_language_code="en",
            response_json=confirm_payload,
            success=True,
            note="confirm approval ticket",
        )
        append_result(run_dir / MCP_RESULTS_FILE, result)
        results.append(result)

    cancel_language = "zh-CN"
    cancel_proposal_payload = model_or_dict(
        mcp_main.create_change_decision_proposal_tool(
            change_id=int(fixture["pending_change_ids"][2]),
            email=email,
            language_code=cancel_language,
            ctx=next_ctx("cancel-proposal-zh"),
        )
    )
    cancel_ticket_payload = model_or_dict(
        mcp_main.create_approval_ticket_tool(
            proposal_id=int(cancel_proposal_payload["proposal_id"]),
            email=email,
            channel="mcp",
            language_code=cancel_language,
            ctx=next_ctx("cancel-ticket-create-zh"),
        )
    )
    cancel_payload = model_or_dict(
        mcp_main.cancel_approval_ticket_tool(
            ticket_id=str(cancel_ticket_payload["ticket_id"]),
            email=email,
            language_code=cancel_language,
            ctx=next_ctx("cancel-ticket-zh"),
        )
    )
    result = build_result_from_payload(
        surface="mcp_tools",
        scenario_id="mcp.cancel_ticket.zh-CN",
        expected_language_code=cancel_language,
        account_language_code="en",
        response_json=cancel_payload,
        success=True,
        note="cancel approval ticket",
    )
    append_result(run_dir / MCP_RESULTS_FILE, result)
    results.append(result)
    return results


def run_mixed_language_acceptance(*, run_dir: Path, args: argparse.Namespace) -> list[AcceptanceResult]:
    fixture, client, headers = build_rest_fixture(args)
    user_id = int(fixture["user_id"])
    results: list[AcceptanceResult] = []
    patch_change_id = int(fixture["pending_change_ids"][1])

    scenarios = [
        {
            "scenario_id": "mixed.detect.zh_input_en_account",
            "account_language": "en",
            "payload": {"change_id": patch_change_id, "patch": {"event_name": "作业三更新", "due_date": "2026-03-30"}},
            "expected_language": "zh-CN",
            "expected_resolution": "detected_input",
        },
        {
            "scenario_id": "mixed.detect.en_input_zh_account",
            "account_language": "zh-CN",
            "payload": {"change_id": patch_change_id, "patch": {"event_name": "Homework Three Updated", "due_date": "2026-03-30"}},
            "expected_language": "en",
            "expected_resolution": "detected_input",
        },
        {
            "scenario_id": "mixed.override.en",
            "account_language": "zh-CN",
            "payload": {"change_id": patch_change_id, "language_code": "en", "patch": {"event_name": "作业三更新", "due_date": "2026-03-30"}},
            "expected_language": "en",
            "expected_resolution": "explicit",
        },
        {
            "scenario_id": "mixed.override.zh",
            "account_language": "en",
            "payload": {"change_id": patch_change_id, "language_code": "zh-CN", "patch": {"event_name": "Homework Three Updated", "due_date": "2026-03-30"}},
            "expected_language": "zh-CN",
            "expected_resolution": "explicit",
        },
    ]

    for scenario in scenarios:
        set_user_language_code(user_id=user_id, language_code=scenario["account_language"])
        response = client.post("/agent/proposals/change-edit-commit", headers=headers, json=scenario["payload"])
        payload = response.json()
        result = build_result_from_payload(
            surface="mixed_language",
            scenario_id=scenario["scenario_id"],
            expected_language_code=scenario["expected_language"],
            account_language_code=scenario["account_language"],
            response_json=payload,
            success=response.status_code == 201 and payload.get("language_resolution_source") == scenario["expected_resolution"],
            note="mixed-language proposal generation",
        )
        append_result(run_dir / MIXED_RESULTS_FILE, result)
        results.append(result)

    assisted_results = run_llm_assisted_mixed_scenarios(run_dir=run_dir, args=args)
    results.extend(assisted_results)
    return results


def run_llm_assisted_mixed_scenarios(*, run_dir: Path, args: argparse.Namespace) -> list[AcceptanceResult]:
    fixture, client, headers = build_rest_fixture(args)
    user_id = int(fixture["user_id"])
    patch_change_id = int(fixture["pending_change_ids"][2])
    import app.modules.agents.generation_gateway as generation_gateway

    scenarios = [
        ("mixed.llm_assisted.zh_ok", "zh-CN", "en", {"summary": "请在回放审核中通过这条变更。", "reason": "当前时间变更明确，系统状态一致。"}, False),
        ("mixed.llm_assisted.en_ok", "en", "zh-CN", {"summary": "Approve this replay change.", "reason": "The due date change is clear and internally consistent."}, False),
        ("mixed.llm_assisted.zh_fallback", "zh-CN", "en", {"summary": "Approve this replay change.", "reason": "The due date change is clear and internally consistent."}, True),
    ]
    results: list[AcceptanceResult] = []

    @contextmanager
    def llm_assisted(fake_payload: dict[str, Any]):
        previous_mode = os.environ.get("AGENT_GENERATION_MODE")
        previous_invoke = generation_gateway.invoke_llm_json
        os.environ["AGENT_GENERATION_MODE"] = "llm_assisted"
        get_settings.cache_clear()

        def _fake_invoke(db, *, invoke_request):  # type: ignore[no-untyped-def]
            from app.modules.llm_gateway.contracts import LlmInvokeResult

            del db
            del invoke_request
            return LlmInvokeResult(
                json_object=fake_payload,
                provider_id="agent-env-default",
                protocol="chat_completions",
                model="acceptance-fake",
                latency_ms=5,
                raw_usage={},
            )

        generation_gateway.invoke_llm_json = _fake_invoke
        try:
            yield
        finally:
            generation_gateway.invoke_llm_json = previous_invoke
            if previous_mode is None:
                os.environ.pop("AGENT_GENERATION_MODE", None)
            else:
                os.environ["AGENT_GENERATION_MODE"] = previous_mode
            get_settings.cache_clear()

    for scenario_id, target_language, account_language, fake_payload, expect_fallback in scenarios:
        set_user_language_code(user_id=user_id, language_code=account_language)
        with llm_assisted(fake_payload):
            response = client.post(
                "/agent/proposals/change-edit-commit",
                headers=headers,
                json={
                    "change_id": patch_change_id,
                    "language_code": target_language,
                    "patch": {
                        "event_name": "Homework 三 Updated",
                        "due_date": "2026-04-01",
                    },
                },
            )
        payload = response.json()
        fallback_observed = bool(expect_fallback and payload.get("summary") != fake_payload["summary"])
        result = build_result_from_payload(
            surface="mixed_language",
            scenario_id=scenario_id,
            expected_language_code=target_language,
            account_language_code=account_language,
            response_json=payload,
            success=response.status_code == 201 and (fallback_observed if expect_fallback else payload.get("language_code") == target_language),
            note="llm-assisted bilingual narrative",
        )
        result_dict = result.to_dict()
        result_dict["llm_assisted_expected_fallback"] = expect_fallback
        result_dict["llm_assisted_fallback_observed"] = fallback_observed
        live_eval.append_jsonl(run_dir / MIXED_RESULTS_FILE, result_dict)
        results.append(result)
    return results


def run_manual_prompt_eval(*, run_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    fixture = bootstrap_fixture(args)
    email = str(fixture["email"])
    user_id = int(fixture["user_id"])
    proposal_change_id = int(fixture["pending_change_ids"][0])
    confirm_change_ids = [
        int(fixture["pending_change_ids"][1]),
        int(fixture["pending_change_ids"][2]),
    ]
    prompts = [
        ("manual.zh.workspace", "请总结一下我现在的工作区状态", "workspace", "en", None),
        ("manual.en.workspace", "Can you summarize my current workspace state?", "workspace", "zh-CN", None),
        ("manual.zh.proposal", "请帮我为第一条待处理变更生成 proposal", "proposal", "en", None),
        ("manual.en.proposal", "Please create a proposal for my first pending change.", "proposal", "zh-CN", None),
        ("manual.zh.confirm", "请确认执行刚创建的审批票据", "confirm", "en", None),
        ("manual.en.confirm", "Please confirm the approval ticket that was just created.", "confirm", "zh-CN", None),
    ]
    items: list[dict[str, Any]] = []
    request_counter = {"value": 0}

    def next_ctx(label: str) -> Context:
        request_counter["value"] += 1
        request = SimpleNamespace(user=None)
        request_context = RequestContext(
            request_id=f"agent-bilingual-manual-{request_counter['value']:02d}-{label}",
            meta=None,
            session=None,
            lifespan_context=None,
            request=request,
        )
        return Context(request_context=request_context, fastmcp=None)  # type: ignore[arg-type]

    for scenario_id, prompt, operation, account_language, explicit_language in prompts:
        set_user_language_code(user_id=user_id, language_code=account_language)
        language_context = get_user_language_context(
            user_id=user_id,
            explicit_language_code=explicit_language,
            input_texts=[prompt],
        )
        if operation == "workspace":
            payload = model_or_dict(mcp_main.get_workspace_context_tool(email=email, language_code=language_context.effective_language_code, ctx=next_ctx(operation)))
        elif operation == "proposal":
            payload = model_or_dict(
                mcp_main.create_change_decision_proposal_tool(
                    change_id=proposal_change_id,
                    email=email,
                    language_code=language_context.effective_language_code,
                    ctx=next_ctx(operation),
                )
            )
        else:
            confirm_change_id = confirm_change_ids.pop(0)
            proposal = model_or_dict(
                mcp_main.create_change_decision_proposal_tool(
                    change_id=confirm_change_id,
                    email=email,
                    language_code=language_context.effective_language_code,
                    ctx=next_ctx(f"{operation}-proposal"),
                )
            )
            ticket = model_or_dict(
                mcp_main.create_approval_ticket_tool(
                    proposal_id=int(proposal["proposal_id"]),
                    email=email,
                    language_code=language_context.effective_language_code,
                    ctx=next_ctx(f"{operation}-ticket"),
                )
            )
            payload = model_or_dict(
                mcp_main.confirm_approval_ticket_tool(
                    ticket_id=str(ticket["ticket_id"]),
                    email=email,
                    language_code=language_context.effective_language_code,
                    ctx=next_ctx(operation),
                )
            )
        actual_language, mixed = detect_payload_language(payload)
        items.append(
            {
                "scenario_id": scenario_id,
                "prompt": prompt,
                "operation": operation,
                "account_language_code": account_language,
                "explicit_language_code": explicit_language,
                "input_language_code": language_context.input_language_code,
                "effective_language_code": language_context.effective_language_code,
                "language_resolution_source": language_context.resolution_source,
                "actual_output_language_code": actual_language,
                "mixed_language_output": mixed,
                "wrong_language": actual_language is not None and actual_language != language_context.effective_language_code,
                "response_excerpt": excerpt_payload(payload),
            }
        )
    return {"generated_at": live_eval.utc_now_iso(), "items": items}


def run_backend_sampling(*, run_dir: Path, args: argparse.Namespace) -> list[AcceptanceResult]:
    fixture, client, headers = build_rest_fixture(args)
    user_id = int(fixture["user_id"])
    change_id = int(fixture["pending_change_ids"][0])
    source_id = int(fixture["source_id"])
    results: list[AcceptanceResult] = []
    for language_code in ("zh-CN", "en"):
        set_user_language_code(user_id=user_id, language_code=language_code)
        for scenario_id, path in (
            (f"backend.changes_summary.{language_code}", "/changes/summary"),
            (f"backend.change_item.{language_code}", f"/changes/{change_id}"),
            (f"backend.source_observability.{language_code}", f"/sources/{source_id}/observability"),
        ):
            response = client.get(path, headers=headers)
            payload = response.json()
            result = build_result_from_payload(
                surface="backend_sampling",
                scenario_id=scenario_id,
                expected_language_code=language_code,
                account_language_code=language_code,
                response_json=payload,
                success=response.status_code == 200,
                note=path,
            )
            append_result(run_dir / REST_RESULTS_FILE, result)
            results.append(result)
    return results


def build_rest_fixture(args: argparse.Namespace) -> tuple[dict[str, Any], TestClient, dict[str, str]]:
    fixture = bootstrap_fixture(args)
    client = build_test_client()
    headers = {"X-API-Key": get_settings().app_api_key}
    login = client.post("/auth/login", headers=headers, json={"email": fixture["email"], "password": args.password})
    if login.status_code != 200:
        raise AcceptanceFailure(f"login failed: {login.text}")
    return fixture, client, headers


def bootstrap_fixture(args: argparse.Namespace) -> dict[str, Any]:
    claw_smoke.configure_smoke_database(database_url=str(args.database_url).strip() if args.database_url else None)
    reset_schema_guard_cache()
    fixture = claw_smoke.seed_fixture(
        email=str(args.email),
        other_email=str(args.other_email),
        password=str(args.password),
    )
    return fixture


def build_test_client() -> TestClient:
    reset_engine()
    get_settings.cache_clear()
    reset_schema_guard_cache()
    from services.app_api.main import app

    return TestClient(app)


def set_user_language_code(*, user_id: int, language_code: str) -> None:
    session_factory = claw_smoke.get_session_factory()
    with session_factory() as db:
        from app.db.models.shared import User
        user = db.scalar(select(User).where(User.id == user_id).limit(1))
        if user is None:
            raise AcceptanceFailure(f"user {user_id} not found")
        user.language_code = language_code
        db.commit()


def get_user_language_context(*, user_id: int, explicit_language_code: str | None, input_texts: list[str]) -> AgentLanguageContext:
    session_factory = claw_smoke.get_session_factory()
    with session_factory() as db:
        return resolve_agent_language_context(
            db,
            user_id=user_id,
            explicit_language_code=explicit_language_code,
            input_texts=input_texts,
        )


def current_account_language(client: TestClient, headers: dict[str, str]) -> str | None:
    response = client.get("/settings/profile", headers=headers)
    if response.status_code != 200:
        return None
    payload = response.json()
    value = payload.get("language_code")
    return value if isinstance(value, str) else None


def append_result(path: Path, result: AcceptanceResult) -> None:
    live_eval.append_jsonl(path, result.to_dict())


def model_or_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        payload = value.model_dump(mode="json")
        return payload if isinstance(payload, dict) else {}
    return value if isinstance(value, dict) else {}


def build_result_from_payload(
    *,
    surface: str,
    scenario_id: str,
    expected_language_code: str | None,
    account_language_code: str | None,
    response_json: dict[str, Any],
    success: bool,
    note: str | None,
    protected_strings: list[str] | None = None,
) -> AcceptanceResult:
    actual_language_code, mixed_language_output = detect_payload_language(response_json)
    resolution_source = response_json.get("language_resolution_source") if isinstance(response_json.get("language_resolution_source"), str) else None
    forbidden_translation = detect_forbidden_translation(response_json=response_json, protected_strings=protected_strings or [])
    wrong_language = (
        expected_language_code is not None
        and actual_language_code is not None
        and actual_language_code != expected_language_code
    )
    return AcceptanceResult(
        surface=surface,
        scenario_id=scenario_id,
        success=success and not wrong_language and not forbidden_translation,
        expected_language_code=expected_language_code,
        actual_language_code=actual_language_code,
        account_language_code=account_language_code,
        input_language_code=response_json.get("input_language_code") if isinstance(response_json.get("input_language_code"), str) else None,
        language_resolution_source=resolution_source,
        wrong_language=wrong_language,
        mixed_language_output=mixed_language_output,
        forbidden_translation_violation=forbidden_translation,
        note=note,
        response_excerpt=excerpt_payload(response_json),
    )


def detect_payload_language(payload: dict[str, Any]) -> tuple[str | None, bool]:
    texts = extract_user_facing_text(payload)
    actual = detect_agent_input_language(texts)
    combined = " ".join(texts)
    mixed = bool(actual is None and has_cjk(combined) and has_latin(combined))
    return actual, mixed


def extract_user_facing_text(value: object) -> list[str]:
    output: list[str] = []
    _extract_texts(value, output)
    return output


def _extract_texts(value: object, output: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {
                "summary",
                "reason",
                "detail",
                "message",
                "label",
                "confirm_summary",
                "cancel_summary",
                "transition_message",
                "why_now",
                "suggested_action_reason",
                "risk_summary",
                "impact_summary",
                "next_action_label",
            } and isinstance(item, str) and item.strip():
                output.append(item.strip())
            elif key in {
                "recommended_next_action",
                "blocking_conditions",
                "items",
                "summary",
                "observability",
                "change",
                "source",
                "family",
                "source_recovery",
                "operator_guidance",
                "decision_support",
                "outcome_preview",
            }:
                _extract_texts(item, output)
    elif isinstance(value, list):
        for item in value:
            _extract_texts(item, output)


def detect_forbidden_translation(*, response_json: dict[str, Any], protected_strings: list[str]) -> bool:
    if not protected_strings:
        return False
    try:
        texts = json.dumps(response_json, ensure_ascii=False, sort_keys=True)
    except Exception:
        texts = " ".join(extract_user_facing_text(response_json))
    return not any(value and value in texts for value in protected_strings)


def has_cjk(text: str) -> bool:
    return any(0x4E00 <= ord(ch) <= 0x9FFF for ch in text)


def has_latin(text: str) -> bool:
    return any("a" <= ch.lower() <= "z" for ch in text)


def excerpt_payload(payload: Any, *, max_length: int = 1000) -> str | None:
    try:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except Exception:
        raw = str(payload)
    if len(raw) <= max_length:
        return raw
    return f"{raw[: max_length - 3]}..."


def build_summary(
    *,
    rest_results: list[AcceptanceResult],
    mcp_results: list[AcceptanceResult],
    mixed_results: list[AcceptanceResult],
    backend_results: list[AcceptanceResult],
    manual_notes: dict[str, Any],
) -> dict[str, Any]:
    all_results = [*rest_results, *mcp_results, *mixed_results, *backend_results]
    pass_count = sum(1 for row in all_results if row.success)
    fail_count = len(all_results) - pass_count
    by_surface = {
        "rest_agent": summarize_surface(rest_results),
        "mcp_tools": summarize_surface(mcp_results),
        "mixed_language": summarize_surface(mixed_results),
        "backend_sampling": summarize_surface(backend_results),
    }
    by_resolution: dict[str, int] = {"explicit": 0, "detected_input": 0, "user_profile": 0, "default": 0}
    for row in all_results:
        if row.language_resolution_source in by_resolution:
            by_resolution[row.language_resolution_source] += 1
    return {
        "generated_at": live_eval.utc_now_iso(),
        "total_scenarios": len(all_results),
        "pass_count": pass_count,
        "fail_count": fail_count,
        "by_surface": by_surface,
        "by_language_resolution_source": by_resolution,
        "wrong_language_output_count": sum(1 for row in all_results if row.wrong_language),
        "mixed_language_output_count": sum(1 for row in all_results if row.mixed_language_output),
        "forbidden_translation_violations": sum(1 for row in all_results if row.forbidden_translation_violation),
        "deterministic_fallback_count": sum(1 for row in mixed_results if row.scenario_id.endswith("fallback")),
        "llm_assisted_wrong_language_fallback_count": sum(1 for row in mixed_results if "llm_assisted" in row.scenario_id and row.scenario_id.endswith("fallback")),
        "manual_prompt_count": len(manual_notes.get("items") or []),
    }


def summarize_surface(results: list[AcceptanceResult]) -> dict[str, Any]:
    return {
        "total": len(results),
        "passed": sum(1 for row in results if row.success),
        "failed": sum(1 for row in results if not row.success),
    }


def render_manual_notes(payload: dict[str, Any]) -> str:
    lines = [
        "# Manual Eval Notes",
        "",
        f"- Generated at: {payload.get('generated_at')}",
        "",
    ]
    for item in payload.get("items") or []:
        lines.extend(
            [
                f"## {item['scenario_id']}",
                f"- Prompt: {item['prompt']}",
                f"- Operation: {item['operation']}",
                f"- Account language: `{item['account_language_code']}`",
                f"- Explicit language override: `{item['explicit_language_code']}`",
                f"- Input language: `{item['input_language_code']}`",
                f"- Effective language: `{item['effective_language_code']}`",
                f"- Resolution source: `{item['language_resolution_source']}`",
                f"- Actual output language: `{item['actual_output_language_code']}`",
                f"- Mixed-language output: `{item['mixed_language_output']}`",
                f"- Wrong-language output: `{item['wrong_language']}`",
                f"- Response excerpt: `{item['response_excerpt']}`",
                "",
            ]
        )
    return "\n".join(lines)


def render_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# Agent Bilingual Acceptance",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Total scenarios: `{summary['total_scenarios']}`",
        f"- Pass: `{summary['pass_count']}`",
        f"- Fail: `{summary['fail_count']}`",
        "",
        "## Surfaces",
        "",
    ]
    for key, payload in summary["by_surface"].items():
        lines.append(f"- `{key}`: total=`{payload['total']}` passed=`{payload['passed']}` failed=`{payload['failed']}`")
    lines.extend(
        [
            "",
            "## Language Quality",
            "",
            f"- wrong_language_output_count: `{summary['wrong_language_output_count']}`",
            f"- mixed_language_output_count: `{summary['mixed_language_output_count']}`",
            f"- forbidden_translation_violations: `{summary['forbidden_translation_violations']}`",
            f"- deterministic_fallback_count: `{summary['deterministic_fallback_count']}`",
            f"- llm_assisted_wrong_language_fallback_count: `{summary['llm_assisted_wrong_language_fallback_count']}`",
            "",
            "## Resolution Sources",
            "",
        ]
    )
    for key, value in summary["by_language_resolution_source"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    return "\n".join(lines)


def load_summary(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / SUMMARY_JSON_FILE).read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
