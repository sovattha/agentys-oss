# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adaptateur Gmail pour Google API.

Implémente l'interface EmailProvider pour Gmail.
Utilise google-auth et google-api-python-client.
"""

import os
import base64
from contextlib import contextmanager
import json
import logging
import math
import re
import threading
import time
from datetime import datetime
from email.header import decode_header as decode_mime_header
from email.message import Message
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import Dict, List, Optional, Tuple

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Default timeout (seconds) for every Gmail API call. Without this, .execute()
# calls inherit httplib2's indefinite-blocking default → the UI can freeze for
# minutes if Google's network path stalls. 30s is generous for normal calls
# and still protects against hung syncs.
_GMAIL_HTTP_TIMEOUT = 30.0
_GMAIL_SLOW_LOG_THRESHOLD_MS = 5000
_GMAIL_ACCOUNT_MAX_IN_FLIGHT = 2


class GmailQuotaBackoffError(RuntimeError):
    """Raised when an interactive Gmail call would wait too long for quota."""

    code = "GMAIL_QUOTA_BACKOFF"

    def __init__(self, operation: str, account_key: str, retry_after: float):
        self.operation = operation
        self.account_key = account_key
        self.retry_after = max(1, int(math.ceil(retry_after)))
        super().__init__(
            f"Gmail quota backoff for {operation} on account={account_key}: "
            f"retry after {self.retry_after}s"
        )


# Audit 2026-05-11 (runtime logs P0): synthetic IDs from QuickSteps demo /
# fixture flows ("email-N", "PYTHON-FLASK-Bx", "draft-abc123",
# "test-email-id" …) were leaking into mark_as_read / mark_as_unread,
# producing repeated Gmail HTTP 400 "Invalid id value" errors. Gmail message
# IDs are opaque strings, so deny only the synthetic patterns we create.
# "reply-<ts>" (2026-06-11): placeholder Sent rows inserted at reply time for
# immediate folder visibility (cf. dedupe_sent_by_content) — they have no
# provider counterpart, so any Gmail call on them is a guaranteed 400/404.
_SYNTHETIC_GMAIL_ID_RE = re.compile(
    r"^(?:email-\d+|reply-\d+|draft-[A-Za-z0-9_-]+|test-email-id|PYTHON-FLASK-[A-Za-z0-9_-]+)$"
)


def _is_gmail_message_id(message_id: str) -> bool:
    if not isinstance(message_id, str) or not message_id:
        return False
    return not bool(_SYNTHETIC_GMAIL_ID_RE.match(message_id))


def _build_authorized_http(creds) -> "object":
    """Wrap credentials in an AuthorizedHttp with an explicit timeout.

    Returns an AuthorizedHttp ready to be passed as `http=` to `build()`.
    Imported lazily to keep module import light and to avoid a hard failure
    if google_auth_httplib2 is unavailable (falls back to no-timeout build).
    """
    try:
        import httplib2
        from google_auth_httplib2 import AuthorizedHttp
        return AuthorizedHttp(creds, http=httplib2.Http(timeout=_GMAIL_HTTP_TIMEOUT))
    except Exception:
        return None

from app.interfaces.email_provider import (
    EmailProvider,
    StandardEmail,
    EmailFolder,
    InsufficientScopeError,
)
from app.providers.email_parser_mixin import EmailParserMixin

logger = logging.getLogger(__name__)

# Global lock keyed by token_file path to serialize refresh + file write across
# concurrent GmailAdapter instances sharing the same credential file.
# Bug fix: previously, concurrent threads could both call creds.refresh() and
# overwrite token.json → corrupt JSON → silent logout on next start.
_TOKEN_REFRESH_LOCKS: dict = {}
_TOKEN_REFRESH_LOCKS_GUARD = threading.Lock()


def _get_token_refresh_lock(token_file: Optional[str]) -> threading.RLock:
    """Return a reentrant lock dedicated to refresh+write for the given token_file."""
    key = token_file or "<default>"
    with _TOKEN_REFRESH_LOCKS_GUARD:
        lock = _TOKEN_REFRESH_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _TOKEN_REFRESH_LOCKS[key] = lock
        return lock


def _atomic_write_text(path: str, content: str) -> None:
    """Write content to path atomically (write temp + rename).

    Prevents partial writes from corrupting token.json if the process is
    interrupted or another thread reads mid-write. Falls back to a direct
    write if the atomic path fails (e.g. running under a mock_open that
    doesn't create a real file).
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    tmp_path = f"{path}.tmp.{os.getpid()}.{threading.get_ident()}"
    try:
        os.makedirs(directory, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            # fsync is best-effort: OSError on some filesystems, TypeError
            # when fileno() is mocked in tests. Either is OK to swallow — the
            # atomic rename below is the real safety net.
            try:
                os.fsync(f.fileno())
            except (OSError, TypeError, ValueError):
                pass
        try:
            os.replace(tmp_path, path)
        except OSError:
            # The tmp file may not have been physically created (e.g. mocked
            # open() in unit tests). Fall back to a direct write.
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


# Maximum retry-delay we honor from Google (safety cap to avoid abuse / hung syncs)
GMAIL_MAX_HONORED_RETRY_DELAY = 60.0
# Pattern matching google.protobuf.Duration ("30s", "1.5s", "0.250s")
_DURATION_PATTERN = re.compile(r"^([0-9]+(?:\.[0-9]+)?)s$")


def _parse_duration_seconds(value) -> Optional[float]:
    """Parse a google.protobuf.Duration string ("30s") or numeric seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = _DURATION_PATTERN.match(value.strip())
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    return None


def _extract_gmail_retry_delay(exception: HttpError) -> Optional[float]:
    """
    Extract the server-requested retry delay from a Gmail HttpError.

    Sources (in priority order):
    1. ``error.details[].retryDelay`` from google.rpc.RetryInfo (canonical for 429).
    2. HTTP ``Retry-After`` header (fallback, mostly emitted on 503).

    Returns the delay in seconds (capped to GMAIL_MAX_HONORED_RETRY_DELAY) or
    None if no delay was advertised.
    """
    if not isinstance(exception, HttpError):
        return None

    # Try parsing the JSON body for google.rpc.RetryInfo
    content = getattr(exception, "content", None)
    if content:
        try:
            payload = json.loads(content.decode("utf-8") if isinstance(content, bytes) else content)
            details = (payload.get("error") or {}).get("details") or []
            for detail in details:
                if not isinstance(detail, dict):
                    continue
                detail_type = detail.get("@type", "")
                if "RetryInfo" in detail_type:
                    delay = _parse_duration_seconds(detail.get("retryDelay"))
                    if delay is not None and delay >= 0:
                        return min(delay, GMAIL_MAX_HONORED_RETRY_DELAY)
        except (ValueError, AttributeError, KeyError):
            pass

    # Fallback: HTTP Retry-After header (seconds or HTTP-date)
    try:
        retry_after = exception.resp.get("retry-after") if exception.resp else None
        if retry_after:
            delay = _parse_duration_seconds(retry_after)
            if delay is None:
                # Header may be plain seconds without "s" suffix
                try:
                    delay = float(retry_after)
                except ValueError:
                    delay = None
            if delay is not None and delay >= 0:
                return min(delay, GMAIL_MAX_HONORED_RETRY_DELAY)
    except (AttributeError, TypeError):
        pass

    return None


def _low_priority_backoff_seconds() -> float:
    """Cooldown for opportunistic Gmail metadata fetches after any 429."""
    try:
        return max(0.0, float(os.getenv("GMAIL_LOW_PRIORITY_BACKOFF_SECONDS", "900")))
    except (TypeError, ValueError):
        return 900.0


class _GmailQuotaCoordinator:
    """In-process per-account gate for Gmail calls that consume metadata quota."""

    def __init__(self, key: str):
        self.key = key
        self._lock = threading.RLock()
        self._in_flight = threading.BoundedSemaphore(_GMAIL_ACCOUNT_MAX_IN_FLIGHT)
        self._next_allowed_at = 0.0
        self._low_priority_next_allowed_at = 0.0
        self._fallback_delay = 4.5

    def retry_after_seconds(self) -> float:
        return max(0.0, self._next_allowed_at - time.monotonic())

    def low_priority_retry_after_seconds(self) -> float:
        return max(0.0, self._low_priority_next_allowed_at - time.monotonic())

    def _wait_until_allowed(self, operation: str, max_wait_seconds: float | None = None) -> None:
        delay = max(0.0, self._next_allowed_at - time.monotonic())
        while delay > 0:
            if max_wait_seconds is not None and delay > max_wait_seconds:
                raise GmailQuotaBackoffError(operation, self.key, delay)
            logger.info(
                "Gmail quota gate: sleeping %.1fs before %s for account=%s",
                delay,
                operation,
                self.key,
            )
            time.sleep(delay)
            delay = max(0.0, self._next_allowed_at - time.monotonic())

    def _next_delay(self, exceptions: list[HttpError]) -> tuple[float, bool]:
        server_delays = [
            _extract_gmail_retry_delay(exc)
            for exc in exceptions
            if isinstance(exc, HttpError)
        ]
        server_delays = [d for d in server_delays if d is not None]
        if server_delays:
            return max(server_delays), True
        delay = self._fallback_delay
        self._fallback_delay = min(delay * 2.0, GMAIL_MAX_HONORED_RETRY_DELAY)
        return delay, False

    def _record_rate_limit(self, operation: str, exceptions: list[HttpError]) -> float:
        delay, from_server = self._next_delay(exceptions)
        now = time.monotonic()
        self._next_allowed_at = max(self._next_allowed_at, now + delay)
        self._low_priority_next_allowed_at = max(
            self._low_priority_next_allowed_at,
            now + max(delay, _low_priority_backoff_seconds()),
        )
        source = "server" if from_server else "fallback"
        logger.warning(
            "Gmail quota gate: 429 on %s for account=%s, %s backoff %.1fs",
            operation,
            self.key,
            source,
            delay,
        )
        return delay

    def _record_success(self) -> None:
        self._fallback_delay = max(self._fallback_delay * 0.7, 4.5)

    def run(self, operation: str, execute, max_wait_seconds: float | None = None):
        while True:
            self._wait_until_allowed(operation, max_wait_seconds=max_wait_seconds)
            with self._lock:
                delay = self.retry_after_seconds()
            if delay > 0:
                continue
            with self._in_flight:
                try:
                    result = execute()
                except HttpError as exc:
                    if getattr(getattr(exc, "resp", None), "status", None) == 429:
                        with self._lock:
                            self._record_rate_limit(operation, [exc])
                    raise
            with self._lock:
                self._record_success()
            return result

    def run_batch(self, operation: str, execute, rate_limited_errors):
        while True:
            self._wait_until_allowed(operation)
            with self._lock:
                delay = self.retry_after_seconds()
            if delay > 0:
                continue
            with self._in_flight:
                try:
                    result = execute()
                except HttpError as exc:
                    if getattr(getattr(exc, "resp", None), "status", None) == 429:
                        with self._lock:
                            self._record_rate_limit(operation, [exc])
                    raise

                errors = list(rate_limited_errors() or [])
            with self._lock:
                if errors:
                    self._record_rate_limit(operation, errors)
                else:
                    self._record_success()
            return result

_GMAIL_QUOTA_COORDINATORS: dict[str, _GmailQuotaCoordinator] = {}
_GMAIL_QUOTA_COORDINATORS_GUARD = threading.Lock()


def _get_gmail_quota_coordinator(key: Optional[str]) -> _GmailQuotaCoordinator:
    quota_key = key or "<default>"
    with _GMAIL_QUOTA_COORDINATORS_GUARD:
        coordinator = _GMAIL_QUOTA_COORDINATORS.get(quota_key)
        if coordinator is None:
            coordinator = _GmailQuotaCoordinator(quota_key)
            _GMAIL_QUOTA_COORDINATORS[quota_key] = coordinator
        return coordinator


class GmailAdapter(EmailProvider, EmailParserMixin):
    """
    Adaptateur Gmail via Google API.

    Modes d'authentification supportés :
    1. OAuth2 avec credentials.json (interactif)
    2. Service Account (pour applications serveur)
    3. Refresh Token (pour tokens pré-générés)
    4. Server-side tokens (pour comptes OAuth via l'app web)

    Variables d'environnement :
    - GOOGLE_CREDENTIALS_FILE : Chemin vers credentials.json
    - GOOGLE_TOKEN_FILE : Chemin vers token.json (cache OAuth)
    - GOOGLE_CLIENT_ID : Client ID (alternative à credentials.json)
    - GOOGLE_CLIENT_SECRET : Client Secret
    - GOOGLE_REFRESH_TOKEN : Refresh token pré-généré
    """

    PROVIDER_NAME = "gmail"

    # Scopes requis pour lire/envoyer des emails + calendrier (Issue #26)
    SCOPES = [
        # Email scopes
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.compose",
        # Settings scope (signature sync)
        "https://www.googleapis.com/auth/gmail.settings.basic",
        # Calendar scopes (Issue #26)
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar",
    ]

    def __init__(
        self,
        credentials_file: Optional[str] = None,
        token_file: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
        account_id: Optional[str] = None,
    ):
        """
        Initialise l'adaptateur Gmail.

        Args:
            credentials_file: Chemin vers credentials.json (OAuth)
            token_file: Chemin vers token.json (cache)
            client_id: Google Client ID
            client_secret: Google Client Secret
            refresh_token: Refresh token pré-généré
            account_id: ID du compte pour tokens server-side (OAuth web)
        """
        self.credentials_file = credentials_file or os.getenv("GOOGLE_CREDENTIALS_FILE")
        self.token_file = token_file or os.getenv("GOOGLE_TOKEN_FILE", "token.json")
        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET")
        self.refresh_token = refresh_token or os.getenv("GOOGLE_REFRESH_TOKEN")
        self.account_id = account_id
        self._quota = _get_gmail_quota_coordinator(self.account_id or self.token_file)

        self._credentials: Optional[Credentials] = None
        # Thread-local storage for Gmail `_service`. httplib2.Http (used
        # internally by the Google client) is NOT thread-safe — concurrent
        # SSL I/O on the same Http corrupts OpenSSL BIO buffers, which
        # surfaces as `malloc(): unsorted double linked list corrupted` on
        # Linux (segfault on Windows). Each thread gets its own Http via
        # the `_service` property below; credentials are shared and
        # refresh is already serialized by `_TOKEN_REFRESH_LOCKS`.
        self._service_storage = threading.local()
        self._quota_wait_storage = threading.local()
        self._authenticated = False
        self._auth_fail_time: float = 0  # Cooldown: timestamp of last auth failure
        self._auth_fail_reason: str = ""  # Last auth failure reason for logging
        self._last_error: str = ""  # Last API error for surfacing to callers

    @property
    def _service(self):
        """Thread-local Gmail API service (lazily built per thread).

        Returns None if not yet authenticated (preserves the legacy truthiness
        check used by `_ensure_authenticated`).
        """
        svc = getattr(self._service_storage, "service", None)
        if svc is not None:
            return svc
        # Lazy build for this thread if we already have credentials.
        if self._authenticated and self._credentials is not None:
            _authed_http = _build_authorized_http(self._credentials)
            svc = (
                build("gmail", "v1", http=_authed_http, cache_discovery=False)
                if _authed_http is not None
                else build("gmail", "v1", credentials=self._credentials)
            )
            self._service_storage.service = svc
            return svc
        return None

    @_service.setter
    def _service(self, value) -> None:
        """Store a service instance in the current thread's local storage.

        Callers (authenticate(), batch-err recovery) set this when they've
        just built a fresh service. Other threads will lazily build their
        own on first `_service` read.
        """
        # `_service_storage` may not exist yet if a subclass __init__ sets
        # `_service` before super().__init__() runs; create lazily.
        if not hasattr(self, "_service_storage"):
            self._service_storage = threading.local()
        self._service_storage.service = value

    @contextmanager
    def limited_quota_wait(self, max_wait_seconds: float):
        """Temporarily cap Gmail quota waiting for user-facing requests."""
        storage = self._quota_wait_state()
        previous = getattr(storage, "max_wait_seconds", None)
        storage.max_wait_seconds = max_wait_seconds
        try:
            yield
        finally:
            if previous is None:
                try:
                    delattr(storage, "max_wait_seconds")
                except AttributeError:
                    pass
            else:
                storage.max_wait_seconds = previous

    def _execute_gmail_request(self, request, operation: str):
        """Execute one Gmail request through the per-account quota gate."""
        started_at = time.perf_counter()
        try:
            result = self._quota_gate().run(
                operation,
                request.execute,
                max_wait_seconds=getattr(self._quota_wait_state(), "max_wait_seconds", None),
            )
        except Exception as exc:
            self._log_gmail_api_timing(operation, started_at, success=False, error=exc)
            raise
        self._log_gmail_api_timing(operation, started_at, success=True)
        return result

    def _execute_gmail_batch(self, batch, operation: str, rate_limited_errors):
        """Execute a Gmail batch while honoring account-level 429 backoff."""
        started_at = time.perf_counter()
        try:
            result = self._quota_gate().run_batch(operation, batch.execute, rate_limited_errors)
        except Exception as exc:
            self._log_gmail_api_timing(f"{operation}.batch", started_at, success=False, error=exc)
            raise
        self._log_gmail_api_timing(f"{operation}.batch", started_at, success=True)
        return result

    def _log_gmail_api_timing(
        self,
        operation: str,
        started_at: float,
        *,
        success: bool,
        error: Exception | None = None,
    ) -> None:
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        if success and elapsed_ms < _GMAIL_SLOW_LOG_THRESHOLD_MS:
            logger.debug(
                "[GMAIL-API] operation=%s account_key=%s success=true ms=%s",
                operation,
                getattr(self, "account_id", None) or "local",
                elapsed_ms,
            )
            return

        if success:
            logger.warning(
                "[GMAIL-API] operation=%s account_key=%s success=true ms=%s",
                operation,
                getattr(self, "account_id", None) or "local",
                elapsed_ms,
            )
            return

        logger.warning(
            "[GMAIL-API] operation=%s account_key=%s success=false ms=%s error_type=%s",
            operation,
            getattr(self, "account_id", None) or "local",
            elapsed_ms,
            type(error).__name__ if error else "unknown",
        )

    def _quota_gate(self) -> _GmailQuotaCoordinator:
        if not hasattr(self, "_quota"):
            self._quota = _get_gmail_quota_coordinator(
                getattr(self, "account_id", None) or getattr(self, "token_file", None)
            )
        return self._quota

    def low_priority_quota_retry_after_seconds(self) -> int:
        """Seconds remaining before low-priority Gmail metadata fetches may run."""
        return int(math.ceil(self._quota_gate().low_priority_retry_after_seconds()))

    def _quota_wait_state(self):
        if not hasattr(self, "_quota_wait_storage"):
            self._quota_wait_storage = threading.local()
        return self._quota_wait_storage

    @property
    def provider_name(self) -> str:
        return self.PROVIDER_NAME

    def _get_server_tokens(self) -> Optional[dict]:
        """
        Récupère les tokens depuis le stockage serveur.

        Returns:
            Token data dict ou None si non trouvé.
        """
        if not self.account_id:
            return None

        try:
            from app.api.oauth import get_tokens_server, _refresh_tokens_server
            import time

            token_data = get_tokens_server(self.account_id)
            if not token_data:
                return None

            # Auto-refresh si nécessaire (5 min buffer)
            expires_at = token_data.get("expires_at", 0)
            if expires_at and time.time() > (expires_at - 5 * 60):
                logger.info(f"Token expirant pour {self.account_id}, rafraîchissement...")
                refreshed = _refresh_tokens_server(self.account_id)
                if refreshed:
                    token_data = refreshed
                elif token_data.get("refresh_token"):
                    # Pre-refresh failed but we have a refresh_token — return as-is
                    # and let google-auth handle the refresh on first API call
                    logger.warning(
                        f"Pré-rafraîchissement échoué pour {self.account_id}, "
                        "utilisation du refresh_token existant"
                    )
                else:
                    logger.error(f"Échec du rafraîchissement pour {self.account_id}")
                    return None

            return token_data

        except Exception as e:
            logger.error(f"Erreur récupération tokens serveur: {e}")
            return None

    def authenticate(self) -> bool:
        """
        Authentifie via Google OAuth2.

        Returns:
            True si l'authentification réussit.
        """
        try:
            creds = None

            # Méthode 0 : Tokens stockés côté serveur (OAuth web)
            if self.account_id:
                server_tokens = self._get_server_tokens()
                if server_tokens:
                    access_token = server_tokens.get("access_token")
                    refresh_token = server_tokens.get("refresh_token")
                    if access_token or refresh_token:
                        creds = Credentials(
                            token=access_token,
                            refresh_token=refresh_token,
                            token_uri="https://oauth2.googleapis.com/token",
                            client_id=self.client_id,
                            client_secret=self.client_secret,
                            scopes=self.SCOPES
                        )
                        logger.info(f"Tokens serveur chargés pour {self.account_id}")

            # Méthode 1 : Token existant dans fichier
            if not creds and self.token_file and os.path.exists(self.token_file):
                try:
                    creds = Credentials.from_authorized_user_file(self.token_file, self.SCOPES)
                except Exception as e:
                    # Fichier corrompu ou vide - le supprimer
                    logger.warning(f"Token invalide, suppression: {e}")
                    os.remove(self.token_file)
                    creds = None

            # Méthode 2 : Refresh token fourni directement
            if not creds and self.refresh_token and self.client_id and self.client_secret:
                creds = Credentials(
                    token=None,
                    refresh_token=self.refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                    scopes=self.SCOPES
                )

            # Rafraîchir si nécessaire (token expiré OU pas encore d'access token)
            # Serialized under a per-token-file lock to prevent two concurrent
            # threads from both calling creds.refresh() and racing on the
            # token.json write (which would produce corrupt JSON → silent logout).
            if creds and creds.refresh_token and (not creds.valid or creds.expired):
                with _get_token_refresh_lock(self.token_file):
                    # Re-check after acquiring lock: another thread may have
                    # already refreshed while we were waiting.
                    if not creds.valid or creds.expired:
                        try:
                            creds.refresh(Request())
                        except Exception as refresh_err:
                            err_str = str(refresh_err)
                            if "invalid_grant" in err_str:
                                # Refresh token définitivement révoqué — supprimer le token local
                                if self.token_file and os.path.exists(self.token_file):
                                    os.remove(self.token_file)
                                    logger.warning(f"Token révoqué (invalid_grant), fichier supprimé: {self.token_file}")
                                raise ValueError(
                                    "Refresh token révoqué (invalid_grant). "
                                    "Reconnectez votre compte Gmail via OAuth."
                                ) from refresh_err
                            raise  # Re-raise other refresh errors
                        # Sauvegarder le token rafraîchi (atomique pour éviter corruption)
                        if self.token_file:
                            _atomic_write_text(self.token_file, creds.to_json())

            # Méthode 3 : Flow OAuth interactif
            if not creds or not creds.valid:
                if self.credentials_file and os.path.exists(self.credentials_file):
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.credentials_file, self.SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                    # Sauvegarder le token atomiquement
                    if self.token_file:
                        with _get_token_refresh_lock(self.token_file):
                            _atomic_write_text(self.token_file, creds.to_json())
                else:
                    raise ValueError(
                        "Authentification impossible. Fournissez credentials.json "
                        "ou GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET + GOOGLE_REFRESH_TOKEN"
                    )

            self._credentials = creds
            # Prefer an HTTP with explicit timeout; fall back to the default
            # (no timeout) build if the dependency isn't available.
            _authed_http = _build_authorized_http(creds)
            if _authed_http is not None:
                self._service = build("gmail", "v1", http=_authed_http, cache_discovery=False)
            else:
                self._service = build("gmail", "v1", credentials=creds)
            self._authenticated = True
            logger.info("[OK] Authentification Gmail réussie")
            return True

        except Exception as e:
            import time
            self._authenticated = False
            self._auth_fail_time = time.time()
            self._auth_fail_reason = str(e)
            logger.error(f"[FAIL] Authentification Gmail échouée: {e}")
            return False

    @property
    def auth_failure_reason(self) -> str:
        """Message du dernier échec d'authentification ("" si aucun).

        `authenticate()` avale toutes les exceptions et renvoie un simple
        False, ce qui confond une révocation définitive (invalid_grant) avec
        un incident réseau. Les appelants qui doivent trancher entre les deux
        — le cron de renouvellement des watch — lisent cette raison plutôt que
        de deviner.
        """
        return self._auth_fail_reason

    def _ensure_authenticated(self) -> None:
        """S'assure que le service est authentifié."""
        if not self._authenticated or not self._service:
            # Cooldown: don't retry auth for 60s after a failure
            import time
            if self._auth_fail_time and (time.time() - self._auth_fail_time) < 60:
                raise RuntimeError(
                    f"Authentification Gmail en cooldown (60s). "
                    f"Raison: {self._auth_fail_reason}"
                )
            if not self.authenticate():
                self._auth_fail_time = time.time()
                raise RuntimeError("Authentification Gmail requise")

    # NOTE: _parse_email_address est fournie par EmailParserMixin

    def _get_header(self, headers: List[dict], name: str) -> str:
        """Récupère un header par son nom, décode les headers MIME si nécessaire."""
        for header in headers:
            if header.get("name", "").lower() == name.lower():
                value = header.get("value", "")
                # Décoder les headers MIME encodés (=?UTF-8?B?...?=)
                if "=?" in value:
                    parts = []
                    for part, charset in decode_mime_header(value):
                        if isinstance(part, bytes):
                            parts.append(part.decode(charset or "utf-8", errors="replace"))
                        else:
                            parts.append(part)
                    return " ".join(parts)
                return value
        return ""

    def _decode_body(self, payload: dict, message_id: str = None) -> tuple:
        """
        Décode le corps d'un email (text et html).

        Gère les structures multipart complexes:
        - multipart/alternative (text/plain + text/html)
        - multipart/mixed (content + attachments)
        - multipart/related (HTML + inline images)
        """
        body_text = ""
        body_html = None
        cid_map = {}

        def decode_text_body(data: str, headers: dict, mime_type: str) -> str:
            raw_bytes = base64.urlsafe_b64decode(data)

            declared_charset = None
            content_type = headers.get("content-type") or mime_type
            if content_type:
                parsed = Message()
                parsed["content-type"] = content_type
                declared_charset = parsed.get_content_charset()

            candidates = []
            for charset in (declared_charset, "utf-8", "windows-1252", "iso-8859-1"):
                if charset and charset.lower() not in candidates:
                    candidates.append(charset.lower())

            for charset in candidates:
                try:
                    return raw_bytes.decode(charset)
                except (LookupError, UnicodeDecodeError):
                    continue

            return raw_bytes.decode("utf-8", errors="replace")

        def extract_parts(part, depth=0):
            nonlocal body_text, body_html
            mime_type = part.get("mimeType", "").lower()
            body_data = part.get("body", {}).get("data", "")

            # Log for debugging complex emails
            if depth == 0:
                logger.debug(f"Root MIME type: {mime_type}")

            # Collect inline images by Content-ID
            part_headers = {
                h["name"].lower(): h["value"]
                for h in part.get("headers", [])
            }
            content_id = part_headers.get("content-id", "")
            if content_id and mime_type.startswith("image/"):
                cid_key = content_id.strip("<>")
                try:
                    if body_data:
                        # Gmail body.data is urlsafe base64 — re-encode to standard base64
                        raw_bytes = base64.urlsafe_b64decode(body_data)
                        b64_data = base64.b64encode(raw_bytes).decode("ascii")
                        cid_map[cid_key] = (mime_type, b64_data)
                    elif part.get("body", {}).get("attachmentId") and message_id:
                        # Fetch attachment data from Gmail API
                        att = self._execute_gmail_request(
                            self._service.users().messages().attachments().get(
                                userId="me",
                                messageId=message_id,
                                id=part["body"]["attachmentId"],
                            ),
                            "messages.attachments.get.inline",
                        )
                        att_data = att.get("data", "")
                        if att_data:
                            raw_bytes = base64.urlsafe_b64decode(att_data)
                            b64_data = base64.b64encode(raw_bytes).decode("ascii")
                            cid_map[cid_key] = (mime_type, b64_data)
                except Exception as e:
                    logger.warning(f"Error extracting CID image {cid_key}: {e}")
                return

            # Direct body data (leaf node)
            if body_data:
                try:
                    decoded = decode_text_body(body_data, part_headers, mime_type)
                    if "text/plain" in mime_type:
                        # Only set if we don't have text yet (prefer first occurrence)
                        if not body_text:
                            body_text = decoded
                    elif "text/html" in mime_type:
                        # Always prefer HTML - overwrite if found
                        body_html = decoded
                        logger.debug(f"Found HTML body at depth {depth}, length: {len(decoded)}")
                except Exception as e:
                    logger.warning(f"Error decoding body part: {e}")

            # Recurse into nested parts
            parts = part.get("parts", [])
            if parts:
                # For multipart/alternative, prefer HTML over plain text
                # Process all parts to find both versions
                for sub_part in parts:
                    extract_parts(sub_part, depth + 1)

        extract_parts(payload)

        # Si pas de texte mais du HTML, extraire le texte du HTML
        if not body_text and body_html:
            body_text = self._extract_text_from_html(body_html)

        # Resolve inline CID images to base64 data URIs
        if body_html and cid_map:
            body_html = self._resolve_cid_images(body_html, cid_map)

        # BUG-Y003 fix: some senders write UTF-8 bytes that have already been
        # mis-encoded as Latin-1 once (classic mojibake — "Université" surfaces
        # as "UniversitÃ©"). Detect the telltale "Ã" / "Â" / "â€" markers and
        # reverse the encoding round-trip. Same heuristic already applied to
        # display names in email_parser_mixin._demojibake; we extend it here
        # to the body text/html that gets rendered in the reader pane.
        body_text = self._demojibake(body_text) or body_text
        if body_html:
            body_html = self._demojibake(body_html) or body_html

        # Log what we found
        logger.debug(f"Decoded body - text: {len(body_text) if body_text else 0} chars, html: {len(body_html) if body_html else 0} chars")

        return body_text.strip(), body_html

    # Noise attachment filenames embedded by email services (not real user attachments)
    _NOISE_ATTACHMENT_NAMES = frozenset({"favicon.ico", "icon.png", "icon.gif", "spacer.gif", "pixel.gif", "blank.gif"})

    @staticmethod
    def _is_noise_attachment(filename: str, size: int) -> bool:
        """Filter out embedded service branding (favicons, tracking pixels, logos)."""
        name_lower = filename.lower()
        if name_lower in GmailAdapter._NOISE_ATTACHMENT_NAMES:
            return True
        # Tiny images (< 3KB) with generic branding names
        if size > 0 and size < 3072:
            import re
            if re.match(r'^(icon|logo|spacer|pixel|tracking|transparent|blank)', name_lower):
                return True
            # Sub-200 byte images are tracking pixels
            if size < 200 and re.search(r'\.(gif|png)$', name_lower):
                return True
        return False

    @staticmethod
    def _is_inline_part(part: dict) -> bool:
        """True si la part est un embed inline (Content-ID) et PAS une vraie
        pièce jointe. Outlook met un Content-ID sur de vraies pièces jointes
        (avec Content-Disposition: attachment) — la disposition prime sur le
        Content-ID, sinon ces fichiers disparaissent de l'email reçu."""
        headers = {
            (h.get("name") or "").lower(): h.get("value") or ""
            for h in part.get("headers", [])
        }
        if headers.get("content-disposition", "").lower().lstrip().startswith("attachment"):
            return False
        return bool(headers.get("content-id"))

    def _check_has_attachments(self, payload: dict) -> bool:
        """Check if a Gmail payload contains real attachments (not just MIME parts)."""
        def _scan(part):
            filename = part.get("filename")
            if not filename:
                for sub in part.get("parts", []):
                    if _scan(sub):
                        return True
                return False
            body = part.get("body", {})
            att_id = body.get("attachmentId")
            if att_id and not GmailAdapter._is_inline_part(part):
                size = body.get("size", 0)
                if not GmailAdapter._is_noise_attachment(filename, size):
                    return True
            for sub in part.get("parts", []):
                if _scan(sub):
                    return True
            return False
        return _scan(payload)

    def _extract_attachment_metadata(self, payload: dict) -> list:
        """Extrait les métadonnées des pièces jointes depuis le payload Gmail."""
        result = []

        def _scan(part):
            filename = part.get("filename")
            body = part.get("body", {})
            att_id = body.get("attachmentId")
            size = body.get("size", 0)
            if filename and att_id and not GmailAdapter._is_inline_part(part):
                # Skip noise attachments (favicons, tracking pixels)
                if not GmailAdapter._is_noise_attachment(filename, size):
                    result.append({
                        "id": att_id,
                        "filename": filename,
                        "size": size,
                        "content_type": part.get("mimeType", "application/octet-stream"),
                    })
            for sub in part.get("parts", []):
                _scan(sub)

        _scan(payload)
        return result

    def download_attachment(self, msg_id: str, att_id: str) -> tuple:
        """Télécharge une pièce jointe Gmail. Retourne (bytes, content_type, filename)."""
        import base64 as _b64
        self._ensure_authenticated()

        # Download attachment data
        att_data = self._execute_gmail_request(
            self._service.users().messages().attachments().get(
                userId="me", messageId=msg_id, id=att_id
            ),
            "messages.attachments.get",
        )
        raw = att_data.get("data", "")
        # Gmail uses URL-safe base64 without padding
        data_bytes = _b64.urlsafe_b64decode(raw + "==")

        # Find filename and content_type from the full message payload
        content_type = "application/octet-stream"
        filename = "attachment"
        try:
            msg = self._execute_gmail_request(
                self._service.users().messages().get(
                    userId="me", id=msg_id, format="full"
                ),
                "messages.get.attachment_metadata",
            )

            def _find(part):
                if part.get("body", {}).get("attachmentId") == att_id:
                    return part
                for sub in part.get("parts", []):
                    found = _find(sub)
                    if found:
                        return found
                return None

            found = _find(msg.get("payload", {}))
            if found:
                content_type = found.get("mimeType", content_type)
                filename = found.get("filename", filename)
        except Exception as _e:
            logger.warning(f"Could not fetch Gmail message metadata for attachment: {_e}")

        return data_bytes, content_type, filename

    def _map_to_standard_email(self, message: dict) -> StandardEmail:
        """Convertit un message Gmail en StandardEmail."""
        payload = message.get("payload", {})
        headers = payload.get("headers", [])

        # Expéditeur
        from_header = self._get_header(headers, "From")
        sender_email, sender_name = self._parse_email_address(from_header)

        # Destinataires (utilise le mixin)
        to_list = self._normalize_recipients(self._get_header(headers, "To"))
        cc_list = self._normalize_recipients(self._get_header(headers, "Cc"))

        # Sujet
        subject = self._get_header(headers, "Subject")

        # Corps
        body_text, body_html = self._decode_body(payload, message_id=message.get("id"))

        # Date
        received_at = None
        date_header = self._get_header(headers, "Date")
        if date_header:
            try:
                from email.utils import parsedate_to_datetime
                received_at = parsedate_to_datetime(date_header)
            except Exception:
                pass

        # Labels pour déterminer is_read
        labels = message.get("labelIds", [])
        is_read = "UNREAD" not in labels

        attachments = self._extract_attachment_metadata(payload)

        # Extract iCal text from MIME parts while payload is available.
        # Small .ics attachments are inlined (no separate attachmentId), so they
        # won't show up via download_attachment; scanning the payload is the only
        # reliable way.  Failures are silent — iCal is non-critical.
        ical_text = None
        try:
            from app.providers.gmail_calendar import _find_ical_text
            ical_text = _find_ical_text(payload, self._service, message.get("id"))
        except Exception:
            pass

        # Extract classification headers for labeling pipeline
        _CLASSIFICATION_HEADER_NAMES = {
            "list-unsubscribe", "precedence", "auto-submitted",
            "x-auto-response-suppress", "x-mailer", "reply-to",
        }
        classification_headers = {}
        for h in headers:
            h_name_lower = h.get("name", "").lower()
            if h_name_lower in _CLASSIFICATION_HEADER_NAMES and h.get("value"):
                classification_headers[h_name_lower] = h["value"]

        return StandardEmail(
            id=message.get("id", ""),
            sender=sender_email,
            sender_name=sender_name,
            to=to_list,
            cc=cc_list,
            subject=subject,
            body=body_text,
            body_html=body_html,
            received_at=received_at,
            is_read=is_read,
            has_attachments=bool(attachments) or self._check_has_attachments(payload),
            attachments=attachments,
            ical_text=ical_text,
            conversation_id=message.get("threadId"),
            provider_source=self.PROVIDER_NAME,
            raw_metadata={
                "labelIds": labels,
                "message_id": self._get_header(headers, "Message-ID"),
                "snippet": message.get("snippet", ""),
                "classification_headers": classification_headers,
            }
        )

    def _batch_fetch_messages(self, message_ids: list[str], format: str = "full", metadata_headers: list[str] = None) -> list[dict]:
        """
        Fetch multiple messages in a single batch HTTP request.

        Gmail Batch API: up to 100 requests per batch.
        Returns list of successfully fetched message dicts (order not guaranteed).

        Includes adaptive throttling to respect Gmail rate limits:
        - Configurable chunk size (default 25, max 100) to stay under quota
        - Configurable inter-chunk delay (default 1.5s) for multi-batch fetches
        - 429 detection in batch callbacks for aggressive throttling
        - Delay increases on errors, decreases on clean successes
        - Circuit breaker after 3 consecutive batch-level failures
        - Mini-batch retry with per-wave backoff (not per-message)
        """
        import time as _time
        from app.config import DEFAULT_CACHE_CONFIG

        if not message_ids:
            return []

        results = []
        failed_ids = []  # Non-429 failures eligible for a small retry.
        rate_limited_ids = []  # 429s must wait for the next sync cycle.

        chunk_size = min(DEFAULT_CACHE_CONFIG.gmail_batch_chunk_size, 100)
        initial_delay = DEFAULT_CACHE_CONFIG.gmail_batch_initial_delay
        total_chunks = (len(message_ids) + chunk_size - 1) // chunk_size
        chunk_delay = initial_delay if total_chunks > 1 else 0.0
        consecutive_batch_failures = 0
        MAX_CONSECUTIVE_FAILURES = 3

        for i in range(0, len(message_ids), chunk_size):
            # Circuit breaker: stop hammering if too many consecutive failures
            if consecutive_batch_failures >= MAX_CONSECUTIVE_FAILURES:
                remaining = len(message_ids) - i
                logger.error(
                    f"Circuit breaker: {consecutive_batch_failures} consecutive batch failures, "
                    f"skipping remaining {remaining} messages (will retry next sync)"
                )
                break

            # Inter-chunk delay (skip first chunk)
            if i > 0 and chunk_delay > 0:
                _time.sleep(chunk_delay)

            chunk = message_ids[i:i + chunk_size]
            batch = self._service.new_batch_http_request()
            _chunk_results = {}
            _chunk_errors = {}
            _chunk_rate_limited = {}

            def _make_callback(msg_id):
                def _cb(request_id, response, exception):
                    if exception is not None:
                        # Detect 429 rate-limit errors separately
                        if isinstance(exception, HttpError) and exception.resp.status == 429:
                            _chunk_rate_limited[msg_id] = exception
                        else:
                            _chunk_errors[msg_id] = exception
                    else:
                        _chunk_results[msg_id] = response
                return _cb

            for msg_id in chunk:
                request_kwargs = {"userId": "me", "id": msg_id, "format": format}
                if metadata_headers and format == "metadata":
                    request_kwargs["metadataHeaders"] = metadata_headers
                batch.add(
                    self._service.users().messages().get(**request_kwargs),
                    callback=_make_callback(msg_id),
                    request_id=msg_id,
                )

            try:
                self._execute_gmail_batch(
                    batch,
                    "messages.batch_get",
                    lambda: list(_chunk_rate_limited.values()),
                )
                consecutive_batch_failures = 0

                # 429s detected in batch callbacks: the account-level quota gate
                # has recorded the server/fallback backoff. Do not immediately
                # retry these IDs individually; that is exactly what amplifies
                # Gmail metadata quota exhaustion.
                if _chunk_rate_limited:
                    logger.warning(
                        f"Batch fetch: {len(_chunk_rate_limited)}/{len(chunk)} "
                        "rate-limited (429), deferring failed IDs to next sync"
                    )
                    rate_limited_ids.extend(_chunk_rate_limited.keys())

                # Adaptive: reduce delay on clean success, mild increase on other errors
                if not _chunk_errors and not _chunk_rate_limited:
                    chunk_delay = max(chunk_delay * 0.7, initial_delay) if total_chunks > 1 else 0.0
                elif _chunk_errors:
                    chunk_delay = min(chunk_delay * 1.5, 8.0)
            except Exception as batch_err:
                consecutive_batch_failures += 1
                # BatchError (e.g. SSL error / "Response not in multipart/mixed format").
                # Do NOT fall back to individual requests: sequential SSL calls after a
                # failed batch overloads the connection pool and causes segfaults on Windows.
                # Skip this chunk — emails will be retried on the next sync cycle.
                logger.warning(
                    f"Batch execute failed ({batch_err}), skipping chunk of {len(chunk)} messages "
                    f"(failure {consecutive_batch_failures}/{MAX_CONSECUTIVE_FAILURES})"
                )
                # Aggressive backoff on batch-level SSL/network failure
                chunk_delay = min(chunk_delay * 2.0 + 1.0, 15.0)
                # Rebuild the service to reset the httplib2 connection pool.
                try:
                    _authed_http = _build_authorized_http(self._credentials)
                    if _authed_http is not None:
                        self._service = build("gmail", "v1", http=_authed_http, cache_discovery=False)
                    else:
                        self._service = build("gmail", "v1", credentials=self._credentials)
                except Exception:
                    pass
                # Sleep after rebuild to let the network settle
                _time.sleep(chunk_delay)
                continue

            results.extend(_chunk_results.values())
            failed_ids.extend(_chunk_errors.keys())

            if _chunk_errors:
                logger.warning(f"Batch fetch: {len(_chunk_errors)}/{len(chunk)} failed")

        if rate_limited_ids:
            logger.warning(
                "Skipped immediate retry for %s Gmail rate-limited messages",
                len(rate_limited_ids),
            )

        # Retry non-429 failed messages in mini-batches with per-wave backoff
        if failed_ids:
            logger.info(f"Retrying {len(failed_ids)} failed messages in mini-batches")
            retry_batch_size = 10
            wave_backoff = max(chunk_delay, 1.0)  # Inherit last known delay (respects 429 ramp-up)
            recovered = []
            still_failed = []

            for ri in range(0, len(failed_ids), retry_batch_size):
                retry_chunk = failed_ids[ri:ri + retry_batch_size]
                _time.sleep(wave_backoff)

                chunk_failures = 0
                for _retry_id in retry_chunk:
                    try:
                        request_kwargs = {"userId": "me", "id": _retry_id, "format": format}
                        if metadata_headers and format == "metadata":
                            request_kwargs["metadataHeaders"] = metadata_headers
                        msg = self._execute_gmail_request(
                            self._service.users().messages().get(**request_kwargs),
                            "messages.get.retry",
                        )
                        if msg:
                            recovered.append(msg)
                    except Exception as retry_err:
                        logger.debug(f"Individual retry failed for {_retry_id}: {retry_err}")
                        chunk_failures += 1
                        still_failed.append(_retry_id)

                # Adjust delay based on mini-batch success rate
                if chunk_failures == 0:
                    wave_backoff = max(wave_backoff * 0.5, 1.0)
                elif chunk_failures > len(retry_chunk) // 2:
                    wave_backoff = min(wave_backoff * 2, 16.0)

            results.extend(recovered)
            if still_failed:
                logger.warning(f"Retry: {len(recovered)} recovered, {len(still_failed)} permanently failed")

        return results

    def get_unread_messages(self, limit: int = 10) -> List[StandardEmail]:
        """Récupère les messages non lus."""
        self._ensure_authenticated()

        try:
            # Rechercher les messages non lus
            results = self._execute_gmail_request(
                self._service.users().messages().list(
                    userId="me",
                    q="is:unread",
                    maxResults=limit,
                ),
                "messages.list.unread",
            )

            messages = results.get("messages", [])
            emails = []

            for msg_ref in messages:
                # Récupérer le message complet
                msg = self._execute_gmail_request(
                    self._service.users().messages().get(
                        userId="me",
                        id=msg_ref["id"],
                        format="full",
                    ),
                    "messages.get.unread",
                )
                emails.append(self._map_to_standard_email(msg))

            return emails

        except HttpError as e:
            logger.error(f"Erreur API Gmail: {e}")
            return []

    def get_messages(self, limit: int = 50, unread_only: bool = False, label_ids: List[str] = None, query: str = None) -> List[StandardEmail]:
        """
        Récupère les messages (tous ou non lus seulement).

        Uses parallel fetching with BatchProcessor for faster loading.

        Args:
            limit: Maximum number of messages.
            unread_only: If True, only fetch unread.
            label_ids: Gmail label IDs to filter by (default: ["INBOX"]).
        """
        self._ensure_authenticated()

        try:
            # Map IMAP-style folder names to Gmail API label IDs
            _IMAP_TO_GMAIL = {
                "[Gmail]/Spam": "SPAM",
                "[Gmail]/Trash": "TRASH",
                "[Gmail]/Sent Mail": "SENT",
                "[Gmail]/Drafts": "DRAFT",
            }
            if label_ids:
                label_ids = [_IMAP_TO_GMAIL.get(lbl, lbl) for lbl in label_ids]

            # Step 1: List message IDs (single fast API call)
            query_params = {
                "userId": "me",
                "maxResults": limit,
                "labelIds": label_ids or ["INBOX"],
            }
            if query:
                query_params["q"] = query
            elif unread_only:
                query_params["q"] = "is:unread"
            # Gmail API excludes spam/trash by default — must opt-in
            if label_ids and any(lbl in ("SPAM", "TRASH") for lbl in label_ids):
                query_params["includeSpamTrash"] = True

            results = self._execute_gmail_request(
                self._service.users().messages().list(**query_params),
                "messages.list",
            )
            message_refs = results.get("messages", [])

            if not message_refs:
                return []

            # Step 2: Fetch message details via Gmail Batch API (up to 100 per batch)
            msg_ids = [ref["id"] for ref in message_refs]
            raw_messages = self._batch_fetch_messages(msg_ids, format="full")

            emails = []
            for msg in raw_messages:
                try:
                    emails.append(self._map_to_standard_email(msg))
                except Exception as e:
                    logger.warning(f"Failed to map message: {e}")

            logger.info(f"Gmail batch fetch: {len(emails)}/{len(message_refs)} messages")

            return emails

        except HttpError as e:
            logger.error(f"Erreur API Gmail: {e}")
            return []

    def get_message_headers(self, limit: int = 50, unread_only: bool = False, folder: Optional[str] = None) -> List[StandardEmail]:
        """
        Fetch email headers only (no body content) - OPTIMIZED for list view.

        Uses format="metadata" which is 50-70% faster than format="full".
        Only fetches headers needed for inbox list rendering.

        Args:
            limit: Maximum number of messages to fetch.
            unread_only: If True, only fetch unread messages.
            folder: Gmail label to fetch from (default: INBOX).

        Returns:
            List of StandardEmail with headers populated (body will be empty).
        """
        self._ensure_authenticated()

        try:
            import time as _time
            start_time = _time.time()

            # Map folder names to Gmail labels
            label_mapping = {
                "INBOX": ["INBOX"],
                "[Gmail]/Sent Mail": ["SENT"],
                "[Gmail]/Spam": ["SPAM"],
                "[Gmail]/Trash": ["TRASH"],
                "[Gmail]/Drafts": ["DRAFT"],
            }

            # Step 1: List message IDs (single fast API call)
            query_params = {
                "userId": "me",
                "maxResults": limit,
            }

            # Set label filter based on folder
            target_folder = folder or "INBOX"
            _q_parts = []
            if unread_only:
                _q_parts.append("is:unread")

            if target_folder == "[Gmail]/All Mail":
                # Archivé = pas dans inbox, sent, spam, trash — ni drafts.
                # QA 2026-06-10 : sans `-in:drafts`, ce chemin (listing
                # headers) remplissait le dossier "archived" du cache SQLite
                # avec les brouillons "(Sans objet)", alors que l'autre
                # chemin (get_archived_emails, ligne ~2945) les exclut. Les
                # deux syncs se réécrivaient mutuellement → la vue Archives
                # changeait de contenu à chaque refresh.
                _q_parts.append("-in:inbox -in:sent -in:spam -in:trash -in:drafts")
            elif target_folder in label_mapping:
                query_params["labelIds"] = label_mapping[target_folder]
            else:
                query_params["labelIds"] = ["INBOX"]

            if _q_parts:
                query_params["q"] = " ".join(_q_parts)
            # Gmail API excludes spam/trash by default — must opt-in
            if target_folder in ("[Gmail]/Spam", "[Gmail]/Trash"):
                query_params["includeSpamTrash"] = True

            results = self._execute_gmail_request(
                self._service.users().messages().list(**query_params),
                "messages.list.headers",
            )
            message_refs = results.get("messages", [])

            if not message_refs:
                return []

            # Step 2: Fetch message metadata via Gmail Batch API (OPTIMIZED)
            msg_ids = [ref["id"] for ref in message_refs]
            raw_messages = self._batch_fetch_messages(
                msg_ids, format="metadata",
                # Audit 2026-06-13: include the decisive bulk-mail RFC headers so
                # the rules-only labeler can fire List-Unsubscribe / Precedence /
                # Auto-Submitted → Noise even on the fast header-only fetch.
                metadata_headers=[
                    "From", "To", "Subject", "Date", "Message-ID",
                    "List-Unsubscribe", "Precedence", "Auto-Submitted",
                ]
            )

            emails = []
            for msg in raw_messages:
                try:
                    emails.append(self._map_metadata_to_standard_email(msg))
                except Exception as e:
                    logger.warning(f"Failed to map metadata: {e}")

            elapsed = _time.time() - start_time
            logger.info(
                f"Gmail header-only batch fetch: {len(emails)}/{len(message_refs)} "
                f"in {elapsed:.2f}s (optimized)"
            )

            return emails

        except HttpError as e:
            logger.error(f"Gmail metadata fetch error: {e}")
            return []
        except Exception as e:
            logger.error(f"Gmail metadata fetch unexpected error: {type(e).__name__}: {e}")
            return []

    def _map_metadata_to_standard_email(self, msg: dict) -> StandardEmail:
        """
        Map Gmail metadata response to StandardEmail (no body).

        Optimized version of _map_to_standard_email for list view.
        """
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

        # Parse sender
        from_header = headers.get("From", "")
        sender_email, sender_name = self._parse_email_address(from_header)

        # Parse date
        date_str = headers.get("Date", "")
        received_at = None
        if date_str:
            try:
                from email.utils import parsedate_to_datetime
                received_at = parsedate_to_datetime(date_str)
            except (ValueError, TypeError):
                pass

        # Check read status from labels
        labels = msg.get("labelIds", [])
        is_read = "UNREAD" not in labels

        # Get snippet as body preview
        snippet = msg.get("snippet", "")

        # Surface the bulk-mail RFC headers (lowercased keys, matching the
        # full-fetch path) so the rules-only labeler can fire List-Unsubscribe /
        # Precedence / Auto-Submitted → Noise without a full body fetch.
        _classification_headers = {
            name.lower(): headers[name]
            for name in ("List-Unsubscribe", "Precedence", "Auto-Submitted", "X-Auto-Response-Suppress")
            if headers.get(name)
        }

        return StandardEmail(
            id=msg["id"],
            subject=headers.get("Subject", "(No Subject)"),
            sender=sender_email or from_header,
            sender_name=sender_name,
            body="",  # Empty body for header-only fetch
            body_html=None,
            received_at=received_at,
            is_read=is_read,
            # Inspect the actual part metadata (filename + body.attachmentId, no
            # Content-ID) instead of trusting the root mimeType. The old
            # `"multipart/mixed" in mimeType` test showed a false paperclip on
            # inline-only emails (multipart/mixed root, no real attachment) and
            # missed attachments under multipart/signed|related roots. If the
            # metadata payload lacks part detail, this returns False and the
            # detail-open backfill corrects it — strictly better than over-eager.
            has_attachments=self._check_has_attachments(msg.get("payload", {})),
            conversation_id=msg.get("threadId"),
            provider_source=self.PROVIDER_NAME,
            raw_metadata={
                "message_id": headers.get("Message-ID", ""),
                "header_only": True,
                "snippet": snippet,
                "classification_headers": _classification_headers,
            }
        )

    def search_emails(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
        include_body: bool = True,
    ) -> List[StandardEmail]:
        """
        Recherche des emails avec une requête Gmail.

        Args:
            query: Requête de recherche Gmail (ex: "from:user@example.com")
            limit: Nombre maximum de résultats
            offset: Décalage pour la pagination (découpe côté Python)
            include_body: Si False, ne charge que les headers + snippet.

        Returns:
            Liste des emails correspondant à la recherche.
        """
        self._ensure_authenticated()

        try:
            # Si offset > 0, on doit fetcher offset + limit résultats puis découper
            max_results = min(offset + limit, 500) if offset > 0 else limit
            query_params = {
                "userId": "me",
                "maxResults": max_results,
                "q": query,
            }

            results = self._execute_gmail_request(
                self._service.users().messages().list(**query_params),
                "messages.list.search",
            )
            messages = results.get("messages", [])

            # Batch fetch full message details
            msg_ids = [ref["id"] for ref in messages]
            if include_body:
                raw_messages = self._batch_fetch_messages(msg_ids, format="full")
            else:
                raw_messages = self._batch_fetch_messages(
                    msg_ids,
                    format="metadata",
                    metadata_headers=["From", "To", "Subject", "Date", "Message-ID"],
                )

            emails = []
            for msg in raw_messages:
                try:
                    if include_body:
                        emails.append(self._map_to_standard_email(msg))
                    else:
                        emails.append(self._map_metadata_to_standard_email(msg))
                except Exception as e:
                    logger.warning(f"Failed to map search result: {e}")

            # Appliquer offset + limit
            if offset > 0:
                emails = emails[offset:offset + limit]
            else:
                emails = emails[:limit]

            logger.info(
                f"Search '{query}' returned {len(emails)} emails "
                f"(offset={offset}, include_body={include_body})"
            )
            return emails

        except HttpError as e:
            logger.error(f"Gmail search error: {e}")
            return []

    def get_message_by_id(self, message_id: str) -> Optional[StandardEmail]:
        """Récupère un message par son ID."""
        self._ensure_authenticated()

        try:
            msg = self._execute_gmail_request(
                self._service.users().messages().get(
                    userId="me",
                    id=message_id,
                    format="full",
                ),
                "messages.get",
            )
            return self._map_to_standard_email(msg)

        except HttpError as e:
            if e.resp.status == 404:
                logger.warning(f"Message non trouvé: {message_id}")
            elif e.resp.status == 400:
                logger.warning(f"ID message invalide (ignoré): {message_id}")
            else:
                logger.error(f"Erreur récupération message {message_id}: {e}")
            return None

    def get_thread_messages(self, thread_id: str) -> List[StandardEmail]:
        """Fetch all messages in a Gmail thread via threads().get() API.

        Returns all messages (read + unread, inbox + sent + archived) in a single call.
        """
        self._ensure_authenticated()
        try:
            thread = self._execute_gmail_request(
                self._service.users().threads().get(
                    userId="me",
                    id=thread_id,
                    format="full",
                ),
                "threads.get",
            )
            emails = []
            for msg in thread.get("messages", []):
                try:
                    emails.append(self._map_to_standard_email(msg))
                except Exception as e:
                    logger.warning(f"Failed to map thread message: {e}")
            return emails
        except HttpError as e:
            logger.error(f"Error fetching thread {thread_id}: {e}")
            return []

    def _get_reply_metadata(self, message_id: str) -> Optional[dict]:
        """Fetch only threadId + Message-ID header for reply threading (lightweight)."""
        try:
            msg = self._execute_gmail_request(
                self._service.users().messages().get(
                    userId="me",
                    id=message_id,
                    format="metadata",
                    metadataHeaders=["Message-ID"],
                ),
                "messages.get.reply_metadata",
            )
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            return {
                "thread_id": msg.get("threadId"),
                "message_id_header": headers.get("Message-ID"),
            }
        except HttpError as e:
            logger.warning(f"Failed to fetch reply metadata for {message_id}: {e}")
            return None

    def _create_message(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        is_html: bool = False,
        reply_to_id: Optional[str] = None,
        attachments: Optional[List[Tuple[str, bytes, str]]] = None,
        reply_metadata: Optional[dict] = None,
        from_name: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """Crée un message MIME."""
        if attachments:
            # mixed container: body + attachments
            msg = MIMEMultipart("mixed")
            if is_html:
                msg.attach(MIMEText(body, "html"))
            else:
                msg.attach(MIMEText(body))
            for filename, data, content_type in attachments:
                maintype, subtype = content_type.split("/", 1) if "/" in content_type else ("application", "octet-stream")
                part = MIMEBase(maintype, subtype)
                part.set_payload(data)
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
            msg["From"] = from_name

        if cc:
            msg["Cc"] = ", ".join(cc)

        if bcc:
            msg["Bcc"] = ", ".join(bcc)

        if idempotency_key:
            message_id = idempotency_key.strip()
            if not message_id.startswith("<"):
                message_id = f"<{message_id}>"
            msg["Message-ID"] = message_id
            msg["X-Agentys-Idempotency-Key"] = idempotency_key

        # Headers pour reply (use pre-fetched metadata to avoid extra API call)
        if reply_to_id:
            mid = reply_metadata.get("message_id_header") if reply_metadata else None
            if not mid and reply_metadata is None:
                # Fallback only when the caller did not already decide how to
                # thread the reply. send_reply_directly can pass threadId-only
                # metadata to avoid an extra messages.get before messages.send.
                meta = self._get_reply_metadata(reply_to_id)
                mid = meta.get("message_id_header") if meta else None
            if mid:
                msg["In-Reply-To"] = mid
                msg["References"] = mid

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        return {"raw": raw}

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
        thread_id: Optional[str] = None,
        from_name: Optional[str] = None,
    ) -> Optional[str]:
        """Crée un brouillon."""
        self._last_error = ""
        self._ensure_authenticated()

        try:
            # Fetch reply metadata ONCE (for both In-Reply-To header and threadId)
            reply_metadata = None
            if reply_to_id:
                reply_metadata = self._get_reply_metadata(reply_to_id)

            message = self._create_message(
                to=to,
                subject=subject,
                body=body,
                cc=cc,
                bcc=bcc,
                is_html=is_html,
                reply_to_id=reply_to_id,
                attachments=attachments,
                reply_metadata=reply_metadata,
                from_name=from_name,
            )

            # Si c'est une réponse, ajouter le threadId
            draft_body = {"message": message}
            resolved_thread_id = thread_id
            if not resolved_thread_id and reply_metadata:
                resolved_thread_id = reply_metadata.get("thread_id")
            if resolved_thread_id:
                draft_body["message"]["threadId"] = resolved_thread_id

            try:
                draft = self._execute_gmail_request(
                    self._service.users().drafts().create(
                        userId="me",
                        body=draft_body
                    ),
                    "drafts.create",
                )
                return draft.get("id")
            except HttpError as e:
                if resolved_thread_id and e.resp.status in (400, 404):
                    # ThreadId may be invalid (email archived/moved) — retry without it
                    logger.warning(f"Erreur création brouillon avec threadId ({e.resp.status}), retry sans threadId")
                    draft_body_no_thread = {"message": message.copy()}
                    draft_body_no_thread["message"].pop("threadId", None)
                    draft2 = self._execute_gmail_request(
                        self._service.users().drafts().create(
                            userId="me",
                            body=draft_body_no_thread
                        ),
                        "drafts.create.retry_without_thread",
                    )
                    return draft2.get("id")
                raise

        except HttpError as e:
            logger.error(f"Erreur création brouillon: {e}")
            self._last_error = str(e)
            return None

    def send_draft(self, draft_id: str) -> bool:
        """Envoie un brouillon."""
        self._ensure_authenticated()

        try:
            self._execute_gmail_request(
                self._service.users().drafts().send(
                    userId="me",
                    body={"id": draft_id}
                ),
                "drafts.send",
            )
            return True

        except Exception as e:
            logger.error(f"Erreur envoi brouillon: {e}", exc_info=True)
            return False

    def send_reply_directly(
        self,
        to: List[str],
        subject: str,
        body: str,
        reply_to_id: str,
        cc: Optional[List[str]] = None,
        attachments: Optional[List[Tuple[str, bytes, str]]] = None,
        thread_id: Optional[str] = None,
        message_id_header: Optional[str] = None,
        is_html: bool = False,
        idempotency_key: Optional[str] = None,
    ) -> Optional[str]:
        """
        Send a reply in ONE Gmail API call (messages.send) instead of
        create_draft + send_draft (2 calls). Saves ~500-1000ms.

        Returns the sent message ID on success, None on failure.
        """
        self._last_error = ""
        self._ensure_authenticated()

        try:
            # Gmail's threading contract requires both the provider threadId
            # and RFC reply headers. If the caller only has threadId from the
            # cached row, fetch the lightweight Message-ID metadata before
            # sending instead of asking Gmail to infer the thread.
            reply_metadata = {
                "thread_id": thread_id,
                "message_id_header": message_id_header,
            }
            if not thread_id or not message_id_header:
                fetched_metadata = self._get_reply_metadata(reply_to_id)
                if fetched_metadata:
                    if not reply_metadata["thread_id"]:
                        reply_metadata["thread_id"] = fetched_metadata.get("thread_id")
                    if not reply_metadata["message_id_header"]:
                        reply_metadata["message_id_header"] = fetched_metadata.get("message_id_header")

            message = self._create_message(
                to=to,
                subject=subject,
                body=body,
                cc=cc,
                is_html=is_html,
                reply_to_id=reply_to_id,
                attachments=attachments,
                reply_metadata=reply_metadata,
                idempotency_key=idempotency_key,
            )

            # Resolve threadId
            resolved_thread_id = reply_metadata.get("thread_id")
            if resolved_thread_id:
                message["threadId"] = resolved_thread_id

            _send_t0 = time.perf_counter()
            result = self._execute_gmail_request(
                self._service.users().messages().send(
                    userId="me",
                    body=message,
                ),
                "messages.send.reply",
            )
            _send_ms = int((time.perf_counter() - _send_t0) * 1000)
            _log = logger.warning if _send_ms >= 5000 else logger.info
            _log(
                "[PERF-SEND] phase=gmail_messages_send_done operation=reply "
                "account_key=%s to_count=%s cc_count=%s attachments=%s "
                "thread_id_present=%s message_id_header_present=%s ms=%s",
                getattr(self, "account_id", None) or "local",
                len(to or []),
                len(cc or []),
                len(attachments or []),
                bool(resolved_thread_id),
                bool(reply_metadata.get("message_id_header")),
                _send_ms,
            )
            return result.get("id")

        except Exception as e:
            if "_send_t0" in locals():
                logger.warning(
                    "[PERF-SEND] phase=gmail_messages_send_error operation=reply "
                    "account_key=%s ms=%s error_type=%s",
                    getattr(self, "account_id", None) or "local",
                    int((time.perf_counter() - _send_t0) * 1000),
                    type(e).__name__,
                )
            logger.error(f"Erreur envoi direct: {e}", exc_info=True)
            self._last_error = str(e)
            return None

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
        """
        Send a new message in ONE Gmail API call (messages.send) instead of
        create_draft + send_draft (2 calls). Returns message ID or None.
        After a successful send, ``self._last_sent_thread_id`` holds the
        Gmail threadId for the new message (used by the followup tracker
        to pair sent messages with incoming replies).
        """
        self._last_error = ""
        self._last_sent_thread_id = ""
        self._ensure_authenticated()

        try:
            message = self._create_message(
                to=to,
                subject=subject,
                body=body,
                cc=cc,
                bcc=bcc,
                is_html=is_html,
                attachments=attachments,
                from_name=from_name,
                idempotency_key=idempotency_key,
            )

            _send_t0 = time.perf_counter()
            result = self._execute_gmail_request(
                self._service.users().messages().send(
                    userId="me",
                    body=message,
                ),
                "messages.send.new",
            )
            _send_ms = int((time.perf_counter() - _send_t0) * 1000)
            _log = logger.warning if _send_ms >= 5000 else logger.info
            _log(
                "[PERF-SEND] phase=gmail_messages_send_done operation=new "
                "account_key=%s to_count=%s cc_count=%s bcc_count=%s "
                "attachments=%s ms=%s",
                getattr(self, "account_id", None) or "local",
                len(to or []),
                len(cc or []),
                len(bcc or []),
                len(attachments or []),
                _send_ms,
            )
            # Stash the threadId so callers (followup tracker) can pair the
            # sent message back to incoming replies later.
            self._last_sent_thread_id = result.get("threadId") or ""
            return result.get("id")

        except Exception as e:
            if "_send_t0" in locals():
                logger.warning(
                    "[PERF-SEND] phase=gmail_messages_send_error operation=new "
                    "account_key=%s ms=%s error_type=%s",
                    getattr(self, "account_id", None) or "local",
                    int((time.perf_counter() - _send_t0) * 1000),
                    type(e).__name__,
                )
            logger.error(f"[FAIL] send_new_directly: {e}", exc_info=True)
            self._last_error = str(e)
            return None

    def find_sent_message_by_idempotency_key(self, idempotency_key: str) -> Optional[str]:
        """Return a sent Gmail message ID carrying the scheduled-send Message-ID."""
        self._ensure_authenticated()
        message_id = (idempotency_key or "").strip()
        if not message_id:
            return None
        if not message_id.startswith("<"):
            message_id = f"<{message_id}>"
        try:
            result = self._execute_gmail_request(
                self._service.users().messages().list(
                    userId="me",
                    q=f"rfc822msgid:{message_id} in:sent",
                    maxResults=1,
                ),
                "messages.list.sent_idempotency",
            )
        except HttpError as e:
            logger.warning("Gmail sent idempotency lookup failed: %s", e)
            return None
        messages = result.get("messages") or []
        if not messages:
            return None
        return messages[0].get("id")

    def mark_as_read(self, message_id: str) -> bool:
        """Marque un message comme lu."""
        if not _is_gmail_message_id(message_id):
            # Synthetic IDs (email-N, demo fixtures, draft-* etc.) leak
            # from QuickSteps preview / fixture flows. Don't burn quota
            # on Gmail just to receive a guaranteed 400.
            logger.debug("mark_as_read: skipping non-Gmail id %r", message_id)
            return False
        self._ensure_authenticated()

        try:
            self._execute_gmail_request(
                self._service.users().messages().modify(
                    userId="me",
                    id=message_id,
                    body={"removeLabelIds": ["UNREAD"]}
                ),
                "messages.modify.mark_read",
            )
            return True

        except HttpError as e:
            if e.resp.status in (404, 403):
                logger.warning(f"Erreur marquage message: {e.resp.status} - {message_id}")
            else:
                logger.error(f"Erreur marquage message: {e}")
            return False

    def mark_as_unread(self, message_id: str) -> bool:
        """Marque un message comme non lu."""
        if not _is_gmail_message_id(message_id):
            logger.debug("mark_as_unread: skipping non-Gmail id %r", message_id)
            return False
        self._ensure_authenticated()

        try:
            self._execute_gmail_request(
                self._service.users().messages().modify(
                    userId="me",
                    id=message_id,
                    body={"addLabelIds": ["UNREAD"]}
                ),
                "messages.modify.mark_unread",
            )
            return True

        except HttpError as e:
            if e.resp.status in (404, 403):
                logger.warning(f"Erreur marquage message non lu: {e.resp.status} - {message_id}")
            else:
                logger.error(f"Erreur marquage message non lu: {e}")
            return False

    def _get_or_create_label(self, label_name: str) -> Optional[str]:
        """
        Récupère l'ID d'un label, ou le crée s'il n'existe pas.

        Args:
            label_name: Nom du label (ex: "Agentys/URGENT").

        Returns:
            L'ID du label ou None en cas d'erreur.
        """
        self._ensure_authenticated()

        try:
            # Lister les labels existants
            results = self._execute_gmail_request(
                self._service.users().labels().list(userId="me"),
                "labels.list",
            )
            labels = results.get("labels", [])

            # Chercher le label
            for label in labels:
                if label.get("name") == label_name:
                    return label.get("id")

            # Créer le label s'il n'existe pas
            label_body = {
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show"
            }

            created = self._execute_gmail_request(
                self._service.users().labels().create(
                    userId="me",
                    body=label_body
                ),
                "labels.create",
            )

            logger.info(f"Label créé: {label_name}")
            return created.get("id")

        except HttpError as e:
            logger.error(f"Erreur gestion label: {e}")
            return None

    def apply_label(self, message_id: str, label: str) -> bool:
        """
        Applique un label à un message Gmail.

        Args:
            message_id: ID du message.
            label: Nom du label (sera préfixé par "Agentys/").

        Returns:
            True si le label a été appliqué.
        """
        self._ensure_authenticated()

        # Préfixer le label pour éviter les conflits
        full_label = f"Agentys/{label}"

        try:
            # Récupérer ou créer le label
            label_id = self._get_or_create_label(full_label)
            if not label_id:
                return False

            # Appliquer le label au message
            self._execute_gmail_request(
                self._service.users().messages().modify(
                    userId="me",
                    id=message_id,
                    body={"addLabelIds": [label_id]}
                ),
                "messages.modify.apply_label",
            )

            logger.debug(f"Label '{full_label}' appliqué au message {message_id}")
            return True

        except HttpError as e:
            logger.error(f"Erreur application label: {e}")
            return False

    def move_to_spam(self, message_id: str) -> bool:
        """
        Déplace un message vers le dossier spam.

        Args:
            message_id: ID du message Gmail.

        Returns:
            True si le déplacement a réussi.
        """
        self._ensure_authenticated()

        try:
            self._execute_gmail_request(
                self._service.users().messages().modify(
                    userId="me",
                    id=message_id,
                    body={"addLabelIds": ["SPAM"], "removeLabelIds": ["INBOX"]}
                ),
                "messages.modify.move_to_spam",
            )
            logger.debug(f"Message {message_id} déplacé vers spam")
            return True
        except HttpError as e:
            logger.error(f"Erreur déplacement vers spam: {e}")
            return False

    def move_to_inbox(self, message_id: str) -> bool:
        """
        Déplace un message du spam vers la boîte de réception.

        Args:
            message_id: ID du message Gmail (ou IMAP UID — converti).

        Returns:
            True si le déplacement a réussi, False si l'ID ne peut pas être
            résolu en Gmail message ID (cas IMAP UID sans fallback).
        """
        self._ensure_authenticated()

        # Parity with delete_email: convert IMAP UID → Gmail ID when needed.
        gmail_id = self._resolve_gmail_id(message_id)
        if gmail_id is None:
            logger.warning(f"Cannot resolve message ID {message_id} for Gmail API move_to_inbox")
            return False

        try:
            self._execute_gmail_request(
                self._service.users().messages().modify(
                    userId="me",
                    id=gmail_id,
                    body={"addLabelIds": ["INBOX"], "removeLabelIds": ["SPAM"]}
                ),
                "messages.modify.move_to_inbox",
            )
            logger.debug(f"Message {gmail_id} déplacé vers la boîte de réception")
            return True
        except HttpError as e:
            if e.resp.status == 404:
                logger.warning(f"Message {gmail_id} introuvable dans Gmail API (404) — déjà déplacé")
            else:
                logger.error(f"Erreur déplacement vers inbox: {e}")
            raise

    def restore_from_trash(self, message_id: str) -> bool:
        """
        Restaure un message de la corbeille vers la boîte de réception.

        Utilise l'API Gmail untrash pour retirer le message de TRASH.

        Args:
            message_id: ID du message Gmail.

        Returns:
            True si la restauration a réussi.
        """
        self._ensure_authenticated()

        try:
            self._execute_gmail_request(
                self._service.users().messages().untrash(
                    userId="me",
                    id=message_id
                ),
                "messages.untrash",
            )
            logger.debug(f"Message {message_id} restauré depuis la corbeille")
            return True
        except HttpError as e:
            logger.error(f"Erreur restauration depuis corbeille: {e}")
            raise

    def _resolve_gmail_id(self, message_id: str) -> str | None:
        """Resolve an IMAP UID to a Gmail message ID if needed.

        Gmail API message IDs are hex strings (e.g. '18e5f1a2b3c4d5e6').
        IMAP UIDs are numeric (e.g. '14084'). When the app fetches via IMAP
        but deletes via Gmail API, we need to convert.
        """
        # If already a Gmail-style hex ID, return as-is
        if not message_id.isdigit():
            return message_id

        # Numeric ID = IMAP UID — search Gmail by UID to find the real message ID
        try:
            # Gmail X-GM-MSGID is NOT the same as IMAP UID.
            # Use rfc822msgid search if available, or list recent messages.
            # Simplest: search by Gmail internal "rfc822msgid" won't work without it.
            # Fallback: use IMAP adapter to get Message-ID header, then search Gmail.
            logger.warning(f"Received IMAP UID {message_id} for Gmail API — attempting IMAP fallback")
            return None
        except Exception as e:
            logger.error(f"Failed to resolve IMAP UID {message_id} to Gmail ID: {e}")
            return None

    def delete_email(self, message_id: str) -> bool:
        """
        Supprime un email en le déplaçant vers la corbeille.

        Utilise l'API Gmail trash pour déplacer le message vers TRASH.
        Le message sera définitivement supprimé après 30 jours.

        Args:
            message_id: ID du message Gmail ou IMAP UID.

        Returns:
            True si la suppression a réussi.
        """
        self._ensure_authenticated()

        # Resolve IMAP UID to Gmail ID if needed
        gmail_id = self._resolve_gmail_id(message_id)
        if gmail_id is None:
            logger.warning(f"Cannot resolve message ID {message_id} for Gmail API — falling back to IMAP delete")
            return self._imap_delete_fallback(message_id)

        try:
            self._execute_gmail_request(
                self._service.users().messages().trash(
                    userId="me",
                    id=gmail_id
                ),
                "messages.trash",
            )
            logger.info(f"Message {gmail_id} déplacé vers la corbeille via Gmail API")
            return True
        except HttpError as e:
            if e.resp.status == 404:
                logger.warning(f"Message {gmail_id} introuvable dans Gmail API (404)")
            elif e.resp.status == 403:
                logger.warning(f"Erreur suppression email (scopes insuffisants): {gmail_id}")
            else:
                logger.error(f"Erreur suppression email: {e}")
            raise

    def _imap_delete_fallback(self, imap_uid: str) -> bool:
        """Delete via IMAP when we only have an IMAP UID (not a Gmail message ID)."""
        import imaplib
        import re
        try:
            host = os.getenv("IMAP_HOST", "imap.gmail.com")
            user = os.getenv("IMAP_USER", "")
            password = os.getenv("IMAP_PASSWORD", "")

            if not user or not password:
                logger.warning("IMAP credentials not available for fallback delete")
                return False

            conn = imaplib.IMAP4_SSL(host, 993, timeout=15)
            conn.login(user, password)
            conn.select("INBOX")

            # Auto-detect trash folder name via IMAP flags
            trash_folder = None
            status, folder_list = conn.list()
            if status == "OK" and folder_list:
                for entry in folder_list:
                    raw = entry.decode() if isinstance(entry, bytes) else str(entry)
                    if "\\Trash" in raw.split(")")[0]:
                        m = re.search(r'"([^"]+)"\s*$', raw)
                        if m:
                            trash_folder = m.group(1)
                            break

            if not trash_folder:
                logger.warning("[DELETE] IMAP fallback: could not detect trash folder")
                conn.logout()
                return False

            result = conn.uid('copy', imap_uid.encode(), trash_folder)
            if result[0] == "OK":
                conn.uid('store', imap_uid, "+FLAGS", "\\Deleted")
                conn.expunge()
                logger.info(f"[DELETE] IMAP fallback: UID {imap_uid} moved to {trash_folder}")
                conn.logout()
                return True

            logger.warning(f"[DELETE] IMAP fallback COPY failed for UID {imap_uid}: {result}")
            conn.logout()
            return False
        except Exception as e:
            logger.error(f"[DELETE] IMAP fallback error for UID {imap_uid}: {e}")
            return False

    def permanently_delete(self, message_id: str) -> bool:
        """
        Supprime définitivement un email (pas de corbeille).

        Args:
            message_id: ID du message Gmail.

        Returns:
            True si la suppression a réussi.

        Raises:
            InsufficientScopeError: le token n'a pas le scope complet
                ``https://mail.google.com/`` exigé par messages.delete.
                Permanent — l'appelant doit désactiver l'opération pour ce
                compte, pas re-tenter (audit 2026-06-09 : 2 107 retries 403).
        """
        self._ensure_authenticated()

        try:
            self._execute_gmail_request(
                self._service.users().messages().delete(
                    userId="me",
                    id=message_id
                ),
                "messages.delete",
            )
            logger.debug(f"Message {message_id} supprimé définitivement")
            return True
        except HttpError as e:
            status = getattr(getattr(e, "resp", None), "status", None)
            if status == 403 and "insufficient" in str(e).lower():
                raise InsufficientScopeError(
                    "messages.delete exige le scope complet "
                    "https://mail.google.com/ (non demandé par l'app)",
                    required_scope="https://mail.google.com/",
                ) from e
            logger.error(f"Erreur suppression définitive: {e}")
            return False

    def batch_modify_labels(self, message_ids: List[str],
                            add_label_ids: List[str] = None,
                            remove_label_ids: List[str] = None) -> int:
        """
        Modifie les labels de plusieurs messages en un seul appel API.

        Utilise batchModify (scope gmail.modify, jusqu'à 1000 messages).

        Args:
            message_ids: Liste des IDs Gmail.
            add_label_ids: Labels à ajouter (ex: ["TRASH", "INBOX"]).
            remove_label_ids: Labels à retirer (ex: ["SPAM"]).

        Returns:
            Nombre de messages traités avec succès.
        """
        if not message_ids:
            return 0

        self._ensure_authenticated()

        body = {"ids": message_ids}
        if add_label_ids:
            body["addLabelIds"] = add_label_ids
        if remove_label_ids:
            body["removeLabelIds"] = remove_label_ids

        # batchModify handles up to 1000 IDs per call
        total = 0
        for i in range(0, len(message_ids), 1000):
            chunk = message_ids[i:i + 1000]
            try:
                self._execute_gmail_request(
                    self._service.users().messages().batchModify(
                        userId="me",
                        body={**body, "ids": chunk}
                    ),
                    "messages.batchModify",
                )
                total += len(chunk)
                logger.info(f"batchModify: {len(chunk)} messages traités")
            except HttpError as e:
                logger.error(f"batchModify error: {e}")

        return total

    def archive_email(self, message_id: str) -> bool:
        """
        Archive un email en retirant le label INBOX.

        L'email reste dans All Mail mais n'apparaît plus dans la boîte de réception.

        Args:
            message_id: ID du message Gmail.

        Returns:
            True si l'archivage a réussi.
        """
        self._ensure_authenticated()

        try:
            self._execute_gmail_request(
                self._service.users().messages().modify(
                    userId="me",
                    id=message_id,
                    body={"removeLabelIds": ["INBOX"]}
                ),
                "messages.modify.archive",
            )
            logger.debug(f"Message {message_id} archivé")
            return True
        except HttpError as e:
            if e.resp.status == 404:
                logger.debug(f"Message {message_id} déjà archivé/introuvable — considéré comme succès")
                return True
            if e.resp.status == 403:
                logger.warning(f"Erreur archivage email (scopes insuffisants): {message_id}")
            else:
                logger.error(f"Erreur archivage email: {e}")
            return False

    def _create_draft_standard_email(
        self, draft_id: str, message: dict, base_email: StandardEmail
    ) -> StandardEmail:
        """
        Crée un StandardEmail à partir des données d'un brouillon.

        Refactoring: Extract Method (Fowler) - Duplicated Code
        Cette méthode factorise la création de StandardEmail pour les brouillons,
        évitant la duplication entre get_user_drafts et get_draft_by_id.

        Args:
            draft_id: Identifiant du brouillon Gmail.
            message: Données du message brut.
            base_email: Email de base obtenu via _map_to_standard_email.

        Returns:
            StandardEmail avec les métadonnées de brouillon.
        """
        return StandardEmail(
            id=draft_id,
            sender=base_email.sender,
            sender_name=base_email.sender_name,
            to=base_email.to,
            cc=base_email.cc,
            subject=base_email.subject,
            body=base_email.body,
            body_html=base_email.body_html,
            received_at=base_email.received_at,
            is_read=base_email.is_read,
            has_attachments=base_email.has_attachments,
            conversation_id=base_email.conversation_id,
            provider_source=self.PROVIDER_NAME,
            raw_metadata={
                **base_email.raw_metadata,
                "is_user_draft": True,
                "draft_id": draft_id,
                "message_id": message.get("id", "")
            }
        )

    def get_user_drafts(self, limit: int = 50) -> List[StandardEmail]:
        """
        Récupère les brouillons de l'utilisateur.

        Args:
            limit: Nombre maximum de brouillons.

        Returns:
            Liste de StandardEmail représentant les brouillons.
        """
        self._ensure_authenticated()

        try:
            # Lister les brouillons
            results = self._execute_gmail_request(
                self._service.users().drafts().list(
                    userId="me",
                    maxResults=limit
                ),
                "drafts.list",
            )

            drafts_list = results.get("drafts", [])
            drafts = []

            # Batch fetch is not directly available for drafts.get, use sequential
            # but limit overhead with error handling
            for draft_ref in drafts_list:
                try:
                    draft = self._execute_gmail_request(
                        self._service.users().drafts().get(
                            userId="me",
                            id=draft_ref["id"],
                            format="full"
                        ),
                        "drafts.get",
                    )
                    message = draft.get("message", {})
                    base_email = self._map_to_standard_email(message)
                    email = self._create_draft_standard_email(
                        draft_id=draft_ref["id"],
                        message=message,
                        base_email=base_email
                    )
                    drafts.append(email)
                except HttpError as e:
                    logger.warning(f"Failed to fetch draft {draft_ref['id']}: {e}")
                    continue

            logger.debug(f"Récupéré {len(drafts)} brouillons utilisateur")
            return drafts

        except HttpError as e:
            logger.error(f"Erreur récupération brouillons: {e}")
            return []

    def get_draft_by_id(self, draft_id: str) -> Optional[StandardEmail]:
        """
        Récupère un brouillon par son ID.

        Args:
            draft_id: Identifiant du brouillon.

        Returns:
            Le brouillon ou None si non trouvé.
        """
        self._ensure_authenticated()

        try:
            draft = self._execute_gmail_request(
                self._service.users().drafts().get(
                    userId="me",
                    id=draft_id,
                    format="full"
                ),
                "drafts.get",
            )

            message = draft.get("message", {})
            base_email = self._map_to_standard_email(message)
            return self._create_draft_standard_email(
                draft_id=draft_id,
                message=message,
                base_email=base_email
            )

        except HttpError as e:
            logger.error(f"Brouillon non trouvé: {draft_id} - {e}")
            return None

    def fetch_messages_since(
        self, since: datetime, limit: int = 100
    ) -> List[StandardEmail]:
        """
        Fetch messages received since a specific timestamp (delta sync).

        Uses Gmail's `after:` query parameter to fetch only new emails,
        minimizing API calls and bandwidth.

        Args:
            since: Fetch emails received after this timestamp.
            limit: Maximum number of messages to fetch.

        Returns:
            List of StandardEmail objects.
        """
        self._ensure_authenticated()

        try:
            # Convert datetime to Unix timestamp for Gmail query
            timestamp = int(since.timestamp())
            query = f"after:{timestamp}"

            logger.debug(f"Gmail delta sync: fetching emails after {since}")

            # List messages matching the query
            results = self._execute_gmail_request(
                self._service.users().messages().list(
                    userId="me",
                    q=query,
                    maxResults=limit,
                ),
                "messages.list.delta",
            )

            messages = results.get("messages", [])

            # Handle pagination if needed
            while "nextPageToken" in results and len(messages) < limit:
                page_token = results["nextPageToken"]
                results = self._execute_gmail_request(
                    self._service.users().messages().list(
                        userId="me",
                        q=query,
                        maxResults=min(limit - len(messages), 100),
                        pageToken=page_token,
                    ),
                    "messages.list.delta_page",
                )
                messages.extend(results.get("messages", []))

            # Batch fetch full message details
            msg_ids = [ref["id"] for ref in messages[:limit]]
            raw_messages = self._batch_fetch_messages(msg_ids, format="full")

            emails = []
            for msg in raw_messages:
                try:
                    emails.append(self._map_to_standard_email(msg))
                except Exception as e:
                    logger.warning(f"Failed to map delta sync message: {e}")

            logger.debug(f"Gmail delta sync: fetched {len(emails)} emails")
            return emails

        except HttpError as e:
            logger.error(f"Gmail delta sync error: {e}")
            raise

    def get_history_changes(
        self, start_history_id: str, limit: int = 100
    ) -> dict:
        """
        Fetch incremental changes via Gmail History API.

        Uses historyId for true delta sync — only returns messages
        added/deleted/modified since the checkpoint. Much faster than
        timestamp-based queries on busy inboxes.

        Args:
            start_history_id: historyId checkpoint from last sync.
            limit: Maximum messages to return per change type.

        Returns:
            Dict with 'added', 'deleted', 'label_changes', 'new_history_id'.
            Returns None for 'new_history_id' if historyId was invalid (expired).
        """
        self._ensure_authenticated()

        try:
            added_ids: list[str] = []
            deleted_ids: list[str] = []
            label_changes: list[dict] = []
            new_history_id = start_history_id

            page_token = None
            while True:
                request = self._service.users().history().list(
                    userId="me",
                    startHistoryId=start_history_id,
                    historyTypes=["messageAdded", "messageDeleted", "labelAdded", "labelRemoved"],
                    maxResults=500,
                    **({"pageToken": page_token} if page_token else {}),
                )
                result = self._execute_gmail_request(request, "history.list")

                new_history_id = result.get("historyId", new_history_id)

                for record in result.get("history", []):
                    for added in record.get("messagesAdded", []):
                        msg = added["message"]
                        # Only inbox messages (skip DRAFT, SPAM, TRASH)
                        labels = msg.get("labelIds", [])
                        if "INBOX" in labels:
                            added_ids.append(msg["id"])

                    for deleted in record.get("messagesDeleted", []):
                        deleted_ids.append(deleted["message"]["id"])

                    for lbl_added in record.get("labelsAdded", []):
                        msg_id = lbl_added["message"]["id"]
                        label_changes.append({
                            "id": msg_id,
                            "message_id": msg_id,
                            "added": lbl_added.get("labelIds", []),
                        })
                    for lbl_removed in record.get("labelsRemoved", []):
                        msg_id = lbl_removed["message"]["id"]
                        label_changes.append({
                            "id": msg_id,
                            "message_id": msg_id,
                            "removed": lbl_removed.get("labelIds", []),
                        })

                page_token = result.get("nextPageToken")
                if not page_token:
                    break

            # Deduplicate
            added_ids = list(dict.fromkeys(added_ids))[:limit]
            deleted_ids = list(dict.fromkeys(deleted_ids))

            # Fetch full details for added messages
            added_emails: list[StandardEmail] = []
            for msg_id in added_ids:
                try:
                    msg = self._execute_gmail_request(
                        self._service.users().messages().get(
                            userId="me", id=msg_id, format="full",
                        ),
                        "messages.get.history_added",
                    )
                    added_emails.append(self._map_to_standard_email(msg))
                except HttpError:
                    continue

            logger.info(
                f"Gmail history sync: +{len(added_emails)} added, "
                f"-{len(deleted_ids)} deleted, {len(label_changes)} label changes"
            )

            return {
                "added": added_emails,
                "deleted": deleted_ids,
                "label_changes": label_changes,
                "new_history_id": new_history_id,
            }

        except HttpError as e:
            if e.resp.status == 404:
                # historyId expired — need full sync
                logger.warning(f"Gmail historyId {start_history_id} expired, need full sync")
                return {
                    "added": [],
                    "deleted": [],
                    "label_changes": [],
                    "new_history_id": None,  # Signal caller to do full sync
                }
            if e.resp.status in (429, 500, 503):
                # Transient Google error — preserve checkpoint, skip this cycle
                logger.warning(f"Gmail history API transient error {e.resp.status}, will retry next cycle: {e}")
                return {
                    "added": [],
                    "deleted": [],
                    "label_changes": [],
                    "new_history_id": start_history_id,  # Preserve checkpoint, no full sync
                }
            logger.error(f"Gmail history API error: {e}")
            raise

    def get_current_history_id(self) -> Optional[str]:
        """Get the current historyId from the user's profile."""
        self._ensure_authenticated()
        try:
            profile = self._execute_gmail_request(
                self._service.users().getProfile(userId="me"),
                "users.getProfile",
            )
            return profile.get("historyId")
        except HttpError as e:
            logger.error(f"Failed to get Gmail profile historyId: {e}")
            return None

    def start_watch(
        self,
        topic_name: str,
        label_ids: Optional[List[str]] = None,
        label_filter_action: str = "include",
    ) -> dict:
        """
        Subscribe to Gmail Pub/Sub push notifications for this account.

        Calls ``users.watch()``. The mailbox publishes a message to ``topic_name``
        every time something changes (new message, label change, etc.). Gmail
        force-renews the subscription every 7 days, so the caller is responsible
        for re-invoking this method on a daily/weekly cadence.

        Args:
            topic_name: Fully-qualified Pub/Sub topic, e.g.
                ``projects/my-gcp-project/topics/agentys-gmail``. The Gmail API
                service account ``gmail-api-push@system.gserviceaccount.com``
                must have ``roles/pubsub.publisher`` on this topic — see
                ``docs/operations/gmail-push-setup.md`` for the one-time GCP setup.
            label_ids: Optional list of Gmail label IDs to filter on (e.g.
                ``["INBOX"]``). Defaults to the whole mailbox.
            label_filter_action: ``"include"`` (default) or ``"exclude"``.

        Returns:
            Dict with ``historyId`` (starting checkpoint) and ``expiration``
            (epoch ms when the watch expires).
        """
        self._ensure_authenticated()
        body: dict = {
            "topicName": topic_name,
            "labelFilterAction": label_filter_action,
        }
        if label_ids:
            body["labelIds"] = label_ids
        try:
            response = self._execute_gmail_request(
                self._service.users().watch(userId="me", body=body),
                "users.watch",
            )
            logger.info(
                "Gmail watch started: topic=%s historyId=%s expires=%s",
                topic_name,
                response.get("historyId"),
                response.get("expiration"),
            )
            return response
        except HttpError as e:
            logger.error("Failed to start Gmail watch on %s: %s", topic_name, e)
            raise

    def stop_watch(self) -> bool:
        """Cancel any active Gmail Pub/Sub subscription for this account."""
        self._ensure_authenticated()
        try:
            self._execute_gmail_request(
                self._service.users().stop(userId="me"),
                "users.stop",
            )
            logger.info("Gmail watch stopped")
            return True
        except HttpError as e:
            logger.error("Failed to stop Gmail watch: %s", e)
            return False

    def get_sent_emails(self, limit: int = 50, since=None) -> List[StandardEmail]:
        """
        Récupère les emails envoyés.

        Args:
            limit: Nombre maximum d'emails à récupérer.
            since: datetime optionnel — ne retourne que les emails envoyés après cette date.

        Returns:
            Liste d'emails normalisés (StandardEmail).
        """
        self._ensure_authenticated()

        try:
            query_kwargs: dict = {
                "userId": "me",
                "labelIds": ["SENT"],
                "maxResults": limit,
            }
            if since is not None:
                import calendar as _cal
                since_ts = int(_cal.timegm(since.timetuple()))
                query_kwargs["q"] = f"after:{since_ts}"

            # Rechercher les messages envoyés (label SENT)
            results = self._execute_gmail_request(
                self._service.users().messages().list(**query_kwargs),
                "messages.list.sent",
            )

            messages = results.get("messages", [])

            if not messages:
                return []

            # Fetch message details via Gmail Batch API
            msg_ids = [ref["id"] for ref in messages]
            raw_messages = self._batch_fetch_messages(msg_ids, format="full")

            emails = []
            for msg in raw_messages:
                try:
                    emails.append(self._map_to_standard_email(msg))
                except Exception as e:
                    logger.warning(f"Failed to map sent email: {e}")

            logger.info(f"Gmail sent emails batch fetch: {len(emails)} emails")
            return emails

        except HttpError as e:
            logger.error(f"Erreur récupération emails envoyés: {e}")
            return []

    def get_archived_messages(self, limit: int = 2000) -> List[StandardEmail]:
        """
        Fetch archived messages — emails not in Inbox/Sent/Spam/Trash/Drafts.

        Gmail archiving = removing the INBOX label while keeping the message.
        These emails are invisible to the default INBOX-only sync, so
        bidirectional conversations that the user has acted on and tidied
        away never enter the local DB. This method closes that gap by
        walking the "All Mail minus the standard folders" slice.

        Paginates up to ``limit`` (Gmail API caps each page at 500).

        Args:
            limit: Maximum number of archived messages to fetch.

        Returns:
            List of StandardEmail objects (full body + metadata).
        """
        self._ensure_authenticated()

        try:
            query = "-in:inbox -in:sent -in:spam -in:trash -in:drafts"
            message_refs: List[dict] = []
            page_token: Optional[str] = None

            while len(message_refs) < limit:
                page_size = min(limit - len(message_refs), 500)
                kwargs = {
                    "userId": "me",
                    "q": query,
                    "maxResults": page_size,
                }
                if page_token:
                    kwargs["pageToken"] = page_token
                results = self._execute_gmail_request(
                    self._service.users().messages().list(**kwargs),
                    "messages.list.archived",
                )
                message_refs.extend(results.get("messages", []))
                page_token = results.get("nextPageToken")
                if not page_token:
                    break

            if not message_refs:
                logger.info("Gmail archive fetch: no archived messages found")
                return []

            msg_ids = [ref["id"] for ref in message_refs[:limit]]
            raw_messages = self._batch_fetch_messages(msg_ids, format="full")

            emails: List[StandardEmail] = []
            for msg in raw_messages:
                try:
                    emails.append(self._map_to_standard_email(msg))
                except Exception as e:
                    logger.warning(f"Failed to map archived message: {e}")

            logger.info(
                f"Gmail archive fetch: {len(emails)}/{len(message_refs)} archived messages"
            )
            return emails

        except HttpError as e:
            logger.error(f"Gmail archive fetch error: {e}")
            return []

    def get_sent_backfill(self, limit: int = 1000) -> List[StandardEmail]:
        """Deep historical fetch of Sent messages, beyond the recent window.

        ``get_sent_emails(limit=N)`` issues a single ``messages.list`` call and
        is capped at one Gmail page (≤500 ids). It is fine for the periodic
        2-minute sync (limit=50) but not for a one-shot backfill that must
        cover the user's pre-install Sent history. This method paginates the
        SENT label until ``limit`` is reached or the cursor exhausts — same
        shape as :meth:`get_inbox_backfill`.

        Use case: emails the user sent through Gmail Web / mobile / another
        client BEFORE installing Agentys never reach the local Email table
        through the delta path (``get_history_changes`` only fires after the
        historyId checkpoint). Without this backfill, ``Contact.sent_count``
        stays at 0 for everyone the user already corresponds with, and the
        bidirectional contacts list is artificially poor.

        Args:
            limit: Maximum number of sent messages to fetch (paginated).

        Returns:
            List of StandardEmail with full body + metadata.
        """
        self._ensure_authenticated()

        try:
            message_refs: List[dict] = []
            page_token: Optional[str] = None

            while len(message_refs) < limit:
                page_size = min(limit - len(message_refs), 500)
                kwargs = {
                    "userId": "me",
                    "labelIds": ["SENT"],
                    "maxResults": page_size,
                }
                if page_token:
                    kwargs["pageToken"] = page_token
                results = self._execute_gmail_request(
                    self._service.users().messages().list(**kwargs),
                    "messages.list.sent_backfill",
                )
                message_refs.extend(results.get("messages", []))
                page_token = results.get("nextPageToken")
                if not page_token:
                    break

            if not message_refs:
                logger.info("Gmail sent backfill: no messages found")
                return []

            msg_ids = [ref["id"] for ref in message_refs[:limit]]
            raw_messages = self._batch_fetch_messages(msg_ids, format="full")

            emails: List[StandardEmail] = []
            for msg in raw_messages:
                try:
                    emails.append(self._map_to_standard_email(msg))
                except Exception as e:
                    logger.warning(f"Failed to map sent backfill message: {e}")

            logger.info(
                f"Gmail sent backfill: {len(emails)}/{len(message_refs)} messages"
            )
            return emails

        except HttpError as e:
            logger.error(f"Gmail sent backfill error: {e}")
            return []

    def get_inbox_backfill(self, limit: int = 1000) -> List[StandardEmail]:
        """Deep historical fetch of Inbox messages, beyond the delta/recent window.

        The Gmail delta (historyId) sync only returns events *after* the
        checkpoint. Any email received before the user installed Agentys —
        still sitting in their Inbox — never enters the DB through the
        normal code path. Without this backfill, contacts whose only
        incoming message predates the install appear one-way (sent_count>0,
        received_count=0) and get filtered out of the bidirectional list.

        Args:
            limit: Maximum number of inbox messages to fetch (paginated).

        Returns:
            List of StandardEmail with full body + metadata.
        """
        self._ensure_authenticated()

        try:
            query = "in:inbox"
            message_refs: List[dict] = []
            page_token: Optional[str] = None

            while len(message_refs) < limit:
                page_size = min(limit - len(message_refs), 500)
                kwargs = {
                    "userId": "me",
                    "q": query,
                    "maxResults": page_size,
                }
                if page_token:
                    kwargs["pageToken"] = page_token
                results = self._execute_gmail_request(
                    self._service.users().messages().list(**kwargs),
                    "messages.list.inbox_backfill",
                )
                message_refs.extend(results.get("messages", []))
                page_token = results.get("nextPageToken")
                if not page_token:
                    break

            if not message_refs:
                logger.info("Gmail inbox backfill: no messages found")
                return []

            msg_ids = [ref["id"] for ref in message_refs[:limit]]
            raw_messages = self._batch_fetch_messages(msg_ids, format="full")

            emails: List[StandardEmail] = []
            for msg in raw_messages:
                try:
                    emails.append(self._map_to_standard_email(msg))
                except Exception as e:
                    logger.warning(f"Failed to map inbox backfill message: {e}")

            logger.info(
                f"Gmail inbox backfill: {len(emails)}/{len(message_refs)} messages"
            )
            return emails

        except HttpError as e:
            logger.error(f"Gmail inbox backfill error: {e}")
            return []

    def list_folders(self) -> List[EmailFolder]:
        """
        Liste les labels Gmail de l'utilisateur.

        Returns:
            Liste de dossiers normalisés (EmailFolder).
        """
        self._ensure_authenticated()

        try:
            results = self._execute_gmail_request(
                self._service.users().labels().list(userId="me"),
                "labels.list",
            )
            labels = results.get("labels", [])

            folders = []
            # System labels that should be categorized as 'system'
            system_labels = {
                "INBOX", "SENT", "DRAFT", "TRASH", "SPAM", "STARRED",
                "UNREAD", "IMPORTANT", "CATEGORY_PERSONAL", "CATEGORY_SOCIAL",
                "CATEGORY_PROMOTIONS", "CATEGORY_UPDATES", "CATEGORY_FORUMS"
            }

            for label in labels:
                label_id = label.get("id", "")
                label_name = label.get("name", "")

                # Skip internal labels
                if label_name.startswith("CATEGORY_") and label_name != "CATEGORY_PERSONAL":
                    continue

                # Determine display name (handle nested labels like "Parent/Child")
                display_name = label_name.split("/")[-1] if "/" in label_name else label_name

                # Determine parent_id for nested labels
                parent_id = None
                if "/" in label_name:
                    parent_name = "/".join(label_name.split("/")[:-1])
                    # Find parent label
                    for other_label in labels:
                        if other_label.get("name") == parent_name:
                            parent_id = other_label.get("id")
                            break

                # Determine folder type
                folder_type = "system" if label_id in system_labels or label_name in system_labels else "user"

                # Get message counts if available
                unread_count = label.get("messagesUnread", 0)
                total_count = label.get("messagesTotal", 0)

                folders.append(EmailFolder(
                    id=label_id,
                    name=label_name,
                    display_name=display_name,
                    type=folder_type,
                    parent_id=parent_id,
                    unread_count=unread_count,
                    total_count=total_count,
                ))

            logger.info(f"Gmail list_folders: {len(folders)} folders")
            return folders

        except HttpError as e:
            logger.error(f"Erreur récupération labels Gmail: {e}")
            return []

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

        Args:
            draft_id: ID du brouillon à modifier.
            subject: Nouveau sujet (optionnel).
            body: Nouveau corps (optionnel).
            to: Nouveaux destinataires (optionnel).
            cc: Nouvelle liste CC (optionnel).
            is_html: True si le body est en HTML.

        Returns:
            True si la mise à jour réussit.
        """
        self._ensure_authenticated()

        try:
            # Récupérer le brouillon actuel
            current = self.get_draft_by_id(draft_id)
            if not current:
                return False

            # Fusionner les valeurs
            final_to = to if to is not None else current.to
            final_subject = subject if subject is not None else current.subject
            final_body = body if body is not None else current.body
            final_cc = cc if cc is not None else current.cc

            logger.debug(f"update_draft: current.to={current.to}, final_to={final_to}")

            # Créer le nouveau message
            message = self._create_message(
                to=final_to,
                subject=final_subject,
                body=final_body,
                cc=final_cc,
                is_html=is_html
            )

            # Mettre à jour le brouillon
            self._execute_gmail_request(
                self._service.users().drafts().update(
                    userId="me",
                    id=draft_id,
                    body={"message": message}
                ),
                "drafts.update",
            )

            logger.info(f"Brouillon {draft_id} mis à jour")
            return True

        except HttpError as e:
            logger.error(f"Erreur mise à jour brouillon {draft_id}: {e}")
            return False

    # Headers requested by the labelizer's RFC noise rules. Kept in sync with
    # `_map_to_standard_email` so backfill and fresh sync produce equivalent
    # raw_metadata["classification_headers"] payloads.
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
        """Fetch RFC bulk-classification headers for Gmail message IDs.

        Uses Gmail metadata-only fetches so historical backfills do not download
        full bodies. Returns lowercase header keys matching the shape persisted
        by sync_service into Email.raw_headers.
        """
        self._ensure_authenticated()
        if not message_ids:
            return {}

        raw_messages = self._batch_fetch_messages(
            list(message_ids),
            format="metadata",
            metadata_headers=list(self._CLASSIFICATION_HEADER_NAMES_FOR_BACKFILL),
        )
        wanted = {name.lower() for name in self._CLASSIFICATION_HEADER_NAMES_FOR_BACKFILL}
        out: Dict[str, Dict[str, str]] = {}
        for msg in raw_messages:
            msg_id = msg.get("id")
            if not msg_id:
                continue
            extracted: Dict[str, str] = {}
            for header in msg.get("payload", {}).get("headers", []) or []:
                name = (header.get("name") or "").lower()
                value = header.get("value")
                if name in wanted and value:
                    extracted[name] = value
            if extracted:
                out[msg_id] = extracted
        return out

    def search_subscription_emails(self, limit: int = 200) -> List[StandardEmail]:
        """
        Search for subscription/billing related emails.

        Uses Gmail query to find receipts, invoices, payment confirmations
        and subscription notifications. Fetches metadata + List-Unsubscribe header.

        Args:
            limit: Maximum number of emails to scan.

        Returns:
            List of StandardEmail with list_unsubscribe in raw_metadata.
        """
        self._ensure_authenticated()

        try:
            query = "subject:(receipt OR invoice OR payment OR subscription OR billing OR order OR shipping OR confirmation OR reçu OR facture OR commande OR livraison) -from:me"

            results = self._execute_gmail_request(
                self._service.users().messages().list(
                    userId="me",
                    q=query,
                    maxResults=limit,
                    includeSpamTrash=True,
                ),
                "messages.list.subscriptions",
            )

            message_refs = results.get("messages", [])
            if not message_refs:
                return []

            emails = []
            for msg_ref in message_refs:
                try:
                    msg = self._execute_gmail_request(
                        self._service.users().messages().get(
                            userId="me",
                            id=msg_ref["id"],
                            format="metadata",
                            metadataHeaders=[
                                "From", "Subject", "Date",
                                "List-Unsubscribe", "List-Unsubscribe-Post",
                            ],
                        ),
                        "messages.get.subscriptions",
                    )

                    headers = {
                        h["name"]: h["value"]
                        for h in msg.get("payload", {}).get("headers", [])
                    }

                    from_header = headers.get("From", "")
                    sender_email, sender_name = self._parse_email_address(from_header)

                    date_str = headers.get("Date", "")
                    received_at = None
                    if date_str:
                        try:
                            from email.utils import parsedate_to_datetime
                            received_at = parsedate_to_datetime(date_str)
                        except (ValueError, TypeError):
                            pass

                    labels = msg.get("labelIds", [])
                    is_read = "UNREAD" not in labels

                    emails.append(StandardEmail(
                        id=msg["id"],
                        subject=headers.get("Subject", ""),
                        sender=sender_email or from_header,
                        sender_name=sender_name,
                        body="",
                        body_html=None,
                        received_at=received_at,
                        is_read=is_read,
                        has_attachments=False,
                        conversation_id=msg.get("threadId"),
                        provider_source=self.PROVIDER_NAME,
                        raw_metadata={
                            "list_unsubscribe": headers.get("List-Unsubscribe", ""),
                            "list_unsubscribe_post": headers.get("List-Unsubscribe-Post", ""),
                            "header_only": True,
                        },
                    ))
                except HttpError as e:
                    logger.warning(f"Could not fetch subscription email {msg_ref['id']}: {e}")
                    continue

            logger.info(f"Found {len(emails)} subscription-related emails")
            return emails

        except HttpError as e:
            logger.error(f"Gmail subscription search error: {e}")
            return []

    def search_newsletter_emails(self, limit: int = 300) -> List[StandardEmail]:
        """
        Search for newsletter emails via Gmail API.

        Uses Gmail's category:promotions and list:* filters plus
        List-Unsubscribe header extraction.

        Args:
            limit: Maximum number of emails to scan.

        Returns:
            List of StandardEmail with list_unsubscribe in raw_metadata.
        """
        self._ensure_authenticated()

        try:
            query = (
                "(list:* OR category:promotions OR subject:newsletter "
                "OR subject:unsubscribe OR subject:weekly OR subject:digest) -from:me"
            )

            results = self._execute_gmail_request(
                self._service.users().messages().list(
                    userId="me",
                    q=query,
                    maxResults=limit,
                ),
                "messages.list.newsletters",
            )

            message_refs = results.get("messages", [])
            if not message_refs:
                return []

            emails = []
            for msg_ref in message_refs:
                try:
                    msg = self._execute_gmail_request(
                        self._service.users().messages().get(
                            userId="me",
                            id=msg_ref["id"],
                            format="metadata",
                            metadataHeaders=[
                                "From", "Subject", "Date",
                                "List-Unsubscribe", "List-Unsubscribe-Post",
                            ],
                        ),
                        "messages.get.newsletters",
                    )

                    headers = {
                        h["name"]: h["value"]
                        for h in msg.get("payload", {}).get("headers", [])
                    }

                    list_unsub = headers.get("List-Unsubscribe", "")
                    if not list_unsub:
                        continue

                    from_header = headers.get("From", "")
                    sender_email, sender_name = self._parse_email_address(from_header)

                    date_str = headers.get("Date", "")
                    received_at = None
                    if date_str:
                        try:
                            from email.utils import parsedate_to_datetime
                            received_at = parsedate_to_datetime(date_str)
                        except (ValueError, TypeError):
                            pass

                    emails.append(StandardEmail(
                        id=msg["id"],
                        subject=headers.get("Subject", ""),
                        sender=sender_email or from_header,
                        sender_name=sender_name,
                        body="",
                        body_html=None,
                        received_at=received_at,
                        is_read=True,
                        has_attachments=False,
                        conversation_id=msg.get("threadId"),
                        provider_source=self.PROVIDER_NAME,
                        raw_metadata={
                            "list_unsubscribe": list_unsub,
                            "list_unsubscribe_post": headers.get("List-Unsubscribe-Post", ""),
                            "header_only": True,
                        },
                    ))
                except HttpError as e:
                    logger.warning(f"Could not fetch newsletter email {msg_ref['id']}: {e}")
                    continue

            logger.info(f"Found {len(emails)} newsletter emails")
            return emails

        except HttpError as e:
            logger.error(f"Gmail newsletter search error: {e}")
            return []

    def get_signature(self) -> Optional[dict]:
        """
        Récupère la signature email de l'utilisateur depuis Gmail.

        Uses the Gmail API users.settings.sendAs endpoint to fetch
        the signature configured for the primary email address.

        Returns:
            Dict with 'html' and 'text' keys, or None if no signature found.
        """
        self._ensure_authenticated()

        try:
            # Get send-as settings (contains signature)
            send_as_list = self._execute_gmail_request(
                self._service.users().settings().sendAs().list(
                    userId="me"
                ),
                "settings.sendAs.list",
            )

            send_as_items = send_as_list.get("sendAs", [])

            # Find the primary send-as (isPrimary=True) or default
            primary_send_as = None
            for item in send_as_items:
                if item.get("isPrimary", False):
                    primary_send_as = item
                    break

            if not primary_send_as and send_as_items:
                primary_send_as = send_as_items[0]

            if not primary_send_as:
                logger.debug("No send-as settings found for Gmail account")
                return None

            # Extract signature (HTML format from Gmail)
            signature_html = primary_send_as.get("signature", "")

            if not signature_html:
                logger.debug("No signature configured in Gmail settings")
                return None

            # Convert HTML to plain text preserving line breaks
            import re
            import html as _html
            sig = signature_html
            sig = re.sub(r'<br\s*/?>', '\n', sig, flags=re.IGNORECASE)
            sig = re.sub(r'</(?:p|div|li|tr|h[1-6])>', '\n', sig, flags=re.IGNORECASE)
            sig = re.sub(r'<[^>]+>', '', sig)
            sig = _html.unescape(sig)
            sig = re.sub(r'\n{3,}', '\n\n', sig)
            sig = re.sub(r'[ \t]+', ' ', sig)
            signature_text = sig.strip()

            logger.info("Gmail signature fetched successfully")
            return {
                "html": signature_html,
                "text": signature_text
            }

        except HttpError as e:
            if e.resp.status in (403, 401):
                logger.warning(f"Gmail signature: insufficient scopes (HTTP {e.resp.status})")
                raise PermissionError(
                    "Scope Gmail insuffisant pour accéder à la signature. "
                    "Veuillez reconnecter votre compte Gmail."
                )
            logger.error(f"Error fetching Gmail signature: {e}")
            return None
