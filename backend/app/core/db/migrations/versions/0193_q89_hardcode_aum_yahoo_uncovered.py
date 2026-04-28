"""PR-Q89 — Hardcode AUM for Q87 Irish UCITS funds Yahoo Finance does not cover.

Post Q87 merge (0192), 13/24 blue-chip share classes return
totalAssets=None + sharesOutstanding=None from Yahoo Finance.  This is a
structural data gap (deterministic across multiple queries), not a rate-limit
issue.

AUM values sourced from public factsheets (iShares, Vanguard, SPDR, Invesco)
and justETF fund profiles, snapshot date 2026-04-28.  EUR→USD at ~1.09.
Values are fund-level AUM (consistent with Yahoo totalAssets semantics).

Observability: aum_method='hardcoded_q89' + aum_factsheet_date='2026-04-28'
distinguish static-source rows for downstream audit.  Refresh quarterly
via follow-up migration when AUM drift > ±10%.

Revision ID: 0193_q89_hardcode_aum_yahoo_uncovered
Revises: 0192_q87_irish_ucits_blue_chip_seed
Create Date: 2026-04-28 23:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0193_q89_hardcode_aum_yahoo_uncovered"
down_revision: str | None = "0192_q87_irish_ucits_blue_chip_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Hardcoded AUM (USD) for Q87 funds Yahoo Finance structurally does not cover.
# Sources: public factsheets + justETF fund profiles, snapshot 2026-04-28.
# EUR→USD conversion at ~1.09 where source reports in EUR.
_HARDCODED_AUM: dict[str, tuple[int, str]] = {
    # (aum_usd, fund_name) — for audit traceability
    # ── iShares / BlackRock ──
    "IE00B5BMR087": (143_708_000_000, "iShares Core S&P 500 UCITS ETF USD (Acc)"),         # CSPX.L — iShares factsheet $143.7B
    "IE00B4L5Y983": (139_463_000_000, "iShares Core MSCI World UCITS ETF USD (Acc)"),       # SWDA.L — iShares factsheet $139.5B
    "IE00B4K48X80": (16_262_000_000, "iShares Core MSCI Europe UCITS ETF EUR (Acc)"),       # IMEU.L — justETF €14,919M × 1.09
    "IE00B3F81R35": (10_631_000_000, "iShares Core EUR Corp Bond UCITS ETF EUR (Dist)"),    # IEAC.L — justETF €9,753M × 1.09
    "IE00BDBRDM35": (2_637_000_000, "iShares Core Global Aggregate Bond UCITS ETF (Dist)"), # AGGG.L — justETF €2,419M × 1.09
    "IE00B4L5YX21": (6_817_000_000, "iShares Core MSCI Japan IMI UCITS ETF USD (Acc)"),     # IJPA.L — justETF €6,254M × 1.09
    "IE00B8FHGS14": (3_235_000_000, "iShares Edge MSCI World Min Vol UCITS ETF USD (Acc)"), # MVOL.L — iShares factsheet $3.2B
    # ── SPDR / State Street ──
    "IE00B6YX5C33": (18_000_000_000, "SPDR S&P 500 UCITS ETF USD (Dist)"),                  # SPY5.L — justETF €16,513M × 1.09
    "IE00BFY0GT14": (16_401_000_000, "SPDR MSCI World UCITS ETF USD (Acc)"),                 # SPPW.L — justETF €15,047M × 1.09
    "IE00B459R192": (169_000_000, "SPDR Bloomberg U.S. Aggregate Bond UCITS ETF (Dist)"),    # SUAG.L — justETF €155M × 1.09
    # ── Invesco ──
    "IE00B3YCGJ38": (34_913_000_000, "Invesco S&P 500 UCITS ETF USD (Acc)"),                # SPXP.L — justETF €32,030M × 1.09
    "IE0032077012": (17_335_000_000, "Invesco EQQQ NASDAQ-100 UCITS ETF USD (Acc)"),         # EQQQ.L — Invesco factsheet $17.3B
    # ── Vanguard ──
    "IE00BG47KH54": (2_128_000_000, "Vanguard Global Aggregate Bond UCITS ETF EUR Hedged"),  # VAGP.L — justETF €1,952M × 1.09
}


def upgrade() -> None:
    conn = op.get_bind()
    for isin, (aum_usd, _name) in _HARDCODED_AUM.items():
        conn.execute(
            text("""
                UPDATE instruments_universe
                SET attributes = attributes || jsonb_build_object(
                    'aum_usd', :aum_usd,
                    'aum_native', :aum_usd,
                    'aum_native_currency', 'USD',
                    'aum_source', 'public_factsheet',
                    'aum_method', 'hardcoded_q89',
                    'aum_fetched_at', NOW()::text,
                    'aum_degraded', false,
                    'aum_degraded_reason', NULL,
                    'aum_factsheet_date', '2026-04-28'
                )
                WHERE isin = :isin
                  AND (attributes->>'_q87_manual_seed')::bool = true
            """),
            {"isin": isin, "aum_usd": aum_usd},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for isin in _HARDCODED_AUM:
        conn.execute(
            text("""
                UPDATE instruments_universe
                SET attributes = attributes - 'aum_usd'
                                            - 'aum_native'
                                            - 'aum_native_currency'
                                            - 'aum_source'
                                            - 'aum_method'
                                            - 'aum_fetched_at'
                                            - 'aum_degraded'
                                            - 'aum_degraded_reason'
                                            - 'aum_factsheet_date'
                WHERE isin = :isin
                  AND attributes->>'aum_method' = 'hardcoded_q89'
            """),
            {"isin": isin},
        )
