from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.agents import AgentCommandRun, AgentCommandRunStatus
from app.modules.agents.command_planner import generate_command_plan
from app.modules.agents.command_registry import (
    AgentCommandExecutionBoundary,
    AgentCommandScopeKind,
    command_tool_spec,
)
from app.modules.agents.gateway import (
    AgentGatewayOrigin,
    cancel_approval_ticket_for_user,
    confirm_approval_ticket_for_user,
    create_approval_ticket_for_proposal,
    create_change_decision_proposal,
    create_change_edit_commit_proposal,
    create_family_relink_commit_proposal,
    create_family_relink_preview_proposal,
    create_label_learning_commit_proposal,
    create_source_recovery_proposal,
    get_approval_ticket_for_user,
    get_change_context,
    get_family_context,
    get_recent_activity,
    get_source_context,
    get_workspace_context,
)
from app.modules.agents.language_context import resolve_agent_language_context
from app.modules.changes.change_listing_service import list_changes
from app.modules.sources.read_service import build_source_read_payload
from app.modules.sources.sources_service import list_input_sources


class AgentCommandNotFoundError(RuntimeError):
    pass


class AgentCommandInvalidStateError(RuntimeError):
    pass


class AgentCommandValidationError(RuntimeError):
    pass


def plan_workspace_command_for_user(
    db: Session,
    *,
    user_id: int,
    input_text: str,
    scope_kind: str | None,
    scope_id: int | None,
    language_code: str | None,
) -> dict[str, Any]:
    normalized_scope_kind: AgentCommandScopeKind = _normalize_scope_kind(scope_kind)
    language_context = resolve_agent_language_context(
        db,
        user_id=user_id,
        explicit_language_code=language_code,
        input_texts=[input_text],
    )
    scope_snapshot = build_scope_snapshot(
        db=db,
        user_id=user_id,
        scope_kind=normalized_scope_kind,
        scope_id=scope_id,
        language_code=language_context.effective_language_code,
    )
    command_id = uuid4().hex
    plan_payload = generate_command_plan(
        db,
        command_id=command_id,
        input_text=input_text,
        language_context=language_context,
        scope_snapshot=scope_snapshot,
    )
    row = AgentCommandRun(
        command_id=command_id,
        user_id=user_id,
        input_text=input_text.strip(),
        scope_kind=normalized_scope_kind,
        scope_id=str(scope_id) if scope_id is not None else None,
        language_code=language_context.effective_language_code,
        language_resolution_source=language_context.resolution_source,
        status=AgentCommandRunStatus(str(plan_payload["status"])),
        status_reason=str(plan_payload.get("status_reason") or ""),
        plan_json={
            "steps": list(jsonable_encoder(plan_payload.get("steps") or [])),
            "scope_snapshot": jsonable_encoder(scope_snapshot),
        },
        execution_results_json={"results_by_step": {}},
        executed_at=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize_agent_command_run(row)


def get_agent_command_run_for_user(
    db: Session,
    *,
    user_id: int,
    command_id: str,
) -> dict[str, Any] | None:
    row = db.scalar(
        select(AgentCommandRun)
        .where(AgentCommandRun.command_id == command_id, AgentCommandRun.user_id == user_id)
        .limit(1)
    )
    if row is None:
        return None
    return serialize_agent_command_run(row)


def execute_agent_command_run_for_user(
    db: Session,
    *,
    user_id: int,
    command_id: str,
    selected_step_ids: list[str] | None,
    language_code: str | None,
) -> dict[str, Any]:
    row = db.scalar(
        select(AgentCommandRun)
        .where(AgentCommandRun.command_id == command_id, AgentCommandRun.user_id == user_id)
        .with_for_update()
    )
    if row is None:
        raise AgentCommandNotFoundError("Agent command run not found")
    if row.status in {AgentCommandRunStatus.CLARIFICATION_REQUIRED, AgentCommandRunStatus.UNSUPPORTED}:
        raise AgentCommandInvalidStateError("This command requires clarification or is unsupported and cannot be executed")

    steps = list((row.plan_json or {}).get("steps") or [])
    if not steps:
        raise AgentCommandInvalidStateError("This command has no executable steps")

    selected_ids = _resolve_selected_step_ids(steps=steps, selected_step_ids=selected_step_ids)
    language_context = resolve_agent_language_context(
        db,
        user_id=user_id,
        explicit_language_code=language_code or row.language_code,
    )

    results_by_step = dict(((row.execution_results_json or {}).get("results_by_step") or {}))
    row.status = AgentCommandRunStatus.EXECUTING
    row.status_reason = None
    db.commit()
    db.refresh(row)

    first_failure: str | None = None
    executed_any = False
    executed_at = datetime.now(UTC)

    for step in steps:
        step_id = str(step.get("step_id") or "")
        if step_id not in selected_ids:
            continue
        existing = results_by_step.get(step_id)
        if isinstance(existing, dict) and existing.get("status") == "succeeded":
            continue

        unsatisfied = [
            dep
            for dep in step.get("depends_on") or []
            if str(((results_by_step.get(dep) or {}).get("status") or "")) != "succeeded"
        ]
        if unsatisfied:
            results_by_step[step_id] = _step_result_payload(
                step_id=step_id,
                status="blocked",
                error_text=f"Blocked by unresolved dependencies: {', '.join(unsatisfied)}",
            )
            continue

        started_at = datetime.now(UTC)
        try:
            resolved_args = _resolve_step_args(step.get("args") or {}, results_by_step=results_by_step)
            output = _execute_step(
                db=db,
                user_id=user_id,
                command_id=command_id,
                step=step,
                args=resolved_args,
                language_code=language_context.effective_language_code,
            )
            results_by_step[step_id] = _step_result_payload(
                step_id=step_id,
                status="succeeded",
                output_summary=_summarize_command_output(output),
                raw_output=output,
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )
        except Exception as exc:
            results_by_step[step_id] = _step_result_payload(
                step_id=step_id,
                status="failed",
                error_text=str(exc),
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )
            if first_failure is None:
                first_failure = str(exc)
        executed_any = True

    row.execution_results_json = {"results_by_step": jsonable_encoder(results_by_step)}
    if executed_any:
        row.executed_at = executed_at
    all_succeeded = all(
        str(((results_by_step.get(str(step.get("step_id") or "")) or {}).get("status") or "")) == "succeeded"
        for step in steps
    )
    if first_failure is not None:
        row.status = AgentCommandRunStatus.FAILED
        row.status_reason = first_failure[:1000]
    elif all_succeeded:
        row.status = AgentCommandRunStatus.COMPLETED
        row.status_reason = None
    else:
        row.status = AgentCommandRunStatus.PLANNED
        row.status_reason = "partial_execution"
    db.commit()
    db.refresh(row)
    return serialize_agent_command_run(row)


def serialize_agent_command_run(row: AgentCommandRun) -> dict[str, Any]:
    plan_steps = list((row.plan_json or {}).get("steps") or [])
    results_by_step = dict(((row.execution_results_json or {}).get("results_by_step") or {}))
    results = []
    seen: set[str] = set()
    for step in plan_steps:
        step_id = str(step.get("step_id") or "")
        seen.add(step_id)
        result = results_by_step.get(step_id) or {}
        results.append(
            {
                "step_id": step_id,
                "status": str(result.get("status") or "pending"),
                "output_summary": dict(result.get("output_summary") or {}),
                "error_text": result.get("error_text"),
                "started_at": result.get("started_at"),
                "finished_at": result.get("finished_at"),
            }
        )
    for step_id, result in results_by_step.items():
        if step_id in seen:
            continue
        results.append(
            {
                "step_id": step_id,
                "status": str(result.get("status") or "pending"),
                "output_summary": dict(result.get("output_summary") or {}),
                "error_text": result.get("error_text"),
                "started_at": result.get("started_at"),
                "finished_at": result.get("finished_at"),
            }
        )
    return {
        "command_id": row.command_id,
        "owner_user_id": row.user_id,
        "input_text": row.input_text,
        "scope_kind": row.scope_kind,
        "scope_id": int(row.scope_id) if isinstance(row.scope_id, str) and row.scope_id.isdigit() else None,
        "language_code": row.language_code,
        "language_resolution_source": row.language_resolution_source,
        "status": row.status.value,
        "status_reason": row.status_reason,
        "plan": plan_steps,
        "execution_results": results,
        "executed_at": row.executed_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def build_scope_snapshot(
    *,
    db: Session,
    user_id: int,
    scope_kind: AgentCommandScopeKind,
    scope_id: int | None,
    language_code: str,
) -> dict[str, Any]:
    if scope_kind == "workspace":
        workspace = get_workspace_context(db=db, user_id=user_id, language_code=language_code)
        recent_activity = get_recent_activity(db=db, user_id=user_id, limit=10, language_code=language_code)
        pending_changes = list_changes(
            db,
            user_id=user_id,
            review_status="pending",
            review_bucket="all",
            intake_phase="all",
            source_id=None,
            limit=10,
            offset=0,
            language_code=language_code,
        )
        sources = [
            build_source_read_payload(db, source=row, language_code=language_code)
            for row in list_input_sources(db, user_id=user_id, status="active")
        ]
        return {
            "scope_kind": "workspace",
            "workspace_context": {
                "recommended_next_action": workspace.get("recommended_next_action"),
                "blocking_conditions": workspace.get("blocking_conditions"),
                "available_next_tools": workspace.get("available_next_tools"),
                "summary": workspace.get("summary"),
                "top_pending_changes": workspace.get("top_pending_changes"),
            },
            "recent_activity": (recent_activity or {}).get("items") or [],
            "pending_changes": pending_changes,
            "sources": sources,
        }
    if scope_kind == "change":
        if scope_id is None:
            raise AgentCommandValidationError("scope_id is required for change scope")
        return {
            "scope_kind": "change",
            "change_context": get_change_context(db=db, user_id=user_id, change_id=scope_id, language_code=language_code),
        }
    if scope_kind == "source":
        if scope_id is None:
            raise AgentCommandValidationError("scope_id is required for source scope")
        return {
            "scope_kind": "source",
            "source_context": get_source_context(db=db, user_id=user_id, source_id=scope_id, language_code=language_code),
        }
    if scope_kind == "family":
        if scope_id is None:
            raise AgentCommandValidationError("scope_id is required for family scope")
        return {
            "scope_kind": "family",
            "family_context": get_family_context(db=db, user_id=user_id, family_id=scope_id, language_code=language_code),
        }
    raise AgentCommandValidationError(f"unsupported scope kind: {scope_kind}")


def _resolve_selected_step_ids(*, steps: list[dict[str, Any]], selected_step_ids: list[str] | None) -> set[str]:
    available_ids = {str(step.get("step_id") or "") for step in steps}
    if selected_step_ids is None:
        return available_ids
    selected = {str(item or "").strip() for item in selected_step_ids if str(item or "").strip()}
    if not selected:
        raise AgentCommandValidationError("selected_step_ids must not be empty")
    unknown = sorted(selected - available_ids)
    if unknown:
        raise AgentCommandValidationError(f"selected_step_ids contains unknown steps: {', '.join(unknown)}")
    return selected


def _resolve_step_args(args: Any, *, results_by_step: dict[str, dict[str, Any]]) -> Any:
    if isinstance(args, dict):
        if "$ref" in args and len(args) == 1:
            return _resolve_step_ref(str(args["$ref"]), results_by_step=results_by_step)
        return {key: _resolve_step_args(value, results_by_step=results_by_step) for key, value in args.items()}
    if isinstance(args, list):
        return [_resolve_step_args(value, results_by_step=results_by_step) for value in args]
    return args


def _resolve_step_ref(ref: str, *, results_by_step: dict[str, dict[str, Any]]) -> Any:
    parts = [segment for segment in str(ref or "").split(".") if segment]
    if len(parts) < 2:
        raise AgentCommandValidationError(f"invalid step ref: {ref}")
    step_id = parts[0]
    payload = results_by_step.get(step_id) or {}
    if str(payload.get("status") or "") != "succeeded":
        raise AgentCommandValidationError(f"step ref requires a succeeded dependency: {ref}")
    current: Any = payload.get("raw_output")
    for segment in parts[1:]:
        if isinstance(current, dict) and segment in current:
            current = current[segment]
            continue
        raise AgentCommandValidationError(f"step ref path not found: {ref}")
    return deepcopy(current)


def _execute_step(
    *,
    db: Session,
    user_id: int,
    command_id: str,
    step: dict[str, Any],
    args: dict[str, Any],
    language_code: str,
) -> Any:
    tool_name = str(step.get("tool_name") or "")
    command_tool_spec(tool_name)
    origin = AgentGatewayOrigin(kind="command", label="workspace_command", request_id=command_id)

    if tool_name == "get_workspace_context":
        return get_workspace_context(db=db, user_id=user_id, language_code=language_code)
    if tool_name == "get_recent_agent_activity":
        return get_recent_activity(
            db=db,
            user_id=user_id,
            limit=max(1, min(int(args.get("limit") or 10), 50)),
            language_code=language_code,
        )
    if tool_name == "list_pending_changes":
        return list_changes(
            db,
            user_id=user_id,
            review_status="pending",
            review_bucket=str(args.get("review_bucket") or "all"),
            intake_phase=str(args.get("intake_phase") or "all"),
            source_id=None,
            limit=max(1, min(int(args.get("limit") or 10), 50)),
            offset=0,
            language_code=language_code,
        )
    if tool_name == "list_sources":
        return [
            build_source_read_payload(db, source=row, language_code=language_code)
            for row in list_input_sources(db, user_id=user_id, status=str(args.get("status") or "active"))
        ]
    if tool_name == "get_change_context":
        return get_change_context(db=db, user_id=user_id, change_id=int(args["change_id"]), language_code=language_code)
    if tool_name == "get_source_context":
        return get_source_context(db=db, user_id=user_id, source_id=int(args["source_id"]), language_code=language_code)
    if tool_name == "get_family_context":
        return get_family_context(db=db, user_id=user_id, family_id=int(args["family_id"]), language_code=language_code)
    if tool_name == "create_change_decision_proposal":
        return create_change_decision_proposal(
            db=db,
            user_id=user_id,
            change_id=int(args["change_id"]),
            origin=origin,
            language_code=language_code,
        )
    if tool_name == "create_change_edit_commit_proposal":
        return create_change_edit_commit_proposal(
            db=db,
            user_id=user_id,
            change_id=int(args["change_id"]),
            patch=dict(args.get("patch") or {}),
            origin=origin,
            language_code=language_code,
        )
    if tool_name == "create_source_recovery_proposal":
        return create_source_recovery_proposal(
            db=db,
            user_id=user_id,
            source_id=int(args["source_id"]),
            origin=origin,
            language_code=language_code,
        )
    if tool_name == "create_family_relink_preview_proposal":
        return create_family_relink_preview_proposal(
            db=db,
            user_id=user_id,
            raw_type_id=int(args["raw_type_id"]),
            family_id=int(args["family_id"]),
            origin=origin,
            language_code=language_code,
        )
    if tool_name == "create_family_relink_commit_proposal":
        return create_family_relink_commit_proposal(
            db=db,
            user_id=user_id,
            raw_type_id=int(args["raw_type_id"]),
            family_id=int(args["family_id"]),
            origin=origin,
            language_code=language_code,
        )
    if tool_name == "create_label_learning_commit_proposal":
        return create_label_learning_commit_proposal(
            db=db,
            user_id=user_id,
            change_id=int(args["change_id"]),
            family_id=int(args["family_id"]),
            origin=origin,
            language_code=language_code,
        )
    if tool_name == "create_approval_ticket":
        return create_approval_ticket_for_proposal(
            db=db,
            user_id=user_id,
            proposal_id=int(args["proposal_id"]),
            channel=str(args.get("channel") or "command"),
            origin=origin,
            language_code=language_code,
        )
    if tool_name == "get_approval_ticket":
        ticket = get_approval_ticket_for_user(
            db=db,
            user_id=user_id,
            ticket_id=str(args["ticket_id"]),
            language_code=language_code,
        )
        if ticket is None:
            raise AgentCommandNotFoundError("Approval ticket not found")
        return ticket
    if tool_name == "confirm_approval_ticket":
        return confirm_approval_ticket_for_user(
            db=db,
            user_id=user_id,
            ticket_id=str(args["ticket_id"]),
            origin=origin,
            language_code=language_code,
        )
    if tool_name == "cancel_approval_ticket":
        return cancel_approval_ticket_for_user(
            db=db,
            user_id=user_id,
            ticket_id=str(args["ticket_id"]),
            origin=origin,
            language_code=language_code,
        )

    raise AgentCommandValidationError(f"unsupported tool execution: {tool_name}")


def _summarize_command_output(output: Any) -> dict[str, Any]:
    if isinstance(output, list):
        return {
            "item_count": len(output),
            "first_item_id": _first_list_item_id(output),
        }
    if isinstance(output, dict):
        summary = {}
        for key in (
            "command_id",
            "proposal_id",
            "ticket_id",
            "status",
            "target_kind",
            "target_id",
            "summary",
            "summary_code",
            "risk_level",
        ):
            if key in output:
                summary[key] = output.get(key)
        if not summary:
            summary["keys"] = sorted(output.keys())[:10]
        return summary
    return {"value": output}


def _first_list_item_id(output: list[Any]) -> Any:
    if not output:
        return None
    first = output[0]
    if not isinstance(first, dict):
        return None
    for key in ("id", "source_id", "proposal_id", "ticket_id", "change_id"):
        if key in first:
            return first.get(key)
    return None


def _step_result_payload(
    *,
    step_id: str,
    status: str,
    output_summary: dict[str, Any] | None = None,
    raw_output: Any = None,
    error_text: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "status": status,
        "output_summary": dict(jsonable_encoder(output_summary or {})),
        "raw_output": jsonable_encoder(raw_output) if raw_output is not None else None,
        "error_text": error_text,
        "started_at": started_at.isoformat() if started_at is not None else None,
        "finished_at": finished_at.isoformat() if finished_at is not None else None,
    }


def _normalize_scope_kind(value: str | None) -> AgentCommandScopeKind:
    normalized = str(value or "workspace").strip().lower() or "workspace"
    if normalized not in {"workspace", "change", "source", "family"}:
        raise AgentCommandValidationError("scope_kind must be one of: workspace, change, source, family")
    return normalized  # type: ignore[return-value]
