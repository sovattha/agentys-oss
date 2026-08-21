# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapters pour l'analyse du style d'écriture.
"""

from app.adapters.style.writing_style_analyzer_adapter import WritingStyleAnalyzerAdapter
from app.adapters.style.style_similarity_analyzer import StyleSimilarityAnalyzer

__all__ = ["WritingStyleAnalyzerAdapter", "StyleSimilarityAnalyzer"]
