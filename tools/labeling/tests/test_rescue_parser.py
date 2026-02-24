from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.labeling.normalize_labeled import NormalizeConfig, run_normalization_pipeline

ROOT_DIR = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT_DIR / "tools" / "labeling" / "schema" / "email_label.json"


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def make_rescue_candidate(email_id: str) -> dict[str, Any]:
    return {
        "email_id": email_id,
        "label": "KEEP",
        "confidence": 0.55,
        "reasons": ["class got moved maybe"],
        "course_hints": ["CSE 101"],
        "event_type": "weird_event",  # unmapped -> null -> rescue candidate
        "action_items": [],
        "raw_extract": {"deadline_text": None, "time_text": None, "location_text": None},
        "notes": None,
    }


def build_config(tmp_path: Path) -> NormalizeConfig:
    return NormalizeConfig(
        input_path=tmp_path / "labeled.jsonl",
        output_path=tmp_path / "normalized.jsonl",
        errors_path=tmp_path / "normalize_errors.jsonl",
        dedupe=False,
        max_action_items=5,
        rescue_llm=True,
        rescue_out_path=tmp_path / "rescue_applied.jsonl",
        timezone="America/Los_Angeles",
        schema_path=SCHEMA_PATH,
    )


def test_rescue_parser_applies_updates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    write_jsonl(build_config(tmp_path).input_path, [make_rescue_candidate("rescue-1")])

    captured: list[dict[str, Any]] = []

    class FakeResponse:
        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, timeout: Any) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        async def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
            captured.append({"url": url, "json": json, "headers": headers})
            body = "rescue-1\tKEEP\t0.91\tschedule_change\tCSE 101,WI26\trescued"
            return FakeResponse(body)

    monkeypatch.setattr("tools.labeling.normalize_labeled.httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setenv("RESCUE_LLM_BASE_URL", "https://example-rescue.local")
    monkeypatch.setenv("RESCUE_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("RESCUE_LLM_MODEL", "rescue-model")
    monkeypatch.setenv("RESCUE_LLM_BATCH_SIZE", "10")
    monkeypatch.setenv("RESCUE_LLM_CONCURRENCY", "2")

    config = build_config(tmp_path)
    summary = run_normalization_pipeline(config)
    normalized = read_jsonl(config.output_path)
    rescue_applied = read_jsonl(config.rescue_out_path)

    assert summary["rescue_enabled"] is True
    assert summary["rescue_candidate_count"] == 1
    assert summary["rescue_applied_count"] == 1
    assert len(captured) == 1
    assert captured[0]["url"] == "https://example-rescue.local/label"
    assert captured[0]["json"]["model"] == "rescue-model"
    assert isinstance(captured[0]["json"]["inputs"], list)
    assert isinstance(captured[0]["json"]["inputs"][0], str)

    assert normalized[0]["event_type"] == "schedule_change"
    assert normalized[0]["label"] == "KEEP"
    assert normalized[0]["confidence"] == 0.91
    assert "WI26" in normalized[0]["course_hints"]
    assert rescue_applied[0]["email_id"] == "rescue-1"
    assert rescue_applied[0]["after_event_type"] == "schedule_change"


def test_rescue_line_count_mismatch_marks_failed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    write_jsonl(build_config(tmp_path).input_path, [make_rescue_candidate("rescue-a"), make_rescue_candidate("rescue-b")])

    class FakeResponse:
        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, timeout: Any) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        async def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
            _ = (url, json, headers)
            return FakeResponse("only-one-line\tKEEP\t0.8\tdeadline\tCSE 100\tok")

    monkeypatch.setattr("tools.labeling.normalize_labeled.httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setenv("RESCUE_LLM_BASE_URL", "https://example-rescue.local")
    monkeypatch.setenv("RESCUE_LLM_MODEL", "rescue-model")

    config = build_config(tmp_path)
    summary = run_normalization_pipeline(config)
    error_rows = read_jsonl(config.errors_path)
    rescue_applied = read_jsonl(config.rescue_out_path)

    assert summary["rescue_candidate_count"] == 2
    assert summary["rescue_applied_count"] == 0
    assert rescue_applied == []
    assert any(item["error_type"] == "rescue_failed" for item in error_rows)


def test_rescue_invalid_line_fields_marks_failed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    write_jsonl(build_config(tmp_path).input_path, [make_rescue_candidate("rescue-invalid")])

    class FakeResponse:
        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, timeout: Any) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        async def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
            _ = (url, json, headers)
            # invalid label + invalid event_type should be rejected by parser
            return FakeResponse("rescue-invalid\tMAYBE\t2.4\tunknown_type\tCSE 100\tbad line")

    monkeypatch.setattr("tools.labeling.normalize_labeled.httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setenv("RESCUE_LLM_BASE_URL", "https://example-rescue.local")
    monkeypatch.setenv("RESCUE_LLM_MODEL", "rescue-model")

    config = build_config(tmp_path)
    summary = run_normalization_pipeline(config)
    normalized = read_jsonl(config.output_path)
    errors = read_jsonl(config.errors_path)

    assert summary["rescue_candidate_count"] == 1
    assert summary["rescue_applied_count"] == 0
    assert normalized[0]["event_type"] is None
    assert any(item["error_type"] == "rescue_failed" for item in errors)
