from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RateLimitBucket(Base):
    """Fixed-window counters for unauthenticated endpoints.

    Fixed window rather than sliding: simpler, one row per key, and the known
    weakness is a burst of up to 2x the limit straddling a window boundary.
    Acceptable here because the goal is throttling credential stuffing, not
    precise quota enforcement.
    """

    __tablename__ = "rate_limit_buckets"
    __table_args__ = {"schema": "claims"}

    bucket_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
