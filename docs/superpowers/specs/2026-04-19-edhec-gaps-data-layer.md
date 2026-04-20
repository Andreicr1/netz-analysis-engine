---
title: EDHEC Quant Gap Closure — Data Layer Spec
date: 2026-04-19
author: financial-timeseries-db-architect (design rounds 1 + 2)
status: approved — Cenário X3 (Tiingo included)
scope: migrations 0132/0133, matview mv_nport_sector_attribution, Tiingo hypertables, equity_characteristics_monthly
---

# Data Layer Spec — G3 Attribution Cascade + Tiingo Fundamentals + G5 Lookahead

**Audience:** senior engineer translating this into Opus execution prompts
**Migration head:** 0131 → next migrations 0132, 0133 (conditional), 0134

---

## 1. Migration 0132 — `benchmark_etf_canonical_map`

### 1.1 Classificação

Tabela **global** (sem RLS, sem `organization_id`). Dados universais (S&P 500 → SPY para todos tenants). Não é hypertable — dimensão baixa cardinalidade (~30 linhas). `CREATE TABLE` regular.

### 1.2 DDL

```sql
CREATE TYPE benchmark_asset_class AS ENUM (
    'equity_us_large', 'equity_us_mid', 'equity_us_small',
    'equity_intl_dev', 'equity_em',
    'fi_us_agg', 'fi_us_treasury', 'fi_us_hy', 'fi_us_ig', 'fi_us_muni',
    'fi_intl', 'commodities', 'reits', 'other'
);

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE benchmark_etf_canonical_map (
    id                         BIGSERIAL PRIMARY KEY,
    benchmark_name_canonical   TEXT NOT NULL,
    benchmark_name_aliases     TEXT[] NOT NULL DEFAULT '{}',
    proxy_etf_ticker           TEXT NOT NULL,
    proxy_etf_cik              TEXT,
    proxy_etf_series_id        TEXT,
    asset_class                benchmark_asset_class NOT NULL,
    fit_quality_score          NUMERIC(4,3) NOT NULL DEFAULT 1.0
        CHECK (fit_quality_score >= 0 AND fit_quality_score <= 1),
    source                     TEXT NOT NULL DEFAULT 'manual_seed',
    notes                      TEXT,
    effective_from             DATE NOT NULL DEFAULT '1900-01-01',
    effective_to               DATE NOT NULL DEFAULT '9999-12-31',
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_canonical_effective UNIQUE (benchmark_name_canonical, effective_from),
    CONSTRAINT chk_effective_range CHECK (effective_to > effective_from),
    CONSTRAINT chk_proxy_identifier CHECK (proxy_etf_cik IS NOT NULL OR proxy_etf_series_id IS NOT NULL)
);

CREATE INDEX ix_benchmark_map_canonical_trgm
    ON benchmark_etf_canonical_map USING GIN (benchmark_name_canonical gin_trgm_ops);
CREATE INDEX ix_benchmark_map_aliases_gin
    ON benchmark_etf_canonical_map USING GIN (benchmark_name_aliases);
CREATE INDEX ix_benchmark_map_ticker
    ON benchmark_etf_canonical_map (proxy_etf_ticker);
CREATE INDEX ix_benchmark_map_asset_class_active
    ON benchmark_etf_canonical_map (asset_class)
    WHERE effective_to = '9999-12-31';
```

### 1.3 Seed inline (20 rows)

