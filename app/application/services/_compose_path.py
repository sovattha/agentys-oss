"""Helpers privés du DraftService pour le mode compose (Phase 2b).

Sépare la logique de construction de prompts compose pour garder
draft_service.py focalisé sur l'orchestration. Pas d'API publique —
ces helpers ne sont consommés que par DraftService.

Décisions verrouillées (cf. docs/draft-pipeline-phases.md) :
- KB compose = section ## Savoir uniquement (extract_savoir_section)
- Per-contact overrides : nickname / preferred_greeting / formality_override
  appliqués via mandatory_opening + tone_directive (mirror routes_misc.py)
- Self-Critique = shadow mode, n'escalade jamais en compose

Audit 2026-05-04 (P1.4 + P2.8) : self-critique passe de 100% → 10% sampling
(`SELF_CRITIQUE_SAMPLE_RATE`). Sur la fraction sampled, si le score est sous
`SELF_CRITIQUE_REGEN_THRESHOLD` ET au moins un risque actionnable est détecté,
on déclenche 1 regen Drafter (cap dur à 1 retry). Rationale : 90% d'économie
sur l'auto-critique + qualité strictement améliorée sur les drafts à risque.
"""

from __future__ import annotations

import logging
import os
import random
import re
from typing import Any, Optional

from app.application.dto.draft_context import DraftContext
from app.domain.ports.llm_port import SystemPrompt, SystemSegment
from app.prompts.savoir_extractor import extract_savoir_section

logger = logging.getLogger(__name__)


# P1.4 — Self-critique sampling. Override via env for ops tuning (eg. raise to
# 1.0 in staging to validate prompt drift after a model upgrade).
#
# 2026-05-05: introduced SELF_CRITIQUE_MODE as a clearer alias —
#   off    → sample_rate = 0.0  (no critique calls, no regen)
#   shadow → sample_rate = 0.10 (current default — observe + regen on sampled)
#   active → sample_rate = 1.0  (every draft is self-critiqued + regen-eligible)
# SELF_CRITIQUE_SAMPLE_RATE still wins if both are set, so ops can pin a
# specific rate (e.g. 0.25 for a partial rollout). Pre-condition for flipping
# to "active": run scripts/eval_drafting.py on the 6 personas and confirm
# overall score holds within ±5 pts (LLM-judge variance baseline).
_MODE_TO_RATE = {"off": 0.0, "shadow": 0.10, "active": 1.0}


def _get_sample_rate() -> float:
    explicit = os.getenv("SELF_CRITIQUE_SAMPLE_RATE")
    if explicit is not None and explicit.strip() != "":
        try:
            rate = float(explicit)
        except (TypeError, ValueError):
            rate = 0.10
        return max(0.0, min(1.0, rate))

    mode = (os.getenv("SELF_CRITIQUE_MODE") or "shadow").strip().lower()
    return _MODE_TO_RATE.get(mode, 0.10)


# P2.8 — Regen trigger: a sampled critique with self_score below this threshold
# AND at least one actionable risk regenerates the draft once. Threshold tuned
# from the 200-case eval at tasks/eval-critic-haiku-vs-sonnet-verdict-2026-05-04.md
# — score<60 catches the failure cluster (placeholder, language_drift) without
# false positives on stylistic-but-shippable drafts (score 60-80).
SELF_CRITIQUE_REGEN_THRESHOLD = 60

# Risks that warrant a regen (vs purely informational). `filler` and
# `length_excessive` are stylistic — we leave the user to decide.
_REGEN_TRIGGER_RISKS: frozenset[str] = frozenset({
    "hallucination",
    "placeholder",
    "tone_mismatch",
    "off_topic",
    "language_drift",
    "signature_doubled",
})


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

_BASE_SYSTEM_PROMPT = (
    "Tu es un assistant qui rédige des emails pour l'utilisateur. "
    "Tu écris UNIQUEMENT le corps du message, sans ligne 'Objet:'. "
    "Tu écris en français sauf si on te demande une autre langue. "
    "RÈGLE ABSOLUE — PAS DE SIGNATURE : n'écris JAMAIS le nom de "
    "l'expéditeur, son titre, ni aucune signature à la fin du "
    "message. Le corps doit se terminer par la formule de clôture "
    "(ex: «À bientôt,», «Cordialement,», «Merci,») et rien d'autre. "
    "La signature est ajoutée automatiquement par l'interface après "
    "génération. Ne mets JAMAIS '[Votre Nom]', '[Votre nom]', "
    "le prénom seul, le nom complet, ou «Co-fondateur» après la clôture."
)


