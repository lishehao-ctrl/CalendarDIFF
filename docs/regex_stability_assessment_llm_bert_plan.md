# Regex Stability Assessment And LLM/BERT Comparison Plan

Updated: 2026-02-28

## 1) Context

This project originally relied on regex-heavy runtime rules in two critical paths:

1. ICS normalization and course/deadline extraction  
2. Gmail email rule classification and due-time extraction

The concern is valid: regex rules tend to be brittle under template drift, language variation, and semi-structured text noise.

## 2) Scope Of This Refactor

Runtime regex logic has been removed from:

1. `app/modules/sync/normalizer.py`
2. `app/modules/sync/email_rules.py`
3. `app/modules/users/service.py`
4. `app/modules/users/schemas.py`
5. `app/core/logging.py`

Legacy regex definitions are retained in one archive reference file:

1. `app/modules/sync/archive/legacy_regex_patterns.py`

Notes:

1. Archive file is intentionally not imported by runtime.
2. This gives a stable rollback/reference point for A/B comparison experiments.

## 3) Why Regex Was Unstable In Practice

Main failure modes observed for this domain:

1. Template drift:
   - Small copy edits in LMS/email templates break hard-coded expression assumptions.
2. Boundary brittleness:
   - Regex patterns overfit separators, casing, and punctuation.
3. Mixed language / mixed formatting:
   - Chinese + English + symbols + markdown/HTML fragments are hard to capture with one deterministic regex set.
4. Ambiguous semantics:
   - Pattern match does not imply intent certainty (for example announcement vs actionable deadline).
5. Maintenance overhead:
   - Every new edge case usually creates more patterns and ordering complexity.

## 4) Current Runtime Strategy After Removal

Runtime rule path is now regex-free:

1. Keyword/token scanning for event intent (`schedule_change`, `deadline`, `exam`, `assignment`, `action_required`)
2. Lightweight non-regex due parsing:
   - ISO token parse
   - month/day with fallback year
   - m/d/y with AM/PM and timezone abbreviation handling
3. Course hint parsing by token shape heuristics (non-regex)

This keeps deterministic behavior but avoids pattern-level fragility.

## 5) Proposed Comparison: Rules vs LLM vs BERT

### 5.1 Candidates

1. Baseline A: Current regex-free deterministic rules (now in runtime)
2. Candidate B: LLM extraction/classification (structured JSON output, fail-closed)
3. Candidate C: BERT-style local classifier + optional sequence labeling head

### 5.2 Evaluation Data

Use three splits from labeled email/ICS-derived data:

1. Train split (for BERT only)
2. Dev split (threshold tuning)
3. Frozen test split (final comparison, never used for tuning)

Recommended sample composition:

1. In-domain routine emails
2. Template-changed emails
3. Noisy/forwarded/multipart snippets
4. Non-actionable announcements and grade updates

### 5.3 Metrics

Primary:

1. `KEEP/DROP` precision, recall, F1
2. Event type macro F1
3. Due-time extraction success rate
4. False-positive rate on non-actionable emails

Operational:

1. p50/p95 latency per message
2. Failure-mode rate (timeout, invalid schema, empty extraction)
3. Cost per 1k messages (LLM)
4. Infrastructure cost and throughput (BERT)

Safety:

1. Fail-open vs fail-closed behavior under parser/model failure
2. Review queue inflation risk

### 5.4 Experiment Design

Run offline replay first:

1. Replay same frozen dataset through A/B/C
2. Store per-sample outputs with model/rule version tags
3. Compute slice-level metrics (course, sender type, template family, language mix)

Then shadow mode online:

1. Keep deterministic path as source-of-truth
2. Run LLM/BERT in shadow for score collection only
3. Compare divergence and drift weekly

### 5.5 Promotion Criteria (Suggested)

A model path can replace rule path only if:

1. `KEEP` precision is higher than baseline by a meaningful margin
2. False-positive rate does not increase
3. p95 latency and failure rate meet SLO
4. Fail-closed semantics remain guaranteed

## 6) Architecture Guidance For Next Step

To support long-term comparison cleanly:

1. Keep a single decision interface:
   - `classify(message) -> {label, confidence, event_type, due_at, reasons, origin}`
2. Implement multiple backends behind the same interface:
   - `rules_backend`
   - `llm_backend`
   - `bert_backend`
3. Store `decision_origin` + `decision_version` in persistence for audit and rollback.

## 7) Risks And Mitigations

1. LLM hallucination / schema drift:
   - strict JSON schema + confidence threshold + fail-closed.
2. BERT domain drift:
   - periodic re-labeling and re-training cadence.
3. Comparison bias:
   - freeze test set and avoid iterative leakage into evaluation.

## 8) Practical Next Actions

1. Define a frozen evaluation set and label schema version.
2. Add backend abstraction layer for decision engines.
3. Implement shadow inference logging format.
4. Run first baseline vs LLM vs BERT benchmark report.
