from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Input, InputType, SyncRunStatus, SyncTriggerType, User, UserTerm
from app.modules.inputs.schemas import InputCreateRequest
from app.modules.inputs.service import create_ics_input
from app.modules.notify.interface import ChangeDigestItem, Notifier, SendResult
from app.modules.sync.service import SyncRunResult, sync_source
from app.modules.users.service import create_or_initialize_user, get_registered_user


BASELINE_FAILURE_STATUSES = {
    SyncRunStatus.FETCH_FAILED,
    SyncRunStatus.PARSE_FAILED,
    SyncRunStatus.DIFF_FAILED,
    SyncRunStatus.EMAIL_FAILED,
}


class OnboardingRegisterError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class OnboardingStatus:
    stage: str
    message: str
    registered_user_id: int | None
    first_input_id: int | None
    last_error: str | None


@dataclass(frozen=True)
class OnboardingRegisterResult:
    user_id: int
    term_id: int
    input_id: int
    is_baseline_sync: bool
    changes_created: int


def get_onboarding_status(db: Session) -> OnboardingStatus:
    user = get_registered_user(db)
    if user is None:
        return OnboardingStatus(
            stage="needs_user",
            message="Create user profile first with notify_email.",
            registered_user_id=None,
            first_input_id=None,
            last_error=None,
        )

    first_ics_input = db.scalar(
        select(Input)
        .where(Input.user_id == user.id, Input.type == InputType.ICS)
        .order_by(Input.id.asc())
        .limit(1)
    )
    term_exists = db.scalar(
        select(UserTerm.id)
        .where(UserTerm.user_id == user.id)
        .order_by(UserTerm.id.asc())
        .limit(1)
    )

    if user.onboarding_completed_at is not None:
        return OnboardingStatus(
            stage="ready",
            message="Onboarding complete.",
            registered_user_id=user.id,
            first_input_id=first_ics_input.id if first_ics_input is not None else None,
            last_error=None,
        )

    if term_exists is None:
        return OnboardingStatus(
            stage="needs_term",
            message="Create first term window.",
            registered_user_id=user.id,
            first_input_id=first_ics_input.id if first_ics_input is not None else None,
            last_error=None,
        )
    if first_ics_input is None:
        return OnboardingStatus(
            stage="needs_ics",
            message="Connect first ICS calendar source.",
            registered_user_id=user.id,
            first_input_id=None,
            last_error=None,
        )

    return OnboardingStatus(
        stage="needs_baseline",
        message="Run first successful ICS baseline sync.",
        registered_user_id=user.id,
        first_input_id=first_ics_input.id,
        last_error=first_ics_input.last_error,
    )


def register_onboarding(
    db: Session,
    *,
    notify_email: str,
    term_code: str,
    term_label: str,
    term_starts_on: date,
    term_ends_on: date,
    ics_url: str,
) -> OnboardingRegisterResult:
    user, _ = create_or_initialize_user(db, notify_email=notify_email)
    term = _upsert_term(
        db,
        user=user,
        code=term_code,
        label=term_label,
        starts_on=term_starts_on,
        ends_on=term_ends_on,
    )

    try:
        input_result = create_ics_input(
            db,
            user_id=user.id,
            payload=InputCreateRequest(url=ics_url, user_term_id=term.id),
        )
    except RuntimeError as exc:
        raise OnboardingRegisterError(str(exc), status_code=422) from exc

    sync_result = _run_baseline_sync(db, input_row=input_result.input)
    if sync_result.status in BASELINE_FAILURE_STATUSES:
        safe_error = sync_result.last_error or "baseline sync failed"
        if sync_result.status == SyncRunStatus.PARSE_FAILED:
            raise OnboardingRegisterError(safe_error, status_code=422)
        raise OnboardingRegisterError(safe_error, status_code=502)

    user.onboarding_completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    return OnboardingRegisterResult(
        user_id=user.id,
        term_id=term.id,
        input_id=input_result.input.id,
        is_baseline_sync=sync_result.is_baseline_sync,
        changes_created=sync_result.changes_created,
    )


def _upsert_term(
    db: Session,
    *,
    user: User,
    code: str,
    label: str,
    starts_on: date,
    ends_on: date,
) -> UserTerm:
    normalized_code = code.strip()
    existing = db.scalar(
        select(UserTerm)
        .where(UserTerm.user_id == user.id, UserTerm.code == normalized_code)
        .order_by(UserTerm.id.asc())
        .limit(1)
    )
    if existing is not None:
        existing.label = label.strip()
        existing.starts_on = starts_on
        existing.ends_on = ends_on
        existing.is_active = True
        if existing.ends_on < existing.starts_on:
            raise OnboardingRegisterError("ends_on must be greater than or equal to starts_on", status_code=422)
        _assert_no_overlap(
            db,
            user_id=user.id,
            starts_on=existing.starts_on,
            ends_on=existing.ends_on,
            exclude_term_id=existing.id,
        )
        db.commit()
        db.refresh(existing)
        return existing

    if ends_on < starts_on:
        raise OnboardingRegisterError("ends_on must be greater than or equal to starts_on", status_code=422)
    _assert_no_overlap(db, user_id=user.id, starts_on=starts_on, ends_on=ends_on, exclude_term_id=None)

    term = UserTerm(
        user_id=user.id,
        code=normalized_code,
        label=label.strip(),
        starts_on=starts_on,
        ends_on=ends_on,
        is_active=True,
    )
    db.add(term)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise OnboardingRegisterError("Term code already exists for this user", status_code=409) from exc
    db.refresh(term)
    return term


def _assert_no_overlap(
    db: Session,
    *,
    user_id: int,
    starts_on: date,
    ends_on: date,
    exclude_term_id: int | None,
) -> None:
    stmt = select(UserTerm.id).where(
        UserTerm.user_id == user_id,
        UserTerm.is_active.is_(True),
        UserTerm.starts_on <= ends_on,
        UserTerm.ends_on >= starts_on,
    )
    if exclude_term_id is not None:
        stmt = stmt.where(UserTerm.id != exclude_term_id)
    existing = db.scalar(stmt.order_by(UserTerm.starts_on.asc(), UserTerm.id.asc()).limit(1))
    if existing is not None:
        raise OnboardingRegisterError("active term window overlaps existing active term", status_code=422)


def _run_baseline_sync(db: Session, *, input_row: Input) -> SyncRunResult:
    # During onboarding we do not want a real email side effect; this only validates
    # that fetch/parse/diff pipeline succeeds and seeds the baseline snapshot/events.
    class _NoopNotifier(Notifier):
        def send_changes_digest(
            self,
            to_email: str,
            input_label: str,
            input_id: int,
            items: list[ChangeDigestItem],
        ) -> SendResult:
            return SendResult(success=True, error=None)

    return sync_source(
        db,
        input_row,
        notifier=_NoopNotifier(),
        trigger_type=SyncTriggerType.MANUAL,
        lock_owner="onboarding-register",
    )
