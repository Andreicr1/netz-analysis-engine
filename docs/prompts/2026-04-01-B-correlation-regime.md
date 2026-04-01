# Prompt B — Correlation Regime Heatmap (2 endpoints)

## Contexto

Dois endpoints de correlação regime-aware existem no backend mas não têm interface:

- `GET /analytics/correlation-regime/{profile}` → `CorrelationRegimeRead`
- `GET /analytics/correlation-regime/{profile}/pair/{inst_a}/{inst_b}` → `PairCorrelationTimeseriesRead`

O frontend já tem correlação básica (`GET /analytics/correlation`) na página `/analytics`.
Este prompt adiciona a versão regime-aware com heatmap divergente (RdBu) e drill-down por par.

**Diferença entre os dois endpoints:**
- `/analytics/correlation` — matriz de correlação simples (Pearson), sem regime conditioning
- `/analytics/correlation-regime/{profile}` — matriz com Marchenko-Pastur denoising, absorption ratio,
  detecção de contagion, e indicação de regime shift

---

## Arquivos a ler antes de implementar

```
backend/app/domains/wealth/schemas/correlation_regime.py   — shapes exatos: CorrelationRegimeRead, PairCorrelationTimeseriesRead
backend/app/domains/wealth/routes/correlation_regime.py    — params disponíveis: window_days, baseline_days
frontends/wealth/src/routes/(app)/analytics/+page.server.ts — loader atual (adicionar correlation-regime aqui)
frontends/wealth/src/routes/(app)/analytics/+page.svelte   — onde inserir o novo painel
frontends/wealth/src/lib/types/analytics.ts                — adicionar tipos TypeScript
frontends/wealth/src/lib/components/charts/               — padrão dos charts existentes
```

---

## Fase 1 — Tipos TypeScript

Em `frontends/wealth/src/lib/types/analytics.ts`, adicionar:

```typescript
export interface InstrumentCorrelation {
  instrument_a_id: string;
  instrument_a_name: string;
  instrument_b_id: string;
  instrument_b_name: string;
  current_correlation: number;
  baseline_correlation: number;
  correlation_change: number;
  is_contagion: boolean;
}

export interface ConcentrationAnalysis {
  eigenvalues: number[];
  explained_variance_ratios: number[];
  first_eigenvalue_ratio: number;
  concentration_status: string;       // "low" | "moderate" | "high" | "critical"
  diversification_ratio: number;
  dr_alert: boolean;
  absorption_ratio: number;
  absorption_status: string;          // "ok" | "warning" | "critical"
  mp_threshold: number;
  n_signal_eigenvalues: number;
}

export interface CorrelationRegimeResult {
  profile: string;
  instrument_count: number;
  window_days: number;
  correlation_matrix: number[][];
  instrument_labels: string[];
  contagion_pairs: InstrumentCorrelation[];
  concentration: ConcentrationAnalysis;
  average_correlation: number;
  baseline_average_correlation: number;
  regime_shift_detected: boolean;
  computed_at: string;
}

export interface PairCorrelationPoint {
  date: string;
  rolling_correlation: number;
  regime: string;
}

export interface PairCorrelationResult {
  instrument_a_id: string;
  instrument_a_name: string;
  instrument_b_id: string;
  instrument_b_name: string;
  window_days: number;
  series: PairCorrelationPoint[];
}
```
