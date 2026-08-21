"""Tests for the Gmail Pub/Sub push handler (N3)."""
import base64
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from app.api import gmail_push as gp


@pytest.fixture(autouse=True)
def _restore_env():
    saved = {k: os.environ.get(k) for k in (
        gp.PUSH_AUDIENCE_ENV, gp.PUSH_SERVICE_ACCOUNT_ENV, gp.DEFAULT_TOPIC_ENV,
    )}
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_decode_pubsub_payload_happy_path():
    payload = {"emailAddress": "user@example.com", "historyId": 12345}
    envelope = {
        "message": {
            "data": base64.b64encode(json.dumps(payload).encode()).decode()
        }
    }
    assert gp._decode_pubsub_payload(envelope) == payload


def test_decode_pubsub_payload_missing_data():
    assert gp._decode_pubsub_payload({"message": {}}) is None
    assert gp._decode_pubsub_payload({}) is None


def test_decode_pubsub_payload_invalid_base64():
    envelope = {"message": {"data": "!!!not-base64!!!"}}
    assert gp._decode_pubsub_payload(envelope) is None


def test_verify_pubsub_jwt_rejects_missing_audience(caplog):
    os.environ.pop(gp.PUSH_AUDIENCE_ENV, None)
    assert gp._verify_pubsub_jwt("Bearer token") is None


def test_verify_pubsub_jwt_rejects_missing_bearer():
    os.environ[gp.PUSH_AUDIENCE_ENV] = "https://example.com/api/gmail/push"
    assert gp._verify_pubsub_jwt(None) is None
    assert gp._verify_pubsub_jwt("Basic xxxxx") is None


def test_verify_pubsub_jwt_returns_claims_on_success():
    os.environ[gp.PUSH_AUDIENCE_ENV] = "https://example.com/api/gmail/push"
    os.environ[gp.PUSH_SERVICE_ACCOUNT_ENV] = "agentys-pubsub@example.iam.gserviceaccount.com"
    fake_claims = {"email": "agentys-pubsub@example.iam.gserviceaccount.com", "iss": "google"}
    with patch("google.oauth2.id_token.verify_oauth2_token", return_value=fake_claims):
        assert gp._verify_pubsub_jwt("Bearer abc.def.ghi") == fake_claims


def test_verify_pubsub_jwt_rejects_wrong_service_account():
    os.environ[gp.PUSH_AUDIENCE_ENV] = "https://example.com/api/gmail/push"
    os.environ[gp.PUSH_SERVICE_ACCOUNT_ENV] = "expected@example.iam.gserviceaccount.com"
    fake_claims = {"email": "intruder@evil.com", "iss": "google"}
    with patch("google.oauth2.id_token.verify_oauth2_token", return_value=fake_claims):
        assert gp._verify_pubsub_jwt("Bearer abc.def.ghi") is None


def test_verify_pubsub_jwt_rejects_invalid_signature():
    os.environ[gp.PUSH_AUDIENCE_ENV] = "https://example.com/api/gmail/push"
    with patch(
        "google.oauth2.id_token.verify_oauth2_token",
        side_effect=ValueError("bad signature"),
    ):
        assert gp._verify_pubsub_jwt("Bearer bogus") is None


def test_trigger_history_sync_unknown_account_returns_ignored():
    fake_session = MagicMock()
    fake_session.query.return_value.filter.return_value.first.return_value = None
    with patch("app.api.gmail_push.get_session", return_value=fake_session):
        result = gp._trigger_history_sync("nobody@example.com", "42")
    assert result == {"status": "ignored", "reason": "unknown_account"}
    fake_session.close.assert_called_once()


