# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour ItemTrackerPort - le port generique de tracking.

Ce module teste le contrat du port abstrait ItemTrackerPort:
1. Interface abstraite non instanciable
2. Methodes requises definies
3. Alias de compatibilite (ProcessedEmailsTrackerPort, ProcessedDraftsTrackerPort)
4. Conformite avec Clean Architecture (Dependency Inversion Principle)

TDD: Tests ecrits pour valider le contrat du port.
Clean Architecture: Domain layer (Ports).
"""

import pytest
from abc import ABC

from app.domain.ports.item_tracker_port import (
    ItemTrackerPort,
    ProcessedEmailsTrackerPort,
    ProcessedDraftsTrackerPort,
)


# =============================================================================
# TESTS - INTERFACE ABSTRAITE
# =============================================================================


class TestItemTrackerPortIsAbstract:
    """Tests pour verifier que le port est abstrait."""

    def test_port_inherits_from_abc(self):
        """ItemTrackerPort herite de ABC."""
        assert issubclass(ItemTrackerPort, ABC)

    def test_port_cannot_be_instantiated(self):
        """Le port ne peut pas etre instancie directement."""
        with pytest.raises(TypeError) as exc_info:
            ItemTrackerPort()
        assert "abstract" in str(exc_info.value).lower()

    def test_port_requires_implementation(self):
        """Une implementation incomplete leve TypeError."""
        class IncompleteTracker(ItemTrackerPort):
            # Ne definit pas toutes les methodes abstraites
            pass

        with pytest.raises(TypeError):
            IncompleteTracker()


class TestItemTrackerPortMethods:
    """Tests pour les methodes requises du port."""

    def test_has_is_processed_method(self):
        """Le port definit is_processed."""
        assert hasattr(ItemTrackerPort, "is_processed")

    def test_has_mark_processed_method(self):
        """Le port definit mark_processed."""
        assert hasattr(ItemTrackerPort, "mark_processed")

    def test_has_count_method(self):
        """Le port definit count."""
        assert hasattr(ItemTrackerPort, "count")

    def test_has_get_all_ids_method(self):
        """Le port definit get_all_ids."""
        assert hasattr(ItemTrackerPort, "get_all_ids")

    def test_has_clear_method(self):
        """Le port definit clear."""
        assert hasattr(ItemTrackerPort, "clear")

    def test_all_methods_are_abstract(self):
        """Toutes les methodes du port sont abstraites."""
        abstract_methods = ItemTrackerPort.__abstractmethods__
        expected = {"is_processed", "mark_processed", "count", "get_all_ids", "clear"}
        assert abstract_methods == expected


class TestItemTrackerPortMethodSignatures:
    """Tests pour les signatures des methodes."""

    def test_is_processed_takes_item_id(self):
        """is_processed prend item_id en parametre."""
        import inspect
        sig = inspect.signature(ItemTrackerPort.is_processed)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "item_id" in params

    def test_mark_processed_takes_item_id(self):
        """mark_processed prend item_id en parametre."""
        import inspect
        sig = inspect.signature(ItemTrackerPort.mark_processed)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "item_id" in params

    def test_count_takes_no_args(self):
        """count ne prend pas d'arguments."""
        import inspect
        sig = inspect.signature(ItemTrackerPort.count)
        params = list(sig.parameters.keys())
        assert params == ["self"]

    def test_get_all_ids_takes_no_args(self):
        """get_all_ids ne prend pas d'arguments."""
        import inspect
        sig = inspect.signature(ItemTrackerPort.get_all_ids)
        params = list(sig.parameters.keys())
        assert params == ["self"]

    def test_clear_takes_no_args(self):
        """clear ne prend pas d'arguments."""
        import inspect
        sig = inspect.signature(ItemTrackerPort.clear)
        params = list(sig.parameters.keys())
        assert params == ["self"]


# =============================================================================
# TESTS - ALIAS DE COMPATIBILITE
# =============================================================================


class TestProcessedEmailsTrackerPortAlias:
    """Tests pour l'alias ProcessedEmailsTrackerPort."""

    def test_alias_points_to_item_tracker_port(self):
        """ProcessedEmailsTrackerPort est un alias de ItemTrackerPort."""
        assert ProcessedEmailsTrackerPort is ItemTrackerPort

    def test_alias_is_abstract(self):
        """L'alias est aussi abstrait."""
        with pytest.raises(TypeError):
            ProcessedEmailsTrackerPort()


class TestProcessedDraftsTrackerPortAlias:
    """Tests pour l'alias ProcessedDraftsTrackerPort."""

    def test_alias_points_to_item_tracker_port(self):
        """ProcessedDraftsTrackerPort est un alias de ItemTrackerPort."""
        assert ProcessedDraftsTrackerPort is ItemTrackerPort

    def test_alias_is_abstract(self):
        """L'alias est aussi abstrait."""
        with pytest.raises(TypeError):
            ProcessedDraftsTrackerPort()


# =============================================================================
# TESTS - IMPLEMENTATION CONFORME
# =============================================================================


