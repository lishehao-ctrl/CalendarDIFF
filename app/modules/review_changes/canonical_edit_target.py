from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import Change
from app.db.models.shared import User
from app.modules.review_changes.canonical_edit_errors import (
    CanonicalEditNotFoundError,
    CanonicalEditValidationError,
)


def load_user_or_raise(db: Session, *, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise CanonicalEditNotFoundError("user not found")
    return user


def resolve_target_entity_uid(
    db: Session,
    *,
    user_id: int,
    change_id: int | None,
    entity_uid: str | None,
) -> str:
    normalized_entity_uid = entity_uid.strip() if isinstance(entity_uid, str) else ""
    if entity_uid is not None and not normalized_entity_uid:
        raise CanonicalEditValidationError("target.entity_uid must not be blank")
    if change_id is None and not normalized_entity_uid:
        raise CanonicalEditValidationError("target.change_id or target.entity_uid is required")

    change_entity_uid: str | None = None
    if change_id is not None:
        row = db.scalar(
            select(Change)
            .where(Change.id == change_id, Change.user_id == user_id)
            .limit(1)
        )
        if row is None:
            raise CanonicalEditNotFoundError("target change not found")
        change_entity_uid = row.entity_uid

    if change_entity_uid is not None and normalized_entity_uid and change_entity_uid != normalized_entity_uid:
        raise CanonicalEditValidationError("target.change_id and target.entity_uid must reference the same entity_uid")

    resolved = normalized_entity_uid or change_entity_uid
    if not isinstance(resolved, str) or not resolved:
        raise CanonicalEditValidationError("unable to resolve target entity_uid")
    return resolved


__all__ = [
    "load_user_or_raise",
    "resolve_target_entity_uid",
]
