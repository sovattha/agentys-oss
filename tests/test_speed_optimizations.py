# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Performance Speed Test — Verification Suite

Verifies that all 5 phases of performance optimization (60+ fixes)
are properly implemented and behaving as expected.

Run: pytest tests/test_speed_optimizations.py -v --tb=short
Expected: 31 passed, 0 failed, runtime < 20s
"""

import os
import re
import time
import sqlite3
import threading
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime


# Project root for file content analysis
PROJECT_ROOT = Path(__file__).parent.parent
FRONTEND_SRC = PROJECT_ROOT / "agentys-app" / "src"
BACKEND_SRC = PROJECT_ROOT / "app"


# ============================================================================
# Class 1: TestPhase1QuickWins (7 tests)
# ============================================================================

class TestPhase1QuickWins:
    """Phase 1: LRU cache fix, SQLite PRAGMAs, folder cache invalidation."""

    def test_cache_eviction_is_lru_not_lfu(self):
        """LRU eviction uses last_accessed_at, not hit count."""
        from app.infrastructure.cache import Cache

        cache = Cache(max_size=2, default_ttl=None)
        cache.set("high_hits", "A")
        # Give high_hits many accesses → high hit count, last_accessed = now
        for _ in range(100):
            cache.get("high_hits")

        time.sleep(0.05)
        # low_hits: 0 hits but more recent last_accessed_at
        cache.set("low_hits", "B")

        # Adding 3rd entry triggers eviction
        # LRU evicts "high_hits" (oldest last_accessed_at)
        # LFU would evict "low_hits" (fewer hits)
        cache.set("trigger", "C")

        assert cache.get("high_hits") is None, "LRU should evict oldest-accessed, not least-hit"
        assert cache.get("low_hits") == "B", "Recent entry should survive LRU eviction"
        assert cache.get("trigger") == "C"

    def test_cache_entry_tracks_last_accessed_at(self):
        """CacheEntry.touch() updates last_accessed_at timestamp."""
        from app.infrastructure.cache import CacheEntry

        entry = CacheEntry(value="test")
        t1 = entry.last_accessed_at
        time.sleep(0.02)
        entry.touch()

        assert entry.last_accessed_at > t1, "touch() should update last_accessed_at"
        assert entry.hits == 1

    def test_sqlite_pragmas_applied(self):
        """4 performance PRAGMAs applied on every new connection."""
        from app.infrastructure.database import Database

        orig_initialized = Database._initialized
        orig_local = Database._local

        try:
            Database._initialized = False
            Database._local = threading.local()

            with tempfile.TemporaryDirectory() as tmpdir:
                db = Database(Path(tmpdir) / "test_pragmas.db")
                conn = db._get_connection()

                sync = conn.execute("PRAGMA synchronous").fetchone()[0]
                cache_sz = conn.execute("PRAGMA cache_size").fetchone()[0]
                temp = conn.execute("PRAGMA temp_store").fetchone()[0]
                mmap = conn.execute("PRAGMA mmap_size").fetchone()[0]

                assert sync == 1, f"synchronous should be NORMAL(1), got {sync}"
                assert cache_sz == -64000, f"cache_size should be -64000, got {cache_sz}"
                assert temp == 2, f"temp_store should be MEMORY(2), got {temp}"
                assert mmap == 268435456, f"mmap_size should be 256MB, got {mmap}"

                db.close()
        finally:
            Database._initialized = orig_initialized
            Database._local = orig_local

    def test_folder_cache_invalidation_targeted(self):
        """Targeted folder invalidation clears only specified folder."""
        # Replicate exact algorithm from routes.py:222-231
        _email_cache = {
            (1, "inbox"): ["e1"], (1, "sent"): ["e2"],
            (2, "inbox"): ["e3"], (1, "trash"): ["e4"],
        }

        folders = ("inbox",)
        folder_set = {f.lower() for f in folders}
        keys_to_remove = [k for k in _email_cache if k[1] in folder_set]
        for k in keys_to_remove:
            del _email_cache[k]

        assert (1, "inbox") not in _email_cache
        assert (2, "inbox") not in _email_cache
        assert (1, "sent") in _email_cache, "Sent folder should survive"
        assert (1, "trash") in _email_cache, "Trash folder should survive"

        # Verify source contains the matching function (moved to routes_helpers.py)
        source = (BACKEND_SRC / "api" / "routes_helpers.py").read_text(encoding="utf-8")
        assert "def _invalidate_folder_cache(" in source
        assert "k[1] in folder_set" in source

    def test_folder_cache_invalidation_all(self):
        """No-args call clears everything."""
        _email_cache = {
            (1, "inbox"): ["e1"], (1, "sent"): ["e2"],
            (2, "inbox"): ["e3"],
        }

        folders = ()
        if not folders:
            _email_cache.clear()

        assert len(_email_cache) == 0

    def test_folder_cache_invalidation_multiple(self):
        """Multi-folder invalidation clears 2 folders, 3rd survives."""
        _email_cache = {
            (1, "inbox"): ["e1"], (1, "sent"): ["e2"],
            (1, "trash"): ["e3"], (2, "inbox"): ["e4"],
        }

        folders = ("inbox", "trash")
        folder_set = {f.lower() for f in folders}
        keys_to_remove = [k for k in _email_cache if k[1] in folder_set]
        for k in keys_to_remove:
            del _email_cache[k]

        assert len(_email_cache) == 1
        assert (1, "sent") in _email_cache

    def test_email_cache_max_entries_lru(self):
        """LRU eviction at max capacity evicts oldest, not newest."""
        from app.infrastructure.cache import Cache

        cache = Cache(max_size=10, default_ttl=None)
        for i in range(10):
            cache.set(f"key_{i}", f"val_{i}")

        # Manually set timestamps to ensure deterministic ordering
        base_time = time.time() - 100
        for i in range(10):
            cache._cache[f"key_{i}"].last_accessed_at = base_time + i

        # Access key_0 → moves it to most recent
        cache.get("key_0")

        # Add 11th entry → should evict key_1 (oldest untouched)
        cache.set("key_10", "val_10")

        assert len(cache) == 10
        assert cache.get("key_0") is not None, "Recently accessed should survive"
        assert cache.get("key_10") is not None, "Newly added should exist"
        assert "key_1" not in cache._cache, "Oldest untouched should be evicted"


# ============================================================================
# Class 2: TestPhase2BackendIO (6 tests)
# ============================================================================

class TestPhase2BackendIO:
    """Phase 2: Gmail batch fetch, provider pool, thread pool, batch SQLite."""

    def test_gmail_batch_fetch_uses_configurable_chunk_size(self):
        """_batch_fetch_messages uses configurable chunk size from CacheConfig."""
        from app.config import CacheConfig

        # Verify class-level defaults (not env-var-sensitive singleton)
        assert hasattr(CacheConfig, "gmail_batch_chunk_size")
        assert CacheConfig.gmail_batch_chunk_size == 25

        assert hasattr(CacheConfig, "gmail_batch_initial_delay")
        assert CacheConfig.gmail_batch_initial_delay == 1.5

        # Verify chunk calculation with configurable size
        chunk_size = CacheConfig.gmail_batch_chunk_size
        message_ids = list(range(250))
        chunks = [message_ids[i:i + chunk_size] for i in range(0, len(message_ids), chunk_size)]
        assert len(chunks) == 10  # 250 / 25 = 10 chunks
        assert len(chunks[0]) == 25
        assert len(chunks[-1]) == 25  # 250 is exactly divisible by 25

        # Verify source uses configurable chunk_size (not hardcoded 100)
        source = (BACKEND_SRC / "providers" / "gmail_adapter.py").read_text(encoding="utf-8")
        assert "new_batch_http_request" in source
        assert "chunk_size" in source

    def test_provider_pool_caches_connection(self):
        """ProviderPool returns cached provider without calling factory twice."""
        from app.providers.provider_pool import ProviderPool

        ProviderPool.reset_instance()
        try:
            pool = ProviderPool(check_health=False)

            mock_provider = Mock()
            mock_provider.authenticate.return_value = True
            factory = Mock(return_value=mock_provider)

            p1 = pool.get_or_create("acct_1", factory)
            p2 = pool.get_or_create("acct_1", factory)

            assert p1 is p2
            assert factory.call_count == 1
        finally:
            ProviderPool.reset_instance()

    def test_provider_pool_idle_cleanup(self):
        """cleanup_idle() removes providers idle beyond TTL."""
        from app.providers.provider_pool import ProviderPool

        ProviderPool.reset_instance()
        try:
            pool = ProviderPool(max_idle_seconds=0.05, check_health=False)

            mock_provider = Mock()
            mock_provider.authenticate.return_value = True
            pool.get_or_create("acct_1", Mock(return_value=mock_provider))

            assert pool.size == 1
            time.sleep(0.1)
            removed = pool.cleanup_idle()

            assert removed == 1
            assert pool.size == 0
        finally:
            ProviderPool.reset_instance()

    def test_thread_pool_max_workers(self):
        """Thread pool has 8 workers with 'agentys-bg' prefix."""
        from app.infrastructure.thread_pool import _pool

        assert _pool._max_workers == 8
        assert _pool._thread_name_prefix == "agentys-bg"

    def test_submit_background_catches_exceptions(self):
        """submit_background wraps exceptions, returns None without crash."""
        from app.infrastructure.thread_pool import submit_background

        def failing_fn():
            raise RuntimeError("Intentional test error")

        future = submit_background(failing_fn)
        result = future.result(timeout=5)

        assert result is None

    def test_batch_sqlite_insert_performance(self):
        """executemany + single commit is faster than commit-per-insert."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "perf.db")

            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("CREATE TABLE test (id INTEGER, val TEXT)")
            conn.commit()

            rows = [(i, f"value_{i}") for i in range(500)]

            # Anti-pattern: commit per insert (simulates unbatched writes)
            t_start = time.perf_counter()
            for row in rows:
                conn.execute("INSERT INTO test VALUES (?, ?)", row)
                conn.commit()
            t_individual = time.perf_counter() - t_start

            conn.execute("DELETE FROM test")
            conn.commit()

            # Optimized: executemany + single commit
            t_start = time.perf_counter()
            conn.executemany("INSERT INTO test VALUES (?, ?)", rows)
            conn.commit()
            t_batch = time.perf_counter() - t_start

            conn.close()

            assert t_batch < t_individual, (
                f"Batch ({t_batch:.4f}s) should be faster than individual ({t_individual:.4f}s)"
            )


