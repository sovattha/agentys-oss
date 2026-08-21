# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class EmailTemplate:
    id: str
    name: str
    category: str
    template_body: str
    description: Optional[str] = None
    language: str = "fr"
    tone: str = "professional"
    enabled: bool = True
    priority: int = 0
    conditions: Optional[Dict[str, Any]] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: Optional[str] = None
    usage_count: int = 0
    # Audit 2026-04-25 (HIGH-Backend-3): per-user scoping. None = legacy/global
    # template (only writable by admins). Set on create from JWT email so a
    # template the user authored is also the only template they can mutate.
    owner_email: Optional[str] = None


@dataclass
class TemplateMatch:
    template: EmailTemplate
    score: float
    variables: Dict[str, str] = field(default_factory=dict)


class TemplateVariables:
    SENDER_NAME = "sender_name"
    SENDER_EMAIL = "sender_email"
    SUBJECT = "subject"
    DATE = "date"
    TIME = "time"
    GREETING = "greeting"
    SIGNATURE = "signature"
    COMPANY = "company"
    PRIORITY = "priority"
    CATEGORY = "category"
    THREAD_COUNT = "thread_count"

    @staticmethod
    def get_all() -> List[str]:
        return [
            TemplateVariables.SENDER_NAME,
            TemplateVariables.SENDER_EMAIL,
            TemplateVariables.SUBJECT,
            TemplateVariables.DATE,
            TemplateVariables.TIME,
            TemplateVariables.GREETING,
            TemplateVariables.SIGNATURE,
            TemplateVariables.COMPANY,
            TemplateVariables.PRIORITY,
            TemplateVariables.CATEGORY,
            TemplateVariables.THREAD_COUNT,
        ]