def build_compose_system_prompt(
    style_context: str,
    knowledge_base: str,
    mandatory_opening: Optional[str],
    tone_directive: Optional[str],
    mandatory_closing: Optional[str] = None,
) -> list[SystemSegment]:
    """Construit le system prompt compose en segments cacheables.

    Retourne des `SystemSegment` pour permettre au ClaudeAdapter de placer un
    cache breakpoint à la fin de chaque segment.
    La segmentation est conçue pour maximiser le cache hit rate :

    - Segment 1 (très stable, partagé entre TOUS les composes d'un même user) :
      base prompt + Savoir KB. Hit cache à chaque compose.
    - Segment 2 (stable par contact) : style_context + per-contact overrides.
      Hit cache pour les composes successifs au MÊME destinataire.

    Si un segment est vide (ex: pas de KB, pas de style profile), il n'est
    pas ajouté — la liste peut donc contenir 1 ou 2 éléments.

    Inputs :
        style_context : output de build_style_guidance_from_profile(recipient_email)
        knowledge_base : KB markdown brute (memoire.md) — on en extrait Savoir
        mandatory_opening : ligne d'ouverture imposée si nickname custom
        tone_directive : directive de ton si formality_override per-contact
        mandatory_closing : clôture imposée si preferred_closing per-contact
            (règle dure, symétrique de mandatory_opening) — sinon le LLM
            retombe sur son défaut «À bientôt,» (cf. _BASE_SYSTEM_PROMPT).

    Le `style_context` peut contenir une mention du recipient — c'est intentionnel
    (cf. mirror routes_misc.py original). On NE neutralise PAS ce contenu car il
    vient du profile (data interne, pas user-controlled).
    """
    # ── Segment 1 : base + Savoir KB ─────────────────────────────────────
    seg1_parts = [_BASE_SYSTEM_PROMPT]
    savoir = extract_savoir_section(knowledge_base)
    if savoir:
        seg1_parts.append(
            "\n\n=== BASE DE CONNAISSANCES ===\n"
            + savoir
            + "Utilise ces faits factuels quand ils sont pertinents. Ne pas citer "
            "ce bloc verbatim — paraphrase naturellement."
        )
    segment_1 = "".join(seg1_parts)

    # ── Segment 2 : style_context + per-contact ──────────────────────────
    seg2_parts: list[str] = []
    if style_context:
        seg2_parts.append(
            f"{style_context}\n\n"
            "IMPORTANT : adapte obligatoirement le ton, la salutation et "
            "la clôture au style du destinataire décrit ci-dessus."
        )
    if mandatory_opening:
        seg2_parts.append(
            f"OUVERTURE OBLIGATOIRE : la première ligne du corps "
            f"DOIT être exactement «{mandatory_opening}» (pas «Salut,», "
            f"pas «Bonjour,», pas de prénom complet — ce surnom précis). "
            "C'est une règle non négociable."
        )
    if mandatory_closing:
        seg2_parts.append(
            f"CLÔTURE OBLIGATOIRE : le corps DOIT se terminer par exactement "
            f"«{mandatory_closing}» (pas «À bientôt,», pas «Cordialement,», "
            f"pas «Merci,» — cette formule précise) et RIEN après. La "
            "signature est ajoutée par l'interface. C'est une règle non "
            "négociable."
        )
    if tone_directive:
        seg2_parts.append(tone_directive)

    segments = [SystemSegment(segment_1)]
    if seg2_parts:
        segments.append(SystemSegment("\n\n".join(seg2_parts)))
    return segments


def _email_address_lower(part: str) -> str:
    """Pull out the lowercased email address from a "Name <email>" token,
    or return the bare email lowercased. Returns "" when no @ is present."""
    raw = (part or "").strip()
    if "<" in raw and ">" in raw:
        inner = raw.split("<", 1)[1].split(">", 1)[0]
        return inner.strip().lower()
    return raw.lower()


def _contact_formality_for(part: str, contact_profiles: Any) -> Optional[str]:
    """Return the formality_override ('casual'/'formal') stored for this
    recipient in contact_profiles, or None when unknown."""
    if contact_profiles is None:
        return None
    email = _email_address_lower(part)
    if not email or "@" not in email:
        return None
    try:
        cp = contact_profiles.get(email)
    except Exception:
        return None
    if not isinstance(cp, dict):
        return None
    raw = cp.get("formality_override")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower()
    return None


