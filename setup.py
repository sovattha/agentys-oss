#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Assistant de configuration Agentys.

CLI interactive pour :
- Voir l'état de la configuration actuelle
- Configurer les providers email (Gmail, Outlook, IMAP/SMTP)
- Tester les connexions
"""

import os
import sys
import json
import webbrowser
from pathlib import Path
from typing import Optional, Dict, Tuple

# Ajouter le path du projet
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# Vérifier les dépendances
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env", override=True)
except ImportError:
    print("\n❌ Dépendances manquantes !")
    print("\nInstalle les dépendances avec :")
    print("\n  pip install -r requirements.txt\n")
    sys.exit(1)


# ============================================================================
# COULEURS ET AFFICHAGE
# ============================================================================

class C:
    """Couleurs ANSI."""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    END = '\033[0m'

def clear():
    os.system('clear' if os.name != 'nt' else 'cls')

def header(text: str):
    print(f"\n{C.BOLD}{C.CYAN}{'═' * 60}{C.END}")
    print(f"{C.BOLD}{C.CYAN}  {text}{C.END}")
    print(f"{C.BOLD}{C.CYAN}{'═' * 60}{C.END}\n")

def success(text: str):
    print(f"{C.GREEN}✓ {text}{C.END}")

def error(text: str):
    print(f"{C.RED}✗ {text}{C.END}")

def warning(text: str):
    print(f"{C.YELLOW}⚠ {text}{C.END}")

def info(text: str):
    print(f"{C.CYAN}ℹ {text}{C.END}")

def dim(text: str):
    print(f"{C.DIM}{text}{C.END}")

def ask(prompt: str, default: str = None) -> str:
    if default:
        result = input(f"{C.BOLD}{prompt}{C.END} [{default}]: ").strip()
        return result if result else default
    return input(f"{C.BOLD}{prompt}{C.END}: ").strip()

def ask_yes_no(prompt: str, default: bool = True) -> bool:
    suffix = "[O/n]" if default else "[o/N]"
    result = input(f"{prompt} {suffix}: ").strip().lower()
    if not result:
        return default
    return result in ['o', 'oui', 'y', 'yes']

def ask_choice(prompt: str, choices: list) -> int:
    print(f"\n{C.BOLD}{prompt}{C.END}\n")
    for i, choice in enumerate(choices, 1):
        print(f"  {C.CYAN}{i}.{C.END} {choice}")
    print()
    while True:
        try:
            result = input(f"Choix (1-{len(choices)}): ").strip()
            if not result:
                return 0
            idx = int(result)
            if 1 <= idx <= len(choices):
                return idx
        except ValueError:
            pass
        error("Choix invalide")

def press_enter():
    input(f"\n{C.DIM}Appuie sur Entrée pour continuer...{C.END}")


# ============================================================================
# DÉTECTION DE LA CONFIGURATION
# ============================================================================

def get_env(key: str) -> Optional[str]:
    """Récupère une variable d'environnement."""
    return os.getenv(key)

def mask_secret(value: str, show: int = 4) -> str:
    """Masque une valeur secrète."""
    if not value:
        return ""
    if len(value) <= show * 2:
        return "*" * len(value)
    return value[:show] + "..." + value[-show:]

def check_provider_config(provider: str) -> Dict[str, Tuple[bool, str]]:
    """Vérifie la configuration d'un provider."""
    configs = {
        "GMAIL": {
            "GOOGLE_CLIENT_ID": get_env("GOOGLE_CLIENT_ID"),
            "GOOGLE_CLIENT_SECRET": get_env("GOOGLE_CLIENT_SECRET"),
            "GOOGLE_REFRESH_TOKEN": get_env("GOOGLE_REFRESH_TOKEN"),
        },
        "OUTLOOK": {
            "AZURE_TENANT_ID": get_env("AZURE_TENANT_ID"),
            "AZURE_CLIENT_ID": get_env("AZURE_CLIENT_ID"),
            "AZURE_CLIENT_SECRET": get_env("AZURE_CLIENT_SECRET"),
            "OUTLOOK_USER_ID": get_env("OUTLOOK_USER_ID"),
        },
        "IMAP": {
            "IMAP_HOST": get_env("IMAP_HOST"),
            "IMAP_USER": get_env("IMAP_USER"),
            "IMAP_PASSWORD": get_env("IMAP_PASSWORD"),
        },
        "SMTP": {
            "SMTP_HOST": get_env("SMTP_HOST"),
            "SMTP_USER": get_env("SMTP_USER"),
            "SMTP_PASSWORD": get_env("SMTP_PASSWORD"),
        },
    }

    if provider not in configs:
        return {}

    result = {}
    for key, value in configs[provider].items():
        if value:
            result[key] = (True, mask_secret(value))
        else:
            result[key] = (False, "non configuré")

    return result

def get_current_provider() -> Optional[str]:
    """Retourne le provider actuellement configuré."""
    return get_env("EMAIL_PROVIDER_TYPE")

def is_provider_ready(provider: str) -> bool:
    """Vérifie si un provider est prêt à l'emploi."""
    config = check_provider_config(provider)
    return all(ok for ok, _ in config.values())


# ============================================================================
# AFFICHAGE DE L'ÉTAT
# ============================================================================

