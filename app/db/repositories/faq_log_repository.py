"""
Repository for FaqAgentLog — stats and history queries.
"""

from datetime import datetime, timedelta
from typing import Sequence

from sqlalchemy import select

from app.db.models.faq_agent_log import FaqAgentLog
from app.db.repositories.base import BaseRepository


class FaqLogRepository(BaseRepository[FaqAgentLog]):
    model = FaqAgentLog

    def get_history(
        self, account_id: object, limit: int = 20
    ) -> Sequence[FaqAgentLog]:
        # Audit FI-001: column is Integer; coerce defensively for old callers.
        try:
            aid = int(account_id)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return []
        stmt = (
            select(FaqAgentLog)
            .where(FaqAgentLog.account_id == aid)
            .order_by(FaqAgentLog.created_at.desc())
            .limit(limit)
        )
        return self.session.scalars(stmt).all()

    def get_stats(self, account_id: object, days: int = 30) -> dict:
        try:
            aid = int(account_id)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return {
                "auto_sent_count": 0,
                "skipped_count": 0,
                "avg_confidence": 0.0,
                "top_entries": [],
                "period_days": days,
            }
        since = datetime.utcnow() - timedelta(days=days)
        base = select(FaqAgentLog).where(
            FaqAgentLog.account_id == aid,
            FaqAgentLog.created_at >= since,
        )
        logs = self.session.scalars(base).all()

        auto_sent = [log for log in logs if log.action == "auto_sent"]
        skipped = [log for log in logs if log.action == "skipped"]
        avg_conf = (
            sum(log.confidence_score for log in auto_sent) / len(auto_sent)
            if auto_sent
            else 0.0
        )

        # Top matched entries
        entry_counts: dict[str, dict] = {}
        for log in auto_sent:
            if log.matched_entry_id:
                if log.matched_entry_id not in entry_counts:
                    entry_counts[log.matched_entry_id] = {
                        "id": log.matched_entry_id,
                        "title": log.matched_entry_title or "",
                        "count": 0,
                    }
                entry_counts[log.matched_entry_id]["count"] += 1
        top_entries = sorted(
            entry_counts.values(), key=lambda x: x["count"], reverse=True
        )[:5]

        return {
            "auto_sent_count": len(auto_sent),
            "skipped_count": len(skipped),
            "avg_confidence": round(avg_conf, 1),
            "top_entries": top_entries,
            "period_days": days,
        }
