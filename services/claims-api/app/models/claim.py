import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Sequence,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ClaimStatus(StrEnum):
    SUBMITTED = "submitted"
    TRIAGED = "triaged"
    UNDER_REVIEW = "under_review"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SETTLED = "settled"
    DENIED = "denied"
    WITHDRAWN = "withdrawn"


class LossType(StrEnum):
    COLLISION = "collision"
    THEFT = "theft"
    FIRE = "fire"
    FLOOD = "flood"
    STORM = "storm"
    LIABILITY = "liability"
    OTHER = "other"


class RiskBand(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


claim_number_seq = Sequence("claim_number_seq", schema="claims")

_STATUS_LIST = ", ".join(f"'{s.value}'" for s in ClaimStatus)
_LOSS_TYPE_LIST = ", ".join(f"'{t.value}'" for t in LossType)


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (
        CheckConstraint(f"status IN ({_STATUS_LIST})", name="ck_claims_status"),
        CheckConstraint(f"loss_type IN ({_LOSS_TYPE_LIST})", name="ck_claims_loss_type"),
        CheckConstraint(
            "risk_band IS NULL OR risk_band IN ('low', 'medium', 'high')",
            name="ck_claims_risk_band",
        ),
        CheckConstraint("claimed_amount > 0", name="ck_claims_claimed_amount"),
        CheckConstraint(
            "settled_amount IS NULL OR settled_amount >= 0",
            name="ck_claims_settled_amount",
        ),
        Index("ix_claims_status", "status"),
        Index("ix_claims_assigned_adjuster_id", "assigned_adjuster_id"),
        Index("ix_claims_policy_id", "policy_id"),
        {"schema": "claims"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    claim_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    policy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claims.policies.id"))
    assigned_adjuster_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("claims.users.id"), nullable=True
    )

    loss_date: Mapped[date] = mapped_column(Date)
    reported_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    loss_type: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    claimed_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    status: Mapped[str] = mapped_column(String(32), server_default="submitted")
    settled_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    risk_band: Mapped[str | None] = mapped_column(String(16), nullable=True)
    latest_assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
