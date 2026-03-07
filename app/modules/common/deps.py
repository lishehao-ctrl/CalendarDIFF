from __future__ import annotations

from fastapi import Depends
from app.db.models.shared import User
from app.modules.auth.deps import get_onboarded_authenticated_user_or_409


def get_onboarded_user_or_409(user: User = Depends(get_onboarded_authenticated_user_or_409)) -> User:
    return user


def require_onboarded_user_or_409(_: User = Depends(get_onboarded_user_or_409)) -> None:
    return None
