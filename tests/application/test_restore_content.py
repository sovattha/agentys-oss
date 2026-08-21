# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le use case RestoreContentUseCase.

Couvre:
- Restauration avec mapping valide
- Gestion du token vide
- Remplacement multiple de marqueurs
"""

from unittest.mock import MagicMock
from app.application.restore_content import RestoreContentUseCase


class TestRestoreContentUseCase:
    """Tests pour RestoreContentUseCase.execute()."""

    def _make_use_case(self, mapping: dict) -> RestoreContentUseCase:
        """Crée un use case avec un mock EncryptionPort."""
        mock_encryption = MagicMock()
        mock_encryption.decrypt_mapping.return_value = mapping
        return RestoreContentUseCase(encryption=mock_encryption)

    def test_restore_single_marker(self):
        """Test restauration d'un seul marqueur."""
        uc = self._make_use_case({"[NOM-1]": "Jean Dupont"})
        result = uc.execute("Bonjour [NOM-1], comment allez-vous ?", "encrypted-token")
        assert result == "Bonjour Jean Dupont, comment allez-vous ?"

    def test_restore_multiple_markers(self):
        """Test restauration de plusieurs marqueurs."""
        mapping = {
            "[NOM-1]": "Marie",
            "[EMAIL-1]": "marie@example.com",
            "[TEL-1]": "01 23 45 67 89",
        }
        uc = self._make_use_case(mapping)
        text = "Contact: [NOM-1] ([EMAIL-1]), tél: [TEL-1]"
        result = uc.execute(text, "encrypted-token")
        assert result == "Contact: Marie (marie@example.com), tél: 01 23 45 67 89"

    def test_restore_empty_token_returns_original(self):
        """Test que token vide retourne le contenu tel quel."""
        uc = self._make_use_case({})
        result = uc.execute("Texte original", "")
        assert result == "Texte original"
        # Le decrypt_mapping ne doit pas être appelé
        uc.encryption.decrypt_mapping.assert_not_called()

    def test_restore_no_markers_in_text(self):
        """Test restauration quand le texte ne contient pas les marqueurs."""
        uc = self._make_use_case({"[NOM-1]": "Jean"})
        result = uc.execute("Texte sans marqueur", "encrypted-token")
        assert result == "Texte sans marqueur"

    def test_restore_repeated_marker(self):
        """Test que le même marqueur est remplacé à chaque occurrence."""
        uc = self._make_use_case({"[NOM-1]": "Alice"})
        result = uc.execute("[NOM-1] a dit à [NOM-1]", "encrypted-token")
        assert result == "Alice a dit à Alice"

    def test_restore_preserves_unmatched_markers(self):
        """Test que les marqueurs non trouvés dans le mapping restent intacts."""
        uc = self._make_use_case({"[NOM-1]": "Jean"})
        result = uc.execute("[NOM-1] et [NOM-2]", "encrypted-token")
        assert result == "Jean et [NOM-2]"

    def test_restore_empty_text(self):
        """Test avec texte vide."""
        uc = self._make_use_case({"[NOM-1]": "Jean"})
        result = uc.execute("", "encrypted-token")
        assert result == ""

    def test_restore_calls_decrypt_mapping(self):
        """Test que decrypt_mapping est appelé avec le bon token."""
        uc = self._make_use_case({})
        uc.execute("text", "my-token")
        uc.encryption.decrypt_mapping.assert_called_once_with("my-token")
