# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Utilitaire JSON centralisé.

Ce module fournit des fonctions de parsing JSON sûres avec gestion d'erreurs cohérente.
Il remplace les appels json.loads() dispersés dans le code pour assurer :
- Une gestion d'erreurs uniforme
- Des valeurs par défaut typées
- Un logging centralisé des erreurs de parsing
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def safe_json_parse(
    content: str,
    default: Optional[Dict[str, Any]] = None,
    error_context: str = ""
) -> Dict[str, Any]:
    """
    Parse une chaîne JSON de manière sécurisée.

    Args:
        content: La chaîne JSON à parser.
        default: Valeur par défaut si le parsing échoue.
        error_context: Contexte pour le message d'erreur (ex: "PrioritizationAgent").

    Returns:
        Le dictionnaire parsé ou la valeur par défaut.

    Example:
        >>> result = safe_json_parse('{"key": "value"}', default={})
        >>> result
        {'key': 'value'}
    """
    if default is None:
        default = {}

    if not content or not content.strip():
        if error_context:
            logger.debug(f"[{error_context}] Contenu JSON vide, utilisation du défaut")
        return default

    try:
        parsed = json.loads(content.strip())
        if not isinstance(parsed, dict):
            if error_context:
                logger.warning(f"[{error_context}] JSON n'est pas un objet, utilisation du défaut")
            return default
        return parsed
    except json.JSONDecodeError as e:
        if error_context:
            logger.warning(f"[{error_context}] Erreur parsing JSON: {e}")
        return default
    except Exception as e:
        if error_context:
            logger.error(f"[{error_context}] Erreur inattendue parsing JSON: {e}")
        return default


def safe_json_parse_list(
    content: str,
    default: Optional[list] = None,
    error_context: str = ""
) -> list:
    """
    Parse une chaîne JSON attendue comme liste.

    Args:
        content: La chaîne JSON à parser.
        default: Valeur par défaut si le parsing échoue.
        error_context: Contexte pour le message d'erreur.

    Returns:
        La liste parsée ou la valeur par défaut.
    """
    if default is None:
        default = []

    if not content or not content.strip():
        return default

    try:
        parsed = json.loads(content.strip())
        if not isinstance(parsed, list):
            if error_context:
                logger.warning(f"[{error_context}] JSON n'est pas une liste, utilisation du défaut")
            return default
        return parsed
    except json.JSONDecodeError as e:
        if error_context:
            logger.warning(f"[{error_context}] Erreur parsing JSON: {e}")
        return default
    except Exception as e:
        if error_context:
            logger.error(f"[{error_context}] Erreur inattendue: {e}")
        return default


def extract_json_from_response(
    content: str,
    default: Optional[Dict[str, Any]] = None,
    error_context: str = ""
) -> Dict[str, Any]:
    """
    Extrait un objet JSON d'une réponse LLM qui peut contenir du texte supplémentaire.

    Gère les cas où le modèle retourne du texte avant/après le JSON,
    utilise des blocs de code markdown, ou produit du JSON avec des erreurs
    mineures (virgules finales, codes ANSI, BOM).

    Args:
        content: La réponse LLM contenant potentiellement du JSON.
        default: Valeur par défaut si l'extraction échoue.
        error_context: Contexte pour le message d'erreur.

    Returns:
        Le dictionnaire extrait ou la valeur par défaut.

    Example:
        >>> extract_json_from_response('Voici le résultat: {"score": 85}')
        {'score': 85}
    """
    if default is None:
        default = {}

    if not content or not content.strip():
        if error_context:
            logger.warning("[%s] Réponse LLM vide, utilisation du défaut", error_context)
        return default

    # Nettoyage : BOM, codes ANSI, underscores échappés markdown
    text = content.strip()
    text = text.lstrip("\ufeff")
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    text = text.replace("\\_", "_")

    # Essayer chaque candidat brut puis avec trailing-commas corrigées
    for candidate in _json_candidates(text):
        for json_str in (candidate, _fix_trailing_commas(candidate)):
            result = safe_json_parse(json_str)
            if result != {}:
                return result

    # Dernier recours : tenter de réparer un JSON tronqué
    repaired = _try_repair_truncated(text)
    if repaired:
        result = safe_json_parse(repaired)
        if result != {}:
            if error_context:
                # WARNING, not info: a repaired truncation means the model was cut
                # off (raise the cap / shorten the prompt). Truncated values are
                # nulled above, so the result is partial — surface it.
                logger.warning("[%s] JSON tronqué réparé (réponse coupée — valeurs manquantes mises à null)", error_context)
            return result

    # Toutes les stratégies ont échoué
    if error_context:
        preview = content[:500].replace("\n", "\\n")
        logger.warning(
            "[%s] Impossible d'extraire du JSON valide. "
            "Réponse (%d chars) : %s",
            error_context, len(content), preview,
        )

    return default


