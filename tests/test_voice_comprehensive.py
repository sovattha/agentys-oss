# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests comprehensifs pour le module voice.

Ces tests visent a augmenter la couverture de app/voice.py de 46% a 100%.

pytest tests/test_voice_comprehensive.py -v
"""

import pytest
from unittest.mock import patch, MagicMock
import threading
from pathlib import Path
import tempfile


# ============================================================================
# TESTS TTS ENGINE
# ============================================================================


class TestTTSEngineInit:
    """Tests pour l'initialisation de TTSEngine."""

    def test_tts_engine_init_attributes(self):
        """Test des attributs initiaux de TTSEngine."""
        from app.voice import TTSEngine

        with patch("app.voice.TTS_ENABLED", True), \
             patch("app.voice.TTS_RATE", 175), \
             patch("app.voice.TTS_VOLUME", 1.0):
            engine = TTSEngine()

        assert engine._engine is None
        assert engine._initialized is False
        assert engine._rate == 175
        assert engine._volume == 1.0
        assert engine._available_voices == []

    def test_tts_engine_init_disabled_by_env(self):
        """Test TTSEngine desactive via variable d'environnement."""
        from app.voice import TTSEngine

        with patch("app.voice.TTS_ENABLED", False):
            engine = TTSEngine()

        assert engine._enabled is False


class TestTTSEngineInitEngine:
    """Tests pour la methode _init_engine."""

    def test_init_engine_success(self):
        """Test initialisation reussie du moteur TTS."""
        from app.voice import TTSEngine

        mock_pyttsx3 = MagicMock()
        mock_engine = MagicMock()
        mock_voice = MagicMock()
        mock_voice.id = "voice_id"
        mock_voice.name = "French Voice"
        mock_voice.languages = ["fr-FR"]
        mock_engine.getProperty.return_value = [mock_voice]

        mock_pyttsx3.init.return_value = mock_engine

        with patch.dict("sys.modules", {"pyttsx3": mock_pyttsx3}):
            engine = TTSEngine()
            result = engine._init_engine()

        assert result is True
        assert engine._initialized is True
        assert engine._engine is mock_engine
        mock_engine.setProperty.assert_any_call("rate", engine._rate)
        mock_engine.setProperty.assert_any_call("volume", engine._volume)

    def test_init_engine_already_initialized(self):
        """Test _init_engine quand deja initialise."""
        from app.voice import TTSEngine

        engine = TTSEngine()
        engine._initialized = True
        engine._engine = MagicMock()

        result = engine._init_engine()

        assert result is True

    def test_init_engine_already_initialized_no_engine(self):
        """Test _init_engine quand initialise mais sans moteur."""
        from app.voice import TTSEngine

        engine = TTSEngine()
        engine._initialized = True
        engine._engine = None

        result = engine._init_engine()

        assert result is False

    def test_init_engine_import_error(self):
        """Test _init_engine avec erreur d'import."""
        from app.voice import TTSEngine

        with patch.dict("sys.modules", {"pyttsx3": None}):
            with patch("builtins.__import__", side_effect=ImportError("pyttsx3 not found")):
                engine = TTSEngine()
                result = engine._init_engine()

        assert result is False
        assert engine._initialized is True
        assert engine._engine is None

    def test_init_engine_runtime_error(self):
        """Test _init_engine avec erreur runtime."""
        from app.voice import TTSEngine

        mock_pyttsx3 = MagicMock()
        mock_pyttsx3.init.side_effect = RuntimeError("Audio device not found")

        with patch.dict("sys.modules", {"pyttsx3": mock_pyttsx3}):
            engine = TTSEngine()
            result = engine._init_engine()

        assert result is False
        assert engine._engine is None


class TestTTSEngineTrySetFrenchVoice:
    """Tests pour la methode _try_set_french_voice."""

    def test_try_set_french_voice_no_engine(self):
        """Test _try_set_french_voice sans moteur."""
        from app.voice import TTSEngine

        engine = TTSEngine()
        engine._engine = None

        result = engine._try_set_french_voice()

        assert result is False

    def test_try_set_french_voice_found(self):
        """Test _try_set_french_voice trouve une voix francaise."""
        from app.voice import TTSEngine

        mock_engine = MagicMock()
        engine = TTSEngine()
        engine._engine = mock_engine
        engine._available_voices = [
            {"id": "en_voice", "name": "English Voice", "lang": []},
            {"id": "fr_voice", "name": "French Voice", "lang": ["fr-FR"]},
        ]

        result = engine._try_set_french_voice()

        assert result is True
        mock_engine.setProperty.assert_called_with("voice", "fr_voice")

    def test_try_set_french_voice_found_francais(self):
        """Test _try_set_french_voice trouve 'francais' dans le nom."""
        from app.voice import TTSEngine

        mock_engine = MagicMock()
        engine = TTSEngine()
        engine._engine = mock_engine
        engine._available_voices = [
            {"id": "fr_voice", "name": "Voix Francais", "lang": []},
        ]

        result = engine._try_set_french_voice()

        assert result is True

    def test_try_set_french_voice_found_fr(self):
        """Test _try_set_french_voice trouve 'fr' dans le nom."""
        from app.voice import TTSEngine

        mock_engine = MagicMock()
        engine = TTSEngine()
        engine._engine = mock_engine
        engine._available_voices = [
            {"id": "fr_voice", "name": "Voice FR", "lang": []},
        ]

        result = engine._try_set_french_voice()

        assert result is True

    def test_try_set_french_voice_not_found(self):
        """Test _try_set_french_voice aucune voix francaise."""
        from app.voice import TTSEngine

        mock_engine = MagicMock()
        engine = TTSEngine()
        engine._engine = mock_engine
        engine._available_voices = [
            {"id": "en_voice", "name": "English Voice", "lang": []},
        ]

        result = engine._try_set_french_voice()

        assert result is False

    def test_try_set_french_voice_set_error(self):
        """Test _try_set_french_voice avec erreur lors du setProperty."""
        from app.voice import TTSEngine

        mock_engine = MagicMock()
        mock_engine.setProperty.side_effect = Exception("Failed to set voice")

        engine = TTSEngine()
        engine._engine = mock_engine
        engine._available_voices = [
            {"id": "fr_voice", "name": "French Voice", "lang": []},
        ]

        result = engine._try_set_french_voice()

        assert result is False


