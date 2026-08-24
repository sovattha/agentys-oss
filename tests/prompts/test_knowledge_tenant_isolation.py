# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from pathlib import Path


def test_account_knowledge_does_not_fallback_to_global_memoire(monkeypatch):
    from app import _prompts_monolith as prompts

    monkeypatch.setattr(prompts, "load_knowledge_from_db", lambda account_id: None)

    def fail_global():
        raise AssertionError("global memoire.md fallback leaked into account-scoped path")

    monkeypatch.setattr(prompts, "load_knowledge_base", fail_global)

    assert prompts.load_account_knowledge(123) == ""


def test_legacy_knowledge_without_account_keeps_global_fallback(monkeypatch):
    from app import _prompts_monolith as prompts

    monkeypatch.setattr(prompts, "load_knowledge_base", lambda: "global kb")

    assert prompts.load_account_knowledge(None) == "global kb"


def test_smart_router_uses_account_safe_knowledge_loader():
    source = Path("app/smart_routing.py").read_text(encoding="utf-8")

    assert "load_account_knowledge" in source
    assert "load_knowledge_from_db" not in source
    assert "load_knowledge_base() or \"\"" not in source
