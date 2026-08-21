# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for app/infrastructure/cache.py"""

import sys
import time
import threading
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from app.infrastructure.cache import (
    CacheEntry,
    Cache,
    FileCache,
    KnowledgeBaseCache,
    cached,
    get_cache,
    get_knowledge_cache,
)


# ============================================================================
# CACHE ENTRY TESTS
# ============================================================================


class TestCacheEntry:
    """Tests for CacheEntry dataclass."""

    def test_create_entry_with_value(self):
        """Test creating entry with value."""
        entry = CacheEntry(value="test_value")
        assert entry.value == "test_value"
        assert entry.hits == 0
        assert entry.ttl is None

    def test_create_entry_with_ttl(self):
        """Test creating entry with TTL."""
        entry = CacheEntry(value=42, ttl=60.0)
        assert entry.value == 42
        assert entry.ttl == 60.0

    def test_is_expired_no_ttl(self):
        """Test entry without TTL never expires."""
        entry = CacheEntry(value="data", ttl=None)
        assert entry.is_expired is False

    def test_is_expired_not_yet(self):
        """Test entry not expired within TTL."""
        entry = CacheEntry(value="data", ttl=300.0)
        assert entry.is_expired is False

    def test_is_expired_after_ttl(self):
        """Test entry expires after TTL."""
        entry = CacheEntry(value="data", ttl=0.001)
        time.sleep(0.002)
        assert entry.is_expired is True

    def test_touch_increments_hits(self):
        """Test touch increments hit counter."""
        entry = CacheEntry(value="data")
        assert entry.hits == 0
        entry.touch()
        assert entry.hits == 1
        entry.touch()
        entry.touch()
        assert entry.hits == 3

    def test_created_at_timestamp(self):
        """Test created_at is set to current time."""
        before = time.time()
        entry = CacheEntry(value="data")
        after = time.time()
        assert before <= entry.created_at <= after

    def test_generic_typing(self):
        """Test CacheEntry works with different types."""
        int_entry = CacheEntry[int](value=42)
        str_entry = CacheEntry[str](value="hello")
        dict_entry = CacheEntry[dict](value={"key": "value"})

        assert int_entry.value == 42
        assert str_entry.value == "hello"
        assert dict_entry.value == {"key": "value"}


# ============================================================================
# CACHE TESTS
# ============================================================================