def show_status():
    """Affiche l'état actuel de la configuration."""
    clear()
    print(f"""
{C.BOLD}{C.CYAN}
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║               🔧 Agentys - Configuration                    ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
{C.END}""")

    # Provider LLM
    llm_provider = get_env("LLM_PROVIDER") or "claude"
    llm_model = get_env("LLM_MODEL") or "(défaut)"
    print(f"{C.BOLD}Provider LLM :{C.END} ", end="")
    if llm_provider.lower() == "ollama":
        print(f"{C.GREEN}Ollama{C.END} (local)")
        print(f"  Modèle : {C.CYAN}{llm_model}{C.END}")
    else:
        print(f"{C.BLUE}Claude{C.END} (Anthropic)")
        api_key = get_env("ANTHROPIC_API_KEY")
        if api_key:
            success(f"ANTHROPIC_API_KEY = {mask_secret(api_key)}")
        else:
            error("ANTHROPIC_API_KEY = non configurée")

    print()

    # Provider actuel
    current = get_current_provider()
    print(f"{C.BOLD}Provider actif :{C.END} ", end="")
    if current:
        if is_provider_ready(current):
            print(f"{C.GREEN}{current} ✓{C.END}")
        else:
            print(f"{C.YELLOW}{current} (incomplet){C.END}")
    else:
        print(f"{C.DIM}aucun{C.END}")

    print()

    # État de chaque provider
    print(f"{C.BOLD}Providers disponibles :{C.END}\n")

    providers = ["IMAP", "SMTP", "GMAIL", "OUTLOOK"]

    for provider in providers:
        config = check_provider_config(provider)
        ready = is_provider_ready(provider)
        active = current == provider

        # Icône de statut
        if ready:
            status = f"{C.GREEN}●{C.END}"
        elif any(ok for ok, _ in config.values()):
            status = f"{C.YELLOW}◐{C.END}"
        else:
            status = f"{C.DIM}○{C.END}"

        # Marqueur actif
        active_mark = f" {C.CYAN}← actif{C.END}" if active else ""

        print(f"  {status} {C.BOLD}{provider}{C.END}{active_mark}")

        for key, (ok, value) in config.items():
            if ok:
                print(f"      {C.GREEN}✓{C.END} {key} = {C.DIM}{value}{C.END}")
            else:
                print(f"      {C.RED}✗{C.END} {key}")
        print()


# ============================================================================
# CONFIGURATION GMAIL
# ============================================================================

def setup_gmail():
    """Configure Gmail pas à pas."""
    header("Configuration Gmail")

    print(f"""
Cette configuration nécessite de créer un projet Google Cloud.

{C.BOLD}Étapes :{C.END}
  1. Créer un projet sur Google Cloud Console
  2. Activer l'API Gmail
  3. Configurer OAuth (écran de consentement)
  4. Créer des identifiants OAuth
  5. Générer un token d'accès
""")

    if not ask_yes_no("Continuer?"):
        return

    # Étape 1 : Projet Google Cloud
    header("1/5 - Créer un projet Google Cloud")
    print(f"""
{C.BOLD}Actions :{C.END}
  1. Va sur {C.CYAN}https://console.cloud.google.com/{C.END}
  2. Clique sur le sélecteur de projet → "Nouveau projet"
  3. Nom : {C.BOLD}Agentys{C.END}
  4. Clique sur "Créer"
""")
    if ask_yes_no("Ouvrir Google Cloud Console?"):
        webbrowser.open("https://console.cloud.google.com/")
    press_enter()

    # Étape 2 : Activer l'API
    header("2/5 - Activer l'API Gmail")
    print(f"""
{C.BOLD}Actions :{C.END}
  1. Va sur {C.CYAN}https://console.cloud.google.com/apis/library/gmail.googleapis.com{C.END}
  2. Sélectionne ton projet "Agentys"
  3. Clique sur "Activer"
""")
    if ask_yes_no("Ouvrir la page API Gmail?"):
        webbrowser.open("https://console.cloud.google.com/apis/library/gmail.googleapis.com")
    press_enter()

    # Étape 3 : OAuth consent
    header("3/5 - Configurer OAuth")
    print(f"""
{C.BOLD}Actions :{C.END}
  1. Va sur {C.CYAN}https://console.cloud.google.com/apis/credentials/consent{C.END}
  2. Choisis "Externe" → "Créer"
  3. Remplis : Nom = Agentys, ton email
  4. Scopes : ajoute gmail.readonly, gmail.send, gmail.modify
  5. Utilisateurs test : ajoute ton email Gmail
""")
    if ask_yes_no("Ouvrir la page OAuth?"):
        webbrowser.open("https://console.cloud.google.com/apis/credentials/consent")
    press_enter()

    # Étape 4 : Créer credentials
    header("4/5 - Créer les identifiants")
    print(f"""
{C.BOLD}Actions :{C.END}
  1. Va sur {C.CYAN}https://console.cloud.google.com/apis/credentials{C.END}
  2. "+ Créer des identifiants" → "ID client OAuth"
  3. Type : "Application de bureau"
  4. Nom : "Agentys Desktop"
  5. {C.YELLOW}Note le Client ID et Client Secret !{C.END}
""")
    if ask_yes_no("Ouvrir la page Credentials?"):
        webbrowser.open("https://console.cloud.google.com/apis/credentials")
    press_enter()

    print(f"\n{C.BOLD}Entre les informations OAuth :{C.END}\n")
    client_id = ask("Client ID")
    client_secret = ask("Client Secret")

    if not client_id or not client_secret:
        error("Client ID et Secret requis")
        return

    # Étape 5 : Générer token
    header("5/5 - Générer le token")

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        error("google-auth-oauthlib non installé")
        info("Exécute : pip install google-auth google-auth-oauthlib google-api-python-client")
        return

    # Créer credentials temporaires
    creds_data = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"]
        }
    }

    temp_file = PROJECT_ROOT / ".temp_creds.json"
    temp_file.write_text(json.dumps(creds_data))

    try:
        SCOPES = [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.compose",
        ]

        info("Ouverture du navigateur pour authentification...")
        flow = InstalledAppFlow.from_client_secrets_file(str(temp_file), SCOPES)
        creds = flow.run_local_server(port=0)

        success("Token généré !")
        refresh_token = creds.refresh_token

    except Exception as e:
        error(f"Erreur : {e}")
        return
    finally:
        temp_file.unlink(missing_ok=True)

    # Sauvegarder
    save_config({
        "EMAIL_PROVIDER_TYPE": "GMAIL",
        "GOOGLE_CLIENT_ID": client_id,
        "GOOGLE_CLIENT_SECRET": client_secret,
        "GOOGLE_REFRESH_TOKEN": refresh_token,
    })

    success("Configuration Gmail terminée !")

    if ask_yes_no("\nTester la connexion?"):
        test_provider("GMAIL")


