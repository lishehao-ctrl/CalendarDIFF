# Product / Engineering Decision Memo — 2026-03-18

This memo compresses the current product and engineering direction into one execution-oriented baseline.

It is meant to answer:

1. what the product is optimizing for
2. where ambiguity should live
3. which technical tradeoffs are now considered settled

## 1. Bootstrap and replay are different product phases

`bootstrap` and `replay` are not the same thing.

- `bootstrap` = initial source warmup, first large sync, backfill-like cost
- `replay` = normal ongoing operation after warmup

Product implication:

- users should not confuse bootstrap cost spikes with normal daily operation
- source observability should report bootstrap and replay separately

Engineering implication:

- replay harness must wait for bootstrap before entering time-sequenced replay
- token/cache/latency metrics should be split by bootstrap vs replay

## 2. Gmail cache should target stable prompt reuse

The highest-value cache opportunity is Gmail stage1 across many different emails.

Decision:

- cache the stable prompt prefix
- keep message body / source message context in the non-cached tail
- treat same-message stage2/3/4 reuse as a secondary optimization layer

Reason:

- bootstrap and inbox triage often end at stage1
- caching full message context creates cache but usually does not produce reuse

## 3. ICS should optimize for runtime completion, not cache rate

ICS remains primarily:

- structured inventory
- deterministic time diff
- canonical fact source

Decision:

- do not prioritize explicit cache optimization for ICS
- prioritize scheduler/bootstrap completion and correct terminal state writeback

Reason:

- ICS prompt prefixes are usually short and highly event-specific
- the operational risk is stuck `RUNNING`, not low cache hit rate

## 4. Extraction stays source-near; canonicalization stays in governance

Decision:

- parser extracts source-near `raw_type`, `event_name`, `ordinal`, and time
- canonical grouping belongs to `family_name`
- alias merge and family suggestion are governance concerns, not parser prerequisites

Reason:

- preserves auditability
- avoids brittle parser dependence on mutable family state
- matches entity resolution practice: extraction, suggestion, and merge are separate steps

## 5. Changes is the truth workspace; Families is the naming workspace

Decision:

- `Changes` remains the primary daily inbox
- `Families` remains the governance lane
- family learning may be initiated from review, but does not replace review
- `Manual` remains a fallback lane

Reason:

- timeline truth and naming truth are related but not identical
- collapsing them fully would make the core workflow harder to operate

## 6. Prefilter stays recall-first

Decision:

- do not miss real ddlchange
- then maximize junk interception before LLM

Operational stance:

- campus admin, wrapper noise, advisement, newsletters, and non-target bureaucracy should be blocked as early as possible
- parser should receive higher-value candidates, not clean up every noisy message

Secondary classifier stance:

- any BERT / secondary suppressor between prefilter and LLM is an optional upgrade path
- it must not be a required runtime dependency for deployment
- supported runtime modes should be:
  - `off`
  - `shadow`
  - `enforce`
- default deployment mode is `off`
- `shadow` may observe and log candidate suppressions, but must not change the main result path
- only `enforce` may suppress after the deterministic recall-first prefilter

## 7. Observability belongs in product language, not developer language

Decision:

- user-visible observability should use:
  - status
  - elapsed time
  - LLM calls
  - input tokens
  - cached input tokens
  - cache creation input tokens
  - total tokens
  - average latency

Do not expose:

- raw worker internals
- queue jargon
- metadata field names

UI implication:

- `Sources` is the observability lane
- `Overview` only needs a compact intake posture summary

## 8. Public product language should keep drifting away from legacy module names

Decision:

- product lanes are:
  - `Sources`
  - `Changes`
  - `Families`
  - `Manual`
  - `Settings`

Legacy internal modules or route families may still exist temporarily, but they should stop defining product language.

Reason:

- the system is now entity-first and user-facing
- legacy route/module history should not shape future UX or documentation
