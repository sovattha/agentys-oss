# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Identity and name detection helpers — read user profile from memoire.md."""

from __future__ import annotations

import html as _html
import re as _re
import unicodedata as _unicodedata



__all__ = [
    "_user_identity_cache", "_extract_user_identity", "_extract_user_name",
    "_extract_language_variant",
    "_variant_to_rule",
    "_extract_preferred_language",
    "invalidate_identity_cache", "_is_person_name", "_is_likely_feminine",
    "_clean_sender_name", "_compute_greeting_hint", "_compute_closing_hint",
    "normalize_closing_to_language",
    "_is_unknown_sender_name", "is_placeholder_style_value",
    "_tokenize_greeting", "_nickname_matches_recipient",
    "_extract_prior_user_salutation",
    "_email_local_name_tokens", "_display_name_conflicts_with_email_tokens",
    "_signature_name_matching_email", "_signature_person_name",
    "_UNDEFINED_PLACEHOLDERS", "_NON_PERSON_WORDS",
]


def _load_kb(account_id: int | None = None) -> str:
    """Load knowledge base without cross-tenant global fallback for accounts."""
    from app._prompts_monolith import load_account_knowledge
    return load_account_knowledge(account_id)


# Per-account identity cache: {account_id: {name, job_title, company}}
# account_id=0 is the legacy global cache
_user_identity_cache: dict[int, dict] = {}

_UNDEFINED_PLACEHOLDERS = {"[a definir]", "[à définir]", "[a définir]", "[À définir]"}


def _is_unknown_sender_name(raw_name: str) -> bool:
    """True for provider/thread placeholders, not real display names."""
    if not raw_name:
        return False
    normalized = _unicodedata.normalize("NFKC", str(raw_name)).strip().lower()
    normalized = normalized.strip("[](){} \t\r\n.,;:")
    return normalized in {"unknown", "inconnu", "undefined", "none", "null", "n/a"}


def _extract_user_identity(account_id: int | None = None) -> dict:
    """Extract user's name, job title, and company. Cached per account_id."""
    cache_key = account_id or 0
    if cache_key in _user_identity_cache:
        return _user_identity_cache[cache_key]
    result = {"name": "", "job_title": "", "company": ""}
    try:
        kb = _load_kb(account_id)
        for key, pattern in [
            ("name",      r"\*\*Nom complet\*\*\s*:\s*(.+)"),
            ("job_title", r"\*\*Poste\*\*\s*:\s*(.+)"),
            ("company",   r"\*\*Entreprise\*\*\s*:\s*(.+)"),
        ]:
            match = _re.search(pattern, kb)
            if match:
                val = match.group(1).strip()
                if val and val.lower() not in _UNDEFINED_PLACEHOLDERS:
                    result[key] = val
    except Exception:
        pass
    _user_identity_cache[cache_key] = result
    return result


def _extract_user_name(account_id: int | None = None) -> str:
    """Extract user's full name."""
    return _extract_user_identity(account_id)["name"]


_ISO_VARIANT_PATTERN = _re.compile(r"^[a-z]{2}-[A-Z]{2}$")

# Legacy labels → ISO codes (for backward compat with old memoire.md)
_LEGACY_VARIANT_MAP = {
    "fr-QC": "fr-CA", "fr-neutral": "", "en-NA": "en-US", "en-UK": "en-GB",
    "Québec": "fr-CA", "France": "fr-FR", "Belgique": "fr-BE",
    "Suisse": "fr-CH", "Royaume-Uni": "en-GB", "Australie": "en-AU",
    "Espagne": "es-ES", "Brésil": "pt-BR",
    "Mexique": "es-MX", "Canada": "fr-CA",
}


def _extract_language_variant(account_id: int | None = None) -> str:
    """Extract langue_variante. Returns ISO code (e.g. 'fr-CA', 'fr-FR') or ''."""
    try:
        kb = _load_kb(account_id)
        match = _re.search(r"\*\*Variante linguistique\*\*\s*:\s*(\S+)", kb)
        if match:
            val = match.group(1).strip()
            if _ISO_VARIANT_PATTERN.match(val):
                return val
            if val in _LEGACY_VARIANT_MAP:
                return _LEGACY_VARIANT_MAP[val]
    except Exception:
        pass
    return ""


def _variant_to_rule(variant: str) -> str:
    """Convert language variant to a prompt instruction line."""
    if not variant:
        return ""
    return f"- REGIONAL VARIANT: {variant}. Adapt vocabulary, spelling, and regional expressions accordingly.\n"


def _extract_preferred_language(account_id: int | None = None) -> str:
    """Extract preferred language. Returns 'FRENCH', 'ENGLISH', or '' (auto)."""
    try:
        kb = _load_kb(account_id)
        match = _re.search(r"\*\*Langue\*\*\s*:\s*(.+)", kb)
        if match:
            val = match.group(1).strip().lower()
            if val in ("français", "francais", "french"):
                return "FRENCH"
            if val in ("anglais", "english"):
                return "ENGLISH"
    except Exception:
        pass
    return ""  # auto → no override


def invalidate_identity_cache(account_id: int | None = None) -> None:
    """Invalider le cache identité et la knowledge base.

    Args:
        account_id: If provided, only invalidate that account's cache.
                    If None, invalidate all accounts (legacy behavior).
    """
    global _user_identity_cache
    if account_id is not None:
        _user_identity_cache.pop(account_id, None)
    else:
        _user_identity_cache.clear()
    from app._prompts_monolith import _kb_cache
    _kb_cache["content"] = None
    _kb_cache["timestamp"] = 0


