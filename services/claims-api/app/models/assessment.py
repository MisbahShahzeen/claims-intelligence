"""Assessments and their citations.

Assessments are immutable. Re-running produces a new row with a new
model_version rather than mutating the old one, so two model versions can be
compared on the same claim. There is no status column - presence and recency
are the state.

assessment_citations is polymorphic on (source_type, source_id) with no foreign
key. That is the opposite of the choice made for the two vector collections, and
deliberately so: there the discriminator polluted a search index, here it only
holds a reference. Splitting it into two near-identical tables would turn
"fetch all evidence for this assessment" into a union on the hottest read path.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
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

COVERAGE_VERDICTS = ("covered", "partially_covered", "not_covered", "indeterminate")
SOURCE_TYPES = ("policy_chunk", "precedent")

_VERDICTS = ", ".join(f"'{v}'" for v in COVERAGE_VERDICTS)
_SOURCES = ", ".join(f"'{s}'" for s in SOURCE_TYPES)


class Assessment(Base):
    __tablename__ = "assessments"
    __table_args__ = (
        CheckConstraint(f"coverage_verdict IN ({_VERDICTS})", name="ck_assessments_verdict"),
        CheckConstraint("risk_band IN ('low', 'medium', 'high')", name="ck_assessments_risk_band"),
        CheckConstraint("risk_score >= 0 AND risk_score <= 100", name="ck_assessments_risk_score"),
        Index("ix_assessments_claim_id", "claim_id"),
        Index("ix_assessments_created_at", "created_at"),
        {"schema": "ai"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))

    coverage_verdict: Mapped[str] = mapped_column(String(32))
    coverage_rationale: Mapped[str] = mapped_column(Text)
    risk_score: Mapped[float] = mapped_column(Numeric(5, 2))
    risk_band: Mapped[str] = mapped_column(String(16))
    risk_rationale: Mapped[str] = mapped_column(Text)
    recommended_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    model_version: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[int] = mapped_column(Integer, server_default="1")
    input_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    latency_ms: Mapped[int] = mapped_column(Integer, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssessmentCitation(Base):
    """The evidence behind a verdict. Every claim the model makes traces here."""

    __tablename__ = "assessment_citations"
    __table_args__ = (
        CheckConstraint(f"source_type IN ({_SOURCES})", name="ck_citations_source_type"),
        Index("ix_assessment_citations_assessment_id", "assessment_id"),
        {"schema": "ai"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai.assessments.id"))
    source_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    source_ref: Mapped[str] = mapped_column(String(128))
    relevance: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    quoted_span: Mapped[str | None] = mapped_column(Text, nullable=True)
    supports: Mapped[str] = mapped_column(String(32), server_default="coverage")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
