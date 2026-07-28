import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, DateTime, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class UserRole(StrEnum):
    ADJUSTER = "adjuster"
    SENIOR_ADJUSTER = "senior_adjuster"
    ADMIN = "admin"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('adjuster', 'senior_adjuster', 'admin')",
            name="ck_users_role",
        ),
        CheckConstraint("authority_limit >= 0", name="ck_users_authority_limit_non_negative"),
        {"schema": "claims"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32))
    authority_limit: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), server_default="0"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
