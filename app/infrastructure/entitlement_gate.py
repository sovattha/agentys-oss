# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""LLM entitlement gate for paid AI features."""

from __future__ import annotations

import os
from typing import Any, Optional

from app.billing.entitlements import BillingEntitlementService


def _is_billing_enforcement_enabled() -> bool:
    return os.environ.get("BILLING_ENFORCEMENT_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class EntitlementGatedLLM:
    """Wraps an LLMPort and blocks calls without an active paid subscription."""

    def __init__(self, inner: Any):
        self._inner = inner

    @property
    def name(self) -> str:
        return getattr(self._inner, "name", "entitlement-gated")

    @property
    def model(self) -> str:
        return getattr(self._inner, "model", "")

    def _check(self) -> None:
        account_id, user_id = self._context_ids()
        BillingEntitlementService().assert_ai_allowed(
            user_id=user_id,
            account_id=account_id,
            enforce_llm_budget=True,
        )

    def complete(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self._check()
        return self._inner.complete(*args, **kwargs)

    def stream(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self._check()
        return self._inner.stream(*args, **kwargs)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._inner, item)

    @staticmethod
    def _context_ids() -> tuple[Optional[int], Optional[int]]:
        account_id: Optional[int] = None
        user_id: Optional[int] = None
        try:
            from app.infrastructure.cost_manager import get_usage_context

            account_id, user_id, _feature = get_usage_context()
        except Exception:
            pass
        if account_id is None:
            try:
                from app.infrastructure.llm_attribution import current_account_id

                account_id = current_account_id()
            except Exception:
                pass
        return account_id, user_id