class TestCache:
    """Tests for Cache class."""

    def test_create_cache_defaults(self):
        """Test creating cache with default settings."""
        cache = Cache()
        assert cache.max_size == 1000
        assert cache.default_ttl == 300

    def test_create_cache_custom_settings(self):
        """Test creating cache with custom settings."""
        cache = Cache(max_size=100, default_ttl=60)
        assert cache.max_size == 100
        assert cache.default_ttl == 60

    def test_set_and_get(self):
        """Test basic set and get."""
        cache = Cache()
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_missing_key(self):
        """Test getting non-existent key returns None."""
        cache = Cache()
        assert cache.get("nonexistent") is None

    def test_get_with_default(self):
        """Test getting with custom default value."""
        cache = Cache()
        assert cache.get("missing", default="fallback") == "fallback"

    def test_get_expired_entry(self):
        """Test getting expired entry returns default."""
        cache = Cache(default_ttl=0.001)
        cache.set("key", "value")
        time.sleep(0.002)
        assert cache.get("key") is None

    def test_set_with_custom_ttl(self):
        """Test set with custom TTL."""
        cache = Cache(default_ttl=300)
        cache.set("key", "value", ttl=0.001)
        time.sleep(0.002)
        assert cache.get("key") is None

    def test_set_updates_existing(self):
        """Test set updates existing key."""
        cache = Cache()
        cache.set("key", "value1")
        cache.set("key", "value2")
        assert cache.get("key") == "value2"

    def test_delete_existing(self):
        """Test deleting existing key."""
        cache = Cache()
        cache.set("key", "value")
        result = cache.delete("key")
        assert result is True
        assert cache.get("key") is None

    def test_delete_nonexistent(self):
        """Test deleting non-existent key."""
        cache = Cache()
        result = cache.delete("nonexistent")
        assert result is False

    def test_clear(self):
        """Test clearing the cache."""
        cache = Cache()
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.clear()
        assert len(cache) == 0

    def test_len(self):
        """Test __len__ returns entry count."""
        cache = Cache()
        assert len(cache) == 0
        cache.set("key1", "value1")
        assert len(cache) == 1
        cache.set("key2", "value2")
        assert len(cache) == 2

    def test_contains_existing(self):
        """Test __contains__ for existing key."""
        cache = Cache()
        cache.set("key", "value")
        assert "key" in cache

    def test_contains_missing(self):
        """Test __contains__ for missing key."""
        cache = Cache()
        assert "missing" not in cache

    def test_contains_expired(self):
        """Test __contains__ for expired key."""
        cache = Cache(default_ttl=0.001)
        cache.set("key", "value")
        time.sleep(0.002)
        assert "key" not in cache

    def test_eviction_on_max_size(self):
        """Test LRU eviction when max_size reached."""
        cache = Cache(max_size=2)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        # Access key1 so its last_accessed_at is more recent than key2's.
        # Sleep briefly to guarantee a distinct timestamp on Windows
        # where time.time() resolution can be ~15ms.
        time.sleep(0.02)
        cache.get("key1")
        # Add key3, should evict key2 (least recently used)
        cache.set("key3", "value3")
        assert "key1" in cache
        assert "key3" in cache
        assert "key2" not in cache

    def test_eviction_counter(self):
        """Test eviction counter is incremented."""
        cache = Cache(max_size=1)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        stats = cache.get_stats()
        assert stats["evictions"] == 1

    def test_cleanup_expired(self):
        """Test cleanup_expired removes expired entries."""
        cache = Cache()
        cache.set("key1", "value1", ttl=0.001)
        cache.set("key2", "value2", ttl=300)
        time.sleep(0.002)
        removed = cache.cleanup_expired()
        assert removed == 1
        assert "key1" not in cache
        assert "key2" in cache

    def test_get_stats(self):
        """Test get_stats returns correct statistics."""
        cache = Cache(max_size=100)
        cache.set("key1", "value1")
        cache.get("key1")  # hit
        cache.get("key1")  # hit
        cache.get("missing")  # miss

        stats = cache.get_stats()
        assert stats["size"] == 1
        assert stats["max_size"] == 100
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 66.67
        assert stats["evictions"] == 0

    def test_get_stats_empty_cache(self):
        """Test get_stats on empty cache."""
        cache = Cache()
        stats = cache.get_stats()
        assert stats["size"] == 0
        assert stats["hit_rate"] == 0

    def test_hit_miss_tracking(self):
        """Test hit and miss counters."""
        cache = Cache()
        cache.set("key", "value")

        # Hits
        cache.get("key")
        cache.get("key")

        # Misses
        cache.get("missing1")
        cache.get("missing2")
        cache.get("missing3")

        stats = cache.get_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 3

    def test_thread_safety(self):
        """Test cache is thread-safe."""
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
                for _ in range(100):
                    cache.get("key_0")
                    cache.get("nonexistent")
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            threads.append(threading.Thread(target=writer, name=f"writer_{i}"))
            threads.append(threading.Thread(target=reader, name=f"reader_{i}"))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_evict_lru_empty_cache(self):
        """Test _evict_lru on empty cache doesn't crash."""
        cache = Cache(max_size=1)
        cache._evict_lru()  # Should not raise

    def test_different_value_types(self):
        """Test cache works with different value types."""
        cache = Cache()
        cache.set("int", 42)
        cache.set("str", "hello")
        cache.set("list", [1, 2, 3])
        cache.set("dict", {"a": 1})
        cache.set("none", None)

        assert cache.get("int") == 42
        assert cache.get("str") == "hello"
        assert cache.get("list") == [1, 2, 3]
        assert cache.get("dict") == {"a": 1}
        # Note: None is valid but indistinguishable from cache miss

    def test_set_no_ttl_overrides_default(self):
        """Test set with ttl=None uses default_ttl."""
        cache = Cache(default_ttl=60)
        cache.set("key", "value", ttl=None)
        entry = cache._cache["key"]
        assert entry.ttl == 60

    def test_set_ttl_zero(self):
        """Test set with ttl=0 expires immediately."""
        cache = Cache(default_ttl=300)
        cache.set("key", "value", ttl=0)
        # TTL=0 means immediate expiration check
        time.sleep(0.001)
        assert cache.get("key") is None


# ============================================================================
# FILE CACHE TESTS
# ============================================================================


