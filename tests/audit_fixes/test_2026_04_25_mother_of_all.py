# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fixes — 2026-04-25 mother-of-all report.

Couvre les 5 fixes ajoutés ce soir au-dessus du WIP existant :

- **P0-A1** (sync_service historyId checkpoint persistence on partial failure)
  → ``test_sync_persists_history_id_when_store_emails_fails``

- **P0-A2** (sync_service 401 mid-fetch triggers single re-auth retry)
  → ``test_fetch_with_retry_reauths_on_401_class_error``,
    ``test_is_auth_expired_error_recognises_common_signals``

- **P0-4** (routes_drafts /refine try-acquire prevents concurrent generations)
  → ``test_refining_lock_blocks_concurrent_acquire``,
    ``test_refining_lock_release_allows_subsequent_acquire``

- **P1-1** (daemon _failed_draft_counts TTL eviction)
  → ``test_failed_draft_counts_evicts_old_entries``,
    ``test_failed_draft_counts_keeps_fresh_entries``

Run: ``pytest tests/audit_fixes/test_2026_04_25_mother_of_all.py -v``
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# P0-A2 — _is_auth_expired_error heuristics


def test_is_auth_expired_error_recognises_common_signals():
    from app.services.sync_service import _is_auth_expired_error

    # Cas 1 : googleapiclient HttpError-like (objet avec .resp.status)
    err1 = type("Httperr", (Exception,), {})()
    err1.resp = type("Resp", (), {"status": 401})()
    assert _is_auth_expired_error(err1) is True

    # Cas 2 : msgraph HttpResponseError-like (status_code attr)
    err2 = type("GraphErr", (Exception,), {})()
    err2.status_code = 401
    assert _is_auth_expired_error(err2) is True

    # Cas 3 : RefreshError par nom de classe
    RefreshError = type("RefreshError", (Exception,), {})
    assert _is_auth_expired_error(RefreshError("token revoked")) is True

    # Cas 4 : RuntimeError du _ensure_authenticated (cooldown)
    assert _is_auth_expired_error(
        RuntimeError("Authentification Gmail en cooldown (60s)")
    ) is True

    # Cas 5 : message contenant "401" / "Unauthorized" / "invalid_grant"
    assert _is_auth_expired_error(Exception("Server returned 401")) is True
    assert _is_auth_expired_error(Exception("Unauthorized request")) is True
    assert _is_auth_expired_error(Exception("invalid_grant: refresh expired")) is True

    # Cas 6 : Google renvoie 403 quand l'utilisateur n'a pas accordé tous les scopes.
    err3 = type("ScopeErr", (Exception,), {})(
        "Request had insufficient authentication scopes."
    )
    err3.resp = type("Resp", (), {"status": 403})()
    assert _is_auth_expired_error(err3) is True

    # Cas négatifs — ne doivent PAS être considérés comme auth-expired
    assert _is_auth_expired_error(Exception("connection reset by peer")) is False
    assert _is_auth_expired_error(ValueError("bad payload")) is False
    assert _is_auth_expired_error(Exception("500 Internal Server Error")) is False


def test_fetch_with_retry_reauths_on_401_class_error():
    """Un 401 mid-fetch doit déclencher un appel à adapter.authenticate()
    suivi d'un retry unique. Le test vérifie aussi que SI le retry réussit,
    on retourne le résultat — pas l'erreur."""
    from app.services.sync_service import SyncService

    service = SyncService()

    adapter = MagicMock()
    adapter.provider_name = "gmail"
    # 1er appel get_messages → 401, 2ème appel → succès
    err_401 = Exception("HTTP 401 Unauthorized")
    adapter.get_messages.side_effect = [err_401, [MagicMock(), MagicMock()]]
    adapter.authenticate.return_value = True

    result = service._fetch_emails_with_retry(adapter, since=None)

    assert len(result) == 2, "second attempt should return the email list"
    assert adapter.authenticate.call_count == 1, "must reauth exactly once"
    assert adapter.get_messages.call_count == 2, "must retry once after reauth"


