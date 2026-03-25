#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.fastmcp.server import RequestContext
from sqlalchemy import create_engine, text
from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.db.models.shared import CourseWorkItemLabelFamily, CourseWorkItemRawType
from app.db.session import get_session_factory, reset_engine
from app.modules.agents.mcp_audit_service import list_mcp_tool_invocations
from app.modules.common.course_identity import normalize_label_token
from services.mcp_server.main import (
    create_approval_ticket_impl,
    create_change_decision_proposal_impl,
    create_change_edit_commit_proposal_impl,
    create_family_relink_commit_proposal_impl,
    create_family_relink_preview_proposal_impl,
    confirm_approval_ticket_impl,
    get_change_context_impl,
    get_family_context_impl,
    get_recent_agent_activity_impl,
    get_workspace_context_impl,
)

OUTPUT_ROOT = REPO_ROOT / "output"


@dataclass
class SmokeStep:
    name: str
    ok: bool
    detail: str
    payload: dict[str, Any] | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a reproducible backend-side Claw/MCP smoke against the local CalendarDIFF codebase.")
    parser.add_argument("--email", default="agent-live-eval@example.com")
    parser.add_argument("--other-email", default="agent-live-eval-other@example.com")
    parser.add_argument("--password", default="password123")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--output-root", default=str(OUTPUT_ROOT))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_dir = Path(args.output_root).expanduser().resolve() / f"claw-mcp-smoke-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    configure_smoke_database(database_url=str(args.database_url).strip() if args.database_url else None)

    fixture = seed_fixture(
        email=str(args.email),
        other_email=str(args.other_email),
        password=str(args.password),
    )

    steps: list[SmokeStep] = []
    request_counter = 0

    def next_ctx(label: str) -> Context:
        nonlocal request_counter
        request_counter += 1
        request = SimpleNamespace(user=None)
        request_context = RequestContext(
            request_id=f"claw-smoke-{request_counter:02d}-{label}",
            meta=None,
            session=None,
            lifespan_context=None,
            request=request,
        )
        return Context(request_context=request_context, fastmcp=None)  # type: ignore[arg-type]

    try:
        recent_before = get_recent_agent_activity_impl(email=fixture["email"], limit=5, ctx=next_ctx("recent-before"))
        steps.append(SmokeStep("recent_activity_before", True, "Loaded recent agent activity.", {"count": len(recent_before.get("items") or [])}))

        workspace = get_workspace_context_impl(email=fixture["email"], ctx=next_ctx("workspace"))
        steps.append(
            SmokeStep(
                "workspace_context",
                True,
                "Loaded workspace context.",
                {
                    "changes_pending": int((workspace.get("summary") or {}).get("changes_pending") or 0),
                    "baseline_review_pending": int((workspace.get("summary") or {}).get("baseline_review_pending") or 0),
                },
            )
        )

        primary_change_id = int(fixture["pending_change_ids"][0])
        change_context = get_change_context_impl(change_id=primary_change_id, email=fixture["email"], ctx=next_ctx("change-context"))
        steps.append(SmokeStep("change_context", True, "Loaded pending change context.", {"change_id": change_context["change"]["id"]}))

        proposal = create_change_decision_proposal_impl(change_id=primary_change_id, email=fixture["email"], ctx=next_ctx("change-proposal"))
        steps.append(SmokeStep("change_proposal", True, "Created change proposal.", {"proposal_id": proposal["proposal_id"], "origin_request_id": proposal.get("origin_request_id")}))

        ticket = create_approval_ticket_impl(proposal_id=int(proposal["proposal_id"]), email=fixture["email"], ctx=next_ctx("ticket-create"))
        steps.append(SmokeStep("approval_ticket_create", True, "Created approval ticket.", {"ticket_id": ticket["ticket_id"], "origin_request_id": ticket.get("origin_request_id")}))

        confirmed = confirm_approval_ticket_impl(ticket_id=str(ticket["ticket_id"]), email=fixture["email"], ctx=next_ctx("ticket-confirm"))
        steps.append(
            SmokeStep(
                "approval_ticket_confirm",
                True,
                "Confirmed approval ticket.",
                {"ticket_id": confirmed["ticket_id"], "status": confirmed["status"], "transition_message_code": confirmed["transition_message_code"]},
            )
        )

        edit_change_id = int((fixture["pending_change_ids"] or [primary_change_id, primary_change_id])[1])
        edit_proposal = create_change_edit_commit_proposal_impl(
            change_id=edit_change_id,
            patch={"due_date": "2026-03-30", "event_name": "Homework 3 Edited"},
            email=fixture["email"],
            ctx=next_ctx("edit-proposal"),
        )
        steps.append(
            SmokeStep(
                "change_edit_commit_proposal",
                True,
                "Created proposal edit commit proposal.",
                {"proposal_id": edit_proposal["proposal_id"], "kind": edit_proposal["suggested_payload"]["kind"]},
            )
        )

        edit_ticket = create_approval_ticket_impl(proposal_id=int(edit_proposal["proposal_id"]), email=fixture["email"], ctx=next_ctx("edit-ticket-create"))
        steps.append(
            SmokeStep(
                "change_edit_commit_ticket_create",
                True,
                "Created proposal edit approval ticket.",
                {"ticket_id": edit_ticket["ticket_id"]},
            )
        )

        edit_confirmed = confirm_approval_ticket_impl(ticket_id=str(edit_ticket["ticket_id"]), email=fixture["email"], ctx=next_ctx("edit-ticket-confirm"))
        steps.append(
            SmokeStep(
                "change_edit_commit_ticket_confirm",
                True,
                "Confirmed proposal edit approval ticket.",
                {"ticket_id": edit_confirmed["ticket_id"], "result_kind": (edit_confirmed.get("executed_result") or {}).get("kind")},
            )
        )

        family_context = get_family_context_impl(family_id=int(fixture["family_id"]), email=fixture["email"], ctx=next_ctx("family-context"))
        steps.append(
            SmokeStep(
                "family_context",
                True,
                "Loaded family context.",
                {"family_id": family_context["family"]["id"], "pending_suggestions": len(family_context.get("pending_raw_type_suggestions") or [])},
            )
        )

        family_commit = create_family_relink_commit_proposal_impl(
            raw_type_id=int(fixture["family_relink_raw_type_id"]),
            family_id=int(fixture["family_relink_target_family_id"]),
            email=fixture["email"],
            ctx=next_ctx("family-commit-proposal"),
        )
        steps.append(
            SmokeStep(
                "family_relink_commit_proposal",
                True,
                "Created family relink commit proposal.",
                {"proposal_id": family_commit["proposal_id"], "kind": family_commit["suggested_payload"]["kind"]},
            )
        )

        family_commit_ticket = create_approval_ticket_impl(
            proposal_id=int(family_commit["proposal_id"]),
            email=fixture["email"],
            ctx=next_ctx("family-commit-ticket-create"),
        )
        steps.append(
            SmokeStep(
                "family_relink_commit_ticket_create",
                True,
                "Created family relink approval ticket.",
                {"ticket_id": family_commit_ticket["ticket_id"]},
            )
        )

        family_commit_confirmed = confirm_approval_ticket_impl(
            ticket_id=str(family_commit_ticket["ticket_id"]),
            email=fixture["email"],
            ctx=next_ctx("family-commit-ticket-confirm"),
        )
        steps.append(
            SmokeStep(
                "family_relink_commit_ticket_confirm",
                True,
                "Confirmed family relink approval ticket.",
                {"ticket_id": family_commit_confirmed["ticket_id"], "result_kind": (family_commit_confirmed.get("executed_result") or {}).get("kind")},
            )
        )

        raw_type_id, target_family_id = ensure_family_preview_fixture(
            user_id=int(fixture["user_id"]),
            source_family_id=int(fixture["family_id"]),
        )
        family_preview = create_family_relink_preview_proposal_impl(
            raw_type_id=raw_type_id,
            family_id=target_family_id,
            email=fixture["email"],
            ctx=next_ctx("family-preview"),
        )
        steps.append(
            SmokeStep(
                "family_relink_preview",
                True,
                "Created family relink preview proposal.",
                {
                    "proposal_id": family_preview["proposal_id"],
                    "execution_mode": family_preview["execution_mode"],
                    "can_create_ticket": family_preview["can_create_ticket"],
                },
            )
        )

        recent_after = get_recent_agent_activity_impl(email=fixture["email"], limit=10, ctx=next_ctx("recent-after"))
        steps.append(SmokeStep("recent_activity_after", True, "Loaded recent agent activity after actions.", {"count": len(recent_after.get("items") or [])}))

        settings_audit = fetch_mcp_invocations(user_id=int(fixture["user_id"]))
        steps.append(
            SmokeStep(
                "settings_mcp_invocations",
                True,
                "Loaded MCP invocation audit through the Settings-backed audit service.",
                {
                    "count": len(settings_audit),
                    "latest_tool_names": [row["tool_name"] for row in settings_audit[:5]],
                },
            )
        )
    except Exception as exc:
        steps.append(SmokeStep("unexpected_failure", False, str(exc), None))

    success = all(step.ok for step in steps)
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "success": success,
        "fixture": fixture,
        "steps": [step.__dict__ for step in steps],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_dir / "summary.md").write_text(render_markdown(summary), encoding="utf-8")
    print(run_dir)


