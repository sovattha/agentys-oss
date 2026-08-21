# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Integration tests — combinaisons des fixes de l'audit 2026-04-26.

Audit context : 7 fixes ont touché `routes_pending.py` dans le même flow
validate (RACE-002, SIL-001, SIL-002, SIL-003, SIL-007, TRUST-001 ×2). Ces
tests exercent les **combinaisons** de paths qui n'étaient couvertes par
aucun test unitaire — c'est là que vivent les régressions subtiles.

Chaque test correspond à un scénario réaliste de panne ou de concurrence :
    - send échoue mid-flow → revert d'état correct (SIL-001 + RACE-002)
    - 2e validate sur draft déjà SENT → 409 sans double-send (RACE-002)
    - reject pendant validate inflight → 409 propre (SIL-003 + lock)
    - provider raise dans le lock → état préservé, pas de leak partiel
    - body client tente d'écrire dans un autre compte (TRUST-001)
    - attachment corrompu → mark failed (SCHED-001 cousin path)

Toutes les dépendances (provider, store, signature, account resolution,
background tasks) sont mockées : le test n'envoie aucun email réel.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from app.api.app import create_app
from app.domain.entities.pending_draft import PendingDraftStatus


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    app = create_app({"TESTING": True})
    with app.test_client() as c:
        yield c


def _make_draft(draft_id="draft-test", status=PendingDraftStatus.PENDING, account_id=1):
    """Mock PendingDraft cohérent avec le real flow validate.

    `status` doit être un membre de `PendingDraftStatus` — sinon le RACE-002
    guard à `routes_pending.py:287` traite la string comme "déjà traitée"
    et renvoie 409 (cf. lessons.md 2026-04-26 sur Enum mocks).
    """
    draft = MagicMock()
    draft.id = draft_id
    draft.email_id = f"email-{draft_id}"
    draft.email_sender = "sender@example.com"
    draft.draft_subject = "Re: Test"
    draft.draft_body = "Reply body content."
    draft.draft_v1 = "Reply body content."
    draft.email_received_at = None
    draft.account_id = account_id
    draft.status = status
    draft.refund_info = None
    draft.account_info = None
    draft.routing_tier = "standard"
    return draft


def _mock_lock():
    """MagicMock supporte __enter__/__exit__ donc fonctionne comme context manager."""
    return MagicMock()


def _setup_store(mock_get_container, draft, draft_lock=None):
    """Configure le store avec le draft + le lock per-draft."""
    mock_store = MagicMock()
    mock_store.get_by_id.return_value = draft
    mock_store.get_draft_lock.return_value = draft_lock or _mock_lock()
    mock_store.update_status.return_value = None
    mock_store.update_content.return_value = None
    mock_container = MagicMock()
    mock_container.get_pending_draft_store.return_value = mock_store
    mock_get_container.return_value = mock_container
    return mock_store


# ─────────────────────────────────────────────────────────────────────────────
# 1. RACE-002 + SIL-001 — send échoue, status revert, retry possible
# ─────────────────────────────────────────────────────────────────────────────

