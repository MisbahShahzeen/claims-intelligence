import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class OutboxEvent(Base):
    """Events written in the same transaction as the state they describe.

    The relay publishes rows where published_at IS NULL. Because the row and the
    business change commit together, an event can never describe a change that
    was rolled back, and a committed change can never fail to produce an event.
    """

    __tablename__ = "outbox"
    __table_args__ = (
        Index(
            "ix_outbox_unpublished",
            "created_at",
            postgresql_where="published_at IS NULL",
        ),
        {"schema": "claims"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    event_type: Mapped[str] = mapped_column(String(64))
    aggregate_type: Mapped[str] = mapped_column(String(32))
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    envelope: Mapped[dict[str, Any]] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProcessedEvent(Base):
    """Consumer-side idempotency ledger.

    Kafka delivers at least once. A consumer that writes its event_id here inside
    the same transaction as its side effect becomes effectively exactly-once.
    """

    __tablename__ = "processed_events"
    __table_args__ = {"schema": "claims"}

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    consumer_group: Mapped[str] = mapped_column(String(64), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
