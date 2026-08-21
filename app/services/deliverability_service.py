"""Score de deliverability d'un draft avant envoi (#192 — phase 1).

Analyse heuristique sans appel réseau : détecte les patterns qui dégradent
le sender score ou déclenchent les filtres spam. Pas de check DNS/SPF/DKIM/DMARC
ici — ce sera une phase 2 dans un service séparé (appel réseau → async).

Input : ``subject`` + ``body`` en texte plain.
Output : ``DeliverabilityReport`` avec ``score`` (0-100, 100 = parfait) et
``issues`` (liste de flags avec severity et explication).

Conçu pour :
- Être appelable inline dans le CriticAgent (< 1ms).
- Être exposé via un endpoint HTTP léger pour le scoring live côté UI (#199).
- Ne JAMAIS lever d'exception — un score dégradé + issues est toujours préférable
  à un crash qui bloquerait l'envoi.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List

# Seuils exposés pour tests et tuning.
MAX_SUBJECT_LENGTH = 78           # > 78 → tronqué sur la plupart des clients.
MIN_SUBJECT_LENGTH = 3
MAX_SUBJECT_EMOJI = 1
MAX_EXCLAMATION_PER_100_CHARS = 2.0
MAX_UPPERCASE_WORD_RATIO = 0.15    # > 15% des mots en MAJ = suspect.
MAX_LINKS_PER_KB = 4.0
DEFAULT_LINK_COUNT_SOFT_CAP = 5
# Mots à risque : liste non-exhaustive, minuscules, word-boundary-matched.
_SPAM_TRIGGER_WORDS = {
    # FR
    "offre limitée", "cliquez ici", "gagnez", "gagner", "gratuit",
    "cent pour cent gratuit", "argent facile", "félicitations",
    "urgent", "act now",
    # EN
    "free", "click here", "winner", "act now", "limited time",
    "100% free", "risk free", "100% satisfied", "no catch",
    "buy direct", "call now", "order now",
}

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001F9FF\U0001FA00-\U0001FAFF\U00002700-\U000027BF]"
)
_WORD_RE = re.compile(r"\b[\wÀ-ÿ]+\b", re.UNICODE)
_FAKE_RE_RE = re.compile(r"^\s*(re:\s*){2,}", re.IGNORECASE)
_ALL_CAPS_WORD_RE = re.compile(r"\b[A-ZÀ-Ý]{3,}\b")


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    HIGH = "high"


@dataclass(frozen=True)
class DeliverabilityIssue:
    code: str
    severity: Severity
    message: str


@dataclass
class DeliverabilityReport:
    score: int  # 0-100, 100 = parfait.
    issues: List[DeliverabilityIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "issues": [
                {"code": i.code, "severity": i.severity.value, "message": i.message}
                for i in self.issues
            ],
        }

    def is_risky(self, threshold: int = 50) -> bool:
        """True si le score est en dessous du seuil — déclenche un warning UI."""
        return self.score < threshold


# Poids de pénalité par issue. Tuning itératif à prévoir quand on aura
# des données réelles de bounces ; pour l'instant, pondérations raisonnables.
_PENALTY = {
    Severity.INFO: 3,
    Severity.WARN: 10,
    Severity.HIGH: 25,
}


def _check_subject(subject: str) -> List[DeliverabilityIssue]:
    issues: List[DeliverabilityIssue] = []
    stripped = subject.strip()
    if not stripped:
        issues.append(DeliverabilityIssue(
            "subject_empty", Severity.HIGH,
            "Sujet vide — certains filtres mettent en spam automatiquement.",
        ))
        return issues
    if len(stripped) < MIN_SUBJECT_LENGTH:
        issues.append(DeliverabilityIssue(
            "subject_too_short", Severity.WARN,
            f"Sujet trop court (<{MIN_SUBJECT_LENGTH} caractères).",
        ))
    if len(stripped) > MAX_SUBJECT_LENGTH:
        issues.append(DeliverabilityIssue(
            "subject_too_long", Severity.INFO,
            f"Sujet tronqué sur mobile (>{MAX_SUBJECT_LENGTH} caractères).",
        ))
    if len(_EMOJI_RE.findall(stripped)) > MAX_SUBJECT_EMOJI:
        issues.append(DeliverabilityIssue(
            "subject_excessive_emoji", Severity.WARN,
            "Plusieurs emojis dans le sujet — perçu comme marketing.",
        ))
    if _FAKE_RE_RE.search(stripped):
        issues.append(DeliverabilityIssue(
            "fake_re_prefix", Severity.HIGH,
            "Préfixe 'Re: Re:' répété — pattern d'arnaque, fortement flaggé.",
        ))
    if len(_ALL_CAPS_WORD_RE.findall(stripped)) >= 2:
        issues.append(DeliverabilityIssue(
            "subject_shouting", Severity.WARN,
            "Mots en MAJUSCULES dans le sujet — baisse le sender score.",
        ))
    return issues


def _check_body(body: str) -> List[DeliverabilityIssue]:
    issues: List[DeliverabilityIssue] = []
    if not body.strip():
        issues.append(DeliverabilityIssue(
            "body_empty", Severity.HIGH,
            "Corps vide — souvent assimilé à du spam.",
        ))
        return issues

    # Exclamations excessives.
    body_len = max(len(body), 1)
    excl_ratio = body.count("!") / body_len * 100
    if excl_ratio > MAX_EXCLAMATION_PER_100_CHARS:
        issues.append(DeliverabilityIssue(
            "excessive_exclamations", Severity.WARN,
            f"Trop de points d'exclamation ({excl_ratio:.1f} / 100 chars).",
        ))

    # Ratio de mots en MAJ.
    words = _WORD_RE.findall(body)
    all_caps = [w for w in words if w.isupper() and len(w) >= 3]
    if words:
        ratio = len(all_caps) / len(words)
        if ratio > MAX_UPPERCASE_WORD_RATIO:
            issues.append(DeliverabilityIssue(
                "excessive_uppercase", Severity.WARN,
                f"{ratio * 100:.0f}% des mots en MAJUSCULES — perçu comme spam.",
            ))

    # Densité de liens.
    links = _URL_RE.findall(body)
    if len(links) > DEFAULT_LINK_COUNT_SOFT_CAP:
        issues.append(DeliverabilityIssue(
            "excessive_links", Severity.WARN,
            f"{len(links)} liens — densité élevée.",
        ))
    if body:
        link_density = len(links) / max(len(body) / 1000, 0.5)  # per KB
        if link_density > MAX_LINKS_PER_KB:
            issues.append(DeliverabilityIssue(
                "link_to_text_ratio_high", Severity.HIGH,
                "Ratio liens/texte élevé — déclenche souvent les filtres spam.",
            ))

    # Mots-clés spam connus.
    body_lower = body.lower()
    triggered = [w for w in _SPAM_TRIGGER_WORDS if w in body_lower]
    if triggered:
        severity = Severity.HIGH if len(triggered) >= 3 else Severity.WARN
        shown = ", ".join(triggered[:5])
        issues.append(DeliverabilityIssue(
            "spam_trigger_words", severity,
            f"Vocabulaire à risque détecté : {shown}.",
        ))

    return issues


def score_draft(subject: str, body: str) -> DeliverabilityReport:
    """Score un draft entre 0 (catastrophe spam) et 100 (parfait).

    Robuste : aucune exception levée. Si l'input est invalide (None, bytes…),
    retombe sur un score neutre et ajoute une issue.
    """
    if not isinstance(subject, str):
        subject = ""
    if not isinstance(body, str):
        body = ""

    issues = _check_subject(subject) + _check_body(body)
    penalty = sum(_PENALTY[i.severity] for i in issues)
    score = max(0, 100 - penalty)
    return DeliverabilityReport(score=score, issues=issues)
