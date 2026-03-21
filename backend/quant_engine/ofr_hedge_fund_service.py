"""OFR Hedge Fund Monitor API client.

Async service — called directly from async route handlers or workers.

Base URL: https://data.financialresearch.gov/hf/v1
Auth: None required (fully open).
Source: SEC Form PF, CFTC TFF, FRB SCOOS, FICC Sponsored Repo.

Lifecycle: Instantiate ONCE in FastAPI lifespan() or at worker startup.
Store as app.state.ofr_hedge_fund_service and inject via dependency.

Config is injected as parameter — no module-level settings reads.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quant_engine.fiscal_data_service import AsyncTokenBucketRateLimiter

# Suppress httpx DEBUG logs
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
#  Data types (frozen dataclasses)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LeverageSnapshot:
    """Hedge fund industry leverage ratio at a point in time."""

    date: str
    gav_weighted_mean: float | None
    p5: float | None
    p50: float | None
    p95: float | None


@dataclass(frozen=True)
class IndustrySizeSnapshot:
    """Hedge fund industry total AUM at a point in time."""

    date: str
    gav_sum: float | None
    nav_sum: float | None
    fund_count: float | None


@dataclass(frozen=True)
class StrategySnapshot:
    """AUM by strategy at a point in time."""

    date: str
    strategy: str
    gav_sum: float | None


@dataclass(frozen=True)
class CounterpartySnapshot:
    """Prime broker concentration metric at a point in time."""

    date: str
    mnemonic: str
    value: float


@dataclass(frozen=True)
class RepoVolumeSnapshot:
    """FICC sponsored repo volume at a point in time."""

    date: str
    volume: float


@dataclass(frozen=True)
class RiskScenarioSnapshot:
    """Stress test scenario result at a point in time."""

    date: str
    scenario: str
    value: float


@dataclass(frozen=True)
class SeriesMetadata:
    """Metadata for an OFR series mnemonic."""

    mnemonic: str
    description: str
    dataset: str
    frequency: str


# ---------------------------------------------------------------------------
#  Value parsing
# ---------------------------------------------------------------------------


def _parse_value(raw: Any) -> float | None:
    """Parse a timeseries value. OFR returns [date, value] with value as float or null."""
    if raw is None:
        return None
    try:
        val = float(raw)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(val):
        return None
    return val


def _classify_error(status_code: int) -> str:
    """Classify HTTP error into action: 'retry', 'skip', 'fail'."""
    if status_code == 429:
        return "retry"
    if status_code == 503:
        return "retry"
    if status_code == 400:
        return "skip"
    if status_code in (401, 403):
        return "fail"
    if status_code >= 500:
        return "retry"
    return "skip"


# ---------------------------------------------------------------------------
#  OFRHedgeFundService
# ---------------------------------------------------------------------------

# Strategy names used in FPF mnemonic patterns (must match OFR mnemonics exactly).
_STRATEGIES = ("EQUITY", "CREDIT", "MACRO", "MULTI", "RV", "EVENT", "FOF", "FUTURES", "OTHER")


class OFRHedgeFundService:
    """OFR Hedge Fund Monitor API client with rate limiting and error handling.

    Args:
        http_client: Injected httpx.AsyncClient (allows test mocking).
        rate_limiter: Shared async rate limiter. If None, creates default (5 req/s).
        base_url: OFR HFM API base URL.
    """

    BASE_URL = "https://data.financialresearch.gov/hf/v1"

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        rate_limiter: AsyncTokenBucketRateLimiter | None = None,
        base_url: str | None = None,
    ):
        self._client = http_client
        self._rate_limiter = rate_limiter or AsyncTokenBucketRateLimiter()
        self._base_url = base_url or self.BASE_URL

    # ── Low-level fetch ───────────────────────────────────────────

    async def fetch_timeseries(
        self,
        mnemonic: str,
        start_date: str,
        periodicity: str = "Q",
        *,
        max_retries: int = 3,
    ) -> list[tuple[str, float]]:
        """Generic single-series fetch. Returns list of (date, value) tuples.

        Endpoint: /series/timeseries?mnemonic={mnemonic}&start_date={start_date}
        """
        await self._rate_limiter.acquire()

        params: dict[str, Any] = {
            "mnemonic": mnemonic,
            "start_date": start_date,
            "periodicity": periodicity,
            "remove_nulls": "true",
            "time_format": "date",
        }
        url = f"{self._base_url}/series/timeseries"

        for attempt in range(max_retries):
            try:
                response = await self._client.get(url, params=params)
                response.raise_for_status()
                body = response.json()

                results: list[tuple[str, float]] = []
                for pair in body if isinstance(body, list) else []:
                    if isinstance(pair, list) and len(pair) >= 2:
                        val = _parse_value(pair[1])
                        if val is not None:
                            results.append((str(pair[0]), val))
                return results

            except httpx.HTTPStatusError as e:
                action = _classify_error(e.response.status_code)
                if action == "fail":
                    logger.error("ofr auth failure", mnemonic=mnemonic, status=e.response.status_code)
                    return []
                if action == "skip":
                    logger.warning(
                        "ofr series error, skipping",
                        mnemonic=mnemonic,
                        status=e.response.status_code,
                    )
                    return []
                wait = min(2**attempt * 2, 30)
                logger.warning("ofr retrying", mnemonic=mnemonic, attempt=attempt + 1, wait=wait)
                await asyncio.sleep(wait)

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                wait = min(2**attempt * 2, 30)
                logger.warning(
                    "ofr connection error, retrying",
                    mnemonic=mnemonic,
                    error=str(e),
                    wait=wait,
                )
                await asyncio.sleep(wait)

        logger.error("ofr exhausted retries", mnemonic=mnemonic, max_retries=max_retries)
        return []

    async def _fetch_multi(
        self,
        mnemonics: list[str],
        start_date: str,
    ) -> dict[str, list[tuple[str, float]]]:
        """Fetch multiple series. Returns dict mapping mnemonic to timeseries."""
        results: dict[str, list[tuple[str, float]]] = {}
        for mne in mnemonics:
            results[mne] = await self.fetch_timeseries(mne, start_date)
        return results

    # ── High-level fetch methods ──────────────────────────────────

    async def fetch_industry_leverage(self, start_date: str) -> list[LeverageSnapshot]:
        """Hedge fund industry leverage ratios over time.

        OFR provides leverage by size cohort (top 10, 11-50, 51+),
        not as a single all-fund aggregate. We fetch all three cohorts.
        """
        mnemonics = [
            "FPF-ALLQHF_GAVN10_LEVERAGERATIO_AVERAGE",
            "FPF-ALLQHF_GAVN11TO50_LEVERAGERATIO_AVERAGE",
            "FPF-ALLQHF_GAVN51_LEVERAGERATIO_AVERAGE",
        ]
        data = await self._fetch_multi(mnemonics, start_date)

        # Index by date for merging
        labels = {
            "FPF-ALLQHF_GAVN10_LEVERAGERATIO_AVERAGE": "top10",
            "FPF-ALLQHF_GAVN11TO50_LEVERAGERATIO_AVERAGE": "mid",
            "FPF-ALLQHF_GAVN51_LEVERAGERATIO_AVERAGE": "rest",
        }
        by_date: dict[str, dict[str, float | None]] = {}
        for mne, series in data.items():
            key = labels.get(mne, mne)
            for date_str, val in series:
                by_date.setdefault(date_str, {})[key] = val

        return [
            LeverageSnapshot(
                date=d,
                gav_weighted_mean=vals.get("top10"),
                p5=vals.get("rest"),
                p50=vals.get("mid"),
                p95=vals.get("top10"),
            )
            for d, vals in sorted(by_date.items(), reverse=True)
        ]

    async def fetch_industry_size(self, start_date: str) -> list[IndustrySizeSnapshot]:
        """Hedge fund industry total AUM (GAV, NAV, fund count)."""
        mnemonics = [
            "FPF-ALLQHF_GAV_SUM",
            "FPF-ALLQHF_NAV_SUM",
            "FPF-ALLQHF_COUNT",
        ]
        data = await self._fetch_multi(mnemonics, start_date)

        by_date: dict[str, dict[str, float | None]] = {}
        labels = {"FPF-ALLQHF_GAV_SUM": "gav", "FPF-ALLQHF_NAV_SUM": "nav", "FPF-ALLQHF_COUNT": "count"}
        for mne, series in data.items():
            key = labels.get(mne, mne)
            for date_str, val in series:
                by_date.setdefault(date_str, {})[key] = val

        return [
            IndustrySizeSnapshot(
                date=d,
                gav_sum=vals.get("gav"),
                nav_sum=vals.get("nav"),
                fund_count=vals.get("count"),
            )
            for d, vals in sorted(by_date.items(), reverse=True)
        ]

    async def fetch_strategy_breakdown(self, start_date: str) -> list[StrategySnapshot]:
        """AUM by strategy (credit, equity, macro, multi, relative value)."""
        results: list[StrategySnapshot] = []
        for strategy in _STRATEGIES:
            mnemonic = f"FPF-STRATEGY_{strategy}_GAV_SUM"
            series = await self.fetch_timeseries(mnemonic, start_date)
            for date_str, val in series:
                results.append(
                    StrategySnapshot(date=date_str, strategy=strategy.lower(), gav_sum=val)
                )
        return sorted(results, key=lambda s: s.date, reverse=True)

    async def fetch_counterparty_concentration(
        self, start_date: str
    ) -> list[CounterpartySnapshot]:
        """Counterparty risk metrics from SCOOS (FRB dealer financing survey)."""
        mnemonics = [
            "SCOOS-NET_LENDERCOMPET",
            "SCOOS-NET_LENDERWILLINGNESS",
        ]
        results: list[CounterpartySnapshot] = []
        for mne in mnemonics:
            series = await self.fetch_timeseries(mne, start_date, periodicity="Q")
            for date_str, val in series:
                results.append(CounterpartySnapshot(date=date_str, mnemonic=mne, value=val))
        return sorted(results, key=lambda s: s.date, reverse=True)

    async def fetch_repo_volumes(self, start_date: str) -> list[RepoVolumeSnapshot]:
        """FICC sponsored repo service volumes."""
        series = await self.fetch_timeseries(
            "FICC-SPONSORED_REPO_VOL", start_date, periodicity="M"
        )
        return [RepoVolumeSnapshot(date=d, volume=v) for d, v in series]

    async def fetch_risk_scenarios(self, start_date: str) -> list[RiskScenarioSnapshot]:
        """Stress test results: CDS spread scenarios (P5, P50 percentiles)."""
        scenario_mnemonics = [
            ("cds_down_250bps_p5", "FPF-ALLQHF_CDSDOWN250BPS_P5"),
            ("cds_down_250bps_p50", "FPF-ALLQHF_CDSDOWN250BPS_P50"),
            ("cds_up_250bps_p5", "FPF-ALLQHF_CDSUP250BPS_P5"),
            ("cds_up_250bps_p50", "FPF-ALLQHF_CDSUP250BPS_P50"),
        ]
        results: list[RiskScenarioSnapshot] = []
        for scenario_name, mne in scenario_mnemonics:
            series = await self.fetch_timeseries(mne, start_date)
            for date_str, val in series:
                results.append(
                    RiskScenarioSnapshot(date=date_str, scenario=scenario_name, value=val)
                )
        return sorted(results, key=lambda s: s.date, reverse=True)

    async def search_series(self, query: str) -> list[SeriesMetadata]:
        """Search available mnemonics by keyword.

        Endpoint: /metadata/search?query={query}
        Use wildcards: ``*leverage*`` matches all leverage-related series.
        """
        await self._rate_limiter.acquire()
        url = f"{self._base_url}/metadata/search"
        try:
            response = await self._client.get(url, params={"query": query})
            response.raise_for_status()
            body = response.json()

            # Response is list of {mnemonic, dataset, field, value, type}.
            # Group by mnemonic, extract description from field="description/name".
            meta_map: dict[str, dict[str, str]] = {}
            for item in body if isinstance(body, list) else []:
                mne = item.get("mnemonic", "")
                if not mne:
                    continue
                entry = meta_map.setdefault(mne, {"mnemonic": mne, "dataset": item.get("dataset", "")})
                field_name = item.get("field", "")
                if field_name == "description/name":
                    entry["description"] = item.get("value", "")
                elif field_name == "frequency":
                    entry["frequency"] = item.get("value", "")

            return [
                SeriesMetadata(
                    mnemonic=v["mnemonic"],
                    description=v.get("description", ""),
                    dataset=v.get("dataset", ""),
                    frequency=v.get("frequency", ""),
                )
                for v in meta_map.values()
            ]
        except Exception as e:
            logger.warning("ofr search failed", query=query, error=str(e))
            return []


# ---------------------------------------------------------------------------
#  DB reader functions — read from ofr_hedge_fund_data hypertable
# ---------------------------------------------------------------------------


async def get_ofr_leverage_from_db(
    db: AsyncSession,
    lookback_days: int = 730,
) -> list[dict[str, Any]]:
    """Read OFR leverage data from the ofr_hedge_fund_data hypertable."""
    from app.shared.models import OfrHedgeFundData

    cutoff = date.today() - timedelta(days=lookback_days)
    stmt = (
        select(OfrHedgeFundData.obs_date, OfrHedgeFundData.series_id, OfrHedgeFundData.value)
        .where(
            OfrHedgeFundData.series_id.startswith("OFR_LEVERAGE_"),
            OfrHedgeFundData.obs_date >= cutoff,
        )
        .order_by(OfrHedgeFundData.obs_date.desc())
    )
    result = await db.execute(stmt)
    return [
        {"date": str(r.obs_date), "series_id": r.series_id, "value": float(r.value)}
        for r in result.all()
        if r.value is not None
    ]


async def get_ofr_industry_size_from_db(
    db: AsyncSession,
    lookback_days: int = 730,
) -> list[dict[str, Any]]:
    """Read OFR industry size data from the ofr_hedge_fund_data hypertable."""
    from app.shared.models import OfrHedgeFundData

    cutoff = date.today() - timedelta(days=lookback_days)
    stmt = (
        select(OfrHedgeFundData.obs_date, OfrHedgeFundData.series_id, OfrHedgeFundData.value)
        .where(
            OfrHedgeFundData.series_id.startswith("OFR_INDUSTRY_"),
            OfrHedgeFundData.obs_date >= cutoff,
        )
        .order_by(OfrHedgeFundData.obs_date.desc())
    )
    result = await db.execute(stmt)
    return [
        {"date": str(r.obs_date), "series_id": r.series_id, "value": float(r.value)}
        for r in result.all()
        if r.value is not None
    ]


async def get_ofr_repo_volumes_from_db(
    db: AsyncSession,
    lookback_days: int = 730,
) -> list[dict[str, Any]]:
    """Read OFR FICC repo volumes from the ofr_hedge_fund_data hypertable."""
    from app.shared.models import OfrHedgeFundData

    cutoff = date.today() - timedelta(days=lookback_days)
    stmt = (
        select(OfrHedgeFundData.obs_date, OfrHedgeFundData.value)
        .where(
            OfrHedgeFundData.series_id == "OFR_REPO_VOLUME",
            OfrHedgeFundData.obs_date >= cutoff,
        )
        .order_by(OfrHedgeFundData.obs_date.desc())
    )
    result = await db.execute(stmt)
    return [
        {"date": str(r.obs_date), "value": float(r.value)}
        for r in result.all()
        if r.value is not None
    ]


async def get_ofr_risk_scenarios_from_db(
    db: AsyncSession,
    lookback_days: int = 730,
) -> list[dict[str, Any]]:
    """Read OFR stress scenario results from the ofr_hedge_fund_data hypertable."""
    from app.shared.models import OfrHedgeFundData

    cutoff = date.today() - timedelta(days=lookback_days)
    stmt = (
        select(OfrHedgeFundData.obs_date, OfrHedgeFundData.series_id, OfrHedgeFundData.value)
        .where(
            OfrHedgeFundData.series_id.startswith("OFR_CDS_"),
            OfrHedgeFundData.obs_date >= cutoff,
        )
        .order_by(OfrHedgeFundData.obs_date.desc())
    )
    result = await db.execute(stmt)
    return [
        {"date": str(r.obs_date), "series_id": r.series_id, "value": float(r.value)}
        for r in result.all()
        if r.value is not None
    ]
