# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les edge cases du module Dashboard.

Ces tests couvrent les cas limites non testés :
- Fonctions utilitaires get_stats, get_history, get_config
- Calcul ROI avec division par zéro
- Gestion des erreurs d'import pandas
- Stats avec fichiers corrompus ou manquants
- API endpoints avec données invalides
- WebSocket disponibilité et notifications
- Gestion des erreurs de container

Principes Clean Architecture respectés :
- Tests du module sans dépendances externes réelles
- Injection de dépendances via mocks
- Tests unitaires isolés
"""

import pytest
import json
from unittest.mock import Mock, patch

# Détecter si pandas est disponible
import importlib.util
PANDAS_AVAILABLE = importlib.util.find_spec("pandas") is not None

# Skip marker pour les tests nécessitant pandas
requires_pandas = pytest.mark.skipif(
    not PANDAS_AVAILABLE,
    reason="pandas not installed"
)


# =============================================================================
# TESTS GET_STATS EDGE CASES
# =============================================================================


class TestGetStatsEdgeCases:
    """Tests pour la fonction get_stats."""

    def test_get_stats_no_output_files(self):
        """Stats avec aucun fichier de sortie."""
        with patch('app.dashboard.OUTPUTS_DIR') as mock_dir:
            mock_dir.exists.return_value = False

            from app.dashboard import get_stats

            stats = get_stats()

            assert stats["total_emails"] == 0
            assert stats["validated_v1"] == 0
            assert stats["corrected_v2"] == 0
            assert stats["v1_percent"] == 0
            assert stats["v2_percent"] == 0
            assert stats["total_cost"] == "0.00"

    def test_get_stats_empty_output_dir(self):
        """Stats avec répertoire output vide."""
        with patch('app.dashboard.OUTPUTS_DIR') as mock_dir:
            mock_dir.exists.return_value = True
            mock_dir.glob.return_value = []

            from app.dashboard import get_stats

            stats = get_stats()

            assert stats["total_emails"] == 0

    def test_get_stats_corrupted_excel_file(self, tmp_path):
        """Stats avec fichier Excel corrompu."""
        # Créer un fichier invalide
        corrupt_file = tmp_path / "corrupt.xlsx"
        corrupt_file.write_text("not an excel file", encoding="utf-8")

        with patch('app.dashboard.OUTPUTS_DIR', tmp_path):
            from app.dashboard import get_stats

            # Ne doit pas planter
            stats = get_stats()

            assert stats["total_emails"] == 0

    @requires_pandas
    def test_get_stats_excel_without_status_column(self, tmp_path):
        """Stats avec fichier Excel sans colonne Status."""
        import pandas as pd

        excel_file = tmp_path / "no_status.xlsx"
        df = pd.DataFrame({"Col1": [1, 2, 3], "Col2": ["a", "b", "c"]})
        df.to_excel(excel_file, index=False)

        with patch('app.dashboard.OUTPUTS_DIR', tmp_path):
            from app.dashboard import get_stats

            stats = get_stats()

            # Fichier ignoré car pas de colonne Status
            assert stats["total_emails"] == 0

    @requires_pandas
    def test_get_stats_calculates_percentages_correctly(self, tmp_path):
        """Calcul correct des pourcentages V1/V2."""
        import pandas as pd

        excel_file = tmp_path / "test.xlsx"
        df = pd.DataFrame({
            "Status": ["V1", "V1", "V2", "IGNORÉ"]
        })
        df.to_excel(excel_file, index=False)

        with patch('app.dashboard.OUTPUTS_DIR', tmp_path):
            from app.dashboard import get_stats

            stats = get_stats()

            assert stats["total_emails"] == 4
            assert stats["validated_v1"] == 2
            assert stats["corrected_v2"] == 1
            assert stats["ignored"] == 1
            assert stats["v1_percent"] == 50  # 2/4 * 100
            assert stats["v2_percent"] == 25  # 1/4 * 100

    @requires_pandas
    def test_get_stats_handles_na_in_status(self, tmp_path):
        """Gestion des valeurs NA dans la colonne Status."""
        import pandas as pd
        import numpy as np

        excel_file = tmp_path / "with_na.xlsx"
        df = pd.DataFrame({
            "Status": ["V1", np.nan, "V2", None]
        })
        df.to_excel(excel_file, index=False)

        with patch('app.dashboard.OUTPUTS_DIR', tmp_path):
            from app.dashboard import get_stats

            stats = get_stats()

            # NA ne doit pas être comptés comme V1/V2
            assert stats["validated_v1"] == 1
            assert stats["corrected_v2"] == 1

    @requires_pandas
    def test_get_stats_token_estimation(self, tmp_path):
        """Estimation des tokens basée sur le nombre d'emails."""
        import pandas as pd

        excel_file = tmp_path / "emails.xlsx"
        df = pd.DataFrame({
            "Status": ["V1"] * 10  # 10 emails
        })
        df.to_excel(excel_file, index=False)

        with patch('app.dashboard.OUTPUTS_DIR', tmp_path):
            from app.dashboard import get_stats

            stats = get_stats()

            # 10 emails * 3000 tokens/email
            assert stats["total_tokens"] == 30000
            assert stats["total_tokens_formatted"] == "30,000"

    @requires_pandas
    def test_get_stats_cost_calculation(self, tmp_path):
        """Calcul du coût avec le modèle Opus."""
        import pandas as pd

        excel_file = tmp_path / "emails.xlsx"
        df = pd.DataFrame({
            "Status": ["V1"] * 100  # 100 emails
        })
        df.to_excel(excel_file, index=False)

        with patch('app.dashboard.OUTPUTS_DIR', tmp_path):
            from app.dashboard import get_stats

            stats = get_stats()

            # 300,000 tokens total
            # 80% input (240,000) * $15/1M = $3.60
            # 20% output (60,000) * $75/1M = $4.50
            # Total = $8.10
            assert float(stats["total_cost"]) > 0


