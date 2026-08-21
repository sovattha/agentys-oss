# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Hot-reload de configuration sans restart du daemon.

Utilise watchdog pour surveiller les fichiers de config et recharger
automatiquement les paramètres quand ils changent.

Usage:
    from app.infrastructure.hot_reload import ConfigWatcher, get_config_watcher

    watcher = get_config_watcher()
    watcher.start()

    # Plus tard...
    watcher.stop()
"""

import os
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any
from dataclasses import dataclass, field

# Watchdog est optionnel - le hot-reload fonctionnera en mode dégradé sans
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None  # type: ignore
    FileSystemEventHandler = object  # type: ignore
    FileModifiedEvent = None  # type: ignore

from app.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class WatchedFile:
    """Fichier surveillé pour hot-reload."""
    path: Path
    last_modified: float = 0
    callbacks: List[Callable[[], None]] = field(default_factory=list)


# ============================================================================
# HANDLER DE FICHIERS
# ============================================================================

class ConfigFileHandler(FileSystemEventHandler):
    """Handler pour les changements de fichiers de config."""

    def __init__(self, config_watcher: "ConfigWatcher"):
        self.config_watcher = config_watcher
        super().__init__()

    def on_modified(self, event):
        """Appelé quand un fichier surveillé est modifié."""
        if WATCHDOG_AVAILABLE and FileModifiedEvent and isinstance(event, FileModifiedEvent):
            filepath = Path(event.src_path)
            self.config_watcher._handle_file_change(filepath)


# ============================================================================
# CONFIG WATCHER
# ============================================================================

class ConfigWatcher:
    """
    Surveillant de configuration avec hot-reload.

    Permet de recharger automatiquement la configuration quand
    les fichiers sont modifiés, sans avoir à redémarrer le daemon.

    Attributes:
        watched_files: Dictionnaire des fichiers surveillés
        observer: Observer watchdog pour les changements de fichiers
        debounce_delay: Délai en secondes pour éviter les reloads multiples
    """

    def __init__(self, debounce_delay: float = 1.0):
        self.watched_files: Dict[str, WatchedFile] = {}
        self.observer: Optional[Observer] = None
        self.debounce_delay = debounce_delay
        self._last_reload: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._running = False
        self._config_cache: Dict[str, Any] = {}

    def watch(self, filepath: Path, callback: Callable[[], None]) -> None:
        """
        Ajoute un fichier à surveiller.

        Args:
            filepath: Chemin du fichier à surveiller
            callback: Fonction à appeler lors d'un changement
        """
        filepath = Path(filepath).resolve()
        key = str(filepath)

        with self._lock:
            if key not in self.watched_files:
                self.watched_files[key] = WatchedFile(
                    path=filepath,
                    last_modified=filepath.stat().st_mtime if filepath.exists() else 0
                )

            self.watched_files[key].callbacks.append(callback)
            logger.info(f"Watching file for hot-reload: {filepath}")

    def unwatch(self, filepath: Path) -> None:
        """Arrête de surveiller un fichier."""
        key = str(Path(filepath).resolve())
        with self._lock:
            if key in self.watched_files:
                del self.watched_files[key]
                logger.info(f"Stopped watching: {filepath}")

    def start(self) -> None:
        """Démarre la surveillance des fichiers."""
        if self._running:
            return

        if not WATCHDOG_AVAILABLE:
            logger.warning(
                "watchdog package not installed - hot-reload disabled. "
                "Install with: pip install watchdog"
            )
            self._running = True  # Mark as running to avoid repeated warnings
            return

        self.observer = Observer()

        # Collecter les dossiers uniques à surveiller
        directories = set()
        for wf in self.watched_files.values():
            directories.add(str(wf.path.parent))

        # Ajouter un handler pour chaque dossier
        handler = ConfigFileHandler(self)
        for directory in directories:
            self.observer.schedule(handler, directory, recursive=False)

        self.observer.start()
        self._running = True
        logger.info(f"Config hot-reload started, watching {len(self.watched_files)} files")

    def stop(self) -> None:
        """Arrête la surveillance."""
        if self.observer and self._running:
            self.observer.stop()
            self.observer.join(timeout=5)
            self._running = False
            logger.info("Config hot-reload stopped")

    def _handle_file_change(self, filepath: Path) -> None:
        """Gère un changement de fichier."""
        key = str(filepath.resolve())

        with self._lock:
            if key not in self.watched_files:
                return

            # Debounce: ignorer les changements trop rapprochés
            now = time.time()
            last = self._last_reload.get(key, 0)
            if now - last < self.debounce_delay:
                return

            self._last_reload[key] = now
            watched = self.watched_files[key]

        logger.info(f"Config file changed: {filepath.name}, triggering reload")

        # Appeler tous les callbacks enregistrés
        for callback in watched.callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Error in hot-reload callback: {e}")

    def force_reload(self, filepath: Optional[Path] = None) -> None:
        """
        Force un rechargement.

        Args:
            filepath: Fichier spécifique à recharger (tous si None)
        """
        if filepath:
            key = str(Path(filepath).resolve())
            if key in self.watched_files:
                for callback in self.watched_files[key].callbacks:
                    try:
                        callback()
                    except Exception as e:
                        logger.error(f"Error in force_reload: {e}")
        else:
            # Recharger tous les fichiers
            for watched in self.watched_files.values():
                for callback in watched.callbacks:
                    try:
                        callback()
                    except Exception as e:
                        logger.error(f"Error in force_reload: {e}")

    @property
    def is_running(self) -> bool:
        """Retourne True si la surveillance est active."""
        return self._running


# ============================================================================
# RECHARGEMENT DE CONFIG SPECIFIQUE
# ============================================================================

class EnvConfigReloader:
    """
    Recharge les variables d'environnement depuis .env.

    Permet de modifier .env et que les changements soient pris
    en compte sans redémarrer l'application.
    """

    def __init__(self, env_path: Optional[Path] = None):
        from app.config import PROJECT_ROOT
        self.env_path = env_path or PROJECT_ROOT / ".env"
        self._original_values: Dict[str, str] = {}
        self._store_original()

    def _store_original(self) -> None:
        """Stocke les valeurs originales."""
        keys_to_track = [
            "DAEMON_POLL_INTERVAL",
            "FOLLOWUP_DELAY_DAYS",
            "DAEMON_SKIP_LOW_PRIORITY",
            "CONFIDENCE_THRESHOLD",
            "MONTHLY_BUDGET_USD",
            "NOTIFICATIONS_ENABLED",
            "DATA_RETENTION_DAYS",
        ]
        for key in keys_to_track:
            self._original_values[key] = os.getenv(key, "")

    def reload(self) -> Dict[str, tuple]:
        """
        Recharge le fichier .env et retourne les changements.

        Returns:
            Dict de key -> (old_value, new_value) pour les valeurs modifiées
        """
        if not self.env_path.exists():
            return {}

        changes = {}

        # Parser le fichier .env
        new_values = {}
        content = self.env_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'\"")
                new_values[key] = value

        # Détecter les changements
        for key, new_value in new_values.items():
            old_value = os.getenv(key, "")
            if old_value != new_value:
                changes[key] = (old_value, new_value)
                os.environ[key] = new_value
                logger.info(f"Config reloaded: {key} = {new_value[:20]}...")

        return changes

    def get_reloadable_config(self) -> Dict[str, Any]:
        """Retourne la config actuelle rechargeable."""
        return {
            "poll_interval": int(os.getenv("DAEMON_POLL_INTERVAL", "60")),
            "skip_low_priority": os.getenv("DAEMON_SKIP_LOW_PRIORITY", "").lower() == "true",
            "confidence_threshold": int(os.getenv("CONFIDENCE_THRESHOLD", "70")),
            "monthly_budget": float(os.getenv("MONTHLY_BUDGET_USD", "0")),
            "notifications_enabled": os.getenv("NOTIFICATIONS_ENABLED", "").lower() == "true",
            "data_retention_days": int(os.getenv("DATA_RETENTION_DAYS", "90")),
        }


# ============================================================================
# SINGLETON
# ============================================================================

_config_watcher: Optional[ConfigWatcher] = None
_env_reloader: Optional[EnvConfigReloader] = None


def get_config_watcher() -> ConfigWatcher:
    """Retourne l'instance singleton du ConfigWatcher."""
    global _config_watcher
    if _config_watcher is None:
        _config_watcher = ConfigWatcher()
    return _config_watcher


def get_env_reloader() -> EnvConfigReloader:
    """Retourne l'instance singleton du EnvConfigReloader."""
    global _env_reloader
    if _env_reloader is None:
        _env_reloader = EnvConfigReloader()
    return _env_reloader


def setup_hot_reload() -> ConfigWatcher:
    """
    Configure le hot-reload pour les fichiers de config standards.

    Surveille :
    - .env pour les variables d'environnement
    - knowledge/memoire.md pour la knowledge base

    Returns:
        L'instance ConfigWatcher configurée
    """
    from app.config import PROJECT_ROOT, KNOWLEDGE_DIR

    watcher = get_config_watcher()
    reloader = get_env_reloader()

    # Surveiller .env
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        watcher.watch(env_file, reloader.reload)

    # Surveiller knowledge base
    knowledge_file = KNOWLEDGE_DIR / "memoire.md"
    if knowledge_file.exists():
        def reload_knowledge():
            logger.info("Knowledge base updated, will be used in next email processing")
        watcher.watch(knowledge_file, reload_knowledge)

    return watcher
