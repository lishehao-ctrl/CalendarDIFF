# Semantic Cleanup Agent Prompt

把下面这段提示词直接给另一个 agent 使用即可。

```text
You are working in the CalendarDIFF repo.

Before doing anything else, read this file first:
/Users/lishehao/Desktop/Project/CalendarDIFF/ENTITY_FIRST_SEMANTIC_SPEC.md

Treat that spec as the single source of truth for the cleanup. If older tests, docs, names, helper APIs, or compatibility layers conflict with it, follow the spec, not the legacy shape.

Your job is to continue the repo-wide cleanup so the codebase speaks one vocabulary only:
- stable internal identity = entity_uid
- canonical approved state = event_entities
- review/audit queue = changes with before_semantic_json / after_semantic_json
- user-facing display = course + family + ordinal
- source data = input_sources + source_event_observations for evidence/provenance only

What you should do:
1. Read the spec.
2. Scan the repo for remaining legacy canonical expressions, aliases, DTO fields, tests, docs, and OpenAPI snapshot drift.
3. Remove or rewrite them so they match the spec.
4. Prefer deleting dead compatibility code over keeping it.
5. Keep the main route families stable: /sources, /sync-requests, /review/*, /users/*.
6. If you touch frontend DTO consumers, update them in the same pass.
7. Run the validation commands from the spec that are relevant to your changes.
8. Report exactly what you changed, what you deleted, and what still remains.

Important constraints:
- Do not preserve legacy Input/Event/Snapshot semantics just because old code or tests still mention them.
- Do not introduce new dual-write or backfill layers.
- Do not treat course + family + ordinal as the stable identity.
- Do not use file-backed review evidence in the main flow.
- Do not keep misleading aliases like before_json / after_json / proposal_entity_uid.
- Respect legitimate surviving terms listed in the spec, such as input_sources and input-service.

Cleanup target areas, in order:
1. runtime code under app/ and services/
2. backend tests
3. frontend DTO/types and review consumers
4. OpenAPI snapshots
5. docs
6. scripts and repo guards

When you finish, write your response in Chinese and use this structure:

1. 结果
- 用 2 到 4 句总结这次清理达成了什么。

2. 主要改动
- 按模块归纳，不要写成琐碎的逐文件流水账。
- 明确说明哪些旧表达被删掉，哪些新表达成为唯一口径。

3. 验证
- 列出你实际运行过的命令。
- 如果有没跑的检查，直接说明。

4. 剩余风险
- 只写真实还没清掉的点。
- 如果没有，就明确说目前没有发现新的旧 canonical 冗余表达。

Quality bar:
- Prefer minimal but decisive diffs.
- Keep naming aligned with the spec.
- If a test only validates removed legacy behavior, delete or rewrite it.
- If a doc describes removed tables as active runtime architecture, fix it.
- If an OpenAPI snapshot is stale, regenerate it.

Do not stop after analysis. Make the edits, verify them, then report the outcome.
```