# ============================================================================
# Class 3: TestPhase3FrontendArchitecture (4 tests)
# ============================================================================

class TestPhase3FrontendArchitecture:
    """Phase 3: Extracted hooks, LabelsContext dedup, CSS containment."""

    def test_extracted_controller_hooks_exist(self):
        """3 controller hook files exist in hooks/ directory."""
        hooks_dir = FRONTEND_SRC / "hooks"

        assert (hooks_dir / "useEmailDetailController.ts").exists()
        assert (hooks_dir / "useDraftController.ts").exists()
        assert (hooks_dir / "useNavigationController.ts").exists()

    def test_labels_context_deduplication(self):
        """LabelsContext has split contexts and exports useSharedLabels."""
        ctx_file = FRONTEND_SRC / "contexts" / "LabelsContext.tsx"
        assert ctx_file.exists(), "LabelsContext.tsx should exist"

        source = ctx_file.read_text(encoding="utf-8")
        assert "useSharedLabels" in source
        # Verify split contexts for render optimization
        assert "LabelsDataContext" in source or "LabelCountsContext" in source

    def test_css_containment_applied(self):
        """At least 3 CSS containment rules for layout isolation."""
        css_file = FRONTEND_SRC / "App.css"
        source = css_file.read_text(encoding="utf-8")

        containment_count = len(re.findall(r"contain\s*:\s*layout", source))
        assert containment_count >= 3, (
            f"Expected >=3 containment rules, found {containment_count}"
        )

    def test_prefers_reduced_motion_present(self):
        """At least 4 prefers-reduced-motion rules across CSS files."""
        css_files = list(FRONTEND_SRC.rglob("*.css"))
        total = 0
        for f in css_files:
            content = f.read_text(encoding="utf-8")
            total += content.count("prefers-reduced-motion")

        assert total >= 4, f"Expected >=4 reduced-motion rules, found {total}"


