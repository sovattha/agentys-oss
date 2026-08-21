# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
FAQ Scanner: extracts FAQ Q&A pairs from websites and documents.

URL extraction (multi-tier, merged — all $0 tiers run in parallel):
  1.   Schema.org FAQPage JSON-LD   (structured data → $0)
  1.5  Inline JS data stores        (Next.js __NEXT_DATA__, window.__X__ → $0)
  2.   HTML pattern matching         (details/summary, accordion, headings → $0)
  3.   LLM extraction via Haiku      (fallback when structural tiers yield nothing → ~$0.001)

  Tiers 1, 1.5 and 2 are always run and their results are merged + deduplicated.
  LLM (tier 3) is only called when all structural tiers return nothing.
  Hidden tab detection runs regardless and surfaces a warning to the user.

Document extraction:
  - PDF (via pdfplumber)
  - TXT (plain read)
  - DOCX (via python-docx)
  All documents are parsed to text, then Q&A pairs extracted via LLM.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

from app.utils.safe_outbound import SsrfBlocked, safe_get

logger = logging.getLogger(__name__)

# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class FaqEntry:
    """A single extracted FAQ question-answer pair."""
    question: str
    answer: str
    source: str = "manual"  # "schema.org", "js_store", "html", "llm", "document"

    def to_dict(self) -> dict:
        return {"question": self.question, "answer": self.answer, "source": self.source}


@dataclass
class ScanResult:
    """Result of a FAQ scan operation."""
    faq: list[FaqEntry] = field(default_factory=list)
    extraction_tier: str = ""  # e.g. "schema.org", "schema.org+js_store", "html", "llm"
    source_url: str = ""
    filename: str = ""
    error: Optional[str] = None
    hidden_tabs: list[str] = field(default_factory=list)  # tab names skipped (JS-rendered)

    def to_dict(self) -> dict:
        return {
            "faq": [e.to_dict() for e in self.faq],
            "extraction_tier": self.extraction_tier,
            "source_url": self.source_url,
            "filename": self.filename,
            "error": self.error,
            "hidden_tabs": self.hidden_tabs,
        }


# ── URL scanning ─────────────────────────────────────────────────────────────

_REQUEST_TIMEOUT = 15
_MAX_PAGE_SIZE = 500_000  # 500 KB max for HTML
_USER_AGENT = "Agentys-FAQ-Scanner/1.0"

# Common FAQ-related CSS class/id patterns
_FAQ_CLASS_PATTERNS = re.compile(
    r"faq|frequently[_-]?asked|accordion|collapse|expandable|toggle[_-]?item",
    re.IGNORECASE,
)

# FAQ heading patterns (h1-h4)
_FAQ_HEADING_RE = re.compile(
    r"(?:FAQ|Frequently\s+Asked\s+Questions|Questions\s+fr[ée]quentes|Foire\s+aux\s+questions|F\.A\.Q\.)",
    re.IGNORECASE,
)


