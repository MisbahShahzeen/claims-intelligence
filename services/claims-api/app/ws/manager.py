"""In-memory registry of live WebSocket connections.

Per-process, deliberately. Each API replica holds only its own connections and
receives every event via its own Kafka consumer group, so fanout across replicas
needs no shared state and no Redis backplane. The cost is that a replica restart
drops its connections - which the client's reconnect logic handles.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket

from app.core import metrics

logger = logging.getLogger("claims-api.ws")


@dataclass(frozen=True)
class Connection:
    socket: WebSocket
    user_id: str
    role: str


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[Connection] = set()
        self._lock = asyncio.Lock()

    @property
    def count(self) -> int:
        return len(self._connections)

    async def register(self, connection: Connection) -> None:
        async with self._lock:
            self._connections.add(connection)
            metrics.websocket_connections.set(len(self._connections))
        logger.info(
            "ws connected user=%s role=%s (%d live)",
            connection.user_id,
            connection.role,
            len(self._connections),
        )

    async def unregister(self, connection: Connection) -> None:
        async with self._lock:
            self._connections.discard(connection)
            metrics.websocket_connections.set(len(self._connections))
        logger.info("ws disconnected user=%s (%d live)", connection.user_id, len(self._connections))

    async def broadcast(self, message: dict[str, Any]) -> int:
        """Send to every live connection. Returns how many received it.

        A send can fail if the peer vanished between the last poll and now, so
        failures are collected and pruned rather than allowed to abort the loop.
        One dead socket must not stop the others from being notified.
        """
        async with self._lock:
            targets = list(self._connections)

        if not targets:
            return 0

        dead: list[Connection] = []
        delivered = 0
        for connection in targets:
            try:
                await connection.socket.send_json(message)
                delivered += 1
            except Exception:
                dead.append(connection)

        if dead:
            async with self._lock:
                for connection in dead:
                    self._connections.discard(connection)
            logger.info("pruned %d dead connection(s)", len(dead))

        return delivered


manager = ConnectionManager()
