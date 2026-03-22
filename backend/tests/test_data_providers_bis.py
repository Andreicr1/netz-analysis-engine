"""Tests for BIS data provider — credit-to-GDP gap, DSR, property prices.

Covers:
- BisIndicator frozen dataclass creation and immutability
- _parse_quarter() edge cases (valid, malformed, out-of-range)
- fetch_bis_dataset() CSV parsing with mocked httpx responses
- fetch_all_bis_data() aggregation across 3 datasets
- HTTP error handling (status errors, connection errors, empty responses)
- Field validation and type coercion
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from data_providers.bis.service import (
    COUNTRIES,
    DATASETS,
    BisIndicator,
    _parse_quarter,
    fetch_all_bis_data,
    fetch_bis_dataset,
)

# ── BisIndicator Dataclass ────────────────────────────────────────────


class TestBisIndicator:
    def test_creation(self):
        bi = BisIndicator(
            country_code="US",
            indicator="credit_to_gdp_gap",
            period=datetime(2024, 1, 1, tzinfo=timezone.utc),
            value=5.2,
            dataset="WS_CREDIT_GAP",
        )
        assert bi.country_code == "US"
        assert bi.indicator == "credit_to_gdp_gap"
        assert bi.value == 5.2
        assert bi.dataset == "WS_CREDIT_GAP"
        assert bi.period == datetime(2024, 1, 1, tzinfo=timezone.utc)

    def test_frozen_immutability(self):
        bi = BisIndicator(
            country_code="BR",
            indicator="debt_service_ratio",
            period=datetime(2023, 7, 1, tzinfo=timezone.utc),
            value=12.3,
            dataset="WS_DSR",
        )
        with pytest.raises(AttributeError):
            bi.value = 99.9  # type: ignore[misc]

    def test_equality(self):
        kwargs = dict(
            country_code="DE",
            indicator="property_prices",
            period=datetime(2024, 4, 1, tzinfo=timezone.utc),
            value=3.1,
            dataset="WS_SPP",
        )
        assert BisIndicator(**kwargs) == BisIndicator(**kwargs)

    def test_negative_value(self):
        bi = BisIndicator(
            country_code="JP",
            indicator="credit_to_gdp_gap",
            period=datetime(2024, 1, 1, tzinfo=timezone.utc),
            value=-2.5,
            dataset="WS_CREDIT_GAP",
        )
        assert bi.value == -2.5

    def test_zero_value(self):
        bi = BisIndicator(
            country_code="CN",
            indicator="debt_service_ratio",
            period=datetime(2024, 1, 1, tzinfo=timezone.utc),
            value=0.0,
            dataset="WS_DSR",
        )
        assert bi.value == 0.0


# ── _parse_quarter ────────────────────────────────────────────────────


class TestParseQuarter:
    def test_q1(self):
        result = _parse_quarter("2024-Q1")
        assert result == datetime(2024, 1, 1, tzinfo=timezone.utc)

    def test_q2(self):
        result = _parse_quarter("2024-Q2")
        assert result == datetime(2024, 4, 1, tzinfo=timezone.utc)

    def test_q3(self):
        result = _parse_quarter("2023-Q3")
        assert result == datetime(2023, 7, 1, tzinfo=timezone.utc)

    def test_q4(self):
        result = _parse_quarter("2023-Q4")
        assert result == datetime(2023, 10, 1, tzinfo=timezone.utc)

    def test_empty_string(self):
        assert _parse_quarter("") is None

    def test_no_quarter_separator(self):
        assert _parse_quarter("2024-01") is None

    def test_invalid_quarter_number(self):
        assert _parse_quarter("2024-Q0") is None

    def test_non_numeric_year(self):
        assert _parse_quarter("ABCD-Q1") is None

    def test_non_numeric_quarter(self):
        assert _parse_quarter("2024-QX") is None

    def test_just_year(self):
        assert _parse_quarter("2024") is None

    def test_none_like(self):
        assert _parse_quarter("None") is None

    def test_extra_dash(self):
        assert _parse_quarter("2024-Q1-extra") is None


# ── Constants ─────────────────────────────────────────────────────────


class TestBisConstants:
    def test_countries_count(self):
        assert len(COUNTRIES) == 44

    def test_countries_iso2(self):
        for code in COUNTRIES:
            assert len(code) == 2
            assert code == code.upper()

    def test_key_countries_present(self):
        for key in ["US", "GB", "DE", "FR", "JP", "CN", "BR"]:
            assert key in COUNTRIES

    def test_datasets_count(self):
        assert len(DATASETS) == 3

    def test_dataset_keys(self):
        keys = [d[0] for d in DATASETS]
        assert "WS_CREDIT_GAP" in keys
        assert "WS_DSR" in keys
        assert "WS_SPP" in keys

    def test_dataset_indicators(self):
        indicators = [d[2] for d in DATASETS]
        assert "credit_to_gdp_gap" in indicators
        assert "debt_service_ratio" in indicators
        assert "property_prices" in indicators


# ── fetch_bis_dataset ─────────────────────────────────────────────────


def _make_csv_response(rows: list[dict[str, str]]) -> str:
    """Build CSV text from list of dicts."""
    if not rows:
        return "REF_AREA,TIME_PERIOD,OBS_VALUE\n"
    headers = list(rows[0].keys())
    lines = [",".join(headers)]
    for row in rows:
        lines.append(",".join(row.get(h, "") for h in headers))
    return "\n".join(lines)


class TestFetchBisDataset:
    async def test_parses_csv_correctly(self):
        csv_text = _make_csv_response([
            {"REF_AREA": "US", "TIME_PERIOD": "2024-Q1", "OBS_VALUE": "5.2"},
            {"REF_AREA": "BR", "TIME_PERIOD": "2024-Q2", "OBS_VALUE": "-1.3"},
            {"REF_AREA": "DE", "TIME_PERIOD": "2023-Q4", "OBS_VALUE": "0.0"},
        ])

        mock_resp = AsyncMock()
        mock_resp.text = csv_text
        mock_resp.raise_for_status = lambda: None

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        results = await fetch_bis_dataset(client, "WS_CREDIT_GAP", "credit_to_gdp_gap")

        assert len(results) == 3
        assert results[0].country_code == "US"
        assert results[0].indicator == "credit_to_gdp_gap"
        assert results[0].value == 5.2
        assert results[0].dataset == "WS_CREDIT_GAP"
        assert results[0].period == datetime(2024, 1, 1, tzinfo=timezone.utc)

        assert results[1].country_code == "BR"
        assert results[1].value == -1.3

        assert results[2].value == 0.0

    async def test_skips_rows_missing_ref_area(self):
        csv_text = _make_csv_response([
            {"REF_AREA": "", "TIME_PERIOD": "2024-Q1", "OBS_VALUE": "5.2"},
            {"REF_AREA": "US", "TIME_PERIOD": "2024-Q1", "OBS_VALUE": "3.1"},
        ])

        mock_resp = AsyncMock()
        mock_resp.text = csv_text
        mock_resp.raise_for_status = lambda: None

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        results = await fetch_bis_dataset(client, "WS_DSR", "debt_service_ratio")
        assert len(results) == 1
        assert results[0].country_code == "US"

    async def test_skips_rows_missing_obs_value(self):
        csv_text = _make_csv_response([
            {"REF_AREA": "US", "TIME_PERIOD": "2024-Q1", "OBS_VALUE": ""},
            {"REF_AREA": "BR", "TIME_PERIOD": "2024-Q1", "OBS_VALUE": "7.5"},
        ])

        mock_resp = AsyncMock()
        mock_resp.text = csv_text
        mock_resp.raise_for_status = lambda: None

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        results = await fetch_bis_dataset(client, "WS_DSR", "debt_service_ratio")
        assert len(results) == 1

    async def test_skips_rows_invalid_period(self):
        csv_text = _make_csv_response([
            {"REF_AREA": "US", "TIME_PERIOD": "not-a-quarter", "OBS_VALUE": "5.2"},
            {"REF_AREA": "US", "TIME_PERIOD": "2024-Q1", "OBS_VALUE": "3.1"},
        ])

        mock_resp = AsyncMock()
        mock_resp.text = csv_text
        mock_resp.raise_for_status = lambda: None

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        results = await fetch_bis_dataset(client, "WS_SPP", "property_prices")
        assert len(results) == 1

    async def test_skips_rows_non_numeric_value(self):
        csv_text = _make_csv_response([
            {"REF_AREA": "US", "TIME_PERIOD": "2024-Q1", "OBS_VALUE": "abc"},
            {"REF_AREA": "BR", "TIME_PERIOD": "2024-Q1", "OBS_VALUE": "4.5"},
        ])

        mock_resp = AsyncMock()
        mock_resp.text = csv_text
        mock_resp.raise_for_status = lambda: None

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        results = await fetch_bis_dataset(client, "WS_CREDIT_GAP", "credit_to_gdp_gap")
        assert len(results) == 1

    async def test_empty_csv(self):
        csv_text = "REF_AREA,TIME_PERIOD,OBS_VALUE\n"

        mock_resp = AsyncMock()
        mock_resp.text = csv_text
        mock_resp.raise_for_status = lambda: None

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        results = await fetch_bis_dataset(client, "WS_DSR", "debt_service_ratio")
        assert results == []

    async def test_http_status_error_returns_empty(self):
        mock_resp = AsyncMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "Server Error",
                request=httpx.Request("GET", "https://test"),
                response=httpx.Response(500),
            )
        )

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        results = await fetch_bis_dataset(client, "WS_CREDIT_GAP", "credit_to_gdp_gap")
        assert results == []

    async def test_connection_error_returns_empty(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        results = await fetch_bis_dataset(client, "WS_DSR", "debt_service_ratio")
        assert results == []

    async def test_custom_countries_filter(self):
        csv_text = _make_csv_response([
            {"REF_AREA": "US", "TIME_PERIOD": "2024-Q1", "OBS_VALUE": "5.2"},
        ])

        mock_resp = AsyncMock()
        mock_resp.text = csv_text
        mock_resp.raise_for_status = lambda: None

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        results = await fetch_bis_dataset(
            client, "WS_CREDIT_GAP", "credit_to_gdp_gap", countries=["US", "BR"],
        )
        assert len(results) == 1

        # Verify ref_area in URL contains only specified countries
        call_args = client.get.call_args
        assert "US+BR" in call_args[0][0]

    async def test_large_dataset(self):
        """Verify parsing handles many rows without issues."""
        rows = [
            {"REF_AREA": c, "TIME_PERIOD": f"2024-Q{q}", "OBS_VALUE": str(i + q * 0.1)}
            for i, c in enumerate(COUNTRIES[:10])
            for q in range(1, 5)
        ]
        csv_text = _make_csv_response(rows)

        mock_resp = AsyncMock()
        mock_resp.text = csv_text
        mock_resp.raise_for_status = lambda: None

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        results = await fetch_bis_dataset(client, "WS_SPP", "property_prices")
        assert len(results) == 40  # 10 countries × 4 quarters


# ── fetch_all_bis_data ────────────────────────────────────────────────


class TestFetchAllBisData:
    @patch("data_providers.bis.service.fetch_bis_dataset")
    async def test_aggregates_all_datasets(self, mock_fetch):
        mock_fetch.side_effect = [
            [BisIndicator("US", "credit_to_gdp_gap", datetime(2024, 1, 1, tzinfo=timezone.utc), 5.0, "WS_CREDIT_GAP")],
            [BisIndicator("US", "debt_service_ratio", datetime(2024, 1, 1, tzinfo=timezone.utc), 12.0, "WS_DSR")],
            [BisIndicator("US", "property_prices", datetime(2024, 1, 1, tzinfo=timezone.utc), 3.0, "WS_SPP")],
        ]

        results = await fetch_all_bis_data()
        assert len(results) == 3
        assert mock_fetch.call_count == 3

        indicators = {r.indicator for r in results}
        assert indicators == {"credit_to_gdp_gap", "debt_service_ratio", "property_prices"}

    @patch("data_providers.bis.service.fetch_bis_dataset")
    async def test_handles_partial_failures(self, mock_fetch):
        mock_fetch.side_effect = [
            [BisIndicator("US", "credit_to_gdp_gap", datetime(2024, 1, 1, tzinfo=timezone.utc), 5.0, "WS_CREDIT_GAP")],
            [],  # DSR failed
            [BisIndicator("US", "property_prices", datetime(2024, 1, 1, tzinfo=timezone.utc), 3.0, "WS_SPP")],
        ]

        results = await fetch_all_bis_data()
        assert len(results) == 2

    @patch("data_providers.bis.service.fetch_bis_dataset")
    async def test_all_datasets_empty(self, mock_fetch):
        mock_fetch.return_value = []

        results = await fetch_all_bis_data()
        assert results == []
        assert mock_fetch.call_count == 3

    @patch("data_providers.bis.service.fetch_bis_dataset")
    async def test_custom_countries_passed_through(self, mock_fetch):
        mock_fetch.return_value = []

        await fetch_all_bis_data(countries=["US", "BR"])

        for call in mock_fetch.call_args_list:
            assert call[1].get("countries") == ["US", "BR"] or call[0][3] == ["US", "BR"]
