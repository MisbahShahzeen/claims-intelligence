"""Decision worker.

Consumes document.extracted, assembles evidence, calls Gemini, writes an
assessment with citations, and emits assessment.completed.

Does NOT write to claims.claims. The triage transition belongs to claims-api,
which owns that table and the state machine that governs it. This worker states
what it found; the service that owns the claim decides what to do about it.
"""

import asyncio
import logging
import signal
import uuid

from aiokafka import AIOKafkaConsumer
from claims_events import DocumentEvent, EventEnvelope, Topic
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from decider import queries
from decider.assessor import Assessor
from decider.config import get_settings
from decider.embedder import Embedder
from decider.retriever import Retriever

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
)
logging.getLogger("aiokafka").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("decision-worker")

settings = get_settings()


class DecisionWorker:
    def __init__(self) -> None:
        self._engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)
        self._embedder = Embedder()
        self._retriever = Retriever(self._embedder)
        self._assessor = Assessor()
        self._consumer: AIOKafkaConsumer | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            Topic.DOCUMENT.value,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=settings.consumer_group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        await self._consumer.start()
        logger.info("listening on %s", Topic.DOCUMENT.value)

    async def stop(self) -> None:
        self._stopping.set()
        if self._consumer is not None:
            await self._consumer.stop()
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
            failed = False
            for _partition, messages in batches.items():
                for message in messages:
                    try:
                        await self._handle(message.value)
                    except Exception:
                        logger.exception("failed handling message")
                        failed = True

            # Only advance offsets if every message in the batch was handled.
            # Committing after a failure would silently drop the work; leaving
            # the offset means Kafka redelivers and processed_events dedupes
            # anything that did succeed.
            if not failed:
                await self._consumer.commit()

    async def _handle(self, raw: bytes) -> None:
        envelope = EventEnvelope.from_json(raw)
        if envelope.event_type != DocumentEvent.EXTRACTED.value:
            return

        claim_id = uuid.UUID(envelope.payload["claim_id"])

        async with self._sessions() as session:
            async with session.begin():
                claimed = await session.execute(
                    queries.CLAIM_EVENT,
                    {
                        "event_id": str(envelope.event_id),
                        "consumer_group": settings.consumer_group,
                    },
                )
                if claimed.scalar_one_or_none() is None:
                    logger.info("skip duplicate event_id=%s", envelope.event_id)
                    return

                context = (
                    (await session.execute(queries.CLAIM_CONTEXT, {"claim_id": str(claim_id)}))
                    .mappings()
                    .one_or_none()
                )
                if context is None:
                    logger.error("claim %s not found", claim_id)
                    return

                claim = {k: str(v) for k, v in dict(context).items()}
                extractions = [
                    {
                        "filename": row.filename,
                        "doc_type": row.doc_type,
                        "confidence": float(row.confidence) if row.confidence else None,
                        "data": row.extracted,
                    }
                    for row in await session.execute(
                        queries.CLAIM_EXTRACTIONS, {"claim_id": str(claim_id)}
                    )
                ]

                logger.info(
                    "assessing %s (%d document(s))", claim["claim_number"], len(extractions)
                )

                narrative = f"{claim['loss_type']} claim: {claim['description']}"
                evidence = await self._retriever.gather(
                    session,
                    loss_narrative=narrative,
                    product_type=claim["product_type"],
                )

                result = await self._assessor.assess(
                    claim=claim, extractions=extractions, evidence=evidence
                )

                await session.execute(
                    queries.INSERT_USAGE,
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

                if not result.succeeded:
                    logger.error(
                        "assessment failed for %s: %s", claim["claim_number"], result.error
                    )
                    raise RuntimeError(result.error or "assessment failed")

                payload = result.payload or {}
                assessment_id = await session.scalar(
                    queries.INSERT_ASSESSMENT,
                    {
                        "claim_id": str(claim_id),
                        "coverage_verdict": payload["coverage_verdict"],
                        "coverage_rationale": payload["coverage_rationale"],
                        "risk_score": payload["risk_score"],
                        "risk_band": payload["risk_band"],
                        "risk_rationale": payload.get("risk_rationale", ""),
                        "recommended_amount": payload.get("recommended_amount"),
                        "model_version": result.model,
                        "prompt_version": result.prompt_version,
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                        "latency_ms": result.latency_ms,
                    },
                )

                refs = {f"clause:{h.id}": h.source_ref for h in evidence.clauses}
                refs |= {f"precedent:{h.id}": h.source_ref for h in evidence.precedents}

                for citation in result.citations:
                    source = str(citation["source"])
                    source_type, _, source_id = source.partition(":")
                    await session.execute(
                        queries.INSERT_CITATION,
                        {
                            "assessment_id": str(assessment_id),
                            "source_type": "policy_chunk"
                            if source_type == "clause"
                            else "precedent",
                            "source_id": source_id,
                            "source_ref": refs.get(source, source)[:128],
                            "relevance": citation.get("relevance"),
                            "quoted_span": citation.get("quoted_span"),
                            "supports": citation.get("supports", "coverage")[:32],
                        },
                    )

                outgoing = EventEnvelope(
                    event_type="assessment.completed",
                    aggregate_type="claim",
                    aggregate_id=claim_id,
                    payload={
                        "claim_id": str(claim_id),
                        "claim_number": claim["claim_number"],
                        "assessment_id": str(assessment_id),
                        "coverage_verdict": payload["coverage_verdict"],
                        "risk_score": payload["risk_score"],
                        "risk_band": payload["risk_band"],
                        "recommended_amount": payload.get("recommended_amount"),
                        "citation_count": len(result.citations),
                    },
                )
                await session.execute(
                    queries.INSERT_OUTBOX,
                    {
                        "event_id": str(outgoing.event_id),
                        "event_type": outgoing.event_type,
                        "aggregate_type": outgoing.aggregate_type,
                        "aggregate_id": str(outgoing.aggregate_id),
                        "envelope": outgoing.model_dump_json(),
                    },
                )

                logger.info(
                    "assessed %s: %s, risk %s (%s), %d citation(s), %d tokens, $%.6f, %dms",
                    claim["claim_number"],
                    payload["coverage_verdict"],
                    payload["risk_score"],
                    payload["risk_band"],
                    len(result.citations),
                    result.input_tokens + result.output_tokens,
                    result.cost_usd,
                    result.latency_ms,
                )


async def main() -> None:
    worker = DecisionWorker()
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
