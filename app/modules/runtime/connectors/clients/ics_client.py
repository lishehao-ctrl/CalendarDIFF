from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import httpx

from app.core.config import get_settings
from app.modules.runtime.connectors.clients.types import FetchResult

logger = logging.getLogger(__name__)


class ICSClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._max_retries = max(settings.http_max_retries, 0)
        self._timeout = httpx.Timeout(
            connect=settings.http_connect_timeout_seconds,
            read=settings.http_read_timeout_seconds,
            write=settings.http_read_timeout_seconds,
            pool=settings.http_connect_timeout_seconds,
        )

    def fetch(
        self,
        url: str,
        source_id: int,
        if_none_match: str | None = None,
        if_modified_since: str | None = None,
    ) -> FetchResult:
        last_error: Exception | None = None
        request_headers: dict[str, str] = {}
        if if_none_match:
            request_headers["If-None-Match"] = if_none_match
        if if_modified_since:
            request_headers["If-Modified-Since"] = if_modified_since

        for attempt in range(self._max_retries + 1):
            try:
                with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                    response = client.get(url, headers=request_headers or None)

                if response.status_code == 304:
                    return FetchResult(
                        content=None,
                        etag=response.headers.get("etag"),
                        last_modified=response.headers.get("last-modified"),
                        status_code=304,
                        not_modified=True,
                        fetched_at_utc=datetime.now(timezone.utc),
                    )

                if response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"Server error status={response.status_code}", request=response.request, response=response
                    )
                response.raise_for_status()

                return FetchResult(
                    content=response.content,
                    etag=response.headers.get("etag"),
                    last_modified=response.headers.get("last-modified"),
                    status_code=response.status_code,
                    not_modified=False,
                    fetched_at_utc=datetime.now(timezone.utc),
                )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt < self._max_retries:
                    sleep_seconds = min(0.5 * (2**attempt), 2.0)
                    time.sleep(sleep_seconds)
                else:
                    logger.warning("ICS fetch failed for source_id=%s after retries", source_id)

        assert last_error is not None
        raise last_error
