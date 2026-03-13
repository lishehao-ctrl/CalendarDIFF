# Future Architecture Optimization Agent Prompt

把下面这段提示词直接给另一个 agent 使用即可。

```text
You are working in the CalendarDIFF repo.

Read these two files first, in order:
1. /Users/lishehao/Desktop/Project/CalendarDIFF/ENTITY_FIRST_SEMANTIC_SPEC.md
2. /Users/lishehao/Desktop/Project/CalendarDIFF/FUTURE_ARCH_OPTIMIZATION_SPEC.md

Treat them as the source of truth for this task.

Your job is not to keep cleaning wording only. Your job is to implement the next architecture optimization wave on top of the already-clean entity-first semantic model.

Current baseline assumptions:
- approved canonical state already lives only in event_entities
- changes already represent semantic proposals/audit
- source payload naming already uses source_facts
- change_source_refs already exists

What you need to optimize now:
1. flatten migrations into a true clean baseline for the current schema
2. introduce strong typed schemas for semantic/source/evidence/source-ref payloads
3. reduce review read-path complexity by introducing a projection or equivalent batched read model
4. define and implement explicit family label authority rules
5. clean up any remaining runtime naming that still implies “canonical event” instead of approved entity state

Execution rules:
- Do not reintroduce compatibility backfills or dual-write logic.
- Do not preserve transitional migration logic just because it already exists.
- Do not keep key runtime payloads as untyped loose dicts if they belong to the semantic/source/evidence main flow.
- Do not leave family_id vs family_name behavior ambiguous.
- Prefer one decisive cleanup pass per area over partial shims.

Recommended order:
1. migration baseline
2. typed schema extraction
3. review projection/read model
4. family label authority implementation
5. naming cleanup

Minimum expected deliverables:
- a clean migration story that matches the actual current schema
- typed models for source_facts, semantic payloads, frozen evidence, and change source refs
- a simpler review list/read path with less row-by-row lookup work
- a documented and implemented rule for how family labels behave in event_entities, changes, and user-facing display

Validation:
- Run the relevant commands from FUTURE_ARCH_OPTIMIZATION_SPEC.md.
- If you skip any command, say so explicitly.

When you finish, respond in Chinese and use this structure:

1. 结果
- 用 2 到 4 句总结这轮架构优化真正改善了什么。

2. 主要改动
- 按优化主题分组，不要写成逐文件流水账。
- 明确说明哪些复杂度被移除了，哪些边界现在更清晰了。

3. 验证
- 列出你实际运行过的命令。
- 明说哪些没跑。

4. 剩余风险
- 只写还真实存在的结构性风险。
- 如果没有新的明显结构风险，就明确写没有发现新的高优先级结构冗余。

Quality bar:
- Favor model clarity over historical compatibility.
- Prefer reducing future developer decision points.
- Keep diffs readable and architecture-oriented.
- If a concept can be made single-source-of-truth, do that instead of layering another helper.

Do not stop at analysis. Implement the changes, verify them, and then report.
```
