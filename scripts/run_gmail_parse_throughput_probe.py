#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
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


@dataclass(frozen=True)
class QueueSnapshot:
    recorded_at: str
    request_id: str
    source_id: int
    status: str
    stage: str | None
    substage: str | None
    progress_phase: str | None
    progress_current: int | None
    progress_total: int | None
    parse_queue_depth: int | None
    parse_retry_depth: int | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Gmail parse throughput probe against a live backend.")
    parser.add_argument("--public-api-base", required=True)
    parser.add_argument("--api-key", default=os.getenv("APP_API_KEY", ""))
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--source-id", type=int, required=True)
    parser.add_argument("--trace-label", default=None)
    parser.add_argument("--output-root", default=str(OUTPUT_ROOT))
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--manifest", default=str(replay.DEFAULT_MANIFEST))
    parser.add_argument("--email-bucket", default=replay.DEFAULT_EMAIL_BUCKET)
    parser.add_argument("--fake-provider-host", default=replay.DEFAULT_FAKE_HOST)
    parser.add_argument("--fake-provider-port", type=int, default=replay.DEFAULT_FAKE_PORT)
    parser.add_argument("--start-fake-provider", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--global-batch", type=int, default=1)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_key = str(args.api_key or "").strip()
    if not api_key:
        raise SystemExit("--api-key or APP_API_KEY is required")

    run_dir = Path(args.output_root).expanduser().resolve() / f"gmail-parse-throughput-probe-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    fake_provider_pid: int | None = None
    try:
        maybe_start_fake_provider(
            args=args,
            run_dir=run_dir,
        )
        fake_provider_pid = getattr(args, "_fake_provider_pid", None)

        client = replay.build_api_client(public_api_base=str(args.public_api_base), api_key=api_key)
        try:
            replay.ensure_authenticated_session(client, email=str(args.email), password=str(args.password))
            trace_id = str(args.trace_label or f"gmail-throughput-{uuid.uuid4().hex[:8]}")
            request_id = replay.create_sync_request(client, source_id=int(args.source_id), trace_id=trace_id)
            final_payload, final_observability, snapshots = wait_for_probe_completion(
                client=client,
                request_id=request_id,
                source_id=int(args.source_id),
                timeout_seconds=float(args.timeout_seconds),
                poll_seconds=float(args.poll_seconds),
            )
        finally:
            client.close()

        summary = build_probe_summary(
            source_id=int(args.source_id),
            request_id=request_id,
            final_payload=final_payload,
            final_observability=final_observability,
            snapshots=snapshots,
        )
        (run_dir / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (run_dir / "SUMMARY.md").write_text(render_summary(summary), encoding="utf-8")
        with (run_dir / "queue-snapshots.jsonl").open("w", encoding="utf-8") as handle:
            for row in snapshots:
                handle.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
        print(run_dir)
    finally:
        if fake_provider_pid is not None:
            try:
                os.kill(int(fake_provider_pid), signal.SIGTERM)
            except OSError:
                pass


def maybe_start_fake_provider(*, args: argparse.Namespace, run_dir: Path) -> None:
    if not bool(args.start_fake_provider):
        return
    manifest_path = Path(args.manifest).expanduser().resolve()
    fake_provider_pid = replay.start_fake_provider_with_bucket(
        host=str(args.fake_provider_host),
        port=int(args.fake_provider_port),
        manifest_path=manifest_path,
        email_bucket=str(args.email_bucket),
    )
    replay.ensure_fake_provider_ready(host=str(args.fake_provider_host), port=int(args.fake_provider_port))
    batches = replay.load_batch_specs(json.loads(manifest_path.read_text(encoding="utf-8")))
    if not batches:
        raise RuntimeError("manifest did not produce any replay batches")
    batch_index = max(min(int(args.global_batch), len(batches)), 1) - 1
    batch = batches[batch_index]
    replay.set_fake_provider_batch(
        host=str(args.fake_provider_host),
        port=int(args.fake_provider_port),
        semester=batch.semester,
        batch=batch.batch,
        run_tag=run_dir.name,
    )
    setattr(args, "_fake_provider_pid", fake_provider_pid)


def wait_for_probe_completion(
    *,
    client,
    request_id: str,
    source_id: int,
    timeout_seconds: float,
    poll_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any], list[QueueSnapshot]]:
    deadline = time.monotonic() + timeout_seconds
    snapshots: list[QueueSnapshot] = []
    final_payload: dict[str, Any] | None = None
    final_observability: dict[str, Any] | None = None

    while time.monotonic() < deadline:
        payload = replay.request_json(client, "GET", f"/sync-requests/{request_id}")
        observability = replay.request_json(client, "GET", f"/sources/{source_id}/observability")
        snapshots.append(build_queue_snapshot(request_id=request_id, source_id=source_id, payload=payload))
        final_payload = payload
        final_observability = observability
        status = str(payload.get("status") or "")
        if status in {"SUCCEEDED", "FAILED"}:
            return payload, observability, snapshots
        time.sleep(max(float(poll_seconds), 0.1))

    raise RuntimeError(f"gmail throughput probe timed out request_id={request_id}")


def build_queue_snapshot(*, request_id: str, source_id: int, payload: dict[str, Any]) -> QueueSnapshot:
    progress = payload.get("progress") if isinstance(payload.get("progress"), dict) else {}
    diagnostics = collect_queue_diagnostics()
    return QueueSnapshot(
        recorded_at=datetime.now(UTC).isoformat(),
        request_id=request_id,
        source_id=source_id,
        status=str(payload.get("status") or ""),
        stage=str(payload.get("stage") or "") or None,
        substage=str(payload.get("substage") or "") or None,
        progress_phase=str(progress.get("phase") or "") or None,
        progress_current=int(progress.get("current")) if isinstance(progress.get("current"), (int, float)) else None,
        progress_total=int(progress.get("total")) if isinstance(progress.get("total"), (int, float)) else None,
        parse_queue_depth=diagnostics.get("parse_queue_depth"),
        parse_retry_depth=diagnostics.get("parse_retry_depth"),
    )


def collect_queue_diagnostics() -> dict[str, Any]:
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
    except Exception as exc:  # pragma: no cover - defensive diagnostics path
        diagnostics["parse_queue_error"] = str(exc)
    finally:
        if redis_client is not None:
            try:
                redis_client.close()
            except Exception:
                pass
    return diagnostics


def build_probe_summary(
    *,
    source_id: int,
    request_id: str,
    final_payload: dict[str, Any],
    final_observability: dict[str, Any],
    snapshots: list[QueueSnapshot],
) -> dict[str, Any]:
    progress = final_payload.get("progress") if isinstance(final_payload.get("progress"), dict) else {}
    queue_depths = [row.parse_queue_depth for row in snapshots if isinstance(row.parse_queue_depth, int)]
    retry_depths = [row.parse_retry_depth for row in snapshots if isinstance(row.parse_retry_depth, int)]
    queued_email_count = _int_or_none(progress.get("total")) if isinstance(progress, dict) else None
    if queued_email_count is None:
        progress_totals = [row.progress_total for row in snapshots if isinstance(row.progress_total, int)]
        queued_email_count = max(progress_totals) if progress_totals else None
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "request_id": request_id,
        "source_id": source_id,
        "queued_email_count": queued_email_count,
        "elapsed_ms": final_payload.get("elapsed_ms"),
        "status": final_payload.get("status"),
        "applied": bool(final_payload.get("applied")),
        "gmail_parse_summary": replay.extract_sync_gmail_parse_summary(final_payload),
        "llm_usage": replay.extract_sync_llm_usage(final_payload),
        "queue_depth_max": max(queue_depths) if queue_depths else None,
        "queue_depth_final": queue_depths[-1] if queue_depths else None,
        "queue_retry_depth_max": max(retry_depths) if retry_depths else None,
        "queue_retry_depth_final": retry_depths[-1] if retry_depths else None,
        "latest_replay": final_observability.get("latest_replay") if isinstance(final_observability.get("latest_replay"), dict) else None,
        "snapshot_count": len(snapshots),
    }


def render_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# Gmail Parse Throughput Probe",
        "",
        f"- Request ID: `{summary['request_id']}`",
        f"- Source ID: `{summary['source_id']}`",
        f"- Status: `{summary['status']}`",
        f"- Applied: `{summary['applied']}`",
        f"- Queued email count: `{summary['queued_email_count']}`",
        f"- Elapsed ms: `{summary['elapsed_ms']}`",
        f"- Queue depth max: `{summary['queue_depth_max']}`",
        f"- Queue depth final: `{summary['queue_depth_final']}`",
        f"- Queue retry depth max: `{summary['queue_retry_depth_max']}`",
        f"- Queue retry depth final: `{summary['queue_retry_depth_final']}`",
        "",
        "## Gmail Parse Summary",
        "",
        f"```json\n{json.dumps(summary.get('gmail_parse_summary'), ensure_ascii=False, indent=2)}\n```",
        "",
        "## LLM Usage",
        "",
        f"```json\n{json.dumps(summary.get('llm_usage'), ensure_ascii=False, indent=2)}\n```",
    ]
    return "\n".join(lines) + "\n"


def _int_or_none(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


if __name__ == "__main__":
    main()
