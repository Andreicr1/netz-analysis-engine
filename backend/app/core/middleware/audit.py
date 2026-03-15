"""Audit middleware — request ID generation.

Stub for Sprint 2b. Full implementation adds correlation ID middleware
for request tracing in Sprint 3.
"""

from __future__ import annotations

import uuid


def get_request_id() -> str:
    """Return a unique request ID for audit correlation."""
    return str(uuid.uuid4())