def _multi_recipient_greeting_hint(
    recipient_email: str,
    language: Optional[str],
    contact_profiles: Optional[Any] = None,
) -> Optional[str]:
    """Return greeting directive when composing to multiple recipients.

    1 recipient  → None (single-contact path or LLM decides).
    2 recipients →
        compatible registers ("formal+formal" or "casual+casual" both known)
        → "Bonjour {first1} et {first2}," / "Hi {first1} and {first2},"
        mixed registers, unknown signals, or `contact_profiles` not provided
        with at least one signal
        → "Bonjour," / "Hello,"  (register-neutral group greeting)
    3+           → "Bonjour à tous," / "Hello everyone,"

    Issue #592: naming both recipients when their tu/vous signals are
    mixed (or unknown) forces a register on one of them that may be
    wrong. Falling back to a generic group greeting is safer than
    addressing them by name with the wrong tone.
    """
    parts = [p.strip() for p in re.split(r"[,;]", recipient_email) if p.strip()]
    if len(parts) <= 1:
        return None

    is_english = (language or "").lower().startswith("en")

    if len(parts) >= 3:
        return "Hello everyone," if is_english else "Bonjour à tous,"

    # 2 recipients — decide whether to name them.
    can_name = True
    if contact_profiles is not None:
        # Strict register check (issue #592). Both contacts must have a
        # known matching formality_override; otherwise the group greeting
        # is safer.
        f1 = _contact_formality_for(parts[0], contact_profiles)
        f2 = _contact_formality_for(parts[1], contact_profiles)
        if not (f1 and f2 and f1 == f2):
            can_name = False

    if can_name:
        try:
            from app._prompts_monolith import _extract_display_name
            raw1 = _extract_display_name(parts[0])
            raw2 = _extract_display_name(parts[1])
            n1 = raw1.split()[0] if raw1 else ""
            n2 = raw2.split()[0] if raw2 else ""
        except Exception:
            n1, n2 = "", ""
        if n1 and n2:
            return f"Hi {n1} and {n2}," if is_english else f"Bonjour {n1} et {n2},"

    # Mixed/unknown registers OR couldn't derive both names → neutral group.
    return "Hello," if is_english else "Bonjour,"


def build_compose_user_prompt(
    ctx: DraftContext,
    mandatory_opening: Optional[str],
    mandatory_closing: Optional[str] = None,
) -> str:
    """Construit le user prompt compose."""
    sender_name = ctx.user_email.split("@")[0]  # Best-effort fallback
    user_prompt = (
        f"Rédige un nouveau email.\n"
        f"Expéditeur : {sender_name}\n"
        f"Destinataire : {ctx.recipient_email}\n"
        f"Objet : {ctx.subject}\n"
    )
    if ctx.instructions:
        # Issue #457 (Phase 1) — `ctx.instructions` is already chevron-
        # sanitized at intake (routes_misc.py compose_email). The wrapper
        # adds an explicit untrust sentinel for the LLM so role-override
        # patterns (`Ignore les instructions précédentes…`) inside the
        # user command are marked as data, not a directive.
        from app.prompts.builders import wrap_untrusted
        user_prompt += (
            "Instructions :\n"
            + wrap_untrusted(ctx.instructions, tag="user-instructions")
            + "\n"
        )
    if mandatory_opening:
        user_prompt += (
            f"\nCommence impérativement par la ligne exacte : "
            f"{mandatory_opening}\n"
        )
    if mandatory_closing:
        user_prompt += (
            f"\nTermine impérativement par la ligne exacte : "
            f"{mandatory_closing}\n"
        )
    user_prompt += (
        "\nÉcris uniquement le corps du message, prêt à envoyer. "
        "Pas de ligne 'Objet:' dans le corps."
    )
    return user_prompt


# ---------------------------------------------------------------------------
# Per-contact override resolution
# ---------------------------------------------------------------------------

