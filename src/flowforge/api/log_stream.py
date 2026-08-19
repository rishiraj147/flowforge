"""WebSocket log streaming endpoints."""

import asyncio
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketException
from starlette.websockets import WebSocketDisconnect

from flowforge.authz import Permission, has_permission
from flowforge.config import Settings
from flowforge.deps import resolve_user_from_token
from flowforge.log_stream import stream_execution_logs
from flowforge.models import Execution
from flowforge.services import execution_service

router = APIRouter(tags=["log-stream"])


@router.websocket("/ws/executions/{execution_id}/logs")
async def websocket_execution_logs(
    websocket: WebSocket,
    execution_id: uuid.UUID,
    token: str = Query(..., min_length=1),
) -> None:
    """Stream task-run logs for an execution in real time.

  Auth: pass JWT access token as query param `token` (browser WebSockets
  cannot set Authorization headers in all environments).

  Workers PUBLISH to Redis; this handler SUBSCRIBES and forwards JSON events
  to the browser. Heartbeats keep the connection alive through proxies.
    """

    settings: Settings = websocket.app.state.settings
    sessionmaker = websocket.app.state.sessionmaker

    async with sessionmaker() as session:
        user = await resolve_user_from_token(session, settings, token)

        if user is None or not has_permission(user.role, Permission.EXECUTIONS_READ):
            raise WebSocketException(code=1008, reason="Unauthorized")

        execution = await execution_service.get_execution(session, execution_id)

        if execution is None:
            raise WebSocketException(code=1008, reason="Execution not found")

    await websocket.accept()

    try:
        await stream_execution_logs(websocket, execution_id, settings)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
