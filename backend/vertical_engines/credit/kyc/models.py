"""KYC screening DB model stubs.

Leaf module — zero sibling imports.

The KYC screening tables were part of the compliance domain which has
been removed from scope. These stubs keep the kyc package importable.
The persist_kyc_screenings_to_db function will raise at runtime if
called without the backing tables.
"""
from __future__ import annotations

import structlog

logger = structlog.get_logger()


class _StubModel:
    """Minimal stub that logs a warning when instantiated."""

    def __init__(self, **kwargs):
        logger.warning(
            "kyc_model_stub_instantiated",
            note="compliance domain removed from scope — KYC results will NOT be persisted",
        )
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.id = None


class KYCScreening(_StubModel):
    pass


class KYCScreeningMatch(_StubModel):
    pass
