# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adaptateur IMAP pour serveurs email génériques.

Implémente l'interface EmailProvider pour tout serveur IMAP.
Utilise imaplib (bibliothèque standard Python).
"""

import base64
import os
import re
import ssl
import time as _time
import imaplib
import socket
import email
import email.message
import logging
import threading
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import List, Optional, Tuple

from app.interfaces.email_provider import EmailProvider, StandardEmail, EmailFolder
from app.providers.email_parser_mixin import EmailParserMixin

logger = logging.getLogger(__name__)

# Limit concurrent IMAP connections across all threads.
# Gmail allows ~15 simultaneous IMAP connections per account; we cap at 5 to
# leave headroom for the user's own mail clients and avoid "Too many connections".
# 5 allows: sync service + prefetch + 3 concurrent user requests without contention.
_IMAP_CONNECTION_SEMAPHORE = threading.Semaphore(10)

# Module-level caches — persistent folder discovery between requests
# Format: key: (host, username) → (folder_name, timestamp)
# TTL de 1h pour éviter des caches stale si l'utilisateur renomme un dossier IMAP.
_FOLDER_CACHE_TTL = 3600  # 1 heure
_SENT_FOLDER_GLOBAL_CACHE: dict = {}
_SPAM_FOLDER_GLOBAL_CACHE: dict = {}
_TRASH_FOLDER_GLOBAL_CACHE: dict = {}
_DRAFTS_FOLDER_GLOBAL_CACHE: dict = {}
_ARCHIVE_FOLDER_GLOBAL_CACHE: dict = {}

# Keep-alive: liste des connexions actives (weak refs) + thread daemon
import weakref as _weakref

_active_imap_connections: list = []  # weak refs to IMAPSMTPAdapter instances
_keepalive_lock = threading.Lock()
_keepalive_thread_started = False  # Audit HIGH-8 (2026-04-25): lazy init guard


def _keepalive_worker() -> None:
    """Envoie NOOP toutes les 4 minutes sur les adaptateurs IMAP actifs.

    Accède à la connexion via _try_keepalive_noop() qui acquiert _connection_lock
    de façon non-bloquante pour éviter les races SSL avec les threads en cours.

    Audit MED-7 (2026-04-25): copie la liste sous lock, puis itère sans lock
    pour éviter de bloquer _register_imap_connection pendant ~30 s × N comptes
    sur un lien flaky.
    """
    while True:
        _time.sleep(240)  # 4 minutes
        with _keepalive_lock:
            snapshot = list(_active_imap_connections)
        alive = []
        for ref in snapshot:
            adapter = ref()
            if adapter is None:
                continue
            try:
                adapter._try_keepalive_noop()
            except Exception as e:
                logging.getLogger(__name__).debug(f"Keepalive worker error: {e}")
            alive.append(ref)
        with _keepalive_lock:
            _active_imap_connections[:] = alive


def _start_keepalive_thread_once() -> None:
    """Démarre le thread keepalive au premier register, jamais à l'import.

    Audit HIGH-8 (2026-04-25): démarrer un thread daemon à l'import top-level
    pose deux problèmes : (a) tests unitaires qui n'utilisent pas IMAP voient
    un thread parasite, (b) gunicorn pré-fork lance N threads (un par worker).
    Lazy-start sous lock garantit qu'on ne crée le thread que lors du premier
    enregistrement réel d'une connexion IMAP.
    """
    global _keepalive_thread_started
    if _keepalive_thread_started:
        return
    with _keepalive_lock:
        if _keepalive_thread_started:
            return
        threading.Thread(
            target=_keepalive_worker, daemon=True, name="imap-keepalive"
        ).start()
        _keepalive_thread_started = True


def _register_imap_connection(adapter) -> None:
    """Enregistre un adaptateur IMAP pour le keep-alive."""
    _start_keepalive_thread_once()
    with _keepalive_lock:
        _active_imap_connections.append(_weakref.ref(adapter))


def _get_folder_cache(cache: dict, key: tuple) -> str | None:
    """Lit un cache de dossier avec TTL. Retourne None si absent ou expiré."""
    entry = cache.get(key)
    if entry is None:
        return None
    folder_name, ts = entry
    if _time.time() - ts > _FOLDER_CACHE_TTL:
        del cache[key]
        return None
    return folder_name


def _set_folder_cache(cache: dict, key: tuple, folder_name: str) -> None:
    """Écrit dans un cache de dossier avec timestamp."""
    cache[key] = (folder_name, _time.time())



class IMAPAdapter(EmailProvider, EmailParserMixin):
    """
    Adaptateur IMAP générique.

    Fonctionne avec tout serveur IMAP (Gmail, Yahoo, serveurs privés, etc.)

    Variables d'environnement :
    - IMAP_HOST : Serveur IMAP (ex: imap.gmail.com)
    - IMAP_PORT : Port (993 par défaut pour SSL)
    - IMAP_USER : Nom d'utilisateur / email
    - IMAP_PASSWORD : Mot de passe ou App Password
    - IMAP_USE_SSL : Utiliser SSL (true par défaut)
    - IMAP_FOLDER : Dossier à consulter (INBOX par défaut)
    """

    PROVIDER_NAME = "imap"

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        use_ssl: bool = True,
        folder: str = "INBOX",
    ):
        """
        Initialise l'adaptateur IMAP.

        Args:
            host: Serveur IMAP
            port: Port (993 SSL, 143 non-SSL)
            username: Nom d'utilisateur
            password: Mot de passe
            use_ssl: Utiliser SSL/TLS
            folder: Dossier par défaut
        """
        self.host = host or os.getenv("IMAP_HOST")
        self.port = port or int(os.getenv("IMAP_PORT", "993" if use_ssl else "143"))
        self.username = username or os.getenv("IMAP_USER")
        self.password = password or os.getenv("IMAP_PASSWORD")
        self.use_ssl = use_ssl if use_ssl is not None else os.getenv("IMAP_USE_SSL", "true").lower() == "true"
        self.folder = folder or os.getenv("IMAP_FOLDER", "INBOX")

        # Fail fast on missing config so the factory can surface a clear
        # ProviderConfigurationError instead of imaplib raising deep down
        # the stack with a generic socket / login error.
        missing: list[str] = []
        if not self.host:
            missing.append("IMAP_HOST")
        if not self.username:
            missing.append("IMAP_USER")
        if not self.password:
            missing.append("IMAP_PASSWORD")
        if missing:
            raise ValueError(
                "IMAP configuration incomplete — missing: "
                + ", ".join(missing)
            )

        self._connection: Optional[imaplib.IMAP4_SSL | imaplib.IMAP4] = None
        self._authenticated = False
        self._auth_time: float = 0.0  # Timestamp of last successful auth
        self._semaphore_acquired = False  # True while holding _IMAP_CONNECTION_SEMAPHORE
        self._sent_folder_name: Optional[str] = None    # Cached sent folder name
        self._spam_folder_name: Optional[str] = None    # Cached spam folder name
        self._trash_folder_name: Optional[str] = None   # Cached trash folder name
        self._drafts_folder_name: Optional[str] = None  # Cached drafts folder name
        self._archived_folder_name: Optional[str] = None  # Cached archive folder name
        self._selected_folder: Optional[str] = None  # Last successfully selected folder (avoids redundant SELECT)
        self._connection_lock = threading.RLock()  # Protect SSL connection from concurrent access

    @property
    def provider_name(self) -> str:
        return self.PROVIDER_NAME

    # Map English Gmail folder names to their IMAP flag for auto-detection
    _FOLDER_FLAG_MAP = {
        "[Gmail]/Trash": r"\Trash",
        "[Gmail]/Spam": r"\Junk",
        "[Gmail]/All Mail": r"\All",
        "[Gmail]/Sent Mail": r"\Sent",
        "[Gmail]/Drafts": r"\Drafts",
    }

    def _resolve_localized_folder(self, english_name: str) -> str | None:
        """Resolve an English Gmail folder name to the localized IMAP name.

        Gmail uses localized folder names (e.g. [Gmail]/Corbeille instead of
        [Gmail]/Trash for French accounts). This method detects the correct name
        using IMAP LIST flags.
        """
        flag = self._FOLDER_FLAG_MAP.get(english_name)
        if not flag:
            return None

        import re
        try:
            status, folder_list = self._connection.list()
            if status == "OK" and folder_list:
                for entry in folder_list:
                    raw = entry.decode() if isinstance(entry, bytes) else str(entry)
                    flags_part = raw.split(")")[0] if ")" in raw else ""
                    if flag in flags_part:
                        m = re.search(r'"([^"]+)"\s*$', raw)
                        if m:
                            resolved = m.group(1)
                            logger.info(f"Resolved '{english_name}' -> '{resolved}' via IMAP flag {flag}")
                            return resolved
        except Exception as e:
            logger.debug(f"Failed to resolve localized folder for {english_name}: {e}")
        return None

    # Secondary folder names (lowercase) that may be slow on Gmail virtual folders.
    # These get an automatic 15s socket timeout guard during SELECT.
    _SECONDARY_FOLDER_KEYWORDS = frozenset([
        "spam", "junk", "trash", "deleted", "drafts", "draft",
        "all mail", "tous les messages", "archived",
    ])

    def _is_secondary_folder(self, folder_name: str) -> bool:
        """Check if a folder name matches a known slow/secondary IMAP folder."""
        lower = folder_name.strip('"').lower()
        return any(kw in lower for kw in self._SECONDARY_FOLDER_KEYWORDS)

    def _select_folder(self, folder_name: str, **kwargs):
        """Select an IMAP folder, quoting names that contain special characters.

        Skips the SELECT command if the folder is already selected (saves 1-3s per request).
        Pass force=True to force re-selection even if already selected.
        Pass timeout=N to temporarily set socket timeout for this SELECT (useful for
        slow Gmail virtual folders like Trash/Spam that can take 30-60s on first access).

        Secondary folders (spam, trash, junk, drafts, archived) automatically get a
        15-second timeout guard to prevent blocking on slow Gmail virtual folders.
        """
        force = kwargs.pop('force', False)
        select_timeout = kwargs.pop('timeout', None)
        normalized = folder_name.strip('"')
        if not force and self._selected_folder == normalized:
            return ("OK", [b"Already selected"])
        quoted = f'"{folder_name}"' if any(c in folder_name for c in ' []') else folder_name

        # Auto-apply 15s timeout for secondary folders if no explicit timeout given
        if select_timeout is None and self._is_secondary_folder(folder_name):
            select_timeout = 15

        old_timeout = None
        if select_timeout and self._connection and hasattr(self._connection, 'socket'):
            try:
                sock = self._connection.socket()
                old_timeout = sock.gettimeout()
                sock.settimeout(select_timeout)
            except Exception:
                old_timeout = None

        try:
            result = self._connection.select(quoted, **kwargs)
        except (socket.timeout, TimeoutError, OSError) as e:
            logger.warning(
                f"[TIMEOUT] IMAP SELECT '{folder_name}' timed out after {select_timeout}s: {e}"
            )
            result = ("TIMEOUT", [b"SELECT timed out"])
        finally:
            if old_timeout is not None and self._connection and hasattr(self._connection, 'socket'):
                try:
                    self._connection.socket().settimeout(old_timeout)
                except Exception:
                    pass

        if result[0] == "OK":
            self._selected_folder = normalized
        return result

    def authenticate(self) -> bool:
        """
        Authentifie via IMAP, avec retry pour les erreurs transitoires.

        Returns:
            True si l'authentification réussit.

        NOTE: Called with self._connection_lock held by _ensure_authenticated.
        """
        _MAX_ATTEMPTS = 3
        _RETRY_DELAYS = (0, 5, 20)  # seconds before attempt 1, 2, 3 (exponential-ish backoff)

        # Release any existing semaphore slot before re-acquiring (reconnect scenario)
        if self._semaphore_acquired:
            _IMAP_CONNECTION_SEMAPHORE.release()
            self._semaphore_acquired = False

        # Acquire semaphore BEFORE opening the connection — held until disconnect().
        # This caps concurrent open IMAP connections across all threads, preventing
        # Gmail's "Too many simultaneous connections" error.
        if not _IMAP_CONNECTION_SEMAPHORE.acquire(timeout=30):
            logger.warning("[FAIL] IMAP semaphore timeout — trop de connexions simultanées")
            return False
        self._semaphore_acquired = True

        for attempt in range(_MAX_ATTEMPTS):
            if _RETRY_DELAYS[attempt]:
                _time.sleep(_RETRY_DELAYS[attempt])

            try:
                # Connexion avec timeout direct (pas setdefaulttimeout qui est global et
                # crée une race condition avec Werkzeug : les sockets HTTP héritent du timeout)
                if self.use_ssl:
                    self._connection = imaplib.IMAP4_SSL(self.host, self.port, timeout=15)
                else:
                    logger.warning(
                        f"IMAP connection to {self.host}:{self.port} without TLS -- "
                        "credentials will be sent in plain text. "
                        "Set IMAP_USE_SSL=true for secure connections."
                    )
                    self._connection = imaplib.IMAP4(self.host, self.port, timeout=15)

                # Extend timeout to 60s for subsequent operations (Gmail virtual
                # folders like Trash/Spam can take 30-60s on first SELECT)
                if self._connection and hasattr(self._connection, 'socket'):
                    try:
                        self._connection.socket().settimeout(60)
                    except Exception:
                        pass

                # Authentification
                self._connection.login(self.username, self.password)
                self._authenticated = True
                self._selected_folder = None  # Force re-SELECT on next operation
                self._auth_time = _time.time()
                _register_imap_connection(self)  # register adapter (not raw conn) for lock-safe keepalive
                logger.info(f"[OK] Authentification IMAP réussie ({self.host})")
                return True

            except imaplib.IMAP4.error as e:
                err_str = str(e)
                is_transient = any(kw in err_str for kw in (
                    "Too many", "ALERT", "Connection", "Temporary",
                    "CANNOT", "PRIVACYREQUIRED", "UNAVAILABLE", "TRY AGAIN",
                ))
                if is_transient and attempt < _MAX_ATTEMPTS - 1:
                    logger.warning(f"[WARN] Auth IMAP transitoire (tentative {attempt + 1}/{_MAX_ATTEMPTS}): {e}")
                    continue
                if is_transient:
                    logger.warning(f"[FAIL] Authentification IMAP échouée (transitoire): {e}")
                else:
                    logger.error(f"[FAIL] Authentification IMAP échouée: {e}")
                self._authenticated = False
                _IMAP_CONNECTION_SEMAPHORE.release()
                self._semaphore_acquired = False
                return False

            except Exception as e:
                is_timeout = isinstance(e, (socket.timeout, TimeoutError, OSError))
                level = "Timeout" if is_timeout else "Erreur"
                if attempt < _MAX_ATTEMPTS - 1:
                    logger.warning(f"[WARN] {level} connexion IMAP (tentative {attempt + 1}/{_MAX_ATTEMPTS}): {e}")
                    continue
                logger.error(f"[FAIL] Erreur connexion IMAP: {e}")

        self._authenticated = False
        _IMAP_CONNECTION_SEMAPHORE.release()
        self._semaphore_acquired = False
        return False

    def _ensure_authenticated(self) -> None:
        """S'assure que la connexion est établie et active.

        NOTE: Must be called with self._connection_lock held by the caller.
        """
        if not self._authenticated or not self._connection:
            if not self.authenticate():
                raise RuntimeError("Authentification IMAP requise")
            return

        # Skip NOOP for fresh connections (saves ~10s on Gmail's rate-limited IMAP)
        if _time.time() - self._auth_time < 60:
            return

        # Vérifier que la connexion est encore vivante avec NOOP
        try:
            status, _ = self._connection.noop()
            if status != "OK":
                raise Exception("NOOP failed")
        except ssl.SSLError as e:
            # SSL error = connexion corrompue, reset immédiat sans LOGOUT
            logger.warning(f"SSL error during NOOP, force-resetting connection: {e}")
            self._reset_on_ssl_error()
            if not self.authenticate():
                raise RuntimeError("Reconnexion IMAP échouée après SSL error")
        except Exception:
            # Connexion morte, forcer ré-authentification
            logger.info("IMAP connection stale, reconnecting...")
            self._authenticated = False
            self._connection = None
            self._selected_folder = None  # Reset folder cache so SELECT is re-issued
            if not self.authenticate():
                raise RuntimeError("Reconnexion IMAP échouée")

    def _decode_header_value(self, value: str) -> str:
        """Décode un header email (peut être encodé en base64/quoted-printable)."""
        if not value:
            return ""

        decoded_parts = []
        for part, charset in decode_header(value):
            if isinstance(part, bytes):
                charset = charset or "utf-8"
                try:
                    decoded_parts.append(part.decode(charset, errors="replace"))
                except Exception:
                    decoded_parts.append(part.decode("utf-8", errors="replace"))
            else:
                decoded_parts.append(part)

        joined = " ".join(decoded_parts)
        # Audit 2026-05-18: when the sending MUA writes raw UTF-8 bytes into
        # a header field without RFC 2047 wrapping, `decode_header` hands the
        # whole value back as a plain string with the bytes already
        # mis-interpreted as Latin-1 ("Crypto UniversitÃ©" instead of
        # "Crypto Université"). Repair the round-trip before the value lands
        # in sender_name / subject.
        return self._demojibake(joined)

    def _parse_email_address(self, header_value: str) -> tuple:
        """Parse une adresse email avec nom optionnel."""
        from email.utils import parseaddr

        decoded = self._decode_header_value(header_value)
        name, addr = parseaddr(decoded)

        # parseaddr returns (name, addr) - may be empty strings
        if addr:
            return addr, name if name else None

        # Fallback: return decoded value as email
        return decoded, None

    def _get_body(self, msg: email.message.Message) -> tuple:
        """Extrait le corps text et HTML d'un message."""
        body_text = ""
        body_html = None
        cid_map = {}

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                # Collect inline images by Content-ID BEFORE checking disposition.
                # Some email clients (Outlook, certain MUAs) send signature images with
                # Content-Disposition: attachment even though they have a Content-ID —
                # they must be collected here or cid: references stay unresolved in body_html.
                content_id = part.get("Content-ID", "")
                if content_id and content_type.startswith("image/"):
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            cid_key = content_id.strip("<>")
                            b64_data = base64.b64encode(payload).decode("ascii")
                            cid_map[cid_key] = (content_type, b64_data)
                    except Exception:
                        pass
                    continue

                # Skip regular (non-CID) attachments — no text to extract
                if "attachment" in content_disposition:
                    continue

                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        text = payload.decode(charset, errors="replace")

                        if content_type == "text/plain" and not body_text:
                            body_text = text
                        elif content_type == "text/html" and not body_html:
                            body_html = text
                except Exception as e:
                    logger.warning(f"Failed to extract {content_type} part: {e}")
                    continue
        else:
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    text = payload.decode(charset, errors="replace")

                    if msg.get_content_type() == "text/html":
                        body_html = text
                        # Utilise le mixin pour extraction du texte
                        body_text = self._extract_text_from_html(text)
                    else:
                        body_text = text
            except Exception as e:
                logger.warning(f"Failed to decode email body: {e}")

        # Si on n'a que du HTML sans texte, extraire le texte du HTML
        if not body_text and body_html:
            body_text = self._extract_text_from_html(body_html)

        # Si le body_text ressemble à du CSS/HTML brut, re-extraire depuis le HTML
        if body_text and body_html and self._looks_like_css_or_html(body_text):
            body_text = self._extract_text_from_html(body_html)

        # Resolve inline CID images to base64 data URIs
        if body_html and cid_map:
            body_html = self._resolve_cid_images(body_html, cid_map)

        # BUG-Y003 fix: reverse Latin-1-as-UTF-8 mojibake on the body, same as
        # gmail_adapter._decode_body. Some IMAP servers send already-corrupted
        # bytes with a UTF-8 charset header, so the standard charset decode
        # leaves the mojibake in place.
        body_text = self._demojibake(body_text) or body_text
        if body_html:
            body_html = self._demojibake(body_html) or body_html

        if not body_html and body_text:
            logger.debug(f"Email has text body ({len(body_text)} chars) but no HTML body")

        return body_text.strip(), body_html

    def _has_attachments(self, msg: email.message.Message) -> bool:
        """Vérifie si le message a des pièces jointes."""
        if msg.is_multipart():
            for part in msg.walk():
                content_disposition = str(part.get("Content-Disposition", ""))
                if "attachment" in content_disposition:
                    return True
        return False

    def _extract_attachment_metadata(self, msg: email.message.Message) -> list:
        """Extrait les métadonnées des pièces jointes (exclut les images inline)."""
        result = []
        idx = 0
        if not msg.is_multipart():
            return result
        for part in msg.walk():
            content_disposition = str(part.get("Content-Disposition", ""))
            content_id = part.get("Content-ID", "")
            # Skip inline images (have Content-ID)
            if content_id:
                continue
            if "attachment" in content_disposition:
                raw_filename = part.get_filename() or "attachment"
                filename = self._decode_header_value(raw_filename)
                payload = part.get_payload(decode=True)
                result.append({
                    "id": str(idx),
                    "filename": filename,
                    "size": len(payload) if payload else 0,
                    "content_type": part.get_content_type() or "application/octet-stream",
                })
                idx += 1
        return result

    def download_attachment(self, msg_uid: str, part_idx: str) -> tuple:
        """Re-fetche le message IMAP et extrait la pièce jointe à l'index donné."""
        self._ensure_authenticated()

        # Try the same folders as get_message_by_id
        folders_to_try = [self.folder]
        _gk = (self.host, self.username)
        _cached_sent = _get_folder_cache(_SENT_FOLDER_GLOBAL_CACHE, _gk)
        if _cached_sent and _cached_sent not in folders_to_try:
            folders_to_try.append(_cached_sent)
        if self._sent_folder_name and self._sent_folder_name not in folders_to_try:
            folders_to_try.append(self._sent_folder_name)

        target_idx = int(part_idx)

        for folder_name in folders_to_try:
            try:
                status, _ = self._select_folder(folder_name)
                if status != "OK":
                    continue

                status, data = self._connection.uid('fetch', msg_uid.encode(), "(BODY.PEEK[])")
                if status != "OK" or not data or not data[0]:
                    continue
                if not isinstance(data[0], tuple) or len(data[0]) < 2:
                    continue

                raw_email = data[0][1]
                if not isinstance(raw_email, bytes):
                    continue

                msg = email.message_from_bytes(raw_email)
                current_idx = 0
                for part in msg.walk():
                    content_disposition = str(part.get("Content-Disposition", ""))
                    content_id = part.get("Content-ID", "")
                    if content_id:
                        continue
                    if "attachment" in content_disposition:
                        if current_idx == target_idx:
                            payload_bytes = part.get_payload(decode=True) or b""
                            raw_filename = part.get_filename() or "attachment"
                            filename = self._decode_header_value(raw_filename)
                            content_type = part.get_content_type() or "application/octet-stream"
                            return payload_bytes, content_type, filename
                        current_idx += 1
            except Exception as _e:
                logger.debug(f"IMAP download_attachment: folder {folder_name} failed: {_e}")
                continue

        raise ValueError(f"Attachment index {part_idx} not found for IMAP message {msg_uid}")

    def _map_to_standard_email(self, msg_id: str, msg: email.message.Message, header_info: bytes) -> StandardEmail:
        """Convertit un message email en StandardEmail."""
        # Expéditeur
        from_header = msg.get("From", "")
        sender_email, sender_name = self._parse_email_address(from_header)

        # Destinataires (utilise le mixin)
        to_list = self._normalize_recipients(msg.get("To", ""))
        cc_list = self._normalize_recipients(msg.get("Cc", ""))

        # Sujet
        subject = self._decode_header_value(msg.get("Subject", ""))

        # Corps
        body_text, body_html = self._get_body(msg)

        # Date (always timezone-aware to avoid comparison errors)
        received_at = None
        date_header = msg.get("Date")
        if date_header:
            try:
                from datetime import timezone
                received_at = parsedate_to_datetime(date_header)
                if received_at and received_at.tzinfo is None:
                    received_at = received_at.replace(tzinfo=timezone.utc)
            except Exception:
                pass

        # Statut lu/non lu (flag \Seen)
        # header_info format: b'123 (FLAGS (\\Seen \\Recent) RFC822 {size}'
        # Decode bytes to string and check for Seen flag
        is_read = False
        if header_info:
            try:
                header_str = header_info.decode('utf-8', errors='ignore') if isinstance(header_info, bytes) else str(header_info)
                # Check for \Seen flag in the FLAGS section
                is_read = '\\Seen' in header_str or 'FLAGS (\\Seen' in header_str
            except Exception:
                pass

        # Thread ID (Message-ID ou In-Reply-To)
        message_id_header = msg.get("Message-ID", "")
        thread_id = msg.get("In-Reply-To") or msg.get("References") or message_id_header

        attachments = self._extract_attachment_metadata(msg)

        # Extract raw iCal text from text/calendar MIME parts (not in body_text/body_html).
        # For Teams/Google Meet invites the .ics content is a separate MIME part.
        ical_text = None
        if msg.is_multipart():
            for _part in msg.walk():
                _ct = _part.get_content_type() or ""
                _fn = (_part.get_filename() or "").lower()
                if "calendar" in _ct or _fn.endswith(".ics"):
                    try:
                        _payload = _part.get_payload(decode=True)
                        if _payload:
                            _decoded = _payload.decode(_part.get_content_charset() or "utf-8", errors="replace")
                            if "BEGIN:VCALENDAR" in _decoded.upper():
                                ical_text = _decoded
                                break
                    except Exception:
                        pass

        # Extract classification headers for labeling pipeline
        _CLASSIFICATION_HEADER_NAMES = (
            "List-Unsubscribe", "Precedence", "Auto-Submitted",
            "X-Auto-Response-Suppress", "X-Mailer", "Reply-To",
        )
        classification_headers = {}
        for _hdr_name in _CLASSIFICATION_HEADER_NAMES:
            _hdr_val = msg.get(_hdr_name)
            if _hdr_val:
                classification_headers[_hdr_name.lower()] = _hdr_val

        return StandardEmail(
            id=msg_id,
            sender=sender_email,
            sender_name=sender_name,
            to=to_list,
            cc=cc_list,
            subject=subject,
            body=body_text,
            body_html=body_html,
            received_at=received_at,
            is_read=is_read,
            has_attachments=bool(attachments) or self._has_attachments(msg),
            attachments=attachments,
            ical_text=ical_text,
            conversation_id=thread_id,
            provider_source=self.PROVIDER_NAME,
            raw_metadata={
                "flags": header_info.decode('utf-8', errors='ignore') if isinstance(header_info, bytes) else str(header_info),
                "message_id": message_id_header,
                "classification_headers": classification_headers,
            }
        )

    def get_messages(self, limit: int = 50, unread_only: bool = False, folder: Optional[str] = None, **kwargs) -> List[StandardEmail]:
        """
        Récupère les messages de la boîte de réception.

        Args:
            limit: Nombre maximum de messages à récupérer.
            unread_only: Si True, ne récupère que les messages non lus.
            folder: IMAP folder to fetch from (uses self.folder if not specified).

        Returns:
            Liste de StandardEmail triés par date (plus récents en premier).
        """
        with self._connection_lock:
            self._ensure_authenticated()

            try:
                # Sélectionner le dossier
                target_folder = folder or self.folder
                self._select_folder(target_folder)

                # Rechercher les messages par UID (stables, contrairement aux sequence numbers)
                search_criteria = "UNSEEN" if unread_only else "ALL"
                status, message_ids = self._connection.uid('search', None, search_criteria)

                if status != "OK":
                    logger.error("Erreur recherche IMAP")
                    return []

                ids = message_ids[0].split()

                if not ids:
                    return []

                # Prendre les N derniers UIDs (les plus récents dans IMAP)
                recent_ids = ids[-limit:] if len(ids) > limit else ids

                # Fetch all messages in a single batch request (much faster than one by one)
                id_range = b','.join(recent_ids)
                status, all_data = self._connection.uid('fetch', id_range, "(FLAGS BODY.PEEK[])")

                if status != "OK":
                    logger.error("Erreur fetch batch IMAP")
                    return []

                emails = []
                # Parse the batch response
                # Gmail IMAP returns FLAGS in a SEPARATE item after each tuple:
                # - Item 0: tuple (b'MSG_ID (RFC822 {size}', raw_email_bytes)
                # - Item 1: bytes b' FLAGS (\\Seen))'
                # - Item 2: tuple (next message)
                # - Item 3: bytes (next flags)
                # ...
                i = 0
                while i < len(all_data):
                    item = all_data[i]
                    if not isinstance(item, tuple) or len(item) < 2:
                        i += 1
                        continue

                    header_info = item[0]
                    raw_email = item[1]

                    if not isinstance(raw_email, bytes):
                        i += 1
                        continue

                    # Check if next item contains FLAGS
                    flags_data = b''
                    if i + 1 < len(all_data) and isinstance(all_data[i + 1], bytes):
                        flags_data = all_data[i + 1]
                        i += 1  # Skip the flags item

                    # Combine header_info with flags_data for is_read detection
                    combined_info = header_info + flags_data

                    # Extract UID from the header info
                    # UID fetch format: b'123 (UID 456 FLAGS ... BODY[] ...'
                    try:
                        header_decoded = header_info.decode('utf-8', errors='ignore')
                        uid_match = re.search(r'UID\s+(\d+)', header_decoded)
                        if uid_match:
                            msg_id_str = uid_match.group(1)
                        else:
                            # Fallback: use sequence number
                            msg_id_str = header_info.split(b' ')[0].decode()
                    except (IndexError, AttributeError):
                        i += 1
                        continue

                    msg = email.message_from_bytes(raw_email)
                    emails.append(self._map_to_standard_email(msg_id_str, msg, combined_info))
                    i += 1

                # Trier par date décroissante (plus récents en premier)
                emails.sort(key=lambda e: e.received_at.isoformat() if e.received_at else "", reverse=True)

                return emails

            except Exception as e:
                logger.warning(f"Erreur récupération emails IMAP: {e}")
                return []

    def get_unread_messages(self, limit: int = 10) -> List[StandardEmail]:
        """Récupère les messages non lus."""
        return self.get_messages(limit=limit, unread_only=True)

    def get_message_headers(self, limit: int = 50, unread_only: bool = False, folder: Optional[str] = None) -> List[StandardEmail]:
        """
        Fetch email headers only (no body content).

        Significantly faster than get_messages() for inbox list rendering.
        Uses ENVELOPE and BODY.PEEK[HEADER] instead of RFC822.

        Args:
            limit: Maximum number of messages to fetch.
            unread_only: If True, only fetch unread messages.
            folder: IMAP folder to fetch from (uses self.folder if not specified).

        Returns:
            List of StandardEmail with headers populated (body will be empty).
        """
        with self._connection_lock:
            self._ensure_authenticated()

            target_folder = folder or self.folder
            is_archive_folder = target_folder in ("[Gmail]/All Mail", "[Gmail]/Tous les messages")
            try:
                select_status, _ = self._select_folder(target_folder)
                if select_status != "OK":
                    # Try auto-detecting localized folder name via IMAP flags
                    _resolved = self._resolve_localized_folder(target_folder)
                    if _resolved:
                        target_folder = _resolved
                        select_status, _ = self._select_folder(target_folder)
                    if select_status != "OK":
                        logger.error(f"[FAIL] SELECT '{target_folder}' échoué (status={select_status}) — SEARCH annulé")
                        return []

                # Search for messages by UID
                # For Gmail's All Mail folder, filter out inbox/sent/spam/trash to get only archived
                is_gmail = "gmail" in (self.host or "").lower()
                if is_archive_folder and is_gmail:
                    # Gmail IMAP: archivé = dans All Mail, hors Inbox/Sent/Spam/Trash
                    # Note: "\\Inbox" Python = "\Inbox" envoyé au serveur (label Gmail)
                    # SINCE filter limits scan to last 6 months — avoids scanning entire mailbox
                    from datetime import datetime as _dt, timedelta as _td
                    _since = (_dt.now() - _td(days=180)).strftime("%d-%b-%Y")
                    _base = f'SINCE {_since} NOT X-GM-LABELS "\\Inbox" NOT X-GM-LABELS "\\Sent" NOT X-GM-LABELS "\\Spam" NOT X-GM-LABELS "\\Trash"'
                    _q = f'UNSEEN {_base}' if unread_only else _base
                    status, message_ids = self._connection.uid('search', None, _q)
                elif unread_only:
                    status, message_ids = self._connection.uid('search', None, 'UNSEEN')
                else:
                    status, message_ids = self._connection.uid('search', None, 'ALL')

                if status != "OK":
                    logger.error("IMAP search error")
                    return []

                ids = message_ids[0].split()
                if not ids:
                    return []

                # Take the N most recent UIDs
                recent_ids = ids[-limit:] if len(ids) > limit else ids

                # Fetch only headers by UID
                id_range = b','.join(recent_ids)
                status, all_data = self._connection.uid('fetch',
                    id_range,
                    "(UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES CONTENT-TYPE)])"
                )

                if status != "OK":
                    logger.error("IMAP header fetch error")
                    return []

                # Second pass: BODYSTRUCTURE pour détecter les PJ sans télécharger le corps
                # BODYSTRUCTURE inclut Content-Disposition des parties → fiable, sans faux positifs
                bs_lookup: dict = {}
                try:
                    status_bs, bs_data = self._connection.uid('fetch', id_range, "(UID BODYSTRUCTURE)")
                    if status_bs == "OK" and bs_data:
                        for bs_item in bs_data:
                            if isinstance(bs_item, bytes):
                                bs_str = bs_item.decode('utf-8', errors='ignore')
                                uid_m = re.search(r'UID\s+(\d+)', bs_str)
                                if uid_m:
                                    # '"attachment"' dans BODYSTRUCTURE = Content-Disposition: attachment sur une partie
                                    bs_lookup[uid_m.group(1)] = '"attachment"' in bs_str.lower()
                except Exception as _bs_err:
                    logger.debug(f"BODYSTRUCTURE fetch ignoré (non-critique): {_bs_err}")

                emails = []
                for item in all_data:
                    if not isinstance(item, tuple) or len(item) < 2:
                        continue

                    header_info = item[0]
                    header_bytes = item[1]

                    if not isinstance(header_bytes, bytes):
                        continue

                    # Extract UID from header info
                    try:
                        header_decoded = header_info.decode('utf-8', errors='ignore')
                        uid_match = re.search(r'UID\s+(\d+)', header_decoded)
                        if uid_match:
                            msg_id_str = uid_match.group(1)
                        else:
                            msg_id_str = header_info.split(b' ')[0].decode()
                    except (IndexError, AttributeError):
                        continue

                    # Parse headers
                    try:
                        headers = email.message_from_bytes(header_bytes)

                        # Extract and decode header values
                        subject = self._decode_header_value(headers.get("Subject", ""))
                        from_header = headers.get("From", "")
                        sender_email, sender_name = self._parse_email_address(from_header)
                        date_str = headers.get("Date", "")
                        message_id = headers.get("Message-ID", "")

                        # Thread ID — same logic as _message_to_standard_email (full-email path)
                        _in_reply_to = headers.get("In-Reply-To", "").strip()
                        _references = headers.get("References", "").strip()
                        thread_id = _in_reply_to or _references or message_id or None

                        # Parse date
                        received_at = None
                        if date_str:
                            try:
                                from datetime import timezone
                                received_at = parsedate_to_datetime(date_str)
                                if received_at and received_at.tzinfo is None:
                                    received_at = received_at.replace(tzinfo=timezone.utc)
                            except (ValueError, TypeError):
                                pass

                        # Check read status from FLAGS
                        is_read = b"\\Seen" in header_info

                        # Create StandardEmail with header data only (no body)
                        std_email = StandardEmail(
                            id=msg_id_str,
                            subject=subject or "(No Subject)",
                            sender=sender_email or from_header,
                            sender_name=sender_name,
                            body="",  # Empty body for header-only fetch
                            body_html=None,
                            received_at=received_at,
                            is_read=is_read,
                            has_attachments=bs_lookup.get(msg_id_str, False),
                            conversation_id=thread_id,
                            provider_source=self.PROVIDER_NAME,
                            raw_metadata={
                                "message_id": message_id,
                                "header_only": True,
                            }
                        )
                        emails.append(std_email)

                    except Exception as e:
                        logger.warning(f"Error parsing header for message {msg_id_str}: {e}")
                        continue

                # Sort by date descending (most recent first)
                emails.sort(key=lambda e: e.received_at.isoformat() if e.received_at else "", reverse=True)

                logger.info(f"IMAP header-only fetch: {len(emails)} emails")
                return emails

            except Exception as e:
                logger.error(f"IMAP header fetch error: {e}")
                return []

    def _parse_address(self, address: str) -> tuple:
        """
        Parse an email address header into name and email parts.

        Args:
            address: Email address header (e.g., "John Doe <john@example.com>")

        Returns:
            Tuple of (name, email) where name may be empty.
        """
        import re

        if not address:
            return ("", "")

        # Match "Name <email>" pattern
        match = re.match(r'^"?([^"<]*)"?\s*<?([^>]+)>?$', address.strip())
        if match:
            name = match.group(1).strip()
            email_addr = match.group(2).strip()
            return (name, email_addr)

        # Just an email address
        return ("", address.strip())

    def _build_imap_criteria(self, query: str) -> list[str]:
        """Parse une query de recherche et retourne une liste de critères IMAP SEARCH.

        Critères supportés :
        - from:x@y.com → 'FROM "x@y.com"'
        - to:x@y.com   → 'TO "x@y.com"'
        - subject:mot  → 'SUBJECT "mot"'
        - body:mot / contenu:mot → 'TEXT "mot"'
        - texte libre  → 'TEXT "mot"' pour chaque mot

        Retourne [] si aucun critère exploitable.
        """
        import re
        criteria = []
        remaining_words = []

        for token in query.split():
            lower = token.lower()
            if lower.startswith('from:'):
                val = token[5:].strip('"')
                if val:
                    criteria.append(f'FROM "{val}"')
            elif lower.startswith('to:'):
                val = token[3:].strip('"')
                if val:
                    criteria.append(f'TO "{val}"')
            elif lower.startswith('subject:') or lower.startswith('objet:'):
                sep = ':'
                val = token[token.index(sep) + 1:].strip('"')
                if val:
                    criteria.append(f'SUBJECT "{val}"')
            elif lower.startswith('body:') or lower.startswith('contenu:'):
                sep = ':'
                val = token[token.index(sep) + 1:].strip('"')
                if val:
                    criteria.append(f'TEXT "{val}"')
            elif lower.startswith('after:') or lower.startswith('before:'):
                # Skip date filters — not supported in basic IMAP SEARCH here
                pass
            elif lower.startswith('label:') or lower.startswith('is:'):
                pass
            elif lower in ('has:attachment', 'has:attachments'):
                # Gmail: extension X-GM-RAW pour recherche PJ côté serveur
                if "gmail" in (self.host or "").lower() or "googlemail" in (self.host or "").lower():
                    criteria.append('X-GM-RAW "has:attachment"')
                # IMAP générique: pas de critère standard — le cache SQLite (BODYSTRUCTURE) prend le relais
            elif lower.startswith('has:'):
                pass  # autres opérateurs has: non supportés côté IMAP
            elif re.match(r'^[\w\.-]+@[\w\.-]+$', token):
                # Bare email address → FROM or TO
                criteria.append(f'FROM "{token}"')
                criteria.append(f'TO "{token}"')
            else:
                remaining_words.append(token)

        # Texte libre : critère TEXT par mot
        for word in remaining_words:
            if len(word) >= 2:
                criteria.append(f'TEXT "{word}"')

        return criteria

    def _search_in_folder_advanced(self, folder_name: str, criteria: list[str]) -> list:
        """Exécute chaque critère IMAP SEARCH et fusionne les UIDs (union)."""
        try:
            status, _ = self._select_folder(folder_name)
            if status != "OK":
                return []
        except Exception:
            return []

        all_ids: set[bytes] = set()
        for criterion in criteria:
            try:
                status, result = self._connection.uid('search', None, criterion)
                if status == "OK" and result[0]:
                    all_ids.update(result[0].split())
            except Exception:
                pass

        return [(folder_name, mid) for mid in all_ids]

    def _search_in_folder(self, folder_name: str, email_addr: str) -> list:
        """Search FROM/TO an address in a specific IMAP folder. Returns raw msg ids."""
        try:
            status, _ = self._select_folder(folder_name)
            if status != "OK":
                return []
        except Exception:
            return []

        ids = []
        try:
            status, from_ids = self._connection.uid('search', None, f'FROM "{email_addr}"')
            if status == "OK" and from_ids[0]:
                ids.extend(from_ids[0].split())
        except Exception:
            pass

        try:
            status, to_ids = self._connection.uid('search', None, f'TO "{email_addr}"')
            if status == "OK" and to_ids[0]:
                ids.extend(to_ids[0].split())
        except Exception:
            pass

        return [(folder_name, mid) for mid in ids]

    def search_emails(self, query: str, limit: int = 20) -> List[StandardEmail]:
        """
        Recherche des emails avec une requête dans tous les dossiers principaux
        (Inbox, Sent, Archive, Trash).

        Pour IMAP, on extrait l'adresse email de la requête et on utilise
        les critères FROM/TO pour la recherche.

        Args:
            query: Requête de recherche (ex: "from:user@example.com OR to:user@example.com")
            limit: Nombre maximum de résultats

        Returns:
            Liste des emails correspondant à la recherche.
        """
        self._ensure_authenticated()

        try:
            # Construire les critères IMAP depuis la query
            criteria = self._build_imap_criteria(query)

            # Fallback legacy : si aucun critère IMAP, tenter extraction email brute
            if not criteria:
                import re
                email_match = re.search(r'[\w\.-]+@[\w\.-]+', query)
                if email_match:
                    email_addr = email_match.group()
                    criteria = [f'FROM "{email_addr}"', f'TO "{email_addr}"']
                else:
                    logger.warning(f"IMAP: aucun critère de recherche pour: {query}")
                    return []

            # Dossiers à chercher (inbox + sent + trash) — resolved via IMAP flags
            folders_to_search = [self.folder]  # INBOX
            sent = self._sent_folder_name or _get_folder_cache(_SENT_FOLDER_GLOBAL_CACHE, (self.host, self.username))
            if not sent:
                self._select_sent_folder()
                sent = self._sent_folder_name
            if sent:
                folders_to_search.append(sent)
            trash = self._select_trash_folder()
            if trash:
                folders_to_search.append(trash)

            # Chercher dans chaque dossier avec les critères avancés
            all_folder_ids = []
            searched_folders = set()
            for folder_name in folders_to_search:
                if folder_name in searched_folders:
                    continue
                searched_folders.add(folder_name)
                results = self._search_in_folder_advanced(folder_name, criteria)
                if results:
                    all_folder_ids.extend(results)
                    logger.debug(f"Found {len(results)} matches in {folder_name}")

            if not all_folder_ids:
                logger.info(f"IMAP search for '{email_addr}' returned 0 emails across all folders")
                return []

            # Dédupliquer par message-id (même email peut être dans plusieurs dossiers)
            # On garde la première occurrence (préférence: inbox > sent > archive > trash)
            seen_ids = set()
            unique_folder_ids = []
            for folder_name, msg_id in all_folder_ids:
                key = (folder_name, msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id))
                if key not in seen_ids:
                    seen_ids.add(key)
                    unique_folder_ids.append((folder_name, msg_id))

            # Limiter avant de fetch (performance)
            recent = unique_folder_ids[-limit * 2:] if len(unique_folder_ids) > limit * 2 else unique_folder_ids

            emails = []
            for folder_name, msg_id in recent:
                try:
                    self._select_folder(folder_name)
                    status, data = self._connection.uid('fetch', msg_id, "(FLAGS BODY.PEEK[])")
                    if status != "OK" or not data or not data[0]:
                        continue

                    flags = data[0][0] if isinstance(data[0], tuple) else b""
                    raw_email = data[0][1] if isinstance(data[0], tuple) else data[0]
                    msg = email.message_from_bytes(raw_email)

                    parsed = self._map_to_standard_email(
                        msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id),
                        msg,
                        flags
                    )
                    # Dédupliquer par subject + sender + date (cross-folder duplicates)
                    dedup_key = f"{parsed.subject}|{parsed.sender}|{parsed.received_at}"
                    if dedup_key not in seen_ids:
                        seen_ids.add(dedup_key)
                        emails.append(parsed)
                except Exception as e:
                    logger.warning(f"Could not fetch message {msg_id} from {folder_name}: {e}")
                    continue

            # Trier par date décroissante et limiter
            emails.sort(key=lambda e: e.received_at.isoformat() if e.received_at else "", reverse=True)
            emails = emails[:limit]

            logger.info(f"IMAP search for '{email_addr}' returned {len(emails)} emails across {len(searched_folders)} folders")

            # Remettre le dossier principal sélectionné
            try:
                self._select_folder(self.folder)
            except Exception:
                pass

            return emails

        except Exception as e:
            logger.error(f"IMAP search error: {e}")
            # Remettre le dossier principal sélectionné
            try:
                self._select_folder(self.folder)
            except Exception:
                pass
            return []

    def search_subscription_emails(self, limit: int = 200) -> List[StandardEmail]:
        """
        Search for subscription/billing related emails via IMAP.

        Uses IMAP SUBJECT search for common subscription keywords.
        Extracts List-Unsubscribe header from each message.

        Args:
            limit: Maximum number of emails to scan.

        Returns:
            List of StandardEmail with list_unsubscribe in raw_metadata.
        """
        self._ensure_authenticated()

        try:
            # IMAP OR searches for subscription keywords
            search_criteria = (
                '(OR OR OR OR OR OR OR OR OR OR OR '
                'SUBJECT "receipt" '
                'SUBJECT "invoice" '
                'SUBJECT "payment" '
                'SUBJECT "subscription" '
                'SUBJECT "billing" '
                'SUBJECT "order" '
                'SUBJECT "shipping" '
                'SUBJECT "confirmation" '
                'SUBJECT "reçu" '
                'SUBJECT "facture" '
                'SUBJECT "commande" '
                'SUBJECT "livraison")'
            )

            # Search inbox + spam/junk folders
            folders_to_search = [self.folder]
            spam_folders = (
                ["[Gmail]/Spam", "Spam", "Junk"]
                if "gmail" in (self.host or "").lower()
                else ["Spam", "Junk", "INBOX.Spam", "[Gmail]/Spam"]
            )
            for sf in spam_folders:
                try:
                    self._select_folder(sf)
                    folders_to_search.append(sf)
                    break  # Found a valid spam folder
                except Exception:
                    continue

            all_msg_ids = []  # list of (folder, msg_id) tuples
            for folder in folders_to_search:
                try:
                    self._select_folder(folder)
                    status, msg_ids = self._connection.uid('search', None, search_criteria)
                    if status == "OK" and msg_ids[0]:
                        for mid in msg_ids[0].split():
                            all_msg_ids.append((folder, mid))
                except Exception:
                    continue

            # Take only the most recent ones
            recent = all_msg_ids[-limit:] if len(all_msg_ids) > limit else all_msg_ids

            emails = []
            current_folder = None
            for folder, msg_id in recent:
                if folder != current_folder:
                    self._select_folder(folder)
                    current_folder = folder
                try:
                    # Fetch headers only (including List-Unsubscribe)
                    status, data = self._connection.uid('fetch',
                        msg_id,
                        "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE LIST-UNSUBSCRIBE LIST-UNSUBSCRIBE-POST)])"
                    )
                    if status != "OK" or not data or not data[0]:
                        continue

                    raw_header = data[0][1] if isinstance(data[0], tuple) else data[0]
                    msg = email.message_from_bytes(raw_header)

                    from_header = msg.get("From", "")
                    sender_email, sender_name = self._parse_email_address(from_header)

                    subject = self._decode_header_value(msg.get("Subject", ""))

                    received_at = None
                    date_header = msg.get("Date")
                    if date_header:
                        try:
                            received_at = parsedate_to_datetime(date_header)
                        except Exception:
                            pass

                    list_unsub = msg.get("List-Unsubscribe", "")
                    list_unsub_post = msg.get("List-Unsubscribe-Post", "")

                    msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)

                    emails.append(StandardEmail(
                        id=msg_id_str,
                        subject=subject,
                        sender=sender_email,
                        sender_name=sender_name,
                        body="",
                        body_html=None,
                        received_at=received_at,
                        is_read=True,
                        has_attachments=False,
                        conversation_id=None,
                        provider_source=self.PROVIDER_NAME,
                        raw_metadata={
                            "list_unsubscribe": list_unsub,
                            "list_unsubscribe_post": list_unsub_post,
                            "header_only": True,
                        },
                    ))
                except Exception as e:
                    logger.warning(f"Could not fetch subscription email {msg_id}: {e}")
                    continue

            logger.info(f"IMAP found {len(emails)} subscription-related emails")
            return emails

        except Exception as e:
            logger.error(f"IMAP subscription search error: {e}")
            return []

    def search_newsletter_emails(self, limit: int = 300) -> List[StandardEmail]:
        """
        Search for newsletter emails via IMAP.

        Strategy: fetch the most recent emails and keep only those
        with a List-Unsubscribe header (the defining trait of newsletters).
        We scan a larger pool (up to 3x limit) because most emails
        won't have the header.

        Args:
            limit: Maximum number of newsletter emails to return.

        Returns:
            List of StandardEmail with list_unsubscribe in raw_metadata.
        """
        self._ensure_authenticated()

        try:
            self._select_folder(self.folder)

            # Fetch ALL recent emails (not keyword-filtered) to find List-Unsubscribe headers
            status, msg_ids = self._connection.uid('search', None, "ALL")
            if status != "OK" or not msg_ids[0]:
                return []

            all_ids = msg_ids[0].split()
            # Scan up to 3x the limit to find enough newsletters
            scan_limit = min(len(all_ids), limit * 3)
            recent_ids = all_ids[-scan_limit:]

            emails = []
            for msg_id in recent_ids:
                try:
                    status, data = self._connection.uid('fetch',
                        msg_id,
                        "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE LIST-UNSUBSCRIBE LIST-UNSUBSCRIBE-POST)])"
                    )
                    if status != "OK" or not data or not data[0]:
                        continue

                    raw_header = data[0][1] if isinstance(data[0], tuple) else data[0]
                    msg = email.message_from_bytes(raw_header)

                    list_unsub = msg.get("List-Unsubscribe", "")
                    # Only keep emails that actually have List-Unsubscribe
                    if not list_unsub:
                        continue

                    from_header = msg.get("From", "")
                    sender_email, sender_name = self._parse_email_address(from_header)

                    subject = self._decode_header_value(msg.get("Subject", ""))

                    received_at = None
                    date_header = msg.get("Date")
                    if date_header:
                        try:
                            received_at = parsedate_to_datetime(date_header)
                        except Exception:
                            pass

                    list_unsub_post = msg.get("List-Unsubscribe-Post", "")
                    msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)

                    emails.append(StandardEmail(
                        id=msg_id_str,
                        subject=subject,
                        sender=sender_email,
                        sender_name=sender_name,
                        body="",
                        body_html=None,
                        received_at=received_at,
                        is_read=True,
                        has_attachments=False,
                        conversation_id=None,
                        provider_source=self.PROVIDER_NAME,
                        raw_metadata={
                            "list_unsubscribe": list_unsub,
                            "list_unsubscribe_post": list_unsub_post,
                            "header_only": True,
                        },
                    ))
                except Exception as e:
                    logger.warning(f"Could not fetch newsletter email {msg_id}: {e}")
                    continue

            logger.info(f"IMAP found {len(emails)} newsletter emails")
            return emails

        except Exception as e:
            logger.error(f"IMAP newsletter search error: {e}")
            return []

    def get_message_by_id(self, message_id: str, folder: Optional[str] = None) -> Optional[StandardEmail]:
        """Récupère un message par son ID.

        Args:
            message_id: UID IMAP du message.
            folder: Dossier IMAP spécifique (None = essayer INBOX puis Sent).
        """
        self._ensure_authenticated()

        # Build list of folders to try
        if folder:
            folders_to_try = [folder]
        else:
            folders_to_try = [self.folder]
            # Also try Sent folders as fallback (UIDs are folder-specific in IMAP)
            _gk = (self.host, self.username)
            _cached_sent = _get_folder_cache(_SENT_FOLDER_GLOBAL_CACHE, _gk)
            if _cached_sent and _cached_sent not in folders_to_try:
                folders_to_try.append(_cached_sent)
            elif not _cached_sent:
                # Detect sent folder via \Sent IMAP flag (handles all locales)
                _detected_count = self._select_sent_folder()
                if self._sent_folder_name and self._sent_folder_name not in folders_to_try:
                    folders_to_try.append(self._sent_folder_name)
                else:
                    # Fallback to hardcoded names if detection failed
                    is_gmail = "gmail" in (self.host or "").lower()
                    if is_gmail:
                        sent_folders = ["[Gmail]/Sent Mail", "Sent"]
                    else:
                        sent_folders = ["Sent", "Sent Items", "INBOX.Sent", "[Gmail]/Sent Mail"]
                    folders_to_try.extend(sent_folders)

        for folder_name in folders_to_try:
            try:
                status, _ = self._select_folder(folder_name)
                if status != "OK":
                    continue

                status, data = self._connection.uid('fetch', message_id.encode(), "(FLAGS BODY.PEEK[])")

                if status != "OK" or not data or not data[0]:
                    continue

                if not isinstance(data[0], tuple) or len(data[0]) < 2:
                    continue

                flags = data[0][0]
                raw_email = data[0][1]

                if not isinstance(raw_email, bytes):
                    continue

                msg = email.message_from_bytes(raw_email)
                result = self._map_to_standard_email(message_id, msg, flags)
                _set_folder_cache(_SENT_FOLDER_GLOBAL_CACHE, (self.host, self.username), folder_name)
                return result

            except Exception as e:
                logger.debug(f"Could not fetch message {message_id} from folder {folder_name}: {e}")
                continue

        logger.warning(f"Message IMAP {message_id} not found in any folder")
        return None

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
        Crée un brouillon dans le dossier Drafts.

        Note: IMAP ne supporte pas nativement les brouillons.
        Cette méthode sauvegarde le message dans le dossier Drafts.
        """
        self._ensure_authenticated()

        try:
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            from email.mime.base import MIMEBase
            from email import encoders
            import time

            # Créer le message
            if attachments:
                msg = MIMEMultipart("mixed")
                msg.attach(MIMEText(body, "html" if is_html else "plain"))
                for filename, file_data, content_type in attachments:
                    part = MIMEBase(*content_type.split("/", 1)) if "/" in content_type else MIMEBase("application", "octet-stream")
                    part.set_payload(file_data)
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", "attachment", filename=filename)
                    msg.attach(part)
            elif is_html:
                msg = MIMEMultipart("alternative")
                msg.attach(MIMEText(body, "html"))
            else:
                msg = MIMEText(body)

            msg["To"] = ", ".join(to)
            msg["Subject"] = subject
            if from_name:
                from email.utils import formataddr
                msg["From"] = formataddr((from_name, self.username))
            else:
                msg["From"] = self.username

            if cc:
                msg["Cc"] = ", ".join(cc)

            if bcc:
                msg["Bcc"] = ", ".join(bcc)

            # Headers pour reply
            if reply_to_id:
                original = self.get_message_by_id(reply_to_id)
                if original and original.raw_metadata.get("message_id"):
                    msg["In-Reply-To"] = original.raw_metadata["message_id"]
                    msg["References"] = original.raw_metadata["message_id"]

            # Sauvegarder dans Drafts
            draft_folder = self._select_drafts_folder() or "Drafts"

            # Append le message
            result = self._connection.append(
                draft_folder,
                "\\Draft",
                imaplib.Time2Internaldate(time.time()),
                msg.as_bytes()
            )

            if result[0] == "OK":
                # Extraire l'UID du résultat
                import re
                match = re.search(r'\[APPENDUID \d+ (\d+)\]', str(result[1]))
                draft_id = match.group(1) if match else f"draft-{int(time.time())}"
                return draft_id

            return None

        except Exception as e:
            logger.error(f"Erreur création brouillon IMAP: {e}")
            return None

    def send_draft(self, draft_id: str) -> bool:
        """
        IMAP ne peut pas envoyer d'emails directement.
        Cette méthode retourne False - utilisez SMTPAdapter pour l'envoi.
        """
        logger.warning("IMAP ne peut pas envoyer d'emails. Utilisez SMTPAdapter.")
        return False

    def mark_as_read(self, message_id: str) -> bool:
        """Marque un message comme lu (par UID)."""
        self._ensure_authenticated()

        try:
            self._select_folder(self.folder)
            result = self._connection.uid('store', message_id.encode(), "+FLAGS", "\\Seen")
            return result[0] == "OK"

        except ssl.SSLError as e:
            logger.warning(f"SSL error in mark_as_read, resetting connection: {e}")
            self._reset_on_ssl_error()
            return False
        except Exception as e:
            logger.error(f"Erreur marquage lu IMAP: {e}")
            return False

    def mark_as_unread(self, message_id: str) -> bool:
        """Marque un message comme non lu (par UID)."""
        self._ensure_authenticated()

        try:
            self._select_folder(self.folder)
            result = self._connection.uid('store', message_id.encode(), "-FLAGS", "\\Seen")
            return result[0] == "OK"

        except ssl.SSLError as e:
            logger.warning(f"SSL error in mark_as_unread, resetting connection: {e}")
            self._reset_on_ssl_error()
            return False
        except Exception as e:
            logger.error(f"Erreur marquage non lu IMAP: {e}")
            return False

    def archive_email(self, message_id: str) -> bool:
        """
        Archive un email.

        Gmail IMAP: supprime de INBOX (retire le label INBOX = archivage dans All Mail).
        IMAP standard: COPY vers le dossier Archive, puis DELETE de l'original.
        """
        with self._connection_lock:
            self._ensure_authenticated()

            try:
                is_gmail = "gmail" in (self.host or "").lower()

                if is_gmail:
                    # Gmail IMAP: expunge de INBOX = retirer le label INBOX = archiver dans All Mail
                    self._select_folder(self.folder)
                    result = self._connection.uid('store', str(message_id), "+FLAGS", "\\Deleted")
                    if result[0] == "OK":
                        self._connection.expunge()
                        logger.info(f"Email UID {message_id} archivé (Gmail)")
                        return True
                    # UID introuvable = déjà archivé/supprimé → succès
                    logger.debug(f"Email UID {message_id} introuvable lors de l'archivage — déjà traité")
                    return True

                # IMAP standard: COPY vers dossier Archive, puis DELETE de l'original
                archive_folder = self._select_archive_folder()
                if not archive_folder:
                    logger.warning(
                        f"Dossier Archive introuvable — archivage impossible pour UID {message_id}"
                    )
                    return False

                # Re-sélectionner le dossier source (_select_archive_folder a changé la sélection)
                self._select_folder(self.folder)
                result = self._connection.uid('copy', str(message_id).encode(), archive_folder)
                if result[0] != "OK":
                    logger.warning(f"IMAP COPY to Archive failed for UID {message_id}: {result}")
                    return False

                self._connection.uid('store', str(message_id), "+FLAGS", "\\Deleted")
                self._connection.expunge()
                logger.info(f"Email UID {message_id} archivé vers {archive_folder}")
                return True

            except ssl.SSLError as e:
                logger.warning(f"SSL error in archive_email, resetting connection: {e}")
                self._reset_on_ssl_error()
                return False
            except Exception as e:
                logger.error(f"Erreur archivage IMAP: {e}")
                return False

    def delete_email(self, message_id: str) -> bool:
        """
        Supprime un email en le déplaçant vers la corbeille.

        Gmail IMAP: COPY vers [Gmail]/Trash puis DELETE de l'original.
        Standard IMAP: \\Deleted + expunge (serveur gère le trash).
        """
        # IMAP UIDs must be numeric — skip non-numeric IDs immediately (e.g. Gmail API hex IDs)
        if not str(message_id).strip().isdigit():
            logger.debug(f"[DELETE] ID non-numérique ignoré pour IMAP: {message_id}")
            return False

        with self._connection_lock:
            self._ensure_authenticated()

            try:
                self._select_folder(self.folder)

                is_gmail = "gmail" in (self.host or "").lower()
                if is_gmail:
                    # Gmail: COPY to Trash (auto-detected name), then delete from current folder
                    trash_folder = self._select_trash_folder()
                    if not trash_folder:
                        logger.error("Cannot find Trash folder for Gmail IMAP")
                        return False
                    # Re-select INBOX (select_trash_folder changed selection)
                    self._select_folder(self.folder)
                    result = self._connection.uid('copy', str(message_id).encode(), trash_folder)
                    logger.info(f"[DELETE] Gmail COPY UID {message_id} to {trash_folder}: {result[0]}")
                    if result[0] != "OK":
                        logger.warning(f"IMAP COPY to Trash failed for UID {message_id}: {result}")
                        return False
                    # Remove from current folder
                    self._connection.uid('store', str(message_id), "+FLAGS", "\\Deleted")
                    self._connection.expunge()
                    logger.info(f"[DELETE] Gmail UID {message_id} moved to Trash successfully")
                    return True

                # Standard IMAP: \\Deleted + expunge
                result = self._connection.uid('store', str(message_id), "+FLAGS", "\\Deleted")
                if result[0] == "OK":
                    self._connection.expunge()
                    return True

                logger.debug(f"Email UID {message_id} introuvable lors de la suppression — déjà traité")
                return True

            except Exception as e:
                logger.error(f"Erreur suppression IMAP: {e}")
                return False

    def move_to_inbox(self, message_id: str) -> bool:
        """
        Déplace un email du spam vers la boîte de réception.
        IMAP: COPY vers INBOX depuis le dossier spam, puis DELETE de l'original.
        """
        self._ensure_authenticated()

        try:
            spam_folder = self._select_spam_folder()
            if not spam_folder:
                logger.warning(f"Impossible de trouver le dossier spam pour l'email {message_id}")
                return False

            result = self._connection.uid('copy', message_id.encode(), 'INBOX')
            if result[0] == "OK":
                self._connection.uid('store', message_id.encode(), "+FLAGS", "\\Deleted")
                self._connection.expunge()
                logger.info(f"Email UID {message_id} déplacé de {spam_folder} vers INBOX")
                return True

            logger.warning(f"Impossible de déplacer l'email {message_id} vers INBOX")
            return False

        except Exception as e:
            logger.error(f"Erreur move_to_inbox IMAP: {e}")
            return False

    def restore_from_trash(self, message_id: str) -> bool:
        """
        Restaure un email de la corbeille vers la boîte de réception.
        IMAP: COPY vers INBOX depuis le dossier trash, puis DELETE de l'original.
        """
        self._ensure_authenticated()

        try:
            trash_folder = self._select_trash_folder()
            if not trash_folder:
                logger.warning(f"Impossible de trouver le dossier trash pour l'email {message_id}")
                return False

            result = self._connection.uid('copy', message_id.encode(), 'INBOX')
            if result[0] == "OK":
                self._connection.uid('store', message_id.encode(), "+FLAGS", "\\Deleted")
                self._connection.expunge()
                logger.info(f"Email UID {message_id} restauré de {trash_folder} vers INBOX")
                return True

            logger.warning(f"Impossible de restaurer l'email {message_id} vers INBOX")
            return False

        except Exception as e:
            logger.error(f"Erreur restore_from_trash IMAP: {e}")
            return False

    def move_to_spam(self, message_id: str) -> bool:
        """
        Déplace un email vers le dossier spam/indésirables.
        IMAP: COPY vers le dossier spam, puis DELETE de l'original.
        """
        self._ensure_authenticated()

        try:
            spam_folder = self._select_spam_folder()
            if not spam_folder:
                logger.warning(f"Impossible de trouver le dossier spam pour l'email {message_id}")
                return False

            # Re-sélectionner le dossier source (_select_spam_folder a changé la sélection)
            self._select_folder(self.folder)
            result = self._connection.uid('copy', message_id.encode(), spam_folder)
            if result[0] == "OK":
                self._connection.uid('store', message_id.encode(), "+FLAGS", "\\Deleted")
                self._connection.expunge()
                logger.info(f"Email UID {message_id} déplacé vers {spam_folder}")
                return True

            logger.warning(f"Impossible de déplacer l'email {message_id} vers {spam_folder}")
            return False

        except Exception as e:
            logger.error(f"Erreur move_to_spam IMAP: {e}")
            return False

    def unarchive_email(self, message_id: str) -> bool:
        """
        Restaure un email depuis les Archives vers la boîte de réception.

        IMAP standard: COPY vers INBOX depuis le dossier Archive, puis DELETE de l'original.
        Gmail IMAP: COPY vers INBOX uniquement (ajoute le label INBOX sans supprimer de All Mail).
        """
        self._ensure_authenticated()

        try:
            archive_folder = self._select_archive_folder()
            if not archive_folder:
                logger.warning(f"Dossier Archive introuvable pour l'email {message_id}")
                return False

            # archive_folder est maintenant sélectionné — COPY depuis archive vers INBOX
            is_gmail = "gmail" in (self.host or "").lower()
            result = self._connection.uid('copy', message_id.encode(), 'INBOX')
            if result[0] != "OK":
                logger.warning(f"Impossible de désarchiver l'email {message_id} vers INBOX")
                return False

            if not is_gmail:
                # IMAP standard: supprimer de l'archive après copie vers INBOX
                self._connection.uid('store', message_id.encode(), "+FLAGS", "\\Deleted")
                self._connection.expunge()
            # Pour Gmail IMAP: COPY seul suffit (ajoute le label INBOX), pas de suppression de All Mail

            logger.info(f"Email UID {message_id} désarchivé vers INBOX")
            return True

        except Exception as e:
            logger.error(f"Erreur unarchive_email IMAP: {e}")
            return False

    def permanently_delete(self, message_id: str) -> bool:
        """
        Supprime définitivement un email (flag \\Deleted + expunge).

        Args:
            message_id: ID du message IMAP.

        Returns:
            True si la suppression a réussi.
        """
        self._ensure_authenticated()

        try:
            self._select_folder(self.folder)
            result = self._connection.uid('store', message_id.encode(), "+FLAGS", "\\Deleted")
            if result[0] == "OK":
                self._connection.expunge()
                logger.debug(f"Message UID {message_id} supprimé définitivement (IMAP)")
                return True
            return False
        except Exception as e:
            logger.error(f"Erreur suppression définitive IMAP: {e}")
            return False

    def get_user_drafts(self, limit: int = 50) -> List[StandardEmail]:
        """
        Récupère les brouillons de l'utilisateur.

        Note: IMAP peut accéder au dossier Drafts mais la détection
        de brouillons "à compléter" n'est pas supportée nativement.
        """
        self._ensure_authenticated()

        try:
            drafts_folder = self._select_drafts_folder()
            if not drafts_folder:
                logger.warning("Dossier brouillons non trouvé")
                return []

            # Rechercher tous les messages
            status, message_ids = self._connection.uid('search', None, "ALL")

            if status != "OK":
                return []

            emails = []
            ids = message_ids[0].split()

            for msg_id in ids[-limit:]:
                status, data = self._connection.uid('fetch', msg_id, "(FLAGS BODY.PEEK[])")

                if status != "OK":
                    continue

                flags = data[0][0] if isinstance(data[0], tuple) else b""
                raw_email = data[0][1] if isinstance(data[0], tuple) else data[0]
                msg = email.message_from_bytes(raw_email)

                emails.append(self._map_to_standard_email(
                    msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id),
                    msg,
                    flags
                ))

            return emails

        except Exception as e:
            logger.error(f"Erreur récupération brouillons IMAP: {e}")
            return []

    def _select_sent_folder(self) -> int:
        """Select the Sent folder, using cached name if available.

        Returns the EXISTS message count (>0) on success, 0 on failure.
        Caches the folder name to avoid re-probing (saves ~10s per avoided probe on Gmail).

        Detection strategy (in order):
        1. Cached name from previous successful probe
        2. \\Sent flag from IMAP LIST (language-agnostic, handles modified UTF-7 encoding)
        3. Hardcoded fallback names (legacy path)
        """
        import re as _re

        def _try_select(name: str) -> int:
            """Try selecting a folder. Returns EXISTS count or 0."""
            try:
                status, data = self._select_folder(name)
                if status == "OK" and data and data[0]:
                    return int(data[0])
            except Exception:
                pass
            return 0

        def _cache_and_return(name: str, count: int) -> int:
            self._sent_folder_name = name
            _set_folder_cache(_SENT_FOLDER_GLOBAL_CACHE, (self.host, self.username), name)
            logger.debug(f"Using sent folder: {name} ({count} messages)")
            return count

        # 1. Use cached name if we already found it
        if self._sent_folder_name:
            count = _try_select(self._sent_folder_name)
            if count > 0:
                return count
            self._sent_folder_name = None  # Cache was stale

        # 2. Detect via \Sent flag from IMAP LIST — works regardless of folder name language/encoding
        try:
            status, folder_list = self._connection.list()
            if status == "OK" and folder_list:
                for entry in folder_list:
                    raw = entry.decode() if isinstance(entry, bytes) else str(entry)
                    # IMAP LIST line: (<flags>) "<sep>" "<name>"
                    # e.g. (\HasNoChildren \Sent) "/" "[Gmail]/Messages envoy&AOk-s"
                    flags_part = raw.split(")")[0] if ")" in raw else ""
                    if r"\Sent" in flags_part or "\\Sent" in flags_part:
                        # Extract folder name — last quoted or unquoted token after separator
                        m = _re.search(r'"([^"]+)"\s*$', raw) or _re.search(r'(\S+)\s*$', raw)
                        if m:
                            folder_name = m.group(1)
                            count = _try_select(folder_name)
                            if count > 0:
                                return _cache_and_return(folder_name, count)
                            # Folder found via flag but SELECT returned 0 (empty mailbox is OK)
                            # Still cache and return 0 so caller knows we found it
                            return _cache_and_return(folder_name, 0)
        except Exception as list_err:
            logger.debug(f"IMAP LIST probe failed: {list_err}")

        # 3. Fallback to hardcoded names (covers servers that don't advertise \Sent flag)
        is_gmail = "gmail" in (self.host or "").lower()
        if is_gmail:
            sent_folders = [
                "[Gmail]/Sent Mail",
                "[Gmail]/Messages envoy\u00e9s",
                "[Gmail]/Messages envoy&AOk-s",  # modified UTF-7
                "[Gmail]/Gesendete Mails",
                "[Gmail]/Correo enviado",
                "Sent",
                "INBOX.Sent",
                "Sent Items",
            ]
        else:
            sent_folders = [
                "Sent",
                "Sent Items",
                "INBOX.Sent",
                "[Gmail]/Sent Mail",
                "Sent Messages",
                "Éléments envoyés",
                "Éléments envoyés",
            ]

        for folder_name in sent_folders:
            count = _try_select(folder_name)
            if count > 0:
                return _cache_and_return(folder_name, count)

        logger.warning("Dossier emails envoyés non trouvé après toutes les tentatives")
        return 0

    def _select_folder_by_flag(
        self,
        imap_flag: str,
        fallback_names: list,
        cache_attr: str,
        global_cache: dict,
        warning_label: str,
    ) -> str:
        """Generic helper: find a special folder via IMAP \\Flag, then hardcoded fallbacks.

        Returns the folder name string on success (may be empty if mailbox exists but has 0 msgs),
        or '' if not found at all.  The result is cached in self.<cache_attr> and global_cache.
        """
        import re as _re

        def _try_select(name: str) -> bool:
            try:
                status, _ = self._select_folder(name)
                return status == "OK"
            except Exception:
                return False

        def _cache(name: str) -> str:
            setattr(self, cache_attr, name)
            _set_folder_cache(global_cache, (self.host, self.username), name)
            logger.debug(f"Using {warning_label} folder: {name}")
            return name

        # 1. Instance cache
        cached = getattr(self, cache_attr, None)
        if cached:
            if _try_select(cached):
                return cached
            setattr(self, cache_attr, None)

        # 2. Module-level cache (with TTL)
        gk = (self.host, self.username)
        name = _get_folder_cache(global_cache, gk)
        if name:
            if _try_select(name):
                setattr(self, cache_attr, name)
                return name
            del global_cache[gk]

        # 3. IMAP LIST flag detection (language/encoding agnostic)
        try:
            status, folder_list = self._connection.list()
            if status == "OK" and folder_list:
                for entry in folder_list:
                    raw = entry.decode() if isinstance(entry, bytes) else str(entry)
                    flags_part = raw.split(")")[0] if ")" in raw else ""
                    if imap_flag in flags_part:
                        m = _re.search(r'"([^"]+)"\s*$', raw) or _re.search(r'(\S+)\s*$', raw)
                        if m:
                            return _cache(m.group(1))
        except Exception as list_err:
            logger.debug(f"IMAP LIST probe failed for {warning_label}: {list_err}")

        # 4. Hardcoded fallback names
        for name in fallback_names:
            if _try_select(name):
                return _cache(name)

        logger.warning(f"Dossier {warning_label} non trouvé après toutes les tentatives")
        return ""

    def _select_spam_folder(self) -> str:
        """Select the Spam/Junk folder. Returns folder name or '' if not found."""
        _host = (self.host or "").lower()
        is_gmail = "gmail" in _host
        is_outlook = any(h in _host for h in ("outlook", "hotmail", "live.com", "office365"))
        if is_gmail:
            fallbacks = ["[Gmail]/Spam", "Spam", "Junk", "INBOX.Spam"]
        elif is_outlook:
            fallbacks = ["Junk", "Spam", "INBOX.Spam"]
        else:
            fallbacks = ["Junk", "Spam", "INBOX.Spam", "[Gmail]/Spam"]
        return self._select_folder_by_flag(
            r"\Junk", fallbacks, "_spam_folder_name", _SPAM_FOLDER_GLOBAL_CACHE, "spam"
        )

    def _select_trash_folder(self) -> str:
        """Select the Trash folder. Returns folder name or '' if not found."""
        _host = (self.host or "").lower()
        is_gmail = "gmail" in _host
        is_outlook = any(h in _host for h in ("outlook", "hotmail", "live.com", "office365"))
        if is_gmail:
            fallbacks = ["[Gmail]/Trash", "Trash", "Deleted Items", "INBOX.Trash"]
        elif is_outlook:
            fallbacks = ["Deleted Items", "Trash", "INBOX.Trash"]
        else:
            fallbacks = ["Deleted Items", "Trash", "INBOX.Trash", "[Gmail]/Trash"]
        return self._select_folder_by_flag(
            r"\Trash", fallbacks, "_trash_folder_name", _TRASH_FOLDER_GLOBAL_CACHE, "trash"
        )

    def _select_drafts_folder(self) -> str:
        """Select the Drafts folder. Returns folder name or '' if not found."""
        _host = (self.host or "").lower()
        is_gmail = "gmail" in _host
        if is_gmail:
            fallbacks = ["[Gmail]/Drafts", "Drafts", "Draft", "INBOX.Drafts"]
        else:
            fallbacks = ["Drafts", "Draft", "INBOX.Drafts", "[Gmail]/Drafts"]
        return self._select_folder_by_flag(
            r"\Drafts", fallbacks, "_drafts_folder_name", _DRAFTS_FOLDER_GLOBAL_CACHE, "drafts"
        )

    def _select_archive_folder(self) -> str:
        """Select the Archive folder. Returns folder name or '' if not found.

        Gmail IMAP uses the \\All flag (All Mail). Standard IMAP servers use \\Archive.
        """
        is_gmail = "gmail" in (self.host or "").lower()
        if is_gmail:
            fallbacks = ["[Gmail]/All Mail", "Archive", "Archives", "INBOX.Archive"]
            flag = r"\All"
        else:
            fallbacks = ["Archive", "Archives", "INBOX.Archive", "[Gmail]/All Mail"]
            flag = r"\Archive"
        return self._select_folder_by_flag(
            flag, fallbacks, "_archived_folder_name", _ARCHIVE_FOLDER_GLOBAL_CACHE, "archive"
        )

    def resolve_folder_name(self, logical_folder: str) -> str:
        """Map a logical folder name (inbox/sent/spam/trash/draft/archived) to the
        actual IMAP folder name for this server.

        This uses IMAP flag detection + fallback lists, so it works with Gmail,
        Outlook/Hotmail, Yahoo, and generic IMAP servers regardless of locale.
        """
        logical = logical_folder.lower().strip()
        if logical == "inbox":
            return "INBOX"

        with self._connection_lock:
            self._ensure_authenticated()
            if logical == "sent":
                # _select_sent_folder is different (returns count), use _select_folder_by_flag
                is_gmail = "gmail" in (self.host or "").lower()
                fallbacks = (
                    ["[Gmail]/Sent Mail", "Sent", "Sent Items", "INBOX.Sent"]
                    if is_gmail
                    else ["Sent", "Sent Items", "Sent Messages", "INBOX.Sent", "[Gmail]/Sent Mail"]
                )
                return self._select_folder_by_flag(
                    r"\Sent", fallbacks, "_sent_folder_name", _SENT_FOLDER_GLOBAL_CACHE, "sent"
                ) or "Sent"
            elif logical == "spam":
                return self._select_spam_folder() or "Junk"
            elif logical == "trash":
                return self._select_trash_folder() or "Trash"
            elif logical in ("draft", "drafts"):
                return self._select_drafts_folder() or "Drafts"
            elif logical == "archived":
                # Gmail has All Mail; others often don't have an archive folder
                is_gmail = "gmail" in (self.host or "").lower()
                fallbacks = (
                    ["[Gmail]/All Mail", "Archive", "INBOX"]
                    if is_gmail
                    else ["Archive", "INBOX.Archive", "[Gmail]/All Mail", "INBOX"]
                )
                return self._select_folder_by_flag(
                    r"\All", fallbacks, "_archived_folder_name",
                    {}, "archived"  # no global cache for archived
                ) or "INBOX"
            else:
                return logical_folder

    def get_sent_emails(self, limit: int = 50) -> List[StandardEmail]:
        """
        Récupère les emails envoyés (headers only — fast).

        Minimizes IMAP round-trips: SELECT + single FETCH (no SEARCH).
        Gmail rate-limits each operation to ~10s, so fewer ops = much faster.

        Args:
            limit: Nombre maximum d'emails à récupérer.

        Returns:
            Liste d'emails normalisés (StandardEmail).
        """
        with self._connection_lock:
            self._ensure_authenticated()

            try:
                select_result = self._select_sent_folder()
                if not select_result:
                    return []

                # EXISTS count is returned by SELECT as (status, [b'170'])
                total_messages = select_result if isinstance(select_result, int) else 0

                if total_messages == 0:
                    return []

                # Fetch the last `limit` messages by sequence number (most recent).
                # Sequence numbers are 1-based. Using "N:*" avoids a SEARCH round-trip (~10s on Gmail).
                start = max(1, total_messages - limit + 1)
                fetch_range = f"{start}:*"

                status, all_data = self._connection.fetch(
                    fetch_range,
                    "(UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID)])"
                )

                if status != "OK":
                    logger.error("Erreur fetch batch IMAP sent emails")
                    return []

                emails = []
                for item in all_data:
                    if not isinstance(item, tuple) or len(item) < 2:
                        continue

                    header_info = item[0]
                    header_bytes = item[1]

                    if not isinstance(header_bytes, bytes):
                        continue

                    # Extract UID from header info
                    try:
                        header_decoded = header_info.decode('utf-8', errors='ignore')
                        uid_match = re.search(r'UID\s+(\d+)', header_decoded)
                        if uid_match:
                            msg_id_str = uid_match.group(1)
                        else:
                            msg_id_str = header_info.split(b' ')[0].decode()
                    except (IndexError, AttributeError):
                        continue

                    # Parse headers
                    try:
                        headers = email.message_from_bytes(header_bytes)

                        subject = self._decode_header_value(headers.get("Subject", ""))
                        from_header = headers.get("From", "")
                        sender_email, sender_name = self._parse_email_address(from_header)
                        to_header = headers.get("To", "")
                        cc_header = headers.get("CC", "")
                        date_str = headers.get("Date", "")
                        message_id = headers.get("Message-ID", "")

                        # Parse recipients
                        to_list = []
                        if to_header:
                            to_list = [addr.strip() for addr in to_header.split(",") if addr.strip()]

                        cc_list = []
                        if cc_header:
                            cc_list = [addr.strip() for addr in cc_header.split(",") if addr.strip()]

                        # Parse date
                        received_at = None
                        if date_str:
                            try:
                                from datetime import timezone
                                received_at = parsedate_to_datetime(date_str)
                                if received_at and received_at.tzinfo is None:
                                    received_at = received_at.replace(tzinfo=timezone.utc)
                            except (ValueError, TypeError):
                                pass

                        is_read = b"\\Seen" in header_info

                        std_email = StandardEmail(
                            id=msg_id_str,
                            subject=subject or "(No Subject)",
                            sender=sender_email or from_header,
                            sender_name=sender_name,
                            body="",
                            body_html=None,
                            received_at=received_at,
                            is_read=is_read,
                            has_attachments=False,
                            conversation_id=message_id or None,
                            provider_source=self.PROVIDER_NAME,
                            raw_metadata={"header_only": True},
                        )
                        std_email.to = to_list
                        std_email.cc = cc_list
                        emails.append(std_email)

                    except Exception as e:
                        logger.warning(f"Error parsing sent header for message {msg_id_str}: {e}")
                        continue

                # Trier par date décroissante (plus récents en premier)
                emails.sort(key=lambda e: e.received_at.isoformat() if e.received_at else "", reverse=True)

                logger.info(f"IMAP sent emails fetch (headers-only): {len(emails)} emails")
                return emails

            except Exception as e:
                logger.warning(f"Erreur récupération emails envoyés IMAP: {e}")
                return []

    def list_folders(self) -> List[EmailFolder]:
        """
        Liste les dossiers IMAP de l'utilisateur.

        Returns:
            Liste de dossiers normalisés (EmailFolder).
        """
        self._ensure_authenticated()

        try:
            # Get list of folders
            status, folder_data = self._connection.list()

            if status != "OK":
                logger.error("Erreur listage dossiers IMAP")
                return []

            folders = []
            # System folders that should be categorized as 'system'
            system_folders = {
                "INBOX", "Sent", "Drafts", "Trash", "Spam", "Junk",
                "[Gmail]/Sent Mail", "[Gmail]/Drafts", "[Gmail]/Trash",
                "[Gmail]/Spam", "[Gmail]/All Mail", "[Gmail]/Starred",
                "[Gmail]/Important", "Sent Items", "Deleted Items",
            }

            for folder_line in folder_data:
                if not folder_line:
                    continue

                # Parse IMAP LIST response: (flags) "delimiter" "folder_name"
                # Example: b'(\\HasNoChildren) "/" "INBOX"'
                try:
                    if isinstance(folder_line, bytes):
                        folder_line = folder_line.decode('utf-8', errors='replace')

                    # Extract folder name (last quoted string or unquoted name)
                    import re
                    # Match folder name in quotes or after last space
                    match = re.search(r'"([^"]+)"$|(\S+)$', folder_line)
                    if not match:
                        continue

                    folder_name = match.group(1) or match.group(2)
                    if not folder_name:
                        continue

                    # Determine display name
                    display_name = folder_name.split("/")[-1] if "/" in folder_name else folder_name

                    # Determine parent_id for nested folders
                    parent_id = None
                    if "/" in folder_name:
                        parent_name = "/".join(folder_name.split("/")[:-1])
                        parent_id = parent_name

                    # Determine folder type
                    folder_type = "system" if folder_name in system_folders else "user"

                    # Try to get message count (optional - some servers don't support this)
                    unread_count = 0
                    total_count = 0
                    try:
                        status, select_data = self._select_folder(folder_name, readonly=True)
                        if status == "OK":
                            total_count = int(select_data[0]) if select_data and select_data[0] else 0
                            # Get unread count via SEARCH
                            status, unseen_data = self._connection.uid('search', None, "UNSEEN")
                            if status == "OK" and unseen_data[0]:
                                unread_count = len(unseen_data[0].split())
                    except Exception:
                        pass  # Ignore errors - counts are optional

                    folders.append(EmailFolder(
                        id=folder_name,
                        name=folder_name,
                        display_name=display_name,
                        type=folder_type,
                        parent_id=parent_id,
                        unread_count=unread_count,
                        total_count=total_count,
                    ))

                except Exception as e:
                    logger.warning(f"Error parsing folder line: {e}")
                    continue

            # Re-select INBOX after listing
            self._select_folder(self.folder)

            logger.info(f"IMAP list_folders: {len(folders)} folders")
            return folders

        except Exception as e:
            logger.error(f"Erreur listage dossiers IMAP: {e}")
            return []

    def get_draft_by_id(self, draft_id: str) -> Optional[StandardEmail]:
        """Récupère un brouillon par son ID."""
        # Utilise la même logique que get_message_by_id mais dans le dossier Drafts
        self._ensure_authenticated()

        try:
            if not self._select_drafts_folder():
                return None

            status, data = self._connection.uid('fetch', draft_id.encode(), "(FLAGS BODY.PEEK[])")

            if status != "OK" or not data or not data[0]:
                return None

            flags = data[0][0] if isinstance(data[0], tuple) else b""
            raw_email = data[0][1] if isinstance(data[0], tuple) else data[0]
            msg = email.message_from_bytes(raw_email)

            return self._map_to_standard_email(draft_id, msg, flags)

        except Exception as e:
            logger.error(f"Erreur récupération brouillon IMAP {draft_id}: {e}")
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
        """
        Met à jour un brouillon existant.

        Note: IMAP ne supporte pas la mise à jour directe.
        Cette méthode supprime l'ancien brouillon et en crée un nouveau.
        """
        self._ensure_authenticated()

        try:
            # Récupérer le brouillon existant
            existing = self.get_draft_by_id(draft_id)
            if not existing:
                return False

            # Supprimer l'ancien brouillon
            drafts_folder = self._select_drafts_folder()
            if drafts_folder:
                self._connection.uid('store', draft_id.encode(), "+FLAGS", "\\Deleted")
                self._connection.expunge()

            # Créer un nouveau brouillon avec les valeurs mises à jour
            new_to = to if to is not None else existing.to
            new_subject = subject if subject is not None else existing.subject
            new_body = body if body is not None else existing.body
            new_cc = cc if cc is not None else existing.cc

            new_draft_id = self.create_draft(
                to=new_to,
                subject=new_subject,
                body=new_body,
                cc=new_cc,
                is_html=is_html
            )

            return new_draft_id is not None

        except Exception as e:
            logger.error(f"Erreur mise à jour brouillon IMAP {draft_id}: {e}")
            return False

    def get_signature(self) -> Optional[dict]:
        """
        Extrait la signature email depuis les emails envoyés.

        IMAP n'a pas d'API pour les signatures. Cette méthode analyse
        les emails envoyés pour détecter et extraire la signature.

        NOTE: get_sent_emails() only fetches headers (no body). This method
        fetches full email bodies directly via IMAP FETCH BODY.PEEK[].

        Returns:
            Dict with 'html' and 'text' keys, or None if no signature found.
        """
        try:
            import re
            from collections import Counter

            bodies = self._fetch_sent_bodies(limit=10)
            if not bodies:
                logger.debug("No sent email bodies found for signature extraction")
                return None

            # Collect potential signatures from emails
            potential_signatures = []
            potential_html_signatures = []

            for body_text, body_html in bodies:
                # Prefer HTML extraction (handles Outlook.com rich signatures)
                if body_html and len(body_html) > 30:
                    from app.providers.outlook_adapter import OutlookAdapter
                    # Strip quoted thread from HTML before pattern matching
                    new_html = re.split(r'<hr[^>]*>', body_html, maxsplit=1, flags=re.IGNORECASE)[0]
                    new_html = re.split(
                        r'<div[^>]*style=["\'][^"\']*border-top[^"\']*["\'][^>]*>',
                        new_html, maxsplit=1, flags=re.IGNORECASE
                    )[0]
                    sig_result = OutlookAdapter._extract_signature_div(new_html)
                    if sig_result:
                        potential_html_signatures.append(sig_result)
                        continue

                # Fall back to plain text extraction
                body = body_text or ""
                if not body or len(body) < 20:
                    continue

                # Strip the quoted/forwarded thread before looking for the signature.
                body_stripped = re.split(r'\n_{5,}|\n-{10,}', body, maxsplit=1)[0]
                # Also stop at "De :" / "From:" quoted-header patterns
                body_stripped = re.split(
                    r'\n(?:De\s*:|From\s*:)\s+\S', body_stripped, maxsplit=1
                )[0]

                # Pattern 1: After "-- " delimiter
                if "\n-- \n" in body_stripped:
                    sig = body_stripped.split("\n-- \n")[-1].strip()
                    if 10 < len(sig) < 500:
                        potential_signatures.append(sig)
                    continue

                # Pattern 2: After closing phrase — one paragraph only (no re.DOTALL)
                closing_patterns = [
                    r'(?:Cordialement|Best regards|Regards|Bien à vous|Sincèrement|À bientôt)[,.]?\s*\n(.+?)(?:\n\n|$)',
                    r'(?:Merci|Thanks|Thank you)[,.]?\s*\n(.+?)(?:\n\n|$)',
                ]

                for pattern in closing_patterns:
                    match = re.search(pattern, body_stripped, re.IGNORECASE)
                    if match:
                        sig = match.group(1).strip()
                        if 5 < len(sig) < 500:
                            potential_signatures.append(sig)
                        break

            # If HTML signatures found, return the first one (no frequency requirement —
            # HTML id="Signature" is authoritative)
            if potential_html_signatures:
                sig = potential_html_signatures[0]
                logger.info("IMAP signature extracted (HTML div) from sent emails: %r", sig["text"][:80])
                return sig

            if not potential_signatures:
                logger.debug("No signature pattern detected in sent emails")
                return None

            # Find the most common signature (appears in multiple emails)
            normalized = [re.sub(r'\s+', ' ', sig).strip() for sig in potential_signatures]
            counter = Counter(normalized)

            if not counter:
                return None

            most_common = counter.most_common(1)[0]
            if most_common[1] >= 2:  # At least 2 occurrences
                signature_text = most_common[0]
                # Find original (non-normalized) version
                for sig in potential_signatures:
                    if re.sub(r'\s+', ' ', sig).strip() == signature_text:
                        signature_text = sig
                        break

                logger.info(f"IMAP signature extracted from {most_common[1]} sent emails")
                return {
                    "html": signature_text.replace('\n', '<br>'),
                    "text": signature_text
                }

            # Fallback: if only 1 occurrence but it came from closing-phrase heuristic,
            # return it (user may have few sent emails)
            if len(potential_signatures) == 1:
                sig = potential_signatures[0]
                logger.info("IMAP signature extracted (single match) from sent emails: %r", sig[:80])
                return {
                    "html": sig.replace('\n', '<br>'),
                    "text": sig
                }

            logger.debug("No consistent signature found in sent emails")
            return None

        except Exception as e:
            logger.error(f"Error extracting IMAP signature: {e}")
            return None

    def _fetch_sent_bodies(self, limit: int = 10) -> list:
        """Fetch full email bodies from the sent folder for signature extraction.

        Returns a list of (body_text, body_html) tuples.
        """
        import email as email_lib

        with self._connection_lock:
            self._ensure_authenticated()
            try:
                select_result = self._select_sent_folder()
                if not select_result:
                    return []

                total = select_result if isinstance(select_result, int) else 0
                if total == 0:
                    return []

                start = max(1, total - limit + 1)
                status, all_data = self._connection.fetch(
                    f"{start}:*", "(BODY.PEEK[])"
                )
                if status != "OK" or not all_data:
                    return []

                results = []
                for item in all_data:
                    if not isinstance(item, tuple) or len(item) < 2:
                        continue
                    raw_bytes = item[1]
                    if not isinstance(raw_bytes, bytes):
                        continue
                    try:
                        msg = email_lib.message_from_bytes(raw_bytes)
                        body_text, body_html = self._get_body(msg)
                        if body_text or body_html:
                            results.append((body_text, body_html))
                    except Exception as e:
                        logger.debug(f"Error parsing sent email body for signature: {e}")
                        continue

                return results

            except Exception as e:
                logger.warning(f"Error fetching sent bodies for signature: {e}")
                return []

    def _try_keepalive_noop(self) -> None:
        """NOOP non-bloquant pour le keepalive — acquiert _connection_lock de façon non-bloquante.

        Si le verrou est déjà tenu par un autre thread (IMAP fetch en cours),
        le NOOP est ignoré pour cette itération plutôt que de créer une race SSL.
        Si NOOP échoue, marque la connexion comme morte pour forcer ré-auth au prochain appel.
        """
        if not self._connection_lock.acquire(blocking=False):
            return  # Another thread is using the connection — skip, don't race
        try:
            if self._authenticated and self._connection:
                try:
                    self._connection.noop()
                except Exception as e:
                    logger.warning(f"IMAP keepalive NOOP failed ({self.host}): {e} — marking connection as dead")
                    self._authenticated = False
                    self._selected_folder = None
        finally:
            self._connection_lock.release()

    def _reset_on_ssl_error(self) -> None:
        """Force-reset the IMAP connection after an SSL error.

        SSL errors leave the underlying socket in a corrupted state. Reusing
        the connection causes segfaults in libssl C extensions. This method
        closes the raw socket directly (no LOGOUT — the SSL layer is already
        broken) and resets all auth state so the next call re-authenticates.
        """
        try:
            self._authenticated = False
            self._selected_folder = None
            conn = self._connection
            self._connection = None
            if conn:
                try:
                    sock = conn.socket()
                    if sock:
                        sock.close()
                except Exception:
                    pass
            if self._semaphore_acquired:
                _IMAP_CONNECTION_SEMAPHORE.release()
                self._semaphore_acquired = False
        except Exception:
            pass

    def disconnect(self) -> None:
        """Ferme la connexion IMAP proprement.

        CRITICAL: Must call LOGOUT before closing the socket to avoid
        SSL/TLS memory corruption during cleanup. Direct socket closure
        without LOGOUT causes malloc errors in libssl.3.dylib.
        """
        # ``_connection_lock`` is unset when __init__ raised early (e.g.
        # missing IMAP config). Use getattr so __del__ during failed
        # construction stays silent rather than producing AttributeError.
        lock = getattr(self, "_connection_lock", None)
        if lock is None:
            return
        with lock:
            if self._connection:
                try:
                    # Always try LOGOUT first (safe even if not authenticated)
                    try:
                        self._connection.logout()
                    except Exception:
                        # LOGOUT may fail, but we still need to close the socket
                        pass

                    # Then close the socket safely
                    try:
                        sock = self._connection.socket()
                        if sock:
                            sock.shutdown(2)  # SHUT_RDWR
                            sock.close()
                    except Exception:
                        pass
                except Exception:
                    pass
                finally:
                    self._connection = None
                    self._authenticated = False
                    self._selected_folder = None

            # Release semaphore slot now that the connection is closed
            if self._semaphore_acquired:
                _IMAP_CONNECTION_SEMAPHORE.release()
                self._semaphore_acquired = False

    def __del__(self):
        """Déconnexion automatique."""
        try:
            self.disconnect()
        except Exception:
            pass
