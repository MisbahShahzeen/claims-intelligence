import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    claim_id: uuid.UUID
    filename: str
    mime_type: str
    size_bytes: int
    doc_type: str
    processing_status: str
    created_at: datetime
