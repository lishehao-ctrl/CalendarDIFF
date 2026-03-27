from __future__ import annotations

import json
from itertools import chain, repeat
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.run_real_user_flow_eval as real_flow


def test_change_focus_path_uses_bucket_and_focus_param() -> None:
    assert real_flow.change_focus_path({"id": 11, "review_bucket": "changes"}) == "/changes?bucket=changes&focus=11"
    assert real_flow.change_focus_path({"id": 12, "review_bucket": "initial_review"}) == "/changes?bucket=initial_review&focus=12"


def test_select_review_targets_picks_distinct_rows() -> None:
    targets = real_flow.select_review_targets(
        [
            {"id": 1, "review_status": "pending", "change_type": "created"},
            {"id": 2, "review_status": "pending", "change_type": "due_changed"},
            {"id": 3, "review_status": "pending", "change_type": "removed"},
        ]
    )

    assert targets["approve"]["id"] == 1
    assert targets["edit"]["id"] == 2
    assert targets["reject"]["id"] == 3


def test_build_summary_markdown_includes_all_flow_lines(tmp_path: Path) -> None:
    summary = {
        "generated_at": "2026-03-26T00:00:00+00:00",
        "overall_status": "passed",
        "run_dir": str(tmp_path),
        "flows": [
            {
                "flow_id": "auth_register_and_enter_onboarding",
                "title": "Register and enter onboarding",
                "status": "passed",
                "browser_checks_passed": True,
                "api_checks_passed": True,
                "user_visible_outcome": "Redirected to onboarding.",
                "artifacts": {},
                "notes": ["Browser step", "API step"],
            }
        ],
    }

    markdown = real_flow.build_summary_markdown(summary=summary)

    assert "# Real User Flow Eval" in markdown
    assert "auth_register_and_enter_onboarding" in markdown
    assert "Redirected to onboarding." in markdown


def test_write_summary_persists_json_and_markdown(tmp_path: Path) -> None:
    summary = {
        "generated_at": "2026-03-26T00:00:00+00:00",
        "overall_status": "passed",
        "run_dir": str(tmp_path),
        "flows": [],
    }

    real_flow.write_summary(run_dir=tmp_path, summary=summary)

    assert json.loads((tmp_path / "SUMMARY.json").read_text(encoding="utf-8"))["overall_status"] == "passed"
    assert "Real User Flow Eval" in (tmp_path / "SUMMARY.md").read_text(encoding="utf-8")


def test_normalize_failure_message_adds_fake_gmail_hint() -> None:
    error = RuntimeError("sync failed code=gmail_auth_failed message=bad auth")

    normalized = real_flow.normalize_failure_message(error)

    assert "gmail_auth_failed" in normalized
    assert "GMAIL_API_BASE_URL=http://127.0.0.1:8765/gmail/v1/users/me" in normalized


def test_build_skipped_results_marks_remaining_flows_skipped() -> None:
    rows = real_flow.build_skipped_results(reason="preflight failed", start_index=2)

    assert [row.flow_id for row in rows] == [
        "gmail_source_sync_and_observability",
        "changes_review_resolution",
        "agent_assisted_low_risk_action",
    ]
    assert all(row.status == "skipped" for row in rows)


def test_build_summary_includes_failure_stage_and_preflight(tmp_path: Path) -> None:
    summary = real_flow.build_summary(
        run_dir=tmp_path,
        results=[],
        failure_stage="backend_not_fake_gmail_ready",
        preflight={"status": "failed", "remediation": "restart backend"},
    )

    assert summary["failure_stage"] == "backend_not_fake_gmail_ready"
    assert summary["preflight"]["status"] == "failed"
    markdown = real_flow.build_summary_markdown(summary=summary)
    assert "## Preflight" in markdown
    assert "backend_not_fake_gmail_ready" in markdown


def test_build_lightweight_gmail_monitoring_config_narrows_scope() -> None:
    config = real_flow.build_lightweight_gmail_monitoring_config(
        {"monitor_since": "2025-01-01", "label_id": "COURSE", "label_ids": ["COURSE", "INBOX"]}
    )

    assert config["monitor_since"] == (
        real_flow.datetime.now(real_flow.replay.UTC).date() - real_flow.timedelta(days=1)
    ).isoformat()
    assert config["label_id"] == "INBOX"
    assert "label_ids" not in config


