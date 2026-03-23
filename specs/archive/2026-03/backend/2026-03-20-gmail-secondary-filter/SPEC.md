# Gmail Secondary Filter Plan

## Goal

Add a `prefilter -> secondary classifier -> LLM` pipeline for Gmail intake.

The secondary classifier is a small BERT-family text classifier hosted behind Hugging Face APIs.
It is not a semantic parser. It is a high-confidence `non_target` suppressor that reduces Gmail LLM load without hurting recall of real grade-relevant time signals.

## Product Rules

- Deterministic prefilter remains recall-first.
- Secondary classifier never becomes the sole positive gate.
- The classifier may suppress only very high-confidence `non_target`.
- `relevant` and `uncertain` both continue to LLM.
- If the classifier is unavailable, the system must fail open and continue to LLM.

## Label Schema

The classifier predicts exactly one of:

- `relevant`
  - The message likely contains a grade-relevant academic time signal that should still be sent to LLM.
  - Includes:
    - new homework / quiz / exam / project announcements with due/scheduled time
    - due date / time changes
    - bulk schedule mutations
    - ambiguous-but-possibly-real cases that should not be dropped early

- `non_target`
  - The message should be suppressed before LLM.
  - Includes:
    - shipping / subscription / recruiting bait
    - newsletters / digests / wrappers
    - campus admin noise
    - academic non-target messages that clearly state no canonical due-time mutation

- `uncertain`
  - The classifier is not confident enough to suppress.
  - Must continue to LLM.

## Runtime Contract

Runtime output shape for the secondary filter:

```json
{
  "label": "relevant | non_target | uncertain",
  "confidence": 0.0,
  "provider": "huggingface_distilbert",
  "reason_code": "string"
}
```

Runtime decision policy:

- if `label=non_target` and `confidence >= threshold`: suppress
- else: continue to LLM

Recommended first threshold:

- `0.98`

Recommended first production policy:

- `shadow mode` first
- then `hard suppress` only for `non_target >= 0.995`

## Dataset Strategy

### 1. Real sample pool

Use only Gmail messages that already passed deterministic prefilter.

Reason:

- This is the true post-prefilter distribution.
- The secondary classifier should learn only the hard cases that deterministic rules cannot cleanly separate.

### 2. Three dataset splits

- `gold_eval`
  - manually reviewed only
  - used for thresholding and release gating

- `train_main`
  - real samples with GPT pseudo-labels

- `train_hard`
  - synthetic hard cases generated from GPT using real-message style and known bait patterns

### 3. Label sources

Strong `relevant`:

- Gmail messages that led to approved or edited-and-approved changes
- Gmail messages with stable downstream canonical linkage

Strong `non_target`:

- deterministic obvious junk
- review-confirmed non-targets
- newsletter / wrapper / recruiting / shipping / subscription bait

Strong `uncertain`:

- mixed or weakly evidenced academic signals
- wrapper-heavy mail
- “could matter” messages that should still reach LLM

## GPT Pseudo-Labeling

Use GPT only as an offline labeling worker, never in runtime.

Pseudo-label output schema:

```json
{
  "label": "relevant | non_target | uncertain",
  "confidence": 0.0,
  "why_short": "string",
  "suppress_before_llm": true
}
```

Use GPT for:

- real-sample pseudo-labeling
- hard negative synthesis
- hard positive synthesis

Do not train on raw GPT confidence directly.
Use only:

- label
- sample text
- optional sample weight

## Hugging Face Stack

Recommended common HF workflow:

1. annotate / curate with Argilla or plain JSONL/CSV
2. fine-tune text classification with Transformers or AutoTrain
3. push model to Hub
4. call hosted `text-classification` inference

Recommended first model:

- `distilbert-base-uncased`

Alternative small encoders:

- `MiniLM`
- `mpnet` small variants

## Training Plan

### Option A: fastest path

Use Hugging Face AutoTrain text classification.

Pros:

- low ops overhead
- easy Hub deployment
- good enough for first production pass

### Option B: more control

Use Transformers `sequence_classification`.

Recommended defaults:

- max_length: `256` or `384`
- epochs: `2-4`
- learning_rate: `2e-5` to `5e-5`
- batch_size: `16-32`
- weighted loss toward `relevant`

Split policy:

- prefer time-based split over random split

Reason:

- the system is evaluated chronologically
- random split overestimates real-world performance

## Deployment Plan

### Phase 1: Shadow

- deterministic prefilter passes messages
- secondary classifier runs
- predictions are logged
- no suppress action yet

Track:

- `secondary_filter_non_target_rate`
- `secondary_filter_shadow_precision`
- `secondary_filter_shadow_recall_on_relevant`
- effect on later LLM mode labels

### Phase 2: High-confidence suppress

- suppress only `non_target >= threshold`
- continue to log shadow labels for all messages

### Phase 3: Threshold tuning

- adjust threshold on `gold_eval`
- optimize for:
  - near-perfect `relevant recall`
  - very high precision on suppressed `non_target`

## Metrics

Primary:

- `relevant recall`
- `suppressed_non_target_precision`
- `secondary_filter_suppression_rate`
- `gmail_stage1_call_count`
- `avg_gmail_request_elapsed_ms`
- `gmail_schema_invalid_count`
- `gmail_retry_count`

Secondary:

- `cached_input_tokens`
- `total_tokens`
- `avg latency`

## Integration Notes

Current repo hook:

- `app/modules/runtime/connectors/gmail_second_filter.py`

Current behavior:

- deterministic prefilter is recall-first
- secondary filter exists as a no-op stub
- runtime currently fails open

Next code steps:

1. define runtime DTO for HF classifier response
2. add shadow-mode logging payload
3. add HF provider implementation in `gmail_second_filter.py`
4. add threshold-based suppression
5. add offline dataset export script
6. add GPT pseudo-labeling worker prompt and output schema

## Release Rule

Do not enable suppression until:

- `gold_eval` exists
- shadow metrics are stable
- relevant recall is acceptable
- fail-open path is tested
