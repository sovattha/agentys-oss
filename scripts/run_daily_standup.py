# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Run the daily AI-team standup synchronously.

Bypasses the Redis queue + worker (issue #262 infra not deployed on Railway).
Invoked by launchd/cron at 08:00 UTC. Exits 0 on success, 1 on failure.

Flow:
  1. Aggregate yesterday's activity via `standup.build_daily_context()`.
  2. Invoke Claude (sonnet) with the `standup_prompts/system.md` system prompt
     via `claude_spawn.spawn()`.
  3. `standup.finalise_standup()` writes the MD file and builds the digest.
  4. If `should_send_digest` → push to Telegram via `telegram.send()`.

Dry-run (`--dry-run`): skips Claude call and Telegram, prints the aggregated
context to stdout. Useful to verify the pipeline without burning tokens.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Ensure repo root on sys.path so `import ai_team` works under launchd.
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from ai_team.lib import standup, telegram  # noqa: E402

log = logging.getLogger("daily_standup")

# Model IDs per CLAUDE.md + knowledge updates (2026-04):
# claude-sonnet-4-6 is current; legacy sonnet-4 still works. We default to the
# stable 2025-05-14 release since it's what the rest of the codebase uses
# (see app/config.py:CLAUDE_MODEL_FAST).
_DEFAULT_MODEL = os.environ.get("STANDUP_MODEL", "claude-sonnet-4-5")


def _call_anthropic_api(
    *, system_prompt: str, user_prompt: str, model: str, max_tokens: int
) -> tuple[str, int, int]:
    """Call Anthropic Messages API. Returns (text, tokens_in, tokens_out).

    Uses ANTHROPIC_API_KEY_NIGHTLY if set (per issue #262 spec — batch off-hours
    reporting), falls back to ANTHROPIC_API_KEY.
    """
    from anthropic import Anthropic  # local import — not needed for --dry-run

    api_key = (
        os.environ.get("ANTHROPIC_API_KEY_NIGHTLY")
        or os.environ.get("ANTHROPIC_API_KEY")
    )
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY_NIGHTLY or ANTHROPIC_API_KEY must be set"
        )
    client = Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = ""
    if resp.content and hasattr(resp.content[0], "text"):
        text = resp.content[0].text or ""
    return text, resp.usage.input_tokens, resp.usage.output_tokens

_PROMPTS_DIR = _REPO / "ai_team" / "agents" / "cron" / "standup_prompts"
_SYSTEM_PROMPT_PATH = _PROMPTS_DIR / "system.md"


def _load_system_prompt() -> str:
    return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def _fetch_github_issues_via_gh(owner: str, repo: str, date_iso: str) -> list[dict]:
    """Fetch issues updated on `date_iso` using `gh` CLI (bypasses Python SSL)."""
    gh = shutil.which("gh")
    if not gh:
        return []
    try:
        # Fetch updated yesterday — same filter as the urllib version.
        next_day = (datetime.fromisoformat(date_iso) + timedelta(days=1)).strftime("%Y-%m-%d")
        out = subprocess.run(
            [
                gh, "issue", "list",
                "--repo", f"{owner}/{repo}",
                "--state", "all",
                "--search", f"updated:{date_iso}..{next_day}",
                "--json", "number,title,labels,url",
                "--limit", "30",
            ],
            capture_output=True, text=True, timeout=15,
        )
        if out.returncode != 0:
            log.warning("gh issue list failed: %s", out.stderr[:200])
            return []
        items = json.loads(out.stdout or "[]")
    except Exception as e:  # noqa: BLE001
        log.warning("gh issue list exception: %s", e)
        return []

    results: list[dict] = []
    for it in items:
        labels = [
            (lbl.get("name") if isinstance(lbl, dict) else str(lbl)) or ""
            for lbl in it.get("labels", [])
        ]
        if not any(lbl.startswith("agent:") for lbl in labels):
            continue
        results.append({
            "number": it.get("number"),
            "title": it.get("title", ""),
            "labels": labels,
            "url": it.get("url", ""),
        })
    return results


