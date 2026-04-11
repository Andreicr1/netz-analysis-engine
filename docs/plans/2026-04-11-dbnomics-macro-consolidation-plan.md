# DB-nomics Macro Consolidation — Stable Provider Tiering

**Created:** 2026-04-11
**Status:** Plan locked, no code written yet (execution paused pending route refactor work)
**Owner:** Andrei
**Driver:** The `macro_ingestion` worker silently skips FRED series that get renamed upstream (OECD publishes a new methodology → FRED retires the old series ID → 400 → `_classify_error` classifies as `skip` → coverage drops invisibly). The core Fed-native series (DFF, DGS10, CPIAUCSL, UNRATE, VIXCLS, BAA10Y, Case-Shiller metros) never fail — the pain comes exclusively from OECD/ECB/BIS/IMF/BCB series that FRED **proxies** from external providers. This plan eliminates the proxy layer for those providers by going through DB-nomics (a free academic SDMX aggregator from CEPREMAP that federates OECD, ECB, Eurostat, BIS, IMF, World Bank, and ~90 other sources into a single REST API with stable identifiers).

Complementary to [2026-04-11-tiingo-migration-plan.md](./2026-04-11-tiingo-migration-plan.md). Tiingo consolidates price/NAV data; DB-nomics consolidates macro data. Different domains, same principle: **one stable provider per origin**.

---

## 1. Decisions already locked

| Decision | Value | Rationale |
|---|---|---|
| FRED retention | Keep as primary for US-origin series | ~65 series from BLS/BEA/Fed/Treasury/S&P/ICE are stable and never rename. FRED is the authoritative aggregation layer. |
| DB-nomics adoption | Single aggregator for OECD + ECB + Eurostat + BIS + IMF + World Bank | Free, no auth, stable SDMX identifiers from primary sources. Eliminates the FRED-as-OECD-proxy rename problem at root. |
| BCB direct | Separate tiny integration | DB-nomics BCB provider only has Balance of Payments — no SELIC, no IPCA. Going direct to `https://api.bcb.gov.br/dados/serie` (SGS) for 2 series is cheaper than hoping DB-nomics expands coverage. |
| Worker collapse | `bis_ingestion` (lock 900_014) and `imf_ingestion` (lock 900_015) fold into `macro_ingestion` (lock 43) | Both already hit the same primary sources that DB-nomics exposes. One worker, one lock, one fetch strategy. |
| Canonical series ID strategy | Keep existing FRED IDs as the canonical key in `macro_data.series_id` | Zero downstream consumer churn. Migrate the **source** of each series, not its identifier. `macro_data.source` column flips from `fred` → `dbnomics` / `bcb` per row origin. |
| Historical `source='fred'` rows | Preserved | Migration changes future writes; historical rows stay as they are. |
| Rate limit | None — DB-nomics is free & open | Add bounded concurrency via `httpx.AsyncClient.limits` for local socket budget (100 connections) |
| Execution order vs Tiingo plan | Sequential, not parallel | Tiingo plan touches `providers/` + workers + catalog schema. This plan touches only macro workers + adds a new DB-nomics client. Zero file overlap, but sequencing avoids confusing CI runs. |

## 2. Validated DB-nomics coverage

Verified by direct API calls against `https://api.db.nomics.world/v22` on 2026-04-11:

| Provider | Code | Datasets relevant to us | Status |
|---|---|---|---|
| OECD | `OECD` | `DSD_STES@DF_CLI` (Composite Leading Indicators, 4 variants), short-term economic statistics, DP_LIVE | ✅ Full coverage — replaces all FRED OECD-proxied series |
| ECB | `ECB` | 17 category tree: Prices, Monetary operations, Monetary & financial statistics, Financial markets & interest rates, ECB/Eurosystem policy rates, External transactions, Government finance, Euro area accounts, ECB surveys, RTDB research | ✅ Full — replaces ECBDFR (deposit rate) and derived Euro rates |
| Eurostat | `Eurostat` | `PRC_HICP_FP` (HICP first published), `PRC_HICP_AIND` (HICP annual), and full Eurostat catalog via SDMX | ✅ Full — replaces `CP0000EZ19M086NEST` (Eurostat HICP proxied by FRED) |
| BIS | `BIS` | `WEBSTATS_CREDGAP` (credit gaps), `WEBSTATS_DSR` (debt service ratio), `WEBSTATS_PP` (property prices), `WEBSTATS_TOTCRED` (total credit), `WEBSTATS_GLI` (global liquidity), `WEBSTATS_CPI` (consumer prices), `WEBSTATS_EXCHRATES`, `CBPOL` (policy rates) | ✅ Full — **collapses `bis_ingestion` worker entirely** |
| IMF | `IMF` | `WEO` (World Economic Outlook forecasts), `IFS` (International Financial Statistics), `BOP`, `BOPAGG`, `CDIS`, `COFER`, regional outlooks (AFRREO, APDREO, ...) | ✅ Full — **collapses `imf_ingestion` worker entirely** |
| World Bank | `WB` | Full WDI catalog | ✅ Full, not currently used but available for future demographics/development indicators |
| **BCB** | `BCB` | **ONLY** `bop` (Balance of Payments, 120 series, last indexed 2025-06-29) | ❌ **Insufficient** — no SELIC, no IPCA, no policy rates. Must go direct to BCB SGS. |