def test_wait_for_gmail_flow_progress_accepts_succeeded_without_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request_json(_client, method: str, path: str):
        assert method == "GET"
        assert path == "/sync-requests/req-1"
        return {"request_id": "req-1", "source_id": 5, "status": "SUCCEEDED", "applied": False}

    monkeypatch.setattr(real_flow.replay, "request_json", fake_request_json)

    payload = real_flow.wait_for_gmail_flow_progress(
        client=object(), request_id="req-1", source_id=5, timeout_seconds=1.0, stall_window_seconds=0.1
    )

    assert payload["status"] == "SUCCEEDED"


def test_wait_for_review_prep_source_sync_accepts_succeeded_without_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request_json(_client, method: str, path: str):
        assert method == "GET"
        assert path == "/sync-requests/req-2"
        return {"request_id": "req-2", "source_id": 4, "status": "SUCCEEDED", "applied": False}

    monkeypatch.setattr(real_flow.replay, "request_json", fake_request_json)

    payload = real_flow.wait_for_review_prep_source_sync(
        client=object(), request_id="req-2", source_id=4, provider="ics", timeout_seconds=1.0, stall_window_seconds=0.1
    )

    assert payload["status"] == "SUCCEEDED"


def test_wait_for_review_prep_source_sync_uses_provider_specific_budgets(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[float, float, bool]] = []

    monkeypatch.setattr(
        real_flow,
        "wait_for_source_flow_progress",
        lambda _client, request_id, source_id, timeout_seconds, stall_window_seconds, allow_observability_ready: (
            captured.append((timeout_seconds, stall_window_seconds, allow_observability_ready)) or {"status": "SUCCEEDED"}
        ),
    )

    real_flow.wait_for_review_prep_source_sync(client=object(), request_id="gmail-req", source_id=5, provider="gmail")
    real_flow.wait_for_review_prep_source_sync(client=object(), request_id="ics-req", source_id=4, provider="ics")

    assert captured == [
        (real_flow.GMAIL_REVIEW_PREP_TIMEOUT_SECONDS, real_flow.GMAIL_REVIEW_PREP_STALL_WINDOW_SECONDS, False),
        (real_flow.ICS_REVIEW_PREP_TIMEOUT_SECONDS, real_flow.ICS_REVIEW_PREP_STALL_WINDOW_SECONDS, False),
    ]


def test_wait_for_onboarding_ready_with_ics_source_waits_for_backend_convergence(monkeypatch: pytest.MonkeyPatch) -> None:
    status_rows = iter(
        [
            {"stage": "needs_canvas_ics"},
            {"stage": "ready"},
        ]
    )
    source_rows = iter(
        [
            [],
            [{"source_id": 4, "provider": "ics"}],
        ]
    )

    monkeypatch.setattr(
        real_flow.replay,
        "request_json",
        lambda _client, method, path: next(status_rows) if method == "GET" and path == "/onboarding/status" else {},
    )
    monkeypatch.setattr(
        real_flow.replay,
        "request_json_list",
        lambda _client, method, path: next(source_rows) if method == "GET" and path == "/sources?status=all" else [],
    )

    onboarding_status, ics_source = real_flow.wait_for_onboarding_ready_with_ics_source(
        client=object(),
        timeout_seconds=2.0,
    )

    assert onboarding_status["stage"] == "ready"
    assert ics_source["provider"] == "ics"


def test_wait_for_onboarding_ready_with_ics_source_times_out_with_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        real_flow.replay,
        "request_json",
        lambda _client, method, path: {"stage": "needs_canvas_ics"} if method == "GET" and path == "/onboarding/status" else {},
    )
    monkeypatch.setattr(
        real_flow.replay,
        "request_json_list",
        lambda _client, method, path: [] if method == "GET" and path == "/sources?status=all" else [],
    )

    with pytest.raises(real_flow.RealFlowEvalError) as excinfo:
        real_flow.wait_for_onboarding_ready_with_ics_source(client=object(), timeout_seconds=0.01)

    assert "flow 2 failed to produce a ready user with an ICS source" in str(excinfo.value)
    assert "stage=needs_canvas_ics" in str(excinfo.value)


