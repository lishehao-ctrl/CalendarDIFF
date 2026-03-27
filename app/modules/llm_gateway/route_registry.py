from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.modules.llm_gateway.contracts import (
    LlmInvokeRequest,
    LlmStreamRequest,
    ResolvedLlmProfile,
)
from app.modules.llm_gateway.registry import (
    resolve_agent_llm_profile,
    resolve_helper_llm_profile,
    resolve_judge_llm_profile,
    resolve_llm_profile,
)


@dataclass(frozen=True)
class ResolvedLlmRoute:
    route_id: str
    profile: ResolvedLlmProfile
    is_fallback: bool


def resolve_llm_routes(
    db: Session | None,
    *,
    invoke_request: LlmInvokeRequest | LlmStreamRequest,
) -> list[ResolvedLlmRoute]:
    primary = _resolve_profile_for_request(
        db,
        invoke_request=invoke_request,
        explicit_provider_id=None,
        explicit_protocol=invoke_request.protocol_override,
    )
    routes = [
        ResolvedLlmRoute(
            route_id=f"{invoke_request.profile_family}:{primary.provider_id}:{primary.protocol}:primary",
            profile=primary,
            is_fallback=False,
        )
    ]
    return routes


def _resolve_profile_for_request(
    db: Session | None,
    *,
    invoke_request: LlmInvokeRequest | LlmStreamRequest,
    explicit_provider_id: str | None,
    explicit_protocol: str | None,
) -> ResolvedLlmProfile:
    if invoke_request.profile_family == "agent":
        return resolve_agent_llm_profile(
            explicit_provider_id=explicit_provider_id,
            explicit_protocol=explicit_protocol,  # type: ignore[arg-type]
        )
    if invoke_request.profile_family == "helper":
        return resolve_helper_llm_profile(
            explicit_provider_id=explicit_provider_id,
            explicit_protocol=explicit_protocol,  # type: ignore[arg-type]
        )
    if invoke_request.profile_family == "judge":
        return resolve_judge_llm_profile(
            explicit_provider_id=explicit_provider_id,
            explicit_protocol=explicit_protocol,  # type: ignore[arg-type]
        )
    return resolve_llm_profile(
        db,
        source_id=invoke_request.source_id,
        explicit_provider_id=explicit_provider_id,
        explicit_protocol=explicit_protocol,  # type: ignore[arg-type]
    )

__all__ = [
    "ResolvedLlmRoute",
    "resolve_llm_routes",
]
