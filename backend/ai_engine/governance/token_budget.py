"""Token-usage telemetry for AI engine calls.

Records cumulative token usage per deal for audit and cost visibility.
No hard caps — generation quality takes precedence over cost savings
given the low per-token cost of GPT-4o / GPT-4o-mini.

Limits are ONLY the upstream model TPM ceilings (800 K for gpt-4o,
4 M for gpt-4o-mini).  The tracker here is purely observational.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reference: model-level ceilings (informational only)
# ---------------------------------------------------------------------------
GPT4O_TPM     = 800_000   # gpt-4o  – 800 K tokens/min
GPT4O_MINI_TPM = 4_000_000 # gpt-4o-mini – 4 M tokens/min

MAX_TOKENS_SINGLE_CALL = 25_000
"""Advisory max output tokens for any single OpenAI call (for logging)."""


# ---------------------------------------------------------------------------
# Exception (kept for backward compat — never raised in normal flow)
# ---------------------------------------------------------------------------
class TokenBudgetExceeded(RuntimeError):
    """Retained for backward compatibility.  Never raised by the tracker."""


# ---------------------------------------------------------------------------
# Usage tracker (telemetry only — no enforcement)
# ---------------------------------------------------------------------------
@dataclass
class TokenBudgetTracker:
    """Accumulates token usage across multiple calls within a pipeline run.

    This tracker is **observational only** — it never blocks calls.
    All data is recorded for cost dashboards and audit logs.
    """

    context: str = "deep_review"
    enforce: bool = False          # kept for call-site compat; always ignored
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    call_count: int = 0
    _log: list[dict] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    # -- pre-flight: no-op (no enforcement) ---------------------------------
    def check_before_call(self, *, label: str = "") -> None:
        """No-op.  Kept so callers don't need changes."""
        pass

    # -- post-call recording ------------------------------------------------
    def record(self, *, input_tokens: int = 0, output_tokens: int = 0,
               label: str = "") -> None:
        """Record a completed call for telemetry.

        Thread-safe: protected by ``threading.Lock`` for concurrent access
        from ``asyncio.to_thread`` calls during async pipeline execution.
        """
        with self._lock:
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            self.call_count += 1
            self._log.append({
                "call": self.call_count,
                "label": label,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cumulative": self.total_tokens,
            })

            if output_tokens > MAX_TOKENS_SINGLE_CALL:
                logger.warning("TOKEN_USAGE_SINGLE_CALL_LARGE", extra={
                    "context": self.context, "label": label,
                    "output_tokens": output_tokens,
                    "advisory_limit": MAX_TOKENS_SINGLE_CALL,
                })

            logger.debug(
                "TOKEN_USAGE_RECORD context=%s label=%s cumulative=%d",
                self.context, label, self.total_tokens,
            )

    def summary(self) -> dict:
        """Return a summary dict for audit logging."""
        return {
            "context": self.context,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "call_count": self.call_count,
        }
