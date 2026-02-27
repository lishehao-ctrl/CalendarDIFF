from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.config import Settings, get_settings

_ALLOWED_EVENT_TYPES = {
    "deadline",
    "exam",
    "schedule_change",
    "assignment",
    "action_required",
    "announcement",
    "grade",
    "other",
}


class LlmRawExtract(BaseModel):
    deadline_text: str | None = None
    time_text: str | None = None
    location_text: str | None = None


class LlmActionItem(BaseModel):
    action: str | None = None
    due_iso: str | None = None
    where_text: str | None = None


class LlmExtractDecision(BaseModel):
    label: Literal["KEEP", "DROP"]
    event_type: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    raw_extract: LlmRawExtract = Field(default_factory=LlmRawExtract)
    action_items: list[LlmActionItem] = Field(default_factory=list)
    proposed_title: str | None = None

    @field_validator("label", mode="before")
    @classmethod
    def _normalize_label(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("event_type", mode="before")
    @classmethod
    def _normalize_event_type(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip().lower()
            return stripped or None
        return value

    @field_validator("event_type")
    @classmethod
    def _validate_event_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in _ALLOWED_EVENT_TYPES:
            raise ValueError("event_type is not supported")
        return value

    @field_validator("reasons", mode="before")
    @classmethod
    def _normalize_reasons(cls, value: object) -> object:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            stripped = item.strip()
            if not stripped:
                continue
            out.append(stripped)
            if len(out) >= 3:
                break
        return out


class EmailLlmFallbackError(RuntimeError):
    def __init__(self, *, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class EmailLlmRequestPayload:
    subject: str | None
    snippet: str | None
    body_text: str | None
    from_header: str | None
    internal_date: str | None
    timezone_name: str
    rule_event_type: str | None
    rule_score: float


class EmailLlmFallbackClient:
    def __init__(self, *, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._timeout = httpx.Timeout(
            connect=self._settings.http_connect_timeout_seconds,
            read=self._settings.email_llm_timeout_seconds,
            write=self._settings.email_llm_timeout_seconds,
            pool=self._settings.http_connect_timeout_seconds,
        )

    def extract_for_ambiguous_email(self, payload: EmailLlmRequestPayload) -> LlmExtractDecision:
        if not self._settings.email_llm_base_url or not self._settings.email_llm_api_key:
            raise EmailLlmFallbackError(
                code="llm_fallback_timeout",
                message="LLM fallback is enabled but base URL or API key is not configured",
            )

        request_payload = self._build_chat_payload(payload)
        response_json = self._request_with_retry(request_payload)
        llm_json = self._extract_llm_json(response_json)
        try:
            return LlmExtractDecision.model_validate(llm_json)
        except ValidationError as exc:
            raise EmailLlmFallbackError(
                code="llm_fallback_schema_invalid",
                message=f"LLM fallback JSON schema is invalid: {exc.errors()}",
            ) from exc

    def _request_with_retry(self, request_payload: dict) -> dict:
        attempts = max(int(self._settings.email_llm_max_retries), 0) + 1
        last_error: Exception | None = None
        for _ in range(attempts):
            try:
                return self._post_chat_completions(request_payload)
            except ValueError as exc:
                raise EmailLlmFallbackError(
                    code="llm_fallback_invalid_json",
                    message=f"LLM fallback HTTP response is not valid JSON: {exc}",
                ) from exc
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
        raise EmailLlmFallbackError(
            code="llm_fallback_timeout",
            message=f"LLM fallback request failed: {last_error}",
        )

    def _post_chat_completions(self, request_payload: dict) -> dict:
        url = _build_chat_completions_url(self._settings.email_llm_base_url)
        headers = {
            "Authorization": f"Bearer {self._settings.email_llm_api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
            response = client.post(url, headers=headers, json=request_payload)
        response.raise_for_status()
        parsed = response.json()
        if not isinstance(parsed, dict):
            raise ValueError("LLM fallback response must be a JSON object")
        return parsed

    def _build_chat_payload(self, payload: EmailLlmRequestPayload) -> dict:
        truncated_body = (payload.body_text or "")[: max(self._settings.email_llm_max_body_chars, 0)]
        user_payload = {
            "subject": payload.subject,
            "snippet": payload.snippet,
            "body_text": truncated_body,
            "from_header": payload.from_header,
            "internal_date": payload.internal_date,
            "timezone_name": payload.timezone_name,
            "rule_event_type": payload.rule_event_type,
            "rule_score": payload.rule_score,
        }
        system_prompt = (
            "You are an email event extractor for an academic deadline tracker. "
            "Return JSON only. Decide whether this email should enter review queue. "
            "Use label KEEP only when actionable. "
            "If uncertain, return DROP with lower confidence."
        )
        user_prompt = (
            "Extract structured decision with schema: "
            "{label,event_type,confidence,reasons,raw_extract,action_items,proposed_title}. "
            "Event types: deadline, exam, schedule_change, assignment, action_required, announcement, grade, other. "
            "Keep reasons concise (max 3).\n"
            f"INPUT_JSON:\n{json.dumps(user_payload, ensure_ascii=True)}"
        )
        return {
            "model": self._settings.email_llm_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

    def _extract_llm_json(self, response_json: dict) -> dict:
        choices = response_json.get("choices")
        if not isinstance(choices, list) or not choices:
            raise EmailLlmFallbackError(code="llm_fallback_invalid_json", message="LLM fallback response has no choices")
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise EmailLlmFallbackError(code="llm_fallback_invalid_json", message="LLM fallback choice payload is invalid")
        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise EmailLlmFallbackError(code="llm_fallback_invalid_json", message="LLM fallback message payload is invalid")

        content = message.get("content")
        raw_text = _extract_text_content(content)
        if raw_text is None:
            raise EmailLlmFallbackError(code="llm_fallback_invalid_json", message="LLM fallback content is empty")

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise EmailLlmFallbackError(code="llm_fallback_invalid_json", message="LLM fallback content is not JSON") from exc

        if not isinstance(parsed, dict):
            raise EmailLlmFallbackError(code="llm_fallback_invalid_json", message="LLM fallback JSON must be an object")
        return parsed


def _extract_text_content(content: object) -> str | None:
    if isinstance(content, str):
        stripped = content.strip()
        return stripped or None
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())
        if chunks:
            return "\n".join(chunks)
    return None


def _build_chat_completions_url(base_url: str | None) -> str:
    if not base_url or not base_url.strip():
        raise ValueError("email_llm_base_url is required")
    normalized = base_url.strip().rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"
