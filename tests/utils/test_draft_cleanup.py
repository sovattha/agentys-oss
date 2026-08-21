# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for app.utils.draft_cleanup.strip_reasoning_leakage.

This module pins the contract used by both the refine path
(`app/application/refine_email.py`) and the main SmartRouter pipeline
(`app/smart_routing.py`) — six call sites all share these regexes, so a
behavioural regression here would silently degrade every emitted draft.
"""

from __future__ import annotations

from app.utils.draft_cleanup import strip_ai_dashes, strip_reasoning_leakage


def test_empty_input_passthrough():
    """Empty / whitespace-only inputs collapse to "" (no body to preserve)."""
    assert strip_reasoning_leakage("") == ""
    assert strip_reasoning_leakage("   \n  ") == ""


def test_clean_text_unchanged():
    """Real reply text without any reasoning markers must pass through verbatim."""
    text = (
        "Bonjour Alice,\n\n"
        "Merci pour ton message. Je te confirme la réunion de mardi à 10h.\n\n"
        "À bientôt,"
    )
    assert strip_reasoning_leakage(text) == text


def test_strips_je_dois_chain_of_thought():
    text = (
        "Je dois prioriser le besoin client:\n"
        "- Vérifier le contexte instruction\n"
        "- Adapter la critique du registre\n"
        "\n"
        "Bonjour Alice,\n"
        "Voici ma réponse."
    )
    cleaned = strip_reasoning_leakage(text)
    assert "Je dois prioriser" not in cleaned
    assert "Vérifier le contexte instruction" not in cleaned
    assert "Adapter la critique" not in cleaned
    assert "Bonjour Alice," in cleaned
    assert "Voici ma réponse." in cleaned


def test_strips_resolution_section_header():
    text = (
        "**Résolution :** je vais répondre brièvement.\n"
        "\n"
        "Hello,\n"
        "Thanks for the heads up."
    )
    cleaned = strip_reasoning_leakage(text)
    assert "Résolution" not in cleaned
    assert "Hello," in cleaned


def test_strips_meta_prose_about_directives():
    text = (
        "Ces deux directives sont contradictoires.\n"
        "Selon les règles fournies, je dois favoriser la concision.\n"
        "\n"
        "Bonjour,\n"
        "C'est noté, je vous reviens demain."
    )
    cleaned = strip_reasoning_leakage(text)
    assert "Ces deux directives" not in cleaned
    assert "Selon les règles" not in cleaned
    assert "Bonjour," in cleaned
    assert "C'est noté" in cleaned


def test_safety_net_returns_original_when_strip_empties_text():
    """If every line looks like reasoning, return original — never an empty draft."""
    text = "Je dois faire X:\nL'instruction originale est claire."
    cleaned = strip_reasoning_leakage(text)
    # Both lines match patterns → would empty the result. Safety net kicks in.
    assert cleaned == text.strip()


def test_does_not_strip_legit_je_dois_without_colon():
    """The Je-dois pattern requires a trailing colon (the model announcing itself).

    A natural French sentence "Je dois te dire que..." has no colon and must
    survive unchanged.
    """
    text = "Je dois te dire que c'est super.\nÀ demain."
    cleaned = strip_reasoning_leakage(text)
    assert "Je dois te dire que c'est super." in cleaned
    assert "À demain." in cleaned


def test_does_not_strip_je_dois_sentence_with_colon_mid_line():
    """Audit 2026-06-02 I: a legitimate sentence whose colon is followed by
    content on the SAME line must survive — only a true header (colon ENDING the
    line) is a reasoning leak. Compose-from-scratch is exactly where such openings
    appear, and the old pattern silently deleted them."""
    # "Let me summarize: <content>" — content after the colon on the same line.
    en = "Let me summarize: we agreed on the budget.\n\nThanks."
    assert strip_reasoning_leakage(en) == en.strip()
    # French spaced-colon style "ceci : <content>".
    fr = "Je dois vous transmettre ceci : le rapport est prêt.\n\nCordialement,"
    assert strip_reasoning_leakage(fr) == fr.strip()
    # A greeting then a colon-bearing body line — the whole body must survive
    # (MULTILINE used to match the body line even behind a greeting).
    full = (
        "Bonjour Marie,\n\n"
        "Je dois vous confirmer une chose importante : la réunion est avancée à 14h.\n\n"
        "Cordialement,"
    )
    assert strip_reasoning_leakage(full) == full.strip()


def test_still_strips_je_dois_header_ending_with_colon():
    """The true reasoning-header form (colon ENDS the line, reply on the next)
    is still stripped — the I tightening must not weaken real leak detection."""
    text = "Je dois adopter un ton formel :\nBonjour,\nVoici ma réponse."
    cleaned = strip_reasoning_leakage(text)
    assert "Je dois adopter" not in cleaned
    assert "Bonjour," in cleaned
    assert "Voici ma réponse." in cleaned


def test_in_block_skips_reasoning_bullets_only():
    """While inside a reasoning block, plain content lines end the block.

    A bullet that does NOT contain reasoning vocabulary terminates the block.
    """
    text = (
        "Je dois structurer ma réponse:\n"
        "- 1 cup of flour\n"
        "- 2 eggs\n"
        "\n"
        "Voici la recette."
    )
    cleaned = strip_reasoning_leakage(text)
    # First "- 1 cup of flour" doesn't contain reasoning vocab → ends the block,
    # so it (and following lines) should survive.
    assert "1 cup of flour" in cleaned
    assert "2 eggs" in cleaned
    assert "Voici la recette." in cleaned
    assert "Je dois structurer" not in cleaned


# ===========================================================================
# strip_ai_dashes — em/en dash + spaced-hyphen connectors → human punctuation
# ===========================================================================


def test_ai_dashes_empty_passthrough():
    assert strip_ai_dashes("") == ""
    assert strip_ai_dashes(None) is None  # type: ignore[arg-type]


def test_ai_dashes_em_dash_connector_becomes_comma():
    """The exact pattern the user flagged in the compose window."""
    text = (
        "Je t'envoie le lien sur Telegram — je pense que ça vaut la peine "
        "qu'on regarde ça ensemble."
    )
    cleaned = strip_ai_dashes(text)
    assert "—" not in cleaned
    assert "Telegram, je pense que" in cleaned


def test_ai_dashes_en_dash_connector_becomes_comma():
    cleaned = strip_ai_dashes("Le projet avance bien – on devrait livrer mardi.")
    assert "–" not in cleaned
    assert "avance bien, on devrait" in cleaned


def test_ai_dashes_glued_em_dash_becomes_comma():
    """No spaces around the dash (word—word) still normalises."""
    cleaned = strip_ai_dashes("rapide—efficace")
    assert cleaned == "rapide, efficace"


def test_ai_dashes_double_hyphen_connector():
    cleaned = strip_ai_dashes("C'est prêt -- je t'envoie ça.")
    assert "C'est prêt, je t'envoie ça." == cleaned


def test_ai_dashes_spaced_ascii_hyphen_connector():
    cleaned = strip_ai_dashes("qualité - rapidité - coût")
    assert cleaned == "qualité, rapidité, coût"


def test_ai_dashes_after_sentence_punctuation_is_dropped():
    """A dash right after sentence punctuation is decoration → drop it."""
    cleaned = strip_ai_dashes("J'ai fini l'audit. — Voici le résultat.")
    assert "—" not in cleaned
    assert cleaned == "J'ai fini l'audit. Voici le résultat."


def test_ai_dashes_preserves_compound_words():
    """Hyphens INSIDE words must never be touched."""
    text = (
        "Salut Jean-Pierre,\n\n"
        "Le rendez-vous de ce week-end est confirmé. Co-fondateur "
        "d'Agentys, je gère le suivi par e-mail.\n\n"
        "À bientôt,"
    )
    # No connector dashes here at all → must be byte-identical.
    assert strip_ai_dashes(text) == text


def test_ai_dashes_preserves_numeric_ranges():
    assert strip_ai_dashes("Disponible 9h-17h.") == "Disponible 9h-17h."
    assert strip_ai_dashes("Exercice 2024–2025") == "Exercice 2024-2025"
    assert strip_ai_dashes("entre 10 - 15 personnes") == "entre 10 - 15 personnes"


def test_ai_dashes_preserves_leading_bullet_dash():
    """A line that STARTS with a dash is a bullet, not a connector."""
    text = "Points clés :\n- qualité\n- rapidité\n— coût"
    cleaned = strip_ai_dashes(text)
    # Leading "- " and "— " markers stay; nothing mid-clause to rewrite.
    assert cleaned == text


def test_ai_dashes_is_idempotent():
    text = "Telegram — je pense, et 9h-17h -- voilà."
    once = strip_ai_dashes(text)
    assert strip_ai_dashes(once) == once
    assert "—" not in once and "--" not in once
