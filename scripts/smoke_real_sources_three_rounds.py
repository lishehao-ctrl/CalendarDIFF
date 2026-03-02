#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


@dataclass(frozen=True)
class RoundProfile:
    round_id: int
    difficulty: str
    alias_profile: str


ROUND_PROFILES = [
    RoundProfile(round_id=1, difficulty="simple", alias_profile="canonical"),
    RoundProfile(round_id=2, difficulty="medium", alias_profile="updated-wording"),
    RoundProfile(round_id=3, difficulty="alias-heavy", alias_profile="multi-alias-same-subject"),
]


class SmokeFailure(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run three-round real-source smoke (fake ICS + fake Gmail + online LLM).")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000", help="Base URL of CalendarDIFF API.")
    parser.add_argument("--api-key", default=os.getenv("APP_API_KEY", ""), help="API key. Defaults to APP_API_KEY.")
    parser.add_argument(
        "--report",
        default="data/synthetic/v2_ddlchange_160/qa/real_source_smoke_report.json",
        help="Report output path.",
    )
    parser.add_argument("--fake-provider-host", default="127.0.0.1", help="Fake source provider host.")
    parser.add_argument("--fake-provider-port", type=int, default=8765, help="Fake source provider port.")
    parser.add_argument("--sync-timeout-seconds", type=float, default=120.0, help="Timeout for each sync request.")
    parser.add_argument("--poll-interval-seconds", type=float, default=1.5, help="Polling interval for sync status.")
    parser.add_argument(
        "--cleanup-sources",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Delete created input sources at the end.",
    )
    parser.add_argument(
        "--notify-email",
        default="smoke.runner@example.com",
        help="Notify email used when onboarding is missing.",
    )
    return parser.parse_args()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _hash_base_url(base_url: str) -> str:
    return hashlib.sha256(base_url.encode("utf-8")).hexdigest()[:16]


def _require_llm_env() -> tuple[str, str]:
    model = (os.getenv("INGESTION_LLM_MODEL") or "").strip()
    base_url = (os.getenv("INGESTION_LLM_BASE_URL") or "").strip()
    api_key = (os.getenv("INGESTION_LLM_API_KEY") or "").strip()

    missing: list[str] = []
    if not model:
        missing.append("INGESTION_LLM_MODEL")
    if not base_url:
        missing.append("INGESTION_LLM_BASE_URL")
    if not api_key:
        missing.append("INGESTION_LLM_API_KEY")
    if missing:
        raise SmokeFailure(f"missing llm env config: {missing}")
    return model, base_url


def _request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    json_payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    response = client.request(method, path, json=json_payload, headers=headers, timeout=timeout)
    if response.status_code >= 400:
        raise SmokeFailure(f"{method} {path} failed status={response.status_code} body={response.text[:800]}")
    try:
        payload = response.json()
    except Exception as exc:  # pragma: no cover - defensive path
        raise SmokeFailure(f"{method} {path} returned non-json body") from exc
    if not isinstance(payload, dict):
        raise SmokeFailure(f"{method} {path} returned non-object json")
    return payload


