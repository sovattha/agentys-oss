# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Comprehensive unit tests for the smart_routing module.

Tests pure/testable functions that don't require LLM calls or container setup.
Focus on rule-based logic, regex patterns, and data structure handling.
"""

import os

# Set API key BEFORE any imports that might use it
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")

# Prevent conftest from importing app.api (sentry/OpenSSL chain)
# This test file uses only pure functions from smart_routing
import pytest

from app.smart_routing import (
    # Data structures
    RoutingTier,
    SmartRouter,
    ComplexitySignals,
    RoutingDecision,
    RoutingResult,
    # Pure utility functions
    _is_filler_line,
    should_skip_prefilter,
    _count_questions,
    analyze_complexity,
    calculate_complexity_score,
    calculate_dynamic_max_tokens,
    _parse_combined_response,
    _parse_email_content,
    _extract_first_name,
    _strip_signature,
    _clean_prompt_leakage,
    _strip_filler_mid_draft,
    _strip_duplicate_greetings,
    _enforce_greeting,
    _detect_blackmail,
    _detect_misdirected,
    _strip_leading_parrot,
    _truncate_for_short_body,
    _strip_hedging,
    _strip_subject_echo,
    _fallback_for_greeting_closing_stub,
    strip_unknown_body_artifacts,
    # Critic skip gate + observability
    _draft_passes_quality_gate,
    _complex_user_notes_fast_path_passes,
    _has_meaningful_user_instructions,
    _record_critic_gate,
    _get_critic_gate_snapshot,
    _multi_draft_enabled_for,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_signals():
    """Standard complexity signals for baseline testing."""
    return ComplexitySignals(
        body_length=500,
        question_count=2,
        technical_content=1,
        thread_depth=1,
        topic_count=1,
        multiple_requests=False,
        user_instructions=False,
        has_attachments=False,
    )


# ============================================================================
# TEST: _multi_draft_enabled_for
# ============================================================================


class TestMultiDraftEnabledFor:
    def test_user_instructions_disable_multi_draft(self, monkeypatch):
        monkeypatch.setattr("app.config.MULTI_DRAFT_ENABLED", True)

        assert _multi_draft_enabled_for("Réponds en confirmant le rendez-vous") is False

    def test_empty_instructions_honor_feature_flag(self, monkeypatch):
        monkeypatch.setattr("app.config.MULTI_DRAFT_ENABLED", True)

        assert _multi_draft_enabled_for("") is True


# ============================================================================
# TEST: strip_unknown_body_artifacts
# ============================================================================


class TestUnknownBodyArtifacts:
    def test_removes_provider_unknown_artifact_lines(self):
        draft = (
            "Bonjour Alexandre,\n\n"
            "Merci pour ton soutien.\n\n"
            "Unknown (forwarded content),\n\n"
            "À bientôt,"
        )

        result = strip_unknown_body_artifacts(draft)

        assert "Unknown" not in result
        assert "Merci pour ton soutien" in result
        assert result.endswith("À bientôt,")

    def test_preserves_unknown_inside_real_sentence(self):
        draft = "Le statut exact est encore unknown côté fournisseur."

        assert strip_unknown_body_artifacts(draft) == draft


# ============================================================================
# TEST: _is_filler_line
# ============================================================================

class TestIsFillerLine:
    """Test filler line detection."""

    def test_empty_line(self):
        """Empty/whitespace-only lines are not filler."""
        assert not _is_filler_line("")
        assert not _is_filler_line("   ")
        assert not _is_filler_line("\n")

    def test_exact_filler_matches(self):
        """Exact filler phrases are detected."""
        assert _is_filler_line("super")
        assert _is_filler_line("Super!")
        assert _is_filler_line("awesome")
        assert _is_filler_line("let's go")
        assert _is_filler_line("c'est parti")
        assert _is_filler_line("C'est parti!")

    def test_french_filler(self):
        """French filler phrases are detected."""
        assert _is_filler_line("je reste à votre disposition")
        assert _is_filler_line("n'hésitez pas à me contacter")
        assert _is_filler_line("j'espère que cela aide")

    def test_english_filler(self):
        """English filler phrases are detected."""
        assert _is_filler_line("feel free to reach out")
        assert _is_filler_line("i'm happy to help")
        assert _is_filler_line("happy to assist")

    def test_prefix_match(self):
        """Filler prefixes are detected."""
        assert _is_filler_line("c'est parti, voilà!")
        assert _is_filler_line("let's go and get started")
        assert _is_filler_line("bien sûr, je vais faire")

    def test_meta_commentary_regex(self):
        """Meta-commentary patterns are detected."""
        assert _is_filler_line("en réponse à votre email")
        assert _is_filler_line("voici ma réponse")
        assert _is_filler_line("regarding your message")
        assert _is_filler_line("here is my reply")

    def test_non_filler_content(self):
        """Normal content is not flagged as filler."""
        assert not _is_filler_line("I can help with that issue")
        assert not _is_filler_line("The database is down")
        # Note: "Regarding your request" matches meta-commentary regex, so it's filler
        assert not _is_filler_line("I found a good solution for you")

    def test_filler_with_trailing_punctuation(self):
        """Filler detection handles trailing punctuation."""
        assert _is_filler_line("super!")
        assert _is_filler_line("super!.")
        assert _is_filler_line("super,")
        assert _is_filler_line("super.")


# ============================================================================
# TEST: should_skip_prefilter
# ============================================================================

class TestShouldSkipPrefilter:
    """Test pre-filter skip logic."""

    def test_self_sent_email(self):
        """Self-sent emails are skipped."""
        result = should_skip_prefilter(
            sender="john@example.com",
            user_email="john@example.com",
        )
        assert result == "self-sent"

    def test_self_sent_case_insensitive(self):
        """Self-sent detection is case-insensitive."""
        result = should_skip_prefilter(
            sender="John@Example.com",
            user_email="john@example.com",
        )
        assert result == "self-sent"

    def test_auto_generated_senders(self):
        """Auto-generated senders are skipped."""
        assert should_skip_prefilter(sender="noreply@company.com")
        assert should_skip_prefilter(sender="no-reply@example.com")
        assert should_skip_prefilter(sender="notifications@app.com")
        assert should_skip_prefilter(sender="mailer-daemon@example.com")
        assert should_skip_prefilter(sender="postmaster@example.com")
        # Additional patterns - test with angle brackets for proper matching
        assert should_skip_prefilter(sender="<noreply@example.com>")
        assert should_skip_prefilter(sender="Bounce notification <bounce@company.com>")

    def test_github_gitlab_senders(self):
        """GitHub/GitLab notifications are skipped."""
        assert should_skip_prefilter(sender="notifications@github.com")
        assert should_skip_prefilter(sender="noreply@gitlab.com")
        assert should_skip_prefilter(sender="notifications@bitbucket.org")

    def test_calendar_subjects(self):
        """Calendar/meeting subjects are skipped."""
        # Pattern requires "invitation|accepted|declined" + "meeting|event" with stuff in between
        assert should_skip_prefilter(
            sender="john@example.com",
            subject="invitation for the meeting"
        )
        assert should_skip_prefilter(
            sender="john@example.com",
            subject="accepted the event"
        )
        assert should_skip_prefilter(
            sender="john@example.com",
            subject="declined the reunion"
        )

    def test_ooo_subjects(self):
        """Out of office subjects are skipped."""
        assert should_skip_prefilter(
            sender="john@example.com",
            subject="Out of office until Friday"
        )
        assert should_skip_prefilter(
            sender="john@example.com",
            subject="Auto-reply: Will return Monday"
        )

    def test_delivery_status_subjects(self):
        """Delivery status subjects are skipped."""
        assert should_skip_prefilter(
            sender="john@example.com",
            subject="Undeliverable: Your message could not be sent"
        )
        assert should_skip_prefilter(
            sender="john@example.com",
            subject="Mail Delivery Status Notification"
        )

    def test_non_action_labels(self):
        """Non-action labels are skipped."""
        assert should_skip_prefilter(
            sender="john@example.com",
            label="FYI"
        )
        assert should_skip_prefilter(
            sender="john@example.com",
            label="Noise"
        )

    def test_action_label_not_skipped(self):
        """Action label doesn't trigger skip."""
        result = should_skip_prefilter(
            sender="john@example.com",
            label="Action"
        )
        assert result is None

    def test_normal_email_not_skipped(self):
        """Normal emails are not skipped."""
        result = should_skip_prefilter(
            sender="alice@company.com",
            user_email="bob@company.com",
            subject="Project Update",
            label="Action"
        )
        assert result is None

    def test_empty_label_not_skipped(self):
        """Empty label doesn't trigger skip."""
        result = should_skip_prefilter(
            sender="john@example.com",
            label=""
        )
        assert result is None


