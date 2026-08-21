# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Per-contact greeting/closing override construction for the compose path.

Covers two user-reported defects (2026-05-21, contact ``nathan.roy@corp.example``):

1. **Double-interpellation** — a stored ``preferred_greeting`` that already
   names the contact ("Salut Nathan,") had the nickname blindly appended,
   producing "Salut Nathan, Nat,". The fix lives in
   :func:`build_mandatory_opening`.

2. **Per-contact closing ignored** — the compose path never enforced
   ``preferred_closing`` ("A+"), so the LLM defaulted to "À bientôt,". The fix
   adds :func:`resolve_mandatory_closing` + a hard "CLÔTURE OBLIGATOIRE" rule
   threaded through the system/user/regen prompt builders and returned by
   :func:`resolve_per_contact_overrides` (now a 4-tuple).

Both compose paths (DraftService and the legacy inline ``_build_compose_prompts``)
share these helpers, so testing the helpers + the builders covers both.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.application.dto.draft_context import DraftContext
from app.application.services._compose_path import (
    build_compose_system_prompt,
    build_compose_user_prompt,
    build_mandatory_opening,
    build_regen_user_prompt,
    resolve_contact_override_data,
    resolve_mandatory_closing,
    resolve_per_contact_overrides,
)

# Same person, two addresses (the screenshot bug): override configured on the
# work work address, compose hitting the unconfigured gmail address.
_WORK = "nathan.roy@corp.example"
_GMAIL = "nathanroy@gmail.com"


def _system_text(segments) -> str:
    """Flatten a list[SystemSegment] to one string for substring assertions."""
    return "\n\n".join(getattr(s, "text", str(s)) for s in segments)


# ---------------------------------------------------------------------------
# build_mandatory_opening — the greeting-construction fix
# ---------------------------------------------------------------------------

class TestBuildMandatoryOpening:
    def test_no_nickname_returns_none(self):
        # Nothing to enforce without a nickname.
        assert build_mandatory_opening("Bonjour,", None) is None
        assert build_mandatory_opening("Bonjour,", "") is None

    def test_template_greeting_expands_with_nickname(self):
        # The current stored form for the reported contact.
        assert build_mandatory_opening("Bonjour {first_name},", "Nat") == "Bonjour Nat,"

    def test_literal_greeting_with_name_substitutes_nickname(self):
        # THE BUG: legacy literal greeting already names the contact. We must
        # NOT produce "Salut Nathan, Nat," — swap the name for the nickname.
        result = build_mandatory_opening("Salut Nathan,", "Nat")
        assert result == "Salut Nat,"
        assert "Nathan" not in result

    def test_literal_greeting_lowercase_is_capitalised(self):
        assert build_mandatory_opening("salut nathan,", "Nat") == "Salut Nat,"

    def test_bare_greeting_word_appends_nickname(self):
        # Pre-existing behaviour preserved.
        assert build_mandatory_opening("Salut", "kiki") == "Salut kiki,"

    def test_bare_greeting_word_with_trailing_comma_no_double_comma(self):
        # Sibling defect: "Bonjour," + nickname must not become "Bonjour, Nat,".
        assert build_mandatory_opening("Bonjour,", "Nat") == "Bonjour Nat,"

    def test_title_addressee_kept_verbatim(self):
        # A title greeting must keep its title — never inject the nickname.
        assert build_mandatory_opening("Bonjour Maître,", "Nat") == "Bonjour Maître,"

    def test_generic_addressee_kept_verbatim(self):
        assert build_mandatory_opening("Bonjour à tous,", "Nat") == "Bonjour à tous,"

    def test_none_greeting_falls_back_to_salut(self):
        assert build_mandatory_opening(None, "Nat") == "Salut Nat,"

    def test_unknown_template_token_falls_back_cleanly(self):
        # A truly unsupported token ({company} is not first_name/last_name/
        # civility) leaks braces from the expander → must fall back to the
        # literal "Salut <nickname>," rather than leaking "{company}".
        result = build_mandatory_opening("Bonjour {company},", "Nat")
        assert "{" not in result
        assert result == "Salut Nat,"

    def test_supported_template_tokens_expand_without_fallback(self):
        # {civility}/{last_name} ARE handled by the expander (civility→empty,
        # last_name→first_name fallback), so this expands cleanly, no fallback.
        result = build_mandatory_opening("Bonjour {civility} {last_name},", "Nat")
        assert "{" not in result
        assert result == "Bonjour Nat,"


