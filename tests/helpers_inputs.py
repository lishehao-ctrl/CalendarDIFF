from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.inputs.schemas import InputCreateRequest
from app.modules.inputs.service import create_ics_input


def create_ics_input_for_user(db_session: Session, *, user_id: int, url: str) -> int:
    created = create_ics_input(
        db_session,
        user_id=user_id,
        payload=InputCreateRequest(url=url),
    )
    return created.input.id

