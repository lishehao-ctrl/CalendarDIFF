from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Input, InputType, SyncRunStatus, SyncTriggerType
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

    if user.onboarding_completed_at is not None:
        return OnboardingStatus(
            stage="ready",
            message="Onboarding complete.",
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
    ics_url: str,
) -> OnboardingRegisterResult:
    user, _ = create_or_initialize_user(db, notify_email=notify_email)

    try:
        input_result = create_ics_input(
            db,
            user_id=user.id,
            payload=InputCreateRequest(url=ics_url, user_term_id=None),
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
        input_id=input_result.input.id,
        is_baseline_sync=sync_result.is_baseline_sync,
        changes_created=sync_result.changes_created,
    )


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
