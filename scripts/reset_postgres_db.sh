#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

TARGET_DB_NAME="${1:-deadline_diff}"
BASE_DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://postgres:postgres@localhost:5432/${TARGET_DB_NAME}}"

export TARGET_DB_NAME
export BASE_DATABASE_URL

DATABASE_URL="$(
"${PYTHON_BIN}" <<'PY'
import os
from sqlalchemy.engine.url import make_url

url = make_url(os.environ["BASE_DATABASE_URL"])
print(url.set(database=os.environ["TARGET_DB_NAME"]).render_as_string(hide_password=False))
PY
)"
ADMIN_DATABASE_URL="$(
"${PYTHON_BIN}" <<'PY'
import os
from sqlalchemy.engine.url import make_url

url = make_url(os.environ["BASE_DATABASE_URL"])
print(url.set(database="postgres").render_as_string(hide_password=False))
PY
)"

export DATABASE_URL
export ADMIN_DATABASE_URL

echo "Resetting PostgreSQL database: ${TARGET_DB_NAME}"

"${PYTHON_BIN}" <<'PY'
import os
import re

from sqlalchemy import create_engine, text

db_name = os.environ["TARGET_DB_NAME"]
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", db_name):
    raise SystemExit(f"Invalid database name: {db_name!r}")

engine = create_engine(os.environ["ADMIN_DATABASE_URL"], future=True, isolation_level="AUTOCOMMIT")
with engine.connect() as conn:
    conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
    conn.execute(text(f'CREATE DATABASE "{db_name}"'))
engine.dispose()
PY

"${PYTHON_BIN}" -m alembic upgrade head
"${PYTHON_BIN}" -m alembic current
