"""Financial data extraction — structured financials, BDC/REIT metrics, AM platform metrics.

Two extraction strategies:
  1. XBRLS.from_filings() — multi-period stitching for income/balance/CF (primary)
  2. EntityFacts — concept-level queries, better for BDCs with custom taxonomies (fallback)

AM platform metrics (AUM, FRE, DE) use fuzzy label search across all taxonomies
because these are custom XBRL concepts, not us-gaap.

Ratios: only 4 credit-relevant ratios computed:
  leverage_ratio, nii_dividend_coverage, interest_coverage, debt_service_coverage

Sync service — dispatched via asyncio.to_thread().
"""
from __future__ import annotations

from typing import Any

import structlog

from vertical_engines.credit.edgar.models import FinancialStatements

logger = structlog.get_logger()


# ── XBRL concept fallback lists ───────────────────────────────────

_CONCEPTS_NAV_PER_SHARE = ["NetAssetValuePerShare"]
_CONCEPTS_TOTAL_ASSETS = ["Assets"]
_CONCEPTS_TOTAL_DEBT = [
    "LongTermDebtAndCapitalLeaseObligations",
    "LongTermDebt",
    "DebtAndCapitalLeaseObligations",
]
_CONCEPTS_NET_INVESTMENT_INCOME = [
    "InvestmentIncomeNet",
    "NetInvestmentIncome",
    "InvestmentIncome",
]
_CONCEPTS_DIVIDENDS_PAID = [
    "PaymentsOfDividendsCommonStock",
    "DividendsPaid",
    "PaymentsOfDividends",
]
_CONCEPTS_TOTAL_REVENUES = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "TotalRevenues",
]

# ── Structured financials via XBRLS ───────────────────────────────


def _statement_df_to_dicts(df: Any) -> list[dict[str, Any]]:
    """Convert a statement DataFrame to list of period dicts.

    DataFrame has concepts as rows, period dates as columns.
    Each dict = one period with label:value pairs.
    """
    if df is None or df.empty:
        return []

    periods: list[dict[str, Any]] = []
    metadata_cols = {
        "concept", "label", "balance", "weight",
        "preferred_sign", "dimension", "unit", "point_in_time",
    }
    period_cols = [c for c in df.columns if c not in metadata_cols]

    for col in period_cols:
        period_data: dict[str, Any] = {"period": str(col)}
        for idx, row in df.iterrows():
            label = row.get("label", row.get("concept", str(idx)))
            val = row[col]
            if val is not None and str(val).strip():
                try:
                    period_data[str(label)] = float(val)
                except (ValueError, TypeError):
                    period_data[str(label)] = str(val)
        periods.append(period_data)

    return periods


def extract_structured_financials(
    company: Any,
    *,
    filings: Any | None = None,
) -> FinancialStatements:
    """Extract multi-period income/balance/CF from XBRL filings.

    Args:
        filings: Pre-fetched 10-K filings. When provided, skip
            ``company.get_filings()`` call to avoid duplicate SEC requests.

    Primary: XBRLS.from_filings() for multi-period stitching.
    Fallback: EntityFacts for BDCs with custom taxonomies.

    Never raises — returns empty FinancialStatements on failure.

    """
    result = FinancialStatements()

    try:
        from edgar.xbrl import XBRLS
    except ImportError:
        logger.warning("edgartools_not_installed")
        return result

    try:
        if filings is None:
            filings = company.get_filings(form="10-K", amendments=False)
        if not filings:
            return result
        filings = filings.head(5)

        # Record provenance
        for f in filings:
            result.source_filings.append({
                "accession_number": getattr(f, "accession_no", ""),
                "filing_date": str(getattr(f, "filing_date", "")),
                "form": getattr(f, "form", ""),
            })

        # Multi-period stitching
        try:
            xbrls = XBRLS.from_filings(filings)
            statements = xbrls.statements

            income = statements.income_statement()
            if income:
                df = income.to_dataframe()
                result.income_statement = _statement_df_to_dicts(df)

            balance = statements.balance_sheet()
            if balance:
                df = balance.to_dataframe()
                result.balance_sheet = _statement_df_to_dicts(df)

            # Note: cashflow_statement() on StitchedStatements (not cash_flow_statement)
            cashflow = statements.cashflow_statement()
            if cashflow:
                df = cashflow.to_dataframe()
                result.cash_flow = _statement_df_to_dicts(df)

        except Exception as exc:
            logger.debug(
                "xbrls_stitching_failed_trying_entityfacts",
                company=company.name if hasattr(company, "name") else "",
                error=str(exc),
            )
            # Fallback: EntityFacts for BDCs
            _extract_via_entity_facts(company, result)

        # Count periods
        for stmt in [result.income_statement, result.balance_sheet, result.cash_flow]:
            if stmt:
                result.periods_available = len(stmt)
                break

    except Exception as exc:
        logger.warning(
            "structured_financials_extraction_failed",
            error=str(exc),
            exc_info=True,
        )

    return result


