from __future__ import annotations

import logging

from app.core.config import get_settings
from app.core.logging import sanitize_log_message
from app.db.session import get_session_factory
from app.modules.runtime.apply.worker import run_core_apply_tick
from app.modules.runtime.connectors.connector_runtime import run_connector_tick
from app.modules.runtime.connectors.orchestrator import run_orchestrator_tick
from app.modules.runtime.llm.tick_runner import run_llm_worker_tick
from app.modules.notify.consumer import run_notification_enqueue_tick
from app.modules.notify.digest_service import dispatch_pending_notifications
from app.modules.runtime.kernel.parse_task_queue import get_parse_queue_redis_client
from app.modules.runtime.service_workers import TickResult, build_periodic_worker_task, coerce_int_metric

logger = logging.getLogger(__name__)
session_factory = get_session_factory()
redis_client = get_parse_queue_redis_client()
settings = get_settings()


def _build_ingest_tick(worker_id: str):
    def _tick() -> dict[str, object]:
        orchestrated_count = 0
        connector_processed = 0
        try:
            with session_factory() as db:
                try:
                    orchestrated_count = run_orchestrator_tick(db, worker_id=worker_id)
                except Exception as exc:  # pragma: no cover - defensive worker loop
                    db.rollback()
                    logger.error(
                        "ingest service stage failed stage=orchestrator worker_id=%s error=%s",
                        worker_id,
                        sanitize_log_message(str(exc)),
                    )

                try:
                    connector_processed = run_connector_tick(db, worker_id=worker_id)
                except Exception as exc:  # pragma: no cover - defensive worker loop
                    db.rollback()
                    logger.error(
                        "ingest service stage failed stage=connector worker_id=%s error=%s",
                        worker_id,
                        sanitize_log_message(str(exc)),
                    )
        except Exception as exc:  # pragma: no cover - defensive worker loop
            logger.error(
                "ingest service tick failed worker_id=%s error=%s",
                worker_id,
                sanitize_log_message(str(exc)),
            )
        return {
            "orchestrated_count": orchestrated_count,
            "connector_processed": connector_processed,
        }

    return _tick


def _log_ingest_success(worker_id: str, result: TickResult, latency_ms: int) -> str:
    payload = result if isinstance(result, dict) else {}
    orchestrated_count = coerce_int_metric(payload.get("orchestrated_count"))
    connector_processed = coerce_int_metric(payload.get("connector_processed"))
    return (
        "ingest service tick worker_id=%s orchestrated_count=%s connector_processed=%s latency_ms=%s"
        % (
            worker_id,
            orchestrated_count,
            connector_processed,
            latency_ms,
        )
    )


run_ingest_worker = build_periodic_worker_task(
    service_name="ingest-service",
    worker_name="ingest service",
    worker_id_env="INGESTION_WORKER_ID",
    enabled_env="INGEST_SERVICE_ENABLE_WORKER",
    tick_seconds_env="INGESTION_TICK_SECONDS",
    default_tick_seconds=2.0,
    logger=logger,
    tick_builder=_build_ingest_tick,
    log_success=_log_ingest_success,
)



def _build_review_apply_tick(worker_id: str):
    def _tick() -> dict[str, object]:
        apply_processed = 0
        try:
            with session_factory() as db:
                try:
                    apply_processed = run_core_apply_tick(db)
                except Exception as exc:  # pragma: no cover - defensive worker loop
                    db.rollback()
                    logger.error(
                        "review apply stage failed worker_id=%s error=%s",
                        worker_id,
                        sanitize_log_message(str(exc)),
                    )
        except Exception as exc:  # pragma: no cover - defensive worker loop
            logger.error(
                "review apply tick failed worker_id=%s error=%s",
                worker_id,
                sanitize_log_message(str(exc)),
            )
        return {"apply_processed": apply_processed}

    return _tick



def _log_review_apply_success(worker_id: str, result: TickResult, latency_ms: int) -> str:
    payload = result if isinstance(result, dict) else {}
    apply_processed = coerce_int_metric(payload.get("apply_processed"))
    return "review apply tick worker_id=%s apply_processed=%s latency_ms=%s" % (
        worker_id,
        apply_processed,
        latency_ms,
    )


