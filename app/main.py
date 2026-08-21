# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Point d'entrée principal d'Agentys.

Orchestre le pipeline de traitement des emails :
1. Scan du dossier /data/inputs pour les fichiers Excel
2. Traitement via Drafter -> Critic -> Correction
3. Sauvegarde des résultats datés dans /data/outputs
"""

import sys
from datetime import datetime
from pathlib import Path
try:
    import pandas as pd
except ImportError:
    pd = None  # Optional: only needed for Excel pipeline (main.py)

from app.config import (
    INPUTS_DIR,
    OUTPUTS_DIR,
    PROGRESS_BAR_LENGTH,
)
from app.prompts import load_knowledge_base
from app.agents import (
    DrafterAgent,
    CriticAgent,
    EmailResult,
    process_single_email,
    token_counter,
)


# ============================================================================
# UTILITAIRES D'AFFICHAGE
# ============================================================================

def print_header():
    """Affiche l'en-tête du programme."""
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║              🤖 Agentys - Email Pipeline                   ║")
    print("║         Drafter Agent + Critic Agent + Correction           ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()


def print_progress(current: int, total: int, status: str = ""):
    """Affiche une barre de progression."""
    progress = current / total
    filled = int(PROGRESS_BAR_LENGTH * progress)
    bar = "█" * filled + "░" * (PROGRESS_BAR_LENGTH - filled)
    sys.stdout.write(
        f"\r[{bar}] {current}/{total} ({progress*100:.0f}%) "
        f"{token_counter} {status[:40]:<40}"
    )
    sys.stdout.flush()


def print_stats(results: list[EmailResult]):
    """Affiche les statistiques finales."""
    valid_v1 = sum(1 for r in results if r.status == "VALIDÉ V1")
    corrected = sum(1 for r in results if r.status == "CORRIGÉ V2")
    ignored = sum(1 for r in results if r.status.startswith("IGNORÉ"))

    print()
    print()
    print("📊 Statistiques :")
    print(f"   ├─ Validés V1 : {valid_v1}")
    print(f"   ├─ Corrigés V2 : {corrected}")
    print(f"   └─ Ignorés : {ignored}")
    print()
    print("🔢 Tokens utilisés :")
    print(f"   ├─ Input  : {token_counter.input:,}")
    print(f"   ├─ Output : {token_counter.output:,}")
    print(f"   └─ Total  : {token_counter.total:,}")


# ============================================================================
# SCAN DES FICHIERS EXCEL
# ============================================================================

def scan_input_files() -> list[Path]:
    """
    Scanne le dossier /data/inputs pour les fichiers Excel.

    Returns:
        Liste des fichiers .xlsx trouvés.
    """
    INPUTS_DIR.mkdir(parents=True, exist_ok=True)

    xlsx_files = list(INPUTS_DIR.glob("*.xlsx"))

    if not xlsx_files:
        print(f"⚠️  Aucun fichier Excel trouvé dans {INPUTS_DIR}")
        print("   Placez vos fichiers .xlsx dans ce dossier et relancez.")
        return []

    print(f"📂 Fichiers trouvés dans {INPUTS_DIR.name}/ :")
    for f in xlsx_files:
        print(f"   └─ {f.name}")

    return xlsx_files


# ============================================================================
# CHARGEMENT DES DONNÉES
# ============================================================================

def load_excel(file_path: Path) -> "pd.DataFrame":
    """
    Charge un fichier Excel et normalise les colonnes.

    Args:
        file_path: Chemin vers le fichier Excel.

    Returns:
        DataFrame avec les colonnes normalisées.

    Raises:
        ImportError: Si pandas/openpyxl ne sont pas installés.
    """
    if pd is None:
        raise ImportError(
            "pandas et openpyxl sont requis pour le pipeline Excel. "
            "Installez-les avec : pip install pandas openpyxl"
        )
    # Essayer différentes configurations de lecture
    try:
        # Format avec en-têtes sur la première ligne
        df = pd.read_excel(file_path)

        # Vérifier si les colonnes attendues existent
        expected_cols = {"Numéro", "Email reçu", "Réponse"}
        if not expected_cols.issubset(set(df.columns)):
            # Format avec lignes à sauter (ancien format)
            df = pd.read_excel(file_path, skiprows=2, header=None)
            df.columns = ["Numéro", "Email reçu", "Réponse"]

    except Exception:
        # Fallback : format avec lignes à sauter
        df = pd.read_excel(file_path, skiprows=2, header=None)
        df.columns = ["Numéro", "Email reçu", "Réponse"]

    # Filtrer les lignes valides
    df = df[df["Numéro"].notna()].reset_index(drop=True)

    return df


# ============================================================================
# TRAITEMENT PRINCIPAL
# ============================================================================

def process_file(file_path: Path) -> Path:
    """
    Traite un fichier Excel et génère le rapport.

    Args:
        file_path: Chemin vers le fichier Excel source.

    Returns:
        Chemin vers le fichier de résultats.
    """
    print()
    print(f"📧 Traitement de : {file_path.name}")
    print("─" * 60)

    # Charger les données
    df = load_excel(file_path)
    total = len(df)
    print(f"   Emails à traiter : {total}")

    # Charger la base de connaissances
    knowledge = load_knowledge_base()
    print(f"🧠 Mémoire chargée : {len(knowledge):,} caractères")
    print()

    # Initialiser les agents
    drafter = DrafterAgent(knowledge_base=knowledge)
    critic = CriticAgent(knowledge_base=knowledge)

    # Réinitialiser le compteur de tokens
    token_counter.reset()

    # Traiter chaque email
    results: list[EmailResult] = []

    for idx, row in df.iterrows():
        numero = int(row["Numéro"])
        email_content = row.get("Email reçu", "")
        human_response = row.get("Réponse", "")

        # Ignorer les emails vides
        if pd.isna(email_content) or str(email_content).strip() == "":
            print_progress(idx + 1, total, f"#{numero} - Ignoré (vide)")
            results.append(EmailResult(
                numero=numero,
                email_content=str(email_content) if pd.notna(email_content) else "",
                human_response=str(human_response) if pd.notna(human_response) else "",
                draft_v1="",
                critique="",
                draft_final="",
                status="IGNORÉ - Email vide"
            ))
            continue

        # Traitement de l'email
        print_progress(idx + 1, total, f"#{numero} - Draft V1...")

        result = process_single_email(
            drafter=drafter,
            critic=critic,
            numero=numero,
            email_content=str(email_content),
            human_response=str(human_response) if pd.notna(human_response) else ""
        )

        status_icon = "✓" if result.status == "VALIDÉ V1" else "↻"
        print_progress(idx + 1, total, f"#{numero} - {status_icon} {result.status}")

        results.append(result)

    # Afficher les statistiques
    print_stats(results)

    # Sauvegarder les résultats
    output_path = save_results(results, file_path.stem)

    return output_path


# ============================================================================
# SAUVEGARDE DES RÉSULTATS
# ============================================================================

def save_results(results: list[EmailResult], source_name: str) -> Path:
    """
    Sauvegarde les résultats dans un fichier Excel daté.

    Args:
        results: Liste des résultats de traitement.
        source_name: Nom du fichier source (pour le préfixe).

    Returns:
        Chemin vers le fichier de résultats.

    Raises:
        ImportError: Si pandas/openpyxl ne sont pas installés.
    """
    if pd is None:
        raise ImportError(
            "pandas et openpyxl sont requis pour sauvegarder les résultats. "
            "Installez-les avec : pip install pandas openpyxl"
        )
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    # Nom du fichier avec date
    date_str = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    output_file = OUTPUTS_DIR / f"rapport_{date_str}.xlsx"

    # Convertir en DataFrame
    data = [{
        "Numéro": r.numero,
        "Email reçu": r.email_content,
        "Réponse (Humain)": r.human_response,
        "Draft_IA_V1": r.draft_v1,
        "Critique": r.critique,
        "Draft_IA_Final": r.draft_final,
        "Status": r.status
    } for r in results]

    df = pd.DataFrame(data)
    df.to_excel(output_file, index=False)

    print()
    print(f"💾 Résultats sauvegardés : {output_file.name}")

    return output_file


# ============================================================================
# POINT D'ENTRÉE
# ============================================================================

def main():
    """Point d'entrée principal."""
    print_header()

    # Scanner les fichiers d'entrée
    input_files = scan_input_files()

    if not input_files:
        print()
        print("💡 Astuce : Placez vos fichiers Excel dans le dossier data/inputs/")
        return

    print()

    # Traiter chaque fichier
    for file_path in input_files:
        process_file(file_path)

    print()
    print("═" * 60)
    print("✅ Traitement terminé !")
    print(f"📁 Résultats disponibles dans : {OUTPUTS_DIR}")
    print()


if __name__ == "__main__":
    main()
