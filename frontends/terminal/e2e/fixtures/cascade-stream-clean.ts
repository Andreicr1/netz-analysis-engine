/**
 * Simulates a complete, successful (phase_1_succeeded, winner_signal=optimal)
 * construction SSE stream.
 *
 * Event order mirrors construction_run_executor.py. Humanized `type` values
 * match EVENT_TYPE_LABELS in backend/app/domains/wealth/schemas/sanitized.py
 * (verified 2026-04-24). Frontend dispatches on raw_type first
 * (portfolio-workspace.svelte.ts:2029), so functionally both work, but we
 * keep `type` in sync with backend convention for contract fidelity.
 */

const RUN_ID = "e2e-run-00000000-0000-0000-0000-000000000001";

interface SseFrame {
  event?: string;
  data: Record<string, unknown>;
}

const frames: SseFrame[] = [
  {
    data: {
      type: "Construction started",
      raw_type: "run_started",
      phase: "STARTED",
      message: "Construction run started",
      progress: 0.0,
      run_id: RUN_ID,
    },
  },
  {
    data: {
      type: "Optimizer started",
      raw_type: "optimizer_started",
      phase: "FACTOR_MODELING",
      message: "Factor model estimation",
      progress: 0.1,
    },
  },
  {
    data: {
      type: "Universe pre-filter completed",
      raw_type: "prefilter_dedup_completed",
      phase: "FACTOR_MODELING",
      message: "Universe deduplication complete",
      progress: 0.15,
      metrics: {
        universe_size_before_dedup: 42,
        universe_size_after_dedup: 38,
        n_clusters: 4,
        pair_corr_p50: 0.32,
        pair_corr_p95: 0.71,
      },
    },
  },
  {
    data: {
      type: "Shrinkage completed",
      raw_type: "shrinkage_completed",
      phase: "SHRINKAGE",
      message: "Covariance estimation complete",
      progress: 0.3,
      metrics: {
        kappa_sample: 12400,
        kappa_final: 5800,
        kappa_factor_fallback: null,
        covariance_source: "sample",
      },
    },
  },
  {
    data: {
      type: "Optimizer phase completed",
      raw_type: "optimizer_phase_complete",
      phase: "SOCP_OPTIMIZATION",
      message: "Phase 1: Max Return completed",
      progress: 0.5,
      metrics: {
        phase: "phase_1_ru_max_return",
        phase_label: "Phase 1 · Max Return",
        status: "succeeded",
        objective_value: 0.0922,
      },
    },
  },
  {
    data: {
      type: "Optimizer phase completed",
      raw_type: "optimizer_phase_complete",
      phase: "SOCP_OPTIMIZATION",
      message: "Phase 2: Robust completed",
      progress: 0.6,
      metrics: {
        phase: "phase_2_ru_robust",
        phase_label: "Phase 2 · Robust",
        status: "skipped",
        objective_value: null,
      },
    },
  },
  {
    data: {
      type: "Optimizer phase completed",
      raw_type: "optimizer_phase_complete",
      phase: "SOCP_OPTIMIZATION",
      message: "Phase 3: Min Tail Risk completed",
      progress: 0.7,
      metrics: {
        phase: "phase_3_min_cvar",
        phase_label: "Phase 3 · Min Tail Risk",
        status: "skipped",
        objective_value: null,
      },
    },
  },
  {
    data: {
      type: "Optimizer cascade summary",
      raw_type: "cascade_telemetry_completed",
      phase: "SOCP_OPTIMIZATION",
      message: "Cascade resolved",
      progress: 0.75,
      metrics: {
        cascade_summary: "phase_1_succeeded",
        winner_signal: "optimal",
        operator_signal: {
          kind: "feasible",
          binding: null,
          message_key: "feasible",
          min_achievable_cvar: 0.032,
          user_cvar_limit: 0.05,
        },
        min_achievable_cvar: 0.032,
        achievable_return_band: { lower: 0.068, upper: 0.094 },
        operator_message: {
          title: "Allocation within risk budget",
          body: "The portfolio was optimised for maximum return within your CVaR limit.",
          severity: "info",
          action_hint: null,
        },
        coverage: {
          pct_covered: 0.89,
          hard_fail: false,
          n_total_blocks: 18,
          n_covered_blocks: 16,
          missing_blocks: ["alt_commodities", "fi_em_hard_currency"],
        },
        phase_attempts: [
          { phase: "phase_1_ru_max_return", status: "succeeded", solver: "CLARABEL", wall_ms: 340, objective_value: 0.0922, cvar_within_limit: true },
          { phase: "phase_2_ru_robust", status: "skipped", solver: null, wall_ms: 0, objective_value: null, cvar_within_limit: null },
          { phase: "phase_3_min_cvar", status: "skipped", solver: null, wall_ms: 0, objective_value: null, cvar_within_limit: null },
        ],
      },
    },
  },
  {
    data: {
      type: "Stress tests started",
      raw_type: "stress_started",
      phase: "BACKTESTING",
      message: "Running stress scenarios",
      progress: 0.85,
    },
  },
  {
    data: {
      type: "Construction succeeded",
      raw_type: "run_succeeded",
      phase: "COMPLETED",
      message: "Construction complete",
      progress: 1.0,
      run_id: RUN_ID,
      status: "succeeded",
      metrics: { wall_clock_ms: 8400 },
    },
  },
];

export function buildCleanSseStream(): string {
  return frames
    .map((f) => {
      const lines: string[] = [];
      if (f.event) lines.push(`event: ${f.event}`);
      lines.push(`data: ${JSON.stringify(f.data)}`);
      lines.push(""); // blank line terminates the SSE event
      return lines.join("\n");
    })
    .join("\n") + "\n"; // trailing newline so the last event's blank line is complete
}

export { RUN_ID };
