from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.labeling.eval_gold import run_eval_gold


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


def test_eval_gold_uses_only_reviewed_rows_and_outputs_fn_fp(tmp_path: Path) -> None:
    gold_path = tmp_path / "gold_queue.jsonl"
    outdir = tmp_path / "rules_eval_gold"
    _write_jsonl(
        gold_path,
        [
            {
                "email_id": "a",
                "rule_label": "KEEP",
                "rule_event_type": "deadline",
                "gold_label": "KEEP",
                "gold_event_type": "deadline",
            },
            {
                "email_id": "b",
                "rule_label": "DROP",
                "rule_event_type": "null",
                "gold_label": "KEEP",
                "gold_event_type": "assignment",
            },
            {
                "email_id": "c",
                "rule_label": "KEEP",
                "rule_event_type": "exam",
                "gold_label": "DROP",
                "gold_event_type": None,
            },
            {
                "email_id": "unreviewed",
                "rule_label": "KEEP",
                "rule_event_type": "deadline",
                "gold_label": None,
                "gold_event_type": None,
            },
        ],
    )

    metrics = run_eval_gold(gold_path=gold_path, outdir=outdir)
    assert metrics["counts"]["gold_total"] == 4
    assert metrics["counts"]["reviewed_total"] == 3
    assert metrics["label_metrics"]["tp_keep"] == 1
    assert metrics["label_metrics"]["fn_keep"] == 1
    assert metrics["label_metrics"]["fp_keep"] == 1
    assert metrics["label_metrics"]["tn_drop"] == 0

    fn_rows = _read_jsonl(outdir / "fn_gold.jsonl")
    fp_rows = _read_jsonl(outdir / "fp_gold.jsonl")
    assert [row["email_id"] for row in fn_rows] == ["b"]
    assert [row["email_id"] for row in fp_rows] == ["c"]

    persisted = _read_json(outdir / "metrics.json")
    assert persisted["counts"]["reviewed_total"] == 3
    assert persisted["event_metrics"]["total_rows"] == 2
