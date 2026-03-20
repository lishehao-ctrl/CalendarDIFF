from __future__ import annotations

import importlib

MODEL_MODULES = (
    "app.db.models.shared",
    "app.db.models.input",
    "app.db.models.runtime",
    "app.db.models.review",
    "app.db.models.notify",
)


def load_all_models() -> None:
    for module_name in MODEL_MODULES:
        importlib.import_module(module_name)


__all__ = ["MODEL_MODULES", "load_all_models"]