# ---------------------------------------------------------------------------
# resolve_mandatory_closing — the closing-enforcement fix
# ---------------------------------------------------------------------------

class TestResolveMandatoryClosing:
    def test_plain_closing_used_verbatim(self):
        # No comma is appended — "A+" was stored without one on purpose.
        assert resolve_mandatory_closing("A+") == "A+"

    def test_closing_with_comma_preserved(self):
        assert resolve_mandatory_closing("Cordialement,") == "Cordialement,"

    def test_whitespace_is_stripped(self):
        assert resolve_mandatory_closing("  Merci,  ") == "Merci,"

    def test_none_returns_none(self):
        assert resolve_mandatory_closing(None) is None

    def test_empty_or_blank_returns_none(self):
        assert resolve_mandatory_closing("") is None
        assert resolve_mandatory_closing("   ") is None

    def test_no_closing_sentinel_filtered(self):
        # The onboarding "(no closing or just name)" sentinel must never be
        # promoted to a hard closing rule.
        assert resolve_mandatory_closing("(no closing or just name)") is None


# ---------------------------------------------------------------------------
# build_compose_system_prompt — closing directive emission
# ---------------------------------------------------------------------------

class TestComposeSystemPromptClosing:
    def test_closing_directive_present_when_set(self):
        segs = build_compose_system_prompt(
            style_context="", knowledge_base="",
            mandatory_opening="Bonjour Nat,", tone_directive=None,
            mandatory_closing="A+",
        )
        text = _system_text(segs)
        assert "CLÔTURE OBLIGATOIRE" in text
        assert "«A+»" in text

    def test_no_closing_directive_when_none(self):
        segs = build_compose_system_prompt(
            style_context="", knowledge_base="",
            mandatory_opening="Bonjour Nat,", tone_directive=None,
            mandatory_closing=None,
        )
        assert "CLÔTURE OBLIGATOIRE" not in _system_text(segs)

    def test_static_first_segment_unaffected_by_closing(self):
        # The closing lives in the dynamic (segment-2) block, so segment 0 must
        # stay byte-identical with/without a closing — protects prompt-cache.
        base = build_compose_system_prompt("", "", None, None, None)
        with_closing = build_compose_system_prompt("", "", None, None, "A+")
        assert base[0].text == with_closing[0].text


# ---------------------------------------------------------------------------
# build_compose_user_prompt / build_regen_user_prompt — reinforcement
# ---------------------------------------------------------------------------

class TestComposeUserPromptClosing:
    def _ctx(self) -> DraftContext:
        return DraftContext(
            recipient_email="nathan.roy@corp.example",
            subject="Appareils",
            instructions="",
            knowledge_base="",
            user_email="me@example.com",
            account_id=6,
        )

    def test_user_prompt_reinforces_closing(self):
        up = build_compose_user_prompt(self._ctx(), "Bonjour Nat,", "A+")
        assert "Termine impérativement par la ligne exacte : A+" in up

    def test_user_prompt_no_closing_line_when_none(self):
        up = build_compose_user_prompt(self._ctx(), "Bonjour Nat,", None)
        assert "Termine impérativement" not in up

    def test_regen_prompt_reinforces_closing(self):
        crit = SimpleNamespace(risks=("placeholder",), self_score=40)
        rp = build_regen_user_prompt("ORIGINAL", crit, "Bonjour Nat,", "A+")
        assert "ORIGINAL" in rp
        assert "Clôture obligatoire : «A+»." in rp


# ---------------------------------------------------------------------------
# resolve_per_contact_overrides — end-to-end wiring on the reported data
# ---------------------------------------------------------------------------

