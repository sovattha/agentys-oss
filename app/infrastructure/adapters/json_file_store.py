# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Classe de base pour la persistance JSON.

Cette abstraction factorise la logique commune de lecture/ecriture
JSON utilisee par tous les adapters legacy.

Clean Architecture:
- Couche Infrastructure
- Pas de dependance vers le domaine
- Reutilisable par tous les adapters JSON
"""

import json
import os
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TypeVar, Generic, List, Dict, Any, Optional

T = TypeVar("T")


def _atomic_write_json(filepath: Path, payload: Any) -> None:
    """Write JSON to disk atomically.

    Strategy: serialize to a sibling tempfile, fsync, then ``os.replace`` over
    the target. ``os.replace`` is atomic on POSIX and on NTFS (Windows ≥ 10),
    so concurrent readers either see the old file or the new one — never a
    truncated/half-written state. This is the load-bearing safety property
    behind ``sent_emails.json`` / ``schedules.json`` etc., which are read by
    the badge endpoint (every 5 min from each connected user) AND written by
    the auto-followup background loop AND by every ``send_new`` request.
    Without this, a crash or a write-write race silently empties the file
    via ``json.JSONDecodeError`` → ``return []`` in the load path.
    """
    tmp = filepath.with_suffix(filepath.suffix + ".tmp")
    data = json.dumps(payload, indent=2, ensure_ascii=False)
    # Open in text mode with explicit utf-8 to match the historical
    # ``write_text`` encoding semantics; fsync the file descriptor before
    # close so the rename can't outrun the data on power loss.
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(data)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            # Some filesystems (tmpfs, FUSE mounts, network shares) don't
            # support fsync. The atomic-rename below still gives us
            # crash-consistency for the common case.
            pass
    os.replace(tmp, filepath)


class JsonFileStore(ABC, Generic[T]):
    """
    Classe de base abstraite pour la persistance JSON.

    Fournit les operations communes:
    - Lecture/ecriture de fichiers JSON
    - Gestion des erreurs
    - Creation automatique des repertoires

    Les sous-classes doivent implementer:
    - _entity_to_dict(): Conversion entity -> dict
    - _dict_to_entity(): Conversion dict -> entity
    """

    def __init__(self, filepath: Path):
        """
        Initialise le store.

        Args:
            filepath: Chemin du fichier JSON de persistance.
        """
        self._filepath = filepath
        # Serialize load+modify+save sequences within the process. Multi-worker
        # safety relies on the atomic-rename in ``_atomic_write_json`` plus the
        # caller's idempotency; this lock just keeps the in-process race
        # window from corrupting state between two threads in the same worker.
        self._write_lock = threading.RLock()
        self._ensure_dir()

    @property
    def filepath(self) -> Path:
        """Retourne le chemin du fichier."""
        return self._filepath

    def _ensure_dir(self) -> None:
        """Cree le repertoire parent si necessaire."""
        self._filepath.parent.mkdir(parents=True, exist_ok=True)

    def _load_raw(self) -> List[Dict[str, Any]]:
        """
        Charge les donnees brutes depuis le fichier.

        Returns:
            Liste de dictionnaires. Liste vide si fichier inexistant ou invalide.
        """
        if not self._filepath.exists():
            return []
        try:
            data = json.loads(self._filepath.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return []
            return data
        except (json.JSONDecodeError, OSError):
            return []

    def _save_raw(self, records: List[Dict[str, Any]]) -> None:
        """
        Sauvegarde les donnees brutes dans le fichier.

        Args:
            records: Liste de dictionnaires a sauvegarder.
        """
        with self._write_lock:
            _atomic_write_json(self._filepath, records)

    @abstractmethod
    def _entity_to_dict(self, entity: T) -> Dict[str, Any]:
        """
        Convertit une entite en dictionnaire pour stockage.

        Args:
            entity: Entite a convertir.

        Returns:
            Dictionnaire serialisable.
        """
        pass

    @abstractmethod
    def _dict_to_entity(self, data: Dict[str, Any]) -> T:
        """
        Convertit un dictionnaire en entite.

        Args:
            data: Dictionnaire lu depuis le fichier.

        Returns:
            Entite du domaine.
        """
        pass

    def _load_all(self) -> List[T]:
        """
        Charge toutes les entites.

        Returns:
            Liste d'entites.
        """
        return [self._dict_to_entity(d) for d in self._load_raw()]

    def _save_all(self, entities: List[T]) -> None:
        """
        Sauvegarde toutes les entites.

        Args:
            entities: Liste d'entites a sauvegarder.
        """
        self._save_raw([self._entity_to_dict(e) for e in entities])

    def _insert(self, entity: T) -> None:
        """
        Insere une entite en debut de liste.

        Args:
            entity: Entite a inserer.
        """
        with self._write_lock:
            records = self._load_raw()
            records.insert(0, self._entity_to_dict(entity))
            self._save_raw(records)

    def _append(self, entity: T) -> None:
        """
        Ajoute une entite en fin de liste.

        Args:
            entity: Entite a ajouter.
        """
        with self._write_lock:
            records = self._load_raw()
            records.append(self._entity_to_dict(entity))
            self._save_raw(records)

    def _find_by_key(self, key: str, value: Any) -> Optional[T]:
        """
        Trouve une entite par cle.

        Args:
            key: Nom de la cle a chercher.
            value: Valeur a matcher.

        Returns:
            Entite trouvee ou None.
        """
        for data in self._load_raw():
            if data.get(key) == value:
                return self._dict_to_entity(data)
        return None

    def _update_by_key(
        self,
        key: str,
        value: Any,
        updates: Dict[str, Any],
    ) -> bool:
        """
        Met a jour une entite par cle.

        Args:
            key: Nom de la cle pour identifier l'entite.
            value: Valeur de la cle.
            updates: Dictionnaire des champs a mettre a jour.

        Returns:
            True si mise a jour effectuee, False sinon.
        """
        records = self._load_raw()
        for record in records:
            if record.get(key) == value:
                record.update(updates)
                self._save_raw(records)
                return True
        return False

    def _count(self) -> int:
        """
        Compte le nombre total d'entites.

        Returns:
            Nombre d'entites.
        """
        return len(self._load_raw())

    def _count_by_field(self, field: str) -> Dict[str, int]:
        """
        Compte les entites par valeur d'un champ.

        Args:
            field: Nom du champ a grouper.

        Returns:
            Dictionnaire {valeur: count}.
        """
        counts: Dict[str, int] = {}
        for record in self._load_raw():
            value = record.get(field, "UNKNOWN")
            counts[value] = counts.get(value, 0) + 1
        return counts


class MultiFileJsonStore(ABC):
    """
    Classe de base pour les stores utilisant plusieurs fichiers JSON.

    Utile pour les adapters gerant plusieurs types de donnees
    (ex: FollowupAdapter avec emails + schedules).
    """

    def __init__(self, data_dir: Path):
        """
        Initialise le store.

        Args:
            data_dir: Repertoire contenant les fichiers JSON.
        """
        self._data_dir = data_dir
        # Single lock for all files in the directory. Re-entrant so a caller
        # holding the lock can chain ``_load_file`` / ``_save_file`` calls
        # without deadlocking on the same instance.
        self._write_lock = threading.RLock()
        self._ensure_dir()

    @property
    def data_dir(self) -> Path:
        """Retourne le repertoire de donnees."""
        return self._data_dir

    def _ensure_dir(self) -> None:
        """Cree le repertoire si necessaire."""
        self._data_dir.mkdir(parents=True, exist_ok=True)

    def _load_file(self, filename: str) -> List[Dict[str, Any]]:
        """
        Charge un fichier JSON.

        Args:
            filename: Nom du fichier (sans chemin).

        Returns:
            Liste de dictionnaires.
        """
        filepath = self._data_dir / filename
        if not filepath.exists():
            return []
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return []
            return data
        except (json.JSONDecodeError, OSError):
            return []

    def _save_file(self, filename: str, records: List[Dict[str, Any]]) -> None:
        """
        Sauvegarde dans un fichier JSON.

        Args:
            filename: Nom du fichier (sans chemin).
            records: Donnees a sauvegarder.
        """
        filepath = self._data_dir / filename
        with self._write_lock:
            _atomic_write_json(filepath, records)
