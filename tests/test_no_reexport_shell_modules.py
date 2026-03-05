from __future__ import annotations

from pathlib import Path


def test_legacy_service_facades_removed() -> None:
    removed = [
        "app/modules/core_ingest/service.py",
        "app/modules/review_changes/service.py",
        "app/modules/review_links/service.py",
        "app/modules/input_control_plane/service.py",
    ]
    for path in removed:
        assert not Path(path).exists(), f"{path} should be removed in hard-cut import mode"
