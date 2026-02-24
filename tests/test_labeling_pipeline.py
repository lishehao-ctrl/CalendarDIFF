from __future__ import annotations

import asyncio
import json
import mailbox
import sys
from email.message import EmailMessage
from pathlib import Path

import pytest

from tools import label_emails as cli
from tools.labeling.label_emails_async import LabelingConfig, run_labeling_pipeline


ROOT_DIR = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT_DIR / "tools" / "labeling" / "schema" / "email_label.json"
PROMPT_PATH = ROOT_DIR / "tools" / "labeling" / "prompts" / "system.txt"


def _make_mbox(path: Path, count: int = 1) -> None:
    mbox_obj = mailbox.mbox(str(path), create=True)
    try:
        for idx in range(1, count + 1):
            msg = EmailMessage()
            msg["From"] = "instructor@school.edu"
            msg["To"] = "student@school.edu"
            msg["Subject"] = f"Course update #{idx}"
            msg["Date"] = "Tue, 20 Feb 2026 10:00:00 -0800"
            msg["Message-ID"] = f"<msg-{idx:03d}@example.edu>"
            msg.set_content(f"Homework {idx} deadline moved to Sunday 11:59 PM.")
            mbox_obj.add(msg)
        mbox_obj.flush()
    finally:
        mbox_obj.close()


def _valid_label(email_id: str, label: str = "KEEP", confidence: float = 0.84) -> dict[str, object]:
    return {
        "email_id": email_id,
        "label": label,
        "confidence": confidence,
        "reasons": ["deadline changed"],
        "course_hints": ["CSE 100"],
        "event_type": "deadline" if label == "KEEP" else None,
        "action_items": (
            [{"action": "Submit Homework", "due_iso": "2026-02-22T23:59:00-08:00", "where": "Gradescope"}]
            if label == "KEEP"
            else []
        ),
        "raw_extract": {
            "deadline_text": "moved to Sunday 11:59 PM",
            "time_text": "Sunday 11:59 PM",
            "location_text": "Gradescope",
        },
        "notes": None,
    }


def _build_config(tmp_path: Path, mbox_path: Path, out_path: Path) -> LabelingConfig:
    return LabelingConfig(
        openai_api_key="sk-test",
        openai_model="gpt-5.3-codex",
        openai_base_url="https://code.respyun.com/v1",
        input_mbox=mbox_path,
        labeled_jsonl=out_path,
        error_jsonl=tmp_path / "label_errors.jsonl",
        workers=2,
        max_retries=0,
        max_body_chars=12000,
        max_output_tokens=600,
        temperature=0.2,
        max_records=None,
        dry_run=False,
        prompt_path=PROMPT_PATH,
        schema_path=SCHEMA_PATH,
    )


def _read_jsonl_rows(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_valid_json_and_request_shape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mbox_path = tmp_path / "emails.mbox"
    out_path = tmp_path / "labeled.jsonl"
    _make_mbox(mbox_path, count=1)

    api_calls: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, payload: str) -> None:
            self.output_text = payload
            self.model = "fake-model"

    class FakeResponses:
        async def create(self, **kwargs: object) -> FakeResponse:
            api_calls.append(dict(kwargs))
            return FakeResponse(json.dumps(_valid_label("msg-001@example.edu")))

    class FakeClient:
        def __init__(self, api_key: str, base_url: str | None = None) -> None:
            self.api_key = api_key
            self.base_url = base_url
            self.responses = FakeResponses()

    monkeypatch.setattr("tools.labeling.label_emails_async.AsyncOpenAI", FakeClient)
    summary = asyncio.run(run_labeling_pipeline(_build_config(tmp_path, mbox_path, out_path)))

    assert summary["processed"] == 1
    assert summary["success_count"] == 1
    assert summary["invalid_dropped_count"] == 0
    assert summary["error_count"] == 0
    assert len(api_calls) == 1

    call = api_calls[0]
    assert call.get("store") is False
    assert "text" not in call
    assert "response_format" not in call
    assert call.get("input")
    first_input = call["input"][0]
    assert first_input["role"] == "user"
    assert isinstance(first_input["content"], list)
    assert first_input["content"][0]["type"] == "input_text"
    assert isinstance(first_input["content"][0]["text"], str)

    rows = _read_jsonl_rows(out_path)
    assert len(rows) == 1
    assert set(rows[0].keys()) == {
        "email_id",
        "label",
        "confidence",
        "reasons",
        "course_hints",
        "event_type",
        "action_items",
        "raw_extract",
        "notes",
    }


