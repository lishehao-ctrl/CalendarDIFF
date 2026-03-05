#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from tools.labeling.label_emails_async import read_mbox_input_emails
    from tools.labeling.rules_extract import EVENT_PRECEDENCE, analyze_email_rules
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    label_module = importlib.import_module("tools.labeling.label_emails_async")
    rules_module = importlib.import_module("tools.labeling.rules_extract")
    read_mbox_input_emails = label_module.read_mbox_input_emails
    EVENT_PRECEDENCE = rules_module.EVENT_PRECEDENCE
    analyze_email_rules = rules_module.analyze_email_rules


@dataclass(frozen=True)
class InspectFnConfig:
    fn_path: Path
    emails_jsonl: Path | None
    input_mbox: Path | None
    pred_path: Path
    silver_path: Path
    out_jsonl: Path
    out_md: Path
    timezone: str
    batch_size: int
    batch_index: int
    snippet_head_chars: int
    snippet_tail_chars: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect FN samples with current deterministic rule traces.")
    parser.add_argument("--fn", default="data/rules_eval/fn_keep_drop.jsonl", help="FN source file path.")
    parser.add_argument("--emails-jsonl", default=None, help="Raw emails JSONL context source.")
    parser.add_argument("--input-mbox", default=None, help="Raw mbox context source.")
    parser.add_argument("--pred", default="data/rules_labeled.jsonl", help="Prediction JSONL for current rule output.")
    parser.add_argument("--silver", default="data/labeled.jsonl", help="Silver labels JSONL.")
    parser.add_argument("--out-jsonl", default="data/rules_eval/fn_inspect_batch.jsonl", help="Inspection JSONL output.")
    parser.add_argument("--out-md", default="data/rules_eval/fn_inspect_batch.md", help="Inspection markdown output.")
    parser.add_argument("--timezone", default="America/Los_Angeles", help="IANA timezone for date parsing.")
    parser.add_argument("--batch-size", type=int, default=10, help="Rows per review batch.")
    parser.add_argument("--batch-index", type=int, default=0, help="0-based batch index.")
    parser.add_argument("--snippet-head-chars", type=int, default=350, help="Chars for snippet_head.")
    parser.add_argument("--snippet-tail-chars", type=int, default=350, help="Chars for snippet_tail.")
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> InspectFnConfig:
    fn_path = Path(args.fn)
    if not fn_path.is_file():
        raise RuntimeError(f"FN file not found: {fn_path}")

    emails_jsonl = Path(args.emails_jsonl) if args.emails_jsonl else None
    input_mbox = Path(args.input_mbox) if args.input_mbox else None
    if (emails_jsonl is None) == (input_mbox is None):
        raise RuntimeError("Exactly one of --emails-jsonl or --input-mbox is required.")
    if emails_jsonl is not None and not emails_jsonl.is_file():
        raise RuntimeError(f"emails JSONL not found: {emails_jsonl}")
    if input_mbox is not None and not input_mbox.is_file():
        raise RuntimeError(f"mbox not found: {input_mbox}")

    pred_path = Path(args.pred)
    if not pred_path.is_file():
        raise RuntimeError(f"Prediction JSONL not found: {pred_path}")
    silver_path = Path(args.silver)
    if not silver_path.is_file():
        raise RuntimeError(f"Silver JSONL not found: {silver_path}")

    timezone = str(args.timezone).strip()
    if not timezone:
        raise RuntimeError("--timezone cannot be blank.")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"Invalid timezone: {timezone}") from exc

    batch_size = int(args.batch_size)
    batch_index = int(args.batch_index)
    if batch_size <= 0:
        raise RuntimeError("--batch-size must be > 0")
    if batch_index < 0:
        raise RuntimeError("--batch-index must be >= 0")

    snippet_head_chars = int(args.snippet_head_chars)
    snippet_tail_chars = int(args.snippet_tail_chars)
    if snippet_head_chars <= 0 or snippet_tail_chars <= 0:
        raise RuntimeError("--snippet-head-chars and --snippet-tail-chars must be > 0")

    return InspectFnConfig(
        fn_path=fn_path,
        emails_jsonl=emails_jsonl,
        input_mbox=input_mbox,
        pred_path=pred_path,
        silver_path=silver_path,
        out_jsonl=Path(args.out_jsonl),
        out_md=Path(args.out_md),
        timezone=timezone,
        batch_size=batch_size,
        batch_index=batch_index,
        snippet_head_chars=snippet_head_chars,
        snippet_tail_chars=snippet_tail_chars,
    )


