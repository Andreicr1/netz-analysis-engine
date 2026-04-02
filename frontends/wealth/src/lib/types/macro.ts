/** Macro domain types — FRED, Treasury, OFR, BIS, IMF. */

export interface MacroIndicators {
	vix: number | null;
	vix_date: string | null;
	yield_curve_10y2y: number | null;
	yield_curve_date: string | null;
	cpi_yoy: number | null;
	cpi_date: string | null;
	fed_funds_rate: number | null;
	fed_funds_date: string | null;
}

export interface DimensionScore {
	score: number;
	n_indicators: number;
	indicators: Record<string, number>;
}

export interface DataFreshness {
	last_date: string | null;
	days_stale: number | null;
	weight: number;
	status: "fresh" | "decaying" | "stale";
}

export interface RegionalScore {
	composite_score: number;
	coverage: number;
	dimensions: Record<string, DimensionScore>;
	data_freshness: Record<string, DataFreshness>;
	analysis_text: string | null;
}

export interface GlobalIndicators {
	geopolitical_risk_score: number;
	energy_stress: number;
	commodity_stress: number;
	usd_strength: number;
}

export interface MacroScores {
	as_of_date: string;
	regions: Record<string, RegionalScore>;
	global_indicators: GlobalIndicators;
}

export interface RegimeHierarchy {
	global_regime: string;
	regional_regimes: Record<string, string>;
	composition_reasons: Record<string, string>;
	as_of_date: string | null;
}

export interface TreasuryPoint {
	obs_date: string;
	value: number;
}

export interface OfrPoint {
	obs_date: string;
	value: number;
}

export interface BisPoint {
	period: string;
	value: number;
}

export interface ImfPoint {
	year: number;
	value: number;
}

export interface FredPoint {
	obs_date: string;
	value: number;
}

export function regimeColor(regime: string | null | undefined): string {
	switch (regime) {
		case "crisis":      return "var(--ii-danger)";
		case "stress":      return "var(--ii-warning)";
		case "recovery":    return "var(--ii-info)";
		case "expansion":   return "var(--ii-success)";
		case "normal":      return "var(--ii-success)";
		default:            return "var(--ii-text-muted)";
	}
}

export function freshnessColor(status: string): string {
	switch (status) {
		case "fresh":    return "var(--ii-success)";
		case "decaying": return "var(--ii-warning)";
		case "stale":    return "var(--ii-danger)";
		default:         return "var(--ii-text-muted)";
	}
}

export interface MacroSnapshot {
	id: string;
	as_of_date: string;
	data_json: Record<string, unknown>;
}

export interface MacroReview {
	id: string;
	organization_id: string;
	status: string;
	is_emergency: boolean;
	as_of_date: string;
	snapshot_id: string | null;
	report_json: Record<string, unknown>;
	approved_by: string | null;
	approved_at: string | null;
	decision_rationale: string | null;
	created_at: string;
	created_by: string | null;
}