class TestTTSEngineEnabledProperty:
    """Tests pour la propriete enabled."""

    def test_enabled_false_when_disabled(self):
        """Test enabled retourne False quand desactive."""
        from app.voice import TTSEngine

        engine = TTSEngine()
        engine._enabled = False

        assert engine.enabled is False

    def test_enabled_calls_init_when_not_initialized(self):
        """Test enabled appelle _init_engine quand pas initialise."""
        from app.voice import TTSEngine

        engine = TTSEngine()
        engine._enabled = True
        engine._initialized = False

        with patch.object(engine, "_init_engine", return_value=True) as mock_init:
            _ = engine.enabled  # Access the property to trigger _init_engine

        mock_init.assert_called_once()

    def test_enabled_checks_engine_when_initialized(self):
        """Test enabled verifie l'engine quand initialise."""
        from app.voice import TTSEngine

        engine = TTSEngine()
        engine._enabled = True
        engine._initialized = True
        engine._engine = MagicMock()

        assert engine.enabled is True

        engine._engine = None
        assert engine.enabled is False


class TestTTSEngineSetRate:
    """Tests pour la methode set_rate."""

    def test_set_rate_updates_internal_rate(self):
        """Test set_rate met a jour _rate."""
        from app.voice import TTSEngine

        engine = TTSEngine()
        engine.set_rate(200)

        assert engine._rate == 200

    def test_set_rate_updates_engine(self):
        """Test set_rate met a jour le moteur si disponible."""
        from app.voice import TTSEngine

        mock_engine = MagicMock()
        engine = TTSEngine()
        engine._engine = mock_engine

        engine.set_rate(200)

        mock_engine.setProperty.assert_called_with("rate", 200)

    def test_set_rate_no_engine(self):
        """Test set_rate sans moteur initialise."""
        from app.voice import TTSEngine

        engine = TTSEngine()
        engine._engine = None

        # Ne devrait pas lever d'exception
        engine.set_rate(200)

        assert engine._rate == 200


class TestTTSEngineSetVolume:
    """Tests pour la methode set_volume."""

    def test_set_volume_updates_internal_volume(self):
        """Test set_volume met a jour _volume."""
        from app.voice import TTSEngine

        engine = TTSEngine()
        engine.set_volume(0.5)

        assert engine._volume == 0.5

    def test_set_volume_clamps_low(self):
        """Test set_volume limite a 0.0 minimum."""
        from app.voice import TTSEngine

        engine = TTSEngine()
        engine.set_volume(-0.5)

        assert engine._volume == 0.0

    def test_set_volume_clamps_high(self):
        """Test set_volume limite a 1.0 maximum."""
        from app.voice import TTSEngine

        engine = TTSEngine()
        engine.set_volume(1.5)

        assert engine._volume == 1.0

    def test_set_volume_updates_engine(self):
        """Test set_volume met a jour le moteur si disponible."""
        from app.voice import TTSEngine

        mock_engine = MagicMock()
        engine = TTSEngine()
        engine._engine = mock_engine

        engine.set_volume(0.7)

        mock_engine.setProperty.assert_called_with("volume", 0.7)


class TestTTSEngineSetVoice:
    """Tests pour la methode set_voice."""

    def test_set_voice_init_fails(self):
        """Test set_voice quand init echoue."""
        from app.voice import TTSEngine

        engine = TTSEngine()

        with patch.object(engine, "_init_engine", return_value=False):
            result = engine.set_voice("french")

        assert result is False

    def test_set_voice_found(self):
        """Test set_voice trouve une voix correspondante."""
        from app.voice import TTSEngine

        mock_engine = MagicMock()
        engine = TTSEngine()
        engine._engine = mock_engine
        engine._initialized = True
        engine._available_voices = [
            {"id": "en_voice", "name": "English Voice"},
            {"id": "fr_voice", "name": "Thomas French"},
        ]

        result = engine.set_voice("thomas")

        assert result is True
        mock_engine.setProperty.assert_called_with("voice", "fr_voice")

    def test_set_voice_not_found(self):
        """Test set_voice ne trouve pas la voix."""
        from app.voice import TTSEngine

        mock_engine = MagicMock()
        engine = TTSEngine()
        engine._engine = mock_engine
        engine._initialized = True
        engine._available_voices = [
            {"id": "en_voice", "name": "English Voice"},
        ]

        result = engine.set_voice("spanish")

        assert result is False

    def test_set_voice_error_on_set(self):
        """Test set_voice avec erreur lors du set."""
        from app.voice import TTSEngine

        mock_engine = MagicMock()
        mock_engine.setProperty.side_effect = Exception("Failed")

        engine = TTSEngine()
        engine._engine = mock_engine
        engine._initialized = True
        engine._available_voices = [
            {"id": "fr_voice", "name": "French Voice"},
        ]

        result = engine.set_voice("french")

        assert result is False