class TestResolvePerContactOverridesRepro:
    """Drives the exact stored data for the user-reported contact through the
    DraftService resolver, with the writing-style profile injected via a fake
    container (no DB / no real-data dependency)."""

    def _patch_profile(self, monkeypatch, contact: dict) -> None:
        fake_profile = SimpleNamespace(
            typical_signature="Alexandre Simon",
            contact_profiles={"nathan.roy@corp.example": contact},
        )
        fake_container = SimpleNamespace(
            get_writing_style_profile=lambda account_id: fake_profile
        )
        monkeypatch.setattr(
            "app.infrastructure.container.get_container",
            lambda: fake_container,
        )

    def _ctx(self) -> DraftContext:
        return DraftContext(
            recipient_email="nathan.roy@corp.example",
            subject="Appareils musculation Nat",
            instructions="",
            knowledge_base="",
            user_email="me@example.com",
            account_id=6,
        )

    def test_current_stored_data_produces_clean_opening_and_closing(self, monkeypatch):
        # Account-6 live data: tokenised greeting + nickname + "A+" closing.
        self._patch_profile(monkeypatch, {
            "email": "nathan.roy@corp.example",
            "nickname": "Nat",
            "preferred_greeting": "Bonjour {first_name},",
            "preferred_closing": "A+",
            "formality_override": "casual",
        })
        opening, tone, signature, closing = resolve_per_contact_overrides(self._ctx())
        assert opening == "Bonjour Nat,"
        assert closing == "A+"
        assert signature == "Alexandre Simon"
        assert tone is not None  # casual → tutoiement directive

    def test_legacy_literal_greeting_no_longer_doubles(self, monkeypatch):
        # The stale literal greeting that produced the screenshot bug.
        self._patch_profile(monkeypatch, {
            "email": "nathan.roy@corp.example",
            "nickname": "Nat",
            "preferred_greeting": "Salut Nathan,",
            "preferred_closing": "A+",
            "formality_override": "casual",
        })
        opening, _tone, _sig, closing = resolve_per_contact_overrides(self._ctx())
        assert opening == "Salut Nat,"
        assert opening != "Salut Nathan, Nat,"
        assert closing == "A+"

    def test_returns_four_tuple(self, monkeypatch):
        self._patch_profile(monkeypatch, {
            "email": "nathan.roy@corp.example", "nickname": "Nat",
            "preferred_greeting": "Bonjour {first_name},", "preferred_closing": "A+",
        })
        result = resolve_per_contact_overrides(self._ctx())
        assert len(result) == 4

    def test_no_account_returns_four_nones(self):
        ctx = DraftContext(
            recipient_email="x@y.com", subject="s", instructions="",
            knowledge_base="", user_email="me@example.com", account_id=0,
        )
        assert resolve_per_contact_overrides(ctx) == (None, None, None, None)


# ---------------------------------------------------------------------------
# Legacy inline _build_compose_prompts — the LIVE default path
# ---------------------------------------------------------------------------

