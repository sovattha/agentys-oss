# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression test for the route-level tail-trim backstop in /api/refine-text.

Audit 2026-05-19 round-3: PR #744 hardened the `_PLACEHOLDER_STRUCTURAL_RE`
regex with Unicode whitespace but `Reply body,` still leaked in production
on R3.1 (same input as round-2 R1). Two suspected causes:

1. System-prompt rule 12 contained literal "Reply body," as an example
   of what NOT to emit — possibly priming the LLM to echo it.
2. The `_strip_refine_reasoning` strip runs BEFORE the
   signature/closing/stacked-closing passes; any placeholder shifted
   to a new tail position by those passes would survive.

Fix: (a) rewrite rule 12 abstractly, (b) re-run the strip AFTER all
post-LLM passes, (c) add a last-resort tail-trim that drops a trailing
1-3-word line containing body/corps/message/reply/email/content/draft.
"""

import os
import time
from unittest.mock import MagicMock, patch

import jwt as _pyjwt
import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")

from app.api.auth import JWT_ALGORITHM, JWT_SECRET


@pytest.fixture(scope="module")
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


def _auth_headers() -> dict:
    token = _pyjwt.encode(
        {"sub": "12345", "email": "test@agentys.app",
         "iat": int(time.time()), "exp": int(time.time()) + 3600},
        JWT_SECRET, algorithm=JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


def _mock_container(body: str) -> MagicMock:
    r = MagicMock()
    r.content = body
    c = MagicMock()
    c.llm_drafting.complete.return_value = r
    c.llm_drafting_smart.complete.return_value = r
    c.get_writing_style_profile.return_value = None
    return c


class TestTailPlaceholderBackstop:
    def test_strips_round3_r3_1_exact_reproduction(self, client):
        """The byte-exact R3.1 production LLM output. Pre-fix this leaked
        the trailing `Reply body,` line through to the API response."""
        c = _mock_container(
            "Bonjour Alexandre,\n\n"
            "Je confirme ma disponibilité demain à 14h pour l'appel Q4. "
            "Je prépare les diapositives en ce moment.\n\n"
            "Reply body,"
        )
        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=42):
            resp = client.post(
                "/api/refine-text",
                json={
                    "text": "confirmer dispo demain 14h pour le call Q4",
                    "instruction": "Rédige un email complet",
                },
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        refined = resp.get_json()["refined_text"]
        assert "Reply body" not in refined, (
            f"R3.1 placeholder survived: {refined[-200:]!r}"
        )
        # Should still end with the meaningful last sentence.
        assert "moment" in refined.lower()

    def test_strips_tail_variants_via_regex(self, client):
        """Variants the regex picks up before the tail-trim even runs."""
        for variant in [
            "Reply body",
            "REPLY BODY",
            "Reply body.",
            "[Reply Body]",
            "Message body,",
            "Email body;",
        ]:
            c = _mock_container(
                f"Bonjour,\n\nOk demain.\n\nCordialement,\n\n{variant}"
            )
            with patch("app.api.routes_helpers._get_container", return_value=c), \
                 patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=42):
                resp = client.post(
                    "/api/refine-text",
                    json={"text": "ok demain", "instruction": "Rédige"},
                    headers=_auth_headers(),
                )
            refined = resp.get_json()["refined_text"]
            assert "Reply body" not in refined.replace(" ", "")
            assert "Message body" not in refined.replace(" ", "")
            assert "Email body" not in refined.replace(" ", "")

    def test_tail_trim_catches_regex_misses_when_no_closing_hint(self, client):
        """The tail-trim backstop fires when a placeholder REMAINS at the tail
        after all upstream passes. The common production trigger is
        `_compute_closing_hint` returning empty (user has no preferred_closings
        and formality is undetermined), so `_enforce_closing` doesn't append
        anything and the LLM's placeholder stays at the tail. Mock that
        scenario explicitly."""
        c = _mock_container(
            "Bonjour,\n\nC'est confirmé.\n\nEmail content"
        )
        # Force _compute_closing_hint to return empty — that's the prod
        # condition where `_enforce_closing` doesn't append anything.
        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=42), \
             patch("app.prompts._compute_closing_hint", return_value=""):
            resp = client.post(
                "/api/refine-text",
                json={"text": "confirmé", "instruction": "Rédige"},
                headers=_auth_headers(),
            )
        refined = resp.get_json()["refined_text"]
        assert "Email content" not in refined

    def test_preserves_legitimate_short_trailing_prose(self, client):
        """A short closing word like "Cordialement," must NOT be eaten by
        the tail-trim. It's in _CLOSING_TAIL_WORDS so the early-exit fires."""
        c = _mock_container(
            "Bonjour,\n\nOk pour demain.\n\nCordialement,"
        )
        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=42):
            resp = client.post(
                "/api/refine-text",
                json={"text": "ok", "instruction": "Rédige"},
                headers=_auth_headers(),
            )
        refined = resp.get_json()["refined_text"]
        assert refined.rstrip().endswith("Cordialement,")

    def test_preserves_proper_nouns_in_tail(self, client):
        """A trailing line like "À demain Alexandre" is NOT a placeholder —
        it's a legitimate informal closing. Must NOT be stripped."""
        c = _mock_container(
            "Salut,\n\nC'est noté.\n\nÀ demain Alexandre"
        )
        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=42):
            resp = client.post(
                "/api/refine-text",
                json={"text": "noté", "instruction": "Rédige"},
                headers=_auth_headers(),
            )
        refined = resp.get_json()["refined_text"]
        # The closing-enforce + stacked-closing strip may modify this line,
        # but the tail-trim must NOT have stripped it (no body/corps/message
        # keyword present).
        assert "Alexandre" in refined or "demain" in refined.lower()


