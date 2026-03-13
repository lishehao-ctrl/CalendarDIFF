You are working in the CalendarDIFF repo.

Read this file first:

- /Users/lishehao/Desktop/Project/CalendarDIFF/RESPONSES_API_MIGRATION_SPEC.md

Treat it as the source of truth for this task.

Your job is to migrate the repo's ingestion LLM gateway from the old Chat Completions path to a Responses API architecture.

Important context:

- the user will fill the env values such as base URL, API key, and model
- the provider may be OpenAI-compatible rather than OpenAI first-party
- the provider may require `extra_body`, for example `{"enable_thinking": true}`
- the repo already depends on the official `openai` Python SDK

What you must do:

1. replace the current `chat/completions` runtime path with a `client.responses.create(...)` path
2. keep the parser-facing gateway contract stable
3. use structured JSON output through Responses `text.format` JSON schema
4. support env-configured `extra_body` passthrough
5. normalize base URLs so users can provide `/v1`, `/v1/responses`, or `/v1/chat/completions`
6. update the targeted tests to the new response shape
7. update docs if they still describe Chat Completions as the active ingestion runtime

Execution rules:

- do not reintroduce Chat Completions compatibility layers
- do not redesign the semantic event pipeline
- do not change parser output contracts unless strictly necessary
- do not hardcode provider-specific values
- do not use full-schema prompt dumping as the primary structured-output mechanism when the Responses API can carry the schema structurally
- do not hide unrelated repo failures; if unrelated files fail, say so clearly

Recommended implementation order:

1. contracts + settings + profile parsing
2. SDK client/base-url normalization/extra-body parsing
3. Responses request builder and response extractor
4. gateway wiring
5. targeted tests
6. docs sync

Validation you should run:

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_llm_gateway_format_retry.py \
  tests/test_ingestion_parser_format_retry.py \
  tests/test_llm_registry_fallback.py
```

```bash
python -m py_compile \
  app/modules/llm_gateway/contracts.py \
  app/modules/llm_gateway/registry.py \
  app/modules/llm_gateway/gateway.py \
  app/modules/ingestion/llm_parsers/calendar_parser.py \
  app/modules/ingestion/llm_parsers/gmail_parser.py
```

If you touch parser/runtime more broadly, also run:

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_llm_worker_calendar_delta.py \
  tests/test_llm_parse_pipeline_gmail_branch.py
```

Known caveat:

- there are unrelated merge-conflict/syntax problems in `app/modules/review_changes/canonical_edit_*`
- do not scope-creep into that area unless your changes directly require it
- if full-repo validation fails because of those unrelated files, report that explicitly

When you finish, respond in Chinese and use this structure:

1. 结果
- 用 2 到 4 句总结 Responses API 迁移达成了什么

2. 主要改动
- 按模块归纳
- 明确说明哪些旧 `chat/completions` 架构被删掉
- 明确说明新的 Responses API 路径和 `extra_body` 支持怎么落地

3. 验证
- 列出你实际运行过的命令
- 明说哪些没跑

4. 风险 / 剩余问题
- 只写真实剩余问题
- 如果失败来自 repo 里与本任务无关的旧问题，要明确标出来

Quality bar:

- prefer a decisive architecture swap over a half-compatible bridge
- keep diffs centered on the LLM gateway and parser path
- preserve current parser semantics
- make the new path easier for future providers that expose `responses.create(...)`

Do not stop at analysis. Implement the migration, validate it, then report.
