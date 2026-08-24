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

"""Compare CriticAgent on Sonnet 4 vs Haiku 4.5 over the same drafts.

Question this script answers : if we swap the prod Critic model from
``claude-sonnet-4-20250514`` (current) to ``claude-haiku-4-5-20251001``, do
the VALID/REJECT decisions change? If agreement >= 90 %, Haiku is a safe
drop-in (3x cheaper). If < 80 %, Sonnet's nuance is buying us something and
we keep it.

Approach :
- Reuse the existing 200-case eval dataset (`scripts/eval_dataset.py`).
- Build the *same* structured Critic system+user prompts the prod
  CriticAgent uses (`app.prompts.builders`).
- Hit Anthropic directly with each model via two independent adapters.
- Parse the JSON response with the same parser the prod path uses
  (`extract_json_from_response`).
- Aggregate : decision agreement, score correlation, cost, latency.

Cost (50 cases, both models, ~700 input + ~120 output tokens per call):
- Sonnet : ~$0.20
- Haiku  : ~$0.07
- Total  : ~$0.27

Caveats :
- Cache effects are NOT measured here — both models call cold cache. A real
  prod comparison would also factor in Sonnet's much lower cost-on-cache-hit
  if shadow telemetry confirms a high hit rate (separate audit).
- We use account_id=None so no learned-rules block is injected (keeps the
  comparison clean of per-account drift).
- Both adapters use the same `cache_control: ephemeral` annotation as prod,
  but with 50 unique drafts in 50 unique system-prompt prefixes (KB stays
  fixed but the test runner is the only writer in the cache window) we
  expect minimal cache reuse anyway.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "scripts"))

# Load .env so ANTHROPIC_API_KEY is available even when not exported in the shell.
try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env")
except ImportError:
    pass

import anthropic  # noqa: E402

from eval_dataset import ALL_CASES, EvalCase  # noqa: E402
from app.prompts.builders import (  # noqa: E402
    get_critic_structured_system_prompt,
    get_critic_structured_user_prompt,
)
from app.utils.json_parser import extract_json_from_response  # noqa: E402

# Pricing in USD per 1M tokens (4.x family, May 2026 list price).
_PRICING = {
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00,
                                  "cache_write": 3.75, "cache_read": 0.30},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00,
                                   "cache_write": 1.25, "cache_read": 0.10},
}

_MODEL_SONNET = "claude-sonnet-4-20250514"
_MODEL_HAIKU = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 600  # CriticAgent in prod uses 120 but the structured rubric
                   # JSON is ~250-400 tokens with all 7 scores + suggestions;
                   # 600 leaves headroom so we don't truncate the comparison.


@dataclass
class CallResult:
    model: str
    decision: str            # "valid" | "reject" | "parse_failed"
    overall: int             # 0-100, computed as mean of 7 scores
    scores: dict             # {coherence, tone, completeness, errors, ...}
    suggestions: list        # list[str]
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    cost_usd: float
    raw_excerpt: str = ""    # first 200 chars of raw response for debugging


@dataclass
class CaseEval:
    case_id: str
    category: str
    sonnet: CallResult | None = None
    haiku: CallResult | None = None
    agreement: bool = False  # decisions match
    overall_delta: int = 0   # |sonnet.overall - haiku.overall|
    error: str = ""


def _cost(model: str, usage) -> float:
    p = _PRICING[model]
    # Anthropic separates cache reads (cheap) from regular input (expensive).
    in_tokens = usage.input_tokens
    out_tokens = usage.output_tokens
    cache_w = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_r = getattr(usage, "cache_read_input_tokens", 0) or 0
    return (
        in_tokens * p["input"] / 1_000_000
        + out_tokens * p["output"] / 1_000_000
        + cache_w * p["cache_write"] / 1_000_000
        + cache_r * p["cache_read"] / 1_000_000
    )


def _parse_critique(raw: str) -> tuple[str, int, dict, list]:
    """Mirror of CriticAgent._parse_critique_response (essential subset).

    Returns (decision, overall_0_100, scores_dict, suggestions).
    """
    data = extract_json_from_response(raw)
    if not data:
        return "parse_failed", 0, {}, []
    score_keys = ("coherence", "tone", "completeness", "errors",
                  "conciseness", "over_commitment", "emotional_intelligence")
    scores = {}
    for k in score_keys:
        v = data.get(k, 50)
        try:
            scores[k] = max(0, min(100, int(v)))
        except (TypeError, ValueError):
            scores[k] = 50
    overall = sum(scores.values()) // len(scores)
    decision = (data.get("decision") or "").lower()
    if decision not in ("valid", "reject"):
        # Mirror prod fallback : score-based decision.
        decision = "valid" if overall >= 70 else "reject"
    suggestions = data.get("suggestions") or []
    if not isinstance(suggestions, list):
        suggestions = []
    return decision, overall, scores, suggestions


def _run_one_call(client: anthropic.Anthropic, model: str, system: str, user: str) -> CallResult:
    t0 = time.time()
    response = client.messages.create(
        model=model,
        max_tokens=_MAX_TOKENS,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
    )
    latency_ms = int((time.time() - t0) * 1000)
    raw = response.content[0].text if response.content else ""
    decision, overall, scores, suggestions = _parse_critique(raw)
    return CallResult(
        model=model,
        decision=decision,
        overall=overall,
        scores=scores,
        suggestions=suggestions,
        latency_ms=latency_ms,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cache_creation_input_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
        cache_read_input_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        cost_usd=_cost(model, response.usage),
        raw_excerpt=raw[:200],
    )


def _evaluate_case(client: anthropic.Anthropic, case: EvalCase, kb: str) -> CaseEval:
    system_prompt = get_critic_structured_system_prompt(kb, contact="", account_id=None)
    user_prompt = get_critic_structured_user_prompt(
        email_content=case.email_in,
        draft=case.draft_v1,
        context=None,
        threshold=70,
    )

    out = CaseEval(case_id=case.case_id, category=case.category)
    try:
        out.sonnet = _run_one_call(client, _MODEL_SONNET, system_prompt, user_prompt)
        out.haiku = _run_one_call(client, _MODEL_HAIKU, system_prompt, user_prompt)
        out.agreement = (out.sonnet.decision == out.haiku.decision)
        out.overall_delta = abs(out.sonnet.overall - out.haiku.overall)
    except Exception as e:
        out.error = f"{type(e).__name__}: {e}"
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=50, help="Number of cases (default 50)")
    parser.add_argument("--parallel", type=int, default=4)
    parser.add_argument("--out", type=Path,
                        default=_REPO / "tasks" / "eval-critic-haiku-vs-sonnet-2026-05-04.json")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("missing ANTHROPIC_API_KEY (and not picked up from .env)", file=sys.stderr)
        return 1

    kb = (_REPO / "knowledge" / "memoire.md").read_text(encoding="utf-8")
    cases = ALL_CASES[:args.n]
    print(f"[start] {len(cases)} cases, parallel={args.parallel}", file=sys.stderr)

    client = anthropic.Anthropic()
    results: list[CaseEval] = []
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futures = {ex.submit(_evaluate_case, client, c, kb): c for c in cases}
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            done = len(results)
            if done % 5 == 0 or done == len(cases):
                err_n = sum(1 for x in results if x.error)
                print(f"  {done}/{len(cases)} done, errors={err_n}, "
                      f"elapsed={time.time()-t_start:.0f}s",
                      file=sys.stderr)

    # Aggregates
    successful = [r for r in results if r.sonnet and r.haiku and not r.error]
    n = len(successful)
    if n == 0:
        print("no successful comparisons", file=sys.stderr)
        return 1

    agreed = sum(1 for r in successful if r.agreement)
    sonnet_valid = sum(1 for r in successful if r.sonnet.decision == "valid")
    haiku_valid = sum(1 for r in successful if r.haiku.decision == "valid")
    sonnet_reject = sum(1 for r in successful if r.sonnet.decision == "reject")
    haiku_reject = sum(1 for r in successful if r.haiku.decision == "reject")

    deltas = [r.overall_delta for r in successful]
    sonnet_costs = [r.sonnet.cost_usd for r in successful]
    haiku_costs = [r.haiku.cost_usd for r in successful]
    sonnet_lat = [r.sonnet.latency_ms for r in successful]
    haiku_lat = [r.haiku.latency_ms for r in successful]

    # Confusion matrix on the binary decision.
    matrix = {("valid", "valid"): 0, ("valid", "reject"): 0,
              ("reject", "valid"): 0, ("reject", "reject"): 0}
    for r in successful:
        matrix[(r.sonnet.decision, r.haiku.decision)] += 1

    summary = {
        "n_total": len(results),
        "n_successful": n,
        "agreement_rate": round(agreed / n, 4),
        "sonnet_valid_rate": round(sonnet_valid / n, 4),
        "haiku_valid_rate": round(haiku_valid / n, 4),
        "sonnet_reject_rate": round(sonnet_reject / n, 4),
        "haiku_reject_rate": round(haiku_reject / n, 4),
        "overall_delta_mean": round(statistics.mean(deltas), 1),
        "overall_delta_p95": round(_pct(deltas, 95), 1),
        "cost_total_sonnet_usd": round(sum(sonnet_costs), 4),
        "cost_total_haiku_usd": round(sum(haiku_costs), 4),
        "cost_per_call_sonnet_usd": round(statistics.mean(sonnet_costs), 6),
        "cost_per_call_haiku_usd": round(statistics.mean(haiku_costs), 6),
        "cost_ratio_sonnet_over_haiku": round(sum(sonnet_costs) / sum(haiku_costs), 2)
            if sum(haiku_costs) else None,
        "latency_p50_sonnet_ms": int(statistics.median(sonnet_lat)),
        "latency_p50_haiku_ms": int(statistics.median(haiku_lat)),
        "latency_p95_sonnet_ms": int(_pct(sonnet_lat, 95)),
        "latency_p95_haiku_ms": int(_pct(haiku_lat, 95)),
        "confusion_matrix": {
            "sonnet_valid_haiku_valid": matrix[("valid", "valid")],
            "sonnet_valid_haiku_reject": matrix[("valid", "reject")],
            "sonnet_reject_haiku_valid": matrix[("reject", "valid")],
            "sonnet_reject_haiku_reject": matrix[("reject", "reject")],
        },
        "wall_time_s": round(time.time() - t_start, 1),
    }

    payload = {"summary": summary, "results": [asdict(r) for r in results]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(json.dumps(summary, indent=2), file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"[ok] wrote {args.out}", file=sys.stderr)
    return 0


def _pct(values, p):
    s = sorted(values)
    if not s:
        return 0
    k = (len(s) - 1) * (p / 100)
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (k - lo)


if __name__ == "__main__":
    sys.exit(main())
