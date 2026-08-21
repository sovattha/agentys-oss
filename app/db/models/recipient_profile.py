"""RecipientProfile : profil psychologique DISC persisté par contact (#190).

Unique par couple (account_id, recipient_email). Mis à jour périodiquement
(cron nightly) ou à la réception d'un nouvel email.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class RecipientProfileRow(Base):
    """Mapping ORM pour la table ``recipient_profiles``.

    Nommé ``RecipientProfileRow`` pour ne pas confondre avec la domain entity
    :class:`app.domain.entities.recipient_profile.RecipientProfile` qui reste
    immuable et détachée de la DB.
    """

    __tablename__ = "recipient_profiles"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "recipient_email",
            name="uq_recipient_profiles_account_email",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    disc: Mapped[str] = mapped_column(String(2), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    disc_scores_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )
