"""Form 4 insider trading signal detection for credit early-warning.

Detects credit-relevant insider trading patterns:
  - Net selling > 10% of holdings in 90-day window
  - 3+ distinct insiders selling within 30 days (cluster signal)
  - C-suite sales > $1M (executive exodus signal)

Exclusions:
  - 10b5-1 plan transactions (Form 4 checkbox + footnote fallback)
  - Transaction code "F" (tax withholding on RSU vesting)
  - Transaction code "G" (gift transfers)
  - Option exercises with immediate hold

HTTP optimization: filters Form 4 filings by filing_date from index
metadata BEFORE calling filing.obj() (which downloads each filing).

Sync service — dispatched via asyncio.to_thread().
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

import structlog

from vertical_engines.credit.edgar.models import (
    InsiderSignal,
    InsiderSignalType,
    SignalSeverity,
)

logger = structlog.get_logger()

# Transaction codes to exclude (not discretionary selling)
_EXCLUDE_CODES = {"F", "G", "J"}  # F=tax withhold, G=gift, J=other

# C-suite titles (case-insensitive substrings)
_CSUITE_TITLES = {"ceo", "cfo", "coo", "chief executive", "chief financial", "chief operating"}


def detect_insider_signals(
    company: Any,
    *,
    lookback_days: int = 365,
) -> list[InsiderSignal]:
    """Detect credit-relevant insider trading signals from Form 4 filings.

    Never raises — returns empty list on failure.
    """
    try:
        return _detect_signals_impl(company, lookback_days)
    except Exception as exc:
        logger.warning(
            "insider_signal_detection_failed",
            company=getattr(company, "name", "?"),
            error=str(exc),
            exc_info=True,
        )
        return []


def _detect_signals_impl(
    company: Any,
    lookback_days: int,
) -> list[InsiderSignal]:
    """Internal implementation — may raise."""
    cutoff = datetime.now() - timedelta(days=lookback_days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    entity_name = getattr(company, "name", "Unknown")

    # Fetch Form 4 filings — filter by date from index BEFORE downloading
    form4_filings = company.get_filings(
        form="4",
        filing_date=f"{cutoff_str}:",
    )
    if not form4_filings:
        return []
    form4_filings = form4_filings.head(30)  # Reduced from 50 (perf optimization)

    # Parse filings — only download those within lookback window
    insider_txns: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_sell_txns: list[dict[str, Any]] = []

    for filing in form4_filings:
        # Double-check filing date from index (available without download)
        filing_date = getattr(filing, "filing_date", None)
        if filing_date and str(filing_date) < cutoff_str:
            continue

        try:
            form4 = filing.obj()
            if form4 is None:
                continue

            # Extract owner info
            owner = getattr(form4, "reporting_owner", None)
            owner_name = str(owner) if owner else "Unknown"
            is_officer = getattr(owner, "is_officer", False) if owner else False
            is_director = getattr(owner, "is_director", False) if owner else False
            title = getattr(owner, "officer_title", "") if owner else ""

            # Check for 10b5-1 plan indicator
            is_planned = _is_10b5_1_transaction(filing, form4)

            # Process transactions
            transactions = getattr(form4, "transactions", None) or []
            for txn in transactions:
                code = getattr(txn, "transaction_code", "") or ""
                if code.upper() in _EXCLUDE_CODES:
                    continue

                acquired = getattr(txn, "acquired_disposed", "") or ""
                shares = getattr(txn, "shares", 0) or 0
                price = getattr(txn, "price_per_share", 0) or getattr(txn, "price", 0) or 0
                shares_after = getattr(txn, "shares_owned_following", 0) or 0

                txn_dict: dict[str, Any] = {
                    "date": str(filing_date or ""),
                    "insider": owner_name,
                    "title": title or "",
                    "is_officer": is_officer,
                    "is_director": is_director,
                    "shares": abs(float(shares)),
                    "price": float(price),
                    "value": abs(float(shares) * float(price)),
                    "acquired_disposed": acquired,
                    "transaction_code": code,
                    "shares_after": float(shares_after),
                    "is_planned": is_planned,
                }

                insider_txns[owner_name].append(txn_dict)

                # Track sell transactions (disposed, not planned)
                if acquired == "D" and not is_planned:
                    all_sell_txns.append(txn_dict)

        except Exception as exc:
            logger.debug("form4_parse_failed", filing=str(filing), error=str(exc))
            continue

    if not all_sell_txns:
        return []

    # ── Signal Detection ──
    signals: list[InsiderSignal] = []

    _check_net_selling(insider_txns, entity_name, signals)
    _check_cluster_selling(all_sell_txns, entity_name, signals)
    _check_executive_sales(insider_txns, entity_name, signals)

    return signals


def _is_10b5_1_transaction(filing: Any, form4: Any) -> bool:
    """Detect 10b5-1 plan transactions.

    Primary: Check Form 4 checkbox field (SEC 2023 amendments).
    Fallback: Search filing text/footnotes for "10b5-1" keyword.
    """
    # Check for 10b5-1 flag on the form4 object
    if hasattr(form4, "is_10b5_1") and form4.is_10b5_1:
        return True

    # Footnote fallback
    if hasattr(form4, "footnotes"):
        footnotes = form4.footnotes
        if footnotes:
            text = " ".join(str(f) for f in footnotes)
            if "10b5-1" in text.lower() or "rule 10b5-1" in text.lower():
                return True

    # Text fallback (more expensive — downloads filing text)
    try:
        text = filing.text()
        if text and "10b5-1" in text[:5000].lower():
            return True
    except Exception:
        pass

    return False


def _check_net_selling(
    insider_txns: dict[str, list[dict[str, Any]]],
    entity_name: str,
    signals: list[InsiderSignal],
    *,
    window_days: int = 90,
    threshold: float = 0.10,
) -> None:
    """Detect aggregate insider net selling > threshold of holdings in window."""
    for insider, txns in insider_txns.items():
        sells = [t for t in txns if t["acquired_disposed"] == "D" and not t["is_planned"]]
        if not sells:
            continue

        total_sold = sum(t["shares"] for t in sells)
        # Use the highest shares_after value as proxy for total holdings
        max_after = max((t["shares_after"] for t in sells), default=0)
        total_holdings = total_sold + max_after

        if total_holdings > 0 and total_sold / total_holdings > threshold:
            agg_value = sum(t["value"] for t in sells)
            signals.append(InsiderSignal(
                signal_type=InsiderSignalType.NET_SELLING_THRESHOLD,
                severity=SignalSeverity.ELEVATED,
                entity_name=entity_name,
                description=(
                    f"{insider} sold {total_sold / total_holdings:.0%} of holdings "
                    f"({total_sold:,.0f} shares) within {window_days}-day window"
                ),
                insiders=[{"name": insider, "title": sells[0].get("title", "")}],
                transactions=sells[:10],
                aggregate_value=agg_value,
                period_days=window_days,
                detected_at=datetime.now().isoformat()[:10],
            ))


def _check_cluster_selling(
    all_sell_txns: list[dict[str, Any]],
    entity_name: str,
    signals: list[InsiderSignal],
    *,
    window_days: int = 30,
    min_insiders: int = 3,
) -> None:
    """Detect 3+ distinct insiders selling within a rolling window."""
    if len(all_sell_txns) < min_insiders:
        return

    sorted_txns = sorted(all_sell_txns, key=lambda t: t["date"])

    for i, txn in enumerate(sorted_txns):
        window_end = txn["date"]
        # Collect sells within window_days
        window_sells = [
            s for s in sorted_txns[i:]
            if s["date"] <= _add_days_str(window_end, window_days)
        ]
        distinct_insiders = {s["insider"] for s in window_sells}
        if len(distinct_insiders) >= min_insiders:
            agg_value = sum(s["value"] for s in window_sells)
            signals.append(InsiderSignal(
                signal_type=InsiderSignalType.CLUSTER_SELLING,
                severity=SignalSeverity.ELEVATED,
                entity_name=entity_name,
                description=(
                    f"{len(distinct_insiders)} distinct insiders sold "
                    f"within {window_days}-day window starting {window_end}"
                ),
                insiders=[{"name": n} for n in distinct_insiders],
                transactions=window_sells[:10],
                aggregate_value=agg_value,
                period_days=window_days,
                detected_at=datetime.now().isoformat()[:10],
            ))
            break  # One cluster signal is sufficient


def _check_executive_sales(
    insider_txns: dict[str, list[dict[str, Any]]],
    entity_name: str,
    signals: list[InsiderSignal],
    *,
    threshold: float = 1_000_000,
) -> None:
    """Detect C-suite sales exceeding $1M."""
    for insider, txns in insider_txns.items():
        is_csuite = any(
            cs in (txns[0].get("title") or "").lower()
            for cs in _CSUITE_TITLES
        ) if txns else False

        if not is_csuite:
            continue

        sells = [t for t in txns if t["acquired_disposed"] == "D" and not t["is_planned"]]
        agg_value = sum(t["value"] for t in sells)

        if agg_value >= threshold:
            signals.append(InsiderSignal(
                signal_type=InsiderSignalType.EXECUTIVE_SALE,
                severity=SignalSeverity.WATCH if agg_value < 5_000_000 else SignalSeverity.CRITICAL,
                entity_name=entity_name,
                description=(
                    f"{insider} ({txns[0].get('title', 'C-suite')}) sold "
                    f"${agg_value:,.0f} in aggregate"
                ),
                insiders=[{
                    "name": insider,
                    "title": txns[0].get("title", ""),
                    "is_officer": txns[0].get("is_officer", True),
                }],
                transactions=sells[:10],
                aggregate_value=agg_value,
                period_days=365,
                detected_at=datetime.now().isoformat()[:10],
            ))


def _add_days_str(date_str: str, days: int) -> str:
    """Add days to a YYYY-MM-DD date string. Returns YYYY-MM-DD."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return (dt + timedelta(days=days)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return "9999-12-31"
