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
Recap Scheduler — Background thread that triggers monthly recap.

Checks hourly. On the first working day of each month at >= 13:00:
1. Computes recap via RecapService
2. Sets banner flags in settings
3. Optionally sends recap email to user (via provider)
"""

import logging
import threading
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 3600  # 1 hour


def _format_time(minutes: float) -> str:
    """Format minutes into human-readable string."""
    if minutes < 1:
        return f"{int(minutes * 60)} s"
    elif minutes < 60:
        return f"{int(minutes)} min"
    else:
        return f"{minutes / 60:.1f}h"


def _get_first_working_day(year: int, month: int) -> int:
    """Return the day number (1-3) of the first Mon-Fri in the given month."""
    d = date(year, month, 1)
    while d.weekday() >= 5:  # Sat=5, Sun=6
        d = d.replace(day=d.day + 1)
    return d.day


def _render_email(recap: dict) -> str:
    """Render the recap email HTML template with recap data."""
    template_path = Path(__file__).parent.parent / "templates" / "recap_email.html"
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        logger.error("Recap email template not found: %s", template_path)
        return ""

    best = recap.get("best", {})

    # Estimate hours without Agentys: 5x the time saved (manual = ~25 min/email vs 5 min)
    hours_without = round(recap.get("emails_processed", 0) * 25 / 60, 0)

    replacements = {
        "{month_label}": recap.get("month_label", ""),
        "{month_label_upper}": recap.get("month_label", "").upper(),
        "{time_saved_hours}": str(recap.get("time_saved_hours", 0)),
        "{time_saved_work_days}": str(recap.get("time_saved_work_days", 0)),
        "{inbox_zero_days}": str(recap.get("inbox_zero_days", 0)),
        "{avg_reply_time}": _format_time(recap.get("avg_reply_time_minutes", 0)),
        "{fastest_reply}": _format_time(recap.get("fastest_reply_minutes", 0)),
        "{ai_assisted_percent}": str(recap.get("ai_assisted_percent", 0)),
        "{days_active}": str(recap.get("days_active", 0)),
        "{best_inbox_zero_days}": str(best.get("inbox_zero_days", 0)),
        "{best_avg_reply_time}": _format_time(best.get("avg_reply_time_minutes", 0)),
        "{best_fastest_reply}": _format_time(best.get("fastest_reply_minutes", 0)),
        "{best_ai_assisted_percent}": str(best.get("ai_assisted_percent", 0)),
        "{best_days_active}": str(best.get("days_active", 0)),
        "{hours_without}": str(int(hours_without)),
        "{comparison_message}": recap.get("comparison", {}).get("message", ""),
    }

    for key, val in replacements.items():
        html = html.replace(key, val)

    return html


def _should_trigger(today: date) -> bool:
    """Check if today is the first working day of the month."""
    first_wd = _get_first_working_day(today.year, today.month)
    return today.day == first_wd


def _get_recap_month(today: date) -> str:
    """Get the month string for the recap (previous month)."""
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


class RecapScheduler:
    """Background thread that triggers monthly recap email + banner."""

    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="RecapScheduler")
        self._thread.start()
        logger.info("RecapScheduler started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("RecapScheduler stopped")

    def _run(self) -> None:
        # Initial delay: wait 60s after API startup before first check
        if self._stop_event.wait(timeout=60):
            return

        while not self._stop_event.is_set():
            # Issue #577 item 4 Phase B — heartbeat at the START of each
            # tick. Tolerance 2× interval so a single missed tick (clock
            # skew, slow DB) does not alert.
            from app.services.scheduler_heartbeat import record_heartbeat

            record_heartbeat(
                "recap_scheduler",
                status="ok",
                expected_interval_seconds=CHECK_INTERVAL_SECONDS * 2,
            )
            try:
                self._check_and_trigger()
            except Exception as e:
                logger.warning("RecapScheduler check failed: %s", e)
                record_heartbeat(
                    "recap_scheduler",
                    status="error",
                    expected_interval_seconds=CHECK_INTERVAL_SECONDS * 2,
                )

            if self._stop_event.wait(timeout=CHECK_INTERVAL_SECONDS):
                break

    def _check_and_trigger(self) -> None:
        today = date.today()
        now = datetime.now()

        # Conditions: first working day + after 13:00
        if not _should_trigger(today):
            return
        if now.hour < 13:
            return

        from app.api.settings import load_settings, save_settings

        recap_month = _get_recap_month(today)

        # M-1 fix (2026-04-25 audit): the scheduler runs in a daemon
        # thread with no request context, so AccountManager.get_current_account()
        # returns whoever activated last on the API — not necessarily a
        # user who should be emailed. Iterate the active accounts loaded
        # from the AccountRepository instead and compute / mail one recap
        # per account.
        try:
            from app.db.database import get_db_session
            from app.db.repositories.account_repository import AccountRepository
            with get_db_session() as session:
                active_accounts = list(AccountRepository(session).get_active_accounts())
        except Exception as e:
            logger.warning("RecapScheduler: failed to load accounts: %s", e)
            return

        if not active_accounts:
            logger.info("RecapScheduler: no active accounts, skipping recap")
            return

        # Audit scalabilité 2026-05-29 (quick win #3) : les flags recap se
        # lisent et s'écrivent PAR COMPTE. L'ancienne lecture globale faisait
        # de `monthly_recap_email_sent_month` un verrou partagé : le premier
        # envoi réussi marquait le mois « fait » pour tous les autres tenants
        # (récap silencieusement perdu), et l'opt-out per-compte écrit par le
        # PATCH /api/settings (scopé) était ignoré par le scheduler (global).
        # Idem bannière : posée en global, elle était masquée à vie par un
        # `monthly_recap_banner_dismissed` per-compte d'un mois précédent.
        from app.services.recap_service import get_recap
        for account in active_accounts:
            account_id = int(account.id)
            try:
                acc_settings = load_settings(account_id=account_id)
                banner_done = acc_settings.get("monthly_recap_banner_month") == recap_month
                email_done = acc_settings.get("monthly_recap_email_sent_month") == recap_month
                email_enabled = bool(acc_settings.get("monthly_recap_email_enabled", True))

                if banner_done and (email_done or not email_enabled):
                    continue  # Tout est déjà fait pour CE compte

                recap = get_recap(recap_month, account_id=account_id)

                if email_enabled and not email_done:
                    self._send_recap_email_for(account, recap, acc_settings, recap_month)

                if not banner_done:
                    acc_settings["monthly_recap_banner_month"] = recap_month
                    acc_settings["monthly_recap_banner_dismissed"] = False
                    save_settings(acc_settings, account_id=account_id)
                    logger.info(
                        "Monthly recap banner activated for %s (account %s)",
                        recap_month, account.email,
                    )
            except Exception as e:
                logger.warning(
                    "RecapScheduler: failed for account %s: %s", account.email, e
                )

    def _send_recap_email_for(self, account, recap: dict, settings: dict, recap_month: str) -> None:
        """Send recap email to the specified account.

        Replaces the pre-fix `_send_recap_email` which read the active
        account from the process-global singleton (cf. M-1).
        """
        try:
            from app.providers.factory import get_email_provider

            html = _render_email(recap)
            if not html:
                return

            provider = get_email_provider(account)
            month_label = recap.get("month_label", recap_month)
            subject = f"Votre recap {month_label} - Agentys"

            success = provider.send_email(
                to=[account.email],
                subject=subject,
                body=html,
                is_html=True,
            )

            if success:
                from app.api.settings import save_settings
                settings["monthly_recap_email_sent_month"] = recap_month
                # Per-compte (audit scalabilité 2026-05-29) : un save GLOBAL
                # ici verrouillait le mois pour tous les autres tenants.
                save_settings(settings, account_id=int(account.id))
                logger.info(
                    "Monthly recap email sent for %s (account %s)", recap_month, account.email
                )
            else:
                logger.warning(
                    "Failed to send recap email for %s (account %s)", recap_month, account.email
                )

            if hasattr(provider, "disconnect"):
                try:
                    provider.disconnect()
                except Exception:
                    pass
        except Exception as e:
            logger.warning("RecapScheduler email error: %s", e)
