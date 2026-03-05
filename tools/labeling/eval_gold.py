#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import importlib
from pathlib import Path
from typing import Any

try:
    from tools.labeling.eval_rules import EVENT_CLASSES
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    EVENT_CLASSES = importlib.import_module("tools.labeling.eval_rules").EVENT_CLASSES


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate rules against reviewed gold queue labels.")
    parser.add_argument("--gold", default="data/gold_queue.jsonl", help="Gold queue JSONL with reviewed labels.")
    parser.add_argument("--outdir", default="data/rules_eval_gold", help="Output directory for gold metrics.")
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
    micro = correct / total if total > 0 else 0.0
    macro = (sum(macro_f1_parts) / len(macro_f1_parts)) if macro_f1_parts else 0.0
    return {
        "total_rows": total,
        "macro_f1": round(macro, 6),
        "micro_f1": round(micro, 6),
        "per_class": per_class,
    }


def run_eval_gold(*, gold_path: Path, outdir: Path) -> dict[str, Any]:
    rows = _read_jsonl(gold_path)
    reviewed: list[dict[str, Any]] = []
    for row in rows:
        gold_label = row.get("gold_label")
        if isinstance(gold_label, str) and gold_label.strip():
            reviewed.append(row)

    tp = fp = fn = tn = 0
    confusion_event: dict[str, dict[str, int]] = {}
    fn_rows: list[dict[str, Any]] = []
    fp_rows: list[dict[str, Any]] = []
    event_total = 0

    for row in reviewed:
        email_id = str(row.get("email_id") or "unknown")
        truth_label = str(row.get("gold_label") or "").strip().upper()
        pred_label = str(row.get("rule_label") or "DROP").strip().upper()
        if truth_label == "KEEP" and pred_label == "KEEP":
            tp += 1
        elif truth_label == "DROP" and pred_label == "KEEP":
            fp += 1
            fp_rows.append({"email_id": email_id, "gold_label": truth_label, "rule_label": pred_label})
        elif truth_label == "KEEP" and pred_label == "DROP":
            fn += 1
            fn_rows.append({"email_id": email_id, "gold_label": truth_label, "rule_label": pred_label})
        elif truth_label == "DROP" and pred_label == "DROP":
            tn += 1

        if truth_label == "KEEP":
            event_total += 1
            gold_event = _normalize_event(row.get("gold_event_type"))
            pred_event = _normalize_event(row.get("rule_event_type"))
            confusion_event.setdefault(gold_event, {})
            confusion_event[gold_event][pred_event] = confusion_event[gold_event].get(pred_event, 0) + 1

    for label in EVENT_CLASSES:
        confusion_event.setdefault(label, {})
        for pred in EVENT_CLASSES:
            confusion_event[label].setdefault(pred, 0)

    metrics = {
        "counts": {
            "gold_total": len(rows),
            "reviewed_total": len(reviewed),
        },
        "label_metrics": _binary_metrics(tp, fp, fn, tn),
        "event_metrics": _event_metrics(confusion_event, total=event_total),
    }
    _write_json(outdir / "metrics.json", metrics)
    _write_jsonl(outdir / "fn_gold.jsonl", fn_rows)
    _write_jsonl(outdir / "fp_gold.jsonl", fp_rows)
    return metrics


def main() -> int:
    try:
        args = parse_args()
        metrics = run_eval_gold(gold_path=Path(args.gold), outdir=Path(args.outdir))
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
