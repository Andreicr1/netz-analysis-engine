# Prompt I — Frontend UX: 5 Problemas de Fluxo (Content, Macro, Portfolio, Analytics, Scores)

## Contexto

Diagnóstico realizado via screenshots de wealth.investintell.com em 2026-03-30.
5 problemas identificados — mix de feature flags, role check, dados faltantes e UX.

Backend: https://api.investintell.com
Frontend: D:\Projetos\netz-analysis-engine\frontends\wealth
Python: D:\Projetos\netz-analysis-engine\backend\.venv\Scripts\python.exe

## Pré-leitura obrigatória

Antes de qualquer mudança, leia:
- D:\Projetos\netz-analysis-engine\backend\app\core\config\settings.py  (linhas 99-105)
- D:\Projetos\netz-analysis-engine\backend\app\domains\wealth\routes\content.py  (linhas 43-49)
- D:\Projetos\netz-analysis-engine\frontends\wealth\src\routes\(app)\+layout.svelte  (sidebar sections)
- D:\Projetos\netz-analysis-engine\frontends\wealth\src\routes\(app)\model-portfolios\+page.svelte
- D:\Projetos\netz-analysis-engine\frontends\wealth\src\routes\(app)\model-portfolios\+page.server.ts
- D:\Projetos\netz-analysis-engine\frontends\wealth\src\routes\(app)\macro\+page.svelte  (primeiras 60 linhas)

## O que NÃO fazer

- Não alterar o backend para desabilitar feature flags permanentemente
- Não criar novos endpoints — usar os existentes
- Não alterar o fluxo de aprovação do Macro Review (está correto)
- Não adicionar `FEATURE_WEALTH_CONTENT` hardcoded no settings.py — usar Railway env var
- Não refatorar o sidebar inteiro — mudanças cirúrgicas apenas

---

## Problema 1 — "Content production feature is not enabled"

**Root cause:** `settings.feature_wealth_content` é `False` por default
(ver `app/core/config/settings.py` linha 103).
O backend retorna 404 em todos os endpoints de `/content/` quando False.
O frontend captura o 404 e exibe o banner de erro.

**Fix: Railway env var**

No Railway dashboard, variáveis de ambiente do serviço backend, adicionar:
```
FEATURE_WEALTH_CONTENT=true
```

Verificar também:
```
FEATURE_WEALTH_FACT_SHEETS=true
FEATURE_WEALTH_MONITORING=true
```

Após adicionar, forçar redeploy Railway (ou o serviço pega automaticamente em alguns minutos).

**Verificação:**
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  https://api.investintell.com/api/v1/content \
  | head -c 200
# Antes: {"detail": "Content production feature is not enabled"}
# Depois: [] ou lista de content items
```

---

## Problema 2 — Portfolio Builder: botão "New Portfolio" invisível

**Root cause:** O botão existe no código mas está atrás de um role check:
```svelte
// model-portfolios/+page.svelte linha 20
const IC_ROLES = ["investment_team", "director", "admin"];
let canCreate = $derived(actorRole !== null && IC_ROLES.includes(actorRole));
```

O `actorRole` vem de `actor?.role` no `+page.server.ts`, que por sua vez
vem do JWT do Clerk. Se o usuário demo não tem role `investment_team`,
`director` ou `admin`, o botão não aparece.

**Fix A — Verificar role no Clerk (preferido):**

Acessar o Clerk Dashboard → Users → selecionar o usuário demo →
Metadata/Organizations → verificar `publicMetadata.role` ou `orgRole`.
Deve ser um dos: `investment_team`, `director`, `admin`.

Se não estiver configurado, atualizar via Clerk Dashboard ou via API:
```bash
# Clerk Management API — atualizar role do usuário demo
curl -X PATCH https://api.clerk.dev/v1/users/{USER_ID} \
  -H "Authorization: Bearer $CLERK_SECRET_KEY" \
  -H "Content-Type: application/json" \
  -d '{"public_metadata": {"role": "investment_team"}}'
```

**Fix B — Diagnóstico local (se role já estiver correto):**

Verificar o que o backend retorna para o actor atual:
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  https://api.investintell.com/api/v1/auth/me \
  | python -m json.tool
# Checar o campo "role" no response
```

Se o campo `role` retornar null ou string diferente das 3 permitidas,
atualizar no Clerk.

---

## Problema 3 — Macro Review: onde gerar e fluxo de aprovação

**Diagnóstico:** O link `/macro` **já existe** no sidebar (seção Portfolio,
item "Macro"). O DB tem 4 macro_reviews (3 approved, 1 pending), todas de
2026-03-27. O fluxo funciona, mas não está óbvio para o usuário.

