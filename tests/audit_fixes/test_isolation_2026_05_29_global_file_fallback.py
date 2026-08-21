# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit 2026-05-29 — global-file fallback cross-tenant KB leak.

Bug: when a web/multi-tenant request resolved a positive ``account_id`` but the
per-account knowledge base lookup MISSED, three code paths fell back to the
process-global ``knowledge/memoire.md`` and returned ANOTHER tenant's profile,
contacts, tone rules and "Savoir" facts:

  - ``MemoryManager.get_memory``        (sink for GET /api/memory family)
  - ``DrafterAgent._resolve_knowledge`` (KB injected into draft prompts)
  - ``CriticAgent._resolve_knowledge``  (KB injected into critic prompts)

Fix: when ``account_id`` is set, a DB miss returns "" — the global file is read
ONLY when there is no account (Tauri desktop single-user).

Run: pytest tests/audit_fixes/test_isolation_2026_05_29_global_file_fallback.py -v
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

TENANT_A_PII = "## Profil — Nom complet: Crypto Université\nContacts: Alexandre, Nathan\n"


# --------------------------------------------------------------------------- #
# MemoryManager.get_memory
# --------------------------------------------------------------------------- #

def _make_manager(tmp_path, account_id):
    from app.memory_manager import MemoryManager
    mem = tmp_path / "memoire.md"
    mem.write_text(TENANT_A_PII, encoding="utf-8")
    hist = tmp_path / "history.json"
    return MemoryManager(memory_file=mem, history_file=hist, account_id=account_id)


def test_get_memory_web_account_db_miss_returns_empty_not_global(tmp_path):
    """account_id set + DB miss → "" (NOT the global memoire.md of tenant A)."""
    mgr = _make_manager(tmp_path, account_id=777)
    with patch("app._prompts_monolith.load_knowledge_from_db", return_value=None):
        out = mgr.get_memory()
    assert out == "", "web account must not read the global memoire.md on a DB miss"
    assert "Crypto Université" not in out


def test_get_memory_web_account_db_hit_returns_own_kb(tmp_path):
    """account_id set + DB hit → that account's own KB."""
    mgr = _make_manager(tmp_path, account_id=777)
    with patch("app._prompts_monolith.load_knowledge_from_db", return_value="OWN_KB_777"):
        out = mgr.get_memory()
    assert out == "OWN_KB_777"


def test_get_memory_no_account_reads_global_file_desktop(tmp_path):
    """account_id None (Tauri desktop single-user) still reads memoire.md."""
    mgr = _make_manager(tmp_path, account_id=None)
    out = mgr.get_memory()
    assert "Crypto Université" in out, "desktop single-user behaviour must be preserved"


# --------------------------------------------------------------------------- #
# DrafterAgent / CriticAgent _resolve_knowledge
# --------------------------------------------------------------------------- #

class _Stub:
    """Minimal carrier for the only attribute _resolve_knowledge reads."""
    def __init__(self, account_id):
        self.account_id = account_id


@pytest.mark.parametrize("agent_path", ["DrafterAgent", "CriticAgent"])
def test_agent_resolve_knowledge_web_account_db_miss_returns_empty(agent_path):
    """A draft/critic prompt for a web account must NOT receive another
    tenant's global memoire.md when the per-account KB is empty."""
    import app.agents as agents_mod
    cls = getattr(agents_mod, agent_path)
    stub = _Stub(account_id=42)
    with patch("app.prompts.load_knowledge_from_db", return_value=None), \
         patch("app.agents.load_knowledge_base", return_value=TENANT_A_PII) as glob:
        out = cls._resolve_knowledge(stub)
    assert out == ""
    glob.assert_not_called()


@pytest.mark.parametrize("agent_path", ["DrafterAgent", "CriticAgent"])
def test_agent_resolve_knowledge_no_account_uses_global(agent_path):
    """No account (desktop) → load_knowledge_base() global file, unchanged."""
    import app.agents as agents_mod
    cls = getattr(agents_mod, agent_path)
    stub = _Stub(account_id=None)
    with patch("app.prompts.load_knowledge_from_db", return_value=None), \
         patch("app.agents.load_knowledge_base", return_value="GLOBAL_KB") as glob:
        out = cls._resolve_knowledge(stub)
    assert out == "GLOBAL_KB"
    glob.assert_called_once()


@pytest.mark.parametrize("agent_path", ["DrafterAgent", "CriticAgent"])
def test_agent_resolve_knowledge_web_account_db_hit(agent_path):
    import app.agents as agents_mod
    cls = getattr(agents_mod, agent_path)
    stub = _Stub(account_id=42)
    with patch("app.prompts.load_knowledge_from_db", return_value="OWN_42"), \
         patch("app.agents.load_knowledge_base", return_value="GLOBAL_KB") as glob:
        out = cls._resolve_knowledge(stub)
    assert out == "OWN_42"
    glob.assert_not_called()
