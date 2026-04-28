"""PR-Q90 — Revert Q87 manual seed of Irish UCITS blue-chips.

Q87 (migration 0192) seeded 22 blue-chip Irish UCITS ETFs across 4 tables
(esma_funds + esma_securities + esma_isin_ticker_map + instruments_universe)
plus 4 esma_managers FK rows. Intent was to bridge the discovery gap from
ESMA Register Solr (which omits Irish UCITS).

Reverted because:
1. 22 funds is arbitrary — no principled criterion for inclusion/exclusion.
2. Manual seed maintenance does not scale to institutional production
   (real Irish UCITS universe is ~7,000 funds; Q87 covers <0.4%).
3. Workaround treats the symptom; root cause is missing data provider.
4. Top sponsor coverage gap (iShares/Vanguard/SPDR/Invesco) is better
   solved by integrating Central Bank of Ireland UCITS Register or
   Morningstar Direct as proper data ingestion sources.

Backlog Q91+: Central Bank of Ireland fund register provider.
Backlog Q92+: Morningstar Direct API integration.
Backlog Q93+: SEC EDGAR cross-reference for dual-listed UCITS ETFs.

Revision ID: 0193_q90_revert_q87_manual_seed
Revises: 0192_q87_irish_ucits_blue_chip_seed
Create Date: 2026-04-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0193_q90_revert_q87_manual_seed"
down_revision: str | None = "0192_q87_irish_ucits_blue_chip_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Order matters: child tables referencing instruments_universe must be
    # cleaned first; then ESMA chain (esma_isin_ticker_map -> esma_securities
    # -> esma_funds -> esma_managers).
    #
    # Pre-flight on DB local found only screening_results with Q87 refs (120
    # rows from prior screening_batch executions). Other potential children
    # (instrument_screening_metrics, fund_risk_metrics, instrument_identity,
    # nav_timeseries, instruments_org) were empty for Q87 instrument_ids,
    # but we DELETE defensively in case downstream environments differ.
    op.execute("""
        DELETE FROM screening_results
        WHERE instrument_id IN (
            SELECT instrument_id FROM instruments_universe
            WHERE (attributes->>'_q87_manual_seed')::bool = true
        )
    """)
    op.execute("""
        DELETE FROM instrument_screening_metrics
        WHERE instrument_id IN (
            SELECT instrument_id FROM instruments_universe
            WHERE (attributes->>'_q87_manual_seed')::bool = true
        )
    """)
    op.execute("""
        DELETE FROM fund_risk_metrics
        WHERE instrument_id IN (
            SELECT instrument_id FROM instruments_universe
            WHERE (attributes->>'_q87_manual_seed')::bool = true
        )
    """)
    op.execute("""
        DELETE FROM instrument_identity
        WHERE instrument_id IN (
            SELECT instrument_id FROM instruments_universe
            WHERE (attributes->>'_q87_manual_seed')::bool = true
        )
    """)
    op.execute("""
        DELETE FROM instruments_org
        WHERE instrument_id IN (
            SELECT instrument_id FROM instruments_universe
            WHERE (attributes->>'_q87_manual_seed')::bool = true
        )
    """)
    # nav_timeseries FK has no ON DELETE CASCADE (see 0011 migration). In
    # environments where instrument_ingestion (lock 900_010) ran after Q87
    # merge, it fetched daily NAV for the seeded tickers via Yahoo Finance.
    # Delete those rows before the instruments_universe parent delete.
    op.execute("""
        DELETE FROM nav_timeseries
        WHERE instrument_id IN (
            SELECT instrument_id FROM instruments_universe
            WHERE (attributes->>'_q87_manual_seed')::bool = true
        )
    """)
    op.execute(
        "DELETE FROM instruments_universe "
        "WHERE (attributes->>'_q87_manual_seed')::bool = true"
    )
    op.execute(
        "DELETE FROM esma_isin_ticker_map "
        "WHERE resolved_via = 'manual_seed_q87'"
    )
    op.execute(
        "DELETE FROM esma_securities "
        "WHERE fund_lei IN ("
        "  SELECT lei FROM esma_funds "
        "  WHERE classification_source = 'manual_seed'"
        ")"
    )
    op.execute(
        "DELETE FROM esma_funds "
        "WHERE classification_source = 'manual_seed'"
    )
    # Remove the 4 sponsor manager rows seeded by Q87 ONLY if no remaining
    # esma_funds reference them (preserves real ESMA Solr managers if they
    # happened to share the same ID in the future).
    op.execute("""
        DELETE FROM esma_managers
        WHERE esma_id IN ('C21345', 'C23431', 'C716', 'C51403')
          AND NOT EXISTS (
            SELECT 1 FROM esma_funds
            WHERE esma_funds.esma_manager_id = esma_managers.esma_id
          )
    """)


def downgrade() -> None:
    # No-op. Q87 manual seed is a deliberately discarded approach
    # (see module docstring). Re-applying it would require re-introducing
    # the workaround we are removing. If a future migration needs to
    # restore some subset of these funds, it should do so explicitly with
    # a new revision and updated rationale.
    pass
