# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for ``app.services.auto_reply``.

GH#622 regression coverage — the OOO auto-reply path was previously a
private daemon method only reachable from the legacy IMAP polling code.
Gmail OAuth accounts route through ``sync_service._store_emails`` and
never received an auto-reply. This file exercises the extracted service
in isolation and the dedupe contract.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.services import auto_reply as auto_reply_mod
from app.services.auto_reply import send_auto_reply_if_needed


@pytest.fixture(autouse=True)
def _clear_replied_state():
    """Per-test reset of the module-level dedupe set."""
    auto_reply_mod.reset_replied_senders()
    yield
    auto_reply_mod.reset_replied_senders()


def _make_email(
    sender: str = "alice@example.com",
    subject: str = "Quick question",
    body: str = "Hello, can you confirm?",
    email_id: str = "msg-1",
):
    e = MagicMock()
    e.id = email_id
    e.sender = sender
    e.subject = subject
    e.body = body
    return e


def _enabled_settings(message: str = "Out of office", days: int = 7) -> dict:
    today = datetime.now()
    return {
        "auto_reply_enabled": True,
        "auto_reply_message": message,
        "auto_reply_start": (today - timedelta(days=days)).strftime("%Y-%m-%d"),
        "auto_reply_end": (today + timedelta(days=days)).strftime("%Y-%m-%d"),
    }


def _disabled_settings() -> dict:
    return {"auto_reply_enabled": False}


def _make_provider(draft_id: str | None = "draft-1", send_ok: bool = True):
    provider = MagicMock()
    provider.create_draft.return_value = draft_id
    provider.send_draft.return_value = send_ok
    return provider


class TestAutoReplySendsWhenEnabledAndInWindow:
    def test_sends_when_settings_active(self):
        provider = _make_provider()
        email = _make_email()

        with patch(
            "app.api.settings.load_settings", return_value=_enabled_settings()
        ):
            sent = send_auto_reply_if_needed(
                provider=provider, account_id=1, email=email
            )

        assert sent is True
        provider.create_draft.assert_called_once()
        kwargs = provider.create_draft.call_args.kwargs
        assert kwargs["to"] == ["alice@example.com"]
        assert kwargs["subject"] == "Re: Quick question"
        # Body starts with the configured OOO message — followed by the
        # account's signature, appended via ``app.utils.signature.append_signature``
        # so the recipient sees the same closing as on every other email the
        # user sends. The signature payload is account-dependent so we only
        # assert the message prefix + the signature wrapper presence.
        assert kwargs["body"].startswith("Out of office")
        if len(kwargs["body"]) > len("Out of office"):
            assert "agentys-signature" in kwargs["body"]
        assert kwargs["reply_to_id"] == "msg-1"
        provider.send_draft.assert_called_once_with("draft-1")

    def test_subject_re_prefix_not_duplicated(self):
        provider = _make_provider()
        email = _make_email(subject="Re: thread")

        with patch(
            "app.api.settings.load_settings", return_value=_enabled_settings()
        ):
            send_auto_reply_if_needed(provider=provider, account_id=1, email=email)

        assert provider.create_draft.call_args.kwargs["subject"] == "Re: thread"

    def test_empty_subject_gets_sans_objet(self):
        provider = _make_provider()
        email = _make_email(subject="")

        with patch(
            "app.api.settings.load_settings", return_value=_enabled_settings()
        ):
            send_auto_reply_if_needed(provider=provider, account_id=1, email=email)

        assert provider.create_draft.call_args.kwargs["subject"] == "Re: (sans sujet)"


