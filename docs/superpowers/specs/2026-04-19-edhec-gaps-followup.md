---
title: EDHEC Quant Gap Closure — Follow-up Decisions + Final Plan
date: 2026-04-19
authors: wealth-architect + wealth-portfolio-quant-architect + financial-timeseries-db-architect (round 2)
status: approved — Cenário X3 final
---

# Follow-up Decisions + Final Plan (Cenário X3)

Consolidates round-2 specialist analysis (S1 collision check, GICS diagnostic SQL, matview details, Tiingo Fundamentals rescoping) and captures user decisions.

---

## 1. User Decisions (Andrei, 2026-04-19)

| Pendência | Decisão |
|---|---|
| GICS diagnostic antes de 0133 | Aprovado. **Buffer 3-4 dias em S2** para contingência. 0133 só se Cenário B. |
| G5 Option A vs B | **Option A direto** (6 chars via Tiingo). Skip staged Option B sanity. |
| Matview refresh no `nport_ingestion` | Aprovado. UNIQUE INDEX obrigatório. REFRESH CONCURRENTLY FORA do advisory lock. |
| Lock ID Tiingo worker | **900_060**. |
| Staged validation G5 | Skip (bkelly-lab/ipca ALS já validado em paper). |
| Tiingo ToS | Power tier cobre dev; Enterprise será contratado ao virar SaaS. |
| X3 vs Y | **X3 approved** — Tiingo paralelo com S3-S4, G5 vira prod direto. |
| Commit target | **main** (não branch atual `feat/terminal-v1-bundle-parity`). |

---

## 2. S1 Collision Analysis — CLEAN

Três PRs paralelos em S1 em superfícies disjuntas:

| PR | Files modified | Files new |
|---|---|---|
| PR-Q1 (G1) | `quant_engine/scoring_service.py`, `backend/app/domains/wealth/workers/global_risk_metrics.py`, `calibration/wealth_scoring.yaml` | `quant_engine/scoring_components/robust_sharpe.py`, `backend/alembic/versions/0132_add_sharpe_cf.py` (renumerar se 0132 ocupada por canonical_map), `backend/tests/quant_engine/test_scoring_robust.py` |
| PR-Q2 (G2) | (nenhum — `factor_model_service.py` não tocado; factor_cov derivado internamente) | `quant_engine/diversification_service.py`, `backend/tests/quant_engine/test_diversification.py` |
| PR-Q3 (G3-F1) | (nenhum em `quant_engine/`) | `vertical_engines/wealth/attribution/{__init__.py,service.py,returns_based.py,models.py}`, `backend/tests/vertical_engines/wealth/test_attribution_returns.py` |

**Merge order recomendada:** Q3 → Q2 → Q1 (Q1 último porque muda scoring behavior com flag default OFF).

**Nota importante sobre numeração de migrations:** G1 adiciona cols em `fund_risk_metrics`. Se PR-Q5 (canonical_map) merger primeiro, G1 é 0133; se G1 merger primeiro, canonical_map vira 0133. **Resolver via rebase antes do merge final** — Alembic não tolera collision em revision numbers.

---

## 3. G1 Feature Flag Design (definitivo)

- **ConfigService key:** `wealth.scoring.use_robust_sharpe` (bool, default `false`)
- **Storage:** `vertical_config_defaults` seed via `calibration/wealth_scoring.yaml`
- **Resolution:** `ScoringConfig.use_robust_sharpe: bool` resolvido no async entry point (route handler OU worker), passado stateless para `scoring_service.score_fund(config=...)`
- **Flag OFF (default merge):** `risk_adjusted_return` reads `fund_risk_metrics.sharpe_ratio` — bit-for-bit idêntico ao pré-PR
- **Flag ON:** reads `fund_risk_metrics.sharpe_cf`; fallback `sharpe_ratio` com `logger.warning` se NULL
- **Worker path:** `global_risk_metrics` (lock 900_071) popula `sharpe_cf` SEMPRE (independente da flag)

