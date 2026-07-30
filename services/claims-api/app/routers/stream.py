"""WebSocket endpoint for live claim updates.

Auth happens in the first message, not the URL. The browser WebSocket API cannot
set request headers, so the two common alternatives are a token in the query
string or a first-message handshake. Query strings end up in access logs, proxy
logs, and browser history; a first message does not. The cost is a few lines of
handshake code and a timeout to stop unauthenticated sockets lingering.
"""

import asyncio
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.tokens import TokenError, decode_access_token
from app.services import user_service
from app.ws.manager import Connection, manager

logger = logging.getLogger("claims-api.ws")
router = APIRouter(tags=["stream"])

AUTH_TIMEOUT_SECONDS = 5.0


async def _authenticate(websocket: WebSocket, session: AsyncSession) -> Connection | None:
    try:
        payload = await asyncio.wait_for(websocket.receive_json(), timeout=AUTH_TIMEOUT_SECONDS)
    except TimeoutError:
        await websocket.close(code=4408, reason="Authentication timeout")
        return None
    except Exception:
        await websocket.close(code=4400, reason="Malformed handshake")
        return None

    token = payload.get("token") if isinstance(payload, dict) else None
    if not token:
        await websocket.close(code=4401, reason="Missing token")
        return None

    try:
        claims = decode_access_token(token)
        user_id = uuid.UUID(claims["sub"])
    except (TokenError, KeyError, ValueError):
        await websocket.close(code=4401, reason="Invalid token")
        return None

    user = await user_service.get_by_id(session, user_id)
    if user is None or not user.is_active:
        await websocket.close(code=4401, reason="Unknown or inactive user")
        return None

    return Connection(socket=websocket, user_id=str(user.id), role=user.role)


@router.websocket("/ws/claims")
async def claims_stream(
    websocket: WebSocket,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    await websocket.accept()

    connection = await _authenticate(websocket, session)
    if connection is None:
        return

    await manager.register(connection)
    await websocket.send_json({"type": "connected", "role": connection.role})

    try:
        while True:
            # The client sends nothing but heartbeats. Reading keeps the
            # coroutine alive and surfaces disconnects promptly.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("ws error for user=%s", connection.user_id)
    finally:
        await manager.unregister(connection)
