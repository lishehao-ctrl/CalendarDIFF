from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import sanitize_log_message
from app.db.session import get_db
from app.modules.inputs.service import (
    GmailOAuthStateError,
    create_gmail_input_from_oauth,
    parse_gmail_oauth_state,
)
from app.modules.sync.gmail_client import GmailClient
from app.modules.users.service import (
    UserNotInitializedError,
    UserOnboardingIncompleteError,
    require_onboarded_user,
    user_onboarding_incomplete_detail,
    user_not_initialized_detail,
)

router = APIRouter(tags=["oauth"])


@router.get("/v1/oauth/gmail/callback", include_in_schema=False)
def gmail_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if error:
        message = sanitize_log_message(error_description or error)
        return _redirect_with_status("error", message=message)
    if not code or not state:
        return _redirect_with_status("error", message="Missing OAuth callback parameters")

    try:
        oauth_state = parse_gmail_oauth_state(state)
    except GmailOAuthStateError as exc:
        return _redirect_with_status("error", message=sanitize_log_message(str(exc)))

    gmail_client = GmailClient()
    try:
        user = require_onboarded_user(db)
        tokens = gmail_client.exchange_code(code=code)
        profile = gmail_client.get_profile(access_token=tokens.access_token)
        result = create_gmail_input_from_oauth(
            db,
            user_id=user.id,
            label=oauth_state.label,
            from_contains=oauth_state.from_contains,
            subject_keywords=oauth_state.subject_keywords,
            account_email=profile.email_address,
            history_id=None,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            access_token_expires_at=tokens.expires_at,
        )
    except UserNotInitializedError:
        return _redirect_with_status("error", message=user_not_initialized_detail()["message"])
    except UserOnboardingIncompleteError:
        return _redirect_with_status("error", message=user_onboarding_incomplete_detail()["message"])
    except Exception as exc:
        db.rollback()
        return _redirect_with_status("error", message=sanitize_log_message(str(exc)))

    return _redirect_with_status("success", input_id=result.input.id)


def _redirect_with_status(status_value: str, *, input_id: int | None = None, message: str | None = None) -> RedirectResponse:
    settings = get_settings()
    app_base_url = settings.app_base_url.rstrip("/") if settings.app_base_url else ""
    query: dict[str, str] = {"gmail_oauth_status": status_value}
    if input_id is not None:
        query["input_id"] = str(input_id)
    if message:
        query["message"] = message[:256]
    target_path = f"/ui?{urlencode(query)}"
    target = f"{app_base_url}{target_path}" if app_base_url else target_path
    return RedirectResponse(url=target, status_code=302)