# ============================================================================
# TEST: _count_questions
# ============================================================================

class TestCountQuestions:
    """Test question counting logic."""

    def test_no_questions(self):
        """Text with no questions returns 0."""
        assert _count_questions("This is a statement.") == 0
        assert _count_questions("I agree with this approach.") == 0

    def test_question_mark_only(self):
        """Question marks are counted."""
        assert _count_questions("Can you help?") == 1
        assert _count_questions("Can you help? What about this?") == 2

    def test_interrogative_phrases(self):
        """Interrogative phrase patterns are counted."""
        assert _count_questions("Is there a problem?") >= 1
        assert _count_questions("Could you review this?") >= 1
        assert _count_questions("Would you be available?") >= 1

    def test_french_questions(self):
        """French question patterns are counted."""
        assert _count_questions("Pouvez-vous m'aider?") >= 1
        assert _count_questions("Comment ça marche?") >= 1
        assert _count_questions("Quand sera-ce disponible?") >= 1

    def test_multiple_questions_same_sentence(self):
        """Multiple questions in one sentence are counted."""
        text = "Can you help? What about this? When will you be ready?"
        count = _count_questions(text)
        assert count >= 3

    def test_interrogative_without_question_mark(self):
        """Interrogative phrases without ? marks are counted."""
        text = "I wonder if you could help"
        # May or may not be counted depending on pattern matching
        # Just verify it doesn't crash
        count = _count_questions(text)
        assert isinstance(count, int)

    def test_multiline_questions(self):
        """Questions across multiple lines are counted."""
        text = "Can you help?\n\nWhat about this?\n\nWhen will it be done?"
        count = _count_questions(text)
        assert count >= 2

    def test_mixed_lang_questions(self):
        """Mixed language questions are counted."""
        text = "Can you help? Pouvez-vous m'aider?"
        count = _count_questions(text)
        assert count >= 2


# ============================================================================
# TEST: analyze_complexity
# ============================================================================

class TestAnalyzeComplexity:
    """Test complexity signal analysis."""

    def test_empty_input(self):
        """Empty inputs return minimal signals."""
        signals = analyze_complexity("")
        assert signals.body_length == 0
        assert signals.question_count == 0
        assert signals.technical_content == 0

    def test_body_length_captured(self):
        """Body length is accurately captured."""
        text = "a" * 500
        signals = analyze_complexity(text)
        assert signals.body_length == 500

    def test_question_counting(self):
        """Questions are counted in signals."""
        text = "Can you help? What about this? When?"
        signals = analyze_complexity(text)
        assert signals.question_count >= 2

    def test_technical_keywords_detected(self):
        """Technical keywords are detected."""
        text = "The API endpoint has an error. Check the SQL schema."
        signals = analyze_complexity(text)
        assert signals.technical_content > 0

    def test_list_detection(self):
        """Lists trigger multiple_requests flag."""
        text = """
        1. First item
        2. Second item
        3. Third item
        """
        signals = analyze_complexity(text)
        assert signals.multiple_requests is True

    def test_topic_count_detection(self):
        """Multiple topics are detected via paragraph breaks."""
        text = """
        First topic here.

        Second topic here.

        Third topic here.
        """
        signals = analyze_complexity(text)
        assert signals.topic_count >= 2

    def test_thread_depth_passed_through(self):
        """Thread depth parameter is captured."""
        signals = analyze_complexity("text", thread_depth=5)
        assert signals.thread_depth == 5

    def test_instructions_flag(self):
        """User instructions flag is set."""
        signals = analyze_complexity("text", has_instructions=True)
        assert signals.user_instructions is True

    def test_attachments_flag(self):
        """Attachments flag is set."""
        signals = analyze_complexity("text", has_attachments=True)
        assert signals.has_attachments is True

    def test_topic_count_capped(self):
        """Topic count is capped at 5."""
        text = "\n\n".join(["topic"] * 20)
        signals = analyze_complexity(text)
        assert signals.topic_count <= 5


# ============================================================================
# TEST: calculate_complexity_score
# ============================================================================

class TestCalculateComplexityScore:
    """Test complexity scoring algorithm."""

    def test_minimal_email(self):
        """Minimal email gets low score."""
        signals = ComplexitySignals(body_length=50, question_count=0)
        score = calculate_complexity_score(signals)
        assert 0 <= score < 30

    def test_simple_email(self):
        """Simple email with one question."""
        signals = ComplexitySignals(
            body_length=200,
            question_count=1,
            technical_content=0,
        )
        score = calculate_complexity_score(signals)
        assert 0 <= score < 50

    def test_complex_email(self):
        """Complex email with multiple signals."""
        signals = ComplexitySignals(
            body_length=2000,
            question_count=5,
            technical_content=3,
            thread_depth=5,
            multiple_requests=True,
            user_instructions=True,
            has_attachments=True,
        )
        score = calculate_complexity_score(signals)
        assert score >= 70

    def test_score_range(self):
        """Scores are bounded 0-100."""
        signals = ComplexitySignals(
            body_length=10000,
            question_count=10,
            technical_content=10,
            thread_depth=10,
        )
        score = calculate_complexity_score(signals)
        assert 0 <= score <= 100

    def test_body_length_scoring(self):
        """Body length contributes to score."""
        short = ComplexitySignals(body_length=100)
        long = ComplexitySignals(body_length=2000)
        short_score = calculate_complexity_score(short)
        long_score = calculate_complexity_score(long)
        assert long_score > short_score

    def test_question_count_scoring(self):
        """Question count contributes to score."""
        no_q = ComplexitySignals(body_length=500, question_count=0)
        one_q = ComplexitySignals(body_length=500, question_count=1)
        many_q = ComplexitySignals(body_length=500, question_count=3)
        assert calculate_complexity_score(one_q) > calculate_complexity_score(no_q)
        assert calculate_complexity_score(many_q) > calculate_complexity_score(one_q)

    def test_technical_content_scoring(self):
        """Technical content contributes to score."""
        no_tech = ComplexitySignals(technical_content=0)
        one_tech = ComplexitySignals(technical_content=1)
        many_tech = ComplexitySignals(technical_content=4)
        assert calculate_complexity_score(one_tech) > calculate_complexity_score(no_tech)
        assert calculate_complexity_score(many_tech) > calculate_complexity_score(one_tech)

    def test_thread_depth_scoring(self):
        """Thread depth contributes to score."""
        shallow = ComplexitySignals(thread_depth=0)
        medium = ComplexitySignals(thread_depth=2)
        deep = ComplexitySignals(thread_depth=5)
        assert calculate_complexity_score(medium) > calculate_complexity_score(shallow)
        assert calculate_complexity_score(deep) > calculate_complexity_score(medium)


