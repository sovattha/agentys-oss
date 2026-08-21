# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Schemas for the onboarding knowledge base pipeline.

Defines dataclasses for emails (fixture format), user profile,
extracted knowledge, and response rules.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EmailDirection(str, Enum):
    """Whether the email was sent or received by the user."""
    SENT = "sent"
    RECEIVED = "received"


class ToneLevel(str, Enum):
    """Communication tone classification."""
    FORMAL = "formal"
    SEMI_FORMAL = "semi-formal"
    CASUAL = "casual"


class ContactType(str, Enum):
    """Relationship type with a contact."""
    COLLEAGUE = "colleague"
    MANAGER = "manager"
    DIRECT_REPORT = "direct_report"
    CLIENT = "client"
    SUPPLIER = "supplier"
    PROSPECT = "prospect"
    PARTNER = "partner"
    EXTERNAL = "external"


class Language(str, Enum):
    """Supported languages.

    The pipeline ships dedicated prompts for ``FR`` and ``EN`` only. Any
    other detected dominant language is exposed as ``UNSUPPORTED`` so the
    orchestrator can flag the run as partial instead of silently feeding
    a French prompt to (e.g.) a Spanish-only inbox.
    """
    FR = "fr"
    EN = "en"
    MIXED = "mixed"
    UNSUPPORTED = "unsupported"


# ---------------------------------------------------------------------------
# Email fixture schema
# ---------------------------------------------------------------------------

@dataclass
class EmailAddress:
    """An email address with optional display name."""
    email: str
    name: Optional[str] = None


@dataclass
class Attachment:
    """Email attachment metadata."""
    filename: str
    mime_type: str
    size_bytes: int = 0


@dataclass
class FixtureEmail:
    """
    Schema for test fixture emails.

    Matches the fields of the Email SQLAlchemy model but in a
    JSON-friendly format for test fixtures.
    """
    id: str
    from_addr: EmailAddress
    to: List[EmailAddress]
    subject: str
    body: str
    date: str  # ISO 8601
    direction: EmailDirection
    cc: List[EmailAddress] = field(default_factory=list)
    thread_id: Optional[str] = None
    attachments: List[Attachment] = field(default_factory=list)
    signature: Optional[str] = None
    language: Language = Language.FR
    is_read: bool = True
    labels: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Profile schema (output of ProfileAgent)
# ---------------------------------------------------------------------------

@dataclass
class SignatureInfo:
    """Extracted signature information."""
    name: str
    title: Optional[str] = None
    department: Optional[str] = None
    company: Optional[str] = None


@dataclass
class ToneProfile:
    """User's communication tone profile.

    ``greeting_styles`` / ``closing_styles`` are plural maps keyed by
    formality + language (e.g. ``{"casual_fr": "...", "formal_en": "..."}``)
    — see ``app/onboarding/agents/prompts/profile.txt``. The singular
    ``greeting_style`` / ``closing_style`` fields are the flattened
    representatives produced by ``OnboardingManager.get_insights`` for
    frontend consumers.
    """
    default_tone: ToneLevel = ToneLevel.SEMI_FORMAL
    addressing: Optional[str] = None  # "tu" | "vous" | "mixed" | None (EN-only)
    greeting_style: str = ""      # Flattened representative for UI
    closing_style: str = ""       # Flattened representative for UI
    greeting_styles: dict = field(default_factory=dict)  # Full plural map
    closing_styles: dict = field(default_factory=dict)   # Full plural map
    uses_emoji: bool = False
    average_response_length: str = "medium"  # short / medium / long


@dataclass
class UserProfile:
    """
    Complete user communication profile.

    Output of the ProfileAgent analysis.
    """
    user_email: str
    user_name: str
    preferred_name: str = ""
    profession: str = ""
    profession_confirmed: bool = False
    signature: Optional[SignatureInfo] = None
    tone: ToneProfile = field(default_factory=ToneProfile)
    languages: List[Language] = field(default_factory=lambda: [Language.FR])
    language_variant: Optional[str] = None  # ISO code (fr-FR, en-US, ...)


# ---------------------------------------------------------------------------
# Knowledge schema (output of KnowledgeAgent)
# ---------------------------------------------------------------------------

@dataclass
class ContactKnowledge:
    """Knowledge about a specific contact.

    ``interaction_count`` is filled server-side by ``KnowledgeAgent.analyse``
    from the indexer metrics — the LLM no longer echoes the number we
    already have. ``language_variant`` is populated by the LLM (ISO code
    like ``fr-FR`` / ``en-US``) and is also derivable from email TLD as a
    fallback. Sociological ``type`` and per-contact ``topics`` were
    removed: they cost LLM tokens and were never consumed by drafts.
    """
    email: str
    name: str
    company: Optional[str] = None
    title: Optional[str] = None
    preferred_language: Language = Language.FR
    preferred_tone: ToneLevel = ToneLevel.SEMI_FORMAL
    interaction_count: int = 0
    language_variant: Optional[str] = None


@dataclass
class KnowledgeBase:
    """
    Extracted knowledge base.

    Output of the KnowledgeAgent analysis. Only contacts are produced by
    the agent; FAQ is injected post-hoc from user-supplied sources
    (website scan or document upload), not scanned from emails.
    """
    contacts: List[ContactKnowledge] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Style schema (output of StyleAgent — formerly RulesAgent)
# ---------------------------------------------------------------------------

@dataclass
class ContactRule:
    """Per-contact response rules."""
    contact_email: str
    tone: ToneLevel
    language: Language
    greeting: str
    closing: str
    addressing: Optional[str] = None  # "tu" | "vous" | None (EN or unknown)


@dataclass
class ResponseRule:
    """A general response rule inferred from email history.

    Simplified to a single descriptive sentence: the StyleAgent prompt
    used to ask for a structured ``{name, trigger, action, priority,
    examples}`` payload, but ``manager.py:_merge_rules`` collapsed every
    rule to ``{description: ...}`` before persistence, so the structured
    fields cost LLM tokens for nothing. Frontend renderers read
    ``description`` directly now.
    """
    description: str


@dataclass
class RulesSet:
    """
    Complete set of response rules.

    Output of the StyleAgent analysis.
    """
    contact_rules: List[ContactRule] = field(default_factory=list)
    general_rules: List[ResponseRule] = field(default_factory=list)
    forbidden_phrases: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Label schema (output of LabelAgent)
# ---------------------------------------------------------------------------

@dataclass
class CategoryRule:
    """Règle de catégorisation apprise."""
    label_name: str        # Label cible (défaut : Action/FYI/Noise)
    condition_type: str    # sender, subject, body, domain
    condition_value: str   # Pattern ou valeur
    confidence: float = 0.0  # 0.0-1.0
    reason: str = ""       # Explication


@dataclass
class CategoryAnalysis:
    """Output du LabelAgent."""
    default_label_rules: List[CategoryRule] = field(default_factory=list)
    statistics: dict = field(default_factory=dict)
