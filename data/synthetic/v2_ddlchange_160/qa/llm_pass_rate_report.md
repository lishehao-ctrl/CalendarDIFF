# Ingestion LLM Pass Rate Report

- run_id: `ingestion-llm-eval-d6646976b40f`
- started_at: `2026-03-02T04:05:28.898261+00:00`
- finished_at: `2026-03-02T04:06:30.159142+00:00`
- provider: `env-default`
- model: `qwen-flash-us`
- base_url_hash: `e8364293a810`
- passed: `True`

## Mail
- structured_success_rate: `0.9917`
- label_accuracy: `0.9083`
- event_macro_f1: `0.8572`
- ambiguous_macro_f1: `0.25`
- non_ambiguous_macro_f1: `0.6072`

## ICS
- structured_success_rate: `1.0`
- diff_accuracy: `1.0`
- uid_hit_rate: `1.0`

## Threshold Check
- mail.event_macro_f1: `True`
- ics.diff_accuracy: `True`
- mail.structured_success_rate: `True`
- ics.structured_success_rate: `True`
