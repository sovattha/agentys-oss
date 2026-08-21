# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Contract tests between the Python onboarding agent outputs and the
frontend TypeScript interfaces consumed by LearningInsights / PillarStyle.

Motivation: the 2026-04-20 audit caught a silent drift where
ProfileAgent produced ``tone.greeting_styles`` (plural dict) while the
frontend expected ``tone.greeting_style`` (singular string). The bug
shipped unnoticed because nothing asserted the field names were
consistent across the stack. These tests fail loudly on any future
drift — add a field to the prompt / dataclass, update TS, or update the
EXPECTED_* sets here.

Strategy: parse ``agentys-app/src/types/onboarding.ts`` with a simple
regex to extract interface field names, then compare against the
dataclass and a sanitized sample agent output. No ts-node / Node
dependency — plain text extraction keeps this CI-cheap.

pytest tests/test_onboarding/test_schema_contract.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
TS_TYPES = REPO_ROOT / "agentys-app" / "src" / "types" / "onboarding.ts"


# --- Ground truth: fields the backend MUST produce so the UI renders ---
# Keep aligned with prompts/profile.txt + schemas.py + types/onboarding.ts.

EXPECTED_PROFILE_FIELDS = {
    "user_email",
    "user_name",
    "preferred_name",
    "profession",
    "profession_confirmed",
    "signature",
    "tone",
    "languages",
}

EXPECTED_TONE_FIELDS = {
    "default_tone",
    "addressing",
    "greeting_style",
    "closing_style",
    "greeting_styles",
    "closing_styles",
    "uses_emoji",
    "average_response_length",
}

EXPECTED_CONTACT_RULE_FIELDS = {
    "contact_email",
    "tone",
    "language",
    "addressing",
    "greeting",
    "closing",
}


# --- Minimal TS interface parser (regex-based, no Node required) -------

