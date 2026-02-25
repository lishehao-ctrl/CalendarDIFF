from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from app.core.config import get_settings

router = APIRouter(include_in_schema=False)
_FRONTEND_OUT_DIR = Path(__file__).resolve().parents[3] / "frontend" / "out"


@router.api_route("/ui", methods=["GET", "HEAD", "OPTIONS"])
def ui_index() -> Response:
    return _serve_index()


@router.get("/ui/app-config.js")
def ui_app_config() -> Response:
    settings = get_settings()
    payload = {
        "apiBase": "",
        "apiKey": settings.app_api_key,
    }
    content = f"window.__APP_CONFIG__ = {json.dumps(payload)};"
    return Response(content=content, media_type="application/javascript")


@router.api_route("/ui/{path:path}", methods=["GET", "HEAD", "OPTIONS"])
def ui_assets(path: str) -> Response:
    normalized = path.strip("/")
    if normalized == "profiles":
        raise HTTPException(status_code=404, detail="UI route not found")
    if normalized in {"inputs", "runs", "dev"} or normalized.startswith(("inputs/", "runs/", "dev/")):
        raise HTTPException(status_code=404, detail="UI route not found")
    asset = _resolve_asset_path(path)
    if asset is not None:
        return FileResponse(asset)
    if _looks_like_asset_request(path):
        raise HTTPException(status_code=404, detail="UI asset not found")
    return _serve_index()


def _serve_index() -> FileResponse:
    index = _resolve_index_file()
    if index is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "UI assets are missing. Run `cd frontend && npm ci && npm run build` "
                "to generate static files."
            ),
        )
    return FileResponse(index)


def _resolve_index_file() -> Path | None:
    for relative in ("ui/index.html", "index.html"):
        candidate = _safe_join(relative)
        if candidate is not None and candidate.exists():
            return candidate
    return None


def _resolve_asset_path(path: str) -> Path | None:
    normalized = path.strip("/")
    if not normalized:
        return _resolve_index_file()

    candidates = [
        normalized,
        f"{normalized}.html",
        f"{normalized}/index.html",
        f"ui/{normalized}",
        f"ui/{normalized}.html",
        f"ui/{normalized}/index.html",
    ]

    seen: set[str] = set()
    for relative in candidates:
        if relative in seen:
            continue
        seen.add(relative)
        candidate = _safe_join(relative)
        if candidate is not None and candidate.exists() and candidate.is_file():
            return candidate
    return None


def _safe_join(relative_path: str) -> Path | None:
    root = _FRONTEND_OUT_DIR.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _looks_like_asset_request(path: str) -> bool:
    normalized = path.strip("/")
    if normalized.startswith("_next/"):
        return True
    return "." in Path(normalized).name
