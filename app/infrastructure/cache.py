# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Cache pour la knowledge base et autres données fréquemment accédées.

Évite les rechargements inutiles de fichiers volumineux et améliore
les performances du daemon.

Usage:
    from app.infrastructure.cache import get_cache, cached

    # Utiliser le cache directement
    cache = get_cache()
    cache.set("key", value, ttl=300)
    value = cache.get("key")

    # Utiliser le décorateur
    @cached(ttl=300)
    def expensive_function():
        ...
"""

import time
import threading
import hashlib
from typing import Any, Callable, Optional, Dict, TypeVar, Generic
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path

from app.infrastructure.logging_config import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


# ============================================================================
# CACHE ENTRY
# ============================================================================

@dataclass
class CacheEntry(Generic[T]):
    """Entrée du cache avec TTL.

    `created_at` reste en `time.time()` (epoch wall clock) car il sert au
    calcul de TTL qui est exprimé en secondes "réelles".

    `last_accessed_at` utilise `time.perf_counter_ns()` (haute résolution
    sub-µs et monotone) pour garantir une discrimination stricte entre
    deux accès consécutifs — `time.time()` a ~15ms de résolution sur
    Windows, ce qui faisait collisionner les timestamps et perturbait
    l'éviction LRU (cf. fix 2026-04-26).
    """
    value: T
    created_at: float = field(default_factory=time.time)
    ttl: Optional[float] = None  # None = pas d'expiration
    hits: int = 0
    last_accessed_at: int = field(default_factory=time.perf_counter_ns)

    @property
    def is_expired(self) -> bool:
        """Vérifie si l'entrée a expiré."""
        if self.ttl is None:
            return False
        return time.time() - self.created_at > self.ttl

    def touch(self) -> None:
        """Incrémente le compteur de hits et met à jour le timestamp d'accès."""
        self.hits += 1
        self.last_accessed_at = time.perf_counter_ns()


# ============================================================================
# CACHE PRINCIPAL
# ============================================================================

