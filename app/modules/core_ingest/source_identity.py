from __future__ import annotations

import hashlib

SOURCE_UID_NAMESPACE = "source_scoped_entity"


def build_source_scoped_entity_uid(*, source_kind: str, external_event_id: str) -> str:
    normalized_kind = (source_kind or "").strip().lower() or "unknown"
    normalized_external_id = external_event_id.strip()
    identity = f"{normalized_kind}|{normalized_external_id}|{SOURCE_UID_NAMESPACE}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return f"ent_{digest}"


__all__ = ["build_source_scoped_entity_uid"]