_NON_PERSON_WORDS = {
    # Organizational units
    "service", "equipe", "équipe", "team", "dept", "département", "department",
    "direction", "comité", "comite", "bureau", "groupe", "division", "section",
    "financiere", "financière", "financial",
    # Roles / generic descriptors (not real names)
    "rh", "hr", "support", "info", "contact", "admin", "webmaster",
    "client", "collegue", "collègue", "colleague", "ami", "potentiel",
    "vieux", "old", "former", "ancien", "ancienne", "nouveau", "new",
    "organisatrice", "organisateur", "coordinateur", "coordinatrice",
    "legal", "juridique", "technique", "technical",
    # Professional titles / roles
    "investisseur", "investor", "analyste", "analyst",
    "directeur", "director", "manager", "partenaire", "partner",
    "consultant", "founder", "fondateur",
    "president", "président", "comptable", "accountant",
    "ingenieur", "ingénieur", "engineer", "developer", "dev", "designer",
    "lead", "chief",
    # Place names / orgs that look like names
    "montreal", "montréal", "toronto", "paris", "london", "york",
    "techhub", "hub", "lab", "labs", "studio", "studios",
    "corp", "inc", "llc", "ltd", "sarl", "sas",
    # Government / institutions / organizations
    "commission", "association", "fédération", "federation", "ministère", "ministere",
    "agence", "agency", "office", "conseil", "fondation", "foundation",
    "institut", "institute", "autorité", "authority", "tribunal", "chambre",
    "formation", "université", "universite", "university", "universities",
    # Automated / system senders
    "noreply", "notification", "newsletter", "system", "bot",
    "monitoring", "alertes", "alerts", "facturation", "billing",
    "security", "sécurité", "updates", "mailer",
}

_EXPLICIT_SERVICE_SENDER_WORDS = {
    "service", "equipe", "équipe", "team", "dept", "département", "department",
    "rh", "hr", "support", "info", "contact", "admin", "webmaster",
    "noreply", "notification", "newsletter", "system", "bot",
    "monitoring", "alertes", "alerts", "facturation", "billing",
    "security", "sécurité", "updates", "mailer",
}


def _is_person_name(name: str) -> bool:
    """Return True if *name* looks like a real person (vs org/team/role)."""
    words = _name_words(name)
    if not words:
        return False
    for w in words:
        if w in _NON_PERSON_WORDS:
            return False
    return True


def _display_has_explicit_service_word(display_name: str) -> bool:
    return any(word in _EXPLICIT_SERVICE_SENDER_WORDS for word in _name_words(display_name))


def _normalise_token(value: str) -> str:
    normalized = _unicodedata.normalize("NFKD", (value or "").lower())
    return "".join(ch for ch in normalized if not _unicodedata.combining(ch))


def _name_words(value: str) -> list[str]:
    return _re.findall(r"[a-z0-9]+", _normalise_token(value))


def _name_token_matches(left: str, right: str) -> bool:
    if left == right:
        return True
    return min(len(left), len(right)) >= 3 and (
        left.startswith(right) or right.startswith(left)
    )


def _email_local_name_tokens(sender_email: str) -> list[str]:
    """Return person-like tokens from an email local-part.

    Accepts either a bare address or a full ``Display <addr>`` string.
    Generic mailboxes such as support/contact/billing are filtered out.
    """
    raw = (sender_email or "").strip()
    if "<" in raw and ">" in raw:
        raw = raw.split("<", 1)[1].split(">", 1)[0].strip()
    if "@" not in raw:
        return []
    local = raw.split("@", 1)[0].strip("<>\"' ").lower()
    tokens = [
        t for t in _re.split(r"[._+\-0-9]+", local)
        if t.isalpha() and len(t) >= 2 and t not in _NON_PERSON_WORDS
    ]
    return tokens


def _display_name_conflicts_with_email_tokens(
    display_name: str,
    email_tokens: list[str],
) -> bool:
    """True when a display name looks unrelated to a ``first.last`` address."""
    if len(email_tokens) < 2:
        return False
    display_words = _name_words(display_name)
    if not display_words:
        return False
    return not any(
        _name_token_matches(display_word, email_token)
        for display_word in display_words
        for email_token in email_tokens
    )


_SIGNATURE_NAME_REJECT_WORDS = _NON_PERSON_WORDS | {
    "merci", "thanks", "thank", "cordialement", "regards", "best",
    "sincerely", "cheers", "bientot", "amicalement", "salutations",
    "salut", "bonjour", "hello", "hi", "hey",
    "telephone", "téléphone", "phone", "mobile", "linkedin", "www",
}


def _signature_candidate_parts(line: str) -> list[str]:
    # Names are often followed by a title on the same line:
    # "Alexandre Simon - Co-fondateur". Try the whole line and the
    # separator-delimited chunks, then let word validation reject title chunks.
    parts = [line]
    parts.extend(
        part.strip()
        for part in _re.split(r"\s+(?:[|•·]|[-–—])\s+|,", line)
        if part.strip()
    )
    return parts


def _plain_signature_text(text: str) -> str:
    raw = text or ""
    if "<" in raw and ">" in raw:
        raw = _re.sub(r"<\s*br\s*/?\s*>", "\n", raw, flags=_re.IGNORECASE)
        raw = _re.sub(r"</\s*(?:p|div|li|tr|h[1-6])\s*>", "\n", raw, flags=_re.IGNORECASE)
        raw = _re.sub(r"<[^>]+>", " ", raw)
    return _html.unescape(raw)


