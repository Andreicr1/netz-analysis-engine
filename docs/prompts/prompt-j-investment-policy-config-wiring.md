# Prompt J — Investment Policy: Corrigir Leitura e Escrita de Configs

## Contexto

A página Investment Policy está completamente desconectada do backend.
Todos os valores mostrados são defaults hardcoded — nada é lido nem salvo no DB.

O super_admin (Andrei) tem acesso total aos endpoints `/admin/configs/` — o role
`SUPER_ADMIN` está no JWT do Clerk e o `require_super_admin` passa corretamente.
O problema é de mapeamento de nomes, não de permissão.

## Diagnóstico preciso

3 desconexões simultâneas:

### 1. Vertical errado no +page.server.ts
```typescript
// ERRADO — filtra por "wealth", backend registra como "liquid_funds"
configs.filter((c: any) => c.vertical === "wealth")
// Resultado: configs = [] sempre
```

### 2. Config types inexistentes nos saves
O frontend chama endpoints que não existem:
- `PATCH /admin/configs/wealth/risk_limits`     → 404
- `PATCH /admin/configs/wealth/scoring_weights` → 404
- `PATCH /admin/configs/wealth/universe_filters` → 404
- `PATCH /admin/configs/wealth/rebalancing`      → 404

### 3. Mapeamento errado entre config types
| IP espera (errado) | Backend tem (correto) | Onde estão os dados |
|---|---|---|
| `risk_limits` | `calibration` | `calibration.cvar_limits.{growth,moderate,conservative}` |
| `scoring_weights` | `scoring` | `scoring.fund.weights` |
| `universe_filters` | não existe | defaults hardcoded são OK por ora |
| `rebalancing` | `calibration` | `calibration.drift_bands` |
| `portfolio_profiles` | `portfolio_profiles` | `portfolio_profiles.profiles.{growth,moderate,conservative}` |

## Pré-leitura obrigatória

Antes de qualquer mudança, leia:
- D:\Projetos\netz-analysis-engine\frontends\wealth\src\routes\(app)\investment-policy\+page.server.ts
- D:\Projetos\netz-analysis-engine\frontends\wealth\src\routes\(app)\investment-policy\+page.svelte  (linhas 1-160)
- D:\Projetos\netz-analysis-engine\backend\app\domains\admin\routes\configs.py
- D:\Projetos\netz-analysis-engine\backend\app\core\config\registry.py  (ver todos os config_types registrados)

## O que NÃO fazer

- NÃO criar novos endpoints no backend — usar os existentes
- NÃO alterar `require_super_admin` — está correto
- NÃO alterar a estrutura da página (sliders, UI) — só os dados
- NÃO usar `PATCH` — o backend usa `PUT /admin/configs/{vertical}/{config_type}`
- NÃO assumir que `org_id` não é necessário — o PUT exige `?org_id=` para overrides

## Fix 1 — +page.server.ts: corrigir vertical e endpoint

```typescript
// D:\Projetos\netz-analysis-engine\frontends\wealth\src\routes\(app)\investment-policy\+page.server.ts

import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ locals }) => {
    const api = createServerApiClient(locals.token);

    // Buscar todos os configs do vertical liquid_funds (não "wealth")
    const [configsResult] = await Promise.allSettled([
        api.get("/admin/configs/"),
    ]);

    const configs = configsResult.status === "fulfilled"
        ? (configsResult.value as any[]).filter((c: any) => c.vertical === "liquid_funds")
        : [];

    return { configs, token: locals.token };
};
```

## Fix 2 — +page.svelte: corrigir findConfig e saves

### 2a. Corrigir findConfig para ler dos config_types corretos

Localizar no +page.svelte:
```typescript
function findConfig(type: string): Record<string, any> | undefined {
    return data.configs.find((c: any) => c.config_type === type)?.value;
}
```

Substituir por:
```typescript
function findConfig(type: string): Record<string, any> | undefined {
    return data.configs.find((c: any) => c.config_type === type)?.value;
}

// Helpers para extrair dados dos config_types reais
function getCalibration(): Record<string, any> {
    return findConfig("calibration") ?? {};
}
function getPortfolioProfiles(): Record<string, any> {
    return findConfig("portfolio_profiles") ?? {};
}
function getScoringConfig(): Record<string, any> {
    return findConfig("scoring") ?? {};
}
```

### 2b. Corrigir a inicialização de riskLimits

Localizar:
```typescript
const savedRiskLimits = findConfig("risk_limits");
let riskLimits = $state(structuredClone(savedRiskLimits ?? defaultRiskLimits));
```

