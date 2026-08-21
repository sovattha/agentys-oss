#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Wizard de Configuration Entreprise Agentys.

CLI interactive pour configurer Agentys pour une entreprise :
- Informations entreprise (secteur, taille, langues)
- Activation/désactivation des agents
- Import de la knowledge base
- Packs préconfigurés (Startup, PME, Enterprise, SaaS, E-commerce, B2B)
"""

import os
import sys
from pathlib import Path
from typing import Optional, List

# Ajouter le path du projet
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# Vérifier les dépendances
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env", override=True)
except ImportError:
    print("\n[ERREUR] Dependances manquantes !")
    print("\nInstalle les dependances avec :")
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
    print(f"\n{C.BOLD}{C.CYAN}{'=' * 60}{C.END}")
    print(f"{C.BOLD}{C.CYAN}  {text}{C.END}")
    print(f"{C.BOLD}{C.CYAN}{'=' * 60}{C.END}\n")


def success(text: str):
    print(f"{C.GREEN}[OK] {text}{C.END}")


def error(text: str):
    print(f"{C.RED}[ERREUR] {text}{C.END}")


def warning(text: str):
    print(f"{C.YELLOW}[ATTENTION] {text}{C.END}")


def info(text: str):
    print(f"{C.CYAN}[INFO] {text}{C.END}")


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


def ask_choice(prompt: str, choices: list, allow_multiple: bool = False) -> int | List[int]:
    """Demande un choix parmi une liste."""
    print(f"\n{C.BOLD}{prompt}{C.END}\n")
    for i, choice in enumerate(choices, 1):
        print(f"  {C.CYAN}{i}.{C.END} {choice}")
    print()

    if allow_multiple:
        print(f"{C.DIM}(Entrez les numeros separes par des virgules, ex: 1,3,5){C.END}")

    while True:
        try:
            result = input("Choix: ").strip()
            if not result:
                return [] if allow_multiple else 0

            if allow_multiple:
                indices = [int(x.strip()) for x in result.split(",")]
                if all(1 <= idx <= len(choices) for idx in indices):
                    return indices
            else:
                idx = int(result)
                if 1 <= idx <= len(choices):
                    return idx
        except ValueError:
            pass
        error("Choix invalide")


def press_enter():
    input(f"\n{C.DIM}Appuie sur Entree pour continuer...{C.END}")


# ============================================================================
# WIZARD PRINCIPAL
# ============================================================================

def show_welcome():
    """Affiche l'ecran de bienvenue."""
    clear()
    print(f"""
{C.BOLD}{C.CYAN}
+===========================================================+
|                                                           |
|          Agentys - Wizard de Configuration              |
|                                                           |
|   Configurez votre equipe d'agents IA en quelques etapes  |
|                                                           |
+===========================================================+
{C.END}

Ce wizard va vous guider pour :

  {C.CYAN}1.{C.END} Definir votre entreprise (secteur, taille, langues)
  {C.CYAN}2.{C.END} Choisir un pack d'agents preconfigure
  {C.CYAN}3.{C.END} Personnaliser les agents actifs
  {C.CYAN}4.{C.END} Importer votre knowledge base

{C.DIM}Duree estimee : 5-10 minutes{C.END}
""")