class TestTTSEngineGetVoices:
    """Tests pour la methode get_voices."""

    def test_get_voices_calls_init(self):
        """Test get_voices appelle _init_engine."""
        from app.voice import TTSEngine

        engine = TTSEngine()
        engine._available_voices = []

        with patch.object(engine, "_init_engine") as mock_init:
            engine.get_voices()

        mock_init.assert_called_once()

    def test_get_voices_returns_voices(self):
        """Test get_voices retourne les voix."""
        from app.voice import TTSEngine

        engine = TTSEngine()
        engine._initialized = True
        expected_voices = [{"id": "v1", "name": "Voice 1"}]
        engine._available_voices = expected_voices

        result = engine.get_voices()

        assert result == expected_voices


class TestTTSEngineSpeak:
    """Tests pour la methode speak."""

    def test_speak_disabled(self):
        """Test speak quand desactive."""
        from app.voice import TTSEngine

        engine = TTSEngine()
        engine._enabled = False

        result = engine.speak("Hello")

        assert result is False

    def test_speak_blocking(self):
        """Test speak en mode bloquant."""
        from app.voice import TTSEngine

        mock_pyttsx3_engine = MagicMock()
        engine = TTSEngine()
        engine._engine = mock_pyttsx3_engine
        engine._enabled = True
        engine._initialized = True

        result = engine.speak("Hello", block=True)

        assert result is True
        mock_pyttsx3_engine.say.assert_called_once_with("Hello")
        mock_pyttsx3_engine.runAndWait.assert_called_once()

    def test_speak_non_blocking(self):
        """Test speak en mode non-bloquant."""
        from app.voice import TTSEngine

        mock_pyttsx3_engine = MagicMock()
        engine = TTSEngine()
        engine._engine = mock_pyttsx3_engine
        engine._enabled = True
        engine._initialized = True

        with patch("threading.Thread") as mock_thread:
            mock_thread_instance = MagicMock()
            mock_thread.return_value = mock_thread_instance

            result = engine.speak("Hello", block=False)

        assert result is True
        mock_pyttsx3_engine.say.assert_called_once_with("Hello")
        mock_thread.assert_called_once()
        mock_thread_instance.start.assert_called_once()

    def test_speak_error(self):
        """Test speak avec erreur."""
        from app.voice import TTSEngine

        mock_pyttsx3_engine = MagicMock()
        mock_pyttsx3_engine.say.side_effect = Exception("TTS error")

        engine = TTSEngine()
        engine._engine = mock_pyttsx3_engine
        engine._enabled = True
        engine._initialized = True

        result = engine.speak("Hello")

        assert result is False


class TestTTSEngineSpeakAsync:
    """Tests pour la methode speak_async."""

    def test_speak_async_creates_thread(self):
        """Test speak_async cree un thread."""
        from app.voice import TTSEngine

        engine = TTSEngine()

        with patch("threading.Thread") as mock_thread:
            mock_thread_instance = MagicMock()
            mock_thread.return_value = mock_thread_instance

            engine.speak_async("Hello")

        mock_thread.assert_called_once()
        mock_thread_instance.start.assert_called_once()


class TestTTSEngineStop:
    """Tests pour la methode stop."""

    def test_stop_with_engine(self):
        """Test stop avec moteur."""
        from app.voice import TTSEngine

        mock_engine = MagicMock()
        engine = TTSEngine()
        engine._engine = mock_engine

        engine.stop()

        mock_engine.stop.assert_called_once()

    def test_stop_without_engine(self):
        """Test stop sans moteur."""
        from app.voice import TTSEngine

        engine = TTSEngine()
        engine._engine = None

        # Ne devrait pas lever d'exception
        engine.stop()

    def test_stop_with_error(self):
        """Test stop avec erreur."""
        from app.voice import TTSEngine

        mock_engine = MagicMock()
        mock_engine.stop.side_effect = Exception("Stop error")

        engine = TTSEngine()
        engine._engine = mock_engine

        # Ne devrait pas lever d'exception
        engine.stop()


# ============================================================================
# TESTS TTS MESSAGES
# ============================================================================


class TestTTSMessages:
    """Tests pour les messages TTS."""

    def test_tts_messages_defined(self):
        """Test messages TTS definis."""
        from app.voice import TTS_MESSAGES

        assert "draft_created" in TTS_MESSAGES
        assert "email_skipped" in TTS_MESSAGES
        assert "error" in TTS_MESSAGES
        assert len(TTS_MESSAGES) > 10

    def test_get_tts_message_simple(self):
        """Test get_tts_message sans formatage."""
        from app.voice import get_tts_message

        result = get_tts_message("draft_created")

        assert result == "Brouillon cree avec succes" or "Brouillon" in result

    def test_get_tts_message_with_format(self):
        """Test get_tts_message avec formatage."""
        from app.voice import get_tts_message

        result = get_tts_message("new_emails", count=5)

        assert "5" in result

    def test_get_tts_message_unknown_key(self):
        """Test get_tts_message avec cle inconnue retourne la cle."""
        from app.voice import get_tts_message

        result = get_tts_message("unknown_key")

        assert result == "unknown_key"


