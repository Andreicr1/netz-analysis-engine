from __future__ import annotations

from app.domains.credit.deals.enums import DealType, RejectionCode


def run_minimum_qualification(deal) -> tuple[bool, str, RejectionCode | None]:
    """Deterministic minimum mandate filters for the Netz Private Credit Fund.

    Mandate-qualifying deal types:
      - DIRECT_LOAN   — core mandate
      - FUND_INVESTMENT — permitted
      - SPV_NOTE      — permitted

    Non-qualifying:
      - EQUITY_STAKE  — out of mandate (pure equity, no credit component)
    """

    deal_type_value = deal.deal_type.value if hasattr(deal.deal_type, "value") else str(deal.deal_type)

    qualifying_types = {
        DealType.DIRECT_LOAN.value,
        DealType.FUND_INVESTMENT.value,
        DealType.SPV_NOTE.value,
    }

    if deal_type_value in qualifying_types:
        return True, f"{deal_type_value} meets minimum mandate filters.", None

    return False, f"Deal rejected: {deal_type_value} is out of mandate.", RejectionCode.OUT_OF_MANDATE

