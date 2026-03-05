from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.logging import sanitize_log_message
from app.db.models import Change, Input
from app.modules.review_changes.change_decision_service import ReviewChangeNotFoundError

PREVIEW_MAX_BYTES = 64 * 1024
logger = logging.getLogger(__name__)


class EvidencePathError(RuntimeError):
    pass


class ReviewChangeEvidenceNotFoundError(RuntimeError):
    pass


class ReviewChangeEvidenceReadError(RuntimeError):
    pass


def preview_review_change_evidence(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    side: Literal["before", "after"],
) -> dict:
    row, resolved = resolve_change_evidence_file(db, user_id=user_id, change_id=change_id, side=side)
    try:
        content_bytes = resolved.read_bytes()
    except FileNotFoundError as exc:
        raise ReviewChangeEvidenceNotFoundError("Evidence file not found") from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.error("failed to read evidence preview error=%s", sanitize_log_message(str(exc)))
        raise ReviewChangeEvidenceReadError("Failed to prepare evidence preview") from exc

    truncated = len(content_bytes) > PREVIEW_MAX_BYTES
    preview_text = build_evidence_preview_text(content_bytes)
    return {
        "side": side,
        "content_type": "text/calendar",
        "truncated": truncated,
        "filename": f"change-{row.id}-{side}.ics",
        "event_count": 0,
        "events": [],
        "preview_text": preview_text,
    }


def extract_snapshot_evidence_key(raw_evidence_key: object) -> dict[str, Any] | None:
    if not isinstance(raw_evidence_key, dict):
        return None
    return raw_evidence_key


def extract_snapshot_evidence_path(raw_evidence_key: object) -> str | None:
    key = extract_snapshot_evidence_key(raw_evidence_key)
    if key is None:
        return None
    path_value = key.get("path")
    if isinstance(path_value, str) and path_value:
        return path_value
    return None


def resolve_change_evidence_file(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    side: Literal["before", "after"],
) -> tuple[Change, Path]:
    row = db.scalar(
        select(Change)
        .join(Input, Input.id == Change.input_id)
        .options(joinedload(Change.before_snapshot), joinedload(Change.after_snapshot))
        .where(Change.id == change_id, Input.user_id == user_id)
    )
    if row is None:
        raise ReviewChangeNotFoundError("Review change not found")

    snapshot = row.before_snapshot if side == "before" else row.after_snapshot
    evidence_path = extract_snapshot_evidence_path(snapshot.raw_evidence_key if snapshot is not None else None)
    if evidence_path is None:
        raise ReviewChangeEvidenceNotFoundError("Evidence file not found")

    try:
        resolved = resolve_evidence_file_path(evidence_path)
    except EvidencePathError as exc:
        raise ReviewChangeEvidenceNotFoundError("Evidence file not found") from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.error("failed to resolve evidence path error=%s", sanitize_log_message(str(exc)))
        raise ReviewChangeEvidenceReadError("Failed to prepare evidence file") from exc

    if not resolved.exists() or not resolved.is_file():
        raise ReviewChangeEvidenceNotFoundError("Evidence file not found")
    return row, resolved


def build_evidence_preview_text(content_bytes: bytes) -> str:
    preview_bytes = content_bytes[:PREVIEW_MAX_BYTES]
    return preview_bytes.decode("utf-8", errors="replace")


def resolve_evidence_file_path(raw_path: str) -> Path:
    normalized = raw_path.strip() if isinstance(raw_path, str) else ""
    if not normalized:
        raise EvidencePathError("evidence path is empty")

    settings = get_settings()
    configured_base = Path(settings.evidence_dir).expanduser()
    if configured_base.is_absolute():
        base_dir = configured_base.resolve()
    else:
        base_dir = (Path.cwd() / configured_base).resolve()

    path_obj = Path(normalized).expanduser()
    if path_obj.is_absolute():
        resolved = path_obj.resolve()
    else:
        resolved = (base_dir / path_obj).resolve()

    if not is_relative_to(resolved, base_dir):
        raise EvidencePathError("evidence path escaped base directory")
    return resolved


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


__all__ = [
    "EvidencePathError",
    "ReviewChangeEvidenceNotFoundError",
    "ReviewChangeEvidenceReadError",
    "preview_review_change_evidence",
]