class TestFileCache:
    """Tests for FileCache class."""

    def test_create_with_default_cache(self):
        """Test creating FileCache with default cache."""
        file_cache = FileCache()
        assert file_cache._cache is not None

    def test_create_with_custom_cache(self):
        """Test creating FileCache with custom cache."""
        custom_cache = Cache(max_size=10)
        file_cache = FileCache(cache=custom_cache)
        # FileCache uses provided cache or creates new one
        assert isinstance(file_cache._cache, Cache)

    def test_get_file_loads_content(self, tmp_path):
        """Test get_file loads file content."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("file content")

        file_cache = FileCache()
        loader = Mock(return_value="loaded content")

        result = file_cache.get_file(test_file, loader)

        assert result == "loaded content"
        loader.assert_called_once_with(test_file)

    def test_get_file_uses_cache(self, tmp_path):
        """Test get_file uses cached content on second call."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("file content")

        file_cache = FileCache()
        loader = Mock(return_value="loaded content")

        # First call - loads
        result1 = file_cache.get_file(test_file, loader)
        # Second call - from cache
        result2 = file_cache.get_file(test_file, loader)

        assert result1 == "loaded content"
        assert result2 == "loaded content"
        assert loader.call_count == 1

    def test_get_file_reloads_on_modification(self, tmp_path):
        """Test get_file reloads when file is modified."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("original content")

        file_cache = FileCache()
        load_count = [0]

        def loader(path):
            load_count[0] += 1
            return path.read_text()

        # First load
        result1 = file_cache.get_file(test_file, loader)
        assert result1 == "original content"

        # Modify file (ensure mtime changes)
        time.sleep(0.01)
        test_file.write_text("modified content")

        # Should reload
        result2 = file_cache.get_file(test_file, loader)
        assert result2 == "modified content"
        assert load_count[0] == 2

    def test_get_file_not_found(self, tmp_path):
        """Test get_file returns None for non-existent file."""
        test_file = tmp_path / "nonexistent.txt"

        file_cache = FileCache()
        loader = Mock()

        result = file_cache.get_file(test_file, loader)

        assert result is None
        loader.assert_not_called()

    def test_get_file_deleted_file(self, tmp_path):
        """Test get_file handles deleted file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        file_cache = FileCache()
        loader = Mock(return_value="content")

        # Load first time
        file_cache.get_file(test_file, loader)

        # Delete file
        test_file.unlink()

        # Should return None
        result = file_cache.get_file(test_file, loader)
        assert result is None

    def test_invalidate(self, tmp_path):
        """Test invalidate removes file from cache."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        file_cache = FileCache()
        loader = Mock(return_value="content")

        # Load
        file_cache.get_file(test_file, loader)
        assert loader.call_count == 1

        # Invalidate
        file_cache.invalidate(test_file)

        # Should reload
        file_cache.get_file(test_file, loader)
        assert loader.call_count == 2

    def test_clear(self, tmp_path):
        """Test clear removes all cached files."""
        test_file1 = tmp_path / "test1.txt"
        test_file2 = tmp_path / "test2.txt"
        test_file1.write_text("content1")
        test_file2.write_text("content2")

        file_cache = FileCache()
        loader = Mock(side_effect=lambda p: p.read_text())

        # Load both
        file_cache.get_file(test_file1, loader)
        file_cache.get_file(test_file2, loader)
        assert loader.call_count == 2

        # Clear
        file_cache.clear()

        # Should reload both
        file_cache.get_file(test_file1, loader)
        file_cache.get_file(test_file2, loader)
        assert loader.call_count == 4


# ============================================================================
# KNOWLEDGE BASE CACHE TESTS
# ============================================================================


class TestKnowledgeBaseCache:
    """Tests for KnowledgeBaseCache class."""

    def test_create_instance(self):
        """Test creating KnowledgeBaseCache instance."""
        kb_cache = KnowledgeBaseCache()
        assert kb_cache._file_cache is not None
        assert kb_cache._knowledge_path is None

    def test_get_knowledge_from_file(self, tmp_path):
        """Test get_knowledge loads from file."""
        test_file = tmp_path / "memoire.md"
        test_file.write_text("# Knowledge Base\n\nTest content")

        kb_cache = KnowledgeBaseCache()
        result = kb_cache.get_knowledge(test_file)

        assert result == "# Knowledge Base\n\nTest content"

    def test_get_knowledge_nonexistent_file(self, tmp_path):
        """Test get_knowledge returns empty string for missing file."""
        test_file = tmp_path / "nonexistent.md"

        kb_cache = KnowledgeBaseCache()
        result = kb_cache.get_knowledge(test_file)

        assert result == ""

    def test_get_knowledge_uses_cache(self, tmp_path):
        """Test get_knowledge uses cache on subsequent calls."""
        test_file = tmp_path / "memoire.md"
        test_file.write_text("content")

        kb_cache = KnowledgeBaseCache()

        # Spy on read_text
        with patch.object(Path, 'read_text', return_value="content"):
            result1 = kb_cache.get_knowledge(test_file)
            result2 = kb_cache.get_knowledge(test_file)

            assert result1 == "content"
            assert result2 == "content"
            # Note: Due to FileCache logic, this depends on mtime

    def test_get_knowledge_default_path(self, tmp_path):
        """Test get_knowledge uses default path when None."""
        with patch('app.config.KNOWLEDGE_DIR', tmp_path):
            test_file = tmp_path / "memoire.md"
            test_file.write_text("default knowledge")

            kb_cache = KnowledgeBaseCache()
            result = kb_cache.get_knowledge(None)

            assert result == "default knowledge"

    def test_get_knowledge_default_path_not_exists(self, tmp_path):
        """Test get_knowledge returns empty when default doesn't exist."""
        with patch('app.config.KNOWLEDGE_DIR', tmp_path):
            # Don't create the file
            kb_cache = KnowledgeBaseCache()
            result = kb_cache.get_knowledge(None)

            assert result == ""

    def test_invalidate(self, tmp_path):
        """Test invalidate clears the cache."""
        test_file = tmp_path / "memoire.md"
        test_file.write_text("content")

        kb_cache = KnowledgeBaseCache()

        # Load
        kb_cache.get_knowledge(test_file)

        # Invalidate
        kb_cache.invalidate()

        # Modify file
        time.sleep(0.01)
        test_file.write_text("new content")

        # Should get new content
        result = kb_cache.get_knowledge(test_file)
        assert result == "new content"

    def test_empty_file_returns_empty_string(self, tmp_path):
        """Test empty file returns empty string."""
        test_file = tmp_path / "memoire.md"
        test_file.write_text("")

        kb_cache = KnowledgeBaseCache()
        result = kb_cache.get_knowledge(test_file)

        assert result == ""