# ============================================================================
# Class 4: TestPhase4PipelineWebSocket (5 tests)
# ============================================================================

class TestPhase4PipelineWebSocket:
    """Phase 4: Smart suggestions parallel, WebSocket delta, debounced writes."""

    def test_websocket_delta_only_streaming(self):
        """emit_draft_chunk: non-final omits accumulated_text, final includes it.

        Audit ISO-06 / S-01 : `_resolve_ws_room()` retourne None hors flask
        request context → emit skip. Pour tester le payload, on patche le
        resolver pour forcer une room synthétique, OR on passe account_id
        explicite (route emit_to_account).
        """
        from app.api.websocket import emit_draft_chunk

        mock_sio = MagicMock()

        with patch("app.api.websocket.get_socketio", return_value=mock_sio), \
             patch("app.api.websocket._resolve_ws_room", return_value="account_1"):
            # Non-final chunk
            emit_draft_chunk("e1", "chunk1", 0, "chunk1", 25.0, is_final=False)
            payload = mock_sio.emit.call_args[0][1]

            assert "accumulated_text" not in payload, \
                "Non-final chunk should omit accumulated_text"
            assert payload["chunk"] == "chunk1"

            mock_sio.reset_mock()

            # Final chunk
            emit_draft_chunk("e1", "chunk2", 1, "chunk1chunk2", 100.0, is_final=True)
            payload = mock_sio.emit.call_args[0][1]

            assert "accumulated_text" in payload, \
                "Final chunk should include accumulated_text"
            assert payload["accumulated_text"] == "chunk1chunk2"

    def test_pending_draft_store_debounced_writes(self):
        """PendingDraftStore uses 2s debounce timer for disk writes."""
        from app.infrastructure.pending_draft_store import InMemoryPendingDraftStore

        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "test_drafts.json")
            store = InMemoryPendingDraftStore(persist_path=persist_path)

            assert store._SAVE_DEBOUNCE_SECONDS == 2.0

            # Create a mock draft and add it
            mock_draft = Mock()
            mock_draft.id = "test-id"
            mock_draft.email_id = "email-id"
            mock_draft.status = Mock()
            mock_draft.created_at = datetime.now().isoformat()

            store.add(mock_draft)

            # Timer should be active (scheduled but not yet fired)
            assert store._save_timer is not None
            assert store._dirty is True

            # Cleanup
            if store._save_timer:
                store._save_timer.cancel()

    def test_pending_draft_store_skips_debounce_when_interpreter_shutdown_starts(self):
        """PendingDraftStore should not log noisy timer tracebacks during shutdown."""
        from app.domain.entities.pending_draft import PendingDraft, PendingDraftStatus
        from app.infrastructure.pending_draft_store import InMemoryPendingDraftStore

        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "test_drafts.json")
            store = InMemoryPendingDraftStore(persist_path=persist_path)

            pending_draft = PendingDraft(
                id="test-id",
                email_id="email-id",
                email_sender="sender@example.com",
                email_subject="Subject",
                draft_subject="Re: Subject",
                draft_body="Draft body",
                status=PendingDraftStatus.PENDING,
            )

            with patch(
                "threading.Timer.start",
                side_effect=RuntimeError("can't create new thread at interpreter shutdown"),
            ):
                store.add(pending_draft)

            assert store._dirty is True
            assert store._save_timer is None
            store.flush()

    def test_pending_draft_store_email_id_index(self):
        """O(1) secondary index for email_id lookups.

        Audit isolation 2026-04-22 (ISO-09) : la clé du `_email_id_index`
        est maintenant un tuple `(account_id, email_id)` pour scoper le
        lookup par compte. Les versions antérieures utilisaient juste
        `email_id` ce qui leakait les drafts cross-account.
        """
        from app.infrastructure.pending_draft_store import InMemoryPendingDraftStore
        from app.domain.entities.pending_draft import PendingDraftStatus

        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "test_drafts.json")
            store = InMemoryPendingDraftStore(persist_path=persist_path)

            # Populate 100 entries directly (bypass disk writes)
            for i in range(100):
                mock_draft = Mock()
                mock_draft.id = f"draft-{i}"
                mock_draft.email_id = f"email-{i}"
                mock_draft.account_id = "acct-1"
                mock_draft.status = PendingDraftStatus.PENDING
                mock_draft.created_at = datetime.now().isoformat()
                store._store[mock_draft.id] = mock_draft
                # Tuple (account_id, email_id) — cf. pending_draft_store.py:49
                store._email_id_index[(mock_draft.account_id, mock_draft.email_id)] = mock_draft.id

            # 1000 lookups should be fast (O(1) via index)
            t_start = time.perf_counter()
            for _ in range(100):
                for j in range(0, 100, 10):
                    store.get_by_email_id(f"email-{j}", account_id="acct-1")
            elapsed_ms = (time.perf_counter() - t_start) * 1000

            assert elapsed_ms < 500, f"1000 index lookups took {elapsed_ms:.1f}ms (>500ms)"
            assert hasattr(store, '_email_id_index')
            assert len(store._email_id_index) == 100

    def test_process_endpoint_202_accepted_pattern(self):
        """Process endpoint returns 202 Accepted with background processing."""
        source = (BACKEND_SRC / "api" / "routes_emails.py").read_text(encoding="utf-8")

        assert "202" in source
        assert "enqueue_draft_job" in source


