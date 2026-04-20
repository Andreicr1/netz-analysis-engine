"""Wealth attribution — portfolio and fund-level.

Portfolio (Brinson-Fachler, policy benchmark): :class:`AttributionService`.
Fund (rail cascade: returns-based today; holdings / proxy / IPCA later):
:func:`compute_fund_attribution`.
"""

from vertical_engines.wealth.attribution.models import (
    AttributionRequest,
    BlockAttribution,
    FundAttributionResult,
    PortfolioAttributionResult,
    RailBadge,
    ReturnsBasedResult,
    StyleExposure,
)
from vertical_engines.wealth.attribution.service import (
    AttributionService,
    compute_fund_attribution,
)

__all__ = [
    "AttributionRequest",
    "AttributionService",
    "BlockAttribution",
    "FundAttributionResult",
    "PortfolioAttributionResult",
    "RailBadge",
    "ReturnsBasedResult",
    "StyleExposure",
    "compute_fund_attribution",
]
