#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.run_year_timeline_replay_smoke as replay

ACCEPTANCE_REPORT_FILE = "backend-acceptance-report.json"
ACCEPTANCE_NOTES_FILE = "backend-operator-notes.md"
DEFAULT_TIME_BUDGET_SECONDS = 4 * 60 * 60
DEFAULT_PENDING_LIMIT = 100
FAMILY_ACTION_CHECKPOINTS = {0, 1, 6, 12, 18}
MANUAL_ACTION_CHECKPOINT_INDEX = 6
RUNTIME_FAILURE_PATTERN = re.compile(r"request_id=(?P<request_id>[a-f0-9]+).*source_id=(?P<source_id>\d+)")


@dataclass(frozen=True)
class RuntimeFailureDetails:
    request_id: str | None
    source_id: int | None
    classification: str
    message: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run backend-only year timeline acceptance using public APIs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start")
    start.add_argument("--public-api-base", required=True)
    start.add_argument("--api-key", default="")
    start.add_argument("--manifest", default=str(replay.DEFAULT_MANIFEST))
    start.add_argument("--email-bucket", default=replay.DEFAULT_EMAIL_BUCKET)
    start.add_argument("--ics-derived-set", default=replay.DEFAULT_ICS_DERIVED_SET)
    start.add_argument("--fake-provider-host", default=replay.DEFAULT_FAKE_HOST)
    start.add_argument("--fake-provider-port", type=int, default=replay.DEFAULT_FAKE_PORT)
    start.add_argument("--start-fake-provider", action=argparse.BooleanOptionalAction, default=True)
    start.add_argument("--notify-email", default=None)
    start.add_argument("--auth-password", default="password123")
    start.add_argument("--time-budget-seconds", type=int, default=DEFAULT_TIME_BUDGET_SECONDS)
    start.add_argument("--max-checkpoints", type=int, default=None)

    cont = subparsers.add_parser("continue")
    cont.add_argument("--run-dir", required=True)
    cont.add_argument("--time-budget-seconds", type=int, default=DEFAULT_TIME_BUDGET_SECONDS)
    cont.add_argument("--max-checkpoints", type=int, default=None)

    report = subparsers.add_parser("report")
    report.add_argument("--run-dir", required=True)

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "start":
        run_dir = start_acceptance(args)
        print(run_dir)
        return
    run_dir = Path(args.run_dir).expanduser().resolve()
    if args.command == "continue":
        continue_acceptance(
            run_dir=run_dir,
            time_budget_seconds=int(args.time_budget_seconds),
            max_checkpoints=args.max_checkpoints,
        )
        print(run_dir)
        return
    if args.command == "report":
        print(json.dumps(load_acceptance_report(run_dir), ensure_ascii=False, indent=2))
        return
    raise SystemExit(f"unsupported command: {args.command}")


def start_acceptance(args: argparse.Namespace) -> Path:
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_year_timeline_replay_smoke.py"),
        "start",
        "--public-api-base",
        str(args.public_api_base),
        "--api-key",
        str(args.api_key),
        "--manifest",
        str(args.manifest),
        "--email-bucket",
        str(args.email_bucket),
        "--ics-derived-set",
        str(args.ics_derived_set),
        "--fake-provider-host",
        str(args.fake_provider_host),
        "--fake-provider-port",
        str(args.fake_provider_port),
        "--auth-password",
        str(args.auth_password),
    ]
    if bool(args.start_fake_provider):
        command.append("--start-fake-provider")
    else:
        command.append("--no-start-fake-provider")
    if args.notify_email:
        command.extend(["--notify-email", str(args.notify_email)])

    completed = subprocess.run(command, cwd=str(REPO_ROOT), capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip() or "replay start failed")
    run_dir = Path((completed.stdout or "").strip().splitlines()[-1]).resolve()
    initialize_acceptance_artifacts(run_dir)
    continue_acceptance(
        run_dir=run_dir,
        time_budget_seconds=int(args.time_budget_seconds),
        max_checkpoints=args.max_checkpoints,
    )
    return run_dir


