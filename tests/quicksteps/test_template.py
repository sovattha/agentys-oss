# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Template variable interpolation.

Two correctness properties:
  1. Variables are substituted by literal lookup — no eval, no string format.
  2. ``render_html`` HTML-escapes substituted values so user-controlled
     names cannot break the surrounding markup (XSS guard).
"""
from __future__ import annotations

from datetime import datetime

from app.quicksteps import template


def _ctx(**kw) -> dict[str, str]:
    base = template.build_context(
        sender_email="alice.smith@example.com",
        sender_name="Alice Smith",
        subject="Project status",
        me_email="me@example.com",
        me_display_name="Bob Builder",
        locale="fr",
        now=datetime(2026, 5, 6),
    )
    base.update(kw)
    return base


class TestBuildContext:
    def test_full_population(self):
        ctx = _ctx()
        assert ctx["sender.firstname"] == "Alice"
        assert ctx["sender.lastname"] == "Smith"
        assert ctx["sender.email"] == "alice.smith@example.com"
        assert ctx["sender.name"] == "Alice Smith"
        assert ctx["subject"] == "Project status"
        assert ctx["me.firstname"] == "Bob"
        assert ctx["me.email"] == "me@example.com"
        # French date formatting
        assert ctx["date"] == "6 mai 2026"

    def test_falls_back_to_local_part_when_name_missing(self):
        ctx = template.build_context(sender_email="someone@x.com", sender_name="")
        assert ctx["sender.firstname"] == "someone"
        assert ctx["sender.lastname"] == ""

    def test_lastname_empty_when_one_word(self):
        ctx = template.build_context(sender_email="x@y.com", sender_name="Madonna")
        assert ctx["sender.firstname"] == "Madonna"
        assert ctx["sender.lastname"] == ""

    def test_english_date_locale(self):
        ctx = template.build_context(locale="en", now=datetime(2026, 5, 6))
        # English format includes the month name; we don't assert exact form
        # because strftime depends on the system locale; only that it ran.
        assert "2026" in ctx["date"]

    def test_no_none_values(self):
        ctx = template.build_context()
        assert all(isinstance(v, str) for v in ctx.values())


class TestRenderPlain:
    def test_substitutes_known_variables(self):
        out = template.render_plain("Hi {sender.firstname}, re: {subject}", _ctx())
        assert out == "Hi Alice, re: Project status"

    def test_unknown_variable_renders_empty(self):
        out = template.render_plain("[{nope.foo}]", _ctx())
        assert out == "[]"

    def test_empty_template_returns_empty(self):
        assert template.render_plain("", _ctx()) == ""

    def test_no_variables_passes_through(self):
        out = template.render_plain("hello world", _ctx())
        assert out == "hello world"


class TestRenderHtml:
    def test_substitutes_and_escapes(self):
        ctx = _ctx()
        out = template.render_html("<p>Hello {sender.firstname}</p>", ctx)
        assert out == "<p>Hello Alice</p>"

    def test_html_in_value_is_escaped(self):
        ctx = template.build_context(
            sender_email="bad@example.com",
            sender_name="Bob & <script>alert(1)</script>",
        )
        out = template.render_html("<p>From: {sender.name}</p>", ctx)
        assert "<script>" not in out
        assert "&lt;script&gt;" in out
        assert "&amp;" in out

    def test_quote_in_value_is_escaped(self):
        ctx = template.build_context(sender_name='Alice "Quotes" Smith', sender_email="a@x.com")
        out = template.render_html("{sender.name}", ctx)
        assert '"' not in out
        assert "&quot;" in out


class TestUnknownVariableCollection:
    def test_returns_sorted_unique(self):
        problems = template.collect_unknown_variables(
            "{nope.alpha} {nope.alpha} {nope.beta}",
            _ctx(),
        )
        assert problems == ["nope.alpha", "nope.beta"]

    def test_empty_when_all_known(self):
        assert template.collect_unknown_variables(
            "Hi {sender.firstname}, today is {date}",
            _ctx(),
        ) == []

    def test_empty_template_returns_empty(self):
        assert template.collect_unknown_variables("", _ctx()) == []


class TestPlaceholderChips:
    """`{x}` menu chips (data-ar-token spans) resolve like plain {token}s."""

    FIRST_NAME_CHIP = (
        '<span class="ar-token" data-ar-token="sender.firstname" '
        'contenteditable="false">Prénom expéditeur</span>'
    )
    SUBJECT_CHIP = (
        '<span class="ar-token" data-ar-token="subject" '
        'contenteditable="false">Sujet</span>'
    )

    def test_render_html_resolves_chip(self):
        out = template.render_html(
            f"Bonjour {self.FIRST_NAME_CHIP}, re: {self.SUBJECT_CHIP}", _ctx()
        )
        assert out == "Bonjour Alice, re: Project status"
        assert "data-ar-token" not in out

    def test_render_plain_resolves_chip(self):
        out = template.render_plain(f"Re: {self.SUBJECT_CHIP}", _ctx())
        assert out == "Re: Project status"

    def test_chip_value_is_html_escaped(self):
        # XSS guard still applies to chip-sourced tokens.
        ctx = _ctx(**{"sender.firstname": '<script>"x"'})
        out = template.render_html(f"Hi {self.FIRST_NAME_CHIP}", ctx)
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_collect_unknown_variables_sees_through_chips(self):
        bad = (
            '<span data-ar-token="sender.bogus" contenteditable="false">X</span>'
        )
        assert template.collect_unknown_variables(bad, _ctx()) == ["sender.bogus"]

    def test_known_chip_is_not_flagged_unknown(self):
        assert template.collect_unknown_variables(self.FIRST_NAME_CHIP, _ctx()) == []


class TestUnifiedSyntaxAndVocab:
    """Footgun fix: one renderer accepts both ``{x}`` and ``{{x}}``, shares one
    vocabulary (sender.* / me.* / recipient.* + legacy aliases), and exposes an
    ``on_unknown`` policy — reply/forward and the follow-up draft now agree."""

    def test_double_brace_syntax_resolves(self):
        # The follow-up `{{...}}` syntax now resolves in the shared renderer.
        assert template.render_plain("Hi {{sender.firstname}}", _ctx()) == "Hi Alice"
        assert template.render_html("<p>{{subject}}</p>", _ctx()) == "<p>Project status</p>"

    def test_legacy_recipient_aliases_map_to_canonical(self):
        ctx = template.build_context(
            recipient_email="alex.doe@acme.com", subject="Q3 plan",
        )
        assert template.render_plain(
            "{{recipient_name}} / {{recipient_first_name}}", ctx,
        ) == "Alex Doe / Alex"
        assert template.render_plain("re {{original_subject}}", ctx) == "re Q3 plan"
        # The canonical dotted form is equivalent to the legacy alias.
        assert template.render_plain("{recipient.name}", ctx) == "Alex Doe"

    def test_recipient_falls_back_to_sender_for_inbound(self):
        # No explicit recipient (reply/forward) → recipient.* aliases the
        # inbound sender, so a body addressing the recipient resolves to the
        # person being replied to instead of failing silently.
        assert template.render_plain("Hi {recipient.firstname}", _ctx()) == "Hi Alice"

    def test_explicit_recipient_overrides_sender(self):
        ctx = template.build_context(
            sender_email="alice@x.com", sender_name="Alice Smith",
            recipient_email="bob.jones@acme.com",
        )
        assert ctx["recipient.name"] == "Bob Jones"
        assert ctx["recipient.firstname"] == "Bob"
        assert ctx["sender.name"] == "Alice Smith"

    def test_on_unknown_blank_is_default(self):
        assert template.render_plain("track {order_id}", _ctx()) == "track "

    def test_on_unknown_literal_keeps_token(self):
        # Both syntaxes are left intact when the policy is "literal" (the
        # follow-up path — protects pasted braces like {shipping_id}).
        assert template.render_plain(
            "track {order_id} and {{ship_no}}", _ctx(), on_unknown="literal",
        ) == "track {order_id} and {{ship_no}}"

    def test_collect_unknown_resolves_aliases(self):
        ctx = template.build_context(recipient_email="a@b.com", subject="x")
        assert template.collect_unknown_variables(
            "{{recipient_name}} {{original_subject}}", ctx,
        ) == []
        # Genuinely unknown names still surface.
        assert template.collect_unknown_variables("{{bogus_name}}", ctx) == ["bogus_name"]

    def test_render_html_escapes_double_brace_value(self):
        ctx = template.build_context(sender_name="<b>x</b>", sender_email="a@x.com")
        out = template.render_html("{{sender.name}}", ctx)
        assert "<b>" not in out
        assert "&lt;b&gt;" in out
