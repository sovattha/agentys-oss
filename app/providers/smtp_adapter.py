# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adaptateur SMTP pour l'envoi d'emails.

Implémente partiellement EmailProvider - uniquement les méthodes d'envoi.
Pour la lecture, utilisez IMAPAdapter ou un autre adaptateur.
"""

import os
import smtplib
import logging
import uuid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import List, Optional, Tuple

from app.interfaces.email_provider import EmailProvider, StandardEmail

logger = logging.getLogger(__name__)


class SMTPAdapter(EmailProvider):
    """
    Adaptateur SMTP pour l'envoi d'emails.

    Fonctionne avec tout serveur SMTP (Gmail, Outlook, serveurs privés, etc.)

    Variables d'environnement :
    - SMTP_HOST : Serveur SMTP (ex: smtp.gmail.com)
    - SMTP_PORT : Port (587 pour TLS, 465 pour SSL, 25 sans chiffrement)
    - SMTP_USER : Nom d'utilisateur / email
    - SMTP_PASSWORD : Mot de passe ou App Password
    - SMTP_USE_TLS : Utiliser TLS (true par défaut)
    - SMTP_USE_SSL : Utiliser SSL (false par défaut)
    - SMTP_FROM_EMAIL : Adresse expéditeur (par défaut = SMTP_USER)
    - SMTP_FROM_NAME : Nom d'affichage de l'expéditeur

    Serveurs courants :
    - Gmail: smtp.gmail.com:587 (TLS) ou smtp.gmail.com:465 (SSL)
    - Outlook: smtp.office365.com:587 (TLS)
    - Yahoo: smtp.mail.yahoo.com:587 (TLS)
    """

    PROVIDER_NAME = "smtp"

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        use_tls: bool = True,
        use_ssl: bool = False,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
    ):
        """
        Initialise l'adaptateur SMTP.

        Args:
            host: Serveur SMTP
            port: Port (587 TLS, 465 SSL, 25 non chiffré)
            username: Nom d'utilisateur
            password: Mot de passe
            use_tls: Utiliser STARTTLS
            use_ssl: Utiliser SSL direct
            from_email: Adresse expéditeur
            from_name: Nom d'affichage
        """
        self.host = host or os.getenv("SMTP_HOST")
        self.username = username or os.getenv("SMTP_USER")
        self.password = password or os.getenv("SMTP_PASSWORD")

        # Fail fast on missing config. Without this, ``authenticate()`` would
        # call ``smtplib.SMTP_SSL(None, port)`` which leaves the socket
        # un-opened, and the next ``ehlo()`` raises the cryptic
        # ``please run connect() first`` from smtplib — hiding the actual
        # cause (no SMTP_HOST set). The factory wraps ValueError into a
        # clear ProviderConfigurationError, so ops sees the real problem.
        missing: list[str] = []
        if not self.host:
            missing.append("SMTP_HOST")
        if not self.username:
            missing.append("SMTP_USER")
        if not self.password:
            missing.append("SMTP_PASSWORD")
        if missing:
            raise ValueError(
                "SMTP configuration incomplete — missing: "
                + ", ".join(missing)
            )

        # Gestion TLS/SSL
        env_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
        env_ssl = os.getenv("SMTP_USE_SSL", "false").lower() == "true"
        self.use_tls = use_tls if use_tls is not None else env_tls
        self.use_ssl = use_ssl if use_ssl is not None else env_ssl

        # Port par défaut selon le mode
        default_port = "465" if self.use_ssl else ("587" if self.use_tls else "25")
        self.port = port or int(os.getenv("SMTP_PORT", default_port))

        # Expéditeur
        self.from_email = from_email or os.getenv("SMTP_FROM_EMAIL", self.username)
        self.from_name = from_name or os.getenv("SMTP_FROM_NAME")

        self._connection: Optional[smtplib.SMTP | smtplib.SMTP_SSL] = None
        self._authenticated = False

    @property
    def provider_name(self) -> str:
        return self.PROVIDER_NAME

    def authenticate(self) -> bool:
        """
        Authentifie via SMTP.

        Returns:
            True si l'authentification réussit.
        """
        try:
            # Auto-détection SSL par port (465 = SSL direct)
            use_ssl = self.use_ssl or self.port == 465
            use_tls = self.use_tls and not use_ssl

            # Connexion selon le mode
            if use_ssl:
                self._connection = smtplib.SMTP_SSL(self.host, self.port)
                self._connection.ehlo()
            else:
                self._connection = smtplib.SMTP(self.host, self.port)
                self._connection.ehlo()
                if use_tls:
                    self._connection.starttls()
                    self._connection.ehlo()  # Re-annonce les capacités après TLS (RFC 3207)

            # Authentification
            self._connection.login(self.username, self.password)
            self._authenticated = True
            logger.info(f"[OK] Authentification SMTP réussie ({self.host})")
            return True

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"[FAIL] Authentification SMTP échouée: {e}")
            self._authenticated = False
            return False

        except Exception as e:
            logger.error(f"[FAIL] Erreur connexion SMTP: {e}")
            self._authenticated = False
            return False

    def _ensure_authenticated(self) -> None:
        """S'assure que la connexion est établie."""
        if not self._authenticated or not self._connection:
            if not self.authenticate():
                raise RuntimeError("Authentification SMTP requise")

    def _create_message(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        is_html: bool = False,
        reply_to: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        attachments: Optional[List[Tuple[str, bytes, str]]] = None,
        idempotency_key: Optional[str] = None,
    ) -> MIMEMultipart:
        """
        Crée un message MIME.

        Args:
            attachments: Liste de tuples (filename, data, content_type).
        """
        # Use "mixed" if attachments, "alternative" otherwise
        msg = MIMEMultipart("mixed" if attachments else "alternative")

        # Headers
        if self.from_name:
            msg["From"] = f"{self.from_name} <{self.from_email}>"
        else:
            msg["From"] = self.from_email

        msg["To"] = ", ".join(to)
        msg["Subject"] = subject

        if cc:
            msg["Cc"] = ", ".join(cc)

        if reply_to:
            msg["Reply-To"] = reply_to

        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to

        if idempotency_key:
            message_id = idempotency_key.strip()
            if not message_id.startswith("<"):
                message_id = f"<{message_id}>"
            msg["Message-ID"] = message_id
            msg["X-Agentys-Idempotency-Key"] = idempotency_key

        # Corps
        if is_html:
            msg.attach(MIMEText(body, "html", "utf-8"))
        else:
            msg.attach(MIMEText(body, "plain", "utf-8"))

        # Pièces jointes
        if attachments:
            for filename, data, content_type in attachments:
                maintype, subtype = content_type.split("/", 1) if "/" in content_type else ("application", "octet-stream")
                part = MIMEBase(maintype, subtype)
                part.set_payload(data)
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", "attachment", filename=filename)
                msg.attach(part)

        return msg

    # ===== Méthodes de lecture (non supportées par SMTP) =====

    def get_unread_messages(self, limit: int = 10) -> List[StandardEmail]:
        """SMTP ne peut pas lire d'emails. Utilisez IMAPAdapter."""
        logger.warning("SMTP ne peut pas lire d'emails. Utilisez IMAPAdapter.")
        return []

    def get_message_by_id(self, message_id: str) -> Optional[StandardEmail]:
        """SMTP ne peut pas lire d'emails. Utilisez IMAPAdapter."""
        logger.warning("SMTP ne peut pas lire d'emails. Utilisez IMAPAdapter.")
        return None

    # ===== Méthodes d'envoi (supportées) =====

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
        from_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        SMTP ne supporte pas les brouillons.
        Cette méthode stocke le brouillon en mémoire et retourne un ID temporaire.
        """
        # Stocker en mémoire (pour send_draft)
        if not hasattr(self, "_drafts"):
            self._drafts = {}

        import time
        draft_id = f"smtp-draft-{int(time.time() * 1000)}"

        self._drafts[draft_id] = {
            "to": to,
            "subject": subject,
            "body": body,
            "cc": cc,
            "bcc": bcc,
            "is_html": is_html,
            "reply_to_id": reply_to_id,
            "attachments": attachments,
        }

        logger.info(f"Brouillon SMTP créé en mémoire: {draft_id}")
        return draft_id

    def send_draft(self, draft_id: str) -> bool:
        """Envoie un brouillon stocké en mémoire."""
        if not hasattr(self, "_drafts") or draft_id not in self._drafts:
            logger.error(f"Brouillon non trouvé: {draft_id}")
            return False

        draft = self._drafts[draft_id]

        result = self.send_email(
            to=draft["to"],
            subject=draft["subject"],
            body=draft["body"],
            cc=draft.get("cc"),
            bcc=draft.get("bcc"),
            is_html=draft["is_html"],
            attachments=draft.get("attachments"),
        )

        if result:
            del self._drafts[draft_id]

        return result

    def send_email(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        is_html: bool = False,
        reply_to: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        attachments: Optional[List[Tuple[str, bytes, str]]] = None,
        idempotency_key: Optional[str] = None,
    ) -> bool:
        """
        Envoie un email directement.

        Args:
            to: Liste des destinataires
            subject: Sujet
            body: Corps du message
            cc: Copie carbone
            bcc: Copie carbone cachée
            is_html: Corps en HTML
            reply_to: Adresse de réponse
            in_reply_to: Message-ID pour thread
            attachments: Liste de tuples (filename, data, content_type)

        Returns:
            True si l'envoi réussit
        """
        try:
            self._ensure_authenticated()
            msg = self._create_message(
                to=to,
                subject=subject,
                body=body,
                cc=cc,
                is_html=is_html,
                reply_to=reply_to,
                in_reply_to=in_reply_to,
                attachments=attachments,
                idempotency_key=idempotency_key,
            )

            # Destinataires complets (To + Cc + Bcc pour l'enveloppe SMTP)
            recipients = to.copy()
            if cc:
                recipients.extend(cc)
            if bcc:
                recipients.extend(bcc)

            # Envoi. sendmail() RETURNS a dict of the recipients the server
            # REFUSED when SOME (not all) fail; it only RAISES
            # (SMTPRecipientsRefused) when ALL fail. Discarding that dict reported
            # a partial refusal as a full success → the user was told "sent" while
            # a recipient (often a bad cc/bcc) silently never received the mail.
            # Treat any refusal as a send failure so the caller surfaces an error
            # (untrusted-input / chaos audit 2026-06-02, P1 silent data loss).
            refused = self._connection.sendmail(
                self.from_email,
                recipients,
                msg.as_string()
            )
            # Real sendmail() always returns a dict ({} on full success); guard on
            # the type so a non-empty dict of refused recipients is treated as a
            # failure, while test doubles / odd return values are not.
            if isinstance(refused, dict) and refused:
                logger.error(
                    f"[FAIL] SMTP a refusé {len(refused)}/{len(recipients)} "
                    f"destinataire(s): {', '.join(refused.keys())}"
                )
                return False

            logger.info(f"[OK] Email envoyé via SMTP à {', '.join(to)}")
            return True

        except smtplib.SMTPException as e:
            logger.error(f"[FAIL] Erreur envoi SMTP: {e}")
            return False

        except Exception as e:
            logger.error(f"[FAIL] Erreur inattendue SMTP: {e}")
            return False

    def mark_as_read(self, message_id: str) -> bool:
        """SMTP ne peut pas marquer d'emails. Utilisez IMAPAdapter."""
        logger.warning("SMTP ne peut pas marquer d'emails. Utilisez IMAPAdapter.")
        return False

    def mark_as_unread(self, message_id: str) -> bool:
        """SMTP ne peut pas marquer d'emails. Utilisez IMAPAdapter."""
        logger.warning("SMTP ne peut pas marquer d'emails. Utilisez IMAPAdapter.")
        return False

    def get_user_drafts(self, limit: int = 50) -> List[StandardEmail]:
        """SMTP ne peut pas lire les brouillons. Utilisez IMAPAdapter."""
        logger.warning("SMTP ne peut pas lire les brouillons. Utilisez IMAPAdapter.")
        return []

    def get_draft_by_id(self, draft_id: str) -> Optional[StandardEmail]:
        """SMTP ne peut pas lire les brouillons. Utilisez IMAPAdapter."""
        logger.warning("SMTP ne peut pas lire les brouillons. Utilisez IMAPAdapter.")
        return None

    def update_draft(
        self,
        draft_id: str,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        to: Optional[List[str]] = None,
        cc: Optional[List[str]] = None,
        is_html: bool = False
    ) -> bool:
        """SMTP ne peut pas mettre à jour les brouillons. Utilisez IMAPAdapter."""
        logger.warning("SMTP ne peut pas mettre à jour les brouillons. Utilisez IMAPAdapter.")
        return False

    def disconnect(self) -> None:
        """Ferme la connexion SMTP."""
        # ``_connection`` is unset when __init__ raised early (e.g. missing
        # config). Use getattr so __del__ during failed construction stays
        # silent instead of producing AttributeError noise during teardown.
        connection = getattr(self, "_connection", None)
        if connection:
            try:
                connection.quit()
            except Exception:
                pass
            self._connection = None
            self._authenticated = False

    def __del__(self):
        """Déconnexion automatique."""
        try:
            self.disconnect()
        except Exception:
            pass