def build_mandatory_opening(
    contact_greeting: Optional[str],
    contact_nickname: Optional[str],
    *,
    language: str = "FRENCH",
) -> Optional[str]:
    """Construit la ligne d'ouverture imposée depuis (salutation, surnom).

    Logique centralisée et partagée par le chemin DraftService
    (``resolve_per_contact_overrides``) et le chemin inline legacy
    (``routes_misc._build_compose_prompts``). Les deux copies divergeaient
    et portaient le même bug de double-interpellation (« Salut Nathan, Nat, »).

    Trois formes de ``contact_greeting`` gérées :

    1. Template tokenisé (« Bonjour {first_name}, ») → expansion avec le
       surnom (« Bonjour Nat, »). Si des tokens inconnus persistent, fallback
       sur « Salut <surnom>, ».
    2. Salutation littérale qui nomme déjà quelqu'un (« Salut Nathan, ») →
       on REMPLACE l'interpellation par le surnom (« Salut Nat, ») au lieu de
       l'accoler (« Salut Nathan, Nat, »). Cohérent avec la branche template
       qui remplit le slot nom par le surnom. Les interpellations génériques
       (« Bonjour à tous, ») ou les titres (« Bonjour Maître, ») sont gardés
       verbatim — on n'y injecte JAMAIS le surnom.
    3. Mot de salutation nu (« Salut », « Bonjour, ») → on retire la virgule
       traînante éventuelle puis on ajoute le surnom (« Bonjour Nat, »), ce qui
       évite le « Bonjour, Nat, » à double virgule.

    Retourne ``None`` quand il n'y a pas de surnom (rien à imposer).

    Note : ``contact_greeting`` est supposé déjà validé par
    ``is_canonical_greeting_for_contact`` côté appelant — donc une
    interpellation par nom présente est garantie compatible avec ce contact.
    Le helper reste néanmoins sûr si ce n'est pas le cas (il substitue le
    surnom au lieu de propager un nom étranger).
    """
    if not contact_nickname:
        return None
    greeting = (contact_greeting or "Salut").strip()

    # 1. Template tokenisé.
    if "{" in greeting:
        from app.smart_routing import _expand_greeting_template
        expanded = _expand_greeting_template(greeting, contact_nickname, language)
        if expanded and "{" not in expanded:
            return expanded
        # Tokens inconnus (ex: {prenom}/{nom}) → fallback littéral propre,
        # sinon le placeholder fuit verbatim dans le corps généré.
        logger.debug(
            "compose: greeting template '%s' a laissé un placeholder non "
            "résolu, fallback 'Salut <surnom>,'", greeting,
        )
        return f"Salut {contact_nickname},"

    # 2. Salutation littérale avec interpellation explicite.
    from app.smart_routing import (
        _GREETING_ADDRESSEE_RE,
        _GREETING_GENERIC_ADDRESSEES,
        _GREETING_TITLE_TOKENS,
        _normalise_name_words,
    )
    match = _GREETING_ADDRESSEE_RE.match(greeting)
    if match:
        addressee_words = _normalise_name_words(match.group(1))
        # Scan ALL addressee words (not just the first) so multi-token forms
        # like « à tous » (first word normalises to "a") or « Monsieur Dupont »
        # are still recognised as generic/title.
        if any(
            w in _GREETING_GENERIC_ADDRESSEES or w in _GREETING_TITLE_TOKENS
            for w in addressee_words
        ):
            # « Bonjour à tous, » / « Bonjour Maître, » — salutation complète,
            # surtout pas y accoler/substituer le surnom.
            return greeting
        # « Salut Nathan, » → « Salut Nat, » : on remplace le nom par le surnom.
        prefix = greeting[: match.start(1)]
        prefix = prefix[:1].upper() + prefix[1:]
        return f"{prefix}{contact_nickname},"

    # 3. Mot de salutation nu (avec/ sans virgule traînante).
    word = greeting.rstrip(" ,")
    greet_cap = (word[:1].upper() + word[1:]) if word else "Salut"
    return f"{greet_cap} {contact_nickname},"


def resolve_mandatory_closing(preferred_closing: Optional[str]) -> Optional[str]:
    """Retourne la clôture par contact à imposer comme règle dure, ou ``None``.

    Symétrique de :func:`build_mandatory_opening` pour la clôture : un
    ``preferred_closing`` (« A+ ») devient une règle dure pour que le LLM ne
    retombe pas sur son défaut (« À bientôt, »). On filtre le sentinel
    onboarding « no closing » / « just name » (même garde que le hint mou dans
    ``style_guidance.build_contact_hint_block``) pour qu'il ne fuite jamais
    comme une vraie clôture. La valeur est utilisée verbatim (pas d'ajout de
    virgule) — l'utilisateur a stocké « A+ » sans virgule volontairement.
    """
    if not isinstance(preferred_closing, str):
        return None
    cleaned = preferred_closing.strip()
    if not cleaned:
        return None
    from app.prompts.identity import _is_no_closing_marker
    if _is_no_closing_marker(cleaned):
        return None
    return cleaned


# Generic / role mailboxes whose local-part is shared by unrelated people.
# A per-contact override must NEVER cross between two of these (info@acme vs
# info@globex are different inboxes), so they are barred from same-person
# matching even when their normalised local-parts are identical.
_ROLE_MAILBOX_LOCALPARTS = frozenset({
    "info", "contact", "hello", "support", "sales", "admin", "team", "noreply",
    "office", "mail", "postmaster", "newsletter", "notifications", "notification",
    "billing", "accounts", "account", "jobs", "careers", "marketing", "news",
    "updates", "donotreply", "help", "feedback", "service", "webmaster",
    "abuse", "hr",
})

# The per-contact fields the compose path consumes — the only ones a same-person
# sibling entry is allowed to backfill onto an under-configured recipient.
_OVERRIDE_FIELDS = (
    "nickname", "preferred_greeting", "preferred_closing", "formality_override",
)