class TestLegacyBuildComposePromptsRepro:
    """USE_DRAFT_SERVICE_COMPOSE defaults False, so `_build_compose_prompts`
    (routes_misc) is the path the user's streaming compose actually hit.
    Inject a fake profile via the container so the assertions are deterministic
    and never touch the encrypted DB."""

    def _patch(self, monkeypatch, contact: dict) -> None:
        fake_profile = SimpleNamespace(
            typical_signature="Alexandre",
            reference_examples=[],  # build_style_guidance skips few-shot block
            contact_profiles={"nathan.roy@corp.example": contact},
        )
        fake_container = SimpleNamespace(
            get_writing_style_profile=lambda account_id: fake_profile
        )
        monkeypatch.setattr(
            "app.api.routes_helpers._get_container", lambda: fake_container
        )

    def test_live_path_clean_opening_and_hard_closing(self, monkeypatch):
        from app.api.routes_misc import _build_compose_prompts

        self._patch(monkeypatch, {
            "email": "nathan.roy@corp.example",
            "nickname": "Nat",
            "preferred_greeting": "Bonjour {first_name},",
            "preferred_closing": "A+",
            "formality_override": "casual",
        })
        system_segments, user_prompt, signature = _build_compose_prompts(
            to_email="nathan.roy@corp.example",
            subject="Appareils musculation Nat",
            instructions="Demande-lui quand il reçoit ses appareils de musculation",
            sender_name="Alexandre",
            account_id=6,
        )
        sys_text = _system_text(system_segments)
        # Opening: single clean interpellation, no doubled name.
        assert "OUVERTURE OBLIGATOIRE" in sys_text
        assert "«Bonjour Nat,»" in sys_text
        assert "Salut Nathan, Nat," not in sys_text
        # Closing: now a HARD rule (was absent → LLM defaulted to "À bientôt,").
        assert "CLÔTURE OBLIGATOIRE" in sys_text
        assert "«A+»" in sys_text
        assert "Termine impérativement par la ligne exacte : A+" in user_prompt
        assert signature == "Alexandre"

    def test_live_path_legacy_literal_greeting_not_doubled(self, monkeypatch):
        from app.api.routes_misc import _build_compose_prompts

        self._patch(monkeypatch, {
            "email": "nathan.roy@corp.example",
            "nickname": "Nat",
            "preferred_greeting": "Salut Nathan,",  # the stale literal that bugged
            "preferred_closing": "A+",
            "formality_override": "casual",
        })
        system_segments, _user_prompt, _sig = _build_compose_prompts(
            to_email="nathan.roy@corp.example",
            subject="Appareils musculation Nat",
            instructions="Demande-lui quand il reçoit ses appareils",
            sender_name="Alexandre",
            account_id=6,
        )
        sys_text = _system_text(system_segments)
        assert "«Salut Nat,»" in sys_text
        assert "Salut Nathan, Nat," not in sys_text


# ---------------------------------------------------------------------------
# resolve_contact_override_data — per-PERSON override resolution
# A contact configured on one address must personalise drafts to their other
# address. Exact-email match wins field-by-field; a same-person sibling only
# backfills the gaps. Conservative same-person test (audited for false
# positives): john@a must NOT inherit from john@b, info@a must NOT from info@b.
# ---------------------------------------------------------------------------

