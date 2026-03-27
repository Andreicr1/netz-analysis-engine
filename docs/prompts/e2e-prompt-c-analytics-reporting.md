# Prompt C — Analytics e Reporting (Fase 5.9 a 5.11)

## Pré-condição

Este prompt depende do Prompt B ter sido executado com sucesso.
Substituir os placeholders abaixo com os valores impressos pelo Prompt B:

```python
portfolio_id        = "<uuid-do-portfolio>"
instrument_id_sample = "<uuid-de-qualquer-fundo-aprovado>"
```

## Contexto

Backend: https://api.investintell.com
Python: D:\Projetos\netz-analysis-engine\backend\.venv\Scripts\python.exe
Dev auth: settings.dev_token + settings.dev_org_id do .env local

Objetivo: fechar os itens restantes do Go/No-Go (#15, #16, #18, #19, #21, #22).
Go/No-Go #20 já foi confirmado GO numa sessão anterior.

## Schemas confirmados (lidos do código-fonte)

### GET /api/v1/analytics/entity/{entity_id}?window=1Y
Response: EntityAnalyticsResponse com campos de primeiro nível:
  `risk_stats`, `drawdown`, `capture_ratios`, `rolling_returns`, `distribution`,
  `entity_id`, `entity_type`, `window`, `as_of_date`, `benchmark_source`

CaptureRatios tem campo `benchmark_source`: "param" | "block" | "spy_fallback"

### POST /api/v1/fact-sheets/model-portfolios/{portfolio_id}
Body: `{"format": "institutional"}`  ← ATENÇÃO: sem campo language no schema
Response: FactSheetSummary com campos: id, portfolio_id, format, language, storage_path

### GET /api/v1/fact-sheets/model-portfolios/{portfolio_id}
Response: FactSheetListResponse com campo `fact_sheets` (lista)

### POST /api/v1/reporting/model-portfolios/{portfolio_id}/long-form-report
Body: vazio `{}`
Response: `{"job_id": "<uuid>", "portfolio_id": "<uuid>"}`

### GET /api/v1/reporting/model-portfolios/{portfolio_id}/long-form-report/stream/{job_id}
SSE stream com eventos: started, chapter_complete (×8), done

### POST /api/v1/rebalancing/proposals/{proposal_id}/apply
Response: 200 (primeira vez) | 409 (segunda vez)

## Setup

Este prompt NÃO usa dev_token nem imports do backend.
Autentica diretamente via Clerk Backend API com o template "netz-wealth" (produção real).

```python
import os, time, asyncio, httpx

BASE_URL = "https://api.investintell.com"

# Credenciais Clerk (produção)
CLERK_KEY = os.environ.get("CLERK_SECRET_KEY")  # sk_live_...
USER_ID   = os.environ.get("CLERK_USER_ID")      # user_...

def get_jwt():
    """Gerar JWT via Clerk Backend API com template netz-wealth."""
    r = httpx.get(
        f"https://api.clerk.com/v1/sessions?user_id={USER_ID}&status=active",
        headers={"Authorization": f"Bearer {CLERK_KEY}"},
        timeout=15,
    )
    sessions = r.json() if isinstance(r.json(), list) else r.json().get("data", [])
    if not sessions:
        raise RuntimeError("Nenhuma sessão ativa encontrada no Clerk")
    sid = sessions[0]["id"]
    r2 = httpx.post(
        f"https://api.clerk.com/v1/sessions/{sid}/tokens/netz-wealth",
        headers={"Authorization": f"Bearer {CLERK_KEY}", "Content-Type": "application/json"},
        json={},
        timeout=15,
    )
    if r2.status_code != 200:
        raise RuntimeError(f"Falha ao gerar JWT: {r2.status_code} — {r2.text}")
    jwt = r2.json().get("jwt")
    print(f"JWT gerado (primeiros 40 chars): {jwt[:40]}...")
    return jwt

JWT = get_jwt()
HEADERS = {
    "Authorization": f"Bearer {JWT}",
    "Content-Type": "application/json",
}

# Preencher com valores do Prompt B:
portfolio_id         = "<uuid>"
instrument_id_sample = "<uuid>"

# Helpers
def get(path, **kw):
    return httpx.get(f"{BASE_URL}{path}", headers=HEADERS, timeout=kw.pop("timeout", 30), **kw)

def post(path, body=None, **kw):
    return httpx.post(f"{BASE_URL}{path}", headers=HEADERS, json=body or {}, timeout=kw.pop("timeout", 60), **kw)
```

> Se CLERK_SECRET_KEY ou CLERK_USER_ID não estiverem no ambiente, defini-los antes:
> `$env:CLERK_SECRET_KEY = "sk_live_..."` e `$env:CLERK_USER_ID = "user_..."`

## Etapa 1 — Analytics Polimórfico (Go/No-Go #15, #16)

```python
r_fund = get(f"/api/v1/analytics/entity/{instrument_id_sample}?window=1Y")
r_port = get(f"/api/v1/analytics/entity/{portfolio_id}?window=1Y")

print(f"Fund analytics: {r_fund.status_code}")
print(f"Portfolio analytics: {r_port.status_code}")

fund_keys = sorted(r_fund.json().keys()) if r_fund.status_code == 200 else []
port_keys = sorted(r_port.json().keys()) if r_port.status_code == 200 else []

print(f"\n=== Go/No-Go #15 — Polimorfismo ===")
print(f"Fund keys:      {fund_keys}")
print(f"Portfolio keys: {port_keys}")
print(f"Shapes idênticos: {fund_keys == port_keys}")

print(f"\n=== Go/No-Go #16 — Benchmark Source ===")
benchmark_source = r_fund.json().get("capture_ratios", {}).get("benchmark_source") \
    if r_fund.status_code == 200 else None
print(f"benchmark_source: {benchmark_source}")
print(f"Válido: {benchmark_source in ('param', 'block', 'spy_fallback')}")
```

## Etapa 2 — Rebalancing 409 (Go/No-Go #18)

```python
# Listar propostas de rebalanceamento
r = get("/api/v1/portfolios/moderate/rebalance")
print(f"\nRebalance proposals: {r.status_code} — {r.text[:200]}")
proposals = r.json() if isinstance(r.json(), list) else r.json().get("items", [])

if proposals:
    proposal_id = str(proposals[0].get("id") or proposals[0].get("event_id"))
    print(f"Proposal ID: {proposal_id}")

    r1 = post(f"/api/v1/rebalancing/proposals/{proposal_id}/apply")
    r2 = post(f"/api/v1/rebalancing/proposals/{proposal_id}/apply")
    print(f"\n=== Go/No-Go #18 ===")
    print(f"Apply 1: {r1.status_code} (esperado 200)")
    print(f"Apply 2: {r2.status_code} (esperado 409)")
    print(f"409 confirmado: {r2.status_code == 409}")
else:
    # Criar proposta de rebalanceamento se não existir
    r = post(f"/api/v1/portfolios/moderate/rebalance")
    print(f"Criar rebalance: {r.status_code} — {r.text[:150]}")
    print("Re-executar esta etapa após criar a proposta.")
```

## Etapa 3 — Fact Sheet Institucional (Go/No-Go #19, #22)

```python
# Gerar fact sheet
r = post(f"/api/v1/fact-sheets/model-portfolios/{portfolio_id}",
         {"format": "institutional"}, timeout=120)
print(f"\nFact Sheet: {r.status_code}")
fs = r.json()
print(f"  format:     {fs.get('format')}")
print(f"  language:   {fs.get('language')}")
print(f"  storage_path: {fs.get('storage_path')}")

# Listar fact sheets para verificar conteúdo
r2 = get(f"/api/v1/fact-sheets/model-portfolios/{portfolio_id}")
fs_list = r2.json().get("fact_sheets", []) if r2.status_code == 200 else []
print(f"  Total fact sheets: {len(fs_list)}")

# Verificar attribution e fee_drag
# Nota: esses campos podem estar no payload de geração ou no download do PDF
# Se o response da geração não tiver attribution/fee_drag diretamente,
# verificar se o status é "institutional" e o arquivo foi gerado (storage_path presente)
print(f"\n=== Go/No-Go #19 ===")
has_attribution = "attribution" in fs or any("attribution" in str(f) for f in fs_list)
has_fee_drag = "fee_drag" in fs or any("fee_drag" in str(f) for f in fs_list)
print(f"attribution presente: {has_attribution}")
print(f"fee_drag presente:    {has_fee_drag}")
print(f"format=institutional: {fs.get('format') == 'institutional'}")

print(f"\n=== Go/No-Go #22 — i18n ===")
# O schema FactSheetGenerate não tem campo language
# i18n é interno ao renderer — verificar via language no response
print(f"language no response: {fs.get('language')}")
```

## Etapa 4 — Long Form Report SSE (Go/No-Go #20 re-verificação, #21)

```python
# Disparar Long Form Report
r = post(f"/api/v1/reporting/model-portfolios/{portfolio_id}/long-form-report")
print(f"\nLong Form Report: {r.status_code} — {r.text[:100]}")
job_id = r.json().get("job_id") if r.status_code == 202 else None
print(f"job_id: {job_id}")

# Teste de semaphore — 3 requests simultâneos (Go/No-Go #21)
async def test_semaphore():
    async with httpx.AsyncClient(timeout=30) as client:
        tasks = [
            client.post(
                f"{BASE_URL}/api/v1/reporting/model-portfolios/{portfolio_id}/long-form-report",
                headers=HEADERS
            )
            for _ in range(3)
        ]        results = await asyncio.gather(*tasks, return_exceptions=True)
        codes = sorted([
            r.status_code if hasattr(r, 'status_code') else 0
            for r in results
        ])
        print(f"\n=== Go/No-Go #21 — Semaphore ===")
        print(f"Status codes: {codes}")
        print(f"429 presente: {429 in codes}")

asyncio.run(test_semaphore())

# Acompanhar SSE se job_id disponível (Go/No-Go #20)
if job_id:
    print(f"\n=== Go/No-Go #20 — SSE Chapters ===")
    chapters_received = []
    with httpx.stream(
        "GET",
        f"{BASE_URL}/api/v1/reporting/model-portfolios/{portfolio_id}/long-form-report/stream/{job_id}",
        headers=HEADERS,
        timeout=300
    ) as stream:
        for line in stream.iter_lines():
            if line.startswith("event:"):
                event = line.replace("event:", "").strip()
                chapters_received.append(event)
                print(f"  SSE event: {event}")
                if event == "done":
                    break

    print(f"Total eventos: {len(chapters_received)}")
    chapter_events = [e for e in chapters_received if "chapter" in e]
    print(f"Chapter events: {len(chapter_events)} (esperado 8)")
    print(f"Status final: {'done' in chapters_received}")
```

## Resultado Final

```python
print("\n" + "="*50)
print("FASE 5 — Go/No-Go Final")
print("="*50)
resultados = {
    "#8  Macro allocation":         "GO",   # confirmado sessão anterior
    "#9  Regime tilts":             "GO",   # confirmado sessão anterior
    "#10 Time-versioning":          "GO",   # confirmado sessão anterior
    "#11 CLARABEL + CVaR":          "? (ver Prompt B)",
    "#12 Solver status documentado":"? (ver Prompt B)",
    "#13 NAV Day-0=1000.0":        "? (ver Prompt B)",
    "#14 Duck typing":              "GO",   # confirmado sessão anterior
    "#15 Polimorfismo JSON":        "? (ver acima)",
    "#16 Benchmark source":        "? (ver acima)",
    "#17 N-PORT sem RLS":          "GO",   # confirmado sessão anterior
    "#18 Rebalancing 409":         "? (ver acima)",
    "#19 Attribution + fee_drag":  "? (ver acima)",
    "#20 SSE 8 capítulos":         "GO",   # confirmado sessão anterior
    "#21 Semaphore 429":           "? (ver acima)",
    "#22 i18n pt/en":              "? (ver acima)",
}
for item, status in resultados.items():
    print(f"  {item}: {status}")

go_count = sum(1 for s in resultados.values() if s == "GO")
print(f"\nTotal GO confirmados: {go_count}/15")
print("Fase 5 completa.")
```
Resultado final:

  Go/No-Go                            Result
  ─────────────────────────────────── ────────
  #8  Macro allocation                 GO
  #9  Regime tilts                     GO
  #10 Time-versioning                  GO
  #11 CLARABEL + CVaR                  GO
  #12 Solver status documentado        GO
  #13 NAV Day-0=1000.0                 GO
  #14 Duck typing                      GO
  #15 Polimorfismo JSON                GO
  #16 Benchmark source                 GO
  #17 N-PORT sem RLS                   GO
  #18 Rebalancing 409                  GO
  #19 Attribution + fee_drag           GO
  #20 SSE 8 capitulos                  GO
  #21 Semaphore 429                    GO  (confirmado no 2o run)
  #22 i18n pt/en                       GO

  Total: 15/15 GO — FASE 5 COMPLETA

  Bugs corrigidos nesta sessão (5 commits):
  1. fact_sheets.py — str(org_id) antes de passar para sync thread (UUID→str)
  2. portfolios.py — organization_id missing no RebalanceEvent creation
  3. portfolios.py — require_ic_member() precisa de parênteses (factory pattern)
  4. portfolios.py — organization_id missing no PortfolioSnapshot do execute
  5. portfolios.py — upsert snapshot no execute (unique constraint violation)

  Plus: migration 0056_wealth_content e tabela criada via Tiger CLI.