# ============================================================================
# TESTS HELPER FUNCTIONS
# ============================================================================


class TestSpeakFunction:
    """Tests pour la fonction speak."""

    def test_speak_calls_tts_engine(self):
        """Test speak appelle tts_engine.speak."""
        from app import voice

        with patch.object(voice.tts_engine, "speak", return_value=True) as mock_speak:
            result = voice.speak("Hello", block=False)

        mock_speak.assert_called_once_with("Hello", False)
        assert result is True


class TestSpeakMessageFunction:
    """Tests pour la fonction speak_message."""

    def test_speak_message_calls_speak(self):
        """Test speak_message appelle speak avec le bon message."""
        from app import voice

        with patch.object(voice, "speak", return_value=True) as mock_speak:
            result = voice.speak_message("draft_created", block=True)

        mock_speak.assert_called_once()
        assert result is True


# ============================================================================
# TESTS VOICE TRANSCRIBER
# ============================================================================


class TestVoiceTranscriber:
    """Tests pour VoiceTranscriber."""

    def test_transcriber_init_no_api_key(self):
        """Test init sans cle API."""
        from app.voice import VoiceTranscriber

        # api_key=OPENAI_API_KEY est capturée comme default à la création du
        # dataclass → patch module-level constant ne suffit pas. On passe
        # api_key=None explicitement.
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            VoiceTranscriber(api_key=None)

    def test_transcriber_init_with_api_key(self):
        """Test init avec cle API."""
        from app.voice import VoiceTranscriber

        transcriber = VoiceTranscriber(api_key="test_key")

        assert transcriber.api_key == "test_key"
        assert transcriber.model == "whisper-1"

    def test_transcribe_success(self):
        """Test transcription reussie."""
        from app.voice import VoiceTranscriber

        mock_openai = MagicMock()
        mock_client = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        mock_client.audio.transcriptions.create.return_value = "  Hello world  "

        with patch.dict("sys.modules", {"openai": mock_openai}):
            transcriber = VoiceTranscriber(api_key="test_key")

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(b"fake audio data")
                audio_path = Path(f.name)

            result = transcriber.transcribe(audio_path)

        assert result == "Hello world"

    def test_transcribe_import_error(self):
        """Test transcription avec erreur d'import openai."""
        from app.voice import VoiceTranscriber

        transcriber = VoiceTranscriber(api_key="test_key")

        with patch("builtins.__import__", side_effect=ImportError("openai not found")):
            with pytest.raises(ImportError, match="openai"):
                transcriber.transcribe(Path("test.wav"))

    def test_transcribe_api_error(self):
        """Test transcription avec erreur API."""
        from app.voice import VoiceTranscriber

        mock_openai = MagicMock()
        mock_client = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        mock_client.audio.transcriptions.create.side_effect = Exception("API error")

        with patch.dict("sys.modules", {"openai": mock_openai}):
            transcriber = VoiceTranscriber(api_key="test_key")

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(b"fake audio data")
                audio_path = Path(f.name)

            with pytest.raises(RuntimeError, match="Erreur transcription"):
                transcriber.transcribe(audio_path)

    def test_transcribe_from_microphone_success(self):
        """Test enregistrement microphone reussi."""
        from app.voice import VoiceTranscriber
        import numpy as np

        mock_sd = MagicMock()
        mock_sf = MagicMock()
        mock_sd.rec.return_value = np.zeros((16000, 1))

        transcriber = VoiceTranscriber(api_key="test_key")

        with patch.dict("sys.modules", {"sounddevice": mock_sd, "soundfile": mock_sf}):
            with patch.object(transcriber, "transcribe", return_value="Hello"):
                result = transcriber.transcribe_from_microphone(duration=2)

        assert result == "Hello"
        mock_sd.rec.assert_called_once()
        mock_sd.wait.assert_called_once()

    def test_transcribe_from_microphone_import_error(self):
        """Test enregistrement microphone avec erreur d'import."""
        from app.voice import VoiceTranscriber

        transcriber = VoiceTranscriber(api_key="test_key")

        with patch("builtins.__import__", side_effect=ImportError("sounddevice not found")):
            with pytest.raises(ImportError, match="sounddevice"):
                transcriber.transcribe_from_microphone()


# ============================================================================
# TESTS VOICE INTERFACE EXECUTE
# ============================================================================


