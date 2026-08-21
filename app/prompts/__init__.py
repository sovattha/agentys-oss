# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Prompts package — drop-in replacement for the former prompts.py monolith.

All public symbols are re-exported from _prompts_monolith for backward
compatibility. Existing imports (`from app.prompts import X`) continue
to work unchanged.

Migration plan (Epic #134, issue #161):
1. Templates will be extracted to app/prompts/templates/*.txt
2. Builders will move to app/prompts/builders.py
3. Helpers will move to app/prompts/helpers.py
4. Identity helpers will move to app/prompts/identity.py
5. _prompts_monolith.py will be deleted once empty
"""

# Re-export everything from all submodules for backward compatibility.
# This ensures all 84 import sites continue to work unchanged.
from app._prompts_monolith import *  # noqa: F401, F403
from app.prompts.builders import *  # noqa: F401, F403
from app.prompts.helpers import *  # noqa: F401, F403
from app.prompts.identity import *  # noqa: F401, F403
from app._prompts_monolith import (  # noqa: F401 — explicit re-exports (monolith symbols)
    # Knowledge loading
    load_knowledge_base,
    load_knowledge_from_db,
    load_account_knowledge,
    invalidate_identity_cache,
    # Template constants
    DEFAULT_KNOWLEDGE,
    DRAFTER_SYSTEM_PROMPT,
    DRAFTER_USER_PROMPT,
    DRAFTER_USER_PROMPT_WITH_INSTRUCTIONS,
    DRAFTER_USER_PROMPT_WITH_CONTEXT,
    DRAFTER_CORRECTION_PROMPT,
    DRAFTER_REVISION_WITH_CRITIQUE_PROMPT,
    CRITIC_SYSTEM_PROMPT,
    CRITIC_USER_PROMPT,
    CRITIC_STRUCTURED_SYSTEM_PROMPT,
    CRITIC_STRUCTURED_USER_PROMPT,
    UNIFIED_DRAFT_SYSTEM_PROMPT,
    UNIFIED_DRAFT_USER_PROMPT,
    STANDARD_DRAFT_SYSTEM_PROMPT,
    STANDARD_DRAFT_USER_PROMPT,
    REPLY_QUALITY_GUARDRAILS,
    CLASSIFY_AND_DRAFT_SYSTEM_PROMPT,
    CLASSIFY_AND_DRAFT_USER_PROMPT,
    # Helper functions
    extract_sent_examples,
    extract_user_formulas,
    compute_style_metrics,
    classify_intent,
    analyze_email_formality,
    formality_to_temperature,
    # Private helpers used by smart_routing.py and builders.py
    _detect_language,
    _detect_language_override,
    load_primary_language_for_account,
    _extract_display_name,
    _extract_data_hint,
    _build_answer_template,
    _extract_knowledge_answer,
    _get_intent_rules,
    _kb_cache,
)
from app.prompts.builders import (  # noqa: F401 — explicit re-exports (builders)
    get_drafter_system_prompt,
    get_drafter_user_prompt,
    get_drafter_correction_prompt,
    get_drafter_system_prompt_with_style,
    get_drafter_system_prompt_with_history,
    get_drafter_system_prompt_with_history_split,
    get_drafter_system_prompt_with_context,
    get_drafter_system_prompt_with_context_split,
    get_drafter_user_prompt_with_context,
    get_drafter_revision_with_critique_prompt,
    get_drafter_system_segments_with_history,
    get_critic_system_prompt,
    get_critic_user_prompt,
    get_critic_structured_system_prompt,
    get_critic_structured_system_segments,
    get_critic_structured_user_prompt,
    get_unified_draft_system_prompt,
    get_unified_draft_user_prompt,
    get_standard_draft_prompts,
    get_classify_and_draft_prompts,
    format_conversation_history,
    format_thread_context,
    format_contact_summary,
    get_contact_summarizer_prompts,
    # P0.1 (2026-05-14): helper to flatten the SystemSegment list returned
    # by get_standard_draft_prompts back to a single string. Used by tests
    # and by the batch enqueue path (BatchRequest.system_prompt: str).
    _segments_to_text,
)