# ============================================================================
# CONFIGURATION IMAP/SMTP
# ============================================================================

def setup_imap_smtp():
    """Configure IMAP + SMTP."""
    header("Configuration IMAP/SMTP")

    print(f"""
Cette configuration fonctionne avec la plupart des serveurs email.

{C.BOLD}Serveurs courants :{C.END}
  • Gmail     : imap.gmail.com / smtp.gmail.com
  • Outlook   : outlook.office365.com
  • Yahoo     : imap.mail.yahoo.com / smtp.mail.yahoo.com
  • OVH       : ssl0.ovh.net

{C.YELLOW}Note : Pour Gmail/Yahoo, utilise un "App Password" (mot de passe d'application){C.END}
""")

    if not ask_yes_no("Continuer?"):
        return

    # Demander les infos
    print(f"\n{C.BOLD}Configuration IMAP (lecture) :{C.END}\n")
    imap_host = ask("Serveur IMAP", "imap.gmail.com")
    imap_port = ask("Port IMAP", "993")
    imap_user = ask("Email / Utilisateur")
    imap_password = ask("Mot de passe (ou App Password)")

    print(f"\n{C.BOLD}Configuration SMTP (envoi) :{C.END}\n")
    smtp_host = ask("Serveur SMTP", "smtp.gmail.com")
    smtp_port = ask("Port SMTP", "587")
    smtp_user = ask("Email (si différent)", imap_user)
    smtp_password = ask("Mot de passe (si différent)", imap_password)

    # Sauvegarder
    save_config({
        "EMAIL_PROVIDER_TYPE": "IMAP_SMTP",
        "IMAP_HOST": imap_host,
        "IMAP_PORT": imap_port,
        "IMAP_USER": imap_user,
        "IMAP_PASSWORD": imap_password,
        "IMAP_USE_SSL": "true",
        "SMTP_HOST": smtp_host,
        "SMTP_PORT": smtp_port,
        "SMTP_USER": smtp_user,
        "SMTP_PASSWORD": smtp_password,
        "SMTP_USE_TLS": "true",
    })

    success("Configuration IMAP/SMTP terminée !")

    if ask_yes_no("\nTester la connexion?"):
        test_provider("IMAP_SMTP")


# ============================================================================
# CONFIGURATION LLM (CLAUDE / OLLAMA)
# ============================================================================

def setup_llm():
    """Configure le provider LLM."""
    header("Configuration du moteur IA")

    print(f"""
{C.BOLD}Choisissez le moteur IA à utiliser :{C.END}

  {C.BLUE}Claude{C.END} (Anthropic)
    • Modèles cloud très performants
    • Nécessite une clé API
    • Coût à l'usage

  {C.GREEN}Ollama{C.END} (Local)
    • Modèles locaux gratuits
    • Pas de clé API requise
    • Nécessite Ollama installé
""")

    choice = ask_choice("Quel provider utiliser ?", [
        "Claude (Anthropic) - cloud, haute qualité",
        "Ollama (Local) - gratuit, sans API"
    ])

    if choice == 1:
        setup_claude()
    elif choice == 2:
        setup_ollama()


def setup_claude():
    """Configure Claude (Anthropic)."""
    header("Configuration Claude (Anthropic)")

    print(f"""
{C.BOLD}Pour obtenir une clé API :{C.END}
  1. Va sur {C.CYAN}https://console.anthropic.com/{C.END}
  2. Crée un compte ou connecte-toi
  3. Va dans "API Keys"
  4. Crée une nouvelle clé
""")

    if ask_yes_no("Ouvrir la console Anthropic?"):
        webbrowser.open("https://console.anthropic.com/")

    print()
    api_key = ask("Clé API Anthropic (sk-ant-...)")

    if not api_key:
        error("Clé requise")
        return

    # Choix du modèle
    print(f"\n{C.BOLD}Modèle par défaut :{C.END}\n")
    model_choice = ask_choice("Quel modèle utiliser ?", [
        "claude-opus-4-7 (le plus intelligent)",
        "claude-sonnet-4-6 (équilibré, recommandé)",
        "claude-haiku-4-5-20251001 (rapide et économique)"
    ])

    models = {
        1: "claude-opus-4-7",
        2: "claude-sonnet-4-6",
        3: "claude-haiku-4-5-20251001"
    }
    model = models.get(model_choice, "claude-sonnet-4-6")

    save_config({
        "LLM_PROVIDER": "claude",
        "LLM_MODEL": model,
        "ANTHROPIC_API_KEY": api_key
    })
    success(f"Claude configuré avec {model} !")


def setup_ollama():
    """Configure Ollama (modèles locaux)."""
    header("Configuration Ollama")

    # Vérifier si Ollama est installé
    import subprocess
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            raise Exception("Ollama non démarré")
        models_output = result.stdout
    except FileNotFoundError:
        error("Ollama n'est pas installé !")
        print(f"""
{C.BOLD}Pour installer Ollama :{C.END}
  1. Va sur {C.CYAN}https://ollama.ai{C.END}
  2. Télécharge et installe Ollama
  3. Lance : {C.CYAN}ollama pull mixtral{C.END}
""")
        if ask_yes_no("Ouvrir ollama.ai ?"):
            webbrowser.open("https://ollama.ai")
        return
    except Exception as e:
        error(f"Ollama n'est pas démarré : {e}")
        info("Lance : ollama serve")
        return

    # Afficher les modèles disponibles
    print(f"\n{C.BOLD}Modèles disponibles :{C.END}\n")
    print(f"{C.DIM}{models_output}{C.END}")

    # Extraire les noms des modèles
    available_models = []
    for line in models_output.strip().split("\n")[1:]:  # Skip header
        if line.strip():
            model_name = line.split()[0]
            available_models.append(model_name)

    if not available_models:
        warning("Aucun modèle installé !")
        print(f"\n{C.BOLD}Installe un modèle :{C.END}")
        print(f"  {C.CYAN}ollama pull mixtral{C.END}")
        print(f"  {C.CYAN}ollama pull llama3.3{C.END}")
        print(f"  {C.CYAN}ollama pull mistral{C.END}")
        return

    # Choix du modèle
    model_choice = ask_choice("Quel modèle utiliser ?", available_models)
    if model_choice == 0:
        return

    model = available_models[model_choice - 1]

    save_config({
        "LLM_PROVIDER": "ollama",
        "LLM_MODEL": model
    })
    success(f"Ollama configuré avec {model} !")

    # Test rapide
    if ask_yes_no("\nTester le modèle ?"):
        test_llm()


