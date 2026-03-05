from __future__ import annotations

from typing import Any, Iterator


class Calendar:
    @staticmethod
    def from_ical(content: bytes | str) -> Calendar: ...
    def walk(self) -> Iterator[Any]: ...

