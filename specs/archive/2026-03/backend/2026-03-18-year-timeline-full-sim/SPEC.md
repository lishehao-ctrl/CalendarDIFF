# Year Timeline Full-Sim Background Layer

## Summary
Build a full-year simulation layer on top of the existing course-signal year timeline.

The current year timeline is already good at:
- course-related Gmail signal realism
- ICS change realism
- cross-channel lag for monitored academic events

What it does **not** yet simulate well is the rest of a real inbox:
- unrelated personal mail
- academic but non-target noise
- wrappers, digests, forwarding clutter
- campus and admin mail

This pass should add a realistic background-email layer so CalendarDIFF can be tested in a more realistic, full-inbox setting.

The result should be a **full simulation dataset**, not a replacement for the current core year timeline.

## Product intent
CalendarDIFF should be robust not only against hard course signals, but also against:
- lots of irrelevant mail
- near-relevant academic clutter
- wrapper-heavy messages
- misleading keywords like `deadline`, `final`, `quiz`, `submission`

This pass exists to measure:
- prefilter precision
- parser robustness under inbox-scale distraction
- false-positive resistance

## Required architecture decision
Do **not** mutate the existing core year timeline into a mixed junk bucket.

Instead, keep two layers:

1. `core course timeline`
   - the existing year timeline data for monitored course events
2. `background inbox stream`
   - unrelated and weakly-related non-target email traffic

Then compose them into:

3. `full simulation`
   - one mixed email stream that interleaves core signals and background noise

This preserves:
- precise regression on the core set
- realistic inbox simulation on the full set

## Scope

### In scope
- a one-year background email generator
- a full-sim composer that mixes course signal mail with background mail
- export of a full-sim email-pool bucket
- derived sets for full-sim evaluation
- tests for deterministic generation, composition, and fixture export

### Out of scope
- no frontend work
- no public API changes
- no parser changes in this pass
- no requirement to add unrelated ICS subscription noise unless it is trivial and clearly useful

## Main files
Recommended implementation files:

- `tools/datasets/year_timeline_background_stream.py`
- `tools/datasets/export_year_timeline_fixtures.py`
- optionally one small composition helper if needed:
  - `tools/datasets/year_timeline_full_sim.py`

Tests:
- `tests/test_year_timeline_background_stream.py`
- `tests/test_year_timeline_fixture_export.py`
- optionally one full-sim contract test if needed

Artifacts:
- `tests/fixtures/private/email_pool/year_timeline_full_sim/`
- `tests/fixtures/private/email_pool/derived_sets/year_timeline_full_sim_*.json`
- optionally a small manifest under `data/synthetic/year_timeline_demo/`

## Required realism

### 1. Background mail categories
The background stream must include at least these categories:

- `personal_finance`
  - bank alerts, billing, payment confirmation, credit card notices
- `commerce`
  - delivery, shopping, promo mail, subscription renewal
- `account_security`
  - verification, password reset, sign-in alert
- `campus_general`
  - university-wide events, admin reminders, housing, health, transportation
- `clubs_and_events`
  - org meetings, volunteering, social invites
- `newsletter`
  - generic digests, mailing-list summaries
- `jobs_and_careers`
  - recruiting, networking, internship alerts
- `calendar_wrapper`
  - “you have an event”, RSVP, calendar forwarding
- `academic_non_target`
  - lecture/discussion/office-hours/lab logistics, grade release, exam-format notes, solution release
- `lms_wrapper_noise`
  - Canvas/Piazza/Ed wrappers with no target signal

These categories must be deterministic and generated from templates, not hand-authored one-offs.

### 2. Realistic false-positive bait
The background stream must intentionally include misleading phrases such as:

- `deadline`
- `due`
- `final`
- `quiz`
- `submission`
- `grade`
- `assignment`
- `project`

But these messages should still be **non-target** from the product perspective.

Examples:
- “final billing deadline”
- “project fair RSVP due Friday”
- “quiz bowl registration”
- “grade posted”
- “lab section moved, report unchanged”

This is the point of the full-sim layer.

### 3. Inbox density
The full simulation should feel like a real mailbox, where monitored course mail is a minority.

