from __future__ import annotations

from dataclasses import dataclass

from app.modules.ingestion.ics_delta.parser import ParsedIcsComponent, parse_ics_snapshot


@dataclass(frozen=True)
class IcsDeltaResult:
    changed_components: list[dict[str, str]]
    removed_component_keys: list[str]
    next_fingerprints: dict[str, str]
    total_components: int
    changed_components_count: int
    removed_components_count: int
    invalid_components: int


def build_ics_delta(
    *,
    content: bytes,
    previous_fingerprints: dict[str, str],
) -> IcsDeltaResult:
    snapshot = parse_ics_snapshot(content=content)
    normalized_previous = _normalize_previous_fingerprints(previous_fingerprints)
    current_fingerprints = {key: component.fingerprint for key, component in snapshot.components.items()}

    changed_keys: list[str] = []
    for key, fingerprint in current_fingerprints.items():
        if normalized_previous.get(key) != fingerprint:
            changed_keys.append(key)
    changed_keys.sort()

    removed_keys = sorted(
        (set(normalized_previous) - set(current_fingerprints)) | set(snapshot.cancelled_component_keys)
    )

    changed_components = [_serialize_changed_component(snapshot.components[key]) for key in changed_keys]
    return IcsDeltaResult(
        changed_components=changed_components,
        removed_component_keys=removed_keys,
        next_fingerprints=current_fingerprints,
        total_components=snapshot.total_components,
        changed_components_count=len(changed_components),
        removed_components_count=len(removed_keys),
        invalid_components=snapshot.invalid_components,
    )


def _normalize_previous_fingerprints(value: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, fingerprint in value.items():
        if not isinstance(key, str) or not key.strip():
            continue
        if not isinstance(fingerprint, str) or not fingerprint.strip():
            continue
        normalized[key.strip()] = fingerprint.strip()
    return normalized


def _serialize_changed_component(component: ParsedIcsComponent) -> dict[str, str]:
    return {
        "component_key": component.component_key,
        "external_event_id": component.external_event_id,
        "component_ical_b64": component.component_ical_b64,
    }
