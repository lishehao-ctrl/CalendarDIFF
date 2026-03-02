# V2 Ingestion LLM Runtime (Minimal Chat-Completions-Only)

## Scope

Calendar and Gmail ingestion parsers use a minimal LLM gateway:

1. OpenAI-compatible `chat/completions` API only.
2. JSON object output only (schema-validated).
3. No DB provider registry.
4. No source-level LLM binding.

## Runtime Modules

1. `app/modules/llm_gateway/contracts.py`
2. `app/modules/llm_gateway/registry.py`
3. `app/modules/llm_gateway/transport_openai_compat.py`
4. `app/modules/llm_gateway/adapters/chat_completions.py`
5. `app/modules/llm_gateway/json_contract.py`
6. `app/modules/llm_gateway/gateway.py`
7. `app/modules/ingestion/llm_parsers/contracts.py`
8. `app/modules/ingestion/llm_parsers/schemas.py`
9. `app/modules/ingestion/llm_parsers/calendar_v2.py`
10. `app/modules/ingestion/llm_parsers/gmail_v2.py`

## Configuration

Only three environment variables are required:

1. `INGESTION_LLM_MODEL`
2. `INGESTION_LLM_BASE_URL`
3. `INGESTION_LLM_API_KEY`

Gateway runtime defaults are fixed in code:

1. timeout: `12s`
2. max retries: `1`
3. max input chars: `12000`

## Failure Matrix

1. `parse_llm_timeout`
   - LLM request timed out
   - retryable: yes
2. `parse_llm_empty_output`
   - LLM returned empty text or parser input is empty
   - retryable: no
3. `parse_llm_calendar_schema_invalid`
   - Calendar parser JSON/schema validation failed
   - retryable: no
4. `parse_llm_gmail_schema_invalid`
   - Gmail parser JSON/schema validation failed
   - retryable: no
5. `parse_llm_calendar_upstream_error`
   - Calendar parser upstream/network/http failure
   - retryable: yes
6. `parse_llm_gmail_upstream_error`
   - Gmail parser upstream/network/http failure
   - retryable: yes
7. `parse_llm_upstream_error`
   - Global ingestion env missing/invalid
   - retryable: no

Connector runtime maps parser errors to `ConnectorResultStatus.PARSE_FAILED`.
Job retries and dead-letter transitions remain unchanged.

## Gmail Ingestion Flow

1. Load cursor `history_id`.
2. If first run (no cursor), baseline to current profile `history_id` and return `NO_CHANGE`.
3. Pull incrementals with `list_history(start_history_id)`.
4. Fetch each message metadata/body.
5. Apply optional source filters (`label_id/label_ids/from_contains/subject_keywords`).
6. Parse each message with `gmail_v2` parser through `llm_gateway`.
7. Update cursor to latest history ID only on successful parse path.

## Calendar Ingestion Flow

1. Fetch ICS with conditional headers (`etag`, `last-modified`).
2. Decode source content.
3. Parse with `calendar_v2` parser through `llm_gateway`.
4. Update cursor patch (`etag`, `last_modified`) only on successful parse path.

## Notes

1. Gateway transport uses in-process `httpx`; no shell subprocess `curl`.
2. External status visibility remains `/v2/sync-requests/{request_id}`.
3. Email review pipeline is rules-only and does not use LLM fallback.