run_review_apply_worker = build_periodic_worker_task(
    service_name="review-service",
    worker_name="review apply",
    worker_id_env="REVIEW_APPLY_WORKER_ID",
    enabled_env="REVIEW_SERVICE_ENABLE_APPLY_WORKER",
    tick_seconds_env="REVIEW_APPLY_TICK_SECONDS",
    default_tick_seconds=2.0,
    logger=logger,
    tick_builder=_build_review_apply_tick,
    log_success=_log_review_apply_success,
)



def _build_notification_tick(worker_id: str):
    def _tick() -> dict[str, object]:
        enqueued_notifications = 0
        processed_batches = 0
        sent_count = 0
        failed_count = 0
        try:
            with session_factory() as db:
                if settings.enable_notifications:
                    enqueued_notifications = run_notification_enqueue_tick(db)
                    dispatch_result = dispatch_pending_notifications(db)
                    processed_batches = dispatch_result.processed_batches
                    sent_count = dispatch_result.sent_count
                    failed_count = dispatch_result.failed_count
                else:
                    logger.info(
                        "notification tick skipped worker_id=%s reason=notifications_disabled",
                        worker_id,
                    )
        except Exception as exc:  # pragma: no cover - defensive worker loop
            logger.error(
                "notification tick failed worker_id=%s error=%s",
                worker_id,
                sanitize_log_message(str(exc)),
            )
        return {
            "enqueued_notifications": enqueued_notifications,
            "processed_slots": processed_batches,
            "processed_batches": processed_batches,
            "sent_count": sent_count,
            "failed_count": failed_count,
        }

    return _tick



def _log_notification_success(worker_id: str, result: TickResult, latency_ms: int) -> str:
    payload = result if isinstance(result, dict) else {}
    enqueued_notifications = coerce_int_metric(payload.get("enqueued_notifications"))
    processed_batches = coerce_int_metric(payload.get("processed_batches") or payload.get("processed_slots"))
    sent_count = coerce_int_metric(payload.get("sent_count"))
    failed_count = coerce_int_metric(payload.get("failed_count"))
    return (
        "notification tick worker_id=%s enqueued_notifications=%s processed_batches=%s sent_count=%s failed_count=%s tick_latency_ms=%s"
        % (
            worker_id,
            enqueued_notifications,
            processed_batches,
            sent_count,
            failed_count,
            latency_ms,
        )
    )


run_notification_worker = build_periodic_worker_task(
    service_name="notification-service",
    worker_name="notification",
    worker_id_env="NOTIFICATION_WORKER_ID",
    enabled_env="NOTIFICATION_SERVICE_ENABLE_WORKER",
    tick_seconds_env="NOTIFICATION_TICK_SECONDS",
    default_tick_seconds=5.0,
    logger=logger,
    tick_builder=_build_notification_tick,
    log_success=_log_notification_success,
)



def _build_llm_tick(worker_id: str):
    def _tick() -> int:
        return run_llm_worker_tick(
            redis_client=redis_client,
            session_factory=session_factory,
            worker_id=worker_id,
        )

    return _tick



def _log_llm_success(worker_id: str, result: TickResult, latency_ms: int) -> str | None:
    processed = int(result) if isinstance(result, int) else 0
    if processed <= 0:
        return None
    return "llm worker tick worker_id=%s processed=%s latency_ms=%s" % (
        worker_id,
        processed,
        latency_ms,
    )


run_llm_worker = build_periodic_worker_task(
    service_name="llm-service",
    worker_name="llm",
    worker_id_env="LLM_WORKER_ID",
    enabled_env="LLM_SERVICE_ENABLE_WORKER",
    logger=logger,
    tick_builder=_build_llm_tick,
    log_success=_log_llm_success,
    fixed_tick_seconds=0.05,
)


__all__ = [
    "run_ingest_worker",
    "run_llm_worker",
    "run_notification_worker",
    "run_review_apply_worker",
]
