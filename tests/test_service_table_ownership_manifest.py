from __future__ import annotations

import json
import os
import subprocess
import sys


def test_service_table_ownership_check_script_passes() -> None:
    env = dict(os.environ)
    result = subprocess.run(
        [sys.executable, "scripts/check_table_ownership.py"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["valid"] is True
    assert payload["errors"] == []
