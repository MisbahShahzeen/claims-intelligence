import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import CurrentUser
from app.models.claim import ClaimStatus
from app.models.user import UserRole
from app.schemas.claim import (
    ClaimCreate,
    ClaimDetail,
    ClaimHistoryEntry,
    ClaimPage,
    ClaimRead,
    ClaimTransition,
)
from app.services import claim_service
from app.services.claim_service import ClaimServiceError
from app.services.claim_state_machine import TransitionOutcome, available_transitions

router = APIRouter(prefix="/claims", tags=["claims"])

STATUS_FOR_OUTCOME = {
    TransitionOutcome.ILLEGAL: status.HTTP_409_CONFLICT,
    TransitionOutcome.FORBIDDEN: status.HTTP_403_FORBIDDEN,
    TransitionOutcome.INVALID: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def _as_http_error(error: ClaimServiceError) -> HTTPException:
    return HTTPException(
        status_code=STATUS_FOR_OUTCOME.get(error.outcome, status.HTTP_400_BAD_REQUEST),
        detail=error.message,
    )


@router.post("", response_model=ClaimRead, status_code=status.HTTP_201_CREATED)
async def submit_claim(
    payload: ClaimCreate,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ClaimRead:
    try:
        claim = await claim_service.create_claim(session, payload)
    except ClaimServiceError as error:
        raise _as_http_error(error) from error
    return ClaimRead.model_validate(claim)


@router.get("", response_model=ClaimPage)
async def list_claims(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    claim_status: Annotated[ClaimStatus | None, Query(alias="status")] = None,
    mine: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ClaimPage:
    items, total = await claim_service.list_claims(
        session,
        status=claim_status.value if claim_status else None,
        assigned_adjuster_id=user.id if mine else None,
        limit=limit,
        offset=offset,
    )
    return ClaimPage(
        items=[ClaimRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{claim_id}", response_model=ClaimDetail)
async def get_claim(
    claim_id: uuid.UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ClaimDetail:
    claim = await claim_service.get_claim(session, claim_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")

    detail = ClaimDetail.model_validate(claim)
    detail.available_transitions = sorted(
        available_transitions(ClaimStatus(claim.status), UserRole(user.role))
    )
    return detail


@router.get("/{claim_id}/history", response_model=list[ClaimHistoryEntry])
async def get_claim_history(
    claim_id: uuid.UUID,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ClaimHistoryEntry]:
    claim = await claim_service.get_claim(session, claim_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    entries = await claim_service.get_history(session, claim_id)
    return [ClaimHistoryEntry.model_validate(entry) for entry in entries]


@router.post("/{claim_id}/transitions", response_model=ClaimRead)
async def transition_claim(
    claim_id: uuid.UUID,
    payload: ClaimTransition,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ClaimRead:
    try:
        claim = await claim_service.transition_claim(
            session,
            claim_id,
            actor=user,
            to_status=payload.to_status,
            settlement_amount=payload.settlement_amount,
            reason=payload.reason,
        )
    except ClaimServiceError as error:
        if error.message == "Claim not found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=error.message
            ) from error
        raise _as_http_error(error) from error
    return ClaimRead.model_validate(claim)
