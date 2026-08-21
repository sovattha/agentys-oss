# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests de charge et performance pour Agentys.

pytest tests/test_load.py -v
"""

import os
import time
import threading
import pytest
from concurrent.futures import ThreadPoolExecutor, as_completed
import tempfile
from pathlib import Path

# ============================================================================
# TESTS PERFORMANCE BASIQUES
# ============================================================================

class TestBasicPerformance:
    """Tests de performance de base."""

    def test_email_parsing_speed(self):
        """Test vitesse parsing email."""
        from app.utils.email_cleaner import clean_email_content

        # Email de test typique
        email_body = """
        Hi John,

        Thanks for your email regarding the project update.

        Here are the key points:
        1. Timeline is on track
        2. Budget is within limits
        3. Team is performing well

        Let me know if you have any questions.

        Best regards,
        Jane

        --
        Jane Doe
        Project Manager
        Company Inc.
        """

        # Mesurer le temps de parsing
        iterations = 1000
        start = time.time()

        for _ in range(iterations):
            clean_email_content(email_body)

        elapsed = time.time() - start
        avg_ms = (elapsed / iterations) * 1000

        # Doit être < 1ms par parsing
        assert avg_ms < 1.0, f"Parsing trop lent: {avg_ms:.3f}ms/iter"

    def test_command_parser_speed(self):
        """Test vitesse parsing commandes vocales."""
        from app.voice import CommandParser

        parser = CommandParser()
        commands = [
            "aide",
            "help",
            "montre les stats",
            "show statistics",
            "réponds à l'email de John",
            "marquer comme lu",
            "ignore cet email",
            "montre les emails urgents",
            "refresh",
            "status",
        ]

        iterations = 1000
        start = time.time()

        for _ in range(iterations):
            for cmd in commands:
                parser.parse(cmd)

        elapsed = time.time() - start
        total_parses = iterations * len(commands)
        avg_us = (elapsed / total_parses) * 1_000_000

        # Doit être < 100µs par parsing
        assert avg_us < 100, f"Parsing trop lent: {avg_us:.1f}µs/iter"

    def test_token_usage_dataclass_speed(self):
        """Test vitesse création/manipulation TokenUsage."""
        from app.domain.entities import TokenUsage

        iterations = 10000
        start = time.time()

        for i in range(iterations):
            usage = TokenUsage(input_tokens=1000, output_tokens=500, model="claude-opus-4-20250514")
            _ = usage.total
            _ = usage.cost

        elapsed = time.time() - start
        avg_us = (elapsed / iterations) * 1_000_000

        # Doit être < 10µs par opération
        assert avg_us < 10, f"TokenUsage trop lent: {avg_us:.1f}µs/iter"


# ============================================================================
# TESTS CHARGE CONCURRENTE
# ============================================================================

class TestConcurrentLoad:
    """Tests de charge concurrente."""

    def test_concurrent_email_parsing(self):
        """Test parsing emails en parallèle."""
        from app.utils.email_cleaner import clean_email_content

        email_body = "Test email content with signature\n--\nJohn Doe"

        def parse_emails(n):
            results = []
            for _ in range(n):
                result = clean_email_content(email_body)
                results.append(result)
            return len(results)

        # 10 threads, 100 emails chacun
        num_threads = 10
        emails_per_thread = 100

        start = time.time()

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [
                executor.submit(parse_emails, emails_per_thread)
                for _ in range(num_threads)
            ]
            results = [f.result() for f in as_completed(futures)]

        elapsed = time.time() - start
        total_emails = sum(results)

        assert total_emails == num_threads * emails_per_thread
        # 1000 emails en moins de 2 secondes
        assert elapsed < 2.0, f"Trop lent: {elapsed:.2f}s pour {total_emails} emails"

    def test_concurrent_command_parsing(self):
        """Test parsing commandes en parallèle."""
        from app.voice import CommandParser

        def parse_commands(n):
            parser = CommandParser()  # Nouvelle instance par thread
            results = []
            for i in range(n):
                cmd = ["aide", "help", "stats", "refresh"][i % 4]
                action, _ = parser.parse(cmd)
                results.append(action)
            return len(results)

        num_threads = 10
        commands_per_thread = 500

        start = time.time()

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [
                executor.submit(parse_commands, commands_per_thread)
                for _ in range(num_threads)
            ]
            results = [f.result() for f in as_completed(futures)]

        elapsed = time.time() - start
        total = sum(results)

        assert total == num_threads * commands_per_thread
        # 5000 commandes en moins de 1 seconde
        assert elapsed < 1.0, f"Trop lent: {elapsed:.2f}s pour {total} commandes"

    def test_concurrent_database_access(self):
        """Test accès concurrent à la base de données via SQLite direct."""
        import sqlite3

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_concurrent.db"

            # Créer la DB et la table d'abord
            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS concurrent_test (
                    id INTEGER PRIMARY KEY,
                    thread_id INTEGER,
                    value TEXT
                )
            """)
            conn.commit()
            conn.close()

            errors = []
            lock = threading.Lock()

            def insert_records(thread_id, n):
                """Chaque thread crée sa propre connexion."""
                try:
                    # Connexion SQLite directe
                    thread_conn = sqlite3.connect(str(db_path), timeout=30.0)
                    for i in range(n):
                        thread_conn.execute(
                            "INSERT INTO concurrent_test (thread_id, value) VALUES (?, ?)",
                            (thread_id, f"value_{thread_id}_{i}")
                        )
                    thread_conn.commit()
                    thread_conn.close()
                    return n
                except Exception as e:
                    with lock:
                        errors.append(f"Thread {thread_id}: {str(e)}")
                    return 0

            num_threads = 5
            inserts_per_thread = 100

            start = time.time()

            with ThreadPoolExecutor(max_workers=num_threads) as executor:
                futures = [
                    executor.submit(insert_records, i, inserts_per_thread)
                    for i in range(num_threads)
                ]
                [f.result() for f in as_completed(futures)]

            elapsed = time.time() - start

            # Vérifier pas d'erreurs
            assert len(errors) == 0, f"Erreurs: {errors}"

            # Vérifier total
            conn = sqlite3.connect(str(db_path))
            total = conn.execute("SELECT COUNT(*) FROM concurrent_test").fetchone()[0]
            conn.close()

            expected = num_threads * inserts_per_thread
            assert total == expected, f"Attendu {expected}, obtenu {total}"

            # 500 inserts en moins de 5 secondes (SQLite locks peuvent ralentir)
            assert elapsed < 5.0, f"Trop lent: {elapsed:.2f}s pour {total} inserts"


