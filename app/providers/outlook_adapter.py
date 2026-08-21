# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adaptateur Outlook pour Microsoft Graph API.

Implémente l'interface EmailProvider pour Microsoft 365 / Outlook.
Utilise azure-identity pour l'authentification et msgraph-sdk pour les appels API.
"""

import os
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

from azure.identity import ClientSecretCredential, DeviceCodeCredential
from azure.core.credentials import AccessToken, TokenCredential
from msgraph import GraphServiceClient

_retry_logger = logging.getLogger(__name__)

# Maximum Retry-After delay we honor from Microsoft Graph (cap for hung syncs).
_OUTLOOK_MAX_RETRY_AFTER = 60.0


def _graph_request_with_retry(method, url, *, headers=None, timeout=10, max_retries=2, **kwargs):
    """Execute a Microsoft Graph HTTP request with 429 Retry-After backoff.

    Microsoft Graph returns HTTP 429 with a `Retry-After` header (seconds)
    when the caller is throttled. Prior to this helper, the two request
    sites in the adapter returned `[]` on any non-200 response, silently
    dropping attachments while the user saw no error → "attachment
    unavailable forever" even after the throttle lifted.

    Args:
        method: HTTP verb (`requests.get`, `requests.post`, ...).
        url: Target URL.
        headers: HTTP headers dict.
        timeout: Per-request timeout in seconds.
        max_retries: Number of 429 retries before giving up (default 2).

    Returns:
        The final `requests.Response` (may still be 429 after retries).
    """
    last_resp = None
    attempt = 0
    while True:
        last_resp = method(url, headers=headers, timeout=timeout, **kwargs)
        if last_resp.status_code != 429 or attempt >= max_retries:
            return last_resp
        # Honor server's Retry-After header; fall back to exponential backoff.
        retry_after = last_resp.headers.get("Retry-After", "")
        try:
            delay = min(float(retry_after), _OUTLOOK_MAX_RETRY_AFTER)
        except (TypeError, ValueError):
            delay = min(2.0 ** attempt, _OUTLOOK_MAX_RETRY_AFTER)
        _retry_logger.warning(
            "Outlook Graph 429 — sleeping %.2fs before retry %d/%d (url=%s)",
            delay, attempt + 1, max_retries, url,
        )
        time.sleep(max(0.1, delay))
        attempt += 1
    # Unreachable; kept for clarity.
    return last_resp  # pragma: no cover


class _StaticTokenCredential(TokenCredential):
    """
    Custom TokenCredential that returns a pre-existing access token.

    Supports proactive refresh via a callback to prevent mid-session expiry.
    """

    def __init__(self, access_token: str, expires_at: float = 0, refresh_callback=None):
        self._token = access_token
        self._expires_at = expires_at
        self._refresh_callback = refresh_callback

    def get_token(self, *scopes, **kwargs) -> AccessToken:
        """Return the token, refreshing proactively if expiry is within 5 minutes."""
        import time
        import logging as _stc_log
        now = time.time()
        # Proactively refresh if token expires within 5 minutes
        # Skip refresh if expires_at is unknown (0) and we already have a token
        needs_refresh = (
            self._refresh_callback
            and self._expires_at > 0
            and now > self._expires_at - 300
        )
        if needs_refresh:
            try:
                new_tokens = self._refresh_callback()
                if new_tokens and new_tokens.get("access_token"):
                    self._token = new_tokens["access_token"]
                    self._expires_at = new_tokens.get("expires_at", now + 3600)
            except Exception as e:
                _stc_log.getLogger(__name__).warning(
                    f"Outlook token proactive refresh failed: {e}"
                )
        expiry = int(self._expires_at) if self._expires_at > 0 else int(now) + 3600
        return AccessToken(self._token, expiry)


from msgraph.generated.users.item.messages.messages_request_builder import MessagesRequestBuilder
from msgraph.generated.users.item.mail_folders.item.messages.messages_request_builder import (
    MessagesRequestBuilder as FolderMessagesRequestBuilder
)
from msgraph.generated.models.message import Message
from msgraph.generated.models.recipient import Recipient
from msgraph.generated.models.email_address import EmailAddress
from msgraph.generated.models.item_body import ItemBody
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.users.item.messages.item.reply.reply_post_request_body import ReplyPostRequestBody
from msgraph.generated.users.item.messages.item.create_reply.create_reply_post_request_body import CreateReplyPostRequestBody

from app.interfaces.email_provider import EmailProvider, StandardEmail, EmailFolder
from app.providers.email_parser_mixin import EmailParserMixin

logger = logging.getLogger(__name__)


import asyncio
import threading

# REAUTH log de-duplication. The OAuth-revoked path (the most common reason
# for auth failure on a long-lived account) is hit every sync cycle until
# the user reconnects, so a stock ``logger.warning`` produces N×7 lines a
# day for an account fleet. We surface the WARNING once per (account, day)
# and demote subsequent occurrences to DEBUG — the operator still sees the
# first signal, the daily sync log stays readable.
_REAUTH_WARN_TTL_SECONDS = 24 * 3600
_reauth_warned_at: dict[str, float] = {}
_reauth_warned_lock = threading.Lock()


def _log_reauth_required(account_id: str) -> None:
    """First call per account-per-24h logs at WARNING; rest at DEBUG."""
    key = str(account_id or "?")
    now = time.time()
    with _reauth_warned_lock:
        last = _reauth_warned_at.get(key, 0.0)
        first = (now - last) >= _REAUTH_WARN_TTL_SECONDS
        if first:
            _reauth_warned_at[key] = now
    log = logger.warning if first else logger.debug
    log(
        "[REAUTH] OAuth tokens manquants/révoqués pour account_id=%s — "
        "l'utilisateur doit reconnecter son compte Outlook",
        account_id,
    )

# Global shared event loop for Microsoft Graph API requests to avoid "Event loop is closed" errors
_outlook_loop = asyncio.new_event_loop()
_outlook_thread = threading.Thread(target=_outlook_loop.run_forever, daemon=True, name="OutlookAdapterAsyncLoop")
_outlook_thread.start()
_outlook_loop_lock = threading.Lock()  # Protects loop/thread restart from race conditions

_ASYNC_TIMEOUT = 30  # secondes max avant TimeoutError

def _run_async(coro, timeout: float = _ASYNC_TIMEOUT):
    """
    Exécute une coroutine sur la boucle partagée et attend le résultat.

    - Timeout 30s pour éviter un blocage indéfini.
    - Auto-redémarre le thread si la boucle a crashé.
    - Lock protège le redémarrage contre les accès concurrents.

    S-14 fix (2026-04-24): also recycle when the loop is closed but the
    thread is still alive. A coroutine raising at top level can leave
    `loop.is_closed() == True` while the thread is technically running
    its final teardown — `is_alive()` alone misses this and submits new
    futures into a closed loop, hanging the full timeout per call.
    """
    global _outlook_loop, _outlook_thread
    with _outlook_loop_lock:
        # Recycle on either (a) thread dead or (b) loop closed
        if (not _outlook_thread.is_alive()) or _outlook_loop.is_closed():
            if _outlook_loop.is_closed():
                logger.warning(
                    "OutlookAdapterAsyncLoop boucle fermée (thread alive=%s), recyclage...",
                    _outlook_thread.is_alive(),
                )
            else:
                logger.warning("OutlookAdapterAsyncLoop thread mort, redémarrage...")
            _outlook_loop = asyncio.new_event_loop()
            _outlook_thread = threading.Thread(
                target=_outlook_loop.run_forever, daemon=True, name="OutlookAdapterAsyncLoop"
            )
            _outlook_thread.start()
        loop = _outlook_loop
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        return future.result(timeout=timeout)
    except TimeoutError:
        future.cancel()
        raise TimeoutError(f"Opération Outlook async timeout après {timeout}s")

class OutlookAdapter(EmailProvider, EmailParserMixin):
    """
    Adaptateur Microsoft Outlook via Graph API.

    Supporte deux modes d'authentification :
    - Client credentials (app-only) : pour les applications serveur
    - Device code flow : pour les applications interactives

    Variables d'environnement requises :
    - AZURE_TENANT_ID : ID du tenant Azure AD
    - AZURE_CLIENT_ID : ID de l'application Azure AD
    - AZURE_CLIENT_SECRET : Secret de l'application (mode app-only)
    - OUTLOOK_USER_ID : Email ou ID de l'utilisateur cible
    """

    PROVIDER_NAME = "outlook"
    GRAPH_SCOPES = ["https://graph.microsoft.com/.default"]
    USER_SCOPES = [
        "https://graph.microsoft.com/Mail.Read",
        "https://graph.microsoft.com/Mail.ReadWrite",
        "https://graph.microsoft.com/Mail.Send",
        "https://graph.microsoft.com/Calendars.ReadWrite",
        "https://graph.microsoft.com/People.Read",
        # Contact photos — mirrors the avatars the user already sees in
        # Outlook for senders in their contacts / org directory.
        "https://graph.microsoft.com/Contacts.Read",
        # mailboxSettings exposes the user's server-side signature (and
        # automatic-replies). Without it, get_signature()'s Strategy 1 403s on
        # every mailbox and we fall back to regex-scraping sent mail. Delegated,
        # user-consentable scope.
        "https://graph.microsoft.com/MailboxSettings.Read",
        "https://graph.microsoft.com/User.Read",
    ]

    # Fields requested for the inbox delta sync. Microsoft Graph BAKES this
    # $select into the @odata.deltaLink it returns from the delta-init call, and
    # that link is then reused verbatim on every subsequent delta tick — the
    # $select cannot be changed afterwards. So the init MUST request the full
    # metadata set; requesting only `id` poisons the deltaLink and every
    # delta-synced email lands with a blank subject/sender/recipients/date
    # ("inbox shows (No subject) + empty sender right after connecting Outlook",
    # 2026-06-23). Body is deliberately EXCLUDED: the delta-init call enumerates
    # the entire inbox to establish the checkpoint, and the app is metadata-only
    # by default (bodies load on demand), so pulling every body here would be
    # pure waste / quota burn.
    _DELTA_SELECT = (
        "id,from,toRecipients,ccRecipients,subject,receivedDateTime,"
        "isRead,hasAttachments,conversationId,importance,categories,webLink"
    )

    def __init__(
        self,
        tenant_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        user_id: Optional[str] = None,
        use_device_code: bool = False,
        account_id: Optional[str] = None,
        **kwargs  # Ignore other unknown parameters
    ):
        """
        Initialise l'adaptateur Outlook.

        Args:
            tenant_id: Azure AD tenant ID (ou via env AZURE_TENANT_ID)
            client_id: Azure AD application ID (ou via env AZURE_CLIENT_ID)
            client_secret: Azure AD client secret (ou via env AZURE_CLIENT_SECRET)
            user_id: User email or ID (ou via env OUTLOOK_USER_ID)
            use_device_code: Utiliser le device code flow au lieu de client credentials
            account_id: ID du compte pour tokens server-side (OAuth web)
        """
        self.tenant_id = tenant_id or os.getenv("AZURE_TENANT_ID")
        self.client_id = client_id or os.getenv("AZURE_CLIENT_ID", os.getenv("MICROSOFT_CLIENT_ID"))
        self.client_secret = client_secret or os.getenv("AZURE_CLIENT_SECRET", os.getenv("MICROSOFT_CLIENT_SECRET"))
        self.user_id = user_id or os.getenv("OUTLOOK_USER_ID")
        self.use_device_code = use_device_code
        self.account_id = account_id

        self._client: Optional[GraphServiceClient] = None
        self._authenticated = False
        self._access_token: Optional[str] = None

        # Skip validation if account_id is provided (OAuth web mode)
        if self.account_id:
            # OAuth web mode - tokens will be loaded from server storage
            logger.debug(f"OutlookAdapter initialized with account_id: {self.account_id}")
            return

        # Validation for Azure AD mode
        if not self.tenant_id or not self.client_id:
            raise ValueError(
                "AZURE_TENANT_ID et AZURE_CLIENT_ID sont requis. "
                "Configurez-les via variables d'environnement ou paramètres."
            )

        if not self.use_device_code and not self.client_secret:
            raise ValueError(
                "AZURE_CLIENT_SECRET requis pour le mode app-only. "
                "Utilisez use_device_code=True pour le mode interactif."
            )

    @property
    def provider_name(self) -> str:
        return self.PROVIDER_NAME

    def _get_server_tokens(self) -> Optional[dict]:
        """
        Récupère les tokens OAuth depuis le stockage serveur.

        Returns:
            Dict avec access_token, refresh_token, etc. ou None
        """
        if not self.account_id:
            return None

        try:
            from app.api.oauth import get_tokens_server, _refresh_tokens_server
            import time

            token_data = get_tokens_server(self.account_id)
            if not token_data:
                return None

            # Vérifier si le token a besoin d'être rafraîchi (expiré ou absent)
            expires_at = token_data.get("expires_at", 0)
            access_token = token_data.get("access_token", "")
            token_missing = not access_token
            token_expired = time.time() > (expires_at - 5 * 60)

            if token_expired or token_missing:
                reason = "absent" if token_missing else "expirant"
                logger.info(f"Token {reason} pour {self.account_id}, rafraîchissement...")
                try:
                    token_data = _refresh_tokens_server(self.account_id)
                except Exception as refresh_err:
                    # Distinguish auth failures (require user reauth) from
                    # transient network errors so operators can diagnose
                    # "Échec du rafraîchissement" without digging into logs.
                    logger.error(
                        "Échec rafraîchissement tokens Outlook pour %s: %s (%s)",
                        self.account_id, type(refresh_err).__name__, refresh_err,
                    )
                    return None
                if not token_data:
                    logger.error(
                        "Échec rafraîchissement tokens Outlook pour %s — "
                        "provider retourne None (possible invalid_grant)",
                        self.account_id,
                    )
                    return None

            return token_data

        except Exception as e:
            logger.error(f"Erreur récupération tokens serveur ({type(e).__name__}): {e}")
            return None

    def authenticate(self) -> bool:
        """
        Authentifie via Azure AD ou tokens OAuth serveur.

        Priorité d'authentification :
        1. Tokens OAuth serveur (si account_id fourni)
        2. Device code flow (si use_device_code=True)
        3. Client credentials (mode app-only)

        Returns:
            True si l'authentification réussit.
        """
        try:
            # Méthode 1 : Tokens OAuth depuis le stockage serveur
            if self.account_id:
                server_tokens = self._get_server_tokens()
                if server_tokens:
                    access_token = server_tokens.get("access_token")
                    self.user_id = server_tokens.get("email")  # Set user email from tokens

                    if access_token:
                        self._access_token = access_token
                        expires_at = server_tokens.get("expires_at", 0)
                        # Create a credential that proactively refreshes via _get_server_tokens
                        credential = _StaticTokenCredential(access_token, expires_at, self._get_server_tokens)
                        self._client = GraphServiceClient(credentials=credential, scopes=self.USER_SCOPES)
                        self._authenticated = True
                        logger.info(f"[OK] Authentification Outlook via OAuth serveur (user: {self.user_id})")
                        return True
                # account_id fourni mais tokens absents/refresh_token invalide
                # → NE PAS tomber sur ClientSecretCredential (app-only tenant)
                # qui émet un faux "tenant_id invalide" masquant le vrai problème
                # (révocation OAuth utilisateur). On retourne False explicitement
                # pour que le sync_service marque le compte "needs reauth" au lieu
                # de spammer 10x auth fails → 1h backoff → onboarding figé.
                _log_reauth_required(self.account_id)
                self._authenticated = False
                return False

            # Méthode 2 : Device code flow (interactif)
            if self.use_device_code:
                credential = DeviceCodeCredential(
                    tenant_id=self.tenant_id,
                    client_id=self.client_id
                )
                scopes = self.USER_SCOPES
            # Méthode 3 : Client credentials (app-only)
            else:
                if not self.client_secret:
                    logger.error("No client_secret available for app-only mode")
                    return False

                credential = ClientSecretCredential(
                    tenant_id=self.tenant_id,
                    client_id=self.client_id,
                    client_secret=self.client_secret
                )
                scopes = self.GRAPH_SCOPES

            self._client = GraphServiceClient(credentials=credential, scopes=scopes)
            self._authenticated = True
            logger.info(f"[OK] Authentification Outlook réussie (user: {self.user_id})")
            return True

        except Exception as e:
            logger.error(f"[FAIL] Authentification Outlook échouée: {e}")
            self._authenticated = False
            return False

    def _ensure_authenticated(self) -> None:
        """S'assure que le client est authentifié."""
        if not self._authenticated or not self._client:
            if not self.authenticate():
                raise RuntimeError("Authentification Outlook requise")

    def _is_auth_error(self, error: Exception) -> bool:
        """Retourne True si l'erreur est une erreur d'authentification (401)."""
        err = str(error).lower()
        return any(code in err for code in ("401", "invalidauthenticationtoken", "authenticationrequired", "tokenexpired", "unauthorized", "accessdenied"))

    def _is_throttle_error(self, error: Exception) -> bool:
        """Audit P1-A5 (mother-of-all 2026-04-25) — détecte un 429 venant de
        la SDK msgraph (qui ne route pas par notre `_graph_request_with_retry`).

        Le SDK raise des `APIError` / `ODataError` dont le `status_code` ou
        le message texte contient l'info. On reste permissif : on regarde
        à la fois ``status_code``, ``response_status_code``, et le message.
        """
        if getattr(error, "status_code", None) == 429:
            return True
        if getattr(error, "response_status_code", None) == 429:
            return True
        err = str(error).lower()
        return "429" in err or "too many requests" in err or "throttl" in err

    def _retry_after_seconds(self, error: Exception, default: float = 30.0) -> float:
        """Audit P1-A5 — extrait le Retry-After d'une exception SDK msgraph.

        Le SDK peut exposer le header via ``response_headers`` ou laisser le
        texte original. Fallback `default` si rien n'est trouvable.
        """
        candidates = []
        for attr in ("response_headers", "headers"):
            h = getattr(error, attr, None)
            if h is None:
                continue
            try:
                v = h.get("Retry-After") or h.get("retry-after")
                if v:
                    candidates.append(v)
            except AttributeError:
                pass
        # Cherche aussi dans le message texte (heuristique).
        import re as _re
        m = _re.search(r"retry[- ]?after[:= ]\s*(\d+)", str(error).lower())
        if m:
            candidates.append(m.group(1))
        for c in candidates:
            try:
                return min(float(c), _OUTLOOK_MAX_RETRY_AFTER)
            except (TypeError, ValueError):
                continue
        return default

    def _reset_and_reauth(self) -> None:
        """Réinitialise l'état d'auth et force un nouveau cycle d'authentification."""
        self._authenticated = False
        self._client = None
        self._access_token = None
        self._ensure_authenticated()

    def _map_to_standard_email(self, message: Message) -> StandardEmail:
        """
        Convertit un message Graph API en StandardEmail.

        Args:
            message: Message de l'API Microsoft Graph.

        Returns:
            Email normalisé StandardEmail.
        """
        # Extraire l'expéditeur
        sender_email = ""
        sender_name = None
        sender_spoofed = False
        if message.from_ and message.from_.email_address:
            sender_email = message.from_.email_address.address or ""
            sender_name = message.from_.email_address.name
            # Audit 2026-05-18: Microsoft Graph occasionally hands back a
            # display name that's already double-decoded UTF-8 → Latin-1
            # ("Crypto UniversitÃ©" instead of "Crypto Université"). The
            # IMAP/Gmail paths repair this inside _parse_email_address; the
            # Outlook path doesn't go through that helper, so we call the
            # shared mixin repair directly.
            sender_name = self._demojibake(sender_name) if sender_name else None
            # Audit 2026-05-18: strip invisible chars and flag homograph
            # attacks ("Хfinity Billpay" with Cyrillic Х). Spoof detection
            # runs after mojibake repair so legitimate accented Latin names
            # aren't false-positive'd by the lookalike-script check.
            if sender_name:
                from app.utils.sender_spoofing import detect_sender_spoofing
                sender_name, sender_spoofed = detect_sender_spoofing(sender_name)

        # Extraire les destinataires
        to_list = []
        if message.to_recipients:
            to_list = [
                r.email_address.address
                for r in message.to_recipients
                if r.email_address and r.email_address.address
            ]

        cc_list = []
        if message.cc_recipients:
            cc_list = [
                r.email_address.address
                for r in message.cc_recipients
                if r.email_address and r.email_address.address
            ]

        # Corps du message
        body_text = ""
        body_html = None
        if message.body:
            if message.body.content_type == BodyType.Html:
                body_html = message.body.content
                # Utilise le mixin pour extraction du texte
                body_text = self._extract_text_from_html(message.body.content or "")
                # Resolve inline cid: images (broken otherwise — Graph ships them
                # as separate inline attachments, not inline parts).
                body_html = self._resolve_outlook_inline_images(
                    message.id or "", body_html, bool(message.has_attachments)
                )
            else:
                body_text = message.body.content or ""
            # Audit 2026-05-19 (Y003 / F-02) : on NE demojibake PAS le corps
            # Outlook. Microsoft Graph renvoie un corps deja decode en UTF-8
            # propre (jamais mojibake au transport), donc lui appliquer le
            # reparateur serait du risque sans gain (reinterpretation a
            # l'aveugle). Les noms d'expediteur / sujets — champs courts
            # historiquement corrompus cote serveur — restent traites plus haut.

        # Date de réception
        received_at = None
        if message.received_date_time:
            received_at = message.received_date_time

        return StandardEmail(
            id=message.id or "",
            sender=sender_email,
            sender_name=sender_name,
            to=to_list,
            cc=cc_list,
            subject=self._demojibake(message.subject or ""),
            body=body_text.strip(),
            body_html=body_html,
            received_at=received_at,
            is_read=message.is_read or False,
            has_attachments=message.has_attachments or False,
            conversation_id=message.conversation_id,
            provider_source=self.PROVIDER_NAME,
            sender_spoofed=sender_spoofed,
            raw_metadata={
                "importance": str(message.importance) if message.importance else None,
                "categories": message.categories or [],
                "web_link": message.web_link,
            }
        )

    def get_unread_messages(self, limit: int = 10) -> List[StandardEmail]:
        """
        Récupère les messages non lus.

        Args:
            limit: Nombre maximum de messages.

        Returns:
            Liste d'emails normalisés.
        """
        return self.get_messages(limit=limit, unread_only=True)

    async def _get_messages_async(self, limit: int, unread_only: bool = False, folder_id: str = None) -> List[Message]:
        """
        Récupère les messages de manière asynchrone.

        Microsoft Graph API supports batch fetching natively via $top parameter,
        returning all requested messages in a single API call.

        Args:
            limit: Maximum number of messages to fetch.
            unread_only: If True, only fetch unread messages.
            folder_id: Optional Outlook folder ID to fetch from.

        Returns:
            List of Message objects from Graph API.
        """
        self._ensure_authenticated()

        # Build query parameters - Graph API returns full messages in one call
        query_params = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
            filter="isRead eq false" if unread_only else None,
            top=limit,
            orderby=["receivedDateTime desc"],
            select=["id", "from", "toRecipients", "ccRecipients", "subject",
                    "body", "receivedDateTime", "isRead", "hasAttachments",
                    "conversationId", "importance", "categories", "webLink"]
        )

        request_config = MessagesRequestBuilder.MessagesRequestBuilderGetRequestConfiguration(
            query_parameters=query_params
        )

        # Default to inbox when no folder specified — the Graph API /users/{id}/messages
        # endpoint returns ALL folders (including Junk Email), unlike Gmail which
        # excludes spam by default. This ensures consistent behavior across providers.
        effective_folder = folder_id or "inbox"
        result = await self._client.users.by_user_id(self.user_id).mail_folders.by_mail_folder_id(
            effective_folder
        ).messages.get(request_configuration=request_config)
        return result.value if result and result.value else []

    def get_messages(self, limit: int = 50, unread_only: bool = False, label_ids: list = None, folder: str = None, **kwargs) -> List[StandardEmail]:
        """
        Récupère les messages (tous ou non lus seulement).

        Uses Microsoft Graph API batch fetching - single API call returns all messages.
        Mapping to StandardEmail is parallelized for faster processing.

        Args:
            limit: Nombre maximum de messages (default 50).
            unread_only: Si True, ne récupère que les messages non lus.
            label_ids: Outlook folder IDs to filter by (uses first ID).
            folder: Nom du dossier IMAP-style (inbox, sent, drafts, etc.) — mappé vers l'ID Graph.

        Returns:
            Liste d'emails normalisés triés par date (plus récents en premier).
        """
        from concurrent.futures import ThreadPoolExecutor

        # Mapper les noms de dossiers IMAP-style vers les well-known folder IDs de Graph
        _FOLDER_MAP = {
            "inbox": "inbox",
            "sent": "sentitems",
            "drafts": "drafts",
            "trash": "deleteditems",
            "junk": "junkemail",
            "spam": "junkemail",
            "archive": "archive",
        }

        def _fetch_messages():
            folder_id = label_ids[0] if label_ids else None
            if not folder_id and folder:
                folder_id = _FOLDER_MAP.get(folder.lower())
            messages = _run_async(self._get_messages_async(limit, unread_only, folder_id=folder_id))
            if not messages:
                return []
            with ThreadPoolExecutor(max_workers=4) as executor:
                return list(executor.map(self._map_to_standard_email, messages))

        try:
            emails = _fetch_messages()
            logger.info(f"Outlook fetch: {len(emails)} emails in single API call")
            return emails

        except Exception as e:
            if self._is_auth_error(e):
                logger.warning("Outlook 401 sur messages, rafraîchissement des tokens...")
                try:
                    self._reset_and_reauth()
                    emails = _fetch_messages()
                    logger.info(f"Outlook fetch (après refresh): {len(emails)} emails")
                    return emails
                except Exception as retry_e:
                    logger.error(f"Erreur récupération messages Outlook après refresh: {retry_e}")
                    return []
            # Audit P1-A5 : 429 throttling — la SDK msgraph ne route pas par
            # notre helper avec backoff. On fait le retry une fois ici pour
            # ne pas faire entrer le sync en backoff auth (qui pénalise 10min)
            # alors que Microsoft demande juste un retry après quelques secondes.
            if self._is_throttle_error(e):
                delay = self._retry_after_seconds(e, default=30.0)
                logger.warning(
                    f"Outlook 429 throttle on get_messages — sleeping {delay:.1f}s "
                    f"and retrying once"
                )
                import time as _t
                _t.sleep(delay)
                try:
                    emails = _fetch_messages()
                    logger.info(f"Outlook fetch (après throttle retry): {len(emails)} emails")
                    return emails
                except Exception as retry_e:
                    logger.error(f"Erreur Outlook après throttle retry: {retry_e}")
                    return []
            logger.error(f"Erreur récupération messages Outlook: {e}")
            return []

    async def _get_message_by_id_async(self, message_id: str, expand_attachments: bool = False) -> Optional[Message]:
        """Récupère un message par ID de manière asynchrone.

        Args:
            message_id: ID Graph du message.
            expand_attachments: Si True, inclut les pièces jointes inline ($expand)
                pour éviter un second appel HTTP.
        """
        self._ensure_authenticated()

        try:
            from msgraph.generated.users.item.messages.item.message_item_request_builder import MessageItemRequestBuilder

            _select = [
                "id", "from", "toRecipients", "ccRecipients", "bccRecipients",
                "subject", "body", "receivedDateTime", "isRead",
                "hasAttachments", "conversationId", "importance",
                "categories", "webLink", "replyTo", "flag",
            ]
            _expand = ["attachments($select=id,name,size,contentType,isInline)"] if expand_attachments else None

            query_params = MessageItemRequestBuilder.MessageItemRequestBuilderGetQueryParameters(
                select=_select,
                expand=_expand,
            )
            request_config = MessageItemRequestBuilder.MessageItemRequestBuilderGetRequestConfiguration(
                query_parameters=query_params,
            )

            message = await self._client.users.by_user_id(self.user_id).messages.by_message_id(
                message_id
            ).get(request_configuration=request_config)
            return message
        except Exception:
            return None

    def extract_attachment_metadata(self, msg_id: str) -> list:
        """Récupère les métadonnées des pièces jointes via Graph API."""
        import requests as _req

        if not self._access_token:
            return []
        try:
            url = f"https://graph.microsoft.com/v1.0/users/{self.user_id}/messages/{msg_id}/attachments?$select=id,name,size,contentType,isInline"
            resp = _graph_request_with_retry(
                _req.get,
                url,
                headers={"Authorization": f"Bearer {self._access_token}"},
                timeout=10,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            return [
                {
                    "id": att.get("id", ""),
                    "filename": att.get("name", "attachment"),
                    "size": att.get("size", 0),
                    "content_type": att.get("contentType", "application/octet-stream"),
                }
                for att in data.get("value", [])
                if not att.get("isInline", False)
            ]
        except Exception as _e:
            logger.warning(f"Outlook extract_attachment_metadata({msg_id}): {_e}")
            return []

    def _fetch_inline_cid_map(self, msg_id: str) -> dict:
        """Fetch a message's INLINE attachments and map content-id -> (mime, base64).

        Outlook/Graph (unlike Gmail/IMAP) does not ship inline image parts with the
        message body, so cid: references render broken unless we pull the inline
        attachments separately. Graph returns contentBytes as standard base64, so no
        re-encode is needed. Returns {} on any failure (degrade to broken images,
        never crash the mapper).
        """
        import requests as _req

        if not self._access_token or not msg_id:
            return {}
        try:
            url = (
                f"https://graph.microsoft.com/v1.0/users/{self.user_id}/messages/{msg_id}"
                "/attachments?$filter=isInline eq true"
                "&$select=id,name,contentType,contentId,contentBytes"
            )
            resp = _graph_request_with_retry(
                _req.get,
                url,
                headers={"Authorization": f"Bearer {self._access_token}"},
                timeout=15,
            )
            if resp.status_code != 200:
                return {}
            cid_map: dict = {}
            for att in resp.json().get("value", []):
                content_id = (att.get("contentId") or "").strip("<>")
                content_bytes = att.get("contentBytes")
                if content_id and content_bytes:
                    cid_map[content_id] = (
                        att.get("contentType") or "application/octet-stream",
                        content_bytes,
                    )
            return cid_map
        except Exception as _e:
            logger.debug(f"Outlook _fetch_inline_cid_map({msg_id}): {_e}")
            return {}

    def _resolve_outlook_inline_images(
        self, msg_id: str, body_html: Optional[str], has_attachments: bool
    ) -> Optional[str]:
        """Replace cid: image refs in an Outlook HTML body with inline data URIs.

        The extra Graph call is gated behind ``has_attachments`` AND an actual
        ``cid:`` reference in the body, so plain emails (and attachment emails with
        no inline images) never pay for it.
        """
        if not body_html or not has_attachments or "cid:" not in body_html:
            return body_html
        cid_map = self._fetch_inline_cid_map(msg_id)
        if not cid_map:
            return body_html
        return self._resolve_cid_images(body_html, cid_map)

    def download_attachment(self, msg_id: str, att_id: str) -> tuple:
        """Télécharge une pièce jointe Outlook. Retourne (bytes, content_type, filename)."""
        import requests as _req
        import base64 as _b64

        if not self._access_token:
            raise RuntimeError("Outlook: not authenticated")

        url = f"https://graph.microsoft.com/v1.0/users/{self.user_id}/messages/{msg_id}/attachments/{att_id}"
        resp = _graph_request_with_retry(
            _req.get,
            url,
            headers={"Authorization": f"Bearer {self._access_token}"},
            timeout=30,
        )
        resp.raise_for_status()
        att_data = resp.json()
        content_bytes_b64 = att_data.get("contentBytes", "")
        data = _b64.b64decode(content_bytes_b64) if content_bytes_b64 else b""
        content_type = att_data.get("contentType", "application/octet-stream")
        filename = att_data.get("name", "attachment")
        return data, content_type, filename

    def get_message_by_id(self, message_id: str) -> Optional[StandardEmail]:
        """
        Récupère un message par son ID.

        Args:
            message_id: ID du message.

        Returns:
            Email normalisé ou None.
        """

        try:
            message = _run_async(self._get_message_by_id_async(message_id, expand_attachments=True))
            if message:
                std = self._map_to_standard_email(message)
                if std:
                    # Extract attachment metadata from the $expand'd response first
                    # (avoids a second HTTP call).  Fall back to a dedicated request
                    # only when the inline data is missing.
                    atts = self._extract_expanded_attachments(message)
                    if not atts:
                        atts = self.extract_attachment_metadata(message_id)
                    if atts:
                        std.attachments = atts
                        std.has_attachments = True
                return std
            return None
        except Exception as e:
            logger.error(f"Erreur récupération message {message_id}: {e}")
            return None

    @staticmethod
    def _extract_expanded_attachments(message: Message) -> list:
        """Extract attachment metadata from a message fetched with $expand=attachments."""
        try:
            raw_atts = getattr(message, 'attachments', None)
            if not raw_atts:
                return []
            return [
                {
                    "id": att.id or "",
                    "filename": att.name or "attachment",
                    "size": att.size or 0,
                    "content_type": att.content_type or "application/octet-stream",
                }
                for att in raw_atts
                if not getattr(att, 'is_inline', False)
            ]
        except Exception:
            return []

    async def _fetch_messages_since_async(
        self, since: datetime, limit: int
    ) -> List[Message]:
        """Fetch messages since timestamp asynchronously."""
        self._ensure_authenticated()

        # Format datetime for OData filter
        since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")

        query_params = FolderMessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
            filter=f"receivedDateTime gt {since_iso}",
            top=limit,
            orderby=["receivedDateTime desc"],
            select=["id", "from", "toRecipients", "ccRecipients", "subject",
                    "body", "receivedDateTime", "isRead", "hasAttachments",
                    "conversationId", "importance", "categories", "webLink"]
        )

        request_config = FolderMessagesRequestBuilder.MessagesRequestBuilderGetRequestConfiguration(
            query_parameters=query_params
        )

        result = await self._client.users.by_user_id(self.user_id).mail_folders.by_mail_folder_id("inbox").messages.get(
            request_configuration=request_config
        )

        return result.value if result and result.value else []

    def fetch_messages_since(
        self, since: datetime, limit: int = 100
    ) -> List[StandardEmail]:
        """
        Fetch messages received since a specific timestamp (delta sync).

        Uses Microsoft Graph's $filter parameter with receivedDateTime
        to fetch only new emails, minimizing API calls and bandwidth.

        Args:
            since: Fetch emails received after this timestamp.
            limit: Maximum number of messages to fetch.

        Returns:
            List of StandardEmail objects.
        """

        try:
            logger.debug(f"Outlook delta sync: fetching emails after {since}")
            messages = _run_async(self._fetch_messages_since_async(since, limit))
            emails = [self._map_to_standard_email(msg) for msg in messages]
            logger.debug(f"Outlook delta sync: fetched {len(emails)} emails")
            return emails
        except Exception as e:
            logger.error(f"Outlook delta sync error: {e}")
            raise

    async def _create_draft_async(
        self,
        to: List[str],
        subject: str,
        body: str,
        reply_to_id: Optional[str],
        cc: Optional[List[str]],
        bcc: Optional[List[str]] = None,
        is_html: bool = False,
        attachments: Optional[list] = None,
    ) -> Optional[str]:
        """Crée un brouillon de manière asynchrone."""
        self._ensure_authenticated()

        # Construire les destinataires
        to_recipients = [
            Recipient(email_address=EmailAddress(address=addr))
            for addr in to
        ]

        cc_recipients = []
        if cc:
            cc_recipients = [
                Recipient(email_address=EmailAddress(address=addr))
                for addr in cc
            ]

        bcc_recipients = []
        if bcc:
            bcc_recipients = [
                Recipient(email_address=EmailAddress(address=addr))
                for addr in bcc
            ]

        # Corps du message
        body_type = BodyType.Html if is_html else BodyType.Text
        item_body = ItemBody(content=body, content_type=body_type)

        # Créer le message
        draft = Message(
            subject=subject,
            body=item_body,
            to_recipients=to_recipients,
            cc_recipients=cc_recipients if cc_recipients else None,
            bcc_recipients=bcc_recipients if bcc_recipients else None,
        )

        try:
            if reply_to_id:
                # Créer une réponse à un message existant
                create_body = CreateReplyPostRequestBody(message=draft)
                result = await self._client.users.by_user_id(
                    self.user_id
                ).messages.by_message_id(
                    reply_to_id
                ).create_reply.post(create_body)
            else:
                # Créer un nouveau brouillon
                result = await self._client.users.by_user_id(
                    self.user_id
                ).messages.post(draft)

            if not result or not result.id:
                return None

            # Upload attachments if provided. OL-02: routes files larger than
            # ~3 MB through a Graph upload session so they are no longer silently
            # dropped (a plain inline POST raises above the limit, and the
            # surrounding except used to swallow it and return None).
            if attachments:
                await self._upload_attachments_async(result.id, attachments)

            return result.id

        except Exception as e:
            logger.error(f"Erreur création brouillon: {e}")
            return None

    async def _upload_attachments_async(self, message_id: str, attachments: list) -> None:
        """Attach files to a draft/message, transparently handling large files.

        Microsoft Graph rejects a single ``messages/{id}/attachments`` POST once
        the base64 body exceeds ~3 MB. Before OL-02 a larger attachment raised,
        the surrounding ``except`` returned ``None`` and the email was silently
        never sent. Files at or under the limit keep the fast inline POST; larger
        files use a chunked upload session (createUploadSession + PUT).
        """
        import base64
        from msgraph.generated.models.file_attachment import FileAttachment

        INLINE_LIMIT = 3 * 1024 * 1024  # Graph's documented inline-attachment cap
        for att in attachments:
            # att = (filename, content_bytes, content_type)
            filename, content_bytes, content_type = att
            # Normalise to raw bytes so we can size-check and stream-upload.
            raw = (
                base64.b64decode(content_bytes)
                if isinstance(content_bytes, str)
                else content_bytes
            )
            if raw is not None and len(raw) > INLINE_LIMIT:
                self._upload_large_attachment_via_session(
                    message_id, filename, raw, content_type
                )
            else:
                file_att = FileAttachment(
                    odata_type="#microsoft.graph.fileAttachment",
                    name=filename,
                    content_type=content_type,
                    content_bytes=base64.b64encode(raw).decode("ascii"),
                )
                await self._client.users.by_user_id(
                    self.user_id
                ).messages.by_message_id(message_id).attachments.post(file_att)

    def _upload_large_attachment_via_session(
        self, message_id: str, filename: str, raw_bytes: bytes, content_type: str
    ) -> None:
        """Upload a >3 MB attachment via a Graph upload session (chunked PUT).

        Raises on failure so the caller surfaces an error rather than silently
        dropping the email (OL-02).
        """
        import requests as http_requests

        self._ensure_authenticated()
        if not self._access_token:
            raise RuntimeError("No access token for large attachment upload")

        size = len(raw_bytes)
        create_url = (
            f"https://graph.microsoft.com/v1.0/users/{self.user_id}"
            f"/messages/{message_id}/attachments/createUploadSession"
        )
        create_resp = _graph_request_with_retry(
            http_requests.post,
            create_url,
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            },
            json={
                "AttachmentItem": {
                    "attachmentType": "file",
                    "name": filename,
                    "size": size,
                    "contentType": content_type or "application/octet-stream",
                }
            },
            timeout=30,
        )
        if create_resp.status_code not in (200, 201):
            raise RuntimeError(
                f"createUploadSession failed: HTTP {create_resp.status_code}"
            )
        upload_url = (create_resp.json() or {}).get("uploadUrl")
        if not upload_url:
            raise RuntimeError("createUploadSession returned no uploadUrl")

        # Graph requires every chunk except the last to be a multiple of 320 KiB.
        chunk_size = 320 * 1024 * 10  # 3.2 MiB
        start = 0
        while start < size:
            end = min(start + chunk_size, size)
            chunk = raw_bytes[start:end]
            put_resp = _graph_request_with_retry(
                http_requests.put,
                upload_url,
                headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {start}-{end - 1}/{size}",
                },
                data=chunk,
                timeout=60,
            )
            # 200/201 = upload complete; 202 = more chunks expected.
            if put_resp.status_code not in (200, 201, 202):
                raise RuntimeError(
                    f"Attachment chunk upload failed: HTTP {put_resp.status_code}"
                )
            start = end

    def create_draft(
        self,
        to: List[str],
        subject: str,
        body: str,
        reply_to_id: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        is_html: bool = False,
        attachments: Optional[list] = None,
        from_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        Crée un brouillon d'email.

        Args:
            to: Destinataires.
            subject: Sujet.
            body: Corps.
            reply_to_id: ID du message original (pour réponse).
            cc: Destinataires en copie.
            bcc: Destinataires en copie cachée.
            is_html: True si le corps est HTML.

        Returns:
            ID du brouillon créé.
        """

        try:
            return _run_async(self._create_draft_async(
                to=to,
                subject=subject,
                body=body,
                reply_to_id=reply_to_id,
                cc=cc,
                bcc=bcc,
                is_html=is_html,
                attachments=attachments,
            ))
        except Exception as e:
            logger.error(f"Erreur création brouillon: {e}")
            return None

    async def _send_draft_async(self, draft_id: str) -> bool:
        """Envoie un brouillon de manière asynchrone."""
        self._ensure_authenticated()

        try:
            await self._client.users.by_user_id(
                self.user_id
            ).messages.by_message_id(
                draft_id
            ).send.post()
            return True
        except Exception as e:
            logger.error(f"Erreur envoi brouillon: {e}")
            return False

    def send_draft(self, draft_id: str) -> bool:
        """
        Envoie un brouillon existant.

        Args:
            draft_id: ID du brouillon.

        Returns:
            True si envoyé avec succès.
        """

        try:
            return _run_async(self._send_draft_async(draft_id))
        except Exception as e:
            logger.error(f"Erreur envoi brouillon: {e}")
            return False

    async def _mark_as_read_async(self, message_id: str) -> bool:
        """Marque un message comme lu de manière asynchrone."""
        self._ensure_authenticated()

        try:
            update = Message(is_read=True)
            await self._client.users.by_user_id(
                self.user_id
            ).messages.by_message_id(
                message_id
            ).patch(update)
            return True
        except Exception as e:
            logger.error(f"Erreur marquage message: {e}")
            return False

    def mark_as_read(self, message_id: str) -> bool:
        """
        Marque un message comme lu.

        Args:
            message_id: ID du message.

        Returns:
            True si marqué avec succès.
        """

        try:
            return _run_async(self._mark_as_read_async(message_id))
        except Exception as e:
            logger.error(f"Erreur marquage message: {e}")
            return False

    def mark_as_unread(self, message_id: str) -> bool:
        """
        Marque un message comme non lu.

        Args:
            message_id: ID du message.

        Returns:
            True si marqué avec succès.
        """

        try:
            return _run_async(self._mark_as_unread_async(message_id))
        except Exception as e:
            logger.error(f"Erreur marquage message non lu: {e}")
            return False

    async def _mark_as_unread_async(self, message_id: str) -> bool:
        """Marque un message comme non lu de manière asynchrone."""
        self._ensure_authenticated()

        try:
            update = Message(is_read=False)
            await self._client.users.by_user_id(
                self.user_id
            ).messages.by_message_id(
                message_id
            ).patch(update)
            return True
        except Exception as e:
            logger.error(f"Erreur marquage message non lu: {e}")
            return False

    async def _apply_label_async(self, message_id: str, label: str) -> bool:
        """Applique une catégorie à un message de manière asynchrone."""
        self._ensure_authenticated()

        try:
            # Récupérer le message pour avoir les catégories existantes
            message = await self._client.users.by_user_id(
                self.user_id
            ).messages.by_message_id(
                message_id
            ).get()

            if not message:
                return False

            # Ajouter la nouvelle catégorie aux existantes
            existing_categories = message.categories or []
            full_label = label if label.startswith("Agentys-") else f"Agentys-{label}"

            if full_label not in existing_categories:
                existing_categories.append(full_label)

            # Mettre à jour le message
            update = Message(categories=existing_categories)
            await self._client.users.by_user_id(
                self.user_id
            ).messages.by_message_id(
                message_id
            ).patch(update)

            logger.debug(f"Catégorie '{full_label}' appliquée au message {message_id}")
            return True

        except Exception as e:
            logger.error(f"Erreur application catégorie: {e}")
            return False

    def apply_label(self, message_id: str, label: str) -> bool:
        """
        Applique une catégorie à un message Outlook.

        Args:
            message_id: ID du message.
            label: Nom du label (sera préfixé par "Agentys-").

        Returns:
            True si la catégorie a été appliquée.
        """

        try:
            return _run_async(self._apply_label_async(message_id, label))
        except Exception as e:
            logger.error(f"Erreur application catégorie: {e}")
            return False

    async def _move_to_spam_async(self, message_id: str) -> bool:
        """Déplace un message vers le dossier spam de manière asynchrone."""
        self._ensure_authenticated()

        try:
            await self._client.users.by_user_id(
                self.user_id
            ).messages.by_message_id(
                message_id
            ).move.post(
                body={"destinationId": "junkemail"}
            )
            logger.debug(f"Message {message_id} déplacé vers spam (Outlook)")
            return True
        except Exception as e:
            logger.error(f"Erreur déplacement vers spam: {e}")
            return False

    def move_to_spam(self, message_id: str) -> bool:
        """
        Déplace un message vers le dossier spam/indésirables.

        Args:
            message_id: ID du message Outlook.

        Returns:
            True si le déplacement a réussi.
        """

        try:
            return _run_async(self._move_to_spam_async(message_id))
        except Exception as e:
            logger.error(f"Erreur déplacement vers spam: {e}")
            return False

    # ------------------------------------------------------------------
    # move_to_inbox / restore_from_trash
    # ------------------------------------------------------------------

    async def _move_to_inbox_async(self, message_id: str) -> bool:
        """Déplace un message vers la boîte de réception de manière asynchrone."""
        self._ensure_authenticated()

        try:
            await self._client.users.by_user_id(
                self.user_id
            ).messages.by_message_id(
                message_id
            ).move.post(
                body={"destinationId": "inbox"}
            )
            logger.debug(f"Message {message_id} déplacé vers inbox (Outlook)")
            return True
        except Exception as e:
            err_str = str(e).lower()
            if "404" in err_str or "not found" in err_str or "itemnotfound" in err_str:
                logger.debug(f"Message {message_id} introuvable — déjà traité")
                return True
            logger.error(f"Erreur déplacement vers inbox: {e}")
            return False

    def move_to_inbox(self, message_id: str) -> bool:
        """
        Déplace un message vers la boîte de réception (ex: depuis spam).

        Args:
            message_id: ID du message Outlook.

        Returns:
            True si le déplacement a réussi.
        """
        try:
            return _run_async(self._move_to_inbox_async(message_id))
        except Exception as e:
            logger.error(f"Erreur déplacement vers inbox: {e}")
            return False

    def restore_from_trash(self, message_id: str) -> bool:
        """
        Restaure un message de la corbeille vers la boîte de réception.

        Args:
            message_id: ID du message Outlook.

        Returns:
            True si la restauration a réussi.
        """
        return self.move_to_inbox(message_id)

    # ------------------------------------------------------------------
    # send_reply_directly (fast path — single API call)
    # ------------------------------------------------------------------

    async def _send_reply_directly_async(
        self,
        to: list,
        subject: str,
        body: str,
        reply_to_id: str,
        cc: list = None,
        bcc: list = None,
        attachments: list = None,
        is_html: bool = False,
        from_name: str = None,
        **kwargs,
    ) -> str | None:
        """Envoie une réponse directement sans créer de brouillon."""
        self._ensure_authenticated()

        to_recipients = [
            Recipient(email_address=EmailAddress(address=addr))
            for addr in to
        ]
        cc_recipients = [
            Recipient(email_address=EmailAddress(address=addr))
            for addr in (cc or [])
        ]
        bcc_recipients = [
            Recipient(email_address=EmailAddress(address=addr))
            for addr in (bcc or [])
        ]

        body_type = BodyType.Html if is_html else BodyType.Text
        item_body = ItemBody(content=body, content_type=body_type)

        reply_msg = Message(
            body=item_body,
            to_recipients=to_recipients,
            cc_recipients=cc_recipients if cc_recipients else None,
            bcc_recipients=bcc_recipients if bcc_recipients else None,
        )

        try:
            if attachments:
                # Attachments require 2-step: create reply draft → upload → send
                create_body = CreateReplyPostRequestBody(message=reply_msg)
                draft = await self._client.users.by_user_id(
                    self.user_id
                ).messages.by_message_id(
                    reply_to_id
                ).create_reply.post(create_body)

                if not draft or not draft.id:
                    return None

                # OL-02: large files use an upload session; on attach failure
                # delete the orphan reply draft and surface the error.
                try:
                    await self._upload_attachments_async(draft.id, attachments)
                except Exception:
                    try:
                        await self._client.users.by_user_id(
                            self.user_id
                        ).messages.by_message_id(draft.id).delete()
                    except Exception:
                        pass
                    raise

                await self._client.users.by_user_id(
                    self.user_id
                ).messages.by_message_id(
                    draft.id
                ).send.post()
                logger.debug(f"Réponse directe avec pièces jointes envoyée à {reply_to_id} (Outlook)")
                return draft.id
            else:
                # No attachments: single API call via reply.post()
                # reply.post() returns None — the sent message ID isn't available
                # Return a truthy marker so callers know sending succeeded
                reply_body = ReplyPostRequestBody(message=reply_msg, comment="")
                await self._client.users.by_user_id(
                    self.user_id
                ).messages.by_message_id(
                    reply_to_id
                ).reply.post(body=reply_body)
                logger.debug(f"Réponse directe envoyée à {reply_to_id} (Outlook)")
                return f"sent-reply-{reply_to_id}"
        except Exception as e:
            logger.error(f"Erreur envoi réponse directe: {e}")
            return None

    def send_reply_directly(
        self,
        to: list,
        subject: str,
        body: str,
        reply_to_id: str,
        cc: list = None,
        bcc: list = None,
        attachments: list = None,
        is_html: bool = False,
        from_name: str = None,
        **kwargs,
    ) -> str | None:
        """
        Envoie une réponse directement sans créer de brouillon (fast path).

        Args:
            to: Destinataires.
            subject: Sujet.
            body: Corps du message.
            reply_to_id: ID du message original.
            cc: Destinataires en copie.
            bcc: Destinataires en copie cachée.
            attachments: Liste de tuples (filename, content_bytes, content_type).
            is_html: True si le corps est HTML.
            from_name: Nom d'affichage de l'expéditeur (ignoré pour Outlook).

        Returns:
            ID du message envoyé, ou None en cas d'erreur.
        """
        try:
            return _run_async(self._send_reply_directly_async(
                to=to, subject=subject, body=body,
                reply_to_id=reply_to_id, cc=cc, bcc=bcc,
                attachments=attachments,
                is_html=is_html, from_name=from_name,
            ))
        except Exception as e:
            logger.error(f"Erreur envoi réponse directe: {e}")
            return None

    # ------------------------------------------------------------------
    # send_new_directly (fast path for new messages)
    # ------------------------------------------------------------------

    async def _send_new_directly_async(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: list = None,
        bcc: list = None,
        attachments: list = None,
        is_html: bool = False,
        from_name: str = None,
        idempotency_key: str = None,
    ) -> str | None:
        """Envoie un nouveau message directement via Graph API."""
        self._ensure_authenticated()

        to_recipients = [
            Recipient(email_address=EmailAddress(address=addr))
            for addr in to
        ]
        cc_recipients = [
            Recipient(email_address=EmailAddress(address=addr))
            for addr in (cc or [])
        ]
        bcc_recipients = [
            Recipient(email_address=EmailAddress(address=addr))
            for addr in (bcc or [])
        ]

        body_type = BodyType.Html if is_html else BodyType.Text
        item_body = ItemBody(content=body, content_type=body_type)

        msg = Message(
            subject=subject,
            body=item_body,
            to_recipients=to_recipients,
            cc_recipients=cc_recipients if cc_recipients else None,
            bcc_recipients=bcc_recipients if bcc_recipients else None,
        )

        self._last_sent_thread_id = ""
        try:
            # Create as draft first, then send (Graph API doesn't have a direct sendMail on messages builder)
            result = await self._client.users.by_user_id(
                self.user_id
            ).messages.post(msg)

            if not result or not result.id:
                return None

            # Outlook's equivalent of Gmail's threadId — the followup tracker
            # uses this to pair sent messages with incoming replies.
            self._last_sent_thread_id = getattr(result, "conversation_id", "") or ""

            # Upload attachments if provided. OL-02: large files use an upload
            # session; if attaching fails, delete the orphan draft so it does not
            # linger unsent in the user's Drafts, then surface the failure.
            if attachments:
                try:
                    await self._upload_attachments_async(result.id, attachments)
                except Exception:
                    try:
                        await self._client.users.by_user_id(
                            self.user_id
                        ).messages.by_message_id(result.id).delete()
                    except Exception:
                        pass
                    raise

            # Send the message
            await self._client.users.by_user_id(
                self.user_id
            ).messages.by_message_id(
                result.id
            ).send.post()

            logger.debug("Nouveau message envoyé directement (Outlook)")
            return result.id
        except Exception as e:
            logger.error(f"Erreur envoi nouveau message direct: {e}")
            return None

    def send_new_directly(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        attachments: Optional[list] = None,
        is_html: bool = False,
        from_name: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Optional[str]:
        """
        Envoie un nouveau message en un seul appel (fast path).

        Args:
            to: Destinataires.
            subject: Sujet.
            body: Corps du message.
            cc: Destinataires en copie.
            bcc: Destinataires en copie cachée.
            attachments: Liste de tuples (filename, content_bytes, content_type).
            is_html: True si le corps est HTML.
            from_name: Nom d'affichage de l'expéditeur (ignoré pour Outlook).

        Returns:
            ID du message envoyé, ou None en cas d'erreur.
        """
        try:
            return _run_async(self._send_new_directly_async(
                to=to, subject=subject, body=body,
                cc=cc, bcc=bcc, attachments=attachments,
                is_html=is_html, from_name=from_name,
                idempotency_key=idempotency_key,
            ))
        except Exception as e:
            logger.error(f"Erreur envoi nouveau message direct: {e}")
            return None

    # ------------------------------------------------------------------
    # get_label_counts
    # ------------------------------------------------------------------

    async def _get_label_counts_async(self) -> dict:
        """Récupère les compteurs de chaque dossier well-known (requêtes parallèles)."""
        self._ensure_authenticated()

        _WELL_KNOWN = {
            "inbox": "inbox",
            "sent": "sentitems",
            "drafts": "drafts",
            "trash": "deleteditems",
            "spam": "junkemail",
        }

        async def _fetch_folder(name: str, folder_id: str):
            try:
                folder_obj = await self._client.users.by_user_id(
                    self.user_id
                ).mail_folders.by_mail_folder_id(
                    folder_id
                ).get()
                if folder_obj:
                    return name, {
                        "total": getattr(folder_obj, 'total_item_count', 0) or 0,
                        "unread": getattr(folder_obj, 'unread_item_count', 0) or 0,
                    }
                return name, {"total": 0, "unread": 0}
            except Exception as e:
                logger.debug(f"Outlook get_label_counts: {folder_id} — {e}")
                return name, {"total": 0, "unread": 0}

        results = await asyncio.gather(
            *[_fetch_folder(name, folder_id) for name, folder_id in _WELL_KNOWN.items()]
        )
        return dict(results)

    def get_label_counts(self) -> dict:
        """
        Récupère le nombre d'emails par dossier (inbox, sent, drafts, trash, spam).

        Returns:
            Dict avec le nom du dossier en clé et {total, unread} en valeur.
        """
        try:
            return _run_async(self._get_label_counts_async())
        except Exception as e:
            logger.error(f"Erreur récupération compteurs dossiers: {e}")
            return {}

    async def _delete_email_async(self, message_id: str) -> bool:
        """Supprime un email de manière asynchrone (déplace vers corbeille)."""
        self._ensure_authenticated()

        try:
            # Move to deleted items folder (trash)
            await self._client.users.by_user_id(
                self.user_id
            ).messages.by_message_id(
                message_id
            ).move.post(
                body={"destinationId": "deleteditems"}
            )
            logger.debug(f"Message {message_id} déplacé vers la corbeille")
            return True
        except Exception as e:
            err_str = str(e).lower()
            if "404" in err_str or "not found" in err_str or "itemnotfound" in err_str:
                logger.debug(f"Message {message_id} introuvable lors de la suppression — déjà traité")
                return True
            logger.error(f"Erreur suppression email: {e}")
            return False

    def delete_email(self, message_id: str) -> bool:
        """
        Supprime un email en le déplaçant vers la corbeille.

        Args:
            message_id: ID du message Outlook.

        Returns:
            True si la suppression a réussi.
        """
        import asyncio
        import concurrent.futures

        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    return executor.submit(_run_async, self._delete_email_async(message_id)).result()
            else:
                return _run_async(self._delete_email_async(message_id))
        except Exception as e:
            logger.error(f"Erreur suppression email: {e}")
            return False

    async def _permanently_delete_async(self, message_id: str) -> bool:
        """Supprime définitivement un email (pas de corbeille)."""
        self._ensure_authenticated()

        try:
            await self._client.users.by_user_id(
                self.user_id
            ).messages.by_message_id(
                message_id
            ).delete()
            logger.debug(f"Message {message_id} supprimé définitivement (Outlook)")
            return True
        except Exception as e:
            logger.error(f"Erreur suppression définitive: {e}")
            return False

    def permanently_delete(self, message_id: str) -> bool:
        """
        Supprime définitivement un email (pas de corbeille).

        Args:
            message_id: ID du message Outlook.

        Returns:
            True si la suppression a réussi.
        """

        try:
            return _run_async(self._permanently_delete_async(message_id))
        except Exception as e:
            logger.error(f"Erreur suppression définitive: {e}")
            return False

    async def _archive_email_async(self, message_id: str) -> bool:
        """Archive un email de manière asynchrone."""
        self._ensure_authenticated()

        try:
            # Move to archive folder
            await self._client.users.by_user_id(
                self.user_id
            ).messages.by_message_id(
                message_id
            ).move.post(
                body={"destinationId": "archive"}
            )
            logger.debug(f"Message {message_id} archivé")
            return True
        except Exception as e:
            err_str = str(e).lower()
            if "404" in err_str or "not found" in err_str or "itemnotfound" in err_str:
                logger.debug(f"Message {message_id} introuvable lors de l'archivage — déjà traité")
                return True
            # "archive" folder may not exist on personal/Outlook.com accounts — try deleteditems as fallback
            if "400" in err_str or "bad request" in err_str or "archive" in err_str:
                logger.debug(f"Message {message_id}: dossier archive indisponible, tentative fallback deleteditems")
                try:
                    await self._client.users.by_user_id(
                        self.user_id
                    ).messages.by_message_id(
                        message_id
                    ).move.post(
                        body={"destinationId": "deleteditems"}
                    )
                    logger.debug(f"Message {message_id} archivé via fallback deleteditems (compte personnel)")
                    return True
                except Exception as e2:
                    logger.warning(f"[OUTLOOK] archive failed: {e2}")
                    return False
            logger.error(f"Erreur archivage email: {e}")
            return False

    def archive_email(self, message_id: str) -> bool:
        """
        Archive un email en le déplaçant vers le dossier Archive.

        Args:
            message_id: ID du message Outlook.

        Returns:
            True si l'archivage a réussi.
        """
        import asyncio
        import concurrent.futures

        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    return executor.submit(_run_async, self._archive_email_async(message_id)).result()
            else:
                return _run_async(self._archive_email_async(message_id))
        except Exception as e:
            logger.error(f"Erreur archivage email: {e}")
            return False

    async def _get_user_drafts_async(self, limit: int) -> List[Message]:
        """Récupère les brouillons de l'utilisateur de manière asynchrone."""
        self._ensure_authenticated()

        query_params = FolderMessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
            top=limit,
            orderby=["receivedDateTime desc"],
            select=["id", "from", "toRecipients", "ccRecipients", "subject",
                    "body", "receivedDateTime", "isRead", "hasAttachments",
                    "conversationId", "importance", "categories", "webLink", "isDraft"]
        )

        request_config = FolderMessagesRequestBuilder.MessagesRequestBuilderGetRequestConfiguration(
            query_parameters=query_params
        )

        # Récupérer les messages du dossier Drafts
        result = await self._client.users.by_user_id(
            self.user_id
        ).mail_folders.by_mail_folder_id(
            "drafts"
        ).messages.get(
            request_configuration=request_config
        )

        return result.value if result and result.value else []

    def get_user_drafts(self, limit: int = 50) -> List[StandardEmail]:
        """
        Récupère les brouillons de l'utilisateur.

        Args:
            limit: Nombre maximum de brouillons.

        Returns:
            Liste de StandardEmail représentant les brouillons.
        """

        try:
            messages = _run_async(self._get_user_drafts_async(limit))
            drafts = []

            for msg in messages:
                email = self._map_to_standard_email(msg)
                # Ajouter les métadonnées de brouillon
                email.raw_metadata["is_user_draft"] = True
                email.raw_metadata["draft_id"] = msg.id

                drafts.append(StandardEmail(
                    id=msg.id or "",
                    sender=email.sender,
                    sender_name=email.sender_name,
                    to=email.to,
                    cc=email.cc,
                    subject=email.subject,
                    body=email.body,
                    body_html=email.body_html,
                    received_at=email.received_at,
                    is_read=email.is_read,
                    has_attachments=email.has_attachments,
                    conversation_id=email.conversation_id,
                    provider_source=self.PROVIDER_NAME,
                    raw_metadata={
                        **email.raw_metadata,
                        "is_user_draft": True,
                        "draft_id": msg.id
                    }
                ))

            logger.debug(f"Récupéré {len(drafts)} brouillons utilisateur")
            return drafts

        except Exception as e:
            logger.error(f"Erreur récupération brouillons: {e}")
            return []

    async def _get_sent_emails_async(self, limit: int) -> List[Message]:
        """Récupère les emails envoyés de manière asynchrone."""
        self._ensure_authenticated()

        query_params = FolderMessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
            top=limit,
            orderby=["sentDateTime desc"],
            select=["id", "from", "toRecipients", "ccRecipients", "subject",
                    "body", "sentDateTime", "receivedDateTime", "isRead", "hasAttachments",
                    "conversationId", "importance", "categories", "webLink"]
        )

        request_config = FolderMessagesRequestBuilder.MessagesRequestBuilderGetRequestConfiguration(
            query_parameters=query_params
        )

        # Récupérer les messages du dossier SentItems
        result = await self._client.users.by_user_id(
            self.user_id
        ).mail_folders.by_mail_folder_id(
            "sentitems"
        ).messages.get(
            request_configuration=request_config
        )

        return result.value if result and result.value else []

    def get_sent_emails(self, limit: int = 50) -> List[StandardEmail]:
        """
        Récupère les emails envoyés.

        Args:
            limit: Nombre maximum d'emails à récupérer.

        Returns:
            Liste d'emails normalisés (StandardEmail).
        """
        from concurrent.futures import ThreadPoolExecutor

        def _fetch(retry: bool = False) -> list:
            messages = _run_async(self._get_sent_emails_async(limit))
            if not messages:
                return []
            with ThreadPoolExecutor(max_workers=4) as executor:
                return list(executor.map(self._map_to_standard_email, messages))

        try:
            emails = _fetch()
            logger.info(f"Outlook sent emails fetch: {len(emails)} emails")
            return emails

        except Exception as e:
            if self._is_auth_error(e):
                logger.warning("Outlook 401 sur emails envoyés, rafraîchissement des tokens...")
                try:
                    self._reset_and_reauth()
                    emails = _fetch()
                    logger.info(f"Outlook sent emails fetch (après refresh): {len(emails)} emails")
                    return emails
                except Exception as retry_e:
                    logger.error(f"Erreur récupération emails envoyés Outlook après refresh: {retry_e}")
                    return []
            # Audit P1-A5 : 429 throttle one-shot retry (cf. get_messages).
            if self._is_throttle_error(e):
                delay = self._retry_after_seconds(e, default=30.0)
                logger.warning(f"Outlook 429 sur sent emails — sleep {delay:.1f}s, retry once")
                import time as _t
                _t.sleep(delay)
                try:
                    return _fetch()
                except Exception as retry_e:
                    logger.error(f"Erreur sent emails Outlook après throttle retry: {retry_e}")
                    return []
            logger.error(f"Erreur récupération emails envoyés Outlook: {e}")
            return []

    async def _get_archived_messages_async(self, limit: int) -> List[Message]:
        """Fetch messages from user folders that aren't standard system folders.

        Walks every mail folder, skips the well-known ones (inbox, sentitems,
        drafts, deleteditems, junkemail, outbox, conversationhistory), and
        queries messages in the rest — the `Archive` folder, any custom user
        folders (clients, projects, etc.). This is the Outlook equivalent of
        Gmail's "not in Inbox/Sent/Spam/Trash" slice.
        """
        self._ensure_authenticated()

        folders = await self._list_folders_async()
        if not folders:
            return []

        system_wkns = {
            "inbox", "sentitems", "drafts", "deleteditems",
            "junkemail", "outbox", "conversationhistory",
        }
        target_folder_ids: List[str] = []
        for f in folders:
            wkn = getattr(f, "well_known_name", None)
            folder_id = getattr(f, "id", None) or ""
            if not folder_id:
                continue
            if wkn and wkn.lower() in system_wkns:
                continue
            target_folder_ids.append(folder_id)

        if not target_folder_ids:
            return []

        # Share the budget across target folders (most recent first). Graph
        # caps $top at 1000; we batch at 250 per folder to stay responsive.
        per_folder = max(1, min(250, limit // max(len(target_folder_ids), 1)))
        collected: List[Message] = []

        query_params = FolderMessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
            top=per_folder,
            orderby=["receivedDateTime desc"],
            select=["id", "from", "toRecipients", "ccRecipients", "subject",
                    "body", "sentDateTime", "receivedDateTime", "isRead",
                    "hasAttachments", "conversationId", "importance",
                    "categories", "webLink"],
        )
        request_config = FolderMessagesRequestBuilder.MessagesRequestBuilderGetRequestConfiguration(
            query_parameters=query_params,
        )

        for fid in target_folder_ids:
            if len(collected) >= limit:
                break
            try:
                result = await self._client.users.by_user_id(
                    self.user_id
                ).mail_folders.by_mail_folder_id(fid).messages.get(
                    request_configuration=request_config,
                )
                msgs = result.value if result and result.value else []
                collected.extend(msgs[: limit - len(collected)])
            except Exception as e:
                # Some folders are unreadable (permission quirks); skip and continue.
                logger.debug(f"Outlook archive fetch: skipped folder {fid}: {e}")

        return collected

    def get_archived_messages(self, limit: int = 2000) -> List[StandardEmail]:
        """Fetch archived / user-foldered messages.

        Outlook equivalent of Gmail's archived slice: everything that isn't
        in a standard system folder. Covers the `Archive` well-known folder
        and any custom user folders the user has created for organisation.
        """
        from concurrent.futures import ThreadPoolExecutor

        def _fetch() -> list:
            messages = _run_async(self._get_archived_messages_async(limit))
            if not messages:
                return []
            with ThreadPoolExecutor(max_workers=4) as executor:
                return list(executor.map(self._map_to_standard_email, messages))

        try:
            emails = _fetch()
            logger.info(f"Outlook archive fetch: {len(emails)} archived messages")
            return emails
        except Exception as e:
            if self._is_auth_error(e):
                logger.warning("Outlook 401 sur archive, rafraîchissement des tokens...")
                try:
                    self._reset_and_reauth()
                    emails = _fetch()
                    logger.info(f"Outlook archive fetch (après refresh): {len(emails)} messages")
                    return emails
                except Exception as retry_e:
                    logger.error(f"Erreur archive Outlook après refresh: {retry_e}")
                    return []
            if self._is_throttle_error(e):
                delay = self._retry_after_seconds(e, default=30.0)
                logger.warning(f"Outlook 429 sur archive — sleep {delay:.1f}s, retry once")
                import time as _t
                _t.sleep(delay)
                try:
                    return _fetch()
                except Exception as retry_e:
                    logger.error(f"Erreur archive Outlook après throttle retry: {retry_e}")
                    return []
            logger.error(f"Erreur archive Outlook: {e}")
            return []

    async def _get_inbox_backfill_async(self, limit: int) -> List[Message]:
        """Fetch inbox messages ordered by receivedDateTime desc, paginated."""
        self._ensure_authenticated()

        # Graph caps $top at 1000; stay at 500 per page to avoid timeouts.
        page_size = min(500, limit)
        query_params = FolderMessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
            top=page_size,
            orderby=["receivedDateTime desc"],
            select=["id", "from", "toRecipients", "ccRecipients", "subject",
                    "body", "receivedDateTime", "isRead", "hasAttachments",
                    "conversationId", "importance", "categories", "webLink"],
        )
        request_config = FolderMessagesRequestBuilder.MessagesRequestBuilderGetRequestConfiguration(
            query_parameters=query_params,
        )

        try:
            result = await self._client.users.by_user_id(
                self.user_id
            ).mail_folders.by_mail_folder_id("inbox").messages.get(
                request_configuration=request_config,
            )
            msgs = result.value if result and result.value else []
            return msgs[:limit]
        except Exception as e:
            logger.debug(f"Outlook inbox backfill fetch: {e}")
            return []

    def get_inbox_backfill(self, limit: int = 1000) -> List[StandardEmail]:
        """Deep historical fetch of Inbox messages (parallel to archive backfill).

        The delta sync (receivedDateTime > since) only covers events after
        the last checkpoint. Emails that sat in the Inbox before Agentys
        was installed never enter the DB — causing their senders to appear
        as one-way contacts (received_count=0) even though the user has
        ongoing correspondence with them.
        """
        from concurrent.futures import ThreadPoolExecutor

        def _fetch() -> list:
            messages = _run_async(self._get_inbox_backfill_async(limit))
            if not messages:
                return []
            with ThreadPoolExecutor(max_workers=4) as executor:
                return list(executor.map(self._map_to_standard_email, messages))

        try:
            emails = _fetch()
            logger.info(f"Outlook inbox backfill: {len(emails)} messages")
            return emails
        except Exception as e:
            if self._is_auth_error(e):
                try:
                    self._reset_and_reauth()
                    emails = _fetch()
                    logger.info(f"Outlook inbox backfill (after refresh): {len(emails)} messages")
                    return emails
                except Exception as retry_e:
                    logger.error(f"Outlook inbox backfill after refresh: {retry_e}")
                    return []
            if self._is_throttle_error(e):
                delay = self._retry_after_seconds(e, default=30.0)
                logger.warning(f"Outlook 429 sur inbox backfill — sleep {delay:.1f}s, retry once")
                import time as _t
                _t.sleep(delay)
                try:
                    return _fetch()
                except Exception as retry_e:
                    logger.error(f"Outlook inbox backfill après throttle retry: {retry_e}")
                    return []
            logger.error(f"Outlook inbox backfill error: {e}")
            return []

    async def _list_folders_async(self) -> List[dict]:
        """Liste les dossiers mail de manière asynchrone."""
        self._ensure_authenticated()

        try:
            result = await self._client.users.by_user_id(
                self.user_id
            ).mail_folders.get()
            return result.value if result and result.value else []
        except Exception as e:
            logger.error(f"Erreur listage dossiers Outlook: {e}")
            return []

    def list_folders(self) -> List[EmailFolder]:
        """
        Liste les dossiers mail Outlook de l'utilisateur.

        Returns:
            Liste de dossiers normalisés (EmailFolder).
        """

        try:
            folders_data = _run_async(self._list_folders_async())

            if not folders_data:
                return []

            # System folders in Outlook
            system_folder_ids = {
                "inbox", "drafts", "sentitems", "deleteditems",
                "junkemail", "archive", "outbox"
            }

            folders = []
            for folder in folders_data:
                folder_id = getattr(folder, 'id', '') or ''
                folder_name = getattr(folder, 'display_name', '') or ''

                # Determine folder type based on well-known name
                well_known_name = getattr(folder, 'well_known_name', None)
                folder_type = "system" if well_known_name and well_known_name.lower() in system_folder_ids else "user"

                # Get counts
                unread_count = getattr(folder, 'unread_item_count', 0) or 0
                total_count = getattr(folder, 'total_item_count', 0) or 0

                # Get parent folder id
                parent_id = getattr(folder, 'parent_folder_id', None)

                folders.append(EmailFolder(
                    id=folder_id,
                    name=folder_name,
                    display_name=folder_name,
                    type=folder_type,
                    parent_id=parent_id,
                    unread_count=unread_count,
                    total_count=total_count,
                ))

            logger.info(f"Outlook list_folders: {len(folders)} folders")
            return folders

        except Exception as e:
            logger.error(f"Erreur listage dossiers Outlook: {e}")
            return []

    async def _get_draft_by_id_async(self, draft_id: str) -> Optional[Message]:
        """Récupère un brouillon par ID de manière asynchrone."""
        self._ensure_authenticated()

        try:
            message = await self._client.users.by_user_id(
                self.user_id
            ).messages.by_message_id(draft_id).get()
            return message
        except Exception:
            return None

    def get_draft_by_id(self, draft_id: str) -> Optional[StandardEmail]:
        """
        Récupère un brouillon par son ID.

        Args:
            draft_id: Identifiant du brouillon.

        Returns:
            Le brouillon ou None si non trouvé.
        """

        try:
            message = _run_async(self._get_draft_by_id_async(draft_id))
            if message:
                email = self._map_to_standard_email(message)
                return StandardEmail(
                    id=draft_id,
                    sender=email.sender,
                    sender_name=email.sender_name,
                    to=email.to,
                    cc=email.cc,
                    subject=email.subject,
                    body=email.body,
                    body_html=email.body_html,
                    received_at=email.received_at,
                    is_read=email.is_read,
                    has_attachments=email.has_attachments,
                    conversation_id=email.conversation_id,
                    provider_source=self.PROVIDER_NAME,
                    raw_metadata={
                        **email.raw_metadata,
                        "is_user_draft": True,
                        "draft_id": draft_id
                    }
                )
            return None
        except Exception as e:
            logger.error(f"Brouillon non trouvé {draft_id}: {e}")
            return None

    async def _update_draft_async(
        self,
        draft_id: str,
        subject: Optional[str],
        body: Optional[str],
        to: Optional[List[str]],
        cc: Optional[List[str]],
        bcc: Optional[List[str]],
        is_html: bool
    ) -> bool:
        """Met à jour un brouillon de manière asynchrone."""
        self._ensure_authenticated()

        try:
            # Récupérer le brouillon actuel pour fusionner les valeurs
            current = await self._get_draft_by_id_async(draft_id)
            if not current:
                return False

            # Préparer les destinataires
            to_recipients = None
            if to is not None:
                to_recipients = [
                    Recipient(email_address=EmailAddress(address=addr))
                    for addr in to
                ]
            elif current.to_recipients:
                to_recipients = current.to_recipients

            cc_recipients = None
            if cc is not None:
                cc_recipients = [
                    Recipient(email_address=EmailAddress(address=addr))
                    for addr in cc
                ]
            elif current.cc_recipients:
                cc_recipients = current.cc_recipients

            # Préparer les BCC (preserve existing if not explicitly changed)
            bcc_recipients = None
            if bcc is not None:
                bcc_recipients = [
                    Recipient(email_address=EmailAddress(address=addr))
                    for addr in bcc
                ]
            elif current.bcc_recipients:
                bcc_recipients = current.bcc_recipients

            # Préparer le corps
            item_body = None
            if body is not None:
                body_type = BodyType.Html if is_html else BodyType.Text
                item_body = ItemBody(content=body, content_type=body_type)
            elif current.body:
                item_body = current.body

            # Créer l'objet de mise à jour
            update = Message(
                subject=subject if subject is not None else current.subject,
                body=item_body,
                to_recipients=to_recipients,
                cc_recipients=cc_recipients,
                bcc_recipients=bcc_recipients,
            )

            # Appliquer la mise à jour
            await self._client.users.by_user_id(
                self.user_id
            ).messages.by_message_id(draft_id).patch(update)

            logger.info(f"Brouillon {draft_id} mis à jour")
            return True

        except Exception as e:
            logger.error(f"Erreur mise à jour brouillon {draft_id}: {e}")
            return False

    def update_draft(
        self,
        draft_id: str,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        to: Optional[List[str]] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        is_html: bool = False
    ) -> bool:
        """
        Met à jour un brouillon existant.

        Args:
            draft_id: ID du brouillon à modifier.
            subject: Nouveau sujet (optionnel).
            body: Nouveau corps (optionnel).
            to: Nouveaux destinataires (optionnel).
            cc: Nouvelle liste CC (optionnel).
            bcc: Nouvelle liste BCC (optionnel).
            is_html: True si le body est en HTML.

        Returns:
            True si la mise à jour réussit.
        """

        try:
            return _run_async(self._update_draft_async(
                draft_id=draft_id,
                subject=subject,
                body=body,
                to=to,
                cc=cc,
                bcc=bcc,
                is_html=is_html
            ))
        except Exception as e:
            logger.error(f"Erreur mise à jour brouillon: {e}")
            return False

    def search_subscription_emails(self, limit: int = 200) -> List[StandardEmail]:
        """
        Search for subscription/billing related emails via Outlook Graph API.

        Uses OData $search to find receipts, invoices, and billing emails.
        Extracts internet message headers for List-Unsubscribe.

        Args:
            limit: Maximum number of emails to scan.

        Returns:
            List of StandardEmail with list_unsubscribe in raw_metadata.
        """

        try:
            emails = _run_async(self._search_subscription_emails_async(limit))
            return emails
        except Exception as e:
            logger.error(f"Outlook subscription search error: {e}")
            return []

    async def _search_subscription_emails_async(self, limit: int) -> List[StandardEmail]:
        """Async implementation of subscription email search."""
        self._ensure_authenticated()

        keywords = ["receipt", "invoice", "payment", "subscription", "billing"]
        search_query = " OR ".join(f'subject:"{kw}"' for kw in keywords)

        query_params = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
            search=search_query,
            top=limit,
            orderby=["receivedDateTime desc"],
            select=["id", "from", "subject", "receivedDateTime", "isRead",
                    "conversationId", "internetMessageHeaders"],
        )

        request_config = MessagesRequestBuilder.MessagesRequestBuilderGetRequestConfiguration(
            query_parameters=query_params
        )

        result = await self._client.users.by_user_id(self.user_id).messages.get(
            request_configuration=request_config
        )

        messages = list(result.value) if result and result.value else []

        # Also search junk email folder for subscription emails
        try:
            junk_result = await (
                self._client.users.by_user_id(self.user_id)
                .mail_folders.by_mail_folder_id("junkemail")
                .messages.get(request_configuration=request_config)
            )
            if junk_result and junk_result.value:
                seen_ids = {m.id for m in messages}
                for m in junk_result.value:
                    if m.id not in seen_ids:
                        messages.append(m)
        except Exception as e:
            logger.debug(f"Outlook junk folder subscription search skipped: {e}")

        emails = []

        for message in messages:
            sender_email = ""
            sender_name = None
            if message.from_ and message.from_.email_address:
                sender_email = message.from_.email_address.address or ""
                sender_name = message.from_.email_address.name

            received_at = message.received_date_time if message.received_date_time else None

            # Extract List-Unsubscribe from internet message headers
            list_unsub = ""
            list_unsub_post = ""
            if message.internet_message_headers:
                for header in message.internet_message_headers:
                    if header.name and header.name.lower() == "list-unsubscribe":
                        list_unsub = header.value or ""
                    elif header.name and header.name.lower() == "list-unsubscribe-post":
                        list_unsub_post = header.value or ""

            emails.append(StandardEmail(
                id=message.id or "",
                subject=message.subject or "",
                sender=sender_email,
                sender_name=sender_name,
                body="",
                body_html=None,
                received_at=received_at,
                is_read=message.is_read or False,
                has_attachments=False,
                conversation_id=message.conversation_id,
                provider_source=self.PROVIDER_NAME,
                raw_metadata={
                    "list_unsubscribe": list_unsub,
                    "list_unsubscribe_post": list_unsub_post,
                    "header_only": True,
                },
            ))

        logger.info(f"Outlook found {len(emails)} subscription-related emails")
        return emails

    def search_newsletter_emails(self, limit: int = 300) -> List[StandardEmail]:
        """
        Search for newsletter emails via Outlook Graph API.

        Uses $search for newsletter keywords and filters results
        that have List-Unsubscribe in internet message headers.

        Args:
            limit: Maximum number of emails to scan.

        Returns:
            List of StandardEmail with list_unsubscribe in raw_metadata.
        """

        try:
            emails = _run_async(self._search_newsletter_emails_async(limit))
            return emails
        except Exception as e:
            logger.error(f"Outlook newsletter search error: {e}")
            return []

    async def _search_newsletter_emails_async(self, limit: int) -> List[StandardEmail]:
        """Async implementation of newsletter email search."""
        self._ensure_authenticated()

        keywords = ["newsletter", "unsubscribe", "weekly", "digest"]
        search_query = " OR ".join(f'subject:"{kw}"' for kw in keywords)

        query_params = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
            search=search_query,
            top=limit,
            orderby=["receivedDateTime desc"],
            select=["id", "from", "subject", "receivedDateTime", "isRead",
                    "conversationId", "internetMessageHeaders"],
        )

        request_config = MessagesRequestBuilder.MessagesRequestBuilderGetRequestConfiguration(
            query_parameters=query_params
        )

        result = await self._client.users.by_user_id(self.user_id).messages.get(
            request_configuration=request_config
        )

        messages = result.value if result and result.value else []
        emails = []

        for message in messages:
            list_unsub = ""
            list_unsub_post = ""
            if message.internet_message_headers:
                for header in message.internet_message_headers:
                    if header.name and header.name.lower() == "list-unsubscribe":
                        list_unsub = header.value or ""
                    elif header.name and header.name.lower() == "list-unsubscribe-post":
                        list_unsub_post = header.value or ""

            if not list_unsub:
                continue

            sender_email = ""
            sender_name = None
            if message.from_ and message.from_.email_address:
                sender_email = message.from_.email_address.address or ""
                sender_name = message.from_.email_address.name

            received_at = message.received_date_time if message.received_date_time else None

            emails.append(StandardEmail(
                id=message.id or "",
                subject=message.subject or "",
                sender=sender_email,
                sender_name=sender_name,
                body="",
                body_html=None,
                received_at=received_at,
                is_read=message.is_read or False,
                has_attachments=False,
                conversation_id=message.conversation_id,
                provider_source=self.PROVIDER_NAME,
                raw_metadata={
                    "list_unsubscribe": list_unsub,
                    "list_unsubscribe_post": list_unsub_post,
                    "header_only": True,
                },
            ))

        logger.info(f"Outlook found {len(emails)} newsletter emails")
        return emails

    @staticmethod
    def _extract_signature_div(html_content: str) -> Optional[dict]:
        """Extract signature from <div id="Signature"> or <div class="*signature*">.

        Handles nested <div> elements by counting open/close tags to find
        the matching closing </div> of the signature container.

        Returns:
            Dict with 'html' and 'text' keys, or None.
        """
        import re

        patterns = [
            r'<div[^>]*id=["\']?Signature["\']?[^>]*>',
            r'<div[^>]*class=["\']?[^"\']*signature[^"\']*["\']?[^>]*>',
        ]

        for pat in patterns:
            start_m = re.search(pat, html_content, re.IGNORECASE)
            if not start_m:
                continue

            # Walk forward from end of opening tag, counting nested div depth
            pos = start_m.end()
            depth = 1
            while depth > 0 and pos < len(html_content):
                open_m = re.search(r'<div\b', html_content[pos:], re.IGNORECASE)
                close_m = re.search(r'</div\s*>', html_content[pos:], re.IGNORECASE)
                if close_m is None:
                    break  # malformed HTML — give up
                if open_m and open_m.start() < close_m.start():
                    depth += 1
                    pos += open_m.end()
                else:
                    depth -= 1
                    if depth == 0:
                        inner_html = html_content[start_m.end():pos + close_m.start()]
                        sig_text = re.sub(r'<[^>]+>', '', inner_html)
                        sig_text = sig_text.replace('&nbsp;', ' ')
                        sig_text = re.sub(r'\s+', ' ', sig_text).strip()
                        if len(sig_text) > 10:
                            sig_html = html_content[start_m.start():pos + close_m.end()]
                            logger.info("Outlook signature extracted (HTML div) from sent emails: %r", sig_text[:80])
                            return {"html": sig_html, "text": sig_text}
                    pos += close_m.end()

        return None

    # Headers the labelizer's RFC noise rules consume — kept in sync with
    # GmailAdapter._CLASSIFICATION_HEADER_NAMES_FOR_BACKFILL so a backfill
    # produces equivalent raw_headers payloads across providers.
    _CLASSIFICATION_HEADER_NAMES_FOR_BACKFILL = (
        "List-Unsubscribe",
        "Precedence",
        "Auto-Submitted",
        "X-Auto-Response-Suppress",
        "X-Mailer",
        "Reply-To",
    )

    def fetch_classification_headers_batch(
        self,
        message_ids: List[str],
    ) -> Dict[str, Dict[str, str]]:
        """Fetch RFC bulk-classification headers for Outlook message IDs.

        Mirrors ``GmailAdapter.fetch_classification_headers_batch`` so the
        metadata-only header-backfill endpoint (``app/api/labels.py``) works for
        Outlook accounts instead of dead-ending with "Gmail uniquement pour
        l'instant". Uses a per-message ``$select=internetMessageHeaders`` fetch
        (no body download) and returns lowercase header keys, matching the shape
        ``sync_service`` persists into ``Email.raw_headers``.

        NOTE: this powers the on-demand historical backfill. Fresh-sync header
        inclusion is deliberately NOT added to the hot ``get_messages`` path —
        pulling internetMessageHeaders for every synced message would inflate
        the Graph payload for all Outlook users (a separate perf tradeoff).
        """
        import requests as _req
        import urllib.parse

        self._ensure_authenticated()
        if not message_ids or not self._access_token:
            return {}

        wanted = {name.lower() for name in self._CLASSIFICATION_HEADER_NAMES_FOR_BACKFILL}
        out: Dict[str, Dict[str, str]] = {}
        headers = {"Authorization": f"Bearer {self._access_token}"}

        for msg_id in message_ids:
            if not msg_id:
                continue
            try:
                encoded = urllib.parse.quote(msg_id, safe="")
                url = (
                    f"https://graph.microsoft.com/v1.0/users/{self.user_id}"
                    f"/messages/{encoded}?$select=internetMessageHeaders"
                )
                resp = _graph_request_with_retry(_req.get, url, headers=headers, timeout=15)
                if resp.status_code != 200:
                    continue
                extracted: Dict[str, str] = {}
                for hdr in resp.json().get("internetMessageHeaders", []) or []:
                    name = (hdr.get("name") or "").lower()
                    value = hdr.get("value")
                    if name in wanted and value:
                        extracted[name] = value
                if extracted:
                    out[msg_id] = extracted
            except Exception as _e:  # noqa: BLE001
                logger.debug("Outlook fetch_classification_headers_batch(%s): %s", msg_id, _e)
                continue
        return out

    def get_signature(self) -> Optional[dict]:
        """
        Récupère la signature email de l'utilisateur depuis Outlook.

        Strategy:
        1. Try mailboxSettings (Graph API exposes signature in recent SDK versions)
        2. Fallback: extract from recent SENT emails by pattern matching

        Returns:
            Dict with 'html' and 'text' keys, or None if no signature found.
        """
        import re

        async def _get_signature_async():
            self._ensure_authenticated()

            async def _from_mailbox_settings():
                """Legacy Graph mailboxSettings signature — FALLBACK ONLY.

                Modern OWA stores signatures in roaming cloud settings that
                Graph does NOT expose; this legacy field can be years stale
                (2026-06 import bug: it returned an obsolete signature variant
                instead of the one visible in every recent sent email). The
                sent-items extraction reflects what the user actually sends
                today, so it runs FIRST and this only covers empty/unreadable
                sent folders.
                """
                try:
                    settings = await self._client.users.by_user_id(
                        self.user_id
                    ).mailbox_settings.get()

                    if settings:
                        # Recent Graph API versions expose signature properties
                        sig_html = (
                            getattr(settings, 'signature_for_new_messages', None)
                            or getattr(settings, 'signatureForNewMessages', None)
                        )
                        if not sig_html:
                            # Try additional_data dict (SDK may store unknown props there)
                            ad = getattr(settings, 'additional_data', {}) or {}
                            sig_html = ad.get('signatureForNewMessages') or ad.get('signatureForRepliesOrForwards')

                        if sig_html and len(sig_html.strip()) > 5:
                            sig_text = re.sub(r'<[^>]+>', '', sig_html)
                            sig_text = sig_text.replace('&nbsp;', ' ')
                            sig_text = re.sub(r'\s+', ' ', sig_text).strip()
                            logger.info("Outlook signature fetched from mailboxSettings")
                            return {"html": sig_html, "text": sig_text}
                except Exception as e:
                    logger.debug(f"mailboxSettings signature not available: {e}")
                return None

            try:
                # --- Strategy 1: extract from recent SENT emails (newest first) ---
                sent_emails = await self._get_messages_async(
                    limit=10, unread_only=False, folder_id="sentitems"
                )

                if not sent_emails:
                    logger.debug("No sent emails found to extract signature")
                    return await _from_mailbox_settings()

                for email in sent_emails:
                    body_obj = getattr(email, 'body', None)
                    if not body_obj:
                        continue
                    content = (
                        body_obj.content
                        if hasattr(body_obj, 'content') and body_obj.content
                        else (body_obj.get('content', '') if isinstance(body_obj, dict) else '')
                    )
                    if not content or len(content) < 30:
                        continue

                    # Detect whether body is HTML or plain text.
                    # Require that the tag name is followed by \s, >, or / — this excludes
                    # email addresses like <alexandre@host> where the next char is a letter.
                    is_html = bool(re.search(
                        r'<(?:div|html|body|span|table|tr|td|th|ul|ol|li|h[1-6]|em|strong|b|i|a|p|br|hr)(?=[\s>/])',
                        content, re.IGNORECASE
                    ))

                    # Strip quoted/forwarded thread BEFORE looking for the signature.
                    # The signature lives in the NEW content part (before the separator).
                    if is_html:
                        # HTML email: separator is <hr> or a border-top div
                        new_content = re.split(r'<hr[^>]*>', content, maxsplit=1, flags=re.IGNORECASE)[0]
                        new_content = re.split(
                            r'<div[^>]*style=["\'][^"\']*border-top[^"\']*["\'][^>]*>',
                            new_content, maxsplit=1, flags=re.IGNORECASE
                        )[0]
                    else:
                        # Plain text email: separator is 5+ underscores or "De :" / "From:"
                        new_content = re.split(r'\n_{5,}', content, maxsplit=1)[0]
                        new_content = re.split(r'\n(?:De\s*:|From\s*:)', new_content, maxsplit=1, flags=re.IGNORECASE)[0]

                    logger.debug(
                        "[signature] body type=%s, new_content_len=%s",
                        "html" if is_html else "text",
                        len(new_content),
                    )

                    if is_html:
                        # --- Nested-div-safe extraction for id="Signature" or class="*signature*" ---
                        sig_result = self._extract_signature_div(new_content)
                        if sig_result:
                            return sig_result

                        # Standard text separator "-- " followed by BR (HTML context only)
                        sep_match = re.search(r'--\s*<br\s*/?>(.*?)(?:</div>|</p>)', new_content, re.DOTALL | re.IGNORECASE)
                        if sep_match:
                            sig_html = sep_match.group(1)
                            sig_text = re.sub(r'<[^>]+>', '', sig_html).replace('&nbsp;', ' ')
                            sig_text = re.sub(r'\s+', ' ', sig_text).strip()
                            if len(sig_text) > 10:
                                logger.info("Outlook signature extracted (HTML --br) from sent emails: %r", sig_text[:80])
                                return {"html": sig_html, "text": sig_text}

                        # Closing-phrase heuristic for HTML: extract content after a closing
                        # phrase (Cordialement, Best regards, etc.) within new_content.
                        closing_re = r'(?:Cordialement|Best regards?|Regards|Bien à vous|Sincèrement|À bientôt|Merci|Thanks|Thank you)[,.]?\s*(?:<br\s*/?>|</(?:div|p)>)'
                        closing_m = re.search(closing_re, new_content, re.IGNORECASE)
                        if closing_m:
                            after_closing = new_content[closing_m.end():]
                            # Strip remaining HTML, see if what follows looks like a signature
                            after_text = re.sub(r'<[^>]+>', '\n', after_closing)
                            after_text = after_text.replace('&nbsp;', ' ')
                            after_text = re.sub(r'\n{3,}', '\n\n', after_text).strip()
                            after_lines = [ln for ln in after_text.splitlines() if ln.strip()]
                            if 1 <= len(after_lines) <= 6 and 10 < len(after_text) <= 400:
                                # Also keep the HTML version (from closing phrase onward)
                                sig_html_block = new_content[closing_m.start():]
                                logger.info("Outlook signature extracted (HTML closing-phrase) from sent emails: %r", after_text[:80])
                                return {"html": sig_html_block, "text": after_text}
                    else:
                        # Plain text patterns — NO re.DOTALL, use lazy match per line
                        # "-- " separator (RFC 3676 signature delimiter)
                        pt_match = re.search(r'^--\s*\n(.+?)(?:\n\n|$)', new_content, re.MULTILINE)
                        if pt_match:
                            sig_text = pt_match.group(1).strip()
                            if len(sig_text) > 10:
                                logger.info("Outlook signature extracted (plain text) from sent emails: %r", sig_text[:80])
                                return {"html": sig_text.replace('\n', '<br>'), "text": sig_text}

                        # Last paragraph heuristic: look for the last double-newline-separated
                        # block that is short (≤300 chars, ≤5 lines) — typical signature shape.
                        # Only applies when the body has multiple paragraphs (to avoid capturing
                        # the entire body of a single-paragraph message).
                        paragraphs = [p.strip() for p in re.split(r'\n{2,}', new_content.strip()) if p.strip()]
                        if len(paragraphs) >= 2:
                            last_para = paragraphs[-1]
                            # Strip trailing lines that are only underscores (Outlook separator artifact)
                            para_lines = last_para.splitlines()
                            while para_lines and re.match(r'^[_ ]+$', para_lines[-1]):
                                para_lines.pop()
                            last_para = '\n'.join(para_lines)
                            last_lines = last_para.splitlines()
                            if len(last_lines) <= 5 and len(last_para) <= 300:
                                sig_text = last_para.strip()
                                if len(sig_text) > 10:
                                    logger.info("Outlook signature extracted (last-para) from sent emails: %r", sig_text[:80])
                                    return {"html": sig_text.replace('\n', '<br>'), "text": sig_text}

                logger.debug("Could not extract signature from Outlook sent emails")
                # --- Strategy 2 (fallback): legacy mailboxSettings ---
                return await _from_mailbox_settings()

            except Exception as e:
                logger.error(f"Error fetching Outlook signature: {e}")
                # Sent-items fetch blew up (e.g. Graph throttling) — the
                # legacy mailboxSettings fallback may still have something.
                return await _from_mailbox_settings()

        try:
            return _run_async(_get_signature_async())
        except Exception as e:
            logger.error(f"Error in get_signature: {e}")
            return None

    # =========================================================================
    # Delta Sync (Issue #27)
    # =========================================================================

    def _map_raw_dict_to_standard_email(self, msg: dict) -> StandardEmail:
        """
        Convert a raw Graph API JSON dict to StandardEmail.

        Unlike _map_to_standard_email() which expects an msgraph SDK Message object,
        this handles the raw JSON dicts returned by the delta endpoint.
        """
        sender_email = ""
        sender_name = None
        from_data = msg.get("from", {})
        if from_data:
            email_addr = from_data.get("emailAddress", {})
            sender_email = email_addr.get("address", "")
            sender_name = email_addr.get("name")

        to_list = []
        for r in msg.get("toRecipients", []):
            addr = r.get("emailAddress", {}).get("address")
            if addr:
                to_list.append(addr)

        cc_list = []
        for r in msg.get("ccRecipients", []):
            addr = r.get("emailAddress", {}).get("address")
            if addr:
                cc_list.append(addr)

        body_text = ""
        body_html = None
        body_data = msg.get("body", {})
        if body_data:
            content = body_data.get("content", "")
            if body_data.get("contentType", "").lower() == "html":
                body_html = content
                body_text = self._extract_text_from_html(content)
                # Resolve inline cid: images so delta-synced messages render them too.
                body_html = self._resolve_outlook_inline_images(
                    msg.get("id", ""), body_html, bool(msg.get("hasAttachments", False))
                )
            else:
                body_text = content

        received_at = None
        received_str = msg.get("receivedDateTime")
        if received_str:
            try:
                received_at = datetime.fromisoformat(received_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        return StandardEmail(
            id=msg.get("id", ""),
            sender=sender_email,
            sender_name=sender_name,
            to=to_list,
            cc=cc_list,
            subject=msg.get("subject", ""),
            body=body_text.strip(),
            body_html=body_html,
            received_at=received_at,
            is_read=msg.get("isRead", False),
            has_attachments=msg.get("hasAttachments", False),
            conversation_id=msg.get("conversationId"),
            provider_source=self.PROVIDER_NAME,
            raw_metadata={
                "importance": msg.get("importance"),
                "categories": msg.get("categories", []),
                "web_link": msg.get("webLink"),
            }
        )

    def get_current_history_id(self) -> Optional[str]:
        """
        Initialize delta tracking by performing an initial delta query.

        Calls GET /me/mailFolders/inbox/messages/delta without a token, pages
        through all results, and returns the final @odata.deltaLink.
        This URL serves as the checkpoint for subsequent delta syncs.

        Returns:
            DeltaLink URL string, or None on failure.
        """
        import requests as http_requests

        async def _get_delta_token():
            self._ensure_authenticated()

            if not self._access_token:
                logger.error("No access token available for delta init")
                return None

            headers = {"Authorization": f"Bearer {self._access_token}"}
            url = (
                f"https://graph.microsoft.com/v1.0/users/{self.user_id}"
                f"/mailFolders/inbox/messages/delta"
                f"?$select={self._DELTA_SELECT}&$top=50"
            )

            # Page through all results to get to the final deltaLink.
            # P1-A5 (2026-04-26): route through _graph_request_with_retry so
            # Microsoft's 429 Retry-After is honoured (~30s) instead of
            # bubbling up as a generic failure that triggers a 10-min auth
            # backoff in sync_service.
            while url:
                resp = _graph_request_with_retry(
                    http_requests.get, url, headers=headers, timeout=30
                )
                if resp.status_code != 200:
                    logger.error(f"Delta init failed: HTTP {resp.status_code}")
                    return None

                data = resp.json()
                next_link = data.get("@odata.nextLink")
                delta_link = data.get("@odata.deltaLink")

                if delta_link:
                    logger.info("Outlook delta token initialized")
                    return delta_link

                if next_link:
                    url = next_link
                else:
                    break

            logger.warning("No deltaLink found in delta init response")
            return None

        try:
            return _run_async(_get_delta_token())
        except Exception as e:
            logger.error(f"Error getting Outlook delta token: {e}")
            return None

    def get_history_changes(
        self, start_history_id: str, limit: int = 100
    ) -> dict:
        """
        Fetch incremental changes via Microsoft Graph delta API.

        Uses the deltaToken from the previous sync to fetch only new/changed
        messages. Much faster than timestamp-based queries.

        Args:
            start_history_id: Delta token or full deltaLink URL from last sync.
            limit: Maximum number of added messages to return.

        Returns:
            Dict with 'added', 'deleted', 'label_changes', 'new_history_id'.
            Returns None for 'new_history_id' if the token expired (410 Gone).
        """
        import requests as http_requests

        async def _fetch_delta():
            self._ensure_authenticated()

            if not self._access_token:
                logger.error("No access token for delta sync")
                return {
                    "added": [], "deleted": [], "label_changes": [],
                    "new_history_id": None,
                }

            headers = {"Authorization": f"Bearer {self._access_token}"}

            # Build the delta URL from the stored token
            if start_history_id.startswith("http"):
                # Full deltaLink URL stored
                url = start_history_id
            else:
                # Just the raw token value. A $deltatoken already encodes the
                # $select it was created with, so we must NOT re-append $select
                # here (Graph can reject a deltatoken request that also carries
                # $select). A token minted before the _DELTA_SELECT fix is
                # id-only and self-heals via the poisoned-checkpoint guard below.
                url = (
                    f"https://graph.microsoft.com/v1.0/users/{self.user_id}"
                    f"/mailFolders/inbox/messages/delta"
                    f"?$deltatoken={start_history_id}"
                )

            added_msgs: list[dict] = []
            deleted_ids: list[str] = []
            new_token = None

            while url:
                # P1-A5 (2026-04-26): same Retry-After handling as delta init.
                resp = _graph_request_with_retry(
                    http_requests.get, url, headers=headers, timeout=30
                )

                # 410 Gone or 404 = token expired
                if resp.status_code in (404, 410):
                    logger.warning("Outlook delta token expired, need full sync")
                    return {
                        "added": [], "deleted": [], "label_changes": [],
                        "new_history_id": None,
                    }

                if resp.status_code != 200:
                    logger.error(f"Outlook delta sync failed: HTTP {resp.status_code}")
                    raise RuntimeError(f"Delta sync HTTP {resp.status_code}")

                data = resp.json()

                # Process messages in this page
                for msg in data.get("value", []):
                    # Check if this is a deletion (reason == "deleted")
                    if msg.get("@removed"):
                        deleted_ids.append(msg.get("id", ""))
                    else:
                        added_msgs.append(msg)

                # Check for next page or final delta link
                next_link = data.get("@odata.nextLink")
                delta_link = data.get("@odata.deltaLink")

                if delta_link:
                    new_token = delta_link
                    url = None
                elif next_link:
                    url = next_link
                else:
                    url = None

            # Self-heal legacy "poisoned" checkpoints (2026-06-23). Accounts whose
            # delta token was created before the $select fix carry an id-only
            # checkpoint baked into the opaque $deltatoken — Microsoft Graph keeps
            # honouring that select forever, so every change comes back with NO
            # from/subject/receivedDateTime and would persist as a blank inbox row
            # ("(No subject)" + empty sender). Detect it (changes present, yet not
            # one carries the metadata we now request) and surface it like an
            # expired token: drop the blanks and return new_history_id=None so
            # sync_service falls back to the timestamp sync and then re-initialises
            # a healthy deltaLink via get_current_history_id().
            if added_msgs and not any(
                ("from" in m) or ("subject" in m) or ("receivedDateTime" in m)
                for m in added_msgs
            ):
                logger.warning(
                    "Outlook delta token is metadata-less (legacy id-only "
                    "checkpoint) — discarding %d blank change(s) and forcing a "
                    "full re-init", len(added_msgs),
                )
                return {
                    "added": [], "deleted": deleted_ids, "label_changes": [],
                    "new_history_id": None,
                    # Distinguishes this from an ordinary 410-expiry so
                    # sync_service can schedule an inbox backfill to heal the
                    # blank rows the poisoned checkpoint already persisted.
                    "poisoned": True,
                }

            # Convert raw dicts to StandardEmail (capped at limit)
            added_emails = [
                self._map_raw_dict_to_standard_email(msg)
                for msg in added_msgs[:limit]
            ]

            # OL-04: propagate read-status changes. The delta payload carries the
            # current isRead for every changed message; emit it as UNREAD
            # add/remove so sync_service writes it to the DB row. Without this, an
            # email marked read/unread in Outlook web or mobile never updates the
            # Agentys unread badge until the next full timestamp resync (the
            # existing-row branch of _store_emails does not touch is_read).
            label_changes = []
            for msg in added_msgs:
                mid = msg.get("id")
                if not mid or "isRead" not in msg:
                    continue
                if msg.get("isRead"):
                    label_changes.append({"message_id": mid, "removed": ["UNREAD"]})
                else:
                    label_changes.append({"message_id": mid, "added": ["UNREAD"]})

            logger.info(
                f"Outlook delta sync: +{len(added_emails)} added, "
                f"-{len(deleted_ids)} deleted, "
                f"{len(label_changes)} read-status changes"
            )

            return {
                "added": added_emails,
                "deleted": deleted_ids,
                "label_changes": label_changes,
                "new_history_id": new_token,
            }

        try:
            return _run_async(_fetch_delta())
        except Exception as e:
            logger.error(f"Outlook delta sync error: {e}")
            raise
