"""Ingestion worker.

Consumes document.uploaded, extracts structured data via Gemini, and emits
document.extracted. The claim's business status is never touched — the pipeline
and the adjudication lifecycle are separate state machines.

Transaction boundary: the Gemini call happens OUTSIDE the database transaction
because it is slow and external. The processed_events insert, the extractions
row, the document status update, and the outgoing event all commit together.
A crash after the model call but before the commit means we pay for a second
call on redelivery, and never write a partial result. That trade is deliberate.
"""

import asyncio
import logging
import signal
import uuid
from pathlib import Path

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from claims_events import DeadLetterReason, DocumentEvent, EventEnvelope, Topic, dead_letter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from worker.config import get_settings
from worker.extractor import ExtractionResult, Extractor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
)
logging.getLogger("aiokafka").setLevel(logging.WARNING)
logger = logging.getLogger("ingestion-worker")

settings = get_settings()
STORAGE_ROOT = Path(settings.storage_root).resolve()

CLAIM_EVENT = text("""
    INSERT INTO claims.processed_events (event_id, consumer_group)
    VALUES (:event_id, :consumer_group)
    ON CONFLICT (event_id, consumer_group) DO NOTHING
    RETURNING event_id
""")

INSERT_EXTRACTION = text("""
    INSERT INTO documents.extractions
        (document_id, model, succeeded, extracted, confidence, error, latency_ms)
    VALUES
        (:document_id, :model, :succeeded, CAST(:extracted AS jsonb), :confidence,
         :error, :latency_ms)
    RETURNING id
""")

INSERT_AI_USAGE = text("""
    INSERT INTO ai.ai_usage
        (claim_id, service, operation, model, input_tokens, output_tokens,
         cost_usd, latency_ms, cache_hit, succeeded)
    VALUES
        (:claim_id, 'ingestion-worker', 'extract', :model, :input_tokens,
         :output_tokens, :cost_usd, :latency_ms, false, :succeeded)
""")

UPDATE_DOCUMENT = text("""
    UPDATE documents.documents
    SET processing_status = :status, doc_type = :doc_type, updated_at = now()
    WHERE id = :document_id
""")

INSERT_OUTBOX = text("""
    INSERT INTO claims.outbox (event_id, event_type, aggregate_type, aggregate_id, envelope)
    VALUES (:event_id, :event_type, :aggregate_type, :aggregate_id, CAST(:envelope AS jsonb))
""")


