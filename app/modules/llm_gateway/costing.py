from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.core.config import get_settings

_TOKEN_DENOMINATOR = Decimal("1000000")
_USD_QUANTIZE = Decimal("0.000001")
_COST_KEYS = (
    "estimated_cost_usd",
    "input_cost_usd",
    "cached_input_cost_usd",
    "output_cost_usd",
)
_QWEN_FLASH_US_MODEL_ALIASES = {
    "qwen3.5-flash",
    "qwen-flash",
    "qwen-flash-us",
}


@dataclass(frozen=True)
class _PricingDefinition:
    pricing_key: str
    input_per_1m_usd: Decimal
    cached_input_per_1m_usd: Decimal
    output_per_1m_usd: Decimal


def estimate_llm_usage_cost(
    *,
    provider_id: str | None,
    vendor: str | None,
    model: str | None,
    protocol: str | None,
    usage: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized_usage = _normalize_usage(usage)
    has_usage_fields = isinstance(usage, dict) and any(
        key in usage for key in ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")
    )
    pricing = _resolve_pricing(
        provider_id=provider_id,
        vendor=vendor,
        model=model,
        protocol=protocol,
    )
    if pricing is None or not has_usage_fields:
        return {
            "estimated_cost_usd": None,
            "input_cost_usd": None,
            "cached_input_cost_usd": None,
            "output_cost_usd": None,
            "pricing_available": False,
            "pricing_key": None,
        }

    input_tokens = max(normalized_usage["input_tokens"], 0)
    cached_input_tokens = max(min(normalized_usage["cached_input_tokens"], input_tokens), 0)
    uncached_input_tokens = max(input_tokens - cached_input_tokens, 0)
    output_tokens = max(normalized_usage["output_tokens"], 0)

    input_cost = (Decimal(uncached_input_tokens) * pricing.input_per_1m_usd) / _TOKEN_DENOMINATOR
    cached_input_cost = (Decimal(cached_input_tokens) * pricing.cached_input_per_1m_usd) / _TOKEN_DENOMINATOR
    output_cost = (Decimal(output_tokens) * pricing.output_per_1m_usd) / _TOKEN_DENOMINATOR
    total_cost = input_cost + cached_input_cost + output_cost
    return {
        "estimated_cost_usd": _decimal_to_usd(total_cost),
        "input_cost_usd": _decimal_to_usd(input_cost),
        "cached_input_cost_usd": _decimal_to_usd(cached_input_cost),
        "output_cost_usd": _decimal_to_usd(output_cost),
        "pricing_available": True,
        "pricing_key": pricing.pricing_key,
    }


def merge_llm_cost_summary(
    summary: dict[str, Any] | None,
    *,
    estimate: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = _coerce_cost_summary(summary)
    if not isinstance(estimate, dict):
        merged["unpriced_call_count"] += 1
        merged["pricing_available"] = False
        return merged
    if not bool(estimate.get("pricing_available")):
        merged["unpriced_call_count"] += 1
        merged["pricing_available"] = False
        return merged
    for key in _COST_KEYS:
        merged[key] = _round_usd(Decimal(str(merged.get(key) or 0)) + Decimal(str(estimate.get(key) or 0)))
    merged["pricing_available"] = merged["unpriced_call_count"] == 0
    return merged


def empty_llm_cost_summary() -> dict[str, Any]:
    return {
        "estimated_cost_usd": 0.0,
        "input_cost_usd": 0.0,
        "cached_input_cost_usd": 0.0,
        "output_cost_usd": 0.0,
        "pricing_available": True,
        "unpriced_call_count": 0,
    }


def _coerce_cost_summary(value: dict[str, Any] | None) -> dict[str, Any]:
    summary = empty_llm_cost_summary()
    if not isinstance(value, dict):
        return summary
    for key in _COST_KEYS:
        try:
            summary[key] = _round_usd(Decimal(str(value.get(key) or 0)))
        except Exception:
            summary[key] = 0.0
    try:
        summary["unpriced_call_count"] = max(int(value.get("unpriced_call_count") or 0), 0)
    except Exception:
        summary["unpriced_call_count"] = 0
    summary["pricing_available"] = bool(value.get("pricing_available", summary["unpriced_call_count"] == 0))
    return summary


def _resolve_pricing(
    *,
    provider_id: str | None,
    vendor: str | None,
    model: str | None,
    protocol: str | None,
) -> _PricingDefinition | None:
    normalized_provider_id = str(provider_id or "").strip().lower()
    normalized_vendor = str(vendor or "").strip().lower()
    normalized_model = str(model or "").strip().lower()
    normalized_protocol = str(protocol or "").strip().lower()
    settings = get_settings()
    if normalized_vendor != "dashscope_openai":
        return None
    if normalized_model not in _QWEN_FLASH_US_MODEL_ALIASES:
        return None
    if normalized_protocol == "chat_completions" or normalized_provider_id == "qwen_us_chat":
        return _PricingDefinition(
            pricing_key="dashscope_us:qwen_flash_chat_le_256k",
            input_per_1m_usd=_resolve_price(settings.llm_price_qwen_us_chat_input_per_1m_usd, "0.05"),
            cached_input_per_1m_usd=_resolve_price(settings.llm_price_qwen_us_chat_cached_input_per_1m_usd, "0.01"),
            output_per_1m_usd=_resolve_price(settings.llm_price_qwen_us_chat_output_per_1m_usd, "0.40"),
        )
    if normalized_protocol in {"", "responses"} or normalized_provider_id in {"qwen_us_main", "env-default"}:
        return _PricingDefinition(
            pricing_key="dashscope_us:qwen_flash_le_256k",
            input_per_1m_usd=_resolve_price(settings.llm_price_qwen_us_main_input_per_1m_usd, "0.05"),
            cached_input_per_1m_usd=_resolve_price(settings.llm_price_qwen_us_main_cached_input_per_1m_usd, "0.01"),
            output_per_1m_usd=_resolve_price(settings.llm_price_qwen_us_main_output_per_1m_usd, "0.40"),
        )
    return None


def _resolve_price(value: float | None, fallback: str) -> Decimal:
    if value is None:
        return Decimal(fallback)
    return Decimal(str(value))


def _normalize_usage(usage: dict[str, Any] | None) -> dict[str, int]:
    payload = usage if isinstance(usage, dict) else {}
    return {
        "input_tokens": _int(payload.get("input_tokens")),
        "cached_input_tokens": _int(payload.get("cached_input_tokens")),
        "output_tokens": _int(payload.get("output_tokens")),
    }


def _int(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except Exception:
        return 0


def _decimal_to_usd(value: Decimal) -> float:
    return _round_usd(value)


def _round_usd(value: Decimal) -> float:
    return float(value.quantize(_USD_QUANTIZE, rounding=ROUND_HALF_UP))


__all__ = [
    "empty_llm_cost_summary",
    "estimate_llm_usage_cost",
    "merge_llm_cost_summary",
]
