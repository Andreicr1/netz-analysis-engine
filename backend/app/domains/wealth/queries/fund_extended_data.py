"""Hydrate per-fund-type extended data from dedicated SEC/ESMA tables.

Called by the fact-sheet endpoint to populate the polymorphic
``FundExtendedData`` discriminated union.  Runs inside
``asyncio.to_thread`` on a sync session (same pattern as
``gather_fund_enrichment``).

All ``_pct`` values are returned as **pure decimal fractions**
(0.015 = 1.5 %).  No ×100 conversion happens here — the frontend
``formatPercent()`` handles display.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.orm import Session

from app.domains.wealth.schemas.instrument import (
    BDCExtendedData,
    ETFExtendedData,
    MMFExtendedData,
    MutualFundExtendedData,
    PrivateFundExtendedData,
    UCITSExtendedData,
)

logger = structlog.get_logger(__name__)

# Map mv_unified_funds.fund_type → universe branch key used in this module.
_FUND_TYPE_TO_UNIVERSE: dict[str, str] = {
    "mutual_fund": "registered_us",
    "closed_end_fund": "registered_us",
    "interval_fund": "registered_us",
    "etf": "etf",
    "bdc": "bdc",
    "money_market": "money_market",
}


def _float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    return float(v)


# ── Mutual Fund / Closed-End / Interval ──────────────────────────────────


def _hydrate_mutual_fund(
    sync_db: Session,
    *,
    external_id: str,
    series_id: str | None,
) -> MutualFundExtendedData | None:
    from app.shared.models import SecFundClass, SecRegisteredFund

    fund_cik: str | None = None

    # Try direct CIK
    row = sync_db.query(SecRegisteredFund).filter(SecRegisteredFund.cik == external_id).first()
    if row:
        fund_cik = external_id
    else:
        # Try via class_id or series_id
        fc = (
            sync_db.query(SecFundClass.cik)
            .filter(
                (SecFundClass.class_id == external_id)
                | (SecFundClass.series_id == external_id)
            )
            .first()
        )
        if fc:
            fund_cik = fc[0]
            row = sync_db.query(SecRegisteredFund).filter(SecRegisteredFund.cik == fund_cik).first()

    if not row:
        return None

    # Prospectus stats (RR1) — prefer series_id match
    from app.domains.wealth.models.prospectus import SecFundProspectusStats

    lookup_series = series_id or row.series_id
    ps = None
    if lookup_series:
        ps = (
            sync_db.query(SecFundProspectusStats)
            .filter(SecFundProspectusStats.series_id == lookup_series)
            .first()
        )

    return MutualFundExtendedData(
        # N-CEN classification
        is_index=row.is_index,
        is_non_diversified=row.is_non_diversified,
        is_target_date=row.is_target_date,
        is_fund_of_fund=row.is_fund_of_fund,
        is_master_feeder=row.is_master_feeder,
        lei=row.lei,
        # Costs
        management_fee_pct=_float_or_none(row.management_fee),
        net_operating_expenses_pct=_float_or_none(row.net_operating_expenses),
        has_expense_limit=row.has_expense_limit,
        has_expense_waived=row.has_expense_waived,
        # Performance
        return_before_fees_pct=_float_or_none(row.return_before_fees),
        return_after_fees_pct=_float_or_none(row.return_after_fees),
        return_stdv_before_fees_pct=_float_or_none(row.return_stdv_before_fees),
        return_stdv_after_fees_pct=_float_or_none(row.return_stdv_after_fees),
        # AUM & NAV
        monthly_avg_net_assets=_float_or_none(row.monthly_avg_net_assets),
        daily_avg_net_assets=_float_or_none(row.daily_avg_net_assets),
        nav_per_share=_float_or_none(row.nav_per_share),
        market_price_per_share=_float_or_none(row.market_price_per_share),
        # Operational
        is_sec_lending_authorized=row.is_sec_lending_authorized,
        did_lend_securities=row.did_lend_securities,
        has_line_of_credit=row.has_line_of_credit,
        has_interfund_borrowing=row.has_interfund_borrowing,
        has_swing_pricing=row.has_swing_pricing,
        did_pay_broker_research=row.did_pay_broker_research,
        # Prospectus RR1
        fee_waiver_pct=_float_or_none(ps.fee_waiver_pct) if ps else None,
        distribution_12b1_pct=_float_or_none(ps.distribution_12b1_pct) if ps else None,
        acquired_fund_fees_pct=_float_or_none(ps.acquired_fund_fees_pct) if ps else None,
        other_expenses_pct=_float_or_none(ps.other_expenses_pct) if ps else None,
        portfolio_turnover_pct=_float_or_none(ps.portfolio_turnover_pct) if ps else None,
        expense_example_1y=_float_or_none(ps.expense_example_1y) if ps else None,
        expense_example_3y=_float_or_none(ps.expense_example_3y) if ps else None,
        expense_example_5y=_float_or_none(ps.expense_example_5y) if ps else None,
        expense_example_10y=_float_or_none(ps.expense_example_10y) if ps else None,
        bar_chart_best_qtr_pct=_float_or_none(ps.bar_chart_best_qtr_pct) if ps else None,
        bar_chart_worst_qtr_pct=_float_or_none(ps.bar_chart_worst_qtr_pct) if ps else None,
        # Accounts
        total_shareholder_accounts=row.total_shareholder_accounts,
        # N-CEN metadata
        ncen_report_date=row.ncen_report_date,
    )


# ── ETF ──────────────────────────────────────────────────────────────────


def _hydrate_etf(
    sync_db: Session,
    *,
    external_id: str,
) -> ETFExtendedData | None:
    from app.shared.models import SecEtf

    row = sync_db.query(SecEtf).filter(SecEtf.series_id == external_id).first()
    if not row:
        # Try by ticker as fallback
        row = sync_db.query(SecEtf).filter(SecEtf.ticker == external_id).first()
    if not row:
        return None

    return ETFExtendedData(
        index_tracked=row.index_tracked,
        tracking_difference_gross_pct=_float_or_none(row.tracking_difference_gross),
        tracking_difference_net_pct=_float_or_none(row.tracking_difference_net),
        is_index=row.is_index,
        asset_class=row.asset_class,
        creation_unit_size=row.creation_unit_size,
        is_in_kind_etf=row.is_in_kind_etf,
        pct_in_kind_creation=_float_or_none(row.pct_in_kind_creation),
        pct_in_kind_redemption=_float_or_none(row.pct_in_kind_redemption),
        management_fee_pct=_float_or_none(row.management_fee),
        net_operating_expenses_pct=_float_or_none(row.net_operating_expenses),
        return_before_fees_pct=_float_or_none(row.return_before_fees),
        return_after_fees_pct=_float_or_none(row.return_after_fees),
        monthly_avg_net_assets=_float_or_none(row.monthly_avg_net_assets),
        daily_avg_net_assets=_float_or_none(row.daily_avg_net_assets),
        nav_per_share=_float_or_none(row.nav_per_share),
        market_price_per_share=_float_or_none(row.market_price_per_share),
        is_sec_lending_authorized=row.is_sec_lending_authorized,
        did_lend_securities=row.did_lend_securities,
        has_expense_limit=row.has_expense_limit,
        ncen_report_date=row.ncen_report_date,
    )


# ── BDC ──────────────────────────────────────────────────────────────────


def _hydrate_bdc(
    sync_db: Session,
    *,
    external_id: str,
) -> BDCExtendedData | None:
    from app.shared.models import SecBdc

    row = sync_db.query(SecBdc).filter(SecBdc.series_id == external_id).first()
    if not row:
        row = sync_db.query(SecBdc).filter(SecBdc.ticker == external_id).first()
    if not row:
        return None

    return BDCExtendedData(
        investment_focus=row.investment_focus,
        is_externally_managed=row.is_externally_managed,
        management_fee_pct=_float_or_none(row.management_fee),
        net_operating_expenses_pct=_float_or_none(row.net_operating_expenses),
        return_before_fees_pct=_float_or_none(row.return_before_fees),
        return_after_fees_pct=_float_or_none(row.return_after_fees),
        monthly_avg_net_assets=_float_or_none(row.monthly_avg_net_assets),
        daily_avg_net_assets=_float_or_none(row.daily_avg_net_assets),
        nav_per_share=_float_or_none(row.nav_per_share),
        market_price_per_share=_float_or_none(row.market_price_per_share),
        is_sec_lending_authorized=row.is_sec_lending_authorized,
        has_line_of_credit=row.has_line_of_credit,
        has_interfund_borrowing=row.has_interfund_borrowing,
        ncen_report_date=row.ncen_report_date,
    )


# ── Money Market Fund ────────────────────────────────────────────────────


def _hydrate_mmf(
    sync_db: Session,
    *,
    external_id: str,
) -> MMFExtendedData | None:
    from app.shared.models import SecMoneyMarketFund

    row = (
        sync_db.query(SecMoneyMarketFund)
        .filter(SecMoneyMarketFund.series_id == external_id)
        .first()
    )
    if not row:
        return None

    return MMFExtendedData(
        mmf_category=row.mmf_category,
        is_govt_fund=row.is_govt_fund,
        is_retail=row.is_retail,
        is_exempt_retail=row.is_exempt_retail,
        weighted_avg_maturity=row.weighted_avg_maturity,
        weighted_avg_life=row.weighted_avg_life,
        seven_day_gross_yield_pct=_float_or_none(row.seven_day_gross_yield),
        net_assets=_float_or_none(row.net_assets),
        shares_outstanding=_float_or_none(row.shares_outstanding),
        total_portfolio_securities=_float_or_none(row.total_portfolio_securities),
        cash=_float_or_none(row.cash),
        pct_daily_liquid=_float_or_none(row.pct_daily_liquid_latest),
        pct_weekly_liquid=_float_or_none(row.pct_weekly_liquid_latest),
        seeks_stable_nav=row.seeks_stable_nav,
        stable_nav_price=_float_or_none(row.stable_nav_price),
        reporting_period=row.reporting_period,
        investment_adviser=row.investment_adviser,
    )


# ── Private Fund ─────────────────────────────────────────────────────────


def _hydrate_private_fund(
    sync_db: Session,
    *,
    external_id: str,
) -> PrivateFundExtendedData | None:
    from app.shared.models import SecManagerFund

    row = (
        sync_db.query(SecManagerFund)
        .filter(SecManagerFund.id == external_id)
        .first()
    )
    if not row:
        # Fallback: try fund_id
        row = (
            sync_db.query(SecManagerFund)
            .filter(SecManagerFund.fund_id == external_id)
            .first()
        )
    if not row:
        return None

    return PrivateFundExtendedData(
        sec_fund_type=row.fund_type,
        strategy_label=row.strategy_label,
        gross_asset_value=row.gross_asset_value,
        investor_count=row.investor_count,
        vintage_year=row.vintage_year,
        is_fund_of_funds=row.is_fund_of_funds,
    )


# ── UCITS ────────────────────────────────────────────────────────────────


def _hydrate_ucits(
    sync_db: Session,
    *,
    external_id: str,
) -> UCITSExtendedData | None:
    from app.shared.models import EsmaFund

    row = sync_db.query(EsmaFund).filter(EsmaFund.isin == external_id).first()
    if not row:
        return None

    return UCITSExtendedData(
        domicile=row.domicile,
        host_member_states=row.host_member_states or [],
        fund_type=row.fund_type,
        strategy_label=row.strategy_label,
        yahoo_ticker=row.yahoo_ticker,
    )


# ── Public entry point ───────────────────────────────────────────────────


def hydrate_extended_data(
    sync_db: Session,
    *,
    external_id: str,
    universe: str,
    fund_type: str,
    series_id: str | None = None,
) -> (
    MutualFundExtendedData
    | ETFExtendedData
    | BDCExtendedData
    | MMFExtendedData
    | PrivateFundExtendedData
    | UCITSExtendedData
    | None
):
    """Hydrate per-fund-type extended data from the dedicated source table.

    Parameters
    ----------
    sync_db:
        Synchronous SQLAlchemy session (runs inside ``asyncio.to_thread``).
    external_id:
        The ``mv_unified_funds.external_id`` value (CIK, series_id, UUID, or ISIN).
    universe:
        The ``mv_unified_funds.universe`` value (``registered_us``, ``private_us``, ``ucits_eu``).
    fund_type:
        The ``mv_unified_funds.fund_type`` value (``mutual_fund``, ``etf``, ``bdc``,
        ``money_market``, ``closed_end_fund``, ``interval_fund``, etc.).
    series_id:
        Optional series_id for registered_us (helps narrow prospectus lookup).

    Returns
    -------
    One of the six typed ExtendedData schemas, or ``None`` if the source
    table row was not found.
    """
    resolved = _FUND_TYPE_TO_UNIVERSE.get(fund_type, universe)

    if resolved == "etf":
        return _hydrate_etf(sync_db, external_id=external_id)

    if resolved == "bdc":
        return _hydrate_bdc(sync_db, external_id=external_id)

    if resolved == "money_market":
        return _hydrate_mmf(sync_db, external_id=external_id)

    if universe == "private_us":
        return _hydrate_private_fund(sync_db, external_id=external_id)

    if universe == "ucits_eu":
        return _hydrate_ucits(sync_db, external_id=external_id)

    # Default: registered_us mutual fund / closed-end / interval
    return _hydrate_mutual_fund(sync_db, external_id=external_id, series_id=series_id)
