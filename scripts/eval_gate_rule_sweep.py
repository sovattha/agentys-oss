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

"""Sweep multiple gate-rule variants against the 200-case eval JSON.

Audit 2026-05-04 (Tier B #4) : the deployed gate
(``self_score>=85 AND risks==() AND a_confirmer_count==0 AND confidence=='high'``)
skips only 5 % of drafts on the synthetic eval — most of the latency win the
runbook promised is left on the table because the rule is very strict on two
near-noise dimensions (``confidence=='high'`` and ``len(risks)==0`` even for
benign categories like ``filler``).

This script replays the existing 2026-04-30 eval through several candidate
rules, joins each gate decision with the cached external Critic verdict on
the same draft, and produces a precision/recall/safety table per variant.

No new API calls : the SelfCritique fields (``self_score``, ``self_risks``,
``self_a_confirmer``, ``self_confidence``) and the cached ``critic_decision``
already live in the input JSON. The only thing that varies between variants
is the boolean rule applied at replay time.

Variants explored (chosen because each isolates ONE relaxation knob, so the
table reads as an ablation rather than a one-shot sweep):

    R1 STRICT          : current deployed rule — baseline
    R2 SCORE_75        : score>=75, otherwise = R1
    R3 CONF_MED        : confidence in {high, med}, otherwise = R1
    R4 FILLER_OK       : risks ⊆ {filler}, otherwise = R1
    R5 CONF_MED+FILLER : R3 + R4 — moderate combined relaxation
    R6 ALL_LOOSE       : R2 + R3 + R4 — aggressive, expected highest skip rate

Output : a markdown table to stdout + a JSON artifact for diff/audit.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_INPUT = Path("tasks/eval-self-critique-live-2026-04-30.json")
_OUTPUT_JSON = Path("tasks/eval-gate-rule-sweep-2026-05-04.json")
_OUTPUT_MD = Path("tasks/eval-gate-rule-sweep-2026-05-04.md")


# ---------------------------------------------------------------------------
# Rule variants — each takes a case dict, returns True if the gate skips.
# Common precondition (failed SelfCritique → never skip) factored out below.
# ---------------------------------------------------------------------------

def _common_block(c: dict) -> bool:
    """Shared pre-conditions any rule must respect (fail-safe)."""
    return bool(c.get("self_failure_reason"))


def r1_strict(c: dict) -> bool:
    if _common_block(c):
        return False
    if c["self_score"] < 85:
        return False
    if c["self_risks"]:
        return False
    if c["self_a_confirmer"] > 0:
        return False
    if c["self_confidence"] != "high":
        return False
    return True


def r2_score_75(c: dict) -> bool:
    if _common_block(c):
        return False
    if c["self_score"] < 75:
        return False
    if c["self_risks"]:
        return False
    if c["self_a_confirmer"] > 0:
        return False
    if c["self_confidence"] != "high":
        return False
    return True


def r3_conf_med(c: dict) -> bool:
    if _common_block(c):
        return False
    if c["self_score"] < 85:
        return False
    if c["self_risks"]:
        return False
    if c["self_a_confirmer"] > 0:
        return False
    if c["self_confidence"] not in ("high", "med"):
        return False
    return True


def r4_filler_ok(c: dict) -> bool:
    if _common_block(c):
        return False
    if c["self_score"] < 85:
        return False
    # Tolerate `filler` (least dangerous risk : verbosity, not factuality);
    # block all other categories.
    if any(r != "filler" for r in c["self_risks"]):
        return False
    if c["self_a_confirmer"] > 0:
        return False
    if c["self_confidence"] != "high":
        return False
    return True


def r5_conf_med_filler(c: dict) -> bool:
    if _common_block(c):
        return False
    if c["self_score"] < 85:
        return False
    if any(r != "filler" for r in c["self_risks"]):
        return False
    if c["self_a_confirmer"] > 0:
        return False
    if c["self_confidence"] not in ("high", "med"):
        return False
    return True


def r6_all_loose(c: dict) -> bool:
    if _common_block(c):
        return False
    if c["self_score"] < 75:
        return False
    if any(r != "filler" for r in c["self_risks"]):
        return False
    if c["self_a_confirmer"] > 0:
        return False
    if c["self_confidence"] not in ("high", "med"):
        return False
    return True


_RULES: list[tuple[str, Callable[[dict], bool], str]] = [
    ("R1_STRICT",          r1_strict,          "score>=85, risks=∅, a_confirmer=0, conf=high (DEPLOYED)"),
    ("R2_SCORE_75",        r2_score_75,        "R1 with score>=75 instead of 85"),
    ("R3_CONF_MED",        r3_conf_med,        "R1 with conf ∈ {high, med}"),
    ("R4_FILLER_OK",       r4_filler_ok,       "R1 tolerating risks ⊆ {filler}"),
    ("R5_CONF_MED+FILLER", r5_conf_med_filler, "R3 + R4 combined"),
    ("R6_ALL_LOOSE",       r6_all_loose,       "R2 + R3 + R4 (aggressive)"),
]


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

@dataclass
class RuleStats:
    name: str
    description: str
    n: int
    skip_total: int
    skip_when_critic_valid: int   # productive skip
    skip_when_critic_reject: int  # DANGER — gate let through a Critic-rejected draft
    escalate_when_critic_valid: int
    escalate_when_critic_reject: int
    skip_breakdown_by_category: dict
    danger_breakdown_by_category: dict
    danger_examples: list

    @property
    def skip_rate(self) -> float:
        return self.skip_total / self.n if self.n else 0.0

    @property
    def precision_when_skipping(self) -> float:
        return (self.skip_when_critic_valid / self.skip_total) if self.skip_total else 0.0

    @property
    def useful_skip_rate(self) -> float:
        valids = self.skip_when_critic_valid + self.escalate_when_critic_valid
        return (self.skip_when_critic_valid / valids) if valids else 0.0

    @property
    def skip_on_reject_rate(self) -> float:
        rejects = self.skip_when_critic_reject + self.escalate_when_critic_reject
        return (self.skip_when_critic_reject / rejects) if rejects else 0.0


def evaluate_rule(name: str, fn, description: str, cases: list) -> RuleStats:
    skip_v = skip_r = esc_v = esc_r = 0
    skip_cat: Counter[str] = Counter()
    danger_cat: Counter[str] = Counter()
    danger_examples: list = []

    for c in cases:
        critic = c.get("critic_decision", "")
        if not critic:
            continue
        skip = fn(c)
        cat = c.get("category", "?")
        if skip:
            skip_cat[cat] += 1
            if critic == "valid":
                skip_v += 1
            else:
                skip_r += 1
                danger_cat[cat] += 1
                if len(danger_examples) < 12:
                    danger_examples.append({
                        "case_id": c["case_id"],
                        "category": cat,
                        "self_score": c["self_score"],
                        "self_risks": c["self_risks"],
                        "self_confidence": c["self_confidence"],
                        "critic_score": c.get("critic_score", -1),
                    })
        else:
            if critic == "valid":
                esc_v += 1
            else:
                esc_r += 1

    n = skip_v + skip_r + esc_v + esc_r
    return RuleStats(
        name=name,
        description=description,
        n=n,
        skip_total=skip_v + skip_r,
        skip_when_critic_valid=skip_v,
        skip_when_critic_reject=skip_r,
        escalate_when_critic_valid=esc_v,
        escalate_when_critic_reject=esc_r,
        skip_breakdown_by_category=dict(skip_cat),
        danger_breakdown_by_category=dict(danger_cat),
        danger_examples=danger_examples,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def render_md(stats_list: list[RuleStats]) -> str:
    lines = [
        "# Gate rule sweep — 2026-05-04",
        "",
        "Replay of 6 candidate gate rules against the 200-case "
        "`tasks/eval-self-critique-live-2026-04-30.json` eval. **No new API "
        "calls** — every variant applies a different boolean rule to the "
        "cached SelfCritique outputs and joins with the cached Critic verdict "
        "(treated as ground truth proxy, with the documented 34 % FP caveat).",
        "",
        "## Trade-off table",
        "",
        "| Rule | Skip rate | Useful skip / Critic-VALID | DANGER (skip-on-reject) | "
        "Skip categories | Description |",
        "|---|---|---|---|---|---|",
    ]
    for s in stats_list:
        skip_cats = ", ".join(f"{k}:{v}" for k, v in sorted(s.skip_breakdown_by_category.items()))
        if not skip_cats:
            skip_cats = "—"
        lines.append(
            f"| **{s.name}** | {s.skip_rate:.1%} ({s.skip_total}/{s.n}) | "
            f"{s.useful_skip_rate:.1%} ({s.skip_when_critic_valid}/"
            f"{s.skip_when_critic_valid + s.escalate_when_critic_valid}) | "
            f"{s.skip_on_reject_rate:.2%} ({s.skip_when_critic_reject}/"
            f"{s.skip_when_critic_reject + s.escalate_when_critic_reject}) | "
            f"{skip_cats} | {s.description} |"
        )

    lines += [
        "",
        "## DANGER cell — drafts the gate would skip but Critic rejected",
        "",
        "Per the 2026-04-30 verdict, Critic on Haiku had a documented 34 % FP "
        "rate on `good` drafts. So *some* skip-on-reject cases are actually "
        "the gate correctly bypassing a Critic false positive. The bad case "
        "is when a danger-cell entry comes from `hallucination`, "
        "`placeholder`, `tone_mismatch`, `off_topic`, or any non-`good` "
        "category — that means the gate would have shipped a genuinely bad "
        "draft.",
        "",
        "| Rule | Total danger cells | Of which `good` (likely Critic FP) | Of which truly risky |",
        "|---|---|---|---|",
    ]
    for s in stats_list:
        good_n = s.danger_breakdown_by_category.get("good", 0)
        risky_n = sum(v for k, v in s.danger_breakdown_by_category.items() if k != "good")
        lines.append(
            f"| **{s.name}** | {s.skip_when_critic_reject} | {good_n} | "
            f"**{risky_n}** {'⚠️' if risky_n > 0 else '✓'} |"
        )

    lines += [
        "",
        "## How to read this",
        "",
        "- **Skip rate** : higher = more drafts bypass the Critic. The runbook's "
        "  active-mode latency win scales linearly with this.",
        "- **Useful skip / Critic-VALID** : of all drafts the Critic would "
        "  validate, what fraction does the gate (correctly) bypass. Higher = "
        "  more cost saved without changing outcomes.",
        "- **DANGER (skip-on-reject)** : of all drafts the Critic would reject, "
        "  what fraction does the gate let through. Lower = safer. **The "
        "  category breakdown matters more than the raw rate** — a 5 % danger "
        "  rate concentrated entirely on `good` drafts (= Critic false "
        "  positives) is fine; a 1 % danger rate on `hallucination` is not.",
        "",
        "## Recommendation logic",
        "",
        "- Pick the rule with the **highest skip rate** for which the danger "
        "  cell shows **zero non-`good` entries** (column 4 = 0 in the danger "
        "  table). That's the most permissive rule that's still safe by this "
        "  dataset.",
        "- Confirm by re-running the live eval at that rule "
        "  (`scripts/eval_self_critique.py --threshold 75 --live "
        "  --include-critic`) before flipping the deployed rule.",
        "- Update the conjunctive checks in "
        "  `app/services/draft_orchestrator.py:_gate_should_skip_critic` and "
        "  the gate-test fixture in "
        "  `tests/services/test_draft_orchestrator_self_critique_gate.py` "
        "  in the same commit.",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    if not _INPUT.exists():
        print(f"missing {_INPUT}", file=sys.stderr)
        return 1
    payload = json.loads(_INPUT.read_text(encoding="utf-8"))
    cases = payload["results"]

    stats = [evaluate_rule(name, fn, desc, cases) for name, fn, desc in _RULES]

    # Console summary
    print(f"{'Rule':<22} {'Skip':>10} {'Useful':>10} {'Danger':>10}  Skip categories")
    print("-" * 90)
    for s in stats:
        skip_cats = ",".join(f"{k}={v}" for k, v in sorted(s.skip_breakdown_by_category.items()))
        print(
            f"{s.name:<22} {s.skip_rate:>9.1%} {s.useful_skip_rate:>9.1%} "
            f"{s.skip_on_reject_rate:>9.2%}  {skip_cats}"
        )

    # JSON artifact
    _OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_JSON.write_text(json.dumps([
        {
            "name": s.name,
            "description": s.description,
            "n": s.n,
            "skip_total": s.skip_total,
            "skip_when_critic_valid": s.skip_when_critic_valid,
            "skip_when_critic_reject": s.skip_when_critic_reject,
            "escalate_when_critic_valid": s.escalate_when_critic_valid,
            "escalate_when_critic_reject": s.escalate_when_critic_reject,
            "skip_rate": round(s.skip_rate, 4),
            "useful_skip_rate": round(s.useful_skip_rate, 4),
            "skip_on_reject_rate": round(s.skip_on_reject_rate, 4),
            "skip_by_category": s.skip_breakdown_by_category,
            "danger_by_category": s.danger_breakdown_by_category,
            "danger_examples": s.danger_examples,
        }
        for s in stats
    ], indent=2, ensure_ascii=False), encoding="utf-8")

    # Markdown report
    _OUTPUT_MD.write_text(render_md(stats), encoding="utf-8")
    print()
    print(f"[ok] wrote {_OUTPUT_JSON}")
    print(f"[ok] wrote {_OUTPUT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