_INTERFACE_BODY_RE = re.compile(
    r"export\s+interface\s+(?P<name>\w+)\s*\{(?P<body>[^}]*)\}",
    re.DOTALL,
)
_FIELD_NAME_RE = re.compile(r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\??\s*:")


def _parse_ts_interfaces(source: str) -> dict[str, set[str]]:
    """Extract field names from ``export interface Foo { ... }`` blocks.

    Handles optional ``?`` markers. Ignores nested object types inside
    JSDoc or comments — sufficient for our flat interfaces.
    """
    interfaces: dict[str, set[str]] = {}
    for match in _INTERFACE_BODY_RE.finditer(source):
        name = match.group("name")
        body = match.group("body")
        fields: set[str] = set()
        for raw_line in body.splitlines():
            # Strip line / block comments so ``// comment`` does not leak in.
            line = re.sub(r"//.*$", "", raw_line)
            line = re.sub(r"/\*.*?\*/", "", line)
            field_match = _FIELD_NAME_RE.match(line)
            if field_match:
                fields.add(field_match.group("name"))
        interfaces[name] = fields
    return interfaces


@pytest.fixture(scope="module")
def ts_interfaces() -> dict[str, set[str]]:
    assert TS_TYPES.is_file(), f"Missing TS types file at {TS_TYPES}"
    return _parse_ts_interfaces(TS_TYPES.read_text(encoding="utf-8"))


# --- Interface ↔ expected ground truth ---------------------------------

def test_user_profile_interface_has_all_expected_fields(ts_interfaces):
    ts_fields = ts_interfaces.get("UserProfile", set())
    missing = EXPECTED_PROFILE_FIELDS - ts_fields
    assert not missing, (
        f"UserProfile TS interface is missing fields required by backend: "
        f"{sorted(missing)}. Update agentys-app/src/types/onboarding.ts."
    )


def test_profile_tone_interface_has_all_expected_fields(ts_interfaces):
    ts_fields = ts_interfaces.get("ProfileTone", set())
    missing = EXPECTED_TONE_FIELDS - ts_fields
    assert not missing, (
        f"ProfileTone TS interface is missing fields: {sorted(missing)}. "
        f"This is how the 2026-04-20 greeting_style bug slipped through."
    )


def test_contact_rule_interface_has_all_expected_fields(ts_interfaces):
    ts_fields = ts_interfaces.get("ContactRule", set())
    missing = EXPECTED_CONTACT_RULE_FIELDS - ts_fields
    assert not missing, (
        f"ContactRule TS interface is missing fields: {sorted(missing)}. "
        f"Update agentys-app/src/types/onboarding.ts."
    )


# --- Backend dataclasses must advertise the same shape -----------------

def test_backend_user_profile_dataclass_matches():
    from dataclasses import fields as dc_fields
    from app.onboarding.schemas import UserProfile

    backend_fields = {f.name for f in dc_fields(UserProfile)}
    missing = EXPECTED_PROFILE_FIELDS - backend_fields
    assert not missing, (
        f"UserProfile dataclass is missing fields: {sorted(missing)}. "
        f"Update app/onboarding/schemas.py."
    )


def test_backend_tone_profile_dataclass_matches():
    from dataclasses import fields as dc_fields
    from app.onboarding.schemas import ToneProfile

    backend_fields = {f.name for f in dc_fields(ToneProfile)}
    missing = EXPECTED_TONE_FIELDS - backend_fields
    assert not missing, (
        f"ToneProfile dataclass is missing fields: {sorted(missing)}."
    )


def test_backend_contact_rule_dataclass_matches():
    from dataclasses import fields as dc_fields
    from app.onboarding.schemas import ContactRule

    backend_fields = {f.name for f in dc_fields(ContactRule)}
    missing = EXPECTED_CONTACT_RULE_FIELDS - backend_fields
    assert not missing, (
        f"ContactRule dataclass is missing fields: {sorted(missing)}."
    )


# --- Prompts must ask the LLM for every required field ----------------

def test_profile_prompt_asks_for_every_expected_key():
    """Prompts are the actual contract with the LLM. If a prompt omits a
    field, the model won't produce it — even if schemas / types list it."""
    prompt_fr = (REPO_ROOT / "app/onboarding/agents/prompts/profile.txt").read_text(encoding="utf-8")
    prompt_en = (REPO_ROOT / "app/onboarding/agents/prompts/profile_en.txt").read_text(encoding="utf-8")

    # `uses_emoji` is intentionally OMITTED — the schema field still exists
    # (`schemas.py:ToneProfile.uses_emoji: bool = False`) for backward compat
    # with persisted profiles, but the prompt no longer asks the LLM to
    # extract it. The original profile.txt schema example listed it without
    # any extraction rule, so the LLM was guessing — see audit 2026-05-04.
    required_tokens = [
        "user_email", "user_name", "preferred_name",
        "profession", "signature", "default_tone", "addressing",
        "greeting_styles", "closing_styles",
        "average_response_length", "languages",
    ]

    for token in required_tokens:
        assert token in prompt_fr, f"profile.txt (FR) does not mention '{token}'"
        assert token in prompt_en, f"profile_en.txt (EN) does not mention '{token}'"


def test_style_prompt_asks_for_addressing():
    prompt_fr = (REPO_ROOT / "app/onboarding/agents/prompts/style.txt").read_text(encoding="utf-8")
    prompt_en = (REPO_ROOT / "app/onboarding/agents/prompts/style_en.txt").read_text(encoding="utf-8")

    assert "addressing" in prompt_fr, "style.txt must request contact_rules[].addressing"
    assert "addressing" in prompt_en, "style_en.txt must request contact_rules[].addressing"


# --- The flatten transform is the hot-path that prevents bug #1 -------

def test_flatten_profile_styles_picks_default_tone_variant():
    """get_insights must expose a singular greeting_style / closing_style
    matching default_tone + primary language, so the frontend renders."""
    from app.onboarding.manager import _flatten_profile_styles

    profile = {
        "user_email": "u@example.com",
        "user_name": "Alex",
        "languages": ["fr", "en"],
        "tone": {
            "default_tone": "semi-formal",
            "greeting_styles": {
                "casual_fr": "Salut {first_name},",
                "semi_formal_fr": "Bonjour {first_name},",
                "formal_fr": "Bonjour Madame/Monsieur {last_name},",
            },
            "closing_styles": {
                "casual_fr": "Alex",
                "semi_formal_fr": "Cordialement,",
            },
        },
    }
    out = _flatten_profile_styles(profile)
    assert out["tone"]["greeting_style"] == "Bonjour {first_name},"
    assert out["tone"]["closing_style"] == "Cordialement,"
    # Plural maps are preserved for settings screens.
    assert "casual_fr" in out["tone"]["greeting_styles"]


def test_flatten_profile_styles_fallback_when_exact_key_missing():
    """Falls back to same formality / any language, then first non-empty."""
    from app.onboarding.manager import _flatten_profile_styles

    profile = {
        "languages": ["fr"],
        "tone": {
            "default_tone": "formal",
            # No formal_fr key — should fall back to formal_en, then
            # finally anything non-empty.
            "greeting_styles": {"formal_en": "Dear Sir/Madam,"},
            "closing_styles": {"casual_fr": "A+"},
        },
    }
    out = _flatten_profile_styles(profile)
    assert out["tone"]["greeting_style"] == "Dear Sir/Madam,"
    assert out["tone"]["closing_style"] == "A+"


def test_flatten_profile_styles_preserves_existing_singular():
    """Never overwrite a singular field already set — respect prior data."""
    from app.onboarding.manager import _flatten_profile_styles

    profile = {
        "tone": {
            "default_tone": "casual",
            "greeting_style": "Bonjour,",        # prefilled
            "closing_style": "",                  # empty → flatten fills it
            "greeting_styles": {"casual_fr": "Salut,"},
            "closing_styles": {"casual_fr": "++"},
        },
        "languages": ["fr"],
    }
    out = _flatten_profile_styles(profile)
    assert out["tone"]["greeting_style"] == "Bonjour,"   # unchanged
    assert out["tone"]["closing_style"] == "++"          # filled


def test_flatten_profile_styles_handles_empty_input():
    from app.onboarding.manager import _flatten_profile_styles

    # No tone key at all → nothing to flatten.
    assert _flatten_profile_styles({}) == {}
    # Non-dict tone → pass through untouched.
    assert _flatten_profile_styles({"tone": None}) == {"tone": None}
    # Not a dict — pass through.
    assert _flatten_profile_styles(None) is None
    # Empty tone dict → flatten fills singular keys with empty strings so
    # the UI `&&` conditional renders nothing (instead of crashing on
    # missing property). Truthiness, not presence, guards rendering.
    out = _flatten_profile_styles({"tone": {}})
    assert out["tone"]["greeting_style"] == ""
    assert out["tone"]["closing_style"] == ""
