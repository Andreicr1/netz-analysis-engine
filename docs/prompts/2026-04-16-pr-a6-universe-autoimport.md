# PR-A6 — Universe Auto-Import + Cleanup

- **Data**: 2026-04-16
- **Executor**: Opus 4.6 (1M) em sessão paralela
- **Branch**: `feat/pr-a6-universe-autoimport`
- **Base**: `main` HEAD após merge de PR-A5 (commit `bfc5242e`)
- **Scope**: Resolver o gap arquitetural entre o catálogo institucional sanitizado (`instruments_universe` + `is_institutional = true`, ~5k ativos qualificados) e o universe org-scoped (`instruments_org`) que alimenta o Builder/Optimizer. Auto-import bulk + cleanup determinístico do estado órfão herdado de seeds antigos.
- **Specialists paralelos (coordenar, não duplicar)**:
  - `financial-timeseries-db-architect` → Section B-alt (SQL exato do worker, índices concorrentes, migration safety, backup/restore, lock contention, vacuum/analyze pós-UPSERT)
  - `wealth-portfolio-quant-architect` → Section H-alt (comportamento do optimizer com ~5k candidates, pre-filtros por mandate_fit antes do SOCP, cardinalidade CLARABEL, tempo de cascata Phase 1 → 1.5 → 2 → 3)

---

## ERRATA — Real Data Corrections (2026-04-16, post-worker-run)

> **READ THIS FIRST.** The sections below were written by specialist agents before the worker population run. Multiple assumptions were wrong. This errata overrides any conflicting claim in the original spec. When in doubt, trust errata.

### Schema corrections

1. **`instruments_universe.instrument_type`** = `'fund'` for 9,007 of 9,008 institutional rows. It is NOT `registered_us`/`etf`/`ucits_eu`/`money_market`. The SEC universe classification lives in **`attributes->>'sec_universe'`** with values: `registered_us` (5,109), `etf` (911), `bdc` (48), `NULL` (2,940 — mostly ESMA/private).
2. **`fund_inception_date` does NOT exist** as a column on `instruments_universe`. The 5Y track-record filter must use an alternative source: `nav_timeseries` coverage (COUNT of trading days per instrument_id) or LATERAL join to source tables (`sec_registered_funds.fund_inception_date`, `sec_etfs` attributes, `esma_funds.first_offer_date`). **Recommended:** use `nav_timeseries` coverage >= 1,260 trading days (~5Y) as the universal proxy — it works cross-universe and is already populated by `instrument_ingestion`.
3. **`mv_unified_funds.inception_date`** is NULL for ALL 23,368 registered_us rows with AUM >= $200M. Do NOT use this column for track-record filtering. Use `nav_timeseries` coverage instead.
4. **`allocation_blocks`** has `display_name` (not `label`). The 22 active block_ids are: `alt_commodities`, `alt_gold`, `alt_real_estate`, `cash`, `dm_asia_equity`, `dm_europe_equity`, `em_equity`, `fi_aggregate`, `fi_em_debt`, `fi_govt`, `fi_high_yield`, `fi_ig_corporate`, `fi_short_term`, `fi_tips`, `fi_us_aggregate`, `fi_us_high_yield`, `fi_us_tips`, `fi_us_treasury`, `na_equity_growth`, `na_equity_large`, `na_equity_small`, `na_equity_value`.
5. **`instruments_org`** currently has **169 rows** (155 with block_id, 156 approved, 13 pending). This is the stale seed data to be cleaned.

### Cardinality corrections

| Metric | Spec assumption | Actual value |
|---|---|---|
| Institutional funds (instruments_universe) | ~5k | **9,008** |
| AUM >= $200M (mv_unified_funds) | ~5k liquid | **42,318 total** (23,368 registered_us + 18,950 private_us) |
| Liquid AUM >= $200M (registered_us only) | ~5k | **23,368** (BUT inception=NULL, cannot filter 5Y via MV) |
| ETF rows in mv_unified_funds | expected thousands | **0** (ETFs not appearing as separate universe; may be subsumed in registered_us) |
| UCITS in mv_unified_funds | expected thousands | **2,929** (but AUM < $200M threshold for most) |
| strategy_label coverage (registered_us AUM>=200M) | assumed high | **4,803/23,368 (20.5%)** — most unlabeled |
| instruments_org seeds | ~50-200 | **169** |

### Asset class distribution (institutional instruments_universe)

| asset_class | count |
|---|---|
| equity | 6,468 |
| fixed_income | 2,041 |
| cash | 272 |
| alternatives | 224 |
| fund | 3 |

### Block classification mapping (corrected)

The spec assumed 3 buckets (EQUITY/FI/ALT). Reality: 22 granular blocks. The `block_classification` table must map `(sec_universe, asset_class, strategy_label)` → one of the 22 block_ids. Strategy_label is the most granular classifier (37→47 labels post-reclassification). Use `STRATEGY_LABEL_TO_BLOCKS` in `backend/vertical_engines/wealth/model_portfolio/block_mapping.py` as the canonical source. Fallback chain: `strategy_label` → `asset_class` → `geography` → skip (no block assigned, worker logs warning, row NOT imported).

### Auto-import candidate estimate (corrected)

With the NAV coverage filter (>= 1,260 trading days) replacing inception_date, and AUM >= $200M, the actual candidate count will be LOWER than 23,368 because:
- Many registered_us funds have < 5Y NAV history in `nav_timeseries`
- strategy_label is NULL for ~80% → block_classification fallback to asset_class+geography
- Some may not have `is_institutional = true` in `instruments_universe` despite being in `mv_unified_funds`

**Estimated final auto-import count: 3,000-7,000 per org** (validated after worker runs). The pre-filter cascade (Layer 0-3 from quant-architect) then reduces to ~200-400 for CLARABEL.

### Worker execution evidence (2026-04-16)

All workers ran successfully. Key results for PR-A6 planning:
- `global_risk_metrics`: 5,446 instruments scored, 5,042 with DTW (92.6%), 4,472 with 5Y return (82.1%)
- Regime: RISK_OFF (stress 36.1/100)
- Classification: P0+P1+P2 applied (2,806 updates), P3 = 0 rows

---

## Why this PR exists

O Playwright run no final do PR-A5 confirmou o sintoma: o portfolio de teste executou a cascata do optimizer contra um `instruments_org` herdado de seeds antigos (~50-200 rows, aprovações `"pending"` misturadas com `"approved"` pré-mandate). A build não retornou `success` — não por bug do optimizer, mas porque o **substrato de candidates está corrupto**: mistura de vehicles retail (excluídos pelo `universe_sanitization`), ativos sem `block_id`, e privates que não deveriam estar auto-aprovados.

Três gaps estruturais:

1. **Não existe ponte de bulk ingest entre catálogo global e `instruments_org`.** `universe_sync` (lock 900_070) popula `instruments_universe` com ~14k ativos cru globais. `universe_sanitization` (lock 900_063, migration 0134) marca `is_institutional` reduzindo para ~5k. Mas o onramp para `instruments_org` é **fund-by-fund via `screener_import_service.import_instrument`** — manual, usado pelo Screener UI e pelo worker de ESMA. Nunca foi construído um worker global que faça fan-out para todas as orgs ativas.
2. **`block_id` depende de atribuição manual.** `STRATEGY_LABEL_TO_BLOCKS` (em `backend/vertical_engines/wealth/model_portfolio/block_mapping.py`) já existe como tabela de classificação canônica — usada pelo construction advisor para sugerir blocos. O auto-import precisa **consumir esse mapping**, não criar paralelo.
3. **Seeds antigos poluem o universe atual.** Portfolios existentes (`model_portfolios`, `portfolio_calibration`, `portfolio_construction_runs`, `portfolio_stress_results`, `portfolio_snapshots`, `model_portfolio_nav`, `portfolio_alerts`) foram criados contra `instruments_org` pré-sanitization. Não são recuperáveis — foram construídos sobre um universo que já não existe conceitualmente. Precisam de **truncate cirúrgico** preservando as primitivas institucionais (`allocation_blocks`, `portfolio_views` quando forem IC genuínas, mandate bands).

Objetivo do PR: fechar o pipeline **Catálogo global → Sanitização → Auto-import por org → Builder operando sobre ~200-2000 candidates pós-mandate filter**, reduzindo 100% da latência operacional hoje paga por onboarding de ativo no Screener.

---

## Mandates (não-negociáveis)

- **`mandate_high_end_no_shortcuts.md`** — este PR toca compliance (quem autorizou o ativo no universe do cliente?) e o substrato de todo portfolio downstream. Iterar o necessário, instalar o necessário, nenhuma otimização de custo em detrimento de correção.
- **`feedback_no_emojis.md`** — zero emojis em código, commit messages, logs, audit events, admin endpoints, frontend.
- **`feedback_smart_backend_dumb_frontend.md`** — a UI do admin mostra "última run + rows added/updated/skipped + reason histogram"; não expõe "lock 900_xxx" ou termos técnicos do worker.
- **`feedback_infra_before_visual.md`** — Section F (admin visibility) é telemetria mínima, não UI de luxo. Backend correto primeiro; se sobrar tempo, polish.
- **`feedback_no_remove_endpoints.md`** — não remover `import_instrument` nem routes existentes do Screener. Screener continua sendo o override manual / path para privates. Auto-import **complementa**, não substitui.
- **`feedback_yagni_agent_danger.md`** — métodos "não-usados" em `screener_import_service` podem ser callback do onboarding manual. Não simplificar.
- **`mandate DB-first`** — worker lê de hypertables e tabelas globais já ingeridas (`instruments_universe`, `sec_manager_funds`, `sec_registered_funds`, `sec_etfs`, `sec_bdcs`, `sec_money_market_funds`, `esma_funds`). Nenhuma chamada a API externa.
- **RLS obrigatório** — worker é global mas itera orgs; cada iteração abre transação com `SET LOCAL app.current_organization_id`. Nunca usar `SET` (leaka no pool).
- **Advisory locks com literais deterministas** — nada de `hash()` Python.
- **Async-first** — worker e endpoint admin usam `async def` + `AsyncSession`. Pydantic `response_model` + `model_validate` em qualquer rota nova.
- **Idempotência P5** — executar duas vezes o worker com mesmo snapshot de catálogo produz o mesmo estado em `instruments_org`.

---

## Section A — Cleanup migration

### A.1 Premissa de estado

Pós-merge de PR-A5, o banco contém:

- `instruments_org` herdado: mistura de `approval_status IN ('pending', 'approved')`, `block_id` populado inconsistentemente, FK para `instruments_universe` às vezes aponta para ativos agora `is_institutional = false`.
- `model_portfolios` e dependências calibradas sobre esse substrato. A calibração (EWMA, covariância, BL views) não sobrevive à troca do substrato.
- `portfolio_views` pode conter IC views genuínas (inputs humanos para BL). **Preservar** se `created_by` for user humano e `expires_at > NOW()`.

### A.2 Migration Alembic — `0139_universe_cleanup_pre_autoimport`

Cabeçalho e pré-requisitos:

- `revision = "0139_universe_cleanup_pre_autoimport"`
- `down_revision = "0138_holdings_drift_alerts"`
- **Transacional obrigatório** — a migration inteira roda em uma transação. Se qualquer step falhar, rollback total.
- **Audit**: cada DELETE/TRUNCATE emite um `audit_event` via `write_audit_event()` com `entity_type = 'universe_cleanup'`, `action = 'truncate'`, payload = `{table, rows_affected, reason: 'pr_a6_pre_autoimport'}`. Correlation via `request_id = '<migration:0139>'`.

### A.3 Backup pré-cleanup (responsabilidade do executor, fora da migration)

Antes de `alembic upgrade head`:

- Executor roda `pg_dump` comprimido contra `DIRECT_DATABASE_URL` para `backups/backup_pre_universe_cleanup_<YYYYMMDD_HHMMSS>.sql.gz`.
- Dump cobre apenas as tabelas afetadas: `model_portfolios`, `portfolio_calibration`, `portfolio_construction_runs`, `portfolio_stress_results`, `portfolio_alerts`, `portfolio_snapshots`, `portfolio_views`, `model_portfolio_nav`, `instruments_org`.
- Comando e nome gerado commitados como comentário no cabeçalho da migration para trilha de auditoria.
- Em prod (Timescale Cloud) o executor usa Timescale native backup snapshot antes de rodar — a migration apenas **assume** que o backup existe.

### A.4 Sequência de operações

Ordem de FK resolution — derivada do schema atual. Confirmar lendo as migrations 0068-0138 antes de codificar; se alguma FK tiver `ON DELETE CASCADE` que torne um step redundante, documentar inline.

