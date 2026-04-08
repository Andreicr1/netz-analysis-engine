# Opus Prompt: Backlog Cleanup — CI Stabilization & Wealth Library Recovery

## Mandatory Reads (faça isto antes de tocar em qualquer arquivo)
1. `backend/manifests/routes.json` e `backend/manifests/workers.json` — manifests stale.
2. `backend/scripts/generate_manifests.py` — script que regenera os manifests.
3. `backend/tests/test_scoring_fee_efficiency.py` — bug está no teste (espera 50.0, código retorna 45.0).
4. `frontends/wealth/src/lib/components/AllocationView.svelte` (linhas 93-95) — `state_referenced_locally`.
5. `git log origin/feat/wealth-library --oneline -5` — saber em que estado a branch da PR #97 está.
6. `gh pr view 97 --json mergeable,headRefOid` — confirmar mergeability atual.

## Contexto
A `main` está consolidada com Sprints S1-S5 (quant) + a purga do Cloudflare (PR #99 mergeado em 2026-04-08). Não há proteção de branch na `main` (`Branch not protected`), então merges manuais sem CI verde são permitidos. O backend roda em Railway, R2 é o único Cloudflare sobrevivente.

Existem **4 frentes pendentes** descobertas pelo expurgo CF, todas pré-existentes ao trabalho que fizemos. Precisamos atacá-las nesta ordem (lowest risk first):

| # | Frente | Tamanho | Bloqueia o quê |
|---|---|---|---|
| 1 | Manifests stale (`routes.json`, `workers.json`) | 1 comando | 4 dos 25 testes do `test-backend` |
| 2 | `svelte-check` (3 errors, 9 warnings em 4 arquivos) | ~30 min | Job inteiro do `check-frontends` |
| 3 | 21 testes restantes do `test-backend` | algumas horas | CI verde da `main` |
| 4 | Rebase + recuperação da PR #97 (Wealth Library) | depende de #3 | Merge da PR #97 |

A migração de CSP (`static/_headers` → `hooks.server.ts`) **NÃO está nesta sprint** — é trabalho de segurança real e merece sessão dedicada.

## Phased Implementation

### Fase 0: Git Workflow
```bash
git checkout main && git pull origin main
```
Confirme que o último commit é `b53a9da Merge pull request #99 from Andreicr1/chore/cloudflare-purge`. Se não for, pare e investigue antes de seguir.

---

### Fase 1: Regenerar Manifests (branch `chore/regen-manifests`)

1. `git checkout -b chore/regen-manifests`
2. `cd backend && python scripts/generate_manifests.py`
3. `cd .. && git diff backend/manifests/` — verificar que apenas `routes.json` e `workers.json` mudaram.
4. `cd backend && python -m pytest tests/test_manifest_freshness.py -v` — devem passar 4/4.
5. Commit:
   ```
   chore(manifests): regenerate routes.json and workers.json

   Both manifest files were stale. test_manifest_freshness.py was
   failing on 4 assertions (test_routes_manifest_byte_equal,
   test_no_undocumented_routes, test_workers_manifest_byte_equal,
   test_no_undocumented_workers). Regenerated via the canonical
   script. No code changes — only the manifests.
   ```
6. PR + merge: `gh pr create --base main --title "chore(manifests): regenerate stale manifests" --body "..." && gh pr merge --merge --delete-branch`

---

### Fase 2: svelte-check (branch `fix/svelte-check-frontends-wealth`)

São **3 errors + 9 warnings** em 4 arquivos do `frontends/wealth/`. Os 3 errors são o mínimo a corrigir (warnings podem ficar).

**Erros (devem virar zero):**

1. **`AllocationView.svelte:93,94,95`** — `state_referenced_locally` em `ssrStrategic`/`ssrTactical`/`ssrEffective`.
   - **Causa:** `let strategic = $state(ssrStrategic as StrategicRow[])` captura só o valor inicial. Em Svelte 5, props devem ser acessadas via `$props()` reativamente.
   - **Fix:** ou (a) usar `let { ssrStrategic } = $props()` no topo e referenciar dentro de `$derived`/`$effect`, ou (b) suprimir explicitamente com `// svelte-ignore state_referenced_locally` se a captura única for intencional (ex: SSR hydration).

2. **`BlendedBenchmarkEditor.svelte:282`** — `a11y_label_has_associated_control`.
   - **Fix:** envolver o `<Input>` dentro do `<label>` ou adicionar `for={inputId}` ao label + `id={inputId}` ao Input.

3. **`screener/analytics/+page.svelte:95`** — `state_referenced_locally` em `initialFundId`.
   - Mesmo padrão do #1.

**Verificação:**
```bash
cd frontends/wealth && pnpm check 2>&1 | grep "svelte-check found"
```
Deve mostrar `0 errors` (warnings ok).

**Commit + PR + merge** com mensagem explicando o padrão Svelte 5 reactivity e por que cada fix é correto.

**O QUE NÃO FAZER NESTA FASE:**
- Não tocar em `ActiveSharePanel.svelte` (a11y warning, não error)
- Não silenciar errors com `// svelte-ignore` sem entender — só use se a captura única for genuinamente intencional
- Não rebaseé/mexa em `feat/wealth-library` ainda

---

### Fase 3: 21 Testes Restantes do test-backend (branch `fix/test-backend-stabilization`)

Após a Fase 1, sobram ~21 testes falhando. Ataque por categoria, **um commit por categoria**:

**Lista exata (de `gh run view 24113955222 --log-failed` rodado anteriormente):**

| Categoria | Testes | Sintoma | Hipótese |
|---|---|---|---|
| `test_extraction_dispatch.py` | `test_dispatch_extraction_background_tasks_uses_unified_pipeline` | `RuntimeError: There is no current event loop in thread 'MainThread'` | `asyncio.get_event_loop()` deprecated em Python 3.12+. Trocar por `asyncio.new_event_loop()` ou usar `pytest-asyncio` markers. |
| `test_global_table_isolation.py` | `test_no_unlisted_global_table_consumers` | `screener_import_service.py` não está no `ALLOWLISTED_GLOBAL_TABLE_CONSUMERS` | Adicionar entry no allowlist com rationale (ler o arquivo, ver o pattern dos outros) |
| `test_instrument_ingestion.py` | `test_beyond_max` | `_resolve_period(5000) == 'max'` mas teste espera `'10y'` | Decidir: (a) corrigir o código para retornar `'10y'` para >10y, ou (b) atualizar o teste se `'max'` é o comportamento correto. Ler o histórico do arquivo via `git log` antes de decidir. |
| `test_manifest_freshness.py` × 4 | já corrigidos na Fase 1 | — | — |
| `test_market_data_ws.py` × 7 | todos os testes WebSocket | precisa investigação | Provavelmente um fixture ou conftest quebrado. Ler `tests/conftest.py` primeiro. |
| `test_phase_a_integration.py::test_plausibility_rejects_extreme_vix` | 1 teste | precisa ler | — |
| `test_portfolio_analytics.py` × 2 | `test_holdings_returns_list`, `test_performance_returns_series` | precisa ler | — |
| `test_portfolio_screener_rest.py` × 6 | screener catalog tests | precisa ler | provavelmente compartilham fixture |
| `test_regional_macro_service.py::test_build_fetch_configs` | 1 teste | precisa ler | — |
| `test_scoring_fee_efficiency.py::test_fee_efficiency_none_defaults_neutral` | 1 teste | `assert 45.0 == 50.0` | **Bug está no teste, não no código.** O código (`scoring_service.py:133`) retorna `45.0` quando `expense_ratio_pct=None` (penaliza opacidade). Atualizar o teste para `assert components["fee_efficiency"] == 45.0` e renomear para `test_fee_efficiency_none_penalty`. |

**Estratégia:**
1. Rode `cd backend && python -m pytest tests/ --tb=line 2>&1 | grep FAIL` para ter a lista atualizada.
2. Comece pelos triviais (allowlist add, fee_efficiency assertion, asyncio fix) — esses dão momentum.
3. Para os WebSocket / portfolio_screener_rest (grupos grandes), ler o conftest e os fixtures antes de mexer em código de produção.
4. Um commit por categoria, mensagem com `fix(tests):` ou `fix(backend):` conforme onde está o bug real.
5. Run `cd backend && python -m pytest tests/ -q` no final — deve mostrar 0 failures (warnings/skips ok).
6. Run `ruff check backend/` — deve ficar limpo (ignorar os erros pré-existentes I001 em `main.py` se não foram tocados).

**O QUE NÃO FAZER NESTA FASE:**
- Não rode `make check` na primeira tentativa — vai disparar lint+typecheck+test e mascarar onde está o problema. Rode `pytest` puro primeiro.
- Não toque em `quant_engine/` — está consolidado e estável.
- Não toque em arquivos de migration — eles estão na ordem correta após S1-S5 + 0094 + 0095.
- Não invente correções para os WS tests sem ler o conftest. Pode ser uma única raiz comum.

---

### Fase 4: Rebase + Recuperação da PR #97 (Wealth Library)

Pré-requisito: **Fase 3 completa** com `test-backend` verde na `main`.

1. `git fetch origin && git checkout feat/wealth-library`
2. **Avaliar drift:** `git log origin/feat/wealth-library..feat/wealth-library --oneline` — provavelmente vai mostrar a tentativa de rebase que eu fiz contra a `main` antiga (sem S3-S5). Decidir entre:
   - **Opção A (recomendada):** descartar o rebase local e refazer contra a main atualizada:
     ```bash
     git reset --hard origin/feat/wealth-library
     git rebase main
     ```
   - **Opção B:** force-push o rebase local primeiro, depois rebasear de novo. Mais ruído no histórico.
3. Resolver conflitos do rebase. Os pontos prováveis (porque `main` agora tem S4+S5):
   - `backend/app/domains/wealth/workers/risk_calc.py` — S4 e S5 modificaram. Provavelmente conflito com qualquer mudança da Wealth Library aqui.
   - Migrations 0094, 0095 — wealth-library tinha 0088-0092 próprios. **Não deve ter conflito** porque os números são diferentes, mas verificar a chain `down_revision`.
   - `mv_unified_funds` — se a wealth-library tocar nessa MV, vai conflitar com 0094/0095.
4. Após rebase limpo:
   ```bash
   cd backend && python -m pytest tests/ -q --tb=line
   ```
   Deve passar (a Fase 3 já corrigiu os 25 testes herdados).
5. `git push origin feat/wealth-library --force-with-lease` (force porque rebase reescreveu commits).
6. **Não merge automaticamente.** Verificar a CI rodando na PR #97 atualizada e me reportar o estado para revisar antes do merge final.

**O QUE NÃO FAZER NESTA FASE:**
- Não tente fazer Fase 4 antes da Fase 3 estar verde.
- Não use `--force` plain — sempre `--force-with-lease`.
- Não toque em arquivos fora do escopo da PR #97 durante o rebase. Se aparecer um conflito em `optimizer_service.py` (S2 file), pause e me avise.

---

## What NOT to do (geral, todas as fases)

- **NÃO tocar em `R2StorageClient`, `R2_*` env vars, ou qualquer coisa relacionada a Cloudflare R2** — é o único CF surface vivo em produção.
- **NÃO alterar `frontends/{credit,wealth}/static/_headers`** — a migração de CSP é trabalho separado, deletar agora é regressão de segurança.
- **NÃO alterar `quant_engine/`, `optimizer_service.py`, `correlation_regime_service.py`, `black_litterman_service.py`, `garch_service.py`, `cvar_service.py`, `drift_service.py`, `stress_scenarios.py`, `scoring_service.py`, `expense_ratio_validator.py`** — todos consolidados nas Sprints S2-S5.
- **NÃO commitar `pnpm-lock.yaml` rebuilds desnecessários** — só se realmente alterou `package.json`.
- **NÃO usar `git stash --include-untracked` sem listar antes o que está untracked** — risco de stashar arquivos importantes (lição aprendida na sessão anterior, ver `docs/superpowers/plans/2026-04-07-discovery-fcl-analysis-page.md`).
- **NÃO usar `git push --force` sem `--with-lease`**.
- **NÃO mergear nada com `--squash`** — preservar commits atômicos é o padrão consolidado deste repo.

## Definition of Done

- [ ] Fase 1 mergeada: `chore/regen-manifests` → main, 4 testes de manifest passando.
- [ ] Fase 2 mergeada: `fix/svelte-check-frontends-wealth` → main, `pnpm check` em `frontends/wealth` mostra 0 errors.
- [ ] Fase 3 mergeada: `fix/test-backend-stabilization` → main, `cd backend && pytest tests/ -q` mostra 0 failures.
- [ ] Fase 4: PR #97 rebaseada contra main, `--force-with-lease` push feito, **CI status reportado para revisão antes do merge final** (NÃO mergear sozinho).
- [ ] Backlog atualizado em `MEMORY.md` (`feedback_*` ou `project_*`) com: "CSP migration ainda pendente" + "PR #97 aguardando revisão final pós-rebase".
- [ ] Cada fase em branch separada, commits atômicos por categoria, PR + merge sem squash.
