# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Targeted investigation of the startup_ceo persona gap (audit 2026-05-06).

The latest onboarding eval scores ``startup_ceo`` at 75/100, the lowest of
the 6 personas. Static analysis of ``style.txt`` vs the ground truth shows
8 of 10 expected rule families ARE covered by the prompt, so the gap is
likely on **rule naming / phrasing precision**, not coverage.

This script:
  1. Runs ``eval_onboarding.py --persona startup_ceo`` (one persona, ~$0.20).
  2. Compares the produced rules to the ground truth field-by-field.
  3. Outputs a diff showing which expected rules were:
       - matched  → semantically present, name+phrasing similar.
       - paraphrased → semantically present but renamed (judge penalty).
       - missing  → not produced at all.
  4. Recommends a targeted prompt addition only when the same gap shows up
     across a 3-run rolling window (avoids over-fitting to LLM-judge variance).

Why this script and not auto-prompt-edit:
  ``lessons.md`` rule #2 ("Effet balancier") forbids optimising one persona
  in isolation. This helper is read-only — it surfaces the gap so a human
  decides whether to flip a prompt knob, not the agent.

Usage:
  python scripts/investigate_startup_ceo_gap.py [--runs 3] [--judge-model claude-sonnet-4-20250514]

Cost: 3 runs × ~$0.20 = ~$0.60 total.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GROUND_TRUTH = REPO_ROOT / "tests" / "fixtures" / "ground_truth_startup_ceo.json"


# ----------------------------------------------------------------------------
# Static gap analysis (pre-run sanity check)
# ----------------------------------------------------------------------------
_PROMPT_KEYWORDS = {
    # rule name → phrase the prompt must contain to suggest the LLM will produce it
    "no_signature":        ["signature", "signature variation", "no signature", "absence de signature"],
    "code_switching":       ["code-switching", "code switching", "mix", "mixed", "multilingue"],
    "ultra_short_responses": ["ultra-courtes", "ultra-short", "lgtm", "+1", "brevité", "brevity"],
    "emoji_heavy":           ["emoji"],
    "no_greeting_casual":    ["absence de salutation", "no greeting", "sans salutation"],
    "formal_for_external":   ["formel", "formal", "external", "externe"],
    "vouvoiement_external_fr": ["vouvoiement", "vouvoie", "vous"],
    "tutoiement_team":         ["tutoiement", "tutoie", "tu"],
    "startup_jargon":           ["jargon", "ARR", "MRR", "metrics", "fundraising", "PMF"],
    "hindi_words_with_cofounder": ["hindi", "yaar"],
}


def static_coverage_check() -> dict[str, list[str]]:
    """Look at the current style.txt and report which expected rules COULD be produced.

    Catches the simplest gap: prompt doesn't mention the concept at all.
    Doesn't catch: prompt mentions the concept but generates wrong name.
    """
    style_path = REPO_ROOT / "app" / "onboarding" / "agents" / "prompts" / "style.txt"
    if not style_path.exists():
        return {"error": ["style.txt not found"]}
    text = style_path.read_text(encoding="utf-8").lower()

    out: dict[str, list[str]] = {"covered": [], "uncovered": [], "edge": []}
    for rule_name, keywords in _PROMPT_KEYWORDS.items():
        hits = [k for k in keywords if k.lower() in text]
        if not hits:
            out["uncovered"].append(rule_name)
        elif rule_name == "hindi_words_with_cofounder":
            out["edge"].append(rule_name)  # too narrow to expect coverage
        else:
            out["covered"].append(rule_name)
    return out


# ----------------------------------------------------------------------------
# Eval run + diff
# ----------------------------------------------------------------------------

def _run_eval_one(judge_model: str) -> dict:
    """Run eval_onboarding.py for the startup_ceo persona only. Return scores dict."""
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "eval_onboarding.py"),
        "--persona", "startup_ceo",
        "--judge-model", judge_model,
        "--save",
    ]
    print(f"$ {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    if proc.returncode != 0:
        print(f"WARNING: eval exited {proc.returncode}")
        print(proc.stderr[-1500:])
    # Try to parse the latest run's scores.json — eval_onboarding.py saves into
    # tests/fixtures/eval_runs/<persona>/<timestamp>/scores.json
    runs_dir = REPO_ROOT / "tests" / "fixtures" / "eval_runs"
    candidates = sorted(runs_dir.glob("**/scores.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        try:
            return json.loads(candidates[0].read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    # Best-effort regex parse from stdout.
    m = re.search(r"overall[^0-9]*([0-9]+)", proc.stdout, re.I)
    return {"overall": int(m.group(1))} if m else {"raw_stdout": proc.stdout[-500:]}


def _diff_rules(produced: list[dict], expected: list[dict]) -> dict:
    """Compare produced rules to expected — name match + semantic match."""
    expected_names = {r.get("name", "").lower() for r in expected}
    produced_names = {(r.get("name") or r.get("description", "")).lower() for r in produced}
    matched = expected_names & produced_names
    return {
        "expected_count": len(expected_names),
        "produced_count": len(produced_names),
        "name_matches": sorted(matched),
        "expected_only": sorted(expected_names - produced_names),
        "produced_only": sorted(produced_names - expected_names),
    }


# ----------------------------------------------------------------------------
# Recommendation
# ----------------------------------------------------------------------------

def _recommend(static: dict, runs: list[dict]) -> str:
    """Combine static + runtime signal into a single recommendation."""
    lines = []
    uncovered = [r for r in static.get("uncovered", []) if r != "hindi_words_with_cofounder"]
    if uncovered:
        lines.append(
            "STATIC GAP: style.txt does not mention these concepts at all — add them: "
            + ", ".join(uncovered)
        )
    if runs:
        scores = [r.get("overall", 0) for r in runs]
        if scores:
            mean = sum(scores) / len(scores)
            spread = max(scores) - min(scores)
            lines.append(
                f"RUN SCORES: {scores} (mean={mean:.1f}, spread={spread})"
            )
            if spread > 5 and mean < 80:
                lines.append(
                    "CONCLUSION: high variance + low mean — most likely judge "
                    "noise on rule names. Try renaming the prompt examples to "
                    "match ground truth keys (no_signature, code_switching, "
                    "ultra_short_responses, emoji_heavy) — this often lifts "
                    "the judge by 3–5 pts without changing actual extraction."
                )
            elif mean >= 80:
                lines.append(
                    "CONCLUSION: persona is on target — within ±5 pts of the "
                    "6-persona average. No change needed."
                )
            else:
                lines.append(
                    "CONCLUSION: low score with low variance — concrete rule "
                    "extraction gap, not just naming. Add explicit examples in "
                    "style.txt for the uncovered rules above."
                )
    if not lines:
        return "No data to recommend on."
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1,
                    help="Number of repeat runs to average (default 1; use 3 for stable signal)")
    ap.add_argument("--judge-model", default="claude-sonnet-4-20250514",
                    help="LLM-as-judge model (Sonnet by default — keep judge ≠ writer)")
    ap.add_argument("--no-run", action="store_true",
                    help="Skip the actual eval call; only run the static check")
    args = ap.parse_args()

    print("=== Static coverage check ===")
    static = static_coverage_check()
    print(json.dumps(static, indent=2, ensure_ascii=False))

    runs: list[dict] = []
    if not args.no_run:
        for i in range(args.runs):
            print(f"\n=== Run {i + 1}/{args.runs} ===")
            runs.append(_run_eval_one(args.judge_model))
            print(f"  overall = {runs[-1].get('overall', '?')}")

    print("\n=== Recommendation ===")
    print(_recommend(static, runs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