def _signature_name_matching_email(signature_text: str, sender_email: str) -> str:
    """Extract a signature name that correlates with the sender address.

    This is deliberately conservative: the signature can override an ambiguous
    display name only when at least one candidate name line matches the email
    local-part tokens. It will not invent a name from title/company lines.
    """
    email_tokens = _email_local_name_tokens(sender_email)
    if not signature_text or not email_tokens:
        return ""

    plain = _plain_signature_text(signature_text)
    try:
        from app.utils.signature import extract_signature_zone
        zone = extract_signature_zone(plain)
    except Exception:
        zone = ""

    tail = "\n".join(plain.splitlines()[-12:])
    scan_text = tail
    if zone and zone not in scan_text:
        scan_text = f"{scan_text}\n{zone}" if scan_text else zone

    for raw_line in scan_text.splitlines():
        line = raw_line.strip().strip("•*-–— \t")
        if not line or len(line) > 100:
            continue
        if "@" in line or "http" in line.lower() or _re.search(r"\d{4,}", line):
            continue
        for part in _signature_candidate_parts(line):
            words = _name_words(part)
            if not 1 <= len(words) <= 4:
                continue
            if any(word in _SIGNATURE_NAME_REJECT_WORDS for word in words):
                continue
            matched = [
                idx for idx, word in enumerate(words)
                if any(_name_token_matches(word, token) for token in email_tokens)
            ]
            if not matched:
                continue
            if len(words) == 1:
                if len(email_tokens) >= 2 and _name_token_matches(words[0], email_tokens[0]):
                    return part.strip()
                continue
            return part.strip()
    return ""


def _signature_person_name(signature_text: str) -> str:
    """Extract a plausible full person name from the current email signature."""
    if not signature_text:
        return ""

    plain = _plain_signature_text(signature_text)
    try:
        from app.utils.signature import extract_signature_zone
        zone = extract_signature_zone(plain)
    except Exception:
        zone = ""

    tail = "\n".join(plain.splitlines()[-8:])
    scan_text = tail
    if zone and zone not in scan_text:
        scan_text = f"{scan_text}\n{zone}" if scan_text else zone
    for raw_line in reversed(scan_text.splitlines()):
        line = raw_line.strip().strip("•*-–— \t")
        if not line or len(line) > 100:
            continue
        if "@" in line or "http" in line.lower() or _re.search(r"\d{4,}", line):
            continue
        for part in _signature_candidate_parts(line):
            words = _name_words(part)
            if not 2 <= len(words) <= 4:
                continue
            if any(word in _SIGNATURE_NAME_REJECT_WORDS for word in words):
                continue
            if not _is_person_name(part):
                continue
            return part.strip()
    return ""


# Common feminine first names (FR + EN) for gender detection in greetings
_FEMININE_FIRST_NAMES = {
    # French
    "marie", "claire", "sophie", "julie", "amélie", "amelie", "chantal",
    "christine", "colette", "danielle", "émilie", "emilie", "françoise",
    "francoise", "geneviève", "genevieve", "hélène", "helene", "isabelle",
    "jeanne", "laure", "laurence", "louise", "madeleine", "marguerite",
    "martine", "monique", "nathalie", "nicole", "pascale", "patricia",
    "sandrine", "simone", "sylvie", "thérèse", "therese", "valérie",
    "valerie", "véronique", "veronique", "cécile", "cecile", "dominique",
    "florence", "manon", "camille", "léa", "lea", "chloé", "chloe",
    "audrey", "caroline", "catherine", "sylviane", "josiane", "mireille",
    "anne", "brigitte", "denise", "evelyne", "jocelyne", "lise",
    "lucie", "nadia", "stéphanie", "céline", "celine", "elise", "élise",
    "maude", "josée", "josee", "andrée", "andree", "renée", "renee",
    "carole", "diane", "ginette", "pierrette", "aline", "odette",
    # French — modern / common (post-1970 generations + classical gaps)
    "alexandra", "alexia", "alix", "anaïs", "anais", "angélique", "angelique",
    "audrey", "aurélie", "aurelie", "aurore", "barbara", "béatrice", "beatrice",
    "blandine", "candice", "capucine", "carla", "cassandra", "charlotte",
    "claudia", "clara", "clémence", "clemence", "clémentine", "clementine",
    "constance", "coralie", "coraline", "cyrielle", "delphine", "elena",
    "éléonore", "eleonore", "eléna", "elena", "élodie", "elodie", "elsa",
    "emma", "estelle", "eugénie", "eugenie", "fanny", "flora", "gaëlle",
    "gaelle", "héloïse", "heloise", "inès", "ines", "ingrid", "iris",
    "jade", "jeannine", "jessica", "jocelyne", "joëlle", "joelle", "jolyane",
    "jordane", "jordana", "judith", "juliette", "justine", "lara", "laëtitia",
    "laetitia", "lalie", "lana", "léa", "lea", "léna", "lena", "leslie",
    "lila", "lily", "lilou", "linda", "lisa", "lola", "lorène", "lorene",
    "louane", "louna", "lucile", "lucille", "ludivine", "maëlle", "maelle",
    "maëva", "maeva", "maïa", "maia", "maily", "margaux", "margot",
    "mathilde", "maud", "mauricette", "maxine", "maya", "mégane", "megane",
    "mélanie", "melanie", "mélina", "melina", "mélissa", "melissa", "mélodie",
    "melodie", "mia", "mila", "morgane", "muriel", "myriam", "nadège",
    "nadege", "nadine", "naomi", "nina", "noémie", "noemie", "nora",
    "océane", "oceane", "olivia", "ophélie", "ophelie", "pauline", "perrine",
    "rachel", "rebecca", "régine", "regine", "rita", "romane", "rose",
    "roxane", "sabine", "sabrina", "salomé", "salome", "sara", "sarah",
    "ségolène", "segolene", "séverine", "severine", "shirley", "sofia",
    "sonia", "soraya", "stella", "tania", "tatiana", "thelma", "tiffany",
    "valentine", "vanessa", "victoire", "violaine", "viviane", "yasmine",
    "yolande", "zoé", "zoe",
    # English
    "alice", "amanda", "angela", "anna", "barbara", "betty", "charlotte",
    "christina", "deborah", "diana", "dorothy", "elizabeth", "emily",
    "emma", "fiona", "grace", "hannah", "helen", "jane", "jennifer",
    "jessica", "julia", "karen", "katherine", "kate", "laura", "linda",
    "lisa", "margaret", "maria", "mary", "michelle", "nancy", "natalie",
    "olivia", "rachel", "rebecca", "ruth", "samantha", "sandra", "sarah",
    "stephanie", "susan", "victoria", "abigail", "ashley", "brittany",
    "cynthia", "donna", "eva", "heather", "irene", "janet", "joyce",
    "kelly", "megan", "pamela", "tamara", "wendy",
}


