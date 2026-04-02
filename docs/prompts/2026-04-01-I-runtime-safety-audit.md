# Prompt I — Runtime Safety Audit (null guards, type coercion, CRD/CIK mismatches)

## Contexto

Erros encontrados em produção após deploy dos sprints A–H:

1. **`.toFixed()` em valores null/undefined** — `confidence_score.toFixed(1)` crashava quando o campo vinha null do backend. Fix: `Number(x).toFixed()` ou optional chaining.
2. **String→datetime mismatch** — domain models retornam ISO strings, Pydantic schemas esperam `datetime`. FastAPI serializa e dá 500 antes de montar response (CORS nem aparece).
3. **CRD enviado para rota que espera CIK** — `catalog_sql.py` popula `manager_id` com CRD, frontend chama `/sec/managers/{cik}` com esse valor.
4. **Feature flag desligada** — endpoints existem mas retornam 404 via `_require_feature()`. Não é bug, mas confunde.

## Objetivo

Varrer TODO o codebase e encontrar TODAS as ocorrências destes 4 padrões de erro, listando arquivo + linha + fix sugerido. **Não implementar — apenas listar.**

---

## Parte 1 — Frontend: `.toFixed()` / `.toLocaleString()` / `.toPrecision()` sem null guard

**Onde buscar:** `frontends/wealth/src/**/*.svelte` e `frontends/wealth/src/**/*.ts`

**Padrão perigoso:**
```
variavel.toFixed(N)          ← crash se variavel é null/undefined/string
variavel.toLocaleString()    ← idem
variavel.toPrecision(N)      ← idem
```

**Padrão seguro (aceito):**
```
variavel?.toFixed(N)                    ← optional chaining
Number(variavel).toFixed(N)             ← coercion explícita (dentro de null check)
variavel.toFixed?.(N)                   ← optional method call
formatPercent(variavel)                 ← @investintell/ui formatter (já trata null)
formatNumber(variavel)                  ← idem
```

**O que fazer:**
1. `grep -rn '\.toFixed\(' frontends/wealth/src/` — listar TODAS as ocorrências
2. Para cada uma, verificar se há null guard no bloco pai (`{#if x !== null}`, ternário, `??`, `?.`)
3. Classificar: SAFE (tem guard) ou UNSAFE (pode crashar)
4. Repetir para `.toLocaleString(` e `.toPrecision(`

**Exceção:** Chamadas dentro de `formatPercent`, `formatNumber`, `formatCurrency`, `formatAUM`, `formatBps` são SAFE — os formatters já tratam null internamente.

---

## Parte 2 — Frontend: acesso a propriedades de objetos possivelmente null

**Padrão perigoso:**
```svelte
{item.nested.property}           ← crash se item ou nested é null
{data.result.field.toFixed(2)}   ← duplo risco: null + toFixed
```

**Onde buscar:** Componentes que recebem dados de API e renderizam diretamente:
- `frontends/wealth/src/routes/(app)/**/+page.svelte`
- `frontends/wealth/src/lib/components/**/*.svelte`

**Foco nos campos que vêm nullable do backend:**
- `confidence_score`, `screening_score`, `expense_ratio_pct`
- `avg_annual_return_1y`, `avg_annual_return_10y`
- `aum`, `total_assets`, `gross_asset_value`
- `cvar_95_3m`, `sharpe_1y`, `return_1y`, `volatility_1y`
- `growth_tilt`, `equity_pct`, `fixed_income_pct`, `cash_pct`
- `market_value`, `shares`, `weight`

**Método:** Para cada campo acima, grep no frontend e verificar se o acesso tem null guard.

---

## Parte 3 — Backend: str↔datetime mismatch entre domain models e Pydantic schemas