class TestAutoReplySkipReasons:
    def test_skipped_when_disabled(self):
        provider = _make_provider()
        with patch(
            "app.api.settings.load_settings", return_value=_disabled_settings()
        ):
            assert (
                send_auto_reply_if_needed(provider, 1, _make_email()) is False
            )
        provider.create_draft.assert_not_called()

    def test_skipped_when_message_empty(self):
        provider = _make_provider()
        settings = _enabled_settings(message="   ")
        with patch("app.api.settings.load_settings", return_value=settings):
            assert (
                send_auto_reply_if_needed(provider, 1, _make_email()) is False
            )
        provider.create_draft.assert_not_called()

    def test_skipped_when_today_before_window(self):
        provider = _make_provider()
        today = datetime.now()
        settings = {
            "auto_reply_enabled": True,
            "auto_reply_message": "Away",
            "auto_reply_start": (today + timedelta(days=2)).strftime("%Y-%m-%d"),
            "auto_reply_end": (today + timedelta(days=9)).strftime("%Y-%m-%d"),
        }
        with patch("app.api.settings.load_settings", return_value=settings):
            assert (
                send_auto_reply_if_needed(provider, 1, _make_email()) is False
            )
        provider.create_draft.assert_not_called()

    def test_skipped_when_today_after_window(self):
        provider = _make_provider()
        today = datetime.now()
        settings = {
            "auto_reply_enabled": True,
            "auto_reply_message": "Away",
            "auto_reply_start": (today - timedelta(days=9)).strftime("%Y-%m-%d"),
            "auto_reply_end": (today - timedelta(days=2)).strftime("%Y-%m-%d"),
        }
        with patch("app.api.settings.load_settings", return_value=settings):
            assert (
                send_auto_reply_if_needed(provider, 1, _make_email()) is False
            )
        provider.create_draft.assert_not_called()

    def test_skipped_when_incoming_is_auto_reply(self):
        """Never auto-reply to an auto-reply — loop prevention."""
        provider = _make_provider()
        with patch(
            "app.api.settings.load_settings", return_value=_enabled_settings()
        ):
            assert (
                send_auto_reply_if_needed(
                    provider, 1, _make_email(), is_auto_reply=True
                )
                is False
            )
        provider.create_draft.assert_not_called()

    def test_skipped_for_self_send_bare_address(self):
        provider = _make_provider()
        with patch(
            "app.api.settings.load_settings", return_value=_enabled_settings()
        ):
            assert (
                send_auto_reply_if_needed(
                    provider,
                    1,
                    _make_email(sender="me@example.com"),
                    account_email="me@example.com",
                )
                is False
            )
        provider.create_draft.assert_not_called()

    def test_skipped_for_self_send_display_name_form(self):
        provider = _make_provider()
        with patch(
            "app.api.settings.load_settings", return_value=_enabled_settings()
        ):
            assert (
                send_auto_reply_if_needed(
                    provider,
                    1,
                    _make_email(sender='"Me" <me@example.com>'),
                    account_email="me@example.com",
                )
                is False
            )
        provider.create_draft.assert_not_called()

    def test_skipped_when_sender_is_another_own_account(self):
        """Cross-account loop guard — Gmail must not auto-reply to Hotmail
        (or any other inbox the same user has connected to Agentys).
        """
        provider = _make_provider()
        with patch(
            "app.api.settings.load_settings", return_value=_enabled_settings()
        ):
            assert (
                send_auto_reply_if_needed(
                    provider,
                    1,
                    _make_email(sender="alex@hotmail.com"),
                    account_email="me@gmail.com",
                    own_account_emails={"me@gmail.com", "alex@hotmail.com"},
                )
                is False
            )
        provider.create_draft.assert_not_called()

    def test_external_sender_still_replies_when_own_set_provided(self):
        """Sanity: providing ``own_account_emails`` must not break the
        happy path — an external sender outside the set still gets a reply.
        """
        provider = _make_provider()
        with patch(
            "app.api.settings.load_settings", return_value=_enabled_settings()
        ):
            sent = send_auto_reply_if_needed(
                provider,
                1,
                _make_email(sender="external@somewhere.com"),
                account_email="me@gmail.com",
                own_account_emails={"me@gmail.com", "alex@hotmail.com"},
            )
        assert sent is True
        provider.create_draft.assert_called_once()

    @pytest.mark.parametrize(
        "sender",
        [
            "noreply@stripe.com",
            "no-reply@github.com",
            "notifications@slack.com",
            "mailer-daemon@example.com",
        ],
    )
    def test_skipped_for_automated_senders(self, sender: str):
        provider = _make_provider()
        with patch(
            "app.api.settings.load_settings", return_value=_enabled_settings()
        ):
            assert (
                send_auto_reply_if_needed(provider, 1, _make_email(sender=sender))
                is False
            )
        provider.create_draft.assert_not_called()


class TestAutoReplyDedupe:
    def test_does_not_reply_twice_to_same_sender(self):
        provider = _make_provider()
        with patch(
            "app.api.settings.load_settings", return_value=_enabled_settings()
        ):
            first = send_auto_reply_if_needed(provider, 1, _make_email())
            second = send_auto_reply_if_needed(
                provider, 1, _make_email(email_id="msg-2")
            )

        assert first is True
        assert second is False
        assert provider.create_draft.call_count == 1

    def test_same_sender_different_account_replies_twice(self):
        """Multi-account user: each account has its own OOO window."""
        provider = _make_provider()
        with patch(
            "app.api.settings.load_settings", return_value=_enabled_settings()
        ):
            first = send_auto_reply_if_needed(provider, 1, _make_email())
            second = send_auto_reply_if_needed(
                provider, 2, _make_email(email_id="msg-2")
            )

        assert first is True
        assert second is True
        assert provider.create_draft.call_count == 2