def step_company_info() -> dict:
    """Etape 1: Informations entreprise."""
    header("Etape 1/4 - Informations Entreprise")


    # Nom de l'entreprise
    company_name = ask("Nom de votre entreprise")
    if not company_name:
        error("Le nom est requis")
        return step_company_info()

    # Secteur d'activite
    sectors = [
        ("tech", "Tech / Logiciel"),
        ("saas", "SaaS"),
        ("ecommerce", "E-commerce"),
        ("finance", "Finance / Banque"),
        ("healthcare", "Sante / Medical"),
        ("education", "Education / Formation"),
        ("retail", "Commerce / Retail"),
        ("consulting", "Conseil / Services"),
        ("manufacturing", "Industrie / Manufacturing"),
        ("legal", "Juridique"),
        ("real_estate", "Immobilier"),
        ("hospitality", "Hotellerie / Tourisme"),
        ("media", "Media / Communication"),
        ("nonprofit", "Association / ONG"),
        ("other", "Autre"),
    ]

    print(f"\n{C.BOLD}Secteur d'activite :{C.END}\n")
    for i, (_, label) in enumerate(sectors, 1):
        print(f"  {C.CYAN}{i:2d}.{C.END} {label}")
    print()

    sector_idx = 0
    while sector_idx == 0:
        try:
            sector_idx = int(ask("Votre secteur (1-15)", "15"))
            if not 1 <= sector_idx <= 15:
                sector_idx = 0
                error("Choix invalide")
        except ValueError:
            error("Entrez un numero")

    sector_code = sectors[sector_idx - 1][0]

    # Taille de l'entreprise
    sizes = [
        ("solo", "Solo (1 personne)"),
        ("startup", "Startup (2-10)"),
        ("smb", "PME (11-50)"),
        ("midmarket", "ETI (51-200)"),
        ("enterprise", "Grande entreprise (200+)"),
    ]

    size_choice = ask_choice("Taille de votre entreprise", [s[1] for s in sizes])
    size_code = sizes[size_choice - 1][0] if size_choice > 0 else "smb"

    # Langues
    print(f"\n{C.BOLD}Langues supportees :{C.END}")
    print(f"{C.DIM}Entrez les codes ISO (ex: fr,en,de) separes par des virgules{C.END}")
    languages_input = ask("Langues", "fr,en")
    languages = [lang.strip().lower() for lang in languages_input.split(",")]

    primary_language = languages[0] if languages else "fr"

    return {
        "company_name": company_name,
        "sector": sector_code,
        "size": size_code,
        "primary_language": primary_language,
        "supported_languages": languages,
    }


def step_choose_pack() -> Optional[str]:
    """Etape 2: Choix du pack."""
    header("Etape 2/4 - Choix du Pack")

    from app.application import get_available_packs

    packs = get_available_packs()

    print(f"""
Les packs preconfigures activent automatiquement les agents
les plus pertinents pour votre type d'activite.

{C.DIM}Vous pourrez personnaliser les agents a l'etape suivante.{C.END}
""")

    choices = []
    for pack in packs:
        choices.append(f"{pack['name']} - {pack['description']} ({pack['agents_count']} agents)")

    choices.append("Configuration personnalisee (choisir les agents manuellement)")

    choice = ask_choice("Quel pack correspond le mieux a votre activite ?", choices)

    if choice == 0 or choice == len(choices):
        return None  # Custom

    return packs[choice - 1]["id"]


def step_configure_agents(pack_id: Optional[str] = None) -> List[dict]:
    """Etape 3: Configuration des agents."""
    header("Etape 3/4 - Configuration des Agents")

    from app.application import get_available_agents, PACK_CONFIGURATIONS
    from app.domain.entities import ConfigPack

    all_agents = get_available_agents()

    # Pre-selectionner selon le pack
    preselected = set()
    if pack_id:
        pack_enum = ConfigPack(pack_id)
        if pack_enum in PACK_CONFIGURATIONS:
            pack_config = PACK_CONFIGURATIONS[pack_enum]
            preselected = {a["id"] for a in pack_config.get("agents", [])}
            info(f"Pack {pack_id} : {len(preselected)} agents pre-selectionnes")

    # Grouper par categorie
    categories = {}
    for agent in all_agents:
        cat = agent.get("category", "other")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(agent)

    category_names = {
        "core": "Agents Principaux (toujours actifs)",
        "support": "Support Client",
        "expert": "Experts Metier",
        "sales": "Ventes & Marketing",
        "productivity": "Productivite",
        "analytics": "Analytics",
    }

    print(f"""
Selectionnez les agents a activer pour votre entreprise.

{C.DIM}Les agents 'core' (Drafter, Critic) sont toujours actifs.{C.END}
""")

    selected_agents = []

    for cat, agents in categories.items():
        cat_name = category_names.get(cat, cat.title())
        print(f"\n{C.BOLD}{C.CYAN}=== {cat_name} ==={C.END}\n")

        for agent in agents:
            is_preselected = agent["id"] in preselected
            is_core = cat == "core"

            status = ""
            if is_core:
                status = f" {C.GREEN}(obligatoire){C.END}"
            elif is_preselected:
                status = f" {C.YELLOW}(recommande){C.END}"

            print(f"  {C.BOLD}{agent['name']}{C.END}{status}")
            print(f"  {C.DIM}{agent['description']}{C.END}")

            if is_core:
                # Core agents toujours actifs
                selected_agents.append({"id": agent["id"], "priority": 100})
                print(f"  {C.GREEN}[ACTIF]{C.END}\n")
            else:
                default = is_preselected
                if ask_yes_no(f"  Activer {agent['name']} ?", default=default):
                    priority = 50
                    if is_preselected:
                        # Recuperer la priorite du pack
                        for pack_agent in PACK_CONFIGURATIONS.get(ConfigPack(pack_id), {}).get("agents", []):
                            if pack_agent["id"] == agent["id"]:
                                priority = pack_agent.get("priority", 50)
                                break
                    selected_agents.append({"id": agent["id"], "priority": priority})
                    print(f"  {C.GREEN}[ACTIF]{C.END}\n")
                else:
                    print(f"  {C.DIM}[inactif]{C.END}\n")

    return selected_agents


