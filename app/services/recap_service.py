# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Recap Service — Aggregates monthly recap data from multiple sources.

Data sources:
- RecapTracker: reply times, inbox zero, active days
- DraftHistory: emails processed, drafts generated
- MINUTES_SAVED_PER_DRAFT = 3

Computes comparison with previous month and all-time best records.
"""

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Fallback constants (used only if DraftQualityTracker unavailable)
MINUTES_SAVED_PER_DRAFT = 3      # Rédaction IA — base par brouillon
MINUTES_PER_AUTOSORT = 0.4       # Tri automatique
MINUTES_PER_AUTOARCHIVE = 0.4    # Archivage auto
MINUTES_PER_ACTIVE_DAY_KBD = 2   # Raccourcis clavier
_BEST_RECORDS_FILE = Path(os.environ.get("AGENTYS_DATA_DIR", "data")) / "recap" / "best_records.json"

MONTH_NAMES_EN = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
MONTH_NAMES_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _read_best_records_file() -> dict:
    if _BEST_RECORDS_FILE.exists():
        try:
            with open(_BEST_RECORDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _load_best_records(account_id=None) -> dict:
    """Personal-best metrics. Audit 2026-05-29: best records were a single
    process-global blob, so one tenant saw another tenant's records as their
    own. ``account_id`` namespaces them under ``accounts[str(id)]``;
    ``account_id=None`` keeps the legacy top-level blob (Tauri / tests).
    """
    raw = _read_best_records_file()
    if account_id is None:
        return raw
    return dict(raw.get("accounts", {}).get(str(account_id), {}))


def _save_best_records(records: dict, account_id=None) -> None:
    """Audit MED-1 (2026-04-25): atomic write via tempfile + os.replace pour
    éviter qu'un crash mid-write laisse un JSON tronqué.

    Audit 2026-05-29: when account_id is set, merge into that account's bucket
    so tenants don't overwrite each other's records.
    """
    import os
    import tempfile
    if account_id is None:
        payload = records
    else:
        payload = _read_best_records_file()
        payload.setdefault("accounts", {})[str(account_id)] = records
    try:
        _BEST_RECORDS_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=_BEST_RECORDS_FILE.name + ".",
            suffix=".tmp",
            dir=str(_BEST_RECORDS_FILE.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp_path, _BEST_RECORDS_FILE)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except IOError as e:
        logger.warning("Failed to save best records: %s", e)


def _prev_month(month: str) -> str:
    """Given YYYY-MM, return the previous month string."""
    year, m = int(month[:4]), int(month[5:7])
    if m == 1:
        return f"{year - 1}-12"
    return f"{year}-{m - 1:02d}"


def _month_label(month: str) -> str:
    """Convert YYYY-MM to English label: 'FEBRUARY 2026'."""
    parts = month.split("-")
    m_idx = int(parts[1]) - 1
    return f"{MONTH_NAMES_EN[m_idx].upper()} {parts[0]}"


def _month_label_fr(month: str) -> str:
    """Convert YYYY-MM to French label: 'avril 2026'."""
    parts = month.split("-")
    m_idx = int(parts[1]) - 1
    return f"{MONTH_NAMES_FR[m_idx]} {parts[0]}"


def get_recap(month: Optional[str] = None, account_id: Optional[int] = None) -> dict:
    """
    Compute the full monthly recap for the given month.

    Args:
        month: YYYY-MM format. Defaults to previous month.
        account_id: Filtre les drafts sur ce compte. Si None ou <= 0,
                    les métriques draft_history sont nulles (safe default).

    Returns:
        Dict with all recap fields.
    """
    if not month:
        today = date.today()
        if today.month == 1:
            month = f"{today.year - 1}-12"
        else:
            month = f"{today.year}-{today.month - 1:02d}"

    # --- Gather data from RecapTracker ---
    from app.services.recap_tracker import get_recap_tracker
    tracker = get_recap_tracker()
    # Scope tracker metrics to this account (audit 2026-05-29) so reply-times /
    # inbox-zero / active-days don't mix in other tenants' behaviour.
    _tracker_aid = account_id if account_id and account_id > 0 else None
    tracker_data = tracker.get_month_data(month, account_id=_tracker_aid)

    reply_times = tracker_data["reply_times"]
    inbox_zero_dates = tracker_data["inbox_zero_dates"]
    active_dates = tracker_data["active_dates"]

    # --- Gather data from DraftHistory (scoped par compte) ---
    emails_processed = 0
    drafts_generated = 0
    inferred_emails_processed = False
    if account_id and account_id > 0:
        try:
            from app.infrastructure.container import get_container
            container = get_container()
            draft_history = container.get_draft_history()
            all_records = draft_history.get_all_for_account(account_id, limit=10000)
            for record in all_records:
                if record.timestamp and record.timestamp.startswith(month):
                    emails_processed += 1
                    if record.draft_final or record.draft_v1:
                        drafts_generated += 1
        except Exception as e:
            logger.warning("Failed to load draft history for recap: %s", e)

    # --- Feature breakdown via DraftQualityTracker (données réelles) ---
    tracker_activity = {}
    try:
        from app.draft_quality_tracker import get_tracker
        tracker_activity = get_tracker().get_month_activity(month, account_id=_tracker_aid)
    except Exception as e:
        logger.warning("Failed to load tracker activity for recap: %s", e)

    tb = tracker_activity.get("time_breakdown", {})
    feats = tracker_activity.get("features", {})
    tiers = tracker_activity.get("tiers", {})

    tracked_drafts = int(tracker_activity.get("drafts") or 0)
    tracked_ai_drafts = (
        int(tiers.get("simple") or 0)
        + int(tiers.get("standard") or 0)
        + int(tiers.get("complex") or 0)
        + int(feats.get("compose_ai") or 0)
        + int(feats.get("auto_reply") or 0)
    )
    if drafts_generated == 0 and tracked_ai_drafts > 0:
        drafts_generated = tracked_ai_drafts
    elif tracked_drafts > drafts_generated:
        drafts_generated = tracked_drafts
    if emails_processed == 0 and drafts_generated > 0:
        emails_processed = drafts_generated
        inferred_emails_processed = True
    elif 0 < emails_processed < drafts_generated:
        emails_processed = drafts_generated
        inferred_emails_processed = True

    # --- Compute metrics ---
    inbox_zero_days = len(inbox_zero_dates)
    days_active = len(active_dates)

    avg_reply_time = round(sum(reply_times) / len(reply_times), 1) if reply_times else 0
    fastest_reply = round(min(reply_times), 1) if reply_times else 0

    ai_assisted_percent = round(drafts_generated / emails_processed * 100, 1) if emails_processed > 0 else 0

    # Fallback si tracker indisponible
    drafts_min = tb.get("drafts", drafts_generated * MINUTES_SAVED_PER_DRAFT)
    archive_min = tb.get("archive", drafts_generated * MINUTES_PER_AUTOARCHIVE)
    label_min = tb.get("label", emails_processed * MINUTES_PER_AUTOSORT)
    followup_min = tb.get("followup", 0)
    attachment_min = tb.get("attachment_reminder", 0)
    deep_work_min = tb.get("deep_work", 0)
    shortcuts_min = tb.get("shortcuts", days_active * MINUTES_PER_ACTIVE_DAY_KBD)

    n_simple = tiers.get("simple", 0)
    n_standard = tiers.get("standard", 0)
    n_complex = tiers.get("complex", 0)
    n_compose = feats.get("compose_ai", 0)
    n_auto_reply = feats.get("auto_reply", 0)
    n_attachment = feats.get("attachment_reminder", 0)
    n_deep_work = feats.get("deep_work_emails", 0)
    n_shortcuts = feats.get("shortcut", 0)

    total_ai_drafts = n_simple + n_standard + n_complex + n_compose + n_auto_reply
    if total_ai_drafts == 0:
        total_ai_drafts = drafts_generated

    feature_breakdown = [
        {
            "key": "ai_drafting",
            "label": "AI drafting",
            # drafts_min includes compose_ai + refine_ai + auto_reply (from tracker)
            "minutes": round(drafts_min),
            "detail": f"{total_ai_drafts} draft{'s' if total_ai_drafts != 1 else ''}",
        },
        {
            "key": "autosort",
            "label": "Auto-sorting",
            "minutes": round(label_min),
            "detail": f"{emails_processed} emails sorted",
        },
        {
            "key": "autoarchive",
            "label": "Auto-archiving",
            "minutes": round(archive_min),
            "detail": f"{tracker_activity.get('archives', drafts_generated)} archived after send",
        },
        {
            "key": "shortcuts",
            "label": "Keyboard shortcuts",
            "minutes": round(shortcuts_min),
            "detail": f"{n_shortcuts or days_active * 8} actions",
        },
        {
            "key": "attachment_reminder",
            "label": "Attachment reminder",
            "minutes": round(attachment_min),
            "detail": f"{n_attachment} forgotten attachment{'s' if n_attachment != 1 else ''} caught",
        } if n_attachment > 0 else None,
        {
            "key": "deep_work",
            "label": "Focus mode",
            "minutes": round(deep_work_min),
            "detail": f"{n_deep_work} interruption{'s' if n_deep_work != 1 else ''} blocked",
        } if n_deep_work > 0 else None,
        {
            "key": "followup",
            "label": "Follow-up reminders",
            "minutes": round(followup_min),
            "detail": f"{tiers.get('followup', 0)} reminder{'s' if tiers.get('followup', 0) != 1 else ''}",
        } if followup_min > 0 else None,
    ]
    feature_breakdown = [f for f in feature_breakdown if f is not None and f["minutes"] > 0]

    # Temps total = somme de toutes les contributions
    time_saved_minutes = sum(f["minutes"] for f in feature_breakdown)
    time_saved_hours = round(time_saved_minutes / 60, 1)
    time_saved_work_days = round(time_saved_hours / 8, 1)
    has_tracked_activity = (
        time_saved_minutes > 0
        or inbox_zero_days > 0
        or days_active > 0
        or drafts_generated > 0
    )
    data_quality = "empty" if not has_tracked_activity else "complete"
    data_notes = []
    if has_tracked_activity and inferred_emails_processed:
        data_quality = "partial"
        data_notes.append("draft_history_missing")

    # --- Comparison with previous month (scoped par compte) ---
    prev = _prev_month(month)
    prev_recap = _compute_basic_metrics(prev, account_id=account_id)
    comparison = _build_comparison(time_saved_hours, prev_recap.get("time_saved_hours", 0), prev, month, account_id=_tracker_aid)

    # --- Best records (scoped per account — audit 2026-05-29) ---
    best = _load_best_records(_tracker_aid)
    current_metrics = {
        "inbox_zero_days": inbox_zero_days,
        "avg_reply_time_minutes": avg_reply_time,
        "fastest_reply_minutes": fastest_reply,
        "ai_assisted_percent": ai_assisted_percent,
        "days_active": days_active,
    }

    updated = False
    for key, val in current_metrics.items():
        is_lower_better = key in ("avg_reply_time_minutes", "fastest_reply_minutes")
        current_best = best.get(key)
        if current_best is None:
            best[key] = val
            updated = True
        elif is_lower_better:
            if val > 0 and (current_best == 0 or val < current_best):
                best[key] = val
                updated = True
        else:
            if val > current_best:
                best[key] = val
                updated = True

    if updated:
        _save_best_records(best, _tracker_aid)

    return {
        "month": month,
        "month_label": _month_label(month),
        "emails_processed": emails_processed,
        "drafts_generated": drafts_generated,
        "time_saved_hours": time_saved_hours,
        "time_saved_work_days": time_saved_work_days,
        "inbox_zero_days": inbox_zero_days,
        "avg_reply_time_minutes": avg_reply_time,
        "fastest_reply_minutes": fastest_reply,
        "ai_assisted_percent": ai_assisted_percent,
        "days_active": days_active,
        "comparison": comparison,
        "best": best,
        "feature_breakdown": feature_breakdown,
        "is_empty": not has_tracked_activity,
        "data_quality": data_quality,
        "data_notes": data_notes,
    }


def _compute_basic_metrics(month: str, account_id: Optional[int] = None) -> dict:
    """Compute time_saved_hours for a given month (scoped par compte).

    Sans ``account_id`` valide, retourne 0 et log un warning — évite le
    silent-failure si un futur caller oublie le paramètre (vs silent 0h).
    """
    drafts = 0
    tracker_minutes = 0.0
    if account_id and account_id > 0:
        try:
            from app.draft_quality_tracker import get_tracker
            tracker_activity = get_tracker().get_month_activity(month, account_id=account_id)
            tracker_minutes = float(tracker_activity.get("time_saved_min") or 0)
        except Exception as e:
            logger.debug(f"recap tracker metrics failed for account={account_id} month={month}: {e}")
        try:
            from app.infrastructure.container import get_container
            container = get_container()
            draft_history = container.get_draft_history()
            for record in draft_history.get_all_for_account(account_id, limit=10000):
                if record.timestamp and record.timestamp.startswith(month):
                    if record.draft_final or record.draft_v1:
                        drafts += 1
        except Exception as e:
            logger.debug(f"recap basic metrics failed for account={account_id} month={month}: {e}")
    else:
        logger.warning(
            f"recap _compute_basic_metrics called without account_id (month={month}) — "
            "returning 0. All callers must pass a valid account_id after commit 18aa46fb."
        )
    history_hours = round(drafts * MINUTES_SAVED_PER_DRAFT / 60, 1)
    tracker_hours = round(tracker_minutes / 60, 1)
    return {"time_saved_hours": max(history_hours, tracker_hours)}


def _build_comparison(current_hours: float, prev_hours: float, prev_month: str, current_month: str, account_id=None) -> dict:
    """Build comparison object with French message."""
    # Check if previous month had any data
    prev_label = _month_label_fr(prev_month)
    delta = round(current_hours - prev_hours, 1)

    if current_hours == 0 and prev_hours == 0:
        return {
            "type": "empty",
            "delta_hours": 0,
            "message": "Pas encore assez de données pour comparer ce mois.",
        }

    # First month check: no previous data at all
    if prev_hours == 0 and current_hours > 0:
        # Check if there's any data before prev_month
        has_history = False
        try:
            from app.services.recap_tracker import get_recap_tracker
            tracker = get_recap_tracker()
            # Scope history lookup to this account (audit 2026-05-29).
            all_data = tracker.get_all_data(account_id=account_id)
            for d in all_data.get("active_dates", []):
                if d < current_month:
                    has_history = True
                    break
        except Exception:
            pass

        if not has_history:
            return {
                "type": "first_month",
                "delta_hours": 0,
                "message": "Premier mois complet : ce sera votre point de référence.",
            }

    if delta > 0.5:
        return {
            "type": "improving",
            "delta_hours": delta,
            "message": f"{delta} h de plus qu’en {prev_label}. Vous accélérez.",
        }
    elif delta < -0.5:
        return {
            "type": "declining",
            "delta_hours": delta,
            "message": f"{abs(delta)} h de moins qu’en {prev_label}. Le mode focus peut aider.",
        }
    else:
        return {
            "type": "same",
            "delta_hours": delta,
            "message": f"Stable par rapport à {prev_label}. Vous gardez le rythme.",
        }
