#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

TARGET_PATH="${1:-dev.db}"

echo "Resetting SQLite database: ${TARGET_PATH}"
rm -f "${TARGET_PATH}" "${TARGET_PATH}-wal" "${TARGET_PATH}-shm"

"${PYTHON_BIN}" -m alembic upgrade head
"${PYTHON_BIN}" -m alembic current
