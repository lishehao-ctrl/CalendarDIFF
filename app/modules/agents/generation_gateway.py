from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.agents.language_context import AgentLanguageContext, agent_output_language_mismatch
from app.modules.llm_gateway import LlmGatewayError, LlmInvokeRequest, invoke_llm_typed

logger = logging.getLogger(__name__)

AgentProposalKindLiteral = Literal["change_decision", "source_recovery", "family_relink_preview", "proposal_edit_commit"]

AGENT_GENERATION_MODE_DETERMINISTIC = "deterministic"
AGENT_GENERATION_MODE_LLM_ASSISTED = "llm_assisted"
_AGENT_GENERATION_MODES = {
    AGENT_GENERATION_MODE_DETERMINISTIC,
    AGENT_GENERATION_MODE_LLM_ASSISTED,
}

_SUMMARY_MAX_CHARS = 180
_REASON_MAX_CHARS = 600

_AGENT_PROPOSAL_SYSTEM_PROMPT = (
    "You rewrite proposal copy for CalendarDIFF's bounded review agent. "
    "Keep the action, risk level, and execution boundary fixed. "
    "Do not invent facts that are not present in the provided context. "
    "Summary must be a single short sentence. "
    "Reason must be concise, specific, and grounded in the provided target snapshot. "
    "The output language must follow target_language_code. "
    "input_language_code is only a comprehension hint and does not override target_language_code. "
    "Do not translate raw evidence, event names, family names, raw types, or source-native labels unless they are already system-owned copy. "
    "Never mention internal model behavior, JSON, schemas, or hidden system state. "
    "Return JSON only."
)


@dataclass(frozen=True)
class AgentProposalDraft:
    summary: str
    summary_code: str
    summary_params_json: dict
    reason: str
    reason_code: str
    reason_params_json: dict
    risk_level: str
    confidence: float
    suggested_action: str
    payload_json: dict
    context_json: dict
    target_snapshot_json: dict


@dataclass(frozen=True)
class AgentProposalDraftRequest:
    proposal_kind: AgentProposalKindLiteral
    target_kind: str
    target_id: str
    origin_request_id: str | None
    language_context: AgentLanguageContext
    deterministic_draft: AgentProposalDraft


class AgentProposalNarrativeResponse(BaseModel):
    summary: str = Field(min_length=1, max_length=_SUMMARY_MAX_CHARS)
    reason: str = Field(min_length=1, max_length=_REASON_MAX_CHARS)

    model_config = {"extra": "forbid"}


def generate_agent_proposal_draft(
    db: Session,
    *,
    draft_request: AgentProposalDraftRequest,
) -> AgentProposalDraft:
    mode = _resolve_agent_generation_mode()
    if mode != AGENT_GENERATION_MODE_LLM_ASSISTED:
        return draft_request.deterministic_draft

    try:
        llm_result = invoke_llm_typed(
            db,
            invoke_request=LlmInvokeRequest(
                task_name=f"agent_{draft_request.proposal_kind}_proposal_narrative",
                system_prompt=_AGENT_PROPOSAL_SYSTEM_PROMPT,
                user_payload=_build_user_payload(draft_request=draft_request),
                output_schema_name="AgentProposalNarrativeResponse",
                output_schema_json=AgentProposalNarrativeResponse.model_json_schema(),
                profile_family="agent",
                source_id=_resolve_source_id(draft_request=draft_request),
                request_id=_normalize_origin_request_id(draft_request.origin_request_id),
                temperature=0.0,
                session_cache_mode="disable",
            ),
            response_model=AgentProposalNarrativeResponse,
            validation_label=f"agent_{draft_request.proposal_kind}_proposal_narrative",
        )
        narrative = llm_result.value
    except (LlmGatewayError, ValidationError) as exc:
        logger.warning(
            "agents.generation_gateway.fallback proposal_kind=%s target_kind=%s target_id=%s error=%s",
            draft_request.proposal_kind,
            draft_request.target_kind,
            draft_request.target_id,
            exc,
        )
        return draft_request.deterministic_draft

    if agent_output_language_mismatch(
        target_language_code=draft_request.language_context.effective_language_code,
        texts=(narrative.summary, narrative.reason),
    ):
        logger.warning(
            "agents.generation_gateway.language_mismatch proposal_kind=%s target_kind=%s target_id=%s target_language=%s",
            draft_request.proposal_kind,
            draft_request.target_kind,
            draft_request.target_id,
            draft_request.language_context.effective_language_code,
        )
        return draft_request.deterministic_draft

    summary = _normalize_text(
        narrative.summary,
        fallback=draft_request.deterministic_draft.summary,
        max_chars=_SUMMARY_MAX_CHARS,
    )
    reason = _normalize_text(
        narrative.reason,
        fallback=draft_request.deterministic_draft.reason,
        max_chars=_REASON_MAX_CHARS,
    )
    logger.info(
        "agents.generation_gateway.llm_assisted proposal_kind=%s target_kind=%s target_id=%s",
        draft_request.proposal_kind,
        draft_request.target_kind,
        draft_request.target_id,
    )
    return replace(
        draft_request.deterministic_draft,
        summary=summary,
        reason=reason,
    )


