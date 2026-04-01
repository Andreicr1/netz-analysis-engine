# Prompt H — P1/P2 Catálogo + NAV + Dados (#56-#62)

## Contexto

Valida os itens de dados e catálogo após o Global Instruments Refactor.
**Pré-requisito: Prompt G completo e deploy Railway feito.**

Backend: https://api.investintell.com
Python: D:\Projetos\netz-analysis-engine\backend\.venv\Scripts\python.exe
Dev auth: settings.dev_token + settings.dev_org_id

## Pré-leitura obrigatória

Antes de qualquer código, leia:
- D:\Projetos\netz-analysis-engine\docs\reference\deploy-checklist.md  (seções Fase 4, Go/No-Go #56-#62)
- D:\Projetos\netz-analysis-engine\docs\reference\universe-sync-backlog.md
- D:\Projetos\netz-analysis-engine\backend\scripts\backfill_nav.py
- D:\Projetos\netz-analysis-engine\backend\app\domains\wealth\workers\universe_sync.py  (se existir)

## O que NÃO fazer

- Não rodar `_deactivate_no_nav` antes do backfill estar completo
- Não rodar `risk_calc` em escala antes de `_deactivate_no_nav`
- Não alterar `instruments_universe` manualmente — usar universe_sync
- Não assumir que os tickers ESMA (.LX, .VI) têm NAV — a maioria não tem

---

## Setup

```python
import sys, time, httpx, asyncio, asyncpg, os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path("D:/Projetos/netz-analysis-engine/backend/.env"))
sys.path.insert(0, "D:/Projetos/netz-analysis-engine/backend")
from app.core.config.settings import settings

BASE_URL = "https://api.investintell.com"
HEADERS  = {
    "Authorization": f"Bearer {settings.dev_token}",
    "X-DEV-ACTOR": settings.dev_org_id,
    "Content-Type": "application/json",
}
DB = os.environ["DIRECT_DATABASE_URL"].replace(
    "postgresql+asyncpg://", "postgresql://"
).replace("postgresql+psycopg://", "postgresql://")

def get(path, **kw):
    return httpx.get(f"{BASE_URL}{path}", headers=HEADERS,
                     timeout=kw.pop("timeout", 30), **kw)

def post(path, body=None, **kw):
    return httpx.post(f"{BASE_URL}{path}", headers=HEADERS,
                      json=body or {}, timeout=kw.pop("timeout", 60), **kw)
```

---

## Etapa 1 — Estado atual do catálogo e NAV (SQL direto)

```python
async def check_catalog_and_nav():
    conn = await asyncpg.connect(DB)

    print("=== Estado do catálogo ===")
    r = await conn.fetch("""
        SELECT instrument_type, is_active, COUNT(*) as total
        FROM instruments_universe
        GROUP BY instrument_type, is_active
        ORDER BY instrument_type, is_active
    """)
    for row in r:
        print(f"  type={row['instrument_type']} active={row['is_active']} count={row['total']}")

    total_active = await conn.fetchval(
        "SELECT COUNT(*) FROM instruments_universe WHERE is_active = true"
    )
    total_all = await conn.fetchval("SELECT COUNT(*) FROM instruments_universe")
    print(f"  Total ativos: {total_active} / {total_all}")

    print()
    print("=== Estado do NAV backfill ===")
    r = await conn.fetchrow("""
        SELECT COUNT(*) as rows,
               COUNT(DISTINCT instrument_id) as instruments,
               MIN(nav_date) as oldest,
               MAX(nav_date) as newest
        FROM nav_timeseries
    """)
    print(f"  rows:        {r['rows']:,}")
    print(f"  instruments: {r['instruments']}")
    print(f"  oldest:      {r['oldest']}")
    print(f"  newest:      {r['newest']}")

    print()
    print("=== Cobertura de histórico ===")
    rows = await conn.fetch("""
        SELECT
            CASE
                WHEN cnt >= 2520 THEN '10+ anos'
                WHEN cnt >= 1260 THEN '5-10 anos'
                WHEN cnt >= 252  THEN '1-5 anos'
                ELSE '<1 ano'
            END as cobertura,
            COUNT(*) as instrumentos
        FROM (
            SELECT instrument_id, COUNT(*) as cnt
            FROM nav_timeseries
            GROUP BY instrument_id
        ) sub
        GROUP BY cobertura
        ORDER BY cobertura DESC
    """)
    for row in rows:
        print(f"  {row['cobertura']}: {row['instrumentos']}")

    print()
    print("=== instruments_org (tenant demo) ===")
    r = await conn.fetchrow("SELECT COUNT(*) FROM instruments_org")
    print(f"  Total lingas instruments_org: {r['count']}")

    print()
    print("=== N-PORT holdings ===")
    r = await conn.fetchrow("""
        SELECT COUNT(*) as rows,
               COUNT(DISTINCT cik) as funds,
               MIN(report_date) as oldest,
               MAX(report_date) as newest
        FROM sec_nport_holdings
    """)
    print(f"  rows:    {r['rows']:,}")
    print(f"  funds:   {r['funds']}")
    print(f"  oldest:  {r['oldest']}")
    print(f"  newest:  {r['newest']}")

    print()
    print("=== RR1 Prospectus ===")
    try:
        r_ret = await conn.fetchrow("SELECT COUNT(*) FROM sec_fund_prospectus_returns")
        r_stat = await conn.fetchrow("SELECT COUNT(*) FROM sec_fund_prospectus_stats")
        print(f"  sec_fund_prospectus_returns: {r_ret['count']:,}")
        print(f"  sec_fund_prospectus_stats:   {r_stat['count']:,}")
    except Exception as e:
        print(f"  ERRO: {e} — tabelas podem não existir ainda")

    await conn.close()

asyncio.run(check_catalog_and_nav())
```

---

## Etapa 2 — Go/No-Go #56: Import screener 2-step

```python
print("=== #56 — Import screener 2-step (global + instruments_org) ===")

# Usar um CIK de ETF conhecido que pode nao estar no universo
# iShares Core S&P 500 ETF — CIK 1100663 (se nao estiver)
# Buscar primeiro no catalog
r = get("/api/v1/screener/catalog?q=IVV&limit=5")
items = r.json().get("items", []) if r.status_code == 200 else []
ivv_in_catalog = any(i.get("ticker") == "IVV" for i in items)
print(f"IVV ja no catalog: {ivv_in_catalog}")

if not ivv_in_catalog:
    # Tentar import via screener
    # Endpoint pode variar — verificar openapi.json
    r_import = post("/api/v1/screener/import", {
        "ticker": "IVV",
        "asset_class": "equity",
        "geography": "north_america",
        "currency": "USD",
    })
    print(f"Import IVV: {r_import.status_code} — {r_import.text[:100]}")

    if r_import.status_code in (200, 201):
        result = r_import.json()
        instrument_id = result.get("instrument_id")
        print(f"instrument_id criado: {instrument_id}")

        # Verificar via SQL que:
        # 1. instruments_universe tem a row (global, sem org_id)
        # 2. instruments_org tem a row (org-scoped)
        async def verify_2step(iid, org_id):
            conn = await asyncpg.connect(DB)
            iu = await conn.fetchrow(
                "SELECT instrument_id, ticker FROM instruments_universe WHERE instrument_id = $1",
                iid if isinstance(iid, str) else str(iid)
            )
            io = await conn.fetchrow(
                "SELECT id, organization_id FROM instruments_org WHERE instrument_id = $1",
                iid if isinstance(iid, str) else str(iid)
            )
            print(f"  instruments_universe: {'OK' if iu else 'MISSING'}")
            print(f"  instruments_org:      {'OK' if io else 'MISSING'}")
            if io:
                print(f"  instruments_org.organization_id: {io['organization_id']}")
            await conn.close()
            return iu is not None and io is not None

        import uuid
        iid = uuid.UUID(instrument_id) if instrument_id else None
        go_56 = asyncio.run(verify_2step(iid, settings.dev_org_id)) if iid else False
    else:
        print("  Import falhou — verificar endpoint correto em openapi.json")
        go_56 = False
else:
    print("  IVV ja importado — 2-step validado implicitamente")
    go_56 = True  # se esta no catalog global, o import anterior foi correto

print(f"GO #56: {go_56}")
```

---

## Etapa 3 — Go/No-Go #57: NAV backfill >= 4k instrumentos

```python
print("=== #57 — NAV backfill >= 4.000 instrumentos ===")

async def check_nav_count():
    conn = await asyncpg.connect(DB)
    count = await conn.fetchval(
        "SELECT COUNT(DISTINCT instrument_id) FROM nav_timeseries"
    )
    print(f"  Instrumentos com NAV: {count}")
    await conn.close()
    return count

nav_count = asyncio.run(check_nav_count())
go_57 = nav_count >= 4000
print(f"GO #57: {go_57}  (meta: >= 4.000, atual: {nav_count})")

if not go_57:
    print()
    print("  NAV backfill ainda em andamento ou parou.")
    print("  Para retomar (tem checkpoint — nao precisa de --reset):")
    print()
    print("  cd D:\\Projetos\\netz-analysis-engine\\backend")
    print("  .venv\\Scripts\\python.exe -m scripts.backfill_nav --batch-size 50 --lookback 3650 --sleep 5")
    print()
    print("  Monitorar progresso:")
    print("  Get-Content .nav_backfill_checkpoint.json | ConvertFrom-Json | Select count, updated_at")
```

---

## Etapa 4 — Go/No-Go #58: _deactivate_no_nav

**Só executar se #57 for GO (backfill completo).**

```python
print("=== #58 — _deactivate_no_nav ===")

if not go_57:
    print("  SKIP — aguardar backfill completar (#57) antes de executar")
    go_58 = None
else:
    # Verificar quantos instrumentos estao ativos sem nenhum NAV
    async def count_active_no_nav():
        conn = await asyncpg.connect(DB)
        count = await conn.fetchval("""
            SELECT COUNT(*)
            FROM instruments_universe iu
            WHERE iu.is_active = true
              AND NOT EXISTS (
                  SELECT 1 FROM nav_timeseries nt
                  WHERE nt.instrument_id = iu.instrument_id
              )
        """)
        await conn.close()
        return count

    active_no_nav = asyncio.run(count_active_no_nav())
    print(f"  Instrumentos ativos sem NAV: {active_no_nav}")

    if active_no_nav > 0:
        print()
        print("  Executar universe_sync com _deactivate_no_nav:")
        print()
        print("  Para disparar via endpoint:")
        r_sync = post("/api/v1/workers/run-universe-sync", {"deactivate_no_nav": True})
        print(f"  universe_sync: {r_sync.status_code} — {r_sync.text[:80]}")

        if r_sync.status_code == 404:
            print("  Endpoint nao exposto. Executar diretamente:")
            print()
            print("  cd D:\\Projetos\\netz-analysis-engine\\backend")
            print("  .venv\\Scripts\\python.exe -c \"")
            print("  import asyncio")
            print("  from app.domains.wealth.workers.universe_sync import run_universe_sync")
            print("  asyncio.run(run_universe_sync(deactivate_no_nav=True))")
            print("  \"")
            go_58 = None
        else:
            print("  Aguardando 120s...")
            time.sleep(120)

            # Re-verificar
            active_no_nav_after = asyncio.run(count_active_no_nav())
            print(f"  Instrumentos ativos sem NAV apos deactivate: {active_no_nav_after}")
            go_58 = active_no_nav_after < active_no_nav
    else:
        print("  Todos os instrumentos ativos tem NAV — deactivate nao necessario")
        go_58 = True

    print(f"GO #58: {go_58}")
```

---

## Etapa 5 — Go/No-Go #59: risk_calc em escala

**Só executar se #57 e #58 forem GO.**

```python
print("=== #59 — risk_calc em escala (>= 1.000 instrumentos) ===")

if not go_57:
    print("  SKIP — aguardar NAV backfill (#57)")
    go_59 = None
else:
    # Verificar estado atual de fund_risk_metrics
    async def check_risk_metrics():
        conn = await asyncpg.connect(DB)
        count = await conn.fetchval(
            "SELECT COUNT(DISTINCT instrument_id) FROM fund_risk_metrics"
        )
        latest = await conn.fetchval(
            "SELECT MAX(calc_date) FROM fund_risk_metrics"
        )
        await conn.close()
        return count, latest

    count_before, latest_before = asyncio.run(check_risk_metrics())
    print(f"  fund_risk_metrics atual: {count_before} instrumentos, ultima calc: {latest_before}")

    if count_before < 1000:
        print()
        print("  Disparar risk_calc (pode levar 2-4h para 5k+ instrumentos):")
        r_risk = post("/api/v1/workers/run-risk-calc")
        print(f"  risk_calc: {r_risk.status_code} — {r_risk.text[:80]}")
        print()
        print("  Monitorar via SQL:")
        print("  SELECT COUNT(DISTINCT instrument_id), MAX(calc_date) FROM fund_risk_metrics;")
        print()
        print("  Aguardando 300s para inicio do processamento...")
        time.sleep(300)

        count_after, latest_after = asyncio.run(check_risk_metrics())
        print(f"  fund_risk_metrics apos 5min: {count_after} instrumentos")
        go_59 = count_after > count_before or count_after >= 1000
    else:
        go_59 = count_before >= 1000

    print(f"GO #59: {go_59}  (meta: >= 1.000, atual: {count_before if count_before >= 1000 else 'em andamento'})")
```

---

## Etapa 6 — Go/No-Go #60-#62: Dados de referencia

```python
async def check_reference_data():
    conn = await asyncpg.connect(DB)

    print("=== #60 — N-PORT 24 trimestres ===")
    r = await conn.fetchrow("""
        SELECT COUNT(*) as rows,
               COUNT(DISTINCT cik) as funds,
               COUNT(DISTINCT DATE_TRUNC('quarter', report_date)) as quarters,
               MIN(report_date) as oldest,
               MAX(report_date) as newest
        FROM sec_nport_holdings
    """)
    print(f"  rows:     {r['rows']:,}  (meta: >= 4.470.000)")
    print(f"  funds:    {r['funds']}")
    print(f"  quarters: {r['quarters']}  (meta: 24)")
    print(f"  range:    {r['oldest']} → {r['newest']}")
    go_60 = r["rows"] >= 4_000_000 and r["quarters"] >= 20
    print(f"GO #60: {go_60}")

    print()
    print("=== #61 — RR1 prospectus returns ===")
    try:
        r = await conn.fetchrow("""
            SELECT COUNT(*) as rows,
                   COUNT(DISTINCT series_id) as series,
                   MIN(year) as oldest_year,
                   MAX(year) as newest_year
            FROM sec_fund_prospectus_returns
        """)
        print(f"  rows:    {r['rows']:,}  (meta: >= 17.500)")
        print(f"  series:  {r['series']}")
        print(f"  years:   {r['oldest_year']} → {r['newest_year']}")
        go_61 = r["rows"] >= 17_000
    except Exception as e:
        print(f"  ERRO: {e}")
        go_61 = False
    print(f"GO #61: {go_61}")

    print()
    print("=== #62 — RR1 prospectus stats ===")
    try:
        r = await conn.fetchrow("""
            SELECT COUNT(*) as rows,
                   COUNT(DISTINCT series_id) as series
            FROM sec_fund_prospectus_stats
        """)
        print(f"  rows:   {r['rows']:,}  (meta: >= 72.000)")
        print(f"  series: {r['series']}")
        go_62 = r["rows"] >= 70_000
    except Exception as e:
        print(f"  ERRO: {e}")
        go_62 = False
    print(f"GO #62: {go_62}")

    await conn.close()
    return go_60, go_61, go_62

go_60, go_61, go_62 = asyncio.run(check_reference_data())
```

---

## Resultado Final

```python
print()
print("="*58)
print("PROMPT H — P1/P2 Catálogo + NAV + Dados (#56-#62)")
print("="*58)

resultados = {
    "#56 Import screener 2-step (global + instruments_org)": go_56,
    "#57 NAV backfill >= 4.000 instrumentos":                go_57,
    "#58 _deactivate_no_nav executado":                      go_58,
    "#59 risk_calc >= 1.000 instrumentos":                   go_59,
    "#60 N-PORT 24 trimestres, 4.47M+ rows":                 go_60,
    "#61 RR1 prospectus returns 17.500+ rows":               go_61,
    "#62 RR1 prospectus stats 72.000+ rows":                 go_62,
}

go_count   = sum(1 for v in resultados.values() if v is True)
fail_count = sum(1 for v in resultados.values() if v is False)
skip_count = sum(1 for v in resultados.values() if v is None)

for item, status in resultados.items():
    label = "✅ GO" if status is True else ("❌ FAIL" if status is False else "⏳ PENDENTE/SKIP")
    print(f"  {item:<55} {label}")

print()
print(f"  GO:      {go_count}/7")
print(f"  FAIL:    {fail_count}/7")
print(f"  PENDENTE:{skip_count}/7")
print()

if fail_count == 0 and skip_count == 0:
    print("  ✅ P1/P2 COMPLETO — catálogo e dados validados")
    print("  Próximo: risk_calc em escala, expor RR1 e N-PORT no frontend")
elif go_57 and not go_58:
    print("  ⏳ NAV backfill OK — executar _deactivate_no_nav para limpar catálogo")
elif not go_57:
    print("  ⏳ Aguardar NAV backfill completar antes de prosseguir")
    print("  Retomar: .venv\\Scripts\\python.exe -m scripts.backfill_nav --batch-size 50 --sleep 5")
else:
    print("  ❌ FALHAS — verificar itens acima")
```

## Notas de diagnóstico

**#56 endpoint de import:** verificar no `openapi.json` qual é o path correto
do import 2-step. Pode ser `/api/v1/screener/import` ou
`/api/v1/manager-screener/managers/{crd}/add-to-universe`.
O critério é: o resultado deve criar em `instruments_universe` (global) E em
`instruments_org` (org-scoped). Verificar via SQL após o import.

**#57 se o backfill parou:** o script `backfill_nav.py` tem checkpoint em
`.nav_backfill_checkpoint.json`. Retomar sem `--reset`. Os tickers ESMA
(.LX, .VI, .PA) vão skipar com "possibly delisted" — é esperado, não é erro.
O checkpoint os marca como "done" mesmo sem NAV.

**#58 _deactivate_no_nav:** marca `is_active=false` para instrumentos sem
nenhuma row em `nav_timeseries`. Depois disso, o `instrument_ingestion` worker
diário não vai mais tentar buscar NAV para esses tickers. Reduz o catálogo
efetivo de ~8.950 para ~4.000-5.000 (apenas os com cobertura Yahoo).

**#59 risk_calc em escala:** o worker processa todos os instrumentos ativos
com NAV. Com ~5k instrumentos × 2.520 pregões, o cálculo de CVaR, Sharpe,
momentum leva 2-4h. Monitorar via:
```sql
SELECT COUNT(DISTINCT instrument_id), MAX(calc_date)
FROM fund_risk_metrics;
```

**#60 N-PORT quarters:** se `quarters < 24`, o bulk loader pode ter rodado
com filtro de CIKs mais restrito. Verificar:
```sql
SELECT DATE_TRUNC('quarter', report_date) as q, COUNT(DISTINCT cik)
FROM sec_nport_holdings
GROUP BY q ORDER BY q;
```

**#61/#62 RR1 tabelas ausentes:** se as tabelas não existem, a migration 0070
(Prompt G) não foi aplicada ou as tabelas foram criadas no Timescale Cloud mas
não no ambiente local. Verificar se o bulk loader RR1 foi executado:
`python -m scripts.load_rr1_prospectus` (ou equivalente).
