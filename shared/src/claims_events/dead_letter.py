"""Dead-letter envelope construction.

A poisoned event must leave the main topic or it blocks its partition forever.
Publishing it to a dedicated topic and committing the offset is the standard
resolution: processing continues, and the failure is preserved for inspection
rather than discarded.

The dead-letter envelope wraps the original event whole rather than summarising
it. That means a fixed bug can be resolved by replaying the payload as-is,
without reconstructing what the original event contained.
"""

from typing import Any

from claims_events.envelope import EventEnvelope
from claims_events.topics import DeadLetterReason


def build(
    original: EventEnvelope,
    *,
    reason: DeadLetterReason,
    error: str,
    consumer_group: str,
    attempts: int = 1,
) -> EventEnvelope:
    return EventEnvelope(
        event_type="event.dead_lettered",
        aggregate_type=original.aggregate_type,
        aggregate_id=original.aggregate_id,
        payload={
            "reason": reason.value,
            "error": error[:2000],
            "consumer_group": consumer_group,
            "attempts": attempts,
            "original_event_id": str(original.event_id),
            "original_event_type": original.event_type,
            "original_occurred_at": original.occurred_at.isoformat(),
            "original_payload": original.payload,
        },
    )


def to_outbox_params(envelope: EventEnvelope) -> dict[str, Any]:
    """Shape a dead-letter envelope for the outbox insert.

    aggregate_type is forced to 'dead_letter' so topic_for routes it away from
    the topic it failed on. Writing it back to the original topic would
    guarantee an infinite loop.
    """
    return {
        "event_id": str(envelope.event_id),
        "event_type": envelope.event_type,
        "aggregate_type": "dead_letter",
        "aggregate_id": str(envelope.aggregate_id),
        "envelope": envelope.model_dump_json(),
    }
