# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Gestionnaire de mémoire IA pour Agentys.

Permet de visualiser et modifier la base de connaissances de l'IA
depuis le dashboard. Supporte l'historique des modifications et
le versioning.

Usage:
    from app.memory_manager import MemoryManager, get_memory_manager

    manager = get_memory_manager()

    # Récupérer la mémoire
    content = manager.get_memory()

    # Mettre à jour la mémoire
    manager.update_memory(new_content)

    # Voir l'historique
    history = manager.get_history()
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

from app.config import KNOWLEDGE_DIR, DATA_DIR


# ============================================================================
# CONFIGURATION
# ============================================================================

MEMORY_FILE = KNOWLEDGE_DIR / "memoire.md"
MEMORY_HISTORY_FILE = DATA_DIR / "memory_history.json"
MAX_HISTORY_ENTRIES = 50


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class MemoryVersion:
    """Version de la mémoire."""
    id: str
    content_hash: str
    content_length: int
    preview: str  # Premiers 200 caractères
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    created_by: str = "user"
    change_summary: str = ""


@dataclass
class MemorySection:
    """Section de la mémoire."""
    title: str
    level: int  # 1-6 pour les niveaux de heading
    content: str
    start_line: int
    end_line: int


@dataclass
class MemoryStats:
    """Statistiques de la mémoire."""
    total_size: int
    word_count: int
    section_count: int
    last_modified: Optional[str]
    version_count: int


# ============================================================================
# MEMORY MANAGER
# ============================================================================

