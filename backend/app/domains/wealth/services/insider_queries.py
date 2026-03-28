"""Insider sentiment score queries.

Reads from sec_insider_sentiment materialized view to compute a
0-100 score based on insider buy/sell activity (Officers + Directors only,
excluding 10% Owners). All queries are sync (matches DD report engine
context inside asyncio.to_thread()).

Score interpretation:
  > 50 — net buying pressure (bullish)
  = 50 — neutral (no data or balanced)
  < 50 — net selling pressure (bearish)
"""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = structlog.get_logger()


def get_insider_sentiment_score(
    db: Session,
    *,
    issuer_cik: str | None = None,
    issuer_ticker: str | None = None,
    lookback_quarters: int = 4,
) -> float:
    """Return insider_sentiment_score in [0, 100].

    Uses only Officer + Director transactions (excludes 10% Owner).
    Uses only informative codes: P (purchase) and S (sale).

    Parameters
    ----------
    db : Session
        Sync database session.
    issuer_cik : str | None
        Issuer CIK (primary lookup key).
    issuer_ticker : str | None
        Issuer ticker (fallback lookup key).
    lookback_quarters : int
        Number of quarters to look back (default 4).

    Returns
    -------
    float
        Score in [0, 100]. 50.0 means neutral/no data.

    """
    if not issuer_cik and not issuer_ticker:
        return 50.0

    try:
        if issuer_cik:
            rows = db.execute(
                text("""
                    SELECT buy_value, sell_value
                    FROM sec_insider_sentiment
                    WHERE issuer_cik = :cik
                      AND quarter >= (CURRENT_DATE - INTERVAL ':n quarters')::date
                    ORDER BY quarter DESC
                """.replace(":n quarters", f"{lookback_quarters} quarters")),
                {"cik": issuer_cik},
            ).fetchall()
        else:
            rows = db.execute(
                text("""
                    SELECT buy_value, sell_value
                    FROM sec_insider_sentiment
                    WHERE issuer_ticker = :ticker
                      AND quarter >= (CURRENT_DATE - INTERVAL ':n quarters')::date
                    ORDER BY quarter DESC
                """.replace(":n quarters", f"{lookback_quarters} quarters")),
                {"ticker": issuer_ticker},
            ).fetchall()

        if not rows:
            return 50.0

        buy_value = sum(
            float(r.buy_value) if r.buy_value is not None else 0.0
            for r in rows
        )
        sell_value = sum(
            float(r.sell_value) if r.sell_value is not None else 0.0
            for r in rows
        )
        total = buy_value + sell_value

        if total == 0:
            return 50.0

        net_buy_ratio = buy_value / total
        return round(net_buy_ratio * 100, 2)

    except Exception:
        logger.exception(
            "insider_sentiment_score_failed",
            issuer_cik=issuer_cik,
            issuer_ticker=issuer_ticker,
        )
        return 50.0


def get_insider_summary(
    db: Session,
    *,
    issuer_cik: str | None = None,
    issuer_ticker: str | None = None,
    lookback_quarters: int = 4,
) -> dict:
    """Return detailed insider activity summary for DD report narrative.

    Returns dict with buy_count, sell_count, buy_value, sell_value,
    unique_buyers, unique_sellers, score. Empty dict on error or no data.
    """
    if not issuer_cik and not issuer_ticker:
        return {}

    try:
        if issuer_cik:
            rows = db.execute(
                text("""
                    SELECT buy_count, sell_count, buy_value, sell_value,
                           unique_buyers, unique_sellers
                    FROM sec_insider_sentiment
                    WHERE issuer_cik = :cik
                      AND quarter >= (CURRENT_DATE - INTERVAL ':n quarters')::date
                    ORDER BY quarter DESC
                """.replace(":n quarters", f"{lookback_quarters} quarters")),
                {"cik": issuer_cik},
            ).fetchall()
        else:
            rows = db.execute(
                text("""
                    SELECT buy_count, sell_count, buy_value, sell_value,
                           unique_buyers, unique_sellers
                    FROM sec_insider_sentiment
                    WHERE issuer_ticker = :ticker
                      AND quarter >= (CURRENT_DATE - INTERVAL ':n quarters')::date
                    ORDER BY quarter DESC
                """.replace(":n quarters", f"{lookback_quarters} quarters")),
                {"ticker": issuer_ticker},
            ).fetchall()

        if not rows:
            return {}

        buy_count = sum(r.buy_count or 0 for r in rows)
        sell_count = sum(r.sell_count or 0 for r in rows)
        buy_value = sum(float(r.buy_value) if r.buy_value else 0.0 for r in rows)
        sell_value = sum(float(r.sell_value) if r.sell_value else 0.0 for r in rows)
        unique_buyers = sum(r.unique_buyers or 0 for r in rows)
        unique_sellers = sum(r.unique_sellers or 0 for r in rows)

        total = buy_value + sell_value
        score = round((buy_value / total) * 100, 2) if total > 0 else 50.0

        return {
            "buy_count": buy_count,
            "sell_count": sell_count,
            "buy_value": buy_value,
            "sell_value": sell_value,
            "unique_buyers": unique_buyers,
            "unique_sellers": unique_sellers,
            "score": score,
        }

    except Exception:
        logger.exception(
            "insider_summary_failed",
            issuer_cik=issuer_cik,
            issuer_ticker=issuer_ticker,
        )
        return {}
