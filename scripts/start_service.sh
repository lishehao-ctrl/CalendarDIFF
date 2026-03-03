#!/usr/bin/env sh
set -eu

SERVICE_NAME="${SERVICE_NAME:-}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
RUN_MIGRATIONS="${RUN_MIGRATIONS:-false}"

if [ -z "${SERVICE_NAME}" ]; then
  echo "SERVICE_NAME is required (input|ingest|review|notification|llm)" >&2
  exit 1
fi

case "${SERVICE_NAME}" in
  input)
    APP_MODULE="services.input_api.main:app"
    ;;
  ingest)
    APP_MODULE="services.ingest_api.main:app"
    ;;
  review)
    APP_MODULE="services.review_api.main:app"
    ;;
  notification)
    APP_MODULE="services.notification_api.main:app"
    ;;
  llm)
    APP_MODULE="services.llm_api.main:app"
    ;;
  *)
    echo "invalid SERVICE_NAME='${SERVICE_NAME}' (expected input|ingest|review|notification|llm)" >&2
    exit 1
    ;;
esac

attempt=1
max_attempts="${DB_WAIT_MAX_ATTEMPTS:-30}"
sleep_seconds="${DB_WAIT_SLEEP_SECONDS:-2}"

until python -c "from sqlalchemy import create_engine, text; import os; engine = create_engine(os.environ['DATABASE_URL'], future=True); conn = engine.connect(); conn.execute(text('SELECT 1')); conn.close(); engine.dispose()" >/dev/null 2>&1; do
  if [ "${attempt}" -ge "${max_attempts}" ]; then
    echo "Database is not ready after ${attempt} attempts" >&2
    exit 1
  fi
  echo "Waiting for PostgreSQL (${attempt}/${max_attempts})..."
  attempt=$((attempt + 1))
  sleep "${sleep_seconds}"
done

case "$(echo "${RUN_MIGRATIONS}" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes|on)
    alembic upgrade head
    ;;
  *)
    ;;
esac

exec uvicorn "${APP_MODULE}" --host "${HOST}" --port "${PORT}"