class MemoryManager:
    """
    Gestionnaire de la mémoire/base de connaissances de l'IA.

    Permet de lire, modifier et suivre l'historique des changements.

    Modes:
        - DB mode (account_id provided): reads/writes via OnboardingRepository per-user.
        - File mode (legacy, no account_id): reads/writes knowledge/memoire.md global.
    """

    def __init__(
        self,
        memory_file: Optional[Path] = None,
        history_file: Optional[Path] = None,
        account_id: Optional[int] = None,
    ):
        self.memory_file = memory_file or MEMORY_FILE
        self.history_file = history_file or MEMORY_HISTORY_FILE
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        self.account_id = account_id

        self.history: List[MemoryVersion] = []
        self._load_history()

    def _load_history(self) -> None:
        """Charge l'historique des versions."""
        if self.history_file.exists():
            try:
                data = json.loads(self.history_file.read_text(encoding="utf-8"))
                self.history = [MemoryVersion(**v) for v in data]
            except Exception:
                self.history = []

    def _save_history(self) -> None:
        """Sauvegarde l'historique des versions."""
        # Limiter la taille de l'historique
        if len(self.history) > MAX_HISTORY_ENTRIES:
            self.history = self.history[-MAX_HISTORY_ENTRIES:]

        self.history_file.write_text(
            json.dumps([asdict(v) for v in self.history], indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def _compute_hash(self, content: str) -> str:
        """Calcule le hash du contenu."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def _create_version(self, content: str, change_summary: str = "") -> MemoryVersion:
        """Crée une nouvelle version."""
        return MemoryVersion(
            id=f"v_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.history)}",
            content_hash=self._compute_hash(content),
            content_length=len(content),
            preview=content[:200].replace("\n", " ").strip(),
            change_summary=change_summary
        )

    def get_memory(self) -> str:
        """
        Récupère le contenu de la mémoire.

        In DB mode (account_id set), loads from OnboardingRepository.
        In file mode (legacy), reads knowledge/memoire.md.

        Returns:
            Le contenu de la base de connaissances (markdown).
        """
        if self.account_id:
            try:
                from app._prompts_monolith import load_knowledge_from_db
                kb = load_knowledge_from_db(self.account_id)
                if kb:
                    return kb
            except Exception:
                pass
            # account_id is set (web / multi-tenant): a DB miss returns "".
            # Falling back to the process-global memoire.md would return
            # another tenant's knowledge base (profile, contacts, savoirs) —
            # cross-tenant leak (audit 2026-05-29). Only the no-account case
            # (Tauri desktop single-user) may read the global file below.
            return ""
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def update_memory(
        self,
        content: str,
        change_summary: str = "",
        created_by: str = "user"
    ) -> MemoryVersion:
        """
        Met à jour la mémoire avec un nouveau contenu.

        Args:
            content: Le nouveau contenu
            change_summary: Résumé des changements
            created_by: Qui a fait la modification

        Returns:
            La nouvelle version créée
        """
        # Créer la version
        version = self._create_version(content, change_summary)
        version.created_by = created_by

        # Sauvegarder le contenu
        if self.account_id:
            self._save_to_db(content)
        else:
            self.memory_file.parent.mkdir(parents=True, exist_ok=True)
            self.memory_file.write_text(content, encoding="utf-8")

        # Ajouter à l'historique
        self.history.append(version)
        self._save_history()

        # Invalidate caches for this account
        try:
            from app.prompts.identity import invalidate_identity_cache
            invalidate_identity_cache(self.account_id)
        except Exception:
            pass

        return version

    def save_memory(self, content: str, change_summary: str = "") -> MemoryVersion:
        """Alias for update_memory (used by onboarding manager)."""
        return self.update_memory(content, change_summary, created_by="system")

    def _save_to_db(self, markdown_content: str) -> None:
        """Parse markdown back to JSON and save to OnboardingRepository."""
        import json
        from app.db.database import get_db_session
        from app.db.repositories.onboarding_repository import OnboardingRepository
        from app.onboarding.manager import parse_knowledge_markdown

        profile, knowledge, rules = parse_knowledge_markdown(markdown_content)

        with get_db_session() as session:
            repo = OnboardingRepository(session)
            result = repo.get_completed_by_account(self.account_id)
            if result:
                # Merge into the existing profile_json instead of overwriting it.
                # The parser only extracts a subset of fields (name, signature,
                # tone, language_variant, writing_format), so a wholesale
                # overwrite would wipe richer onboarding-produced data
                # (signature.address, languages list, full tone struct, etc.).
                try:
                    existing_profile = json.loads(result.profile_json or "{}")
                except Exception:
                    existing_profile = {}
                merged_profile = {**existing_profile, **profile}
                # Nested dicts need explicit merging (signature, tone) to avoid
                # the parser's partial dict erasing keys it didn't touch.
                for nested_key in ("signature", "tone", "writing_format"):
                    if nested_key in profile and isinstance(profile[nested_key], dict):
                        merged_profile[nested_key] = {
                            **(existing_profile.get(nested_key) or {}),
                            **profile[nested_key],
                        }
                result.profile_json = json.dumps(merged_profile, ensure_ascii=False)
                result.knowledge_json = json.dumps(knowledge, ensure_ascii=False)
                result.rules_json = json.dumps(rules, ensure_ascii=False)
                session.commit()

        # The KB markdown is rebuilt from profile_json on read and cached for
        # 10 min in _KB_DB_CACHE. Without this, GET /api/memory after a save
        # returns the pre-save markdown, so the UI reverts to old values
        # (the symptom that made the writing-format save look broken).
        try:
            from app._prompts_monolith import invalidate_kb_db_cache
            invalidate_kb_db_cache(self.account_id)
        except Exception:
            pass

    def get_history(
        self,
        limit: int = 20,
        offset: int = 0
    ) -> List[MemoryVersion]:
        """
        Récupère l'historique des versions.

        Args:
            limit: Nombre maximum de versions à retourner
            offset: Offset pour la pagination

        Returns:
            Liste des versions (plus récentes en premier)
        """
        sorted_history = sorted(
            self.history,
            key=lambda v: v.created_at,
            reverse=True
        )
        return sorted_history[offset:offset + limit]

    def get_version(self, version_id: str) -> Optional[MemoryVersion]:
        """Récupère une version spécifique."""
        for version in self.history:
            if version.id == version_id:
                return version
        return None

    def restore_version(self, version_id: str) -> Optional[MemoryVersion]:
        """
        Restaure une version précédente.

        Note: On ne peut pas récupérer le contenu exact des anciennes versions
        car on ne stocke que les métadonnées. Cette fonction crée une nouvelle
        version avec une note indiquant la restauration.
        """
        version = self.get_version(version_id)
        if not version:
            return None

        # On ne peut pas vraiment restaurer sans stocker le contenu complet
        # On retourne None pour indiquer que ce n'est pas possible
        return None

    def get_sections(self) -> List[MemorySection]:
        """
        Parse la mémoire en sections (basé sur les headings markdown).

        Returns:
            Liste des sections trouvées
        """
        content = self.get_memory()
        if not content:
            return []

        sections = []
        lines = content.split("\n")
        current_section: Optional[MemorySection] = None
        current_content_lines: List[str] = []

        for i, line in enumerate(lines):
            # Détecter les headings markdown
            if line.startswith("#"):
                # Sauvegarder la section précédente
                if current_section:
                    current_section.content = "\n".join(current_content_lines).strip()
                    current_section.end_line = i - 1
                    sections.append(current_section)
                    current_content_lines = []

                # Compter les #
                level = 0
                for char in line:
                    if char == "#":
                        level += 1
                    else:
                        break

                title = line[level:].strip()
                current_section = MemorySection(
                    title=title,
                    level=level,
                    content="",
                    start_line=i,
                    end_line=i
                )
            else:
                current_content_lines.append(line)

        # Dernière section
        if current_section:
            current_section.content = "\n".join(current_content_lines).strip()
            current_section.end_line = len(lines) - 1
            sections.append(current_section)

        return sections

    def update_section(
        self,
        section_title: str,
        new_content: str,
        change_summary: str = ""
    ) -> Optional[MemoryVersion]:
        """
        Met à jour une section spécifique de la mémoire.

        Args:
            section_title: Titre de la section à modifier
            new_content: Nouveau contenu de la section
            change_summary: Résumé des changements

        Returns:
            La nouvelle version ou None si section non trouvée
        """
        content = self.get_memory()
        sections = self.get_sections()

        # Trouver la section
        target_section = None
        for section in sections:
            if section.title.lower() == section_title.lower():
                target_section = section
                break

        if not target_section:
            return None

        # Reconstruire le contenu
        lines = content.split("\n")

        # Construire le nouveau contenu de la section
        heading = "#" * target_section.level + " " + target_section.title
        new_section_lines = [heading] + new_content.split("\n")

        # Remplacer les lignes
        new_lines = (
            lines[:target_section.start_line] +
            new_section_lines +
            lines[target_section.end_line + 1:]
        )

        new_content_full = "\n".join(new_lines)

        return self.update_memory(
            new_content_full,
            change_summary or f"Mise à jour section: {section_title}"
        )

    def add_section(
        self,
        title: str,
        content: str,
        level: int = 2,
        position: str = "end"
    ) -> MemoryVersion:
        """
        Ajoute une nouvelle section à la mémoire.

        Args:
            title: Titre de la section
            content: Contenu de la section
            level: Niveau du heading (1-6)
            position: "end" ou "start"

        Returns:
            La nouvelle version
        """
        current_content = self.get_memory()

        heading = "#" * level + " " + title
        new_section = f"\n\n{heading}\n{content}"

        if position == "start":
            # Trouver le premier heading pour insérer après
            lines = current_content.split("\n")
            insert_idx = 0
            for i, line in enumerate(lines):
                if line.startswith("#"):
                    insert_idx = i
                    break
            new_content = "\n".join(lines[:insert_idx]) + new_section + "\n" + "\n".join(lines[insert_idx:])
        else:
            new_content = current_content.rstrip() + new_section

        return self.update_memory(new_content, f"Ajout section: {title}")

    def delete_section(self, section_title: str) -> Optional[MemoryVersion]:
        """
        Supprime une section de la mémoire.

        Args:
            section_title: Titre de la section à supprimer

        Returns:
            La nouvelle version ou None si section non trouvée
        """
        content = self.get_memory()
        sections = self.get_sections()

        # Trouver la section
        target_section = None
        for section in sections:
            if section.title.lower() == section_title.lower():
                target_section = section
                break

        if not target_section:
            return None

        # Supprimer les lignes
        lines = content.split("\n")
        new_lines = (
            lines[:target_section.start_line] +
            lines[target_section.end_line + 1:]
        )

        new_content = "\n".join(new_lines)

        return self.update_memory(new_content, f"Suppression section: {section_title}")

    def search(self, query: str) -> List[Dict[str, Any]]:
        """
        Recherche dans la mémoire.

        Args:
            query: Terme de recherche

        Returns:
            Liste des correspondances avec contexte
        """
        content = self.get_memory()
        if not content or not query:
            return []

        results = []
        query_lower = query.lower()
        lines = content.split("\n")

        for i, line in enumerate(lines):
            if query_lower in line.lower():
                # Contexte: 2 lignes avant/après
                start = max(0, i - 2)
                end = min(len(lines), i + 3)
                context = "\n".join(lines[start:end])

                results.append({
                    "line": i + 1,
                    "match": line,
                    "context": context
                })

        return results

    def get_stats(self) -> MemoryStats:
        """
        Récupère les statistiques de la mémoire.

        Returns:
            Statistiques de la mémoire
        """
        content = self.get_memory()
        sections = self.get_sections()

        # Date de dernière modification
        last_modified = None
        if self.memory_file.exists():
            last_modified = datetime.fromtimestamp(
                self.memory_file.stat().st_mtime
            ).isoformat()

        return MemoryStats(
            total_size=len(content),
            word_count=len(content.split()) if content else 0,
            section_count=len(sections),
            last_modified=last_modified,
            version_count=len(self.history)
        )

    def export_memory(self, format: str = "markdown") -> str:
        """
        Exporte la mémoire dans différents formats.

        Args:
            format: "markdown", "json", ou "text"

        Returns:
            Le contenu exporté
        """
        content = self.get_memory()

        if format == "json":
            sections = self.get_sections()
            return json.dumps({
                "content": content,
                "sections": [asdict(s) for s in sections],
                "stats": asdict(self.get_stats())
            }, indent=2, ensure_ascii=False)

        elif format == "text":
            # Supprimer le markdown
            import re
            text = re.sub(r"#+ ", "", content)
            text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
            text = re.sub(r"\*([^*]+)\*", r"\1", text)
            text = re.sub(r"`([^`]+)`", r"\1", text)
            return text

        else:
            return content

    def import_memory(self, content: str, merge: bool = False) -> MemoryVersion:
        """
        Importe du contenu dans la mémoire.

        Args:
            content: Contenu à importer
            merge: Si True, fusionne avec le contenu existant

        Returns:
            La nouvelle version
        """
        if merge:
            current = self.get_memory()
            content = current + "\n\n---\n\n# Contenu Importé\n\n" + content

        return self.update_memory(content, "Import de contenu")


# ============================================================================
# SINGLETON
# ============================================================================

_memory_manager: Optional[MemoryManager] = None
_memory_managers: Dict[int, MemoryManager] = {}


def get_memory_manager(account_id: Optional[int] = None) -> MemoryManager:
    """Retourne un MemoryManager, per-account si account_id fourni.

    Args:
        account_id: If provided, returns a DB-backed manager for this account.
                    If None, returns the legacy file-based singleton.
    """
    if account_id:
        if account_id not in _memory_managers:
            _memory_managers[account_id] = MemoryManager(account_id=account_id)
        return _memory_managers[account_id]

    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