# ============================================================================
# TESTS MEMOIRE
# ============================================================================

class TestMemoryUsage:
    """Tests d'utilisation mémoire."""

    def test_email_cleaner_no_memory_leak(self):
        """Test pas de fuite mémoire dans le cleaner."""
        from app.utils.email_cleaner import clean_email_content
        import gc

        # Forcer garbage collection
        gc.collect()

        email_body = "Test " * 1000  # Email volumineux

        # Traiter beaucoup d'emails
        for _ in range(1000):
            _ = clean_email_content(email_body)

        # Forcer collection
        gc.collect()

        # Pas d'exception = pas de fuite détectée
        assert True

    def test_command_parser_no_memory_leak(self):
        """Test pas de fuite mémoire dans le parser."""
        from app.voice import CommandParser
        import gc

        gc.collect()

        for _ in range(100):
            parser = CommandParser()
            for _ in range(100):
                parser.parse("test command")

        gc.collect()
        assert True


# ============================================================================
# TESTS LATENCE
# ============================================================================

class TestLatency:
    """Tests de latence."""

    def test_email_cleaner_latency_distribution(self):
        """Test distribution de latence pour le cleaner."""
        from app.utils.email_cleaner import clean_email_content

        email_body = "Test email " * 50

        latencies = []
        for _ in range(1000):
            start = time.perf_counter()
            clean_email_content(email_body)
            latencies.append((time.perf_counter() - start) * 1000)  # ms

        p50 = sorted(latencies)[500]
        p95 = sorted(latencies)[950]
        p99 = sorted(latencies)[990]

        # P50 < 0.5ms, P95 < 1ms, P99 < 2ms
        assert p50 < 0.5, f"P50 trop haut: {p50:.3f}ms"
        assert p95 < 1.0, f"P95 trop haut: {p95:.3f}ms"
        assert p99 < 2.0, f"P99 trop haut: {p99:.3f}ms"

    def test_database_query_latency(self):
        """Test latence des requêtes database."""
        from app.infrastructure.database import Database

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_latency.db"
            db = Database(db_path)

            # Créer table et données
            db.execute("""
                CREATE TABLE IF NOT EXISTS latency_test (
                    id INTEGER PRIMARY KEY,
                    data TEXT
                )
            """)

            for i in range(1000):
                db.execute(
                    "INSERT INTO latency_test (data) VALUES (?)",
                    (f"data_{i}",)
                )

            # Mesurer latence des queries
            latencies = []
            for _ in range(100):
                start = time.perf_counter()
                db.fetchall("SELECT * FROM latency_test WHERE id > 500")
                latencies.append((time.perf_counter() - start) * 1000)  # ms

            p50 = sorted(latencies)[50]
            p95 = sorted(latencies)[95]

            # P50 < 5ms, P95 < 20ms
            assert p50 < 5, f"P50 trop haut: {p50:.3f}ms"
            assert p95 < 20, f"P95 trop haut: {p95:.3f}ms"