Target ratio guidance for Gmail full-sim:
- `10%` monitored course-signal mail from the core year timeline
- `15%` academic but non-target mail
- `25%` wrappers/digests/clutter
- `50%` unrelated personal/general noise

These ratios do not need to be exact per batch, but should be roughly true over the full year.

### 4. Temporal realism
Background mail should not be uniformly random.

It should reflect realistic seasonal behavior:
- quarter start:
  - more setup/admin/campus mail
- mid-quarter:
  - more academic clutter and reminders
- internship season:
  - more jobs/career mail
- holiday periods:
  - more commerce/travel/social mail
- finals windows:
  - more academic but non-target mail like grade release, exam-format instructions, review sessions

### 5. Sender realism
Background senders should also have roles/styles, even if they are not academic.

Examples:
- `no-reply` automation
- campus office
- student org
- recruiter
- commerce sender
- security alert sender
- LMS wrapper sender

Each should influence:
- `from_header`
- subject style
- amount of junk text
- body formatting regularity

### 6. Message structure realism
Background messages should vary in:
- short notification style
- long newsletter style
- wrapper + quoted content style
- list/digest style
- footer-heavy promotional style

Some messages should have:
- noisy quoted threads
- repeated disclaimer/footer text
- HTML-ish plain-text flattening patterns
- multiple action prompts

## Composition rules

### Core rule
Do not destroy the existing core year timeline sample ids or truth semantics.

The full-sim layer should:
- import or read the existing core generated Gmail samples
- generate background samples
- merge them into a new mixed bucket with stable deterministic ordering

### Recommended new bucket
- `year_timeline_full_sim`

This bucket should include:
- all core course Gmail timeline messages
- plus background messages interleaved by timestamp

### Ordering
The final mixed bucket should be sorted by realistic `internal_date`.

The core signal messages must retain their own metadata such as:
- expected mode
- expected record type
- expected semantic payload / directive

Background messages should use:
- `expected_mode="unknown"`
- `expected_record_type=null`

## Derived sets
Add full-sim derived sets, recommended:

- `year_timeline_full_sim_smoke_96`
  - broad representative sample
- `year_timeline_full_sim_false_positive_bait_96`
  - messages with deadline-like language but non-target semantics
- `year_timeline_full_sim_academic_noise_96`
  - lecture/discussion/lab/grade/exam-format clutter
- `year_timeline_full_sim_wrapper_heavy_96`
  - LMS and digest style noise

Optional:
- `year_timeline_full_sim_quarter_start_64`
- `year_timeline_full_sim_finals_window_64`

## Export requirements
Update exporter logic so it can emit:

- the existing core bucket unchanged
- the new full-sim bucket
- derived sets for the full-sim bucket

Do not break:
- `scripts/process_local_email_pool.py --bucket ...`
- library catalog structure

## Validation
Required:

```bash
pytest -q tests/test_year_timeline_background_stream.py tests/test_year_timeline_fixture_export.py
python tools/datasets/year_timeline_scenarios.py --output data/synthetic/year_timeline_demo/year_timeline_manifest.json
python tools/datasets/export_year_timeline_fixtures.py --manifest data/synthetic/year_timeline_demo/year_timeline_manifest.json --target all
python scripts/process_local_email_pool.py --bucket year_timeline_full_sim --list-samples
```

Strongly recommended:

```bash
python scripts/process_local_email_pool.py --bucket year_timeline_full_sim --derived-set year_timeline_full_sim_smoke_96
```

If practical, also run one mixed/full-sim parser smoke to estimate false-positive behavior.

## Acceptance criteria
- existing core year timeline remains usable and intact
- new full-sim bucket exists and is deterministic
- background noise is substantially richer than a few admin samples
- full-sim ratio makes monitored course mail a minority
- false-positive bait is realistic and useful
- exporter/library discovery still works
- derived sets exist and are non-empty

## Implementation guidance
- Keep core generator edits minimal if possible
- Prefer a separate background generator and a clear merge step
- Do not hand-write giant JSON payloads
- Avoid overfitting to one inbox style
- Preserve deterministic output from fixed seed

## Notes for executor
- If you delegate, use subagents only for sidecar design:
  - background mail taxonomy
  - false-positive bait design
  - seasonal density suggestions
- Keep the actual generator/composer edits local
- Write results back into `OUTPUT.md`