```
S&P 500 → SPY (equity_us_large)
Russell 2000 → IWM (equity_us_small)
Russell 1000 → IWB
Russell Midcap → IWR (equity_us_mid)
Russell 3000 → IWV
MSCI EAFE → EFA (equity_intl_dev)
MSCI ACWI ex-US → ACWX
MSCI Emerging Markets → EEM (equity_em)
MSCI World → URTH
NASDAQ 100 → QQQ
Dow Jones Industrial Average → DIA
Bloomberg US Aggregate Bond → AGG (fi_us_agg)
Bloomberg US Treasury → GOVT (fi_us_treasury)
ICE BofA US High Yield → HYG (fi_us_hy)
Bloomberg US Corporate IG → LQD (fi_us_ig)
Bloomberg Municipal → MUB (fi_us_muni)
Bloomberg Global Agg ex-USD → BNDX (fi_intl)
Bloomberg Commodity → DJP (commodities)
MSCI US REIT → VNQ (reits)
S&P Target Date → NULL (other, fallback)
```

Cada linha traz 3-6 aliases reais capturados de `sec_registered_funds.primary_benchmark`.

### 1.4 Fuzzy match (3 níveis)

1. **Exact alias**: `WHERE :name = ANY(benchmark_name_aliases)` — O(log n) via GIN
2. **Trigram**: `WHERE canonical % :name OR EXISTS (SELECT 1 FROM unnest(aliases) a WHERE a % :name)` — threshold `set_limit(0.4)`
3. **Asset class fallback**: classifier Python classifica benchmark por keywords, cai no default

### 1.5 Reversibilidade

```sql
-- downgrade()
DROP TABLE IF EXISTS benchmark_etf_canonical_map;
DROP TYPE IF EXISTS benchmark_asset_class;
-- pg_trgm: NOT DROP (pode estar em uso por outras features)
```

---

## 2. GICS Diagnostic — Migration 0133 Conditional

### 2.1 Diagnostic SQL (read-only, Timescale Cloud)

```sql
-- Block A: Cobertura industry_sector últimos 4 trimestres
WITH recent AS (
  SELECT *
  FROM sec_nport_holdings
  WHERE period_of_report >= (CURRENT_DATE - INTERVAL '15 months')
)
SELECT
  COUNT(*)                                                    AS total_rows,
  COUNT(*) FILTER (WHERE industry_sector IS NULL
                    OR btrim(industry_sector) = '')           AS sector_null,
  ROUND(100.0 * COUNT(*) FILTER (WHERE industry_sector IS NULL
                    OR btrim(industry_sector) = '') / NULLIF(COUNT(*),0), 2) AS pct_null,
  COUNT(*) FILTER (WHERE issuer_category IS NOT NULL
                    AND btrim(issuer_category) <> '')         AS issuer_cat_filled,
  COUNT(DISTINCT industry_sector)                             AS distinct_sectors
FROM recent;

-- Block B: Top-50 valores de industry_sector
SELECT industry_sector, COUNT(*) AS n
FROM sec_nport_holdings
WHERE period_of_report >= (CURRENT_DATE - INTERVAL '15 months')
  AND industry_sector IS NOT NULL AND btrim(industry_sector) <> ''
GROUP BY 1 ORDER BY n DESC LIMIT 50;

-- Block C: Descoberta de colunas SIC/NAICS
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'sec_nport_holdings'
  AND (column_name ILIKE '%sic%' OR column_name ILIKE '%naics%'
       OR column_name ILIKE '%industry%' OR column_name ILIKE '%sector%');

-- Block D: se SIC existir (ajustar nome real pós-Block C)
-- SELECT COUNT(*), COUNT(*) FILTER (WHERE sic_code IS NULL) AS sic_null,
--        COUNT(*) FILTER (WHERE sic_code !~ '^[0-9]{3,4}$') AS sic_malformed,
--        COUNT(DISTINCT sic_code) AS distinct_sics
-- FROM sec_nport_holdings WHERE period_of_report >= (CURRENT_DATE - INTERVAL '15 months');
```

### 2.2 Árvore de decisão

| Cenário | Gatilho | Ação |
|---|---|---|
| A | `pct_null < 10%` | Usa `industry_sector` direto. **Skip 0133.** |
| B | `pct_null > 10%` + SIC preenchido > 90% | Commit 0133 com `sic_gics_mapping`. Enrich na matview. |
| C | Ambos > 10% null | Flag wealth-architect. Brinson degrada para `issuer_category × country`. `confidence='low'` em F2. |

