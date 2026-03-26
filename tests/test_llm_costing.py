from __future__ import annotations

from app.core.config import get_settings
from app.modules.llm_gateway.costing import estimate_llm_usage_cost


def test_estimate_llm_usage_cost_prices_qwen_flash_with_cached_input() -> None:
    estimate = estimate_llm_usage_cost(
        provider_id="qwen_us_main",
        vendor="dashscope_openai",
        model="qwen3.5-flash",
        protocol="responses",
        usage={
            "input_tokens": 1000,
            "cached_input_tokens": 200,
            "cache_creation_input_tokens": 500,
            "output_tokens": 500,
        },
    )

    assert estimate["pricing_available"] is True
    assert estimate["pricing_key"] == "dashscope_us:qwen_flash_le_256k"
    assert estimate["input_cost_usd"] == 0.00004
    assert estimate["cached_input_cost_usd"] == 0.000002
    assert estimate["output_cost_usd"] == 0.0002
    assert estimate["estimated_cost_usd"] == 0.000242


def test_estimate_llm_usage_cost_uses_env_override(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PRICE_QWEN_US_MAIN_INPUT_PER_1M_USD", "0.12")
    monkeypatch.setenv("LLM_PRICE_QWEN_US_MAIN_CACHED_INPUT_PER_1M_USD", "0.03")
    monkeypatch.setenv("LLM_PRICE_QWEN_US_MAIN_OUTPUT_PER_1M_USD", "0.90")
    get_settings.cache_clear()
    try:
        estimate = estimate_llm_usage_cost(
            provider_id="qwen_us_main",
            vendor="dashscope_openai",
            model="qwen3.5-flash",
            protocol="responses",
            usage={
                "input_tokens": 1000,
                "cached_input_tokens": 100,
                "output_tokens": 200,
            },
        )
    finally:
        get_settings.cache_clear()

    assert estimate["pricing_available"] is True
    assert estimate["input_cost_usd"] == 0.000108
    assert estimate["cached_input_cost_usd"] == 0.000003
    assert estimate["output_cost_usd"] == 0.00018
    assert estimate["estimated_cost_usd"] == 0.000291


def test_estimate_llm_usage_cost_marks_unknown_provider_unpriced() -> None:
    estimate = estimate_llm_usage_cost(
        provider_id="env-default",
        vendor="openai",
        model="gpt-4.1-mini",
        protocol="responses",
        usage={"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 20},
    )

    assert estimate["pricing_available"] is False
    assert estimate["pricing_key"] is None
    assert estimate["estimated_cost_usd"] is None
