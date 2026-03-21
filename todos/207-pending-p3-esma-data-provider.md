---
status: done
priority: p3
issue_id: "207"
tags: [backend, data-provider, esma, wealth]
dependencies: []
---

# ESMA Register data provider (register_service + ticker_resolver)

## Problem Statement

To expand the fund universe beyond US SEC-registered managers, we need to ingest ESMA UCITS fund data. No `esma-registers` PyPI package exists — we must query the ESMA Solr API directly and resolve ISINs to Yahoo Finance tickers via OpenFIGI.

## Proposed Solution

### Approach

Create `backend/data_providers/esma/` following the `data_providers/sec/` pattern:

1. **`models.py`** — frozen dataclasses: `EsmaManager`, `EsmaFund`, `IsinResolution`

2. **`register_service.py`** — ESMA Register API client:
   - Paginated Solr queries to `registers.esma.europa.eu/solr/esma_registers_funds_cbdif/select`
   - Filter: `funds_legal_framework_name:UCITS`
   - Uses `httpx.AsyncClient` (already a dependency)
   - Rate limiting: respect ESMA server limits
   - Returns `AsyncIterator[EsmaFund]` for memory-efficient processing

3. **`ticker_resolver.py`** — ISIN → Yahoo Finance ticker:
   - Primary: OpenFIGI batch API (`idType=ID_ISIN`, 100 per batch, 250 req/min with API key)
   - Exchange code mapping: OpenFIGI exchange → Yahoo Finance suffix (`.L`, `.PA`, `.DE`, `.AS`, `.MI`, etc.)
   - Writes resolved tickers to `esma_isin_ticker_map`

4. **`shared.py`** — shared constants (exchange suffix map, rate limits)

5. **`__init__.py`** — package init

## Technical Details

**Affected files:**
- `backend/data_providers/esma/__init__.py` — new
- `backend/data_providers/esma/models.py` — new
- `backend/data_providers/esma/register_service.py` — new
- `backend/data_providers/esma/ticker_resolver.py` — new
- `backend/data_providers/esma/shared.py` — new

**Constraints:**
- Import-linter: `data_providers` must not import `vertical_engines`, `app.domains`, or `quant_engine`
- No external `esma-registers` package — direct Solr API via httpx
- OpenFIGI free API key needed (env var `OPENFIGI_API_KEY`)
- FIRDS FULINS_C XML download for ISIN join (stdlib `xml.etree.ElementTree`)

## Acceptance Criteria

- [ ] `register_service.py` fetches UCITS fund data from ESMA Solr API
- [ ] `ticker_resolver.py` resolves ISINs via OpenFIGI batch API
- [ ] Exchange suffix mapping covers major European exchanges
- [ ] No forbidden imports (import-linter passes)
- [ ] `make check` passes (lint + typecheck + test)
