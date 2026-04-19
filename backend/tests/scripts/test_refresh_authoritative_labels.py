"""Unit tests for the priority ladder in
``backend/scripts/refresh_authoritative_labels.py`` — PR-A26.3.2 Section E.

The DB integration test (seed + run + assert) is skipped by default; set
``RUN_DB_INTEGRATION=1`` and have docker-compose up to run it.
"""
from __future__ import annotations

import os

import pytest

from scripts.refresh_authoritative_labels import (
    SOURCE_BDC,
    SOURCE_ESMA,
    SOURCE_ETF,
    SOURCE_MMF,
    SOURCE_NEEDS_REVIEW,
    SOURCE_OVERRIDE,
    SOURCE_TIINGO,
    InstrumentRow,
    _resolve,
)


def _row(
    *,
    instrument_id: str = "11111111-1111-1111-1111-111111111111",
    ticker: str | None = None,
    isin: str | None = None,
    series_id: str | None = None,
    fund_name: str | None = None,
    sec_cik: str | None = None,
    current_label: str | None = None,
) -> InstrumentRow:
    return InstrumentRow(
        instrument_id=instrument_id,
        ticker=ticker,
        isin=isin,
        series_id=series_id,
        fund_name=fund_name,
        sec_cik=sec_cik,
        current_label=current_label,
    )


def _resolve_with(inst: InstrumentRow, **indexes):
    return _resolve(
        inst,
        overrides=indexes.get("overrides", {}),
        mmf=indexes.get("mmf", {}),
        etf_by_series=indexes.get("etf_by_series", {}),
        etf_by_ticker=indexes.get("etf_by_ticker", {}),
        bdc=indexes.get("bdc", {}),
        esma=indexes.get("esma", {}),
        tiingo=indexes.get("tiingo", {}),
    )


class TestOverridePriority:
    """PR-A26.3.5 Session 1 — priority-0 curator overrides bypass every
    downstream authoritative source.
    """

    def test_override_wins_over_etf_series(self) -> None:
        inst = _row(ticker="SCHD", series_id="S00099")
        result = _resolve_with(
            inst,
            overrides={"SCHD": ("Large Value", "Schwab Dividend — regression fix")},
            etf_by_series={"S00099": ("Real Estate", "Schwab Dividend ETF")},
            etf_by_ticker={"SCHD": ("Real Estate", "Schwab Dividend ETF")},
        )
        assert result.label == "Large Value"
        assert result.source == SOURCE_OVERRIDE
        assert result.source_table == "instrument_strategy_overrides"
        assert result.source_value == "SCHD"

    def test_override_wins_over_mmf(self) -> None:
        inst = _row(ticker="SCHB", series_id="S00100")
        result = _resolve_with(
            inst,
            overrides={"SCHB": ("Large Blend", "Schwab Broad Market — regression fix")},
            mmf={"S00100": ("Government", "spurious MMF match")},
        )
        assert result.label == "Large Blend"
        assert result.source == SOURCE_OVERRIDE

    def test_ft_vest_buffer_family_regex_fallback(self) -> None:
        for ticker in ("FJUL", "FAUG", "FJAN", "FDEC"):
            inst = _row(ticker=ticker)
            result = _resolve_with(inst)
            assert result.label == "Balanced", f"{ticker} should resolve to Balanced"
            assert result.source == SOURCE_OVERRIDE
            assert result.source_value == ticker

    def test_ft_vest_regex_does_not_match_unrelated_tickers(self) -> None:
        # "FOO" starts with F but isn't a 3-letter month code.
        inst = _row(ticker="FOO")
        result = _resolve_with(inst)
        assert result.source == SOURCE_NEEDS_REVIEW

    def test_override_skipped_when_ticker_missing(self) -> None:
        inst = _row(ticker=None, series_id="S00001")
        result = _resolve_with(
            inst,
            overrides={"ANYTHING": ("Large Blend", "n/a")},
            mmf={"S00001": ("Government", "mmf")},
        )
        assert result.source == SOURCE_MMF

    def test_exact_ticker_override_preferred_over_ft_vest_regex(self) -> None:
        # Sanity: exact table entry is checked before the FT Vest regex.
        inst = _row(ticker="FJUL")
        result = _resolve_with(
            inst,
            overrides={"FJUL": ("Large Blend", "explicit override trumps family regex")},
        )
        assert result.label == "Large Blend"
        assert result.reason == "explicit override trumps family regex"