**Search validation (negative results to confirm FRED retention):**

- `DGS10` on DB-nomics → 0 results
- `DFF` on DB-nomics → 0 results
- `UNRATE` on DB-nomics → 0 results
- `CPIAUCSL` on DB-nomics → 0 results
- `VIXCLS` on DB-nomics → 0 results

DB-nomics' `FED` provider is the **Federal Reserve Board of Governors** statistical releases (G.17 Industrial Production, CHGDEL Delinquency, H.8 Bank Balance Sheets, Z.1 Financial Accounts) — **not** the St. Louis Fed FRED aggregation. H.15 Selected Interest Rates is not published. This is why FRED retention is mandatory.

## 3. Target architecture — three tiers

```
                       ┌─────────────────────────┐
                       │   macro_ingestion       │
                       │   (lock 43, daily)      │
                       └────────────┬────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
              ▼                     ▼                     ▼
     ┌────────────────┐   ┌────────────────────┐   ┌──────────────┐
     │ FRED           │   │ DB-nomics          │   │ BCB SGS      │
     │ (~65 series)   │   │ (~25 series)       │   │ (2 series)   │
     │                │   │                    │   │              │
     │ US Treasury    │   │ OECD CLI           │   │ SELIC        │
     │ DFF, DGS10/2   │   │ Euro rates (ECB)   │   │ IPCA         │
     │ CPIAUCSL       │   │ HICP (Eurostat)    │   │              │
     │ UNRATE, PAYEMS │   │ BIS credit gap     │   │              │
     │ VIXCLS         │   │ BIS DSR            │   │              │
     │ BAML spreads   │   │ BIS property       │   │              │
     │ Case-Shiller   │   │ IMF WEO            │   │              │
     │   (20 metros)  │   │ IMF IFS            │   │              │
     │ Commodities    │   │ WB WDI             │   │              │
     └────────┬───────┘   └──────────┬─────────┘   └──────┬───────┘
              │                      │                    │
              └──────────────────────┼────────────────────┘
                                     ▼
                           ┌──────────────────────┐
                           │ macro_data           │
                           │ hypertable           │
                           │                      │
                           │ series_id (canonical)│
                           │ source ∈ {fred,      │
                           │   dbnomics, bcb}     │
                           │ value, obs_date      │
                           └──────────────────────┘
```

**Collapsed workers** (eliminated in this plan):
- `bis_ingestion` (lock 900_014, weekly) → rolls into `macro_ingestion`
- `imf_ingestion` (lock 900_015, quarterly) → rolls into `macro_ingestion`

Both workers currently write to their own hypertables (`bis_statistics`, `imf_weo_forecasts`). **Migration decision:** keep those tables for historical data, but point new writes at `macro_data` with BIS/IMF series prefixed canonical IDs (`BIS_CREDGAP_US`, `IMF_WEO_USA_GDP_GROWTH`, etc.). Dual-write is **not** needed — existing readers of `bis_statistics` and `imf_weo_forecasts` are counted and migrated in §6.3 before the writer switches.

## 4. Series migration map

### 4.1 From FRED → DB-nomics (24 series)

