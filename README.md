# Deadline Diff Watcher (MVP)

FastAPI + Postgres backend for monitoring ICS feeds and sending email alerts when deadline-like events change.

## Features

- Register ICS sources through API.
- Periodic background sync with APScheduler.
- Postgres advisory lock to prevent duplicate scheduler runs.
- ICS parsing + canonical event normalization.
- Diff engine with debounced removals (3 consecutive snapshots).
- Audit log (`changes`) and email notifications.
- API key authentication for protected endpoints.

## Quick Start (Docker)

```bash
docker compose up --build
```

API will be available at `http://localhost:8000`.

## Local Development

1. Create virtual environment and install dependencies:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

2. Copy environment file and adjust values:

```bash
cp .env.example .env
```

3. Run app:

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

4. Run tests:

```bash
python -m pytest -q
```
## Structured Output From ICS

You can generate structured JSON from a local ICS file in two ways.

### 1) Local CLI (recommended for quick inspection)

```bash
python scripts/ics_to_structured.py \
  --input tests/fixtures/private/user_calendar.ics \
  --output reports/structured_output.json \
  --pretty
```

Or print to stdout:

```bash
python scripts/ics_to_structured.py --input /path/to/file.ics --pretty
```

Output schema:
- `source_file`
- `generated_at_utc`
- `course_count`
- `total_deadlines`
- `courses[]`
- `courses[].course_label`
- `courses[].deadline_count`
- `courses[].deadlines[]`
- `courses[].deadlines[].uid`
- `courses[].deadlines[].title`
- `courses[].deadlines[].ddl_type`
- `courses[].deadlines[].start_at_utc`
- `courses[].deadlines[].end_at_utc`

### 2) API

Create a source, then read the structured output from `/v1/sources/{id}/deadlines`.

```bash
curl -X POST http://localhost:8000/v1/sources/ics \
  -H "X-API-Key: ${APP_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"name":"My Calendar","url":"https://example.com/feed.ics"}'

curl http://localhost:8000/v1/sources/1/deadlines \
  -H "X-API-Key: ${APP_API_KEY}"
```

Course inference behavior:
- Section tags are highest priority: `[CGS124_WI26_A00] -> CGS 124`.
- Summary fallback is enabled with blacklist protection.
- Description text is only used for section-tag extraction, not free-form course matching.
- If nothing matches, `course_label` is `Unknown`.

## API Endpoints

- `GET /health`
- `POST /v1/sources/ics`
- `GET /v1/sources`
- `POST /v1/sources/{id}/sync`
- `GET /v1/sources/{id}/deadlines`
- `GET /v1/changes`

Protected endpoints require `X-API-Key` matching `APP_API_KEY`.

## Notes

- ICS source URLs are encrypted at rest via Fernet (`APP_SECRET_KEY`).
- URLs are not returned in API responses.
- Private ICS files should stay under `tests/fixtures/private/` (ignored by git).
- Generated test reports and structured outputs under `reports/` are ignored by git.
