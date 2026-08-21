# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
E2E — FAQ Agent : KB CRUD, marketplace catalog/subscribe/config, stats/history, FAQ processing.

Pipeline testé :
  1. Knowledge CRUD  — create, list, filter, update, delete, categories, import
  2. Catalogue       — FAQ Agent présent, prix, statut installed
  3. Souscription    — subscribe, installed, catalog, idempotent, unsubscribe
  4. Configuration   — save, read, defaults, partial merge
  5. Stats/History   — empty state, after logs, history sorting
  6. Matching logic  — high confidence, low confidence, no entries
  7. Full flow       — subscribe → config → KB entry → process → stats
  8. Smart routing   — FAQ_AUTO tier integration

Aucun vrai appel LLM ni réseau — tout est mocké.
"""

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

# Will be set once the test account is created in DB (integer PK)
_TEST_ACCOUNT_ID = None


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    """Flask app avec DB temporaire et répertoire de config isolé."""
    global _TEST_ACCOUNT_ID

    # Point the DB to a temp file so tests don't touch the real database
    tmp_dir = tmp_path_factory.mktemp("faq_e2e")
    db_path = tmp_dir / "test_faq.db"
    os.environ["AGENTYS_DB_PATH"] = str(db_path)

    # Reset engine so it picks up the new DB path
    from app.db.database import reset_engine, init_db
    reset_engine()

    from app.api.app import create_app
    flask_app = create_app(config={"TESTING": True})

    # Init DB tables
    from app.db.database import get_engine
    engine = get_engine(db_path=db_path)
    init_db(engine)

    # Also create knowledge_entries and faq_agent_logs tables explicitly
    from app.db.models.knowledge_entry import KnowledgeEntry  # noqa: F401
    from app.db.models.faq_agent_log import FaqAgentLog  # noqa: F401
    from app.db.models.base import Base
    Base.metadata.create_all(bind=engine)

    # Create a test account in the DB (Account.id is an integer PK)
    from app.db.database import get_db_session
    from app.db.models.account import Account
    with flask_app.app_context():
        with get_db_session() as session:
            acct = Account(
                email="test-faq@example.com",
                provider="mock",
                is_active=True,
            )
            session.add(acct)
            session.flush()
            _TEST_ACCOUNT_ID = acct.id

    # Redirect marketplace config dir
    import app.api.agent_marketplace as _mp
    _mp._DATA_DIR = tmp_dir / "agent_configs"
    _mp._DATA_DIR.mkdir(parents=True, exist_ok=True)

    yield flask_app

    # Cleanup
    reset_engine()
    if "AGENTYS_DB_PATH" in os.environ:
        del os.environ["AGENTYS_DB_PATH"]


@pytest.fixture(scope="module")
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def clean_settings(app, tmp_path):
    """Remet installed_agents à [] et supprime les configs agents avant chaque test.
    Uses an isolated settings file so real data/settings.json is never touched."""
    import app.api.agent_marketplace as _mp
    import app.api.settings as _settings_mod

    # Redirect settings to a temp file so real settings are never wiped
    _original_settings_file = _settings_mod.SETTINGS_FILE
    _test_settings_file = tmp_path / "test_settings.json"
    _settings_mod.SETTINGS_FILE = _test_settings_file

    def _reset():
        with app.app_context():
            settings = _settings_mod.load_settings()
            settings["installed_agents"] = []
            _settings_mod.save_settings(settings)
        if _mp._DATA_DIR.exists():
            for f in _mp._DATA_DIR.glob("*.json"):
                f.unlink(missing_ok=True)

    _reset()
    yield
    _reset()
    # Restore original settings file path
    _settings_mod.SETTINGS_FILE = _original_settings_file


@pytest.fixture(autouse=True)
def clean_db_tables(app):
    """Nettoie les tables knowledge_entries et faq_agent_logs entre chaque test."""
    yield
    with app.app_context():
        try:
            from app.db.database import get_db_session
            with get_db_session() as session:
                session.execute(__import__("sqlalchemy").text("DELETE FROM knowledge_entries"))
                session.execute(__import__("sqlalchemy").text("DELETE FROM faq_agent_logs"))
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _mock_faq_account_id():
    """Routes knowledge ignorent account_id body et lisent _resolve_account_id_for_user.
    En CI sans JWT actif → None → 400 no active account. Mock pour que
    _TEST_ACCOUNT_ID (créé en DB) soit utilisé."""
    from unittest.mock import patch
    with patch("app.api.routes_helpers._resolve_account_id_for_user",
               return_value=_TEST_ACCOUNT_ID or 1):
        yield


# ─────────────────────────────────────────────────────────────────────────────
# 1. Knowledge CRUD
# ─────────────────────────────────────────────────────────────────────────────

class TestFaqKnowledgeCrud:

    def test_create_entry(self, client, app):
        """POST /api/knowledge/entries → 201, returns entry with id."""
        resp = client.post(
            "/api/knowledge/entries",
            json={
                "title": "Comment réinitialiser mon mot de passe ?",
                "content": "Allez dans Paramètres > Sécurité.",
                "category": "FAQ",
                "account_id": _TEST_ACCOUNT_ID,
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert "id" in data
        assert data["title"] == "Comment réinitialiser mon mot de passe ?"
        assert data["category"] == "FAQ"

    def test_list_entries(self, client, app):
        """GET /api/knowledge/entries → returns created entries."""

        # Create 2 entries
        client.post("/api/knowledge/entries", json={
            "title": "FAQ 1", "content": "Content 1", "category": "FAQ",
            "account_id": _TEST_ACCOUNT_ID,
        })
        client.post("/api/knowledge/entries", json={
            "title": "Tech 1", "content": "Content 2", "category": "TECHNIQUE",
            "account_id": _TEST_ACCOUNT_ID,
        })

        resp = client.get(f"/api/knowledge/entries?account_id={_TEST_ACCOUNT_ID}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) >= 2

    def test_list_entries_filter_category(self, client, app):
        """GET ?category=FAQ → only FAQ entries."""

        client.post("/api/knowledge/entries", json={
            "title": "FAQ Only", "content": "C", "category": "FAQ",
            "account_id": _TEST_ACCOUNT_ID,
        })
        client.post("/api/knowledge/entries", json={
            "title": "Tech Only", "content": "C", "category": "TECHNIQUE",
            "account_id": _TEST_ACCOUNT_ID,
        })

        resp = client.get(f"/api/knowledge/entries?category=FAQ&account_id={_TEST_ACCOUNT_ID}")
        data = resp.get_json()
        assert all(e["category"] == "FAQ" for e in data)

    def test_update_entry(self, client, app):
        """PATCH /api/knowledge/entries/<id> → updated fields."""

        create_resp = client.post("/api/knowledge/entries", json={
            "title": "Original", "content": "Original content", "category": "FAQ",
            "account_id": _TEST_ACCOUNT_ID,
        })
        entry_id = create_resp.get_json()["id"]

        resp = client.patch(
            f"/api/knowledge/entries/{entry_id}",
            json={"title": "Updated Title", "content": "Updated Content"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["title"] == "Updated Title"
        assert data["content"] == "Updated Content"

    def test_delete_entry(self, client, app):
        """DELETE → 200, entry gone from list."""

        create_resp = client.post("/api/knowledge/entries", json={
            "title": "To Delete", "content": "C", "category": "FAQ",
            "account_id": _TEST_ACCOUNT_ID,
        })
        entry_id = create_resp.get_json()["id"]

        resp = client.delete(f"/api/knowledge/entries/{entry_id}")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

        # Verify gone
        list_resp = client.get(f"/api/knowledge/entries?account_id={_TEST_ACCOUNT_ID}")
        ids = [e["id"] for e in list_resp.get_json()]
        assert entry_id not in ids

    def test_create_entry_missing_title(self, client, app):
        """POST without title → 400."""

        resp = client.post("/api/knowledge/entries", json={
            "content": "Content only",
            "account_id": _TEST_ACCOUNT_ID,
        })
        assert resp.status_code == 400

    def test_get_categories(self, client, app):
        """GET /api/knowledge/categories → category counts."""

        client.post("/api/knowledge/entries", json={
            "title": "FAQ A", "content": "C", "category": "FAQ",
            "account_id": _TEST_ACCOUNT_ID,
        })
        client.post("/api/knowledge/entries", json={
            "title": "FAQ B", "content": "C", "category": "FAQ",
            "account_id": _TEST_ACCOUNT_ID,
        })
        client.post("/api/knowledge/entries", json={
            "title": "Tech A", "content": "C", "category": "TECHNIQUE",
            "account_id": _TEST_ACCOUNT_ID,
        })

        resp = client.get(f"/api/knowledge/categories?account_id={_TEST_ACCOUNT_ID}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("FAQ", 0) >= 2
        assert data.get("TECHNIQUE", 0) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 2. Marketplace Catalog
# ─────────────────────────────────────────────────────────────────────────────

class TestFaqMarketplaceCatalog:

    def test_catalog_contains_faq_agent(self, client):
        """Le catalogue doit contenir le FAQ Agent avec ses métadonnées."""
        resp = client.get("/api/agent-marketplace/catalog")
        assert resp.status_code == 200
        data = resp.get_json()
        faq = next((a for a in data if a["id"] == "faq"), None)
        assert faq is not None, "FAQ Agent doit être dans le catalogue"
        assert faq["name"] == "FAQ Agent"
        assert faq["category"] == "Customer Service"
        assert faq["price_monthly"] == 15
        assert faq["rating"] == 4.7
        assert "installed" in faq

    def test_faq_not_installed_by_default(self, client):
        """Avant souscription : installed=False."""
        resp = client.get("/api/agent-marketplace/catalog")
        data = resp.get_json()
        faq = next(a for a in data if a["id"] == "faq")
        assert faq["installed"] is False

    def test_faq_is_configured_always_true(self, client):
        """Après subscribe → is_configured=True (no secrets needed)."""
        client.post("/api/agent-marketplace/faq/subscribe")
        resp = client.get("/api/agent-marketplace/installed")
        faq = next(a for a in resp.get_json() if a["id"] == "faq")
        assert faq["is_configured"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 3. Souscription
# ─────────────────────────────────────────────────────────────────────────────

class TestFaqMarketplaceSubscription:

    def test_subscribe_faq(self, client):
        """POST /subscribe → ok=True + agent_id retourné."""
        resp = client.post("/api/agent-marketplace/faq/subscribe")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["agent_id"] == "faq"

    def test_appears_in_installed(self, client):
        """Après souscription, GET /installed contient le FAQ Agent."""
        client.post("/api/agent-marketplace/faq/subscribe")
        resp = client.get("/api/agent-marketplace/installed")
        ids = [a["id"] for a in resp.get_json()]
        assert "faq" in ids

    def test_catalog_marks_installed(self, client):
        """Après souscription, /catalog reflète installed=True."""
        client.post("/api/agent-marketplace/faq/subscribe")
        resp = client.get("/api/agent-marketplace/catalog")
        faq = next(a for a in resp.get_json() if a["id"] == "faq")
        assert faq["installed"] is True

    def test_double_subscribe_idempotent(self, client):
        """Souscrire deux fois n'ajoute pas de doublon."""
        client.post("/api/agent-marketplace/faq/subscribe")
        client.post("/api/agent-marketplace/faq/subscribe")
        resp = client.get("/api/agent-marketplace/installed")
        ids = [a["id"] for a in resp.get_json()]
        assert ids.count("faq") == 1

    def test_unsubscribe_removes(self, client):
        """DELETE /unsubscribe → agent absent de /installed."""
        client.post("/api/agent-marketplace/faq/subscribe")
        resp = client.delete("/api/agent-marketplace/faq/unsubscribe")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

        resp2 = client.get("/api/agent-marketplace/installed")
        ids = [a["id"] for a in resp2.get_json()]
        assert "faq" not in ids