def _is_likely_feminine(name: str) -> bool:
    """
    Heuristic check if a first name is likely feminine.

    Checks the first name (and compound parts like Marie-Claire) against
    a known set of feminine names.
    """
    if not name:
        return False
    # For compound names like "Marie-Claire", check each part
    parts = name.lower().replace('-', ' ').split()
    for part in parts:
        if part in _FEMININE_FIRST_NAMES:
            return True
    return False


def _clean_sender_name(raw_name: str) -> tuple[str, bool, str]:
    """
    Strip professional titles and suffixes from sender name.

    Returns (cleaned_name, forced_feminine, preserved_title) where:
    - forced_feminine is True if a feminine title was found
    - preserved_title is the original title to use in greetings (e.g. "Me" for lawyers)
    """
    if not raw_name:
        return raw_name, False, ""

    name = raw_name.strip()
    forced_feminine = False
    preserved_title = ""

    # Strip trailing professional suffixes (", CPA", ", PhD", ", MBA", etc.)
    name = _re.sub(r',\s*(?:CPA|PhD|MBA|M\.?Sc|B\.?Sc|P\.?Eng|Esq|Jr|Sr|III?|IV)\.?\s*$', '', name, flags=_re.IGNORECASE).strip()

    # Strip leading professional titles
    title_match = _re.match(r'^(Me\.?|Mme\.?|Mrs?\.?|Ms\.?|Dr\.?|Prof\.?|Pr\.?)\s+', name, flags=_re.IGNORECASE)
    if title_match:
        title = title_match.group(1).lower().rstrip('.')
        if title in ('me', 'mme', 'mrs', 'ms'):
            forced_feminine = True
        # Preserve "Me" (Maître) for lawyers — gender-neutral legal title
        if title == 'me':
            preserved_title = "Me"
        elif title == 'dr':
            preserved_title = "Dr"
        elif title == 'prof' or title == 'pr':
            preserved_title = "Prof."
        name = name[title_match.end():].strip()

    return name, forced_feminine, preserved_title


# Greeting words that anchor the conservative position-based tokenizer.
# The recipient's first name is replaced with `{first_name}` only when it
# appears *directly after* one of these words — this avoids false positives
# on short nicknames (Al, Eva, Sam) that could collide with normal vocabulary.
_GREETING_ANCHORS = (
    r"Bonjour|Salut|Hi|Hello|Hey|Dear|Coucou|Ol[aá]|Hola|"
    r"Cher|Ch[eèéê]re|Ch[eèéê]res?"
)


# Pattern: a salutation line in any of the supported languages.
# Group 1 = greeting word (Bonjour, Salut, Hi, …), group 2 = name token.
# Anchored on the whole stripped line — refuses partial matches inside body
# text (e.g. "Bonjour Alex, comment vas-tu" would NOT match because of the
# trailing question — we want a clean salutation line, not body content).
_PRIOR_SALUTATION_RE = _re.compile(
    rf"^({_GREETING_ANCHORS})\s+([A-ZÉÈÊÀÂÔÎÏŒÇa-zéèêàâôîïœç'’\-]{{2,40}})\s*[,!.]?\s*$",
    _re.IGNORECASE,
)

# Generic salutation tokens that are NOT a person's first name — refusing
# them prevents false positives like "Bonjour vous," / "Hi all," / "Dear team,".
_GENERIC_SALUTATION_TOKENS = {
    "vous", "tous", "toutes", "tout", "toute", "team", "all", "everyone",
    "monsieur", "madame", "messieurs", "mesdames", "sir", "madam",
}


def _extract_prior_user_salutation(
    conversation_history: list[dict] | None,
    user_email: str,
    contact_email: str,
) -> tuple[str, str]:
    """Look for the salutation the user most recently used to address this contact.

    Scans the user's *outgoing* messages in ``conversation_history`` for a first
    line matching ``^(Bonjour|Salut|Hi|Dear|...) <FirstName>[,!.]?$`` and
    returns ``(rebuilt_salutation, first_name)``.

    Why: when the user has already addressed a contact by first name in the
    same thread (e.g. "Bonjour Alexandra,"), that is the strongest source of
    truth — stronger than email-prefix extraction (which can yield the LAST
    name when ``From: "Aubert"`` is the only display token) and stronger
    than formality-based defaults. Mirroring the user's own past wording is
    the deterministic way to avoid the "Bonjour Aubert" regression.

    Returns ``("", "")`` when no clear pattern is found. Fail-open: never
    raise, never block the draft path.
    """
    if not conversation_history or not user_email or not contact_email:
        return "", ""
    user_lower = user_email.lower().strip()
    contact_lower = contact_email.lower().strip()
    try:
        for email in conversation_history:
            sender = (email.get("sender") or email.get("from") or "").lower()
            if user_lower not in sender:
                continue
            # Optional `to`/`recipient` field guard — skip if the email was
            # addressed to someone else in the thread (multi-party threads).
            to_field = (
                email.get("to")
                or email.get("recipient")
                or email.get("recipients")
                or ""
            )
            if isinstance(to_field, list):
                to_field = " ".join(str(x) for x in to_field)
            if to_field and contact_lower not in str(to_field).lower():
                continue
            body = email.get("body") or email.get("body_preview") or ""
            if not body:
                continue
            for line in body.split("\n"):
                stripped = line.strip()
                if not stripped:
                    continue
                m = _PRIOR_SALUTATION_RE.match(stripped)
                if m:
                    greeting_word = m.group(1)
                    name_token = m.group(2).strip()
                    if name_token.lower() in _GENERIC_SALUTATION_TOKENS:
                        # Fall through to next email — generic salutations
                        # carry no first-name signal.
                        break
                    return f"{greeting_word} {name_token},", name_token
                # First non-empty line wasn't a salutation → bail on this
                # email; salutations only live on the first content line.
                break
    except Exception:
        return "", ""
    return "", ""


