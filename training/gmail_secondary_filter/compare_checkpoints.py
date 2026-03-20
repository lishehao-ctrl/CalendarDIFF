from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.metrics import classification_report
from transformers import AutoModelForSequenceClassification, AutoTokenizer


LABEL_TO_ID = {
    "relevant": 0,
    "non_target": 1,
    "uncertain": 2,
}
ID_TO_LABEL = {value: key for key, value in LABEL_TO_ID.items()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Gmail secondary-filter checkpoints.")
    parser.add_argument("--eval-file", required=True)
    parser.add_argument("--checkpoint-a", required=True)
    parser.add_argument("--checkpoint-b", required=True)
    parser.add_argument("--output-json", required=True)
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


def load_eval_rows(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            metadata = row.get("metadata") or {}
            rows.append(
                {
                    "text": build_text(row),
                    "label": row["label"],
                    "sample_id": row["sample_id"],
                    "relevant_like": bool(metadata.get("relevant_like")),
                    "risk_tier": metadata.get("risk_tier"),
                    "pattern_family": metadata.get("pattern_family"),
                }
            )
    return rows


def softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=-1, keepdims=True)
    exp = np.exp(shifted)
    return exp / np.sum(exp, axis=-1, keepdims=True)


def evaluate_checkpoint(checkpoint_dir: Path, rows: list[dict]) -> dict:
    tokenizer = AutoTokenizer.from_pretrained(str(checkpoint_dir))
    model = AutoModelForSequenceClassification.from_pretrained(str(checkpoint_dir))
    model.eval()

    import torch

    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    model.to(device)

    all_probs = []
    all_pred_labels = []
    for row in rows:
        encoded = tokenizer(row["text"], truncation=True, max_length=256, return_tensors="pt")
        encoded = {key: value.to(device) for key, value in encoded.items()}
        with torch.no_grad():
            logits = model(**encoded).logits.detach().cpu().numpy()
        probs = softmax(logits)[0]
        all_probs.append(probs.tolist())
        all_pred_labels.append(ID_TO_LABEL[int(np.argmax(probs))])

    y_true = [row["label"] for row in rows]
    report = classification_report(
        y_true,
        all_pred_labels,
        labels=["relevant", "non_target", "uncertain"],
        output_dict=True,
        zero_division=0,
    )

    thresholds = [0.90, 0.95, 0.98, 0.99, 0.995]
    threshold_metrics = {}
    for threshold in thresholds:
        suppressed = []
        suppressed_labels = []
        suppressed_rows = []
        for row, probs in zip(rows, all_probs):
            non_target_prob = probs[LABEL_TO_ID["non_target"]]
            if non_target_prob >= threshold:
                suppressed.append(row["sample_id"])
                suppressed_labels.append(row["label"])
                suppressed_rows.append(row)
        false_suppression = sum(1 for label in suppressed_labels if label != "non_target")
        high_risk_false_suppression = sum(
            1
            for row in suppressed_rows
            if row["label"] != "non_target" and row.get("relevant_like")
        )
        threshold_metrics[str(threshold)] = {
            "suppressed_count": len(suppressed),
            "suppressed_non_target_precision": (
                round(sum(1 for label in suppressed_labels if label == "non_target") / len(suppressed_labels), 4)
                if suppressed_labels
                else None
            ),
            "false_suppression_count": false_suppression,
            "high_risk_false_suppression_count": high_risk_false_suppression,
            "false_suppression_sample_ids": [row["sample_id"] for row in suppressed_rows if row["label"] != "non_target"][:20],
            "high_risk_false_suppression_sample_ids": [
                row["sample_id"]
                for row in suppressed_rows
                if row["label"] != "non_target" and row.get("relevant_like")
            ][:20],
        }

    return {
        "checkpoint": str(checkpoint_dir),
        "classification_report": report,
        "threshold_metrics": threshold_metrics,
    }


def main() -> None:
    args = parse_args()
    rows = load_eval_rows(Path(args.eval_file).expanduser().resolve())
    result = {
        "checkpoint_a": evaluate_checkpoint(Path(args.checkpoint_a).expanduser().resolve(), rows),
        "checkpoint_b": evaluate_checkpoint(Path(args.checkpoint_b).expanduser().resolve(), rows),
    }
    output_path = Path(args.output_json).expanduser().resolve()
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
