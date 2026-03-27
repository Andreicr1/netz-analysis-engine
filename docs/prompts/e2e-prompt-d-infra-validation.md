# Prompt D — Infra Validation (Fase 6–8, Go/No-Go #23–#28)

## Contexto

Backend: https://api.investintell.com
Python: D:\Projetos\netz-analysis-engine\backend\.venv\Scripts\python.exe
Dev auth: settings.dev_token + settings.dev_org_id do .env local

Pré-condição: Prompts A/B/C executados com sucesso (15/15 GO).
Valores da sessão anterior:
  portfolio_id         = "c872b6eb-f065-45b2-ad47-17ec9b3e2a3b"
  instrument_id_sample = "e9c02fd6-1ac2-46a0-965d-e360c72cca31"

Objetivo: fechar os últimos 6 itens do deploy checklist.
Go/No-Go a fechar: #23, #24, #25, #26, #27, #28

## Setup

```python
import sys, time, subprocess
sys.path.insert(0, 'D:/Projetos/netz-analysis-engine/backend')
from app.core.config.settings import settings

BASE_URL = "https://api.investintell.com"
HEADERS = {
    "Authorization": f"Bearer {settings.dev_token}",
    "X-DEV-ACTOR": settings.dev_org_id,
    "Content-Type": "application/json"
}

portfolio_id         = "c872b6eb-f065-45b2-ad47-17ec9b3e2a3b"
instrument_id_sample = "e9c02fd6-1ac2-46a0-965d-e360c72cca31"

import httpx

def get(path, **kw):
    return httpx.get(f"{BASE_URL}{path}", headers=HEADERS, timeout=kw.pop("timeout", 30), **kw)

def post(path, body=None, **kw):
    return httpx.post(f"{BASE_URL}{path}", headers=HEADERS, json=body or {}, timeout=kw.pop("timeout", 30), **kw)
```

---

## Etapa 1 — Audit Trail (Go/No-Go #23)

```python
# Buscar audit events do ciclo E2E
r = get("/api/v1/audit/events")
print(f"Audit events: {r.status_code}")
events = r.json() if isinstance(r.json(), list) else r.json().get("items", [])

event_types = [e.get("event_type") for e in events]
print(f"Tipos encontrados: {sorted(set(event_types))}")

expected = {
    "macro_approved",
    "allocation_proposed",
    "portfolio_constructed",
    "rebalance_applied",
    "long_form_report_generated",
}
present = expected & set(event_types)
missing = expected - set(event_types)

print(f"\n=== Go/No-Go #23 ===")
print(f"Esperados: {sorted(expected)}")
print(f"Presentes: {sorted(present)}")
print(f"Faltando:  {sorted(missing)}")
go_23 = len(missing) == 0
print(f"GO: {go_23}")
```

> Se o endpoint `/api/v1/audit/events` não existir (404), verificar via SQL direto no Timescale Cloud:
> ```sql
> SELECT event_type, COUNT(*), MAX(created_at)
> FROM audit_events
> WHERE organization_id = '<dev_org_id>'
> GROUP BY event_type
> ORDER BY MAX(created_at) DESC;
> ```

---

## Etapa 2 — RLS Cross-Tenant (Go/No-Go #24)

```python
# Verificar zero leakage: com JWT de org_A, não deve ver dados de org_B
# Usar uma segunda org_id fictícia — se a query retornar rows, há leakage
import uuid
fake_org_id = str(uuid.uuid4())  # org que certamente não existe

# Tentar acessar model_portfolio_nav com header de org fake
headers_fake = {**HEADERS, "X-DEV-ACTOR": fake_org_id}
r = httpx.get(
    f"{BASE_URL}/api/v1/model-portfolios/{portfolio_id}/track-record",
    headers=headers_fake,
    timeout=15
)
print(f"\n=== Go/No-Go #24 — RLS Cross-Tenant ===")
print(f"Status (org fake acessando portfolio de org real): {r.status_code}")
# Esperado: 403 ou 404 (RLS bloqueia) — nunca 200 com dados
nav_count = len(r.json().get("nav_series", [])) if r.status_code == 200 else 0
print(f"NAV series retornados: {nav_count} (esperado 0)")
go_24 = r.status_code in (403, 404) or nav_count == 0
print(f"GO: {go_24}")
```

---

## Etapa 3 — Performance Analytics (Go/No-Go #25)