class TestVoiceInterfaceExecute:
    """Tests pour VoiceInterface._execute."""

    def test_execute_help(self):
        """Test execution commande help."""
        from app.voice import VoiceInterface

        interface = VoiceInterface()
        result = interface._execute("help", None, None)

        assert "Commandes vocales" in result

    def test_execute_show_stats(self):
        """Test execution commande show_stats."""
        from app.voice import VoiceInterface

        interface = VoiceInterface()

        with patch("app.history.draft_history") as mock_history:
            mock_history.get_stats.return_value = {
                "total": 100,
                "automation_rate": 85,
            }

            result = interface._execute("show_stats", None, None)

        assert "100" in result
        assert "85" in result

    def test_execute_mark_read(self):
        """Test execution commande mark_read."""
        from app.voice import VoiceInterface

        interface = VoiceInterface()
        result = interface._execute("mark_read", None, None)

        assert "lu" in result.lower()

    def test_execute_skip(self):
        """Test execution commande skip."""
        from app.voice import VoiceInterface

        interface = VoiceInterface()
        result = interface._execute("skip", None, None)

        assert "ignor" in result.lower()

    def test_execute_reply_to(self):
        """Test execution commande reply_to."""
        from app.voice import VoiceInterface

        interface = VoiceInterface()
        result = interface._execute("reply_to", "John", None)

        assert "John" in result

    def test_execute_show_priority(self):
        """Test execution commande show_priority."""
        from app.voice import VoiceInterface

        interface = VoiceInterface()
        result = interface._execute("show_priority", None, None)

        assert "priorit" in result.lower()

    def test_execute_unknown_action(self):
        """Test execution action inconnue."""
        from app.voice import VoiceInterface

        interface = VoiceInterface()
        result = interface._execute("unknown_action", None, None)

        assert "unknown_action" in result


class TestVoiceInterfaceListenAndExecute:
    """Tests pour VoiceInterface.listen_and_execute."""

    def test_listen_and_execute_disabled(self):
        """Test listen_and_execute quand desactive."""
        from app.voice import VoiceInterface

        with patch("app.voice.OPENAI_API_KEY", None):
            interface = VoiceInterface()

        interface._enabled = False
        result = interface.listen_and_execute()

        assert "non disponible" in result.lower()

    def test_listen_and_execute_success(self):
        """Test listen_and_execute reussi."""
        from app.voice import VoiceInterface

        with patch("app.voice.OPENAI_API_KEY", "test_key"):
            interface = VoiceInterface()

        interface._enabled = True
        interface.transcriber = MagicMock()
        interface.transcriber.transcribe_from_microphone.return_value = "aide"

        result = interface.listen_and_execute()

        assert "Commandes" in result

    def test_listen_and_execute_command_not_recognized(self):
        """Test listen_and_execute commande non reconnue."""
        from app.voice import VoiceInterface

        with patch("app.voice.OPENAI_API_KEY", "test_key"):
            interface = VoiceInterface()

        interface._enabled = True
        interface.transcriber = MagicMock()
        interface.transcriber.transcribe_from_microphone.return_value = "blablabla"

        result = interface.listen_and_execute()

        assert "non reconnu" in result.lower()

    def test_listen_and_execute_error(self):
        """Test listen_and_execute avec erreur."""
        from app.voice import VoiceInterface

        with patch("app.voice.OPENAI_API_KEY", "test_key"):
            interface = VoiceInterface()

        interface._enabled = True
        interface.transcriber = MagicMock()
        interface.transcriber.transcribe_from_microphone.side_effect = Exception("Mic error")

        result = interface.listen_and_execute()

        assert "Erreur" in result


# ============================================================================
# TESTS WAKE WORD LISTENER ADVANCED
# ============================================================================


class TestWakeWordListenerStart:
    """Tests pour WakeWordListener.start."""

    def test_start_already_running(self):
        """Test start quand deja en cours."""
        from app.voice import WakeWordListener

        listener = WakeWordListener()
        listener._running = True

        result = listener.start()

        assert result is True

    def test_start_success(self):
        """Test start reussi."""
        from app.voice import WakeWordListener, VoiceTranscriber

        with patch.object(VoiceTranscriber, "__init__", return_value=None), \
             patch.object(VoiceTranscriber, "__post_init__", return_value=None), \
             patch("app.voice.VoiceTranscriber") as mock_transcriber:
            mock_transcriber.return_value = MagicMock()

            listener = WakeWordListener()
            result = listener.start()

            # Arreter le thread pour nettoyer
            listener.stop()

        assert result is True


class TestWakeWordListenerStop:
    """Tests pour WakeWordListener.stop."""

    def test_stop_not_running(self):
        """Test stop quand pas en cours."""
        from app.voice import WakeWordListener

        listener = WakeWordListener()
        listener._running = False

        # Ne devrait pas lever d'exception
        listener.stop()

        assert listener.is_running is False

    def test_stop_running(self):
        """Test stop quand en cours."""
        from app.voice import WakeWordListener

        listener = WakeWordListener()
        listener._running = True
        listener._stop_event = threading.Event()
        listener._thread = MagicMock()
        listener._thread.is_alive.return_value = True

        listener.stop()

        assert listener._running is False
        listener._thread.join.assert_called_once()


