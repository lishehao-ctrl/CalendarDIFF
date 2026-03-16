from __future__ import annotations

import argparse
import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.db.models.input import InputSource
from app.db.session import get_session_factory
from app.modules.common.source_term_window import parse_source_term_window
from app.modules.input_control_plane.source_secrets import decode_source_secrets
from app.modules.sync.gmail_client import GmailClient

REPO_ROOT = Path(__file__).resolve().parents[1]
PRIVATE_ROOT = REPO_ROOT / "tests" / "fixtures" / "private" / "email_pool"
SYNTHETIC_SOURCE_PATH = REPO_ROOT / "tests" / "fixtures" / "synthetic_gmail_ddlchange_samples.json"

MAX_BODY_CHARS = 12000
DEFAULT_SOURCE_ID = 2
DEFAULT_SCAN_LIMIT = 2500

BUCKET_SYNTHETIC = "synthetic_ddlchange"
BUCKET_RANDOM = "oauth_random_300"
BUCKET_FILTERED = "oauth_filtered_150"
ALL_BUCKETS = (BUCKET_SYNTHETIC, BUCKET_RANDOM, BUCKET_FILTERED)

TARGET_BY_BUCKET = {
    BUCKET_SYNTHETIC: 30,
    BUCKET_RANDOM: 300,
    BUCKET_FILTERED: 150,
}

