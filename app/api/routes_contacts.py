# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Routes API REST pour la gestion des contacts (autocomplete, insights, relations).

Endpoints:
- GET  /api/contacts/autocomplete              — Autocomplétion des contacts
- GET  /api/contacts/insights                   — Insights agrégés par contact
- POST /api/contacts/<email>/analyze            — Analyse historique d'un contact
- GET  /api/contacts/<email>/relationship       — Relation détectée/overridée
- PUT  /api/contacts/<email>/relationship       — Override manuel de relation
- DELETE /api/contacts/<email>/relationship     — Suppression de l'override
- GET  /api/contacts/relationships/overrides    — Liste de tous les overrides
- POST /api/contacts/reconcile                  — Force réconciliation sent/received counts
"""

import asyncio
import logging
import re
import threading

from flask import request, jsonify, Response

from app.db.models.email import Email

from .utils.errors import error_response
from .routes_helpers import (
    api_bp,
    _NOREPLY_PATTERNS,
    _NOISE_DOMAINS,
    _NO_ACCOUNT_SENTINEL,
    _resolve_account_id_for_user,
    _resolve_account_id_cached,
    _get_current_account_for_user,
    _get_blocked_senders_set,
    _is_noise_recipient,
    require_owned_account_id,
    EMAIL_ID_MAX_LENGTH,
)
import app.api.routes_helpers as _rh

logger = logging.getLogger(__name__)

# Loose RFC-5322-ish check — we just want to reject obvious garbage and path
# traversal in the query param. Real validation happens at the People/Graph API.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


# =============================================================================
# CONTACT AUTOCOMPLETE ENDPOINT (must be before /contacts/<contact_email> routes)
# =============================================================================

_contacts_cache: dict = {}
_contacts_cache_lock = threading.Lock()
_CONTACTS_CACHE_TTL = 60  # secondes


def _block_cross_account_access(requested_account_id: int):
    """Reject the request if the caller is asking for someone else's data.

    Pre-fix (cf. 2026-04-25 audit H-1/H-2) the contact endpoints accepted
    `?account_id=N` verbatim, so any authenticated caller could enumerate
    other tenants' contacts and relationship overrides by changing the
    query parameter. We now compare against the JWT-resolved account id
    and 403 on mismatch.

    Returns a Flask response on rejection, or None on success. The local
    Tauri loopback path is trusted by design (single-user install — no
    one to impersonate) and lets the explicit id through.

    Audit F-02 (2026-05-16): the prior guard ``if caller_aid > 0`` short-
    circuited the whole check whenever the resolver returned 0 (defensive
    except fallback) OR -1 (``_NO_ACCOUNT_SENTINEL``, JWT user with no
    DB account yet — the pre-OAuth onboarding state on cloud). In
    multi-tenant cloud, every freshly signed-up user could thus enumerate
    any tenant's contact insights / relationship overrides on the 5
    endpoints that call this helper. Differentiate "pre-OAuth on cloud"
    (reject) from "Tauri loopback" (trust) via ``_is_loopback``.
    """
    try:
        caller_aid = _resolve_account_id_for_user()
    except Exception:
        caller_aid = _NO_ACCOUNT_SENTINEL

    if caller_aid > 0:
        if requested_account_id != caller_aid:
            logger.warning(
                "Blocked cross-account access: caller=%s, requested=%s",
                caller_aid, requested_account_id,
            )
            return jsonify({"error": "Forbidden: account_id does not match caller"}), 403
        return None

    # No resolvable caller identity. Allow only if request originates
    # from loopback (Tauri desktop, trusted single-user install).
    try:
        from app.api.auth import is_trusted_loopback
        if is_trusted_loopback():
            return None
    except Exception:
        pass

    logger.warning(
        "Blocked cross-account access: caller has no resolvable identity "
        "(caller_aid=%s, requested=%s, remote=%s)",
        caller_aid, requested_account_id, request.remote_addr,
    )
    return jsonify({"error": "Forbidden: caller has no resolved account"}), 403


def _merge_style_contacts(contacts_map, contact_profiles, query, *, own_email="", blocked_set=None):
    """Fold per-contact writing-style profiles into the autocomplete pool.

    ``contact_profiles`` is ``WritingStyleProfile.contact_profiles`` — the
    runtime source of truth for per-contact styles (a ``{email_lower: dict}``
    map; see ``app/domain/ports/contact_style_store_port.py`` for why the SQLite
    store is still deferred). A contact the user has given a personal writing
    voice is, by definition, someone they write to, so they must be suggestable
    in compose even when no sent email is indexed yet — a freshly-defined style,
    or a SENT-folder sync gap. Bug 2026-05-31: ``karine.morel@gmail.com`` had
    a style profile but no synced sent email, so she never appeared in the To:
    autocomplete.

    On a typed ``query`` a profile matches by address or nickname (like a
    mail-derived row); on empty focus (``query`` blank) only contacts with a
    curated voice — nickname, greeting or closing — are folded in, so the empty
    dropdown mirrors Settings → Style instead of flooding with bare profiles.

    Mutates and returns ``contacts_map`` (``{email: {email, name, freq, sent}}``).
    A style-only contact is inserted with ``sent=True`` (so it clears the
    sent_only filter), plus ``style_only`` and a ``signal`` richness count so the
    empty-focus sort ranks real emailed contacts first, then richest styles, then
    A–Z. A contact already surfaced from mail
    history keeps its real frequency and only borrows the style's nickname when
    the mail row had no name. Pure (no I/O) so it unit-tests directly.
    """
    blocked_set = blocked_set or set()
    own_email = (own_email or "").strip().lower()
    q = (query or "").lower().strip()
    if not contact_profiles:
        return contacts_map
    for key, data in contact_profiles.items():
        email = (key or "").strip().lower()
        if not email and isinstance(data, dict):
            email = (data.get("email") or "").strip().lower()
        if not email or "@" not in email:
            continue
        nickname = (data.get("nickname") or "").strip() if isinstance(data, dict) else ""
        greeting = (data.get("preferred_greeting") or "").strip() if isinstance(data, dict) else ""
        closing = (data.get("preferred_closing") or "").strip() if isinstance(data, dict) else ""
        if q:
            # Typed query: match the same way mail-derived rows do — address OR name.
            if q not in email and q not in nickname.lower():
                continue
        else:
            # Empty focus (To: clicked, nothing typed): surface only contacts with
            # a curated voice — nickname, greeting or closing — i.e. the set shown
            # under Settings → Style. Keeps style-only contacts suggestable with
            # zero keystrokes (bug 2026-06-01) without flooding the dropdown with
            # bare auto-derived formality-only profiles.
            if not (nickname or greeting or closing):
                continue
        if own_email and email == own_email:
            continue
        if email in blocked_set:
            continue
        if email in contacts_map:
            if nickname and not contacts_map[email].get("name"):
                contacts_map[email]["name"] = nickname
            continue
        contacts_map[email] = {
            "email": email,
            "name": nickname,
            "freq": 1,
            "sent": True,  # user-curated → treat as a deliberate sent contact
            "style_only": True,
            # Curation richness drives the empty-focus ordering (richest first).
            "signal": (1 if nickname else 0) + (1 if greeting else 0) + (1 if closing else 0),
        }
    return contacts_map


@api_bp.route("/contacts/autocomplete", methods=["GET"])
def autocomplete_contacts():
    """
    Recherche de contacts pour l'autocomplétion.

    Extrait les contacts directement de la table emails (senders + recipients)
    triés par fréquence d'interaction.

    Query Parameters:
        q (str): Terme de recherche (optionnel, retourne top 10 si vide).
    """
    import time as _ct_time
    from sqlalchemy import func

    query = request.args.get("q", "").strip()
    sent_only_param = request.args.get("sent_only", "").strip().lower() in ("1", "true", "yes")
    # include_self_param: when true, do NOT strip the user's multi-account
    # emails from the result set. Use case: search filters (From/To/CC in
    # SmartSearchBar) where matching emails from the user's other accounts
    # is a valid, expected outcome — without this, typing one's own name
    # returns "no contact found" because every match gets stripped.
    # Compose recipients still default to false: we don't want to suggest
    # "send to yourself" as a primary completion.
    include_self_param = request.args.get("include_self", "").strip().lower() in ("1", "true", "yes")

    # Résoudre l'account : utiliser le paramètre explicit s'il est fourni,
    # sinon fallback sur la résolution interne (JWT / get_current_account).
    #
    # H-1 fix (2026-04-25): if the explicit param is set we still check it
    # belongs to the JWT caller — pre-fix any user could enumerate other
    # tenants' contacts by changing ?account_id=.
    #
    # 2026-05-12 fix: the frontend's compose modal sends `account_id=<hash>`
    # (from `/api/accounts` which returns hash IDs), while the old code did
    # `request.args.get("account_id", type=int)` and silently coerced the
    # hash to None, falling through to JWT resolution. In multi-account
    # setups where JWT-resolved account != UI-active account, contacts came
    # from the wrong account → "No contact found" with no signal to the
    # operator. Switch to `require_owned_account_id` which already handles
    # int + hash + ownership uniformly (see reference_account_id_dual_format
    # memory). Imported at module level so test patches can target the
    # `app.api.routes_contacts.require_owned_account_id` symbol.
    explicit_raw = (request.args.get("account_id") or "").strip()
    if explicit_raw:
        resolved = require_owned_account_id(explicit_raw)
        if resolved == _NO_ACCOUNT_SENTINEL:
            logger.warning(
                "contacts autocomplete: unowned/unresolvable account_id=%r",
                explicit_raw,
            )
            return jsonify({
                "error": "Forbidden: account_id does not resolve to an owned account",
            }), 403
        account_id = resolved
    else:
        try:
            account_id = _resolve_account_id_for_user()
        except Exception:
            account_id = 0

    # Optional limit (default 10, clamped to [1, 50])
    try:
        _limit = int(request.args.get("limit", "10"))
    except ValueError:
        _limit = 10
    _limit = max(1, min(_limit, 50))

    # Cache check (sent_only + include_self + limit are part of key —
    # different filter modes produce different result sets).
    _ct_key = (account_id, query.lower(), sent_only_param, include_self_param, _limit)
    with _contacts_cache_lock:
        _ct_entry = _contacts_cache.get(_ct_key)
        if _ct_entry and (_ct_time.time() - _ct_entry["ts"]) < _CONTACTS_CACHE_TTL:
            return jsonify(_ct_entry["data"]), 200

    # Get current account email(s) to exclude from results — never suggest the
    # user to themselves. own_account_emails covers ALL of the user's linked
    # accounts so a profiled own-address can't leak via the sent_only style merge,
    # which skips the multi-account self-strip further down (own_email alone is
    # derived from a different account-id resolution than the style merge uses).
    own_email = ""
    own_account_emails: set[str] = set()
    try:
        from app.multi_accounts import get_account_manager
        mgr = get_account_manager()
        acct = mgr.get_account(account_id) if account_id else _get_current_account_for_user()
        if acct:
            own_email = acct.email.strip().lower()
        try:
            own_account_emails = {
                (a.email or "").strip().lower()
                for a in mgr.get_all_accounts() if getattr(a, "email", None)
            }
        except Exception:
            pass
    except Exception:
        pass

    try:
        with _rh.get_db_session() as session:
            # Exclude spam/trash folders and automated/noise addresses
            excluded_folders = [
                "spam", "trash", "junk", "[Gmail]/Spam", "[Gmail]/Trash",
                "Junk", "Deleted Items", "deleteditems", "junkemail",
            ]

            _contact_account_id = account_id or _resolve_account_id_cached()

            # Merge results
            contacts_map: dict[str, dict] = {}
            # Name lookup map populated from sender_name — used to enrich sent_only results
            # (recipients column has no names, only emails)
            sender_name_lookup: dict[str, str] = {}

            # Query senders (people who emailed us)
            # In sent_only mode: still query to build name lookup, but don't add contacts from senders
            senders_q = session.query(
                Email.sender,
                Email.sender_name,
                func.count(Email.id).label("freq"),
            )
            senders_q = senders_q.filter(Email.sender.isnot(None))
            senders_q = senders_q.filter(Email.account_id == _contact_account_id)
            senders_q = senders_q.filter(
                (Email.folder.is_(None)) | (~Email.folder.in_(excluded_folders))
            )
            if query:
                like_pattern = f"%{query}%"
                senders_q = senders_q.filter(
                    (Email.sender.ilike(like_pattern))
                    | (Email.sender_name.ilike(like_pattern))
                )
            senders_q = senders_q.group_by(Email.sender, Email.sender_name)
            senders_rows = senders_q.all()

            # In sent_only mode, populate the name lookup for recipient
            # enrichment (recipients column has no names). Senders are still
            # added to ``contacts_map`` below with ``sent=False`` so they're
            # available as a soft-fallback when the sent-only filter at the
            # end empties the result set (see comment on the ``sent_filtered``
            # fallback further down — 2026-05-12 fix). Pre-fix this branch
            # also did ``senders_rows = []`` to hard-strip senders, which is
            # what caused "No contact found" in compose any time the user's
            # SENT folder backfill was incomplete.
            if sent_only_param:
                for row in senders_rows:
                    email_addr = (row.sender or "").strip().lower()
                    if email_addr and row.sender_name:
                        sender_name_lookup.setdefault(email_addr, row.sender_name)

            for row in senders_rows:
                email_addr = (row.sender or "").strip().lower()
                if not email_addr or "@" not in email_addr:
                    continue
                # Skip automated/noise addresses
                if any(email_addr.startswith(p) for p in _NOREPLY_PATTERNS):
                    continue
                local_part = email_addr.split("@", 1)[0]
                # Also catch "noreply"/"no-reply" anywhere in local part
                if "noreply" in local_part or "no-reply" in local_part or "donotreply" in local_part:
                    continue
                domain = email_addr.split("@", 1)[1] if "@" in email_addr else ""
                if any(domain == nd or domain.endswith("." + nd) for nd in _NOISE_DOMAINS):
                    continue
                if email_addr not in contacts_map:
                    contacts_map[email_addr] = {
                        "email": email_addr,
                        "name": row.sender_name or "",
                        "freq": row.freq,
                        "sent": False,
                    }
                else:
                    contacts_map[email_addr]["freq"] += row.freq
                    if row.sender_name and not contacts_map[email_addr]["name"]:
                        contacts_map[email_addr]["name"] = row.sender_name

            # Query recipients (people we sent to) - parse comma-separated field
            recip_q = session.query(
                Email.recipients,
                func.count(Email.id).label("freq"),
            ).filter(
                Email.recipients.isnot(None),
                Email.is_sent.is_(True),
                Email.account_id == (account_id or _resolve_account_id_cached()),
                (Email.folder.is_(None)) | (~Email.folder.in_(excluded_folders)),
            )
            if query:
                recip_q = recip_q.filter(Email.recipients.ilike(f"%{query}%"))
            recip_q = recip_q.group_by(Email.recipients)

            for row in recip_q.all():
                if not row.recipients:
                    continue
                for addr in row.recipients.split(","):
                    addr = addr.strip().lower()
                    if not addr or "@" not in addr:
                        continue
                    if any(addr.startswith(p) for p in _NOREPLY_PATTERNS):
                        continue
                    addr_local = addr.split("@", 1)[0]
                    # Catch noreply/no-reply/donotreply/*-noreply anywhere in local part
                    if ("noreply" in addr_local or "no-reply" in addr_local
                            or "donotreply" in addr_local or "do-not-reply" in addr_local):
                        continue
                    addr_domain = addr.split("@", 1)[1] if "@" in addr else ""
                    if any(addr_domain == nd or addr_domain.endswith("." + nd) for nd in _NOISE_DOMAINS):
                        continue
                    # Skip obvious automated/transactional addresses (invoice+, billing+, etc)
                    if addr_local.startswith(("invoice", "billing", "receipt", "statement", "notification")):
                        continue
                    if query and query.lower() not in addr:
                        continue
                    if addr not in contacts_map:
                        contacts_map[addr] = {
                            "email": addr,
                            "name": sender_name_lookup.get(addr, ""),
                            "freq": row.freq,
                            "sent": True,
                        }
                    else:
                        contacts_map[addr]["freq"] += row.freq
                        contacts_map[addr]["sent"] = True
                        if not contacts_map[addr]["name"] and addr in sender_name_lookup:
                            contacts_map[addr]["name"] = sender_name_lookup[addr]

        # Remove blocked senders from autocomplete
        blocked_set = _get_blocked_senders_set()
        if blocked_set:
            contacts_map = {k: v for k, v in contacts_map.items() if k not in blocked_set}

        # Always strip the active account's own email — typing your own
        # address as a recipient or filter target is rarely the intent
        # and always available as a manual chip.
        if own_email:
            contacts_map.pop(own_email, None)
        # Strip OTHER multi-account emails by default (avoid self-references
        # in compose dropdowns). Skip the strip when include_self=true so
        # search filters can surface "emails from my other account" results.
        # NB: cross-tenant leak is impossible regardless of this flag because
        # the SQL queries above already filter by Email.account_id.
        if not sent_only_param and not include_self_param:
            try:
                for a in mgr.get_all_accounts():
                    contacts_map.pop(a.email.strip().lower(), None)
            except Exception:
                pass
        # Remove contacts named "Moi" / "Me" (Gmail self-references)
        contacts_map = {
            k: v for k, v in contacts_map.items()
            if v.get("name", "").strip().lower() not in ("moi", "me")
        }

        # No query → only show contacts the user has actually sent to
        # (avoids filling the initial dropdown with commercial/automated senders)
        if not query:
            sent_only = {k: v for k, v in contacts_map.items() if v.get("sent")}
            if sent_only:
                contacts_map = sent_only

        # Explicit sent_only mode — prefer sent contacts, but soft-fallback to
        # the unfiltered set when the sent_only filter would empty the dropdown.
        #
        # Why the fallback : "no contact found" on the compose To field used
        # to fire under several documented conditions that are NOT user-fault :
        #   - Gmail SENT folder historyId delta gap → some sent emails never
        #     get `is_sent=True` (see tasks/lessons.md → Sync).
        #   - Multi-account setups where the active account has inbox-only
        #     data while the user's sent-from history lives on another linked
        #     account.
        #   - New account where sent-folder backfill hasn't completed yet.
        # In all three the spam-suppression filters above (noreply / noise /
        # blocked-senders / multi-account-self) still hold, so the fallback
        # expands from "sent recipients" to "all known contacts matching q",
        # not to "all senders including spam". The dropdown stays useful.
        if sent_only_param:
            sent_filtered = {k: v for k, v in contacts_map.items() if v.get("sent")}
            if sent_filtered:
                contacts_map = sent_filtered
            # else: keep contacts_map unfiltered (soft fallback)

        # Merge per-contact writing-style profiles AFTER the sent_only filter so
        # a style-only contact (no mail history) survives it. A contact you've
        # given a personal writing voice is unambiguously someone you write to,
        # so they must always be suggestable in compose (bug 2026-05-31:
        # karine.morel@gmail.com had a style but no synced sent email, so she
        # never appeared in the To: dropdown). Runs on empty focus too — bug
        # 2026-06-01: a user with several per-contact styles but only two indexed
        # sent recipients saw just those two on focus. On empty focus
        # _merge_style_contacts folds in only curated-voice contacts (the
        # Settings → Style set); the final [:_limit] slice still bounds the list.
        # Best-effort so a style-store hiccup never breaks autocomplete.
        #
        # Cross-account (bug 2026-06-24): per-contact styles are stored PER
        # ACCOUNT, but a recipient the user has given a personal voice to is
        # "their contact" no matter which of the user's OWN accounts they
        # compose from. Merge style contacts from every account owned by the
        # same user, so a contact styled under account A stays suggestable when
        # composing from account B (karine.morel@gmail.com was styled under
        # several accounts but invisible in New Message because the *compose*
        # account's own store didn't list her). Tenancy-safe: the sibling set is
        # restricted to the resolved account's user_id — and for loopback/Tauri,
        # where accounts carry user_id NULL, to the other NULL-user accounts
        # (i.e. the single local user's accounts).
        if isinstance(_contact_account_id, int) and _contact_account_id > 0:
            try:
                from app.db.models.account import Account
                _owner_uid = (
                    session.query(Account.user_id)
                    .filter(Account.id == _contact_account_id)
                    .scalar()
                )
                if _owner_uid is not None:
                    _sib_q = session.query(Account.id).filter(
                        Account.user_id == _owner_uid
                    )
                else:
                    _sib_q = session.query(Account.id).filter(
                        Account.user_id.is_(None)
                    )
                _sibling_ids = {int(r[0]) for r in _sib_q.all()}
            except Exception as e:
                logger.debug("contact-style sibling lookup failed: %s", e)
                _sibling_ids = set()
            _sibling_ids.add(_contact_account_id)

            _style_blocked = (blocked_set or set()) | own_account_emails
            try:
                _store = _rh._get_container().get_writing_style_store()
            except Exception as e:
                logger.debug("writing-style store unavailable: %s", e)
                _store = None
            if _store is not None:
                for _sid in _sibling_ids:
                    try:
                        _profile = _store.load(_sid)
                        _cp = getattr(_profile, "contact_profiles", None) if _profile else None
                        if _cp:
                            _merge_style_contacts(
                                contacts_map, _cp, query,
                                own_email=own_email,
                                blocked_set=_style_blocked,
                            )
                    except Exception as e:
                        logger.debug(
                            "contact-style merge skipped for account %s: %s", _sid, e
                        )

        if not query:
            # Empty focus: a curated, bounded "your people" list. Order:
            #   1. contacts you've actually emailed (real sent recipients), by freq
            #   2. then your most-curated style contacts (richest signal first)
            #   3. then alphabetical — so the list is deterministic and predictable.
            # Type to reach anyone beyond the cap.
            def _empty_focus_key(c):
                emailed = bool(c.get("sent") and not c.get("style_only"))
                return (
                    0 if emailed else 1,
                    -(c.get("freq", 0)) if emailed else -(c.get("signal", 0)),
                    (c.get("name") or c.get("email") or "").lower(),
                )
            results = sorted(contacts_map.values(), key=_empty_focus_key)[: max(_limit, 12)]
        else:
            # Typed query: sent contacts first (5x boost), then frequency.
            results = sorted(
                contacts_map.values(),
                key=lambda c: c["freq"] * (5 if c.get("sent") else 1),
                reverse=True,
            )[:_limit]

        contacts_result = [{"name": c["name"], "email": c["email"]} for c in results]
        with _contacts_cache_lock:
            _contacts_cache[_ct_key] = {"data": contacts_result, "ts": _ct_time.time()}
        return jsonify(contacts_result), 200

    except Exception as e:
        logger.error(f"Contact autocomplete error: {e}")
        return jsonify({"error": "Failed to search contacts"}), 500


# =============================================================================
# HIDE CONTACT FROM AUTOCOMPLETE
# =============================================================================


@api_bp.route("/contacts/hide", methods=["POST"])
def hide_contact():
    """
    Masque un contact de l'autocomplétion en l'ajoutant aux expéditeurs bloqués.

    Request Body:
        email (str): L'adresse email à masquer.

    Returns:
        JSON avec succès et la liste mise à jour.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    email_to_hide = data.get("email", "").strip().lower()
    if not email_to_hide:
        return jsonify({"error": "email is required"}), 400

    try:
        current_account = _get_current_account_for_user()
        if not current_account:
            return jsonify({"error": "No active account"}), 400

        from app.multi_accounts import get_account_manager
        manager = get_account_manager()

        blocked = current_account.blocked_senders or []
        if email_to_hide not in [s.lower() for s in blocked]:
            blocked.append(email_to_hide)

        manager.update_account(current_account.id, blocked_senders=blocked)

        # Invalidate contacts autocomplete cache
        with _contacts_cache_lock:
            _contacts_cache.clear()

        logger.info(f"Contact masqué de l'autocomplétion : {email_to_hide}")
        return jsonify({"success": True, "email": email_to_hide})

    except Exception as e:
        logger.error(f"Erreur lors du masquage du contact {email_to_hide}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@api_bp.route("/contacts/unhide", methods=["POST"])
def unhide_contact():
    """
    Restaure un contact masqué (le retire des expéditeurs bloqués).

    Request Body:
        email (str): L'adresse email à restaurer.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    email_to_unhide = data.get("email", "").strip().lower()
    if not email_to_unhide:
        return jsonify({"error": "email is required"}), 400

    try:
        current_account = _get_current_account_for_user()
        if not current_account:
            return jsonify({"error": "No active account"}), 400

        from app.multi_accounts import get_account_manager
        manager = get_account_manager()

        blocked = current_account.blocked_senders or []
        blocked = [s for s in blocked if s.lower() != email_to_unhide]

        manager.update_account(current_account.id, blocked_senders=blocked)

        # Invalidate contacts autocomplete cache
        with _contacts_cache_lock:
            _contacts_cache.clear()

        logger.info(f"Contact restauré dans l'autocomplétion : {email_to_unhide}")
        return jsonify({"success": True, "email": email_to_unhide})

    except Exception as e:
        logger.error(f"Erreur lors de la restauration du contact {email_to_unhide}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# CONTACT ANALYSIS ENDPOINT
# =============================================================================

# Email validation pattern for contact analysis
CONTACT_EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def _validate_contact_email(email: str) -> bool:
    """Validate contact email format."""
    if not email or len(email) > EMAIL_ID_MAX_LENGTH:
        return False
    return bool(CONTACT_EMAIL_PATTERN.match(email))


@api_bp.route("/contacts/insights", methods=["GET"])
def contacts_insights():
    """
    Insights agrégés par contact : volume, longueur moyenne, ratio édition, CC fréquents.

    Query Parameters:
        limit (int): Nombre max de contacts (défaut 20).
        days (int): Période en jours (défaut 60).
    """
    from app.draft_quality_tracker import get_tracker
    from app.api.routes_helpers import _resolve_account_id_cached

    limit = request.args.get("limit", 20, type=int)
    days = request.args.get("days", 60, type=int)
    _account_id = _resolve_account_id_cached()
    # Audit F-05 (2026-05-16): the previous ternary degraded to
    # `tracker_account_id = None` when the resolver returned
    # _NO_ACCOUNT_SENTINEL (-1) or any non-positive value. That hit the
    # tracker's unscoped read branch and returned top contacts across
    # ALL tenants combined — same cross-tenant surface as F-02, but
    # triggered by stale-JWT or deleted-account-row mis-state. Hard
    # 401 instead.
    if not isinstance(_account_id, int) or _account_id <= 0:
        return jsonify({"error": "Authentication required"}), 401
    tracker_account_id = str(_account_id)

    try:
        tracker = get_tracker()
        top_contacts = tracker.get_top_contacts(limit=limit, days=days, account_id=tracker_account_id)

        results = []
        for c in top_contacts:
            contact_email_addr = c["contact"]
            # Audit F-02 (2026-05-16): plumb tracker_account_id into the
            # three per-contact readers. Pre-fix they queried
            # `WHERE contact = ?` only and aggregated rows from every
            # tenant on shared-SQLite installs (avg reply length, edit
            # ratio, and the cc_added column which contains real email
            # addresses of co-recipients).
            avg_length = tracker.get_contact_avg_length(
                contact_email_addr, days=days, account_id=tracker_account_id
            )
            edit_stats = tracker.get_contact_edit_stats(
                contact_email_addr, days=days, account_id=tracker_account_id
            )
            cc_patterns = tracker.get_contact_cc_patterns(
                contact_email_addr, days=days, account_id=tracker_account_id
            )

            results.append({
                "contact": contact_email_addr,
                "total_sends": c["total"],
                "unmodified": c["unmodified"],
                "avg_edit_ratio": edit_stats["avg_edit_ratio"] if edit_stats else c["avg_edit_ratio"],
                "avg_length": avg_length,
                "cc_patterns": cc_patterns,
            })

        return jsonify({"contacts": results}), 200
    except Exception as e:
        logger.error(f"[ERROR] contacts_insights: {e}")
        return jsonify({"error": str(e)}), 500


def _extract_addr(raw: str | None) -> str:
    """Normalise « Name <email> » ou « EMAIL » → adresse minuscule, ou "".

    Même extraction que ``ContactRepository.recompute_counts_from_emails`` :
    on déplie un éventuel chevron, on minuscule, et on rejette tout ce qui
    n'a pas d'arobase.
    """
    if not raw:
        return ""
    addr = raw.strip().lower()
    if "<" in addr and ">" in addr:
        addr = addr.split("<", 1)[1].split(">", 1)[0].strip()
    if "@" not in addr:
        return ""
    return addr


# Minimum number of emails the user must have SENT to a contact for them to be
# offered as a VIP. The single biggest precision lever (diag 2026-05-26): a
# *single* reply to a SaaS/transactional sender (G2 / Notion / Vast.ai onboarding
# mails…) made it look like a relationship, while a real contact the user had
# emailed 12× but whose replies weren't synced was dropped entirely. Requiring
# ≥2 keeps the people you deliberately, repeatedly write to and drops one-offs.
_MIN_SENT_FOR_VIP = 2
_MIN_RECEIVED_FOR_VIP = 1


def _aggregate_top_contacts(
    received_rows,   # itérable de (sender, sender_name, freq)
    sent_rows,       # itérable de (recipients_csv, cc_csv)
    *,
    exclude_emails: set[str],
    limit: int,
) -> list[dict]:
    """Top contacts à proposer en VIP (onboarding Step 4), classés par volume ENVOYÉ.

    Inclusion : ``received_count >= _MIN_RECEIVED_FOR_VIP`` ET
    ``sent_count >= _MIN_SENT_FOR_VIP``, moins ``exclude_emails`` (compte
    courant + VIP existants + expéditeurs masqués) et ``_is_noise_recipient``
    (noreply/automatisés/bruit connu).

    Fonction pure (aucune I/O) pour être testable directement.
    """
    received: dict[str, int] = {}
    names: dict[str, str] = {}
    for row in received_rows:
        addr = _extract_addr(row[0])
        if not addr:
            continue
        received[addr] = received.get(addr, 0) + int(row[2] or 0)
        sender_name = row[1]
        if sender_name and not names.get(addr):
            names[addr] = sender_name.strip()

    sent: dict[str, int] = {}
    for row in sent_rows:
        # Compter chaque adresse au plus une fois par email envoyé (un même
        # destinataire en To+Cc ne doit pas gonfler son score deux fois) —
        # aligne la sémantique sur recompute_counts_from_emails.
        seen: set[str] = set()
        for csv in (row[0] or "", row[1] or ""):
            for part in csv.split(","):
                addr = _extract_addr(part)
                if not addr or addr in seen:
                    continue
                seen.add(addr)
                sent[addr] = sent.get(addr, 0) + 1
                # Récupère un nom d'affichage depuis « Nom <addr> » côté
                # destinataires quand la face entrante n'en a pas fourni.
                if "<" in part and not names.get(addr):
                    nm = part.split("<", 1)[0].strip().strip('"').strip()
                    if nm:
                        names[addr] = nm

    out: list[dict] = []
    for addr, sc in sent.items():
        if sc < _MIN_SENT_FOR_VIP:        # pas assez d'échanges délibérés
            continue
        if received.get(addr, 0) < _MIN_RECEIVED_FOR_VIP:
            continue
        if addr in exclude_emails:
            continue
        if _is_noise_recipient(addr):
            continue
        out.append({
            "email": addr,
            "name": names.get(addr, ""),
            "sent_count": sc,
            "received_count": received.get(addr, 0),
        })

    # Classement : écrire À quelqu'un est le signal le plus fort, donc sent_count
    # décroissant d'abord, puis received_count (booste les vrais aller-retours),
    # puis email pour un ordre stable et déterministe (tests + UI sans
    # scintillement).
    out.sort(key=lambda c: (
        -c["sent_count"],
        -c["received_count"],
        c["email"],
    ))
    return out[:limit]


@api_bp.route("/contacts/suggested-vip", methods=["GET"])
def suggested_vip_contacts():
    """Contacts « légitimes » proposés en VIP (onboarding Step 4).

    Lit directement la table Email (et non la table Contact) : pendant
    l'onboarding la réconciliation ``recompute_counts_from_emails`` peut ne pas
    avoir encore tourné, mais les emails déjà synchronisés suffisent à détecter
    les vrais correspondants. Renvoie ``[]`` (jamais une erreur) si le scan
    n'a encore rien produit — le front retombe alors sur la saisie manuelle.

    Query params:
        limit (int): nombre max de suggestions (défaut 6, borné à [1, 50]).

    Returns:
        {"contacts": [{"name", "email", "sent_count", "received_count"}]}
    """
    from sqlalchemy import func

    limit = request.args.get("limit", 6, type=int) or 6
    limit = max(1, min(limit, 50))

    account_id = _resolve_account_id_cached()
    # Même garde que /contacts/insights (audit F-05) : un account_id non
    # résolu (-1 sentinelle pré-OAuth, ou 0 défensif) ne doit jamais retomber
    # sur une lecture non scopée qui agrégerait les contacts d'autres tenants.
    if not isinstance(account_id, int) or account_id <= 0:
        return jsonify({"error": "Authentication required"}), 401

    # Exclusions : l'email du compte courant (on ne se propose pas soi-même),
    # les contacts déjà VIP (rien à promouvoir), et les expéditeurs masqués.
    exclude_emails: set[str] = set()
    try:
        from app.multi_accounts import get_account_manager
        acct = get_account_manager().get_account(account_id)
        if acct and getattr(acct, "email", None):
            exclude_emails.add(acct.email.strip().lower())
    except Exception:
        pass
    try:
        from app.infrastructure.container import get_container
        store = get_container().get_label_store(account_id=account_id)
        for v in store.get_vip_senders():
            if v:
                exclude_emails.add(v.strip().lower())
    except Exception:
        pass
    try:
        exclude_emails |= {e.strip().lower() for e in _get_blocked_senders_set() if e}
    except Exception:
        pass

    try:
        with _rh.get_db_session() as session:
            received_rows = (
                session.query(
                    Email.sender,
                    Email.sender_name,
                    func.count(Email.id).label("freq"),
                )
                .filter(
                    Email.account_id == account_id,
                    Email.is_sent.is_(False),
                    Email.sender.isnot(None),
                )
                .group_by(Email.sender, Email.sender_name)
                .all()
            )
            sent_rows = (
                session.query(Email.recipients, Email.cc)
                .filter(
                    Email.account_id == account_id,
                    Email.is_sent.is_(True),
                )
                .all()
            )
    except Exception as e:
        # Lecture best-effort : un scan partiel / une table vide ne doit pas
        # casser l'onboarding. On renvoie [] et le front garde la saisie manuelle.
        logger.error(f"suggested_vip_contacts query failed: {e}")
        return jsonify({"contacts": []}), 200

    contacts = _aggregate_top_contacts(
        received_rows, sent_rows, exclude_emails=exclude_emails, limit=limit
    )
    return jsonify({"contacts": contacts}), 200


@api_bp.route("/contacts/<contact_email>/analyze", methods=["POST"])
def analyze_contact_history(contact_email: str):
    """
    Analyse l'historique des échanges avec un contact.

    Ce endpoint analyse les 20 derniers emails avec le contact spécifié
    et retourne le contexte relationnel (ton, sujets récurrents, etc.).

    Args:
        contact_email: Adresse email du contact à analyser.

    Query Parameters:
        account_id (int): ID du compte email de l'utilisateur (requis).
        limit (int): Nombre maximum d'emails à analyser (défaut: 20, max: 50).

    Returns:
        JSON avec le ContactContext analysé.

    Errors:
        400: Paramètres invalides.
        404: Contact non trouvé ou aucun email avec ce contact.
        500: Erreur interne.
    """
    # Validate contact_email
    if not _validate_contact_email(contact_email):
        return jsonify({"error": "Invalid contact email format"}), 400

    # Get and validate account_id
    account_id_str = request.args.get("account_id")
    if not account_id_str:
        return jsonify({"error": "account_id query parameter is required"}), 400

    # Audit F-04 (2026-05-16): accept both int (/api/init) and hex
    # (/api/accounts) account_ids. The prior `int()`-only validator
    # 400'd on hex even though the frontend AccountManager sends hex;
    # see the same migration on the autocomplete handler at
    # lines 122-138 for the canonical rationale. Ownership check is
    # built into require_owned_account_id, so the legacy
    # _block_cross_account_access wrapper is no longer needed here.
    account_id = require_owned_account_id(account_id_str)
    if account_id == _NO_ACCOUNT_SENTINEL:
        return jsonify({"error": "Forbidden: account_id does not resolve to an owned account"}), 403

    # Get and validate limit
    limit_str = request.args.get("limit", "20")
    try:
        limit = int(limit_str)
        if limit <= 0 or limit > 50:
            return jsonify({"error": "limit must be between 1 and 50"}), 400
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400

    logger.info(
        f"Analyzing contact history for {contact_email} "
        f"(account_id={account_id}, limit={limit})"
    )

    try:
        with _rh.get_db_session() as session:
            email_repository = _rh.EmailRepository(session)
            use_case = _rh._get_container().get_analyze_contact_history_use_case(
                email_repository=email_repository
            )

            # Run async use case
            loop = asyncio.new_event_loop()
            try:
                context = loop.run_until_complete(
                    use_case.execute(
                        contact_email=contact_email,
                        account_id=account_id,
                        limit=limit,
                    )
                )
            finally:
                loop.close()

            # Convert to response format
            return jsonify({
                "data": {
                    "contact_email": context.contact_email,
                    "email_count": context.email_count,
                    "dominant_tone": context.dominant_tone.value,
                    "tone_confidence": context.tone_confidence,
                    "recurring_topics": [
                        {
                            "topic": topic.topic,
                            "frequency": topic.frequency,
                        }
                        for topic in context.recurring_topics
                    ],
                    "relationship_strength": context.relationship_strength,
                    "first_interaction": (
                        context.first_interaction.isoformat()
                        if context.first_interaction
                        else None
                    ),
                    "last_interaction": (
                        context.last_interaction.isoformat()
                        if context.last_interaction
                        else None
                    ),
                    "analysis_duration_ms": context.analysis_duration_ms,
                    "is_complete": context.is_complete,
                    "analyzed_at": context.analyzed_at.isoformat(),
                }
            })

    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    except Exception as e:
        logger.error(f"Error analyzing contact {contact_email}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


# =============================================================================
# RELATIONSHIP DETECTION ENDPOINTS
# =============================================================================

def _make_relationship_service(session):
    """Instantiate RelationshipDetectionService from an existing session."""
    from app.db.repositories.relationship_repository import RelationshipRepository
    from app.services.relationship_detection_service import RelationshipDetectionService

    return RelationshipDetectionService(repository=RelationshipRepository(session))


# Valid relationship types for validation
VALID_RELATIONSHIP_TYPES = {"colleague", "client", "friend", "manager", "vendor", "unknown"}


@api_bp.route("/contacts/<contact_email>/relationship", methods=["GET"])
def get_contact_relationship(contact_email: str):
    """
    Get the relationship type for a contact.

    Returns the detected or overridden relationship type for the specified contact.
    User overrides take precedence over automatic detection.

    Args:
        contact_email: Email address of the contact.

    Query Parameters:
        account_id (int): ID of the user's account (required).

    Returns:
        JSON with relationship data.

    Example:
        GET /api/contacts/john@example.com/relationship?account_id=1
    """
    # Validate contact email
    if not _validate_contact_email(contact_email):
        return jsonify({"error": "Invalid contact email format"}), 400

    # Get and validate account_id
    account_id_str = request.args.get("account_id")
    if not account_id_str:
        return jsonify({"error": "account_id query parameter is required"}), 400

    # Audit F-04 (2026-05-16): accept both int (/api/init) and hex
    # (/api/accounts) account_ids. The prior `int()`-only validator
    # 400'd on hex even though the frontend AccountManager sends hex;
    # see the same migration on the autocomplete handler at
    # lines 122-138 for the canonical rationale. Ownership check is
    # built into require_owned_account_id, so the legacy
    # _block_cross_account_access wrapper is no longer needed here.
    account_id = require_owned_account_id(account_id_str)
    if account_id == _NO_ACCOUNT_SENTINEL:
        return jsonify({"error": "Forbidden: account_id does not resolve to an owned account"}), 403

    try:
        with _rh.get_db_session() as session:
            service = _make_relationship_service(session)
            detection = service.get_relationship(
                account_id=account_id,
                contact_email=contact_email,
            )

        return jsonify({
            "data": {
                "contact_email": detection.contact_email,
                "relationship_type": detection.relationship_type.value,
                "confidence": detection.confidence,
                "communication_frequency": detection.communication_frequency.value,
                "typical_hours": detection.typical_hours,
                "is_user_override": detection.is_user_override,
                "detected_at": detection.detected_at.isoformat(),
            }
        }), 200

    except Exception as e:
        logger.error(f"Error getting relationship for {contact_email}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/contacts/<contact_email>/relationship", methods=["PUT"])
def set_contact_relationship(contact_email: str):
    """
    Set or update the relationship type for a contact (manual override).

    This creates a user override that takes precedence over automatic detection.

    Args:
        contact_email: Email address of the contact.

    Query Parameters:
        account_id (int): ID of the user's account (required).

    Request Body:
        relationship_type (str): One of: colleague, client, friend, manager, vendor, unknown

    Returns:
        JSON with the updated relationship data.

    Example:
        PUT /api/contacts/john@example.com/relationship?account_id=1
        {"relationship_type": "client"}
    """
    # Validate contact email
    if not _validate_contact_email(contact_email):
        return jsonify({"error": "Invalid contact email format"}), 400

    # Get and validate account_id
    account_id_str = request.args.get("account_id")
    if not account_id_str:
        return jsonify({"error": "account_id query parameter is required"}), 400

    # Audit F-04 (2026-05-16): accept both int (/api/init) and hex
    # (/api/accounts) account_ids. The prior `int()`-only validator
    # 400'd on hex even though the frontend AccountManager sends hex;
    # see the same migration on the autocomplete handler at
    # lines 122-138 for the canonical rationale. Ownership check is
    # built into require_owned_account_id, so the legacy
    # _block_cross_account_access wrapper is no longer needed here.
    account_id = require_owned_account_id(account_id_str)
    if account_id == _NO_ACCOUNT_SENTINEL:
        return jsonify({"error": "Forbidden: account_id does not resolve to an owned account"}), 403

    # Get and validate request body
    data = request.get_json(silent=True) or {}
    relationship_type = data.get("relationship_type")

    if not relationship_type:
        return jsonify({"error": "relationship_type is required in request body"}), 400

    if relationship_type.lower() not in VALID_RELATIONSHIP_TYPES:
        return jsonify({
            "error": f"Invalid relationship_type. Must be one of: {', '.join(VALID_RELATIONSHIP_TYPES)}"
        }), 400

    try:
        with _rh.get_db_session() as session:
            service = _make_relationship_service(session)
            detection = service.set_relationship_override(
                account_id=account_id,
                contact_email=contact_email,
                relationship_type=relationship_type.lower(),
            )

        return jsonify({
            "data": {
                "contact_email": detection.contact_email,
                "relationship_type": detection.relationship_type.value,
                "confidence": detection.confidence,
                "communication_frequency": detection.communication_frequency.value,
                "typical_hours": detection.typical_hours,
                "is_user_override": detection.is_user_override,
                "detected_at": detection.detected_at.isoformat(),
            }
        }), 200

    except Exception as e:
        logger.error(f"Error setting relationship for {contact_email}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/contacts/<contact_email>/relationship", methods=["DELETE"])
def delete_contact_relationship(contact_email: str):
    """
    Delete a relationship override for a contact.

    Removes the manual override, allowing automatic detection to be used again.

    Args:
        contact_email: Email address of the contact.

    Query Parameters:
        account_id (int): ID of the user's account (required).

    Returns:
        JSON with success status.

    Example:
        DELETE /api/contacts/john@example.com/relationship?account_id=1
    """
    # Validate contact email
    if not _validate_contact_email(contact_email):
        return jsonify({"error": "Invalid contact email format"}), 400

    # Get and validate account_id
    account_id_str = request.args.get("account_id")
    if not account_id_str:
        return jsonify({"error": "account_id query parameter is required"}), 400

    # Audit F-04 (2026-05-16): accept both int (/api/init) and hex
    # (/api/accounts) account_ids. The prior `int()`-only validator
    # 400'd on hex even though the frontend AccountManager sends hex;
    # see the same migration on the autocomplete handler at
    # lines 122-138 for the canonical rationale. Ownership check is
    # built into require_owned_account_id, so the legacy
    # _block_cross_account_access wrapper is no longer needed here.
    account_id = require_owned_account_id(account_id_str)
    if account_id == _NO_ACCOUNT_SENTINEL:
        return jsonify({"error": "Forbidden: account_id does not resolve to an owned account"}), 403

    try:
        with _rh.get_db_session() as session:
            service = _make_relationship_service(session)
            deleted = service.delete_relationship_override(
                account_id=account_id,
                contact_email=contact_email,
            )

        if deleted:
            return jsonify({"success": True, "message": "Override deleted"}), 200
        else:
            return jsonify({"error": "Override not found"}), 404

    except Exception as e:
        logger.error(f"Error deleting relationship for {contact_email}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/contacts/relationships/overrides", methods=["GET"])
def get_all_relationship_overrides():
    """
    Get all relationship overrides for an account.

    Returns:
        JSON with list of all overrides.

    Query Parameters:
        account_id (int): ID of the user's account (required).

    Example:
        GET /api/contacts/relationships/overrides?account_id=1
    """
    # Get and validate account_id
    account_id_str = request.args.get("account_id")
    if not account_id_str:
        return jsonify({"error": "account_id query parameter is required"}), 400

    # Audit F-04 (2026-05-16): accept both int (/api/init) and hex
    # (/api/accounts) account_ids. The prior `int()`-only validator
    # 400'd on hex even though the frontend AccountManager sends hex;
    # see the same migration on the autocomplete handler at
    # lines 122-138 for the canonical rationale. Ownership check is
    # built into require_owned_account_id, so the legacy
    # _block_cross_account_access wrapper is no longer needed here.
    account_id = require_owned_account_id(account_id_str)
    if account_id == _NO_ACCOUNT_SENTINEL:
        return jsonify({"error": "Forbidden: account_id does not resolve to an owned account"}), 403

    try:
        with _rh.get_db_session() as session:
            service = _make_relationship_service(session)
            overrides = service.get_all_overrides(account_id=account_id)

        return jsonify({
            "data": [
                {
                    "contact_email": override.contact_email,
                    "relationship_type": override.relationship_type,
                    "created_at": override.created_at.isoformat(),
                    "updated_at": override.updated_at.isoformat(),
                }
                for override in overrides
            ]
        }), 200

    except Exception as e:
        logger.error(f"Error getting overrides for account {account_id}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


# =============================================================================
# CONTACT AVATAR ENDPOINT
# =============================================================================
# Mirrors the photos the user already sees in Gmail / Outlook by reading their
# contacts directory through the provider's OAuth credentials. Returns image
# bytes on success and 204 on miss — the frontend renders the fallback
# initial-avatar without surfacing a noisy Network error.

@api_bp.route("/contacts/avatar", methods=["GET"])
def get_contact_avatar():
    """Returns the avatar image for `?email=<addr>` as raw bytes.

    Falls back to 204 when:
        - the email is malformed
        - the user's OAuth scopes don't include contacts (legacy grants)
        - the contact has no photo in the user's directory
        - the provider call fails for any other reason

    The frontend renders an initial-letter avatar for empty responses, so this
    endpoint must NEVER return 4xx/5xx for "no photo found" — that logs noise
    without changing the UX.
    """
    raw_email = (request.args.get("email", "") or "").strip()
    if not raw_email or len(raw_email) > 320 or not _EMAIL_RE.match(raw_email):
        return Response(status=204)

    try:
        account_id = _resolve_account_id_cached()
    except Exception:
        return Response(status=401)

    if not account_id:
        return Response(status=204)

    # Resolve the active provider for this account.
    try:
        provider = _rh._get_authenticated_provider()
    except Exception as exc:  # noqa: BLE001
        logger.debug("avatar: provider unavailable: %s", exc)
        return Response(status=204)

    # Fast path: if the OAuth grant doesn't include the contacts-photo scope,
    # skip the expensive provider API call entirely (avoids ~1s round-trip
    # to Google/MS just to get a 403). The scope check is cached for 6h.
    from app.services.oauth_scope_check import has_contacts_scope
    if not has_contacts_scope(provider, int(account_id)):
        return Response(
            status=204,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    from app.services.contact_avatar_service import get_contact_avatar as _lookup

    result = _lookup(provider, raw_email, account_id)
    if not result:
        # Cache the negative on the client so we don't pound the endpoint
        # for every redraw of an avatar with no photo.
        # A valid contact with no photo is expected, not a backend error.
        return Response(
            status=204,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    photo_bytes, content_type = result
    return Response(
        photo_bytes,
        mimetype=content_type,
        headers={
            "Content-Length": str(len(photo_bytes)),
            # 24h browser cache + revalidation. The backend's own cache layer
            # is the source of truth; this just spares us round-trips while
            # the user scrolls.
            "Cache-Control": "private, max-age=86400",
        },
    )


# =============================================================================
# CONTACT-PHOTOS OAUTH SCOPE STATUS
# =============================================================================
# Backs ContactPhotosBanner: probes whether the user's OAuth grant includes the
# contact-photo scope. Gmail contact scopes are intentionally not requested, so
# Gmail accounts do not show a re-consent CTA for avatars.

@api_bp.route("/contacts/avatar-status", methods=["GET"])
def get_contact_avatar_status():
    """Returns whether the active account has granted the contact-photo scope.

    Response shape: ``{granted: bool, provider: 'gmail'|'outlook'|'', reason: str|None}``.
    Frontend renders the re-consent CTA banner when ``granted`` is False.
    """
    payload = {"granted": False, "provider": "", "reason": None}

    try:
        account_id = _resolve_account_id_cached()
    except Exception:
        return jsonify(payload), 200

    if not account_id:
        return jsonify(payload), 200

    try:
        provider = _rh._get_authenticated_provider()
    except Exception as exc:  # noqa: BLE001
        logger.debug("avatar-status: provider unavailable: %s", exc)
        payload["reason"] = "provider_unavailable"
        return jsonify(payload), 200

    provider_name = (getattr(provider, "provider_name", "") or "").lower()
    payload["provider"] = provider_name if provider_name in ("gmail", "outlook") else ""
    if provider_name == "gmail":
        payload["provider"] = ""
        payload["reason"] = "gmail_contact_scopes_not_requested"
        return jsonify(payload), 200

    from app.services.oauth_scope_check import has_contacts_scope
    payload["granted"] = bool(has_contacts_scope(provider, int(account_id)))
    if not payload["granted"]:
        payload["reason"] = "scope_not_granted"
    return jsonify(payload), 200


@api_bp.route("/contacts/reconcile", methods=["POST"])
def reconcile_contacts():
    """Force recomputation of sent_count/received_count from stored emails."""
    account_id = _resolve_account_id_for_user()
    if account_id is None:
        return jsonify({"error": "Compte introuvable"}), 404

    try:
        from app.db.database import get_db_session
        from app.db.repositories.contact_repository import ContactRepository
        from app.api.routes_learning import _contact_counts_reconciled

        acct_id_int = int(account_id)
        with get_db_session() as sess:
            stats = ContactRepository(sess).recompute_counts_from_emails(acct_id_int)
            sess.commit()

        _contact_counts_reconciled.pop(acct_id_int, None)
        logger.info("Manual contact reconciliation for account %s: %s", acct_id_int, stats)
        return jsonify({"ok": True, "stats": stats}), 200
    except Exception as e:
        logger.error("Contact reconciliation failed for account %s: %s", account_id, e)
        return error_response("CONTACTS_RECONCILIATION_FAILED", "Reconciliation failed", 500)