def test_fetch_with_retry_does_not_reauth_on_non_auth_error():
    """Une erreur non-auth (ex: timeout réseau) doit propager sans tenter de re-auth."""
    from app.services.sync_service import SyncService

    service = SyncService()
    adapter = MagicMock()
    adapter.provider_name = "gmail"
    adapter.get_messages.side_effect = TimeoutError("network timeout")

    with pytest.raises(TimeoutError):
        service._fetch_emails_with_retry(adapter, since=None)
    assert adapter.authenticate.call_count == 0, "no reauth on non-auth errors"


def test_fetch_with_retry_reauth_failure_propagates():
    """Si la re-auth elle-même échoue, on doit propager l'exception (pas le swallow)."""
    from app.services.sync_service import SyncService

    service = SyncService()
    adapter = MagicMock()
    adapter.provider_name = "gmail"
    adapter.get_messages.side_effect = Exception("HTTP 401 Unauthorized")
    adapter.authenticate.return_value = False  # re-auth fails

    with pytest.raises(RuntimeError, match="Re-auth returned False"):
        service._fetch_emails_with_retry(adapter, since=None)


# ---------------------------------------------------------------------------
# P0-A1 (ANNULÉ par audit 2026-06-11 B-01) — checkpoint delta sur échec partiel
#
# L'ancien fix P0-A1 persistait le history_id dans l'except du bloc delta.
# B-01 a montré que c'était une perte silencieuse d'emails : update_sync_time()
# bump last_sync_at en effet de bord, donc le fallback timestamp lisait
# « maintenant » et ne re-fetchait jamais le batch fetché-mais-non-stocké.
# Le contrat actuel : `fallback_since` est capturé AVANT le bloc delta et
# AUCUN checkpoint n'est persisté dans l'except. Les tests comportementaux
# vivent dans tests/services (régression B-01) ; ici on garde le proof of
# presence anti-revert.


def test_sync_delta_failure_does_not_advance_checkpoint(monkeypatch, tmp_path):
    """Sanity check : `fallback_since` est capturé avant le delta et le
    persist prématuré du checkpoint dans l'except a bien disparu.

    On ne mock pas tout le sync — on grep le source pour vérifier que le
    fix n'a pas été reverté. Test fragile au refactor mais utile comme
    proof of presence.
    """
    import inspect
    from app.services import sync_service

    src = inspect.getsource(sync_service.SyncService._sync_account)
    # Capture du point de reprise AVANT le bloc delta (audit 2026-06-11 B-01).
    assert "fallback_since = account.last_sync_at" in src, (
        "fallback_since capture before delta block missing"
    )
    assert "since = fallback_since" in src, (
        "timestamp fallback must resume from the pre-delta checkpoint"
    )
    # Le commentaire-ancre du fix est aussi un signal qu'on n'a pas perdu
    # l'intention au refactor.
    assert "B-01" in src, "B-01 anchor comment missing (fix possibly reverted)"


# ---------------------------------------------------------------------------
# P0-4 — refining lock try_acquire pattern


def test_refining_lock_blocks_concurrent_acquire(tmp_path):
    """Deux try_acquire successifs sur le même draft : le 2ème échoue."""
    from app.infrastructure.pending_draft_store import InMemoryPendingDraftStore

    store = InMemoryPendingDraftStore(persist_path=str(tmp_path / "drafts.json"))
    draft_id = "draft-abc-123"

    first = store.try_acquire_refining_lock(draft_id)
    second = store.try_acquire_refining_lock(draft_id)

    assert first is True, "first acquire must succeed"
    assert second is False, "second acquire must fail without release"


def test_refining_lock_release_allows_subsequent_acquire(tmp_path):
    """Après release, un nouveau try_acquire doit réussir."""
    from app.infrastructure.pending_draft_store import InMemoryPendingDraftStore

    store = InMemoryPendingDraftStore(persist_path=str(tmp_path / "drafts.json"))
    draft_id = "draft-xyz-456"

    assert store.try_acquire_refining_lock(draft_id) is True
    store.release_refining_lock(draft_id)
    assert store.try_acquire_refining_lock(draft_id) is True, (
        "should re-acquire after release"
    )