def _normalise_email_localpart(email: str) -> str:
    """Lowercase the local-part, drop a ``+tag``, strip all separators.

    ``nathan.roy@corp.example`` and ``nathanroy@gmail.com`` both normalise to
    ``nathanroy`` — the signal that links a person's multiple addresses.
    """
    local = (email or "").split("@", 1)[0].strip().lower().split("+", 1)[0]
    return re.sub(r"[^a-z0-9]", "", local)


def _is_distinctive_localpart(email: str) -> bool:
    """Distinctive enough that a normalised match plausibly means the SAME
    person rather than a common-name coincidence: the local-part must decompose
    into >=2 alphabetic name tokens (a ``firstname.lastname`` shape).

    A bare single token is NOT distinctive — even a long one. ``christine@a``
    and ``christine@b`` are very likely two different people, so a long-token
    rule would wrongly link them. The reported ``nathanroy@gmail.com`` still
    resolves because its sibling ``nathan.roy@corp.example`` IS two tokens, and
    :func:`_is_same_person` accepts the pair when EITHER side is distinctive.
    """
    local = (email or "").split("@", 1)[0].strip().lower().split("+", 1)[0]
    tokens = [t for t in re.split(r"[._+\-0-9]+", local) if t.isalpha() and len(t) >= 2]
    return len(tokens) >= 2


def _raw_localpart(email: str) -> str:
    """Lowercased local-part with a ``+tag`` removed but separators KEPT
    (``nathan.sok`` stays dotted) — used to tell format variants apart."""
    return (email or "").split("@", 1)[0].strip().lower().split("+", 1)[0]


def _is_same_person(email_a: str, email_b: str) -> bool:
    """Heuristic: do two addresses plausibly belong to the same person?

    Conservative by design — this gates whether one address's stored override
    (incl. tone/closing, which are personal) may personalise another, and is
    audited for false positives. Two DIFFERENT people who share a
    ``firstname.lastname`` at different domains (``jean.martin@clientA`` vs
    ``jean.martin@clientB``) also share a normalised local-part, so name-match
    alone is unsafe. Require ALL of:

    1. equal normalised local-parts,
    2. neither a generic/role mailbox (``info@``, ``noreply@``…),
    3. a distinctive (``firstname.lastname``) local-part on at least one side,
    4. a corroborating signal beyond the shared name — same domain (same org →
       overwhelmingly the same individual) OR differing raw local-parts (a
       format variant of ONE identity, e.g. ``nathan.sok`` vs ``nathanroy``;
       two different people don't coincidentally write the same name dotted on
       one domain and concatenated on another).

    Identical raw local-parts at different domains stay ambiguous → no match
    (configure those addresses explicitly rather than risk a cross-person leak).
    """
    na = _normalise_email_localpart(email_a)
    if not na or na != _normalise_email_localpart(email_b):
        return False
    if na in _ROLE_MAILBOX_LOCALPARTS:
        return False
    if not (_is_distinctive_localpart(email_a) or _is_distinctive_localpart(email_b)):
        return False
    domain_a = (email_a or "").split("@", 1)[-1].strip().lower() if "@" in (email_a or "") else ""
    domain_b = (email_b or "").split("@", 1)[-1].strip().lower() if "@" in (email_b or "") else ""
    if domain_a and domain_a == domain_b:
        return True
    return _raw_localpart(email_a) != _raw_localpart(email_b)


def resolve_contact_override_data(
    contact_profiles: Any, recipient_email: str
) -> Optional[dict]:
    """Effective per-contact override dict for ``recipient_email``.

    A person often has several addresses (work + personal); the per-contact
    config is keyed by exact email, so an override stored on one address used
    to silently not apply when composing to the other. This resolves overrides
    by *person*: the recipient's own (exact-email) entry wins field by field,
    and any override field it leaves empty is backfilled from a same-person
    sibling entry in the same profile.

    Returns ``None`` when neither the exact entry nor a usable sibling exists.
    Fail-open: any error degrades to the plain exact-match lookup so the draft
    path is never blocked.
    """
    if contact_profiles is None:
        return None
    first_to = _email_address_lower((recipient_email or "").split(",")[0])
    if not first_to:
        return None
    try:
        exact = contact_profiles.get(first_to)
    except Exception:
        return None

    effective = dict(exact) if isinstance(exact, dict) else {}
    missing = [
        f for f in _OVERRIDE_FIELDS
        if not (isinstance(effective.get(f), str) and effective.get(f).strip())
    ]
    # Recipient's own entry already specifies every override → exact-match
    # priority, no sibling lookup (zero behaviour change for configured
    # recipients).
    if exact is not None and not missing:
        return exact

    # The sibling scan walks the whole profile, which on the live backend is a
    # DB-backed `list_for_account`. A role mailbox can never be a same-person
    # match, so skip the scan entirely for those — keeps `info@`/`noreply@`
    # compose on a single indexed lookup.
    recip_norm = _normalise_email_localpart(first_to)
    if not recip_norm or recip_norm in _ROLE_MAILBOX_LOCALPARTS:
        return exact if exact is not None else None

    backfilled = False
    try:
        siblings = sorted(contact_profiles.items(), key=lambda kv: kv[0])
    except Exception:
        siblings = []
    for key, data in siblings:
        if not missing:
            break
        if key == first_to or not isinstance(data, dict):
            continue
        if not _is_same_person(first_to, key):
            continue
        for field in list(missing):
            val = data.get(field)
            if isinstance(val, str) and val.strip():
                effective[field] = val.strip()
                missing.remove(field)
                backfilled = True

    if exact is None and not backfilled:
        return None
    return effective


