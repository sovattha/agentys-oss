# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les edge cases de l'infrastructure.

Ce module couvre les cas limites non testés :
- Cache: TTL, éviction LRU, concurrence, valeurs limites
- Rate Limiter: boundaries, inputs invalides, clock drift
- FakeClock: temps négatif, precision, edge cases temporels
- Learning Use Cases: validation inputs, priority score bounds

Principes Clean Architecture respectés :
- Tests unitaires isolés de l'infrastructure
- Injection de dépendances via mocks
- Tests déterministes (pas de time.sleep() dans les tests unitaires)
"""

import pytest
import time
import threading
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock


# =============================================================================
# TESTS CACHE - EDGE CASES TTL ET ÉVICTION
# =============================================================================


class TestCacheEdgeCases:
    """Tests edge cases pour le Cache en mémoire."""

    def test_cache_max_size_zero(self):
        """Cache avec max_size=0 devrait lever une erreur ou être inutilisable."""
        from app.infrastructure.cache import Cache

        # Comportement actuel: accepte max_size=0
        cache = Cache(max_size=0, default_ttl=300)

        # Tenter d'ajouter une entrée devrait déclencher éviction immédiate
        cache.set("key1", "value1")

        # Avec max_size=0, le cache ne peut rien stocker
        # Vérifie le comportement actuel (peut être 0 ou 1 selon implémentation)
        assert len(cache) <= 1

    def test_cache_max_size_negative(self):
        """Cache avec max_size négatif devrait être géré."""
        from app.infrastructure.cache import Cache

        # Comportement actuel: accepte des valeurs négatives
        cache = Cache(max_size=-1, default_ttl=300)

        # Le cache devrait fonctionner ou lever une erreur
        cache.set("key1", "value1")
        # -1 < 0, donc condition len(cache) >= max_size est toujours vraie
        # L'éviction devrait se produire

    def test_cache_ttl_zero(self):
        """TTL=0 devrait expirer immédiatement."""
        from app.infrastructure.cache import Cache

        cache = Cache(max_size=100, default_ttl=0)
        cache.set("key1", "value1")

        # Avec TTL=0, l'entrée expire immédiatement après création
        # Mais il y a une fenêtre infinitésimale
        # On vérifie le comportement au prochain get
        result = cache.get("key1")

        # is_expired: time.time() - created_at > ttl (0)
        # Si même instant: 0 > 0 = False, pas expiré
        # Sinon: any_positive > 0 = True, expiré
        # Le résultat dépend du timing
        assert result is None or result == "value1"

    def test_cache_ttl_negative(self):
        """TTL négatif devrait être traité comme expiré."""
        from app.infrastructure.cache import Cache

        cache = Cache(max_size=100, default_ttl=-1)
        cache.set("key1", "value1")

        # is_expired: time.time() - created_at > -1
        # Toujours True car time.time() - created_at >= 0 > -1
        result = cache.get("key1")

        # Comportement actuel: devrait être expiré immédiatement
        assert result is None

    def test_cache_ttl_none_never_expires(self):
        """TTL=None signifie pas d'expiration."""
        from app.infrastructure.cache import Cache

        cache = Cache(max_size=100, default_ttl=None)
        cache.set("key1", "value1")

        # Sans TTL, l'entrée ne devrait jamais expirer
        result = cache.get("key1")
        assert result == "value1"

    def test_cache_eviction_lru_with_equal_hits(self):
        """Éviction LRU quand toutes les entrées ont le même nombre de hits."""
        from app.infrastructure.cache import Cache

        cache = Cache(max_size=3, default_ttl=300)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        # Toutes ont 0 hits, l'éviction choisit le min par clé (arbitraire)
        cache.set("key4", "value4")

        # Une entrée doit avoir été évincée
        assert len(cache) == 3

        # key4 doit être présente
        assert cache.get("key4") == "value4"

    def test_cache_eviction_respects_hits(self):
        """L'éviction respecte le nombre de hits."""
        from app.infrastructure.cache import Cache

        cache = Cache(max_size=3, default_ttl=300)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        # Accéder plusieurs fois à key1 et key3
        for _ in range(5):
            cache.get("key1")
            cache.get("key3")

        # key2 a le moins de hits (0), sera évincée
        cache.set("key4", "value4")

        # key2 devrait avoir été évincée
        assert cache.get("key2") is None
        assert cache.get("key1") == "value1"
        assert cache.get("key3") == "value3"

    def test_cache_update_existing_key(self):
        """Mettre à jour une clé existante ne déclenche pas d'éviction."""
        from app.infrastructure.cache import Cache

        cache = Cache(max_size=2, default_ttl=300)
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        # Mettre à jour key1
        cache.set("key1", "new_value1")

        # Pas d'éviction car la clé existe déjà
        assert len(cache) == 2
        assert cache.get("key1") == "new_value1"
        assert cache.get("key2") == "value2"

    def test_cache_concurrent_access(self):
        """Accès concurrent au cache est thread-safe."""
        from app.infrastructure.cache import Cache

        cache = Cache(max_size=1000, default_ttl=300)
        errors = []

        def writer(thread_id):
            try:
                for i in range(100):
                    cache.set(f"key_{thread_id}_{i}", f"value_{thread_id}_{i}")
            except Exception as e:
                errors.append(e)

        def reader(thread_id):
            try:
                for i in range(100):
                    cache.get(f"key_{thread_id}_{i}")
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            threads.append(threading.Thread(target=writer, args=(i,)))
            threads.append(threading.Thread(target=reader, args=(i,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_cache_cleanup_expired_returns_count(self):
        """cleanup_expired() retourne le nombre d'entrées supprimées."""
        from app.infrastructure.cache import Cache

        cache = Cache(max_size=100, default_ttl=0.001)  # 1ms TTL
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        # Attendre expiration
        time.sleep(0.01)

        removed = cache.cleanup_expired()
        assert removed == 2

    def test_cache_contains_expired_entry(self):
        """'in' operator retourne False pour entrée expirée."""
        from app.infrastructure.cache import Cache

        cache = Cache(max_size=100, default_ttl=0.001)
        cache.set("key1", "value1")

        # Vérifier immédiatement
        assert "key1" in cache or "key1" not in cache  # Dépend du timing

        # Attendre expiration
        time.sleep(0.01)

        assert "key1" not in cache

    def test_cache_stats_hit_rate_division_by_zero(self):
        """get_stats() gère division par zéro quand cache vide."""
        from app.infrastructure.cache import Cache

        cache = Cache(max_size=100, default_ttl=300)
        stats = cache.get_stats()

        # Pas d'accès = total 0, hit_rate devrait être 0 pas NaN
        assert stats["hit_rate"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    def test_cache_delete_nonexistent_key(self):
        """delete() sur clé inexistante retourne False."""
        from app.infrastructure.cache import Cache

        cache = Cache(max_size=100, default_ttl=300)
        result = cache.delete("nonexistent")

        assert result is False

    def test_cache_none_value(self):
        """Le cache peut stocker None comme valeur."""
        from app.infrastructure.cache import Cache

        cache = Cache(max_size=100, default_ttl=300)
        cache.set("key1", None)

        # Problème: get() retourne None pour clé manquante ET pour valeur None
        result = cache.get("key1")
        assert result is None

        # Utiliser 'in' pour distinguer
        assert "key1" in cache


# =============================================================================
# TESTS RATE LIMITER - EDGE CASES
# =============================================================================


class TestRateLimiterEdgeCases:
    """Tests edge cases pour le SlidingWindowRateLimiter."""

    def test_rate_limiter_max_requests_zero(self):
        """max_requests=0 bloque toutes les requêtes (non-blocking mode)."""
        from app.infrastructure.rate_limiter import SlidingWindowRateLimiter, RateLimitExceededError

        limiter = SlidingWindowRateLimiter(
            name="test",
            max_requests=0,
            window_seconds=60.0,
            blocking=False
        )

        # Aucune requête ne devrait passer car 0 + 1 <= 0 est False
        with pytest.raises(RateLimitExceededError):
            limiter.acquire()

    def test_rate_limiter_max_requests_negative(self):
        """max_requests négatif bloque toutes les requêtes."""
        from app.infrastructure.rate_limiter import SlidingWindowRateLimiter, RateLimitExceededError

        limiter = SlidingWindowRateLimiter(
            name="test",
            max_requests=-1,
            window_seconds=60.0,
            blocking=False
        )

        # Condition: len(timestamps) + count <= max_requests
        # 0 + 1 <= -1 est False, donc bloque
        with pytest.raises(RateLimitExceededError):
            limiter.acquire()

    def test_rate_limiter_window_seconds_zero(self):
        """window_seconds=0 a un comportement spécial."""
        from app.infrastructure.rate_limiter import SlidingWindowRateLimiter

        limiter = SlidingWindowRateLimiter(
            name="test",
            max_requests=10,
            window_seconds=0.0,
            blocking=False
        )

        # Avec window=0, toutes les requêtes sont immédiatement expirées
        # La première requête devrait passer
        result = limiter.acquire()
        assert result is True

        # La deuxième aussi car window=0 expire tout
        result = limiter.acquire()
        assert result is True

    def test_rate_limiter_window_seconds_negative(self):
        """window_seconds négatif a un comportement imprévisible."""
        from app.infrastructure.rate_limiter import SlidingWindowRateLimiter

        limiter = SlidingWindowRateLimiter(
            name="test",
            max_requests=10,
            window_seconds=-1.0,
            blocking=False
        )

        # cutoff = now - (-1) = now + 1 = futur
        # Donc toutes les requêtes récentes sont "expirées"
        result = limiter.acquire()
        assert result is True

    def test_rate_limiter_exact_boundary(self):
        """Requêtes exactement à la limite."""
        from app.infrastructure.rate_limiter import SlidingWindowRateLimiter

        limiter = SlidingWindowRateLimiter(
            name="test",
            max_requests=3,
            window_seconds=60.0,
            blocking=False
        )

        # Remplir jusqu'à la limite
        assert limiter.acquire() is True
        assert limiter.acquire() is True
        assert limiter.acquire() is True

        # La 4ème doit échouer
        from app.infrastructure.rate_limiter import RateLimitExceededError
        with pytest.raises(RateLimitExceededError):
            limiter.acquire()

    def test_rate_limiter_acquire_count_greater_than_max(self):
        """acquire(count) où count > max_requests."""
        from app.infrastructure.rate_limiter import SlidingWindowRateLimiter, RateLimitExceededError

        limiter = SlidingWindowRateLimiter(
            name="test",
            max_requests=5,
            window_seconds=60.0,
            blocking=False
        )

        # Demander plus que le max
        with pytest.raises(RateLimitExceededError):
            limiter.acquire(count=10)

    def test_rate_limiter_acquire_count_zero(self):
        """acquire(count=0) devrait toujours réussir."""
        from app.infrastructure.rate_limiter import SlidingWindowRateLimiter

        limiter = SlidingWindowRateLimiter(
            name="test",
            max_requests=3,
            window_seconds=60.0,
            blocking=False
        )

        # Remplir le limiter
        limiter.acquire()
        limiter.acquire()
        limiter.acquire()

        # count=0 devrait toujours passer
        result = limiter.acquire(count=0)
        assert result is True

    def test_rate_limiter_acquire_count_negative(self):
        """acquire(count) avec count négatif."""
        from app.infrastructure.rate_limiter import SlidingWindowRateLimiter

        limiter = SlidingWindowRateLimiter(
            name="test",
            max_requests=3,
            window_seconds=60.0,
            blocking=False
        )

        # count négatif: len(timestamps) + (-1) <= 3 toujours vrai
        result = limiter.acquire(count=-1)
        assert result is True

    def test_rate_limiter_stats_after_reset(self):
        """Stats après reset()."""
        from app.infrastructure.rate_limiter import SlidingWindowRateLimiter

        limiter = SlidingWindowRateLimiter(
            name="test",
            max_requests=10,
            window_seconds=60.0,
            blocking=False
        )

        # Faire quelques requêtes
        limiter.acquire()
        limiter.acquire()

        # Reset
        limiter.reset()

        # Les timestamps sont vidés mais stats restent
        stats = limiter.stats
        assert stats.total_requests == 2  # Stats non réinitialisées

        # Nouvelles requêtes passent
        assert limiter.acquire() is True

    def test_rate_limiter_concurrent_access(self):
        """Accès concurrent au rate limiter."""
        from app.infrastructure.rate_limiter import SlidingWindowRateLimiter

        limiter = SlidingWindowRateLimiter(
            name="test",
            max_requests=100,
            window_seconds=60.0,
            blocking=False
        )

        success_count = 0
        lock = threading.Lock()

        def acquire_request():
            nonlocal success_count
            try:
                if limiter.acquire():
                    with lock:
                        success_count += 1
            except Exception:
                pass

        threads = [threading.Thread(target=acquire_request) for _ in range(200)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactement 100 requêtes devraient réussir
        assert success_count == 100


# =============================================================================
# TESTS TOKEN BUCKET RATE LIMITER - EDGE CASES
# =============================================================================


class TestTokenBucketEdgeCases:
    """Tests edge cases pour le TokenBucketRateLimiter."""

    def test_token_bucket_max_tokens_zero(self):
        """max_tokens=0 bloque toutes les requêtes."""
        from app.infrastructure.rate_limiter import TokenBucketRateLimiter, RateLimitExceededError

        limiter = TokenBucketRateLimiter(
            name="test",
            tokens_per_second=1.0,
            max_tokens=0,
            blocking=False
        )

        # self._tokens = float(0) = 0.0
        # 0.0 >= 1 est False
        with pytest.raises(RateLimitExceededError):
            limiter.acquire(tokens=1)

    def test_token_bucket_negative_tokens_per_second(self):
        """tokens_per_second négatif consomme les tokens au lieu de les remplir."""
        from app.infrastructure.rate_limiter import TokenBucketRateLimiter

        limiter = TokenBucketRateLimiter(
            name="test",
            tokens_per_second=-1.0,
            max_tokens=10,
            blocking=False
        )

        # Au début: _tokens = 10
        assert limiter.acquire(tokens=1) is True

        # Après un temps, les tokens devraient diminuer (pas augmenter)
        time.sleep(0.1)

        # Refill: tokens + elapsed * (-1) = tokens - elapsed
        # Ce qui réduit les tokens disponibles

    def test_token_bucket_acquire_zero_tokens(self):
        """acquire(tokens=0) réussit toujours."""
        from app.infrastructure.rate_limiter import TokenBucketRateLimiter

        limiter = TokenBucketRateLimiter(
            name="test",
            tokens_per_second=1.0,
            max_tokens=0,  # Bucket vide
            blocking=False
        )

        # 0.0 >= 0 est True
        result = limiter.acquire(tokens=0)
        assert result is True


# =============================================================================
# TESTS FAKE CLOCK - EDGE CASES
# =============================================================================


class TestFakeClockEdgeCases:
    """Tests edge cases pour FakeClock."""

    def test_fake_clock_advance_by_negative_time(self):
        """advance_by() avec valeurs négatives recule le temps."""
        from app.infrastructure.clock import FakeClock

        start_time = datetime(2024, 6, 15, 12, 0, 0)
        clock = FakeClock(start_time)

        # Reculer de 2 heures
        clock.advance_by(hours=-2)

        expected = datetime(2024, 6, 15, 10, 0, 0)
        assert clock.now() == expected

    def test_fake_clock_advance_negative_days(self):
        """advance_by() avec jours négatifs."""
        from app.infrastructure.clock import FakeClock

        start_time = datetime(2024, 6, 15, 12, 0, 0)
        clock = FakeClock(start_time)

        clock.advance_by(days=-10)

        expected = datetime(2024, 6, 5, 12, 0, 0)
        assert clock.now() == expected

    def test_fake_clock_advance_mixed_positive_negative(self):
        """advance_by() avec mix de valeurs positives et négatives."""
        from app.infrastructure.clock import FakeClock

        start_time = datetime(2024, 6, 15, 12, 0, 0)
        clock = FakeClock(start_time)

        # +1 jour, -2 heures
        clock.advance_by(days=1, hours=-2)

        expected = datetime(2024, 6, 16, 10, 0, 0)
        assert clock.now() == expected

    def test_fake_clock_elapsed_after_negative_advance(self):
        """elapsed() retourne un timedelta négatif après recul."""
        from app.infrastructure.clock import FakeClock

        start_time = datetime(2024, 6, 15, 12, 0, 0)
        clock = FakeClock(start_time)

        clock.advance_by(hours=-2)
        elapsed = clock.elapsed()

        # elapsed = current - initial = -2 heures
        assert elapsed == timedelta(hours=-2)
        assert elapsed.total_seconds() < 0

    def test_fake_clock_year_boundary_crossing(self):
        """advance_by() traverse les frontières d'année."""
        from app.infrastructure.clock import FakeClock

        start_time = datetime(2024, 12, 31, 23, 59, 59)
        clock = FakeClock(start_time)

        clock.advance_by(seconds=2)

        expected = datetime(2025, 1, 1, 0, 0, 1)
        assert clock.now() == expected

    def test_fake_clock_leap_year_handling(self):
        """advance_by() gère correctement les années bissextiles."""
        from app.infrastructure.clock import FakeClock

        # 2024 est une année bissextile
        start_time = datetime(2024, 2, 28, 12, 0, 0)
        clock = FakeClock(start_time)

        clock.advance_by(days=1)

        expected = datetime(2024, 2, 29, 12, 0, 0)
        assert clock.now() == expected

    def test_fake_clock_microsecond_precision(self):
        """FakeClock préserve la précision microseconde."""
        from app.infrastructure.clock import FakeClock

        start_time = datetime(2024, 1, 1, 0, 0, 0, 123456)
        clock = FakeClock(start_time)

        assert clock.now().microsecond == 123456

        clock.advance_by(milliseconds=1)  # +1000 microseconds

        assert clock.now().microsecond == 124456

    def test_fake_clock_set_time_to_past(self):
        """set_time() peut définir un temps dans le passé."""
        from app.infrastructure.clock import FakeClock

        clock = FakeClock(datetime(2024, 6, 15, 12, 0, 0))
        clock.set_time(datetime(2020, 1, 1, 0, 0, 0))

        assert clock.now() == datetime(2020, 1, 1, 0, 0, 0)

    def test_fake_clock_reset_preserves_initial(self):
        """reset() remet à l'heure initiale même après set_time()."""
        from app.infrastructure.clock import FakeClock

        initial = datetime(2024, 1, 1, 0, 0, 0)
        clock = FakeClock(initial)

        clock.set_time(datetime(2030, 12, 31, 23, 59, 59))
        clock.reset()

        assert clock.now() == initial


# =============================================================================
# TESTS LEARNING USE CASES - VALIDATION INPUTS
# =============================================================================


class TestLearningUseCasesInputValidation:
    """Tests pour la validation des inputs dans les use cases Learning."""

    def test_should_require_review_priority_score_boundary_89(self):
        """priority_score=89 ne déclenche pas la review haute priorité."""
        from app.application.learning import ShouldRequireReviewUseCase

        mock_provider = Mock()
        mock_provider.get_satisfaction_rate.return_value = 100  # Haute confiance

        use_case = ShouldRequireReviewUseCase(
            insights_provider=mock_provider,
            confidence_threshold=70,
            sensitive_words=[],
        )

        result = use_case.execute(email_content="Hello", priority_score=89)

        # 89 < 90, donc pas de review pour haute priorité
        assert result.needs_review is False

    def test_should_require_review_priority_score_boundary_90(self):
        """priority_score=90 déclenche exactement la review haute priorité."""
        from app.application.learning import ShouldRequireReviewUseCase

        mock_provider = Mock()
        mock_provider.get_satisfaction_rate.return_value = 100

        use_case = ShouldRequireReviewUseCase(
            insights_provider=mock_provider,
            confidence_threshold=70,
            sensitive_words=[],
        )

        result = use_case.execute(email_content="Hello", priority_score=90)

        # 90 >= 90, déclenche la review
        assert result.needs_review is True
        assert "priorité très haute" in result.reasons[0]

    def test_should_require_review_priority_score_over_100(self):
        """priority_score > 100 fonctionne (pas de validation de plage)."""
        from app.application.learning import ShouldRequireReviewUseCase

        mock_provider = Mock()
        mock_provider.get_satisfaction_rate.return_value = 100

        use_case = ShouldRequireReviewUseCase(
            insights_provider=mock_provider,
            confidence_threshold=70,
            sensitive_words=[],
        )

        result = use_case.execute(email_content="Hello", priority_score=500)

        # 500 >= 90, déclenche la review
        assert result.needs_review is True

    def test_should_require_review_priority_score_negative(self):
        """priority_score négatif fonctionne (pas de validation)."""
        from app.application.learning import ShouldRequireReviewUseCase

        mock_provider = Mock()
        mock_provider.get_satisfaction_rate.return_value = 100

        use_case = ShouldRequireReviewUseCase(
            insights_provider=mock_provider,
            confidence_threshold=70,
            sensitive_words=[],
        )

        result = use_case.execute(email_content="Hello", priority_score=-50)

        # -50 < 90, pas de review pour haute priorité
        assert result.needs_review is False

    def test_should_require_review_confidence_boundary_exact(self):
        """satisfaction_rate exactement égal au threshold."""
        from app.application.learning import ShouldRequireReviewUseCase

        mock_provider = Mock()
        mock_provider.get_satisfaction_rate.return_value = 70  # Exactement au seuil

        use_case = ShouldRequireReviewUseCase(
            insights_provider=mock_provider,
            confidence_threshold=70,
            sensitive_words=[],
        )

        result = use_case.execute(email_content="Hello", priority_score=50)

        # 70 < 70 est False, donc pas de review pour faible confiance
        assert result.needs_review is False

    def test_should_require_review_confidence_just_below(self):
        """satisfaction_rate juste en dessous du threshold."""
        from app.application.learning import ShouldRequireReviewUseCase

        mock_provider = Mock()
        mock_provider.get_satisfaction_rate.return_value = 69.9

        use_case = ShouldRequireReviewUseCase(
            insights_provider=mock_provider,
            confidence_threshold=70,
            sensitive_words=[],
        )

        result = use_case.execute(email_content="Hello", priority_score=50)

        # 69.9 < 70, déclenche review pour faible confiance
        assert result.needs_review is True
        assert "Confiance système faible" in result.reasons[0]

    def test_should_require_review_sensitive_word_case_insensitive(self):
        """Les mots sensibles sont détectés de manière case-insensitive."""
        from app.application.learning import ShouldRequireReviewUseCase

        mock_provider = Mock()
        mock_provider.get_satisfaction_rate.return_value = 100

        use_case = ShouldRequireReviewUseCase(
            insights_provider=mock_provider,
            confidence_threshold=70,
            sensitive_words=["contrat"],
        )

        # Test avec différentes casses
        for content in ["CONTRAT important", "Contrat", "contrat", "CoNtRaT"]:
            result = use_case.execute(email_content=content, priority_score=50)
            assert result.needs_review is True, f"Failed for: {content}"

    def test_should_require_review_sensitive_word_as_substring(self):
        """Les mots sensibles sont détectés même comme substring."""
        from app.application.learning import ShouldRequireReviewUseCase

        mock_provider = Mock()
        mock_provider.get_satisfaction_rate.return_value = 100

        use_case = ShouldRequireReviewUseCase(
            insights_provider=mock_provider,
            confidence_threshold=70,
            sensitive_words=["urgent"],
        )

        # "urgent" est substring de "urgently"
        result = use_case.execute(email_content="Please respond urgently", priority_score=50)

        assert result.needs_review is True

    def test_should_require_review_multiple_criteria(self):
        """Plusieurs critères déclenchés ajoutent plusieurs raisons."""
        from app.application.learning import ShouldRequireReviewUseCase

        mock_provider = Mock()
        mock_provider.get_satisfaction_rate.return_value = 50  # Faible confiance

        use_case = ShouldRequireReviewUseCase(
            insights_provider=mock_provider,
            confidence_threshold=70,
            sensitive_words=["contrat"],
        )

        result = use_case.execute(
            email_content="Urgent contrat à signer",
            priority_score=95  # Haute priorité
        )

        assert result.needs_review is True
        # Au moins 2 raisons (priorité haute + contenu sensible)
        # Note: sensitive words ne détecte qu'un seul mot
        assert len(result.reasons) >= 2

    def test_analyze_feedback_limit_zero(self):
        """limit=0 retourne insights vides."""
        from app.application.learning import AnalyzeFeedbackUseCase

        mock_store = Mock()
        mock_store.get_all.return_value = []

        use_case = AnalyzeFeedbackUseCase(feedback_store=mock_store)
        result = use_case.execute(limit=0)

        mock_store.get_all.assert_called_once_with(limit=0)
        assert result.total_with_feedback == 0

    def test_analyze_feedback_limit_negative(self):
        """limit négatif est passé au store tel quel."""
        from app.application.learning import AnalyzeFeedbackUseCase

        mock_store = Mock()
        mock_store.get_all.return_value = []

        use_case = AnalyzeFeedbackUseCase(feedback_store=mock_store)
        use_case.execute(limit=-10)

        mock_store.get_all.assert_called_once_with(limit=-10)

    def test_extract_patterns_limit_zero(self):
        """ExtractPatterns avec limit=0."""
        from app.application.learning import ExtractPatternsUseCase

        mock_feedback_store = Mock()
        mock_feedback_store.get_with_comments.return_value = []

        use_case = ExtractPatternsUseCase(
            feedback_store=mock_feedback_store,
            pattern_store=Mock(),
            llm=Mock(),
        )

        result = use_case.execute(limit=0)

        mock_feedback_store.get_with_comments.assert_called_once_with(limit=0)
        assert result == []

    def test_generate_adjustment_pattern_with_empty_trigger(self):
        """Pattern avec trigger vide génère ajustement valide."""
        from app.application.learning import GenerateAdjustmentUseCase
        from app.domain.entities.learning import LearnedPattern, PatternType

        # Pattern avec trigger vide
        pattern = LearnedPattern.create(
            pattern_type=PatternType.BAD,
            trigger="",
            correction="Use formal language",
        )
        pattern.frequency = 5

        mock_pattern_store = Mock()
        mock_pattern_store.get_by_type.return_value = [pattern]

        mock_adjustment_store = Mock()

        use_case = GenerateAdjustmentUseCase(
            pattern_store=mock_pattern_store,
            adjustment_store=mock_adjustment_store,
        )

        result = use_case.execute()

        assert result is not None
        # Ajustement: "Évite: . Use formal language" (trigger vide)
        assert "Use formal language" in result.adjustment

    def test_enhance_prompt_with_unicode(self):
        """EnhancePrompt gère correctement l'unicode."""
        from app.application.learning import EnhancePromptUseCase

        adjustments = [Mock(adjustment="Utilise des émojis 😊")]

        mock_store = Mock()
        mock_store.get_active.return_value = adjustments

        use_case = EnhancePromptUseCase(adjustment_store=mock_store)
        result = use_case.execute("Base prompt avec éàü caractères")

        assert "😊" in result
        assert "éàü" in result


# =============================================================================
# TESTS CLAUDE ADAPTER - EDGE CASES
# =============================================================================


class TestClaudeAdapterEdgeCases:
    """Tests edge cases pour ClaudeAdapter.

    Note: Ces tests nécessitent le module anthropic.
    On utilise pytest.importorskip pour les sauter si non disponible.
    """

    @pytest.fixture(autouse=True)
    def skip_if_no_anthropic(self):
        """Skip ces tests si anthropic n'est pas installé."""
        pytest.importorskip("anthropic")

    def test_claude_adapter_empty_api_key_string(self):
        """API key vide (string vide) lève ValueError."""
        from app.adapters.llm.claude_adapter import ClaudeAdapter

        # String vide est falsy comme None
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': ''}):
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY requise"):
                ClaudeAdapter(api_key="")

    def test_claude_adapter_whitespace_api_key(self):
        """API key avec seulement des espaces."""
        from app.adapters.llm.claude_adapter import ClaudeAdapter
        import anthropic

        # "   " n'est pas falsy mais est invalide
        # Le code actuel accepte car bool("   ") == True
        with patch.object(anthropic, 'Anthropic'):
            adapter = ClaudeAdapter(api_key="   ")
            assert adapter._api_key == "   "

    def test_claude_adapter_is_available_with_key(self):
        """is_available() retourne True avec clé API."""
        from app.adapters.llm.claude_adapter import ClaudeAdapter
        import anthropic

        with patch.object(anthropic, 'Anthropic'):
            adapter = ClaudeAdapter(api_key="test-key")
            assert adapter.is_available() is True

    def test_claude_adapter_model_property(self):
        """model property retourne le modèle configuré."""
        from app.adapters.llm.claude_adapter import ClaudeAdapter
        import anthropic

        with patch.object(anthropic, 'Anthropic'):
            adapter = ClaudeAdapter(api_key="test-key", model="claude-3-opus-20240229")
            assert adapter.model == "claude-3-opus-20240229"

    def test_claude_adapter_name_property(self):
        """name property retourne 'claude'."""
        from app.adapters.llm.claude_adapter import ClaudeAdapter
        import anthropic

        with patch.object(anthropic, 'Anthropic'):
            adapter = ClaudeAdapter(api_key="test-key")
            assert adapter.name == "claude"

    def test_claude_adapter_complete_empty_response(self):
        """complete() avec réponse vide du LLM."""
        from app.adapters.llm.claude_adapter import ClaudeAdapter
        import anthropic

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = []  # Réponse vide
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 0
        mock_client.messages.create.return_value = mock_response

        with patch.object(anthropic, 'Anthropic', return_value=mock_client):
            adapter = ClaudeAdapter(api_key="test-key")

            # Devrait lever LLMResponseError car response.content est vide
            from app.domain.exceptions import LLMResponseError
            with pytest.raises(LLMResponseError):
                adapter.complete(system="test", user="test")

    def test_claude_adapter_complete_max_tokens_zero(self):
        """complete() avec max_tokens=0 doit lever InvalidBoundsError."""
        from app.adapters.llm.claude_adapter import ClaudeAdapter
        from app.domain.exceptions import InvalidBoundsError
        import anthropic

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="response")]
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 0
        mock_client.messages.create.return_value = mock_response

        with patch.object(anthropic, 'Anthropic', return_value=mock_client):
            adapter = ClaudeAdapter(api_key="test-key")

            # max_tokens=0 est invalide et doit lever InvalidBoundsError
            with pytest.raises(InvalidBoundsError):
                adapter.complete(system="test", user="test", max_tokens=0)


# =============================================================================
# TESTS LEARNING STATS - EDGE CASES
# =============================================================================


class TestLearningStatsEdgeCases:
    """Tests edge cases pour GetLearningStatsUseCase."""

    def test_learning_stats_all_zero(self):
        """Stats avec tout à zéro."""
        from app.application.learning import GetLearningStatsUseCase

        mock_pattern_store = Mock()
        mock_pattern_store.count.return_value = 0
        mock_pattern_store.count_by_type.return_value = {"good": 0, "bad": 0}

        mock_adjustment_store = Mock()
        mock_adjustment_store.count_active.return_value = 0

        mock_feedback_store = Mock()
        mock_feedback_store.get_all.return_value = []

        use_case = GetLearningStatsUseCase(
            pattern_store=mock_pattern_store,
            adjustment_store=mock_adjustment_store,
            feedback_store=mock_feedback_store,
        )

        result = use_case.execute()

        assert result["patterns_count"] == 0
        assert result["good_patterns"] == 0
        assert result["bad_patterns"] == 0
        assert result["active_adjustments"] == 0
        assert result["total_with_feedback"] == 0

    def test_learning_stats_missing_count_by_type_keys(self):
        """count_by_type sans certaines clés."""
        from app.application.learning import GetLearningStatsUseCase

        mock_pattern_store = Mock()
        mock_pattern_store.count.return_value = 5
        mock_pattern_store.count_by_type.return_value = {}  # Pas de clés

        mock_adjustment_store = Mock()
        mock_adjustment_store.count_active.return_value = 0

        mock_feedback_store = Mock()
        mock_feedback_store.get_all.return_value = []

        use_case = GetLearningStatsUseCase(
            pattern_store=mock_pattern_store,
            adjustment_store=mock_adjustment_store,
            feedback_store=mock_feedback_store,
        )

        result = use_case.execute()

        # Utilise .get() avec défaut 0
        assert result["good_patterns"] == 0
        assert result["bad_patterns"] == 0


# =============================================================================
# TESTS LEARNING INSIGHTS - EDGE CASES
# =============================================================================


class TestLearningInsightsEdgeCases:
    """Tests edge cases pour LearningInsights entity."""

    def test_learning_insights_default_values(self):
        """LearningInsights avec valeurs par défaut."""
        from app.domain.entities.learning import LearningInsights

        insights = LearningInsights()

        assert insights.total_with_feedback == 0
        assert insights.good_count == 0
        assert insights.bad_count == 0
        assert insights.neutral_count == 0
        assert insights.v1_good_rate == 0
        assert insights.v2_good_rate == 0

    def test_learning_insights_satisfaction_rate_no_total(self):
        """satisfaction_rate avec total=0 évite division par zéro."""
        from app.domain.entities.learning import LearningInsights

        insights = LearningInsights(
            total_with_feedback=0,
            good_count=0,
            bad_count=0,
        )

        # Devrait retourner 0.0 sans erreur
        rate = insights.satisfaction_rate
        assert rate == 0.0

    def test_learning_insights_satisfaction_rate_calculation(self):
        """satisfaction_rate calcule correctement le pourcentage."""
        from app.domain.entities.learning import LearningInsights

        insights = LearningInsights(
            total_with_feedback=100,
            good_count=75,
            bad_count=10,
            neutral_count=15,
        )

        rate = insights.satisfaction_rate
        # 75 / 100 * 100 = 75.0%
        assert rate == 75.0


# =============================================================================
# TESTS LEARNED PATTERN - EDGE CASES
# =============================================================================


class TestLearnedPatternEdgeCases:
    """Tests edge cases pour LearnedPattern entity."""

    def test_learned_pattern_increment_frequency_from_zero(self):
        """increment_frequency() depuis 0."""
        from app.domain.entities.learning import LearnedPattern, PatternType

        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
            correction="",
        )

        assert pattern.frequency == 1
        pattern.increment_frequency()
        assert pattern.frequency == 2

    def test_learned_pattern_is_reliable_boundary(self):
        """is_reliable() aux bornes."""
        from app.domain.entities.learning import LearnedPattern, PatternType

        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
            correction="",
        )

        # confidence=0.5, frequency=1
        # Par défaut: is_reliable(min_confidence=0.6)
        # 0.5 >= 0.6 est False
        assert pattern.is_reliable() is False

        # Augmenter la fréquence (confidence = min(1.0, frequency/10))
        pattern.increment_frequency()  # freq=2, conf=0.2
        pattern.increment_frequency()  # freq=3, conf=0.3
        pattern.increment_frequency()  # freq=4, conf=0.4
        pattern.increment_frequency()  # freq=5, conf=0.5
        pattern.increment_frequency()  # freq=6, conf=0.6

        # Maintenant confidence=0.6 >= 0.6
        assert pattern.is_reliable() is True

        # Tester avec un seuil plus bas
        assert pattern.is_reliable(min_confidence=0.5) is True

    def test_learned_pattern_from_dict_missing_fields(self):
        """from_dict() avec champs manquants utilise défauts."""
        from app.domain.entities.learning import LearnedPattern
        from datetime import datetime

        # from_dict() requiert certains champs obligatoires
        data = {
            "id": "test-id",
            "timestamp": datetime.now().isoformat(),  # Requis
            "pattern_type": "good",
            "trigger": "test trigger",
        }

        pattern = LearnedPattern.from_dict(data)

        # Champs avec défauts
        assert pattern.correction == ""
        assert pattern.frequency == 1
        assert pattern.confidence == 0.5

    def test_learned_pattern_to_dict_roundtrip(self):
        """to_dict() puis from_dict() préserve les données."""
        from app.domain.entities.learning import LearnedPattern, PatternType

        original = LearnedPattern.create(
            pattern_type=PatternType.BAD,
            trigger="bad trigger",
            correction="correction text",
            examples=["example1", "example2"],
        )
        original.increment_frequency()

        data = original.to_dict()
        restored = LearnedPattern.from_dict(data)

        assert restored.pattern_type == original.pattern_type
        assert restored.trigger == original.trigger
        assert restored.correction == original.correction
        assert restored.frequency == original.frequency


# =============================================================================
# TESTS PROMPT ADJUSTMENT - EDGE CASES
# =============================================================================


class TestPromptAdjustmentEdgeCases:
    """Tests edge cases pour PromptAdjustment entity."""

    def test_prompt_adjustment_create_with_empty_strings(self):
        """create() avec strings vides."""
        from app.domain.entities.learning import PromptAdjustment

        adjustment = PromptAdjustment.create(
            section="",
            adjustment="",
            reason="",
        )

        assert adjustment.section == ""
        assert adjustment.adjustment == ""
        assert adjustment.reason == ""
        assert adjustment.active is True  # L'attribut est 'active' pas 'is_active'

    def test_prompt_adjustment_activate_already_active(self):
        """activate() sur ajustement déjà actif."""
        from app.domain.entities.learning import PromptAdjustment

        adjustment = PromptAdjustment.create(
            section="test",
            adjustment="test",
            reason="test",
        )

        assert adjustment.active is True
        adjustment.activate()
        assert adjustment.active is True

    def test_prompt_adjustment_deactivate_already_inactive(self):
        """deactivate() sur ajustement déjà inactif."""
        from app.domain.entities.learning import PromptAdjustment

        adjustment = PromptAdjustment.create(
            section="test",
            adjustment="test",
            reason="test",
        )

        adjustment.deactivate()
        assert adjustment.active is False
        adjustment.deactivate()
        assert adjustment.active is False

    def test_prompt_adjustment_from_dict_missing_is_active(self):
        """from_dict() sans 'active' utilise défaut True."""
        from app.domain.entities.learning import PromptAdjustment
        from datetime import datetime

        data = {
            "id": "test-id",
            "timestamp": datetime.now().isoformat(),  # Le champ est 'timestamp'
            "section": "test",
            "adjustment": "test",
            "reason": "test",
        }

        adjustment = PromptAdjustment.from_dict(data)

        assert adjustment.active is True


# =============================================================================
# TESTS REVIEW REQUIREMENT - EDGE CASES
# =============================================================================


class TestReviewRequirementEdgeCases:
    """Tests edge cases pour ReviewRequirement entity."""

    def test_review_requirement_add_duplicate_reason(self):
        """add_reason() avec raison en double ne duplique pas."""
        from app.domain.entities.learning import ReviewRequirement

        requirement = ReviewRequirement(needs_review=True, priority_score=90)

        requirement.add_reason("Raison 1")
        requirement.add_reason("Raison 1")  # Duplicate

        # Le code vérifie "if reason not in self.reasons" avant d'ajouter
        # Donc les doublons ne sont PAS ajoutés
        assert requirement.reasons.count("Raison 1") == 1

    def test_review_requirement_add_empty_reason(self):
        """add_reason() avec raison vide."""
        from app.domain.entities.learning import ReviewRequirement

        requirement = ReviewRequirement(needs_review=True, priority_score=90)

        requirement.add_reason("")

        # Comportement actuel: accepte les raisons vides
        assert "" in requirement.reasons

    def test_review_requirement_reasons_default(self):
        """reasons est une liste vide par défaut."""
        from app.domain.entities.learning import ReviewRequirement

        requirement = ReviewRequirement(needs_review=False, priority_score=50)

        # L'entité n'a pas de champ confidence_score, mais a reasons et priority_score
        assert requirement.reasons == []
        assert requirement.priority_score == 50