def seed_fixture(*, email: str, other_email: str, password: str) -> dict[str, Any]:
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "seed_agent_live_eval_fixture.py"),
        "--email",
        email,
        "--other-email",
        other_email,
        "--password",
        password,
    ]
    completed = subprocess.run(command, cwd=str(REPO_ROOT), capture_output=True, text=True, env=os.environ.copy())
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip() or "seed fixture failed")
    return json.loads(completed.stdout)


def fetch_mcp_invocations(*, user_id: int) -> list[dict[str, Any]]:
    session_factory = get_session_factory()
    with session_factory() as db:
        rows = list_mcp_tool_invocations(db, user_id=user_id, limit=20)
        return [
            {
                "invocation_id": row.invocation_id,
                "tool_name": row.tool_name,
                "status": row.status.value,
                "proposal_id": row.proposal_id,
                "ticket_id": row.ticket_id,
                "created_at": row.created_at.isoformat(),
                "completed_at": row.completed_at.isoformat() if row.completed_at is not None else None,
            }
            for row in rows
        ]


def configure_smoke_database(*, database_url: str | None) -> None:
    settings = get_settings()
    target_url = database_url or settings.test_database_url
    os.environ["DATABASE_URL"] = target_url
    os.environ["TEST_DATABASE_URL"] = target_url
    get_settings.cache_clear()
    reset_engine()
    recreate_postgres_database(target_url)
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip() or "alembic upgrade head failed")
    get_settings.cache_clear()
    reset_engine()