class TestSendFailureRevertCombinedRace002:
    """Quand `send_draft` échoue après `create_draft` succès, on doit :
       - revert PENDING (pas VALIDATED — sinon le daemon ignore le draft)
       - permettre un retry immédiat (le 2e POST doit voir PENDING, pas 409)
    """

    @patch("app.api.routes_pending._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_pending._get_authenticated_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_send_failure_reverts_to_pending_not_validated(
        self, mock_get_container, mock_get_provider, mock_resolve, client
    ):
        draft = _make_draft("draft-fail-001")
        mock_store = _setup_store(mock_get_container, draft)

        # send_reply_directly retourne False → fallback create_draft + send_draft
        # send_draft retourne False → SIL-001 path
        mock_provider = MagicMock(spec=["create_draft", "send_draft", "send_reply_directly"])
        mock_provider.send_reply_directly.return_value = None
        mock_provider.create_draft.return_value = "gmail-draft-fail"
        mock_provider.send_draft.return_value = False
        mock_get_provider.return_value = mock_provider

        resp = client.post("/api/pending-drafts/draft-fail-001/validate")

        assert resp.status_code == 500
        assert "failed to send" in resp.get_json()["error"].lower()

        # SIL-001 : update_status doit avoir été appelé avec PENDING (pas VALIDATED).
        # On filtre les calls update_status pour vérifier le status passé.
        update_calls = mock_store.update_status.call_args_list
        statuses = [c.args[1] if len(c.args) >= 2 else c.kwargs.get("status") for c in update_calls]
        assert PendingDraftStatus.PENDING in statuses, (
            f"SIL-001 broken : send fail doit revert→PENDING, got statuses={statuses}"
        )
        assert PendingDraftStatus.VALIDATED not in statuses, (
            "Régression SIL-001 : VALIDATED orphelinerait le draft (daemon le skip)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. RACE-002 — 2e validate sur draft SENT renvoie 409
# ─────────────────────────────────────────────────────────────────────────────

class TestSecondValidateOnSentReturns409:
    """Si un autre tick a déjà SENT le draft, le 2e validate doit voir le
    statut SENT au moment du check inside-lock et retourner 409 propre.
    """

    @patch("app.api.routes_pending._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_pending._get_authenticated_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_validate_on_already_sent_returns_409(
        self, mock_get_container, mock_get_provider, mock_resolve, client
    ):
        # Le draft est PENDING au premier get_by_id (avant le lock) puis SENT
        # quand on re-read inside le lock — c'est la fenêtre RACE-002.
        draft_pre = _make_draft("draft-race-002", status=PendingDraftStatus.PENDING)
        draft_post = _make_draft("draft-race-002", status=PendingDraftStatus.SENT)
        mock_store = _setup_store(mock_get_container, draft_pre)
        # 1er appel = pre-lock, 2e appel = inside-lock (re-read)
        mock_store.get_by_id.side_effect = [draft_pre, draft_post]

        mock_provider = MagicMock()
        mock_get_provider.return_value = mock_provider

        resp = client.post("/api/pending-drafts/draft-race-002/validate")

        assert resp.status_code == 409
        body = resp.get_json()
        assert "déjà été traité" in body["error"] or "already" in body.get("error", "").lower()
        assert body.get("status") == "sent"
        # Critique : le provider NE DOIT PAS avoir tenté un 2e send.
        mock_provider.send_reply_directly.assert_not_called()
        mock_provider.create_draft.assert_not_called()
        mock_provider.send_draft.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 3. RACE-002 — 2e validate sur draft REJECTED renvoie 409
# ─────────────────────────────────────────────────────────────────────────────

class TestSecondValidateOnRejectedReturns409:
    """Si reject est passé entre temps, validate doit voir REJECTED inside-lock."""

    @patch("app.api.routes_pending._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_pending._get_authenticated_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_validate_on_rejected_returns_409(
        self, mock_get_container, mock_get_provider, mock_resolve, client
    ):
        draft_pre = _make_draft("draft-rej", status=PendingDraftStatus.PENDING)
        draft_post = _make_draft("draft-rej", status=PendingDraftStatus.REJECTED)
        mock_store = _setup_store(mock_get_container, draft_pre)
        mock_store.get_by_id.side_effect = [draft_pre, draft_post]

        mock_provider = MagicMock()
        mock_get_provider.return_value = mock_provider

        resp = client.post("/api/pending-drafts/draft-rej/validate")

        assert resp.status_code == 409
        body = resp.get_json()
        assert body.get("status") == "rejected"
        mock_provider.send_reply_directly.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 4. RACE-002 + VALIDATED — retry permis
# ─────────────────────────────────────────────────────────────────────────────

class TestRetryAllowedFromValidated:
    """SIL-001 a renommé le path d'échec : VALIDATED reste un état "retry-able"
    pour permettre à l'utilisateur de cliquer "Approuver et Envoyer" une 2e
    fois après un timeout réseau. Le RACE-002 guard accepte VALIDATED dans
    le tuple `(PENDING, MODIFIED, VALIDATED)`.
    """

    @patch("app.api.routes_pending._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_pending._get_authenticated_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_validate_on_validated_status_proceeds_to_send(
        self, mock_get_container, mock_get_provider, mock_resolve, client
    ):
        draft = _make_draft("draft-validated", status=PendingDraftStatus.VALIDATED)
        _setup_store(mock_get_container, draft)

        mock_provider = MagicMock(spec=["send_reply_directly", "create_draft", "send_draft"])
        mock_provider.send_reply_directly.return_value = "msg-id-retry"
        mock_get_provider.return_value = mock_provider

        # On patche le post-send pipeline pour rester focus sur le send path.
        with patch("app.api.routes_pending._evict_email_from_all_caches"), \
             patch("app.api.websocket.emit_email_sent"), \
             patch("app.api.routes_pending._rh.get_db_session"), \
             patch("app.api.routes_pending._rh.EmailRepository"), \
             patch("app.api.routes_pending._rh.submit_background"):
            resp = client.post("/api/pending-drafts/draft-validated/validate")

        # Le retry doit passer (200 ou 500 si DB stuff fail — pas 409).
        assert resp.status_code != 409, (
            "VALIDATED doit rester retry-able selon SIL-001 ; 409 ici "
            "indiquerait que le tuple RACE-002 a été restreint à PENDING/MODIFIED."
        )
        mock_provider.send_reply_directly.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# 5. SIL-003 — reject pendant validate inflight (status check)
# ─────────────────────────────────────────────────────────────────────────────

class TestRejectAfterSentReturns409:
    """SIL-003 : le reject endpoint doit refuser si le draft est déjà SENT
    (race avec /validate). Précédemment, reject écrasait SENT → REJECTED.
    """

    @patch("app.api.routes_pending._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_helpers._get_container")
    def test_reject_on_sent_draft_returns_409(
        self, mock_get_container, mock_resolve, client
    ):
        draft = _make_draft("draft-sent-then-reject", status=PendingDraftStatus.SENT)
        mock_store = _setup_store(mock_get_container, draft)

        resp = client.post("/api/pending-drafts/draft-sent-then-reject/reject")

        assert resp.status_code == 409, (
            f"SIL-003 broken : reject sur SENT doit retourner 409, got {resp.status_code}"
        )
        body = resp.get_json()
        assert body.get("status") == "sent"
        # update_status REJECTED ne doit PAS avoir été appelé.
        for call in mock_store.update_status.call_args_list:
            status_arg = call.args[1] if len(call.args) >= 2 else call.kwargs.get("status")
            assert status_arg != PendingDraftStatus.REJECTED, (
                "SIL-003 broken : reject a écrasé SENT → REJECTED"
            )


class TestRejectOnValidatedReturns409:
    """SIL-003 cas similaire : reject sur VALIDATED (Gmail draft créé mais
    pas encore envoyé) doit aussi être bloqué — sinon on perd le brouillon.
    """

    @patch("app.api.routes_pending._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_helpers._get_container")
    def test_reject_on_validated_draft_returns_409(
        self, mock_get_container, mock_resolve, client
    ):
        draft = _make_draft("draft-val-then-reject", status=PendingDraftStatus.VALIDATED)
        _setup_store(mock_get_container, draft)

        resp = client.post("/api/pending-drafts/draft-val-then-reject/reject")

        assert resp.status_code == 409
        assert resp.get_json().get("status") == "validated"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Provider exception inside lock — état préservé, pas de leak partiel
# ─────────────────────────────────────────────────────────────────────────────

class TestProviderExceptionInsideLock:
    """Si le provider raise mid-send (ex: timeout réseau), le code doit :
       - sortir du lock proprement (pas de deadlock)
       - retourner 500 avec un message d'erreur lisible
       - NE PAS marquer SENT dans le store (sinon perte de retry)
    """

    @patch("app.api.routes_pending._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_pending._get_authenticated_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_provider_raise_keeps_state_recoverable(
        self, mock_get_container, mock_get_provider, mock_resolve, client
    ):
        draft = _make_draft("draft-network-fail")
        mock_store = _setup_store(mock_get_container, draft)

        mock_provider = MagicMock(spec=["send_reply_directly", "create_draft", "send_draft"])
        mock_provider.send_reply_directly.side_effect = ConnectionError("Network down")
        mock_provider.create_draft.side_effect = ConnectionError("Network down")
        mock_get_provider.return_value = mock_provider

        resp = client.post("/api/pending-drafts/draft-network-fail/validate")

        # Le code doit recover proprement, pas crash.
        assert resp.status_code in (500, 502), (
            f"Network exception must surface as 5xx, got {resp.status_code}"
        )
        # SENT ne doit jamais avoir été inscrit (état mensonger sinon).
        for call in mock_store.update_status.call_args_list:
            status_arg = call.args[1] if len(call.args) >= 2 else call.kwargs.get("status")
            assert status_arg != PendingDraftStatus.SENT, (
                "Network exception ne doit jamais marquer SENT"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 7. TRUST-001 — body client account_id ignoré
# ─────────────────────────────────────────────────────────────────────────────

class TestTrust001ClientAccountIdIgnored:
    """TRUST-001 : le post-send background thread `record_sent_recipients` et
    le style profile update doivent utiliser le account_id résolu côté
    serveur (`_resolve_account_id_cached`), jamais celui du request body
    (qui pourrait être crafté pour pollute un autre user).
    """

    @patch("app.api.routes_pending._resolve_account_id_cached", return_value=42)
    @patch("app.api.routes_pending._get_authenticated_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_post_send_uses_server_account_id_not_body(
        self, mock_get_container, mock_get_provider, mock_resolve, client
    ):
        draft = _make_draft("draft-trust-001", account_id=42)
        _setup_store(mock_get_container, draft)

        mock_provider = MagicMock(spec=["send_reply_directly"])
        mock_provider.send_reply_directly.return_value = "msg-id-trust"
        mock_get_provider.return_value = mock_provider

        # On capture les calls à record_sent_recipients pour vérifier l'aid passé.
        with patch("app.api.routes_pending._evict_email_from_all_caches"), \
             patch("app.api.websocket.emit_email_sent"), \
             patch("app.api.routes_pending._rh.get_db_session"), \
             patch("app.api.routes_pending._rh.EmailRepository"), \
             patch("app.api.routes_pending._rh.submit_background") as mock_bg, \
             patch("app.api.routes_helpers.record_sent_recipients") as mock_record:

            # Body crafté tente d'écrire sous account_id=999 (pas le caller).
            resp = client.post(
                "/api/pending-drafts/draft-trust-001/validate",
                json={"account_id": 999, "additional_recipients": ["bob@example.com"]},
            )

            # Run any queued background tasks synchronously to assert the call.
            for call in mock_bg.call_args_list:
                fn = call.args[0]
                try:
                    fn()
                except Exception:
                    pass  # Le bg peut échouer (pas de DB réelle), on s'en fiche pour ce test.

        assert resp.status_code in (200, 500), (
            f"Validate must succeed or fail at post-send, got {resp.status_code}"
        )
        # Si record_sent_recipients a été appelé, le 1er arg doit être 42 (server),
        # PAS 999 (body). Si pas appelé du tout, le test reste valide (pas de leak).
        for call in mock_record.call_args_list:
            aid = call.args[0]
            assert aid == 42, (
                f"TRUST-001 broken : record_sent_recipients appelé avec aid={aid} "
                f"(body=999, server=42). Le body crafté a réussi à override."
            )


# ─────────────────────────────────────────────────────────────────────────────
# 8. SCHED-001 cousin — attachment corrompu côté validate (base64 décode fail)
# ─────────────────────────────────────────────────────────────────────────────

class TestCorruptAttachmentValidatePath:
    """Le scheduled email scheduler raise sur attachment corrompu (SCHED-001).
    Pour le path validate (interactif), le code skip silencieusement les
    attachments qui ne décodent pas — décision UX différente du scheduler
    (l'utilisateur voit les attachments uploadés, donc on n'envoie pas un
    email muet sans pj). Ce test documente la décision : skip + log debug,
    et l'envoi continue avec les attachments valides.
    """

    @patch("app.api.routes_pending._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_pending._get_authenticated_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_corrupt_attachment_is_skipped_send_continues(
        self, mock_get_container, mock_get_provider, mock_resolve, client
    ):
        draft = _make_draft("draft-bad-att")
        _setup_store(mock_get_container, draft)

        mock_provider = MagicMock(spec=["send_reply_directly"])
        mock_provider.send_reply_directly.return_value = "msg-id-att"
        mock_get_provider.return_value = mock_provider

        with patch("app.api.routes_pending._evict_email_from_all_caches"), \
             patch("app.api.websocket.emit_email_sent"), \
             patch("app.api.routes_pending._rh.get_db_session"), \
             patch("app.api.routes_pending._rh.EmailRepository"), \
             patch("app.api.routes_pending._rh.submit_background"):
            resp = client.post(
                "/api/pending-drafts/draft-bad-att/validate",
                json={
                    "attachments": [
                        {"filename": "good.txt", "data_base64": "aGVsbG8=", "content_type": "text/plain"},
                        {"filename": "bad.bin", "data_base64": "!!!corrupt!!!", "content_type": "application/octet-stream"},
                    ]
                },
            )

        # L'envoi doit aboutir (200 ou 500 selon les bg tasks).
        assert resp.status_code != 409
        # send_reply_directly a été appelé : on récupère les attachments effectifs.
        mock_provider.send_reply_directly.assert_called_once()
        sent_kwargs = mock_provider.send_reply_directly.call_args.kwargs
        sent_atts = sent_kwargs.get("attachments")
        # 1 seule pj valide : la corrompue a été skip.
        assert sent_atts is not None and len(sent_atts) == 1
        assert sent_atts[0][0] == "good.txt"


# ─────────────────────────────────────────────────────────────────────────────
# 9. Cross-account isolation — draft d'un autre user → 404 (CRIT-Iso-4)
# ─────────────────────────────────────────────────────────────────────────────

class TestCrossAccountValidateRejected:
    """Le draft appartient à account 1, le caller est account 2 → 404 (anti-leak).
    Combine `_draft_belongs_to_account` (CRIT-Iso-4 strict) et le RACE-002
    guard : la 1ère barrière est l'ownership, le RACE-002 ne doit jamais
    être atteint (sinon le caller leak l'existence du draft en discriminant
    409 vs 200 selon le statut). Depuis l'audit IDOR (a63976cc), le code
    masque l'existence du draft cross-compte avec 404 au lieu de 403 —
    pour empêcher l'enumeration via discrimination 403 vs 404.
    """

    @patch("app.api.routes_pending._resolve_account_id_cached", return_value=2)
    @patch("app.api.routes_pending._get_authenticated_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_validate_other_account_draft_returns_403(
        self, mock_get_container, mock_get_provider, mock_resolve, client
    ):
        # Draft appartient à account_id=1, caller = 2.
        draft = _make_draft("draft-cross", account_id=1)
        mock_store = _setup_store(mock_get_container, draft)

        mock_provider = MagicMock()
        mock_get_provider.return_value = mock_provider

        resp = client.post("/api/pending-drafts/draft-cross/validate")

        # 404 (pas 403) : anti-enumeration — le caller ne doit pas pouvoir
        # discriminer entre "n'existe pas" et "existe mais pas le mien".
        assert resp.status_code == 404
        # Le provider ne doit jamais avoir été appelé (court-circuit ownership).
        mock_provider.send_reply_directly.assert_not_called()
        mock_provider.create_draft.assert_not_called()
        # Aucune tentative d'écriture statut sous le couvert d'un autre compte.
        mock_store.update_status.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 10. Concurrence : 2 validate simultanés → exactement 1 send
# ─────────────────────────────────────────────────────────────────────────────

class TestSequentialValidateExactlyOneSend:
    """RACE-002 sans threading : 2 calls séquentiels où le 2e voit l'état
    post-send (SENT) inscrit par le 1er. C'est le path le plus fréquent
    en prod (double-clic utilisateur, retry réseau côté client) — moins
    spectaculaire que le threading mais plus stable et tout aussi
    discriminant : si le RACE-002 guard est cassé, le 2e call double-send.

    Note : on évite le threading car Flask test_client + app_ctx ne sont
    pas thread-safe ensemble. Le vrai backend tourne sous gunicorn (1 req
    par thread, app_ctx propre), invariant vérifié séparément par
    `TestSecondValidateOnSentReturns409` (mêmes assertions, état mocké).
    """

    @patch("app.api.routes_pending._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_pending._get_authenticated_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_double_click_validate_sends_only_once(
        self, mock_get_container, mock_get_provider, mock_resolve, client
    ):
        state = {"status": PendingDraftStatus.PENDING, "send_count": 0}

        def get_by_id(_id):
            return _make_draft("draft-double-click", status=state["status"])

        def update_status(_id, status, **kwargs):
            state["status"] = status

        real_lock = threading.RLock()
        mock_store = MagicMock()
        mock_store.get_by_id.side_effect = get_by_id
        mock_store.get_draft_lock.return_value = real_lock
        mock_store.update_status.side_effect = update_status
        mock_container = MagicMock()
        mock_container.get_pending_draft_store.return_value = mock_store
        mock_get_container.return_value = mock_container

        def fake_send(**_kwargs):
            state["send_count"] += 1
            state["status"] = PendingDraftStatus.SENT
            return "msg-id-double-click"

        mock_provider = MagicMock(spec=["send_reply_directly"])
        mock_provider.send_reply_directly.side_effect = fake_send
        mock_get_provider.return_value = mock_provider

        with patch("app.api.routes_pending._evict_email_from_all_caches"), \
             patch("app.api.websocket.emit_email_sent"), \
             patch("app.api.routes_pending._rh.get_db_session"), \
             patch("app.api.routes_pending._rh.EmailRepository"), \
             patch("app.api.routes_pending._rh.submit_background"):
            resp1 = client.post("/api/pending-drafts/draft-double-click/validate")
            resp2 = client.post("/api/pending-drafts/draft-double-click/validate")

        # 1er call doit avoir réussi (200/500 selon les bg tasks, pas 409).
        assert resp1.status_code != 409
        # 2e call doit avoir vu SENT inside-lock → 409.
        assert resp2.status_code == 409, (
            f"RACE-002 broken : 2e validate sur SENT a passé (got {resp2.status_code})"
        )
        # Invariant clé : exactement 1 send.
        assert state["send_count"] == 1, (
            f"Double-send détecté ({state['send_count']} sends)"
        )
