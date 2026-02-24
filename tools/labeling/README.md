# Offline Email Labeling Tool (MBOX, Local Strong JSON Enforcement)

This tool builds silver labels from academic emails for downstream training.

- Input: **mbox only** (Google Takeout style)
- Main output: `labeled.jsonl`
- Sidecar errors: `label_errors.jsonl`
- API mode: Responses API with plain string output (no API-level strict schema)

Schema enforcement is done locally in code (`jsonschema` + logic checks), with a two-round repair loop.

## Security Rules

- Never commit raw mailbox data.
- Never commit secrets (`OPENAI_API_KEY`, OAuth tokens, private URLs).
- Keep generated data under `data/` (already gitignored).
- Logs are sanitized; do not print raw email bodies manually.

## Quick Start

1. Prepare env file:

```bash
cp tools/labeling/.env.example tools/labeling/.env
```

2. Fill `tools/labeling/.env`:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL` (example: `gpt-5.3-codex`)

3. Run labeling:

```bash
python -m tools.label_emails \
  --in data/DDW-CANDIDATE.mbox \
  --out data/labeled.jsonl \
  --workers 10
```

4. Validate output:

```bash
python tools/labeling/validate_labeled.py --input data/labeled.jsonl
```

## CLI Flags

- `--in` input mbox path (required)
- `--out` output labeled JSONL path (required)
- `--workers` concurrency, default `10`
- `--max` process at most N emails (after skip/filter)
- `--dry-run` no API calls and no file writes, only scan/summary

Model is always read from `OPENAI_MODEL` in `tools/labeling/.env`.

## Runtime Behavior

### Resume

- Resume is enabled automatically.
- If `--out` already contains some `email_id`, those emails are skipped on rerun.

### Long-body truncation

- `body_text` is truncated with head + tail preservation.
- Marker format: `...[TRUNCATED N CHARS]...`
- This keeps late-email clues that often appear near the end.

### Local Strong JSON Enforcement (No API Strict Mode)

Per email, pipeline is:

1. Generate label with Responses API (plain text output).
2. Parse JSON (direct `json.loads`).
3. If parse fails, extract first balanced `{...}` and parse again.
4. Validate with local schema + logic rules.
5. If invalid, run repair round 1 with:
   - schema text
   - validation error list
   - original invalid output
   - instruction: `Output ONLY corrected JSON. No explanation.`
6. If still invalid, run repair round 2 with the same strategy.
7. If still invalid after round 2:
   - write one row to `label_errors.jsonl`
   - do **not** write any fallback row into `labeled.jsonl`

No synthetic fallback labels are produced.

## Output Contract

Each `labeled.jsonl` row is one JSON object with exactly:

- `email_id`
- `label` (`KEEP|DROP`)
- `confidence` (`0..1`)
- `reasons` (`string[]`)
- `course_hints` (`string[]`)
- `event_type` (`deadline|exam|schedule_change|assignment|grade|action_required|announcement|other|null`)
- `action_items` (`[{action,due_iso,where}]`)
- `raw_extract` (`{deadline_text,time_text,location_text}`)
- `notes` (`string|null`)

Top-level extra keys are rejected.

## Defaults

- `LABEL_CONCURRENCY=10`
- `LABEL_MAX_RETRIES=6` (transport/API retry)
- `LABEL_TEMPERATURE=0.2` (allowed `0..0.3`)
- `LABEL_MAX_OUTPUT_TOKENS=600`
- `LABEL_MAX_BODY_CHARS=12000`
- `ERROR_JSONL=data/label_errors.jsonl`

## Notes

- Input is always mbox for this tool path.
- `EMAILS_INPUT_FORMAT` is not used by `python -m tools.label_emails`.

## Routing labeled outputs

Use deterministic post-label routing to split labeled rows into operational buckets.

Recommended workflow (normalize first, then route):

```bash
python tools/labeling/normalize_labeled.py \
  --input data/labeled.jsonl \
  --output data/normalized.jsonl \
  --errors data/normalize_errors.jsonl \
  --dedupe true \
  --max-action-items 5 \
  --rescue-llm false \
  --rescue-out data/rescue_applied.jsonl \
  --timezone America/Los_Angeles