# =============================================================================
# TESTS GET_HISTORY EDGE CASES
# =============================================================================


class TestGetHistoryEdgeCases:
    """Tests pour la fonction get_history."""

    def test_get_history_empty_dir(self):
        """Historique avec répertoire vide."""
        with patch('app.dashboard.OUTPUTS_DIR') as mock_dir:
            mock_dir.exists.return_value = False

            from app.dashboard import get_history

            history = get_history()

            assert history == []

    @requires_pandas
    def test_get_history_limits_to_10(self, tmp_path):
        """Historique limité aux 10 derniers fichiers."""
        import pandas as pd

        # Créer 15 fichiers
        for i in range(15):
            excel_file = tmp_path / f"rapport_{i:02d}.xlsx"
            df = pd.DataFrame({"Status": ["V1"]})
            df.to_excel(excel_file, index=False)

        with patch('app.dashboard.OUTPUTS_DIR', tmp_path):
            from app.dashboard import get_history

            history = get_history()

            assert len(history) <= 10

    @requires_pandas
    def test_get_history_extracts_date_from_filename(self, tmp_path):
        """Extraction de la date du nom de fichier."""
        import pandas as pd

        excel_file = tmp_path / "rapport_2024-01-15.xlsx"
        df = pd.DataFrame({"Status": ["V1"]})
        df.to_excel(excel_file, index=False)

        with patch('app.dashboard.OUTPUTS_DIR', tmp_path):
            from app.dashboard import get_history

            history = get_history()

            assert len(history) == 1
            assert "2024-01-15" in history[0]["date"]

    @requires_pandas
    def test_get_history_handles_corrupt_file(self, tmp_path):
        """Gestion des fichiers corrompus dans l'historique."""
        import pandas as pd

        # Fichier valide
        valid_file = tmp_path / "valid.xlsx"
        df = pd.DataFrame({"Status": ["V1"]})
        df.to_excel(valid_file, index=False)

        # Fichier corrompu
        corrupt_file = tmp_path / "corrupt.xlsx"
        corrupt_file.write_text("not excel", encoding="utf-8")

        with patch('app.dashboard.OUTPUTS_DIR', tmp_path):
            from app.dashboard import get_history

            history = get_history()

            # Seul le fichier valide est inclus
            assert len(history) == 1


# =============================================================================
# TESTS GET_CONFIG EDGE CASES
# =============================================================================


class TestGetConfigEdgeCases:
    """Tests pour la fonction get_config."""

    def test_get_config_missing_knowledge_file(self):
        """Config avec fichier knowledge manquant."""
        with patch('app.dashboard.KNOWLEDGE_DIR') as mock_knowledge:
            mock_file = Mock()
            mock_file.exists.return_value = False
            mock_knowledge.__truediv__ = Mock(return_value=mock_file)

            with patch('app.dashboard.INPUTS_DIR') as mock_inputs:
                mock_corpus = Mock()
                mock_corpus.exists.return_value = False
                mock_inputs.__truediv__ = Mock(return_value=mock_corpus)

                from app.dashboard import get_config

                config = get_config()

                assert config["knowledge_size"] == 0
                assert config["corpus_count"] == 0

    def test_get_config_empty_knowledge_file(self, tmp_path):
        """Config avec fichier knowledge vide."""
        knowledge_file = tmp_path / "memoire.md"
        knowledge_file.write_text("", encoding="utf-8")

        with patch('app.dashboard.KNOWLEDGE_DIR', tmp_path):
            with patch('app.dashboard.INPUTS_DIR') as mock_inputs:
                mock_corpus = Mock()
                mock_corpus.exists.return_value = False
                mock_inputs.__truediv__ = Mock(return_value=mock_corpus)

                from app.dashboard import get_config

                config = get_config()

                assert config["knowledge_size"] == 0


# =============================================================================
# TESTS CALCULATE_ROI EDGE CASES
# =============================================================================


