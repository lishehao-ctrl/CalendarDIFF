from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.modules.ingestion.eval.contracts import EvalDataset, IcsEvalPair, MailEvalSample

EXPECTED_MAIL_COUNT = 120
EXPECTED_ICS_PAIR_COUNT = 40
EXPECTED_TOTAL_COUNT = 160


class DatasetLoadError(RuntimeError):
    pass


def load_eval_dataset(*, dataset_root: str | Path) -> EvalDataset:
    root = Path(dataset_root)
    mail_raw_rows = _read_jsonl(root / "mail" / "raw_mail_120.jsonl")
    mail_gold_rows = _read_jsonl(root / "mail" / "gold_mail_120.jsonl")
    mail_ambiguity_rows = _read_jsonl(root / "mail" / "ambiguity_mail_120.jsonl")

    pair_index_rows = _read_jsonl(root / "ics" / "pair_index_40.jsonl")
    ics_gold_rows = _read_jsonl(root / "ics" / "gold_diff_40.jsonl")
    ics_ambiguity_rows = _read_jsonl(root / "ics" / "ambiguity_40.jsonl")

    mail_samples = _build_mail_samples(
        raw_rows=mail_raw_rows,
        gold_rows=mail_gold_rows,
        ambiguity_rows=mail_ambiguity_rows,
    )
    ics_pairs = _build_ics_pairs(
        root=root,
        pair_index_rows=pair_index_rows,
        gold_rows=ics_gold_rows,
        ambiguity_rows=ics_ambiguity_rows,
    )

    if len(mail_samples) != EXPECTED_MAIL_COUNT:
        raise DatasetLoadError(
            f"mail sample count mismatch: expected {EXPECTED_MAIL_COUNT}, got {len(mail_samples)}"
        )
    if len(ics_pairs) != EXPECTED_ICS_PAIR_COUNT:
        raise DatasetLoadError(
            f"ics pair count mismatch: expected {EXPECTED_ICS_PAIR_COUNT}, got {len(ics_pairs)}"
        )
    if len(mail_samples) + len(ics_pairs) != EXPECTED_TOTAL_COUNT:
        raise DatasetLoadError(
            f"dataset total mismatch: expected {EXPECTED_TOTAL_COUNT}, got {len(mail_samples) + len(ics_pairs)}"
        )

    return EvalDataset(mail_samples=mail_samples, ics_pairs=ics_pairs)


def _build_mail_samples(
    *,
    raw_rows: list[dict[str, Any]],
    gold_rows: list[dict[str, Any]],
    ambiguity_rows: list[dict[str, Any]],
) -> list[MailEvalSample]:
    raw_by_id = _index_by_key(raw_rows, key="email_id", name="mail raw")
    gold_by_id = _index_by_key(gold_rows, key="email_id", name="mail gold")
    ambiguity_by_id = _index_by_key(ambiguity_rows, key="email_id", name="mail ambiguity")

    _assert_same_keys(
        left=raw_by_id,
        right=gold_by_id,
        left_name="mail raw",
        right_name="mail gold",
    )
    _assert_same_keys(
        left=raw_by_id,
        right=ambiguity_by_id,
        left_name="mail raw",
        right_name="mail ambiguity",
    )

    ordered_ids = [row["email_id"] for row in raw_rows if isinstance(row.get("email_id"), str)]
    samples: list[MailEvalSample] = []
    for email_id in ordered_ids:
        raw_row = raw_by_id[email_id]
        gold_row = gold_by_id[email_id]
        ambiguity_row = ambiguity_by_id[email_id]

        gold_label = str(gold_row.get("label") or "").strip().upper()
        if gold_label not in {"KEEP", "DROP"}:
            raise DatasetLoadError(f"mail gold label invalid for {email_id}: {gold_label!r}")

        gold_event_value = gold_row.get("event_type")
        gold_event_type = gold_event_value.strip().lower() if isinstance(gold_event_value, str) and gold_event_value.strip() else None

        samples.append(
            MailEvalSample(
                email_id=email_id,
                from_addr=_optional_str(raw_row.get("from")),
                subject=_optional_str(raw_row.get("subject")),
                date=_optional_str(raw_row.get("date")),
                body_text=_optional_str(raw_row.get("body_text")),
                gold_label=gold_label,  # type: ignore[arg-type]
                gold_event_type=gold_event_type,
                ambiguous=bool(ambiguity_row.get("is_ambiguous") is True),
            )
        )
    return samples