### 3.1 Backfill sequence (critical ordering)

1. Merge PR-Q1 com flag OFF
2. Migration adiciona 5 cols em `fund_risk_metrics`
3. `global_risk_metrics` worker full-backfill job (1-2h, ~10k instrumentos)
4. Validar: `SELECT COUNT(*) FROM fund_risk_metrics WHERE sharpe_cf IS NULL AND status='active'` = 0
5. Flip flag `use_robust_sharpe=true` em **staging** primeiro
6. Smoke test DD ch.5 renders + scoring rankings stable
7. Flip flag em **prod**

### 3.2 Rollback

`ConfigService.set('wealth.scoring.use_robust_sharpe', False)` reverte em <1min. Zero schema rollback necessário (cols adicionadas permanecem, apenas deixam de ser lidas).

---

## 4. G2 Non-Conflict with G1

`factor_model_service.decompose_portfolio()` hoje retorna:
- `loadings` (N×K)
- `factor_returns` (T×K)
- `idiosyncratic_var`

Covariância derivada ex-post via `np.cov(factor_returns.T)`. **G2 não modifica `factor_model_service.py`.** Derivação interna em `diversification_service.meucci_decomposition()`. Zero conflito com PR-Q1.

Se futuramente quiser expor `get_factor_covariance()` publicamente, fazer em PR separado pós-S1.

---

## 5. GICS Diagnostic Protocol (S2)

### 5.1 Execution

Script `backend/scripts/diagnose_nport_gics.py` (read-only contra Timescale Cloud prod) roda os 4 blocks de SQL (Block A cobertura, Block B top-50, Block C column discovery, Block D SIC distribution). Resultado entregue como JSON artifact + human-readable summary.

### 5.2 Decision tree

| Cenário | Ação |
|---|---|
| A (`pct_null < 10%`) | Skip 0133. F2 uses `industry_sector` direct. |
| B (`pct_null > 10%` + SIC preenchido >90%) | Commit `0133_sic_gics_mapping.py` + seed 1200 rows. F2 JOIN via matview. |
| C (ambos >10% null) | Abort 0133. Replan F2: Brinson degrada para `issuer_category × country`. Flag `confidence='low'` em saída F2. wealth-architect replan triggered. |

### 5.3 Buffer absorvido

3-4 dias S2 cobrem: (a) rodar diagnóstico, (b) decidir cenário, (c) (se B) seed SIC→GICS inline, (d) (se C) replan F2.

---

## 6. Matview Refresh — Final Decision

### 6.1 DDL final

```sql
CREATE MATERIALIZED VIEW mv_nport_sector_attribution AS
SELECT
    h.filer_cik,
    h.period_of_report,
    COALESCE(NULLIF(btrim(h.issuer_category), ''), 'Unknown')   AS issuer_category,
    COALESCE(
        NULLIF(btrim(h.industry_sector), ''),
        m.gics_sector,
        'Unclassified'
    )                                                            AS industry_sector,
    SUM(h.value_usd)                                             AS aum_usd,
    SUM(h.value_usd) / NULLIF(
        SUM(SUM(h.value_usd)) OVER (PARTITION BY h.filer_cik, h.period_of_report),
        0
    )                                                            AS weight,
    COUNT(*)                                                     AS holdings_count
FROM sec_nport_holdings h
LEFT JOIN sic_gics_mapping m ON m.sic_code = h.sic_code
GROUP BY 1, 2, 3, 4;

CREATE UNIQUE INDEX ux_mv_nport_sector_attribution
    ON mv_nport_sector_attribution (filer_cik, period_of_report, issuer_category, industry_sector);
```

COALESCE garante NOT NULL em todos os campos UNIQUE → REFRESH CONCURRENTLY válido.

### 6.2 Refresh hook

**FORA do advisory lock 900_018** (nport_ingestion). Sessão SQL separada, sem lock extra. Razão: REFRESH CONCURRENTLY custa 30-90s; segurar 900_018 bloqueia próximos ingestion runs desnecessariamente.

