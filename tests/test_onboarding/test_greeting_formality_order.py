"""Regression: onboarding must put the FORMAL greeting/closing in slot [0].

ProfileAgent emits greeting_styles/closing_styles keyed by formality
(formal_fr / casual_fr / semi_formal_fr / *_en). Downstream consumers
(smart_routing._compute_greeting_hint, the Default Writing Style panel) read
preferred_greetings[0] as FORMAL and [1] as CASUAL. The old flatten took
dict.values() in insertion order, and the prompt example lists casual_fr first,
so "Salut {first_name}," leaked into the formal slot. These tests pin the
formality-keyed ordering.
"""
from app.onboarding.manager import _order_styles_by_formality


def test_formal_greeting_wins_slot_zero_over_casual_emitted_first():
    # casual_fr deliberately emitted FIRST (the prompt's own example order).
    styles = {
        "casual_fr": "Salut {first_name},",
        "semi_formal_fr": "Bonjour {first_name},",
        "formal_fr": "Bonjour Madame {last_name},",
    }
    ordered = _order_styles_by_formality(styles, "fr")
    assert ordered[0] == "Bonjour Madame {last_name},"   # formal → slot 0
    assert ordered[1] == "Salut {first_name},"           # casual → slot 1
    assert ordered[0] != "Salut {first_name},"           # the bug must not recur


def test_semi_formal_fills_formal_slot_when_no_strict_formal():
    styles = {
        "casual_fr": "Salut {first_name},",
        "semi_formal_fr": "Bonjour {first_name},",
    }
    ordered = _order_styles_by_formality(styles, "fr")
    assert ordered[0] == "Bonjour {first_name},"  # semi-formal is the most formal here
    assert ordered[1] == "Salut {first_name},"


def test_closings_follow_the_same_formal_first_ordering():
    styles = {
        "casual_fr": "(no closing or just name)",
        "formal_fr": "Cordialement,",
        "semi_formal_fr": "Merci,",
    }
    ordered = _order_styles_by_formality(styles, "fr")
    assert ordered[0] == "Cordialement,"
    # Placeholder "no closing" values are filtered; the next usable register
    # should become the casual slot rather than preserving LLM no-signal text.
    assert ordered[1] == "Merci,"
    assert "(no closing or just name)" not in ordered


def test_primary_language_drives_which_formal_greeting_leads():
    styles = {
        "formal_fr": "Bonjour Madame {last_name},",
        "formal_en": "Dear {last_name},",
        "casual_en": "Hey {first_name},",
    }
    ordered = _order_styles_by_formality(styles, "en")
    assert ordered[0] == "Dear {last_name},"   # en primary → en formal leads
    assert ordered[1] == "Hey {first_name},"


def test_duplicate_values_are_deduped():
    styles = {
        "formal_fr": "Cordialement,",
        "semi_formal_fr": "Cordialement,",  # same value under another key
        "casual_fr": "A+",
    }
    ordered = _order_styles_by_formality(styles, "fr")
    assert ordered == ["Cordialement,", "A+"]


def test_empty_and_malformed_inputs_return_empty_list():
    assert _order_styles_by_formality({}, "fr") == []
    assert _order_styles_by_formality(None, "fr") == []
    assert _order_styles_by_formality({"casual_fr": ""}, "fr") == []  # empty value skipped


def test_handles_language_enum_primary_lang_gracefully():
    class _Lang:
        value = "en"
    styles = {"formal_en": "Dear {last_name},", "casual_en": "Hey {first_name},"}
    ordered = _order_styles_by_formality(styles, _Lang())
    assert ordered[0] == "Dear {last_name},"
