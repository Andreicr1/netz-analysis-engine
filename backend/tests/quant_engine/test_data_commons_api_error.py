"""F03 regression: Data Commons API failure distinguishable from valid empty (S05-F03).

Validates that API failures raise DataCommonsAPIError instead of
silently returning empty lists/dicts, while valid empty responses
still return [] correctly.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from quant_engine.data_commons_service import (
    DataCommonsAPIError,
    DataCommonsService,
)


def _mock_client() -> MagicMock:
    return MagicMock()


# ── F03 regression: API failure distinguishable from valid empty ──────────


@pytest.mark.asyncio
async def test_observation_fetch_api_failure_raises():
    """Network failure -> DataCommonsAPIError, NOT silent []."""
    svc = DataCommonsService(api_key="test")
    mock_dc = _mock_client()
    mock_dc.observation.fetch.side_effect = ConnectionError("simulated network failure")

    with patch.object(svc, "_get_client", return_value=mock_dc):
        with pytest.raises(DataCommonsAPIError, match="observation fetch failed"):
            await svc.fetch_economic_indicators(
                entity_dcids=["geoId/06"],
                variables=["UnemploymentRate_Person"],
            )


@pytest.mark.asyncio
async def test_observation_fetch_valid_empty_returns_empty_list():
    """Valid 'no data' response -> [], NOT exception."""
    svc = DataCommonsService(api_key="test")
    mock_dc = _mock_client()
    mock_response = MagicMock()
    mock_response.to_dict.return_value = {"byVariable": {}}
    mock_dc.observation.fetch.return_value = mock_response

    with patch.object(svc, "_get_client", return_value=mock_dc):
        result = await svc.fetch_economic_indicators(
            entity_dcids=["geoId/99999"],
            variables=["UnemploymentRate_Person"],
        )
    assert result == []  # valid empty, not error


@pytest.mark.asyncio
async def test_geo_hierarchy_api_failure_raises():
    """Geo hierarchy API failure -> DataCommonsAPIError."""
    svc = DataCommonsService(api_key="test")
    mock_dc = _mock_client()
    mock_dc.node.fetch_place_children.side_effect = TimeoutError("simulated timeout")

    with patch.object(svc, "_get_client", return_value=mock_dc):
        with pytest.raises(DataCommonsAPIError, match="geo hierarchy fetch failed"):
            await svc.fetch_geographic_hierarchy(
                parent_dcid="country/USA",
                child_type="State",
            )


@pytest.mark.asyncio
async def test_demographic_profile_api_failure_raises():
    """Demographic profile failure -> DataCommonsAPIError."""
    svc = DataCommonsService(api_key="test")
    mock_dc = _mock_client()
    mock_dc.node.fetch_entity_names.side_effect = ConnectionError("down")

    with patch.object(svc, "_get_client", return_value=mock_dc):
        with pytest.raises(DataCommonsAPIError, match="demographic profile fetch failed"):
            await svc.fetch_demographic_profile(geo_dcid="geoId/06")
