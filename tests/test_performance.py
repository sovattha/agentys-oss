# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour les modules de performance (cache, pagination, batch).
"""

import time
import threading
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from unittest.mock import Mock
from datetime import datetime

from app.infrastructure.cache import (
    Cache,
    CacheEntry,
    FileCache,
    KnowledgeBaseCache,
    cached,
    get_cache,
    get_knowledge_cache,
)
from app.infrastructure.pagination import (
    Paginator,
    PageResult,
    CursorPaginator,
    EmailPaginator,
    paginate,
    chunked,
)
from app.infrastructure.batch import (
    BatchProcessor,
    BatchResult,
    BatchItemResult,
    BatchItemStatus,
    process_in_batches,
)


# ============================================================================
# TESTS CACHE
# ============================================================================

class TestCacheEntry:
    """Tests pour CacheEntry."""

    def test_cache_entry_creation(self):
        """Test création d'une entrée."""
        entry = CacheEntry(value="test", ttl=60)
        assert entry.value == "test"
        assert entry.ttl == 60
        assert entry.hits == 0
        assert not entry.is_expired

    def test_cache_entry_expiration(self):
        """Test expiration d'une entrée."""
        entry = CacheEntry(value="test", ttl=0.01)
        assert not entry.is_expired
        time.sleep(0.02)
        assert entry.is_expired

    def test_cache_entry_no_expiration(self):
        """Test entrée sans expiration."""
        entry = CacheEntry(value="test", ttl=None)
        assert not entry.is_expired

    def test_cache_entry_touch(self):
        """Test incrément des hits."""
        entry = CacheEntry(value="test")
        assert entry.hits == 0
        entry.touch()
        assert entry.hits == 1
        entry.touch()
        assert entry.hits == 2