1. **`TRUNCATE portfolio_stress_results CASCADE`** — depende de `portfolio_construction_runs`.
2. **`TRUNCATE portfolio_construction_runs CASCADE`** — depende de `model_portfolios`.
3. **`TRUNCATE portfolio_snapshots CASCADE`** — depende de `model_portfolios`.
4. **`TRUNCATE model_portfolio_nav CASCADE`** — hypertable, depende de `model_portfolios`. Validar se TimescaleDB permite TRUNCATE em hypertable (sim, desde TSDB 2.x, mas chunks detach é assíncrono — se bloquear, usar `SELECT drop_chunks(...)`+`TRUNCATE`).
5. **`TRUNCATE portfolio_alerts CASCADE`** — depende de `model_portfolios`.
6. **`TRUNCATE portfolio_calibration CASCADE`** — depende de `model_portfolios`.
7. **`DELETE FROM portfolio_views WHERE expires_at < NOW() OR created_by IS NULL`** — preserva IC views humanas vivas. NÃO truncar.
8. **`TRUNCATE model_portfolios CASCADE`** — depende de nada crítico preservado.
9. **`DELETE FROM instruments_org WHERE selected_at < '2026-04-15 00:00:00+00'`** — mata órfãos pré-sanitization; auto-import do Section C repovoa.

### A.5 Preservar (explicitamente, não tocar)

- `allocation_blocks` — mandate bands, blended benchmarks, seed institucional. **Jamais** tocar.
- `portfolio_views` com `expires_at > NOW() AND created_by IS NOT NULL` — IC views humanas.
- `portfolios` (se distinto de `model_portfolios` — validar schema; hoje `model_portfolios` é o root).
- `fund_risk_metrics`, `nav_timeseries`, `instruments_universe`, `benchmark_nav`, `macro_data` — globais, intocáveis.

### A.6 Downgrade

`downgrade()` declara explicitamente `raise RuntimeError("0139 cleanup is irreversible — restore from backups/backup_pre_universe_cleanup_*.sql.gz")`. Não tentar reconstruir. Não é uma migration "reversível" — é um ponto de truncate cirúrgico com backup externo.

### A.7 Verificação pós-migration

Incluir no CI um teste (`backend/tests/wealth/test_migration_0139_cleanup.py`) que roda em ambiente descartável:

- Seed de `model_portfolios`/`instruments_org` antigos, rodar upgrade, asseverar counts zerados.
- Asseverar `allocation_blocks` preservados.
- Asseverar `portfolio_views` humanas preservadas.

---

## Section B — `block_id` auto-classification

### B.1 Fonte única de verdade

A tabela de lookup **já existe**: `backend/vertical_engines/wealth/model_portfolio/block_mapping.py` → `STRATEGY_LABEL_TO_BLOCKS`. Mapeia 37 `strategy_label` → lista priorizada de `block_id` (primeiro = canônico).

Blocos-alvo canônicos (derivados do mapping): `na_equity_large`, `na_equity_growth`, `na_equity_value`, `na_equity_small`, `dm_europe_equity`, `dm_asia_equity`, `em_equity`, `fi_us_aggregate`, `fi_us_treasury`, `fi_us_tips`, `fi_us_high_yield`, `fi_em_debt`, `alt_real_estate`, `alt_commodities`, `alt_gold`, `alt_hedge_fund`, `alt_managed_futures`, `cash`.

**Não criar migration nova de seed**. Assumir `allocation_blocks` populado pelos seeds existentes; se faltar algum block, falhar loud com log `block_mapping_missing_block` e skip do instrument, nunca silenciar.

### B.2 Função canônica de classificação (nova)

Criar `backend/app/domains/wealth/services/universe_auto_import_classifier.py`:

- Assinatura: `def classify_block(instrument: dict) -> tuple[str | None, str]` — recebe payload com `instrument_type`, `asset_class`, `attributes` (JSONB dict), retorna `(block_id, decision_reason)`.
- Decisão em cascata:
  1. Se `attributes.get("strategy_label")` mapear via `blocks_for_strategy_label(...)` → primeiro da lista, reason `"strategy_label"`.
  2. Se `asset_class == "cash"` ou `instrument_type == "money_market"` → `"cash"`, reason `"asset_class_cash"`.
  3. Se `asset_class == "fixed_income"` sem strategy_label → `"fi_us_aggregate"`, reason `"fallback_fi"`.
  4. Se `asset_class == "equity"` sem strategy_label → `"na_equity_large"`, reason `"fallback_equity"`.
  5. Se `attributes.get("fund_type") == "Real Estate Fund"` → `"alt_real_estate"`, reason `"fund_type_real_estate"`.
  6. Se `attributes.get("fund_type") in ("Hedge Fund", "Private Equity Fund", "Venture Capital Fund")` e **liquid universe** → pular (privates não entram no auto-import).
  7. Else → `(None, "unclassified")` — instrument é skipado no auto-import, NÃO importado como pending.

### B.3 Edge cases institucionais (explicit decisões)

- **MMF (Money Market Funds)** → `cash`. MMF é cash-equivalent para mandate/IPS; nunca `fi_us_aggregate`. Justificativa: reporting regulatório (SEC Rule 2a-7) trata como liquidity sleeve.
- **BDC (Business Development Company)** → **NÃO entra no auto-import**. BDC é private credit público com dinâmicas de liquidez hybrid; entra via Screener manual apenas, mesmo sendo `instrument_type = "bdc"`. Tratar como private universe.
- **ETF de commodity** (ex: GLD, PDBC) → `alt_gold` se `strategy_label == "Precious Metals"`, senão `alt_commodities`.
- **ETF de infraestrutura** → mapping aponta para `alt_commodities` hoje. Aceitar por ora; flag como dívida técnica para Phase FI (há plan em `project_fixed_income_quant_expansion`).
- **Hybrid funds / multi-asset** (ex: "Allocation--50% to 70% Equity") → `(None, "hybrid_unsupported")`. Skipar e logar. Não chutar bloco.
- **Target-date / retirement** — já foram marcados `is_institutional = false` pelo sanitization. Auto-import filtra `WHERE is_institutional = true`, então não chegam aqui.

### B.4 Teste obrigatório

`backend/tests/wealth/test_universe_auto_import_classifier.py`:

- Cobrir cada ramo da cascata (mínimo 1 asserção por ramo = 7 + 3 edge cases = 10 asserções).
- Table-driven com pares `(input_dict, expected_block, expected_reason)`.
- Incluir regressão: instrument com `strategy_label = "Private Credit"` deve mapear para `fi_us_high_yield` (conforme mapping atual), **mesmo o auto-import pulando privates** — a função retorna o mapping, o worker decide skipar.

---

## Section C — Worker `universe_auto_import`

### C.1 Identidade

- **Path**: `backend/app/domains/wealth/workers/universe_auto_import.py`.
- **Lock ID**: `900_103` — literal, próximo livre após `900_102` (alert_sweeper). **Não usar `900_071`** — conflita com `global_risk_metrics`.
- **Schedule**: Daily 04:00 UTC. Ordem de dependência: deve rodar **depois** de `universe_sync` (900_070, weekly) e `universe_sanitization` (900_063, on-demand). Em deploy, o cron do `universe_auto_import` verifica primeiro se `universe_sanitization` rodou nas últimas 48h; se não, loga `dependency_stale_sanitization` e prossegue (não bloqueia — stale < 48h é aceitável).
- **Scope**: global worker que itera orgs ativas. Um advisory lock global para impedir concorrência. Dentro do loop de orgs, sem lock per-org (idempotência via UPSERT resolve concorrência).

### C.2 Critérios SQL de qualificação (liquid universe, ~5k alvo)

Query seletiva sobre `instruments_universe`. SQL arquitetural (SQL exato fica com `financial-timeseries-db-architect`):

```
SELECT iu.instrument_id, iu.instrument_type, iu.asset_class, iu.attributes, iu.name
FROM instruments_universe iu
WHERE iu.is_active = true
  AND iu.is_institutional = true
  AND iu.instrument_type IN ('fund', 'etf', 'mutual_fund', 'closed_end_fund', 'interval_fund', 'money_market', 'ucits')
  AND (iu.attributes->>'fund_type' IS NULL
       OR iu.attributes->>'fund_type' NOT IN ('Hedge Fund', 'Private Equity Fund', 'Venture Capital Fund', 'Securitized Asset Fund'))
  AND (iu.attributes->>'aum_usd')::numeric >= 200000000      -- USD 200M floor
  AND (iu.attributes->>'track_record_years')::numeric >= 5    -- 5Y minimum
```

Edge: `aum_usd` e `track_record_years` podem não estar em `attributes` para todo instrument. Fallback:

- `aum_usd`: JOIN com `sec_registered_funds.net_assets`, `sec_etfs.monthly_avg_net_assets`, `sec_bdcs.total_net_assets`, `esma_funds` (sem AUM hoje — skip ESMA se AUM null).
- `track_record_years`: derivar de `attributes->>'fund_inception_date'` ou `sec_registered_funds.perf_inception_date`. Se NULL, skipar (não assumir — compliance não aceita).

### C.3 Loop principal

Pseudocódigo da topologia (SQL exato → db-architect):

```
lock = pg_try_advisory_lock(900_103)
if not lock: log "lock_contention" return

try:
    instruments = fetch_qualified_instruments(db)   # ~5k rows, global
    orgs = fetch_active_orgs(db)                    # organizations table, is_active = true

    for org in orgs:
        async with new_transaction() as tx:
            tx.execute("SET LOCAL app.current_organization_id = :org_id", {"org_id": org.id})
            metrics = {"added": 0, "updated": 0, "skipped": 0, "failed": 0, "per_reason": {}}

            for inst in instruments:
                block_id, reason = classify_block(inst)
                if block_id is None:
                    metrics["skipped"] += 1
                    metrics["per_reason"][reason] = metrics["per_reason"].get(reason, 0) + 1
                    continue

                # UPSERT — idempotent
                result = tx.execute("""
                    INSERT INTO instruments_org
                        (id, organization_id, instrument_id, block_id, approval_status, selected_at)
                    VALUES
                        (gen_random_uuid(), :org_id, :inst_id, :block_id, 'approved', NOW())
                    ON CONFLICT (organization_id, instrument_id) DO UPDATE
                    SET block_id = EXCLUDED.block_id
                    WHERE instruments_org.block_id IS DISTINCT FROM EXCLUDED.block_id
                      AND instruments_org.approval_status != 'rejected'  -- respect manual reject
                    RETURNING (xmax = 0) AS inserted
                """, {...})
                # classify added vs updated via RETURNING

            write_audit_event(
                tx, org_id=org.id,
                entity_type="universe_auto_import",
                action="run",
                payload=metrics,
            )
            tx.commit()
finally:
    pg_advisory_unlock(900_103)
```

### C.4 Idempotência — pontos críticos

- **UNIQUE constraint `(organization_id, instrument_id)`** em `instruments_org`. **Verificar se existe** na migration 0068; se não, **adicionar via migration `0140_instruments_org_unique`** no mesmo PR. Sem essa constraint, UPSERT vira INSERT duplicado.
- **Respeitar override manual**: `approval_status = 'rejected'` (IC disse não) nunca é sobrescrito. `WHERE instruments_org.approval_status != 'rejected'` no ON CONFLICT.
- **block_id override**: se `block_id` manual existir e diferir do classificado, **preservar o manual** se tiver flag `attributes->>'block_override' = 'true'` em `instruments_org` (adicionar coluna `block_overridden BOOLEAN DEFAULT false` via migration 0140). Sem flag, sobrescrever com classificação nova.

### C.5 Métricas e logging

Cada run emite log estruturado:

```
logger.info(
    "universe_auto_import_completed",
    org_id=str(org_id),
    instruments_evaluated=5000,
    added=1200,
    updated=300,
    skipped=3500,
    per_reason={"unclassified": 450, "hybrid_unsupported": 80, ...},
    duration_seconds=12.3,
)
```

### C.6 Testes

`backend/tests/wealth/workers/test_universe_auto_import.py`:

- Fixture: 2 orgs, 10 instruments no `instruments_universe` (mix de qualified/unqualified/private).
- Asserções (mínimo 8):
  1. Liquid qualified são inseridos em ambas orgs com `approval_status = 'approved'`.
  2. Privates não são inseridos.
  3. Non-institutional não são inseridos.
  4. Re-run é no-op (added=0, updated=0).
  5. Manual `approval_status = 'rejected'` sobrevive re-run.
  6. `block_overridden = true` sobrevive re-run.
  7. Audit event escrito por org.
  8. Lock contention log quando outra instância segura o lock.

---

## Section D — Provisioning hook (org nova → auto-import imediato)

### D.1 Estado atual

Não existe `org_provisioning_service` nem webhook Clerk no backend — confirmado via grep. Orgs novas criadas pela Clerk Dashboard só aparecem quando o primeiro user faz login e `get_db_with_rls` injeta o `organization_id` do JWT. `ConfigService` resolve defaults preguiçosamente.

Consequência: novo tenant **fica 24h sem universe** até o próximo run de `universe_auto_import`. Inaceitável institucionalmente.

### D.2 Endpoint admin + hook

**Criar `POST /admin/universe/auto-import/run`** (novo route em `backend/app/domains/admin/routes/universe_auto_import.py`):

