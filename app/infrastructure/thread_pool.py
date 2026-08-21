"""
Centralized thread pool for background tasks.

Replaces ad-hoc Thread(daemon=True).start() with bounded concurrency.
Maximum 8 workers to prevent thread explosion.

Usage:
    from app.infrastructure.thread_pool import submit_background

    submit_background(my_function, arg1, arg2)
"""

import atexit
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from app.infrastructure.logging_config import get_logger

logger = get_logger(__name__)

_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="agentys-bg")


def get_executor() -> ThreadPoolExecutor:
    """Return the centralized thread pool executor for direct Future submission."""
    return _pool


def submit_background(fn, *args, **kwargs):
    """Submit a function to run in the background thread pool.

    Returns the Future object for optional result tracking.
    Exceptions are logged but not re-raised.
    """
    usage_context = _capture_usage_context()

    def _wrapped():
        tokens = _apply_usage_context(usage_context)
        try:
            with _apply_llm_attribution_context(usage_context):
                return fn(*args, **kwargs)
        except Exception as e:
            logger.error(f"Background task {fn.__name__} failed: {e}")
            return None
        finally:
            _reset_usage_context(tokens)

    return _pool.submit(_wrapped)


def _capture_usage_context():
    try:
        from app.infrastructure.cost_manager import get_usage_context

        return get_usage_context()
    except Exception:
        return None


def _apply_usage_context(usage_context):
    if not usage_context:
        return None
    try:
        from app.infrastructure.cost_manager import set_usage_context

        account_id, user_id, feature = usage_context
        return set_usage_context(account_id=account_id, user_id=user_id, feature=feature)
    except Exception:
        return None


def _apply_llm_attribution_context(usage_context):
    if not usage_context:
        return nullcontext()
    account_id, user_id, feature = usage_context
    if account_id is None:
        return nullcontext()
    try:
        from app.infrastructure.llm_attribution import llm_attribution

        return llm_attribution(
            "background",
            account_id=account_id,
            user_id=user_id,
            feature=feature,
        )
    except Exception:
        return nullcontext()


def _reset_usage_context(tokens) -> None:
    try:
        from app.infrastructure.cost_manager import reset_usage_context

        reset_usage_context(tokens)
    except Exception:
        return None


def shutdown_pool():
    """Gracefully shut down the thread pool."""
    _pool.shutdown(wait=False)


atexit.register(shutdown_pool)
