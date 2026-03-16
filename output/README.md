# Output Artifacts

This directory is for local runtime artifacts, probes, screenshots, and one-off evaluation outputs.

Rules:
- Treat everything here as disposable by default.
- Do not commit generated output artifacts.
- Keep only a small manually curated subset on disk when it provides unique debugging or benchmark value.
- If an artifact becomes important repo knowledge, summarize it in docs and then delete the raw output when practical.

Current practice:
- `output/` is git-ignored except for this README.
- Long-lived source-of-truth docs should not live here.
