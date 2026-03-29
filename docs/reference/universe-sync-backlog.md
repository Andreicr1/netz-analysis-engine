# Universe Sync Backlog — `universe_sync` Worker

**Data:** 2026-03-29
**Status:** Pendente — executar após validação da migration 0069 (global instruments)
**Contexto:** Migration 0069 globalizou `instruments_universe` e criou `instruments_org`. O catálogo hoje tem apenas 17 instrumentos. Este worker popula o catálogo global a partir das fontes SEC/ESMA já enriquecidas.

---

## Problema

`instruments_universe` é um catálogo global, mas não tem alimentação automática a partir das tabelas SEC/ESMA. Os 17 instrumentos atuais chegaram via seed manual. O sistema tem 3.8M de rows de dados institucionais e nenhum worker que faça a ponte para o catálogo investível.

---

## Números reais (verificados via tiger db, 2026-03-29)

### Situação atual do `instruments_universe`
| Campo | Valor |
|---|---|
| Total de instrumentos | 17 |
| Tipo único | `fund` |

### pgvector `wealth_vector_chunks` — granularidade real por fonte

| source_type | entity_id | Entidades únicas | Com embedding | Ticker disponível |
|---|---|---|---|---|
| `sec_fund_series_profile` | `series_id` (ex: S000000008) | 13.229 | 13.229 | 170 séries (via sec_fund_classes, classe canônica) |
| `esma_fund_profile` | `ISIN` | 10.436 | 10.436 | 2.929 (via esma_funds.yahoo_ticker) |
| `sec_manager_profile` | `CRD` | 5.680 | 5.680 | — |
| `sec_fund_profile` | `CIK` | 4.690 | 4.690 | legado — CIK-level, menos granular que series |
| `sec_etf_profile` | `series_id` | 985 | 985 | 925 |
| `sec_bdc_profile` | `CIK` | 196 | 196 | 0 (precisa resolução) |
| `sec_mmf_profile` | `series_id` | 373 | 373 | 0 (não negociados em Yahoo) |

### Tickers Yahoo disponíveis por fonte (imediato)

| Fonte | Tabela | Granularidade | Tickers disponíveis | Método |
|---|---|---|---|---|
| ETFs SEC | `sec_etfs` | series_id | **925** | `ticker` direto |
| Mutual Funds (série canônica) | `sec_fund_classes` | series_id | **170** | `DISTINCT ON (series_id) ORDER BY expense_ratio_pct ASC` |
| ESMA UCITS | `esma_funds` | ISIN | **2.929** | `yahoo_ticker` resolvido |
| BDCs SEC | `sec_bdcs` | CIK | **0** | Precisa resolução por nome |
| **Total imediato** | | | **~4.024** | |

### Potencial futuro (quando ticker resolution expandir)

| Fonte | Séries sem ticker | Potencial |
|---|---|---|
| `sec_fund_series_profile` | 13.059 séries | Alto — quando sec_fund_classes ganhar mais tickers via OpenFIGI ou N-PORT |
| `sec_bdcs` | 196 BDCs | Médio — Yahoo search por nome |

---

## Princípio de design crítico — série como unidade investível

Um mutual fund tem 1 série e N share classes (ex: Vanguard Total Stock Market = série S000002439 com classes Admiral, Institutional, ETF, Investor). O NAV é idêntico entre classes. A unidade investível no catálogo é a **série**, não a classe.

`instruments_universe` deve ter **uma entrada por série**, com:
- `isin` = `series_id` (identificador canônico SEC) ou ISIN real (ESMA)
- `ticker` = ticker da share class canônica (menor `expense_ratio_pct` com ticker disponível)
- `attributes.canonical_class` = nome da classe selecionada
- `attributes.expense_ratio_pct` = ER da classe canônica
- `attributes.series_id` = series_id SEC (para lookup reverso)

Isso é o mesmo que o pgvector já faz: `sec_fund_series_profile` tem `entity_id = series_id`, uma entrada por série.

---

## Arquitetura do worker `universe_sync`

**Scope:** global  
**Lock ID:** 900_070 (próximo disponível)  
**Frequência:** semanal (junto com `sec_bulk_ingestion`)  
**Tabela alvo:** `instruments_universe` (upsert, sem RLS)  
**Tabelas de origem:** `sec_etfs`, `sec_fund_classes`, `sec_bdcs`, `esma_funds`, `esma_isin_ticker_map`

### Fase 1 — ETFs SEC (925 instrumentos imediatos)

