#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Iterator

from jsonschema import Draft202012Validator

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_PATH = ROOT_DIR / "tools" / "labeling" / "schema" / "email_label.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate labeled JSONL for local-enforced email labeling pipeline.")
    parser.add_argument(
        "--input",
        default=os.getenv("LABELED_JSONL", "data/labeled.jsonl"),
        help="Path to labeled JSONL (default: data/labeled.jsonl or LABELED_JSONL).",
    )
    parser.add_argument(
        "--schema",
        default=str(DEFAULT_SCHEMA_PATH),
        help="Path to local validation schema.",
    )
    parser.add_argument(
        "--errors",
        default=os.getenv("ERROR_JSONL", "data/label_errors.jsonl"),
        help="Optional label_errors.jsonl path for sidecar summary.",
    )
    return parser.parse_args()


def iter_jsonl(path: Path) -> Iterator[tuple[int, dict[str, object]]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"Line {line_number} is not a JSON object.")
            yield line_number, payload


def is_confidence_in_range(value: object) -> bool:
    return isinstance(value, (int, float)) and 0.0 <= float(value) <= 1.0


def summarize_error_sidecar(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {
            "error_sidecar_path": str(path),
            "error_sidecar_exists": False,
            "error_sidecar_count": 0,
            "invalid_after_repair_count": 0,
        }

    total = 0
    invalid_after_repair = 0
    for _, payload in iter_jsonl(path):
        total += 1
        if payload.get("error_type") == "json_invalid_after_repair":
            invalid_after_repair += 1
    return {
        "error_sidecar_path": str(path),
        "error_sidecar_exists": True,
        "error_sidecar_count": total,
        "invalid_after_repair_count": invalid_after_repair,
    }


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    schema_path = Path(args.schema)
    errors_path = Path(args.errors)

    if not input_path.is_file():
        raise SystemExit(f"Labeled JSONL not found: {input_path}")
    if not schema_path.is_file():
        raise SystemExit(f"Schema file not found: {schema_path}")

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    total_count = 0
    valid_count = 0
    invalid_count = 0
    schema_invalid_count = 0
    logic_invalid_count = 0

    keep_count = 0
    low_confidence_count = 0
    action_items_total = 0
    event_type_counter: Counter[str] = Counter()

    errors: list[dict[str, object]] = []
    warnings: list[str] = []

    for line_number, payload in iter_jsonl(input_path):
        total_count += 1
        schema_errors: list[str] = [err.message for err in validator.iter_errors(payload)]
        logic_errors: list[str] = []

        label = payload.get("label")
        confidence = payload.get("confidence")
        reasons = payload.get("reasons")
        action_items = payload.get("action_items")
        event_type = payload.get("event_type")

        if label not in {"KEEP", "DROP"}:
            logic_errors.append("label must be KEEP or DROP")
        if not is_confidence_in_range(confidence):
            logic_errors.append("confidence must be in [0,1]")
        if not isinstance(reasons, list):
            logic_errors.append("reasons must be an array")
        if not isinstance(action_items, list):
            logic_errors.append("action_items must be an array")
        elif label == "DROP" and len(action_items) != 0:
            logic_errors.append("DROP label should have empty action_items")
        if label == "DROP" and event_type is not None:
            logic_errors.append("DROP label should use event_type=null")

        row_issues = schema_errors + logic_errors
        if row_issues:
            invalid_count += 1
            if schema_errors:
                schema_invalid_count += 1
            if logic_errors:
                logic_invalid_count += 1
            errors.append(
                {
                    "line": line_number,
                    "email_id": payload.get("email_id"),
                    "schema_issues": schema_errors,
                    "logic_issues": logic_errors,
                    "issues": row_issues,
                }
            )
            continue

        valid_count += 1
        if label == "KEEP":
            keep_count += 1
        if isinstance(confidence, (int, float)) and float(confidence) < 0.6:
            low_confidence_count += 1
        if isinstance(action_items, list):
            action_items_total += len(action_items)
        if isinstance(event_type, str):
            event_type_counter[event_type] += 1

    keep_ratio = (keep_count / valid_count) if valid_count else 0.0
    avg_action_items = (action_items_total / valid_count) if valid_count else 0.0
    low_confidence_ratio = (low_confidence_count / valid_count) if valid_count else 0.0

    if valid_count:
        if keep_ratio < 0.05 or keep_ratio > 0.95:
            warnings.append(f"keep_ratio={keep_ratio:.4f} is unusual; verify prompt/model settings.")
        if low_confidence_ratio > 0.5:
            warnings.append(f"low_confidence_ratio={low_confidence_ratio:.4f} is high; review label quality.")
        if event_type_counter:
            max_bucket = max(event_type_counter.values())
            max_bucket_ratio = max_bucket / valid_count
            if max_bucket_ratio > 0.9:
                warnings.append(
                    f"event_type distribution is highly concentrated (max_ratio={max_bucket_ratio:.4f}); "
                    "check prompt drift."
                )

    sidecar_summary = summarize_error_sidecar(errors_path)

    report = {
        "input": str(input_path),
        "total_count": total_count,
        "valid_count": valid_count,
        "invalid_count": invalid_count,
        "schema_invalid_count": schema_invalid_count,
        "logic_invalid_count": logic_invalid_count,
        "keep_ratio": round(keep_ratio, 4),
        "event_type_distribution": dict(event_type_counter),
        "avg_action_items_per_row": round(avg_action_items, 4),
        "low_confidence_ratio": round(low_confidence_ratio, 4),
        "warnings": warnings,
        "errors": errors[:50],
        **sidecar_summary,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if invalid_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
