"""Legal consent records captured before OAuth handoff."""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class LegalConsent(Base):
    """Proof that a user accepted legal terms before starting OAuth."""

    __tablename__ = "legal_consents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    terms_version: Mapped[str] = mapped_column(String(64), nullable=False)
    privacy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)


Index("ix_legal_consents_provider_accepted", LegalConsent.provider, LegalConsent.accepted_at)
Index("ix_legal_consents_account_id", LegalConsent.account_id)
Index("ix_legal_consents_user_id", LegalConsent.user_id)
