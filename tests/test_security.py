# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le module de sécurité.

Couvre:
- Chiffrement/Déchiffrement
- Anonymisation des données
- Rétention et purge RGPD
"""

import pytest
from unittest.mock import MagicMock, patch

from cryptography.fernet import InvalidToken

from app.infrastructure.security import (
    EncryptionManager,
    DataRetentionManager,
    RetentionPolicy,
)


class TestEncryptionManager:
    """Tests pour le gestionnaire de chiffrement."""

    def test_encrypt_decrypt_string(self, tmp_path):
        """Chiffre et déchiffre une chaîne."""
        with patch.object(EncryptionManager, '_key_file', tmp_path / "key"):
            with patch.object(EncryptionManager, '_salt_file', tmp_path / "salt"):
                manager = EncryptionManager()

                original = "secret data 123"
                encrypted = manager.encrypt(original)

                assert encrypted != original
                assert manager.decrypt(encrypted) == original

    def test_encrypt_decrypt_unicode(self, tmp_path):
        """Supporte les caractères unicode."""
        with patch.object(EncryptionManager, '_key_file', tmp_path / "key"):
            with patch.object(EncryptionManager, '_salt_file', tmp_path / "salt"):
                manager = EncryptionManager()

                original = "Bonjour le monde! Éàü 日本語"
                encrypted = manager.encrypt(original)

                assert manager.decrypt(encrypted) == original

    def test_encrypt_decrypt_dict(self, tmp_path):
        """Chiffre et déchiffre un dictionnaire."""
        with patch.object(EncryptionManager, '_key_file', tmp_path / "key"):
            with patch.object(EncryptionManager, '_salt_file', tmp_path / "salt"):
                manager = EncryptionManager()

                original = {"key": "value", "number": 123, "list": [1, 2, 3]}
                encrypted = manager.encrypt_dict(original)

                assert manager.decrypt_dict(encrypted) == original

    def test_different_encryptions(self, tmp_path):
        """Chaque chiffrement est différent (IV aléatoire)."""
        with patch.object(EncryptionManager, '_key_file', tmp_path / "key"):
            with patch.object(EncryptionManager, '_salt_file', tmp_path / "salt"):
                manager = EncryptionManager()

                original = "test data"
                encrypted1 = manager.encrypt(original)
                encrypted2 = manager.encrypt(original)

                assert encrypted1 != encrypted2
                assert manager.decrypt(encrypted1) == manager.decrypt(encrypted2)

    def test_key_persistence(self, tmp_path):
        """La clé est persistée entre instances."""
        key_file = tmp_path / "key"
        salt_file = tmp_path / "salt"

        with patch.object(EncryptionManager, '_key_file', key_file):
            with patch.object(EncryptionManager, '_salt_file', salt_file):
                manager1 = EncryptionManager()
                encrypted = manager1.encrypt("test")

                manager2 = EncryptionManager()
                assert manager2.decrypt(encrypted) == "test"

    def test_secret_key_derivation(self, tmp_path):
        """Une clé secrète produit une dérivation déterministe."""
        with patch.object(EncryptionManager, '_key_file', tmp_path / "key"):
            with patch.object(EncryptionManager, '_salt_file', tmp_path / "salt"):
                manager1 = EncryptionManager(secret_key="my-secret-key")
                encrypted = manager1.encrypt("test")

                manager2 = EncryptionManager(secret_key="my-secret-key")
                assert manager2.decrypt(encrypted) == "test"

    def test_wrong_key_fails(self, tmp_path):
        """Une mauvaise clé échoue au déchiffrement."""
        with patch.object(EncryptionManager, '_key_file', tmp_path / "key1"):
            with patch.object(EncryptionManager, '_salt_file', tmp_path / "salt"):
                manager1 = EncryptionManager(secret_key="key1")
                encrypted = manager1.encrypt("test")

        with patch.object(EncryptionManager, '_key_file', tmp_path / "key2"):
            with patch.object(EncryptionManager, '_salt_file', tmp_path / "salt2"):
                manager2 = EncryptionManager(secret_key="key2")

                with pytest.raises(InvalidToken):
                    manager2.decrypt(encrypted)

    def test_hash_email(self, tmp_path):
        """Hash d'email pour anonymisation."""
        with patch.object(EncryptionManager, '_key_file', tmp_path / "key"):
            with patch.object(EncryptionManager, '_salt_file', tmp_path / "salt"):
                manager = EncryptionManager()

                hash1 = manager.hash_email("test@example.com")
                hash2 = manager.hash_email("TEST@EXAMPLE.COM")

                assert hash1 == hash2  # Case insensitive
                assert len(hash1) == 16


class TestDataRetentionManager:
    """Tests pour le gestionnaire de rétention."""

    @pytest.fixture
    def mock_db(self):
        """Mock de la base de données."""
        db = MagicMock()
        db.execute.return_value = MagicMock(rowcount=5)
        db.fetchone.return_value = {"count": 10, "oldest": "2024-01-01"}
        db.fetchall.return_value = []
        return db

    def test_purge_old_data(self, mock_db):
        """Purge les données anciennes."""
        manager = DataRetentionManager(db=mock_db)

        results = manager.purge_old_data()

        assert "audit_log" in results
        assert "draft_history" in results
        assert mock_db.execute.called
        assert mock_db.commit.called

    def test_custom_retention_policy(self, mock_db):
        """Utilise une politique personnalisée."""
        policy = RetentionPolicy(
            audit_logs_days=30,
            draft_history_days=60,
        )
        manager = DataRetentionManager(policy=policy, db=mock_db)

        assert manager.policy.audit_logs_days == 30
        assert manager.policy.draft_history_days == 60

    def test_get_retention_stats(self, mock_db):
        """Retourne les statistiques de rétention."""
        manager = DataRetentionManager(db=mock_db)

        stats = manager.get_retention_stats()

        assert "audit_log" in stats
        assert "draft_history" in stats

    def test_export_user_data(self, mock_db):
        """Exporte les données d'un utilisateur."""
        manager = DataRetentionManager(db=mock_db)

        export = manager.export_user_data("user@example.com")

        assert "export_date" in export
        assert "user_email" in export
        assert "data" in export

    def test_delete_user_data(self, mock_db):
        """Supprime les données d'un utilisateur."""
        manager = DataRetentionManager(db=mock_db)

        results = manager.delete_user_data("user@example.com")

        assert "draft_history" in results
        assert "sent_emails" in results
        assert mock_db.execute.called


class TestRetentionPolicy:
    """Tests pour RetentionPolicy."""

    def test_default_values(self):
        """Valeurs par défaut correctes."""
        policy = RetentionPolicy()

        assert policy.audit_logs_days == 90
        assert policy.draft_history_days == 365
        assert policy.cost_tracking_days == 365
        assert policy.sent_emails_days == 90
        assert policy.processed_emails_days == 30

    def test_custom_values(self):
        """Valeurs personnalisées."""
        policy = RetentionPolicy(
            audit_logs_days=30,
            draft_history_days=180,
        )

        assert policy.audit_logs_days == 30
        assert policy.draft_history_days == 180


