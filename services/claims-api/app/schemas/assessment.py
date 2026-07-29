import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class CitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_type: str
    source_id: uuid.UUID
    source_ref: str
    relevance: Decimal | None
    quoted_span: str | None
    supports: str


class AssessmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    claim_id: uuid.UUID
    coverage_verdict: str
    coverage_rationale: str
    risk_score: Decimal
    risk_band: str
    risk_rationale: str
    recommended_amount: Decimal | None
    model_version: str
    prompt_version: int
    latency_ms: int
    created_at: datetime
    citations: list[CitationRead] = []


class SourceDetail(BaseModel):
    """The full text behind a citation, fetched on demand.

    Citations store a display reference, not the clause body. Loading every
    clause with the assessment would send several kilobytes the adjuster
    probably will not read; this endpoint serves the one they clicked.
    """

    source_type: str
    source_id: uuid.UUID
    source_ref: str
    body: str
    metadata: dict = {}
