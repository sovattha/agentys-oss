# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Sentinel leak follow-up — 2026-05-11.

Source: tasks/sentinel-leak-audit-2026-05-11.md (S-01, S-02, S-03, S-05, S-08).

Follow-up to PR #634 (the `(no closing or just name)` fix). Audit found
four related leak paths plus a placeholder injection gap.

User demanded: "je ne veux pas d'injection à définir, à confirmer, TBD" —
defense in depth across all sinks.

  S-01 (LATENT)  smart_routing.py Path A `variables["sign_off"]` reads
                  preferred_closings[0] raw — bypasses _compute_closing_hint
                  and would leak the sentinel into a user-defined template.
  S-02 (MEDIUM) routes_misc.py `_expand_greeting_template` result not
                  guarded by `"{" not in result` — unknown tokens like
                  {prenom} leak into mandatory_opening verbatim.
  S-03 (MEDIUM) Same defect as S-02 at routes_drafts.py refine-text path.
  S-05 (LOW)    `[À définir]` placeholders from manager.build_knowledge_markdown
                  reach the Drafter system prompt via memoire.md. Self-critique
                  watchlist covers [À confirmer]/[TBD]/etc. but NOT [À définir].
  S-08 (LOW)    memory_trace_builder.py leaves preferred_greetings AND
                  preferred_closings unsanitized — UI display leak.

Run: pytest tests/audit_fixes/test_sentinel_leak_followup.py -v
"""

from __future__ import annotations

import inspect
import re



# --------------------------------------------------------------------------- #
# S-01: Path A `sign_off` template variable must filter the no-closing sentinel
# --------------------------------------------------------------------------- #


class TestS01PathASignOffSentinelFilter:
    def test_source_filters_sentinel_before_template_render(self):
        from app import smart_routing

        src = inspect.getsource(smart_routing)
        m = re.search(r'variables\["sign_off"\]\s*=\s*([^\n]+)', src)
        assert m is not None, "Could not locate variables['sign_off'] assignment"
        assignment = m.group(1)
        ok = (
            "_is_no_closing_marker" in assignment
            or "_compute_closing_hint" in assignment
            or "preferred_closings[0]" not in assignment
        )
        assert ok, (
            f"Path A sign_off assignment is still raw: `{assignment.strip()}` — "
            "the (no closing or just name) sentinel will leak into custom templates."
        )


# --------------------------------------------------------------------------- #
# S-02 / S-03: mandatory_opening must guard against unrendered {tokens}
# --------------------------------------------------------------------------- #


class TestS02RoutesMiscMandatoryOpeningGuard:
    def test_source_has_brace_guard_after_expand(self):
        from app.api import routes_misc

        src = inspect.getsource(routes_misc.compose_email)
        for m in re.finditer(r"_expand_greeting_template\(", src):
            window = src[m.start(): m.start() + 800]
            assert (
                '"{" not in' in window
                or "'{' not in" in window
                or "_expanded" in window  # if refactored to use _expanded var
            ), (
                "routes_misc compose_email: _expand_greeting_template call site "
                "missing `{` guard — unknown placeholders leak as mandatory_opening."
            )


class TestS03RoutesDraftsMandatoryOpeningGuard:
    def test_source_has_brace_guard_after_expand(self):
        from app.api import routes_drafts

        src = inspect.getsource(routes_drafts)
        for m in re.finditer(r"_expand_greeting_template\(", src):
            window = src[m.start(): m.start() + 800]
            assert (
                '"{" not in' in window
                or "'{' not in" in window
                or "_expanded" in window
            ), (
                "routes_drafts.py: _expand_greeting_template call site missing "
                "`{` guard — unknown placeholders leak."
            )


# --------------------------------------------------------------------------- #
# S-05: zero injection of [À définir] / [À confirmer] / [TBD]
# --------------------------------------------------------------------------- #


class TestS05PlaceholderInjection:
    """User demanded: ZERO injection of [À définir], [À confirmer], [TBD]."""

    def test_build_knowledge_markdown_no_a_definir_when_empty(self):
        """No `[À définir]` line emitted when the field is empty."""
        from app.onboarding.manager import build_knowledge_markdown

        profile = {
            "user_name": "",
            "signature": {"company": "", "title": ""},
            "tone": {"default_tone": "semi-formal"},
        }
        md = build_knowledge_markdown(profile, {}, {})

        assert "[À définir]" not in md, (
            f"build_knowledge_markdown still emits [À définir] when fields are "
            f"empty. Output:\n{md}"
        )

    def test_placeholder_markers_include_a_definir(self):
        """CriticAgent's _PLACEHOLDER_MARKERS must catch [À définir]."""
        from app.agents import _PLACEHOLDER_MARKERS

        markers_lower = {m.lower() for m in _PLACEHOLDER_MARKERS}
        assert any("définir" in m for m in markers_lower) or any(
            "definir" in m for m in markers_lower
        ), (
            f"_PLACEHOLDER_MARKERS does not catch [À définir]. "
            f"Current: {sorted(_PLACEHOLDER_MARKERS)}"
        )

    def test_draft_has_placeholder_detects_a_definir(self):
        from app.agents import _draft_has_placeholder

        draft = "Bonjour Alex,\n\nVoici les détails.\n\nCordialement,\n[À définir]"
        assert _draft_has_placeholder(draft) is True, (
            "Critic does not detect [À définir] as a placeholder."
        )

    def test_draft_has_placeholder_detects_a_confirmer_and_tbd(self):
        """Regression guard: existing [À confirmer] and [TBD] detection stays."""
        from app.agents import _draft_has_placeholder

        assert _draft_has_placeholder("Foo [À confirmer]") is True
        assert _draft_has_placeholder("Bar [TBD]") is True


# --------------------------------------------------------------------------- #
# S-08: memory_trace_builder symmetry — sanitize both greetings AND closings
# --------------------------------------------------------------------------- #


class TestS08MemoryTraceBuilderSanitizes:
    def test_no_unrendered_braces_in_trace(self):
        from app.domain.services import memory_trace_builder

        src = inspect.getsource(memory_trace_builder)
        for field in ("preferred_greetings", "preferred_closings"):
            m = re.search(
                rf'"{field}":\s*([^\n,]+(?:,\s*\n[^\n]+)*)',
                src,
            )
            assert m is not None, f"Could not locate {field} assignment"
            assignment = m.group(1)
            ok = (
                "sanitize" in assignment.lower()
                or '"{"' in assignment
                or "'{'" in assignment
            )
            assert ok, (
                f"memory_trace_builder: {field} assignment `{assignment}` "
                "lacks brace/sanitize filter — `{first_name}` tokens leak "
                "into the memory trace UI."
            )
