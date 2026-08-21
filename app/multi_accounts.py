# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Support multi-comptes email.

Ce module permet de gérer plusieurs comptes email avec configuration
et contexte spécifiques pour chaque compte.
"""

import os
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from enum import Enum

from app.config import DATA_DIR

logger = logging.getLogger(__name__)


def _invalidate_routes_account_id_cache(email: str | None) -> None:
    """ISO-12 fix: notify routes_helpers to drop a stale cached account_id.

    Lazily imported because `app.api.routes_helpers` itself imports from
    `app.multi_accounts` (`get_current_account`), so a top-level import
    here would create a circular dependency.
    """
    if not email:
        return
    try:
        from app.api.routes_helpers import _invalidate_account_id_cache as _inv
        _inv(email)
    except Exception as _err:
        # Best-effort — never block account mutations on a cache eviction
        # failure (e.g. during early boot before routes_helpers is loaded).
        logger.debug("ISO-12 cache invalidation failed for %s: %s", email, _err)


# ============================================================================
# CONFIGURATION
# ============================================================================

ACCOUNTS_FILE = DATA_DIR / "email_accounts.json"
MULTI_ACCOUNTS_ENABLED = os.getenv("MULTI_ACCOUNTS_ENABLED", "true").lower() == "true"


# ============================================================================
# ENUMS
# ============================================================================

class ProviderType(Enum):
    """Types de providers email supportés."""
    GMAIL = "gmail"
    OUTLOOK = "outlook"
    IMAP_SMTP = "imap_smtp"


class AccountStatus(Enum):
    """Statut d'un compte."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class AccountConfig:
    """Configuration d'un compte email."""
    id: str
    name: str
    email: str
    provider: str  # ProviderType value
    credentials_path: Optional[str] = None  # Path to credentials file

    # Configuration spécifique
    check_interval_minutes: int = 5
    max_emails_per_batch: int = 10
    auto_reply_enabled: bool = True
    draft_only: bool = False

    # Personnalisation
    knowledge_base_path: Optional[str] = None
    signature: Optional[str] = None
    signature_html: Optional[str] = None
    avatar_url: Optional[str] = None
    default_language: str = "fr"

    # IMAP/SMTP settings (for imap_smtp provider)
    imap_host: Optional[str] = None
    imap_port: Optional[int] = None
    imap_user: Optional[str] = None
    imap_password: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None

    # Filtres
    allowed_senders: Optional[List[str]] = None
    blocked_senders: Optional[List[str]] = None
    allowed_domains: Optional[List[str]] = None
    blocked_domains: Optional[List[str]] = None
    spammed_senders: Optional[List[str]] = None
    spammed_domains: Optional[List[str]] = None

    # Métadonnées
    status: str = field(default_factory=lambda: AccountStatus.ACTIVE.value)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_sync: Optional[str] = None
    last_error: Optional[str] = None
    email_count: int = 0

    # Multi-user isolation: links this account to a JWT user ID (None = legacy/Tauri)
    user_id: Optional[int] = None


@dataclass
class AccountContext:
    """Contexte actif pour un compte."""
    account_id: str
    knowledge_base: str
    settings: Dict[str, Any]
    active_since: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class AccountStats:
    """Statistiques d'un compte."""
    account_id: str
    emails_processed: int = 0
    drafts_created: int = 0
    drafts_sent: int = 0
    errors: int = 0
    avg_response_time_seconds: float = 0.0
    last_activity: Optional[str] = None


# ============================================================================
# ACCOUNT MANAGER
# ============================================================================

