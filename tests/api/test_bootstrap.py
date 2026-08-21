"""Tests for the shared background-services bootstrap (app/api/bootstrap.py).

2026-06-13: prod web moved from the Werkzeug dev server (run_api.py) to
gunicorn (app/api/gunicorn_app.py). All background services (sync, schedulers,
workers, warmup) used to be started inline in run_api.main() — gunicorn_app
only created the Flask app. The shared bootstrap module guarantees both
entrypoints start the same services; these tests pin that contract.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_load_test_mode_starts_nothing(monkeypatch):
    """In load-test mode every background service stays off (gunicorn load
    tests never started them historically) and the call must not raise."""
    monkeypatch.setenv("AGENTYS_LOAD_TEST_MODE", "true")

    from app.api.bootstrap import start_background_services

    services = start_background_services(app=None)

    assert services.sync_service is None
    assert services.batch_worker is None
    assert services.recap_scheduler is None
    assert services.scheduled_email_scheduler is None
    assert services.learning_scheduler is None
    assert services.reminder_stop is None


def test_stop_accepts_inert_handles():
    """stop_background_services() is wired to atexit under gunicorn — it must
    never raise, even on handles that were never started."""
    from app.api.bootstrap import BackgroundServices, stop_background_services

    stop_background_services(BackgroundServices())


def test_gunicorn_app_starts_background_services():
    """gunicorn_app must wire the bootstrap (start + atexit drain) outside
    load-test mode — otherwise switching prod to gunicorn silently kills
    email sync and every scheduler."""
    source = (PROJECT_ROOT / "app" / "api" / "gunicorn_app.py").read_text()

    assert "start_background_services" in source
    assert "stop_background_services" in source
    assert "atexit" in source


def test_run_api_uses_shared_bootstrap():
    """run_api.py must consume the same bootstrap as gunicorn_app so the two
    entrypoints can never drift apart again."""
    source = (PROJECT_ROOT / "run_api.py").read_text()

    assert "start_background_services" in source
    assert "stop_background_services" in source


def test_post_sync_labeling_wired_in_boot_path():
    """Régression 2026-07-16 : la classification ne tournait que comme bg-job
    de GET /api/emails (webapp ouverte). Le hook post-sync doit exister dans
    bootstrap et être gaté sur new_emails_count — sinon le mobile (qui ne
    liste pas l'inbox quand counts=0) reste à « 0 à traiter » pour toujours.
    """
    import app.api.bootstrap as bootstrap

    src = Path(bootstrap.__file__).read_text(encoding="utf-8")
    assert "_label_new_emails_bg" in src
    # Le gate coût : ne classifier qu'à l'arrivée réelle de nouveaux mails.
    assert "if r.new_emails_count:" in src
    # Le hook vit APRÈS le cleanup noise dans la même boucle de résultats.
    assert src.index("_cleanup_noise_bg") < src.index("_label_new_emails_bg")


def test_label_new_emails_bg_queries_and_forwards(monkeypatch):
    """_label_new_emails_bg charge les non-lus inbox récents et les passe à
    _label_cached_emails_if_needed (qui est idempotent). Sans emails → no-op.
    """
    from unittest.mock import MagicMock, patch

    import app.api.routes_emails as re_mod

    fake_emails = [MagicMock(), MagicMock()]
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.all.return_value = fake_emails
    session = MagicMock()
    session.query.return_value = query
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)

    with patch("app.db.database.get_db_session", return_value=ctx), \
         patch.object(re_mod, "_label_cached_emails_if_needed") as mock_label:
        re_mod._label_new_emails_bg(42)
        mock_label.assert_called_once_with(fake_emails, 42)

    # Aucun email → pas d'appel au labeler.
    query.all.return_value = []
    with patch("app.db.database.get_db_session", return_value=ctx), \
         patch.object(re_mod, "_label_cached_emails_if_needed") as mock_label:
        re_mod._label_new_emails_bg(42)
        mock_label.assert_not_called()


def test_label_new_emails_bg_never_raises(monkeypatch):
    """Hook best-effort : une DB en vrac ne doit jamais faire tomber le
    thread post-sync (warning loggé, pas d'exception)."""
    from unittest.mock import patch

    import app.api.routes_emails as re_mod

    with patch("app.db.database.get_db_session", side_effect=RuntimeError("db down")):
        re_mod._label_new_emails_bg(42)  # ne doit pas lever
