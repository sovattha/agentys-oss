#!/usr/bin/env python
"""Round 2 of the Haiku-4.5 cache investigation.

Round 1 (sequential test) showed Haiku 4.5 NEVER caches — input_tokens
reports the full prompt every time, cache_w and cache_r both stay at 0.
Sonnet 4 with the same prompt cached on call 3.

This script tests three hypotheses :

H1. SDK version too old to know about Haiku 4.5 caching.
    → check anthropic.__version__

H2. Haiku 4.5 needs the prompt-caching beta header.
    → add ``extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"}``
    and re-run.

H3. Caching is supported on a different Haiku version (3.5) but not 4.5.
    → run the same test on claude-3-5-haiku-20241022.

Cost : ~6-9 small calls, well under $0.05.
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


def _label_usage(prefix: str, u) -> None:
    in_tok = u.input_tokens
    cache_w = getattr(u, "cache_creation_input_tokens", 0) or 0
    cache_r = getattr(u, "cache_read_input_tokens", 0) or 0
    out_tok = u.output_tokens
    print(f"  {prefix}  in={in_tok}  cache_w={cache_w}  cache_r={cache_r}  out={out_tok}")


def run_test(client, model: str, prompt: str, label: str, *, beta_header: bool = False) -> None:
    print()
    print(f"=== {label} ===")
    if beta_header:
        print("  using anthropic-beta: prompt-caching-2024-07-31")
    for i in range(3):
        kwargs = dict(
            model=model,
            max_tokens=30,
            system=[{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": f"call {i + 1}"}],
        )
        if beta_header:
            kwargs["extra_headers"] = {"anthropic-beta": "prompt-caching-2024-07-31"}
        try:
            r = client.messages.create(**kwargs)
            _label_usage(f"Call {i + 1}/3", r.usage)
        except Exception as e:
            print(f"  Call {i + 1}/3 FAILED: {type(e).__name__}: {str(e)[:200]}")
        time.sleep(0.3)  # tiny pacing


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1

    print(f"H1 — Anthropic SDK version : {anthropic.__version__}")

    kb = (_REPO / "knowledge" / "memoire.md").read_text(encoding="utf-8")
    prompt = get_critic_structured_system_prompt(kb)
    print(f"Prompt length : {len(prompt)} chars")

    client = anthropic.Anthropic()

    # H2 : Haiku 4.5 with the prompt-caching beta header
    run_test(
        client,
        "claude-haiku-4-5-20251001",
        prompt,
        "H2 — Haiku 4.5 + prompt-caching beta header",
        beta_header=True,
    )

    # H3 : Haiku 3.5 (older, well-known to support caching)
    run_test(
        client,
        "claude-3-5-haiku-20241022",
        prompt,
        "H3 — Haiku 3.5 (control — older but caching-supported)",
    )

    # H4 (bonus) : Haiku 4.5 via .beta.messages — the dedicated beta endpoint
    print()
    print("=== H4 — Haiku 4.5 via client.beta.messages (different code path) ===")
    try:
        beta_client = anthropic.Anthropic()
        for i in range(3):
            r = beta_client.beta.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=30,
                system=[{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": f"call {i + 1}"}],
            )
            _label_usage(f"Call {i + 1}/3", r.usage)
            time.sleep(0.3)
    except Exception as e:
        print(f"  beta endpoint FAILED: {type(e).__name__}: {str(e)[:200]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