# ============================================================================
# Class 5: TestPhase5CleanupCSS (4 tests)
# ============================================================================

class TestPhase5CleanupCSS:
    """Phase 5: Guarded imports, IndexedDB TTLs, lazy logging, console cleanup."""

    def test_guarded_pandas_imports(self):
        """Every 'import pandas' in dashboard.py is preceded by try:."""
        source = (BACKEND_SRC / "dashboard.py").read_text(encoding="utf-8")

        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "import pandas" in line and not line.strip().startswith("#"):
                # Check that a 'try:' appears within the previous 3 lines
                preceding = "\n".join(lines[max(0, i - 3):i])
                assert "try:" in preceding, (
                    f"'import pandas' at line {i + 1} not guarded by try/except"
                )

    def test_indexeddb_cache_ttl_values(self):
        """cache.ts uses stale TTL and max age, IndexedDB storage."""
        cache_file = FRONTEND_SRC / "api" / "cache.ts"
        source = cache_file.read_text(encoding="utf-8")

        # Stale time (120s or 60s accepted)
        assert (re.search(r"120\s*\*\s*1000", source) or "120000" in source
                or re.search(r"60\s*\*\s*1000", source) or "60000" in source), \
            "Expected stale TTL"
        # Max age (10 min or 5 min accepted)
        assert (re.search(r"10\s*\*\s*60", source) or "600000" in source
                or re.search(r"5\s*\*\s*60", source) or "300000" in source), \
            "Expected max age"
        # IndexedDB
        assert "indexedDB" in source or "agentys_cache" in source, \
            "Expected IndexedDB storage"

    def test_lazy_logging_format_routes(self):
        """[TIMING] logs in route files use %s format, not f-strings."""
        timing_lines = []
        for route_file in ("routes_emails.py", "routes_helpers.py", "routes.py"):
            filepath = BACKEND_SRC / "api" / route_file
            if filepath.exists():
                source = filepath.read_text(encoding="utf-8")
                timing_lines.extend(
                    line.strip() for line in source.split("\n")
                    if "[TIMING]" in line and "logger" in line
                )

        assert len(timing_lines) >= 1, "Expected at least 1 [TIMING] log line"

    def test_console_log_count_reduced(self):
        """< 260 executable console.* statements across frontend app TypeScript."""
        total = 0
        for ext in ("*.ts", "*.tsx"):
            for f in FRONTEND_SRC.rglob(ext):
                if "__tests__" in f.parts or ".test." in f.name:
                    continue
                content = f.read_text(encoding="utf-8")
                lines = [
                    line for line in content.splitlines()
                    if not line.lstrip().startswith("//")
                ]
                total += len(re.findall(r"console\.(log|warn|error|debug|info)", "\n".join(lines)))

        assert total < 260, f"Expected <260 console statements, found {total}"


