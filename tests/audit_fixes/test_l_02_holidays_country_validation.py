# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix L-2 (issue #545) — `GET /api/calendar/public-holidays` interpolait
le query param `country` directement dans l'URL upstream Nager.Date :

    url = f"https://date.nager.at/api/v3/PublicHolidays/{year}/{country}"

`request.args.get("country", "").strip().upper()` laissait passer `/`, `?`,
`#`, `%2F` — un caller pouvait donc pivoter sur d'autres routes de
date.nager.at via `?country=FR/../OtherEndpoint`. L'hostname étant fixé,
le SSRF interne est impossible, mais c'est un bug fonctionnel + path-
fragment injection upstream.

Fix : `_COUNTRY_RE = ^[A-Z]{2}$` et `_REGION_RE = ^(?:[A-Z]{2}-)?[A-Z0-9]{1,3}$`
appliqués au boundary HTTP (400 si invalide) + assertion défensive dans
`_fetch_nager_year` (raise ValueError si appelé avec un country invalide).

Run: `pytest tests/audit_fixes/test_l_02_holidays_country_validation.py -v`
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("flask_cors")


@pytest.fixture
def app():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


# Loopback bypass: calendar_routes_bp est dans `_guarded_blueprints`. Pour
# exercer la logique de validation sans monter un JWT, on hit en loopback
# (REMOTE_ADDR=127.0.0.1) — l'auth guard laisse passer les appels locaux.
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}


# --------------------------------------------------------------------------- #
# Reject: path-fragment injection in `country`
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("payload", [
    "FR/../OtherEndpoint",
    "FR/Available",
    "FR?foo=bar",
    "FR%2F..",
    "FR FR",          # space
    "F",              # too short
    "FRA",            # too long
    "F1",             # digit not allowed
    "..",
    "/",
    "*",
    # NB: `FR#anchor` n'est pas testé — les fragments d'URL (`#…`) sont
    # strip côté client avant transmission, donc ce vecteur n'atteint
    # jamais le serveur. La regex `_COUNTRY_RE` rejetterait quand même
    # un `#` reçu en byte direct, mais le test client Werkzeug le coupe.
])
def test_invalid_country_returns_400(client, payload):
    """L-2: any country that isn't ISO 3166-1 alpha-2 must be 400."""
    resp = client.get(
        f"/api/calendar/public-holidays?country={payload}&start=2026-01-01&end=2026-01-31",
        environ_base=LOOPBACK,
    )
    assert resp.status_code == 400, (
        f"country={payload!r} should be rejected with 400, got {resp.status_code}"
    )
    body = resp.get_json()
    assert "invalid country code" in (body.get("error") or "")


@pytest.mark.parametrize("payload", [
    "QC/..",
    "QC/Available",
    "CA-QC/..",
    "CA-QC?foo=bar",
    "QC QC",
    "Q1Q1",       # too long for unprefixed
    "CA-Q1Q1Q1",  # too long for prefixed
    "/",
    "*",
])
def test_invalid_region_returns_400(client, payload):
    """L-2: region must match ISO 3166-2 subdivision shape."""
    resp = client.get(
        f"/api/calendar/public-holidays?country=CA&region={payload}"
        "&start=2026-01-01&end=2026-01-31",
        environ_base=LOOPBACK,
    )
    assert resp.status_code == 400, (
        f"region={payload!r} should be rejected with 400, got {resp.status_code}"
    )
    body = resp.get_json()
    assert "invalid region code" in (body.get("error") or "")


# --------------------------------------------------------------------------- #
# Accept: well-formed ISO codes (no upstream fetch — Nager.Date stubbed)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("country,region", [
    ("FR", None),
    ("CA", "QC"),
    ("CA", "CA-QC"),
    ("AU", "NSW"),
    ("US", "CA"),
])
def test_valid_iso_codes_pass_validation(client, country, region):
    """L-2: well-formed codes proceed to the upstream fetch path."""
    qs = f"country={country}"
    if region:
        qs += f"&region={region}"
    qs += "&start=2026-01-01&end=2026-01-31"

    with patch("app.api.calendar_routes._fetch_nager_year", return_value=[]):
        resp = client.get(
            f"/api/calendar/public-holidays?{qs}",
            environ_base=LOOPBACK,
        )

    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert "holidays" in body
    assert "error" not in body or not body["error"]


# --------------------------------------------------------------------------- #
# Defense-in-depth: `_fetch_nager_year` itself rejects bad input
# --------------------------------------------------------------------------- #


def test_fetch_nager_year_rejects_invalid_country_directly():
    """L-2: defensive layer — even if a future caller forgets the boundary
    check, `_fetch_nager_year` raises before opening the URL."""
    from app.api.calendar_routes import _fetch_nager_year

    with pytest.raises(ValueError, match="invalid country code"):
        _fetch_nager_year("FR/..", 2026)
    with pytest.raises(ValueError, match="invalid country code"):
        _fetch_nager_year("foo/bar", 2026)
