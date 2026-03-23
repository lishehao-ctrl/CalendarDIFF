Read this first:
- /Users/lishehao/Desktop/Project/CalendarDIFF/specs/archive/2026-03/backend/2026-03-18-year-timeline-variety-prefilter/SPEC.md

Implement the dataset/tooling pass described there.

This is a backend/data-generation task, not a frontend task.

Your write scope is:
- `tools/datasets/*` related to year timeline/full-sim generation
- `tests/fixtures/private/email_pool/*`
- `tests/fixtures/private/ics_timeline/*` if needed for continuity
- `data/synthetic/year_timeline_demo/*`
- `scripts/evaluate_local_email_prefilter.py`
- `.gitignore` only if needed for the new archive root
- tests that directly cover this new dataset/tooling pass

Important rules:
- you are not alone in the repo; do not revert or overwrite unrelated edits from other agents
- do not touch frontend files
- do not change Gmail parser logic or prefilter logic
- archive current generated year-timeline outputs before replacing the active working set
- keep generation deterministic

Required outputs:
- generate the new dataset / fixtures
- generate or update derived sets
- add the offline prefilter evaluation path
- update:
  - /Users/lishehao/Desktop/Project/CalendarDIFF/specs/archive/2026-03/backend/2026-03-18-year-timeline-variety-prefilter/OUTPUT.md

When finished, write into `OUTPUT.md`:
- changed files
- commands run
- resulting dataset scale and category mix
- archive path used
- what now better simulates a real year inbox
- what still remains unrealistic
