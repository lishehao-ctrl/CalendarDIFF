from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models.shared import User
from app.modules.auth.deps import get_authenticated_user_or_401
from app.modules.input_control_plane.sources_service import get_input_source


def require_registered_user_or_409(user: User = Depends(get_authenticated_user_or_401)) -> User:
    return user


def require_owned_source_or_404(*, db: Session, user_id: int, source_id: int):
    source = get_input_source(db, user_id=user_id, source_id=source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Input source not found")
    return source


__all__ = [
    "require_owned_source_or_404",
    "require_registered_user_or_409",
]