| Canonical `series_id` (kept unchanged) | DB-nomics path | Frequency | Reason for migration |
|---|---|---|---|
| `CLVMNACSCAB1GQEA19` | `Eurostat/NAMQ_10_GDP/Q.CLV10_MEUR.SCA.B1GQ.EA19` | Quarterly | Currently FRED-proxied from Eurostat |
| `CP0000EZ19M086NEST` | `Eurostat/PRC_HICP_MANR/M.RCH_A.CP00.EA19` | Monthly | HICP direct from Eurostat |
| `ECBDFR` | `ECB/FM/D.U2.EUR.4F.KR.DFR.LEV` | Daily | ECB deposit facility rate native |
| `IRLTLT01DEM156N` | `ECB/FM/M.DE.EUR.4F.BB.U_A10Y.YLD` | Monthly | German 10Y Bund from ECB direct |
| `CSCICP02EZM460S` | `OECD/DSD_STES@DF_BCI_CCI/EA19.BC.CSMR.AS` | Monthly | Consumer confidence from OECD direct |
| `JPNRGDPEXP` | `OECD/DSD_STES@DF_QNA/JPN.B1GQ.VOLVC.IX.Q` | Quarterly | Japan GDP from OECD |
| `CHNLOLITOAASTSAM` | `OECD/DSD_STES@DF_CLI/CHN.LOLI.AA.M` | Monthly | **OECD CLI China — the main pain point today** |
| `JPNLOLITOAASTSAM` | `OECD/DSD_STES@DF_CLI/JPN.LOLI.AA.M` | Monthly | OECD CLI Japan |
| `JPNCPIALLMINMEI` | `OECD/DSD_STES@DF_CPI/JPN.CPALTT01.IXOB.M` | Monthly | Japan CPI from OECD direct |
| `CHNCPIALLMINMEI` | `OECD/DSD_STES@DF_CPI/CHN.CPALTT01.IXOB.M` | Monthly | China CPI from OECD direct |
| `IRLTLT01JPM156N` | `OECD/DSD_STES@DF_LTIR/JPN.IRLT.M` | Monthly | Japan 10Y yield from OECD |
| `BRALOLITOAASTSAM` | `OECD/DSD_STES@DF_CLI/BRA.LOLI.AA.M` | Monthly | OECD CLI Brazil |
| `INDLOLITOAASTSAM` | `OECD/DSD_STES@DF_CLI/IND.LOLI.AA.M` | Monthly | OECD CLI India |
| `MEXLOLITONOSTSAM` | `OECD/DSD_STES@DF_CLI/MEX.LOLI.NO.M` | Monthly | OECD CLI Mexico |
| `INDCPIALLMINMEI` | `OECD/DSD_STES@DF_CPI/IND.CPALTT01.IXOB.M` | Monthly | India CPI from OECD |

**Exact dataset codes above are illustrative.** PR-A §5.2 includes a one-shot discovery script (`scripts/discover_dbnomics_mapping.py`) that runs search queries against DB-nomics for each canonical FRED ID, presents candidate matches ranked by relevance, and writes the confirmed mapping to `backend/app/shared/macro/dbnomics_series_map.yaml`. The mapping is hand-reviewed once before PR-B cutover. This is non-negotiable — if we guess the dataset codes we inherit exactly the rename problem we're trying to escape.

### 4.2 From BIS direct API → DB-nomics (~8 series, collapses `bis_ingestion`)

| Current `bis_statistics` table | DB-nomics path | Notes |
|---|---|---|
| Credit gap (US) | `BIS/WEBSTATS_CREDGAP/Q.US.N.A.M.770.A` | Quarterly |
| Credit gap (Euro area) | `BIS/WEBSTATS_CREDGAP/Q.XM.N.A.M.770.A` | |
| Debt service ratio (US private non-financial) | `BIS/WEBSTATS_DSR/Q.US.P.A.770` | |
| Debt service ratio (Euro area) | `BIS/WEBSTATS_DSR/Q.XM.P.A.770` | |
| Property prices (US residential) | `BIS/WEBSTATS_PP/Q.US.R.628.A` | Quarterly |
| Property prices (Euro area residential) | `BIS/WEBSTATS_PP/Q.XM.R.628.A` | |
| Total credit (US private non-financial) | `BIS/WEBSTATS_TOTCRED/Q.US.P.A.M.770.A` | |
| CBPOL policy rates | `BIS/CBPOL/D.*` | Daily policy rates by country |

Current worker `bis_ingestion` uses BIS SDMX directly and is noisy (BIS SDMX gateway has historically been flaky). DB-nomics mirrors BIS with a stable cache layer.

**Historical data preservation:** the existing `bis_statistics` hypertable is NOT dropped. Writes shift to `macro_data`; the old table becomes read-only for historical queries until the last consumer is migrated (`quant_engine/regional_macro_service.py::build_regional_snapshot` reads from both). A follow-up sprint drops `bis_statistics` after 2 quarters of dual-path stability.

### 4.3 From IMF direct API → DB-nomics (IMF WEO biannual, collapses `imf_ingestion`)

`imf_ingestion` currently hits `https://www.imf.org/external/datamapper/api/v1/` for WEO GDP growth and inflation forecasts across ~40 countries, writing to `imf_weo_forecasts` hypertable.

| Current source | DB-nomics path |
|---|---|
| IMF DataMapper `NGDP_RPCH` | `IMF/WEO:{release}/{country}.NGDP_RPCH` — GDP growth projection |
| IMF DataMapper `PCPIPCH` | `IMF/WEO:{release}/{country}.PCPIPCH` — Inflation projection |
| IMF DataMapper `NGDPD` | `IMF/WEO:{release}/{country}.NGDPD` — GDP in USD |