def _coerce_text(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text if text else None
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


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


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _dedupe_by_email(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        email_id = row.get("email_id")
        if isinstance(email_id, str) and email_id.strip():
            out[email_id.strip()] = row
    return out


def _load_fn_ids(path: Path) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        email_id: str | None = None
        if raw.startswith("{"):
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                value = payload.get("email_id")
                if isinstance(value, str) and value.strip():
                    email_id = value.strip()
        else:
            email_id = raw

        if not email_id or email_id in seen:
            continue
        seen.add(email_id)
        ids.append(email_id)
    return ids


def _load_context_map_from_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    context_map: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        email_id = _coerce_text(row.get("email_id"))
        if not email_id:
            continue
        context_map[email_id] = {
            "from": _coerce_text(row.get("from")),
            "subject": _coerce_text(row.get("subject")),
            "date": _coerce_text(row.get("date")),
            "body_text": _coerce_text(row.get("body_text")) or "",
        }
    return context_map


def _load_context_map_from_mbox(path: Path) -> dict[str, dict[str, Any]]:
    context_map: dict[str, dict[str, Any]] = {}
    rows, _errors = read_mbox_input_emails(path, skip_ids=set())
    for row in rows:
        context_map[row.email_id] = {
            "from": _coerce_text(row.from_field),
            "subject": _coerce_text(row.subject),
            "date": _coerce_text(row.date),
            "body_text": row.body_text or "",
        }
    return context_map


def _slice_head(text: str, count: int) -> str:
    normalized = " ".join(text.split())
    return normalized[:count]


def _slice_tail(text: str, count: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= count:
        return normalized
    return normalized[-count:]


def _build_matched_rules(analysis: Any) -> list[dict[str, str]]:
    ordered = [event for event in EVENT_PRECEDENCE if event != "other"] + ["noise"]
    out: list[dict[str, str]] = []
    for rule_name in ordered:
        snippet = analysis.matched_snippets.get(rule_name)
        if not snippet:
            continue
        out.append({"rule": rule_name, "snippet": snippet})
    if analysis.raw_extract.get("deadline_text"):
        out.append({"rule": "due_parse", "snippet": str(analysis.raw_extract.get("deadline_text"))})
    if analysis.raw_extract.get("location_text"):
        out.append({"rule": "location_parse", "snippet": str(analysis.raw_extract.get("location_text"))})
    return out


def _describe_drop_code(code: str) -> str:
    mapping = {
        "noise_digest": "digest/newsletter style message dominated by low-action signals",
        "no_actionable_signal": "no actionable event signal matched",
        "weak_course_signal": "course context is weak or missing",
        "dropped_by_rule": "dropped by deterministic gating",
    }
    return mapping.get(code, code)


def _render_markdown(rows: list[dict[str, Any]], *, config: InspectFnConfig, total_fn: int) -> str:
    lines: list[str] = []
    lines.append("# FN Inspect Batch")
    lines.append("")
    lines.append(f"- Source FN file: `{config.fn_path}`")
    lines.append(f"- Batch index: `{config.batch_index}`")
    lines.append(f"- Batch size: `{config.batch_size}`")
    lines.append(f"- Total FN ids in source: `{total_fn}`")
    lines.append(f"- Records in this batch: `{len(rows)}`")
    lines.append("")

    for idx, row in enumerate(rows, start=1):
        lines.append(f"## {idx}. {row['email_id']}")
        lines.append("")
        lines.append(f"- Subject: {row.get('subject') or '(missing)'}")
        lines.append(f"- From: {row.get('from') or '(missing)'}")
        lines.append(f"- Date: {row.get('date') or '(missing)'}")
        lines.append(
            f"- Silver: `{row.get('silver_label')}` / `{row.get('silver_event_type')}` | "
            f"Pred: `{row.get('pred_label')}` / `{row.get('pred_event_type')}`"
        )
        lines.append(f"- Pred confidence: `{row.get('pred_confidence')}`")
        miss_reasons = row.get("miss_reasons") or []
        lines.append(f"- Miss reasons: {', '.join(miss_reasons) if miss_reasons else '(none)'}")
        lines.append("- Matched rules:")
        matched_rules = row.get("matched_rules") or []
        if matched_rules:
            for rule in matched_rules:
                lines.append(f"  - `{rule.get('rule')}`: {rule.get('snippet')}")
        else:
            lines.append("  - (none)")
        lines.append("")
        lines.append("### Snippet Head")
        lines.append("```text")
        lines.append(row.get("snippet_head") or "")
        lines.append("```")
        lines.append("")
        lines.append("### Snippet Tail")
        lines.append("```text")
        lines.append(row.get("snippet_tail") or "")
        lines.append("```")
        lines.append("")

    return "\n".join(lines) + "\n"


def run_inspect(config: InspectFnConfig) -> dict[str, Any]:
    all_fn_ids = _load_fn_ids(config.fn_path)
    start = config.batch_index * config.batch_size
    end = start + config.batch_size
    batch_ids = all_fn_ids[start:end]

    if config.emails_jsonl is not None:
        context_map = _load_context_map_from_jsonl(config.emails_jsonl)
    else:
        assert config.input_mbox is not None
        context_map = _load_context_map_from_mbox(config.input_mbox)

    pred_map = _dedupe_by_email(_read_jsonl(config.pred_path))
    silver_map = _dedupe_by_email(_read_jsonl(config.silver_path))
    timezone = ZoneInfo(config.timezone)

    rows: list[dict[str, Any]] = []
    for email_id in batch_ids:
        context = context_map.get(email_id, {})
        subject = _coerce_text(context.get("subject")) or ""
        body_text = _coerce_text(context.get("body_text")) or ""
        date_hint = _coerce_text(context.get("date"))
        from_field = _coerce_text(context.get("from"))

        analysis = analyze_email_rules(
            subject=subject,
            body_text=body_text,
            date_hint=date_hint,
            timezone=timezone,
        )
        pred = pred_map.get(email_id, {})
        silver = silver_map.get(email_id, {})
        due_iso = None
        if analysis.action_items:
            due_iso = analysis.action_items[0].get("due_iso")

        miss_reasons = [_describe_drop_code(code) for code in analysis.drop_reason_codes]
        rows.append(
            {
                "email_id": email_id,
                "subject": subject or None,
                "from": from_field,
                "date": date_hint,
                "silver_label": silver.get("label"),
                "silver_event_type": silver.get("event_type"),
                "pred_label": pred.get("label"),
                "pred_event_type": pred.get("event_type"),
                "pred_confidence": pred.get("confidence"),
                "snippet_head": _slice_head(body_text, config.snippet_head_chars),
                "snippet_tail": _slice_tail(body_text, config.snippet_tail_chars),
                "matched_rules": _build_matched_rules(analysis),
                "miss_reasons": miss_reasons,
                "course_hints_current": analysis.course_hints,
                "due_parse_current": {
                    "due_iso": due_iso,
                    "deadline_text": analysis.raw_extract.get("deadline_text"),
                    "time_text": analysis.raw_extract.get("time_text"),
                    "location_text": analysis.raw_extract.get("location_text"),
                },
            }
        )

    _write_jsonl(config.out_jsonl, rows)
    _write_text(config.out_md, _render_markdown(rows, config=config, total_fn=len(all_fn_ids)))
    return {
        "fn_total": len(all_fn_ids),
        "batch_index": config.batch_index,
        "batch_size": config.batch_size,
        "batch_count": len(rows),
        "out_jsonl": str(config.out_jsonl),
        "out_md": str(config.out_md),
    }


def main() -> int:
    try:
        config = build_config(parse_args())
        summary = run_inspect(config)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
