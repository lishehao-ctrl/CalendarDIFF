from __future__ import annotations

from types import SimpleNamespace

from app.modules.runtime_kernel.parse_task_queue import compute_parse_reclaim_idle_ms, consume_parse_tasks


def test_compute_parse_reclaim_idle_ms_uses_claim_timeout(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.runtime_kernel.parse_task_queue.get_settings",
        lambda: SimpleNamespace(llm_claim_timeout_seconds=300),
    )

    assert compute_parse_reclaim_idle_ms(poll_ms=500) == 300000


def test_consume_parse_tasks_passes_claim_timeout_to_reclaim(monkeypatch) -> None:
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        "app.modules.runtime_kernel.parse_task_queue.get_settings",
        lambda: SimpleNamespace(llm_claim_timeout_seconds=300),
    )
    monkeypatch.setattr("app.modules.runtime_kernel.parse_task_queue.ensure_parse_queue_group", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.modules.runtime_kernel.parse_task_queue.move_due_parse_retries", lambda *_args, **_kwargs: 0)

    def _claim_idle_stream_tasks(redis_client, *, stream_key, group_name, consumer_name, min_idle_ms, count):  # noqa: ANN001
        del redis_client, stream_key, group_name, consumer_name, count
        observed["min_idle_ms"] = min_idle_ms
        return []

    monkeypatch.setattr("app.modules.runtime_kernel.parse_task_queue.claim_idle_stream_tasks", _claim_idle_stream_tasks)
    monkeypatch.setattr(
        "app.modules.runtime_kernel.parse_task_queue.consume_stream_tasks",
        lambda *args, **kwargs: [],
    )

    consume_parse_tasks(
        redis_client=object(),  # type: ignore[arg-type]
        worker_id="llm-worker-test",
        batch_size=4,
        poll_ms=500,
    )

    assert observed["min_idle_ms"] == 300000