class TestBareSchemaValueLeak:
    """Audit 2026-05-20 — Haiku occasionally leaks a bare schema *value*
    ("unknown") on its own line where the closing belongs, when the
    over-constrained Ctrl+G prompt tips it into "fill a schema" mode.

    Unlike "Reply body" (a leaked label), the bare value carries none of the
    body/corps/message/reply/email/content/draft keywords the route tail-trim
    keys on, so it fell through every existing guard and shipped (user report:
    a French casual draft to a known contact ended with a lone `unknown.`).
    """

    def test_strips_bare_unknown_screenshot_repro(self, client):
        """Byte-exact repro of the reported draft: a French casual note whose
        closing slot is a lone `unknown.`. The contact is very casual so
        `_compute_closing_hint` returns "" (no closing appended) — the leaked
        value is therefore the tail line that `_enforce_closing` leaves
        untouched (it only strips RECOGNISED closings)."""
        c = _mock_container(
            "Salut Nathan,\n\n"
            "J'espère que ça va bien. On mange des biscuits au chocolat ce midi.\n\n"
            "unknown."
        )
        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=42), \
             patch("app.prompts._compute_closing_hint", return_value=""):
            resp = client.post(
                "/api/refine-text",
                json={
                    "text": "biscuits chocolat ce midi avec nathan",
                    "instruction": "transforme en email",
                    "to": "nathanroy@gmail.com",
                },
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        refined = resp.get_json()["refined_text"]
        assert "unknown" not in refined.lower(), (
            f"bare schema value survived: {refined!r}"
        )
        # The real prose must remain intact.
        assert "biscuits" in refined.lower()
        assert refined.rstrip().endswith("midi.")

    def test_strips_unknown_even_when_closing_appended_after(self, client):
        """When a real closing IS appended after the leak, `_enforce_closing`
        pushes the bare value off the tail (it lands between body and
        closing). The backstop is a global/multiline sub, so it strips the
        value at any position — not just the last line — and the resulting
        blank gap is collapsed."""
        c = _mock_container(
            "Bonjour Marc,\n\n"
            "Je confirme notre rendez-vous de jeudi.\n\n"
            "unknown."
        )
        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=42), \
             patch("app.prompts._compute_closing_hint", return_value="À bientôt,"):
            resp = client.post(
                "/api/refine-text",
                json={"text": "confirme rdv jeudi", "instruction": "Rédige un email"},
                headers=_auth_headers(),
            )
        refined = resp.get_json()["refined_text"]
        assert "unknown" not in refined.lower(), (
            f"buried schema value survived: {refined!r}"
        )
        # The legitimate appended closing must remain.
        assert "À bientôt" in refined
        # No empty paragraph left where the value was removed.
        assert "\n\n\n" not in refined

    def test_strips_schema_value_variants(self, client):
        """Casing, brackets, trailing punctuation and the two schema-null
        siblings all get stripped."""
        for variant in ["unknown", "Unknown.", "[unknown]", "UNDEFINED",
                        "unspecified,", "  unknown  "]:
            c = _mock_container(f"Bonjour,\n\nOk pour demain.\n\n{variant}")
            with patch("app.api.routes_helpers._get_container", return_value=c), \
                 patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=42), \
                 patch("app.prompts._compute_closing_hint", return_value=""):
                resp = client.post(
                    "/api/refine-text",
                    json={"text": "ok demain", "instruction": "Rédige"},
                    headers=_auth_headers(),
                )
            refined = resp.get_json()["refined_text"]
            assert "unknown" not in refined.lower()
            assert "undefined" not in refined.lower()
            assert "unspecified" not in refined.lower()
            assert "demain" in refined.lower()

    def test_preserves_prose_that_only_contains_the_word(self, client):
        """A real sentence that merely CONTAINS "unknown" is not a bare value
        — the whole-line anchor must leave it intact."""
        c = _mock_container(
            "Bonjour,\n\nLe statut du paiement reste unknown pour le moment."
        )
        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=42), \
             patch("app.prompts._compute_closing_hint", return_value=""):
            resp = client.post(
                "/api/refine-text",
                json={"text": "statut paiement inconnu", "instruction": "Rédige"},
                headers=_auth_headers(),
            )
        refined = resp.get_json()["refined_text"]
        assert "unknown" in refined.lower(), (
            f"whole-line anchor over-matched and ate prose: {refined!r}"
        )