def test_llm():
    """Teste le provider LLM configuré."""
    header("Test du moteur IA")

    try:
        # Import dynamique pour éviter les erreurs de config
        import sys
        sys.path.insert(0, str(PROJECT_ROOT))

        from app.llm import get_llm_provider

        llm_provider = get_env("LLM_PROVIDER") or "claude"
        info(f"Provider : {llm_provider}")

        provider = get_llm_provider()
        info(f"Modèle : {provider.model}")

        info("Test en cours...")
        response = provider.complete(
            system="Tu es un assistant amical.",
            user="Dis 'Bonjour' en une seule phrase.",
            max_tokens=50
        )

        success("Réponse reçue !")
        print(f"\n  {C.CYAN}{response.content}{C.END}\n")
        print(f"{C.DIM}Tokens : {response.input_tokens}↓ {response.output_tokens}↑{C.END}")

    except Exception as e:
        error(f"Erreur : {e}")


def setup_anthropic():
    """Configure la clé API Anthropic (alias pour compatibilité)."""
    setup_claude()


# ============================================================================
# SAUVEGARDE
# ============================================================================

def save_config(values: Dict[str, str]):
    """Sauvegarde les valeurs dans .env"""
    env_file = PROJECT_ROOT / ".env"

    # Lire le contenu existant
    existing = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                existing[key.strip()] = value.strip()

    # Mettre à jour
    existing.update(values)

    # Écrire
    lines = []
    for key, value in existing.items():
        lines.append(f"{key}={value}")

    env_file.write_text("\n".join(lines) + "\n")

    # Recharger
    load_dotenv(env_file, override=True)

    info(f"Configuration sauvegardée dans {env_file}")


# ============================================================================
# TEST DE CONNEXION
# ============================================================================

def test_provider(provider: str = None):
    """Teste la connexion au provider."""
    if not provider:
        provider = get_current_provider()

    if not provider:
        error("Aucun provider configuré")
        return

    header(f"Test de connexion {provider}")

    try:
        from app.providers.factory import get_email_provider

        info("Création du provider...")
        p = get_email_provider(provider)

        info("Authentification...")
        if p.authenticate():
            success("Authentification réussie !")

            info("Récupération des emails...")
            emails = p.get_unread_messages(limit=5)

            if emails:
                success(f"{len(emails)} email(s) non lu(s) :")
                for e in emails[:3]:
                    print(f"  • {e.sender}: {e.subject[:40]}...")
            else:
                info("Aucun email non lu")

            return True
        else:
            error("Échec de l'authentification")
            return False

    except Exception as e:
        error(f"Erreur : {e}")
        return False


# ============================================================================
# SCAN DES EMAILS AVEC RÉPONSES
# ============================================================================

def extract_email_body_with_llm(raw_email: str, provider, is_reply: bool = False) -> tuple:
    """
    Utilise le LLM pour extraire uniquement le texte principal d'un email.
    Supprime citations, headers, signatures, etc.

    Args:
        raw_email: Le corps brut de l'email
        provider: Provider LLM (Claude ou Ollama)
        is_reply: True si c'est une réponse (on cherche ce que l'auteur a rédigé)

    Returns:
        tuple: (texte_extrait, erreur_eventuelle, input_tokens, output_tokens)
    """
    if not raw_email or len(raw_email.strip()) < 10:
        return "", "Email trop court", 0, 0

    context = "cette réponse email" if is_reply else "cet email"

    system_prompt = "Tu es un extracteur de contenu email. Réponds uniquement avec le texte extrait, sans explications."

    user_prompt = f"""Extrait UNIQUEMENT le message principal de {context}.

SUPPRIME :
- Les citations (lignes avec ">", texte des emails précédents)
- Les headers (De:, À:, Objet:, Date:, From:, To:, Sent:, etc.)
- Les blocs "Le XX a écrit :", "On XX wrote:", "-----Original Message-----"
- La signature (Cordialement, --, nom, coordonnées, téléphone)
- Les disclaimers légaux / confidentialité
- Les images/pièces jointes mentionnées ([image], [cid:])
- Les liens mailto:

GARDE UNIQUEMENT le message rédigé par l'auteur.

Si tu ne trouves pas de contenu, réponds uniquement: VIDE

EMAIL BRUT :
\"\"\"
{raw_email[:4000]}
\"\"\"

TEXTE EXTRAIT :"""

    try:
        response = provider.complete(
            system=system_prompt,
            user=user_prompt,
            max_tokens=1500
        )
        result = response.content.strip()

        # Nettoyer les guillemets éventuels
        if result.startswith('"') and result.endswith('"'):
            result = result[1:-1]
        if result.startswith("```") and result.endswith("```"):
            result = result[3:-3].strip()

        if result.upper() == "VIDE" or len(result) < 5:
            return "", "Contenu vide", 0, 0

        return result, None, response.input_tokens, response.output_tokens
    except Exception as e:
        return "", str(e), 0, 0


