from __future__ import annotations

from pathlib import Path


def test_input_router_is_router_aggregator_only() -> None:
    content = Path("app/modules/sources/router.py").read_text(encoding="utf-8")
    assert "@router." not in content
    assert "@public_router." not in content
    assert "include_router(" in content
