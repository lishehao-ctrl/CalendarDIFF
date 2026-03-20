from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import evaluate
import numpy as np
import torch
from datasets import Dataset
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    Trainer,
    TrainingArguments,
)


LABEL_TO_ID = {
    "relevant": 0,
    "non_target": 1,
    "uncertain": 2,
}
ID_TO_LABEL = {value: key for key, value in LABEL_TO_ID.items()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train Gmail secondary filter classifier locally.")
    parser.add_argument("--train-file", required=True)
    parser.add_argument("--eval-file", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--model-name", default="distilbert-base-uncased")
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--train-batch-size", type=int, default=8)
    parser.add_argument("--eval-batch-size", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--resume-from-checkpoint", default=None)
    parser.add_argument("--relevant-weight", type=float, default=2.0)
    parser.add_argument("--non-target-weight", type=float, default=1.0)
    parser.add_argument("--uncertain-weight", type=float, default=1.0)
    parser.add_argument("--relevant-like-uncertain-weight", type=float, default=1.5)
    return parser.parse_args()


def build_text(row: dict) -> str:
    from_header = str(row.get("from_header") or "")
    subject = str(row.get("subject") or "")
    snippet = str(row.get("snippet") or "")
    body_text = str(row.get("body_text") or "")
    known_course_tokens = row.get("known_course_tokens") or []
    course_text = " | ".join(str(item) for item in known_course_tokens if isinstance(item, str))
    return "\n".join(
        [
            f"FROM: {from_header}",
            f"SUBJECT: {subject}",
            f"SNIPPET: {snippet}",
            f"KNOWN_COURSE_TOKENS: {course_text}",
            f"BODY: {body_text}",
        ]
    )


def compute_effective_weight(
    *,
    label: str,
    relevant_like: bool,
    risk_tier: str | None,
    base_weight: float,
    relevant_weight: float,
    non_target_weight: float,
    uncertain_weight: float,
    relevant_like_uncertain_weight: float,
) -> float:
    weight = max(float(base_weight), 0.0)
    if label == "relevant":
        return weight * relevant_weight
    if label == "non_target":
        return weight * non_target_weight
    if relevant_like and risk_tier in {"high", "critical"}:
        return weight * relevant_like_uncertain_weight
    return weight * uncertain_weight


def load_jsonl_dataset(
    path: Path,
    *,
    relevant_weight: float,
    non_target_weight: float,
    uncertain_weight: float,
    relevant_like_uncertain_weight: float,
) -> Dataset:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            metadata = row.get("metadata") or {}
            relevant_like = bool(metadata.get("relevant_like")) if isinstance(metadata, dict) else False
            risk_tier = metadata.get("risk_tier") if isinstance(metadata, dict) else None
            label = row["label"]
            rows.append(
                {
                    "text": build_text(row),
                    "label": LABEL_TO_ID[label],
                    "weight": compute_effective_weight(
                        label=label,
                        relevant_like=relevant_like,
                        risk_tier=str(risk_tier) if isinstance(risk_tier, str) else None,
                        base_weight=float(row.get("weight") or 1.0),
                        relevant_weight=relevant_weight,
                        non_target_weight=non_target_weight,
                        uncertain_weight=uncertain_weight,
                        relevant_like_uncertain_weight=relevant_like_uncertain_weight,
                    ),
                }
            )
    return Dataset.from_list(rows)


@dataclass
class WeightedDataCollator:
    tokenizer: object

    def __post_init__(self) -> None:
        self._base = DataCollatorWithPadding(tokenizer=self.tokenizer)

    def __call__(self, features):
        weights = [float(feature.pop("weight", 1.0)) for feature in features]
        for feature in features:
            feature.pop("text", None)
        batch = self._base(features)
        batch["weights"] = torch.tensor(weights, dtype=torch.float32)
        return batch


class WeightedTrainer(Trainer):
    def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):  # type: ignore[override]
        labels = inputs.pop("labels")
        weights = inputs.pop("weights", None)
        outputs = model(**inputs)
        logits = outputs.logits
        loss_fct = torch.nn.CrossEntropyLoss(reduction="none")
        per_example_loss = loss_fct(logits, labels)
        if weights is not None:
            weights = weights.to(per_example_loss.device)
            loss = (per_example_loss * weights).mean()
        else:
            loss = per_example_loss.mean()
        if return_outputs:
            return loss, outputs
        return loss


def compute_metrics(eval_pred):
    accuracy_metric = evaluate.load("accuracy")
    precision_metric = evaluate.load("precision")
    recall_metric = evaluate.load("recall")
    f1_metric = evaluate.load("f1")

    logits, labels = eval_pred
    predictions = np.argmax(logits, axis=-1)

    accuracy = accuracy_metric.compute(predictions=predictions, references=labels)["accuracy"]
    macro_precision = precision_metric.compute(predictions=predictions, references=labels, average="macro")["precision"]
    macro_recall = recall_metric.compute(predictions=predictions, references=labels, average="macro")["recall"]
    macro_f1 = f1_metric.compute(predictions=predictions, references=labels, average="macro")["f1"]
    per_class_recall = recall_metric.compute(predictions=predictions, references=labels, average=None)["recall"]

    return {
        "accuracy": accuracy,
        "macro_precision": macro_precision,
        "macro_recall": macro_recall,
        "macro_f1": macro_f1,
        "relevant_recall": per_class_recall[LABEL_TO_ID["relevant"]],
        "non_target_recall": per_class_recall[LABEL_TO_ID["non_target"]],
        "uncertain_recall": per_class_recall[LABEL_TO_ID["uncertain"]],
    }


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    tokenizer = AutoTokenizer.from_pretrained(args.model_name)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model_name,
        num_labels=len(LABEL_TO_ID),
        id2label=ID_TO_LABEL,
        label2id=LABEL_TO_ID,
    )

    train_dataset = load_jsonl_dataset(
        Path(args.train_file).expanduser().resolve(),
        relevant_weight=args.relevant_weight,
        non_target_weight=args.non_target_weight,
        uncertain_weight=args.uncertain_weight,
        relevant_like_uncertain_weight=args.relevant_like_uncertain_weight,
    )
    eval_dataset = load_jsonl_dataset(
        Path(args.eval_file).expanduser().resolve(),
        relevant_weight=args.relevant_weight,
        non_target_weight=args.non_target_weight,
        uncertain_weight=args.uncertain_weight,
        relevant_like_uncertain_weight=args.relevant_like_uncertain_weight,
    )

    def tokenize(batch):
        return tokenizer(batch["text"], truncation=True, max_length=args.max_length)

    train_dataset = train_dataset.map(tokenize, batched=True)
    eval_dataset = eval_dataset.map(tokenize, batched=True)

    training_args = TrainingArguments(
        output_dir=str(output_dir),
        learning_rate=args.learning_rate,
        per_device_train_batch_size=args.train_batch_size,
        per_device_eval_batch_size=args.eval_batch_size,
        num_train_epochs=args.epochs,
        eval_strategy="epoch",
        save_strategy="epoch",
        logging_strategy="steps",
        logging_steps=50,
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="relevant_recall",
        greater_is_better=True,
        report_to=[],
        use_mps_device=True,
        remove_unused_columns=False,
        dataloader_pin_memory=False,
    )

    trainer = WeightedTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        tokenizer=tokenizer,
        data_collator=WeightedDataCollator(tokenizer=tokenizer),
        compute_metrics=compute_metrics,
    )

    trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))

    metrics = trainer.evaluate()
    metrics_path = output_dir / "eval_metrics.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
