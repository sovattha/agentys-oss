"""
Recap Tracker — Lightweight daily metrics for monthly recap.

Tracks:
- reply_times_minutes: delta between email received_at and draft validated time
- inbox_zero_dates: dates where inbox count reached 0
- active_dates: dates where at least 1 email was processed

Storage: data/recap/daily_tracking.json
"""

import json
import logging
import os
import threading
from datetime import datetime, date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DATA_DIR = Path(os.environ.get("AGENTYS_DATA_DIR", "data")) / "recap"
_TRACKING_FILE = _DATA_DIR / "daily_tracking.json"
_lock = threading.Lock()

_instance: Optional["RecapTracker"] = None


def get_recap_tracker() -> "RecapTracker":
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = RecapTracker()
    return _instance


class RecapTracker:
    def __init__(self, tracking_file: Path = _TRACKING_FILE):
        self._file = tracking_file
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict:
        if self._file.exists():
            try:
                with open(self._file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("Failed to load recap tracking: %s", e)
        return {"reply_times_minutes": {}, "inbox_zero_dates": [], "active_dates": []}

    def _save(self) -> None:
        """Audit MED-1 (2026-04-25): atomic write."""
        import os
        import tempfile
        try:
            fd, tmp_path = tempfile.mkstemp(
                prefix=self._file.name + ".",
                suffix=".tmp",
                dir=str(self._file.parent),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except OSError:
                        pass
                os.replace(tmp_path, self._file)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except IOError as e:
            logger.warning("Failed to save recap tracking: %s", e)

    def _get_bucket(self, account_id=None, create: bool = False) -> dict:
        """Return the per-account metrics container.

        Audit 2026-05-29: this tracker was process-global, so one tenant's
        reply-times / inbox-zero / active-days leaked into every other
        tenant's monthly recap. ``account_id`` now namespaces the data.

        ``account_id=None`` returns the flat top-level dict — preserving the
        pre-fix structure exactly (Tauri single-user, legacy data, and tests).
        A provided account_id stores under ``accounts[str(id)]`` so the buckets
        are isolated. Read access never mutates ``_data``.
        """
        if account_id is None:
            return self._data
        key = str(account_id)
        if create:
            accounts = self._data.setdefault("accounts", {})
            return accounts.setdefault(
                key,
                {"reply_times_minutes": {}, "inbox_zero_dates": [], "active_dates": []},
            )
        accounts = self._data.get("accounts", {})
        return accounts.get(
            key,
            {"reply_times_minutes": {}, "inbox_zero_dates": [], "active_dates": []},
        )

    def record_reply_time(
        self,
        email_received_at: str,
        validated_at: Optional[datetime] = None,
        account_id=None,
    ) -> None:
        """Record reply time in minutes. Called on validate/send."""
        try:
            if not email_received_at:
                return
            received = datetime.fromisoformat(email_received_at.replace("Z", "+00:00"))
            now = validated_at or datetime.now(received.tzinfo)
            delta_minutes = max(0, (now - received).total_seconds() / 60)

            month_key = date.today().strftime("%Y-%m")
            with _lock:
                bucket = self._get_bucket(account_id, create=True)
                times = bucket.setdefault("reply_times_minutes", {})
                month_times = times.setdefault(month_key, [])
                month_times.append(round(delta_minutes, 1))
                self._save()
        except Exception as e:
            logger.debug("Failed to record reply time: %s", e)

    def record_inbox_zero(self, account_id=None) -> None:
        """Record an inbox zero event for today."""
        today_str = date.today().isoformat()
        with _lock:
            bucket = self._get_bucket(account_id, create=True)
            dates = bucket.setdefault("inbox_zero_dates", [])
            if today_str not in dates:
                dates.append(today_str)
                self._save()

    def record_activity(self, account_id=None) -> None:
        """Record that user was active today (processed at least 1 email)."""
        today_str = date.today().isoformat()
        with _lock:
            bucket = self._get_bucket(account_id, create=True)
            dates = bucket.setdefault("active_dates", [])
            if today_str not in dates:
                dates.append(today_str)
                self._save()

    def get_month_data(self, month: str, account_id=None) -> dict:
        """Get tracking data for a specific month (YYYY-MM format)."""
        with _lock:
            bucket = self._get_bucket(account_id)
            reply_times = bucket.get("reply_times_minutes", {}).get(month, [])
            inbox_zero = [d for d in bucket.get("inbox_zero_dates", []) if d.startswith(month)]
            active = [d for d in bucket.get("active_dates", []) if d.startswith(month)]
        return {
            "reply_times": reply_times,
            "inbox_zero_dates": inbox_zero,
            "active_dates": active,
        }

    def get_all_data(self, account_id=None) -> dict:
        """Return full tracking data (for best records computation)."""
        with _lock:
            if account_id is None:
                return dict(self._data)
            return dict(self._get_bucket(account_id))
