from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.labeling.eval_rules import run_eval


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_eval_rules_confusion_and_overlap_handling(tmp_path: Path) -> None:
    pred_path = tmp_path / "rules_labeled.jsonl"
    silver_norm_path = tmp_path / "silver_normalized.jsonl"
    outdir = tmp_path / "rules_eval"

    _write_jsonl(
        pred_path,
        [
            {
                "email_id": "a",
                "label": "KEEP",
                "event_type": "deadline",
                "confidence": 0.9,
            },
            {
                "email_id": "b",
                "label": "DROP",
                "event_type": None,
                "confidence": 0.8,
            },
            {
                "email_id": "c",
                "label": "KEEP",
                "event_type": "exam",
                "confidence": 0.7,
            },
            {
                "email_id": "pred-only",
                "label": "KEEP",
                "event_type": "announcement",
                "confidence": 0.6,
            },
        ],
    )
    _write_jsonl(
        silver_norm_path,
        [
            {
                "email_id": "a",
                "label": "KEEP",
                "event_type": "deadline",
                "confidence": 0.95,
            },
            {
                "email_id": "b",
                "label": "KEEP",
                "event_type": "assignment",
                "confidence": 0.95,
            },
            {
                "email_id": "c",
                "label": "DROP",
                "event_type": None,
                "confidence": 0.95,
            },
            {
                "email_id": "silver-only",
                "label": "KEEP",
                "event_type": "schedule_change",
                "confidence": 0.95,
            },
        ],
    )

    metrics = run_eval(
        pred_path=pred_path,
        silver_path=silver_norm_path,
        silver_normalized_path=silver_norm_path,
        outdir=outdir,
    )

    assert metrics["counts"]["pred_total"] == 4
    assert metrics["counts"]["silver_total"] == 4
    assert metrics["counts"]["overlap_total"] == 3

    label_metrics = metrics["label_metrics"]
    assert label_metrics["tp_keep"] == 1
    assert label_metrics["fp_keep"] == 1
    assert label_metrics["fn_keep"] == 1
    assert label_metrics["tn_drop"] == 0

    confusion_label = _read_json(outdir / "confusion_label.json")
    assert confusion_label["silver_KEEP_pred_KEEP"] == 1
    assert confusion_label["silver_DROP_pred_KEEP"] == 1
    assert confusion_label["silver_KEEP_pred_DROP"] == 1
    assert confusion_label["silver_DROP_pred_DROP"] == 0

    fn_rows = _read_jsonl(outdir / "fn_keep_drop.jsonl")
    fp_rows = _read_jsonl(outdir / "fp_keep_drop.jsonl")
    assert [row["email_id"] for row in fn_rows] == ["b"]
    assert [row["email_id"] for row in fp_rows] == ["c"]


def test_eval_rules_event_macro_micro_and_disagreements(tmp_path: Path) -> None:
    pred_path = tmp_path / "rules_labeled.jsonl"
    silver_norm_path = tmp_path / "silver_normalized.jsonl"
    outdir = tmp_path / "rules_eval"

    _write_jsonl(
        pred_path,
        [
            {"email_id": "x", "label": "KEEP", "event_type": "deadline", "confidence": 0.9},
            {"email_id": "y", "label": "KEEP", "event_type": "exam", "confidence": 0.9},
            {"email_id": "z", "label": "KEEP", "event_type": "assignment", "confidence": 0.9},
        ],
    )
    _write_jsonl(
        silver_norm_path,
        [
            {"email_id": "x", "label": "KEEP", "event_type": "deadline", "confidence": 0.9},
            {"email_id": "y", "label": "KEEP", "event_type": "deadline", "confidence": 0.9},
            {"email_id": "z", "label": "KEEP", "event_type": "assignment", "confidence": 0.9},
        ],
    )

    metrics = run_eval(
        pred_path=pred_path,
        silver_path=silver_norm_path,
        silver_normalized_path=silver_norm_path,
        outdir=outdir,
    )
    event_metrics = metrics["event_metrics"]
    assert event_metrics["total_rows"] == 3
    assert event_metrics["micro_f1"] == round(2 / 3, 6)
    assert event_metrics["macro_f1"] > 0.0

    disagreement_rows = _read_jsonl(outdir / "event_disagreements.jsonl")
    assert [row["email_id"] for row in disagreement_rows] == ["y"]
    confusion_event = _read_json(outdir / "confusion_event_type.json")
    assert confusion_event["deadline"]["exam"] == 1


def test_eval_rules_guardrail_and_delta_outputs(tmp_path: Path) -> None:
    pred_path = tmp_path / "rules_labeled.jsonl"
    silver_norm_path = tmp_path / "silver_normalized.jsonl"
    outdir = tmp_path / "rules_eval"
    baseline_path = tmp_path / "baseline_metrics.json"

    _write_jsonl(
        pred_path,
        [
            {"email_id": "a", "label": "KEEP", "event_type": "deadline", "confidence": 0.9},
            {"email_id": "b", "label": "DROP", "event_type": None, "confidence": 0.9},
            {"email_id": "c", "label": "DROP", "event_type": None, "confidence": 0.9},
        ],
    )
    _write_jsonl(
        silver_norm_path,
        [
            {"email_id": "a", "label": "KEEP", "event_type": "deadline", "confidence": 0.9},
            {"email_id": "b", "label": "KEEP", "event_type": "assignment", "confidence": 0.9},
            {"email_id": "c", "label": "DROP", "event_type": None, "confidence": 0.9},
        ],
    )
    baseline_payload = {
        "label_metrics": {
            "precision_keep": 0.9,
            "recall_keep": 0.4,
            "f1_keep": 0.55,
            "fp_keep": 1,
            "fn_keep": 2,
        }
    }
    baseline_path.write_text(json.dumps(baseline_payload), encoding="utf-8")

    metrics = run_eval(
        pred_path=pred_path,
        silver_path=silver_norm_path,
        silver_normalized_path=silver_norm_path,
        outdir=outdir,
        baseline_metrics_path=baseline_path,
        max_precision_drop=0.2,
    )

    assert "metrics_delta" in metrics
    assert "guardrail" in metrics
    assert (outdir / "metrics_delta.json").is_file()
    assert (outdir / "guardrail.json").is_file()

    delta = _read_json(outdir / "metrics_delta.json")
    guardrail = _read_json(outdir / "guardrail.json")
    assert delta["has_baseline"] is True
    assert guardrail["has_baseline"] is True
    assert guardrail["passed"] is True
