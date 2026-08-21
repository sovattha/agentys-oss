#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Script de lancement du dashboard Agentys.

Usage:
    python run_dashboard.py              # Lance sur localhost:5050
    python run_dashboard.py --port 8080  # Lance sur port personnalisé
    python run_dashboard.py --public     # Accessible depuis le réseau
"""

import argparse
import sys
from pathlib import Path

# Ajouter le répertoire racine au path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="Lance le dashboard Agentys")
    parser.add_argument("--port", type=int, default=5050, help="Port du serveur (défaut: 5050)")
    parser.add_argument("--public", action="store_true", help="Rendre accessible sur le réseau")
    parser.add_argument("--debug", action="store_true", help="Mode debug Flask")
    args = parser.parse_args()

    host = "0.0.0.0" if args.public else "127.0.0.1"

    from app.dashboard import run_dashboard
    run_dashboard(host=host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