def _tokenize_greeting(text: str, nickname: str) -> str:
    """Replace the recipient's first name with `{first_name}` in a greeting.

    Conservative by design: only tokenizes when the nickname appears as the
    token immediately following a known greeting anchor (Bonjour, Salut, Hi,
    Dear, …). The greeting word's original case is preserved.

    Args:
        text: Greeting line to tokenize (e.g. ``"Bonjour Alexandra,"``).
        nickname: Known first name / nickname of the recipient.

    Returns:
        Tokenized greeting (e.g. ``"Bonjour {first_name},"``) or the input
        unchanged when the nickname is empty, already tokenized, or does not
        appear in an anchored position (title-based, multi-word, …).
    """
    if not text or not nickname:
        return text
    # Already tokenized — never double-tokenize
    if "{first_name}" in text or "{last_name}" in text or "{civility}" in text:
        return text

    pattern = _re.compile(
        rf"(^\s*(?:{_GREETING_ANCHORS})\s+){_re.escape(nickname)}\b",
        _re.IGNORECASE,
    )
    return pattern.sub(r"\1{first_name}", text, count=1)


def _nickname_matches_recipient(nickname: str, recipient_email: str) -> bool:
    """Sanity-check a stored per-contact nickname against the recipient address.

    A ``ContactStyleProfile`` nickname fills ``{first_name}`` in the mandatory
    opening line. A stale or cross-contaminated profile row can carry a nickname
    that belongs to a *different* contact — and because the opening is enforced
    as a non-negotiable rule, that poisons every draft to the recipient
    (2026-05-14 incident: ``alexandre.simon@hotmail.com`` held nickname
    "Nat", Nathan's — every draft opened "Salut Nat,").

    Returns ``True`` when the nickname is plausibly this recipient's name, OR
    when there is nothing reliable to check against (handle-style addresses
    like ``0xfastlife@gmx.com`` legitimately carry unrelated nicknames — we
    fail open so a legitimate nickname is never suppressed). Returns ``False``
    ONLY when the email local-part exposes real name tokens and *none* of them
    relate to the nickname — a strong signal of a corrupt row.
    """
    nick = (nickname or "").strip().lower()
    if not nick:
        return True
    local = (recipient_email or "").split("@")[0].strip().lower()
    if not local:
        return True
    # Name tokens from the local-part ("alexandre.simon" → alexandre,
    # simon). Split on the usual separators + digits; keep alphabetic
    # runs of length >= 2.
    tokens = [t for t in _re.split(r"[._+\-0-9]+", local) if t.isalpha() and len(t) >= 2]
    if not tokens:
        return True  # handle-style address — no name signal to validate against
    for tok in tokens:
        # A shared 3-char prefix covers Alex<->Alexandre, Nat<->Nathansok.
        shared = 0
        for a, b in zip(nick, tok):
            if a != b:
                break
            shared += 1
        if shared >= 3 or nick in tok or tok in nick:
            return True
    # No token related to the nickname. Suppress ONLY on a strong signal:
    # a multi-token local-part (firstname.lastname style) where nothing
    # matched. A lone token is an initials-style mash (jdupont, asmith)
    # that legitimately can't spell out the first name — failing open
    # there avoids silently discarding a user-set nickname (e.g. nickname
    # "Jean" vs "jdupont@…", the common false positive).
    return len(tokens) < 2