- Body: `{"org_id": UUID, "reason": str}`. Reason livre (e.g., `"org_provisioning"`, `"manual_reimport_after_rejection_reversal"`).
- Disparada sincrônicamente (não async job) para orgs novas: ~5k UPSERTs cabem em < 10s, aceitável no onboarding.
- Roda a mesma função do worker (refatorar em `backend/app/domains/wealth/services/universe_auto_import_service.py` com assinatura `async def auto_import_for_org(db, org_id, reason) -> Metrics`). Worker e endpoint são wrappers finos.
- RBAC: apenas role `ADMIN`. Enforce via Clerk claim.

### D.3 Clerk webhook (opcional neste PR, recomendado)

Escopo: criar stub `POST /webhooks/clerk/organization.created` em `backend/app/core/auth/clerk_webhook.py`, assinatura HMAC validada, que enfileira chamada ao endpoint admin acima. Se o escopo apertar, deixar para PR-A7 mas documentar explicitamente no release notes: "orgs novas exigem que admin dispare POST /admin/universe/auto-import/run manualmente até PR-A7".

### D.4 Audit

Endpoint admin emite audit event `auto_import_manual_trigger` com `actor_id` (Clerk user), `org_id`, `reason`, `metrics`.

---

## Section E — Approval semantics + RBAC + audit

### E.1 Taxonomia final

| Universe | Path de entrada | `approval_status` inicial |
|---|---|---|
| `registered_us` (mutual_fund, closed_end, interval_fund) | auto-import | `approved` |
| `etf` | auto-import | `approved` |
| `money_market` | auto-import | `approved` |
| `ucits_eu` | auto-import | `approved` |
| `bdc` | **Screener manual** (não auto-import) | `pending` |
| `private_us` (hedge, PE, VC, RE, SAF) | **Screener manual** (não auto-import) | `pending` |

### E.2 Justificativa institucional

- **Liquid vehicles** são commodities institucionais regulados (N-PORT, N-CEN, UCITS prospectus). Auto-approval é aceitável porque mandate_fit e screening layers filtram downstream antes do fund entrar no portfolio.
- **Privates** exigem DD gate: contratos bilaterais, side-letters, GP relationship, lockup. O `approval_status = approved` em private fund é uma decisão IC formal — **jamais** gerada por worker.

### E.3 Preservação do gate

O constraint `approval_status = 'approved'` continua sendo gate em:

- `_load_universe_funds` (em `model_portfolios.py`).
- Builder UI dropdown de candidates.
- Optimizer cascade (reject inválido).

O PR-A6 **não remove o gate** — muda como liquid chega nele (automático) vs como private chega (manual).

### E.4 RBAC

- Trigger manual do worker (`POST /admin/universe/auto-import/run`): role `ADMIN` apenas.
- Override de `block_id` ou `approval_status` em `instruments_org` row: role `INVESTMENT_TEAM` ou superior. Confirmar no route do Screener existente; se gap, documentar.
- Reject row (`approval_status = 'rejected'`): role `INVESTMENT_TEAM`. Rejeição persiste através de runs do worker.

### E.5 Audit contract

Toda mutação em `instruments_org` escreve `audit_event`:

- `action ∈ {auto_import_insert, auto_import_update_block, manual_approve, manual_reject, manual_block_override, cleanup_delete}`.
- `before` / `after` JSONB snapshots completos da row.
- `correlation_id = worker_run_id | http_request_id`.

---

## Section F — Frontend admin visibility (telemetria mínima)

Alvo: `/admin/universe` no frontend `wealth` — página existente (confirmar) ou nova sob `frontends/wealth/src/routes/admin/universe/+page.svelte`.

### F.1 Blocos obrigatórios (backend → UI, dumb frontend)

1. **Última run** card: timestamp, duration, orgs processed, total UPSERTs. Endpoint `GET /admin/universe/auto-import/status` retorna pré-computado.
2. **Reason histogram** chart: top 10 `per_reason` agregado última semana. Mostra claramente quanto está sendo skipado e por quê — sinal para dívida de classificação.
3. **Org coverage table**: `org_id | org_name | rows_in_universe | last_import_at | unclassified_count`. Útil para identificar orgs "vazias" (provisionamento falho).
4. **Manual trigger button** (role ADMIN): dispara `POST /admin/universe/auto-import/run` para org selecionada. Mostra progresso via polling simples (10s interval, não SSE — é run curto).

### F.2 Formatters

Todos os números via `formatNumber` / `formatDateTime` / `formatDuration` do `@netz/ui`. Zero `.toFixed`/`.toLocaleString`.

### F.3 NÃO fazer nesta PR

- Não recriar screener UI.
- Não criar UI de edição de `STRATEGY_LABEL_TO_BLOCKS` — mapping é código.
- Não adicionar configuração de AUM floor por org — USD 200M é global (mudar requer PR).

---

## Section G — Rollback / manual override

### G.1 Rollback do PR inteiro

1. Revert do deploy.
2. Restore de `backups/backup_pre_universe_cleanup_<timestamp>.sql.gz` (backup externo da Section A.3) para as 9 tabelas.
3. `alembic downgrade 0138`. Migration 0139 tem `downgrade()` que raise — executor precisa rodar `alembic stamp 0138` após restore manual.

### G.2 Override manual de `block_id`

- Screener UI existente permite editar `block_id` de row em `instruments_org`.
- Ao fazer override, setar `attributes.block_overridden = true` em `instruments_org` (coluna nova via migration 0140).
- Worker respeita esse flag e não sobrescreve no próximo run.

### G.3 Rejection de instrument

- IC pode marcar `approval_status = 'rejected'` via Screener. Persiste através dos runs.
- Para "reativar", admin precisa resetar manualmente para `'pending'` ou `'approved'`. Worker não reativa rejections automaticamente.

### G.4 Ressurreição silenciosa (risco alto — tratamento)

**Risco**: IC remove manualmente uma row (`DELETE`), worker diário re-insere. Essa é a única razão pela qual DELETE não é o path canônico de rejeição — **reject é via `approval_status`**.

Mitigação: Screener UI e admin docs deixam explícito "Para remover do universe permanentemente, use Reject. DELETE é apenas para GC pós-rejection."

---

## Section H — Verification matrix

### H.1 DB state

- `SELECT COUNT(*) FROM instruments_org` ≈ `num_active_orgs × (5000 - skipped)`. Exemplo: 3 orgs, ~4500 qualified após skipar hybrid/unclassified → ~13500 rows.
- `SELECT COUNT(*) FROM instruments_org WHERE approval_status = 'approved' AND block_id IS NOT NULL` = total esperado.
- `SELECT COUNT(DISTINCT block_id) FROM instruments_org` ≥ 15 (cobertura das 18 blocos; alguns podem ficar vazios se nenhum strategy_label mapear — e.g., `alt_managed_futures`).

### H.2 Worker re-run idempotente

- Run 1: added ≈ 4500, updated = 0, skipped ≈ 500.
- Run 2 (imediato): added = 0, updated = 0, skipped ≈ 500 (mesmo reason histogram).

### H.3 Playwright e2e (nova spec)

`frontends/wealth/e2e/universe-autoimport.spec.ts`:

1. Login como admin.
2. Navegar `/admin/universe`, disparar manual run para org de teste.
3. Esperar metrics card atualizar com `added ≈ 4500`.
4. Navegar `/portfolio/builder`, criar novo model portfolio.
5. Abrir dropdown de candidates — asseverar ≥ 100 rows visíveis.
6. Disparar build com mandate default.
7. **Asseverar**: build completa com `status = success`, `run.solver_status = optimal`.
8. Abrir stress panel — asseverar 4 scenarios populados.

### H.4 Backend pytest

- `test_universe_auto_import_classifier.py` — 10+ asserções.
- `test_universe_auto_import_worker.py` — 8+ asserções.
- `test_migration_0139_cleanup.py` — preserva/zera corretamente.
- `test_admin_universe_route.py` — RBAC (non-admin → 403), happy path, idempotência.

### H.5 Observability

- Log `universe_auto_import_completed` aparece uma vez por org por run.
- Audit events de `auto_import_insert` somam = `added` do metrics.
- Nenhum `pg_advisory_unlock` warning (lock sempre liberado).

---

## Section I — Risk register

### I.1 Compliance / institutional trust

- **Risco**: cliente auditor pergunta "quem autorizou esses 4500 ativos no meu universe?" Resposta formal: "política de auto-approval para liquid regulated vehicles ≥ USD 200M AUM, 5Y track record, sanitização SEC/ESMA; IC override via Screener; audit trail completo em `audit_events`."
- **Mitigação**: incluir policy statement em `docs/reference/universe-autoimport-policy.md` referenciando AUM floor, track record floor, exclusões (privates, BDC, retail).

### I.2 Classificação incorreta

- **Risco**: `STRATEGY_LABEL_TO_BLOCKS` erra bloco para fund específico (e.g., multi-asset classificado como equity). Downstream: mandate_fit filtra wrong, optimizer sofre ou exclui.
- **Mitigação**: flag `block_overridden`, Screener UI mostra "Auto-classified (override disponível)" com preview do mapping; `per_reason` histogram monitora skips por "hybrid_unsupported".

### I.3 Performance

- **Risco**: UPSERT de ~5k × N orgs pode contender row locks em horário de pico.
- **Mitigação**: schedule 04:00 UTC (off-hours). Per-org transaction. Confirmar com db-architect se batch size recomendado é 500/txn. Medir p95.

### I.4 Cardinalidade do optimizer com 5k candidates

- **Delegado**: `wealth-portfolio-quant-architect` responde se CLARABEL aguenta 5k × N blocks no problema. **Hipótese**: otimizer nunca vê 5k — mandate_fit filtra antes (por block, por AUM mínimo da org, por approved status), reduzindo para ~200-2000 candidates por run. Validar empiricamente.

### I.5 Impacto em features dependentes

- **Drift monitor / watchlist**: rows novas em `instruments_org` são visíveis automaticamente. Sem retrabalho.
- **Scoring**: scoring roda sobre `instruments_universe` (global) e lê `fund_risk_metrics`. Não afetado.
- **Rebalancing**: impact analyzer usa `instruments_org` — ganha cobertura instantânea.
- **DD Report**: private funds continuam exigindo trigger manual (auto-import não cobre DD).

### I.6 Seed de dev / test

- **Risco**: devs rodando localmente não têm `instruments_universe` populado (worker `universe_sync` não rodou). Worker `universe_auto_import` não faz nada.
- **Mitigação**: script `backend/scripts/seed_universe_for_dev.py` que injeta ~100 instruments fake em `instruments_universe` para dev local. Documentar em CONTRIBUTING.

---

## Section J — Deliverables checklist

Ordem de commit dentro do branch `feat/pr-a6-universe-autoimport`:

1. **Commit 1** — `feat(wealth): add block_overridden + unique constraint on instruments_org`
   - Migration `0140_instruments_org_unique_and_override.py`:
     - `ADD COLUMN block_overridden BOOLEAN NOT NULL DEFAULT false`.
     - `CREATE UNIQUE INDEX CONCURRENTLY idx_instruments_org_unique ON instruments_org (organization_id, instrument_id)` — `CONCURRENTLY` para não travar prod.
     - `ADD CONSTRAINT uq_instruments_org UNIQUE USING INDEX idx_instruments_org_unique`.

2. **Commit 2** — `feat(wealth): universe auto-import classifier service`
   - `backend/app/domains/wealth/services/universe_auto_import_classifier.py`.
   - `backend/tests/wealth/services/test_universe_auto_import_classifier.py`.

3. **Commit 3** — `feat(wealth): universe_auto_import service and worker`
   - `backend/app/domains/wealth/services/universe_auto_import_service.py` (núcleo reutilizável).
   - `backend/app/domains/wealth/workers/universe_auto_import.py` (wrapper worker, lock 900_103).
   - `backend/tests/wealth/workers/test_universe_auto_import.py`.
   - Registrar no `backend/app/domains/admin/routes/worker_registry.py`.

4. **Commit 4** — `feat(admin): universe auto-import admin routes`
   - `backend/app/domains/admin/routes/universe_auto_import.py` (`POST /admin/universe/auto-import/run`, `GET /admin/universe/auto-import/status`).
   - `backend/tests/admin/test_universe_auto_import_routes.py`.

5. **Commit 5** — `feat(wealth): cleanup migration 0139 + pre-truncate audit`
   - `backend/app/core/db/migrations/versions/0139_universe_cleanup_pre_autoimport.py`.
   - `backend/tests/migrations/test_0139_cleanup.py`.
   - **Pré-flight doc** em `docs/runbooks/pr-a6-cleanup.md` com comando `pg_dump` e path esperado do backup.

6. **Commit 6** — `feat(wealth-frontend): admin universe auto-import visibility`
   - `frontends/wealth/src/routes/admin/universe/+page.svelte`.
   - `frontends/wealth/src/lib/api/admin/universe.ts` (typed client via openapi-types).
   - Playwright spec `frontends/wealth/e2e/universe-autoimport.spec.ts`.

7. **Commit 7** — `chore: update CLAUDE.md workers table + reference docs`
   - Adicionar linha `universe_auto_import | 900_103 | global (itera orgs) | instruments_org | sanitized catalog | Daily 04:00 UTC` na tabela de workers.
   - Atualizar `universe_sanitization` row (lock 900_063 — está ausente hoje da tabela).
   - Criar `docs/reference/universe-autoimport-policy.md`.