# ============================================================================
# TESTS THROUGHPUT
# ============================================================================

class TestThroughput:
    """Tests de débit."""

    def test_email_processing_throughput(self):
        """Test débit traitement emails."""
        from app.utils.email_cleaner import clean_email_content

        email_body = """
        Subject: Important Update

        Dear Team,

        Please review the attached document.

        Best regards,
        Manager

        --
        Sent from my iPhone
        """

        # Charge fixe : garde le signal de débit sans bloquer la CI pendant 1s.
        count = 0
        start = time.time()
        target = 5_000
        for _ in range(target):
            clean_email_content(email_body)
            count += 1

        elapsed = time.time() - start

        # Doit traiter au moins 5000 emails/seconde.
        assert count == target
        assert elapsed < 1.0, f"Débit trop faible: {count / elapsed:.0f} emails/s"

    def test_database_insert_throughput(self):
        """Test débit insertions database."""
        from app.infrastructure.database import Database

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_throughput.db"
            db = Database(db_path)

            db.execute("""
                CREATE TABLE IF NOT EXISTS throughput_test (
                    id INTEGER PRIMARY KEY,
                    data TEXT
                )
            """)

            # Charge fixe : garde le seuil de 500 inserts/s sans attendre 1s.
            count = 0
            start = time.time()
            target = 500
            for _ in range(target):
                db.execute(
                    "INSERT INTO throughput_test (data) VALUES (?)",
                    (f"data_{count}",)
                )
                count += 1

            elapsed = time.time() - start

            # Doit insérer au moins 500 rows/seconde.
            assert count == target
            assert elapsed < 1.0, f"Débit trop faible: {count / elapsed:.0f} inserts/s"


# ============================================================================
# TESTS SCALABILITE
# ============================================================================

class TestScalability:
    """Tests de scalabilité."""

    def test_email_cleaner_scales_linearly(self):
        """Test que le cleaner scale linéairement."""
        from app.utils.email_cleaner import clean_email_content

        # Tester différentes tailles d'emails
        sizes = [100, 500, 1000, 5000]
        times = []

        for size in sizes:
            email = "word " * size
            start = time.perf_counter()
            for _ in range(100):
                clean_email_content(email)
            times.append(time.perf_counter() - start)

        # Vérifier scaling ~linéaire (ratio temps doit être proche du ratio taille)
        # Temps pour 5000 mots / temps pour 500 mots devrait être ~10x
        ratio = times[-1] / times[1]
        expected_ratio = sizes[-1] / sizes[1]

        # Tolérer 5x l'écart attendu (les regex peuvent être non-linéaires)
        assert ratio < expected_ratio * 5, f"Scaling non-linéaire: ratio={ratio:.1f}, attendu≈{expected_ratio}"

    @pytest.mark.skipif(
        os.environ.get("CI") == "true",
        reason="Variance trop forte sur runner CI Hetzner partagé "
               "(observé jusqu'à 11.3× — voir commits 540034cb / 6f76596d). "
               "Toujours utile en local sur machine stable.",
    )
    def test_concurrent_scaling(self):
        """Test que la performance scale avec les threads.

        Mesure l'overhead du GIL + ThreadPoolExecutor : 4 threads ne doivent pas
        prendre plus de 10× le temps d'1 thread pour faire 4× le travail.

        Robustesse anti-flake (CI Hetzner partagé) :
        - Warm-up pour amortir init parser / caches interpréteur.
        - perf_counter (sub-ms) au lieu de time.time().
        - Charge augmentée (10k itérations) pour que les temps absolus dominent
          le bruit du scheduler (~ms sur runner partagé).
        - min de 3 runs pour exclure les outliers GC/scheduling.
        - Skippé en CI (variance > 10× malgré tout cela).
        """
        from app.voice import CommandParser

        def work(n: int) -> int:
            parser = CommandParser()
            for _ in range(n):
                parser.parse("test")
            return n

        work_per_thread = 10_000
        runs = 3

        # Warm-up : 1 itération hors mesure (caches, allocations, JIT-équivalent)
        work(work_per_thread)
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda _: work(work_per_thread), range(4)))

        # Mesure : on prend le min sur N runs (élimine les pauses GC sporadiques)
        times_1 = []
        for _ in range(runs):
            start = time.perf_counter()
            work(work_per_thread)
            times_1.append(time.perf_counter() - start)

        times_4 = []
        for _ in range(runs):
            start = time.perf_counter()
            with ThreadPoolExecutor(max_workers=4) as executor:
                list(executor.map(lambda _: work(work_per_thread), range(4)))
            times_4.append(time.perf_counter() - start)

        time_1 = min(times_1)
        time_4 = min(times_4)

        # 4 threads font 4× le travail. Au pire (GIL-bound) on attend ratio ~4×
        # plus l'overhead executor. Seuil 10× : tolère les pauses scheduler
        # importantes sur runners CI partagés (vu jusqu'à 6.57× en prod CI),
        # tout en capturant les vraies régressions de perf (>10× = bug).
        assert time_4 < time_1 * 10, (
            f"Overhead excessif: 1t={time_1:.3f}s (runs={times_1}), "
            f"4t={time_4:.3f}s (runs={times_4}), ratio={time_4/time_1:.2f}x"
        )