def _compute_greeting_hint(
    sender_name: str,
    formality: int,
    language: str,
    sender_email: str = "",
    signature_text: str = "",
) -> str:
    """
    Compute the exact greeting line the LLM should use.

    Args:
        sender_name: Display name of the sender (e.g. "Jean Martin").
        formality: 1-5 score.
        language: "ENGLISH" or "FRENCH".
        sender_email: Optional raw email (e.g. "jean.martin@x.com") used as a
            tiebreaker when ``sender_name`` has an ambiguous token order
            (BUG-G002 "Aubert John" without comma / all-caps).

    When ``sender_name`` is empty (rare in production — Gmail/Outlook
    almost always provide one), fall back to a formality-appropriate
    generic greeting instead of returning ``""``. An empty hint causes
    ``_enforce_greeting`` to STRIP whatever greeting the LLM emitted,
    leaving a body that opens cold (Bug D, 2026-05-13 stress test).
    Hot-thread continuation paths set the empty hint explicitly at the
    call site (see smart_routing.py:1631), so this fallback does not
    break the "no greeting on hot-thread reply" intent.
    """
    # Placeholder/provider names ("Unknown", "Inconnu", "[à définir]", …)
    # are not usable greetings. Clear them so the later, stronger fallbacks can
    # use a matching signature or email local-part before returning generic text.
    if is_placeholder_style_value(sender_name) or _is_unknown_sender_name(sender_name):
        sender_name = ""

    signature_name = _signature_name_matching_email(signature_text, sender_email)

    if not sender_name:
        if signature_name:
            sender_name = signature_name
        else:
            email_name_tokens = _email_local_name_tokens(sender_email)
            if email_name_tokens:
                sender_name = " ".join(
                    token.capitalize()
                    for token in (
                        (email_name_tokens[0], email_name_tokens[-1])
                        if len(email_name_tokens) >= 2
                        else (email_name_tokens[0],)
                    )
                )
    if not sender_name:
        if language == "ENGLISH":
            return "Hello," if formality >= 3 else "Hi,"
        return "Bonjour," if formality >= 3 else "Salut,"

    signature_name = signature_name or ""

    # Clean titles and suffixes BEFORE person detection (handles "Alexandre - Consultant" etc.)
    cleaned_name, forced_feminine, preserved_title = _clean_sender_name(sender_name)
    name_to_check = cleaned_name.strip() if cleaned_name else sender_name.strip()
    # Strip role/title suffixes after separators: "John Doe - CEO", "John | Consultant", "John, Founder"
    for sep in (' - ', ' | ', ' — ', ' – '):
        if sep in name_to_check:
            name_to_check = name_to_check.split(sep)[0].strip()
            break

    email_name_tokens = _email_local_name_tokens(sender_email)

    # Detect non-person senders (teams, services, roles) on the cleaned name
    if not _is_person_name(name_to_check):
        is_service_sender = _display_has_explicit_service_word(name_to_check)
        if is_service_sender:
            if formality >= 3:
                return "Bonjour," if language != "ENGLISH" else "Hello,"
            else:
                return "Salut," if language != "ENGLISH" else "Hi,"
        signature_person = _signature_person_name(signature_text)
        if signature_name:
            name_to_check = signature_name
        elif len(email_name_tokens) >= 2:
            name_to_check = " ".join(
                token.capitalize() for token in (email_name_tokens[0], email_name_tokens[-1])
            )
        elif signature_person:
            name_to_check = signature_person
        else:
            if formality >= 3:
                return "Bonjour," if language != "ENGLISH" else "Hello,"
            else:
                return "Salut," if language != "ENGLISH" else "Hi,"

    signature_words = _name_words(signature_name)
    display_words = _name_words(name_to_check)
    display_is_signature_last_name = (
        bool(signature_words)
        and len(display_words) == 1
        and len(signature_words) >= 2
        and any(
            _name_token_matches(display_words[0], word)
            for word in signature_words[1:]
        )
        and not _name_token_matches(display_words[0], signature_words[0])
    )
    if signature_name and (
        _display_name_conflicts_with_email_tokens(name_to_check, email_name_tokens)
        or display_is_signature_last_name
    ):
        name_to_check = signature_name
    elif _display_name_conflicts_with_email_tokens(name_to_check, email_name_tokens):
        # Gmail/Outlook can expose a branded display name ("Crypto Formation")
        # while the actual address still carries the human sender
        # (alexandre.simon@...). In that case the address is the better
        # first-name signal; otherwise every draft opens with the brand token.
        name_to_check = " ".join(
            token.capitalize() for token in (email_name_tokens[0], email_name_tokens[-1])
        )

    # BUG-G002 fix: handle "Last, First" (vCard / French corporate format)
    # e.g. "Aubert, Jean" → reorder to "Jean Aubert" before splitting
    if name_to_check and ',' in name_to_check:
        _comma_parts = name_to_check.split(',', 1)
        _last_part = _comma_parts[0].strip()
        _first_part = _comma_parts[1].strip()
        if _first_part:  # Valid "Last, First" format
            name_to_check = f"{_first_part} {_last_part}"

    parts = name_to_check.split() if name_to_check else sender_name.strip().split()

    # BUG-G002 fix: detect ALL-CAPS first token (French directory format "DUPONT Marie")
    # If the first word is all uppercase and there is a second word in proper case,
    # the name is in "LAST First" order — swap to use the second word as first_name.
    if (len(parts) >= 2
            and parts[0] == parts[0].upper()
            and parts[0] != parts[0].lower()  # at least one uppercase letter
            and len(parts[0]) > 1):
        first_name = parts[1]
        last_name = parts[0]
    else:
        first_name = parts[0] if parts else sender_name
        last_name = parts[-1] if len(parts) > 1 else ""
        # BUG-G002 extension: when sender email prefix is derivable and the PROPER-case
        # name is ambiguous (e.g. "Aubert John" stored without comma), prefer the
        # token that matches the email's local-part prefix as first_name.
        # Conservative: only swap if the second token matches email prefix AND first doesn't.
        if len(parts) >= 2 and "@" in (sender_email or ""):
            try:
                _local = (sender_email.split("@")[0] or "").strip("<>\"' ").lower()
                # Email prefix often looks like "firstname.lastname" or "firstname"
                _first_prefix = _local.split(".")[0] if _local else ""
                if _first_prefix and len(_first_prefix) >= 2:
                    p0_lower = parts[0].lower()
                    p1_lower = parts[1].lower()
                    if p1_lower.startswith(_first_prefix) and not p0_lower.startswith(_first_prefix):
                        first_name, last_name = parts[1], parts[0]
            except Exception:
                pass
        # Single-token display name ("Aubert"): when the email prefix exposes
        # a richer "first.last" pair AND the sole word matches the LAST token,
        # promote the first email token to first_name. This recovers cases like
        # `"Aubert" <alexandra.aubert@…>` where the From header dropped the
        # first name. Conservative — only triggers if the sole word matches
        # the trailing email token but NOT the leading one.
        elif len(parts) == 1 and "@" in (sender_email or ""):
            try:
                _local = (sender_email.split("@")[0] or "").strip("<>\"' ").lower()
                _email_tokens = [t for t in _re.split(r"[._\-+]", _local)
                                 if t.isalpha() and len(t) >= 2]
                _sole = parts[0].lower()
                if (len(_email_tokens) >= 2
                        and _email_tokens[-1] == _sole
                        and _email_tokens[0] != _sole):
                    first_name = _email_tokens[0].capitalize()
                    last_name = parts[0]
            except Exception:
                pass

    # Gender detection for formal greetings
    is_feminine = forced_feminine or _is_likely_feminine(first_name)

    if formality >= 4:
        if language == "ENGLISH":
            if last_name:
                if preserved_title:
                    return f"{preserved_title} {last_name},"
                title = "Ms." if is_feminine else "Mr."
                return f"Dear {title} {last_name},"
            return f"Dear {first_name},"
        else:
            if last_name:
                if preserved_title:
                    return f"{preserved_title} {last_name},"
                title = "Mme" if is_feminine else "M."
                return f"{title} {last_name},"
            return f"Bonjour {first_name},"
    elif formality == 3:
        if language == "ENGLISH":
            return f"Hi {first_name},"
        else:
            return f"Bonjour {first_name},"
    elif formality == 2:
        if language == "ENGLISH":
            return f"Hey {first_name},"
        else:
            return f"Salut {first_name},"
    else:
        # formality 1 (VERY CASUAL) — no greeting, like texting a friend
        return ""