def test_wait_for_change_persistence_polls_until_edited_name_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    monotonic_values = chain([0.0, 0.0, 1.0, 2.0], repeat(2.0))
    change_rows = iter(
        [
            {"id": 16, "review_status": "pending"},
            {"id": 16, "review_status": "approved"},
            {"id": 16, "review_status": "approved"},
        ]
    )
    edit_context_rows = iter(
        [
            {"editable_event": {"event_name": "Old Name"}},
            {"editable_event": {"event_name": "Real Flow Edited c089"}},
        ]
    )

    monkeypatch.setattr(real_flow.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(real_flow.time, "sleep", lambda _seconds: None)

    def fake_request_json(_client, method: str, path: str):
        assert method == "GET"
        if path == "/changes/16":
            return next(change_rows)
        if path == "/changes/16/edit-context":
            return next(edit_context_rows)
        raise AssertionError(path)

    monkeypatch.setattr(real_flow.replay, "request_json", fake_request_json)

    row, edit_context = real_flow.wait_for_change_persistence(
        client=object(),
        change_id=16,
        expected_review_status="approved",
        expected_edited_event_name="Real Flow Edited c089",
        timeout_seconds=5.0,
    )

    assert row["review_status"] == "approved"
    assert edit_context is not None
    assert edit_context["editable_event"]["event_name"] == "Real Flow Edited c089"


def test_wait_for_change_persistence_times_out_with_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monotonic_values = chain([0.0, 0.0, 5.0, 5.0], repeat(5.0))

    monkeypatch.setattr(real_flow.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(real_flow.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        real_flow.replay,
        "request_json",
        lambda _client, method, path: {"id": 16, "review_status": "pending"} if method == "GET" and path == "/changes/16" else {},
    )

    with pytest.raises(real_flow.RealFlowEvalError) as excinfo:
        real_flow.wait_for_change_persistence(
            client=object(),
            change_id=16,
            expected_review_status="approved",
            timeout_seconds=0.1,
        )

    assert "flow 4 persistence timeout" in str(excinfo.value)
    assert "last_review_status=pending" in str(excinfo.value)


def test_observability_ready_for_flow_requires_stable_visible_state() -> None:
    ready = real_flow._observability_is_ready_for_flow(
        request_id="req-1",
        observability={
            "active_request_id": None,
            "source_product_phase": "monitoring_live",
            "source_recovery": {"trust_state": "trusted"},
            "bootstrap": {"request_id": "req-1", "status": "SUCCEEDED"},
            "latest_replay": None,
        },
    )

    blocked = real_flow._observability_is_ready_for_flow(
        request_id="req-1",
        observability={
            "active_request_id": "req-1",
            "source_product_phase": "monitoring_live",
            "source_recovery": {"trust_state": "trusted"},
            "bootstrap": {"request_id": "req-1", "status": "SUCCEEDED"},
        },
    )

    assert ready is True
    assert blocked is False


def test_infer_failure_stage_maps_worker_pipeline_stall() -> None:
    stage = real_flow.infer_failure_stage(
        "replay sync stalled request_id=abc source_id=5 status=RUNNING progress_phase=llm_queue progress_label=Queued for extraction"
    )

    assert stage == "backend_worker_pipeline_stalled"


def test_summarize_probe_status_extracts_runtime_fields() -> None:
    payload = {
        "request_id": "req-1",
        "source_id": 5,
        "status": "RUNNING",
        "stage": "LLM_PARSE",
        "substage": "queued",
        "updated_at": "2026-03-26T00:00:10+00:00",
        "progress": {
            "phase": "llm_queue",
            "label": "Queued for extraction",
            "updated_at": "2026-03-26T00:00:09+00:00",
        },
    }
    observability = {
        "active_request_id": "req-1",
        "sync_state": "running",
        "runtime_state": "running",
        "source_product_phase": "importing_baseline",
        "source_recovery": {"trust_state": "blocked"},
        "bootstrap": {"request_id": "req-0", "status": "SUCCEEDED", "updated_at": "2026-03-26T00:00:06+00:00"},
        "latest_replay": {"request_id": "req-1", "status": "RUNNING", "updated_at": "2026-03-26T00:00:08+00:00"},
        "active": {
            "sync_state": "running",
            "runtime_state": "running",
            "stage_updated_at": "2026-03-26T00:00:08+00:00",
            "progress": {"phase": "llm_queue", "updated_at": "2026-03-26T00:00:08+00:00"},
        },
    }

    summary = real_flow._summarize_probe_status(
        payload=payload,
        observability=observability,
        last_progress_observed_at="2026-03-26T00:00:11+00:00",
        queue_diagnostics={"parse_queue_depth": 7, "parse_retry_depth": 2, "llm_worker_concurrency": 12, "llm_queue_consumer_poll_ms": 500},
    )

    assert summary["request_id"] == "req-1"
    assert summary["source_id"] == 5
    assert summary["progress_phase"] == "llm_queue"
    assert summary["source_active_request_id"] == "req-1"
    assert summary["source_product_phase"] == "importing_baseline"
    assert summary["source_recovery_trust_state"] == "blocked"
    assert summary["latest_replay_request_id"] == "req-1"
    assert summary["last_sync_payload_updated_at"] == "2026-03-26T00:00:09+00:00"
    assert summary["last_observability_updated_at"] == "2026-03-26T00:00:08+00:00"
    assert summary["last_progress_observed_at"] == "2026-03-26T00:00:11+00:00"
    assert summary["parse_queue_depth"] == 7
    assert summary["parse_retry_depth"] == 2


def test_collect_parse_queue_diagnostics_reports_depths(monkeypatch: pytest.MonkeyPatch) -> None:
    redis_client = SimpleNamespace(close=lambda: None)

    monkeypatch.setattr(real_flow, "get_settings", lambda: SimpleNamespace(llm_worker_concurrency=9, llm_queue_consumer_poll_ms=250))
    monkeypatch.setattr(real_flow, "get_parse_queue_redis_client", lambda: redis_client)
    monkeypatch.setattr(real_flow, "parse_queue_depth", lambda client: 14)
    monkeypatch.setattr(real_flow, "parse_retry_depth", lambda client: 3)

    diagnostics = real_flow.collect_parse_queue_diagnostics()

    assert diagnostics == {
        "parse_queue_depth": 14,
        "parse_retry_depth": 3,
        "llm_worker_concurrency": 9,
        "llm_queue_consumer_poll_ms": 250,
    }


def test_wait_for_source_flow_progress_resets_stall_when_queue_depth_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    monotonic_values = chain([0.0, 0.0, 0.11, 0.11, 0.19, 0.19], repeat(0.19))
    sync_rows = iter(
        [
            {
                "request_id": "req-queue",
                "source_id": 5,
                "status": "RUNNING",
                "stage": "LLM_PARSE",
                "substage": "llm_task_queued",
                "updated_at": "2026-03-26T00:00:10+00:00",
                "progress": {"phase": "llm_queue", "label": "Queued for extraction", "updated_at": "2026-03-26T00:00:10+00:00"},
            },
            {
                "request_id": "req-queue",
                "source_id": 5,
                "status": "RUNNING",
                "stage": "LLM_PARSE",
                "substage": "llm_task_queued",
                "updated_at": "2026-03-26T00:00:10+00:00",
                "progress": {"phase": "llm_queue", "label": "Queued for extraction", "updated_at": "2026-03-26T00:00:10+00:00"},
            },
            {
                "request_id": "req-queue",
                "source_id": 5,
                "status": "SUCCEEDED",
                "applied": True,
            },
        ]
    )

    monkeypatch.setattr(real_flow.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(real_flow.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        real_flow.replay,
        "request_json",
        lambda _client, method, path: next(sync_rows)
        if method == "GET" and path == "/sync-requests/req-queue"
        else {
            "active_request_id": "req-queue",
            "active": {
                "status": "RUNNING",
                "stage": "LLM_PARSE",
                "substage": "llm_task_queued",
                "progress": {"phase": "llm_queue", "updated_at": "2026-03-26T00:00:10+00:00"},
            },
        },
    )
    queue_rows = iter(
        [
            {"parse_queue_depth": 10, "parse_retry_depth": 0, "llm_worker_concurrency": 12, "llm_queue_consumer_poll_ms": 500},
            {"parse_queue_depth": 9, "parse_retry_depth": 0, "llm_worker_concurrency": 12, "llm_queue_consumer_poll_ms": 500},
        ]
    )
    monkeypatch.setattr(real_flow, "collect_parse_queue_diagnostics", lambda: next(queue_rows))

    payload = real_flow.wait_for_source_flow_progress(
        client=object(),
        request_id="req-queue",
        source_id=5,
        timeout_seconds=1.0,
        stall_window_seconds=0.1,
        allow_observability_ready=False,
    )

    assert payload["status"] == "SUCCEEDED"


def test_wait_for_source_flow_progress_stalls_when_queue_depth_and_payload_do_not_change(monkeypatch: pytest.MonkeyPatch) -> None:
    monotonic_values = chain([0.0, 0.0, 0.11, 0.11, 0.21, 0.21], repeat(0.21))
    running_row = {
        "request_id": "req-stuck",
        "source_id": 5,
        "status": "RUNNING",
        "stage": "LLM_PARSE",
        "substage": "llm_task_queued",
        "updated_at": "2026-03-26T00:00:10+00:00",
        "progress": {"phase": "llm_queue", "label": "Queued for extraction", "updated_at": "2026-03-26T00:00:10+00:00"},
    }
    observability_row = {
        "active_request_id": "req-stuck",
        "latest_replay": {"request_id": "req-stuck", "status": "RUNNING", "updated_at": "2026-03-26T00:00:10+00:00"},
    }

    monkeypatch.setattr(real_flow.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(real_flow.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        real_flow.replay,
        "request_json",
        lambda _client, method, path: running_row if method == "GET" and path == "/sync-requests/req-stuck" else observability_row,
    )
    monkeypatch.setattr(
        real_flow,
        "collect_parse_queue_diagnostics",
        lambda: {"parse_queue_depth": 10, "parse_retry_depth": 0, "llm_worker_concurrency": 12, "llm_queue_consumer_poll_ms": 500},
    )

    with pytest.raises(real_flow.RealFlowEvalError) as excinfo:
        real_flow.wait_for_source_flow_progress(
            client=object(),
            request_id="req-stuck",
            source_id=5,
            timeout_seconds=1.0,
            stall_window_seconds=0.1,
            allow_observability_ready=False,
        )

    message = str(excinfo.value)
    assert "\"parse_queue_depth\": 10" in message
    assert "\"parse_retry_depth\": 0" in message


def test_ensure_review_targets_stops_after_gmail_when_targets_ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "api_events.jsonl").write_text("", encoding="utf-8")
    pending_sequences = iter(
        [
            [],
            [
                {"id": 1, "review_status": "pending", "change_type": "created"},
                {"id": 2, "review_status": "pending", "change_type": "due_changed"},
                {"id": 3, "review_status": "pending", "change_type": "removed"},
            ],
        ]
    )
    sync_calls: list[tuple[int, str]] = []

    monkeypatch.setattr(
        real_flow.replay,
        "request_json_list",
        lambda _client, method, path: next(pending_sequences) if method == "GET" and path == "/changes?review_status=pending&limit=200" else [],
    )
    monkeypatch.setattr(real_flow.replay, "set_fake_provider_batch", lambda **_: None)
    monkeypatch.setattr(real_flow.replay, "create_sync_request", lambda _client, source_id, trace_id: f"req-{source_id}")
    monkeypatch.setattr(
        real_flow,
        "wait_for_review_prep_source_sync",
        lambda _client, request_id, source_id, provider, timeout_seconds=None, stall_window_seconds=None: (
            sync_calls.append((source_id, request_id)) or {"status": "SUCCEEDED"}
        ),
    )

    targets = real_flow.ensure_review_targets(
        client=object(),
        batches=[type("Batch", (), {"semester": 2026, "batch": 1, "global_batch": 1})(), type("Batch", (), {"semester": 2026, "batch": 2, "global_batch": 2})()],
        ics_source_id=4,
        gmail_source_id=5,
        fake_provider_host="127.0.0.1",
        fake_provider_port=8765,
        run_tag="run-tag",
        run_dir=tmp_path,
    )

    assert targets["approve"]["id"] == 1
    assert sync_calls == [(5, "req-5")]


def test_ensure_review_targets_uses_multiple_gmail_batches_before_ics(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "api_events.jsonl").write_text("", encoding="utf-8")
    pending_sequences = iter(
        [
            [],
            [{"id": 1, "review_status": "pending", "change_type": "created"}],
            [
                {"id": 1, "review_status": "pending", "change_type": "created"},
                {"id": 2, "review_status": "pending", "change_type": "due_changed"},
                {"id": 3, "review_status": "pending", "change_type": "removed"},
            ],
        ]
    )
    sync_calls: list[int] = []

    monkeypatch.setattr(
        real_flow.replay,
        "request_json_list",
        lambda _client, method, path: next(pending_sequences) if method == "GET" and path == "/changes?review_status=pending&limit=200" else [],
    )
    monkeypatch.setattr(real_flow.replay, "set_fake_provider_batch", lambda **_: None)
    monkeypatch.setattr(real_flow.replay, "create_sync_request", lambda _client, source_id, trace_id: f"req-{source_id}")
    monkeypatch.setattr(
        real_flow,
        "wait_for_review_prep_source_sync",
        lambda _client, request_id, source_id, provider, timeout_seconds=None, stall_window_seconds=None: (
            sync_calls.append(source_id) or {"status": "SUCCEEDED"}
        ),
    )

    targets = real_flow.ensure_review_targets(
        client=object(),
        batches=[
            type("Batch", (), {"semester": 2026, "batch": 1, "global_batch": 1})(),
            type("Batch", (), {"semester": 2026, "batch": 2, "global_batch": 2})(),
            type("Batch", (), {"semester": 2026, "batch": 3, "global_batch": 3})(),
        ],
        ics_source_id=4,
        gmail_source_id=5,
        fake_provider_host="127.0.0.1",
        fake_provider_port=8765,
        run_tag="run-tag",
        run_dir=tmp_path,
    )

    assert targets["edit"]["id"] == 2
    assert sync_calls == [5, 5]


def test_ensure_review_targets_falls_back_to_ics_when_gmail_not_enough(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "api_events.jsonl").write_text("", encoding="utf-8")
    pending_sequences = iter(
        [
            [],
            [{"id": 1, "review_status": "pending", "change_type": "created"}],
            [{"id": 1, "review_status": "pending", "change_type": "created"}],
            [{"id": 1, "review_status": "pending", "change_type": "created"}],
            [
                {"id": 1, "review_status": "pending", "change_type": "created"},
                {"id": 2, "review_status": "pending", "change_type": "due_changed"},
                {"id": 3, "review_status": "pending", "change_type": "removed"},
            ],
        ]
    )
    sync_calls: list[int] = []

    monkeypatch.setattr(
        real_flow.replay,
        "request_json_list",
        lambda _client, method, path: next(pending_sequences) if method == "GET" and path == "/changes?review_status=pending&limit=200" else [],
    )
    monkeypatch.setattr(real_flow.replay, "set_fake_provider_batch", lambda **_: None)
    monkeypatch.setattr(real_flow.replay, "create_sync_request", lambda _client, source_id, trace_id: f"req-{source_id}")
    monkeypatch.setattr(
        real_flow,
        "wait_for_review_prep_source_sync",
        lambda _client, request_id, source_id, provider, timeout_seconds=None, stall_window_seconds=None: (
            sync_calls.append(source_id) or {"status": "SUCCEEDED"}
        ),
    )

    targets = real_flow.ensure_review_targets(
        client=object(),
        batches=[
            type("Batch", (), {"semester": 2026, "batch": 1, "global_batch": 1})(),
            type("Batch", (), {"semester": 2026, "batch": 2, "global_batch": 2})(),
            type("Batch", (), {"semester": 2026, "batch": 3, "global_batch": 3})(),
            type("Batch", (), {"semester": 2026, "batch": 4, "global_batch": 4})(),
        ],
        ics_source_id=4,
        gmail_source_id=5,
        fake_provider_host="127.0.0.1",
        fake_provider_port=8765,
        run_tag="run-tag",
        run_dir=tmp_path,
    )

    assert targets["edit"]["id"] == 2
    assert sync_calls == [5, 5, 5, 4]
