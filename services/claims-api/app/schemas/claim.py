import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.claim import ClaimStatus, LossType


class ClaimCreate(BaseModel):
    policy_number: str = Field(min_length=1, max_length=32)
    loss_date: date
    loss_type: LossType
    description: str = Field(min_length=10, max_length=5000)
    claimed_amount: Decimal = Field(gt=0, decimal_places=2)


class ClaimTransition(BaseModel):
    to_status: ClaimStatus
    settlement_amount: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    reason: str | None = Field(default=None, max_length=1000)


class ClaimRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    claim_number: str
    policy_id: uuid.UUID
    assigned_adjuster_id: uuid.UUID | None
    loss_date: date
    reported_date: datetime
    loss_type: str
    description: str
    claimed_amount: Decimal
    status: str
    settled_amount: Decimal | None
    risk_band: str | None
    created_at: datetime
    updated_at: datetime


class ClaimDetail(ClaimRead):
    available_transitions: list[str] = []


class ClaimHistoryEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_status: str | None
    to_status: str
    actor_id: uuid.UUID | None
    actor_type: str
    reason: str | None
    created_at: datetime


class ClaimPage(BaseModel):
    items: list[ClaimRead]
    total: int
    limit: int
    offset: int
