from __future__ import annotations

from types import SimpleNamespace

from app.modules.onboarding.service import _derive_source_health, _derive_stage_and_message


def test_derive_stage_and_message_for_canvas_requirement() -> None:
    stage, message, message_code, message_params = _derive_stage_and_message(
        user=SimpleNamespace(),
        canvas_source=None,
        gmail_source=None,
        gmail_skipped=False,
    )
    assert stage == "needs_canvas_ics"
    assert message == "Add your Canvas ICS link before anything else."
    assert message_code == "onboarding.stage.needs_canvas_ics"
    assert message_params == {}


def test_derive_stage_and_message_for_ready_state() -> None:
    monitoring_window = SimpleNamespace()
    stage, message, message_code, message_params = _derive_stage_and_message(
        user=SimpleNamespace(),
        canvas_source=SimpleNamespace(connected=True, monitoring_window=monitoring_window),
        gmail_source=None,
        gmail_skipped=True,
    )
    assert stage == "ready"
    assert message == "Onboarding complete."
    assert message_code == "onboarding.stage.ready"
    assert message_params == {}


def test_derive_source_health_codes() -> None:
    disconnected = _derive_source_health(active_sources=[], first_error_source=None)
    assert disconnected.message_code == "onboarding.source_health.disconnected"

    attention = _derive_source_health(active_sources=[SimpleNamespace()], first_error_source=SimpleNamespace(id=2, provider="gmail"))
    assert attention.message_code == "onboarding.source_health.attention"
    assert attention.affected_source_id == 2
    assert attention.affected_provider == "gmail"

    healthy = _derive_source_health(active_sources=[SimpleNamespace()], first_error_source=None)
    assert healthy.message_code == "onboarding.source_health.healthy"
