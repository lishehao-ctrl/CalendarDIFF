#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

if [[ ! -x "${ROOT_DIR}/.venv/bin/uvicorn" ]]; then
  echo "Missing .venv uvicorn. Run local setup first."
  exit 1
fi

APP_KEY="${APP_API_KEY:-$(grep '^APP_API_KEY=' .env | cut -d= -f2-)}"
if [[ -z "${APP_KEY}" ]]; then
  echo "APP_API_KEY is required."
  exit 1
fi

DATABASE_URL_VALUE="${DATABASE_URL:-postgresql+psycopg://postgres:postgres@localhost:5432/deadline_diff}"
export DATABASE_URL="${DATABASE_URL_VALUE}"

LOG_DIR="/tmp/deadline_diff_smoke"
FEED_DIR="$(mktemp -d /tmp/deadline_diff_feed.XXXXXX)"
SMTP_LOG="${LOG_DIR}/smtp.log"
API_A_LOG="${LOG_DIR}/api_a.log"
API_B_LOG="${LOG_DIR}/api_b.log"
HTTP_LOG="${LOG_DIR}/http.log"

mkdir -p "${LOG_DIR}"

SMTP_PID=""
HTTP_PID=""
API_A_PID=""
API_B_PID=""

cleanup() {
  [[ -n "${API_A_PID}" ]] && kill "${API_A_PID}" >/dev/null 2>&1 || true
  [[ -n "${API_B_PID}" ]] && kill "${API_B_PID}" >/dev/null 2>&1 || true
  [[ -n "${SMTP_PID}" ]] && kill "${SMTP_PID}" >/dev/null 2>&1 || true
  [[ -n "${HTTP_PID}" ]] && kill "${HTTP_PID}" >/dev/null 2>&1 || true
  rm -rf "${FEED_DIR}"
}
trap cleanup EXIT

echo "[1/8] Starting PostgreSQL..."
docker compose up -d postgres

echo "[2/8] Resetting PostgreSQL database..."
scripts/reset_postgres_db.sh

echo "[3/8] Preparing ICS feed and local HTTP server..."
cat > "${FEED_DIR}/feed.ics" <<'EOF'
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Deadline Diff Smoke//EN
BEGIN:VEVENT
UID:smoke-event-1
DTSTART:20260224T090000Z
DTEND:20260224T100000Z
SUMMARY:CSE 151A Homework 1
DESCRIPTION:submit to portal
END:VEVENT
END:VCALENDAR
EOF
"${PYTHON_BIN}" -m http.server 8765 --directory "${FEED_DIR}" >"${HTTP_LOG}" 2>&1 &
HTTP_PID="$!"

echo "[4/8] Starting SMTP debug sink..."
"${PYTHON_BIN}" -m smtpd -n -c DebuggingServer 127.0.0.1:1025 >"${SMTP_LOG}" 2>&1 &
SMTP_PID="$!"

echo "[5/8] Starting API instance A (8000) and B (8001)..."
APP_API_KEY="${APP_KEY}" \
DATABASE_URL="${DATABASE_URL_VALUE}" \
DEFAULT_NOTIFY_EMAIL="notify@example.com" \
SMTP_HOST="127.0.0.1" \
SMTP_PORT="1025" \
SCHEDULER_TICK_SECONDS="5" \
DISABLE_SCHEDULER="false" \
SCHEMA_GUARD_ENABLED="true" \
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 >"${API_A_LOG}" 2>&1 &
API_A_PID="$!"

APP_API_KEY="${APP_KEY}" \
DATABASE_URL="${DATABASE_URL_VALUE}" \
DEFAULT_NOTIFY_EMAIL="notify@example.com" \
SMTP_HOST="127.0.0.1" \
SMTP_PORT="1025" \
SCHEDULER_TICK_SECONDS="5" \
DISABLE_SCHEDULER="false" \
SCHEMA_GUARD_ENABLED="true" \
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001 >"${API_B_LOG}" 2>&1 &
API_B_PID="$!"

echo "[6/8] Waiting for both APIs to become healthy..."
for _ in {1..30}; do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 && curl -fsS http://127.0.0.1:8001/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
  echo "API instance A failed to become healthy."
  exit 1
fi
if ! curl -fsS http://127.0.0.1:8001/health >/dev/null 2>&1; then
  echo "API instance B failed to become healthy."
  exit 1
fi

echo "[7/8] Creating source and waiting baseline tick..."
SOURCE_JSON="$(
  curl -fsS \
    -H "X-API-Key: ${APP_KEY}" \
    -H "Content-Type: application/json" \
    -d '{"name":"Smoke Multi Instance","url":"http://127.0.0.1:8765/feed.ics","interval_minutes":1,"notify_email":"notify@example.com"}' \
    http://127.0.0.1:8000/v1/sources/ics
)"
SOURCE_ID="$(echo "${SOURCE_JSON}" | "${PYTHON_BIN}" -c 'import json,sys; print(json.load(sys.stdin)["id"])')"

sleep 8

echo "[8/8] Mutating feed, waiting scheduler diff, and asserting dedup..."
cat > "${FEED_DIR}/feed.ics" <<'EOF'
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Deadline Diff Smoke//EN
BEGIN:VEVENT
UID:smoke-event-1
DTSTART:20260224T100000Z
DTEND:20260224T110000Z
SUMMARY:CSE 151A Homework 1
DESCRIPTION:submit to portal
END:VEVENT
END:VCALENDAR
EOF

HAS_CHANGES="0"
# interval_minutes is 1, so allow up to 2 minutes to avoid boundary flakes
# between baseline completion and the first due scheduler cycle.
for _ in {1..60}; do
  CHANGES_JSON="$(curl -fsS -H "X-API-Key: ${APP_KEY}" "http://127.0.0.1:8000/v1/changes?source_id=${SOURCE_ID}&limit=20")"
  CHANGE_COUNT="$(echo "${CHANGES_JSON}" | "${PYTHON_BIN}" -c 'import json,sys; print(len(json.load(sys.stdin)))')"
  if [[ "${CHANGE_COUNT}" -gt 0 ]]; then
    HAS_CHANGES="1"
    break
  fi
  sleep 2
done

if [[ "${HAS_CHANGES}" != "1" ]]; then
  echo "No changes detected from scheduler."
  exit 1
fi

"${PYTHON_BIN}" <<'PY'
import os
from sqlalchemy import create_engine, text

engine = create_engine(os.environ["DATABASE_URL"], future=True)
with engine.connect() as conn:
    duplicates = conn.execute(
        text(
            """
            SELECT change_id, COUNT(*) AS cnt
            FROM notifications
            GROUP BY change_id
            HAVING COUNT(*) > 1
            """
        )
    ).all()
    total = conn.execute(text("SELECT COUNT(*) FROM notifications")).scalar_one()

if duplicates:
    raise SystemExit(f"Duplicate notifications detected: {duplicates}")
if total == 0:
    raise SystemExit("No notification rows were generated.")
print("notification_dedup_ok total_notifications=", total)
PY

echo "Smoke success: scheduler ran on two instances without duplicate notifications."
echo "Logs:"
echo "  ${API_A_LOG}"
echo "  ${API_B_LOG}"
echo "  ${SMTP_LOG}"