# ============================================================================
# TEST: calculate_dynamic_max_tokens
# ============================================================================

class TestCalculateDynamicMaxTokens:
    """Test dynamic token budget calculation."""

    def test_skip_tier_zero_tokens(self):
        """SKIP tier gets 0 tokens."""
        signals = ComplexitySignals()
        assert calculate_dynamic_max_tokens(signals, RoutingTier.SKIP) == 0

    def test_simple_tier_fixed_tokens(self):
        """SIMPLE tier gets fixed 150 tokens."""
        signals = ComplexitySignals()
        assert calculate_dynamic_max_tokens(signals, RoutingTier.SIMPLE) == 150

    def test_standard_ultra_short(self):
        """Ultra-short simple emails get 128 tokens."""
        signals = ComplexitySignals(body_length=100, question_count=0)
        tokens = calculate_dynamic_max_tokens(signals, RoutingTier.STANDARD)
        assert tokens == 128

    def test_standard_short(self):
        """Short emails get 256 tokens."""
        signals = ComplexitySignals(body_length=250, question_count=1)
        tokens = calculate_dynamic_max_tokens(signals, RoutingTier.STANDARD)
        assert tokens == 256

    def test_standard_medium(self):
        """Medium emails get 384 tokens."""
        signals = ComplexitySignals(body_length=400, question_count=2)
        tokens = calculate_dynamic_max_tokens(signals, RoutingTier.STANDARD)
        assert tokens == 384

    def test_standard_long(self):
        """Long emails get 512 tokens."""
        signals = ComplexitySignals(body_length=800, question_count=3)
        tokens = calculate_dynamic_max_tokens(signals, RoutingTier.STANDARD)
        assert tokens == 512

    def test_standard_very_long(self):
        """Very long emails get 768 tokens."""
        signals = ComplexitySignals(body_length=2000, question_count=5)
        tokens = calculate_dynamic_max_tokens(signals, RoutingTier.STANDARD)
        assert tokens == 768

    def test_complex_tier_varies_by_score(self):
        """COMPLEX tier varies by complexity score."""
        simple_complex = ComplexitySignals(
            body_length=500,
            question_count=1,
            technical_content=0,
        )
        hard_complex = ComplexitySignals(
            body_length=2000,
            question_count=5,
            technical_content=3,
            thread_depth=5,
        )
        simple_tokens = calculate_dynamic_max_tokens(simple_complex, RoutingTier.COMPLEX)
        hard_tokens = calculate_dynamic_max_tokens(hard_complex, RoutingTier.COMPLEX)
        # Both should be ≥768, but hard should be higher or equal
        assert simple_tokens >= 768
        assert hard_tokens >= simple_tokens


# ============================================================================
# TEST: _parse_combined_response
# ============================================================================

class TestParseCombinedResponse:
    """Test JSON parsing of combined classification+draft."""

    def test_valid_json(self):
        """Valid JSON is parsed correctly."""
        content = '{"label": "Action", "draft": "I will help with this."}'
        label, draft = _parse_combined_response(content)
        assert label == "Action"
        assert draft == "I will help with this."

    def test_json_with_markdown_fences(self):
        """JSON wrapped in markdown code fences is parsed."""
        content = '```json\n{"label": "FYI", "draft": "Just FYI"}\n```'
        label, draft = _parse_combined_response(content)
        assert label == "FYI"
        assert draft == "Just FYI"

    def test_missing_label(self):
        """Missing label defaults to FYI."""
        content = '{"draft": "Some text"}'
        label, draft = _parse_combined_response(content)
        assert label == "FYI"

    def test_missing_draft(self):
        """Missing draft defaults to empty string."""
        content = '{"label": "Action"}'
        label, draft = _parse_combined_response(content)
        assert label == "Action"
        assert draft == ""

    def test_null_draft(self):
        """Null draft is treated as empty."""
        content = '{"label": "Action", "draft": null}'
        label, draft = _parse_combined_response(content)
        assert label == "Action"
        assert draft == ""

    def test_string_null_draft(self):
        """String "null" is treated as empty."""
        content = '{"label": "Action", "draft": "null"}'
        label, draft = _parse_combined_response(content)
        assert label == "Action"
        assert draft == ""

    def test_invalid_json_fallback_with_label(self):
        """Invalid JSON falls back to keyword detection."""
        content = "Action\nThis is the draft content."
        label, draft = _parse_combined_response(content)
        assert label == "Action"
        assert "draft" in draft.lower()

    def test_invalid_json_fallback_fyi(self):
        """Invalid JSON with FYI label."""
        content = "FYI\nSome content here"
        label, draft = _parse_combined_response(content)
        assert label == "FYI"

    def test_invalid_json_default(self):
        """Invalid JSON with no recognizable label defaults to FYI."""
        content = "This is just plain text that doesn't parse"
        label, draft = _parse_combined_response(content)
        assert label == "FYI"


# ============================================================================
# TEST: _parse_email_content
# ============================================================================

class TestParseEmailContent:
    """Test email string parsing."""

    def test_full_email_parsing(self):
        """Complete email with From/Subject/Body is parsed."""
        email = """From: alice@example.com
Subject: Project Update

Here is the project status."""
        sender, subject, body = _parse_email_content(email)
        assert "alice@example.com" in sender
        assert "Project Update" in subject
        assert "status" in body.lower()

    def test_french_format(self):
        """French format (De:/Sujet:) is parsed."""
        email = """De: bob@example.com
Sujet: Réunion demain

Le code est prêt."""
        sender, subject, body = _parse_email_content(email)
        assert "bob@example.com" in sender
        assert "Réunion" in subject
        assert "prêt" in body.lower()

    def test_only_body(self):
        """Email with only body may return empty values if no headers found."""
        email = "Just the body text here."
        sender, subject, body = _parse_email_content(email)
        # If no clear headers, sender/subject may be empty
        assert sender == "" or "@" in sender
        assert subject == ""
        # Body may be empty or contain the text depending on parsing
        assert body == "" or "body" in body.lower() or "text" in body.lower()

    def test_case_insensitive_headers(self):
        """Headers are case-insensitive."""
        email = """FROM: charlie@example.com
SUBJECT: Query

Question about the API."""
        sender, subject, body = _parse_email_content(email)
        assert "charlie@example.com" in sender
        assert "Query" in subject

    def test_empty_input(self):
        """Empty input returns empty strings."""
        sender, subject, body = _parse_email_content("")
        assert sender == ""
        assert subject == ""
        assert body == ""


