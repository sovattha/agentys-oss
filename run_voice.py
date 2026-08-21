#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Point d'entrée pour les commandes vocales Agentys.

Usage:
    python run_voice.py              # Mode interactif
    python run_voice.py --listen     # Écoute continue
    python run_voice.py --text "commande"  # Commande textuelle

Prérequis:
    - pip install openai sounddevice soundfile
    - Variable OPENAI_API_KEY configurée
"""

import argparse
import sys
import logging
from pathlib import Path

# Ajouter le répertoire racine au path
sys.path.insert(0, str(Path(__file__).parent))

from app.voice import VoiceInterface, CommandParser
from app.daemon import EmailDaemon
from app.history import draft_history
from app.infrastructure.logging_config import setup_logging

# Configuration logging
setup_logging()
logger = logging.getLogger(__name__)


class VoiceController:
    """
    Contrôleur vocal pour Agentys.

    Connecte l'interface vocale au daemon et exécute les commandes.
    """

    def __init__(self, daemon: EmailDaemon = None):
        self.voice = VoiceInterface()
        self.parser = CommandParser()
        self.daemon = daemon
        self._email_cache = []  # Cache des emails pour les commandes

    def _ensure_daemon(self):
        """S'assure que le daemon est initialisé."""
        if self.daemon is None:
            print("🔄 Initialisation du daemon...")
            self.daemon = EmailDaemon()
            if not self.daemon.provider.authenticate():
                print("❌ Authentification échouée")
                return False
            print("✅ Daemon prêt")
        return True

    def execute(self, action: str, arg: str = None) -> str:
        """
        Exécute une action vocale.

        Args:
            action: L'action à exécuter.
            arg: Argument optionnel.

        Returns:
            Message de résultat.
        """
        if action == "help":
            return self.parser.get_help()

        if action == "show_stats":
            return self._show_stats()

        if action == "mark_read":
            return self._mark_read()

        if action == "skip":
            return self._skip_current()

        if action == "reply_to":
            return self._reply_to(arg)

        if action == "show_priority":
            return self._show_priority()

        if action == "refresh":
            return self._refresh_emails()

        if action == "status":
            return self._show_status()

        return f"❓ Action non reconnue: {action}"

    def _show_stats(self) -> str:
        """Affiche les statistiques."""
        stats = draft_history.get_stats()
        return (
            f"📊 Statistiques Agentys:\n"
            f"   • Emails traités: {stats.get('total', 0)}\n"
            f"   • Taux d'automatisation: {stats.get('automation_rate', 0):.0f}%\n"
            f"   • Validés V1: {stats.get('validated_v1', 0)}\n"
            f"   • Corrigés V2: {stats.get('corrected_v2', 0)}"
        )

    def _mark_read(self) -> str:
        """Marque les emails comme lus."""
        if not self._ensure_daemon():
            return "❌ Daemon non disponible"

        try:
            unread = self.daemon.provider.get_unread_messages(limit=10)
            count = 0
            for email in unread:
                self.daemon.provider.mark_as_read(email.id)
                count += 1
            return f"✅ {count} email(s) marqué(s) comme lu(s)"
        except Exception as e:
            return f"❌ Erreur: {e}"

    def _skip_current(self) -> str:
        """Ignore l'email courant."""
        if self._email_cache:
            email = self._email_cache.pop(0)
            return f"⏭️ Email ignoré: {email.subject[:40]}"
        return "📭 Aucun email en attente"

    def _reply_to(self, query: str) -> str:
        """Répond à un email spécifique."""
        if not self._ensure_daemon():
            return "❌ Daemon non disponible"

        if not query:
            return "❓ Précisez le destinataire (ex: 'réponds à John')"

        try:
            # Chercher l'email correspondant
            unread = self.daemon.provider.get_unread_messages(limit=20)
            matching = [
                e for e in unread
                if query.lower() in e.sender.lower()
                or (e.sender_name and query.lower() in e.sender_name.lower())
            ]

            if not matching:
                return f"📭 Aucun email trouvé de '{query}'"

            email = matching[0]
            print(f"📧 Traitement de: {email.subject[:50]}")

            # Générer le brouillon
            success = self.daemon.process_email(email)
            if success:
                return f"✅ Brouillon créé pour {email.sender}"
            else:
                return "❌ Échec création brouillon"

        except Exception as e:
            return f"❌ Erreur: {e}"

    def _show_priority(self) -> str:
        """Affiche les emails prioritaires."""
        if not self._ensure_daemon():
            return "❌ Daemon non disponible"

        try:
            unread = self.daemon.provider.get_unread_messages(limit=20)
            if not unread:
                return "📭 Aucun email non lu"

            # Prioriser
            prioritized = []
            for email in unread:
                content = self.daemon._format_email_for_agent(email)
                priority = self.daemon.prioritizer.analyze(content, email.sender)
                prioritized.append((email, priority.get("priority_score", 50)))

            # Trier et afficher les top 5
            prioritized.sort(key=lambda x: x[1], reverse=True)
            top_5 = prioritized[:5]

            lines = ["🎯 Emails prioritaires:"]
            for email, score in top_5:
                lines.append(f"   [{score}] {email.sender_name or email.sender}: {email.subject[:30]}")

            # Mettre en cache
            self._email_cache = [e for e, _ in top_5]

            return "\n".join(lines)

        except Exception as e:
            return f"❌ Erreur: {e}"

    def _refresh_emails(self) -> str:
        """Rafraîchit le cache des emails."""
        if not self._ensure_daemon():
            return "❌ Daemon non disponible"

        try:
            unread = self.daemon.provider.get_unread_messages(limit=50)
            self._email_cache = unread[:10]
            return f"🔄 {len(self._email_cache)} emails en cache"
        except Exception as e:
            return f"❌ Erreur: {e}"

    def _show_status(self) -> str:
        """Affiche le statut du système."""
        lines = ["📋 Statut Agentys:"]

        # Voice
        lines.append(f"   🎤 Voice: {'Actif' if self.voice.enabled else 'Inactif'}")

        # Daemon
        if self.daemon:
            lines.append("   🤖 Daemon: Connecté")
            lines.append(f"   📬 Provider: {self.daemon.provider.__class__.__name__}")
        else:
            lines.append("   🤖 Daemon: Non initialisé")


        return "\n".join(lines)


