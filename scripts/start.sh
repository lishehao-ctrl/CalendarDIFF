#!/usr/bin/env sh
set -eu

attempt=1
max_attempts="${DB_WAIT_MAX_ATTEMPTS:-30}"
sleep_seconds="${DB_WAIT_SLEEP_SECONDS:-2}"

until python -c "from sqlalchemy import create_engine, text; import os; engine = create_engine(os.environ['DATABASE_URL'], future=True); conn = engine.connect(); conn.execute(text('SELECT 1')); conn.close(); engine.dispose()" >/dev/null 2>&1; do
  if [ "$attempt" -ge "$max_attempts" ]; then
    echo "Database is not ready after ${attempt} attempts"
    exit 1
  fi
  echo "Waiting for PostgreSQL (${attempt}/${max_attempts})..."
  attempt=$((attempt + 1))
  sleep "$sleep_seconds"
done

alembic upgrade head

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
