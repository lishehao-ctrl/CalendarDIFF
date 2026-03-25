from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.shared import User
from app.modules.common.language import DEFAULT_LANGUAGE_CODE, LanguageCodeLiteral, normalize_language_code

AgentLanguageResolutionSource = Literal["explicit", "detected_input", "user_profile", "default"]


@dataclass(frozen=True)
class AgentLanguageContext:
    effective_language_code: LanguageCodeLiteral
    input_language_code: LanguageCodeLiteral | None
    system_language_code: LanguageCodeLiteral
    resolution_source: AgentLanguageResolutionSource


def resolve_agent_language_context(
    db: Session,
    *,
    user_id: int,
    explicit_language_code: str | None = None,
    input_texts: Iterable[str | None] | None = None,
) -> AgentLanguageContext:
    system_language_code = _load_user_language_code(db=db, user_id=user_id)
    explicit = _normalize_optional_language_code(explicit_language_code)
    if explicit is not None:
        return AgentLanguageContext(
            effective_language_code=explicit,
            input_language_code=None,
            system_language_code=system_language_code,
            resolution_source="explicit",
        )

    detected_input_language = detect_agent_input_language(input_texts or [])
    if detected_input_language is not None:
        return AgentLanguageContext(
            effective_language_code=detected_input_language,
            input_language_code=detected_input_language,
            system_language_code=system_language_code,
            resolution_source="detected_input",
        )

    if system_language_code != DEFAULT_LANGUAGE_CODE:
        return AgentLanguageContext(
            effective_language_code=system_language_code,
            input_language_code=None,
            system_language_code=system_language_code,
            resolution_source="user_profile",
        )

    return AgentLanguageContext(
        effective_language_code=DEFAULT_LANGUAGE_CODE,
        input_language_code=None,
        system_language_code=DEFAULT_LANGUAGE_CODE,
        resolution_source="default",
    )


def detect_agent_input_language(values: Iterable[str | None]) -> LanguageCodeLiteral | None:
    texts = [value.strip() for value in values if isinstance(value, str) and value.strip()]
    if not texts:
        return None
    combined = " ".join(texts)
    cjk_count = sum(1 for ch in combined if _is_cjk(ch))
    latin_count = sum(1 for ch in combined if ("a" <= ch.lower() <= "z"))

    if cjk_count == 0 and latin_count == 0:
        return None
    if cjk_count > 0 and latin_count == 0:
        return "zh-CN"
    if latin_count > 0 and cjk_count == 0:
        return "en"
    if cjk_count >= 4 and cjk_count >= max(int(latin_count * 0.35), 1):
        return "zh-CN"
    if latin_count >= 8 and latin_count >= max(cjk_count * 3, 1):
        return "en"
    return None


def collect_agent_input_texts(value: object) -> list[str]:
    collected: list[str] = []
    _collect_texts_into(value, collected)
    return [item for item in collected if item]


def agent_output_language_mismatch(*, target_language_code: LanguageCodeLiteral, texts: Iterable[str | None]) -> bool:
    detected = detect_agent_input_language(texts)
    if detected is None:
        return False
    return detected != target_language_code


def _collect_texts_into(value: object, output: list[str]) -> None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            output.append(stripped)
        return
    if isinstance(value, dict):
        for item in value.values():
            _collect_texts_into(item, output)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            _collect_texts_into(item, output)


def _load_user_language_code(*, db: Session, user_id: int) -> LanguageCodeLiteral:
    raw = db.scalar(select(User.language_code).where(User.id == user_id).limit(1))
    normalized = _normalize_optional_language_code(raw)
    return normalized or DEFAULT_LANGUAGE_CODE


def _normalize_optional_language_code(value: str | None) -> LanguageCodeLiteral | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return normalize_language_code(value)
    except ValueError:
        return None


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0xF900 <= code <= 0xFAFF
    )


__all__ = [
    "AgentLanguageContext",
    "AgentLanguageResolutionSource",
    "agent_output_language_mismatch",
    "collect_agent_input_texts",
    "detect_agent_input_language",
    "resolve_agent_language_context",
]
