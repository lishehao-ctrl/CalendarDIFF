from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import get_settings


def save_ics(source_id: int, content: bytes, retrieved_at: datetime) -> dict[str, Any]:
    settings = get_settings()
    retrieved_at_utc = _as_utc(retrieved_at)

    sha256_hex = hashlib.sha256(content).hexdigest()
    file_timestamp = retrieved_at_utc.strftime("%Y-%m-%dT%H-%M-%SZ")
    filename = f"{file_timestamp}__sha256_{sha256_hex}.ics"

    configured_base = Path(settings.evidence_dir).expanduser()
    if configured_base.is_absolute():
        write_base_dir = configured_base
        stored_base_dir = configured_base
    else:
        write_base_dir = (Path.cwd() / configured_base).resolve()
        stored_base_dir = configured_base

    write_source_dir = write_base_dir / "ics" / f"source_{source_id}"
    write_source_dir.mkdir(parents=True, exist_ok=True)

    final_write_path = write_source_dir / filename
    temp_fd, temp_path_str = tempfile.mkstemp(prefix=".tmp_", suffix=".ics", dir=write_source_dir)
    temp_path = Path(temp_path_str)
    try:
        with os.fdopen(temp_fd, "wb") as temp_file:
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, final_write_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    stored_path = (stored_base_dir / "ics" / f"source_{source_id}" / filename).as_posix()
    return {
        "kind": "ics",
        "store": "fs",
        "path": stored_path,
        "sha256": sha256_hex,
        "retrieved_at": retrieved_at_utc.isoformat(),
    }


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