**O fluxo correto (documentar/comunicar, não alterar código):**
```
1. Sidebar → Portfolio → "Macro"
2. Clicar "Generate Macro Review"
3. Aguardar geração (~30-60s)
4. Clicar "Approve" no review gerado (outro usuário deve aprovar — self-approval blocked)
5. O review aprovado aparece no wizard de Portfolio Builder → step "Macro Inputs"
6. No wizard, selecionar o review desejado antes de construir
```

**Fix UX — Adicionar hint no Portfolio Builder quando não há macro reviews aprovados:**

No arquivo `model-portfolios/create/+page.svelte`, na seção "Macro Inputs"
(em torno da linha 540-548), adicionar um link para `/macro` quando
`macroReviews` estiver vazio:

Localizar o bloco:
```svelte
<h2 class="step-title">Macro Inputs</h2>
<div class="step-optional-banner">
    This step is optional. If skipped, the optimizer uses Black-Litterman market equilibrium prior.
</div>
```

Adicionar após o banner, dentro de `{#if macroReviews.length === 0}`:
```svelte
{#if macroReviews.length === 0}
    <div class="step-empty-hint">
        No approved macro reviews available.
        <a href="/macro" class="step-empty-link">Generate one in Macro →</a>
    </div>
{/if}
```

Adicionar estilo em `<style>`:
```css
.step-empty-hint {
    font-size: var(--ii-text-small, 0.8125rem);
    color: var(--ii-text-muted);
    padding: var(--ii-space-stack-xs, 8px) 0;
}
.step-empty-link {
    color: var(--ii-brand-primary);
    text-decoration: none;
    font-weight: 600;
}
.step-empty-link:hover { text-decoration: underline; }
```

---

## Problema 4 — Analytics: Portfolio 0.00%, Benchmark 43.41%

**Root cause:** O portfolio "Smoke Test Moderate" está em status `Backtesting`
— nunca teve `construct` executado após o Global Instruments Refactor.
Sem construct, não há `fund_selection_schema.weights` e o
`portfolio_nav_synthesizer` não tem dados para gerar NAV sintético.

**Fix: Disparar construct via API**

```python
import httpx, sys
sys.path.insert(0, 'D:/Projetos/netz-analysis-engine/backend')
from app.core.config.settings import settings

BASE_URL = "https://api.investintell.com"
HEADERS  = {
    "Authorization": f"Bearer {settings.dev_token}",
    "X-DEV-ACTOR": settings.dev_org_id,
    "Content-Type": "application/json",
}

PORTFOLIO_ID = "c872b6eb-f065-45b2-ad47-17ec9b3e2a3b"  # Smoke Test Moderate

# 1. Construir
r = httpx.post(
    f"{BASE_URL}/api/v1/model-portfolios/{PORTFOLIO_ID}/construct",
    headers=HEADERS,
    json={},
    timeout=60,
)
print(f"Construct: {r.status_code}")
if r.status_code == 200:
    snap = r.json()
    opt = snap.get("fund_selection_schema", {}).get("optimization", {})
    print(f"  solver: {opt.get('solver')}")
    print(f"  status: {opt.get('status')}")
    print(f"  weights: {snap.get('fund_selection_schema', {}).get('weights')}")

# 2. Sintetizar NAV
r2 = httpx.post(
    f"{BASE_URL}/api/v1/workers/run-portfolio-nav-synthesizer",
    headers=HEADERS,
    json={},
    timeout=120,
)
print(f"NAV synthesizer: {r2.status_code} — {r2.text[:80]}")
```

**Verificar resultado:**
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.investintell.com/api/v1/model-portfolios/c872b6eb-f065-45b2-ad47-17ec9b3e2a3b/nav" \
  | python -m json.tool | head -20
# Deve retornar série NAV com primeiro valor = 1000.0
```

Após NAV gerado, a página de Analytics deve mostrar retorno do portfolio
calculado (não 0.00%).

---

## Problema 5 — Score 0.0 nos fundos do portfolio

**Root cause:** `run_global_risk_metrics` populou `fund_risk_metrics` com
`organization_id = NULL` para 6.074 instrumentos. O screener/portfolio
lê o score, mas a query pode estar filtrando por `organization_id = {org_id}`
ao invés de aceitar NULL.

**Diagnóstico — verificar como o score é lido:**

Localizar o serviço que calcula/lê scores:
```powershell
Select-String -Recurse `
    -Path "D:\Projetos\netz-analysis-engine\backend" `
    -Pattern "fund_risk_metrics.*score|score.*fund_risk" `
    -Include "*.py" | Select-Object Filename, LineNumber, Line
```