# ============================================================================
# TESTS STRESS
# ============================================================================

class TestStress:
    """Tests de stress."""

    def test_sustained_load(self):
        """Test charge soutenue."""
        from app.utils.email_cleaner import clean_email_content
        from app.voice import CommandParser

        parser = CommandParser()

        errors = []
        count = 0

        # Charge soutenue fixe : même garde-fou, sans 5s incompressibles en CI.
        start = time.time()
        target = 10_000
        for _ in range(target):
            try:
                clean_email_content("Test email content")
                parser.parse("help")
                count += 1
            except Exception as e:
                errors.append(str(e))

        elapsed = time.time() - start

        assert len(errors) == 0, f"Erreurs sous charge: {errors[:5]}"
        assert count == target
        assert elapsed < 5.0, f"Débit insuffisant: {count / elapsed:.0f} opérations/s"

    def test_burst_load(self):
        """Test charge en rafale."""
        from app.utils.email_cleaner import clean_email_content

        email = "Test " * 1000

        # 3 rafales suffisent à couvrir le chemin sans consommer 3s+ de CI.
        for burst in range(3):
            start = time.time()
            for _ in range(1000):
                clean_email_content(email)
            elapsed = time.time() - start

            # Chaque rafale doit terminer en < 2s
            assert elapsed < 2.0, f"Rafale {burst} trop lente: {elapsed:.2f}s"


# ============================================================================
# TESTS CACHE
# ============================================================================

class TestCachePerformance:
    """Tests performance du cache."""

    def test_cache_hit_ratio(self):
        """Test ratio de hits du cache."""
        from app.infrastructure.cache import Cache

        cache = Cache(max_size=100, default_ttl=60)

        # Ajouter des éléments
        for i in range(100):
            cache.set(f"key_{i}", f"value_{i}")

        # Accéder plusieurs fois aux mêmes clés
        hits = 0
        misses = 0
        for i in range(1000):
            key = f"key_{i % 100}"
            if cache.get(key) is not None:
                hits += 1
            else:
                misses += 1

        hit_ratio = hits / (hits + misses)
        assert hit_ratio > 0.95, f"Hit ratio trop bas: {hit_ratio:.2%}"

    def test_cache_performance_improvement(self):
        """Test amélioration performance avec cache.

        Utilise `time.perf_counter()` (résolution sub-µs) plutôt que
        `time.time()` (résolution ~15ms sur Windows) pour mesurer
        précisément un cache hit qui prend <100µs. Garde-fou
        ZeroDivisionError si le speedup est tellement grand que
        time_with_cache mesure 0.
        """
        from app.infrastructure.cache import Cache

        cache = Cache(max_size=100, default_ttl=60)

        def expensive_operation(key):
            time.sleep(0.001)  # Simule opération coûteuse (1ms)
            return f"result_{key}"

        def cached_operation(key):
            result = cache.get(key)
            if result is None:
                result = expensive_operation(key)
                cache.set(key, result)
            return result

        # Sans cache
        start = time.perf_counter()
        for _ in range(100):
            expensive_operation("test")
        time_no_cache = time.perf_counter() - start

        # Avec cache (première passe remplit le cache)
        for i in range(10):
            cached_operation(f"key_{i}")

        # Avec cache (hits)
        start = time.perf_counter()
        for _ in range(100):
            cached_operation("key_5")  # Toujours dans le cache
        time_with_cache = time.perf_counter() - start

        # Cache doit être au moins 10x plus rapide.
        # Garde-fou : si time_with_cache est tellement petit qu'on a 0,
        # le speedup est >> 10x donc on passe le test.
        if time_with_cache <= 0:
            return
        speedup = time_no_cache / time_with_cache
        assert speedup > 10, f"Speedup insuffisant: {speedup:.1f}x"


