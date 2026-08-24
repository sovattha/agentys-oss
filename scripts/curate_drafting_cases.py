#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Curate drafting eval cases from persona fixtures (Run2a — Issue #468).

Pipeline:
  1. Extract cases from all persona fixtures via the same logic as
     ``eval_drafting.extract_cases``.
  2. Tag each case with metadata: language (from fixture), length bucket,
     heuristic intent, heuristic complexity.
  3. Stratified-sample N cases (default 15) covering the matrix
     {language × length × intent × complexity}.
  4. Write ``tests/fixtures/drafting_eval/cases.json`` + ``golds-draft.json``
     (golds = reference_reply marked as DRAFT — needs human edit before Run2c).

Pure mechanical curation — no LLM call. The human-in-the-loop step (Run2b)
edits the golds-draft to "if the drafter generated this, I'd send it as-is".

Usage:
    python scripts/curate_drafting_cases.py                 # default 15 cases
    python scripts/curate_drafting_cases.py --n 20          # 20 cases
    python scripts/curate_drafting_cases.py --dry-run       # print, don't write
    python scripts/curate_drafting_cases.py --output-dir <path>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from eval_drafting import DraftingCase, extract_cases, resolve_persona_path  # noqa: E402

PERSONAS = ["lawyer_paris", "sales_director", "startup_ceo", "hr_director", "consultant_intl"]
DEFAULT_OUTPUT_DIR = ROOT / "tests" / "fixtures" / "drafting_eval"


# ── Heuristic taggers (pure, no LLM) ────────────────────────────────────────


def _length_bucket(body: str) -> str:
    """short < 80 words, mid 80-200, long > 200."""
    n = len(body.split())
    if n < 80:
        return "short"
    if n <= 200:
        return "mid"
    return "long"


# Closed vocabulary intent — heuristic only, will mislabel sometimes.
# Run2b human edits include intent re-tagging if the gold reveals a different intent.
_INTENT_PATTERNS = [
    ("decline", re.compile(r"\b(decline|refus|impossible|cannot|d[ée]cliner|regret(?:tably)?|malheureusement|ne peux pas)\b", re.I)),
    ("schedule", re.compile(r"\b(schedule|meeting|call|reunion|r[ée]union|appointment|rdv|disponibilit|availab|propose .{0,12}h\b)\b", re.I)),
    ("ack", re.compile(r"\b(thanks|thank you|merci|received|bien re[çc]u|noted|not[ée])\b", re.I)),
    ("ask", re.compile(r"\?|pourriez|could you|would you|please confirm|veuillez confirmer", re.I)),
]


def _intent_heuristic(incoming_body: str, reference_reply: str | None) -> str:
    """Best-effort intent label. Looks at incoming + reply combined text."""
    haystack = incoming_body + "\n" + (reference_reply or "")
    for label, pattern in _INTENT_PATTERNS:
        if pattern.search(haystack):
            return label
    return "reply"


# Complexity: number of questions in the incoming + body length signal.
def _complexity_heuristic(body: str) -> str:
    n_questions = body.count("?")
    n_words = len(body.split())
    if n_questions >= 3 or n_words > 250:
        return "high"
    if n_questions >= 1 or n_words > 100:
        return "mid"
    return "low"


def _detect_language(body: str) -> str:
    """Cheap language detection: French markers vs English markers.

    Avoids langdetect dependency. Errs on FR if both signals present.
    """
    fr_markers = ("Bonjour", "Cordialement", "Madame", "Monsieur", "Cher ", "vous ", " votre ", "Maître")
    en_markers = ("Hi ", "Hello", "Best regards", "Best,", "Thanks,", "Sincerely", " your ", " you ")
    fr_score = sum(1 for m in fr_markers if m in body)
    en_score = sum(1 for m in en_markers if m in body)
    if fr_score >= en_score:
        return "fr"
    return "en"


# ── Tagged case ────────────────────────────────────────────────────────────


@dataclass
class TaggedCase:
    persona: str
    case: DraftingCase
    language: str
    length: str
    intent: str
    complexity: str
    n_history: int = 0

    @property
    def stratification_key(self) -> tuple[str, str, str, str]:
        return (self.language, self.length, self.intent, self.complexity)

    def to_case_json(self) -> dict[str, Any]:
        return {
            "case_id": self.case.case_id,
            "persona": self.persona,
            "incoming_email": self.case.incoming_email,
            "conversation_history": self.case.conversation_history,
            # default empty — Run2b human edits this with Reply Composer keywords
            # for the cases meant to test guided drafting (≥60% target per README).
            "instructions": "",
            "user_email": self.case.user_email,
            "user_name": self.case.user_name,
            "user_signature": self.case.user_signature,
            "thread_id": self.case.thread_id,
            "metadata": {
                "language": self.language,
                "length": self.length,
                "intent": self.intent,
                "complexity": self.complexity,
                "n_history": self.n_history,
                "has_user_keywords": False,
                "selection_reason": (
                    f"stratification ({self.language}/{self.length}/{self.intent}/{self.complexity})"
                ),
            },
        }

    def to_gold_draft(self) -> dict[str, Any]:
        """Gold draft = reference_reply marked as DRAFT for human edit."""
        return {
            "case_id": self.case.case_id,
            "gold_body": (self.case.reference_reply or "").strip(),
            "rationale": "DRAFT — copied from reference_reply, edit to 'if drafter generated this, I'd send as-is'",
            "edge_cases_handled": [],
            "_status": "draft_needs_human_edit",
        }


