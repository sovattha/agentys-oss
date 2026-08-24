# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Regression: bounce permanent-delete must not strip Noise label on provider failure.

Bug 2026-05-18: ``_cleanup_noise_bg`` discarded the return value of
``provider.permanently_delete``. When Gmail returned False (transient
HttpError, 404, rate limit), the code still appended the email id to
``permanently_deleted_ids`` and then called ``bulk_remove_label(..., "Noise")``.
The email survived upstream → next IMAP sync re-imported it to folder='inbox'
without a Noise label → it showed in the Inbox tab → background classifier
re-labelled it Noise → next cleanup pass repeated the failed delete and
stripped the label again. The user saw the bounce flicker between Inbox and
Noise tabs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def reset_noise_cleanup_state():
    from app.api import routes_emails as re

    re._noise_auto_cleanup_last_started.clear()
    re._noise_cleanup_running = False
    re._noise_manual_cleanup_running = False
    yield
    re._noise_auto_cleanup_last_started.clear()
    re._noise_cleanup_running = False
    re._noise_manual_cleanup_running = False


def test_failed_permanent_delete_does_not_strip_noise_label():
    """Provider returning False from permanently_delete must NOT mark the
    email as deleted — otherwise the downstream ``bulk_remove_label`` call
    would strip the Noise label from an email that still exists upstream."""
    from app.api import routes_emails as re

    # Build a fake provider whose permanent-delete always reports failure
    fake_provider = MagicMock()
    fake_provider.permanently_delete.return_value = False
    fake_provider.delete_email.return_value = False

    # Fake label store — records bulk_remove_label calls
    fake_label_store = MagicMock()
    fake_label_store.get_emails_by_label.return_value = ["bounce-1"]

    # Fake db email: a 4-day-old bounce
    fake_em = MagicMock()
    fake_em.email_id = "bounce-1"
    fake_em.sender = "mailer-daemon@google.com"
    fake_em.is_read = True
    fake_em.date = datetime.now(timezone.utc) - timedelta(days=4)

    fake_repo = MagicMock()
    fake_repo.get_by_account.return_value = [fake_em]
    fake_repo.get_by_email_id.return_value = fake_em

    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_session)
    fake_session.__exit__ = MagicMock(return_value=False)

    fake_container = MagicMock()
    fake_container.get_label_store.return_value = fake_label_store
    fake_container.get_settings_store.return_value.get_settings.return_value = {
        "auto_cleanup_noise": True,
        "cleanup_noise_days": 7,
    }

    fake_account_manager = MagicMock()
    fake_account_manager.get_account.return_value = MagicMock(email="user@example.com")

    with patch.object(re._rh, "_get_container", return_value=fake_container), \
         patch.object(re._rh, "get_db_session", return_value=fake_session), \
         patch.object(re._rh, "EmailRepository", return_value=fake_repo), \
         patch("app.api.settings.load_settings", return_value={"auto_cleanup_noise": True, "cleanup_noise_days": 7}), \
         patch("app.providers.factory.get_pooled_provider", return_value=fake_provider), \
         patch("app.multi_accounts.get_account_manager", return_value=fake_account_manager):

        re._cleanup_noise_bg(account_id=1, oauth_account_id="abc123", manual=False)

    # The provider call must have happened
    fake_provider.permanently_delete.assert_called_with("bounce-1")

    # CRITICAL: Noise label must NOT have been removed for the bounce id —
    # the upstream delete failed, so the email may reappear in INBOX on the
    # next sync. Stripping the label here is what creates the flicker.
    for call in fake_label_store.bulk_remove_label.call_args_list:
        ids_arg = call.args[0] if call.args else call.kwargs.get("email_ids", set())
        assert "bounce-1" not in set(ids_arg), (
            "bulk_remove_label('Noise') was called for an email whose "
            "permanent-delete failed — this is the flicker bug"
        )


def test_auto_noise_cleanup_skips_messages_already_outside_inbox():
    from app.api import routes_emails as re

    fake_provider = MagicMock()
    fake_provider.delete_email.return_value = True
    fake_provider.permanently_delete.return_value = True

    fake_label_store = MagicMock()
    fake_label_store.get_emails_by_label.return_value = ["noise-1"]

    fake_em = MagicMock()
    fake_em.email_id = "noise-1"
    fake_em.sender = "news@example.com"
    fake_em.is_read = True
    fake_em.is_sent = False
    fake_em.folder = "trash"
    fake_em.date = datetime.now(timezone.utc) - timedelta(days=10)

    fake_repo = MagicMock()
    fake_repo.get_by_account.return_value = [fake_em]

    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_session)
    fake_session.__exit__ = MagicMock(return_value=False)

    fake_container = MagicMock()
    fake_container.get_label_store.return_value = fake_label_store

    fake_account_manager = MagicMock()
    fake_account_manager.get_account.return_value = MagicMock(email="user@example.com")

    with patch.object(re._rh, "_get_container", return_value=fake_container), \
         patch.object(re._rh, "get_db_session", return_value=fake_session), \
         patch.object(re._rh, "EmailRepository", return_value=fake_repo), \
         patch("app.api.settings.load_settings", return_value={"auto_cleanup_noise": True, "cleanup_noise_days": 7}), \
         patch("app.providers.factory.get_pooled_provider", return_value=fake_provider), \
         patch("app.multi_accounts.get_account_manager", return_value=fake_account_manager):

        result = re._cleanup_noise_bg(account_id=1, oauth_account_id="abc123", manual=False)

    assert result == (0, 0)
    fake_provider.delete_email.assert_not_called()
    fake_provider.permanently_delete.assert_not_called()
    fake_label_store.bulk_remove_label.assert_not_called()


