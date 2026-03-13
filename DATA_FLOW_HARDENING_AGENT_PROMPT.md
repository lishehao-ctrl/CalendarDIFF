You are working in the CalendarDIFF repo.

Read this file first:

- /Users/lishehao/Desktop/Project/CalendarDIFF/DATA_FLOW_HARDENING_SPEC.md

Treat it as the source of truth for this task.

Your job is to make the current data flow truly unambiguous for future development.

This is not a broad redesign pass. This is a hardening pass focused on:

1. fixing the canonical edit branch so it is trustworthy again
2. collapsing the observation payload contract to one active runtime shape
3. enforcing latest-family-label authority everywhere user-facing
4. syncing docs to the real flow

Important decisions are already made by the spec:

- the active observation runtime envelope is top-level `source_facts + semantic_event + link_signals + kind_resolution`
- `semantic_event_draft` is parser-stage only
- `enrichment` is not an active runtime observation contract
- users should always see the latest family label
- `family_id` is the only label authority
- canonical edit internally means direct edit of approved entity state by `entity_uid`

Execution rules:

- do not reintroduce legacy Input/Event/Snapshot semantics
- do not keep half-compatibility branches if the spec already picks one direction
- do not leave merge markers or dead branch code in place
- do not leave user-facing display split between snapshot family names and latest labels
- do not scope-creep into unrelated architecture work

Recommended order:

1. canonical_edit_* repair
2. observation payload contract cleanup
3. family label authority cleanup
4. docs sync
5. targeted validation

Validation you should run:

```bash
rg -n "^(<<<<<<<|=======|>>>>>>>)" app/modules/review_changes
```

```bash
python -m py_compile \
  app/modules/review_changes/canonical_edit_target.py \
  app/modules/review_changes/canonical_edit_audit.py \
  app/modules/review_changes/canonical_edit_builder.py \
  app/modules/review_changes/canonical_edit_preview_flow.py \
  app/modules/review_changes/canonical_edit_apply_txn.py \
  app/modules/review_changes/canonical_edit_snapshot.py
```

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_review_edits_api.py \
  tests/test_review_canonical_edit_boundaries.py \
  tests/test_review_canonical_edit_flow_boundaries.py \
  tests/test_review_change_source_summary_api.py \
  tests/test_review_items_summary_api.py \
  tests/test_review_label_learning_api.py \
  tests/test_review_link_candidates_api.py \
  tests/test_review_link_alerts_api.py
```

If frontend display code is touched, also run:

```bash
cd frontend
npm run typecheck
npm run lint
NEXT_DIST_DIR=.next-prod npm run build
```

When you finish, respond in Chinese and use this structure:

1. 结果
- 用 2 到 4 句总结 data flow 变得更清楚的地方

2. 主要改动
- 按主题归纳
- 明确说明 canonical edit 修了什么
- 明确说明 observation payload 只剩什么 shape
- 明确说明 family label authority 现在怎么工作

3. 验证
- 列出你实际运行过的命令
- 明说哪些没跑

4. 风险 / 剩余问题
- 只写真实还存在的问题
- 如果没有新的高优先级 data flow 混乱点，就明确写出来

Quality bar:

- favor one clear contract over fallback-rich code
- favor future developer clarity over short-term compatibility
- keep diffs centered on data flow clarity
- do not stop at analysis

Implement the cleanup, validate it, and then report.