def _extract_via_entity_facts(company: Any, result: FinancialStatements) -> None:
    """Fallback: extract key financial data via EntityFacts API.

    Better for BDCs with custom XBRL taxonomies.
    """
    try:
        from edgar.entity.core import NoCompanyFactsFound
    except ImportError:
        return

    try:
        facts = company.get_facts()

        # Income statement proxy: revenue time series
        try:
            income_ts = facts.income_statement(periods=5, annual=True)
            if income_ts is not None:
                df = income_ts.to_dataframe() if hasattr(income_ts, "to_dataframe") else None
                if df is not None and not df.empty:
                    result.income_statement = _statement_df_to_dicts(df)
        except Exception:
            pass

        # Balance sheet proxy
        try:
            balance_ts = facts.balance_sheet(periods=5, annual=True)
            if balance_ts is not None:
                df = balance_ts.to_dataframe() if hasattr(balance_ts, "to_dataframe") else None
                if df is not None and not df.empty:
                    result.balance_sheet = _statement_df_to_dicts(df)
        except Exception:
            pass

    except NoCompanyFactsFound:
        logger.debug("no_company_facts", company=getattr(company, "name", ""))
    except Exception as exc:
        logger.debug("entity_facts_fallback_failed", error=str(exc))


# ── BDC/REIT metrics ─────────────────────────────────────────────


def _query_fact(facts: Any, concept: str) -> dict[str, Any] | None:
    """Query a single fact with annual preference."""
    try:
        results = (
            facts.query()
            .by_concept(concept)
            .by_form_type("10-K")
            .execute()
        )
        if results:
            f = results[0]
            return {
                "val": f.numeric_value,
                "as_of": str(getattr(f, "period_end", "")),
                "filed": str(getattr(f, "filing_date", "")),
                "form": getattr(f, "form_type", ""),
                "concept": getattr(f, "concept", concept),
            }
    except Exception:
        pass
    return None


def _query_fact_multi_concept(facts: Any, concepts: list[str]) -> dict[str, Any] | None:
    """Try multiple concepts in order, return first match."""
    for concept in concepts:
        result = _query_fact(facts, concept)
        if result:
            return result
    return None


def extract_bdc_reit_metrics(company: Any) -> dict[str, Any]:
    """Extract BDC/REIT financial metrics via EntityFacts API."""
    metrics: dict[str, Any] = {}

    try:
        from edgar.entity.core import NoCompanyFactsFound
    except ImportError:
        return metrics

    try:
        facts = company.get_facts()
    except NoCompanyFactsFound:
        return metrics
    except Exception as exc:
        logger.debug("bdc_reit_facts_failed", error=str(exc))
        return metrics

    metrics["nav_per_share"] = _query_fact_multi_concept(facts, _CONCEPTS_NAV_PER_SHARE)
    metrics["total_assets_usd"] = _query_fact_multi_concept(facts, _CONCEPTS_TOTAL_ASSETS)
    metrics["total_debt_usd"] = _query_fact_multi_concept(facts, _CONCEPTS_TOTAL_DEBT)
    metrics["net_investment_income_usd"] = _query_fact_multi_concept(
        facts, _CONCEPTS_NET_INVESTMENT_INCOME,
    )
    metrics["dividends_paid_usd"] = _query_fact_multi_concept(facts, _CONCEPTS_DIVIDENDS_PAID)

    # Total assets trend (3 years)
    try:
        trend_results = (
            facts.query()
            .by_concept("Assets")
            .by_form_type("10-K")
            .execute()
        )
        if trend_results:
            metrics["total_assets_trend"] = [
                {
                    "val": f.numeric_value,
                    "as_of": str(getattr(f, "period_end", "")),
                    "form": getattr(f, "form_type", ""),
                }
                for f in trend_results[:3]
            ]
    except Exception:
        pass

    # Derived ratios
    _compute_bdc_derived_ratios(metrics)

    # Remove None entries
    metrics = {k: v for k, v in metrics.items() if v is not None}

    return metrics


def _compute_bdc_derived_ratios(metrics: dict[str, Any]) -> None:
    """Compute leverage ratio and NII dividend coverage."""
    assets = metrics.get("total_assets_usd")
    debt = metrics.get("total_debt_usd")
    if assets and debt and assets.get("val") and debt.get("val"):
        equity = assets["val"] - debt["val"]
        if equity > 0:
            ratio = debt["val"] / equity
            metrics["leverage_ratio"] = {
                "val": round(ratio, 4),
                "exceeds_1940_act_cap": ratio > 2.0,
            }

    nii = metrics.get("net_investment_income_usd")
    div = metrics.get("dividends_paid_usd")
    if nii and div and nii.get("val") and div.get("val") and abs(div["val"]) > 0:
        coverage = nii["val"] / abs(div["val"])
        metrics["nii_dividend_coverage"] = {
            "val": round(coverage, 4),
            "below_1x": coverage < 1.0,
        }


