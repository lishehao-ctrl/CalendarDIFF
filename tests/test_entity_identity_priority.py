from __future__ import annotations

from datetime import datetime, timezone

from app.modules.runtime.apply.observation_priority import choose_primary_observation


def test_choose_primary_observation_prefers_newer_observation() -> None:
    older = {
        "source_kind": "calendar",
        "observed_at": datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc),
        "observation_id": 1,
        "event_payload": {"confidence": 0.9},
    }
    newer = {
        "source_kind": "calendar",
        "observed_at": datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
        "observation_id": 2,
        "event_payload": {"confidence": 0.9},
    }
    chosen = choose_primary_observation([older, newer])
    assert chosen == newer


def test_choose_primary_observation_prefers_higher_id_on_exact_tie() -> None:
    first = {
        "source_kind": "email",
        "observed_at": datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
        "observation_id": 10,
        "event_payload": {"confidence": 0.5},
    }
    second = {
        "source_kind": "email",
        "observed_at": datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
        "observation_id": 11,
        "event_payload": {"confidence": 0.5},
    }
    chosen = choose_primary_observation([first, second])
    assert chosen == second