# ============================================================================
# CACHED DECORATOR TESTS
# ============================================================================


class TestCachedDecorator:
    """Tests for @cached decorator."""

    def setup_method(self):
        """Reset global cache before each test."""
        import app.infrastructure.cache as cache_module
        cache_module._cache = None

    def test_cached_basic(self):
        """Test basic caching of function result."""
        call_count = [0]

        @cached(ttl=60)
        def expensive_function():
            call_count[0] += 1
            return "result"

        result1 = expensive_function()
        result2 = expensive_function()

        assert result1 == "result"
        assert result2 == "result"
        assert call_count[0] == 1

    def test_cached_with_args(self):
        """Test caching with function arguments."""
        call_count = [0]

        @cached(ttl=60)
        def add(a, b):
            call_count[0] += 1
            return a + b

        result1 = add(1, 2)
        result2 = add(1, 2)
        result3 = add(2, 3)

        assert result1 == 3
        assert result2 == 3
        assert result3 == 5
        assert call_count[0] == 2  # Different args = different cache key

    def test_cached_with_kwargs(self):
        """Test caching with keyword arguments."""
        call_count = [0]

        @cached(ttl=60)
        def greet(name, greeting="Hello"):
            call_count[0] += 1
            return f"{greeting}, {name}!"

        result1 = greet("Alice")
        result2 = greet("Alice")
        result3 = greet("Alice", greeting="Hi")

        assert result1 == "Hello, Alice!"
        assert result2 == "Hello, Alice!"
        assert result3 == "Hi, Alice!"
        assert call_count[0] == 2

    def test_cached_expiration(self):
        """Test cache expires after TTL."""
        call_count = [0]

        @cached(ttl=0.001)
        def get_data():
            call_count[0] += 1
            return "data"

        result1 = get_data()
        time.sleep(0.002)
        result2 = get_data()

        assert result1 == "data"
        assert result2 == "data"
        assert call_count[0] == 2

    def test_cached_with_key_prefix(self):
        """Test caching with custom key prefix."""
        call_count = [0]

        @cached(ttl=60, key_prefix="my_prefix")
        def compute():
            call_count[0] += 1
            return "computed"

        result1 = compute()
        compute()

        assert result1 == "computed"
        assert call_count[0] == 1

    def test_cached_preserves_function_metadata(self):
        """Test decorator preserves function name and docstring."""
        @cached(ttl=60)
        def documented_function():
            """This is the docstring."""
            return "result"

        assert documented_function.__name__ == "documented_function"
        assert documented_function.__doc__ == "This is the docstring."

    def test_cached_different_functions_different_cache(self):
        """Test different functions have different cache keys."""
        @cached(ttl=60)
        def func_a():
            return "a"

        @cached(ttl=60)
        def func_b():
            return "b"

        assert func_a() == "a"
        assert func_b() == "b"

    def test_cached_with_none_return(self):
        """Test caching functions that return None."""
        call_count = [0]

        @cached(ttl=60)
        def returns_none():
            call_count[0] += 1
            return None

        # Note: None is not cached (treated as cache miss)
        result1 = returns_none()
        result2 = returns_none()

        assert result1 is None
        assert result2 is None
        # Both calls execute because None is not cacheable


