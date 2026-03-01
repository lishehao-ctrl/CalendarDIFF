# V2 LLM Gateway + Parsers (Calendar + Gmail)

## Scope

V2 ingestion runtime executes live LLM parsing for both calendar and Gmail connectors
through a unified OpenAI-compatible gateway.
The gateway supports both `chat/completions` and `responses` APIs.

## Runtime Modules

1. `app/modules/llm_gateway/contracts.py`
2. `app/modules/llm_gateway/registry.py`
3. `app/modules/llm_gateway/transport_openai_compat.py`
4. `app/modules/llm_gateway/adapters/chat_completions.py`
5. `app/modules/llm_gateway/adapters/responses.py`
6. `app/modules/llm_gateway/json_contract.py`
7. `app/modules/llm_gateway/gateway.py`
8. `app/modules/ingestion/llm_parsers/contracts.py`
9. `app/modules/ingestion/llm_parsers/schemas.py`
10. `app/modules/ingestion/llm_parsers/calendar_v2.py`
11. `app/modules/ingestion/llm_parsers/gmail_v2.py`

## Configuration

1. Provider metadata is configured in DB (`llm_providers`) via internal APIs.
2. Source-level provider binding is configured in DB (`source_llm_bindings`).
3. API keys are resolved from environment variables via `api_key_ref` (no key plaintext in DB).
4. Runtime hardening flags:
   - `LLM_ALLOW_HTTP_BASE_URL`
   - `LLM_REGISTRY_CACHE_TTL_SECONDS`

## Contract

### Error

`LlmParseError(code, message, retryable, provider, parser_version="v2")`

### Context

`ParserContext(source_id, provider, source_kind, request_id | optional)`

### Output

`ParserOutput(records, parser_name, parser_version, model_hint)`

`records[]` must use `record_type + payload` objects.
Connector runtime appends parser metadata under `payload._parser`.

## Failure Matrix

1. `parse_llm_timeout`
   - LLM request timed out
   - retryable: yes
2. `parse_llm_empty_output`
   - LLM returned empty content or source input was empty after preprocessing
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
7. `parse_llm_provider_not_found`
   - no enabled/default provider or missing binding provider
   - retryable: no
8. `parse_llm_provider_disabled`
   - source binding points to disabled provider
   - retryable: no
9. `parse_llm_provider_key_missing`
   - provider `api_key_ref` env variable not present
   - retryable: no
10. `parse_llm_mode_unsupported`
   - unsupported `api_mode`
   - retryable: no

Connector runtime maps parser errors to `ConnectorResultStatus.PARSE_FAILED`.
Job retries and dead-letter transitions remain unchanged.
Connector logs include `request_id/source_id/provider/error_code` for parse failures.

## Internal Management APIs

1. `POST /internal/v2/llm-providers`
2. `GET /internal/v2/llm-providers`
3. `PATCH /internal/v2/llm-providers/{provider_id}`
4. `POST /internal/v2/llm-providers/{provider_id}/validations`
5. `POST /internal/v2/llm-default-provider`
6. `PATCH /internal/v2/input-sources/{source_id}/llm-binding`

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
3. Email review pipeline (`email_rules` + `email_llm_fallback`) is intentionally untouched.
