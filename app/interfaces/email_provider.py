# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Interface abstraite pour les fournisseurs d'email.

Cette abstraction permet de découpler le code métier des implémentations
spécifiques (Outlook, Gmail, etc.). Les agents ne voient que des StandardEmail.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple


class InsufficientScopeError(Exception):
    """Le token OAuth n'a pas le scope requis pour cette opération.

    Échec PERMANENT : re-tenter avec le même token ne réussira jamais
    (ex. ``users.messages.delete`` Gmail exige le scope complet
    ``https://mail.google.com/`` que l'app ne demande pas — décision
    produit 2026-06-09 : on ne demande pas ce scope restreint).
    Les appelants doivent désactiver l'opération pour ce compte au lieu
    de re-tenter (cf. tempête de retries de la purge auto, audit
    2026-06-09 : 2 107 erreurs 403 en 3 jours).
    """

    def __init__(self, message: str, *, required_scope: str | None = None):
        super().__init__(message)
        self.required_scope = required_scope


@dataclass
class EmailFolder:
    """
    Représentation normalisée d'un dossier email.

    Permet d'afficher les labels Gmail ou dossiers Outlook
    de manière uniforme dans l'interface.
    """
    id: str
    name: str
    display_name: str
    type: str = "custom"  # "inbox", "sent", "drafts", "spam", "trash", "custom"
    parent_id: Optional[str] = None
    unread_count: int = 0
    total_count: int = 0


@dataclass
class StandardEmail:
    """
    Représentation normalisée d'un email.

    Peu importe le fournisseur source (Outlook, Gmail, etc.),
    tous les emails sont convertis vers ce format standard.
    """
    id: str
    sender: str
    sender_name: Optional[str] = None
    to: List[str] = field(default_factory=list)
    cc: List[str] = field(default_factory=list)
    subject: str = ""
    body: str = ""
    body_html: Optional[str] = None
    received_at: Optional[datetime] = None
    is_read: bool = False
    has_attachments: bool = False
    attachments: list = field(default_factory=list)  # [{id, filename, size, content_type}]
    conversation_id: Optional[str] = None
    provider_source: str = "unknown"
    ical_text: Optional[str] = None  # Raw iCal/VCALENDAR content if a .ics part was found

    # Audit 2026-05-18: ``True`` when the raw ``sender_name`` carried
    # invisible/format characters (variation selectors, zero-width joiners)
    # OR mixed Latin with a Latin-lookalike script (Cyrillic / Greek). The
    # ingest path stamps this so the inbox can render a "Suspicious sender"
    # badge before the user clicks through.
    sender_spoofed: bool = False

    # Métadonnées brutes du provider (pour debug/audit)
    raw_metadata: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.provider_source}] {self.sender}: {self.subject}"

    @property
    def sender_display(self) -> str:
        """Retourne le nom de l'expéditeur ou son email."""
        return self.sender_name or self.sender

    @property
    def preview(self) -> str:
        """Retourne un aperçu du corps de l'email (100 premiers caractères)."""
        if not self.body:
            return ""
        return self.body[:100] + "..." if len(self.body) > 100 else self.body