class TestPriorityLadder:
    def test_mmf_wins_over_etf_when_both_match(self) -> None:
        inst = _row(series_id="S00001", ticker="ANY")
        result = _resolve_with(
            inst,
            mmf={"S00001": ("Government", "Schwab MMF")},
            etf_by_series={"S00001": ("Large Blend", "Schwab ETF")},
            etf_by_ticker={"ANY": ("Large Blend", "Schwab ETF")},
        )
        assert result.label == "Government Money Market"
        assert result.source == SOURCE_MMF

    def test_etf_series_wins_over_etf_ticker(self) -> None:
        inst = _row(series_id="S00002", ticker="XLF")
        result = _resolve_with(
            inst,
            etf_by_series={"S00002": ("Sector Equity", "XLF")},
            etf_by_ticker={"XLF": ("Large Blend", "fallback")},
        )
        assert result.label == "Sector Equity"
        assert result.source == SOURCE_ETF

    def test_etf_ticker_when_no_series_match(self) -> None:
        inst = _row(series_id=None, ticker="XLF")
        result = _resolve_with(
            inst,
            etf_by_ticker={"XLF": ("Sector Equity", "XLF")},
        )
        assert result.label == "Sector Equity"
        assert result.source == SOURCE_ETF

    def test_bdc_when_no_mmf_or_etf(self) -> None:
        inst = _row(series_id="S00003")
        result = _resolve_with(
            inst,
            bdc={"S00003": ("Private Credit (BDC)", "ARCC")},
        )
        assert result.label == "Private Credit"
        assert result.source == SOURCE_BDC

    def test_esma_skipped_when_isin_is_series_id(self) -> None:
        # IU rows for SEC funds reuse `isin` to store the series_id; the
        # ladder must NOT treat that as an ESMA bridge target.
        inst = _row(isin="S00009999")
        result = _resolve_with(
            inst,
            esma={"S00009999": ("Balanced", "trap")},
            tiingo={"11111111-1111-1111-1111-111111111111": "Real Estate"},
        )
        assert result.source == SOURCE_TIINGO
        assert result.label == "Real Estate"

    def test_esma_when_real_isin_and_no_sec_match(self) -> None:
        inst = _row(isin="LU0123456789")
        result = _resolve_with(
            inst,
            esma={"LU0123456789": ("Asian Equity", "JPM Asia")},
        )
        assert result.label == "Asian Equity"
        assert result.source == SOURCE_ESMA

    def test_tiingo_fallback_when_no_authoritative(self) -> None:
        inst = _row(ticker="XYZ")
        result = _resolve_with(
            inst,
            tiingo={"11111111-1111-1111-1111-111111111111": "Large Blend"},
        )
        assert result.label == "Large Blend"
        assert result.source == SOURCE_TIINGO

    def test_needs_review_when_nothing_matches(self) -> None:
        inst = _row(ticker="UNKNOWN")
        result = _resolve_with(inst)
        assert result.label is None
        assert result.source == SOURCE_NEEDS_REVIEW
        assert "no authoritative source" in result.reason

    def test_municipal_etf_skips_to_tiingo(self) -> None:
        # Municipal Bond is intentionally unmapped (PR-A24 excludes muni)
        inst = _row(series_id="S00004", ticker="VTEB")
        result = _resolve_with(
            inst,
            etf_by_series={"S00004": ("Municipal Bond", "VTEB")},
            tiingo={"11111111-1111-1111-1111-111111111111": "Inflation-Linked Bond"},
        )
        # ETF map returns None for Municipal Bond → ladder continues
        assert result.source == SOURCE_TIINGO
        assert result.label == "Inflation-Linked Bond"

    def test_target_date_esma_skips_to_tiingo(self) -> None:
        inst = _row(isin="IE00BD123456")
        result = _resolve_with(
            inst,
            esma={"IE00BD123456": ("Target Date", "iShares Lifepath")},
            tiingo={"11111111-1111-1111-1111-111111111111": "Balanced"},
        )
        assert result.source == SOURCE_TIINGO
        assert result.label == "Balanced"

    def test_regression_xlf_pattern(self) -> None:
        """XLF is the canonical contamination → fix case from the spec."""
        inst = _row(
            ticker="XLF",
            series_id="S000006411",
            current_label="Real Estate",  # Tiingo's contaminated label
        )
        result = _resolve_with(
            inst,
            etf_by_series={"S000006411": ("Sector Equity", "Financial SPDR")},
        )
        assert result.label == "Sector Equity"
        assert result.source == SOURCE_ETF
        # Confirms the contamination_resolved bookkeeping branch fires:
        assert inst.current_label != result.label


@pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION") != "1",
    reason="DB integration test — set RUN_DB_INTEGRATION=1 with docker-compose up",
)
@pytest.mark.asyncio
async def test_dry_run_against_dev_db_makes_no_writes() -> None:
    """End-to-end: confirms dry-run produces no writes to instruments_universe."""
    from sqlalchemy import text

    from app.core.db.engine import async_session_factory
    from scripts.refresh_authoritative_labels import run

    async with async_session_factory() as db:
        before = await db.execute(
            text(
                "SELECT COUNT(*) FROM instruments_universe "
                "WHERE attributes ? 'strategy_label_refreshed_at'"
            )
        )
        before_count = before.scalar_one()

    report = await run(apply=False)
    assert report["dry_run"] is True
    assert report["candidates"] > 0

    async with async_session_factory() as db:
        after = await db.execute(
            text(
                "SELECT COUNT(*) FROM instruments_universe "
                "WHERE attributes ? 'strategy_label_refreshed_at'"
            )
        )
        after_count = after.scalar_one()

    assert before_count == after_count, (
        f"Dry-run wrote refresh metadata: before={before_count} after={after_count}"
    )
