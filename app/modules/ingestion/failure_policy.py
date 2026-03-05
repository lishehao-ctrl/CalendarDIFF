from __future__ import annotations

from app.db.models.ingestion import ConnectorResultStatus
from app.modules.ingestion.connector_types import ConnectorFailureDecision
from app.modules.runtime_kernel import truncate_error


def decide_failure(
    *,
    result_status: ConnectorResultStatus,
    error_code: str | None,
    error_message: str | None,
) -> ConnectorFailureDecision:
    normalized_code = (error_code or "connector_failed").strip() or "connector_failed"
    normalized_message = truncate_error(error_message or normalized_code)
    retryable = _is_retryable_failure(result_status=result_status, error_code=normalized_code)
    return ConnectorFailureDecision(
        retryable=retryable,
        normalized_code=normalized_code,
        normalized_message=normalized_message,
    )


def _is_retryable_failure(*, result_status: ConnectorResultStatus, error_code: str) -> bool:
    code = error_code.lower()
    if result_status == ConnectorResultStatus.AUTH_FAILED:
        return False
    if result_status == ConnectorResultStatus.RATE_LIMITED:
        return True
    if "rate_limit" in code:
        return True
    if "timeout" in code:
        return True
    if "upstream" in code:
        return True
    if "fetch_failed" in code:
        return True
    if "queue_unavailable" in code:
        return True
    if "connector_exception" in code:
        return True
    return result_status in {ConnectorResultStatus.FETCH_FAILED, ConnectorResultStatus.PARSE_FAILED}


__all__ = ["decide_failure"]
