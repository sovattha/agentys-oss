# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Mixin pour le parsing d'emails.

Fournit des utilitaires communs pour parser les emails dans les adapters.
Ce pattern DRY (Don't Repeat Yourself) evite la duplication de code
entre GmailAdapter, OutlookAdapter et IMAPAdapter.

Clean Architecture:
- Couche Infrastructure (shared utilities)
- Ne depend d'aucune implementation concrete
"""

import re
from typing import Dict, Optional, Tuple

try:
    from ftfy import fix_encoding as _ftfy_fix_encoding
except ImportError:  # pragma: no cover - ftfy is declared in requirements.txt
    _ftfy_fix_encoding = None


class EmailParserMixin:
    """
    Mixin fournissant des utilitaires de parsing d'emails.

    Utilise par les adapters email pour:
    - Parser les adresses email avec noms
    - Extraire le texte du HTML
    - Decoder les headers encodes

    Usage:
        class MyAdapter(EmailProvider, EmailParserMixin):
            def parse_sender(self, header: str) -> tuple:
                return self._parse_email_address(header)
    """

    # Regex pre-compilees pour de meilleures performances
    _EMAIL_WITH_NAME_RE = re.compile(
        r'^(?:"?([^"<]*)"?\s*)?<([^<>\s]+@[^<>\s]+)>$'
    )
    # Supporte +, ., - dans la partie locale (user+tag@example.com)
    _SIMPLE_EMAIL_RE = re.compile(r'^[\w\.\-\+]+@[\w\.-]+\.\w+$')
    # ReDoS guard (chaos audit 2026-06-02): this one is UNANCHORED and run via
    # .search() as a fallback, so on a long no-'@' header the greedy unbounded
    # local-part backtracked O(n^2) and hung the (single) worker. RFC 5321 caps
    # the local-part at 64 and a domain label at 63 — bounding the quantifiers
    # makes per-start-position work constant (overall linear) without changing
    # which real addresses match.
    _EMAIL_IN_TEXT_RE = re.compile(r'[\w\.\-\+]{1,64}@[\w\.\-]{1,255}\.\w{1,24}')
    _HTML_TAG_RE = re.compile(r'<[^>]+>')
    _STYLE_SCRIPT_RE = re.compile(r'<(style|script)[^>]*>.*?</\1>', re.DOTALL | re.IGNORECASE)
    _WHITESPACE_RE = re.compile(r'[ \t]+')
    _BLANK_LINES_RE = re.compile(r'\n\s*\n+')
    _CSS_JUNK_RE = re.compile(r'@media\b|!important|{[^}]*display\s*:|{[^}]*min-width\s*:', re.IGNORECASE)
    _CID_SRC_RE = re.compile(r'(<img\b[^>]*\bsrc\s*=\s*["\'])cid:([^"\'>\s]+)(["\'])', re.IGNORECASE)

    @staticmethod
    def _demojibake(text: Optional[str]) -> Optional[str]:
        """Repare un texte corrompu en mojibake UTF-8-lu-en-Latin-1.

        Certains emails arrivent avec des octets UTF-8 deja mal decodes une
        fois en Latin-1/CP1252 (``Université`` -> ``UniversitÃ©``, ``c'est`` ->
        ``câ€™est``). On detecte le motif revelateur ``Ã`` / ``Â`` / ``â€`` puis
        on confie la reparation a ``ftfy.fix_encoding``, qui — contrairement a
        un aller-retour ``encode('latin-1')`` brut — :

          * gere le contenu MIXTE (mojibake + ``€`` / emoji / guillemet courbe)
            sequence par sequence. L'ancien code renvoyait la chaine INTACTE des
            qu'un seul codepoint > U+00FF apparaissait, car ``.encode('latin-1')``
            levait alors une exception sur toute la chaine — donc les corps
            francais (qui contiennent presque toujours un ``€`` ou une
            apostrophe courbe) restaient mojibake (bug Y003 / F-01) ;
          * n'applique la correction QUE si elle rend le texte moins aberrant
            (modele de "badness" interne a ftfy), ce qui evite de reinterpreter
            a l'aveugle un texte deja correct comme le faisait l'ancien code
            (F-02 : ``Ãª`` clair -> ``ê`` sans verification).

        Idempotent sur une chaine sans marqueur (renvoyee telle quelle, sans
        meme appeler ftfy) ; tout echec renvoie l'original intact.
        """
        markers = ("Ã", "Â", "â€")
        if not text or not any(marker in text for marker in markers):
            return text

        def _repair_short_sequences(value: str) -> str:
            # Repli si ftfy est indisponible ou laisse une sequence encore
            # suspecte : decode uniquement les courtes sequences mojibake
            # valides pour preserver le contenu mixte deja correct (€ / emoji).
            fixed: list[str] = []
            i = 0
            while i < len(value):
                width = 0
                if value[i] in ("Ã", "Â"):
                    width = 2
                elif value[i] == "â":
                    width = 3

                if width and i + width <= len(value):
                    chunk = value[i:i + width]
                    for encoding in ("cp1252", "latin-1"):
                        try:
                            fixed.append(chunk.encode(encoding).decode("utf-8"))
                            i += width
                            break
                        except (UnicodeEncodeError, UnicodeDecodeError):
                            continue
                    else:
                        fixed.append(value[i])
                        i += 1
                    continue

                fixed.append(value[i])
                i += 1

            return "".join(fixed)

        if _ftfy_fix_encoding is not None:
            try:
                repaired = _ftfy_fix_encoding(text)
                if repaired != text or not any(marker in repaired for marker in markers):
                    return repaired
            except Exception:
                pass

        return _repair_short_sequences(text)

    def _parse_email_address(self, header_value: str) -> Tuple[str, Optional[str]]:
        """
        Parse une adresse email avec nom optionnel.

        Formats supportes:
        - "Name" <email@example.com>
        - Name <email@example.com>
        - email@example.com
        - Texte avec email@example.com dedans

        Args:
            header_value: La valeur du header email (From, To, etc.)

        Returns:
            Tuple (email, name) ou (email, None) si pas de nom.

        Examples:
            >>> self._parse_email_address('"John Doe" <john@example.com>')
            ('john@example.com', 'John Doe')

            >>> self._parse_email_address('john@example.com')
            ('john@example.com', None)
        """
        if not header_value:
            return "", None

        value = header_value.strip()

        # Format: "Name" <email@example.com> ou Name <email@example.com>
        match = self._EMAIL_WITH_NAME_RE.match(value)
        if match:
            name, email = match.groups()
            if name:
                cleaned = self._demojibake(name.strip())
                # Audit 2026-05-18: strip invisible/format chars (variation
                # selectors, ZWJs, tag chars) and surface mixed-script
                # homograph attacks. The boolean lands on StandardEmail via
                # the adapter, which also re-runs detect_sender_spoofing so
                # callers that build StandardEmail without going through
                # this helper still get the flag.
                from app.utils.sender_spoofing import strip_invisible
                cleaned = strip_invisible(cleaned) if cleaned else cleaned
                return email.strip(), cleaned
            return email.strip(), None

        # Format simple: email@example.com
        if self._SIMPLE_EMAIL_RE.match(value):
            return value, None

        # Fallback: extraire l'email du texte
        email_match = self._EMAIL_IN_TEXT_RE.search(value)
        if email_match:
            return email_match.group(), None

        # Dernier recours: si ca contient @, retourner tel quel
        if "@" in value:
            return value, None

        return "", None

    def _extract_text_from_html(self, html: str) -> str:
        """
        Extrait le texte brut d'un contenu HTML.

        Supprime les balises HTML, décode les entités et retourne le texte.

        Args:
            html: Contenu HTML.

        Returns:
            Texte brut sans balises.
        """
        if not html:
            return ""
        import html as html_module
        # Supprimer les blocs <style> et <script> avec leur contenu
        text = self._STYLE_SCRIPT_RE.sub('', html)
        # Supprimer les balises HTML restantes
        text = self._HTML_TAG_RE.sub('', text)
        # Décoder les entités HTML (ex: &eacute; -> é)
        text = html_module.unescape(text)
        # Nettoyer les espaces multiples et lignes vides
        text = self._WHITESPACE_RE.sub(' ', text)
        text = self._BLANK_LINES_RE.sub('\n', text)
        return text.strip()

    def _looks_like_css_or_html(self, text: str) -> bool:
        """Détecte si un texte est du CSS/HTML brut au lieu de contenu lisible."""
        if not text:
            return False
        sample = text[:500]
        return bool(self._CSS_JUNK_RE.search(sample))

    def _normalize_recipients(self, header: str) -> list:
        """
        Parse une liste de destinataires depuis un header.

        Args:
            header: Header To/Cc avec potentiellement plusieurs adresses.

        Returns:
            Liste d'adresses email.

        Example:
            >>> self._normalize_recipients("alice@ex.com, bob@ex.com")
            ['alice@ex.com', 'bob@ex.com']
        """
        if not header:
            return []

        recipients = []
        for addr in header.split(","):
            addr = addr.strip()
            if addr:
                email, _ = self._parse_email_address(addr)
                if email:
                    recipients.append(email)

        return recipients

    def _resolve_cid_images(self, html: str, cid_map: Dict[str, Tuple[str, str]]) -> str:
        """
        Replace cid: references in HTML with inline base64 data URIs.

        Args:
            html: HTML body content.
            cid_map: Dict mapping content_id -> (mime_type, base64_data).
                     Content IDs should be without angle brackets.

        Returns:
            HTML with cid: references replaced by data: URIs.
        """
        if not html or not cid_map:
            return html

        def _replace_cid(match):
            prefix = match.group(1)   # <img ... src="
            cid = match.group(2)      # content-id value
            suffix = match.group(3)   # closing quote
            # Try exact match, then without angle brackets
            entry = cid_map.get(cid) or cid_map.get(cid.strip("<>"))
            if entry:
                mime_type, b64_data = entry
                return f"{prefix}data:{mime_type};base64,{b64_data}{suffix}"
            return match.group(0)

        return self._CID_SRC_RE.sub(_replace_cid, html)