class IngestionWorker:
    def __init__(self) -> None:
        self._engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)
        self._extractor = Extractor()
        self._consumer: AIOKafkaConsumer | None = None
        self._producer: AIOKafkaProducer | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            Topic.DOCUMENT.value,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=settings.consumer_group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            enable_idempotence=True,
            acks="all",
        )
        await self._consumer.start()
        await self._producer.start()
        logger.info("listening on %s", Topic.DOCUMENT.value)

    async def stop(self) -> None:
        self._stopping.set()
        if self._consumer is not None:
            await self._consumer.stop()
        if self._producer is not None:
            await self._producer.stop()
        await self._engine.dispose()
        logger.info("worker stopped")

    def request_stop(self) -> None:
        self._stopping.set()

    async def run(self) -> None:
        assert self._consumer is not None
        while not self._stopping.is_set():
            batches = await self._consumer.getmany(timeout_ms=1000)
            if not batches:
                continue
            for _partition, messages in batches.items():
                for message in messages:
                    await self._handle(message.value)
            await self._consumer.commit()

    async def _handle(self, raw: bytes) -> None:
        envelope = EventEnvelope.from_json(raw)
        if envelope.event_type != DocumentEvent.UPLOADED.value:
            return

        payload = envelope.payload
        document_id = uuid.UUID(payload["document_id"])
        claim_id = uuid.UUID(payload["claim_id"])

        if await self._already_processed(envelope.event_id):
            logger.info("skip duplicate event_id=%s", envelope.event_id)
            return

        path = STORAGE_ROOT / payload["storage_key"]
        try:
            data = path.read_bytes()
        except OSError as error:
            logger.error("cannot read %s: %s", path, error)
            await self._record(
                envelope,
                document_id,
                claim_id,
                ExtractionResult(
                    succeeded=False,
                    model=settings.gemini_model,
                    latency_ms=0,
                    error=f"storage read failed: {error}",
                ),
            )
            return

        logger.info(
            "extracting document=%s claim=%s (%d bytes)",
            document_id,
            payload.get("claim_number"),
            len(data),
        )

        result = await self._extractor.extract(
            data, payload["mime_type"], payload.get("filename", "upload")
        )

        if result.succeeded:
            logger.info(
                "extracted document=%s type=%s confidence=%s tokens=%d/%d cost=$%.6f %dms",
                document_id,
                (result.extracted or {}).get("doc_type"),
                result.confidence,
                result.input_tokens,
                result.output_tokens,
                result.cost_usd,
                result.latency_ms,
            )
        else:
            logger.error("extraction failed document=%s: %s", document_id, result.error)

        await self._record(envelope, document_id, claim_id, result)

    async def _already_processed(self, event_id: uuid.UUID) -> bool:
        async with self._sessions() as session:
            row = await session.execute(
                text(
                    "SELECT 1 FROM claims.processed_events "
                    "WHERE event_id = :event_id AND consumer_group = :consumer_group"
                ),
                {"event_id": str(event_id), "consumer_group": settings.consumer_group},
            )
            return row.scalar_one_or_none() is not None

    async def _record(
        self,
        envelope: EventEnvelope,
        document_id: uuid.UUID,
        claim_id: uuid.UUID,
        result: ExtractionResult,
    ) -> None:
        import json

        extracted = result.extracted or {}
        doc_type = extracted.get("doc_type", "unknown")
        if doc_type not in {
            "police_report",
            "invoice",
            "medical_bill",
            "repair_estimate",
            "photo",
            "other",
            "unknown",
        }:
            doc_type = "other"

        outgoing = EventEnvelope(
            event_type=(
                DocumentEvent.EXTRACTED.value
                if result.succeeded
                else DocumentEvent.EXTRACTION_FAILED.value
            ),
            aggregate_type="document",
            aggregate_id=document_id,
            payload={
                "document_id": str(document_id),
                "claim_id": str(claim_id),
                "doc_type": doc_type,
                "confidence": result.confidence,
                "summary": extracted.get("summary"),
                "error": result.error,
            },
        )

        async with self._sessions() as session:
            async with session.begin():
                claimed = await session.execute(
                    CLAIM_EVENT,
                    {
                        "event_id": str(envelope.event_id),
                        "consumer_group": settings.consumer_group,
                    },
                )
                if claimed.scalar_one_or_none() is None:
                    logger.info("lost idempotency race for %s", envelope.event_id)
                    return

                await session.execute(
                    INSERT_EXTRACTION,
                    {
                        "document_id": str(document_id),
                        "model": result.model,
                        "succeeded": result.succeeded,
                        "extracted": json.dumps(extracted) if result.succeeded else None,
                        "confidence": result.confidence,
                        "error": result.error,
                        "latency_ms": result.latency_ms,
                    },
                )
                await session.execute(
                    INSERT_AI_USAGE,
                    {
                        "claim_id": str(claim_id),
                        "model": result.model,
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                        "cost_usd": result.cost_usd,
                        "latency_ms": result.latency_ms,
                        "succeeded": result.succeeded,
                    },
                )
                await session.execute(
                    UPDATE_DOCUMENT,
                    {
                        "document_id": str(document_id),
                        "status": "extracted" if result.succeeded else "failed",
                        "doc_type": doc_type,
                    },
                )
                await session.execute(
                    INSERT_OUTBOX,
                    {
                        "event_id": str(outgoing.event_id),
                        "event_type": outgoing.event_type,
                        "aggregate_type": outgoing.aggregate_type,
                        "aggregate_id": str(outgoing.aggregate_id),
                        "envelope": outgoing.model_dump_json(),
                    },
                )

                # A failed extraction already emits document.extraction_failed,
                # which nothing consumes. Also dead-lettering it means the
                # failure is visible on a topic an operator monitors, rather
                # than only in a database column nobody queries.
                if not result.succeeded:
                    letter = dead_letter.build(
                        envelope,
                        reason=DeadLetterReason.MODEL_FAILURE,
                        error=result.error or "extraction failed",
                        consumer_group=settings.consumer_group,
                        attempts=result.attempts,
                    )
                    await session.execute(INSERT_OUTBOX, dead_letter.to_outbox_params(letter))


async def main() -> None:
    worker = IngestionWorker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.request_stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: worker.request_stop())

    await worker.start()
    try:
        await worker.run()
    finally:
        await worker.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
