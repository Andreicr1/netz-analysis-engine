# Prompt A — Seed do Universe (Fase 5.1 a 5.5)

## Contexto

Backend: https://api.investintell.com
Python: D:\Projetos\netz-analysis-engine\backend\.venv\Scripts\python.exe
Dev auth: settings.dev_token + settings.dev_org_id do .env local

Itens Go/No-Go já confirmados: #8, #9, #10, #14, #17, #20
Objetivo desta sessão: popular o universe com ≥3 fundos aprovados via fluxo completo.

## Schemas confirmados (lidos do código-fonte)

### POST /api/v1/instruments/import/yahoo
Body: `{"ticker": "SPY"}`
Response: objeto Instrument com campo `id` (UUID) — usar como `instrument_id` e `fund_id`

### POST /api/v1/dd-reports/funds/{fund_id}
Body: `{"config_overrides": null}` (ou body vazio)
Response: DDReportSummary com campos: `id`, `instrument_id`, `status`, `confidence_score`, `decision_anchor`

### GET /api/v1/dd-reports/{report_id}
Response: DDReportRead com campo `status` (pending → generating → completed | failed)

### POST /api/v1/dd-reports/{report_id}/approve
Body: `{"rationale": "E2E smoke test"}`
Response: DDReportSummary atualizado
IMPORTANTE: Aprovação do DD Report cria automaticamente o registro de UniverseApproval pending.

### POST /api/v1/universe/funds/{instrument_id}/approve
Body: `{"decision": "approved", "rationale": "E2E smoke test seed"}`
Response: UniverseApprovalRead

### GET /api/v1/universe
Response: list[UniverseAssetRead] com campos: instrument_id, fund_name, block_id, approval_decision

## Setup

```python
import sys, time, httpx
sys.path.insert(0, 'D:/Projetos/netz-analysis-engine/backend')
from app.core.config.settings import settings

BASE_URL = "https://api.investintell.com"
HEADERS = {
    "Authorization": f"Bearer {settings.dev_token}",
    "X-DEV-ACTOR": settings.dev_org_id,
    "Content-Type": "application/json"
}
print("org_id:", settings.dev_org_id)
print("token:", settings.dev_token[:20], "...")
```

## Etapa 1 — Importar 3 ETFs

```python
"""
Usando fundos mútuos em vez de ETFs — mais representativos do produto institucional.
Holdings concentradas = DD Report mais leve e rápido:
  - OAKMX: Oakmark Fund (~30 holdings, value concentrated)
  - DODGX: Dodge & Cox Stock (~70 holdings, value)
  - PRWCX: T. Rowe Price Capital Appreciation (balanced, multi-asset)
"""
tickers = ["OAKMX", "DODGX", "PRWCX"]
instrument_ids = {}

for ticker in tickers:
    r = httpx.post(f"{BASE_URL}/api/v1/instruments/import/yahoo",
                   json={"ticker": ticker}, headers=HEADERS, timeout=30)
    print(f"{ticker}: {r.status_code} — {r.text[:200]}")
    if r.status_code in (200, 201):
        data = r.json()
        instrument_ids[ticker] = str(data.get("id"))
    elif r.status_code == 409:
        # Já existe — buscar pelo ticker
        r2 = httpx.get(f"{BASE_URL}/api/v1/instruments",
                       params={"ticker": ticker}, headers=HEADERS)
        items = r2.json()
        if items:
            instrument_ids[ticker] = str(items[0].get("id") or items[0].get("instrument_id"))
            print(f"  {ticker} já existia: {instrument_ids[ticker]}")

print("\nInstrument IDs:", instrument_ids)
# Se algum falhar, tentar TRBCX ou VFIAX como substituto
```

## Etapa 2 — Disparar DD Reports em paralelo

```python
import asyncio, httpx as ahttpx

async def trigger_dd(ticker, instrument_id):
    async with ahttpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{BASE_URL}/api/v1/dd-reports/funds/{instrument_id}",
            json={},
            headers=HEADERS
        )
        print(f"  DD trigger {ticker}: {r.status_code} — {r.text[:150]}")
        if r.status_code in (200, 201, 202):
            return ticker, str(r.json().get("id"))
        return ticker, None

results = asyncio.run(asyncio.gather(*[
    trigger_dd(t, iid) for t, iid in instrument_ids.items()
]))
report_ids = {t: rid for t, rid in results if rid}
print("\nReport IDs:", report_ids)
```

## Etapa 3 — Aguardar conclusão (polling, até 10 min por fundo)

```python
def wait_for_dd(ticker, report_id, max_seconds=600, interval=20):
    elapsed = 0
    while elapsed < max_seconds:
        r = httpx.get(f"{BASE_URL}/api/v1/dd-reports/{report_id}",
                      headers=HEADERS, timeout=10)
        data = r.json()
        status = data.get("status", "unknown")
        confidence = data.get("confidence_score") or 0
        print(f"  [{elapsed}s] {ticker}: status={status} confidence={confidence}")
        if status in ("completed", "failed", "approved", "rejected"):
            return data
        time.sleep(interval)
        elapsed += interval
    print(f"  TIMEOUT: {ticker}")
    return None

print("\nAguardando DD Reports (pode levar 2-5 min por fundo)...")
dd_results = {}
for ticker, report_id in report_ids.items():
    print(f"\n{ticker} ({report_id}):")
    dd_results[ticker] = wait_for_dd(ticker, report_id)
```

## Etapa 4 — Aprovar DD Reports

```python
for ticker, result in dd_results.items():
    if not result:
        print(f"SKIP {ticker} — timeout")
        continue
    report_id = report_ids[ticker]
    r = httpx.post(
        f"{BASE_URL}/api/v1/dd-reports/{report_id}/approve",
        json={"rationale": "E2E smoke test — validação de pipeline"},
        headers=HEADERS, timeout=15
    )
    print(f"Approve DD {ticker}: {r.status_code} — {r.text[:100]}")
```

## Etapa 5 — Aprovar no Universe

```python
for ticker, instrument_id in instrument_ids.items():
    r = httpx.post(
        f"{BASE_URL}/api/v1/universe/funds/{instrument_id}/approve",
        json={"decision": "approved", "rationale": "E2E smoke test seed"},
        headers=HEADERS, timeout=15
    )
    print(f"Universe approve {ticker}: {r.status_code} — {r.text[:150]}")

# Verificar universe
r = httpx.get(f"{BASE_URL}/api/v1/universe", headers=HEADERS, timeout=15)
universe = r.json()
print(f"\nUniverse: {len(universe)} fundos")
for f in universe:
    print(f"  {f.get('fund_name')} | block={f.get('block_id')} | decision={f.get('approval_decision')}")
```

## Critério de conclusão

Reportar ao final:
- Quantos instrumentos foram importados com sucesso
- Quantos DD Reports completaram (status=completed ou failed)
- Quantos DD Reports foram aprovados
- Quantos fundos aparecem no GET /universe com approval_decision=approved
- Os instrument_ids aprovados (necessários para o Prompt B)

**SUCESSO:** ≥3 fundos com approval_decision=approved no universe.
**Se < 3:** tentar importar QQQ, IEF, GLD como substitutos e repetir o fluxo.

## Output para o Prompt B

Ao terminar, imprimir exatamente:
```
=== RESULTADO PARA PROMPT B ===
instrument_ids = {
    "OAKMX": "<uuid>",
    "DODGX": "<uuid>",
    "PRWCX": "<uuid>"
}
universe_count = 3
```
