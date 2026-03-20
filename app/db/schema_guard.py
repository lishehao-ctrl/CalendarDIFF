from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db.base import Base
from app.db.model_registry import load_all_models


_SCHEMA_CACHE: dict[str, SchemaNotReadyError | None] = {}

_SCHEMA_ERROR_HINTS = (
    'relation "',
    'column "',
    "no such table",
    "no such column",
    "undefinedtable",
    "undefinedcolumn",
    "does not exist",
    "alembic_version",
)


class SchemaNotReadyError(RuntimeError):
    """Raised when the connected database revision does not match Alembic head."""


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _alembic_head_revision() -> str:
    config = Config(str(_project_root() / "alembic.ini"))
    config.set_main_option("script_location", str(_project_root() / "app/db/migrations"))
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    if not head:  # pragma: no cover - defensive guard
        raise RuntimeError("Alembic head revision is not defined")
    return head


def _load_current_revision(engine: Engine) -> str | None:
    with engine.connect() as conn:
        inspector = inspect(conn)
        if "alembic_version" not in inspector.get_table_names():
            return None

        rows = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        if not rows:
            return None
        return rows[0]


def _find_schema_shape_mismatch(engine: Engine) -> str | None:
    load_all_models()
    with engine.connect() as conn:
        inspector = inspect(conn)
        existing_tables = set(inspector.get_table_names())
        missing_tables: list[str] = []
        missing_columns: list[str] = []

        for table in Base.metadata.sorted_tables:
            if table.schema not in (None, "public"):
                continue
            if table.name not in existing_tables:
                missing_tables.append(table.name)
                continue

            existing_columns = {column["name"] for column in inspector.get_columns(table.name, schema=table.schema)}
            for column in table.columns:
                if column.name not in existing_columns:
                    missing_columns.append(f"{table.name}.{column.name}")

    details: list[str] = []
    if missing_tables:
        preview = ", ".join(missing_tables[:5])
        suffix = " ..." if len(missing_tables) > 5 else ""
        details.append(f"missing tables: {preview}{suffix}")
    if missing_columns:
        preview = ", ".join(missing_columns[:8])
        suffix = " ..." if len(missing_columns) > 8 else ""
        details.append(f"missing columns: {preview}{suffix}")
    if not details:
        return None
    return "; ".join(details)


def _schema_not_ready_message(current_revision: str | None, head_revision: str, *, shape_mismatch: str | None = None) -> str:
    current = current_revision or "none"
    if shape_mismatch and current_revision == head_revision:
        revision_detail = (
            f"Current revision matches head ({head_revision}), "
            "but required schema objects are missing. "
        )
    else:
        revision_detail = f"Current revision: {current}. Expected revision: {head_revision}. "

    mismatch_detail = f"Detected schema mismatch: {shape_mismatch}. " if shape_mismatch else ""
    return (
        "Database schema is not ready for this app version. "
        f"{revision_detail}"
        f"{mismatch_detail}"
        "In-place upgrades from prior migration chains are not supported. "
        "Reset database state (`scripts/reset_postgres_db.sh`) and run `alembic upgrade head` "
        "against a fresh database."
    )


def assert_schema_ready(engine: Engine) -> None:
    head_revision = _alembic_head_revision()
    current_revision = _load_current_revision(engine)
    if current_revision != head_revision:
        raise SchemaNotReadyError(_schema_not_ready_message(current_revision=current_revision, head_revision=head_revision))

    shape_mismatch = _find_schema_shape_mismatch(engine)
    if shape_mismatch:
        raise SchemaNotReadyError(
            _schema_not_ready_message(
                current_revision=current_revision,
                head_revision=head_revision,
                shape_mismatch=shape_mismatch,
            )
        )


def ensure_schema_ready(engine: Engine, *, force_refresh: bool = False) -> None:
    key = str(engine.url)
    if not force_refresh and key in _SCHEMA_CACHE:
        cached = _SCHEMA_CACHE[key]
        if cached is not None:
            raise cached
        return

    try:
        assert_schema_ready(engine)
    except SchemaNotReadyError as exc:
        _SCHEMA_CACHE[key] = exc
        raise

    _SCHEMA_CACHE[key] = None


def reset_schema_guard_cache() -> None:
    _SCHEMA_CACHE.clear()
    _alembic_head_revision.cache_clear()


def is_schema_mismatch_error(exc: Exception) -> bool:
    if isinstance(exc, SchemaNotReadyError):
        return True
    text_lower = str(exc).lower()
    return any(hint in text_lower for hint in _SCHEMA_ERROR_HINTS)
