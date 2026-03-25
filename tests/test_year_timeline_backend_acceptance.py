from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import scripts.run_year_timeline_backend_acceptance as acceptance


def test_classify_runtime_failure_parses_request_and_source() -> None:
    details = acceptance.classify_runtime_failure(
        "replay sync stalled request_id=abcd1234ef source_id=22 status=RUNNING"
    )

    assert details.classification == "runtime"
    assert details.request_id == "abcd1234ef"
    assert details.source_id == 22


def test_build_checkpoint_entry_marks_family_or_manual_as_confusing() -> None:
    entry = acceptance.build_checkpoint_entry(
        checkpoint={"label": "2026-04 checkpoint @ batch 1"},
        checkpoint_index=6,
        pending_changes=[{"id": 1}],
        families=[{"id": 10}],
        actions=[
            {"kind": "approve", "change_id": 1, "label": "HW1"},
            {"kind": "family_rename", "family_id": 10, "canonical_label": "Homework"},
        ],
        sources=[
            {
                "source_id": 1,
                "provider": "gmail",
                "line": "- Source 1 gmail: runtime=active sync=idle",
                "runtime_issue": False,
            }
        ],
        elapsed_seconds=12.5,
    )

    assert entry["rating"] == "费解"
    assert entry["knows_what_is_happening"] is False
    assert entry["blocker"] is None


def test_finalize_acceptance_report_rolls_summary(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / acceptance.replay.STATE_FILE).write_text(
        json.dumps(
            {
                "run_id": "acceptance-run",
                "created_at": "2026-03-18T00:00:00+00:00",
                "finished": True,
                "checkpoints": [],
                "checkpoint_summaries": [],
            }
        ),
        encoding="utf-8",
    )
    report = {
        "run_id": "acceptance-run",
        "checkpoints": [
            {"rating": "清晰", "elapsed_seconds": 10.0},
            {"rating": "费解", "elapsed_seconds": 20.0},
            {"rating": "费解", "elapsed_seconds": 30.0},
        ],
    }
    monkeypatch.setattr(
        acceptance.replay,
        "build_report",
        lambda run_dir_arg: {
            "run_id": "acceptance-run",
            "bootstrap": {"completed_request_count": 2},
            "replay": {"completed_batch_count": 12},
            "llm_usage": {"overall": {"total_tokens": 123}},
        },
    )

    acceptance.finalize_acceptance_report(run_dir, report)

    saved = json.loads((run_dir / acceptance.ACCEPTANCE_REPORT_FILE).read_text(encoding="utf-8"))
    assert saved["status"] == "finished"
    assert saved["summary"]["checkpoint_count"] == 3
    assert saved["summary"]["average_checkpoint_seconds"] == 20.0
    assert saved["summary"]["rating_counts"] == {"清晰": 1, "费解": 2}


def test_title_case_label_normalizes_lowercase_family_label() -> None:
    assert acceptance.title_case_label("lab report") == "Lab Report"
    assert acceptance.title_case_label("take-home final") == "Take-Home Final"