def scan_emails_with_replies():
    """Scanne les réponses (RE:) et les exporte."""
    header("Scanner les emails avec réponses")

    print(f"""
Cette fonction va :
  1. Récupérer vos réponses (emails RE:)
  2. Extraire l'email reçu + votre réponse (nettoyée)
  3. Sauvegarder dans {C.CYAN}data/inputs/emails_corpus.xlsx{C.END}

Ce corpus servira à entraîner l'IA sur votre style.
""")

    limit = ask("Nombre de réponses à scanner", "100")
    try:
        limit = int(limit)
    except ValueError:
        limit = 100

    if not ask_yes_no(f"Scanner les {limit} dernières réponses ?"):
        return

    try:
        from app.providers.factory import get_email_provider
        from app.llm import get_llm_provider
        import pandas as pd

        info("Connexion au provider email...")
        email_provider = get_email_provider()

        if not email_provider.authenticate():
            error("Échec authentification")
            return

        llm_provider = get_llm_provider()
        llm_name = get_env("LLM_PROVIDER") or "claude"
        info(f"Initialisation de {llm_name} ({llm_provider.model})...")

        info("Récupération des emails envoyés...")

        # Récupérer tous les emails envoyés (on filtrera par thread ensuite)
        service = email_provider._service
        results = service.users().messages().list(
            userId="me",
            q="in:sent",
            maxResults=limit
        ).execute()

        sent_messages = results.get("messages", [])
        info(f"{len(sent_messages)} emails envoyés trouvés (filtrage par conversation...)")

        corpus = []
        seen_threads = set()
        skipped_no_conversation = 0
        total_input_tokens = 0
        total_output_tokens = 0

        for msg_ref in sent_messages:
            try:
                # Récupérer le message envoyé
                sent_msg = service.users().messages().get(
                    userId="me",
                    id=msg_ref["id"],
                    format="full"
                ).execute()

                thread_id = sent_msg.get("threadId")

                # Éviter les doublons de thread
                if thread_id in seen_threads:
                    continue
                seen_threads.add(thread_id)

                # Récupérer le thread complet
                thread = service.users().threads().get(
                    userId="me",
                    id=thread_id,
                    format="full"
                ).execute()

                messages = thread.get("messages", [])
                if len(messages) < 2:
                    skipped_no_conversation += 1
                    continue

                # Trouver ma réponse et l'email auquel je réponds
                for i, msg in enumerate(messages):
                    if msg.get("id") == msg_ref["id"]:
                        # C'est ma réponse, chercher l'email précédent
                        if i > 0:
                            prev_msg = messages[i - 1]
                            prev_labels = prev_msg.get("labelIds", [])

                            # Vérifier que le précédent n'est pas de moi
                            if "SENT" not in prev_labels:
                                # Extraire les contenus bruts
                                received_email = email_provider._map_to_standard_email(prev_msg)
                                my_reply = email_provider._map_to_standard_email(msg)

                                # Nettoyer l'email reçu avec le LLM
                                cleaned_received, err1, in1, out1 = extract_email_body_with_llm(
                                    received_email.body, llm_provider, is_reply=False
                                )
                                total_input_tokens += in1
                                total_output_tokens += out1

                                if not cleaned_received:
                                    print(f"\r  {C.YELLOW}⚠{C.END} Email reçu vide: {err1} - {received_email.subject[:30]}...", end="\n")
                                    continue

                                # Nettoyer ma réponse avec le LLM
                                cleaned_reply, err2, in2, out2 = extract_email_body_with_llm(
                                    my_reply.body, llm_provider, is_reply=True
                                )
                                total_input_tokens += in2
                                total_output_tokens += out2

                                if not cleaned_reply:
                                    print(f"\r  {C.YELLOW}⚠{C.END} Réponse vide: {err2} - {my_reply.subject[:30]}...", end="\n")
                                    continue

                                corpus.append({
                                    "Numéro": len(corpus) + 1,
                                    "E-mail reçu": f"De: {received_email.sender}\nSujet: {received_email.subject}\n\n{cleaned_received}",
                                    "Réponse": cleaned_reply
                                })

                                print(f"\r  {C.GREEN}✓{C.END} {len(corpus)} conversations | {skipped_no_conversation} ignorés | Tokens: {total_input_tokens:,}↓ {total_output_tokens:,}↑", end="", flush=True)
                        break

            except Exception as e:
                print(f"\r  {C.RED}✗{C.END} Erreur: {e}", end="\n")
                continue

        print()

        if not corpus:
            warning("Aucune réponse trouvée")
            return

        # Sauvegarder en Excel
        output_dir = PROJECT_ROOT / "data" / "inputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "emails_corpus.xlsx"

        df = pd.DataFrame(corpus)
        df.to_excel(output_file, index=False)

        success(f"{len(corpus)} conversations extraites ({skipped_no_conversation} emails sans réponse ignorés)")
        print(f"  {C.CYAN}{output_file}{C.END}")

        # Afficher le total des tokens
        total_tokens = total_input_tokens + total_output_tokens
        # Coût Haiku: $0.25/1M input, $1.25/1M output
        cost = (total_input_tokens * 0.25 + total_output_tokens * 1.25) / 1_000_000
        print(f"\n{C.DIM}Tokens utilisés : {total_input_tokens:,}↓ + {total_output_tokens:,}↑ = {total_tokens:,}{C.END}")
        print(f"{C.DIM}Coût estimé : ${cost:.4f}{C.END}")

    except ImportError as e:
        error(f"Module manquant : {e}")
        info("Exécute : pip install pandas openpyxl")
    except Exception as e:
        error(f"Erreur : {e}")


