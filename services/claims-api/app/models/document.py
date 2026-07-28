import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class DocumentType(StrEnum):
    POLICE_REPORT = "police_report"
    INVOICE = "invoice"
    MEDICAL_BILL = "medical_bill"
    REPAIR_ESTIMATE = "repair_estimate"
    PHOTO = "photo"
    OTHER = "other"
    UNKNOWN = "unknown"


class ProcessingStatus(StrEnum):
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    FAILED = "failed"


_DOC_TYPES = ", ".join(f"'{t.value}'" for t in DocumentType)
_PROC_STATUSES = ", ".join(f"'{s.value}'" for s in ProcessingStatus)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(f"doc_type IN ({_DOC_TYPES})", name="ck_documents_doc_type"),
        CheckConstraint(
            f"processing_status IN ({_PROC_STATUSES})", name="ck_documents_processing_status"
        ),
        CheckConstraint("size_bytes > 0", name="ck_documents_size_bytes"),
        Index("ix_documents_claim_id", "claim_id"),
        Index("ix_documents_content_hash", "content_hash"),
        {"schema": "documents"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(512))
    content_hash: Mapped[str] = mapped_column(String(64))
    mime_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)

    doc_type: Mapped[str] = mapped_column(String(32), server_default="unknown")
    processing_status: Mapped[str] = mapped_column(String(32), server_default="uploaded")

    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Extraction(Base):
    """Append-only. One row per attempt, so model versions can be compared."""

    __tablename__ = "extractions"
    __table_args__ = (
        Index("ix_extractions_document_id", "document_id"),
        {"schema": "documents"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.documents.id"))
    model: Mapped[str] = mapped_column(String(64))
    succeeded: Mapped[bool] = mapped_column(server_default="true")
    extracted: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AiUsage(Base):
    """Every model call, priced. Feeds the Grafana cost dashboard in Phase 11."""

    __tablename__ = "ai_usage"
    __table_args__ = (
        Index("ix_ai_usage_claim_id", "claim_id"),
        Index("ix_ai_usage_created_at", "created_at"),
        {"schema": "ai"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    claim_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    service: Mapped[str] = mapped_column(String(32))
    operation: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 8), server_default="0")
    latency_ms: Mapped[int] = mapped_column(Integer, server_default="0")
    cache_hit: Mapped[bool] = mapped_column(server_default="false")
    succeeded: Mapped[bool] = mapped_column(server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
