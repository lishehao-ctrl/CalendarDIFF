from __future__ import annotations

import json
import subprocess
import sys


def test_microservice_closure_guard_passes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_microservice_closure.py"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["valid"] is True
    assert payload["errors"] == []
