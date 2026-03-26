from __future__ import annotations

from app.modules.runtime.llm.gmail_parse_summary import empty_gmail_parse_summary
import scripts.run_gmail_parse_throughput_probe as probe


def test_build_probe_summary_aggregates_queue_snapshots() -> None:
    snapshots = [
        probe.QueueSnapshot(
            recorded_at="2026-03-26T00:00:00+00:00",
            request_id="req-1",
            source_id=2,
            status="RUNNING",
            stage="llm_parse",
            substage="llm_task_queued",
            progress_phase="llm_queue",
            progress_current=50,
            progress_total=120,
            parse_queue_depth=40,
            parse_retry_depth=0,
        ),
        probe.QueueSnapshot(
            recorded_at="2026-03-26T00:00:05+00:00",
            request_id="req-1",
            source_id=2,
            status="RUNNING",
            stage="llm_parse",
            substage="llm_task_queued",
            progress_phase="llm_queue",
            progress_current=80,
            progress_total=120,
            parse_queue_depth=25,
            parse_retry_depth=1,
        ),
        probe.QueueSnapshot(
            recorded_at="2026-03-26T00:00:10+00:00",
            request_id="req-1",
            source_id=2,
            status="SUCCEEDED",
            stage="completed",
            substage="apply_completed",
            progress_phase="completed",
            progress_current=None,
            progress_total=None,
            parse_queue_depth=3,
            parse_retry_depth=0,
        ),
    ]

    summary = probe.build_probe_summary(
        source_id=2,
        request_id="req-1",
        final_payload={
            "status": "SUCCEEDED",
            "applied": True,
            "elapsed_ms": 12345,
            "progress": {},
            "llm_usage": {"total_tokens": 4000},
            "gmail_parse_summary": {**empty_gmail_parse_summary(), "message_count": 120},
        },
        final_observability={"latest_replay": {"request_id": "req-1", "status": "SUCCEEDED"}},
        snapshots=snapshots,
    )

    assert summary["request_id"] == "req-1"
    assert summary["source_id"] == 2
    assert summary["queued_email_count"] == 120
    assert summary["queue_depth_max"] == 40
    assert summary["queue_depth_final"] == 3
    assert summary["queue_retry_depth_max"] == 1
    assert summary["queue_retry_depth_final"] == 0
    assert summary["snapshot_count"] == 3


def test_render_summary_includes_throughput_fields() -> None:
    markdown = probe.render_summary(
        {
            "request_id": "req-1",
            "source_id": 2,
            "status": "SUCCEEDED",
            "applied": True,
            "queued_email_count": 120,
            "elapsed_ms": 12345,
            "queue_depth_max": 40,
            "queue_depth_final": 3,
            "queue_retry_depth_max": 1,
            "queue_retry_depth_final": 0,
            "gmail_parse_summary": {"message_count": 120},
            "llm_usage": {"total_tokens": 4000},
        }
    )

    assert "Gmail Parse Throughput Probe" in markdown
    assert "`120`" in markdown
    assert "Queue depth max" in markdown
    assert "total_tokens" in markdown
