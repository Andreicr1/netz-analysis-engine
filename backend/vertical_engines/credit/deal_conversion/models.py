"""Deal conversion leaf models — result DTO.

LEAF MODULE — zero sibling imports within the deal_conversion package.

Error contract: raises-on-failure (transactional engine).
ValueError on validation gates (deal already converted, intelligence not READY).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConversionResult:
    portfolio_deal_id: uuid.UUID
    active_investment_id: uuid.UUID
    pipeline_deal_id: uuid.UUID
    status: str = "converted"
