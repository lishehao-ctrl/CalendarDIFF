from __future__ import annotations

from app.modules.common.text_sanitize import sanitize_markup_text
from app.modules.runtime.connectors.llm_parsers.semantic_orchestrator import _build_gmail_cache_prefix
from app.modules.runtime.connectors.clients.gmail_client import _extract_plain_text_from_payload


def test_sanitize_markup_text_removes_html_and_unescapes_entities() -> None:
    raw = "<html><body><h1>Quiz&nbsp;1</h1><p>Due<br>Friday &amp; submit on Canvas.</p><script>ignore()</script></body></html>"
    cleaned = sanitize_markup_text(raw)
    assert cleaned is not None
    assert "<html" not in cleaned
    assert "ignore()" not in cleaned
    assert "Quiz 1" in cleaned
    assert "Friday & submit on Canvas." in cleaned



def test_extract_plain_text_from_payload_sanitizes_html_fallback_body() -> None:
    payload = {
        "mimeType": "text/html",
        "body": {
            "data": "PGh0bWw+PGJvZHk+PHA+SFEgMyBEdWU8YnI+RnJpZGF5IGF0IDExOjU5cG08L3A+PC9ib2R5PjwvaHRtbD4="
        },
    }
    cleaned = _extract_plain_text_from_payload(payload)
    assert cleaned is not None
    assert "<html" not in cleaned.lower()
    assert "HQ 3 Due" in cleaned
    assert "Friday at 11:59pm" in cleaned



def test_build_gmail_cache_prefix_sanitizes_html_body_text() -> None:
    payload = {
        "message_id": "m1",
        "subject": "<b>Homework update</b>",
        "snippet": "Due &amp; updated",
        "body_text": "<div>Homework 2 moved<br>to Monday</div>",
        "from_header": "<span>staff@example.edu</span>",
        "thread_id": "t1",
        "internal_date": "2026-03-01T09:00:00+00:00",
    }
    prefix = _build_gmail_cache_prefix(payload=payload)
    message = prefix["source_message"]
    assert message["subject"] == "Homework update"
    assert message["snippet"] == "Due & updated"
    assert message["body_text"] == "Homework 2 moved\nto Monday"
    assert message["from_header"] == "staff@example.edu"