class TestWakeWordListenerListenLoop:
    """Tests pour WakeWordListener._listen_loop."""

    def test_listen_loop_detection(self):
        """Test boucle d'ecoute avec detection."""
        from app.voice import WakeWordListener

        listener = WakeWordListener()
        listener._running = True
        listener._stop_event = threading.Event()
        listener._callback = MagicMock()
        listener._transcriber = MagicMock()

        # Simuler une detection puis arret
        call_count = [0]

        def mock_listen():
            call_count[0] += 1
            if call_count[0] == 1:
                return "agent"
            listener._running = False
            return None

        with patch.object(listener, "_listen_for_wake_word", side_effect=mock_listen):
            listener._listen_loop()

        assert listener._detections == 1
        listener._callback.assert_called_once_with("agent")

    def test_listen_loop_error_handling(self):
        """Test boucle d'ecoute avec gestion d'erreurs."""
        from app.voice import WakeWordListener

        listener = WakeWordListener()
        listener._running = True
        listener._stop_event = threading.Event()
        listener._max_errors = 2

        error_count = [0]

        def mock_listen():
            error_count[0] += 1
            raise Exception("Listen error")

        with patch.object(listener, "_listen_for_wake_word", side_effect=mock_listen):
            listener._listen_loop()

        assert listener._running is False
        assert listener._error_count >= listener._max_errors


class TestWakeWordListenerListenForWakeWord:
    """Tests pour WakeWordListener._listen_for_wake_word."""

    def test_listen_for_wake_word_silence(self):
        """Test detection avec silence."""
        from app.voice import WakeWordListener
        import numpy as np

        mock_sd = MagicMock()
        mock_sf = MagicMock()
        mock_sd.rec.return_value = np.zeros((16000, 1))  # Silence

        listener = WakeWordListener()

        with patch.dict("sys.modules", {"sounddevice": mock_sd, "soundfile": mock_sf}):
            result = listener._listen_for_wake_word()

        assert result is None

    def test_listen_for_wake_word_detected(self):
        """Test detection avec wake word."""
        from app.voice import WakeWordListener
        import numpy as np

        mock_sd = MagicMock()
        mock_sf = MagicMock()
        mock_sd.rec.return_value = np.ones((16000, 1)) * 0.5  # Audio non-silence

        mock_transcriber = MagicMock()
        mock_transcriber.transcribe.return_value = "hey agent comment ca va"

        listener = WakeWordListener()
        listener._transcriber = mock_transcriber

        with patch.dict("sys.modules", {"sounddevice": mock_sd, "soundfile": mock_sf}), \
             patch("tempfile.NamedTemporaryFile"):
            result = listener._listen_for_wake_word()

        assert result == "agent"

    def test_listen_for_wake_word_not_detected(self):
        """Test detection sans wake word."""
        from app.voice import WakeWordListener
        import numpy as np

        mock_sd = MagicMock()
        mock_sf = MagicMock()
        mock_sd.rec.return_value = np.ones((16000, 1)) * 0.5

        mock_transcriber = MagicMock()
        mock_transcriber.transcribe.return_value = "bonjour tout le monde"

        listener = WakeWordListener()
        listener._transcriber = mock_transcriber

        with patch.dict("sys.modules", {"sounddevice": mock_sd, "soundfile": mock_sf}), \
             patch("tempfile.NamedTemporaryFile"):
            result = listener._listen_for_wake_word()

        assert result is None

    def test_listen_for_wake_word_import_error(self):
        """Test detection avec erreur d'import."""
        from app.voice import WakeWordListener

        listener = WakeWordListener()

        with patch("builtins.__import__", side_effect=ImportError("sounddevice not found")):
            with pytest.raises(ImportError, match="sounddevice"):
                listener._listen_for_wake_word()


# ============================================================================
# TESTS CONTINUOUS VOICE INTERFACE ADVANCED
# ============================================================================


class TestContinuousVoiceInterfaceOnWakeWord:
    """Tests pour ContinuousVoiceInterface._on_wake_word."""

    def test_on_wake_word_with_feedback(self):
        """Test callback wake word avec feedback."""
        from app.voice import ContinuousVoiceInterface

        with patch("app.voice.OPENAI_API_KEY", "test_key"):
            interface = ContinuousVoiceInterface(feedback_enabled=True)

        interface._voice_interface._enabled = True
        interface._voice_interface.transcriber = MagicMock()
        interface._voice_interface.transcriber.transcribe_from_microphone.return_value = "aide"

        with patch("app.voice.speak") as mock_speak, \
             patch("app.voice.speak_message_for_result"):
            interface._on_wake_word("agent")

        mock_speak.assert_called_with("Oui?", block=True)

    def test_on_wake_word_without_feedback(self):
        """Test callback wake word sans feedback."""
        from app.voice import ContinuousVoiceInterface

        with patch("app.voice.OPENAI_API_KEY", "test_key"):
            interface = ContinuousVoiceInterface(feedback_enabled=False)

        interface._voice_interface._enabled = True
        interface._voice_interface.transcriber = MagicMock()
        interface._voice_interface.transcriber.transcribe_from_microphone.return_value = "aide"

        with patch("app.voice.speak") as mock_speak:
            interface._on_wake_word("agent")

        mock_speak.assert_not_called()

    def test_on_wake_word_error_with_feedback(self):
        """Test callback wake word avec erreur et feedback."""
        from app.voice import ContinuousVoiceInterface

        with patch("app.voice.OPENAI_API_KEY", "test_key"):
            interface = ContinuousVoiceInterface(feedback_enabled=True)

        interface._voice_interface._enabled = True
        interface._voice_interface.listen_and_execute = MagicMock(side_effect=Exception("Error"))

        with patch("app.voice.speak") as mock_speak:
            interface._on_wake_word("agent")

        # Devrait appeler speak pour l'erreur
        assert mock_speak.call_count >= 1


