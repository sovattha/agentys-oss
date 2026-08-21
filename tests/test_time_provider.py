# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le TimeProvider (Clock Pattern).

Ce module teste l'abstraction du temps pour la Clean Architecture.
Les entités du domaine ne doivent pas dépendre directement de datetime.now().
"""

import pytest
from datetime import datetime, timedelta

from app.domain.ports.time_provider import TimeProvider
from app.infrastructure.clock import SystemClock, FakeClock


class TestTimeProviderInterface:
    """Tests pour l'interface TimeProvider."""

    def test_time_provider_is_abstract(self):
        """TimeProvider ne peut pas être instancié directement."""
        with pytest.raises(TypeError):
            TimeProvider()  # type: ignore

    def test_time_provider_defines_now_method(self):
        """TimeProvider doit définir la méthode now()."""
        assert hasattr(TimeProvider, "now")


class TestSystemClock:
    """Tests pour SystemClock (implémentation production)."""

    def test_system_clock_implements_time_provider(self):
        """SystemClock implémente TimeProvider."""
        clock = SystemClock()
        assert isinstance(clock, TimeProvider)

    def test_system_clock_returns_datetime(self):
        """SystemClock.now() retourne un datetime."""
        clock = SystemClock()
        result = clock.now()
        assert isinstance(result, datetime)

    def test_system_clock_returns_current_time(self):
        """SystemClock.now() retourne l'heure courante."""
        clock = SystemClock()
        before = datetime.now()
        result = clock.now()
        after = datetime.now()
        assert before <= result <= after

    def test_system_clock_returns_consistent_time(self):
        """SystemClock retourne des temps cohérents dans un court intervalle."""
        clock = SystemClock()
        result1 = clock.now()
        result2 = clock.now()
        # Les deux appels doivent être très proches (moins de 1 seconde)
        assert abs((result2 - result1).total_seconds()) < 1

    def test_system_clock_str_representation(self):
        """SystemClock a une représentation string lisible."""
        clock = SystemClock()
        str_repr = str(clock)
        assert "SystemClock" in str_repr
        # Format attendu: SystemClock(YYYY-MM-DD HH:MM:SS)
        assert "-" in str_repr  # Date format
        assert ":" in str_repr  # Time format

    def test_system_clock_repr(self):
        """SystemClock a une représentation repr complète."""
        clock = SystemClock()
        repr_str = repr(clock)
        assert "SystemClock" in repr_str
        assert "current=" in repr_str


class TestFakeClock:
    """Tests pour FakeClock (implémentation tests)."""

    def test_fake_clock_implements_time_provider(self):
        """FakeClock implémente TimeProvider."""
        clock = FakeClock()
        assert isinstance(clock, TimeProvider)

    def test_fake_clock_default_time(self):
        """FakeClock utilise l'heure courante par défaut."""
        before = datetime.now()
        clock = FakeClock()
        after = datetime.now()
        assert before <= clock.now() <= after

    def test_fake_clock_with_fixed_time(self):
        """FakeClock peut être initialisé avec un temps fixe."""
        fixed_time = datetime(2024, 1, 15, 14, 30, 0)
        clock = FakeClock(fixed_time)
        assert clock.now() == fixed_time

    def test_fake_clock_set_time(self):
        """FakeClock.set_time() permet de changer l'heure."""
        clock = FakeClock()
        new_time = datetime(2025, 12, 25, 0, 0, 0)
        clock.set_time(new_time)
        assert clock.now() == new_time

    def test_fake_clock_advance_by(self):
        """FakeClock.advance_by() avance l'heure."""
        start_time = datetime(2024, 1, 1, 12, 0, 0)
        clock = FakeClock(start_time)
        clock.advance_by(hours=2, minutes=30)
        expected = datetime(2024, 1, 1, 14, 30, 0)
        assert clock.now() == expected

    def test_fake_clock_advance_by_days(self):
        """FakeClock.advance_by() avance de plusieurs jours."""
        start_time = datetime(2024, 1, 1, 12, 0, 0)
        clock = FakeClock(start_time)
        clock.advance_by(days=5)
        expected = datetime(2024, 1, 6, 12, 0, 0)
        assert clock.now() == expected

    def test_fake_clock_advance_by_timedelta(self):
        """FakeClock.advance_by_delta() accepte un timedelta."""
        start_time = datetime(2024, 1, 1, 12, 0, 0)
        clock = FakeClock(start_time)
        clock.advance_by_delta(timedelta(hours=3, minutes=45))
        expected = datetime(2024, 1, 1, 15, 45, 0)
        assert clock.now() == expected

    def test_fake_clock_immutable_per_call(self):
        """FakeClock.now() retourne la même valeur sans avancement."""
        fixed_time = datetime(2024, 6, 15, 10, 30, 0)
        clock = FakeClock(fixed_time)
        result1 = clock.now()
        result2 = clock.now()
        assert result1 == result2 == fixed_time

    def test_fake_clock_advance_by_seconds(self):
        """FakeClock.advance_by() avance de secondes."""
        start_time = datetime(2024, 1, 1, 12, 0, 0)
        clock = FakeClock(start_time)
        clock.advance_by(seconds=45)
        expected = datetime(2024, 1, 1, 12, 0, 45)
        assert clock.now() == expected

    def test_fake_clock_advance_by_milliseconds(self):
        """FakeClock.advance_by() avance de millisecondes."""
        start_time = datetime(2024, 1, 1, 12, 0, 0)
        clock = FakeClock(start_time)
        clock.advance_by(milliseconds=500)
        expected = datetime(2024, 1, 1, 12, 0, 0, 500000)
        assert clock.now() == expected


