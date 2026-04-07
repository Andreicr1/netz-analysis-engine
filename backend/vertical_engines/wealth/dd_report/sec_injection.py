"""SEC Injection — sync SEC data queries for DD Report evidence.

Gathers 13F holdings (sector weights, drift detection) and ADV manager
profile (AUM history, compliance disclosures, fee structure, team) from
global SEC tables. All queries are sync (matches DD report engine context
inside asyncio.to_thread()).

SEC tables are global (no organization_id, no RLS). Linkage from Fund to
SEC is via manager_name → sec_managers.firm_name (case-insensitive).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import structlog
from sqlalchemy import func, text
from sqlalchemy.orm import Session

logger = structlog.get_logger()

# Sector weight change threshold (pp) to flag drift between quarters.
_DRIFT_THRESHOLD_PP = 0.05

# N-PORT issuerCat → human-readable labels.
# issuerCat describes the ISSUER type (corporate, government, etc.), not the
# instrument type.  For debt holdings, "CORP" = corporate bonds.  For equity
# holdings, "CORP" = corporate equity (stocks).  The asset_class-aware
# label_nport_sector() function resolves this ambiguity.
NPORT_ISSUER_LABELS: dict[str, str] = {
    "CORP": "Corporate",
    "UST": "US Treasury",
    "USGA": "US Govt Agency",
    "USGSE": "US Govt Sponsored",
    "NUSS": "Non-US Sovereign",
    "MUN": "Municipal",
    "MBS": "Mortgage-Backed",
    "ABS": "Asset-Backed",
    "CMO": "Collateralized Mortgage",
    "FGN": "Foreign Govt",
    "LOAN": "Bank Loans",
    "MM": "Money Market",
    "EC": "Equity",
    "PF": "Private Fund",
    "RF": "Registered Fund",
    "FI": "Fixed Income",
    "OT": "Other",
    "OTHER": "Other",
}

# N-PORT assetCat codes that indicate equity instruments
_EQUITY_ASSET_CATS = {"EC", "STIV"}


def label_nport_sector(raw: str | None, asset_class: str | None = None) -> str:
    """Map N-PORT issuerCat code to readable label.

    If the ``sector`` column already contains an enriched GICS label
    (e.g. "Technology", "Healthcare"), returns it as-is.  Only raw
    issuerCat codes (EC, CORP, UST, etc.) are remapped.

    When asset_class is provided, disambiguates issuerCat — e.g. "CORP" with
    asset_class "EC" becomes "Corporate Equity" instead of "Corporate Bonds".
    """
    if not raw:
        return "Other"
    code = raw.strip().upper()

    # If the value is NOT a known issuerCat code, it's already an enriched
    # GICS sector label — return the original casing as-is.
    if code not in NPORT_ISSUER_LABELS:
        return raw.strip()

    # Disambiguate "Corporate" based on asset class
    if code == "CORP" and asset_class:
        ac = asset_class.strip().upper()
        if ac in _EQUITY_ASSET_CATS:
            return "Equity"
        return "Corporate Bonds"

    return NPORT_ISSUER_LABELS[code]


def _batch_gics_lookup(
    db: Session,
    cusips: list[str],
) -> dict[str, str]:
    """Batch lookup GICS sectors from sec_cusip_ticker_map for given CUSIPs.

    Returns a dict mapping cusip → gics_sector for CUSIPs that have a
    non-null gics_sector. Used to enrich equity holdings in N-PORT data
    with granular GICS labels instead of generic "Equity" issuerCat.
    """
    if not cusips:
        return {}
    try:
        from app.shared.models import SecCusipTickerMap

        rows = (
            db.query(SecCusipTickerMap.cusip, SecCusipTickerMap.gics_sector)
            .filter(
                SecCusipTickerMap.cusip.in_(cusips),
                SecCusipTickerMap.gics_sector.isnot(None),
            )
            .all()
        )
        return {r.cusip: r.gics_sector for r in rows}
    except Exception:
        logger.exception("gics_batch_lookup_failed", cusip_count=len(cusips))
        return {}


def _resolve_sector(
    holding: Any,
    cusip_to_gics: dict[str, str],
) -> str:
    """Resolve sector label for an N-PORT holding.

    For equity holdings (asset_class in EC/STIV), uses GICS sector from
    cusip_to_gics if available. Falls back to label_nport_sector() for
    non-equity or when GICS is not available.
    """
    ac = (holding.asset_class or "").strip().upper()
    if ac in _EQUITY_ASSET_CATS and holding.cusip:
        gics = cusip_to_gics.get(holding.cusip)
        if gics:
            return gics
    return label_nport_sector(holding.sector, holding.asset_class)


def gather_sec_13f_data(
    db: Session,
    *,
    manager_name: str | None,
    cik: str | None = None,
) -> dict[str, Any]:
    """Gather 13F sector allocation and drift data for a fund manager.

    Returns dict with keys: thirteenf_available, sector_weights,
    drift_detected, drift_quarters. Empty dict on error or no data.

    Parameters
    ----------
    db : Session
        Sync database session.
    manager_name : str | None
        Fund manager name for SEC linkage.
    cik : str | None
        Direct CIK override (skips manager_name lookup).

    """
    if not cik and not manager_name:
        return {}

    try:
        resolved_cik = cik or _resolve_cik(db, manager_name)
        if not resolved_cik:
            return {}

        from app.shared.models import Sec13fHolding

        # Find available report dates (most recent 8 quarters)
        lookback = date.today() - timedelta(days=8 * 92)
        dates_result = (
            db.query(Sec13fHolding.report_date)
            .filter(
                Sec13fHolding.cik == resolved_cik,
                Sec13fHolding.report_date >= lookback,
            )
            .distinct()
            .order_by(Sec13fHolding.report_date.desc())
            .limit(8)
            .all()
        )

        if not dates_result:
            return {}

        report_dates = [r[0] for r in dates_result]
        latest_date = report_dates[0]

        # Sector aggregation for latest + previous quarter in single query
        compare_dates = report_dates[:2]
        weights_by_date = _compute_sector_weights_batch(db, resolved_cik, compare_dates)
        sector_weights = weights_by_date.get(latest_date, {})

        # Drift detection: compare two most recent quarters
        drift_detected = False
        if len(compare_dates) >= 2:
            prev_weights = weights_by_date.get(compare_dates[1], {})
            if sector_weights and prev_weights:
                drift_detected = _detect_sector_drift(sector_weights, prev_weights)

        return {
            "thirteenf_available": True,
            "sector_weights": sector_weights,
            "drift_detected": drift_detected,
            "drift_quarters": len(report_dates),
        }

    except Exception:
        logger.exception("sec_13f_gather_failed", manager_name=manager_name)
        return {}


def gather_sec_nport_data(
    db: Session,
    *,
    fund_cik: str | None,
    series_id: str | None = None,
    holdings_limit: int = 10,
) -> dict[str, Any]:
    """Gather N-PORT fund-level holdings for DD report evidence.

    DB-only reads from sec_nport_holdings and sec_fund_style_snapshots.
    Returns dict with sector_weights, asset_allocation, top_holdings,
    report_date, fund_style, style_drift_detected. Empty dict if no data.

    Parameters
    ----------
    db : Session
        Sync database session.
    fund_cik : str | None
        Fund CIK from sec_registered_funds (N-PORT filer).
    series_id : str | None
        Series ID to filter holdings for umbrella CIKs with multiple series.
        When provided, only holdings tagged with this series are returned.
    holdings_limit : int
        Number of top holdings to return (default 10).

    """
    if not fund_cik:
        return {}

    try:
        from app.shared.models import SecFundStyleSnapshot, SecNportHolding

        # Build series filter for umbrella CIKs
        series_filter = [
            SecNportHolding.cik == fund_cik,
        ]
        if series_id:
            series_filter.append(SecNportHolding.series_id == series_id)

        # Find the 2 most recent report dates for this fund
        lookback = date.today() - timedelta(days=400)  # ~13 months
        dates_result = (
            db.query(SecNportHolding.report_date)
            .filter(
                *series_filter,
                SecNportHolding.report_date >= lookback,
            )
            .distinct()
            .order_by(SecNportHolding.report_date.desc())
            .limit(2)
            .all()
        )

        if not dates_result:
            return {}

        report_dates = [r[0] for r in dates_result]
        latest_date = report_dates[0]

        # Get all holdings for the latest report date
        holdings = (
            db.query(SecNportHolding)
            .filter(
                *series_filter,
                SecNportHolding.report_date == latest_date,
            )
            .all()
        )

        if not holdings:
            return {}

        # Batch GICS lookup for equity holdings
        equity_cusips = [
            h.cusip for h in holdings
            if h.cusip and (h.asset_class or "").strip().upper() in _EQUITY_ASSET_CATS
        ]
        cusip_to_gics = _batch_gics_lookup(db, equity_cusips)
        logger.info(
            "nport_gics_lookup",
            fund_cik=fund_cik,
            equity_cusips=len(equity_cusips),
            gics_matched=len(cusip_to_gics),
        )

        # Compute sector weights (group by sector label, sum pct_of_nav)
        sector_totals: dict[str, float] = {}
        for h in holdings:
            sector = _resolve_sector(h, cusip_to_gics)
            pct = float(h.pct_of_nav or 0)
            sector_totals[sector] = sector_totals.get(sector, 0.0) + pct

        sector_weights = {
            s: round(v / 100, 4)  # pct_of_nav is 0-100, normalize to 0-1
            for s, v in sorted(sector_totals.items(), key=lambda x: -x[1])
            if v > 0
        }

        # Compute asset allocation (equity / fixed income / cash split)
        asset_totals: dict[str, float] = {}
        for h in holdings:
            ac = (h.asset_class or "Other").strip()
            pct = float(h.pct_of_nav or 0)
            asset_totals[ac] = asset_totals.get(ac, 0.0) + pct

        asset_allocation = {
            ac: round(v / 100, 4)
            for ac, v in sorted(asset_totals.items(), key=lambda x: -x[1])
            if v > 0
        }

        # Top N holdings by pct_of_nav
        sorted_holdings = sorted(
            holdings, key=lambda h: float(h.pct_of_nav or 0), reverse=True,
        )
        top_holdings = [
            {
                "name": h.issuer_name or "Unknown",
                "cusip": h.cusip,
                "sector": _resolve_sector(h, cusip_to_gics),
                "issuer_category": h.sector,
                # Normalize human percent (7.41) → decimal fraction (0.0741)
                "pct_of_nav": round(float(h.pct_of_nav or 0) / 100.0, 6),
                "market_value": h.market_value,
            }
            for h in sorted_holdings[:holdings_limit]
        ]

        # Get latest style snapshot
        fund_style: dict[str, Any] = {}
        style_row = (
            db.query(SecFundStyleSnapshot)
            .filter(SecFundStyleSnapshot.cik == fund_cik)
            .order_by(SecFundStyleSnapshot.report_date.desc())
            .first()
        )
        if style_row:
            fund_style = {
                "style_label": style_row.style_label,
                "growth_tilt": style_row.growth_tilt,
                "equity_pct": style_row.equity_pct,
                "fi_pct": style_row.fixed_income_pct,
                "cash_pct": style_row.cash_pct,
                "confidence": style_row.confidence,
            }

        # Detect style drift: check if style_label changed in last 2 snapshots
        style_drift_detected = False
        style_history = (
            db.query(SecFundStyleSnapshot.style_label, SecFundStyleSnapshot.report_date)
            .filter(SecFundStyleSnapshot.cik == fund_cik)
            .order_by(SecFundStyleSnapshot.report_date.desc())
            .limit(2)
            .all()
        )
        if len(style_history) >= 2 and style_history[0][0] != style_history[1][0]:
            style_drift_detected = True

        # Portfolio-level insider sentiment (weighted by pct_of_nav)
        portfolio_insider_score: float | None = None
        try:
            from app.domains.wealth.services.insider_queries import (
                get_insider_sentiment_score,
            )

            insider_scores: list[tuple[float, float]] = []
            for h in sorted_holdings[:20]:  # top 20 by pct_of_nav
                # Equity holdings: match via issuer_name → ticker not in N-PORT,
                # but cusip is available. Try CUSIP prefix as issuer identifier.
                # For now use issuer_name-based ticker if available.
                score = 50.0
                if h.cusip:
                    # Try issuer_cik from cusip — not available directly,
                    # so try ticker match via issuer_name
                    score = get_insider_sentiment_score(db, issuer_cik=h.cusip[:6])
                if score == 50.0:
                    continue
                weight = float(h.pct_of_nav or 0) / 100
                if weight > 0:
                    insider_scores.append((score, weight))

            if insider_scores:
                total_weight = sum(w for _, w in insider_scores)
                if total_weight > 0:
                    portfolio_insider_score = round(
                        sum(s * w for s, w in insider_scores) / total_weight, 1,
                    )
        except Exception:
            logger.debug("nport_insider_sentiment_skipped", fund_cik=fund_cik)

        logger.info(
            "sec_nport_gathered",
            fund_cik=fund_cik,
            report_date=str(latest_date),
            holdings_count=len(holdings),
            sectors=len(sector_weights),
        )

        result_data: dict[str, Any] = {
            "report_date": str(latest_date),
            "holdings_count": len(holdings),
            "sector_weights": sector_weights,
            "asset_allocation": asset_allocation,
            "top_holdings": top_holdings,
            "fund_style": fund_style,
            "style_drift_detected": style_drift_detected,
        }
        if portfolio_insider_score is not None:
            result_data["portfolio_insider_sentiment"] = portfolio_insider_score

        return result_data

    except Exception:
        logger.exception("sec_nport_gather_failed", fund_cik=fund_cik)
        return {}


def gather_nport_sector_history(
    db: Session,
    *,
    fund_cik: str | None,
    series_id: str | None = None,
) -> list[dict[str, Any]]:
    """Gather historical sector weight allocation from N-PORT data.

    Returns a list of dicts with report_date and sector_weights.
    Used for area-stack charts in Fact Sheets.
    """
    if not fund_cik:
        return []

    try:
        from app.shared.models import SecNportHolding

        series_filter = [SecNportHolding.cik == fund_cik]
        if series_id:
            series_filter.append(SecNportHolding.series_id == series_id)

        # Get all unique report dates for this fund
        report_dates = (
            db.query(SecNportHolding.report_date)
            .filter(*series_filter)
            .distinct()
            .order_by(SecNportHolding.report_date.asc())
            .all()
        )
        if not report_dates:
            return []

        # Pre-fetch all holdings across all dates for batch GICS lookup
        all_dates = [rd for (rd,) in report_dates]
        all_holdings = (
            db.query(SecNportHolding)
            .filter(
                *series_filter,
                SecNportHolding.report_date.in_(all_dates),
            )
            .all()
        )

        # Batch GICS lookup for all equity CUSIPs across all dates
        equity_cusips = list({
            h.cusip for h in all_holdings
            if h.cusip and (h.asset_class or "").strip().upper() in _EQUITY_ASSET_CATS
        })
        cusip_to_gics = _batch_gics_lookup(db, equity_cusips)

        # Group holdings by report_date
        holdings_by_date: dict[date, list[Any]] = {}
        for h in all_holdings:
            holdings_by_date.setdefault(h.report_date, []).append(h)

        history = []
        for rd in all_dates:
            holdings = holdings_by_date.get(rd, [])
            if not holdings:
                continue

            # Compute sector weights (group by sector label, sum pct_of_nav)
            sector_totals: dict[str, float] = {}
            for h in holdings:
                sector = _resolve_sector(h, cusip_to_gics)
                pct = float(h.pct_of_nav or 0)
                sector_totals[sector] = sector_totals.get(sector, 0.0) + pct

            sector_weights = {
                s: round(v / 100, 4)
                for s, v in sorted(sector_totals.items(), key=lambda x: -x[1])
                if v > 0
            }

            history.append({
                "report_date": rd.isoformat(),
                "sector_weights": sector_weights,
            })

        return history

    except Exception:
        logger.exception("sec_nport_history_failed", fund_cik=fund_cik)
        return []


def gather_fund_enrichment(
    db: Session,
    *,
    fund_cik: str | None,
    sec_universe: str | None,
    series_id: str | None = None,
) -> dict[str, Any]:
    """Gather N-CEN classification flags and XBRL fee data for DD report.

    Queries SecRegisteredFund (N-CEN), SecFundClass (XBRL), and dedicated
    vehicle tables (SecEtf, SecBdc, SecMoneyMarketFund) for enrichment.
    Returns empty dict on error or no data — never raises.

    Parameters
    ----------
    db : Session
        Sync database session.
    fund_cik : str | None
        Fund CIK from sec_registered_funds.
    sec_universe : str | None
        Universe tag (e.g. "registered_us").

    """
    if not fund_cik or sec_universe != "registered_us":
        return {}

    try:
        from app.shared.models import (
            SecBdc,
            SecEtf,
            SecFundClass,
            SecMoneyMarketFund,
            SecRegisteredFund,
        )

        fund = (
            db.query(SecRegisteredFund)
            .filter(SecRegisteredFund.cik == fund_cik)
            .first()
        )
        if not fund:
            return {}

        result: dict[str, Any] = {
            "enrichment_available": True,
            "strategy_label": fund.strategy_label,
            "classification": {
                "is_index": fund.is_index,
                "is_non_diversified": fund.is_non_diversified,
                "is_target_date": fund.is_target_date,
                "is_fund_of_fund": fund.is_fund_of_fund,
                "is_master_feeder": fund.is_master_feeder,
            },
            "operational": {
                "is_sec_lending_authorized": fund.is_sec_lending_authorized,
                "did_lend_securities": fund.did_lend_securities,
                "has_swing_pricing": fund.has_swing_pricing,
                "did_pay_broker_research": fund.did_pay_broker_research,
            },
            "ncen_fees": {},
            "share_classes": [],
            "monthly_avg_net_assets": (
                float(fund.monthly_avg_net_assets)
                if fund.monthly_avg_net_assets is not None
                else None
            ),
            "fund_inception_date": (
                str(fund.inception_date)
                if fund.inception_date
                else None
            ),
        }

        # N-CEN fees (only reported for closed-end / interval funds)
        if fund.management_fee is not None or fund.net_operating_expenses is not None:
            result["ncen_fees"] = {
                "management_fee": float(fund.management_fee) if fund.management_fee is not None else None,
                "net_operating_expenses": float(fund.net_operating_expenses) if fund.net_operating_expenses is not None else None,
            }

        # XBRL per-share-class data — filter by series_id when available
        # to avoid returning all classes from umbrella CIKs
        class_q = db.query(SecFundClass).filter(SecFundClass.cik == fund_cik)
        if series_id:
            class_q = class_q.filter(SecFundClass.series_id == series_id)
        class_rows = class_q.all()
        for sc in class_rows:
            result["share_classes"].append({
                "class_id": sc.class_id,
                "class_name": sc.class_name,
                "series_name": sc.series_name,
                "ticker": sc.ticker,
                # XBRL OEF stores _pct fields as pure fractions (0.007 = 0.7%).
                # Keep as fractions — frontend formatPercent() handles display.
                "expense_ratio_pct": float(sc.expense_ratio_pct) if sc.expense_ratio_pct is not None else None,
                "advisory_fees_paid": float(sc.advisory_fees_paid) if sc.advisory_fees_paid is not None else None,
                "net_assets": float(sc.net_assets) if sc.net_assets is not None else None,
                "holdings_count": sc.holdings_count,
                "portfolio_turnover_pct": float(sc.portfolio_turnover_pct) if sc.portfolio_turnover_pct is not None else None,
                "avg_annual_return_pct": float(sc.avg_annual_return_pct) if sc.avg_annual_return_pct is not None else None,
            })

        # Vehicle-specific data (ETF / BDC / MMF)
        if fund.series_id:
            etf = (
                db.query(SecEtf)
                .filter(SecEtf.series_id == fund.series_id)
                .first()
            )
            if etf:
                result["vehicle_specific"] = {
                    "type": "etf",
                    "tracking_difference_gross": float(etf.tracking_difference_gross) if etf.tracking_difference_gross is not None else None,
                    "tracking_difference_net": float(etf.tracking_difference_net) if etf.tracking_difference_net is not None else None,
                    "index_tracked": etf.index_tracked,
                }
            else:
                bdc = (
                    db.query(SecBdc)
                    .filter(SecBdc.series_id == fund.series_id)
                    .first()
                )
                if bdc:
                    result["vehicle_specific"] = {
                        "type": "bdc",
                        "investment_focus": bdc.investment_focus,
                        "is_externally_managed": bdc.is_externally_managed,
                    }
                else:
                    mmf = (
                        db.query(SecMoneyMarketFund)
                        .filter(SecMoneyMarketFund.series_id == fund.series_id)
                        .first()
                    )
                    if mmf:
                        result["vehicle_specific"] = {
                            "type": "mmf",
                            "mmf_category": mmf.mmf_category,
                            "weighted_avg_maturity": mmf.weighted_avg_maturity,
                            "weighted_avg_life": mmf.weighted_avg_life,
                            "seven_day_gross_yield": float(mmf.seven_day_gross_yield) if mmf.seven_day_gross_yield is not None else None,
                        }

        # Insider sentiment (aggregate from portfolio holdings or direct)
        try:
            from app.domains.wealth.services.insider_queries import (
                get_insider_sentiment_score,
                get_insider_summary,
            )

            # Try direct issuer CIK first (single-stock or ETF tracking an issuer)
            insider_score = get_insider_sentiment_score(db, issuer_cik=fund_cik)
            if insider_score != 50.0:
                result["insider_sentiment_score"] = insider_score
                insider_detail = get_insider_summary(db, issuer_cik=fund_cik)
                if insider_detail:
                    result["insider_summary"] = insider_detail
        except Exception:
            logger.debug("insider_sentiment_skipped", fund_cik=fund_cik)

        logger.info(
            "fund_enrichment_gathered",
            fund_cik=fund_cik,
            strategy_label=result.get("strategy_label"),
            share_classes=len(result["share_classes"]),
            has_vehicle_specific="vehicle_specific" in result,
            has_insider="insider_sentiment_score" in result,
        )

        return result

    except Exception:
        logger.exception("fund_enrichment_gather_failed", fund_cik=fund_cik)
        return {}


def gather_sec_adv_data(
    db: Session,
    *,
    manager_name: str | None,
    crd_number: str | None = None,
) -> dict[str, Any]:
    """Gather ADV manager profile data for DD report chapters.

    Returns dict with keys: compliance_disclosures, adv_aum_history,
    adv_fee_structure, adv_team. Empty dict on error or no data.

    Parameters
    ----------
    db : Session
        Sync database session.
    manager_name : str | None
        Fund manager name for SEC linkage.
    crd_number : str | None
        Direct CRD override (skips manager_name lookup).

    """
    if not crd_number and not manager_name:
        return {}

    try:
        resolved_crd = crd_number or _resolve_crd(db, manager_name)
        if not resolved_crd:
            return {}

        from app.shared.models import SecManager, SecManagerFund, SecManagerTeam

        # Manager profile
        manager = (
            db.query(SecManager)
            .filter(SecManager.crd_number == resolved_crd)
            .first()
        )
        if not manager:
            return {}

        # Compliance disclosures count
        compliance_disclosures = manager.compliance_disclosures or 0

        # AUM history (from the single manager record — workers update periodically)
        adv_aum_history: dict[str, Any] = {}
        if manager.aum_total is not None:
            adv_aum_history["total"] = float(manager.aum_total)
        if manager.aum_discretionary is not None:
            adv_aum_history["discretionary"] = float(manager.aum_discretionary)
        if manager.aum_non_discretionary is not None:
            adv_aum_history["non_discretionary"] = float(manager.aum_non_discretionary)
        if manager.total_accounts is not None:
            adv_aum_history["total_accounts"] = manager.total_accounts

        # Fee structure
        adv_fee_structure: list[str] = []
        if manager.fee_types:
            adv_fee_structure = (
                manager.fee_types if isinstance(manager.fee_types, list)
                else [str(manager.fee_types)]
            )

        # Funds managed (Schedule D)
        fund_rows = (
            db.query(SecManagerFund)
            .filter(SecManagerFund.crd_number == resolved_crd)
            .all()
        )
        adv_funds = [
            {
                "fund_name": f.fund_name,
                "gross_asset_value": float(f.gross_asset_value) if f.gross_asset_value else None,
                "fund_type": f.fund_type,
                "is_fund_of_funds": f.is_fund_of_funds,
                "investor_count": f.investor_count,
            }
            for f in fund_rows
        ]

        # Team members
        team_rows = (
            db.query(SecManagerTeam)
            .filter(SecManagerTeam.crd_number == resolved_crd)
            .all()
        )
        adv_team = [
            {
                "person_name": t.person_name,
                "title": t.title,
                "role": t.role,
                "education": t.education,
                "certifications": t.certifications or [],
                "years_experience": t.years_experience,
                "bio_summary": t.bio_summary,
            }
            for t in team_rows
        ]

        return {
            "compliance_disclosures": compliance_disclosures,
            "adv_aum_history": adv_aum_history,
            "adv_fee_structure": adv_fee_structure,
            "adv_funds": adv_funds,
            "adv_team": adv_team,
            "adv_registration_status": manager.registration_status,
            "adv_firm_name": manager.firm_name,
            "adv_website": manager.website,
            "crd_number": resolved_crd,
        }

    except Exception:
        logger.exception("sec_adv_gather_failed", manager_name=manager_name)
        return {}


def gather_sec_adv_brochure(
    db: Session,
    crd_number: str | None,
    sections: list[str] | None = None,
) -> dict[str, str]:
    """Fetch ADV Part 2A brochure narrative sections for a manager.

    Returns dict keyed by section name with content text.
    Never raises — returns empty dict on any failure.

    Parameters
    ----------
    db : Session
        Sync database session.
    crd_number : str | None
        Manager CRD number.
    sections : list[str] | None
        Section names to fetch. Defaults to the 4 most relevant for
        manager_assessment: item_5, item_8, item_9, item_10.

    """
    if not crd_number:
        return {}

    if sections is None:
        sections = ["item_5", "item_8", "item_9", "item_10"]

    try:
        rows = (
            db.execute(
                text("""
                    SELECT section, content
                    FROM sec_manager_brochure_text
                    WHERE crd_number = :crd
                      AND section = ANY(:sections)
                    ORDER BY filing_date DESC, section
                """),
                {"crd": crd_number, "sections": sections},
            )
            .mappings()
            .all()
        )
        # Latest filing wins — first occurrence per section
        result: dict[str, str] = {}
        for row in rows:
            if row["section"] not in result:
                result[row["section"]] = row["content"]
        return result
    except Exception:
        logger.exception("sec_adv_brochure_gather_failed", crd_number=crd_number)
        return {}


# ── Prospectus data (RR1) ──────────────────────────────────────────


def gather_prospectus_stats(
    db: Session,
    *,
    fund_cik: str | None,
    series_id: str | None = None,
) -> dict[str, Any]:
    """Gather fee and expense stats from sec_fund_prospectus_stats.

    Resolves series_id from CIK if not provided. Returns the canonical
    share class row — the one with the lowest expense_ratio_pct among
    all classes for the series (avoids institutional share class skew).

    Returns empty dict if no data or on error. Never raises.
    """
    if not fund_cik and not series_id:
        return {}
    try:
        from app.domains.wealth.models.prospectus import SecFundProspectusStats

        resolved = series_id or _resolve_series_id(db, fund_cik)
        if not resolved:
            return {}

        row = (
            db.query(SecFundProspectusStats)
            .filter(SecFundProspectusStats.series_id == resolved)
            .order_by(
                # Lowest-cost class first (canonical retail share class)
                SecFundProspectusStats.expense_ratio_pct.asc().nulls_last(),
                SecFundProspectusStats.filing_date.desc().nulls_last(),
            )
            .first()
        )

        if not row:
            return {}

        def _f(v: Any) -> float | None:
            return float(v) if v is not None else None

        result: dict[str, Any] = {
            "prospectus_stats_available": True,
            "series_id": row.series_id,
            "class_id": row.class_id,
            "filing_date": str(row.filing_date) if row.filing_date else None,
            "data_source": "SEC DERA RR1 Prospectus",
            # Fee structure
            "management_fee_pct":       _f(row.management_fee_pct),
            "expense_ratio_pct":        _f(row.expense_ratio_pct),
            "net_expense_ratio_pct":    _f(row.net_expense_ratio_pct),
            "fee_waiver_pct":           _f(row.fee_waiver_pct),
            "distribution_12b1_pct":    _f(row.distribution_12b1_pct),
            "acquired_fund_fees_pct":   _f(row.acquired_fund_fees_pct),
            "other_expenses_pct":       _f(row.other_expenses_pct),
            "portfolio_turnover_pct":   _f(row.portfolio_turnover_pct),
            # Expense examples (per $10k)
            "expense_example_1y":  _f(row.expense_example_1y),
            "expense_example_3y":  _f(row.expense_example_3y),
            "expense_example_5y":  _f(row.expense_example_5y),
            "expense_example_10y": _f(row.expense_example_10y),
            # Average annual returns (standardized prospectus periods)
            "avg_annual_return_1y":  _f(row.avg_annual_return_1y),
            "avg_annual_return_5y":  _f(row.avg_annual_return_5y),
            "avg_annual_return_10y": _f(row.avg_annual_return_10y),
            # Bar chart extremes
            "bar_chart_best_qtr_pct":  _f(row.bar_chart_best_qtr_pct),
            "bar_chart_worst_qtr_pct": _f(row.bar_chart_worst_qtr_pct),
            "bar_chart_ytd_pct":       _f(row.bar_chart_ytd_pct),
        }

        # XBRL/RR1 stores _pct fields as pure fractions → ×100 for LLM display
        _PCT_KEYS = [
            "expense_ratio_pct",
            "net_expense_ratio_pct",
            "management_fee_pct",
            "fee_waiver_pct",
            "distribution_12b1_pct",
            "acquired_fund_fees_pct",
            "other_expenses_pct",
            "portfolio_turnover_pct",
            "avg_annual_return_1y",
            "avg_annual_return_5y",
            "avg_annual_return_10y",
            "bar_chart_best_qtr_pct",
            "bar_chart_worst_qtr_pct",
            "bar_chart_ytd_pct",
        ]
        for _k in _PCT_KEYS:
            if result.get(_k) is not None:
                result[_k] = round(result[_k] * 100, 6)

        logger.info(
            "prospectus_stats_gathered",
            series_id=resolved,
            expense_ratio=result.get("expense_ratio_pct"),
            has_avg_returns=result.get("avg_annual_return_10y") is not None,
        )
        return result

    except Exception:
        logger.exception("prospectus_stats_gather_failed", fund_cik=fund_cik)
        return {}


def gather_prospectus_returns(
    db: Session,
    *,
    fund_cik: str | None,
    series_id: str | None = None,
    years_back: int = 12,
) -> list[dict[str, Any]]:
    """Gather annual return history from sec_fund_prospectus_returns.

    Returns list of {year, annual_return_pct} dicts sorted ascending by year.
    Capped at years_back years from today (default 12).

    Returns empty list if no data or on error. Never raises.
    """
    if not fund_cik and not series_id:
        return []
    try:
        from datetime import date as _date

        from app.domains.wealth.models.prospectus import SecFundProspectusReturn

        resolved = series_id or _resolve_series_id(db, fund_cik)
        if not resolved:
            return []

        cutoff_year = _date.today().year - years_back

        rows = (
            db.query(SecFundProspectusReturn)
            .filter(
                SecFundProspectusReturn.series_id == resolved,
                SecFundProspectusReturn.year >= cutoff_year,
            )
            .order_by(SecFundProspectusReturn.year.asc())
            .all()
        )

        if not rows:
            return []

        # SEC DERA RR1 stores returns as pure fractions (0.0469 = 4.69%).
        # Frontend formatPercent() expects fractions — no ×100 needed.
        result = [
            {"year": r.year, "annual_return_pct": float(r.annual_return_pct)}
            for r in rows
        ]

        logger.info(
            "prospectus_returns_gathered",
            series_id=resolved,
            years=len(result),
            first_year=result[0]["year"],
            last_year=result[-1]["year"],
        )
        return result

    except Exception:
        logger.exception("prospectus_returns_gather_failed", fund_cik=fund_cik)
        return []


# ── Internal helpers ────────────────────────────────────────────────


def _resolve_series_id(db: Session, cik: str | None) -> str | None:
    """Resolve primary series_id from fund CIK via sec_fund_classes.

    Returns the series_id with the most share classes (most data-rich series)
    when a CIK has multiple series. Returns None if not found.
    """
    if not cik:
        return None
    try:
        from app.shared.models import SecFundClass

        row = (
            db.query(SecFundClass.series_id, func.count().label("cnt"))
            .filter(
                SecFundClass.cik == cik,
                SecFundClass.series_id.isnot(None),
                SecFundClass.series_id != "",
            )
            .group_by(SecFundClass.series_id)
            .order_by(func.count().desc())
            .first()
        )
        return row.series_id if row else None
    except Exception:
        logger.debug("series_id_resolution_failed", cik=cik)
        return None


def _resolve_cik(db: Session, manager_name: str | None) -> str | None:
    """Resolve manager_name → CIK via sec_managers table."""
    if not manager_name:
        return None
    from app.shared.models import SecManager

    row = (
        db.query(SecManager.cik)
        .filter(func.lower(SecManager.firm_name) == manager_name.lower())
        .first()
    )
    return row[0] if row and row[0] else None


def _resolve_crd(db: Session, manager_name: str | None) -> str | None:
    """Resolve manager_name → CRD number via sec_managers table."""
    if not manager_name:
        return None
    from app.shared.models import SecManager

    row = (
        db.query(SecManager.crd_number)
        .filter(func.lower(SecManager.firm_name) == manager_name.lower())
        .first()
    )
    return row[0] if row and row[0] else None


def _compute_sector_weights(
    db: Session,
    cik: str,
    report_date: date,
) -> dict[str, float]:
    """Compute sector weight allocation for a given quarter.

    Mirrors ThirteenFService.get_sector_aggregation() logic but sync.
    Excludes options (CALL/PUT) — only equity positions.
    """
    from app.shared.models import Sec13fHolding

    holdings = (
        db.query(Sec13fHolding)
        .filter(
            Sec13fHolding.cik == cik,
            Sec13fHolding.report_date == report_date,
        )
        .all()
    )
    if not holdings:
        return {}

    # Exclude options — only equity positions reflect sector exposure
    equity = [
        h for h in holdings
        if (h.asset_class or "").upper() not in ("CALL", "PUT")
    ]
    if not equity:
        return {}

    total_value = sum(h.market_value or 0 for h in equity)
    if total_value <= 0:
        return {}

    sector_totals: dict[str, int] = {}
    for h in equity:
        sector = h.sector or "Unknown"
        sector_totals[sector] = sector_totals.get(sector, 0) + (h.market_value or 0)

    return {
        sector: round(val / total_value, 4)
        for sector, val in sorted(sector_totals.items(), key=lambda x: -x[1])
    }


def _compute_sector_weights_batch(
    db: Session,
    cik: str,
    report_dates: list[date],
) -> dict[date, dict[str, float]]:
    """Compute sector weight allocation for multiple quarters in one query."""
    if not report_dates:
        return {}

    from app.shared.models import Sec13fHolding

    holdings = (
        db.query(Sec13fHolding)
        .filter(
            Sec13fHolding.cik == cik,
            Sec13fHolding.report_date.in_(report_dates),
        )
        .all()
    )
    if not holdings:
        return {}

    # Group by report_date, then compute weights per date
    by_date: dict[date, list] = {}
    for h in holdings:
        by_date.setdefault(h.report_date, []).append(h)

    result: dict[date, dict[str, float]] = {}
    for rd, date_holdings in by_date.items():
        equity = [
            h for h in date_holdings
            if (h.asset_class or "").upper() not in ("CALL", "PUT")
        ]
        if not equity:
            continue
        total_value = sum(h.market_value or 0 for h in equity)
        if total_value <= 0:
            continue
        sector_totals: dict[str, int] = {}
        for h in equity:
            sector = h.sector or "Unknown"
            sector_totals[sector] = sector_totals.get(sector, 0) + (h.market_value or 0)
        result[rd] = {
            sector: round(val / total_value, 4)
            for sector, val in sorted(sector_totals.items(), key=lambda x: -x[1])
        }

    return result


def _detect_sector_drift(
    current: dict[str, float],
    previous: dict[str, float],
) -> bool:
    """Detect material sector drift between two quarters.

    Returns True if any sector weight shifted by more than
    _DRIFT_THRESHOLD_PP (5pp default).
    """
    all_sectors = set(current.keys()) | set(previous.keys())
    for sector in all_sectors:
        cur_w = current.get(sector, 0.0)
        prev_w = previous.get(sector, 0.0)
        if abs(cur_w - prev_w) > _DRIFT_THRESHOLD_PP:
            return True
    return False