def create_knowledge_base_wizard():
    """Crée la base de connaissances via un wizard interactif."""
    header("Créer la base de connaissances")

    memoire_file = PROJECT_ROOT / "knowledge" / "memoire.md"

    if memoire_file.exists():
        warning(f"Le fichier {memoire_file} existe déjà.")
        if not ask_yes_no("Voulez-vous le remplacer ?", default=False):
            return

    print(f"""
Ce wizard va vous poser des questions pour créer votre base de connaissances.
L'IA utilisera ces informations pour rédiger des réponses cohérentes.

{C.DIM}Appuyez sur Entrée pour passer une question.{C.END}
""")

    if not ask_yes_no("Commencer ?"):
        return

    # Questions du wizard
    print(f"\n{C.BOLD}═══ Identité ═══{C.END}\n")

    nom = ask("Votre nom complet")
    poste = ask("Votre poste / fonction")
    entreprise = ask("Nom de l'entreprise / organisation")
    secteur = ask("Secteur d'activité", "")

    print(f"\n{C.BOLD}═══ Contact ═══{C.END}\n")

    email_pro = ask("Email professionnel", "")
    telephone = ask("Téléphone (optionnel)", "")
    site_web = ask("Site web (optionnel)", "")

    print(f"\n{C.BOLD}═══ Style de communication ═══{C.END}\n")

    tutoiement = ask_choice("Comment vous adressez-vous aux interlocuteurs ?", [
        "Vouvoiement systématique",
        "Tutoiement avec les collègues, vouvoiement avec les clients",
        "Tutoiement généralement",
        "Ça dépend du contexte (l'IA s'adaptera)"
    ])
    style_map = {1: "vouvoiement", 2: "mixte", 3: "tutoiement", 4: "adaptatif"}
    style_tutoiement = style_map.get(tutoiement, "adaptatif")

    ton = ask_choice("Quel ton général adoptez-vous ?", [
        "Très formel et professionnel",
        "Professionnel mais chaleureux",
        "Décontracté et amical",
        "Variable selon le contexte"
    ])
    ton_map = {1: "formel", 2: "professionnel-chaleureux", 3: "décontracté", 4: "adaptatif"}
    style_ton = ton_map.get(ton, "professionnel-chaleureux")

    signature = ask("Formule de politesse préférée", "Cordialement")

    print(f"\n{C.BOLD}═══ Services / Produits ═══{C.END}\n")

    print(f"{C.DIM}Décrivez brièvement vos services/produits (une ligne par service, ligne vide pour terminer):{C.END}")
    services = []
    while True:
        service = input("  • ").strip()
        if not service:
            break
        services.append(service)

    print(f"\n{C.BOLD}═══ Règles métier ═══{C.END}\n")

    print(f"{C.DIM}Y a-t-il des règles importantes à respecter ? (une par ligne, ligne vide pour terminer):{C.END}")
    print(f"{C.DIM}Ex: \"Ne jamais donner de prix sans devis\", \"Toujours proposer un RDV\"{C.END}")
    regles = []
    while True:
        regle = input("  • ").strip()
        if not regle:
            break
        regles.append(regle)

    print(f"\n{C.BOLD}═══ Informations à ne pas divulguer ═══{C.END}\n")

    print(f"{C.DIM}Quelles informations ne doivent JAMAIS être partagées ? (ligne vide pour terminer):{C.END}")
    interdits = []
    while True:
        interdit = input("  • ").strip()
        if not interdit:
            break
        interdits.append(interdit)

    print(f"\n{C.BOLD}═══ Phrases types ═══{C.END}\n")

    print(f"{C.DIM}Avez-vous des phrases types que vous utilisez souvent ? (ligne vide pour terminer):{C.END}")
    phrases = []
    while True:
        phrase = input("  • ").strip()
        if not phrase:
            break
        phrases.append(phrase)

    # Génération du fichier
    print(f"\n{C.BOLD}Génération de la base de connaissances...{C.END}\n")

    content = f"""# Base de Connaissances - {entreprise or "Mon Organisation"}

## Identité

"""
    if nom:
        content += f"- **Nom** : {nom}\n"
    if poste:
        content += f"- **Fonction** : {poste}\n"
    if entreprise:
        content += f"- **Organisation** : {entreprise}\n"
    if secteur:
        content += f"- **Secteur** : {secteur}\n"

    content += "\n## Coordonnées\n\n"
    if email_pro:
        content += f"- Email : {email_pro}\n"
    if telephone:
        content += f"- Téléphone : {telephone}\n"
    if site_web:
        content += f"- Site web : {site_web}\n"

    content += f"""
## Style de Communication

- **Adresse** : {style_tutoiement}
- **Ton** : {style_ton}
- **Signature** : {signature}

## Règles de Rédaction

- Répondre dans la même langue que l'email reçu
- Être concis et aller à l'essentiel
- Ne jamais inventer d'informations
"""

    if services:
        content += "\n## Services / Produits\n\n"
        for s in services:
            content += f"- {s}\n"

    if regles:
        content += "\n## Règles Métier\n\n"
        for r in regles:
            content += f"- {r}\n"

    if interdits:
        content += "\n## Informations Confidentielles (NE PAS DIVULGUER)\n\n"
        for i in interdits:
            content += f"- ❌ {i}\n"

    if phrases:
        content += "\n## Phrases Types\n\n"
        for p in phrases:
            content += f"- \"{p}\"\n"

    content += """
## Instructions pour l'IA

1. Utiliser les informations ci-dessus pour personnaliser les réponses
2. Respecter le ton et le style de communication définis
3. Ne jamais révéler les informations confidentielles
4. En cas de doute, rester vague plutôt qu'inventer
5. Proposer un suivi ou une action concrète quand c'est pertinent
"""

    # Sauvegarder
    memoire_file.parent.mkdir(parents=True, exist_ok=True)
    memoire_file.write_text(content, encoding="utf-8")

    success("Base de connaissances créée !")
    print(f"  {C.CYAN}{memoire_file}{C.END}")

    print(f"\n{C.BOLD}Aperçu :{C.END}")
    print(f"{C.DIM}{content[:800]}...{C.END}" if len(content) > 800 else f"{C.DIM}{content}{C.END}")

    print(f"\n{C.BOLD}Vous pouvez éditer ce fichier manuellement pour l'affiner.{C.END}")