class TestAutoReplyProviderFailures:
    def test_returns_false_when_create_draft_fails(self):
        provider = _make_provider(draft_id=None)
        with patch(
            "app.api.settings.load_settings", return_value=_enabled_settings()
        ):
            assert (
                send_auto_reply_if_needed(provider, 1, _make_email()) is False
            )
        provider.send_draft.assert_not_called()

    def test_returns_false_when_send_draft_fails(self):
        provider = _make_provider(send_ok=False)
        with patch(
            "app.api.settings.load_settings", return_value=_enabled_settings()
        ):
            assert (
                send_auto_reply_if_needed(provider, 1, _make_email()) is False
            )
        # If send fails we must NOT mark as replied — a retry should be allowed
        # on the next sync tick (we're best-effort, not transactional).
        assert (
            None,  # account_id present, sender lowercase
        ) or True  # placeholder — actual dedupe assertion below
        # Re-attempting should produce another send_draft call.
        with patch(
            "app.api.settings.load_settings", return_value=_enabled_settings()
        ):
            provider.send_draft.return_value = True
            assert (
                send_auto_reply_if_needed(provider, 1, _make_email()) is True
            )
        assert provider.send_draft.call_count == 2

    def test_swallows_provider_exception(self):
        provider = _make_provider()
        provider.create_draft.side_effect = RuntimeError("provider blew up")
        with patch(
            "app.api.settings.load_settings", return_value=_enabled_settings()
        ):
            assert (
                send_auto_reply_if_needed(provider, 1, _make_email()) is False
            )


class TestSenderNames:
    def test_display_name_form(self):
        assert auto_reply_mod._sender_names('"Alex Doe" <alex@x.com>') == (
            "Alex Doe",
            "Alex",
        )

    def test_bare_address_humanised(self):
        assert auto_reply_mod._sender_names("alex.doe@acme.com") == (
            "Alex Doe",
            "Alex",
        )

    def test_single_token_address(self):
        assert auto_reply_mod._sender_names("support@stripe.com") == (
            "Support",
            "Support",
        )


class TestResolveMessageTokens:
    # The exact chip HTML AutoReplyModal stores for each placeholder.
    NAME_CHIP = (
        '<span class="ar-token" data-ar-token="name" '
        'contenteditable="false">Nom</span>'
    )
    FIRST_NAME_CHIP = (
        '<span class="ar-token" data-ar-token="first_name" '
        'contenteditable="false">Prénom</span>'
    )
    PERIOD_CHIP = (
        '<span class="ar-period-token" data-ar-token="absence_period" '
        'contenteditable="false">du 26 mars au 29 mars</span>'
    )

    def test_resolves_name_and_first_name(self):
        html = f"Bonjour {self.FIRST_NAME_CHIP},<br>Signé {self.NAME_CHIP}."
        out = auto_reply_mod._resolve_message_tokens(
            html, full_name="Alex Doe", first_name="Alex"
        )
        assert out == "Bonjour Alex,<br>Signé Alex Doe."

    def test_unwraps_absence_period_to_inner_text(self):
        html = f"Absent {self.PERIOD_CHIP} inclus."
        out = auto_reply_mod._resolve_message_tokens(
            html, full_name="Alex Doe", first_name="Alex"
        )
        # The wrapper is gone, the already-formatted date text remains.
        assert out == "Absent du 26 mars au 29 mars inclus."

    def test_noop_without_tokens(self):
        html = "Bonjour, je suis absent cette semaine."
        assert (
            auto_reply_mod._resolve_message_tokens(
                html, full_name="A B", first_name="A"
            )
            == html
        )

    def test_integration_resolves_tokens_in_sent_body(self):
        provider = _make_provider()
        email = _make_email(sender='"Marie Curie" <marie.curie@x.com>')
        msg = f"Bonjour {self.FIRST_NAME_CHIP}, je reviens bientôt."
        with patch(
            "app.api.settings.load_settings",
            return_value=_enabled_settings(message=msg),
        ):
            send_auto_reply_if_needed(provider=provider, account_id=1, email=email)
        body = provider.create_draft.call_args.kwargs["body"]
        assert body.startswith("Bonjour Marie, je reviens bientôt.")
        assert "data-ar-token" not in body  # chip fully resolved
