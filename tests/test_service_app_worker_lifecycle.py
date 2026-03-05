from __future__ import annotations

import anyio
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.service_app import create_service_app


def test_worker_task_starts_and_is_cancelled_on_shutdown(db_engine) -> None:
    del db_engine
    router = APIRouter()

    @router.get("/ping")
    def _ping() -> dict[str, bool]:
        return {"ok": True}

    state = {"started": 0, "cancelled": 0}

    async def _worker_task() -> None:
        state["started"] += 1
        cancelled_cls = anyio.get_cancelled_exc_class()
        try:
            while True:
                await anyio.sleep(0.01)
        except cancelled_cls:
            state["cancelled"] += 1
            raise

    app = create_service_app(
        title="Worker Lifecycle Test",
        version="0.1.0",
        routers=[router],
        worker_tasks=[_worker_task],
    )

    with TestClient(app) as client:
        response = client.get("/ping")
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert state["started"] == 1

    assert state["cancelled"] == 1


def test_service_app_without_worker_tasks_starts_normally(db_engine) -> None:
    del db_engine
    router = APIRouter()

    @router.get("/ping")
    def _ping() -> dict[str, bool]:
        return {"ok": True}

    app = create_service_app(
        title="No Worker Tasks Test",
        version="0.1.0",
        routers=[router],
    )
    with TestClient(app) as client:
        response = client.get("/ping")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_service_app_runs_startup_hooks(db_engine) -> None:
    del db_engine
    router = APIRouter()
    state = {"hook_called": 0}

    @router.get("/ping")
    def _ping() -> dict[str, bool]:
        return {"ok": True}

    def _startup_hook(_app) -> None:
        state["hook_called"] += 1

    app = create_service_app(
        title="Startup Hook Test",
        version="0.1.0",
        routers=[router],
        startup_hooks=[_startup_hook],
    )

    with TestClient(app) as client:
        response = client.get("/ping")
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    assert state["hook_called"] == 1