def _resolve_github_env() -> tuple[str | None, str | None, str | None]:
    """Use env first, then fall back to `gh` CLI + `git remote` for local dev."""
    owner, repo, token = standup.default_github_env()
    if token and owner and repo:
        return owner, repo, token

    gh = shutil.which("gh")
    if gh and not token:
        try:
            out = subprocess.run(
                [gh, "auth", "token"], capture_output=True, text=True, timeout=5
            )
            if out.returncode == 0:
                token = out.stdout.strip() or None
        except Exception:
            pass

    if not (owner and repo):
        try:
            out = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=str(_REPO),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if out.returncode == 0:
                url = out.stdout.strip()
                # git@github.com:owner/repo.git OR https://github.com/owner/repo.git
                import re
                m = re.search(r"[:/]([\w.-]+)/([\w.-]+?)(\.git)?$", url)
                if m:
                    owner = owner or m.group(1)
                    repo = repo or m.group(2)
        except Exception:
            pass

    return owner, repo, token


def _send_digest_sync(digest: str) -> None:
    """Sync wrapper around the async `telegram.send()`."""
    asyncio.run(telegram.send(digest))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip Claude + Telegram, just print aggregated context",
    )
    parser.add_argument("--model", default=_DEFAULT_MODEL)
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=int(os.environ.get("STANDUP_MAX_OUTPUT_TOKENS", "3000")),
    )
    args = parser.parse_args()

    from ai_team.lib.logging_setup import configure_logging
    configure_logging()

    db_path = os.environ.get(
        "AGENTYS_AITEAM_DB",
        str(_REPO / "ai_team" / "data" / "ai_team.db"),
    )
    monthly_budget = float(os.environ.get("AI_TEAM_BUDGET_MONTHLY_USD", "200"))
    gh_owner, gh_repo, gh_token = _resolve_github_env()

    # urllib works on Linux (system CA bundle). If it fails (macOS system Python
    # SSL issue), we fall back to `gh` CLI below.
    ctx = standup.build_daily_context(
        db_path=db_path,
        monthly_budget_usd=monthly_budget,
        github_owner=gh_owner,
        github_repo=gh_repo,
        github_token=gh_token,
    )

    if not ctx.github_issues and gh_owner and gh_repo:
        issues = _fetch_github_issues_via_gh(gh_owner, gh_repo, ctx.date_iso)
        if issues:
            ctx = dataclasses.replace(ctx, github_issues=issues)

    context_block = ctx.to_prompt_context()

    log.info(
        "Built context: date=%s, %d actions, %.3f USD, budget=%s, %d agents, %d issues",
        ctx.date_iso,
        ctx.total_actions,
        ctx.total_cost_usd,
        ctx.budget_state,
        len(ctx.per_agent),
        len(ctx.github_issues),
    )

    if args.dry_run:
        print("=== AGGREGATED CONTEXT ===")
        print(context_block)
        return 0

    system_prompt = _load_system_prompt()
    log.info("Invoking Claude API (model=%s, max_tokens=%d)...", args.model, args.max_tokens)
    try:
        transcript, tokens_in, tokens_out = _call_anthropic_api(
            system_prompt=system_prompt,
            user_prompt=context_block,
            model=args.model,
            max_tokens=args.max_tokens,
        )
    except Exception as e:  # noqa: BLE001
        log.error("Anthropic API call failed: %s", e)
        return 1

    if not transcript:
        log.error("Empty response from Anthropic API")
        return 1

    # Sonnet 4 pricing: $3/Mtok input, $15/Mtok output
    cost_usd = (tokens_in / 1_000_000) * 3.0 + (tokens_out / 1_000_000) * 15.0
    log.info(
        "API OK: %d tokens_in, %d tokens_out, %.4f USD",
        tokens_in, tokens_out, cost_usd,
    )

    finalised = standup.finalise_standup(transcript=transcript, ctx=ctx)
    log.info(
        "Wrote standup MD: %s (%d remontées items)",
        finalised["path"],
        len(finalised["items"]),
    )

    if finalised["should_send_digest"] and finalised["digest"]:
        try:
            _send_digest_sync(finalised["digest"])
            log.info("Telegram digest sent")
        except Exception as e:  # noqa: BLE001 — log then continue
            log.error("Telegram send failed: %s", e)
    else:
        log.info("No ALERT/WARN item → skipped Telegram digest")

    return 0


if __name__ == "__main__":
    sys.exit(main())
