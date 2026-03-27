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
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = REPO_ROOT / "frontend"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.modules.runtime.kernel.parse_task_queue import (
    get_parse_queue_redis_client,
    parse_queue_depth,
    parse_retry_depth,
)
import scripts.run_year_timeline_replay_smoke as replay

OUTPUT_ROOT = REPO_ROOT / "output"
SUMMARY_JSON = "SUMMARY.json"
SUMMARY_MD = "SUMMARY.md"
GMAIL_PROBE_TIMEOUT_SECONDS = 180.0
FLOW_TWO_READY_TIMEOUT_SECONDS = 45.0
GMAIL_REVIEW_PREP_TIMEOUT_SECONDS = 1800.0
GMAIL_REVIEW_PREP_STALL_WINDOW_SECONDS = 600.0
ICS_REVIEW_PREP_TIMEOUT_SECONDS = 600.0
ICS_REVIEW_PREP_STALL_WINDOW_SECONDS = 240.0
WAIT_TIME_EPSILON_SECONDS = 1e-6


class RealFlowEvalError(RuntimeError):
    pass


@dataclass(frozen=True)
class FlowDefinition:
    flow_id: str
    title: str


@dataclass
class FlowResult:
    flow_id: str
    title: str
    status: str
    browser_checks_passed: bool
    api_checks_passed: bool
    user_visible_outcome: str
    artifacts: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


