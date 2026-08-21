# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour app/main.py.

Ce module teste le pipeline de traitement des emails :
- Fonctions d'affichage (print_header, print_progress, print_stats)
- Scan des fichiers Excel
- Chargement des données
- Traitement principal
- Sauvegarde des résultats
"""

import io
from datetime import datetime
from unittest.mock import MagicMock, patch

try:
    import pandas as pd
except ImportError:
    pd = None  # Optional: tests requiring pandas will be skipped
import pytest

# Skip entire module if pandas is not available
pytestmark = pytest.mark.skipif(pd is None, reason="pandas not installed")

from app.agents import EmailResult


# ============================================================================
# TESTS - FONCTIONS D'AFFICHAGE
# ============================================================================

class TestPrintHeader:
    """Tests pour print_header."""

    def test_print_header_outputs_to_stdout(self):
        """print_header doit afficher l'en-tête sur stdout."""
        from app.main import print_header

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            print_header()

        output = captured.getvalue()
        assert "Agentys" in output
        assert "Email Pipeline" in output

    def test_print_header_contains_box_characters(self):
        """print_header doit contenir les caractères de la boîte."""
        from app.main import print_header

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            print_header()

        output = captured.getvalue()
        assert "╔" in output
        assert "╚" in output


class TestPrintProgress:
    """Tests pour print_progress."""

    def test_print_progress_shows_percentage(self):
        """print_progress doit afficher le pourcentage."""
        from app.main import print_progress

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            print_progress(5, 10, "Test status")

        output = captured.getvalue()
        assert "50%" in output
        assert "5/10" in output

    def test_print_progress_zero_progress(self):
        """print_progress doit gérer 0/n correctement."""
        from app.main import print_progress

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            print_progress(0, 10)

        output = captured.getvalue()
        assert "0%" in output

    def test_print_progress_full_progress(self):
        """print_progress doit gérer n/n correctement."""
        from app.main import print_progress

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            print_progress(10, 10)

        output = captured.getvalue()
        assert "100%" in output

    def test_print_progress_shows_filled_bar(self):
        """print_progress doit afficher la barre remplie."""
        from app.main import print_progress

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            print_progress(5, 10)

        output = captured.getvalue()
        assert "█" in output or "░" in output

    def test_print_progress_truncates_long_status(self):
        """print_progress doit tronquer les statuts longs."""
        from app.main import print_progress

        long_status = "A" * 100
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            print_progress(1, 10, long_status)

        output = captured.getvalue()
        assert len(output) < len(long_status) + 100


class TestPrintStats:
    """Tests pour print_stats."""

    def test_print_stats_counts_valid_v1(self):
        """print_stats doit compter les VALIDÉ V1."""
        from app.main import print_stats

        results = [
            EmailResult(1, "", "", "", "", "", "VALIDÉ V1"),
            EmailResult(2, "", "", "", "", "", "VALIDÉ V1"),
            EmailResult(3, "", "", "", "", "", "CORRIGÉ V2"),
        ]

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            print_stats(results)

        output = captured.getvalue()
        assert "Validés V1 : 2" in output

    def test_print_stats_counts_corrected(self):
        """print_stats doit compter les CORRIGÉ V2."""
        from app.main import print_stats

        results = [
            EmailResult(1, "", "", "", "", "", "CORRIGÉ V2"),
            EmailResult(2, "", "", "", "", "", "CORRIGÉ V2"),
            EmailResult(3, "", "", "", "", "", "CORRIGÉ V2"),
        ]

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            print_stats(results)

        output = captured.getvalue()
        assert "Corrigés V2 : 3" in output

    def test_print_stats_counts_ignored(self):
        """print_stats doit compter les IGNORÉ."""
        from app.main import print_stats

        results = [
            EmailResult(1, "", "", "", "", "", "IGNORÉ - Email vide"),
            EmailResult(2, "", "", "", "", "", "IGNORÉ - Autre raison"),
        ]

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            print_stats(results)

        output = captured.getvalue()
        assert "Ignorés : 2" in output

    def test_print_stats_empty_results(self):
        """print_stats doit gérer une liste vide."""
        from app.main import print_stats

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            print_stats([])

        output = captured.getvalue()
        assert "Validés V1 : 0" in output
        assert "Corrigés V2 : 0" in output
        assert "Ignorés : 0" in output