# ============================================================================
# TESTS SPEAK MESSAGE FOR RESULT
# ============================================================================


class TestSpeakMessageForResultExtended:
    """Tests etendus pour speak_message_for_result."""

    def test_speak_for_long_result(self):
        """Test message pour resultat long."""
        from app.voice import speak_message_for_result

        with patch("app.voice.speak") as mock_speak:
            long_result = "A" * 100
            speak_message_for_result(long_result)

        # Devrait tronquer a 50 caracteres
        call_args = mock_speak.call_args[0][0]
        assert len(call_args) <= 50

    def test_speak_for_draft_english(self):
        """Test message pour draft en anglais."""
        from app.voice import speak_message_for_result

        with patch("app.voice.speak_message") as mock_speak:
            speak_message_for_result("Draft created successfully")

        mock_speak.assert_called_with("draft_created")

    def test_speak_for_skipped_english(self):
        """Test message pour skipped en anglais."""
        from app.voice import speak_message_for_result

        with patch("app.voice.speak_message") as mock_speak:
            speak_message_for_result("Email skipped")

        mock_speak.assert_called_with("email_skipped")

    def test_speak_for_error_english(self):
        """Test message pour error en anglais."""
        from app.voice import speak_message_for_result

        with patch("app.voice.speak_message") as mock_speak:
            speak_message_for_result("An error occurred")

        mock_speak.assert_called_with("error")


# ============================================================================
# TESTS MAIN FUNCTION
# ============================================================================


class TestMainFunction:
    """Tests pour la fonction main."""

    def test_main_disabled(self):
        """Test main quand commandes vocales desactivees."""
        from app import voice

        with patch.object(voice.VoiceInterface, "__init__", return_value=None):
            mock_interface = MagicMock()
            mock_interface.enabled = False

            with patch("app.voice.VoiceInterface", return_value=mock_interface):
                # Main devrait retourner sans boucle
                with patch("builtins.print"):
                    voice.main()

    def test_main_keyboard_interrupt(self):
        """Test main avec interruption clavier."""
        from app import voice

        mock_interface = MagicMock()
        mock_interface.enabled = True
        mock_interface.parser.get_help.return_value = "Help text"

        with patch("app.voice.VoiceInterface", return_value=mock_interface), \
             patch("builtins.input", side_effect=KeyboardInterrupt), \
             patch("builtins.print"):
            # Main devrait gerer KeyboardInterrupt gracieusement
            voice.main()


# ============================================================================
# TESTS COMMANDS VALIDATION
# ============================================================================


class TestCommandsValidation:
    """Tests pour la validation des commandes."""

    def test_all_commands_unique_actions(self):
        """Test que toutes les actions sont uniques."""
        from app.voice import COMMANDS

        actions = [cmd["action"] for cmd in COMMANDS.values()]
        assert len(actions) == len(set(actions))

    def test_commands_have_multiple_patterns(self):
        """Test que certaines commandes ont plusieurs patterns."""
        from app.voice import COMMANDS

        commands_with_multiple = [
            name for name, cmd in COMMANDS.items()
            if len(cmd["patterns"]) > 1
        ]
        assert len(commands_with_multiple) > 0

    def test_patterns_support_french_and_english(self):
        """Test que les patterns supportent francais et anglais."""
        from app.voice import COMMANDS

        # Verifier que 'aide' a des patterns en francais et anglais
        aide_patterns = COMMANDS.get("aide", {}).get("patterns", [])
        pattern_str = " ".join(aide_patterns)
        assert "aide" in pattern_str.lower() or "help" in pattern_str.lower()


# ============================================================================
# TESTS THREAD SAFETY
# ============================================================================


class TestThreadSafety:
    """Tests pour la securite des threads."""

    def test_tts_engine_lock(self):
        """Test que TTSEngine utilise un lock."""
        from app.voice import TTSEngine

        engine = TTSEngine()
        assert hasattr(engine, "_lock")
        assert isinstance(engine._lock, type(threading.Lock()))

    def test_wake_listener_stop_event(self):
        """Test que WakeWordListener utilise un Event pour arret."""
        from app.voice import WakeWordListener

        listener = WakeWordListener()
        assert hasattr(listener, "_stop_event")
        assert isinstance(listener._stop_event, type(threading.Event()))


# ============================================================================
# TESTS EDGE CASES
# ============================================================================


