# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Module de sécurité pour Agentys.

Fournit:
- Chiffrement des données sensibles (credentials, tokens)
- Politique de rétention des données (RGPD)
- Purge automatique des anciennes données

Note: L'anonymisation est dans app.domain.services.anonymizer_service.
"""

import base64
import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.config import DATA_DIR, get_env, get_env_int

logger = logging.getLogger(__name__)


def _atomic_write_bytes(target: Path, data: bytes, mode: int = 0o600) -> None:
    """Atomic, restricted-permission write of binary data.

    Audit F-HIGH-4 (2026-04-25): both the salt and the encryption key files
    must survive partial writes (power loss, SIGKILL) and stay readable only
    by the owning process. We write to a sibling tempfile, chmod, fsync,
    then os.replace — atomic on POSIX, near-atomic on Windows (rename
    over existing).
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=target.name + ".", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        try:
            os.chmod(tmp_path, mode)
        except OSError:
            # Windows ignores POSIX modes — silent by design.
            pass
        os.replace(tmp_path, str(target))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ============================================================================
# CHIFFREMENT
# ============================================================================

class EncryptionManager:
    """
    Gestionnaire de chiffrement pour les données sensibles.

    Utilise Fernet (AES-128-CBC) pour le chiffrement symétrique.
    La clé est dérivée d'un secret ou générée automatiquement.
    """

    _key_file = DATA_DIR / ".encryption_key"
    _salt_file = DATA_DIR / ".encryption_salt"

    def __init__(self, secret_key: Optional[str] = None):
        """
        Initialise le gestionnaire de chiffrement.

        Args:
            secret_key: Clé secrète pour dériver la clé de chiffrement.
                       Si None, utilise la variable d'env ou génère une clé.
        """
        self._fernet: Optional[Fernet] = None
        self._init_encryption(secret_key)

    def _init_encryption(self, secret_key: Optional[str] = None) -> None:
        """Initialise le système de chiffrement."""
        secret = secret_key or get_env("ENCRYPTION_SECRET", None)

        if secret:
            # Dériver la clé depuis le secret
            key = self._derive_key(secret)
        else:
            # Charger ou générer une clé
            key = self._load_or_generate_key()

        self._fernet = Fernet(key)

    def _derive_key(self, secret: str) -> bytes:
        """Dérive une clé Fernet depuis un secret."""
        salt = self._get_or_create_salt()

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )

        key = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
        return key

    def _get_or_create_salt(self) -> bytes:
        """Récupère ou crée le salt pour la dérivation."""
        if self._salt_file.exists():
            return self._salt_file.read_bytes()

        salt = os.urandom(16)
        _atomic_write_bytes(self._salt_file, salt, mode=0o600)
        return salt

    def _load_or_generate_key(self) -> bytes:
        """Charge ou génère une clé de chiffrement."""
        if self._key_file.exists():
            return self._key_file.read_bytes()

        key = Fernet.generate_key()
        _atomic_write_bytes(self._key_file, key, mode=0o600)
        logger.info("Generated new encryption key")
        return key

    def encrypt(self, data: str) -> str:
        """
        Chiffre une chaîne de caractères.

        Args:
            data: Données à chiffrer

        Returns:
            Données chiffrées en base64
        """
        if not self._fernet:
            raise RuntimeError("Encryption not initialized")

        encrypted = self._fernet.encrypt(data.encode())
        return base64.urlsafe_b64encode(encrypted).decode()

    def decrypt(self, encrypted_data: str) -> str:
        """
        Déchiffre une chaîne de caractères.

        Args:
            encrypted_data: Données chiffrées en base64

        Returns:
            Données déchiffrées

        Raises:
            InvalidToken: Si les données sont corrompues ou la clé incorrecte
        """
        if not self._fernet:
            raise RuntimeError("Encryption not initialized")

        try:
            encrypted = base64.urlsafe_b64decode(encrypted_data.encode())
            return self._fernet.decrypt(encrypted).decode()
        except InvalidToken:
            logger.error("Failed to decrypt data: invalid token or corrupted data")
            raise

    def encrypt_dict(self, data: Dict[str, Any]) -> str:
        """Chiffre un dictionnaire en JSON."""
        return self.encrypt(json.dumps(data))

    def decrypt_dict(self, encrypted_data: str) -> Dict[str, Any]:
        """Déchiffre un dictionnaire depuis JSON."""
        return json.loads(self.decrypt(encrypted_data))

    def hash_email(self, email: str) -> str:
        """
        Génère un hash d'email pour anonymisation.

        Args:
            email: Adresse email à hasher

        Returns:
            Hash SHA-256 tronqué
        """
        return hashlib.sha256(email.lower().encode()).hexdigest()[:16]


