# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour la refactorisation du learning_service.py.

Objectif : Corriger la violation de Clean Architecture.
Le domaine ne doit JAMAIS importer depuis l'infrastructure.

La fonction standalone `get_enhanced_drafter_prompt` est supprimée.
La méthode `enhance_prompt` est ajoutée au `LearningService`.
"""

from unittest.mock import Mock


# =============================================================================
# TESTS DE CONFORMITÉ CLEAN ARCHITECTURE
# =============================================================================


class TestCleanArchitectureCompliance:
    """Vérifie que le domaine ne viole pas la Dependency Rule."""

    def test_learning_service_no_infrastructure_imports(self):
        """Le module learning_service.py ne doit pas importer depuis infrastructure."""
        import ast
        from pathlib import Path

        # Lire le fichier source
        source_path = Path(__file__).parent.parent / "app" / "domain" / "services" / "learning_service.py"
        source_code = source_path.read_text()

        # Parser l'AST
        tree = ast.parse(source_code)

        # Collecter tous les imports
        infrastructure_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "infrastructure" in alias.name:
                        infrastructure_imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module and "infrastructure" in node.module:
                    infrastructure_imports.append(node.module)

        # Il ne doit y avoir aucun import depuis infrastructure
        assert infrastructure_imports == [], (
            f"Violation Clean Architecture : imports depuis infrastructure trouvés : "
            f"{infrastructure_imports}"
        )

    def test_domain_service_only_imports_from_domain(self):
        """Le service de domaine ne doit importer que depuis le domaine."""
        import ast
        from pathlib import Path

        source_path = Path(__file__).parent.parent / "app" / "domain" / "services" / "learning_service.py"
        source_code = source_path.read_text()

        tree = ast.parse(source_code)

        # Imports autorisés pour un service de domaine
        allowed_prefixes = ("app.domain", "typing", "dataclasses", "datetime", "abc")

        forbidden_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                # Vérifier si l'import est autorisé
                is_allowed = any(
                    node.module.startswith(prefix)
                    for prefix in allowed_prefixes
                )
                if node.module.startswith("app.") and not is_allowed:
                    forbidden_imports.append(node.module)

        assert forbidden_imports == [], (
            f"Imports interdits dans le domaine : {forbidden_imports}"
        )


# =============================================================================
# TESTS DU LEARNING SERVICE REFACTORISÉ
# =============================================================================


class TestLearningServiceEnhancePrompt:
    """Tests pour la méthode enhance_prompt du LearningService."""

    def test_learning_service_has_enhance_prompt_method(self):
        """Le service doit avoir une méthode enhance_prompt."""
        from app.domain.services.learning_service import LearningService

        assert hasattr(LearningService, "enhance_prompt")

    def test_enhance_prompt_returns_base_when_no_adjustments(self):
        """Retourne le prompt de base s'il n'y a pas d'ajustements."""
        from app.domain.services.learning_service import LearningService

        # Mock des use cases
        mock_enhance_use_case = Mock()
        mock_enhance_use_case.execute.return_value = "Base prompt"  # Pas d'enrichissement

        service = LearningService(
            analyze_use_case=Mock(),
            extract_use_case=Mock(),
            should_review_use_case=Mock(),
            generate_adjustment_use_case=Mock(),
            stats_use_case=Mock(),
            enhance_prompt_use_case=mock_enhance_use_case,
        )

        result = service.enhance_prompt("Base prompt")

        assert result == "Base prompt"
        mock_enhance_use_case.execute.assert_called_once_with("Base prompt")

    def test_enhance_prompt_adds_learned_rules(self):
        """Ajoute les règles apprises au prompt."""
        from app.domain.services.learning_service import LearningService

        # Simuler un prompt enrichi
        enriched_prompt = """Base prompt

## Règles apprises (basées sur les feedbacks)
- Utiliser un ton amical
- Répondre de manière concise"""

        mock_enhance_use_case = Mock()
        mock_enhance_use_case.execute.return_value = enriched_prompt

        service = LearningService(
            analyze_use_case=Mock(),
            extract_use_case=Mock(),
            should_review_use_case=Mock(),
            generate_adjustment_use_case=Mock(),
            stats_use_case=Mock(),
            enhance_prompt_use_case=mock_enhance_use_case,
        )

        result = service.enhance_prompt("Base prompt")

        assert "Règles apprises" in result
        assert "ton amical" in result
        assert "concise" in result

    def test_enhance_prompt_with_empty_base(self):
        """Gère correctement un prompt vide."""
        from app.domain.services.learning_service import LearningService

        mock_enhance_use_case = Mock()
        mock_enhance_use_case.execute.return_value = ""

        service = LearningService(
            analyze_use_case=Mock(),
            extract_use_case=Mock(),
            should_review_use_case=Mock(),
            generate_adjustment_use_case=Mock(),
            stats_use_case=Mock(),
            enhance_prompt_use_case=mock_enhance_use_case,
        )

        result = service.enhance_prompt("")

        assert result == ""
        mock_enhance_use_case.execute.assert_called_once_with("")


# =============================================================================
# TESTS DE RÉTROCOMPATIBILITÉ
# =============================================================================


