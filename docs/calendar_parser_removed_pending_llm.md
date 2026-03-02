# Calendar Parser Removed (Obsolete Note)

This document is obsolete after the V2 hard-cut cleanup.

Current runtime no longer uses legacy `sync/service` parser stubs or archived parser references. Calendar ingestion is handled by the V2 ingestion pipeline (`input_sources -> sync_requests -> ingest_results -> core_ingest apply -> review decisions`).
