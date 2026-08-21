#!/usr/bin/env python
"""Diagnose why Haiku Critic shows 0 % cache hit rate.

Audit 2026-05-04 (Tier 2 B) : the ground-truth analyzer reported
``cache_read_input_tokens=0`` on all 60 Haiku Critic calls despite the
prompt being 3510 tokens (well above Haiku's 2048 cache floor). Either
(a) parallel-4 worker racing on cache writes, (b) Haiku-specific SDK
behaviour, or (c) bug in our prompt setup.

Method : run 3 sequential calls with IDENTICAL system prompt for both
Haiku 4.5 (the prod Critic) and Sonnet 4 (positive control — we already
know it caches). Print raw usage on each call. Expected if caching works :

    Call 1 : in=N, cache_w=N, cache_r=0
    Call 2 : in=~0, cache_w=0, cache_r=N
    Call 3 : in=~0, cache_w=0, cache_r=N

Cost : ~6 cheap calls (max_tokens=50). Total under $0.03.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env")
except ImportError:
    pass

import anthropic
from app.prompts.builders import get_critic_structured_system_prompt


def run_sequential(client, model: str, label: str, prompt: str, n: int = 3) -> None:
    print()
    print(f"=== {label} ({model}) — {n} sequential calls ===")
    for i in range(n):
        t0 = time.time()
        r = client.messages.create(
            model=model,
            max_tokens=50,
            system=[{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": f"Sequential test call {i + 1}, just say ok"}],
        )
        elapsed_ms = int((time.time() - t0) * 1000)
        u = r.usage
        in_tok = u.input_tokens
        cache_w = getattr(u, "cache_creation_input_tokens", 0) or 0
        cache_r = getattr(u, "cache_read_input_tokens", 0) or 0
        out_tok = u.output_tokens
        denom = in_tok + cache_w + cache_r
        hit_rate = (cache_r / denom) if denom else 0.0
        print(
            f"  Call {i + 1}/{n}  ({elapsed_ms} ms)  "
            f"in={in_tok}  cache_w={cache_w}  cache_r={cache_r}  out={out_tok}  "
            f"hit_rate={hit_rate:.1%}"
        )


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1

    kb = (_REPO / "knowledge" / "memoire.md").read_text(encoding="utf-8")
    prompt = get_critic_structured_system_prompt(kb)
    print(f"Prompt length: {len(prompt)} chars")

    # Confirm token count for both models — Haiku has a 2048 floor, Sonnet 1024.
    client = anthropic.Anthropic()
    for model in ("claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"):
        ct = client.messages.count_tokens(
            model=model,
            system=prompt,
            messages=[{"role": "user", "content": "x"}],
        )
        floor = 2048 if "haiku" in model else 1024
        print(f"  {model}: {ct.input_tokens} tokens — cacheable(>={floor})? {ct.input_tokens >= floor}")

    # Sonnet : positive control. We expect cache_w on call 1, cache_r on calls 2-3.
    run_sequential(client, "claude-sonnet-4-20250514", "POSITIVE CONTROL — Sonnet 4", prompt)

    # Haiku : the suspect. Same code path, same prompt.
    run_sequential(client, "claude-haiku-4-5-20251001", "SUSPECT — Haiku 4.5", prompt)

    print()
    print("Verdict :")
    print("  - If Haiku cache_r > 0 on call 2-3 → caching works ; the analyzer's")
    print("    parallel-4 was racing on cache writes. Fix : run analyzer with --parallel 1")
    print("    once to prime the cache, then increase concurrency.")
    print("  - If Haiku cache_r = 0 on call 2-3 → genuine model/SDK behaviour. Dig deeper.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
