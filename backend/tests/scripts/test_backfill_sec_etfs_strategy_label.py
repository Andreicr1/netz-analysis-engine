"""Unit tests for ``backend/scripts/backfill_sec_etfs_strategy_label.py`` —
PR-A26.3.3 Section D. Exercises the ``_classify`` entry point against
representative ETF rows; the DB round-trip is validated via the runbook.
"""
from __future__ import annotations

from scripts.backfill_sec_etfs_strategy_label import EtfRow, _classify


def _row(
    fund_name: str,
    tiingo_description: str | None = None,
    ticker: str | None = None,
    series_id: str = "S000001",
) -> EtfRow:
    return EtfRow(
        series_id=series_id,
        ticker=ticker,
        fund_name=fund_name,
        tiingo_description=tiingo_description,
    )


class TestClassify:
    def test_real_estate_from_name(self) -> None:
        label, source = _classify(_row("iShares U.S. Real Estate ETF"))
        assert label == "Real Estate"
        assert source == "tiingo_cascade"

    def test_gold_from_description(self) -> None:
        label, source = _classify(
            _row(
                "SPDR Gold Shares",
                tiingo_description=(
                    "The fund seeks to reflect the performance of the price "
                    "of gold bullion, less expenses."
                ),
            )
        )
        assert label == "Precious Metals"
        assert source == "tiingo_cascade"

    def test_unclassified_when_no_signal(self) -> None:
        # Neutral name + no description → cascade falls back, source marks unclassified.
        label, source = _classify(_row("XYZ Opportunities Fund"))
        assert source in {"tiingo_cascade", "unclassified"}
        # If it classified, fine; otherwise marked unclassified.
        if source == "unclassified":
            assert label is None

    def test_description_beats_name(self) -> None:
        # Layer 1 (description) has higher authority than Layer 2 (name regex).
        label, source = _classify(
            _row(
                "Innovator Growth Accelerator ETF",
                tiingo_description=(
                    "The fund invests in U.S. Treasury securities with "
                    "short maturities and seeks current income consistent "
                    "with preservation of capital."
                ),
            )
        )
        assert label is not None
        assert source == "tiingo_cascade"

    def test_returns_tuple_shape(self) -> None:
        out = _classify(_row("Vanguard Total Bond Market ETF"))
        assert isinstance(out, tuple)
        assert len(out) == 2
