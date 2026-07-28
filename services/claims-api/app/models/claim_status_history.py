import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ActorType(StrEnum):
    USER = "user"
    SYSTEM = "system"


class ClaimStatusHistory(Base):
    __tablename__ = "claim_status_history"
    __table_args__ = (
        CheckConstraint("actor_type IN ('user', 'system')", name="ck_history_actor_type"),
        CheckConstraint(
            "(actor_type = 'system' AND actor_id IS NULL) OR "
            "(actor_type = 'user' AND actor_id IS NOT NULL)",
            name="ck_history_actor_consistency",
        ),
        Index("ix_claim_status_history_claim_id", "claim_id"),
        {"schema": "claims"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claims.claims.id"))
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("claims.users.id"), nullable=True
    )
    actor_type: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
