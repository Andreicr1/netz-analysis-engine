O que é
Um módulo dedicado dentro do Wealth OS para descoberta, monitoramento e peer comparison de investment managers registrados no SEC. Opera sobre as tabelas sec_managers, sec_13f_holdings, sec_13f_diffs e sec_institutional_allocations. A ação final é "Add to Universe" — que injeta o manager no fluxo existente de aprovação IC.

Três modos de uso, uma interface
O screener serve três casos de uso com igual prioridade. A mesma interface suporta os três via contexto:
Modo 1 — Discovery: encontrar managers desconhecidos que atendem critérios de mandato. Filtros aplicados sobre o universo completo de managers SEC.
Modo 2 — Monitoring: acompanhar managers já aprovados ou em DD. Filtro pré-aplicado: universe_status IN (approved, dd_pending, watchlist). Alertas de drift e compliance.
Modo 3 — Peer Comparison: selecionar N managers e comparar side-by-side em métricas chave. Ativado via seleção múltipla na tabela principal.

Arquitetura de dados
Todos os filtros e colunas derivam diretamente das tabelas SEC existentes:
sec_managers                    → firma-level attributes
sec_13f_holdings (latest)       → portfolio snapshot atual
sec_13f_diffs (last 4 quarters) → drift signals
sec_institutional_allocations   → pedigree institucional
instruments_universe            → link para managers já no sistema
Não há novo modelo de dados. O screener é uma view sobre o que já existe.

Filtros do screener
Bloco 1 — Firma (sec_managers)
FiltroTipoCampoAUM rangerange slideraum_totalStrategy typemulti-selectclient_types JSONBFee typemulti-selectfee_types JSONBGeographymulti-selectstate, countryRegistration statusselectregistration_statusCompliance cleantogglecompliance_disclosures = 0Last ADV fileddate rangelast_adv_filed_at
Bloco 2 — Portfolio (sec_13f_holdings latest quarter)
FiltroTipoCampoSector exposuremulti-selectsector (post-fix)Top holding concentrationrangeHHI calculadoPosition countrangeCOUNT por CIK/quarterMin portfolio sizerangeSUM(market_value)
Bloco 3 — Drift (sec_13f_diffs last 4Q)
FiltroTipoCampoStyle drift detectedtogglederived from sector rotationTurnover raterange(EXITED + NEW_POSITION) / total positionsHigh activity quartersrangequarters com turnover > threshold
Bloco 4 — Institutional pedigree
FiltroTipoCampoInstitutional holderstoggleEXISTS em sec_institutional_allocationsHolder typemulti-selectfiler_type (endowment, pension, foundation)
Bloco 5 — Universe status (Monitoring mode)
FiltroTipoCampoIn universemulti-selectjoin com instruments_universeStatusmulti-selectapproved / dd_pending / watchlist / not_in_universe

Tabela de resultados
Colunas default (configuráveis):
ColunaFonteManager namesec_managers.firm_nameAUMsec_managers.aum_totalStrategysec_managers.client_typesTop sectorsec_13f_holdings aggregatedHHIcomputedCompliancesec_managers.compliance_disclosuresDrift signalsec_13f_diffs derivedInstitutional holdersCOUNT sec_institutional_allocationsUniverse statusinstruments_universe joinLast 13Fsec_13f_holdings.report_date MAX
Comportamento:

VirtualList para performance com 5000+ managers
Sort por qualquer coluna
Row click → ContextPanel (drill-down)
Multi-select → ativa Peer Comparison mode


ContextPanel (drill-down de manager)
Quando um manager é selecionado, o painel lateral mostra:
Tab 1 — Profile

Dados ADV: AUM histórico, fee structure, compliance history, team size
Registration info, website, sede

Tab 2 — Holdings

Sector allocation chart (pie/bar) — atual e 4 quarters anteriores
Top 10 positions table com CUSIP, issuer, market value, weight
Style drift timeline

Tab 3 — Institutional

Lista de endowments/pensions que detêm o manager (via 13F reverso)
Coverage type indicator (PUBLIC_SECURITIES / NO_PUBLIC_SECURITIES)

Tab 4 — Universe

Status atual no Wealth OS
Link para DD Report se existir
Botão de ação primária (ver abaixo)


