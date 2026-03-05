from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection
from sqlalchemy.engine.url import make_url

from app.core.config import get_settings
from app.db.base import Base
from app.db.model_registry import load_all_models

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

load_all_models()

target_metadata = Base.metadata


def _assert_postgres_url(url: str) -> None:
    parsed = make_url(url)
    if parsed.drivername.startswith("postgresql"):
        return
    raise RuntimeError(
        "PostgreSQL-only migration chain: DATABASE_URL must use a PostgreSQL driver. "
        f"Got driver '{parsed.drivername}'."
    )


def _assert_postgres_connection(connection: Connection) -> None:
    if connection.dialect.name.startswith("postgresql"):
        return
    raise RuntimeError(
        "PostgreSQL-only migration chain: connected dialect must be PostgreSQL. "
        f"Got '{connection.dialect.name}'."
    )


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    _assert_postgres_url(url)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        _assert_postgres_connection(connection)
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