def step_knowledge_base() -> dict:
    """Etape 4: Knowledge Base."""
    header("Etape 4/4 - Base de Connaissances")

    print("""
La base de connaissances permet a l'IA de personnaliser
ses reponses avec le contexte de votre entreprise.

Options :
  1. Importer un fichier existant (.md, .txt)
  2. Creer maintenant (wizard rapide)
  3. Passer cette etape (a faire plus tard)
""")

    choice = ask_choice("Comment souhaitez-vous proceder ?", [
        "Importer un fichier existant",
        "Creer maintenant (5 min)",
        "Passer pour l'instant",
    ])

    kb_config = {
        "company_name": "",
        "company_description": "",
        "products_services": "",
        "tone_guidelines": "",
        "forbidden_topics": [],
        "custom_file_path": None,
    }

    if choice == 1:
        # Import fichier
        file_path = ask("Chemin du fichier a importer")
        if file_path and Path(file_path).exists():
            kb_config["custom_file_path"] = file_path
            content = Path(file_path).read_text(encoding='utf-8')
            kb_config["company_description"] = content
            success(f"Fichier importe : {file_path}")
        else:
            warning("Fichier non trouve, etape passee")

    elif choice == 2:
        # Wizard rapide
        print(f"\n{C.BOLD}=== Wizard Knowledge Base ==={C.END}\n")

        kb_config["company_name"] = ask("Nom de l'entreprise")
        kb_config["company_description"] = ask(
            "Description breve de votre activite (1-2 phrases)"
        )

        print(f"\n{C.DIM}Produits/Services principaux (un par ligne, ligne vide pour terminer):{C.END}")
        services = []
        while True:
            service = input("  - ").strip()
            if not service:
                break
            services.append(service)
        kb_config["products_services"] = "\n".join(services)

        tone_choice = ask_choice("Ton de communication :", [
            "Formel et professionnel (vouvoiement)",
            "Professionnel mais chaleureux",
            "Decontracte et amical (tutoiement)",
            "Adaptatif selon le contexte",
        ])
        tone_map = {
            1: "Ton formel, vouvoiement systematique, reponses structurees.",
            2: "Ton professionnel mais accessible, vouvoiement par defaut.",
            3: "Ton decontracte, tutoiement accepte, reponses directes.",
            4: "Adapter le ton selon l'interlocuteur et le contexte.",
        }
        kb_config["tone_guidelines"] = tone_map.get(tone_choice, tone_map[2])

        print(f"\n{C.DIM}Sujets a eviter/interdits (ligne vide pour terminer):{C.END}")
        forbidden = []
        while True:
            topic = input("  - ").strip()
            if not topic:
                break
            forbidden.append(topic)
        kb_config["forbidden_topics"] = forbidden

    return kb_config


