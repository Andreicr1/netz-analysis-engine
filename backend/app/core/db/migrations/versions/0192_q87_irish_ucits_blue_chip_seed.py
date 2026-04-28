"""PR-Q87 — Irish UCITS blue-chip seed table (high-impact coverage).

ESMA Register Solr does not include Irish-domiciled UCITS — only 2 IE funds
out of 10,436 in the register.  Major sponsors (iShares ~$700B, Vanguard
~$300B, SPDR ~$200B, Invesco ~$50B in UCITS AUM) are all Irish-domiciled
and entirely missing from the engine.

This migration seeds 22 GLEIF-verified Irish UCITS blue-chip ETFs across
4 coordinated tables:
  - esma_funds: LEI-keyed entries with classification_source='manual_seed'
  - esma_securities: share-class ISINs FK'd to fund LEI (24 share classes)
  - esma_isin_ticker_map: ticker resolution with resolved_via='manual_seed_q87'
  - instruments_universe: fund-type entries with _q87_manual_seed=true marker

LEIs verified against GLEIF API (status=ISSUED) before commit.
ISINs verified against issuer factsheets.
Tickers verified via Yahoo Finance listing lookup.

Strategy C option 3 from FINDINGS Q78b.  Long-term: Strategy C option 1
(Central Bank of Ireland provider) as PR-Q88+.

Revision ID: 0191_q87_irish_ucits_blue_chip_seed
Revises: 0190_screening_runs_allow_watchlist
Create Date: 2026-04-28 20:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0192_q87_irish_ucits_blue_chip_seed"
down_revision: str | None = "0191_q85_reprioritize_esma_tickers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ── Verified seed data ───────────────────────────────────────────
# Each tuple: (lei, fund_name, esma_manager_id, yahoo_ticker)
# LEIs verified against GLEIF API (all status=ISSUED, country=IE).
# esma_manager_id values confirmed in local DB esma_managers table.
_FUNDS: list[tuple[str, str, str, str]] = [
    # ── iShares / BlackRock (C21345) ──
    ("5493006ESS9BM09FB892", "iShares Core S&P 500 UCITS ETF", "C21345", "CSPX.L"),
    ("54930084HRJY26SCMW95", "iShares Core S&P 500 UCITS ETF USD (Dist)", "C21345", "IUSA.L"),
    ("549300QS4Q1IT6XCA514", "iShares Core MSCI World UCITS ETF", "C21345", "SWDA.L"),
    ("549300HAPVPBRLCT6I96", "iShares Core MSCI EM IMI UCITS ETF", "C21345", "EIMI.L"),
    ("549300DUUSUNHLKQFH49", "iShares Core MSCI Europe UCITS ETF EUR (Acc)", "C21345", "IMEU.L"),
    ("549300782C9C8O0ENH86", "iShares Core EUR Corp Bond UCITS ETF", "C21345", "IEAC.L"),
    ("5493004Z4IROQYVVZZ47", "iShares Core Global Aggregate Bond UCITS ETF", "C21345", "AGGG.L"),
    ("549300YHIXN3L7FNZG03", "iShares Core MSCI Japan IMI UCITS ETF", "C21345", "IJPA.L"),
    ("549300JYU88HR0UW6N22", "iShares Edge MSCI World Quality Factor UCITS ETF", "C21345", "IWQU.L"),
    ("549300WL2LLLS7HFSV96", "iShares Edge MSCI World Minimum Volatility UCITS ETF", "C21345", "MVOL.L"),
    # ── Vanguard (C23431) ──
    ("EEXSPYGY7X8YAH8ZJF49", "Vanguard FTSE All-World UCITS ETF", "C23431", "VWRL.L"),
    ("B8GS85IADJB33D8WL305", "Vanguard S&P 500 UCITS ETF", "C23431", "VUSA.L"),
    ("549300UOT4V4L4YMCN45", "Vanguard FTSE Developed World UCITS ETF", "C23431", "VEVE.L"),
    ("NV9M4O28LWYSNOU5C468", "Vanguard FTSE Emerging Markets UCITS ETF", "C23431", "VFEM.L"),
    ("549300H52HCNP55DFN76", "Vanguard FTSE Developed Europe UCITS ETF", "C23431", "VEUR.L"),
    ("549300PDJ4F2JCB3E384", "Vanguard Global Aggregate Bond UCITS ETF", "C23431", "VAGP.L"),
    # ── SPDR / State Street (C716) ──
    ("549300F1TODGOV4WQV40", "SPDR S&P 500 UCITS ETF", "C716", "SPY5.L"),
    ("549300RZKVPV4X7OVS36", "SPDR MSCI World UCITS ETF", "C716", "SPPW.L"),
    ("549300K1O2DF9UGEON92", "SPDR Bloomberg U.S. Aggregate Bond UCITS ETF", "C716", "SUAG.L"),
    # ── Invesco (C51403) ──
    ("635400KZRKKKNVCJXD85", "Invesco S&P 500 UCITS ETF", "C51403", "SPXP.L"),
    ("6354007BW1OH9AUD2H21", "Invesco MSCI World UCITS ETF", "C51403", "MXFP.L"),
    ("549300G3HDTLNIY9YW25", "Invesco EQQQ NASDAQ-100 UCITS ETF", "C51403", "EQQQ.L"),
]

# Each tuple: (isin, fund_lei, full_name, currency)
# Primary share class per fund + Vanguard Acc variants.
_SECURITIES: list[tuple[str, str, str, str]] = [
    # ── iShares ──
    ("IE00B5BMR087", "5493006ESS9BM09FB892", "iShares Core S&P 500 UCITS ETF USD (Acc)", "USD"),
    ("IE0031442068", "54930084HRJY26SCMW95", "iShares Core S&P 500 UCITS ETF USD (Dist)", "USD"),
    ("IE00B4L5Y983", "549300QS4Q1IT6XCA514", "iShares Core MSCI World UCITS ETF USD (Acc)", "USD"),
    ("IE00BKM4GZ66", "549300HAPVPBRLCT6I96", "iShares Core MSCI EM IMI UCITS ETF USD (Acc)", "USD"),
    ("IE00B4K48X80", "549300DUUSUNHLKQFH49", "iShares Core MSCI Europe UCITS ETF EUR (Acc)", "EUR"),
    ("IE00B3F81R35", "549300782C9C8O0ENH86", "iShares Core EUR Corp Bond UCITS ETF EUR (Dist)", "EUR"),
    ("IE00BDBRDM35", "5493004Z4IROQYVVZZ47", "iShares Core Global Aggregate Bond UCITS ETF USD (Dist)", "USD"),
    ("IE00B4L5YX21", "549300YHIXN3L7FNZG03", "iShares Core MSCI Japan IMI UCITS ETF USD (Acc)", "USD"),
    ("IE00BP3QZ601", "549300JYU88HR0UW6N22", "iShares Edge MSCI World Quality Factor UCITS ETF USD (Acc)", "USD"),
    ("IE00B8FHGS14", "549300WL2LLLS7HFSV96", "iShares Edge MSCI World Minimum Volatility UCITS ETF USD (Acc)", "USD"),
    # ── Vanguard (primary + Acc variants) ──
    ("IE00B3RBWM25", "EEXSPYGY7X8YAH8ZJF49", "Vanguard FTSE All-World UCITS ETF USD (Dist)", "USD"),
    ("IE00BK5BQT80", "EEXSPYGY7X8YAH8ZJF49", "Vanguard FTSE All-World UCITS ETF USD (Acc)", "USD"),
    ("IE00B3XXRP09", "B8GS85IADJB33D8WL305", "Vanguard S&P 500 UCITS ETF USD (Dist)", "USD"),
    ("IE00BFMXXD54", "B8GS85IADJB33D8WL305", "Vanguard S&P 500 UCITS ETF USD (Acc)", "USD"),
    ("IE00BKX55T58", "549300UOT4V4L4YMCN45", "Vanguard FTSE Developed World UCITS ETF USD (Acc)", "USD"),
    ("IE00B3VVMM84", "NV9M4O28LWYSNOU5C468", "Vanguard FTSE Emerging Markets UCITS ETF USD (Dist)", "USD"),
    ("IE00B945VV12", "549300H52HCNP55DFN76", "Vanguard FTSE Developed Europe UCITS ETF EUR (Dist)", "EUR"),
    ("IE00BG47KH54", "549300PDJ4F2JCB3E384", "Vanguard Global Aggregate Bond UCITS ETF EUR Hedged (Dist)", "EUR"),
    # ── SPDR ──
    ("IE00B6YX5C33", "549300F1TODGOV4WQV40", "SPDR S&P 500 UCITS ETF USD (Dist)", "USD"),
    ("IE00BFY0GT14", "549300RZKVPV4X7OVS36", "SPDR MSCI World UCITS ETF USD (Acc)", "USD"),
    ("IE00B459R192", "549300K1O2DF9UGEON92", "SPDR Bloomberg U.S. Aggregate Bond UCITS ETF USD (Dist)", "USD"),
    # ── Invesco ──
    ("IE00B3YCGJ38", "635400KZRKKKNVCJXD85", "Invesco S&P 500 UCITS ETF USD (Acc)", "USD"),
    ("IE00B60SX394", "6354007BW1OH9AUD2H21", "Invesco MSCI World UCITS ETF USD (Acc)", "USD"),
    ("IE0032077012", "549300G3HDTLNIY9YW25", "Invesco EQQQ NASDAQ-100 UCITS ETF USD (Acc)", "USD"),
]

# Each tuple: (isin, yahoo_ticker, exchange)
_TICKER_MAP: list[tuple[str, str, str]] = [
    ("IE00B5BMR087", "CSPX.L", "LSE"),
    ("IE0031442068", "IUSA.L", "LSE"),
    ("IE00B4L5Y983", "SWDA.L", "LSE"),
    ("IE00BKM4GZ66", "EIMI.L", "LSE"),
    ("IE00B4K48X80", "IMEU.L", "LSE"),
    ("IE00B3F81R35", "IEAC.L", "LSE"),
    ("IE00BDBRDM35", "AGGG.L", "LSE"),
    ("IE00B4L5YX21", "IJPA.L", "LSE"),
    ("IE00BP3QZ601", "IWQU.L", "LSE"),
    ("IE00B8FHGS14", "MVOL.L", "LSE"),
    ("IE00B3RBWM25", "VWRL.L", "LSE"),
    ("IE00BK5BQT80", "VWRA.L", "LSE"),
    ("IE00B3XXRP09", "VUSA.L", "LSE"),
    ("IE00BFMXXD54", "VUAA.L", "LSE"),
    ("IE00BKX55T58", "VEVE.L", "LSE"),
    ("IE00B3VVMM84", "VFEM.L", "LSE"),
    ("IE00B945VV12", "VEUR.L", "LSE"),
    ("IE00BG47KH54", "VAGP.L", "LSE"),
    ("IE00B6YX5C33", "SPY5.L", "LSE"),
    ("IE00BFY0GT14", "SPPW.L", "LSE"),
    ("IE00B459R192", "SUAG.L", "LSE"),
    ("IE00B3YCGJ38", "SPXP.L", "LSE"),
    ("IE00B60SX394", "MXFP.L", "LSE"),
    ("IE0032077012", "EQQQ.L", "LSE"),
]

# Build a lookup: lei -> (fund_name, manager_name, ticker)
_FUND_BY_LEI = {lei: (name, mgr, ticker) for lei, name, mgr, ticker in _FUNDS}

# Manager display names for instruments_universe attributes
_MANAGER_NAMES = {
    "C21345": "BlackRock Asset Management Ireland Limited",
    "C23431": "Vanguard Group (Ireland) Limited",
    "C716": "State Street Global Advisors Europe Limited",
    "C51403": "Invesco Investment Management Limited",
}

# Classify asset_class from fund name
def _asset_class(name: str) -> str:
    name_lower = name.lower()
    if any(kw in name_lower for kw in ("bond", "aggregate", "corp bond", "treasury")):
        return "fixed_income"
    return "equity"


# Classify investment_geography from fund name
def _inv_geography(name: str) -> str:
    name_lower = name.lower()
    if "all-world" in name_lower or "world" in name_lower or "global" in name_lower:
        return "Global"
    if "s&p 500" in name_lower or "nasdaq" in name_lower or "usa" in name_lower or "u.s." in name_lower:
        return "north_america"
    if "europe" in name_lower:
        return "dm_europe"
    if "emerging" in name_lower or " em " in name_lower:
        return "em_broad"
    if "japan" in name_lower:
        return "dm_asia"
    if "ftse 100" in name_lower:
        return "dm_europe"
    return "Global"


def upgrade() -> None:
    # ── 0. esma_managers — seed 4 sponsor IDs (FK requirement for esma_funds) ──
    # Without this, fresh CI/staging environments fail the esma_funds INSERT
    # with FK violation (esma_managers populated only when ESMA Solr ingest
    # has run, which doesn't happen in test environments).
    op.execute("""
        INSERT INTO esma_managers (esma_id, company_name, country, data_fetched_at)
        VALUES
          ('C21345', 'BlackRock Asset Management Ireland Limited', 'IE', NOW()),
          ('C23431', 'Vanguard Group (Ireland) Limited', 'IE', NOW()),
          ('C716',   'State Street Global Advisors Europe Limited', 'IE', NOW()),
          ('C51403', 'Invesco Investment Management Limited', 'IE', NOW())
        ON CONFLICT (esma_id) DO NOTHING
    """)

    # ── 1. esma_funds — one row per LEI ──
    fund_values = []
    for lei, name, mgr, ticker in _FUNDS:
        fund_values.append(
            f"('{lei}', '{lei}', $${name}$$, '{mgr}', 'IE', 'UCITS', "
            f"'{ticker}', true, 'manual_seed', NOW(), NOW())"
        )
    op.execute(
        "INSERT INTO esma_funds "
        "(lei, legacy_isin_misnamed, fund_name, esma_manager_id, domicile, "
        "fund_type, yahoo_ticker, is_institutional, classification_source, "
        "sanitized_at, data_fetched_at) VALUES\n"
        + ",\n".join(fund_values)
        + "\nON CONFLICT (lei) DO NOTHING"
    )

    # ── 2. esma_securities — one row per ISIN (share class) ──
    sec_values = []
    for isin, fund_lei, full_name, currency in _SECURITIES:
        sec_values.append(
            f"('{isin}', '{fund_lei}', $${full_name}$$, '{currency}', "
            f"true, NOW(), NOW(), NOW())"
        )
    op.execute(
        "INSERT INTO esma_securities "
        "(isin, fund_lei, full_name, currency, is_active, "
        "data_fetched_at, first_seen_at, last_seen_at) VALUES\n"  # noqa: COM812
        + ",\n".join(sec_values)
        + "\nON CONFLICT (isin) DO NOTHING"
    )

    # ── 3. esma_isin_ticker_map — one row per ISIN ──
    map_values = []
    for isin, ticker, exchange in _TICKER_MAP:
        # Find fund_lei from securities list
        fund_lei = next(
            (fl for i, fl, _, _ in _SECURITIES if i == isin), None,
        )
        lei_sql = f"'{fund_lei}'" if fund_lei else "NULL"
        map_values.append(
            f"('{isin}', '{ticker}', '{exchange}', true, "
            f"'manual_seed_q87', {lei_sql}, NOW())"
        )
    op.execute(
        "INSERT INTO esma_isin_ticker_map "
        "(isin, yahoo_ticker, exchange, is_tradeable, resolved_via, "
        "fund_lei, last_verified_at) VALUES\n"
        + ",\n".join(map_values)
        + "\nON CONFLICT (isin) DO NOTHING"
    )

    # ── 4. instruments_universe — one row per ISIN ──
    # Build ISIN→ticker lookup from _TICKER_MAP (share-class level)
    _isin_to_ticker = {i: t for i, t, _ in _TICKER_MAP}

    inst_values = []
    for isin, fund_lei, full_name, currency in _SECURITIES:
        # Always resolve ticker from _TICKER_MAP (per-ISIN), not fund-level
        ticker = _isin_to_ticker.get(isin)
        # Resolve manager from fund
        fund_info = _FUND_BY_LEI.get(fund_lei)
        if fund_info:
            _, mgr_id, _ = fund_info
        else:
            mgr_id = next(
                (f[2] for f in _FUNDS if f[0] == fund_lei), "C21345",
            )

        mgr_name = _MANAGER_NAMES.get(mgr_id, mgr_id)
        ac = _asset_class(full_name)
        inv_geo = _inv_geography(full_name)
        geo = "dm_europe"  # Domicile geography — all IE

        attrs = (
            f'{{"name": {_json_str(full_name)}, '
            f'"fund_subtype": "ucits", '
            f'"structure": "UCITS", '
            f'"domicile": "IE", '
            f'"esma_lei": "{fund_lei}", '
            f'"is_ucits_etf": true, '
            f'"manager_name": {_json_str(mgr_name)}, '
            f'"aum_usd": null, '
            f'"inception_date": null, '
            f'"is_institutional": true, '
            f'"_q87_manual_seed": true}}'
        )

        ticker_sql = f"'{ticker}'" if ticker else "NULL"
        inst_values.append(
            f"(gen_random_uuid(), 'fund', $${full_name}$$, '{isin}', "
            f"{ticker_sql}, '{ac}', '{geo}', '{currency}', '{inv_geo}', "
            f"true, '{attrs}'::jsonb, NOW(), NOW())"
        )
    # ON CONFLICT (instrument_id): instrument_id is PK (always present in any
    # schema). gen_random_uuid() never produces collision with existing rows,
    # so effectively a no-op idempotency wrapper — but syntactically valid in
    # both local DB (with manual uq_iu_isin) and CI fresh DB (without).
    # Original ON CONFLICT (isin) failed in CI because uq_iu_isin is not
    # defined in any migration — exists only via legacy manual setup locally.
    op.execute(
        "INSERT INTO instruments_universe "
        "(instrument_id, instrument_type, name, isin, ticker, "
        "asset_class, geography, currency, investment_geography, "
        "is_active, attributes, created_at, updated_at) VALUES\n"
        + ",\n".join(inst_values)
        + "\nON CONFLICT (instrument_id) DO NOTHING"
    )


def downgrade() -> None:
    # Order matters: instruments_universe -> esma_isin_ticker_map ->
    # esma_securities -> esma_funds (FK chain)
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
    # Remove seed managers only if no remaining funds reference them.
    # Real ESMA Solr ingest may have populated these same IDs — do not delete
    # if other funds (esma_solr) still reference them.
    op.execute("""
        DELETE FROM esma_managers
        WHERE esma_id IN ('C21345', 'C23431', 'C716', 'C51403')
          AND NOT EXISTS (
            SELECT 1 FROM esma_funds
            WHERE esma_funds.esma_manager_id = esma_managers.esma_id
          )
    """)


def _json_str(s: str) -> str:
    """Escape a string for use inside a JSON value."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