def _json_candidates(text: str) -> List[str]:
    """Génère des chaînes JSON candidates depuis différents formats LLM."""
    candidates: List[str] = []

    # 1. Texte complet
    candidates.append(text)

    # 2. Blocs ```json ... ```
    for m in re.finditer(r"```json\s*\n?(.*?)```", text, re.DOTALL):
        inner = m.group(1).strip()
        if inner and inner not in candidates:
            candidates.append(inner)

    # 3. Blocs ``` ... ```
    for m in re.finditer(r"```\s*\n?(.*?)```", text, re.DOTALL):
        inner = m.group(1).strip()
        if inner and inner not in candidates:
            candidates.append(inner)

    # 4. Premier { au dernier }
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        substr = text[first:last + 1]
        if substr not in candidates:
            candidates.append(substr)

    return candidates


def _fix_trailing_commas(text: str) -> str:
    """Supprime les virgules finales avant ] ou } (erreur LLM fréquente)."""
    return re.sub(r",\s*([}\]])", r"\1", text)


def _try_repair_truncated(text: str) -> Optional[str]:
    """Tente de réparer un JSON tronqué en fermant les accolades/crochets manquants.

    Gère le cas où le LLM retourne un JSON incomplet (réponse coupée).
    """
    first = text.find("{")
    if first == -1:
        return None

    # Extraire depuis le premier {
    json_text = text[first:]

    # Supprimer tout texte incomplet à la fin (clé/valeur tronquée)
    # Retirer le dernier token incomplet : string non fermée, clé sans valeur, etc.
    json_text = re.sub(r',\s*"[^"]*$', '', json_text)  # clé tronquée : , "key_tron
    json_text = re.sub(r':\s*"[^"]*$', ': null', json_text)  # valeur string tronquée
    # Valeur NUMÉRIQUE tronquée (chaos audit 2026-06-02) : on n'arrive ici que si
    # le JSON n'a AUCUNE accolade fermante (vraie troncature), donc un nombre nu
    # en toute fin est presque sûrement coupé (ex: "score": 85 coupé en "score": 8).
    # Garder le préfixe persisterait une valeur FAUSSE indiscernable d'une vraie ;
    # on le remplace par null ("inconnu") plutôt que par un nombre erroné.
    json_text = re.sub(r':\s*-?\d+\.?\d*$', ': null', json_text)  # valeur numérique tronquée
    json_text = re.sub(r',\s*$', '', json_text)  # virgule finale

    # Compter les accolades/crochets ouverts
    open_braces = json_text.count("{") - json_text.count("}")
    open_brackets = json_text.count("[") - json_text.count("]")

    if open_braces <= 0 and open_brackets <= 0:
        return None  # Pas un cas de troncature

    # Fermer les structures ouvertes
    json_text += "}" * open_braces + "]" * open_brackets

    # Nettoyer les virgules finales créées
    json_text = _fix_trailing_commas(json_text)

    return json_text


def to_json_string(data: Any, pretty: bool = False) -> str:
    """
    Convertit des données en chaîne JSON.

    Args:
        data: Les données à sérialiser.
        pretty: Si True, formate le JSON avec indentation.

    Returns:
        La chaîne JSON.
    """
    if pretty:
        return json.dumps(data, ensure_ascii=False, indent=2)
    return json.dumps(data, ensure_ascii=False)
