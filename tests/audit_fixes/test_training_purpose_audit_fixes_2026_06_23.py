# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for the Training-tab "does everything serve a purpose" audit fixes
(2026-06-23). Each improvement wired a previously dead/asymmetric Training
control into the live draft path.

Covered:
  #1  Format → Complexité (vocabulary) directive is built from the KB and
      reaches the STANDARD draft prompt (was stored + round-tripped but never
      read).
  #3  Per-contact preferred_closing is enforced as a hard sign-off on the
      REPLY path (was reply-side soft hint only; compose already enforced it).
  #4d POST /api/style/reanalyze re-derives the formality_level enum from the
      freshly measured formality_score (the enum used to stay stale).
  #6  The casual closing slot [1] wins for a casual reply via _closing_hint_for
      (the formal slot [0] used to always win, making the casual closing dead).
"""

from __future__ import annotations

from types import SimpleNamespace

from app.prompts.builders import (
    get_standard_draft_prompts,
    _segments_to_text,
    _build_vocab_rule,
)


def _render(result) -> str:
    segments, user_prompt = result
    return _segments_to_text(segments) + "\n" + user_prompt


# --------------------------------------------------------------------------- #
# #1 — Vocabulary (complexité) directive
# --------------------------------------------------------------------------- #


class TestVocabRule:
    def test_accessible_maps_to_plain_directive(self):
        out = _build_vocab_rule("## Format\n- **Vocabulaire**: accessible\n")
        assert "VOCABULARY" in out
        assert "plain" in out.lower() or "< 12" in out

    def test_elabore_maps_to_rich_directive(self):
        out = _build_vocab_rule("- **Vocabulaire**: elabore")
        assert "VOCABULARY" in out
        assert "rich" in out.lower() or "technical" in out.lower()

    def test_standard_emits_nothing(self):
        # "standard" is the neutral default — no directive (avoid prompt bloat).
        assert _build_vocab_rule("- **Vocabulaire**: standard") == ""

    def test_missing_marker_emits_nothing(self):
        assert _build_vocab_rule("## Format\n- **Longueur préférée**: concis") == ""
        assert _build_vocab_rule("") == ""

    def test_vocab_directive_reaches_standard_draft_prompt(self):
        """Integration: a KB trained to 'accessible' surfaces the VOCABULARY
        rule in the rendered STANDARD prompt. Pre-fix the control did nothing."""
        kb = "## Format\n- **Longueur préférée**: moyen\n- **Vocabulaire**: accessible\n"
        rendered = _render(get_standard_draft_prompts(
            sender="x@example.com",
            subject="Question",
            body="Peux-tu me confirmer la date ?",
            knowledge_base=kb,
            account_id=None,
        ))
        assert "VOCABULARY" in rendered


# --------------------------------------------------------------------------- #
# #3 — Per-contact preferred_closing enforced on the REPLY path
# --------------------------------------------------------------------------- #


class TestPerContactClosingReachesReplyPrompt:
    def test_contact_closing_enforced_in_french_reply(self, monkeypatch):
        # 5-tuple: (nickname, greeting, variant, formality_override, closing)
        monkeypatch.setattr(
            "app.prompts.builders._resolve_contact_overrides",
            lambda account_id, sender, detected_language: ("", "", "", "", "Bisous,"),
        )
        _, user_prompt = get_standard_draft_prompts(
            sender="ami@example.com",
            subject="Coucou",
            body="On se voit demain pour discuter du projet ?",
            account_id=42,
        )
        assert "Bisous," in user_prompt
        assert "MUST END WITH EXACTLY" in user_prompt

    def test_no_contact_closing_adds_no_directive(self, monkeypatch):
        monkeypatch.setattr(
            "app.prompts.builders._resolve_contact_overrides",
            lambda account_id, sender, detected_language: ("", "", "", "", ""),
        )
        _, user_prompt = get_standard_draft_prompts(
            sender="ami@example.com",
            subject="Coucou",
            body="On se voit demain ?",
            account_id=42,
        )
        assert "MUST END WITH EXACTLY" not in user_prompt

    def test_english_closing_skipped_on_french_reply(self, monkeypatch):
        """Language-clash guard: an English stored closing must NOT be forced
        onto a French reply (it would leak a wrong-language sign-off)."""
        monkeypatch.setattr(
            "app.prompts.builders._resolve_contact_overrides",
            lambda account_id, sender, detected_language: ("", "", "", "", "Best regards,"),
        )
        _, user_prompt = get_standard_draft_prompts(
            sender="ami@example.com",
            subject="Bonjour",
            body="Peux-tu me confirmer la date de la réunion de demain ?",
            account_id=42,
        )
        # The closing is skipped (clash) rather than leaked.
        assert "MUST END WITH EXACTLY" not in user_prompt
        assert "Best regards" not in user_prompt


# --------------------------------------------------------------------------- #
# #6 — Casual closing slot [1] wins for a casual reply (_closing_hint_for)
# --------------------------------------------------------------------------- #


class TestCasualClosingSlotSelection:
    def _stub_router(self, monkeypatch, closings):
        from app.smart_routing import SmartRouter  # noqa: F401  (import side effects)

        class _Prof:
            preferred_closings = closings
            preferred_greetings: list = []
            typical_signature = None

        class _Ctn:
            def get_writing_style_profile(self, account_id=None):
                return _Prof()

        monkeypatch.setattr(
            "app.infrastructure.container.get_container", lambda: _Ctn()
        )
        from app.smart_routing import SmartRouter as _SR
        return _SR, SimpleNamespace(_account_id=1)

    def test_casual_reply_picks_casual_slot(self, monkeypatch):
        SR, stub = self._stub_router(monkeypatch, ["Cordialement,", "À bientôt,"])
        # formality 2 = casual → casual slot [1] wins.
        assert SR._closing_hint_for(stub, 2, "FRENCH") == "À bientôt,"

    def test_formal_reply_keeps_formal_slot(self, monkeypatch):
        SR, stub = self._stub_router(monkeypatch, ["Cordialement,", "À bientôt,"])
        # formality 4 = formal → formal slot [0] wins (no reorder).
        assert SR._closing_hint_for(stub, 4, "FRENCH") == "Cordialement,"

    def test_single_closing_unaffected(self, monkeypatch):
        SR, stub = self._stub_router(monkeypatch, ["Cordialement,"])
        assert SR._closing_hint_for(stub, 2, "FRENCH") == "Cordialement,"


# --------------------------------------------------------------------------- #
# #4d — reanalyze re-derives the formality_level enum from the score
# --------------------------------------------------------------------------- #


class TestReanalyzeFormalityLevelSync:
    def _build(self, monkeypatch, score):
        # Stub the store so _build_profile starts from an empty base.
        class _Store:
            def load(self, account_id):
                return None

        class _Ctn:
            def get_writing_style_store(self):
                return _Store()

        monkeypatch.setattr(
            "app.infrastructure.container.get_container", lambda: _Ctn()
        )
        from app.api.style_inference import _build_profile
        return _build_profile(
            account_id=1,
            email_count=10,
            metrics={"formality_score": score},
            examples=[],
        )

    def test_high_score_yields_formal(self, monkeypatch):
        prof = self._build(monkeypatch, 0.9)
        assert prof.formality_level.value == "formal"

    def test_low_score_yields_casual(self, monkeypatch):
        prof = self._build(monkeypatch, 0.1)
        assert prof.formality_level.value == "casual"

    def test_mid_score_yields_mixed(self, monkeypatch):
        prof = self._build(monkeypatch, 0.5)
        assert prof.formality_level.value == "mixed"
        # And the continuous score is persisted too.
        assert abs(prof.formality_score - 0.5) < 1e-6


# --------------------------------------------------------------------------- #
# #2 — Compose-from-scratch injects learned rules (but NOT the FAQ)
# --------------------------------------------------------------------------- #


class TestComposeInjectsLearnedRules:
    def test_learned_rules_reach_compose_prompt(self, monkeypatch):
        from app.api import routes_misc

        sentinel = "Ne commence JAMAIS par Madame/Monsieur."
        monkeypatch.setattr(
            "app.prompts.builders._get_learning_section",
            lambda contact="", account_id=None, **kw: f"\n\nPRIORITÉ ABSOLUE\n\n{sentinel}",
        )
        system, user, _sig = routes_misc._build_compose_prompts(
            to_email="dest@example.com",
            subject="Bonjour",
            instructions="Rédige un email de relance",
            sender_name="Alex",
            account_id=0,  # skip profile/KB disk I/O; rules block still runs
        )
        text = "\n".join(getattr(s, "text", str(s)) for s in system)
        assert sentinel in text, (
            "Les règles apprises globales doivent gouverner aussi la compose, "
            "pas seulement les réponses (fix #2)."
        )

    def test_compose_does_not_inject_faq(self, monkeypatch):
        """The user asked: no FAQ grounding in compose-from-scratch. Verify the
        compose builder never pulls FAQ entries even when they exist."""
        from app.api import routes_misc

        called = {"faq": False}

        def _boom(*a, **k):
            called["faq"] = True
            return "Q: secret? / R: leaked"

        # _load_faq_entries_cached is the FAQ loader used by the reply path.
        monkeypatch.setattr(
            "app.smart_routing._load_faq_entries_cached", _boom, raising=False
        )
        monkeypatch.setattr(
            "app.prompts.builders._get_learning_section",
            lambda contact="", account_id=None, **kw: "",
        )
        system, user, _sig = routes_misc._build_compose_prompts(
            to_email="dest@example.com",
            subject="Bonjour",
            instructions="Rédige un email",
            sender_name="Alex",
            account_id=0,
        )
        text = "\n".join(getattr(s, "text", str(s)) for s in system) + "\n" + user
        assert called["faq"] is False
        assert "FAQ_VALIDÉES" not in text and "leaked" not in text


# --------------------------------------------------------------------------- #
# #4c — GET /api/writing-style/profile exposes the observed metrics
# --------------------------------------------------------------------------- #


class TestWritingStyleProfileEndpoint:
    def _auth(self):
        import time
        import jwt as _pyjwt
        from app.api.auth import JWT_ALGORITHM, JWT_SECRET
        tok = _pyjwt.encode(
            {"sub": "1", "email": "t@agentys.app",
             "iat": int(time.time()), "exp": int(time.time()) + 3600},
            JWT_SECRET, algorithm=JWT_ALGORITHM,
        )
        return {"Authorization": f"Bearer {tok}"}

    def test_endpoint_returns_metrics(self, monkeypatch):
        from app.api.app import create_app

        prof = SimpleNamespace(
            avg_sentence_length=14.0, sentence_length_variance=3.0,
            vocabulary_density=0.45, formality_score=0.72,
            emoji_frequency=0.1, exclamation_rate=0.2,
            avg_paragraph_count=2.0, email_count=37,
        )

        class _Store:
            def load(self, account_id):
                return prof

        class _Ctn:
            def get_writing_style_store(self):
                return _Store()

        monkeypatch.setattr(
            "app.api.routes_learning._resolve_account_id_for_user", lambda: 13
        )
        monkeypatch.setattr(
            "app.api.routes_learning._rh._get_container", lambda: _Ctn()
        )

        app = create_app(config={"TESTING": True})
        client = app.test_client()
        resp = client.get(
            "/api/writing-style/profile?account_id=13", headers=self._auth()
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()["profile"]
        assert abs(body["formality_score"] - 0.72) < 1e-6
        assert abs(body["avg_sentence_length"] - 14.0) < 1e-6
        assert body["email_count"] == 37

    def test_endpoint_returns_null_profile_when_absent(self, monkeypatch):
        from app.api.app import create_app

        class _Store:
            def load(self, account_id):
                return None

        class _Ctn:
            def get_writing_style_store(self):
                return _Store()

        monkeypatch.setattr(
            "app.api.routes_learning._resolve_account_id_for_user", lambda: 13
        )
        monkeypatch.setattr(
            "app.api.routes_learning._rh._get_container", lambda: _Ctn()
        )
        app = create_app(config={"TESTING": True})
        resp = app.test_client().get(
            "/api/writing-style/profile", headers=self._auth()
        )
        assert resp.status_code == 200
        assert resp.get_json()["profile"] is None
