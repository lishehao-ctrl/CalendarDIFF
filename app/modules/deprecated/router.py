from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import require_api_key

router = APIRouter(include_in_schema=False, dependencies=[Depends(require_api_key)])
_TOMBSTONE_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def _raise_not_found() -> None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _register(path: str) -> None:
    router.add_api_route(path, _raise_not_found, methods=_TOMBSTONE_METHODS, include_in_schema=False)


# Legacy API namespace removals.
_register("/v1/sources")
_register("/v1/status")
_register("/v1/review_candidates")
_register("/v1/review_candidates/{candidate_id}/route")
_register("/v1/changes/feed")
_register("/v1/changes")
_register("/v1/snapshots")

# Legacy notifications surface removals.
_register("/v1/notification_prefs")
_register("/v1/notifications/send_digest_now")
_register("/v1/dev/inject_notify")

# Legacy user endpoints removals.
_register("/v1/user")
_register("/v1/user/terms")
_register("/v1/user/terms/{term_id}")

# Legacy input-scoped routes removals.
_register("/v1/inputs/ics")
_register("/v1/inputs/{input_id}/runs")
_register("/v1/inputs/{input_id}/deadlines")
_register("/v1/inputs/{input_id}/overrides")
_register("/v1/inputs/{input_id}/changes")
_register("/v1/inputs/{input_id}/snapshots")
_register("/v1/inputs/{input_id}/changes/{change_id}/viewed")
_register("/v1/inputs/{input_id}/changes/{change_id}/evidence/{side}/preview")
_register("/v1/inputs/{input_id}/changes/{change_id}/evidence/{side}/download")
_register("/v1/changes/{change_id}/evidence/{side}/download")

# Legacy email-review namespace removals.
_register("/v1/emails/queue")
_register("/v1/emails/{email_id}/route")
_register("/v1/emails/{email_id}/mark_viewed")
_register("/v1/emails/{email_id}/apply")
