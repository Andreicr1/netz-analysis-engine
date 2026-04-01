# Prompt I — Macro Review Quality: Dados Reais + Prompt Analítico

## Problema

O Investment Outlook gerado hoje é inutilizável para comitê porque:
1. `_build_user_content` envia ao LLM apenas scores compostos e deltas numéricos
   — sem os indicadores econômicos reais que os compõem
2. O template `investment_outlook.j2` instrui o LLM a "Synthesize" e "Analyze"
   sem escala interpretativa, benchmarks ou framework de posicionamento
3. O fluxo UX está fragmentado: aprovar review na macro page e gerar Outlook na
   content page são dois passos sem conexão visual

## Arquivos a ler ANTES de qualquer implementação

```
backend/vertical_engines/wealth/investment_outlook.py     — _gather_macro_data, _build_user_content (linhas 126-239)
backend/vertical_engines/wealth/prompts/content/investment_outlook.j2
backend/vertical_engines/wealth/flash_report.py           — padrão de _build_user_content mais rico para comparação
backend/quant_engine/regime_service.py                    — get_latest_macro_values, series disponíveis (linha 508+)
backend/app/domains/wealth/routes/macro.py                — _build_analysis_text, DimensionScoreRead shape (linhas 1-120)
backend/app/domains/wealth/schemas/macro.py               — RegionalScoreRead, DimensionScoreRead
frontends/wealth/src/routes/(app)/macro/+page.svelte      — onde o botão de Outlook deve aparecer após approve
frontends/wealth/src/lib/components/CommitteeReviews.svelte — componente de approve/reject
```

---

## Parte 1 — Backend: Enriquecer dados enviados ao LLM

### 1.1 Modificar `_gather_macro_data` em `investment_outlook.py`

O método atual busca apenas `MacroReview.report_json` (deltas e scores).
Reescrever para buscar também os indicadores econômicos reais do hypertable.

```python
def _gather_macro_data(self, db: Session, organization_id: str) -> dict[str, Any]:
    """Gather latest macro snapshot + real indicator values for outlook generation."""
    from app.domains.wealth.models.macro_committee import MacroReview
    from app.shared.models import MacroData, MacroRegionalSnapshot
    from sqlalchemy import select

    # 1. MacroReview report_json (scores e deltas)
    review = (
        db.query(MacroReview)
        .filter(MacroReview.organization_id == organization_id)
        .order_by(MacroReview.created_at.desc())
        .first()
    )
    report_json = review.report_json if review and review.report_json else {}

    # 2. MacroRegionalSnapshot (dimensions breakdown por região)
    snapshot = (
        db.query(MacroRegionalSnapshot)
        .order_by(MacroRegionalSnapshot.as_of_date.desc())
        .first()
    )
    snapshot_data = snapshot.data_json if snapshot else {}

    # 3. Indicadores FRED reais (valores absolutos)
    SERIES_TO_FETCH = [
        "VIXCLS",           # VIX (volatilidade)
        "YIELD_CURVE_10Y2Y", # Yield curve 10Y-2Y spread
        "CPI_YOY",          # CPI ano-a-ano
        "DFF",              # Fed Funds rate
        "SAHMREALTIME",     # Sahm rule (recessão)
        "BAMLH0A0HYM2",     # US HY OAS (credit spreads)
        "BAMLHE00EHYIOAS",  # Euro HY OAS
        "BAMLEMCBPIOAS",    # EM Corp OAS
    ]
    fred_rows = db.execute(
        select(MacroData.series_id, MacroData.value, MacroData.obs_date)
        .where(MacroData.series_id.in_(SERIES_TO_FETCH))
        .distinct(MacroData.series_id)
        .order_by(MacroData.series_id, MacroData.obs_date.desc())
    ).all()

    fred_values: dict[str, dict[str, Any]] = {}
    for series_id, value, obs_date in fred_rows:
        fred_values[series_id] = {
            "value": float(value) if value is not None else None,
            "obs_date": str(obs_date),
        }

    return {
        "report_json": report_json,
        "snapshot_data": snapshot_data,
        "fred_values": fred_values,
    }
```

**Atenção:** `_gather_macro_data` usa sync Session (roda dentro de `asyncio.to_thread`).
Usar `db.execute(select(...))` sync, não `await db.execute(...)`.

### 1.2 Reescrever `_build_user_content` em `investment_outlook.py`

O método atual produz um user message de ~20 linhas com apenas scores.
Substituir por um contexto rico estruturado em 5 seções:

