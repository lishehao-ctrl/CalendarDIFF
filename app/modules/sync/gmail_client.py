from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings
from app.core.oauth_config import build_oauth_runtime_config

_REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class GmailOAuthTokens:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None


@dataclass(frozen=True)
class GmailOAuthClientSecrets:
    client_id: str
    client_secret: str
    redirect_uris: tuple[str, ...]


@dataclass(frozen=True)
class GmailProfile:
    email_address: str
    history_id: str | None


@dataclass(frozen=True)
class GmailLabel:
    id: str
    name: str


@dataclass(frozen=True)
class GmailHistoryResult:
    message_ids: list[str]
    history_id: str | None


@dataclass(frozen=True)
class GmailMessageMetadata:
    message_id: str
    thread_id: str | None
    snippet: str
    body_text: str | None
    internal_date: str | None
    subject: str
    from_header: str
    label_ids: list[str]


class GmailAPIError(RuntimeError):
    def __init__(self, *, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(message)


class GmailHistoryExpiredError(GmailAPIError):
    pass


class GmailClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._settings = settings
        self._oauth_runtime = build_oauth_runtime_config(settings=settings)
        self._oauth_authorize_url = _normalize_endpoint(settings.gmail_oauth_authorize_url)
        self._oauth_token_url = _normalize_endpoint(settings.gmail_oauth_token_url)
        self._gmail_api_base = _normalize_endpoint(settings.gmail_api_base_url)
        self._timeout = httpx.Timeout(
            connect=settings.http_connect_timeout_seconds,
            read=settings.http_read_timeout_seconds,
            write=settings.http_read_timeout_seconds,
            pool=settings.http_connect_timeout_seconds,
        )

    def build_authorization_url(self, *, state: str) -> str:
        oauth_client = self._load_oauth_client_secrets()
        redirect_uri = self._resolve_redirect_uri(oauth_client=oauth_client)
        params = {
            "client_id": oauth_client.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": self._oauth_runtime.gmail_scope,
            "access_type": self._oauth_runtime.gmail_access_type,
            "include_granted_scopes": "true" if self._oauth_runtime.gmail_include_granted_scopes else "false",
            "prompt": self._oauth_runtime.gmail_prompt,
            "state": state,
        }
        return f"{self._oauth_authorize_url}?{urlencode(params)}"

    def exchange_code(self, *, code: str) -> GmailOAuthTokens:
        oauth_client = self._load_oauth_client_secrets()
        redirect_uri = self._resolve_redirect_uri(oauth_client=oauth_client)
        payload = {
            "code": code,
            "client_id": oauth_client.client_id,
            "client_secret": oauth_client.client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        response_json = self._post_token(payload)
        return _parse_oauth_tokens(response_json)

    def refresh_access_token(self, *, refresh_token: str) -> GmailOAuthTokens:
        oauth_client = self._load_oauth_client_secrets()
        payload = {
            "client_id": oauth_client.client_id,
            "client_secret": oauth_client.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        response_json = self._post_token(payload)
        return _parse_oauth_tokens(response_json)

    def get_profile(self, *, access_token: str) -> GmailProfile:
        payload = self._get_json("/profile", access_token=access_token)
        email_address = str(payload.get("emailAddress") or "")
        history_id_raw = payload.get("historyId")
        history_id = str(history_id_raw) if history_id_raw is not None else None
        return GmailProfile(email_address=email_address, history_id=history_id)

    def list_labels(self, *, access_token: str) -> list[GmailLabel]:
        payload = self._get_json("/labels", access_token=access_token)
        labels: list[GmailLabel] = []
        for item in payload.get("labels", []) or []:
            if not isinstance(item, dict):
                continue
            label_id = item.get("id")
            name = item.get("name")
            if isinstance(label_id, str) and label_id and isinstance(name, str) and name:
                labels.append(GmailLabel(id=label_id, name=name))
        return labels

    def list_history(self, *, access_token: str, start_history_id: str) -> GmailHistoryResult:
        message_ids: list[str] = []
        seen_ids: set[str] = set()
        page_token: str | None = None
        latest_history_id: str | None = None

        while True:
            params: dict[str, str | int | float | bool | None] = {
                "startHistoryId": start_history_id,
                "historyTypes": "messageAdded",
                "maxResults": "500",
            }
            if page_token is not None:
                params["pageToken"] = page_token
            payload = self._get_json("/history", access_token=access_token, params=params)
            history_id_raw = payload.get("historyId")
            if history_id_raw is not None:
                latest_history_id = str(history_id_raw)

            for history_item in payload.get("history", []) or []:
                if not isinstance(history_item, dict):
                    continue
                for added in history_item.get("messagesAdded", []) or []:
                    if not isinstance(added, dict):
                        continue
                    message = added.get("message")
                    if not isinstance(message, dict):
                        continue
                    message_id = message.get("id")
                    if isinstance(message_id, str) and message_id and message_id not in seen_ids:
                        seen_ids.add(message_id)
                        message_ids.append(message_id)

            next_page_token = payload.get("nextPageToken")
            if not isinstance(next_page_token, str) or not next_page_token:
                break
            page_token = next_page_token

        return GmailHistoryResult(message_ids=message_ids, history_id=latest_history_id)

    def list_message_ids(
        self,
        *,
        access_token: str,
        query: str | None = None,
        label_ids: Sequence[str] | None = None,
    ) -> list[str]:
        message_ids: list[str] = []
        seen_ids: set[str] = set()
        page_token: str | None = None

        while True:
            params: dict[str, str | int | float | bool | None | Sequence[str]] = {
                "maxResults": "500",
            }
            if query:
                params["q"] = query
            if label_ids:
                params["labelIds"] = [label for label in label_ids if isinstance(label, str) and label.strip()]
            if page_token is not None:
                params["pageToken"] = page_token
            payload = self._get_json("/messages", access_token=access_token, params=params)
            for item in payload.get("messages", []) or []:
                if not isinstance(item, dict):
                    continue
                message_id = item.get("id")
                if isinstance(message_id, str) and message_id and message_id not in seen_ids:
                    seen_ids.add(message_id)
                    message_ids.append(message_id)

            next_page_token = payload.get("nextPageToken")
            if not isinstance(next_page_token, str) or not next_page_token:
                break
            page_token = next_page_token

        return message_ids

    def get_message_metadata(self, *, access_token: str, message_id: str) -> GmailMessageMetadata:
        payload = self._get_json(
            f"/messages/{message_id}",
            access_token=access_token,
            params={"format": "full"},
        )
        thread_id = str(payload.get("threadId") or "") or None
        snippet = str(payload.get("snippet") or "")
        internal_date_raw = payload.get("internalDate")
        internal_date = _internal_date_ms_to_iso8601(internal_date_raw)

        label_ids: list[str] = []
        for label_id in payload.get("labelIds", []) or []:
            if isinstance(label_id, str) and label_id:
                label_ids.append(label_id)

        subject = ""
        from_header = ""
        payload_obj = payload.get("payload")
        body_text: str | None = None
        if isinstance(payload_obj, dict):
            for header in payload_obj.get("headers", []) or []:
                if not isinstance(header, dict):
                    continue
                name = str(header.get("name") or "")
                value = str(header.get("value") or "")
                if name.lower() == "subject":
                    subject = value
                if name.lower() == "from":
                    from_header = value
            body_text = _extract_plain_text_from_payload(payload_obj)

        return GmailMessageMetadata(
            message_id=message_id,
            thread_id=thread_id,
            snippet=snippet,
            body_text=body_text,
            internal_date=internal_date,
            subject=subject,
            from_header=from_header,
            label_ids=label_ids,
        )

    def _post_token(self, payload: dict[str, str]) -> dict:
        with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
            response = client.post(self._oauth_token_url, data=payload)
        self._raise_for_api_error(response)
        return response.json()

    def _get_json(
        self,
        path: str,
        *,
        access_token: str,
        params: Mapping[
            str,
            str | int | float | bool | None | Sequence[str | int | float | bool | None],
        ]
        | None = None,
    ) -> dict:
        with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
            response = client.get(
                f"{self._gmail_api_base}{path}",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )
        self._raise_for_api_error(response)
        return response.json()

    def _raise_for_api_error(self, response: httpx.Response) -> None:
        if response.is_success:
            return
        detail = _extract_gmail_error_message(response)
        if response.status_code == 404 and "history" in detail.lower():
            raise GmailHistoryExpiredError(status_code=response.status_code, message=detail)
        raise GmailAPIError(status_code=response.status_code, message=detail)

    def _load_oauth_client_secrets(self) -> GmailOAuthClientSecrets:
        return _load_oauth_client_secrets(self._settings.gmail_oauth_client_secrets_file)

    def _resolve_redirect_uri(self, *, oauth_client: GmailOAuthClientSecrets) -> str:
        redirect_uri = self._oauth_runtime.gmail_redirect_uri
        if redirect_uri not in oauth_client.redirect_uris:
            raise RuntimeError(
                "OAuth redirect URI is not registered in Gmail OAuth client secrets; "
                "check OAUTH_PUBLIC_BASE_URL/OAUTH_ROUTE_PREFIX/OAUTH_CALLBACK_ROUTE_TEMPLATE and Google OAuth settings"
            )
        return redirect_uri


def _load_oauth_client_secrets(file_path: str | None) -> GmailOAuthClientSecrets:
    if not file_path or not file_path.strip():
        raise RuntimeError("Gmail OAuth client secrets file is not configured")

    candidate = Path(file_path).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise RuntimeError("Gmail OAuth client secrets file was not found") from exc
    except Exception as exc:
        raise RuntimeError("Gmail OAuth client secrets file path is invalid") from exc

    if not resolved.is_file():
        raise RuntimeError("Gmail OAuth client secrets path must be a regular file")

    repo_root = _REPO_ROOT.resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError:
        pass
    else:
        raise RuntimeError("Gmail OAuth client secrets file must be outside the repository")

    _assert_oauth_secrets_permissions(resolved)

    try:
        raw_content = resolved.read_text(encoding="utf-8")
    except Exception as exc:
        raise RuntimeError("Failed to read Gmail OAuth client secrets file") from exc

    payload = _parse_client_secrets_payload(raw_content)
    return _extract_oauth_client_secrets(payload)


def _assert_oauth_secrets_permissions(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        mode = path.stat().st_mode & 0o777
    except Exception as exc:
        raise RuntimeError("Failed to read Gmail OAuth client secrets file permissions") from exc
    if mode & 0o077:
        raise RuntimeError("Gmail OAuth client secrets file permissions are too open; run chmod 600")


def _parse_client_secrets_payload(raw_content: str) -> dict[str, object]:
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError:
        payload = _parse_single_record_jsonl(raw_content)
    if not isinstance(payload, dict):
        raise RuntimeError("Gmail OAuth client secrets file content is invalid")
    return payload


def _parse_single_record_jsonl(raw_content: str) -> dict[str, object]:
    lines = [line.strip() for line in raw_content.splitlines() if line.strip()]
    if len(lines) != 1:
        raise RuntimeError("Gmail OAuth client secrets file content is invalid")
    try:
        payload = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise RuntimeError("Gmail OAuth client secrets file content is invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Gmail OAuth client secrets file content is invalid")
    return payload


def _extract_oauth_client_secrets(payload: dict[str, object]) -> GmailOAuthClientSecrets:
    web_payload = payload.get("web")
    if not isinstance(web_payload, dict):
        raise RuntimeError("Gmail OAuth client secrets file missing web client configuration")

    client_id = str(web_payload.get("client_id") or "").strip()
    client_secret = str(web_payload.get("client_secret") or "").strip()

    redirect_uris: list[str] = []
    redirect_uris_raw = web_payload.get("redirect_uris")
    if isinstance(redirect_uris_raw, list):
        for value in redirect_uris_raw:
            if isinstance(value, str) and value.strip():
                redirect_uris.append(value.strip())

    if not client_id or not client_secret or not redirect_uris:
        raise RuntimeError("Gmail OAuth client secrets file missing required fields")

    return GmailOAuthClientSecrets(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uris=tuple(redirect_uris),
    )


def _parse_oauth_tokens(payload: dict) -> GmailOAuthTokens:
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("Missing access_token in Gmail OAuth response")

    refresh_token_raw = payload.get("refresh_token")
    refresh_token = refresh_token_raw if isinstance(refresh_token_raw, str) and refresh_token_raw else None

    expires_in_raw = payload.get("expires_in")
    expires_at: datetime | None = None
    if isinstance(expires_in_raw, (int, float)):
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(int(expires_in_raw), 0))

    return GmailOAuthTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    )


def _extract_gmail_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        return f"Gmail API error status={response.status_code}"

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message:
                return message
            errors = error.get("errors")
            if isinstance(errors, list) and errors:
                first = errors[0]
                if isinstance(first, dict):
                    reason = first.get("reason")
                    if isinstance(reason, str) and reason:
                        return reason
        elif isinstance(error, str) and error:
            return error
    return f"Gmail API error status={response.status_code}"


def _internal_date_ms_to_iso8601(value: object) -> str | None:
    try:
        milliseconds = int(str(value))
    except Exception:
        return None
    return datetime.fromtimestamp(milliseconds / 1000.0, tz=timezone.utc).isoformat()


def _extract_plain_text_from_payload(payload: dict) -> str | None:
    # Prefer plain-text body without persisting raw email content anywhere.
    text = _extract_plain_text_from_part(payload)
    if text is None:
        return None
    cleaned = text.strip()
    if not cleaned:
        return None
    return cleaned[:20000]


def _extract_plain_text_from_part(part: dict) -> str | None:
    mime_type = str(part.get("mimeType") or "").lower()
    body = part.get("body")
    if mime_type.startswith("text/plain") and isinstance(body, dict):
        data = body.get("data")
        decoded = _decode_base64url_to_text(data)
        if decoded is not None and decoded.strip():
            return decoded

    parts = part.get("parts")
    if isinstance(parts, list):
        for child in parts:
            if not isinstance(child, dict):
                continue
            extracted = _extract_plain_text_from_part(child)
            if extracted is not None and extracted.strip():
                return extracted

    if isinstance(body, dict):
        data = body.get("data")
        decoded = _decode_base64url_to_text(data)
        if decoded is not None and decoded.strip():
            return decoded
    return None


def _decode_base64url_to_text(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        # Gmail uses URL-safe base64 without padding.
        padded = value + "=" * (-len(value) % 4)
        decoded_bytes = base64.urlsafe_b64decode(padded.encode("utf-8"))
        return decoded_bytes.decode("utf-8", errors="replace")
    except Exception:
        return None


def _normalize_endpoint(value: str) -> str:
    text = value.strip()
    if not text:
        raise RuntimeError("Gmail endpoint URL must not be blank")
    return text.rstrip("/")
