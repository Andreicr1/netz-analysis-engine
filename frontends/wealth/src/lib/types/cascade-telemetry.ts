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
	| "constraint_polytope_empty";

export interface OperatorSignal {
	kind: OperatorSignalKind;
	binding: string | null;
	message_key: string;
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

export interface CascadeTelemetry {
	phase_attempts: PhaseAttempt[];
	cascade_summary: CascadeSummary;
	min_achievable_cvar: number | null;
	achievable_return_band: AchievableReturnBand | null;
	operator_signal: OperatorSignal | null;
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