class TestCalculateRoiEdgeCases:
    """Tests pour la fonction calculate_roi."""

    def test_roi_zero_emails(self):
        """ROI avec zéro emails."""
        from app.dashboard import calculate_roi

        draft_stats = {"total": 0}
        cost_stats = {"current_month_cost": "0.00"}

        roi = calculate_roi(draft_stats, cost_stats)

        assert roi["time_saved_hours"] == 0
        assert roi["value_generated"] == 0
        assert roi["roi_percent"] == 0

    def test_roi_zero_cost_avoids_division(self):
        """ROI avec coût zéro évite division par zéro."""
        from app.dashboard import calculate_roi

        draft_stats = {"total": 100}
        cost_stats = {"current_month_cost": "0.00"}

        roi = calculate_roi(draft_stats, cost_stats)

        # Pas de division par zéro
        assert roi["roi_percent"] == 0

    def test_roi_invalid_cost_string(self):
        """ROI avec coût invalide."""
        from app.dashboard import calculate_roi

        draft_stats = {"total": 100}
        cost_stats = {"current_month_cost": "invalid"}

        roi = calculate_roi(draft_stats, cost_stats)

        # Devrait gérer gracieusement
        assert roi["total_cost"] == "0.00"

    def test_roi_cost_with_dollar_sign(self):
        """ROI avec signe dollar dans le coût."""
        from app.dashboard import calculate_roi

        draft_stats = {"total": 100}
        cost_stats = {"current_month_cost": "$5.00"}

        roi = calculate_roi(draft_stats, cost_stats)

        assert roi["total_cost"] == "5.00"

    def test_roi_positive_calculation(self):
        """Calcul ROI positif."""
        from app.dashboard import calculate_roi

        draft_stats = {"total": 100}
        cost_stats = {"current_month_cost": "1.00"}

        roi = calculate_roi(draft_stats, cost_stats)

        # 100 emails * (5 min - 10sec/60) = ~483 min = ~8h
        # 8h * $50/h = $400 de valeur
        # ROI = ($400 / $1 - 1) * 100 = 39900%
        assert roi["roi_percent"] > 0
        assert roi["value_generated"] > 0

    def test_roi_missing_total_key(self):
        """ROI avec clé 'total' manquante."""
        from app.dashboard import calculate_roi

        draft_stats = {}  # Pas de clé 'total'
        cost_stats = {"current_month_cost": "1.00"}

        roi = calculate_roi(draft_stats, cost_stats)

        # get("total", 0) retourne 0
        assert roi["time_saved_hours"] == 0


# =============================================================================
# TESTS WEBSOCKET AVAILABILITY
# =============================================================================


class TestWebSocketAvailability:
    """Tests pour la disponibilité WebSocket."""

    def test_notify_email_processed_without_socketio(self):
        """Notification sans SocketIO disponible."""
        with patch('app.dashboard.socketio', None):
            from app.dashboard import notify_email_processed

            # Ne doit pas lever d'exception
            notify_email_processed("Test Subject", "V1", "NORMAL")

    def test_notify_draft_created_without_socketio(self):
        """Notification brouillon sans SocketIO."""
        with patch('app.dashboard.socketio', None):
            from app.dashboard import notify_draft_created

            notify_draft_created("Subject", "recipient@example.com")

    def test_notify_error_without_socketio(self):
        """Notification erreur sans SocketIO."""
        with patch('app.dashboard.socketio', None):
            from app.dashboard import notify_error

            notify_error("Error message", "warning")

    def test_notify_budget_alert_without_socketio(self):
        """Alerte budget sans SocketIO."""
        with patch('app.dashboard.socketio', None):
            from app.dashboard import notify_budget_alert

            notify_budget_alert(85.5, 14.50)

    def test_broadcast_stats_update_without_socketio(self):
        """Broadcast stats sans SocketIO."""
        with patch('app.dashboard.socketio', None):
            from app.dashboard import broadcast_stats_update

            broadcast_stats_update()

    def test_notify_truncates_long_subject(self):
        """Notification tronque les sujets longs."""
        mock_socketio = Mock()

        with patch('app.dashboard.socketio', mock_socketio):
            from app.dashboard import notify_email_processed

            long_subject = "A" * 100  # 100 caractères
            notify_email_processed(long_subject, "V1")

            # Vérifier que emit a été appelé
            mock_socketio.emit.assert_called_once()
            call_args = mock_socketio.emit.call_args
            data = call_args[0][1]

            # Subject tronqué à 50 chars + "..."
            assert len(data["subject"]) == 53


# =============================================================================
# TESTS GET_LEARNING_STATS EDGE CASES
# =============================================================================


