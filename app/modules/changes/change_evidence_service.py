from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import Change
from app.modules.common.payload_schemas import FrozenChangeEvidence
from app.modules.changes.change_decision_service import ChangeNotFoundError


class ChangeEvidenceNotFoundError(RuntimeError):
    pass


class ChangeEvidenceReadError(RuntimeError):
    pass


def preview_change_evidence(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    side: Literal["before", "after"],
) -> dict:
    row = db.scalar(
        select(Change).where(Change.id == change_id, Change.user_id == user_id)
    )
    if row is None:
        raise ChangeNotFoundError("Review change not found")

    evidence = row.before_evidence_json if side == "before" else row.after_evidence_json
    if not isinstance(evidence, dict):
        raise ChangeEvidenceNotFoundError("Evidence preview unavailable")
    try:
        normalized = FrozenChangeEvidence.model_validate(evidence)
    except Exception as exc:  # pragma: no cover - defensive malformed frozen evidence path
        raise ChangeEvidenceReadError("Evidence preview is malformed") from exc

    return {
        "side": side,
        "content_type": normalized.content_type,
        "truncated": False,
        "filename": f"change-{row.id}-{side}.evidence",
        "provider": normalized.provider,
        "structured_kind": normalized.structured_kind,
        "structured_items": [item.model_dump(mode="json") for item in normalized.structured_items],
        "event_count": normalized.event_count,
        "events": [item.model_dump(mode="json") for item in normalized.events],
        "preview_text": normalized.preview_text,
    }


__all__ = [
    "ChangeEvidenceNotFoundError",
    "ChangeEvidenceReadError",
    "preview_change_evidence",
]
