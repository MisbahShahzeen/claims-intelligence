"""In-process Kafka consumer for claims-api.

Runs inside the API process rather than as a separate service. A read-model
update is cheap enough to share an event loop with request handling, and in
Phase 9 the WebSocket connections live in this process too - so the consumer
that will push to them has to be here.

Consumer group is per-process (a uuid suffix), which means every API replica
receives every event rather than the group load-balancing between them. That is
broadcast semantics, and it is what makes WebSocket fanout work across replicas
without a Redis backplane. The cost is group churn on every restart.
"""

import asyncio
import logging
import uuid

from aiokafka import AIOKafkaConsumer
from claims_events import EventEnvelope, Topic
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.services import claim_service
from app.ws.manager import manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s %(message)s")
logger = logging.getLogger("claims-api.consumer")
logger.setLevel(logging.INFO)
settings = get_settings()

SHARED_GROUP = "claims-api-readmodel"

CLAIM_EVENT = text("""
    INSERT INTO claims.processed_events (event_id, consumer_group)
    VALUES (:event_id, :consumer_group)
    ON CONFLICT (event_id, consumer_group) DO NOTHING
    RETURNING event_id
""")


class EventConsumer:
    def __init__(self) -> None:
        self._consumer: AIOKafkaConsumer | None = None
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._instance_group = f"claims-api-{uuid.uuid4().hex[:8]}"

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            Topic.CLAIM.value,
            Topic.ASSESSMENT.value,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=self._instance_group,
            enable_auto_commit=False,
            # earliest, not latest. A fresh per-instance group would otherwise skip
            # every event published before the process started - including ones
            # it has never applied. The shared-group idempotency ledger makes
            # replaying safe: already-applied events are recognised and skipped.
            auto_offset_reset="earliest",
        )
        await self._consumer.start()
        self._task = asyncio.create_task(self._run())
        logger.info("consumer started, group=%s", self._instance_group)

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._consumer is not None:
            await self._consumer.stop()
        logger.info("consumer stopped")

    async def _run(self) -> None:
        assert self._consumer is not None
        while not self._stopping.is_set():
            try:
                batches = await self._consumer.getmany(timeout_ms=1000)
                if not batches:
                    continue
                failed = False
                for _partition, messages in batches.items():
                    for message in messages:
                        try:
                            await self._handle(message.value)
                        except Exception:
                            logger.exception("failed handling event")
                            failed = True
                if not failed:
                    await self._consumer.commit()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("consumer loop error")
                await asyncio.sleep(1)

    async def _handle(self, raw: bytes) -> None:
        envelope = EventEnvelope.from_json(raw)

        if envelope.event_type in {"claim.submitted", "claim.status_changed"}:
            await self._broadcast(envelope)
            return

        if envelope.event_type != "assessment.completed":
            return

        payload = envelope.payload
        claim_id = uuid.UUID(payload["claim_id"])

        async with SessionLocal() as session:
            async with session.begin():
                # Idempotency here uses the SHARED group, not the per-instance
                # group. Every replica receives this event, but the read-model
                # update must happen exactly once across the whole cluster.
                claimed = await session.execute(
                    CLAIM_EVENT,
                    {
                        "event_id": str(envelope.event_id),
                        "consumer_group": SHARED_GROUP,
                    },
                )
                if claimed.scalar_one_or_none() is None:
                    logger.debug("read model already applied for %s", envelope.event_id)
                    return

                claim = await claim_service.apply_assessment(
                    session,
                    claim_id,
                    assessment_id=uuid.UUID(payload["assessment_id"]),
                    risk_band=payload["risk_band"],
                )
                if claim is None:
                    logger.warning("claim %s not found", claim_id)
                    return

                logger.info(
                    "applied assessment to %s: status=%s risk=%s",
                    claim.claim_number,
                    claim.status,
                    claim.risk_band,
                )
                pending = {
                    "type": "claim.assessed",
                    "claim_id": str(claim.id),
                    "claim_number": claim.claim_number,
                    "status": claim.status,
                    "risk_band": claim.risk_band,
                    "coverage_verdict": payload.get("coverage_verdict"),
                    "risk_score": payload.get("risk_score"),
                    "occurred_at": envelope.occurred_at.isoformat(),
                }

        delivered = await manager.broadcast(pending)
        logger.info("broadcast claim.assessed to %d client(s)", delivered)

    async def _broadcast(self, envelope: EventEnvelope) -> None:
        payload = envelope.payload
        message = {
            "type": envelope.event_type,
            "claim_id": payload.get("claim_id"),
            "claim_number": payload.get("claim_number"),
            "occurred_at": envelope.occurred_at.isoformat(),
        }
        if envelope.event_type == "claim.status_changed":
            message["from_status"] = payload.get("from_status")
            message["to_status"] = payload.get("to_status")
        else:
            message["status"] = payload.get("status")
            message["claimed_amount"] = payload.get("claimed_amount")
            message["loss_type"] = payload.get("loss_type")

        delivered = await manager.broadcast(message)
        if delivered:
            logger.info("broadcast %s to %d client(s)", envelope.event_type, delivered)


consumer = EventConsumer()
