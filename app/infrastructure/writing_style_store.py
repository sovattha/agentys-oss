# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter de stockage pour les profils de style d'écriture.

Implémente le port WritingStyleStorePort avec stockage JSON local.
Un fichier par compte: style_profile_{account_id}.json dans data/learning/.

Ce stockage est purement local (NFR47 - pas d'envoi aux serveurs).
"""

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.config import get_ai_artifact_retention_days, should_persist_email_content
from app.domain.entities.writing_style import ReferenceExample, WritingStyleProfile
from app.domain.ports.writing_style_port import WritingStyleStorePort

logger = logging.getLogger(__name__)

# Pattern pour les noms de fichiers
PROFILE_FILENAME_PATTERN = "style_profile_{account_id}.json"

# Single lock guards every read/write across the store. Onboarding runs 4
# agents in parallel (`ThreadPoolExecutor(max_workers=4)`) and each agent's
# completion can trigger a style-profile save — without this lock, two
# simultaneous `write_text` calls interleave on Windows and leave trailing
# garbage (valid JSON + orphan tail), causing JSONDecodeError on the next
# load and forcing the "No per-contact styles configured" empty state.
_FILE_LOCK = threading.Lock()

# In-memory cache keyed by (account_id, file mtime_ns). Each draft cycle hits
# `load()` 2–4× (Drafter → Critic → optional Refine, plus _resolve_contact_overrides);
# previously every hit re-read + re-parsed the JSON file. The mtime is the
# cache key second component so saves invalidate themselves automatically:
# a fresh save bumps mtime → next load sees a different key → reloads from
# disk. No TTL needed — file mtime IS the freshness signal.
_PROFILE_CACHE: Dict[Tuple[int, int], WritingStyleProfile] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX_ENTRIES = 64  # bound the cache so a long-lived process doesn't grow unbounded


class FileWritingStyleStore(WritingStyleStorePort):
    """
    Adapter de stockage fichier pour les profils de style d'écriture.

    Stocke chaque profil dans un fichier JSON séparé:
    - data/learning/style_profile_1.json
    - data/learning/style_profile_2.json
    - etc.

    Attributes:
        data_dir: Répertoire de stockage des fichiers.
    """

    def __init__(self, data_dir: Optional[Path] = None):
        """
        Initialise le store.

        Args:
            data_dir: Répertoire de stockage (défaut: data/learning).
        """
        if data_dir is None:
            data_dir = Path("data/learning")
        self._data_dir = data_dir
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        """Crée le répertoire de données s'il n'existe pas."""
        self._data_dir.mkdir(parents=True, exist_ok=True)

    def _get_filepath(self, account_id: int) -> Path:
        """
        Génère le chemin du fichier pour un compte.

        Args:
            account_id: ID du compte.

        Returns:
            Chemin complet du fichier JSON.
        """
        filename = PROFILE_FILENAME_PATTERN.format(account_id=account_id)
        return self._data_dir / filename

    @staticmethod
    def _safe_reference_example(example: ReferenceExample) -> Optional[ReferenceExample]:
        """Return metadata-only style provenance without durable email text.

        Audit regressions (2026-05-18 batch5) F-07: a prior branch had
        persisted up to 1000 chars of regex-anonymized body excerpts +
        200 chars of subject. ``anonymize_text`` is a regex pass that
        catches email/phone/URL/AMOUNT but leaves names mid-sentence,
        company names, project codes, addresses, and non-Latin scripts
        intact — NOT a content-safety guarantee. The Drafter prompt path
        (``prompts/helpers.py:extract_cross_thread_examples``) would
        also inject those excerpts verbatim, opening a self-prompt-
        injection channel.

        Decision: empty strings until a named-entity reject (not regex
        scrub) can guarantee no PII survives. The metadata fields
        (length_bucket, word_count, formality_level, preferred_greetings,
        preferred_closings) preserve the style signal without content.
        """
        if not example.anonymized:
            return None

        return ReferenceExample(
            length_bucket=example.length_bucket,
            body_excerpt="",
            subject="",
            anonymized=True,
            word_count=example.word_count,
            collected_at=example.collected_at,
            source_email_id=example.source_email_id,
        )

    @staticmethod
    def _parse_reference_timestamp(value: Optional[str]) -> Optional[datetime]:
        """Parse un timestamp d'exemple. None/invalid => non persistable."""
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _reference_example_is_recent(self, example: ReferenceExample) -> bool:
        """True si l'exemple dérivé reste dans la fenêtre de rétention."""
        collected_at = self._parse_reference_timestamp(example.collected_at)
        if collected_at is None:
            return False

        cutoff = datetime.now(timezone.utc) - timedelta(days=get_ai_artifact_retention_days())
        return collected_at >= cutoff

    def _minimize_profile(self, profile: WritingStyleProfile) -> WritingStyleProfile:
        """Minimise les exemples durables quand le cloud est metadata-only."""
        if should_persist_email_content():
            return profile

        safe_examples = []
        for example in profile.reference_examples:
            safe = self._safe_reference_example(example)
            if safe is not None and self._reference_example_is_recent(safe):
                safe_examples.append(safe)
        profile.reference_examples = safe_examples
        return profile

    def _profile_to_dict_for_storage(self, profile: WritingStyleProfile) -> Dict:
        """Sérialise un profil en appliquant la politique de rétention."""
        profile = self._minimize_profile(profile)
        return profile.to_dict()

    def save(self, profile: WritingStyleProfile) -> bool:
        """
        Sauvegarde un profil de style.

        Writes are serialised on ``_FILE_LOCK`` and go through a temp
        file + atomic rename so concurrent agent completions can't
        interleave bytes into the final file.

        Args:
            profile: Profil à sauvegarder.

        Returns:
            True si succès, False sinon.
        """
        filepath = self._get_filepath(profile.account_id)
        try:
            payload = json.dumps(
                self._profile_to_dict_for_storage(profile),
                indent=2,
                ensure_ascii=False,
            )
            tmp_path = filepath.with_suffix(filepath.suffix + ".tmp")
            with _FILE_LOCK:
                # Atomic rename: if the write aborts mid-flight, the live
                # file is untouched. `os.replace` is atomic on POSIX and
                # best-effort on Windows (retried by Python on ERROR_ACCESS).
                tmp_path.write_text(payload, encoding="utf-8")
                os.replace(tmp_path, filepath)
            # Drop any cached profile for this account — the new mtime would
            # already make the next load() miss, but evicting eagerly avoids
            # a transient window where a stale entry survives until the next
            # eviction cycle.
            with _CACHE_LOCK:
                stale = [k for k in _PROFILE_CACHE if k[0] == profile.account_id]
                for k in stale:
                    _PROFILE_CACHE.pop(k, None)
            logger.info(f"Writing style profile saved for account {profile.account_id}")
            return True
        except (OSError, TypeError) as e:
            logger.error(f"Failed to save writing style profile: {e}")
            return False

    def load(self, account_id: int) -> Optional[WritingStyleProfile]:
        """
        Charge un profil de style.

        Args:
            account_id: ID du compte.

        Returns:
            Profil chargé ou None si non trouvé.
        """
        filepath = self._get_filepath(account_id)
        if not filepath.exists():
            logger.debug(f"No writing style profile found for account {account_id}")
            return None

        try:
            # Read under the same lock as save/delete so we can never catch
            # a partially-rewritten file (atomic rename is near-instant but
            # a concurrent save + read on Windows can still collide).
            with _FILE_LOCK:
                stat = filepath.stat()
                mtime_ns = stat.st_mtime_ns
                cache_key = (account_id, mtime_ns)
                with _CACHE_LOCK:
                    cached = _PROFILE_CACHE.get(cache_key)
                if cached is not None:
                    return cached
                data = json.loads(filepath.read_text(encoding="utf-8"))
            profile = self._minimize_profile(WritingStyleProfile.from_dict(data))
            with _CACHE_LOCK:
                # Drop any stale entry for this account_id (different mtime)
                # before inserting — keeps the cache bounded for long-running
                # processes without needing time-based eviction.
                stale = [k for k in _PROFILE_CACHE if k[0] == account_id and k != cache_key]
                for k in stale:
                    _PROFILE_CACHE.pop(k, None)
                if len(_PROFILE_CACHE) >= _CACHE_MAX_ENTRIES:
                    # FIFO eviction — pop the oldest insertion. Python dicts
                    # preserve insertion order since 3.7, so iter() gives the
                    # oldest key first.
                    try:
                        oldest = next(iter(_PROFILE_CACHE))
                        _PROFILE_CACHE.pop(oldest, None)
                    except StopIteration:
                        pass
                _PROFILE_CACHE[cache_key] = profile
            logger.debug(f"Writing style profile loaded for account {account_id}")
            return profile
        except (json.JSONDecodeError, OSError, KeyError, ValueError) as e:
            logger.error(f"Failed to load writing style profile: {e}")
            return None

    def exists(self, account_id: int) -> bool:
        """
        Vérifie si un profil existe pour un compte.

        Args:
            account_id: ID du compte.

        Returns:
            True si le profil existe.
        """
        return self._get_filepath(account_id).exists()

    def delete(self, account_id: int) -> bool:
        """
        Supprime un profil de style.

        Args:
            account_id: ID du compte.

        Returns:
            True si supprimé, False si non trouvé ou erreur.
        """
        filepath = self._get_filepath(account_id)
        if not filepath.exists():
            logger.debug(f"No profile to delete for account {account_id}")
            return False

        try:
            filepath.unlink()
            with _CACHE_LOCK:
                stale = [k for k in _PROFILE_CACHE if k[0] == account_id]
                for k in stale:
                    _PROFILE_CACHE.pop(k, None)
            logger.info(f"Writing style profile deleted for account {account_id}")
            return True
        except OSError as e:
            logger.error(f"Failed to delete writing style profile: {e}")
            return False

    def list_all(self) -> List[int]:
        """
        Liste tous les IDs de comptes ayant un profil.

        Returns:
            Liste des IDs de comptes.
        """
        account_ids = []
        pattern = "style_profile_*.json"

        try:
            for filepath in self._data_dir.glob(pattern):
                # Extraire l'ID du nom de fichier
                name = filepath.stem  # style_profile_123
                parts = name.split("_")
                if len(parts) >= 3:
                    try:
                        account_id = int(parts[2])
                        account_ids.append(account_id)
                    except ValueError:
                        continue
        except OSError as e:
            logger.error(f"Failed to list writing style profiles: {e}")

        return sorted(account_ids)

    def update(self, profile: WritingStyleProfile) -> bool:
        """
        Met à jour un profil existant.

        Alias de save() car le stockage fichier écrase toujours.

        Args:
            profile: Profil mis à jour.

        Returns:
            True si succès.
        """
        return self.save(profile)

    def get_or_create_empty(self, account_id: int) -> WritingStyleProfile:
        """
        Charge un profil ou en crée un vide s'il n'existe pas.

        Args:
            account_id: ID du compte.

        Returns:
            Profil existant ou nouveau profil vide.
        """
        profile = self.load(account_id)
        if profile is None:
            profile = WritingStyleProfile.create_empty(account_id)
            self.save(profile)
        return profile