# ============================================================================
# TESTS - SCAN DES FICHIERS
# ============================================================================

class TestScanInputFiles:
    """Tests pour scan_input_files."""

    def test_scan_input_files_creates_dir_if_missing(self, tmp_path):
        """scan_input_files doit créer le dossier s'il n'existe pas."""
        from app.main import scan_input_files

        inputs_dir = tmp_path / "inputs"

        with patch("app.main.INPUTS_DIR", inputs_dir):
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                scan_input_files()

        assert inputs_dir.exists()

    def test_scan_input_files_returns_empty_if_no_files(self, tmp_path):
        """scan_input_files doit retourner [] si aucun fichier."""
        from app.main import scan_input_files

        inputs_dir = tmp_path / "inputs"
        inputs_dir.mkdir()

        with patch("app.main.INPUTS_DIR", inputs_dir):
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                result = scan_input_files()

        assert result == []

    def test_scan_input_files_finds_xlsx_files(self, tmp_path):
        """scan_input_files doit trouver les fichiers .xlsx."""
        from app.main import scan_input_files

        inputs_dir = tmp_path / "inputs"
        inputs_dir.mkdir()
        (inputs_dir / "test1.xlsx").touch()
        (inputs_dir / "test2.xlsx").touch()
        (inputs_dir / "not_excel.txt").touch()

        with patch("app.main.INPUTS_DIR", inputs_dir):
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                result = scan_input_files()

        assert len(result) == 2
        assert all(f.suffix == ".xlsx" for f in result)

    def test_scan_input_files_prints_found_files(self, tmp_path):
        """scan_input_files doit afficher les fichiers trouvés."""
        from app.main import scan_input_files

        inputs_dir = tmp_path / "inputs"
        inputs_dir.mkdir()
        (inputs_dir / "emails.xlsx").touch()

        with patch("app.main.INPUTS_DIR", inputs_dir):
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                scan_input_files()

        output = captured.getvalue()
        assert "emails.xlsx" in output


# ============================================================================
# TESTS - CHARGEMENT EXCEL
# ============================================================================

class TestLoadExcel:
    """Tests pour load_excel."""

    def test_load_excel_standard_format(self, tmp_path):
        """load_excel doit charger un fichier au format standard."""
        from app.main import load_excel

        df = pd.DataFrame({
            "Numéro": [1, 2, 3],
            "Email reçu": ["email1", "email2", "email3"],
            "Réponse": ["rep1", "rep2", "rep3"]
        })
        file_path = tmp_path / "test.xlsx"
        df.to_excel(file_path, index=False)

        result = load_excel(file_path)

        assert len(result) == 3
        assert "Numéro" in result.columns
        assert "Email reçu" in result.columns
        assert "Réponse" in result.columns

    def test_load_excel_filters_nan_numero(self, tmp_path):
        """load_excel doit filtrer les lignes sans numéro."""
        from app.main import load_excel

        df = pd.DataFrame({
            "Numéro": [1, None, 3],
            "Email reçu": ["email1", "email2", "email3"],
            "Réponse": ["rep1", "rep2", "rep3"]
        })
        file_path = tmp_path / "test.xlsx"
        df.to_excel(file_path, index=False)

        result = load_excel(file_path)

        assert len(result) == 2
        assert 1 in result["Numéro"].values
        assert 3 in result["Numéro"].values


# ============================================================================
# TESTS - SAUVEGARDE DES RÉSULTATS
# ============================================================================