def continue_acceptance(*, run_dir: Path, time_budget_seconds: int, max_checkpoints: int | None) -> None:
    report = load_acceptance_report(run_dir)
    replay_report = replay.build_report(run_dir)
    merge_replay_report(report, replay_report)
    client = build_client_from_run(run_dir)
    operator_state = report.setdefault(
        "operator_state",
        {
            "rejections_done": 0,
            "edits_done": 0,
            "family_renamed": False,
            "family_relinked": False,
            "family_created_id": None,
            "manual_created": False,
            "manual_updated": False,
            "manual_deleted": False,
            "manual_entity_uid": None,
        },
    )
    started = time.time()
    while True:
        state = replay.load_state(run_dir)
        merge_replay_report(report, replay.build_report(run_dir))
        if bool(state.get("finished")):
            finalize_acceptance_report(run_dir, report)
            return
        handled_count = len(report.get("checkpoints", []))
        if max_checkpoints is not None and handled_count >= max_checkpoints:
            report["status"] = "partial"
            report["stopped_reason"] = f"max_checkpoints_reached:{max_checkpoints}"
            save_acceptance_report(run_dir, report)
            return
        if time.time() - started > time_budget_seconds:
            report["status"] = "partial"
            report["stopped_reason"] = f"time_budget_exceeded:{time_budget_seconds}"
            save_acceptance_report(run_dir, report)
            append_note(
                run_dir,
                "\n## Run stopped\n"
                f"- Reason: exceeded {time_budget_seconds}s execution budget.\n",
            )
            return
        if bool(state.get("awaiting_manual")):
            checkpoint_index = int(state["current_checkpoint_index"])
            if any(item.get("checkpoint_index") == checkpoint_index for item in report.get("checkpoints", [])):
                resume_to_next_checkpoint(run_dir, report)
                continue
            handle_checkpoint(
                run_dir=run_dir,
                client=client,
                report=report,
                operator_state=operator_state,
                state=state,
            )
            resume_to_next_checkpoint(run_dir, report)
            continue
        if try_resume_idle_replay(run_dir=run_dir, client=client, report=report):
            continue
        time.sleep(5)


