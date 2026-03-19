Read `SPEC.md` first and treat it as authoritative.

You are implementing a full-simulation inbox background layer for CalendarDIFF.

This is a dataset/tooling task, not a product API task.

Key instructions:

- Keep the existing core year timeline intact.
- Add a second generator layer for background inbox traffic.
- Compose core course mail + background mail into a new full-sim bucket.
- Do not hand-author large static JSON payloads.
- Keep everything deterministic from a fixed seed.
- Preserve compatibility with the existing email pool exporter and processing scripts.

Main goals:
- make monitored course mail a minority inside the full-sim bucket
- add realistic false-positive bait
- add unrelated personal/general noise
- add academic but non-target noise
- add wrapper/digest clutter

Preferred implementation strategy:

1. create a background-stream generator
2. create a composition step that merges background + core course timeline
3. export a new bucket `year_timeline_full_sim`
4. add derived sets for false-positive bait, academic noise, wrapper-heavy, and broad smoke
5. add tests and regenerate fixtures

Delegation guidance:
- if you use subagents, use them only for:
  - background-mail taxonomy design
  - seasonal density design
  - test gap scan
- do not assign overlapping edits on the main generator/composer files

Required final output:
- changed files
- commands run
- what now feels more like a real inbox
- remaining realism gaps
- all of that written into `OUTPUT.md`
