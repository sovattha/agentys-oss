# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""#957 Phase 1 — few-shot par contact + anti-double-injection.

Couvre :
- ``_history_render_pool`` : quand le few-shot <TES_RÉPONSES_PRÉCÉDENTES>
  existe, l'historique brut ne rend que le côté contact (reçus).
- Les builders drafter (_split ×3, legacy ×2 via le même helper, paire
  unified) ne rendent jamais un email ENVOYÉ à la fois en few-shot ET dans
  <HISTORIQUE_CONVERSATION>.
- ``_fetch_conversation_history_for_contact`` : pool DB élargi à 10 (la
  source du few-shot), fallback IMAP borné à ``_IMAP_HISTORY_LIMIT``.

Tests unitaires — aucun appel LLM.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

USER = "user@corp.fr"
CONTACT = "claire@client.fr"

SENT_BODY = (
    "Bonjour Claire, voici le compte rendu détaillé de notre point produit "
    "d'hier avec les prochaines étapes."
)
RECV_BODY = (
    "Merci pour le point, pouvez-vous m'envoyer la nouvelle proposition "
    "tarifaire avant vendredi ?"
)


def _history():
    return [
        {"sender": CONTACT, "subject": "Re: Point produit", "date": "2026-06-09", "body": RECV_BODY},
        {"sender": USER, "subject": "Point produit", "date": "2026-06-08", "body": SENT_BODY},
    ]


def _received_only_history():
    return [
        {"sender": CONTACT, "subject": "Re: Point produit", "date": "2026-06-09", "body": RECV_BODY},
    ]


def _historique_section(text: str) -> str:
    """Extrait le contenu de <HISTORIQUE_CONVERSATION> (vide si absent)."""
    if "<HISTORIQUE_CONVERSATION>" not in text:
        return ""
    return text.split("<HISTORIQUE_CONVERSATION>")[1].split("</HISTORIQUE_CONVERSATION>")[0]


# ============================================================================
# Section 1 — _history_render_pool
# ============================================================================

class TestHistoryRenderPool:
    def test_no_fewshot_keeps_full_history(self):
        from app.prompts.builders import _history_render_pool
        hist = _history()
        assert _history_render_pool(hist, USER, "") == hist

    def test_fewshot_filters_user_sent(self):
        from app.prompts.builders import _history_render_pool
        pool = _history_render_pool(_history(), USER, "<TES_RÉPONSES_PRÉCÉDENTES>…")
        assert [h["sender"] for h in pool] == [CONTACT]

    def test_no_user_email_keeps_full_history(self):
        from app.prompts.builders import _history_render_pool
        hist = _history()
        assert _history_render_pool(hist, "", "section") == hist

    def test_sender_case_insensitive(self):
        from app.prompts.builders import _history_render_pool
        hist = [{"sender": USER.upper(), "subject": "s", "date": "", "body": SENT_BODY}]
        assert _history_render_pool(hist, USER, "section") == []


# ============================================================================
# Section 2 — builders _split : few-shot présent → historique côté contact
# ============================================================================

