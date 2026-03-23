# Year Timeline Variety + Prefilter Evaluation Spec

## Purpose

Build a larger and more varied one-year offline simulation dataset so CalendarDIFF can be tested against:

- real deadline-change signals
- large volumes of unrelated inbox junk
- misleading near-course spam
- academic non-target clutter
- source-layer prefilter behavior before messages ever reach the LLM

This pass is about dataset realism and measurement. It is not a parser-refactor pass.

## Fixed Decisions

- Keep this pass backend/tooling/dataset-only.
- Do not change Gmail parser semantics, family logic, or canonical apply logic in this pass.
- Do not change Gmail prefilter logic in this pass; measure it instead.
- Preserve the current core year timeline concept:
  - monitored course-signal source of truth
  - mixed inbox/full-sim layer built on top
- Preserve the current `responses + shared cache prefix` LLM path; this pass only improves the data it is tested against.
- Alias merge suggestion is out of scope; extraction can remain source-near and family handles merge later.

## Required End State

- The repo has one new larger year-scale dataset generation pass that is more various than the current full-sim/year-timeline set.
- The new dataset models a continuous year inbox with far more unrelated mail and more distinct junk categories.
- Every Gmail sample in the new dataset has enough metadata to evaluate whether it should be blocked by the prefilter before LLM.
- There is one offline prefilter-evaluation path that reports interception rate before LLM:
  - overall
  - by mail category
  - by target vs non-target class
- Existing generated year-timeline artifacts are archived under an ignored archive location so the new dataset can become the active working set without losing historical reference.

## Product Intent

The target test should simulate this workflow:

1. a very large mixed inbox enters the system
2. obvious junk is stopped before LLM
3. only a smaller subset reaches Gmail LLM parsing
4. among those, true ddlchange signals should still survive

This pass exists so we can measure:

- prefilter interception rate
- junk leak-through rate
- downstream Gmail parser robustness on the post-filter subset

## Scope

### In scope

- expand the one-year Gmail full-sim generator into a much more various, high-noise inbox simulation
- keep or regenerate compatible ICS timeline fixtures where needed for mixed regression continuity
- add expected prefilter-route labels or equivalent routing metadata for Gmail samples
- add one offline prefilter-evaluation script or test helper
- archive current generated year-timeline datasets
- add/update tests for dataset generation and prefilter evaluation
- update any catalog/derived-set manifests needed for the new dataset

### Out of scope

- no frontend work
- no public HTTP API changes
- no Gmail parser logic changes
- no Gmail prefilter logic changes
- no family merge/suggestion implementation changes

## Required Dataset Shape

### 1. Bigger mixed inbox

The new full-sim dataset should be materially larger than the current 5760-message mixed year.

Recommended target:

- at least `10k` Gmail messages total across the synthetic year
- monitored course-signal messages should remain a minority
- the rest should be split across realistic noise categories

The distribution does not need to be exactly fixed, but should roughly look like:

- `5%` to `10%` monitored target course-signal mail
- `10%` to `20%` academic but non-target mail
- `20%` to `30%` wrappers / digests / mailing-list clutter
- `45%` to `60%` unrelated personal/commercial/security/campus noise

### 2. More varied junk categories

The generator should add stronger variation across these non-target families:

- ads / commerce / promo
- personal finance / billing / bank / card
- package / subscription / renewal
- account security / verification / login alerts
- housing / lease / maintenance / utilities
- jobs / recruiting / networking
- campus-wide admin
- clubs / events / RSVP / volunteering
- student services / advising / EASy / enrollment bureaucracy
- LMS wrappers with no target signal
- academic non-target:
  - lecture
  - discussion
  - lab logistics
  - office hours
  - grade posted / regrade / solutions
  - exam-format notes

### 3. Misleading bait before LLM

The junk stream must intentionally include many phrases that can trick weak filters:

- `deadline`
- `due`
- `final`
- `quiz`
- `assignment`
- `project`
- `submission`
- `grade`

But these should still be labeled non-target when appropriate.

### 4. Continuous year realism

Do not make every batch feel the same.

The year should evolve with realistic timing:

- quarter start: admin/setup/course logistics spikes
- mid-quarter: assignment churn and academic clutter
- internship season: recruiting and career spikes
- housing / billing / commerce cycles
- finals windows: grade release, exam-format, review-session clutter
- break windows: more commerce / personal / travel / social noise

