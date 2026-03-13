from __future__ import annotations

import hashlib
import json

ICS_COMPONENT_FINGERPRINT_HASH_KEY = "ics_component_fingerprint"


def build_component_key(*, uid: str, recurrence_id: str | None) -> str:
    normalized_uid = uid.strip()
    normalized_rid = (recurrence_id or "").strip()
    return f"{normalized_uid}#{normalized_rid}"


def build_external_event_id(*, uid: str, recurrence_id: str | None) -> str:
    normalized_uid = uid.strip()
    normalized_rid = (recurrence_id or "").strip()
    if not normalized_rid:
        return normalized_uid
    return f"{normalized_uid}#{normalized_rid}"


def external_event_id_from_component_key(component_key: str) -> str:
    key = component_key.strip()
    if "#" not in key:
        return key
    uid, rid = key.split("#", 1)
    uid = uid.strip()
    rid = rid.strip()
    if not rid:
        return uid
    return f"{uid}#{rid}"


def compute_component_fingerprint(*, fields: dict[str, object]) -> str:
    payload = {
        "hash_key": ICS_COMPONENT_FINGERPRINT_HASH_KEY,
        "fields": fields,
    }
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
