# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Regression tests for account-scoped provider resolution (2026-05-13)."""

from __future__ import annotations


def test_search_provider_fallback_never_uses_default_without_account(monkeypatch):
    from app.api import search

    def _boom(*_args, **_kwargs):
        raise AssertionError("default provider must not be created")

    monkeypatch.setattr("app.providers.factory.get_pooled_provider", _boom)

    assert search._search_via_provider("invoice", None, limit=5) == []


def test_labels_provider_resolution_fails_closed_for_web_without_oauth(monkeypatch):
    from app.api import labels
    from app.api import routes_helpers

    monkeypatch.setattr(
        routes_helpers,
        "_resolve_oauth_account_id_for_db_account",
        lambda _account_id: None,
    )
    monkeypatch.setattr(routes_helpers, "_is_web_request_context", lambda: True)

    assert labels._get_provider_for_db_account(123) is None
