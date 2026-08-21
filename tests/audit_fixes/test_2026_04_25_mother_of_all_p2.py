# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fixes — 2026-04-25 mother-of-all report (passe 2).

Couvre les fixes ajoutés en deuxième passe (continue-jusqu'à-tout-fermer) :

- **P0-A3** — sync UNIQUE collision drops contact updates
  → ``test_ensure_contact_for_email_creates_missing_contact``,
    ``test_ensure_contact_for_email_skips_self_email``,
    ``test_ensure_contact_for_email_handles_sent_recipients``

- **P1-A4** — auth backoff explicit eviction on account deletion
  → ``test_evict_auth_backoff_drops_entry``,
    ``test_evict_auth_backoff_returns_false_on_missing``

- **P1-A5** — Outlook 429 handling
  → ``test_is_throttle_error_recognises_signals``,
    ``test_retry_after_seconds_extracts_from_headers_and_message``

- **P2** — backoff log noise reduction
  → ``test_backoff_clear_log_level_depends_on_failure_count``

- **P2** — Gmail watch scheduler module sanity
  → ``test_gmail_watch_scheduler_skips_when_no_topic``,
    ``test_gmail_watch_scheduler_start_stop_lifecycle``

- **C-2 / C-3 cache isolation** — verrouille les fixes existants pour Codex
  → ``test_pending_draft_cache_keyed_per_account``,
    ``test_smart_routing_draft_cache_keyed_per_account``

Run: ``pytest tests/audit_fixes/test_2026_04_25_mother_of_all_p2.py -v``
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock



# ---------------------------------------------------------------------------
# P0-A3 — _ensure_contact_for_email helper


def test_ensure_contact_for_email_creates_missing_contact():
    """En cas d'UNIQUE collision (ou email déjà connu), on doit AU MINIMUM
    garantir que le contact existe. Le bump du compteur n'est pas fait
    (anti-double-count) mais l'absence du contact serait une régression
    de la liste contacts."""
    from app.services.sync_service import SyncService

    svc = SyncService()

    contact_repo = MagicMock()
    std_email = MagicMock()
    std_email.sender = "alice@example.com"
    std_email.sender_name = "Alice"
    std_email.to = []
    std_email.cc = []

    account = MagicMock()
    account.id = 42
    account.email = "owner@example.com"

    svc._ensure_contact_for_email(contact_repo, std_email, account, is_sent=False)

    contact_repo.get_or_create.assert_called_once()
    # On ne doit JAMAIS appeler increment_email_count ici (anti-double-count).
    contact_repo.increment_email_count.assert_not_called()


def test_ensure_contact_for_email_skips_self_email():
    """Le sender = l'email du compte → on ne doit pas créer un contact "soi-même"."""
    from app.services.sync_service import SyncService

    svc = SyncService()
    contact_repo = MagicMock()
    std_email = MagicMock()
    std_email.sender = None
    std_email.to = ["owner@example.com"]
    std_email.cc = []

    account = MagicMock()
    account.email = "owner@example.com"
    account.id = 1

    svc._ensure_contact_for_email(contact_repo, std_email, account, is_sent=True)

    # owner@example.com est self → aucun get_or_create attendu.
    contact_repo.get_or_create.assert_not_called()


def test_ensure_contact_for_email_handles_sent_recipients():
    """Sur un sent email, chaque recipient (To+CC) qui n'est pas self doit
    être créé."""
    from app.services.sync_service import SyncService

    svc = SyncService()
    contact_repo = MagicMock()
    std_email = MagicMock()
    std_email.sender = None
    std_email.to = ["alice@example.com", "Bob <bob@example.com>"]
    std_email.cc = ["carol@example.com"]

    account = MagicMock()
    account.email = "owner@example.com"
    account.id = 1

    svc._ensure_contact_for_email(contact_repo, std_email, account, is_sent=True)

    # 3 contacts uniques, tous différents de owner@example.com.
    assert contact_repo.get_or_create.call_count == 3
    contact_repo.increment_email_count.assert_not_called()


def test_ensure_contact_for_email_swallows_repo_errors():
    """Un crash dans contact_repo NE DOIT PAS bloquer la sync — log silencieux."""
    from app.services.sync_service import SyncService

    svc = SyncService()
    contact_repo = MagicMock()
    contact_repo.get_or_create.side_effect = RuntimeError("DB locked")

    std_email = MagicMock()
    std_email.sender = "alice@example.com"
    std_email.sender_name = None
    std_email.to = []
    std_email.cc = []

    account = MagicMock()
    account.id = 1
    account.email = "owner@example.com"

    # Ne doit pas raise.
    svc._ensure_contact_for_email(contact_repo, std_email, account, is_sent=False)


# ---------------------------------------------------------------------------
# P1-A4 — auth backoff eviction on deletion


def test_evict_auth_backoff_drops_entry():
    from app.services.sync_service import SyncService

    svc = SyncService()
    svc._auth_backoff[42] = (3, 1234567.0, 1234567.0)

    assert svc.evict_auth_backoff(42) is True
    assert 42 not in svc._auth_backoff


def test_evict_auth_backoff_returns_false_on_missing():
    from app.services.sync_service import SyncService

    svc = SyncService()
    assert svc.evict_auth_backoff(999) is False


# ---------------------------------------------------------------------------
# P1-A5 — Outlook 429 throttle helpers


def test_is_throttle_error_recognises_signals():
    from app.providers.outlook_adapter import OutlookAdapter

    adapter = OutlookAdapter.__new__(OutlookAdapter)  # bypass __init__

    # Cas 1 : status_code attr = 429
    err1 = type("APIErr", (Exception,), {})()
    err1.status_code = 429
    assert adapter._is_throttle_error(err1) is True

    # Cas 2 : response_status_code attr = 429
    err2 = type("APIErr2", (Exception,), {})()
    err2.response_status_code = 429
    assert adapter._is_throttle_error(err2) is True

    # Cas 3 : message contenant "429"
    assert adapter._is_throttle_error(Exception("HTTP 429 Too Many Requests")) is True
    # Cas 4 : message "throttled"
    assert adapter._is_throttle_error(Exception("Service is throttled")) is True
    # Cas négatif
    assert adapter._is_throttle_error(Exception("500 Internal Server Error")) is False
    assert adapter._is_throttle_error(ValueError("bad payload")) is False


def test_retry_after_seconds_extracts_from_headers_and_message():
    from app.providers.outlook_adapter import OutlookAdapter

    adapter = OutlookAdapter.__new__(OutlookAdapter)

    # Cas 1 : Retry-After dans response_headers
    err1 = type("E", (Exception,), {})()
    err1.response_headers = {"Retry-After": "45"}
    assert adapter._retry_after_seconds(err1) == 45.0

    # Cas 2 : header lowercase
    err2 = type("E", (Exception,), {})()
    err2.headers = {"retry-after": "12"}
    assert adapter._retry_after_seconds(err2) == 12.0

    # Cas 3 : extraction depuis le message texte
    err3 = Exception("Throttled — retry after: 30 seconds")
    assert adapter._retry_after_seconds(err3) == 30.0

    # Cas 4 : aucun signal → default
    err4 = Exception("plain error")
    assert adapter._retry_after_seconds(err4, default=99.0) == 99.0

    # Cas 5 : Retry-After plafonné par _OUTLOOK_MAX_RETRY_AFTER
    from app.providers.outlook_adapter import _OUTLOOK_MAX_RETRY_AFTER
    err5 = type("E", (Exception,), {})()
    err5.response_headers = {"Retry-After": str(_OUTLOOK_MAX_RETRY_AFTER + 100)}
    assert adapter._retry_after_seconds(err5) == _OUTLOOK_MAX_RETRY_AFTER


# ---------------------------------------------------------------------------
# P2 — backoff log noise


def test_backoff_clear_log_level_depends_on_failure_count():
    """Un seul échec → debug. Multi-échecs → info "recovered".

    Sentinel : on grep la source de SyncService._perform_sync pour vérifier
    la présence de la condition. Test fragile au refactor mais utile pour
    Codex demain — preuve que le fix n'a pas été reverté.
    """
    import inspect
    from app.services.sync_service import SyncService

    src = inspect.getsource(SyncService._perform_sync)
    assert "_prev_failures >= 2" in src, (
        "log noise reduction missing — fix should gate `recovered` log on >= 2 failures"
    )
    assert "Backoff cleared" in src or "recovered" in src.lower(), (
        "backoff clear log message should still exist"
    )


# ---------------------------------------------------------------------------
# P2 — Gmail watch scheduler


def test_gmail_watch_scheduler_skips_when_no_topic(monkeypatch, caplog):
    """Sans GMAIL_PUSH_TOPIC, le scheduler skip silencieusement (pas de crash)."""
    from app.services.gmail_watch_scheduler import GmailWatchScheduler

    monkeypatch.delenv("GMAIL_PUSH_TOPIC", raising=False)
    monkeypatch.delenv("GMAIL_PUBSUB_TOPIC", raising=False)
    sched = GmailWatchScheduler()

    with caplog.at_level(logging.DEBUG, logger="app.services.gmail_watch_scheduler"):
        # Pas besoin de DB : on skip avant d'y accéder.
        sched._renew_due()

    assert any("GMAIL_PUSH_TOPIC not set" in rec.message for rec in caplog.records)


def test_gmail_watch_scheduler_start_stop_lifecycle():
    """start() lance le thread, stop() le termine proprement."""
    from app.services.gmail_watch_scheduler import GmailWatchScheduler

    sched = GmailWatchScheduler()
    sched.start()
    assert sched._thread is not None
    assert sched._thread.is_alive()

    sched.stop()
    sched._thread.join(timeout=2)
    assert not sched._thread.is_alive()


# ---------------------------------------------------------------------------
# C-2 — pending draft cache cross-account isolation


def test_pending_draft_cache_keyed_per_account():
    """Le cache _pending_draft_ids_cache doit être keyed par account_id —
    deux comptes ne partagent pas leur set d'email_ids.

    On test la sémantique du cache directement (cache hit path) plutôt que
    de re-monter toute la chaine store + DB cross-reference.
    """
    import time as _t
    from app.api import routes_emails as re_mod

    # Reset le cache (state global du module) avant le test.
    re_mod._pending_draft_ids_cache.clear()

    now = _t.time()
    re_mod._pending_draft_ids_cache[1] = {
        "ids": {"email-a-1", "email-a-2"},
        "timestamp": now,
    }
    re_mod._pending_draft_ids_cache[2] = {
        "ids": {"email-b-1"},
        "timestamp": now,
    }

    ids_a = re_mod._get_pending_draft_email_ids(account_id=1)
    ids_b = re_mod._get_pending_draft_email_ids(account_id=2)

    assert ids_a == {"email-a-1", "email-a-2"}, "account 1 must see its own cached IDs"
    assert ids_b == {"email-b-1"}, "account 2 must see its own cached IDs"
    assert "email-b-1" not in ids_a, "no cross-account leak A→B"
    assert "email-a-1" not in ids_b, "no cross-account leak B→A"

    # Cleanup pour ne pas polluer les tests suivants.
    re_mod._pending_draft_ids_cache.clear()


# ---------------------------------------------------------------------------
# C-3 — smart_routing draft cache cross-account isolation


def test_smart_routing_draft_cache_keyed_per_account(tmp_path, monkeypatch):
    """Deux comptes avec le même email_id (collision UID IMAP) ne doivent
    pas partager le draft mis en cache."""
    from app import smart_routing as sr_mod

    # Force le cache disque dans tmp_path pour pas polluer le ~/.agentys.
    monkeypatch.setattr(sr_mod, "_get_cache_path",
                        lambda: str(tmp_path / "draft_cache.json"))
    sr_mod._draft_cache.clear()

    # Cache une réponse pour (account=1, email=X) puis lis avec account=2.
    sr_mod._cache_draft("UID-12345", "DRAFT-A", account_id=1)

    cached_for_1 = sr_mod._get_cached_draft("UID-12345", account_id=1)
    cached_for_2 = sr_mod._get_cached_draft("UID-12345", account_id=2)

    assert cached_for_1 == "DRAFT-A", "owner sees its own cached draft"
    assert cached_for_2 is None, (
        "different account with same email_id must NOT see cross-account draft"
    )