def test_trigger_history_sync_returns_error_without_checkpoint_when_no_service():
    """B-07 (audit 2026-06-11) — adapté : l'ancien comportement épinglé ici
    stockait last_history_id sans avoir syncé (le delta suivant sautait le
    message poussé). Désormais : checkpoint INTACT + status 'error' pour que
    le handler réponde 5xx et que Pub/Sub redélivre."""
    fake_account = MagicMock()
    fake_account.id = 7
    fake_account.email = "user@example.com"
    fake_account.last_history_id = "previous-checkpoint"
    fake_session = MagicMock()
    fake_session.query.return_value.filter.return_value.first.return_value = fake_account
    with patch("app.api.gmail_push.get_session", return_value=fake_session):
        with patch(
            "app.services.sync_jobs.enqueue_sync_job",
            side_effect=RuntimeError("queue unavailable"),
        ):
            with patch(
                "app.services.sync_service.get_sync_service",
                side_effect=Exception("no sync service"),
            ):
                result = gp._trigger_history_sync("user@example.com", "99")
    assert result == {"status": "error", "reason": "sync_unavailable"}
    assert fake_account.last_history_id == "previous-checkpoint"  # unchanged
    fake_session.commit.assert_not_called()


def test_trigger_history_sync_enqueues_targeted_sync_job():
    fake_account = MagicMock()
    fake_account.id = 3
    fake_account.email = "user@example.com"
    fake_account.user_id = 11
    # Starting state — last_history_id MUST stay untouched so the queued job can
    # delta-fetch from it. The push's historyId is only a "something changed"
    # signal, not the checkpoint.
    fake_account.last_history_id = "previous-checkpoint"
    fake_session = MagicMock()
    fake_session.query.return_value.filter.return_value.first.return_value = fake_account
    queued_job = {
        "id": "job-123",
        "status": "queued",
        "coalesced": False,
    }
    with patch("app.api.gmail_push.get_session", return_value=fake_session):
        with patch(
            "app.services.sync_jobs.enqueue_sync_job",
            return_value=queued_job,
        ) as enqueue:
            with patch("app.services.sync_service.get_sync_service") as get_service:
                result = gp._trigger_history_sync("user@example.com", "99")
            get_service.assert_not_called()
    assert result == {"status": "ok", "job_id": "job-123", "coalesced": False}
    assert fake_account.last_history_id == "previous-checkpoint"
    enqueue.assert_called_once_with(
        account_id=3,
        folder="inbox",
        limit=50,
        unread_only=False,
        user_id=11,
        source="gmail_push",
    )
    fake_session.commit.assert_not_called()


def test_trigger_history_sync_falls_back_to_sync_service_when_queue_unavailable():
    fake_account = MagicMock()
    fake_account.id = 3
    fake_account.email = "user@example.com"
    # Starting state — last_history_id MUST stay untouched so SyncService can
    # delta-fetch from it. The push's historyId is only a "something changed"
    # signal, not the checkpoint.
    fake_account.last_history_id = "previous-checkpoint"
    fake_session = MagicMock()
    fake_session.query.return_value.filter.return_value.first.return_value = fake_account
    fake_svc = MagicMock()
    with patch("app.api.gmail_push.get_session", return_value=fake_session):
        with patch(
            "app.services.sync_jobs.enqueue_sync_job",
            side_effect=RuntimeError("queue unavailable"),
        ):
            with patch("app.services.sync_service.get_sync_service", return_value=fake_svc):
                result = gp._trigger_history_sync("user@example.com", "42")
    assert result == {"status": "ok"}
    assert fake_account.last_history_id == "previous-checkpoint"  # unchanged
    fake_svc.trigger_account_sync.assert_called_once_with(3)
    fake_svc.trigger_sync.assert_not_called()


# ---------------------------------------------------------------------------
# Auto-enrolment of the Gmail watch on OAuth connect (2026-07).
#
# Bug: start_watch() was only ever called by the renew-due cron and the manual
# HTTP endpoint. A freshly-connected Gmail account had NO watch until the daily
# cron picked it up (up to 24h) — and prod showed watch_null accounts stuck on
# polling. enroll_gmail_watch_async wires enrolment into the OAuth success path.


class _ImmediateThread:
    """Runs the thread target synchronously so async enrolment is testable."""

    def __init__(self, target=None, daemon=None, name=None):
        self._target = target

    def start(self):
        if self._target:
            self._target()


def test_enroll_watch_async_noop_without_topic(monkeypatch):
    monkeypatch.delenv(gp.DEFAULT_TOPIC_ENV, raising=False)
    with patch.object(gp.threading, "Thread") as mock_thread:
        gp.enroll_gmail_watch_async("user@example.com")
    mock_thread.assert_not_called()