**WEO release versioning:** DB-nomics stores each WEO release as a separate dataset (`IMF/WEO:2024-10`, `IMF/WEO:2025-04`, etc.). The worker must query `https://api.db.nomics.world/v22/datasets/IMF` at startup, find the most recent `WEO:YYYY-MM` dataset, and use it. Update every 6 months when the new release lands.

**Same historical preservation as §4.2** — `imf_weo_forecasts` hypertable kept, writes shift to `macro_data`, consumers migrated before drop.

### 4.4 BCB direct (2 series, new tiny integration)

```python
# backend/quant_engine/bcb_service.py
BCB_SGS_SERIES = {
    "BCB_SELIC": 11,      # SGS code for Selic overnight target
    "BCB_IPCA_YOY": 13522, # SGS code for IPCA 12-month cumulative
}

# Endpoint:
# https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados?formato=json&dataInicial={d}&dataFinal={d}
```

BCB SGS (Sistema Gerenciador de Séries Temporais) is a free, no-auth REST API. Single endpoint per series, JSON response, stable numeric codes since 2000+. The entire integration fits in ~80 lines and replaces the `INTDSRBRM193N` + `BRACPIALLMINMEI` FRED-proxied rows.

**Replaces in `CREDIT_SERIES` and `REGION_SERIES["EM"]`:**
- `INTDSRBRM193N` → `BCB_SELIC` (daily → canonical ID renamed, `source='bcb'`)
- `BRACPIALLMINMEI` → `BCB_IPCA_YOY` (monthly)

## 5. Work package — PR-A (DB-nomics client + discovery script)

**Goal:** land a standalone DB-nomics client with tests and the mapping discovery script. No worker changes, no behavior changes. PR merges on its own before PR-B wires it in.

### 5.1 `backend/quant_engine/dbnomics_service.py`

