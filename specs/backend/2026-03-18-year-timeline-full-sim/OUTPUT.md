# Execution Output

## Changed Files

- `tools/datasets/year_timeline_background_stream.py`
- `tools/datasets/year_timeline_full_sim.py`
- `tools/datasets/export_year_timeline_fixtures.py`
- `scripts/process_local_email_pool.py`
- `tests/test_year_timeline_background_stream.py`
- `tests/test_year_timeline_fixture_export.py`
- `data/synthetic/year_timeline_demo/year_timeline_background_stream.json`
- `data/synthetic/year_timeline_demo/year_timeline_full_sim_manifest.json`
- `tests/fixtures/private/email_pool/year_timeline_full_sim/*`
- `tests/fixtures/private/email_pool/derived_sets/year_timeline_full_sim_*.json`
- regenerated existing year-timeline artifacts under `data/synthetic/year_timeline_demo/` and `tests/fixtures/private/email_pool/year_timeline_gmail/`

## Validation Run

- `pytest -q tests/test_year_timeline_background_stream.py tests/test_year_timeline_fixture_export.py`
  - result: `5 passed`
- `pytest -q tests/test_year_timeline_scenarios.py tests/test_year_timeline_background_stream.py tests/test_year_timeline_fixture_export.py`
  - result: `10 passed`
- `python tools/datasets/year_timeline_scenarios.py --output data/synthetic/year_timeline_demo/year_timeline_manifest.json`
  - result: manifest regenerated successfully
- `python tools/datasets/export_year_timeline_fixtures.py --manifest data/synthetic/year_timeline_demo/year_timeline_manifest.json --target all`
  - result: core bucket, full-sim bucket, derived sets, and background/full-sim manifests regenerated successfully
- `python scripts/process_local_email_pool.py --bucket year_timeline_full_sim --list-samples`
  - result: full-sim bucket listed successfully
- `python scripts/process_local_email_pool.py --bucket year_timeline_full_sim --derived-set year_timeline_full_sim_smoke_96 --list-samples`
  - result: full-sim derived set listed successfully

## What Improved

- The repo now has a separate deterministic background inbox generator instead of stuffing junk directly into the core year timeline.
- Full-sim composition preserves core course Gmail samples and their truth fields, then interleaves them with background mail into `year_timeline_full_sim`.
- The mixed inbox now matches the target ratio exactly over the full year:
  - `576` core course messages
  - `864` academic-but-non-target messages
  - `1440` wrapper/digest/clutter messages
  - `2880` unrelated personal/general messages
  - total `5760`, so monitored course mail is `10%`
- Background categories now cover:
  - `personal_finance`
  - `commerce`
  - `account_security`
  - `campus_general`
  - `clubs_and_events`
  - `newsletter`
  - `jobs_and_careers`
  - `calendar_wrapper`
  - `academic_non_target`
  - `lms_wrapper_noise`
- False-positive bait is now encoded generator-side instead of hand-authored. Messages intentionally contain terms like `deadline`, `due`, `final`, `quiz`, `assignment`, `submission`, and `project` while still remaining non-target.
- Seasonal behavior now shifts category mix:
  - quarter start: more campus/admin/setup mail
  - spring midterm/project window: more recruiting/internship mail
  - finals windows: more academic non-target clutter and LMS wrapper noise
  - late fall/finals rollover: more commerce and social clutter
- New full-sim derived sets now exist for:
  - smoke
  - false-positive bait
  - academic noise
  - wrapper heavy
  - quarter start
  - finals window

## Remaining Gaps

- The full-sim stream is still plain-text synthetic mail; it does not reproduce real HTML flattening or MIME multipart artifacts exactly.
- Background sender identities are realistic templates, not real-world mailbox histories or personalized long-lived threads.
- The inbox density ratio is realistic at year scale, but per-batch total volume is still fixed rather than fully elastic.
- No unrelated ICS subscription noise was added in this pass; the realism upgrade is Gmail/inbox focused only.
