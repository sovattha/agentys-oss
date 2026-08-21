# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Entités pour l'analyse du style d'écriture personnel.

Ce module définit les entités métier pour l'apprentissage et la représentation
du style d'écriture unique de chaque utilisateur basé sur ses emails envoyés.
"""

import re as _re
from dataclasses import InitVar, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

# ---------------------------------------------------------------------------
# Détection automatique de variante linguistique
# ---------------------------------------------------------------------------

_SIGNATURE_VARIANTS = [
    ('fr-CA', [r'\bqu[eé]bec\b', r'\bqc\b', r'\bmontr[eé]al\b', r'\blaval\b',
               r'\blongueuil\b', r'\bgatineau\b', r'\bsherbrooke\b', r'\bsaguenay\b']),
    ('fr-FR', [r'\bfrance\b', r'\bparis\b', r'\blyon\b', r'\bmarseille\b',
               r'\btoulouse\b', r'\bnantes\b', r'\blille\b', r'\bcedex\b', r'\brennes\b']),
    ('fr-BE', [r'\bbelgique\b', r'\bbruxelles\b', r'\bli[eè]ge\b',
               r'\bantwerp\b', r'\bgand\b', r'\bghent\b']),
    ('fr-CH', [r'\bsuisse\b', r'\bschweiz\b', r'\bgen[eè]ve\b', r'\bzurich\b',
               r'\bberne\b', r'\blausanne\b']),
    ('en-GB', [r'\bunited kingdom\b', r'\blondon\b', r'\bbirmingham\b',
               r'\bmanchester\b', r'\bedinburgh\b', r'\bglasgow\b']),
    ('es-ES', [r'\bespa[gñ]a\b', r'\bspain\b', r'\bmadrid\b', r'\bbarcelona\b',
               r'\bseville\b', r'\bvalencia\b']),
    ('en-AU', [r'\baustralia\b', r'\baudstralie\b', r'\bsydney\b', r'\bmelbourne\b',
               r'\bbrisbane\b', r'\bperth\b']),
]


def detect_variant_from_signature(signature_text: str) -> str:
    """Detect variant from signature text. Returns ISO code (e.g. 'fr-CA') or ''."""
    text = signature_text.lower()
    for iso_code, patterns in _SIGNATURE_VARIANTS:
        for pat in patterns:
            if _re.search(pat, text):
                return iso_code
    return ''


def detect_variant_from_domain(email_address: str) -> str:
    """Detect variant from email domain. Returns ISO code (e.g. 'fr-CA') or ''."""
    domain = email_address.split('@')[-1].lower() if '@' in email_address else ''
    if '.qc.ca' in domain or '.gouv.qc.ca' in domain:
        return 'fr-CA'
    if domain.endswith('.fr') or '.gouv.fr' in domain:
        return 'fr-FR'
    if domain.endswith('.be'):
        return 'fr-BE'
    if domain.endswith('.ch'):
        return 'fr-CH'
    if domain.endswith('.co.uk') or domain.endswith('.uk'):
        return 'en-GB'
    if domain.endswith('.es'):
        return 'es-ES'
    if domain.endswith('.com.br') or domain.endswith('.br'):
        return 'pt-BR'
    if domain.endswith('.com.au') or domain.endswith('.au'):
        return 'en-AU'
    if domain.endswith('.mx'):
        return 'es-MX'
    return ''


class FormalityLevel(str, Enum):
    """Niveau de formalité du style d'écriture."""
    FORMAL = "formal"      # Vouvoiement, formules complètes
    CASUAL = "casual"      # Tutoiement, contractions, décontracté
    MIXED = "mixed"        # Semi-formel : mélange selon le contexte


LengthBucket = Literal["short", "medium", "long"]