```python
"""DB-nomics REST client — stable SDMX aggregator across OECD, ECB, BIS, IMF, WB.

DB-nomics (https://db.nomics.world/) is a free academic SDMX aggregator from
CEPREMAP that federates ~93 macroeconomic providers under a single REST API.
Used for all macro series whose primary source is OECD, ECB, Eurostat, BIS,
IMF, or World Bank. FRED-native series (DFF, DGS10, UNRATE, CPIAUCSL, VIXCLS,
Case-Shiller, BAML spreads) stay on FredService — DB-nomics does not mirror
the St. Louis Fed aggregation layer.

No auth. No rate limit (open data). Bounded concurrency via httpx.Limits.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DBNOMICS_BASE_URL = "https://api.db.nomics.world/v22"
DEFAULT_TIMEOUT = 30.0
BATCH_CONCURRENCY = 20


@dataclass(frozen=True, slots=True)
class DBnomicsObservation:
    provider_code: str
    dataset_code: str
    series_code: str
    obs_date: date
    value: float | None


class DBnomicsService:
    """Synchronous DB-nomics client suitable for worker thread pools."""

    def __init__(
        self,
        http_client: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._client = http_client or httpx.Client(
            timeout=timeout,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
            headers={"Accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> DBnomicsService:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch_series(
        self,
        provider_code: str,
        dataset_code: str,
        series_code: str,
        observation_start: date | None = None,
    ) -> list[DBnomicsObservation]:
        """Fetch a single series by (provider, dataset, series) triplet.

        Returns empty list on 404 (series removed upstream) or non-200.
        """
        url = f"{DBNOMICS_BASE_URL}/series/{provider_code}/{dataset_code}/{series_code}"
        params: dict[str, str] = {"observations": "1"}
        if observation_start:
            params["observations_start"] = observation_start.isoformat()

        try:
            resp = self._client.get(url, params=params)
            if resp.status_code in (404, 400):
                logger.warning(
                    "dbnomics_series_not_found",
                    provider=provider_code,
                    dataset=dataset_code,
                    series=series_code,
                )
                return []
            if resp.status_code != 200:
                logger.warning(
                    "dbnomics_non_200",
                    status=resp.status_code,
                    provider=provider_code,
                )
                return []
            payload = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("dbnomics_http_error error=%s", exc)
            return []

        return self._parse_series(payload, provider_code, dataset_code, series_code)

    def fetch_batch(
        self,
        mappings: list[tuple[str, str, str]],
        observation_start: date | None = None,
    ) -> dict[tuple[str, str, str], list[DBnomicsObservation]]:
        """Fetch many series in parallel through a thread pool.

        Each tuple is (provider, dataset, series). Returns a dict keyed by
        the same tuple — missing keys indicate the series returned empty.
        """
        import concurrent.futures

        results: dict[tuple[str, str, str], list[DBnomicsObservation]] = {}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=BATCH_CONCURRENCY,
            thread_name_prefix="dbnomics-fetch",
        ) as pool:
            futures = {
                pool.submit(
                    self.fetch_series,
                    provider,
                    dataset,
                    series,
                    observation_start,
                ): (provider, dataset, series)
                for provider, dataset, series in mappings
            }
            for fut in concurrent.futures.as_completed(futures):
                key = futures[fut]
                try:
                    obs = fut.result()
                    if obs:
                        results[key] = obs
                except Exception as exc:
                    logger.warning(
                        "dbnomics_task_failed",
                        key=key,
                        error=str(exc),
                    )

        return results

    def search_series(
        self,
        query: str,
        provider_code: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search for series by free-text query. Used by discovery script only."""
        url = f"{DBNOMICS_BASE_URL}/search"
        params: dict[str, str] = {"q": query, "limit": str(limit)}
        if provider_code:
            params["provider_code"] = provider_code
        try:
            resp = self._client.get(url, params=params)
            if resp.status_code != 200:
                return []
            return resp.json().get("results", {}).get("docs", [])
        except httpx.HTTPError:
            return []

    # ── Internals ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_series(
        payload: dict[str, Any],
        provider_code: str,
        dataset_code: str,
        series_code: str,
    ) -> list[DBnomicsObservation]:
        series_list = payload.get("series", {}).get("docs", [])
        if not series_list:
            return []
        doc = series_list[0]
        periods = doc.get("period", [])
        values = doc.get("value", [])
        out: list[DBnomicsObservation] = []
        for period_str, raw_val in zip(periods, values, strict=False):
            obs_date = _parse_period(period_str)
            if obs_date is None:
                continue
            try:
                val = float(raw_val) if raw_val not in (None, "NA") else None
            except (TypeError, ValueError):
                continue
            out.append(
                DBnomicsObservation(
                    provider_code=provider_code,
                    dataset_code=dataset_code,
                    series_code=series_code,
                    obs_date=obs_date,
                    value=val,
                ),
            )
        return out


def _parse_period(raw: str) -> date | None:
    """DB-nomics period format varies by frequency:
    - Daily:   "2026-04-10"
    - Weekly:  "2026-W15" (ISO week)
    - Monthly: "2026-04"
    - Quarterly: "2026-Q2"
    - Annual:  "2026"
    """
    try:
        if "W" in raw:
            year, week = raw.split("-W")
            return date.fromisocalendar(int(year), int(week), 1)
        if "Q" in raw:
            year, q = raw.split("-Q")
            month = (int(q) - 1) * 3 + 1
            return date(int(year), month, 1)
        parts = raw.split("-")
        if len(parts) == 1:
            return date(int(parts[0]), 1, 1)
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return None
```

### 5.2 `backend/scripts/discover_dbnomics_mapping.py`

A one-shot discovery script that takes the list of ~24 canonical FRED series IDs we want to migrate, runs targeted searches against DB-nomics via `search_series()`, ranks candidates by substring match on the FRED title + provider preference (`OECD > ECB > Eurostat > BIS > IMF`), writes human-reviewable candidates to `backend/app/shared/macro/dbnomics_series_map.yaml.draft`, and prints a diff against any existing mapping file. Andrei hand-reviews, renames the draft to `.yaml`, commits.

This gates the whole migration. No guessing of dataset codes in code review. The mapping file is the contract.

```yaml
# backend/app/shared/macro/dbnomics_series_map.yaml
# Canonical FRED series ID → DB-nomics (provider, dataset, series) triplet
# Hand-reviewed after running scripts/discover_dbnomics_mapping.py

CLVMNACSCAB1GQEA19:
  provider: Eurostat
  dataset: NAMQ_10_GDP
  series: Q.CLV10_MEUR.SCA.B1GQ.EA19
  notes: "Euro Area Real GDP (quarterly, chain-linked volumes)"

ECBDFR:
  provider: ECB
  dataset: FM
  series: D.U2.EUR.4F.KR.DFR.LEV
  notes: "ECB deposit facility rate (daily)"

CHNLOLITOAASTSAM:
  provider: OECD
  dataset: DSD_STES@DF_CLI
  series: CHN.LOLI.AA.M
  notes: "OECD Composite Leading Indicator China (amplitude-adjusted, monthly)"

# ... rest of the 24 entries
```

### 5.3 Tests — `backend/tests/test_dbnomics_service.py`

Mirror the `test_tiingo_provider_layer.py` pattern: `httpx.MockTransport` for all HTTP, no real DB-nomics calls. Cover:

