#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.models.input import IngestTriggerType, SyncRequest
from app.db.models.review import EventEntity
from app.db.session import get_session_factory
from app.modules.llm_gateway.usage_tracking import LLM_USAGE_SUMMARY_KEY

DEFAULT_MANIFEST = REPO_ROOT / "data" / "synthetic" / "year_timeline_demo" / "year_timeline_manifest.json"
OUTPUT_ROOT = REPO_ROOT / "output"
STATE_FILE = "state.json"
CHECKPOINTS_FILE = "checkpoints.json"
REPORT_FILE = "report.json"
SUMMARY_FILE = "summary.md"
RUN_CREDS_FILE = "run_credentials.json"
API_KEY_ENV = "APP_API_KEY"
DEFAULT_FAKE_HOST = "127.0.0.1"
DEFAULT_FAKE_PORT = 8765
DEFAULT_EMAIL_BUCKET = "year_timeline_full_sim"
DEFAULT_ICS_DERIVED_SET = "year_timeline_smoke_16"
PAGE_SIZE = 200
BOOTSTRAP_WARMUP_TIMEOUT_SECONDS = 900.0
SYNC_STALL_TIMEOUT_SECONDS = 90.0
REPLAY_SYNC_TIMEOUT_SECONDS = 900.0

SCENARIO_BY_PHASE = {
    "WI26": "year-timeline-wi26",
    "SP26": "year-timeline-sp26",
    "SU26": "year-timeline-su26",
    "FA26": "year-timeline-fa26",
}


class ReplayFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class BatchSpec:
    semester: int
    batch: int
    global_batch: int
    phase_label: str
    start_iso: str
    month_key: str
    scenario_id: str
    transition_id: str


