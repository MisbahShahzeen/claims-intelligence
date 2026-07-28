import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.deps import CurrentUser
from app.schemas.document import DocumentRead
from app.services import claim_service, document_service
from app.services.document_service import DocumentError

router = APIRouter(prefix="/claims/{claim_id}/documents", tags=["documents"])
settings = get_settings()


@router.get("", response_model=list[DocumentRead])
async def list_documents(
    claim_id: uuid.UUID,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DocumentRead]:
    claim = await claim_service.get_claim(session, claim_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    documents = await document_service.list_for_claim(session, claim_id)
    return [DocumentRead.model_validate(doc) for doc in documents]


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    claim_id: uuid.UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    file: Annotated[UploadFile, File()],
) -> DocumentRead:
    claim = await claim_service.get_claim(session, claim_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")

    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {settings.max_upload_bytes} bytes",
        )

    try:
        document, _duplicate = await document_service.upload(
            session,
            claim=claim,
            actor=user,
            filename=file.filename or "upload",
            mime_type=file.content_type or "application/octet-stream",
            data=data,
        )
    except DocumentError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error

    return DocumentRead.model_validate(document)