- `fetch_series` happy path with monthly series
- `fetch_series` period parsing: daily, weekly, quarterly, monthly, annual
- `fetch_series` 404 → empty list
- `fetch_series` non-200 → empty list, logged
- `fetch_batch` fans out via thread pool, merges results
- `fetch_batch` partial failure: one 404 + two 200s → dict with 2 keys
- `search_series` returns sorted docs
- `_parse_period` for each frequency format
- Context manager protocol

### 5.4 Gate PR-A

```bash
cd backend
python -m ruff check quant_engine/dbnomics_service.py scripts/discover_dbnomics_mapping.py tests/test_dbnomics_service.py
python -m mypy quant_engine/dbnomics_service.py --ignore-missing-imports
python -m pytest tests/test_dbnomics_service.py -x
```

No architecture changes. Import-linter clean. No integration tests — the mapping discovery script runs manually once.

## 6. Work package — PR-B (Worker cutover + BCB integration)

**Depends on:** PR-A merged, mapping file hand-reviewed and committed.

### 6.1 Enhance `macro_ingestion` worker to multi-source

The existing `macro_ingestion` worker (lock 43) fetches all series from `FredService.fetch_batch_concurrent()`. Enhance it to split the series list by source:

```python
# backend/app/domains/wealth/workers/macro_ingestion.py

async def _do_ingest(db: AsyncSession) -> dict[str, Any]:
    fred_series, dbnomics_series, bcb_series = _partition_series_by_source()

    rows: list[dict[str, Any]] = []

    # Tier 1: FRED (existing path, unchanged)
    fred_svc = FredService(api_key=settings.fred_api_key)
    fred_obs = await asyncio.to_thread(
        fred_svc.fetch_batch_concurrent, fred_series,
    )
    rows.extend(_obs_to_macro_data_rows(fred_obs, source="fred"))

    # Tier 2: DB-nomics (new path)
    with DBnomicsService() as dbn:
        dbn_obs = await asyncio.to_thread(
            dbn.fetch_batch,
            [(m.provider, m.dataset, m.series) for m in dbnomics_series],
        )
    rows.extend(_dbnomics_obs_to_macro_data_rows(dbn_obs, dbnomics_series))

    # Tier 3: BCB direct (new tiny integration)
    with BcbSgsService() as bcb:
        bcb_obs = await asyncio.to_thread(bcb.fetch_batch, bcb_series)
    rows.extend(_bcb_obs_to_macro_data_rows(bcb_obs))

    # Single upsert to macro_data — source column distinguishes origin
    await _upsert_macro_data(db, rows)
    ...
```

`_partition_series_by_source()` reads the canonical series list from `regional_macro_service.REGION_SERIES + GLOBAL_SERIES + CREDIT_SERIES` and cross-references `dbnomics_series_map.yaml` to classify each one as FRED / DB-nomics / BCB.

### 6.2 New `backend/quant_engine/bcb_service.py` (SGS SELIC + IPCA)

~80 lines. Single endpoint pattern:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime

import httpx

logger = logging.getLogger(__name__)

BCB_SGS_BASE_URL = "https://api.bcb.gov.br/dados/serie"

BCB_SERIES: dict[str, int] = {
    "BCB_SELIC": 11,        # Taxa Selic (% a.a. alvo Copom)
    "BCB_IPCA_YOY": 13522,  # IPCA - variação acumulada 12 meses
}


@dataclass(frozen=True, slots=True)
class BcbObservation:
    canonical_series_id: str
    obs_date: date
    value: float


