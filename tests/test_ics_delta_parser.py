from __future__ import annotations

from app.modules.ingestion.ics_delta.diff import build_ics_delta
from app.modules.ingestion.ics_delta.parser import IcsDeltaParseError, parse_ics_snapshot


def _ics_text(events: list[str]) -> bytes:
    body = "\n".join(events)
    return (
        "BEGIN:VCALENDAR\n"
        "VERSION:2.0\n"
        "PRODID:-//CalendarDIFF Test//EN\n"
        f"{body}\n"
        "END:VCALENDAR\n"
    ).encode("utf-8")


def _vevent(*, uid: str | None, start: str, end: str, summary: str, extra_lines: list[str] | None = None) -> str:
    lines = ["BEGIN:VEVENT"]
    if uid is not None:
        lines.append(f"UID:{uid}")
    lines.extend(
        [
            f"DTSTART:{start}",
            f"DTEND:{end}",
            f"SUMMARY:{summary}",
        ]
    )
    if extra_lines:
        lines.extend(extra_lines)
    lines.append("END:VEVENT")
    return "\n".join(lines)


def test_build_ics_delta_detects_changed_and_removed_components() -> None:
    before = _ics_text(
        [
            _vevent(uid="evt-unchanged", start="20260301T100000Z", end="20260301T110000Z", summary="Quiz"),
            _vevent(uid="evt-update", start="20260302T100000Z", end="20260302T110000Z", summary="HW1"),
            _vevent(uid="evt-remove", start="20260303T100000Z", end="20260303T110000Z", summary="Lab"),
            _vevent(uid="evt-cancel", start="20260304T100000Z", end="20260304T110000Z", summary="Project"),
        ]
    )
    before_snapshot = parse_ics_snapshot(content=before)
    previous_fingerprints = {key: component.fingerprint for key, component in before_snapshot.components.items()}

    after = _ics_text(
        [
            _vevent(uid="evt-unchanged", start="20260301T100000Z", end="20260301T110000Z", summary="Quiz"),
            _vevent(uid="evt-update", start="20260302T130000Z", end="20260302T140000Z", summary="HW1"),
            _vevent(uid="evt-new", start="20260305T100000Z", end="20260305T110000Z", summary="Midterm"),
            _vevent(
                uid="evt-cancel",
                start="20260304T100000Z",
                end="20260304T110000Z",
                summary="Project",
                extra_lines=["STATUS:CANCELLED"],
            ),
        ]
    )
    delta = build_ics_delta(content=after, previous_fingerprints=previous_fingerprints)

    changed_keys = {row["component_key"] for row in delta.changed_components}
    assert changed_keys == {"evt-new#", "evt-update#"}
    assert set(delta.removed_component_keys) == {"evt-remove#", "evt-cancel#"}
    assert "evt-unchanged#" in delta.next_fingerprints
    assert "evt-remove#" not in delta.next_fingerprints
    assert "evt-cancel#" not in delta.next_fingerprints
    assert delta.invalid_components == 0


def test_parse_ics_snapshot_counts_invalid_components_without_uid() -> None:
    content = _ics_text(
        [
            _vevent(uid=None, start="20260301T100000Z", end="20260301T110000Z", summary="Missing UID"),
            _vevent(uid="evt-valid", start="20260302T100000Z", end="20260302T110000Z", summary="Valid"),
        ]
    )
    snapshot = parse_ics_snapshot(content=content)

    assert snapshot.total_components == 2
    assert snapshot.invalid_components == 1
    assert set(snapshot.components) == {"evt-valid#"}


def test_parse_ics_snapshot_raises_on_malformed_calendar() -> None:
    malformed = b"BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:x\nSUMMARY:bad\n"
    try:
        parse_ics_snapshot(content=malformed)
    except IcsDeltaParseError as exc:
        assert "ics parse failed" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected IcsDeltaParseError")
