"""PR-A26.3.5 Session 1 — instrument_strategy_overrides.

Canonical curator-maintained overrides for the authoritative refresh
pipeline (priority 0). Populated with ~48 institutional tickers that the
Tiingo-description cascade mislabels today (SCHD/QQQM/SCHB/VMIAX/FJUL/
AGG/XLF + 41 peers).

Global table, no RLS. ``strategy_label`` is free-text and must match a
key in ``vertical_engines.wealth.model_portfolio.block_mapping.
STRATEGY_LABEL_TO_BLOCKS`` (enforced by upstream validator, not by DB
constraint — keeping the table mapping-layer agnostic).

Reversible.
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0158_instrument_strategy_overrides"
down_revision = "0157_fuzzy_bridge_audit"
branch_labels = None
depends_on = None


SEED_OVERRIDES: tuple[tuple[str, str, str], ...] = (
    # ── Equity US — Large Blend ──
    ("SPY", "Large Blend", "SPDR S&P 500 ETF Trust"),
    ("IVV", "Large Blend", "iShares Core S&P 500 ETF"),
    ("VOO", "Large Blend", "Vanguard S&P 500 ETF"),
    ("VTI", "Large Blend", "Vanguard Total Stock Market ETF"),
    ("SCHB", "Large Blend", "Schwab U.S. Broad Market ETF — regression fix, mislabeled Cash Equivalent"),
    ("ITOT", "Large Blend", "iShares Core S&P Total U.S. Stock Market ETF"),
    # ── Equity US — Large Growth ──
    ("QQQ", "Large Growth", "Invesco QQQ Trust"),
    ("QQQM", "Large Growth", "Invesco NASDAQ 100 ETF — regression fix, mislabeled Real Estate"),
    ("VUG", "Large Growth", "Vanguard Growth ETF"),
    ("IWF", "Large Growth", "iShares Russell 1000 Growth ETF"),
    ("SCHG", "Large Growth", "Schwab U.S. Large-Cap Growth ETF"),
    # ── Equity US — Large Value ──
    ("VTV", "Large Value", "Vanguard Value ETF"),
    ("IWD", "Large Value", "iShares Russell 1000 Value ETF"),
    ("SCHV", "Large Value", "Schwab U.S. Large-Cap Value ETF"),
    ("SCHD", "Large Value", "Schwab U.S. Dividend Equity ETF — regression fix, mislabeled Real Estate"),
    # ── Equity US — Small/Mid ──
    ("IWM", "Small Blend", "iShares Russell 2000 ETF"),
    ("VB", "Small Blend", "Vanguard Small-Cap ETF"),
    ("IJR", "Small Blend", "iShares Core S&P Small-Cap ETF"),
    ("VO", "Mid-Cap Blend", "Vanguard Mid-Cap ETF"),
    # ── Equity DM (Europe / Asia) ──
    ("EFA", "Foreign Large Blend", "iShares MSCI EAFE ETF — regression fix"),
    ("VEA", "Foreign Large Blend", "Vanguard Developed Markets ETF"),
    ("IEFA", "Foreign Large Blend", "iShares Core MSCI EAFE ETF"),
    ("VXUS", "Foreign Large Blend", "Vanguard Total International Stock ETF"),
    ("FEZ", "Europe Stock", "SPDR EURO STOXX 50 ETF — regression fix"),
    # ── Equity EM ──
    ("EEM", "Diversified Emerging Mkts", "iShares MSCI Emerging Markets ETF"),
    ("VWO", "Diversified Emerging Mkts", "Vanguard FTSE Emerging Markets ETF"),
    ("IEMG", "Diversified Emerging Mkts", "iShares Core MSCI Emerging Markets ETF"),
    # ── FI US Aggregate ──
    ("AGG", "Intermediate Core Bond", "iShares Core U.S. Aggregate Bond ETF — regression fix, mislabeled Government Bond"),
    ("BND", "Intermediate Core Bond", "Vanguard Total Bond Market ETF"),
    ("SCHZ", "Intermediate Core Bond", "Schwab U.S. Aggregate Bond ETF"),
    # ── FI US Treasury ──
    ("TLT", "Long Government", "iShares 20+ Year Treasury Bond ETF"),
    ("IEF", "Intermediate Government", "iShares 7-10 Year Treasury Bond ETF"),
    ("SHY", "Short Government", "iShares 1-3 Year Treasury Bond ETF"),
    ("GOVT", "Intermediate Government", "iShares U.S. Treasury Bond ETF"),
    # ── FI TIPS / HY / IG ──
    ("TIP", "Inflation-Protected Bond", "iShares TIPS Bond ETF"),
    ("SCHP", "Inflation-Protected Bond", "Schwab U.S. TIPS ETF"),
    ("HYG", "High Yield Bond", "iShares iBoxx High Yield Corporate Bond ETF"),
    ("JNK", "High Yield Bond", "SPDR Bloomberg High Yield Bond ETF"),
    ("LQD", "Corporate Bond", "iShares iBoxx Investment Grade Corporate Bond ETF"),
    # ── Alt — Commodities / Gold ──
    ("DBC", "Commodities Broad Basket", "Invesco DB Commodity Index Tracking Fund"),
    ("GSG", "Commodities Broad Basket", "iShares S&P GSCI Commodity-Indexed Trust"),
    ("GLD", "Precious Metals", "SPDR Gold Shares"),
    ("IAU", "Precious Metals", "iShares Gold Trust"),
    # ── Alt — Real Estate ──
    ("VNQ", "Real Estate", "Vanguard Real Estate ETF"),
    ("SCHH", "Real Estate", "Schwab U.S. REIT ETF"),
    # ── Sector Equity (regression fixes) ──
    ("XLF", "Sector Equity", "Financial Select Sector SPDR Fund — regression fix, mislabeled Real Estate"),
    ("XLE", "Sector Equity", "Energy Select Sector SPDR Fund"),
    ("XLK", "Sector Equity", "Technology Select Sector SPDR Fund"),
    ("XLV", "Sector Equity", "Health Care Select Sector SPDR Fund"),
    ("VMIAX", "Sector Equity", "Vanguard Materials Index Fund — regression fix, mislabeled Precious Metals"),
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE instrument_strategy_overrides (
            ticker TEXT PRIMARY KEY,
            strategy_label TEXT NOT NULL,
            rationale TEXT NOT NULL,
            curated_by TEXT NOT NULL DEFAULT 'seed_migration',
            curated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    bind = op.get_bind()
    stmt = text(
        "INSERT INTO instrument_strategy_overrides "
        "(ticker, strategy_label, rationale, curated_by) "
        "VALUES (:ticker, :label, :rationale, 'seed_migration') "
        "ON CONFLICT (ticker) DO NOTHING"
    )
    for ticker, label, rationale in SEED_OVERRIDES:
        bind.execute(stmt, {"ticker": ticker, "label": label, "rationale": rationale})


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS instrument_strategy_overrides")
