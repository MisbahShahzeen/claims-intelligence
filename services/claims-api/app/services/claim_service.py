import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.claim import Claim, ClaimStatus
from app.models.claim_status_history import ActorType, ClaimStatusHistory
from app.models.policy import Policy, PolicyStatus
from app.models.user import User
from app.schemas.claim import ClaimCreate
from app.services.claim_state_machine import (
    TransitionOutcome,
    TransitionRequest,
    TransitionResult,
    evaluate,
)


class ClaimServiceError(Exception):
    def __init__(self, outcome: TransitionOutcome, message: str) -> None:
        self.outcome = outcome
        self.message = message
        super().__init__(message)


async def _next_claim_number(session: AsyncSession) -> str:
    value = await session.scalar(select(func.nextval("claims.claim_number_seq")))
    return f"CLM-{datetime.now(UTC).year}-{value:06d}"


async def get_policy_by_number(session: AsyncSession, policy_number: str) -> Policy | None:
    result = await session.execute(
        select(Policy).where(Policy.policy_number == policy_number.upper())
    )
    return result.scalar_one_or_none()


async def create_claim(session: AsyncSession, payload: ClaimCreate) -> Claim:
    policy = await get_policy_by_number(session, payload.policy_number)
    if policy is None:
        raise ClaimServiceError(TransitionOutcome.INVALID, "Unknown policy number")
    if policy.status != PolicyStatus.ACTIVE.value:
        raise ClaimServiceError(TransitionOutcome.INVALID, "Policy is not active")
    if not (policy.effective_from <= payload.loss_date <= policy.effective_to):
        raise ClaimServiceError(
            TransitionOutcome.INVALID,
            "Loss date falls outside the policy period",
        )

    claim = Claim(
        claim_number=await _next_claim_number(session),
        policy_id=policy.id,
        loss_date=payload.loss_date,
        loss_type=payload.loss_type.value,
        description=payload.description,
        claimed_amount=payload.claimed_amount,
        status=ClaimStatus.SUBMITTED.value,
    )
    session.add(claim)
    await session.flush()

    session.add(
        ClaimStatusHistory(
            claim_id=claim.id,
            from_status=None,
            to_status=ClaimStatus.SUBMITTED.value,
            actor_id=None,
            actor_type=ActorType.SYSTEM.value,
            reason="Claim submitted via FNOL intake",
        )
    )
    await session.commit()
    await session.refresh(claim)
    return claim


async def get_claim(session: AsyncSession, claim_id: uuid.UUID) -> Claim | None:
    return await session.get(Claim, claim_id)


async def list_claims(
    session: AsyncSession,
    *,
    status: str | None = None,
    assigned_adjuster_id: uuid.UUID | None = None,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[Claim], int]:
    filters = []
    if status is not None:
        filters.append(Claim.status == status)
    if assigned_adjuster_id is not None:
        filters.append(Claim.assigned_adjuster_id == assigned_adjuster_id)

    total = await session.scalar(
        select(func.count()).select_from(Claim).where(*filters)
    )
    result = await session.execute(
        select(Claim)
        .where(*filters)
        .order_by(Claim.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars()), int(total or 0)


async def get_history(session: AsyncSession, claim_id: uuid.UUID) -> list[ClaimStatusHistory]:
    result = await session.execute(
        select(ClaimStatusHistory)
        .where(ClaimStatusHistory.claim_id == claim_id)
        .order_by(ClaimStatusHistory.created_at.asc())
    )
    return list(result.scalars())


async def _escalated_by(session: AsyncSession, claim_id: uuid.UUID) -> uuid.UUID | None:
    result = await session.execute(
        select(ClaimStatusHistory.actor_id)
        .where(
            ClaimStatusHistory.claim_id == claim_id,
            ClaimStatusHistory.to_status == ClaimStatus.PENDING_APPROVAL.value,
        )
        .order_by(ClaimStatusHistory.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def transition_claim(
    session: AsyncSession,
    claim_id: uuid.UUID,
    actor: User,
    to_status: ClaimStatus,
    settlement_amount: Decimal | None = None,
    reason: str | None = None,
) -> Claim:
    claim = await session.get(Claim, claim_id, with_for_update=True)
    if claim is None:
        raise ClaimServiceError(TransitionOutcome.INVALID, "Claim not found")

    from_status = ClaimStatus(claim.status)
    escalated_by = None
    if from_status is ClaimStatus.PENDING_APPROVAL:
        escalated_by = await _escalated_by(session, claim_id)

    result: TransitionResult = evaluate(
        TransitionRequest(
            from_status=from_status,
            to_status=to_status,
            actor_id=actor.id,
            actor_role=actor.role,
            actor_authority_limit=actor.authority_limit,
            settlement_amount=settlement_amount,
            escalated_by_id=escalated_by,
        )
    )
    if not result.allowed:
        raise ClaimServiceError(result.outcome, result.message or "Transition not permitted")

    claim.status = to_status.value
    if settlement_amount is not None and to_status in {
        ClaimStatus.APPROVED,
        ClaimStatus.SETTLED,
    }:
        claim.settled_amount = settlement_amount
    if to_status is ClaimStatus.UNDER_REVIEW and claim.assigned_adjuster_id is None:
        claim.assigned_adjuster_id = actor.id

    session.add(
        ClaimStatusHistory(
            claim_id=claim.id,
            from_status=from_status.value,
            to_status=to_status.value,
            actor_id=actor.id,
            actor_type=ActorType.USER.value,
            reason=reason,
        )
    )
    await session.commit()
    await session.refresh(claim)
    return claim