def scan_url(url: str) -> ScanResult:
    """Scan a URL for FAQ content using the multi-tier merge strategy.

    All $0-cost tiers (Schema.org, JS data stores, HTML patterns) run and their
    results are merged and deduplicated. LLM is only used as a last resort when
    all structural tiers yield nothing.
    """
    try:
        # SSRF-VULN-01 (issue #557): centralized SSRF defenses — scheme allowlist,
        # private-IP filter (incl. 169.254.169.254 cloud metadata), redirects
        # re-validated per hop. Public callers can no longer exfiltrate AWS
        # IMDS via a 302 chain.
        resp = safe_get(
            url,
            timeout=_REQUEST_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
        )
        resp.raise_for_status()
    except SsrfBlocked as e:
        logger.warning("FAQ scanner: URL bloquée (SSRF defense): %s — %s", url, e)
        return ScanResult(error=f"URL non autorisée : {e}", source_url=url)
    except requests.RequestException as e:
        logger.warning("FAQ scanner: failed to fetch %s: %s", url, e)
        return ScanResult(error=f"Impossible de charger la page : {e}", source_url=url)

    content_type = resp.headers.get("content-type", "")
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        return ScanResult(error="La page n'est pas du HTML", source_url=url)

    html = resp.text[:_MAX_PAGE_SIZE]
    all_entries: list[FaqEntry] = []
    tiers_used: list[str] = []

    # Tier 1: Schema.org FAQPage JSON-LD
    schema_entries = _extract_schema_org(html)
    if schema_entries:
        all_entries.extend(schema_entries)
        tiers_used.append("schema.org")
        logger.debug("FAQ scanner: tier 1 (Schema.org) found %d entries", len(schema_entries))

    # Tier 1.5: Inline JS data stores (Next.js __NEXT_DATA__, window.__ assignments…)
    js_entries = _extract_js_data_stores(html)
    if js_entries:
        all_entries.extend(js_entries)
        tiers_used.append("js_store")
        logger.debug("FAQ scanner: tier 1.5 (JS stores) found %d entries", len(js_entries))

    # Tier 2: HTML pattern matching — always run when structural results are thin
    # (Schema.org may only cover one tab; HTML may cover static markup of another)
    if len(all_entries) < 5:
        html_entries = _extract_html_patterns(html)
        if html_entries:
            all_entries.extend(html_entries)
            tiers_used.append("html")
            logger.debug("FAQ scanner: tier 2 (HTML) found %d entries", len(html_entries))

    # Detect hidden / JS-rendered tabs (for user-facing warning)
    hidden_tabs = _detect_hidden_tabs(html)

    # Deduplicate across all tiers
    all_entries = _deduplicate(all_entries)

    if all_entries:
        tier_label = "+".join(tiers_used) if tiers_used else "mixed"
        logger.info(
            "FAQ scanner: found %d entries (tiers: %s) from %s",
            len(all_entries), tier_label, url,
        )
        return ScanResult(
            faq=all_entries,
            extraction_tier=tier_label,
            source_url=url,
            hidden_tabs=hidden_tabs,
        )

    # Tier 3: LLM extraction (Haiku) — last resort
    cleaned_text = _clean_html_to_text(html)
    if len(cleaned_text.strip()) < 100:
        return ScanResult(
            error="Page trop courte ou vide — aucune FAQ détectée",
            source_url=url,
            hidden_tabs=hidden_tabs,
        )

    llm_entries = _extract_with_llm(cleaned_text)
    if llm_entries:
        logger.info("FAQ scanner: tier 3 (LLM) found %d entries from %s", len(llm_entries), url)
        return ScanResult(
            faq=llm_entries,
            extraction_tier="llm",
            source_url=url,
            hidden_tabs=hidden_tabs,
        )

    # Build informative error — include tab names if we detected hidden ones
    error_msg = "Aucune FAQ détectée sur cette page"
    if hidden_tabs:
        tab_list = ", ".join(f'"{t}"' for t in hidden_tabs[:3])
        error_msg += (
            f". Des onglets ({tab_list}) ont été détectés mais ne peuvent pas être lus"
            f" (le contenu est rendu côté client). Importez un document à la place."
        )

    return ScanResult(error=error_msg, source_url=url, hidden_tabs=hidden_tabs)


# ── Tier 1: Schema.org FAQPage ──────────────────────────────────────────────