def save_configuration(
    company_info: dict,
    pack_id: Optional[str],
    agents: List[dict],
    kb_config: dict
):
    """Sauvegarde la configuration complete."""
    from app.domain.entities import (
        WizardConfig, BusinessSector, CompanySize, ConfigPack,
        AgentActivation, KnowledgeBaseConfig
    )
    from app.infrastructure.wizard_config_store import get_wizard_config_store
    from app.application import SaveWizardConfigUseCase
    import uuid

    # Creer la config
    config = WizardConfig(
        config_id=str(uuid.uuid4()),
        company_name=company_info["company_name"],
        sector=BusinessSector(company_info["sector"]),
        size=CompanySize(company_info["size"]),
        primary_language=company_info["primary_language"],
        supported_languages=company_info["supported_languages"],
        pack=ConfigPack(pack_id) if pack_id else ConfigPack.CUSTOM,
        agents=[
            AgentActivation(
                agent_id=a["id"],
                enabled=True,
                priority=a.get("priority", 50)
            )
            for a in agents
        ],
        knowledge_base=KnowledgeBaseConfig(
            company_name=kb_config.get("company_name", ""),
            company_description=kb_config.get("company_description", ""),
            products_services=kb_config.get("products_services", ""),
            tone_guidelines=kb_config.get("tone_guidelines", ""),
            forbidden_topics=kb_config.get("forbidden_topics", []),
            custom_file_path=kb_config.get("custom_file_path"),
        ),
    )
    config.mark_complete()

    # Sauvegarder
    store = get_wizard_config_store()
    use_case = SaveWizardConfigUseCase(persistence=store)
    use_case.execute(config)

    return config


def show_summary(config):
    """Affiche le resume de la configuration."""
    header("Configuration Terminee !")

    print(f"""
{C.BOLD}Resume de votre configuration :{C.END}

  Entreprise : {C.CYAN}{config.company_name}{C.END}
  Secteur    : {config.sector.value}
  Taille     : {config.size.value}
  Langues    : {', '.join(config.supported_languages)}
  Pack       : {config.pack.value}

{C.BOLD}Agents actifs ({len(config.get_active_agents())}) :{C.END}
""")

    for agent in config.get_active_agents():
        print(f"  - {agent.agent_id} (priorite: {agent.priority})")

    print(f"""

{C.GREEN}Configuration sauvegardee dans data/wizard_config.json{C.END}

{C.BOLD}Prochaines etapes :{C.END}

  1. Verifiez la configuration email : {C.CYAN}python setup.py{C.END}
  2. Lancez le daemon : {C.CYAN}python run_daemon.py{C.END}
  3. Consultez le dashboard : {C.CYAN}python -m app.dashboard{C.END}
""")


def run_wizard():
    """Execute le wizard complet."""
    show_welcome()

    if not ask_yes_no("Commencer la configuration ?"):
        print("\nA bientot !\n")
        return

    # Etape 1: Infos entreprise
    company_info = step_company_info()

    # Etape 2: Choix du pack
    pack_id = step_choose_pack()

    # Etape 3: Configuration agents
    agents = step_configure_agents(pack_id)

    # Etape 4: Knowledge base
    kb_config = step_knowledge_base()

    # Confirmation finale
    header("Confirmation")

    print(f"""
{C.BOLD}Recapitulatif :{C.END}

  Entreprise : {C.CYAN}{company_info['company_name']}{C.END}
  Secteur    : {company_info['sector']}
  Taille     : {company_info['size']}
  Pack       : {pack_id or 'custom'}
  Agents     : {len(agents)} actifs
  Langues    : {', '.join(company_info['supported_languages'])}
""")

    if not ask_yes_no("Sauvegarder cette configuration ?"):
        warning("Configuration annulee")
        return

    # Sauvegarder
    try:
        config = save_configuration(company_info, pack_id, agents, kb_config)
        show_summary(config)
    except Exception as e:
        error(f"Erreur lors de la sauvegarde : {e}")
        import traceback
        traceback.print_exc()


# ============================================================================
# MENU DE GESTION (post-wizard)
# ============================================================================