Cada commit deve passar `make check` independentemente.

### J.1 Sequência de execução local

```
# 1. branch + deps
git checkout -b feat/pr-a6-universe-autoimport

# 2. rodar testes incrementais commit-a-commit (make check em cada)

# 3. local: garantir seed do universe
make up
python backend/scripts/seed_universe_for_dev.py
alembic upgrade head  # aplica 0140
alembic upgrade head  # aplica 0139 (irreversível — só em branch dev)

# 4. smoke test: dispara worker manualmente
python -m backend.app.domains.wealth.workers.universe_auto_import

# 5. playwright
cd frontends/wealth && pnpm test:e2e universe-autoimport
```

### J.2 Deploy sequence (prod)

1. Merge PR-A6 → trigger build Railway.
2. **Antes do deploy automático**: operador roda Timescale backup snapshot manual.
3. Deploy. Alembic upgrade aplica 0140 (unique constraint) e 0139 (cleanup, irreversível).
4. Cron `universe_auto_import` no próximo 04:00 UTC preenche `instruments_org`. **Alternativa**: admin dispara `POST /admin/universe/auto-import/run` para cada org ativa imediatamente pós-deploy.
5. Validar via Playwright contra prod (read-only flow até Builder).

---

## Section K — What NOT to do

- **Não remover** `screener_import_service.import_instrument` — é o path canônico para onboard manual (privates, overrides, edge cases).
- **Não mover** `STRATEGY_LABEL_TO_BLOCKS` para YAML ou DB — é código versionado institucional; override dinâmico introduz superfície de risco sem ganho.
- **Não tornar 0139 reversível** — é ponto de truncate declarado; reversibilidade falsa esconde que o estado pré-cleanup foi destruído.
- **Não auto-aprovar privates** — violação do DD gate institucional. Mantra: liquid = auto, private = manual.
- **Não filtrar por `organization_id` em `fund_risk_metrics`, `instruments_universe`, `nav_timeseries`** — são globais por design.
- **Não usar `hash()` Python** para lock — `900_103` é literal.
- **Não criar UI de edição de AUM floor / track record floor** — decisão institucional, mudança via PR.
- **Não compactar cleanup em uma migration fake-reversível** — explicit irreversibility é feature, não bug.
- **Não pular o backup pré-cleanup em prod** — runbook obrigatório em `docs/runbooks/pr-a6-cleanup.md`.
- **Não substituir o gate `approval_status`** — gate continua; só muda como chega nele.
- **Não rodar `universe_auto_import` em paralelo sem advisory lock** — lock contention em UPSERT global é real.
- **Não emojis.** Em lugar nenhum.

---

## Reference files (paths absolutos)

- `C:\Users\andre\projetos\netz-analysis-engine\CLAUDE.md` — arquitetura, workers table, regras async/RLS, formatter discipline.
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\models\instrument.py` — `Instrument` (global catalog).
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\models\instrument_org.py` — `InstrumentOrg` (org-scoped).
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\models\block.py` — `AllocationBlock` schema.
- `C:\Users\andre\projetos\netz-analysis-engine\backend\vertical_engines\wealth\model_portfolio\block_mapping.py` — fonte canônica `STRATEGY_LABEL_TO_BLOCKS`.
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\workers\universe_sanitization.py` — sanitization worker de referência (padrão lock, audit, idempotência).
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\workers\universe_sync.py` — catalog ingest worker de referência.
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\services\screener_import_service.py` — `import_instrument` (path manual preservado).
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\core\db\migrations\versions\0134_universe_sanitization_flags.py` — pattern de migration que adiciona colunas e partial index.
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\core\db\migrations\versions\0138_holdings_drift_alerts.py` — HEAD atual, base do `down_revision`.
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\core\db\audit.py` — `write_audit_event`.
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\admin\routes\worker_registry.py` — registry onde o novo worker se declara.
- `C:\Users\andre\projetos\netz-analysis-engine\docs\prompts\2026-04-15-construction-engine-pr-a5-frontend-migration.md` — template estrutural desta spec.
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\routes\model_portfolios.py` — `_load_universe_funds` (consumidor pós-PR).

---

## Anexos delegados (specialists paralelos)

- **Section B-alt (db-architect)** — SQL exato de qualificação, `ON CONFLICT DO UPDATE` final, análise de lock contention do UPSERT em `instruments_org`, índice `CONCURRENTLY` seguro em Timescale Cloud, pattern de backup seletivo via `pg_dump -t`, vacuum/analyze pós run.
- **Section H-alt (quant-architect)** — comportamento do CLARABEL cascade com 2000 candidates × 18 blocks, pre-filter mandate_fit antes do SOCP (redução para ~200-500), time budget Phase 1 → 1.5 → 2 → 3, fallback heurístico quando CLARABEL diverge em scale, validação que stress scenarios continuam determinísticos sob novo universe.


---

# PR-A6 — Anexo SQL / DB (Universe Auto-Import + Cleanup)

> Especialista: `financial-timeseries-db-architect`.
> Data: 2026-04-15. Head Alembic **real** no repo: `0138_holdings_drift_alerts` (CLAUDE.md `0131_return_5y_10y` está desatualizada — corrigir na próxima varredura). Migrations desta PR devem descender de `0138`.

## Flags / pré-condições a confirmar antes do primeiro `make migrate`

| # | Flag | Impacto se ignorado |
|---|------|---------------------|
| F1 | **Lock ID 900_071 JÁ ESTÁ OCUPADO** por `global_risk_metrics` (ver CLAUDE.md tabela de workers). Worker novo deve usar **`900_103`** (sequência após `alert_sweeper=900_102`). | Dois workers com o mesmo advisory lock se serializam, mas um deles nunca ganha janela em prod. Race de métricas e staleness. |
| F2 | `instruments_org` **não tem coluna `source`** hoje (ver `backend/app/domains/wealth/models/instrument_org.py`). Migration A.3 precisa adicioná-la. | Spec do prompt principal assume `source='universe_auto_import'` — sem a coluna o `ON CONFLICT` não distingue importado manual vs automático e apaga overrides. |
| F3 | `instruments_universe` usa **`instrument_type` + `asset_class`**, não `asset_type`. A coluna equivalente à "universe" (registered_us / etf / ucits_eu / money_market / bdc / private_us) vive em `attributes->>'sec_universe'` (populada por `universe_sync`). | Query de qualificação quebra se usar `asset_type`. |
| F4 | `is_institutional` é **GENERATED COLUMN** (migration `0134_universe_sanitization_flags`) lendo `attributes->>'is_institutional'`. É read-only; não tentar escrever via INSERT. | INSERT falha com `cannot insert into column "is_institutional"`. |
| F5 | `fund_risk_metrics` **NÃO** tem coluna `aum_usd`. AUM canônico vive em: (a) `instruments_universe.attributes->>'aum_usd'` (popular por `universe_sync`), (b) `mv_unified_funds.aum_usd` (coluna materializada consolidando N-CEN + XBRL + N-MFP + ADV GAV). Fonte preferida = **`mv_unified_funds.aum_usd`** porque é a única que atravessa os 6 branches com coalesce correto. | Se usar só `attributes->>'aum_usd'`, UCITS/MMF sem AUM no attribute nunca qualificam. |
| F6 | `mv_unified_funds.external_id` é heterogêneo: CIK (registered_us sem share class), `class_id`, `series_id`, `isin` (UCITS), UUID string (private_us). Bridge para `instruments_universe.instrument_id` é via `attributes->>'series_id'`, `attributes->>'sec_cik'`, `isin`, `ticker`. **Não há chave única** — a junção exige fallback em cascata. | Instrumentos novos (recém-importados pelo `universe_sync`) podem não aparecer se bridge falha. |
| F7 | `InstrumentOrg` herda `OrganizationScopedMixin` → **RLS está ativo**. TRUNCATE em tabela com RLS exige superuser **ou** DELETE com `SET LOCAL app.current_organization_id`. | TRUNCATE sem bypass causa `permission denied` em Timescale Cloud (role app não é superuser). |
| F8 | `model_portfolio_nav` é **hypertable TimescaleDB** (1mo chunks, ver `c3d4e5f6a7b8_timescaledb_hypertables_compression.py`). TRUNCATE hypertable funciona mas **não libera disco de chunks comprimidos** se houver policy ativa — e o ORDER BY do cleanup queria ambos. Solução: `SELECT drop_chunks('model_portfolio_nav', older_than => INTERVAL '100 years')` ou descomprimir primeiro. | TRUNCATE direto pode deixar chunks órfãos visíveis em `_timescaledb_catalog.chunk`. |
| F9 | `approval_status` não é enum — é `VARCHAR(20)` sem CHECK. Valores em uso no código: `pending`, `approved`, `rejected`. **Não inventar** `promoted` ou novo valor sem migration. | Frontend/screener filtra exatamente esses 3 valores. |

Se qualquer flag acima for falsa no merge time, interromper aplicação e pedir reconcile.

---

## Section A — Cleanup migration (`0139_universe_cleanup_pre_autoimport.py`)

### A.0 — Backup obrigatório (operador, antes do `make migrate`)

```bash
# Timestamp determinístico — inclui segundos para evitar colisão com o backup
# pre-apply feito por outros scripts (backups/backup_pre_apply_*.sql.gz já existem).
TS=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_FILE="backups/backup_pre_universe_cleanup_${TS}.sql.gz"

pg_dump \
  --no-owner \
  --no-privileges \
  --format=custom \
  --compress=9 \
  --table=instruments_org \
  --table=model_portfolios \
  --table=model_portfolio_nav \
  --table=portfolio_construction_runs \
  --table=portfolio_stress_results \
  --table=portfolio_alerts \
  --table=portfolio_views \
  --table=strategic_allocation \
  --table=tactical_positions \
  "$DIRECT_DATABASE_URL" \
  | gzip -9 > "$BACKUP_FILE"

echo "Backup: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"
# Registrar checksum para audit
sha256sum "$BACKUP_FILE" > "${BACKUP_FILE}.sha256"
```

> **Nota de porta:** `DIRECT_DATABASE_URL` (5432) e não o pooler `DATABASE_URL` — pg_dump com pooler corrompe o snapshot em long-running dumps.

### A.1 — Discovery de dependências (fazer 1× e documentar no commit message)

```sql
-- Execute no prod read-replica antes da migration para confirmar árvore real:
SELECT
    conrelid::regclass AS child_table,
    conname,
    confrelid::regclass AS parent_table,
    confdeltype AS on_delete
FROM pg_constraint
WHERE contype = 'f'
  AND confrelid::regclass::text IN (
      'model_portfolios',
      'portfolio_construction_runs',
      'instruments_org'
  )
ORDER BY parent_table, child_table;
```

Esperado (baseado na leitura dos models, validar no merge time):

- `model_portfolio_nav.portfolio_id` → `model_portfolios` (CASCADE presumido; modelo em `model_portfolio_nav.py`)
- `portfolio_stress_results.run_id` → `portfolio_construction_runs`
- `portfolio_alerts.portfolio_id` → `model_portfolios`
- `portfolio_views.portfolio_id` → `model_portfolios`
- `rebalance_proposals.portfolio_id` → `model_portfolios`

Se alguma FK tiver `ON DELETE NO ACTION` ou `RESTRICT`, TRUNCATE CASCADE falha e precisamos DELETE topologicamente ordenado.

### A.2 — Ordem de limpeza (filhos → pais, bypass RLS)

```python
# 0139_universe_cleanup_pre_autoimport.py
from alembic import op

revision = "0139_universe_cleanup_pre_autoimport"
down_revision = "0138_holdings_drift_alerts"
branch_labels = None
depends_on = None

CUTOFF = "2026-04-15"  # Data-corte — acertar com Andrei no merge

