import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import CurrentUser
from app.models.assessment import SOURCE_TYPES
from app.schemas.assessment import AssessmentRead, SourceDetail
from app.services import assessment_service, claim_service

router = APIRouter(tags=["assessments"])


@router.get("/claims/{claim_id}/assessment", response_model=AssessmentRead)
async def get_assessment(
    claim_id: uuid.UUID,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssessmentRead:
    claim = await claim_service.get_claim(session, claim_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")

    assessment = await assessment_service.latest_for_claim(session, claim_id)
    if assessment is None:
        # 404 rather than an empty object: a claim without an assessment is a
        # normal state (submitted, or the pipeline failed), and the client
        # should render "not assessed" rather than a blank verdict.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No assessment available for this claim",
        )
    return AssessmentRead.model_validate(assessment)


@router.get("/sources/{source_type}/{source_id}", response_model=SourceDetail)
async def get_source(
    source_type: str,
    source_id: uuid.UUID,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SourceDetail:
    if source_type not in SOURCE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown source type: {source_type}",
        )

    detail = await assessment_service.source_detail(session, source_type, source_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    return SourceDetail.model_validate(detail)
