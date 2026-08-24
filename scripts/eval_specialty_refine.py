#!/usr/bin/env python3
# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Eval harness — refine-text expert mode (Ctrl+Shift+G) vs standard mode (Ctrl+G).

Pour 5 cas variés (immobilier QC + droit), appelle /api/refine-text en mode
standard et en mode expert, capture les sorties, calcule des métriques
objectives, puis envoie à un LLM-as-judge pour scorer 4 axes :

  1. Précision juridique (les articles cités existent et s'appliquent au cas)
  2. Ancrage au cas (la réponse parle de la situation, pas du concept)
  3. Ton humain (pas de phrases-robot, prose fluide, conversationnel)
  4. Actionnabilité (séquence d'étapes concrètes, pas un générique)

Sortie : tableau récapitulatif + verdict ROI.

Usage : python scripts/eval_specialty_refine.py [--no-judge] [--verbose]
"""

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import urllib.request
import urllib.error

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Force UTF-8 stdout on Windows so the f"...→..." prints don't crash
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

# Load .env so we can use the Anthropic SDK directly for the judge
def _load_env():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_env()

API_URL = "http://localhost:5050/api/refine-text"

# ── Cas de test ──────────────────────────────────────────────────────────────


CASES = [
    # ── IMMOBILIER QC (13 cas) ──────────────────────────────────────────────
    {
        "id": "immo_vice_cache_fondation",
        "specialty": "real-estate-qc",
        "subject": "achat maison vis cache",
        "instruction": "Reponds-lui de facon professionnelle",
        "notes": (
            "J'ai achete une maison il y a 6 mois et j'ai trouve un probleme "
            "majeur dans la fondation. Est-ce que je peux faire une "
            "reclamation pour ma maison?"
        ),
    },
    {
        "id": "immo_commission_negociation",
        "specialty": "real-estate-qc",
        "subject": "commission de courtage",
        "instruction": "Reponds-lui",
        "notes": (
            "Bonjour, mon courtier veut prendre 5% de commission pour vendre "
            "ma maison. Je trouve ca tres eleve. Est-ce que c'est negociable "
            "et qu'est-ce qui est standard?"
        ),
    },
    {
        "id": "immo_premier_acheteur_rap_celiapp",
        "specialty": "real-estate-qc",
        "subject": "premier achat - financement",
        "instruction": "Reponds-lui en expliquant les options",
        "notes": (
            "On veut acheter notre premier condo a Montreal vers 350k. "
            "On a 30k dans nos REER chacun. Est-ce qu'on peut combiner "
            "le RAP et le CELIAPP pour la mise de fonds?"
        ),
    },
    {
        "id": "immo_inspection_pyrite",
        "specialty": "real-estate-qc",
        "subject": "pyrite trouvee inspection",
        "instruction": "Reponds-lui",
        "notes": (
            "L'inspection pre-achat a revele de la pyrite dans la dalle de "
            "beton du sous-sol. On doit fermer dans 2 semaines. Est-ce qu'on "
            "peut se retirer ou negocier une baisse de prix?"
        ),
    },
    {
        "id": "immo_promesse_achat_retrait",
        "specialty": "real-estate-qc",
        "subject": "annulation promesse achat",
        "instruction": "Reponds-lui",
        "notes": (
            "J'ai signe une promesse d'achat sur un duplex la semaine "
            "passee mais je veux me retirer car j'ai trouve mieux. Est-ce "
            "que je perds mon depot de 5000$?"
        ),
    },
    {
        "id": "immo_condo_cotisation_speciale",
        "specialty": "real-estate-qc",
        "subject": "cotisation speciale condo",
        "instruction": "Reponds-lui",
        "notes": (
            "Le syndicat de mon condo vient de voter une cotisation speciale "
            "de 15000$ par unite pour refaire la toiture. Est-ce que je peux "
            "contester? Le fonds de prevoyance etait suppose couvrir ca."
        ),
    },
    {
        "id": "immo_taxe_bienvenue_montreal",
        "specialty": "real-estate-qc",
        "subject": "calcul taxe de bienvenue",
        "instruction": "Reponds-lui",
        "notes": (
            "On achete une maison a 625000$ a Montreal. Combien on doit "
            "prevoir pour la taxe de bienvenue (droits de mutation)? "
            "Et est-ce qu'il y a des exonerations comme premier acheteur?"
        ),
    },
    {
        "id": "immo_acm_strategie_prix",
        "specialty": "real-estate-qc",
        "subject": "strategie de prix",
        "instruction": "Reponds-lui",
        "notes": (
            "Tu m'as fait une ACM a 540k mais le marche a ralenti. "
            "Penses-tu qu'on devrait afficher a 525k pour creer de l'interet "
            "ou rester a 549k pour avoir de la marge de negociation?"
        ),
    },
    {
        "id": "immo_plex_premier_investissement",
        "specialty": "real-estate-qc",
        "subject": "achat premier plex",
        "instruction": "Reponds-lui",
        "notes": (
            "J'ai 80k de mise de fonds et je veux acheter un 4-plex a "
            "Quebec ou Trois-Rivieres. C'est mon premier investissement "
            "locatif. Quels sont les ratios cles a verifier (taux de cap, "
            "MRB, etc.) et les pieges classiques?"
        ),
    },
    {
        "id": "immo_courtier_mandat_retrait",
        "specialty": "real-estate-qc",
        "subject": "annulation contrat courtage",
        "instruction": "Reponds-lui",
        "notes": (
            "J'ai signe un contrat de courtage exclusif il y a 2 mois "
            "(formulaire BCS) avec mon courtier mais je suis pas content "
            "de son travail. Est-ce que je peux resilier avant la fin du "
            "mandat sans avoir a payer la commission?"
        ),
    },
    {
        "id": "immo_construction_neuve_garantie",
        "specialty": "real-estate-qc",
        "subject": "garantie maison neuve GCR",
        "instruction": "Reponds-lui",
        "notes": (
            "On a achete une maison neuve d'un constructeur en 2024. "
            "1 an plus tard on decouvre des fissures dans le revetement "
            "exterieur et des problemes d'infiltration. Est-ce que la "
            "garantie GCR couvre ca? Comment on procede pour reclamer?"
        ),
    },
    {
        "id": "immo_zonage_terrain_agricole",
        "specialty": "real-estate-qc",
        "subject": "terrain potentiellement agricole",
        "instruction": "Reponds-lui",
        "notes": (
            "Je veux acheter un terrain de 4 hectares a St-Jean-sur-"
            "Richelieu pour construire ma maison. L'agent dit que c'est OK "
            "mais j'ai vu CPTAQ sur les documents. Comment je verifie si "
            "je peux vraiment construire?"
        ),
    },
    {
        "id": "immo_notaire_titre_heritage",
        "specialty": "real-estate-qc",
        "subject": "verification titre maison heritee",
        "instruction": "Reponds-lui",
        "notes": (
            "Ma mere est decedee et je dois m'occuper de la vente de "
            "sa maison. Le testament la transferait a moi et ma soeur. "
            "Quelles verifications le notaire doit faire avant la vente "
            "et combien ca coute?"
        ),
    },

    # ── DROIT QC (12 cas) ───────────────────────────────────────────────────
    {
        "id": "legal_congediement_sans_preavis",
        "specialty": "legal-qc",
        "subject": "Congediement injustifie?",
        "instruction": "Reponds-lui avec les options",
        "notes": (
            "Mon employeur m'a remercie hier sans preavis apres 8 ans dans "
            "l'entreprise. Pas d'indemnite, juste 'les affaires vont mal'. "
            "Est-ce que c'est legal? Qu'est-ce que je peux faire?"
        ),
    },
    {
        "id": "legal_recouvrement_creance",
        "specialty": "legal-qc",
        "subject": "ex-locataire ne paie pas",
        "instruction": "Reponds-lui",
        "notes": (
            "Mon ancien locataire est parti il y a 3 mois en me devant "
            "8000$ de loyer impaye et de degats. Il ne repond plus a mes "
            "messages. Je dois aller en petites creances ou autre chose?"
        ),
    },
    {
        "id": "legal_divorce_partage_patrimoine",
        "specialty": "legal-qc",
        "subject": "separation - maison familiale",
        "instruction": "Reponds-lui",
        "notes": (
            "Ma femme et moi on se separe apres 12 ans de mariage. La "
            "maison est a mon nom (achetee avant le mariage) mais on l'a "
            "renovee ensemble. Elle veut la moitie. Est-ce qu'elle a "
            "raison? Comment ca marche le patrimoine familial?"
        ),
    },
    {
        "id": "legal_heritage_sans_testament",
        "specialty": "legal-qc",
        "subject": "deces parent sans testament",
        "instruction": "Reponds-lui",
        "notes": (
            "Mon pere est decede la semaine derniere. Il n'avait pas "
            "de testament. Il etait separe (pas divorce officiellement) "
            "depuis 5 ans et avait une nouvelle conjointe. Qui herite quoi "
            "entre la conjointe officielle, la conjointe de fait et nous "
            "les 3 enfants?"
        ),
    },
    {
        "id": "legal_charge_criminelle_premiere",
        "specialty": "legal-qc",
        "subject": "premiere charge - voies de fait",
        "instruction": "Reponds-lui",
        "notes": (
            "Mon fils de 22 ans s'est fait arrete hier pour voies de fait "
            "apres une bagarre dans un bar. C'est sa premiere offense. "
            "Il sort sur promesse mardi. Qu'est-ce qu'on doit faire avant "
            "et qu'est-ce qu'il risque?"
        ),
    },
    {
        "id": "legal_impot_revenu_omis",
        "specialty": "legal-qc",
        "subject": "oubli declaration revenus 2023",
        "instruction": "Reponds-lui",
        "notes": (
            "Je viens de realiser que j'ai oublie de declarer 32000$ de "
            "revenus de mon side-business en 2023. Si je fais une "
            "divulgation volontaire maintenant, est-ce que je risque des "
            "penalites criminelles ou juste des interets?"
        ),
    },
    {
        "id": "legal_consommateur_voiture_defectueuse",
        "specialty": "legal-qc",
        "subject": "voiture usagee defectueuse",
        "instruction": "Reponds-lui",
        "notes": (
            "J'ai achete une voiture usagee chez un concessionnaire "
            "(pas un particulier) il y a 6 mois. La transmission vient "
            "de lacher (12000$ a reparer). Le marchand dit que ce n'est "
            "pas de son probleme. La LPC me protege-t-elle?"
        ),
    },
    {
        "id": "legal_heures_supp_non_payees",
        "specialty": "legal-qc",
        "subject": "OT impayees pendant 6 mois",
        "instruction": "Reponds-lui",
        "notes": (
            "Mon patron me fait travailler 50-55h/sem depuis 6 mois mais "
            "il refuse de payer les heures supp en disant que je suis "
            "'cadre'. Je suis superviseur d'equipe mais je fais le meme "
            "travail technique. Quels sont mes recours?"
        ),
    },
    {
        "id": "legal_mandat_protection_parent",
        "specialty": "legal-qc",
        "subject": "mandat protection mere age",
        "instruction": "Reponds-lui",
        "notes": (
            "Ma mere de 84 ans commence a perdre ses facultes (oublis "
            "frequents, confusion). Elle a fait un mandat de protection "
            "il y a 10 ans avec mon pere comme mandataire mais il est "
            "decede. Comment on l'active maintenant et qui devient "
            "mandataire?"
        ),
    },
    {
        "id": "legal_accident_delit_de_fuite",
        "specialty": "legal-qc",
        "subject": "delit de fuite - mon auto",
        "instruction": "Reponds-lui",
        "notes": (
            "Je suis revenu a mon stationnement hier et mon auto avait "
            "ete frappee. L'autre conducteur est parti sans laisser ses "
            "infos. J'ai pas de temoin et pas de camera. Mon assurance "
            "(seulement responsabilite, pas tous risques) couvre rien. "
            "Est-ce que je peux reclamer a la SAAQ ou ailleurs?"
        ),
    },
    {
        "id": "legal_contrat_signe_sous_pression",
        "specialty": "legal-qc",
        "subject": "bail commercial - vice consentement",
        "instruction": "Reponds-lui",
        "notes": (
            "J'ai signe un bail commercial de 5 ans pour mon nouveau "
            "salon de coiffure le mois passe. Le proprio m'a dit que si "
            "je ne signais pas tout de suite, il avait 3 autres "
            "candidats. J'ai pas eu le temps de lire et il y a des "
            "clauses abusives (loyer +10%/an, restos exclus, etc.). "
            "Est-ce que je peux annuler?"
        ),
    },
    {
        "id": "legal_discrimination_age_emploi",
        "specialty": "legal-qc",
        "subject": "non renouvellement contrat 55 ans",
        "instruction": "Reponds-lui",
        "notes": (
            "J'ai 56 ans et mon contrat de 3 ans n'a pas ete renouvele "
            "alors que mes 2 collegues plus jeunes (32 et 38 ans) l'ont "
            "ete. Mes evaluations etaient toujours bonnes. Le boss a dit "
            "qu'on cherchait 'un nouveau souffle'. Est-ce de la "
            "discrimination par age?"
        ),
    },
]


# ── Métriques objectives ─────────────────────────────────────────────────────


ROBOT_PHRASES = [
    r"de fa[çc]on g[ée]n[ée]rale",
    r"selon les circonstances",
    r"[àa] titre informatif",
    r"je vous propose un aper[çc]u",
    r"pour votre situation sp[ée]cifique",
    r"sans me substituer [àa] un avis",
    r"dans les plus brefs d[ée]lais",
    r"sous r[ée]serve d'une analyse compl[èe]te",
    r"les principes g[ée]n[ée]raux applicables sont les suivants",
    r"ce type de question soul[èe]ve des enjeux",
    r"les grandes lignes sont les suivantes",
]

INLINE_CITATION_RE = re.compile(
    r"\((?:art\.?|arts?\.?|article)\s*[\dA-Z\-]+(?:\s*[A-Z]{2,5})?[^)]*\)"
    r"|"
    r"\((?:LNT|CCQ|CCC|RBQ|OACIQ|GCR|RCI|SCHL)[^)]*\)"
    r"|"
    r"\((?:CCQ|LNT)\s*art\.?\s*[\d\-]+\)",
    re.IGNORECASE,
)

ACTIONABLE_TIMING_RE = re.compile(
    r"\b(cette semaine|ce mois|d'ici (?:demain|une? semaine|quelques? jours?)"
    r"|d[èe]s (?:cette semaine|maintenant|aujourd'hui)"
    r"|dans les?\s+\d+\s+(?:jours?|semaines?))\b",
    re.IGNORECASE,
)

NUMBERED_STEP_RE = re.compile(r"(?:^|\s)(?:\(\d\)|\d[\.\)]\s)", re.MULTILINE)

HEADER_RE = re.compile(r"(?:^|\n)#{1,4}\s|\*\*[^*]+\*\*", re.MULTILINE)

FOOTNOTE_RE = re.compile(r"\n-{3,}\s*\n\s*Sources?\s*[:：]", re.IGNORECASE)


@dataclass
class Metrics:
    word_count: int
    has_footnote: bool
    n_headers: int                # ## or **bold** counts
    n_robot_phrases: int
    n_inline_citations: int
    n_numbered_steps: int
    n_actionable_timings: int     # "cette semaine", "d'ici X jours"…

    def to_dict(self) -> dict:
        return asdict(self)


def compute_metrics(text: str) -> Metrics:
    words = re.findall(r"\S+", text)
    n_robot = sum(
        1 for pat in ROBOT_PHRASES
        if re.search(pat, text, re.IGNORECASE)
    )
    return Metrics(
        word_count=len(words),
        has_footnote=bool(FOOTNOTE_RE.search(text)),
        n_headers=len(HEADER_RE.findall(text)),
        n_robot_phrases=n_robot,
        n_inline_citations=len(INLINE_CITATION_RE.findall(text)),
        n_numbered_steps=len(NUMBERED_STEP_RE.findall(text)),
        n_actionable_timings=len(ACTIONABLE_TIMING_RE.findall(text)),
    )


# ── Appels API ───────────────────────────────────────────────────────────────


def call_refine_text(
    notes: str,
    instruction: str,
    subject: str,
    use_specialty: bool,
    timeout: int = 120,
) -> dict:
    """Appelle POST /api/refine-text. Retourne le payload JSON parsé."""
    body = {
        "text": notes,
        "instruction": instruction,
        "subject": subject,
        "use_specialty": use_specialty,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:200]}"}
    except Exception as e:
        return {"error": str(e)}
    payload["_latency_s"] = round(time.time() - t0, 2)
    return payload


# ── LLM-as-judge ─────────────────────────────────────────────────────────────


JUDGE_SYSTEM = """Tu es un juge senior pour la qualité de réponses email professionnelles dans le contexte juridique/immobilier au Québec.

Tu reçois UN email entrant + DEUX réponses générées (A et B). Tu dois noter chaque réponse sur 4 axes (note de 1 à 10) :

1. PRÉCISION JURIDIQUE (1-10) : Les articles/lois cités existent réellement et s'appliquent au cas ? Pas d'invention de numéros, pas d'erreur de droit ?
2. ANCRAGE AU CAS (1-10) : La réponse parle de la situation décrite (fondation, 6 mois…) ou se contente de définir des concepts juridiques ?
3. TON HUMAIN (1-10) : Prose fluide, pas de phrases-robot ("De façon générale", "Pour votre situation spécifique"), pas d'en-têtes type mémoire d'avocat (## ou **bold**) ?
4. ACTIONNABILITÉ (1-10) : Donne une séquence d'étapes concrètes, des timings ("cette semaine"), des actions précises — pas juste "consultez un professionnel" générique ?

Sortie EXACTEMENT en JSON, rien d'autre :

{
  "A": {"precision": N, "ancrage": N, "ton": N, "actionnabilite": N, "comment": "..."},
  "B": {"precision": N, "ancrage": N, "ton": N, "actionnabilite": N, "comment": "..."},
  "winner": "A" | "B" | "tie",
  "lift_justifies_3x_cost": true | false,
  "reasoning": "1-2 phrases sur le verdict"
}

Sois SÉVÈRE. Une réponse qui contient "De façon générale" perd au moins 2 points en TON. Un email avec en-têtes ## perd 3 points en TON. Une énumération de 4 critères au lieu d'une application au cas perd 3 points en ANCRAGE."""


_anthropic_client = None


def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY missing — cannot run judge")
        _anthropic_client = anthropic.Anthropic(api_key=api_key)
    return _anthropic_client


JUDGE_MODEL = "claude-sonnet-4-5"  # Sonnet 4.5 — strong judge, ~$0.05/case


def call_judge(case_id: str, notes: str, output_a: str, output_b: str) -> dict:
    """Appelle Sonnet directement via l'Anthropic SDK pour scorer la paire."""
    user_prompt = f"""EMAIL ENTRANT (situation du client) :
{notes}

===

RÉPONSE A :
{output_a}

===

RÉPONSE B :
{output_b}

===

Note les deux réponses selon les 4 axes et rends le JSON. Aucun texte avant ou après le JSON."""

    try:
        client = _get_anthropic_client()
        response = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=1500,
            system=JUDGE_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text.strip() if response.content else ""
        # Extract JSON from the response
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return {"_raw": raw, "_error": "no JSON found"}
    except Exception as e:
        return {"_error": str(e)}


# ── Statistiques (intervalles de confiance) ──────────────────────────────────


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """
    Wilson score interval pour une proportion (95% par défaut).

    Bien meilleur que l'intervalle normal pour les petits échantillons.
    Référence: https://en.wikipedia.org/wiki/Binomial_proportion_confidence_interval

    Returns: (lower, upper) bornes ∈ [0, 1].
    """
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    return (sum((v - m) ** 2 for v in values) / (len(values) - 1)) ** 0.5


# ── Coûts modèles (Anthropic, 2026-04, $/MTok) ───────────────────────────────


COST_HAIKU_IN = 1.00      # Haiku 4.5
COST_HAIKU_OUT = 5.00
COST_SONNET_IN = 3.00     # Sonnet 4.6
COST_SONNET_OUT = 15.00


def estimate_cost(metrics: Metrics, mode: str) -> float:
    """Estimation grossière en USD — basée sur word_count comme proxy de tokens.

    Tokens ≈ words × 1.3 (FR), input prompt ~ 800 tokens en standard, ~3000 en expert
    (avec le contexte expert injecté).
    """
    out_tokens = metrics.word_count * 1.3
    if mode == "standard":
        in_tokens = 800
        return (in_tokens * COST_HAIKU_IN + out_tokens * COST_HAIKU_OUT) / 1_000_000
    else:  # expert
        # Sonnet plan: ~3000 tokens in, ~400 out
        plan_cost = (3000 * COST_SONNET_IN + 400 * COST_SONNET_OUT) / 1_000_000
        # Haiku draft: ~3500 tokens in (system + plan), out_tokens
        draft_cost = (3500 * COST_HAIKU_IN + out_tokens * COST_HAIKU_OUT) / 1_000_000
        return plan_cost + draft_cost


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-judge", action="store_true",
                        help="Skip LLM-as-judge")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print full email outputs")
    parser.add_argument("--save", default=None,
                        help="Save results to JSON file")
    args = parser.parse_args()

    print("=" * 80)
    print("EVAL — refine-text expert mode (Ctrl+Shift+G) vs standard (Ctrl+G)")
    print(f"{len(CASES)} cases × 2 modes = {len(CASES) * 2} LLM calls "
          f"(+ {len(CASES)} judge calls)")
    print("=" * 80)

    results = []
    for i, case in enumerate(CASES, 1):
        print(f"\n[{i}/{len(CASES)}] {case['id']}")
        print(f"  Notes: {case['notes'][:100]}...")

        # Standard mode
        print("  Calling STANDARD mode...", end=" ", flush=True)
        std = call_refine_text(
            case["notes"], case["instruction"], case["subject"],
            use_specialty=False,
        )
        if "error" in std:
            print(f"ERROR: {std['error']}")
            continue
        std_text = std.get("refined_text", "")
        std_metrics = compute_metrics(std_text)
        std_cost = estimate_cost(std_metrics, "standard")
        print(f"OK ({std.get('_latency_s', '?')}s, {std_metrics.word_count} mots)")

        # Expert mode
        print("  Calling EXPERT mode...", end=" ", flush=True)
        exp = call_refine_text(
            case["notes"], case["instruction"], case["subject"],
            use_specialty=True,
        )
        if "error" in exp:
            print(f"ERROR: {exp['error']}")
            continue
        exp_text = exp.get("refined_text", "")
        exp_metrics = compute_metrics(exp_text)
        exp_cost = estimate_cost(exp_metrics, "expert")
        warn = exp.get("specialty_info", {}).get("warning")
        print(f"OK ({exp.get('_latency_s', '?')}s, {exp_metrics.word_count} mots)"
              + (f" [warning: {warn}]" if warn else ""))

        # Judge
        judge = None
        if not args.no_judge:
            print("  Calling JUDGE...", end=" ", flush=True)
            judge = call_judge(
                case["id"], case["notes"], std_text, exp_text,
            )
            if "_error" in judge:
                print(f"ERROR: {judge['_error']}")
            else:
                winner = judge.get("winner", "?")
                print(f"OK (winner: {winner})")

        results.append({
            "case_id": case["id"],
            "specialty": case["specialty"],
            "standard": {
                "text": std_text,
                "metrics": std_metrics.to_dict(),
                "cost_usd": round(std_cost, 5),
                "latency_s": std.get("_latency_s"),
            },
            "expert": {
                "text": exp_text,
                "metrics": exp_metrics.to_dict(),
                "cost_usd": round(exp_cost, 5),
                "latency_s": exp.get("_latency_s"),
                "warning": warn,
                "applied_sources": exp.get("specialty_info", {}).get("applied_sources", []),
            },
            "judge": judge,
        })

        if args.verbose:
            print("\n  --- STANDARD ---")
            print("  " + std_text.replace("\n", "\n  "))
            print("\n  --- EXPERT ---")
            print("  " + exp_text.replace("\n", "\n  "))
            if judge and "_error" not in judge:
                print("\n  --- JUDGE ---")
                print("  " + json.dumps(judge, indent=2, ensure_ascii=False).replace("\n", "\n  "))

    # ── Summary ────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("RÉSUMÉ — Métriques objectives (moyennes sur les 5 cas)")
    print("=" * 80)
    if not results:
        print("Aucun résultat exploitable.")
        return

    def avg(field, mode):
        vals = [r[mode]["metrics"][field] for r in results]
        return sum(vals) / len(vals)

    metric_names = ["word_count", "has_footnote", "n_headers", "n_robot_phrases",
                    "n_inline_citations", "n_numbered_steps", "n_actionable_timings"]
    print(f"\n{'Metric':<25} {'Standard':<15} {'Expert':<15} {'Delta':<15}")
    print("-" * 70)
    for m in metric_names:
        s = avg(m, "standard")
        e = avg(m, "expert")
        delta = e - s
        delta_str = f"{delta:+.2f}"
        print(f"{m:<25} {s:<15.2f} {e:<15.2f} {delta_str:<15}")

    # Cost
    avg_std_cost = sum(r["standard"]["cost_usd"] for r in results) / len(results)
    avg_exp_cost = sum(r["expert"]["cost_usd"] for r in results) / len(results)
    print(f"\n{'cost_usd':<25} {avg_std_cost:<15.5f} {avg_exp_cost:<15.5f} "
          f"x{avg_exp_cost / avg_std_cost:.1f}")

    # Latency
    avg_std_lat = sum(r["standard"]["latency_s"] or 0 for r in results) / len(results)
    avg_exp_lat = sum(r["expert"]["latency_s"] or 0 for r in results) / len(results)
    print(f"{'latency_s':<25} {avg_std_lat:<15.2f} {avg_exp_lat:<15.2f} "
          f"+{avg_exp_lat - avg_std_lat:.2f}s")

    # Judge scores
    if not args.no_judge:
        print("\n" + "=" * 80)
        print("JUGE LLM — Scores moyens (1-10) — A=Standard, B=Expert")
        print("=" * 80)
        axes = ["precision", "ancrage", "ton", "actionnabilite"]
        valid = [r for r in results if r.get("judge") and "_error" not in r["judge"]]
        if not valid:
            print("Aucun jugement exploitable.")
        else:
            print(f"\n{'Axe':<20} {'Std (A) µ±σ':<18} {'Exp (B) µ±σ':<18} {'Lift':<10}")
            print("-" * 70)
            for axe in axes:
                a_scores = [r["judge"]["A"][axe] for r in valid if "A" in r["judge"]]
                b_scores = [r["judge"]["B"][axe] for r in valid if "B" in r["judge"]]
                if a_scores and b_scores:
                    a_avg = sum(a_scores) / len(a_scores)
                    b_avg = sum(b_scores) / len(b_scores)
                    a_sd = stddev(a_scores)
                    b_sd = stddev(b_scores)
                    lift = b_avg - a_avg
                    print(f"{axe:<20} {f'{a_avg:.2f} ± {a_sd:.2f}':<18} "
                          f"{f'{b_avg:.2f} ± {b_sd:.2f}':<18} {lift:+.2f}")

            wins = sum(1 for r in valid if r["judge"].get("winner") == "B")
            ties = sum(1 for r in valid if r["judge"].get("winner") == "tie")
            losses = sum(1 for r in valid if r["judge"].get("winner") == "A")
            n = len(valid)
            print(f"\nVerdict du juge : Expert wins {wins}, ties {ties}, losses {losses} (sur {n})")

            # Wilson 95% CI sur la win rate (B wins / total)
            win_rate = wins / n
            ci_lo, ci_hi = wilson_ci(wins, n)
            print(f"Win rate Expert : {win_rate:.1%} "
                  f"(IC 95% Wilson: [{ci_lo:.1%}, {ci_hi:.1%}], n={n})")

            # Win-or-tie rate (Expert "non-perdant")
            wins_or_ties = wins + ties
            wt_rate = wins_or_ties / n
            wt_lo, wt_hi = wilson_ci(wins_or_ties, n)
            print(f"Win-or-tie rate : {wt_rate:.1%} "
                  f"(IC 95% Wilson: [{wt_lo:.1%}, {wt_hi:.1%}])")

            justified = sum(1 for r in valid
                            if r["judge"].get("lift_justifies_3x_cost") is True)
            j_lo, j_hi = wilson_ci(justified, n)
            print(f"Lift justifie 3× cost : {justified}/{n} = {justified/n:.1%} "
                  f"(IC 95%: [{j_lo:.1%}, {j_hi:.1%}])")

            # Breakdown par specialty
            print("\nBreakdown par spécialité :")
            print(f"{'Specialty':<20} {'n':<5} {'Wins':<8} {'Win rate':<12} {'IC 95%':<22}")
            print("-" * 70)
            specialties = sorted(set(r["specialty"] for r in valid))
            for spec in specialties:
                spec_results = [r for r in valid if r["specialty"] == spec]
                spec_n = len(spec_results)
                spec_wins = sum(1 for r in spec_results if r["judge"].get("winner") == "B")
                if spec_n > 0:
                    spec_lo, spec_hi = wilson_ci(spec_wins, spec_n)
                    print(f"{spec:<20} {spec_n:<5} {spec_wins:<8} "
                          f"{spec_wins/spec_n:.1%}{'':<6} "
                          f"[{spec_lo:.1%}, {spec_hi:.1%}]")

            # Cas où Expert a perdu (à analyser)
            losers = [r for r in valid if r["judge"].get("winner") == "A"]
            if losers:
                print(f"\nCas où Expert a PERDU ({len(losers)}/{n}) — à analyser :")
                for r in losers:
                    reasoning = r["judge"].get("reasoning", "?")[:120]
                    print(f"  - {r['case_id']}: {reasoning}")

    if args.save:
        out = Path(args.save)
        out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nRésultats sauvegardés → {out}")


if __name__ == "__main__":
    main()
