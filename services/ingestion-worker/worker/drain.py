"""One-shot consumer: drain the claim topic, process each event once, exit.

Demonstrates the idempotency contract. Kafka guarantees at-least-once delivery,
so the same event can arrive more than once. Writing event_id into
claims.processed_events inside the same transaction as the side effect turns
at-least-once into effectively-once.

Run with --replay to rewind this consumer group to the start of the topic. Every
event is redelivered; none should be processed a second time.
"""

import asyncio
import logging
import sys

from aiokafka import AIOKafkaConsumer
from claims_events import EventEnvelope, Topic
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from worker.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
logger = logging.getLogger("drain")

settings = get_settings()

CLAIM_EVENT = text("""
    INSERT INTO claims.processed_events (event_id, consumer_group)
    VALUES (:event_id, :consumer_group)
    ON CONFLICT (event_id, consumer_group) DO NOTHING
    RETURNING event_id
""")


async def main(replay: bool) -> None:
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    consumer = AIOKafkaConsumer(
        Topic.CLAIM.value,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.consumer_group,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await consumer.start()

    processed = 0
    duplicates = 0
    sought = not replay

    try:
        while True:
            batches = await consumer.getmany(timeout_ms=settings.idle_timeout_ms)

            if not sought:
                assignment = consumer.assignment()
                if assignment:
                    await consumer.seek_to_beginning(*assignment)
                    sought = True
                    logger.info("rewound %d partition(s) to the beginning", len(assignment))
                    continue

            if not batches:
                break

            for _partition, messages in batches.items():
                for message in messages:
                    envelope = EventEnvelope.from_json(message.value)

                    async with session_factory() as session:
                        async with session.begin():
                            claimed = await session.execute(
                                CLAIM_EVENT,
                                {
                                    "event_id": str(envelope.event_id),
                                    "consumer_group": settings.consumer_group,
                                },
                            )
                            if claimed.scalar_one_or_none() is None:
                                duplicates += 1
                                logger.info(
                                    "SKIP  duplicate %s event_id=%s",
                                    envelope.event_type,
                                    envelope.event_id,
                                )
                                continue

                            # Phase 6 puts the real side effect here, in this
                            # same transaction as the processed_events insert.
                            processed += 1
                            logger.info(
                                "OK    %s event_id=%s claim=%s",
                                envelope.event_type,
                                envelope.event_id,
                                envelope.payload.get("claim_number"),
                            )

            # Offsets commit only after the database transaction succeeds.
            # Committing first would lose events on a crash; committing after
            # means a crash causes redelivery, which processed_events absorbs.
            await consumer.commit()
    finally:
        await consumer.stop()
        await engine.dispose()

    logger.info("done: %d processed, %d duplicates skipped", processed, duplicates)


if __name__ == "__main__":
    asyncio.run(main(replay="--replay" in sys.argv))