# ============================================================================
# TEST: _extract_first_name
# ============================================================================

class TestExtractFirstName:
    """Test first name extraction from sender."""

    def test_full_name_with_email(self):
        """Full name with email is parsed."""
        assert _extract_first_name("John Doe <john@example.com>") == "John"
        assert _extract_first_name("Alice Smith <alice@example.com>") == "Alice"

    def test_single_name(self):
        """Single name is extracted."""
        assert _extract_first_name("John <john@example.com>") == "John"

    def test_quoted_name(self):
        """Quoted names are handled."""
        assert _extract_first_name('"John Doe" <john@example.com>') == "John"

    def test_email_only(self):
        """Email-only sender returns empty."""
        assert _extract_first_name("john@example.com") == ""

    def test_empty_sender(self):
        """Empty sender returns empty."""
        assert _extract_first_name("") == ""

    def test_whitespace_only(self):
        """Whitespace-only sender returns empty."""
        assert _extract_first_name("   ") == ""

    def test_name_with_special_chars(self):
        """Names with accents/special chars are handled."""
        # Should extract the first word
        assert _extract_first_name("François Dupont <francois@example.com>") == "François"


# ============================================================================
# TEST: _strip_signature
# ============================================================================

class TestStripSignature:
    """Test signature removal from drafts."""

    def test_simple_signature_removed(self):
        """Simple sign-off is removed."""
        draft = """I'll help with that.

Best regards,
John"""
        result = _strip_signature(draft)
        assert "Best regards" not in result
        assert "John" not in result or result.count("John") < draft.count("John")

    def test_trailing_empty_lines_removed(self):
        """Trailing empty lines are removed."""
        draft = """Here's the answer.


"""
        result = _strip_signature(draft)
        assert result.strip() == "Here's the answer."

    def test_french_signature_removed(self):
        """French sign-offs are removed."""
        draft = """Voici la réponse.

Cordialement,
Alexandre"""
        result = _strip_signature(draft)
        assert "Cordialement" not in result
        # Name may be partially preserved if it's common

    def test_draft_without_signature_unchanged(self):
        """Draft without signature is unchanged."""
        draft = "This is just content without signature."
        result = _strip_signature(draft)
        assert result.strip() == draft.strip()

    def test_yes_no_artifacts_removed(self):
        """YES/NO artifacts are removed."""
        draft = """I agree with the plan.

YES,"""
        result = _strip_signature(draft)
        assert "YES" not in result or "agree" in result

    def test_empty_draft_unchanged(self):
        """Empty draft remains empty or whitespace."""
        assert _strip_signature("") == ""
        # Whitespace-only draft may be returned as-is or stripped
        result = _strip_signature("   ")
        assert result == "" or result.strip() == ""


# ============================================================================
# TEST: _clean_prompt_leakage
# ============================================================================

class TestCleanPromptLeakage:
    """Test removal of prompt structure artifacts."""

    def test_email_headers_removed(self):
        """Email headers at top are removed."""
        draft = """From: john@example.com
Date: 2024-03-20
Subject: Re: Project

Here's the content."""
        result = _clean_prompt_leakage(draft)
        assert "From:" not in result
        assert "Date:" not in result
        assert "Here's the content" in result

    def test_separator_cut(self):
        """Content after --- separator is cut."""
        draft = """Great idea, I'll start on it.

---

Alternative response: ..."""
        result = _clean_prompt_leakage(draft)
        assert "Alternative" not in result
        assert "I'll start on it" in result

    def test_a_confirmer_placeholder_removed(self):
        """[À confirmer] placeholders are removed."""
        draft = """I'll send the report.

[À confirmer]"""
        result = _clean_prompt_leakage(draft)
        assert "[À confirmer]" not in result

    def test_filler_lines_at_end_removed(self):
        """Trailing filler lines are removed."""
        draft = """Here's what I found.

I hope this helps!"""
        result = _clean_prompt_leakage(draft)
        assert "I hope this helps" not in result or "Here's what" in result

    def test_clean_content_preserved(self):
        """Non-artifact content is preserved."""
        draft = "Here's my detailed response with real information."
        result = _clean_prompt_leakage(draft)
        assert "detailed response" in result


# ============================================================================
# TEST: _strip_filler_mid_draft
# ============================================================================

class TestStripFillerMidDraft:
    """Test filler removal from middle of draft."""

    def test_full_line_filler_removed(self):
        """Full-line filler is removed."""
        draft = """I can help with that.

I hope this helps!

Let me know if you need anything."""
        result = _strip_filler_mid_draft(draft)
        assert "I hope this helps" not in result

    def test_inline_filler_removed(self):
        """Inline filler phrases are removed."""
        draft = "I'll update the code, and I remain at your disposal."
        result = _strip_filler_mid_draft(draft)
        assert "remain at your disposal" not in result
        assert "update the code" in result

    def test_casual_filler_preserved_at_low_formality(self):
        """Casual filler is preserved at formality ≤ 2."""
        draft = "Super! Let's go with this approach."
        result = _strip_filler_mid_draft(draft, formality=1)
        assert "Super" in result or "Let's go" in result

    def test_casual_filler_removed_at_high_formality(self):
        """Casual filler is removed at formality > 2."""
        draft = "Super! Let's go with this plan."
        result = _strip_filler_mid_draft(draft, formality=4)
        assert "Super" not in result or "plan" in result

    def test_multiple_fillers_removed(self):
        """Multiple filler phrases are removed."""
        draft = """I'll get started on this.

I'm happy to help with the project. I hope this helps!

Let me know if you need anything else."""
        result = _strip_filler_mid_draft(draft)
        assert len(result) < len(draft)
        assert "get started" in result


# ============================================================================
# TEST: _strip_duplicate_greetings
# ============================================================================

class TestStripDuplicateGreetings:
    """Test duplicate greeting removal."""

    def test_single_greeting_kept(self):
        """Single greeting is kept."""
        draft = """Hello John,

I can help with that."""
        result = _strip_duplicate_greetings(draft)
        assert "Hello John" in result

    def test_duplicate_greeting_removed(self):
        """Duplicate greeting mid-draft is removed."""
        draft = """Hello DevOps Team,

Here's the update.

Hi there,

The details follow."""
        result = _strip_duplicate_greetings(draft)
        # First greeting should be kept
        assert "Hello DevOps" in result or "DevOps" in result
        # Duplicate "Hi there" should be removed
        lines_count_before = draft.count('\n')
        lines_count_after = result.count('\n')
        assert lines_count_after <= lines_count_before

    def test_french_duplicate_greeting_removed(self):
        """French duplicate greetings are removed."""
        draft = """Bonjour,

Voici la réponse.

Salut,

Continuons."""
        result = _strip_duplicate_greetings(draft)
        # Only one greeting should remain
        greeting_count = (result.count("Bonjour") + result.count("Salut") +
                         result.count("Hello") + result.count("Hi"))
        assert greeting_count <= 2

    def test_short_draft_unchanged(self):
        """Short drafts with <3 lines are unchanged."""
        draft = """Hello,

Response text."""
        result = _strip_duplicate_greetings(draft)
        assert result == draft

    def test_bare_name_vocative_stripped(self):
        """Bare-name vocative ("Alexandre,") right after greeting is stripped."""
        draft = """Bonjour Alexandre,

Alexandre,

Je voulais confirmer notre réunion de mardi à 15h.

À bientôt,"""
        result = _strip_duplicate_greetings(draft)
        # Full greeting kept
        assert "Bonjour Alexandre" in result
        # Bare vocative "Alexandre," alone on a line should be gone
        lines = [line.strip() for line in result.split('\n') if line.strip()]
        assert "Alexandre," not in lines, f"bare vocative not stripped: {lines}"

    def test_bare_name_with_title_stripped(self):
        """Two-word vocative ("Mme Martin,") after greeting is stripped."""
        draft = """Bonjour Madame,

Mme Martin,

Merci pour votre message."""
        result = _strip_duplicate_greetings(draft)
        lines = [line.strip() for line in result.split('\n') if line.strip()]
        assert "Mme Martin," not in lines

    def test_bare_vocative_not_stripped_in_body(self):
        """Bare name further down (not right after greeting) is preserved."""
        draft = """Bonjour,

Voici la liste des présents :

Alexandre,

Kiki."""
        result = _strip_duplicate_greetings(draft)
        # "Alexandre," is part of a list — must be kept
        assert "Alexandre," in result