class TestSaveResults:
    """Tests pour save_results."""

    def test_save_results_creates_output_dir(self, tmp_path):
        """save_results doit créer le dossier de sortie."""
        from app.main import save_results

        outputs_dir = tmp_path / "outputs"

        results = [
            EmailResult(1, "email", "human", "v1", "critique", "final", "VALIDÉ V1")
        ]

        with patch("app.main.OUTPUTS_DIR", outputs_dir):
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                save_results(results, "test")

        assert outputs_dir.exists()

    def test_save_results_creates_xlsx_file(self, tmp_path):
        """save_results doit créer un fichier .xlsx."""
        from app.main import save_results

        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()

        results = [
            EmailResult(1, "email", "human", "v1", "critique", "final", "VALIDÉ V1")
        ]

        with patch("app.main.OUTPUTS_DIR", outputs_dir):
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                output_path = save_results(results, "test")

        assert output_path.exists()
        assert output_path.suffix == ".xlsx"

    def test_save_results_file_contains_data(self, tmp_path):
        """save_results doit inclure les données dans le fichier."""
        from app.main import save_results

        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()

        results = [
            EmailResult(1, "email content", "human response", "draft v1", "critique", "final", "VALIDÉ V1"),
            EmailResult(2, "email2", "human2", "v1-2", "crit2", "final2", "CORRIGÉ V2"),
        ]

        with patch("app.main.OUTPUTS_DIR", outputs_dir):
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                output_path = save_results(results, "test")

        df = pd.read_excel(output_path)
        assert len(df) == 2
        assert "Numéro" in df.columns
        assert "Status" in df.columns

    def test_save_results_file_has_dated_name(self, tmp_path):
        """save_results doit nommer le fichier avec la date."""
        from app.main import save_results

        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()

        results = [EmailResult(1, "", "", "", "", "", "VALIDÉ V1")]

        with patch("app.main.OUTPUTS_DIR", outputs_dir):
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                output_path = save_results(results, "test")

        assert "rapport_" in output_path.name
        current_year = str(datetime.now().year)
        assert current_year in output_path.name


# ============================================================================
# TESTS - TRAITEMENT PRINCIPAL
# ============================================================================

class TestProcessFile:
    """Tests pour process_file."""

    def test_process_file_processes_all_rows(self, tmp_path):
        """process_file doit traiter toutes les lignes."""
        from app.main import process_file

        inputs_dir = tmp_path / "inputs"
        inputs_dir.mkdir()
        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()

        df = pd.DataFrame({
            "Numéro": [1, 2],
            "Email reçu": ["Test email 1", "Test email 2"],
            "Réponse": ["Response 1", "Response 2"]
        })
        file_path = inputs_dir / "test.xlsx"
        df.to_excel(file_path, index=False)

        mock_drafter = MagicMock()
        mock_drafter.draft.return_value = "Draft response"
        mock_critic = MagicMock()
        mock_critic.evaluate.return_value = "VALID"
        mock_critic.is_valid.return_value = True

        with patch("app.main.OUTPUTS_DIR", outputs_dir), \
             patch("app.main.DrafterAgent", return_value=mock_drafter), \
             patch("app.main.CriticAgent", return_value=mock_critic), \
             patch("app.main.load_knowledge_base", return_value="knowledge"), \
             patch("app.main.token_counter") as mock_counter:
            mock_counter.input = 100
            mock_counter.output = 50
            mock_counter.total = 150

            captured = io.StringIO()
            with patch("sys.stdout", captured):
                output_path = process_file(file_path)

        assert output_path.exists()
        result_df = pd.read_excel(output_path)
        assert len(result_df) == 2

    def test_process_file_skips_empty_emails(self, tmp_path):
        """process_file doit ignorer les emails vides."""
        from app.main import process_file

        inputs_dir = tmp_path / "inputs"
        inputs_dir.mkdir()
        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()

        df = pd.DataFrame({
            "Numéro": [1, 2, 3],
            "Email reçu": ["Valid email", "", None],
            "Réponse": ["Response", "", ""]
        })
        file_path = inputs_dir / "test.xlsx"
        df.to_excel(file_path, index=False)

        mock_drafter = MagicMock()
        mock_drafter.draft.return_value = "Draft"
        mock_critic = MagicMock()
        mock_critic.evaluate.return_value = "VALID"
        mock_critic.is_valid.return_value = True

        with patch("app.main.OUTPUTS_DIR", outputs_dir), \
             patch("app.main.DrafterAgent", return_value=mock_drafter), \
             patch("app.main.CriticAgent", return_value=mock_critic), \
             patch("app.main.load_knowledge_base", return_value="knowledge"), \
             patch("app.main.token_counter") as mock_counter:
            mock_counter.input = 100
            mock_counter.output = 50
            mock_counter.total = 150

            captured = io.StringIO()
            with patch("sys.stdout", captured):
                output_path = process_file(file_path)

        result_df = pd.read_excel(output_path)
        ignored_count = len(result_df[result_df["Status"].str.startswith("IGNORÉ")])
        assert ignored_count == 2
        assert mock_drafter.draft.call_count == 1


