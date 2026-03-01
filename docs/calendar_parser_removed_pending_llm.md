# Calendar Parser Removed (Pending LLM)

## Effective Date

1. This repository state as of `2026-02-28` removes calendar parser/normalizer from runtime.

## Current Runtime Behavior

1. `InputType.ICS` sync still performs fetch and cache checks (`304` and normalized content hash).
2. Any successful fetch/check path returns:
   - `SyncRunStatus.PARSE_FAILED`
   - `error_code=parse_calendar_parser_removed`
   - `last_error=calendar parser removed, pending llm implementation`
3. When `content` is present, raw evidence is still written by `save_ics`.
4. ICS sync does not write `SnapshotEvent`, `Event`, or `Change` rows in this temporary phase.

## Evidence Preview Behavior

1. `/v2/change-events/{change_id}/evidence/{side}/preview` no longer parses VEVENT payload.
2. Endpoint returns raw text preview only:
   - `event_count=0`
   - `events=[]`
   - `preview_text=<decoded text up to PREVIEW_MAX_BYTES>`

## Archived Legacy Code

1. Legacy parser reference: `app/modules/sync/archive/legacy_ics_parser.py`
2. Legacy normalizer reference: `app/modules/sync/archive/legacy_normalizer.py`
3. Runtime stubs remain in:
   - `app/modules/sync/ics_parser.py`
   - `app/modules/sync/normalizer.py`

## Dependency Change

1. Removed `icalendar` from:
   - `pyproject.toml`
   - `requirements.txt`

## Impact

1. Calendar diff functionality is intentionally unavailable until LLM pipeline is implemented.
2. Email ingestion/review/apply flow is unchanged.
3. Existing parser-focused tests and tooling are expected to fail until updated.

## Rollback

1. Revert this change set (single commit rollback is recommended).
2. Restore `icalendar` dependency in `pyproject.toml` and `requirements.txt`.
3. Restore pre-removal runtime implementation in `app/modules/sync/service.py`, `ics_parser.py`, `normalizer.py`, and `app/modules/changes/router.py`.
