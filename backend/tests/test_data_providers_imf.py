"""Tests for IMF WEO data provider — GDP growth, inflation, fiscal balance, govt debt.

Covers:
- ImfForecast frozen dataclass creation and immutability
- ISO3 → ISO2 country code mapping completeness
- fetch_imf_indicator() JSON parsing with mocked httpx responses
- fetch_all_imf_data() aggregation across 4 indicators
- HTTP error handling (status errors, connection errors, invalid JSON)
- Edge cases: missing countries, non-numeric values, empty responses
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from data_providers.imf.service import (
    COUNTRIES,
    INDICATORS,
    ISO3_TO_ISO2,
    ImfForecast,
    fetch_all_imf_data,
    fetch_imf_indicator,
)


# ── ImfForecast Dataclass ─────────────────────────────────────────────


class TestImfForecast:
    def test_creation(self):
        f = ImfForecast(
            country_code="US",
            indicator="NGDP_RPCH",
            year=2024,
            value=2.1,
            edition="202604",
        )
        assert f.country_code == "US"
        assert f.indicator == "NGDP_RPCH"
        assert f.year == 2024
        assert f.value == 2.1
        assert f.edition == "202604"

    def test_frozen_immutability(self):
        f = ImfForecast(
            country_code="BR",
            indicator="PCPIPCH",
            year=2025,
            value=4.5,
            edition="202604",
        )
        with pytest.raises(AttributeError):
            f.value = 99.9  # type: ignore[misc]

    def test_equality(self):
        kwargs = dict(
            country_code="DE",
            indicator="GGXWDG_NGDP",
            year=2024,
            value=60.5,
            edition="202604",
        )
        assert ImfForecast(**kwargs) == ImfForecast(**kwargs)

    def test_negative_value(self):
        f = ImfForecast(
            country_code="JP",
            indicator="GGXCNL_NGDP",
            year=2024,
            value=-3.2,
            edition="202604",
        )
        assert f.value == -3.2

    def test_zero_value(self):
        f = ImfForecast(
            country_code="CN",
            indicator="NGDP_RPCH",
            year=2024,
            value=0.0,
            edition="202604",
        )
        assert f.value == 0.0


# ── ISO3 → ISO2 Mapping ──────────────────────────────────────────────


class TestIso3ToIso2:
    def test_all_countries_have_mapping(self):
        for iso3 in COUNTRIES:
            assert iso3 in ISO3_TO_ISO2, f"Missing ISO3→ISO2 mapping for {iso3}"

    def test_mapping_produces_iso2(self):
        for iso3, iso2 in ISO3_TO_ISO2.items():
            assert len(iso2) == 2, f"ISO2 for {iso3} should be 2 chars, got {iso2}"
            assert iso2 == iso2.upper(), f"ISO2 for {iso3} should be uppercase"

    def test_key_mappings(self):
        assert ISO3_TO_ISO2["USA"] == "US"
        assert ISO3_TO_ISO2["GBR"] == "GB"
        assert ISO3_TO_ISO2["BRA"] == "BR"
        assert ISO3_TO_ISO2["DEU"] == "DE"
        assert ISO3_TO_ISO2["JPN"] == "JP"
        assert ISO3_TO_ISO2["CHN"] == "CN"

    def test_mapping_count_matches_countries(self):
        assert len(ISO3_TO_ISO2) == len(COUNTRIES)

    def test_no_duplicate_iso2_values(self):
        iso2_values = list(ISO3_TO_ISO2.values())
        assert len(iso2_values) == len(set(iso2_values)), "Duplicate ISO2 values found"


# ── Constants ─────────────────────────────────────────────────────────


class TestImfConstants:
    def test_countries_count(self):
        assert len(COUNTRIES) == 44

    def test_countries_iso3(self):
        for code in COUNTRIES:
            assert len(code) == 3
            assert code == code.upper()

    def test_indicators_count(self):
        assert len(INDICATORS) == 4

    def test_indicator_codes(self):
        codes = [i[0] for i in INDICATORS]
        assert "NGDP_RPCH" in codes
        assert "PCPIPCH" in codes
        assert "GGXCNL_NGDP" in codes
        assert "GGXWDG_NGDP" in codes

    def test_indicator_labels(self):
        labels = [i[1] for i in INDICATORS]
        assert "gdp_growth" in labels
        assert "inflation" in labels
        assert "fiscal_balance" in labels
        assert "govt_debt" in labels


# ── fetch_imf_indicator ──────────────────────────────────────────────


def _make_imf_response(indicator_code: str, data: dict[str, dict[str, float]]) -> dict:
    """Build IMF API response structure."""
    return {"values": {indicator_code: data}}


class TestFetchImfIndicator:
    async def test_parses_json_correctly(self):
        response_data = _make_imf_response("NGDP_RPCH", {
            "USA": {"2024": 2.1, "2025": 1.8},
            "BRA": {"2024": 3.0},
        })

        mock_resp = MagicMock()
        mock_resp.json.return_value = response_data
        mock_resp.raise_for_status = MagicMock()

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        results = await fetch_imf_indicator(
            client, "NGDP_RPCH", countries=["USA", "BRA"],
        )

        assert len(results) == 3  # 2 USA + 1 BRA
        us_results = [r for r in results if r.country_code == "US"]
        assert len(us_results) == 2
        assert any(r.year == 2024 and r.value == 2.1 for r in us_results)
        assert any(r.year == 2025 and r.value == 1.8 for r in us_results)

        br_results = [r for r in results if r.country_code == "BR"]
        assert len(br_results) == 1
        assert br_results[0].value == 3.0

    async def test_iso3_to_iso2_conversion(self):
        response_data = _make_imf_response("PCPIPCH", {
            "DEU": {"2024": 2.0},
        })

        mock_resp = MagicMock()
        mock_resp.json.return_value = response_data
        mock_resp.raise_for_status = MagicMock()

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        results = await fetch_imf_indicator(
            client, "PCPIPCH", countries=["DEU"],
        )

        assert len(results) == 1
        assert results[0].country_code == "DE"  # Converted from DEU

    async def test_skips_non_numeric_values(self):
        response_data = _make_imf_response("NGDP_RPCH", {
            "USA": {"2024": 2.1, "2025": "n/a", "notes": "test"},
        })

        mock_resp = MagicMock()
        mock_resp.json.return_value = response_data
        mock_resp.raise_for_status = MagicMock()

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        results = await fetch_imf_indicator(
            client, "NGDP_RPCH", countries=["USA"],
        )

        assert len(results) == 1
        assert results[0].year == 2024

    async def test_missing_country_in_response(self):
        response_data = _make_imf_response("NGDP_RPCH", {
            "USA": {"2024": 2.1},
            # BRA missing from response
        })

        mock_resp = MagicMock()
        mock_resp.json.return_value = response_data
        mock_resp.raise_for_status = MagicMock()

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        results = await fetch_imf_indicator(
            client, "NGDP_RPCH", countries=["USA", "BRA"],
        )

        assert len(results) == 1
        assert results[0].country_code == "US"

    async def test_empty_values_in_response(self):
        response_data = {"values": {"NGDP_RPCH": {}}}

        mock_resp = MagicMock()
        mock_resp.json.return_value = response_data
        mock_resp.raise_for_status = MagicMock()

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        results = await fetch_imf_indicator(
            client, "NGDP_RPCH", countries=["USA"],
        )
        assert results == []

    async def test_missing_values_key(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"something_else": {}}
        mock_resp.raise_for_status = MagicMock()

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        results = await fetch_imf_indicator(
            client, "NGDP_RPCH", countries=["USA"],
        )
        assert results == []

    async def test_http_status_error_returns_empty(self):
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "Server Error",
                request=httpx.Request("GET", "https://test"),
                response=httpx.Response(500),
            )
        )

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        results = await fetch_imf_indicator(client, "NGDP_RPCH")
        assert results == []

    async def test_connection_error_returns_empty(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        results = await fetch_imf_indicator(client, "PCPIPCH")
        assert results == []

    async def test_invalid_json_returns_empty(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.side_effect = ValueError("Invalid JSON")

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        results = await fetch_imf_indicator(client, "NGDP_RPCH")
        assert results == []

    async def test_edition_format(self):
        response_data = _make_imf_response("NGDP_RPCH", {
            "USA": {"2024": 2.1},
        })

        mock_resp = MagicMock()
        mock_resp.json.return_value = response_data
        mock_resp.raise_for_status = MagicMock()

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        results = await fetch_imf_indicator(
            client, "NGDP_RPCH", countries=["USA"],
        )

        assert len(results) == 1
        # Edition should be YYYYMM format
        assert len(results[0].edition) == 6
        assert results[0].edition.isdigit()

    async def test_negative_values_preserved(self):
        response_data = _make_imf_response("GGXCNL_NGDP", {
            "USA": {"2024": -5.2},
        })

        mock_resp = MagicMock()
        mock_resp.json.return_value = response_data
        mock_resp.raise_for_status = MagicMock()

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        results = await fetch_imf_indicator(
            client, "GGXCNL_NGDP", countries=["USA"],
        )

        assert results[0].value == -5.2


# ── fetch_all_imf_data ───────────────────────────────────────────────


class TestFetchAllImfData:
    @patch("data_providers.imf.service.fetch_imf_indicator")
    async def test_aggregates_all_indicators(self, mock_fetch):
        mock_fetch.side_effect = [
            [ImfForecast("US", "NGDP_RPCH", 2024, 2.1, "202604")],
            [ImfForecast("US", "PCPIPCH", 2024, 3.5, "202604")],
            [ImfForecast("US", "GGXCNL_NGDP", 2024, -5.2, "202604")],
            [ImfForecast("US", "GGXWDG_NGDP", 2024, 120.0, "202604")],
        ]

        results = await fetch_all_imf_data()
        assert len(results) == 4
        assert mock_fetch.call_count == 4

        indicators = {r.indicator for r in results}
        assert indicators == {"NGDP_RPCH", "PCPIPCH", "GGXCNL_NGDP", "GGXWDG_NGDP"}

    @patch("data_providers.imf.service.fetch_imf_indicator")
    async def test_handles_partial_failures(self, mock_fetch):
        mock_fetch.side_effect = [
            [ImfForecast("US", "NGDP_RPCH", 2024, 2.1, "202604")],
            [],  # inflation failed
            [],  # fiscal failed
            [ImfForecast("US", "GGXWDG_NGDP", 2024, 120.0, "202604")],
        ]

        results = await fetch_all_imf_data()
        assert len(results) == 2

    @patch("data_providers.imf.service.fetch_imf_indicator")
    async def test_all_indicators_empty(self, mock_fetch):
        mock_fetch.return_value = []

        results = await fetch_all_imf_data()
        assert results == []
        assert mock_fetch.call_count == 4

    @patch("data_providers.imf.service.fetch_imf_indicator")
    async def test_custom_countries_passed_through(self, mock_fetch):
        mock_fetch.return_value = []

        await fetch_all_imf_data(countries=["USA", "BRA"])

        for call in mock_fetch.call_args_list:
            assert call[1].get("countries") == ["USA", "BRA"] or call[0][2] == ["USA", "BRA"]