```python
import statistics

print(f"\n=== Go/No-Go #25 — Performance p95 < 500ms ===")
latencies = []
for i in range(10):
    start = time.monotonic()
    r = get(f"/api/v1/analytics/entity/{instrument_id_sample}?window=1Y")
    elapsed_ms = (time.monotonic() - start) * 1000
    latencies.append(elapsed_ms)
    print(f"  [{i+1}] {r.status_code} — {elapsed_ms:.0f}ms")

latencies.sort()
p50 = statistics.median(latencies)
p95 = latencies[int(len(latencies) * 0.95)]
p99 = latencies[-1]

print(f"\np50: {p50:.0f}ms")
print(f"p95: {p95:.0f}ms  (alvo: < 500ms)")
print(f"p99: {p99:.0f}ms")
go_25 = p95 < 500
print(f"GO: {go_25}")
```

---

## Etapa 4 — Advisory Locks (Go/No-Go #26)

```python
# Verificar ausência de colisão de IDs de advisory locks
# Requer acesso direto ao DB — executar via psql ou asyncpg
import asyncio, asyncpg

async def check_advisory_locks():
    conn = await asyncpg.connect(settings.database_url)
    rows = await conn.fetch("""
        SELECT objid, COUNT(*) as cnt
        FROM pg_locks
        WHERE locktype = 'advisory'
        GROUP BY objid
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC;
    """)
    await conn.close()
    return rows

rows = asyncio.run(check_advisory_locks())
print(f"\n=== Go/No-Go #26 — Advisory Lock Collision ===")
if rows:
    print("COLISÕES ENCONTRADAS:")
    for r in rows:
        print(f"  objid={r['objid']} count={r['cnt']}")
    go_26 = False
else:
    print("Nenhuma colisão de advisory lock IDs.")
    go_26 = True
print(f"GO: {go_26}")
```

> Nota: se nenhum worker estiver rodando no momento, `pg_locks` retorna vazio — isso é GO.
> Para testar com worker ativo, disparar `POST /api/v1/workers/run-macro-ingestion` antes desta query.

---

## Etapa 5 — Worker Manifest (Go/No-Go #27)

```python
r = get("/api/v1/workers/manifest")
print(f"\n=== Go/No-Go #27 — Worker Manifest ===")
print(f"Status: {r.status_code}")

if r.status_code == 200:
    manifest = r.json()
    workers = manifest if isinstance(manifest, list) else manifest.get("workers", [])
    worker_ids = [w.get("lock_id") or w.get("name") for w in workers]
    print(f"Workers registrados: {worker_ids}")
    # portfolio_nav_synthesizer deve estar presente (lock 900_030)
    has_synthesizer = any(
        "nav_synthesizer" in str(w).lower() or "900030" in str(w) or "900_030" in str(w)
        for w in workers
    )
    print(f"portfolio_nav_synthesizer presente: {has_synthesizer}")
    go_27 = has_synthesizer
else:
    print(f"Endpoint não disponível: {r.text[:150]}")
    go_27 = False

print(f"GO: {go_27}")
```

---

## Etapa 6 — Railway Cron Jobs (Go/No-Go #28)

```python
# Verificação local — ler railway.toml e confirmar [[crons]] configurados
import pathlib

toml_path = pathlib.Path("D:/Projetos/netz-analysis-engine/railway.toml")
print(f"\n=== Go/No-Go #28 — Railway Cron Jobs ===")

if toml_path.exists():
    content = toml_path.read_text()
    cron_blocks = [line for line in content.splitlines() if "[[crons]]" in line or "python -m app.workers.cli" in line]
    print(f"[[crons]] entries encontradas: {sum(1 for l in cron_blocks if '[[crons]]' in l)}")
    print(f"Linhas com python -m app.workers.cli: {sum(1 for l in cron_blocks if 'python -m app.workers.cli' in l)}")
    for line in cron_blocks:
        print(f"  {line.strip()}")
    go_28 = (
        sum(1 for l in cron_blocks if "[[crons]]" in l) >= 5
        and sum(1 for l in cron_blocks if "python -m app.workers.cli" in l) >= 5
    )
else:
    print("railway.toml não encontrado no path esperado.")
    go_28 = False

print(f"GO: {go_28}")
```

---

## Resultado Final

```python
print("\n" + "="*55)
print("Go/No-Go — Fase 6-8 (Prompt D)")
print("="*55)
resultados = {
    "#23 Audit trail":         go_23,
    "#24 RLS cross-tenant":    go_24,
    "#25 Performance p95":     go_25,
    "#26 Advisory locks":      go_26,
    "#27 Worker manifest":     go_27,
    "#28 Railway Cron Jobs":   go_28,
}
for item, status in resultados.items():
    print(f"  {item}: {'GO' if status else 'NO-GO'}")

total_go = sum(1 for v in resultados.values() if v)
print(f"\nTotal GO: {total_go}/6")
if total_go == 6:
    print("FASE 6-8 COMPLETA — 28/28 GO — SISTEMA EM PRODUÇÃO.")
else:
    print("Itens NO-GO precisam de investigação antes de declarar produção.")
```