class TestClockIntegration:
    """Tests d'intégration pour les clocks."""

    def test_clocks_are_interchangeable(self):
        """SystemClock et FakeClock sont interchangeables via TimeProvider."""
        def get_timestamp(clock: TimeProvider) -> datetime:
            return clock.now()

        system_clock = SystemClock()
        fake_clock = FakeClock(datetime(2024, 1, 1, 0, 0, 0))

        # Les deux fonctionnent avec la même fonction
        system_result = get_timestamp(system_clock)
        fake_result = get_timestamp(fake_clock)

        assert isinstance(system_result, datetime)
        assert fake_result == datetime(2024, 1, 1, 0, 0, 0)

    def test_fake_clock_for_time_sensitive_tests(self):
        """Démo: FakeClock permet des tests déterministes."""
        # Simuler un processus qui expire après 1 heure
        clock = FakeClock(datetime(2024, 1, 1, 10, 0, 0))
        expiry_time = clock.now() + timedelta(hours=1)

        # Immédiatement après: pas expiré
        assert clock.now() < expiry_time

        # Avancer de 30 minutes: toujours valide
        clock.advance_by(minutes=30)
        assert clock.now() < expiry_time

        # Avancer de 31 minutes supplémentaires: expiré
        clock.advance_by(minutes=31)
        assert clock.now() > expiry_time


class TestClockUtilities:
    """Tests pour les utilitaires de clock."""

    def test_fake_clock_reset(self):
        """FakeClock.reset() remet l'heure initiale."""
        initial_time = datetime(2024, 1, 1, 0, 0, 0)
        clock = FakeClock(initial_time)
        clock.advance_by(days=10)
        clock.reset()
        assert clock.now() == initial_time

    def test_fake_clock_elapsed_since_start(self):
        """FakeClock.elapsed() retourne le temps écoulé depuis le début."""
        initial_time = datetime(2024, 1, 1, 0, 0, 0)
        clock = FakeClock(initial_time)
        clock.advance_by(hours=5, minutes=30)
        elapsed = clock.elapsed()
        assert elapsed == timedelta(hours=5, minutes=30)

    def test_fake_clock_str_representation(self):
        """FakeClock a une représentation string lisible."""
        fixed_time = datetime(2024, 6, 15, 10, 30, 0)
        clock = FakeClock(fixed_time)
        str_repr = str(clock)
        assert "2024-06-15" in str_repr
        assert "10:30:00" in str_repr

    def test_fake_clock_repr_representation(self):
        """FakeClock a une représentation repr complète."""
        fixed_time = datetime(2024, 6, 15, 10, 30, 0)
        clock = FakeClock(fixed_time)
        repr_str = repr(clock)
        assert "FakeClock" in repr_str
        assert "current=" in repr_str
        assert "initial=" in repr_str


class TestClockFactory:
    """Tests pour la factory function."""

    def test_get_clock_default_returns_system_clock(self):
        """get_clock() sans arguments retourne SystemClock."""
        from app.infrastructure.clock import get_clock
        clock = get_clock()
        assert isinstance(clock, SystemClock)

    def test_get_clock_with_use_fake_returns_fake_clock(self):
        """get_clock(use_fake=True) retourne FakeClock."""
        from app.infrastructure.clock import get_clock
        clock = get_clock(use_fake=True)
        assert isinstance(clock, FakeClock)

    def test_get_clock_with_initial_time(self):
        """get_clock() passe initial_time à FakeClock."""
        from app.infrastructure.clock import get_clock
        fixed_time = datetime(2024, 1, 1, 0, 0, 0)
        clock = get_clock(use_fake=True, initial_time=fixed_time)
        assert clock.now() == fixed_time


class TestContainerIntegration:
    """Tests d'intégration avec le Container."""

    def test_container_has_clock_property(self):
        """Container expose une propriété clock."""
        from app.infrastructure.container import Container
        container = Container()
        assert hasattr(container, "clock")

    def test_container_clock_is_system_clock_by_default(self):
        """Container.clock retourne SystemClock par défaut."""
        from app.infrastructure.container import Container
        container = Container()
        assert isinstance(container.clock, SystemClock)

    def test_container_set_clock(self):
        """Container.set_clock() permet d'injecter un FakeClock."""
        from app.infrastructure.container import Container
        container = Container()
        fake_clock = FakeClock(datetime(2024, 1, 1, 0, 0, 0))
        container.set_clock(fake_clock)
        assert container.clock is fake_clock
        assert container.clock.now() == datetime(2024, 1, 1, 0, 0, 0)

    def test_container_clock_is_singleton(self):
        """Container.clock retourne le même objet à chaque appel."""
        from app.infrastructure.container import Container
        container = Container()
        clock1 = container.clock
        clock2 = container.clock
        assert clock1 is clock2
