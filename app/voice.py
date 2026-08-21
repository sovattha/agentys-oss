# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Commandes vocales pour Agentys.

Ce module permet de :
- Transcrire des commandes audio (STT via OpenAI Whisper)
- Parser les commandes naturelles
- Exécuter les actions correspondantes
- Feedback vocal (TTS via pyttsx3)

Prérequis:
- pip install openai pyttsx3
- Variable OPENAI_API_KEY configurée

Usage TTS:
    from app.voice import tts_engine, speak

    # Parler une phrase
    speak("Brouillon créé avec succès")

    # Configuration avancée
    tts_engine.set_rate(150)  # Vitesse
    tts_engine.set_voice("french")  # Voix française si disponible
"""

import os
import re
import threading
from dataclasses import dataclass
from typing import Optional, Tuple, List
from pathlib import Path

# ============================================================================
# CONFIGURATION
# ============================================================================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TTS_ENABLED = os.getenv("TTS_ENABLED", "true").lower() == "true"
TTS_RATE = int(os.getenv("TTS_RATE", "175"))  # Mots par minute
TTS_VOLUME = float(os.getenv("TTS_VOLUME", "1.0"))  # 0.0 à 1.0


# ============================================================================
# TEXT-TO-SPEECH ENGINE
# ============================================================================

class TTSEngine:
    """
    Moteur Text-to-Speech pour le feedback vocal.

    Utilise pyttsx3 pour la synthèse vocale cross-platform.
    Thread-safe pour utilisation depuis le daemon.

    Attributes:
        enabled: Si le TTS est activé
        rate: Vitesse de parole en mots par minute
        volume: Volume (0.0 à 1.0)
    """

    def __init__(self):
        self._engine = None
        self._enabled = TTS_ENABLED
        self._lock = threading.Lock()
        self._initialized = False
        self._rate = TTS_RATE
        self._volume = TTS_VOLUME
        self._available_voices: List[dict] = []

    def _init_engine(self) -> bool:
        """Initialise le moteur TTS de manière lazy."""
        if self._initialized:
            return self._engine is not None

        try:
            import pyttsx3
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", self._rate)
            self._engine.setProperty("volume", self._volume)

            # Lister les voix disponibles
            voices = self._engine.getProperty("voices")
            self._available_voices = [
                {"id": v.id, "name": v.name, "lang": getattr(v, "languages", [])}
                for v in voices
            ]

            # Essayer de trouver une voix française
            self._try_set_french_voice()

            self._initialized = True
            return True
        except Exception as e:
            print(f"⚠️ TTS non disponible: {e}")
            self._initialized = True
            self._engine = None
            return False

    def _try_set_french_voice(self) -> bool:
        """Tente de configurer une voix française."""
        if not self._engine:
            return False

        for voice in self._available_voices:
            name_lower = voice["name"].lower()
            if "french" in name_lower or "français" in name_lower or "fr" in name_lower:
                try:
                    self._engine.setProperty("voice", voice["id"])
                    return True
                except Exception:
                    pass
        return False

    @property
    def enabled(self) -> bool:
        """Retourne True si le TTS est activé et fonctionnel."""
        if not self._enabled:
            return False
        if not self._initialized:
            return self._init_engine()
        return self._engine is not None

    def set_rate(self, rate: int) -> None:
        """Configure la vitesse de parole."""
        self._rate = rate
        if self._engine:
            self._engine.setProperty("rate", rate)

    def set_volume(self, volume: float) -> None:
        """Configure le volume (0.0 à 1.0)."""
        self._volume = max(0.0, min(1.0, volume))
        if self._engine:
            self._engine.setProperty("volume", self._volume)

    def set_voice(self, voice_query: str) -> bool:
        """
        Configure la voix par nom ou langue.

        Args:
            voice_query: Partie du nom de la voix ou langue (ex: "french", "Thomas")

        Returns:
            True si une voix correspondante a été trouvée
        """
        if not self._init_engine():
            return False

        query_lower = voice_query.lower()
        for voice in self._available_voices:
            if query_lower in voice["name"].lower():
                try:
                    self._engine.setProperty("voice", voice["id"])
                    return True
                except Exception:
                    pass
        return False

    def get_voices(self) -> List[dict]:
        """Retourne la liste des voix disponibles."""
        self._init_engine()
        return self._available_voices

    def speak(self, text: str, block: bool = False) -> bool:
        """
        Prononce le texte donné.

        Args:
            text: Le texte à prononcer
            block: Si True, attend la fin de la parole

        Returns:
            True si le texte a été prononcé avec succès
        """
        if not self.enabled:
            return False

        with self._lock:
            try:
                self._engine.say(text)
                if block:
                    self._engine.runAndWait()
                else:
                    # Exécuter dans un thread séparé
                    threading.Thread(
                        target=self._engine.runAndWait,
                        daemon=True
                    ).start()
                return True
            except Exception as e:
                print(f"⚠️ Erreur TTS: {e}")
                return False

    def speak_async(self, text: str) -> None:
        """Prononce le texte de manière asynchrone."""
        threading.Thread(
            target=self.speak,
            args=(text, True),
            daemon=True
        ).start()

    def stop(self) -> None:
        """Arrête la parole en cours."""
        if self._engine:
            try:
                self._engine.stop()
            except Exception:
                pass


# ============================================================================
# MESSAGES TTS PRÉDÉFINIS
# ============================================================================

TTS_MESSAGES = {
    # Confirmations
    "draft_created": "Brouillon créé avec succès",
    "draft_created_v1": "Brouillon validé du premier coup",
    "draft_created_v2": "Brouillon créé après correction",
    "email_skipped": "Email ignoré",
    "email_marked_read": "Email marqué comme lu",

    # Statuts
    "processing": "Traitement en cours",
    "daemon_started": "Daemon démarré",
    "daemon_stopped": "Daemon arrêté",
    "checking_emails": "Vérification des nouveaux emails",
    "no_new_emails": "Aucun nouvel email",
    "new_emails": "{count} nouveaux emails détectés",

    # Priorités
    "urgent_email": "Email urgent détecté",
    "important_email": "Email important",

    # Erreurs
    "error": "Une erreur s'est produite",
    "connection_error": "Erreur de connexion",
    "api_error": "Erreur API",

    # Aide
    "help_intro": "Voici les commandes disponibles",
    "command_not_recognized": "Commande non reconnue",
}


def get_tts_message(key: str, **kwargs) -> str:
    """Récupère un message TTS prédéfini avec formatage."""
    message = TTS_MESSAGES.get(key, key)
    if kwargs:
        message = message.format(**kwargs)
    return message


# Instance globale du moteur TTS
tts_engine = TTSEngine()


def speak(text: str, block: bool = False) -> bool:
    """
    Fonction helper pour parler.

    Args:
        text: Le texte à prononcer
        block: Si True, attend la fin de la parole

    Returns:
        True si le texte a été prononcé
    """
    return tts_engine.speak(text, block)


def speak_message(key: str, block: bool = False, **kwargs) -> bool:
    """
    Prononce un message prédéfini.

    Args:
        key: Clé du message dans TTS_MESSAGES
        block: Si True, attend la fin de la parole
        **kwargs: Variables pour le formatage

    Returns:
        True si le texte a été prononcé
    """
    message = get_tts_message(key, **kwargs)
    return speak(message, block)


# ============================================================================
# COMMANDES SUPPORTÉES
# ============================================================================

COMMANDS = {
    "repondre": {
        "patterns": [
            r"répond[s]? (?:à|au|aux)? (?:l'?email|message)? (?:de )?(.*)",
            r"write (?:a )?(?:reply|response) to (.*)",
            r"answer (?:the )?email from (.*)",
        ],
        "action": "reply_to",
        "description": "Répondre à un email spécifique"
    },
    "marquer_lu": {
        "patterns": [
            r"marque[r]? (?:comme )?lu[s]?",
            r"mark (?:as )?read",
        ],
        "action": "mark_read",
        "description": "Marquer les emails comme lus"
    },
    "ignorer": {
        "patterns": [
            r"ignor(?:e[r]?|er?) (?:cet? |l'?)?(email|message)?",
            r"skip (?:this )?(?:email|message)?",
            r"passe[r]?",
        ],
        "action": "skip",
        "description": "Ignorer l'email actuel"
    },
    "priorite": {
        "patterns": [
            r"(?:montre|affiche)[r]? (?:les )?(?:emails? )?(?:urgent|prioritaire)[s]?",
            r"show (?:urgent|priority) (?:emails?)?",
        ],
        "action": "show_priority",
        "description": "Afficher les emails prioritaires"
    },
    "stats": {
        "patterns": [
            r"(?:montre|affiche)[r]? (?:les )?stats?(?:istiques)?",
            r"show (?:me )?(?:the )?stats?(?:istics)?",
        ],
        "action": "show_stats",
        "description": "Afficher les statistiques"
    },
    "refresh": {
        "patterns": [
            r"rafraîchi[rs]?|refresh|actualise[r]?",
            r"check (?:new )?(?:emails?|messages?)",
            r"vérifie[r]? (?:les )?(?:nouveaux )?(?:emails?|messages?)",
        ],
        "action": "refresh",
        "description": "Rafraîchir la liste des emails"
    },
    "status": {
        "patterns": [
            r"status|statut|état",
            r"(?:what's|whats|quel est) (?:the|le) (?:status|statut|état)",
        ],
        "action": "status",
        "description": "Afficher le statut du système"
    },
    "followups": {
        "patterns": [
            r"(?:montre|affiche)[r]? (?:les )?(?:relances|follow[- ]?ups?)",
            r"show (?:me )?(?:the )?follow[- ]?ups?",
            r"pending (?:follow[- ]?ups?|relances)",
        ],
        "action": "show_followups",
        "description": "Afficher les relances en attente"
    },
    "aide": {
        "patterns": [
            r"aide|help|commandes|commands",
        ],
        "action": "help",
        "description": "Afficher l'aide"
    },
}


# ============================================================================
# TRANSCRIPTION AUDIO
# ============================================================================

@dataclass
class VoiceTranscriber:
    """Transcrit l'audio en texte via OpenAI Whisper."""

    api_key: str = OPENAI_API_KEY
    model: str = "whisper-1"

    def __post_init__(self):
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY non configurée. Commandes vocales désactivées.")

    def transcribe(self, audio_file: Path) -> str:
        """
        Transcrit un fichier audio en texte.

        Args:
            audio_file: Chemin vers le fichier audio (mp3, wav, m4a, etc.)

        Returns:
            Le texte transcrit.
        """
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)

            with open(audio_file, "rb") as f:
                response = client.audio.transcriptions.create(
                    model=self.model,
                    file=f,
                    response_format="text"
                )

            return response.strip()

        except ImportError:
            raise ImportError("openai non installé. Exécutez: pip install openai")
        except Exception as e:
            raise RuntimeError(f"Erreur transcription: {e}")

    def transcribe_from_microphone(self, duration: int = 5) -> str:
        """
        Enregistre depuis le microphone et transcrit.

        Args:
            duration: Durée d'enregistrement en secondes.

        Returns:
            Le texte transcrit.
        """
        try:
            import sounddevice as sd
            import soundfile as sf
            import tempfile

            # Enregistrer l'audio
            sample_rate = 16000
            print(f"🎤 Parlez maintenant ({duration}s)...")
            audio = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1)
            sd.wait()
            print("✅ Enregistrement terminé")

            # Sauvegarder temporairement
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                sf.write(f.name, audio, sample_rate)
                return self.transcribe(Path(f.name))

        except ImportError:
            raise ImportError("sounddevice/soundfile non installés. Exécutez: pip install sounddevice soundfile")


