#!/usr/bin/env python3
"""
Apply NER ground truth annotations to emails.csv — V2 (maximum effort).

CONVENTIONS STRICTES :
1. Entités extraites UNIQUEMENT du texte visible (subject + body_preview).
   Les champs sender/sender_name sont des métadonnées et N'APPARTIENNENT PAS au texte
   donné à spaCy pour le benchmark. Exemple : "Fatima" dans "fatima@okara.ai" n'est pas
   taggée comme PERSON si elle n'apparaît pas explicitement dans subject+body.

2. Usernames NON taggés : nathan, lunlunfr, turcotar, @Copilot, vercel[bot], etc.
   Ce sont des handles techniques, pas des noms humains. spaCy les prendra comme false
   positives, ce qui est informatif sur la précision du modèle.

3. Produits/logiciels NON taggés comme ORG : Safari, iOS, Galaxy S26, Windows (discutable
   mais conservateur), cryptography, eventlet, azure-identity, html2canvas, MSAL, etc.
   Les cryptomonnaies (Bitcoin, Ethereum, USDT, BTC) sont des INSTRUMENTS financiers, pas
   des organisations — skip.

4. URLs et parties d'URL NON taggées : "stripe.com" dans une URL ≠ mention de "Stripe"
   comme entité textuelle. spaCy ne tokenise pas les URLs en entités.

5. Caractères zero-width (‌​‍‎‏﻿ etc.) ignorés — invisibles pour humain et spaCy.

6. Dédoublonnage intra-ligne : si "Nathan" apparaît 5 fois, on compte 1 entité.
   Surface forms distinctes ("Nathan Roy" vs "Nathan Roy") comptent comme 2 entités
   distinctes (cases différents = spans différents pour spaCy).

7. Noms dans ORG composé ("Club d'échecs de Vevey") : Vevey n'est PAS re-taggé LOC si
   déjà inclus dans le span ORG. Exception : si Vevey apparaît ailleurs hors de l'ORG.

8. Pour les templates identiques (Vercel deployment ×18, chess.com game-turn ×N), annotation
   strictement identique pour cohérence.

CATÉGORIES SPACY CIBLES (fr_core_news_md) :
- PER (PERSON) : noms de personnes
- ORG : entreprises, institutions, marques, services clairement identifiés
- LOC : villes, pays, régions, adresses
- MISC : non utilisé ici (facultatif)

Format : entités séparées par '|'.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path


# ============================================================================
# ANNOTATIONS V2 (maximum effort, relu ligne par ligne)
# ============================================================================
ANNOTATIONS: dict[str, tuple[str, str, str]] = {
    # --- factures (20 emails) ---
    # 43: Anthropic receipt. Body contient "Anthropic, PBC" x3. Stripe seulement dans URLs — skip.
    "43": ("", "Anthropic, PBC", ""),
    # 117: Vercel usage. Body = zero-width chars. Subject a "Agentys projects".
    "117": ("", "Agentys", ""),
    # 905: Chess club email reply. Richard Besson, Richard, Nathan Roy, Nathan dans body.
    #      "Club d'échecs de Vevey" dans subject ET body. Infomaniak x2.
    #      Vevey subsumé dans l'ORG.
    "905": ("Richard Besson|Richard|Nathan Roy|Nathan", "Club d'échecs de Vevey|Infomaniak", ""),
    # 211: Calendar Line. Nathan Roy (subject), Nathan Roy (body). La Romana, Google Agenda.
    #      "Europe" dans "Heure d'Europe centrale", Paris, Genève, Suisse.
    "211": ("Nathan Roy|Nathan Roy", "La Romana|Google Agenda", "Europe|Paris|Genève|Suisse"),
    # 219: Redcare. Redcare Apotheke (subject + body). Suisse.
    "219": ("", "Redcare Apotheke", "Suisse"),
    # 121: Domaine le Z event. "Domaine le Z" subject + "domaine le Z" body. Coinsins.
    #      Macaron Vanille = sender seulement, PAS dans le texte → skip.
    "121": ("", "Domaine le Z", "Coinsins"),
    # 484: Google AI Studio. "Hello Nathan" + "Google AI Studio" x2 + "Gemini API".
    "484": ("Nathan", "Google AI Studio|Gemini", ""),
    # 946: Klarna. "avec Klarna" dans body.
    "946": ("", "Klarna", ""),
    # 38: GitHub issue #159. Preview tronquée avant "GitHub". "Agentys"/"agentys" en lowercase
    #     dans repo path → skip. Pas d'entités proper-case visibles dans l'extrait.
    "38": ("", "", ""),
    # 898: Chess club, Dušan, Aurelien. "Club d'Échecs de Vevey" + Payerne + Suisse.
    "898": ("Nathan|Dušan Stojanović|Aurelien Pomini", "Club d'Échecs de Vevey", "Suisse|Payerne"),
    # 149: Vercel receipt. Vercel Inc. x3 dans body. Stripe seulement dans URLs → skip.
    "149": ("", "Vercel Inc.", ""),
    # 105: Ana + Olga dans subject ET body. Google Agenda.
    "105": ("Ana|Olga", "Google Agenda", ""),
    # 904: Chess club Laurent. "Salut Laurent" + "Nathan" + "Léo". "Vevey 3" dans subject.
    "904": ("Laurent|Nathan|Léo", "", "Vevey"),
    # 292: Google Cloud invoice. Nathan Roy + Google Cloud Platform x2.
    "292": ("Nathan Roy", "Google Cloud Platform", ""),
    # 301: Vacances Pâques. Google Agenda seulement.
    "301": ("", "Google Agenda", ""),
    # 332: Macaron Vanille Lausanne. "le MACCARO à Lausanne-Flon". "UNIQUE EN SUISSE !".
    #      Macaron Vanille PAS dans le texte visible.
    "332": ("", "MACCARO", "Flon|Lausanne|Suisse"),
    # 212: Macaron Vanille Coinsins. "MacaronVanille sur Instagram" + Coinsins + Gland.
    "212": ("", "MacaronVanille|Instagram", "Coinsins|Gland"),
    # 167: Stripe webhook. "Stripe" x3 + "Agentys".
    "167": ("", "Stripe|Agentys", ""),
    # 40: GitHub issue #158. Preview tronquée avant "GitHub". Pas d'entités visibles.
    "40": ("", "", ""),
    # 908: Chess club Richard. "Salut Richard" + "Nathan". "Club d'échecs de Vevey" + Infomaniak.
    "908": ("Richard|Nathan", "Club d'échecs de Vevey|Infomaniak", ""),
    # --- rdv (10 emails) ---
    # 264: STOKR. STOKR x2 + H100 Group AB + NGM. Luxembourg.
    "264": ("", "STOKR|H100 Group AB|NGM", "Luxembourg"),
    # 133: Chess.com bots cirque. "sur Chess.com !" dans body.
    "133": ("", "Chess.com", ""),
    # 181: GitHub UX Mobile. "L'app Agentys" dans body. Safari = produit, skip.
    "181": ("", "Agentys", ""),
    # 13: Elections. Body = zero-width. Rien.
    "13": ("", "", ""),
    # 753: Chess.com "C'est les échecs ou rien". Body ne mentionne PAS "Chess.com" visiblement.
    #      Le mot "Chess.com" est dans le sender, pas dans le texte.
    "753": ("", "", ""),
    # 260: Notion. "Notion's Terms" dans subject.
    "260": ("", "Notion", ""),
    # 104: TCS. "Le Grand Prix TCS" subject.
    "104": ("", "TCS", ""),
    # 134: Chess.com bots cirque (dup de 133). "sur Chess.com !".
    "134": ("", "Chess.com", ""),
    # 180: GitHub PR #146. Subject mentionne "ux-mobile". Body fait références à Safari (skip),
    #      WCAG (standard, skip). Pas d'ORG/PER valables.
    "180": ("", "", ""),
    # 23: ElevenLabs credits. Body : "in ElevenCreative for 24 hours". ElevenLabs sender seulement.
    "23": ("", "ElevenCreative", ""),
    # --- support (21 emails) ---
    # 358: GitHub issue close. "view it on GitHub:" visible.
    "358": ("", "GitHub", ""),
    # 54: Deps outdated. Seuls des noms de packages (cryptography, eventlet, azure-identity...).
    #     Pas d'entités NER standard.
    "54": ("", "", ""),
    # 460: GitHub close. "view it on GitHub:" visible.
    "460": ("", "GitHub", ""),
    # 438: GitHub close. "view it on GitHub:" visible.
    "438": ("", "GitHub", ""),
    # 430: GitHub close. "view it on GitHub:" visible.
    "430": ("", "GitHub", ""),
    # 459: GitHub comment + "view it on GitHub:".
    "459": ("", "GitHub", ""),
    # 471: GitHub comment + "view it on GitHub:".
    "471": ("", "GitHub", ""),
    # 410: GitHub bug empty_body. Preview se termine par "view it on GitH..." → tronqué.
    #      Strictement, "GitHub" n'est pas un mot complet dans le texte. Skip.
    "410": ("", "", ""),
    # 881: Issue #171 security. Preview tronquée avant GitHub. Package names seulement.
    "881": ("", "", ""),
    # 50: Dead code. Preview termine par file paths. Pas d'entité standard.
    "50": ("", "", ""),
    # 103: UX Audit. Preview contient "l'agent nocturne Playwright". Playwright = outil Microsoft.
    "103": ("", "Playwright", ""),
    # 736: GitHub issue close. "view it on GitHub:" visible.
    "736": ("", "GitHub", ""),
    # 384: GitHub issue + "dimension mismatch Qdrant" + "view it on GitHub:".
    "384": ("", "Qdrant|GitHub", ""),
    # 371: Vercel bot PR #127. Body = base64 massif. Pas d'entités lisibles.
    #      Subject : "[nathan/agentys] fix(#74): Workflow cancel API non implémentée côté frontend (PR #127)".
    #      Pas de mot-majuscule ORG.
    "371": ("", "", ""),
    # 197: Entraînement issue. "Refonte Entraînement d'Agentys" dans body.
    "197": ("", "Agentys", ""),
    # 233: Julien newsletter. Julien, Thomas, Inoxtag, Djilsi, Maxime Biaggi, LeBouseuh.
    "233": ("Julien|Thomas|Inoxtag|Djilsi|Maxime Biaggi|LeBouseuh", "", ""),
    # 425: GitHub issue + "dimension mismatch Qdrant" + "view it on GitHub:".
    "425": ("", "Qdrant|GitHub", ""),
    # 96: Google indexing. "Google has started validating..." + "Google" x2.
    "96": ("", "Google", ""),
    # 415: GitHub bug simple_email. Preview tronquée avant "GitH..." — strict skip.
    "415": ("", "", ""),
    # 751: Google security. "[image: Google]" + "your Google Account" + "Windows device".
    #      Windows = OS, tagué ORG par convention Microsoft.
    "751": ("", "Google|Windows", ""),
    # --- internal (20 emails, 18 Vercel deployment templates identiques + 2 GitHub) ---
    # Template Vercel : "Hey Nathan" + "Agentys projects" (subject) + "Vercel Inc." + "Covina, CA".
    "876": ("Nathan", "Vercel Inc.|Agentys", "Covina"),
    "178": ("Nathan", "Vercel Inc.|Agentys", "Covina"),
    "280": ("Nathan", "Vercel Inc.|Agentys", "Covina"),
    "111": ("Nathan", "Vercel Inc.|Agentys", "Covina"),
    "248": ("Nathan", "Vercel Inc.|Agentys", "Covina"),
    "10":  ("Nathan", "Vercel Inc.|Agentys", "Covina"),
    "725": ("Nathan", "Vercel Inc.|Agentys", "Covina"),
    "235": ("Nathan", "Vercel Inc.|Agentys", "Covina"),
    "728": ("Nathan", "Vercel Inc.|Agentys", "Covina"),
    "724": ("Nathan", "Vercel Inc.|Agentys", "Covina"),
    "721": ("Nathan", "Vercel Inc.|Agentys", "Covina"),
    "1":   ("Nathan", "Vercel Inc.|Agentys", "Covina"),
    "750": ("Nathan", "Vercel Inc.|Agentys", "Covina"),
    "120": ("Nathan", "Vercel Inc.|Agentys", "Covina"),
    "745": ("Nathan", "Vercel Inc.|Agentys", "Covina"),
    "97":  ("Nathan", "Vercel Inc.|Agentys", "Covina"),
    "883": ("Nathan", "Vercel Inc.|Agentys", "Covina"),
    "155": ("Nathan", "Vercel Inc.|Agentys", "Covina"),
    # 204 : GitHub PR #136. Subject capitalise "Agentys button". Body = base64 massif.
    "204": ("", "Agentys", ""),
    # 179 : GitHub PR #146. Subject lowercase "ux-mobile". Pas d'entités majuscules.
    "179": ("", "", ""),
    # --- spam_like (15 emails) ---
    # 339: Amare. "Dear Amare Family, Amare is making..." + "across Europe".
    "339": ("", "Amare", "Europe"),
    # 77: LesScoresDeChantal PR #46 merge. "view it on GitHub: https://github.com/LesScoresDeChantal/..."
    #     GitHub visible + LesScoresDeChantal dans chemin text.
    "77": ("", "LesScoresDeChantal|GitHub", ""),
    # 338: Amare dup.
    "338": ("", "Amare", "Europe"),
    # 73: Okara. "Google Search Console" x2 + "Google" x2. Fatima = sender seulement → skip.
    "73": ("", "Google Search Console|Google", ""),
    # 337: Amare dup.
    "337": ("", "Amare", "Europe"),
    # 78: LesScoresDeChantal PR #47. "Stripe affiliation" + "Stripe promo" dans body.
    #     @Copilot = bot handle, skip.
    "78": ("", "Stripe", ""),
    # 74: LesScoresDeChantal PR #46 Re:. Même contenu que 78 (email reply same thread).
    "74": ("", "Stripe", ""),
    # 207: Higgsfield. "Welcome to Higgsfield!" + "Higgsfield" x3.
    "207": ("", "Higgsfield", ""),
    # 286: Notion/David G. Subject : "David G and 1 other made updates in LesScoresDeChantal".
    #      Body = zero-width. Notion dans sender seulement → skip.
    "286": ("David G", "LesScoresDeChantal", ""),
    # 16: Samsung. Body = URL longue + "dès maintenant les nouvelles offres". "Samsung" uniquement
    #     dans URL samsung.com. Pas d'entité textuelle.
    "16": ("", "", ""),
    # 261: Ethermail. "via PayMail" + "Ethermail Ads" + "© 2025 EtherMail" + "from EtherMail".
    "261": ("", "Ethermail|PayMail|EtherMail", ""),
    # 189: Chantal Läng in subject. LesScoresDeChantal in subject. Body = zero-width.
    #      Notion = sender seulement → skip.
    "189": ("Chantal Läng", "LesScoresDeChantal", ""),
    # 769: Yellow Media (subject). Body : "Bloomberg Strategist Predicts Tether..." + "Bitcoin"
    #      (crypto), "Ethereum" (crypto). Tether est à la fois crypto ET Tether Ltd — tag ambigu
    #      mais le contexte parle de l'émetteur ("Tether's massive... supply"). Tag Tether.
    "769": ("", "Yellow Media|Bloomberg|Tether", ""),
    # 252: Notion mention Chantal. Body : "@Jérémy svp... @Nathan Roy". Subject : "Chantal Läng".
    "252": ("Chantal Läng|Jérémy|Nathan Roy", "", ""),
    # 254: Idem 252 (même template).
    "254": ("Chantal Läng|Jérémy|Nathan Roy", "", ""),
    # 159: Notion workspace bot + LesScoresDeChantal/SERVICE-APIMetier-ts + "view it on GitHub:".
    "159": ("", "LesScoresDeChantal|GitHub", ""),
    # --- newsletter (20 emails) ---
    # 317: Cryptorecherche + "Yrile" signature.
    "317": ("Yrile", "Cryptorecherche", ""),
    # 232: Samsung S26 URL + "Galaxy S26" produit. Samsung pas dans texte visible.
    "232": ("", "", ""),
    # 313: Chess.com + lunlunfr (username skip).
    "313": ("", "Chess.com", ""),
    # 336: Chess.com + lunlunfr (username skip).
    "336": ("", "Chess.com", ""),
    # 282: Samsung URL body. Pas d'entité textuelle.
    "282": ("", "", ""),
    # 341: Chess.com + lunlunfr (skip).
    "341": ("", "Chess.com", ""),
    # 314: Chess.com + turcotar (username skip).
    "314": ("", "Chess.com", ""),
    # 910: Fwd Vevey Echecs. "Laurent", "Nathan", "Cindy Werner". "Formspree", "Vevey Echecs"
    #      (dans "submission on Inscriptions Vevey Echecs").
    "910": ("Laurent|Nathan|Cindy Werner", "Formspree|Vevey Echecs", ""),
    # 250: Chess.com + turcotar (skip).
    "250": ("", "Chess.com", ""),
    # 128: Blockunity Bitcoin. "Philip Swift" dans body. Bitcoin = instrument skip.
    #      Blockunity uniquement dans URL → skip.
    "128": ("Philip Swift", "", ""),
    # 171: Cryptorecherche + "chaîne YouTube" + "vidéo Youtube publique".
    "171": ("", "Cryptorecherche|Youtube|YouTube", ""),
    # 363: Chess.com + lunlunfr (skip).
    "363": ("", "Chess.com", ""),
    # 359: Cryptorecherche + "Nouvelle vidéo Paul Cryptoformation".
    "359": ("Paul", "Cryptorecherche", ""),
    # 246: Cryptorecherche. USDT = token skip.
    "246": ("", "Cryptorecherche", ""),
    # 118: Cryptorecherche + Yrile. TAO = token skip.
    "118": ("Yrile", "Cryptorecherche", ""),
    # 165: Chess.com + turcotar (skip).
    "165": ("", "Chess.com", ""),
    # 244: Vercel Your competitors. Body = zero-width. Subject = pas d'ORG textuel
    #      (Vercel uniquement sender).
    "244": ("", "", ""),
    # 199: Chess.com + turcotar (skip).
    "199": ("", "Chess.com", ""),
    # 17: Chess.com + lunlunfr (skip).
    "17": ("", "Chess.com", ""),
    # 67: Sweatcoin. Subject "Nathan, vous êtes..." + body "Nathan, voici..." + "Gains Sweatcoin"
    #     + "Sweatcoins".
    "67": ("Nathan", "Sweatcoin|Sweatcoins", ""),
}


def apply_annotations(csv_path: Path, out_path: Path) -> None:
    """Rewrite CSV with annotations populated."""
    rows: list[dict] = []
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            email_id = row["id"]
            if email_id in ANNOTATIONS:
                person, org, loc = ANNOTATIONS[email_id]
                row["entities_person"] = person
                row["entities_org"] = org
                row["entities_loc"] = loc
            rows.append(row)

    fieldnames = ["id", "category", "sender", "subject", "body_preview",
                  "entities_person", "entities_org", "entities_loc"]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)

    # Stats par catégorie
    total = len(rows)
    annotated = sum(1 for r in rows if r["id"] in ANNOTATIONS)
    missing = [r["id"] for r in rows if r["id"] not in ANNOTATIONS]

    def count_entities(value: str) -> int:
        return len(value.split("|")) if value else 0

    persons_by_cat: dict[str, int] = {}
    orgs_by_cat: dict[str, int] = {}
    locs_by_cat: dict[str, int] = {}
    rows_with_entities_by_cat: dict[str, int] = {}

    for r in rows:
        if r["id"] not in ANNOTATIONS:
            continue
        p, o, loc = ANNOTATIONS[r["id"]]
        cat = r["category"]
        persons_by_cat[cat] = persons_by_cat.get(cat, 0) + count_entities(p)
        orgs_by_cat[cat] = orgs_by_cat.get(cat, 0) + count_entities(o)
        locs_by_cat[cat] = locs_by_cat.get(cat, 0) + count_entities(loc)
        if p or o or loc:
            rows_with_entities_by_cat[cat] = rows_with_entities_by_cat.get(cat, 0) + 1

    print(f"Rows: {total}, annotés: {annotated}, manquants: {len(missing)}")
    if missing:
        print(f"IDs sans annotation: {missing}")

    total_p = sum(persons_by_cat.values())
    total_o = sum(orgs_by_cat.values())
    total_l = sum(locs_by_cat.values())
    print(f"\nEntités totales : PERSON={total_p} | ORG={total_o} | LOC={total_l} | total={total_p+total_o+total_l}")

    print("\nVentilation par catégorie :")
    for cat in sorted(set(persons_by_cat) | set(orgs_by_cat) | set(locs_by_cat)):
        p = persons_by_cat.get(cat, 0)
        o = orgs_by_cat.get(cat, 0)
        loc = locs_by_cat.get(cat, 0)
        with_ent = rows_with_entities_by_cat.get(cat, 0)
        print(f"  {cat:12s} | PER={p:3d} ORG={o:3d} LOC={loc:3d} | rows avec entités={with_ent}")

    # Rows complètement vides (aucune entité)
    empty_rows = [r["id"] for r in rows
                  if r["id"] in ANNOTATIONS
                  and not any(ANNOTATIONS[r["id"]])]
    print(f"\nRows sans aucune entité : {len(empty_rows)} "
          f"(attendu pour templates auto + URLs : newsletters/spam/github)")

    print(f"\nOutput : {out_path}")


def main() -> int:
    csv_path = Path("tmp/ner_benchmark/emails.csv")
    out_path = Path("tmp/ner_benchmark/emails.csv")
    apply_annotations(csv_path, out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