```sql
-- Fonte: sec_etfs WHERE ticker IS NOT NULL
INSERT INTO instruments_universe (
    instrument_id, instrument_type, name, isin, ticker,
    asset_class, geography, currency, is_active, attributes
)
SELECT
    gen_random_uuid(),
    'fund',
    e.fund_name,
    e.series_id,          -- series_id como isin (identificador canônico)
    e.ticker,
    COALESCE(e.strategy_label, 'equity'),  -- inferir asset_class do strategy_label
    'United States',
    'USD',
    true,
    jsonb_build_object(
        'series_id', e.series_id,
        'sec_cik', e.cik,
        'fund_subtype', 'etf',
        'strategy_label', e.strategy_label,
        'is_index', e.is_index,
        'expense_ratio_pct', e.net_operating_expenses,
        'tracking_difference_net', e.tracking_difference_net,
        'aum_usd', e.monthly_avg_net_assets
    )
FROM sec_etfs e
WHERE e.ticker IS NOT NULL
ON CONFLICT (ticker) DO UPDATE SET
    name = EXCLUDED.name,
    attributes = EXCLUDED.attributes,
    updated_at = now()
```

### Fase 2 — Mutual Fund Series com classe canônica (170 imediatos)

Lógica de seleção da classe canônica: dentro de cada `series_id`, selecionar a share class com menor `expense_ratio_pct` que tenha ticker. Isso privilegia classes institucionais (menor custo, maior AUM típico).

```sql
-- Fonte: sec_fund_classes, DISTINCT ON (series_id) ORDER BY expense_ratio_pct ASC
WITH canonical AS (
    SELECT DISTINCT ON (fc.series_id)
        fc.series_id,
        fc.series_name,
        fc.ticker,
        fc.class_name AS canonical_class,
        fc.expense_ratio_pct,
        fc.net_assets,
        rf.strategy_label,
        rf.fund_type
    FROM sec_fund_classes fc
    LEFT JOIN sec_registered_funds rf ON rf.cik = fc.cik
    WHERE fc.ticker IS NOT NULL
      AND EXISTS (
          SELECT 1 FROM wealth_vector_chunks wvc
          WHERE wvc.entity_id = fc.series_id
            AND wvc.source_type = 'sec_fund_series_profile'
      )
    ORDER BY fc.series_id, fc.expense_ratio_pct ASC NULLS LAST
)
INSERT INTO instruments_universe (
    instrument_id, instrument_type, name, isin, ticker,
    asset_class, geography, currency, is_active, attributes
)
SELECT
    gen_random_uuid(),
    'fund',
    c.series_name,
    c.series_id,          -- series_id como isin
    c.ticker,
    -- asset_class inferido do strategy_label
    CASE
        WHEN c.strategy_label ILIKE '%bond%' OR c.strategy_label ILIKE '%fixed%' OR c.strategy_label ILIKE '%muni%' THEN 'fixed_income'
        WHEN c.strategy_label ILIKE '%money market%' THEN 'cash'
        ELSE 'equity'
    END,
    'United States',
    'USD',
    true,
    jsonb_build_object(
        'series_id', c.series_id,
        'fund_subtype', c.fund_type,
        'strategy_label', c.strategy_label,
        'canonical_class', c.canonical_class,
        'expense_ratio_pct', c.expense_ratio_pct,
        'aum_usd', c.net_assets
    )
FROM canonical c
ON CONFLICT (ticker) DO UPDATE SET
    name = EXCLUDED.name,
    attributes = EXCLUDED.attributes,
    updated_at = now()
```

### Fase 3 — ESMA UCITS (2.929 imediatos)

```sql
-- Fonte: esma_funds WHERE yahoo_ticker IS NOT NULL
INSERT INTO instruments_universe (
    instrument_id, instrument_type, name, isin, ticker,
    asset_class, geography, currency, is_active, attributes
)
SELECT
    gen_random_uuid(),
    'fund',
    ef.fund_name,
    ef.isin,              -- ISIN real (não series_id)
    ef.yahoo_ticker,
    CASE
        WHEN ef.strategy_label ILIKE '%bond%' OR ef.strategy_label ILIKE '%fixed%' THEN 'fixed_income'
        WHEN ef.strategy_label ILIKE '%money market%' THEN 'cash'
        ELSE 'equity'
    END,
    ef.domicile,
    'EUR',                -- maioria UCITS é EUR
    true,
    jsonb_build_object(
        'isin', ef.isin,
        'fund_subtype', 'ucits',
        'strategy_label', ef.strategy_label,
        'domicile', ef.domicile,
        'esma_manager_id', ef.esma_manager_id
    )
FROM esma_funds ef
WHERE ef.yahoo_ticker IS NOT NULL
ON CONFLICT (ticker) DO UPDATE SET
    name = EXCLUDED.name,
    attributes = EXCLUDED.attributes,
    updated_at = now()
```

