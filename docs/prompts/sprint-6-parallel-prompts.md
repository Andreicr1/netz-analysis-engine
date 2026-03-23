# Sprint 6 — Prompts para sessões paralelas
# Repo: D:\Projetos\netz-analysis-engine
# Todos os sprints partem de main. Branch separada por sessão.
# Sprint 5 já está em execução — estas sessões podem iniciar agora.

---

## SESSÃO 1 — feat/ux-sprint-6-credit-memo
## Modelo: Sonnet 4.6
## Independente: toca só frontends/credit/

### Contexto
Ler CLAUDE.md e docs/plans/ux-remediation-plan.md seção Credit antes de tocar código.
Tipos disponíveis em packages/ui/src/types/api.d.ts.
Sprint 5 já completou: Credit.1, Credit.2, Credit.3, Credit.4, Credit.5, Credit.7, Credit.8.

### Section 3.Credit.6 — Domain-language e formatters (pequeno, warm-up)
Arquivo: frontends/credit/src/lib/components/DealStageTimeline.svelte
1. Substituir qualquer new Date(...).toLocaleDateString() por formatDate() de @netz/ui
2. Verificar se ainda há .toFixed() — substituir por formatBps/formatCurrency/formatPercent
3. StatusBadge com resolve do credit status-map existente em frontends/credit/src/lib/utils/status-maps.ts
Commit: feat(credit): domain-language formatter adoption — Section 3.Credit.6

### Section 3.Credit.7 — Memo e reporting workflow hardening
Arquivos:
- frontends/credit/src/lib/components/ICMemoViewer.svelte
- frontends/credit/src/routes/(team)/funds/[fundId]/reporting/+page.svelte

1. ICMemoViewer: gate de exibição do memo — só mostrar quando committee_votes tem quórum
   OU esignature_status === "complete". Mostrar estado pendente explícito se não.
2. Reporting page: substituir geração de report por LongRunningAction de @netz/ui
   wired ao endpoint existente — retorna run_id, polling via GET /jobs/{id}/status
3. Nenhum endpoint novo — só wiring de infraestrutura existente

Commit: feat(credit): memo gate and reporting LongRunningAction — Section 3.Credit.7 complement

---

## SESSÃO 2 — feat/ux-sprint-6-wealth-portfolio
## Modelo: Sonnet 4.6
## Independente: toca só frontends/wealth/

### Contexto
Ler CLAUDE.md e docs/plans/ux-remediation-plan.md seção Wealth antes de tocar código.
Sprint 5 completou: Wealth.1, Wealth.2, Wealth.3, Wealth.4, Wealth.5.
Working tree tem Wealth.6 e risk batch em progresso — verificar estado antes de começar.

### Section 3.Wealth.6 — Portfolio workbench rebuild
Arquivo: frontends/wealth/src/routes/(team)/portfolios/[profile]/+page.svelte

1. Recompor como workspace multi-região:
   - Esquerda: allocation navigator (lista de fundos com pesos atuais)
   - Centro: DataTable de @netz/ui com full allocation table, multi-sort, row expansion
   - Direita: before/after rebalance side-by-side
2. computed_at do servidor em toda freshness copy — nunca Date.now()
3. Botão "Export drift history" → GET /portfolios/{profile}/drift-history/export
4. Todos os valores via formatPercent, formatBps, formatCurrency de @netz/ui

Commit: feat(wealth): portfolio workbench rebuild — Section 3.Wealth.6

### Risk store batch (complemento Wealth.1)
Arquivo: frontends/wealth/src/lib/stores/risk-store.svelte.ts

1. Substituir fetches individuais por GET /risk/summary?profiles=a,b,c
   Endpoint batch disponível — ver api.d.ts para RiskSummaryBatch
2. Manter SSE-primary — batch só para poll fallback
3. Zero breaking change na interface do store

Commit: feat(wealth): batched risk summary endpoint in risk store

---

## SESSÃO 3 — feat/ux-sprint-6-admin
## Modelo: Sonnet 4.6
## Independente: toca só frontends/admin/

### Contexto
Ler CLAUDE.md e docs/plans/ux-remediation-plan.md seção Admin antes de tocar código.
Sprint 3/4 completou: Admin.1, Admin.2, Admin.3, Admin.4, Admin.5, Admin.6, Admin.7.
Verificar o que realmente ainda falta antes de implementar.