def upgrade() -> None:
    # 1) Métricas pré-limpeza para audit (não apaga nada ainda)
    op.execute("""
        CREATE TEMP TABLE _cleanup_pre_counts AS
        SELECT 'instruments_org'           AS tbl, COUNT(*)::bigint AS n FROM instruments_org
        UNION ALL SELECT 'model_portfolios',            COUNT(*) FROM model_portfolios
        UNION ALL SELECT 'model_portfolio_nav',         COUNT(*) FROM model_portfolio_nav
        UNION ALL SELECT 'portfolio_construction_runs', COUNT(*) FROM portfolio_construction_runs
        UNION ALL SELECT 'portfolio_stress_results',    COUNT(*) FROM portfolio_stress_results
        UNION ALL SELECT 'portfolio_alerts',            COUNT(*) FROM portfolio_alerts
        UNION ALL SELECT 'portfolio_views',             COUNT(*) FROM portfolio_views
        UNION ALL SELECT 'strategic_allocation',        COUNT(*) FROM strategic_allocation;
    """)

    # 2) Bypass RLS para a transação (role de migration precisa BYPASSRLS
    #    em Timescale Cloud. Se não tiver, rodar como superuser manualmente.)
    op.execute("SET LOCAL row_security = off;")

    # 3) TimescaleDB: drop de chunks da hypertable (mais limpo que TRUNCATE)
    op.execute("""
        SELECT drop_chunks(
            'model_portfolio_nav',
            older_than => INTERVAL '100 years'
        );
    """)

    # 4) TRUNCATE em ordem topológica. CASCADE seguro porque já dropamos
    #    chunks da hypertable acima e as outras tabelas são regulares.
    #    RESTART IDENTITY zera serials (model_portfolios não usa serial,
    #    mas é defensivo).
    op.execute("""
        TRUNCATE TABLE
            portfolio_stress_results,
            portfolio_alerts,
            portfolio_views,
            rebalance_proposals,
            portfolio_construction_runs,
            model_portfolios,
            strategic_allocation,
            tactical_positions
        RESTART IDENTITY CASCADE;
    """)

    # 5) DELETE seletivo em instruments_org (preserva imports recentes
    #    feitos manualmente — rule: anything before cutoff is stale,
    #    after cutoff foi escolha consciente).
    op.execute(f"""
        DELETE FROM instruments_org
        WHERE selected_at < '{CUTOFF}'::date;
    """)

    # 6) Audit: log diff para audit_events (uma linha por tabela)
    op.execute("""
        INSERT INTO audit_events (
            event_id, organization_id, actor, action, entity_type,
            entity_id, before, after, request_id, created_at
        )
        SELECT
            gen_random_uuid(),
            NULL,                                  -- global cleanup
            'alembic:0139',
            'truncate',
            'cleanup_pre_universe_autoimport',
            pre.tbl,
            jsonb_build_object('rows', pre.n),
            jsonb_build_object('rows', 0),
            NULL,
            now()
        FROM _cleanup_pre_counts pre;
    """)


def downgrade() -> None:
    # TRUNCATE é não-reversível sem restore do backup.
    # Downgrade falha deliberadamente para forçar o operador a restaurar
    # `backups/backup_pre_universe_cleanup_<timestamp>.sql.gz`.
    raise RuntimeError(
        "0139 cleanup is non-reversible. "
        "Restore from backups/backup_pre_universe_cleanup_*.sql.gz "
        "with pg_restore --clean before downgrading."
    )
```

**Justificativa:**
- `SET LOCAL row_security = off;` transaction-scoped — não vaza em pool (CLAUDE.md rule).
- `drop_chunks` antes do TRUNCATE garante catalog limpo em Timescale; TRUNCATE sozinho em hypertable deixa chunks vazios referenciados até próximo VACUUM policy.
- Audit por-tabela (não por-row) evita explosão de `audit_events` — centenas de milhares de rows colapsam em N linhas.
- Downgrade intencionalmente falha: senão um `alembic downgrade -1` destrói silenciosamente o backup.

### A.3 — Adicionar coluna `source` em `instruments_org` (migration separada)

```python
# 0140_instruments_org_source_column.py
revision = "0140_instruments_org_source_column"
down_revision = "0139_universe_cleanup_pre_autoimport"

def upgrade() -> None:
    op.execute("""
        ALTER TABLE instruments_org
        ADD COLUMN IF NOT EXISTS source VARCHAR(40)
            NOT NULL DEFAULT 'manual';
    """)
    # Partial index: worker query filtra por source = 'universe_auto_import'
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_instruments_org_source_auto
        ON instruments_org (organization_id, source)
        WHERE source = 'universe_auto_import';
    """)

def downgrade() -> None:
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_instruments_org_source_auto;")
    op.execute("ALTER TABLE instruments_org DROP COLUMN IF EXISTS source;")
```

> `CREATE INDEX CONCURRENTLY` **não pode rodar dentro de transação** — Alembic precisa do `op.execute` com `postgresql_concurrently=True` ou rodar em autocommit. Alternativa: aplicar o índice em script separado após `make migrate`. Registrar como TODO se usar o path transacional.

### A.4 — Índices de suporte ao worker

```python
# Parte do 0140 ou de 0141 separado
op.execute("""
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_instruments_org_selected_at
    ON instruments_org (selected_at);
""")

-- Para WHERE AUM ≥ 200M no caminho do worker
op.execute("""
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_iu_attr_aum_institutional
    ON instruments_universe (
        ((attributes->>'aum_usd')::numeric)
    ) WHERE is_institutional = TRUE;
""")

-- Para WHERE inception_date ≤ today - 5y
op.execute("""
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_iu_attr_inception_institutional
    ON instruments_universe (
        ((attributes->>'inception_date')::date)
    ) WHERE is_institutional = TRUE;
""")

-- Para a bridge instruments_universe ↔ mv_unified_funds via series_id/cik/isin
op.execute("""
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_iu_attr_series_id
    ON instruments_universe ((attributes->>'series_id'))
    WHERE is_institutional = TRUE;
""")
op.execute("""
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_iu_attr_sec_cik
    ON instruments_universe ((attributes->>'sec_cik'))
    WHERE is_institutional = TRUE;
""")
```

> `mv_unified_funds.external_id` já tem índice único (ver `0135_mv_unified_funds_institutional`).

---

## Section B — Tabela `block_classification` (`0141_block_classification_table.py`)

### B.1 — Schema

```python
revision = "0141_block_classification_table"
down_revision = "0140_instruments_org_source_column"

def upgrade() -> None:
    op.execute("""
        CREATE TABLE block_classification (
            universe      VARCHAR(40) NOT NULL,
            fund_type     VARCHAR(40) NOT NULL,     -- 'etf', 'bdc', 'money_market', 'mutual_fund', ...
            asset_class   VARCHAR(50) NOT NULL,     -- coluna real em instruments_universe
            strategy_key  VARCHAR(80) NOT NULL,     -- normalized label; 'DEFAULT' = catch-all
            block_id      VARCHAR(80) NOT NULL
                REFERENCES allocation_blocks(block_id)
                ON DELETE RESTRICT,
            priority      SMALLINT NOT NULL DEFAULT 100,  -- lower = preferido em caso de múltiplos matches
            PRIMARY KEY (universe, fund_type, asset_class, strategy_key)
        );

        CREATE INDEX idx_block_classification_lookup
            ON block_classification (universe, fund_type, asset_class);
    """)
    _seed_block_classification()

def _seed_block_classification() -> None:
    # ATENÇÃO: valores de block_id precisam existir em allocation_blocks.
    # Baseado em 0122 (FI) e 0126 (equity). Se algum block_id abaixo não
    # existir, a FK quebra. Andrei precisa confirmar os 6 blocks de
    # 'EQUITY', 'FIXED_INCOME', 'ALTERNATIVES' consolidados.
    #
    # Blocks conhecidos no repo (não assumir outros sem grep):
    #   - na_equity_large          (0126)
    #   - fi_aggregate, fi_ig_corporate, fi_high_yield, fi_tips,
    #     fi_govt, fi_em_debt, fi_short_term  (0122)
    # O restante (em_equity_*, eu_equity_*, alternatives_*) precisa
    # de migration adicional ou confirmação de que já foram seeded
    # fora de Alembic.
    op.execute("""
        INSERT INTO block_classification
            (universe, fund_type, asset_class, strategy_key, block_id, priority)
        VALUES
            -- registered_us / ETF / equity
            ('registered_us', 'etf',          'equity',       'DEFAULT', 'na_equity_large',  100),
            ('registered_us', 'mutual_fund',  'equity',       'DEFAULT', 'na_equity_large',  100),
            -- registered_us / FI
            ('registered_us', 'etf',          'fixed_income', 'DEFAULT', 'fi_aggregate',     100),
            ('registered_us', 'etf',          'fixed_income', 'high_yield', 'fi_high_yield', 50),
            ('registered_us', 'etf',          'fixed_income', 'tips',       'fi_tips',       50),
            ('registered_us', 'etf',          'fixed_income', 'govt',       'fi_govt',       50),
            ('registered_us', 'etf',          'fixed_income', 'ig_corp',    'fi_ig_corporate', 50),
            ('registered_us', 'etf',          'fixed_income', 'em_debt',    'fi_em_debt',    50),
            ('registered_us', 'etf',          'fixed_income', 'short_term', 'fi_short_term', 50),
            ('registered_us', 'mutual_fund',  'fixed_income', 'DEFAULT', 'fi_aggregate',     100),
            -- Money Market → FI / cash-equivalent bucket (usar fi_short_term por ora)
            ('registered_us', 'money_market', 'fixed_income', 'DEFAULT', 'fi_short_term',    100),
            -- BDC → alternatives. BLOCK 'alternatives_private_credit' DEVE EXISTIR.
            -- Se Andrei ainda não criou, este INSERT falha — criar junto.
            ('registered_us', 'bdc',          'alternatives', 'DEFAULT', 'alternatives_private_credit', 100),
            -- UCITS
            ('ucits_eu',      'ucits',        'equity',       'DEFAULT', 'na_equity_large',  100),
            ('ucits_eu',      'ucits',        'fixed_income', 'DEFAULT', 'fi_aggregate',     100)
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS block_classification;")
```

### B.2 — Edge cases explícitos

| Caso | Tratamento |
|---|---|
| `asset_class IS NULL` em `instruments_universe` | Worker **pula** a row (log em `rows_skipped_no_asset_class`). Não auto-classifica como OTHER — é sinal de dado sujo do `universe_sync`. |
| Hybrid (60/40) | Bater pelo `strategy_label` dominante: se contém "balanced" ou "60/40", atribuir ao asset_class principal ('equity'). Layer 2 pode refinar depois. |
| Crypto ETFs | Block `alternatives_crypto` — **não existe hoje**. Se aparecer, worker pula com `rows_skipped_missing_block`. Não inventar block na primeira rodada. |
| Mismatch entre `instruments_universe.asset_class` e o `asset_class` em `allocation_blocks` | Fallback via `strategy_key='DEFAULT'`. Se mesmo assim não acha, pula. |

---

## Section C — Worker `universe_auto_import` SQL (lock **900_103**)

### C.1 — Query de qualificação (versão canônica)

```sql
-- $1 = :org_id (uuid)
-- $2 = :cutoff_date (date, = CURRENT_DATE - INTERVAL '5 years')
-- $3 = :aum_floor (numeric, 200000000)
-- $4 = :coverage_days_min (int, 1260)

WITH candidates AS (
    SELECT
        iu.instrument_id,
        iu.asset_class,
        COALESCE(iu.attributes->>'sec_universe', 'unknown') AS universe,
        -- fund_type canônico: attr > mv_unified_funds fallback
        COALESCE(
            iu.attributes->>'fund_subtype',
            muf.fund_type
        ) AS fund_type,
        COALESCE(iu.attributes->>'strategy_label', '') AS strategy_raw,
        -- AUM cross-universe: mv_unified_funds canonical > attributes fallback
        COALESCE(
            muf.aum_usd,
            (iu.attributes->>'aum_usd')::numeric
        ) AS aum_usd,
        -- Inception: attributes > mv_unified_funds
        COALESCE(
            (iu.attributes->>'inception_date')::date,
            muf.inception_date
        ) AS inception_date
    FROM instruments_universe iu
    LEFT JOIN mv_unified_funds muf
        ON muf.external_id = COALESCE(
               iu.attributes->>'series_id',
               iu.attributes->>'sec_cik',
               iu.isin,
               iu.ticker
           )
    WHERE iu.is_active = TRUE
      AND iu.is_institutional = TRUE
      AND iu.asset_class IS NOT NULL
      AND COALESCE(iu.attributes->>'sec_universe', '') IN (
          'registered_us', 'etf', 'ucits_eu', 'money_market'
      )
),
qualified AS (
    SELECT
        c.*,
        -- strategy_key normalizado (minúsculas, snake_case) para lookup
        CASE
            WHEN c.strategy_raw ILIKE '%high yield%'   THEN 'high_yield'
            WHEN c.strategy_raw ILIKE '%tips%'         THEN 'tips'
            WHEN c.strategy_raw ILIKE '%government%'
              OR c.strategy_raw ILIKE '%treasury%'     THEN 'govt'
            WHEN c.strategy_raw ILIKE '%investment grade%'
              OR c.strategy_raw ILIKE '%ig corp%'      THEN 'ig_corp'
            WHEN c.strategy_raw ILIKE '%emerging market%'
              AND c.asset_class = 'fixed_income'       THEN 'em_debt'
            WHEN c.strategy_raw ILIKE '%short%' AND c.asset_class = 'fixed_income'
                                                       THEN 'short_term'
            ELSE 'DEFAULT'
        END AS strategy_key
    FROM candidates c
    WHERE c.inception_date IS NOT NULL
      AND c.inception_date <= $2::date
      AND COALESCE(c.aum_usd, 0) >= $3::numeric
),
nav_coverage AS (
    -- Coverage check: ≥ 1260 NAV points (roughly 5y trading days)
    -- Só computa para os qualified — não faz full scan da hypertable.
    SELECT
        q.instrument_id,
        COUNT(nt.nav_date) AS n_obs
    FROM qualified q
    JOIN nav_timeseries nt
        ON nt.instrument_id = q.instrument_id
       AND nt.nav_date >= ($2::date - INTERVAL '30 days')  -- chunk exclusion
    GROUP BY q.instrument_id
),
with_blocks AS (
    SELECT DISTINCT ON (q.instrument_id)
        q.instrument_id,
        bc.block_id
    FROM qualified q
    JOIN nav_coverage nc ON nc.instrument_id = q.instrument_id
    JOIN block_classification bc
        ON bc.universe     = q.universe
       AND bc.fund_type    = q.fund_type
       AND bc.asset_class  = q.asset_class
       AND (bc.strategy_key = q.strategy_key OR bc.strategy_key = 'DEFAULT')
    WHERE nc.n_obs >= $4
    ORDER BY q.instrument_id, bc.priority ASC  -- lower priority wins
)
INSERT INTO instruments_org (
    id, organization_id, instrument_id, block_id,
    approval_status, selected_at, source
)
SELECT
    gen_random_uuid(),
    $1::uuid,
    wb.instrument_id,
    wb.block_id,
    'approved',
    now(),
    'universe_auto_import'
