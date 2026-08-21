# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression tests — audit 2026-05-14 (1824), F-01.

F-01 — the UTF-8 encoding-hygiene commit made every ``app/`` file reader
force ``encoding="utf-8"``. But data files already on disk were written by
the older code via ``Path.write_text()`` with NO ``encoding=`` — i.e. cp1252
on Windows, the documented primary dev box. ``read_text(encoding="utf-8")``
then raises ``UnicodeDecodeError`` on the first accented byte, and the
``except`` handlers treated that as "corrupt file": ``RoutingEngine._load``
called ``_init_defaults()`` → ``_save()`` which OVERWRITES the user's custom
rules with defaults; ``AuditLogger._load`` zeroed ``self._events``, lost on
the next ``_save()``.

The fix routes every such read through ``read_text_legacy_safe``, which falls
back to cp1252 and signals the caller to re-save as UTF-8. A genuinely corrupt
file (valid UTF-8, invalid JSON) must STILL fall back to the historical
behaviour — that path is asserted here too, so the fix is proven not to have
widened scope.
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")

from app.infrastructure.audit import AuditLogger
from app.infrastructure.text_io import read_text_legacy_safe
from app.routing import DEFAULT_RULES, RoutingEngine


def _write_legacy_cp1252(path, obj) -> None:
    """Write ``obj`` as JSON the way pre-hygiene code did on Windows:
    ``Path.write_text(json.dumps(..., ensure_ascii=False))`` with no
    ``encoding=`` → the platform default, cp1252."""
    path.write_bytes(json.dumps(obj, ensure_ascii=False).encode("cp1252"))


class TestReadTextLegacySafe:
    """``read_text_legacy_safe(path) -> (text, recovered)``."""

    def test_valid_utf8_returns_recovered_false(self, tmp_path):
        p = tmp_path / "f.json"
        p.write_text('{"clé": "valéur €"}', encoding="utf-8")
        text, recovered = read_text_legacy_safe(p)
        assert recovered is False
        assert text == '{"clé": "valéur €"}'

    def test_legacy_cp1252_file_is_recovered(self, tmp_path):
        p = tmp_path / "f.json"
        p.write_bytes('{"clé": "valéur"}'.encode("cp1252"))
        text, recovered = read_text_legacy_safe(p)
        assert recovered is True
        assert text == '{"clé": "valéur"}'


class TestRoutingEngineEncodingRecovery:
    """``RoutingEngine._load`` must never destroy a merely-unreadable file."""

    def test_legacy_cp1252_file_keeps_custom_rules(self, tmp_path):
        """The F-01 P0: a cp1252 routing_rules.json with a custom rule must
        load intact — NOT be overwritten with DEFAULT_RULES."""
        p = tmp_path / "routing_rules.json"
        _write_legacy_cp1252(p, {
            "rules": [
                {"id": "vip-müller", "name": "Priorité Müller",
                 "conditions": [], "action": "vip_notify"},
            ],
            "updated_at": "2026-05-14T00:00:00",
        })
        engine = RoutingEngine(filepath=p)
        assert "vip-müller" in engine.rules
        assert engine.rules["vip-müller"].name == "Priorité Müller"
        # exactly the one custom rule — defaults were NOT merged in
        assert len(engine.rules) == 1

    def test_legacy_cp1252_file_is_healed_to_utf8(self, tmp_path):
        """After recovery the file is re-saved as UTF-8, so the next load is
        clean (idempotent self-heal)."""
        p = tmp_path / "routing_rules.json"
        _write_legacy_cp1252(p, {
            "rules": [{"id": "r-é", "name": "Règle accentuée",
                       "conditions": [], "action": "skip"}],
            "updated_at": "2026-05-14T00:00:00",
        })
        RoutingEngine(filepath=p)
        # file on disk is now valid UTF-8 with the rule intact
        healed = json.loads(p.read_text(encoding="utf-8"))
        assert healed["rules"][0]["id"] == "r-é"
        # second load no longer needs the cp1252 fallback
        _, recovered = read_text_legacy_safe(p)
        assert recovered is False

    def test_genuinely_corrupt_json_still_falls_back_to_defaults(self, tmp_path):
        """A valid-UTF-8 but invalid-JSON file is genuine corruption — the
        historical ``_init_defaults()`` behaviour MUST be preserved (proves the
        fix did not widen scope)."""
        p = tmp_path / "routing_rules.json"
        p.write_text("{ this is not valid json", encoding="utf-8")
        engine = RoutingEngine(filepath=p)
        assert len(engine.rules) == len(DEFAULT_RULES)

    def test_missing_file_initializes_defaults(self, tmp_path):
        """No file on disk → defaults, unchanged behaviour."""
        p = tmp_path / "does_not_exist.json"
        engine = RoutingEngine(filepath=p)
        assert len(engine.rules) == len(DEFAULT_RULES)


class TestAuditLoggerEncodingRecovery:
    """``AuditLogger._load`` must not zero its event history on a cp1252 file."""

    def test_legacy_cp1252_file_keeps_events(self, tmp_path):
        """The F-01 P1 sibling: a cp1252 audit.json must load its events, not
        reset to ``[]`` (which the next ``_save()`` would persist, losing the
        log)."""
        p = tmp_path / "audit.json"
        _write_legacy_cp1252(p, {
            "events": [
                {"event_type": "draft_created", "success": True,
                 "details": {"sujet": "Réunion café"}},
            ],
        })
        audit = AuditLogger(filepath=p)
        assert len(audit._events) == 1
        assert audit._events[0]["details"]["sujet"] == "Réunion café"

    def test_legacy_cp1252_audit_file_is_healed_to_utf8(self, tmp_path):
        p = tmp_path / "audit.json"
        _write_legacy_cp1252(p, {
            "events": [{"event_type": "daemon_start",
                        "details": {"note": "démarré"}}],
        })
        AuditLogger(filepath=p)
        healed = json.loads(p.read_text(encoding="utf-8"))
        assert healed["events"][0]["details"]["note"] == "démarré"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