def _build_ics_pairs(
    *,
    root: Path,
    pair_index_rows: list[dict[str, Any]],
    gold_rows: list[dict[str, Any]],
    ambiguity_rows: list[dict[str, Any]],
) -> list[IcsEvalPair]:
    index_by_id = _index_by_key(pair_index_rows, key="pair_id", name="ics index")
    gold_by_id = _index_by_key(gold_rows, key="pair_id", name="ics gold")
    ambiguity_by_id = _index_by_key(ambiguity_rows, key="pair_id", name="ics ambiguity")

    _assert_same_keys(
        left=index_by_id,
        right=gold_by_id,
        left_name="ics index",
        right_name="ics gold",
    )
    _assert_same_keys(
        left=index_by_id,
        right=ambiguity_by_id,
        left_name="ics index",
        right_name="ics ambiguity",
    )

    ordered_ids = [row["pair_id"] for row in pair_index_rows if isinstance(row.get("pair_id"), str)]
    pairs: list[IcsEvalPair] = []
    for pair_id in ordered_ids:
        index_row = index_by_id[pair_id]
        gold_row = gold_by_id[pair_id]
        ambiguity_row = ambiguity_by_id[pair_id]

        before_rel = _require_str(index_row.get("before_path"), field=f"{pair_id}.before_path")
        after_rel = _require_str(index_row.get("after_path"), field=f"{pair_id}.after_path")

        before_path = root / before_rel
        after_path = root / after_rel
        if not before_path.is_file():
            raise DatasetLoadError(f"ics before file missing: {before_path}")
        if not after_path.is_file():
            raise DatasetLoadError(f"ics after file missing: {after_path}")

        expected_diff_class = _require_str(
            gold_row.get("expected_diff_class"),
            field=f"{pair_id}.expected_diff_class",
        ).upper()
        if expected_diff_class not in {"DUE_CHANGED", "CREATED", "NO_CHANGE", "REMOVED_CANDIDATE"}:
            raise DatasetLoadError(
                f"ics expected_diff_class invalid for {pair_id}: {expected_diff_class!r}"
            )

        expected_changed_uids_raw = gold_row.get("expected_changed_uids")
        if not isinstance(expected_changed_uids_raw, list):
            raise DatasetLoadError(f"ics expected_changed_uids must be list for {pair_id}")
        expected_changed_uids = [
            uid.strip()
            for uid in expected_changed_uids_raw
            if isinstance(uid, str) and uid.strip()
        ]

        pairs.append(
            IcsEvalPair(
                pair_id=pair_id,
                before_content=before_path.read_bytes(),
                after_content=after_path.read_bytes(),
                expected_diff_class=expected_diff_class,  # type: ignore[arg-type]
                expected_changed_uids=expected_changed_uids,
                ambiguous=bool(ambiguity_row.get("is_ambiguous") is True),
            )
        )
    return pairs


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise DatasetLoadError(f"dataset file missing: {path}")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DatasetLoadError(f"invalid jsonl in {path}:{line_no}") from exc
            if not isinstance(payload, dict):
                raise DatasetLoadError(f"jsonl row must be object in {path}:{line_no}")
            rows.append(payload)
    return rows


def _index_by_key(
    rows: list[dict[str, Any]],
    *,
    key: str,
    name: str,
) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for row in rows:
        raw_value = row.get(key)
        value = raw_value.strip() if isinstance(raw_value, str) else ""
        if not value:
            raise DatasetLoadError(f"{name} row missing {key}")
        if value in mapping:
            raise DatasetLoadError(f"{name} has duplicate {key}: {value}")
        mapping[value] = row
    return mapping


def _assert_same_keys(
    *,
    left: dict[str, Any],
    right: dict[str, Any],
    left_name: str,
    right_name: str,
) -> None:
    left_keys = set(left.keys())
    right_keys = set(right.keys())
    if left_keys != right_keys:
        missing_on_right = sorted(left_keys - right_keys)
        missing_on_left = sorted(right_keys - left_keys)
        raise DatasetLoadError(
            f"id mismatch between {left_name} and {right_name}; "
            f"missing_on_{right_name}={missing_on_right[:5]} missing_on_{left_name}={missing_on_left[:5]}"
        )


def _optional_str(value: object) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _require_str(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetLoadError(f"missing string field: {field}")
    return value.strip()
