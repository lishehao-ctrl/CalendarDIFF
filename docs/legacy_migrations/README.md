# Legacy Migration Archive

These files are archived snapshots of the pre-reset Alembic chain and are kept
for historical reference only.

- `0001_mvp_schema.py.txt`
- `0002_ics_audit_evidence.py.txt`
- `0003_notification_idempotency_key.py.txt`
- `0004_ui_overrides_and_change_viewed.py.txt`

Do not move these files back into `app/db/migrations/versions/`.
The active migration chain is now:

- `app/db/migrations/versions/0001_input_first_baseline.py`
- `app/db/migrations/versions/0002_profile_terms_and_input_identity.py`
- `app/db/migrations/versions/0003_fixed_interval_profile_notify_only.py`
- `app/db/migrations/versions/0004_user_terms_digest_foundation.py`
- `app/db/migrations/versions/0005_drop_profile_schema.py` (current head, revision id `0005_drop_profile_schema`)

Deprecated local reset scripts from previous eras:

- `scripts/reset_sqlite_db.sh` is archived/non-default for this repository.
- Use `scripts/reset_postgres_db.sh` for active local development reset.

This archive is documentation-only and is not executable.
