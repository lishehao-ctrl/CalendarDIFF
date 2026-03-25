from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.modules.llm_gateway.contracts import (
    LlmInvokeRequest,
    LlmStreamRequest,
    ResolvedLlmProfile,
)
from app.modules.llm_gateway.route_policy import resolve_route_policy
from app.modules.llm_gateway.registry import (
    resolve_agent_llm_profile,
    resolve_llm_profile,
    resolve_provider_fallback_ids,
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
    policy = resolve_route_policy(
        invoke_request=invoke_request,
        primary_protocol=primary.protocol,
    )
    if not policy.allow_fallback or policy.max_routes <= 1:
        return routes

    for protocol in policy.fallback_protocols:
        if len(routes) >= policy.max_routes:
            break
        try:
            fallback = _resolve_profile_for_request(
                db,
                invoke_request=invoke_request,
                explicit_provider_id=primary.provider_id,
                explicit_protocol=protocol,
            )
        except Exception:
            continue
        if not _same_route(primary, fallback):
            routes.append(
                ResolvedLlmRoute(
                    route_id=f"{invoke_request.profile_family}:{fallback.provider_id}:{fallback.protocol}:fallback",
                    profile=fallback,
                    is_fallback=True,
                )
            )

    for provider_id in resolve_provider_fallback_ids(provider_id=primary.provider_id):
        if len(routes) >= policy.max_routes:
            break
        fallback = _resolve_profile_for_request(
            db,
            invoke_request=invoke_request,
            explicit_provider_id=provider_id,
            explicit_protocol=None,
        )
        if fallback.vendor != primary.vendor or _same_route(primary, fallback):
            continue
        routes.append(
            ResolvedLlmRoute(
                route_id=f"{invoke_request.profile_family}:{fallback.provider_id}:{fallback.protocol}:fallback",
                profile=fallback,
                is_fallback=True,
            )
        )
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
    return resolve_llm_profile(
        db,
        source_id=invoke_request.source_id,
        explicit_provider_id=explicit_provider_id,
        explicit_protocol=explicit_protocol,  # type: ignore[arg-type]
    )


def _same_route(left: ResolvedLlmProfile, right: ResolvedLlmProfile) -> bool:
    return (
        left.provider_id == right.provider_id
        and left.base_url == right.base_url
        and left.model == right.model
        and left.protocol == right.protocol
        and left.vendor == right.vendor
    )


__all__ = [
    "ResolvedLlmRoute",
    "resolve_llm_routes",
]
