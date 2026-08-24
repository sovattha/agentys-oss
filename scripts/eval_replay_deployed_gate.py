#!/usr/bin/env python
# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Replay the 2026-04-30 self-critique eval against the *deployed* gate rule.

The original eval (`scripts/eval_self_critique.py`) computes `would_escalate`
with a looser rule than what we deployed in `DraftOrchestrator`:

    Eval rule (loose) — escalate IF
        self_score < threshold OR a_count > 0
        OR any risk in {hallucination, placeholder, tone_mismatch}
        OR confidence == "low"

    Deployed gate rule (strict) — skip Critic IF ALL of
        self_score >= 85
        AND len(risks) == 0
        AND a_confirmer_count == 0
        AND confidence == "high"
        AND failure_reason == ""

This script does NOT make new API calls. It re-reads the per-case JSON of the
prior live eval and re-derives every metric using the strict deployed rule, so
we can answer the only question that matters today: would the gate as deployed
to prod produce safe skips on the 200-case dataset?
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


_INPUT = Path("tasks/eval-self-critique-live-2026-04-30.json")


def deployed_gate_skips(case: dict) -> bool:
    """Apply the *exact* rule from app.services.draft_orchestrator._gate_should_skip_critic."""
    if case.get("self_failure_reason"):
        return False
    if case["self_score"] < 85:
        return False
    if case["self_risks"]:
        return False
    if case["self_a_confirmer"] > 0:
        return False
    if case["self_confidence"] != "high":
        return False
    return True


def main() -> int:
    if not _INPUT.exists():
        print(f"missing {_INPUT}", file=sys.stderr)
        return 1
    payload = json.loads(_INPUT.read_text(encoding="utf-8"))
    cases = payload["results"]

    # Confusion-matrix axes — gate decision (skip vs escalate) crossed against
    # the Critic verdict on the SAME draft (valid vs reject). The cells we
    # care about most are:
    #   - skip_when_critic_reject : the gate would have shipped a draft the
    #                               external Critic flagged → would-be regression
    #   - skip_when_critic_valid  : the gate's productive skip — saved a call
    skip_valid = 0       # gate=skip, Critic=valid  → safe & cost saved
    skip_reject = 0      # gate=skip, Critic=reject → DANGER, false skip
    esc_valid = 0        # gate=escalate, Critic=valid → over-conservative
    esc_reject = 0       # gate=escalate, Critic=reject → caught a real reject
    no_critic = 0        # missing critic decision

    skip_by_category: Counter[str] = Counter()
    danger_examples: list[dict] = []

    for c in cases:
        critic = c.get("critic_decision", "")
        skip = deployed_gate_skips(c)
        if not critic:
            no_critic += 1
            continue
        if skip and critic == "valid":
            skip_valid += 1
            skip_by_category[c["category"]] += 1
        elif skip and critic == "reject":
            skip_reject += 1
            skip_by_category[c["category"]] += 1
            if len(danger_examples) < 10:
                danger_examples.append(c)
        elif not skip and critic == "valid":
            esc_valid += 1
        elif not skip and critic == "reject":
            esc_reject += 1

    n = skip_valid + skip_reject + esc_valid + esc_reject
    skip_total = skip_valid + skip_reject
    skip_rate = skip_total / n if n else 0.0

    # The two safety metrics the operator must look at before flipping to active.
    precision_when_skipping = (skip_valid / skip_total) if skip_total else None
    # "Skip-on-reject rate" — fraction of all REAL rejects that the gate
    # silently waved through. This is the regression rate we ship with.
    real_rejects = skip_reject + esc_reject
    skip_on_reject_rate = (skip_reject / real_rejects) if real_rejects else 0.0
    # "Useful skip rate" — fraction of Critic-valid cases the gate skipped.
    # Higher = more cost saved without changing the user-visible verdict.
    real_valids = skip_valid + esc_valid
    useful_skip_rate = (skip_valid / real_valids) if real_valids else 0.0

    print(f"Cases with both gate decision and Critic verdict: {n}")
    print(f"Cases missing critic decision: {no_critic}")
    print()
    print("Confusion matrix (rows = deployed gate, cols = Critic):")
    print("               | Critic VALID | Critic REJECT")
    print(f"  Gate SKIP    | {skip_valid:>12} | {skip_reject:>13}")
    print(f"  Gate ESCALATE| {esc_valid:>12} | {esc_reject:>13}")
    print()
    print(f"Skip rate (gate decides to skip Critic):  {skip_rate:.1%}  ({skip_total}/{n})")
    print(f"Precision when skipping (Critic VALID|skip): {precision_when_skipping:.1%}" if precision_when_skipping is not None else "Precision when skipping: n/a (no skips)")
    print(f"Useful skip rate (skipped|Critic-VALID):     {useful_skip_rate:.1%}  ({skip_valid}/{real_valids})")
    print(f"DANGER — Skip-on-reject rate (skipped|Critic-REJECT): {skip_on_reject_rate:.2%}  ({skip_reject}/{real_rejects})")
    print()
    print("Skip distribution by case category:")
    for cat, k in sorted(skip_by_category.items(), key=lambda x: -x[1]):
        print(f"  {cat:<18} {k}")
    if danger_examples:
        print()
        print("Examples where gate would skip but Critic rejected:")
        for d in danger_examples:
            print(f"  - {d['case_id']} ({d['category']}): self_score={d['self_score']}, "
                  f"risks={d['self_risks']}, conf={d['self_confidence']}, "
                  f"critic_score={d.get('critic_score', '?')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
