from __future__ import annotations

from app.modules.sync.types import RawICSEvent


class ICSParser:
    def parse(self, content: bytes) -> list[RawICSEvent]:
        del content
        raise RuntimeError(
            "calendar parser removed from runtime; see app.modules.sync.archive.legacy_ics_parser for reference"
        )
