"""Netz runtime kit — stability primitives.

Part of the Stability Guardrails charter. See
``docs/reference/stability-guardrails.md`` and
``docs/superpowers/specs/2026-04-07-stability-guardrails-design.md``
for the design and the six non-negotiable principles (P1 Bounded,
P2 Batched, P3 Isolated, P4 Lifecycle, P5 Idempotent, P6 Fault-Tolerant).

Primitives landed in this module MUST be:
- Isolated (no dependency on any app.domains.* package)
- Fully tested (>= 95% coverage)
- Documented with behavior guarantees, not just signatures
- Importable without side-effects
"""

from app.core.runtime.broadcaster import (
    BroadcasterClosedError,
    BroadcasterConfig,
    BroadcasterFullError,
    BroadcasterMetrics,
    ConnectionId,
    FanoutResult,
    RateLimitedBroadcaster,
    make_connection_id,
)
from app.core.runtime.outbound_channel import (
    BoundedOutboundChannel,
    ChannelConfig,
    ChannelMetrics,
    DropPolicy,
)

__all__ = [
    "BoundedOutboundChannel",
    "BroadcasterClosedError",
    "BroadcasterConfig",
    "BroadcasterFullError",
    "BroadcasterMetrics",
    "ChannelConfig",
    "ChannelMetrics",
    "ConnectionId",
    "DropPolicy",
    "FanoutResult",
    "RateLimitedBroadcaster",
    "make_connection_id",
]