# ── AM platform metrics ──────────────────────────────────────────


def _query_fact_by_label(facts: Any, label: str) -> dict[str, Any] | None:
    """Query by label with fuzzy matching — for custom XBRL concepts."""
    try:
        results = (
            facts.query()
            .by_label(label, fuzzy=True)
            .by_form_type("10-K")
            .execute()
        )
        if results:
            f = results[0]
            return {
                "val": f.numeric_value,
                "as_of": str(getattr(f, "period_end", "")),
                "filed": str(getattr(f, "filing_date", "")),
                "form": getattr(f, "form_type", ""),
                "concept": getattr(f, "concept", label),
            }
    except Exception:
        pass
    return None


def extract_am_platform_metrics(company: Any) -> dict[str, Any]:
    """Extract AM platform metrics (AUM, FRE, DE) via fuzzy label search.

    These are custom XBRL concepts (NOT us-gaap), so we search by label
    across all taxonomies.
    """
    metrics: dict[str, Any] = {}

    try:
        from edgar.entity.core import NoCompanyFactsFound
    except ImportError:
        return metrics

    try:
        facts = company.get_facts()
    except NoCompanyFactsFound:
        return metrics
    except Exception as exc:
        logger.debug("am_platform_facts_failed", error=str(exc))
        return metrics

    # Standard concepts
    metrics["total_assets_usd"] = _query_fact_multi_concept(facts, _CONCEPTS_TOTAL_ASSETS)
    metrics["total_revenues_usd"] = _query_fact_multi_concept(facts, _CONCEPTS_TOTAL_REVENUES)

    # Custom concepts — fuzzy label search
    metrics["aum_usd"] = _query_fact_by_label(facts, "Assets Under Management")
    metrics["management_fee_revenue_usd"] = _query_fact_by_label(facts, "Management Fee")
    metrics["fee_related_earnings_usd"] = _query_fact_by_label(facts, "Fee Related Earnings")
    metrics["distributable_earnings_usd"] = _query_fact_by_label(facts, "Distributable Earnings")

    # Remove None entries
    metrics = {k: v for k, v in metrics.items() if v is not None}

    return metrics


# ── Ratio calculation ─────────────────────────────────────────────


def calculate_ratios(financials: FinancialStatements) -> dict[str, float | None]:
    """Calculate 4 credit-relevant ratios from structured financials.

    Only ratios with concrete consumers:
      leverage_ratio, nii_dividend_coverage, interest_coverage, debt_service_coverage

    Returns None for any ratio where data is insufficient or periods misalign.
    """
    ratios: dict[str, float | None] = {
        "leverage_ratio": None,
        "nii_dividend_coverage": None,
        "interest_coverage": None,
        "debt_service_coverage": None,
    }

    if not financials.balance_sheet:
        return ratios

    # Use most recent period
    latest_bs = financials.balance_sheet[0] if financials.balance_sheet else {}
    latest_is = financials.income_statement[0] if financials.income_statement else {}
    latest_cf = financials.cash_flow[0] if financials.cash_flow else {}

    # Leverage ratio: total_debt / total_equity
    total_assets = _find_value(latest_bs, ["Total Assets", "Assets"])
    total_liabilities = _find_value(
        latest_bs, ["Total Liabilities", "Liabilities"],
    )
    if total_assets and total_liabilities:
        equity = total_assets - total_liabilities
        if equity > 0:
            total_debt = _find_value(
                latest_bs,
                ["Long-Term Debt", "Total Debt", "Long-term Debt"],
            )
            if total_debt:
                ratios["leverage_ratio"] = round(total_debt / equity, 4)

    # Interest coverage: EBIT / interest_expense
    operating_income = _find_value(
        latest_is,
        ["Operating Income", "Income from Operations", "Operating Income (Loss)"],
    )
    interest_expense = _find_value(
        latest_is,
        ["Interest Expense", "Interest expense"],
    )
    if operating_income and interest_expense and abs(interest_expense) > 0:
        ratios["interest_coverage"] = round(
            operating_income / abs(interest_expense), 4,
        )

    # DSCR: operating_cf / total_debt_service
    operating_cf = _find_value(
        latest_cf,
        [
            "Net Cash from Operating Activities",
            "Operating Cash Flow",
            "Cash from Operations",
        ],
    )
    if operating_cf and interest_expense and abs(interest_expense) > 0:
        ratios["debt_service_coverage"] = round(
            operating_cf / abs(interest_expense), 4,
        )

    return ratios


def _find_value(period_data: dict[str, Any], labels: list[str]) -> float | None:
    """Find a numeric value in a period dict by trying multiple label variants."""
    for label in labels:
        val = period_data.get(label)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                continue
    return None
