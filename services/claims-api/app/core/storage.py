"""Local filesystem storage.

Deliberately behind a narrow interface: save/read/delete by key. Phase 12 swaps
this for MinIO or S3 without touching the callers. Storing files inside Postgres
would avoid a second system but bloats backups and makes streaming awkward.
"""

import hashlib
import uuid
from pathlib import Path

from app.core.config import get_settings

settings = get_settings()

ROOT = Path(settings.storage_root).resolve()


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_key(claim_id: uuid.UUID, filename: str) -> str:
    suffix = Path(filename).suffix.lower()[:16]
    return f"{claim_id}/{uuid.uuid4()}{suffix}"


def save(key: str, data: bytes) -> Path:
    path = (ROOT / key).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Refusing to write outside the storage root")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def read(key: str) -> bytes:
    path = (ROOT / key).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Refusing to read outside the storage root")
    return path.read_bytes()
