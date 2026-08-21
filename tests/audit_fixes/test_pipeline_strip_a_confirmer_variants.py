"""
Audit fix — failure-mode #7 (2026-04-24)
=========================================

`_strip_a_confirmer` regex previously missed a family of LLM-emitted
placeholder markers, leaving raw "[à vérifier]" / "[to verify]" / "[TODO]"
text in user-facing drafts.

These tests pin the post-fix behavior: the expanded alternation removes
all known variants without touching legitimate content.

Source: tasks/audit-reports/2026-04-24_stability/03-draft-pipeline.md
        — failure-mode row #7 (MEDIUM).
"""

import pytest

from app.smart_routing import _strip_a_confirmer


# --- Variants the OLD regex did NOT cover (these would leak pre-fix) ---

@pytest.mark.parametrize(
    "draft_in, must_not_contain",
    [
        # French verify variants
        ("Le rendez-vous est prévu pour [à vérifier - date].", "[à vérifier"),
        ("Le rendez-vous est prévu [À VÉRIFIER].", "À VÉRIFIER"),
        ("Le rendez-vous est prévu [À VERIFIER].", "VERIFIER"),
        ("Le montant: 100€ [à verifier].", "[à verifier"),
        # French complete variants
        ("Bonjour, [à compléter avec son prénom],", "[à compléter"),
        ("Le détail [À COMPLETER - liste produits].", "[À COMPLETER"),
        # English variants
        ("The amount is [TO VERIFY: 100$].", "[TO VERIFY"),
        ("The deadline is [to verify].", "[to verify"),
        ("The price is [to confirm].", "[to confirm"),
        ("Status: [to complete with shipping date].", "[to complete"),
        ("Hi [PLACEHOLDER],", "[PLACEHOLDER"),
        ("Best regards, [placeholder: name]", "[placeholder"),
        ("Total: [TODO]", "[TODO"),
        ("Total: [todo: insert final price]", "[todo"),
        ("Date: [TO BE FILLED]", "[TO BE FILLED"),
        ("Date: [TO BE ADDED]", "[TO BE ADDED"),
        ("Date: [TO BE PROVIDED]", "[TO BE PROVIDED"),
        ("Date: [TO BE DETERMINED]", "[TO BE DETERMINED"),
        # French bracket variants
        ("Adresse: [à remplir]", "[à remplir"),
        ("Adresse: [à préciser - rue + ville]", "[à préciser"),
        ("Choix: [à définir]", "[à définir"),
        # Bare-phrase variants
        ("Le rendez-vous est à vérifier.", "à vérifier"),
        ("Le rendez-vous est à compléter.", "à compléter"),
        ("Le détail est à préciser.", "à préciser"),
        ("Le formulaire est à remplir.", "à remplir"),
        ("Status to be confirmed.", "to be confirmed"),
        ("Status to be verified.", "to be verified"),
        ("Status to be filled.", "to be filled"),
        # Other tags
        ("Done [FIXME: handle edge case].", "[FIXME"),
        ("Reference: [XXX]", "[XXX"),
        ("Status [TBA].", "[TBA"),
        ("Content: [REDACTED]", "[REDACTED"),
    ],
)
def test_post_fix_removes_placeholder_variants(draft_in, must_not_contain):
    out = _strip_a_confirmer(draft_in)
    assert must_not_contain not in out, (
        f"Expected '{must_not_contain}' to be stripped from draft, got: {out!r}"
    )


# --- Variants the OLD regex DID cover (regression check) ---

@pytest.mark.parametrize(
    "draft_in, must_not_contain",
    [
        ("Date: [À confirmer]", "[À confirmer"),
        ("Date: [à confirmer - jour suivant]", "[à confirmer"),
        ("Total: [À valider]", "[À valider"),
        ("Status: [TBD]", "[TBD"),
        ("Content: [REDACTE]", "[REDACTE"),
        ("Le rendez-vous est à confirmer.", "à confirmer"),
        ("Le rendez-vous est à valider.", "à valider"),
        # Multi-line — only the placeholder line should be stripped
        (
            "Bonjour Marc,\n\n"
            "Le montant: [à vérifier - 100€]\n\n"
            "Cordialement,",
            "[à vérifier",
        ),
    ],
)
def test_post_fix_still_removes_legacy_variants(draft_in, must_not_contain):
    """Regression check: variants the OLD regex caught must still be stripped."""
    out = _strip_a_confirmer(draft_in)
    assert must_not_contain not in out


# --- Negatives: legitimate content must NOT be touched ---

@pytest.mark.parametrize(
    "draft_in",
    [
        # Conjugated forms — must not match
        "Je vais vérifier ces détails ce soir.",
        "Pourriez-vous compléter le formulaire?",
        "We need to confirm the deadline tomorrow.",
        # Brackets without placeholder keywords
        "Reference: [Q4-2025]",
        "Email: [contact@example.com]",
        # Legitimate "verify" not in placeholder context
        "Please review and verify the attachment.",
    ],
)
def test_legitimate_content_preserved(draft_in):
    out = _strip_a_confirmer(draft_in)
    # Legitimate content must round-trip with no change
    assert out == draft_in


def test_empty_input_returns_empty():
    assert _strip_a_confirmer("") == ""
    assert _strip_a_confirmer(None) is None  # type: ignore[arg-type]


def test_no_brackets_fast_path():
    """Optimization: drafts without `[` are returned unchanged immediately."""
    draft = "Bonjour Marc,\n\nMerci pour votre email.\n\nCordialement"
    assert _strip_a_confirmer(draft) == draft