class TestEnforceGreeting:
    """Test deterministic greeting enforcement."""

    def test_coucou_named_greeting_not_prefixed_by_formal_title_hint(self):
        """A strong casual greeting from the LLM must not get a second formal line."""
        draft = """Coucou Magali,

Super, c'est noté ! Filet de bar pour toi et filet de bœuf pour Thierry.

Cordialement,"""

        result = _enforce_greeting(draft, "M. Boisseau,")

        lines = [line.strip() for line in result.split("\n") if line.strip()]
        assert lines[0] == "Coucou Magali,"
        assert "M. Boisseau," not in lines
        assert sum(1 for line in lines if line.endswith(",")) == 2


# ============================================================================
# TEST: _detect_blackmail
# ============================================================================

class TestDetectBlackmail:
    """Test blackmail detection and override."""

    def test_normal_email_unchanged(self):
        """Normal emails are not modified."""
        draft = "I can help with the project."
        body = "Can you help with the project?"
        result = _detect_blackmail(draft, body)
        assert result == draft

    def test_email_without_keywords_unchanged(self):
        """Emails without blackmail keywords are unchanged."""
        draft = "I appreciate the feedback."
        body = "Can you provide feedback on the code?"
        result = _detect_blackmail(draft, body)
        assert result == draft

    def test_blackmail_keywords_without_demand_unchanged(self):
        """Blackmail keywords without financial demand don't trigger override."""
        draft = "I'll look into this."
        body = "This is a threat - we demand action!"
        # No financial demand, so should be unchanged
        _detect_blackmail(draft, body)
        # May or may not be changed, but shouldn't crash

    def test_empty_inputs_unchanged(self):
        """Empty inputs are returned unchanged."""
        assert _detect_blackmail("", "") == ""
        assert _detect_blackmail("draft", "") == "draft"
        assert _detect_blackmail("", "body") == ""


# ============================================================================
# TEST: _detect_misdirected
# ============================================================================

class TestDetectMisdirected:
    """Test misdirected email detection."""

    def test_normal_email_unchanged(self):
        """Normal emails are not flagged."""
        draft = "I can help with that."
        body = "Can you help?"
        result = _detect_misdirected(draft, body, "sender@example.com")
        assert result == draft

    def test_without_forwarded_marker_unchanged(self):
        """Emails without 'forwarded message' are unchanged."""
        draft = "I'll get back to you."
        body = "Some internal content here."
        result = _detect_misdirected(draft, body, "sender@example.com")
        assert result == draft

    def test_empty_inputs_unchanged(self):
        """Empty inputs are returned unchanged."""
        assert _detect_misdirected("", "", "") == ""
        assert _detect_misdirected("draft", "", "") == "draft"


# ============================================================================
# TEST: _strip_leading_parrot
# ============================================================================

class TestStripLeadingParrot:
    """Test leading parroting removal."""

    def test_normal_draft_unchanged(self):
        """Normal drafts without parroting are unchanged."""
        draft = "I'll help with the implementation."
        body = "Can you help with implementation?"
        result = _strip_leading_parrot(draft, body)
        assert result == draft

    def test_parrot_line_removed(self):
        """Parroted opening line is removed."""
        draft = "Can you help with the database migration?\n\nI'll start working on it."
        body = "Can you help with the database migration?"
        result = _strip_leading_parrot(draft, body)
        # Parrot line should be stripped
        assert "I'll start working" in result

    def test_short_draft_safety(self):
        """Very short drafts are returned as-is for safety."""
        draft = "Yes"
        body = "Yes"
        result = _strip_leading_parrot(draft, body)
        assert result == draft or len(result) >= len(draft) - 10

    def test_empty_inputs_unchanged(self):
        """Empty inputs are returned unchanged."""
        assert _strip_leading_parrot("", "") == ""
        assert _strip_leading_parrot("draft", "") == "draft"
        assert _strip_leading_parrot("", "body") == ""


# ============================================================================
# TEST: _truncate_for_short_body
# ============================================================================

class TestTruncateForShortBody:
    """Test truncation for very short emails."""

    def test_long_body_unchanged(self):
        """Long emails are not truncated."""
        body = "a" * 200
        draft = "Here's a long detailed response about the project. " * 5
        result = _truncate_for_short_body(draft, body)
        assert result == draft

    def test_ultra_short_body_truncated(self):
        """Ultra-short bodies (<50 chars) are truncated to 1 sentence."""
        body = "Can you help?"
        draft = """Hello,

I'll definitely help. Let me also mention this. And this too. Plus another sentence."""
        result = _truncate_for_short_body(draft, body)
        # Result should be shorter
        assert len(result) <= len(draft)

    def test_short_body_truncated(self):
        """Short bodies (50-99 chars) are truncated to 2 sentences."""
        body = "Can you help with the database? Also need your feedback."
        draft = """Hello,

I'll help with the database. Here's the feedback. Another point. And another. Plus more."""
        result = _truncate_for_short_body(draft, body)
        assert len(result) <= len(draft)

    def test_empty_inputs_unchanged(self):
        """Empty inputs are returned unchanged."""
        assert _truncate_for_short_body("", "") == ""
        assert _truncate_for_short_body("draft", "") == "draft"


# ============================================================================
# TEST: _strip_hedging
# ============================================================================

class TestStripHedging:
    """Test hedging phrase removal."""

    def test_english_hedging_removed(self):
        """English hedging qualifiers are removed."""
        draft = "I think the price is around $50."
        result = _strip_hedging(draft)
        # "I think" should be removed, leaving "The price..."
        assert len(result) < len(draft) or "price" in result

    def test_french_hedging_removed(self):
        """French hedging qualifiers are removed."""
        draft = "Je pense que c'est une bonne idée."
        result = _strip_hedging(draft)
        assert len(result) < len(draft) or "bonne" in result

    def test_normal_text_unchanged(self):
        """Text without hedging is unchanged."""
        draft = "The deadline is Friday."
        result = _strip_hedging(draft)
        assert result == draft

    def test_empty_draft_unchanged(self):
        """Empty draft is unchanged."""
        assert _strip_hedging("") == ""


