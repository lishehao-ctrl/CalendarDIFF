from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.modules.input_control_plane.sources_service import get_input_source
from app.modules.users.service import get_registered_user


def require_registered_user_or_409(db: Session):
    user = get_registered_user(db)
    if user is None:
        raise HTTPException(status_code=409, detail={"code": "user_not_initialized", "message": "user not initialized"})
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