class IMAPSMTPAdapter(EmailProvider):
    """
    Adaptateur combiné IMAP + SMTP pour lecture et envoi.

    Utilise IMAP pour lire les emails et SMTP pour les envoyer.
    C'est l'adaptateur recommandé pour les serveurs standards.

    Variables d'environnement :
    - IMAP_* : Configuration IMAP (voir IMAPAdapter)
    - SMTP_* : Configuration SMTP (voir SMTPAdapter)
    """

    PROVIDER_NAME = "imap_smtp"

    def __init__(
        self,
        # IMAP settings
        imap_host: Optional[str] = None,
        imap_port: Optional[int] = None,
        imap_username: Optional[str] = None,
        imap_password: Optional[str] = None,
        imap_use_ssl: bool = True,
        imap_folder: str = "INBOX",
        # SMTP settings
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_username: Optional[str] = None,
        smtp_password: Optional[str] = None,
        smtp_use_tls: bool = True,
        smtp_use_ssl: bool = False,
        smtp_from_email: Optional[str] = None,
        smtp_from_name: Optional[str] = None,
    ):
        """Initialise les deux adaptateurs."""
        from app.providers.imap_adapter import IMAPAdapter

        self._imap = IMAPAdapter(
            host=imap_host,
            port=imap_port,
            username=imap_username,
            password=imap_password,
            use_ssl=imap_use_ssl,
            folder=imap_folder,
        )

        self._smtp = SMTPAdapter(
            host=smtp_host,
            port=smtp_port,
            username=smtp_username,
            password=smtp_password,
            use_tls=smtp_use_tls,
            use_ssl=smtp_use_ssl,
            from_email=smtp_from_email,
            from_name=smtp_from_name,
        )

        self._authenticated = False

    @property
    def provider_name(self) -> str:
        return self.PROVIDER_NAME

    def authenticate(self) -> bool:
        """Authentifie SMTP immédiatement, IMAP paresseusement (à la première lecture)."""
        smtp_ok = self._smtp.authenticate()
        self._authenticated = smtp_ok
        # IMAP auth is lazy — _imap._ensure_authenticated() is called
        # on first IMAP operation (get_messages, mark_as_read, etc.)
        return self._authenticated

    # Délégation IMAP (lecture)
    def resolve_folder_name(self, logical_folder: str) -> str:
        """Delegate folder resolution to the IMAP adapter."""
        return self._imap.resolve_folder_name(logical_folder)

    def get_messages(self, limit: int = 50, unread_only: bool = False, **kwargs) -> List[StandardEmail]:
        return self._imap.get_messages(limit, unread_only, **kwargs)

    def get_message_headers(self, limit: int = 50, unread_only: bool = False, folder: str = None) -> List[StandardEmail]:
        """Fetch headers only (optimized for list view)."""
        return self._imap.get_message_headers(limit, unread_only, folder)

    def get_sent_emails(self, limit: int = 50) -> List[StandardEmail]:
        """Fetch sent emails."""
        return self._imap.get_sent_emails(limit)

    def get_unread_messages(self, limit: int = 10) -> List[StandardEmail]:
        return self._imap.get_unread_messages(limit)

    def get_message_by_id(self, message_id: str, folder: Optional[str] = None) -> Optional[StandardEmail]:
        return self._imap.get_message_by_id(message_id, folder=folder)

    def mark_as_read(self, message_id: str) -> bool:
        return self._imap.mark_as_read(message_id)

    def mark_as_unread(self, message_id: str) -> bool:
        return self._imap.mark_as_unread(message_id)

    def delete_email(self, message_id: str) -> bool:
        """Délègue la suppression à l'adaptateur IMAP."""
        return self._imap.delete_email(message_id)

    def archive_email(self, message_id: str) -> bool:
        """Délègue l'archivage à l'adaptateur IMAP."""
        return self._imap.archive_email(message_id)

    def permanently_delete(self, message_id: str) -> bool:
        """Délègue la suppression définitive à l'adaptateur IMAP."""
        return self._imap.permanently_delete(message_id)

    def search_subscription_emails(self, limit: int = 200) -> List[StandardEmail]:
        """Délègue la recherche d'abonnements à l'adaptateur IMAP."""
        return self._imap.search_subscription_emails(limit)

    def search_newsletter_emails(self, limit: int = 300) -> List[StandardEmail]:
        """Délègue la recherche de newsletters à l'adaptateur IMAP."""
        return self._imap.search_newsletter_emails(limit)

    # Délégation SMTP (envoi)
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
        from_name: Optional[str] = None,
    ) -> Optional[str]:
        return self._smtp.create_draft(to, subject, body, reply_to_id, cc, bcc, is_html, attachments, from_name=from_name)

    def send_draft(self, draft_id: str) -> bool:
        return self._smtp.send_draft(draft_id)

    def send_email(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        is_html: bool = False,
        attachments: Optional[List[Tuple[str, bytes, str]]] = None,
    ) -> bool:
        return self._smtp.send_email(to, subject, body, cc=cc, is_html=is_html, attachments=attachments)

    # FIX EMAIL-002 (audit P0): the ScheduledEmailScheduler calls
    # send_new_directly / send_reply_directly on the provider; without these
    # shims, every IMAP/SMTP scheduled send AttributeError'd and the row was
    # marked failed permanently. SMTP doesn't return a server-side Message-ID
    # from sendmail(), so we mint a synthetic one to satisfy the scheduler's
    # `if not sent_message_id: mark_failed("provider returned no message_id")`
    # check at scheduled_email_scheduler.py:147.
    def _synthetic_message_id(self) -> str:
        domain = "agentys.local"
        if self._smtp.from_email and "@" in self._smtp.from_email:
            domain = self._smtp.from_email.rsplit("@", 1)[-1] or domain
        return f"<{uuid.uuid4().hex}@{domain}>"

    def send_new_directly(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        attachments: Optional[List[Tuple[str, bytes, str]]] = None,
        is_html: bool = False,
        from_name: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Optional[str]:
        """Send a new (non-reply) email directly via SMTP.

        Returns a synthetic Message-ID on success, or None on failure (the
        scheduler will mark_failed on None).
        """
        original_from_name = self._smtp.from_name
        if from_name:
            self._smtp.from_name = from_name
        try:
            ok = self._smtp.send_email(
                to=to,
                subject=subject,
                body=body,
                cc=cc,
                bcc=bcc,
                is_html=is_html,
                attachments=attachments,
                idempotency_key=idempotency_key,
            )
        finally:
            self._smtp.from_name = original_from_name
        if not ok:
            return None
        if idempotency_key:
            message_id = idempotency_key.strip()
            return message_id if message_id.startswith("<") else f"<{message_id}>"
        return self._synthetic_message_id()

    def send_reply_directly(
        self,
        to: List[str],
        subject: str,
        body: str,
        reply_to_id: str,
        cc: Optional[List[str]] = None,
        attachments: Optional[List[Tuple[str, bytes, str]]] = None,
        thread_id: Optional[str] = None,
        is_html: bool = False,
        idempotency_key: Optional[str] = None,
    ) -> Optional[str]:
        """Send a reply via SMTP, threading via In-Reply-To/References headers.

        Returns a synthetic Message-ID on success, or None on failure. The
        `thread_id` is currently unused for SMTP (no native thread concept);
        it's accepted to match the provider interface.
        """
        ok = self._smtp.send_email(
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            is_html=is_html,
            in_reply_to=reply_to_id,
            attachments=attachments,
            idempotency_key=idempotency_key,
        )
        if not ok:
            return None
        if idempotency_key:
            message_id = idempotency_key.strip()
            return message_id if message_id.startswith("<") else f"<{message_id}>"
        return self._synthetic_message_id()

    # Délégation IMAP (recherche)
    def search_emails(self, query: str, limit: int = 20) -> List[StandardEmail]:
        return self._imap.search_emails(query, limit)

    # Délégation IMAP (brouillons utilisateur)
    def get_user_drafts(self, limit: int = 50) -> List[StandardEmail]:
        return self._imap.get_user_drafts(limit)

    def get_draft_by_id(self, draft_id: str) -> Optional[StandardEmail]:
        return self._imap.get_draft_by_id(draft_id)

    def update_draft(
        self,
        draft_id: str,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        to: Optional[List[str]] = None,
        cc: Optional[List[str]] = None,
        is_html: bool = False
    ) -> bool:
        return self._imap.update_draft(draft_id, subject, body, to, cc, is_html)

    def disconnect(self) -> None:
        """Déconnecte les deux services."""
        # ``_imap`` / ``_smtp`` may be unset when __init__ raised early
        # (e.g. the inner SMTPAdapter rejected missing config). getattr
        # keeps __del__ silent during failed construction.
        imap = getattr(self, "_imap", None)
        smtp = getattr(self, "_smtp", None)
        if imap is not None:
            try:
                imap.disconnect()
            except Exception:
                pass
        if smtp is not None:
            try:
                smtp.disconnect()
            except Exception:
                pass
        self._authenticated = False

    def __del__(self):
        try:
            self.disconnect()
        except Exception:
            pass