def recreate_postgres_database(database_url: str) -> None:
    if not database_url.startswith("postgresql"):
        return
    db_name = database_url.rsplit("/", 1)[-1]
    admin_url = database_url.rsplit("/", 1)[0] + "/postgres"
    engine = create_engine(admin_url, future=True, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        engine.dispose()


def ensure_family_preview_fixture(*, user_id: int, source_family_id: int) -> tuple[int, int]:
    session_factory = get_session_factory()
    with session_factory() as db:
        source_family = db.scalar(
            select(CourseWorkItemLabelFamily)
            .where(CourseWorkItemLabelFamily.id == source_family_id, CourseWorkItemLabelFamily.user_id == user_id)
            .limit(1)
        )
        if source_family is None:
            raise RuntimeError("source family fixture missing")

        raw_type = db.scalar(
            select(CourseWorkItemRawType)
            .where(CourseWorkItemRawType.family_id == source_family.id)
            .order_by(CourseWorkItemRawType.id.asc())
            .limit(1)
        )
        if raw_type is None:
            raw_type = CourseWorkItemRawType(
                family_id=source_family.id,
                raw_type="write-up",
                normalized_raw_type=normalize_label_token("write-up"),
                metadata_json={},
            )
            db.add(raw_type)
            db.flush()

        target_family = db.scalar(
            select(CourseWorkItemLabelFamily)
            .where(
                CourseWorkItemLabelFamily.user_id == user_id,
                CourseWorkItemLabelFamily.normalized_course_identity == source_family.normalized_course_identity,
                CourseWorkItemLabelFamily.id != source_family.id,
            )
            .order_by(CourseWorkItemLabelFamily.id.asc())
            .limit(1)
        )
        if target_family is None:
            target_family = CourseWorkItemLabelFamily(
                user_id=user_id,
                course_dept=source_family.course_dept,
                course_number=source_family.course_number,
                course_suffix=source_family.course_suffix,
                course_quarter=source_family.course_quarter,
                course_year2=source_family.course_year2,
                normalized_course_identity=source_family.normalized_course_identity,
                canonical_label="Project",
                normalized_canonical_label=normalize_label_token("Project"),
            )
            db.add(target_family)
            db.flush()
        db.commit()
        db.refresh(raw_type)
        db.refresh(target_family)
        return int(raw_type.id), int(target_family.id)


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Claw MCP Smoke",
        "",
        f"- Generated at: {summary['generated_at']}",
        f"- Success: {'yes' if summary['success'] else 'no'}",
        f"- Notify email: {summary['fixture']['email']}",
        "",
        "## Steps",
        "",
    ]
    for step in summary["steps"]:
        marker = "PASS" if step["ok"] else "FAIL"
        lines.append(f"- `{marker}` `{step['name']}`: {step['detail']}")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
