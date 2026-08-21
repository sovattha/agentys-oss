# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Service d'inférence de style depuis l'outbox (issue #187).

Analyse purement lexicale (regex + stdlib) d'un corpus d'emails envoyés
pour extraire des métriques statistiques décrivant le style réel de
l'utilisateur. Remplace les sliders explicites de Formalité/Émotion.

Aucune dépendance LLM : déterministe, < 5s sur 500 emails.
"""

from __future__ import annotations

import logging
import re
import statistics
from typing import Any, Dict, Iterable, List, Protocol, Sequence, Tuple

from app.domain.entities.writing_style import ReferenceExample

logger = logging.getLogger(__name__)


class _HasBodyText(Protocol):
    """Duck-type minimal pour un email analysable."""

    body_text: Any  # str ou None
    subject: Any


# ---------------------------------------------------------------------------
# Patterns précompilés
# ---------------------------------------------------------------------------

# Emojis (plages Unicode principales : émoticônes, symboles, pictogrammes)
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F5FF"  # Symboles & pictogrammes
    "\U0001F600-\U0001F64F"  # Émoticônes
    "\U0001F680-\U0001F6FF"  # Transport & cartes
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"  # Gestes & humains
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002600-\U000026FF"  # Symboles divers
    "\U00002700-\U000027BF"  # Dingbats
    "]",
    flags=re.UNICODE,
)

# Séparateur de phrase — évite les abréviations fréquentes ("M.", "Mme.", "etc.")
# Approximation raisonnable pour des emails (pas de parseur linguistique complet).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-Ÿ])")

_WORD_RE = re.compile(r"\b[\wÀ-ÿ']+\b", flags=re.UNICODE)

_BULLET_LINE_RE = re.compile(r"^\s*(?:[-•*]|\d+\.)\s+\S", flags=re.MULTILINE)

# Marqueurs de formalité (poids positif → formel, négatif → casual)
_FORMAL_MARKERS = [
    # Vouvoiement
    r"\bvous\b", r"\bvotre\b", r"\bvos\b", r"\bveuillez\b",
    # Formules
    r"\bmadame\b", r"\bmonsieur\b", r"\bcher\b", r"\bchère\b",
    r"\bcordialement\b", r"\bdistingué", r"\brespectueus",
    r"\bje vous prie\b", r"\bbien à vous\b",
    r"\bsuite à\b", r"\bconcernant\b",
]

_CASUAL_MARKERS = [
    # Tutoiement
    r"\btu\b", r"\bton\b", r"\btes\b", r"\bt'\w", r"\bt'as\b",
    # Salutations casual
    r"\bsalut\b", r"\bhey\b", r"\byo\b", r"\bcoucou\b",
    # Clôtures casual
    r"\bbises\b", r"\bbisous\b", r"\b(?:à\s+plus|a\+)\b",
    # Contractions / registre parlé
    r"\bouais\b", r"\bbah\b", r"\btrop\b", r"\bgénial\b", r"\bsuper\b",
]

_FORMAL_RE = [re.compile(p, flags=re.IGNORECASE) for p in _FORMAL_MARKERS]
_CASUAL_RE = [re.compile(p, flags=re.IGNORECASE) for p in _CASUAL_MARKERS]


# ---------------------------------------------------------------------------
# Patterns d'anonymisation (ordre d'application : URL → EMAIL → TEL → MONTANT → NOM)
# ---------------------------------------------------------------------------

_URL_RE = re.compile(
    r"https?://[^\s<>\"'()]+|www\.[^\s<>\"'()]+",
    flags=re.IGNORECASE,
)

_EMAIL_RE = re.compile(
    r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b",
    flags=re.IGNORECASE,
)

# Tel FR (06/01/etc. avec séparateurs) ou international (+33 …).
# Exige EXACTEMENT 10 chiffres pour FR (0X + 8 chiffres) ou +CC + 9 chiffres
# pour l'international → évite de matcher dates (2024), codes postaux (75001),
# montants (42,50), numéros de commande (issue #187 review finding F8).
_PHONE_RE = re.compile(
    r"(?<!\w)"                                # pas de caractère word juste avant
    r"(?:"
    # Format FR : 0X XX XX XX XX (5 groupes de 2 chiffres, séparateurs homogènes ou mixtes)
    r"0\d(?:[\s.-]?\d{2}){4}"
    r"|"
    # Format international : +CC suivi de 9-10 chiffres séparés
    r"\+\d{1,3}[\s.-]?\d(?:[\s.-]?\d{2}){4}"
    r")"
    r"(?!\d)"                                 # pas de chiffre juste après
)

# Montants : 1 500 €, 42,50 €, $5,000, £100
_AMOUNT_RE = re.compile(
    r"(?:"
    r"[€$£]\s*\d[\d\s,.]*"            # symbole avant : $5,000
    r"|"
    r"\d[\d\s,.]*\s*(?:€|EUR|USD|\$|CAD|GBP|£|CHF)"  # montant avant symbole
    r")",
    flags=re.IGNORECASE,
)

# Nom après formule d'adresse (FR + EN), gère prénoms composés
_NAME_AFTER_GREETING_RE = re.compile(
    r"(\b(?:Bonjour|Salut|Hey|Hi|Hello|Cher|Chère|Monsieur|Madame|Mme|M\.)\s+)"
    r"([A-ZÀ-Ÿ][a-zà-ÿ]+(?:[-\s][A-ZÀ-Ÿ][a-zà-ÿ]+){0,2})",
)


# ---------------------------------------------------------------------------
# Buckets de longueur
# ---------------------------------------------------------------------------

_SHORT_MAX_WORDS = 40
_MEDIUM_MAX_WORDS = 150


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class StyleInferenceService:
    """
    Analyse un corpus d'emails envoyés et produit des métriques de style.

    Usage:
        service = StyleInferenceService()
        metrics = service.analyze_outbox(sent_emails)
        # → {'formality_score': 0.72, 'avg_sentence_length': 15.3, ...}
    """

    def analyze_outbox(self, emails: Sequence[_HasBodyText]) -> Dict[str, float]:
        """Calcule les métriques lexicales sur un corpus d'emails.

        Le corpus doit être une séquence matérialisée (liste/tuple), pas un
        générateur — on itère plusieurs fois sur bodies pour calculer chaque
        métrique indépendamment.
        """
        bodies = [self._clean_body(e) for e in emails]
        bodies = [b for b in bodies if b]

        if not bodies:
            return self._neutral_metrics()

        sentence_lengths = self._collect_sentence_lengths(bodies)
        avg_sentence_length = statistics.fmean(sentence_lengths) if sentence_lengths else 0.0
        sentence_length_variance = (
            statistics.pstdev(sentence_lengths) if len(sentence_lengths) > 1 else 0.0
        )

        vocabulary_density = self._vocabulary_density(bodies)
        formality_score = self._formality_score(bodies)
        emoji_rate = self._mean(len(_EMOJI_RE.findall(b)) for b in bodies)
        exclamation_rate = self._mean(b.count("!") for b in bodies)
        bullet_usage_rate = sum(
            1 for b in bodies if _BULLET_LINE_RE.search(b)
        ) / len(bodies)
        avg_paragraph_count = self._mean(
            max(1, len([p for p in b.split("\n\n") if p.strip()])) for b in bodies
        )

        return {
            "avg_sentence_length": round(avg_sentence_length, 3),
            "sentence_length_variance": round(sentence_length_variance, 3),
            "vocabulary_density": round(vocabulary_density, 3),
            "formality_score": round(formality_score, 3),
            "emoji_rate": round(emoji_rate, 3),
            "exclamation_rate": round(exclamation_rate, 3),
            "bullet_usage_rate": round(bullet_usage_rate, 3),
            "avg_paragraph_count": round(avg_paragraph_count, 3),
        }

    # -----------------------------------------------------------------------
    # Anonymisation
    # -----------------------------------------------------------------------

    @staticmethod
    def anonymize_text(text: str) -> str:
        """
        Redacte irréversiblement les données sensibles avec placeholders.

        Ordre d'application : URL → EMAIL → TEL → MONTANT → PERSONNE.
        L'ordre compte : appliquer URL avant EMAIL évite qu'une URL avec '@'
        soit redactée en deux passes.
        """
        if not text:
            return text
        out = _URL_RE.sub("[URL]", text)
        out = _EMAIL_RE.sub("[EMAIL]", out)
        out = _PHONE_RE.sub("[TEL]", out)
        out = _AMOUNT_RE.sub("[MONTANT]", out)
        out = _NAME_AFTER_GREETING_RE.sub(r"\1[PERSONNE]", out)
        return out

    # -----------------------------------------------------------------------
    # Sélection d'exemples-référence
    # -----------------------------------------------------------------------

    def select_reference_examples(
        self, emails: Sequence[_HasBodyText]
    ) -> List[ReferenceExample]:
        """
        Sélectionne jusqu'à 3 exemples anonymisés (short / medium / long).

        Pour chaque bucket, on prend l'email le plus proche de la médiane
        du bucket (évite les outliers). Si un bucket est vide, il est omis.
        Tous les exemples retournés sont anonymisés.

        Le corpus doit être une séquence matérialisée (pas un générateur) —
        sinon les méthodes de bucketing et de médiane ne peuvent pas opérer.
        """
        bucketed: Dict[str, List[Tuple[int, _HasBodyText]]] = {
            "short": [],
            "medium": [],
            "long": [],
        }

        for email in emails:
            body = self._clean_body(email)
            if not body:
                continue
            wc = len(_WORD_RE.findall(body))
            if wc == 0:
                continue
            bucket = self._bucket_for(wc)
            bucketed[bucket].append((wc, email))

        examples: List[ReferenceExample] = []
        for bucket_name in ("short", "medium", "long"):
            candidates = bucketed[bucket_name]
            if not candidates:
                continue
            picked_wc, picked_email = self._pick_median(candidates)
            body = self._clean_body(picked_email)
            subject = getattr(picked_email, "subject", "") or ""
            source_email_id = (
                getattr(picked_email, "email_id", None)
                or getattr(picked_email, "id", None)
                or None
            )
            examples.append(
                ReferenceExample(
                    length_bucket=bucket_name,  # type: ignore[arg-type]
                    body_excerpt=self.anonymize_text(body),
                    subject=self.anonymize_text(subject),
                    anonymized=True,
                    word_count=picked_wc,
                    source_email_id=str(source_email_id)[:255] if source_email_id else None,
                )
            )
        return examples

    @staticmethod
    def _bucket_for(word_count: int) -> str:
        if word_count <= _SHORT_MAX_WORDS:
            return "short"
        if word_count <= _MEDIUM_MAX_WORDS:
            return "medium"
        return "long"

    @staticmethod
    def _pick_median(
        candidates: List[Tuple[int, _HasBodyText]],
    ) -> Tuple[int, _HasBodyText]:
        word_counts = [wc for wc, _ in candidates]
        median_wc = statistics.median(word_counts)
        return min(candidates, key=lambda pair: abs(pair[0] - median_wc))

    # -----------------------------------------------------------------------
    # Helpers privés
    # -----------------------------------------------------------------------

    @staticmethod
    def _neutral_metrics() -> Dict[str, float]:
        return {
            "avg_sentence_length": 0.0,
            "sentence_length_variance": 0.0,
            "vocabulary_density": 0.0,
            "formality_score": 0.5,
            "emoji_rate": 0.0,
            "exclamation_rate": 0.0,
            "bullet_usage_rate": 0.0,
            "avg_paragraph_count": 0.0,
        }

    @staticmethod
    def _clean_body(email: _HasBodyText) -> str:
        body = getattr(email, "body_text", "") or ""
        if not isinstance(body, str):
            return ""
        return body.strip()

    @staticmethod
    def _mean(values: Iterable[float]) -> float:
        seq = list(values)
        return sum(seq) / len(seq) if seq else 0.0

    @staticmethod
    def _collect_sentence_lengths(bodies: List[str]) -> List[int]:
        lengths: List[int] = []
        for body in bodies:
            sentences = _SENTENCE_SPLIT_RE.split(body)
            for sentence in sentences:
                words = _WORD_RE.findall(sentence)
                if words:
                    lengths.append(len(words))
        return lengths

    @staticmethod
    def _vocabulary_density(bodies: List[str]) -> float:
        """Type-token ratio (TTR) : mots uniques / total mots.

        Note : le TTR brut est biaisé par la taille du corpus — il décroît
        mécaniquement à mesure que le corpus grandit (plus on ajoute de texte,
        plus la probabilité de rencontrer un mot déjà vu augmente). Pour un
        usage strict de comparaison entre utilisateurs avec volumes très
        différents, utiliser plutôt MATTR ou MTLD (hors scope ici — le volume
        est borné à 500 emails, donc le TTR reste interprétable).

        Implémentation streaming via set() + compteur, évite de matérialiser
        la liste complète des tokens en mémoire.
        """
        unique_tokens: set[str] = set()
        total_tokens = 0
        for body in bodies:
            for token in _WORD_RE.findall(body):
                unique_tokens.add(token.lower())
                total_tokens += 1
        if total_tokens == 0:
            return 0.0
        return len(unique_tokens) / total_tokens

    @staticmethod
    def _formality_score(bodies: List[str]) -> float:
        """
        Score de formalité continu [0, 1] agrégé sur le corpus.

        Calcul :
          - Compte les marqueurs formels et casuals dans tout le corpus.
          - Ajoute des pénalités casual pour emojis et exclamations fréquents.
          - Normalise via sigmoïde pour rester borné.
        """
        formal_hits = sum(
            len(pattern.findall(body)) for body in bodies for pattern in _FORMAL_RE
        )
        casual_hits = sum(
            len(pattern.findall(body)) for body in bodies for pattern in _CASUAL_RE
        )

        emoji_count = sum(len(_EMOJI_RE.findall(body)) for body in bodies)
        exclamation_count = sum(body.count("!") for body in bodies)

        # Pénalité casual : emojis comptent comme marqueurs casuals supplémentaires
        casual_hits += emoji_count * 2
        # Pénalité casual modeste pour les exclamations (évite d'écraser le signal)
        casual_hits += exclamation_count // 2

        total = formal_hits + casual_hits
        if total == 0:
            return 0.5

        # Ratio brut ∈ [0, 1]
        raw = formal_hits / total
        # Lissage léger vers 0.5 pour éviter 0.0 / 1.0 en bordure
        return 0.05 + 0.9 * raw
