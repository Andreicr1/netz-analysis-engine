# DEPRECATED 2026-03-18: Azure Service Bus replaced by Redis pub/sub + BackgroundTasks (Milestone 2).
# Retained for rollback capability only.
"""Azure Service Bus producer — enqueue pipeline jobs.

DEPRECATED: Use Redis pub/sub + BackgroundTasks instead. This module is
kept for rollback capability only. All send operations were already no-ops
in local dev (when SERVICE_BUS_NAMESPACE is not set).
"""
from __future__ import annotations

import json
import logging
import uuid
import warnings
from datetime import UTC, datetime

from app.core.config import settings

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    """Lazy-init the ServiceBusClient singleton."""
    global _client
    if _client is not None:
        return _client

    ns = getattr(settings, "SERVICE_BUS_NAMESPACE", None)
    if not ns:
        logger.warning(
            "SERVICE_BUS_NAMESPACE not configured — Service Bus operations "
            "will be skipped (local dev mode).",
        )
        return None

    from azure.identity import DefaultAzureCredential
    from azure.servicebus import ServiceBusClient

    _client = ServiceBusClient(
        fully_qualified_namespace=ns,
        credential=DefaultAzureCredential(),
    )
    return _client


def _build_message(payload: dict, stage: str | None = None) -> dict:
    """Wrap payload in the standard job envelope."""
    return {
        "job_id": str(uuid.uuid4()),
        "stage": stage or "unknown",
        "fund_id": payload.get("fund_id"),
        "payload": payload,
        "triggered_by": payload.get("triggered_by"),
        "enqueued_at": datetime.now(UTC).isoformat(),
        "attempt": 1,
    }


def send_to_topic(topic: str, payload: dict, *, stage: str) -> str | None:
    """Publish a message to a Service Bus topic.

    DEPRECATED: Use Redis pub/sub + BackgroundTasks instead.

    Returns the ``job_id`` on success, or ``None`` if Service Bus is
    not configured.
    """
    warnings.warn(
        "servicebus_client.send_to_topic is deprecated — use Redis pub/sub + BackgroundTasks",
        DeprecationWarning,
        stacklevel=2,
    )
    client = _get_client()
    if client is None:
        logger.warning("Service Bus not available — skipping send_to_topic(%s)", topic)
        return None

    from azure.servicebus import ServiceBusMessage

    envelope = _build_message(payload, stage)
    job_id = envelope["job_id"]

    with client.get_topic_sender(topic) as sender:
        msg = ServiceBusMessage(
            body=json.dumps(envelope),
            application_properties={"stage": stage},
            subject=stage,
            message_id=job_id,
        )
        sender.send_messages(msg)

    logger.info(
        "Enqueued job %s to topic=%s stage=%s", job_id, topic, stage,
    )
    return job_id


def send_to_queue(queue: str, payload: dict, *, stage: str = "memo") -> str | None:
    """Publish a message to a Service Bus queue.

    DEPRECATED: Use Redis pub/sub + BackgroundTasks instead.

    Returns the ``job_id`` on success, or ``None`` if Service Bus is
    not configured.
    """
    warnings.warn(
        "servicebus_client.send_to_queue is deprecated — use Redis pub/sub + BackgroundTasks",
        DeprecationWarning,
        stacklevel=2,
    )
    client = _get_client()
    if client is None:
        logger.warning("Service Bus not available — skipping send_to_queue(%s)", queue)
        return None

    from azure.servicebus import ServiceBusMessage

    envelope = _build_message(payload, stage)
    job_id = envelope["job_id"]

    with client.get_queue_sender(queue) as sender:
        sender.send_messages(
            ServiceBusMessage(
                body=json.dumps(envelope),
                message_id=job_id,
            ),
        )

    logger.info("Enqueued job %s to queue=%s", job_id, queue)
    return job_id
