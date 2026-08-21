# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le module voice.

pytest tests/test_voice.py -v
"""

import pytest
from unittest.mock import Mock, patch
import sys
from pathlib import Path

# Ajouter le répertoire racine
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.voice import (
    COMMANDS,
    CommandParser,
    VoiceInterface,
)


# ============================================================================
# TESTS COMMANDS
# ============================================================================

class TestCommands:
    """Tests pour les commandes définies."""

    def test_all_commands_have_required_fields(self):
        """Toutes les commandes ont les champs requis."""
        for cmd_name, cmd_info in COMMANDS.items():
            assert "patterns" in cmd_info, f"{cmd_name} manque 'patterns'"
            assert "action" in cmd_info, f"{cmd_name} manque 'action'"
            assert "description" in cmd_info, f"{cmd_name} manque 'description'"

    def test_all_patterns_are_valid_regex(self):
        """Tous les patterns sont des regex valides."""
        import re
        for cmd_name, cmd_info in COMMANDS.items():
            for pattern in cmd_info["patterns"]:
                try:
                    re.compile(pattern)
                except re.error as e:
                    pytest.fail(f"{cmd_name}: pattern invalide '{pattern}': {e}")

    def test_expected_commands_exist(self):
        """Les commandes attendues existent."""
        expected = ["repondre", "marquer_lu", "ignorer", "priorite", "stats", "aide"]
        for cmd in expected:
            assert cmd in COMMANDS, f"Commande manquante: {cmd}"


# ============================================================================
# TESTS COMMAND PARSER
# ============================================================================

class TestCommandParser:
    """Tests pour CommandParser."""

    def setup_method(self):
        """Setup pour chaque test."""
        self.parser = CommandParser()

    def test_parse_help_fr(self):
        """Parse commande aide en français."""
        action, arg = self.parser.parse("aide")
        assert action == "help"

    def test_parse_help_en(self):
        """Parse commande help en anglais."""
        action, arg = self.parser.parse("help")
        assert action == "help"

    def test_parse_stats_fr(self):
        """Parse commande stats en français."""
        action, arg = self.parser.parse("montre les stats")
        assert action == "show_stats"

    def test_parse_stats_en(self):
        """Parse commande stats en anglais."""
        action, arg = self.parser.parse("show me the statistics")
        assert action == "show_stats"

    def test_parse_reply_with_name(self):
        """Parse commande répondre avec nom."""
        action, arg = self.parser.parse("réponds à l'email de John")
        assert action == "reply_to"
        assert arg is not None
        assert "john" in arg.lower()

    def test_parse_reply_en(self):
        """Parse commande reply en anglais."""
        action, arg = self.parser.parse("write a reply to Alice")
        assert action == "reply_to"
        assert "alice" in arg.lower()

    def test_parse_mark_read_fr(self):
        """Parse commande marquer lu en français."""
        action, arg = self.parser.parse("marquer comme lu")
        assert action == "mark_read"

    def test_parse_mark_read_en(self):
        """Parse commande mark read en anglais."""
        action, arg = self.parser.parse("mark as read")
        assert action == "mark_read"

    def test_parse_skip_fr(self):
        """Parse commande ignorer en français."""
        action, arg = self.parser.parse("ignore cet email")
        assert action == "skip"

    def test_parse_skip_en(self):
        """Parse commande skip en anglais."""
        action, arg = self.parser.parse("skip this email")
        assert action == "skip"

    def test_parse_priority_fr(self):
        """Parse commande priorité en français."""
        action, arg = self.parser.parse("montre les emails urgents")
        assert action == "show_priority"

    def test_parse_priority_en(self):
        """Parse commande priority en anglais."""
        action, arg = self.parser.parse("show urgent emails")
        assert action == "show_priority"

    def test_parse_refresh(self):
        """Parse commande refresh."""
        action, arg = self.parser.parse("refresh")
        assert action == "refresh"

    def test_parse_status(self):
        """Parse commande status."""
        action, arg = self.parser.parse("status")
        assert action == "status"

    def test_parse_followups(self):
        """Parse commande followups."""
        action, arg = self.parser.parse("montre les relances")
        assert action == "show_followups"

    def test_parse_unknown_command(self):
        """Parse commande inconnue."""
        action, arg = self.parser.parse("blablabla random text")
        assert action is None
        assert arg is None

    def test_parse_empty_string(self):
        """Parse chaîne vide."""
        action, arg = self.parser.parse("")
        assert action is None

    def test_get_help(self):
        """Aide retourne du contenu."""
        help_text = self.parser.get_help()
        assert "Commandes vocales" in help_text
        assert len(help_text) > 100

    def test_parse_case_insensitive(self):
        """Parsing insensible à la casse."""
        action1, _ = self.parser.parse("HELP")
        action2, _ = self.parser.parse("Help")
        action3, _ = self.parser.parse("help")
        assert action1 == action2 == action3 == "help"


# ============================================================================
# TESTS VOICE INTERFACE
# ============================================================================

class TestVoiceInterface:
    """Tests pour VoiceInterface."""

    def test_interface_creation_without_api_key(self):
        """Création sans clé API."""
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=True):
            # Recharger le module pour prendre en compte le changement
            interface = VoiceInterface()
            # Le transcriber devrait être None ou l'interface désactivée
            assert interface.parser is not None

    def test_interface_has_parser(self):
        """Interface a un parser."""
        interface = VoiceInterface()
        assert interface.parser is not None
        assert isinstance(interface.parser, CommandParser)

    def test_enabled_property(self):
        """Propriété enabled."""
        interface = VoiceInterface()
        assert isinstance(interface.enabled, bool)


# ============================================================================
# TESTS INTEGRATION
# ============================================================================

class TestVoiceIntegration:
    """Tests d'intégration pour le module voice."""

    def test_parse_and_help(self):
        """Parsing suivi d'aide."""
        parser = CommandParser()
        action, _ = parser.parse("aide")
        assert action == "help"

        help_text = parser.get_help()
        assert "Commandes" in help_text

    def test_french_english_parity(self):
        """Parité français/anglais."""
        parser = CommandParser()

        test_cases = [
            ("aide", "help", "help"),
            ("montre les stats", "show stats", "show_stats"),
            ("ignore cet email", "skip this email", "skip"),
            ("marquer lu", "mark read", "mark_read"),
        ]

        for fr_cmd, en_cmd, expected_action in test_cases:
            action_fr, _ = parser.parse(fr_cmd)
            action_en, _ = parser.parse(en_cmd)
            assert action_fr == expected_action, f"FR: {fr_cmd} -> {action_fr}"
            assert action_en == expected_action, f"EN: {en_cmd} -> {action_en}"


