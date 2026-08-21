# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Moteur de spécialités — classification d'emails par domaine et chargement de contexte expert.

Classification $0 (keyword matching) + chargement sélectif des fichiers expert (.md).
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SPECIALTIES_DIR = Path(__file__).parent.parent / "knowledge" / "specialties"

# Cache TTL (seconds)
_CACHE_TTL = 300  # 5 minutes


@dataclass
class SpecialtyMatch:
    """Résultat de classification d'un email par spécialité."""
    specialty_id: str
    specialty_name: str
    category: str
    expert_ids: list[str] = field(default_factory=list)
    expert_names: list[str] = field(default_factory=list)
    risk_level: str = "low"  # "high" | "medium" | "low"
    confidence: float = 0.0
    keyword_hits: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class SpecialtyEngine:
    """
    Classifie les emails entrants et charge le contexte expert approprié.

    - Classification: keyword matching contre classifier-rules.json ($0, pas de LLM)
    - Seuil: >= 2 keyword hits pour match
    - Chargement sélectif: 1-3 fichiers expert .md par email
    - Cache 5 min pour fichiers JSON et .md
    """

    def __init__(self):
        self._specialty_cache: dict[str, tuple[dict, float]] = {}
        self._rules_cache: dict[str, tuple[dict, float]] = {}
        self._expert_cache: dict[str, tuple[str, float]] = {}

    # ── Settings ──────────────────────────────────────────────────────────

    def get_active_specialties(self, account_id: Optional[int] = None) -> list[str]:
        """Lit active_specialties depuis les settings.

        Avec account_id : merge settings globaux + overrides per-compte (DB).
        Sans account_id : settings globaux uniquement (data/settings.json).

        Sur Railway, le fichier global est éphémère : les activations faites
        via l'UI sont stockées par compte (account.settings_json), donc passer
        account_id est nécessaire pour que Ctrl+Shift+G / refine-text
        récupère les spécialités activées par l'utilisateur.
        """
        try:
            from app.api.settings import load_settings
            settings = load_settings(account_id=account_id)
            return settings.get("active_specialties", [])
        except Exception:
            return []

    # ── Specialty metadata ────────────────────────────────────────────────

    def list_specialties(self) -> list[dict]:
        """Liste toutes les spécialités disponibles avec métadonnées."""
        specialties = []
        if not SPECIALTIES_DIR.exists():
            return specialties
        for subdir in sorted(SPECIALTIES_DIR.iterdir()):
            if not subdir.is_dir():
                continue
            spec_file = subdir / "specialty.json"
            if not spec_file.exists():
                continue
            spec = self._load_specialty_json(subdir.name)
            if spec:
                specialties.append(spec)
        return specialties

    def get_specialty(self, specialty_id: str) -> Optional[dict]:
        """Charge les métadonnées complètes d'une spécialité."""
        return self._load_specialty_json(specialty_id)

    def _load_specialty_json(self, specialty_id: str) -> Optional[dict]:
        """Charge specialty.json avec cache 5 min."""
        now = time.time()
        cached = self._specialty_cache.get(specialty_id)
        if cached and (now - cached[1]) < _CACHE_TTL:
            return cached[0]

        spec_file = SPECIALTIES_DIR / specialty_id / "specialty.json"
        if not spec_file.exists():
            return None
        try:
            data = json.loads(spec_file.read_text(encoding="utf-8"))
            self._specialty_cache[specialty_id] = (data, now)
            return data
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Error loading specialty %s: %s", specialty_id, e)
            return None

    def _load_classifier_rules(self, specialty_id: str) -> Optional[dict]:
        """Charge classifier-rules.json avec cache 5 min."""
        now = time.time()
        cached = self._rules_cache.get(specialty_id)
        if cached and (now - cached[1]) < _CACHE_TTL:
            return cached[0]

        rules_file = SPECIALTIES_DIR / specialty_id / "classifier-rules.json"
        if not rules_file.exists():
            return None
        try:
            data = json.loads(rules_file.read_text(encoding="utf-8"))
            self._rules_cache[specialty_id] = (data, now)
            return data
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Error loading classifier rules for %s: %s", specialty_id, e)
            return None

    # ── Classification ($0 keyword matching) ──────────────────────────────

    def classify_email(
        self,
        subject: str,
        body: str,
        active_specialties: list[str],
    ) -> Optional[SpecialtyMatch]:
        """
        Classifie un email par keyword matching (pas de LLM, $0).

        Seuil: >= 2 keyword hits pour considérer un match.
        Retourne le meilleur match (score le plus élevé) parmi les spécialités actives.
        """
        if not active_specialties:
            return None

        text = f"{subject} {body}".lower()
        # Normalize accents for matching
        text_normalized = _normalize_for_matching(text)

        best_match: Optional[SpecialtyMatch] = None
        best_score = 0

        for spec_id in active_specialties:
            rules = self._load_classifier_rules(spec_id)
            spec = self._load_specialty_json(spec_id)
            if not rules or not spec:
                continue

            detection_rules = rules.get("detection_rules", [])

            cat_best_score = 0
            cat_best_rule = None

            for rule in detection_rules:
                keywords_fr = rule.get("keywords_fr", [])
                keywords_en = rule.get("keywords_en", [])
                # Support both combined "keywords" field and separate "keywords_fr"/"keywords_en"
                if keywords_fr or keywords_en:
                    all_keywords = keywords_fr + keywords_en
                else:
                    all_keywords = rule.get("keywords", [])

                hits = 0
                for kw in all_keywords:
                    kw_lower = kw.lower()
                    kw_normalized = _normalize_for_matching(kw_lower)
                    if kw_normalized in text_normalized or kw_lower in text:
                        hits += 1

                if hits >= 2 and hits > cat_best_score:
                    cat_best_score = hits
                    cat_best_rule = rule

            if cat_best_rule and cat_best_score > best_score:
                # Resolve expert names from specialty.json
                expert_ids = cat_best_rule.get("experts", [])
                expert_map = {e["id"]: e["name"] for e in spec.get("experts", [])}
                expert_names = [expert_map.get(eid, eid) for eid in expert_ids]

                # Determine risk level from rule or specialty risk_levels
                risk = cat_best_rule.get("risk", "low")
                risk = _resolve_risk_level(risk, cat_best_rule.get("category", ""), spec)

                best_score = cat_best_score
                best_match = SpecialtyMatch(
                    specialty_id=spec_id,
                    specialty_name=spec.get("name", spec_id),
                    category=cat_best_rule.get("category", ""),
                    expert_ids=expert_ids,
                    expert_names=expert_names,
                    risk_level=risk,
                    confidence=min(1.0, cat_best_score / 5.0),
                    keyword_hits=cat_best_score,
                )

            # Fallback disabled — no context injection without keyword matches.
            # Previously injected default experts at confidence=0.2 even with 0 hits,
            # which caused irrelevant domain context on unrelated emails.

        return best_match

    def build_default_match(self, specialty_id: str) -> Optional[SpecialtyMatch]:
        """Construit un SpecialtyMatch par défaut pour une spécialité donnée.

        Utilisé lorsqu'on force l'application d'une spécialité sans passer
        par la classification keyword (ex: raccourci Ctrl+Shift+G — la
        demande utilisateur est explicite, on ne veut pas de "no_match"
        à cause d'un sujet typoé ou de notes trop courtes).

        Stratégie : charger les experts de priorité 1 de la spécialité
        (max 3 pour respecter la limite de `build_specialty_context`).

        Returns:
            SpecialtyMatch avec category="general", ou None si la
            spécialité est inconnue (pas de fichier specialty.json).
        """
        spec = self._load_specialty_json(specialty_id)
        if not spec:
            return None

        experts = spec.get("experts", [])
        sorted_experts = sorted(experts, key=lambda e: e.get("priority", 99))
        top = sorted_experts[:3]
        expert_ids = [e["id"] for e in top if e.get("id")]
        expert_names = [e.get("name", e.get("id", "")) for e in top]

        risk_levels = spec.get("risk_levels", {}) or {}
        default_risk = risk_levels.get("general") or "medium"

        return SpecialtyMatch(
            specialty_id=specialty_id,
            specialty_name=spec.get("name", specialty_id),
            category="general",
            expert_ids=expert_ids,
            expert_names=expert_names,
            risk_level=default_risk,
            confidence=1.0,  # explicit user intent — pas d'incertitude
            keyword_hits=0,
        )

    # ── Context building ──────────────────────────────────────────────────

    def build_specialty_context(self, match: SpecialtyMatch) -> str:
        """
        Charge les fichiers expert correspondants et construit le bloc de contexte.

        Charge: response-guidelines.md + 1-3 expert .md files (max ~10KB total).
        """
        spec_dir = SPECIALTIES_DIR / match.specialty_id
        if not spec_dir.exists():
            return ""

        spec = self._load_specialty_json(match.specialty_id)
        if not spec:
            return ""

        parts: list[str] = []

        # 1. Response guidelines
        guidelines_file = spec_dir / "response-guidelines.md"
        if guidelines_file.exists():
            content = self._load_expert_file(str(guidelines_file))
            if content:
                parts.append(f"## Directives de réponse — {match.specialty_name}\n\n{content}")

        # 2. Matched expert files (max 3)
        expert_map = {e["id"]: e["file"] for e in spec.get("experts", [])}
        loaded = 0
        for eid in match.expert_ids[:3]:
            file_rel = expert_map.get(eid)
            if not file_rel:
                continue
            expert_path = spec_dir / file_rel
            content = self._load_expert_file(str(expert_path))
            if content:
                parts.append(content)
                loaded += 1

        # 3. Template if available for the matched category
        template_dir = spec_dir / "templates"
        if template_dir.exists():
            # Try to find a matching template by category name
            category_slug = match.category.replace("_", "-")
            for ext in [".md"]:
                tpl_file = template_dir / f"{category_slug}{ext}"
                if tpl_file.exists():
                    content = self._load_expert_file(str(tpl_file))
                    if content:
                        parts.append(f"## Modèle suggéré\n\n{content}")
                    break

        if not parts:
            return ""

        # Combine and truncate to ~10KB max
        combined = "\n\n---\n\n".join(parts)
        max_chars = 10_000
        if len(combined) > max_chars:
            combined = combined[:max_chars] + "\n\n[... contexte tronqué]"

        return combined

    def _load_expert_file(self, file_path: str) -> Optional[str]:
        """Charge un fichier expert .md avec cache 5 min."""
        now = time.time()
        cached = self._expert_cache.get(file_path)
        if cached and (now - cached[1]) < _CACHE_TTL:
            return cached[0]

        try:
            path = Path(file_path)
            if not path.exists():
                return None
            content = path.read_text(encoding="utf-8")
            self._expert_cache[file_path] = (content, now)
            return content
        except IOError as e:
            logger.warning("Error loading expert file %s: %s", file_path, e)
            return None


