from __future__ import annotations

from app.db.models.shared import User
from app.modules.settings.schemas import UserResponse


def to_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        timezone_name=user.timezone_name,
        timezone_source=user.timezone_source,
        language_code=user.language_code,
        calendar_delay_seconds=user.calendar_delay_seconds,
        created_at=user.created_at,
    )


__all__ = ["to_user_response"]