class TestResolveContactOverrideData:
    def _profiles(self) -> dict:
        return {
            _WORK: {
                "email": _WORK, "nickname": "Nat",
                "preferred_greeting": "Bonjour,", "preferred_closing": "A+",
                "formality_override": "casual",
            },
            _GMAIL: {
                "email": _GMAIL, "nickname": None, "preferred_greeting": None,
                "preferred_closing": None, "formality_override": None,
            },
        }

    def test_sibling_backfills_unconfigured_address(self):
        data = resolve_contact_override_data(self._profiles(), _GMAIL)
        assert data is not None
        assert data["nickname"] == "Nat"
        assert data["preferred_closing"] == "A+"
        assert data["preferred_greeting"] == "Bonjour,"
        assert data["formality_override"] == "casual"

    def test_exact_match_fields_take_priority_over_sibling(self):
        profiles = self._profiles()
        profiles[_GMAIL]["nickname"] = "Sovv"          # recipient's own value
        profiles[_GMAIL]["preferred_closing"] = "Ciao"  # recipient's own value
        data = resolve_contact_override_data(profiles, _GMAIL)
        # Own non-empty fields win; only the still-empty greeting is backfilled.
        assert data["nickname"] == "Sovv"
        assert data["preferred_closing"] == "Ciao"
        assert data["preferred_greeting"] == "Bonjour,"

    def test_fully_configured_recipient_returned_as_is(self):
        data = resolve_contact_override_data(self._profiles(), _WORK)
        assert data["nickname"] == "Nat"
        assert data["preferred_closing"] == "A+"

    def test_common_first_name_does_not_inherit_across_domains(self):
        profiles = {
            "john@acme.test": {"email": "john@acme.test", "nickname": None,
                               "preferred_closing": None},
            "john@globex.test": {"email": "john@globex.test", "nickname": "Johnny",
                                  "preferred_closing": "Cheers"},
        }
        data = resolve_contact_override_data(profiles, "john@acme.test")
        # A bare common first name is not a same-person signal across domains.
        assert data is None or (
            not data.get("nickname") and not data.get("preferred_closing")
        )

    def test_role_mailbox_does_not_inherit_across_domains(self):
        profiles = {
            "info@acme.test": {"email": "info@acme.test", "nickname": None},
            "info@globex.test": {"email": "info@globex.test", "nickname": "Acme Bot",
                                  "preferred_closing": "Regards"},
        }
        data = resolve_contact_override_data(profiles, "info@acme.test")
        assert data is None or (
            not data.get("nickname") and not data.get("preferred_closing")
        )

    def test_firstname_lastname_collision_across_domains_does_not_inherit(self):
        # F1/F2: two DIFFERENT people who share firstname.lastname at different
        # domains normalise-equal, but identical raw local-parts across domains
        # are ambiguous — personal tone/closing must NOT leak between them.
        profiles = {
            "jean.martin@client-a.test": {"email": "jean.martin@client-a.test"},
            "jean.martin@client-b.test": {"email": "jean.martin@client-b.test",
                                          "nickname": "Jeannot",
                                          "preferred_closing": "Bisous,",
                                          "formality_override": "casual"},
        }
        data = resolve_contact_override_data(profiles, "jean.martin@client-a.test")
        assert data is None or (
            not data.get("preferred_closing")
            and not data.get("formality_override")
            and not data.get("nickname")
        )

    def test_long_common_first_name_does_not_inherit_across_domains(self):
        # F3: a long single-token first name (christine) is not distinctive —
        # christine@a and christine@b are very likely different people.
        profiles = {
            "christine@a.test": {"email": "christine@a.test"},
            "christine@b.test": {"email": "christine@b.test", "nickname": "Chris",
                                 "preferred_closing": "xoxo"},
        }
        data = resolve_contact_override_data(profiles, "christine@a.test")
        assert data is None or (
            not data.get("nickname") and not data.get("preferred_closing")
        )

    def test_same_domain_format_variant_inherits(self):
        # Same org + a format variant of one identity → same person, safe.
        profiles = {
            "john.smith@acme.test": {"email": "john.smith@acme.test",
                                     "nickname": "JS", "preferred_closing": "Cheers"},
            "johnsmith@acme.test": {"email": "johnsmith@acme.test"},
        }
        data = resolve_contact_override_data(profiles, "johnsmith@acme.test")
        assert data is not None
        assert data["nickname"] == "JS"
        assert data["preferred_closing"] == "Cheers"

    def test_recipient_with_display_name_is_resolved(self):
        # F6: a "Name <email>" recipient must still resolve to the bare address.
        data = resolve_contact_override_data(self._profiles(), '"Nat" <%s>' % _GMAIL)
        assert data is not None
        assert data["nickname"] == "Nat"
        assert data["preferred_closing"] == "A+"

    def test_no_entry_and_no_sibling_returns_none(self):
        profiles = {_WORK: {"email": _WORK, "nickname": "Nat"}}
        assert resolve_contact_override_data(profiles, "random@stranger.test") is None

    def test_empty_or_missing_profiles_returns_none(self):
        assert resolve_contact_override_data({}, _GMAIL) is None
        assert resolve_contact_override_data(None, _GMAIL) is None


# ---------------------------------------------------------------------------
# resolve_per_contact_overrides — end-to-end sibling fallback (DraftService)
# ---------------------------------------------------------------------------

