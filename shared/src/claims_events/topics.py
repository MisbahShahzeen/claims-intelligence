from enum import StrEnum


class Topic(StrEnum):
    CLAIM = "claims.claim.v1"
    DOCUMENT = "claims.document.v1"
    ASSESSMENT = "claims.assessment.v1"
    DEAD_LETTER = "claims.dead-letter.v1"


TOPICS: dict[str, int] = {
    Topic.CLAIM: 3,
    Topic.DOCUMENT: 3,
    Topic.ASSESSMENT: 3,
    Topic.DEAD_LETTER: 1,
}

_AGGREGATE_TOPICS = {
    "dead_letter": Topic.DEAD_LETTER,
    "claim": Topic.CLAIM,
    "document": Topic.DOCUMENT,
    "assessment": Topic.ASSESSMENT,
}


def topic_for(aggregate_type: str) -> Topic:
    try:
        return _AGGREGATE_TOPICS[aggregate_type]
    except KeyError:
        raise ValueError(f"No topic registered for aggregate type {aggregate_type!r}") from None


class ClaimEvent(StrEnum):
    SUBMITTED = "claim.submitted"
    STATUS_CHANGED = "claim.status_changed"


class DocumentEvent(StrEnum):
    UPLOADED = "document.uploaded"
    EXTRACTED = "document.extracted"
    EXTRACTION_FAILED = "document.extraction_failed"


class DeadLetterReason(StrEnum):
    """Why an event could not be processed.

    Recorded on the dead-letter envelope so an operator can triage without
    reading logs. The distinction that matters: a MODEL_FAILURE may become
    processable if the model or prompt changes, while MALFORMED_EVENT and
    MISSING_DATA will not.
    """

    MODEL_FAILURE = "model_failure"
    MALFORMED_EVENT = "malformed_event"
    MISSING_DATA = "missing_data"