class Cache:
    """
    Cache en mémoire avec TTL et statistiques.

    Thread-safe pour utilisation depuis le daemon.

    Attributes:
        max_size: Nombre maximum d'entrées
        default_ttl: TTL par défaut en secondes
    """

    def __init__(self, max_size: int = 1000, default_ttl: Optional[float] = 300):
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """
        Récupère une valeur du cache.

        Args:
            key: Clé de cache
            default: Valeur par défaut si non trouvé

        Returns:
            La valeur ou default si non trouvée/expirée
        """
        with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self._stats["misses"] += 1
                return default

            if entry.is_expired:
                del self._cache[key]
                self._stats["misses"] += 1
                return default

            entry.touch()
            self._stats["hits"] += 1
            return entry.value

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """
        Stocke une valeur dans le cache.

        Args:
            key: Clé de cache
            value: Valeur à stocker
            ttl: Time-to-live en secondes (None = default_ttl)
        """
        with self._lock:
            # Vérifier la taille max
            if len(self._cache) >= self.max_size and key not in self._cache:
                self._evict_lru()

            self._cache[key] = CacheEntry(
                value=value,
                ttl=ttl if ttl is not None else self.default_ttl
            )

    def delete(self, key: str) -> bool:
        """Supprime une entrée du cache."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """Vide le cache."""
        with self._lock:
            self._cache.clear()
            logger.info("Cache cleared")

    def _evict_lru(self) -> None:
        """Évince l'entrée la moins récemment utilisée.

        Note résolution timestamps : `CacheEntry` utilise `time.perf_counter_ns()`
        (cf. dataclass plus haut) plutôt que `time.time()` qui n'a que ~15ms
        de résolution sur Windows. Avec time.time() les écritures consécutives
        (set k1, set k2 → 0ms d'écart) avaient des timestamps identiques et
        `min` retombait sur l'ordre du dict ce qui évinçait n'importe quelle
        entrée. perf_counter_ns garantit la monotonie stricte.
        """
        if not self._cache:
            return

        lru_key = min(self._cache.keys(), key=lambda k: self._cache[k].last_accessed_at)
        del self._cache[lru_key]
        self._stats["evictions"] += 1

    def cleanup_expired(self) -> int:
        """Supprime les entrées expirées."""
        with self._lock:
            expired_keys = [k for k, v in self._cache.items() if v.is_expired]
            for key in expired_keys:
                del self._cache[key]
            return len(expired_keys)

    def get_stats(self) -> dict:
        """Retourne les statistiques du cache."""
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            hit_rate = self._stats["hits"] / total * 100 if total > 0 else 0
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "hits": self._stats["hits"],
                "misses": self._stats["misses"],
                "hit_rate": round(hit_rate, 2),
                "evictions": self._stats["evictions"],
            }

    def __contains__(self, key: str) -> bool:
        """Vérifie si une clé existe et n'est pas expirée."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None or entry.is_expired:
                return False
            return True

    def __len__(self) -> int:
        """Retourne le nombre d'entrées."""
        return len(self._cache)


# ============================================================================
# CACHE FICHIERS
# ============================================================================

class FileCache:
    """
    Cache spécialisé pour les fichiers avec détection de modification.

    Recharge automatiquement si le fichier a été modifié.
    """

    def __init__(self, cache: Optional[Cache] = None):
        self._cache = cache or Cache(default_ttl=None)  # Pas d'expiration auto
        self._mtimes: Dict[str, float] = {}
        self._lock = threading.Lock()

    def get_file(self, filepath: Path, loader: Callable[[Path], Any]) -> Any:
        """
        Récupère le contenu d'un fichier avec cache.

        Args:
            filepath: Chemin du fichier
            loader: Fonction pour charger le fichier

        Returns:
            Le contenu du fichier (depuis cache ou rechargé)
        """
        key = str(filepath.resolve())

        with self._lock:
            # Vérifier si le fichier a été modifié
            try:
                current_mtime = filepath.stat().st_mtime
            except FileNotFoundError:
                self._cache.delete(key)
                return None

            cached_mtime = self._mtimes.get(key, 0)

            if current_mtime > cached_mtime or key not in self._cache:
                # Recharger le fichier
                logger.debug(f"Reloading file: {filepath.name}")
                content = loader(filepath)
                self._cache.set(key, content)
                self._mtimes[key] = current_mtime
                return content

            return self._cache.get(key)

    def invalidate(self, filepath: Path) -> None:
        """Invalide le cache pour un fichier."""
        key = str(filepath.resolve())
        with self._lock:
            self._cache.delete(key)
            self._mtimes.pop(key, None)

    def clear(self) -> None:
        """Vide le cache des fichiers."""
        with self._lock:
            self._cache.clear()
            self._mtimes.clear()


# ============================================================================
# CACHE KNOWLEDGE BASE
# ============================================================================

class KnowledgeBaseCache:
    """
    Cache spécialisé pour la knowledge base.

    Charge et cache le contenu de memoire.md avec rechargement
    automatique si le fichier est modifié.
    """

    def __init__(self):
        self._file_cache = FileCache()
        self._knowledge_path: Optional[Path] = None

    def _load_knowledge(self, filepath: Path) -> str:
        """Charge le contenu de la knowledge base."""
        return filepath.read_text(encoding="utf-8")

    def get_knowledge(self, filepath: Optional[Path] = None) -> str:
        """
        Récupère le contenu de la knowledge base.

        Args:
            filepath: Chemin vers le fichier (utilise le défaut si None)

        Returns:
            Le contenu de la knowledge base
        """
        if filepath is None:
            from app.config import KNOWLEDGE_DIR
            filepath = KNOWLEDGE_DIR / "memoire.md"

        if not filepath.exists():
            return ""

        content = self._file_cache.get_file(filepath, self._load_knowledge)
        return content or ""

    def invalidate(self) -> None:
        """Invalide le cache."""
        self._file_cache.clear()


# ============================================================================
# DÉCORATEUR CACHED
# ============================================================================

def cached(ttl: Optional[float] = 300, key_prefix: str = ""):
    """
    Décorateur pour mettre en cache le résultat d'une fonction.

    Args:
        ttl: Time-to-live en secondes
        key_prefix: Préfixe pour la clé de cache

    Usage:
        @cached(ttl=60)
        def expensive_function(arg1, arg2):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Générer la clé de cache
            cache = get_cache()
            key_parts = [key_prefix or func.__name__]
            key_parts.extend(str(arg) for arg in args)
            key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            cache_key = hashlib.md5(":".join(key_parts).encode(), usedforsecurity=False).hexdigest()

            # Vérifier le cache
            result = cache.get(cache_key)
            if result is not None:
                return result

            # Exécuter et mettre en cache
            result = func(*args, **kwargs)
            cache.set(cache_key, result, ttl)
            return result

        return wrapper
    return decorator


# ============================================================================
# SINGLETONS
# ============================================================================

_cache: Optional[Cache] = None
_knowledge_cache: Optional[KnowledgeBaseCache] = None


def get_cache() -> Cache:
    """Retourne l'instance singleton du cache."""
    global _cache
    if _cache is None:
        _cache = Cache()
    return _cache


def get_knowledge_cache() -> KnowledgeBaseCache:
    """Retourne l'instance singleton du cache de knowledge base."""
    global _knowledge_cache
    if _knowledge_cache is None:
        _knowledge_cache = KnowledgeBaseCache()
    return _knowledge_cache
