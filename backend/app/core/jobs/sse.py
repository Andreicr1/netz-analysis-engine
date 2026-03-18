"""
SSE Stream Generator — Netz Analysis Engine
=============================================

Uses sse-starlette for proper SSE wire protocol (event framing, id, retry, ping).
Pattern from Wealth OS routers/risk.py:179-232.

Uses fetch() + ReadableStream on the frontend (not EventSource)
because EventSource cannot send Authorization headers.
"""

from __future__ import annotations

import json
import logging

from fastapi import Request
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from app.core.jobs.tracker import TERMINAL_EVENT_TYPES, subscribe_job

logger = logging.getLogger(__name__)


async def create_job_stream(request: Request, job_id: str) -> EventSourceResponse:
    """Create an SSE response that streams job progress events.

    Heartbeat every 15s keeps connection alive (Azure Container Apps idle timeout = 30s).
    """

    async def event_generator():
        async for msg in subscribe_job(job_id):
            if await request.is_disconnected():
                logger.info("SSE client disconnected for job %s", job_id)
                break

            event_type = msg.pop("event", "message")
            yield ServerSentEvent(
                data=json.dumps(msg),
                event=event_type,
            )

            if event_type in TERMINAL_EVENT_TYPES:
                break

    return EventSourceResponse(
        event_generator(),
        ping=15,
        ping_message_factory=lambda: ServerSentEvent(comment="keep-alive"),
    )