Substituir por:
```typescript
// Ler de calibration.cvar_limits — mapeando para o shape esperado pela UI
const calibration = findConfig("calibration") ?? {};
const cvarLimits = calibration.cvar_limits ?? {};
const savedRiskLimits = cvarLimits && Object.keys(cvarLimits).length > 0 ? {
    conservative: {
        cvar_limit:   Math.abs((cvarLimits.conservative?.cvar_95_lm ?? -0.05) * 100),
        var_limit:    Math.abs((cvarLimits.conservative?.cvar_95_lm ?? -0.05) * 100 * 0.8),
        max_drawdown: Math.abs((cvarLimits.conservative?.cvar_95_lm ?? -0.05) * 100 * 3),
        min_liquidity: 80,
    },
    balanced: {
        cvar_limit:   Math.abs((cvarLimits.moderate?.cvar_95_lm ?? -0.08) * 100),
        var_limit:    Math.abs((cvarLimits.moderate?.cvar_95_lm ?? -0.08) * 100 * 0.75),
        max_drawdown: Math.abs((cvarLimits.moderate?.cvar_95_lm ?? -0.08) * 100 * 3),
        min_liquidity: 60,
    },
    aggressive: {
        cvar_limit:   Math.abs((cvarLimits.growth?.cvar_95_lm ?? -0.15) * 100),
        var_limit:    Math.abs((cvarLimits.growth?.cvar_95_lm ?? -0.15) * 100 * 0.67),
        max_drawdown: Math.abs((cvarLimits.growth?.cvar_95_lm ?? -0.15) * 100 * 2.3),
        min_liquidity: 40,
    },
} : null;
let riskLimits = $state(structuredClone(savedRiskLimits ?? defaultRiskLimits));
```

### 2c. Corrigir a inicialização de scoringWeights

Localizar:
```typescript
const savedScoring = findConfig("scoring_weights");
let scoringWeights = $state(structuredClone(savedScoring ?? defaultScoringWeights));
```

Substituir por:
```typescript
// Ler de scoring.fund.weights
const scoringRaw = findConfig("scoring") ?? {};
const scoringFundWeights = scoringRaw?.fund?.weights ?? {};
const savedScoring = Object.keys(scoringFundWeights).length > 0 ? {
    return_consistency:    Math.round((scoringFundWeights.pct_positive_months  ?? 0.2) * 100),
    risk_adjusted_return:  Math.round((scoringFundWeights.sharpe_ratio         ?? 0.3) * 100),
    drawdown_control:      Math.round((scoringFundWeights.max_drawdown         ?? 0.25) * 100),
    information_ratio:     Math.round((scoringFundWeights.correlation_diversification ?? 0.25) * 100),
    flows_momentum:        0,
    fee_efficiency:        0,
} : null;
let scoringWeights = $state(structuredClone(savedScoring ?? defaultScoringWeights));
```

### 2d. Corrigir saveRiskLimits

Localizar:
```typescript
async function saveRiskLimits() {
    riskLimitsSaving = true;
    try {
        await api.patch("/admin/configs/wealth/risk_limits", { value: structuredClone(riskLimits) });
```

Substituir por:
```typescript
async function saveRiskLimits() {
    riskLimitsSaving = true;
    try {
        // Converter de volta para o formato calibration.cvar_limits
        const calibrationPatch = structuredClone(getCalibration());
        calibrationPatch.cvar_limits = {
            conservative: {
                cvar_95_lm: -(riskLimits.conservative.cvar_limit / 100),
                warning_threshold: 0.8,
                breach_consecutive_days: 5,
            },
            moderate: {
                cvar_95_lm: -(riskLimits.balanced.cvar_limit / 100),
                warning_threshold: 0.8,
                breach_consecutive_days: 3,
            },
            growth: {
                cvar_95_lm: -(riskLimits.aggressive.cvar_limit / 100),
                warning_threshold: 0.8,
                breach_consecutive_days: 5,
            },
        };
        // PUT /admin/configs/{vertical}/{config_type}?org_id={org_id}
        // Requer If-Match header com a versão atual
        const orgId = data.configs.find((c: any) => c.config_type === "calibration")?.org_id
            ?? data.configs.find((c: any) => c.vertical === "liquid_funds")?.org_id;
        const currentVersion = data.configs.find((c: any) => c.config_type === "calibration")?.version ?? 0;
        await api.put(
            `/admin/configs/liquid_funds/calibration${orgId ? `?org_id=${orgId}` : ""}`,
            { value: calibrationPatch },
            { headers: { "If-Match": String(currentVersion) } },
        );
        riskLimitsSnapshot = JSON.stringify(riskLimits);
        showToast("Risk limits saved");
    } catch (e) {
        showToast("Failed to save risk limits", "error");
    } finally {
        riskLimitsSaving = false;
    }
}
```

### 2e. Corrigir saveScoringWeights

Localizar:
```typescript
async function saveScoringWeights() {
    scoringSaving = true;
    try {
        await api.patch("/admin/configs/wealth/scoring_weights", { value: structuredClone(scoringWeights) });
```

