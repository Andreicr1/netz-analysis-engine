# Prompt B — Portfolio Construction (Fase 5.6 a 5.8)

## Pré-condição

Este prompt depende do Prompt A ter sido executado com sucesso.
Substituir os placeholders abaixo com os valores impressos pelo Prompt A:

```python
# Preencher com os valores do Prompt A:
instrument_ids = {
    "OAKMX": "<e9c02fd6>",
    "DODGX": "<fded0e2b>",
    "PRWCX": "<a9840962>",
}
```

## Contexto

Backend: https://api.investintell.com
Python: D:\Projetos\netz-analysis-engine\backend\.venv\Scripts\python.exe
Dev auth: settings.dev_token + settings.dev_org_id do .env local

Objetivo: criar ModelPortfolio, construir com CLARABEL, sintetizar NAV.
Go/No-Go a fechar: #11, #12, #13

## Schemas confirmados (lidos do código-fonte)

### POST /api/v1/model-portfolios
Body: `{"profile": "moderate", "display_name": "Smoke Test Moderate 2026"}`
ATENÇÃO: campo é `display_name`, não `name`.
Response: ModelPortfolioRead com campo `id` (UUID)

### POST /api/v1/model-portfolios/{portfolio_id}/construct
Body: vazio `{}`
Response: snapshot com fund_selection_schema contendo:
  - `optimization.solver` — "CLARABEL" ou "SCS"
  - `optimization.status` — "optimal" | "optimal:cvar_constrained" | "optimal:min_variance_fallback" | "optimal:cvar_violated" | "fallback:insufficient_fund_data"
  - `optimization.cvar_95` — valor do CVaR calculado
  - `optimization.cvar_limit` — limite do perfil

### GET /api/v1/model-portfolios/{portfolio_id}/track-record
Response: objeto com campo `nav_series` (lista de {date, nav, daily_return})

### POST /api/v1/workers/run-risk-calc
### POST /api/v1/workers/run-portfolio-nav-synthesizer
Body: vazio. Response: {status: "queued" | "started"}

## Setup

Este prompt NÃO usa dev_token nem imports do backend.
Autentica diretamente via Clerk Backend API com o template "netz-wealth" (produção real).

```python
import os, time, httpx

BASE_URL = "https://api.investintell.com"

# Credenciais Clerk (produção)
CLERK_KEY = os.environ.get("CLERK_SECRET_KEY")  # sk_live_...
USER_ID   = os.environ.get("CLERK_USER_ID")      # user_...

def get_jwt():
    """Gerar JWT via Clerk Backend API com template netz-wealth."""
    # 1. Buscar sessão ativa do usuário
    r = httpx.get(
        f"https://api.clerk.com/v1/sessions?user_id={USER_ID}&status=active",
        headers={"Authorization": f"Bearer {CLERK_KEY}"},
        timeout=15,
    )
    sessions = r.json() if isinstance(r.json(), list) else r.json().get("data", [])
    if not sessions:
        raise RuntimeError("Nenhuma sessão ativa encontrada no Clerk")
    sid = sessions[0]["id"]

    # 2. Gerar token com template netz-wealth (inclui org claims + role)
    r2 = httpx.post(
        f"https://api.clerk.com/v1/sessions/{sid}/tokens/netz-wealth",
        headers={"Authorization": f"Bearer {CLERK_KEY}", "Content-Type": "application/json"},
        json={},
        timeout=15,
    )
    if r2.status_code != 200:
        raise RuntimeError(f"Falha ao gerar JWT: {r2.status_code} — {r2.text}")
    jwt = r2.json().get("jwt")
    print(f"JWT gerado com sucesso (primeiros 40 chars): {jwt[:40]}...")
    return jwt

JWT = get_jwt()
HEADERS = {
    "Authorization": f"Bearer {JWT}",
    "Content-Type": "application/json",
}

# Preencher com valores do Prompt A:
instrument_ids = {
    "SPY": "<uuid>",
    "AGG": "<uuid>",
    "VNQ": "<uuid>",
}

# Helpers
def get(path, **kw):
    return httpx.get(f"{BASE_URL}{path}", headers=HEADERS, timeout=kw.pop("timeout", 30), **kw)

def post(path, body=None, **kw):
    return httpx.post(f"{BASE_URL}{path}", headers=HEADERS, json=body or {}, timeout=kw.pop("timeout", 60), **kw)
```

> Se CLERK_SECRET_KEY ou CLERK_USER_ID não estiverem no ambiente, defini-los antes:
> `$env:CLERK_SECRET_KEY = "sk_live_..."` e `$env:CLERK_USER_ID = "user_..."`
```

## Etapa 1 — Rodar workers de risco

```python
for worker in ["run-risk-calc", "run-screening-batch"]:
    r = post(f"/api/v1/workers/{worker}")
    print(f"{worker}: {r.status_code} — {r.text[:100]}")

