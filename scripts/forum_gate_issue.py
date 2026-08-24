# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""CLI gate for nightly auditors before they create a GitHub issue (#386 P1).

Used by `scripts/audit-e2e.sh` and `scripts/nightly-ux-inspection.sh`. Reads
a candidate issue from stdin (JSON: {title, body, scope?}), opens an in-process
forum with the configured personas (cf. ai_team/config/forum_peers.yaml), and
exits 0 (allowed) or 1 (blocked) so the bash caller can short-circuit
``gh issue create``.

Usage:
    echo '{"title":"...","body":"..."}' | python scripts/forum_gate_issue.py \\
        --invitee senior-dev \\
        --invitee qa \\
        --quorum 2 \\
        --convener nightly-auditor

Env vars:
    AGENTYS_DB_PATH       SQLite DB for ai_team_forums (audit log)
    FORUM_GATE_POLICY     'approve_only' (default) or 'lenient'
    FORUM_PEERS_YAML      Personas YAML (default: ai_team/config/forum_peers.yaml)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from ai_team.lib.forum import (
    EscalationPolicy,
    SqliteForumStore,
    gate_issue_creation,
)
from ai_team.lib.forum_llm_peer import (
    AnthropicHaikuClient,
    LlmPeerSender,
    load_personas,
)

log = logging.getLogger("forum_gate_issue")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


async def _run(args: argparse.Namespace) -> int:
    raw = sys.stdin.read()
    payload = json.loads(raw)
    title = payload["title"]
    body = payload.get("body", "")

    policy = EscalationPolicy(os.environ.get("FORUM_GATE_POLICY", "approve_only"))
    personas_path = Path(
        os.environ.get(
            "FORUM_PEERS_YAML",
            str(Path(__file__).resolve().parents[1] / "ai_team" / "config" / "forum_peers.yaml"),
        )
    )
    personas = load_personas(personas_path)
    sender = LlmPeerSender(client=AnthropicHaikuClient(), personas=personas)
    store = SqliteForumStore()
    decision = await gate_issue_creation(
        title=title, body=body,
        invitees=args.invitee, quorum=args.quorum,
        convener=args.convener, sender=sender, store=store,
        policy=policy,
    )

    log.info(
        "forum_id=%s outcome=%s allowed=%s",
        decision.forum_id, decision.outcome.value, decision.allowed,
    )
    print(json.dumps({
        "forum_id": decision.forum_id,
        "outcome": decision.outcome.value,
        "allowed": decision.allowed,
    }))
    return 0 if decision.allowed else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--invitee", action="append", required=True,
                        help="Persona name (cf. ai_team/config/forum_peers.yaml)")
    parser.add_argument("--quorum", type=int, default=2)
    parser.add_argument("--convener", default="nightly-auditor")
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
