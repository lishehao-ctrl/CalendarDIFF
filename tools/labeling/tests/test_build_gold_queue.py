from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.labeling.build_gold_queue import GoldQueueConfig, build_gold_queue


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_build_gold_queue_is_deterministic_and_contains_annotation_slots(tmp_path: Path) -> None:
    eval_dir = tmp_path / "rules_eval"
    pred_path = tmp_path / "rules_labeled.jsonl"
    silver_norm = tmp_path / "normalized.jsonl"
    emails_jsonl = tmp_path / "emails.jsonl"
    output_path = tmp_path / "gold_queue.jsonl"

    _write_jsonl(
        eval_dir / "fn_keep_drop.jsonl",
        [{"email_id": f"fn-{idx}"} for idx in range(1, 8)],
    )
    _write_jsonl(
        eval_dir / "event_disagreements.jsonl",
        [{"email_id": f"evt-{idx}"} for idx in range(1, 4)],
    )
    _write_jsonl(
        pred_path,
        [
            {"email_id": f"fn-{idx}", "label": "DROP", "event_type": None, "confidence": 0.2, "reasons": []}
            for idx in range(1, 8)
        ]
        + [
            {"email_id": f"keep-{idx}", "label": "KEEP", "event_type": "deadline", "confidence": 0.8, "reasons": ["r"]}
            for idx in range(1, 8)
        ]
        + [
            {"email_id": f"evt-{idx}", "label": "KEEP", "event_type": "exam", "confidence": 0.7, "reasons": ["r"]}
            for idx in range(1, 4)
        ],
    )
    _write_jsonl(
        silver_norm,
        [
            {"email_id": f"fn-{idx}", "label": "KEEP", "event_type": "deadline"}
            for idx in range(1, 8)
        ]
        + [
            {"email_id": f"keep-{idx}", "label": "KEEP", "event_type": "deadline"}
            for idx in range(1, 8)
        ],
    )
    _write_jsonl(
        emails_jsonl,
        [
            {
                "email_id": f"fn-{idx}",
                "from": "a@x.edu",
                "subject": f"s-{idx}",
                "date": "2026-02-20T10:00:00-08:00",
                "body_text": "body",
            }
            for idx in range(1, 8)
        ],
    )

    config = GoldQueueConfig(
        eval_dir=eval_dir,
        pred_path=pred_path,
        silver_normalized_path=silver_norm,
        emails_jsonl=emails_jsonl,
        input_mbox=None,
        output_path=output_path,
        size=10,
        seed=7,
    )
    summary_a = build_gold_queue(config)
    rows_a = _read_jsonl(output_path)
    summary_b = build_gold_queue(config)
    rows_b = _read_jsonl(output_path)

    assert summary_a["queue_size"] == 10
    assert summary_b["queue_size"] == 10
    assert rows_a == rows_b
    assert all("gold_label" in row for row in rows_a)
    assert all(row["gold_label"] is None for row in rows_a)
    assert all("sample_bucket" in row for row in rows_a)
    assert len({row["email_id"] for row in rows_a}) == len(rows_a)


def test_build_gold_queue_uses_pred_and_silver_fields(tmp_path: Path) -> None:
    eval_dir = tmp_path / "rules_eval"
    pred_path = tmp_path / "rules_labeled.jsonl"
    silver_norm = tmp_path / "normalized.jsonl"
    output_path = tmp_path / "gold_queue.jsonl"

    _write_jsonl(eval_dir / "fn_keep_drop.jsonl", [{"email_id": "x"}])
    _write_jsonl(eval_dir / "event_disagreements.jsonl", [])
    _write_jsonl(
        pred_path,
        [
            {
                "email_id": "x",
                "label": "KEEP",
                "event_type": "deadline",
                "confidence": 0.91,
                "reasons": ["deadline found"],
            }
        ],
    )
    _write_jsonl(
        silver_norm,
        [
            {"email_id": "x", "label": "KEEP", "event_type": "deadline"},
        ],
    )

    config = GoldQueueConfig(
        eval_dir=eval_dir,
        pred_path=pred_path,
        silver_normalized_path=silver_norm,
        emails_jsonl=None,
        input_mbox=None,
        output_path=output_path,
        size=1,
        seed=1,
    )
    build_gold_queue(config)
    rows = _read_jsonl(output_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["email_id"] == "x"
    assert row["silver_label"] == "KEEP"
    assert row["rule_label"] == "KEEP"
    assert row["rule_event_type"] == "deadline"
    assert row["rule_confidence"] == 0.91
