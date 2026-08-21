# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Validation des URLs de webhooks sortantes.

M-8 (audit security.md, issue #542) : les webhooks Slack / Teams / Discord
sont configurables côté user. Sans validation du host, un user (ou un
attaquant en mode multi-tenant futur) peut pointer le webhook vers un
endpoint interne (`http://localhost:5050/api/dev/reset-all-data`,
`http://169.254.169.254/...`) et déclencher une SSRF outbound dès qu'un
événement Agentys produit une notification.

Ce module fournit un helper unique partagé par les 3 adapters
(`SlackNotifier`, `TeamsNotifier`, `DiscordBot._send_webhook`).

Choix de design :
  * **Allow-list explicite par vendor** : on connaît les hosts officiels
    de chaque service (cf. `SLACK_HOSTS`, `TEAMS_HOSTS`, `DISCORD_HOSTS`).
    Tout pattern `*.suffix` est autorisé pour les sous-domaines tenant-
    spécifiques de Teams (`<tenant>.webhook.office.com`).
  * **HTTPS only** : les 3 services rejettent HTTP en pratique ; on bloque
    en amont pour éviter qu'un user copie-colle une URL `http://...` qui
    permettrait un MITM ou un loopback déguisé.
  * **Pas d'IP littérale** : empêche `http://127.0.0.1`, `[::1]`,
    `http://10.0.0.1`, `http://169.254.169.254` (AWS/GCP metadata) même
    si le host text du user matche par accident.
  * **Pas de userinfo** : `https://attacker.com@hooks.slack.com/` est
    parsé selon le RFC en host=`hooks.slack.com` mais certaines libs
    HTTP clientes interprètent différemment ; refus blanket.

`is_allowed_webhook_url` retourne `False` plutôt que de raise — l'appelant
décide quoi faire (typiquement : log + skip, ne pas crasher la boucle de
notification).
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Iterable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# Hosts autorisés par vendor. Sources :
# - Slack: https://api.slack.com/messaging/webhooks (host `hooks.slack.com`)
# - Teams: legacy `outlook.office.com/webhook/...` + nouveau format
#   tenant `<tenant>.webhook.office.com` (Power Automate)
# - Discord: officiel `discord.com/api/webhooks/...`, legacy `discordapp.com`
SLACK_HOSTS: tuple[str, ...] = ("hooks.slack.com",)
TEAMS_HOSTS: tuple[str, ...] = ("outlook.office.com", "*.webhook.office.com")
DISCORD_HOSTS: tuple[str, ...] = ("discord.com", "discordapp.com")


def _host_matches(host: str, pattern: str) -> bool:
    """Match exact ou suffixe via `*.subdomain.tld`.

    `*.webhook.office.com` matche `eu1.webhook.office.com` mais pas
    `webhook.office.com` lui-même (un pattern wildcard exige au moins un
    label devant) — empêche un pattern trop laxiste de devenir un wildcard
    de niveau eTLD.
    """
    host = host.lower()
    pattern = pattern.lower()
    if pattern.startswith("*."):
        suffix = pattern[2:]
        # Doit contenir au moins un label avant le suffix
        return host.endswith("." + suffix) and host != suffix
    return host == pattern


def _is_ip_literal(host: str) -> bool:
    """True si `host` est une IPv4/IPv6 literal — bloque les loopback et
    metadata services (169.254.169.254, fd00::/8, etc.) même quand le user
    aurait deviné le bon host text."""
    try:
        # Strip IPv6 brackets si présents.
        cleaned = host.strip("[]")
        ipaddress.ip_address(cleaned)
        return True
    except ValueError:
        return False


def is_allowed_webhook_url(
    url: str | None,
    allowed_host_patterns: Iterable[str],
) -> bool:
    """Validate an outbound webhook URL against an allow-list.

    Args:
        url: URL fournie par le user (peut être None / vide).
        allowed_host_patterns: hosts ou patterns `*.suffix` autorisés.

    Returns:
        True si l'URL est sûre à appeler ; False sinon (loggue le motif
        à WARNING). L'appelant doit traiter False comme « ne pas envoyer ».
    """
    if not url or not isinstance(url, str):
        return False

    try:
        parsed = urlparse(url.strip())
    except Exception as e:
        logger.warning("webhook URL rejected: parse error (%s)", e)
        return False

    # Schéma : HTTPS only.
    if parsed.scheme.lower() != "https":
        logger.warning(
            "webhook URL rejected: scheme=%r (HTTPS required)",
            parsed.scheme,
        )
        return False

    # Userinfo (login:pass@host) : refus blanket.
    if parsed.username or parsed.password:
        logger.warning("webhook URL rejected: contains userinfo")
        return False

    host = (parsed.hostname or "").lower()
    if not host:
        logger.warning("webhook URL rejected: empty host")
        return False

    # IP literal → refus (loopback, link-local, metadata).
    if _is_ip_literal(host):
        logger.warning("webhook URL rejected: IP literal host=%s", host)
        return False

    # Match contre l'allow-list.
    for pattern in allowed_host_patterns:
        if _host_matches(host, pattern):
            return True

    logger.warning(
        "webhook URL rejected: host=%s not in allow-list (%s)",
        host, ", ".join(allowed_host_patterns),
    )
    return False