def interactive_mode(controller: VoiceController):
    """Mode interactif avec saisie texte."""
    print("""
╔═══════════════════════════════════════════════════════════════╗
║              🎤 Agentys - Mode Vocal                        ║
║                  (Mode texte interactif)                      ║
╚═══════════════════════════════════════════════════════════════╝
    """)

    print(controller.parser.get_help())
    print("\nTapez une commande (ou 'quit' pour quitter):\n")

    while True:
        try:
            text = input("🎤 > ").strip()

            if text.lower() in ("quit", "exit", "q"):
                print("👋 Au revoir!")
                break

            if not text:
                continue

            # Parser et exécuter
            action, arg = controller.parser.parse(text)

            if action is None:
                print(f"❓ Commande non reconnue: {text}")
                continue

            result = controller.execute(action, arg)
            print(f"\n{result}\n")

        except KeyboardInterrupt:
            print("\n👋 Au revoir!")
            break
        except Exception as e:
            print(f"❌ Erreur: {e}")


def listen_mode(controller: VoiceController):
    """Mode écoute continue avec micro."""
    if not controller.voice.enabled:
        print("❌ Les commandes vocales nécessitent OPENAI_API_KEY")
        print("   pip install openai sounddevice soundfile")
        return

    print("""
╔═══════════════════════════════════════════════════════════════╗
║              🎤 Agentys - Écoute Continue                   ║
║              Appuyez sur Entrée pour parler                   ║
║              Ctrl+C pour quitter                              ║
╚═══════════════════════════════════════════════════════════════╝
    """)

    print(controller.parser.get_help())

    while True:
        try:
            input("\n⏎ Appuyez sur Entrée pour parler...")

            # Transcrire
            text = controller.voice.transcriber.transcribe_from_microphone(duration=5)
            print(f"📝 Transcrit: {text}")

            # Parser et exécuter
            action, arg = controller.parser.parse(text)

            if action is None:
                print(f"❓ Commande non reconnue: {text}")
                continue

            result = controller.execute(action, arg)
            print(f"\n{result}")

        except KeyboardInterrupt:
            print("\n👋 Au revoir!")
            break
        except Exception as e:
            print(f"❌ Erreur: {e}")


def main():
    parser = argparse.ArgumentParser(description="Agentys Voice Control")
    parser.add_argument("--listen", action="store_true", help="Mode écoute continue (micro)")
    parser.add_argument("--text", type=str, help="Exécuter une commande textuelle")
    parser.add_argument("--init-daemon", action="store_true", help="Initialiser le daemon au démarrage")

    args = parser.parse_args()

    # Créer le contrôleur
    daemon = None
    if args.init_daemon:
        print("🔄 Initialisation du daemon...")
        daemon = EmailDaemon()
        if daemon.provider.authenticate():
            print("✅ Daemon prêt")
        else:
            print("❌ Authentification échouée")
            daemon = None

    controller = VoiceController(daemon=daemon)

    # Mode d'exécution
    if args.text:
        # Commande unique
        action, arg = controller.parser.parse(args.text)
        if action:
            result = controller.execute(action, arg)
            print(result)
        else:
            print(f"❓ Commande non reconnue: {args.text}")

    elif args.listen:
        # Mode écoute micro
        listen_mode(controller)

    else:
        # Mode interactif texte
        interactive_mode(controller)


if __name__ == "__main__":
    main()
