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

"""Repro ciblée du bug "reviens-moi" (inversion sémantique de la consigne dictée).

Scénario (cf. capture du 2026-06-15) :
  - Titulaire du compte : Alexandre Simon (co-fondateur d'Agentys, account 1).
  - Il répond à un email de Nathan Roy.
  - Il DICTE la consigne « reviens-moi » (impératif : "[Nathan,] reviens vers moi").
  - Bug observé : le brouillon renverse le sens en « je reviens vers toi avec
    mon feedback dès que j'ai regardé » — Alexandre s'auto-promet de revenir,
    et le contenu paraphrase l'email entrant de Nathan.

Chemin emprunté : VRAI chemin prod — DrafterAgent(account_id=1) sur la KB du
compte 1 (= Alexandre), LLM = container.llm_drafting (Haiku 4.5 via API, cf.
agents.py:__post_init__ "Haiku for all drafts"). N runs (LLM non-déterministe).

Usage:
    python scripts/repro_reviens_moi.py            # 3 runs
    python scripts/repro_reviens_moi.py --runs 5

Exit code:
    1 si le bug est reproduit sur >= 1 run (RED attendu avant fix).
    0 si toutes les sorties préservent la direction (GREEN attendu après fix).
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# Déclenche le chargement dotenv + setup des imports app.
from eval_onboarding import GREEN, RED, YELLOW, DIM, RESET, BOLD  # noqa: E402

# Scénario figé ----------------------------------------------------------------
ACCOUNT_ID = 1  # = Alexandre Simon (cf. data/learning/style_profile_1.json)
USER_EMAIL = "alexandre.simon@hotmail.com"
INSTRUCTIONS = "reviens-moi"

INCOMING = (
    "De: Nathan Roy <nathanroy@gmail.com>\n"
    "Sujet: Re: Feedback site web déploiement\n\n"
    "Salut Alexandre,\n\n"
    "Super ! Je vais regarder ça tout à l'heure et je te donne mon feedback.\n\n"
    "Nathan"
)

HISTORY = [
    {
        "sender": "nathanroy@gmail.com",
        "subject": "Re: Feedback site web déploiement",
        "body": "Salut Alexandre,\n\nSuper ! Je vais regarder ça tout à l'heure et je te donne mon feedback.\n\nNathan",
        "date": "2026-05-28T15:45:00",
    },
]

# Smoking gun : la consigne "reviens-moi" (Nathan doit revenir vers Alexandre)
# ne doit JAMAIS être rendue par une auto-promesse d'Alexandre ("je reviens").
BAD_DIRECTION = re.compile(
    r"je\s+reviens\s+vers\s+(toi|vous)|je\s+(te|vous)\s+reviens",
    re.IGNORECASE,
)
# Signal positif attendu : Alexandre demande à Nathan de revenir vers lui.
GOOD_DIRECTION = re.compile(
    r"reviens\s+vers\s+moi|reviens[- ]moi|tiens[- ]moi\s+au\s+courant|"
    r"fais[- ]moi\s+(signe|un\s+retour)|attends\s+ton\s+(retour|feedback)|"
    r"h[ée]site\s+pas\s+.\s+(me\s+)?revenir",
    re.IGNORECASE,
)


def classify(draft: str) -> str:
    """-> 'BUG' | 'OK' | 'AMBIGU'."""
    if BAD_DIRECTION.search(draft):
        return "BUG"
    if GOOD_DIRECTION.search(draft):
        return "OK"
    return "AMBIGU"


def main() -> int:
    parser = argparse.ArgumentParser(description="Repro bug 'reviens-moi'")
    parser.add_argument("--runs", type=int, default=3, help="Nombre de runs (LLM non-déterministe)")
    parser.add_argument(
        "--instructions",
        default=INSTRUCTIONS,
        help="Consigne dictée (défaut: 'reviens-moi'). Passer '' pour tester l'auto-draft.",
    )
    parser.add_argument("--no-history", action="store_true", help="Ne pas passer l'historique du fil")
    args = parser.parse_args()

    from app.agents import DrafterAgent

    instructions = args.instructions
    history = None if args.no_history else HISTORY
    print(f"{BOLD}Repro bug 'reviens-moi' — DrafterAgent prod (Haiku, account {ACCOUNT_ID}){RESET}")
    label_instr = f">>> {instructions} <<<" if instructions else "(vide = auto-draft)"
    print(f"  Titulaire : Alexandre | Contact : Nathan | Consigne : {label_instr} | history={not args.no_history}\n")

    agent = DrafterAgent(account_id=ACCOUNT_ID)

    verdicts: list[str] = []
    for i in range(1, args.runs + 1):
        draft = agent.draft(
            email_content=INCOMING,
            conversation_history=history,
            instructions=instructions,
            user_email=USER_EMAIL,
        )
        verdict = classify(draft)
        verdicts.append(verdict)
        color = {"BUG": RED, "OK": GREEN, "AMBIGU": YELLOW}[verdict]
        print(f"{color}── Run {i}/{args.runs} : {verdict}{RESET}")
        print(f"{DIM}{draft}{RESET}\n")

    n_bug = verdicts.count("BUG")
    n_ok = verdicts.count("OK")
    n_amb = verdicts.count("AMBIGU")
    print(f"{BOLD}Bilan{RESET} : {RED}{n_bug} BUG{RESET} / {GREEN}{n_ok} OK{RESET} / {YELLOW}{n_amb} AMBIGU{RESET} sur {args.runs} runs")

    if n_bug > 0:
        print(f"{RED}→ Bug reproduit (inversion de direction).{RESET}")
        return 1
    if n_ok == args.runs:
        print(f"{GREEN}→ Toutes les sorties préservent la direction de la consigne.{RESET}")
        return 0
    print(f"{YELLOW}→ Aucun bug franc mais sorties ambiguës — à inspecter.{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