def test_refining_lock_independent_per_draft(tmp_path):
    """Deux drafts différents ne se bloquent pas mutuellement."""
    from app.infrastructure.pending_draft_store import InMemoryPendingDraftStore

    store = InMemoryPendingDraftStore(persist_path=str(tmp_path / "drafts.json"))

    assert store.try_acquire_refining_lock("draft-A") is True
    assert store.try_acquire_refining_lock("draft-B") is True, (
        "different drafts must not contend for the same lock"
    )


def test_refining_lock_release_is_idempotent(tmp_path):
    """release sans acquire préalable ne doit pas raise."""
    from app.infrastructure.pending_draft_store import InMemoryPendingDraftStore

    store = InMemoryPendingDraftStore(persist_path=str(tmp_path / "drafts.json"))
    # Aucun acquire — release silencieux attendu.
    store.release_refining_lock("never-acquired")

    # Acquire puis double release ne raise pas non plus.
    store.try_acquire_refining_lock("d1")
    store.release_refining_lock("d1")
    store.release_refining_lock("d1")  # second release : no-op


# ---------------------------------------------------------------------------
# P1-1 — daemon _failed_draft_counts TTL eviction


def test_failed_draft_counts_evicts_old_entries():
    """Les entrées >7j (par défaut) doivent être supprimées."""
    import time as _t
    from app.daemon import EmailDaemon

    daemon = EmailDaemon(provider=MagicMock())

    now = _t.time()
    eight_days_ago = now - (8 * 86400)
    one_day_ago = now - 86400

    daemon._failed_draft_counts = {
        "old-email": (3, eight_days_ago),
        "fresh-email": (1, one_day_ago),
    }

    evicted = daemon._evict_failed_draft_counts(ttl_days=7)

    assert evicted == 1, "exactly one entry should be evicted"
    assert "old-email" not in daemon._failed_draft_counts
    assert "fresh-email" in daemon._failed_draft_counts


def test_failed_draft_counts_keeps_fresh_entries():
    """Aucune entrée fresh ne doit être touchée."""
    import time as _t
    from app.daemon import EmailDaemon

    daemon = EmailDaemon(provider=MagicMock())
    now = _t.time()
    daemon._failed_draft_counts = {
        f"email-{i}": (1, now - i * 3600) for i in range(5)
    }

    evicted = daemon._evict_failed_draft_counts(ttl_days=7)

    assert evicted == 0, "nothing should be evicted within TTL"
    assert len(daemon._failed_draft_counts) == 5


def test_failed_draft_counts_evicts_with_custom_ttl():
    """Le ttl_days configurable doit être respecté."""
    import time as _t
    from app.daemon import EmailDaemon

    daemon = EmailDaemon(provider=MagicMock())
    now = _t.time()
    daemon._failed_draft_counts = {
        "two-days": (1, now - 2 * 86400),
        "five-hours": (1, now - 5 * 3600),
    }

    # TTL d'1 jour → seul "five-hours" survit.
    evicted = daemon._evict_failed_draft_counts(ttl_days=1)
    assert evicted == 1
    assert "two-days" not in daemon._failed_draft_counts
    assert "five-hours" in daemon._failed_draft_counts


def test_failed_draft_counts_legacy_int_format_safe():
    """Les entrées legacy int (avant migration tuple) ne doivent pas crasher."""
    from app.daemon import EmailDaemon

    daemon = EmailDaemon(provider=MagicMock())
    daemon._failed_draft_counts = {"legacy": 2}  # ancien format int

    # L'éviction filtre par isinstance(tuple, ...) → l'entrée int est ignorée
    # silencieusement (ni évincée ni crashée). Sur le prochain access, le
    # caller normalise via la branche isinstance(_entry, int) du retry path.
    evicted = daemon._evict_failed_draft_counts(ttl_days=7)
    assert evicted == 0, "int legacy entries should be skipped, not crashed"
    assert "legacy" in daemon._failed_draft_counts
