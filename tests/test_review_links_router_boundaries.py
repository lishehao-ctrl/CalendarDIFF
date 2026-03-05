from __future__ import annotations

import ast
from pathlib import Path


def test_review_links_router_is_router_aggregator_only() -> None:
    path = Path("app/modules/review_links/router.py")
    content = path.read_text(encoding="utf-8")
    assert "@router." not in content
    assert "include_router(" in content
    module = ast.parse(content)
    function_defs = [node for node in module.body if isinstance(node, ast.FunctionDef)]
    assert function_defs == []
