# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Module de nettoyage et préparation du contenu email.

Fournit des fonctions pour :
- Supprimer les signatures email
- Supprimer le texte cité
- Détecter les auto-replies
- Tronquer les emails trop longs
"""

import re
from typing import Tuple, Dict

from app.config import MAX_EMAIL_TOKENS, CHARS_PER_TOKEN


# =============================================================================
# SUJET EMAIL — préfixes Re:/Fwd:
# =============================================================================

_REPLY_PREFIX = re.compile(r'^\s*(re|fwd?)\s*:\s*', re.IGNORECASE)


def build_reply_subject(subject: str) -> str:
    """Retourne 'Re: <sujet>' en évitant les 'Re: Re: Re:'.

    Strip tous les préfixes Re:/RE:/Fwd:/FW: en chaîne,
    puis préfixe avec un unique 'Re: '.
    """
    s = subject or ''
    while _REPLY_PREFIX.match(s):
        s = _REPLY_PREFIX.sub('', s).strip()
    return f"Re: {s}"


def build_forward_subject(subject: str) -> str:
    """Retourne 'Fwd: <sujet>' en évitant les 'Fwd: Fwd:'."""
    s = subject or ''
    while _REPLY_PREFIX.match(s):
        s = _REPLY_PREFIX.sub('', s).strip()
    return f"Fwd: {s}"


# =============================================================================
# PATTERNS DE SIGNATURES
# =============================================================================

# Indicateurs de début de signature
SIGNATURE_PATTERNS = [
    # Délimiteurs explicites
    r"^--\s*$",
    r"^___+\s*$",
    r"^---+\s*$",
    r"^===+\s*$",
    r"^\*{3,}\s*$",

    # Phrases typiques de signature
    r"^(?:Best\s+)?Regards?,?\s*$",
    r"^Cordialement,?\s*$",
    r"^Bien\s+(?:cordialement|à\s+vous),?\s*$",
    r"^Merci,?\s*$",
    r"^Thanks?,?\s*$",
    r"^Cheers,?\s*$",
    r"^Sincerely,?\s*$",
    r"^Kind\s+regards?,?\s*$",
    r"^Sent\s+from\s+",
    r"^Envoyé\s+depuis\s+",
    r"^Get\s+Outlook\s+for\s+",
    r"^Téléchargez\s+Outlook\s+",
    r"^Sent\s+with\s+",
    # Formules de clôture supplémentaires (FR/EN)
    r"^Amicalement,?\s*$",
    r"^Amitiés,?\s*$",
    r"^(?:À\s+bientôt|A\s+bientôt),?\s*$",
    r"^En\s+vous\s+remerciant",
    r"^En\s+te\s+remerciant",
    r"^Dans\s+l.attente\s+de",
    r"^(?:Salutations\s+)?distinguées,?\s*$",
    r"^(?:Salutations\s+)?cordiales,?\s*$",
    r"^(?:Meilleures\s+)?salutations,?\s*$",
    r"^Bien\s+à\s+(?:vous|toi),?\s*$",
    r"^Merci\s+(?:d.avance|beaucoup|pour\s+tout),?\s*$",
    r"^(?:Best|Warm|Kind)\s+(?:wishes?|regards?),?\s*$",
    r"^Warm\s+regards?,?\s*$",
    r"^Looking\s+forward",
    r"^Bonsoir,?\s*$",
    r"^Bonne\s+(?:journée|soirée|semaine|continuation),?\s*$",
    r"^Have\s+a\s+(?:good|great|nice)\s+(?:day|weekend),?\s*$",
]

SIGNATURE_REGEX = re.compile(
    "|".join(SIGNATURE_PATTERNS),
    re.IGNORECASE | re.MULTILINE
)


# =============================================================================
# PATTERNS DE TEXTE CITÉ
# =============================================================================

# Patterns de citation (lignes commençant par >)
QUOTE_LINE_PATTERN = re.compile(r"^>+\s*", re.MULTILINE)

# Patterns d'en-tête de citation
QUOTE_HEADER_PATTERNS = [
    # "On Jan 15, 2025, at 10:30 AM, John Doe wrote:"
    r"^On\s+.+\s+wrote:\s*$",
    # "Le 15 janv. 2025 à 10:30, Jean Dupont a écrit :"
    r"^Le\s+.+\s+(?:a\s+)?écrit\s*:\s*$",
    # "From: John Doe"
    r"^From:\s+.+$",
    # "De: Jean Dupont"
    r"^De\s*:\s+.+$",
    # "----- Original Message -----"
    r"^-+\s*(?:Original\s+Message|Message\s+d'origine)\s*-+\s*$",
    # "---------- Forwarded message ----------"
    r"^-+\s*(?:Forwarded\s+message|Message\s+transféré)\s*-+\s*$",
    # "Begin forwarded message:"
    r"^Begin\s+forwarded\s+message:\s*$",
    r"^Début\s+du\s+message\s+transféré\s*:\s*$",
]

QUOTE_HEADER_REGEX = re.compile(
    "|".join(QUOTE_HEADER_PATTERNS),
    re.IGNORECASE | re.MULTILINE
)


# =============================================================================
# PATTERNS AUTO-REPLY
# =============================================================================

AUTO_REPLY_SUBJECT_PATTERNS = [
    r"^Out\s+of\s+(?:the\s+)?Office",
    r"^Absence\s+(?:du\s+bureau)?",
    r"^Auto(?:matic)?[-\s]?Reply",
    r"^Réponse\s+automatique",
    r"^Automatic\s+response",
    r"^I\s+am\s+currently\s+(?:out|away|on\s+(?:leave|vacation))",
    r"^Je\s+suis\s+(?:actuellement\s+)?(?:absent|en\s+(?:congés?|vacances))",
    r"^\[Auto\]",
    r"^OOO:",
    r"^OOF:",  # Out of Facility
    r"^Vacation\s+(?:Reply|Response)",
    r"^Do\s+not\s+reply",
    r"^Ne\s+pas\s+répondre",
]

AUTO_REPLY_SUBJECT_REGEX = re.compile(
    "|".join(AUTO_REPLY_SUBJECT_PATTERNS),
    re.IGNORECASE
)

AUTO_REPLY_BODY_PATTERNS = [
    r"I\s+am\s+(?:currently\s+)?(?:out\s+of\s+(?:the\s+)?office|away|on\s+(?:leave|vacation))",
    r"Je\s+suis\s+(?:actuellement\s+)?(?:absent|en\s+(?:congés?|vacances))",
    r"This\s+is\s+an?\s+(?:automated?|automatic)\s+(?:reply|response|message)",
    r"Ceci\s+est\s+un(?:e)?\s+(?:réponse|message)\s+automatique",
    r"I\s+will\s+(?:be\s+)?(?:back|return)\s+(?:on|in)",
    r"Je\s+(?:serai\s+de\s+retour|reviens)\s+(?:le|à\s+partir\s+du)",
    r"limited\s+access\s+to\s+(?:my\s+)?email",
    r"accès\s+limité\s+(?:à\s+)?(?:mes\s+)?(?:e?-?mails?|courriels?)",
    r"will\s+respond\s+(?:upon|when)\s+(?:my\s+)?return",
]

AUTO_REPLY_BODY_REGEX = re.compile(
    "|".join(AUTO_REPLY_BODY_PATTERNS),
    re.IGNORECASE
)


# =============================================================================
# FONCTIONS DE NETTOYAGE
# =============================================================================

def strip_signature(body: str) -> str:
    """
    Supprime la signature d'un email.

    Cherche les indicateurs de signature et supprime tout ce qui suit.

    Args:
        body: Corps de l'email.

    Returns:
        Corps sans la signature.
    """
    if not body:
        return ""

    lines = body.split("\n")
    signature_start = None

    # Chercher la première ligne de signature (en partant de la fin)
    for i in range(len(lines) - 1, max(0, len(lines) - 20), -1):
        line = lines[i]
        if SIGNATURE_REGEX.search(line):
            signature_start = i
            break

    if signature_start is not None:
        # Garder jusqu'à la ligne avant la signature
        return "\n".join(lines[:signature_start]).rstrip()

    return body.rstrip()


def strip_quoted_text(body: str) -> str:
    """
    Supprime le texte cité (réponses précédentes) d'un email.

    Détecte :
    - Les lignes commençant par ">"
    - Les en-têtes de citation ("On ... wrote:", "Le ... a écrit :")
    - Les messages transférés

    Args:
        body: Corps de l'email.

    Returns:
        Corps sans le texte cité.
    """
    if not body:
        return ""

    lines = body.split("\n")
    result_lines = []
    in_quote_block = False
    in_forwarded_block = False

    # Patterns pour détecter les blocs transférés (tout le reste est ignoré)
    forwarded_patterns = [
        r"^-+\s*(?:Forwarded\s+message|Message\s+transféré)\s*-+\s*$",
        r"^Begin\s+forwarded\s+message:\s*$",
        r"^Début\s+du\s+message\s+transféré\s*:\s*$",
    ]
    forwarded_regex = re.compile("|".join(forwarded_patterns), re.IGNORECASE)

    for i, line in enumerate(lines):
        # Vérifier si c'est un début de message transféré
        if forwarded_regex.search(line):
            in_forwarded_block = True
            continue

        # Si on est dans un bloc transféré, ignorer tout le reste
        if in_forwarded_block:
            continue

        # Vérifier si c'est un en-tête de citation (mais pas forwarded)
        if QUOTE_HEADER_REGEX.search(line) and not forwarded_regex.search(line):
            in_quote_block = True
            continue

        # Vérifier si la ligne commence par ">"
        if QUOTE_LINE_PATTERN.match(line):
            in_quote_block = True
            continue

        # Si on était dans un bloc de citation et qu'on trouve une ligne normale
        if in_quote_block:
            # Ligne vide dans le bloc de citation : continuer à ignorer
            if line.strip() == "":
                continue
            # Nouvelle ligne non citée : sortir du bloc
            in_quote_block = False

        if not in_quote_block:
            result_lines.append(line)

    return "\n".join(result_lines).strip()


def detect_auto_reply(body: str, subject: str = "") -> bool:
    """
    Détecte si un email est une réponse automatique (out-of-office, etc.).

    Args:
        body: Corps de l'email.
        subject: Sujet de l'email (optionnel).

    Returns:
        True si c'est une réponse automatique.
    """
    # Vérifier le sujet
    if subject and AUTO_REPLY_SUBJECT_REGEX.search(subject):
        return True

    # Vérifier le corps
    if body and AUTO_REPLY_BODY_REGEX.search(body):
        return True

    return False


def truncate_for_tokens(
    body: str,
    max_tokens: int = MAX_EMAIL_TOKENS,
    chars_per_token: float = CHARS_PER_TOKEN,
    add_truncation_notice: bool = True
) -> str:
    """
    Tronque un email trop long pour respecter la limite de tokens.

    Args:
        body: Corps de l'email.
        max_tokens: Limite de tokens (défaut: 8000).
        chars_per_token: Estimation caractères/token (défaut: 4.0).
        add_truncation_notice: Ajouter une notice si tronqué.

    Returns:
        Corps tronqué si nécessaire.
    """
    if not body:
        return ""

    max_chars = int(max_tokens * chars_per_token)

    if len(body) <= max_chars:
        return body

    # Tronquer et essayer de couper à un paragraphe
    truncated = body[:max_chars]

    # Chercher le dernier saut de ligne double pour couper proprement
    last_paragraph = truncated.rfind("\n\n")
    if last_paragraph > max_chars * 0.7:  # Au moins 70% du contenu
        truncated = truncated[:last_paragraph]
    else:
        # Sinon, chercher le dernier saut de ligne simple
        last_newline = truncated.rfind("\n")
        if last_newline > max_chars * 0.8:
            truncated = truncated[:last_newline]

    if add_truncation_notice:
        truncated += "\n\n[... Email tronqué pour traitement ...]"

    return truncated


def clean_email_content(
    body: str,
    subject: str = "",
    max_tokens: int = MAX_EMAIL_TOKENS,
    strip_signatures: bool = True,
    strip_quotes: bool = True,
    check_auto_reply: bool = True,
) -> Tuple[str, Dict[str, any]]:
    """
    Nettoie le contenu d'un email pour le traitement par IA.

    Applique dans l'ordre :
    1. Détection auto-reply
    2. Suppression signature
    3. Suppression texte cité
    4. Troncature si nécessaire

    Args:
        body: Corps de l'email.
        subject: Sujet de l'email.
        max_tokens: Limite de tokens.
        strip_signatures: Supprimer les signatures.
        strip_quotes: Supprimer le texte cité.
        check_auto_reply: Vérifier si auto-reply.

    Returns:
        Tuple (corps nettoyé, metadata):
        - metadata contient: is_auto_reply, was_truncated, original_length
    """
    metadata = {
        "is_auto_reply": False,
        "was_truncated": False,
        "original_length": len(body) if body else 0,
        "cleaned_length": 0,
    }

    if not body:
        return "", metadata

    # Étape 1: Détecter auto-reply
    if check_auto_reply:
        metadata["is_auto_reply"] = detect_auto_reply(body, subject)

    cleaned = body

    # Étape 2: Supprimer signature
    if strip_signatures:
        cleaned = strip_signature(cleaned)

    # Étape 3: Supprimer texte cité
    if strip_quotes:
        cleaned = strip_quoted_text(cleaned)

    # Étape 4: Tronquer si nécessaire
    original_cleaned_len = len(cleaned)
    cleaned = truncate_for_tokens(cleaned, max_tokens=max_tokens)
    metadata["was_truncated"] = len(cleaned) < original_cleaned_len

    metadata["cleaned_length"] = len(cleaned)

    return cleaned, metadata
