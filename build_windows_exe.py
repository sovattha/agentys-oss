#!/usr/bin/env python3
"""
Build script pour créer Agentys-Backend.exe pour Windows.

Usage:
    pip install pyinstaller
    python build_windows_exe.py
"""

import subprocess
import sys
import os

def build():
    print("🔨 Build Agentys-Backend.exe...")

    # Options PyInstaller
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",                          # Un seul fichier exe
        "--name", "Agentys-Backend",          # Nom de l'exe
        "--console",                          # Afficher la console (pour voir les logs)

        # Hidden imports (modules chargés dynamiquement)
        "--hidden-import", "anthropic",
        "--hidden-import", "openai",
        "--hidden-import", "flask",
        "--hidden-import", "flask_socketio",
        "--hidden-import", "flask_cors",
        "--hidden-import", "eventlet",
        "--hidden-import", "dotenv",
        "--hidden-import", "tiktoken",
        "--hidden-import", "tiktoken_ext",
        "--hidden-import", "tiktoken_ext.openai_public",
        "--hidden-import", "imaplib",
        "--hidden-import", "smtplib",
        "--hidden-import", "email",

        # Inclure les dossiers de données
        "--add-data", "knowledge;knowledge",
        "--add-data", "agents;agents",

        # Script principal
        "run_daemon.py"
    ]

    # Ajouter l'icône si elle existe
    icon_path = "agentys-app/src-tauri/icons/icon.ico"
    if os.path.exists(icon_path):
        cmd.insert(-1, "--icon")
        cmd.insert(-1, icon_path)

    print(f"Commande: {' '.join(cmd)}")
    print()

    result = subprocess.run(cmd)

    if result.returncode == 0:
        print()
        print("=" * 50)
        print("✅ Build réussi !")
        print()
        print("L'exe est dans: dist/Agentys-Backend.exe")
        print()
        print("Pour distribuer, copier:")
        print("  - dist/Agentys-Backend.exe")
        print("  - .env (configuré)")
        print("  - knowledge/ (si personnalisé)")
        print("=" * 50)
    else:
        print("❌ Erreur de build")
        sys.exit(1)

if __name__ == "__main__":
    build()
