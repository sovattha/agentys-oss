# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from app import smart_routing


def test_draft_cache_honors_agentys_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTYS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("AGENTYS_DRAFT_CACHE_PATH", raising=False)
    monkeypatch.setattr(smart_routing, "_CACHE_FILE", None)

    assert smart_routing._get_cache_path() == tmp_path / "draft_cache.json"


def test_draft_cache_honors_explicit_path(tmp_path, monkeypatch):
    explicit = tmp_path / "nested" / "draft-cache.json"
    monkeypatch.setenv("AGENTYS_DRAFT_CACHE_PATH", str(explicit))
    monkeypatch.setattr(smart_routing, "_CACHE_FILE", None)

    assert smart_routing._get_cache_path() == explicit
    assert explicit.parent.exists()
