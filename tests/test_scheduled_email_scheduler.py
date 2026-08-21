"""Tests pour le scheduler d'emails programmes.

Le scheduler boucle toutes les ~60s, recupere les rows due via
ScheduledEmailStore.list_due, charge le provider du compte concerne,
envoie l'email (compose ou reply), met a jour le status. Les tests
appellent _process_due() directement pour ne pas attendre 60s.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def store(tmp_path):
    from app.services.scheduled_email_store import ScheduledEmailStore

    return ScheduledEmailStore(db_path=str(tmp_path / "sched.db"))


@pytest.fixture()
def fake_account():
    acct = MagicMock()
    acct.id = "1"
    acct.email = "alex@example.com"
    return acct


def _payload(**overrides):
    base = {
        "to": ["bob@example.com"],
        "subject": "Hello",
        "body": "<p>Hi</p>",
        "cc": [],
        "bcc": [],
        "is_html": True,
        "reply_to_id": None,
        "thread_id": None,
        "attachments": [],
        "skip_signature": False,
        "signature_html": "",
        "ai_assisted": False,
        "from_name": None,
    }
    base.update(overrides)
    return base


def _make_provider_mock(*, send_new_id="msg-new-1", send_reply_id="msg-reply-1"):
    p = MagicMock()
    p.send_new_directly.return_value = send_new_id
    p.send_reply_directly.return_value = send_reply_id
    p.disconnect = MagicMock()
    return p


def _patch_account_loader(account):
    """Stub _load_account pour retourner un account fixe."""
    return patch(
        "app.services.scheduled_email_scheduler._load_account",
        return_value=account,
    )


def _patch_provider_factory(provider):
    # Updated for EMAIL-001 fix: scheduler now resolves the provider via
    # `self._make_provider(account)` (which goes through multi_accounts).
    # Patch the method directly so the test stays decoupled from that path.
    return patch(
        "app.services.scheduled_email_scheduler.ScheduledEmailScheduler._make_provider",
        return_value=provider,
    )


# ── tests d'envoi ──────────────────────────────────────────────────────────


def test_process_due_sends_new_email(store, fake_account):
    from app.services.scheduled_email_scheduler import ScheduledEmailScheduler

    sid = store.insert(
        account_id=1,
        payload=_payload(),
        send_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    provider = _make_provider_mock(send_new_id="msg-42")
    scheduler = ScheduledEmailScheduler(store=store)

    with _patch_account_loader(fake_account), _patch_provider_factory(provider):
        scheduler._process_due()

    provider.send_new_directly.assert_called_once()
    kwargs = provider.send_new_directly.call_args.kwargs
    assert kwargs["to"] == ["bob@example.com"]
    assert kwargs["subject"] == "Hello"
    assert kwargs["idempotency_key"] == f"agentys-scheduled-{sid}@agentys.local"

    row = store.get_by_id(sid)
    assert row["status"] == "sent"
    assert row["sent_message_id"] == "msg-42"


def test_recovered_sending_row_marks_sent_if_provider_finds_idempotency_key(
    store, fake_account
):
    """Crash recovery must not send a duplicate if Sent already has the message."""
    from app.services.scheduled_email_scheduler import ScheduledEmailScheduler

    sid = store.insert(
        account_id=1,
        payload=_payload(),
        send_at=datetime.now(timezone.utc) - timedelta(minutes=20),
    )
    assert store.claim_for_send(sid) is True
    # Fix racine du flip-flop (migration 043) : `updated_at < now - 0min` est
    # STRICT et la granularité d'horloge Windows (~15 ms) rendait deux now()
    # consécutifs parfois ÉGAUX → 0 récupéré → échec aléatoire. `now` est
    # désormais injectable : futur déterministe — supersède le time.sleep(0.02)
    # de mitigation qui flippait encore.
    future = datetime.now(timezone.utc) + timedelta(seconds=1)
    assert store.recover_stuck_sending(threshold_minutes=0, now=future) == 1

    provider = _make_provider_mock(send_new_id="duplicate-would-send")
    provider.find_sent_message_by_idempotency_key.return_value = "msg-already-sent"
    scheduler = ScheduledEmailScheduler(store=store)

    with _patch_account_loader(fake_account), _patch_provider_factory(provider):
        scheduler._process_due()

    provider.find_sent_message_by_idempotency_key.assert_called_once_with(
        f"agentys-scheduled-{sid}@agentys.local"
    )
    provider.send_new_directly.assert_not_called()
    row = store.get_by_id(sid)
    assert row["status"] == "sent"
    assert row["sent_message_id"] == "msg-already-sent"


def test_recovered_sending_row_fails_closed_without_sent_lookup(store, fake_account):
    """A post-crash retry without provider proof would risk duplicate delivery."""
    from app.services.scheduled_email_scheduler import ScheduledEmailScheduler

    sid = store.insert(
        account_id=1,
        payload=_payload(),
        send_at=datetime.now(timezone.utc) - timedelta(minutes=20),
    )
    assert store.claim_for_send(sid) is True
    # Même injection de `now` déterministe que le test précédent (fix 043).
    future = datetime.now(timezone.utc) + timedelta(seconds=1)
    assert store.recover_stuck_sending(threshold_minutes=0, now=future) == 1

    provider = _make_provider_mock(send_new_id="duplicate-would-send")
    del provider.find_sent_message_by_idempotency_key
    scheduler = ScheduledEmailScheduler(store=store)

    with _patch_account_loader(fake_account), _patch_provider_factory(provider):
        scheduler._process_due()

    provider.send_new_directly.assert_not_called()
    row = store.get_by_id(sid)
    assert row["status"] == "failed"
    assert "unknown delivery state" in row["error"]


def test_process_due_sends_reply_with_threading(store, fake_account):
    from app.services.scheduled_email_scheduler import ScheduledEmailScheduler

    payload = _payload(
        reply_to_id="orig-msg-99",
        thread_id="thread-7",
        subject="Re: Hello",
    )
    sid = store.insert(
        account_id=1,
        payload=payload,
        send_at=datetime.now(timezone.utc) - timedelta(minutes=2),
    )
    provider = _make_provider_mock(send_reply_id="msg-reply-77")
    scheduler = ScheduledEmailScheduler(store=store)

    with _patch_account_loader(fake_account), _patch_provider_factory(provider):
        scheduler._process_due()

    provider.send_reply_directly.assert_called_once()
    kwargs = provider.send_reply_directly.call_args.kwargs
    assert kwargs["reply_to_id"] == "orig-msg-99"
    assert kwargs["thread_id"] == "thread-7"
    assert kwargs["subject"] == "Re: Hello"

    row = store.get_by_id(sid)
    assert row["status"] == "sent"
    assert row["sent_message_id"] == "msg-reply-77"


def test_process_due_skips_future_rows(store, fake_account):
    from app.services.scheduled_email_scheduler import ScheduledEmailScheduler

    sid = store.insert(
        account_id=1,
        payload=_payload(),
        send_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    provider = _make_provider_mock()
    scheduler = ScheduledEmailScheduler(store=store)

    with _patch_account_loader(fake_account), _patch_provider_factory(provider):
        scheduler._process_due()

    provider.send_new_directly.assert_not_called()
    provider.send_reply_directly.assert_not_called()
    assert store.get_by_id(sid)["status"] == "pending"


def test_process_due_marks_failed_on_provider_none(store, fake_account):
    """Provider qui retourne None -> failure. Doit etre marque failed."""
    from app.services.scheduled_email_scheduler import ScheduledEmailScheduler

    sid = store.insert(
        account_id=1,
        payload=_payload(),
        send_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    provider = MagicMock()
    provider.send_new_directly.return_value = None
    provider.disconnect = MagicMock()
    scheduler = ScheduledEmailScheduler(store=store)

    with _patch_account_loader(fake_account), _patch_provider_factory(provider):
        scheduler._process_due()

    row = store.get_by_id(sid)
    assert row["status"] == "failed"


def test_process_due_marks_failed_when_account_missing(store):
    """Le compte n'existe plus -> on flag failed et on n'essaie pas d'envoyer."""
    from app.services.scheduled_email_scheduler import ScheduledEmailScheduler

    sid = store.insert(
        account_id=999,
        payload=_payload(),
        send_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    scheduler = ScheduledEmailScheduler(store=store)

    with patch(
        "app.services.scheduled_email_scheduler._load_account",
        return_value=None,
    ), patch(
        "app.services.scheduled_email_scheduler.ScheduledEmailScheduler._make_provider"
    ) as factory_mock:
        scheduler._process_due()
        factory_mock.assert_not_called()

    assert store.get_by_id(sid)["status"] == "failed"


def test_process_due_emits_websocket_event_on_send(store, fake_account):
    from app.services.scheduled_email_scheduler import ScheduledEmailScheduler

    sid = store.insert(
        account_id=1,
        payload=_payload(),
        send_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    provider = _make_provider_mock(send_new_id="msg-ws-1")
    scheduler = ScheduledEmailScheduler(store=store)

    with _patch_account_loader(fake_account), _patch_provider_factory(provider), patch(
        "app.services.scheduled_email_scheduler.emit_email_sent_scheduled"
    ) as ws_mock:
        scheduler._process_due()

    ws_mock.assert_called_once()
    # account_id explicite (lecon emit-from-bg-thread 2026-04-24)
    kwargs = ws_mock.call_args.kwargs
    assert kwargs.get("account_id") == 1
    assert kwargs.get("scheduled_id") == sid


def test_process_due_handles_cancelled_between_list_and_send(store, fake_account):
    """Race condition : row annulee apres list_due mais avant send.

    Le scheduler doit re-verifier le status au moment du send et skip
    silencieusement si plus pending.
    """
    from app.services.scheduled_email_scheduler import ScheduledEmailScheduler

    sid = store.insert(
        account_id=1,
        payload=_payload(),
        send_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    provider = _make_provider_mock()
    scheduler = ScheduledEmailScheduler(store=store)

    # Annule juste avant le _process_due (simule la race en patchant
    # list_due pour annuler entre la lecture et l'envoi).
    original_list_due = store.list_due

    def list_due_then_cancel(**kwargs):
        rows = original_list_due(**kwargs)
        store.cancel(sid)  # race : autre thread annule
        return rows

    with patch.object(store, "list_due", side_effect=list_due_then_cancel), \
         _patch_account_loader(fake_account), \
         _patch_provider_factory(provider):
        scheduler._process_due()

    provider.send_new_directly.assert_not_called()
    assert store.get_by_id(sid)["status"] == "cancelled"


def test_scheduler_lifecycle_start_stop():
    from app.services.scheduled_email_scheduler import ScheduledEmailScheduler

    scheduler = ScheduledEmailScheduler()
    scheduler.start()
    assert scheduler._thread is not None
    assert scheduler._thread.is_alive()
    scheduler.stop()
    # Apres stop, le thread doit avoir termine en moins de 5s
    assert not scheduler._thread.is_alive()


def test_start_idempotent_does_not_create_two_threads():
    from app.services.scheduled_email_scheduler import ScheduledEmailScheduler

    scheduler = ScheduledEmailScheduler()
    scheduler.start()
    first_thread = scheduler._thread
    scheduler.start()
    assert scheduler._thread is first_thread
    scheduler.stop()


# ── B-02 (audit 2026-06-11) : échec transitoire → revert_claim, pas failed ──


def test_transient_provider_load_failure_reverts_claim(store, fake_account):
    """Un provider qui ne charge pas (refresh OAuth, réseau) est transitoire :
    la row doit revenir en pending (revert_claim) pour retry au tick suivant,
    pas être marquée failed définitivement."""
    from app.services.scheduled_email_scheduler import ScheduledEmailScheduler

    sid = store.insert(
        account_id=1,
        payload=_payload(),
        send_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    scheduler = ScheduledEmailScheduler(store=store)

    with _patch_account_loader(fake_account), patch(
        "app.services.scheduled_email_scheduler.ScheduledEmailScheduler._make_provider",
        side_effect=RuntimeError("OAuth refresh failed"),
    ):
        scheduler._process_due()

    row = store.get_by_id(sid)
    assert row["status"] == "pending"
    assert row["attempts"] == 1  # claim_for_send a incrémenté, revert conserve


def test_provider_load_failure_exhausts_attempts_then_failed(store, fake_account):
    """Au-delà du cap MAX_SEND_ATTEMPTS, l'échec provider redevient terminal."""
    from app.services.scheduled_email_scheduler import (
        MAX_SEND_ATTEMPTS,
        ScheduledEmailScheduler,
    )

    sid = store.insert(
        account_id=1,
        payload=_payload(),
        send_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    # Simule MAX-1 tentatives précédentes (claim incrémente, revert conserve).
    for _ in range(MAX_SEND_ATTEMPTS - 1):
        assert store.claim_for_send(sid) is True
        store.revert_claim(sid)
    scheduler = ScheduledEmailScheduler(store=store)

    with _patch_account_loader(fake_account), patch(
        "app.services.scheduled_email_scheduler.ScheduledEmailScheduler._make_provider",
        side_effect=RuntimeError("OAuth refresh failed"),
    ):
        scheduler._process_due()

    row = store.get_by_id(sid)
    assert row["status"] == "failed"
    assert "Provider load" in row["error"]


def test_transient_network_error_during_send_reverts_claim(store, fake_account):
    """ConnectionError pendant l'envoi (premier attempt) → revert, pas failed."""
    from app.services.scheduled_email_scheduler import ScheduledEmailScheduler

    sid = store.insert(
        account_id=1,
        payload=_payload(),
        send_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    provider = _make_provider_mock()
    provider.send_new_directly.side_effect = ConnectionError("connection reset")
    scheduler = ScheduledEmailScheduler(store=store)

    with _patch_account_loader(fake_account), _patch_provider_factory(provider):
        scheduler._process_due()

    row = store.get_by_id(sid)
    assert row["status"] == "pending"
    assert row["attempts"] == 1


def test_validation_error_during_send_stays_terminal(store, fake_account):
    """Une erreur de validation (ex. pièce jointe corrompue → ValueError)
    n'est PAS transitoire : mark_failed dès le premier attempt."""
    from app.services.scheduled_email_scheduler import ScheduledEmailScheduler

    sid = store.insert(
        account_id=1,
        payload=_payload(),
        send_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    provider = _make_provider_mock()
    provider.send_new_directly.side_effect = ValueError("destinataire invalide")
    scheduler = ScheduledEmailScheduler(store=store)

    with _patch_account_loader(fake_account), _patch_provider_factory(provider):
        scheduler._process_due()

    row = store.get_by_id(sid)
    assert row["status"] == "failed"
    assert "destinataire invalide" in row["error"]


# ── dispatch_now (Send Now override) ───────────────────────────────────────


def test_dispatch_now_sends_pending_row_synchronously(store, fake_account):
    """Send Now bypasses the 60s poll: a pending row scheduled in the future
    is dispatched as soon as the user clicks the button."""
    from app.services.scheduled_email_scheduler import ScheduledEmailScheduler

    sid = store.insert(
        account_id=1,
        payload=_payload(),
        # Future send_at — list_due() would skip it. dispatch_now must not.
        send_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )
    provider = _make_provider_mock(send_new_id="msg-now-1")
    scheduler = ScheduledEmailScheduler(store=store)

    with _patch_account_loader(fake_account), _patch_provider_factory(provider):
        success, err = scheduler.dispatch_now(sid, account_id=1)

    assert success is True
    assert err is None
    provider.send_new_directly.assert_called_once()
    assert store.get_by_id(sid)["status"] == "sent"


def test_dispatch_now_rejects_non_pending_row(store, fake_account):
    from app.services.scheduled_email_scheduler import ScheduledEmailScheduler

    sid = store.insert(
        account_id=1,
        payload=_payload(),
        send_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    store.cancel(sid)
    scheduler = ScheduledEmailScheduler(store=store)

    success, err = scheduler.dispatch_now(sid, account_id=1)

    assert success is False
    assert err is not None and "cancelled" in err


def test_dispatch_now_scoped_per_account(store, fake_account):
    """A user can only send-now their own rows — wrong account_id returns introuvable."""
    from app.services.scheduled_email_scheduler import ScheduledEmailScheduler

    sid = store.insert(
        account_id=1,
        payload=_payload(),
        send_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    scheduler = ScheduledEmailScheduler(store=store)

    success, err = scheduler.dispatch_now(sid, account_id=999)

    assert success is False
    assert err == "introuvable"
    assert store.get_by_id(sid)["status"] == "pending"


def test_default_scheduler_singleton_roundtrip():
    from app.services.scheduled_email_scheduler import (
        ScheduledEmailScheduler,
        get_default_scheduler,
        set_default_scheduler,
    )

    custom = ScheduledEmailScheduler()
    set_default_scheduler(custom)
    assert get_default_scheduler() is custom
