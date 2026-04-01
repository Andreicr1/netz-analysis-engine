/** Analytics domain types — Attribution, Drift, Correlation. */

export interface SectorAttribution {
	sector: string;
	block_id: string;
	allocation_effect: number;
	selection_effect: number;
	interaction_effect: number;
	total_effect: number;
}

export interface AttributionResult {
	profile: string;
	start_date: string;
	end_date: string;
	granularity: "monthly" | "quarterly";
	total_portfolio_return: number;
	total_benchmark_return: number;
	total_excess_return: number;
	allocation_total: number;
	selection_total: number;
	interaction_total: number;
	total_allocation_combined: number;
	sectors: SectorAttribution[];
	n_periods: number;
	benchmark_available: boolean;
	benchmark_approach: string;
}

export interface MetricDrift {
	metric_name: string;
	recent_mean: number;
	baseline_mean: number;
	baseline_std: number;
	z_score: number;
	is_anomalous: boolean;
}

export interface StrategyDriftAlert {
	alert_type: string;
	instrument_id: string;
	instrument_name: string;
	status: string;
	anomalous_count: number;
	total_metrics: number;
	metrics: MetricDrift[];
	severity: "none" | "moderate" | "severe";
	detected_at: string;
}

export interface ParetoResult {
	profile: string;
	recommended_weights: Record<string, number>;
	pareto_sharpe: number[];
	pareto_cvar: number[];
	n_solutions: number;
	seed: number;
	input_hash: string;
	status: string;
	job_id?: string;
}

export interface ConcentrationAnalysis {
	absorption_ratio: number;
	eigenvalues: number[];
	mp_threshold: number;
	n_signal_eigenvalues: number;
}

export interface CorrelationResult {
	profile: string;
	matrix: number[][];
	labels: string[];
	concentration: ConcentrationAnalysis;
}

export interface RollingCorrelation {
	dates: string[];
	values: number[];
	instrument_a: string;
	instrument_b: string;
}

export interface BacktestFoldResult {
	fold: number;
	sharpe: number | null;
	cvar_95: number | null;
	max_drawdown: number | null;
	n_obs: number;
	period_start?: string;
	period_end?: string;
}

export interface BacktestResult {
	mean_sharpe: number | null;
	std_sharpe: number | null;
	positive_folds: number;
	total_folds: number;
	folds: BacktestFoldResult[];
}

// ── Risk Budgeting (eVestment p.43-44) ──────────────────────────────

export interface FundRiskBudget {
	block_id: string;
	block_name: string;
	weight: number;
	mean_return: number;
	mctr: number | null;
	pctr: number | null;
	mcetl: number | null;
	pcetl: number | null;
	implied_return_vol: number | null;
	implied_return_etl: number | null;
	difference_vol: number | null;
	difference_etl: number | null;
}

export interface RiskBudgetResult {
	profile: string;
	portfolio_volatility: number;
	portfolio_etl: number;
	portfolio_starr: number | null;
	funds: FundRiskBudget[];
	as_of_date: string | null;
}

// ── Factor Analysis (eVestment p.46) ────────────────────────────────

export interface FactorContribution {
	factor_label: string;
	pct_contribution: number;
}

export interface FactorAnalysisResult {
	profile: string;
	systematic_risk_pct: number;
	specific_risk_pct: number;
	factor_contributions: FactorContribution[];
	r_squared: number;
	portfolio_factor_exposures: Record<string, number>;
	as_of_date: string | null;
}

// ── Monte Carlo Simulation ─────────────────────────────────────────

export interface MonteCarloConfidenceBar {
	horizon: string;
	horizon_days: number;
	pct_5: number;
	pct_10: number;
	pct_25: number;
	pct_50: number;
	pct_75: number;
	pct_90: number;
	pct_95: number;
	mean: number;
}

export interface MonteCarloResult {
	entity_id: string;
	entity_name: string;
	n_simulations: number;
	statistic: string;
	percentiles: Record<string, number>;
	mean: number;
	median: number;
	std: number;
	historical_value: number;
	confidence_bars: MonteCarloConfidenceBar[];
}

// ── Peer Group Rankings (eVestment Section IV) ────────────────────

export interface PeerRanking {
	metric_name: string;
	value: number | null;
	percentile: number;
	quartile: number;
	peer_count: number;
	peer_median: number;
	peer_p25: number;
	peer_p75: number;
}

export interface PeerGroupResult {
	entity_id: string;
	entity_name: string;
	strategy_label: string;
	peer_count: number;
	rankings: PeerRanking[];
	as_of_date: string | null;
}

// ── Active Share (eVestment p.73) ─────────────────────────────────

export interface ActiveShareResult {
	entity_id: string;
	entity_name: string;
	active_share: number;
	overlap: number;
	active_share_efficiency: number | null;
	n_portfolio_positions: number;
	n_benchmark_positions: number;
	n_common_positions: number;
	as_of_date: string | null;
}

export type Timeframe = "ytd" | "1y" | "3y" | "custom";

export function effectColor(value: number): string {
	if (value > 0.001) return "var(--ii-success)";
	if (value < -0.001) return "var(--ii-danger)";
	return "var(--ii-text-muted)";
}

export function severityColor(severity: string): string {
	switch (severity) {
		case "severe":   return "var(--ii-danger)";
		case "moderate": return "var(--ii-warning)";
		default:         return "var(--ii-success)";
	}
}