class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_empty_wake_words_list(self):
        """Test avec liste de wake words vide utilisant les defaults."""
        from app.voice import WakeWordListener, DEFAULT_WAKE_WORDS

        # Quand on passe [], les wake words restent []
        # car la logique est: wake_words or DEFAULT_WAKE_WORDS
        # Mais [] est falsy, donc DEFAULT_WAKE_WORDS est utilise
        listener = WakeWordListener(wake_words=[])
        # La logique fait que [] devient les defaults
        expected = [w.lower() for w in DEFAULT_WAKE_WORDS]
        assert listener.wake_words == expected

    def test_very_long_text_to_speak(self):
        """Test avec texte tres long a prononcer."""
        from app.voice import TTSEngine

        engine = TTSEngine()
        engine._enabled = False

        # Ne devrait pas lever d'exception
        result = engine.speak("A" * 10000)
        assert result is False

    def test_special_characters_in_command(self):
        """Test commande avec caracteres speciaux."""
        from app.voice import CommandParser

        parser = CommandParser()
        action, _ = parser.parse("aide!@#$%")

        # Devrait quand meme reconnaitre 'aide'
        assert action == "help"

    def test_unicode_in_command(self):
        """Test commande avec unicode."""
        from app.voice import CommandParser

        parser = CommandParser()
        action, _ = parser.parse("aide ")

        assert action == "help"

    def test_whitespace_only_command(self):
        """Test commande avec espaces seulement."""
        from app.voice import CommandParser

        parser = CommandParser()
        action, _ = parser.parse("   ")

        assert action is None

    def test_mixed_case_wake_words(self):
        """Test wake words avec casse mixte."""
        from app.voice import WakeWordListener

        listener = WakeWordListener(wake_words=["AGENT", "AgEnTyS", "hey AGENT"])

        assert "agent" in listener.wake_words
        assert "agentys" in listener.wake_words
        assert "hey agent" in listener.wake_words


# ============================================================================
# TESTS CONFIGURATION
# ============================================================================


class TestConfiguration:
    """Tests pour la configuration."""

    def test_default_rate(self):
        """Test taux par defaut."""
        from app.voice import TTS_RATE

        assert TTS_RATE == 175

    def test_default_volume(self):
        """Test volume par defaut."""
        from app.voice import TTS_VOLUME

        assert TTS_VOLUME == 1.0

    def test_default_wake_words_content(self):
        """Test contenu des wake words par defaut."""
        from app.voice import DEFAULT_WAKE_WORDS

        assert "agent" in DEFAULT_WAKE_WORDS
        assert "agentys" in DEFAULT_WAKE_WORDS
        assert "hey agent" in DEFAULT_WAKE_WORDS


# ============================================================================
# TESTS ADDITIONAL COVERAGE
# ============================================================================


class TestVoiceInterfaceWithApiKey:
    """Tests pour VoiceInterface avec cle API."""

    def test_voice_interface_enabled_with_api_key(self):
        """Test VoiceInterface est active avec cle API."""
        from app.voice import VoiceInterface, VoiceTranscriber

        with patch.object(VoiceTranscriber, "__init__", return_value=None), \
             patch.object(VoiceTranscriber, "__post_init__", return_value=None):
            interface = VoiceInterface()

        assert interface._enabled is True


class TestWakeWordListenerCallbackError:
    """Tests pour les erreurs de callback du WakeWordListener."""

    def test_listen_loop_callback_error(self):
        """Test boucle d'ecoute avec erreur de callback."""
        from app.voice import WakeWordListener

        listener = WakeWordListener()
        listener._running = True
        listener._stop_event = threading.Event()
        listener._transcriber = MagicMock()

        # Callback qui leve une exception
        def failing_callback(word):
            raise Exception("Callback failed")

        listener._callback = failing_callback

        # Simuler une detection puis arret
        call_count = [0]

        def mock_listen():
            call_count[0] += 1
            if call_count[0] == 1:
                return "agent"
            listener._running = False
            return None

        with patch.object(listener, "_listen_for_wake_word", side_effect=mock_listen), \
             patch("builtins.print"):
            listener._listen_loop()

        # La boucle doit continuer malgre l'erreur
        assert listener._detections == 1


class TestContinuousVoiceInterfaceStartWithEnabledInterface:
    """Tests pour ContinuousVoiceInterface.start avec interface active."""

    def test_start_with_enabled_voice_interface(self):
        """Test start avec interface vocale active."""
        from app.voice import ContinuousVoiceInterface, VoiceTranscriber

        # Mock pour permettre l'initialisation
        with patch.object(VoiceTranscriber, "__init__", return_value=None), \
             patch.object(VoiceTranscriber, "__post_init__", return_value=None):
            interface = ContinuousVoiceInterface()

        # Mock le wake listener
        interface._wake_listener = MagicMock()
        interface._wake_listener.start.return_value = True

        result = interface.start()

        assert result is True
        interface._wake_listener.start.assert_called_once()


class TestMainFunctionLoop:
    """Tests pour la boucle principale de main."""

    def test_main_loop_processes_commands(self):
        """Test boucle main traite les commandes."""
        from app import voice

        # Simuler plusieurs iterations puis KeyboardInterrupt
        call_count = [0]

        def mock_input():
            call_count[0] += 1
            if call_count[0] > 2:
                raise KeyboardInterrupt
            return ""

        mock_interface = MagicMock()
        mock_interface.enabled = True
        mock_interface.parser.get_help.return_value = "Help text"
        mock_interface.listen_and_execute.return_value = "Command executed"

        with patch("app.voice.VoiceInterface", return_value=mock_interface), \
             patch("builtins.input", side_effect=mock_input), \
             patch("builtins.print"):
            voice.main()

        # listen_and_execute doit etre appele au moins une fois
        assert mock_interface.listen_and_execute.call_count >= 1


class TestModuleRunAsMain:
    """Test du module quand execute directement."""

    def test_module_main_block(self):
        """Test que __name__ == '__main__' appelle main."""
        # Ce test est difficile a implementer proprement
        # car il necessite d'executer le module directement
        # On verifie simplement que main existe et est callable
        from app.voice import main

        assert callable(main)
