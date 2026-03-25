from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.shared import User
from app.modules.agents.language_context import detect_agent_input_language, resolve_agent_language_context


def test_detect_agent_input_language_recognizes_chinese() -> None:
    assert detect_agent_input_language(["请帮我通过这条变更"]) == "zh-CN"


def test_detect_agent_input_language_recognizes_english() -> None:
    assert detect_agent_input_language(["please approve this change"]) == "en"


def test_resolve_agent_language_context_prefers_explicit_override(db_session) -> None:
    user = User(
        email="lang-explicit@example.com",
        language_code="en",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    context = resolve_agent_language_context(
        db_session,
        user_id=user.id,
        explicit_language_code="zh-CN",
        input_texts=["please approve this change"],
    )

    assert context.effective_language_code == "zh-CN"
    assert context.system_language_code == "en"
    assert context.resolution_source == "explicit"


def test_resolve_agent_language_context_uses_detected_input_before_user_profile(db_session) -> None:
    user = User(
        email="lang-detected@example.com",
        language_code="en",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    context = resolve_agent_language_context(
        db_session,
        user_id=user.id,
        explicit_language_code=None,
        input_texts=["请把这个 proposal 改成中文"],
    )

    assert context.effective_language_code == "zh-CN"
    assert context.input_language_code == "zh-CN"
    assert context.system_language_code == "en"
    assert context.resolution_source == "detected_input"