# ============================================================================
# TESTS VOICE CONTROLLER (depuis run_voice.py)
# ============================================================================

class TestVoiceController:
    """Tests pour VoiceController."""

    def test_stats_without_daemon(self):
        """Stats sans daemon (mock)."""
        # Import dynamique pour éviter les dépendances
        from run_voice import VoiceController

        controller = VoiceController(daemon=None)

        with patch("run_voice.draft_history") as mock_history:
            mock_history.get_stats.return_value = {
                "total": 100,
                "automation_rate": 85,
                "validated_v1": 70,
                "corrected_v2": 30,
            }

            result = controller._show_stats()

            assert "100" in result
            assert "85" in result

    def test_status_without_daemon(self):
        """Status sans daemon."""
        from run_voice import VoiceController

        controller = VoiceController(daemon=None)

        result = controller._show_status()

        assert "Statut" in result
        assert "Voice" in result

    def test_execute_help(self):
        """Exécution commande help."""
        from run_voice import VoiceController

        controller = VoiceController(daemon=None)
        result = controller.execute("help")

        assert "Commandes" in result

    def test_execute_unknown_action(self):
        """Exécution action inconnue."""
        from run_voice import VoiceController

        controller = VoiceController(daemon=None)
        result = controller.execute("unknown_action")

        assert "non reconnue" in result


# ============================================================================
# TESTS WAKE WORD LISTENER
# ============================================================================

class TestWakeWordListener:
    """Tests pour WakeWordListener."""

    def test_wake_word_listener_creation(self):
        """Test création du wake word listener."""
        from app.voice import WakeWordListener, DEFAULT_WAKE_WORDS

        listener = WakeWordListener()
        assert listener.wake_words == [w.lower() for w in DEFAULT_WAKE_WORDS]
        assert listener.is_running is False

    def test_wake_word_listener_custom_words(self):
        """Test wake words personnalisés."""
        from app.voice import WakeWordListener

        custom_words = ["Assistant", "Hey Claude"]
        listener = WakeWordListener(wake_words=custom_words)

        assert "assistant" in listener.wake_words
        assert "hey claude" in listener.wake_words

    def test_wake_word_listener_set_words(self):
        """Test modification des wake words."""
        from app.voice import WakeWordListener

        listener = WakeWordListener()
        listener.set_wake_words(["new word"])

        assert listener.wake_words == ["new word"]

    def test_wake_word_listener_callback(self):
        """Test configuration du callback."""
        from app.voice import WakeWordListener

        listener = WakeWordListener()
        callback = Mock()
        listener.set_callback(callback)

        assert listener._callback is callback

    def test_wake_word_listener_stats(self):
        """Test statistiques."""
        from app.voice import WakeWordListener

        listener = WakeWordListener()
        stats = listener.stats

        assert "detections" in stats
        assert "total_listens" in stats
        assert "running" in stats
        assert "wake_words" in stats
        assert stats["running"] is False
        assert stats["detections"] == 0

    def test_wake_word_listener_start_without_api_key(self):
        """Test démarrage sans clé API."""
        from app.voice import WakeWordListener

        # Patch VoiceTranscriber pour raise ValueError (simule pas d'API key).
        # Patch app.voice.OPENAI_API_KEY ne suffit pas : la default value
        # api_key=OPENAI_API_KEY est capturée à la création de la classe.
        with patch("app.voice.VoiceTranscriber", side_effect=ValueError("OPENAI_API_KEY non configurée")):
            listener = WakeWordListener()
            result = listener.start()
            assert result is False

    def test_wake_word_listener_stop_when_not_running(self):
        """Test arrêt quand non démarré."""
        from app.voice import WakeWordListener

        listener = WakeWordListener()
        # Ne devrait pas lever d'exception
        listener.stop()
        assert listener.is_running is False