class BcbSgsService:
    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._client = http_client or httpx.Client(
            timeout=30.0,
            headers={"Accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> BcbSgsService:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch_series(
        self,
        canonical_series_id: str,
        observation_start: date | None = None,
    ) -> list[BcbObservation]:
        sgs_code = BCB_SERIES.get(canonical_series_id)
        if sgs_code is None:
            logger.warning("bcb_unknown_canonical_id series=%s", canonical_series_id)
            return []

        url = f"{BCB_SGS_BASE_URL}/bcdata.sgs.{sgs_code}/dados"
        params: dict[str, str] = {"formato": "json"}
        if observation_start:
            params["dataInicial"] = observation_start.strftime("%d/%m/%Y")

        try:
            resp = self._client.get(url, params=params)
            if resp.status_code != 200:
                logger.warning(
                    "bcb_non_200 series=%s status=%s",
                    canonical_series_id, resp.status_code,
                )
                return []
            payload = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("bcb_http_error error=%s", exc)
            return []

        if not isinstance(payload, list):
            return []

        out: list[BcbObservation] = []
        for item in payload:
            raw_date = item.get("data", "")
            raw_val = item.get("valor", "")
            try:
                # BCB returns dates as "dd/mm/yyyy" and values as string with decimal comma
                obs_date = datetime.strptime(raw_date, "%d/%m/%Y").date()
                val = float(raw_val.replace(",", "."))
            except (ValueError, AttributeError):
                continue
            out.append(
                BcbObservation(
                    canonical_series_id=canonical_series_id,
                    obs_date=obs_date,
                    value=val,
                ),
            )
        return out

    def fetch_batch(
        self,
        canonical_series_ids: list[str],
        observation_start: date | None = None,
    ) -> list[BcbObservation]:
        out: list[BcbObservation] = []
        for sid in canonical_series_ids:
            out.extend(self.fetch_series(sid, observation_start))
        return out
```

No thread pool needed — only 2 series, serial is fine.

### 6.3 Consumer migration for `bis_statistics` / `imf_weo_forecasts`

Before collapsing workers, every reader of the old tables must be switched to `macro_data`. Grep targets:

```bash
grep -rn "BisStatistics\|bis_statistics\|ImfWeoForecast\|imf_weo_forecasts" backend/
```

Expected consumers (from CLAUDE.md + code read):
- `quant_engine/regional_macro_service.py::build_regional_snapshot` — reads BIS credit gap
- `quant_engine/stress_severity_service.py` — reads IMF WEO GDP growth for macro backdrop
- `vertical_engines/credit/market_data/*` — reads BIS property prices for real estate deals
- `vertical_engines/wealth/macro_committee_engine.py` — reads IMF WEO

Each consumer changes from:
```python
stmt = select(BisStatistics).where(BisStatistics.indicator == "credit_gap_us")
```
to:
```python
stmt = select(MacroData).where(MacroData.series_id == "BIS_CREDGAP_US")
```

One PR per consumer module to keep blast radius small, or bundle them in PR-B if reviewable. I recommend bundling — 4-5 files, ~200 lines of diff total.

### 6.4 Worker deprecation

After consumers migrate:

1. `bis_ingestion.py` → `git rm backend/app/domains/wealth/workers/bis_ingestion.py`, release lock `900_014`, remove from `manifests/workers.json`
2. `imf_ingestion.py` → `git rm backend/app/domains/wealth/workers/imf_ingestion.py`, release lock `900_015`, remove from `manifests/workers.json`
3. Update `CLAUDE.md` worker table to reflect the collapse

### 6.5 Migration 0111 — series_id canonical additions

Some canonical series in the mapping don't exist in today's `macro_data.series_id` column (`BIS_CREDGAP_US`, `IMF_WEO_USA_GDP_GROWTH`, `BCB_SELIC`, `BCB_IPCA_YOY`). The column is already text and accepts arbitrary values — no schema change required.

**What DOES need a migration:** the `source` column enum (if any) and any CHECK constraint. Current `macro_data.source` defaults to `'fred'` but it's a plain text column (confirmed in `0013_benchmark_nav.py` pattern, not the enum type). Verify with:
```bash
cd backend && python -c "from app.shared.models import MacroData; print(MacroData.__table__.c.source)"
```

If it's a plain `String` — no migration needed. If it's an `Enum` — add migration 0111 to extend the enum with `'dbnomics'` and `'bcb'`. I expect plain text, but confirm during PR-B implementation.

### 6.6 Gate PR-B

```bash
cd backend
python -m alembic upgrade head  # noop unless 0111 is needed
python -m ruff check app/domains/wealth/workers/macro_ingestion.py quant_engine/bcb_service.py
python -m mypy app/domains/wealth/workers/macro_ingestion.py quant_engine/bcb_service.py --ignore-missing-imports
python -m pytest tests/test_macro_ingestion.py tests/test_bcb_service.py tests/test_regional_macro_service.py -x
python scripts/run_global_worker.py macro_ingestion  # smoke test against real DB-nomics + BCB
```

Smoke test success criteria:
- `macro_data` row count increases proportionally (+ ~25 dbnomics rows + 2 bcb rows per ingestion cycle)
- `SELECT source, COUNT(*) FROM macro_data WHERE obs_date > CURRENT_DATE - INTERVAL '90 days' GROUP BY source` shows `fred`, `dbnomics`, `bcb` all populated
- `_fetch_stress_dates()` in `risk_calc.py` still returns a non-empty set (HMM regime classification unaffected)

## 7. Work package — PR-C (Rename detector + observability)

**Depends on:** PR-B merged and stable.

### 7.1 FRED series rename detector

For the ~65 series we keep on FRED, add a monthly reconciliation job that detects when a FRED series is renamed upstream (our symptom: silent zero coverage). The job:

1. Reads the canonical series list
2. For each, calls `https://api.stlouisfed.org/fred/series?series_id=X&api_key=...`
3. Checks the `notes` field for "Discontinued" or "Replaced by" language
4. Checks `last_updated` — if stale > 90 days while the series should be daily/weekly, flags
5. Writes alerts to a new `macro_series_alerts` table + emits structlog events

Runs weekly (lock 900_016). Low-cost, catches problems before they propagate.

### 7.2 Per-series observability

Mirrors the §12.12 pattern from the Tiingo plan. Add structured logs to `macro_ingestion`:

```python
logger.info(
    "macro_ingestion.tier_summary",
    tier="dbnomics",
    series_expected=len(dbnomics_series),
    series_fetched=len(dbn_obs),
    rows_written=sum(len(v) for v in dbn_obs.values()),
    duration_ms=...,
)
```

Alerts when `series_fetched / series_expected < 0.8` for any tier. Railway logs → Slack.

### 7.3 Gate PR-C

`make check` full gate.

## 8. Operational validation (post-PR-B merge)

```sql
-- 1. Source distribution per obs_date (should be 3 sources after migration)
SELECT
  obs_date,
  source,
  COUNT(*) as series_count
FROM macro_data
WHERE obs_date >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY obs_date, source
ORDER BY obs_date DESC, source;

-- 2. Series coverage health per canonical ID
SELECT
  series_id,
  source,
  MAX(obs_date) AS latest,
  (CURRENT_DATE - MAX(obs_date)) AS staleness_days
FROM macro_data
GROUP BY series_id, source
HAVING (CURRENT_DATE - MAX(obs_date)) > 30
ORDER BY staleness_days DESC;

-- 3. No series lost to the migration — reference check against regional_macro_service
SELECT COUNT(DISTINCT series_id) AS unique_series FROM macro_data;
-- Expected: at least 85 (65 FRED + 18 DB-nomics + 2 BCB), likely more if historical series kept
```

## 9. Open items before execution

1. **Verify `macro_data.source` is plain text, not enum** — affects whether migration 0111 is needed
2. **Confirm DB-nomics observation_start behavior** — does it default to full history when omitted, or require explicit date? Check in PR-A tests
3. **IMF WEO release auto-detection** — decide whether `macro_ingestion` discovers the latest `WEO:YYYY-MM` dataset at every run or reads from a config file refreshed manually
4. **BCB SGS historical depth** — SELIC starts in 1986, IPCA in 1980 — confirm the API returns full history when `dataInicial` is omitted or far in the past
5. **FredService retention** — after migration, the `FredService` still handles 65 series. No changes to that service in this plan. If we want to remove the unused OECD-proxy series from the FRED fetch list, that's a follow-up cleanup PR

## 10. Relationship to the Tiingo migration plan

Execution order: **Tiingo plan first, this plan second.** Reasons:

- Tiingo plan unblocks the current `blended_momentum_score` / `peer_sharpe_pctl` gap, which is user-facing
- Tiingo touches `providers/`, `instrument_ingestion`, `benchmark_ingest`, and the `source='yfinance'` column label — a large surface
- DB-nomics plan touches only macro workers and reference services — zero overlap with Tiingo's file set
- Once Tiingo lands and is stable, attention shifts to macro data reliability
- Both plans share the `quant_engine/` namespace but at different files (Tiingo uses `providers/`, DB-nomics adds `dbnomics_service.py` and `bcb_service.py`)

No blocking dependencies in the other direction — the Tiingo plan does not depend on any macro work.

## 11. Summary of enhancements from this plan

| Item | Before | After |
|---|---|---|
| External macro providers | 6 (FRED, BIS SDMX, IMF DataMapper, OECD-via-FRED, ECB-via-FRED, BCB-via-FRED) | 3 (FRED, DB-nomics, BCB direct) |
| Workers writing macro data | 3 (`macro_ingestion`, `bis_ingestion`, `imf_ingestion`) | 1 (`macro_ingestion`) |
| Advisory locks used | 3 (43, 900_014, 900_015) | 1 (43) |
| Series with rename risk | ~16 OECD/ECB-proxied FRED series | 0 (direct SDMX) |
| Rename detection | None — silent zero-coverage | Weekly reconciliation job with alerts |
| Code lines (worker + client) | ~1,200 (three workers + FredService for everything) | ~800 (one worker + FredService + DBnomicsService + BcbSgsService) |
| Observability | Log per-worker at end | Per-tier per-run with SLO alerting |

**The migration replaces a fragile FRED-as-universal-proxy pattern with a source-authoritative three-tier architecture.** Every series now comes from the provider that actually publishes it, via a stable SDMX aggregator where that provider offers one. The ~65 FRED-native series that have never failed continue through FRED untouched.