def update_knowledge_base():
    """Analyse le corpus d'emails pour enrichir la base de connaissances."""
    header("Mettre à jour la base de connaissances")

    corpus_file = PROJECT_ROOT / "data" / "inputs" / "emails_corpus.xlsx"
    memoire_file = PROJECT_ROOT / "knowledge" / "memoire.md"

    if not corpus_file.exists():
        error(f"Corpus non trouvé : {corpus_file}")
        info("Lance d'abord 'Scanner les emails avec réponses'")
        return

    print(f"""
Cette fonction va :
  1. Analyser le corpus {C.CYAN}emails_corpus.xlsx{C.END}
  2. Extraire votre style d'écriture et patterns de réponse
  3. Enrichir {C.CYAN}knowledge/memoire.md{C.END}
""")

    if not ask_yes_no("Continuer ?"):
        return

    try:
        import pandas as pd
        from app.llm import get_llm_provider

        # Charger le corpus
        df = pd.read_excel(corpus_file)
        info(f"{len(df)} conversations chargées")

        # Charger la mémoire existante
        existing_memory = ""
        if memoire_file.exists():
            existing_memory = memoire_file.read_text()
            info(f"Mémoire existante : {len(existing_memory)} caractères")

        # Préparer le prompt
        samples = df.head(20).to_dict('records')
        samples_text = "\n\n---\n\n".join([
            f"EMAIL REÇU:\n{s['E-mail reçu']}\n\nRÉPONSE:\n{s['Réponse']}"
            for s in samples
        ])

        system_prompt = """Tu es un expert en analyse de communication écrite.
Analyse les exemples d'emails fournis et génère une base de connaissances structurée."""

        user_prompt = f"""Analyse ces exemples d'emails et de réponses pour extraire :

1. **Ton et style** : Comment la personne s'exprime (formel/informel, tutoiement/vouvoiement)
2. **Patterns de réponse** : Structures récurrentes, formules de politesse
3. **Sujets fréquents** : Types de demandes et comment elles sont traitées
4. **Règles implicites** : Ce qui est accepté/refusé, conditions, exceptions

EXEMPLES D'EMAILS ET RÉPONSES :
{samples_text}

BASE DE CONNAISSANCES EXISTANTE :
{existing_memory if existing_memory else "(vide)"}

Génère une base de connaissances mise à jour au format Markdown qui :
- Conserve les informations existantes pertinentes
- Ajoute les nouveaux patterns découverts
- Reste concis et actionnable pour un agent IA

Réponds UNIQUEMENT avec le contenu Markdown, sans commentaires."""

        # Utiliser le provider LLM configuré
        provider = get_llm_provider()
        llm_name = get_env("LLM_PROVIDER") or "claude"
        info(f"Analyse avec {llm_name} ({provider.model})...")

        response = provider.complete(
            system=system_prompt,
            user=user_prompt,
            max_tokens=4000
        )

        new_memory = response.content

        # Backup de l'ancienne mémoire
        if memoire_file.exists():
            backup_file = memoire_file.with_suffix(".md.backup")
            backup_file.write_text(existing_memory)
            info(f"Backup créé : {backup_file}")

        # Sauvegarder la nouvelle mémoire
        memoire_file.parent.mkdir(parents=True, exist_ok=True)
        memoire_file.write_text(new_memory)

        success("Base de connaissances mise à jour !")
        print(f"  {C.CYAN}{memoire_file}{C.END}")
        print(f"\n{C.DIM}Aperçu :{C.END}")
        print(new_memory[:500] + "..." if len(new_memory) > 500 else new_memory)

    except ImportError as e:
        error(f"Module manquant : {e}")
    except Exception as e:
        error(f"Erreur : {e}")


# ============================================================================
# RESET CONFIGURATION
# ============================================================================

def test_agents():
    """Teste le pipeline DrafterAgent + CriticAgent avec un email exemple."""
    header("Test des agents IA")

    print(f"""
Ce test va :
  1. Envoyer un email exemple au {C.CYAN}DrafterAgent{C.END}
  2. Faire évaluer la réponse par le {C.CYAN}CriticAgent{C.END}
  3. Corriger si nécessaire (pipeline complet)
""")

    # Email de test personnalisable
    default_email = """De: client@example.com
Sujet: Question sur vos services

Bonjour,

Je suis intéressé par vos services et j'aimerais avoir plus d'informations sur vos tarifs et délais.

Pouvez-vous me faire parvenir une brochure ?

Cordialement,
Jean Dupont"""

    use_custom = ask_yes_no("Utiliser un email personnalisé ?", default=False)

    if use_custom:
        print(f"\n{C.BOLD}Entrez l'email de test (terminez par une ligne vide) :{C.END}")
        lines = []
        while True:
            line = input()
            if not line:
                break
            lines.append(line)
        test_email = "\n".join(lines) if lines else default_email
    else:
        test_email = default_email

    print(f"\n{C.BOLD}Email de test :{C.END}")
    print(f"{C.DIM}{test_email}{C.END}")

    if not ask_yes_no("\nLancer le test ?"):
        return

    try:
        from app.agents import DrafterAgent, CriticAgent, token_counter
        from app.infrastructure.container import reset_container

        # Reset le container pour prendre en compte la config actuelle
        reset_container()

        llm_provider = get_env("LLM_PROVIDER") or "claude"
        info(f"Provider IA : {llm_provider}")

        # Créer les agents
        info("Création des agents...")
        drafter = DrafterAgent()
        critic = CriticAgent()

        # Étape 1 : Draft V1
        info("DrafterAgent génère la réponse V1...")
        draft_v1 = drafter.draft(test_email)

        print(f"\n{C.BOLD}📝 Draft V1 :{C.END}")
        print(f"{C.CYAN}{draft_v1}{C.END}")

        # Étape 2 : Critique
        info("\nCriticAgent évalue la réponse...")
        critique = critic.evaluate(test_email, draft_v1)

        print(f"\n{C.BOLD}🔍 Critique :{C.END}")
        if critic.is_valid(critique):
            print(f"{C.GREEN}{critique}{C.END}")
            status = "VALIDÉ V1"
        else:
            print(f"{C.YELLOW}{critique}{C.END}")

            # Étape 3 : Correction
            info("\nDrafterAgent corrige la réponse...")
            draft_v2 = drafter.revise(test_email, critique)

            print(f"\n{C.BOLD}📝 Draft V2 (corrigé) :{C.END}")
            print(f"{C.CYAN}{draft_v2}{C.END}")
            status = "CORRIGÉ V2"

        # Résumé
        print(f"\n{C.BOLD}{'═' * 50}{C.END}")
        print(f"{C.BOLD}Résultat :{C.END} {C.GREEN}{status}{C.END}")
        print(f"{C.BOLD}Tokens :{C.END} {token_counter}")

        success("Test des agents terminé !")

    except Exception as e:
        error(f"Erreur : {e}")
        import traceback
        traceback.print_exc()