@dataclass
class ReferenceExample:
    """
    Exemple-référence anonymisé extrait de l'outbox pour le few-shot du DrafterAgent.

    Sélectionné parmi les emails envoyés par l'utilisateur, anonymisé (noms propres,
    emails, téléphones, montants) puis utilisé dans le prompt en mode few-shot pour
    capturer le style réel de l'utilisateur plutôt que des labels explicites.

    Attributes:
        length_bucket: "short" (≤40 mots), "medium" (40-150), "long" (>150).
        body_excerpt: Corps de l'email anonymisé.
        subject: Sujet de l'email anonymisé.
        anonymized: Flag de sécurité — must be set to True explicitly by the
            inference path AFTER anonymization. Default False : un appelant qui
            oublie de le flagger ne fuite PAS — `_filter_anonymized_examples`
            rejette l'exemple silencieusement.
        word_count: Nombre de mots du corps (avant anonymisation).
        collected_at: Timestamp ISO de création de l'exemple dérivé.
        source_email_id: ID provider du message source, sans contenu.
    """

    length_bucket: LengthBucket
    body_excerpt: str
    subject: str
    anonymized: bool = False
    word_count: int = 0
    collected_at: Optional[str] = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    source_email_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "length_bucket": self.length_bucket,
            "body_excerpt": self.body_excerpt,
            "subject": self.subject,
            "anonymized": self.anonymized,
            "word_count": self.word_count,
            "collected_at": self.collected_at,
            "source_email_id": self.source_email_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReferenceExample":
        return cls(
            length_bucket=data["length_bucket"],
            body_excerpt=data["body_excerpt"],
            subject=data["subject"],
            anonymized=data.get("anonymized", False),
            word_count=data.get("word_count", 0),
            collected_at=data.get("collected_at"),
            source_email_id=data.get("source_email_id"),
        )


@dataclass
class ContactStyleProfile:
    """
    Style de communication adapté à un contact spécifique.

    Appris automatiquement de l'historique des emails envoyés à ce contact.
    """
    email: str
    formality_override: Optional[FormalityLevel] = None
    preferred_greeting: Optional[str] = None
    preferred_closing: Optional[str] = None
    preferred_signature: Optional[str] = None
    langue_variante: Optional[str] = None
    langue: Optional[str] = None  # spoken language: 'francais', 'anglais', or None (auto)
    nickname: Optional[str] = None
    # Auto-derivation flags for `formality_override` (see
    # `app/services/writing_style.py::update_contact_formality_from_send`).
    # When `formality_locked == False`, the override is recomputed from the
    # most-recently-sent email body. Manual edits in the Training UI flip
    # `formality_locked = True` so the user's choice is respected.
    formality_locked: bool = False
    # ISO-8601 UTC timestamp of the last time `formality_override` was set
    # by the auto-derivation path or by a manual edit. Surfaced in the
    # Training UI as "Updated <relative-date>".
    formality_updated_at: Optional[str] = None
    # PR5 — stability filter. The previous `last sent email wins` policy
    # flipped the override on every dissenting send (a one-line "ok merci"
    # could turn a Formal client into Casual). Now a divergent measurement
    # is parked on `formality_pending` first and only promoted to
    # `formality_override` when a SECOND consecutive send agrees. A virgin
    # override (None) bypasses the buffer — the first measurement is taken
    # at face value because there is no prior signal to disagree with.
    formality_pending: Optional[FormalityLevel] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "email": self.email,
            "formality_override": self.formality_override.value if self.formality_override else None,
            "preferred_greeting": self.preferred_greeting,
            "preferred_closing": self.preferred_closing,
            "preferred_signature": self.preferred_signature,
            "langue_variante": self.langue_variante,
            "langue": self.langue,
            "nickname": self.nickname,
            "formality_locked": self.formality_locked,
            "formality_updated_at": self.formality_updated_at,
            "formality_pending": self.formality_pending.value if self.formality_pending else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContactStyleProfile":
        # Legacy profiles may carry deprecated keys (`email_count`,
        # `relationship_tier`, `superior`/`subordinate` tiers). Just ignore
        # them — they are no longer part of the entity.
        # `formality_locked` / `formality_updated_at` / `formality_pending`
        # default safely so old payloads still round-trip without a migration
        # script.
        return cls(
            email=data["email"],
            formality_override=FormalityLevel(data["formality_override"]) if data.get("formality_override") else None,
            preferred_greeting=data.get("preferred_greeting"),
            preferred_closing=data.get("preferred_closing"),
            preferred_signature=data.get("preferred_signature"),
            langue_variante=data.get("langue_variante"),
            langue=data.get("langue"),
            nickname=data.get("nickname"),
            formality_locked=bool(data.get("formality_locked", False)),
            formality_updated_at=data.get("formality_updated_at"),
            formality_pending=FormalityLevel(data["formality_pending"]) if data.get("formality_pending") else None,
        )

    # PR3 follow-up — `to_prompt_hint()` was removed. The localized fr/en
    # equivalent lives in :func:`app.prompts.style_guidance.build_contact_hint_block`.
    # All callsites of `to_prompt_hint()` (none remained inside `app/`, only
    # tests) have been migrated to the free function in style_guidance.