def _extract_schema_org(html: str) -> list[FaqEntry]:
    """Extract FAQ from Schema.org FAQPage JSON-LD structured data."""
    entries: list[FaqEntry] = []

    pattern = re.compile(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.DOTALL | re.IGNORECASE,
    )
    for match in pattern.finditer(html):
        try:
            data = json.loads(match.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            continue

        items = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
        if isinstance(data, dict) and "@graph" in data:
            items = data["@graph"]

        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = item.get("@type", "")
            if isinstance(item_type, list):
                item_type = " ".join(item_type)
            if "FAQPage" not in item_type:
                continue

            main_entity = item.get("mainEntity", [])
            if isinstance(main_entity, dict):
                main_entity = [main_entity]

            for qa in main_entity:
                if not isinstance(qa, dict):
                    continue
                if "Question" not in str(qa.get("@type", "")):
                    continue
                question = qa.get("name", "").strip()
                accepted = qa.get("acceptedAnswer", {})
                answer = accepted.get("text", "").strip() if isinstance(accepted, dict) else ""
                if question and answer:
                    answer = re.sub(r"<[^>]+>", "", answer).strip()
                    entries.append(FaqEntry(question=question, answer=answer, source="schema.org"))

    return entries


# ── Tier 1.5: Inline JS data stores ─────────────────────────────────────────
#
# React/Next.js apps embed their pre-hydration data as JSON in <script> tags.
# This data is present in the raw HTML response — no JS execution needed.
# We walk the full JSON tree recursively looking for FAQ-shaped arrays at any depth.

# Hard keys are strongly specific to Q&A schemas.
# Soft keys are common generic field names — require at least one hard key on Q or A side.
_Q_KEYS_HARD = frozenset({"question", "q", "query"})
_Q_KEYS_SOFT = frozenset({"title", "heading", "name", "label", "ask"})
_A_KEYS_HARD = frozenset({"answer", "a", "response", "reply", "solution"})
_A_KEYS_SOFT = frozenset({"body", "description", "content", "text", "detail", "message"})

# Captures any window.FOO = { or window.FOO = [ assignment in a script tag
_WINDOW_ASSIGN_RE = re.compile(
    r'window\.[_$A-Za-z][_$A-Za-z0-9]*\s*=\s*([{[])',
)


def _extract_js_data_stores(html: str) -> list[FaqEntry]:
    """Extract FAQ from inline JavaScript data stores embedded in the page HTML.

    Targets:
      - Next.js: <script id="__NEXT_DATA__" type="application/json">
      - Nuxt / generic: window.__NUXT__, window.__INITIAL_STATE__, window.__APP_DATA__
      - Any window.X = {…} or window.X = […] that contains a FAQ-shaped array

    The JSON tree is walked recursively; FAQ arrays are detected at any depth.
    """
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
    except ImportError:
        logger.warning("beautifulsoup4 not installed — skipping JS data store extraction")
        return []

    all_entries: list[FaqEntry] = []

    # ── Strategy A: Next.js <script id="__NEXT_DATA__" type="application/json"> ──
    next_data_tag = soup.find("script", id="__NEXT_DATA__")
    if next_data_tag and next_data_tag.string:
        try:
            data = json.loads(next_data_tag.string)
            found = _find_faq_in_json(data)
            if found:
                all_entries.extend(found)
                logger.debug("JS stores: __NEXT_DATA__ yielded %d FAQ entries", len(found))
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # ── Strategy B: window.X = {…} assignments in other <script> tags ───────
    if not all_entries:
        for script_tag in soup.find_all("script"):
            tag_type = script_tag.get("type", "")
            tag_id = script_tag.get("id", "")
            # Skip JSON-LD (tier 1) and __NEXT_DATA__ (already handled above)
            if "ld+json" in tag_type or tag_id == "__NEXT_DATA__":
                continue

            content = script_tag.string
            if not content or len(content) < 100:
                continue

            for match in _WINDOW_ASSIGN_RE.finditer(content):
                json_start = match.start(1)  # position of { or [
                json_str = _extract_balanced_json(content, json_start)
                if not json_str or len(json_str) < 50:
                    continue
                try:
                    data = json.loads(json_str)
                    found = _find_faq_in_json(data)
                    if found:
                        all_entries.extend(found)
                        logger.debug(
                            "JS stores: window assignment at offset %d yielded %d entries",
                            match.start(), len(found),
                        )
                except (json.JSONDecodeError, ValueError, TypeError):
                    pass

            if all_entries:
                break  # found something — stop scanning further script tags

    return _deduplicate(all_entries)


def _find_faq_in_json(obj: Any, depth: int = 0) -> list[FaqEntry]:
    """Recursively walk a JSON structure looking for FAQ Q&A arrays at any depth.

    When an array is identified as a FAQ array it is extracted in full and the
    walker does not recurse into its items (avoids double-counting).
    Non-FAQ arrays are recursed into item-by-item.
    """
    if depth > 15:
        return []

    results: list[FaqEntry] = []

    if isinstance(obj, list) and obj:
        extracted = _try_extract_faq_array(obj)
        if extracted:
            # This array IS a FAQ set — take it and stop recursing into it
            results.extend(extracted)
        else:
            # Not a FAQ array — recurse into each element
            for item in obj[:200]:  # cap to prevent explosion on huge datasets
                results.extend(_find_faq_in_json(item, depth + 1))

    elif isinstance(obj, dict):
        for value in obj.values():
            if isinstance(value, (dict, list)):
                results.extend(_find_faq_in_json(value, depth + 1))

    return results


def _try_extract_faq_array(items: list) -> list[FaqEntry]:
    """Attempt to interpret a list of dicts as a FAQ Q&A collection.

    Detection heuristic:
    1. All sampled items must be dicts.
    2. Identify a Q key and an A key from hard/soft sets.
    3. At least one of the two sides must use a hard key (avoids extracting
       every CMS content list with generic "title"/"description" fields).
    4. At least 50 % of the sampled items must have both keys populated.

    Returns extracted entries on success, empty list on mismatch.
    """
    if len(items) < 2:
        return []

    sample = [item for item in items[:5] if isinstance(item, dict)]
    if len(sample) < 2:
        return []

    q_key: Optional[str] = None
    a_key: Optional[str] = None
    q_is_hard = False
    a_is_hard = False

    for item in sample:
        # Build a lowercase → original-case key map for this item
        keys_lower = {k.lower(): k for k in item if isinstance(k, str)}

        if q_key is None:
            for k in _Q_KEYS_HARD:
                if k in keys_lower:
                    q_key = keys_lower[k]
                    q_is_hard = True
                    break
            if not q_key:
                for k in _Q_KEYS_SOFT:
                    if k in keys_lower:
                        q_key = keys_lower[k]
                        break

        if a_key is None:
            for k in _A_KEYS_HARD:
                if k in keys_lower:
                    a_key = keys_lower[k]
                    a_is_hard = True
                    break
            if not a_key:
                for k in _A_KEYS_SOFT:
                    if k in keys_lower:
                        a_key = keys_lower[k]
                        break

        if q_key and a_key:
            break

    # Require at least one hard key to avoid over-extraction
    if not q_key or not a_key or (not q_is_hard and not a_is_hard):
        return []

    # Verify hit-rate: ≥50 % of the first 20 items must have both keys populated
    check_sample = [item for item in items[:20] if isinstance(item, dict)]
    valid_count = sum(
        1 for item in check_sample
        if item.get(q_key) and item.get(a_key)
    )
    if valid_count < len(check_sample) * 0.5:
        return []

    entries: list[FaqEntry] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        q = str(item.get(q_key, "")).strip()
        a = str(item.get(a_key, "")).strip()
        if not q or not a or len(a) < 5:
            continue
        if q in ("null", "None", "undefined"):
            continue
        # Strip residual HTML tags from answer text
        a = re.sub(r"<[^>]+>", " ", a)
        a = re.sub(r"\s{2,}", " ", a).strip()
        entries.append(FaqEntry(question=q, answer=a, source="js_store"))

    return entries


def _extract_balanced_json(text: str, start: int) -> Optional[str]:
    """Extract a balanced JSON object ({…}) or array ([…]) from `text` at position `start`.

    Uses a character-level state machine that correctly handles:
    - Nested objects and arrays (depth counting)
    - String literals (ignores brackets inside strings)
    - Escaped characters inside strings (backslash sequences)

    Capped at 500 KB to avoid runaway extraction on minified bundles.
    """
    if start >= len(text):
        return None

    opener = text[start]
    if opener not in ("{", "["):
        return None
    closer = "}" if opener == "{" else "]"

    depth = 0
    in_string = False
    prev_backslash = False
    end = min(start + 500_000, len(text))

    for i in range(start, end):
        c = text[i]

        if prev_backslash:
            prev_backslash = False
            continue

        if c == "\\" and in_string:
            prev_backslash = True
            continue

        if c == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    return None


# ── Tier 2: HTML pattern matching ────────────────────────────────────────────

def _extract_html_patterns(html: str) -> list[FaqEntry]:
    """Extract FAQ from common HTML patterns (details/summary, accordion, etc.)."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("beautifulsoup4 not installed — skipping HTML pattern extraction")
        return []

    soup = BeautifulSoup(html, "html.parser")
    entries: list[FaqEntry] = []

    # Strategy A: <details>/<summary> elements (semantic HTML FAQ)
    for details in soup.find_all("details"):
        summary = details.find("summary")
        if not summary:
            continue
        question = summary.get_text(strip=True)
        summary.decompose()
        answer = details.get_text(separator="\n", strip=True)
        if question and answer and len(answer) > 10:
            entries.append(FaqEntry(question=question, answer=answer, source="html"))

    if entries:
        return entries

    # Strategy B: FAQ sections identified by heading + sibling structure
    for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
        heading_text = heading.get_text(strip=True)
        if not _FAQ_HEADING_RE.search(heading_text):
            continue

        parent = heading.parent
        if not parent:
            continue

        # Look for dt/dd pairs (definition lists)
        dl = parent.find("dl")
        if dl:
            dts = dl.find_all("dt")
            dds = dl.find_all("dd")
            for dt, dd in zip(dts, dds):
                q = dt.get_text(strip=True)
                a = dd.get_text(separator="\n", strip=True)
                if q and a:
                    entries.append(FaqEntry(question=q, answer=a, source="html"))
            if entries:
                return entries

        # Look for alternating h3/h4 (question) + p/div (answer) after the FAQ heading
        siblings = list(heading.find_next_siblings())
        i = 0
        while i < len(siblings) - 1:
            el = siblings[i]
            if el.name in ("h3", "h4", "h5"):
                q = el.get_text(strip=True)
                answer_parts = []
                j = i + 1
                while j < len(siblings) and siblings[j].name not in ("h1", "h2", "h3", "h4", "h5"):
                    text = siblings[j].get_text(separator="\n", strip=True)
                    if text:
                        answer_parts.append(text)
                    j += 1
                a = "\n".join(answer_parts).strip()
                if q and a and len(a) > 10:
                    entries.append(FaqEntry(question=q, answer=a, source="html"))
                i = j
            else:
                i += 1

    if entries:
        return entries

    # Strategy C: elements with FAQ-related class/id attributes
    faq_containers = soup.find_all(
        attrs={"class": _FAQ_CLASS_PATTERNS}
    ) + soup.find_all(
        attrs={"id": _FAQ_CLASS_PATTERNS}
    )

    for container in faq_containers[:20]:
        questions = container.find_all(["h3", "h4", "h5", "button", "summary"])
        for q_el in questions:
            q_text = q_el.get_text(strip=True)
            if not q_text or len(q_text) < 5:
                continue
            answer_el = q_el.find_next_sibling(["div", "p", "section"])
            if answer_el:
                a_text = answer_el.get_text(separator="\n", strip=True)
                if a_text and len(a_text) > 10:
                    entries.append(FaqEntry(question=q_text, answer=a_text, source="html"))

    return entries


# ── Tier 3: LLM extraction ──────────────────────────────────────────────────

_LLM_EXTRACTION_SYSTEM = """Tu es un extracteur de FAQ. On te donne le texte d'une page web.
Extrais UNIQUEMENT les paires question/réponse qui sont explicitement présentes dans le texte.
Ne génère RIEN. Ne devine RIEN. Si une question n'a pas de réponse claire dans le texte, ignore-la.

Retourne un JSON array:
[{"question": "...", "answer": "..."}]

Si aucune FAQ n'est trouvée, retourne: []"""

_LLM_DOC_EXTRACTION_SYSTEM = """Tu es un extracteur de FAQ. On te donne le contenu d'un document.
Extrais UNIQUEMENT les paires question/réponse qui sont explicitement présentes dans le texte.
Ne génère RIEN. Ne devine RIEN. Si tu ne trouves pas de FAQ structurées, cherche des sections
de type "Questions fréquentes", "FAQ", "Q&A", ou des formats question-réponse.

Retourne un JSON array:
[{"question": "...", "answer": "..."}]

Si aucune FAQ n'est trouvée, retourne: []"""


def _extract_with_llm(text: str) -> list[FaqEntry]:
    """Use Haiku to extract Q&A pairs from cleaned text."""
    try:
        from app.infrastructure.container import get_container
        from app.infrastructure.llm_attribution import llm_attribution
        # Background FAQ extraction — routes to ANTHROPIC_API_KEY_BACKGROUND.
        llm = get_container().llm_background

        truncated = text[:8000]

        with llm_attribution("faq_scan_url", feature="knowledge_scan"):
            response = llm.complete(
                system=_LLM_EXTRACTION_SYSTEM,
                user=f"Texte de la page web:\n\n{truncated}",
                max_tokens=4096,
                temperature=0.0,
            )

        return _parse_llm_faq_response(response.content, source="llm")
    except Exception as e:
        logger.warning("FAQ scanner LLM extraction failed: %s", e)
        return []


def _parse_llm_faq_response(content: str, source: str = "llm") -> list[FaqEntry]:
    """Parse the LLM JSON response into a FaqEntry list.

    Handles both JSON arrays (the expected format) and dict-wrapped results.
    Uses direct json.loads() first because extract_json_from_response only
    handles Dict[str, Any] and would silently discard top-level arrays.
    """
    result = None
    cleaned = content.strip()

    # Strip markdown code fences if present
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()

    try:
        result = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        try:
            from app.utils.json_parser import extract_json_from_response
            result = extract_json_from_response(content, default={}, error_context="FaqScanner")
        except Exception:
            pass

    if result is None:
        return []

    entries = []
    items = (
        result if isinstance(result, list)
        else result.get("faq", []) if isinstance(result, dict)
        else []
    )

    for item in items:
        if not isinstance(item, dict):
            continue
        q = (item.get("question") or "").strip()
        a = (item.get("answer") or "").strip()
        if q and a and len(a) > 5:
            entries.append(FaqEntry(question=q, answer=a, source=source))

    return entries


# ── Tab detection ─────────────────────────────────────────────────────────────

def _detect_hidden_tabs(html: str) -> list[str]:
    """Detect tab names whose content is hidden / JS-rendered and couldn't be read.

    Uses WAI-ARIA attributes (role="tab", aria-selected) and common tablist
    patterns to identify inactive tabs. Returns up to 10 tab label strings.
    """
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
    except ImportError:
        return []

    hidden_names: list[str] = []

    # Strategy 1: WAI-ARIA role="tab" elements with aria-selected="false"
    tabs_with_role = soup.find_all(attrs={"role": "tab"})
    if tabs_with_role:
        for tab in tabs_with_role:
            if tab.get("aria-selected") == "false":
                name = tab.get_text(strip=True)
                if name and len(name) < 100:
                    hidden_names.append(name)
        if hidden_names:
            return list(dict.fromkeys(hidden_names))[:10]

    # Strategy 2: role="tablist" container — first child assumed active, rest hidden
    for tablist in soup.find_all(attrs={"role": "tablist"}):
        children = tablist.find_all(["button", "a", "li"], recursive=False)
        if not children:
            children = tablist.find_all(["button", "a", "li"])
        for i, tab in enumerate(children):
            if i == 0:
                continue  # first tab is typically the active/visible one
            name = tab.get_text(strip=True)
            if name and len(name) < 100:
                hidden_names.append(name)
        if hidden_names:
            return list(dict.fromkeys(hidden_names))[:10]

    return []


# ── Deduplication ─────────────────────────────────────────────────────────────

def _deduplicate(entries: list[FaqEntry]) -> list[FaqEntry]:
    """Remove duplicate FAQ entries based on normalized question text.

    Keeps the first occurrence. Normalization: lowercase, punctuation stripped,
    first 80 characters (catches near-identical questions across tiers).
    """
    seen: set[str] = set()
    unique: list[FaqEntry] = []
    for entry in entries:
        normalized = re.sub(r"[^\w\s]", "", entry.question.lower()).strip()[:80]
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(entry)
    return unique


# ── HTML cleaning ────────────────────────────────────────────────────────────

_STRIP_TAGS = {"script", "style", "nav", "footer", "header", "aside", "noscript", "iframe"}


def _clean_html_to_text(html: str) -> str:
    """Convert HTML to clean text, stripping navigation, scripts, etc."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        for tag_name in _STRIP_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    except ImportError:
        text = re.sub(
            r"<(script|style|nav|footer|header|aside)[^>]*>.*?</\1>",
            "", html, flags=re.DOTALL | re.IGNORECASE,
        )
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()


# ── Document scanning ────────────────────────────────────────────────────────

_SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".docx", ".doc", ".md"}
_MAX_DOC_SIZE = 10_000_000  # 10 MB


def scan_document(file_bytes: bytes, filename: str) -> ScanResult:
    """Extract FAQ from an uploaded document.

    Supported formats: PDF, TXT, DOCX, MD.
    """
    ext = _get_extension(filename).lower()

    if ext not in _SUPPORTED_EXTENSIONS:
        return ScanResult(
            error=f"Format non supporté ({ext}). Formats acceptés : PDF, TXT, DOCX.",
            filename=filename,
        )

    if len(file_bytes) > _MAX_DOC_SIZE:
        return ScanResult(error="Fichier trop volumineux (max 10 Mo)", filename=filename)

    try:
        if ext == ".pdf":
            text = _extract_pdf_text(file_bytes)
        elif ext in (".docx", ".doc"):
            text = _extract_docx_text(file_bytes)
        elif ext in (".txt", ".md"):
            text = file_bytes.decode("utf-8", errors="replace")
        else:
            return ScanResult(error=f"Format non supporté : {ext}", filename=filename)
    except Exception as e:
        logger.warning("FAQ scanner: document extraction failed for %s: %s", filename, e)
        return ScanResult(error=f"Erreur de lecture du fichier : {e}", filename=filename)

    if not text or len(text.strip()) < 50:
        return ScanResult(error="Document vide ou trop court", filename=filename)

    entries = _extract_faq_from_document_text(text)

    if not entries:
        return ScanResult(
            error="Aucune FAQ détectée dans ce document",
            filename=filename,
            extraction_tier="document",
        )

    logger.info("FAQ scanner: extracted %d FAQ entries from document %s", len(entries), filename)
    return ScanResult(faq=entries, extraction_tier="document", filename=filename)


def _get_extension(filename: str) -> str:
    """Get the file extension, including the dot."""
    idx = filename.rfind(".")
    return filename[idx:] if idx >= 0 else ""


def _extract_pdf_text(file_bytes: bytes) -> str:
    """Extract text from a PDF file using pdfplumber."""
    import io
    try:
        import pdfplumber
    except ImportError:
        raise ImportError("pdfplumber n'est pas installé — impossible de lire les PDF")

    pages_text = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages[:50]:
            text = page.extract_text()
            if text:
                pages_text.append(text)

    return "\n\n".join(pages_text)


def _extract_docx_text(file_bytes: bytes) -> str:
    """Extract text from a DOCX file using python-docx."""
    import io
    try:
        from docx import Document
    except ImportError:
        raise ImportError("python-docx n'est pas installé — impossible de lire les DOCX")

    # SECURITY (audit 2026-05-29, CWE-409): a DOCX is a ZIP; python-docx fully
    # inflates document.xml into memory with no size cap, so a ~10MB upload can
    # decompress to GBs and OOM-kill the single web process. Reject decompression
    # bombs BEFORE parsing: cap member count, total/largest uncompressed size, and
    # compression ratio.
    import zipfile
    _MAX_TOTAL_UNCOMPRESSED = 100 * 1024 * 1024   # 100 MB
    _MAX_MEMBERS = 2000
    _MAX_RATIO = 120
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            infos = zf.infolist()
            if len(infos) > _MAX_MEMBERS:
                raise ValueError("DOCX rejected: too many archive members")
            total_uncompressed = sum(i.file_size for i in infos)
            if total_uncompressed > _MAX_TOTAL_UNCOMPRESSED:
                raise ValueError("DOCX rejected: uncompressed size exceeds limit")
            compressed = sum(i.compress_size for i in infos) or 1
            if total_uncompressed / compressed > _MAX_RATIO:
                raise ValueError("DOCX rejected: compression ratio too high (possible zip bomb)")
    except zipfile.BadZipFile:
        raise ValueError("Invalid DOCX file")

    doc = Document(io.BytesIO(file_bytes))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def _extract_faq_from_document_text(text: str) -> list[FaqEntry]:
    """Use LLM to extract FAQ from document text."""
    try:
        from app.infrastructure.container import get_container
        from app.infrastructure.llm_attribution import llm_attribution
        # Background FAQ extraction — routes to ANTHROPIC_API_KEY_BACKGROUND.
        llm = get_container().llm_background

        truncated = text[:12000]

        with llm_attribution("faq_scan_document", feature="knowledge_scan"):
            response = llm.complete(
                system=_LLM_DOC_EXTRACTION_SYSTEM,
                user=f"Contenu du document:\n\n{truncated}",
                max_tokens=4096,
                temperature=0.0,
            )

        return _parse_llm_faq_response(response.content, source="document")
    except Exception as e:
        logger.warning("FAQ scanner document LLM extraction failed: %s", e)
        return []