### 5. Prefilter-evaluation metadata

Each Gmail sample in the new full-sim working set must support offline prefilter evaluation.

Recommended fields or equivalent:

- `prefilter_expected_route`
  - `parse`
  - `skip_unknown`
- `prefilter_reason_family`
  - for example `target_course_signal`, `academic_non_target`, `lms_wrapper_noise`, `commerce`, `security`, `campus_admin`, `jobs`, `housing`, etc.
- optional:
  - `prefilter_should_match_course_token`
  - `prefilter_sender_strength`
  - `prefilter_keyword_bait`

Do not overcomplicate the schema if a smaller equivalent shape is enough.

## Required Evaluation Tooling

Add one offline evaluation path for prefilter interception.

Recommended new script:

- `scripts/evaluate_local_email_prefilter.py`

It should:

- load a bucket or derived set from `tests/fixtures/private/email_pool`
- run the current `matches_gmail_source_filters()` behavior on each sample
- report:
  - total parse vs skip counts
  - interception rate before LLM
  - target recall at prefilter stage
  - non-target interception by category
  - false-positive leak-through by category

This pass is measuring the filter, not changing it.

## Archive Requirement

Before or while generating the new active dataset:

- archive the current generated year-timeline artifacts into a new ignored location

Recommended ignored archive root:

- `archive/generated/`

Recommended archive content:

- current `data/synthetic/year_timeline_demo/*`
- current `tests/fixtures/private/email_pool/year_timeline_gmail/*`
- current `tests/fixtures/private/email_pool/year_timeline_full_sim/*`
- current `tests/fixtures/private/ics_timeline/scenarios/year-timeline-*`
- current `tests/fixtures/private/year_timeline_mixed/*`

The pass should update `.gitignore` if needed so the archive location stays ignored.

Do not delete historical outputs without archiving them first.

## Required Implementation Areas

- `tools/datasets/year_timeline_scenarios.py`
- `tools/datasets/year_timeline_background_stream.py`
- `tools/datasets/year_timeline_full_sim.py`
- `tools/datasets/export_year_timeline_fixtures.py`
- new helper(s) if needed under `tools/datasets/`
- `scripts/evaluate_local_email_prefilter.py`
- catalog / manifest / derived-set files under:
  - `tests/fixtures/private/email_pool/`
  - `tests/fixtures/private/ics_timeline/`
  - `data/synthetic/year_timeline_demo/`
- `.gitignore` if a new archive root is introduced

## Acceptance Criteria

1. A new more-varied one-year mixed inbox dataset exists and is larger than the current full-sim baseline.
2. The dataset includes explicit non-target junk families and realistic false-positive bait.
3. The dataset supports offline prefilter evaluation before LLM.
4. Existing generated year-timeline outputs are archived into an ignored archive location instead of being silently overwritten.
5. New or updated derived sets exist for:
   - broad smoke
   - alias hard cases
   - prefilter bait
   - academic non-target noise
   - wrapper-heavy noise
   - full-year mixed regression
6. The repo has a repeatable prefilter evaluation command that produces interception stats.

## Required Tests

- generator tests for the new larger variety mix
- exporter tests for the new manifests / buckets / derived sets
- prefilter evaluation tests or at least one deterministic script contract test
- existing year-timeline generator/exporter tests updated as needed

Minimum validation commands expected from the executing agent:

```bash
pytest -q tests/test_year_timeline_scenarios.py tests/test_year_timeline_background_stream.py tests/test_year_timeline_fixture_export.py
python tools/datasets/year_timeline_scenarios.py --output data/synthetic/year_timeline_demo/year_timeline_manifest.json
python tools/datasets/export_year_timeline_fixtures.py --manifest data/synthetic/year_timeline_demo/year_timeline_manifest.json --target all
python scripts/process_local_email_pool.py --bucket year_timeline_gmail --derived-set year_timeline_alias_hard_48 --list-samples
python scripts/evaluate_local_email_prefilter.py --bucket <new-full-sim-bucket> --derived-set <new-prefilter-derived-set>
```

## Explicit Non-Goals

- no frontend integration
- no parser prompt changes
- no filter heuristic tuning
- no change to public backend API surface