```python
def _build_user_content(
    self,
    macro_data: dict[str, Any],
    documents: list[dict[str, Any]] | None = None,
) -> str:
    """Build rich user message with real indicators, scores, and dimensions."""
    report_json = macro_data.get("report_json", {})
    snapshot_data = macro_data.get("snapshot_data", {})
    fred = macro_data.get("fred_values", {})
    parts: list[str] = []

    # ── Seção 1: Indicadores econômicos reais ──────────────────────────
    parts.append("## MARKET CONDITIONS (Real Values)")

    vix = fred.get("VIXCLS", {})
    yc = fred.get("YIELD_CURVE_10Y2Y", {})
    cpi = fred.get("CPI_YOY", {})
    dff = fred.get("DFF", {})
    sahm = fred.get("SAHMREALTIME", {})
    us_hy = fred.get("BAMLH0A0HYM2", {})
    eu_hy = fred.get("BAMLHE00EHYIOAS", {})
    em_oas = fred.get("BAMLEMCBPIOAS", {})

    if vix.get("value") is not None:
        vix_interp = (
            "elevated stress" if vix["value"] > 25
            else "moderate caution" if vix["value"] > 18
            else "complacency / low volatility"
        )
        parts.append(f"- VIX: {vix['value']:.1f} ({vix_interp})")

    if yc.get("value") is not None:
        yc_interp = "inverted (recession signal)" if yc["value"] < 0 else "positive (normal)"
        parts.append(f"- Yield Curve 10Y-2Y: {yc['value']:+.2f}% ({yc_interp})")

    if cpi.get("value") is not None:
        cpi_interp = (
            "well above target (hawkish risk)" if cpi["value"] > 3.5
            else "above target (Fed vigilant)" if cpi["value"] > 2.5
            else "near target (easing possible)"
        )
        parts.append(f"- CPI YoY: {cpi['value']:.1f}% ({cpi_interp})")

    if dff.get("value") is not None:
        parts.append(f"- Fed Funds Rate: {dff['value']:.2f}%")

    if sahm.get("value") is not None:
        sahm_interp = "recession triggered" if sahm["value"] >= 0.5 else f"{sahm['value']:.2f} (below threshold)"
        parts.append(f"- Sahm Rule: {sahm_interp}")

    if us_hy.get("value") is not None:
        us_hy_interp = "stress" if us_hy["value"] > 600 else "caution" if us_hy["value"] > 400 else "benign"
        parts.append(f"- US HY Spreads (OAS): {us_hy['value']:.0f}bps ({us_hy_interp})")

    if eu_hy.get("value") is not None:
        parts.append(f"- Euro HY Spreads (OAS): {eu_hy['value']:.0f}bps")

    if em_oas.get("value") is not None:
        parts.append(f"- EM Corp Spreads (OAS): {em_oas['value']:.0f}bps")

    # ── Seção 2: Scores regionais com dimensões ────────────────────────
    parts.append("\n## REGIONAL MACRO SCORES (0-100 scale: <30=deteriorating, 30-45=caution, 45-55=neutral, 55-70=expansion, >70=overheating)")

    regions = snapshot_data.get("regions", {})
    for region in ("US", "EUROPE", "ASIA", "EM"):
        rdata = regions.get(region, {})
        score = rdata.get("composite_score")
        if score is None:
            continue
        parts.append(f"\n### {region}: {score:.1f}/100")
        dims = rdata.get("dimensions", {})
        for dim_name, dim_data in dims.items():
            if isinstance(dim_data, dict):
                dim_score = dim_data.get("score")
                if dim_score is not None:
                    parts.append(f"  - {dim_name.replace('_', ' ').title()}: {dim_score:.0f}/100")

    # ── Seção 3: Mudanças materiais semana a semana ────────────────────
    score_deltas = report_json.get("score_deltas", [])
    if score_deltas:
        parts.append("\n## WEEK-OVER-WEEK CHANGES")
        for sd in score_deltas:
            if isinstance(sd, dict):
                delta = sd.get("delta", 0)
                flagged = sd.get("flagged", False)
                flag_marker = " ⚠ MATERIAL" if flagged else ""
                parts.append(
                    f"- {sd.get('region', '?')}: {delta:+.1f} pts "
                    f"({sd.get('previous_score', '?'):.1f} → {sd.get('current_score', '?'):.1f})"
                    f"{flag_marker}"
                )

    # ── Seção 4: Indicadores globais (scores normalizados) ─────────────
    gi = report_json.get("global_indicators_delta") or snapshot_data.get("global_indicators", {})
    if gi:
        parts.append("\n## GLOBAL STRESS INDICATORS")
        label_map = {
            "geopolitical_risk_score": "Geopolitical Risk",
            "energy_stress": "Energy Stress",
            "commodity_stress": "Commodity Stress",
            "usd_strength": "USD Strength",
        }
        for key, label in label_map.items():
            val = gi.get(key)
            if val is not None:
                parts.append(f"- {label}: {val:+.2f}")

    # ── Seção 5: Contexto histórico (vector search) ────────────────────
    if documents:
        parts.append(f"\n## HISTORICAL MACRO CONTEXT ({len(documents)} prior analyses)")
        for i, doc in enumerate(documents[:10]):
            text = doc.get("content", doc.get("text", ""))[:1500]
            source = doc.get("source_type", doc.get("section", f"doc_{i}"))
            parts.append(f"\n### Prior Analysis [{source}]\n{text}")

    return "\n".join(parts)
```