def manage_agents():
    """Gere les agents (activer/desactiver)."""
    from app.infrastructure.wizard_config_store import get_wizard_config_store
    from app.application import ToggleAgentUseCase, get_available_agents

    store = get_wizard_config_store()
    config = store.load()

    if not config:
        warning("Aucune configuration trouvee. Lancez d'abord le wizard.")
        return

    header("Gestion des Agents")

    all_agents = get_available_agents()
    active_ids = {a.agent_id for a in config.get_active_agents()}

    print(f"{C.BOLD}Agents actuellement actifs :{C.END}\n")

    for agent in all_agents:
        status = f"{C.GREEN}[ACTIF]{C.END}" if agent["id"] in active_ids else f"{C.DIM}[inactif]{C.END}"
        print(f"  {status} {agent['name']} - {agent['description']}")

    print()

    # Actions
    action = ask_choice("Que souhaitez-vous faire ?", [
        "Activer un agent",
        "Desactiver un agent",
        "Retour",
    ])

    if action == 1:
        # Activer
        inactive = [a for a in all_agents if a["id"] not in active_ids]
        if not inactive:
            info("Tous les agents sont deja actifs")
            return

        choice = ask_choice(
            "Quel agent activer ?",
            [f"{a['name']} - {a['description']}" for a in inactive]
        )
        if choice > 0:
            use_case = ToggleAgentUseCase(persistence=store)
            use_case.execute(inactive[choice - 1]["id"], enabled=True)
            success(f"Agent {inactive[choice - 1]['name']} active")

    elif action == 2:
        # Desactiver
        active = [a for a in all_agents if a["id"] in active_ids and a["category"] != "core"]
        if not active:
            info("Aucun agent desactivable (les agents core sont obligatoires)")
            return

        choice = ask_choice(
            "Quel agent desactiver ?",
            [f"{a['name']} - {a['description']}" for a in active]
        )
        if choice > 0:
            use_case = ToggleAgentUseCase(persistence=store)
            use_case.execute(active[choice - 1]["id"], enabled=False)
            success(f"Agent {active[choice - 1]['name']} desactive")


def view_config():
    """Affiche la configuration actuelle."""
    from app.infrastructure.wizard_config_store import get_wizard_config_store

    store = get_wizard_config_store()
    config = store.load()

    if not config:
        warning("Aucune configuration trouvee. Lancez d'abord le wizard.")
        return

    show_summary(config)


def export_config():
    """Exporte la configuration."""
    from app.infrastructure.wizard_config_store import get_wizard_config_store

    store = get_wizard_config_store()
    config = store.load()

    if not config:
        warning("Aucune configuration trouvee.")
        return

    output_path = ask("Chemin du fichier d'export", "wizard_config_export.json")

    try:
        store.export_to_file(output_path)
        success(f"Configuration exportee vers {output_path}")
    except Exception as e:
        error(f"Erreur : {e}")


def main_menu():
    """Menu principal."""
    from app.infrastructure.wizard_config_store import get_wizard_config_store

    while True:
        clear()
        print(f"""
{C.BOLD}{C.CYAN}
+===========================================================+
|          Agentys - Configuration Entreprise             |
+===========================================================+
{C.END}""")

        store = get_wizard_config_store()
        config = store.load()

        if config:
            print(f"  Configuration active : {C.GREEN}{config.company_name}{C.END}")
            print(f"  Agents actifs : {len(config.get_active_agents())}")
            print(f"  Pack : {config.pack.value}")
            print()

        choice = ask_choice("Que souhaitez-vous faire ?", [
            "Lancer le wizard de configuration",
            "Voir la configuration actuelle",
            "Gerer les agents (activer/desactiver)",
            "Exporter la configuration",
            "Quitter",
        ])

        if choice == 1:
            run_wizard()
            press_enter()
        elif choice == 2:
            view_config()
            press_enter()
        elif choice == 3:
            manage_agents()
            press_enter()
        elif choice == 4:
            export_config()
            press_enter()
        elif choice == 5 or choice == 0:
            print("\nA bientot !\n")
            break


def main():
    """Point d'entree."""
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "--wizard" or cmd == "-w":
            run_wizard()
        elif cmd == "--view" or cmd == "-v":
            view_config()
        elif cmd == "--agents" or cmd == "-a":
            manage_agents()
        elif cmd == "--help" or cmd == "-h":
            print("""
Usage: python run_wizard.py [OPTIONS]

Options:
  --wizard, -w    Lancer le wizard de configuration
  --view, -v      Voir la configuration actuelle
  --agents, -a    Gerer les agents
  --help, -h      Afficher cette aide

Sans argument, lance le menu interactif.
""")
        else:
            print(f"Option inconnue: {cmd}")
            print("Utilisez --help pour voir les options disponibles.")
    else:
        main_menu()


if __name__ == "__main__":
    main()
