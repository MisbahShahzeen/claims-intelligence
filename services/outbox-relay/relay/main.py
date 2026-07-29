"""Outbox relay.

Polls claims.outbox for unpublished rows and publishes them to Kafka, then marks
them published. Runs as its own process so a slow broker never adds latency to an
HTTP request, and so it can be restarted or scaled without touching the API.

Delivery is at-least-once by design: the publish and the mark-published are two
separate operations, and a crash between them replays the event. Consumers
deduplicate on event_id, which is why claims.processed_events exists.
"""

import asyncio
import logging
import signal
from typing import Any

from aiokafka import AIOKafkaProducer
from claims_events import EventEnvelope, topic_for
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from relay import metrics
from relay.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
)
logger = logging.getLogger("outbox-relay")

settings = get_settings()

CLAIM_BATCH = text("""
    SELECT id, event_id, aggregate_type, envelope, attempts
    FROM claims.outbox
    WHERE published_at IS NULL AND attempts < :max_attempts
    ORDER BY created_at
    LIMIT :batch_size
    FOR UPDATE SKIP LOCKED
""")

MARK_PUBLISHED = text("""
    UPDATE claims.outbox SET published_at = now() WHERE id = :id
""")

BACKLOG = text("""
    SELECT count(*) AS backlog,
           COALESCE(EXTRACT(EPOCH FROM (now() - min(created_at))), 0)::int AS oldest_age
    FROM claims.outbox
    WHERE published_at IS NULL
""")

MARK_FAILED = text("""
    UPDATE claims.outbox
    SET attempts = attempts + 1, last_error = :error
    WHERE id = :id
""")


class Relay:
    def __init__(self) -> None:
        self._engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        self._producer: AIOKafkaProducer | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            enable_idempotence=True,
            acks="all",
        )
        await self._producer.start()
        metrics.serve(settings.metrics_port)
        logger.info("metrics on :%d", settings.metrics_port)
        logger.info("connected to kafka at %s", settings.kafka_bootstrap_servers)

    async def stop(self) -> None:
        self._stopping.set()
        if self._producer is not None:
            await self._producer.stop()
        await self._engine.dispose()
        logger.info("relay stopped")

    def request_stop(self) -> None:
        self._stopping.set()

    async def run(self) -> None:
        while not self._stopping.is_set():
            try:
                published = await self._drain_once()
            except Exception:
                logger.exception("relay iteration failed")
                published = 0

            if published == 0:
                try:
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=settings.poll_interval_seconds
                    )
                except TimeoutError:
                    pass

    async def _drain_once(self) -> int:
        assert self._producer is not None
        published = 0

        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    CLAIM_BATCH,
                    {"max_attempts": settings.max_attempts, "batch_size": settings.batch_size},
                )
                rows = result.mappings().all()

                # Recorded every cycle, including when the batch is empty, so a
                # rising backlog is visible even while nothing is succeeding.
                stats = (await session.execute(BACKLOG)).mappings().one()
                metrics.outbox_backlog.set(stats["backlog"])
                metrics.outbox_oldest_age_seconds.set(stats["oldest_age"])

                for row in rows:
                    if await self._publish(session, row):
                        published += 1

        if published:
            logger.info("published %d event(s)", published)
        return published

    async def _publish(self, session: Any, row: Any) -> bool:
        assert self._producer is not None
        try:
            envelope = EventEnvelope.model_validate(row["envelope"])
            topic = topic_for(row["aggregate_type"])

            with metrics.publish_seconds.time():
                await self._producer.send_and_wait(
                    topic.value,
                    value=envelope.to_json().encode("utf-8"),
                    key=envelope.partition_key,
                )
            await session.execute(MARK_PUBLISHED, {"id": row["id"]})
            metrics.events_published_total.labels(
                event_type=envelope.event_type, topic=topic.value
            ).inc()
            logger.info(
                "published %s event_id=%s topic=%s", envelope.event_type, envelope.event_id, topic
            )
            return True
        except Exception as error:
            logger.warning("failed to publish outbox row %s: %s", row["id"], error)
            metrics.events_failed_total.labels(
                event_type=str(row.get("event_type", "unknown"))
            ).inc()
            await session.execute(
                MARK_FAILED, {"id": row["id"], "error": f"{type(error).__name__}: {error}"}
            )
            return False


async def main() -> None:
    relay = Relay()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, relay.request_stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: relay.request_stop())

    await relay.start()
    try:
        await relay.run()
    finally:
        await relay.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