O comportamento correto: ao buscar `fund_risk_metrics` para um instrumento,
a query deve aceitar `organization_id IS NULL` (global) **OU** `organization_id = {org_id}` (org-scoped), com preferência para org-scoped quando existir.

**Fix padrão para o SELECT:**
```sql
-- ANTES (bugado — só busca org-scoped)
WHERE instrument_id = :id AND organization_id = :org_id

-- DEPOIS (correto — aceita global ou org-scoped)
WHERE instrument_id = :id
  AND (organization_id = :org_id OR organization_id IS NULL)
ORDER BY organization_id NULLS LAST
LIMIT 1
```

Localizar onde essa query está e corrigir. Arquivo mais provável:
- `app/domains/wealth/workers/risk_calc.py` (função de scoring)
- `app/domains/wealth/routes/screener.py` ou `catalog.py` (endpoint do catalog)
- `vertical_engines/wealth/scoring/` (se existir)

**Verificar via SQL que os dados existem:**
```python
import asyncio, asyncpg, os
from dotenv import load_dotenv
load_dotenv('D:/Projetos/netz-analysis-engine/backend/.env')
DB = os.environ["DIRECT_DATABASE_URL"].replace("postgresql+asyncpg://","postgresql://").replace("postgresql+psycopg://","postgresql://")

async def check():
    conn = await asyncpg.connect(DB)
    # OAKMX instrument_id
    rows = await conn.fetch("""
        SELECT frm.instrument_id, frm.organization_id,
               frm.sharpe_ratio_1y, frm.cvar_95, frm.momentum_score
        FROM fund_risk_metrics frm
        JOIN instruments_universe iu ON iu.instrument_id = frm.instrument_id
        WHERE iu.ticker = 'OAKMX'
        ORDER BY frm.organization_id NULLS LAST
        LIMIT 5
    """)
    for r in rows:
        print(dict(r))
    await conn.close()

asyncio.run(check())
```

Se retornar rows com `organization_id = NULL` e valores não-nulos de
`sharpe_ratio_1y`, o problema é na query de leitura, não nos dados.

**Após corrigir a query, rodar `risk_calc(org_id)` para o tenant demo:**
```python
r3 = httpx.post(
    f"{BASE_URL}/api/v1/workers/run-risk-calc",
    headers=HEADERS,
    json={},
    timeout=300,
)
print(f"risk_calc: {r3.status_code}")
```

---

## Sequência de execução recomendada

1. **Railway:** Adicionar `FEATURE_WEALTH_CONTENT=true` + redeploy → resolve Problema 1
2. **Clerk:** Verificar/corrigir role do usuário demo → resolve Problema 2
3. **Frontend:** Adicionar hint no create wizard → resolve Problema 3 (UX)
4. **API:** Rodar construct + NAV synthesizer para Smoke Test Moderate → resolve Problema 4
5. **Backend:** Corrigir query de score em `fund_risk_metrics` para aceitar NULL → resolve Problema 5

Problemas 1 e 2 são de infraestrutura/config — não requerem mudança de código.
Problema 3 é 1 bloco Svelte.
Problema 4 são 2 chamadas API.
Problema 5 é 1 fix de WHERE clause.

---

## Definition of Done

- [ ] Content page não mostra banner "not enabled", botões Outlook/Flash Report/Spotlight funcionam
- [ ] Model Portfolios page mostra botão "New Portfolio" para o usuário demo
- [ ] Create wizard mostra link para `/macro` quando não há reviews aprovados
- [ ] Analytics mostra Portfolio != 0.00% (NAV sintético gerado)
- [ ] Fund scores != 0.0 no portfolio builder (fund_risk_metrics lido corretamente)

## Verificação final (após todos os fixes)

```bash
# 1. Content habilitado
curl -s -H "Authorization: Bearer $TOKEN" \
  https://api.investintell.com/api/v1/content | jq length

# 2. Role correto
curl -s -H "Authorization: Bearer $TOKEN" \
  https://api.investintell.com/api/v1/auth/me | jq .role

# 3. NAV do portfolio
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.investintell.com/api/v1/model-portfolios/c872b6eb-f065-45b2-ad47-17ec9b3e2a3b/nav" \
  | jq '.[0]'

# 4. Score de OAKMX
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.investintell.com/api/v1/funds/OAKMX/risk" \
  | jq '{sharpe: .sharpe_ratio_1y, cvar: .cvar_95, score: .momentum_score}'
```
