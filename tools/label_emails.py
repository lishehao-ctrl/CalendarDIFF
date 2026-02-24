from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from tools.labeling.label_emails_async import (
    DEFAULT_PROMPT_PATH,
    DEFAULT_SCHEMA_PATH,
    DEFAULT_TOOL_ENV_PATH,
    LabelingConfig,
    configure_logging,
    load_env_file,
    run_labeling_pipeline,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline academic email auto-labeling (mbox only).")
    parser.add_argument("--in", dest="input_mbox", required=True, help="Input mbox file path.")
    parser.add_argument("--out", dest="labeled_jsonl", required=True, help="Output labeled JSONL path.")
    parser.add_argument("--workers", type=int, default=10, help="Concurrent workers (default: 10).")
    parser.add_argument("--max", type=int, default=None, help="Process at most N emails after filtering.")
    parser.add_argument("--dry-run", action="store_true", help="No API call and no output writes.")
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> LabelingConfig:
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required.")

    openai_base_url = os.getenv("OPENAI_BASE_URL", "").strip() or None
    model_name = os.getenv("OPENAI_MODEL", "gpt-5.3-codex").strip() or "gpt-5.3-codex"

    if args.workers <= 0:
        raise RuntimeError("--workers must be > 0")
    if args.max is not None and args.max <= 0:
        raise RuntimeError("--max must be > 0")

    return LabelingConfig(
        openai_api_key=openai_api_key,
        openai_model=model_name,
        openai_base_url=openai_base_url,
        input_mbox=Path(args.input_mbox),
        labeled_jsonl=Path(args.labeled_jsonl),
        error_jsonl=Path(os.getenv("ERROR_JSONL", "data/label_errors.jsonl")),
        workers=args.workers,
        max_retries=int(os.getenv("LABEL_MAX_RETRIES", "6")),
        max_body_chars=int(os.getenv("LABEL_MAX_BODY_CHARS", "12000")),
        max_output_tokens=int(os.getenv("LABEL_MAX_OUTPUT_TOKENS", "600")),
        temperature=float(os.getenv("LABEL_TEMPERATURE", "0.2")),
        max_records=args.max,
        dry_run=args.dry_run,
        prompt_path=Path(os.getenv("EMAIL_LABEL_PROMPT", str(DEFAULT_PROMPT_PATH))),
        schema_path=Path(os.getenv("EMAIL_LABEL_SCHEMA", str(DEFAULT_SCHEMA_PATH))),
    )


def main() -> int:
    configure_logging()
    env_file = Path(os.getenv("LABELING_ENV_FILE", str(DEFAULT_TOOL_ENV_PATH)))
    load_env_file(env_file)

    try:
        args = parse_args()
        config = build_config(args)
        summary = asyncio.run(run_labeling_pipeline(config))
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