# ============================================================================
# SINGLETON TESTS
# ============================================================================


class TestSingletons:
    """Tests for singleton accessor functions."""

    def setup_method(self):
        """Reset singletons before each test."""
        import app.infrastructure.cache as cache_module
        cache_module._cache = None
        cache_module._knowledge_cache = None

    def test_get_cache_returns_cache(self):
        """Test get_cache returns Cache instance."""
        cache = get_cache()
        assert isinstance(cache, Cache)

    def test_get_cache_singleton(self):
        """Test get_cache returns same instance."""
        cache1 = get_cache()
        cache2 = get_cache()
        assert cache1 is cache2

    def test_get_knowledge_cache_returns_instance(self):
        """Test get_knowledge_cache returns KnowledgeBaseCache instance."""
        kb_cache = get_knowledge_cache()
        assert isinstance(kb_cache, KnowledgeBaseCache)

    def test_get_knowledge_cache_singleton(self):
        """Test get_knowledge_cache returns same instance."""
        kb_cache1 = get_knowledge_cache()
        kb_cache2 = get_knowledge_cache()
        assert kb_cache1 is kb_cache2


# ============================================================================
# EDGE CASES
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_cache_with_unicode_keys(self):
        """Test cache with unicode keys."""
        cache = Cache()
        cache.set("clé_française", "valeur")
        cache.set("日本語", "japanese")
        cache.set("emoji_🚀", "rocket")

        assert cache.get("clé_française") == "valeur"
        assert cache.get("日本語") == "japanese"
        assert cache.get("emoji_🚀") == "rocket"

    def test_cache_with_large_values(self):
        """Test cache with large values."""
        cache = Cache()
        large_value = "x" * 1_000_000  # 1MB string
        cache.set("large", large_value)

        assert cache.get("large") == large_value

    def test_cache_entry_hits_overflow(self):
        """Test hits counter handles many increments."""
        entry = CacheEntry(value="test")
        for _ in range(100000):
            entry.touch()
        assert entry.hits == 100000

    def test_cache_negative_ttl(self):
        """Test cache with negative TTL expires immediately."""
        cache = Cache()
        cache.set("key", "value", ttl=-1)
        assert cache.get("key") is None

    def test_cache_zero_max_size(self):
        """Test cache with zero max_size."""
        cache = Cache(max_size=0)
        cache.set("key", "value")
        # With max_size=0, entry should be evicted immediately
        # or not stored at all (depends on implementation)

    @pytest.mark.skipif(sys.platform == "win32", reason="Symlinks require elevated privileges on Windows")
    def test_file_cache_symlink(self, tmp_path):
        """Test file cache handles symlinks."""
        real_file = tmp_path / "real.txt"
        real_file.write_text("real content")

        link_file = tmp_path / "link.txt"
        link_file.symlink_to(real_file)

        file_cache = FileCache()
        loader = Mock(return_value="content")

        result = file_cache.get_file(link_file, loader)
        assert result == "content"

    def test_concurrent_cache_modifications(self):
        """Test concurrent modifications don't corrupt cache."""
        cache = Cache(max_size=100)
        errors = []

        def modifier(thread_id):
            try:
                for i in range(100):
                    key = f"key_{thread_id}_{i}"
                    cache.set(key, i)
                    cache.get(key)
                    cache.delete(key)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=modifier, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_cache_stats_during_operations(self):
        """Test stats remain consistent during operations."""
        cache = Cache(max_size=10)

        for i in range(20):
            cache.set(f"key_{i}", i)

        stats = cache.get_stats()
        assert stats["size"] <= stats["max_size"]
        assert stats["evictions"] >= 10  # At least 10 evictions

    def test_file_cache_special_characters_in_path(self, tmp_path):
        """Test file cache with special characters in path."""
        special_dir = tmp_path / "dir with spaces & symbols!"
        special_dir.mkdir()
        test_file = special_dir / "file (1).txt"
        test_file.write_text("content")

        file_cache = FileCache()
        loader = Mock(return_value="content")

        result = file_cache.get_file(test_file, loader)
        assert result == "content"
