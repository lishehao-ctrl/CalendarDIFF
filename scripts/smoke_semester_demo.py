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
from pathlib import Path
from typing import Any

import httpx

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.semester_demo_scenarios import ScenarioManifest, build_scenario_manifest, write_scenario_manifest


@dataclass(frozen=True)
class BatchPointer:
    semester: int
    batch: int
    global_batch: int


class DemoFailure(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run 3-semester high-fidelity ICS/Gmail demo with mixed review decisions and JSONL notify sink."
    )
    parser.add_argument("--input-api-base", required=True, help="Input-service API base URL.")
    parser.add_argument("--review-api-base", required=True, help="Review-service API base URL.")
    parser.add_argument("--ingest-api-base", default=None, help="Optional ingest-service API base URL.")
    parser.add_argument("--notify-api-base", default=None, help="Notification-service API base URL.")
    parser.add_argument("--llm-api-base", default=None, help="Optional llm-service API base URL.")
    parser.add_argument("--api-key", default=os.getenv("APP_API_KEY", ""), help="Public API key.")
    parser.add_argument(
        "--ops-token",
        default=os.getenv("INTERNAL_SERVICE_TOKEN_OPS", ""),
        help="Ops internal service token for status probes.",
    )
    parser.add_argument("--semesters", type=int, default=3)
    parser.add_argument("--batches-per-semester", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--review-policy", default="mixed", choices=["mixed"])
    parser.add_argument("--seed", type=int, default=20260305)
    parser.add_argument(
        "--report",
        default="data/synthetic/semester_demo/qa/semester_demo_report.json",
        help="Report output path.",
    )
    parser.add_argument(
        "--notification-jsonl",
        default=os.getenv("NOTIFY_JSONL_PATH", "data/smoke/notify_sink.jsonl"),
        help="Expected JSONL notification sink path.",
    )
    parser.add_argument("--fake-provider-host", default="127.0.0.1")
    parser.add_argument("--fake-provider-port", type=int, default=8765)
    parser.add_argument("--sync-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=1.5)
    parser.add_argument(
        "--cleanup-sources",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Delete created input sources at the end.",
    )
    parser.add_argument(
        "--notify-email",
        default="semester.demo.runner@example.com",
        help="Notify email used when onboarding is missing.",
    )
    return parser.parse_args()


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _require_online_llm_env() -> tuple[str, str]:
    model = (os.getenv("INGESTION_LLM_MODEL") or os.getenv("APP_LLM_OPENAI_MODEL") or "").strip()
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
        raise DemoFailure(f"missing online llm env config: {missing}")
    return model, base_url


def _ensure_authenticated_session(client: httpx.Client, *, notify_email: str, password: str) -> None:
    register_response = client.post(
        "/auth/register",
        json={"notify_email": notify_email, "password": password},
        timeout=10.0,
    )
    if register_response.status_code == 201:
        return
    if register_response.status_code != 409:
        raise DemoFailure(f"auth register failed status={register_response.status_code} body={register_response.text[:800]}")

    login_response = client.post(
        "/auth/login",
        json={"notify_email": notify_email, "password": password},
        timeout=10.0,
    )
    if login_response.status_code != 200:
        raise DemoFailure(f"auth login failed status={login_response.status_code} body={login_response.text[:800]}")


def _request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    json_payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    response = client.request(method, path, json=json_payload, headers=headers, timeout=timeout)
    if response.status_code >= 400:
        raise DemoFailure(f"{method} {path} failed status={response.status_code} body={response.text[:800]}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise DemoFailure(f"{method} {path} returned non-object json")
    return payload


def _request_json_list(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    response = client.request(method, path, headers=headers, timeout=timeout)
    if response.status_code >= 400:
        raise DemoFailure(f"{method} {path} failed status={response.status_code} body={response.text[:800]}")
    payload = response.json()
    if not isinstance(payload, list):
        raise DemoFailure(f"{method} {path} returned non-list json")
    return [row for row in payload if isinstance(row, dict)]


def _request_paginated_list(client: httpx.Client, *, path: str, page_size: int = 200) -> list[dict[str, Any]]:
    offset = 0
    out: list[dict[str, Any]] = []
    while True:
        separator = "&" if "?" in path else "?"
        page_path = f"{path}{separator}limit={page_size}&offset={offset}"
        rows = _request_json_list(client, "GET", page_path)
        out.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return out


def _wait_sync_success(
    client: httpx.Client,
    *,
    request_id: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        payload = _request_json(client, "GET", f"/sync-requests/{request_id}")
        status = str(payload.get("status") or "")
        applied = bool(payload.get("applied"))
        if status == "FAILED":
            raise DemoFailure(
                "sync request failed "
                f"request_id={request_id} code={payload.get('error_code')} "
                f"message={payload.get('error_message')}"
            )
        if status == "SUCCEEDED" and applied:
            return payload
        time.sleep(max(0.2, poll_interval_seconds))
    raise DemoFailure(f"sync request timed out request_id={request_id}")


def _poll_fake_provider_ready(client: httpx.Client, *, timeout_seconds: float = 20.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            payload = _request_json(client, "GET", "/__admin/state", timeout=2.0)
            if isinstance(payload.get("counters"), dict):
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise DemoFailure("fake source provider did not become ready")


def _set_fake_batch(
    client: httpx.Client,
    *,
    semester: int,
    batch: int,
    run_tag: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"semester": semester, "batch": batch}
    if run_tag:
        body["run_tag"] = run_tag
    payload = _request_json(client, "POST", "/__admin/semester-batch", json_payload=body)
    if int(payload.get("semester", -1)) != semester or int(payload.get("batch", -1)) != batch:
        raise DemoFailure(f"failed to set fake provider semester/batch to {semester}/{batch}")
    return payload


def _extract_source_ids(change_row: dict[str, Any]) -> set[int]:
    raw = change_row.get("proposal_sources")
    if not isinstance(raw, list):
        return set()
    out: set[int] = set()
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("source_id"), int):
            out.add(int(item["source_id"]))
    return out


def _mixed_decision_for_change(*, seed: int, change_id: int) -> str:
    digest = hashlib.sha256(f"{seed}:{change_id}".encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) / 0xFFFFFFFF
    if bucket < 0.80:
        return "approve"
    if bucket < 0.95:
        return "reject"
    return "pending"


def _count_jsonl_rows(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _assert(assertions: list[dict[str, Any]], *, name: str, passed: bool, detail: str) -> None:
    assertions.append({"name": name, "passed": passed, "detail": detail})


def main() -> int:
    args = parse_args()
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    notification_jsonl_path = Path(args.notification_jsonl)
    notification_rows_before = _count_jsonl_rows(notification_jsonl_path)

    run_id = f"semester-demo-{_hash_text(str(time.time()))}"
    run_tag = f"sem{run_id[-6:]}"
    started_at = _utc_now_iso()

    report: dict[str, Any] = {
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": None,
        "passed": False,
        "fatal_errors": [],
        "assertions": [],
        "failed_assertions": [],
        "llm_mode": "online",
        "llm_model": None,
        "llm_base_url_hash": None,
        "input_api_base": args.input_api_base,
        "review_api_base": args.review_api_base,
        "notify_api_base": args.notify_api_base,
        "ingest_api_base": args.ingest_api_base,
        "seed": args.seed,
        "review_policy": args.review_policy,
        "scenario_manifest_path": str(report_path.with_name(f"{run_id}_scenario_manifest.json")),
        "source": {"calendar_source_id": None, "gmail_source_id": None, "gmail_baseline_request_id": None},
        "semesters": [],
        "suffix_assertions": {},
        "provider_state": {},
        "notification_sink": {
            "path": str(notification_jsonl_path),
            "rows_before": notification_rows_before,
            "rows_after": None,
            "rows_delta": None,
        },
        "notification_flush": {
            "batches_flushed": 0,
            "enqueued_notifications": 0,
            "processed_slots": 0,
            "sent_count": 0,
            "failed_count": 0,
        },
    }

    fake_process: subprocess.Popen[str] | None = None
    fake_client: httpx.Client | None = None
    input_client: httpx.Client | None = None
    review_client: httpx.Client | None = None
    created_source_ids: list[int] = []

    try:
        model, llm_base_url = _require_online_llm_env()
        report["llm_model"] = model
        report["llm_base_url_hash"] = _hash_text(llm_base_url)

        if not args.api_key:
            raise DemoFailure("missing APP_API_KEY / --api-key")
        if not args.ops_token:
            raise DemoFailure("missing INTERNAL_SERVICE_TOKEN_OPS / --ops-token")
        if not args.notify_api_base:
            raise DemoFailure("notify_api_base is required for semester demo notification flush")

        manifest = build_scenario_manifest(
            semesters=args.semesters,
            batches_per_semester=args.batches_per_semester,
            batch_size=args.batch_size,
            seed=args.seed,
        )
        manifest_path = Path(report["scenario_manifest_path"])
        write_scenario_manifest(manifest_path, manifest)

        suffix_expectations = _build_suffix_expectations(manifest=manifest)
        report["suffix_assertions"] = {
            key: {"expected": value, "passed": False, "detail": "not evaluated"}
            for key, value in suffix_expectations.items()
        }
        report["semesters"] = [
            {
                "semester": semester_plan.semester,
                "courses": list(semester_plan.courses),
                "ics_target_count": args.batches_per_semester * args.batch_size,
                "gmail_target_count": args.batches_per_semester * args.batch_size,
                "batches": [],
                "review_totals": {"approved": 0, "rejected": 0, "pending": 0},
                "notification_flush": {
                    "batches_flushed": 0,
                    "enqueued_notifications": 0,
                    "processed_slots": 0,
                    "sent_count": 0,
                    "failed_count": 0,
                },
            }
            for semester_plan in manifest.plans
        ]

        api_headers = {"X-API-Key": args.api_key}
        input_client = httpx.Client(base_url=args.input_api_base.rstrip("/"), headers=api_headers)
        review_client = httpx.Client(base_url=args.review_api_base.rstrip("/"), headers=api_headers)

        _check_health(input_client, "/health")
        _check_health(review_client, "/health")
        if args.ingest_api_base:
            _check_external_health(args.ingest_api_base)
        _check_external_health(args.notify_api_base)
        if args.llm_api_base:
            _check_external_health(args.llm_api_base)

        _ensure_authenticated_session(input_client, notify_email=args.notify_email, password=args.auth_password)
        _request_json(input_client, "GET", "/onboarding/status")

        fake_cmd = [
            sys.executable,
            "scripts/fake_source_provider.py",
            "--host",
            args.fake_provider_host,
            "--port",
            str(args.fake_provider_port),
            "--scenario-manifest",
            str(manifest_path),
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
            input_client,
            "POST",
            "/sources",
            json_payload={
                "source_kind": "calendar",
                "provider": "ics",
                "source_key": f"{run_id}-ics",
                "display_name": "Semester Demo Calendar Source",
                "poll_interval_seconds": 900,
                "config": {},
                "secrets": {"url": f"http://{args.fake_provider_host}:{args.fake_provider_port}/ics/calendar.ics"},
            },
        )
        gmail_source = _request_json(
            input_client,
            "POST",
            "/sources",
            json_payload={
                "source_kind": "email",
                "provider": "gmail",
                "source_key": f"{run_id}-gmail",
                "display_name": "Semester Demo Inbox Source",
                "poll_interval_seconds": 900,
                "config": {"label_id": "INBOX"},
                "secrets": {"access_token": "fake-access-token", "account_email": "fake.student@example.edu"},
            },
        )
        calendar_source_id = int(ics_source["source_id"])
        gmail_source_id = int(gmail_source["source_id"])
        created_source_ids.extend([calendar_source_id, gmail_source_id])
        report["source"]["calendar_source_id"] = calendar_source_id
        report["source"]["gmail_source_id"] = gmail_source_id

        _set_fake_batch(fake_client, semester=1, batch=0, run_tag=run_tag)
        baseline_req = _request_json(
            input_client,
            "POST",
            f"/sources/{gmail_source_id}/sync-requests",
            json_payload={"metadata": {"kind": "semester-demo-baseline"}},
            headers={"Idempotency-Key": f"{run_id}:baseline:gmail"},
        )
        baseline_request_id = str(baseline_req["request_id"])
        report["source"]["gmail_baseline_request_id"] = baseline_request_id
        _wait_sync_success(
            input_client,
            request_id=baseline_request_id,
            timeout_seconds=args.sync_timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
        )

        decided_change_ids: set[int] = set()
        pinned_pending_ids: set[int] = set()
        source_filter = {calendar_source_id, gmail_source_id}

        for pointer in _flatten_manifest_batches(manifest):
            _set_fake_batch(fake_client, semester=pointer.semester, batch=pointer.batch)
            semester_report = _semester_report(report=report, semester=pointer.semester)
            batch_report: dict[str, Any] = {
                "semester": pointer.semester,
                "batch": pointer.batch,
                "global_batch": pointer.global_batch,
                "ics_request_id": None,
                "gmail_request_id": None,
                "ics_status": None,
                "gmail_status": None,
                "new_pending_count": 0,
                "approved_count": 0,
                "rejected_count": 0,
                "kept_pending_count": 0,
                "notification_flush": None,
                "errors": [],
            }
            semester_report["batches"].append(batch_report)

            ics_req = _request_json(
                input_client,
                "POST",
                f"/sources/{calendar_source_id}/sync-requests",
                json_payload={"metadata": {"kind": "semester-demo", "semester": pointer.semester, "batch": pointer.batch, "source": "ics"}},
                headers={"Idempotency-Key": f"{run_id}:s{pointer.semester}:b{pointer.batch}:ics"},
            )
            batch_report["ics_request_id"] = str(ics_req["request_id"])
            ics_status_payload = _wait_sync_success(
                input_client,
                request_id=batch_report["ics_request_id"],
                timeout_seconds=args.sync_timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
            )
            batch_report["ics_status"] = str((ics_status_payload.get("connector_result") or {}).get("status") or "")

            gmail_req = _request_json(
                input_client,
                "POST",
                f"/sources/{gmail_source_id}/sync-requests",
                json_payload={"metadata": {"kind": "semester-demo", "semester": pointer.semester, "batch": pointer.batch, "source": "gmail"}},
                headers={"Idempotency-Key": f"{run_id}:s{pointer.semester}:b{pointer.batch}:gmail"},
            )
            batch_report["gmail_request_id"] = str(gmail_req["request_id"])
            gmail_status_payload = _wait_sync_success(
                input_client,
                request_id=batch_report["gmail_request_id"],
                timeout_seconds=args.sync_timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
            )
            batch_report["gmail_status"] = str((gmail_status_payload.get("connector_result") or {}).get("status") or "")

            pending_rows = _request_paginated_list(review_client, path="/review/changes?review_status=pending")
            target_pending_rows = []
            for row in pending_rows:
                change_id = row.get("id")
                if not isinstance(change_id, int):
                    continue
                if change_id in decided_change_ids or change_id in pinned_pending_ids:
                    continue
                if _extract_source_ids(row).intersection(source_filter):
                    target_pending_rows.append(row)

            batch_report["new_pending_count"] = len(target_pending_rows)
            actions = _apply_mixed_review_policy(
                review_client=review_client,
                rows=target_pending_rows,
                seed=args.seed,
                run_id=run_id,
            )
            approved_ids = actions["approved_ids"]
            rejected_ids = actions["rejected_ids"]
            kept_pending_ids = actions["kept_pending_ids"]
            decided_change_ids.update(approved_ids)
            decided_change_ids.update(rejected_ids)
            pinned_pending_ids.update(kept_pending_ids)

            batch_report["approved_count"] = len(approved_ids)
            batch_report["rejected_count"] = len(rejected_ids)
            batch_report["kept_pending_count"] = len(kept_pending_ids)
            semester_report["review_totals"]["approved"] += len(approved_ids)
            semester_report["review_totals"]["rejected"] += len(rejected_ids)
            semester_report["review_totals"]["pending"] += len(kept_pending_ids)

            flush_payload = _flush_notifications(
                notify_api_base=args.notify_api_base,
                ops_token=args.ops_token,
                run_id=run_id,
                semester=pointer.semester,
                batch=pointer.batch,
            )
            batch_report["notification_flush"] = flush_payload
            _accumulate_flush(target=semester_report["notification_flush"], payload=flush_payload)
            _accumulate_flush(target=report["notification_flush"], payload=flush_payload)

            _assert(
                report["assertions"],
                name=f"s{pointer.semester}_b{pointer.batch}_ics_status",
                passed=batch_report["ics_status"] in {"CHANGED", "NO_CHANGE"},
                detail=f"status={batch_report['ics_status']}",
            )
            _assert(
                report["assertions"],
                name=f"s{pointer.semester}_b{pointer.batch}_gmail_status",
                passed=batch_report["gmail_status"] in {"CHANGED", "NO_CHANGE"},
                detail=f"status={batch_report['gmail_status']}",
            )
            _assert(
                report["assertions"],
                name=f"s{pointer.semester}_b{pointer.batch}_flush_progress",
                passed=(flush_payload["processed_slots"] > 0 or flush_payload["sent_count"] > 0 or flush_payload["enqueued_notifications"] > 0),
                detail=json.dumps(flush_payload, ensure_ascii=True),
            )

            if pointer.semester == 1 and pointer.batch == 1:
                _evaluate_suffix_assertions(
                    review_client=review_client,
                    gmail_source_id=gmail_source_id,
                    suffix_expectations=suffix_expectations,
                    report=report,
                )

        provider_state = _request_json(fake_client, "GET", "/__admin/state")
        report["provider_state"] = provider_state
        _validate_provider_volume(report=report, provider_state=provider_state)
        _assert_notification_sink_growth(
            sink_path=notification_jsonl_path,
            baseline_rows=notification_rows_before,
            report=report,
        )

    except Exception as exc:
        report["fatal_errors"].append(str(exc))
        report["passed"] = False
    finally:
        if created_source_ids:
            cleanup_cmd = [sys.executable, "scripts/ops_cleanup_smoke_state.py", "--apply", "--json"]
            for source_id in created_source_ids:
                cleanup_cmd.extend(["--source-id", str(source_id)])
            cleanup = subprocess.run(cleanup_cmd, check=False, capture_output=True, text=True)
            if cleanup.returncode != 0:
                report["fatal_errors"].append(f"pending_cleanup_failed: {(cleanup.stderr or cleanup.stdout)[:600]}")

        if args.cleanup_sources and created_source_ids and input_client is not None:
            for source_id in created_source_ids:
                try:
                    input_client.delete(f"/sources/{source_id}", timeout=8.0)
                except Exception as exc:
                    report["fatal_errors"].append(f"source_cleanup_failed source_id={source_id}: {exc}")

        if input_client is not None:
            input_client.close()
        if review_client is not None:
            review_client.close()
        if fake_client is not None:
            fake_client.close()
        if fake_process is not None:
            fake_process.terminate()
            try:
                fake_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                fake_process.kill()
                fake_process.wait(timeout=5)

        notification_rows_after = _count_jsonl_rows(notification_jsonl_path)
        report["notification_sink"]["rows_after"] = notification_rows_after
        report["notification_sink"]["rows_delta"] = max(notification_rows_after - notification_rows_before, 0)
        report["failed_assertions"] = [row for row in report["assertions"] if row.get("passed") is not True]
        report["passed"] = not report["fatal_errors"] and not report["failed_assertions"]
        report["finished_at"] = _utc_now_iso()
        report_path.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "run_id": report["run_id"],
                "passed": report["passed"],
                "failed_assertions": len(report["failed_assertions"]),
                "fatal_errors": report["fatal_errors"],
                "report": str(report_path),
            },
            ensure_ascii=True,
        )
    )
    return 0 if report["passed"] else 1


def _check_health(client: httpx.Client, path: str) -> None:
    response = client.get(path, timeout=8.0)
    if response.status_code != 200:
        raise DemoFailure(f"health check failed path={path} status={response.status_code} body={response.text[:300]}")


def _check_external_health(base_url: str) -> None:
    response = httpx.get(f"{base_url.rstrip('/')}/health", timeout=8.0)
    if response.status_code != 200:
        raise DemoFailure(f"health check failed base={base_url} status={response.status_code} body={response.text[:300]}")


def _flatten_manifest_batches(manifest: ScenarioManifest) -> list[BatchPointer]:
    pointers: list[BatchPointer] = []
    for semester_plan in manifest.plans:
        for batch_plan in semester_plan.batches:
            pointers.append(
                BatchPointer(
                    semester=batch_plan.semester,
                    batch=batch_plan.batch,
                    global_batch=batch_plan.global_batch,
                )
            )
    pointers.sort(key=lambda row: row.global_batch)
    return pointers


def _semester_report(*, report: dict[str, Any], semester: int) -> dict[str, Any]:
    for row in report["semesters"]:
        if int(row.get("semester") or -1) == semester:
            return row
    raise DemoFailure(f"missing semester report slot for semester={semester}")


def _apply_mixed_review_policy(
    *,
    review_client: httpx.Client,
    rows: list[dict[str, Any]],
    seed: int,
    run_id: str,
) -> dict[str, set[int]]:
    approved_ids: set[int] = set()
    rejected_ids: set[int] = set()
    kept_pending_ids: set[int] = set()

    for row in rows:
        change_id = row.get("id")
        if not isinstance(change_id, int):
            continue
        decision = _mixed_decision_for_change(seed=seed, change_id=change_id)
        if decision == "pending":
            kept_pending_ids.add(change_id)
            continue
        payload = _request_json(
            review_client,
            "POST",
            f"/review/changes/{change_id}/decisions",
            json_payload={"decision": decision, "note": f"semester demo mixed policy run={run_id}"},
        )
        expected_status = "approved" if decision == "approve" else "rejected"
        if str(payload.get("review_status") or "") != expected_status:
            raise DemoFailure(
                f"review decision mismatch change_id={change_id} decision={decision} expected_status={expected_status}"
            )
        if decision == "approve":
            approved_ids.add(change_id)
        else:
            rejected_ids.add(change_id)

    return {
        "approved_ids": approved_ids,
        "rejected_ids": rejected_ids,
        "kept_pending_ids": kept_pending_ids,
    }


def _flush_notifications(
    *,
    notify_api_base: str,
    ops_token: str,
    run_id: str,
    semester: int,
    batch: int,
) -> dict[str, Any]:
    headers = {"X-Service-Name": "ops", "X-Service-Token": ops_token}
    with httpx.Client(base_url=notify_api_base.rstrip("/"), headers=headers) as client:
        return _request_json(
            client,
            "POST",
            "/internal/notifications/flush",
            json_payload={
                "run_id": run_id,
                "semester": semester,
                "batch": batch,
                "force_due": True,
            },
        )


def _accumulate_flush(*, target: dict[str, Any], payload: dict[str, Any]) -> None:
    target["batches_flushed"] = int(target.get("batches_flushed") or 0) + 1
    for key in ("enqueued_notifications", "processed_slots", "sent_count", "failed_count"):
        target[key] = int(target.get(key) or 0) + int(payload.get(key) or 0)


def _build_suffix_expectations(*, manifest: ScenarioManifest) -> dict[str, str]:
    out: dict[str, str] = {}
    for semester_plan in manifest.plans:
        for batch_plan in semester_plan.batches:
            for message in batch_plan.gmail_messages:
                expected = str(message.expected_link_outcome)
                if expected in {"suffix_required_missing", "suffix_mismatch", "auto_link"}:
                    out[message.message_id] = expected
    return out


def _evaluate_suffix_assertions(
    *,
    review_client: httpx.Client,
    gmail_source_id: int,
    suffix_expectations: dict[str, str],
    report: dict[str, Any],
) -> None:
    candidates = _request_paginated_list(
        review_client,
        path=f"/review/link-candidates?status=all&source_id={gmail_source_id}",
    )
    links = _request_paginated_list(
        review_client,
        path=f"/review/links?source_id={gmail_source_id}",
    )
    candidate_by_external = {
        str(row.get("external_event_id")): row
        for row in candidates
        if isinstance(row.get("external_event_id"), str)
    }
    link_by_external = {
        str(row.get("external_event_id")): row
        for row in links
        if isinstance(row.get("external_event_id"), str)
    }

    for message_id, expected in suffix_expectations.items():
        if expected == "auto_link":
            passed = message_id in link_by_external
            detail = f"link_present={passed}"
        else:
            candidate = candidate_by_external.get(message_id)
            if candidate is None:
                passed = False
                detail = "candidate missing"
            else:
                breakdown = candidate.get("score_breakdown")
                score_breakdown = breakdown if isinstance(breakdown, dict) else {}
                reason = str(score_breakdown.get("rule_reason") or "")
                passed = reason == expected
                detail = f"rule_reason={reason}"
        report["suffix_assertions"][message_id]["passed"] = passed
        report["suffix_assertions"][message_id]["detail"] = detail
        _assert(
            report["assertions"],
            name=f"suffix_{message_id}_{expected}",
            passed=passed,
            detail=detail,
        )


def _validate_provider_volume(*, report: dict[str, Any], provider_state: dict[str, Any]) -> None:
    counters_raw = provider_state.get("semester_batch_counters")
    counters = counters_raw if isinstance(counters_raw, dict) else {}

    semester_ics_events: dict[int, int] = {}
    semester_gmail_history_messages: dict[int, int] = {}
    for key, value in counters.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        if not key.startswith("s") or "b" not in key:
            continue
        try:
            semester = int(key[1:3])
        except Exception:
            continue
        semester_ics_events[semester] = semester_ics_events.get(semester, 0) + int(value.get("ics_event_served_count") or 0)
        semester_gmail_history_messages[semester] = semester_gmail_history_messages.get(semester, 0) + int(
            value.get("gmail_history_message_count") or 0
        )

    for semester_payload in report["semesters"]:
        semester = int(semester_payload["semester"])
        ics_target = int(semester_payload["ics_target_count"])
        gmail_target = int(semester_payload["gmail_target_count"])
        ics_observed = semester_ics_events.get(semester, 0)
        gmail_observed = semester_gmail_history_messages.get(semester, 0)
        _assert(
            report["assertions"],
            name=f"semester_{semester}_ics_volume",
            passed=ics_observed >= ics_target,
            detail=f"observed={ics_observed} target={ics_target}",
        )
        _assert(
            report["assertions"],
            name=f"semester_{semester}_gmail_volume",
            passed=gmail_observed >= gmail_target,
            detail=f"observed={gmail_observed} target={gmail_target}",
        )


def _assert_notification_sink_growth(*, sink_path: Path, baseline_rows: int, report: dict[str, Any]) -> None:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        now_rows = _count_jsonl_rows(sink_path)
        if now_rows > baseline_rows:
            _assert(
                report["assertions"],
                name="notification_jsonl_rows_grew",
                passed=True,
                detail=f"rows_before={baseline_rows} rows_after={now_rows}",
            )
            return
        time.sleep(0.2)
    now_rows = _count_jsonl_rows(sink_path)
    _assert(
        report["assertions"],
        name="notification_jsonl_rows_grew",
        passed=False,
        detail=f"rows_before={baseline_rows} rows_after={now_rows}",
    )


if __name__ == "__main__":
    raise SystemExit(main())
