# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit fix H-8 (issue #534) — rate-limit global = paid-API DoS cross-tenant.

Bug: trois endpoints qui font des appels Anthropic facturés utilisaient une
clé de bucket LITTÉRALE pour `_rate_limited`, mutualisant le quota entre tous
les users authentifiés :

  * `routes_misc.py:2618` — `_rate_limited("voice_draft", 10/min)`
  * `routes_misc.py:2891` — `_rate_limited("voice_parse", 30/min)`
  * `routes_emails.py:3732` — `_rate_limited("generate", 10/min)`

Conséquence : un user A consomme les N req/min → tous les autres users
prennent 429. Pas de cap $ par-tenant. Un attaquant peut hammer ces endpoints
jusqu'au cap global et drainer le crédit Anthropic du compte.

Fix : aligner sur la convention déjà utilisée par les sibling endpoints
(`voice_intent`, `transcribe`, `tts_clone`) qui keyent leur bucket via
`f"<bucket>:{_aid}"`. Chaque tenant a son propre quota indépendant.

Run: `pytest tests/audit_fixes/test_h_08_rate_limit_per_tenant.py -v`
"""

from __future__ import annotations

import inspect

import pytest

pytest.importorskip("flask_cors")


# --------------------------------------------------------------------------- #
# Source-level assertions — lock the fix in place against future refactors.
# Mirrors `test_c_03_push_broadcast_admin_only::test_broadcast_source_has_require_admin_decorator`.
# --------------------------------------------------------------------------- #


def _grep_callsite(module_src: str, view_name: str) -> str:
    """Return the body slice between `def <view_name>` and the next `def`,
    so per-callsite assertions don't bleed into the wrong handler."""
    start = module_src.find(f"def {view_name}(")
    assert start > 0, f"{view_name} not found in module source"
    next_def = module_src.find("\ndef ", start + 1)
    if next_def < 0:
        next_def = len(module_src)
    return module_src[start:next_def]


def test_voice_draft_rate_limit_is_per_tenant():
    """`POST /emails/<id>/voice-draft` → bucket key MUST include `:_aid`."""
    from app.api import routes_misc

    src = inspect.getsource(routes_misc)
    body = _grep_callsite(src, "create_voice_draft")

    assert '_rate_limited("voice_draft"' not in body, (
        "H-8 regression: voice_draft uses a LITERAL bucket key — paid Anthropic "
        "calls are now mutualisés cross-tenant. Use f\"voice_draft:{_aid}\"."
    )
    assert 'f"voice_draft:{_aid}"' in body or "f'voice_draft:{_aid}'" in body, (
        "voice_draft rate limit must be keyed per-tenant (`f\"voice_draft:{_aid}\"`)."
    )


def test_voice_parse_rate_limit_is_per_tenant():
    """`/voice/parse-compose` → per-tenant bucket."""
    from app.api import routes_misc

    src = inspect.getsource(routes_misc)
    body = _grep_callsite(src, "parse_compose_utterance")

    assert '_rate_limited("voice_parse"' not in body, (
        "H-8 regression: voice_parse uses a LITERAL bucket key — Anthropic "
        "Haiku calls now share the 30 req/min quota cross-tenant. "
        'Use f"voice_parse:{_aid}".'
    )
    assert 'f"voice_parse:{_aid}"' in body or "f'voice_parse:{_aid}'" in body, (
        "voice_parse rate limit must be keyed per-tenant."
    )


def test_generate_rate_limit_is_per_tenant():
    """`/generate` (drafts preview) → per-tenant bucket."""
    from app.api import routes_emails

    src = inspect.getsource(routes_emails)
    body = _grep_callsite(src, "generate_preview")

    assert '_rate_limited("generate"' not in body, (
        "H-8 regression: /generate uses a LITERAL bucket key — Claude draft "
        'previews now share the 10 req/min quota cross-tenant. '
        'Use f"generate:{_aid}".'
    )
    assert 'f"generate:{_aid}"' in body or "f'generate:{_aid}'" in body, (
        "/generate rate limit must be keyed per-tenant."
    )


# --------------------------------------------------------------------------- #
# 2026-05-05 audit follow-up — `#534 explicitly listed 9 remaining sites as
# `Hors scope`. They are now per-tenant; this parametrized matrix locks them
# in so a future cleanup can't accidentally regress to literal keys.
# --------------------------------------------------------------------------- #


# (module path, view fn name, bucket prefix string)
_PER_TENANT_RATE_LIMITS = [
    # --- routes_emails.py --- (process LLM drafts, send_new_email, send_draft) ---
    ("app.api.routes_emails",     "process_email",          "process"),
    ("app.api.routes_emails",     "send_new_email",         "send_email"),
    ("app.api.routes_emails",     "send_draft",             "send_email"),
    # --- routes_drafts.py --- (refine_text both modes) ---
    ("app.api.routes_drafts",     "refine_text",            "refine_text"),
    ("app.api.routes_drafts",     "refine_text",            "refine_text_expert"),
    # --- scheduled_emails.py --- (create / cancel / patch) ---
    ("app.api.scheduled_emails",  "create_scheduled_email", "schedule_email"),
    ("app.api.scheduled_emails",  "cancel_scheduled_email", "schedule_cancel"),
    ("app.api.scheduled_emails",  "patch_scheduled_email",  "schedule_patch"),
    # --- account_actions.py / knowledge.py --- (one-shot mutations) ---
    # NOTE (2026-05-30): refunds.py supprimé avec la feature Stripe/refund —
    # le cas confirm_refund est retiré de la matrice.
    ("app.api.account_actions",   "confirm_account_action", "account_confirm"),
    ("app.api.knowledge",         "scan_document",          "knowledge_scan_document"),
]


