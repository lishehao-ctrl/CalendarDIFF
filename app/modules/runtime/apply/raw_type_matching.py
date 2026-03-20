from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.modules.llm_gateway import LlmGatewayError, LlmInvokeRequest, invoke_llm_json
from app.modules.common.course_identity import normalize_label_token


class RawTypeMatchSchema(BaseModel):
    matched_raw_type: str | None = Field(default=None, max_length=128)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: str = Field(default="", max_length=255)

    @field_validator("matched_raw_type", mode="before")
    @classmethod
    def _normalize_raw_type(cls, value: object) -> object:
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("evidence", mode="before")
    @classmethod
    def _normalize_evidence(cls, value: object) -> object:
        if not isinstance(value, str):
            return ""
        return value.strip()[:255]


class RawTypeMatchError(RuntimeError):
    pass


def compare_raw_type_against_known_types(
    db: Session,
    *,
    source_id: int | None,
    request_id: str | None,
    provider: str | None,
    course_key: str,
    incoming_raw_type: str,
    event_name: str,
    ordinal: int | None,
    known_raw_types: list[str],
) -> dict[str, object]:
    normalized_incoming = normalize_label_token(incoming_raw_type)
    normalized_candidates = {
        normalize_label_token(item): item.strip()[:128]
        for item in known_raw_types
        if isinstance(item, str) and normalize_label_token(item)
    }
    if not normalized_candidates:
        return {"matched_raw_type": None, "confidence": 0.0, "evidence": ""}
    if normalized_incoming in normalized_candidates:
        return {
            "matched_raw_type": normalized_candidates[normalized_incoming],
            "confidence": 1.0,
            "evidence": "exact_normalized_match",
        }

    invoke_request = LlmInvokeRequest(
        task_name="course_raw_type_match",
        system_prompt=(
            "You compare one incoming academic work-item raw type against known raw types for the same course. "
            "Return JSON only with schema: {\"matched_raw_type\": string|null, \"confidence\": number, \"evidence\": string}. "
            "Choose a candidate only when it is clearly the same academic work-item type label family. "
            "Do not invent new labels. Use null when uncertain."
        ),
        user_payload={
            "course_key": course_key,
            "incoming_raw_type": incoming_raw_type,
            "event_name": event_name,
            "ordinal": ordinal,
            "known_raw_types": sorted(normalized_candidates.values()),
        },
        output_schema_name="RawTypeMatchSchema",
        output_schema_json=RawTypeMatchSchema.model_json_schema(),
        source_id=source_id,
        source_provider=provider,
        request_id=request_id,
    )

    try:
        invoke_result = invoke_llm_json(db, invoke_request=invoke_request)
        parsed = RawTypeMatchSchema.model_validate(invoke_result.json_object)
    except (LlmGatewayError, Exception) as exc:
        raise RawTypeMatchError(str(exc)) from exc

    normalized_match = normalize_label_token(parsed.matched_raw_type)
    if not normalized_match or normalized_match not in normalized_candidates:
        return {"matched_raw_type": None, "confidence": float(parsed.confidence), "evidence": parsed.evidence}
    return {
        "matched_raw_type": normalized_candidates[normalized_match],
        "confidence": float(parsed.confidence),
        "evidence": parsed.evidence,
    }