FLOWS = [
    FlowDefinition("auth_register_and_enter_onboarding", "Register and enter onboarding"),
    FlowDefinition("canvas_ics_onboarding_to_ready", "Complete Canvas onboarding to ready"),
    FlowDefinition("gmail_source_sync_and_observability", "Connect fake Gmail source and inspect observability"),
    FlowDefinition("changes_review_resolution", "Resolve pending changes through review actions"),
    FlowDefinition("agent_assisted_low_risk_action", "Create MCP token and verify a low-risk agent action"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the CalendarDIFF hybrid real-user-flow eval.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run")
    run.add_argument("--public-api-base", required=True)
    run.add_argument("--frontend-base", required=True)
    run.add_argument("--api-key", default=os.getenv("APP_API_KEY", ""))
    run.add_argument("--manifest", default=str(replay.DEFAULT_MANIFEST))
    run.add_argument("--email-bucket", default=replay.DEFAULT_EMAIL_BUCKET)
    run.add_argument("--ics-derived-set", default=replay.DEFAULT_ICS_DERIVED_SET)
    run.add_argument("--fake-provider-host", default=replay.DEFAULT_FAKE_HOST)
    run.add_argument("--fake-provider-port", type=int, default=replay.DEFAULT_FAKE_PORT)
    run.add_argument("--start-fake-provider", action=argparse.BooleanOptionalAction, default=True)
    run.add_argument("--email", default=None)
    run.add_argument("--password", default=os.getenv("SMOKE_AUTH_PASSWORD", "password123"))
    run.add_argument("--output-root", default=str(OUTPUT_ROOT))
    run.add_argument("--mcp-token-label", default="Real Flow Eval")

    report = subparsers.add_parser("report")
    report.add_argument("--run-dir", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "run":
        run_dir = run_eval(args)
        print(run_dir)
        return

    run_dir = Path(args.run_dir).expanduser().resolve()
    summary_path = run_dir / SUMMARY_JSON
    if not summary_path.exists():
        raise SystemExit(f"summary not found: {summary_path}")
    print(json.dumps(json.loads(summary_path.read_text(encoding="utf-8")), ensure_ascii=False, indent=2))


def flow_ids() -> list[str]:
    return [flow.flow_id for flow in FLOWS]


def build_summary_markdown(*, summary: dict[str, Any]) -> str:
    lines = [
        "# Real User Flow Eval",
        "",
        f"- Overall: **{summary['overall_status']}**",
        f"- Generated at: `{summary['generated_at']}`",
        "",
    ]
    preflight = summary.get("preflight")
    if isinstance(preflight, dict):
        lines.extend(
            [
                "## Preflight",
                "",
                f"- Status: `{preflight.get('status', 'unknown')}`",
                f"- Failure stage: `{summary.get('failure_stage') or 'none'}`",
            ]
        )
        remediation = preflight.get("remediation")
        if isinstance(remediation, str) and remediation.strip():
            lines.append(f"- Remediation: {remediation}")
        lines.append("")
    lines.extend(
        [
        "## Flows",
        "",
        ]
    )
    for flow in summary["flows"]:
        lines.extend(
            [
                f"### {flow['flow_id']}",
                f"- Title: {flow['title']}",
                f"- Status: `{flow['status']}`",
                f"- Browser checks: `{flow['browser_checks_passed']}`",
                f"- API checks: `{flow['api_checks_passed']}`",
                f"- Outcome: {flow['user_visible_outcome']}",
            ]
        )
        if flow["notes"]:
            lines.append("- Notes:")
            for note in flow["notes"]:
                lines.append(f"  - {note}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def normalize_failure_message(exc: Exception) -> str:
    message = str(exc)
    if "gmail_auth_failed" in message:
        return (
            f"{message} "
            "Hint: the running backend is likely still pointed at the real Gmail API. "
            "For fake Gmail flow coverage, restart the backend with "
            "GMAIL_API_BASE_URL=http://127.0.0.1:8765/gmail/v1/users/me "
            "and keep the fake provider on the same host/port passed to this runner."
        )
    return message


def fake_gmail_remediation(*, host: str, port: int) -> str:
    return (
        "Restart the backend with "
        f"GMAIL_API_BASE_URL=http://{host}:{port}/gmail/v1/users/me "
        "and keep the fake provider host/port aligned with this runner."
    )


def build_skipped_results(*, reason: str, start_index: int = 0) -> list[FlowResult]:
    return [
        FlowResult(
            flow_id=flow.flow_id,
            title=flow.title,
            status="skipped",
            browser_checks_passed=False,
            api_checks_passed=False,
            user_visible_outcome=reason,
            notes=["Runner did not execute this flow because an earlier prerequisite or flow failed."],
        )
        for flow in FLOWS[start_index:]
    ]


def build_lightweight_gmail_monitoring_config(monitoring_config: dict[str, str]) -> dict[str, str]:
    out = dict(monitoring_config)
    # Keep the Gmail window lightweight without risking a "not started yet"
    # 409 when the local user timezone trails UTC near midnight.
    out["monitor_since"] = (datetime.now(replay.UTC).date() - timedelta(days=1)).isoformat()
    out["label_id"] = "INBOX"
    out.pop("label_ids", None)
    return out


def probe_fake_gmail_backend_ready(
    *,
    public_api_base: str,
    api_key: str,
    password: str,
    monitoring_config: dict[str, str],
    fake_provider_host: str,
    fake_provider_port: int,
    run_dir: Path,
) -> dict[str, Any]:
    probe_email = f"{run_dir.name}-probe-{uuid.uuid4().hex[:8]}@example.com"
    client = replay.build_api_client(public_api_base=public_api_base, api_key=api_key)
    try:
        user = replay.ensure_authenticated_session(client, email=probe_email, password=password)
        source = replay.create_source(
            client,
            payload={
                "source_kind": "email",
                "provider": "gmail",
                "display_name": "Real Flow Gmail Probe",
                "config": {"label_id": "INBOX", **monitoring_config},
                "secrets": {
                    "access_token": "fake-access-token",
                    "account_email": "fake.student@example.edu",
                },
            },
        )
        request_id = replay.create_sync_request(
            client,
            source_id=int(source["source_id"]),
            trace_id=f"real-flow-probe-{uuid.uuid4().hex[:8]}",
        )
        try:
            payload = wait_for_probe_progress(
                client,
                request_id=request_id,
                timeout_seconds=GMAIL_PROBE_TIMEOUT_SECONDS,
            )
            return {
                "ok": True,
                "status": "passed",
                "user_id": int(user["id"]),
                "source_id": int(source["source_id"]),
                "request_id": request_id,
                "result_status": payload.get("status"),
                "failure_stage": None,
                "remediation": None,
            }
        except Exception as exc:
            normalized = normalize_failure_message(exc)
            if "gmail_auth_failed" in str(exc):
                return {
                    "ok": False,
                    "status": "failed",
                    "user_id": int(user["id"]),
                    "source_id": int(source["source_id"]),
                    "request_id": request_id,
                    "failure_stage": "backend_not_fake_gmail_ready",
                    "failure": normalized,
                    "remediation": fake_gmail_remediation(host=fake_provider_host, port=fake_provider_port),
                }
            return {
                "ok": False,
                "status": "failed",
                "user_id": int(user["id"]),
                "source_id": int(source["source_id"]),
                "request_id": request_id,
                "failure_stage": "backend_worker_pipeline_stalled",
                "failure": normalized,
                "status_payload": _summarize_probe_status(payload=None),
                "remediation": (
                    "The fake Gmail probe reached llm_queue but did not complete in time. "
                    "Inspect the backend worker pipeline, Redis parse queue state, and source runtime progress."
                ),
            }
    finally:
        client.close()


def wait_for_probe_progress(
    client: httpx.Client,
    *,
    request_id: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        payload = replay.request_json(client, "GET", f"/sync-requests/{request_id}")
        status = str(payload.get("status") or "")
        stage = str(payload.get("stage") or "").strip().lower()
        progress = payload.get("progress") if isinstance(payload.get("progress"), dict) else {}
        phase = str(progress.get("phase") or "").strip().lower()
        if status == "FAILED":
            raise RealFlowEvalError(
                f"sync failed request_id={request_id} code={payload.get('error_code')} message={payload.get('error_message')}"
            )
        if status == "SUCCEEDED" and bool(payload.get("applied")):
            return payload
        if status == "RUNNING" and (phase in {"llm_queue", "llm_parse", "result_ready", "completed"} or stage in {"llm_parse", "result_ready", "completed"}):
            return payload
        time.sleep(1.0)
    raise RealFlowEvalError(f"probe sync stalled request_id={request_id}")


def wait_for_source_flow_progress(
    client: httpx.Client,
    *,
    request_id: str,
    source_id: int,
    timeout_seconds: float,
    stall_window_seconds: float,
    allow_observability_ready: bool,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    stalled_since = time.monotonic()
    grace_extension_used = False
    last_marker: tuple[Any, ...] | None = None
    latest_payload: dict[str, Any] | None = None
    latest_observability: dict[str, Any] | None = None
    latest_queue_diagnostics: dict[str, Any] | None = None
    last_progress_observed_at: str | None = None

    while True:
        now_monotonic = time.monotonic()
        if now_monotonic + WAIT_TIME_EPSILON_SECONDS >= deadline:
            if (
                not grace_extension_used
                and _sync_request_is_actively_progressing(payload=latest_payload, observability=latest_observability)
            ):
                deadline = now_monotonic + stall_window_seconds
                grace_extension_used = True
            else:
                raise RealFlowEvalError(
                    json.dumps(
                        _build_stalled_failure_details(
                            payload=latest_payload,
                            observability=latest_observability,
                            last_progress_observed_at=last_progress_observed_at,
                            queue_diagnostics=latest_queue_diagnostics,
                        ),
                        ensure_ascii=False,
                    )
                )
        payload = replay.request_json(client, "GET", f"/sync-requests/{request_id}")
        latest_payload = payload
        status = str(payload.get("status") or "")
        if status == "FAILED":
            raise RealFlowEvalError(
                f"sync failed request_id={request_id} code={payload.get('error_code')} message={payload.get('error_message')}"
            )
        if status == "SUCCEEDED":
            return payload

        observability = replay.request_json(client, "GET", f"/sources/{source_id}/observability")
        latest_observability = observability
        latest_queue_diagnostics = collect_parse_queue_diagnostics()
        if allow_observability_ready and _observability_is_ready_for_flow(request_id=request_id, observability=observability):
            return payload

        marker = _build_progress_marker(
            payload=payload,
            observability=observability,
            queue_diagnostics=latest_queue_diagnostics,
        )
        if marker != last_marker:
            last_marker = marker
            stalled_since = now_monotonic
            last_progress_observed_at = datetime.now(replay.UTC).isoformat()

        if now_monotonic - stalled_since + WAIT_TIME_EPSILON_SECONDS >= stall_window_seconds:
            raise RealFlowEvalError(
                json.dumps(
                    _build_stalled_failure_details(
                        payload=latest_payload,
                        observability=latest_observability,
                        last_progress_observed_at=last_progress_observed_at,
                        queue_diagnostics=latest_queue_diagnostics,
                    ),
                    ensure_ascii=False,
                )
            )
        time.sleep(1.0)


def wait_for_gmail_flow_progress(
    client: httpx.Client,
    *,
    request_id: str,
    source_id: int,
    timeout_seconds: float = 180.0,
    stall_window_seconds: float = 60.0,
) -> dict[str, Any]:
    return wait_for_source_flow_progress(
        client,
        request_id=request_id,
        source_id=source_id,
        timeout_seconds=timeout_seconds,
        stall_window_seconds=stall_window_seconds,
        allow_observability_ready=True,
    )


def wait_for_review_prep_source_sync(
    client: httpx.Client,
    *,
    request_id: str,
    source_id: int,
    provider: str,
    timeout_seconds: float | None = None,
    stall_window_seconds: float | None = None,
) -> dict[str, Any]:
    normalized_provider = str(provider or "").strip().lower()
    resolved_timeout = (
        GMAIL_REVIEW_PREP_TIMEOUT_SECONDS
        if normalized_provider == "gmail"
        else ICS_REVIEW_PREP_TIMEOUT_SECONDS
    ) if timeout_seconds is None else timeout_seconds
    resolved_stall_window = (
        GMAIL_REVIEW_PREP_STALL_WINDOW_SECONDS
        if normalized_provider == "gmail"
        else ICS_REVIEW_PREP_STALL_WINDOW_SECONDS
    ) if stall_window_seconds is None else stall_window_seconds
    return wait_for_source_flow_progress(
        client,
        request_id=request_id,
        source_id=source_id,
        timeout_seconds=resolved_timeout,
        stall_window_seconds=resolved_stall_window,
        allow_observability_ready=False,
    )


def wait_for_onboarding_ready_with_ics_source(
    client: httpx.Client,
    *,
    timeout_seconds: float = FLOW_TWO_READY_TIMEOUT_SECONDS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    latest_status: dict[str, Any] | None = None
    latest_source_rows: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        latest_status = replay.request_json(client, "GET", "/onboarding/status")
        latest_source_rows = replay.request_json_list(client, "GET", "/sources?status=all")
        ics_source = next((row for row in latest_source_rows if row.get("provider") == "ics"), None)
        if str((latest_status or {}).get("stage") or "") == "ready" and isinstance(ics_source, dict):
            return latest_status, ics_source
        time.sleep(1.0)
    raise RealFlowEvalError(
        "flow 2 failed to produce a ready user with an ICS source "
        f"stage={str((latest_status or {}).get('stage') or '-')}, "
        f"source_count={len(latest_source_rows)}"
    )


def _build_progress_marker(
    *,
    payload: dict[str, Any] | None,
    observability: dict[str, Any] | None,
    queue_diagnostics: dict[str, Any] | None = None,
) -> tuple[Any, ...]:
    progress = payload.get("progress") if isinstance(payload, dict) and isinstance(payload.get("progress"), dict) else {}
    active = observability.get("active") if isinstance(observability, dict) and isinstance(observability.get("active"), dict) else {}
    bootstrap = observability.get("bootstrap") if isinstance(observability, dict) and isinstance(observability.get("bootstrap"), dict) else {}
    latest_replay = observability.get("latest_replay") if isinstance(observability, dict) and isinstance(observability.get("latest_replay"), dict) else {}
    active_progress = active.get("progress") if isinstance(active, dict) and isinstance(active.get("progress"), dict) else {}
    return (
        payload.get("updated_at") if isinstance(payload, dict) else None,
        payload.get("stage") if isinstance(payload, dict) else None,
        payload.get("substage") if isinstance(payload, dict) else None,
        progress.get("phase") if isinstance(progress, dict) else None,
        progress.get("updated_at") if isinstance(progress, dict) else None,
        observability.get("active_request_id") if isinstance(observability, dict) else None,
        active.get("updated_at") if isinstance(active, dict) else None,
        active.get("stage") if isinstance(active, dict) else None,
        active.get("substage") if isinstance(active, dict) else None,
        active_progress.get("phase") if isinstance(active_progress, dict) else None,
        active_progress.get("updated_at") if isinstance(active_progress, dict) else None,
        bootstrap.get("updated_at") if isinstance(bootstrap, dict) else None,
        bootstrap.get("status") if isinstance(bootstrap, dict) else None,
        latest_replay.get("updated_at") if isinstance(latest_replay, dict) else None,
        latest_replay.get("status") if isinstance(latest_replay, dict) else None,
        observability.get("source_product_phase") if isinstance(observability, dict) else None,
        (observability.get("source_recovery") or {}).get("trust_state") if isinstance(observability, dict) and isinstance(observability.get("source_recovery"), dict) else None,
        (queue_diagnostics or {}).get("parse_queue_depth") if isinstance(queue_diagnostics, dict) else None,
        (queue_diagnostics or {}).get("parse_retry_depth") if isinstance(queue_diagnostics, dict) else None,
    )


def _sync_request_is_actively_progressing(*, payload: dict[str, Any] | None, observability: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    status = str(payload.get("status") or "").strip().upper()
    stage = str(payload.get("stage") or "").strip().lower()
    progress = payload.get("progress") if isinstance(payload.get("progress"), dict) else {}
    progress_phase = str(progress.get("phase") or "").strip().lower()
    if status != "RUNNING":
        return False
    if stage in {"llm_parse", "result_ready", "applying", "completed"}:
        return True
    if progress_phase in {"llm_queue", "llm_parse", "result_ready", "completed"}:
        return True
    active = observability.get("active") if isinstance(observability, dict) and isinstance(observability.get("active"), dict) else {}
    active_status = str(active.get("status") or "").strip().upper()
    active_progress = active.get("progress") if isinstance(active, dict) and isinstance(active.get("progress"), dict) else {}
    active_phase = str(active_progress.get("phase") or "").strip().lower()
    return active_status == "RUNNING" and active_phase in {"llm_queue", "llm_parse", "result_ready", "completed"}


def _observability_is_ready_for_flow(*, request_id: str, observability: dict[str, Any] | None) -> bool:
    if not isinstance(observability, dict):
        return False
    source_product_phase = observability.get("source_product_phase")
    source_recovery = observability.get("source_recovery") if isinstance(observability.get("source_recovery"), dict) else {}
    if not isinstance(source_product_phase, str) or not source_product_phase.strip():
        return False
    if not isinstance(source_recovery, dict) or not isinstance(source_recovery.get("trust_state"), str):
        return False
    active_request_id = str(observability.get("active_request_id") or "").strip()
    if active_request_id == request_id:
        return False
    for key in ("bootstrap", "latest_replay"):
        item = observability.get(key)
        if not isinstance(item, dict):
            continue
        if str(item.get("request_id") or "").strip() != request_id:
            continue
        if not isinstance(item.get("status"), str) or not str(item.get("status")).strip():
            continue
        return True
    return False


def _summarize_probe_status(
    *,
    payload: dict[str, Any] | None,
    observability: dict[str, Any] | None = None,
    last_progress_observed_at: str | None = None,
    queue_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    progress = payload.get("progress") if isinstance(payload, dict) and isinstance(payload.get("progress"), dict) else {}
    active = observability.get("active") if isinstance(observability, dict) and isinstance(observability.get("active"), dict) else {}
    active_progress = active.get("progress") if isinstance(active, dict) and isinstance(active.get("progress"), dict) else {}
    bootstrap = observability.get("bootstrap") if isinstance(observability, dict) and isinstance(observability.get("bootstrap"), dict) else {}
    latest_replay = observability.get("latest_replay") if isinstance(observability, dict) and isinstance(observability.get("latest_replay"), dict) else {}
    source_recovery = observability.get("source_recovery") if isinstance(observability, dict) and isinstance(observability.get("source_recovery"), dict) else {}
    summary = {
        "request_id": payload.get("request_id") if isinstance(payload, dict) else None,
        "source_id": payload.get("source_id") if isinstance(payload, dict) else None,
        "status": payload.get("status") if isinstance(payload, dict) else None,
        "stage": payload.get("stage") if isinstance(payload, dict) else None,
        "substage": payload.get("substage") if isinstance(payload, dict) else None,
        "progress_phase": progress.get("phase") if isinstance(progress, dict) else None,
        "progress_label": progress.get("label") if isinstance(progress, dict) else None,
        "latest_updated_at": payload.get("updated_at") if isinstance(payload, dict) else None,
        "source_sync_state": active.get("sync_state") if isinstance(active, dict) else (observability or {}).get("sync_state") if isinstance(observability, dict) else None,
        "source_runtime_state": active.get("runtime_state") if isinstance(active, dict) else (observability or {}).get("runtime_state") if isinstance(observability, dict) else None,
        "source_active_request_id": (observability or {}).get("active_request_id") if isinstance(observability, dict) else None,
        "source_product_phase": observability.get("source_product_phase") if isinstance(observability, dict) else None,
        "source_recovery_trust_state": source_recovery.get("trust_state") if isinstance(source_recovery, dict) else None,
        "bootstrap_request_id": bootstrap.get("request_id") if isinstance(bootstrap, dict) else None,
        "bootstrap_status": bootstrap.get("status") if isinstance(bootstrap, dict) else None,
        "latest_replay_request_id": latest_replay.get("request_id") if isinstance(latest_replay, dict) else None,
        "latest_replay_status": latest_replay.get("status") if isinstance(latest_replay, dict) else None,
        "last_sync_payload_updated_at": _coalesce_timestamp(
            progress.get("updated_at") if isinstance(progress, dict) else None,
            payload.get("updated_at") if isinstance(payload, dict) else None,
        ),
        "last_observability_updated_at": _coalesce_timestamp(
            active_progress.get("updated_at") if isinstance(active_progress, dict) else None,
            active.get("stage_updated_at") if isinstance(active, dict) else None,
            active.get("updated_at") if isinstance(active, dict) else None,
            latest_replay.get("updated_at") if isinstance(latest_replay, dict) else None,
            bootstrap.get("updated_at") if isinstance(bootstrap, dict) else None,
        ),
        "last_progress_observed_at": last_progress_observed_at,
    }
    if isinstance(queue_diagnostics, dict):
        summary.update(queue_diagnostics)
    return summary


def collect_parse_queue_diagnostics() -> dict[str, Any]:
    settings = get_settings()
    diagnostics: dict[str, Any] = {
        "parse_queue_depth": None,
        "parse_retry_depth": None,
        "llm_worker_concurrency": max(1, int(settings.llm_worker_concurrency)),
        "llm_queue_consumer_poll_ms": max(1, int(settings.llm_queue_consumer_poll_ms)),
    }
    redis_client = None
    try:
        redis_client = get_parse_queue_redis_client()
        diagnostics["parse_queue_depth"] = parse_queue_depth(redis_client)
        diagnostics["parse_retry_depth"] = parse_retry_depth(redis_client)
    except Exception as exc:
        diagnostics["parse_queue_error"] = str(exc)
    finally:
        if redis_client is not None:
            try:
                redis_client.close()
            except Exception:
                pass
    return diagnostics


def _build_stalled_failure_details(
    *,
    payload: dict[str, Any] | None,
    observability: dict[str, Any] | None,
    last_progress_observed_at: str | None,
    queue_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "failure_stage": "backend_worker_pipeline_stalled",
        **_summarize_probe_status(
            payload=payload,
            observability=observability,
            last_progress_observed_at=last_progress_observed_at,
            queue_diagnostics=queue_diagnostics if isinstance(queue_diagnostics, dict) else collect_parse_queue_diagnostics(),
        ),
    }


def _coalesce_timestamp(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return None


def _extract_structured_failure_details(message: str) -> dict[str, Any] | None:
    normalized = str(message or "").strip()
    if not normalized.startswith("{"):
        return None
    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def change_focus_path(change: dict[str, Any]) -> str:
    bucket = "initial_review" if str(change.get("review_bucket") or "") == "initial_review" else "changes"
    return f"/changes?bucket={bucket}&focus={int(change['id'])}"


def select_review_targets(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    pending = [row for row in rows if str(row.get("review_status") or "") == "pending"]
    editable = [row for row in pending if str(row.get("change_type") or "") in {"created", "due_changed"}]
    if len(pending) < 3 or len(editable) < 2:
        raise RealFlowEvalError("not enough pending changes to drive the review flow")
    approve = editable[0]
    edit = next(row for row in editable if int(row["id"]) != int(approve["id"]))
    reject = next(row for row in pending if int(row["id"]) not in {int(approve["id"]), int(edit["id"])} )
    return {"approve": approve, "reject": reject, "edit": edit}


def run_eval(args: argparse.Namespace) -> Path:
    api_key = str(args.api_key or "").strip()
    if not api_key:
        raise RealFlowEvalError("--api-key or APP_API_KEY is required")

    run_dir = Path(args.output_root).expanduser().resolve() / f"real-user-flow-eval-{time.strftime('%Y%m%d-%H%M%S')}"
    (run_dir / "per_flow").mkdir(parents=True, exist_ok=True)
    (run_dir / "screenshots").mkdir(parents=True, exist_ok=True)
    (run_dir / "playwright-output").mkdir(parents=True, exist_ok=True)
    (run_dir / "browser_events.jsonl").write_text("", encoding="utf-8")
    (run_dir / "api_events.jsonl").write_text("", encoding="utf-8")

    public_api_base = str(args.public_api_base).rstrip("/")
    frontend_base = str(args.frontend_base).rstrip("/")
    manifest_path = Path(args.manifest).expanduser().resolve()
    email = str(args.email or f"real-flow-{uuid.uuid4().hex[:10]}@example.com")
    password = str(args.password)

    ensure_http_ready(public_api_base, "/health", "backend health")
    ensure_http_ready(frontend_base, "/login", "frontend login")

    fake_provider_pid: int | None = None
    fake_provider_started = False
    client: httpx.Client | None = None
    results: list[FlowResult] = []
    current_flow_index = -1
    try:
        batches = replay.load_batch_specs(json.loads(manifest_path.read_text(encoding="utf-8")))
        if not batches:
            raise RealFlowEvalError("manifest did not produce any replay batches")
        monitoring_config = replay.build_replay_monitoring_config(batches)
        if bool(args.start_fake_provider):
            fake_provider_pid = replay.start_fake_provider_with_bucket(
                host=str(args.fake_provider_host),
                port=int(args.fake_provider_port),
                manifest_path=manifest_path,
                email_bucket=str(args.email_bucket),
            )
            fake_provider_started = True
        replay.ensure_fake_provider_ready(host=str(args.fake_provider_host), port=int(args.fake_provider_port))
        replay.set_fake_provider_batch(
            host=str(args.fake_provider_host),
            port=int(args.fake_provider_port),
            semester=batches[0].semester,
            batch=batches[0].batch,
            run_tag=run_dir.name,
        )

        client = replay.build_api_client(public_api_base=public_api_base, api_key=api_key)
        preflight = probe_fake_gmail_backend_ready(
            public_api_base=public_api_base,
            api_key=api_key,
            password=password,
            monitoring_config=monitoring_config,
            fake_provider_host=str(args.fake_provider_host),
            fake_provider_port=int(args.fake_provider_port),
            run_dir=run_dir,
        )
        if not preflight["ok"]:
            results.extend(build_skipped_results(reason="Skipped because hybrid eval preflight failed."))
            summary = build_summary(
                run_dir=run_dir,
                results=results,
                failure_stage=str(preflight["failure_stage"]),
                preflight=preflight,
            )
            summary["failure"] = str(preflight["failure"])
            write_summary(run_dir=run_dir, summary=summary)
            print(run_dir)
            raise RealFlowEvalError(str(preflight["failure"]))

        current_flow_index = 0
        auth_context = {"flow_id": FLOWS[0].flow_id, "email": email, "password": password}
        browser_one = run_browser_stage(
          flow_id=FLOWS[0].flow_id,
          stage="default",
          context_payload=auth_context,
          frontend_base=frontend_base,
          run_dir=run_dir,
      )
        user = replay.ensure_authenticated_session(client, email=email, password=password)
        onboarding_status = replay.request_json(client, "GET", "/onboarding/status")
        if str(onboarding_status.get("stage") or "") != "needs_canvas_ics":
            raise RealFlowEvalError("flow 1 expected onboarding stage needs_canvas_ics")
        log_api_event(run_dir, FLOWS[0].flow_id, "session_ready", {"user_id": user["id"], "stage": onboarding_status["stage"]})
        results.append(
            FlowResult(
                flow_id=FLOWS[0].flow_id,
                title=FLOWS[0].title,
                status="passed",
                browser_checks_passed=bool(browser_one.get("passed")),
                api_checks_passed=True,
                user_visible_outcome="The browser register flow lands in onboarding and backend session stage is needs_canvas_ics.",
                artifacts={"browser": browser_one},
                notes=[
                    "Browser executed register form submission and redirect check.",
                    "Backend verified /auth/session and /onboarding/status.",
                    "No fake provider dependency was needed beyond bootstrap availability.",
                ],
            )
        )

        current_flow_index = 1
        onboarding_context = {
          "flow_id": FLOWS[1].flow_id,
          "email": email,
          "password": password,
          "ics_url": f"http://{args.fake_provider_host}:{args.fake_provider_port}/ics/calendar.ics",
          "monitor_since": monitoring_config["monitor_since"],
      }
        browser_two = run_browser_stage(
          flow_id=FLOWS[1].flow_id,
          stage="default",
          context_payload=onboarding_context,
          frontend_base=frontend_base,
          run_dir=run_dir,
      )
        onboarding_status, ics_source = wait_for_onboarding_ready_with_ics_source(client)
        log_api_event(run_dir, FLOWS[1].flow_id, "onboarding_ready", {"ics_source_id": ics_source["source_id"], "stage": onboarding_status["stage"]})
        results.append(
          FlowResult(
              flow_id=FLOWS[1].flow_id,
              title=FLOWS[1].title,
              status="passed",
              browser_checks_passed=bool(browser_two.get("passed")),
              api_checks_passed=True,
              user_visible_outcome="Canvas onboarding completed in the browser and the workspace became ready.",
              artifacts={"browser": browser_two, "ics_source_id": int(ics_source["source_id"])},
              notes=[
                  "Browser submitted Canvas ICS URL, skipped Gmail, and saved monitoring window.",
                  "Backend verified ready onboarding state and ICS source creation.",
                  "Fake provider supplied the ICS endpoint used in onboarding.",
              ],
          )
      )

        current_flow_index = 2
        gmail_source = ensure_gmail_source(
          client=client,
          monitoring_config=build_lightweight_gmail_monitoring_config(monitoring_config),
          fake_provider_host=str(args.fake_provider_host),
          fake_provider_port=int(args.fake_provider_port),
      )
        gmail_trace = f"real-flow-gmail-{uuid.uuid4().hex[:8]}"
        gmail_request_id = replay.create_sync_request(client, source_id=int(gmail_source["source_id"]), trace_id=gmail_trace)
        gmail_sync = wait_for_gmail_flow_progress(client, request_id=gmail_request_id, source_id=int(gmail_source["source_id"]))
        gmail_observability = replay.request_json(client, "GET", f"/sources/{gmail_source['source_id']}/observability")
        browser_three = run_browser_stage(
          flow_id=FLOWS[2].flow_id,
          stage="default",
          context_payload={
              "flow_id": FLOWS[2].flow_id,
              "email": email,
              "password": password,
              "source_name": gmail_source.get("display_name") or "Replay Gmail Source",
              "source_detail_path": f"/sources/{int(gmail_source['source_id'])}",
          },
          frontend_base=frontend_base,
          run_dir=run_dir,
      )
        log_api_event(
          run_dir,
          FLOWS[2].flow_id,
          "gmail_sync_complete",
          {"source_id": gmail_source["source_id"], "request_id": gmail_request_id, "status": gmail_sync["status"]},
      )
        results.append(
          FlowResult(
              flow_id=FLOWS[2].flow_id,
              title=FLOWS[2].title,
              status="passed",
              browser_checks_passed=bool(browser_three.get("passed")),
              api_checks_passed=True,
              user_visible_outcome="The user can see the fake Gmail source and its observability after a real sync request completes.",
              artifacts={
                  "browser": browser_three,
                  "source_id": int(gmail_source["source_id"]),
                  "sync_request_id": gmail_request_id,
              },
              notes=[
                  "Backend created the fake Gmail source through the public /sources API.",
                  "A real sync request was triggered and observed through /sync-requests and /sources/{id}/observability.",
                  "Browser verified the source list and source detail posture after sync.",
              ],
          )
      )

        current_flow_index = 3
        review_targets = ensure_review_targets(
          client=client,
          batches=batches,
          ics_source_id=int(ics_source["source_id"]),
          gmail_source_id=int(gmail_source["source_id"]),
          fake_provider_host=str(args.fake_provider_host),
          fake_provider_port=int(args.fake_provider_port),
          run_tag=run_dir.name,
          run_dir=run_dir,
      )
        edited_name = f"Real Flow Edited {uuid.uuid4().hex[:4]}"
        browser_four = run_browser_stage(
          flow_id=FLOWS[3].flow_id,
          stage="default",
          context_payload={
              "flow_id": FLOWS[3].flow_id,
              "email": email,
              "password": password,
              "approve_path": change_focus_path(review_targets["approve"]),
              "reject_path": change_focus_path(review_targets["reject"]),
              "edit_path": f"/changes/{int(review_targets['edit']['id'])}/proposal",
              "edit_approve_path": change_focus_path(review_targets["edit"]),
              "edited_event_name": edited_name,
          },
          frontend_base=frontend_base,
          run_dir=run_dir,
      )
        approved_row = replay.request_json(client, "GET", f"/changes/{int(review_targets['approve']['id'])}")
        rejected_row = replay.request_json(client, "GET", f"/changes/{int(review_targets['reject']['id'])}")
        edited_row = replay.request_json(client, "GET", f"/changes/{int(review_targets['edit']['id'])}")
        edited_context = replay.request_json(client, "GET", f"/changes/{int(review_targets['edit']['id'])}/edit-context")
        if approved_row.get("review_status") != "approved":
            raise RealFlowEvalError("flow 4 approve action did not persist")
        if rejected_row.get("review_status") != "rejected":
            raise RealFlowEvalError("flow 4 reject action did not persist")
        editable_event = edited_context.get("editable_event") if isinstance(edited_context.get("editable_event"), dict) else {}
        edited_name_value = editable_event.get("event_name")
        if edited_row.get("review_status") != "approved" or edited_name_value != edited_name:
            raise RealFlowEvalError("flow 4 proposal edit + approve did not persist")
        log_api_event(run_dir, FLOWS[3].flow_id, "review_actions_applied", {"approved": approved_row["id"], "rejected": rejected_row["id"], "edited": edited_row["id"]})
        results.append(
          FlowResult(
              flow_id=FLOWS[3].flow_id,
              title=FLOWS[3].title,
              status="passed",
              browser_checks_passed=bool(browser_four.get("passed")),
              api_checks_passed=True,
              user_visible_outcome="The user approved one change, rejected one change, and edited then approved another through the review UI.",
              artifacts={
                  "browser": browser_four,
                  "approved_change_id": int(review_targets["approve"]["id"]),
                  "rejected_change_id": int(review_targets["reject"]["id"]),
                  "edited_change_id": int(review_targets["edit"]["id"]),
              },
              notes=[
                  "Fake provider batches were advanced until enough pending changes existed.",
                  "Browser executed approve, reject, and proposal-edit actions.",
                  "Backend verified /changes and /changes/summary consequences after the UI actions.",
              ],
          )
      )

        current_flow_index = 4
        browser_five_create = run_browser_stage(
          flow_id=FLOWS[4].flow_id,
          stage="create_token",
          context_payload={
              "flow_id": FLOWS[4].flow_id,
              "stage": "create_token",
              "email": email,
              "password": password,
              "token_label": str(args.mcp_token_label),
          },
          frontend_base=frontend_base,
          run_dir=run_dir,
      )
        token_rows = replay.request_json_list(client, "GET", "/settings/mcp-tokens")
        if not token_rows:
            raise RealFlowEvalError("flow 5 expected at least one MCP token after browser creation")

        remaining_pending = [row for row in replay.request_json_list(client, "GET", "/changes?review_status=pending&limit=200") if str(row.get("change_type") or "") in {"created", "due_changed"}]
        if not remaining_pending:
            review_targets = ensure_review_targets(
              client=client,
              batches=batches,
              ics_source_id=int(ics_source["source_id"]),
              gmail_source_id=int(gmail_source["source_id"]),
              fake_provider_host=str(args.fake_provider_host),
              fake_provider_port=int(args.fake_provider_port),
              run_tag=run_dir.name,
              run_dir=run_dir,
          )
            remaining_pending = [row for row in replay.request_json_list(client, "GET", "/changes?review_status=pending&limit=200") if str(row.get("change_type") or "") in {"created", "due_changed"}]
        if not remaining_pending:
            raise RealFlowEvalError("flow 5 could not find a pending editable change for proposal_edit_commit")

        agent_change = remaining_pending[0]
        agent_proposal = replay.request_json(
            client,
            "POST",
            "/agent/proposals/change-edit-commit",
            json_payload={
                "change_id": int(agent_change["id"]),
                "patch": {"event_name": f"Agent Flow Edited {uuid.uuid4().hex[:4]}"},
            },
        )
        ticket = replay.request_json(
            client,
            "POST",
            "/agent/approval-tickets",
            json_payload={"proposal_id": int(agent_proposal["proposal_id"]), "channel": "web"},
        )
        confirmed = replay.request_json(
            client,
            "POST",
            f"/agent/approval-tickets/{str(ticket['ticket_id'])}/confirm",
            json_payload={},
        )
        recent_activity = replay.request_json(client, "GET", "/agent/activity/recent?limit=10")
        proposal_items = [item for item in recent_activity.get("items") or [] if item.get("proposal_id") == int(agent_proposal["proposal_id"])]
        ticket_items = [item for item in recent_activity.get("items") or [] if item.get("ticket_id") == str(ticket["ticket_id"])]
        if not proposal_items or not ticket_items:
            raise RealFlowEvalError("flow 5 expected proposal and ticket rows in recent agent activity")
        browser_five_verify = run_browser_stage(
          flow_id=FLOWS[4].flow_id,
          stage="verify_activity",
          context_payload={
              "flow_id": FLOWS[4].flow_id,
              "stage": "verify_activity",
              "email": email,
              "password": password,
              "expected_proposal_test_id": f"settings-agent-activity-item-proposal-{int(agent_proposal['proposal_id'])}",
              "expected_ticket_test_id": f"settings-agent-activity-item-ticket-{str(ticket['ticket_id'])}",
          },
          frontend_base=frontend_base,
          run_dir=run_dir,
      )
        log_api_event(
          run_dir,
          FLOWS[4].flow_id,
          "agent_action_executed",
          {
              "proposal_id": int(agent_proposal["proposal_id"]),
              "ticket_id": str(ticket["ticket_id"]),
              "result_kind": (confirmed.get("executed_result") or {}).get("kind"),
          },
      )
        results.append(
          FlowResult(
              flow_id=FLOWS[4].flow_id,
              title=FLOWS[4].title,
              status="passed",
              browser_checks_passed=bool(browser_five_create.get("passed")) and bool(browser_five_verify.get("passed")),
              api_checks_passed=True,
              user_visible_outcome="The user creates an MCP token in Settings and then sees recent agent proposal/ticket activity after a low-risk proposal edit commit executes.",
              artifacts={
                  "browser_create_token": browser_five_create,
                  "browser_verify_activity": browser_five_verify,
                  "proposal_id": int(agent_proposal["proposal_id"]),
                  "ticket_id": str(ticket["ticket_id"]),
              },
              notes=[
                  "Browser created the MCP token through the Settings surface.",
                  "Backend executed proposal -> approval ticket -> confirm using the public agent HTTP surface.",
                  "Browser verified the recent activity card now shows the proposal and ticket rows.",
              ],
          )
      )

        summary = build_summary(run_dir=run_dir, results=results)
        write_summary(run_dir=run_dir, summary=summary)
        return run_dir
    except Exception as exc:
        normalized_error = normalize_failure_message(exc)
        inferred_stage = infer_failure_stage(normalized_error)
        failure_details = _extract_structured_failure_details(normalized_error)
        if current_flow_index >= 0:
            failed_flow = FLOWS[current_flow_index]
            results.append(
                FlowResult(
                    flow_id=failed_flow.flow_id,
                    title=failed_flow.title,
                    status="failed",
                    browser_checks_passed=False,
                    api_checks_passed=False,
                    user_visible_outcome=f"Flow stopped before reaching the intended user-visible outcome: {normalized_error}",
                    notes=[
                        "The runner stopped in this flow before all browser and API checks completed.",
                        f"Failure: {normalized_error}",
                    ],
                )
            )
            for skipped in FLOWS[current_flow_index + 1 :]:
                results.append(
                    FlowResult(
                        flow_id=skipped.flow_id,
                        title=skipped.title,
                        status="skipped",
                        browser_checks_passed=False,
                        api_checks_passed=False,
                        user_visible_outcome="Skipped because an earlier flow failed.",
                        notes=["Runner stops subsequent flows after the first failure to preserve state consistency."],
                    )
                )
            summary = build_summary(run_dir=run_dir, results=results, failure_stage=inferred_stage)
            summary["failure"] = normalized_error
            if isinstance(failure_details, dict):
                summary["failure_details"] = failure_details
                for key, value in failure_details.items():
                    if key == "failure_stage":
                        continue
                    summary.setdefault(key, value)
            write_summary(run_dir=run_dir, summary=summary)
            print(run_dir)
        else:
            results.extend(build_skipped_results(reason="Skipped because real user flow setup failed.", start_index=0))
            summary = build_summary(
                run_dir=run_dir,
                results=results,
                failure_stage=inferred_stage,
            )
            summary["failure"] = normalized_error
            if isinstance(failure_details, dict):
                summary["failure_details"] = failure_details
                for key, value in failure_details.items():
                    if key == "failure_stage":
                        continue
                    summary.setdefault(key, value)
            write_summary(run_dir=run_dir, summary=summary)
            print(run_dir)
        raise RealFlowEvalError(normalized_error) from exc
    finally:
        if client is not None:
            client.close()
        if fake_provider_started and fake_provider_pid is not None:
            try:
                os.kill(fake_provider_pid, signal.SIGTERM)
            except OSError:
                pass


def build_summary(
    *,
    run_dir: Path,
    results: list[FlowResult],
    failure_stage: str | None = None,
    preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    overall_status = "passed" if all(result.status == "passed" for result in results) else "failed"
    passed_count = sum(1 for result in results if result.status == "passed")
    flow_count = len(results)
    return {
        "generated_at": datetime.now(replay.UTC).isoformat(),
        "overall_status": overall_status,
        "run_dir": str(run_dir),
        "failure_stage": failure_stage,
        "preflight": preflight,
        "flow_count": flow_count,
        "passed_flow_count": passed_count,
        "goal_completion_rate": round(passed_count / flow_count, 4) if flow_count > 0 else None,
        "flows": [asdict(result) for result in results],
    }


def infer_failure_stage(message: str) -> str | None:
    details = _extract_structured_failure_details(message)
    if isinstance(details, dict):
        stage = details.get("failure_stage")
        if isinstance(stage, str) and stage.strip():
            return stage.strip()
    normalized = str(message or "").lower()
    if "frontend login is not reachable" in normalized:
        return "frontend_not_reachable"
    if "backend health is not reachable" in normalized or "backend health returned" in normalized:
        return "backend_not_reachable"
    if "llm_queue" in normalized or "queued for extraction" in normalized or "probe sync stalled" in normalized:
        return "backend_worker_pipeline_stalled"
    return None


def write_summary(*, run_dir: Path, summary: dict[str, Any]) -> None:
    (run_dir / SUMMARY_JSON).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_dir / SUMMARY_MD).write_text(build_summary_markdown(summary=summary), encoding="utf-8")


def ensure_http_ready(base_url: str, path_suffix: str, label: str) -> None:
    try:
        response = httpx.get(f"{base_url.rstrip('/')}{path_suffix}", timeout=5.0, follow_redirects=True)
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RealFlowEvalError(f"{label} is not reachable at {base_url}{path_suffix}: {exc}") from exc
    if response.status_code >= 500:
        raise RealFlowEvalError(f"{label} returned {response.status_code} at {base_url}{path_suffix}")


def run_browser_stage(
    *,
    flow_id: str,
    stage: str,
    context_payload: dict[str, Any],
    frontend_base: str,
    run_dir: Path,
) -> dict[str, Any]:
    context_path = run_dir / "per_flow" / f"{flow_id}__{stage}.context.json"
    result_path = run_dir / "per_flow" / f"{flow_id}__{stage}.browser.json"
    context_path.write_text(json.dumps(context_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log_path = run_dir / "per_flow" / f"{flow_id}__{stage}.browser.log"
    env = os.environ.copy()
    env["REAL_FLOW_RUN_DIR"] = str(run_dir)
    env["REAL_FLOW_SELECTED_FLOW"] = flow_id
    env["REAL_FLOW_SELECTED_STAGE"] = stage
    env["REAL_FLOW_CONTEXT_PATH"] = str(context_path)
    env["REAL_FLOW_FRONTEND_BASE"] = frontend_base
    completed = subprocess.run(
        ["npm", "run", "e2e:real-flows", "--", "--grep", flow_id],
        cwd=str(FRONTEND_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    log_path.write_text((completed.stdout or "") + (("\n" + completed.stderr) if completed.stderr else ""), encoding="utf-8")
    if completed.returncode != 0:
        raise RealFlowEvalError(f"browser flow failed flow_id={flow_id} stage={stage}: {log_path}")
    if not result_path.exists():
        raise RealFlowEvalError(f"browser flow did not write result payload: {result_path}")
    return json.loads(result_path.read_text(encoding="utf-8"))


def log_api_event(run_dir: Path, flow_id: str, event: str, payload: dict[str, Any]) -> None:
    path_value = run_dir / "api_events.jsonl"
    row = {
        "occurred_at": datetime.now(replay.UTC).isoformat(),
        "flow_id": flow_id,
        "event": event,
        "payload": payload,
    }
    path_value.write_text(path_value.read_text(encoding="utf-8") + json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")


def ensure_gmail_source(
    *,
    client: httpx.Client,
    monitoring_config: dict[str, str],
    fake_provider_host: str,
    fake_provider_port: int,
) -> dict[str, Any]:
    rows = replay.request_json_list(client, "GET", "/sources?status=all")
    for row in rows:
        if str(row.get("provider") or "") == "gmail" and bool(row.get("is_active", True)):
            return row
    return replay.create_source(
        client,
        payload={
            "source_kind": "email",
            "provider": "gmail",
            "display_name": "Real Flow Gmail Source",
            "config": {"label_id": "INBOX", **monitoring_config},
            "secrets": {
                "access_token": "fake-access-token",
                "account_email": "fake.student@example.edu",
            },
        },
    )


def ensure_review_targets(
    *,
    client: httpx.Client,
    batches: list[replay.BatchSpec],
    ics_source_id: int,
    gmail_source_id: int,
    fake_provider_host: str,
    fake_provider_port: int,
    run_tag: str,
    run_dir: Path,
) -> dict[str, dict[str, Any]]:
    targets = _select_pending_review_targets(client)
    if targets is not None:
        return targets

    candidate_batches = batches[1:]
    for provider, source_id in (("gmail", gmail_source_id), ("ics", ics_source_id)):
        for batch in candidate_batches:
            replay.set_fake_provider_batch(
                host=fake_provider_host,
                port=fake_provider_port,
                semester=batch.semester,
                batch=batch.batch,
                run_tag=run_tag,
            )
            trace_id = f"real-flow-{provider}-{batch.global_batch}-{source_id}-{uuid.uuid4().hex[:6]}"
            request_id = replay.create_sync_request(client, source_id=source_id, trace_id=trace_id)
            sync_payload = wait_for_review_prep_source_sync(
                client,
                request_id=request_id,
                source_id=source_id,
                provider=provider,
            )
            log_api_event(
                run_dir,
                FLOWS[3].flow_id,
                "review_prep_sync_applied",
                {
                    "provider": provider,
                    "source_id": source_id,
                    "request_id": request_id,
                    "status": sync_payload["status"],
                    "global_batch": batch.global_batch,
                },
            )
            targets = _select_pending_review_targets(client)
            if targets is not None:
                return targets

    raise RealFlowEvalError("could not generate enough pending changes for flow 4")


def _select_pending_review_targets(client: httpx.Client) -> dict[str, dict[str, Any]] | None:
    pending = replay.request_json_list(client, "GET", "/changes?review_status=pending&limit=200")
    try:
        return select_review_targets(pending)
    except RealFlowEvalError:
        return None


if __name__ == "__main__":
    try:
        main()
    except RealFlowEvalError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
