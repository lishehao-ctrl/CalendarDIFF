# Backend Decision Memo — 2026-03-18

This memo records the current product and engineering decisions that should now be treated as active CalendarDIFF guidance.

## 1. Source intake is split into `bootstrap` and `replay`

Definitions:

- `bootstrap`: the first source warmup or large initial backfill
- `replay`: normal ongoing sync after warmup, including manual replay-style runs

Rules:

- keep source create semantics unchanged; the first automatic sync is still allowed
- do not mix bootstrap cost with steady-state replay cost
- observability should always distinguish bootstrap from replay

## 2. Gmail cache optimization focuses on stable prompt-prefix reuse

Rules:

- Gmail stage1 should cache stable prompt material:
  - rules
  - few-shot examples
  - schema
- message body and other per-message context stay outside the cache block
- same-message stage2/3/4 reuse remains a secondary optimization

Interpretation:

- the best cache ROI comes from many messages hitting the same stage1 task
- `cache_creation_input_tokens` and `cached_input_tokens` must be interpreted separately

## 3. ICS is not optimized around explicit cache hit rate

Rules:

- ICS remains a structured inventory and deterministic diff source
- do not prioritize explicit prompt-cache hit rate for ICS
- prioritize runtime completion and terminal-state correctness instead

Interpretation:

- ICS problems are primarily runtime-state and reducer/apply correctness problems
- lightweight prompt cleanup is acceptable, Gmail-style cache engineering is not the main path

## 4. Canonical meaning stays separate from source-near extraction

Rules:

- parser output remains source-near for:
  - `raw_type`
  - `event_name`
  - `ordinal`
  - resolved time
- `family_name` carries canonical grouping
- alias merge, family suggestion, and raw-type relink belong to the governance layer

Interpretation:

- extraction should not depend on existing family state to succeed
- family learning can help review, but should not be pushed back into the parser contract

## 5. Human review is centered on `Changes`

Rules:

- `Changes` decides timeline truth
- `Families` decides naming truth
- when naming drift blocks a correct approval, make family learning easy from `Changes`
- do not restore a standalone user-facing links review lane

Interpretation:

- `Changes` remains the primary user workflow
- `Families` remains governance, not the main inbox
- `Manual` remains fallback

## 6. Prefilter remains recall-first

Rules:

- the highest priority is still “do not miss real ddlchange”
- only after recall is protected should interception rate be optimized
- generic campus/admin/advising/wrapper noise should be blocked pre-LLM when possible

Interpretation:

- noise reduction belongs in deterministic prefilter first
- the parser should receive fewer, more valuable candidates

## 7. Observability is part of the product model, not a developer-only side channel

User-visible observability should focus on:

- status
- elapsed time
- LLM calls
- input tokens
- cached input tokens
- cache creation input tokens
- total tokens
- average latency

Rules:

- present observability primarily under `Sources`
- allow `Overview` to expose only a compact intake posture summary
- do not turn the UI into a raw developer log explorer

Current implementation stance:

- `sync_request.metadata.llm_usage_summary` is the current source of truth for sync-level usage aggregation
- future public source-history/observability endpoints can build on top of that
