from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_dead_runtime_apply_modules_removed() -> None:
    removed_files = [
        REPO_ROOT / "app" / "modules" / "changes" / "summary_service.py",
        REPO_ROOT / "app" / "modules" / "changes" / "workspace_posture.py",
        REPO_ROOT / "app" / "modules" / "runtime" / "apply" / "change_evidence.py",
        REPO_ROOT / "app" / "modules" / "runtime" / "apply" / "constants.py",
        REPO_ROOT / "app" / "modules" / "runtime" / "apply" / "course_work_item_family_rebuild.py",
        REPO_ROOT / "app" / "modules" / "runtime" / "apply" / "course_work_item_family_resolution.py",
        REPO_ROOT / "app" / "modules" / "runtime" / "apply" / "raw_type_matching.py",
        REPO_ROOT / "app" / "modules" / "runtime" / "connectors" / "replay_service.py",
    ]
    for path in removed_files:
        assert not path.exists(), f"dead module should remain removed: {path}"


def test_empty_dead_module_dirs_have_no_source_files() -> None:
    dead_dirs = [
        REPO_ROOT / "app" / "modules" / "sync",
        REPO_ROOT / "app" / "modules" / "evidence",
    ]
    for root in dead_dirs:
        if not root.exists():
            continue
        live_files = [
            path
            for path in root.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        ]
        assert not live_files, f"dead module dir should not regain source files: {live_files}"
