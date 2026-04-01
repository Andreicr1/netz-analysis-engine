/** Model Portfolio domain types — maps 1:1 to backend schemas. */

export interface ModelPortfolio {
	id: string;
	profile: string;
	display_name: string;
	description: string | null;
	benchmark_composite: string | null;
	inception_date: string | null;
	backtest_start_date: string | null;
	inception_nav: number;
	status: string;
	fund_selection_schema: SelectionSchema | null;
	created_at: string;
	created_by: string | null;
}

export interface SelectionSchema {
	profile: string;
	total_weight: number;
	funds: InstrumentWeight[];
}

export interface InstrumentWeight {
	instrument_id: string;
	fund_name: string;
	instrument_type: "mutual_fund" | "etf" | "bdc" | "money_market" | "closed_end" | "interval_fund" | "ucits" | "private" | null;
	block_id: string;
	weight: number;
	score: number;
}

/** @deprecated Use SelectionSchema */
export type FundSelectionSchema = SelectionSchema;
/** @deprecated Use InstrumentWeight */
export type FundWeight = InstrumentWeight;

export interface BacktestFold {
	fold: number;
	sharpe: number | null;
	cvar_95: number | null;
	max_drawdown: number | null;
	n_obs: number;
}

export interface BacktestResult {
	mean_sharpe: number | null;
	std_sharpe: number | null;
	positive_folds: number;
	total_folds: number;
	youngest_fund_start: string | null;
	folds: BacktestFold[];
}

export interface StressScenario {
	name: string;
	start_date: string;
	end_date: string;
	portfolio_return: number;
	max_drawdown: number;
	recovery_days: number | null;
}

export interface StressResult {
	scenarios: StressScenario[];
}

export interface NAVPoint {
	date: string;
	nav: number;
	daily_return: number | null;
}

export interface TrackRecord {
	portfolio_id: string;
	profile: string;
	status: string;
	fund_selection: SelectionSchema | null;
	backtest: BacktestResult | null;
	nav_series: NAVPoint[] | null;
	live_nav: unknown;
	stress: StressResult | null;
}

export function scenarioLabel(name: string): string {
	const map: Record<string, string> = {
		"2008_gfc": "Global Financial Crisis (2008)",
		"2020_covid": "COVID-19 Crash (2020)",
		"2022_rate_hike": "Rate Hike Cycle (2022)",
		"taper_2013": "Taper Tantrum (2013)",
		"rate_shock_200bps": "Rate Shock +200bps",
	};
	return map[name] ?? name.replace(/_/g, " ");
}

export function optimizerStatusLabel(status: string): { label: string; description: string; severity: "success" | "warning" | "danger" } {
	const map: Record<string, { label: string; description: string; severity: "success" | "warning" | "danger" }> = {
		"optimal": {
			label: "Optimal",
			description: "Maximum risk-adjusted return found within all constraints",
			severity: "success",
		},
		"optimal:robust": {
			label: "Robust Optimal",
			description: "SOCP optimization applied \u2014 portfolio is resilient to estimation error in covariance matrix",
			severity: "success",
		},
		"optimal:cvar_constrained": {
			label: "CVaR-Constrained",
			description: "Variance-capped solution \u2014 CVaR constraint was binding, reducing expected return to meet risk limit",
			severity: "warning",
		},
		"optimal:min_variance_fallback": {
			label: "Min-Variance Fallback",
			description: "Minimum-variance portfolio \u2014 all higher-return phases exceeded CVaR limit",
			severity: "warning",
		},
		"optimal:cvar_violated": {
			label: "CVaR Limit Exceeded",
			description: "Warning: CVaR limit exceeded in all optimization phases. Consider adding diversifying funds or adjusting the profile.",
			severity: "danger",
		},
		"fallback:insufficient_fund_data": {
			label: "Heuristic Fallback",
			description: "Insufficient aligned trading data between funds \u2014 weights assigned by block-level heuristic, not optimizer",
			severity: "danger",
		},
	};
	return map[status] ?? { label: status.replace(/_/g, " "), description: "Optimizer status", severity: "warning" };
}

export interface PortfolioView {
	id: string;
	portfolio_id: string;
	asset_instrument_id: string | null;
	peer_instrument_id: string | null;
	view_type: "absolute" | "relative";
	expected_return: number;
	confidence: number;
	rationale: string | null;
	created_by: string | null;
	effective_from: string;
	effective_to: string | null;
	created_at: string;
}

/** Parametric stress test result from POST /stress-test */
export interface ParametricStressResult {
	portfolio_id: string;
	scenario_name: string;
	nav_impact_pct: number;
	cvar_stressed: number | null;
	block_impacts: Record<string, number>;
	worst_block: string | null;
	best_block: string | null;
}

/** Human-readable labels for allocation block IDs — re-exported from canonical source */
export { blockLabel } from "$lib/constants/blocks";

/** Holdings overlap analysis result from GET /model-portfolios/{id}/overlap */
export interface CusipExposure {
	cusip: string;
	issuer_name: string | null;
	total_exposure_pct: number;
	funds_holding: string[];
	is_breach: boolean;
}

export interface SectorExposure {
	sector: string;
	total_exposure_pct: number;
	cusip_count: number;
}

export interface OverlapResult {
	portfolio_id: string;
	computed_at: string;
	limit_pct: number;
	total_holdings: number;
	funds_analyzed: number;
	funds_without_data: number;
	top_cusip_exposures: CusipExposure[];
	sector_exposures: SectorExposure[];
	breaches: CusipExposure[];
	has_sufficient_data: boolean;
	data_warning: string | null;
}

export function profileColor(profile: string): string {
	switch (profile) {
		case "conservative": return "var(--ii-info)";
		case "moderate": return "var(--ii-warning)";
		case "growth": return "var(--ii-success)";
		default: return "var(--ii-text-secondary)";
	}
}

// ── Construction Advisor ────────────────────────────────────────────────

export interface BlockGap {
	block_id: string;
	display_name: string;
	asset_class: string;
	target_weight: number;
	current_weight: number;
	gap_weight: number;
	priority: number;
	reason: string;
}

export interface CoverageAnalysis {
	total_blocks: number;
	covered_blocks: number;
	covered_pct: number;
	block_gaps: BlockGap[];
}

export interface CandidateFund {
	block_id: string;
	instrument_id: string;
	name: string;
	ticker: string | null;
	strategy_label: string | null;
	volatility_1y: number | null;
	correlation_with_portfolio: number;
	overlap_pct: number;
	projected_cvar_95: number | null;
	cvar_improvement: number;
	in_universe: boolean;
	external_id: string;
	has_holdings_data: boolean;
}

export interface MinimumViableSet {
	funds: string[];
	projected_cvar_95: number;
	projected_within_limit: boolean;
	blocks_filled: string[];
	search_method: string;
}

export interface AlternativeProfile {
	profile: string;
	cvar_limit: number;
	current_cvar_would_pass: boolean;
}

export interface ConstructionAdvice {
	portfolio_id: string;
	profile: string;
	current_cvar_95: number;
	cvar_limit: number;
	cvar_gap: number;
	coverage: CoverageAnalysis;
	candidates: CandidateFund[];
	minimum_viable_set: MinimumViableSet | null;
	alternative_profiles: AlternativeProfile[];
	projected_cvar_is_heuristic: boolean;
}