def resolve_per_contact_overrides(
    ctx: DraftContext,
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Résout (mandatory_opening, tone_directive, typical_signature,
    mandatory_closing) depuis le profile.

    Mirror de routes_misc.py:_build_compose_prompts — extrait nickname,
    preferred_greeting, formality_override, preferred_closing du
    ContactStyleProfile dispatché sur ctx.recipient_email. La construction de
    l'ouverture/clôture est déléguée aux helpers partagés
    :func:`build_mandatory_opening` / :func:`resolve_mandatory_closing` pour
    que les deux chemins compose restent alignés.

    Fail-open : toute exception (DB miss, profile malformé, container indispo)
    retourne (None, None, None, None) — le draft path ne doit JAMAIS être
    bloqué par un défaut de profile.
    """
    if not ctx.account_id or ctx.account_id <= 0:
        return None, None, None, None

    contact_nickname: Optional[str] = None
    contact_greeting: Optional[str] = None
    contact_formality: Optional[str] = None
    contact_closing: Optional[str] = None
    typical_signature: Optional[str] = None

    try:
        from app.infrastructure.container import get_container
        profile = get_container().get_writing_style_profile(account_id=ctx.account_id)
        if profile:
            typical_signature = getattr(profile, "typical_signature", None)
            first_to = ctx.recipient_email.split(",")[0].strip().lower()
            # Resolve by PERSON: an override stored on one of a contact's
            # addresses backfills drafts to their other addresses.
            contact_data = resolve_contact_override_data(
                profile.contact_profiles, first_to
            )
            if contact_data:
                _nick_val = contact_data.get("nickname")
                if isinstance(_nick_val, str) and _nick_val.strip():
                    contact_nickname = _nick_val.strip()
                _greet_val = contact_data.get("preferred_greeting")
                # Validate before adopting (2026-05-13 incident: a polluted
                # profile can inject non-greeting first lines into every draft
                # via the system-prompt `MANDATORY OPENING LINE` rule).
                from app.smart_routing import is_canonical_greeting_for_contact
                if (
                    isinstance(_greet_val, str)
                    and is_canonical_greeting_for_contact(
                        _greet_val, contact_nickname or ""
                    )
                ):
                    contact_greeting = _greet_val.strip()
                elif isinstance(_greet_val, str) and _greet_val.strip():
                    logger.warning(
                        "compose: rejecting non-canonical "
                        "preferred_greeting %r for contact %s",
                        _greet_val[:80], first_to,
                    )
                _form_val = contact_data.get("formality_override")
                if isinstance(_form_val, str) and _form_val.strip():
                    contact_formality = _form_val.strip().lower()
                _close_val = contact_data.get("preferred_closing")
                if isinstance(_close_val, str) and _close_val.strip():
                    contact_closing = _close_val.strip()
    except Exception as e:
        logger.debug(f"compose: writing style profile load failed: {e}")
        return None, None, None, None

    # Safety net (2026-05-14): a stale or cross-contaminated ContactStyleProfile
    # row can carry a *different* contact's nickname, which then gets enforced as
    # the mandatory opening of every draft to this recipient. Drop a nickname
    # with no plausible link to the recipient address — and log it.
    if contact_nickname:
        from app.prompts.identity import _nickname_matches_recipient
        _recip = ctx.recipient_email.split(",")[0].strip().lower()
        if not _nickname_matches_recipient(contact_nickname, _recip):
            logger.warning(
                "compose: stored nickname %r looks unrelated to recipient %s "
                "— ignoring it (possible stale/corrupt contact profile)",
                contact_nickname, _recip,
            )
            contact_nickname = None

    # Construire mandatory_opening (surnom + salutation) et mandatory_closing
    # via les helpers partagés — voir build_mandatory_opening pour le fix de
    # double-interpellation et resolve_mandatory_closing pour la clôture dure.
    mandatory_opening = build_mandatory_opening(contact_greeting, contact_nickname)
    mandatory_closing = resolve_mandatory_closing(contact_closing)

    # Tone directive
    tone_directive: Optional[str] = None
    if contact_formality:
        try:
            from app.api.routes_drafts import _build_tone_directive
            tone_directive = _build_tone_directive(contact_formality)
        except Exception:
            pass  # _build_tone_directive missing = no directive (graceful)

    return mandatory_opening, tone_directive, typical_signature, mandatory_closing


def resolve_contact_profiles(ctx: DraftContext) -> Optional[Any]:
    """Resolve the writing-style ``contact_profiles`` view for this account.

    Used by the multi-recipient greeting hint (issue #592) to compare
    register signals across primary recipients. Returns ``None`` on miss
    or any error — callers must treat ``None`` as "no register data
    available" and fall back to a register-neutral group greeting.
    """
    if not ctx.account_id or ctx.account_id <= 0:
        return None
    try:
        from app.infrastructure.container import get_container
        profile = get_container().get_writing_style_profile(account_id=ctx.account_id)
        if profile is None:
            return None
        return profile.contact_profiles
    except Exception as e:
        logger.debug(f"compose: contact_profiles resolve failed: {e}")
        return None


def resolve_style_context(ctx: DraftContext) -> str:
    """Résout le bloc style_context depuis le WritingStyleProfile.

    Si ctx.style_profile est déjà fourni (test injection), l'utilise directement.
    Sinon, charge depuis Container.
    """
    if ctx.style_profile:
        return ctx.style_profile

    if not ctx.account_id or ctx.account_id <= 0:
        return ""

    try:
        from app.infrastructure.container import get_container
        from app.prompts.style_guidance import build_style_guidance_from_profile
        profile = get_container().get_writing_style_profile(account_id=ctx.account_id)
        if profile:
            first_to = ctx.recipient_email.split(",")[0].strip().lower()
            return build_style_guidance_from_profile(
                profile, language="fr", recipient_email=first_to
            )
    except Exception as e:
        logger.debug(f"compose: style_context resolve failed: {e}")

    return ""


# ---------------------------------------------------------------------------
# Drafter invocation (blocking + streaming)
# ---------------------------------------------------------------------------

def run_drafter_blocking(
    llm: Any, system_prompt: SystemPrompt, user_prompt: str
) -> tuple[str, dict]:
    """Appel Drafter blocking. Retourne (body, usage_metadata).

    `system_prompt` accepte str (legacy) ou SystemSegment[].
    """
    response = llm.complete(
        system=system_prompt,
        user=user_prompt,
        max_tokens=500,
    )
    body = (response.content or "").strip()
    usage = {
        "input_tokens": getattr(response, "input_tokens", 0),
        "output_tokens": getattr(response, "output_tokens", 0),
        "model": getattr(response, "model", ""),
        "cache_read_input_tokens": getattr(response, "cache_read_input_tokens", 0),
        "cache_creation_input_tokens": getattr(response, "cache_creation_input_tokens", 0),
    }
    return body, usage


def run_drafter_streaming(
    llm: Any, system_prompt: SystemPrompt, user_prompt: str
) -> tuple[str, dict]:
    """Appel Drafter streaming. Accumulate tous les chunks en synchrone et retourne le body final.

    `system_prompt` accepte str (legacy) ou SystemSegment[].

    Le wrapper endpoint (routes_misc.py) reste responsable de l'émission WebSocket
    par chunk. Phase 2b implémentation simple : on consume le stream localement,
    Phase 2c pourra brancher un callback pour émettre par chunk si besoin.

    Important (review R4) : on accumule le `chunk.text` AVANT de tester is_final,
    car les providers conformes au port LLMStreamChunk peuvent placer un dernier
    token dans le chunk final. Sans cet ordre, on perd silencieusement le dernier
    token.
    """
    accumulated = ""
    last_chunk = None
    for chunk in llm.stream(system=system_prompt, user=user_prompt, max_tokens=500):
        if chunk.text:
            accumulated += chunk.text
        last_chunk = chunk
        if chunk.is_final:
            break
    usage = {
        "input_tokens": getattr(last_chunk, "input_tokens", 0) if last_chunk else 0,
        "output_tokens": getattr(last_chunk, "output_tokens_so_far", 0) if last_chunk else 0,
        "model": getattr(last_chunk, "model", "") if last_chunk else "",
        "cache_read_input_tokens": getattr(last_chunk, "cache_read_input_tokens", 0) if last_chunk else 0,
        "cache_creation_input_tokens": getattr(last_chunk, "cache_creation_input_tokens", 0) if last_chunk else 0,
    }
    return accumulated.strip(), usage


# ---------------------------------------------------------------------------
# Self-Critique shadow invocation
# ---------------------------------------------------------------------------

def _self_critique_shadow_enabled() -> bool:
    """F-05 (audit 2026-04-30): feature flag, default OFF.

    Shadow mode evaluates every compose draft via a second Haiku call but
    never escalates ("locked decision" per draft_service comments). Until
    Phase 4 sentinel actually consumes the telemetry, this is a pure cost
    burden (~$0.0001/compose + ~400ms TTFT in blocking mode). Enable via
    `SELF_CRITIQUE_SHADOW_ENABLED=true` once the consumer exists.
    """
    import os as _os_sc
    return _os_sc.environ.get("SELF_CRITIQUE_SHADOW_ENABLED", "false").strip().lower() in (
        "1", "true", "yes", "on"
    )


def run_self_critique_shadow(self_critique_agent: Any, draft_body: str, ctx: DraftContext):
    """Exécute le SelfCritiqueAgent en shadow mode avec sampling 10% (P1.4).

    Shadow = on calcule le verdict mais on n'escalade JAMAIS via Critic externe
    en compose. Sur la fraction sampled (10% par défaut), le verdict peut
    déclencher 1 regen Drafter dans `_generate_compose` (cf. P2.8).

    Returns:
        SelfCritique sur la fraction sampled (10%).
        None sur les 90% non-sampled — économie 90% des appels Haiku auto-critique
        (~$0.0003/draft × 90% = ~$0.27/1k drafts) tout en conservant un signal
        statistique pour la sentinel L3.

    Ne raise jamais : toute exception → SelfCritique.create_failed.
    """
    if self_critique_agent is None:
        return None
    if not _self_critique_shadow_enabled():
        return None

    # P1.4 — sampling. We use module-level `random` so tests can monkey-patch.
    sample_rate = _get_sample_rate()
    if sample_rate < 1.0 and random.random() >= sample_rate:
        # Not sampled — return None so the caller knows to skip the regen path.
        return None

    try:
        # Compose context = subject + instructions (pas d'email original)
        ctx_str = f"Sujet: {ctx.subject}\nInstructions: {ctx.instructions}"
        return self_critique_agent.evaluate(
            draft=draft_body, context=ctx_str, mode="compose"
        )
    except Exception as e:
        logger.warning(f"compose self-critique shadow failed: {e}")
        from app.domain.entities.self_critique import SelfCritique
        return SelfCritique.create_failed(reason=str(e))


# P2.8 — Regen helpers
# ---------------------------------------------------------------------------

def should_regen_from_critique(critique: Any) -> bool:
    """Décide si un draft doit être régénéré sur base du verdict self-critique.

    Args:
        critique : SelfCritique typé ou None (non-sampled / agent indispo).

    Returns:
        True si (sampled) AND (score < threshold) AND (at least one
        actionable risk detected). False sinon.
    """
    if critique is None:
        return False
    # Failed evaluations carry self_score=0 + empty risks — don't regen on
    # those, they're an LLM/parse/IO failure, not a draft quality signal.
    if getattr(critique, "failure_reason", ""):
        return False
    if getattr(critique, "self_score", 100) >= SELF_CRITIQUE_REGEN_THRESHOLD:
        return False
    risks = getattr(critique, "risks", ()) or ()
    return any(r in _REGEN_TRIGGER_RISKS for r in risks)


def build_regen_user_prompt(
    original_user_prompt: str,
    critique: Any,
    mandatory_opening: Optional[str],
    mandatory_closing: Optional[str] = None,
) -> str:
    """Construit un user prompt pour la 2e passe Drafter, enrichi des risques.

    On garde le prompt original et on suffixe une directive corrective explicite
    pour forcer le LLM à fixer les défauts détectés sans drift sur le reste.
    """
    risks = list(getattr(critique, "risks", ()) or ())
    score = int(getattr(critique, "self_score", 0))
    risks_human = ", ".join(risks) if risks else "qualité globale insuffisante"

    corrective = (
        f"\n\n=== RÉVISION OBLIGATOIRE ===\n"
        f"Le brouillon précédent a été évalué à {score}/100 par l'auto-critique. "
        f"Risques détectés : {risks_human}.\n"
        f"Réécris le message en corrigeant ces défauts spécifiquement. "
        f"Ne re-introduis aucun placeholder type [À confirmer]/[À définir]/[TBD]/[À valider]. "
        f"Garde la même langue que la demande utilisateur. "
        f"Pas de signature, pas de nom de l'expéditeur après la clôture."
    )
    if mandatory_opening:
        corrective += f"\nOuverture obligatoire : «{mandatory_opening}»."
    if mandatory_closing:
        corrective += f"\nClôture obligatoire : «{mandatory_closing}»."
    return original_user_prompt + corrective