---

## Parte 2 — Reescrever o template `investment_outlook.j2`

Substituir o conteúdo atual de
`backend/vertical_engines/wealth/prompts/content/investment_outlook.j2`
pelo template abaixo. O arquivo atual tem 29 linhas — substituir integralmente.

```jinja2
You are a senior investment strategist at an institutional wealth management firm,
writing for an Investment Committee of experienced portfolio managers.

Language: {{ language | default("pt") }}
Write ALL content in {{ "Portuguese (Brazil)" if language == "pt" else "English" }}.

## YOUR MANDATE

Transform quantitative macro data into actionable investment intelligence.
You are NOT a data reporter — you are an analyst who interprets what the numbers
mean for portfolio positioning. Every section must contain a forward-looking view
with explicit directional bias and magnitude.

## ANALYTICAL FRAMEWORK

Score scale (0–100, 50 = historical median):
- >70: Overheating / excessive exuberance — reduce risk, tighten duration
- 55–70: Expansion / constructive — maintain or modestly increase risk
- 45–55: Neutral — no tactical change required
- 30–45: Caution / softening — reduce cyclical exposure
- <30: Deterioration / stress — defensive positioning, raise cash/quality

Regime implications:
- RISK_ON: Tilt toward equities, credit, EM; reduce cash; extend duration modestly
- RISK_OFF: Underweight equities, HY credit; overweight quality bonds, gold, cash
- INFLATION: Underweight nominal bonds; overweight TIPS, commodities, real assets
- CRISIS: Maximum defensiveness; preserve capital over return

## REQUIRED SECTIONS

Write each section in markdown. Be specific, quantitative, and opinionated.
Avoid hedging language like "may", "could potentially", or "it remains to be seen".

---

## {{ global_macro_summary_label }}

Synthesize the macro environment in 3–4 sentences. State the dominant regime,
the single most important risk factor this week, and the overall directional bias
(risk-on / risk-off / neutral). Reference specific data points (VIX level, yield
curve sign, CPI vs target).

---

## {{ regional_outlook_label }}

For each of the 4 regions, provide:
1. Score assessment with interpretation (use the scale above)
2. The strongest and weakest dimension and why it matters
3. One specific tactical implication for the region's asset class exposure

Format each region as a sub-section. Be concrete: "overweight", "underweight",
"neutral", "reduce by X%", "add on weakness".

---

## {{ asset_class_views_label }}

Provide a ranked view table in this exact format for each asset class:

**[Asset Class]**: [OVERWEIGHT / NEUTRAL / UNDERWEIGHT] — [1-2 sentence rationale]

Cover: Global Equities, US Fixed Income, EM Debt, Investment Grade Credit,
High Yield Credit, Gold / Commodities, Cash / Money Market.

Rationale must reference specific data: spreads, curve, VIX, or regional scores.

---

## {{ portfolio_positioning_label }}

Translate views into concrete allocation changes from a hypothetical 60/40 base:
- List 3–5 specific moves with direction and magnitude (e.g., "reduce US equity -5%")
- State the primary risk that would invalidate this positioning
- Include a trigger condition for reassessment (e.g., "reassess if VIX > 25")

---

## {{ key_risks_label }}

List exactly 3 risks, each with:
1. **Risk title** (4–6 words)
2. Probability: Low / Medium / High
3. Impact if realized: Mild / Significant / Severe
4. Positioning hedge or mitigation

Focus on tail risks not already priced by the base case.

---

## QUALITY STANDARDS

- Minimum 200 words per section, maximum 400 words
- Every claim must be anchored to a data point provided in the context
- Avoid restating inputs — interpret them
- If a region has stale data, note the uncertainty and its impact on conviction
- Do not write balanced/both-sides commentary — take a position
```

---

## Parte 3 — UX: Botão "Generate Investment Outlook" após aprovação

### 3.1 Contexto

