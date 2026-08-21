"""Capture instrumentation pour le pipeline post-LLM de smart_routing.

Gated par `CAPTURE_PIPELINE_FIXTURES=1`. OFF par défaut → no-op avec overhead minimal
(vérif env var + early return).

Quand activé, dump chaque invocation du pipeline dans un fichier JSONL quotidien à
`tmp/pipeline_captures/YYYY-MM-DD.jsonl`. Rotation auto : max 500 captures/jour (par
mode) pour limiter le disque. Tout échec de capture est swallow silencieusement —
le pipeline ne doit jamais casser à cause de l'instrumentation.

Ce module est un utilitaire permanent : le code reste dans le repo même après la
capture 48h, OFF par défaut. Réactivable pour les refresh trimestriels de fixtures.

Voir :
  - `_bmad-output/implementation-artifacts/tech-spec-smart-routing-pipeline-refactor.md`
  - `scripts/anonymize_fixtures.py` (anonymisation avant commit)
  - `scripts/anonymize_fixtures.py` (traitement post-capture)

Usage côté smart_routing.py (exemple) :

    from app._fixture_capture import capture_if_enabled

    capture_if_enabled(
        mode="standard",
        raw_draft=raw,
        pipeline_input=dict(
            body=body, subject=subject, sender=sender,
            sender_name=sender_name, effective_sender_name=effective_sender_name,
            greeting_hint=greeting_hint, detected_language=detected_language,
            formality=formality, conversation_history=conversation_history,
        ),
        cleaned_draft=draft,
        corrections=corrections,
        correction_details=correction_details,
        learned_corrections_applied=learned_applied,
    )
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
ENV_FLAG = "CAPTURE_PIPELINE_FIXTURES"
DEFAULT_CAPTURE_DIR = Path("tmp/pipeline_captures")
MAX_CAPTURES_PER_MODE_PER_DAY = 500

# ── State thread-safe ──────────────────────────────────────────────────────
_lock = threading.Lock()
# Compteur de captures aujourd'hui par mode : {(date_str, mode): count}
_daily_counts: dict[tuple[str, str], int] = {}


def _is_enabled() -> bool:
    """Fast-path env var check. Inlined at call sites aussi pour minimiser l'overhead."""
    return os.getenv(ENV_FLAG) == "1"


def _capture_dir() -> Path:
    """Répertoire cible (configurable via env var `PIPELINE_CAPTURE_DIR`)."""
    override = os.getenv("PIPELINE_CAPTURE_DIR")
    return Path(override) if override else DEFAULT_CAPTURE_DIR


def _check_rotation(mode: str) -> bool:
    """Incrémente le compteur quotidien et retourne True si on peut encore capturer.

    Thread-safe. La clé (date, mode) permet d'avoir un quota par mode
    (standard/streaming/classify/v2_partial) et non un quota global.
    """
    today = date.today().isoformat()
    key = (today, mode)
    with _lock:
        current = _daily_counts.get(key, 0)
        if current >= MAX_CAPTURES_PER_MODE_PER_DAY:
            return False
        _daily_counts[key] = current + 1
        # Purge des vieilles entrées (> 2 jours) pour éviter la croissance infinie
        for old_key in list(_daily_counts.keys()):
            if old_key[0] != today:
                _daily_counts.pop(old_key, None)
        return True


def capture_if_enabled(
    *,
    mode: str,
    raw_draft: str,
    pipeline_input: dict[str, Any],
    cleaned_draft: str,
    corrections: int,
    correction_details: list[str],
    learned_corrections_applied: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Capture une invocation du pipeline si l'env var est activée.

    No-op silencieux si :
    - `CAPTURE_PIPELINE_FIXTURES` != "1"
    - Quota quotidien par mode atteint
    - Erreur I/O ou sérialisation (swallow, log debug)

    Arguments:
        mode: identifiant du call site ("standard" | "streaming" | "classify" |
              "v2_partial"). Sera utilisé par l'anonymiseur pour stratifier les
              fixtures et respecter la distribution réelle.
        raw_draft: texte brut sorti du LLM avant pipeline.
        pipeline_input: dict des variables contextuelles passées au pipeline
              (body, subject, sender, formality, etc.). Voir docstring module.
        cleaned_draft: texte après application du pipeline.
        corrections: compteur de corrections tracked (pour multi-draft selection).
        correction_details: labels des steps qui ont modifié le draft.
        learned_corrections_applied: liste des patterns appris qui ont matché
              (pour reproduire le hook CorrectionManager en mock).
        extra: champs optionnels (ex: account_id, thread_depth, tier).
    """
    if not _is_enabled():
        return

    if not _check_rotation(mode):
        logger.debug("Pipeline capture quota reached for mode=%s today", mode)
        return

    try:
        record = {
            "captured_at": time.time(),
            "mode": mode,
            "raw_draft": raw_draft,
            "pipeline_input": pipeline_input,
            "cleaned_draft": cleaned_draft,
            "corrections": int(corrections),
            "correction_details": list(correction_details or []),
            "learned_corrections_applied": list(learned_corrections_applied or []),
            "extra": dict(extra or {}),
        }
        capture_dir = _capture_dir()
        capture_dir.mkdir(parents=True, exist_ok=True)
        path = capture_dir / f"{date.today().isoformat()}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # pragma: no cover - swallow pour ne jamais casser le pipeline
        logger.debug("Pipeline capture failed silently: %s", exc)


def reset_daily_counts_for_testing() -> None:
    """Helper pour les tests unitaires — reset l'état en mémoire."""
    with _lock:
        _daily_counts.clear()