### Fase 4 — BDCs (deferred — ticker resolution pendente)

`sec_bdcs` tem 196 BDCs, 0 tickers. BDCs são negociados como equity — têm ticker real mas não está na tabela.

**Opções de resolução:**
1. Cruzar `sec_bdcs.fund_name` com OpenFIGI name search
2. Cruzar `sec_bdcs.cik` com `sec_cusip_ticker_map` via EDGAR XBRL

Estimativa: ~150 dos 196 BDCs têm ticker Yahoo resolvível. Deferred para sprint separado.

---

## `instruments_universe`: constraint de unicidade

O `ON CONFLICT (ticker)` requer que `ticker` tenha UNIQUE constraint. Verificar se existe antes de rodar o worker:

```sql
SELECT indexname FROM pg_indexes
WHERE tablename = 'instruments_universe' AND indexdef ILIKE '%ticker%';
```

Se não existir, migration prévia adiciona:
```sql
CREATE UNIQUE INDEX IF NOT EXISTS uix_instruments_universe_ticker
ON instruments_universe (ticker)
WHERE ticker IS NOT NULL;
```

Para `isin` (series_id/ISIN), também conveniente ter unique index:
```sql
CREATE UNIQUE INDEX IF NOT EXISTS uix_instruments_universe_isin
ON instruments_universe (isin)
WHERE isin IS NOT NULL;
```

---

## `instrument_ingestion` pós-sync

Após o `universe_sync` popular o catálogo com ~4.024 instrumentos:

| Métrica | Antes | Depois |
|---|---|---|
| Instrumentos no catálogo | 17 | ~4.024 |
| Yahoo tickers a buscar | 17 | ~4.024 |
| Chunks `yf.download()` (batch 500) | 1 | ~9 (+2s sleep cada) |
| Tempo estimado do job NAV (10y backfill) | ~1–3 min | ~20–40 min |
| Rows em `nav_timeseries` (10y × ~2.520 pregões) | ~42.840 | ~10.1M |

O `yf.download(threads=True)` mantém eficiência em batch — não é 4.024 requests individuais, são ~9 downloads em lote.

---

## Sequência de execução

1. Verificar/criar UNIQUE indexes em `instruments_universe (ticker)` e `instruments_universe (isin)`
2. Rodar `universe_sync` (Fase 1 ? 2 ? 3, Fase 4 deferred)
3. Validar: `SELECT COUNT(*), instrument_type FROM instruments_universe GROUP BY instrument_type`
4. Rodar `instrument_ingestion(lookback_days=3650)` — backfill 10 anos
5. Validar: `SELECT COUNT(*), COUNT(DISTINCT instrument_id) FROM nav_timeseries`
6. Rodar `risk_calc` para o tenant demo (wmf-corp) — validar `fund_risk_metrics`

---

## Definition of Done

- [ ] `universe_sync` worker criado em `backend/app/domains/wealth/workers/universe_sync.py`
- [ ] Lock ID 900_070, scope global, sem `set_rls_context`
- [ ] Registrado no dispatcher com frequência semanal
- [ ] Fase 1 (ETFs): 925 instrumentos inseridos
- [ ] Fase 2 (Mutual Funds série canônica): 170 instrumentos inseridos
- [ ] Fase 3 (ESMA): 2.929 instrumentos inseridos
- [ ] UNIQUE index em `instruments_universe(ticker)` criado
- [ ] `instrument_ingestion` rodado com lookback_days=3650 — sem erros
- [ ] `nav_timeseries` com >5M rows após backfill
- [ ] `make check` passa (zero regressões)

---

## O que NÃO fazer

- Não usar `wealth_vector_chunks` como fonte de dados para o worker — ler das tabelas SEC/ESMA diretamente
- Não criar uma entrada por share class — granularidade é a série
- Não inserir MMFs em `instruments_universe` — não são negociados via Yahoo Finance
- Não bloquear `sec_fund_profile` (CIK-level, legado) — `sec_fund_series_profile` é o nível correto
- Não usar `organization_id` em nenhuma query — tabelas globais
