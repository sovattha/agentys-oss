# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Draft Learning — Apprend des corrections utilisateur sur les brouillons.

Quand l'utilisateur modifie un brouillon avant de l'envoyer,
le delta (original -> modifie) est enregistre pour ameliorer
les futurs brouillons.
"""

import difflib
import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timedelta
from typing import Optional

from app.config import get_ai_artifact_retention_days, should_persist_email_content

logger = logging.getLogger(__name__)

def _default_path() -> str:
    state_dir = os.environ.get("AGENTYS_DATA_DIR")
    if not state_dir:
        state_dir = os.path.join(os.path.expanduser("~"), ".agentys")
    return os.path.join(state_dir, "draft_corrections.json")


# Chemin par defaut pour la persistance
_DEFAULT_PATH = _default_path()
_MAX_CORRECTIONS = 50  # Garder les N corrections les plus recentes
_MAX_POSITIVE_EXAMPLES = 10
_MAX_RULES = 100
_EXTRACTION_THRESHOLD = 3  # Nombre de corrections avant extraction LLM

RULE_CATEGORIES = {
    "salutation", "cloture", "ton", "longueur",
    "contenu", "formule", "format", "vocabulaire", "structure",
}
RULE_SCOPES = {"contact", "global"}


class DraftLearningStore:
    """
    Stocke les corrections utilisateur sur les brouillons IA.

    Format de chaque correction:
    {
        "timestamp": "2026-02-10T...",
        "email_id": "...",
        "contact": "sender@example.com",
        "original": "Bonjour, ...",      (draft IA original)
        "sent": "Salut, ...",            (version envoyee par l'utilisateur)
        "diff_summary": "..."             (resume des changements)
    }
    """

    def __init__(self, persist_path: str | None = None):
        self._path = persist_path or _default_path()
        self._lock = threading.Lock()
        self._corrections: list[dict] = []
        self._positive_count: int = 0
        self._positive_examples: list[dict] = []
        self._rules: list[dict] = []
        self._corrections_since_extraction: int = 0
        self._last_extracted_index: int = 0
        self._suggestion_clicks: list[dict] = []
        self._refine_instructions: list[dict] = []
        self._edit_patterns: dict = {}  # {zone: count} — greeting, closing, content, length
        self._load()

    def _load(self) -> None:
        """Charge les corrections depuis le disque."""
        try:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Support both old (plain list) and new (dict) format
                if isinstance(data, list):
                    self._corrections = data
                    self._positive_count = 0
                    self._positive_examples = []
                    self._rules = []
                elif isinstance(data, dict):
                    self._corrections = data.get("corrections", [])
                    self._positive_count = data.get("positive_count", 0)
                    self._positive_examples = data.get("positive_examples", [])
                    self._rules = data.get("rules", [])
                    self._suggestion_clicks = data.get("suggestion_clicks", [])
                    self._refine_instructions = data.get("refine_instructions", [])
                    self._edit_patterns = data.get("edit_patterns", {})
                if not should_persist_email_content():
                    self._minimize_loaded_content()
                self._last_extracted_index = data.get("last_extracted_index", len(self._corrections)) if isinstance(data, dict) else len(self._corrections)
                self._prune_expired_artifacts()
                logger.info(
                    f"Loaded {len(self._corrections)} draft corrections, "
                    f"{self._positive_count} positive signals, {len(self._rules)} rules"
                )
        except Exception as e:
            logger.warning(f"Failed to load draft corrections: {e}")
            self._corrections = []
            self._positive_count = 0
            self._positive_examples = []
            self._rules = []

    @staticmethod
    def _metadata_only_diff_summary(summary: str) -> str:
        """Retire les fragments de texte brut d'un résumé de correction."""
        if not summary:
            return "Correction enregistrée"

        safe_parts: list[str] = []
        for raw_part in summary.split(" | "):
            part = raw_part.strip()
            lower = part.lower()
            if lower.startswith("salutation:"):
                safe_parts.append("Salutation modifiée")
            elif lower.startswith("cloture:") or lower.startswith("clôture:"):
                safe_parts.append("Clôture modifiée")
            elif "->" in part:
                safe_parts.append("Vocabulaire remplacé")
            elif lower.startswith("régénération") or lower.startswith("regeneration"):
                safe_parts.append("Régénération demandée")
            else:
                sanitized = re.sub(r"'[^']*'", "[texte]", part)
                sanitized = re.sub(r'"[^"]*"', "[texte]", sanitized)
                safe_parts.append(sanitized)

        deduped = list(dict.fromkeys(p for p in safe_parts if p))
        return " | ".join(deduped) if deduped else "Correction enregistrée"

    def _correction_for_storage(self, correction: dict) -> dict:
        if should_persist_email_content():
            return dict(correction)
        safe = dict(correction)
        safe["original"] = ""
        safe["sent"] = ""
        if safe.get("instructions") is not None:
            safe["instructions"] = ""
        safe["diff_summary"] = self._metadata_only_diff_summary(
            safe.get("diff_summary", "")
        )
        return safe

    @staticmethod
    def _positive_example_for_storage(example: dict) -> dict:
        if should_persist_email_content():
            return dict(example)
        safe = dict(example)
        safe["snippet"] = ""
        safe["subject"] = ""
        return safe

    @staticmethod
    def _refine_instruction_for_storage(item: dict) -> dict:
        if should_persist_email_content():
            return dict(item)
        safe = dict(item)
        safe["before"] = ""
        safe["after"] = ""
        return safe

    def _minimize_loaded_content(self) -> None:
        self._corrections = [
            self._correction_for_storage(c) for c in self._corrections
        ]
        self._positive_examples = [
            self._positive_example_for_storage(ex) for ex in self._positive_examples
        ]
        self._refine_instructions = [
            self._refine_instruction_for_storage(item)
            for item in self._refine_instructions
        ]

    @staticmethod
    def _is_recent_entry(item: dict, *, retention_days: int) -> bool:
        timestamp = item.get("timestamp") or item.get("created_at")
        if not timestamp:
            return True
        try:
            parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return True
        now = datetime.now(parsed.tzinfo) if parsed.tzinfo else datetime.now()
        return parsed >= now - timedelta(days=retention_days)

    def _prune_expired_artifacts(self) -> None:
        if should_persist_email_content():
            return

        retention_days = get_ai_artifact_retention_days()
        self._corrections = [
            item for item in self._corrections
            if self._is_recent_entry(item, retention_days=retention_days)
        ]
        self._positive_examples = [
            item for item in self._positive_examples
            if self._is_recent_entry(item, retention_days=retention_days)
        ]
        self._suggestion_clicks = [
            item for item in self._suggestion_clicks
            if self._is_recent_entry(item, retention_days=retention_days)
        ]
        self._refine_instructions = [
            item for item in self._refine_instructions
            if self._is_recent_entry(item, retention_days=retention_days)
        ]
        self._last_extracted_index = min(
            self._last_extracted_index,
            len(self._corrections),
        )

    def _save(self) -> None:
        """Sauvegarde les corrections sur disque."""
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            self._prune_expired_artifacts()
            data = {
                "corrections": [
                    self._correction_for_storage(c) for c in self._corrections
                ],
                "positive_count": self._positive_count,
                "positive_examples": [
                    self._positive_example_for_storage(ex)
                    for ex in self._positive_examples
                ],
                "rules": self._rules,
                "last_extracted_index": self._last_extracted_index,
                "suggestion_clicks": self._suggestion_clicks,
                "refine_instructions": [
                    self._refine_instruction_for_storage(item)
                    for item in self._refine_instructions
                ],
                "edit_patterns": self._edit_patterns,
            }
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save draft corrections: {e}")

    def clear(self) -> None:
        """Efface toutes les données d'apprentissage (corrections, règles, signaux)."""
        with self._lock:
            self._corrections = []
            self._positive_count = 0
            self._positive_examples = []
            self._rules = []
            self._corrections_since_extraction = 0
            self._last_extracted_index = 0
            self._suggestion_clicks = []
            self._refine_instructions = []
            self._edit_patterns = {}
            self._save()
        logger.info("[OK] DraftLearningStore cleared")

    def prune_expired(self) -> int:
        """Applique la rétention configurée et persiste si des entrées expirent."""
        with self._lock:
            before = (
                len(self._corrections)
                + len(self._positive_examples)
                + len(self._suggestion_clicks)
                + len(self._refine_instructions)
            )
            self._prune_expired_artifacts()
            after = (
                len(self._corrections)
                + len(self._positive_examples)
                + len(self._suggestion_clicks)
                + len(self._refine_instructions)
            )
            removed = max(before - after, 0)
            if removed:
                self._save()
            return removed

    def delete_persisted(self) -> bool:
        """Supprime le fichier de persistance et vide l'instance en mémoire."""
        with self._lock:
            self._corrections = []
            self._positive_count = 0
            self._positive_examples = []
            self._rules = []
            self._corrections_since_extraction = 0
            self._last_extracted_index = 0
            self._suggestion_clicks = []
            self._refine_instructions = []
            self._edit_patterns = {}
            try:
                if os.path.exists(self._path):
                    os.remove(self._path)
                    return True
            except OSError as exc:
                logger.warning("Failed to delete draft learning store %s: %s", self._path, exc)
                return False
        return False

    def record_correction(
        self,
        email_id: str,
        original_draft: str,
        sent_body: str,
        contact: str = "",
    ) -> bool:
        """
        Enregistre une correction si le brouillon a ete modifie.

        Ignore les corrections mineures (< 10% de changement).

        Returns:
            True si une correction significative a ete enregistree.
        """
        if not original_draft or not sent_body:
            return False

        # Normaliser pour comparaison
        orig_clean = original_draft.strip()
        sent_clean = sent_body.strip()

        # Ignorer si identique
        if orig_clean == sent_clean:
            return False

        # Calculer le taux de changement (base sur la longueur)
        max_len = max(len(orig_clean), len(sent_clean))
        if max_len == 0:
            return False

        # Compter les caracteres differents (approximation rapide)
        min_len = min(len(orig_clean), len(sent_clean))
        diff_chars = abs(len(orig_clean) - len(sent_clean))
        for i in range(min_len):
            if orig_clean[i] != sent_clean[i]:
                diff_chars += 1
        change_ratio = diff_chars / max_len

        # Ignorer les changements mineurs (< 10%)
        if change_ratio < 0.10:
            return False

        # Creer un resume des changements
        diff_summary = self._summarize_diff(orig_clean, sent_clean)

        correction = {
            "timestamp": datetime.now().isoformat(),
            "email_id": email_id,
            "contact": contact,
            "original": orig_clean[:500] if should_persist_email_content() else "",
            "sent": sent_clean[:500] if should_persist_email_content() else "",
            "diff_summary": diff_summary,
        }

        with self._lock:
            self._corrections.append(correction)
            # Garder seulement les plus recents
            if len(self._corrections) > _MAX_CORRECTIONS:
                self._corrections = self._corrections[-_MAX_CORRECTIONS:]

            # Agréger les patterns d'édition par zone
            summary_lower = diff_summary.lower()
            if "salutation" in summary_lower:
                self._edit_patterns["greeting"] = self._edit_patterns.get("greeting", 0) + 1
            if "cloture" in summary_lower:
                self._edit_patterns["closing"] = self._edit_patterns.get("closing", 0) + 1
            if "raccourci" in summary_lower or "allonge" in summary_lower:
                self._edit_patterns["length"] = self._edit_patterns.get("length", 0) + 1
            if "tutoiement" in summary_lower or "vouvoiement" in summary_lower:
                self._edit_patterns["tone"] = self._edit_patterns.get("tone", 0) + 1
            if any(k in summary_lower for k in ("mot", "terme", "vocabulaire", "remplacé", "expression")):
                self._edit_patterns["vocabulary"] = self._edit_patterns.get("vocabulary", 0) + 1
            if any(k in summary_lower for k in ("paragraphe", "structure", "liste", "puces", "réorganis", "ordre")):
                self._edit_patterns["structure"] = self._edit_patterns.get("structure", 0) + 1
            # If none of the above matched, it's a content edit
            if not any(k in summary_lower for k in ("salutation", "cloture", "raccourci", "allonge", "tutoiement", "vouvoiement", "mot", "terme", "vocabulaire", "remplacé", "expression", "paragraphe", "structure", "liste", "puces", "réorganis", "ordre")):
                self._edit_patterns["content"] = self._edit_patterns.get("content", 0) + 1

            self._save()

        logger.info(
            f"Draft correction recorded: {change_ratio:.0%} change, "
            f"email_id={email_id}, contact={contact}"
        )
        return True

    def record_rejection(self, email_id: str, draft_body: str, contact: str = "") -> None:
        """Enregistre un rejet de brouillon comme signal négatif fort."""
        with self._lock:
            self._corrections.append({
                "timestamp": datetime.now().isoformat(),
                "email_id": email_id,
                "contact": contact,
                "original": (
                    (draft_body or "")[:500]
                    if should_persist_email_content()
                    else ""
                ),
                "sent": "",
                "diff_summary": "REJET COMPLET — l'utilisateur a rejeté le brouillon entier",
                "rejected": True,
            })
            if len(self._corrections) > _MAX_CORRECTIONS:
                self._corrections = self._corrections[-_MAX_CORRECTIONS:]
            self._corrections_since_extraction += 1
            self._save()

        logger.info(f"Draft rejection recorded: email_id={email_id}, contact={contact}")

        # Dégrader la confidence des règles matching
        self._degrade_rules_confidence(contact)

        # Lancer extraction si seuil atteint
        if self.should_extract_rules():
            try:
                def _extract_bg():
                    try:
                        added = extract_rules_from_corrections(self)
                        if added:
                            logger.info(f"Post-rejection rule extraction: {len(added)} rules")
                    except Exception:
                        pass
                import threading
                threading.Thread(target=_extract_bg, daemon=True, name="RejectionRuleExtraction").start()
            except Exception:
                pass

    def _degrade_rules_confidence(self, contact: str) -> None:
        """Dégrade la confidence des règles actives quand un brouillon est rejeté."""
        contact_lower = (contact or "").lower()
        with self._lock:
            for rule in self._rules:
                if not rule.get("active", True):
                    continue
                if rule.get("scope") == "global":
                    rule["confidence"] = max(rule.get("confidence", 0.5) - 0.1, 0.1)
                elif rule.get("scope") == "contact" and contact_lower:
                    if rule.get("contact", "").lower() == contact_lower:
                        rule["confidence"] = max(rule.get("confidence", 0.5) - 0.15, 0.1)
            self._save()

    def record_positive(
        self,
        email_id: str,
        draft_body: str,
        contact: str = "",
        email_subject: str = "",
        routing_tier: str = "",
    ) -> None:
        """Enregistre un signal positif et booste la confidence des règles matching."""
        with self._lock:
            self._positive_count += 1
            self._positive_examples.append({
                "timestamp": datetime.now().isoformat(),
                "contact": contact,
                "snippet": (
                    (draft_body or "")[:100]
                    if should_persist_email_content()
                    else ""
                ),
                "subject": (
                    (email_subject or "")[:100]
                    if should_persist_email_content()
                    else ""
                ),
                "tier": routing_tier,
            })
            self._positive_examples = self._positive_examples[-_MAX_POSITIVE_EXAMPLES:]

            # Boost confidence des règles actives matching
            contact_lower = (contact or "").lower()
            for rule in self._rules:
                if not rule.get("active", True):
                    continue
                if rule.get("scope") == "global":
                    rule["confidence"] = min(rule.get("confidence", 0.5) + 0.05, 1.0)
                elif rule.get("scope") == "contact" and contact_lower:
                    if (rule.get("contact", "").lower() == contact_lower):
                        rule["confidence"] = min(rule.get("confidence", 0.5) + 0.05, 1.0)

            self._save()

        logger.info(f"Draft positive signal recorded: email_id={email_id}, contact={contact}")

    def record_regeneration(
        self,
        email_id: str,
        previous_body: str,
        instructions: str,
        contact: str = "",
    ) -> None:
        """Enregistre un regenerate comme signal négatif enrichi (rejet + instructions)."""
        with self._lock:
            self._corrections.append({
                "timestamp": datetime.now().isoformat(),
                "email_id": email_id,
                "contact": contact,
                "original": (
                    (previous_body or "")[:500]
                    if should_persist_email_content()
                    else ""
                ),
                "sent": "",
                "diff_summary": (
                    f"RÉGÉNÉRATION — l'utilisateur a demandé : \"{instructions[:200]}\""
                    if should_persist_email_content()
                    else "Régénération demandée"
                ),
                "regenerated": True,
                "instructions": (
                    instructions[:500] if should_persist_email_content() else ""
                ),
            })
            if len(self._corrections) > _MAX_CORRECTIONS:
                self._corrections = self._corrections[-_MAX_CORRECTIONS:]
            self._corrections_since_extraction += 1
            self._save()

        logger.info(f"Regeneration recorded: email_id={email_id}, instructions='{instructions[:60]}'")

        # Dégrader la confidence des règles
        self._degrade_rules_confidence(contact)

        # Lancer extraction si seuil atteint
        if self.should_extract_rules():
            try:
                def _extract_bg():
                    try:
                        added = extract_rules_from_corrections(self)
                        if added:
                            logger.info(f"Post-regeneration rule extraction: {len(added)} rules")
                    except Exception:
                        pass
                import threading
                threading.Thread(target=_extract_bg, daemon=True, name="RegenRuleExtraction").start()
            except Exception:
                pass

    def record_suggestion_click(
        self,
        email_id: str,
        suggestion_text: str,
        suggestion_index: int = 0,
        contact: str = "",
    ) -> None:
        """Enregistre le clic sur une Smart Suggestion pour affiner le générateur."""
        with self._lock:
            if not hasattr(self, "_suggestion_clicks"):
                self._suggestion_clicks = []
            self._suggestion_clicks.append({
                "timestamp": datetime.now().isoformat(),
                "email_id": email_id,
                "contact": contact,
                "suggestion_text": (
                    suggestion_text[:200] if should_persist_email_content() else ""
                ),
                "suggestion_index": suggestion_index,
            })
            # Garder les 100 derniers clics
            self._suggestion_clicks = self._suggestion_clicks[-100:]
            self._save()
        logger.info(f"Suggestion click recorded: index={suggestion_index}, contact={contact}")

    def record_refine_instruction(
        self,
        instruction: str,
        before_text: str,
        after_text: str,
        contact: str = "",
    ) -> None:
        """Enregistre une instruction de refine pour apprendre les préférences de style."""
        with self._lock:
            if not hasattr(self, "_refine_instructions"):
                self._refine_instructions = []
            self._refine_instructions.append({
                "timestamp": datetime.now().isoformat(),
                "instruction": instruction[:500],
                "before": (
                    before_text[:300] if should_persist_email_content() else ""
                ),
                "after": (
                    after_text[:300] if should_persist_email_content() else ""
                ),
                "contact": contact,
            })
            # Garder les 50 dernières
            self._refine_instructions = self._refine_instructions[-50:]
            self._corrections_since_extraction += 1
            self._save()
        logger.info(f"Refine instruction recorded: '{instruction[:60]}', contact={contact}")

    def _summarize_diff(self, original: str, sent: str) -> str:
        """Resume heuristique des changements avec analyse structuree."""
        changes = []

        orig_lines = original.split("\n")
        sent_lines = sent.split("\n")

        # Greeting change
        if orig_lines and sent_lines and orig_lines[0].strip() != sent_lines[0].strip():
            if should_persist_email_content():
                changes.append(f"Salutation: '{orig_lines[0].strip()[:50]}' -> '{sent_lines[0].strip()[:50]}'")
            else:
                changes.append("Salutation modifiée")

        # Closing change (last non-empty line)
        orig_closing = next((ln for ln in reversed(orig_lines) if ln.strip()), "")
        sent_closing = next((ln for ln in reversed(sent_lines) if ln.strip()), "")
        if orig_closing != sent_closing:
            if should_persist_email_content():
                changes.append(f"Cloture: '{orig_closing.strip()[:50]}' -> '{sent_closing.strip()[:50]}'")
            else:
                changes.append("Clôture modifiée")

        # Length change
        ratio = len(sent) / max(len(original), 1)
        if ratio < 0.6:
            changes.append(f"Raccourci de {(1-ratio)*100:.0f}%")
        elif ratio > 1.4:
            changes.append(f"Allonge de {(ratio-1)*100:.0f}%")

        # Tone detection (tu/vous switch)
        orig_tu = original.lower().count(" tu ") + original.lower().count(" t'")
        orig_vous = original.lower().count(" vous ")
        sent_tu = sent.lower().count(" tu ") + sent.lower().count(" t'")
        sent_vous = sent.lower().count(" vous ")
        if orig_vous > orig_tu and sent_tu > sent_vous:
            changes.append("Ton: vouvoiement -> tutoiement")
        elif orig_tu > orig_vous and sent_vous > sent_tu:
            changes.append("Ton: tutoiement -> vouvoiement")

        # Word-level replacements (top 3 biggest changes)
        orig_words = original.split()
        sent_words = sent.split()
        matcher = difflib.SequenceMatcher(None, orig_words, sent_words)
        replacements = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "replace" and (i2 - i1) <= 5:
                o = " ".join(orig_words[i1:i2])
                s = " ".join(sent_words[j1:j2])
                if should_persist_email_content():
                    replacements.append(f"'{o}' -> '{s}'")
                else:
                    replacements.append("Vocabulaire remplacé")
        if replacements:
            changes.extend(replacements[:3])

        return " | ".join(changes) if changes else "Ajustements mineurs du contenu"

    # ================================================================
    # Rules management
    # ================================================================

    def add_rules(self, rules: list[dict]) -> list[dict]:
        """Ajoute des règles en dédupliquant par rule_text similaire."""
        added = []
        with self._lock:
            existing_texts = {r["rule_text"].lower().strip() for r in self._rules}
            for rule in rules:
                text = rule.get("rule_text", "").strip()
                if not text:
                    continue
                if text.lower() in existing_texts:
                    continue
                # Normaliser les champs
                rule.setdefault("id", f"rule_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}")
                rule.setdefault("category", "contenu")
                rule.setdefault("scope", "global")
                rule.setdefault("contact", "")
                rule.setdefault("confidence", 0.7)
                rule.setdefault("source_emails", [])
                rule.setdefault("created_at", datetime.now().isoformat())
                rule.setdefault("active", True)
                # Valider category et scope
                if rule["category"] not in RULE_CATEGORIES:
                    rule["category"] = "contenu"
                if rule["scope"] not in RULE_SCOPES:
                    rule["scope"] = "global"
                self._rules.append(rule)
                existing_texts.add(text.lower())
                added.append(rule)
            # Limiter le nombre de règles
            if len(self._rules) > _MAX_RULES:
                self._rules = self._rules[-_MAX_RULES:]
            self._save()
        if added:
            logger.info(f"Added {len(added)} new draft rules")
        return added

    def get_rules(self, contact: str = "", active_only: bool = True) -> list[dict]:
        """Retourne les règles, filtrées par contact et statut actif."""
        with self._lock:
            rules = list(self._rules)
        if active_only:
            rules = [r for r in rules if r.get("active", True)]
        if contact:
            contact_lower = contact.lower()
            # Retourner les globales + celles du contact
            rules = [
                r for r in rules
                if r.get("scope") == "global" or r.get("contact", "").lower() == contact_lower
            ]
        return rules

    def delete_rule(self, rule_id: str) -> bool:
        """Supprime une règle par ID."""
        with self._lock:
            before = len(self._rules)
            self._rules = [r for r in self._rules if r.get("id") != rule_id]
            if len(self._rules) < before:
                self._save()
                return True
        return False

    def update_rule(self, rule_id: str, **kwargs) -> bool:
        """Met à jour les champs d'une règle (rule_text, active, category, etc.)."""
        with self._lock:
            for rule in self._rules:
                if rule.get("id") == rule_id:
                    for key, value in kwargs.items():
                        if key in ("rule_text", "active", "category", "scope", "contact", "confidence"):
                            rule[key] = value
                    self._save()
                    return True
        return False

    def should_extract_rules(self) -> bool:
        """Vérifie si on a accumulé assez de corrections pour lancer une extraction."""
        return self._corrections_since_extraction >= _EXTRACTION_THRESHOLD

    def get_rules_for_prompt(self, contact: str = "", limit: int = 10) -> str:
        """Formate les règles pour injection dans le prompt du drafter.

        Les règles récentes sont pondérées plus fortement :
        - < 7 jours : confidence x2
        - 7-30 jours : confidence x1
        - > 30 jours : confidence x0.5
        """
        rules = self.get_rules(contact=contact, active_only=True)
        if not rules:
            return ""

        # Pondération temporelle
        now = datetime.utcnow()
        for r in rules:
            base_confidence = r.get("confidence", 0.5)
            created = r.get("created_at") or r.get("timestamp")
            if created:
                try:
                    ts = datetime.fromisoformat(created) if isinstance(created, str) else created
                    age_days = (now - ts).days
                    if age_days < 7:
                        r["_weighted_confidence"] = min(1.0, base_confidence * 2)
                    elif age_days > 30:
                        r["_weighted_confidence"] = base_confidence * 0.5
                    else:
                        r["_weighted_confidence"] = base_confidence
                except (ValueError, TypeError):
                    r["_weighted_confidence"] = base_confidence
            else:
                r["_weighted_confidence"] = base_confidence

        # Trier par confidence pondérée décroissante
        rules.sort(key=lambda r: r.get("_weighted_confidence", 0), reverse=True)
        rules = rules[:limit]

        contact_lower = (contact or "").lower()
        contact_rules = [r for r in rules if r.get("scope") == "contact" and r.get("contact", "").lower() == contact_lower] if contact_lower else []
        global_rules = [r for r in rules if r.get("scope") == "global"]

        lines = ["<REGLES_APPRISES>"]

        if contact_rules:
            lines.append(f"Règles pour ce contact ({contact}) :")
            for r in contact_rules:
                lines.append(f"- {r['rule_text']}")
            lines.append("")

        if global_rules:
            lines.append("Règles générales :")
            for r in global_rules:
                lines.append(f"- {r['rule_text']}")
            lines.append("")

        # Taux d'acceptation
        with self._lock:
            total = self._positive_count + len(self._corrections)
            positive = self._positive_count
        if total > 0:
            lines.append(f"Taux d'acceptation : {positive / total * 100:.0f}% ({positive}/{total})")

        # Refine instructions → préférences de style explicites
        with self._lock:
            refine_instr = list(self._refine_instructions[-5:]) if hasattr(self, "_refine_instructions") else []
            edit_pats = dict(self._edit_patterns) if hasattr(self, "_edit_patterns") else {}
        if refine_instr:
            lines.append("")
            lines.append("Instructions de style (refine) :")
            for ri in refine_instr:
                lines.append(f"- \"{ri.get('instruction', '')}\"")

        # Edit patterns → zones fréquemment modifiées
        if edit_pats:
            total_edits = sum(edit_pats.values())
            if total_edits >= 3:
                top_zone = max(edit_pats, key=edit_pats.get)
                zone_names = {
                    "greeting": "salutation", "closing": "clôture",
                    "length": "longueur", "tone": "ton", "content": "contenu",
                    "vocabulary": "vocabulaire", "structure": "structure",
                }
                zone_label = zone_names.get(top_zone, top_zone)
                pct = edit_pats[top_zone] / total_edits * 100
                if pct >= 30:
                    lines.append("")
                    lines.append(f"Zone la plus corrigée : {zone_label} ({pct:.0f}% des corrections)")
                    lines.append(f"ATTENTION PARTICULIÈRE à la {zone_label} — l'utilisateur la modifie souvent.")

        # Longueur préférée par contact (from quality tracker)
        if contact:
            try:
                from app.draft_quality_tracker import get_tracker
                avg_len = get_tracker().get_contact_avg_length(contact)
                if avg_len:
                    lines.append("")
                    lines.append(f"Longueur moyenne des réponses à ce contact : ~{avg_len} caractères")
                    lines.append("Ajuste ta longueur en conséquence.")
            except Exception:
                pass

        lines.append("</REGLES_APPRISES>")
        return "\n".join(lines)

    def get_recent_corrections(self, limit: int = 5, contact: str = "") -> str:
        """
        Retourne les corrections recentes formatees pour injection dans le prompt.

        Args:
            limit: Nombre max de corrections a retourner.
            contact: Si fourni, priorise les corrections pour ce contact.

        Returns:
            Section formatee ou chaine vide si pas de corrections.
        """
        with self._lock:
            corrections = list(self._corrections)
            positive_count = self._positive_count

        if not corrections:
            return ""

        # Prioriser les corrections du meme contact
        if contact:
            contact_lower = contact.lower()
            contact_corrections = [
                c for c in corrections if c.get("contact", "").lower() == contact_lower
            ]
            other_corrections = [
                c for c in corrections if c.get("contact", "").lower() != contact_lower
            ]
            ordered = contact_corrections[-limit:] + other_corrections[-(limit - len(contact_corrections)):]
        else:
            ordered = corrections[-limit:]

        if not ordered:
            return ""

        lines = ["<CORRECTIONS_PASSEES>"]

        # Positive reinforcement stats
        total = positive_count + len(corrections)
        if total > 0:
            accuracy = positive_count / total * 100
            lines.append(f"Taux d'acceptation sans modification: {accuracy:.0f}% ({positive_count}/{total})\n")

        lines.append("L'utilisateur a modifié ces brouillons avant de les envoyer.")
        lines.append("APPRENDS de ces corrections pour ne PAS répéter les mêmes erreurs :\n")

        for c in ordered[-limit:]:
            lines.append(f"- {c.get('diff_summary', 'Modifications')}")
            orig = c.get("original", "")[:150]
            sent = c.get("sent", "")[:150]
            if orig and sent:
                lines.append(f"  IA: \"{orig}...\"")
                lines.append(f"  Envoye: \"{sent}...\"")
            lines.append("")

        lines.append("</CORRECTIONS_PASSEES>")
        return "\n".join(lines)


# ============================================================================
# LLM Rule Extraction
# ============================================================================

_EXTRACTION_PROMPT = """\
Tu es un expert en analyse de communications email.

Analyse ces corrections de brouillons IA (version originale vs version envoyée par l'utilisateur) et extrais des RÈGLES D'APPRENTISSAGE concrètes et actionnables.

Corrections à analyser :
{corrections_block}

Règles existantes (à ne pas dupliquer) :
{existing_rules}

Extrais les règles sous forme de JSON array. Chaque règle doit avoir :
- "rule_text": une instruction claire et concise (ex: "Utiliser 'Salut' au lieu de 'Bonjour' pour jean@example.com")
- "category": une de ces valeurs : salutation, cloture, ton, longueur, contenu, formule, format, vocabulaire, structure
- "scope": "contact" si spécifique à un destinataire, "global" sinon
- "contact": l'email du contact si scope=contact, sinon ""
- "confidence": entre 0.5 et 0.9 selon la certitude

Réponds UNIQUEMENT avec un JSON array valide, sans texte avant/après. Si aucune règle pertinente, réponds [].
"""


def extract_rules_from_corrections(store: "DraftLearningStore") -> list[dict]:
    """
    Extrait des règles structurées depuis les corrections non encore analysées.

    Appelle Haiku pour analyser les corrections et en déduire des règles.
    """
    with store._lock:
        start_idx = store._last_extracted_index
        corrections = store._corrections[start_idx:]
        existing_rules = [r["rule_text"] for r in store._rules if r.get("active", True)]

    if not corrections:
        return []

    # Formater les corrections pour le prompt
    corrections_block = ""
    for i, c in enumerate(corrections, 1):
        corrections_block += f"\nCorrection {i}:\n"
        corrections_block += f"  Contact: {c.get('contact', 'inconnu')}\n"
        corrections_block += f"  Original IA: {c.get('original', '')[:300]}\n"
        corrections_block += f"  Envoyé: {c.get('sent', '')[:300]}\n"
        corrections_block += f"  Résumé: {c.get('diff_summary', '')}\n"

    existing_rules_text = "\n".join(f"- {r}" for r in existing_rules) if existing_rules else "(aucune)"

    prompt = _EXTRACTION_PROMPT.format(
        corrections_block=corrections_block,
        existing_rules=existing_rules_text,
    )

    try:
        import anthropic
        from app.config import CLAUDE_MODEL_LABEL
        client = anthropic.Anthropic(timeout=60.0)
        response = client.messages.create(
            model=CLAUDE_MODEL_LABEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        if not response.content or not hasattr(response.content[0], "text"):
            logger.warning("LLM returned empty content for rule extraction")
            return []
        raw = response.content[0].text.strip()

        # Parser le JSON (tolérant aux backticks markdown)
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        rules_data = json.loads(raw)

        if not isinstance(rules_data, list):
            logger.warning("LLM returned non-list for rule extraction")
            return []

        # Enrichir avec les source_emails
        source_emails = [c.get("email_id", "") for c in corrections if c.get("email_id")]
        for rule in rules_data:
            rule["source_emails"] = source_emails

        # Ajouter les règles au store
        added = store.add_rules(rules_data)

        # Mettre à jour l'index d'extraction
        with store._lock:
            store._last_extracted_index = len(store._corrections)
            store._corrections_since_extraction = 0
            store._save()

        logger.info(f"Rule extraction: {len(added)} new rules from {len(corrections)} corrections")
        return added

    except Exception as e:
        logger.error(f"Rule extraction failed: {e}")
        return []


# ISO-03 fix: per-account stores instead of one process-wide singleton.
# Previously, `_store: DraftLearningStore` lived at module level and persisted
# every account's draft corrections to `~/.agentys/draft_corrections.json`,
# so user A's corrections poisoned user B's drafter prompt. We now keep a
# `dict[Optional[int], DraftLearningStore]` keyed by account_id, with the
# per-account file living at `~/.agentys/draft_corrections/<account_id>.json`.
# `account_id=None` keeps the legacy single-tenant path for Tauri desktop.
_stores: dict = {}
_store_lock = threading.Lock()


def _path_for_account(account_id: Optional[int]) -> str:
    if account_id is None:
        # Legacy / Tauri desktop path — unchanged so existing installs keep
        # their corrections file.
        return _default_path()
    base = os.path.dirname(_default_path())
    return os.path.join(base, "draft_corrections", f"{int(account_id)}.json")


def get_draft_learning_store(account_id: Optional[int] = None) -> DraftLearningStore:
    """Retourne le store de corrections pour un compte donné.

    Args:
        account_id: Optional DB account ID. Pass None for the legacy
            Tauri-desktop singleton (single-tenant install). Each distinct
            account_id gets its OWN persistence file under
            `~/.agentys/draft_corrections/<account_id>.json`, isolating
            corrections across users.
    """
    global _stores
    with _store_lock:
        if account_id not in _stores:
            _stores[account_id] = DraftLearningStore(persist_path=_path_for_account(account_id))
        return _stores[account_id]


def delete_draft_learning_store(account_id: Optional[int] = None) -> bool:
    """Supprime le store d'apprentissage persistant d'un compte."""
    with _store_lock:
        store = _stores.pop(account_id, None)
    if store is None:
        store = DraftLearningStore(persist_path=_path_for_account(account_id))
    return store.delete_persisted()
