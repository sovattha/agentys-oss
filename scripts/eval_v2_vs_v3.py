# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Eval V3 revision (CRITIC_MAX_REVISIONS=2) vs V2-only (=1).

Audit 2026-05-06: V3 was shipped 2026-05-05 without proof it materially
improves over V2 on the 6 personas. This script runs ``eval_drafting.py``
twice with the env flag flipped, compares overall scores, and prints a
verdict.

Usage::

    python scripts/eval_v2_vs_v3.py [--personas N] [--judge-model MODEL]

Output:
    eval_v2: 73.4 ± 4.2  (50 cases, 3 personas, $0.81)
    eval_v3: 75.1 ± 3.8  (50 cases, 3 personas, $1.02)
    delta:   +1.7 pts (within ±5 LLM-judge variance — cannot conclude)

Cost: ~$1-3 depending on persona count and judge model. Run manually
when you want to decide whether to keep V3 enabled by default.

Implementation: spawns ``scripts/eval_drafting.py`` as a subprocess so
this script doesn't need to know the harness internals. The harness
exit code + stdout are parsed for the average score.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_eval(critic_max_revisions: int, args: argparse.Namespace) -> dict:
    """Run eval_drafting.py with CRITIC_MAX_REVISIONS=N. Returns parsed result."""
    env = os.environ.copy()
    env["CRITIC_MAX_REVISIONS"] = str(critic_max_revisions)
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "eval_drafting.py"),
        "--all-personas" if args.all_personas else "--personas",
        *([str(args.personas)] if not args.all_personas else []),
        "--judge-model", args.judge_model,
        "--output-json",
    ]
    print(f"\n=== Running eval with CRITIC_MAX_REVISIONS={critic_max_revisions} ===")
    print(f"$ {' '.join(cmd)}")
    proc = subprocess.run(
        cmd, env=env, capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    if proc.returncode != 0:
        print(f"WARNING: eval exited with code {proc.returncode}")
        print(proc.stderr[-2000:])
    # Try to parse a JSON line from stdout. eval_drafting.py is expected
    # to emit a structured summary at the end when --output-json is set.
    # Fall back to regex parsing of "score=XX.X" patterns.
    summary: dict = {"raw_stdout_tail": proc.stdout[-2000:]}
    for line in proc.stdout.splitlines()[::-1]:
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                summary.update(json.loads(line))
                break
            except json.JSONDecodeError:
                continue
    if "overall_mean" not in summary:
        # Best-effort regex fallback.
        m = re.search(r"overall[_\s]*mean[:\s=]+([0-9.]+)", proc.stdout, re.I)
        if m:
            summary["overall_mean"] = float(m.group(1))
        m = re.search(r"total[_\s]*cost[_\s]*usd[:\s=$]+([0-9.]+)", proc.stdout, re.I)
        if m:
            summary["total_cost_usd"] = float(m.group(1))
    return summary


def _verdict(v2: dict, v3: dict, variance_pts: float = 5.0) -> str:
    m2 = v2.get("overall_mean", 0.0)
    m3 = v3.get("overall_mean", 0.0)
    delta = m3 - m2
    cost_extra = (v3.get("total_cost_usd", 0.0) - v2.get("total_cost_usd", 0.0))
    if abs(delta) < variance_pts:
        return (
            f"INCONCLUSIVE: delta={delta:+.1f} pts is within ±{variance_pts:.0f} pts "
            f"of LLM-judge variance. V3 cost +${cost_extra:.2f} for no clear win — "
            "recommend setting CRITIC_MAX_REVISIONS=1 and revisiting after a "
            "prompt change to V3 directives."
        )
    if delta > 0:
        return (
            f"KEEP V3: +{delta:.1f} pts above noise. Cost overhead: +${cost_extra:.2f} "
            f"on this run (~{cost_extra / max(v2.get('total_cost_usd', 0.0), 1e-6):.0%}). "
            "Recommend keeping CRITIC_MAX_REVISIONS=2 (current default)."
        )
    return (
        f"DISABLE V3: {delta:+.1f} pts (V3 underperforms V2). "
        "Set CRITIC_MAX_REVISIONS=1 immediately."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare V2 vs V3 revision quality")
    ap.add_argument("--all-personas", action="store_true",
                    help="Run on all 6 personas (default: 3 random)")
    ap.add_argument("--personas", type=int, default=3,
                    help="Number of random personas (when --all-personas not set)")
    ap.add_argument("--judge-model", default="claude-sonnet-4-20250514",
                    help="LLM-as-judge model — keep Sonnet to avoid writer=judge bias")
    ap.add_argument("--variance-pts", type=float, default=5.0,
                    help="Min absolute delta to consider conclusive")
    args = ap.parse_args()

    print("Sprint A/B — V2 (CRITIC_MAX_REVISIONS=1) vs V3 (=2).\n")
    v2 = _run_eval(1, args)
    v3 = _run_eval(2, args)

    print("\n=== Results ===")
    print(f"V2-only: overall_mean={v2.get('overall_mean', '?')}  cost=${v2.get('total_cost_usd', '?')}")
    print(f"V3:      overall_mean={v3.get('overall_mean', '?')}  cost=${v3.get('total_cost_usd', '?')}")
    print()
    print(_verdict(v2, v3, args.variance_pts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
