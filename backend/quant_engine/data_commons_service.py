"""Data Commons API client (Google).

Async wrapper around the sync ``datacommons_client`` library.
Sync calls are dispatched via ``asyncio.to_thread()`` (same pattern as EDGAR's edgartools).

Base URL: https://api.datacommons.org/v2/
Auth: API key (free, from DC_API_KEY env var).

Lifecycle: Instantiate ONCE in FastAPI lifespan() or at worker startup.
Store as app.state.data_commons_service and inject via dependency.

Config is injected as parameter — no module-level settings reads.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger()

# Suppress noisy loggers
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
#  Data types (frozen dataclasses)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EconomicObservation:
    """Single economic indicator observation for an entity."""

    entity_dcid: str
    variable: str
    date: str
    value: float


@dataclass(frozen=True)
class DemographicProfile:
    """Aggregate demographic snapshot for a geography."""

    geo_dcid: str
    geo_name: str
    population: float | None
    median_age: float | None
    median_income: float | None
    unemployment_rate: float | None


@dataclass(frozen=True)
class GeoEntity:
    """A geographic entity resolved from Data Commons."""

    dcid: str
    name: str
    entity_type: str


# ---------------------------------------------------------------------------
#  DataCommonsService
# ---------------------------------------------------------------------------

# Standard economic variables used across IC memos and DD reports.
_ECONOMIC_VARIABLES = [
    "Count_Person",
    "Median_Age_Person",
    "Median_Income_Household",
    "UnemploymentRate_Person",
]

# Demographic variables for profile aggregation.
_DEMOGRAPHIC_VARIABLES = [
    "Count_Person",
    "Median_Age_Person",
    "Median_Income_Household",
    "UnemploymentRate_Person",
]


class DataCommonsService:
    """Data Commons API client using the official Python library.

    The ``datacommons_client`` library is sync; all calls are wrapped with
    ``asyncio.to_thread()`` to avoid blocking the event loop.

    Args:
        api_key: Data Commons API key (from settings.dc_api_key).

    """

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client: Any = None  # Lazy init to avoid import at module level

    def _get_client(self) -> Any:
        """Lazy-initialize the Data Commons client."""
        if self._client is None:
            try:
                from datacommons_client import DataCommonsClient

                self._client = DataCommonsClient(api_key=self._api_key)
            except ImportError:
                logger.error(
                    "datacommons_client not installed. "
                    "Install with: pip install 'datacommons-client[Pandas]'",
                )
                raise
        return self._client

    # ── Sync helpers (run in thread) ──────────────────────────────

    def _fetch_observations_sync(
        self,
        entity_dcids: list[str],
        variables: list[str],
        date: str = "latest",
    ) -> list[dict[str, Any]]:
        """Sync fetch of observations via datacommons_client."""
        try:
            client = self._get_client()
            response = client.observation.fetch(
                variable_dcids=variables,
                entity_dcids=entity_dcids,
                date=date,
            )
            # Parse response.to_dict() → {byVariable: {var: {byEntity: {entity: {orderedFacets: [...]}}}} }
            records: list[dict[str, Any]] = []
            data = response.to_dict()
            by_variable = data.get("byVariable", {})
            for variable, var_data in by_variable.items():
                by_entity = var_data.get("byEntity", {})
                for entity, entity_data in by_entity.items():
                    for facet in entity_data.get("orderedFacets", []):
                        for obs in facet.get("observations", []):
                            records.append({
                                "entity": entity,
                                "variable": variable,
                                "date": obs.get("date", ""),
                                "value": obs.get("value"),
                            })
            return records
        except Exception as e:
            logger.warning("data_commons observation fetch failed", error=str(e))
            return []

    def _resolve_entity_sync(self, name: str, entity_type: str = "State") -> str | None:
        """Sync resolve a place name to a DCID."""
        try:
            client = self._get_client()
            response = client.resolve.fetch_dcids_by_name(
                names=[name],
                entity_type=entity_type,
            )
            # ResolveResponse.to_dict() → {entities: [{node: name, candidates: [{dcid: ...}]}]}
            data = response.to_dict()
            for entity in data.get("entities", []):
                if entity.get("node") == name:
                    candidates = entity.get("candidates", [])
                    if candidates and isinstance(candidates[0], dict):
                        return candidates[0].get("dcid")
            return None
        except Exception as e:
            logger.warning("data_commons resolve failed", name=name, error=str(e))
            return None

    def _fetch_geo_hierarchy_sync(
        self, parent_dcid: str, child_type: str = "County",
    ) -> list[dict[str, str]]:
        """Sync fetch child entities for a geography."""
        try:
            client = self._get_client()
            response = client.node.fetch_place_children(
                place_dcids=[parent_dcid],
                children_type=child_type,
            )
            results: list[dict[str, str]] = []
            if isinstance(response, dict):
                children = response.get(parent_dcid, [])
                if isinstance(children, list):
                    for child in children:
                        if isinstance(child, dict):
                            results.append({
                                "dcid": child.get("dcid", ""),
                                "name": child.get("name", ""),
                                "type": child.get("type", child_type),
                            })
                        elif isinstance(child, str):
                            results.append({"dcid": child, "name": "", "type": child_type})
            return results
        except Exception as e:
            logger.warning(
                "data_commons geo hierarchy failed",
                parent=parent_dcid,
                error=str(e),
            )
            return []

    def _fetch_demographic_profile_sync(self, geo_dcid: str) -> dict[str, Any]:
        """Sync fetch demographic profile for a geography."""
        try:
            client = self._get_client()

            # Fetch entity name
            name_response = client.node.fetch_entity_names(entity_dcids=[geo_dcid])
            geo_name = ""
            if isinstance(name_response, dict):
                name_obj = name_response.get(geo_dcid)
                if name_obj is not None and hasattr(name_obj, "value"):
                    geo_name = name_obj.value
                elif isinstance(name_obj, str):
                    geo_name = name_obj

            # Fetch demographic observations — reuse _fetch_observations_sync
            records = self._fetch_observations_sync([geo_dcid], _DEMOGRAPHIC_VARIABLES)

            values: dict[str, float | None] = {}
            for rec in records:
                var = rec.get("variable", "")
                val = rec.get("value")
                if val is not None:
                    try:
                        values[var] = float(val)
                    except (ValueError, TypeError):
                        pass

            return {
                "geo_dcid": geo_dcid,
                "geo_name": geo_name,
                "population": values.get("Count_Person"),
                "median_age": values.get("Median_Age_Person"),
                "median_income": values.get("Median_Income_Household"),
                "unemployment_rate": values.get("UnemploymentRate_Person"),
            }
        except Exception as e:
            logger.warning("data_commons demographic profile failed", geo=geo_dcid, error=str(e))
            return {
                "geo_dcid": geo_dcid,
                "geo_name": "",
                "population": None,
                "median_age": None,
                "median_income": None,
                "unemployment_rate": None,
            }

    # ── Public async methods ──────────────────────────────────────

    async def fetch_economic_indicators(
        self,
        entity_dcids: list[str],
        variables: list[str],
        date: str = "latest",
    ) -> list[EconomicObservation]:
        """Fetch economic indicators (GDP, unemployment, income) for given entities.

        Variables: UnemploymentRate_Person, Count_Person,
                   Median_Income_Household, etc.
        """
        records = await asyncio.to_thread(
            self._fetch_observations_sync, entity_dcids, variables, date,
        )
        results: list[EconomicObservation] = []
        for rec in records:
            try:
                results.append(
                    EconomicObservation(
                        entity_dcid=rec.get("entity", ""),
                        variable=rec.get("variable", ""),
                        date=str(rec.get("date", "")),
                        value=float(rec.get("value", 0)),
                    ),
                )
            except (ValueError, TypeError):
                continue
        return results

    async def fetch_demographic_profile(self, geo_dcid: str) -> DemographicProfile:
        """Aggregate demographic snapshot for a geography.

        Population, age distribution, income, unemployment.
        Used for regional market context in IC memos and DD reports.
        """
        data = await asyncio.to_thread(self._fetch_demographic_profile_sync, geo_dcid)
        return DemographicProfile(
            geo_dcid=data["geo_dcid"],
            geo_name=data.get("geo_name", ""),
            population=data.get("population"),
            median_age=data.get("median_age"),
            median_income=data.get("median_income"),
            unemployment_rate=data.get("unemployment_rate"),
        )

    async def resolve_entity(self, name: str, entity_type: str = "State") -> str | None:
        """Resolve a place name to a DCID for subsequent queries."""
        return await asyncio.to_thread(self._resolve_entity_sync, name, entity_type)

    async def fetch_geographic_hierarchy(
        self, parent_dcid: str, child_type: str = "County",
    ) -> list[GeoEntity]:
        """List child entities for a geography (e.g., all counties in a state)."""
        raw = await asyncio.to_thread(
            self._fetch_geo_hierarchy_sync, parent_dcid, child_type,
        )
        return [
            GeoEntity(
                dcid=item.get("dcid", ""),
                name=item.get("name", ""),
                entity_type=item.get("type", child_type),
            )
            for item in raw
        ]
