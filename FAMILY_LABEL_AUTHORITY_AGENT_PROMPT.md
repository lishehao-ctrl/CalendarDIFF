You are working in the CalendarDIFF repo.

Read these files first, in order:

1. `/Users/lishehao/Desktop/Project/CalendarDIFF/ENTITY_FIRST_SEMANTIC_SPEC.md`
2. `/Users/lishehao/Desktop/Project/CalendarDIFF/DATA_FLOW_HARDENING_SPEC.md`
3. `/Users/lishehao/Desktop/Project/CalendarDIFF/FAMILY_LABEL_AUTHORITY_SPEC.md`

Treat them as the source of truth for this task.

Your job is to finish the family label authority cleanup so future development only has one rule:

- `family_id` is the only identity
- latest `canonical_label` is the only default user-facing family label

This is a focused cleanup pass. Do not scope-creep into unrelated architecture work.

Already-decided product rules:

- users should always see the latest family label everywhere
- rename should update display globally
- family rows are not a normal hard-delete target
- if frozen family names still exist inside `changes` or evidence, they are audit-only, not display authority
- later, `course_work_item_family_rebuild` should also be cleaned to converge to the main runtime contract

What to do:

1. inspect all current family label resolution paths
2. remove snapshot-label authority from default display logic
3. ensure user-facing review, edit, link, and notification flows all resolve labels from latest authority by `family_id`
4. tighten family lifecycle behavior so hard delete is not treated as a normal product path
5. update docs to reflect the final rule
6. if a field like `event_entities.family_name` still exists, either remove it or make its deprecated/audit-only role explicit

Important constraints:

- do not reintroduce old fallback logic that prefers frozen names
- do not treat missing family rows as a normal UX branch
- do not use display labels as identity
- do not broaden this into a general semantic refactor
- do not stop after analysis

Recommended order:

1. backend label resolution helpers
2. review/link/notify read paths
3. family lifecycle / delete guard behavior
4. frontend presenters if needed
5. docs sync
6. targeted validation

Suggested validation:

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_review_items_summary_api.py \
  tests/test_review_change_source_summary_api.py \
  tests/test_review_label_learning_api.py \
  tests/test_review_edits_api.py \
  tests/test_review_link_candidates_api.py \
  tests/test_review_link_alerts_api.py \
  tests/test_notify_jsonl_sink.py
```

If frontend code is touched:

```bash
cd /Users/lishehao/Desktop/Project/CalendarDIFF/frontend
npm run typecheck
npm run lint
NEXT_DIST_DIR=.next-prod npm run build
```

When you finish, respond in Chinese and use this structure:

1. 结果
- 用 2 到 4 句总结 family label authority 现在如何工作

2. 主要改动
- 按主题归纳
- 明确说明默认 display authority 现在是什么
- 明确说明是否还保留了冻结 family_name，以及它现在只是什么用途
- 明确说明 family 删除/生命周期规则怎么收敛了

3. 验证
- 列出你实际运行过的命令
- 明说哪些没跑

4. 风险 / 剩余问题
- 只写真实还存在的问题
- 如果没有新的高优先级 family authority 混乱点，就明确写出来

Quality bar:

- prefer one label authority over multiple soft fallbacks
- prefer explicit invariants over permissive legacy behavior
- keep diffs centered on family authority and display consistency
- if a redundant label field remains, make its non-authoritative role explicit