# ============================================================================
# TESTS CONTINUOUS VOICE INTERFACE
# ============================================================================

class TestContinuousVoiceInterface:
    """Tests pour ContinuousVoiceInterface."""

    def test_continuous_interface_creation(self):
        """Test création de l'interface continue."""
        from app.voice import ContinuousVoiceInterface

        with patch("app.voice.OPENAI_API_KEY", None):
            interface = ContinuousVoiceInterface()

            assert interface.is_running is False
            assert interface.feedback_enabled is True

    def test_continuous_interface_custom_wake_words(self):
        """Test wake words personnalisés."""
        from app.voice import ContinuousVoiceInterface

        with patch("app.voice.OPENAI_API_KEY", None):
            interface = ContinuousVoiceInterface(wake_words=["hey bot"])

            stats = interface.stats
            assert "hey bot" in stats["wake_listener"]["wake_words"]

    def test_continuous_interface_stats(self):
        """Test statistiques."""
        from app.voice import ContinuousVoiceInterface

        with patch("app.voice.OPENAI_API_KEY", None):
            interface = ContinuousVoiceInterface()

            stats = interface.stats
            assert "wake_listener" in stats
            assert "enabled" in stats

    def test_continuous_interface_start_without_voice(self):
        """Test démarrage sans interface vocale."""
        from app.voice import ContinuousVoiceInterface

        # VoiceInterface catch ValueError de VoiceTranscriber → enabled=False.
        # Patch directement VoiceTranscriber pour simuler OPENAI_API_KEY manquant.
        with patch("app.voice.VoiceTranscriber", side_effect=ValueError("OPENAI_API_KEY non configurée")):
            interface = ContinuousVoiceInterface()
            result = interface.start()
            assert result is False

    def test_continuous_interface_stop(self):
        """Test arrêt de l'interface."""
        from app.voice import ContinuousVoiceInterface

        with patch("app.voice.OPENAI_API_KEY", None):
            interface = ContinuousVoiceInterface()
            # Ne devrait pas lever d'exception
            interface.stop()
            assert interface.is_running is False


# ============================================================================
# TESTS SPEAK MESSAGE FOR RESULT
# ============================================================================

class TestSpeakMessageForResult:
    """Tests pour speak_message_for_result."""

    def test_speak_for_draft_result(self):
        """Test message pour brouillon."""
        from app.voice import speak_message_for_result

        with patch("app.voice.speak_message") as mock_speak:
            speak_message_for_result("Brouillon créé avec succès")
            mock_speak.assert_called_once_with("draft_created")

    def test_speak_for_skipped_result(self):
        """Test message pour email ignoré."""
        from app.voice import speak_message_for_result

        with patch("app.voice.speak_message") as mock_speak:
            speak_message_for_result("Email ignoré")
            mock_speak.assert_called_once_with("email_skipped")

    def test_speak_for_error_result(self):
        """Test message pour erreur."""
        from app.voice import speak_message_for_result

        with patch("app.voice.speak_message") as mock_speak:
            speak_message_for_result("Une erreur s'est produite")
            mock_speak.assert_called_once_with("error")

    def test_speak_for_stats_result(self):
        """Test message pour stats."""
        from app.voice import speak_message_for_result

        with patch("app.voice.speak") as mock_speak:
            result = "Stats: 100 emails traités"
            speak_message_for_result(result)
            mock_speak.assert_called_once()

    def test_speak_for_generic_result(self):
        """Test message générique."""
        from app.voice import speak_message_for_result

        with patch("app.voice.speak") as mock_speak:
            speak_message_for_result("Action terminée")
            mock_speak.assert_called_once()


# ============================================================================
# TESTS DEFAULT WAKE WORDS
# ============================================================================

class TestDefaultWakeWords:
    """Tests pour les wake words par défaut."""

    def test_default_wake_words_defined(self):
        """Test wake words par défaut définis."""
        from app.voice import DEFAULT_WAKE_WORDS

        assert len(DEFAULT_WAKE_WORDS) > 0
        assert "agent" in DEFAULT_WAKE_WORDS
        assert "agentys" in DEFAULT_WAKE_WORDS

    def test_wake_words_case_insensitive(self):
        """Test wake words insensibles à la casse."""
        from app.voice import WakeWordListener

        listener = WakeWordListener(wake_words=["AGENT", "Agentys"])

        assert "agent" in listener.wake_words
        assert "agentys" in listener.wake_words
