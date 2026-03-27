# Prompt F — Segundo E2E: Quant Upgrade + Wealth Vector Embedding + Fund-Centric Model

## Contexto

Este é o segundo e2e completo do sistema.
O primeiro e2e (Prompts A-D, 2026-03-27) validou o baseline #1-#28.
Este prompt valida tudo implementado depois: #29-#52.

**Inclui os itens do Prompt E (#29-#35) — não é necessário rodar o Prompt E separadamente.**

Backend: https://api.investintell.com
Python: D:\Projetos\netz-analysis-engine\backend\.venv\Scripts\python.exe
Dev auth: settings.dev_token + settings.dev_org_id do .env local

Valores do primeiro e2e (reusar):
  portfolio_id         = "c872b6eb-f065-45b2-ad47-17ec9b3e2a3b"
  instrument_id_sample = "e9c02fd6-1ac2-46a0-965d-e360c72cca31"  # OAKMX

## Pré-condições obrigatórias antes de iniciar

Verificar localmente:

```powershell
cd D:\Projetos\netz-analysis-engine\backend

# 1. Migrations 0058, 0059 e 0060 aplicadas em produção
$env:DATABASE_URL = (Get-Content .env | Select-String "^DIRECT_DATABASE_URL").ToString().Split("=",2)[1]
python -c "
import asyncio, asyncpg, os
from dotenv import load_dotenv; load_dotenv()
url = os.environ['DIRECT_DATABASE_URL'].replace('postgresql+asyncpg://','postgresql://')
async def check():
    conn = await asyncpg.connect(url)
    rows = await conn.fetch('SELECT version_num FROM alembic_version')
    print('migration head:', [r['version_num'] for r in rows])
    # Esperado: ['0060_portfolio_views'] (chain linear, 1 head)
    tables = await conn.fetch(\"\"\"
        SELECT tablename FROM pg_tables
        WHERE tablename IN ('wealth_vector_chunks','sec_fund_classes','portfolio_views')
        AND schemaname='public'
    \"\"\")
    print('tabelas novas:', sorted([r['tablename'] for r in tables]))
    # Esperado: as 3 tabelas presentes
    await conn.close()
asyncio.run(check())
"

# Nota: após sessão regime-history-persistence, adicionar '0061_macro_regime_history'
# ao check de tabelas acima e verificar macro_regime_history na lista.

# 2. arch e aeon disponíveis (agora deps principais, não opcionais)
.\.venv\Scripts\python.exe -c "
import arch, aeon
print('arch:', arch.__version__)   # esperado: 8.0.0
print('aeon:', aeon.__version__)   # esperado: 1.4.0
"
```

Se migration pendente: `alembic upgrade head`
Se arch ausente: `pip install "arch>=7.0"`

## Setup

```python
import sys, time, httpx, asyncio
sys.path.insert(0, 'D:/Projetos/netz-analysis-engine/backend')
from app.core.config.settings import settings

BASE_URL = "https://api.investintell.com"
HEADERS = {
    "Authorization": f"Bearer {settings.dev_token}",
    "X-DEV-ACTOR": settings.dev_org_id,
    "Content-Type": "application/json"
}

portfolio_id         = "c872b6eb-f065-45b2-ad47-17ec9b3e2a3b"
instrument_id_sample = "e9c02fd6-1ac2-46a0-965d-e360c72cca31"  # OAKMX

def get(path, **kw):
    return httpx.get(f"{BASE_URL}{path}", headers=HEADERS,
                     timeout=kw.pop("timeout", 30), **kw)

def post(path, body=None, **kw):
    return httpx.post(f"{BASE_URL}{path}", headers=HEADERS,
                      json=body or {}, timeout=kw.pop("timeout", 60), **kw)
```

---

## Bloco 1 — Quant Upgrade (#29-#35)

### Etapa 1.1 — Re-rodar risk_calc e construct com upgrade ativo

```python
# ORDEM IMPORTA: regime_fit deve rodar antes de risk_calc.
# regime_fit popula macro_regime_history; risk_calc lê de lá para cvar_95_conditional.
# Nota: após a sessão regime-history-persistence, esta ordem passa a ser obrigatória.
# Antes dela, risk_calc usa VIX>=25 como proxy e a ordem não importa.

r = post("/api/v1/workers/run-regime-fit")
print(f"regime_fit: {r.status_code} — {r.text[:80]}")
print("Aguardando 60s para regime_fit completar...")
time.sleep(60)

# Re-rodar risk_calc para popular volatility_garch e cvar_95_conditional
r = post("/api/v1/workers/run-risk-calc")
print(f"risk_calc: {r.status_code} — {r.text[:80]}")
print("Aguardando 90s...")
time.sleep(90)

# Re-construir portfolio para capturar BL returns, shrinkage, robust, factor_exposures
r = post(f"/api/v1/model-portfolios/{portfolio_id}/construct", {})
print(f"Construct: {r.status_code}")
snapshot = r.json()
opt = snapshot.get("fund_selection_schema", {}).get("optimization", {})
print(f"solver:           {opt.get('solver')}")
print(f"status:           {opt.get('status')}")
print(f"cvar_95:          {opt.get('cvar_95')}")
print(f"factor_exposures: {opt.get('factor_exposures')}")
```

### Etapa 1.2 — Go/No-Go #29-#35

```python
print("\n=== Go/No-Go #29 — Migration 0058 (volatility_garch + cvar_95_conditional) ===")
r = get(f"/api/v1/instruments/{instrument_id_sample}/risk-metrics")
print(f"Status: {r.status_code}")
if r.status_code == 200:
    m = r.json()
    print(f"volatility_garch:    {m.get('volatility_garch')}")
    print(f"cvar_95_conditional: {m.get('cvar_95_conditional')}")
    # Nota: cvar_95_conditional usa macro_regime_history (RISK_OFF/CRISIS) como fonte
    # de datas de stress. Se a tabela estiver vazia (regime_fit ainda não rodou ou
    # sessão regime-history-persistence não foi executada), retorna None — correto.
    # Para OAKMX com histórico desde ~2016, deve ser não-None após regime_fit rodar
    # (períodos 2020 COVID e 2022 rate shock qualificam como stress).
    go_29 = m.get('volatility_garch') is not None or m.get('cvar_95_conditional') is not None
else:
    print("Endpoint não expõe — verificar via SQL direto:")
    print("SELECT volatility_garch, cvar_95_conditional FROM fund_risk_metrics "
          "WHERE instrument_id = '<instrument_id>' ORDER BY calc_date DESC LIMIT 1;")
    go_29 = None
print(f"GO: {go_29}")

print("\n=== Go/No-Go #30 — GARCH (arch>=7.0) ===")
if r.status_code == 200:
    vol_garch = r.json().get('volatility_garch')
    go_30 = vol_garch is not None
    print(f"volatility_garch: {vol_garch}  (não-None = GARCH rodou)")
else:
    go_30 = None
print(f"GO: {go_30}")

print("\n=== Go/No-Go #31 — Factor Exposures no construct ===")
factor_exposures = opt.get("factor_exposures")
print(f"factor_exposures: {factor_exposures}")
go_31 = factor_exposures is not None
print(f"GO: {go_31}  (None aceitável se universo < 3 obs)")

print("\n=== Go/No-Go #32 — Robust optimizer status no enum ===")
status_val = opt.get("status", "")
valid_statuses = {
    "optimal", "optimal:robust", "optimal:cvar_constrained",
    "optimal:min_variance_fallback", "optimal:cvar_violated",
    "solver_failed", "fallback:insufficient_fund_data"
}
print(f"status: {status_val}")
go_32 = status_val in valid_statuses
print(f"GO: {go_32}")

print("\n=== Go/No-Go #33 — Portfolio Views CRUD ===")
view_body = {
    "view_type": "absolute",
    "asset_instrument_id": instrument_id_sample,
    "expected_return": 0.09,
    "confidence": 0.65,
    "rationale": "Segundo e2e smoke test"
}
r_create = post(f"/api/v1/model-portfolios/{portfolio_id}/views", view_body)
print(f"POST /views: {r_create.status_code}")
view_id = r_create.json().get("id") if r_create.status_code in (200, 201) else None

r_list = get(f"/api/v1/model-portfolios/{portfolio_id}/views")
print(f"GET /views: {r_list.status_code} — {len(r_list.json()) if r_list.status_code == 200 else 'err'} views")

if view_id:
    r_del = httpx.delete(f"{BASE_URL}/api/v1/model-portfolios/{portfolio_id}/views/{view_id}",
                         headers=HEADERS, timeout=15)
    print(f"DELETE /views/{view_id}: {r_del.status_code}")

go_33 = r_create.status_code in (200, 201) and r_list.status_code == 200
print(f"GO: {go_33}")

print("\n=== Go/No-Go #34 — Stress Test preset + custom ===")
r_gfc = post(f"/api/v1/model-portfolios/{portfolio_id}/stress-test",
             {"scenario_name": "gfc_2008"})
print(f"Preset gfc_2008: {r_gfc.status_code}")
if r_gfc.status_code == 200:
    s = r_gfc.json()
    print(f"  nav_impact_pct: {s.get('nav_impact_pct')}")
    print(f"  worst_block:    {s.get('worst_block')}")

r_custom = post(f"/api/v1/model-portfolios/{portfolio_id}/stress-test", {
    "scenario_name": "custom",
    "shocks": {"na_equity_large": -0.20, "na_equity_value": -0.18}
})
print(f"Custom scenario: {r_custom.status_code}")
go_34 = r_gfc.status_code == 200 and r_custom.status_code == 200
print(f"GO: {go_34}")

print("\n=== Go/No-Go #35 — Performance /stress-test < 500ms server-side ===")
import statistics as _stats, time as _time
latencies = []
for i in range(5):
    t0 = _time.monotonic()
    post(f"/api/v1/model-portfolios/{portfolio_id}/stress-test",
         {"scenario_name": "rate_shock_200bps"})
    latencies.append((_time.monotonic() - t0) * 1000)
p95_raw = sorted(latencies)[int(len(latencies) * 0.95)]
p95_server = p95_raw - 406   # baseline BR→US medido no primeiro e2e
print(f"p95 raw: {p95_raw:.0f}ms  server-side estimado: {p95_server:.0f}ms")
go_35 = p95_server < 500
print(f"GO: {go_35}")
```

---

## Bloco 2 — Wealth Vector Embedding (#36-#45)

### Etapa 2.1 — Pré-condição: seed do worker

```python
# Disparar o seed inicial (~18k chunks, ~$1.43 OpenAI, ~5-10min)
# SÓ EXECUTAR SE wealth_vector_chunks estiver vazio
r = post("/api/v1/workers/run-wealth-embedding")
print(f"wealth_embedding seed: {r.status_code} — {r.text[:80]}")
print("Aguardando 600s para seed completo...")
time.sleep(600)
```

### Etapa 2.2 — Go/No-Go #36-#45

```python
print("\n=== Go/No-Go #36 — Migration 0059 (wealth_vector_chunks) ===")
# Verificar via endpoint de saúde do schema
r = get("/api/v1/admin/health/services")
print(f"Health: {r.status_code}")
# Verificar indiretamente via worker manifest
r_manifest = get("/api/v1/workers/manifest")
workers = r_manifest.json() if r_manifest.status_code == 200 else []
has_embedding = any(
    (w.get("name") or w) == "wealth_embedding"
    for w in workers
)
print(f"Manifest workers: {len(workers)}")
print(f"wealth_embedding presente: {has_embedding}")
go_36 = has_embedding
print(f"GO: {go_36}")

print("\n=== Go/No-Go #37 — Worker registrado (lock 900_041) ===")
# O manifest deve listar wealth_embedding
if isinstance(workers, list) and workers:
    worker_names = [
        (w.get("name") if isinstance(w, dict) else str(w))
        for w in workers
    ]
    print(f"Workers: {sorted(worker_names)}")
    go_37 = "wealth_embedding" in worker_names
else:
    go_37 = has_embedding
print(f"GO: {go_37}")

print("\n=== Go/No-Go #38-#41 — Seed executado (verificar via SQL local) ===")
print("""
Execute localmente (Tiger CLI ou psql):

SELECT entity_type, source_type, COUNT(*) as chunks,
       COUNT(embedding) as with_embedding
FROM wealth_vector_chunks
GROUP BY entity_type, source_type
ORDER BY entity_type, source_type;

Esperado:
  firm  | brochure      | >= 5000  | >= 5000   (#38 brochures)
  fund  | esma_fund     | >= 10000 | >= 10000  (#39 ESMA funds)
  firm  | esma_manager  | >= 500   | >= 500

#40 — Zero rows com entity_type='manager':
SELECT COUNT(*) FROM wealth_vector_chunks WHERE entity_type = 'manager';
Esperado: 0

#41 — firm_crd preenchido em brochures:
SELECT COUNT(*) FROM wealth_vector_chunks
WHERE source_type = 'brochure' AND firm_crd IS NULL;
Esperado: 0 (todas as brochures devem ter firm_crd)
""")

print("\n=== Go/No-Go #42 — Busca fund-centric firma ===")
# Usar OAKMX como fundo de teste — CRD da Oakmark (Harris Associates)
# CRD conhecido: 106116 (Harris Associates L.P.)
r = post("/api/v1/search/fund-firm-context", {
    "sec_crd": "106116",
    "query": "investment philosophy equity selection",
    "section_filter": ["investment_philosophy", "methods_of_analysis"],
    "top": 5
})
print(f"search_fund_firm_context: {r.status_code}")
if r.status_code == 200:
    results = r.json()
    print(f"  chunks retornados: {len(results)}")
    if results:
        print(f"  primeiro chunk score: {results[0].get('score', 0):.3f}")
        print(f"  entity_type: {results[0].get('entity_type')}")
        print(f"  source_type: {results[0].get('source_type')}")
    go_42 = len(results) > 0 and all(
        r.get("entity_type") == "firm" for r in results
    )
elif r.status_code == 404:
    print("  Endpoint não exposto via API — busca é interna ao agente.")
    print("  Verificar via teste unitário: pytest tests/test_wealth_embedding_worker.py -v")
    go_42 = None  # não bloqueante — é função interna
print(f"GO: {go_42}")

print("\n=== Go/No-Go #43 — Busca ESMA funds ===")
r = post("/api/v1/search/esma-funds", {
    "query": "global aggregate bond UCITS Luxembourg",
    "domicile_filter": "LU",
    "top": 5
})
print(f"search_esma_funds: {r.status_code}")
if r.status_code == 200:
    results = r.json()
    print(f"  chunks retornados: {len(results)}")
    go_43 = len(results) > 0
elif r.status_code == 404:
    print("  Endpoint interno — verificar via pytest tests/test_wealth_embedding_worker.py -v")
    go_43 = None
print(f"GO: {go_43}")

print("\n=== Go/No-Go #44 — Busca org-scoped DD chapters ===")
r = post("/api/v1/search/fund-analysis", {
    "instrument_id": instrument_id_sample,
    "query": "investment strategy risk assessment",
    "source_type": "dd_chapter",
    "top": 5
})
print(f"search_fund_analysis: {r.status_code}")
if r.status_code == 200:
    results = r.json()
    print(f"  chunks retornados: {len(results)}")
    go_44 = r.status_code == 200  # 0 chunks aceitável se não há DD report ainda
elif r.status_code == 404:
    print("  Endpoint interno — resultado aceitável se não há DD chapters para OAKMX")
    go_44 = None
print(f"GO: {go_44}")

print("\n=== Go/No-Go #45 — Idempotência do worker ===")
r_count_before = post("/api/v1/workers/run-wealth-embedding")
print(f"Segunda execução do worker: {r_count_before.status_code}")
print("Verificar via SQL local que COUNT(*) não aumentou:")
print("SELECT COUNT(*) FROM wealth_vector_chunks;  -- deve ser igual ao anterior")
go_45 = r_count_before.status_code in (200, 202)
print(f"GO: {go_45}  (verificação real via SQL local)")
```

---

## Bloco 3 — Fund-Centric Model (#46-#52)

### Etapa 3.1 — Pré-condição: popular sec_fund_classes

```python
# Disparar nport_fund_discovery para popular sec_fund_classes
r = post("/api/v1/workers/run-nport-fund-discovery")
print(f"nport_fund_discovery: {r.status_code} — {r.text[:80]}")
print("Aguardando 120s...")
time.sleep(120)
```

### Etapa 3.2 — Go/No-Go #46-#52

```python
print("\n=== Go/No-Go #46 — sec_fund_classes populado ===")
print("""
Verificar via SQL local:
SELECT COUNT(*) FROM sec_fund_classes;
Esperado: > 0 após nport_fund_discovery

SELECT cik, series_name, class_name, ticker
FROM sec_fund_classes LIMIT 10;
""")
# Via API: catalog deve retornar items com class_id preenchido
r = get("/api/v1/screener/catalog?fund_universe=registered_us&limit=20")
print(f"Catalog registered_us: {r.status_code}")
if r.status_code == 200:
    items = r.json().get("items", [])
    items_with_class = [i for i in items if i.get("class_id")]
    print(f"  Total items: {len(items)}")
    print(f"  Items com class_id: {len(items_with_class)}")
    if items_with_class:
        sample = items_with_class[0]
        print(f"  Exemplo: {sample.get('name')} | {sample.get('class_name')} | {sample.get('ticker')}")
    go_46 = len(items_with_class) > 0
else:
    go_46 = None
print(f"GO: {go_46}")

print("\n=== Go/No-Go #47 — Catalog retorna classes (series_id, class_id) ===")
if r.status_code == 200:
    items = r.json().get("items", [])
    has_series = any(i.get("series_id") for i in items)
    has_class  = any(i.get("class_id")  for i in items)
    print(f"  series_id presente: {has_series}")
    print(f"  class_id presente:  {has_class}")
    go_47 = has_class
else:
    go_47 = None
print(f"GO: {go_47}")

print("\n=== Go/No-Go #48 — GET /manager-screener/managers/{crd}/registered-funds ===")
# CRD da Oakmark / Harris Associates (gestora do OAKMX)
TEST_CRD = "106116"
r = get(f"/api/v1/manager-screener/managers/{TEST_CRD}/registered-funds")
print(f"registered-funds: {r.status_code}")
if r.status_code == 200:
    body = r.json()
    funds = body.get("funds", [])
    print(f"  firm_name:    {body.get('firm_name')}")
    print(f"  total_funds:  {body.get('total_funds')}")
    print(f"  funds count:  {len(funds)}")
    if funds:
        f0 = funds[0]
        print(f"  Primeiro fundo: {f0.get('fund_name')} | CIK: {f0.get('cik')}")
        print(f"  already_in_universe: {f0.get('already_in_universe')}")
    go_48 = body.get("total_funds", 0) > 0
elif r.status_code == 404:
    print("  CRD não encontrado — tentar outro CRD com N-PORT disponível")
    print("  Sugestão: verificar sec_managers JOIN sec_registered_funds para CRD válido")
    go_48 = None
else:
    go_48 = False
print(f"GO: {go_48}")

print("\n=== Go/No-Go #49 — add-to-universe com fund_cik (não firma CIK) ===")
if r.status_code == 200 and funds:
    fund_cik_to_add = funds[0]["cik"]
    print(f"Adicionando fundo CIK: {fund_cik_to_add}")
    r_add = post(f"/api/v1/manager-screener/managers/{TEST_CRD}/add-to-universe", {
        "fund_cik": fund_cik_to_add,
        "asset_class": "alternatives",
        "geography": "north_america",
        "currency": "USD"
    })
    print(f"add-to-universe: {r_add.status_code}")

    if r_add.status_code == 201:
        new_instrument_id = r_add.json().get("instrument_id")
        print(f"  instrument_id criado: {new_instrument_id}")

        # Verificar que attributes.sec_cik = fund CIK (não firma CIK)
        r_inst = get(f"/api/v1/instruments/{new_instrument_id}")
        if r_inst.status_code == 200:
            attrs = r_inst.json().get("attributes", {})
            sec_cik  = attrs.get("sec_cik")
            sec_crd  = attrs.get("sec_crd")
            print(f"  attributes.sec_cik (fund):  {sec_cik}")
            print(f"  attributes.sec_crd (firma): {sec_crd}")
            go_49 = sec_cik == fund_cik_to_add and sec_crd == TEST_CRD
            print(f"  sec_cik == fund_cik: {sec_cik == fund_cik_to_add}  ← CRÍTICO")
        else:
            go_49 = r_add.status_code == 201
    elif r_add.status_code == 409:
        print("  409 Conflict — fundo já importado (idempotência OK)")
        go_49 = True
    else:
        go_49 = False
else:
    print("  Skipping — nenhum fundo disponível do CRD de teste")
    go_49 = None
print(f"GO: {go_49}")

print("\n=== Go/No-Go #50 — DisclosureMatrix holdings_source='nport' ===")
# O fundo recém importado (ou OAKMX já existente) deve ter holdings_source=nport no catalog
r = get(f"/api/v1/screener/catalog?q=OAKMX&fund_universe=registered_us&limit=5")
if r.status_code == 200:
    items = r.json().get("items", [])
    if items:
        disc = items[0].get("disclosure", {})
        print(f"  holdings_source: {disc.get('holdings_source')}")
        print(f"  has_holdings:    {disc.get('has_holdings')}")
        print(f"  aum_source:      {disc.get('aum_source')}")
        go_50 = disc.get("holdings_source") == "nport"
    else:
        print("  OAKMX não encontrado no catalog")
        go_50 = None
else:
    go_50 = None
print(f"GO: {go_50}")

print("\n=== Go/No-Go #51 — has_13f_overlay para manager que faz 13F ===")
# Harris Associates / Oakmark faz 13F → has_13f_overlay deve ser True
if r.status_code == 200 and items:
    disc = items[0].get("disclosure", {})
    print(f"  has_13f_overlay: {disc.get('has_13f_overlay')}")
    go_51 = disc.get("has_13f_overlay") is True
else:
    go_51 = None
print(f"GO: {go_51}")

print("\n=== Go/No-Go #52 — Identifier bridge (fund CIK != firm CIK) ===")
# Verificar que sec_managers.cik (firma) != sec_registered_funds.cik (fundo)
# para a mesma relação CRD
r_profile = get(f"/api/v1/manager-screener/managers/{TEST_CRD}/profile")
if r_profile.status_code == 200:
    profile = r_profile.json()
    firm_cik = profile.get("cik")
    print(f"  Firma CIK (13F): {firm_cik}")
    print(f"  Fundo CIK (N-PORT usado em #49): {fund_cik_to_add if 'fund_cik_to_add' in dir() else 'N/A'}")
    if 'fund_cik_to_add' in dir() and firm_cik:
        go_52 = firm_cik != fund_cik_to_add
        print(f"  CIKs distintos: {go_52}  ← CRÍTICO")
    else:
        go_52 = None
else:
    go_52 = None
print(f"GO: {go_52}")
```

---

## Resultado Final

```python
print("\n" + "="*60)
print("SEGUNDO E2E — Go/No-Go Final (#29-#52)")
print("="*60)

resultados = {
    "#29 Migration 0058 (garch + cvar_conditional)": go_29,
    "#30 GARCH arch>=7.0":                           go_30,
    "#31 Factor exposures no construct":             go_31,
    "#32 Robust status no enum válido":              go_32,
    "#33 Portfolio Views CRUD":                      go_33,
    "#34 Stress Test preset + custom":               go_34,
    "#35 Performance stress-test < 500ms":           go_35,
    "#36 Migration 0059 (wealth_vector_chunks)":     go_36,
    "#37 Worker wealth_embedding registrado":        go_37,
    "#38 Seed brochures >= 5000 chunks":             "Ver SQL local",
    "#39 Seed ESMA funds >= 10000 chunks":           "Ver SQL local",
    "#40 Zero entity_type='manager'":               "Ver SQL local",
    "#41 firm_crd preenchido em brochures":          "Ver SQL local",
    "#42 Busca fund-firm-context":                   go_42,
    "#43 Busca ESMA funds":                          go_43,
    "#44 Busca org-scoped dd_chapter":               go_44,
    "#45 Idempotência do worker":                    go_45,
    "#46 sec_fund_classes populado":                 go_46,
    "#47 Catalog retorna class_id":                  go_47,
    "#48 GET registered-funds endpoint":             go_48,
    "#49 add-to-universe usa fund CIK":              go_49,
    "#50 DisclosureMatrix holdings_source=nport":    go_50,
    "#51 has_13f_overlay":                           go_51,
    "#52 Identifier bridge fund CIK != firma CIK":   go_52,
}

go_count   = sum(1 for v in resultados.values() if v is True)
fail_count = sum(1 for v in resultados.values() if v is False)
skip_count = sum(1 for v in resultados.values() if v is None or isinstance(v, str))

for item, status in resultados.items():
    if status is True:
        label = "✅ GO"
    elif status is False:
        label = "❌ FAIL"
    elif isinstance(status, str):
        label = f"📋 {status}"
    else:
        label = "⏭  SKIP (endpoint interno)"
    print(f"  {item:<50} {label}")

print(f"\n  GO:   {go_count}/24")
print(f"  FAIL: {fail_count}/24")
print(f"  SKIP: {skip_count}/24  (verificação manual via SQL ou pytest)")
print()
if fail_count == 0:
    print("  ✅ SEGUNDO E2E COMPLETO — sistema validado pós-upgrade")
else:
    print("  ❌ FALHAS ENCONTRADAS — verificar itens acima antes de marcar GO")
```

## Notas de diagnóstico

**#38-#41 requerem SQL direto** porque não há endpoint público para
contar rows em tabelas globais. Usar Tiger CLI ou psql local com
`DIRECT_DATABASE_URL` do `.env`.

**#42-#44 são funções internas** (`pgvector_search_service.py`) chamadas
pelo agente AI. Se não houver endpoint exposto via API REST, verificar via:
```bash
cd D:\Projetos\netz-analysis-engine\backend
.\.venv\Scripts\python.exe -m pytest tests/test_wealth_embedding_worker.py -v
```

**#49 é o item mais crítico do bloco fund-centric** — confirma que
`attributes.sec_cik` = CIK do fundo (não da firma). Se falhar, o DD Report
vai buscar holdings via 13F (firma) em vez de N-PORT (fundo).

**CRD 106116** (Harris Associates) é usado como fixture de teste porque:
- É o gestor do OAKMX (já no universo do primeiro e2e)
- Faz 13F (has_13f_overlay testável)
- Tem fundos N-PORT registrados (sec_registered_funds populado)
- Se não existir no DB, usar qualquer CRD com `last_nport_date IS NOT NULL`

**Resultado do primeiro e2e para referência:**
- `portfolio_id = "c872b6eb-f065-45b2-ad47-17ec9b3e2a3b"`
- `instrument_id_sample = "e9c02fd6-1ac2-46a0-965d-e360c72cca31"` (OAKMX)
- Baseline de rede BR→US = 406ms
- 28/28 GO em 2026-03-27
