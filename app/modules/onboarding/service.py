from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.input import InputSource
from app.db.models.shared import User


class OnboardingRegisterError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class SourceHealthSummary:
    status: str
    message: str
    affected_source_id: int | None
    affected_provider: str | None


@dataclass(frozen=True)
class OnboardingStatus:
    stage: str
    message: str
    registered_user_id: int | None
    first_source_id: int | None
    source_health: SourceHealthSummary


@dataclass(frozen=True)
class OnboardingRegisterResult:
    user_id: int
    stage: str
    first_source_id: int | None


def get_onboarding_status_for_user(db: Session, *, user: User) -> OnboardingStatus:
    active_sources = list(
        db.scalars(
            select(InputSource)
            .where(
                InputSource.user_id == user.id,
                InputSource.is_active.is_(True),
            )
            .order_by(InputSource.id.asc())
        ).all()
    )
    first_source = active_sources[0] if active_sources else None
    first_error_source = next((source for source in active_sources if source.last_error_message), None)
    source_health = _derive_source_health(active_sources=active_sources, first_error_source=first_error_source)

    if first_source is None:
        return OnboardingStatus(
            stage="needs_source_connection",
            message="Connect at least one active input source.",
            registered_user_id=user.id,
            first_source_id=None,
            source_health=source_health,
        )

    return OnboardingStatus(
        stage="ready",
        message="Onboarding complete.",
        registered_user_id=user.id,
        first_source_id=first_source.id,
        source_health=source_health,
    )


def get_onboarding_status(db: Session, *, user: User) -> OnboardingStatus:
    return get_onboarding_status_for_user(db, user=user)


def register_onboarding(
    db: Session,
    *,
    user: User,
    notify_email: str,
) -> OnboardingRegisterResult:
    normalized = notify_email.strip().lower()
    if normalized != (user.notify_email or "").strip().lower():
        raise OnboardingRegisterError("notify_email is managed by auth register flow", status_code=422)

    status = get_onboarding_status_for_user(db, user=user)
    return OnboardingRegisterResult(
        user_id=user.id,
        stage=status.stage,
        first_source_id=status.first_source_id,
    )


def _derive_source_health(*, active_sources: list[InputSource], first_error_source: InputSource | None) -> SourceHealthSummary:
    if not active_sources:
        return SourceHealthSummary(
            status="disconnected",
            message="No active sources connected yet.",
            affected_source_id=None,
            affected_provider=None,
        )
    if first_error_source is not None:
        return SourceHealthSummary(
            status="attention",
            message="A connected source needs attention before syncs are reliable.",
            affected_source_id=first_error_source.id,
            affected_provider=first_error_source.provider,
        )
    return SourceHealthSummary(
        status="healthy",
        message="Connected sources are ready for intake.",
        affected_source_id=None,
        affected_provider=None,
    )
