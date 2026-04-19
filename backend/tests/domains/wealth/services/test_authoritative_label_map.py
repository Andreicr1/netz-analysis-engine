"""Unit tests for ``authoritative_label_map`` — PR-A26.3.2 Section B."""
from __future__ import annotations

import pytest

from app.domains.wealth.services import authoritative_label_map as m
from vertical_engines.wealth.model_portfolio.block_mapping import (
    STRATEGY_LABEL_TO_BLOCKS,
)


class TestMmfMapping:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Government", "Government Money Market"),
            ("Prime", "Prime Money Market"),
            ("Other Tax Exempt", "Tax-Exempt Money Market"),
            ("Single State", "Single State Money Market"),
        ],
    )
    def test_known_categories(self, raw: str, expected: str) -> None:
        result = m.map_mmf_category(raw)
        assert result.label == expected
        assert result.reason == "sec_mmf"

    def test_null_returns_none(self) -> None:
        result = m.map_mmf_category(None)
        assert result.label is None
        assert "null" in result.reason

    def test_unknown_returns_none_with_reason(self) -> None:
        result = m.map_mmf_category("WeirdNewCategory")
        assert result.label is None
        assert "unknown mmf_category" in result.reason


class TestEtfMapping:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Large Blend", "Large Blend"),
            ("Intermediate-Term Bond", "Intermediate-Term Bond"),
            ("Sector Equity", "Sector Equity"),
            ("ESG/Sustainable Equity", "ESG/Sustainable Equity"),
            ("Real Estate", "Real Estate"),
            ("Precious Metals", "Precious Metals"),
        ],
    )
    def test_clean_passthrough(self, raw: str, expected: str) -> None:
        result = m.map_etf_label(raw)
        assert result.label == expected
        assert result.reason == "sec_etf"

    def test_municipal_intentionally_unmapped(self) -> None:
        result = m.map_etf_label("Municipal Bond")
        assert result.label is None
        assert "muni excluded" in result.reason

    def test_unknown_label_unmapped(self) -> None:
        result = m.map_etf_label("Sci-Fi Equity")
        assert result.label is None
        assert "unmapped sec_etfs label" in result.reason


class TestBdcMapping:
    @pytest.mark.parametrize(
        "raw",
        ["Private Credit (BDC)", "BDC", "Growth / Venture (BDC)"],
    )
    def test_all_bdcs_collapse_to_private_credit(self, raw: str) -> None:
        result = m.map_bdc_label(raw)
        assert result.label == "Private Credit"
        assert result.reason == "sec_bdc"


class TestEsmaMapping:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("International Equity", "International Equity"),
            ("Balanced", "Balanced"),
            ("Asian Equity", "Asian Equity"),
            ("ESG/Sustainable Bond", "ESG/Sustainable Bond"),
        ],
    )
    def test_clean_passthrough(self, raw: str, expected: str) -> None:
        result = m.map_esma_label(raw)
        assert result.label == expected
        assert result.reason == "esma_funds"

    @pytest.mark.parametrize(
        "raw",
        ["Target Date", "Convertible Securities", "European Bond", "Municipal Bond"],
    )
    def test_known_review_buckets_unmapped(self, raw: str) -> None:
        result = m.map_esma_label(raw)
        assert result.label is None
        assert result.reason  # explicit reason set


class TestBlockMappingCoverage:
    def test_no_canonical_label_orphaned(self) -> None:
        """Every label the map can emit MUST exist in block_mapping.py."""
        missing = m.assert_block_mapping_coverage()
        assert missing == [], (
            f"Authoritative map emits canonical labels not present in "
            f"STRATEGY_LABEL_TO_BLOCKS: {missing}"
        )

    def test_all_canonical_labels_have_at_least_one_block(self) -> None:
        for label in m.all_canonical_labels():
            blocks = STRATEGY_LABEL_TO_BLOCKS.get(label, [])
            assert blocks, f"Canonical label {label!r} maps to empty block list"
