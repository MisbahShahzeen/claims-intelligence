import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventEnvelope(BaseModel):
    """The wire contract between every service in the platform.

    Producers build one of these; consumers parse one of these. Nothing else
    crosses a Kafka topic. Adding a field is backwards compatible; changing the
    meaning of one is not, which is what `schema_version` exists for.
    """

    model_config = ConfigDict(frozen=True)

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: str
    aggregate_type: str
    aggregate_id: uuid.UUID
    schema_version: int = 1
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = Field(default_factory=dict)

    @property
    def partition_key(self) -> bytes:
        """Ordering is guaranteed per aggregate, so the aggregate is the key."""
        return str(self.aggregate_id).encode("utf-8")

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: str | bytes) -> "EventEnvelope":
        return cls.model_validate_json(raw)