# ============================================================================
# PARSER DE COMMANDES
# ============================================================================

@dataclass
class CommandParser:
    """Parse les commandes vocales en actions."""

    def parse(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse une commande textuelle.

        Args:
            text: Le texte de la commande.

        Returns:
            Tuple (action, argument) ou (None, None) si non reconnu.
        """
        text_lower = text.lower().strip()

        for cmd_name, cmd_info in COMMANDS.items():
            for pattern in cmd_info["patterns"]:
                match = re.search(pattern, text_lower, re.IGNORECASE)
                if match:
                    # Extraire l'argument si présent
                    arg = match.group(1) if match.groups() else None
                    return cmd_info["action"], arg

        return None, None

    def get_help(self) -> str:
        """Retourne l'aide des commandes disponibles."""
        lines = ["🎤 Commandes vocales disponibles:\n"]
        for cmd_name, cmd_info in COMMANDS.items():
            lines.append(f"  • {cmd_info['description']}")
            lines.append(f"    Exemples: {cmd_info['patterns'][0]}")
            lines.append("")
        return "\n".join(lines)


# ============================================================================
# INTERFACE VOCALE
# ============================================================================

class VoiceInterface:
    """Interface vocale pour Agentys."""

    def __init__(self):
        self.transcriber = None
        self.parser = CommandParser()
        self._enabled = False

        try:
            self.transcriber = VoiceTranscriber()
            self._enabled = True
        except ValueError:
            print("⚠️ Commandes vocales désactivées (OPENAI_API_KEY manquante)")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def listen_and_execute(self, daemon=None) -> Optional[str]:
        """
        Écoute une commande et l'exécute.

        Args:
            daemon: Instance du daemon pour exécuter les actions.

        Returns:
            Message de résultat ou None.
        """
        if not self._enabled:
            return "Commandes vocales non disponibles"

        try:
            # Transcrire
            text = self.transcriber.transcribe_from_microphone(duration=5)
            print(f"📝 Transcrit: {text}")

            # Parser
            action, arg = self.parser.parse(text)

            if action is None:
                return f"Commande non reconnue: {text}"

            # Exécuter
            return self._execute(action, arg, daemon)

        except Exception as e:
            return f"Erreur: {e}"

    def _execute(self, action: str, arg: Optional[str], daemon) -> str:
        """Exécute une action."""
        if action == "help":
            return self.parser.get_help()

        if action == "show_stats":
            from app.history import draft_history
            stats = draft_history.get_stats()
            return f"📊 Stats: {stats['total']} emails traités, {stats['automation_rate']}% automatisation"

        if action == "mark_read":
            return "✅ Emails marqués comme lus"

        if action == "skip":
            return "⏭️ Email ignoré"

        if action == "reply_to":
            return f"📧 Recherche d'emails de: {arg}"

        if action == "show_priority":
            return "🎯 Affichage des emails prioritaires"

        return f"Action exécutée: {action}"


# ============================================================================
# WAKE WORD LISTENER
# ============================================================================

# Wake words supportés (français et anglais)
DEFAULT_WAKE_WORDS = [
    "agent",
    "hey agent",
    "ok agent",
    "agentys",
    "hey agentys",
]


class WakeWordListener:
    """
    Écouteur de mot de réveil pour le mode écoute continue.

    Features:
    - Détection de wake word configurable
    - Mode écoute continue en arrière-plan
    - Callbacks pour actions sur détection
    - Support multi-langues

    Usage:
        listener = WakeWordListener(wake_words=["agent"])
        listener.set_callback(on_wake_word_detected)
        listener.start()  # Démarre l'écoute en background

        # Plus tard
        listener.stop()
    """

    def __init__(
        self,
        wake_words: Optional[List[str]] = None,
        listen_duration: float = 2.0,
        silence_threshold: float = 0.5,
        sample_rate: int = 16000,
    ):
        """
        Initialise l'écouteur de wake word.

        Args:
            wake_words: Liste des mots de réveil (défaut: DEFAULT_WAKE_WORDS)
            listen_duration: Durée d'écoute pour le wake word (secondes)
            silence_threshold: Seuil de silence pour arrêter l'enregistrement
            sample_rate: Taux d'échantillonnage audio
        """
        self.wake_words = [w.lower() for w in (wake_words or DEFAULT_WAKE_WORDS)]
        self.listen_duration = listen_duration
        self.silence_threshold = silence_threshold
        self.sample_rate = sample_rate

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._callback: Optional[callable] = None
        self._transcriber: Optional[VoiceTranscriber] = None
        self._error_count = 0
        self._max_errors = 5

        # Statistiques
        self._detections = 0
        self._total_listens = 0

    def set_callback(self, callback: callable) -> None:
        """
        Configure le callback appelé quand un wake word est détecté.

        Args:
            callback: Fonction appelée avec le wake word détecté
        """
        self._callback = callback

    def set_wake_words(self, wake_words: List[str]) -> None:
        """Configure les wake words."""
        self.wake_words = [w.lower() for w in wake_words]

    @property
    def is_running(self) -> bool:
        """Retourne True si l'écoute est active."""
        return self._running

    @property
    def stats(self) -> dict:
        """Retourne les statistiques d'écoute."""
        return {
            "detections": self._detections,
            "total_listens": self._total_listens,
            "running": self._running,
            "wake_words": self.wake_words,
        }

    def start(self) -> bool:
        """
        Démarre l'écoute continue en arrière-plan.

        Returns:
            True si démarré avec succès
        """
        if self._running:
            return True

        # Vérifier que le transcriber est disponible
        try:
            self._transcriber = VoiceTranscriber()
        except ValueError as e:
            print(f"⚠️ Wake word listener non disponible: {e}")
            return False

        self._running = True
        self._stop_event.clear()
        self._error_count = 0

        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

        print(f"🎤 Wake word listener démarré (mots: {', '.join(self.wake_words)})")
        return True

    def stop(self) -> None:
        """Arrête l'écoute."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

        print("🎤 Wake word listener arrêté")

    def _listen_loop(self) -> None:
        """Boucle principale d'écoute."""
        while self._running and not self._stop_event.is_set():
            try:
                # Écouter un court segment audio
                detected = self._listen_for_wake_word()

                if detected:
                    self._detections += 1
                    print(f"✨ Wake word détecté: {detected}")

                    # Appeler le callback
                    if self._callback:
                        try:
                            self._callback(detected)
                        except Exception as e:
                            print(f"⚠️ Erreur callback: {e}")

                    # Petite pause après détection
                    self._stop_event.wait(0.5)

                self._total_listens += 1
                self._error_count = 0

            except Exception as e:
                self._error_count += 1
                print(f"⚠️ Erreur écoute: {e}")

                if self._error_count >= self._max_errors:
                    print("❌ Trop d'erreurs, arrêt du listener")
                    self._running = False
                    break

                # Pause avant retry
                self._stop_event.wait(1.0)

    def _listen_for_wake_word(self) -> Optional[str]:
        """
        Écoute et détecte un wake word.

        Returns:
            Le wake word détecté ou None
        """
        try:
            import sounddevice as sd
            import soundfile as sf
            import tempfile
            import numpy as np

            # Enregistrer un court segment
            audio = sd.rec(
                int(self.listen_duration * self.sample_rate),
                samplerate=self.sample_rate,
                channels=1,
                blocking=True
            )

            # Vérifier si l'audio contient du son
            if np.max(np.abs(audio)) < 0.01:
                # Silence, pas de wake word
                return None

            # Sauvegarder et transcrire
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as f:
                sf.write(f.name, audio, self.sample_rate)
                text = self._transcriber.transcribe(Path(f.name)).lower()

            # Chercher un wake word
            for wake_word in self.wake_words:
                if wake_word in text:
                    return wake_word

            return None

        except ImportError:
            raise ImportError("sounddevice/soundfile requis pour l'écoute continue")


class ContinuousVoiceInterface:
    """
    Interface vocale avec écoute continue.

    Combine le wake word listener avec l'exécution de commandes.

    Usage:
        interface = ContinuousVoiceInterface(wake_words=["agent"])
        interface.start()

        # Plus tard
        interface.stop()
    """

    def __init__(
        self,
        wake_words: Optional[List[str]] = None,
        daemon=None,
        feedback_enabled: bool = True,
    ):
        """
        Initialise l'interface vocale continue.

        Args:
            wake_words: Liste des wake words
            daemon: Instance du daemon pour les actions
            feedback_enabled: Si True, utilise le TTS pour le feedback
        """
        self.daemon = daemon
        self.feedback_enabled = feedback_enabled

        self._voice_interface = VoiceInterface()
        self._wake_listener = WakeWordListener(wake_words)
        self._wake_listener.set_callback(self._on_wake_word)

        self._command_timeout = 10.0  # Timeout pour la commande après wake word

    def _on_wake_word(self, wake_word: str) -> None:
        """Callback appelé quand un wake word est détecté."""
        if self.feedback_enabled:
            speak("Oui?", block=True)

        print("🎤 En attente de votre commande...")

        # Écouter la commande complète
        try:
            result = self._voice_interface.listen_and_execute(self.daemon)
            print(f"📋 {result}")

            if self.feedback_enabled and result:
                speak_message_for_result(result)

        except Exception as e:
            print(f"⚠️ Erreur: {e}")
            if self.feedback_enabled:
                speak("Une erreur s'est produite")

    @property
    def is_running(self) -> bool:
        """Retourne True si l'écoute est active."""
        return self._wake_listener.is_running

    @property
    def stats(self) -> dict:
        """Retourne les statistiques."""
        return {
            "wake_listener": self._wake_listener.stats,
            "enabled": self._voice_interface.enabled,
        }

    def start(self) -> bool:
        """Démarre l'écoute continue."""
        if not self._voice_interface.enabled:
            print("⚠️ Interface vocale non disponible")
            return False

        return self._wake_listener.start()

    def stop(self) -> None:
        """Arrête l'écoute continue."""
        self._wake_listener.stop()


def speak_message_for_result(result: str) -> None:
    """Prononce un message adapté au résultat."""
    result_lower = result.lower()

    if "brouillon" in result_lower or "draft" in result_lower:
        speak_message("draft_created")
    elif "ignoré" in result_lower or "skipped" in result_lower:
        speak_message("email_skipped")
    elif "stats" in result_lower:
        speak(result[:100])  # Limiter la longueur
    elif "erreur" in result_lower or "error" in result_lower:
        speak_message("error")
    else:
        # Message générique court
        short_result = result[:50] if len(result) > 50 else result
        speak(short_result)


# ============================================================================
# POINT D'ENTRÉE
# ============================================================================

def main():
    """Test de l'interface vocale."""
    print("""
╔═══════════════════════════════════════════════════════════════╗
║              🎤 Agentys - Mode Vocal                        ║
╚═══════════════════════════════════════════════════════════════╝
    """)

    voice = VoiceInterface()

    if not voice.enabled:
        print("❌ Configurez OPENAI_API_KEY pour activer les commandes vocales")
        return

    print(voice.parser.get_help())
    print("\nAppuyez sur Entrée pour parler (Ctrl+C pour quitter)")

    try:
        while True:
            input()
            result = voice.listen_and_execute()
            print(f"\n{result}\n")
    except KeyboardInterrupt:
        print("\n👋 Au revoir!")


if __name__ == "__main__":
    main()