class TestResolvePerContactOverridesSiblingFallback:
    def _patch_profiles(self, monkeypatch, profiles: dict) -> None:
        fake_profile = SimpleNamespace(
            typical_signature="Alexandre Simon",
            contact_profiles=profiles,
        )
        fake_container = SimpleNamespace(
            get_writing_style_profile=lambda account_id: fake_profile
        )
        monkeypatch.setattr(
            "app.infrastructure.container.get_container", lambda: fake_container
        )

    def _ctx(self, recipient: str) -> DraftContext:
        return DraftContext(
            recipient_email=recipient, subject="Performances application",
            instructions="", knowledge_base="", user_email="me@acme.test",
            account_id=13,
        )

    def test_unconfigured_gmail_inherits_from_work_sibling(self, monkeypatch):
        self._patch_profiles(monkeypatch, {
            _WORK: {"email": _WORK, "nickname": "Nat",
                      "preferred_greeting": "Bonjour,", "preferred_closing": "A+",
                      "formality_override": "casual"},
            _GMAIL: {"email": _GMAIL, "nickname": None, "preferred_greeting": None,
                     "preferred_closing": None, "formality_override": None},
        })
        opening, tone, signature, closing = resolve_per_contact_overrides(
            self._ctx(_GMAIL)
        )
        assert opening == "Bonjour Nat,"
        assert closing == "A+"
        assert tone is not None  # casual inherited → tutoiement directive

    def test_common_first_name_no_cross_domain_inheritance(self, monkeypatch):
        self._patch_profiles(monkeypatch, {
            "john@acme.test": {"email": "john@acme.test"},
            "john@globex.test": {"email": "john@globex.test", "nickname": "Johnny",
                                 "preferred_closing": "Cheers"},
        })
        opening, _t, _s, closing = resolve_per_contact_overrides(
            self._ctx("john@acme.test")
        )
        assert opening is None
        assert closing is None

    def test_role_mailbox_no_cross_domain_inheritance(self, monkeypatch):
        self._patch_profiles(monkeypatch, {
            "info@acme.test": {"email": "info@acme.test"},
            "info@globex.test": {"email": "info@globex.test", "nickname": "Bot",
                                 "preferred_closing": "Regards"},
        })
        opening, _t, _s, closing = resolve_per_contact_overrides(
            self._ctx("info@acme.test")
        )
        assert opening is None
        assert closing is None

    def test_firstname_lastname_collision_no_inheritance(self, monkeypatch):
        # F1/F2 contained end-to-end: a different person who shares
        # firstname.lastname at another domain must not inherit tone/closing.
        self._patch_profiles(monkeypatch, {
            "jean.martin@client-a.test": {"email": "jean.martin@client-a.test"},
            "jean.martin@client-b.test": {"email": "jean.martin@client-b.test",
                                          "nickname": "Jeannot",
                                          "preferred_closing": "Bisous,",
                                          "formality_override": "casual"},
        })
        opening, tone, _s, closing = resolve_per_contact_overrides(
            self._ctx("jean.martin@client-a.test")
        )
        assert opening is None
        assert closing is None
        assert tone is None


class TestLegacyBuildComposePromptsSiblingFallback:
    """The LIVE default path (USE_DRAFT_SERVICE_COMPOSE=False): composing to the
    unconfigured gmail address must still emit the work sibling's opening +
    hard closing."""

    def _patch(self, monkeypatch, profiles: dict) -> None:
        fake_profile = SimpleNamespace(
            typical_signature="Alexandre", reference_examples=[],
            contact_profiles=profiles,
        )
        fake_container = SimpleNamespace(
            get_writing_style_profile=lambda account_id: fake_profile
        )
        monkeypatch.setattr(
            "app.api.routes_helpers._get_container", lambda: fake_container
        )

    def test_gmail_address_inherits_work_override(self, monkeypatch):
        from app.api.routes_misc import _build_compose_prompts

        self._patch(monkeypatch, {
            _WORK: {"email": _WORK, "nickname": "Nat",
                      "preferred_greeting": "Bonjour,", "preferred_closing": "A+",
                      "formality_override": "casual"},
            _GMAIL: {"email": _GMAIL, "nickname": None, "preferred_greeting": None,
                     "preferred_closing": None, "formality_override": None},
        })
        system_segments, user_prompt, _sig = _build_compose_prompts(
            to_email=_GMAIL,
            subject="Performances application",
            instructions="Demande-lui où il en est sur les performances",
            sender_name="Alexandre", account_id=13,
        )
        sys_text = _system_text(system_segments)
        assert "«Bonjour Nat,»" in sys_text
        assert "CLÔTURE OBLIGATOIRE" in sys_text
        assert "«A+»" in sys_text
        assert "Termine impérativement par la ligne exacte : A+" in user_prompt
