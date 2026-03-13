# Responses API Migration Spec

## 1. Purpose

This document defines the next LLM-gateway architecture change for CalendarDIFF:

- replace the repo's current `chat/completions` runtime path with a `responses.create(...)` architecture
- keep the rest of the ingestion/review pipeline stable
- make the migration easy for another coding agent to execute without re-deciding the architecture

This spec is intentionally narrow. It is about the LLM gateway and parser integration path, not the whole semantic data model.

If older code, tests, or docs conflict with this file, follow this file.

## 2. External Reference

Primary official references used for this spec:

- OpenAI Responses API overview and request model:
  [Responses API](https://platform.openai.com/docs/api-reference/responses)
- OpenAI migration guidance:
  [Chat Completions to Responses](https://platform.openai.com/docs/guides/responses-vs-chat-completions)
- OpenAI structured output guidance for schema-constrained JSON:
  [Structured outputs](https://platform.openai.com/docs/guides/structured-outputs)

Provider-specific compatibility note supplied by the user:

- the target deployment may use an OpenAI-compatible provider that exposes `client.responses.create(...)`
- the provider may require `base_url` and may support provider-specific `extra_body`, for example:
  `{"enable_thinking": true}`

We must support this provider shape without hardcoding the provider name.

## 3. Current Repo Baseline

The current repo is still built around `chat/completions`:

- [`app/modules/llm_gateway/contracts.py`](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/llm_gateway/contracts.py)
  only allows `LlmApiModeLiteral = Literal["chat_completions"]`
- [`app/modules/llm_gateway/gateway.py`](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/llm_gateway/gateway.py)
  builds Chat Completions payloads and extracts `choices[0].message.content`
- [`app/modules/llm_gateway/adapters/chat_completions.py`](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/llm_gateway/adapters/chat_completions.py)
  is the current request/response codec
- [`app/modules/llm_gateway/transport_openai_compat.py`](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/llm_gateway/transport_openai_compat.py)
  manually posts to `/v1/chat/completions`
- parser callers in
  [`app/modules/ingestion/llm_parsers/calendar_parser.py`](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/ingestion/llm_parsers/calendar_parser.py)
  and
  [`app/modules/ingestion/llm_parsers/gmail_parser.py`](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/ingestion/llm_parsers/gmail_parser.py)
  rely on `invoke_llm_json(...)` returning schema-valid JSON objects

The repo already depends on the official Python SDK:

- [`pyproject.toml`](/Users/lishehao/Desktop/Project/CalendarDIFF/pyproject.toml)
- [`requirements.txt`](/Users/lishehao/Desktop/Project/CalendarDIFF/requirements.txt)

That means we should use the SDK instead of keeping a custom raw-HTTP Chat Completions transport.

## 4. Target Architecture

### 4.1 Single API mode

The ingestion LLM runtime should become Responses-only.

Required result:

- `LlmApiModeLiteral` becomes `Literal["responses"]`
- the gateway no longer builds or parses Chat Completions payloads
- the main runtime path uses the OpenAI SDK sync client and `client.responses.create(...)`

We are not building a multi-mode gateway in this pass.

### 4.2 SDK-driven client path

The new runtime should use the official SDK:

```python
from openai import OpenAI

client = OpenAI(
    api_key=...,
    base_url=...,
    timeout=...,
    max_retries=0,
)

response = client.responses.create(...)
```

Important rule:

- set SDK `max_retries=0`
- keep retry policy in our repo-level gateway logic
- do not stack SDK retries on top of existing gateway format-retry behavior

### 4.3 Structured JSON via Responses API

The repo currently depends on schema-valid JSON outputs.
That behavior must stay intact.

The Responses request must use structured output with JSON schema, not plain-text prompting only.

Required request shape:

- `model = profile.model`
- `instructions = invoke_request.system_prompt`
- `input = [...]` using a single user message that contains the existing task metadata plus serialized `INPUT_JSON`
- `text.format = { "type": "json_schema", "name": ..., "schema": ..., "strict": true }`
- `store = false`
- `temperature = invoke_request.temperature`
- `extra_body = profile.extra_body` when present

Do not keep dumping the whole JSON schema into the system prompt if the API is already carrying the schema structurally.

## 5. Exact Repo Changes Required

## 5.1 Contracts and profile

Update:

- [`app/modules/llm_gateway/contracts.py`](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/llm_gateway/contracts.py)
- [`app/modules/llm_gateway/registry.py`](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/llm_gateway/registry.py)
- [`app/core/config.py`](/Users/lishehao/Desktop/Project/CalendarDIFF/app/core/config.py)

Required changes:

1. `LlmApiModeLiteral` must become:
   - `Literal["responses"]`
2. `ResolvedLlmProfile.api_mode` must be `responses`
3. add a parsed extra-body field to the runtime profile:
   - recommended name: `extra_body: dict[str, object]`
4. add a new settings/env input:
   - recommended env var: `INGESTION_LLM_EXTRA_BODY_JSON`
5. parse `INGESTION_LLM_EXTRA_BODY_JSON` as a JSON object
6. invalid extra-body JSON must fail fast as config error

The existing env names should remain:

- `INGESTION_LLM_BASE_URL`
- `INGESTION_LLM_API_KEY`
- `INGESTION_LLM_MODEL`
- `APP_LLM_OPENAI_MODEL` fallback

The user said they will fill the env values themselves. Do not hardcode provider values.

## 5.2 Base URL normalization

Because users may supply different styles of env values, normalize base URL before creating the SDK client.

The code should accept all of these and normalize them to the SDK root form:

- `https://host/.../v1`
- `https://host/.../v1/`
- `https://host/.../v1/responses`
- `https://host/.../v1/chat/completions`

Target normalized form:

- the SDK should receive a base URL ending at the provider's API root, typically `/v1`
- never pass `/responses` or `/chat/completions` as the final SDK base URL

Recommended helper:

- `normalize_openai_sdk_base_url(...)`

## 5.3 Replace adapter/transport implementation

Remove the Chat Completions-specific adapter path and replace it with a Responses codec.

Current files to replace/refactor:

- [`app/modules/llm_gateway/adapters/chat_completions.py`](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/llm_gateway/adapters/chat_completions.py)
- [`app/modules/llm_gateway/adapters/__init__.py`](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/llm_gateway/adapters/__init__.py)
- [`app/modules/llm_gateway/transport_openai_compat.py`](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/llm_gateway/transport_openai_compat.py)
- [`app/modules/llm_gateway/gateway.py`](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/llm_gateway/gateway.py)

Recommended target layout:

- `app/modules/llm_gateway/adapters/responses.py`
- `app/modules/llm_gateway/responses_client.py` or `transport_responses.py`

The new adapter should provide two responsibilities:

1. build a Responses request payload
2. extract a JSON object from a Responses SDK response object or response dict

### 5.3.1 Required request mapping

The new request builder should keep current semantic behavior:

- preserve `task_name`, `request_id`, `source_id`, and `source_provider` in the user input text
- preserve structured schema validation
- preserve temperature

Recommended user input shape:

```text
TASK: ...
REQUEST_ID: ...
SOURCE_ID: ...
SOURCE_PROVIDER: ...
INPUT_JSON:
{...truncated json...}
```

Recommended Responses call shape:

```python
client.responses.create(
    model=profile.model,
    instructions=invoke_request.system_prompt.strip(),
    input=[
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": user_input_text,
                }
            ],
        }
    ],
    text={
        "format": {
            "type": "json_schema",
            "name": normalized_schema_name,
            "schema": invoke_request.output_schema_json,
            "strict": True,
        }
    },
    temperature=invoke_request.temperature,
    store=False,
    extra_body=profile.extra_body or None,
)
```

### 5.3.2 Required response extraction

The extraction path must:

1. prefer `response.output_text` when available
2. otherwise traverse `response.output[*]` and collect assistant message text blocks
3. parse the resulting text using existing JSON text parsing helpers
4. keep `raw_usage`
5. return a stable upstream identifier

Recommended mapping:

- `upstream_request_id = response.id`
- `raw_usage = response.usage.model_dump()` when available, else `{}`

If the provider returns reasoning items before the final answer, ignore them unless needed for fallback text extraction.
The runtime contract only needs the final JSON object.

### 5.3.3 Error policy

Keep current gateway behavior:

- transport/network timeout -> `parse_llm_timeout`
- upstream HTTP error -> `parse_llm_upstream_error`
- empty text -> `parse_llm_empty_output`
- invalid JSON or schema mismatch -> `parse_llm_schema_invalid`

Do not silently fall back to prose parsing without JSON object validation.

## 5.4 Gateway public surface must stay stable

These public contracts should stay stable for the parser callers:

- `invoke_llm_json(db, invoke_request=...)`
- `LlmInvokeRequest`
- `LlmInvokeResult`
- repo-level retry behavior in `gateway.py`

This pass should be an internal implementation swap, not a parser API rewrite.

## 5.5 Parser/runtime expectations

The parser modules should keep their current behavior:

- [`app/modules/ingestion/llm_parsers/calendar_parser.py`](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/ingestion/llm_parsers/calendar_parser.py)
- [`app/modules/ingestion/llm_parsers/gmail_parser.py`](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/ingestion/llm_parsers/gmail_parser.py)

Required result:

- parser code still calls `invoke_llm_json(...)`
- parser output shape does not change
- schema retry behavior does not change
- only the LLM transport/request layer changes under the hood

## 5.6 Docs and examples

If code is changed, also update the repo docs that describe the LLM path.

Minimum docs to sync:

- [`docs/architecture.md`](/Users/lishehao/Desktop/Project/CalendarDIFF/docs/architecture.md)
- [`docs/event_contracts.md`](/Users/lishehao/Desktop/Project/CalendarDIFF/docs/event_contracts.md)
- optionally [`README.md`](/Users/lishehao/Desktop/Project/CalendarDIFF/README.md) if it mentions the LLM endpoint shape

The docs should say:

- ingestion LLM runtime uses the Responses API
- schema-constrained output uses `text.format` JSON schema
- provider-specific flags can be passed through `INGESTION_LLM_EXTRA_BODY_JSON`

## 6. Explicit Non-Goals

Do not do these in this pass:

- do not redesign the semantic event model
- do not change ingestion record payload shapes
- do not add tool-calling, streaming, or `previous_response_id`
- do not implement a multi-provider abstraction beyond what already exists
- do not scope-creep into unrelated architecture cleanup unless directly required for touched files

## 7. Known Repo Caveat

There are pre-existing syntax/merge-conflict issues in unrelated `review_changes/canonical_edit_*` files in the current repo state.

This Responses API migration is not responsible for solving that unrelated area unless the implementation directly touches it.

That means:

- targeted validation for the LLM gateway/parser path is required
- full-repo compile or full test suite may still fail for unrelated reasons
- if unrelated failures occur, the agent must report them clearly instead of hiding them

## 8. Validation Requirements

At minimum, run these after implementation:

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_llm_gateway_format_retry.py \
  tests/test_ingestion_parser_format_retry.py \
  tests/test_llm_registry_fallback.py
```

Also run targeted import/compile checks for touched modules:

```bash
python -m py_compile \
  app/modules/llm_gateway/contracts.py \
  app/modules/llm_gateway/registry.py \
  app/modules/llm_gateway/gateway.py \
  app/modules/ingestion/llm_parsers/calendar_parser.py \
  app/modules/ingestion/llm_parsers/gmail_parser.py
```

If docs are changed, no extra doc-only validation is required.

If the agent also changes parser/runtime files more broadly, they should additionally run:

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_llm_worker_calendar_delta.py \
  tests/test_llm_parse_pipeline_gmail_branch.py
```

## 9. Done Definition

This migration is complete only if all of the following are true:

1. no active runtime path posts to `/chat/completions`
2. `LlmApiModeLiteral` is `responses`
3. the main runtime path uses `client.responses.create(...)`
4. structured JSON output uses Responses `text.format` JSON schema
5. provider-specific `extra_body` can be configured via env JSON
6. gateway/parser tests for this path pass
7. docs no longer describe Chat Completions as the active ingestion LLM path