**Padrão perigoso:**
```python
# Domain model (dataclass ou plain class)
class FooResult:
    detected_at: str       # ISO string

# Pydantic schema (API response)
class FooRead(BaseModel):
    detected_at: datetime   # expects datetime object

# Route handler
return FooRead(detected_at=result.detected_at)  # 💥 str passed to datetime field
```

**Onde buscar:**
1. Listar todos os dataclasses em `vertical_engines/` que têm campos `str` com comentário "ISO" ou nome terminando em `_at`, `_date`, `_timestamp`
2. Para cada um, encontrar o schema Pydantic correspondente em `backend/app/domains/wealth/schemas/`
3. Comparar tipos — se domain model tem `str` e schema tem `datetime`, é mismatch
4. Verificar se o route handler faz conversão antes de passar ao schema

**Arquivos prioritários:**
```
vertical_engines/wealth/monitoring/strategy_drift_models.py  ← já fixado
vertical_engines/wealth/dd_report/models.py
vertical_engines/wealth/long_form_report/models.py
vertical_engines/wealth/screener/models.py
vertical_engines/wealth/correlation/models.py
vertical_engines/wealth/attribution/models.py
vertical_engines/wealth/*/models.py                          ← todos
```

---

## Parte 4 — Backend: CRD vs CIK confusion

**Contexto:** `SecManager` tem dois identificadores numéricos:
- `cik` — SEC CIK (pode ser NULL para advisers sem 13F)
- `crd_number` — IARD/CRD (sempre presente)

**Padrão perigoso:** Route parameter chamado `{cik}` mas recebendo CRD do frontend, ou query `WHERE cik = :value` quando o valor é CRD.

**Onde buscar:**
1. Grep por `SecManager.cik ==` em todos os route handlers — verificar se o valor passado pode ser CRD
2. Grep por `manager_id` em `catalog_sql.py` e `catalog.ts` — qual identificador é usado
3. Verificar todos os pontos onde o frontend monta URLs com manager identifiers:
   ```
   grep -rn '/sec/managers/' frontends/wealth/src/
   grep -rn '/manager-screener/managers/' frontends/wealth/src/
   ```
4. Confirmar que `/sec/` routes aceitam CRD (post-fix do commit 1197244) e `/manager-screener/` routes usam CRD natively

---

## Parte 5 — Backend: feature flags que retornam 404 (não 501/503)

**Contexto:** `_require_feature()` helper raises 404 quando feature flag está desligada. Isso é confuso porque 404 normalmente significa "rota não existe", não "funcionalidade desabilitada".

**Onde buscar:**
```
grep -rn '_require_feature\|FEATURE_' backend/app/domains/wealth/routes/
```

**Listar:** Todos os endpoints protegidos por feature flags, e qual o status atual de cada flag em prod (verificar `.env.example` ou `backend/app/core/config/settings.py`).

**Sugestão:** Avaliar se deveria ser 501 (Not Implemented) ou 503 (Service Unavailable) em vez de 404.

---

## Output esperado

Um markdown com 5 seções, cada uma com uma tabela:

```markdown
## 1. Unsafe .toFixed() / .toLocaleString() calls

| File | Line | Expression | Guard? | Status |
|------|------|-----------|--------|--------|
| dd-reports/[fundId]/+page.svelte | 81 | confidence_score.toFixed(1) | {#if !== null} | FIXED (Sprint G) |
| ... | ... | ... | none | UNSAFE |

## 2. Nullable property access without guard
...

## 3. str↔datetime mismatches
...

## 4. CRD/CIK confusion points
...

## 5. Feature flag 404s
...
```

---

## Regras

- **Não implementar fixes** — apenas listar e classificar
- **Priorizar por risco:** P0 = crash em produção, P1 = dados errados, P2 = confuso mas não crashante
- **Ler os arquivos** antes de classificar — não assumir baseado só no grep
- **Ignorar:** código em `vertical_engines/credit/` (vertical separado), testes, scripts
- **Contar totais** no final: X unsafe, Y mismatches, Z confusion points