Substituir por:
```typescript
async function saveScoringWeights() {
    scoringSaving = true;
    try {
        // Converter de volta para scoring.fund.weights
        const scoringPatch = structuredClone(getScoringConfig());
        if (!scoringPatch.fund) scoringPatch.fund = {};
        scoringPatch.fund.weights = {
            max_drawdown:              scoringWeights.drawdown_control      / 100,
            sharpe_ratio:              scoringWeights.risk_adjusted_return  / 100,
            pct_positive_months:       scoringWeights.return_consistency    / 100,
            correlation_diversification: scoringWeights.information_ratio   / 100,
        };
        const orgId = data.configs.find((c: any) => c.config_type === "scoring")?.org_id;
        const currentVersion = data.configs.find((c: any) => c.config_type === "scoring")?.version ?? 0;
        await api.put(
            `/admin/configs/liquid_funds/scoring${orgId ? `?org_id=${orgId}` : ""}`,
            { value: scoringPatch },
            { headers: { "If-Match": String(currentVersion) } },
        );
        scoringSnapshot = JSON.stringify(scoringWeights);
        showToast("Scoring weights saved");
    } catch (e) {
        showToast("Failed to save scoring weights", "error");
    } finally {
        scoringSaving = false;
    }
}
```

### 2f. saveUniverseFilters e saveRebalancingRules

Esses dois não têm config_type próprio no backend. Por ora, salvar apenas localmente
(estado Svelte) sem persistência, e adicionar um comentário explicando:

```typescript
async function saveUniverseFilters() {
    // universe_filters não tem config_type dedicado no backend ainda.
    // Aplicado apenas localmente na sessão.
    filtersSaving = true;
    filtersSnapshot = JSON.stringify(universeFilters);
    showToast("Universe filters applied (session only)");
    filtersSaving = false;
}

async function saveRebalancingRules() {
    // rebalancing não tem config_type dedicado no backend ainda.
    // Os parâmetros de drift estão em calibration.drift_bands.
    // TODO: persistir em calibration.drift_bands.
    rebalancingSaving = true;
    rebalancingSnapshot = JSON.stringify(rebalancingRules);
    showToast("Rebalancing rules applied (session only)");
    rebalancingSaving = false;
}
```

## Fix 3 — Verificar que api.put aceita headers customizados

O `createClientApiClient` precisa suportar passar `headers` extras no PUT.
Verificar se o método `put` aceita options:

```powershell
Select-String -Path "D:\Projetos\netz-analysis-engine\frontends\wealth\src\lib\api\client.ts" -Pattern "put|patch" | Select-Object Line
```

Se o método `put` não aceitar headers customizados, adicionar suporte:
```typescript
// Em client.ts, método put
async put<T>(path: string, body: unknown, options?: { headers?: Record<string, string> }): Promise<T> {
    return this.request<T>("PUT", path, body, options?.headers);
}
```

## Verificação

Após as mudanças:

```bash
# 1. Verificar que configs chegam (sem filtro "wealth")
curl -s -H "Authorization: Bearer $TOKEN" \
  https://api.investintell.com/api/v1/admin/configs/ \
  | python -m json.tool | grep config_type
# Deve mostrar: calibration, portfolio_profiles, scoring, blocks, etc. (vertical=liquid_funds)

# 2. Abrir /investment-policy e verificar que os sliders mostram valores do DB
# CVaR Limit Conservative deve ser ~5% (calibration.cvar_limits.conservative.cvar_95_lm = -0.05 → 5%)
# CVaR Limit Moderate deve ser ~8% (cvar_95_lm = -0.08 → 8%)
# CVaR Limit Growth deve ser ~15% (cvar_95_lm = -0.15 → 15%)

# 3. Alterar um slider e salvar — deve retornar 200, não 404
```

## Definition of Done

- [ ] Investment Policy carrega valores reais do DB (não defaults hardcoded)
- [ ] CVaR sliders refletem os limites em `calibration.cvar_limits`
- [ ] Scoring weights refletem `scoring.fund.weights`
- [ ] Salvar Risk Limits faz PUT em `/admin/configs/liquid_funds/calibration` com 200
- [ ] Salvar Scoring Weights faz PUT em `/admin/configs/liquid_funds/scoring` com 200
- [ ] Universe Filters e Rebalancing mostram toast "session only" (sem erro 404)
- [ ] `pnpm run check` passa sem erros TypeScript

## Notas de diagnóstico

**Por que o backend exige `If-Match`:** O PUT usa optimistic locking.
Se a versão for 0 (default para global), pode retornar 428.
Nesse caso, primeiro fazer GET para obter a versão atual:
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.investintell.com/api/v1/admin/configs/liquid_funds/calibration" \
  | python -m json.tool | grep version
```

**Se o PUT retornar 400 "org_id required":** O endpoint de override exige org_id.
Para atualizar o default global (não um override), usar:
`PUT /admin/configs/defaults/liquid_funds/calibration` (sem org_id, sem If-Match).

**Mapeamento CVaR:** O backend armazena como valor negativo decimal (ex: -0.08 = 8%).
A UI mostra como positivo percentual (ex: 8%). Converter ao ler (abs × 100) e ao salvar (÷ 100 × -1).