def reset_config():
    """Supprime les fichiers de configuration pour revenir à zéro."""
    header("Réinitialiser la configuration")

    print(f"""
{C.YELLOW}Attention :{C.END} Cette action va supprimer :

  • {C.CYAN}.env{C.END} - Clés API et configuration
  • {C.CYAN}knowledge/memoire.md{C.END} - Base de connaissances
  • {C.CYAN}data/outputs/*{C.END} - Rapports générés

{C.DIM}Les fichiers de corpus (data/inputs) ne seront pas supprimés.{C.END}
""")

    if not ask_yes_no("Confirmer la réinitialisation ?", default=False):
        info("Annulé")
        return

    deleted = []

    # Supprimer .env
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        env_file.unlink()
        deleted.append(".env")

    # Supprimer memoire.md
    memoire_file = PROJECT_ROOT / "knowledge" / "memoire.md"
    if memoire_file.exists():
        memoire_file.unlink()
        deleted.append("knowledge/memoire.md")

    # Supprimer les outputs
    outputs_dir = PROJECT_ROOT / "data" / "outputs"
    if outputs_dir.exists():
        for f in outputs_dir.glob("*"):
            if f.is_file():
                f.unlink()
                deleted.append(f"data/outputs/{f.name}")

    if deleted:
        success(f"{len(deleted)} fichier(s) supprimé(s) :")
        for f in deleted:
            print(f"  {C.DIM}• {f}{C.END}")
    else:
        info("Aucun fichier à supprimer")

    print(f"\n{C.BOLD}Relance setup.py pour reconfigurer.{C.END}")


# ============================================================================
# MENU PRINCIPAL
# ============================================================================

def main_menu():
    """Menu principal avec options groupées."""
    while True:
        show_status()

        current = get_current_provider()
        llm_provider = get_env("LLM_PROVIDER") or "claude"
        email_ready = current and is_provider_ready(current)

        # Construction du menu groupé
        print(f"\n{C.BOLD}Que veux-tu faire ?{C.END}\n")

        # Groupe 1 : Configuration
        print(f"  {C.CYAN}Configuration{C.END}")
        print(f"    {C.BOLD}1.{C.END} Moteur IA (Claude/Ollama)")
        print(f"    {C.BOLD}2.{C.END} Email - IMAP/SMTP (recommandé)")
        print(f"    {C.BOLD}3.{C.END} Email - Gmail (OAuth)")
        print(f"    {C.BOLD}4.{C.END} Créer la base de connaissances (wizard)")

        # Groupe 2 : Tests
        print(f"\n  {C.CYAN}Tests{C.END}")
        print(f"    {C.BOLD}5.{C.END} Tester le moteur IA ({llm_provider})")
        print(f"    {C.BOLD}6.{C.END} Tester les agents (Drafter + Critic)")
        if email_ready:
            print(f"    {C.BOLD}7.{C.END} Tester la connexion email ({current})")
        else:
            print(f"    {C.DIM}7. Tester la connexion email (non configuré){C.END}")

        # Groupe 3 : Données
        print(f"\n  {C.CYAN}Données{C.END}")
        if email_ready:
            print(f"    {C.BOLD}8.{C.END} Scanner les emails (créer corpus)")
            print(f"    {C.BOLD}9.{C.END} Enrichir la base avec le corpus")
        else:
            print(f"    {C.DIM}8. Scanner les emails (configurez l'email d'abord){C.END}")
            print(f"    {C.DIM}9. Enrichir la base avec le corpus{C.END}")

        # Groupe 4 : Actions
        print(f"\n  {C.CYAN}Actions{C.END}")
        if email_ready:
            print(f"    {C.BOLD}d.{C.END} Lancer le daemon")
        else:
            print(f"    {C.DIM}d. Lancer le daemon (configurez l'email d'abord){C.END}")
        print(f"    {C.BOLD}r.{C.END} Réinitialiser (tout effacer)")
        print(f"    {C.BOLD}0.{C.END} Quitter")

        print()

        # Saisie du choix
        choice_str = input("Choix (0-9, d, r): ").strip().lower()
        if not choice_str:
            continue

        # Actions
        if choice_str == "0":
            print("\nÀ bientôt !\n")
            break
        elif choice_str == "1":
            setup_llm()
            press_enter()
        elif choice_str == "2":
            setup_imap_smtp()
            press_enter()
        elif choice_str == "3":
            setup_gmail()
            press_enter()
        elif choice_str == "4":
            create_knowledge_base_wizard()
            press_enter()
        elif choice_str == "5":
            test_llm()
            press_enter()
        elif choice_str == "6":
            test_agents()
            press_enter()
        elif choice_str == "7":
            if email_ready:
                test_provider()
            else:
                warning("Configure d'abord un provider email (option 2 ou 3)")
            press_enter()
        elif choice_str == "8":
            if email_ready:
                scan_emails_with_replies()
            else:
                warning("Configure d'abord un provider email (option 2 ou 3)")
            press_enter()
        elif choice_str == "9":
            if email_ready:
                update_knowledge_base()
            else:
                warning("Configure d'abord un provider email (option 2 ou 3)")
            press_enter()
        elif choice_str == "d":
            if email_ready:
                print(f"\n{C.BOLD}Lance le daemon avec :{C.END}")
                print("\n  python run_daemon.py\n")
            else:
                warning("Configure d'abord un provider email (option 2 ou 3)")
            press_enter()
        elif choice_str == "r":
            reset_config()
            press_enter()
        else:
            error("Choix invalide")


def main():
    """Point d'entrée."""
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "--status":
            show_status()
        elif cmd == "--test":
            test_provider()
        else:
            print("Usage: python setup.py [--status|--test]")
    else:
        main_menu()


if __name__ == "__main__":
    main()
