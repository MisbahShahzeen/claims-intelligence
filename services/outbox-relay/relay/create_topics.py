"""Create topics explicitly. Auto-creation is off in docker-compose on purpose."""

import asyncio
import logging

from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from claims_events import TOPICS

from relay.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("create-topics")


async def main() -> None:
    settings = get_settings()
    admin = AIOKafkaAdminClient(bootstrap_servers=settings.kafka_bootstrap_servers)
    await admin.start()
    try:
        existing = set(await admin.list_topics())
        wanted = [
            NewTopic(name=str(name), num_partitions=partitions, replication_factor=1)
            for name, partitions in TOPICS.items()
            if str(name) not in existing
        ]
        if not wanted:
            logger.info("all topics already exist")
            return
        await admin.create_topics(wanted)
        for topic in wanted:
            logger.info("created %s (%d partitions)", topic.name, topic.num_partitions)
    finally:
        await admin.close()


if __name__ == "__main__":
    asyncio.run(main())
