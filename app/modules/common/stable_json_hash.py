from __future__ import annotations

import hashlib
import json

from fastapi.encoders import jsonable_encoder


def stable_json_hash(payload: object) -> str:
    serialized = json.dumps(jsonable_encoder(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


__all__ = ["stable_json_hash"]