---

## 7. Tiingo Fundamentals — Final Design

### 7.1 Coverage confirmed

Tiingo Power tier cobre os 6 chars Kelly-Pruitt-Su:

| Char | Fonte Tiingo |
|---|---|
| Size | `/daily.marketCap` direto |
| Book-to-market | `totalEquity / marketCap` |
| Momentum 12-1 | `nav_timeseries` (independente) |
| Quality ROA | `netIncome / totalAssets` |
| Investment growth | `totalAssets` YoY |
| Profitability gross | `grossProfit / revenue` (fallback `revenue - costOfRevenue`) |

### 7.2 Worker spec

- **Name:** `tiingo_fundamentals_ingestion`
- **Lock:** 900_060
- **Cadência:** daily 04:00 UTC (após nport 03:00 UTC)
- **Gate:** `ExternalProviderGate.bulk` (5min)
- **Rate limit:** asyncio.Semaphore, exponential backoff, 10k req/h Power tier
- **Idempotência:** upsert ON CONFLICT (PKs incluem filing_date para restatements)
- **Dual-write:** StorageClient silver parquet → hypertable upsert

### 7.3 Cost / ToS

- **Tier:** Power $50/mo (Andrei's personal account)
- **Usage:** 500 tickers × weekly statements = ~2k req/week; daily metrics backfill = ~125k req one-shot
- **Enterprise upgrade:** deferred until SaaS stage

### 7.4 Universe seed

Top 500 US equities ranked by mkt cap em `instruments_universe` where `asset_class IN ('equity_us_large', 'equity_us_mid', 'equity_us_small')`. Query de seed em `scripts/seed_tiingo_universe.py`.

---

## 8. Final Timeline X3 (9 semanas)

```
Week 1-2 (S1) — Quant reviewer track
   PR-Q1  feat/quant-g1-robust-sharpe
   PR-Q2  feat/quant-g2-enb-meucci
   PR-Q3  feat/wealth-g3-returns-based

Week 3-5 (S2) — Quant reviewer track
   GICS diagnostic (day 1-2 S2)
   PR-Q4  feat/wealth-g3-holdings-based (+0133 conditional)
   Buffer 3-4 days

Week 6 (S3) — Quant track + Data track parallel
   Quant: PR-Q5  feat/wealth-g3-benchmark-proxy (+ 0132)
   Data:  PR-Q7  feat/tiingo-fundamentals-worker (+ 0134)

Week 7 (S4) — Quant track + Data track parallel
   Quant: PR-Q6  feat/quant-g4-evt-gpd
   Data:  PR-Q8  feat/equity-characteristics-matview (+ 0135)

Week 8 (S5) — Quant reviewer track
   PR-Q9  feat/quant-g5-ipca-prod (4th attribution rail)

Week 9 (S6-S8 compressed) — Hardening
   DD ch.4 cascade wiring end-to-end (all 4 rails)
   Agent-native Fund Copilot IPCA queries
   E2E + prod rollout + smoke
```

---

## 9. PR Dependencies

```
PR-Q1 ──── independent
PR-Q2 ──── independent
PR-Q3 ──── independent
  │
  └─► PR-Q4 ──► PR-Q5
                │
PR-Q7 ──► PR-Q8 ┴──► PR-Q9 ──► ch.4 4th rail
PR-Q6 ──── independent
```

---

## 10. Open Items Deferred to Future Sprints

- **Fuzzy match via pg_trgm threshold tuning** — if `benchmark_etf_canonical_map` coverage audit shows <70% → backlog aliases manuais
- **Fama-French 5 + Carhart** as explicit factor model alternative — not IPCA replacement but complement
- **ADV positions / private fund characteristics** ingestion — fora deste sprint
- **G6 copulas, G7 entropy pooling** — deferred indefinitely
- **Cross-asset Brinson (equity + FI one report)** — single-asset-class per chapter for now