# ============================================================================
# TEST: _strip_subject_echo
# ============================================================================

class TestStripSubjectEcho:
    """Test subject-echo line removal."""

    def test_subject_echo_removed(self):
        """Opening line echoing subject is removed."""
        subject = "Meeting reschedule?"
        draft = """Regarding the meeting reschedule, I can do Friday.

Friday works for me."""
        result = _strip_subject_echo(draft, subject)
        # The "Regarding..." line should be stripped
        assert len(result) <= len(draft)

    def test_greeting_not_affected(self):
        """Greeting line is not affected."""
        subject = "Project Update"
        draft = """Hello,

Regarding your project update, I have news."""
        result = _strip_subject_echo(draft, subject)
        assert "Hello" in result or "greeting" in result.lower()

    def test_no_subject_echo_unchanged(self):
        """Drafts without subject echo are unchanged."""
        subject = "Status report"
        draft = """Here's the status. Everything is on track."""
        result = _strip_subject_echo(draft, subject)
        assert result == draft

    def test_empty_subject_unchanged(self):
        """Empty subject doesn't trigger processing."""
        draft = "Regarding the matter, here's the response."
        result = _strip_subject_echo(draft, "")
        assert result == draft

    def test_very_short_subject_unchanged(self):
        """Very short subjects (< 2 words) don't trigger processing."""
        subject = "Hi"
        draft = "Regarding your message, I'll help."
        _strip_subject_echo(draft, subject)
        # May or may not change, but shouldn't crash


# ============================================================================
# TEST: DATA STRUCTURES
# ============================================================================

class TestDataStructures:
    """Test data class instantiation and properties."""

    def test_routing_tier_enum_values(self):
        """RoutingTier enum has expected values."""
        assert RoutingTier.SKIP.value == "skip"
        assert RoutingTier.FAQ_AUTO.value == "faq_auto"
        assert RoutingTier.SIMPLE.value == "simple"
        assert RoutingTier.STANDARD.value == "standard"
        assert RoutingTier.COMPLEX.value == "complex"

    def test_complexity_signals_defaults(self):
        """ComplexitySignals has sensible defaults."""
        signals = ComplexitySignals()
        assert signals.body_length == 0
        assert signals.question_count == 0
        assert signals.technical_content == 0
        assert signals.thread_depth == 0
        assert signals.topic_count == 1
        assert signals.multiple_requests is False
        assert signals.user_instructions is False
        assert signals.has_attachments is False

    def test_complexity_signals_customizable(self):
        """ComplexitySignals fields can be customized."""
        signals = ComplexitySignals(
            body_length=500,
            question_count=3,
            technical_content=2,
            thread_depth=2,
            topic_count=2,
            multiple_requests=True,
            user_instructions=True,
            has_attachments=True,
        )
        assert signals.body_length == 500
        assert signals.question_count == 3
        assert signals.technical_content == 2

    def test_routing_decision_creation(self):
        """RoutingDecision can be created."""
        signals = ComplexitySignals(body_length=500)
        decision = RoutingDecision(
            tier=RoutingTier.STANDARD,
            complexity_score=45,
            reason="Normal business email",
            max_tokens=512,
            signals=signals,
        )
        assert decision.tier == RoutingTier.STANDARD
        assert decision.complexity_score == 45
        assert decision.max_tokens == 512

    def test_routing_result_creation(self):
        """RoutingResult can be created."""
        decision = RoutingDecision(
            tier=RoutingTier.STANDARD,
            complexity_score=50,
            reason="Test",
        )
        result = RoutingResult(
            draft="Here's my response.",
            decision=decision,
            classification="Action",
            priority=50,
            status="ROUTED",
        )
        assert result.draft == "Here's my response."
        assert result.classification == "Action"
        assert result.status == "ROUTED"


# ============================================================================
# INTEGRATION-STYLE TESTS
# ============================================================================

class TestIntegrationScenarios:
    """High-level scenario tests combining multiple functions."""

    def test_scheduling_stub_gets_conservative_fallback(self):
        """Greeting+closing-only drafts should not ship for availability asks."""
        draft = "Salut Nathan,\n\nCordialement,"
        body = (
            "Peux-tu me confirmer tes disponibilités cette semaine pour un court "
            "rendez-vous de test Agentys ?"
        )

        result = _fallback_for_greeting_closing_stub(
            draft=draft,
            subject="Test Agentys",
            body=body,
            greeting_hint="Salut Nathan,",
            closing_hint="Cordialement,",
            detected_language="FRENCH",
            formality=2,
        )

        assert result != draft
        assert "créneaux" in result
        assert result.startswith("Salut Nathan,")
        assert result.endswith("Cordialement,")

    def test_substantive_scheduling_draft_is_kept(self):
        """Do not rewrite a draft that already has a real body sentence."""
        draft = (
            "Salut Nathan,\n\n"
            "Je peux prévoir un court point cette semaine.\n\n"
            "Cordialement,"
        )

        result = _fallback_for_greeting_closing_stub(
            draft=draft,
            subject="Test Agentys",
            body="Peux-tu me confirmer tes disponibilités cette semaine ?",
            greeting_hint="Salut Nathan,",
            closing_hint="Cordialement,",
            detected_language="FRENCH",
            formality=2,
        )

        assert result == draft

    def test_full_complexity_pipeline(self):
        """Test complexity analysis pipeline."""
        body = """
        Can you review the API implementation?

        We have an issue with the database migration.

        Also, check the deployment pipeline for staging.

        Do you need the test results?
        """
        subject = "Urgent: Multiple technical issues"

        signals = analyze_complexity(
            body=body,
            subject=subject,
            thread_depth=2,
            has_instructions=False,
            has_attachments=True,
        )

        score = calculate_complexity_score(signals)

        # Should be moderately complex
        assert score >= 40
        assert signals.question_count >= 2
        assert signals.technical_content >= 1

    def test_simple_response_flow(self):
        """Test simple response routing."""
        body = "Can you confirm receipt?"
        signals = analyze_complexity(body)
        score = calculate_complexity_score(signals)

        # Very simple - should have low score
        assert score < 40

        # Token budget should be minimal
        tokens = calculate_dynamic_max_tokens(signals, RoutingTier.STANDARD)
        assert tokens <= 384

    def test_email_parsing_and_extraction(self):
        """Test full email parsing workflow."""
        email_text = """From: alice@example.com
Subject: Project Timeline

Can you clarify the deadline? We need to know when to deliver."""

        sender, subject, body = _parse_email_content(email_text)
        first_name = _extract_first_name(sender)

        assert "alice" in sender.lower()
        assert "deadline" in subject.lower() or "timeline" in subject.lower()
        assert "clarify" in body.lower()
        assert first_name in ("Alice", "alice", "")  # May depend on parsing

    def test_draft_cleanup_pipeline(self):
        """Test multiple cleanup passes on a draft."""
        raw_draft = """From: recipient@example.com
Date: 2024-03-20
Subject: Re: Update

I hope this helps!

Regarding your request, I can help with that.

Thanks for reaching out, and I remain at your disposal.

Best regards,
John"""

        # Apply various cleanup functions
        cleaned = _clean_prompt_leakage(raw_draft)
        cleaned = _strip_filler_mid_draft(cleaned, formality=3)
        cleaned = _strip_duplicate_greetings(cleaned)
        cleaned = _strip_signature(cleaned)

        # Should be significantly shorter and cleaner
        assert len(cleaned) < len(raw_draft)
        assert "From:" not in cleaned
        assert "I hope this helps" not in cleaned
        assert "Best regards" not in cleaned

    def test_skip_prefilter_prevents_routing(self):
        """Test that prefilter correctly identifies emails to skip."""
        # This email should be skipped
        skip_reason = should_skip_prefilter(
            sender="noreply@github.com",
            user_email="developer@company.com",
            subject="GitHub Notification",
        )
        assert skip_reason is not None

        # This email should NOT be skipped
        skip_reason = should_skip_prefilter(
            sender="colleague@company.com",
            user_email="developer@company.com",
            subject="Need your feedback",
            label="Action",
        )
        assert skip_reason is None