@dataclass
class WritingStyleProfile:
    """
    Profil de style d'écriture d'un utilisateur.

    Représente les caractéristiques du style d'écriture extraites
    de l'analyse des emails envoyés par l'utilisateur.

    Attributes:
        account_id: ID du compte email analysé.
        analyzed_at: Timestamp de la dernière analyse.
        email_count: Nombre d'emails analysés.
        common_words: Mots et expressions fréquemment utilisés.
        avg_sentence_length: Longueur moyenne des phrases (en mots).
        formality_level: Niveau de formalité détecté.
        preferred_greetings: Salutations préférées.
        preferred_closings: Formules de clôture préférées.
        typical_signature: Signature typique si détectée.
        avg_email_length: Longueur moyenne des emails (en caractères).
        analysis_duration_ms: Durée de l'analyse en millisecondes.

    Champs supprimés (PR4 follow-up) :
        - ``humor_level`` + enum ``HumorLevel`` — never populated.
        - ``uses_contractions`` / ``uses_emojis`` — extracted by the LLM but
          never consumed in any prompt after PR3 fusion.
        - ``bullet_list_ratio`` — written by 2 paths, never read after PR3.
        - ``avg_response_time_hours`` — never populated.
        - ``rejected_drafts_count`` + ``record_draft_rejection`` +
          ``rejection_rate`` — collected on draft rejection, never consumed.
    Les fichiers JSON legacy contenant ces clés sont chargés sans erreur
    (``from_dict`` les ignore via ``dict.get`` qui ne référence plus le champ).
    """
    account_id: int
    analyzed_at: datetime
    email_count: int
    common_words: List[str] = field(default_factory=list)
    avg_sentence_length: float = 0.0
    formality_level: FormalityLevel = FormalityLevel.MIXED
    preferred_greetings: List[str] = field(default_factory=list)
    preferred_closings: List[str] = field(default_factory=list)
    typical_signature: Optional[str] = None
    avg_email_length: int = 0
    analysis_duration_ms: int = 0
    # --- Dimensions enrichies (issue #39) ---
    # PR2 sentinel — None = jamais mesuré (le consumer skip la ligne emoji)
    # vs 0.0 = mesure réelle "aucun emoji utilisé".
    emoji_frequency: Optional[float] = None  # Ratio emojis par email (0.0 = jamais, 3.0+ = fréquent)
    # PR6 — `contact_profiles` is no longer a stored field. It is exposed as a
    # property (defined below) that returns a dict-like view backed by the
    # SQLite ``contact_styles`` table. The InitVar accepts the same kwarg
    # for back-compat (``WritingStyleProfile(contact_profiles={...})``) and
    # ``__post_init__`` migrates the data into the store via the view's
    # ``update`` method. The property is defined OUTSIDE the dataclass body
    # to avoid ``InitVar`` / property name collision at class-creation time.
    contact_profiles: InitVar[Optional[Dict[str, Any]]] = None
    # --- Dimensions issue #187 (apprentissage implicite depuis l'outbox) ---
    # Sentinel `None` = inference never ran (cf. `style_guidance.py` skips
    # the corresponding line). Don't conflate "not measured" with a measured
    # value of 0.5 / 0.0 — the LLM should not be told "style mixte" by default
    # when we simply have no data.
    sentence_length_variance: Optional[float] = None  # Écart-type longueur phrases (mots)
    vocabulary_density: Optional[float] = None  # Type-token ratio, 0-1
    formality_score: Optional[float] = None  # 0 = très casual, 1 = très formel (continu)
    exclamation_rate: Optional[float] = None  # Moyenne de "!" par email
    avg_paragraph_count: Optional[float] = None  # Moyenne de paragraphes par email
    reference_examples: List[ReferenceExample] = field(default_factory=list)

    def __post_init__(self, contact_profiles: Optional[Dict[str, Any]] = None):
        """Validation après initialisation + migration des contact_profiles
        legacy vers le SQLite store via la vue.

        Args:
            contact_profiles: InitVar populated by the caller. When provided
                (legacy ``WritingStyleProfile(contact_profiles={...})`` call
                style or ``from_dict`` of a legacy JSON payload), the entries
                are bulk-loaded into the SQLite store on first use of the
                view. In test contexts where the Container is unavailable,
                the view falls back to an in-memory dict transparently.
        """
        if self.account_id <= 0:
            raise ValueError("account_id must be positive")
        if self.email_count < 0:
            raise ValueError("email_count must be non-negative")
        if self.avg_sentence_length < 0:
            raise ValueError("avg_sentence_length must be non-negative")
        if self.avg_email_length < 0:
            raise ValueError("avg_email_length must be non-negative")
        if self.analysis_duration_ms < 0:
            raise ValueError("analysis_duration_ms must be non-negative")
        # Optional[float] sentinel: None means "not measured" — only validate
        # when an actual value is set, so legacy callsites that never populated
        # the field don't trip the bound check.
        if self.formality_score is not None and not 0.0 <= self.formality_score <= 1.0:
            raise ValueError("formality_score must be between 0.0 and 1.0")
        # Convert string formality to enum if needed
        if isinstance(self.formality_level, str):
            self.formality_level = FormalityLevel(self.formality_level)

        # PR6 — initialise the contact_profiles view (backed by SQLite when
        # the Container is wired, in-memory dict otherwise). Migration of
        # legacy init data is delegated to the view's ``update`` so the
        # entity stays decoupled from the store implementation.
        from app.infrastructure.contact_profiles_view import _ContactProfilesView
        self._contact_profiles_view = _ContactProfilesView(self.account_id)
        # Defensive: when the caller does NOT pass `contact_profiles`,
        # ``InitVar`` resolves the default by reading the class attribute,
        # which is now the @property descriptor (same name). The runtime
        # value of the InitVar in that case is a ``property`` object, not
        # ``None``. We accept only an actual dict — anything else is treated
        # as "no init data" and the view stays empty until callers populate
        # it via ``profile.contact_profiles[email] = data``.
        if isinstance(contact_profiles, dict) and contact_profiles:
            try:
                self._contact_profiles_view.update(contact_profiles)
            except Exception as exc:  # pragma: no cover — defensive
                # Migration must never block construction. Log and continue —
                # subsequent writes via the view will populate as expected.
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "Could not bulk-load contact_profiles for account %s: %s",
                    self.account_id, exc,
                )

    @property
    def contact_profiles(self):  # noqa: F811 — intentional InitVar/property co-name (PR6 SQLite migration)
        """Dict-like view of per-contact style profiles, backed by SQLite.

        See :class:`app.infrastructure.contact_profiles_view._ContactProfilesView`
        for the supported operations. The accessor surface
        (``profile.contact_profiles.get(email)``,
        ``profile.contact_profiles[email] = data``,
        ``del profile.contact_profiles[email]``, iteration, ``.items()``,
        ``len()``) is identical to a plain ``dict`` so the ~25 existing
        callers continue to work unchanged.
        """
        return self._contact_profiles_view

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour sérialisation JSON."""
        return {
            "account_id": self.account_id,
            "analyzed_at": self.analyzed_at.isoformat(),
            "email_count": self.email_count,
            "common_words": self.common_words,
            "avg_sentence_length": self.avg_sentence_length,
            "formality_level": self.formality_level.value,
            "preferred_greetings": self.preferred_greetings,
            "preferred_closings": self.preferred_closings,
            "typical_signature": self.typical_signature,
            "avg_email_length": self.avg_email_length,
            "analysis_duration_ms": self.analysis_duration_ms,
            "emoji_frequency": self.emoji_frequency,
            # PR6 — snapshot the SQLite-backed view to a plain dict for JSON
            # serialization. The legacy JSON file layout is preserved so
            # existing readers (boot loaders, backup scripts) keep working
            # during the transition. Once the migration is fully validated,
            # this snapshot can drop to {} and the JSON shrinks accordingly.
            "contact_profiles": self._contact_profiles_view.snapshot(),
            "sentence_length_variance": self.sentence_length_variance,
            "vocabulary_density": self.vocabulary_density,
            "formality_score": self.formality_score,
            "exclamation_rate": self.exclamation_rate,
            "avg_paragraph_count": self.avg_paragraph_count,
            "reference_examples": [ex.to_dict() for ex in self.reference_examples],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WritingStyleProfile":
        """Crée une instance depuis un dictionnaire."""
        analyzed_at = data["analyzed_at"]
        if isinstance(analyzed_at, str):
            analyzed_at = datetime.fromisoformat(analyzed_at)

        return cls(
            account_id=data["account_id"],
            analyzed_at=analyzed_at,
            email_count=data["email_count"],
            common_words=data.get("common_words", []),
            avg_sentence_length=data.get("avg_sentence_length", 0.0),
            formality_level=FormalityLevel(data.get("formality_level", "mixed")),
            preferred_greetings=data.get("preferred_greetings", []),
            preferred_closings=data.get("preferred_closings", []),
            typical_signature=data.get("typical_signature"),
            avg_email_length=data.get("avg_email_length", 0),
            analysis_duration_ms=data.get("analysis_duration_ms", 0),
            # PR4 follow-up — `humor_level`, `uses_contractions`, `uses_emojis`,
            # `bullet_list_ratio`, `avg_response_time_hours`, `rejected_drafts_count`
            # all removed. Legacy JSON keys are silently ignored : `from_dict`
            # simply doesn't reference them, so old payloads round-trip cleanly.
            # PR2 sentinel — keys absent in legacy JSON load as None to signal
            # "never measured" ; explicit zeros in the JSON keep their meaning.
            emoji_frequency=data.get("emoji_frequency"),
            contact_profiles=data.get("contact_profiles", {}),
            # Issue #187 sentinel migration: legacy JSON files persist explicit
            # zeros / 0.5 for these fields — those are *measured* values and we
            # keep them. Only when the key is *absent* do we fall back to None,
            # which signals "never measured" to `style_guidance.py`. New empty
            # profiles created via `create_empty()` get None directly.
            sentence_length_variance=data.get("sentence_length_variance"),
            vocabulary_density=data.get("vocabulary_density"),
            formality_score=data.get("formality_score"),
            exclamation_rate=data.get("exclamation_rate"),
            avg_paragraph_count=data.get("avg_paragraph_count"),
            reference_examples=[
                ReferenceExample.from_dict(ex) if isinstance(ex, dict) else ex
                for ex in data.get("reference_examples", [])
            ],
        )

    @classmethod
    def create_empty(cls, account_id: int) -> "WritingStyleProfile":
        """Crée un profil vide pour un nouveau compte.

        Args:
            account_id: ID du compte email.

        Returns:
            WritingStyleProfile avec valeurs par défaut.
        """
        return cls(
            account_id=account_id,
            analyzed_at=datetime.utcnow(),
            email_count=0,
        )

    def merge_with_new_email(
        self,
        new_words: List[str],
        new_greetings: List[str],
        new_closings: List[str],
        new_email_length: int,
        new_sentence_length: float,
    ) -> None:
        """Met à jour le profil avec les données d'un nouvel email.

        Mise à jour incrémentale plutôt que re-analyse complète.

        Args:
            new_words: Mots caractéristiques du nouvel email.
            new_greetings: Salutations détectées.
            new_closings: Formules de clôture détectées.
            new_email_length: Longueur du nouvel email.
            new_sentence_length: Longueur moyenne des phrases.
        """
        # Mise à jour moyenne pondérée pour email_length
        if self.email_count > 0:
            total_length = self.avg_email_length * self.email_count + new_email_length
            self.avg_email_length = int(total_length / (self.email_count + 1))

            total_sentence = self.avg_sentence_length * self.email_count + new_sentence_length
            self.avg_sentence_length = total_sentence / (self.email_count + 1)
        else:
            self.avg_email_length = new_email_length
            self.avg_sentence_length = new_sentence_length

        # Ajouter les nouveaux mots (garder top 20)
        word_freq: Dict[str, int] = {}
        for word in self.common_words:
            word_freq[word] = word_freq.get(word, 0) + 2  # Poids plus élevé pour existants
        for word in new_words:
            word_freq[word] = word_freq.get(word, 0) + 1
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        self.common_words = [w for w, _ in sorted_words[:20]]

        # Ajouter salutations uniques (garder top 5)
        for greeting in new_greetings:
            if greeting not in self.preferred_greetings:
                self.preferred_greetings.append(greeting)
        self.preferred_greetings = self.preferred_greetings[:5]

        # Ajouter formules de clôture uniques (garder top 5)
        for closing in new_closings:
            if closing not in self.preferred_closings:
                self.preferred_closings.append(closing)
        self.preferred_closings = self.preferred_closings[:5]

        self.email_count += 1
        self.analyzed_at = datetime.utcnow()

    # PR3 follow-up — `to_prompt_context()` was removed. The unified renderer
    # lives in :func:`app.prompts.style_guidance.build_style_guidance_from_profile`
    # and emits continuous metrics + anonymized few-shot + per-contact hint
    # (localised fr/en). All 7 internal callsites (smart_routing.py × 3,
    # routes_drafts.py, routes_misc.py, _compose_path.py, writing_style_service)
    # have been migrated to the free function.


    def is_sufficient(self, min_emails: int = 3) -> bool:
        """Vérifie si le profil a assez de données pour être utilisé.

        Args:
            min_emails: Nombre minimum d'emails analysés requis.

        Returns:
            True si le profil est suffisamment riche.
        """
        return self.email_count >= min_emails

    def update_contact_profile(
        self,
        email: str,
        formality_override: Optional[FormalityLevel] = None,
        greeting: Optional[str] = None,
        closing: Optional[str] = None,
        signature: Optional[str] = None,
        langue_variante: Optional[str] = None,
        langue: Optional[str] = None,
        nickname: Optional[str] = None,
        formality_locked: Optional[bool] = None,
    ) -> None:
        """Met à jour le profil de style pour un contact spécifique.

        ``formality_locked`` :
          - ``None`` (default) : flag laissé tel quel — utilisé par les
            paths automatiques (analyzer, etc.) qui ne touchent pas au lock.
          - ``True`` : lock activé et ``formality_updated_at`` rafraîchi —
            une édition manuelle dans l'UI Training doit toujours passer
            ``True`` pour stopper l'auto-derivation côté envoi.
          - ``False`` : lock relâché. La prochaine envoi recalcule le
            ``formality_override`` à partir du corps. La valeur courante
            n'est pas effacée — l'utilisateur la voit jusqu'au prochain
            send qui produit un niveau différent.
        """
        from datetime import datetime, timezone

        key = email.lower()
        if key in self.contact_profiles:
            profile = ContactStyleProfile.from_dict(self.contact_profiles[key])
        else:
            profile = ContactStyleProfile(email=key)

        formality_changed = False
        if formality_override is not None and profile.formality_override != formality_override:
            profile.formality_override = formality_override
            formality_changed = True
        if greeting == "":
            profile.preferred_greeting = None
        elif greeting:
            profile.preferred_greeting = greeting
        if closing == "":
            profile.preferred_closing = None
        elif closing:
            profile.preferred_closing = closing
        if signature == "":
            profile.preferred_signature = None
        elif signature:
            profile.preferred_signature = signature
        if langue_variante == "":
            profile.langue_variante = None
        elif langue_variante:
            profile.langue_variante = langue_variante
        if langue == "":
            profile.langue = None
        elif langue:
            profile.langue = langue
        if nickname == "":
            profile.nickname = None
        elif nickname:
            profile.nickname = nickname

        if formality_locked is not None:
            profile.formality_locked = bool(formality_locked)
        # Stamp the timestamp whenever formality changed (manual or via
        # this method's call) OR whenever the user is explicitly re-locking
        # the field. Auto-derivation has its own update path in
        # `app/services/contact_formality.py` and won't reach this branch.
        if formality_changed or formality_locked is True:
            profile.formality_updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

        # NOTE: do NOT increment email_count here. This field is meant to
        # track the number of emails *analyzed* for this contact (set by the
        # writing-style analyzer when it processes the mailbox history).
        # Bumping it on every user-initiated PUT turned it into a "save
        # counter" which is meaningless and misleading in the UI.
        self.contact_profiles[key] = profile.to_dict()

    # PR4 follow-up — `record_draft_rejection` and `rejection_rate` removed
    # along with `rejected_drafts_count`. The counter was incremented on every
    # draft rejection (`routes_pending.py:825`) but never read anywhere — pure
    # write-only state. Draft rejection learning lives in `app/draft_learning`
    # which is a separate, consumed pipeline.
