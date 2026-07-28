import uuid
from typing import Any

from claims_events import EventEnvelope
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox import OutboxEvent


def record_event(
    session: AsyncSession,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    payload: dict[str, Any],
) -> EventEnvelope:
    """Stage an event for publication. Does NOT commit.

    The caller commits, so the event and the state change share one transaction.
    """
    envelope = EventEnvelope(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload,
    )
    session.add(
        OutboxEvent(
            event_id=envelope.event_id,
            event_type=envelope.event_type,
            aggregate_type=envelope.aggregate_type,
            aggregate_id=envelope.aggregate_id,
            envelope=envelope.model_dump(mode="json"),
        )
    )
    return envelope
