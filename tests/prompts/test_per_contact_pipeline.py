# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""End-to-end test du pipeline per-contact (issue #454 audit, post-P0).

Vérifie que chaque champ extrait par l'onboarding et exposé dans la Settings UI
(`ContactStyleEditor.tsx`) fait effectivement son chemin jusqu'au prompt LLM
au moment du draft.

Champs persistés par `_persist_contact_profiles` (`onboarding/manager.py:2626`)
et exposés dans `ContactStyleProfile` (`writing_style.py:138`) :
    - nickname               → SURNOM/PRÉNOM D'APPEL
    - formality_override     → Formalité spécifique
    - preferred_greeting     → Salutation habituelle (template expansé)
    - preferred_closing      → Clôture habituelle
    - langue                 → LANGUAGE: Reply in <X>
    - langue_variante        → REGIONAL VARIANT: <X>

Path testé : `WritingStyleProfile.to_prompt_context(recipient_email=...)` →
`style_context` paramètre → `get_standard_draft_prompts(style_context=...)` →
`STANDARD_DRAFT_SYSTEM_PROMPT` (le bloc `{style_context}` est interpolé).

Si un futur refactor casse l'un de ces 6 chemins, ce module fail immédiatement.
"""

from __future__ import annotations

from datetime import datetime

from app.domain.entities.writing_style import (
    ContactStyleProfile,
    FormalityLevel,
    WritingStyleProfile,
)
from app.prompts.builders import get_standard_draft_prompts, _segments_to_text
from app.prompts.style_guidance import build_style_guidance_from_profile


# P0.1 (2026-05-14): `get_standard_draft_prompts` now returns
# `(list[SystemSegment], str)`. These tests substring-assert on the
# rendered system prompt — wrap every call so the assertions still
# match without changing their semantics.
def _flatten_first(result):
    segments, user_prompt = result
    return _segments_to_text(segments), user_prompt


CONTACT_EMAIL = "alice@example.qc.ca"


def _build_profile_with_full_contact() -> WritingStyleProfile:
    """Construit un profil utilisateur avec UN contact entièrement renseigné.

    Tous les 6 champs visibles dans `ContactStyleEditor.tsx` sont posés à
    des valeurs distinctes pour qu'on puisse les chercher individuellement
    dans le prompt généré.
    """
    profile = WritingStyleProfile.create_empty(account_id=42)
    contact = ContactStyleProfile(
        email=CONTACT_EMAIL,
        formality_override=FormalityLevel.CASUAL,
        preferred_greeting="Salut {first_name},",
        preferred_closing="Bisous,",
        langue="français",
        langue_variante="fr-CA",
        nickname="Ali",
    )
    profile.contact_profiles[CONTACT_EMAIL] = contact.to_dict()
    profile.analyzed_at = datetime.utcnow()
    return profile


def _build_prompts_for_contact(profile: WritingStyleProfile) -> tuple[str, str]:
    """Génère le couple (system_prompt, user_prompt) pour ce contact."""
    style_context = build_style_guidance_from_profile(profile, language="fr", recipient_email=CONTACT_EMAIL)
    return _flatten_first(get_standard_draft_prompts(
        sender=CONTACT_EMAIL,
        subject="Coucou",
        body="On se voit demain ?",
        style_context=style_context,
        account_id=None,
    ))


class TestPerContactFieldsReachThePrompt:
    """Chacun des 6 champs persistés doit apparaître dans le system prompt."""

    def test_nickname_reaches_prompt(self):
        profile = _build_profile_with_full_contact()
        system_prompt, _ = _build_prompts_for_contact(profile)
        assert "Ali" in system_prompt, (
            "Le nickname `Ali` doit apparaître dans le system prompt — "
            "ContactStyleProfile.to_prompt_hint() l'expose comme « SURNOM/PRÉNOM D'APPEL »."
        )
        assert "SURNOM" in system_prompt or "first_name" not in system_prompt.split("Salut ", 1)[-1].split("\n", 1)[0], (
            "Le greeting doit être expansé avec le nickname (pas laissé en template)."
        )

    def test_formality_override_reaches_prompt(self):
        profile = _build_profile_with_full_contact()
        system_prompt, _ = _build_prompts_for_contact(profile)
        # `formality_override.value` = "casual" pour FormalityLevel.CASUAL.
        # On cherche le label exact que `to_prompt_hint` génère :
        # « Formalité spécifique: casual »
        assert "Formalité spécifique" in system_prompt
        assert "casual" in system_prompt

    def test_preferred_greeting_reaches_prompt_expanded(self):
        profile = _build_profile_with_full_contact()
        system_prompt, _ = _build_prompts_for_contact(profile)
        # Le template `Salut {first_name},` doit être expansé avec le nickname
        # via `_expand_greeting_template` (smart_routing.py).
        assert "Salut Ali" in system_prompt, (
            "Le greeting doit être expansé : `Salut {first_name},` + nickname=`Ali` "
            "→ `Salut Ali,`. Si on voit encore `{first_name}` dans le prompt, "
            "l'expansion est cassée."
        )

    def test_preferred_closing_reaches_prompt(self):
        profile = _build_profile_with_full_contact()
        system_prompt, _ = _build_prompts_for_contact(profile)
        assert "Bisous" in system_prompt, (
            "La clôture habituelle `Bisous,` doit apparaître via "
            "« Clôture habituelle: ... »."
        )

    def test_langue_reaches_prompt(self):
        profile = _build_profile_with_full_contact()
        system_prompt, _ = _build_prompts_for_contact(profile)
        # PR3 follow-up : `build_contact_hint_block` (FR locale) emits
        # « LANGUE : Réponds en français à ce contact. »
        assert "LANGUE" in system_prompt
        assert "français" in system_prompt

    def test_langue_variante_reaches_prompt(self):
        profile = _build_profile_with_full_contact()
        system_prompt, _ = _build_prompts_for_contact(profile)
        # PR3 follow-up : `build_contact_hint_block` (FR locale) emits
        # « VARIANTE RÉGIONALE : fr-CA. Adapte vocabulaire, ... »
        assert "VARIANTE RÉGIONALE" in system_prompt
        assert "fr-CA" in system_prompt


class TestPerContactCoexistsWithMirrorRule:
    """Le miroir du ton (P0) et l'override per-contact (legacy) doivent
    coexister sans contradiction. L'override gagne quand il est défini,
    sinon le miroir prend le relais.
    """

    def test_mirror_rule_present_alongside_contact_override(self):
        """Quand un contact a un override formel, le prompt doit toujours
        contenir la règle MIROIR DU TON ET la directive de formalité spécifique.
        Le LLM est instruit de prioriser la règle apprise via le « learned
        rules » header (priorité absolue), pas de la confondre avec une
        contradiction structurelle.
        """
        profile = _build_profile_with_full_contact()
        system_prompt, _ = _build_prompts_for_contact(profile)

        # Mirror rule (issue #454 P0)
        assert "irror" in system_prompt.lower() or "miroir" in system_prompt.lower(), (
            "Le system prompt STANDARD doit garder la règle MIROIR DU TON après P0."
        )

        # Per-contact override (legacy, encore en vie)
        assert "Formalité spécifique" in system_prompt, (
            "L'override per-contact `formality_override` doit toujours être injecté."
        )

    def test_unknown_contact_falls_back_to_mirror_only(self):
        """Pour un contact inconnu (pas dans `contact_profiles`), aucun
        bloc « Adaptation pour <email> » n'est injecté — le prompt repose
        uniquement sur le miroir du ton.
        """
        profile = _build_profile_with_full_contact()
        # Génère pour un contact qui n'est PAS dans le profil
        unknown_email = "stranger@example.com"
        style_context = build_style_guidance_from_profile(profile, language="fr", recipient_email=unknown_email)
        system_prompt, _ = _flatten_first(get_standard_draft_prompts(
            sender=unknown_email,
            subject="Hi",
            body="What's up?",
            style_context=style_context,
            account_id=None,
        ))
        # Pas d'adaptation per-contact pour un inconnu
        assert "Adaptation pour" not in system_prompt
        assert "SURNOM" not in system_prompt
        # Mais le miroir du ton est toujours là pour guider le LLM
        assert "irror" in system_prompt.lower() or "miroir" in system_prompt.lower()


class TestEmptyContactProfileIsNoise:
    """Un ContactStyleProfile vide (champs None) ne doit pas polluer le prompt."""

    def test_empty_contact_profile_produces_minimal_hints(self):
        """Si tous les champs sont None, `to_prompt_hint()` retourne une
        chaîne vide ou quasi-vide — pas de directives parasites."""
        profile = WritingStyleProfile.create_empty(account_id=42)
        contact = ContactStyleProfile(email=CONTACT_EMAIL)  # tous None
        profile.contact_profiles[CONTACT_EMAIL] = contact.to_dict()
        profile.analyzed_at = datetime.utcnow()

        style_context = build_style_guidance_from_profile(profile, language="fr", recipient_email=CONTACT_EMAIL)
        # La sortie peut contenir l'en-tête « Adaptation pour <email>: »
        # mais aucune des 6 directives spécifiques.
        for marker in ("SURNOM", "Formalité spécifique", "Clôture habituelle",
                       "REGIONAL VARIANT", "LANGUAGE"):
            assert marker not in style_context, (
                f"Un profil vide ne doit injecter aucun marker `{marker}` "
                f"— `{marker}` indique un champ peuplé."
            )


class TestPerContactOverridesReachUserPromptDirective:
    """Issue #454 P0 fix : la directive `RULE 3 — YOUR REPLY MUST START WITH
    EXACTLY: ...` du user prompt doit utiliser le nickname per-contact, pas
    le nom dérivé de l'email. Idem pour `REGIONAL VARIANT` qui doit refléter
    le `langue_variante` per-contact, pas le default user-level.

    Ces directives ont une autorité supérieure ("MUST", "EXACTLY") aux hints
    du system prompt, donc si on n'override pas, l'email-derived gagne et on
    contredit la per-contact intelligence stockée dans `ContactStyleProfile`.
    """

    def test_user_prompt_directive_uses_contact_nickname(self, monkeypatch):
        """`Salut Ali,` doit gagner sur `Salut Alice,` (email-derived) dans le
        user prompt directive, quand `ContactStyleProfile.nickname=Ali` existe."""
        # Stub the per-contact lookup pour bypasser le store — on teste que
        # `get_standard_draft_prompts` consomme bien les overrides quand ils
        # existent. Le store réel est testé séparément.
        monkeypatch.setattr(
            "app.prompts.builders._resolve_contact_overrides",
            lambda account_id, sender, detected_language: ("Ali", "Salut Ali,", "fr-CA", "", ""),
        )
        _, user_prompt = get_standard_draft_prompts(
            sender="alice.dupont@example.com",
            subject="Coucou",
            body="On se voit demain ?",
            account_id=42,  # déclenche la résolution per-contact
        )
        assert "Salut Ali," in user_prompt, (
            "Le user prompt doit utiliser le nickname `Ali` du `ContactStyleProfile`. "
            "Sans override, `_extract_display_name` aurait produit `Alice` ou "
            "`Alice Dupont` — contradisant le hint per-contact du system prompt."
        )
        # L'email-derived ne doit PAS apparaître dans la directive
        assert "Salut Alice," not in user_prompt, (
            "Le nom dérivé de l'email `Alice` ne doit pas écraser le nickname `Ali`."
        )
        assert "Salut Alice Dupont," not in user_prompt

    def test_user_prompt_directive_uses_contact_variant(self, monkeypatch):
        """`REGIONAL VARIANT: fr-CA` (per-contact) doit gagner sur le default
        user-level (vide ou différent)."""
        monkeypatch.setattr(
            "app.prompts.builders._resolve_contact_overrides",
            lambda account_id, sender, detected_language: ("Ali", "Salut Ali,", "fr-CA", "", ""),
        )
        _, user_prompt = get_standard_draft_prompts(
            sender="alice@example.com",  # .com → pas de variant TLD
            subject="Coucou",
            body="On se voit demain ?",
            account_id=42,
        )
        assert "REGIONAL VARIANT: fr-CA" in user_prompt, (
            "Le user prompt doit utiliser le `langue_variante=fr-CA` du contact, "
            "même si le user-level n'a pas de variant."
        )

    def test_user_prompt_drops_no_shorten_disclaimer_when_override(self, monkeypatch):
        """Quand on utilise un nickname per-contact, la directive « do NOT
        shorten or use nicknames » devient absurde — elle doit disparaître."""
        monkeypatch.setattr(
            "app.prompts.builders._resolve_contact_overrides",
            lambda account_id, sender, detected_language: ("Ali", "Salut Ali,", "", "", ""),
        )
        _, user_prompt = get_standard_draft_prompts(
            sender="alice@example.com",
            subject="Hi",
            body="See you tomorrow?",
            account_id=42,
        )
        assert "do NOT shorten or use nicknames" not in user_prompt, (
            "Avec un nickname override actif, la directive « do NOT shorten or "
            "use nicknames » se contredit elle-même (le nickname EST une forme "
            "raccourcie). Elle doit disparaître."
        )
        # Mais la nouvelle disclaimer pédagogique doit apparaître
        assert "habitual greeting for this contact" in user_prompt

    def test_no_override_keeps_legacy_disclaimer(self):
        """Sans override per-contact (account_id=None), la directive originale
        doit être préservée — pas de régression pour les drafts hors profil."""
        _, user_prompt = get_standard_draft_prompts(
            sender="stranger@example.com",
            subject="Hi",
            body="Quick question",
            account_id=None,
        )
        # Pas d'override → directive legacy avec le warning
        assert "do NOT shorten or use nicknames" in user_prompt or "NO greeting" in user_prompt


class TestResolveContactOverridesHelper:
    """Test direct du helper `_resolve_contact_overrides` contre un store
    réel (in-memory). Verrou contre les régressions de la résolution elle-même.
    """

    def test_helper_returns_nickname_greeting_variant_from_profile(self, monkeypatch):
        """Le helper doit lire les 3 fields depuis WritingStyleProfile et
        retourner le greeting expansé."""
        from app.prompts.builders import _resolve_contact_overrides

        profile = _build_profile_with_full_contact()

        # Stub the store via the container — ce qui simule un profil persisté
        class _StubStore:
            def load(self, account_id):
                return profile if account_id == 42 else None

        class _StubContainer:
            def get_writing_style_store(self):
                return _StubStore()

        monkeypatch.setattr(
            "app.infrastructure.container.get_container",
            lambda: _StubContainer(),
        )

        nickname, greeting, variant, formality_override, closing = _resolve_contact_overrides(
            account_id=42,
            sender=CONTACT_EMAIL,
            detected_language="FRENCH",
        )
        assert nickname == "Ali"
        assert greeting == "Salut Ali,"
        assert variant == "fr-CA"
        # The fixture profile pins formality_override="casual"; verify the
        # helper surfaces it so the caller can override the auto-detected
        # score before computing the greeting.
        assert formality_override == "casual"
        # The fixture pins preferred_closing="Bisous,"; the helper now surfaces
        # it so the reply path can enforce it as a hard sign-off (fix #3).
        assert closing == "Bisous,"

    def test_helper_returns_empty_for_unknown_contact(self, monkeypatch):
        """Contact pas dans le profil → tuple vide, pas d'erreur."""
        from app.prompts.builders import _resolve_contact_overrides

        profile = _build_profile_with_full_contact()

        class _StubStore:
            def load(self, account_id):
                return profile

        class _StubContainer:
            def get_writing_style_store(self):
                return _StubStore()

        monkeypatch.setattr(
            "app.infrastructure.container.get_container",
            lambda: _StubContainer(),
        )

        nickname, greeting, variant, formality_override, closing = _resolve_contact_overrides(
            account_id=42,
            sender="stranger@example.com",
            detected_language="FRENCH",
        )
        assert nickname == ""
        assert greeting == ""
        assert variant == ""
        assert formality_override == ""
        assert closing == ""

    def test_helper_fail_open_on_store_exception(self, monkeypatch):
        """Si le store lève une exception, le helper doit return ("","","") sans
        propager — la résolution per-contact ne doit JAMAIS bloquer le draft."""
        from app.prompts.builders import _resolve_contact_overrides

        class _BrokenStore:
            def load(self, account_id):
                raise RuntimeError("simulated DB outage")

        class _StubContainer:
            def get_writing_style_store(self):
                return _BrokenStore()

        monkeypatch.setattr(
            "app.infrastructure.container.get_container",
            lambda: _StubContainer(),
        )

        result = _resolve_contact_overrides(
            account_id=42,
            sender=CONTACT_EMAIL,
            detected_language="FRENCH",
        )
        assert result == ("", "", "", "", "")  # silent fallback

    def test_helper_skips_no_account_id(self):
        """Sans account_id, pas de lookup — fast-path retourne immédiatement."""
        from app.prompts.builders import _resolve_contact_overrides
        result = _resolve_contact_overrides(
            account_id=None,
            sender=CONTACT_EMAIL,
            detected_language="FRENCH",
        )
        assert result == ("", "", "", "", "")
