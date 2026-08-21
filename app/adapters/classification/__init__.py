# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapters de classification et priorisation d'emails.

Ce module fournit les implémentations concrètes des ports
ClassifierPort, PrioritizationPort et EmailAnalyzerPort.
"""

from .llm_classifier_adapter import LLMClassifierAdapter
from .llm_prioritization_adapter import LLMPrioritizationAdapter
from .llm_email_analyzer_adapter import LLMEmailAnalyzerAdapter

__all__ = [
    "LLMClassifierAdapter",
    "LLMPrioritizationAdapter",
    "LLMEmailAnalyzerAdapter",
]