def test_prefix_text_json_extraction(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mbox_path = tmp_path / "emails.mbox"
    out_path = tmp_path / "labeled.jsonl"
    _make_mbox(mbox_path, count=1)
    label = _valid_label("msg-001@example.edu")

    class FakeResponse:
        def __init__(self, payload: str) -> None:
            self.output_text = payload
            self.model = "fake-model"

    class FakeResponses:
        async def create(self, **kwargs: object) -> FakeResponse:
            payload = f"Here is the result:\n{json.dumps(label)}\nDone."
            return FakeResponse(payload)

    class FakeClient:
        def __init__(self, api_key: str, base_url: str | None = None) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr("tools.labeling.label_emails_async.AsyncOpenAI", FakeClient)
    summary = asyncio.run(run_labeling_pipeline(_build_config(tmp_path, mbox_path, out_path)))

    assert summary["success_count"] == 1
    assert summary["invalid_dropped_count"] == 0
    rows = _read_jsonl_rows(out_path)
    assert len(rows) == 1
    assert rows[0]["label"] == "KEEP"


def test_invalid_json_repaired_round_one_with_schema_feedback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mbox_path = tmp_path / "emails.mbox"
    out_path = tmp_path / "labeled.jsonl"
    _make_mbox(mbox_path, count=1)

    calls: list[dict[str, object]] = []
    invalid_json = '{"email_id":"msg-001@example.edu","label":"KEEP"}'

    class FakeResponse:
        def __init__(self, payload: str) -> None:
            self.output_text = payload
            self.model = "fake-model"

    class FakeResponses:
        async def create(self, **kwargs: object) -> FakeResponse:
            calls.append(dict(kwargs))
            if len(calls) == 1:
                return FakeResponse(invalid_json)
            return FakeResponse(json.dumps(_valid_label("msg-001@example.edu")))

    class FakeClient:
        def __init__(self, api_key: str, base_url: str | None = None) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr("tools.labeling.label_emails_async.AsyncOpenAI", FakeClient)
    summary = asyncio.run(run_labeling_pipeline(_build_config(tmp_path, mbox_path, out_path)))

    assert summary["success_count"] == 1
    assert summary["invalid_dropped_count"] == 0
    assert len(calls) == 2

    repair_prompt = calls[1]["input"][0]["content"][0]["text"]
    assert "Schema (JSON):" in repair_prompt
    assert "Validation errors:" in repair_prompt
    assert "Invalid output:" in repair_prompt
    assert '"label":"KEEP"' in repair_prompt


def test_invalid_json_repaired_in_second_round(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mbox_path = tmp_path / "emails.mbox"
    out_path = tmp_path / "labeled.jsonl"
    _make_mbox(mbox_path, count=1)

    calls = {"count": 0}

    class FakeResponse:
        def __init__(self, payload: str) -> None:
            self.output_text = payload
            self.model = "fake-model"

    class FakeResponses:
        async def create(self, **kwargs: object) -> FakeResponse:
            calls["count"] += 1
            if calls["count"] == 1:
                return FakeResponse('{"email_id":"msg-001@example.edu","label":"KEEP"}')
            if calls["count"] == 2:
                return FakeResponse('{"email_id":"msg-001@example.edu","label":"UNKNOWN","confidence":0.8}')
            return FakeResponse(json.dumps(_valid_label("msg-001@example.edu")))

    class FakeClient:
        def __init__(self, api_key: str, base_url: str | None = None) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr("tools.labeling.label_emails_async.AsyncOpenAI", FakeClient)
    summary = asyncio.run(run_labeling_pipeline(_build_config(tmp_path, mbox_path, out_path)))

    assert summary["success_count"] == 1
    assert summary["invalid_dropped_count"] == 0
    assert summary["error_count"] == 0
    assert calls["count"] == 3


def test_still_invalid_after_round_two_goes_to_error_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mbox_path = tmp_path / "emails.mbox"
    out_path = tmp_path / "labeled.jsonl"
    err_path = tmp_path / "label_errors.jsonl"
    _make_mbox(mbox_path, count=1)

    calls = {"count": 0}

    class FakeResponse:
        def __init__(self, payload: str) -> None:
            self.output_text = payload
            self.model = "fake-model"

    class FakeResponses:
        async def create(self, **kwargs: object) -> FakeResponse:
            calls["count"] += 1
            return FakeResponse("not a json object")

    class FakeClient:
        def __init__(self, api_key: str, base_url: str | None = None) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr("tools.labeling.label_emails_async.AsyncOpenAI", FakeClient)
    summary = asyncio.run(run_labeling_pipeline(_build_config(tmp_path, mbox_path, out_path)))

    assert calls["count"] == 3
    assert summary["success_count"] == 0
    assert summary["invalid_dropped_count"] == 1
    assert summary["error_count"] == 1
    assert not out_path.exists()

    error_rows = _read_jsonl_rows(err_path)
    assert len(error_rows) == 1
    assert error_rows[0]["error_type"] == "json_invalid_after_repair"


def test_resume_skips_existing_ids(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mbox_path = tmp_path / "emails.mbox"
    out_path = tmp_path / "labeled.jsonl"
    _make_mbox(mbox_path, count=2)

    out_path.write_text(json.dumps(_valid_label("msg-001@example.edu")) + "\n", encoding="utf-8")
    api_calls: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, payload: str) -> None:
            self.output_text = payload
            self.model = "fake-model"

    class FakeResponses:
        async def create(self, **kwargs: object) -> FakeResponse:
            api_calls.append(dict(kwargs))
            return FakeResponse(json.dumps(_valid_label("msg-002@example.edu")))

    class FakeClient:
        def __init__(self, api_key: str, base_url: str | None = None) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr("tools.labeling.label_emails_async.AsyncOpenAI", FakeClient)
    summary = asyncio.run(run_labeling_pipeline(_build_config(tmp_path, mbox_path, out_path)))

    assert summary["skipped_existing"] == 1
    assert summary["processed"] == 1
    assert summary["success_count"] == 1
    assert len(api_calls) == 1

    rows = _read_jsonl_rows(out_path)
    assert len(rows) == 2


def test_cli_dry_run_does_not_call_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mbox_path = tmp_path / "emails.mbox"
    out_path = tmp_path / "out.jsonl"
    _make_mbox(mbox_path, count=1)

    called = {"count": 0}

    async def fake_run(config: LabelingConfig) -> dict[str, object]:
        called["count"] += 1
        assert config.dry_run is True
        return {"dry_run": True, "planned_records": 1}

    monkeypatch.setattr("tools.label_emails.run_labeling_pipeline", fake_run)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://code.respyun.com/v1")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.3-codex")
    monkeypatch.setattr(
        sys,
        "argv",
        ["label_emails", "--in", str(mbox_path), "--out", str(out_path), "--dry-run"],
    )

    assert cli.main() == 0
    assert called["count"] == 1


def test_cli_max_passed_to_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mbox_path = tmp_path / "emails.mbox"
    out_path = tmp_path / "out.jsonl"
    _make_mbox(mbox_path, count=3)

    async def fake_run(config: LabelingConfig) -> dict[str, object]:
        assert config.max_records == 2
        assert config.workers == 7
        return {"processed": 2}

    monkeypatch.setattr("tools.label_emails.run_labeling_pipeline", fake_run)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.3-codex")
    monkeypatch.setattr(
        sys,
        "argv",
        ["label_emails", "--in", str(mbox_path), "--out", str(out_path), "--workers", "7", "--max", "2"],
    )

    assert cli.main() == 0


def test_cli_rejects_non_mbox_input(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    jsonl_input = tmp_path / "emails.jsonl"
    jsonl_input.write_text('{"email_id":"x","body_text":"hi"}\n', encoding="utf-8")
    out_path = tmp_path / "out.jsonl"

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.3-codex")
    monkeypatch.setattr(
        sys,
        "argv",
        ["label_emails", "--in", str(jsonl_input), "--out", str(out_path), "--dry-run"],
    )

    assert cli.main() == 1