class EmailProvider(ABC):
    """
    Interface abstraite pour les fournisseurs d'email.

    Toutes les implémentations concrètes (OutlookAdapter, GmailAdapter, etc.)
    doivent hériter de cette classe et implémenter ses méthodes abstraites.

    Cela garantit que le code métier reste agnostique du fournisseur.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Retourne le nom du fournisseur (ex: 'outlook', 'gmail')."""
        pass

    @abstractmethod
    def authenticate(self) -> bool:
        """
        Authentifie la connexion au fournisseur.

        Returns:
            True si l'authentification réussit, False sinon.
        """
        pass

    @abstractmethod
    def get_unread_messages(self, limit: int = 10) -> List[StandardEmail]:
        """
        Récupère les messages non lus.

        Args:
            limit: Nombre maximum de messages à récupérer.

        Returns:
            Liste d'emails normalisés (StandardEmail).
        """
        pass

    def get_messages(self, limit: int = 50, unread_only: bool = False, query: str = None) -> List[StandardEmail]:
        """
        Récupère les messages (tous ou non lus seulement).

        Args:
            limit: Nombre maximum de messages à récupérer.
            unread_only: Si True, ne retourne que les messages non lus.
            query: Provider-specific search query (e.g. Gmail q parameter).

        Returns:
            Liste d'emails normalisés (StandardEmail).
        """
        # Default implementation delegates to get_unread_messages for backward compatibility
        if unread_only:
            return self.get_unread_messages(limit=limit)
        # Subclasses should override this for full implementation
        return self.get_unread_messages(limit=limit)

    @abstractmethod
    def get_message_by_id(self, message_id: str) -> Optional[StandardEmail]:
        """
        Récupère un message spécifique par son ID.

        Args:
            message_id: Identifiant unique du message.

        Returns:
            L'email normalisé ou None si non trouvé.
        """
        pass

    @abstractmethod
    def create_draft(
        self,
        to: List[str],
        subject: str,
        body: str,
        reply_to_id: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        is_html: bool = False,
        attachments: Optional[List[Tuple[str, bytes, str]]] = None,
    ) -> Optional[str]:
        """
        Crée un brouillon d'email.

        Args:
            to: Liste des destinataires.
            subject: Sujet de l'email.
            body: Corps de l'email.
            reply_to_id: ID du message auquel répondre (optionnel).
            cc: Liste des destinataires en copie (optionnel).
            bcc: Liste des destinataires en copie cachée (optionnel).
            is_html: True si le corps est en HTML.
            attachments: Liste de tuples (filename, data, content_type) (optionnel).

        Returns:
            L'ID du brouillon créé, ou None en cas d'échec.
        """
        pass

    @abstractmethod
    def send_draft(self, draft_id: str) -> bool:
        """
        Envoie un brouillon existant.

        Args:
            draft_id: Identifiant du brouillon à envoyer.

        Returns:
            True si l'envoi réussit, False sinon.
        """
        pass

    @abstractmethod
    def mark_as_read(self, message_id: str) -> bool:
        """
        Marque un message comme lu.

        Args:
            message_id: Identifiant du message.

        Returns:
            True si l'opération réussit, False sinon.
        """
        pass

    @abstractmethod
    def mark_as_unread(self, message_id: str) -> bool:
        """
        Marque un message comme non lu.

        Args:
            message_id: Identifiant du message.

        Returns:
            True si l'opération réussit, False sinon.
        """
        pass

    def send_email(
        self,
        to: List[str],
        subject: str,
        body: str,
        reply_to_id: Optional[str] = None,
        cc: Optional[List[str]] = None,
        is_html: bool = False,
        attachments: Optional[List[Tuple[str, bytes, str]]] = None,
    ) -> bool:
        """
        Crée et envoie un email directement.

        Méthode de convenance qui combine create_draft() et send_draft().

        Returns:
            True si l'envoi réussit, False sinon.
        """
        draft_id = self.create_draft(
            to=to,
            subject=subject,
            body=body,
            reply_to_id=reply_to_id,
            cc=cc,
            is_html=is_html,
            attachments=attachments,
        )
        if draft_id:
            return self.send_draft(draft_id)
        return False

    def apply_label(self, message_id: str, label: str) -> bool:
        """
        Applique un label/catégorie à un message.

        Args:
            message_id: Identifiant du message.
            label: Nom du label à appliquer (ex: "URGENT", "NEWSLETTER").

        Returns:
            True si l'opération réussit, False sinon.

        Note:
            - Gmail: Crée le label s'il n'existe pas, puis l'applique
            - Outlook: Utilise les catégories (categories)
        """
        return False

    def restore_from_trash(self, message_id: str) -> bool:
        """
        Restaure un message de la corbeille vers la boîte de réception.

        Args:
            message_id: Identifiant du message.

        Returns:
            True si l'opération réussit, False sinon.
        """
        return False

    def move_to_inbox(self, message_id: str) -> bool:
        """
        Déplace un message du spam vers la boîte de réception.

        Args:
            message_id: Identifiant du message.

        Returns:
            True si l'opération réussit, False sinon.
        """
        return False

    def permanently_delete(self, message_id: str) -> bool:
        """
        Supprime définitivement un message (pas de corbeille).

        Utilisé par la file bulk_jobs pour les jobs de type
        ``delete_forever`` (auto-deletion, empty-trash, empty-spam).

        Default-False makes adapters that don't support permanent
        deletion (read-only IMAP, etc.) opt-out gracefully — the bulk
        worker treats a False return as a transient failure that retries
        twice before giving up. Overridden by Gmail / Outlook / IMAP
        adapters with their respective deleteForever / DELETE / EXPUNGE
        flows.
        """
        return False

    def move_to_spam(self, message_id: str) -> bool:
        """
        Déplace un message vers le dossier spam/indésirables.

        Args:
            message_id: Identifiant du message.

        Returns:
            True si l'opération réussit, False sinon.

        Note:
            - Gmail: Ajoute label "SPAM", retire "INBOX"
            - Outlook: Déplace vers dossier "junkemail"
        """
        return False

    @abstractmethod
    def get_user_drafts(self, limit: int = 50) -> List[StandardEmail]:
        """
        Récupère les brouillons créés par l'utilisateur.

        Cette méthode retourne les brouillons que l'utilisateur a créés
        manuellement dans sa boîte mail (pas les brouillons créés par le daemon).

        Args:
            limit: Nombre maximum de brouillons à récupérer.

        Returns:
            Liste de brouillons normalisés (StandardEmail).
            Chaque brouillon a raw_metadata["is_user_draft"] = True.
        """
        pass

    @abstractmethod
    def get_draft_by_id(self, draft_id: str) -> Optional[StandardEmail]:
        """
        Récupère un brouillon spécifique par son ID.

        Args:
            draft_id: Identifiant unique du brouillon.

        Returns:
            Le brouillon normalisé ou None si non trouvé.
        """
        pass

    @abstractmethod
    def update_draft(
        self,
        draft_id: str,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        to: Optional[List[str]] = None,
        cc: Optional[List[str]] = None,
        is_html: bool = False
    ) -> bool:
        """
        Met à jour un brouillon existant.

        Permet de mettre à jour le contenu d'un brouillon créé par
        l'utilisateur (par exemple après complétion par l'IA).

        Args:
            draft_id: Identifiant du brouillon à modifier.
            subject: Nouveau sujet (si None, conserve l'existant).
            body: Nouveau corps (si None, conserve l'existant).
            to: Nouvelle liste de destinataires (si None, conserve).
            cc: Nouvelle liste CC (si None, conserve).
            is_html: True si le body est en HTML.

        Returns:
            True si la mise à jour réussit, False sinon.
        """
        pass

    def get_sent_emails(self, limit: int = 50, since=None) -> List["StandardEmail"]:
        """
        Récupère les emails envoyés par l'utilisateur.

        Args:
            limit: Nombre maximum d'emails à récupérer.
            since: datetime optionnel — ne retourne que les emails après cette date.

        Returns:
            Liste d'emails normalisés (StandardEmail).
        """
        return []

    def list_folders(self) -> List["EmailFolder"]:
        """
        Liste les dossiers/labels de l'utilisateur.

        Returns:
            Liste de dossiers normalisés (EmailFolder).

        Note:
            - Gmail: Retourne les labels (système et utilisateur)
            - Outlook: Retourne les mail folders
            - IMAP: Retourne les dossiers IMAP
        """
        return []
