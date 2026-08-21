"""RQ job entrypoint for draft generation."""

from __future__ import annotations

from typing import Any

from app.infrastructure.logging_config import get_logger

logger = get_logger(__name__)

_worker_app = None


def _get_worker_app():
    global _worker_app
    if _worker_app is None:
        from app.api import create_app
        from app.api.websocket import init_socketio

        app = create_app()
        init_socketio(app)
        _worker_app = app
    return _worker_app


def process_draft_generation_job(payload: dict[str, Any]) -> None:
    """Process one serialized draft generation job."""
    from app.infrastructure.draft_job_queue import (
        mark_redis_draft_job_started,
        release_redis_draft_job,
    )

    key = str(payload.get("job_key") or "")
    account_id = payload.get("job_account_id")
    task_id = str(payload.get("task_id") or "")
    failed = False
    error = None
    try:
        if task_id:
            try:
                mark_redis_draft_job_started(task_id=task_id)
            except Exception:
                logger.warning("Failed to mark Redis draft job started", exc_info=True)
        app = _get_worker_app()
        with app.app_context():
            from app.api.routes_emails import process_email_draft_payload

            process_email_draft_payload(payload)
    except Exception:
        failed = True
        error = "Draft worker job failed"
        logger.exception("Draft worker job failed")
        raise
    finally:
        if key:
            try:
                release_redis_draft_job(
                    key=key,
                    account_id=account_id,
                    task_id=task_id,
                    failed=failed,
                    error=error,
                )
            except Exception:
                logger.warning("Failed to release Redis draft job", exc_info=True)
