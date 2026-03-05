#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import importlib
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from tools.labeling.label_emails_async import read_mbox_input_emails
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    read_mbox_input_emails = importlib.import_module("tools.labeling.label_emails_async").read_mbox_input_emails


@dataclass(frozen=True)
class GoldQueueConfig:
    eval_dir: Path
    pred_path: Path
    silver_normalized_path: Path
    emails_jsonl: Path | None
    input_mbox: Path | None
    output_path: Path
    size: int
    seed: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build focused gold annotation queue from eval artifacts.")
    parser.add_argument("--eval-dir", default="data/rules_eval", help="Directory from eval_rules output.")
    parser.add_argument("--pred", default="data/rules_labeled.jsonl", help="Rules prediction JSONL path.")
    parser.add_argument("--silver-normalized", default="data/normalized.jsonl", help="Normalized silver JSONL path.")
    parser.add_argument("--emails-jsonl", default=None, help="Optional raw emails JSONL for context.")
    parser.add_argument("--input-mbox", default=None, help="Optional mbox fallback for context.")
    parser.add_argument("--size", type=int, default=150, help="Queue size target.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for deterministic sampling.")
    parser.add_argument("--output", default="data/gold_queue.jsonl", help="Output gold queue JSONL.")
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> GoldQueueConfig:
    eval_dir = Path(args.eval_dir)
    if not eval_dir.is_dir():
        raise RuntimeError(f"Eval dir not found: {eval_dir}")
    pred_path = Path(args.pred)
    if not pred_path.is_file():
        raise RuntimeError(f"Pred JSONL not found: {pred_path}")
    silver_normalized = Path(args.silver_normalized)
    if not silver_normalized.is_file():
        raise RuntimeError(f"Normalized silver JSONL not found: {silver_normalized}")

    emails_jsonl = Path(args.emails_jsonl) if args.emails_jsonl else None
    input_mbox = Path(args.input_mbox) if args.input_mbox else None
    if emails_jsonl is not None and input_mbox is not None:
        raise RuntimeError("Use only one context source: --emails-jsonl or --input-mbox.")
    if emails_jsonl is not None and not emails_jsonl.is_file():
        raise RuntimeError(f"emails.jsonl not found: {emails_jsonl}")
    if input_mbox is not None and not input_mbox.is_file():
        raise RuntimeError(f"mbox not found: {input_mbox}")

    size = int(args.size)
    if size <= 0:
        raise RuntimeError("--size must be > 0")

    return GoldQueueConfig(
        eval_dir=eval_dir,
        pred_path=pred_path,
        silver_normalized_path=silver_normalized,
        emails_jsonl=emails_jsonl,
        input_mbox=input_mbox,
        output_path=Path(args.output),
        size=size,
        seed=int(args.seed),
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _dedupe_by_email(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        email_id = row.get("email_id")
        if isinstance(email_id, str) and email_id.strip():
            out[email_id.strip()] = row
    return out


def _load_context_from_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    context: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        email_id = row.get("email_id")
        if not isinstance(email_id, str) or not email_id.strip():
            continue
        context[email_id.strip()] = {
            "from": row.get("from"),
            "subject": row.get("subject"),
            "date": row.get("date"),
            "body_text": row.get("body_text"),
        }
    return context


def _load_context_from_mbox(path: Path) -> dict[str, dict[str, Any]]:
    context: dict[str, dict[str, Any]] = {}
    rows, _errors = read_mbox_input_emails(path, skip_ids=set())
    for row in rows:
        context[row.email_id] = {
            "from": row.from_field,
            "subject": row.subject,
            "date": row.date,
            "body_text": row.body_text,
        }
    return context


def _pick_rows(
    *,
    rng: random.Random,
    pool: list[dict[str, Any]],
    target: int,
    selected: set[str],
) -> list[dict[str, Any]]:
    candidates = list(pool)
    rng.shuffle(candidates)
    picked: list[dict[str, Any]] = []
    for row in candidates:
        email_id = row.get("email_id")
        if not isinstance(email_id, str) or not email_id.strip():
            continue
        key = email_id.strip()
        if key in selected:
            continue
        selected.add(key)
        picked.append(row)
        if len(picked) >= target:
            break
    return picked


def build_gold_queue(config: GoldQueueConfig) -> dict[str, Any]:
    rng = random.Random(config.seed)
    pred_map = _dedupe_by_email(_read_jsonl(config.pred_path))
    silver_map = _dedupe_by_email(_read_jsonl(config.silver_normalized_path))

    fn_rows = _read_jsonl(config.eval_dir / "fn_keep_drop.jsonl")
    event_rows = _read_jsonl(config.eval_dir / "event_disagreements.jsonl")
    pred_keep_rows = [row for row in pred_map.values() if str(row.get("label")) == "KEEP"]

    target_fn = max(1, int(config.size * 0.7))
    target_keep = max(1, int(config.size * 0.2))
    target_event = max(1, config.size - target_fn - target_keep)

    selected_ids: set[str] = set()
    selected: list[dict[str, Any]] = []

    fn_picked = _pick_rows(rng=rng, pool=fn_rows, target=target_fn, selected=selected_ids)
    for row in fn_picked:
        selected.append({"bucket": "fn_keep_drop", "row": row})

    keep_picked = _pick_rows(rng=rng, pool=pred_keep_rows, target=target_keep, selected=selected_ids)
    for row in keep_picked:
        selected.append({"bucket": "pred_keep_sample", "row": row})

    event_picked = _pick_rows(rng=rng, pool=event_rows, target=target_event, selected=selected_ids)
    for row in event_picked:
        selected.append({"bucket": "event_disagreement", "row": row})

    if len(selected) < config.size:
        fallback_pool = fn_rows + pred_keep_rows + event_rows
        extra = _pick_rows(
            rng=rng,
            pool=fallback_pool,
            target=config.size - len(selected),
            selected=selected_ids,
        )
        for row in extra:
            selected.append({"bucket": "fallback", "row": row})

    if config.emails_jsonl is not None:
        context_map = _load_context_from_jsonl(config.emails_jsonl)
    elif config.input_mbox is not None:
        context_map = _load_context_from_mbox(config.input_mbox)
    else:
        context_map = {}

    output_rows: list[dict[str, Any]] = []
    for item in selected[: config.size]:
        row = item["row"]
        bucket = item["bucket"]
        email_id = str(row.get("email_id"))
        pred = pred_map.get(email_id, {})
        silver = silver_map.get(email_id, {})
        context = context_map.get(email_id, {})
        output_rows.append(
            {
                "email_id": email_id,
                "from": context.get("from"),
                "subject": context.get("subject"),
                "date": context.get("date"),
                "body_text": context.get("body_text"),
                "silver_label": silver.get("label"),
                "silver_event_type": silver.get("event_type"),
                "rule_label": pred.get("label"),
                "rule_event_type": pred.get("event_type"),
                "rule_confidence": pred.get("confidence"),
                "rule_reasons": pred.get("reasons") if isinstance(pred.get("reasons"), list) else [],
                "sample_bucket": bucket,
                "gold_label": None,
                "gold_event_type": None,
                "gold_notes": None,
                "reviewer": None,
                "reviewed_at": None,
            }
        )

    _write_jsonl(config.output_path, output_rows)
    return {
        "output": str(config.output_path),
        "queue_size": len(output_rows),
        "requested_size": config.size,
        "bucket_counts": {
            "fn_keep_drop": len([item for item in output_rows if item["sample_bucket"] == "fn_keep_drop"]),
            "pred_keep_sample": len([item for item in output_rows if item["sample_bucket"] == "pred_keep_sample"]),
            "event_disagreement": len([item for item in output_rows if item["sample_bucket"] == "event_disagreement"]),
            "fallback": len([item for item in output_rows if item["sample_bucket"] == "fallback"]),
        },
    }


def main() -> int:
    try:
        config = build_config(parse_args())
        summary = build_gold_queue(config)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