FROM with_blocks wb
ON CONFLICT (organization_id, instrument_id) DO UPDATE
SET
    block_id = EXCLUDED.block_id,
    approval_status = CASE
        -- Promote 'pending' (imports manuais sem decisão) → approved
        WHEN instruments_org.approval_status = 'pending'
            THEN 'approved'
        -- Preserve decisões manuais (approved/rejected mantêm)
        ELSE instruments_org.approval_status
    END,
    selected_at = GREATEST(instruments_org.selected_at, EXCLUDED.selected_at),
    source = CASE
        -- Se foi importado manualmente e agora qualifica, marca ambos via
        -- flag composta 'manual,auto' — preserve audit da origem.
        WHEN instruments_org.source = 'manual' THEN 'manual,auto'
        ELSE instruments_org.source
    END
RETURNING (xmax = 0) AS inserted;  -- TRUE se INSERT, FALSE se UPDATE
```

### C.2 — Pré-condições para o `ON CONFLICT` funcionar

```python
# Migration 0142 — garantir unique constraint composta
op.execute("""
    CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS
        uq_instruments_org_org_instrument
    ON instruments_org (organization_id, instrument_id);
""")
```

Se o índice já existir (provável — é query pattern óbvio), o `IF NOT EXISTS` é no-op. **Confirmar via** `\d instruments_org` antes da primeira rodada.

### C.3 — Batching e lock hygiene

```python
# backend/app/domains/wealth/workers/universe_auto_import.py (esqueleto)

UNIVERSE_AUTO_IMPORT_LOCK_ID = 900_103  # ver F1

async def run_universe_auto_import() -> dict[str, Any]:
    async with get_db_session() as db:
        # 1) Advisory lock global — serializa runs paralelos acidentais
        got_lock = await db.scalar(
            text("SELECT pg_try_advisory_lock(:lock)"),
            {"lock": UNIVERSE_AUTO_IMPORT_LOCK_ID},
        )
        if not got_lock:
            logger.warning("universe_auto_import.lock_busy")
            return {"skipped": True, "reason": "lock_busy"}

        try:
            orgs = await _fetch_active_orgs(db)
            total = {
                "orgs_processed": 0,
                "rows_added": 0,
                "rows_promoted": 0,
                "rows_skipped_aum": 0,
                "rows_skipped_inception": 0,
                "rows_skipped_coverage": 0,
                "rows_skipped_no_block": 0,
                "duration_ms": 0,
            }
            for org_id in orgs:
                # RLS context — transaction-scoped
                await db.execute(
                    text("SET LOCAL app.current_organization_id = :oid"),
                    {"oid": str(org_id)},
                )
                # Statement-level timeout defensivo
                await db.execute(text("SET LOCAL statement_timeout = '120s'"))

                started = time.monotonic()
                stats = await _qualify_and_upsert(db, org_id)
                await db.commit()
                elapsed = int((time.monotonic() - started) * 1000)

                total["orgs_processed"] += 1
                for k in ("rows_added", "rows_promoted",
                          "rows_skipped_aum", "rows_skipped_inception",
                          "rows_skipped_coverage", "rows_skipped_no_block"):
                    total[k] += stats.get(k, 0)
                total["duration_ms"] += elapsed

                await _write_audit_event(db, org_id, stats, elapsed)
                await db.commit()

            return total
        finally:
            await db.execute(
                text("SELECT pg_advisory_unlock(:lock)"),
                {"lock": UNIVERSE_AUTO_IMPORT_LOCK_ID},
            )
```

**Trade-offs:**

- **Sem `SKIP LOCKED`** no INSERT: o UPSERT é single-row por linha conflitante — lock wait é milissegundos. `SKIP LOCKED` só vale se a tabela tivesse alto write concurrency, o que `instruments_org` não tem (screener/builder fazem reads).
- **Janela de execução**: 04:00 UTC (após `universe_sync=900_070` 03:00 e antes do `global_risk_metrics=900_071` 05:00 — confirmar horários reais no scheduler). Dependência de ordem: `universe_sync` → `universe_auto_import` → `global_risk_metrics`.
- **Performance estimada**: ~14k candidatos, ~5k pós-filtro × N orgs. CTE qualifica → bloco único, não batch de 1000. Esperado: ≤ 30s por org em Timescale Cloud 4vCPU/16GB. Se > 60s, quebrar em chunks de 1000 via `ROW_NUMBER() % 14` LIMIT/OFFSET.
- **Lock contention com screener**: screener faz SELECT em `instruments_org` — PostgreSQL MVCC permite. O UPSERT pega `ROW EXCLUSIVE`, não bloqueia SELECT. Safe.

### C.4 — Counters de skip (implementar no código Python, não no SQL)

A query C.1 só retorna rows qualificadas. Para contar skips, rodar sub-queries leves antes do UPSERT:

```sql
-- Stats de skip — rodar 1× por org, logar e mandar pro audit_event
WITH base AS (
    SELECT
        COUNT(*) FILTER (WHERE COALESCE(
            muf.aum_usd,
            (iu.attributes->>'aum_usd')::numeric,
            0
        ) < $3) AS skipped_aum,
        COUNT(*) FILTER (WHERE (iu.attributes->>'inception_date')::date > $2
                           OR  iu.attributes->>'inception_date' IS NULL) AS skipped_inception,
        COUNT(*) FILTER (WHERE NOT EXISTS (
            SELECT 1 FROM nav_timeseries nt
            WHERE nt.instrument_id = iu.instrument_id
              AND nt.nav_date >= ($2 - INTERVAL '30 days')
            HAVING COUNT(*) >= $4
        )) AS skipped_coverage
    FROM instruments_universe iu
    LEFT JOIN mv_unified_funds muf ON muf.external_id = COALESCE(
        iu.attributes->>'series_id', iu.attributes->>'sec_cik', iu.isin, iu.ticker
    )
    WHERE iu.is_institutional = TRUE
      AND COALESCE(iu.attributes->>'sec_universe', '') IN (
          'registered_us', 'etf', 'ucits_eu', 'money_market'
      )
)
SELECT * FROM base;
```

---

## Section D — Audit & observabilidade

### D.1 — `audit_events` row por execução (não por row)

```sql
INSERT INTO audit_events (
    event_id, organization_id, actor, action, entity_type,
    entity_id, before, after, request_id, created_at
) VALUES (
    gen_random_uuid(),
    :org_id,
    'worker:universe_auto_import',
    'auto_import',
    'instruments_org',
    NULL,
    jsonb_build_object(
        'existing_auto',    :existing_auto_count,
        'existing_manual',  :existing_manual_count
    ),
    jsonb_build_object(
        'rows_added',             :rows_added,
        'rows_promoted',          :rows_promoted,
        'rows_skipped_aum',       :rows_skipped_aum,
        'rows_skipped_inception', :rows_skipped_inception,
        'rows_skipped_coverage',  :rows_skipped_coverage,
        'rows_skipped_no_block',  :rows_skipped_no_block,
        'duration_ms',            :duration_ms,
        'aum_floor_usd',          200000000,
        'cutoff_years',           5,
        'lock_id',                900103
    ),
    :request_id,
    now()
);
```

### D.2 — Métricas estruturadas (structlog, não StatsD)

```python
logger.info(
    "universe_auto_import.org_complete",
    org_id=str(org_id),
    rows_added=stats["rows_added"],
    rows_promoted=stats["rows_promoted"],
    rows_skipped_aum=stats["rows_skipped_aum"],
    rows_skipped_inception=stats["rows_skipped_inception"],
    rows_skipped_coverage=stats["rows_skipped_coverage"],
    rows_skipped_no_block=stats["rows_skipped_no_block"],
    duration_ms=elapsed_ms,
)
```

### D.3 — Alertas (Railway log-based)

- `duration_ms > 60000` por org → warn
- `rows_added == 0 AND existing_auto == 0` por 3 runs consecutivos → erro (worker quebrou)
- `rows_skipped_no_block > 500` → erro (catalog_classification está com gap; adicionar entries)

---

## Section E — Verification SQL (pós-deploy)

```sql
-- 1) Cobertura por org
SELECT
    organization_id,
    COUNT(*)                          AS total_instruments,
    COUNT(*) FILTER (WHERE source LIKE '%auto%')   AS auto_imported,
    COUNT(*) FILTER (WHERE source = 'manual')      AS manual_imported,
    MIN(selected_at)                  AS earliest_selection,
    MAX(selected_at)                  AS latest_selection
FROM instruments_org
GROUP BY organization_id
ORDER BY total_instruments DESC;

-- 2) Distribuição por block — sanity check (EQ vs FI vs Alt)
SELECT
    ab.asset_class,
    io.block_id,
    COUNT(*) AS n,
    COUNT(DISTINCT io.organization_id) AS n_orgs
FROM instruments_org io
JOIN allocation_blocks ab ON ab.block_id = io.block_id
WHERE io.source LIKE '%auto%'
GROUP BY ab.asset_class, io.block_id
ORDER BY ab.asset_class, n DESC;

-- 3) Orgs com 0 auto-imports — alerta!
SELECT o.id, o.name
FROM organizations o
LEFT JOIN instruments_org io
    ON io.organization_id = o.id AND io.source LIKE '%auto%'
WHERE io.id IS NULL
  AND o.is_active = TRUE;

-- 4) Instrumentos que deveriam qualificar mas foram skipados por falta de block
-- (debug do block_classification)
SELECT
    iu.instrument_id,
    iu.name,
    iu.ticker,
    iu.attributes->>'sec_universe' AS universe,
    iu.attributes->>'fund_subtype' AS fund_type,
    iu.asset_class,
    iu.attributes->>'strategy_label' AS strategy
FROM instruments_universe iu
LEFT JOIN block_classification bc
    ON bc.universe     = iu.attributes->>'sec_universe'
   AND bc.fund_type    = iu.attributes->>'fund_subtype'
   AND bc.asset_class  = iu.asset_class
WHERE iu.is_institutional = TRUE
  AND iu.is_active = TRUE
  AND COALESCE((iu.attributes->>'aum_usd')::numeric, 0) >= 200000000
  AND (iu.attributes->>'inception_date')::date <= CURRENT_DATE - INTERVAL '5 years'
  AND bc.block_id IS NULL
ORDER BY (iu.attributes->>'aum_usd')::numeric DESC NULLS LAST
LIMIT 50;

-- 5) Lock status (se suspeitar worker travado)
SELECT
    locktype, classid, objid, granted,
    pg_blocking_pids(pid) AS blocked_by
