# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for app.services.faq_scanner — multi-tier URL extraction + document parsing."""

import json
from unittest.mock import MagicMock, patch

from app.services.faq_scanner import (
    FaqEntry,
    ScanResult,
    _deduplicate,
    _detect_hidden_tabs,
    _extract_balanced_json,
    _extract_faq_from_document_text,
    _extract_html_patterns,
    _extract_js_data_stores,
    _extract_schema_org,
    _extract_with_llm,
    _clean_html_to_text,
    _find_faq_in_json,
    _get_extension,
    _parse_llm_faq_response,
    _try_extract_faq_array,
)


# ── Tier 1: Schema.org FAQPage ──────────────────────────────────────────────

class TestSchemaOrgExtraction:
    """Tests for Schema.org FAQPage JSON-LD extraction."""

    def test_standard_faq_page(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": "What is Agentys?",
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": "Agentys is an AI email assistant."
                    }
                },
                {
                    "@type": "Question",
                    "name": "How much does it cost?",
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": "It starts at $10/month."
                    }
                }
            ]
        }
        </script>
        </head><body></body></html>
        """
        entries = _extract_schema_org(html)
        assert len(entries) == 2
        assert entries[0].question == "What is Agentys?"
        assert entries[0].answer == "Agentys is an AI email assistant."
        assert entries[0].source == "schema.org"
        assert entries[1].question == "How much does it cost?"

    def test_graph_format(self):
        html = """
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "FAQPage",
                    "mainEntity": [
                        {
                            "@type": "Question",
                            "name": "Is it secure?",
                            "acceptedAnswer": {
                                "@type": "Answer",
                                "text": "Yes, all data is encrypted."
                            }
                        }
                    ]
                }
            ]
        }
        </script>
        """
        entries = _extract_schema_org(html)
        assert len(entries) == 1
        assert entries[0].question == "Is it secure?"

    def test_html_in_answer(self):
        html = """
        <script type="application/ld+json">
        {
            "@type": "FAQPage",
            "mainEntity": [{
                "@type": "Question",
                "name": "What formats?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "<p>We support <strong>PDF</strong>, TXT, and DOCX.</p>"
                }
            }]
        }
        </script>
        """
        entries = _extract_schema_org(html)
        assert len(entries) == 1
        assert "<strong>" not in entries[0].answer
        assert "PDF" in entries[0].answer

    def test_no_faq_page(self):
        html = """
        <script type="application/ld+json">
        {"@type": "WebPage", "name": "About us"}
        </script>
        """
        entries = _extract_schema_org(html)
        assert entries == []

    def test_invalid_json(self):
        html = '<script type="application/ld+json">not valid json{</script>'
        entries = _extract_schema_org(html)
        assert entries == []

    def test_empty_html(self):
        entries = _extract_schema_org("")
        assert entries == []


class TestLLMAttribution:
    """LLM fallback scans must be identifiable in token_usage_log."""

    def _patch_usage_recording_llm(self, captured: list):
        class _UsageRecordingLLM:
            def complete(self, **_kwargs):
                from app.infrastructure.token_usage_writer import record_usage

                record_usage(
                    model="claude-haiku-4-5-20251001",
                    input_tokens=250,
                    output_tokens=40,
                )
                return MagicMock(
                    content='[{"question": "Q?", "answer": "Réponse assez longue."}]'
                )

        return (
            patch(
                "app.infrastructure.container.get_container",
                return_value=MagicMock(llm_background=_UsageRecordingLLM()),
            ),
            patch(
                "app.infrastructure.token_usage_writer.enqueue",
                side_effect=lambda record: captured.append(record),
            ),
        )

    def test_url_llm_extraction_records_feature(self):
        captured = []
        container_patch, enqueue_patch = self._patch_usage_recording_llm(captured)

        with container_patch, enqueue_patch:
            entries = _extract_with_llm("Texte de FAQ " * 50)

        assert len(entries) == 1
        assert len(captured) == 1
        assert captured[0].agent == "faq_scan_url"
        assert captured[0].feature == "knowledge_scan"

    def test_document_llm_extraction_records_feature(self):
        captured = []
        container_patch, enqueue_patch = self._patch_usage_recording_llm(captured)

        with container_patch, enqueue_patch:
            entries = _extract_faq_from_document_text("Document FAQ " * 50)

        assert len(entries) == 1
        assert len(captured) == 1
        assert captured[0].agent == "faq_scan_document"
        assert captured[0].feature == "knowledge_scan"


# ── Tier 1.5: Inline JS data stores ─────────────────────────────────────────

class TestTryExtractFaqArray:
    """Unit tests for the FAQ array detection heuristic."""

    def test_hard_question_hard_answer(self):
        items = [
            {"question": "What is it?", "answer": "It is a tool."},
            {"question": "How much?", "answer": "Ten dollars per month."},
        ]
        entries = _try_extract_faq_array(items)
        assert len(entries) == 2
        assert entries[0].question == "What is it?"
        assert entries[0].source == "js_store"

    def test_q_hard_a_soft(self):
        """Hard Q key + soft A key should still be extracted."""
        items = [
            {"question": "How do I sign up?", "description": "Visit our website and click Sign Up."},
            {"question": "Is there a trial?", "description": "Yes, 14 days free."},
        ]
        entries = _try_extract_faq_array(items)
        assert len(entries) == 2

    def test_q_soft_a_hard(self):
        """Soft Q key + hard A key should be extracted."""
        items = [
            {"title": "Can I cancel?", "answer": "Yes, cancel any time from your dashboard."},
            {"title": "Any setup fee?", "answer": "No setup fees, ever."},
        ]
        entries = _try_extract_faq_array(items)
        assert len(entries) == 2

    def test_both_soft_keys_rejected(self):
        """Both-soft-key arrays must NOT be extracted (avoids blog/product lists)."""
        items = [
            {"title": "Blog post 1", "description": "Short intro."},
            {"title": "Blog post 2", "description": "Another intro."},
        ]
        entries = _try_extract_faq_array(items)
        assert entries == []

    def test_minimum_two_items(self):
        items = [{"question": "Only one?", "answer": "Rejected."}]
        entries = _try_extract_faq_array(items)
        assert entries == []

    def test_non_dict_items_rejected(self):
        items = ["string1", "string2", "string3"]
        entries = _try_extract_faq_array(items)
        assert entries == []

    def test_low_hit_rate_rejected(self):
        """If fewer than 50 % of items have both Q and A, reject the array."""
        items = [
            {"question": "Q1?", "answer": "A1."},
            {"name": "no answer here"},
            {"name": "still no answer"},
            {"name": "also no answer"},
        ]
        entries = _try_extract_faq_array(items)
        assert entries == []

    def test_html_stripped_from_answer(self):
        items = [
            {"question": "Format?", "answer": "<p>We support <b>PDF</b> and TXT.</p>"},
            {"question": "Secure?", "answer": "<em>Yes</em>, fully encrypted."},
        ]
        entries = _try_extract_faq_array(items)
        assert len(entries) == 2
        assert "<p>" not in entries[0].answer
        assert "PDF" in entries[0].answer

    def test_short_answer_excluded(self):
        items = [
            {"question": "Good?", "answer": "Yes"},  # too short (< 5 chars)
            {"question": "Better?", "answer": "Absolutely, this is a full answer."},
        ]
        entries = _try_extract_faq_array(items)
        # Short answer filtered but hit-rate might drop — depends on sample
        # What matters: entries with len(a) < 5 are not in results
        for e in entries:
            assert len(e.answer) >= 5


class TestFindFaqInJson:
    """Tests for the recursive JSON walker."""

    def test_top_level_array(self):
        data = [
            {"question": "Q1?", "answer": "A1 long enough."},
            {"question": "Q2?", "answer": "A2 long enough."},
        ]
        entries = _find_faq_in_json(data)
        assert len(entries) == 2

    def test_deeply_nested(self):
        """FAQ array nested 4 levels deep must be found."""
        data = {
            "page": "/faq",
            "props": {
                "pageProps": {
                    "content": {
                        "faqs": [
                            {"question": "Deep Q1?", "answer": "Deep answer one."},
                            {"question": "Deep Q2?", "answer": "Deep answer two."},
                        ]
                    }
                }
            }
        }
        entries = _find_faq_in_json(data)
        assert len(entries) == 2
        assert entries[0].question == "Deep Q1?"

    def test_multiple_tabs_all_captured(self):
        """FAQ arrays across multiple tab objects must all be extracted."""
        data = {
            "tabs": [
                {
                    "id": "about",
                    "faqs": [
                        {"question": "About Q1?", "answer": "About answer one."},
                        {"question": "About Q2?", "answer": "About answer two."},
                    ]
                },
                {
                    "id": "pricing",
                    "faqs": [
                        {"question": "Price Q1?", "answer": "Pricing answer one."},
                        {"question": "Price Q2?", "answer": "Pricing answer two."},
                    ]
                },
            ]
        }
        entries = _find_faq_in_json(data)
        assert len(entries) == 4
        questions = [e.question for e in entries]
        assert "About Q1?" in questions
        assert "About Q2?" in questions
        assert "Price Q1?" in questions
        assert "Price Q2?" in questions

    def test_non_faq_content_ignored(self):
        data = {
            "blogPosts": [
                {"title": "Post 1", "description": "Intro."},
                {"title": "Post 2", "description": "Intro."},
            ],
            "users": [{"name": "Alice"}, {"name": "Bob"}],
        }
        entries = _find_faq_in_json(data)
        assert entries == []

    def test_depth_limit_respected(self):
        """Extremely deep nesting should not raise RecursionError."""
        # Build a 20-level deep dict
        deep = {"question": "Bottom Q?", "answer": "Bottom answer."}
        for _ in range(20):
            deep = {"nested": [deep]}
        # Should not crash and may or may not find the FAQ (depth limit at 15)
        entries = _find_faq_in_json(deep)
        # No assertion on count — just must not raise
        assert isinstance(entries, list)


class TestExtractBalancedJson:
    """Tests for the balanced bracket extractor."""

    def test_simple_object(self):
        text = 'var x = {"key": "val"};'
        result = _extract_balanced_json(text, 8)
        assert result == '{"key": "val"}'

    def test_simple_array(self):
        text = 'var x = [1, 2, 3];'
        result = _extract_balanced_json(text, 8)
        assert result == '[1, 2, 3]'

    def test_nested_object(self):
        text = 'window.__STATE__ = {"a": {"b": [1, 2]}};'
        idx = text.index('{')
        result = _extract_balanced_json(text, idx)
        assert result == '{"a": {"b": [1, 2]}}'

    def test_string_with_braces_inside(self):
        """Braces inside string literals must not affect depth counting."""
        text = 'x = {"key": "value with } brace"};'
        idx = text.index('{')
        result = _extract_balanced_json(text, idx)
        assert result == '{"key": "value with } brace"}'
        parsed = json.loads(result)
        assert parsed["key"] == "value with } brace"

    def test_escaped_quote_in_string(self):
        text = 'x = {"key": "say \\"hello\\" world"};'
        idx = text.index('{')
        result = _extract_balanced_json(text, idx)
        assert result is not None
        parsed = json.loads(result)
        assert 'hello' in parsed["key"]

    def test_wrong_start_char(self):
        text = 'var x = "not json";'
        result = _extract_balanced_json(text, 8)
        assert result is None

    def test_unclosed_object(self):
        text = '{"open": "but never closed"'
        result = _extract_balanced_json(text, 0)
        assert result is None

    def test_out_of_bounds_start(self):
        result = _extract_balanced_json("abc", 100)
        assert result is None


class TestExtractJsDataStores:
    """Integration tests for the JS data store extractor."""

    def test_next_data_tag(self):
        """FAQ extracted from <script id="__NEXT_DATA__" type="application/json">."""
        faq_data = {
            "page": "/faq",
            "props": {
                "pageProps": {
                    "faqs": [
                        {"question": "How do I install?", "answer": "Download the installer from our website."},
                        {"question": "Is it free?", "answer": "We offer a 14-day free trial."},
                    ]
                }
            }
        }
        html = f"""
        <html><head>
        <script id="__NEXT_DATA__" type="application/json">
        {json.dumps(faq_data)}
        </script>
        </head><body><p>FAQ page</p></body></html>
        """
        entries = _extract_js_data_stores(html)
        assert len(entries) == 2
        assert entries[0].question == "How do I install?"
        assert entries[0].source == "js_store"

    def test_next_data_multi_tab(self):
        """FAQ from multiple tab objects inside __NEXT_DATA__ all captured."""
        faq_data = {
            "props": {
                "pageProps": {
                    "tabs": [
                        {
                            "id": "about",
                            "label": "About",
                            "items": [
                                {"question": "About Q1?", "answer": "About answer here."},
                                {"question": "About Q2?", "answer": "About answer two."},
                            ]
                        },
                        {
                            "id": "security",
                            "label": "Security",
                            "items": [
                                {"question": "Security Q?", "answer": "Security answer here."},
                                {"question": "Backup Q?", "answer": "Backup answer here."}
                            ]
                        }
                    ]
                }
            }
        }
        html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(faq_data)}</script>'
        entries = _extract_js_data_stores(html)
        assert len(entries) == 4
        questions = [e.question for e in entries]
        assert "About Q1?" in questions
        assert "Security Q?" in questions
        assert "Backup Q?" in questions

    def test_window_assignment(self):
        """FAQ from window.__APP__ = {...} assignment extracted correctly."""
        faq_list = [
            {"question": "What is the refund policy?", "answer": "Full refund within 30 days."},
            {"question": "Support hours?", "answer": "Monday to Friday, 9am to 5pm."},
        ]
        script_content = f'window.__APP__ = {{"faqData": {json.dumps(faq_list)}}};'
        html = f"<html><body><script>{script_content}</script></body></html>"
        entries = _extract_js_data_stores(html)
        assert len(entries) == 2

    def test_no_faq_data(self):
        """Pages without FAQ JSON yield empty results."""
        html = """
        <html><head>
        <script id="__NEXT_DATA__" type="application/json">
        {"page": "/about", "props": {"pageProps": {"title": "About us"}}}
        </script>
        </head></html>
        """
        entries = _extract_js_data_stores(html)
        assert entries == []

    def test_invalid_json_silently_ignored(self):
        html = '<script id="__NEXT_DATA__" type="application/json">not valid json{</script>'
        entries = _extract_js_data_stores(html)
        assert entries == []

    def test_deduplicates_across_window_scripts(self):
        """Same questions from two different window assignments are only kept once."""
        faq = [
            {"question": "Is it free?", "answer": "Yes, 14-day free trial."},
            {"question": "Can I cancel?", "answer": "Yes, cancel any time."},
        ]
        html = f"""<html><body>
        <script>window.__FAQ__ = {json.dumps(faq)};</script>
        <script>window.__ALSO_FAQ__ = {json.dumps(faq)};</script>
        </body></html>"""
        entries = _extract_js_data_stores(html)
        assert len(entries) == 2


# ── Tab detection ─────────────────────────────────────────────────────────────

class TestDetectHiddenTabs:
    """Tests for the hidden tab detector."""

    def test_aria_selected_false(self):
        html = """
        <div role="tablist">
            <button role="tab" aria-selected="true">About</button>
            <button role="tab" aria-selected="false">Setup &amp; Security</button>
            <button role="tab" aria-selected="false">Pricing &amp; Plans</button>
        </div>
        """
        tabs = _detect_hidden_tabs(html)
        assert "Setup & Security" in tabs
        assert "Pricing & Plans" in tabs
        assert "About" not in tabs

    def test_tablist_first_child_active(self):
        """When no aria-selected attrs, assume first child is active."""
        html = """
        <nav role="tablist">
            <a>Home</a>
            <a>Docs</a>
            <a>Pricing</a>
        </nav>
        """
        tabs = _detect_hidden_tabs(html)
        assert "Docs" in tabs
        assert "Pricing" in tabs
        assert "Home" not in tabs

    def test_no_tabs(self):
        html = "<html><body><p>No tabs here.</p></body></html>"
        tabs = _detect_hidden_tabs(html)
        assert tabs == []

    def test_deduplicates_tab_names(self):
        html = """
        <div role="tablist">
            <button role="tab" aria-selected="false">Pricing</button>
        </div>
        <div role="tablist">
            <button role="tab" aria-selected="false">Pricing</button>
        </div>
        """
        tabs = _detect_hidden_tabs(html)
        assert tabs.count("Pricing") == 1


# ── Deduplication ─────────────────────────────────────────────────────────────

class TestDeduplicate:
    """Tests for cross-tier deduplication."""

    def test_removes_exact_duplicates(self):
        entries = [
            FaqEntry("What is Agentys?", "An AI assistant.", "schema.org"),
            FaqEntry("What is Agentys?", "An AI assistant.", "js_store"),
        ]
        unique = _deduplicate(entries)
        assert len(unique) == 1
        assert unique[0].source == "schema.org"  # first occurrence kept

    def test_keeps_distinct_questions(self):
        entries = [
            FaqEntry("What is Agentys?", "An AI assistant.", "schema.org"),
            FaqEntry("How much does it cost?", "Ten dollars.", "js_store"),
        ]
        unique = _deduplicate(entries)
        assert len(unique) == 2

    def test_normalizes_punctuation(self):
        """Questions differing only in punctuation/case are deduplicated."""
        entries = [
            FaqEntry("What is Agentys?", "A1.", "schema.org"),
            FaqEntry("What is Agentys", "A2.", "js_store"),  # no question mark
            FaqEntry("WHAT IS AGENTYS?", "A3.", "html"),    # uppercase
        ]
        unique = _deduplicate(entries)
        assert len(unique) == 1

    def test_empty_list(self):
        assert _deduplicate([]) == []


# ── Tier 2: HTML pattern matching ────────────────────────────────────────────

class TestHtmlPatternExtraction:
    """Tests for HTML pattern-based FAQ extraction."""

    def test_details_summary(self):
        html = """
        <html><body>
        <details>
            <summary>How do I install?</summary>
            <p>Download from our website and run the installer. It takes about 2 minutes.</p>
        </details>
        <details>
            <summary>Can I use it offline?</summary>
            <p>Yes, the desktop app works offline. Sync happens when you reconnect.</p>
        </details>
        </body></html>
        """
        entries = _extract_html_patterns(html)
        assert len(entries) == 2
        assert entries[0].question == "How do I install?"
        assert "installer" in entries[0].answer
        assert entries[0].source == "html"

    def test_faq_heading_with_subheadings(self):
        html = """
        <html><body>
        <h2>Frequently Asked Questions</h2>
        <h3>What is the return policy?</h3>
        <p>You can return within 30 days for a full refund.</p>
        <h3>Do you ship internationally?</h3>
        <p>Yes, we ship to over 50 countries worldwide.</p>
        <p>Shipping times vary by destination.</p>
        </body></html>
        """
        entries = _extract_html_patterns(html)
        assert len(entries) == 2
        assert entries[0].question == "What is the return policy?"
        assert "30 days" in entries[0].answer
        assert entries[1].question == "Do you ship internationally?"
        assert "50 countries" in entries[1].answer

    def test_french_faq_heading(self):
        html = """
        <html><body>
        <h2>Questions fréquentes</h2>
        <h3>Comment payer ?</h3>
        <p>Par carte bancaire ou virement. Les paiements sont sécurisés.</p>
        </body></html>
        """
        entries = _extract_html_patterns(html)
        assert len(entries) == 1
        assert entries[0].question == "Comment payer ?"

    def test_no_faq_content(self):
        html = """
        <html><body>
        <h1>About Us</h1>
        <p>We are a software company.</p>
        </body></html>
        """
        entries = _extract_html_patterns(html)
        assert entries == []


# ── HTML cleaning ────────────────────────────────────────────────────────────

class TestHtmlCleaning:

    def test_strips_scripts_and_nav(self):
        html = """
        <html><head><script>var x=1;</script></head>
        <body><nav>Menu</nav><main><p>Content here</p></main><footer>Footer</footer></body>
        </html>
        """
        text = _clean_html_to_text(html)
        assert "var x" not in text
        assert "Menu" not in text
        assert "Footer" not in text
        assert "Content here" in text

    def test_collapses_whitespace(self):
        html = "<p>Line 1</p><p></p><p></p><p></p><p>Line 2</p>"
        text = _clean_html_to_text(html)
        assert "\n\n\n" not in text
        assert "Line 1" in text
        assert "Line 2" in text


# ── LLM response parsing ────────────────────────────────────────────────────

class TestLlmResponseParsing:

    def test_parses_json_array(self):
        content = json.dumps([
            {"question": "Q1?", "answer": "Answer 1"},
            {"question": "Q2?", "answer": "Answer 2"},
        ])
        entries = _parse_llm_faq_response(content)
        assert len(entries) == 2
        assert entries[0].question == "Q1?"
        assert entries[0].source == "llm"

    def test_parses_wrapped_object(self):
        content = json.dumps({"faq": [
            {"question": "Q1?", "answer": "Answer 1"},
        ]})
        entries = _parse_llm_faq_response(content)
        assert len(entries) == 1

    def test_filters_short_answers(self):
        content = json.dumps([
            {"question": "Good?", "answer": "Yes, this is a proper answer with enough content."},
            {"question": "Bad?", "answer": "No"},
        ])
        entries = _parse_llm_faq_response(content)
        assert len(entries) == 1
        assert entries[0].question == "Good?"

    def test_empty_response(self):
        entries = _parse_llm_faq_response("[]")
        assert entries == []

    def test_custom_source(self):
        content = json.dumps([{"question": "Q?", "answer": "From a document."}])
        entries = _parse_llm_faq_response(content, source="document")
        assert entries[0].source == "document"


# ── Utilities ────────────────────────────────────────────────────────────────

class TestUtilities:

    def test_get_extension(self):
        assert _get_extension("file.pdf") == ".pdf"
        assert _get_extension("doc.faq.txt") == ".txt"
        assert _get_extension("noext") == ""
        assert _get_extension("archive.tar.gz") == ".gz"

    def test_scan_result_to_dict(self):
        result = ScanResult(
            faq=[FaqEntry(question="Q?", answer="A.", source="schema.org")],
            extraction_tier="schema.org",
            source_url="https://example.com/faq",
        )
        d = result.to_dict()
        assert d["extraction_tier"] == "schema.org"
        assert len(d["faq"]) == 1
        assert d["faq"][0]["question"] == "Q?"
        assert d["error"] is None
        assert d["hidden_tabs"] == []

    def test_scan_result_with_hidden_tabs(self):
        result = ScanResult(
            faq=[FaqEntry(question="Q?", answer="A.", source="schema.org")],
            extraction_tier="schema.org",
            source_url="https://example.com/faq",
            hidden_tabs=["Setup & Security", "Pricing & Plans"],
        )
        d = result.to_dict()
        assert d["hidden_tabs"] == ["Setup & Security", "Pricing & Plans"]

    def test_scan_result_error(self):
        result = ScanResult(error="Page not found", source_url="https://bad.url")
        d = result.to_dict()
        assert d["error"] == "Page not found"
        assert d["faq"] == []
        assert d["hidden_tabs"] == []

    def test_scan_result_composite_tier(self):
        """Composite tier label from merged results serialises correctly."""
        result = ScanResult(
            faq=[FaqEntry("Q?", "A.", "schema.org"), FaqEntry("Q2?", "A2.", "js_store")],
            extraction_tier="schema.org+js_store",
            source_url="https://example.com/faq",
        )
        d = result.to_dict()
        assert d["extraction_tier"] == "schema.org+js_store"

    def test_faq_entry_to_dict(self):
        entry = FaqEntry(question="Q?", answer="A.", source="html")
        d = entry.to_dict()
        assert d == {"question": "Q?", "answer": "A.", "source": "html"}

    def test_faq_entry_js_store_source(self):
        entry = FaqEntry(question="Q?", answer="A.", source="js_store")
        assert entry.to_dict()["source"] == "js_store"