class TestBackwardCompatibility:
    """Tests de rétrocompatibilité avec le code legacy."""

    def test_standalone_function_removed_from_domain_service(self):
        """La fonction standalone get_enhanced_drafter_prompt doit être supprimée du domaine."""
        import importlib

        # Recharger le module pour éviter les caches
        import app.domain.services.learning_service as module
        importlib.reload(module)

        exported = [
            name for name in dir(module)
            if not name.startswith("_") and name == "get_enhanced_drafter_prompt"
        ]

        assert exported == [], (
            "get_enhanced_drafter_prompt ne doit pas être une fonction standalone "
            "dans le domaine. Utilisez LearningService.enhance_prompt() à la place."
        )

    def test_domain_services_init_exports_only_class(self):
        """L'init du module services n'exporte que la classe."""
        from app.domain.services import LearningService

        assert LearningService is not None


# =============================================================================
# TESTS DU GET ACTIVE ADJUSTMENTS USE CASE
# =============================================================================


class TestGetActiveAdjustmentsUseCase:
    """Tests pour le use case GetActiveAdjustmentsUseCase."""

    def test_get_active_adjustments_returns_list(self):
        """Retourne une liste de textes d'ajustement."""
        from app.application.learning import GetActiveAdjustmentsUseCase

        adjustments = [
            Mock(adjustment="Éviter le ton formel", active=True),
            Mock(adjustment="Être concis", active=True),
        ]

        mock_store = Mock()
        mock_store.get_active.return_value = adjustments

        use_case = GetActiveAdjustmentsUseCase(adjustment_store=mock_store)
        result = use_case.execute()

        assert result == ["Éviter le ton formel", "Être concis"]

    def test_get_active_adjustments_empty_when_no_adjustments(self):
        """Retourne une liste vide si pas d'ajustements."""
        from app.application.learning import GetActiveAdjustmentsUseCase

        mock_store = Mock()
        mock_store.get_active.return_value = []

        use_case = GetActiveAdjustmentsUseCase(adjustment_store=mock_store)
        result = use_case.execute()

        assert result == []


class TestLearningServiceGetActiveAdjustments:
    """Tests pour la méthode get_active_adjustments du service."""

    def test_uses_dedicated_use_case_when_available(self):
        """Utilise le use case dédié quand il est injecté."""
        from app.domain.services.learning_service import LearningService

        mock_get_active_use_case = Mock()
        mock_get_active_use_case.execute.return_value = ["Règle 1", "Règle 2"]

        service = LearningService(
            analyze_use_case=Mock(),
            extract_use_case=Mock(),
            should_review_use_case=Mock(),
            generate_adjustment_use_case=Mock(),
            stats_use_case=Mock(),
            enhance_prompt_use_case=Mock(),
            get_active_adjustments_use_case=mock_get_active_use_case,
        )

        result = service.get_active_adjustments()

        assert result == ["Règle 1", "Règle 2"]
        mock_get_active_use_case.execute.assert_called_once()

    def test_fallback_to_enhance_prompt_when_use_case_not_available(self):
        """Utilise enhance_prompt en fallback si use case non injecté."""
        from app.domain.services.learning_service import LearningService

        mock_enhance_use_case = Mock()
        mock_enhance_use_case.execute.return_value = """Base prompt

## Règles apprises (basées sur les feedbacks)
- Règle fallback 1
- Règle fallback 2"""

        service = LearningService(
            analyze_use_case=Mock(),
            extract_use_case=Mock(),
            should_review_use_case=Mock(),
            generate_adjustment_use_case=Mock(),
            stats_use_case=Mock(),
            enhance_prompt_use_case=mock_enhance_use_case,
            # Pas de get_active_adjustments_use_case
        )

        result = service.get_active_adjustments()

        assert "Règle fallback 1" in result
        assert "Règle fallback 2" in result


# =============================================================================
# TESTS D'INTÉGRATION
# =============================================================================


class TestLearningServiceIntegration:
    """Tests d'intégration avec le container."""

    def test_container_provides_learning_service_with_enhance(self):
        """Le container fournit un LearningService fonctionnel."""
        # Ce test simule l'injection de dépendances sans dépendances réelles
        from app.domain.services.learning_service import LearningService

        # Créer un service avec des mocks
        mock_enhance_use_case = Mock()
        mock_enhance_use_case.execute.return_value = "Enhanced prompt"

        service = LearningService(
            analyze_use_case=Mock(),
            extract_use_case=Mock(),
            should_review_use_case=Mock(),
            generate_adjustment_use_case=Mock(),
            stats_use_case=Mock(),
            enhance_prompt_use_case=mock_enhance_use_case,
        )

        assert hasattr(service, "enhance_prompt")
        result = service.enhance_prompt("Test")
        assert result == "Enhanced prompt"

    def test_enhance_prompt_via_service_with_mocked_use_case(self):
        """enhance_prompt fonctionne avec use case mocké."""
        from app.domain.services.learning_service import LearningService

        mock_enhance_use_case = Mock()
        mock_enhance_use_case.execute.return_value = "Test prompt"

        service = LearningService(
            analyze_use_case=Mock(),
            extract_use_case=Mock(),
            should_review_use_case=Mock(),
            generate_adjustment_use_case=Mock(),
            stats_use_case=Mock(),
            enhance_prompt_use_case=mock_enhance_use_case,
        )

        # Appeler enhance_prompt - ne doit pas lever d'erreur
        result = service.enhance_prompt("Test prompt")

        # Doit retourner une chaîne
        assert isinstance(result, str)
        # Doit contenir au moins le prompt de base
        assert "Test prompt" in result or result == "Test prompt"
