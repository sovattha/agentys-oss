# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Provider email synthétique pour les tests de charge locaux."""

from __future__ import annotations

import math
import os
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from app.interfaces.email_provider import EmailFolder, EmailProvider, StandardEmail


_PROVIDER_KIND_OVERRIDE: ContextVar[str | None] = ContextVar(
    "agentys_mock_load_provider_kind",
    default=None,
)


class LoadTestQuotaBackoffError(RuntimeError):
    """Synthetic provider quota error for local load tests."""

    code = "GMAIL_QUOTA_BACKOFF"

    def __init__(self, retry_after: float, provider: str | None = None):
        self.provider = provider or _provider_kind()
        self.retry_after = max(1, int(retry_after))
        super().__init__(
            f"Mock {self.provider} quota backoff: retry after {self.retry_after}s"
        )


def _env_int(name: str, default: int = 0) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _provider_kind() -> str:
    kind = (
        _PROVIDER_KIND_OVERRIDE.get()
        or os.getenv("AGENTYS_MOCK_EMAIL_PROVIDER_KIND", "mock-load")
    ).strip().lower()
    if kind in {"gmail", "google"}:
        return "gmail"
    if kind in {"outlook", "microsoft", "graph"}:
        return "outlook"
    return "mock-load"


@contextmanager
def provider_kind_override(kind: str | None):
    normalized = (kind or "").strip().lower()
    if normalized not in {"gmail", "google", "outlook", "microsoft", "graph"}:
        yield
        return
    token = _PROVIDER_KIND_OVERRIDE.set(normalized)
    try:
        yield
    finally:
        _PROVIDER_KIND_OVERRIDE.reset(token)


def _provider_env_int(suffix: str, default: int = 0) -> int:
    kind = _provider_kind().upper().replace("-", "_")
    names = [f"AGENTYS_MOCK_{kind}_{suffix}"]
    if kind != "GMAIL":
        names.append(f"AGENTYS_MOCK_GMAIL_{suffix}")
    for name in names:
        if name in os.environ:
            return _env_int(name, default)
    return default