### 2.3 Migration 0133 DDL (Cenário B)

```sql
CREATE TABLE sic_gics_mapping (
    sic_code             TEXT PRIMARY KEY,
    gics_sector          TEXT NOT NULL,
    gics_industry_group  TEXT,
    gics_industry        TEXT,
    gics_sub_industry    TEXT,
    source               TEXT NOT NULL DEFAULT 'MSCI_SP_2023',
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Sem RLS. Global. PK cobre único índice necessário.
```

Seed ~1200 linhas inline via `op.bulk_insert()` + validação `SELECT COUNT(*) = 1200` ao final. Fonte: MSCI/S&P public SIC→GICS 2023.

### 2.4 Aplicação do JOIN

**Decisão: LEFT JOIN no matview** (não runtime). Refresh semanal custa ~1-2s adicional; queries attribution ficam triviais. Regra de ouro Netz: pré-computa em worker, lê do DB.

---

## 3. Matview `mv_nport_sector_attribution`

### 3.1 DDL

```sql
CREATE MATERIALIZED VIEW mv_nport_sector_attribution AS
SELECT
    h.filer_cik,
    h.period_of_report,
    COALESCE(NULLIF(btrim(h.issuer_category), ''), 'Unknown')   AS issuer_category,
    COALESCE(
        NULLIF(btrim(h.industry_sector), ''),
        m.gics_sector,                   -- Cenário B fallback via SIC
        'Unclassified'
    )                                                            AS industry_sector,
    SUM(h.value_usd)                                             AS aum_usd,
    SUM(h.value_usd) / NULLIF(
        SUM(SUM(h.value_usd)) OVER (PARTITION BY h.filer_cik, h.period_of_report),
        0
    )                                                            AS weight,
    COUNT(*)                                                     AS holdings_count
FROM sec_nport_holdings h
LEFT JOIN sic_gics_mapping m ON m.sic_code = h.sic_code   -- condicional Cenário B
GROUP BY 1, 2, 3, 4;

CREATE UNIQUE INDEX ux_mv_nport_sector_attribution
    ON mv_nport_sector_attribution (filer_cik, period_of_report, issuer_category, industry_sector);

CREATE INDEX ix_mv_nport_sector_attribution_period
    ON mv_nport_sector_attribution (period_of_report DESC);
```

COALESCE garante não-NULL em todos os campos do UNIQUE (requisito PG). PG 16 `NULLS NOT DISTINCT` disponível mas COALESCE é mais explícito semanticamente ("Unclassified" é categoria legítima).

### 3.2 Refresh integration

**Hook: após commit do último batch, FORA do advisory lock 900_018** (nport_ingestion).

```python
# backend/app/core/jobs/nport_ingestion.py (pseudocódigo)
async with try_advisory_lock(900_018) as got:
    if not got: return
    await ingest_nport_batches(session)
    await session.commit()
# lock released

async with get_session() as refresh_session:
    await refresh_session.execute(text(
        "REFRESH MATERIALIZED VIEW CONCURRENTLY mv_nport_sector_attribution"
    ))
    await refresh_session.commit()
```

Razão: REFRESH CONCURRENTLY adquire EXCLUSIVE lock na matview (não na tabela base). Segurar 900_018 durante refresh bloqueia próximos ingestion runs desnecessariamente.

**Estimativa:** ~300-500k rows distintas; CONCURRENTLY refresh **30-90s** em PG 16 Timescale Cloud. Weekly, sem problema. 2x espaço disco temp durante refresh (desprezível).

---

## 4. Query Patterns

### 4.1 Fase 1 — Returns-Based (monthly alignment)

