"""KYC screening DB model stubs.

The KYC screening tables were part of the compliance domain which has
been removed from scope. These stubs keep kyc_pipeline_screening.py
importable. The persist_kyc_screenings_to_db function will raise at
runtime if called without the backing tables.

TODO: Re-create KYC tables under the appropriate domain when KYC
screening is brought back into scope.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Placeholder classes — will raise AttributeError on instantiation
# if the backing tables don't exist. This is intentional: the screening
# pipeline gracefully handles missing DB persistence.


class _StubModel:
    """Minimal stub that logs a warning when instantiated."""

    def __init__(self, **kwargs):
        logger.warning(
            "KYC model stub instantiated — compliance domain removed from scope. "
            "KYC screening results will NOT be persisted to the database.",
        )
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.id = None


class KYCScreening(_StubModel):
    pass


class KYCScreeningMatch(_StubModel):
    pass
