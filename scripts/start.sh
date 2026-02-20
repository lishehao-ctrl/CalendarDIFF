#!/usr/bin/env sh
set -eu

attempt=1
until alembic upgrade head; do
  if [ "$attempt" -ge 20 ]; then
    echo "Failed to apply migrations after $attempt attempts"
    exit 1
  fi
  attempt=$((attempt + 1))
  echo "Waiting for database..."
  sleep 2
done

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
