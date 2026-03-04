from __future__ import annotations

from app.modules.core_ingest.apply_service import (
    _blocked_entity_uid_set,
    _coerce_candidate_reason,
    _find_existing_entity_link,
    _link_gmail_observation_to_entity,
    _resolve_pending_link_candidates_for_pair,
    _upsert_event_entity_link,
    _upsert_link_candidate,
    _with_candidate_evidence,
)

__all__ = [
    "_blocked_entity_uid_set",
    "_coerce_candidate_reason",
    "_find_existing_entity_link",
    "_link_gmail_observation_to_entity",
    "_resolve_pending_link_candidates_for_pair",
    "_upsert_event_entity_link",
    "_upsert_link_candidate",
    "_with_candidate_evidence",
]
