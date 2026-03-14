from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ApplyOutcome:
    affected_entity_uids: set[str] = field(default_factory=set)
    direct_changes_created: int = 0


__all__ = ["ApplyOutcome"]