print("Aguardando 60s para workers completarem...")
time.sleep(60)
```

## Etapa 2 — Criar ModelPortfolio

```python
r = httpx.post(
    f"{BASE_URL}/api/v1/model-portfolios",
    json={"profile": "moderate", "display_name": "Smoke Test Moderate 2026"},
    headers=HEADERS, timeout=15
)
print(f"Criar portfolio: {r.status_code} — {r.text[:200]}")

portfolio = r.json()
portfolio_id = str(portfolio.get("id"))
print(f"Portfolio ID: {portfolio_id}")
```

## Etapa 3 — Construir com CLARABEL (Go/No-Go #11, #12)

```python
r = httpx.post(
    f"{BASE_URL}/api/v1/model-portfolios/{portfolio_id}/construct",
    json={}, headers=HEADERS, timeout=120
)
print(f"Construct: {r.status_code}")
snapshot = r.json()

opt = snapshot.get("fund_selection_schema", {}).get("optimization", {})
solver   = opt.get("solver")
status   = opt.get("status")
cvar_cur = opt.get("cvar_95")
cvar_lim = opt.get("cvar_limit")
cvar_ok  = opt.get("cvar_within_limit")

print(f"\n=== Go/No-Go #11 ===")
print(f"solver:          {solver}")
print(f"status:          {status}")
print(f"cvar_95:         {cvar_cur}")
print(f"cvar_limit:      {cvar_lim}")
print(f"cvar_within_limit: {cvar_ok}")

print(f"\n=== Go/No-Go #12 ===")
valid_statuses = {
    "optimal", "optimal:cvar_constrained",
    "optimal:min_variance_fallback", "optimal:cvar_violated",
    "solver_failed", "fallback:insufficient_fund_data"
}
print(f"status válido: {status in valid_statuses} ({status})")
```

**Se solver = fallback:insufficient_fund_data:**
Os fundos têm menos de 120 observações de NAV. Verificar:
```python
# Quantas observações de NAV cada fundo tem
for ticker, iid in instrument_ids.items():
    r = httpx.get(f"{BASE_URL}/api/v1/instruments/{iid}",
                  headers=HEADERS, timeout=10)
    nav_count = r.json().get("nav_count") or "N/A"
    print(f"{ticker}: {nav_count} obs de NAV")
```
Se insuficiente, rodar `run-instrument-ingestion` e aguardar 2 min antes de tentar construct novamente.

## Etapa 4 — NAV Sintético (Go/No-Go #13)

```python
r = httpx.post(f"{BASE_URL}/api/v1/workers/run-portfolio-nav-synthesizer",
               json={}, headers=HEADERS, timeout=15)
print(f"NAV synthesizer: {r.status_code} — {r.text[:100]}")
print("Aguardando 30s...")
time.sleep(30)

r = httpx.get(f"{BASE_URL}/api/v1/model-portfolios/{portfolio_id}/track-record",
              headers=HEADERS, timeout=15)
track = r.json()
nav_series = track.get("nav_series", [])
print(f"\n=== Go/No-Go #13 ===")
print(f"NAV series: {len(nav_series)} registros")
if nav_series:
    print(f"Primeiro: {nav_series[0]}")
    print(f"Último:   {nav_series[-1]}")
    primeiro_nav = float(nav_series[0].get("nav", 0))
    print(f"Day-0 nav=1000.0: {abs(primeiro_nav - 1000.0) < 0.01}")
```

## Critério de conclusão

Reportar Go/No-Go:
- #11: solver não é heuristic_fallback + optimization.cvar_95 e cvar_limit presentes → GO / NO-GO
- #12: status é um valor documentado → GO / NO-GO
- #13: primeiro registro nav=1000.0 → GO / NO-GO

## Output para o Prompt C

Ao terminar, imprimir exatamente:
```
=== RESULTADO PARA PROMPT C ===
portfolio_id = "<uuid>"
instrument_id_sample = "<uuid-de-qualquer-fundo-aprovado>"
go_11 = True/False
go_12 = True/False
go_13 = True/False
```

Todos os Go/No-Go validados:
  ┌──────────┬───────────┬──────────────────────────────────────────────────────────────────┐
  │ Go/No-Go │ Resultado │                             Detalhe                              │
  ├──────────┼───────────┼──────────────────────────────────────────────────────────────────┤
  │ #11      │ GO        │ solver=CLARABEL (min_variance), cvar_95=-0.387, cvar_limit=-0.06 │
  ├──────────┼───────────┼──────────────────────────────────────────────────────────────────┤
  │ #12      │ GO        │ status=optimal:min_variance_fallback documentado                 │
  ├──────────┼───────────┼──────────────────────────────────────────────────────────────────┤
  │ #13      │ GO        │ 501 registros, day-0 nav=1000.0, último nav=1304.86              │
  └──────────┴───────────┴──────────────────────────────────────────────────────────────────┘
  === RESULTADO PARA PROMPT C ===
  portfolio_id = "c872b6eb-f065-45b2-ad47-17ec9b3e2a3b"
  instrument_id_sample = "e9c02fd6-1ac2-46a0-965d-e360c72cca31"
  go_11 = True
  go_12 = True
  go_13 = True