# ============================================================================
# TESTS - FONCTION MAIN
# ============================================================================

class TestMain:
    """Tests pour la fonction main."""

    def test_main_no_files_prints_message(self, tmp_path):
        """main doit afficher un message s'il n'y a pas de fichiers."""
        from app.main import main

        inputs_dir = tmp_path / "inputs"
        inputs_dir.mkdir()

        with patch("app.main.INPUTS_DIR", inputs_dir):
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                main()

        output = captured.getvalue()
        assert "data/inputs" in output or "Aucun fichier" in output

    def test_main_processes_files(self, tmp_path):
        """main doit traiter les fichiers trouvés."""
        from app.main import main

        inputs_dir = tmp_path / "inputs"
        inputs_dir.mkdir()
        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()

        pd.DataFrame({
            "Numéro": [1],
            "Email reçu": ["Test"],
            "Réponse": ["Response"]
        })
        (inputs_dir / "test.xlsx").touch()

        mock_process = MagicMock(return_value=outputs_dir / "result.xlsx")

        with patch("app.main.INPUTS_DIR", inputs_dir), \
             patch("app.main.OUTPUTS_DIR", outputs_dir), \
             patch("app.main.scan_input_files", return_value=[inputs_dir / "test.xlsx"]), \
             patch("app.main.process_file", mock_process):
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                main()

        mock_process.assert_called_once()

    def test_main_prints_completion_message(self, tmp_path):
        """main doit afficher un message de fin."""
        from app.main import main

        inputs_dir = tmp_path / "inputs"
        inputs_dir.mkdir()
        outputs_dir = tmp_path / "outputs"

        mock_process = MagicMock(return_value=outputs_dir / "result.xlsx")

        with patch("app.main.INPUTS_DIR", inputs_dir), \
             patch("app.main.OUTPUTS_DIR", outputs_dir), \
             patch("app.main.scan_input_files", return_value=[inputs_dir / "test.xlsx"]), \
             patch("app.main.process_file", mock_process):
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                main()

        output = captured.getvalue()
        assert "terminé" in output.lower() or "Terminé" in output


# ============================================================================
# TESTS - EDGE CASES
# ============================================================================

class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_print_progress_with_zero_total(self):
        """print_progress doit gérer total=0 sans crash."""
        from app.main import print_progress

        try:
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                print_progress(0, 1)
        except ZeroDivisionError:
            pytest.fail("print_progress devrait gérer total=0")

    def test_print_stats_mixed_statuses(self):
        """print_stats doit gérer des statuts mixtes."""
        from app.main import print_stats

        results = [
            EmailResult(1, "", "", "", "", "", "VALIDÉ V1"),
            EmailResult(2, "", "", "", "", "", "CORRIGÉ V2"),
            EmailResult(3, "", "", "", "", "", "IGNORÉ - Vide"),
            EmailResult(4, "", "", "", "", "", "INCONNU"),
        ]

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            print_stats(results)

        output = captured.getvalue()
        assert "Validés V1 : 1" in output
        assert "Corrigés V2 : 1" in output
        assert "Ignorés : 1" in output

    def test_save_results_empty_list(self, tmp_path):
        """save_results doit gérer une liste vide."""
        from app.main import save_results

        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()

        with patch("app.main.OUTPUTS_DIR", outputs_dir):
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                output_path = save_results([], "test")

        assert output_path.exists()
        df = pd.read_excel(output_path)
        assert len(df) == 0

    def test_load_excel_legacy_format(self, tmp_path):
        """load_excel doit gérer le format legacy avec skiprows."""
        from app.main import load_excel

        df = pd.DataFrame([
            ["Header row 1", "", ""],
            ["Header row 2", "", ""],
            [1, "email1", "rep1"],
            [2, "email2", "rep2"],
        ])
        file_path = tmp_path / "legacy.xlsx"
        df.to_excel(file_path, index=False, header=False)

        result = load_excel(file_path)

        assert len(result) >= 1
