# Local Training And HF Deployment Plan

## Recommended Path

Train locally, upload the trained classifier to Hugging Face Hub, and use Hugging Face hosted inference at runtime.

This is the best fit for CalendarDIFF because:

- label space is project-specific
- runtime machine is small
- the model should be cheap and easy to replace

## Phase 1: Dataset Build

Inputs:

- real Gmail messages that already passed deterministic prefilter
- GPT pseudo-labeled samples
- synthetic hard negatives / positives
- manually verified gold eval rows

Output files:

- `gmail_train.jsonl`
- `gmail_eval.jsonl`
- `gmail_shadow_candidates.jsonl`

## Phase 2: Local Fine-Tune

Recommended base:

- `distilbert-base-uncased`

Task:

- sequence classification
- labels: `relevant`, `non_target`, `uncertain`

Recommended starting hyperparameters:

- `max_length=256`
- `epochs=3`
- `learning_rate=2e-5`
- `train_batch_size=16`
- `eval_batch_size=32`
- weighted loss biased toward `relevant`

Split policy:

- prefer chronological split over random split

## Phase 3: Local Eval

Release metrics should include:

- `relevant recall`
- `non_target precision`
- `uncertain rate`
- confusion matrix

Do not optimize for raw accuracy.

## Phase 4: Push To Hub

Push the trained model and tokenizer to a dedicated repo, for example:

- `your-org/calendardiff-gmail-secondary-filter-v1`

Recommended:

- start private
- add a model card with label definitions and threshold rules

## Phase 5: Runtime Inference

Runtime calls HF text-classification API against your uploaded model.

Runtime decision rule:

- `non_target` and confidence >= threshold => suppress
- otherwise => continue to LLM

Recommended first threshold:

- shadow: no suppress
- first hard gate: `0.995`

## Phase 6: Active Learning Loop

For every suppressed sample in shadow mode:

- store model label
- store confidence
- store whether downstream review / canonical evidence would have needed it

Use these rows to build next train set.

## Why Not Use A Public Off-The-Shelf Classifier Directly

Because the CalendarDIFF boundary is project-specific:

- shipping bait with `project`
- LMS wrappers
- academic non-target mail that explicitly says the graded item is unchanged
- broad-audience but truly relevant bulk deadline changes

These boundaries usually require task-specific fine-tuning.
