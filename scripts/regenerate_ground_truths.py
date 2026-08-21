#!/usr/bin/env python3
"""Regenerate ground_truth_*.json fixtures to match the current profile schema.

Audit 2026-05-06: the ProfileAgent prompt evolved to extract three new fields
(``preferred_name``, ``addressing``, ``language_variant``) but the
``ground_truth_*.json`` fixtures were never updated. The judge counts those
fields as "fabricated" → -10 to -15 pts on Profile per persona.

This script adds the three fields to each ground truth based on:
  - User signature first name → preferred_name
  - Existing rules (tutoiement_team / vouvoiement_external_fr) → addressing
  - User domain TLD + persona description → language_variant

Idempotent: re-running on an already-updated file leaves it alone.

Run:
    python scripts/regenerate_ground_truths.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"


# Per-persona derived values. Each entry adds these three fields to
# expected_profile. Derivations documented next to each value.
_PROFILE_PATCHES: dict[str, dict] = {
    # Sophie Martin — TechCorp.fr PM. Signs casual emails as "Sophie",
    # tutoyer team (Pierre, Lucas, Camille) but vouvoyer clients (Mme
    # Leclerc, Mme Petit, M. Renard) → addressing = "mixed".
    "ground_truth.json": {
        "preferred_name": "Sophie",
        "addressing": "mixed",
        "language_variant": "fr-FR",
    },
    # Marc-Antoine Barreau — Avocat Paris, almost everything formal in
    # French legal register. Signs full name. Vouvoiement strict.
    "ground_truth_lawyer_paris.json": {
        "preferred_name": "Marc-Antoine",
        "addressing": "vous",
        "language_variant": "fr-FR",
    },
    # Karim Mandat — Sales director Lyon. Casual with team, formal with
    # clients per closings ("Bonjour Madame/Monsieur" formal +
    # "Salut {first_name}" casual). Addressing = mixed.
    "ground_truth_sales_director.json": {
        "preferred_name": "Karim",
        "addressing": "mixed",
        "language_variant": "fr-FR",
    },
    # Priya Pivot — Startup CEO bilingual EN/FR. Rules explicitly say
    # tutoiement_team + vouvoiement_external_fr → mixed. No regional
    # signal (bilingual, .io domain, code-switching FR/EN) → null.
    "ground_truth_startup_ceo.json": {
        "preferred_name": "Priya",
        "addressing": "mixed",
        "language_variant": None,
    },
    # Catherine Carrière — DRH banque (BCP-banque.fr). Strictly formal
    # banking French. Vouvoiement everywhere.
    "ground_truth_hr_director.json": {
        "preferred_name": "Catherine",
        "addressing": "vous",
        "language_variant": "fr-FR",
    },
    # James Conseil — International consultant, strategyco.com, English-
    # primary (languages: ["en"]). Casual closing "J." or "Cheers, / J.".
    # No FR addressing context (English doesn't have tu/vous) → null.
    # Strategyco is a US-style consulting firm without UK markers → en-US.
    "ground_truth_consultant_intl.json": {
        "preferred_name": "James",
        "addressing": None,
        "language_variant": "en-US",
    },
}


def patch_one(path: Path, fields: dict, *, dry_run: bool) -> tuple[str, list[str]]:
    """Apply the 3-field patch to a single ground-truth file.

    Returns (status, added_keys). Idempotent — re-applying a patch only
    overwrites None values; doesn't clobber any existing customisation.
    """
    if not path.exists():
        return ("missing", [])
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    profile = data.setdefault("expected_profile", {})
    added: list[str] = []
    for key, val in fields.items():
        # Idempotent: only set when key is absent or explicitly null.
        if key not in profile or profile[key] is None and val is not None:
            profile[key] = val
            added.append(key)
    if not added:
        return ("unchanged", [])
    if dry_run:
        return ("would-update", added)
    # Pretty-print to keep diffs readable. ensure_ascii=False preserves
    # the existing French accents in the file (we already saw the cp1252
    # encoding bug; UTF-8 round-trip is mandatory).
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return ("updated", added)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would change without writing files")
    args = ap.parse_args()

    print(f"Regenerating {len(_PROFILE_PATCHES)} ground-truth fixtures "
          f"({'dry-run' if args.dry_run else 'WRITING'})\n")

    summary: list[tuple[str, str, list[str]]] = []
    for filename, fields in _PROFILE_PATCHES.items():
        path = FIXTURES / filename
        status, added = patch_one(path, fields, dry_run=args.dry_run)
        summary.append((filename, status, added))
        marker = {
            "updated": "UPDATED",
            "would-update": "WOULD UPDATE",
            "unchanged": "OK (already current)",
            "missing": "MISSING FILE",
        }[status]
        print(f"  {filename}: {marker}")
        if added:
            print(f"      added: {', '.join(added)}")

    n_changed = sum(1 for _, s, _ in summary if s in ("updated", "would-update"))
    print(f"\n{n_changed}/{len(summary)} files {'would change' if args.dry_run else 'changed'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
