from __future__ import annotations


def normalize_review_note(note: str | None, *, max_len: int = 512) -> str | None:
    if not isinstance(note, str):
        return None
    normalized = note.strip()
    if not normalized:
        return None
    return normalized[:max_len]


def dedupe_ids_preserve_order(ids: list[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for raw in ids:
        normalized = int(raw)
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


__all__ = ["dedupe_ids_preserve_order", "normalize_review_note"]
