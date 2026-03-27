"""Tests for quant_engine.data_commons_service — Data Commons API client.

Uses mocking of the datacommons_client library since it requires an API key
and makes external HTTP calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from quant_engine.data_commons_service import (
    DataCommonsService,
    DemographicProfile,
    EconomicObservation,
    GeoEntity,
)

# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _mock_client() -> MagicMock:
    """Create a mock DataCommonsClient."""
    mock = MagicMock()
    return mock


# ---------------------------------------------------------------------------
#  fetch_economic_indicators
# ---------------------------------------------------------------------------


class TestFetchEconomicIndicators:
    @pytest.mark.asyncio
    async def test_parses_observations(self) -> None:
        svc = DataCommonsService(api_key="test-key")

        mock_response = MagicMock()
        mock_response.to_dict.return_value = {
            "byVariable": {
                "UnemploymentRate_Person": {
                    "byEntity": {
                        "geoId/06": {
                            "orderedFacets": [{"observations": [{"date": "2025", "value": 4.2}]}],
                        },
                    },
                },
                "Count_Person": {
                    "byEntity": {
                        "geoId/06": {
                            "orderedFacets": [{"observations": [{"date": "2025", "value": 39_500_000}]}],
                        },
                    },
                },
            },
            "facets": {},
        }

        mock_dc = _mock_client()
        mock_dc.observation.fetch.return_value = mock_response

        with patch.object(svc, "_get_client", return_value=mock_dc):
            result = await svc.fetch_economic_indicators(
                entity_dcids=["geoId/06"],
                variables=["UnemploymentRate_Person", "Count_Person"],
            )

        assert len(result) == 2
        assert isinstance(result[0], EconomicObservation)
        assert result[0].entity_dcid == "geoId/06"
        assert result[0].variable == "UnemploymentRate_Person"
        assert result[0].value == 4.2

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self) -> None:
        svc = DataCommonsService(api_key="test-key")

        mock_dc = _mock_client()
        mock_dc.observation.fetch.side_effect = Exception("API error")

        with patch.object(svc, "_get_client", return_value=mock_dc):
            result = await svc.fetch_economic_indicators(
                entity_dcids=["geoId/06"],
                variables=["Count_Person"],
            )

        assert result == []


# ---------------------------------------------------------------------------
#  fetch_demographic_profile
# ---------------------------------------------------------------------------


class TestFetchDemographicProfile:
    @pytest.mark.asyncio
    async def test_aggregates_profile(self) -> None:
        svc = DataCommonsService(api_key="test-key")

        mock_name_obj = MagicMock()
        mock_name_obj.value = "California"
        mock_name_response = {"geoId/06": mock_name_obj}

        mock_obs_response = MagicMock()
        mock_obs_response.to_dict.return_value = {
            "byVariable": {
                "Count_Person": {"byEntity": {"geoId/06": {"orderedFacets": [{"observations": [{"date": "2025", "value": 39_500_000}]}]}}},
                "Median_Age_Person": {"byEntity": {"geoId/06": {"orderedFacets": [{"observations": [{"date": "2025", "value": 37.0}]}]}}},
                "Median_Income_Household": {"byEntity": {"geoId/06": {"orderedFacets": [{"observations": [{"date": "2025", "value": 78_000}]}]}}},
                "UnemploymentRate_Person": {"byEntity": {"geoId/06": {"orderedFacets": [{"observations": [{"date": "2025", "value": 4.2}]}]}}},
            },
            "facets": {},
        }

        mock_dc = _mock_client()
        mock_dc.node.fetch_entity_names.return_value = mock_name_response
        mock_dc.observation.fetch.return_value = mock_obs_response

        with patch.object(svc, "_get_client", return_value=mock_dc):
            result = await svc.fetch_demographic_profile("geoId/06")

        assert isinstance(result, DemographicProfile)
        assert result.geo_dcid == "geoId/06"
        assert result.geo_name == "California"
        assert result.population == 39_500_000
        assert result.median_age == 37.0
        assert result.median_income == 78_000
        assert result.unemployment_rate == 4.2

    @pytest.mark.asyncio
    async def test_returns_nulls_on_error(self) -> None:
        svc = DataCommonsService(api_key="test-key")

        mock_dc = _mock_client()
        mock_dc.node.fetch_entity_names.side_effect = Exception("Network error")

        with patch.object(svc, "_get_client", return_value=mock_dc):
            result = await svc.fetch_demographic_profile("geoId/06")

        assert isinstance(result, DemographicProfile)
        assert result.population is None
        assert result.median_income is None


# ---------------------------------------------------------------------------
#  resolve_entity
# ---------------------------------------------------------------------------


class TestResolveEntity:
    @pytest.mark.asyncio
    async def test_resolves_name(self) -> None:
        svc = DataCommonsService(api_key="test-key")

        mock_resolve_response = MagicMock()
        mock_resolve_response.to_dict.return_value = {
            "entities": [
                {"node": "California", "candidates": [{"dcid": "geoId/06"}]},
            ],
        }

        mock_dc = _mock_client()
        mock_dc.resolve.fetch_dcids_by_name.return_value = mock_resolve_response

        with patch.object(svc, "_get_client", return_value=mock_dc):
            result = await svc.resolve_entity("California", "State")

        assert result == "geoId/06"

    @pytest.mark.asyncio
    async def test_returns_none_on_no_match(self) -> None:
        svc = DataCommonsService(api_key="test-key")

        mock_resolve_response = MagicMock()
        mock_resolve_response.to_dict.return_value = {
            "entities": [{"node": "Atlantis", "candidates": []}],
        }

        mock_dc = _mock_client()
        mock_dc.resolve.fetch_dcids_by_name.return_value = mock_resolve_response

        with patch.object(svc, "_get_client", return_value=mock_dc):
            result = await svc.resolve_entity("Atlantis", "State")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self) -> None:
        svc = DataCommonsService(api_key="test-key")

        mock_dc = _mock_client()
        mock_dc.resolve.fetch_dcids_by_name.side_effect = Exception("API error")

        with patch.object(svc, "_get_client", return_value=mock_dc):
            result = await svc.resolve_entity("California")

        assert result is None


# ---------------------------------------------------------------------------
#  fetch_geographic_hierarchy
# ---------------------------------------------------------------------------


class TestFetchGeographicHierarchy:
    @pytest.mark.asyncio
    async def test_returns_children(self) -> None:
        svc = DataCommonsService(api_key="test-key")

        mock_dc = _mock_client()
        mock_dc.node.fetch_place_children.return_value = {
            "geoId/06": [
                {"dcid": "geoId/06001", "name": "Alameda County", "type": "County"},
                {"dcid": "geoId/06003", "name": "Alpine County", "type": "County"},
            ],
        }

        with patch.object(svc, "_get_client", return_value=mock_dc):
            result = await svc.fetch_geographic_hierarchy("geoId/06", "County")

        assert len(result) == 2
        assert isinstance(result[0], GeoEntity)
        assert result[0].dcid == "geoId/06001"
        assert result[0].name == "Alameda County"

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self) -> None:
        svc = DataCommonsService(api_key="test-key")

        mock_dc = _mock_client()
        mock_dc.node.fetch_place_children.side_effect = Exception("Fail")

        with patch.object(svc, "_get_client", return_value=mock_dc):
            result = await svc.fetch_geographic_hierarchy("geoId/06")

        assert result == []
