"""Vector collections.

Two collections, deliberately not one table with a source_type discriminator.
Policy wordings are retrieved at CLAUSE granularity - the answer to "is this
covered" is a specific exclusion, not a whole document. Historical claims are
retrieved at AGGREGATE granularity - one embedding per resolved claim, returned
whole as precedent. Different retrieval units mean different tables and
independently tunable indexes, rather than one polluted ANN search where a
clause competes for top-k against a claim summary.
"""

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

EMBEDDING_DIMENSIONS = 768


class PolicyDocument(Base):
    """A policy wording, versioned. The parent of many clause chunks."""

    __tablename__ = "policy_documents"
    __table_args__ = ({"schema": "ai"},)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    product_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    effective_from: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PolicyChunk(Base):
    """One clause. Retrieval returns these, and they become citations."""

    __tablename__ = "policy_chunks"
    __table_args__ = (
        Index("ix_policy_chunks_document_id", "policy_document_id"),
        Index("ix_policy_chunks_content_hash", "content_hash"),
        {"schema": "ai"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    policy_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai.policy_documents.id")
    )
    section_ref: Mapped[str] = mapped_column(String(64))
    heading: Mapped[str | None] = mapped_column(String(255), nullable=True)
    clause_text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    is_exclusion: Mapped[bool] = mapped_column(Boolean, server_default="false")
    ordinal: Mapped[int] = mapped_column(Integer, server_default="0")
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ClaimPrecedent(Base):
    """One resolved claim, embedded as a narrative summary."""

    __tablename__ = "claim_precedents"
    __table_args__ = (
        CheckConstraint(
            "risk_band IN ('low', 'medium', 'high')", name="ck_precedents_risk_band"
        ),
        Index("ix_claim_precedents_content_hash", "content_hash"),
        {"schema": "ai"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    claim_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    claim_reference: Mapped[str] = mapped_column(String(32))
    product_type: Mapped[str] = mapped_column(String(32))
    loss_type: Mapped[str] = mapped_column(String(32))
    summary_text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(32))
    claimed_amount: Mapped[float] = mapped_column(Numeric(14, 2))
    settled_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    fraud_flag: Mapped[bool] = mapped_column(Boolean, server_default="false")
    risk_band: Mapped[str] = mapped_column(String(16))
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class EmbeddingCache(Base):
    """Content hash to vector. The reason re-seeding costs zero API calls.

    On a free-tier quota this is not an optimisation, it is the difference
    between the seed script working and it returning 429 halfway through.
    """

    __tablename__ = "embedding_cache"
    __table_args__ = ({"schema": "ai"},)

    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(64), primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
