#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = REPO_ROOT / "output"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estimate when a Gmail secondary BERT filter becomes cost-effective."
    )
    parser.add_argument(
        "--report-json",
        default=None,
        help="Optional compare_real_gmail_filter_strategies report.json. Defaults to latest one in output/.",
    )
    parser.add_argument("--hf-hourly-usd", type=float, default=0.03)
    parser.add_argument("--warm-minutes", type=float, default=15.0)
    parser.add_argument("--usd-to-rmb", type=float, default=7.2)
    parser.add_argument("--replicas", type=int, default=1)
    parser.add_argument("--uncached-input-weight", type=float, default=1.0)
    parser.add_argument("--cached-read-weight", type=float, default=0.1)
    parser.add_argument("--cache-create-weight", type=float, default=1.25)
    parser.add_argument(
        "--sample-suppress-counts",
        default="10,25,50,100,200",
        help="Comma-separated suppress counts for multiplier table.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report_path = resolve_report_path(args.report_json)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    baseline = report["strategies"]["prefilter_then_llm"]["llm"]
    message_count = int(baseline["message_count"])
    input_tokens = int(baseline["input_tokens"])
    cached_input_tokens = int(baseline.get("cached_input_tokens") or 0)
    cache_creation_input_tokens = int(baseline.get("cache_creation_input_tokens") or 0)
    output_tokens = int(baseline["output_tokens"])
    naive_llm_cost_rmb = float(baseline["naive_llm_cost_rmb"])
    cost_per_message_rmb = naive_llm_cost_rmb / message_count if message_count > 0 else 0.0
    llm_input_price_per_token_rmb = (
        float(report["pricing_assumptions"]["llm_rmb_per_m_input_tokens"]) / 1_000_000.0
    )
    llm_output_price_per_token_rmb = (
        float(report["pricing_assumptions"]["llm_rmb_per_m_output_tokens"]) / 1_000_000.0
    )

    weighted_input_equivalent_tokens = compute_weighted_input_equivalent_tokens(
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        uncached_input_weight=float(args.uncached_input_weight),
        cached_read_weight=float(args.cached_read_weight),
        cache_create_weight=float(args.cache_create_weight),
    )
    output_as_input_token_multiple = (
        llm_output_price_per_token_rmb / llm_input_price_per_token_rmb
        if llm_input_price_per_token_rmb > 0
        else None
    )
    weighted_total_equivalent_tokens = (
        weighted_input_equivalent_tokens
        + (
            float(output_tokens) * float(output_as_input_token_multiple)
            if output_as_input_token_multiple is not None
            else 0.0
        )
    )
    weighted_llm_cost_rmb = (
        weighted_input_equivalent_tokens * llm_input_price_per_token_rmb
        + output_tokens * llm_output_price_per_token_rmb
    )
    weighted_cost_per_message_rmb = weighted_llm_cost_rmb / message_count if message_count > 0 else 0.0

    warm_window_cost_rmb = (
        float(args.hf_hourly_usd)
        * (float(args.warm_minutes) / 60.0)
        * float(args.usd_to_rmb)
        * max(int(args.replicas), 1)
    )
    break_even_suppressed = (
        warm_window_cost_rmb / cost_per_message_rmb if cost_per_message_rmb > 0 else None
    )
    weighted_break_even_suppressed = (
        warm_window_cost_rmb / weighted_cost_per_message_rmb if weighted_cost_per_message_rmb > 0 else None
    )

    actual_bert = report["strategies"]["prefilter_then_bert_then_llm"]["bert"]
    actual_suppressed = int(actual_bert["suppressed_count"])
    actual_price_multiplier = (
        warm_window_cost_rmb / (actual_suppressed * cost_per_message_rmb)
        if actual_suppressed > 0 and cost_per_message_rmb > 0
        else None
    )
    actual_weighted_price_multiplier = (
        warm_window_cost_rmb / (actual_suppressed * weighted_cost_per_message_rmb)
        if actual_suppressed > 0 and weighted_cost_per_message_rmb > 0
        else None
    )

    sample_counts = [
        int(part.strip())
        for part in str(args.sample_suppress_counts).split(",")
        if part.strip()
    ]
    table = []
    for suppress_count in sample_counts:
        savings_now_naive = suppress_count * cost_per_message_rmb
        savings_now_weighted = suppress_count * weighted_cost_per_message_rmb
        multiplier_naive = (
            warm_window_cost_rmb / savings_now_naive if savings_now_naive > 0 else None
        )
        multiplier_weighted = (
            warm_window_cost_rmb / savings_now_weighted if savings_now_weighted > 0 else None
        )
        table.append(
            {
                "suppress_count": suppress_count,
                "llm_savings_now_rmb_naive": round(savings_now_naive, 6),
                "llm_savings_now_rmb_weighted": round(savings_now_weighted, 6),
                "llm_price_multiplier_needed_for_break_even_naive": (
                    round(multiplier_naive, 4) if multiplier_naive is not None else None
                ),
                "llm_price_multiplier_needed_for_break_even_weighted": (
                    round(multiplier_weighted, 4) if multiplier_weighted is not None else None
                ),
            }
        )

    payload = {
        "report_json": str(report_path),
        "dataset": report.get("dataset"),
        "baseline_llm": {
            "message_count": message_count,
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "cache_creation_input_tokens": cache_creation_input_tokens,
            "output_tokens": output_tokens,
            "naive_llm_cost_rmb": round(naive_llm_cost_rmb, 6),
            "avg_cost_per_llm_message_rmb_naive": round(cost_per_message_rmb, 9),
            "weighted_input_equivalent_tokens": round(weighted_input_equivalent_tokens, 3),
            "output_as_input_token_multiple": (
                round(output_as_input_token_multiple, 4)
                if output_as_input_token_multiple is not None
                else None
            ),
            "weighted_total_equivalent_tokens": round(weighted_total_equivalent_tokens, 3),
            "avg_weighted_total_equivalent_tokens_per_message": (
                round(weighted_total_equivalent_tokens / message_count, 6)
                if message_count > 0
                else None
            ),
            "weighted_llm_cost_rmb": round(weighted_llm_cost_rmb, 6),
            "avg_cost_per_llm_message_rmb_weighted": round(weighted_cost_per_message_rmb, 9),
        },
        "hf_cost_model": {
            "hf_hourly_usd": float(args.hf_hourly_usd),
            "warm_minutes": float(args.warm_minutes),
            "usd_to_rmb": float(args.usd_to_rmb),
            "replicas": max(int(args.replicas), 1),
            "warm_window_cost_rmb": round(warm_window_cost_rmb, 6),
        },
        "weighting_model": {
            "uncached_input_weight": float(args.uncached_input_weight),
            "cached_read_weight": float(args.cached_read_weight),
            "cache_create_weight": float(args.cache_create_weight),
            "formula": "weighted_input = remaining_uncached*uncached_weight + cached_read*cached_read_weight + cache_creation*cache_create_weight; remaining_uncached=max(input-cached_read-cache_creation,0)",
        },
        "break_even": {
            "suppressed_messages_needed_at_current_llm_price_naive": (
                round(break_even_suppressed, 2) if break_even_suppressed is not None else None
            ),
            "suppressed_messages_needed_at_current_llm_price_weighted": (
                round(weighted_break_even_suppressed, 2) if weighted_break_even_suppressed is not None else None
            ),
            "actual_report_suppressed_count": actual_suppressed,
            "actual_report_llm_price_multiplier_needed_naive": (
                round(actual_price_multiplier, 4)
                if actual_price_multiplier is not None
                else None
            ),
            "actual_report_llm_price_multiplier_needed_weighted": (
                round(actual_weighted_price_multiplier, 4)
                if actual_weighted_price_multiplier is not None
                else None
            ),
        },
        "sample_suppress_scenarios": table,
        "decision_rule": (
            "Enable BERT only when expected_suppressed_count * avg_cost_per_llm_message_rmb_weighted > warm_window_cost_rmb."
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def resolve_report_path(raw: str | None) -> Path:
    if raw:
        path = Path(raw).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"report json not found: {path}")
        return path
    candidates = sorted(
        OUTPUT_ROOT.glob("real-gmail-filter-compare-*/report.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("no real-gmail-filter-compare report.json found under output/")
    return candidates[0]


def compute_weighted_input_equivalent_tokens(
    *,
    input_tokens: int,
    cached_input_tokens: int,
    cache_creation_input_tokens: int,
    uncached_input_weight: float,
    cached_read_weight: float,
    cache_create_weight: float,
) -> float:
    remaining_uncached = max(
        float(input_tokens) - float(cached_input_tokens) - float(cache_creation_input_tokens),
        0.0,
    )
    return (
        remaining_uncached * float(uncached_input_weight)
        + float(cached_input_tokens) * float(cached_read_weight)
        + float(cache_creation_input_tokens) * float(cache_create_weight)
    )


if __name__ == "__main__":
    main()