```

Then:

```bash
python tools/labeling/route_labeled.py \
  --input data/normalized.jsonl \
  --outdir data/routes \
  --review-threshold 0.75 \
  --max-action-items 5 \
  --timezone America/Los_Angeles
```

Outputs in `data/routes/`:

- `drop.jsonl`: `label=DROP`
- `notify.jsonl`: high-priority actionable KEEP rows with strong signal
  - high-priority types: `deadline|exam|schedule_change|action_required`
  - `assignment` only notifies when `action_items` contains parseable `due_iso`
  - notify requires strong signal from parseable `due_iso` or non-empty `raw_extract`
- `archive.jsonl`: other `KEEP` rows (`grade|announcement|other|null`)
- `review.jsonl`: supplemental QA queue for risky `KEEP` rows (record may appear in both `notify/archive` and `review`)
- `route_errors.jsonl`: JSON parse/schema validation issues from ingest
- `stats.json`: counts, distributions, top course hints, and warnings

Dedup semantics:

- If the same `email_id` appears multiple times, the router keeps the row with higher `confidence`.
- If confidence ties, it keeps the latest line in input.

Important:

- Route files keep each selected row object unchanged (no added keys, no rewritten fields).
- `--max-action-items` affects warnings/stats only; it does not truncate output objects.
- Normalize rescue settings use env vars when enabled:
  - `RESCUE_LLM_ENABLED`, `RESCUE_LLM_BASE_URL`, `RESCUE_LLM_API_KEY`, `RESCUE_LLM_MODEL`
  - `RESCUE_LLM_TIMEOUT_SECONDS`, `RESCUE_LLM_BATCH_SIZE`, `RESCUE_LLM_CONCURRENCY`, `RESCUE_LLM_PATH`
  - logs are sanitized; do not print tokens/secrets manually

## Rules Extract + Eval

Use deterministic rules as a baseline model for fast offline iteration.

1. Build strict labels from raw emails (`emails.jsonl` or mbox):

```bash
python tools/labeling/rules_extract.py \
  --input-mbox data/DDW-CANDIDATE.mbox \
  --output data/rules_labeled.jsonl \
  --errors data/rules_errors.jsonl \
  --timezone America/Los_Angeles
```

JSONL mode:

```bash
python tools/labeling/rules_extract.py \
  --input-jsonl data/emails.jsonl \
  --output data/rules_labeled.jsonl \
  --errors data/rules_errors.jsonl
```

2. Evaluate rules against silver labels (silver is normalized automatically when needed):

```bash
python tools/labeling/eval_rules.py \
  --pred data/rules_labeled.jsonl \
  --silver data/labeled.jsonl \
  --outdir data/rules_eval
```

Artifacts:

- `data/rules_eval/metrics.json`
- `data/rules_eval/confusion_label.json`
- `data/rules_eval/confusion_event_type.json`
- `data/rules_eval/fn_keep_drop.jsonl`
- `data/rules_eval/fp_keep_drop.jsonl`
- `data/rules_eval/event_disagreements.jsonl`

3. Build a focused gold annotation queue (FN-heavy):

```bash
python tools/labeling/build_gold_queue.py \
  --eval-dir data/rules_eval \
  --pred data/rules_labeled.jsonl \
  --silver-normalized data/normalized.jsonl \
  --input-mbox data/DDW-CANDIDATE.mbox \
  --size 150 \
  --seed 42 \
  --output data/gold_queue.jsonl
```

4. Evaluate rules against reviewed gold labels:

```bash
python tools/labeling/eval_gold.py \
  --gold data/gold_queue.jsonl \
  --outdir data/rules_eval_gold
```
