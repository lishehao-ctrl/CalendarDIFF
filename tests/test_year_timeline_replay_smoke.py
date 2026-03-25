from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.run_year_timeline_replay_smoke as replay


def test_compute_monthly_twice_checkpoints_picks_first_and_midmonth_batches() -> None:
    batches = [
        replay.BatchSpec(1, 1, 1, "WI26", "2026-01-03T10:00:00+00:00", "2026-01", "year-timeline-wi26", "round-00__to__round-01"),
        replay.BatchSpec(1, 2, 2, "WI26", "2026-01-16T10:00:00+00:00", "2026-01", "year-timeline-wi26", "round-01__to__round-02"),
        replay.BatchSpec(1, 3, 3, "WI26", "2026-01-24T10:00:00+00:00", "2026-01", "year-timeline-wi26", "round-02__to__round-03"),
        replay.BatchSpec(1, 4, 4, "WI26", "2026-02-02T10:00:00+00:00", "2026-02", "year-timeline-wi26", "round-03__to__round-04"),
        replay.BatchSpec(1, 5, 5, "WI26", "2026-02-18T10:00:00+00:00", "2026-02", "year-timeline-wi26", "round-04__to__round-05"),
    ]

    checkpoints = replay.compute_monthly_twice_checkpoints(batches)

    assert [row.global_batch for row in checkpoints] == [1, 2, 4, 5]
    assert checkpoints[0].month_key == "2026-01"
    assert checkpoints[1].month_key == "2026-01"
    assert checkpoints[2].month_key == "2026-02"
    assert checkpoints[3].month_key == "2026-02"


def test_diff_snapshots_detects_review_family_and_manual_actions() -> None:
    before = {
        "pending_change_count": 2,
        "event_entity_count": 4,
        "family_count": 1,
        "manual_event_count": 1,
        "changes": [
            {"id": 1, "review_status": "pending", "after_event": {"event_display": {"display_label": "HW1"}}},
            {"id": 2, "review_status": "pending", "after_event": {"event_display": {"display_label": "HW2"}}},
        ],
        "families": [
            {"id": 10, "canonical_label": "Homework", "raw_types": ["hw"]},
        ],
        "raw_types": [
            {"id": 100, "family_id": 10, "raw_type": "hw"},
        ],
        "manual_events": [
            {"entity_uid": "manual-1", "lifecycle": "active", "event_name": "HW 1"},
        ],
    }
    after = {
        "pending_change_count": 0,
        "event_entity_count": 5,
        "family_count": 2,
        "manual_event_count": 2,
        "changes": [
            {"id": 1, "review_status": "approved", "after_event": {"event_display": {"display_label": "HW1 revised"}}},
            {"id": 2, "review_status": "rejected", "after_event": {"event_display": {"display_label": "HW2"}}},
        ],
        "families": [
            {"id": 10, "canonical_label": "Homework", "raw_types": ["hw", "homework"]},
            {"id": 11, "canonical_label": "Project", "raw_types": ["project"]},
        ],
        "raw_types": [
            {"id": 100, "family_id": 11, "raw_type": "hw"},
        ],
        "manual_events": [
            {"entity_uid": "manual-1", "lifecycle": "removed", "event_name": "HW 1"},
            {"entity_uid": "manual-2", "lifecycle": "active", "event_name": "Project 1"},
        ],
    }

    diff = replay.diff_snapshots(before, after)

    assert diff["review_actions"]["approved"] == 1
    assert diff["review_actions"]["rejected"] == 1
    assert diff["review_actions"]["edited_then_approved"] == 1
    assert diff["family_actions"]["created_family_ids"] == [11]
    assert diff["family_actions"]["raw_type_relinks"] == 1
    assert diff["manual_actions"]["created_entity_uids"] == ["manual-2"]
    assert diff["manual_actions"]["removed_entity_uids"] == ["manual-1"]


