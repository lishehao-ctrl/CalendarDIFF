# Gmail Secondary Filter Training

## Goal

Train a small local text classifier on the Gmail secondary filter dataset and push the fine-tuned model to Hugging Face Hub.

Target labels:

- `relevant`
- `non_target`
- `uncertain`

## Recommended Device

This setup is intended for Apple Silicon local training with MPS enabled.

Recommended baseline:

- `distilbert-base-uncased`
- `max_length=256`
- `epochs=3`
- `train_batch_size=8`
- `eval_batch_size=16`

These defaults are chosen to be realistic on a 16GB M1 Pro.

## Install

Recommended packages:

```bash
python -m pip install transformers datasets evaluate accelerate huggingface_hub scikit-learn
```

If you want to pin versions, start with:

```bash
python -m pip install \
  'transformers>=4.44,<5' \
  'datasets>=2.20,<4' \
  'evaluate>=0.4,<1' \
  'accelerate>=0.34,<2' \
  'huggingface_hub>=0.24,<1' \
  'scikit-learn>=1.5,<2'
```

## Train

```bash
python training/gmail_secondary_filter/train_distilbert.py \
  --train-file data/secondary_filter/gmail_train.jsonl \
  --eval-file data/secondary_filter/gmail_eval.jsonl \
  --output-dir training/gmail_secondary_filter/output/distilbert-v1
```

## Push To Hugging Face

```bash
export HF_TOKEN=...
python training/gmail_secondary_filter/push_to_hub.py \
  --model-dir training/gmail_secondary_filter/output/distilbert-v1 \
  --repo-id YOUR_NAMESPACE/calendardiff-gmail-secondary-filter-v1
```

## Runtime Recommendation

Do not hard-gate immediately after first training.

Recommended rollout:

1. train locally
2. evaluate on `gmail_eval.jsonl`
3. push to private HF repo
4. use shadow mode in runtime
5. only then enable high-confidence `non_target` suppression

## Key Metrics

Track these before enabling suppression:

- `relevant recall`
- `non_target precision`
- `uncertain rate`
- confusion matrix

Production threshold should optimize:

- near-perfect `relevant` recall
- very high precision on suppressed `non_target`
