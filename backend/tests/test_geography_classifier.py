"""Tests for the investment geography 3-layer cascade classifier."""

from __future__ import annotations

from app.domains.wealth.services.geography_classifier import (
    classify_from_nport_countries,
    classify_from_text,
    classify_geography,
)

# ── Layer 1: N-PORT ISIN country codes ───────────────────────────


class TestNportClassification:
    def test_us_dominant(self) -> None:
        assert classify_from_nport_countries({"US": 92.0, "GB": 5.0}) == "US"

    def test_europe_dominant(self) -> None:
        assert classify_from_nport_countries({"GB": 30.0, "DE": 25.0, "FR": 10.0}) == "Europe"

    def test_global_when_mixed(self) -> None:
        assert classify_from_nport_countries({"US": 40.0, "JP": 20.0, "GB": 15.0}) == "Global"

    def test_asia_pacific_dominant(self) -> None:
        assert classify_from_nport_countries({"JP": 35.0, "CN": 20.0, "AU": 10.0}) == "Asia Pacific"

    def test_emerging_markets(self) -> None:
        assert classify_from_nport_countries({"BR": 25.0, "MX": 20.0, "ZA": 10.0}) == "Emerging Markets"

    def test_empty_returns_none(self) -> None:
        assert classify_from_nport_countries({}) is None

    def test_unknown_countries_returns_none(self) -> None:
        assert classify_from_nport_countries({"XX": 50.0, "YY": 30.0}) is None


# ── Layer 2: Text keyword matching ──────────────────────────────


class TestTextClassification:
    def test_emerging_in_name(self) -> None:
        assert classify_from_text("Vanguard FTSE Emerging Markets ETF") == "Emerging Markets"

    def test_europe_in_strategy(self) -> None:
        assert classify_from_text("European Equity Large Cap") == "Europe"

    def test_japan_in_name(self) -> None:
        assert classify_from_text("WisdomTree Japan Hedged") == "Asia Pacific"

    def test_global_in_name(self) -> None:
        assert classify_from_text("MSCI World Index Fund") == "Global"

    def test_latam_in_name(self) -> None:
        assert classify_from_text("Latin America Growth Fund") == "Latin America"

    def test_us_in_name(self) -> None:
        assert classify_from_text("Domestic Large Cap Value") == "US"

    def test_ex_us(self) -> None:
        assert classify_from_text("MSCI EAFE ex-US Fund") == "Global"

    def test_none_returns_none(self) -> None:
        assert classify_from_text(None) is None

    def test_no_match_returns_none(self) -> None:
        assert classify_from_text("PRWCX Capital Appreciation") is None


# ── Full cascade ─────────────────────────────────────────────────


class TestClassifyGeography:
    def test_nport_takes_priority(self) -> None:
        """Layer 1 wins over Layer 2."""
        result = classify_geography(
            fund_name="European Equity Fund",
            nport_country_allocations={"US": 90.0},
        )
        assert result == "US"

    def test_strategy_label_over_default(self) -> None:
        """Layer 2 wins over Layer 3."""
        result = classify_geography(
            fund_name="PRWCX",
            strategy_label="Emerging Markets Equity",
            universe_type="registered_us",
        )
        assert result == "Emerging Markets"

    def test_default_us_for_registered(self) -> None:
        """Layer 3: registered US defaults to US."""
        result = classify_geography(
            fund_name="PRWCX Capital Appreciation",
            universe_type="registered_us",
        )
        assert result == "US"

    def test_default_europe_for_ucits(self) -> None:
        """Layer 3: UCITS with IE domicile defaults to Europe."""
        result = classify_geography(
            fund_name="BlackRock GF",
            universe_type="esma",
            domicile="IE",
        )
        assert result == "Europe"

    def test_default_global_for_hedge(self) -> None:
        """Layer 3: hedge funds default to Global."""
        result = classify_geography(
            fund_name="Alpha Partners Fund",
            fund_type="Hedge Fund",
        )
        assert result == "Global"

    def test_china_classified_as_em(self) -> None:
        result = classify_geography(fund_name="China Growth Opportunities")
        assert result == "Emerging Markets"

    def test_india_classified_as_em(self) -> None:
        result = classify_geography(fund_name="India Capital Fund")
        assert result == "Emerging Markets"

    def test_strategy_label_preferred_over_fund_name(self) -> None:
        """strategy_label is checked before fund_name."""
        result = classify_geography(
            strategy_label="Asia Pacific Equity",
            fund_name="US Growth Fund",
        )
        assert result == "Asia Pacific"