```sql
-- :fund_instrument_id (UUID), :etf_ticker_list (TEXT[]), :start_date, :end_date
WITH fund_monthly AS (
    SELECT time_bucket('1 month', ts) AS month,
           last(nav, ts) AS nav_eom
    FROM nav_timeseries
    WHERE instrument_id = :fund_instrument_id
      AND ts >= :start_date AND ts < :end_date
    GROUP BY 1
),
etf_monthly AS (
    SELECT time_bucket('1 month', ts) AS month, series_id,
           last(nav, ts) AS nav_eom
    FROM benchmark_nav
    WHERE ticker = ANY(:etf_ticker_list)
      AND ts >= :start_date AND ts < :end_date
    GROUP BY 1, series_id
)
SELECT f.month,
       f.nav_eom / lag(f.nav_eom) OVER (ORDER BY f.month) - 1 AS fund_ret,
       e.series_id,
       e.nav_eom / lag(e.nav_eom) OVER (PARTITION BY e.series_id ORDER BY e.month) - 1 AS etf_ret
FROM fund_monthly f
JOIN etf_monthly e ON e.month = f.month
ORDER BY f.month, e.series_id;
```

**Índices a verificar:** `nav_timeseries (instrument_id, ts DESC)`; `benchmark_nav (ticker, ts DESC)` ou `(series_id, ts DESC)`. Criar se faltarem.

**Performance target:** <500ms p95 para 1 fundo × 7 ETFs × 10 anos mensal.

### 4.2 Fase 2 — Holdings-Based

```sql
-- :filer_cik, :period_start, :period_end
SELECT period_of_report, issuer_category, industry_sector,
       aum_usd, weight, holdings_count
FROM mv_nport_sector_attribution
WHERE filer_cik = :filer_cik
  AND period_of_report BETWEEN :period_start AND :period_end
ORDER BY period_of_report, weight DESC;
```

Direto da matview — trivial em performance.

### 4.3 Fase 3 — Benchmark Proxy

```sql
-- :target_fund_cik
WITH target_benchmark AS (
    SELECT cik, primary_benchmark FROM sec_registered_funds WHERE cik = :target_fund_cik
),
resolved_proxy AS (
    SELECT tb.cik AS target_cik, tb.primary_benchmark AS benchmark_name,
           m.proxy_etf_ticker, m.proxy_etf_cik, m.proxy_etf_series_id, m.asset_class,
           CASE WHEN tb.primary_benchmark = ANY(m.benchmark_name_aliases) THEN 'exact'
                WHEN similarity(m.benchmark_name_canonical, tb.primary_benchmark) > 0.7 THEN 'fuzzy'
                ELSE 'class_fallback' END AS match_type
    FROM target_benchmark tb
    LEFT JOIN benchmark_etf_canonical_map m
        ON (tb.primary_benchmark = ANY(m.benchmark_name_aliases)
            OR similarity(m.benchmark_name_canonical, tb.primary_benchmark) > 0.7)
       AND CURRENT_DATE BETWEEN m.effective_from AND m.effective_to
    ORDER BY CASE WHEN tb.primary_benchmark = ANY(m.benchmark_name_aliases) THEN 0 ELSE 1 END,
             similarity(m.benchmark_name_canonical, tb.primary_benchmark) DESC
    LIMIT 1
)
SELECT h.*
FROM mv_nport_sector_attribution h
JOIN resolved_proxy rp ON h.filer_cik = rp.proxy_etf_cik
WHERE h.period_of_report = (
    SELECT MAX(period_of_report)
    FROM mv_nport_sector_attribution WHERE filer_cik = rp.proxy_etf_cik
);
```

**Edge cases:**
- `primary_benchmark IS NULL` → asset_class classifier Python
- Sem match canonical/fuzzy → asset_class default proxy (ex.: `equity_us_large` → SPY)
- Proxy sem N-PORT (BDC/MMF) → warning + fallback returns-based
- Múltiplos filings trimestre → MAX(period_of_report) + LIMIT 1

