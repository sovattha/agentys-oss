# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Entité PendingDraft pour les brouillons en attente de validation."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid


class PendingDraftStatus(Enum):
    """Statut d'un brouillon en attente."""
    PENDING = "pending"        # En attente de validation
    VALIDATED = "validated"    # Validé et créé dans Gmail
    SENT = "sent"              # Envoyé via le provider (Story 6-7)
    REJECTED = "rejected"      # Rejeté par l'utilisateur
    MODIFIED = "modified"      # Modifié par l'utilisateur


@dataclass
class PendingDraft:
    """
    Représente un brouillon généré automatiquement en attente de validation.

    Workflow:
    1. Le daemon détecte un nouvel email
    2. Le daemon génère un brouillon et crée un PendingDraft (status=PENDING)
    3. L'utilisateur voit le pending draft dans l'app
    4. L'utilisateur peut:
       - Valider: crée le brouillon dans Gmail (status=VALIDATED)
       - Modifier: édite et crée dans Gmail (status=MODIFIED)
       - Rejeter: supprime le pending draft (status=REJECTED)
    """
    # Identifiant unique
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Email source
    email_id: str = ""
    email_sender: str = ""
    email_sender_name: Optional[str] = None
    email_subject: str = ""
    email_body: str = ""
    email_received_at: Optional[str] = None

    # Brouillon généré
    draft_subject: str = ""
    draft_body: str = ""
    draft_v1: str = ""
    critique: str = ""

    # Contexte de conversation (historique vu par l'IA)
    conversation_history: list = field(default_factory=list)

    # Routing / complexité
    routing_tier: str = ""  # skip, simple, standard, complex

    # Métadonnées
    classification: str = ""
    priority: int = 50
    confidence: float = 0.85
    status: PendingDraftStatus = PendingDraftStatus.PENDING

    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    processed_at: Optional[str] = None

    # Quick Reply (binary yes/no — no LLM cost) — legacy
    quick_replies: Optional[dict] = None

    # Smart Suggestions (Phase 18) — Haiku-generated short reply candidates (5-15 words).
    # Rendered by frontend `PendingDraftDetail.tsx` as clickable chips above the draft.
    # List of strings; None = not generated; [] = explicitly empty (model produced none).
    # Producer: `app.smart_routing.SmartRouter._generate_smart_suggestions()` (DP-01 fix, 2026-04-24).
    smart_suggestions: Optional[list] = None

    # Specialty info (Expert Mode)
    specialty_info: Optional[dict] = None  # {specialty_id, specialty_name, category, experts_used, risk_level}

    # Account info (AccountAgent)
    account_info: Optional[dict] = None  # {action, requester_email, wp_user_id, wp_username, status, ...}

    # Account (multi-account filtering)
    account_id: Optional[str] = None

    # Trace de la mémoire injectée dans le prompt (#159)
    memory_trace: Optional[dict] = None

    # Transparence pipeline (#162)
    classification_reason: str = ""
    correction_details: Optional[list] = None
    pipeline_summary: Optional[str] = None

    # Résultat après validation
    gmail_draft_id: Optional[str] = None

    # Emoji marker chip rendered right after the subject on the Drafts row
    # (same shape as `emails.emoji_marker_json`: {"emoji", "text"?,
    # "include_deadline"?}). For follow-up drafts this is set to
    # {"emoji": "🔁"} by `create_snoozed_followup_draft` so the chip is
    # reliable regardless of the sent email row's timing — the email-row
    # `mark_with_emoji` path races send-time persistence and silently
    # returns email_not_found (cf. routes_pending._build_emoji_marker_map).
    emoji_marker: Optional[dict] = None

    def to_dict(self) -> dict:
        """Convertit en dictionnaire pour sérialisation JSON."""
        return {
            "id": self.id,
            "email_id": self.email_id,
            "email_sender": self.email_sender,
            "email_sender_name": self.email_sender_name,
            "email_subject": self.email_subject,
            "email_body": self.email_body,
            "email_received_at": self.email_received_at.isoformat() if hasattr(self.email_received_at, 'isoformat') else self.email_received_at,
            "draft_subject": self.draft_subject,
            "draft_body": self.draft_body,
            "draft_v1": self.draft_v1,
            "critique": self.critique,
            "conversation_history": self.conversation_history,
            "routing_tier": self.routing_tier,
            "classification": self.classification,
            "priority": self.priority,
            "confidence": self.confidence,
            "status": self.status.value if isinstance(self.status, PendingDraftStatus) else self.status,
            "created_at": self.created_at.isoformat() if hasattr(self.created_at, 'isoformat') else self.created_at,
            "processed_at": self.processed_at.isoformat() if hasattr(self.processed_at, 'isoformat') else self.processed_at,
            "quick_replies": self.quick_replies,
            "smart_suggestions": self.smart_suggestions,
            "specialty_info": self.specialty_info,
            "account_info": self.account_info,
            "account_id": self.account_id,
            "memory_trace": self.memory_trace,
            "classification_reason": self.classification_reason,
            "correction_details": self.correction_details,
            "pipeline_summary": self.pipeline_summary,
            "gmail_draft_id": self.gmail_draft_id,
            "emoji_marker": self.emoji_marker,
        }

    def to_dict_summary(self) -> dict:
        """Lightweight dict for list endpoints — excludes heavy body/critique/history fields."""
        return {
            "id": self.id,
            "email_id": self.email_id,
            "email_sender": self.email_sender,
            "email_sender_name": self.email_sender_name,
            "email_subject": self.email_subject,
            "email_received_at": self.email_received_at.isoformat() if hasattr(self.email_received_at, 'isoformat') else self.email_received_at,
            "draft_subject": self.draft_subject,
            "routing_tier": self.routing_tier,
            "classification": self.classification,
            "priority": self.priority,
            "confidence": self.confidence,
            "status": self.status.value if isinstance(self.status, PendingDraftStatus) else self.status,
            "created_at": self.created_at.isoformat() if hasattr(self.created_at, 'isoformat') else self.created_at,
            "processed_at": self.processed_at.isoformat() if hasattr(self.processed_at, 'isoformat') else self.processed_at,
            "quick_replies": self.quick_replies,
            "smart_suggestions": self.smart_suggestions,
            "specialty_info": self.specialty_info,
            "account_info": self.account_info,
            "account_id": self.account_id,
            "gmail_draft_id": self.gmail_draft_id,
            "emoji_marker": self.emoji_marker,
            "conversation_history_count": len(self.conversation_history) if self.conversation_history else 0,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PendingDraft":
        """Crée une instance depuis un dictionnaire."""
        status = data.get("status", "pending")
        if isinstance(status, str):
            status = PendingDraftStatus(status)

        return cls(
            id=data.get("id", str(uuid.uuid4())),
            email_id=data.get("email_id", ""),
            email_sender=data.get("email_sender", ""),
            email_sender_name=data.get("email_sender_name"),
            email_subject=data.get("email_subject", ""),
            email_body=data.get("email_body", ""),
            email_received_at=data.get("email_received_at"),
            draft_subject=data.get("draft_subject", ""),
            draft_body=data.get("draft_body", ""),
            draft_v1=data.get("draft_v1", ""),
            critique=data.get("critique", ""),
            conversation_history=data.get("conversation_history", []),
            routing_tier=data.get("routing_tier", ""),
            classification=data.get("classification", ""),
            priority=data.get("priority", 50),
            confidence=data.get("confidence", 0.85),
            status=status,
            created_at=data.get("created_at", datetime.now().isoformat()),
            processed_at=data.get("processed_at"),
            quick_replies=data.get("quick_replies"),
            smart_suggestions=data.get("smart_suggestions"),
            specialty_info=data.get("specialty_info"),
            account_info=data.get("account_info"),
            account_id=data.get("account_id"),
            memory_trace=data.get("memory_trace"),
            classification_reason=data.get("classification_reason", ""),
            correction_details=data.get("correction_details"),
            pipeline_summary=data.get("pipeline_summary"),
            gmail_draft_id=data.get("gmail_draft_id"),
            emoji_marker=data.get("emoji_marker"),
        )


# ============================================================================
# WebSocket payload contract — `draft_ready` event
# ============================================================================
# Audit DP-02 (2026-04-24): REST and daemon paths emitted two incompatible
# `draft_ready` shapes. Frontend `mapDaemonEvent` (websocket.ts:430-461)
# only parses the daemon shape: top-level `email_id` + `payload.draft_id`.
# The REST shape (`{data: {email_id, draft_id}}`) silently failed.
#
# CANONICAL SHAPE (consume from `mapDaemonEvent`):
#   {
#     "type": "draft_ready",
#     "email_id": <str>,                    # top-level — frontend reads here
#     "timestamp": <ISO-8601 str>,
#     "payload": {
#       "pending_draft_id": <str>,          # PendingDraft.id
#       "draft_id": <str>,                  # alias for pending_draft_id (frontend reads .draft_id)
#       "draft_content": <str>,             # final draft body
#       "subject": <str>,                   # draft subject (Re: ...)
#       "confidence": <int 0-100>,          # 0-100 percent
#     },
#   }
#
# All emitters (REST `/process` background, batch_queue, labels relabel) MUST use
# `build_draft_ready_payload()` to produce the dict, then wrap with
# `{"type": "draft_ready", **payload}` and pass to `emit_to_account`.

def build_draft_ready_payload(
    *,
    email_id: str,
    pending_draft_id: str,
    draft_content: str,
    subject: str = "",
    confidence: float = 0.85,
    extra: Optional[dict] = None,
) -> dict:
    """Build the canonical `draft_ready` WebSocket event body (DP-02 fix).

    Returns a dict with ``email_id``, ``timestamp``, and ``payload`` keys.
    The caller is expected to add ``"type": "draft_ready"`` and pass the
    result to ``emit_to_account``. Frontend ``mapDaemonEvent`` requires both
    ``email_id`` (top-level) and ``payload.draft_id`` to be non-empty for
    the email-list refresh + toast notifications to fire.

    Args:
        email_id: Provider email id (gmail msg id, IMAP UID, etc.).
        pending_draft_id: ``PendingDraft.id`` (UUID4).
        draft_content: Final draft body text.
        subject: Draft subject (already prefixed ``Re:``).
        confidence: 0-1 float; serialized as 0-100 int in payload.
        extra: Optional merge into the inner ``payload`` dict (e.g. ``recipient``,
            ``classification`` for daemon-flavour). Never overrides canonical keys.

    Returns:
        Dict ready for ``emit_to_account("daemon_event", {"type": "draft_ready", **dict})``.
    """
    confidence_pct = int(round(max(0.0, min(1.0, float(confidence))) * 100))
    payload: dict = {
        "pending_draft_id": pending_draft_id,
        # Frontend `mapDaemonEvent` reads `payload.draft_id` — alias for
        # backward compatibility with the daemon's `pending_draft_id` field.
        "draft_id": pending_draft_id,
        "draft_content": draft_content or "",
        "subject": subject or "",
        "confidence": confidence_pct,
    }
    if extra:
        # Merge extras WITHOUT overriding canonical keys — caller-provided
        # context (recipient, classification, etc.) must not corrupt the contract.
        for k, v in extra.items():
            payload.setdefault(k, v)
    return {
        "email_id": email_id,
        "timestamp": datetime.now().isoformat(),
        "payload": payload,
    }
