from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from app.modules.evidence.store import save_ics


def test_save_ics_persists_file_and_returns_evidence_key(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EVIDENCE_DIR", "./evidence")
    get_settings.cache_clear()

    content = b"BEGIN:VCALENDAR\nEND:VCALENDAR\n"
    retrieved_at = datetime(2026, 2, 19, 20, 31, 10, tzinfo=timezone.utc)

    evidence_key = save_ics(source_id=12, content=content, retrieved_at=retrieved_at)

    assert evidence_key["kind"] == "ics"
    assert evidence_key["store"] == "fs"
    assert evidence_key["sha256"] == hashlib.sha256(content).hexdigest()
    assert evidence_key["retrieved_at"] == "2026-02-19T20:31:10+00:00"
    assert str(evidence_key["path"]).startswith("evidence/ics/source_12/")
    assert "2026-02-19T20-31-10Z__sha256_" in str(evidence_key["path"])

    evidence_path = Path(tmp_path) / str(evidence_key["path"])
    assert evidence_path.exists()
    assert evidence_path.read_bytes() == content

    get_settings.cache_clear()
