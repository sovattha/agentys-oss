# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Starter Quick Steps pack — locks the propose-don't-push contract.

Three invariants we never want to regress on:

1. Every starter rule passes the schema validator. A starter that ships
   with an invalid payload would 500 the editor on first load, before
   the user has any way to delete it.
2. Every starter ships ``enabled=False`` and ``autoEnabled=True``. The
   pack is automatic-ready, but disabled — no auto-fire happens before
   the user enables a rule in Settings.
3. UUIDs are deterministic across calls. The backfill script relies on
   this for idempotence: re-running must NOT insert duplicates with
   different ids.
"""
from __future__ import annotations

import pytest

from app.quicksteps.defaults import build_default_quick_steps, starter_pack_names
from app.quicksteps.schema import validate_quick_step


class TestStarterPack:
    def test_every_rule_validates(self):
        """Each rule must pass `validate_quick_step` as-is. A broken
        starter would 500 the editor on first load."""
        for rule in build_default_quick_steps(account_email="x@y.com"):
            cleaned = validate_quick_step(rule)
            assert cleaned["name"] == rule["name"]

    def test_all_starters_ship_auto_ready_but_disabled(self):
        """Ready, don't run — every starter is preconfigured for automatic
        mode, but disabled until the user opts in."""
        for rule in build_default_quick_steps(account_email="x@y.com"):
            assert rule["autoEnabled"] is True, (
                f"Starter rule {rule['name']!r} does not ship in AUTO mode. "
                "The editor should be ready to run it automatically once "
                "the user enables the rule."
            )
            assert rule["enabled"] is False, (
                f"Starter rule {rule['name']!r} ships enabled. Starter rules "
                "must stay disabled in Settings until the user turns them on."
            )

    def test_ids_are_deterministic(self):
        """uuid5(name) — re-running the backfill must not duplicate rules."""
        first = build_default_quick_steps(account_email="x@y.com")
        second = build_default_quick_steps(account_email="x@y.com")
        assert [r["id"] for r in first] == [r["id"] for r in second]

    def test_ids_are_account_independent(self):
        """The starter id derives from the rule name, not the account.
        Two different accounts get the same id for the same starter rule
        — keeps cross-account analytics clean."""
        a = build_default_quick_steps(account_email="alice@x.com")
        b = build_default_quick_steps(account_email="bob@y.com")
        assert [r["id"] for r in a] == [r["id"] for r in b]

    def test_starter_pack_names_matches_rules(self):
        """The names exposed by ``starter_pack_names`` are the contract
        with the backfill script — they must match the actual rule names
        1:1, in the same order."""
        names_from_helper = list(starter_pack_names())
        names_from_rules = [r["name"] for r in build_default_quick_steps()]
        assert names_from_helper == names_from_rules

    def test_expected_rule_names_present(self):
        """Pin the pack contents. Adding a rule is fine; renaming or
        removing one breaks Settings.tsx's discovery surface (which
        hard-codes some of these names) and the descriptions seed script."""
        names = set(starter_pack_names())
        for required in (
            "Follow-up new thread",
            "Follow-up existing thread",
            "Archive after reply",
            "Accept meeting invitation",
        ):
            assert required in names, (
                f"Starter rule {required!r} is referenced by name elsewhere "
                "(Settings.tsx discovery / seed_quickstep_descriptions). "
                "Rename or removal is a breaking change."
            )

    def test_conditions_use_v2_match_mode_shape(self):
        """The starter pack ships v2 {type, match_mode} conditions
        directly. A legacy-shape starter would still validate — migration
        upgrades it — but the seed path JSON-dumps these raw, so they must
        be authored in the canonical shape."""
        rules = {r["name"]: r for r in build_default_quick_steps(account_email="x@y.com")}

        nudge = rules["Follow-up existing thread"]["triggers"]
        assert {"type": "email_text", "match_mode": "body", "value": "?"} in nudge

        invite = rules["Accept meeting invitation"]["triggers"]
        assert {"type": "calendar_invite", "match_mode": "any", "value": "true"} in invite
        assert {"type": "calendar_invite", "match_mode": "free", "value": "true"} in invite


class TestFollowupBodyLocalization:
    """The follow-up draft body is seeded in the account's language so a FR
    account never gets an English draft baked into its DB. The rule *name*
    stays English (discovery contract) — only the editable body is localized.
    """

    _FOLLOWUP_RULES = ("Follow-up new thread", "Follow-up existing thread")

    def _bodies(self, language: str | None = None) -> list[str]:
        kwargs = {} if language is None else {"language": language}
        rules = {r["name"]: r for r in build_default_quick_steps(account_email="x@y.com", **kwargs)}
        return [rules[name]["actions"][0]["payload"]["body"] for name in self._FOLLOWUP_RULES]

    def test_default_language_is_french(self):
        for body in self._bodies():
            assert "Bonjour" in body
            assert "Cordialement," in body

    def test_english_language_seeds_english_body(self):
        for body in self._bodies("en"):
            assert "Just wanted to follow up" in body
            assert "Sincerely," in body
            assert "Bonjour" not in body

    def test_spanish_language_seeds_spanish_body(self):
        for body in self._bodies("es"):
            assert "Hola" in body
            assert "Atentamente," in body

    def test_unknown_language_falls_back_to_french(self):
        for body in self._bodies("de"):
            assert "Bonjour" in body

    def test_locale_tag_variant_resolves(self):
        # preferred_language can arrive as a full BCP-47 tag (en-US, fr-CA).
        for body in self._bodies("en-US"):
            assert "Sincerely," in body

    def test_body_carries_resolvable_first_name_chip(self):
        # The body is editor HTML with a first-name {x} chip; the backend
        # renderer resolves it and flattens the markup to plain text.
        from app.quicksteps.handlers.create_snoozed_followup_draft import _render_body

        for body in self._bodies("en"):
            assert 'data-ar-token="recipient_first_name"' in body
            rendered = _render_body(
                body, recipient_addr="alex.doe@acme.com", original_subject="x",
            )
            assert rendered == (
                "Hi Alex,\n\n"
                "Just wanted to follow up on my last email. "
                "Let me know if you need anything from my side.\n\n"
                "Sincerely,"
            )
            assert "<div>" not in rendered


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
