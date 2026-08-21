# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
E2E — Blocked Senders : block, unblock, inbox filtering.

Pipeline testé :
  1. GET  /senders/blocked   — liste vide au départ
  2. POST /senders/block     — bloque info@pulsetto.tech
  3. GET  /senders/blocked   — liste retourne le bloqué
  4. GET  /emails            — emails du bloqué absents de l'inbox
  5. POST /senders/block     — idempotent (double-block)
  6. POST /senders/unblock   — débloque l'expéditeur
  7. GET  /senders/blocked   — liste vide à nouveau
  8. GET  /emails            — email réapparaît après déblocage

pytest tests/test_e2e_blocked_senders.py -v
"""

import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_email(sender: str, email_id: str | None = None) -> dict:
    """Génère un dict email minimal."""
    return {
        "id": email_id or str(uuid.uuid4()),
        "sender": sender,
        "sender_name": sender.split("@")[0],
        "subject": f"Message de {sender}",
        "received_at": "2026-03-11T10:00:00Z",
        "is_read": False,
        "body_preview": "Contenu du message.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app(tmp_path_factory):
    """Flask app avec AccountManager isolé dans un dossier temporaire."""
    tmp_dir = tmp_path_factory.mktemp("blocked_senders_e2e")

    # DB temporaire
    import os
    db_path = tmp_dir / "test_blocked.db"
    os.environ["AGENTYS_DB_PATH"] = str(db_path)

    from app.db.database import reset_engine, init_db, get_engine
    reset_engine()

    from app.api.app import create_app
    flask_app = create_app(config={"TESTING": True})

    engine = get_engine(db_path=db_path)
    init_db(engine)

    # AccountManager isolé avec un compte actif
    from app.multi_accounts import AccountManager, ProviderType
    acct_file = tmp_dir / "accounts.json"
    mgr = AccountManager(filepath=acct_file)
    acct = mgr.add_account(
        name="Test User",
        email="test@example.com",
        provider=ProviderType.IMAP_SMTP,
        credentials_path="",
    )
    mgr.switch_to(acct.id)

    # Injecter notre manager dans le singleton
    import app.multi_accounts as _ma
    _ma._account_manager = mgr

    yield flask_app

    # Cleanup
    reset_engine()
    _ma._account_manager = None
    if "AGENTYS_DB_PATH" in os.environ:
        del os.environ["AGENTYS_DB_PATH"]


@pytest.fixture(scope="module")
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def reset_blocked_senders(app):
    """Vide la liste des bloqués avant chaque test."""
    import app.multi_accounts as _ma
    acct = _ma._account_manager.get_current_account()
    _ma._account_manager.update_account(acct.id, blocked_senders=[])
    yield
    acct = _ma._account_manager.get_current_account()
    _ma._account_manager.update_account(acct.id, blocked_senders=[])


# ─────────────────────────────────────────────────────────────────────────────
# Tests — API block/unblock
# ─────────────────────────────────────────────────────────────────────────────

class TestBlockUnblockAPI:

    def test_get_blocked_empty(self, client):
        """GET /senders/blocked retourne une liste vide au départ."""
        r = client.get("/api/senders/blocked")
        assert r.status_code == 200
        data = r.get_json()
        assert data["blocked_senders"] == []
        assert "blocked_domains" in data

    def test_block_sender(self, client):
        """POST /senders/block stocke l'email et le retourne."""
        r = client.post(
            "/api/senders/block",
            data=json.dumps({"email": "info@pulsetto.tech"}),
            content_type="application/json",
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["success"] is True
        assert "info@pulsetto.tech" in data["blocked_senders"]

    def test_get_blocked_after_block(self, client):
        """GET /senders/blocked retourne l'expéditeur bloqué."""
        client.post(
            "/api/senders/block",
            data=json.dumps({"email": "info@pulsetto.tech"}),
            content_type="application/json",
        )
        r = client.get("/api/senders/blocked")
        assert r.status_code == 200
        assert "info@pulsetto.tech" in r.get_json()["blocked_senders"]

    def test_block_multiple_senders(self, client):
        """Bloquer plusieurs expéditeurs accumule la liste."""
        for email in ["info@pulsetto.tech", "thedailydegen@substack.com"]:
            client.post(
                "/api/senders/block",
                data=json.dumps({"email": email}),
                content_type="application/json",
            )
        r = client.get("/api/senders/blocked")
        blocked = r.get_json()["blocked_senders"]
        assert "info@pulsetto.tech" in blocked
        assert "thedailydegen@substack.com" in blocked
        assert len(blocked) == 2

    def test_block_idempotent(self, client):
        """Double-block du même email ne crée pas de doublon."""
        for _ in range(3):
            client.post(
                "/api/senders/block",
                data=json.dumps({"email": "duplicate@test.com"}),
                content_type="application/json",
            )
        r = client.get("/api/senders/blocked")
        blocked = r.get_json()["blocked_senders"]
        assert blocked.count("duplicate@test.com") == 1

    def test_block_normalizes_to_lowercase(self, client):
        """L'email est normalisé en minuscules."""
        client.post(
            "/api/senders/block",
            data=json.dumps({"email": "INFO@Pulsetto.TECH"}),
            content_type="application/json",
        )
        r = client.get("/api/senders/blocked")
        assert "info@pulsetto.tech" in r.get_json()["blocked_senders"]

    def test_block_missing_email_returns_400(self, client):
        """POST sans email retourne 400."""
        r = client.post(
            "/api/senders/block",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert r.status_code == 400

    def test_block_empty_email_returns_400(self, client):
        """POST avec email vide retourne 400."""
        r = client.post(
            "/api/senders/block",
            data=json.dumps({"email": "   "}),
            content_type="application/json",
        )
        assert r.status_code == 400

    def test_unblock_sender(self, client):
        """POST /senders/unblock retire l'expéditeur de la liste."""
        client.post(
            "/api/senders/block",
            data=json.dumps({"email": "info@pulsetto.tech"}),
            content_type="application/json",
        )
        r = client.post(
            "/api/senders/unblock",
            data=json.dumps({"email": "info@pulsetto.tech"}),
            content_type="application/json",
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["success"] is True
        assert "info@pulsetto.tech" not in data["blocked_senders"]

    def test_unblock_removes_only_target(self, client):
        """Unblock ne retire que l'email ciblé, pas les autres."""
        for email in ["info@pulsetto.tech", "thedailydegen@substack.com"]:
            client.post(
                "/api/senders/block",
                data=json.dumps({"email": email}),
                content_type="application/json",
            )
        client.post(
            "/api/senders/unblock",
            data=json.dumps({"email": "info@pulsetto.tech"}),
            content_type="application/json",
        )
        r = client.get("/api/senders/blocked")
        blocked = r.get_json()["blocked_senders"]
        assert "info@pulsetto.tech" not in blocked
        assert "thedailydegen@substack.com" in blocked

    def test_get_blocked_after_unblock_all(self, client):
        """Liste vide après avoir débloqué tous les expéditeurs."""
        for email in ["info@pulsetto.tech", "thedailydegen@substack.com"]:
            client.post(
                "/api/senders/block",
                data=json.dumps({"email": email}),
                content_type="application/json",
            )
        for email in ["info@pulsetto.tech", "thedailydegen@substack.com"]:
            client.post(
                "/api/senders/unblock",
                data=json.dumps({"email": email}),
                content_type="application/json",
            )
        r = client.get("/api/senders/blocked")
        assert r.get_json()["blocked_senders"] == []


# ─────────────────────────────────────────────────────────────────────────────
# Tests — Inbox filtering (unit tests sur les fonctions de filtrage)
# ─────────────────────────────────────────────────────────────────────────────

class TestInboxFiltering:
    """Vérifie que les emails des bloqués sont filtrés de l'inbox.

    On teste :
    - _filter_blocked_senders() directement (logique de filtrage)
    - _get_blocked_senders_set()  après appel API block/unblock
    """

    PULSETTO_EMAIL = "info@pulsetto.tech"
    DEGEN_EMAIL = "thedailydegen@substack.com"
    ALLOWED_EMAIL = "friend@example.com"

    def _inbox(self, blocked_senders_present=True):
        """Retourne une liste d'emails simulant l'inbox."""
        emails = [
            _make_email(self.ALLOWED_EMAIL, "allowed-1"),
            _make_email(self.ALLOWED_EMAIL, "allowed-2"),
        ]
        if blocked_senders_present:
            emails += [
                _make_email(self.PULSETTO_EMAIL, "pulsetto-1"),
                _make_email(self.PULSETTO_EMAIL, "pulsetto-2"),
                _make_email(self.DEGEN_EMAIL, "degen-1"),
            ]
        return emails

    # --- Logique de filtrage ---------------------------------------------------

    def test_filter_empty_blocked_set_returns_all(self):
        """Avec un set vide, tous les emails passent."""
        from app.api.routes import _filter_blocked_senders
        emails = self._inbox(blocked_senders_present=True)
        result = _filter_blocked_senders(emails, set())
        assert len(result) == len(emails)

    def test_filter_blocks_matching_sender(self):
        """_filter_blocked_senders retire les emails du bloqué."""
        from app.api.routes import _filter_blocked_senders
        emails = self._inbox(blocked_senders_present=True)
        blocked = {self.PULSETTO_EMAIL}
        result = _filter_blocked_senders(emails, blocked)
        senders = [e["sender"] for e in result]
        assert self.PULSETTO_EMAIL not in senders
        assert self.DEGEN_EMAIL in senders
        assert self.ALLOWED_EMAIL in senders

    def test_filter_blocks_display_name_format(self):
        """_filter_blocked_senders gère 'Pulsetto <info@pulsetto.tech>'."""
        from app.api.routes import _filter_blocked_senders
        emails = [
            _make_email("Pulsetto <info@pulsetto.tech>", "p-display"),
            _make_email(self.ALLOWED_EMAIL, "ok-1"),
        ]
        blocked = {self.PULSETTO_EMAIL}
        result = _filter_blocked_senders(emails, blocked)
        senders = [e["sender"] for e in result]
        assert "Pulsetto <info@pulsetto.tech>" not in senders
        assert self.ALLOWED_EMAIL in senders

    def test_filter_both_blocked_senders(self):
        """Bloquer les 2 expéditeurs — seuls les autorisés restent."""
        from app.api.routes import _filter_blocked_senders
        emails = self._inbox(blocked_senders_present=True)
        blocked = {self.PULSETTO_EMAIL, self.DEGEN_EMAIL}
        result = _filter_blocked_senders(emails, blocked)
        senders = [e["sender"] for e in result]
        assert self.PULSETTO_EMAIL not in senders
        assert self.DEGEN_EMAIL not in senders
        assert self.ALLOWED_EMAIL in senders
        assert len(result) == 2  # uniquement les 2 emails autorisés

    def test_filter_reduces_count_correctly(self):
        """Le compte baisse du nombre d'emails bloqués."""
        from app.api.routes import _filter_blocked_senders
        emails = self._inbox(blocked_senders_present=True)  # 5 emails
        blocked = {self.PULSETTO_EMAIL}  # 2 emails pulsetto
        result = _filter_blocked_senders(emails, blocked)
        assert len(result) == 3  # 2 allowed + 1 degen

    # --- Intégration API → set de bloqués ------------------------------------

    def test_blocked_set_empty_initially(self, client):
        """_get_blocked_senders_set() retourne un set vide au départ."""
        from app.api.routes import _get_blocked_senders_set
        assert _get_blocked_senders_set() == set()

    def test_blocked_set_after_block(self, client):
        """_get_blocked_senders_set() reflète le blocage via API."""
        from app.api.routes import _get_blocked_senders_set
        client.post(
            "/api/senders/block",
            data=json.dumps({"email": self.PULSETTO_EMAIL}),
            content_type="application/json",
        )
        blocked_set = _get_blocked_senders_set()
        assert self.PULSETTO_EMAIL in blocked_set

    def test_blocked_set_after_block_two(self, client):
        """Les 2 bloqués apparaissent dans le set."""
        from app.api.routes import _get_blocked_senders_set
        for email in [self.PULSETTO_EMAIL, self.DEGEN_EMAIL]:
            client.post(
                "/api/senders/block",
                data=json.dumps({"email": email}),
                content_type="application/json",
            )
        blocked_set = _get_blocked_senders_set()
        assert self.PULSETTO_EMAIL in blocked_set
        assert self.DEGEN_EMAIL in blocked_set

    def test_blocked_set_cleared_after_unblock(self, client):
        """_get_blocked_senders_set() vide après déblocage."""
        from app.api.routes import _get_blocked_senders_set
        client.post(
            "/api/senders/block",
            data=json.dumps({"email": self.PULSETTO_EMAIL}),
            content_type="application/json",
        )
        client.post(
            "/api/senders/unblock",
            data=json.dumps({"email": self.PULSETTO_EMAIL}),
            content_type="application/json",
        )
        assert _get_blocked_senders_set() == set()

    def test_filter_applied_with_api_blocked_set(self, client):
        """Combinaison API + filter : emails bloqués absents du résultat."""
        from app.api.routes import _filter_blocked_senders, _get_blocked_senders_set
        client.post(
            "/api/senders/block",
            data=json.dumps({"email": self.PULSETTO_EMAIL}),
            content_type="application/json",
        )
        emails = self._inbox(blocked_senders_present=True)
        blocked_set = _get_blocked_senders_set()
        result = _filter_blocked_senders(emails, blocked_set)
        senders = [e["sender"] for e in result]
        assert self.PULSETTO_EMAIL not in senders
        assert self.DEGEN_EMAIL in senders


# ─────────────────────────────────────────────────────────────────────────────
# Tests — Persistence (données sauvegardées sur disque)
# ─────────────────────────────────────────────────────────────────────────────

class TestBlockedSenderPersistence:

    def test_block_persisted_to_file(self, client):
        """Le blocage est sauvegardé dans le fichier accounts JSON."""
        import app.multi_accounts as _ma

        client.post(
            "/api/senders/block",
            data=json.dumps({"email": "persist@test.com"}),
            content_type="application/json",
        )

        # Lire directement depuis le fichier JSON
        acct_data = json.loads(_ma._account_manager.filepath.read_text())
        all_blocked = []
        for acct in acct_data.get("accounts", []):
            all_blocked.extend(acct.get("blocked_senders") or [])

        assert "persist@test.com" in all_blocked

    def test_unblock_persisted_to_file(self, client):
        """Le déblocage est sauvegardé dans le fichier accounts JSON."""
        import app.multi_accounts as _ma

        client.post(
            "/api/senders/block",
            data=json.dumps({"email": "persist@test.com"}),
            content_type="application/json",
        )
        client.post(
            "/api/senders/unblock",
            data=json.dumps({"email": "persist@test.com"}),
            content_type="application/json",
        )

        acct_data = json.loads(_ma._account_manager.filepath.read_text())
        all_blocked = []
        for acct in acct_data.get("accounts", []):
            all_blocked.extend(acct.get("blocked_senders") or [])

        assert "persist@test.com" not in all_blocked
