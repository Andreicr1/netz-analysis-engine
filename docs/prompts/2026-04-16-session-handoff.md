# Session Handoff — Construction Engine Pipeline (2026-04-16)

**Para a próxima sessão Opus 4.6 (1M):** você está retomando o trabalho de pipeline institutional portfolio construction do Netz Analysis Engine. Andrei vai trazer o resultado do PR-A9 no primeiro turno. Seu papel é verificar, mergear se válido, e coordenar o próximo passo.

## Repo

- Path: `C:\Users\andre\projetos\netz-analysis-engine`
- Branch ativa: `main` (local pode estar ahead; verifique `git fetch origin main && git reset --hard origin/main` se houver conflitos post-squash-merge)
- Plataforma: Windows + docker-compose (PG 16 + Timescale + Redis + FastAPI + SvelteKit wealth)
- Docker: `netz-analysis-engine-db-1` e `netz-analysis-engine-redis-1` rodando há dias
- DB local: `postgresql://netz:netz@localhost:5434/netz_engine`

## Protocolo operacional

1. **Você NÃO implementa diretamente.** Andrei dispara o Opus em sessão paralela contra specs que escrevemos juntos. Seu papel é: (a) verificar o output contra a spec, (b) identificar regressões/bugs, (c) mergear se passa, (d) escrever spec do próximo PR.
2. **Verificação empírica obrigatória:** toda claim de teste passa é verificada com `pytest` local. Toda claim de DB populada é verificada com query SQL direta (use `psycopg` síncrono — asyncpg tem issue `WinError 64` no Windows).
3. **Brutal honesty sobre testes:** se Opus reporta "28/28 green" mas roda mostra "27 passed, 1 failed", flag imediato. Nunca mergear com red tests.
4. **Auto-merge via `gh pr merge <n> --squash --delete-branch --auto`** quando CI verde + pass criteria da spec atendidos.
5. **Memória persistente:** `C:\Users\andre\.claude\projects\C--Users-andre-projetos-netz-analysis-engine\memory\MEMORY.md` — leia no início e atualize no fim de cada PR significativo.
6. **Encoding:** Windows + cp1252 quebra em caracteres Unicode como κ e ρ; use `python -X utf8 -c` ou `.encode('ascii', errors='replace')` em queries que leem `failure_reason`.

## Pipeline atual (PR-A1 → A8 mergeados, A9 em verificação)

Construction engine é uma cascata de 11 steps. Estado:

| PR | Escopo | Status |
|---|---|---|
| PR-A1 | 5Y EWMA + THBB + κ(Σ) guardrail | MERGED |
| PR-A2 | Multi-view Black-Litterman + THBB prior | MERGED |
| PR-A3 | Hybrid Fundamental Factor Model (8 factors, K=6 efetivo) + remediation | MERGED |
| PR-A4 | Job-or-Stream builder (lock 900_101, idempotency triple-layer) | MERGED |
| PR-A5 | Frontend migration para `/portfolios/{id}/build` | MERGED (#184) |
| PR-A6 | Universe auto-import (lock 900_103) + cleanup migration 0139 | MERGED (#185) |
| PR-A7 | Layer 0+2 pre-filter (strategic block + top-50 per block via manager_score) | MERGED (#186) |
| PR-A8 | Layer 3 correlation dedup (union-find, \|ρ\|>0.95, 1Y daily) | MERGED (#187) |
| **PR-A9** | **κ(Σ) threshold recalibration + factor-cov fallback** | **EM VERIFICAÇÃO** |
| PR-A10 | Frontend rendering de `degraded` status + κ/dedup telemetry (SHRINKAGE panel) | NOT STARTED |

## PR-A9 (verificar primeiro)

Spec: `docs/prompts/2026-04-16-pr-a9-kappa-calibration.md` (290 linhas).

**Mudança:**
- `KAPPA_WARN_THRESHOLD`: 1e3 → **1e4**
- `KAPPA_FALLBACK_THRESHOLD`: novo tier = **5e4** (switch para factor-cov)
- `KAPPA_ERROR_THRESHOLD`: 1e4 → **1e6** (pathological only)
- `check_covariance_conditioning` retorna `CovarianceConditioningResult` enum
- `compute_fund_level_inputs` chama `assemble_factor_covariance` (PR-A3) quando `decision == "factor_fallback"`
- Persist `covariance_source` + `kappa_sample` + `kappa_final` em `statistical_inputs` JSONB

**Pass criteria (Section F.2):**
- 3 portfolios `status=succeeded`
- `solver=clarabel` (não heuristic_fallback)
- `n_weights >= 20`
- `covariance_source in ("sample", "factor_model")` — ambos válidos
- `kappa_sample in [1e3, 1e5]` (banda empírica esperada)
- `wall_clock_ms in [45_000, 120_000]`

**Expected outcome:** os 3 portfolios têm κ=2.4e4-3e4 (empírico, pre-A9). Post-A9 caem no WARN band (>1e4, <5e4) → proceed com sample Σ → CLARABEL real.

**Verification commands:**
```python
# python -X utf8 (para evitar UnicodeEncodeError em κ/ρ)
import psycopg
with psycopg.connect('postgresql://netz:netz@localhost:5434/netz_engine') as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT mp.display_name, pcr.status, pcr.wall_clock_ms,
                   pcr.optimizer_trace->>'solver' as solver,
                   pcr.statistical_inputs->'dedup'->>'n_kept' as n_kept,
                   pcr.statistical_inputs->>'covariance_source' as cov_src,
                   pcr.statistical_inputs->>'kappa_sample' as kappa_s,
                   (SELECT COUNT(*) FROM jsonb_object_keys(pcr.weights_proposed)) as n_weights
            FROM portfolio_construction_runs pcr
            JOIN model_portfolios mp ON mp.id = pcr.portfolio_id
            WHERE pcr.started_at > NOW() - INTERVAL '30 minutes'
            ORDER BY pcr.started_at DESC
        """)
        for r in cur.fetchall(): print(r)
```

**Merge se pass, hold se falhar.** Se falhar, diagnosticar: κ_sample ainda > 5e4? Fallback path quebrado? k_factors_effective=0? Disparar patch focado.

## DB state atual (confirmado pós-PR-A8)

```
instruments_org: 3,184 (todos auto-import, 7 blocks populados)
model_portfolios: 3
  - Conservative Preservation (3945cee6-f85d-4903-a2dd-cf6a51e1c6a5) profile=conservative
  - Balanced Income (e5892474-7438-4ac5-85da-217abcf99932) profile=moderate
  - Dynamic Growth (3163d72b-3f8c-427e-9cd2-bead6377b59c) profile=growth
org_id único: 403d8392-ebfa-5890-b740-45da49c556eb
alembic head: 0141_portfolio_status_degraded
Pipeline post-A8: 3,184 → Layer 0+2 → 270-320 → Layer 3 dedup → 92-95 → CLARABEL
κ observado pré-A9: 2.4e4-3.0e4 (acima de 1e4 threshold antigo → status=degraded)
Regime atual: RISK_OFF (stress 36.1/100)
```

## Próximas etapas após PR-A9 merge

Ordem sugerida (flexível conforme priorização do Andrei):

### 1. PR-A10 — Frontend rendering de `degraded` + SHRINKAGE panel (~4h)

- `portfolio-workspace.svelte.ts`: tratar `status === 'degraded'` (load run + render warning badge)
- SHRINKAGE tab panel: mostrar `covariance_source` (sample/factor_model) + `n_kept` (dedup) + `kappa_final`
- Traduzir para human-friendly via `metric-translators.ts` (PR-A5 Section C): κ<1e4="Excelente condicionamento", 1e4-5e4="Aceitável", factor_fallback="Modelo fatorial aplicado"
- Smart-backend/dumb-frontend: zero jargão cru
- Playwright smoke test
- Nenhuma mudança backend

### 2. PR-A11 — Validation Gate Review (~3h)

Investigar por que status=succeeded era emitido com `solver=heuristic_fallback` pré-PR-A7. A correção em PR-A7 agora emite `degraded` corretamente, mas o `_run_construction_async` ainda roda stress/advisor/validation/narrative sobre weights heurísticos — o que pode confundir. Validar se `validation_gate` deveria bloquear early quando solver=heuristic.

### 3. PR-A12 — BL View Consumption por Profile (~4h)

Black-Litterman hoje recebe views genéricas. Cada profile (conservative/moderate/growth) deveria calibrar view confidence diferente. Ex: growth pondera mais views táticas; conservative confia mais no prior equilibrium.

### 4. Alternativas não-lineares

- **Macro Desk redesign execution** — spec `docs/prompts/2026-04-14-macro-desk-redesign.md` (session A backend mergeada, session B frontend possivelmente mergeada; confirmar)
- **Fund Classification Tiingo Phase 1** — spec `project_fund_classification_tiingo.md` em memory, aguarda go-ahead do Andrei
- **Cross-tenant 403 Playwright + DEDUPED multi-pod staging** — deferred do PR-A5 Section G
- **Legacy endpoint removal** (`/model-portfolios/{id}/construct`) — PR-A5 Section E deprecou, aguarda 2 sprints + telemetry zero de `legacy_construct_endpoint_called` warning

## Specs de referência já gravadas

Todas em `docs/prompts/`:
- `2026-04-15-construction-engine-pr-a3-a4-remediation.md`
- `2026-04-15-construction-engine-pr-a5-frontend-migration.md`
- `2026-04-15-construction-engine-pr-a5-section-f1.md`
- `2026-04-16-pr-a6-universe-autoimport.md` (1625L, com erratas e anexos DB+Quant)
- `2026-04-16-pr-a7-universe-prefilter.md`
- `2026-04-16-pr-a8-correlation-dedup.md`
- `2026-04-16-pr-a9-kappa-calibration.md` ← ativa
- `2026-04-16-worker-population-runbook.md` (runbook dos 10 workers, já executado)

## Memory files críticas (ler antes de responder)

`C:\Users\andre\.claude\projects\C--Users-andre-projetos-netz-analysis-engine\memory\`:

- `mandate_high_end_no_shortcuts.md` — zero atalhos, instalar deps se necessário, iterar até passar
- `feedback_consultant_not_implementer.md` — role é strategic consultant + prompt writer, NÃO implementer
- `feedback_specialist_agents_for_design.md` — usar 6 specialist agents (quant, db, svelte5, echarts, platform, ux-flow) para design
- `feedback_visual_validation.md` — validar em browser antes de claim done
- `feedback_no_emojis.md` — zero emojis em todo output
- `feedback_smart_backend_dumb_frontend.md` — sem CVaR/κ/regime/DTW jargon na UI
- `feedback_clean_execution_merge.md` — auto-merge PR quando pass criteria atendidos
- `feedback_retrieval_thresholds.md` — nunca absolute thresholds sem evidência empírica
- `feedback_parallel_gemini_sessions.md` — Andrei roda Gemini em paralelo para stretch budget
- `project_worker_population_complete.md` — workers rodaram 2026-04-16, coverage state
- `project_construction_engine_remediation.md` — histórico PR-A3+A4
- `project_phase4_builder_complete.md` + `project_phase5_live_workbench_complete.md` — frontend state

## Convenções de trabalho

- **Commits:** `git commit -m` via HEREDOC com `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>` no footer
- **PR body:** Summary + Test plan (checklist markdown) + `🤖 Generated with Claude Code` footer (único emoji permitido — padronização)
- **PR title:** formato `feat(wealth): <escopo> (PR-Ax)` ou `fix(wealth): ...`
- **Branch naming:** `feat/pr-ax-<kebab-case-scope>`
- **Nunca commit direto em main** (lesson learned PR-A3 original do Gemini)
- **Nunca `git reset --hard`** sem `git stash -u` primeiro (lesson learned session anterior — destruí 124 linhas uncommitted do Gemini paralelo)

## Especialistas disponíveis via Agent tool

Quando precisar de design thinking:
- `wealth-architect` — arquitetura institutional + UX institucional
- `wealth-portfolio-quant-architect` — quant pipeline (CVaR, BL, factor model, optimizer)
- `financial-timeseries-db-architect` — schema, migrations, SQL, hypertables, performance
- `svelte5-frontend-consistency` — runes, formatters, SSE fetch+ReadableStream, layout cage
- `wealth-echarts-specialist` — chart design institucional
- `wealth-ux-flow-architect` — Discovery→Predictive Allocation→Convex Construction→NAV Lifecycle→Circulatory flow

Invoke **em paralelo** quando possível. Cada spec grande usa 2-3 em paralelo.

## Primeiro turno nesta sessão

Andrei vai enviar o resultado do PR-A9 (provavelmente formato similar ao de PRs anteriores: commit SHA + files + tests passed + smoke results). Seu primeiro turno:

1. Verificar git log + branch state
2. Rodar tests locais (`pytest backend/tests/wealth/ backend/tests/quant_engine/ -q`)
3. Query SQL de Section F.1 da spec PR-A9
4. Avaliar pass criteria Section F.2
5. Se pass → `gh pr merge <n> --squash --delete-branch --auto`, perguntar next step (A10 frontend ou outra direção)
6. Se fail → diagnosticar root cause, escrever patch note para Andrei colar no Opus

**Seja brutalmente honesto.** Se algum número não fecha, flag. Nunca mergear com red tests. Nunca inventar métricas.

---

**End of handoff. Boa sessão.**
