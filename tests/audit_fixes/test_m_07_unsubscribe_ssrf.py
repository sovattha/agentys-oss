# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix M-7 (issue #541) → re-base sur l'helper centralisé safe_outbound
après Shannon pentest 2026-05-05 (issue #557, SSRF-VULN-02/03/06).

Historique :
- M-7 introduisait `_safe_outbound_url` / `_safe_urlopen` en local dans
  `routes_misc.py`. Ce code n'a apparemment jamais été mergé (les
  symboles n'existent pas dans la branche actuelle), donc cette suite
  testait du fantôme depuis quelques semaines.
- Le fix #557 a unifié la défense via `app.utils.safe_outbound`. Les
  tests de bas niveau vivent désormais dans
  `tests/audit_fixes/test_shannon_557_security_fixes.py` (classe
  `TestSafeOutbound`). Ce fichier garde uniquement les tests qui
  vérifient que la route `/api/newsletters/unsubscribe` refuse bien
  une URL d'attaquant — c'est le contrat utilisateur, pas l'API
  interne.

Run: `pytest tests/audit_fixes/test_m_07_unsubscribe_ssrf.py -v`
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("flask_cors")


REMOTE_ATTACKER = {"REMOTE_ADDR": "203.0.113.10"}


@pytest.fixture
def app():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_jwt_stub():
    fake_payload = {"sub": "1", "email": "user@example.com"}
    with patch("app.api.auth._decode_jwt", return_value=fake_payload):
        yield


@pytest.mark.parametrize("attacker_url", [
    "http://169.254.169.254/latest/meta-data/iam/",
    "http://10.0.0.1/secret",
    "http://192.168.1.1/router-admin",
    "http://metadata.google.internal/computeMetadata/v1/",
])
def test_try_http_unsubscribe_refuses_internal_targets(attacker_url):
    """SSRF-VULN-02/03/06: the unsubscribe helper must refuse RFC 1918,
    cloud metadata, and known internal hostnames."""
    from app.api.routes_misc import _try_http_unsubscribe

    # Stub DNS so private hostnames resolve to private IPs (and any other
    # hostname stays public-looking). _try_http_unsubscribe should refuse
    # at the SsrfBlocked gate before requests.request fires.
    def fake_dns(host, *args, **kwargs):
        # `metadata.google.internal` and the literal IP cases — both
        # already in our blocklist by IP form. The DNS stub just keeps
        # tests hermetic.
        if "169.254" in host or "10.0" in host or "192.168" in host:
            return [(2, 1, 6, "", (host if "." in host and host.replace(".", "").isdigit() else "10.0.0.1", 0))]
        if "metadata" in host:
            return [(2, 1, 6, "", ("169.254.169.254", 0))]
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    with patch("socket.getaddrinfo", side_effect=fake_dns), \
         patch("requests.request") as mock_req:
        ok, status, method = _try_http_unsubscribe(attacker_url)

    # Either we never hit `requests.request` (SsrfBlocked early), or the
    # method returned a refusal (False, 0, "none").
    assert ok is False, f"SSRF leak: {attacker_url} returned ok=True"
    if mock_req.call_count > 0:
        # If requests was called at all, it should NOT have been with the
        # private IP. Accept the call only if the URL was rewritten —
        # which our defense never does. So fail loudly.
        called_urls = [c.args[1] if len(c.args) > 1 else c.kwargs.get("url") for c in mock_req.call_args_list]
        for u in called_urls:
            assert "169.254" not in str(u)
            assert "10.0.0" not in str(u)
            assert "192.168" not in str(u)


def test_try_http_unsubscribe_allows_public_url():
    """Sanity: a legit-looking public URL must reach the request layer."""
    from app.api.routes_misc import _try_http_unsubscribe

    with patch(
        "socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("8.8.8.8", 0))],
    ), patch("requests.request") as mock_req:
        # Mock 200 OK
        from unittest.mock import MagicMock
        mock_req.return_value = MagicMock(status_code=200, headers={})
        ok, status, method = _try_http_unsubscribe(
            "https://list.mailchimp.com/unsubscribe?u=abc"
        )

    assert ok is True
    assert status == 200
    assert method == "rfc8058_post"
    # The forced allow_redirects=False is a defense-in-depth signal we
    # check via the kwargs.
    assert mock_req.call_args.kwargs.get("allow_redirects") is False


def test_no_raw_urlopen_remains_in_routes_misc():
    """Defense against future regression: routes_misc.py must not use
    `urllib.request.urlopen` for attacker-supplied URLs. The fix #557
    routes everything through `safe_request` from app.utils.safe_outbound."""
    import inspect
    from app.api import routes_misc
    src = inspect.getsource(routes_misc)
    lines = [
        ln for ln in src.splitlines()
        if "urllib.request.urlopen(" in ln
        and not ln.lstrip().startswith("#")
    ]
    assert lines == [], (
        "Raw urllib.request.urlopen() reintroduced in routes_misc.py:\n"
        + "\n".join(lines)
    )