def test_normalize_manual_events_drops_non_manual_support_rows() -> None:
    rows = [
        {"entity_uid": "ent-1", "manual_support": False, "event_name": "Approved HW"},
        {"entity_uid": "manual-1", "manual_support": True, "event_name": "Manual HW"},
        {"entity_uid": "manual-2", "event_name": "Legacy row without flag"},
    ]

    normalized = replay.normalize_manual_events(rows)

    assert [row["entity_uid"] for row in normalized] == ["manual-1", "manual-2"]


def test_aggregate_llm_usage_summaries_rolls_up_tokens_cache_and_latency() -> None:
    aggregate = replay.aggregate_llm_usage_summaries(
        [
            {
                "successful_call_count": 2,
                "usage_record_count": 2,
                "latency_ms_total": 900,
                "latency_ms_max": 500,
                "input_tokens": 1800,
                "cached_input_tokens": 1200,
                "cache_creation_input_tokens": 200,
                "output_tokens": 300,
                "reasoning_tokens": 100,
                "total_tokens": 2100,
                "protocols": {"responses": 2},
                "models": {"qwen3.5-plus": 2},
                "task_counts": {"gmail_purpose_mode_classify": 2},
            },
            {
                "successful_call_count": 1,
                "usage_record_count": 1,
                "latency_ms_total": 300,
                "latency_ms_max": 300,
                "input_tokens": 400,
                "cached_input_tokens": 100,
                "cache_creation_input_tokens": 0,
                "output_tokens": 50,
                "reasoning_tokens": 0,
                "total_tokens": 450,
                "protocols": {"chat_completions": 1},
                "models": {"qwen3.5-flash": 1},
                "task_counts": {"calendar_semantic_extract": 1},
            },
        ]
    )

    assert aggregate["successful_call_count"] == 3
    assert aggregate["input_tokens"] == 2200
    assert aggregate["cached_input_tokens"] == 1300
    assert aggregate["output_tokens"] == 350
    assert aggregate["total_tokens"] == 2550
    assert aggregate["avg_latency_ms"] == 400
    assert aggregate["latency_ms_max"] == 500
    assert aggregate["cache_hit_ratio"] == 0.5909
    assert aggregate["protocols"] == {"responses": 2, "chat_completions": 1}