---

## 5. Migration 0134 — Tiingo Fundamentals (Lock 900_060)

### 5.1 Duas hypertables (não uma tabela normalizada)

```sql
-- Statements: esparso, trimestral, múltiplos line items por period
CREATE TABLE tiingo_fundamentals_statements (
    ticker          TEXT NOT NULL,
    period_end      DATE NOT NULL,
    statement_type  TEXT NOT NULL,      -- 'income','balance','cashflow','overview'
    line_item       TEXT NOT NULL,      -- e.g. 'netIncome','totalAssets'
    value           NUMERIC,
    currency        TEXT NOT NULL DEFAULT 'USD',
    filing_date     DATE NOT NULL,      -- restatement versioning
    PRIMARY KEY (ticker, period_end, statement_type, line_item, filing_date)
);
SELECT create_hypertable('tiingo_fundamentals_statements', 'period_end',
    chunk_time_interval => INTERVAL '1 year');
ALTER TABLE tiingo_fundamentals_statements SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'ticker'
);
SELECT add_compression_policy('tiingo_fundamentals_statements', INTERVAL '2 years');

-- Daily: denso, 1 row/ticker/day
CREATE TABLE tiingo_fundamentals_daily (
    ticker           TEXT NOT NULL,
    as_of            DATE NOT NULL,
    market_cap       NUMERIC,
    pe_ratio         NUMERIC,
    pb_ratio         NUMERIC,
    enterprise_value NUMERIC,
    dividend_yield   NUMERIC,
    PRIMARY KEY (ticker, as_of)
);
SELECT create_hypertable('tiingo_fundamentals_daily', 'as_of',
    chunk_time_interval => INTERVAL '1 year');
ALTER TABLE tiingo_fundamentals_daily SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'ticker'
);
```

Ambas globais, sem RLS.

### 5.2 Worker `tiingo_fundamentals_ingestion`

- **Lock ID:** 900_060 (user decision)
- **Cadência:** daily 04:00 UTC (after `nport_ingestion` 03:00 UTC for matview ordering)
- **Gate:** `ExternalProviderGate.bulk` (5min timeout) — same pattern as `sec_13f_ingestion` (900_021), `nport_ingestion` (900_018)
- **Endpoints:**
  - `/tiingo/fundamentals/{ticker}/statements` — quarterly
  - `/tiingo/fundamentals/{ticker}/daily` — daily metrics
- **Idempotência:** upsert `ON CONFLICT (ticker, period_end, statement_type, line_item, filing_date) DO UPDATE` (statements); `(ticker, as_of) DO UPDATE` (daily)
- **Restatements:** PK inclui `filing_date`; views usam `DISTINCT ON (ticker, period_end, line_item) ... ORDER BY ... filing_date DESC`
- **Rate limit:** `asyncio.Semaphore` + exponential backoff (replicar shape `live_price_poll` 900_100)
- **Dual-write:** statements raw em StorageClient `silver/_global/tiingo/statements/` ANTES do upsert hypertable

### 5.3 Universe seed

Top 500 US equities matching `instruments_universe` equity tickers (size-ranked). Backfill one-shot: 500 × 60 trimestres × ~80 line items = ~2.4M rows + ~20% restatements = ~2.9M rows. Daily: 500 × 252 × 15 = 1.9M rows.

**Storage total:** ~250-280 MB compressed. Desprezível.

---

## 6. Migration 0135 — `equity_characteristics_monthly`

### 6.1 DDL

```sql
CREATE TABLE equity_characteristics_monthly (
    instrument_id       UUID NOT NULL,
    ticker              TEXT NOT NULL,
    as_of               DATE NOT NULL,
    size_log_mkt_cap    NUMERIC(10,4),
    book_to_market      NUMERIC(10,4),
    mom_12_1            NUMERIC(10,4),
    quality_roa         NUMERIC(10,4),
    investment_growth   NUMERIC(10,4),
    profitability_gross NUMERIC(10,4),
    source_filing_date  DATE,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, as_of)
);
SELECT create_hypertable('equity_characteristics_monthly', 'as_of',
    chunk_time_interval => INTERVAL '1 year');
ALTER TABLE equity_characteristics_monthly SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'instrument_id'
);
```