_FRENCH_CLOSING_MARKERS = (
    "cordialement", "sincèrement", "à bientôt", "bientôt",
    "bien à vous", "bien à toi", "amicalement", "amitiés",
    "chaleureusement", "cdlt", "bien cordialement",
    # "merci" is the single most common French sign-off and was missing here,
    # so an English draft signed "Merci," was never recognised as French and
    # never translated (user report 2026-06-23). Covers "merci",
    # "merci beaucoup", "merci d'avance".
    "merci",
)

_ENGLISH_CLOSING_MARKERS = (
    "best regards", "kind regards", "warm regards", "regards",
    "sincerely", "best", "cheers", "talk soon", "thank you",
    "thanks", "many thanks", "all the best",
)

# Maps common French closings to their closest English equivalents so the
# user's warmth/formality level is preserved when replying in English.
_FRENCH_TO_ENGLISH_CLOSING: dict[str, str] = {
    "cordialement": "Best regards",
    "bien cordialement": "Best regards",
    "sincèrement": "Sincerely",
    "sincerement": "Sincerely",
    "à bientôt": "Talk soon",
    "a bientot": "Talk soon",
    "bientôt": "Talk soon",
    "bien à vous": "Best regards",
    "bien a vous": "Best regards",
    "bien à toi": "Best",
    "bien a toi": "Best",
    "amicalement": "Best",
    "amitiés": "Warm regards",
    "amities": "Warm regards",
    "chaleureusement": "Warm regards",
    "cdlt": "Best regards",
    # Longest variants first — _translate_closing_to_english returns on the first
    # substring hit, so "merci beaucoup" must precede "merci".
    "merci beaucoup": "Thank you",
    "merci d'avance": "Thanks in advance",
    "merci d’avance": "Thanks in advance",
    "merci": "Thanks",
}

# Reverse map: an English sign-off leaked into a French draft ("Best,",
# "Cheers,") gets rewritten to its French equivalent. Longest/most-specific
# keys first — _translate_closing_to_french returns on the first substring hit.
_ENGLISH_TO_FRENCH_CLOSING: dict[str, str] = {
    "best regards": "Cordialement",
    "kind regards": "Cordialement",
    "warm regards": "Bien cordialement",
    "all the best": "Bien à vous",
    "many thanks": "Merci beaucoup",
    "talk soon": "À bientôt",
    "thank you": "Merci",
    "thanks": "Merci",
    "sincerely": "Sincèrement",
    "regards": "Cordialement",
    "cheers": "À bientôt",
    "best": "Cordialement",
}


def _is_french_closing(candidate: str) -> bool:
    """Return True if candidate looks like a French-language closing."""
    lowered = candidate.lower()
    return any(marker in lowered for marker in _FRENCH_CLOSING_MARKERS)


def _is_english_closing(candidate: str) -> bool:
    """Return True if candidate looks like an English-language closing."""
    lowered = candidate.lower()
    return any(marker in lowered for marker in _ENGLISH_CLOSING_MARKERS)


def _translate_closing_to_english(candidate: str) -> str | None:
    """Return the English equivalent of a French closing, or None if unknown."""
    lowered = candidate.lower()
    for fr, en in _FRENCH_TO_ENGLISH_CLOSING.items():
        if fr in lowered:
            return en
    return None


def _translate_closing_to_french(candidate: str) -> str | None:
    """Return the French equivalent of an English closing, or None if unknown."""
    lowered = candidate.lower()
    for en, fr in _ENGLISH_TO_FRENCH_CLOSING.items():
        if en in lowered:
            return fr
    return None


def normalize_closing_to_language(body: str, language: str) -> str:
    """Rewrite a trailing sign-off that is in the wrong language.

    The compose/reply LLM occasionally signs an otherwise-English draft with a
    French closing ("Merci,") — or the reverse — despite the prompt's explicit
    language directive (user report 2026-06-23: English email ending in
    "Merci,"). This deterministically rewrites ONLY the final closing line to
    match ``language``, leaving the rest of the body untouched.

    Conservative by design: it acts only on a short (<= 4 word) trailing line
    that is recognisably a closing in the *other* language AND has a known
    translation. Anything else is returned unchanged, so it can never mangle a
    real sentence or invent a sign-off the user didn't write.

    Args:
        body: The drafted email body (signature already stripped).
        language: Target language of the body — ``"en"`` or ``"fr"``. Any other
            value is a no-op (no Spanish closing tables yet).
    """
    if not body or language not in ("en", "fr"):
        return body
    lines = body.rstrip().split("\n")
    idx = len(lines) - 1
    while idx >= 0 and not lines[idx].strip():
        idx -= 1
    if idx < 0:
        return body
    candidate = lines[idx].strip().rstrip(",.;:! ")
    # A closing is 1-4 words; bail on anything sentence-shaped to stay safe.
    if not candidate or len(candidate.split()) > 4:
        return body
    if language == "en" and _is_french_closing(candidate):
        translated = _translate_closing_to_english(candidate)
        if translated:
            lines[idx] = _format_closing(translated)
            return "\n".join(lines)
    elif language == "fr" and _is_english_closing(candidate):
        translated = _translate_closing_to_french(candidate)
        if translated:
            lines[idx] = _format_closing(translated)
            return "\n".join(lines)
    return body


# Sentinel emitted by the onboarding ProfileAgent in `closing_styles.casual_*`
# to mark "user uses no closing in this register — just their name or
# nothing". Stored verbatim in WritingStyleProfile.preferred_closings via
# manager.py:2621, where it's a meaningful tag. We must NOT pass it through
# to the LLM as if it were a real closing — that's how the literal string
# "(no closing or just name)," leaked into a generated reply (2026-05-11).
# Frontend uses the same regex in StyleDetectedSection.tsx:81.
import re as _re_closing
_NO_CLOSING_MARKER_RE = _re_closing.compile(r"no\s*closing|just\s*name", _re_closing.IGNORECASE)


