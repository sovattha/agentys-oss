# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit fix M-8 (issue #542) — webhooks Slack/Teams/Discord sans allow-list.

Bug : les 3 adapters de notifications chat acceptaient n'importe quelle URL
HTTP comme `webhook_url` :

  * `app/discord_integration.py:288` (Discord `_send_webhook`)
    (les notifiers Slack/Teams de `slack_teams.py` ont depuis ete supprimes
    comme code mort ; le helper partage reste couvert ci-dessous)

Aucune validation du host. Un user (ou un attaquant en mode multi-tenant
futur) pouvait configurer `webhook_url=http://localhost:5050/api/dev/...`
et déclencher une SSRF outbound dès qu'un événement Agentys produit une
notification (création de brouillon, follow-up, erreur).

Fix : helper partagé `app/infrastructure/webhook_security.py:is_allowed_webhook_url`
+ allow-lists par vendor (`SLACK_HOSTS`, `TEAMS_HOSTS`, `DISCORD_HOSTS`).
HTTPS only, pas d'IP literal, pas de userinfo, host doit matcher l'allow-list.

Run: `pytest tests/audit_fixes/test_m_08_webhook_host_allowlist.py -v`
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.infrastructure.webhook_security import (
    DISCORD_HOSTS,
    SLACK_HOSTS,
    TEAMS_HOSTS,
    is_allowed_webhook_url,
)


# --------------------------------------------------------------------------- #
# Helper unit tests — couvrent le contrat de is_allowed_webhook_url.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("url", [
    None,
    "",
    "   ",
])
def test_empty_url_is_rejected(url):
    assert is_allowed_webhook_url(url, SLACK_HOSTS) is False


def test_slack_legitimate_url_is_allowed():
    url = "https://hooks.slack.com/services/T000/B000/abcdef"
    assert is_allowed_webhook_url(url, SLACK_HOSTS) is True


def test_teams_legitimate_legacy_url_is_allowed():
    url = "https://outlook.office.com/webhook/abc/IncomingWebhook/def"
    assert is_allowed_webhook_url(url, TEAMS_HOSTS) is True


def test_teams_legitimate_tenant_subdomain_is_allowed():
    """Power Automate / tenant-spécifique : `<tenant>.webhook.office.com`."""
    url = "https://contoso.webhook.office.com/webhookb2/abc/IncomingWebhook/def"
    assert is_allowed_webhook_url(url, TEAMS_HOSTS) is True


def test_discord_legitimate_url_is_allowed():
    url = "https://discord.com/api/webhooks/123/token"
    assert is_allowed_webhook_url(url, DISCORD_HOSTS) is True


def test_discord_legacy_discordapp_url_is_allowed():
    url = "https://discordapp.com/api/webhooks/123/token"
    assert is_allowed_webhook_url(url, DISCORD_HOSTS) is True


# --------------------------------------------------------------------------- #
# Reproduction: SSRF vectors MUST be rejected.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("url", [
    "http://localhost:5050/api/dev/reset-all-data",
    "http://127.0.0.1/api/admin",
    "http://[::1]/internal",
    "http://169.254.169.254/latest/meta-data/",  # AWS / GCP metadata
    "http://10.0.0.1/internal",
    "http://192.168.1.1/router-admin",
])
def test_internal_targets_are_rejected(url):
    """Loopback + private + link-local hosts MUST be rejected for ALL
    vendor allow-lists. This is the primary SSRF vector."""
    assert is_allowed_webhook_url(url, SLACK_HOSTS) is False
    assert is_allowed_webhook_url(url, TEAMS_HOSTS) is False
    assert is_allowed_webhook_url(url, DISCORD_HOSTS) is False


def test_http_scheme_is_rejected():
    """HTTPS only — even on the legitimate host."""
    url = "http://hooks.slack.com/services/T000/B000/abcdef"
    assert is_allowed_webhook_url(url, SLACK_HOSTS) is False


def test_userinfo_is_rejected():
    """`https://attacker.com@hooks.slack.com/...` — refus blanket pour
    éviter les pièges de parsing entre libs HTTP."""
    url = "https://attacker.com@hooks.slack.com/services/abc"
    assert is_allowed_webhook_url(url, SLACK_HOSTS) is False


def test_foreign_host_is_rejected_even_if_path_matches_pattern():
    """`https://evil.com/services/T000/B000/abc` — path looks Slack-like
    but host is not in allow-list. Must reject."""
    url = "https://evil.com/services/T000/B000/abc"
    assert is_allowed_webhook_url(url, SLACK_HOSTS) is False


def test_subdomain_of_allowed_host_is_rejected_unless_pattern():
    """Slack allow-list is exact `hooks.slack.com`; `api.slack.com` and
    `evil.hooks.slack.com.attacker.com` must NOT match."""
    assert is_allowed_webhook_url(
        "https://api.slack.com/services/x", SLACK_HOSTS
    ) is False
    assert is_allowed_webhook_url(
        "https://evil.hooks.slack.com.attacker.com/x", SLACK_HOSTS
    ) is False


def test_wildcard_pattern_does_not_match_bare_suffix():
    """`*.webhook.office.com` must require at least one label — i.e.
    `webhook.office.com` itself doesn't match (defense against eTLD-level
    wildcard misuse)."""
    # bare `webhook.office.com` is not in TEAMS_HOSTS allow-list.
    url = "https://webhook.office.com/x"
    assert is_allowed_webhook_url(url, TEAMS_HOSTS) is False


# --------------------------------------------------------------------------- #
# Adapter-level: each notifier MUST gate the outbound POST through the helper.
# --------------------------------------------------------------------------- #


def test_discord_send_webhook_blocks_internal_host(monkeypatch):
    """`DiscordBot._send_webhook` must reject non-allow-list hosts before
    the urllib call — otherwise an internal endpoint receives the POST."""
    from app.discord_integration import DiscordBot, DiscordConfig

    cfg = DiscordConfig(
        webhook_url="http://localhost:5050/api/admin/aggregate",
        enabled=True,
    )
    bot = DiscordBot(config=cfg)

    sentinel = MagicMock()
    monkeypatch.setattr(
        "app.discord_integration.urllib.request.urlopen", sentinel
    )

    sent = bot._send_webhook(content="leak")
    assert sent is False
    sentinel.assert_not_called()


def test_discord_send_webhook_allows_legit_url(monkeypatch):
    from app.discord_integration import DiscordBot, DiscordConfig

    cfg = DiscordConfig(
        webhook_url="https://discord.com/api/webhooks/123/token",
        enabled=True,
    )
    bot = DiscordBot(config=cfg)

    class _FakeResp:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        "app.discord_integration.urllib.request.urlopen",
        lambda *a, **kw: _FakeResp(),
    )

    sent = bot._send_webhook(content="ok")
    assert sent is True