def test_try_resume_idle_replay_advances_saved_run(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / acceptance.replay.RUN_CREDS_FILE).write_text(
        json.dumps({"ics_source_id": 10, "gmail_source_id": 11}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        acceptance.replay,
        "load_state",
        lambda _run_dir: {"awaiting_manual": False, "finished": False},
    )
    monkeypatch.setattr(
        acceptance,
        "api_json_list",
        lambda _client, _path: [
            {"source_id": 10, "runtime_state": "active", "sync_state": "idle"},
            {"source_id": 11, "runtime_state": "active", "sync_state": "idle"},
        ],
    )
    advanced: list[Path] = []
    monkeypatch.setattr(acceptance.replay, "advance_until_checkpoint", lambda path: advanced.append(path) or path)
    monkeypatch.setattr(
        acceptance.replay,
        "build_report",
        lambda _run_dir: {"bootstrap": {}, "replay": {}, "llm_usage": {}},
    )

    report = {"checkpoints": []}
    resumed = acceptance.try_resume_idle_replay(run_dir=run_dir, client=object(), report=report)  # type: ignore[arg-type]

    assert resumed is True
    assert advanced == [run_dir]


def test_build_client_from_run_rejects_user_id_drift(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / acceptance.replay.RUN_CREDS_FILE).write_text(
        json.dumps(
            {
                "public_api_base": "http://127.0.0.1:8200",
                "api_key": "test-api-key",
                "email": "timeline@example.com",
                "password": "password123",
                "user_id": 7,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(acceptance.replay, "build_api_client", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(
        acceptance.replay,
        "ensure_authenticated_session",
        lambda *args, **kwargs: {"id": 9, "email": "timeline@example.com"},
    )

    try:
        acceptance.build_client_from_run(run_dir)
    except RuntimeError as exc:
        assert "expected user_id=7 got user_id=9" in str(exc)
    else:
        raise AssertionError("expected runtime drift detection failure")


def test_try_resume_idle_replay_records_runtime_failure(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / acceptance.replay.RUN_CREDS_FILE).write_text(
        json.dumps({"ics_source_id": 10, "gmail_source_id": 11}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        acceptance.replay,
        "load_state",
        lambda _run_dir: {"awaiting_manual": False, "finished": False},
    )
    monkeypatch.setattr(
        acceptance,
        "api_json_list",
        lambda _client, _path: [
            {"source_id": 10, "runtime_state": "active", "sync_state": "idle"},
            {"source_id": 11, "runtime_state": "active", "sync_state": "idle"},
        ],
    )
    monkeypatch.setattr(
        acceptance.replay,
        "advance_until_checkpoint",
        lambda _run_dir: (_ for _ in ()).throw(
            RuntimeError("replay sync stalled request_id=deadbeef source_id=10 status=RUNNING")
        ),
    )
    monkeypatch.setattr(acceptance, "wait_for_request_terminal", lambda *args, **kwargs: False)

    report = {"checkpoints": []}
    try:
        acceptance.try_resume_idle_replay(run_dir=run_dir, client=object(), report=report)  # type: ignore[arg-type]
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected runtime failure to propagate")

    saved = report["runtime_failures"]
    assert len(saved) == 1
    assert saved[0]["classification"] == "runtime"
    assert saved[0]["request_id"] == "deadbeef"


def test_advance_with_runtime_recording_records_multiple_runtime_failures(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    calls = {"count": 0}

    def fake_advance(_run_dir):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("replay sync stalled request_id=deadbeef source_id=10 status=RUNNING")
        if calls["count"] == 2:
            raise RuntimeError("replay sync stalled request_id=cafebabe source_id=11 status=RUNNING")
        return _run_dir

    monkeypatch.setattr(acceptance.replay, "advance_until_checkpoint", fake_advance)
    monkeypatch.setattr(acceptance, "wait_for_request_terminal", lambda *args, **kwargs: True)
    monkeypatch.setattr(acceptance, "save_acceptance_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(acceptance, "append_note", lambda *args, **kwargs: None)

    report = {"runtime_failures": []}
    acceptance.advance_with_runtime_recording(run_dir=run_dir, report=report, max_retries=3)

    assert calls["count"] == 3
    assert [row["request_id"] for row in report["runtime_failures"]] == ["deadbeef", "cafebabe"]


def test_resume_to_next_checkpoint_ignores_no_manual_checkpoint_race(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    monkeypatch.setattr(
        acceptance.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="run is not waiting at a manual checkpoint"),
    )

    report = {"runtime_failures": []}
    acceptance.resume_to_next_checkpoint(run_dir, report)

    assert report["runtime_failures"] == []


def test_handle_checkpoint_upserts_existing_checkpoint_entry(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    monkeypatch.setattr(acceptance, "api_json_list", lambda _client, _path: [])
    monkeypatch.setattr(acceptance, "gather_source_context", lambda **kwargs: [])
    monkeypatch.setattr(acceptance, "api_json", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(acceptance, "save_acceptance_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(acceptance, "append_note", lambda *args, **kwargs: None)

    report = {
        "checkpoints": [
            {
                "checkpoint_index": 0,
                "label": "old",
                "rating": "清晰",
            }
        ]
    }
    operator_state = {
        "rejections_done": 0,
        "edits_done": 0,
        "family_renamed": True,
        "family_relinked": True,
        "family_created_id": None,
        "manual_created": True,
        "manual_updated": True,
        "manual_deleted": True,
        "manual_entity_uid": None,
    }
    state = {"current_checkpoint_index": 0, "checkpoints": [{"label": "new"}]}

    acceptance.handle_checkpoint(
        run_dir=run_dir,
        client=SimpleNamespace(),
        report=report,
        operator_state=operator_state,
        state=state,
    )

    assert len(report["checkpoints"]) == 1
    assert report["checkpoints"][0]["label"] == "new"


def test_handle_checkpoint_does_not_reject_same_change_it_approved(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    monkeypatch.setattr(
        acceptance,
        "api_json_list",
        lambda _client, path: (
            [
                {
                    "id": 1,
                    "change_type": "updated",
                    "after_event": {"due_time": "11:07:00"},
                    "after_display": {"display_label": "Quiz 6"},
                }
            ]
            if path.startswith("/changes")
            else []
        ),
    )
    monkeypatch.setattr(acceptance, "gather_source_context", lambda **kwargs: [])
    recorded_calls: list[tuple[str, str, dict | None]] = []

    def fake_api_json(_client, method: str, path: str, payload=None):
        recorded_calls.append((method, path, payload))
        return {"ok": True}

    monkeypatch.setattr(acceptance, "api_json", fake_api_json)
    monkeypatch.setattr(acceptance, "save_acceptance_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(acceptance, "append_note", lambda *args, **kwargs: None)

    report = {"checkpoints": []}
    operator_state = {
        "rejections_done": 0,
        "edits_done": 0,
        "family_renamed": True,
        "family_relinked": True,
        "family_created_id": None,
        "manual_created": False,
        "manual_updated": False,
        "manual_deleted": False,
        "manual_entity_uid": None,
    }
    state = {"current_checkpoint_index": 0, "checkpoints": [{"label": "cp-0"}]}

    acceptance.handle_checkpoint(
        run_dir=run_dir,
        client=SimpleNamespace(),
        report=report,
        operator_state=operator_state,
        state=state,
    )

    decision_calls = [call for call in recorded_calls if call[1].endswith("/decisions")]
    assert len(decision_calls) == 1
    assert decision_calls[0][2]["decision"] == "approve"


def test_supports_proposal_edit_only_allows_created_or_due_changed() -> None:
    assert acceptance.supports_proposal_edit({"change_type": "created"}) is True
    assert acceptance.supports_proposal_edit({"change_type": "due_changed"}) is True
    assert acceptance.supports_proposal_edit({"change_type": "updated"}) is False