def handle_checkpoint(
    *,
    run_dir: Path,
    client: httpx.Client,
    report: dict[str, Any],
    operator_state: dict[str, Any],
    state: dict[str, Any],
) -> None:
    checkpoint_index = int(state["current_checkpoint_index"])
    checkpoint = dict(state["checkpoints"][checkpoint_index])
    started = time.monotonic()
    pending_changes = api_json_list(client, "/changes?review_status=pending&limit=100")
    families = api_json_list(client, "/families")
    sources = gather_source_context(run_dir=run_dir, client=client)
    actions = []

    approve_candidate = next((row for row in pending_changes if row.get("change_type") != "removed"), pending_changes[0] if pending_changes else None)
    approve_id = int(approve_candidate["id"]) if isinstance(approve_candidate, dict) and approve_candidate.get("id") is not None else None
    reject_candidate = next(
        (
            row
            for row in pending_changes
            if (row.get("change_type") == "removed" or has_odd_due_time(row))
            and (approve_id is None or int(row["id"]) != approve_id)
        ),
        None,
    )
    edit_candidate = next(
        (
            row
            for row in pending_changes
            if has_odd_due_time(row)
            and supports_proposal_edit(row)
            and (approve_id is None or int(row["id"]) != approve_id)
            and (reject_candidate is None or int(row["id"]) != int(reject_candidate["id"]))
        ),
        None,
    )

    if approve_candidate is not None:
        api_json(
            client,
            "POST",
            f"/changes/{approve_candidate['id']}/decisions",
            {"decision": "approve", "note": "backend acceptance approve"},
        )
        actions.append(
            {
                "kind": "approve",
                "change_id": int(approve_candidate["id"]),
                "label": display_label_for_change(approve_candidate),
            }
        )

    if reject_candidate is not None and int(operator_state.get("rejections_done") or 0) < 16:
        api_json(
            client,
            "POST",
            f"/changes/{reject_candidate['id']}/decisions",
            {"decision": "reject", "note": "backend acceptance reject suspicious or removed proposal"},
        )
        operator_state["rejections_done"] = int(operator_state.get("rejections_done") or 0) + 1
        actions.append(
            {
                "kind": "reject",
                "change_id": int(reject_candidate["id"]),
                "label": display_label_for_change(reject_candidate),
            }
        )

    if edit_candidate is not None and int(operator_state.get("edits_done") or 0) < 12:
        rounded = rounded_due_time(edit_candidate)
        if rounded is not None:
            patch = {"due_time": rounded}
            api_json(
                client,
                "POST",
                "/changes/edits/preview",
                {
                    "mode": "proposal",
                    "target": {"change_id": int(edit_candidate["id"])},
                    "patch": patch,
                    "reason": "backend acceptance normalize suspicious minute",
                },
            )
            api_json(
                client,
                "POST",
                "/changes/edits",
                {
                    "mode": "proposal",
                    "target": {"change_id": int(edit_candidate["id"])},
                    "patch": patch,
                    "reason": "backend acceptance normalize suspicious minute",
                },
            )
            api_json(
                client,
                "POST",
                f"/changes/{edit_candidate['id']}/decisions",
                {"decision": "approve", "note": "backend acceptance edit then approve"},
            )
            operator_state["edits_done"] = int(operator_state.get("edits_done") or 0) + 1
            actions.append(
                {
                    "kind": "edit_then_approve",
                    "change_id": int(edit_candidate["id"]),
                    "label": display_label_for_change(edit_candidate),
                    "patch": patch,
                }
            )

    if checkpoint_index in FAMILY_ACTION_CHECKPOINTS:
        actions.extend(run_family_actions(client=client, families=families, operator_state=operator_state))

    if checkpoint_index >= MANUAL_ACTION_CHECKPOINT_INDEX:
        actions.extend(run_manual_actions(client=client, families=families, operator_state=operator_state))

    elapsed_seconds = round(time.monotonic() - started, 1)
    checkpoint_entry = build_checkpoint_entry(
        checkpoint=checkpoint,
        checkpoint_index=checkpoint_index,
        pending_changes=pending_changes,
        families=families,
        actions=actions,
        sources=sources,
        elapsed_seconds=elapsed_seconds,
    )
    _upsert_checkpoint_entry(report, checkpoint_entry)
    save_acceptance_report(run_dir, report)
    append_note(run_dir, render_checkpoint_note(checkpoint_entry))