@pytest.mark.parametrize("module_path,fn_name,bucket", _PER_TENANT_RATE_LIMITS,
                         ids=[f"{m.rsplit('.', 1)[-1]}::{f}::{b}"
                              for m, f, b in _PER_TENANT_RATE_LIMITS])
def test_remaining_rate_limits_are_per_tenant(module_path, fn_name, bucket):
    """For each formerly-literal bucket, the handler body MUST contain the
    per-tenant `f"<bucket>:{_aid}"` form and MUST NOT contain the literal
    `_rate_limited("<bucket>"` form.

    Source-level grep is used (not behavioural integration) because:
      1. These handlers all stack auth/ownership checks before the rate
         limiter, so a 200/403 round-trip wouldn't isolate the bucket key.
      2. The fix shape is purely textual — the regression mode is a future
         contributor copy-pasting the literal style back. A grep test
         catches that on the very next CI run.
    """
    import importlib

    module = importlib.import_module(module_path)
    src = inspect.getsource(module)
    body = _grep_callsite(src, fn_name)

    literal_form = f'_rate_limited("{bucket}"'
    per_tenant_inline = f'f"{bucket}:{{_aid}}"'
    # Audit F-03 (2026-05-16) hardening: `_per_caller_bucket_key("<bucket>")`
    # is the canonical helper-form. It produces `"<bucket>:<aid>"` when an
    # account id is resolvable, and `"<bucket>:jwt:<email>"` for pre-OAuth
    # users — strictly safer than the bare f-string form which collapsed
    # all `_NO_ACCOUNT_SENTINEL` (-1) callers into one shared bucket.
    per_tenant_helper = f'_per_caller_bucket_key("{bucket}"'

    assert literal_form not in body, (
        f"H-8 follow-up regression in {module_path}:{fn_name} — "
        f"`{literal_form}` is a cross-tenant DoS vector. Replace with "
        f"`_rate_limited({per_tenant_inline}, ...)` or "
        f"`_rate_limited({per_tenant_helper}, ...)`."
    )
    assert per_tenant_inline in body or per_tenant_helper in body, (
        f"H-8 follow-up: {module_path}:{fn_name} bucket `{bucket}` is not "
        f"keyed per-tenant. Expected either `{per_tenant_inline}` or "
        f"`{per_tenant_helper})` in handler body."
    )


def test_no_literal_rate_limit_remains_in_app_api():
    """Whole-package guard: a future contributor who adds a NEW route that
    calls `_rate_limited("foo", ...)` (literal) should be blocked at CI.

    Whitelist: per-IP buckets (`pkce_store:{_ip}`) and per-user buckets
    (`tts_clone:{user_key}`) are intentional — they target unauthenticated
    or pre-account-binding flows.
    """
    import os
    import re

    api_dir = os.path.dirname(inspect.getsourcefile(__import__("app.api", fromlist=["app"])))
    literal_calls: list[tuple[str, int, str]] = []
    for fname in os.listdir(api_dir):
        if not fname.endswith(".py"):
            continue
        path = os.path.join(api_dir, fname)
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                # `_rate_limited("...")` — bare double-quoted literal
                m = re.search(r'_rate_limited\(\s*"([^"]+)"', line)
                if m and ":" not in m.group(1):
                    literal_calls.append((fname, lineno, line.rstrip()))

    assert not literal_calls, (
        "Literal-keyed `_rate_limited` calls found — every bucket must be "
        "keyed by tenant (or per-IP / per-user for unauth flows). "
        "Use `f\"<bucket>:{_aid}\"` after `_aid = _resolve_account_id_cached()`.\n"
        + "\n".join(f"  {f}:{n}  {s}" for f, n, s in literal_calls)
    )


# --------------------------------------------------------------------------- #
# Behavioural assertion — confirm `_rate_limited` actually isolates buckets
# per key. This guards against a future refactor that breaks the dict keying
# (e.g., normalising keys to a common prefix).
# --------------------------------------------------------------------------- #


def test_rate_limited_buckets_are_isolated_per_key():
    """Two distinct bucket keys must not share count — proves the per-tenant
    fix actually achieves isolation at the helper level."""
    from app.api import routes_helpers

    # `_rate_limited` short-circuits when `current_app.testing` is True, so
    # we need a real Flask app with testing=False to exercise the limiter.
    from flask import Flask
    app = Flask(__name__)
    app.config["TESTING"] = False

    # Reset the module-level dict so prior tests don't pollute counts.
    routes_helpers._rate_limit_buckets.clear()

    with app.app_context():
        # Tenant 1 burns through its 2-call quota.
        a1, _ = routes_helpers._rate_limited(
            "voice_parse:1", max_calls=2, window_seconds=60
        )
        a2, _ = routes_helpers._rate_limited(
            "voice_parse:1", max_calls=2, window_seconds=60
        )
        a3, retry = routes_helpers._rate_limited(
            "voice_parse:1", max_calls=2, window_seconds=60
        )
        assert a1 is True
        assert a2 is True
        assert a3 is False, "Tenant 1 should be rate-limited after 2 calls"
        assert retry > 0

        # Tenant 2 must STILL be allowed — its bucket is independent.
        b1, _ = routes_helpers._rate_limited(
            "voice_parse:2", max_calls=2, window_seconds=60
        )
        assert b1 is True, (
            "Tenant 2 was DoS'd by tenant 1's traffic — buckets are not "
            "isolated. The H-8 fix is regressed."
        )
