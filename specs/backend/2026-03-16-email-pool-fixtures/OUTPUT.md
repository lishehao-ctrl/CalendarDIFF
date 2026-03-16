# Execution Output

## Status

Completed.

## Files Changed

- `/Users/lishehao/Desktop/Project/CalendarDIFF/scripts/build_email_pool_fixtures.py`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/tests/fixtures/private/email_pool/synthetic_ddlchange/manifest.json`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/tests/fixtures/private/email_pool/synthetic_ddlchange/samples.jsonl`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/tests/fixtures/private/email_pool/synthetic_ddlchange/README.md`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/tests/fixtures/private/email_pool/oauth_random_300/manifest.json`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/tests/fixtures/private/email_pool/oauth_random_300/samples.jsonl`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/tests/fixtures/private/email_pool/oauth_random_300/README.md`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/tests/fixtures/private/email_pool/oauth_filtered_150/manifest.json`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/tests/fixtures/private/email_pool/oauth_filtered_150/samples.jsonl`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/tests/fixtures/private/email_pool/oauth_filtered_150/README.md`
- `/Users/lishehao/Desktop/Project/CalendarDIFF/specs/backend/2026-03-16-email-pool-fixtures/OUTPUT.md`

## Validation

### Commands Run

1. `PYTHONPATH=. python scripts/build_email_pool_fixtures.py --bucket all --source-id 2 --scan-limit 2500 --seed 20260316`
2. `PYTHONPATH=. python scripts/build_email_pool_fixtures.py --bucket oauth_filtered_150 --source-id 2 --scan-limit 2000 --seed 20260316`
3. 

```bash
python - <<'PY'
import json
from pathlib import Path

root = Path('tests/fixtures/private/email_pool')
for bucket in ['synthetic_ddlchange','oauth_random_300','oauth_filtered_150']:
    d = root / bucket
    rows = []
    with (d/'samples.jsonl').open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    mids = [r.get('message_id') for r in rows if isinstance(r.get('message_id'), str)]
    dup = len(mids) - len(set(mids))
    print(bucket, 'count=', len(rows), 'duplicate_message_id=', dup)
    m = json.loads((d/'manifest.json').read_text(encoding='utf-8'))
    print(' manifest.sample_count=', m.get('sample_count'))
PY
```

4. 

```bash
python - <<'PY'
import json
from pathlib import Path

root = Path('tests/fixtures/private/email_pool')
req_common = ['sample_id','sample_source','message_id','thread_id','subject','from_header','snippet','body_text','internal_date','label_ids','collection_bucket','notes']
req_syn = ['expected_mode','expected_record_type','expected_semantic_event_draft','expected_directive']
req_oauth = ['filter_reason','source_id']
for bucket in ['synthetic_ddlchange','oauth_random_300','oauth_filtered_150']:
    rows = [json.loads(line) for line in (root/bucket/'samples.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    missing = 0
    for r in rows:
        for k in req_common:
            if k not in r:
                missing += 1
        if bucket == 'synthetic_ddlchange':
            for k in req_syn:
                if k not in r:
                    missing += 1
        else:
            for k in req_oauth:
                if k not in r:
                    missing += 1
    print(bucket, 'rows', len(rows), 'missing_fields', missing)
PY
```

### Counts Per Bucket

- `synthetic_ddlchange`: `30` samples, duplicate `message_id`: `0`
- `oauth_random_300`: `300` samples, duplicate `message_id`: `0`
- `oauth_filtered_150`: `150` samples, duplicate `message_id`: `0`

## Notes

- Stayed backend-only.
- Kept collected Gmail content under `tests/fixtures/private/email_pool/`.
- Used existing Gmail OAuth source (`source_id=2`).
- Normalized synthetic positive set into shared `samples.jsonl` sample schema.

## 中文总结

已按规范完成 private email-pool 三个 bucket 的构建与落盘，分别产出 30/300/150 条样本，并通过了 JSON 结构与去重校验。
