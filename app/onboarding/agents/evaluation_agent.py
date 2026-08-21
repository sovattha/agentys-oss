# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
EvaluationAgent: LLM-as-judge for comparing analysis outputs to ground truth.

Metrics:
- Completeness: did the analysis find everything in ground truth?
- Precision: no hallucinations or incorrect extractions?
- Usefulness: are the results exploitable for drafting?
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from app.config import MODEL_FAST
from app.domain.ports.llm_port import LLMPort
from app.infrastructure.container import get_container
from app.utils.json_parser import extract_json_from_response

logger = logging.getLogger(__name__)

MAX_TOKENS_EVALUATION = 4096

EVALUATION_SYSTEM_PROMPT = """\
You are an expert evaluator for communication analysis systems. Your task is to \
compare the OUTPUT of an analysis system against GROUND TRUTH and score the quality.

For each category, score from 0 to 100:

1. **completeness**: Did the system find all items present in ground truth?
   - 100 = found everything, 0 = found nothing
   - Partial credit for partially correct items

2. **precision**: Are the system's outputs correct (no hallucinations)?
   - 100 = everything is correct, 0 = everything is wrong
   - Penalise fabricated contacts, wrong relationship types, etc.

3. **usefulness**: Would these results help generate good email drafts?
   - 100 = immediately usable, 0 = useless
   - Consider: correct tone rules, accurate contact preferences, etc.

Also provide:
- **details**: Brief explanation of the scoring
- **missing**: List of items in ground truth but missing from output
- **incorrect**: List of items in output that are wrong

Output JSON:
{
  "completeness": number,
  "precision": number,
  "usefulness": number,
  "overall": number,
  "details": "string",
  "missing": ["string"],
  "incorrect": ["string"]
}
"""


@dataclass
class EvaluationScore:
    """Evaluation scores for a single category."""
    completeness: int = 0
    precision: int = 0
    usefulness: int = 0
    overall: int = 0
    details: str = ""
    missing: list = field(default_factory=list)
    incorrect: list = field(default_factory=list)


@dataclass
class EvaluationResult:
    """Full evaluation result across all categories."""
    profile_score: EvaluationScore = field(default_factory=EvaluationScore)
    knowledge_score: EvaluationScore = field(default_factory=EvaluationScore)
    rules_score: EvaluationScore = field(default_factory=EvaluationScore)
    overall_score: int = 0