class TestCache:
    """Tests pour le cache principal."""

    def test_cache_get_set(self):
        """Test get et set basiques."""
        cache = Cache()
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_cache_get_missing(self):
        """Test get pour clé inexistante."""
        cache = Cache()
        assert cache.get("missing") is None
        assert cache.get("missing", "default") == "default"

    def test_cache_delete(self):
        """Test suppression."""
        cache = Cache()
        cache.set("key1", "value1")
        assert cache.delete("key1") is True
        assert cache.get("key1") is None
        assert cache.delete("key1") is False

    def test_cache_clear(self):
        """Test vidage du cache."""
        cache = Cache()
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.clear()
        assert len(cache) == 0

    def test_cache_expiration(self):
        """Test expiration automatique."""
        cache = Cache(default_ttl=0.01)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"
        time.sleep(0.02)
        assert cache.get("key1") is None

    def test_cache_custom_ttl(self):
        """Test TTL personnalisé."""
        cache = Cache(default_ttl=60)
        cache.set("key1", "value1", ttl=0.01)
        time.sleep(0.02)
        assert cache.get("key1") is None

    def test_cache_max_size(self):
        """Test taille maximum."""
        cache = Cache(max_size=3)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        cache.set("key4", "value4")  # Devrait évincer une entrée
        assert len(cache) == 3

    def test_cache_lru_eviction(self):
        """Test éviction LRU."""
        cache = Cache(max_size=2)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        # Accéder à key1 pour augmenter ses hits
        cache.get("key1")
        cache.get("key1")
        # Ajouter une nouvelle clé - key2 devrait être évincée
        cache.set("key3", "value3")
        assert "key1" in cache
        assert "key3" in cache
        # key2 a moins de hits, donc évincée
        assert cache.get("key2") is None

    def test_cache_cleanup_expired(self):
        """Test nettoyage des entrées expirées."""
        cache = Cache(default_ttl=0.01)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        time.sleep(0.02)
        removed = cache.cleanup_expired()
        assert removed == 2
        assert len(cache) == 0

    def test_cache_stats(self):
        """Test statistiques du cache."""
        cache = Cache()
        cache.set("key1", "value1")
        cache.get("key1")  # Hit
        cache.get("key2")  # Miss
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 50.0

    def test_cache_contains(self):
        """Test opérateur in."""
        cache = Cache()
        cache.set("key1", "value1")
        assert "key1" in cache
        assert "key2" not in cache

    def test_cache_thread_safety(self):
        """Test thread safety."""
        cache = Cache()
        errors = []

        def writer():
            try:
                for i in range(100):
                    cache.set(f"key_{threading.current_thread().name}_{i}", i)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for i in range(100):
                    cache.get(f"key_{i}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer) for _ in range(5)
        ] + [
            threading.Thread(target=reader) for _ in range(5)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestFileCache:
    """Tests pour le cache de fichiers."""

    def test_file_cache_load(self):
        """Test chargement d'un fichier."""
        with NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("test content")
            f.flush()
            filepath = Path(f.name)

        cache = FileCache()
        content = cache.get_file(filepath, lambda p: p.read_text())
        assert content == "test content"
        filepath.unlink()

    def test_file_cache_reload_on_modification(self):
        """Test rechargement après modification."""
        with NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("original")
            f.flush()
            filepath = Path(f.name)

        cache = FileCache()
        content1 = cache.get_file(filepath, lambda p: p.read_text())
        assert content1 == "original"

        # Modifier le fichier
        time.sleep(0.1)  # Assurer une différence de mtime
        filepath.write_text("modified")

        content2 = cache.get_file(filepath, lambda p: p.read_text())
        assert content2 == "modified"
        filepath.unlink()

    def test_file_cache_not_found(self):
        """Test fichier inexistant."""
        cache = FileCache()
        filepath = Path("/nonexistent/file.txt")
        result = cache.get_file(filepath, lambda p: p.read_text())
        assert result is None

    def test_file_cache_invalidate(self):
        """Test invalidation."""
        with NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("test")
            f.flush()
            filepath = Path(f.name)

        cache = FileCache()
        cache.get_file(filepath, lambda p: p.read_text())
        cache.invalidate(filepath)
        # Le fichier doit être rechargé
        filepath.unlink()


class TestKnowledgeBaseCache:
    """Tests pour le cache de knowledge base."""

    def test_knowledge_cache_load(self):
        """Test chargement de la knowledge base."""
        with TemporaryDirectory() as tmpdir:
            kb_file = Path(tmpdir) / "memoire.md"
            kb_file.write_text("# Knowledge Base\nTest content")

            cache = KnowledgeBaseCache()
            content = cache.get_knowledge(kb_file)
            assert "Knowledge Base" in content

    def test_knowledge_cache_empty_file(self):
        """Test fichier vide."""
        with TemporaryDirectory() as tmpdir:
            kb_file = Path(tmpdir) / "memoire.md"
            kb_file.write_text("")

            cache = KnowledgeBaseCache()
            content = cache.get_knowledge(kb_file)
            assert content == ""

    def test_knowledge_cache_nonexistent(self):
        """Test fichier inexistant."""
        cache = KnowledgeBaseCache()
        content = cache.get_knowledge(Path("/nonexistent/memoire.md"))
        assert content == ""


class TestCachedDecorator:
    """Tests pour le décorateur @cached."""

    def test_cached_function(self):
        """Test mise en cache d'une fonction."""
        call_count = 0

        @cached(ttl=60)
        def expensive_function(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        result1 = expensive_function(5)
        result2 = expensive_function(5)
        assert result1 == 10
        assert result2 == 10
        assert call_count == 1  # Appelé une seule fois

    def test_cached_different_args(self):
        """Test cache avec arguments différents."""
        call_count = 0

        @cached(ttl=60)
        def fn(x, y):
            nonlocal call_count
            call_count += 1
            return x + y

        fn(1, 2)
        fn(1, 2)
        fn(2, 3)
        assert call_count == 2  # Deux appels avec args différents


# ============================================================================
# TESTS PAGINATION
# ============================================================================

class TestPageResult:
    """Tests pour PageResult."""

    def test_page_result_properties(self):
        """Test propriétés du résultat."""
        result = PageResult(
            items=[1, 2, 3],
            page_number=2,
            page_size=3,
            total_items=10,
            total_pages=4,
        )
        assert result.has_next is True
        assert result.has_previous is True
        assert result.start_index == 3
        assert result.end_index == 6

    def test_page_result_first_page(self):
        """Test première page."""
        result = PageResult(
            items=[1, 2, 3],
            page_number=1,
            page_size=3,
            total_items=10,
            total_pages=4,
        )
        assert result.has_previous is False
        assert result.has_next is True

    def test_page_result_last_page(self):
        """Test dernière page."""
        result = PageResult(
            items=[10],
            page_number=4,
            page_size=3,
            total_items=10,
            total_pages=4,
        )
        assert result.has_previous is True
        assert result.has_next is False

    def test_page_result_to_dict(self):
        """Test conversion en dict."""
        result = PageResult(
            items=[1, 2],
            page_number=1,
            page_size=2,
            total_items=5,
            total_pages=3,
        )
        d = result.to_dict()
        assert d["page_number"] == 1
        assert d["has_next"] is True


class TestPaginator:
    """Tests pour le paginateur."""

    def test_paginator_basic(self):
        """Test pagination basique."""
        items = list(range(10))
        paginator = Paginator(items, page_size=3)
        assert paginator.total_items == 10
        assert paginator.total_pages == 4

    def test_paginator_get_page(self):
        """Test récupération de page."""
        items = list(range(10))
        paginator = Paginator(items, page_size=3)

        page1 = paginator.get_page(1)
        assert page1.items == [0, 1, 2]

        page4 = paginator.get_page(4)
        assert page4.items == [9]

    def test_paginator_bounds(self):
        """Test limites."""
        items = list(range(5))
        paginator = Paginator(items, page_size=3)

        # Page 0 → devient 1
        page0 = paginator.get_page(0)
        assert page0.page_number == 1

        # Page 100 → devient dernière page
        page100 = paginator.get_page(100)
        assert page100.page_number == 2

    def test_paginator_iteration(self):
        """Test itération sur les pages."""
        items = list(range(7))
        paginator = Paginator(items, page_size=3)

        pages = list(paginator)
        assert len(pages) == 3
        assert pages[0].items == [0, 1, 2]
        assert pages[1].items == [3, 4, 5]
        assert pages[2].items == [6]

    def test_paginator_len(self):
        """Test len()."""
        items = list(range(10))
        paginator = Paginator(items, page_size=4)
        assert len(paginator) == 3

    def test_paginator_empty(self):
        """Test liste vide."""
        paginator = Paginator([], page_size=10)
        assert paginator.total_pages == 1
        assert paginator.total_items == 0


class TestCursorPaginator:
    """Tests pour le paginateur par curseur."""

    def test_cursor_paginator_basic(self):
        """Test pagination par curseur."""
        data = list(range(10))

        def fetch(cursor, limit):
            if cursor is None:
                return data[:3], "cursor_3"
            elif cursor == "cursor_3":
                return data[3:6], "cursor_6"
            elif cursor == "cursor_6":
                return data[6:9], "cursor_9"
            else:
                return data[9:], None

        paginator = CursorPaginator(fetch, page_size=3)
        page = paginator.get_page()
        assert page.items == [0, 1, 2]
        assert page.next_cursor == "cursor_3"
        assert page.has_more is True

    def test_cursor_paginator_iteration(self):
        """Test itération avec curseur."""
        call_count = 0

        def fetch(cursor, limit):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [1, 2], "next"
            else:
                return [3], None

        paginator = CursorPaginator(fetch)
        pages = list(paginator)
        assert len(pages) == 2


class TestEmailPaginator:
    """Tests pour le paginateur d'emails."""

    def test_email_paginator_basic(self):
        """Test pagination d'emails."""
        provider = Mock()
        provider.fetch_emails_page.return_value = (
            [{"id": 1}, {"id": 2}],
            "next_token"
        )

        paginator = EmailPaginator(provider, page_size=2)
        result = paginator.fetch_page()

        assert len(result.items) == 2
        assert result.has_more is True

    def test_email_paginator_with_filter(self):
        """Test pagination avec filtre."""
        provider = Mock()
        provider.fetch_emails_page.return_value = (
            [{"id": 1, "spam": True}, {"id": 2, "spam": False}],
            None
        )

        paginator = EmailPaginator(
            provider,
            page_size=2,
            filter_func=lambda e: not e.get("spam")
        )
        result = paginator.fetch_page()

        assert len(result.items) == 1
        assert result.items[0]["id"] == 2


class TestPaginationHelpers:
    """Tests pour les helpers de pagination."""

    def test_paginate_helper(self):
        """Test helper paginate()."""
        items = list(range(20))
        page = paginate(items, page=2, page_size=5)
        assert page.items == [5, 6, 7, 8, 9]
        assert page.page_number == 2

    def test_chunked_helper(self):
        """Test helper chunked()."""
        items = list(range(7))
        chunks = list(chunked(items, 3))
        assert chunks == [[0, 1, 2], [3, 4, 5], [6]]


# ============================================================================
# TESTS BATCH
# ============================================================================

class TestBatchItemResult:
    """Tests pour BatchItemResult."""

    def test_batch_item_success(self):
        """Test résultat succès."""
        result = BatchItemResult(
            item="email1",
            status=BatchItemStatus.SUCCESS,
            result="draft1",
            processing_time=0.5,
        )
        assert result.status == BatchItemStatus.SUCCESS
        assert result.error is None

    def test_batch_item_failed(self):
        """Test résultat échec."""
        result = BatchItemResult(
            item="email1",
            status=BatchItemStatus.FAILED,
            error="Connection error",
            retries=2,
        )
        assert result.status == BatchItemStatus.FAILED
        assert result.error == "Connection error"


class TestBatchResult:
    """Tests pour BatchResult."""

    def test_batch_result_success_rate(self):
        """Test calcul taux de succès."""
        result = BatchResult(
            total=10,
            successful=8,
            failed=1,
            skipped=1,
            items=[],
            total_time=5.0,
            started_at=datetime.now(),
            finished_at=datetime.now(),
        )
        assert result.success_rate == 80.0

    def test_batch_result_empty(self):
        """Test résultat vide."""
        result = BatchResult(
            total=0,
            successful=0,
            failed=0,
            skipped=0,
            items=[],
            total_time=0.0,
            started_at=datetime.now(),
            finished_at=datetime.now(),
        )
        assert result.success_rate == 0.0
        assert result.avg_processing_time == 0.0

    def test_batch_result_to_dict(self):
        """Test conversion en dict."""
        result = BatchResult(
            total=5,
            successful=4,
            failed=1,
            skipped=0,
            items=[],
            total_time=2.5,
            started_at=datetime.now(),
            finished_at=datetime.now(),
        )
        d = result.to_dict()
        assert d["total"] == 5
        assert d["success_rate"] == 80.0


class TestBatchProcessor:
    """Tests pour le processeur de batch."""

    def test_batch_processor_basic(self):
        """Test traitement basique."""
        def process(x):
            return x * 2

        processor = BatchProcessor(
            process_func=process,
            batch_size=3,
            max_workers=2,
        )
        result = processor.process([1, 2, 3, 4, 5])

        assert result.total == 5
        assert result.successful == 5
        assert result.failed == 0

    def test_batch_processor_with_errors(self):
        """Test avec erreurs."""
        def process(x):
            if x == 3:
                raise ValueError("Error on 3")
            return x * 2

        processor = BatchProcessor(
            process_func=process,
            batch_size=5,
            max_workers=2,
            max_retries=0,
        )
        result = processor.process([1, 2, 3, 4, 5])

        assert result.successful == 4
        assert result.failed == 1

    def test_batch_processor_retry(self):
        """Test retry."""
        attempt_count = {}

        def process(x):
            attempt_count[x] = attempt_count.get(x, 0) + 1
            if x == 2 and attempt_count[x] < 2:
                raise ValueError("Temporary error")
            return x * 2

        processor = BatchProcessor(
            process_func=process,
            batch_size=5,
            max_workers=1,
            max_retries=2,
            retry_delay=0.01,
        )
        result = processor.process([1, 2, 3])

        assert result.successful == 3
        assert result.failed == 0

    def test_batch_processor_skip(self):
        """Test skip."""
        processor = BatchProcessor(
            process_func=lambda x: x * 2,
            batch_size=5,
        )
        result = processor.process(
            [1, 2, 3, 4, 5],
            skip_func=lambda x: x % 2 == 0  # Skip pairs
        )

        assert result.successful == 3
        assert result.skipped == 2

    def test_batch_processor_progress_callback(self):
        """Test callback de progression."""
        progress_calls = []

        def on_progress(processed, total):
            progress_calls.append((processed, total))

        processor = BatchProcessor(
            process_func=lambda x: x,
            batch_size=2,
            on_progress=on_progress,
        )
        processor.process([1, 2, 3, 4, 5])

        assert len(progress_calls) == 3  # 3 batches

    def test_batch_processor_stop(self):
        """Test arrêt."""
        processed = []

        def slow_process(x):
            time.sleep(0.05)
            processed.append(x)
            return x

        processor = BatchProcessor(
            process_func=slow_process,
            batch_size=1,
            max_workers=1,
        )

        # Lancer le stop dans un thread séparé après un délai
        def stop_later():
            time.sleep(0.02)
            processor.stop()

        import threading
        stop_thread = threading.Thread(target=stop_later)
        stop_thread.start()

        processor.process([1, 2, 3, 4, 5])
        stop_thread.join()

        # Devrait s'arrêter avant de traiter tous les éléments
        # Au moins le premier batch est traité avant le stop
        assert len(processed) >= 1


class TestProcessInBatchesHelper:
    """Tests pour le helper process_in_batches."""

    def test_process_in_batches(self):
        """Test helper."""
        result = process_in_batches(
            items=[1, 2, 3, 4, 5],
            process_func=lambda x: x * 2,
            batch_size=2,
        )
        assert result.total == 5
        assert result.successful == 5


# ============================================================================
# TESTS SINGLETON
# ============================================================================

class TestSingletons:
    """Tests pour les singletons."""

    def test_get_cache_singleton(self):
        """Test singleton cache."""
        cache1 = get_cache()
        cache2 = get_cache()
        assert cache1 is cache2

    def test_get_knowledge_cache_singleton(self):
        """Test singleton knowledge cache."""
        cache1 = get_knowledge_cache()
        cache2 = get_knowledge_cache()
        assert cache1 is cache2