# ── Helpers ───────────────────────────────────────────────────────────────

def _normalize_for_matching(text: str) -> str:
    """Remove accents for fuzzy keyword matching."""
    replacements = {
        "é": "e", "è": "e", "ê": "e", "ë": "e",
        "à": "a", "â": "a", "ä": "a",
        "ù": "u", "û": "u", "ü": "u",
        "ô": "o", "ö": "o",
        "î": "i", "ï": "i",
        "ç": "c",
    }
    for accented, plain in replacements.items():
        text = text.replace(accented, plain)
    return text


def _resolve_risk_level(rule_risk: str, category: str, spec: dict) -> str:
    """Cross-check risk from rule against specialty risk_levels triggers."""
    risk_levels = spec.get("risk_levels", {})

    # Check if category matches high-risk triggers
    high_triggers = risk_levels.get("high", {}).get("triggers", [])
    if category in high_triggers:
        return "high"

    # Check medium triggers
    medium_triggers = risk_levels.get("medium", {}).get("triggers", [])
    if category in medium_triggers and rule_risk != "high":
        return "medium"

    return rule_risk


# ── Singleton ─────────────────────────────────────────────────────────────

_engine: Optional[SpecialtyEngine] = None


def get_specialty_engine() -> SpecialtyEngine:
    """Retourne l'instance singleton du moteur de spécialités."""
    global _engine
    if _engine is None:
        _engine = SpecialtyEngine()
    return _engine