class TestConformantImplementation:
    """Tests pour verifier qu'une implementation conforme est valide."""

    def test_complete_implementation_can_be_instantiated(self):
        """Une implementation complete peut etre instanciee."""
        class ConformantTracker(ItemTrackerPort):
            def __init__(self):
                self._ids = set()

            def is_processed(self, item_id: str) -> bool:
                return item_id in self._ids

            def mark_processed(self, item_id: str) -> None:
                self._ids.add(item_id)

            def count(self) -> int:
                return len(self._ids)

            def get_all_ids(self):
                return self._ids.copy()

            def clear(self) -> None:
                self._ids.clear()

        # Doit pouvoir etre instancie
        tracker = ConformantTracker()
        assert tracker is not None
        assert isinstance(tracker, ItemTrackerPort)

    def test_implementation_passes_isinstance_check(self):
        """Une implementation passe isinstance(x, ItemTrackerPort)."""
        class MinimalTracker(ItemTrackerPort):
            def is_processed(self, item_id: str) -> bool:
                return False

            def mark_processed(self, item_id: str) -> None:
                pass

            def count(self) -> int:
                return 0

            def get_all_ids(self):
                return set()

            def clear(self) -> None:
                pass

        tracker = MinimalTracker()
        assert isinstance(tracker, ItemTrackerPort)
        # Doit aussi passer pour les alias
        assert isinstance(tracker, ProcessedEmailsTrackerPort)
        assert isinstance(tracker, ProcessedDraftsTrackerPort)


# =============================================================================
# TESTS - CLEAN ARCHITECTURE COMPLIANCE
# =============================================================================


class TestCleanArchitectureCompliance:
    """Tests pour la conformite Clean Architecture."""

    def test_port_has_no_implementation_details(self):
        """Le port ne contient aucun detail d'implementation."""
        # Verifie qu'il n'y a pas de variables d'instance dans la classe
        class_attrs = [
            attr for attr in dir(ItemTrackerPort)
            if not attr.startswith("_") and not callable(getattr(ItemTrackerPort, attr, None))
        ]
        assert class_attrs == []

    def test_port_does_not_import_infrastructure(self):
        """Le port ne depend pas de l'infrastructure."""
        import inspect
        source = inspect.getsource(ItemTrackerPort)
        # Ne devrait pas importer json, pathlib, etc.
        assert "import json" not in source
        assert "from pathlib" not in source
        assert "import os" not in source

    def test_port_module_only_uses_abc_and_typing(self):
        """Le module du port n'utilise que abc et typing."""
        from app.domain.ports import item_tracker_port
        import_statements = []
        import inspect
        source = inspect.getsource(item_tracker_port)
        lines = source.split("\n")
        for line in lines:
            if line.strip().startswith("from ") or line.strip().startswith("import "):
                import_statements.append(line.strip())

        # Seuls abc et typing sont autorises
        for stmt in import_statements:
            assert (
                "abc" in stmt or
                "typing" in stmt
            ), f"Import non autorise dans le port: {stmt}"


# =============================================================================
# TESTS - DOCUMENTATION
# =============================================================================


class TestPortDocumentation:
    """Tests pour la documentation du port."""

    def test_port_has_docstring(self):
        """Le port a une docstring."""
        assert ItemTrackerPort.__doc__ is not None
        assert len(ItemTrackerPort.__doc__) > 50

    def test_is_processed_has_docstring(self):
        """is_processed a une docstring."""
        assert ItemTrackerPort.is_processed.__doc__ is not None

    def test_mark_processed_has_docstring(self):
        """mark_processed a une docstring."""
        assert ItemTrackerPort.mark_processed.__doc__ is not None

    def test_count_has_docstring(self):
        """count a une docstring."""
        assert ItemTrackerPort.count.__doc__ is not None

    def test_get_all_ids_has_docstring(self):
        """get_all_ids a une docstring."""
        assert ItemTrackerPort.get_all_ids.__doc__ is not None

    def test_clear_has_docstring(self):
        """clear a une docstring."""
        assert ItemTrackerPort.clear.__doc__ is not None


# =============================================================================
# TESTS - TYPE HINTS
# =============================================================================


class TestPortTypeHints:
    """Tests pour les annotations de type."""

    def test_is_processed_returns_bool(self):
        """is_processed retourne bool."""
        import inspect
        sig = inspect.signature(ItemTrackerPort.is_processed)
        assert sig.return_annotation is bool

    def test_mark_processed_returns_none(self):
        """mark_processed retourne None."""
        import inspect
        sig = inspect.signature(ItemTrackerPort.mark_processed)
        # None annotation peut etre None ou type(None) selon Python
        assert sig.return_annotation is None or sig.return_annotation is type(None)

    def test_count_returns_int(self):
        """count retourne int."""
        import inspect
        sig = inspect.signature(ItemTrackerPort.count)
        assert sig.return_annotation is int

    def test_item_id_is_str(self):
        """item_id est de type str."""
        import inspect
        sig = inspect.signature(ItemTrackerPort.is_processed)
        item_id_param = sig.parameters.get("item_id")
        assert item_id_param is not None
        assert item_id_param.annotation is str
