from __future__ import annotations

from sqlalchemy import select

from app.db.models.review import Input, InputType
from app.db.models.shared import User


def test_deleting_user_via_orm_cascades_inputs(db_session) -> None:
    user = User(email="cascade@example.com", notify_email="cascade@example.com")
    db_session.add(user)
    db_session.flush()
    input_row = Input(user_id=user.id, type=InputType.ICS, identity_key=f"canonical:user:{user.id}", is_active=True)
    db_session.add(input_row)
    db_session.commit()

    db_session.delete(user)
    db_session.commit()

    remaining = db_session.scalar(select(Input).where(Input.identity_key == input_row.identity_key))
    assert remaining is None
