/**
 * Portfolio calibration — shared TS surface for the Builder
 * CalibrationPanel, the portfolio-workspace store, and the construction
 * run payload consumers.
 *
 * Mirrors the Pydantic ``PortfolioCalibrationRead`` schema in
 * ``backend/app/domains/wealth/schemas/model_portfolio.py`` (Phase 4
 * backend route). Numeric columns come back as JSON numbers — the
 * backend serializes ``Decimal`` through Pydantic's default encoder.
 *
 * DL5 — tier structure (Basic 5 / Advanced 10 / Expert 48). DL14 —
 * every field label surfaces via the jargon translation layer in
 * Phase 10; labels in this file are placeholders and MUST be replaced
 * from ``JARGON_TRANSLATION`` when that table lands.
 */

export type CalibrationMandate = "conservative" | "moderate" | "aggressive" | "balanced";

export type CalibrationRegimeOverride =
	| "auto"
	| "NORMAL"
	| "RISK_ON"
	| "RISK_OFF"
	| "CRISIS"
	| "INFLATION";

/** DL7 canonical stress scenario ids. */
export type StressScenarioId =
	| "gfc_2008"
	| "covid_2020"
	| "taper_2013"
	| "rate_shock_200bps";

export interface PortfolioCalibration {
	id: string;
	portfolio_id: string;
	schema_version: number;

	// ── Basic tier (5) ──
	mandate: CalibrationMandate;
	cvar_limit: number;
	max_single_fund_weight: number;
	turnover_cap: number | null;
	stress_scenarios_active: StressScenarioId[];

	// ── Advanced tier (10) ──
	regime_override: CalibrationRegimeOverride | null;
	bl_enabled: boolean;
	bl_view_confidence_default: number;
	garch_enabled: boolean;
	turnover_lambda: number | null;
	stress_severity_multiplier: number;
	advisor_enabled: boolean;
	cvar_level: number;
	lambda_risk_aversion: number | null;
	shrinkage_intensity_override: number | null;

	// ── Expert tier — untyped blob ──
	expert_overrides: Record<string, unknown>;

	// ── Audit ──
	created_at: string;
	updated_at: string;
	updated_by: string | null;
}

/**
 * Partial update body sent to PUT /{portfolio_id}/calibration. The
 * frontend uses ``exclude_unset`` semantics on the backend — only
 * touched fields are shipped.
 */
export type PortfolioCalibrationUpdate = Partial<
	Omit<PortfolioCalibration, "id" | "portfolio_id" | "schema_version" | "created_at" | "updated_at" | "updated_by">
>;

/** Deep-equal helper tailored to the calibration shape (shallow enough for primitives + arrays + flat expert_overrides). */
export function calibrationsEqual(a: PortfolioCalibration, b: PortfolioCalibration): boolean {
	if (a.mandate !== b.mandate) return false;
	if (a.cvar_limit !== b.cvar_limit) return false;
	if (a.max_single_fund_weight !== b.max_single_fund_weight) return false;
	if (a.turnover_cap !== b.turnover_cap) return false;
	if (a.stress_scenarios_active.length !== b.stress_scenarios_active.length) return false;
	for (let i = 0; i < a.stress_scenarios_active.length; i++) {
		if (a.stress_scenarios_active[i] !== b.stress_scenarios_active[i]) return false;
	}
	if (a.regime_override !== b.regime_override) return false;
	if (a.bl_enabled !== b.bl_enabled) return false;
	if (a.bl_view_confidence_default !== b.bl_view_confidence_default) return false;
	if (a.garch_enabled !== b.garch_enabled) return false;
	if (a.turnover_lambda !== b.turnover_lambda) return false;
	if (a.stress_severity_multiplier !== b.stress_severity_multiplier) return false;
	if (a.advisor_enabled !== b.advisor_enabled) return false;
	if (a.cvar_level !== b.cvar_level) return false;
	if (a.lambda_risk_aversion !== b.lambda_risk_aversion) return false;
	if (a.shrinkage_intensity_override !== b.shrinkage_intensity_override) return false;
	const aKeys = Object.keys(a.expert_overrides);
	const bKeys = Object.keys(b.expert_overrides);
	if (aKeys.length !== bKeys.length) return false;
	for (const k of aKeys) {
		if (a.expert_overrides[k] !== b.expert_overrides[k]) return false;
	}
	return true;
}
