"""Démarrage/arrêt partagé des services de fond du backend web.

Extrait de run_api.main() (2026-06-13) pour que le serveur de prod gunicorn
(app/api/gunicorn_app.py) démarre exactement les mêmes services que le serveur
de dev Werkzeug (run_api.py). Avant ce module, le chemin gunicorn ne créait
que l'app Flask : basculer la prod sur gunicorn aurait silencieusement tué la
sync email, les schedulers et les workers.

Tous les imports de services se font à l'intérieur des fonctions : ce module
est importé par app.api.gunicorn_app au boot du worker, et des imports
top-level créeraient des cycles avec app.api (create_app) et app.api.websocket.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # pragma: no cover — import-time only
    from flask import Flask

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class BackgroundServices:
    """Handles des services démarrés, consommés par stop_background_services().

    gmail_watch_scheduler et onboarding_watchdog sont conservés pour
    introspection mais ne sont pas arrêtés explicitement — comportement
    identique au bloc shutdown historique de run_api.main().

    Review F01 — couplage implicite assumé : le cleanup scheduler du provider
    pool est démarré DANS create_app() (pas ici) et reste un singleton module-
    level de app.providers.provider_pool ; stop_background_services() l'arrête
    via import direct, sans handle dans ce dataclass. Même contrat que
    l'ancien run_api.main().
    """

    sync_service: Any = None
    batch_worker: Any = None
    recap_scheduler: Any = None
    gmail_watch_scheduler: Any = None
    scheduled_email_scheduler: Any = None
    learning_scheduler: Any = None
    onboarding_watchdog: Any = None
    reminder_stop: Optional[threading.Event] = None


def start_background_services(app: "Flask | None") -> BackgroundServices:
    """Démarre tous les services de fond du rôle web.

    En mode load-test (AGENTYS_LOAD_TEST_MODE), ne démarre rien et retourne
    des handles inertes — le chemin gunicorn load-test n'a historiquement
    jamais démarré ces services.
    """
    services = BackgroundServices()

    if _env_bool("AGENTYS_LOAD_TEST_MODE"):
        print("Background services: disabled (load test mode)")
        return services

    # SQLite/WAL maintenance must run before background schedulers start
    # competing for writes. This is idempotent and repairs both stale WAL files
    # after interrupted deploys and account.user_id drift from older hash logic.
    try:
        from app.db.database import get_db_session as _startup_db_session
        from app.db.maintenance import (
            checkpoint_wal as _checkpoint_wal,
            repair_all_account_user_ids as _repair_account_user_ids,
            run_with_sqlite_lock_retry as _retry_sqlite_lock,
        )

        def _startup_db_maintenance() -> int:
            _checkpoint_wal(source="startup")
            with _startup_db_session() as _db_session:
                return _repair_account_user_ids(_db_session)

        _repaired_accounts = _retry_sqlite_lock(
            _startup_db_maintenance,
            source="startup",
        )
        if _repaired_accounts:
            print(f"DB maintenance: repaired {_repaired_accounts} account user_id drift(s)")
        else:
            print("DB maintenance: WAL checkpoint complete, account IDs ok")
    except Exception as _db_maintenance_exc:
        logger.warning("DB maintenance skipped during startup: %s", _db_maintenance_exc)

    from app.api.routes import _invalidate_folder_cache
    from app.api.websocket import (
        emit_new_email,
        emit_sync_complete,
        emit_sync_error,
        emit_sync_progress,
        emit_sync_started,
    )
    from app.services.sync_service import init_sync_service

    # Initialize sync service with WebSocket callbacks
    def on_sync_complete_callback(results: list, duration_ms: int) -> None:
        """Convert SyncResult objects to dicts for WebSocket emission."""
        result_dicts = [
            {
                "account_id": r.account_id,
                "account_email": r.account_email,
                "success": r.success,
                "new_emails_count": r.new_emails_count,
                "error_message": r.error_message,
            }
            for r in results
        ]
        emit_sync_complete(result_dicts, duration_ms)

        # Auto-cleanup Noise emails after each successful sync
        for r in results:
            if r.success and r.account_id:
                from app.api.routes_emails import _cleanup_noise_bg
                from app.infrastructure.thread_pool import submit_background as _sb
                from app.multi_accounts import get_account_manager as _gam
                # `r.account_id` is the int DB id (e.g. 6). The provider pool
                # keys by the multi-account hash (e.g. "ca85336e01d3bc46"), so
                # we must resolve the hash via the email — passing the int
                # directly used to surface as a recurring "[NOISE-CLEANUP]
                # Error: Account 6 not found — refusing to fallback to env
                # provider" warning every 2 min in the logs and skipped the
                # cleanup entirely.
                acct_cfg = _gam().get_account_by_email(r.account_email) if r.account_email else None
                if acct_cfg is None:
                    logger.warning(
                        "[NOISE-CLEANUP] Skip auto-cleanup: no account hash for "
                        "db_id=%s email=%s — multi_accounts and DB are out of sync",
                        r.account_id, r.account_email,
                    )
                    continue
                _sb(_cleanup_noise_bg, r.account_id, acct_cfg.id)

                # Classification post-sync (2026-07-16) : sans ce hook, les
                # labels Action/FYI n'étaient produits que par le bg-job de
                # GET /api/emails — donc uniquement quand la webapp était
                # ouverte. Le mobile (counts=0 → n'appelle jamais /api/emails)
                # restait à « 0 à traiter ». Gaté sur new_emails_count : le
                # coût LLM ne court qu'à l'arrivée réelle de mails, comme le
                # chemin webapp, juste proactif. Idempotent côté helper.
                if r.new_emails_count:
                    from app.api.routes_emails import _label_new_emails_bg
                    _sb(_label_new_emails_bg, r.account_id)

                # Audit 2026-05-19 — kill snoozed followup drafts whose
                # thread has any new activity past the cold send (inbound
                # reply OR the user re-engaged the thread themselves).
                # This sweep walks the PendingDraft store directly and
                # treats any post-send activity as a signal that the
                # auto-nudge is moot. (Le `process_replies_after_sync`
                # legacy a été retiré le 2026-06-09 : son FollowupTracker
                # n'existe plus depuis le refactor 316c3434 et l'appel ne
                # faisait plus que logger « tracker port unavailable » à
                # chaque sync.)
                from app.api.quicksteps_scheduler import process_snoozed_draft_replies_after_sync
                _sb(process_snoozed_draft_replies_after_sync, r.account_id, r.account_email)

                # Real background tick: run the throttled per-account sweep
                # (housekeeping rules like "auto-archive inbox > 30d" +
                # snoozed-draft wake) server-side after every sync, so they
                # fire even when the user never opens the inbox. Throttled to
                # 5 min/account inside run_quicksteps_scheduled; idempotent.
                from app.api.quicksteps_scheduler import run_scheduled_sweeps_after_sync
                _sb(run_scheduled_sweeps_after_sync, r.account_id, r.account_email)

    def on_new_email_callback(email_data: dict) -> None:
        # S-08 fix: forward account_id from the sync result so the event
        # routes to the right user's room (sync runs in a bg thread with
        # no Flask request context).
        emit_new_email(email_data, account_id=email_data.get("account_id"))
        try:
            _invalidate_folder_cache("inbox")
            logger.debug("[CACHE] invalidated inbox on new_email")
        except Exception:
            pass

    # Default 120s: with Gmail Pub/Sub push active, the cron only exists as a
    # safety net (catches anything push missed, e.g. during backend restart).
    # Historical default was 15s, which consumed Gmail quota for nothing and
    # shadowed the push notifications (see GitHub issue #184). Lower only if
    # you explicitly need polling-only behavior without push.
    sync_interval = int(os.getenv("SYNC_INTERVAL_SECONDS", 120))
    services.sync_service = init_sync_service(
        sync_interval=sync_interval,
        on_sync_started=emit_sync_started,
        on_sync_progress=emit_sync_progress,
        on_sync_complete=on_sync_complete_callback,
        on_sync_error=emit_sync_error,
        on_new_email=on_new_email_callback,
    )
    print(f"Sync service: interval={sync_interval}s")

    # Start batch worker (off-hours draft processing at 50% discount)
    from app.config import BATCH_API_ENABLED
    if BATCH_API_ENABLED:
        from app.batch_queue import get_batch_worker, touch_user_activity
        services.batch_worker = get_batch_worker()
        services.batch_worker.start()
        print("Batch worker: started (off-hours schedule)")

        # Track user activity on real user-initiated API requests only.
        # Strategy: mutative methods (POST/PATCH/DELETE/PUT) always indicate real
        # user actions. GET requests to list endpoints (/api/emails, /api/drafts,
        # /api/health, etc.) are automated polling and must NOT reset the activity
        # timer — otherwise batch mode can never activate while the app is open.
        # Only GETs to specific-resource paths (e.g. /api/emails/<id>) count.
        import re as _re
        _SPECIFIC_RESOURCE_RE = _re.compile(
            r'^/api/(emails|drafts|draft)/[^/]+', _re.IGNORECASE
        )

        @app.before_request
        def _track_user_activity():
            from flask import request
            if request.method == 'OPTIONS':
                return
            # Mutative requests = real user action
            if request.method in ('POST', 'PATCH', 'DELETE', 'PUT'):
                touch_user_activity()
                return
            # GET to a specific resource (viewing an email/draft) = real user action
            if request.method == 'GET' and _SPECIFIC_RESOURCE_RE.match(request.path):
                touch_user_activity()
    else:
        print("Batch worker: disabled")
    print()

    # Start recap scheduler (monthly recap email + banner trigger)
    from app.services.recap_scheduler import RecapScheduler
    services.recap_scheduler = RecapScheduler()
    services.recap_scheduler.start()
    print("Recap scheduler: started (monthly check)")

    # Start Gmail Pub/Sub watch auto-renewal (audit P2 mother-of-all 2026-04-25).
    # Sans ça, les watches expirent silencieusement après 7j et la sync revert
    # au polling. Skip transparent si GMAIL_PUSH_TOPIC n'est pas set.
    from app.services.gmail_watch_scheduler import GmailWatchScheduler
    services.gmail_watch_scheduler = GmailWatchScheduler()
    services.gmail_watch_scheduler.start()
    print("Gmail watch scheduler: started (renew check every 6h)")

    # Start scheduled-email scheduler (envoi differe — schedule send).
    # Poll toutes les 60s la table scheduled_emails et delivre les rows
    # arrives a echeance (cf. app/services/scheduled_email_scheduler.py).
    from app.services.scheduled_email_scheduler import (
        ScheduledEmailScheduler,
        set_default_scheduler,
    )
    services.scheduled_email_scheduler = ScheduledEmailScheduler()
    set_default_scheduler(services.scheduled_email_scheduler)
    services.scheduled_email_scheduler.start()
    print("Scheduled email scheduler: started (poll every 60s)")

    # Start learning refresh scheduler (auto KB refresh)
    from app.learning_refresh import get_refresh_coordinator, LearningRefreshScheduler
    services.learning_scheduler = LearningRefreshScheduler(get_refresh_coordinator())
    services.learning_scheduler.start()
    print("Learning refresh scheduler: started (deep check every 6h)")

    # Start sync-job dispatch ticker (B-04, audit 2026-06-11). Le dispatch des
    # sync jobs était purement événementiel : un job en retry_waiting / différé
    # quota n'était re-dispatché que si un autre job était enqueué ou terminait.
    # Le tick balaie les backoff_until échus toutes les 60s.
    from app.services.sync_jobs import start_sync_job_ticker
    start_sync_job_ticker()
    print("Sync job ticker: started (dispatch sweep every 60s)")

    # Start onboarding watchdog : flips zombie onboardings to failed when
    # their worker thread dies mid-pipeline (e.g. 'database is locked' on
    # the running-status commit). Without this, the row stays pinned to
    # waiting_for_sync indefinitely and the frontend spins forever.
    from app.services.onboarding_watchdog import OnboardingWatchdog
    services.onboarding_watchdog = OnboardingWatchdog()
    services.onboarding_watchdog.start()
    print("Onboarding watchdog: started (poll every 60s, stale=10min)")

    # Start bulk-actions worker (rate-limited file/queue).
    # On boot it resets any items left in_progress by a previous run —
    # safe because every supported op is idempotent and 404s are treated
    # as skipped (cf. app/services/bulk_jobs/worker.py docstring).
    from app.services.bulk_jobs.worker import init_worker as _init_bulk_worker
    _init_bulk_worker()
    print("Bulk job worker: started (per-account FIFO + token bucket)")

    # Start auto-deletion scheduler (daily 04:00 local). Wires the 3
    # active toggles in Settings → Automatic Deletion into the bulk
    # queue. drafts_7d + newsletters_30d are accepted in settings but
    # currently no-op (cf. scheduler.py docstring "TODO v2").
    from app.services.bulk_jobs.scheduler import init_scheduler as _init_bulk_sched
    _init_bulk_sched()
    print("Auto-deletion scheduler: started (daily 04:00 local)")

    # Warmup (preload KB + writing-style profiles + contact-floor bootstrap) runs
    # in a BACKGROUND daemon thread so it NEVER delays the server reaching
    # socketio.run()/gunicorn serving. It ran SYNCHRONOUSLY here before — on every
    # boot/restart the server didn't accept requests until the warmup finished (it
    # loops ALL accounts and reads the sent folder), so the frontend flashed
    # "Connection lost" during the gap. The first draft may pay the cold-start I/O
    # tax (-500 ms to -1,5 s) until warmup completes — a far better trade than a
    # delayed/unreachable boot. (Stability hardening 2026-06-24.)
    def _run_startup_warmup() -> None:
        try:
            from sqlalchemy import select as _select
            from app.db.database import get_db_session
            from app.db.models.account import Account as _AccountModel
            from app.prompts import load_knowledge_from_db
            from app.infrastructure.container import get_container
            _warmup_count = 0
            _acct_rows: list[tuple[int, str]] = []
            with get_db_session() as _ws:
                for _a in _ws.scalars(_select(_AccountModel)).all():
                    _acct_rows.append((_a.id, _a.email or ""))
            _container = get_container()
            for _aid, _aemail in _acct_rows:
                try:
                    load_knowledge_from_db(_aid)
                    _container.get_writing_style_profile(account_id=_aid)
                    _warmup_count += 1
                except Exception as _we:
                    logger.debug("Warmup suppressed for account %s: %s", _aid, _we)
            print(f"Warmup: KB + style profiles preloaded for {_warmup_count}/{len(_acct_rows)} account(s)")

            # Contact-floor bootstrap: backfill the writing-style per-contact list
            # from the sent folder and repair past NOISE misclassifications for any
            # sender the user has already emailed. Idempotent — cheap to run every
            # startup because it only writes when something actually changes.
            try:
                from app.api.routes_helpers import (
                    backfill_contact_style_profiles_from_sent,
                    repair_noise_for_real_contacts,
                )
                for _aid, _aemail in _acct_rows:
                    try:
                        _bf = backfill_contact_style_profiles_from_sent(_aid)
                        _rp = repair_noise_for_real_contacts(_aid, user_email=_aemail)
                        if _bf.get("contacts_added") or _rp.get("fixed"):
                            print(
                                f"Contact floor (acct {_aid}): "
                                f"+{_bf.get('contacts_added', 0)} style profiles, "
                                f"{_rp.get('fixed', 0)} noise fixed"
                            )
                    except Exception as _cf_err:
                        logger.debug("Contact floor bootstrap skipped for %s: %s", _aid, _cf_err)
            except Exception as _cf_import_err:
                logger.debug("Contact floor bootstrap unavailable: %s", _cf_import_err)
        except Exception as _warmup_exc:
            logger.debug("Warmup failed (non-blocking): %s", _warmup_exc)
            print("Warmup: skipped (non-blocking)")

    threading.Thread(
        target=_run_startup_warmup, name="agentys-startup-warmup", daemon=True
    ).start()
    print("Warmup: started in background (server serving immediately)")

    # Report draft pipeline optimization flags so it's visible what's active
    try:
        from app.smart_routing import (
            _skip_critic_gate_enabled,
            _use_unified_draft_enabled,
        )
        from app.services.contact_summary_service import _feature_enabled as _cs_enabled
        print("Draft optimizations:")
        print(f"  - SKIP_CRITIC_GATE       : {'ON ' if _skip_critic_gate_enabled() else 'OFF'} (heuristic critic bypass)")
        print(f"  - USE_UNIFIED_DRAFT      : {'ON ' if _use_unified_draft_enabled() else 'OFF'} (aggressive critic bypass)")
        print(f"  - ENABLE_CONTACT_SUMMARY : {'ON ' if _cs_enabled() else 'OFF'} (structured long-term context)")
    except Exception as _flag_exc:
        logger.debug("Flag reporting failed: %s", _flag_exc)

    # Start reminder checker (follow-up notifications every 60s)
    from app.services.reminder_service import check_and_notify as _check_reminders

    services.reminder_stop = threading.Event()
    _reminder_stop = services.reminder_stop

    def _reminder_loop():
        while not _reminder_stop.is_set():
            try:
                _check_reminders()
            except Exception as _exc:
                logger.error("[reminder-checker] Error: %s", _exc, exc_info=True)
            _reminder_stop.wait(60)

    threading.Thread(target=_reminder_loop, daemon=True, name="reminder-checker").start()
    print("Reminder checker: started (60s interval)")

    # Start sync service
    services.sync_service.start()

    # Recover orphaned onboarding rows left in 'waiting_for_sync' / 'running'
    # by a previous crash or restart. Without this, the frontend stays stuck
    # on "Chargement..." forever because the in-memory wait thread is gone.
    try:
        from app.db.database import get_session_factory as _get_sf
        from app.onboarding.manager import OnboardingManager as _OM
        _recovery_mgr = _OM(session_factory=_get_sf())
        _recovered = _recovery_mgr.recover_orphaned_waiting()
        if _recovered:
            print(f"Onboarding recovery: {_recovered} orphaned row(s) marked failed")
    except Exception as _exc:
        logger.warning("Onboarding recovery skipped: %s", _exc)

    return services


def stop_background_services(services: BackgroundServices) -> None:
    """Drain ordonné des services — séquence identique au bloc shutdown
    historique de run_api.main(). Appelé via atexit sous gunicorn : chaque
    étape est défensive, rien ne doit lever.
    """
    print("\nStopping services...")
    if services.reminder_stop is not None:
        services.reminder_stop.set()
    if services.learning_scheduler is not None:
        services.learning_scheduler.stop()
    if services.recap_scheduler is not None:
        services.recap_scheduler.stop()
    try:
        if services.scheduled_email_scheduler is not None:
            services.scheduled_email_scheduler.stop()
    except Exception:
        pass
    try:
        from app.services.sync_jobs import stop_sync_job_ticker
        stop_sync_job_ticker()
    except Exception:
        pass
    if services.batch_worker:
        services.batch_worker.stop()
    # Drain bulk-job worker before sync_service so any in-flight
    # provider call finishes naturally (atomic at provider level).
    try:
        from app.services.bulk_jobs.scheduler import shutdown_scheduler as _shutdown_sched
        _shutdown_sched()
    except Exception:
        pass
    try:
        from app.services.bulk_jobs.worker import shutdown_worker as _shutdown_bulk
        _shutdown_bulk(timeout=15.0)
    except Exception:
        pass
    if services.sync_service is not None:
        services.sync_service.stop()
    try:
        from app.providers.provider_pool import stop_cleanup_scheduler
        stop_cleanup_scheduler()
    except Exception as _exc:
        logger.warning("Provider pool cleanup stop skipped during shutdown: %s", _exc)
    try:
        from app.db.maintenance import checkpoint_wal as _checkpoint_wal
        _checkpoint_wal(source="shutdown")
        print("SQLite WAL checkpoint complete")
    except Exception as _exc:
        logger.warning("SQLite WAL checkpoint skipped during shutdown: %s", _exc)
    print("API stopped")
