from __future__ import annotations

from datetime import datetime, timezone

from app.modules.core_ingest.observation_priority import choose_primary_observation
from app.modules.core_ingest.source_identity import build_source_scoped_entity_uid


def test_build_source_scoped_entity_uid_stable_for_same_pair() -> None:
    first = build_source_scoped_entity_uid(source_kind="calendar", external_event_id="abc-123")
    second = build_source_scoped_entity_uid(source_kind="calendar", external_event_id="abc-123")
    assert first == second


def test_build_source_scoped_entity_uid_differs_for_different_pairs() -> None:
    first = build_source_scoped_entity_uid(source_kind="calendar", external_event_id="abc-123")
    second = build_source_scoped_entity_uid(source_kind="email", external_event_id="abc-123")
    third = build_source_scoped_entity_uid(source_kind="calendar", external_event_id="xyz-999")
    assert first != second
    assert first != third


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