def test_enroll_watch_async_enrolls_and_persists(monkeypatch):
    monkeypatch.setenv(gp.DEFAULT_TOPIC_ENV, "projects/test/topics/agentys-gmail")

    account = MagicMock()
    account.provider = "gmail"
    account.email = "user@example.com"

    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = account

    adapter = MagicMock()
    adapter.authenticate.return_value = True
    adapter.start_watch.return_value = {"expiration": "1893456000000", "historyId": "999"}

    with patch.object(gp, "get_session", return_value=session), \
         patch("app.providers.gmail_adapter.GmailAdapter", return_value=adapter), \
         patch.object(gp.threading, "Thread", _ImmediateThread):
        gp.enroll_gmail_watch_async("user@example.com")

    adapter.start_watch.assert_called_once()
    assert account.gmail_watch_topic == "projects/test/topics/agentys-gmail"
    assert account.last_history_id == "999"
    assert account.gmail_watch_expiration is not None
    session.commit.assert_called_once()


def test_enroll_watch_async_ignores_non_gmail_account(monkeypatch):
    monkeypatch.setenv(gp.DEFAULT_TOPIC_ENV, "projects/test/topics/agentys-gmail")
    account = MagicMock()
    account.provider = "outlook"
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = account
    adapter = MagicMock()
    with patch.object(gp, "get_session", return_value=session), \
         patch("app.providers.gmail_adapter.GmailAdapter", return_value=adapter), \
         patch.object(gp.threading, "Thread", _ImmediateThread):
        gp.enroll_gmail_watch_async("user@example.com")
    adapter.start_watch.assert_not_called()
    session.commit.assert_not_called()


def test_enroll_watch_async_swallows_errors(monkeypatch):
    monkeypatch.setenv(gp.DEFAULT_TOPIC_ENV, "projects/test/topics/agentys-gmail")
    with patch.object(gp, "get_session", side_effect=RuntimeError("boom")), \
         patch.object(gp.threading, "Thread", _ImmediateThread):
        # Must not raise — best-effort enrolment.
        gp.enroll_gmail_watch_async("user@example.com")


def test_oauth_success_paths_wire_watch_enrolment():
    """Both Gmail OAuth success handlers (callback + complete) must call
    enroll_gmail_watch_async so a new account gets push immediately."""
    import app.api.oauth as oauth
    src = open(oauth.__file__, encoding="utf-8").read()
    assert src.count("enroll_gmail_watch_async(") >= 2


# ---------------------------------------------------------------------------
# Révocation OAuth hors de l'app (2026-08-07).
#
# Bug : le cron « Gmail watch renew » a échoué 12 jours d'affilée sur 2 comptes
# dont le refresh token était mort. `authenticate()` renvoyant un simple False,
# l'endpoint traitait une révocation définitive comme une panne transitoire →
# alarme rouge en permanence, donc incapable de signaler une vraie panne, et
# sync_service continuait à poller des comptes sans token toutes les 2 min.


def _account_stub(account_id=19, email="dead@example.com"):
    account = MagicMock()
    account.id = account_id
    account.email = email
    account.is_active = True
    account.last_history_id = "12345"
    account.gmail_watch_expiration = None
    account.gmail_watch_topic = "projects/test/topics/old"
    return account


def _renew_with(monkeypatch, adapter, account, tokens_result):
    """Exécute le renouvellement avec un seul compte dû et un adapter donné."""
    monkeypatch.setenv(gp.DEFAULT_TOPIC_ENV, "projects/test/topics/agentys-gmail")
    session = MagicMock()
    session.query.return_value.filter.return_value.filter.return_value.filter.return_value.all.return_value = [account]

    get_tokens = MagicMock(**tokens_result)
    with patch.object(gp, "get_session", return_value=session), \
         patch("app.providers.gmail_adapter.GmailAdapter", return_value=adapter), \
         patch("app.api.oauth.get_tokens_server", get_tokens):
        payload, status = gp._renew_due_watches_payload()
    return payload, status, session


