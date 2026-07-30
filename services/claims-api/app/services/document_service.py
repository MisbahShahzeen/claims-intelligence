import uuid

from claims_events import DocumentEvent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.events import record_event
from app.models.claim import Claim
from app.models.document import Document, ProcessingStatus
from app.models.user import User

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "text/plain",
}


class DocumentError(Exception):
    pass


async def list_for_claim(session: AsyncSession, claim_id: uuid.UUID) -> list[Document]:
    result = await session.execute(
        select(Document).where(Document.claim_id == claim_id).order_by(Document.created_at.asc())
    )
    return list(result.scalars())


async def upload(
    session: AsyncSession,
    claim: Claim,
    actor: User,
    filename: str,
    mime_type: str,
    data: bytes,
) -> tuple[Document, bool]:
    """Store a document and emit document.uploaded.

    Returns (document, was_duplicate). Re-uploading identical bytes to the same
    claim returns the existing row and emits nothing, so the worker is never
    asked to extract the same content twice.
    """
    if mime_type not in ALLOWED_MIME_TYPES:
        raise DocumentError(f"Unsupported content type: {mime_type}")
    if not data:
        raise DocumentError("Uploaded file is empty")

    digest = storage.content_hash(data)

    existing = await session.execute(
        select(Document).where(Document.claim_id == claim.id, Document.content_hash == digest)
    )
    duplicate = existing.scalar_one_or_none()
    if duplicate is not None:
        return duplicate, True

    key = storage.build_key(claim.id, filename)
    storage.save(key, data)

    document = Document(
        claim_id=claim.id,
        filename=filename[:255],
        storage_key=key,
        content_hash=digest,
        mime_type=mime_type,
        size_bytes=len(data),
        processing_status=ProcessingStatus.UPLOADED.value,
        uploaded_by_id=actor.id,
    )
    session.add(document)
    await session.flush()

    record_event(
        session,
        event_type=DocumentEvent.UPLOADED.value,
        aggregate_type="document",
        aggregate_id=document.id,
        payload={
            "document_id": str(document.id),
            "claim_id": str(claim.id),
            "claim_number": claim.claim_number,
            "storage_key": key,
            "mime_type": mime_type,
            "content_hash": digest,
            "filename": document.filename,
        },
    )

    await session.commit()
    await session.refresh(document)
    return document, False