class TestSplitBuildersDedup:
    def test_history_split_no_double_injection(self):
        from app.prompts.builders import get_drafter_system_prompt_with_history_split
        _system, prefix = get_drafter_system_prompt_with_history_split(
            "KB", conversation_history=_history(), user_email=USER, account_id=None,
        )
        assert "TES_RÉPONSES_PRÉCÉDENTES" in prefix
        assert SENT_BODY[:80] in prefix  # le corps envoyé vit dans le few-shot…
        hist_section = _historique_section(prefix)
        assert SENT_BODY[:80] not in hist_section  # …et UNIQUEMENT là.
        assert RECV_BODY[:60] in hist_section

    def test_segments_builder_no_double_injection(self):
        from app.prompts.builders import get_drafter_system_segments_with_history
        _segments, prefix = get_drafter_system_segments_with_history(
            "KB", conversation_history=_history(), user_email=USER, account_id=None,
        )
        assert "TES_RÉPONSES_PRÉCÉDENTES" in prefix
        hist_section = _historique_section(prefix)
        assert SENT_BODY[:80] not in hist_section
        assert RECV_BODY[:60] in hist_section

    def test_context_split_no_double_injection(self):
        from app.prompts.builders import get_drafter_system_prompt_with_context_split
        _system, prefix = get_drafter_system_prompt_with_context_split(
            "KB", "style", "contexte relation", "client", ["concis"],
            conversation_history=_history(), user_email=USER, account_id=None,
        )
        assert "TES_RÉPONSES_PRÉCÉDENTES" in prefix
        hist_section = _historique_section(prefix)
        assert SENT_BODY[:80] not in hist_section
        assert RECV_BODY[:60] in hist_section

    def test_without_fewshot_history_unchanged(self):
        """Sans email envoyé dans le pool : fallback intact (pas de filtre)."""
        from app.prompts.builders import get_drafter_system_prompt_with_history_split
        _system, prefix = get_drafter_system_prompt_with_history_split(
            "KB", conversation_history=_received_only_history(),
            user_email=USER, account_id=None,
        )
        assert "TES_RÉPONSES_PRÉCÉDENTES" not in prefix
        assert RECV_BODY[:60] in _historique_section(prefix)

    def test_all_sent_history_drops_historique_section(self):
        """Pool 100 % envoyé + few-shot → plus rien à rendre en brut."""
        from app.prompts.builders import get_drafter_system_prompt_with_history_split
        hist = [
            {"sender": USER, "subject": "s", "date": "2026-06-08", "body": SENT_BODY},
        ]
        _system, prefix = get_drafter_system_prompt_with_history_split(
            "KB", conversation_history=hist, user_email=USER, account_id=None,
        )
        assert "TES_RÉPONSES_PRÉCÉDENTES" in prefix
        assert "<HISTORIQUE_CONVERSATION>" not in prefix

    def test_history_render_stays_capped_with_large_pool(self):
        """Pool #957 élargi (10 emails) → rendu brut toujours ≤ 2 emails."""
        from app.prompts.builders import get_drafter_system_prompt_with_history_split
        hist = [
            {"sender": CONTACT, "subject": f"s{i}", "date": f"2026-06-{i + 1:02d}",
             "body": f"{RECV_BODY} (variante numéro {i})"}
            for i in range(10)
        ]
        _system, prefix = get_drafter_system_prompt_with_history_split(
            "KB", conversation_history=hist, user_email=USER, account_id=None,
        )
        hist_section = _historique_section(prefix)
        assert hist_section.count("--- Email") <= 2

    def test_tone_directive_mentions_fewshot(self):
        """#957 : le few-shot prime — la directive de ton (cacheable, donc
        statique) doit le mentionner dans les deux branches résumé/sans-résumé."""
        from app.prompts.builders import _history_tone_directives
        for has_summary in (True, False):
            tone_rule, closing = _history_tone_directives(has_summary)
            assert "TES_RÉPONSES_PRÉCÉDENTES" in tone_rule
            assert "TES_RÉPONSES_PRÉCÉDENTES" in closing


# ============================================================================
# Section 3 — paire unified (draft_unified)
# ============================================================================

class TestUnifiedUserPromptDedup:
    def test_with_user_email_filters_sent(self):
        from app.prompts.builders import get_unified_draft_user_prompt
        prompt = get_unified_draft_user_prompt(
            "email reçu", conversation_history=_history(), user_email=USER,
        )
        assert SENT_BODY[:80] not in prompt
        assert RECV_BODY[:60] in prompt

    def test_without_user_email_legacy_unchanged(self):
        from app.prompts.builders import get_unified_draft_user_prompt
        prompt = get_unified_draft_user_prompt(
            "email reçu", conversation_history=_history(),
        )
        assert SENT_BODY[:80] in prompt

    def test_all_sent_history_drops_section(self):
        from app.prompts.builders import get_unified_draft_user_prompt
        hist = [{"sender": USER, "subject": "s", "date": "", "body": SENT_BODY}]
        prompt = get_unified_draft_user_prompt(
            "email reçu", conversation_history=hist, user_email=USER,
        )
        assert "HISTORIQUE DE CONVERSATION" not in prompt


# ============================================================================
# Section 4 — _fetch_conversation_history_for_contact : bornes
# ============================================================================

class TestHistoryFetchLimits:
    def test_db_query_uses_default_pool_of_10(self):
        from app.api.routes_helpers import _fetch_conversation_history_for_contact
        repo = MagicMock()
        repo.get_with_contact.return_value = []
        with patch("app.db.database.get_db_session") as gds, \
             patch("app.db.repositories.EmailRepository", return_value=repo):
            gds.return_value.__enter__ = MagicMock(return_value=MagicMock())
            gds.return_value.__exit__ = MagicMock(return_value=False)
            _fetch_conversation_history_for_contact(
                provider=None, sender_email=CONTACT, account_id=7,
            )
        repo.get_with_contact.assert_called_once()
        assert repo.get_with_contact.call_args.kwargs["limit"] == 10

    def test_imap_fallback_stays_capped(self):
        """Le pool large est DB-only : l'IMAP garde la borne historique (2)."""
        from app.api.routes_helpers import (
            _IMAP_HISTORY_LIMIT,
            _fetch_conversation_history_for_contact,
        )
        provider = MagicMock(spec=["search_emails"])
        provider.search_emails.return_value = []
        repo = MagicMock()
        repo.get_with_contact.return_value = []
        with patch("app.db.database.get_db_session") as gds, \
             patch("app.db.repositories.EmailRepository", return_value=repo):
            gds.return_value.__enter__ = MagicMock(return_value=MagicMock())
            gds.return_value.__exit__ = MagicMock(return_value=False)
            _fetch_conversation_history_for_contact(
                provider=provider, sender_email=CONTACT, account_id=7,
            )
        provider.search_emails.assert_called_once()
        assert provider.search_emails.call_args.kwargs["limit"] == _IMAP_HISTORY_LIMIT
        assert _IMAP_HISTORY_LIMIT == 2
