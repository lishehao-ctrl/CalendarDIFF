from __future__ import annotations

import time
from types import SimpleNamespace

from app.modules.runtime.llm.tick_runner import run_llm_worker_tick


def _msg(message_id: str, request_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        message_id=message_id,
        request_id=request_id,
        source_id=1,
        attempt=0,
        reason="initial",
    )


def test_run_llm_worker_tick_refills_slots_before_batch_finishes(monkeypatch) -> None:
    consumed_batches = [
        ("llm:parse:stream", "llm-parse-workers", [_msg("m1", "req-1")]),
        ("llm:parse:stream", "llm-parse-workers", [_msg("m2", "req-2")]),
        ("llm:parse:stream", "llm-parse-workers", []),
    ]
    consume_calls: list[tuple[int, int]] = []
    acked: list[list[str]] = []
    processed: list[str] = []

    monkeypatch.setattr("app.modules.runtime.llm.tick_runner.get_settings", lambda: SimpleNamespace(llm_worker_concurrency=2, llm_queue_consumer_poll_ms=1))

    def _consume_parse_tasks(*, redis_client, worker_id: str, batch_size: int, poll_ms: int):
        del redis_client, worker_id
        consume_calls.append((batch_size, poll_ms))
        if consumed_batches:
            return consumed_batches.pop(0)
        return ("llm:parse:stream", "llm-parse-workers", [])

    def _ack_parse_tasks(*, redis_client, message_ids: list[str]):
        del redis_client
        acked.append(list(message_ids))
        return len(message_ids)

    def _process_parse_task_message(*, message, redis_client, session_factory, worker_id: str, stream_key: str):
        del redis_client, session_factory, worker_id, stream_key
        if message.message_id == "m1":
            time.sleep(0.05)
        processed.append(message.message_id)
        return True

    monkeypatch.setattr("app.modules.runtime.llm.tick_runner.consume_parse_tasks", _consume_parse_tasks)
    monkeypatch.setattr("app.modules.runtime.llm.tick_runner.ack_parse_tasks", _ack_parse_tasks)
    monkeypatch.setattr("app.modules.runtime.llm.tick_runner.process_parse_task_message", _process_parse_task_message)

    processed_count = run_llm_worker_tick(
        redis_client=object(),  # type: ignore[arg-type]
        session_factory=object(),  # type: ignore[arg-type]
        worker_id="llm-worker-test",
    )

    assert processed_count == 2
    assert processed == ["m1", "m2"] or processed == ["m2", "m1"]
    assert acked == [["m1"], ["m2"]] or acked == [["m2"], ["m1"]]
    assert len(consume_calls) >= 2
