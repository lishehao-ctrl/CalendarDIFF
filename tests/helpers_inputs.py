from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.shared import User
from app.modules.input_control_plane.schemas import InputSourceCreateRequest
from app.modules.input_control_plane.sources_service import create_input_source


def create_ics_input_for_user(db_session: Session, *, user_id: int, url: str) -> int:
    user = db_session.get(User, user_id)
    if user is None:
        raise RuntimeError(f"user not found: {user_id}")
    created = create_input_source(
        db_session,
        user=user,
        payload=InputSourceCreateRequest(
            source_kind="calendar",
            provider="ics",
            config={},
            secrets={"url": url},
        ),
    )
    return created.id