# ─────────────────────────────────────────────────────────────────────────────
# 4. Configuration
# ─────────────────────────────────────────────────────────────────────────────

class TestFaqMarketplaceConfig:

    def test_save_config(self, client):
        """PATCH /faq/config with config → saved."""
        resp = client.patch(
            "/api/agent-marketplace/faq/config",
            json={"confidence_threshold": 70, "reply_tone": "friendly"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_read_config(self, client):
        """GET /faq/config → returns saved values."""
        client.patch(
            "/api/agent-marketplace/faq/config",
            json={"confidence_threshold": 70, "reply_tone": "friendly"},
        )
        resp = client.get("/api/agent-marketplace/faq/config")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["confidence_threshold"] == 70
        assert data["reply_tone"] == "friendly"

    def test_default_config_values(self, client):
        """Fresh config → empty dict (defaults applied in process_faq_email)."""
        resp = client.get("/api/agent-marketplace/faq/config")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)

    def test_update_partial_config(self, client):
        """PATCH with only {test_mode: True} → merges with existing."""
        client.patch(
            "/api/agent-marketplace/faq/config",
            json={"confidence_threshold": 85, "auto_send": True},
        )
        client.patch(
            "/api/agent-marketplace/faq/config",
            json={"test_mode": True},
        )

        import app.api.agent_marketplace as _mp
        stored = _mp._load_agent_config("faq")
        assert stored["confidence_threshold"] == 85
        assert stored["auto_send"] is True
        assert stored["test_mode"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 5. Stats & History
# ─────────────────────────────────────────────────────────────────────────────

class TestFaqStatsAndHistory:

    def test_stats_empty(self, client, app):
        """GET /faq/stats → auto_sent_count: 0, skipped_count: 0."""

        resp = client.get(f"/api/agent-marketplace/faq/stats?account_id={_TEST_ACCOUNT_ID}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["auto_sent_count"] == 0
        assert data["skipped_count"] == 0

    def test_stats_after_logs(self, client, app):
        """Insert mock faq_agent_logs → stats reflect counts + avg confidence."""

        with app.app_context():
            from app.db.database import get_db_session
            from app.db.models.faq_agent_log import FaqAgentLog

            with get_db_session() as session:
                for i in range(3):
                    session.add(FaqAgentLog(
                        id=str(uuid.uuid4()),
                        account_id=_TEST_ACCOUNT_ID,
                        email_id=f"email-{i}",
                        action="auto_sent",
                        confidence_score=80.0 + i * 5,  # 80, 85, 90
                        matched_entry_id="entry-1",
                        matched_entry_title="Password reset",
                    ))
                session.add(FaqAgentLog(
                    id=str(uuid.uuid4()),
                    account_id=_TEST_ACCOUNT_ID,
                    email_id="email-skip",
                    action="skipped",
                    confidence_score=20.0,
                ))

        resp = client.get(f"/api/agent-marketplace/faq/stats?account_id={_TEST_ACCOUNT_ID}")
        data = resp.get_json()
        assert data["auto_sent_count"] == 3
        assert data["skipped_count"] == 1
        assert data["avg_confidence"] == 85.0  # (80+85+90)/3

    def test_history_empty(self, client, app):
        """GET /faq/history → empty list."""

        resp = client.get(f"/api/agent-marketplace/faq/history?account_id={_TEST_ACCOUNT_ID}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == []

    def test_history_returns_recent(self, client, app):
        """Insert logs → history returns them sorted by date desc."""

        with app.app_context():
            from app.db.database import get_db_session
            from app.db.models.faq_agent_log import FaqAgentLog

            with get_db_session() as session:
                session.add(FaqAgentLog(
                    id="log-old",
                    account_id=_TEST_ACCOUNT_ID,
                    email_id="email-old",
                    action="skipped",
                    confidence_score=30.0,
                    created_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
                ))
                session.add(FaqAgentLog(
                    id="log-new",
                    account_id=_TEST_ACCOUNT_ID,
                    email_id="email-new",
                    action="auto_sent",
                    confidence_score=92.0,
                    matched_entry_id="e1",
                    matched_entry_title="Password reset",
                    created_at=datetime(2026, 3, 9, tzinfo=timezone.utc),
                ))

        resp = client.get(f"/api/agent-marketplace/faq/history?account_id={_TEST_ACCOUNT_ID}")
        data = resp.get_json()
        assert len(data) == 2
        # Most recent first
        assert data[0]["email_id"] == "email-new"
        assert data[0]["action"] == "auto_sent"
        assert data[1]["email_id"] == "email-old"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Matching Logic (integration)
# ─────────────────────────────────────────────────────────────────────────────

class TestFaqMatchingLogic:

    def test_process_email_high_confidence(self, app):
        """Create FAQ entries + call process_faq_email with matching email → auto_sent."""


        # Insert FAQ entry directly
        with app.app_context():
            from app.db.database import get_db_session
            from app.db.models.knowledge_entry import KnowledgeEntry

            with get_db_session() as session:
                session.add(KnowledgeEntry(
                    id="faq-entry-1",
                    account_id=_TEST_ACCOUNT_ID,
                    title="Comment réinitialiser mot de passe",
                    content="Allez dans Paramètres > Sécurité > Réinitialiser le mot de passe.",
                    category="FAQ",
                    source="manual",
                ))

        with app.app_context():
            from app.faq_agent import process_faq_email

            # Mock LLM to return "1" (first FAQ entry matches)
            mock_llm_resp = MagicMock()
            mock_llm_resp.content = "1"
            mock_container = MagicMock()
            mock_container.llm_label.complete.return_value = mock_llm_resp

            with patch("app.faq_agent._auto_send_faq"), \
                 patch("app.faq_agent.generate_faq_response", return_value="Voici comment réinitialiser..."), \
                 patch("app.infrastructure.container.get_container", return_value=mock_container):
                result = process_faq_email(
                    email_id="test-email-1",
                    email_subject="Mot de passe",
                    email_body="Comment réinitialiser mon mot de passe ? J'ai oublié.",
                    sender="user@example.com",
                    sender_name="User",
                    account_id=_TEST_ACCOUNT_ID,
                    config={"confidence_threshold": 30, "auto_send": True, "test_mode": False},
                )

            assert result is not None
            assert result.action == "auto_sent"
            assert result.confidence > 0
            assert result.matched_entry_title is not None

    def test_process_email_auto_send_false_stays_draft_only(self, app):
        """Matching FAQ with auto_send disabled must not send."""
        with app.app_context():
            from app.db.database import get_db_session
            from app.db.models.knowledge_entry import KnowledgeEntry

            with get_db_session() as session:
                session.add(KnowledgeEntry(
                    id="faq-entry-draft-only",
                    account_id=_TEST_ACCOUNT_ID,
                    title="Comment réinitialiser mot de passe",
                    content="Allez dans Paramètres > Sécurité.",
                    category="FAQ",
                    source="manual",
                ))

        with app.app_context():
            from app.faq_agent import process_faq_email

            mock_llm_resp = MagicMock()
            mock_llm_resp.content = "1"
            mock_container = MagicMock()
            mock_container.llm_label.complete.return_value = mock_llm_resp

            with patch("app.faq_agent._auto_send_faq") as mock_send, \
                 patch("app.faq_agent.generate_faq_response", return_value="Voici comment réinitialiser..."), \
                 patch("app.infrastructure.container.get_container", return_value=mock_container):
                result = process_faq_email(
                    email_id="test-email-draft-only",
                    email_subject="Mot de passe",
                    email_body="Comment réinitialiser mon mot de passe ?",
                    sender="user@example.com",
                    sender_name="User",
                    account_id=_TEST_ACCOUNT_ID,
                    config={"confidence_threshold": 30, "auto_send": False, "test_mode": False},
                )

            assert result is not None
            assert result.action == "draft_only"
            mock_send.assert_not_called()

    def test_auto_send_faq_uses_db_account_email_not_current_account(self, app):
        """FAQ auto-send must fail closed instead of falling back to another current account."""
        with app.app_context():
            from app.db.database import get_db_session
            from app.db.models.account import Account

            with get_db_session() as session:
                account = session.get(Account, _TEST_ACCOUNT_ID)
                account.signature_text = "Nat Signature"
                session.commit()

            from app.faq_agent import _auto_send_faq

            target_account = MagicMock()
            target_account.email = "test-faq@example.com"
            current_account = MagicMock()
            current_account.email = "alex@example.com"

            manager = MagicMock()
            manager.accounts = {}
            manager.get_account_by_email.return_value = target_account
            manager.get_current_account.return_value = current_account

            provider = MagicMock()
            provider.send_reply_directly.return_value = "sent-faq-1"

            with patch("app.multi_accounts.get_account_manager", return_value=manager), \
                 patch("app.multi_accounts.create_provider_for_account", return_value=provider) as mock_create:
                sent_id = _auto_send_faq(
                    email_id="faq-email-1",
                    recipient="client@example.com",
                    subject="Question",
                    body="Réponse FAQ",
                    account_id=str(_TEST_ACCOUNT_ID),
                )

            assert sent_id == "sent-faq-1"
            mock_create.assert_called_once_with(target_account)
            manager.get_current_account.assert_not_called()
            sent_body = provider.send_reply_directly.call_args.kwargs["body"]
            assert "Nat Signature" in sent_body
            assert "alex@example.com" not in sent_body

    def test_process_email_low_confidence(self, app):
        """Unrelated email → skipped."""


        with app.app_context():
            from app.db.database import get_db_session
            from app.db.models.knowledge_entry import KnowledgeEntry

            with get_db_session() as session:
                session.add(KnowledgeEntry(
                    id="faq-entry-2",
                    account_id=_TEST_ACCOUNT_ID,
                    title="Comment réinitialiser mot de passe",
                    content="Allez dans Paramètres > Sécurité.",
                    category="FAQ",
                    source="manual",
                ))

        with app.app_context():
            from app.faq_agent import process_faq_email

            # Mock LLM to return "NONE" (no FAQ matches pizza order)
            mock_llm_resp = MagicMock()
            mock_llm_resp.content = "NONE"
            mock_container = MagicMock()
            mock_container.llm_label.complete.return_value = mock_llm_resp

            with patch("app.infrastructure.container.get_container", return_value=mock_container):
                result = process_faq_email(
                    email_id="test-email-2",
                    email_subject="Pizza",
                    email_body="Bonjour, je voudrais commander 3 pizzas margherita.",
                    sender="user@example.com",
                    sender_name="User",
                    account_id=_TEST_ACCOUNT_ID,
                    config={"confidence_threshold": 80, "auto_send": True},
                )

        assert result is not None
        assert result.action == "skipped"

    def test_process_email_no_faq_entries(self, app):
        """No FAQ entries → returns None."""


        with app.app_context():
            from app.faq_agent import process_faq_email

            result = process_faq_email(
                email_id="test-email-3",
                email_subject="Question",
                email_body="How do I do something?",
                sender="user@example.com",
                sender_name="User",
                account_id=_TEST_ACCOUNT_ID,
                config={"confidence_threshold": 80},
            )

        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# 7. Full Flow
# ─────────────────────────────────────────────────────────────────────────────

class TestFaqFullFlow:

    def test_subscribe_configure_and_query_stats(self, client, app):
        """Full lifecycle: subscribe → config → create KB entry → query stats."""


        # 1. Subscribe
        resp = client.post("/api/agent-marketplace/faq/subscribe")
        assert resp.status_code == 200

        # 2. Configure
        resp = client.patch(
            "/api/agent-marketplace/faq/config",
            json={"confidence_threshold": 75, "reply_tone": "friendly", "auto_send": True},
        )
        assert resp.status_code == 200

        # 3. Create KB entry
        resp = client.post("/api/knowledge/entries", json={
            "title": "How to reset password",
            "content": "Go to Settings > Security > Reset.",
            "category": "FAQ",
            "account_id": _TEST_ACCOUNT_ID,
        })
        assert resp.status_code == 201

        # 4. Query stats (should be empty — no processing happened)
        resp = client.get(f"/api/agent-marketplace/faq/stats?account_id={_TEST_ACCOUNT_ID}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["auto_sent_count"] == 0

        # 5. Verify config persisted
        resp = client.get("/api/agent-marketplace/faq/config")
        data = resp.get_json()
        assert data["confidence_threshold"] == 75
        assert data["reply_tone"] == "friendly"

    def test_faq_agent_test_mode(self, app):
        """test_mode=True → generates draft but doesn't auto-send."""


        with app.app_context():
            from app.db.database import get_db_session
            from app.db.models.knowledge_entry import KnowledgeEntry

            with get_db_session() as session:
                session.add(KnowledgeEntry(
                    id="faq-test-mode",
                    account_id=_TEST_ACCOUNT_ID,
                    title="Comment réinitialiser mot de passe",
                    content="Allez dans Paramètres > Sécurité > Réinitialiser.",
                    category="FAQ",
                    source="manual",
                ))

        with app.app_context():
            from app.faq_agent import process_faq_email

            # Mock LLM to return "1" (first FAQ entry matches)
            mock_llm_resp = MagicMock()
            mock_llm_resp.content = "1"
            mock_container = MagicMock()
            mock_container.llm_label.complete.return_value = mock_llm_resp

            with patch("app.faq_agent._auto_send_faq") as mock_send, \
                 patch("app.faq_agent.generate_faq_response", return_value="Draft FAQ response"), \
                 patch("app.infrastructure.container.get_container", return_value=mock_container):
                result = process_faq_email(
                    email_id="test-email-tm",
                    email_subject="Mot de passe",
                    email_body="Comment réinitialiser mon mot de passe ?",
                    sender="user@example.com",
                    sender_name="User",
                    account_id=_TEST_ACCOUNT_ID,
                    config={"confidence_threshold": 30, "auto_send": True, "test_mode": True},
                )

            assert result is not None
            assert result.action == "draft_only"
            assert result.draft_body == "Draft FAQ response"
            # _auto_send_faq should NOT have been called (test mode)
            mock_send.assert_not_called()

    def test_smart_routing_faq_tier(self, app):
        """Mock FAQ agent installed + matching email → SmartRouter returns FAQ_AUTO."""
        with app.app_context():
            from app.faq_agent import FaqResult

            mock_faq_result = FaqResult(
                action="auto_sent",
                confidence=92.5,
                matched_entry_id="faq-routing",
                matched_entry_title="Comment réinitialiser mot de passe",
                draft_body="FAQ response body",
            )

            # Patch local imports at their source modules.
            # Force FAQ_AUTO_REPLY_ENABLED=True since the default is now False.
            with patch("app.api.settings.load_settings", return_value={"installed_agents": ["faq"]}), \
                 patch("app.faq_agent.process_faq_email", return_value=mock_faq_result), \
                 patch("app.api.agent_marketplace._load_agent_config", return_value={"confidence_threshold": 80}), \
                 patch("app.smart_routing.FAQ_AUTO_REPLY_ENABLED", True):

                from app.smart_routing import SmartRouter, RoutingTier

                router = SmartRouter.__new__(SmartRouter)
                router._style_metrics_cache = {}
                router._few_shot_cache = {}

                # Mock the account lookup so _faq_account_id resolves
                mock_acct = MagicMock()
                mock_acct.id = str(_TEST_ACCOUNT_ID)
                mock_repo = MagicMock()
                mock_repo.get_by_email.return_value = mock_acct

                with patch("app.db.repositories.account_repository.AccountRepository", return_value=mock_repo):
                    result = router.route(
                        email_content="De: user@example.com\nSujet: Mot de passe\n\nComment réinitialiser ?",
                        sender="user@example.com",
                        subject="Mot de passe",
                        body="Comment réinitialiser mon mot de passe ?",
                        email_id="test-routing",
                        sender_name="User",
                        user_email="test-faq@example.com",
                    )

                assert result is not None
                assert result.decision.tier == RoutingTier.FAQ_AUTO
                assert result.status == "FAQ_AUTO_SENT"

    def test_smart_routing_faq_manual_generation_stays_draft_only(self, app):
        """Manual draft generation disables FAQ auto-send even when globally enabled."""
        with app.app_context():
            from app.faq_agent import FaqResult

            mock_faq_result = FaqResult(
                action="draft_only",
                confidence=92.5,
                matched_entry_id="faq-routing-draft",
                matched_entry_title="Comment réinitialiser mot de passe",
                draft_body="FAQ response body",
                sent_message_id="must-not-leak",
            )

            with patch("app.api.settings.load_settings", return_value={"installed_agents": ["faq"]}), \
                 patch("app.faq_agent.process_faq_email", return_value=mock_faq_result) as mock_process, \
                 patch("app.api.agent_marketplace._load_agent_config", return_value={"confidence_threshold": 80, "auto_send": True}), \
                 patch("app.smart_routing.FAQ_AUTO_REPLY_ENABLED", True):

                from app.smart_routing import SmartRouter, RoutingTier

                router = SmartRouter.__new__(SmartRouter)
                router._style_metrics_cache = {}
                router._few_shot_cache = {}

                mock_acct = MagicMock()
                mock_acct.id = str(_TEST_ACCOUNT_ID)
                mock_repo = MagicMock()
                mock_repo.get_by_email.return_value = mock_acct

                with patch("app.db.repositories.account_repository.AccountRepository", return_value=mock_repo):
                    result = router.route(
                        email_content="De: user@example.com\nSujet: Mot de passe\n\nComment réinitialiser ?",
                        sender="user@example.com",
                        subject="Mot de passe",
                        body="Comment réinitialiser mon mot de passe ?",
                        email_id="test-routing-draft",
                        sender_name="User",
                        user_email="test-faq@example.com",
                        allow_faq_auto_send=False,
                    )

                assert result is not None
                assert result.decision.tier == RoutingTier.FAQ_AUTO
                assert result.status == "FAQ_DRAFT"
                assert result.faq_sent_message_id is None
                assert mock_process.call_args.kwargs["config"]["auto_send"] is False