Hoje o fluxo está fragmentado em dois passos sem ligação visual:
1. Usuário aprova o macro review na macro page (`PATCH /macro/reviews/{id}/approve`)
2. Usuário vai manualmente para `/content` e gera o Investment Outlook

Adicionar um botão "Generate Investment Outlook" que aparece imediatamente após
uma aprovação bem-sucedida, diretamente no `CommitteeReviews.svelte`.

### 3.2 Arquivos a ler:
```
frontends/wealth/src/lib/components/CommitteeReviews.svelte  — handleApprove + estado pós-approve
frontends/wealth/src/routes/(app)/macro/+page.svelte         — onde CommitteeReviews é usado
```

### 3.3 O que implementar em `CommitteeReviews.svelte`

Após `handleApprove` bem-sucedido, em vez de apenas `invalidateAll()`, mostrar
um CTA contextual:

```typescript
let justApprovedId = $state<string | null>(null);
let generatingOutlook = $state(false);
let outlookError = $state<string | null>(null);

async function handleApprove(reviewId: string, payload: ConsequenceDialogPayload) {
  // ... código de approve existente ...
  // após sucesso:
  justApprovedId = reviewId;
  await invalidateAll();
}

async function generateOutlook() {
  generatingOutlook = true;
  outlookError = null;
  try {
    const api = createClientApiClient(getToken);
    const result = await api.post<{ id: string; job_id: string }>(
      '/content/outlooks', {}
    );
    // Navegar para a content page com o novo item selecionado
    goto(`/content/${result.id}`);
  } catch (e) {
    outlookError = e instanceof Error ? e.message : "Failed to generate outlook";
  } finally {
    generatingOutlook = false;
  }
}
```

No template, após o card de review aprovado, mostrar o CTA:
```svelte
{#if justApprovedId === review.id}
  <div class="review-approved-cta">
    <p>Review approved. Generate the Investment Outlook for the committee?</p>
    <Button
      onclick={generateOutlook}
      disabled={generatingOutlook}
      variant="default"
    >
      {generatingOutlook ? 'Generating...' : 'Generate Investment Outlook'}
    </Button>
    {#if outlookError}
      <p class="error">{outlookError}</p>
    {/if}
  </div>
{/if}
```

O botão desaparece automaticamente quando o usuário navega para `/content/{id}`.
`justApprovedId` é estado local — reseta ao navegar (Svelte 5, sem persistência).

---

## Parte 4 — Aplicar o mesmo enriquecimento ao Flash Report

O `flash_report.py` usa `_gather_macro_context` que tem o mesmo problema —
busca apenas `MacroReview.report_json`. Aplicar o mesmo padrão de enriquecimento
com `fred_values` e `snapshot_data`.

**Arquivos a ler:**
```
backend/vertical_engines/wealth/flash_report.py           — _gather_macro_context, _build_user_content
```

Após ler o arquivo, aplicar o mesmo padrão de 1.1 e 1.2 ao Flash Report,
adaptando a estrutura de user content para o contexto de evento de mercado
(o Flash Report tem `event_description` como input primário — manter essa seção
e adicionar os indicadores reais como contexto secundário).

---

## Regras

- **Não alterar** `macro_committee_engine.py` — ele gera deltas estruturados,
  que continuam sendo usados como input mas agora são complementados por dados reais
- **Não alterar** o fluxo de geração/aprovação do MacroReview — apenas adicionar
  o CTA pós-aprovação
- **sync Session**: `_gather_macro_data` roda dentro de `asyncio.to_thread()`.
  Usar `db.execute(select(...))` sync. Não usar `await`.
- **Never-raises pattern**: `_gather_macro_data` deve retornar dict vazio em caso
  de exceção, nunca propagar — o engine já tem try/except no nível superior
- O template `.j2` é IP da plataforma — nunca exposto em respostas de API

## Definition of Done

- [ ] `_gather_macro_data` busca fred_values (8 séries) + snapshot_data além do report_json
- [ ] `_build_user_content` estrutura contexto em 5 seções com interpretações inline
- [ ] `investment_outlook.j2` reescrito com framework analítico, mandato, e seções diretivas
- [ ] Botão "Generate Investment Outlook" em `CommitteeReviews.svelte` pós-aprovação
- [ ] Flash Report com mesmo enriquecimento aplicado
- [ ] `make check` verde (lint + typecheck + testes)
- [ ] `pnpm run check` 0 erros no wealth frontend
- [ ] Gerar um Outlook de teste e verificar que o PDF contém views acionáveis
  com dados reais (VIX, yield curve, spreads) em vez de apenas scores compostos