Ação primária — Add to Universe
O botão de ação no ContextPanel varia por status:
Status atualLabel do botãoAçãonot_in_universe"Add to Universe"Cria entrada em instruments_universe → status: pending → fluxo IC existentedd_pending"View DD Report"Navega para /dd-reports/{fundId}approved"View in Portfolio"Navega para /funds/{id}watchlist"Review"Abre review workflow existente
O "Add to Universe" não cria uma segunda aprovação — injeta no fluxo IC exatamente como qualquer outro instrumento pendente. O screener é o canal de entrada, não um bypass.

Peer Comparison mode
Ativado quando 2-5 managers são selecionados na tabela (checkbox).
Exibe comparison panel com:

Metrics table: AUM, compliance, HHI, top sector, institutional holders — lado a lado
Sector allocation bar chart: stacked bars por manager, mesmos eixos
Holdings overlap: % de CUSIPs em comum entre os managers selecionados
Drift comparison: turnover rate últimos 4 quarters, um linha por manager

Este é o equivalente direto do "Peer Analysis" do eVestment Quantum — e é inteiramente derivado das tabelas SEC sem dado adicional.

Backend
Um endpoint único com query params:
GET /api/wealth/manager-screener
  ?aum_min=1000000000
  &aum_max=50000000000
  &compliance_clean=true
  &sectors=Real+Estate,Technology
  &universe_status=not_in_universe
  &sort_by=aum_total
  &sort_dir=desc
  &page=1
  &page_size=50
Retorna resultados paginados com todos os campos da tabela. SQL dinâmico — cada filtro presente adiciona uma cláusula WHERE. Sem ORM complexo, query builder simples.
Para o ContextPanel, endpoints separados:
GET /api/wealth/managers/{crd}/profile
GET /api/wealth/managers/{crd}/holdings?quarter=2025-12-31
GET /api/wealth/managers/{crd}/drift?quarters=4
GET /api/wealth/managers/{crd}/institutional

Dependências e sequência
O screener depende diretamente do fix do get_sector_aggregation() — sem sector no sec_13f_holdings, o filtro de sector exposure e o sector allocation chart não funcionam.
Sequência de implementação:

Fix sector (prompt já preparado) — bloqueante
Backend endpoints do screener — pode iniciar após fix
Frontend screener page — pode iniciar em paralelo com backend (mock data)
Integração Add to Universe com fluxo IC existente


O que não está neste escopo

Performance returns históricos de fundos (não está no SEC — seria YFinance/FEfundinfo)
Consultant ratings (proprietário eVestment — não replicável)
Fee negotiation intelligence (proprietário — não replicável)
Managers não registrados no SEC (offshore-only, sub $100M AUM)

O que está no escopo cobre 80% do que foi apresentado na demo do eVestment para o caso de uso do Netz.

Próximos passos

Confirmar este brainstorm
Fix do sector (prompt preparado — executar agora)
Brainstorm → plano de implementação (/ce:plan)
M3 do SEC layer absorve o screener como entrega principal
/ce:plan00:45Architected comprehensive plan for Manager Screener implementationArchitected comprehensive plan for Manager Screener implementationYou are implementing the Manager Screener module for the Netz Analysis Engine Wealth OS.

Read these documents before doing anything:
- `docs/brainstorms/2026-03-20-sec-data-providers-brainstorm.md`
- `docs/plans/2026-03-20-feat-sec-data-providers-layer-plan.md`
- `docs/reference/sec-data-providers-implementation-guide.md`
- `backend/app/shared/models.py` — sec_* table definitions
- `backend/vertical_engines/wealth/screener/` — existing screener pattern
- `backend/app/domains/wealth/` — existing wealth API route patterns
- `frontend/wealth/src/routes/screener/` — existing screener frontend pattern

## Context

The SEC data providers layer (M1) is complete. Tables sec_managers,
sec_13f_holdings, sec_13f_diffs, sec_institutional_allocations are populated.
The get_sector_aggregation() fix (GICS sectors replacing COM/CALL/PUT) is
complete and sec_13f_holdings.sector column exists.

This plan implements the Manager Screener — a dedicated module for discovery,
monitoring and peer comparison of SEC-registered investment managers, with
"Add to Universe" as the primary action connecting to the existing IC approval flow.

## Architecture constraint

- Backend: FastAPI async, follows existing wealth domain route patterns
- Frontend: SvelteKit, follows existing Wealth OS patterns (TopNav + ContextSidebar,
  dark + light mode, ECharts for charts, TanStack Table for data tables)
- Design tokens from admin branding API
- No new dependencies unless justified

---