class LoadTestEmailProvider(EmailProvider):
    """Provider sans réseau activé par ``AGENTYS_MOCK_EMAIL_PROVIDER=true``."""

    _quota_lock = threading.Lock()
    _quota_backoff_until = 0.0
    _list_calls = 0
    _detail_calls = 0
    _sent_calls = 0

    @property
    def provider_name(self) -> str:
        return _provider_kind()

    def authenticate(self) -> bool:
        return True

    def disconnect(self) -> None:
        return None

    @classmethod
    def reset_quota_state(cls) -> None:
        with cls._quota_lock:
            cls._quota_backoff_until = 0.0
            cls._list_calls = 0
            cls._detail_calls = 0
            cls._sent_calls = 0

    @classmethod
    def _retry_after_seconds(cls) -> int:
        with cls._quota_lock:
            return max(0, int(math.ceil(cls._quota_backoff_until - time.monotonic())))

    @classmethod
    def _activate_backoff(cls, seconds: int | None = None) -> LoadTestQuotaBackoffError:
        retry_after = seconds or _provider_env_int("BACKOFF_SECONDS", 5)
        retry_after = max(1, retry_after)
        with cls._quota_lock:
            cls._quota_backoff_until = max(
                cls._quota_backoff_until,
                time.monotonic() + retry_after,
            )
        return LoadTestQuotaBackoffError(retry_after, provider=_provider_kind())

    @classmethod
    def _should_rate_limit(cls, counter_name: str, every: int) -> bool:
        if every <= 0:
            return False
        with cls._quota_lock:
            value = getattr(cls, counter_name) + 1
            setattr(cls, counter_name, value)
            return value % every == 0

    def low_priority_quota_retry_after_seconds(self) -> int:
        return self._retry_after_seconds()

    @contextmanager
    def limited_quota_wait(self, max_wait_seconds: float):
        retry_after = self._retry_after_seconds()
        if retry_after > max_wait_seconds:
            raise LoadTestQuotaBackoffError(retry_after)
        yield

    def get_unread_messages(self, limit: int = 10) -> List[StandardEmail]:
        return self.get_messages(limit=limit, unread_only=True)

    def get_messages(
        self,
        limit: int = 50,
        unread_only: bool = False,
        query: str = None,
    ) -> List[StandardEmail]:
        latency_ms = _provider_env_int("LIST_LATENCY_MS", 0)
        if latency_ms:
            time.sleep(latency_ms / 1000.0)
        if self._should_rate_limit(
            "_list_calls",
            _provider_env_int("LIST_BACKOFF_EVERY", 0),
        ):
            raise self._activate_backoff()
        return [self._make_email(f"load-email-{idx}") for idx in range(max(0, limit))]

    def get_message_by_id(self, message_id: str) -> Optional[StandardEmail]:
        latency_ms = _provider_env_int("DETAIL_LATENCY_MS", 0)
        if latency_ms:
            time.sleep(latency_ms / 1000.0)
        if self._should_rate_limit(
            "_detail_calls",
            _provider_env_int("DETAIL_BACKOFF_EVERY", 0),
        ):
            raise self._activate_backoff()
        return self._make_email(message_id)

    def get_sent_emails(self, limit: int = 50, since=None) -> List[StandardEmail]:
        latency_ms = _provider_env_int("SENT_LATENCY_MS", 0)
        if latency_ms:
            time.sleep(latency_ms / 1000.0)
        if self._should_rate_limit(
            "_sent_calls",
            _provider_env_int("SENT_BACKOFF_EVERY", 0),
        ):
            raise self._activate_backoff()
        return [self._make_email(f"sent-load-email-{idx}") for idx in range(max(0, limit))]

    def get_sent_backfill(self, limit: int = 1000) -> List[StandardEmail]:
        return self.get_sent_emails(limit=limit)

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
        return f"mock-draft-{uuid.uuid4().hex}"

    def send_draft(self, draft_id: str) -> bool:
        return True

    def mark_as_read(self, message_id: str) -> bool:
        return True

    def mark_as_unread(self, message_id: str) -> bool:
        return True

    def get_user_drafts(self, limit: int = 50) -> List[StandardEmail]:
        return []

    def get_draft_by_id(self, draft_id: str) -> Optional[StandardEmail]:
        draft = self._make_email(draft_id)
        draft.raw_metadata["is_user_draft"] = True
        return draft

    def update_draft(
        self,
        draft_id: str,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        to: Optional[List[str]] = None,
        cc: Optional[List[str]] = None,
        is_html: bool = False,
    ) -> bool:
        return True

    def list_folders(self) -> List[EmailFolder]:
        return [
            EmailFolder(id="inbox", name="inbox", display_name="Inbox", type="inbox"),
            EmailFolder(id="sent", name="sent", display_name="Sent", type="sent"),
            EmailFolder(id="drafts", name="drafts", display_name="Drafts", type="drafts"),
        ]

    @staticmethod
    def _make_email(message_id: str) -> StandardEmail:
        is_sent = message_id.startswith("sent-") or message_id.startswith("sent:")
        return StandardEmail(
            id=message_id,
            sender="agentys.loadtest@example.com" if is_sent else "client.loadtest@example.com",
            sender_name="Agentys Load Test" if is_sent else "Client Load Test",
            to=["client.loadtest@example.com"] if is_sent else ["agentys.loadtest@example.com"],
            cc=[],
            subject=f"Question test {message_id}",
            body=(
                "Bonjour,\n\n"
                "Pouvez-vous me confirmer la prochaine étape et le délai prévu ?\n\n"
                "Merci."
            ),
            received_at=datetime.now(timezone.utc),
            is_read=False,
            conversation_id=f"thread-{message_id}",
            provider_source=_provider_kind(),
            raw_metadata={"source": "load_test_provider", "provider_kind": _provider_kind()},
        )