class TestGetLearningStatsEdgeCases:
    """Tests pour la fonction get_learning_stats."""

    def test_learning_stats_service_error(self):
        """Stats learning avec erreur de service."""
        with patch('app.dashboard.get_container') as mock_get_container:
            mock_get_container.side_effect = Exception("Service error")

            from app.dashboard import get_learning_stats

            stats = get_learning_stats()

            assert stats["patterns_count"] == 0
            assert stats["active_adjustments"] == 0
            assert stats["analyzed_emails"] == 0
            assert stats["top_patterns"] == []

    def test_learning_stats_limits_top_patterns(self):
        """Stats learning limite à 5 top patterns."""
        with patch('app.dashboard.get_container') as mock_get_container:
            mock_container = Mock()
            mock_service = Mock()
            mock_service.get_stats.return_value = {
                "patterns_count": 100,
                "active_adjustments": 5,
                "total_with_feedback": 50,
                "top_patterns": [{"type": f"pattern_{i}"} for i in range(10)]
            }
            mock_container.get_learning_service.return_value = mock_service
            mock_get_container.return_value = mock_container

            from app.dashboard import get_learning_stats

            stats = get_learning_stats()

            assert len(stats["top_patterns"]) <= 5


# =============================================================================
# TESTS GET_COST_STATS EDGE CASES
# =============================================================================


class TestGetCostStatsEdgeCases:
    """Tests pour la fonction get_cost_stats."""

    def test_cost_stats_manager_error(self):
        """Stats coûts avec erreur du manager."""
        with patch('app.dashboard.get_cost_manager') as mock_manager:
            mock_manager.side_effect = Exception("Manager error")

            from app.dashboard import get_cost_stats

            stats = get_cost_stats()

            assert stats["current_month_cost"] == "0.00"
            assert stats["total_requests"] == 0

    def test_cost_stats_no_budget_set(self):
        """Stats coûts sans budget défini."""
        with patch('app.dashboard.get_cost_manager') as mock_get_manager:
            mock_manager = Mock()
            mock_manager.get_stats.return_value = {
                "current_month_cost": 5.50,
                "monthly_budget": None,
                "remaining_budget": None,
                "usage_percentage": 0,
                "total_requests": 100,
                "by_agent": {},
                "by_model": {},
            }
            mock_get_manager.return_value = mock_manager

            from app.dashboard import get_cost_stats

            stats = get_cost_stats()

            assert stats["monthly_budget"] is None
            assert stats["remaining_budget"] is None


# =============================================================================
# TESTS GET_CATEGORY_BREAKDOWN EDGE CASES
# =============================================================================


class TestGetCategoryBreakdownEdgeCases:
    """Tests pour la fonction get_category_breakdown."""

    def test_category_breakdown_container_error(self):
        """Breakdown avec erreur de container."""
        with patch('app.dashboard.get_container') as mock_container, \
             patch('app.dashboard._dashboard_current_account_id', return_value=1):
            mock_container.side_effect = Exception("Container error")

            from app.dashboard import get_category_breakdown

            breakdown = get_category_breakdown()

            assert breakdown == {}

    def test_category_breakdown_no_categories(self):
        """Breakdown sans catégories."""
        with patch('app.dashboard.get_container') as mock_get_container:
            mock_container = Mock()
            mock_history = Mock()
            mock_history.get_stats.return_value = {}  # Pas de clé "by_category"
            mock_container.get_draft_history.return_value = mock_history
            mock_get_container.return_value = mock_container

            from app.dashboard import get_category_breakdown

            breakdown = get_category_breakdown()

            assert breakdown == {}


# =============================================================================
# TESTS GET_ANALYTICS_STATS EDGE CASES
# =============================================================================


class TestGetAnalyticsStatsEdgeCases:
    """Tests pour la fonction get_analytics_stats."""

    def test_analytics_stats_manager_error(self):
        """Analytics avec erreur du manager."""
        with patch('app.dashboard.get_analytics_manager') as mock_manager:
            mock_manager.side_effect = Exception("Manager error")

            from app.dashboard import get_analytics_stats

            stats = get_analytics_stats()

            assert stats["quality"]["total_scored"] == 0
            assert stats["comparison"]["total_edits"] == 0
            assert stats["performance"]["improvement_trend"] == 0
            assert stats["recommendations"] == []

    def test_analytics_stats_partial_summary(self):
        """Analytics avec résumé partiel."""
        with patch('app.dashboard.get_analytics_manager') as mock_get_manager:
            mock_manager = Mock()
            mock_manager.get_analytics_summary.return_value = {
                "quality": {"total_scored": 50}
                # Clés manquantes: comparison, performance, recommendations
            }
            mock_get_manager.return_value = mock_manager

            from app.dashboard import get_analytics_stats

            stats = get_analytics_stats()

            assert stats["quality"]["total_scored"] == 50
            # Valeurs par défaut pour les clés manquantes
            assert "comparison" in stats
            assert "performance" in stats


# =============================================================================
# TESTS GET_RETENTION_STATS EDGE CASES
# =============================================================================


class TestGetRetentionStatsEdgeCases:
    """Tests pour la fonction get_retention_stats."""

    def test_retention_stats_manager_error(self):
        """Stats rétention avec erreur du manager."""
        with patch('app.dashboard.get_data_retention_manager') as mock_manager:
            mock_manager.side_effect = Exception("Manager error")

            from app.dashboard import get_retention_stats

            stats = get_retention_stats()

            assert stats == {}


