#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

try:
    from tools.labeling.normalize_labeled import NormalizeConfig, run_normalization_pipeline
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from normalize_labeled import NormalizeConfig, run_normalization_pipeline  # type: ignore[no-redef]

EVENT_CLASSES = [
    "deadline",
    "exam",
    "schedule_change",
    "assignment",
    "grade",
    "action_required",
    "announcement",
    "other",
    "null",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate rules_labeled output against normalized silver labels.")
    parser.add_argument("--pred", default="data/rules_labeled.jsonl", help="Rules prediction JSONL.")
    parser.add_argument("--silver", default="data/labeled.jsonl", help="Silver label JSONL (possibly mixed legacy).")
    parser.add_argument(
        "--silver-normalized",
        default=None,
        help="Optional pre-normalized silver JSONL. If absent, normalize --silver on the fly.",
    )
    parser.add_argument("--outdir", default="data/rules_eval", help="Output directory for metrics/artifacts.")
    return parser.parse_args()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise RuntimeError(f"JSONL not found: {path}")
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _normalize_event(value: Any) -> str:
    if value is None:
        return "null"
    text = str(value).strip()
    return text if text else "null"


def _dedupe_by_email(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        email_id = row.get("email_id")
        if not isinstance(email_id, str) or not email_id.strip():
            continue
        deduped[email_id.strip()] = row
    return deduped


def _binary_metrics(tp: int, fp: int, fn: int, tn: int) -> dict[str, Any]:
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    accuracy = (tp + tn) / (tp + tn + fp + fn) if (tp + tn + fp + fn) > 0 else 0.0
    return {
        "tp_keep": tp,
        "fp_keep": fp,
        "fn_keep": fn,
        "tn_drop": tn,
        "precision_keep": round(precision, 6),
        "recall_keep": round(recall, 6),
        "f1_keep": round(f1, 6),
        "accuracy": round(accuracy, 6),
    }


def _event_metrics(confusion: dict[str, dict[str, int]], total: int) -> dict[str, Any]:
    per_class: dict[str, dict[str, float | int]] = {}
    macro_f1_parts: list[float] = []

    for label in EVENT_CLASSES:
        tp = confusion.get(label, {}).get(label, 0)
        fp = sum(confusion.get(other, {}).get(label, 0) for other in EVENT_CLASSES if other != label)
        fn = sum(confusion.get(label, {}).get(other, 0) for other in EVENT_CLASSES if other != label)
        support = sum(confusion.get(label, {}).values())
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
        per_class[label] = {
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
            "support": support,
        }
        if support > 0:
            macro_f1_parts.append(f1)

    correct = sum(confusion.get(label, {}).get(label, 0) for label in EVENT_CLASSES)
    micro_precision = correct / total if total > 0 else 0.0
    macro_f1 = (sum(macro_f1_parts) / len(macro_f1_parts)) if macro_f1_parts else 0.0
    return {
        "total_rows": total,
        "macro_f1": round(macro_f1, 6),
        "micro_f1": round(micro_precision, 6),
        "per_class": per_class,
    }


def _normalize_silver_if_needed(silver_path: Path, normalized_path: Path | None) -> list[dict[str, Any]]:
    if normalized_path is not None:
        return _read_jsonl(normalized_path)

    with tempfile.TemporaryDirectory(prefix="rules_eval_norm_") as temp_dir:
        temp_root = Path(temp_dir)
        config = NormalizeConfig(
            input_path=silver_path,
            output_path=temp_root / "silver_normalized.jsonl",
            errors_path=temp_root / "silver_normalize_errors.jsonl",
            dedupe=True,
            max_action_items=5,
            rescue_llm=False,
            rescue_out_path=temp_root / "silver_rescue_applied.jsonl",
            timezone="America/Los_Angeles",
            schema_path=Path("tools/labeling/schema/email_label.json"),
        )
        run_normalization_pipeline(config)
        return _read_jsonl(config.output_path)


def run_eval(*, pred_path: Path, silver_path: Path, silver_normalized_path: Path | None, outdir: Path) -> dict[str, Any]:
    pred_map = _dedupe_by_email(_read_jsonl(pred_path))
    silver_rows = _normalize_silver_if_needed(silver_path, silver_normalized_path)
    silver_map = _dedupe_by_email(silver_rows)

    overlap_ids = sorted(set(pred_map) & set(silver_map))

    tp = fp = fn = tn = 0
    confusion_event: dict[str, dict[str, int]] = {}
    fn_rows: list[dict[str, Any]] = []
    fp_rows: list[dict[str, Any]] = []
    event_disagreements: list[dict[str, Any]] = []
    event_total = 0

    for email_id in overlap_ids:
        pred = pred_map[email_id]
        silver = silver_map[email_id]
        pred_label = str(pred.get("label") or "DROP")
        silver_label = str(silver.get("label") or "DROP")

        if silver_label == "KEEP" and pred_label == "KEEP":
            tp += 1
        elif silver_label == "DROP" and pred_label == "KEEP":
            fp += 1
            fp_rows.append(
                {
                    "email_id": email_id,
                    "silver_label": silver_label,
                    "pred_label": pred_label,
                    "silver_event_type": silver.get("event_type"),
                    "pred_event_type": pred.get("event_type"),
                }
            )
        elif silver_label == "KEEP" and pred_label == "DROP":
            fn += 1
            fn_rows.append(
                {
                    "email_id": email_id,
                    "silver_label": silver_label,
                    "pred_label": pred_label,
                    "silver_event_type": silver.get("event_type"),
                    "pred_event_type": pred.get("event_type"),
                }
            )
        else:
            tn += 1

        if silver_label == "KEEP":
            event_total += 1
            silver_event = _normalize_event(silver.get("event_type"))
            pred_event = _normalize_event(pred.get("event_type"))
            confusion_event.setdefault(silver_event, {})
            confusion_event[silver_event][pred_event] = confusion_event[silver_event].get(pred_event, 0) + 1
            if pred_label == "KEEP" and pred_event != silver_event:
                event_disagreements.append(
                    {
                        "email_id": email_id,
                        "silver_event_type": silver_event,
                        "pred_event_type": pred_event,
                        "silver_label": silver_label,
                        "pred_label": pred_label,
                    }
                )

    for label in EVENT_CLASSES:
        confusion_event.setdefault(label, {})
        for pred_label in EVENT_CLASSES:
            confusion_event[label].setdefault(pred_label, 0)

    label_confusion = {
        "silver_KEEP_pred_KEEP": tp,
        "silver_DROP_pred_KEEP": fp,
        "silver_KEEP_pred_DROP": fn,
        "silver_DROP_pred_DROP": tn,
    }
    label_metrics = _binary_metrics(tp, fp, fn, tn)
    event_metrics = _event_metrics(confusion_event, total=event_total)

    metrics = {
        "counts": {
            "pred_total": len(pred_map),
            "silver_total": len(silver_map),
            "overlap_total": len(overlap_ids),
        },
        "label_metrics": label_metrics,
        "event_metrics": event_metrics,
    }

    _write_json(outdir / "metrics.json", metrics)
    _write_json(outdir / "confusion_label.json", label_confusion)
    _write_json(outdir / "confusion_event_type.json", confusion_event)
    _write_jsonl(outdir / "fn_keep_drop.jsonl", fn_rows)
    _write_jsonl(outdir / "fp_keep_drop.jsonl", fp_rows)
    _write_jsonl(outdir / "event_disagreements.jsonl", event_disagreements)
    return metrics


def main() -> int:
    try:
        args = parse_args()
        metrics = run_eval(
            pred_path=Path(args.pred),
            silver_path=Path(args.silver),
            silver_normalized_path=Path(args.silver_normalized) if args.silver_normalized else None,
            outdir=Path(args.outdir),
        )
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
