"""P2: Gmail Pub/Sub watch must be auto-renewed by a background scheduler.

Bug (mother-of-all audit 2026-04-25): Gmail Pub/Sub watches expire after
7 days. `app/api/gmail_push.py` has a manual `POST /api/gmail/watch/renew-due`
endpoint, but no internal cron called it — production watches expired
silently and the sync reverted to slow polling without alerting the user.

Fix: `app/services/gmail_watch_scheduler.GmailWatchScheduler` is a daemon
thread that runs every 6h, finds Gmail accounts whose watch expires within
24h, and calls Gmail's `users.watch()` to refresh. Started at boot from
`run_api.py`.
"""

from __future__ import annotations

import time
from unittest.mock import patch


from app.services.gmail_watch_scheduler import GmailWatchScheduler


def test_scheduler_class_exists():
    """Regression: the scheduler must continue to be importable from its
    public path (run_api.py imports it by this name)."""
    assert GmailWatchScheduler is not None
    s = GmailWatchScheduler()
    assert hasattr(s, "start")
    assert hasattr(s, "stop")
    assert hasattr(s, "_renew_due")
    assert hasattr(s, "_renew_one")


def test_scheduler_registered_in_boot_path():
    """The web boot path must call GmailWatchScheduler().start().

    Without this, watches expire silently in prod after 7d and sync silently
    reverts to slow polling — exactly the bug the audit flagged.

    2026-06-13: the background-services startup moved from run_api.main() to
    the shared app/api/bootstrap.py (used by BOTH run_api.py and the gunicorn
    prod entrypoint). The scheduler registration is asserted there, plus the
    wiring of both entrypoints onto the shared bootstrap.
    """
    from app.api import bootstrap
    src = open(bootstrap.__file__, encoding="utf-8").read()
    assert "from app.services.gmail_watch_scheduler import GmailWatchScheduler" in src
    assert "GmailWatchScheduler()" in src
    # The instance must actually be started.
    assert ".start()" in src.split("GmailWatchScheduler()", 1)[1][:200]

    # Both entrypoints must consume the shared bootstrap so the scheduler
    # runs under Werkzeug (dev) AND gunicorn (prod).
    # NB: gunicorn_app is read from disk, NOT imported — importing it would
    # execute create_app() + start the real background services in the tests.
    import os as _os
    import run_api  # noqa: F401  -- imported for getsourcefile reach
    assert "start_background_services" in open(run_api.__file__, encoding="utf-8").read()
    _gapp_src = open(
        _os.path.join(_os.path.dirname(bootstrap.__file__), "gunicorn_app.py"),
        encoding="utf-8",
    ).read()
    assert "start_background_services" in _gapp_src


def test_renew_due_skips_when_topic_missing(monkeypatch):
    """If GMAIL_PUSH_TOPIC is not configured, renewal is a no-op (debug log)
    — no Gmail API calls, no DB queries."""
    monkeypatch.delenv("GMAIL_PUSH_TOPIC", raising=False)
    monkeypatch.delenv("GMAIL_PUBSUB_TOPIC", raising=False)
    sched = GmailWatchScheduler()
    with patch("app.db.database.get_db_session_with_retry") as mock_session:
        sched._renew_due()
        mock_session.assert_not_called()


def test_scheduler_reads_same_topic_env_as_push_endpoints(monkeypatch):
    """Regression (2026-07): the daemon read GMAIL_PUBSUB_TOPIC while every
    other component (gmail_push endpoints + renew-due cron) reads
    GMAIL_PUSH_TOPIC. In prod only GMAIL_PUSH_TOPIC is set, so the daemon
    skipped forever and the internal renewal safety-net was silently dead.
    Both must read the SAME env var.
    """
    # Structural: the shared env-var name must be GMAIL_PUSH_TOPIC.
    from app.api.gmail_push import DEFAULT_TOPIC_ENV
    assert DEFAULT_TOPIC_ENV == "GMAIL_PUSH_TOPIC"

    # Behavioural: with GMAIL_PUSH_TOPIC set (and the legacy name unset), the
    # daemon must NOT skip — it must reach the DB query.
    monkeypatch.delenv("GMAIL_PUBSUB_TOPIC", raising=False)
    monkeypatch.setenv("GMAIL_PUSH_TOPIC", "projects/test/topics/agentys-gmail")
    sched = GmailWatchScheduler()
    with patch("app.db.database.get_db_session_with_retry") as mock_session:
        sess = mock_session.return_value.__enter__.return_value
        sess.query.return_value.filter.return_value.filter.return_value.filter.return_value.all.return_value = []
        sched._renew_due()
        mock_session.assert_called_once()


def test_thread_lifecycle_start_stop():
    """start() must launch a daemon thread, stop() must terminate it cleanly."""
    sched = GmailWatchScheduler()
    sched.start()
    try:
        assert sched._thread is not None
        assert sched._thread.is_alive()
        assert sched._thread.daemon is True
        # Idempotent: starting twice doesn't spawn a second thread.
        first_thread = sched._thread
        sched.start()
        assert sched._thread is first_thread
    finally:
        sched.stop()
        # Give it a moment to actually exit.
        for _ in range(20):
            if not sched._thread.is_alive():
                break
            time.sleep(0.1)
        assert not sched._thread.is_alive()
