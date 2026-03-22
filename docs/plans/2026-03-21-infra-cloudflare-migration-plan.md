# Plano de Implementação — Migração de Hosting para Cloudflare

## Context

O Netz Analysis Engine está migrando de Railway (backend) + Azure (storage legado) para 100% Cloudflare.
A stack alvo: Cloudflare Containers (backend + workers), Cloudflare Workers (API gateway + cron triggers),
Cloudflare Pages (3 frontends SvelteKit), Cloudflare R2 (já ativo). Serviços externos mantidos: Timescale Cloud,
Upstash Redis, Clerk, OpenAI, Mistral.

**Estado atual relevante:**
- Sem Dockerfile — Railway usa nixpacks builder
- Workers em `backend/app/domains/wealth/workers/` (18 workers), disparados via POST `/api/v1/workers/run-{name}`
- `BackgroundTasks.add_task()` + Redis idempotency + `pg_try_advisory_lock`
- Frontends usam `@sveltejs/adapter-node` (3 apps idênticos em config)
- R2 já é default em produção (`FEATURE_R2_ENABLED=true`)
- ADLS deprecated — lazy import, não está em `pyproject.toml`
- Azure fields existem em `settings.py` mas são dead code
- Health check em `/health`, `/api/health`, `/api/v1/admin/health`

---

## Fase 0 — Dockerfile e Container Base

**Objetivo:** Criar imagem Docker única para backend FastAPI + workers.

**Decisão: imagem única.** Backend e workers compartilham 100% do código (workers estão em `backend/app/domains/wealth/workers/`, importam modelos, serviços e config do mesmo app). Imagens separadas dobrariam build time sem benefício — o entrypoint diferencia: `uvicorn` (backend) vs `python -m` (worker). Cloudflare Containers usa `sleepAfter` para controlar idle.

### Arquivos criados