def _request_json_list(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    response = client.request(method, path, headers=headers, timeout=timeout)
    if response.status_code >= 400:
        raise SmokeFailure(f"{method} {path} failed status={response.status_code} body={response.text[:800]}")
    try:
        payload = response.json()
    except Exception as exc:  # pragma: no cover - defensive path
        raise SmokeFailure(f"{method} {path} returned non-json body") from exc
    if not isinstance(payload, list):
        raise SmokeFailure(f"{method} {path} returned non-list json")
    output: list[dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict):
            output.append(item)
    return output


def _wait_sync_success(
    client: httpx.Client,
    *,
    request_id: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status_payload = _request_json(client, "GET", f"/v2/sync-requests/{request_id}")
        status = str(status_payload.get("status") or "")
        applied = bool(status_payload.get("applied"))

        if status == "FAILED":
            raise SmokeFailure(
                "sync request failed "
                f"request_id={request_id} code={status_payload.get('error_code')} "
                f"message={status_payload.get('error_message')}"
            )
        if status == "SUCCEEDED" and applied:
            return status_payload

        time.sleep(max(0.1, poll_interval_seconds))

    raise SmokeFailure(f"sync request timed out waiting for SUCCEEDED+applied request_id={request_id}")


def _extract_source_ids(change_row: dict[str, Any]) -> set[int]:
    raw_sources = change_row.get("proposal_sources")
    if not isinstance(raw_sources, list):
        return set()
    ids: set[int] = set()
    for item in raw_sources:
        if isinstance(item, dict) and isinstance(item.get("source_id"), int):
            ids.add(int(item["source_id"]))
    return ids


def _assert(checks: list[dict[str, Any]], *, name: str, passed: bool, detail: str) -> None:
    checks.append({"name": name, "passed": passed, "detail": detail})


def _poll_fake_provider_ready(client: httpx.Client, *, timeout_seconds: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            payload = _request_json(client, "GET", "/__admin/state", timeout=2.0)
            if "round" in payload:
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise SmokeFailure("fake source provider did not become ready in time")


def _set_fake_round(client: httpx.Client, *, round_id: int, run_tag: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"round": round_id}
    if run_tag:
        body["run_tag"] = run_tag
    payload = _request_json(client, "POST", "/__admin/round", json_payload=body, timeout=5.0)
    if int(payload.get("round", -1)) != round_id:
        raise SmokeFailure(f"failed to set fake provider round to {round_id}")
    return payload


def _build_round_result(profile: RoundProfile) -> dict[str, Any]:
    return {
        "round_id": profile.round_id,
        "difficulty": profile.difficulty,
        "alias_profile": profile.alias_profile,
        "ics_request_id": None,
        "gmail_request_id": None,
        "ics_status": None,
        "gmail_status": None,
        "pending_change_ids": [],
        "approved_change_ids": [],
        "timeline_count_after": 0,
        "feed_count_after": 0,
        "merge_verified": False,
        "single_pending_enforced": False,
        "merge_required_sources_present": False,
        "same_topic_uid_enforced": False,
        "topic_uid": None,
        "errors": [],
    }


def main() -> int:
    args = parse_args()
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    run_id = f"real-source-smoke-{hashlib.sha256(str(time.time()).encode('utf-8')).hexdigest()[:12]}"
    run_tag = f"smk{run_id[-6:]}"
    started_at = _utc_now_iso()

    report: dict[str, Any] = {
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": None,
        "api_base": args.api_base,
        "llm_model": None,
        "llm_base_url_hash": None,
        "merge_gate_mode": "strict_same_topic",
        "global_topic_uid": None,
        "passed": False,
        "fatal_errors": [],
        "source": {
            "calendar_source_id": None,
            "gmail_source_id": None,
            "gmail_baseline_request_id": None,
        },
        "rounds": [_build_round_result(profile) for profile in ROUND_PROFILES],
        "provider_counters": {
            "ics_fetch_count": 0,
            "gmail_profile_count": 0,
            "gmail_history_count": 0,
            "gmail_message_count": 0,
        },
        "assertion_pass_rate": 0.0,
        "failed_assertions": [],
        "assertions": [],
    }

    fake_process: subprocess.Popen[str] | None = None
    fake_client: httpx.Client | None = None
    created_source_ids: list[int] = []

    try:
        model, llm_base_url = _require_llm_env()
        report["llm_model"] = model
        report["llm_base_url_hash"] = _hash_base_url(llm_base_url)

        if not args.api_key:
            raise SmokeFailure("missing api key: pass --api-key or set APP_API_KEY")

        api_headers = {"X-API-Key": args.api_key}
        api_client = httpx.Client(base_url=args.api_base.rstrip("/"), headers=api_headers)
        try:
            health = api_client.get("/health", timeout=8.0)
            if health.status_code != 200:
                raise SmokeFailure(f"health check failed status={health.status_code} body={health.text[:400]}")

            status_payload = _request_json(api_client, "GET", "/v2/onboarding/status")
            stage = str(status_payload.get("stage") or "")
            if stage == "needs_user":
                _request_json(
                    api_client,
                    "POST",
                    "/v2/onboarding/registrations",
                    json_payload={"notify_email": args.notify_email},
                )

            fake_cmd = [
                sys.executable,
                "scripts/fake_source_provider.py",
                "--host",
                args.fake_provider_host,
                "--port",
                str(args.fake_provider_port),
            ]
            fake_process = subprocess.Popen(
                fake_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            fake_client = httpx.Client(base_url=f"http://{args.fake_provider_host}:{args.fake_provider_port}")
            _poll_fake_provider_ready(fake_client)

            ics_source = _request_json(
                api_client,
                "POST",
                "/v2/input-sources",
                json_payload={
                    "source_kind": "calendar",
                    "provider": "ics",
                    "source_key": f"{run_id}-ics",
                    "display_name": "Smoke Calendar Source",
                    "poll_interval_seconds": 900,
                    "config": {},
                    "secrets": {"url": f"http://{args.fake_provider_host}:{args.fake_provider_port}/ics/calendar.ics"},
                },
            )
            gmail_source = _request_json(
                api_client,
                "POST",
                "/v2/input-sources",
                json_payload={
                    "source_kind": "email",
                    "provider": "gmail",
                    "source_key": f"{run_id}-gmail",
                    "display_name": "Smoke Gmail Source",
                    "poll_interval_seconds": 900,
                    "config": {"label_id": "INBOX"},
                    "secrets": {
                        "access_token": "fake-access-token",
                        "account_email": "fake.student@example.edu",
                    },
                },
            )
            calendar_source_id = int(ics_source["source_id"])
            gmail_source_id = int(gmail_source["source_id"])
            created_source_ids.extend([calendar_source_id, gmail_source_id])
            report["source"]["calendar_source_id"] = calendar_source_id
            report["source"]["gmail_source_id"] = gmail_source_id

            _set_fake_round(fake_client, round_id=0, run_tag=run_tag)
            baseline_req = _request_json(
                api_client,
                "POST",
                "/v2/sync-requests",
                json_payload={"source_id": gmail_source_id, "metadata": {"kind": "smoke-baseline"}},
                headers={"Idempotency-Key": f"{run_id}:baseline:gmail"},
            )
            baseline_request_id = str(baseline_req["request_id"])
            report["source"]["gmail_baseline_request_id"] = baseline_request_id
            baseline_status = _wait_sync_success(
                api_client,
                request_id=baseline_request_id,
                timeout_seconds=args.sync_timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
            )
            connector_status = str((baseline_status.get("connector_result") or {}).get("status") or "")
            _assert(
                report["assertions"],
                name="gmail_baseline_no_change",
                passed=connector_status == "NO_CHANGE",
                detail=f"connector_status={connector_status}",
            )

            approved_change_ids: set[int] = set()
            global_topic_uid: str | None = None

            for idx, profile in enumerate(ROUND_PROFILES):
                round_report = report["rounds"][idx]
                _set_fake_round(fake_client, round_id=profile.round_id)

                ics_req = _request_json(
                    api_client,
                    "POST",
                    "/v2/sync-requests",
                    json_payload={
                        "source_id": calendar_source_id,
                        "metadata": {"kind": "smoke-round", "round": profile.round_id, "source": "ics"},
                    },
                    headers={"Idempotency-Key": f"{run_id}:round:{profile.round_id}:ics"},
                )
                round_report["ics_request_id"] = str(ics_req["request_id"])
                ics_status = _wait_sync_success(
                    api_client,
                    request_id=round_report["ics_request_id"],
                    timeout_seconds=args.sync_timeout_seconds,
                    poll_interval_seconds=args.poll_interval_seconds,
                )
                round_report["ics_status"] = str((ics_status.get("connector_result") or {}).get("status") or "")

                gmail_req = _request_json(
                    api_client,
                    "POST",
                    "/v2/sync-requests",
                    json_payload={
                        "source_id": gmail_source_id,
                        "metadata": {"kind": "smoke-round", "round": profile.round_id, "source": "gmail"},
                    },
                    headers={"Idempotency-Key": f"{run_id}:round:{profile.round_id}:gmail"},
                )
                round_report["gmail_request_id"] = str(gmail_req["request_id"])
                gmail_status = _wait_sync_success(
                    api_client,
                    request_id=round_report["gmail_request_id"],
                    timeout_seconds=args.sync_timeout_seconds,
                    poll_interval_seconds=args.poll_interval_seconds,
                )
                round_report["gmail_status"] = str((gmail_status.get("connector_result") or {}).get("status") or "")

                required_sources = {calendar_source_id, gmail_source_id}
                pending_rows = _request_json_list(
                    api_client,
                    "GET",
                    "/v2/review-items/changes?review_status=pending&limit=200",
                )
                round_pending_rows = []
                for row in pending_rows:
                    change_id = row.get("id")
                    if not isinstance(change_id, int) or change_id in approved_change_ids:
                        continue
                    source_ids = _extract_source_ids(row)
                    if source_ids.intersection(required_sources):
                        round_pending_rows.append(row)

                if not round_pending_rows:
                    round_report["pending_change_ids"] = []
                    round_report["single_pending_enforced"] = False
                    round_report["merge_required_sources_present"] = False
                    round_report["merge_verified"] = False
                    round_report["same_topic_uid_enforced"] = False
                    round_report["errors"].append("single_pending_enforced_failed")
                    _assert(
                        report["assertions"],
                        name=f"round_{profile.round_id}_single_pending_enforced",
                        passed=False,
                        detail="pending_ids=[]",
                    )
                    raise SmokeFailure(f"round {profile.round_id}: no new pending review items detected")

                round_report["pending_change_ids"] = [
                    int(row["id"]) for row in round_pending_rows if isinstance(row.get("id"), int)
                ]
                single_pending_enforced = len(round_pending_rows) == 1
                round_report["single_pending_enforced"] = single_pending_enforced
                _assert(
                    report["assertions"],
                    name=f"round_{profile.round_id}_single_pending_enforced",
                    passed=single_pending_enforced,
                    detail=f"pending_ids={sorted(round_report['pending_change_ids'])}",
                )
                if not single_pending_enforced:
                    round_report["errors"].append("single_pending_enforced_failed")
                    raise SmokeFailure(
                        f"round {profile.round_id}: strict gate failed single_pending_enforced "
                        f"pending_ids={sorted(round_report['pending_change_ids'])}"
                    )

                candidate_row = round_pending_rows[0]
                candidate_sources = _extract_source_ids(candidate_row)
                merge_required_sources_present = required_sources.issubset(candidate_sources)
                round_report["merge_required_sources_present"] = merge_required_sources_present
                round_report["merge_verified"] = merge_required_sources_present
                _assert(
                    report["assertions"],
                    name=f"round_{profile.round_id}_merge_required_sources_present",
                    passed=merge_required_sources_present,
                    detail=f"candidate_sources={sorted(candidate_sources)}",
                )
                if not merge_required_sources_present:
                    round_report["errors"].append("cross_source_merge_not_verified")
                    raise SmokeFailure(
                        f"round {profile.round_id}: strict gate failed merge_required_sources_present "
                        f"sources={sorted(candidate_sources)}"
                    )

                topic_uid_raw = candidate_row.get("event_uid")
                topic_uid = str(topic_uid_raw) if isinstance(topic_uid_raw, str) and topic_uid_raw.strip() else ""
                if not topic_uid:
                    raise SmokeFailure(f"round {profile.round_id}: strict gate failed missing event_uid")
                round_report["topic_uid"] = topic_uid

                if global_topic_uid is None:
                    global_topic_uid = topic_uid
                    report["global_topic_uid"] = global_topic_uid
                    same_topic_uid_enforced = True
                else:
                    same_topic_uid_enforced = topic_uid == global_topic_uid

                round_report["same_topic_uid_enforced"] = same_topic_uid_enforced
                _assert(
                    report["assertions"],
                    name=f"round_{profile.round_id}_same_topic_uid_enforced",
                    passed=same_topic_uid_enforced,
                    detail=f"global_topic_uid={global_topic_uid} candidate_topic_uid={topic_uid}",
                )
                if not same_topic_uid_enforced:
                    round_report["errors"].append("same_topic_uid_enforced_failed")
                    raise SmokeFailure(
                        f"round {profile.round_id}: strict gate failed same_topic_uid_enforced "
                        f"global_topic_uid={global_topic_uid} candidate_topic_uid={topic_uid}"
                    )

                round_approved_ids: list[int] = []
                change_id = int(candidate_row["id"])
                decision = _request_json(
                    api_client,
                    "POST",
                    f"/v2/review-items/changes/{change_id}/decisions",
                    json_payload={
                        "decision": "approve",
                        "note": f"real-source-smoke round {profile.round_id}",
                    },
                )
                if str(decision.get("review_status") or "") != "approved":
                    raise SmokeFailure(f"round {profile.round_id}: approve failed for change_id={change_id}")
                approved_change_ids.add(change_id)
                round_approved_ids.append(change_id)

                round_report["approved_change_ids"] = sorted(round_approved_ids)

                pending_after = _request_json_list(
                    api_client,
                    "GET",
                    "/v2/review-items/changes?review_status=pending&limit=200",
                )
                pending_after_ids = {
                    int(item["id"])
                    for item in pending_after
                    if isinstance(item.get("id"), int)
                    and _extract_source_ids(item).intersection(required_sources)
                }
                round_pending_left = sorted(pending_after_ids.intersection(set(round_report["pending_change_ids"])))
                _assert(
                    report["assertions"],
                    name=f"round_{profile.round_id}_pending_cleared",
                    passed=not round_pending_left,
                    detail=f"remaining={round_pending_left}",
                )

                timeline_rows = _request_json_list(
                    api_client,
                    "GET",
                    "/v2/timeline-events?limit=200",
                )
                round_report["timeline_count_after"] = len(timeline_rows)
                if not timeline_rows:
                    raise SmokeFailure(f"round {profile.round_id}: timeline is empty after approve")

                round_event_uids = {topic_uid}
                timeline_uids = {str(item["uid"]) for item in timeline_rows if isinstance(item.get("uid"), str)}
                _assert(
                    report["assertions"],
                    name=f"round_{profile.round_id}_timeline_contains_round_uids",
                    passed=round_event_uids.issubset(timeline_uids),
                    detail=f"round_event_uids={sorted(round_event_uids)}",
                )

                feed_rows = _request_json_list(
                    api_client,
                    "GET",
                    "/v2/change-events?review_status=approved&limit=200",
                )
                round_report["feed_count_after"] = len(feed_rows)
                approved_feed_ids = {
                    int(item["id"])
                    for item in feed_rows
                    if isinstance(item.get("id"), int)
                }
                _assert(
                    report["assertions"],
                    name=f"round_{profile.round_id}_approved_visible_in_feed",
                    passed=set(round_approved_ids).issubset(approved_feed_ids),
                    detail=f"approved_ids={sorted(round_approved_ids)}",
                )

            provider_state = _request_json(fake_client, "GET", "/__admin/state")
            counters = provider_state.get("counters") if isinstance(provider_state.get("counters"), dict) else {}
            for key in report["provider_counters"].keys():
                value = counters.get(key)
                report["provider_counters"][key] = int(value) if isinstance(value, int) else 0

            for round_report in report["rounds"]:
                _assert(
                    report["assertions"],
                    name=f"round_{round_report['round_id']}_ics_status",
                    passed=round_report["ics_status"] in {"CHANGED", "NO_CHANGE"},
                    detail=f"status={round_report['ics_status']}",
                )
                _assert(
                    report["assertions"],
                    name=f"round_{round_report['round_id']}_gmail_status",
                    passed=round_report["gmail_status"] in {"CHANGED", "NO_CHANGE"},
                    detail=f"status={round_report['gmail_status']}",
                )

        finally:
            api_client.close()

    except Exception as exc:
        report["fatal_errors"].append(str(exc))
        report["passed"] = False
    finally:
        if args.cleanup_sources and created_source_ids:
            try:
                headers = {"X-API-Key": args.api_key} if args.api_key else {}
                with httpx.Client(base_url=args.api_base.rstrip("/"), headers=headers) as cleanup_client:
                    for source_id in created_source_ids:
                        cleanup_client.delete(f"/v2/input-sources/{source_id}", timeout=8.0)
            except Exception as exc:  # pragma: no cover - cleanup is best effort
                report["fatal_errors"].append(f"cleanup_failed: {exc}")

        if fake_client is not None:
            try:
                fake_client.close()
            except Exception:
                pass

        if fake_process is not None:
            fake_process.terminate()
            try:
                fake_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                fake_process.kill()
                fake_process.wait(timeout=5)

        passed_checks = sum(1 for row in report["assertions"] if row.get("passed") is True)
        total_checks = len(report["assertions"])
        report["assertion_pass_rate"] = round((passed_checks / total_checks) if total_checks else 0.0, 4)
        report["failed_assertions"] = [row for row in report["assertions"] if row.get("passed") is not True]
        report["passed"] = not report["fatal_errors"] and not report["failed_assertions"]
        report["finished_at"] = _utc_now_iso()
        report_path.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "run_id": report["run_id"],
        "passed": report["passed"],
        "failed_assertions": len(report["failed_assertions"]),
        "fatal_errors": report["fatal_errors"],
        "report": str(report_path),
    }, ensure_ascii=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
