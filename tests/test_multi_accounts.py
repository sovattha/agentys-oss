# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le support multi-comptes email.

pytest tests/test_multi_accounts.py -v
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.multi_accounts import (
    ProviderType,
    AccountStatus,
    AccountConfig,
    AccountStats,
    AccountManager,
    add_email_account,
    list_accounts,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def account_manager(tmp_path):
    """Crée un manager avec fichier temporaire."""
    filepath = tmp_path / "accounts.json"
    return AccountManager(filepath=filepath)


@pytest.fixture
def sample_account_data():
    """Données pour un compte de test."""
    return {
        "name": "Work Email",
        "email": "work@example.com",
        "provider": ProviderType.GMAIL,
        "credentials_path": "/path/to/credentials.json",
    }


# ============================================================================
# TESTS ENUMS
# ============================================================================

class TestEnums:
    """Tests pour les enums."""

    def test_provider_types(self):
        """Types de providers."""
        assert ProviderType.GMAIL.value == "gmail"
        assert ProviderType.OUTLOOK.value == "outlook"
        assert ProviderType.IMAP_SMTP.value == "imap_smtp"

    def test_account_status(self):
        """Statuts de compte."""
        assert AccountStatus.ACTIVE.value == "active"
        assert AccountStatus.INACTIVE.value == "inactive"
        assert AccountStatus.ERROR.value == "error"
        assert AccountStatus.RATE_LIMITED.value == "rate_limited"


# ============================================================================
# TESTS DATA MODELS
# ============================================================================

class TestAccountConfig:
    """Tests pour AccountConfig."""

    def test_creation(self):
        """Création d'une config."""
        config = AccountConfig(
            id="acc-001",
            name="Test Account",
            email="test@example.com",
            provider="gmail",
        )

        assert config.id == "acc-001"
        assert config.name == "Test Account"
        assert config.email == "test@example.com"
        assert config.provider == "gmail"

    def test_default_values(self):
        """Valeurs par défaut."""
        config = AccountConfig(
            id="acc-002",
            name="Account",
            email="test@test.com",
            provider="gmail",
        )

        assert config.check_interval_minutes == 5
        assert config.max_emails_per_batch == 10
        assert config.auto_reply_enabled is True
        assert config.draft_only is False
        assert config.default_language == "fr"
        assert config.status == "active"


class TestAccountStats:
    """Tests pour AccountStats."""

    def test_creation(self):
        """Création de stats."""
        stats = AccountStats(account_id="acc-001")

        assert stats.account_id == "acc-001"
        assert stats.emails_processed == 0
        assert stats.drafts_created == 0


# ============================================================================
# TESTS ACCOUNT MANAGER
# ============================================================================

class TestAccountManager:
    """Tests pour AccountManager."""

    def test_init_empty(self, account_manager):
        """Initialisation vide."""
        assert len(account_manager.accounts) == 0
        assert account_manager.current_account_id is None

    def test_add_account(self, account_manager, sample_account_data):
        """Ajout d'un compte."""
        account = account_manager.add_account(**sample_account_data)

        assert account.id is not None
        assert account.name == "Work Email"
        assert account.email == "work@example.com"
        assert account.provider == "gmail"
        assert account.id in account_manager.accounts

    def test_add_multiple_accounts(self, account_manager):
        """Ajout de plusieurs comptes."""
        acc1 = account_manager.add_account("Work", "work@ex.com", ProviderType.GMAIL)
        acc2 = account_manager.add_account("Personal", "personal@ex.com", ProviderType.OUTLOOK)

        assert len(account_manager.accounts) == 2
        assert acc1.id != acc2.id

    def test_update_account(self, account_manager, sample_account_data):
        """Mise à jour d'un compte."""
        account = account_manager.add_account(**sample_account_data)

        updated = account_manager.update_account(
            account.id,
            name="Updated Name",
            check_interval_minutes=10,
        )

        assert updated is not None
        assert updated.name == "Updated Name"
        assert updated.check_interval_minutes == 10

    def test_update_nonexistent(self, account_manager):
        """Mise à jour d'un compte inexistant."""
        result = account_manager.update_account("nonexistent", name="Test")
        assert result is None

    def test_remove_account(self, account_manager, sample_account_data):
        """Suppression d'un compte."""
        account = account_manager.add_account(**sample_account_data)

        result = account_manager.remove_account(account.id)

        assert result is True
        assert account.id not in account_manager.accounts

    def test_remove_current_account(self, account_manager, sample_account_data):
        """Suppression du compte actif."""
        account = account_manager.add_account(**sample_account_data)
        account_manager.switch_to(account.id)

        account_manager.remove_account(account.id)

        assert account_manager.current_account_id is None

    def test_remove_nonexistent(self, account_manager):
        """Suppression d'un compte inexistant."""
        result = account_manager.remove_account("nonexistent")
        assert result is False

    def test_get_account(self, account_manager, sample_account_data):
        """Récupération par ID."""
        account = account_manager.add_account(**sample_account_data)

        retrieved = account_manager.get_account(account.id)

        assert retrieved is not None
        assert retrieved.email == account.email

    def test_get_account_by_email(self, account_manager, sample_account_data):
        """Récupération par email."""
        account = account_manager.add_account(**sample_account_data)

        retrieved = account_manager.get_account_by_email("work@example.com")

        assert retrieved is not None
        assert retrieved.id == account.id

    def test_get_account_by_email_case_insensitive(self, account_manager, sample_account_data):
        """Récupération par email (case insensitive)."""
        account_manager.add_account(**sample_account_data)

        retrieved = account_manager.get_account_by_email("WORK@EXAMPLE.COM")

        assert retrieved is not None

    def test_get_active_accounts(self, account_manager):
        """Récupération des comptes actifs."""
        acc1 = account_manager.add_account("Active", "a@ex.com", ProviderType.GMAIL)
        acc2 = account_manager.add_account("Inactive", "b@ex.com", ProviderType.GMAIL)
        account_manager.update_account(acc2.id, status=AccountStatus.INACTIVE.value)

        active = account_manager.get_active_accounts()

        assert len(active) == 1
        assert active[0].id == acc1.id


# ============================================================================
# TESTS CONTEXT SWITCHING
# ============================================================================

class TestContextSwitching:
    """Tests pour le switching de contexte."""

    def test_switch_to(self, account_manager, sample_account_data):
        """Bascule vers un compte."""
        account = account_manager.add_account(**sample_account_data)

        context = account_manager.switch_to(account.id)

        assert context is not None
        assert context.account_id == account.id
        assert account_manager.current_account_id == account.id

    def test_switch_to_nonexistent(self, account_manager):
        """Bascule vers un compte inexistant."""
        context = account_manager.switch_to("nonexistent")
        assert context is None

    def test_switch_to_inactive_account(self, account_manager, sample_account_data):
        """Bascule vers un compte inactif (warning mais autorisé)."""
        account = account_manager.add_account(**sample_account_data)
        account_manager.update_account(account.id, status=AccountStatus.INACTIVE.value)

        context = account_manager.switch_to(account.id)

        assert context is not None  # Autorisé avec warning

    def test_get_current_context(self, account_manager, sample_account_data):
        """Récupération du contexte actif."""
        account = account_manager.add_account(**sample_account_data)
        account_manager.switch_to(account.id)

        context = account_manager.get_current_context()

        assert context is not None
        assert context.account_id == account.id

    def test_get_current_context_none(self, account_manager):
        """Pas de contexte actif."""
        context = account_manager.get_current_context()
        assert context is None

    def test_get_current_account(self, account_manager, sample_account_data):
        """Récupération du compte actif."""
        account = account_manager.add_account(**sample_account_data)
        account_manager.switch_to(account.id)

        current = account_manager.get_current_account()

        assert current is not None
        assert current.id == account.id

    def test_context_with_knowledge_base(self, account_manager, tmp_path):
        """Contexte avec knowledge base."""
        kb_path = tmp_path / "kb.md"
        kb_path.write_text("# My Knowledge Base\n\nContent here.")

        account = account_manager.add_account(
            name="With KB",
            email="kb@example.com",
            provider=ProviderType.GMAIL,
            knowledge_base_path=str(kb_path),
        )

        context = account_manager.switch_to(account.id)

        assert "My Knowledge Base" in context.knowledge_base


# ============================================================================
# TESTS FILTERING
# ============================================================================

class TestFiltering:
    """Tests pour le filtrage."""

    def test_sender_allowed_no_filters(self, account_manager, sample_account_data):
        """Expéditeur autorisé (pas de filtres)."""
        account = account_manager.add_account(**sample_account_data)

        result = account_manager.is_sender_allowed(account.id, "anyone@anywhere.com")

        assert result is True

    def test_sender_blocked(self, account_manager, sample_account_data):
        """Expéditeur bloqué."""
        sample_account_data["blocked_senders"] = ["spam@example.com"]
        account = account_manager.add_account(**sample_account_data)

        result = account_manager.is_sender_allowed(account.id, "spam@example.com")

        assert result is False

    def test_domain_blocked(self, account_manager, sample_account_data):
        """Domaine bloqué."""
        sample_account_data["blocked_domains"] = ["spam.com"]
        account = account_manager.add_account(**sample_account_data)

        result = account_manager.is_sender_allowed(account.id, "anyone@spam.com")

        assert result is False

    def test_sender_allowed_whitelist(self, account_manager, sample_account_data):
        """Whitelist d'expéditeurs."""
        sample_account_data["allowed_senders"] = ["vip@company.com"]
        account = account_manager.add_account(**sample_account_data)

        assert account_manager.is_sender_allowed(account.id, "vip@company.com") is True
        assert account_manager.is_sender_allowed(account.id, "other@company.com") is False

    def test_domain_allowed_whitelist(self, account_manager, sample_account_data):
        """Whitelist de domaines."""
        sample_account_data["allowed_domains"] = ["company.com"]
        account = account_manager.add_account(**sample_account_data)

        assert account_manager.is_sender_allowed(account.id, "anyone@company.com") is True
        assert account_manager.is_sender_allowed(account.id, "anyone@other.com") is False


# ============================================================================
# TESTS STATISTICS
# ============================================================================

class TestStatistics:
    """Tests pour les statistiques."""

    def test_update_stats(self, account_manager, sample_account_data):
        """Mise à jour des stats."""
        account = account_manager.add_account(**sample_account_data)

        account_manager.update_stats(
            account.id,
            emails_processed=5,
            drafts_created=3,
        )

        stats = account_manager.stats[account.id]
        assert stats.emails_processed == 5
        assert stats.drafts_created == 3

    def test_update_stats_cumulative(self, account_manager, sample_account_data):
        """Stats cumulatives."""
        account = account_manager.add_account(**sample_account_data)

        account_manager.update_stats(account.id, emails_processed=2)
        account_manager.update_stats(account.id, emails_processed=3)

        stats = account_manager.stats[account.id]
        assert stats.emails_processed == 5

    def test_get_stats_single_account(self, account_manager, sample_account_data):
        """Stats d'un seul compte."""
        account = account_manager.add_account(**sample_account_data)
        account_manager.update_stats(account.id, drafts_created=10)

        stats = account_manager.get_stats(account.id)

        assert stats["drafts_created"] == 10

    def test_get_stats_all(self, account_manager):
        """Stats globales."""
        acc1 = account_manager.add_account("A", "a@ex.com", ProviderType.GMAIL)
        acc2 = account_manager.add_account("B", "b@ex.com", ProviderType.OUTLOOK)

        account_manager.update_stats(acc1.id, emails_processed=10)
        account_manager.update_stats(acc2.id, emails_processed=20)

        stats = account_manager.get_stats()

        assert stats["total_accounts"] == 2
        assert stats["total_emails_processed"] == 30

    def test_update_account_status(self, account_manager, sample_account_data):
        """Mise à jour du statut."""
        account = account_manager.add_account(**sample_account_data)

        account_manager.update_account_status(
            account.id,
            AccountStatus.ERROR,
            error_message="Connection failed",
        )

        updated = account_manager.get_account(account.id)
        assert updated.status == "error"
        assert updated.last_error == "Connection failed"

    def test_mark_synced(self, account_manager, sample_account_data):
        """Marquage sync."""
        account = account_manager.add_account(**sample_account_data)

        account_manager.mark_synced(account.id)

        updated = account_manager.get_account(account.id)
        assert updated.last_sync is not None


# ============================================================================
# TESTS PERSISTENCE
# ============================================================================

class TestPersistence:
    """Tests pour la persistance."""

    def test_save_and_load(self, tmp_path, sample_account_data):
        """Sauvegarde et rechargement."""
        filepath = tmp_path / "accounts.json"

        # Créer et sauvegarder
        manager1 = AccountManager(filepath=filepath)
        account = manager1.add_account(**sample_account_data)
        manager1.switch_to(account.id)
        account_id = account.id

        # Recharger
        manager2 = AccountManager(filepath=filepath)

        assert account_id in manager2.accounts
        assert manager2.current_account_id == account_id

    def test_persistence_stats(self, tmp_path, sample_account_data):
        """Persistance des stats."""
        filepath = tmp_path / "accounts.json"

        manager1 = AccountManager(filepath=filepath)
        account = manager1.add_account(**sample_account_data)
        manager1.update_stats(account.id, emails_processed=50)

        manager2 = AccountManager(filepath=filepath)
        stats = manager2.get_stats(account.id)

        assert stats["emails_processed"] == 50


# ============================================================================
# TESTS HELPERS
# ============================================================================

class TestHelpers:
    """Tests pour les fonctions helper."""

    def test_add_email_account(self, tmp_path):
        """Ajout via helper."""
        with patch("app.multi_accounts._account_manager", None):
            with patch("app.multi_accounts.ACCOUNTS_FILE", tmp_path / "acc.json"):
                account = add_email_account(
                    name="Test",
                    email="test@example.com",
                    provider="gmail",
                )

                assert account.id is not None
                assert account.email == "test@example.com"

    def test_list_accounts(self, tmp_path):
        """Liste des comptes."""
        filepath = tmp_path / "accounts.json"
        manager = AccountManager(filepath=filepath)
        manager.add_account("A", "a@ex.com", ProviderType.GMAIL)
        manager.add_account("B", "b@ex.com", ProviderType.OUTLOOK)

        with patch("app.multi_accounts.get_account_manager", return_value=manager):
            accounts = list_accounts()

        assert len(accounts) == 2
        assert all("id" in a for a in accounts)


# ============================================================================
# TESTS EDGE CASES
# ============================================================================

class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_empty_manager_stats(self, account_manager):
        """Stats avec manager vide."""
        stats = account_manager.get_stats()

        assert stats["total_accounts"] == 0
        assert stats["total_emails_processed"] == 0

    def test_unicode_account_name(self, account_manager):
        """Nom de compte Unicode."""
        account = account_manager.add_account(
            name="Professionnel 🏢",
            email="pro@société.fr",
            provider=ProviderType.GMAIL,
        )

        assert "🏢" in account.name
        assert "société" in account.email

    def test_special_characters_in_email(self, account_manager):
        """Caractères spéciaux dans email."""
        account_manager.add_account(
            name="Special",
            email="user+tag@example.com",
            provider=ProviderType.GMAIL,
        )

        retrieved = account_manager.get_account_by_email("user+tag@example.com")
        assert retrieved is not None