**`infra/cloudflare/Dockerfile`**
```dockerfile
FROM python:3.12-slim AS base
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml backend/
RUN pip install --no-cache-dir -e "./backend[ai,quant,edgar]"

COPY backend/ backend/
COPY profiles/ profiles/
COPY calibration/ calibration/

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

**`infra/cloudflare/.dockerignore`**
```
frontends/
packages/
.git/
.data/
__pycache__/
*.pyc
.env*
docs/
tests/
```

### Arquivos modificados

Nenhum. O health check `/health` já existe em `backend/app/main.py:255`.

### Dependências

Nenhuma fase anterior.

### Critério de conclusão

```bash
docker build -f infra/cloudflare/Dockerfile -t netz-backend .
docker run --rm -e DATABASE_URL=... -e REDIS_URL=... -p 8000:8000 netz-backend
curl http://localhost:8000/health  # → {"status": "ok"}
```

---

## Fase 1 — Estrutura Cloudflare e wrangler.jsonc

**Objetivo:** Definir a configuração de containers e bindings no Cloudflare.

### Arquivos criados

**`infra/cloudflare/wrangler.backend.jsonc`** — Container backend (always-on)
```jsonc
{
  "name": "netz-backend",
  "containers": {
    "image": "./Dockerfile",
    "port": 8000,
    "instances": { "min": 1, "max": 3 },
    // Never sleep — always-on API server
    "memory": "2GB",
    "cpu": 2
  },
  "r2_buckets": [
    { "binding": "NETZ_DATA_LAKE", "bucket_name": "netz-data-lake" }
  ],
  "vars": {
    "APP_ENV": "production",
    "FEATURE_R2_ENABLED": "true"
  }
  // Secrets (DATABASE_URL, REDIS_URL, OPENAI_API_KEY, etc.)
  // configured via `wrangler secret put` or Cloudflare Dashboard
}
```

**`infra/cloudflare/wrangler.workers.jsonc`** — Container workers (sleep-after-idle)
```jsonc
{
  "name": "netz-workers",
  "containers": {
    "image": "./Dockerfile",
    "port": 8000,
    "instances": { "min": 0, "max": 1 },
    "sleep_after": "30m",
    "memory": "2GB",
    "cpu": 2
  },
  "vars": {
    "APP_ENV": "production",
    "FEATURE_R2_ENABLED": "true",
    "NETZ_WORKER_MODE": "true"
  }
  // Same secrets as backend
}
```

> **Nota:** O container workers roda a mesma imagem FastAPI. O `NETZ_WORKER_MODE` é lido
> pelo novo endpoint `/internal/workers/dispatch` (Fase 3). O container sobe, recebe POST
> do Cron Worker, executa o worker via BackgroundTasks, e dorme após 30min de idle.

### Arquivos modificados

Nenhum no código Python — apenas infra.

### Dependências

Fase 0 (Dockerfile).

### Critério de conclusão

```bash
cd infra/cloudflare
npx wrangler containers deploy --config wrangler.backend.jsonc  # deploy bem-sucedido
npx wrangler containers deploy --config wrangler.workers.jsonc  # deploy bem-sucedido
```

---

## Fase 2 — API Gateway Worker

**Objetivo:** Worker JS que faz proxy de todas as requests para o container backend, bloqueando `/internal/*`.

### Arquivos criados

**`infra/cloudflare/gateway/wrangler.toml`**
```toml
name = "netz-gateway"
main = "src/index.ts"
compatibility_date = "2025-12-01"

[vars]
BACKEND_ORIGIN = "https://netz-backend.<account>.containers.cloudflare.com"

[[services]]
binding = "BACKEND"
service = "netz-backend"
```

**`infra/cloudflare/gateway/src/index.ts`**
```typescript
export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // Block /internal/* — only Cron Workers with secret
    if (url.pathname.startsWith("/internal/")) {
      const secret = request.headers.get("X-Worker-Secret");
      if (secret !== env.WORKER_SECRET) {
        return new Response("Forbidden", { status: 403 });
      }
    }

    // Proxy to backend container — preserve all headers (JWT, SSE)
    const backendUrl = new URL(url.pathname + url.search, env.BACKEND_ORIGIN);
    const backendReq = new Request(backendUrl.toString(), {
      method: request.method,
      headers: request.headers,
      body: request.body,
      redirect: "follow",
    });

    const response = await fetch(backendReq);

    // SSE: preserve streaming headers
    const headers = new Headers(response.headers);
    if (headers.get("content-type")?.includes("text/event-stream")) {
      headers.set("Cache-Control", "no-cache");
      headers.delete("Content-Length");
    }

    return new Response(response.body, {
      status: response.status,
      headers,
    });
  },
};
```

**`infra/cloudflare/gateway/package.json`**
```json
{
  "name": "netz-gateway",
  "private": true,
  "scripts": { "deploy": "wrangler deploy" },
  "devDependencies": { "wrangler": "^4" }
}
```

### Arquivos modificados

Nenhum no backend.

### Dependências

Fase 1 (container backend deve estar acessível).

### Critério de conclusão

```bash
curl https://netz-gateway.<domain>/health              # → proxied, 200
curl https://netz-gateway.<domain>/internal/workers/dispatch  # → 403 sem header
curl -H "X-Worker-Secret: $SECRET" https://netz-gateway.<domain>/internal/workers/dispatch  # → proxied
```

---

## Fase 3 — Cron Workers + Endpoint `/internal/workers/dispatch`

**Objetivo:** Scheduled Workers disparam workers Python via POST interno; backend expõe endpoint protegido.

### Arquivos criados

**`backend/app/domains/admin/routes/internal.py`** — Endpoint protegido por secret
```python
"""Internal worker dispatch — called by Cloudflare Cron Workers only."""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel

router = APIRouter(prefix="/internal", tags=["internal"])

class DispatchRequest(BaseModel):
    workers: list[str]  # e.g. ["macro_ingestion", "benchmark_ingest"]

async def require_worker_secret(request: Request) -> None:
    expected = settings.worker_dispatch_secret
    if not expected or request.headers.get("X-Worker-Secret") != expected:
        raise HTTPException(status_code=403, detail="Forbidden")

@router.post("/workers/dispatch", dependencies=[Depends(require_worker_secret)])
async def dispatch_workers(
    body: DispatchRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    """Dispatch one or more workers as background tasks. Returns 202 immediately."""
    dispatched = []
    for name in body.workers:
        worker_fn = WORKER_REGISTRY.get(name)
        if worker_fn:
            background_tasks.add_task(worker_fn)
            dispatched.append(name)
    return {"status": "dispatched", "workers": dispatched}
```

**`backend/app/domains/admin/routes/worker_registry.py`** — Mapa de workers
```python
"""Registry mapping worker names to async entry points."""
from backend.app.domains.wealth.workers import (
    macro_ingestion, benchmark_ingest, treasury_ingestion,
    ofr_ingestion, bis_ingestion, imf_ingestion, nport_ingestion,
    sec_refresh, risk_calc, portfolio_eval, drift_check,
    regime_fit, screening_batch, watchlist_batch,
    ingestion, instrument_ingestion,
)

WORKER_REGISTRY: dict[str, Callable] = {
    "macro_ingestion": macro_ingestion.run_macro_ingestion,
    "benchmark_ingest": benchmark_ingest.run_benchmark_ingest,
    "treasury_ingestion": treasury_ingestion.run_treasury_ingestion,
    "ofr_ingestion": ofr_ingestion.run_ofr_ingestion,
    "bis_ingestion": bis_ingestion.run_bis_ingestion,
    "imf_ingestion": imf_ingestion.run_imf_ingestion,
    "nport_ingestion": nport_ingestion.run_nport_ingestion,
    "sec_refresh": sec_refresh.run_sec_refresh,
    "risk_calc": risk_calc.run_risk_calc,
    "portfolio_eval": portfolio_eval.run_portfolio_eval,
    "drift_check": drift_check.run_drift_check,
    "regime_fit": regime_fit.run_regime_fit,
    "screening_batch": screening_batch.run_screening_batch,
    "watchlist_batch": watchlist_batch.run_watchlist_batch,
    "ingestion": ingestion.run_ingestion,
    "instrument_ingestion": instrument_ingestion.run_instrument_ingestion,
}
```

**`infra/cloudflare/cron/wrangler.toml`**
```toml
name = "netz-cron"
main = "src/index.ts"
compatibility_date = "2025-12-01"

[triggers]
crons = [
  "0 6 * * *",     # daily-0600: macro_ingestion, benchmark_ingest, treasury_ingestion
  "0 6 30 * *",    # daily-0630: ingestion, instrument_ingestion
  "0 7 * * *",     # daily-0700: risk_calc
  "30 7 * * *",    # daily-0730: portfolio_eval, drift_check, regime_fit
  "0 8 * * *",     # daily-0800: screening_batch, watchlist_batch
  "0 8 * * 1",     # weekly-mon: ofr_ingestion
  "0 5 1 */3 *",   # quarterly: sec_refresh, nport_ingestion, bis_ingestion, imf_ingestion
]

