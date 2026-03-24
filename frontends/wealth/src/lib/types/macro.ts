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

export function regimeColor(regime: string | null | undefined): string {
	switch (regime) {
		case "crisis":      return "var(--netz-danger)";
		case "stress":      return "var(--netz-warning)";
		case "recovery":    return "var(--netz-info)";
		case "expansion":   return "var(--netz-success)";
		case "normal":      return "var(--netz-success)";
		default:            return "var(--netz-text-muted)";
	}
}

export function freshnessColor(status: string): string {
	switch (status) {
		case "fresh":    return "var(--netz-success)";
		case "decaying": return "var(--netz-warning)";
		case "stale":    return "var(--netz-danger)";
		default:         return "var(--netz-text-muted)";
	}
}