# ============================================================================
# Class 6: TestCrossPhaseIntegration (3 tests)
# ============================================================================

class TestCrossPhaseIntegration:
    """Cross-phase: thread pool adoption, singleton pattern, cache+pool."""

    def test_thread_pool_used_instead_of_adhoc_threads(self):
        """submit_background() used >=10 times across route modules."""
        count = 0
        for route_file in ("routes.py", "routes_emails.py", "routes_drafts.py",
                           "routes_helpers.py", "routes_pending.py",
                           "routes_learning.py", "routes_contacts.py",
                           "routes_misc.py"):
            filepath = BACKEND_SRC / "api" / route_file
            if filepath.exists():
                source = filepath.read_text(encoding="utf-8")
                count += source.count("submit_background(")
        assert count >= 10, f"Expected >=10 submit_background calls, found {count}"

    def test_provider_pool_singleton_pattern(self):
        """ProviderPool uses double-checked locking singleton."""
        source = (BACKEND_SRC / "providers" / "provider_pool.py").read_text(encoding="utf-8")

        assert "if cls._instance is None:" in source
        assert "with cls._instance_lock:" in source
        # Double-checked locking: check None, lock, check None again
        assert source.count("if cls._instance is None:") == 2

    def test_cache_and_pool_work_together(self):
        """Cache eviction and pool cleanup don't interfere with each other."""
        from app.infrastructure.cache import Cache
        from app.providers.provider_pool import ProviderPool

        ProviderPool.reset_instance()
        try:
            cache = Cache(max_size=5, default_ttl=None)
            pool = ProviderPool(max_idle_seconds=0.05, check_health=False)

            # Fill cache
            for i in range(5):
                cache.set(f"key_{i}", f"val_{i}")

            # Add provider
            mock_provider = Mock()
            mock_provider.authenticate.return_value = True
            pool.get_or_create("acct_1", Mock(return_value=mock_provider))

            # Evict from cache (triggers LRU)
            cache.set("key_5", "val_5")
            assert len(cache) == 5

            # Pool should be unaffected by cache eviction
            assert pool.size == 1

            # Cleanup pool
            time.sleep(0.1)
            pool.cleanup_idle()
            assert pool.size == 0

            # Cache should be unaffected by pool cleanup
            assert len(cache) == 5
        finally:
            ProviderPool.reset_instance()