def tag_case(persona: str, case: DraftingCase) -> TaggedCase:
    body = case.incoming_email.get("body", "")
    return TaggedCase(
        persona=persona,
        case=case,
        language=_detect_language(body),
        length=_length_bucket(body),
        intent=_intent_heuristic(body, case.reference_reply),
        complexity=_complexity_heuristic(body),
        n_history=len(case.conversation_history),
    )


# ── Stratified sampling ────────────────────────────────────────────────────


def stratified_sample(tagged: list[TaggedCase], n_target: int) -> list[TaggedCase]:
    """Pick ``n_target`` cases maximizing matrix coverage.

    Greedy : iterate strata in size-descending order and pick one case per
    stratum until n_target reached or all strata exhausted; then fill with the
    next case from the largest unsampled strata.
    """
    if n_target >= len(tagged):
        return list(tagged)

    # Group by stratification key
    by_stratum: dict[tuple, list[TaggedCase]] = defaultdict(list)
    for t in tagged:
        by_stratum[t.stratification_key].append(t)

    # Deterministic iteration: by stratum size desc, then key tuple lex
    strata_order = sorted(by_stratum.keys(), key=lambda k: (-len(by_stratum[k]), k))

    picked: list[TaggedCase] = []
    cursors = {k: 0 for k in strata_order}

    while len(picked) < n_target:
        progressed = False
        for k in strata_order:
            if len(picked) >= n_target:
                break
            cur = cursors[k]
            if cur < len(by_stratum[k]):
                picked.append(by_stratum[k][cur])
                cursors[k] = cur + 1
                progressed = True
        if not progressed:
            break  # all strata exhausted

    return picked


# ── IO ──────────────────────────────────────────────────────────────────────


def load_all_cases() -> list[TaggedCase]:
    tagged: list[TaggedCase] = []
    for persona in PERSONAS:
        try:
            fixture = resolve_persona_path(persona)
        except FileNotFoundError:
            print(f"  ⚠ persona '{persona}': fixture missing, skipping")
            continue
        cases, _meta = extract_cases(fixture, max_cases=None)
        if not cases:
            print(f"  ⚠ persona '{persona}': 0 cases extracted (no received→sent threads)")
            continue
        for c in cases:
            tagged.append(tag_case(persona, c))
        print(f"  persona '{persona}': {len(cases)} cases extracted, all tagged")
    return tagged


def write_outputs(picked: list[TaggedCase], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    cases_path = output_dir / "cases.json"
    golds_draft_path = output_dir / "golds-draft.json"

    cases_payload = [t.to_case_json() for t in picked]
    golds_payload = [t.to_gold_draft() for t in picked]

    cases_path.write_text(json.dumps(cases_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    golds_draft_path.write_text(json.dumps(golds_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return cases_path, golds_draft_path


def print_distribution(picked: list[TaggedCase]) -> None:
    print("\n── Distribution sélectionnée ──")
    for axis_name, getter in [
        ("language", lambda t: t.language),
        ("length", lambda t: t.length),
        ("intent", lambda t: t.intent),
        ("complexity", lambda t: t.complexity),
        ("persona", lambda t: t.persona),
    ]:
        counts: dict[str, int] = defaultdict(int)
        for t in picked:
            counts[getter(t)] += 1
        ordered = sorted(counts.items(), key=lambda kv: -kv[1])
        line = ", ".join(f"{k}={v}" for k, v in ordered)
        print(f"  {axis_name:11s}: {line}")


# ── Main ────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Curate drafting eval cases from persona fixtures (Run2a, Issue #468)"
    )
    parser.add_argument("--n", type=int, default=15, help="Target number of cases (default 15)")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Where to write cases.json + golds-draft.json (default {DEFAULT_OUTPUT_DIR.relative_to(ROOT)})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print distribution but don't write files",
    )
    # 2026-05-04 — produit non priorisé sur certains personas (ex. lawyer_paris).
    # Permet de regénérer un cases.json ciblé sans toucher aux fixtures source.
    parser.add_argument(
        "--exclude-personas",
        type=str,
        default="",
        metavar="P1,P2",
        help="Comma-separated persona ids to exclude (ex: lawyer_paris,consultant_intl).",
    )
    args = parser.parse_args()

    excluded = {p.strip() for p in args.exclude_personas.split(",") if p.strip()}
    if excluded:
        print(f"Excluding personas: {sorted(excluded)}")

    print(f"Curating {args.n} cases from persona fixtures...")
    tagged = load_all_cases()
    if excluded:
        before = len(tagged)
        tagged = [t for t in tagged if t.persona not in excluded]
        print(f"  After exclude: {len(tagged)} cases ({before - len(tagged)} dropped)")
    print(f"\n  Total tagged: {len(tagged)} cases across {len(PERSONAS)} personas")

    if not tagged:
        print("  ✗ No cases available. Run aborted.")
        sys.exit(1)

    picked = stratified_sample(tagged, args.n)
    print(f"\n  Picked: {len(picked)} cases via stratified sampling")
    print_distribution(picked)

    if args.dry_run:
        print("\n  --dry-run : files NOT written")
        return

    cases_path, golds_path = write_outputs(picked, args.output_dir)
    # Print absolute path if output is outside repo, relative otherwise.
    def _display(p: Path) -> str:
        try:
            return str(p.relative_to(ROOT))
        except ValueError:
            return str(p)
    print(f"\n  ✓ {_display(cases_path)}")
    print(f"  ✓ {_display(golds_path)} (DRAFT — needs Run2b human edit)")
    print(
        "\n  Next: open golds-draft.json, edit each gold_body to 'I'd send as-is',\n"
        "        rename to golds.json, then run baseline-N (Run2c)."
    )


if __name__ == "__main__":
    main()