@dataclass(frozen=True)
class CheckpointSpec:
    checkpoint_index: int
    month_key: str
    global_batch: int
    semester: int
    batch: int
    phase_label: str
    scenario_id: str
    transition_id: str
    label: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run human-in-loop year timeline replay smoke on the local real backend.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start")
    start.add_argument("--public-api-base", required=True)
    start.add_argument("--api-key", default=os.getenv(API_KEY_ENV, ""))
    start.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    start.add_argument("--email-bucket", default=DEFAULT_EMAIL_BUCKET)
    start.add_argument("--ics-derived-set", default=DEFAULT_ICS_DERIVED_SET)
    start.add_argument("--fake-provider-host", default=DEFAULT_FAKE_HOST)
    start.add_argument("--fake-provider-port", type=int, default=DEFAULT_FAKE_PORT)
    start.add_argument("--start-fake-provider", action=argparse.BooleanOptionalAction, default=True)
    start.add_argument("--notify-email", default=None)
    start.add_argument("--auth-password", default=os.getenv("SMOKE_AUTH_PASSWORD", "password123"))

    for name in ("status", "resume", "report"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--run-dir", required=True)

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    command = str(args.command)
    if command == "start":
        run_dir = start_replay(args)
        print(run_dir)
        return
    run_dir = Path(args.run_dir).expanduser().resolve()
    if command == "status":
        print(render_status(run_dir))
        return
    if command == "resume":
        result_dir = resume_replay(run_dir)
        print(result_dir)
        return
    if command == "report":
        report = build_report(run_dir)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    raise ReplayFailure(f"unsupported command: {command}")


def start_replay(args: argparse.Namespace) -> Path:
    public_api_base = str(args.public_api_base).rstrip("/")
    if not public_api_base:
        raise ReplayFailure("--public-api-base is required")
    api_key = str(args.api_key or "").strip()
    if not api_key:
        raise ReplayFailure("APP_API_KEY or --api-key is required")

    manifest = json.loads(Path(args.manifest).expanduser().read_text(encoding="utf-8"))
    batches = load_batch_specs(manifest)
    checkpoints = compute_monthly_twice_checkpoints(batches)
    if not checkpoints:
        raise ReplayFailure("no checkpoints generated from manifest")
    replay_term_config = build_replay_term_config(batches)

    started_at = datetime.now(UTC)
    run_dir = OUTPUT_ROOT / f"year-timeline-replay-{started_at.strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    fake_provider_pid: int | None = None
    if bool(args.start_fake_provider):
        fake_provider_pid = start_fake_provider_with_bucket(
            host=str(args.fake_provider_host),
            port=int(args.fake_provider_port),
            manifest_path=Path(args.manifest).expanduser().resolve(),
            email_bucket=str(args.email_bucket),
        )
    ensure_fake_provider_ready(host=str(args.fake_provider_host), port=int(args.fake_provider_port))
    first_batch = batches[0]
    set_fake_provider_batch(
        host=str(args.fake_provider_host),
        port=int(args.fake_provider_port),
        semester=first_batch.semester,
        batch=first_batch.batch,
        run_tag=run_dir.name,
    )

    notify_email = str(args.notify_email or f"timeline-smoke-{uuid.uuid4().hex[:10]}@example.com")
    auth_password = str(args.auth_password)
    client = build_api_client(public_api_base=public_api_base, api_key=api_key)
    session_user = ensure_authenticated_session(
        client,
        notify_email=notify_email,
        password=auth_password,
    )
    user_id = int(session_user["id"])

    ics_source = create_source(
        client,
        payload={
            "source_kind": "calendar",
            "provider": "ics",
            "display_name": "Replay Canvas ICS",
            "config": replay_term_config,
            "secrets": {"url": f"http://{args.fake_provider_host}:{args.fake_provider_port}/ics/calendar.ics"},
        },
    )
    gmail_source = create_source(
        client,
        payload={
            "source_kind": "email",
            "provider": "gmail",
            "display_name": "Replay Gmail Source",
            "config": replay_term_config,
            "secrets": {
                "access_token": "fake-access-token",
                "account_email": "fake.student@example.edu",
            },
        },
    )

    state = {
        "run_id": run_dir.name,
        "created_at": started_at.isoformat(),
        "public_api_base": public_api_base,
        "api_key": api_key,
        "manifest_path": str(Path(args.manifest).expanduser().resolve()),
        "email_bucket": str(args.email_bucket),
        "ics_derived_set": str(args.ics_derived_set),
        "notify_email": notify_email,
        "auth_password": auth_password,
        "user_id": user_id,
        "ics_source_id": int(ics_source["source_id"]),
        "gmail_source_id": int(gmail_source["source_id"]),
        "fake_provider": {
            "host": str(args.fake_provider_host),
            "port": int(args.fake_provider_port),
            "pid": fake_provider_pid,
            "started_by_harness": bool(args.start_fake_provider),
        },
        "checkpoints": [asdict(row) for row in checkpoints],
        "current_checkpoint_index": 0,
        "next_global_batch": 1,
        "awaiting_manual": False,
        "completed_batches": [],
        "batch_results": [],
        "bootstrap_results": [],
        "checkpoint_summaries": [],
        "finished": False,
    }
    write_json(run_dir / CHECKPOINTS_FILE, {"checkpoints": [asdict(row) for row in checkpoints]})
    write_json(
        run_dir / RUN_CREDS_FILE,
        {
            "public_api_base": public_api_base,
            "api_key": api_key,
            "notify_email": notify_email,
            "password": auth_password,
            "user_id": user_id,
            "ics_source_id": int(ics_source["source_id"]),
            "gmail_source_id": int(gmail_source["source_id"]),
        },
    )
    write_json(run_dir / STATE_FILE, state)
    state["bootstrap_results"] = wait_for_bootstrap_syncs(
        client=client,
        sources=[ics_source, gmail_source],
    )
    write_json(run_dir / STATE_FILE, state)
    return advance_until_checkpoint(run_dir)


def resume_replay(run_dir: Path) -> Path:
    state = load_state(run_dir)
    if state.get("finished"):
        build_report(run_dir)
        return run_dir
    if not state.get("awaiting_manual"):
        raise ReplayFailure("run is not waiting at a manual checkpoint")

    client = build_api_client(public_api_base=str(state["public_api_base"]), api_key=str(state["api_key"]))
    ensure_authenticated_session(
        client,
        notify_email=str(state["notify_email"]),
        password=str(state["auth_password"]),
    )

    current_checkpoint_index = int(state["current_checkpoint_index"])
    checkpoint_before_path = run_dir / f"checkpoint-{current_checkpoint_index:02d}-before.json"
    checkpoint_after_path = run_dir / f"checkpoint-{current_checkpoint_index:02d}-after.json"
    before_snapshot = json.loads(checkpoint_before_path.read_text(encoding="utf-8"))
    after_snapshot = capture_backend_snapshot(
        client=client,
        user_id=int(state["user_id"]),
    )
    write_json(checkpoint_after_path, after_snapshot)
    checkpoint_diff = diff_snapshots(before_snapshot, after_snapshot)
    state.setdefault("checkpoint_summaries", []).append(
        {
            "checkpoint_index": current_checkpoint_index,
            "after_recorded_at": datetime.now(UTC).isoformat(),
            "diff": checkpoint_diff,
        }
    )
    state["awaiting_manual"] = False
    state["current_checkpoint_index"] = current_checkpoint_index + 1
    write_json(run_dir / STATE_FILE, state)
    return advance_until_checkpoint(run_dir)


def advance_until_checkpoint(run_dir: Path) -> Path:
    state = load_state(run_dir)
    if state.get("finished"):
        build_report(run_dir)
        return run_dir

    client = build_api_client(public_api_base=str(state["public_api_base"]), api_key=str(state["api_key"]))
    ensure_authenticated_session(
        client,
        notify_email=str(state["notify_email"]),
        password=str(state["auth_password"]),
    )
    ensure_fake_provider_for_state(state)

    checkpoints = [CheckpointSpec(**row) for row in state["checkpoints"]]
    batches = load_batch_specs(json.loads(Path(state["manifest_path"]).read_text(encoding="utf-8")))
    next_global_batch = int(state["next_global_batch"])
    checkpoint_index = int(state["current_checkpoint_index"])
    target_checkpoint = checkpoints[checkpoint_index] if checkpoint_index < len(checkpoints) else None

    while next_global_batch <= len(batches):
        batch = batches[next_global_batch - 1]
        batch_result = process_batch(
            client=client,
            state=state,
            batch=batch,
        )
        state["completed_batches"].append(batch.global_batch)
        state["batch_results"].append(batch_result)
        next_global_batch = batch.global_batch + 1
        state["next_global_batch"] = next_global_batch
        write_json(run_dir / STATE_FILE, state)

        if target_checkpoint is not None and batch.global_batch == target_checkpoint.global_batch:
            before_snapshot = capture_backend_snapshot(client=client, user_id=int(state["user_id"]))
            write_json(run_dir / f"checkpoint-{checkpoint_index:02d}-before.json", before_snapshot)
            state["awaiting_manual"] = True
            write_json(run_dir / STATE_FILE, state)
            build_report(run_dir)
            return run_dir

    state["finished"] = True
    state["awaiting_manual"] = False
    write_json(run_dir / STATE_FILE, state)
    build_report(run_dir)
    return run_dir


def process_batch(*, client: httpx.Client, state: dict[str, Any], batch: BatchSpec) -> dict[str, Any]:
    set_fake_provider_batch(
        host=str(state["fake_provider"]["host"]),
        port=int(state["fake_provider"]["port"]),
        semester=batch.semester,
        batch=batch.batch,
        run_tag=str(state["run_id"]),
    )
    ics_request_id = create_sync_request(client, source_id=int(state["ics_source_id"]), trace_id=f"ics-{batch.global_batch}")
    ics_status = wait_sync_success(client, request_id=ics_request_id, source_id=int(state["ics_source_id"]))
    gmail_request_id = create_sync_request(client, source_id=int(state["gmail_source_id"]), trace_id=f"gmail-{batch.global_batch}")
    gmail_status = wait_sync_success(client, request_id=gmail_request_id, source_id=int(state["gmail_source_id"]))
    return {
        "global_batch": batch.global_batch,
        "semester": batch.semester,
        "batch": batch.batch,
        "phase_label": batch.phase_label,
        "month_key": batch.month_key,
        "scenario_id": batch.scenario_id,
        "transition_id": batch.transition_id,
        "ics_request_id": ics_request_id,
        "gmail_request_id": gmail_request_id,
        "ics_status": str(ics_status.get("status") or ""),
        "gmail_status": str(gmail_status.get("status") or ""),
        "ics_applied": bool(ics_status.get("applied")),
        "gmail_applied": bool(gmail_status.get("applied")),
        "ics_elapsed_ms": extract_sync_elapsed_ms(ics_status),
        "gmail_elapsed_ms": extract_sync_elapsed_ms(gmail_status),
        "ics_llm_usage": extract_sync_llm_usage(ics_status),
        "gmail_llm_usage": extract_sync_llm_usage(gmail_status),
    }


def capture_backend_snapshot(*, client: httpx.Client, user_id: int) -> dict[str, Any]:
    changes = list_all_changes(client)
    families = request_json_list(client, "GET", "/families")
    raw_types = request_json_list(client, "GET", "/families/raw-types")
    manual_events = normalize_manual_events(
        request_json_list(client, "GET", "/manual/events?include_removed=true")
    )
    sources = request_json_list(client, "GET", "/sources?status=all")
    family_status = request_json(client, "GET", "/families/status")
    event_entity_count = count_event_entities_for_user(user_id=user_id)
    return {
        "recorded_at": datetime.now(UTC).isoformat(),
        "user_id": user_id,
        "event_entity_count": event_entity_count,
        "pending_change_count": sum(1 for row in changes if str(row.get("review_status") or "") == "pending"),
        "approved_change_count": sum(1 for row in changes if str(row.get("review_status") or "") == "approved"),
        "rejected_change_count": sum(1 for row in changes if str(row.get("review_status") or "") == "rejected"),
        "family_count": len(families),
        "raw_type_count": len(raw_types),
        "manual_event_count": len(manual_events),
        "changes": changes,
        "families": families,
        "raw_types": raw_types,
        "manual_events": manual_events,
        "sources": sources,
        "family_status": family_status,
    }


def diff_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_changes = {int(row["id"]): row for row in before.get("changes", []) if isinstance(row, dict) and isinstance(row.get("id"), int)}
    after_changes = {int(row["id"]): row for row in after.get("changes", []) if isinstance(row, dict) and isinstance(row.get("id"), int)}
    approvals = 0
    rejections = 0
    edits_then_approvals = 0
    for change_id, before_row in before_changes.items():
        after_row = after_changes.get(change_id)
        if after_row is None:
            continue
        before_status = str(before_row.get("review_status") or "")
        after_status = str(after_row.get("review_status") or "")
        if before_status == "pending" and after_status == "approved":
            approvals += 1
            if json.dumps(before_row.get("after_event"), sort_keys=True, default=str) != json.dumps(after_row.get("after_event"), sort_keys=True, default=str):
                edits_then_approvals += 1
        if before_status == "pending" and after_status == "rejected":
            rejections += 1

    before_families = {int(row["id"]): row for row in before.get("families", []) if isinstance(row, dict) and isinstance(row.get("id"), int)}
    after_families = {int(row["id"]): row for row in after.get("families", []) if isinstance(row, dict) and isinstance(row.get("id"), int)}
    created_family_ids = sorted(set(after_families) - set(before_families))
    renamed_family_ids: list[int] = []
    updated_family_ids: list[int] = []
    for family_id in sorted(set(before_families) & set(after_families)):
        before_row = before_families[family_id]
        after_row = after_families[family_id]
        if before_row.get("canonical_label") != after_row.get("canonical_label"):
            renamed_family_ids.append(family_id)
        if before_row != after_row:
            updated_family_ids.append(family_id)

    before_raw = {int(row["id"]): row for row in before.get("raw_types", []) if isinstance(row, dict) and isinstance(row.get("id"), int)}
    after_raw = {int(row["id"]): row for row in after.get("raw_types", []) if isinstance(row, dict) and isinstance(row.get("id"), int)}
    raw_type_relinks = 0
    for raw_type_id in sorted(set(before_raw) & set(after_raw)):
        if before_raw[raw_type_id].get("family_id") != after_raw[raw_type_id].get("family_id"):
            raw_type_relinks += 1

    before_manual = {str(row["entity_uid"]): row for row in before.get("manual_events", []) if isinstance(row, dict) and isinstance(row.get("entity_uid"), str)}
    after_manual = {str(row["entity_uid"]): row for row in after.get("manual_events", []) if isinstance(row, dict) and isinstance(row.get("entity_uid"), str)}
    manual_created = sorted(set(after_manual) - set(before_manual))
    manual_removed = sorted(
        uid for uid, row in after_manual.items() if uid in before_manual and before_manual[uid].get("lifecycle") != row.get("lifecycle") and row.get("lifecycle") == "removed"
    )
    manual_updated = sorted(
        uid
        for uid, row in after_manual.items()
        if uid in before_manual and json.dumps(before_manual[uid], sort_keys=True, default=str) != json.dumps(row, sort_keys=True, default=str)
    )

    return {
        "review_actions": {
            "approved": approvals,
            "rejected": rejections,
            "edited_then_approved": edits_then_approvals,
        },
        "family_actions": {
            "created_family_ids": created_family_ids,
            "renamed_family_ids": renamed_family_ids,
            "updated_family_ids": updated_family_ids,
            "raw_type_relinks": raw_type_relinks,
        },
        "manual_actions": {
            "created_entity_uids": manual_created,
            "removed_entity_uids": manual_removed,
            "updated_entity_uids": manual_updated,
        },
        "state_totals": {
            "before_pending_changes": int(before.get("pending_change_count") or 0),
            "after_pending_changes": int(after.get("pending_change_count") or 0),
            "before_event_entities": int(before.get("event_entity_count") or 0),
            "after_event_entities": int(after.get("event_entity_count") or 0),
            "before_families": int(before.get("family_count") or 0),
            "after_families": int(after.get("family_count") or 0),
            "before_manual_events": int(before.get("manual_event_count") or 0),
            "after_manual_events": int(after.get("manual_event_count") or 0),
        },
    }


def build_report(run_dir: Path) -> dict[str, Any]:
    state = load_state(run_dir)
    batch_results = list(state.get("batch_results") or [])
    bootstrap_results = enrich_bootstrap_results_from_api(
        state=state,
        bootstrap_results=list(state.get("bootstrap_results") or []),
    )
    checkpoint_summaries = list(state.get("checkpoint_summaries") or [])
    bootstrap_llm_usage = aggregate_llm_usage_summaries(row.get("llm_usage") for row in bootstrap_results)
    ics_llm_usage = aggregate_llm_usage_summaries(row.get("ics_llm_usage") for row in batch_results)
    gmail_llm_usage = aggregate_llm_usage_summaries(row.get("gmail_llm_usage") for row in batch_results)
    replay_llm_usage = aggregate_llm_usage_summaries([ics_llm_usage, gmail_llm_usage])
    overall_llm_usage = aggregate_llm_usage_summaries([bootstrap_llm_usage, replay_llm_usage])
    report_generated_at = datetime.now(UTC)
    created_at = parse_iso(str(state["created_at"]))
    bootstrap_elapsed_values = [row.get("elapsed_ms") for row in bootstrap_results]
    report = {
        "run_id": state["run_id"],
        "created_at": state["created_at"],
        "report_generated_at": report_generated_at.isoformat(),
        "elapsed_seconds": max(int((report_generated_at - created_at).total_seconds()), 0),
        "finished": bool(state.get("finished")),
        "awaiting_manual": bool(state.get("awaiting_manual")),
        "user_id": int(state["user_id"]),
        "notify_email": state["notify_email"],
        "ics_source_id": int(state["ics_source_id"]),
        "gmail_source_id": int(state["gmail_source_id"]),
        "checkpoints_completed": len(checkpoint_summaries),
        "bootstrap": {
            "completed_request_count": len(bootstrap_results),
            "avg_elapsed_ms": average_int(bootstrap_elapsed_values),
            "total_elapsed_ms": sum(
                max(int(value), 0)
                for value in bootstrap_elapsed_values
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            ),
            "llm_usage": bootstrap_llm_usage,
            "results": bootstrap_results,
        },
        "replay": {
            "completed_batch_count": len(state.get("completed_batches") or []),
            "total_ics_transitions_applied": sum(1 for row in batch_results if row.get("ics_applied")),
            "total_gmail_batches_applied": sum(1 for row in batch_results if row.get("gmail_applied")),
            "avg_ics_elapsed_ms": average_int([row.get("ics_elapsed_ms") for row in batch_results]),
            "avg_gmail_elapsed_ms": average_int([row.get("gmail_elapsed_ms") for row in batch_results]),
            "llm_usage": {
                "overall": replay_llm_usage,
                "ics": ics_llm_usage,
                "gmail": gmail_llm_usage,
            },
        },
        "completed_batch_count": len(state.get("completed_batches") or []),
        "total_ics_transitions_applied": sum(1 for row in batch_results if row.get("ics_applied")),
        "total_gmail_batches_applied": sum(1 for row in batch_results if row.get("gmail_applied")),
        "avg_ics_elapsed_ms": average_int([row.get("ics_elapsed_ms") for row in batch_results]),
        "avg_gmail_elapsed_ms": average_int([row.get("gmail_elapsed_ms") for row in batch_results]),
        "llm_usage": {
            "overall": overall_llm_usage,
            "bootstrap": bootstrap_llm_usage,
            "replay": replay_llm_usage,
            "ics": ics_llm_usage,
            "gmail": gmail_llm_usage,
        },
        "bootstrap_results": bootstrap_results,
        "batch_results": batch_results,
        "checkpoint_summaries": checkpoint_summaries,
    }
    write_json(run_dir / REPORT_FILE, report)
    (run_dir / SUMMARY_FILE).write_text(render_summary(report), encoding="utf-8")
    return report


def enrich_bootstrap_results_from_api(*, state: dict[str, Any], bootstrap_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not bootstrap_results:
        return bootstrap_results
    if not any(_bootstrap_result_is_placeholder(row) for row in bootstrap_results):
        return bootstrap_results
    try:
        client = build_api_client(public_api_base=str(state["public_api_base"]), api_key=str(state["api_key"]))
        login = client.post(
            "/auth/login",
            json={
                "notify_email": str(state["notify_email"]),
                "password": str(state["auth_password"]),
                "timezone_name": "America/Los_Angeles",
            },
        )
        if login.status_code != 200:
            return bootstrap_results
    except Exception:
        return bootstrap_results

    enriched: list[dict[str, Any]] = []
    for row in bootstrap_results:
        source_id = int(row.get("source_id") or 0)
        if source_id <= 0:
            enriched.append(row)
            continue
        try:
            payload = request_json(client, "GET", f"/sources/{source_id}/observability")
        except Exception:
            enriched.append(row)
            continue
        bootstrap_payload = payload.get("bootstrap") if isinstance(payload.get("bootstrap"), dict) else None
        if bootstrap_payload is None:
            enriched.append(row)
            continue
        enriched.append(build_bootstrap_result(source=row, status_payload=bootstrap_payload))
    return enriched


def _bootstrap_result_is_placeholder(row: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    if row.get("request_id") in (None, ""):
        return True
    if row.get("status") in (None, "", "unknown"):
        return True
    if row.get("elapsed_ms") is None:
        return True
    if row.get("llm_usage") is None and row.get("connector_result") is None:
        return True
    return False


def render_summary(report: dict[str, Any]) -> str:
    bootstrap = report.get("bootstrap") if isinstance(report.get("bootstrap"), dict) else {}
    replay = report.get("replay") if isinstance(report.get("replay"), dict) else {}
    llm_usage = report.get("llm_usage") if isinstance(report.get("llm_usage"), dict) else {}
    overall_llm = llm_usage.get("overall") if isinstance(llm_usage.get("overall"), dict) else {}
    bootstrap_llm = llm_usage.get("bootstrap") if isinstance(llm_usage.get("bootstrap"), dict) else {}
    replay_llm = llm_usage.get("replay") if isinstance(llm_usage.get("replay"), dict) else {}
    ics_llm = llm_usage.get("ics") if isinstance(llm_usage.get("ics"), dict) else {}
    gmail_llm = llm_usage.get("gmail") if isinstance(llm_usage.get("gmail"), dict) else {}
    lines = [
        "# Year Timeline Replay Smoke",
        "",
        f"- Run ID: `{report['run_id']}`",
        f"- Finished: `{report['finished']}`",
        f"- Awaiting manual: `{report['awaiting_manual']}`",
        f"- Completed batches: `{report['completed_batch_count']}`",
        f"- ICS transitions applied: `{report['total_ics_transitions_applied']}`",
        f"- Gmail batches applied: `{report['total_gmail_batches_applied']}`",
        f"- Completed checkpoints: `{report['checkpoints_completed']}`",
        f"- Elapsed seconds: `{report.get('elapsed_seconds')}`",
        f"- Avg ICS elapsed ms: `{fmt_int(report.get('avg_ics_elapsed_ms'))}`",
        f"- Avg Gmail elapsed ms: `{fmt_int(report.get('avg_gmail_elapsed_ms'))}`",
        "",
    ]
    if bootstrap:
        lines.extend(
            [
                "## Bootstrap",
                f"- completed requests: `{fmt_int(bootstrap.get('completed_request_count'))}`",
                f"- avg_elapsed_ms: `{fmt_int(bootstrap.get('avg_elapsed_ms'))}`",
                f"- total_elapsed_ms: `{fmt_int(bootstrap.get('total_elapsed_ms'))}`",
                f"- llm_calls: `{fmt_int(bootstrap_llm.get('successful_call_count'))}`",
                f"- llm_total_tokens: `{fmt_int(bootstrap_llm.get('total_tokens'))}`",
                f"- llm_cached_input_tokens: `{fmt_int(bootstrap_llm.get('cached_input_tokens'))}`",
                f"- llm_cache_creation_input_tokens: `{fmt_int(bootstrap_llm.get('cache_creation_input_tokens'))}`",
                "",
            ]
        )
    if replay:
        lines.extend(
            [
                "## Replay",
                f"- completed batches: `{fmt_int(replay.get('completed_batch_count'))}`",
                f"- avg_ics_elapsed_ms: `{fmt_int(replay.get('avg_ics_elapsed_ms'))}`",
                f"- avg_gmail_elapsed_ms: `{fmt_int(replay.get('avg_gmail_elapsed_ms'))}`",
                f"- llm_calls: `{fmt_int(replay_llm.get('successful_call_count'))}`",
                f"- llm_total_tokens: `{fmt_int(replay_llm.get('total_tokens'))}`",
                "",
            ]
        )
    if overall_llm.get("successful_call_count"):
        lines.extend(
            [
                "## LLM Usage",
                f"- calls: `{fmt_int(overall_llm.get('successful_call_count'))}`",
                f"- input_tokens: `{fmt_int(overall_llm.get('input_tokens'))}`",
                f"- cached_input_tokens: `{fmt_int(overall_llm.get('cached_input_tokens'))}`",
                f"- cache_creation_input_tokens: `{fmt_int(overall_llm.get('cache_creation_input_tokens'))}`",
                f"- output_tokens: `{fmt_int(overall_llm.get('output_tokens'))}`",
                f"- reasoning_tokens: `{fmt_int(overall_llm.get('reasoning_tokens'))}`",
                f"- total_tokens: `{fmt_int(overall_llm.get('total_tokens'))}`",
                f"- cache_hit_ratio: `{fmt_ratio(overall_llm.get('cache_hit_ratio'))}`",
                f"- avg_latency_ms: `{fmt_int(overall_llm.get('avg_latency_ms'))}`",
                f"- max_latency_ms: `{fmt_int(overall_llm.get('latency_ms_max'))}`",
                f"- ICS calls: `{fmt_int(ics_llm.get('successful_call_count'))}`",
                f"- Gmail calls: `{fmt_int(gmail_llm.get('successful_call_count'))}`",
                "",
            ]
        )
    for item in report.get("checkpoint_summaries", []):
        diff = item.get("diff") or {}
        lines.extend(
            [
                f"## Checkpoint {item['checkpoint_index']}",
                f"- approved: `{((diff.get('review_actions') or {}).get('approved') or 0)}`",
                f"- rejected: `{((diff.get('review_actions') or {}).get('rejected') or 0)}`",
                f"- edited_then_approved: `{((diff.get('review_actions') or {}).get('edited_then_approved') or 0)}`",
                f"- family created: `{len(((diff.get('family_actions') or {}).get('created_family_ids') or []))}`",
                f"- raw-type relinks: `{((diff.get('family_actions') or {}).get('raw_type_relinks') or 0)}`",
                f"- manual created: `{len(((diff.get('manual_actions') or {}).get('created_entity_uids') or []))}`",
                "",
            ]
        )
    return "\n".join(lines)


def normalize_manual_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        manual_support = row.get("manual_support")
        if manual_support is False:
            continue
        normalized.append(row)
    return normalized


def extract_sync_llm_usage(status_payload: dict[str, Any]) -> dict[str, Any] | None:
    direct_usage = status_payload.get("llm_usage")
    if isinstance(direct_usage, dict):
        return direct_usage
    metadata = status_payload.get("metadata") if isinstance(status_payload.get("metadata"), dict) else {}
    usage = metadata.get(LLM_USAGE_SUMMARY_KEY)
    if not isinstance(usage, dict):
        return None
    return usage


def extract_sync_elapsed_ms(status_payload: dict[str, Any]) -> int | None:
    created_at_raw = status_payload.get("created_at")
    end_raw = status_payload.get("applied_at") or status_payload.get("updated_at")
    if not isinstance(created_at_raw, str) or not isinstance(end_raw, str):
        return None
    try:
        started = parse_iso(created_at_raw)
        ended = parse_iso(end_raw)
    except Exception:
        return None
    return max(int((ended - started).total_seconds() * 1000), 0)


def aggregate_llm_usage_summaries(summaries: Any) -> dict[str, Any]:
    aggregate = {
        "successful_call_count": 0,
        "usage_record_count": 0,
        "latency_ms_total": 0,
        "latency_ms_max": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "api_modes": {},
        "models": {},
        "task_counts": {},
        "cache_hit_ratio": None,
        "avg_latency_ms": None,
    }
    iterable = summaries if isinstance(summaries, (list, tuple)) else list(summaries)
    for item in iterable:
        if not isinstance(item, dict):
            continue
        for key in (
            "successful_call_count",
            "usage_record_count",
            "latency_ms_total",
            "input_tokens",
            "cached_input_tokens",
            "cache_creation_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
        ):
            aggregate[key] += max(int(item.get(key) or 0), 0)
        aggregate["latency_ms_max"] = max(aggregate["latency_ms_max"], max(int(item.get("latency_ms_max") or 0), 0))
        for mapping_key in ("api_modes", "models", "task_counts"):
            mapping = item.get(mapping_key)
            if not isinstance(mapping, dict):
                continue
            for sub_key, raw_count in mapping.items():
                if not isinstance(sub_key, str):
                    continue
                aggregate[mapping_key][sub_key] = max(int(aggregate[mapping_key].get(sub_key) or 0), 0) + max(
                    int(raw_count or 0),
                    0,
                )
    if aggregate["successful_call_count"] > 0:
        aggregate["avg_latency_ms"] = int(aggregate["latency_ms_total"] / aggregate["successful_call_count"])
    if aggregate["input_tokens"] > 0:
        aggregate["cache_hit_ratio"] = round(aggregate["cached_input_tokens"] / aggregate["input_tokens"], 4)
    return aggregate


def average_int(values: list[Any]) -> int | None:
    ints = [max(int(value), 0) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]
    if not ints:
        return None
    return int(sum(ints) / len(ints))


def fmt_int(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return str(int(value))
    except Exception:
        return "-"


def fmt_ratio(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.2%}"
    except Exception:
        return "-"


def render_status(run_dir: Path) -> str:
    state = load_state(run_dir)
    return json.dumps(
        {
            "run_id": state["run_id"],
            "finished": state.get("finished"),
            "awaiting_manual": state.get("awaiting_manual"),
            "current_checkpoint_index": state.get("current_checkpoint_index"),
            "next_global_batch": state.get("next_global_batch"),
            "bootstrap_request_count": len(state.get("bootstrap_results") or []),
            "completed_batch_count": len(state.get("completed_batches") or []),
        },
        ensure_ascii=False,
        indent=2,
    )


def load_batch_specs(manifest: dict[str, Any]) -> list[BatchSpec]:
    out: list[BatchSpec] = []
    for phase in manifest.get("plans", []):
        if not isinstance(phase, dict):
            continue
        phase_label = str(phase.get("phase_label") or "")
        scenario_id = SCENARIO_BY_PHASE.get(phase_label)
        if scenario_id is None:
            continue
        for batch in phase.get("batches", []):
            if not isinstance(batch, dict):
                continue
            global_batch = int(batch.get("global_batch") or 0)
            if global_batch <= 0:
                continue
            start_iso = str(batch.get("start_iso") or "")
            start_dt = parse_iso(start_iso)
            batch_no = int(batch.get("batch") or 0)
            out.append(
                BatchSpec(
                    semester=int(phase.get("semester") or 0),
                    batch=batch_no,
                    global_batch=global_batch,
                    phase_label=phase_label,
                    start_iso=start_iso,
                    month_key=f"{start_dt.year:04d}-{start_dt.month:02d}",
                    scenario_id=scenario_id,
                    transition_id=f"round-{batch_no - 1:02d}__to__round-{batch_no:02d}",
                )
            )
    out.sort(key=lambda row: row.global_batch)
    return out


def compute_monthly_twice_checkpoints(batches: list[BatchSpec]) -> list[CheckpointSpec]:
    by_month: dict[str, list[BatchSpec]] = {}
    for batch in batches:
        by_month.setdefault(batch.month_key, []).append(batch)
    checkpoints: list[CheckpointSpec] = []
    index = 0
    for month_key in sorted(by_month):
        month_batches = sorted(by_month[month_key], key=lambda row: row.global_batch)
        first = month_batches[0]
        second = next((row for row in month_batches if parse_iso(row.start_iso).day >= 15), month_batches[-1])
        chosen: list[BatchSpec] = [first]
        if second.global_batch != first.global_batch:
            chosen.append(second)
        for row in chosen:
            checkpoints.append(
                CheckpointSpec(
                    checkpoint_index=index,
                    month_key=month_key,
                    global_batch=row.global_batch,
                    semester=row.semester,
                    batch=row.batch,
                    phase_label=row.phase_label,
                    scenario_id=row.scenario_id,
                    transition_id=row.transition_id,
                    label=f"{month_key} checkpoint @ batch {row.batch}",
                )
            )
            index += 1
    return checkpoints


def build_replay_term_config(batches: list[BatchSpec]) -> dict[str, str]:
    if not batches:
        raise ReplayFailure("cannot build replay term config without batches")
    start_dates = [parse_iso(row.start_iso).date() for row in batches]
    term_from = min(start_dates)
    term_to = max(start_dates)
    return {
        "term_key": f"{term_from.isoformat()}__{term_to.isoformat()}",
        "term_from": term_from.isoformat(),
        "term_to": term_to.isoformat(),
    }


def build_api_client(*, public_api_base: str, api_key: str) -> httpx.Client:
    return httpx.Client(
        base_url=public_api_base.rstrip("/"),
        headers={"X-API-Key": api_key, "Content-Type": "application/json"},
        timeout=20.0,
    )


def ensure_authenticated_session(client: httpx.Client, *, notify_email: str, password: str) -> dict[str, Any]:
    session = client.get("/auth/session")
    if session.status_code == 200:
        session_payload = request_json(client, "GET", "/auth/session")
    else:
        login_payload = {"notify_email": notify_email, "password": password, "timezone_name": "America/Los_Angeles"}
        login = client.post("/auth/login", json=login_payload)
        if login.status_code == 200:
            session_payload = request_json(client, "GET", "/auth/session")
        else:
            register = client.post(
                "/auth/register",
                json={"notify_email": notify_email, "password": password, "timezone_name": "America/Los_Angeles"},
            )
            if register.status_code not in {201, 409}:
                raise ReplayFailure(f"auth register failed status={register.status_code} body={register.text[:800]}")
            if register.status_code == 409:
                login = client.post("/auth/login", json=login_payload)
                if login.status_code != 200:
                    raise ReplayFailure(f"auth login failed status={login.status_code} body={login.text[:800]}")
            session_payload = request_json(client, "GET", "/auth/session")
    user = session_payload.get("user")
    if not isinstance(user, dict):
        raise ReplayFailure("auth session missing user payload")
    return user


def create_source(client: httpx.Client, *, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post("/sources", json=payload)
    if response.status_code >= 400:
        raise ReplayFailure(f"create source failed status={response.status_code} body={response.text[:800]}")
    data = response.json()
    if not isinstance(data, dict):
        raise ReplayFailure("create source returned non-object json")
    return data


def wait_for_bootstrap_syncs(
    client: httpx.Client,
    *,
    sources: list[dict[str, Any]],
    timeout_seconds: float = BOOTSTRAP_WARMUP_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    return [
        wait_for_source_bootstrap_sync(
            client,
            source=source,
            timeout_seconds=timeout_seconds,
        )
        for source in sources
    ]


def wait_for_source_bootstrap_sync(
    client: httpx.Client,
    *,
    source: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    source_id = int(source.get("source_id") or 0)
    if source_id <= 0:
        raise ReplayFailure("bootstrap source payload missing source_id")
    created_at_raw = source.get("created_at")
    created_at = parse_iso(created_at_raw) if isinstance(created_at_raw, str) and created_at_raw else None
    deadline = time.monotonic() + timeout_seconds
    observed_request_id: str | None = None
    last_marker: tuple[Any, ...] | None = None
    stagnant_since = time.monotonic()

    while time.monotonic() < deadline:
        if observed_request_id is None:
            observed_request_id = find_latest_scheduler_sync_request_id_for_source(
                source_id=source_id,
                not_before=created_at,
            )
        if observed_request_id:
            payload = request_json(client, "GET", f"/sync-requests/{observed_request_id}")
            status = str(payload.get("status") or "")
            if status == "FAILED":
                raise ReplayFailure(
                    f"bootstrap sync failed request_id={observed_request_id} source_id={source_id} "
                    f"code={payload.get('error_code')} message={payload.get('error_message')}"
                )
            if status == "SUCCEEDED" and bool(payload.get("applied")):
                return build_bootstrap_result(source=source, status_payload=payload)
            source_row = get_source_row(client, source_id=source_id)
            heartbeat = _combined_progress_marker(
                payload=payload,
                source_row=source_row,
                active_payload=None,
            )
            now = time.monotonic()
            if heartbeat != last_marker:
                last_marker = heartbeat
                stagnant_since = now
            if now - stagnant_since >= SYNC_STALL_TIMEOUT_SECONDS:
                raise ReplayFailure(_build_sync_timeout_message(payload=payload, source_row=source_row, phase="bootstrap"))
        source_row = get_source_row(client, source_id=source_id)
        observability = request_json(client, "GET", f"/sources/{source_id}/observability")
        bootstrap_payload = observability.get("bootstrap") if isinstance(observability.get("bootstrap"), dict) else None
        if bootstrap_payload is not None:
            bootstrap_status = str(bootstrap_payload.get("status") or "")
            if observed_request_id is None and isinstance(bootstrap_payload.get("request_id"), str) and bootstrap_payload.get("request_id"):
                observed_request_id = str(bootstrap_payload["request_id"])
            if bootstrap_status == "FAILED":
                raise ReplayFailure(
                    f"bootstrap sync failed request_id={bootstrap_payload.get('request_id')} source_id={source_id} "
                    f"code={bootstrap_payload.get('error_code')} message={bootstrap_payload.get('error_message')}"
                )
            if bootstrap_status == "SUCCEEDED" and bool(bootstrap_payload.get("applied")):
                return build_bootstrap_result(source=source, status_payload=bootstrap_payload)
        if (
            observed_request_id is None
            and isinstance(source_row.get("last_polled_at"), str)
            and str(source_row.get("sync_state") or "").strip().lower() == "idle"
        ):
            observed_request_id = find_latest_scheduler_sync_request_id_for_source(
                source_id=source_id,
                not_before=created_at,
            )
            if observed_request_id is not None or bootstrap_payload is not None:
                continue
            return build_bootstrap_result(source=source_row, status_payload=None)
        time.sleep(0.5)

    timed_out_request = None
    if observed_request_id is not None:
        timed_out_request = request_json(client, "GET", f"/sync-requests/{observed_request_id}")
    source_row = get_source_row(client, source_id=source_id)
    if isinstance(timed_out_request, dict):
        raise ReplayFailure(_build_sync_timeout_message(payload=timed_out_request, source_row=source_row, phase="bootstrap"))
    raise ReplayFailure(f"bootstrap sync timed out source_id={source_id}")


def build_bootstrap_result(*, source: dict[str, Any], status_payload: dict[str, Any] | None) -> dict[str, Any]:
    source_id = int(source.get("source_id") or 0)
    return {
        "source_id": source_id,
        "source_kind": str(source.get("source_kind") or ""),
        "provider": str(source.get("provider") or ""),
        "request_id": str(status_payload.get("request_id") or "") if isinstance(status_payload, dict) else None,
        "status": str(status_payload.get("status") or "") if isinstance(status_payload, dict) else "unknown",
        "stage": str(status_payload.get("stage") or "") if isinstance(status_payload, dict) else None,
        "substage": str(status_payload.get("substage") or "") if isinstance(status_payload, dict) else None,
        "stage_updated_at": status_payload.get("stage_updated_at") if isinstance(status_payload, dict) else None,
        "applied": bool(status_payload.get("applied")) if isinstance(status_payload, dict) else False,
        "elapsed_ms": (
            int(status_payload.get("elapsed_ms"))
            if isinstance(status_payload, dict) and isinstance(status_payload.get("elapsed_ms"), (int, float))
            else extract_sync_elapsed_ms(status_payload) if isinstance(status_payload, dict) else None
        ),
        "llm_usage": extract_sync_llm_usage(status_payload) if isinstance(status_payload, dict) else None,
        "connector_result": status_payload.get("connector_result") if isinstance(status_payload, dict) else None,
        "created_at": status_payload.get("created_at") if isinstance(status_payload, dict) else source.get("created_at"),
        "updated_at": status_payload.get("updated_at") if isinstance(status_payload, dict) else source.get("updated_at"),
        "applied_at": status_payload.get("applied_at") if isinstance(status_payload, dict) else None,
        "progress": status_payload.get("progress") if isinstance(status_payload, dict) else None,
    }


def create_sync_request(client: httpx.Client, *, source_id: int, trace_id: str) -> str:
    data = request_json(
        client,
        "POST",
        f"/sources/{source_id}/sync-requests",
        json_payload={"trace_id": trace_id, "metadata": {"kind": "timeline_replay", "trace_id": trace_id}},
    )
    request_id = data.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise ReplayFailure("sync request missing request_id")
    return request_id


def wait_sync_success(
    client: httpx.Client,
    *,
    request_id: str,
    source_id: int | None = None,
    timeout_seconds: float = REPLAY_SYNC_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_marker: tuple[Any, ...] | None = None
    stagnant_since = time.monotonic()
    while time.monotonic() < deadline:
        payload = request_json(client, "GET", f"/sync-requests/{request_id}")
        status = str(payload.get("status") or "")
        if status == "FAILED":
            raise ReplayFailure(
                f"sync failed request_id={request_id} code={payload.get('error_code')} message={payload.get('error_message')}"
            )
        if status == "SUCCEEDED" and bool(payload.get("applied")):
            return payload
        effective_source_id = source_id if source_id is not None else int(payload.get("source_id") or 0)
        source_row = get_source_row(client, source_id=effective_source_id) if effective_source_id > 0 else None
        active_payload = None
        if (
            isinstance(source_row, dict)
            and isinstance(source_row.get("active_request_id"), str)
            and source_row.get("active_request_id")
            and source_row.get("active_request_id") != request_id
        ):
            active_payload = request_json(client, "GET", f"/sync-requests/{source_row['active_request_id']}")
        heartbeat = _combined_progress_marker(
            payload=payload,
            source_row=source_row,
            active_payload=active_payload,
        )
        now = time.monotonic()
        if heartbeat != last_marker:
            last_marker = heartbeat
            stagnant_since = now
        if now - stagnant_since >= SYNC_STALL_TIMEOUT_SECONDS:
            raise ReplayFailure(_build_sync_timeout_message(payload=payload, source_row=source_row, phase="replay"))
        time.sleep(0.5)
    payload = request_json(client, "GET", f"/sync-requests/{request_id}")
    source_id = int(payload.get("source_id") or 0)
    source_row = get_source_row(client, source_id=source_id) if source_id > 0 else None
    raise ReplayFailure(_build_sync_timeout_message(payload=payload, source_row=source_row, phase="replay"))


def list_all_changes(client: httpx.Client) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = request_json_list(client, "GET", f"/changes?review_status=all&limit={PAGE_SIZE}&offset={offset}")
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def request_json(client: httpx.Client, method: str, path: str, *, json_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    response = client.request(method, path, json=json_payload)
    if response.status_code >= 400:
        raise ReplayFailure(f"{method} {path} failed status={response.status_code} body={response.text[:800]}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ReplayFailure(f"{method} {path} returned non-object json")
    return payload


def request_json_list(client: httpx.Client, method: str, path: str) -> list[dict[str, Any]]:
    response = client.request(method, path)
    if response.status_code >= 400:
        raise ReplayFailure(f"{method} {path} failed status={response.status_code} body={response.text[:800]}")
    payload = response.json()
    if not isinstance(payload, list):
        raise ReplayFailure(f"{method} {path} returned non-list json")
    return [row for row in payload if isinstance(row, dict)]


def get_source_row(client: httpx.Client, *, source_id: int) -> dict[str, Any]:
    rows = request_json_list(client, "GET", "/sources?status=all")
    for row in rows:
        if int(row.get("source_id") or 0) == source_id:
            return row
    raise ReplayFailure(f"source not found source_id={source_id}")


def _combined_progress_marker(
    *,
    payload: dict[str, Any],
    source_row: dict[str, Any] | None,
    active_payload: dict[str, Any] | None,
) -> tuple[Any, ...]:
    active_request_id = source_row.get("active_request_id") if isinstance(source_row, dict) else None
    active_marker = _sync_payload_marker(active_payload) if isinstance(active_payload, dict) else (None, None, None, None, None, None, None, None, None, None, None)
    return (
        *_sync_payload_marker(payload),
        source_row.get("sync_state") if isinstance(source_row, dict) else None,
        source_row.get("runtime_state") if isinstance(source_row, dict) else None,
        active_request_id,
        *active_marker,
    )


def _sync_payload_marker(payload: dict[str, Any] | None) -> tuple[Any, ...]:
    if not isinstance(payload, dict):
        return (None, None, None, None, None, None, None, None, None, None, None)
    progress = payload.get("progress") if isinstance(payload.get("progress"), dict) else {}
    connector_result = payload.get("connector_result") if isinstance(payload.get("connector_result"), dict) else {}
    llm_usage = payload.get("llm_usage") if isinstance(payload.get("llm_usage"), dict) else {}
    return (
        payload.get("request_id"),
        payload.get("status"),
        payload.get("updated_at"),
        progress.get("phase"),
        progress.get("current"),
        progress.get("total"),
        progress.get("detail"),
        connector_result.get("status"),
        connector_result.get("records_count"),
        llm_usage.get("last_observed_at") or llm_usage.get("successful_call_count"),
        progress.get("updated_at"),
    )


def _build_sync_timeout_message(
    *,
    payload: dict[str, Any],
    source_row: dict[str, Any] | None,
    phase: str,
) -> str:
    request_id = str(payload.get("request_id") or "-")
    source_id = int(payload.get("source_id") or 0)
    status = str(payload.get("status") or "unknown")
    progress = payload.get("progress") if isinstance(payload.get("progress"), dict) else {}
    progress_phase = str(progress.get("phase") or "-")
    progress_label = str(progress.get("label") or "-")
    updated_at_raw = progress.get("updated_at") if isinstance(progress.get("updated_at"), str) and progress.get("updated_at") else payload.get("updated_at")
    age_seconds: int | None = None
    if isinstance(updated_at_raw, str) and updated_at_raw:
        try:
            updated_at = parse_iso(updated_at_raw)
            age_seconds = int(max((datetime.now(UTC) - updated_at).total_seconds(), 0))
        except Exception:
            age_seconds = None
    source_sync_state = str(source_row.get("sync_state") or "-") if isinstance(source_row, dict) else "-"
    source_active_request_id = str(source_row.get("active_request_id") or "-") if isinstance(source_row, dict) else "-"
    source_runtime_state = str(source_row.get("runtime_state") or "-") if isinstance(source_row, dict) else "-"
    detail = (
        f"{phase} sync stalled request_id={request_id} source_id={source_id} status={status} "
        f"progress_phase={progress_phase} progress_label={progress_label} "
        f"request_age_seconds={age_seconds if age_seconds is not None else '-'} "
        f"source_sync_state={source_sync_state} source_runtime_state={source_runtime_state} "
        f"source_active_request_id={source_active_request_id}"
    )
    if source_active_request_id == request_id and source_sync_state == "running":
        return f"{detail} diagnosis=worker_still_active_or_not_finishing"
    if source_active_request_id != request_id and source_sync_state != "running":
        return f"{detail} diagnosis=sync_request_status_or_projection_not_terminated"
    return f"{detail} diagnosis=stuck_unknown"


def find_latest_scheduler_sync_request_id_for_source(*, source_id: int, not_before: datetime | None) -> str | None:
    session_factory = get_session_factory()
    with session_factory() as db:
        stmt = (
            select(SyncRequest)
            .where(
                SyncRequest.source_id == source_id,
                SyncRequest.trigger_type == IngestTriggerType.SCHEDULER,
            )
            .order_by(SyncRequest.created_at.desc(), SyncRequest.id.desc())
            .limit(1)
        )
        row = db.scalar(stmt)
        if row is None:
            return None
        if not_before is not None and row.created_at < not_before:
            return None
        return str(row.request_id or "") or None


def count_event_entities_for_user(*, user_id: int) -> int:
    session_factory = get_session_factory()
    with session_factory() as db:
        count = db.scalar(select(func.count()).select_from(EventEntity).where(EventEntity.user_id == user_id))
        return int(count or 0)


def start_fake_provider(*, host: str, port: int, manifest_path: Path) -> int:
    return start_fake_provider_with_bucket(host=host, port=port, manifest_path=manifest_path, email_bucket=None)


def start_fake_provider_with_bucket(*, host: str, port: int, manifest_path: Path, email_bucket: str | None) -> int:
    command = [
        sys.executable,
        "scripts/fake_source_provider.py",
        "--host",
        host,
        "--port",
        str(port),
        "--scenario-manifest",
        str(manifest_path),
    ]
    if isinstance(email_bucket, str) and email_bucket.strip():
        command.extend(["--email-bucket", email_bucket.strip()])
    process = subprocess.Popen(
        command,
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return int(process.pid)


def ensure_fake_provider_for_state(state: dict[str, Any]) -> None:
    host = str(state["fake_provider"]["host"])
    port = int(state["fake_provider"]["port"])
    if fake_provider_ready(host=host, port=port):
        return
    if not bool(state["fake_provider"].get("started_by_harness")):
        raise ReplayFailure("fake provider is not reachable")
    manifest_path = Path(state["manifest_path"]).resolve()
    pid = start_fake_provider_with_bucket(
        host=host,
        port=port,
        manifest_path=manifest_path,
        email_bucket=str(state.get("email_bucket") or ""),
    )
    state["fake_provider"]["pid"] = pid
    ensure_fake_provider_ready(host=host, port=port)


def ensure_fake_provider_ready(*, host: str, port: int, timeout_seconds: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if fake_provider_ready(host=host, port=port):
            return
        time.sleep(0.2)
    raise ReplayFailure("fake provider did not become ready")


def fake_provider_ready(*, host: str, port: int) -> bool:
    try:
        response = httpx.get(f"http://{host}:{port}/__admin/state", timeout=1.0)
        return response.status_code == 200
    except Exception:
        return False


def set_fake_provider_batch(*, host: str, port: int, semester: int, batch: int, run_tag: str) -> None:
    response = httpx.post(
        f"http://{host}:{port}/__admin/semester-batch",
        json={"semester": semester, "batch": batch, "run_tag": run_tag},
        timeout=5.0,
    )
    if response.status_code != 200:
        raise ReplayFailure(f"failed to set fake provider semester/batch to {semester}/{batch}: {response.text[:400]}")


def parse_iso(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    return parsed.astimezone(UTC)


def load_state(run_dir: Path) -> dict[str, Any]:
    state_path = run_dir / STATE_FILE
    if not state_path.exists():
        raise ReplayFailure(f"run state not found: {state_path}")
    return json.loads(state_path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except ReplayFailure as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