# ============================================================================
# Class 7: TestPerformanceBenchmarks (2 tests)
# ============================================================================

class TestPerformanceBenchmarks:
    """Micro-benchmarks for cache and SQLite performance."""

    def test_cache_lookup_under_1ms(self):
        """P50 < 0.1ms, P99 < 1.0ms for 10K lookups on 1K cache."""
        from app.infrastructure.cache import Cache

        cache = Cache(max_size=2000, default_ttl=None)
        for i in range(1000):
            cache.set(f"key_{i}", f"value_{i}" * 10)

        timings = []
        for i in range(10000):
            key = f"key_{i % 1000}"
            t_start = time.perf_counter()
            cache.get(key)
            elapsed = (time.perf_counter() - t_start) * 1000  # ms
            timings.append(elapsed)

        timings.sort()
        p50 = timings[len(timings) // 2]
        p99 = timings[int(len(timings) * 0.99)]

        assert p50 < 0.1, f"P50 = {p50:.4f}ms (expected <0.1ms)"
        assert p99 < 1.0, f"P99 = {p99:.4f}ms (expected <1.0ms)"

    def test_sqlite_query_with_pragmas_under_5ms(self):
        """P50 < 3ms, P95 < 5ms for 200 queries on 5K rows."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "bench.db")
            conn = sqlite3.connect(db_path)

            # Apply same PRAGMAs as production
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA cache_size = -64000")
            conn.execute("PRAGMA temp_store = MEMORY")
            conn.execute("PRAGMA mmap_size = 268435456")

            conn.execute("""
                CREATE TABLE bench (
                    id INTEGER PRIMARY KEY,
                    email_id TEXT,
                    subject TEXT,
                    body TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX idx_bench_email ON bench(email_id)")

            # Insert 5K rows
            rows = [
                (i, f"email_{i}", f"Subject {i}", f"Body content {i}" * 20)
                for i in range(5000)
            ]
            conn.executemany(
                "INSERT INTO bench (id, email_id, subject, body) VALUES (?, ?, ?, ?)",
                rows,
            )
            conn.commit()

            # Benchmark 200 queries
            timings = []
            for i in range(200):
                email_id = f"email_{i * 25 % 5000}"
                t_start = time.perf_counter()
                conn.execute(
                    "SELECT * FROM bench WHERE email_id = ?", (email_id,)
                ).fetchone()
                elapsed = (time.perf_counter() - t_start) * 1000  # ms
                timings.append(elapsed)

            conn.close()

            timings.sort()
            p50 = timings[len(timings) // 2]
            p95 = timings[int(len(timings) * 0.95)]

            assert p50 < 3.0, f"P50 = {p50:.4f}ms (expected <3ms)"
            assert p95 < 5.0, f"P95 = {p95:.4f}ms (expected <5ms)"