@dataclass
class EvaluationAgent:
    """
    LLM-as-judge for evaluating onboarding analysis quality.
    """
    model: str = MODEL_FAST
    max_tokens: int = MAX_TOKENS_EVALUATION
    _llm: Optional[LLMPort] = field(default=None, repr=False)

    def __post_init__(self):
        # Onboarding pipeline — routes to ANTHROPIC_API_KEY_ONBOARDING.
        self._llm = get_container().llm_onboarding

    def evaluate(
        self,
        output: dict,
        ground_truth: dict,
    ) -> EvaluationResult:
        """
        Evaluate analysis output against ground truth.

        Skips LLM evaluation for categories with empty output
        (returns score 0 immediately).

        Args:
            output: The analysis result dict with profile/knowledge/rules.
            ground_truth: The expected results from ground_truth.json.

        Returns:
            EvaluationResult with scores per category.
        """
        result = EvaluationResult()

        # Evaluate profile
        profile_output = output.get("profile", {})
        if self._is_output_empty(profile_output, "Profile"):
            result.profile_score = self._empty_score("Profile")
        else:
            result.profile_score = self._evaluate_category(
                category="Profile",
                output=profile_output,
                expected=ground_truth.get("expected_profile", {}),
            )

        # Evaluate knowledge (contacts only — projects/faq are no longer
        # produced by the onboarding pipeline, so scoring them would penalize
        # the system for fields it intentionally doesn't emit).
        knowledge_output = output.get("knowledge", {})
        if self._is_output_empty(knowledge_output, "Knowledge"):
            result.knowledge_score = self._empty_score("Knowledge")
        else:
            knowledge_expected = {
                "contacts": ground_truth.get("expected_contacts", []),
            }
            result.knowledge_score = self._evaluate_category(
                category="Knowledge",
                output=knowledge_output,
                expected=knowledge_expected,
            )

        # Evaluate rules/style (key renamed from "rules" to "style" in #151)
        rules_output = output.get("style") or output.get("rules", {})
        if self._is_output_empty(rules_output, "Rules"):
            result.rules_score = self._empty_score("Rules")
        else:
            result.rules_score = self._evaluate_category(
                category="Rules",
                output=rules_output,
                expected=ground_truth.get("expected_rules", {}),
            )

        # Calculate overall
        scores = [
            result.profile_score.overall,
            result.knowledge_score.overall,
            result.rules_score.overall,
        ]
        result.overall_score = round(sum(scores) / len(scores)) if scores else 0

        return result

    @staticmethod
    def _is_output_empty(output: dict, category: str) -> bool:
        """Check if the output for a category has no meaningful data."""
        if not output:
            return True
        if category == "Profile":
            return not output.get("user_name")
        elif category == "Knowledge":
            return not output.get("contacts")
        elif category == "Rules":
            return (not output.get("contact_rules")
                    and not output.get("general_rules"))
        return False

    @staticmethod
    def _empty_score(category: str) -> EvaluationScore:
        """Return a zero score for empty output (no LLM call needed)."""
        logger.warning(
            "EvaluationAgent: output %s vide — évaluation LLM ignorée",
            category,
        )
        return EvaluationScore(
            completeness=0, precision=0, usefulness=0, overall=0,
            details=f"Output {category} vide — évaluation LLM ignorée",
        )

    def _evaluate_category(self, category: str, output: dict, expected: dict) -> EvaluationScore:
        """Evaluate a single category using LLM-as-judge."""
        user_prompt = (
            f"Category: {category}\n\n"
            f"=== GROUND TRUTH ===\n{json.dumps(expected, ensure_ascii=False, indent=2)}\n\n"
            f"=== SYSTEM OUTPUT ===\n{json.dumps(output, ensure_ascii=False, indent=2)}\n\n"
            f"Compare the system output to the ground truth and produce evaluation scores."
        )

        response = self._llm.complete(
            system=EVALUATION_SYSTEM_PROMPT,
            user=user_prompt,
            max_tokens=self.max_tokens,
            temperature=0.1,
        )

        parsed = extract_json_from_response(
            response.content,
            default={"completeness": 0, "precision": 0, "usefulness": 0, "overall": 0},
            error_context=f"EvaluationAgent:{category}",
        )

        score = EvaluationScore(
            completeness=parsed.get("completeness", 0),
            precision=parsed.get("precision", 0),
            usefulness=parsed.get("usefulness", 0),
            overall=parsed.get("overall", 0),
            details=parsed.get("details", ""),
            missing=parsed.get("missing", []),
            incorrect=parsed.get("incorrect", []),
        )

        logger.info(
            "Evaluation %s: completeness=%d, precision=%d, usefulness=%d, overall=%d",
            category, score.completeness, score.precision, score.usefulness, score.overall,
        )
        return score

    def evaluate_without_llm(self, output: dict, ground_truth: dict) -> EvaluationResult:
        """
        Quick evaluation using heuristics (no LLM needed).

        Useful for unit tests and CI pipelines.
        """
        result = EvaluationResult()

        # Profile evaluation
        profile = output.get("profile", {})
        expected_profile = ground_truth.get("expected_profile", {})
        profile_checks = []
        if profile.get("user_name") == expected_profile.get("user_name"):
            profile_checks.append(True)
        if profile.get("user_email") == expected_profile.get("user_email"):
            profile_checks.append(True)
        # Normalize languages: agents may return dicts or strings
        def _normalize_langs(langs):
            result_set = set()
            for lang in (langs or []):
                if isinstance(lang, dict):
                    val = lang.get("language", lang.get("code", "")).lower()
                    # Map full names to codes
                    for code, names in [("fr", ("french", "français")), ("en", ("english", "anglais"))]:
                        if val in names or val == code:
                            result_set.add(code)
                            break
                    else:
                        result_set.add(val)
                else:
                    result_set.add(str(lang).lower())
            return result_set

        if _normalize_langs(profile.get("languages")) == _normalize_langs(expected_profile.get("languages")):
            profile_checks.append(True)
        profile_pct = round(100 * sum(profile_checks) / max(len(profile_checks), 1))
        result.profile_score = EvaluationScore(
            completeness=profile_pct, precision=profile_pct,
            usefulness=profile_pct, overall=profile_pct,
        )

        # Knowledge evaluation: count matching contacts
        # Handle contacts as dicts ({"email": "..."}) or strings
        raw_contacts = output.get("knowledge", {}).get("contacts", [])
        found_contacts = set()
        for c in raw_contacts:
            if isinstance(c, dict):
                found_contacts.add(c.get("email", "").lower())
            elif isinstance(c, str):
                found_contacts.add(c.lower())
        found_contacts.discard("")

        expected_contacts = set()
        for c in ground_truth.get("expected_contacts", []):
            if isinstance(c, dict):
                expected_contacts.add(c.get("email", "").lower())
            elif isinstance(c, str):
                expected_contacts.add(c.lower())
        if expected_contacts:
            contact_recall = round(100 * len(found_contacts & expected_contacts) / len(expected_contacts))
        else:
            contact_recall = 0
        result.knowledge_score = EvaluationScore(
            completeness=contact_recall, precision=contact_recall,
            usefulness=contact_recall, overall=contact_recall,
            missing=list(expected_contacts - found_contacts),
        )

        # Rules evaluation: count matching contact rules
        _rules_out = output.get("style") or output.get("rules", {})
        found_rules = {r.get("contact_email") for r in _rules_out.get("contact_rules", [])}
        expected_rules = {r.get("contact_email") for r in ground_truth.get("expected_rules", {}).get("contact_rules", [])}
        if expected_rules:
            rules_recall = round(100 * len(found_rules & expected_rules) / len(expected_rules))
        else:
            rules_recall = 0
        result.rules_score = EvaluationScore(
            completeness=rules_recall, precision=rules_recall,
            usefulness=rules_recall, overall=rules_recall,
            missing=list(expected_rules - found_rules),
        )

        scores = [result.profile_score.overall, result.knowledge_score.overall, result.rules_score.overall]
        result.overall_score = round(sum(scores) / len(scores))

        return result