class AccountManager:
    """
    Gestionnaire des comptes email multiples.

    Permet de :
    - Ajouter/modifier/supprimer des comptes
    - Basculer entre comptes (switching de contexte)
    - Charger la configuration spécifique par compte
    """

    def __init__(self, filepath: Path = ACCOUNTS_FILE):
        self.filepath = filepath
        self.accounts: Dict[str, AccountConfig] = {}
        self.stats: Dict[str, AccountStats] = {}
        self._current_per_user: Dict[Optional[int], str] = {}  # {user_id: account_id}
        self._state_lock = threading.Lock()  # Protects _current_per_user reads/writes
        self._load()

    @property
    def current_account_id(self) -> Optional[str]:
        """Legacy getter for Tauri desktop (user_id=None)."""
        return self._current_per_user.get(None)

    @current_account_id.setter
    def current_account_id(self, value: Optional[str]) -> None:
        """Legacy setter for Tauri desktop (user_id=None)."""
        if value is None:
            self._current_per_user.pop(None, None)
        else:
            self._current_per_user[None] = value

    def get_current_for_user(self, user_id: Optional[int]) -> Optional[str]:
        """Retourne le current_account_id pour un user donné.
        Falls back to the None (desktop/Tauri) key only when user_id is None.
        Specific user IDs never fall back to the legacy key (multi-user isolation).
        """
        with self._state_lock:
            if user_id is not None:
                return self._current_per_user.get(user_id)
            return self._current_per_user.get(None)

    def set_current_for_user(self, account_id: str, user_id: Optional[int]) -> None:
        """Définit le current_account_id pour un user donné."""
        with self._state_lock:
            self._current_per_user[user_id] = account_id

    def _load(self) -> None:
        """Charge les comptes depuis le fichier."""
        if self.filepath.exists():
            try:
                # encoding="utf-8" obligatoire : _save() ecrit en utf-8 ;
                # sans ce parametre, read_text() utilise l'encodage plateforme
                # (cp1252 sur Windows) et un nom de compte accentue revient en
                # mojibake (UniversitÃ©). Cf. audit-2026-05-14 fix 117b2c8d.
                raw = self.filepath.read_text(encoding="utf-8")
                if not raw.strip():
                    logger.warning("Accounts file is empty; rewriting empty account state")
                    self._save()
                    return
                data = json.loads(raw)
                needs_save = False
                for acc_data in data.get("accounts", []):
                    acc = AccountConfig(**acc_data)
                    if acc.email:
                        try:
                            from app.account_identity import user_id_from_email
                            canonical_user_id = user_id_from_email(acc.email)
                            if acc.user_id != canonical_user_id:
                                logger.info(
                                    "Migrating AccountConfig user_id for %s: %s -> %s",
                                    acc.email,
                                    acc.user_id,
                                    canonical_user_id,
                                )
                                acc.user_id = canonical_user_id
                                needs_save = True
                        except Exception as exc:
                            logger.debug("AccountConfig user_id migration skipped: %s", exc)
                    self.accounts[acc.id] = acc

                for stat_data in data.get("stats", []):
                    stat = AccountStats(**stat_data)
                    self.stats[stat.account_id] = stat

                # Load per-user current accounts (backward compat with legacy single value)
                current_per_user = data.get("current_per_user")
                if current_per_user and isinstance(current_per_user, dict):
                    self._current_per_user = {
                        (int(k) if k != "null" else None): v
                        for k, v in current_per_user.items()
                    }
                else:
                    # Legacy: single current_account_id → map to user_id=None (Tauri)
                    legacy = data.get("current_account_id")
                    if legacy:
                        self._current_per_user[None] = legacy
                for acc in self.accounts.values():
                    if acc.user_id is not None and acc.id not in self._current_per_user.values():
                        continue
                    if acc.user_id is not None and self._current_per_user.get(acc.user_id) != acc.id:
                        self._current_per_user[acc.user_id] = acc.id
                        needs_save = True
                if needs_save:
                    self._save()

                logger.debug(f"Loaded {len(self.accounts)} email accounts")
            except Exception as e:
                logger.error(f"Error loading accounts: {e}")
        else:
            self._save()

    def _save(self) -> None:
        """Sauvegarde les comptes (avec retry sur file lock Windows)."""
        import time as _time
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "accounts": [asdict(a) for a in self.accounts.values()],
            "stats": [asdict(s) for s in self.stats.values()],
            # Per-user current accounts (keys serialized as strings, None → "null")
            "current_per_user": {
                ("null" if k is None else str(k)): v
                for k, v in self._current_per_user.items()
            },
            # Legacy field for backward compat (Tauri desktop reads this)
            "current_account_id": self.current_account_id,
            "updated_at": datetime.now().isoformat(),
        }
        content = json.dumps(data, indent=2, ensure_ascii=False)
        # Retry up to 3 times on Windows file lock errors (WinError 32)
        for attempt in range(3):
            tmp_path = self.filepath.with_name(
                f".{self.filepath.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            try:
                tmp_path.write_text(content, encoding="utf-8")
                os.replace(tmp_path, self.filepath)
                return
            except OSError as e:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
                if attempt < 2 and getattr(e, 'winerror', 0) == 32:
                    _time.sleep(0.1 * (attempt + 1))
                    continue
                raise

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    def add_account(
        self,
        name: str,
        email: str,
        provider: ProviderType,
        credentials_path: Optional[str] = None,
        **kwargs,
    ) -> AccountConfig:
        """
        Ajoute un nouveau compte.

        Args:
            name: Nom du compte (ex: "Travail", "Personnel")
            email: Adresse email
            provider: Type de provider (gmail, outlook, imap_smtp)
            credentials_path: Chemin vers le fichier de credentials
            **kwargs: Options supplémentaires

        Returns:
            AccountConfig créé
        """
        import uuid
        account_id = kwargs.pop("id", str(uuid.uuid4())[:8])

        # Deduplicate: if an account with this email already exists, update it
        existing = self.get_account_by_email(email)
        if existing:
            # FIX MIGRATE-001/004 (audit P0/P1): a re-add for the same email
            # MUST also reset the SQLite Account row's provider field +
            # last_history_id, otherwise:
            #   - the SQLite provider stays at the old value while the JSON
            #     AccountConfig flips to the new one → sync_service picks the
            #     wrong adapter (e.g. instantiates IMAPSMTPAdapter with no IMAP
            #     creds for an account that's actually now Gmail OAuth) →
            #     authenticate fails silently, sync does nothing forever
            #     (MIGRATE-004).
            #   - the stale last_history_id from the previous session is
            #     replayed against a fresh OAuth token; Google answers
            #     historyExpired, fallback full-sync deletes every cached
            #     email_id that didn't show up in the small fresh window
            #     → user's local cache silently wiped (MIGRATE-001).
            provider_changed = existing.provider != provider.value
            logger.info(
                f"Account with email {email} already exists (id={existing.id}), "
                f"updating instead of creating duplicate "
                f"(provider_changed={provider_changed})"
            )
            existing.name = name
            existing.provider = provider.value
            if credentials_path:
                existing.credentials_path = credentials_path
            existing.status = AccountStatus.ACTIVE.value
            self._save()

            # Sync the SQLite Account row with the new provider + reset sync
            # state so the next tick starts from a clean slate. Defensive:
            # any failure here is logged but doesn't abort the re-add — the
            # JSON AccountConfig has already been updated.
            try:
                from app.db.database import get_db_session
                from app.db.models.account import Account
                with get_db_session() as session:
                    db_acct = (
                        session.query(Account)
                        .filter(Account.email.ilike(email))
                        .first()
                    )
                    if db_acct is not None:
                        if provider_changed:
                            db_acct.provider = provider.value
                        # Always clear sync checkpoint on re-add — the new
                        # token may correspond to a different mailbox state
                        # even when the provider name is unchanged.
                        db_acct.last_history_id = None
                        db_acct.last_sync_at = None
                        db_acct.is_active = True
                        session.commit()
                        logger.info(
                            "MIGRATE-001/004: reset sync state for re-added "
                            f"account {email} (db_id={db_acct.id})"
                        )
            except Exception as e:
                logger.warning(
                    f"MIGRATE-001/004: failed to reset SQLite state for "
                    f"{email}: {e}"
                )

            # Drop any auth-backoff entry tied to the OLD session so the next
            # sync tick doesn't sleep waiting for the cooldown of a token
            # that no longer exists.
            try:
                from app.services.sync_service import get_sync_service
                svc = get_sync_service()
                if svc is not None and hasattr(svc, "evict_auth_backoff"):
                    svc.evict_auth_backoff(existing.id)
            except Exception as e:
                logger.debug(
                    f"MIGRATE-001/004: evict_auth_backoff skipped: {e}"
                )

            _invalidate_routes_account_id_cache(email)
            return existing

        account = AccountConfig(
            id=account_id,
            name=name,
            email=email,
            provider=provider.value,
            credentials_path=credentials_path,
            **kwargs,
        )

        self.accounts[account_id] = account
        self.stats[account_id] = AccountStats(account_id=account_id)
        self._save()

        # ISO-12 fix: bust the per-email account_id cache so subsequent
        # JWT-routed lookups see the new mapping immediately.
        _invalidate_routes_account_id_cache(email)

        logger.info(f"Account added: {name} ({email})")
        return account

    def update_account(self, account_id: str, **updates) -> Optional[AccountConfig]:
        """
        Met à jour un compte existant.

        Args:
            account_id: ID du compte
            **updates: Champs à mettre à jour

        Returns:
            AccountConfig mis à jour ou None
        """
        if account_id not in self.accounts:
            return None

        account = self.accounts[account_id]

        for key, value in updates.items():
            if hasattr(account, key):
                setattr(account, key, value)

        self._save()
        # ISO-12 fix: if the email was changed, evict both the old and the
        # new entry so the resolver re-fetches from DB.
        _invalidate_routes_account_id_cache(account.email)
        if "email" in updates:
            _invalidate_routes_account_id_cache(updates["email"])
        logger.info(f"Account updated: {account_id}")
        return account

    def remove_account(self, account_id: str) -> bool:
        """
        Supprime un compte.

        Args:
            account_id: ID du compte

        Returns:
            True si supprimé
        """
        if account_id not in self.accounts:
            return False

        # Capture the email BEFORE the delete so we can bust the cache.
        _removed_email = self.accounts[account_id].email

        del self.accounts[account_id]
        if account_id in self.stats:
            del self.stats[account_id]

        # Remove from all per-user current mappings
        for uid, aid in list(self._current_per_user.items()):
            if aid == account_id:
                del self._current_per_user[uid]

        self._save()
        # ISO-12 fix: prevent the resolver from returning the now-deleted
        # account's id for up to 60s after deletion.
        _invalidate_routes_account_id_cache(_removed_email)
        logger.info(f"Account removed: {account_id}")
        return True

    def get_account(self, account_id: str) -> Optional[AccountConfig]:
        """Récupère un compte par ID."""
        return self.accounts.get(account_id)

    def get_account_by_email(self, email: str) -> Optional[AccountConfig]:
        """Récupère un compte par adresse email."""
        for account in self.accounts.values():
            if account.email.lower() == email.lower():
                return account
        return None

    def deduplicate_accounts(self) -> int:
        """Remove duplicate accounts (same email), keeping the most recent one.

        Returns the number of duplicates removed.
        """
        seen_emails: Dict[str, str] = {}  # email → account_id (keeps last)
        duplicates: List[str] = []

        for account_id, account in self.accounts.items():
            email_lower = account.email.lower()
            if email_lower in seen_emails:
                # Keep the newer one (current entry), mark the old one as duplicate
                duplicates.append(seen_emails[email_lower])
            seen_emails[email_lower] = account_id

        for dup_id in duplicates:
            del self.accounts[dup_id]
            self.stats.pop(dup_id, None)
            # Clean up current_per_user refs pointing to removed accounts
            for uid, aid in list(self._current_per_user.items()):
                if aid == dup_id:
                    # Reassign to the surviving account
                    email = next((a.email for a in self.accounts.values()), None)
                    surviving = seen_emails.get(email.lower()) if email else None
                    if surviving:
                        self._current_per_user[uid] = surviving
                    else:
                        del self._current_per_user[uid]

        if duplicates:
            self._save()
            logger.info(f"Deduplicated {len(duplicates)} duplicate accounts")

        return len(duplicates)

    def get_all_accounts(self) -> List[AccountConfig]:
        """Retourne tous les comptes."""
        return list(self.accounts.values())

    def get_active_accounts(self) -> List[AccountConfig]:
        """Retourne les comptes actifs."""
        return [a for a in self.accounts.values()
                if a.status == AccountStatus.ACTIVE.value]

    # =========================================================================
    # Context Switching
    # =========================================================================

    def switch_to(
        self,
        account_id: str,
        user_id: Optional[int] = None,
        allow_first_time_bind: bool = True,
    ) -> Optional[AccountContext]:
        """
        Bascule vers un compte (un seul compte actif à la fois par user).

        Désactive tous les autres comptes de ce user avant d'activer celui-ci.

        F-08 (regression audit, 2026-04-29): the prior implementation
        only checked ``user_id`` in the deactivation loop — never against
        the ``account`` being activated. A caller could pass any
        ``user_id`` and pin ``_current_per_user[user_id]`` to a foreign
        account. Combined with the 4 oauth.py call sites that omitted
        ``user_id`` entirely, two concurrent OAuth completions could
        race-overwrite ``_current_per_user[None]`` so background sync
        paths processed the wrong tenant's mailbox.

        Audit follow-up 2026-04-29 (P2): ``allow_first_time_bind``
        defaults True (preserves OAuth-callback behavior — fresh account
        binds to caller). Cautious internal callers that walk legacy
        unbound accounts can pass ``False`` to refuse the implicit
        claim. The API ``/api/accounts/<id>/activate`` already refuses
        unbound-account claims via ``check_account_ownership``; this
        flag is defense-in-depth for non-API callers.

        New rules:
        - If ``account.user_id`` is set AND ``user_id`` is set AND they
          differ → refuse (cross-user activation).
        - If ``account.user_id`` is unset and ``user_id`` is set:
          * ``allow_first_time_bind=True``  → bind + log (default)
          * ``allow_first_time_bind=False`` → refuse + log (cautious)
        - Loopback (``user_id is None``) keeps legacy behavior.

        Args:
            account_id: ID du compte
            user_id: JWT user ID (None = Tauri desktop mode)
            allow_first_time_bind: see above

        Returns:
            AccountContext ou None si compte invalide ou cross-user refused
        """
        account = self.accounts.get(account_id)
        if not account:
            logger.error(f"Account not found: {account_id}")
            return None

        # F-08: refuse cross-user activation.
        if (
            account.user_id is not None
            and user_id is not None
            and account.user_id != user_id
        ):
            logger.warning(
                "[F-08] cross-user switch_to refused: account=%s "
                "account.user_id=%s caller.user_id=%s",
                account_id, account.user_id, user_id,
            )
            return None

        # F-08: first-time bind when account has no user_id yet (e.g.
        # freshly added by an OAuth callback). Subsequent activations
        # then enforce the binding via the guard above.
        if account.user_id is None and user_id is not None:
            if not allow_first_time_bind:
                logger.warning(
                    "[F-08] first-time bind refused (allow_first_time_bind=False): "
                    "account=%s caller.user_id=%s",
                    account_id, user_id,
                )
                return None
            logger.info(
                "[F-08] first-time bind: account=%s → user_id=%s",
                account_id, user_id,
            )
            account.user_id = user_id

        # Enforce single active account per user: deactivate others belonging to same user
        for aid, acc in self.accounts.items():
            if aid != account_id and acc.status == AccountStatus.ACTIVE.value:
                if acc.user_id == user_id:
                    acc.status = AccountStatus.INACTIVE.value
                    logger.info(f"Deactivated account {aid} ({acc.email})")

        # Activate the target account
        account.status = AccountStatus.ACTIVE.value

        self.set_current_for_user(account_id, user_id)
        self._save()

        # Charger la knowledge base du compte
        knowledge_base = ""
        if account.knowledge_base_path:
            kb_path = Path(account.knowledge_base_path)
            if kb_path.exists():
                knowledge_base = kb_path.read_text(encoding="utf-8")

        context = AccountContext(
            account_id=account_id,
            knowledge_base=knowledge_base,
            settings={
                "check_interval_minutes": account.check_interval_minutes,
                "max_emails_per_batch": account.max_emails_per_batch,
                "auto_reply_enabled": account.auto_reply_enabled,
                "draft_only": account.draft_only,
                "signature": account.signature,
                "default_language": account.default_language,
            },
        )

        logger.info(f"Switched to account: {account.name} ({account.email})")
        return context

    def get_current_context(self) -> Optional[AccountContext]:
        """Retourne le contexte du compte actif."""
        if not self.current_account_id:
            return None
        return self.switch_to(self.current_account_id)

    def get_current_account(self) -> Optional[AccountConfig]:
        """Retourne le compte actif."""
        if not self.current_account_id:
            return None
        return self.accounts.get(self.current_account_id)

    # =========================================================================
    # Filtering
    # =========================================================================

    @staticmethod
    def _extract_email(sender: str) -> str:
        """
        Extrait l'adresse email d'une chaîne sender.

        Gère les formats :
        - "john@example.com"
        - "John Doe <john@example.com>"
        - "<john@example.com>"

        Returns:
            L'adresse email en minuscules, ou la chaîne originale en minuscules.
        """
        import re
        match = re.search(r'<([^>]+)>', sender)
        if match:
            return match.group(1).strip().lower()
        return sender.strip().lower()

    def is_sender_allowed(self, account_id: str, sender: str) -> bool:
        """
        Vérifie si un expéditeur est autorisé.

        Args:
            account_id: ID du compte
            sender: Adresse de l'expéditeur (peut inclure un nom d'affichage)

        Returns:
            True si autorisé
        """
        account = self.accounts.get(account_id)
        if not account:
            return True  # Pas de filtre

        sender_email = self._extract_email(sender)

        # Vérifier les bloqués (comparaison exacte sur l'email extrait)
        if account.blocked_senders:
            if sender_email in [s.lower() for s in account.blocked_senders]:
                return False

        # Extraire le domaine
        domain = ""
        if "@" in sender_email:
            domain = sender_email.split("@")[1]

        if domain and account.blocked_domains:
            if domain in [d.lower() for d in account.blocked_domains]:
                return False

        # Si whitelist activée, vérifier (comparaison exacte)
        if account.allowed_senders:
            if sender_email not in [s.lower() for s in account.allowed_senders]:
                return False

        if domain and account.allowed_domains:
            if domain not in [d.lower() for d in account.allowed_domains]:
                return False

        return True

    # =========================================================================
    # Statistics
    # =========================================================================

    def update_stats(
        self,
        account_id: str,
        emails_processed: int = 0,
        drafts_created: int = 0,
        drafts_sent: int = 0,
        errors: int = 0,
        response_time: Optional[float] = None,
    ) -> None:
        """
        Met à jour les statistiques d'un compte.

        Args:
            account_id: ID du compte
            emails_processed: Nombre d'emails traités
            drafts_created: Nombre de brouillons créés
            drafts_sent: Nombre de brouillons envoyés
            errors: Nombre d'erreurs
            response_time: Temps de réponse en secondes
        """
        if account_id not in self.stats:
            self.stats[account_id] = AccountStats(account_id=account_id)

        stat = self.stats[account_id]
        stat.emails_processed += emails_processed
        stat.drafts_created += drafts_created
        stat.drafts_sent += drafts_sent
        stat.errors += errors

        if response_time is not None:
            # Moyenne mobile
            count = stat.emails_processed or 1
            stat.avg_response_time_seconds = (
                (stat.avg_response_time_seconds * (count - 1) + response_time) / count
            )

        stat.last_activity = datetime.now().isoformat()
        self._save()

    def get_stats(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Retourne les statistiques.

        Args:
            account_id: ID du compte (None pour tous)

        Returns:
            Dictionnaire de statistiques
        """
        if account_id:
            stat = self.stats.get(account_id)
            if stat:
                return asdict(stat)
            return {}

        # Stats globales
        total_stats = {
            "total_accounts": len(self.accounts),
            "active_accounts": len(self.get_active_accounts()),
            "total_emails_processed": sum(s.emails_processed for s in self.stats.values()),
            "total_drafts_created": sum(s.drafts_created for s in self.stats.values()),
            "total_drafts_sent": sum(s.drafts_sent for s in self.stats.values()),
            "total_errors": sum(s.errors for s in self.stats.values()),
            "accounts": [asdict(s) for s in self.stats.values()],
        }

        return total_stats

    def update_account_status(
        self,
        account_id: str,
        status: AccountStatus,
        error_message: Optional[str] = None,
    ) -> None:
        """
        Met à jour le statut d'un compte.

        Args:
            account_id: ID du compte
            status: Nouveau statut
            error_message: Message d'erreur optionnel
        """
        if account_id not in self.accounts:
            return

        account = self.accounts[account_id]
        account.status = status.value

        if error_message:
            account.last_error = error_message

        self._save()
        logger.info(f"Account {account_id} status updated to: {status.value}")

    def mark_synced(self, account_id: str) -> None:
        """Marque un compte comme synchronisé."""
        if account_id in self.accounts:
            self.accounts[account_id].last_sync = datetime.now().isoformat()
            self._save()


# ============================================================================
# SINGLETON & HELPERS
# ============================================================================

_account_manager: Optional[AccountManager] = None


def get_account_manager() -> AccountManager:
    """Retourne le gestionnaire de comptes singleton."""
    global _account_manager
    if _account_manager is None:
        _account_manager = AccountManager()
    return _account_manager


def add_email_account(
    name: str,
    email: str,
    provider: str,
    credentials_path: Optional[str] = None,
    **kwargs,
) -> AccountConfig:
    """
    Ajoute un compte email.

    Args:
        name: Nom du compte
        email: Adresse email
        provider: Type de provider (gmail, outlook, imap_smtp)
        credentials_path: Chemin vers les credentials
        **kwargs: Options supplémentaires

    Returns:
        AccountConfig créé
    """
    manager = get_account_manager()
    provider_type = ProviderType(provider)
    return manager.add_account(name, email, provider_type, credentials_path, **kwargs)


def switch_account(
    account_id: str,
    user_id: Optional[int] = None,
    allow_first_time_bind: bool = True,
) -> Optional[AccountContext]:
    """
    Bascule vers un compte.

    Args:
        account_id: ID du compte
        user_id: JWT user ID (None = mode Tauri desktop)
        allow_first_time_bind: refuse l'association implicite si False

    Returns:
        AccountContext ou None
    """
    manager = get_account_manager()
    return manager.switch_to(
        account_id,
        user_id=user_id,
        allow_first_time_bind=allow_first_time_bind,
    )


def get_current_account() -> Optional[AccountConfig]:
    """Retourne le compte actif."""
    manager = get_account_manager()
    return manager.get_current_account()


def list_accounts() -> List[Dict[str, Any]]:
    """
    Liste tous les comptes.

    Returns:
        Liste des comptes avec leurs infos
    """
    manager = get_account_manager()
    return [
        {
            "id": a.id,
            "name": a.name,
            "email": a.email,
            "provider": a.provider,
            "status": a.status,
            "is_current": a.id == manager.current_account_id,
        }
        for a in manager.get_all_accounts()
    ]


def create_provider_for_account(account: AccountConfig):
    """
    Crée une instance de provider pour un compte.

    Args:
        account: Configuration du compte

    Returns:
        Instance EmailProvider
    """
    from app.providers.gmail_adapter import GmailAdapter
    from app.providers.outlook_adapter import OutlookAdapter
    from app.providers.smtp_adapter import IMAPSMTPAdapter

    provider_type = ProviderType(account.provider)

    if provider_type == ProviderType.GMAIL:
        return GmailAdapter(
            credentials_file=account.credentials_path,
            account_id=account.id
        )
    elif provider_type == ProviderType.OUTLOOK:
        return OutlookAdapter(account_id=account.id)
    elif provider_type == ProviderType.IMAP_SMTP:
        return IMAPSMTPAdapter(
            imap_host=account.imap_host,
            imap_port=account.imap_port,
            imap_username=account.imap_user,
            imap_password=account.imap_password,
            smtp_host=account.smtp_host,
            smtp_port=account.smtp_port,
            smtp_username=account.smtp_user,
            smtp_password=account.smtp_password,
        )
    else:
        raise ValueError(f"Unknown provider type: {account.provider}")