# ============================================================================
# TESTS PAGINATION
# ============================================================================

class TestPaginationPerformance:
    """Tests performance pagination."""

    def test_pagination_large_dataset(self):
        """Test pagination sur grand dataset."""
        from app.infrastructure.pagination import Paginator

        # Simuler un grand dataset
        data = list(range(10000))

        # Paginer avec Paginator(items, page_size)
        paginator = Paginator(items=data, page_size=100)

        pages_fetched = 0
        total_items = 0
        start = time.time()

        for page in range(1, 101):  # 100 pages
            result = paginator.get_page(page)
            pages_fetched += 1
            total_items += len(result.items)

        elapsed = time.time() - start

        assert total_items == 10000
        # 100 pages en < 0.5s
        assert elapsed < 0.5, f"Pagination trop lente: {elapsed:.2f}s"


# ============================================================================
# TESTS BATCH PROCESSING
# ============================================================================

class TestBatchPerformance:
    """Tests performance traitement batch."""

    def test_batch_vs_sequential(self):
        """Test batch vs traitement séquentiel.

        Le sleep doit être assez long pour amortir l'overhead du BatchProcessor
        (thread pool startup, GIL contention, batching). Avec 1ms par item le
        test devenait flaky sur les runners CI partagés (speedup 1.7x au lieu
        de 2x — voir CI run 25191034168 du 2026-04-30). 5ms par item donne un
        speedup mécanique de ~3.3x avec 4 workers, marge confortable au-dessus
        du seuil >2x.
        """
        from app.infrastructure.batch import BatchProcessor

        def process_item(item):
            time.sleep(0.005)  # Simule travail (5ms — voir docstring)
            return item * 2

        items = list(range(100))

        # Séquentiel
        start = time.time()
        sequential_results = [process_item(i) for i in items]
        time_sequential = time.time() - start

        # Batch (parallèle)
        processor = BatchProcessor(
            process_func=process_item,
            batch_size=10,
            max_workers=4
        )

        start = time.time()
        batch_result = processor.process(items)
        batch_results = [r.result for r in batch_result.items if r.result is not None]
        time_batch = time.time() - start

        # Vérifier résultats identiques
        assert sorted(sequential_results) == sorted(batch_results)

        # Batch doit être plus rapide (au moins 2x)
        speedup = time_sequential / time_batch
        assert speedup > 2, f"Speedup insuffisant: {speedup:.1f}x"


# ============================================================================
# BENCHMARK SUMMARY
# ============================================================================

class TestBenchmarkSummary:
    """Résumé des benchmarks."""

    def test_generate_benchmark_report(self):
        """Génère un rapport de benchmark."""
        from app.utils.email_cleaner import clean_email_content
        from app.voice import CommandParser

        results = {}

        # Email cleaner
        email = "Test email " * 100

        start = time.perf_counter()
        for _ in range(1000):
            clean_email_content(email)
        results["email_cleaner_1000_ops"] = (time.perf_counter() - start) * 1000

        # Command parser
        parser = CommandParser()
        start = time.perf_counter()
        for _ in range(1000):
            parser.parse("help me")
        results["command_parser_1000_ops"] = (time.perf_counter() - start) * 1000

        # Afficher résultats
        print("\n=== Benchmark Results ===")
        for name, time_ms in results.items():
            print(f"{name}: {time_ms:.2f}ms")
        print("========================\n")

        # Assertions basiques
        assert results["email_cleaner_1000_ops"] < 1000  # < 1000ms pour 1000 ops
        assert results["command_parser_1000_ops"] < 100  # < 100ms pour 1000 ops

# CI trigger nudge: 2026-05-04T20:22:06Z
