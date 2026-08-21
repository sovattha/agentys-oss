#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Script de lancement du daemon email Agentys.

Usage:
    python run_daemon.py              # Mode daemon (boucle infinie)
    python run_daemon.py --once       # Exécuter une seule fois
    python run_daemon.py --test       # Mode test (dry run)
    python run_daemon.py --setup      # Relancer la configuration
"""

import sys
import os
from pathlib import Path

# Ajouter le répertoire racine au path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))


def first_time_setup():
    """Assistant de configuration au premier lancement."""
    env_file = PROJECT_ROOT / ".env"
    env_example = PROJECT_ROOT / ".env.example"

    # Si .env existe déjà, ne rien faire
    if env_file.exists() and "--setup" not in sys.argv:
        return True

    print()
    print("=" * 60)
    print("  🚀 Bienvenue dans Agentys !")
    print("=" * 60)
    print()

    if not env_file.exists():
        print("📋 Première utilisation détectée.")
        print("   Configurons ensemble les paramètres essentiels.")
    else:
        print("📋 Reconfiguration des paramètres.")
    print()

    # Clé API Anthropic
    print("-" * 60)
    print("1️⃣  CLÉ API ANTHROPIC (obligatoire)")
    print("-" * 60)
    print()
    print("   Obtenez votre clé sur: https://console.anthropic.com/")
    print()
    api_key = input("   Clé API (sk-ant-...): ").strip()

    if not api_key:
        print("\n❌ Clé API requise. Relancez le programme.")
        return False

    # Configuration email
    print()
    print("-" * 60)
    print("2️⃣  CONFIGURATION EMAIL")
    print("-" * 60)
    print()
    print("   Serveurs courants:")
    print("   • Gmail:   imap.gmail.com / smtp.gmail.com")
    print("   • Outlook: outlook.office365.com / smtp.office365.com")
    print("   • Yahoo:   imap.mail.yahoo.com / smtp.mail.yahoo.com")
    print()

    imap_host = input("   Serveur IMAP [imap.gmail.com]: ").strip() or "imap.gmail.com"
    smtp_host = input("   Serveur SMTP [smtp.gmail.com]: ").strip() or "smtp.gmail.com"
    email_user = input("   Adresse email: ").strip()
    email_pass = input("   Mot de passe (ou mot de passe d'app): ").strip()

    if not email_user or not email_pass:
        print("\n⚠️  Email non configuré. Vous pourrez le faire plus tard dans .env")

    # Générer le .env
    print()
    print("-" * 60)
    print("📝 Création du fichier .env...")
    print("-" * 60)

    # Lire le template si disponible
    if env_example.exists():
        content = env_example.read_text(encoding="utf-8")
        # Remplacer les valeurs
        content = content.replace("ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxx", f"ANTHROPIC_API_KEY={api_key}")
        content = content.replace("IMAP_HOST=imap.example.com", f"IMAP_HOST={imap_host}")
        content = content.replace("SMTP_HOST=smtp.example.com", f"SMTP_HOST={smtp_host}")
        if email_user:
            content = content.replace("IMAP_USER=user@example.com", f"IMAP_USER={email_user}")
            content = content.replace("SMTP_USER=user@example.com", f"SMTP_USER={email_user}")
            content = content.replace("SMTP_FROM_EMAIL=user@example.com", f"SMTP_FROM_EMAIL={email_user}")
        if email_pass:
            content = content.replace("IMAP_PASSWORD=your-password", f"IMAP_PASSWORD={email_pass}")
            content = content.replace("SMTP_PASSWORD=your-password", f"SMTP_PASSWORD={email_pass}")
    else:
        # Créer un .env minimal
        content = f"""# Agentys - Configuration
# Généré automatiquement au premier lancement

# LLM
LLM_PROVIDER=claude
LLM_MODEL=claude-sonnet-4-6
ANTHROPIC_API_KEY={api_key}

# Email Provider
EMAIL_PROVIDER_TYPE=IMAP_SMTP

# IMAP (lecture)
IMAP_HOST={imap_host}
IMAP_PORT=993
IMAP_USER={email_user}
IMAP_PASSWORD={email_pass}
IMAP_USE_SSL=true
IMAP_FOLDER=INBOX

# SMTP (envoi)
SMTP_HOST={smtp_host}
SMTP_PORT=587
SMTP_USER={email_user}
SMTP_PASSWORD={email_pass}
SMTP_USE_TLS=true
SMTP_FROM_EMAIL={email_user}

# Daemon
DAEMON_POLL_INTERVAL=60
DAEMON_SKIP_LOW_PRIORITY=true

# Logs
LOG_LEVEL=INFO
"""

    env_file.write_text(content, encoding="utf-8")

    print()
    print("✅ Configuration sauvegardée dans .env")
    print()
    print("=" * 60)
    print("  🎉 Configuration terminée !")
    print("=" * 60)
    print()
    print("   Le daemon va maintenant démarrer...")
    print("   Appuyez sur Ctrl+C pour l'arrêter.")
    print()

    # Recharger les variables d'environnement
    from dotenv import load_dotenv
    load_dotenv(env_file, override=True)

    return True


if __name__ == "__main__":
    # Vérifier la configuration au premier lancement
    if "--setup" in sys.argv or not (PROJECT_ROOT / ".env").exists():
        if not first_time_setup():
            sys.exit(1)
        # Retirer --setup des arguments pour continuer
        if "--setup" in sys.argv:
            sys.argv.remove("--setup")

    from app.daemon import EmailDaemon, main

    if "--once" in sys.argv:
        # Mode single run
        print("🔄 Exécution unique...")
        daemon = EmailDaemon()
        count = daemon.run_once()
        print(f"✅ {count} email(s) traité(s)")

    elif "--test" in sys.argv:
        # Mode test - affiche la config sans exécuter
        print("🧪 Mode test - Configuration:")
        print(f"  EMAIL_PROVIDER_TYPE: {os.getenv('EMAIL_PROVIDER_TYPE', 'OUTLOOK')}")
        print(f"  DAEMON_POLL_INTERVAL: {os.getenv('DAEMON_POLL_INTERVAL', '60')}s")
        print(f"  ANTHROPIC_API_KEY: {'✓ Configurée' if os.getenv('ANTHROPIC_API_KEY') else '✗ Manquante'}")

        # Tester la création du provider
        try:
            from app.providers.factory import validate_provider_config

            provider_type = os.getenv("EMAIL_PROVIDER_TYPE", "OUTLOOK")
            config_status = validate_provider_config(provider_type)

            print(f"\n  Configuration {provider_type}:")
            for var, ok in config_status.items():
                status = "✓" if ok else "✗"
                print(f"    {status} {var}")

        except Exception as e:
            print(f"  ❌ Erreur: {e}")

    else:
        # Mode daemon normal
        main()