def test_revoked_account_is_deactivated_not_reported_as_failure(monkeypatch):
    """invalid_grant = l'utilisateur a retiré l'accès : aucun retry ne répare.

    Le compte sort du périmètre au lieu de faire rougir le cron chaque nuit.
    """
    adapter = MagicMock()
    adapter.authenticate.return_value = False
    adapter.auth_failure_reason = "Refresh token révoqué (invalid_grant). Reconnectez..."
    account = _account_stub()

    payload, status, session = _renew_with(
        monkeypatch, adapter, account, {"return_value": {"refresh_token": "stale"}}
    )

    assert status == 200
    assert payload["failed"] == []
    assert [d["account_id"] for d in payload["deactivated"]] == [19]
    # Même remise à zéro que la déconnexion explicite (oauth.py) : sans ça,
    # sync_service poursuit son polling et last_history_id sera rejoué.
    assert account.is_active is False
    assert account.last_history_id is None
    assert account.gmail_watch_topic is None
    session.commit.assert_called_once()


def test_account_without_any_token_is_deactivated(monkeypatch):
    """Plus aucun token en base : rien à rafraîchir, état tout aussi terminal."""
    adapter = MagicMock()
    adapter.authenticate.return_value = False
    adapter.auth_failure_reason = "Authentification impossible. Fournissez credentials.json"
    account = _account_stub(account_id=20)

    payload, _, _ = _renew_with(monkeypatch, adapter, account, {"return_value": None})

    assert payload["failed"] == []
    assert [d["account_id"] for d in payload["deactivated"]] == [20]
    assert account.is_active is False


def test_transient_auth_failure_still_fails_the_cron(monkeypatch):
    """Un 5xx Google ne doit PAS désactiver le compte.

    C'est le garde-fou : sinon un incident Google désactiverait tout le monde
    d'un coup, et l'alarme se tairait exactement quand elle est utile.
    """
    adapter = MagicMock()
    adapter.authenticate.return_value = False
    adapter.auth_failure_reason = "HttpError 503: Backend Error"
    account = _account_stub(account_id=21)

    payload, _, _ = _renew_with(
        monkeypatch, adapter, account, {"return_value": {"refresh_token": "valid"}}
    )

    assert payload["deactivated"] == []
    assert [f["account_id"] for f in payload["failed"]] == [21]
    assert account.is_active is True


def test_unreachable_token_store_does_not_deactivate(monkeypatch):
    """Store injoignable : on ne peut rien conclure, donc on ne désactive pas."""
    adapter = MagicMock()
    adapter.authenticate.return_value = False
    adapter.auth_failure_reason = "connection reset"
    account = _account_stub(account_id=22)

    payload, _, _ = _renew_with(
        monkeypatch, adapter, account, {"side_effect": RuntimeError("store down")}
    )

    assert payload["deactivated"] == []
    assert [f["account_id"] for f in payload["failed"]] == [22]
    assert account.is_active is True


def test_healthy_account_is_renewed(monkeypatch):
    """Non-régression : le chemin nominal reste intact."""
    adapter = MagicMock()
    adapter.authenticate.return_value = True
    adapter.start_watch.return_value = {"expiration": "1893456000000"}
    account = _account_stub(account_id=23)

    payload, _, _ = _renew_with(monkeypatch, adapter, account, {"return_value": {}})

    assert payload["failed"] == []
    assert payload["deactivated"] == []
    assert [r["account_id"] for r in payload["renewed"]] == [23]
    assert account.is_active is True


def test_adapter_exposes_auth_failure_reason():
    """Le cron lit la raison via une API publique, pas un attribut privé."""
    from app.providers.gmail_adapter import GmailAdapter
    assert isinstance(GmailAdapter.auth_failure_reason, property)


def test_renew_workflow_does_not_fail_on_deactivated_accounts():
    """Le workflow ne doit rougir que sur `failed`, jamais sur `deactivated`.

    Sinon on revient au point de départ : rouge tous les jours, donc ignoré.
    """
    src = open(".github/workflows/gmail-watch-renew.yml", encoding="utf-8").read()
    assert "DEACTIVATED_COUNT" in src
    assert '::warning::$DEACTIVATED_COUNT' in src
    # La seule sortie en erreur reste le compteur d'échecs réels.
    assert 'if [ "$FAILED_COUNT" != "0" ]; then' in src
    assert 'if [ "$DEACTIVATED_COUNT" != "0" ]; then\n            echo "::error' not in src