BROAD_TOKEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("token:course", re.compile(r"\\bcourse\\b", re.IGNORECASE)),
    ("token:quiz", re.compile(r"\\bquiz(?:zes)?\\b", re.IGNORECASE)),
    ("token:exam", re.compile(r"\\bexam(?:s)?\\b", re.IGNORECASE)),
    ("token:midterm", re.compile(r"\\bmidterm(?:s)?\\b", re.IGNORECASE)),
    ("token:final", re.compile(r"\\bfinal(?:s)?\\b", re.IGNORECASE)),
    ("token:homework", re.compile(r"\\bhomework\\b|\\bhw\\b", re.IGNORECASE)),
    ("token:assignment", re.compile(r"\\bassignment(?:s)?\\b", re.IGNORECASE)),
    ("token:project", re.compile(r"\\bproject(?:s)?\\b", re.IGNORECASE)),
    ("token:problem_set", re.compile(r"\\bproblem\\s*set(?:s)?\\b", re.IGNORECASE)),
    (
        "pattern:dept_number",
        re.compile(
            r"\\b(?:CSE|MATH|CHEM|PHYS|ECE|DSC|BILD|ECON|MAE|SE|COGS|BENG|PSYC|MGT|MUS)\\s*[- ]?\\s*\\d{1,3}[A-Z]?\\b",
            re.IGNORECASE,
        ),
    ),
]
BROAD_GMAIL_QUERY = (
    '("course" OR "quiz" OR "exam" OR "midterm" OR "final" OR "homework" OR '
    '"assignment" OR "project" OR "problem set" OR "CSE" OR "MATH" OR "CHEM" OR "PHYS" OR "ECE" OR "DSC")'
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build private email-pool fixtures for Gmail parser evaluation.")
    parser.add_argument(
        "--bucket",
        choices=["all", BUCKET_SYNTHETIC, BUCKET_RANDOM, BUCKET_FILTERED],
        default="all",
        help="Which bucket to build.",
    )
    parser.add_argument("--source-id", type=int, default=None, help="Gmail source id. Defaults to active source or id=2.")
    parser.add_argument("--scan-limit", type=int, default=DEFAULT_SCAN_LIMIT, help="Max candidate message ids to scan.")
    parser.add_argument("--seed", type=int, default=20260316, help="Deterministic random sampling seed.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    selected_buckets = list(ALL_BUCKETS) if args.bucket == "all" else [args.bucket]

    source_id = args.source_id
    if source_id is None and any(bucket in {BUCKET_RANDOM, BUCKET_FILTERED} for bucket in selected_buckets):
        source_id = discover_default_gmail_source_id() or DEFAULT_SOURCE_ID

    if BUCKET_SYNTHETIC in selected_buckets:
        build_synthetic_bucket(seed=args.seed)

    if BUCKET_RANDOM in selected_buckets:
        if source_id is None:
            raise RuntimeError("source-id is required for oauth_random_300")
        build_oauth_random_bucket(source_id=source_id, scan_limit=args.scan_limit, seed=args.seed)

    if BUCKET_FILTERED in selected_buckets:
        if source_id is None:
            raise RuntimeError("source-id is required for oauth_filtered_150")
        build_oauth_filtered_bucket(source_id=source_id, scan_limit=args.scan_limit, seed=args.seed)


def discover_default_gmail_source_id() -> int | None:
    session_factory = get_session_factory()
    with session_factory() as db:
        rows = (
            db.execute(
                select(InputSource)
                .where(InputSource.provider == "gmail", InputSource.is_active.is_(True))
                .order_by(InputSource.id.asc())
            )
            .scalars()
            .all()
        )
        if rows:
            return rows[0].id
        fallback = db.execute(select(InputSource).where(InputSource.provider == "gmail").order_by(InputSource.id.asc())).scalars().first()
        return fallback.id if fallback is not None else None


def build_synthetic_bucket(*, seed: int) -> None:
    if not SYNTHETIC_SOURCE_PATH.exists():
        raise FileNotFoundError(f"synthetic source file not found: {SYNTHETIC_SOURCE_PATH}")

    source_rows = json.loads(SYNTHETIC_SOURCE_PATH.read_text(encoding="utf-8"))
    if not isinstance(source_rows, list):
        raise RuntimeError("synthetic source file must contain a JSON array")

    samples: list[dict[str, Any]] = []
    for index, row in enumerate(source_rows, start=1):
        if not isinstance(row, dict):
            continue
        sample_id = str(row.get("sample_id") or f"syn-{index:03d}")
        expected_mode = str(row.get("expected_mode") or "atomic")

        semantic = row.get("expected_semantic_event_draft")
        due_date = None
        if isinstance(semantic, dict) and isinstance(semantic.get("due_date"), str):
            due_date = semantic.get("due_date")
        internal_date = f"{due_date}T12:00:00Z" if due_date else "2026-03-16T12:00:00Z"

        samples.append(
            {
                "sample_id": sample_id,
                "sample_source": "synthetic.generated.ddlchange",
                "message_id": f"synthetic-{sample_id}@fixture.local",
                "thread_id": f"synthetic-thread-{sample_id}",
                "subject": str(row.get("subject") or ""),
                "from_header": str(row.get("from_header") or ""),
                "snippet": str(row.get("snippet") or ""),
                "body_text": normalize_body_text(row.get("body_text"))[0],
                "internal_date": internal_date,
                "label_ids": ["INBOX"],
                "collection_bucket": BUCKET_SYNTHETIC,
                "notes": str(row.get("notes") or "synthetic ddlchange positive sample"),
                "expected_mode": expected_mode,
                "expected_record_type": str(row.get("expected_record_type") or "gmail.message.extracted"),
                "expected_semantic_event_draft": row.get("expected_semantic_event_draft"),
                "expected_directive": row.get("expected_directive"),
            }
        )

    bucket_dir = PRIVATE_ROOT / BUCKET_SYNTHETIC
    write_bucket_outputs(
        bucket_dir=bucket_dir,
        samples=samples,
        manifest={
            "bucket": BUCKET_SYNTHETIC,
            "generated_at": now_utc_iso(),
            "source": str(SYNTHETIC_SOURCE_PATH),
            "seed": seed,
            "target_count": TARGET_BY_BUCKET[BUCKET_SYNTHETIC],
            "sample_count": len(samples),
            "expected_mode_breakdown": count_by_key(samples, "expected_mode"),
            "notes": "Normalized from synthetic Gmail ddlchange set into shared email-pool sample schema.",
        },
        readme_text=render_bucket_readme(
            bucket=BUCKET_SYNTHETIC,
            summary_lines=[
                "Contains synthetic positive ddlchange Gmail-like samples.",
                "Use for recall and parser regression checks on known-positive events/directives.",
                "Records include expected semantic outputs for downstream assertions.",
            ],
        ),
    )


def build_oauth_random_bucket(*, source_id: int, scan_limit: int, seed: int) -> None:
    target = TARGET_BY_BUCKET[BUCKET_RANDOM]
    source_meta, access_token = resolve_source_and_access_token(source_id=source_id)
    client = GmailClient()

    term_window_json = source_meta.get("term_window")
    candidate_ids = list_candidate_ids(
        client=client,
        access_token=access_token,
        term_query_bounds=source_meta.get("term_query_bounds"),
        scan_limit=scan_limit,
    )
    selected_ids = select_ids_deterministic(candidate_ids, target=target, seed=seed)

    samples: list[dict[str, Any]] = []
    for idx, message_id in enumerate(selected_ids, start=1):
        metadata = client.get_message_metadata(access_token=access_token, message_id=message_id)
        body_text, was_truncated = normalize_body_text(metadata.body_text)
        notes = "random inbox sample"
        if was_truncated:
            notes += "; body_text truncated"
        samples.append(
            {
                "sample_id": f"{BUCKET_RANDOM}-{idx:04d}",
                "sample_source": "gmail.oauth",
                "message_id": metadata.message_id,
                "thread_id": metadata.thread_id,
                "subject": metadata.subject,
                "from_header": metadata.from_header,
                "snippet": metadata.snippet,
                "body_text": body_text,
                "internal_date": metadata.internal_date or now_utc_iso(),
                "label_ids": metadata.label_ids,
                "collection_bucket": BUCKET_RANDOM,
                "notes": notes,
                "filter_reason": "inbox_random_term_preferred",
                "source_id": source_id,
            }
        )

    bucket_dir = PRIVATE_ROOT / BUCKET_RANDOM
    write_bucket_outputs(
        bucket_dir=bucket_dir,
        samples=samples,
        manifest={
            "bucket": BUCKET_RANDOM,
            "generated_at": now_utc_iso(),
            "source_id": source_id,
            "seed": seed,
            "scan_limit": scan_limit,
            "target_count": target,
            "sample_count": len(samples),
            "term_window": term_window_json,
            "candidate_count": len(candidate_ids),
            "duplicate_message_ids": duplicate_count(samples),
            "notes": "Inbox random pool with active-term preference; includes realistic background noise.",
        },
        readme_text=render_bucket_readme(
            bucket=BUCKET_RANDOM,
            summary_lines=[
                "Contains real Gmail samples collected through OAuth source without product parser filter.",
                "Sampling prefers active-term inbox messages first, then fills from broader inbox history.",
                "Use for precision/noise evaluation and mixed-set composition.",
            ],
        ),
    )


def build_oauth_filtered_bucket(*, source_id: int, scan_limit: int, seed: int) -> None:
    target = TARGET_BY_BUCKET[BUCKET_FILTERED]
    source_meta, access_token = resolve_source_and_access_token(source_id=source_id)
    client = GmailClient()

    candidate_ids = list_filtered_candidate_ids(
        client=client,
        access_token=access_token,
        term_query_bounds=source_meta.get("term_query_bounds"),
        scan_limit=scan_limit,
    )
    selected_ids = select_ids_deterministic(candidate_ids, target=target, seed=seed)
    samples: list[dict[str, Any]] = []
    for idx, message_id in enumerate(selected_ids, start=1):
        metadata = client.get_message_metadata(access_token=access_token, message_id=message_id)
        matched, reason = matches_broad_course_filter(metadata)
        if not matched:
            reason = "gmail_query_match"
        body_text, was_truncated = normalize_body_text(metadata.body_text)
        notes = "broad course-like filter hit"
        if was_truncated:
            notes += "; body_text truncated"
        samples.append(
            {
                "sample_id": f"{BUCKET_FILTERED}-{idx:04d}",
                "sample_source": "gmail.oauth",
                "message_id": metadata.message_id,
                "thread_id": metadata.thread_id,
                "subject": metadata.subject,
                "from_header": metadata.from_header,
                "snippet": metadata.snippet,
                "body_text": body_text,
                "internal_date": metadata.internal_date or now_utc_iso(),
                "label_ids": metadata.label_ids,
                "collection_bucket": BUCKET_FILTERED,
                "notes": notes,
                "filter_reason": reason,
                "source_id": source_id,
            }
        )

    bucket_dir = PRIVATE_ROOT / BUCKET_FILTERED
    write_bucket_outputs(
        bucket_dir=bucket_dir,
        samples=samples,
        manifest={
            "bucket": BUCKET_FILTERED,
            "generated_at": now_utc_iso(),
            "source_id": source_id,
            "seed": seed,
            "scan_limit": scan_limit,
            "target_count": target,
            "sample_count": len(samples),
            "matched_before_sampling": len(candidate_ids),
            "filter_reason_breakdown": count_by_key(samples, "filter_reason"),
            "duplicate_message_ids": duplicate_count(samples),
            "notes": "Broad inbox+course-token filtered pool; intentionally includes false positives and edge cases.",
        },
        readme_text=render_bucket_readme(
            bucket=BUCKET_FILTERED,
            summary_lines=[
                "Contains real Gmail samples from inbox using broad course-like text markers.",
                "Filter remains intentionally wider than product parser gating logic.",
                "Useful for semi-relevant pool testing and precision stress with noisy positives.",
            ],
        ),
    )


def resolve_source_and_access_token(*, source_id: int) -> tuple[dict[str, Any], str]:
    session_factory = get_session_factory()
    with session_factory() as db:
        source = db.get(InputSource, source_id)
        if source is None:
            raise RuntimeError(f"gmail source id={source_id} not found")
        if source.provider != "gmail":
            raise RuntimeError(f"source id={source_id} is not a gmail source")

        secrets = decode_source_secrets(source)
        refresh_token = secrets.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise RuntimeError(f"gmail source id={source_id} missing refresh_token")

        client = GmailClient()
        access_token = client.refresh_access_token(refresh_token=refresh_token).access_token
        if not isinstance(access_token, str) or not access_token:
            raise RuntimeError(f"gmail source id={source_id} did not return access_token")
        term_window = parse_source_term_window(source, required=False)
        source_meta = {
            "id": source.id,
            "term_window": term_window.to_config_json() if term_window is not None else None,
            "term_query_bounds": list(term_window.gmail_query_bounds()) if term_window is not None else None,
        }
        return source_meta, access_token


def list_candidate_ids(
    *,
    client: GmailClient,
    access_token: str,
    term_query_bounds: list[str] | None,
    scan_limit: int,
) -> list[str]:
    ids: list[str] = []

    if isinstance(term_query_bounds, list) and len(term_query_bounds) == 2:
        start_date, end_exclusive = term_query_bounds[0], term_query_bounds[1]
        if isinstance(start_date, str) and isinstance(end_exclusive, str):
            term_ids = client.list_message_ids(
                access_token=access_token,
                query=f"after:{start_date} before:{end_exclusive}",
                label_ids=["INBOX"],
            )
            ids.extend(term_ids)

    fallback_ids = client.list_message_ids(
        access_token=access_token,
        query="newer_than:5y",
        label_ids=["INBOX"],
    )
    ids.extend(fallback_ids)

    deduped = dedupe_preserve_order(ids)
    if scan_limit > 0:
        return deduped[:scan_limit]
    return deduped


def list_filtered_candidate_ids(
    *,
    client: GmailClient,
    access_token: str,
    term_query_bounds: list[str] | None,
    scan_limit: int,
) -> list[str]:
    ids: list[str] = []
    if isinstance(term_query_bounds, list) and len(term_query_bounds) == 2:
        start_date, end_exclusive = term_query_bounds[0], term_query_bounds[1]
        if isinstance(start_date, str) and isinstance(end_exclusive, str):
            term_query = f'after:{start_date} before:{end_exclusive} {BROAD_GMAIL_QUERY}'
            ids.extend(client.list_message_ids(access_token=access_token, query=term_query, label_ids=["INBOX"]))

    fallback_query = f'newer_than:5y {BROAD_GMAIL_QUERY}'
    ids.extend(client.list_message_ids(access_token=access_token, query=fallback_query, label_ids=["INBOX"]))

    deduped = dedupe_preserve_order(ids)
    if scan_limit > 0:
        return deduped[:scan_limit]
    return deduped


def matches_broad_course_filter(metadata: Any) -> tuple[bool, str]:
    label_ids = [item for item in (metadata.label_ids or []) if isinstance(item, str)]
    if "INBOX" not in label_ids:
        return False, "missing_inbox"

    text = "\n".join(
        [
            str(metadata.subject or ""),
            str(metadata.snippet or ""),
            str(metadata.body_text or ""),
            str(metadata.from_header or ""),
        ]
    )

    for reason, pattern in BROAD_TOKEN_PATTERNS:
        if pattern.search(text):
            return True, reason
    return False, "no_course_like_token"


def normalize_body_text(value: Any) -> tuple[str, bool]:
    if not isinstance(value, str):
        return "", False
    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) <= MAX_BODY_CHARS:
        return text, False
    return text[:MAX_BODY_CHARS], True


def select_ids_deterministic(candidate_ids: list[str], *, target: int, seed: int) -> list[str]:
    if len(candidate_ids) <= target:
        return candidate_ids
    rng = random.Random(seed)
    picked_indices = rng.sample(range(len(candidate_ids)), target)
    return [candidate_ids[idx] for idx in picked_indices]


def write_bucket_outputs(*, bucket_dir: Path, samples: list[dict[str, Any]], manifest: dict[str, Any], readme_text: str) -> None:
    bucket_dir.mkdir(parents=True, exist_ok=True)

    samples_path = bucket_dir / "samples.jsonl"
    with samples_path.open("w", encoding="utf-8") as handle:
        for row in samples:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    (bucket_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (bucket_dir / "README.md").write_text(readme_text, encoding="utf-8")


def render_bucket_readme(*, bucket: str, summary_lines: list[str]) -> str:
    lines = [f"# {bucket}", "", "## Summary", ""]
    for line in summary_lines:
        lines.append(f"- {line}")
    lines.extend(
        [
            "",
            "## Files",
            "",
            "- manifest.json",
            "- samples.jsonl",
            "- README.md",
            "",
            "## Privacy",
            "",
            "- Data remains under tests/fixtures/private/email_pool/.",
            "- No attachments are stored.",
            "- Body text is plain text only.",
        ]
    )
    return "\n".join(lines) + "\n"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def duplicate_count(samples: list[dict[str, Any]]) -> int:
    seen: set[str] = set()
    duplicates = 0
    for row in samples:
        message_id = row.get("message_id")
        if not isinstance(message_id, str):
            continue
        if message_id in seen:
            duplicates += 1
            continue
        seen.add(message_id)
    return duplicates


def count_by_key(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        raw = row.get(key)
        k = str(raw)
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda item: item[0]))


if __name__ == "__main__":
    main()