Global, sem RLS.

### 6.2 Derivação (matview ou worker write)

- **size_log_mkt_cap** ← `LN(tiingo_fundamentals_daily.market_cap)` last-day-of-month
- **book_to_market** ← `totalEquity / market_cap` (statements balance latest-as-of-month)
- **mom_12_1** ← `nav_timeseries` rolling return 12m ex-last-month
- **quality_roa** ← TTM `netIncome / totalAssets` (statements income + balance)
- **investment_growth** ← `totalAssets(t) / totalAssets(t-12m) - 1`
- **profitability_gross** ← `grossProfit / revenue` or fallback `(revenue - costOfRevenue) / revenue`

**Implementation:** worker write (não matview) para transparency de `source_filing_date`. Worker roda após `tiingo_fundamentals_ingestion`. Matview alternativa se perf perm — benchmark ambos no PR-Q8.

### 6.3 Silver parquet

`silver/_global/equity_characteristics/{as_of}/chars.parquet` para DuckDB analytics (Fama-MacBeth cross-sectional regressions fora do hot path).

---

## 7. Índices e Performance

### Já cobertos
- `benchmark_etf_canonical_map`: 4 índices (§1.2)
- `mv_nport_sector_attribution`: UNIQUE (filer_cik, period, issuer_cat, sector) + (period DESC)
- Tiingo tables: PKs já cobrem queries canônicas

### A verificar no repo atual (task para engineer)
1. `nav_timeseries (instrument_id, ts DESC)` — criar se faltar
2. `benchmark_nav (ticker, ts DESC)` ou `(series_id, ts DESC)` — verificar
3. `sec_nport_holdings`: compress segmentby `filer_cik` + orderby `period_of_report DESC`; policy 6 meses
4. `sec_registered_funds.primary_benchmark`: não precisa índice (query filtra por `cik` primeiro)

---

## 8. Coverage Audit

```sql
CREATE TABLE attribution_coverage_audit (
    run_id                  BIGSERIAL PRIMARY KEY,
    run_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    total_funds             INT NOT NULL,
    matched_exact           INT NOT NULL,
    matched_fuzzy           INT NOT NULL,
    matched_class           INT NOT NULL,
    unmatched               INT NOT NULL,
    unmatched_top_strings   JSONB
);
```

Target coverage: ≥70% exact+fuzzy após seed inicial. <70% → backlog de aliases manuais.

---

## 9. Worker Dependencies Summary

| Worker | Lock | Cadência | Hypertables |
|---|---|---|---|
| `nport_ingestion` (existente) | 900_018 | Weekly | `sec_nport_holdings` + refresh matview |
| `tiingo_fundamentals_ingestion` (NOVO) | **900_060** | Daily 04:00 UTC | `tiingo_fundamentals_statements`, `tiingo_fundamentals_daily` |
| `equity_characteristics_compute` (NOVO) | 900_091 | Daily após Tiingo | `equity_characteristics_monthly` |
| `ipca_estimation` (NOVO, S5) | 900_092 | Quarterly | writes to `factor_model_fits` |

---

## 10. Não-Metas (DB)

- RLS policies existentes: inalteradas
- `fund_risk_metrics` schema: only adds `sharpe_cf*`, `cvar_99_evt`, `cvar_999_evt` nullable cols
- G6 copula / G7 entropy: fora
- Climate/ESG tables: fora
- Bloomberg API/SDK: fora (G3 F3 dispensa)
- 10-K XBRL full ingestion além do que Tiingo expõe: fora
