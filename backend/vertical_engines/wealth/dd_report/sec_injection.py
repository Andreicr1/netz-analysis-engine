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


# ── Internal helpers ────────────────────────────────────────────────


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
