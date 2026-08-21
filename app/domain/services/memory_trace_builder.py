# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Build a MemoryTrace snapshot from the current state of the knowledge base.

Called after draft generation to record what memory was available to the Drafter.
Issue #159 (Epic #134).
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def build_memory_trace(account_id: Optional[int] = None, contact_email: str = "") -> dict:
    """Build a MemoryTrace dict capturing what memory the Drafter could access.

    Args:
        account_id: Account to read from (DB-first, file fallback).
        contact_email: Contact email for per-contact rules lookup.

    Returns:
        Dict compatible with MemoryTrace.to_dict() format.
    """
    trace = {
        "profil": {},
        "style_default": {},
        "style_contact": None,
        "savoir": [],
        "rules": [],
    }

    try:
        from app.prompts.identity import _extract_user_identity, _load_kb

        # Profil
        identity = _extract_user_identity(account_id)
        trace["profil"] = {k: v for k, v in identity.items() if v}

        # Style defaults from WritingStyleStore
        try:
            from app.infrastructure.container import get_container
            container = get_container()
            aid = account_id or 1
            style_store = container.get_writing_style_store()
            profile = style_store.load(aid)
            if profile:
                # Audit S-08 (2026-05-11): filter unrendered template tokens
                # (`{first_name}`, `{civility}`, etc.) AND the
                # `(no closing or just name)` sentinel from both lists before
                # snapshotting. Without this, the Memory Trace UI panel
                # renders raw `Cordialement, {first_name}` or shows the
                # casual no-closing marker as if it were a real closing.
                # `_is_no_closing_marker` is the same helper used by
                # `_compute_closing_hint` (PR #634).
                def _sanitize_list(items):
                    if not items:
                        return []
                    try:
                        from app.prompts.identity import _is_no_closing_marker
                    except Exception:
                        _is_no_closing_marker = lambda _s: False  # noqa: E731
                    out = []
                    for s in items:
                        if not s:
                            continue
                        if "{" in s:
                            continue
                        if _is_no_closing_marker(s):
                            continue
                        out.append(s)
                        if len(out) >= 3:
                            break
                    return out

                trace["style_default"] = {
                    "formality_level": getattr(profile.formality_level, "value", str(profile.formality_level)) if profile.formality_level else None,
                    "preferred_greetings": _sanitize_list(profile.preferred_greetings),
                    "preferred_closings": _sanitize_list(profile.preferred_closings),
                }
                # Contact-specific style
                if contact_email and profile.contact_profiles:
                    cp = profile.contact_profiles.get(contact_email)
                    if cp:
                        trace["style_contact"] = {
                            "email": contact_email,
                            "formality_override": cp.get("formality_override"),
                        }
        except Exception:
            pass

        # Savoir entries from KB
        try:
            import re
            kb = _load_kb(account_id)
            savoir_match = re.search(r'## Savoir\n(.*?)(?=\n## |\Z)', kb, re.DOTALL)
            if savoir_match:
                for m in re.finditer(r'### (.+?)\n\n(.+?)(?=\n###|\Z)', savoir_match.group(1), re.DOTALL):
                    title = m.group(1).strip()
                    if title.startswith("Sujets fréquents"):
                        continue
                    category = "GENERAL"
                    if " : " in title:
                        parts = title.split(" : ", 1)
                        if parts[0] in ("FAQ", "TECHNIQUE", "CONTACT", "PROJET", "REGLE"):
                            category = parts[0]
                            title = parts[1]
                    trace["savoir"].append({
                        "id": f"savoir-{len(trace['savoir'])}",
                        "question": title,
                        "category": category,
                    })
        except Exception:
            pass

        # Learned rules
        try:
            from app.draft_learning import get_draft_learning_store
            store = get_draft_learning_store(account_id=account_id)
            rules_text = store.get_rules_for_prompt(contact=contact_email, limit=5)
            if rules_text:
                for line in rules_text.split("\n"):
                    line = line.strip().lstrip("- ").strip()
                    if line and not line.startswith("<") and not line.startswith("RÈGLE"):
                        trace["rules"].append({
                            "id": f"rule-{len(trace['rules'])}",
                            "rule_text": line[:200],
                        })
        except Exception:
            pass

    except Exception as e:
        logger.debug("Failed to build memory trace: %s", e)

    return trace