def test_start_replay_writes_initial_state_and_credentials(tmp_path: Path, monkeypatch) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "plans": [
                    {
                        "semester": 1,
                        "phase_label": "WI26",
                        "batches": [
                            {"batch": 1, "global_batch": 1, "start_iso": "2026-01-03T10:00:00+00:00"},
                            {"batch": 2, "global_batch": 2, "start_iso": "2026-01-16T10:00:00+00:00"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(replay, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(replay, "start_fake_provider_with_bucket", lambda **kwargs: 4321)
    monkeypatch.setattr(replay, "ensure_fake_provider_ready", lambda **kwargs: None)
    primed_batches: list[dict] = []
    monkeypatch.setattr(replay, "set_fake_provider_batch", lambda **kwargs: primed_batches.append(dict(kwargs)))
    monkeypatch.setattr(replay, "build_api_client", lambda **kwargs: object())
    monkeypatch.setattr(replay, "ensure_authenticated_session", lambda *args, **kwargs: {"id": 55})
    created_source_ids = iter([{"source_id": 101}, {"source_id": 202}])
    monkeypatch.setattr(replay, "create_source", lambda client, payload: next(created_source_ids))
    monkeypatch.setattr(
        replay,
        "wait_for_bootstrap_syncs",
        lambda client, sources, timeout_seconds=replay.BOOTSTRAP_WARMUP_TIMEOUT_SECONDS: [
            {"source_id": 101, "request_id": "bootstrap-ics", "status": "SUCCEEDED", "elapsed_ms": 1234},
            {"source_id": 202, "request_id": "bootstrap-gmail", "status": "SUCCEEDED", "elapsed_ms": 2345},
        ],
    )
    monkeypatch.setattr(replay, "advance_until_checkpoint", lambda run_dir: run_dir)

    args = SimpleNamespace(
        public_api_base="http://127.0.0.1:8200",
        api_key="test-api-key",
        manifest=str(manifest_path),
        email_bucket="year_timeline_full_sim",
        ics_derived_set="year_timeline_smoke_16",
        fake_provider_host="127.0.0.1",
        fake_provider_port=8765,
        start_fake_provider=True,
        email="timeline@example.com",
        auth_password="password123",
    )

    run_dir = replay.start_replay(args)
    state = json.loads((run_dir / replay.STATE_FILE).read_text(encoding="utf-8"))
    creds = json.loads((run_dir / replay.RUN_CREDS_FILE).read_text(encoding="utf-8"))

    assert state["user_id"] == 55
    assert state["ics_source_id"] == 101
    assert state["gmail_source_id"] == 202
    assert state["fake_provider"]["pid"] == 4321
    assert state["bootstrap_results"] == [
        {"source_id": 101, "request_id": "bootstrap-ics", "status": "SUCCEEDED", "elapsed_ms": 1234},
        {"source_id": 202, "request_id": "bootstrap-gmail", "status": "SUCCEEDED", "elapsed_ms": 2345},
    ]
    assert creds["email"] == "timeline@example.com"
    assert primed_batches and primed_batches[0]["semester"] == 1 and primed_batches[0]["batch"] == 1
    assert (run_dir / replay.CHECKPOINTS_FILE).is_file()


def test_resume_replay_records_after_snapshot_and_diff(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    state = {
        "run_id": "run-1",
        "created_at": "2026-03-18T00:00:00+00:00",
        "public_api_base": "http://127.0.0.1:8200",
        "api_key": "test-api-key",
        "manifest_path": str(tmp_path / "manifest.json"),
        "email": "timeline@example.com",
        "auth_password": "password123",
        "user_id": 55,
        "ics_source_id": 101,
        "gmail_source_id": 202,
        "fake_provider": {"host": "127.0.0.1", "port": 8765, "pid": None, "started_by_harness": False},
        "checkpoints": [
            {
                "checkpoint_index": 0,
                "month_key": "2026-01",
                "global_batch": 2,
                "semester": 1,
                "batch": 2,
                "phase_label": "WI26",
                "scenario_id": "year-timeline-wi26",
                "transition_id": "round-01__to__round-02",
                "label": "2026-01 checkpoint @ batch 2",
            }
        ],
        "current_checkpoint_index": 0,
        "next_global_batch": 3,
        "awaiting_manual": True,
        "completed_batches": [1, 2],
        "batch_results": [],
        "checkpoint_summaries": [],
        "finished": False,
    }
    manifest = {
        "plans": [
            {
                "semester": 1,
                "phase_label": "WI26",
                "batches": [
                    {"batch": 1, "global_batch": 1, "start_iso": "2026-01-03T10:00:00+00:00"},
                    {"batch": 2, "global_batch": 2, "start_iso": "2026-01-16T10:00:00+00:00"},
                ],
            }
        ]
    }
    Path(state["manifest_path"]).write_text(json.dumps(manifest), encoding="utf-8")
    replay.write_json(run_dir / replay.STATE_FILE, state)
    replay.write_json(
        run_dir / "checkpoint-00-before.json",
        {
            "pending_change_count": 1,
            "event_entity_count": 1,
            "family_count": 1,
            "manual_event_count": 0,
            "changes": [{"id": 1, "review_status": "pending", "after_event": {"event_display": {"display_label": "HW1"}}}],
            "families": [{"id": 10, "canonical_label": "Homework", "raw_types": ["hw"]}],
            "raw_types": [{"id": 100, "family_id": 10, "raw_type": "hw"}],
            "manual_events": [],
        },
    )
    monkeypatch.setattr(replay, "build_api_client", lambda **kwargs: object())
    monkeypatch.setattr(replay, "ensure_authenticated_session", lambda *args, **kwargs: {"id": 55})
    monkeypatch.setattr(replay, "ensure_fake_provider_for_state", lambda state: None)
    monkeypatch.setattr(
        replay,
        "capture_backend_snapshot",
        lambda **kwargs: {
            "pending_change_count": 0,
            "event_entity_count": 2,
            "family_count": 2,
            "manual_event_count": 1,
            "changes": [{"id": 1, "review_status": "approved", "after_event": {"event_display": {"display_label": "HW1 revised"}}}],
            "families": [
                {"id": 10, "canonical_label": "Homework", "raw_types": ["hw"]},
                {"id": 11, "canonical_label": "Project", "raw_types": ["project"]},
            ],
            "raw_types": [{"id": 100, "family_id": 11, "raw_type": "hw"}],
            "manual_events": [{"entity_uid": "manual-1", "lifecycle": "active", "event_name": "Project 1"}],
        },
    )
    monkeypatch.setattr(replay, "advance_until_checkpoint", lambda run_dir: run_dir)

    result = replay.resume_replay(run_dir)
    updated_state = replay.load_state(result)
    after_snapshot = json.loads((run_dir / "checkpoint-00-after.json").read_text(encoding="utf-8"))

    assert updated_state["current_checkpoint_index"] == 1
    assert updated_state["awaiting_manual"] is False
    assert len(updated_state["checkpoint_summaries"]) == 1
    diff = updated_state["checkpoint_summaries"][0]["diff"]
    assert diff["review_actions"]["approved"] == 1
    assert diff["family_actions"]["created_family_ids"] == [11]
    assert diff["manual_actions"]["created_entity_uids"] == ["manual-1"]
    assert after_snapshot["family_count"] == 2


def test_build_report_rolls_up_batch_llm_usage(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    replay.write_json(
        run_dir / replay.STATE_FILE,
        {
            "run_id": "run-usage",
            "created_at": "2026-03-18T00:00:00+00:00",
            "user_id": 1,
            "email": "timeline@example.com",
            "ics_source_id": 10,
            "gmail_source_id": 11,
            "awaiting_manual": True,
            "finished": False,
            "bootstrap_results": [
                {
                    "source_id": 10,
                    "source_kind": "calendar",
                    "provider": "ics",
                    "request_id": "bootstrap-ics",
                    "status": "SUCCEEDED",
                    "applied": True,
                    "elapsed_ms": 3100,
                    "llm_usage": {
                        "successful_call_count": 3,
                        "usage_record_count": 3,
                        "latency_ms_total": 1200,
                        "latency_ms_max": 500,
                        "input_tokens": 900,
                        "cached_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                        "output_tokens": 90,
                        "reasoning_tokens": 0,
                        "total_tokens": 990,
                        "protocols": {"chat_completions": 3},
                        "models": {"qwen3.5-flash": 3},
                        "task_counts": {"calendar_semantic_extract": 3},
                    },
                }
            ],
            "completed_batches": [1],
            "checkpoint_summaries": [],
            "batch_results": [
                {
                    "global_batch": 1,
                    "ics_applied": True,
                    "gmail_applied": True,
                    "ics_elapsed_ms": 2500,
                    "gmail_elapsed_ms": 5200,
                    "ics_llm_usage": {
                        "successful_call_count": 1,
                        "usage_record_count": 1,
                        "latency_ms_total": 300,
                        "latency_ms_max": 300,
                        "input_tokens": 500,
                        "cached_input_tokens": 100,
                        "cache_creation_input_tokens": 0,
                        "output_tokens": 70,
                        "reasoning_tokens": 0,
                        "total_tokens": 570,
                        "protocols": {"chat_completions": 1},
                        "models": {"qwen3.5-flash": 1},
                        "task_counts": {"calendar_semantic_extract": 1},
                    },
                    "gmail_llm_usage": {
                        "successful_call_count": 2,
                        "usage_record_count": 2,
                        "latency_ms_total": 900,
                        "latency_ms_max": 500,
                        "input_tokens": 1800,
                        "cached_input_tokens": 1200,
                        "cache_creation_input_tokens": 200,
                        "output_tokens": 300,
                        "reasoning_tokens": 100,
                        "total_tokens": 2100,
                        "protocols": {"responses": 2},
                        "models": {"qwen3.5-plus": 2},
                        "task_counts": {"gmail_purpose_mode_classify": 2},
                    },
                }
            ],
        },
    )

    report = replay.build_report(run_dir)

    assert report["bootstrap"]["completed_request_count"] == 1
    assert report["bootstrap"]["avg_elapsed_ms"] == 3100
    assert report["bootstrap"]["llm_usage"]["input_tokens"] == 900
    assert report["replay"]["llm_usage"]["overall"]["successful_call_count"] == 3
    assert report["avg_ics_elapsed_ms"] == 2500
    assert report["avg_gmail_elapsed_ms"] == 5200
    assert report["llm_usage"]["overall"]["successful_call_count"] == 6
    assert report["llm_usage"]["overall"]["cached_input_tokens"] == 1300
    assert report["llm_usage"]["gmail"]["input_tokens"] == 1800
    assert report["llm_usage"]["ics"]["input_tokens"] == 500


def test_wait_for_source_bootstrap_sync_prefers_scheduler_request(monkeypatch) -> None:
    client = object()
    source = {
        "source_id": 12,
        "source_kind": "email",
        "provider": "gmail",
        "created_at": "2026-03-18T00:00:00+00:00",
        "updated_at": "2026-03-18T00:00:00+00:00",
    }
    monkeypatch.setattr(replay, "find_latest_scheduler_sync_request_id_for_source", lambda **kwargs: "scheduler-1")
    monkeypatch.setattr(
        replay,
        "get_source_row",
        lambda client_obj, source_id: {
            "source_id": source_id,
            "sync_state": "idle",
            "runtime_state": "active",
            "last_polled_at": "2026-03-18T00:00:04+00:00",
            "active_request_id": None,
        },
    )
    monkeypatch.setattr(
        replay,
        "request_json",
        lambda client_obj, method, path, json_payload=None: (
            {
                "request_id": "scheduler-1",
                "status": "SUCCEEDED",
                "applied": True,
                "created_at": "2026-03-18T00:00:00+00:00",
                "updated_at": "2026-03-18T00:00:03+00:00",
                "applied_at": "2026-03-18T00:00:04+00:00",
                "elapsed_ms": 4000,
                "stage": "completed",
                "substage": "apply_completed",
                "stage_updated_at": "2026-03-18T00:00:04+00:00",
                "metadata": {
                    "llm_usage_summary": {
                        "successful_call_count": 2,
                        "input_tokens": 100,
                        "cached_input_tokens": 40,
                        "cache_creation_input_tokens": 20,
                        "output_tokens": 10,
                        "reasoning_tokens": 0,
                        "total_tokens": 110,
                        "latency_ms_total": 200,
                        "latency_ms_max": 120,
                        "usage_record_count": 2,
                        "protocols": {"chat_completions": 2},
                        "models": {"qwen3.5-flash": 2},
                        "task_counts": {"gmail_purpose_mode_classify": 2},
                    }
                },
                "connector_result": {"provider": "gmail", "status": "NO_CHANGE", "records_count": 0},
                "progress": {"phase": "completed", "updated_at": "2026-03-18T00:00:04+00:00"},
            }
            if path == "/sync-requests/scheduler-1"
            else {
                "source_id": 12,
                "active_request_id": None,
                "bootstrap": {
                    "request_id": "scheduler-1",
                    "phase": "bootstrap",
                    "status": "SUCCEEDED",
                    "applied": True,
                    "created_at": "2026-03-18T00:00:00+00:00",
                    "updated_at": "2026-03-18T00:00:03+00:00",
                    "applied_at": "2026-03-18T00:00:04+00:00",
                    "elapsed_ms": 4000,
                    "stage": "completed",
                    "substage": "apply_completed",
                    "stage_updated_at": "2026-03-18T00:00:04+00:00",
                    "llm_usage": {
                        "successful_call_count": 2,
                        "input_tokens": 100,
                        "cached_input_tokens": 40,
                        "cache_creation_input_tokens": 20,
                        "output_tokens": 10,
                        "reasoning_tokens": 0,
                        "total_tokens": 110,
                        "latency_ms_total": 200,
                        "latency_ms_max": 120,
                        "usage_record_count": 2,
                        "protocols": {"chat_completions": 2},
                        "models": {"qwen3.5-flash": 2},
                        "task_counts": {"gmail_purpose_mode_classify": 2},
                    },
                    "connector_result": {"provider": "gmail", "status": "NO_CHANGE", "records_count": 0},
                    "progress": {"phase": "completed", "updated_at": "2026-03-18T00:00:04+00:00"},
                },
            }
        ),
    )

    result = replay.wait_for_source_bootstrap_sync(client, source=source, timeout_seconds=1.0)

    assert result["request_id"] == "scheduler-1"
    assert result["status"] == "SUCCEEDED"
    assert result["elapsed_ms"] == 4000
    assert result["llm_usage"]["successful_call_count"] == 2
    assert result["stage"] == "completed"
    assert result["applied"] is True


def test_enrich_bootstrap_results_from_api_replaces_placeholder_rows(monkeypatch) -> None:
    state = {
        "public_api_base": "http://127.0.0.1:8200",
        "api_key": "test-api-key",
        "email": "timeline@example.com",
        "auth_password": "password123",
    }
    bootstrap_results = [
        {
            "source_id": 12,
            "source_kind": "email",
            "provider": "gmail",
            "request_id": None,
            "status": "unknown",
            "applied": False,
            "elapsed_ms": None,
            "llm_usage": None,
            "connector_result": None,
            "created_at": "2026-03-18T00:00:00+00:00",
            "updated_at": "2026-03-18T00:00:00+00:00",
        }
    ]
    class _Client:
        def post(self, path, json):  # noqa: ANN001
            assert path == "/auth/login"
            return SimpleNamespace(status_code=200)

    monkeypatch.setattr(replay, "build_api_client", lambda **kwargs: _Client())
    monkeypatch.setattr(
        replay,
        "request_json",
        lambda client_obj, method, path, json_payload=None: {
            "source_id": 12,
            "bootstrap": {
                "request_id": "scheduler-1",
                "status": "SUCCEEDED",
                "stage": "completed",
                "substage": "apply_completed",
                "stage_updated_at": "2026-03-18T00:00:04+00:00",
                "applied": True,
                "elapsed_ms": 4000,
                "llm_usage": {
                    "successful_call_count": 2,
                    "input_tokens": 100,
                    "cached_input_tokens": 40,
                    "cache_creation_input_tokens": 20,
                    "output_tokens": 10,
                    "reasoning_tokens": 0,
                    "total_tokens": 110,
                    "latency_ms_total": 200,
                    "latency_ms_max": 120,
                    "usage_record_count": 2,
                    "protocols": {"chat_completions": 2},
                    "models": {"qwen3.5-flash": 2},
                    "task_counts": {"gmail_purpose_mode_classify": 2},
                },
                "connector_result": {"provider": "gmail", "status": "NO_CHANGE", "records_count": 0},
                "created_at": "2026-03-18T00:00:00+00:00",
                "updated_at": "2026-03-18T00:00:03+00:00",
                "applied_at": "2026-03-18T00:00:04+00:00",
                "progress": {"phase": "completed", "updated_at": "2026-03-18T00:00:04+00:00"},
            },
        },
    )

    enriched = replay.enrich_bootstrap_results_from_api(state=state, bootstrap_results=bootstrap_results)

    assert enriched[0]["request_id"] == "scheduler-1"
    assert enriched[0]["status"] == "SUCCEEDED"
    assert enriched[0]["stage"] == "completed"
    assert enriched[0]["applied"] is True
    assert enriched[0]["elapsed_ms"] == 4000
    assert enriched[0]["llm_usage"]["successful_call_count"] == 2


def test_ensure_authenticated_session_logs_in_existing_user_before_register(monkeypatch) -> None:
    calls: list[tuple[str, str, object | None]] = []

    class _Client:
        def get(self, path):  # noqa: ANN001
            calls.append(("GET", path, None))
            assert path == "/auth/session"
            return SimpleNamespace(status_code=401, text='{"authenticated":false}')

        def post(self, path, json):  # noqa: ANN001
            calls.append(("POST", path, json))
            if path == "/auth/login":
                return SimpleNamespace(status_code=200, text='{"authenticated":true}')
            raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(
        replay,
        "request_json",
        lambda client_obj, method, path, json_payload=None: {"user": {"id": 123, "email": "timeline@example.com"}},
    )

    user = replay.ensure_authenticated_session(_Client(), email="timeline@example.com", password="password123")

    assert user["id"] == 123
    assert [path for _, path, _ in calls] == ["/auth/session", "/auth/login"]
    assert all(path != "/auth/register" for _, path, _ in calls)


def test_ensure_authenticated_session_registers_when_login_fails(monkeypatch) -> None:
    calls: list[tuple[str, str, object | None]] = []

    class _Client:
        def get(self, path):  # noqa: ANN001
            calls.append(("GET", path, None))
            assert path == "/auth/session"
            return SimpleNamespace(status_code=401, text='{"authenticated":false}')

        def post(self, path, json):  # noqa: ANN001
            calls.append(("POST", path, json))
            if path == "/auth/login":
                return SimpleNamespace(status_code=401, text='{"detail":"invalid credentials"}')
            if path == "/auth/register":
                return SimpleNamespace(status_code=201, text='{"authenticated":true}')
            raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(
        replay,
        "request_json",
        lambda client_obj, method, path, json_payload=None: {"user": {"id": 456, "email": "timeline@example.com"}},
    )

    user = replay.ensure_authenticated_session(_Client(), email="timeline@example.com", password="password123")

    assert user["id"] == 456
    assert [path for _, path, _ in calls] == ["/auth/session", "/auth/login", "/auth/register"]


def test_wait_sync_success_allows_queued_request_while_active_source_request_progresses(monkeypatch) -> None:
    heartbeat = {"target": 0, "active": 0, "source": 0, "time": 0.0}

    def fake_monotonic() -> float:
        heartbeat["time"] += 1.0
        return heartbeat["time"]

    def fake_sleep(_seconds: float) -> None:
        return None

    def fake_request_json(client, method, path, json_payload=None):  # noqa: ANN001
        del client, method, json_payload
        if path == "/sync-requests/replay-1":
            heartbeat["target"] += 1
            if heartbeat["target"] < 3:
                return {
                    "request_id": "replay-1",
                    "source_id": 10,
                    "status": "QUEUED",
                    "updated_at": "2026-03-18T00:00:00+00:00",
                    "progress": {"phase": "queued", "current": None, "total": None, "detail": "waiting"},
                    "applied": False,
                }
            return {
                "request_id": "replay-1",
                "source_id": 10,
                "status": "SUCCEEDED",
                "updated_at": "2026-03-18T00:00:04+00:00",
                "applied": True,
                "applied_at": "2026-03-18T00:00:05+00:00",
                "progress": {"phase": "applying", "current": 1, "total": 1, "detail": "done"},
            }
        if path == "/sync-requests/bootstrap-1":
            heartbeat["active"] += 1
            return {
                "request_id": "bootstrap-1",
                "source_id": 10,
                "status": "RUNNING",
                "updated_at": f"2026-03-18T00:00:0{heartbeat['active']}+00:00",
                "progress": {"phase": "gmail_bootstrap_fetch", "current": heartbeat["active"] * 10, "total": 100, "detail": "advancing"},
                "applied": False,
                "llm_usage": {"successful_call_count": heartbeat["active"]},
            }
        raise AssertionError(path)

    def fake_get_source_row(client, *, source_id):  # noqa: ANN001
        del client
        heartbeat["source"] += 1
        return {
            "source_id": source_id,
            "sync_state": "running",
            "runtime_state": "running",
            "active_request_id": "bootstrap-1",
        }

    monkeypatch.setattr(replay.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(replay.time, "sleep", fake_sleep)
    monkeypatch.setattr(replay, "request_json", fake_request_json)
    monkeypatch.setattr(replay, "get_source_row", fake_get_source_row)
    monkeypatch.setattr(replay, "SYNC_STALL_TIMEOUT_SECONDS", 3.0)

    payload = replay.wait_sync_success(object(), request_id="replay-1", source_id=10, timeout_seconds=20.0)

    assert payload["status"] == "SUCCEEDED"
    assert payload["applied"] is True


def test_wait_sync_success_raises_when_progress_is_stalled(monkeypatch) -> None:
    clock = {"time": 0.0}

    def fake_monotonic() -> float:
        clock["time"] += 2.0
        return clock["time"]

    def fake_sleep(_seconds: float) -> None:
        return None

    def fake_request_json(client, method, path, json_payload=None):  # noqa: ANN001
        del client, method, json_payload
        return {
            "request_id": "replay-stuck",
            "source_id": 10,
            "status": "RUNNING",
            "updated_at": "2026-03-18T00:00:00+00:00",
            "progress": {"phase": "running", "current": None, "total": None, "detail": "still running"},
            "applied": False,
        }

    def fake_get_source_row(client, *, source_id):  # noqa: ANN001
        del client
        return {
            "source_id": source_id,
            "sync_state": "running",
            "runtime_state": "running",
            "active_request_id": "replay-stuck",
        }

    monkeypatch.setattr(replay.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(replay.time, "sleep", fake_sleep)
    monkeypatch.setattr(replay, "request_json", fake_request_json)
    monkeypatch.setattr(replay, "get_source_row", fake_get_source_row)
    monkeypatch.setattr(replay, "SYNC_STALL_TIMEOUT_SECONDS", 3.0)

    with pytest.raises(replay.ReplayFailure, match="sync stalled"):
        replay.wait_sync_success(object(), request_id="replay-stuck", source_id=10, timeout_seconds=20.0)


def test_sync_payload_marker_includes_progress_and_usage_heartbeat() -> None:
    payload = {
        "request_id": "req-1",
        "status": "RUNNING",
        "updated_at": "2026-03-18T00:00:05+00:00",
        "progress": {"phase": "calendar_parsing", "current": 2, "total": 4, "detail": "advancing", "updated_at": "2026-03-18T00:00:06+00:00"},
        "connector_result": {"status": "CHANGED", "records_count": 5},
        "llm_usage": {"successful_call_count": 3, "last_observed_at": "2026-03-18T00:00:04+00:00"},
    }

    marker = replay._sync_payload_marker(payload)

    assert marker[0] == "req-1"
    assert marker[3] == "calendar_parsing"
    assert marker[4] == 2
    assert marker[7] == "CHANGED"
    assert marker[9] == "2026-03-18T00:00:04+00:00"
    assert marker[10] == "2026-03-18T00:00:06+00:00"


def test_build_sync_timeout_message_includes_diagnosis() -> None:
    payload = {
        "request_id": "req-1",
        "source_id": 42,
        "status": "RUNNING",
        "updated_at": (datetime.now(UTC) - timedelta(seconds=90)).isoformat(),
        "progress": {"phase": "calendar_parsing", "label": "Parsing calendar events"},
    }
    source_row = {
        "sync_state": "running",
        "runtime_state": "running",
        "active_request_id": "req-1",
    }

    message = replay._build_sync_timeout_message(payload=payload, source_row=source_row, phase="bootstrap")

    assert "bootstrap sync stalled" in message
    assert "diagnosis=worker_still_active_or_not_finishing" in message