FROM pg_locks
WHERE locktype = 'advisory' AND objid = 900103;
```

**Resultado esperado (feliz):**
- Query 1: ~3k-5k auto_imported por org ativa. `manual_imported` > 0 só em orgs que pré-criaram universe manualmente.
- Query 2: distribuição ~60% equity / ~30% FI / ~10% alternatives (ordem de grandeza — varia com catalog composition).
- Query 3: 0 rows. Se retornar orgs ativas, worker falhou ou lock travou.
- Query 4: < 50 rows. Se > 500, faltam entries em `block_classification`.
- Query 5: 0 rows se worker não está rodando. 1 row `granted=true` se está.

---

## Checklist de merge (gate para o operador)

- [ ] `make migrate` em staging aplica `0139`, `0140`, `0141`, `0142` sem erro.
- [ ] `allocation_blocks` contém TODOS os block_ids referenciados em `block_classification` (especialmente `alternatives_private_credit` — pode não existir ainda; criar junto).
- [ ] Backup `backups/backup_pre_universe_cleanup_<TS>.sql.gz` gerado e `.sha256` gravado.
- [ ] Worker scheduler registra `universe_auto_import` em 04:00 UTC — confirmar em `backend/app/core/jobs/scheduler.py` (ou equivalente).
- [ ] Lock ID **900_103** não colide com nenhum outro lock — grep final `grep -rn "900_103\|900103" backend/`.
- [ ] CLAUDE.md atualizado: head `0142_instruments_org_unique_org_instrument` (ou último número usado), nova linha na tabela de workers, e correção do head `0131 → 0138+`.
- [ ] Teste integração em `backend/tests/wealth/test_universe_auto_import.py` cobre: (a) org sem universe prévio → 5k rows; (b) org com manual → promote pending; (c) org com rejected → preserve; (d) re-run idempotente (segundo run = 0 rows added).

---

## Brutal honesty — pontos onde não tive como confirmar

1. **`allocation_blocks` catalog completo**: o repo tem só 2 migrations seedando blocks (`0122`, `0126`). O `blocks.yaml` referenciado pelo comentário de `0126` não existe em `profiles/`. É provável que o seed real venha de script externo ou que blocks como `alternatives_private_credit`, `em_equity_large`, `eu_equity_large` não existam em produção. **Antes de `make migrate` com `0141`**, rodar `SELECT block_id FROM allocation_blocks ORDER BY block_id;` em prod e ajustar a lista em `_seed_block_classification()`.

2. **`portfolio_alerts` / `portfolio_views` / `rebalance_proposals` FKs**: não li os models. Confirmar com `\d` que são realmente CASCADE dependentes de `model_portfolios`. Se algum for `ON DELETE NO ACTION`, o TRUNCATE CASCADE do A.2 falha.

3. **TimescaleDB compression policy em `model_portfolio_nav`**: se há policy ativa (verificar via `SELECT * FROM timescaledb_information.jobs WHERE proc_name = 'policy_compression';`), chunks comprimidos podem falhar em `drop_chunks` sem `decompress_chunk` primeiro. Adicionar no A.2 se for o caso.

4. **Role BYPASSRLS em Timescale Cloud**: Timescale Cloud dá a role `tsdbadmin` mas a app user (`app` / whatever) pode não ter BYPASSRLS. `SET LOCAL row_security = off` só funciona com BYPASSRLS. Plano B: migration roda como superuser via `--user=tsdbadmin` no Alembic config dessa revisão específica.

5. **Semântica de `inception_date` em UCITS**: `esma_funds` não tem `inception_date` na view `mv_unified_funds` (hardcoded `NULL::date`). UCITS vão falhar o filtro de 5y inception até que `universe_sync` popule `attributes->>'inception_date'` a partir de ESMA (se o campo existir na fonte). Verificar antes de contar UCITS nos 5k esperados.

6. **`sec_universe` attribute não é universal**: `universe_sync` popula para ETF/MF/BDC/private. Para `money_market` e `ucits_eu` preciso confirmar no `universe_sync.py` (linhas não lidas) que o attribute é setado. Se não, query C.1 filtra-os out sem avisar.

7. **`nav_timeseries.instrument_id` coluna**: assumi que existe. Não li o model. Se a FK for `ticker` ou `isin` em vez de `instrument_id`, o JOIN em C.1 falha. Confirmar `\d nav_timeseries`.


---

# PR-A6 — Anexo Quant: Cardinalidade, Pre-Filter e Numerical Stability

> **Autor**: wealth-portfolio-quant-architect
> **Escopo**: dimensionamento quant do salto de universo ~200 → ~5.000 candidates institucionais após auto-import.
> **Contrato com o restante do PR**: este anexo assume que a arquitetura SQL/worker de auto-import + cleanup fica sob responsabilidade do db-architect e wealth-architect. Aqui tratamos exclusivamente do impacto sobre o pipeline de construção (Sprints 1–3 + PR-A1/A2/A3).

---

## 1. Brutal honesty sobre CLARABEL com N = 5.000

**Não é viável rodar o cascade direto em 5k candidates.** Análise:

- `backend/quant_engine/optimizer_service.py` implementa mean-variance + CVaR paramétrico (Cornish-Fisher) via CVXPY → CLARABEL. O QP canônico é `min ½ wᵀΣw − λ μᵀw` sujeito a simplex, block bounds, CVaR SOCP, single-fund cap, turnover L1.
- **Complexidade do interior-point CLARABEL** em problemas SOCP densos é empiricamente **O(n^{2.3 … 2.8})** por iteração × ~25–60 iterações. Para N = 200 (baseline atual) um solve típico fica em **0,4–1,2 s**. Extrapolando naive com expoente 2.5 de 200 → 5.000: fator (25)^{2.5} ≈ **3.125× mais lento** ⇒ **20–60 min por phase**. Com 4 phases do cascade + fallbacks SCS, o budget de 120 s do worker (lock 900_101) estoura em >10×.
- **Pressão de memória em Σ**: 5000² floats × 8 B = **200 MB** só para a covariância final. Ledoit-Wolf precisa de ao menos 3 cópias (sample Σ, target F, blended Σ_shrunk) ⇒ **~600 MB de peak**. Robust SOCP (Phase 1.5) materializa uncertainty set ellipsoidal (`L = chol(Σ)`) ⇒ mais 200 MB. O worker Railway Pro (~512 MB headroom) **OOM-eleva**.
- **Condicionamento κ(Σ)**: com N > T (5 anos × ~252 = 1.260 retornos diários), a sample covariance é **singular por construção** (rank ≤ T). Ledoit-Wolf + PSD clamp salva, mas κ(Σ_shrunk) cresce proporcionalmente a N/T ⇒ κ explode de ~1e2 (N=200) para ~1e4–1e5 (N=5000). O guardrail PR-A1 (`warn > 1e3, raise > 1e4`) **dispararia em todo build**.

**Conclusão:** pre-filter é **OBRIGATÓRIO**, não cosmético. Rodar CLARABEL em 5k crus viola três limites simultâneos (wall-clock, memória, κ(Σ)). O pre-filter também é a prática institucional correta — Markowitz (1952) original e Michaud (Resampled Efficiency, 1998) explicitamente recomendam screening multi-critério **antes** do otimizador porque mean-variance amplifica erro de estimação de retornos esperados em universos grandes.

---

## 2. Cascata de pre-filter (Layer 0 → 3)

Proposta: reduzir **5.000 → 200–400 candidates** antes de entregar ao `optimizer_service.py`. Cada layer tem telemetria SSE, audit trail agregado por motivo de exclusão e config-driven thresholds (ConfigService).

### Layer 0 — Mandate fit
- **Input**: ~5.000 candidates do universe auto-import.
- **Regra**: filtra por `asset_class` compatível com os `allocation_blocks` do mandate ativo (Balanced/Growth/Conservative). Bloco "Equity US LC" só recebe instrumentos com `asset_class ∈ {equity, etf_equity, mutual_fund_equity}` e `region ∈ {US, Global}`. Bloco "Fixed Income Corp IG" filtra por `asset_class ∈ {fixed_income, bond_fund}` e `credit_rating ≥ BBB-`.
- **Implementação**: reutilizar o policy engine existente em `vertical_engines/wealth/mandate_fit/` (não criar novo — o PR-A6 apenas wires ao caminho crítico).
- **Telemetria**: `universe_size_after_layer_0` SSE metric.
- **Redução esperada**: 5.000 → 2.000–3.000. Motivo de exclusão agregado: `{"mandate_mismatch": N, "region_mismatch": N, "rating_below_floor": N}`.

### Layer 1 — Quality screen (deterministic)
- **Input**: ~2.500 candidates.
- **Regra**: drop do **quartil inferior** em cada uma de três dimensões ortogonais, lidas de `fund_risk_metrics` (global, pré-computado pelo worker 900_071):
  - `manager_score` (percentile < 25 → drop) — scoring composite 6 componentes (PR-A3 baseline).
  - `sharpe_ratio_5y` (percentile < 25 → drop) — risk-adjusted return.
  - `max_drawdown_5y` (percentile > 75 do valor absoluto → drop) — drawdown control.
- **Opcional (config-gated)**: `cvar_95_conditional` floor se o regime atual é CRISIS ou RISK_OFF — força remoção de tail-risky funds quando o CVaR multiplier já é 0,70/0,85.
- **Por quê quartil, não score absoluto?** Por causa da memória `feedback_retrieval_thresholds.md`: thresholds absolutos não se sustentam entre corpus diferentes (aqui: manager_score é calibrado na distribuição do universo → quartil é invariante a recalibrações).
- **Redução esperada**: 2.500 → 1.200–1.500.

### Layer 2 — Diversification cap por block
- **Input**: ~1.400 candidates.
- **Regra**: top-K candidates por `allocation_block` (K default 100, configurável via ConfigService por profile). Ranking composto: `0.5·manager_score_percentile + 0.3·sharpe_percentile + 0.2·(1 − max_dd_percentile)`.
- **Por quê per-block?** Garante que se o mandate tem 8 blocks (Equity US/EM/EAFE, FI Corp/Sovereign, Alts, Cash), cada um retém representação — evita que um block com retornos historicamente altos monopolize o input do solver.
- **Redução esperada**: 1.400 → 600–800 (cap 100 × 8 blocks, menos blocks com < K elegíveis).

### Layer 3 — Correlation-aware dedup
- **Input**: ~700 candidates.
- **Regra**: cluster por correlação EWMA 1Y (janela ~252 retornos diários, λ = 0,97 consistente com PR-A1). Para cada cluster com pares `ρ > 0,95`, mantém top-1 por `manager_score`. Funds praticamente idênticos (p.ex. share classes do mesmo fundo que escaparam da dedup de CIK/series_id no auto-import, ou ETFs do mesmo benchmark com tracking error mínimo) são colapsados.
- **Algoritmo**: single-linkage hierarchical clustering com threshold 1 − ρ_cut = 0,05 → `scipy.cluster.hierarchy.fcluster`. Complexidade O(n²) em correlation matrix → 700² = 490k cells, <1 s.
- **Por quê não rodar isso sempre, não só no pre-filter?** Porque o CLARABEL com penalty de turnover e cap single-fund já lida bem com redundância quando N é pequeno; em N = 700, o cost/benefit inverte (factor model fica mal-condicionado).
- **Redução esperada**: 700 → **200–400 candidates finais**.

### Alinhamento com literatura institucional
- **Markowitz (1952)**: mean-variance assume inputs bem-estimados; pre-filter reduz erro de estimação de μ e Σ.
- **Michaud (1998) — Resampled Efficiency**: explicitamente argumenta que optimizers são error-maximizers em large N; screening prévio é parte do processo canônico.
- **Black-Litterman (1992)**: prior equilibrium + views funciona melhor quando views são expressáveis sobre um universo tratável (200–400 assets). 5k views seria absurdo operacionalmente — ver §4.
- **Qian / Hallerbach (Risk Parity literature)**: diversification cap por block é equivalente a impor prior de budget igualitário antes do solver, reduzindo sensibilidade a estimação.

---

## 3. Factor Model (PR-A3) com universo reduzido

O `build_fundamental_factor_returns` (`factor_model_service.py:35`) e `decompose_factors` (linha 380) fitam 8 fatores fundamentais. Dimensionamento:

- **8 factors × 400 funds = 3.200 loadings** → trivial (fit via OLS/Ridge em milissegundos).
- **Com 5.000 crus**: 40k loadings + residual covariance 5000×5000 = 200 MB. Mesmo tratando residual como **diagonal** (idiossincrático puro), o EWMA decay λ=0,97 sobre 5Y daily × 5k funds = **6,3M datapoints** em memória (~50 MB, OK), mas o tempo de fit cresce linearmente com N (5k → ~15 s) + PSD clamp O(N²) no κ(Σ_factor)+D ⇒ eliminaria o budget do worker.

**Recomendação firme**: factor model roda **DEPOIS** do pre-filter Layer 0–3, sobre os 200–400 candidates finais. Isso preserva PR-A3 sem refactor. Se no futuro quisermos ampliar (p.ex. para 1.000 candidates em mandatos "unconstrained"), o gate natural é diagonal residual + sparse Σ_factor — mas é trabalho para sprint separado.

**Numerical stability pós-pre-filter:**
- κ(Σ_factor) com N = 300, K = 8 fatores → condição controlada (~1e2 a 1e3).
- Eigenvalue floor PSD clamp `max(1e-10, 1e-8 · trace/N)`: com N = 300 e trace típico O(1e-2) → floor ~1e-13. Escala sem refactor.
- Ledoit-Wolf single-index shrinkage: O(n²) = 90k ops → <10 ms.

---

## 4. Black-Litterman views (PR-A2)

PR-A2 wirou multi-view BL com prior THBB (Theil-Henry Bayesian Black-Litterman). Decisões:

- **Views são por `instrument_id`** (coluna `portfolio_views.instrument_id`), não por block. Operacionalmente, IC não emite 5.000 views — emite visões sobre ~20–50 asset classes + convictions pontuais.
- **Com N = 5.000, o BL posterior seria dominado pelo prior** em ~4.950 assets sem view → equivalente a rodar só o prior. Pior: a equação de posterior de BL, `μ_post = (P·Ω⁻¹·P + τΣ⁻¹)⁻¹ · (P·Ω⁻¹·q + τΣ⁻¹·π)`, exige inverter matriz N×N. Em N = 5.000 = **inversão de 200 MB, O(N³) = 125B ops** ⇒ inviável.
- **Recomendação**: BL posterior roda **APÓS Layer 0–2** (antes do Layer 3 correlation-dedup é indiferente). Em N = 300–700 a inversão é 8–50 ms. Views que referenciam `instrument_id` fora do universo filtrado são **automaticamente descartadas com log WARN** (auditável) — consistente com prática institucional: view sobre fundo que falhou quality screen é sinal para o IC revisitar.
- **Prior THBB**: é equilibrium-based (CAPM-like) via reverse-optimization de benchmark weights. Funciona em qualquer N, mas `Σ_benchmark⁻¹` tem o mesmo problema de inversão em 5k — precisa rodar pós-pre-filter.

---

## 5. Stress tests

`stress_severity_service.py` + 4 cenários parametrizados (GFC, COVID, Taper, Rate Shock) em `POST /stress-test`. Dimensionamento:

- **Hoje**: 4 cenários × ~200 funds × 1.260 dates = 1M cells × 8 B = **8 MB por cenário**. Trivial.
- **Com 5k crus** (sem pre-filter): 4 × 5.000 × 1.260 = 25,2M cells × 8 B = **200 MB por cenário** ⇒ 800 MB total. OOM.
- **Com pre-filter + stress só sobre final weights (instruments with w ≠ 0 after optimization)**: tipicamente 15–40 assets com peso > 0,5% ⇒ **<2 MB por cenário**. Esta é a arquitetura correta e, pelo que vejo em `stress_severity_service.py`, **parece já ser o comportamento** (stress consome `optimized_weights`, não o universe). **Confirmar em §10 do action list**: auditar `stress_severity_service.py` para garantir que o input é a lista de fund_ids com peso, não o universe inteiro.

---

## 6. `fund_risk_metrics` coverage dependency

`_load_universe_funds` (`model_portfolios.py:2300`) exige `JOIN FundRiskMetrics WHERE organization_id IS NULL` (global metrics do worker 900_071). **Gate crítico** para o PR-A6:

- **Hoje**: worker `global_risk_metrics` cobre o subset de instruments em `instruments_universe` que efetivamente têm série NAV suficiente. Candidates com NAV < 3 anos ou gaps graves ficam sem row em `fund_risk_metrics` e caem do universo (o INNER JOIN os remove silenciosamente).
- **Pós-auto-import**: serão ~5.000 instruments qualificados (AUM ≥ 200M, track record ≥ 5y, is_institutional). Se o worker 900_071 não estiver preparado para processar 5k em uma única rodada diária, o auto-import cria instruments que **não aparecem no builder** por falta de metrics.
- **Coordenação com db-architect**: (i) estimar wall-clock do worker 900_071 em N = 5k (hoje ~200 em ~5–10 min → extrapolação linear ~2–4h em 5k, pode estourar janela noturna); (ii) decidir se o worker precisa de batching + sharding (p.ex. processar 500 por batch, paralelizar 4–8 workers); (iii) validar se `manager_score` está populado em 100% dos 5k antes de abrir o builder à produção.
- **Gate operacional**: o PR-A6 deve ter feature flag `AUTO_IMPORT_ENABLED` que só fica ON quando coverage de `fund_risk_metrics.manager_score IS NOT NULL` nos 5k ativos ≥ 95%. Métrica observável em dashboard.

---

## 7. Regime conditioning

`regime_service.py` aplica multiplicadores por regime (RISK_ON=1.0, NORMAL=1.0, RISK_OFF=0.85, CRISIS=0.70) em:
- CVaR limit (direto — reduz tolerância de tail risk em stress).
- Covariance shrinkage intensity (mais shrinkage em CRISIS — targets estável).
- Factor model window (curto em CRISIS, longo em RISK_ON).

Com pre-filter reduzindo para N = 200–400, **nada muda**: os multipliers aplicam sobre Σ_final (já filtered), não sobre universo cru. Comportamento preservado.

**Sinergia com Layer 1 (CVaR floor em CRISIS)**: quando o regime é CRISIS, Layer 1 pode ativar um filtro extra de `cvar_95_conditional > p90` (drop top-decile tail risk antes mesmo do solver). Isso antecipa o que o multiplier faria via CVaR constraint — remove candidates que forçariam infeasibility no cascade.

---

## 8. Numerical stability — tabela-resumo

| Gate | Limiar | N = 200 (hoje) | N = 5.000 (sem filter) | N = 300 (pós-filter) |
|------|--------|----------------|------------------------|----------------------|
| κ(Σ_shrunk) warn / raise | 1e3 / 1e4 | ~5e1 ✅ | ~1e4–1e5 🔴 | ~2e2 ✅ |
| Eigenvalue floor | `max(1e-10, 1e-8·tr/N)` | ~1e-13 ✅ | ~1e-14 (OK mas inútil — Σ singular) | ~1e-13 ✅ |
| Ledoit-Wolf RAM | 3× N² × 8B | 1 MB ✅ | 600 MB 🔴 | 2 MB ✅ |
| CLARABEL wall-clock por phase | budget ~25s | ~0,5s ✅ | 20–60 min 🔴 | ~1s ✅ |
| BL posterior inversion | O(N³) | 64 ms ✅ | ~12 min 🔴 | 220 ms ✅ |
| Factor fit (8 factors) | O(N·T·K) | <0,1s ✅ | ~15s 🟡 | 0,2s ✅ |

---

## 9. Performance budget — worker 120s (lock 900_101)

Distribuição realista pós-pre-filter (N_final = 300):

| Fase | Wall-clock esperado |
|------|---------------------|
| Pre-filter Layer 0–3 (SQL + correlation cluster) | 3–8 s |
| Statistical inputs (BL + LW + GARCH em 300 funds) | 15–25 s |
| Factor model (PR-A3, K=8, N=300) | 5–10 s |
| CLARABEL cascade Phase 1 → 1.5 → 2 → 3 (com SCS fallback) | 30–50 s |
| Stress tests (4 scenarios × ~30 active weights) | 5–10 s |
| Validation + advisor + Jinja narrative | 5–10 s |
| **Total** | **60–110 s** ✅ (dentro do budget com folga de 10–60 s) |

Sem pre-filter: blow-up garantido (CLARABEL sozinho ultrapassa 20 min em phase 1).

---

## 10. Recomendações concretas para o PR-A6

### Implementar
1. **Novo módulo `backend/vertical_engines/wealth/universe_filter/`** com:
   - `service.py` expondo `async def filter_universe(db, org_id, regime, mandate) -> UniverseFilterResult`.
   - `UniverseFilterResult` dataclass: `candidates: list[dict]`, `telemetry: LayerTelemetry` (size_after_each_layer + exclusion_reasons aggregated), `seed_hash: str` (para reprodutibilidade).
   - Helpers internos: `_layer0_mandate_fit`, `_layer1_quality_screen`, `_layer2_diversification_cap`, `_layer3_correlation_dedup`.
2. **Wire em `model_portfolios.py:2300`**: substituir o JOIN direto por chamada a `filter_universe(...)`. `_load_universe_funds` vira uma fachada thin que delega.
3. **Config defaults** em ConfigService (seed YAML em `calibration/wealth/universe_filter.yaml`):
   ```yaml
   layer1:
     manager_score_percentile_floor: 25
     sharpe_percentile_floor: 25
     max_dd_percentile_ceiling: 75
     crisis_cvar_floor_percentile: 90  # only in CRISIS regime
   layer2:
     max_candidates_per_block: 100
     ranking_weights: { manager_score: 0.5, sharpe: 0.3, drawdown: 0.2 }
   layer3:
     ewma_correlation_lambda: 0.97
     cluster_correlation_threshold: 0.95
     window_days: 252
   hard_cap_after_filter: 500  # safety net: never pass > 500 to solver
   ```
4. **Feature flag** `AUTO_IMPORT_ENABLED` (ConfigService) que só liga quando `fund_risk_metrics.manager_score IS NOT NULL` coverage ≥ 95% dos 5k instruments auto-imported.
5. **Telemetria SSE** no `construction_run_executor` — novo event type `universe_filter_progress` com payload `{layer, size_before, size_after, wall_clock_ms, top_exclusion_reasons}`.
6. **Audit trail agregado**: um único `AuditEvent` por construction run com `exclusions_by_layer = {layer0: {reason: count}, layer1: {...}, ...}`. Não emitir um event por candidate excluído (5k audit rows é ruído).

### Testar
1. **Teste de stress de cardinalidade** em `backend/tests/wealth/test_universe_filter_stress.py`:
   - Fixture: org com 5.000 rows em `instruments_org` + `fund_risk_metrics` sintéticos.
   - Assert: `len(candidates_after_filter) < 500`.
   - Assert: wall-clock `filter_universe(...)` < 10 s.
   - Assert: build completo (`POST /portfolios/{id}/build/start` + wait SSE done) < 90 s.
2. **Teste de determinismo**: mesma fixture + mesma seed → mesmo `candidates` (ordem e composição). Essencial para reprodutibilidade de audit trail.
3. **Teste de regime**: regime=CRISIS ativa o CVaR floor em Layer 1; regime=RISK_ON não ativa. Asserta counts de exclusão diferentes.
4. **Teste de degenerate cases**:
   - Org com 10 instruments (abaixo do Layer 2 cap) → Layer 2 é no-op, não crasha.
   - Org com instruments com `manager_score = NULL` → cai no Layer 1 com reason `missing_metrics`.
   - Mandate com 1 block só → Layer 2 não force diversification artificial.

### Auditar (não implementar no PR-A6, mas validar antes do merge)
1. **`stress_severity_service.py`**: confirmar que consome `optimized_weights` (30–50 funds), não universe. Se consumir universe, abrir ticket separado (stress refactor).
2. **Worker 900_071 (`global_risk_metrics`) scaling**: medir wall-clock atual, projetar em 5k, decidir batch/shard plan. Este é gate operacional do PR-A6.
3. **`black_litterman_service.py`**: confirmar que a matriz de inversão é feita sobre `filtered_universe`, não universe. Log assertion em dev.

### Documentar
1. Atualizar `docs/reference/portfolio-construction-reference-v2-post-quant-upgrade.md` com a cascata de pre-filter como **Stage 3.5** (entre Universe Loading e Statistical Inputs).
2. Atualizar `docs/reference/institutional-portfolio-lifecycle-reference.md` explicando que expansão do universe é **sem custo** ao IC porque o pre-filter é automático e auditável.

---

## 11. Tradeoffs honestos

**Ganhos:**
- Tractability: build em 60–110 s vs inviável.
- Numerical stability: κ(Σ) controlado, BL posterior inversível, LW shrinkage respiratório.
- Escalabilidade: universe pode crescer para 10k–20k no futuro sem alterar o solver — só ajustar Layer 2/3 caps.
- Alinhamento com literatura institucional (Michaud, Markowitz, Qian) — pre-filter não é hack, é prática canônica.

**Custos:**
- **Diversification perdida**: Layer 3 (correlation dedup) remove peers altamente correlacionados. Em edge cases, um fundo marginalmente superior pode ser preterido por outro com manager_score ligeiramente maior. **Mitigação**: threshold ρ_cut = 0,95 é conservador (apenas remove quase-duplicatas); o IC pode pin-overridar via views (BL expressa conviction que sobrepõe ranking).
- **Opportunity cost em Layer 1**: quartil inferior em manager_score é dropado. Funds que são "underdog" (low score mas high future alpha potential) são excluídos. **Mitigação**: isso é exatamente o que o IC quer — o builder é para seleção institucional disciplinada, não para discovery; discovery fica no Screener engine.
- **Config-sensitivity**: 4 layers × ~8 thresholds = 32 parâmetros configuráveis. Risco de tuning drift. **Mitigação**: ConfigService versiona (seed_hash no audit), calibration review trimestral no IC.
- **Worker 900_071 bottleneck**: auto-import depende de metrics estarem prontas. Se o worker atrasar, universe fica incompleto. **Mitigação**: feature flag + dashboard de coverage.

**Não-tradeoff**: isto não é um "MVP simplificado". É o caminho correto. Rodar CLARABEL em 5k crus seria overengineering na direção errada — um solver gigante e frágil resolvendo um problema mal-posto.

---

## 12. Checklist de aceitação Quant (para merge do PR-A6)

- [ ] `universe_filter/service.py` implementado com 4 layers + telemetria + determinismo.
- [ ] `_load_universe_funds` refatorado para delegar ao filter service (backward compatible se flag OFF — comportamento legado).
- [ ] Teste de stress com fixture 5k instruments passa em < 90 s wall-clock.
- [ ] Teste de determinismo (mesma seed → mesmo output) passa.
- [ ] Telemetria SSE `universe_filter_progress` emitida em todos os builds.
- [ ] Audit event com exclusions_by_layer escrito via `write_audit_event()`.
- [ ] κ(Σ_shrunk) medido empiricamente pós-filter < 1e3 em 95%+ dos builds (log histogram).
- [ ] Documentação `portfolio-construction-reference-v2` atualizada com Stage 3.5.
- [ ] Feature flag `AUTO_IMPORT_ENABLED` gated em coverage de `manager_score` ≥ 95%.
- [ ] Audit de `stress_severity_service.py` confirmando consumo de `optimized_weights`.
- [ ] Coordenação formal com db-architect sobre scaling do worker 900_071.