def _is_no_closing_marker(s: str) -> bool:
    """True when the string is the onboarding sentinel for "use no closing"."""
    return bool(s and _NO_CLOSING_MARKER_RE.search(s))


# Writing-style "no signal" placeholders. The account-level style analyzer
# (writing_style_analyzer_adapter) and the onboarding tone agent occasionally
# return descriptive non-values like "Unknown", "Unknown (forwarded content)",
# "Salut Unknown", "Inconnu", "None", "N/A" when the analysed sent corpus has
# no usable greeting/closing (the emails were forwards or had empty bodies).
# Such a value must NEVER reach a draft — the caller drops it and falls through
# to the clean formality+language default. This mirrors the onboarding
# ProfileAgent prompt guard (profile.txt) which already forbids these literals.
_PLACEHOLDER_STYLE_RE = _re_closing.compile(
    r"\b(?:unknown|inconnue?|undefined|null|none|n/?a|nil)\b"
    r"|\((?:forwarded\b|empty\s+bod|no\s+(?:signal|greeting|closing|content|body))",
    _re_closing.IGNORECASE,
)


def is_placeholder_style_value(value: object) -> bool:
    """True when a greeting/closing/name string is an LLM "no signal" placeholder.

    See ``_PLACEHOLDER_STYLE_RE``. Empty / non-string inputs return False (the
    caller handles "missing" separately from "garbage placeholder").
    """
    if not isinstance(value, str) or not value.strip():
        return False
    return bool(_PLACEHOLDER_STYLE_RE.search(value))


def _format_closing(candidate: str) -> str:
    """Render the canonical closing line from a stripped candidate.

    Most closings ("Cordialement", "À bientôt") take a trailing comma. But
    sign-offs whose terminal character is already a strong punctuation mark
    ("Merci!", "Bonne soirée?") read naturally without one — appending a
    comma there produces "Merci!," which the user did not write. Bug fix
    2026-05-13 (user-reported "Merci!," draft).
    """
    if candidate.endswith(("!", "?")):
        return candidate
    return f"{candidate},"


def _compute_closing_hint(
    formality: int,
    language: str,
    preferred_closings: list[str] | None = None,
) -> str:
    """
    Compute the expected closing line (e.g. "Sincèrement,").

    Priority:
      1. User's own preferred closing (from WritingStyleProfile) if available
         and compatible with the reply language. French closings are translated
         to English equivalents when language=ENGLISH so the user's warmth
         level is preserved rather than falling back to generic defaults.
         Sentinel markers like "(no closing or just name)" are honoured by
         skipping straight to formality<=1 behaviour (no closing).
      2. Formality + language default

    Args:
        formality: 1-5 score (1 = very casual, 5 = very formal).
        language: "ENGLISH", "FRENCH", or "SPANISH".
        preferred_closings: Top closings extracted from the user's sent emails.

    Returns:
        The closing line (with trailing comma), or "" for VERY CASUAL
        (formality 1) where a closing would feel out of place.
    """
    # 1. Honour the user's own style. For English replies, translate French
    # closings to their English equivalents rather than skipping them entirely.
    # NOTE: this function returns the FIRST language-compatible entry, so the
    # caller decides priority by ORDERING the list. The refine path prepends a
    # per-contact closing at index 0 to make it win; `_closing_hint_for`
    # reorders by formality (casual slot first for a casual reply). We
    # deliberately do NOT reorder here — doing so broke the prepend contract.
    if preferred_closings:
        saw_no_closing_marker = False
        for raw in preferred_closings:
            if not raw:
                continue
            candidate = raw.strip().rstrip(',.;: ')
            if not candidate:
                continue
            if _is_no_closing_marker(candidate):
                # Onboarding sentinel — the user uses no closing in their most
                # casual register. Remember it but keep scanning in case the
                # profile also has a real closing for higher formality.
                saw_no_closing_marker = True
                continue
            if is_placeholder_style_value(candidate):
                # Analyzer "no signal" placeholder leaked into the default
                # closings ("Unknown (forwarded content)") — drop it so we fall
                # through to the formality+language default. 2026-06-01 fix.
                continue
            if language == "ENGLISH" and _is_french_closing(candidate):
                translated = _translate_closing_to_english(candidate)
                if translated:
                    return _format_closing(translated)
                continue  # unknown French closing — skip, try next
            if language == "FRENCH" and _is_english_closing(candidate):
                continue
            # For a Spanish draft, never leak a French/English preferred
            # closing (e.g. a French user's "Cordialement," / "Best,") — skip
            # it and fall through to the Spanish formality default. We don't
            # translate here because there's no FR/EN→ES closing table.
            if language == "SPANISH" and (
                _is_french_closing(candidate) or _is_english_closing(candidate)
            ):
                continue
            return _format_closing(candidate)
        # All preferred closings were either empty or the no-closing marker.
        # Treat as "user prefers no closing" and return "" — falling through
        # to the formality default would override the user's explicit signal.
        if saw_no_closing_marker:
            return ""

    # 2. Formality + language fallback
    if formality <= 1:
        # VERY CASUAL — no closing, like texting a friend
        return ""

    if language == "ENGLISH":
        if formality >= 4:
            return "Best regards,"
        if formality == 3:
            return "Best,"
        return "Cheers,"

    if language == "SPANISH":
        if formality >= 4:
            return "Atentamente,"
        if formality == 3:
            return "Saludos cordiales,"
        return "Un saludo,"

    # French default
    if formality >= 4:
        return "Cordialement,"
    if formality == 3:
        return "Sincèrement,"
    return "À bientôt,"


# ============================================================================
# FONCTIONS UTILITAIRES
# ============================================================================









# ============================================================================
