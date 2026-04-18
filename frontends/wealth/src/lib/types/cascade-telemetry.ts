/**
 * Cascade telemetry payload — emitted by the construction_run_executor
 * (PR-A11) and stored on ``portfolio_construction_runs.cascade_telemetry``
 * (JSONB). The same shape is mirrored on the ``cascade_telemetry_completed``
 * SSE event, so the panel can hydrate before the final REST GET arrives.
 *
 * PR-A13 consumes ``achievable_return_band`` + ``operator_signal`` to drive
 * the Builder Risk Budget panel. PR-A13.2 will reuse these types for the
 * live drag-preview branch (``previewBand``).
 */

export interface AchievableReturnBand {
	lower: number;
	upper: number;
	lower_at_cvar: number;
	upper_at_cvar: number;
}

export type OperatorSignalKind =
	| "feasible"
	| "cvar_limit_below_universe_floor"
	| "upstream_data_missing"
	| "constraint_polytope_empty"
	// PR-A14 — surfaces only when coverage < 0.20 (hard-fail).
	| "universe_coverage_insufficient";

/**
 * PR-A14 — non-blocking secondary signal flagged by the executor when the
 * approved universe covers < 85% of the profile's strategic allocation
 * targets. Primary signal keeps its existing contract; consumers opt in
 * to the secondary by reading ``operator_signal.secondary``.
 */
export interface OperatorSignalSecondary {
	kind: "universe_coverage_insufficient";
	binding: string | null;
	message_key: string;
	pct_covered: number | null;
	missing_blocks_count: number | null;
}

export interface OperatorSignal {
	kind: OperatorSignalKind;
	binding: string | null;
	message_key: string;
	// PR-A14 — additive, None outside the coverage-warning window.
	secondary?: OperatorSignalSecondary | null;
	// PR-A14 — populated only when ``kind === "universe_coverage_insufficient"``.
	pct_covered?: number | null;
	missing_blocks_count?: number | null;
}

/**
 * PR-A14 — universe coverage payload. Surfaces the structural fit between
 * the approved universe (instruments_org) and the profile's strategic
 * allocation blocks. Nullable for legacy runs that predate the surface.
 */
export interface CoverageTelemetry {
	pct_covered: number;
	n_total_blocks: number;
	n_covered_blocks: number;
	covered_blocks: string[];
	missing_blocks: string[];
	renormalization_scale: number | null;
	hard_fail: boolean;
}

export type CascadeSummary =
	| "phase_1_succeeded"
	| "phase_2_robust_succeeded"
	| "phase_3_min_cvar_within_limit"
	| "phase_3_min_cvar_above_limit"
	| "upstream_heuristic";

export interface PhaseAttempt {
	phase: string;
	status: "succeeded" | "infeasible" | "skipped" | "error";
	solver?: string;
	objective_value?: number | null;
	wall_ms?: number;
	infeasibility_reason?: string | null;
	cvar_at_solution?: number | null;
}

/**
 * PR-A19.1 Section C — cascade-aware operator signal. Additive to the
 * legacy ``operator_signal``; distinguishes Phase 1 optimal from
 * Phase 3 min-CVaR fallback when the CVaR target is infeasible. The
 * backend owns the displayable copy (``operator_message``) — smart
 * backend / dumb frontend.
 */
export type WinnerSignal =
	| "optimal"
	| "cvar_infeasible_min_var"
	| "robustness_fallback"
	| "degraded_other"
	| "pre_solve_failure";

export type OperatorMessageSeverity = "info" | "warning" | "error";

export interface OperatorMessage {
	title: string;
	body: string;
	severity: OperatorMessageSeverity;
	action_hint: string;
}

export interface CascadeTelemetry {
	phase_attempts: PhaseAttempt[];
	cascade_summary: CascadeSummary;
	min_achievable_cvar: number | null;
	achievable_return_band: AchievableReturnBand | null;
	operator_signal: OperatorSignal | null;
	// PR-A14 — universe coverage surface (nullable for legacy runs).
	coverage?: CoverageTelemetry | null;
	// PR-A19.1 — cascade-aware signal + backend-owned copy.
	winner_signal?: WinnerSignal | null;
	operator_message?: OperatorMessage | null;
}

/**
 * PR-A13.2 — POST /preview-cvar response. Mirrors
 * ``backend/app/domains/wealth/schemas/preview.py``. Used by the Builder
 * RiskBudgetPanel to populate the ``previewBand ?? serverBand`` channel
 * while the operator drags the slider.
 */
export interface PreviewCvarResponse {
	achievable_return_band: AchievableReturnBand;
	min_achievable_cvar: number;
	operator_signal: OperatorSignal;
	cached: boolean;
	wall_ms: number;
}