def test_auto_noise_cleanup_skips_provider_when_quota_backed_off():
    from app.api import routes_emails as re

    class BackedOffProvider:
        def __init__(self):
            self.delete_email = MagicMock(return_value=True)
            self.permanently_delete = MagicMock(return_value=True)

        def low_priority_quota_retry_after_seconds(self):
            return 55

    fake_provider = BackedOffProvider()
    fake_label_store = MagicMock()
    fake_label_store.get_emails_by_label.return_value = ["noise-1"]

    fake_em = MagicMock()
    fake_em.email_id = "noise-1"
    fake_em.sender = "news@example.com"
    fake_em.is_read = True
    fake_em.is_sent = False
    fake_em.folder = "inbox"
    fake_em.date = datetime.now(timezone.utc) - timedelta(days=10)

    fake_repo = MagicMock()
    fake_repo.get_by_account.return_value = [fake_em]

    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_session)
    fake_session.__exit__ = MagicMock(return_value=False)

    fake_container = MagicMock()
    fake_container.get_label_store.return_value = fake_label_store

    fake_account_manager = MagicMock()
    fake_account_manager.get_account.return_value = MagicMock(email="user@example.com")

    with patch.object(re._rh, "_get_container", return_value=fake_container), \
         patch.object(re._rh, "get_db_session", return_value=fake_session), \
         patch.object(re._rh, "EmailRepository", return_value=fake_repo), \
         patch("app.api.settings.load_settings", return_value={"auto_cleanup_noise": True, "cleanup_noise_days": 7}), \
         patch("app.providers.factory.get_pooled_provider", return_value=fake_provider), \
         patch("app.multi_accounts.get_account_manager", return_value=fake_account_manager):
        result = re._cleanup_noise_bg(account_id=1, oauth_account_id="abc123", manual=False)

    assert result is None
    fake_provider.delete_email.assert_not_called()
    fake_provider.permanently_delete.assert_not_called()
    fake_label_store.bulk_remove_label.assert_not_called()


def test_auto_noise_cleanup_is_throttled_per_account(monkeypatch):
    from app.api import routes_emails as re

    monkeypatch.setenv("AGENTYS_AUTO_CLEANUP_NOISE_MIN_INTERVAL_SECONDS", "3600")
    ticks = iter([100.0, 120.0])
    monkeypatch.setattr(re._cache_time, "monotonic", lambda: next(ticks))

    fake_provider = MagicMock()
    fake_provider.delete_email.return_value = True

    fake_label_store = MagicMock()
    fake_label_store.get_emails_by_label.return_value = ["noise-1"]

    fake_em = MagicMock()
    fake_em.email_id = "noise-1"
    fake_em.sender = "news@example.com"
    fake_em.is_read = True
    fake_em.is_sent = False
    fake_em.folder = "inbox"
    fake_em.date = datetime.now(timezone.utc) - timedelta(days=10)

    fake_repo = MagicMock()
    fake_repo.get_by_account.return_value = [fake_em]

    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_session)
    fake_session.__exit__ = MagicMock(return_value=False)

    fake_container = MagicMock()
    fake_container.get_label_store.return_value = fake_label_store

    fake_account_manager = MagicMock()
    fake_account_manager.get_account.return_value = MagicMock(email="user@example.com")

    with patch.object(re._rh, "_get_container", return_value=fake_container), \
         patch.object(re._rh, "get_db_session", return_value=fake_session), \
         patch.object(re._rh, "EmailRepository", return_value=fake_repo), \
         patch("app.api.settings.load_settings", return_value={"auto_cleanup_noise": True, "cleanup_noise_days": 7}), \
         patch("app.providers.factory.get_pooled_provider", return_value=fake_provider), \
         patch("app.multi_accounts.get_account_manager", return_value=fake_account_manager):

        first = re._cleanup_noise_bg(account_id=1, oauth_account_id="abc123", manual=False)
        second = re._cleanup_noise_bg(account_id=1, oauth_account_id="abc123", manual=False)

    assert first == (1, 0)
    assert second is None
    fake_provider.delete_email.assert_called_once_with("noise-1")
    assert fake_repo.get_by_account.call_count == 1