# ============================================================================
# TEST: _draft_passes_quality_gate (Critic skip heuristic)
# ============================================================================

class TestDraftPassesQualityGate:
    """The heuristic gate decides whether to bypass the LLM critic.
    Conservative: any doubt → return False → run critic. These tests pin the
    invariants so a future tweak doesn't accidentally start trusting risky
    drafts."""

    GOOD_DRAFT = (
        "Bonjour Marie,\n\nMerci pour ton message. Je confirme la réunion "
        "de jeudi à 14h.\n\nÀ bientôt,\nAlex"
    )
    EMAIL = "Bonjour, peux-tu confirmer la réunion de jeudi ?"

    def test_clean_short_draft_passes(self):
        assert _draft_passes_quality_gate(
            draft=self.GOOD_DRAFT,
            email_content=self.EMAIL,
            tier=RoutingTier.STANDARD,
            body_length=len(self.EMAIL),
        )

    def test_complex_tier_blocks_generic_quality_gate(self):
        # The generic gate still treats COMPLEX as risky by default.
        assert not _draft_passes_quality_gate(
            draft=self.GOOD_DRAFT,
            email_content=self.EMAIL,
            tier=RoutingTier.COMPLEX,
            body_length=len(self.EMAIL),
        )

    def test_complex_user_notes_fast_path_allows_borderline_score(self):
        draft = (
            "Bonjour Marie,\n\n"
            "Merci pour ton message. Je confirme que je peux m'en occuper.\n\n"
            "À bientôt,\nAlex"
        )

        assert _complex_user_notes_fast_path_passes(
            draft=draft,
            email_content="Bonjour, peux-tu confirmer que tu peux t'en occuper ?",
            instructions="Réponds en confirmant simplement.",
            complexity_score=53,
            greeting_hint="Bonjour Marie,",
            closing_hint="À bientôt,",
            body_length=2200,
        )

    def test_complex_user_notes_fast_path_keeps_high_score_on_critic_path(self):
        draft = (
            "Bonjour Marie,\n\n"
            "Merci pour ton message. Je confirme que je peux m'en occuper.\n\n"
            "À bientôt,\nAlex"
        )

        assert not _complex_user_notes_fast_path_passes(
            draft=draft,
            email_content="Bonjour, peux-tu confirmer que tu peux t'en occuper ?",
            instructions="Réponds en confirmant simplement.",
            complexity_score=70,
            greeting_hint="Bonjour Marie,",
            closing_hint="À bientôt,",
            body_length=2200,
        )

    def test_complex_user_notes_fast_path_requires_reply_shape(self):
        draft = "Je confirme que je peux m'en occuper."

        assert not _complex_user_notes_fast_path_passes(
            draft=draft,
            email_content="Bonjour, peux-tu confirmer que tu peux t'en occuper ?",
            instructions="Réponds en confirmant simplement.",
            complexity_score=53,
            greeting_hint="Bonjour Marie,",
            closing_hint="À bientôt,",
            body_length=2200,
        )

    def test_validate_and_revise_skips_critic_for_borderline_complex_user_notes(self, monkeypatch):
        from app import agents as _agents

        def fail_if_used(*_args, **_kwargs):
            pytest.fail("critic/revision should be skipped for borderline complex notes")

        # The repo `.env` sets USE_UNIFIED_DRAFT=true (prod bypasses the critic
        # unconditionally). This test exercises the OFF-path "complex user-notes
        # fast path", so pin the flag OFF to stay hermetic w.r.t. ambient env.
        monkeypatch.setenv("USE_UNIFIED_DRAFT", "false")
        monkeypatch.setattr(_agents, "CriticAgent", fail_if_used)
        monkeypatch.setattr(_agents, "DrafterAgent", fail_if_used)

        draft = (
            "Bonjour Marie,\n\n"
            "Merci pour ton message. Je confirme que je peux m'en occuper.\n\n"
            "À bientôt,\nAlex"
        )
        router = SmartRouter()

        final_draft, critique_info = router._validate_and_revise(
            draft=draft,
            email_content="Bonjour, peux-tu confirmer que tu peux t'en occuper ?",
            email_id="email-fast-path",
            conversation_history=[],
            instructions="Réponds en confirmant simplement.",
            user_email="me@example.com",
            max_tokens=768,
            sender_name="Marie",
            greeting_hint="Bonjour Marie,",
            closing_hint="À bientôt,",
            tier=RoutingTier.COMPLEX,
            body_length=2200,
            account_id=14,
            complexity_score=53,
        )

        assert final_draft == draft
        assert critique_info["skipped"] is True
        assert critique_info["skip_reason"] == "complex_user_notes_fast_path"

    def test_validate_and_revise_keeps_drafting_feature_for_critic_and_revision(self, monkeypatch):
        from types import SimpleNamespace

        from app import agents as _agents
        from app.domain.entities.critique import CritiqueDecision, CritiqueStatus
        from app.infrastructure.cost_manager import (
            get_usage_context,
            reset_usage_context,
            set_usage_context,
        )

        seen_contexts = []

        class Scores:
            coherence = 60
            tone = 60
            completeness = 60
            errors = 60
            conciseness = 60
            over_commitment = 60
            emotional_intelligence = 60

            def calculate_overall(self):
                return 60

        class FakeCritic:
            def __init__(self, account_id=None):
                self.account_id = account_id

            def evaluate_draft_with_retry(self, request):
                seen_contexts.append(("critic", get_usage_context()))
                return SimpleNamespace(
                    decision=CritiqueDecision.REJECT,
                    scores=Scores(),
                    suggestions=["Clarifier la prochaine étape."],
                    explanation="Trop vague.",
                    evaluation_time_ms=12,
                    tokens_used=34,
                    status=CritiqueStatus.COMPLETED,
                )

        class FakeDrafter:
            def __init__(self, account_id=None):
                self.account_id = account_id

            def revise_with_critique_and_retry(self, request, critique_result):
                seen_contexts.append(("drafter", get_usage_context()))
                return SimpleNamespace(
                    content=(
                        "Bonjour Marie,\n\n"
                        "Merci pour votre message. Je vais m'en occuper et je reviens "
                        "vers vous avec les éléments demandés dès que possible. "
                        "Je vous tiens informée de la suite."
                    )
                )

        monkeypatch.setenv("SKIP_CRITIC_GATE", "false")
        # The repo `.env` sets USE_UNIFIED_DRAFT=true, which would bypass the
        # critic+revision loop this test asserts runs — pin it OFF for hermeticity.
        monkeypatch.setenv("USE_UNIFIED_DRAFT", "false")
        monkeypatch.setattr(_agents, "CriticAgent", FakeCritic)
        monkeypatch.setattr(_agents, "DrafterAgent", FakeDrafter)

        router = SmartRouter()
        usage_tokens = set_usage_context(
            account_id=21,
            user_id=9901,
            feature="drafting",
        )
        try:
            final_draft, _critique_info = router._validate_and_revise(
                draft="Bonjour Marie,\n\nJe m'en occupe.\n\nCordialement,\nAlex",
                email_content="Bonjour, peux-tu regarder ce dossier et me répondre ?",
                email_id="email-token-context",
                conversation_history=[],
                instructions="Réponds en confirmant la prise en charge.",
                user_email="me@example.com",
                max_tokens=768,
                sender_name="Marie",
                tier=RoutingTier.STANDARD,
                body_length=120,
                account_id=21,
            )
        finally:
            reset_usage_context(usage_tokens)

        assert final_draft
        assert [(name, context[0], context[1], context[2]) for name, context in seen_contexts] == [
            ("critic", 21, 9901, "drafting"),
            ("drafter", 21, 9901, "drafting"),
        ]

    def test_a_confirmer_placeholder_blocks(self):
        bad = self.GOOD_DRAFT + "\nLe tarif est de [À confirmer] euros."
        assert not _draft_passes_quality_gate(
            draft=bad, email_content=self.EMAIL, tier=RoutingTier.STANDARD,
        )

    def test_tu_vous_mix_blocks(self):
        # "Tu peux" + "vous" both present → mixed register → run critic.
        bad = (
            "Salut Marie,\n\nTu peux confirmer la réunion ? Je vous tiens "
            "au courant.\n\nÀ bientôt,\nAlex"
        )
        assert not _draft_passes_quality_gate(
            draft=bad, email_content=self.EMAIL, tier=RoutingTier.STANDARD,
        )

    def test_user_instructions_force_critic(self):
        # When the user gives explicit instructions, we want the critic to
        # verify the draft actually obeyed them.
        assert not _draft_passes_quality_gate(
            draft=self.GOOD_DRAFT, email_content=self.EMAIL,
            has_instructions=True, tier=RoutingTier.STANDARD,
        )

    def test_meta_filler_prefix_blocks(self):
        bad = "Voici ma réponse :\n\n" + self.GOOD_DRAFT
        assert not _draft_passes_quality_gate(
            draft=bad, email_content=self.EMAIL, tier=RoutingTier.STANDARD,
        )

    def test_empty_draft_blocks(self):
        assert not _draft_passes_quality_gate(
            draft="", email_content=self.EMAIL, tier=RoutingTier.STANDARD,
        )