def _build_user_payload(*, draft_request: AgentProposalDraftRequest) -> dict:
    draft = draft_request.deterministic_draft
    return {
        "product": "CalendarDIFF",
        "target_language_code": draft_request.language_context.effective_language_code,
        "system_language_code": draft_request.language_context.system_language_code,
        "input_language_code": draft_request.language_context.input_language_code,
        "language_resolution_source": draft_request.language_context.resolution_source,
        "proposal_kind": draft_request.proposal_kind,
        "target_kind": draft_request.target_kind,
        "target_id": draft_request.target_id,
        "execution_boundary": _execution_boundary(payload=draft.payload_json),
        "deterministic_draft": {
            "summary": draft.summary,
            "reason": draft.reason,
            "summary_code": draft.summary_code,
            "reason_code": draft.reason_code,
            "summary_params": draft.summary_params_json,
            "reason_params": draft.reason_params_json,
            "risk_level": draft.risk_level,
            "confidence": draft.confidence,
            "suggested_action": draft.suggested_action,
            "payload_kind": str((draft.payload_json or {}).get("kind") or ""),
        },
        "context_snapshot": draft.context_json or {},
        "target_snapshot": draft.target_snapshot_json or {},
    }


def _execution_boundary(*, payload: dict) -> str:
    kind = str((payload or {}).get("kind") or "")
    if kind in {"change_decision", "run_source_sync", "family_relink_commit", "label_learning_add_alias_commit", "proposal_edit_commit"}:
        return "approval_ticket_required"
    return "web_only"


def _normalize_origin_request_id(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[:64]


def _resolve_source_id(*, draft_request: AgentProposalDraftRequest) -> int | None:
    if draft_request.target_kind != "source":
        return None
    try:
        return int(draft_request.target_id)
    except (TypeError, ValueError):
        return None


def _normalize_text(value: str, *, fallback: str, max_chars: int) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    if not normalized:
        return fallback
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3].rstrip() + "..."


def _resolve_agent_generation_mode() -> str:
    mode = str(get_settings().agent_generation_mode or AGENT_GENERATION_MODE_DETERMINISTIC).strip().lower()
    if mode in _AGENT_GENERATION_MODES:
        return mode
    logger.warning("agents.generation_gateway.invalid_mode mode=%s fallback=%s", mode, AGENT_GENERATION_MODE_DETERMINISTIC)
    return AGENT_GENERATION_MODE_DETERMINISTIC


__all__ = [
    "AgentProposalDraft",
    "AgentProposalDraftRequest",
    "generate_agent_proposal_draft",
]
