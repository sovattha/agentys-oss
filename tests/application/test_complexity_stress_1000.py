# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Stress test: 1000 emails pour valider le système de complexité.

Teste analyze_complexity() → calculate_complexity_score() → tier routing
sur 1000 cas diversifiés couvrant tous les signaux, boundaries et edge cases.

Catégories:
- SIMPLE ultra-short (80) + one-signal (70) = 150
- STANDARD medium (200) + tech (100) + forced (20) = 320
- COMPLEX multi-q (100) + technical (80) + long (70) = 250
- Boundaries: body_length (40) + questions (30) + tech (30) = 100
- Variations: thread_depth (30) + topics (30) + lists (20) + attachments (20) = 100
- Mixed language (30) + edge cases (50) = 80
Total: 1000 cases
"""

import os
import importlib.util

import pytest

from app.smart_routing import analyze_complexity, calculate_complexity_score


# =========================================================================
# Load test case generators from data files
# =========================================================================

def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_fixtures = _load_module(os.path.join(_ROOT, "tests", "fixtures", "complexity_test_cases.py"), "fixtures")
_standard = _load_module(os.path.join(_ROOT, "tests", "test_data_standard_tier.py"), "standard")


# =========================================================================
# SIMPLE tier generators (inline — from agent output)
# =========================================================================

def _gen_simple_ultra_short():
    """80 cases: body < 200 chars, 0 questions, 0 tech keywords, score 0-10."""
    cases = []

    empties = [
        ("", "Re: Réunion", 0, False, False, "SIMPLE", 0, 0, "Empty body FR"),
        ("", "Re: Meeting notes", 0, False, False, "SIMPLE", 0, 0, "Empty body EN"),
        ("", "Fwd: Document", 0, False, False, "SIMPLE", 0, 0, "Empty body fwd"),
        ("", "Re: Projet", 0, False, False, "SIMPLE", 0, 0, "Empty body projet"),
        ("", "", 0, False, False, "SIMPLE", 0, 0, "Empty body empty subject"),
    ]
    cases.extend(empties)

    fr_acks = [
        "Merci.", "OK.", "Bien reçu.", "Super !", "D'accord.",
        "Entendu.", "Parfait.", "Reçu.", "Noté.", "C'est bon.",
        "Merci beaucoup.", "Très bien.", "Compris.", "Ça marche.",
        "Impeccable.", "Bonne idée.", "Génial.", "Nickel.",
        "Formidable.", "Excellent.", "Tout à fait.", "Absolument.",
        "Avec plaisir.", "Pas de souci.", "Aucun problème.",
        "Merci à toi.", "Merci à vous.", "Bonne journée.",
        "Bon week-end.", "À lundi.", "À demain.", "Cordialement.",
        "Bien à vous.", "Bonne soirée.", "Salut !", "Coucou !",
    ]
    en_acks = [
        "Thanks.", "Got it.", "Perfect.", "Noted, thanks!", "Will do.",
        "Sounds good.", "Great.", "Awesome.", "Sure thing.", "Absolutely.",
        "Understood.", "Acknowledged.", "Thank you!", "Much appreciated.",
        "Works for me.", "No worries.", "All good.", "Cheers.",
        "Roger that.", "On it.", "Good to know.", "Fair enough.",
        "Makes sense.", "Agreed.", "Right.", "Cool.", "Fine by me.",
        "See you then.", "See you Monday.", "Talk soon.",
    ]

    subjects_fr = ["Re: Réunion", "Re: Planning", "Re: Projet Alpha", "Re: Congés",
                    "Re: Dossier client", "Re: Facture", "Re: Livraison", "Re: Devis",
                    "Re: Visite", "Re: Formation", "Re: Compte rendu", "Re: Invitation"]
    subjects_en = ["Re: Meeting", "Re: Schedule", "Re: Project update", "Re: Invoice",
                    "Re: Delivery", "Re: Contract", "Re: Training", "Re: Follow-up",
                    "Re: Quick note", "Re: Sync", "Re: Update", "Re: Confirmation"]

    for i, body in enumerate(fr_acks):
        cases.append((body, subjects_fr[i % len(subjects_fr)], 0, False, False, "SIMPLE", 0, 5, f"FR ack #{i}: {body[:25]}"))
    for i, body in enumerate(en_acks):
        cases.append((body, subjects_en[i % len(subjects_en)], 0, False, False, "SIMPLE", 0, 5, f"EN ack #{i}: {body[:25]}"))

    longer = [
        "Je prends note, merci pour le retour.",
        "Bonne réception, je reviens vers vous rapidement.",
        "Je transmets à mon collègue.",
        "C'est noté, on en reparle lundi.",
        "Je suis disponible toute la semaine.",
        "Le créneau de 14h me convient.",
        "Je vous envoie le fichier demain matin.",
        "Tout est en ordre de mon côté.",
        "Je confirme ma présence.",
    ]
    for i, body in enumerate(longer):
        cases.append((body, subjects_fr[i % len(subjects_fr)], 0, False, False, "SIMPLE", 0, 10, f"FR longer #{i}: {body[:35]}"))

    return cases


def _gen_simple_one_signal():
    """70 cases: 1 question OR 1 tech keyword, body < 200 chars, score < 30."""
    cases = []

    questions_fr = [
        "Tu es dispo demain ?", "On se voit lundi ?", "Ça te va ?",
        "C'est bon pour toi ?", "Tu as reçu le fichier ?", "Tu confirmes ?",
        "On maintient le créneau ?", "Tu peux me rappeler ?", "C'est validé ?",
        "Tu as vu mon message ?", "Ça t'arrange ?", "On décale à jeudi ?",
        "Tu viens à la réunion ?", "Le budget est approuvé ?",
        "Tu as le numéro de Marie ?", "C'est pour quand la livraison ?",
        "On fait ça en visio ?", "Tu préfères mardi ou mercredi ?",
        "Le client a répondu ?", "Tu peux jeter un œil ?",
    ]
    questions_en = [
        "Are you free tomorrow?", "Does that work for you?",
        "Did you get my email?", "Can you confirm?",
        "Shall we keep the slot?", "Can you call me back?",
        "Is it approved?", "Did you see the update?",
        "Does Monday work?", "Can we reschedule?",
        "Have you heard back?", "Is this the final version?",
        "Do you need anything else?", "Can you take a look?",
        "Is the report ready?", "Did the client respond?",
        "Are we still on for Friday?", "Should I go ahead?",
        "Do you have her number?", "Want me to forward it?",
    ]

    for i, body in enumerate(questions_fr):
        cases.append((body, "Re: Question", 0, False, False, "SIMPLE", 5, 15, f"FR 1q #{i}: {body[:30]}"))
    for i, body in enumerate(questions_en):
        cases.append((body, "Re: Question", 0, False, False, "SIMPLE", 5, 15, f"EN 1q #{i}: {body[:30]}"))

    tech_fr = [
        "J'ai mis à jour l'API, c'est en ligne.", "Le bug est corrigé, merci.",
        "Le deploy est terminé.", "J'ai lancé le sprint ce matin.",
        "Le SLA est respecté ce mois-ci.", "La conformité GDPR avance bien.",
        "Le docker est à jour.", "Le SQL a été optimisé.",
        "Le rollback a bien fonctionné.", "Le JSON est valide.",
        "Le merge est terminé.", "Le branch est prête.",
        "La migration est terminée.", "Le endpoint est actif.",
        "Le schema est à jour.",
    ]
    tech_en = [
        "The API is updated and live.", "Bug is fixed, thanks.",
        "Deploy completed successfully.", "Sprint kicked off this morning.",
        "SLA compliance is on track.", "GDPR audit went well.",
        "Docker image rebuilt.", "SQL query optimized.",
        "The rollback went smoothly.", "JSON payload looks good.",
        "Merge completed on main.", "Branch is ready for review.",
        "Migration finished cleanly.", "The endpoint is live now.",
        "Schema update is done.",
    ]

    for i, body in enumerate(tech_fr):
        cases.append((body, "Re: Tech", 0, False, False, "SIMPLE", 4, 15, f"FR 1tech #{i}: {body[:30]}"))
    for i, body in enumerate(tech_en):
        cases.append((body, "Re: Tech", 0, False, False, "SIMPLE", 4, 15, f"EN 1tech #{i}: {body[:30]}"))

    return cases


# =========================================================================
# Assemble all 1000 cases
# =========================================================================

def _build_all_cases():
    """Build the complete list of ~1000 test cases."""
    all_cases = []

    # SIMPLE (150)
    all_cases.extend(_gen_simple_ultra_short())
    all_cases.extend(_gen_simple_one_signal())

    # STANDARD (320)
    all_cases.extend(_standard._gen_standard_medium())
    all_cases.extend(_standard._gen_standard_with_tech())
    all_cases.extend(_standard._gen_standard_forced())

    # COMPLEX (250)
    all_cases.extend(_fixtures._gen_complex_multi_questions())
    all_cases.extend(_fixtures._gen_complex_technical())
    all_cases.extend(_fixtures._gen_complex_long())

    # Boundaries (100)
    all_cases.extend(_fixtures._gen_boundary_body_length())
    all_cases.extend(_fixtures._gen_boundary_questions())
    all_cases.extend(_fixtures._gen_boundary_tech())

    # Variations (100)
    all_cases.extend(_fixtures._gen_thread_depth_variations())
    all_cases.extend(_fixtures._gen_topic_variations())
    all_cases.extend(_fixtures._gen_list_detection())
    all_cases.extend(_fixtures._gen_attachments())

    # Mixed + Edge (80)
    all_cases.extend(_fixtures._gen_mixed_language())
    all_cases.extend(_fixtures._gen_edge_cases())

    return all_cases


ALL_CASES = _build_all_cases()


# =========================================================================
# Parametrized test: 1 test per case
# =========================================================================

@pytest.mark.parametrize(
    "case",
    ALL_CASES,
    ids=[c[-1] for c in ALL_CASES],
)
def test_complexity_routing(case):
    """Validate score range and tier assignment for each email case."""
    body, subject, depth, has_instr, has_attach, expected_tier, smin, smax, desc = case

    signals = analyze_complexity(
        body=body,
        subject=subject,
        thread_depth=depth,
        has_instructions=has_instr,
        has_attachments=has_attach,
    )
    score = calculate_complexity_score(signals)

    # Assert score is in expected range
    assert smin <= score <= smax, (
        f"[{desc}] score={score} not in [{smin},{smax}] "
        f"(body={signals.body_length}c, q={signals.question_count}, "
        f"tech={signals.technical_content}, topics={signals.topic_count})"
    )

    # Derive expected tier from score + instructions
    if score < 30 and not has_instr:
        actual_tier = "SIMPLE"
    elif score >= 50:
        actual_tier = "COMPLEX"
    else:
        actual_tier = "STANDARD"

    assert actual_tier == expected_tier, (
        f"[{desc}] tier={actual_tier} expected={expected_tier} "
        f"(score={score}, instr={has_instr})"
    )


# =========================================================================
# Distribution summary test
# =========================================================================

def test_distribution_summary(capsys):
    """Run all cases and print score distribution summary."""
    tiers = {"SIMPLE": [], "STANDARD": [], "COMPLEX": []}

    for case in ALL_CASES:
        body, subject, depth, has_instr, has_attach, expected_tier, smin, smax, desc = case
        signals = analyze_complexity(body, subject, depth, has_instr, has_attach)
        score = calculate_complexity_score(signals)

        if score < 30 and not has_instr:
            tier = "SIMPLE"
        elif score >= 50:
            tier = "COMPLEX"
        else:
            tier = "STANDARD"

        tiers[tier].append(score)

    total = len(ALL_CASES)
    print(f"\n{'=' * 55}")
    print(f"  Complexity Stress Test — {total} emails")
    print(f"{'=' * 55}")
    for tier_name in ("SIMPLE", "STANDARD", "COMPLEX"):
        scores = tiers[tier_name]
        count = len(scores)
        pct = count / total * 100 if total else 0
        avg = sum(scores) / count if count else 0
        lo = min(scores) if scores else 0
        hi = max(scores) if scores else 0
        print(f"  {tier_name:10s}: {count:4d} cases ({pct:5.1f}%)  "
              f"avg={avg:5.1f}  range=[{lo}, {hi}]")
    all_scores = [s for v in tiers.values() for s in v]
    print(f"  {'TOTAL':10s}: {total:4d} cases          "
          f"min={min(all_scores)}  max={max(all_scores)}")
    print(f"{'=' * 55}")

    # Sanity: we should have ~1000 cases (999 since German edge case was
    # dropped when DE was retired as a UI language — commit 7e388c3e).
    assert total >= 999, f"Expected >= 999 cases, got {total}"