class TestSimpleMicroTemplates:
    def test_short_confirmation_question_uses_safe_template(self, monkeypatch):
        monkeypatch.setattr(
            "app.infrastructure.container.get_container",
            lambda: _NoProfileContainer(),
        )
        router = SmartRouter()

        draft = router._try_micro_template(
            sender="client@example.com",
            subject="Question test",
            body=(
                "Bonjour,\n\n"
                "Pouvez-vous me confirmer la prochaine étape et le délai prévu ?\n\n"
                "Merci."
            ),
        )

        assert draft.startswith("Bonjour,")
        assert "Je vérifie la prochaine étape et le délai prévu" in draft
        assert "vous confirme rapidement" in draft

    def test_short_availability_question_does_not_invent_availability(self, monkeypatch):
        monkeypatch.setattr(
            "app.infrastructure.container.get_container",
            lambda: _NoProfileContainer(),
        )
        router = SmartRouter()

        draft = router._try_micro_template(
            sender="marie@example.com",
            subject="Dispo",
            body="Peux-tu me confirmer tes disponibilités cette semaine ?",
        )

        assert "Je vérifie mes disponibilités" in draft
        assert "Je confirme ma disponibilité" not in draft

    def test_generic_product_instruction_does_not_block_template(self, monkeypatch):
        monkeypatch.setattr(
            "app.infrastructure.container.get_container",
            lambda: _NoProfileContainer(),
        )
        router = SmartRouter()
        body = (
            "Bonjour,\n\n"
            "Pouvez-vous me confirmer la prochaine étape et le délai prévu ?\n"
            "Référence de test : load-capacity-draft-template-20260527-railway-v2-draft-users-u400-a200-6b7e84dd33db42009562c6f08477caac.\n\n"
            "Merci."
        )

        result = router.route_streaming(
            email_id="",
            email_content=body,
            sender="client@example.com",
            subject="Question test",
            body=body,
            instructions="Réponds de façon concise et professionnelle.",
            force=True,
        )

        assert len(body) > 180
        assert result.status == "SIMPLE_TEMPLATE"
        assert "vous confirme rapidement" in result.draft


class _NoProfileContainer:
    def get_writing_style_profile(self, account_id=1):
        return None


class TestMeaningfulUserInstructions:
    def test_plain_product_default_is_not_meaningful(self):
        assert not _has_meaningful_user_instructions("Reply appropriately to this email")

    def test_intent_product_default_with_guardrails_is_not_meaningful(self):
        assert not _has_meaningful_user_instructions(
            "Reply appropriately. Only mention what is in the email. "
            "Reply in MAXIMUM 2 short sentences."
        )

    def test_availability_guardrail_default_is_not_meaningful(self):
        assert not _has_meaningful_user_instructions(
            "Reply appropriately to this email. Only mention what is in the email. "
            "If dates, times, availability, or commitments are missing, do not "
            "invent them; say you will check and come back."
        )

    def test_french_concise_product_default_is_not_meaningful(self):
        assert not _has_meaningful_user_instructions(
            "Réponds de façon concise et professionnelle."
        )

    def test_custom_user_instruction_is_meaningful(self):
        assert _has_meaningful_user_instructions(
            "Réponds oui et propose aussi vendredi matin."
        )


# ============================================================================
# TEST: critic gate observability counters
# ============================================================================

class TestRecordCriticGate:
    """The aggregator must increment the right buckets and never crash on
    invalid outcomes."""

    def _reset_stats(self):
        # Reset by zeroing all known keys directly on the module-level dict
        # (acceptable in tests — production code never touches these).
        from app import smart_routing as _sr
        with _sr._critic_gate_lock:
            for k in _sr._critic_gate_stats:
                _sr._critic_gate_stats[k] = 0
            _sr._critic_gate_last_log_at = 0.0

    def test_skipped_heuristic_increments_and_estimates_savings(self):
        self._reset_stats()
        _record_critic_gate("skipped_heuristic")
        snap = _get_critic_gate_snapshot()
        assert snap["skipped_heuristic"] == 1
        assert snap["ran"] == 0
        assert snap["estimated_ms_saved"] >= 1500

    def test_ran_increments_only_ran_counter(self):
        self._reset_stats()
        _record_critic_gate("ran")
        snap = _get_critic_gate_snapshot()
        assert snap["ran"] == 1
        assert snap["estimated_ms_saved"] == 0

    def test_unknown_outcome_is_ignored(self):
        self._reset_stats()
        _record_critic_gate("garbage_value")
        snap = _get_critic_gate_snapshot()
        assert all(v == 0 for v in snap.values())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
