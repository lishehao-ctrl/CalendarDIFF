from __future__ import annotations

import ast
from pathlib import Path


def test_legacy_service_facades_removed() -> None:
    removed = [
        "app/modules/core_ingest/service.py",
        "app/modules/review_changes/service.py",
        "app/modules/review_links/service.py",
        "app/modules/input_control_plane/service.py",
        "app/modules/llm_runtime/worker.py",
    ]
    for path in removed:
        assert not Path(path).exists(), f"{path} should be removed in hard-cut import mode"


def _is_shell_reexport_module(path: str) -> bool:
    module = ast.parse(Path(path).read_text(encoding="utf-8"))
    has_function_or_class = any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for node in module.body)
    if has_function_or_class:
        return False
    allowed_nodes = (ast.ImportFrom, ast.Import, ast.Assign, ast.Expr)
    return all(isinstance(node, allowed_nodes) for node in module.body)


def test_critical_modules_are_not_shell_reexports() -> None:
    must_have_logic = [
        "app/modules/llm_runtime/tick_runner.py",
        "app/modules/llm_runtime/message_preflight.py",
        "app/modules/llm_runtime/message_processor.py",
        "app/modules/llm_runtime/parse_pipeline.py",
        "app/modules/llm_runtime/transitions.py",
        "app/modules/ingestion/connector_runtime.py",
        "app/modules/core_ingest/pending_proposal_rebuild.py",
        "app/modules/core_ingest/pending_change_store.py",
        "app/modules/review_changes/manual_correction_service.py",
        "app/modules/review_changes/manual_correction_preview_flow.py",
        "app/modules/review_changes/manual_correction_apply_txn.py",
        "app/modules/review_links/alerts_upsert_service.py",
        "app/modules/review_links/alerts_query_service.py",
        "app/modules/review_links/alerts_decision_service.py",
    ]
    for path in must_have_logic:
        assert not _is_shell_reexport_module(path), f"{path} should contain real logic, not re-export shell"
