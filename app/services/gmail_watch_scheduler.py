"""Gmail Pub/Sub watch auto-renewal scheduler.

Audit P2 (mother-of-all 2026-04-25) : `app/api/gmail_push.py:290` expose
``POST /api/gmail/watch/renew-due`` qui renouvelle les watches Gmail
expirant dans les 24h, mais aucun cron interne ne tape ce endpoint. En
production sans CI scheduling externe, les watches expirent silencieusement
au bout de 7 jours et la sync revient au polling sans alerter — l'utilisateur
remarque seulement quand un email "tarde" à apparaître.

Ce scheduler tourne dans un daemon thread (pattern RecapScheduler) et
appelle la logique de renewal directement (pas via HTTP — pas de network
roundtrip pour s'auto-pinger). Idempotent : Gmail accepte les `watch()`
répétés même quand la watch en cours est encore valide.

Une seule instance par process. ``start()`` appelée depuis ``run_api.py``
au boot. Démarre avec un sleep de 60s pour laisser le reste du boot finir
sans hammering, puis check toutes les 6h.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Toutes les 6h : large fenêtre pour rattraper si le process avait été down,
# tout en évitant de spammer Google. Gmail watch expire au bout de 7 jours
# (604800 s) ; on a donc 28 chances de renewal entre chaque expiration —
# largement suffisant.
_CHECK_INTERVAL_SECONDS = 6 * 3600
# On renouvelle tout watch qui expire dans les 24h. Buffer généreux pour ne
# rater aucun cas (timezone shift, container restart, etc.).
_RENEW_WINDOW = timedelta(hours=24)


class GmailWatchScheduler:
    """Background daemon thread that renews Gmail Pub/Sub watches before expiry."""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="GmailWatchScheduler",
        )
        self._thread.start()
        logger.info("GmailWatchScheduler started (interval %ss)", _CHECK_INTERVAL_SECONDS)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("GmailWatchScheduler stopped")

    def _run(self) -> None:
        # Initial delay : laisse le reste du boot terminer (DB, sync service,
        # warmup KB). Évite de spammer Google avec un renewal pendant que
        # tout démarre.
        if self._stop_event.wait(timeout=60):
            return

        while not self._stop_event.is_set():
            try:
                self._renew_due()
            except Exception as e:
                logger.warning("GmailWatchScheduler renewal cycle failed: %s", e)

            if self._stop_event.wait(timeout=_CHECK_INTERVAL_SECONDS):
                break

    def _renew_due(self) -> None:
        """Trouve les comptes Gmail dont la watch expire dans la fenêtre, renouvelle.

        Tolérant : un échec sur un compte ne bloque pas les autres. Les erreurs
        sont loguées (warning) mais pas propagées — un watch raté = juste un
        revert au polling, pas un crash de service.
        """
        import os
        from app.db.database import get_db_session_with_retry
        from app.db.models.account import Account

        # Must match the env var read by gmail_push.py (DEFAULT_TOPIC_ENV) and
        # the renew-due cron. Historically this read GMAIL_PUBSUB_TOPIC while
        # prod only sets GMAIL_PUSH_TOPIC, so the daemon skipped forever and
        # the internal renewal safety-net was silently dead (2026-07 fix).
        topic = os.environ.get("GMAIL_PUSH_TOPIC", "")
        if not topic:
            logger.debug("GmailWatchScheduler skip: GMAIL_PUSH_TOPIC not set")
            return

        cutoff = datetime.now(timezone.utc) + _RENEW_WINDOW
        with get_db_session_with_retry() as session:
            accounts = (
                session.query(Account)
                .filter(Account.provider == "gmail")
                .filter(Account.is_active.is_(True))
                .filter(
                    (Account.gmail_watch_expiration.is_(None))
                    | (Account.gmail_watch_expiration <= cutoff)
                )
                .all()
            )
            if not accounts:
                logger.debug("GmailWatchScheduler: no watches due for renewal")
                return

            renewed = 0
            failed = 0
            for account in accounts:
                try:
                    self._renew_one(account, topic)
                    renewed += 1
                except Exception as e:
                    failed += 1
                    logger.warning(
                        "Gmail watch renewal failed for account %s (%s): %s",
                        account.id, account.email, e,
                    )
            if renewed or failed:
                logger.info(
                    "GmailWatchScheduler: renewed %d / failed %d (cutoff=%s)",
                    renewed, failed, cutoff.isoformat(),
                )
            session.commit()

    def _renew_one(self, account, topic: str) -> None:
        """Renouvelle la watch d'un compte. Met à jour l'expiration en DB."""
        import hashlib
        from app.providers.gmail_adapter import GmailAdapter

        token_hash_id = hashlib.sha256(
            f"gmail:{account.email}".encode()
        ).hexdigest()[:16]
        adapter = GmailAdapter(account_id=token_hash_id)
        if not adapter.authenticate():
            raise RuntimeError("gmail authentication failed")
        response = adapter.start_watch(topic_name=topic, label_ids=["INBOX"])
        exp_ms = response.get("expiration") if isinstance(response, dict) else None
        if exp_ms is not None:
            account.gmail_watch_expiration = datetime.fromtimestamp(
                int(exp_ms) / 1000.0, tz=timezone.utc,
            )
        account.gmail_watch_topic = topic
