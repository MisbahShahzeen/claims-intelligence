import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, Date, DateTime, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ProductType(StrEnum):
    MOTOR = "motor"
    PROPERTY = "property"
    LIABILITY = "liability"
    MARINE = "marine"


class PolicyStatus(StrEnum):
    ACTIVE = "active"
    LAPSED = "lapsed"
    CANCELLED = "cancelled"


class Policy(Base):
    __tablename__ = "policies"
    __table_args__ = (
        CheckConstraint(
            "product_type IN ('motor', 'property', 'liability', 'marine')",
            name="ck_policies_product_type",
        ),
        CheckConstraint(
            "status IN ('active', 'lapsed', 'cancelled')",
            name="ck_policies_status",
        ),
        CheckConstraint("effective_to > effective_from", name="ck_policies_period"),
        CheckConstraint("coverage_limit > 0", name="ck_policies_coverage_limit"),
        CheckConstraint("deductible >= 0", name="ck_policies_deductible"),
        {"schema": "claims"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    policy_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    policyholder_name: Mapped[str] = mapped_column(String(200))
    product_type: Mapped[str] = mapped_column(String(32))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date] = mapped_column(Date)
    coverage_limit: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    deductible: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