[vars]
WORKERS_ORIGIN = "https://netz-workers.<account>.containers.cloudflare.com"
```

**`infra/cloudflare/cron/src/index.ts`**
```typescript
interface Env {
  WORKERS_ORIGIN: string;
  WORKER_SECRET: string;
}

const SCHEDULE_MAP: Record<string, string[]> = {
  "0 6 * * *":     ["macro_ingestion", "benchmark_ingest", "treasury_ingestion"],
  "0 6 30 * *":    ["ingestion", "instrument_ingestion"],
  "0 7 * * *":     ["risk_calc"],
  "30 7 * * *":    ["portfolio_eval", "drift_check", "regime_fit"],
  "0 8 * * *":     ["screening_batch", "watchlist_batch"],
  "0 8 * * 1":     ["ofr_ingestion"],
  "0 5 1 */3 *":   ["sec_refresh", "nport_ingestion", "bis_ingestion", "imf_ingestion"],
};

export default {
  async scheduled(event: ScheduledEvent, env: Env, ctx: ExecutionContext) {
    const workers = SCHEDULE_MAP[event.cron];
    if (!workers) return;

    await fetch(`${env.WORKERS_ORIGIN}/internal/workers/dispatch`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Worker-Secret": env.WORKER_SECRET,
      },
      body: JSON.stringify({ workers }),
    });
  },
};
```

**`infra/cloudflare/cron/package.json`**
```json
{
  "name": "netz-cron",
  "private": true,
  "scripts": { "deploy": "wrangler deploy" },
  "devDependencies": { "wrangler": "^4" }
}
```

### Arquivos modificados

- **`backend/app/core/config/settings.py`** — adicionar `worker_dispatch_secret: str = ""`
- **`backend/app/main.py`** — montar router: `app.include_router(internal_router)`

### Dependências

Fase 1 (container workers) + Fase 2 (gateway sabe bloquear `/internal/*`).

### Critério de conclusão

```bash
# Simular cron trigger local
curl -X POST http://localhost:8000/internal/workers/dispatch \
  -H "X-Worker-Secret: $SECRET" \
  -H "Content-Type: application/json" \
  -d '{"workers": ["macro_ingestion"]}'
# → {"status": "dispatched", "workers": ["macro_ingestion"]}

# Sem secret → 403
curl -X POST http://localhost:8000/internal/workers/dispatch \
  -H "Content-Type: application/json" \
  -d '{"workers": ["macro_ingestion"]}'
# → 403
```

---

## Fase 4 — Frontends SvelteKit → Cloudflare Pages

**Objetivo:** Migrar 3 apps SvelteKit de `adapter-node` (Railway) para `adapter-cloudflare` (Pages).

**Decisão: `@sveltejs/adapter-cloudflare` (SSR via Workers), não `adapter-static`.**
Justificativa:
1. SSE streaming requer server-side fetch com auth headers — `adapter-static` não tem server
2. Clerk auth precisa de hooks de servidor para validar JWT e proteger rotas
3. Pages Functions (Workers) suportam streaming responses
4. Zero config para deploy (Git integration nativa)

### Arquivos modificados

**`frontends/credit/svelte.config.js`** (idem wealth, admin)
```diff
- import adapter from "@sveltejs/adapter-node";
+ import adapter from "@sveltejs/adapter-cloudflare";

  export default {
    kit: {
-     adapter: adapter({ out: "build" }),
+     adapter: adapter({
+       routes: { include: ["/*"], exclude: ["<all>"] },
+     }),
    },
  };
```

**`frontends/credit/package.json`** (idem wealth, admin)
```diff
  "devDependencies": {
-   "@sveltejs/adapter-node": "^5",
+   "@sveltejs/adapter-cloudflare": "^5",
  }
```

### Arquivos criados

**`frontends/credit/wrangler.toml`** (idem wealth, admin — apenas `name` muda)
```toml
name = "netz-credit"
compatibility_date = "2025-12-01"
pages_build_output_dir = ".svelte-kit/cloudflare"

[vars]
PUBLIC_BACKEND_URL = "https://api.netz.app"
```

> Cada frontend é um Cloudflare Pages project separado, com Git integration.
> Build command configurado no Dashboard: `cd frontends/credit && pnpm install && pnpm build`
> Root directory: `/` (monorepo — Cloudflare Pages detecta o build command)

### Dependências

Fase 2 (gateway deve estar acessível como `PUBLIC_BACKEND_URL`).

### Critério de conclusão

```bash
cd frontends/credit
pnpm install
pnpm build  # deve gerar .svelte-kit/cloudflare/ sem erros

# Repetir para wealth e admin
```

---

## Fase 5 — Storage: Ativar R2, Remover ADLS

**Objetivo:** Confirmar R2 como único storage de produção e remover ADLS.

### Arquivos modificados

**`backend/app/services/storage_client.py`**
```diff
  def create_storage_client() -> StorageClient:
-     if settings.feature_r2_enabled:
-         return R2StorageClient()
-     if settings.feature_adls_enabled:
-         return ADLSStorageClient()
-     return LocalStorageClient()
+     if settings.feature_r2_enabled:
+         return R2StorageClient()
+     return LocalStorageClient()
```
- Remover classe `ADLSStorageClient` inteira (linhas ~300-399)
- Manter `LocalStorageClient` (dev) e `R2StorageClient` (prod)

**`backend/app/core/config/settings.py`**
```diff
- feature_adls_enabled: bool = False
- adls_account_name: str = ""
- adls_account_key: str = ""
- adls_container_name: str = ""
- adls_connection_string: str = ""
```

**`backend/app/domains/admin/routes/health.py`**
- Remover check de saúde ADLS (se existir no endpoint `/health/services`)

### Dependências

Nenhuma (pode ser feita em paralelo com Fases 0-4, mas logicamente vem depois para não quebrar rollback).

### Critério de conclusão

```bash
make check  # lint + typecheck + test — tudo passa sem referência a ADLS
grep -r "adls\|ADLSStorage\|feature_adls" backend/  # → zero matches (exceto migrations)
```

---

## Fase 6 — Remover Dependências Azure

**Objetivo:** Eliminar todo código e config Azure do repositório.

### Arquivos a remover/arquivar

```
# Dead code Azure (verificar antes de deletar)
backend/app/services/azure_kb_adapter.py         # Azure Search adapter (replaced by pgvector)
backend/ai_engine/extraction/search_upsert_service.py  # Azure Search upsert (if deprecated)
```

### Arquivos modificados

**`backend/app/core/config/settings.py`** — remover campos deprecated:
```diff
- # ── DEPRECATED (Azure services — kept for rollback, 2026-03-18) ──
- storage_account_url: str = ""
- keyvault_url: str = ""
- service_bus_namespace: str = ""
- applicationinsights_connection_string: str = ""
- azure_openai_endpoint: str = ""
- azure_openai_key: str = ""
- azure_search_endpoint: str = ""
- azure_search_key: str = ""
- SEARCH_INDEX_NAME: str = ""
- SEARCH_CHUNKS_INDEX_NAME: str = ""
```

**`backend/pyproject.toml`** — confirmar que NÃO tem azure-* (já não tem, mas verificar)

**`.env.example`** — remover variáveis Azure deprecated:
```diff
- # AZURE_OPENAI_ENDPOINT=
- # AZURE_OPENAI_KEY=
- # AZURE_SEARCH_ENDPOINT=
- # AZURE_SEARCH_KEY=
- # ADLS_ACCOUNT_NAME=
- # ADLS_ACCOUNT_KEY=
- # ADLS_CONTAINER_NAME=
- # ADLS_CONNECTION_STRING=
- # FEATURE_ADLS_ENABLED=false
```

**`railway.toml`** — arquivar (mover para `infra/archived/railway.toml`)

### Dependências

Fase 5 (ADLS já removido).

### Critério de conclusão

```bash
make check  # tudo passa
grep -ri "azure\|ADLS\|service.bus\|keyvault" backend/app/ --include="*.py" | grep -v "migration\|__pycache__"  # → zero
# Exceção: comentários em migrations são aceitáveis
```

---

## Fase 7 — CI/CD

**Objetivo:** GitHub Actions faz build+push da imagem Docker; Cloudflare Pages faz deploy dos frontends via Git.

### Arquivos criados

**`.github/workflows/deploy.yml`**
```yaml
name: Deploy to Cloudflare
on:
  push:
    branches: [main]

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build Docker image
        run: docker build -f infra/cloudflare/Dockerfile -t netz-backend .

      - name: Push to Cloudflare Container Registry
        run: |
          echo "${{ secrets.CF_API_TOKEN }}" | docker login registry.cloudflare.com -u unused --password-stdin
          docker tag netz-backend registry.cloudflare.com/${{ secrets.CF_ACCOUNT_ID }}/netz-backend:${{ github.sha }}
          docker push registry.cloudflare.com/${{ secrets.CF_ACCOUNT_ID }}/netz-backend:${{ github.sha }}

      - name: Deploy containers
        run: |
          npx wrangler containers deploy --config infra/cloudflare/wrangler.backend.jsonc
          npx wrangler containers deploy --config infra/cloudflare/wrangler.workers.jsonc

      - name: Deploy gateway + cron workers
        run: |
          cd infra/cloudflare/gateway && npx wrangler deploy
          cd infra/cloudflare/cron && npx wrangler deploy
        env:
          CLOUDFLARE_API_TOKEN: ${{ secrets.CF_API_TOKEN }}

  # Frontends: Cloudflare Pages Git integration (auto-deploy on push to main)
  # Configured per-project in Cloudflare Dashboard, not in this workflow.
```

### Arquivos modificados

**`.github/workflows/ci.yml`** — sem mudanças (CI continua igual: lint + typecheck + test)

### Secrets necessários

| Onde | Secret | Descrição |
|------|--------|-----------|
| GitHub | `CF_API_TOKEN` | Cloudflare API token com permissões Workers + Containers + R2 |
| GitHub | `CF_ACCOUNT_ID` | Cloudflare account ID |
| Cloudflare Dashboard | `DATABASE_URL` | Timescale Cloud connection string |
| Cloudflare Dashboard | `REDIS_URL` | Upstash Redis URL |
| Cloudflare Dashboard | `OPENAI_API_KEY` | OpenAI API key |
| Cloudflare Dashboard | `MISTRAL_API_KEY` | Mistral OCR API key |
| Cloudflare Dashboard | `CLERK_SECRET_KEY` | Clerk backend secret |
| Cloudflare Dashboard | `WORKER_SECRET` | Shared secret entre Cron Worker e backend |
| Cloudflare Dashboard | `R2_ACCESS_KEY_ID` | R2 S3-compatible credentials |
| Cloudflare Dashboard | `R2_SECRET_ACCESS_KEY` | R2 S3-compatible credentials |
| Cloudflare Pages | `PUBLIC_BACKEND_URL` | URL do gateway (por app) |
| Cloudflare Pages | `PUBLIC_CLERK_PUBLISHABLE_KEY` | Clerk frontend key (por app) |

### Dependências

Fases 0-4 (todos os artefatos Cloudflare devem existir).

### Critério de conclusão

```bash
git push origin main  # triggers deploy
# Backend container: healthy em /health
# Workers container: healthy (sleep-after-idle)
# Gateway: proxy funcional
# Cron: scheduled events visíveis no Cloudflare Dashboard
# Pages: 3 apps com SSR funcional
```

---

## Fase 8 — Validação e Rollback

**Objetivo:** Smoke tests, DNS cutover, e estratégia de rollback.

### Checklist de Smoke Tests

| Serviço | Teste | Comando |
|---------|-------|---------|
| Backend health | `/health` retorna 200 | `curl https://api.netz.app/health` |
| Auth | JWT Clerk validado | `curl -H "Authorization: Bearer $TOKEN" https://api.netz.app/api/v1/admin/health` |
| SSE streaming | Event stream funcional | `curl -N https://api.netz.app/api/v1/jobs/{id}/stream` |
| R2 storage | Upload + read | Via admin health `/api/v1/admin/health/services` |
| Workers dispatch | Cron trigger | `curl -X POST .../internal/workers/dispatch -H "X-Worker-Secret: ..."` |
| Frontend credit | SSR + Clerk login | Browser: `https://credit.netz.app` |
| Frontend wealth | SSR + Clerk login | Browser: `https://wealth.netz.app` |
| Frontend admin | SSR + Clerk login | Browser: `https://admin.netz.app` |
| DB connectivity | Timescale Cloud | `/api/v1/admin/health/services` |
| Redis | Upstash | `/api/v1/admin/health/services` |

### Estratégia de Rollback

**DNS-based cutover (não feature flag):**
1. Cloudflare DNS: `api.netz.app` → gateway Worker (novo)
2. Se falhar: trocar DNS de volta para Railway (Railway mantido ativo por 7 dias após cutover)
3. Frontends: Cloudflare Pages tem rollback instantâneo para deploy anterior
4. Workers: advisory locks + Redis idempotency impedem duplicação se ambos ambientes estiverem ativos

**Ordem de cutover:**
1. Deploy tudo no Cloudflare (sem DNS change)
2. Smoke tests contra URLs `.workers.dev` / `.pages.dev`
3. DNS cutover: `api.netz.app` → gateway
4. DNS cutover: `credit.netz.app`, `wealth.netz.app`, `admin.netz.app` → Pages
5. Monitorar 48h
6. Desligar Railway

### Monitoramento

- **Cloudflare Workers Analytics** — latência, erros, invocações por Worker
- **Container Logs** — `wrangler containers logs netz-backend`
- **Timescale query health** — `GET /api/v1/admin/health/services` (latência PostgreSQL)
- **Worker health** — `GET /api/v1/admin/health/workers` (last_run, duration, errors)

### Dependências

Todas as fases anteriores.

### Critério de conclusão

- Todos os smoke tests passando contra URLs Cloudflare
- DNS cutover completo
- Railway desligado
- 48h sem incidentes

---

## Resumo de Arquivos

### Novos (12 arquivos)
| Fase | Arquivo |
|------|---------|
| 0 | `infra/cloudflare/Dockerfile` |
| 0 | `infra/cloudflare/.dockerignore` |
| 1 | `infra/cloudflare/wrangler.backend.jsonc` |
| 1 | `infra/cloudflare/wrangler.workers.jsonc` |
| 2 | `infra/cloudflare/gateway/wrangler.toml` |
| 2 | `infra/cloudflare/gateway/src/index.ts` |
| 2 | `infra/cloudflare/gateway/package.json` |
| 3 | `infra/cloudflare/cron/wrangler.toml` |
| 3 | `infra/cloudflare/cron/src/index.ts` |
| 3 | `infra/cloudflare/cron/package.json` |
| 3 | `backend/app/domains/admin/routes/internal.py` |
| 3 | `backend/app/domains/admin/routes/worker_registry.py` |

### Modificados (9 arquivos)
| Fase | Arquivo | Mudança |
|------|---------|---------|
| 3 | `backend/app/core/config/settings.py` | + `worker_dispatch_secret` |
| 3 | `backend/app/main.py` | + mount internal router |
| 4 | `frontends/credit/svelte.config.js` | adapter-node → adapter-cloudflare |
| 4 | `frontends/wealth/svelte.config.js` | adapter-node → adapter-cloudflare |
| 4 | `frontends/admin/svelte.config.js` | adapter-node → adapter-cloudflare |
| 4 | `frontends/*/package.json` (×3) | dep swap |
| 5 | `backend/app/services/storage_client.py` | remover ADLSStorageClient |
| 5 | `backend/app/domains/admin/routes/health.py` | remover ADLS health check |

### Removidos/Arquivados (3+ arquivos)
| Fase | Arquivo | Ação |
|------|---------|------|
| 6 | `railway.toml` | mover para `infra/archived/` |
| 6 | `backend/app/services/azure_kb_adapter.py` | deletar |
| 6 | Settings Azure fields | remover de settings.py |

### Sem mudança
- `backend/app/domains/wealth/workers/*` — workers intocados
- `backend/ai_engine/*` — pipeline intocado
- `backend/vertical_engines/*` — engines intocados
- `backend/quant_engine/*` — quant intocado
- `.github/workflows/ci.yml` — CI intocado
- `docker-compose.yml` — dev local intocado

## Verificação End-to-End

```bash
# 1. Build local
docker build -f infra/cloudflare/Dockerfile -t netz-backend .

# 2. Run com docker-compose (DB + Redis) + container
make up
docker run --rm --network host \
  -e DATABASE_URL=postgresql+asyncpg://netz:password@localhost:5434/netz_engine \
  -e REDIS_URL=redis://localhost:6379/0 \
  -e APP_ENV=development \
  netz-backend

# 3. Testes
make check  # lint + typecheck + test (1439+ tests)

# 4. Smoke
curl http://localhost:8000/health
curl -X POST http://localhost:8000/internal/workers/dispatch \
  -H "X-Worker-Secret: test" -H "Content-Type: application/json" \
  -d '{"workers": ["macro_ingestion"]}'

# 5. Frontend
cd frontends/credit && pnpm install && pnpm build  # adapter-cloudflare output
```
