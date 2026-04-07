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
from app.core.runtime.idle_bridge import (
    BridgeState,
    IdleBridgeConfig,
    IdleBridgePolicy,
    IllegalStateError,
)
from app.core.runtime.llm_gate import (
    LLMGate,
    LLMGateConfig,
    LLMGateError,
    LLMGateMetrics,
    LLMHardTimeoutError,
    LLMRateLimitError,
    LLMResponse,
    LLMUnavailableError,
)
from app.core.runtime.outbound_channel import (
    BoundedOutboundChannel,
    ChannelConfig,
    ChannelMetrics,
    DropPolicy,
)
from app.core.runtime.provider_gate import (
    ExternalProviderGate,
    GateConfig,
    GateMetrics,
    GateState,
    ProviderGateError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.core.runtime.single_flight import SingleFlightLock

__all__ = [
    "BoundedOutboundChannel",
    "BridgeState",
    "BroadcasterClosedError",
    "BroadcasterConfig",
    "BroadcasterFullError",
    "BroadcasterMetrics",
    "ChannelConfig",
    "ChannelMetrics",
    "ConnectionId",
    "DropPolicy",
    "ExternalProviderGate",
    "FanoutResult",
    "GateConfig",
    "GateMetrics",
    "GateState",
    "IdleBridgeConfig",
    "IdleBridgePolicy",
    "IllegalStateError",
    "LLMGate",
    "LLMGateConfig",
    "LLMGateError",
    "LLMGateMetrics",
    "LLMHardTimeoutError",
    "LLMRateLimitError",
    "LLMResponse",
    "LLMUnavailableError",
    "ProviderGateError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "RateLimitedBroadcaster",
    "SingleFlightLock",
    "make_connection_id",
]