# ============================================================================
# RETENTION ET PURGE (RGPD)
# ============================================================================

@dataclass
class RetentionPolicy:
    """Politique de rétention des données."""
    audit_logs_days: int = 90
    draft_history_days: int = 365
    cost_tracking_days: int = 365
    sent_emails_days: int = 90
    processed_emails_days: int = 30


class DataRetentionManager:
    """
    Gestionnaire de rétention des données pour conformité RGPD.

    Applique automatiquement les politiques de rétention:
    - Purge des données anciennes
    - Anonymisation avant archivage
    - Export des données utilisateur
    """

    def __init__(
        self,
        policy: Optional[RetentionPolicy] = None,
        db=None,
    ):
        """
        Initialise le gestionnaire de rétention.

        Args:
            policy: Politique de rétention (par défaut: 90 jours)
            db: Instance de Database pour les opérations SQLite
        """
        self.policy = policy or RetentionPolicy(
            audit_logs_days=get_env_int("RETENTION_AUDIT_DAYS", 90),
            draft_history_days=get_env_int("RETENTION_DRAFT_DAYS", 365),
            cost_tracking_days=get_env_int("RETENTION_COST_DAYS", 365),
            sent_emails_days=get_env_int("RETENTION_SENT_DAYS", 90),
            processed_emails_days=get_env_int("RETENTION_PROCESSED_DAYS", 30),
        )
        self._db = db

    def _get_db(self):
        """Récupère l'instance de base de données."""
        if self._db:
            return self._db
        # Import tardif pour éviter les dépendances circulaires
        from app.infrastructure.database import db
        return db

    def purge_old_data(self) -> Dict[str, int]:
        """
        Purge les données anciennes selon la politique.

        Returns:
            Dictionnaire avec le nombre d'enregistrements supprimés par table
        """
        db = self._get_db()
        results = {}

        # Purge audit_log
        cutoff = (datetime.now() - timedelta(days=self.policy.audit_logs_days)).isoformat()
        cursor = db.execute("DELETE FROM audit_log WHERE timestamp < ?", (cutoff,))
        db.commit()
        results["audit_log"] = cursor.rowcount

        # Purge draft_history
        cutoff = (datetime.now() - timedelta(days=self.policy.draft_history_days)).isoformat()
        cursor = db.execute("DELETE FROM draft_history WHERE created_at < ?", (cutoff,))
        db.commit()
        results["draft_history"] = cursor.rowcount

        # Purge cost_tracking
        cutoff = (datetime.now() - timedelta(days=self.policy.cost_tracking_days)).date().isoformat()
        cursor = db.execute("DELETE FROM cost_tracking WHERE date < ?", (cutoff,))
        db.commit()
        results["cost_tracking"] = cursor.rowcount

        # Purge sent_emails
        cutoff = (datetime.now() - timedelta(days=self.policy.sent_emails_days)).isoformat()
        cursor = db.execute("DELETE FROM sent_emails WHERE sent_at < ?", (cutoff,))
        db.commit()
        results["sent_emails"] = cursor.rowcount

        # Purge processed_emails
        cutoff = (datetime.now() - timedelta(days=self.policy.processed_emails_days)).isoformat()
        cursor = db.execute("DELETE FROM processed_emails WHERE processed_at < ?", (cutoff,))
        db.commit()
        results["processed_emails"] = cursor.rowcount

        total = sum(results.values())
        if total > 0:
            logger.info(f"Purged {total} old records: {results}")

        return results

    def get_retention_stats(self) -> Dict[str, Any]:
        """
        Retourne les statistiques de rétention.

        Returns:
            Dict avec les métriques de rétention par table
        """
        db = self._get_db()
        stats = {}

        tables = [
            ("audit_log", "timestamp", self.policy.audit_logs_days),
            ("draft_history", "created_at", self.policy.draft_history_days),
            ("cost_tracking", "date", self.policy.cost_tracking_days),
            ("sent_emails", "sent_at", self.policy.sent_emails_days),
            ("processed_emails", "processed_at", self.policy.processed_emails_days),
        ]

        for table, date_field, retention_days in tables:
            try:
                # Total records
                total = db.fetchone(f"SELECT COUNT(*) as count FROM {table}")

                # Expiring soon (next 7 days)
                cutoff = (datetime.now() - timedelta(days=retention_days - 7)).isoformat()
                expiring = db.fetchone(
                    f"SELECT COUNT(*) as count FROM {table} WHERE {date_field} < ?",
                    (cutoff,)
                )

                # Oldest record
                oldest = db.fetchone(f"SELECT MIN({date_field}) as oldest FROM {table}")

                stats[table] = {
                    "total_records": total['count'] if total else 0,
                    "expiring_soon": expiring['count'] if expiring else 0,
                    "retention_days": retention_days,
                    "oldest_record": oldest['oldest'] if oldest else None,
                }
            except Exception as e:
                logger.warning(f"Failed to get stats for {table}: {e}")
                stats[table] = {"error": str(e)}

        return stats

    def export_user_data(self, email: str) -> Dict[str, Any]:
        """
        Exporte toutes les données d'un utilisateur (droit d'accès RGPD).

        Args:
            email: Adresse email de l'utilisateur

        Returns:
            Dict avec toutes les données de l'utilisateur
        """
        db = self._get_db()

        export = {
            "export_date": datetime.now().isoformat(),
            "user_email": email,
            "data": {},
        }

        # Draft history
        drafts = db.fetchall(
            "SELECT * FROM draft_history WHERE email_sender LIKE ?",
            (f"%{email}%",)
        )
        export["data"]["draft_history"] = [dict(d) for d in drafts]

        # Sent emails
        sent = db.fetchall(
            "SELECT * FROM sent_emails WHERE recipient LIKE ?",
            (f"%{email}%",)
        )
        export["data"]["sent_emails"] = [dict(s) for s in sent]

        return export

    def delete_user_data(self, email: str) -> Dict[str, int]:
        """
        Supprime toutes les données d'un utilisateur (droit à l'oubli RGPD).

        Args:
            email: Adresse email de l'utilisateur

        Returns:
            Dict avec le nombre d'enregistrements supprimés par table
        """
        db = self._get_db()
        results = {}

        # Supprimer de draft_history
        cursor = db.execute(
            "DELETE FROM draft_history WHERE email_sender LIKE ?",
            (f"%{email}%",)
        )
        db.commit()
        results["draft_history"] = cursor.rowcount

        # Supprimer de sent_emails
        cursor = db.execute(
            "DELETE FROM sent_emails WHERE recipient LIKE ?",
            (f"%{email}%",)
        )
        db.commit()
        results["sent_emails"] = cursor.rowcount

        total = sum(results.values())
        logger.info(f"Deleted {total} records for user {email}: {results}")

        return results


# ============================================================================
# INSTANCES GLOBALES
# ============================================================================

encryption_manager = EncryptionManager()
data_retention_manager = DataRetentionManager()


def get_encryption_manager() -> EncryptionManager:
    """Retourne l'instance globale du gestionnaire de chiffrement."""
    return encryption_manager


def get_data_retention_manager() -> DataRetentionManager:
    """Retourne l'instance globale du gestionnaire de rétention."""
    return data_retention_manager