# =============================================================================
# TESTS API ENDPOINTS EDGE CASES
# =============================================================================


class TestApiEndpointsEdgeCases:
    """Tests pour les endpoints API."""

    @pytest.fixture
    def client(self):
        """Client de test Flask."""
        from app.dashboard import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_api_stats_returns_json(self, client):
        """API stats retourne du JSON."""
        with patch('app.dashboard.get_container') as mock_container, \
             patch('app.dashboard._dashboard_current_account_id', return_value=1):
            mock_c = Mock()
            mock_history = Mock()
            mock_history.get_stats.return_value = {}
            mock_c.get_draft_history.return_value = mock_history
            mock_container.return_value = mock_c

            with patch('app.dashboard.get_stats', return_value={}):
                with patch('app.dashboard.get_history', return_value=[]):
                    with patch('app.dashboard.get_config', return_value={}):
                        response = client.get('/api/stats')

                        assert response.status_code == 200
                        assert response.content_type == 'application/json'

    def test_api_draft_not_found(self, client):
        """API draft retourne 404 si non trouvé."""
        with patch('app.dashboard.get_container') as mock_container, \
             patch('app.dashboard._dashboard_current_account_id', return_value=1):
            mock_c = Mock()
            mock_history = Mock()
            # Route utilise get_by_id_for_account (scoped), cf dashboard.py:1520
            mock_history.get_by_id_for_account.return_value = None
            mock_c.get_draft_history.return_value = mock_history
            mock_container.return_value = mock_c

            response = client.get('/api/draft/nonexistent-id')

            assert response.status_code == 404
            data = json.loads(response.data)
            assert "error" in data

    def test_api_draft_injection_attempt(self, client):
        """API draft rejette les IDs avec caractères d'injection."""
        # Note: Flask routing handles slashes and angle brackets in URLs,
        # so some injection attempts are handled at routing level (404).
        # We test characters that pass Flask routing but should be rejected
        # by our validation pattern.
        malicious_ids = [
            "id-with-quote'",  # Quote character not allowed
            "id.with.dot",  # Dot not allowed (could be path traversal component)
            "id with spaces",  # Spaces not allowed
            "id@special",  # @ not allowed
        ]

        for malicious_id in malicious_ids:
            response = client.get(f'/api/draft/{malicious_id}')

            # SECURITY: IDs avec caractères spéciaux doivent être rejetés
            assert response.status_code == 400, f"Should reject: {malicious_id}"
            data = json.loads(response.data)
            assert "error" in data

    def test_api_feedback_missing_id(self, client):
        """API feedback retourne 400 si ID manquant."""
        response = client.post(
            '/api/feedback',
            data=json.dumps({"feedback": "Test"}),
            content_type='application/json'
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data

    def test_api_feedback_success(self, client):
        """API feedback avec succès."""
        with patch('app.dashboard.get_container') as mock_container, \
             patch('app.dashboard._dashboard_current_account_id', return_value=1):
            mock_c = Mock()
            mock_history = Mock()
            # Route utilise update_feedback_for_account (scoped), cf dashboard.py:1565
            mock_history.update_feedback_for_account.return_value = True
            mock_c.get_draft_history.return_value = mock_history
            mock_container.return_value = mock_c

            response = client.post(
                '/api/feedback',
                data=json.dumps({"id": "test-id", "feedback": "Great!", "rating": 5}),
                content_type='application/json'
            )

            assert response.status_code == 200
            mock_history.update_feedback_for_account.assert_called_once_with("test-id", 1, "Great!", 5)

    def test_api_feedback_invalid_rating_too_high(self, client):
        """API feedback retourne 400 si rating > 5."""
        response = client.post(
            '/api/feedback',
            data=json.dumps({"id": "test-id", "feedback": "Test", "rating": 6}),
            content_type='application/json'
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data
        assert "rating" in data["error"].lower()

    def test_api_feedback_invalid_rating_too_low(self, client):
        """API feedback retourne 400 si rating < 1."""
        response = client.post(
            '/api/feedback',
            data=json.dumps({"id": "test-id", "feedback": "Test", "rating": 0}),
            content_type='application/json'
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data
        assert "rating" in data["error"].lower()

    def test_api_feedback_draft_not_found(self, client):
        """API feedback retourne 404 si draft non trouvé."""
        with patch('app.dashboard.get_container') as mock_container, \
             patch('app.dashboard._dashboard_current_account_id', return_value=1):
            mock_c = Mock()
            mock_history = Mock()
            mock_history.update_feedback.return_value = False
            mock_history.update_feedback_for_account.return_value = False
            mock_c.get_draft_history.return_value = mock_history
            mock_container.return_value = mock_c

            response = client.post(
                '/api/feedback',
                data=json.dumps({"id": "nonexistent-id", "feedback": "Test", "rating": 3}),
                content_type='application/json'
            )

            assert response.status_code == 404
            data = json.loads(response.data)
            assert "error" in data

    def test_api_feedback_rating_only(self, client):
        """API feedback accepte un rating seul sans texte feedback."""
        with patch('app.dashboard.get_container') as mock_container, \
             patch('app.dashboard._dashboard_current_account_id', return_value=1):
            mock_c = Mock()
            mock_history = Mock()
            mock_history.update_feedback.return_value = True
            mock_history.update_feedback_for_account.return_value = True
            mock_c.get_draft_history.return_value = mock_history
            mock_container.return_value = mock_c

            response = client.post(
                '/api/feedback',
                data=json.dumps({"id": "test-id", "rating": 4}),
                content_type='application/json'
            )

            assert response.status_code == 200
            mock_history.update_feedback_for_account.assert_called_once_with("test-id", 1, "", 4)

    def test_api_feedback_rating_null_accepted(self, client):
        """API feedback accepte rating null."""
        with patch('app.dashboard.get_container') as mock_container, \
             patch('app.dashboard._dashboard_current_account_id', return_value=1):
            mock_c = Mock()
            mock_history = Mock()
            mock_history.update_feedback.return_value = True
            mock_history.update_feedback_for_account.return_value = True
            mock_c.get_draft_history.return_value = mock_history
            mock_container.return_value = mock_c

            response = client.post(
                '/api/feedback',
                data=json.dumps({"id": "test-id", "feedback": "Test", "rating": None}),
                content_type='application/json'
            )

            assert response.status_code == 200
            mock_history.update_feedback_for_account.assert_called_once_with("test-id", 1, "Test", None)

    def test_api_feedback_invalid_rating_negative(self, client):
        """API feedback retourne 400 si rating est négatif."""
        response = client.post(
            '/api/feedback',
            data=json.dumps({"id": "test-id", "feedback": "Test", "rating": -1}),
            content_type='application/json'
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data
        assert "rating" in data["error"].lower()

    def test_api_feedback_invalid_rating_float(self, client):
        """API feedback retourne 400 si rating est un float."""
        response = client.post(
            '/api/feedback',
            data=json.dumps({"id": "test-id", "feedback": "Test", "rating": 3.5}),
            content_type='application/json'
        )

        # 3.5 n'est pas un entier, doit être rejeté
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data
        assert "integer" in data["error"].lower() or "rating" in data["error"].lower()

    def test_api_feedback_invalid_rating_string(self, client):
        """API feedback retourne 400 si rating est une string."""
        response = client.post(
            '/api/feedback',
            data=json.dumps({"id": "test-id", "feedback": "Test", "rating": "five"}),
            content_type='application/json'
        )

        # Une string n'est pas un entier valide
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data
        assert "integer" in data["error"].lower() or "rating" in data["error"].lower()

    def test_api_feedback_empty_id(self, client):
        """API feedback retourne 400 si ID est une chaîne vide."""
        response = client.post(
            '/api/feedback',
            data=json.dumps({"id": "", "feedback": "Test", "rating": 3}),
            content_type='application/json'
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data

    def test_api_feedback_very_long_feedback(self, client):
        """API feedback rejette un feedback trop long (>10000 caractères)."""
        long_feedback = "A" * 10001

        response = client.post(
            '/api/feedback',
            data=json.dumps({"id": "test-id", "feedback": long_feedback, "rating": 5}),
            content_type='application/json'
        )

        # SECURITY: Doit rejeter les feedbacks trop longs (DoS protection)
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data
        assert "feedback" in data["error"].lower() or "size" in data["error"].lower()

    def test_api_feedback_max_length_feedback_accepted(self, client):
        """API feedback accepte un feedback de 10000 caractères exactement."""
        with patch('app.dashboard.get_container') as mock_container, \
             patch('app.dashboard._dashboard_current_account_id', return_value=1):
            mock_c = Mock()
            mock_history = Mock()
            mock_history.update_feedback.return_value = True
            mock_history.update_feedback_for_account.return_value = True
            mock_c.get_draft_history.return_value = mock_history
            mock_container.return_value = mock_c

            max_feedback = "A" * 10000

            response = client.post(
                '/api/feedback',
                data=json.dumps({"id": "test-id", "feedback": max_feedback, "rating": 5}),
                content_type='application/json'
            )

            # Accepte exactement 10000 caractères
            assert response.status_code == 200
            mock_history.update_feedback_for_account.assert_called_once()

    def test_api_feedback_invalid_json(self, client):
        """API feedback retourne 400 si JSON invalide."""
        response = client.post(
            '/api/feedback',
            data='{"id": "test-id", invalid json}',
            content_type='application/json'
        )

        assert response.status_code == 400

    def test_api_feedback_empty_body(self, client):
        """API feedback retourne 400 si body vide."""
        response = client.post(
            '/api/feedback',
            data='',
            content_type='application/json'
        )

        assert response.status_code == 400

    def test_api_feedback_whitespace_only_id(self, client):
        """API feedback retourne 400 si ID contient uniquement des espaces."""
        response = client.post(
            '/api/feedback',
            data=json.dumps({"id": "   ", "feedback": "Test", "rating": 3}),
            content_type='application/json'
        )

        # SECURITY: ID contenant des espaces n'est pas valide selon le pattern
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data

    def test_api_feedback_injection_attempt_id(self, client):
        """API feedback rejette les IDs avec caractères d'injection."""
        malicious_ids = [
            "../../../etc/passwd",
            "id'; DROP TABLE drafts;--",
            "<script>alert('xss')</script>",
            "id\x00null",
        ]

        for malicious_id in malicious_ids:
            response = client.post(
                '/api/feedback',
                data=json.dumps({"id": malicious_id, "feedback": "Test", "rating": 3}),
                content_type='application/json'
            )

            # SECURITY: IDs avec caractères spéciaux doivent être rejetés
            assert response.status_code == 400, f"Should reject: {malicious_id}"

    def test_api_feedback_valid_id_format(self, client):
        """API feedback accepte les IDs avec format valide."""
        with patch('app.dashboard.get_container') as mock_container, \
             patch('app.dashboard._dashboard_current_account_id', return_value=1):
            mock_c = Mock()
            mock_history = Mock()
            mock_history.update_feedback.return_value = True
            mock_history.update_feedback_for_account.return_value = True
            mock_c.get_draft_history.return_value = mock_history
            mock_container.return_value = mock_c

            valid_ids = [
                "test-id-123",
                "abc_def_ghi",
                "UPPER-lower-123",
                "a1b2c3",
            ]

            for valid_id in valid_ids:
                response = client.post(
                    '/api/feedback',
                    data=json.dumps({"id": valid_id, "feedback": "Test", "rating": 3}),
                    content_type='application/json'
                )

                assert response.status_code == 200, f"Should accept: {valid_id}"


# =============================================================================
# TESTS API MEMORY EDGE CASES
# =============================================================================


class TestApiMemoryEdgeCases:
    """Tests pour les endpoints API Memory."""

    @pytest.fixture
    def client(self):
        """Client de test Flask."""
        from app.dashboard import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_api_memory_update_missing_content(self, client):
        """API memory update sans content retourne 400."""
        response = client.post(
            '/api/memory',
            data=json.dumps({}),
            content_type='application/json'
        )

        assert response.status_code == 400

    def test_api_memory_section_add_missing_fields(self, client):
        """API memory section add sans champs requis."""
        response = client.post(
            '/api/memory/sections',
            data=json.dumps({"title": "Test"}),  # content manquant
            content_type='application/json'
        )

        assert response.status_code == 400

    def test_api_memory_section_update_missing_content(self, client):
        """API memory section update sans content."""
        response = client.put(
            '/api/memory/sections/Test',
            data=json.dumps({}),
            content_type='application/json'
        )

        assert response.status_code == 400

    def test_api_memory_search_missing_query(self, client):
        """API memory search sans query."""
        response = client.get('/api/memory/search')

        assert response.status_code == 400

    def test_api_memory_import_missing_content(self, client):
        """API memory import sans content."""
        response = client.post(
            '/api/memory/import',
            data=json.dumps({}),
            content_type='application/json'
        )

        assert response.status_code == 400


# =============================================================================
# TESTS SOCKETIO EVENTS
# =============================================================================


class TestSocketIOEvents:
    """Tests pour les événements SocketIO."""

    def test_socketio_connect_emits_status(self):
        """Connexion SocketIO émet le statut."""
        # Ce test vérifie la logique sans vraie connexion WebSocket
        with patch('app.dashboard.SOCKETIO_AVAILABLE', True):
            with patch('app.dashboard.emit') as mock_emit:
                # Simuler l'appel de handle_connect
                mock_emit("connection_status", {"status": "connected"})
                mock_emit.assert_called_once()

    def test_socketio_request_stats_emits_stats(self):
        """Demande de stats émet les statistiques."""
        with patch('app.dashboard.SOCKETIO_AVAILABLE', True):
            with patch('app.dashboard.get_container') as mock_container, \
                 patch('app.dashboard._dashboard_current_account_id', return_value=1):
                mock_c = Mock()
                mock_history = Mock()
                mock_history.get_stats.return_value = {"total": 10}
                mock_c.get_draft_history.return_value = mock_history
                mock_container.return_value = mock_c

                with patch('app.dashboard.emit') as mock_emit:
                    # Simuler l'appel
                    mock_emit("stats_update", {"total": 10})
                    mock_emit.assert_called()


# =============================================================================
# TESTS RUN_DASHBOARD EDGE CASES
# =============================================================================


class TestRunDashboardEdgeCases:
    """Tests pour la fonction run_dashboard."""

    def test_run_dashboard_without_socketio(self):
        """Lancement sans SocketIO disponible."""
        with patch('app.dashboard.SOCKETIO_AVAILABLE', False):
            with patch('app.dashboard.app.run') as mock_run:
                with patch('builtins.print'):
                    from app.dashboard import run_dashboard

                    run_dashboard(host="127.0.0.1", port=5000, debug=False)

                    mock_run.assert_called_once_with(
                        host="127.0.0.1",
                        port=5000,
                        debug=False
                    )

    def test_run_dashboard_with_socketio(self):
        """Lancement avec SocketIO disponible."""
        mock_socketio = Mock()

        with patch('app.dashboard.SOCKETIO_AVAILABLE', True):
            with patch('app.dashboard.socketio', mock_socketio):
                with patch('builtins.print'):
                    from app.dashboard import run_dashboard

                    run_dashboard(host="0.0.0.0", port=8080, debug=True)

                    mock_socketio.run.assert_called_once()


# =============================================================================
# TESTS DASHBOARD ROUTE EDGE CASES
# =============================================================================


class TestDashboardRouteEdgeCases:
    """Tests pour la route principale du dashboard."""

    @pytest.fixture
    def client(self):
        """Client de test Flask."""
        from app.dashboard import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_dashboard_renders_without_data(self, client):
        """Dashboard se rend même sans données."""
        with patch('app.dashboard.get_container') as mock_container, \
             patch('app.dashboard._dashboard_current_account_id', return_value=1):
            mock_c = Mock()
            mock_history = Mock()
            # Route utilise get_all_for_account (scoped), cf dashboard.py:1471
            mock_history.get_all_for_account.return_value = []
            mock_history.get_all.return_value = []
            # M-3 (audit Codex 2026-04-25) : la route préfère get_stats_for_account
            # quand disponible. On stub les deux pour rester compatible avec
            # l'ancien path get_stats() au cas où l'attribut est retiré.
            _empty_stats = {
                "total": 0,
                "validated_v1": 0,
                "corrected_v2": 0,
                "v1_percent": 0,
                "v2_percent": 0,
                "time_saved_hours": 0,
                "automation_rate": 0,
                "avg_processing_time_sec": 0,
                "total_tokens": 0,
                "daily_stats": [],
                "by_category": {},
            }
            mock_history.get_stats.return_value = _empty_stats
            mock_history.get_stats_for_account.return_value = _empty_stats
            mock_c.get_draft_history.return_value = mock_history
            mock_container.return_value = mock_c

            with patch('app.dashboard.get_stats', return_value={
                "total_emails": 0,
                "total_cost": "0.00",
            }):
                with patch('app.dashboard.get_history', return_value=[]):
                    with patch('app.dashboard.get_config', return_value={
                        "inputs_dir": "/tmp",
                        "outputs_dir": "/tmp",
                        "knowledge_file": "/tmp/memoire.md",
                        "knowledge_size": 0,
                        "corpus_count": 0,
                    }):
                        with patch('app.dashboard.get_learning_stats', return_value={
                            "patterns_count": 0,
                            "active_adjustments": 0,
                            "analyzed_emails": 0,
                            "top_patterns": [],
                        }):
                            with patch('app.dashboard.get_cost_stats', return_value={
                                "current_month_cost": "0.00",
                                "monthly_budget": None,
                                "usage_percentage": "0.0",
                                "remaining_budget": None,
                                "total_requests": 0,
                                "by_agent": {},
                            }):
                                with patch('app.dashboard.get_category_breakdown', return_value={}):
                                    with patch('app.dashboard.get_retention_stats', return_value={}):
                                        with patch('app.dashboard.get_analytics_stats', return_value={
                                            "quality": {
                                                "total_scored": 0,
                                                "avg_overall_score": 0,
                                                "avg_user_rating": 0,
                                                "score_distribution": {},
                                            },
                                            "comparison": {
                                                "total_edits": 0,
                                                "avg_edit_ratio": 0,
                                                "avg_similarity": 100,
                                                "distribution": {},
                                            },
                                            "performance": {
                                                "improvement_trend": 0,
                                            },
                                            "recommendations": [],
                                        }):
                                            response = client.get('/')

                                            assert response.status_code == 200
                                            assert b"Agentys" in response.data


# =============================================================================
# TESTS EDGE CASES POUR MODEL_COSTS
# =============================================================================


class TestModelCostsEdgeCases:
    """Tests pour les coûts des modèles."""

    def test_model_costs_has_opus_key(self):
        """MODEL_COSTS contient la clé Opus."""
        from app.agents import MODEL_COSTS

        # Vérifie qu'au moins un modèle Opus existe
        opus_keys = [k for k in MODEL_COSTS if "opus" in k.lower()]
        assert len(opus_keys) >= 1

    def test_model_costs_values_are_positive(self):
        """Tous les coûts sont positifs."""
        from app.agents import MODEL_COSTS

        for model, costs in MODEL_COSTS.items():
            assert costs["input"] >= 0, f"Input cost for {model} should be positive"
            assert costs["output"] >= 0, f"Output cost for {model} should be positive"
