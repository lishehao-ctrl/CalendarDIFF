#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.modules.ingestion.eval import (
    DatasetLoadError,
    load_eval_dataset,
    run_ics_eval,
    run_mail_eval,
    summarize_eval_results,
    summary_to_dict,
)
from app.modules.llm_gateway import LlmGatewayError, llm_runtime_overrides, validate_ingestion_llm_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate ingestion LLM pass rate on full synthetic dataset.")
    parser.add_argument(
        "--dataset-root",
        default="data/synthetic/v2_ddlchange_160",
        help="Dataset root directory.",
    )
    parser.add_argument(
        "--report",
        default="data/synthetic/v2_ddlchange_160/qa/llm_pass_rate_report.json",
        help="Output JSON report path.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Max worker threads for online parser calls.",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=None,
        help="Optional override for LLM request timeout seconds.",
    )
    parser.add_argument(
        "--fail-on-threshold",
        action="store_true",
        default=True,
        help="Exit non-zero when threshold checks fail (default: true).",
    )
    parser.add_argument(
        "--no-fail-on-threshold",
        action="store_false",
        dest="fail_on_threshold",
        help="Do not fail process exit code when threshold checks fail.",
    )
    parser.add_argument(
        "--markdown-report",
        default=None,
        help="Optional markdown summary path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    started_at = datetime.now(timezone.utc)
    run_id = f"ingestion-llm-eval-{uuid4().hex[:12]}"

    provider = None
    model = None
    base_url_hash = None
    fatal_errors: list[str] = []

    try:
        profile = validate_ingestion_llm_config()
        provider = profile.provider_id
        model = profile.model
        base_url_hash = hashlib.sha256(profile.base_url.encode("utf-8")).hexdigest()[:12]
    except LlmGatewayError as exc:
        fatal_errors.append(f"config_error:{exc.code}:{exc}")

    mail_results = []
    ics_results = []
    sample_counts = {"mail": 0, "ics_pairs": 0, "total": 0}

    if not fatal_errors:
        try:
            dataset = load_eval_dataset(dataset_root=args.dataset_root)
        except DatasetLoadError as exc:
            fatal_errors.append(f"dataset_error:{exc}")
        else:
            sample_counts = {
                "mail": len(dataset.mail_samples),
                "ics_pairs": len(dataset.ics_pairs),
                "total": len(dataset.mail_samples) + len(dataset.ics_pairs),
            }
            runtime_ctx = (
                llm_runtime_overrides(timeout_seconds=args.request_timeout)
                if args.request_timeout is not None
                else nullcontext()
            )
            try:
                with runtime_ctx:
                    mail_results = run_mail_eval(samples=dataset.mail_samples, max_workers=args.max_workers)
                    ics_results = run_ics_eval(pairs=dataset.ics_pairs, max_workers=args.max_workers)
            except Exception as exc:  # pragma: no cover - defensive top-level guard
                fatal_errors.append(f"runtime_error:{exc}")

    summary = summarize_eval_results(mail_results=mail_results, ics_results=ics_results)
    summary_payload = summary_to_dict(summary)

    finished_at = datetime.now(timezone.utc)
    passed = bool(summary.decision.passed and not fatal_errors)

    report_payload = {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "provider": provider,
        "model": model,
        "base_url_hash": base_url_hash,
        "sample_counts": sample_counts,
        "passed": passed,
        "mail": summary_payload["mail"],
        "ics": summary_payload["ics"],
        "thresholds": summary_payload["thresholds"],
        "threshold_check": summary_payload["threshold_check"],
        "failed_checks": summary_payload["failed_checks"],
        "fatal_errors": fatal_errors,
        "mail_failed_samples": [
            {
                "email_id": row.email_id,
                "error_code": row.error_code,
                "error_message": row.error_message,
            }
            for row in mail_results
            if row.error_code
        ][:30],
        "ics_failed_samples": [
            {
                "pair_id": row.pair_id,
                "error_code": row.error_code,
                "error_message": row.error_message,
            }
            for row in ics_results
            if row.error_code
        ][:30],
    }

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.markdown_report:
        markdown_path = Path(args.markdown_report)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(_render_markdown(report_payload), encoding="utf-8")

    _print_summary(report_payload=report_payload, report_path=report_path)

    if args.fail_on_threshold and not passed:
        return 1
    return 0


def _render_markdown(report_payload: dict) -> str:
    lines = [
        "# Ingestion LLM Pass Rate Report",
        "",
        f"- run_id: `{report_payload['run_id']}`",
        f"- started_at: `{report_payload['started_at']}`",
        f"- finished_at: `{report_payload['finished_at']}`",
        f"- provider: `{report_payload['provider']}`",
        f"- model: `{report_payload['model']}`",
        f"- base_url_hash: `{report_payload['base_url_hash']}`",
        f"- passed: `{report_payload['passed']}`",
        "",
        "## Mail",
        f"- structured_success_rate: `{report_payload['mail']['structured_success_rate']}`",
        f"- label_accuracy: `{report_payload['mail']['label_accuracy']}`",
        f"- event_macro_f1: `{report_payload['mail']['event_macro_f1']}`",
        f"- ambiguous_macro_f1: `{report_payload['mail']['ambiguous_macro_f1']}`",
        f"- non_ambiguous_macro_f1: `{report_payload['mail']['non_ambiguous_macro_f1']}`",
        "",
        "## ICS",
        f"- structured_success_rate: `{report_payload['ics']['structured_success_rate']}`",
        f"- diff_accuracy: `{report_payload['ics']['diff_accuracy']}`",
        f"- uid_hit_rate: `{report_payload['ics']['uid_hit_rate']}`",
        "",
        "## Threshold Check",
    ]
    threshold_check = report_payload.get("threshold_check", {})
    for name, value in threshold_check.items():
        lines.append(f"- {name}: `{value}`")
    failed_checks = report_payload.get("failed_checks", [])
    if failed_checks:
        lines.append("")
        lines.append("## Failed Checks")
        for item in failed_checks:
            lines.append(f"- `{item}`")
    fatal_errors = report_payload.get("fatal_errors", [])
    if fatal_errors:
        lines.append("")
        lines.append("## Fatal Errors")
        for item in fatal_errors:
            lines.append(f"- `{item}`")
    return "\n".join(lines) + "\n"


def _print_summary(*, report_payload: dict, report_path: Path) -> None:
    print(f"run_id={report_payload['run_id']}")
    print(f"report={report_path}")
    print(
        "samples mail={mail} ics_pairs={ics} total={total}".format(
            mail=report_payload["sample_counts"]["mail"],
            ics=report_payload["sample_counts"]["ics_pairs"],
            total=report_payload["sample_counts"]["total"],
        )
    )
    print(
        "mail structured={structured} macro_f1={macro} label_acc={label_acc}".format(
            structured=report_payload["mail"]["structured_success_rate"],
            macro=report_payload["mail"]["event_macro_f1"],
            label_acc=report_payload["mail"]["label_accuracy"],
        )
    )
    print(
        "ics structured={structured} diff_acc={diff_acc} uid_hit={uid_hit}".format(
            structured=report_payload["ics"]["structured_success_rate"],
            diff_acc=report_payload["ics"]["diff_accuracy"],
            uid_hit=report_payload["ics"]["uid_hit_rate"],
        )
    )
    print(f"passed={report_payload['passed']}")
    if report_payload.get("failed_checks"):
        print(f"failed_checks={','.join(report_payload['failed_checks'])}")
    if report_payload.get("fatal_errors"):
        print(f"fatal_errors={len(report_payload['fatal_errors'])}")


if __name__ == "__main__":
    raise SystemExit(main())