def run_family_actions(*, client: httpx.Client, families: list[dict[str, Any]], operator_state: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if not bool(operator_state.get("family_renamed")):
        target = next(
            (
                row
                for row in families
                if isinstance(row.get("canonical_label"), str) and row["canonical_label"] == row["canonical_label"].lower()
            ),
            None,
        )
        if target is not None:
            payload = {
                "canonical_label": title_case_label(target["canonical_label"]),
                "raw_types": target["raw_types"],
            }
            api_json(client, "PATCH", f"/families/{target['id']}", payload)
            operator_state["family_renamed"] = True
            actions.append({"kind": "family_rename", "family_id": int(target["id"]), "canonical_label": payload["canonical_label"]})

    if not bool(operator_state.get("family_relinked")):
        course_groups: dict[str, list[dict[str, Any]]] = {}
        for family in families:
            course_groups.setdefault(str(family["course_display"]), []).append(family)
        for group in course_groups.values():
            if len(group) < 2:
                continue
            project_family = next(
                (row for row in group if str(row.get("canonical_label") or "").lower() == "project" and row.get("raw_types")),
                None,
            )
            if project_family is None:
                continue
            raw_types = api_json_list(
                client,
                f"/families/raw-types?course_dept={project_family['course_dept']}&course_number={project_family['course_number']}&course_quarter={project_family['course_quarter'] or ''}&course_year2={project_family['course_year2'] or ''}",
            )
            project_raw = next((row for row in raw_types if str(row.get("raw_type") or "").lower() == "project"), None)
            if project_raw is None:
                continue
            created = api_json(
                client,
                "POST",
                "/families",
                {
                    "course_dept": project_family["course_dept"],
                    "course_number": project_family["course_number"],
                    "course_suffix": project_family["course_suffix"],
                    "course_quarter": project_family["course_quarter"],
                    "course_year2": project_family["course_year2"],
                    "canonical_label": "Deliverable",
                    "raw_types": [],
                },
            )
            api_json(
                client,
                "POST",
                "/families/raw-types/relink",
                {"raw_type_id": int(project_raw["id"]), "family_id": int(created["id"]), "note": "backend acceptance relink"},
            )
            operator_state["family_relinked"] = True
            operator_state["family_created_id"] = int(created["id"])
            actions.append(
                {
                    "kind": "family_create_and_relink",
                    "family_id": int(created["id"]),
                    "canonical_label": created["canonical_label"],
                    "raw_type_id": int(project_raw["id"]),
                }
            )
            break
    return actions


def run_manual_actions(*, client: httpx.Client, families: list[dict[str, Any]], operator_state: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    family_id = operator_state.get("family_created_id")
    if not isinstance(family_id, int):
        family_id = int(families[0]["id"]) if families else None
    if family_id is None:
        return actions

    if not bool(operator_state.get("manual_created")):
        created = api_json(
            client,
            "POST",
            "/manual/events",
            {
                "family_id": family_id,
                "event_name": "Operator Checkpoint Item 1",
                "raw_type": "checkpoint",
                "ordinal": 1,
                "due_date": "2026-07-15",
                "time_precision": "date_only",
                "reason": "backend acceptance manual create",
            },
        )
        operator_state["manual_created"] = True
        operator_state["manual_entity_uid"] = created["entity_uid"]
        actions.append({"kind": "manual_create", "entity_uid": created["entity_uid"]})
        return actions

    entity_uid = operator_state.get("manual_entity_uid")
    if not isinstance(entity_uid, str) or not entity_uid:
        return actions

    if not bool(operator_state.get("manual_updated")):
        api_json(
            client,
            "PATCH",
            f"/manual/events/{entity_uid}",
            {
                "family_id": family_id,
                "event_name": "Operator Checkpoint Item 1 Revised",
                "raw_type": "checkpoint",
                "ordinal": 1,
                "due_date": "2026-07-16",
                "time_precision": "date_only",
                "reason": "backend acceptance manual update",
            },
        )
        operator_state["manual_updated"] = True
        actions.append({"kind": "manual_update", "entity_uid": entity_uid})
        return actions

    if not bool(operator_state.get("manual_deleted")):
        api_json(client, "DELETE", f"/manual/events/{entity_uid}?reason=backend_acceptance_cleanup")
        operator_state["manual_deleted"] = True
        actions.append({"kind": "manual_delete", "entity_uid": entity_uid})
    return actions


def build_checkpoint_entry(
    *,
    checkpoint: dict[str, Any],
    checkpoint_index: int,
    pending_changes: list[dict[str, Any]],
    families: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    elapsed_seconds: float,
) -> dict[str, Any]:
    rating = "清晰"
    hardest = "可以看懂自己在做什么。"
    info_gap = "无"
    blocker = None
    if any(action["kind"].startswith("family_") or action["kind"].startswith("manual_") for action in actions):
        rating = "费解"
        hardest = "系统没有直接说明为什么当前应从 Changes 进入 Families 或 Manual。"
        info_gap = "缺少 lane routing 与治理动作触发理由。"
    if not actions:
        rating = "可接受"
        hardest = "需要花时间判断当前是否应该等待下一轮，而不是立刻做治理。"
        info_gap = "缺少明确的“当前无须操作”说明。"
    if any(source["runtime_issue"] for source in sources):
        rating = "明显阻塞"
        blocker = "runtime"
        hardest = "需要额外判断 source/runtime 问题是否会影响当前 change 决策。"
        info_gap = "缺少直接告诉操作者“现在应该停下来等系统恢复还是继续处理”的信号。"
    return {
        "checkpoint_index": checkpoint_index,
        "label": checkpoint["label"],
        "acted_at": datetime.now(UTC).isoformat(),
        "pending_change_count": len(pending_changes),
        "family_count": len(families),
        "actions": actions,
        "sources": sources,
        "elapsed_seconds": elapsed_seconds,
        "knows_what_is_happening": rating in {"清晰", "可接受"},
        "rating": rating,
        "hardest_step": hardest,
        "most_time_consuming_step": "决定哪些 change 应该 reject 或 edit，而不是简单 approve。",
        "missing_information": info_gap,
        "blocker": blocker,
    }


def render_checkpoint_note(entry: dict[str, Any]) -> str:
    lines = [
        f"## Checkpoint {entry['checkpoint_index']} — {entry['acted_at']}",
        f"- Label: `{entry['label']}`",
        f"- Pending changes seen: `{entry['pending_change_count']}`",
        f"- Families seen: `{entry['family_count']}`",
        f"- Actions taken: {format_actions(entry['actions'])}",
        f"- 我是否知道自己在干什么: `{'是' if entry['knows_what_is_happening'] else '否'}`",
        f"- Most difficult step: {entry['hardest_step']}",
        f"- Most time-consuming step: {entry['most_time_consuming_step']}",
        f"- Missing information: {entry['missing_information']}",
        f"- Rating: `{entry['rating']}`",
    ]
    if entry.get("blocker"):
        lines.append(f"- Blocker classification: `{entry['blocker']}`")
    lines.append("- Source posture:")
    lines.extend(source["line"] for source in entry["sources"])
    lines.append("")
    return "\n".join(lines)


def gather_source_context(*, run_dir: Path, client: httpx.Client) -> list[dict[str, Any]]:
    creds = json.loads((run_dir / replay.RUN_CREDS_FILE).read_text(encoding="utf-8"))
    source_ids = {int(creds["ics_source_id"]), int(creds["gmail_source_id"])}
    source_rows = api_json_list(client, "/sources?status=all")
    out = []
    for row in source_rows:
        if int(row["source_id"]) not in source_ids:
            continue
        obs = api_json(client, "GET", f"/sources/{row['source_id']}/observability")
        hist = api_json(client, "GET", f"/sources/{row['source_id']}/sync-history?limit=3")
        guidance = obs.get("operator_guidance") if isinstance(obs.get("operator_guidance"), dict) else {}
        line = (
            f"- Source {row['source_id']} {row['provider']}: runtime={row.get('runtime_state')} sync={row.get('sync_state')} "
            f"bootstrap={(obs.get('bootstrap') or {}).get('status')} "
            f"replay={(obs.get('latest_replay') or {}).get('status') if obs.get('latest_replay') else 'n/a'} "
            f"recent_history={[item['status'] for item in hist.get('items', [])]} "
            f"guidance={guidance.get('recommended_action') or '-'}:{guidance.get('reason_code') or '-'}"
        )
        out.append(
            {
                "source_id": int(row["source_id"]),
                "provider": row["provider"],
                "line": line,
                "runtime_issue": (guidance.get("recommended_action") in {"wait_for_runtime", "investigate_runtime"})
                or bool(row.get("last_error_message")),
            }
        )
    return out


def try_resume_idle_replay(*, run_dir: Path, client: httpx.Client, report: dict[str, Any]) -> bool:
    state = replay.load_state(run_dir)
    if bool(state.get("awaiting_manual")) or bool(state.get("finished")):
        return False

    creds = json.loads((run_dir / replay.RUN_CREDS_FILE).read_text(encoding="utf-8"))
    source_ids = {int(creds["ics_source_id"]), int(creds["gmail_source_id"])}
    source_rows = api_json_list(client, "/sources?status=all")
    relevant_rows = [row for row in source_rows if int(row.get("source_id") or 0) in source_ids]
    if len(relevant_rows) != len(source_ids):
        return False

    for row in relevant_rows:
        runtime_state = str(row.get("runtime_state") or "").lower()
        sync_state = str(row.get("sync_state") or "").lower()
        if runtime_state in {"queued", "running", "rebind_pending"} or sync_state in {"queued", "running"}:
            return False

    advance_with_runtime_recording(run_dir=run_dir, report=report)
    merge_replay_report(report, replay.build_report(run_dir))
    save_acceptance_report(run_dir, report)
    append_note(
        run_dir,
        "\n## Replay Recovery\n"
        f"- At: {datetime.now(UTC).isoformat()}\n"
        "- Reason: previous acceptance process stopped while sources were already idle; replay was advanced from saved state.\n",
    )
    return True


def resume_to_next_checkpoint(run_dir: Path, report: dict[str, Any]) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_year_timeline_replay_smoke.py"),
            "resume",
            "--run-dir",
            str(run_dir),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return
    failure_message = (completed.stderr or completed.stdout).strip()
    if _is_no_manual_checkpoint_race(failure_message):
        return
    details = classify_runtime_failure(failure_message)
    record_runtime_failure(run_dir=run_dir, report=report, details=details)
    if details.request_id is None or not wait_for_request_terminal(run_dir, details.request_id, seconds=180):
        raise RuntimeError(details.message)
    advance_with_runtime_recording(run_dir=run_dir, report=report)


def advance_with_runtime_recording(*, run_dir: Path, report: dict[str, Any], max_retries: int = 3) -> None:
    attempts = 0
    while True:
        try:
            replay.advance_until_checkpoint(run_dir)
            return
        except Exception as exc:
            details = classify_runtime_failure(str(exc))
            record_runtime_failure(run_dir=run_dir, report=report, details=details)
            attempts += 1
            if attempts >= max_retries:
                raise
            if details.request_id is None or not wait_for_request_terminal(run_dir, details.request_id, seconds=180):
                raise


def wait_for_request_terminal(run_dir: Path, request_id: str, *, seconds: int) -> bool:
    client = build_client_from_run(run_dir)
    deadline = time.time() + seconds
    while time.time() < deadline:
        payload = api_json(client, "GET", f"/sync-requests/{request_id}")
        if payload.get("status") == "SUCCEEDED" and bool(payload.get("applied")):
            return True
        if payload.get("status") == "FAILED":
            return False
        time.sleep(5)
    return False


def classify_runtime_failure(message: str) -> RuntimeFailureDetails:
    normalized = message.strip() or "unknown runtime failure"
    match = RUNTIME_FAILURE_PATTERN.search(normalized)
    request_id = match.group("request_id") if match else None
    source_id = int(match.group("source_id")) if match and match.group("source_id").isdigit() else None
    if "sync stalled" in normalized or "sync timed out" in normalized:
        classification = "runtime"
    elif "404" in normalized or "422" in normalized or "409" in normalized:
        classification = "api_contract"
    else:
        classification = "operator_clarity"
    return RuntimeFailureDetails(request_id=request_id, source_id=source_id, classification=classification, message=normalized)


def record_runtime_failure(*, run_dir: Path, report: dict[str, Any], details: RuntimeFailureDetails) -> None:
    report.setdefault("runtime_failures", []).append(
        {
            "at": datetime.now(UTC).isoformat(),
            "request_id": details.request_id,
            "source_id": details.source_id,
            "classification": details.classification,
            "message": details.message,
        }
    )
    save_acceptance_report(run_dir, report)
    append_note(
        run_dir,
        "\n## Runtime Incident\n"
        f"- At: {datetime.now(UTC).isoformat()}\n"
        f"- Classification: `{details.classification}`\n"
        f"- Request: `{details.request_id or '-'}`\n"
        f"- Source: `{details.source_id if details.source_id is not None else '-'}'\n"
        f"- Message: {details.message}\n",
    )


def _upsert_checkpoint_entry(report: dict[str, Any], checkpoint_entry: dict[str, Any]) -> None:
    checkpoints = report.setdefault("checkpoints", [])
    checkpoint_index = checkpoint_entry.get("checkpoint_index")
    if not isinstance(checkpoints, list):
        report["checkpoints"] = [checkpoint_entry]
        return
    if checkpoint_index is None:
        checkpoints.append(checkpoint_entry)
        return
    for idx, existing in enumerate(checkpoints):
        if isinstance(existing, dict) and existing.get("checkpoint_index") == checkpoint_index:
            checkpoints[idx] = checkpoint_entry
            return
    checkpoints.append(checkpoint_entry)


def _is_no_manual_checkpoint_race(message: str) -> bool:
    return "run is not waiting at a manual checkpoint" in message.strip().lower()


def has_odd_due_time(change: dict[str, Any]) -> bool:
    parts = parse_due_time(change)
    if parts is None:
        return False
    _hour, minute, _second = parts
    return minute not in {0, 15, 30, 45, 59}


def supports_proposal_edit(change: dict[str, Any]) -> bool:
    change_type = str(change.get("change_type") or "").strip().lower()
    return change_type in {"created", "due_changed"}


def rounded_due_time(change: dict[str, Any]) -> str | None:
    parts = parse_due_time(change)
    if parts is None:
        return None
    hour, minute, second = parts
    candidates = [0, 15, 30, 45, 59]
    target = min(candidates, key=lambda value: abs(value - minute))
    return f"{hour:02d}:{target:02d}:{second:02d}"


def parse_due_time(change: dict[str, Any]) -> tuple[int, int, int] | None:
    event = change.get("after_event") or change.get("before_event") or {}
    due_time = event.get("due_time")
    if not isinstance(due_time, str) or ":" not in due_time:
        return None
    try:
        hh, mm, ss = due_time.split(":")
        return int(hh), int(mm), int(ss)
    except Exception:
        return None


def display_label_for_change(change: dict[str, Any]) -> str:
    display = change.get("after_display") or change.get("before_display") or {}
    return str(display.get("display_label") or change.get("entity_uid") or "unknown")


def title_case_label(value: str) -> str:
    tokens = [part for part in re.split(r"(\s+|-)", value.strip()) if part]
    normalized: list[str] = []
    for token in tokens:
        if token.isspace() or token == "-":
            normalized.append(token)
            continue
        normalized.append(token[:1].upper() + token[1:].lower())
    return "".join(normalized) or value


def format_actions(actions: list[dict[str, Any]]) -> str:
    if not actions:
        return "无"
    formatted = []
    for action in actions:
        kind = action["kind"]
        if kind in {"approve", "reject"}:
            formatted.append(f"{kind} {action['change_id']} ({action['label']})")
        elif kind == "edit_then_approve":
            formatted.append(f"edit+approve {action['change_id']} ({action['label']}) -> {action['patch']}")
        elif kind == "family_rename":
            formatted.append(f"rename family {action['family_id']} -> {action['canonical_label']}")
        elif kind == "family_create_and_relink":
            formatted.append(f"create family {action['family_id']} {action['canonical_label']} + relink raw_type {action['raw_type_id']}")
        elif kind.startswith("manual_"):
            formatted.append(f"{kind} {action['entity_uid']}")
        else:
            formatted.append(json.dumps(action, ensure_ascii=False))
    return "; ".join(formatted)


def build_client_from_run(run_dir: Path) -> httpx.Client:
    creds = json.loads((run_dir / replay.RUN_CREDS_FILE).read_text(encoding="utf-8"))
    client = replay.build_api_client(public_api_base=str(creds["public_api_base"]), api_key=str(creds["api_key"]))
    user = replay.ensure_authenticated_session(
        client,
        notify_email=str(creds["notify_email"]),
        password=str(creds["password"]),
    )
    expected_user_id = creds.get("user_id")
    if expected_user_id is not None and int(user.get("id") or 0) != int(expected_user_id):
        raise RuntimeError(
            "run credentials drifted from live DB: "
            f"expected user_id={expected_user_id} got user_id={user.get('id')}"
        )
    return client


def initialize_acceptance_artifacts(run_dir: Path) -> None:
    state = replay.load_state(run_dir)
    report = {
        "run_id": state["run_id"],
        "created_at": state["created_at"],
        "status": "running",
        "mode": "backend_api_operator",
        "run_dir": str(run_dir),
        "checkpoints": [],
        "runtime_failures": [],
        "operator_state": {
            "rejections_done": 0,
            "edits_done": 0,
            "family_renamed": False,
            "family_relinked": False,
            "family_created_id": None,
            "manual_created": False,
            "manual_updated": False,
            "manual_deleted": False,
            "manual_entity_uid": None,
        },
    }
    save_acceptance_report(run_dir, report)
    if not (run_dir / ACCEPTANCE_NOTES_FILE).exists():
        append_note(
            run_dir,
            "# Backend Operator Notes\n\n"
            f"- Run ID: `{state['run_id']}`\n"
            "- Mode: `backend-api-only`\n"
            "- Perspective: `student first-use mental model via API surface`\n\n",
        )


def merge_replay_report(acceptance_report: dict[str, Any], replay_report: dict[str, Any]) -> None:
    acceptance_report["replay_report"] = replay_report
    acceptance_report["bootstrap"] = replay_report.get("bootstrap")
    acceptance_report["replay"] = replay_report.get("replay")
    acceptance_report["overall_llm_usage"] = ((replay_report.get("llm_usage") or {}) if isinstance(replay_report.get("llm_usage"), dict) else {})


def finalize_acceptance_report(run_dir: Path, report: dict[str, Any]) -> None:
    report["status"] = "finished"
    replay_report = replay.build_report(run_dir)
    merge_replay_report(report, replay_report)
    ratings = [row["rating"] for row in report.get("checkpoints", []) if isinstance(row, dict) and isinstance(row.get("rating"), str)]
    durations = [float(row["elapsed_seconds"]) for row in report.get("checkpoints", []) if isinstance(row, dict) and isinstance(row.get("elapsed_seconds"), (int, float))]
    report["summary"] = {
        "checkpoint_count": len(report.get("checkpoints", [])),
        "average_checkpoint_seconds": round(statistics.mean(durations), 1) if durations else None,
        "rating_counts": {label: ratings.count(label) for label in sorted(set(ratings))},
        "most_common_question": "我现在为什么应该做这一步，而不是去另一个 lane",
    }
    save_acceptance_report(run_dir, report)


def load_acceptance_report(run_dir: Path) -> dict[str, Any]:
    path = run_dir / ACCEPTANCE_REPORT_FILE
    if not path.exists():
        initialize_acceptance_artifacts(run_dir)
    return json.loads(path.read_text(encoding="utf-8"))


def save_acceptance_report(run_dir: Path, payload: dict[str, Any]) -> None:
    (run_dir / ACCEPTANCE_REPORT_FILE).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_note(run_dir: Path, text: str) -> None:
    path = run_dir / ACCEPTANCE_NOTES_FILE
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text)
        if not text.endswith("\n"):
            fh.write("\n")


def api_json(client: httpx.Client, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    response = client.request(method, path, json=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {response.status_code}: {response.text[:400]}")
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"{method} {path} returned non-object json")
    return data


def api_json_list(client: httpx.Client, path: str) -> list[dict[str, Any]]:
    response = client.get(path)
    if response.status_code >= 400:
        raise RuntimeError(f"GET {path} -> {response.status_code}: {response.text[:400]}")
    data = response.json()
    if not isinstance(data, list):
        raise RuntimeError(f"GET {path} returned non-list json")
    return [row for row in data if isinstance(row, dict)]


if __name__ == "__main__":
    main()
