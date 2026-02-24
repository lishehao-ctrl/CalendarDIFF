from __future__ import annotations

import importlib
from pathlib import Path

ui_router_module = importlib.import_module("app.modules.ui.router")


def _write_ui_fixture(root: Path) -> None:
    (root / "ui").mkdir(parents=True, exist_ok=True)
    (root / "_next" / "static" / "chunks").mkdir(parents=True, exist_ok=True)

    (root / "ui" / "index.html").write_text(
        "<html><body><h1>Deadline Diff Watcher</h1><div id='ui-root-redirect'></div></body></html>",
        encoding="utf-8",
    )
    (root / "processing.html").write_text(
        "<html><body><h1>Processing</h1><div id='processing-page'></div></body></html>",
        encoding="utf-8",
    )
    (root / "feed.html").write_text(
        "<html><body><h1>Feed</h1><div id='feed-page'></div></body></html>",
        encoding="utf-8",
    )
    (root / "runs.html").write_text(
        "<html><body><h1>Input Run History</h1><div id='run-history-page'></div></body></html>",
        encoding="utf-8",
    )
    (root / "_next" / "static" / "chunks" / "main.js").write_text("console.log('ok');", encoding="utf-8")


def test_ui_index_served_from_static_build(client, monkeypatch, tmp_path) -> None:
    _write_ui_fixture(tmp_path)
    monkeypatch.setattr(ui_router_module, "_FRONTEND_OUT_DIR", tmp_path)

    response = client.get("/ui")
    assert response.status_code == 200
    assert "Deadline Diff Watcher" in response.text
    assert "ui-root-redirect" in response.text


def test_ui_app_config_injects_api_key(client) -> None:
    response = client.get("/ui/app-config.js")
    assert response.status_code == 200
    assert "window.__APP_CONFIG__" in response.text
    assert '"apiKey": "test-api-key"' in response.text


def test_ui_returns_503_when_static_build_missing(client, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ui_router_module, "_FRONTEND_OUT_DIR", tmp_path / "missing")

    response = client.get("/ui")
    assert response.status_code == 503
    assert "UI assets are missing" in response.json()["detail"]


def test_ui_next_asset_path_is_served(client, monkeypatch, tmp_path) -> None:
    _write_ui_fixture(tmp_path)
    monkeypatch.setattr(ui_router_module, "_FRONTEND_OUT_DIR", tmp_path)

    response = client.get("/ui/_next/static/chunks/main.js")
    assert response.status_code == 200
    assert "console.log('ok');" in response.text


def test_ui_unknown_path_falls_back_to_index(client, monkeypatch, tmp_path) -> None:
    _write_ui_fixture(tmp_path)
    monkeypatch.setattr(ui_router_module, "_FRONTEND_OUT_DIR", tmp_path)

    response = client.get("/ui/unknown/page")
    assert response.status_code == 200
    assert "Deadline Diff Watcher" in response.text


def test_ui_named_page_path_is_served(client, monkeypatch, tmp_path) -> None:
    _write_ui_fixture(tmp_path)
    monkeypatch.setattr(ui_router_module, "_FRONTEND_OUT_DIR", tmp_path)

    response_profiles = client.get("/ui/profiles")
    assert response_profiles.status_code == 404

    response_processing = client.get("/ui/processing")
    assert response_processing.status_code == 200
    assert "Processing" in response_processing.text
    assert "processing-page" in response_processing.text

    response_feed = client.get("/ui/feed")
    assert response_feed.status_code == 200
    assert "Feed" in response_feed.text
    assert "feed-page" in response_feed.text

    response_runs = client.get("/ui/runs")
    assert response_runs.status_code == 200
    assert "Input Run History" in response_runs.text
    assert "run-history-page" in response_runs.text
