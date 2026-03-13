from __future__ import annotations

from app.db.models.input import SourceKind
from app.db.models.review import Change, ChangeSourceRef
from app.modules.common.payload_schemas import ChangeSourceRefPayload


def normalize_source_refs(raw_rows: list[dict | ChangeSourceRefPayload]) -> list[ChangeSourceRefPayload]:
    out: list[ChangeSourceRefPayload] = []
    for row in raw_rows:
        if isinstance(row, ChangeSourceRefPayload):
            out.append(row)
            continue
        if not isinstance(row, dict):
            continue
        try:
            out.append(ChangeSourceRefPayload.model_validate(row))
        except Exception:
            continue
    return out


def primary_source_from_refs(source_refs: list[dict | ChangeSourceRefPayload]) -> dict | None:
    if not source_refs:
        return None
    first = normalize_source_refs([source_refs[0]])
    if not first:
        return None
    return first[0].to_primary_ref()


def change_source_refs_as_dicts(change: Change) -> list[dict]:
    out: list[dict] = []
    for row in sorted(change.source_refs, key=lambda item: item.position):
        out.append(
            ChangeSourceRefPayload(
                source_id=row.source_id,
                source_kind=row.source_kind.value if isinstance(row.source_kind, SourceKind) else None,
                provider=row.provider,
                external_event_id=row.external_event_id,
                confidence=row.confidence,
            ).model_dump(mode="json")
        )
    return out


def replace_change_source_refs(*, change: Change, source_refs: list[dict | ChangeSourceRefPayload]) -> None:
    normalized = normalize_source_refs(source_refs)
    allowed_source_kind_values = {kind.value for kind in SourceKind}
    existing_by_position = {row.position: row for row in change.source_refs}
    seen_positions: set[int] = set()
    for position, row in enumerate(normalized):
        source_kind_raw = row.source_kind
        source_kind = SourceKind(source_kind_raw) if isinstance(source_kind_raw, str) and source_kind_raw in allowed_source_kind_values else None
        current = existing_by_position.get(position)
        if current is None:
            current = ChangeSourceRef(position=position)
            change.source_refs.append(current)
        current.source_id = row.source_id
        current.source_kind = source_kind
        current.provider = row.provider
        current.external_event_id = row.external_event_id
        current.confidence = row.confidence
        seen_positions.add(position)

    for row in list(change.source_refs):
        if row.position not in seen_positions:
            change.source_refs.remove(row)


__all__ = [
    "change_source_refs_as_dicts",
    "normalize_source_refs",
    "primary_source_from_refs",
    "replace_change_source_refs",
]
